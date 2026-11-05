# -*- coding: utf-8 -*-
"""단일 .kgpack을 사용하는 로컬 대화 UI.

    KG_ENCODER=문자 python views/kgpack_ui.py --pack NAI.kgpack --port 8766

pack은 읽기 전용이다. 자가학습으로 생긴 새 지식은 /private/tmp의 pack별 overlay에
쌓여, 대화 중에는 `pack + 새 지식`으로 읽힌다.
"""
from __future__ import annotations

import argparse
import base64
from collections import deque
from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import posixpath
import re
import sys
import threading
import time
from urllib.parse import urlparse

os.environ.setdefault("KG_ENCODER", "문자")
repo_root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(repo_root))

import engine  # noqa: E402
import encoder  # noqa: E402
import marco.learning.authoring as self_authoring  # noqa: E402
import marco.language.realizer.affect as affect_state  # noqa: E402
import marco.storage.conversations as conversation_store  # noqa: E402
import marco.knowledge.ingest.documents as document_kg  # noqa: E402
import goal_runtime  # noqa: E402
import marco.language.understanding as input_understanding  # noqa: E402
import marco.storage.kgpack as kgpack  # noqa: E402
import marco.knowledge.definitions as local_definitions  # noqa: E402
import marco.language.realizer.composer as response_composer  # noqa: E402
import marco.language.representation as semantic_parser  # noqa: E402
import marco.reasoning.state as state_engine  # noqa: E402
import marco.knowledge.ingest.web as web_learn  # noqa: E402
from encoder import _vec, split_fragments  # noqa: E402


manager_select = "__kg_manager__"


def score(body, cand, graph):
    chunks = list(split_fragments(body)) or [body]
    vecs = [_vec(x) for x in chunks]
    out = []
    for node in cand:
        if node in graph.get("vec", {}):
            out.append((node, max(float((graph["vec"][node] @ v).max()) for v in vecs)))
    return sorted(out, key=lambda x: -x[1])


def path(graph, start, end):
    if not start or start == end:
        return []
    seen, queue = {start: None}, deque([start])
    while queue:
        here = queue.popleft()
        for relation, nxt in graph["adj"].get(here, []):
            if relation not in engine.forward_rels(graph) or nxt in seen:
                continue
            seen[nxt] = (here, relation)
            if nxt == end:
                result, cursor = [], end
                while seen[cursor]:
                    prev, rel = seen[cursor]
                    result.append([prev, rel, cursor])
                    cursor = prev
                return list(reversed(result))
            queue.append(nxt)
    return []


def graph_shape(graph):
    requirements = set(engine.requirements(graph))
    evidence = set(graph.get("증거", []))
    nodes = {}
    for name in graph.get("공통층", {}):
        nodes[name] = "goal" if name == graph["목표"] else ("requirement" if name in requirements else "concept")
    for name in graph.get("사례층", {}):
        nodes.setdefault(name, "evidence" if name in evidence else "case")
    for name in graph.get("무관층", {}):
        nodes.setdefault(name, "irrelevant")
    edges = [[a, r, b] for a, r, b in graph.get("엣지", []) if a in nodes and b in nodes]
    node_rows = []
    for name, kind in nodes.items():
        examples = (graph.get("공통층", {}).get(name)
                    or graph.get("사례층", {}).get(name)
                    or graph.get("무관층", {}).get(name) or [])
        node_rows.append({"name": name, "kind": kind, "examples": list(examples),
                          "source": graph.get("출처", {}).get(name)})
    return {"nodes": node_rows,
            "edges": edges, "goal": graph.get("목표"),
            "requirements": sorted(requirements), "thresholds": graph.get("임계값", {})}


def manager_index(manager):
    graph = {"역할": manager.get("role", "노드 매니저"),
             "목표": manager.get("goal", "그래프고르기"),
             "임계값": {"A_MIN": 0.40, "OK_MIN": 0.50},
             "공통층": {n["path"]: list(n.get("examples") or [n["path"]])
                       for n in manager.get("nodes", [])},
             "사례층": {}, "무관층": {}, "엣지": [], "대사": {},
             "수치조건": {}, "adj": {}, "증거": []}
    graph["vec"] = engine._example_vecs(graph)
    return graph


def manager_shape(manager):
    goal = manager.get("goal", "그래프고르기")
    nodes = [{"name": goal, "kind": "goal", "examples": ["질문에 알맞은 KG 선택"],
              "source": "kgpack manifest"}]
    nodes += [{"name": n["path"], "kind": "concept",
               # 자가학습이 방금 들인 것. 화면에서 뿅 튀어 붙게 표시만 한다.
               "new": bool(n.get("new")),
               # 매니저 3D 화면은 그래프 이름과 선택 경로만 쓴다. 모든 별칭을
               # 매 턴 JSON에 싣는 것은 수십 개 KG에서 응답을 수 MB로 키워 UI를
               # 멈추게 한다. 실제 선택된 그래프의 예시는 아래 ``graph``에만 둔다.
               "examples": [],
               "source": "%s · 목표 %s" % (n.get("role") or "역할 없음", n.get("goal") or "없음")}
              for n in manager.get("nodes", [])]
    return {"nodes": nodes, "edges": list(manager.get("edges") or []), "goal": goal,
            "requirements": [], "thresholds": {"route_min": 0.45}}


def markdown_answer(answer, trace):
    """완결된 지식 문장을 읽기 좋은 문서로 보여준다."""
    if not trace or trace.get("mode") != "self_learning" or not trace.get("winner"):
        return answer
    topic = trace["winner"].removeprefix("지식_")
    return "## %s\n\n%s" % (topic, answer)


def web_grounds_answer(research, refusals):
    """생성 요약 대신 원문 완결 문장으로 답한다. 출처 없는 문장을 만들지 않는다."""
    sources = research.get("sources") or []
    if not sources:
        return refusals["web_no_source"]
    parts = [refusals["web_heading"], refusals["web_intro"]]
    for source in sources:
        heading = source.get("title") or source.get("domain") or refusals["web_source_heading"]
        parts.append("### %s\n%s: %s\n\n> %s" % (heading, refusals["web_source_line"], source.get("url", ""),
                     " ".join(source.get("sentences") or [])))
    return "\n\n".join(parts)


def session_state(session):
    secured = session.secured()
    return {"secured": secured, "self_counter": sorted(session.self_blame),
            "turn": session.turn_no,
            "result": session.result(), "learned_phrases": [list(x) for x in session.learned]}


def question_passage(question):
    """독립 질문만 KG별로 나눈다. 앞 문장은 흔히 뒤 질문의 상황 조건이다."""
    # "배가 뜬다. 수면이 오른다. 몇 칸인가?"의 앞 두 문장을 별도 질의로
    # 보내면 엉뚱한 KG 여러 개가 선택된다. 물음표가 하나면 한 상황 모델이다.
    if len(re.findall(r"[?？]", question)) <= 1:
        return [question.strip()]
    parts = []
    for raw in re.split(r"(?:\r?\n+|(?<=[.!?。！？])\s+|\s+(?:그리고|또한|동시에|한편)\s+)", question):
        part = re.sub(r"^(?:그리고|또한|동시에|한편)\s+", "", raw.strip(" ,;:\t"))
        if part:
            parts.append(part)
    return parts or [question]


def merge_shape(items):
    """여러 KG의 얼개를 이름공간으로 묶어 한 화면에서 충돌 없이 보여준다."""
    nodes, edges = [], []
    multi_goal = "다중KG응답완료"
    for item in items:
        prefix = item["graph"].removeprefix("graphs/").removesuffix(".kg")
        shape = item["shape"]
        for n in shape["nodes"]:
            nodes.append(dict(n, name=prefix + "::" + n["name"]))
        for a, relation, b in shape["edges"]:
            edges.append([prefix + "::" + a, relation, prefix + "::" + b])
        if shape.get("goal"):
            edges.append([prefix + "::" + shape["goal"], "충족", multi_goal])
    nodes.append({"name": multi_goal, "kind": "goal", "examples": ["여러 KG의 답을 함께 사용"],
                  "source": "노드 매니저"})
    return {"nodes": nodes, "edges": edges, "goal": multi_goal,
            "requirements": [], "thresholds": {}}


def merge_trace(items, route):
    activated, path, subtraces = [], [], []
    for item in items:
        prefix = item["graph"].removeprefix("graphs/").removesuffix(".kg")
        trace = item.get("trace") or {}
        subtraces.append({"graph": item["graph"], "question": item["question"], "trace": trace})
        activated += [prefix + "::" + n for n in trace.get("activated", [])]
        path += [[prefix + "::" + a, relation, prefix + "::" + b]
                 for a, relation, b in trace.get("path", [])]
        if item["shape"].get("goal"):
            goal = prefix + "::" + item["shape"]["goal"]
            activated.append(goal)
            path.append([goal, "충족", "다중KG응답완료"])
    activated.append("다중KG응답완료")
    return {"mode": "multi", "question": " / ".join(x["question"] for x in items),
            "winner": "다중KG응답완료", "verdict": "다중KG",
            "rankings": [], "null_rankings": [], "margin": None,
            "activated": list(dict.fromkeys(activated)), "path": path,
            "subtraces": subtraces, "route": route}


class AppState:
    def __init__(self, pack_path, overlay_root=None, graph_overlay=None, *, conversations=None, learning_root=None):
        # graph_overlay: an attached overlay store (marco.storage.graph_view.OverlayAttachment) of
        # explicit or approved changes, or None. With None, nothing of it runs (docs/architecture/overlay.md).
        self.graph_overlay, self._graph_texts = None, {}
        self.pack_path = Path(pack_path).resolve()
        self.manifest, self.data = kgpack.read(self.pack_path)
        from pack_model import PackModel
        self.model = PackModel(self.manifest, self.data)
        self.language_pack = self.model.language
        from pack_model import companion_models
        # 같은 팩의 다른 언어. 그 언어로 온 물음을 이 대화의 상태에 맞춰 답한다.
        self.companions = companion_models(self.manifest, self.data)
        self.manager = self.manifest["manager"]
        with self.model.encoder.activate():
            self.manager_index = manager_index(self.manager)
        self.graphs = sorted(x["path"] for x in self.manifest["files"]
                           if x.get("kind") == "graph")
        if not self.graphs:
            raise kgpack.KGPackError("pack 안에 그래프가 없습니다")
        pack_id = hashlib.sha256(self.pack_path.read_bytes()).hexdigest()[:16]
        if graph_overlay is not None:   # its own working folder: its graph files differ from the pack's
            pack_id += "-overlay-" + hashlib.sha256(str(Path(graph_overlay.path).resolve()).encode()).hexdigest()[:12]
        self.overlay = Path(overlay_root or "/private/tmp/nai-kgpack-overlay") / pack_id
        self.overlay.mkdir(parents=True, exist_ok=True)
        overlay_resolved = self.overlay.resolve()
        self.learning_root = (Path(learning_root).resolve() if learning_root is not None
                              else (self.overlay / "learning").resolve())
        try:
            self.learning_root.relative_to(overlay_resolved)
        except ValueError:
            raise ValueError("learning_root must be at or below the pack overlay directory") from None
        self.lock = threading.RLock()
        self.auto_graph = next((x for x in self.graphs if x.endswith("graph_자가학습.kg")), None)
        self.situation_graph = next((x for x in self.graphs if x.endswith("graph_일상추론.kg")), None)
        self.selected = manager_select
        self.active_name = self.route = None
        self.routed_graphs, self.combined_shape = [], None
        self.graph = self.session = self.graph_path = None
        self.history = []
        # KG 대화 이력과 분리된다. key는 브라우저 탭이 만든 불투명 세션 식별자다.
        self.understanding_history = {}
        self.reasoning_contexts = {}
        self.action_grounding_states = {}
        # 정서 표현 상태는 브라우저 세션마다 분리하고 메모리에만 둔다.
        # KG, overlay, 승인 기록의 내용·판정에는 절대 섞지 않는다.
        self.affect_sessions = {}
        self.project_roots = {}
        self.document_history = {}
        self.conversations = (conversations if conversations is not None
                              else conversation_store.ConversationStore(repo_root / ".marco" / "state" / "conversations.json"))
        # 정의문도 응답 근거다. 호스트 저장소의 자료를 대체물로 읽으면 같은
        # pack이 실행 위치에 따라 다른 답을 낸다. 팩에 없는 선택 기능은 빈
        # 경로로 두어 정의 응답만 비활성화한다.
        definition_asset = "data/위키/정의문.jsonl"
        definition_source = (self._materialize(definition_asset)
                             if definition_asset in self.data
                             else self.overlay / definition_asset)
        self.definitions = local_definitions.DefinitionLookup(definition_source,
                                                               self.overlay / ".definition-index.sqlite")
        self.goals = goal_runtime.GoalRuntime(repo_root)
        # 모델은 답변기가 아니다. 이 객체는 모델 후보를 검증된 상태 JSON으로
        # 축소하는 경계이며, 테스트는 CallableBackend를 주입해 모델 품질과
        # 상태 계산을 독립적으로 검사한다.
        self.semantic_parser = semantic_parser.SemanticParser(model=self.model)
        if graph_overlay is not None:
            self._attach_graph_overlay(graph_overlay)

    def _materialize(self, name):
        """pack의 그래프와 그 ``포함:`` 의존성을 overlay에 함께 펼친다.

        엔진은 include를 현재 파일의 상대 경로로 직접 연다. 선택된 그래프만
        풀면 pack 안에 있어도 포함 그래프가 없어서 ``FileNotFoundError``가
        난다. 의존성도 같은 상대 경로에 써야 엔진의 경로 규칙과 일치한다.
        """
        if name not in self.data:
            raise kgpack.KGPackError("pack에 없는 파일입니다: %s" % name)
        pending, seen = [name], set()
        while pending:
            current = pending.pop()
            if current in seen:
                continue
            seen.add(current)
            target = self.overlay / current
            target.parent.mkdir(parents=True, exist_ok=True)
            body = self.data[current]
            if current in self._graph_texts:        # a graph an attached overlay changes: the merged view's text
                body = self._graph_texts[current]
            # 학습·수집 overlay는 팩을 연 뒤에 새 기록을 더할 수 있다. 다시
            # materialize할 때 그 기록을 초깃값으로 덮어쓰지 않는다.
            learned_overlay = current.endswith((".학습.jsonl", ".수집.jsonl"))
            if not target.exists() or (not learned_overlay and target.read_bytes() != body):
                temp = target.with_name(target.name + ".tmp-%d" % os.getpid())
                try:
                    temp.write_bytes(body)
                    os.replace(temp, target)
                finally:
                    try:
                        temp.unlink()
                    except FileNotFoundError:
                        pass
            if not current.endswith(".kg"):
                continue
            learned = current[:-3] + ".학습.jsonl"
            if learned in self.data:
                pending.append(learned)
            collected = current[:-3] + ".수집.jsonl"
            if collected in self.data:
                pending.append(collected)
            for line in body.decode("utf-8").splitlines():
                line = line.split("#", 1)[0].strip()
                if not line.startswith("포함:"):
                    continue
                for raw in line.split(":", 1)[1].split(","):
                    raw = raw.strip()
                    if not raw or os.path.isabs(raw):
                        raise kgpack.KGPackError("안전하지 않은 포함 경로: %s" % raw)
                    child = posixpath.normpath(posixpath.join(posixpath.dirname(current), raw))
                    if child not in self.data:
                        raise kgpack.KGPackError("pack에 없는 포함 파일: %s (from %s)" % (raw, current))
                    pending.append(child)
        return self.overlay / name

    def _packed_evidence(self, subject):
        """팩에 든 승인 수집 기록에서 정확한 주제의 원문 문장만 꺼낸다."""
        normal = lambda value: re.sub(r"\s+", "", str(value or "")).lower()
        target = normal(subject)
        if not target:
            return []
        # 한 출처의 긴 문서가 뒤 출처의 근거를 밀어내지 않게, 수집 후보도
        # 출처별로 고르게 남긴다. 화면 답변은 그보다 작은 상한을 다시 적용한다.
        by_source, source_order, seen = {}, [], set()
        plan_markers = self.language_pack.get("response_composition", {}).get("plan_markers", [])
        # 요청 대상에는 목표 말이 덧붙을 수 있다. `공책 정리 계획`의 근거
        # 주제는 `공책`이지만, 목표 전체 `공책 정리`는 계획 선택에 남겨야 한다.
        # 팩에 선언된 별칭 중 하나가 앞부분을 유일하게 채울 때만 원문 근거를
        # 찾는다. 임의의 낱말 분해나 부분 일치로 다른 주제를 섞지 않는다.
        aliases_in_pack = set()
        for path, body in self.data.items():
            if not path.endswith(".수집.jsonl"):
                continue
            for raw in body.decode("utf-8", "replace").splitlines():
                try:
                    record = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                aliases_in_pack.update(normal(alias) for alias in
                                       (record.get("주제별칭") or [record.get("주제")]) if normal(alias))
        exact = {alias for alias in aliases_in_pack if alias == target}
        prefixes = {alias for alias in aliases_in_pack
                    if len(alias) >= 2 and target.startswith(alias)}
        best_prefixes = ({alias for alias in prefixes
                          if len(alias) == max(map(len, prefixes))} if prefixes else set())
        accepted_aliases = exact or (best_prefixes if len(best_prefixes) == 1 else set())
        for path, body in sorted(self.data.items()):
            if not path.endswith(".수집.jsonl"):
                continue
            for raw in body.decode("utf-8", "replace").splitlines():
                try:
                    record = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                aliases = record.get("주제별칭") or [record.get("주제")]
                if not accepted_aliases.intersection(normal(alias) for alias in aliases):
                    continue
                source = str(record.get("URL") or record.get("출처") or "").strip()
                claims = record.get("claims", record.get("주장들"))
                rows = claims if isinstance(claims, list) else [
                    {"text": sentence} for sentence in record.get("문장들") or []]
                for index, claim in enumerate(rows):
                    if not isinstance(claim, dict):
                        continue
                    text = str(claim.get("text", claim.get("문장", "")) or "").strip()
                    key = (text, source)
                    if text and source and key not in seen:
                        attributes = claim.get("attributes", claim.get("속성", {}))
                        attributes = attributes if isinstance(attributes, dict) else {}
                        depends = claim.get("depends_on", claim.get("선행", []))
                        depends = depends if isinstance(depends, list) else []
                        if source not in by_source:
                            by_source[source] = []
                            source_order.append(source)
                        if len(by_source[source]) < 8:
                            by_source[source].append({"text": text, "source": source,
                                "id": str(claim.get("id") or "%s:%d" % (source, index)),
                                "relation": str(claim.get("relation", claim.get("관계", "")) or ""),
                                "attributes": attributes, "depends_on": depends,
                                "achieves": claim.get("achieves", claim.get("달성", [])),
                                "requires_state": claim.get("requires_state", claim.get("상태전제", [])),
                                "effects": claim.get("effects", claim.get("결과상태", [])),
                                "actionable": bool(claim.get("actionable", claim.get("실행", False)))
                                if claims is not None else any(marker in text for marker in plan_markers)})
                        seen.add(key)
        evidence = []
        for item_index in range(8):
            for source in source_order:
                rows = by_source[source]
                if item_index < len(rows):
                    evidence.append(rows[item_index])
                    if len(evidence) == 32:
                        return evidence
        return evidence

    # --- Persistent Overlay Infrastructure (docs/architecture/overlay.md) ---------------------
    # Reached only with an overlay store attached. It applies changes that were committed or
    # approved from outside through an explicit call; nothing here makes or approves a change.

    def _attach_graph_overlay(self, attachment):
        from marco.storage.graph_view import PackBase, pack_content_sha256
        from marco.storage.overlay import OverlayBaseMismatch
        content = pack_content_sha256(self.manifest)
        if attachment.base_sha256 != content:
            raise OverlayBaseMismatch("overlay %s is bound to base %s, not this pack (%s); refused"
                                      % (attachment.path, attachment.base_sha256, content))
        self.graph_overlay = attachment
        self.graph_view = None
        self._overlay_base = PackBase(self.manifest, self.data)
        self._overlay_applied = (0, None)
        self._base_manager_nodes = {n["path"]: n for n in self.manager.get("nodes", [])}
        self._sync_graph_overlay()

    def _include_closure(self, name):
        """``name`` and every graph it includes (``포함:``), as ``_materialize`` follows them."""
        out, pending = set(), [name]
        while pending:
            current = pending.pop()
            if current in out or current not in self.data:
                continue
            out.add(current)
            body = self._graph_texts.get(current, self.data[current])
            for line in body.decode("utf-8").splitlines():
                line = line.split("#", 1)[0].strip()
                if line.startswith("포함:"):
                    pending += [posixpath.normpath(posixpath.join(posixpath.dirname(current), raw.strip()))
                                for raw in line.split(":", 1)[1].split(",") if raw.strip()]
        return out

    def _sync_graph_overlay(self):
        """Apply the attached overlay at its head when the head moved since the last application.

        Re-written: the working-folder file of every graph whose merged text changed (and the
        pack's own bytes again for a graph no longer changed); the graph-selection entries of
        those graphs; the rules (``PackModel.apply_rule_overlay``); the active graph if its
        include closure changed. Every open reasoning context is re-derived from its own
        snapshot without the saved replay. A conversation store bound to its base
        (``conversations.binding``) records the head each saved state was derived under.
        Returns whether anything was applied."""
        head = self.graph_overlay.head()
        if head != self._overlay_applied and self._action_grounding_native():
            return self._action_grounding_sync_native(head)
        if head == self._overlay_applied:
            self._bind_overlay_head()
            return False
        view = self.graph_overlay.view(self._overlay_base, at=head[0])
        texts = {self._overlay_base.member(g): view.text(g).encode("utf-8") for g in view.touched_graphs()}
        rules = view.rule_changes()
        changed = {n for n in set(texts) | set(self._graph_texts) if texts.get(n) != self._graph_texts.get(n)}
        self._graph_texts, self.graph_view = texts, view
        for name in sorted(changed):
            if (self.overlay / name).exists():
                self._materialize(name)
        if changed:
            nodes = []
            for node in self.manager.get("nodes", []):
                path = node.get("path")
                if path in texts:
                    node = dict(kgpack._graph_meta(path, texts[path]), **({"new": node["new"]} if "new" in node else {}))
                elif path in changed:
                    node = self._base_manager_nodes.get(path, node)
                nodes.append(node)
            self.manager = dict(self.manager, nodes=nodes)
            self.manager_index = manager_index(self.manager)
        key = "%d:%s" % head if rules else None
        for model in [self.model] + list(self.companions):
            model.apply_rule_overlay(rules or None, key)
        if self.active_name and self.graph is not None and changed & self._include_closure(self.active_name):
            self._activate(self.active_name, force=True)
        if self.reasoning_contexts:
            from marco.reasoning.context import ReasoningContext
            for context_id, context in list(self.reasoning_contexts.items()):
                saved = {k: v for k, v in context.snapshot().items() if k != "replay"}
                fresh = ReasoningContext(model=self.model, companions=self.companions)
                fresh.restore(saved)
                self.reasoning_contexts[context_id] = fresh
        self._overlay_applied = head
        self._bind_overlay_head()
        return True

    def _bind_overlay_head(self):
        binding = getattr(self.conversations, "binding", None)
        if isinstance(binding, dict):
            binding["overlay"] = {"seq": self._overlay_applied[0], "change_id": self._overlay_applied[1]}

    def _saved_reasoning_state(self, saved):
        """A saved reasoning state to restore. A store bound to its base has already compared the head
        the state was saved under with the current one and dropped a stale replay. An unbound store
        cannot tell, so with an attached overlay that has changes the saved replay is dropped and the
        conversation is re-derived under the current view."""
        if (saved is None or self.graph_overlay is None or not self._overlay_applied[0]
                or isinstance(getattr(self.conversations, "binding", None), dict)):
            return saved
        return {k: v for k, v in saved.items() if k != "replay"}

    def _overlay_origins(self, answer):
        """Mark the trace's graph evidence that comes from the overlay with its change and approver.
        Base items get no mark, so their evidence is as it was."""
        trace = answer.get("trace") if isinstance(answer, dict) else None
        view = getattr(self, "graph_view", None)
        if not isinstance(trace, dict) or view is None or not view.seq:
            return
        edges, nodes = [], {}
        items = [(trace, self.active_name, "")]
        for sub in trace.get("subtraces") or []:
            name = sub.get("graph") or ""
            items.append((sub.get("trace") or {}, name, name.removeprefix("graphs/").removesuffix(".kg") + "::"))
        for sub, name, prefix in items:
            if not name or name not in self.data:
                continue
            for edge in sub.get("path") or []:
                origin = view.edge_origin(name, *edge) if len(edge) == 3 else None
                if origin and origin["kind"] == "overlay":
                    edges.append([prefix + edge[0], edge[1], prefix + edge[2], origin])
            evidence = (sub.get("evidence") or {}).get("name") if isinstance(sub.get("evidence"), dict) else None
            for node in [evidence, sub.get("winner")] + list(sub.get("activated") or []):
                origin = view.node_origin(name, node) if isinstance(node, str) else None
                if origin and origin["kind"] == "overlay":
                    nodes[prefix + node] = origin
        trace["origins"] = {"overlay_seq": view.seq, "overlay_change": view.change_id, "edges": edges, "nodes": nodes}

    def export_pack(self, output_path):
        """현재 팩과 승인된 overlay 학습을 새 읽기 전용 팩으로 묶는다.

        원래 팩은 건드리지 않는다. overlay의 그래프 옆 학습·수집 JSONL만
        추가 대상으로 인정하므로 대화 로그·문서·임시 색인이 새 팩에 섞이지
        않는다.
        """
        output = Path(output_path).expanduser().resolve()
        if self.graph_overlay is not None:
            raise ValueError("an attached overlay is not exported into a pack: consolidation into a new base "
                             "is not part of the overlay infrastructure (docs/architecture/overlay.md)")
        if output.exists():
            raise ValueError("내보낼 팩 파일이 이미 있습니다: %s" % output)
        with self.lock:
            for name in sorted(self.data):
                self._materialize(name)
            names = set(self.data)
            graph_root = self.overlay / "graphs"
            if graph_root.exists():
                for candidate in graph_root.rglob("*"):
                    if candidate.is_file() and candidate.name.endswith((".학습.jsonl", ".수집.jsonl")):
                        names.add(candidate.relative_to(self.overlay).as_posix())
            files = [self.overlay / name for name in sorted(names)]
            manifest = kgpack.write_pack(output, files, root=self.overlay)
        return {"path": str(output), "files": [item["path"] for item in manifest["files"]],
                "fingerprint": self.model.fingerprint}

    @property
    def self_learning(self):
        return bool(self.active_name and self.active_name.endswith("graph_자가학습.kg"))

    @property
    def routing(self):
        return self.selected == manager_select

    def _activate(self, name, force=False):
        if name not in self.graphs:
            raise ValueError("pack에 없는 그래프입니다")
        if not force and self.active_name == name and self.graph is not None:
            return
        with self.model.encoder.activate():
            self.active_name = name
            self.graph_path = self._materialize(name)
            self.graph = (web_learn.load(str(self.graph_path))
                          if name.endswith("graph_자가학습.kg") else engine.load(str(self.graph_path)))
            self.session = None if name.endswith("graph_자가학습.kg") else engine.Session(self.graph)

    def _clear_manager_route(self):
        """매니저 모드의 이번 턴이 어떤 KG도 쓰지 않았음을 명시한다."""
        if self.routing:
            self.active_name = self.graph = self.session = self.graph_path = None
            self.routed_graphs, self.combined_shape = [], None

    def select(self, name):
        with self.lock, self.model.encoder.activate():
            self.selected = name
            self.route = None
            self.routed_graphs, self.combined_shape = [], None
            if name == manager_select:
                self.active_name = None
                self.graph = self.session = self.graph_path = None
            else:
                self._activate(name, force=True)
            self.history = []
            return self.info()

    def info(self):
        records = (web_learn.read_collected(web_learn.collect_path(str(self.graph_path)))
                   if self.self_learning else [])
        accepted = [r for r in records if r.get("수집형식") == 3 and r.get("문장들")
                    and web_learn.topic_related(r.get("주제"), r.get("본문"))]
        multi = self.routing and len(self.routed_graphs) > 1
        role = (("노드 매니저 → %d개 KG" % len(self.routed_graphs)) if multi else
                (("노드 매니저 → " + (self.graph.get("역할") or "역할 없음")) if self.routing and self.graph
                else (self.manager.get("role") if self.routing else self.graph.get("역할")))
                )
        goal = (self.combined_shape["goal"] if self.combined_shape else
                (self.graph.get("목표") if self.graph else self.manager.get("goal")))
        single_self = self.self_learning and not multi
        return {
            "pack": self.pack_path.name,
            "pack_path": str(self.pack_path),
            "graphs": self.graphs,
            "selected": self.selected,
            "manager_selection": manager_select,
            "routing_mode": self.routing,
            "routed_graph": self.routed_graphs[0] if self.routing and self.routed_graphs else None,
            "routed_graphs": list(self.routed_graphs),
            "multi_route": multi,
            "route": self.route,
            "role": role,
            "goal": goal,
            "evidence": list(self.graph.get("증거", [])) if self.graph else [],
            "self_learning": single_self,
            "overlay": str(self.overlay),
            "learned_records": len(accepted),
            "rejected_records": len(records) - len(accepted),
            "manager_graph": manager_shape(self.manager),
            "graph": (self.combined_shape or (graph_shape(self.graph) if self.graph else
                      {"nodes": [], "edges": [], "goal": "KG선택대기",
                       "requirements": [], "thresholds": {}})),
            "dialogue": list(self.history),
            "session": None if single_self or multi or not self.session else session_state(self.session),
        }

    def reset(self):
        with self.lock, self.model.encoder.activate():
            if self.routing:
                self.active_name = self.route = None
                self.routed_graphs, self.combined_shape = [], None
                self.graph = self.session = self.graph_path = None
            elif not self.self_learning:
                self.session = engine.Session(self.graph)
            self.history = []
            if self._action_grounding_native():
                self.reasoning_contexts = {}
                self.action_grounding_states = {}
            return self.info()

    def understand(self, text, session_id):
        """입력 분석 전용 경로: KG·검색·overlay·답변 엔진을 전혀 호출하지 않는다."""
        text = (text or "").strip()
        if not text:
            raise ValueError("입력이 비어 있습니다")
        session_id = str(session_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", session_id):
            raise ValueError("유효하지 않은 브라우저 세션입니다")
        with self.lock, self.model.encoder.activate():
            history = self.understanding_history.setdefault(session_id, [])
            result = input_understanding.understand(text, history, language_pack=self.language_pack)
            history.append(result)
            # 문맥 후보만 필요하므로 탭별 최근 30턴으로 한정한다.
            del history[:-30]
            return {"understanding": result, "history_count": len(history),
                    "session": session_id, "mode": "understanding_only"}

    def reset_understanding(self, session_id, conversation_id=None):
        session_id = str(session_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", session_id):
            raise ValueError("유효하지 않은 브라우저 세션입니다")
        with self.lock, self.model.encoder.activate():
            self.understanding_history.pop("chat_" + str(conversation_id) if conversation_id else session_id, None)
        return {"session": session_id, "history_count": 0, "mode": "understanding_only"}

    def save_semantic_correction(self, session_id, raw, semantic_parse, verification):
        """사용자가 명시적으로 승인한 구조화 해석만 학습 후보로 보관한다."""
        session_id = str(session_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", session_id):
            raise ValueError("유효하지 않은 브라우저 세션입니다")
        if not isinstance(semantic_parse, dict) or not semantic_parse.get("accepted"):
            raise ValueError("검증된 의미 JSON만 학습 후보로 승인할 수 있습니다")
        record = {"schema": semantic_parser.SCHEMA_VERSION, "raw": str(raw or ""),
                  "semantic_parse": semantic_parse, "verification": verification or {},
                  "model": semantic_parse.get("model"), "approved_at": __import__("time").time(),
                  "session": session_id}
        target = self.overlay / "semantic_corrections.jsonl"
        with self.lock:
            with target.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return {"saved": True, "path": str(target), "model": record["model"]}

    def project(self, session_id, path=None, conversation_id=None):
        """사용자가 선언한 세션별 작업 루트. 계획 밖 경로 접근은 런타임이 거절한다."""
        session_id = str(session_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", session_id):
            raise ValueError("유효하지 않은 브라우저 세션입니다")
        with self.lock:
            if path is not None:
                candidate = Path(str(path)).expanduser().resolve()
                if candidate == candidate.anchor or not candidate.is_dir():
                    raise ValueError("존재하는 프로젝트 폴더를 지정해 주세요")
                self.project_roots[session_id] = candidate
                if conversation_id:
                    self.conversations.set_project_root(str(conversation_id), candidate)
            saved = self.conversations.project_root(str(conversation_id or ""))
            root = Path(saved) if saved else self.project_roots.get(session_id, repo_root)
            return {"session": session_id, "project_root": str(root), "declared": session_id in self.project_roots}

    def conversations_api(self, action="list", project_id=None, chat_id=None, name=None):
        """프로젝트별 대화와 일반 대화를 로컬 파일에서만 다룬다."""
        with self.lock:
            if action == "list":
                return self.conversations.overview()
            if action == "create_project":
                project = self.conversations.create_project(name)
                chat = self.conversations.create_chat(project["id"])
                return {"project": project, "chat": chat, "overview": self.conversations.overview()}
            if action == "create_chat":
                chat = self.conversations.create_chat(project_id)
                return {"chat": chat, "overview": self.conversations.overview()}
            if action == "select":
                return {"chat": self.conversations.get_chat(chat_id), "overview": self.conversations.overview()}
            raise ValueError("알 수 없는 대화 작업입니다")

    def document(self, session_id, filename, content_b64):
        """사용자가 올린 PDF/PPTX를 세션 overlay에서만 분석·학습한다.

        문서 안의 지시문은 데이터일 뿐 API 호출이나 명령 실행 권한이 아니다.
        충분히 읽힌 주장만 JSON 그래프에 기록하고, 원본도 pack에는 절대 넣지 않는다.
        """
        session_id = str(session_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", session_id):
            raise ValueError("유효하지 않은 브라우저 세션입니다")
        safe_name = Path(str(filename or "document")).name
        if Path(safe_name).suffix.lower() not in (".pdf", ".pptx"):
            raise ValueError("PDF 또는 PPTX 파일만 분석할 수 있습니다")
        try:
            raw = base64.b64decode(str(content_b64 or ""), validate=True)
        except ValueError as exc:
            raise ValueError("문서 데이터가 올바르지 않습니다") from exc
        if not raw or len(raw) > 20 * 1024 * 1024:
            raise ValueError("문서는 20MB 이하의 비어 있지 않은 파일이어야 합니다")
        digest = hashlib.sha256(raw).hexdigest()[:16]
        folder = self.overlay / "documents" / session_id / digest
        folder.mkdir(parents=True, exist_ok=True)
        source = folder / safe_name
        temporary = source.with_name(source.name + ".tmp-%d" % os.getpid())
        try:
            temporary.write_bytes(raw)
            os.replace(temporary, source)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
        result = document_kg.learn(source, folder / "knowledge.graph.json")
        analysis = result["analysis"]
        response = {"session": session_id, "filename": safe_name, "document_id": digest,
                    "status": analysis["status"], "analysis": analysis,
                    "graph_saved": result["saved"], "graph_shape": None}
        if result["saved"]:
            graph = engine.load(result["saved"])
            response["graph_shape"] = graph_shape(graph)
        with self.lock:
            history = self.document_history.setdefault(session_id, [])
            history.append({"document_id": digest, "filename": safe_name,
                            "status": analysis["status"], "graph_saved": result["saved"]})
            del history[:-12]
        return response

    def affect(self, session_id, enabled=None, conversation_id=None):
        """정서 표현 토글의 세션 상태만 읽거나 바꾼다."""
        session_id = str(session_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", session_id):
            raise ValueError("유효하지 않은 브라우저 세션입니다")
        with self.lock:
            context_id = "chat_" + str(conversation_id) if conversation_id else session_id
            state = dict(self.affect_sessions.get(context_id) or affect_state.initial())
            if enabled is not None:
                state["enabled"] = bool(enabled)
                state["mode"] = "neutral"
                state["signals"] = []
                state["note"] = ("정서 표현을 켰습니다. 사실 판단은 바뀌지 않습니다."
                                 if state["enabled"] else "정서 표현은 꺼져 있습니다.")
                self.affect_sessions[context_id] = state
            return {"session": session_id, "affect": state}

    def _said(self, meaning, text):
        """A hold the UI gives itself, said through the language seam from its meaning (goal W2):
        the pack's sentence ``text`` is kept only if the realizer has no plan for the meaning."""
        from marco.language import realize
        return realize({"answer": text, "meaning": meaning}, "unresolved", self.model)

    def _with_affect(self, payload, state):
        """정서 표현은 답변의 접두 표현만 바꾸고 사실 내용을 보존한다."""
        payload["affect"] = state
        answer = payload.get("answer")
        if isinstance(answer, dict) and isinstance(answer.get("answer"), str):
            answer = dict(answer)
            raw_answer = answer["answer"]
            raw_markdown = answer.get("answer_markdown") or raw_answer
            if answer.get("known"):
                formatted = self.model.format_output((answer.get("trace") or {}).get("question", ""), raw_answer)
                if formatted != raw_answer:
                    answer["answer"] = answer["answer_markdown"] = formatted
                    answer["output_contract"] = "number_only"
                    payload["answer"] = answer
                    return payload
            answer["answer"] = affect_state.decorate(raw_answer, state, language_pack=self.language_pack)
            answer["answer_markdown"] = affect_state.decorate(raw_markdown, state, language_pack=self.language_pack)
            payload["answer"] = answer
        return payload

    def turn(self, text, session_id, approval_mode="risk", conversation_id=None):
        """목적 수행 턴. 승인 전에는 읽기 전용 KG·웹 조사만 한다."""
        session_id = str(session_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", session_id):
            raise ValueError("유효하지 않은 브라우저 세션입니다")
        if approval_mode not in ("risk", "all_steps"):
            raise ValueError("알 수 없는 승인 모드입니다")
        with self.lock, self.model.encoder.activate():
            native_entry = self._action_grounding_capture_entry()
            try:
                if self.graph_overlay is not None:
                    self._sync_graph_overlay()
                if conversation_id:
                    self.conversations.get_chat(str(conversation_id))
            except BaseException:
                try:
                    self._action_grounding_restore_entry(native_entry)
                finally:
                    pass
                raise
            context_id = "chat_" + str(conversation_id) if conversation_id else session_id
            prior_context_snapshot = None
            action_tx = None
            life = {'archive': None, 'attempt': None, 'memory': None, 'tx22': None, 'hook': None,
                    'native_result': None, 'native_completed': False, 'save_attempted': False,
                    'save_completed': False, 'terminal_started': False, 'stage': 'begin',
                    'error': None, 'prov': None, 'persist': [], 'gap': None}
            def finish(payload):
                answer = payload.get("answer")
                if self.graph_overlay is not None:
                    self._overlay_origins(answer)
                output = ((answer.get("answer_markdown") or answer.get("answer") or "") if isinstance(answer, dict)
                          else (payload.get("web_answer") or "계획을 만들었습니다. 승인 전에는 실행하지 않습니다."))
                attempt = life['attempt']
                b_post = attempt is not None and life['native_completed']
                recorder = life['archive']['recorder'] if attempt is not None else None
                if attempt is not None:
                    life['stage'] = 'output'
                    question = life['prov'].get('meaning_question') if life['prov'] is not None else None
                    if question is not None:
                        span = question.get('question_span') if type(question) is dict else None
                        if (type(question) is not dict
                                or set(question) != set(('schema', 'pending_id', 'initiating_input_id',
                                                         'pending_creation_output_id', 'context_conversation_id',
                                                         'target', 'target_sha256', 'selection',
                                                         'learning_declaration_sha256', 'question_template_id',
                                                         'question_template_sha256', 'rendered_text_sha256',
                                                         'question_span'))
                                or question['rendered_text_sha256'] != hashlib.sha256(output.encode('utf-8')).hexdigest()
                                or type(span) is not list or len(span) != 2
                                or type(span[0]) is not int or type(span[1]) is not int
                                or not 0 <= span[0] < span[1] <= len(output)):
                            raise ValueError("invalid action learning question metadata")
                    life['stage'] = 'persistence'
                    while life['persist']:
                        row = life['persist'][0]
                        recorder.mark_persistence(attempt, "learning_memory." + row["operation"], row["status"],
                                                  details=row)
                        life['persist'].pop(0)
                if conversation_id:
                    context = self.reasoning_contexts.get(context_id)
                    extra = {}
                    if action_tx is not None and action_tx.get('state') is not None:
                        extra['action_grounding_state'] = action_tx['state']
                    try:
                        life['stage'] = 'save'
                        life['save_attempted'] = True
                        payload["conversation"] = self.conversations.append_turn(
                            str(conversation_id), text, output, payload.get("phase"),
                            reasoning_state=context.snapshot() if context else None, **extra)
                        life['save_completed'] = True
                    except Exception as exc:
                        if not b_post:
                            if action_tx is not None:
                                self._action_grounding_rollback(action_tx)
                            elif isinstance(exc, OSError) and context is not None and prior_context_snapshot is not None:
                                context.restore(prior_context_snapshot)
                        raise
                if action_tx is not None:
                    self._action_grounding_publish(action_tx)
                if attempt is not None:
                    life['stage'] = 'persistence'
                    saved = payload.get("conversation") if conversation_id else None
                    turns = saved.get("turns") if type(saved) is dict else None
                    last = turns[-1] if type(turns) is list and turns and type(turns[-1]) is dict else None
                    details = None
                    if conversation_id and life['save_completed']:
                        details = {'conversation_id': saved.get('id') if type(saved) is dict else None,
                                   'turn_id': last.get('id') if last is not None else None}
                    recorder.mark_persistence(attempt, "conversation.append_turn",
                                              "completed" if conversation_id else "not_requested",
                                              details=details)
                    life['stage'] = 'output'
                    life['terminal_started'] = True
                    recorder.finish(attempt, payload, provenance=life['prov'],
                                    context_result=life['native_result'])
                return payload
            from pack_model import PackModel
            if type(self.model) is PackModel and getattr(self.model, "language_projection", None) is not None:
                try:
                    tx = self._action_grounding_begin(text, context_id, conversation_id, native_entry)
                    action_tx = tx
                    context = tx['context']
                    prior_context_snapshot = tx['pre']
                    memory_cls = None
                    limit_error = None
                    try:
                        from marco.learning.memory import LearningMemory, MemoryLimitError
                        if not callable(getattr(self, '_action_learning_after', None)):
                            life['gap'] = 'action_learning_hook_unavailable'
                        elif not (callable(getattr(LearningMemory, 'active_action_meanings', None))
                                  and callable(getattr(LearningMemory, 'close', None))):
                            life['gap'] = 'action_learning_dependency_unavailable'
                        else:
                            memory_cls = LearningMemory
                            limit_error = MemoryLimitError
                    except (ImportError, AttributeError):
                        life['gap'] = 'action_learning_dependency_unavailable'
                    resource = None
                    if memory_cls is not None:
                        opened = self._action_learning_open(context, session_id, conversation_id)
                        if type(opened) is dict and opened.get('status') == 'open' and opened.get('closed') is False:
                            life['archive'] = opened
                            resource = opened
                        elif type(opened) is dict and opened.get('status') == 'gap' and type(opened.get('gaps')) is list:
                            for gap_row in opened['gaps']:
                                if type(gap_row) is not dict:
                                    continue
                                gap_code = gap_row.get('code')
                                if type(gap_code) is str and gap_code and len(gap_code) <= 128:
                                    life['gap'] = gap_code
                                    break
                    if resource is not None:
                        stamp = deepcopy(resource['runtime_stamp'])
                        stamp['action_binding'] = self._action_grounding_host_binding(context, resource['binding'])
                        life['attempt'] = resource['recorder'].begin(
                            text, runtime_stamp=stamp, provenance=resource['provenance'])
                        life['stage'] = 'memory'
                        base_parser = context._parser()
                        memory_root = Path(resource['root_path']).resolve()
                        overlay_root = self.overlay.resolve()
                        memory_path = memory_root / str(resource['graph_binding']) / 'memory.sqlite'
                        scope_ok = True
                        try:
                            memory_path.resolve().relative_to(memory_root)
                            memory_path.resolve().relative_to(overlay_root)
                        except ValueError:
                            scope_ok = False
                        if scope_ok:
                            memory_path.parent.mkdir(parents=True, exist_ok=True)
                            try:
                                memory_path.parent.resolve().relative_to(memory_root)
                                memory_path.parent.resolve().relative_to(overlay_root)
                                memory_path.resolve().relative_to(memory_root)
                                memory_path.resolve().relative_to(overlay_root)
                            except ValueError:
                                scope_ok = False
                        previous_head = None
                        if not scope_ok:
                            life['gap'] = 'action_learning_memory_scope_invalid'
                        else:
                            try:
                                life['memory'] = memory_cls(
                                    str(memory_path), base_parser,
                                    graph_binding=resource['graph_binding'],
                                    action_projection=resource['action_projection'],
                                    action_learning_projection=resource['learning_projection'],
                                    action_binding=resource['binding'],
                                    dialogue_ledger=resource['ledger'])
                                inventory = life['memory'].active_action_meanings()
                                head = None
                                if type(inventory) is dict and set(inventory) == set(('schema', 'head', 'rows', 'gaps')):
                                    head = inventory['head']
                                if type(head) is dict and set(head) == set(('seq', 'change_id')):
                                    head_seq = head['seq']
                                    head_cid = head['change_id']
                                    if type(head_seq) is int and head_seq >= 0 and (
                                            (head_seq == 0 and head_cid is None)
                                            or (head_seq > 0 and type(head_cid) is str and head_cid)):
                                        previous_head = {'seq': head_seq, 'change_id': head_cid}
                                if previous_head is None:
                                    life['gap'] = 'action_learning_memory_head_invalid'
                            except limit_error:
                                previous_head = None
                                life['gap'] = 'action_learning_memory_unavailable'
                        if previous_head is not None:
                            transaction = dict(resource)
                            transaction.update(attempt=life['attempt'], memory=life['memory'],
                                               base_parser=base_parser, previous_head=previous_head)
                            life['tx22'] = transaction
                    life['stage'] = 'native'
                    outcome = context.turn(text)
                    life['native_result'] = outcome
                    life['native_completed'] = True
                    self._action_grounding_after_turn(tx, outcome)
                    if outcome is None:
                        # Context._turn legitimately remembered an unread statement segment.
                        # This is not an invariant error: keep the new context state and
                        # emit a terminal unresolved outcome for this native branch.
                        projection = getattr(self.model, "language_projection", None)
                        projection_data = getattr(projection, "data", None)
                        if projection_data is None and isinstance(projection, dict):
                            projection_data = projection.get("data")
                        context_replies = None
                        if isinstance(projection_data, dict):
                            context_replies = projection_data.get("context_replies")
                        else:
                            context_replies = getattr(projection_data, "context_replies", None)
                        declared_reply = None
                        if isinstance(context_replies, dict):
                            declared_reply = context_replies.get("input_understanding_failed")
                        else:
                            declared_reply = getattr(context_replies, "input_understanding_failed", None)
                        hold_answer = None
                        hold_reason = "language_graph_capability_gap"
                        if isinstance(declared_reply, str) and declared_reply.strip():
                            try:
                                hold_answer = declared_reply.format(**{"말": str(text)})
                                hold_reason = "input_understanding_failed"
                            except (KeyError, IndexError, ValueError):
                                hold_answer = None
                                hold_reason = "language_graph_capability_gap"
                        reply_sources = getattr(projection, "reply_sources", None)
                        if reply_sources is None and isinstance(projection, dict):
                            reply_sources = projection.get("reply_sources")
                        graph_source = None
                        if isinstance(reply_sources, dict):
                            graph_source = reply_sources.get("input_understanding_failed")
                        verification = context._verification(None, [{"ok": False, "reason": hold_reason}])
                        if isinstance(verification, dict):
                            verification["reply_available"] = hold_answer is not None
                            if graph_source is not None:
                                verification["graph_source"] = graph_source
                        outcome = {
                            "operator": "relational_graph",
                            "status": "unresolved",
                            "transitions": [],
                            "meaning": {
                                "act": "hold",
                                "reason": hold_reason,
                                "said": text,
                                "conversation": context.conversation_id,
                            },
                            "answer": hold_answer,
                            "verification": verification,
                        }
                    self._clear_manager_route()
                    action_adjunct = self._action_grounding_adjunct(action_tx, text, outcome)
                    hook = None
                    if life['tx22'] is not None:
                        life['stage'] = 'learning'
                        hook = self._action_learning_after(tx, outcome, action_adjunct, life['tx22'])
                        if type(hook) is dict and type(hook.get('persistence')) is list:
                            life['persist'] = deepcopy(hook['persistence'])
                        if (type(hook) is not dict
                                or set(hook) != set(('answer', 'learned', 'trace', 'provenance', 'persistence'))
                                or (hook['answer'] is not None
                                    and (type(hook['answer']) is not str or not hook['answer'].strip()))
                                or type(hook['learned']) is not bool or type(hook['trace']) is not dict
                                or type(hook['provenance']) is not dict or type(hook['persistence']) is not list):
                            raise ValueError("invalid action learning hook result")
                        life['hook'] = hook
                        life['stage'] = 'render'
                    omit_b = False
                    if hook is not None:
                        try:
                            budget_total = len(self._action_grounding_canonical(hook['trace']))
                            if action_adjunct is not None and action_adjunct.get('trace') is not None:
                                budget_total += len(self._action_grounding_canonical(action_adjunct['trace']))
                            omit_b = budget_total > self._ACTION_TRACE_BYTES - 4096
                        except (TypeError, ValueError, OverflowError, RecursionError):
                            omit_b = True
                        merged = deepcopy(life['archive']['provenance'])
                        for key in ('action_pending_created', 'meaning_question', 'learning_memory_head',
                                    'sources', 'used_learning'):
                            if key in hook['provenance'] and not (
                                    omit_b and key in ('meaning_question', 'sources', 'used_learning')):
                                merged[key] = deepcopy(hook['provenance'][key])
                        life['prov'] = merged
                    verdict = {"answered": "계산완료", "observed": "상태기억", "unresolved": "조건부족"}[outcome["status"]]
                    reasoning = {"operator": outcome["operator"], "transitions": outcome["transitions"]}
                    trace = {"mode": "situation", "question": text, "winner": outcome["operator"],
                             "verdict": verdict, "reasoning": reasoning, "verification": outcome["verification"],
                             "activated": [], "path": []}
                    public_answer = outcome["answer"]
                    if (isinstance(outcome.get("qualification"), dict)
                            and outcome["qualification"].get("schema") == "marco-known-support-with-pending-set-v2"):
                        import copy as _copy
                        trace["qualification"] = _copy.deepcopy(outcome["qualification"])
                    if action_adjunct is not None:
                        trace['action_grounding'] = action_adjunct['trace']
                        if action_adjunct.get('answer') is not None:
                            public_answer = action_adjunct['answer']
                    learned_out = False
                    if hook is not None:
                        if omit_b:
                            trace['action_learning_gap'] = {'code': 'action_learning_trace_budget'}
                        else:
                            trace['action_learning'] = hook['trace']
                            learned_out = hook['learned']
                            if hook['answer'] is not None:
                                public_answer = hook['answer']
                    elif life['gap'] is not None:
                        trace['action_learning_gap'] = {'code': life['gap']}
                    answer = {"answer": public_answer, "answer_markdown": public_answer,
                              "status": outcome["status"],
                              "meaning": outcome["meaning"],
                              "known": outcome["status"] == "answered", "learned": learned_out,
                              "trace": trace, "reasoning": reasoning, "verification": outcome["verification"],
                              "info": self.info()}
                    if (isinstance(outcome.get("qualification"), dict)
                            and outcome["qualification"].get("schema") == "marco-known-support-with-pending-set-v2"):
                        answer["qualification"] = deepcopy(outcome["qualification"])
                    self.history.append({"question": text, "claim": outcome["operator"],
                                         "evidence": None, "verdict": verdict, "sources": [], "learned": learned_out})
                    return finish({"phase": "answer",
                                   "understanding": {"available": False, "reason": "legacy_intent_not_declared",
                                                     "raw": text, "segments": [], "overall": {}},
                                   "affect": {"available": False, "enabled": False, "reason": "affect_not_declared"},
                                   "answer": answer})
                except BaseException as exc:
                    life['error'] = exc
                    attempt = life['attempt']
                    post_native = attempt is not None and life['native_completed']
                    try:
                        if post_native:
                            try:
                                self._action_grounding_publish(action_tx)
                            except Exception as publish_exc:
                                try:
                                    exc.add_note("action publication failed: %r" % (publish_exc,))
                                except Exception:
                                    pass
                        elif action_tx is not None:
                            self._action_grounding_rollback(action_tx)
                        else:
                            self._action_grounding_restore_entry(native_entry)
                    except Exception:
                        pass
                    if attempt is not None:
                        from marco.runtime.dialogue_trace import TraceWriteError
                        if not isinstance(exc, TraceWriteError):
                            try:
                                exc.add_note("action_learning attempt_id=%s input_id=%s trace_id=%s ledger_source_id=%s"
                                             % (attempt.attempt_id, attempt.input_id, attempt.trace_id,
                                                life['archive'].get('ledger_source_id')))
                            except Exception:
                                pass
                            if isinstance(exc, Exception) and not life['terminal_started']:
                                failure_recorder = life['archive']['recorder']
                                ready = True
                                try:
                                    while life['persist']:
                                        row = life['persist'][0]
                                        failure_recorder.mark_persistence(
                                            attempt, "learning_memory." + row["operation"], row["status"],
                                            details=row)
                                        life['persist'].pop(0)
                                except Exception as reporting_error:
                                    ready = False
                                    try:
                                        reporting_note = "persistence_report_uncertain: %s: %s" % (
                                            type(reporting_error).__name__, reporting_error)
                                        if isinstance(reporting_error, TraceWriteError):
                                            reporting_note += " (attempt_id=%s stage=%s path=%s)" % (
                                                reporting_error.attempt_id, reporting_error.stage,
                                                reporting_error.path)
                                        if reporting_error.__cause__ is not None:
                                            reporting_note += " caused_by %s: %s" % (
                                                type(reporting_error.__cause__).__name__,
                                                reporting_error.__cause__)
                                        exc.add_note(reporting_note)
                                    except Exception:
                                        pass
                                if ready:
                                    failure_recorder._record_failure(
                                        attempt, None, exc, life['stage'],
                                        deepcopy(life['archive']['provenance']))
                    raise
                finally:
                    cleanup_memory = life['memory']
                    cleanup_archive = life['archive']
                    primary_error = life['error']
                    life['memory'] = None
                    cleanup_error = None
                    if cleanup_memory is not None:
                        try:
                            cleanup_memory.close()
                        except BaseException as close_exc:
                            cleanup_error = close_exc
                            if primary_error is not None:
                                try:
                                    primary_error.add_note("memory cleanup failed: %r" % (close_exc,))
                                except Exception:
                                    pass
                    if cleanup_archive is not None:
                        try:
                            self._action_learning_close(cleanup_archive, primary_error)
                        except BaseException as archive_exc:
                            if cleanup_error is None:
                                raise
                            try:
                                cleanup_error.add_note("archive cleanup failed: %r" % (archive_exc,))
                            except Exception:
                                pass
                    if cleanup_error is not None and primary_error is None:
                        raise cleanup_error
            history = self.understanding_history.setdefault(context_id, [])
            understanding = input_understanding.understand(text, history, language_pack=self.language_pack)
            history.append(understanding); del history[:-30]
            request_kind = understanding.get("overall", {}).get("primary", {}).get("kind")
            affect = affect_state.update(self.affect_sessions.get(context_id), text, language_pack=self.language_pack)
            self.affect_sessions[context_id] = affect
            is_work = any(x["goal"]["kind"] == "perform" for x in understanding["segments"])
            if is_work:
                root = Path(self.conversations.project_root(str(conversation_id)) or self.project_roots.get(session_id, repo_root))
                plan = self.goals.plan_work(text, understanding, approval_mode, self.graph_path, root)
                self.goals.remember(context_id, plan)
                return finish(self._with_affect({"phase": "plan", "understanding": understanding, "plan": plan}, affect))
            # 요약·설명·계획은 대화 상태를 *읽을* 수는 있어도, 그 요청 자체가
            # 새 상태 사건은 아니다. 먼저 상황 계산기에 넣으면 `계획해줘` 같은
            # 요청을 못 읽은 변화로 남겨 뒤의 안전한 계획도 막는다.
            if (self.model.permits("relational_graph")
                    and request_kind not in {"request.summary", "request.explain", "request.plan", "request.compare"}):
                from marco.reasoning.context import ReasoningContext
                if context_id not in self.reasoning_contexts:
                    context = ReasoningContext(model=self.model, companions=self.companions)
                    saved = self.conversations.reasoning_state(str(conversation_id)) if conversation_id else None
                    if self.graph_overlay is not None:
                        saved = self._saved_reasoning_state(saved)
                    if saved is not None:
                        context.restore(saved)
                    self.reasoning_contexts[context_id] = context
                context = self.reasoning_contexts[context_id]
                prior_context_snapshot = context.snapshot()
                outcome = context.turn(text)
                if outcome is not None:
                    self._clear_manager_route()
                    verdict = {"answered": "계산완료", "observed": "상태기억", "unresolved": "조건부족"}[outcome["status"]]
                    reasoning = {"operator": outcome["operator"], "transitions": outcome["transitions"]}
                    trace = {"mode": "situation", "question": text, "winner": outcome["operator"],
                             "verdict": verdict, "reasoning": reasoning, "verification": outcome["verification"],
                             "activated": [], "path": []}
                    answer = {"answer": outcome["answer"], "answer_markdown": outcome["answer"],
                              "known": outcome["status"] == "answered", "learned": False,
                              "trace": trace, "reasoning": reasoning, "verification": outcome["verification"],
                              "info": self.info()}
                    self.history.append({"question": text, "claim": outcome["operator"],
                                         "evidence": None, "verdict": verdict, "sources": [], "learned": False})
                    return finish(self._with_affect({"phase": "answer", "understanding": understanding,
                                                    "answer": answer}, affect))
            if understanding.get("overall", {}).get("primary", {}).get("kind") == "dialogue":
                self._clear_manager_route()
                answer_text = input_understanding.dialogue_reply(text, language_pack=self.language_pack)
                trace = {"mode": "dialogue", "question": text, "winner": "dialogue.reply",
                         "verdict": "대화", "activated": [], "path": []}
                answer = {"answer": answer_text, "answer_markdown": answer_text,
                          "learned": False, "known": True, "trace": trace, "info": self.info()}
                self.history.append({"question": text, "claim": "dialogue.reply", "evidence": None,
                                     "verdict": "대화", "sources": [], "learned": False})
                return finish(self._with_affect({"phase": "answer", "understanding": understanding, "answer": answer}, affect))
            # 요청의 말끝을 알아듣는 것만으로는 답이 되지 않는다. 정확히 찾은
            # 로컬 정의를 재료로 삼을 때만 요약·설명을 만든다. 없는 근거나 앞선
            # 대화의 임의 문장을 요약 재료로 쓰지 않는다.
            segment = (understanding.get("segments") or [{}])[0]
            subject = next((item.get("text") for item in segment.get("subject_candidates", [])
                            if item.get("source") == "current"), None)
            if request_kind in {"request.summary", "request.explain", "request.plan"} and subject:
                definition = self.definitions.lookup_term(subject)
                evidence = ([{"text": definition["definition"], "source": definition["source"],
                             "actionable": False}]
                            if definition else self._packed_evidence(subject))
                # A read-only plan/explanation still needs the saved dialogue
                # state.  On a fresh app instance it has not passed through
                # the event branch above, so hydrate it here instead of
                # silently dropping learned definitions and execution grounds.
                if context_id not in self.reasoning_contexts and conversation_id:
                    from marco.reasoning.context import ReasoningContext
                    saved = self.conversations.reasoning_state(str(conversation_id))
                    if self.graph_overlay is not None:
                        saved = self._saved_reasoning_state(saved)
                    if saved is not None:
                        restored = ReasoningContext(model=self.model, companions=self.companions)
                        restored.restore(saved)
                        self.reasoning_contexts[context_id] = restored
                # A learned action is a plan *candidate*, not a past action
                # to repeat.  Keep its definition version and role contract
                # as dialogue-grounded evidence alongside selected pack data.
                # Summary/explanation still require their own factual/causal
                # evidence; definitions alone are not causal proof.
                context = self.reasoning_contexts.get(context_id)
                if request_kind == "request.plan" and context is not None:
                    evidence = context.learned_action_candidates() + evidence
                if request_kind == "request.explain" and context is not None:
                    evidence = context.execution_evidence(subject) + evidence
                composed = response_composer.compose(
                    request_kind,
                    evidence,
                    goal=subject,
                    state=(context.current_state() if context is not None else []))
                if composed is not None:
                    self._clear_manager_route()
                    winner = definition["term"] if definition else subject
                    trace = {"mode": composed["mode"], "question": text,
                             "winner": winner, "verdict": "근거응답",
                             "activated": [winner], "path": [],
                             "sources": composed["selected"]}
                    answer = {"answer": composed["answer"], "answer_markdown": composed["answer"],
                              "learned": False, "known": True, "trace": trace,
                              "composition": composed, "info": self.info()}
                    self.history.append({"question": text, "claim": winner,
                                         "evidence": composed["selected"][0]["source"], "verdict": "근거응답",
                                         "sources": composed["selected"], "learned": False})
                    return finish(self._with_affect({"phase": "answer", "understanding": understanding,
                                                     "answer": answer}, affect))
            # 정의형 질문은 모델이나 유사도보다 먼저 로컬 원문 표제어를 정확히 찾는다.
            # 일치하지 않으면 아무것도 추정하지 않고 기존 KG/웹 흐름으로 넘긴다.
            # 단일 표제어 정의는 기존처럼 KG보다 먼저 쓴다. 반면 A와 B의
            # 비교는 세균·바이러스처럼 전문 KG가 관계 자체를 명시했을 수 있다.
            # 이때는 라우터 점수가 아니라 실제 KG 판정이 '인정'인지로만
            # 선점 여부를 정한다. 약하게 잘못 라우팅된 그래프가 비교를 막지
            # 않도록 근거없음·미지는 정의 비교에 자리를 내준다.
            definition = self.definitions.lookup(text)
            if (request_kind == "request.compare" and subject):
                definition = self.definitions.compare_target(subject) or definition
            if not definition:
                terms = (local_definitions.DefinitionLookup.comparison_terms(
                             (str(subject) + " 비교") if subject else text)
                         if request_kind == "request.compare" else None)
                if terms:
                    entries = []
                    for term in terms:
                        evidence = self._packed_evidence(term)
                        if not evidence:
                            entries = []
                            break
                        entries.append({"label": term, "text": evidence[0]["text"],
                                        "source": evidence[0]["source"],
                                        "attributes": evidence[0].get("attributes", {})})
                    composed = response_composer.compare(entries)
                    if composed is not None:
                        self._clear_manager_route()
                        trace = {"mode": composed["mode"], "question": text,
                                 "winner": " · ".join(terms), "verdict": "원문근거비교",
                                 "activated": list(terms), "path": [],
                                 "sources": composed["selected"]}
                        answer = {"answer": composed["answer"], "answer_markdown": composed["answer"],
                                  "learned": False, "known": True, "trace": trace,
                                  "composition": composed, "info": self.info()}
                        self.history.append({"question": text, "claim": trace["winner"],
                                             "evidence": None, "verdict": "원문근거비교",
                                             "sources": composed["selected"], "learned": False})
                        return finish(self._with_affect({"phase": "answer", "understanding": understanding,
                                                         "answer": answer}, affect))
                comparison = self.definitions.compare(text)
                if comparison:
                    has_specific_kg = False
                    try:
                        route, _score, _candidates = engine.pick_graph(text)
                        if route:
                            has_specific_kg = engine.judge(engine.load_graph(route), text)[0] == "인정"
                    except Exception:
                        has_specific_kg = False
                    if not has_specific_kg:
                        definition = comparison
            if definition:
                self._clear_manager_route()
                if definition.get("kind") == "comparison":
                    entries = definition["definitions"]
                    composed = response_composer.compare([
                        {"label": entry["term"], "text": entry["definition"], "source": entry["source"]}
                        for entry in entries])
                    answer_text = composed["answer"] if composed else ""
                    winner, activated = " · ".join(definition["terms"]), definition["terms"]
                    sources = composed["selected"] if composed else []
                    verdict = "원문정의비교"
                else:
                    answer_text = "**%s** — %s" % (definition["term"], definition["definition"])
                    winner, activated = definition["term"], [definition["term"]]
                    sources, verdict = [{"node": definition["term"], "source": definition["source"]}], "원문정의"
                trace = {"mode": "local_definition", "question": text, "winner": winner,
                         "verdict": verdict, "activated": activated, "path": [], "sources": sources}
                answer = {"answer": answer_text, "answer_markdown": answer_text, "learned": False,
                         "known": True, "trace": trace, "info": self.info(), "definition": definition,
                         **({"composition": composed} if definition.get("kind") == "comparison" else {})}
                self.history.append({"question": text, "claim": winner, "evidence": definition["source"],
                                     "verdict": verdict, "sources": trace["sources"], "learned": False})
                return finish(self._with_affect({"phase": "answer", "understanding": understanding, "answer": answer}, affect))
            # 문장 유사도나 문제별 정규식은 산술·시간·순위 같은 상황을 대신할 수
            # 없다. 학습 모델의 후보도 원문 span·타입 검증을 통과한 JSON일 때만
            # 순수 상태 엔진에 전달한다.
            situation_path = self._materialize(self.situation_graph) if self.situation_graph else None
            semantic = self.semantic_parser.parse(text)
            situation = state_engine.evaluate(semantic, situation_path, model=self.model)
            if semantic.get("accepted") and situation["status"] == "unknown":
                # The question was interpreted, but its premises/operation did
                # not establish an answer. Retrieval cannot supply that proof.
                self._clear_manager_route()
                answer_text = self._said({"act": "hold", "reason": engine._not_found_reason(text, []),
                                          "said": text},
                                         engine._not_found_reply(text, [], self.language_pack["refusals"]))
                reasoning = {"operator": situation.get("operator"), "transitions": situation.get("transitions", [])}
                trace = {"mode": "situation", "question": text, "winner": None,
                         "verdict": "조건부족", "activated": [], "path": [],
                         "semantic_parse": semantic, "reasoning": reasoning,
                         "verification": situation.get("verification", {})}
                answer = {"answer": answer_text, "answer_markdown": answer_text,
                          "known": False, "learned": False, "trace": trace,
                          "semantic_parse": semantic, "reasoning": reasoning,
                          "verification": trace["verification"], "info": self.info()}
                self.history.append({"question": text, "claim": None, "evidence": None,
                                     "verdict": "조건부족", "sources": [], "learned": False})
                return finish(self._with_affect({"phase": "answer", "understanding": understanding,
                                                "answer": answer}, affect))
            if situation["status"] != "unknown":
                # 상황 규칙도 독립 KG의 선언을 근거로 삼는다. 매니저 화면에서
                # 어떤 지식 묶음이 쓰였는지 보이도록 선택 상태를 함께 남긴다.
                if self.routing and self.situation_graph:
                    self._activate(self.situation_graph, force=True)
                    self.routed_graphs = [self.situation_graph]
                    self.route = {"selected": self.situation_graph,
                                  "selected_all": [self.situation_graph],
                                  "score": 1.0, "best_score": 1.0,
                                  "candidates": [[self.situation_graph, 1.0]],
                                  "fallback": False, "segments": [{"question": text,
                                  "selected": self.situation_graph, "score": 1.0,
                                  "best_score": 1.0, "fallback": False,
                                  "candidates": [[self.situation_graph, 1.0]]}]}
                trace = {"mode": "situation", "question": text,
                         "winner": situation.get("operator"),
                         "verdict": "전제불성립" if situation["status"] == "premise_invalid" else "계산완료",
                         "activated": [], "path": [], "semantic_parse": semantic,
                         "reasoning": {"operator": situation.get("operator"), "transitions": situation.get("transitions", [])},
                         "verification": situation.get("verification", {})}
                answer = {"answer": situation["answer"], "answer_markdown": situation["answer"],
                          "learned": False, "known": True, "trace": trace, "semantic_parse": semantic,
                          "reasoning": trace["reasoning"], "verification": trace["verification"], "info": self.info()}
                self.history.append({"question": text, "claim": situation.get("operator"),
                                     "evidence": None, "verdict": trace["verdict"],
                                     "sources": [], "learned": False})
                return finish(self._with_affect({"phase": "answer", "understanding": understanding, "answer": answer}, affect))
            # 해석이 불충분하면 KG 매니저가 비슷한 여러 그래프를 답처럼 나열하지
            # 않는다. 상태 해석 실패 사실은 연구/근거 부족 결과에 그대로 남긴다.
            semantic_failure = {"semantic_parse": semantic, "reasoning": {"operator": None, "transitions": []},
                                "verification": situation.get("verification", {})}
            # 숫자·변수·연산자는 읽었지만 등식/피연산자가 덜 온 경우다. 이는
            # 외부 사실을 찾으면 메울 종류의 빈칸이 아니므로, 일반 질문
            # 추출기(예: "알아")로 넘어가기 전에 입력 보완을 요청한다.
            if semantic.get("reason") == "incomplete_expression":
                self._clear_manager_route()
                trace = {"mode": "situation", "question": text, "winner": None,
                         "verdict": "입력이해실패", "activated": [], "path": [],
                         **semantic_failure,
                         "retrieval": {"diagnosis": "input_understanding_failed",
                                       "need": {"kind": "clarification", "topic": None,
                                                "resolved": False}}}
                answer_text = self._said({"act": "hold", "reason": "input_understanding_failed", "said": text},
                                         self.language_pack["relations"].get("context_replies", {}).get(
                                             "input_understanding_failed", self.language_pack["refusals"]["clarify"]))
                answer = {"answer": answer_text, "answer_markdown": answer_text,
                          "known": False, "learned": False, "trace": trace,
                          **semantic_failure, "info": self.info()}
                self.history.append({"question": text, "claim": None, "evidence": None,
                                     "verdict": "입력이해실패", "sources": [], "learned": False})
                return finish(self._with_affect({"phase": "answer", "understanding": understanding,
                                                 "answer": answer}, affect))
            # 자가학습 KG도 여기서는 학습을 막는다. 웹 저장은 승인 행동으로만 가능하다.
            answer = self.ask(text, allow_learning=False)
            answer.update(semantic_failure)
            if not answer.get("known"):
                answer.setdefault("trace", {}).update(semantic_failure)
            verdict = (answer.get("trace") or {}).get("verdict")
            known = answer.get("known", verdict not in (None, "미지", "지식부족", "B2"))
            if known:
                return finish(self._with_affect({"phase": "answer", "understanding": understanding, "answer": answer}, affect))
            # 모르는 문장을 곧바로 외부 사실 부족으로 부르지 않는다. 검색할
            # 주제를 기존 자가학습 그래프의 질문 구조에서 뽑지 못했다면, 먼저
            # 입력 이해가 막힌 것이다. 이 경우 원문 전체(개인 문맥 포함)를
            # 검색으로 보내도 필요한 전제를 보충했다는 근거가 생기지 않는다.
            learning_path = self._materialize(self.auto_graph) if self.auto_graph else self.graph_path
            topic = None
            if learning_path:
                try:
                    topic, _aliases = web_learn.extract_topic(web_learn.load(learning_path), text,
                                                               self.language_pack)
                except (OSError, ValueError, UnicodeError):
                    topic = None
            if not topic:
                self._clear_manager_route()
                trace = answer.setdefault("trace", {})
                trace.update({"verdict": "입력이해실패",
                              "retrieval": {"diagnosis": "input_understanding_failed",
                                            "need": {"kind": "clarification", "topic": None,
                                                     "resolved": False}}})
                answer["known"] = False
                answer["answer"] = answer["answer_markdown"] = self._said(
                    {"act": "hold", "reason": "input_understanding_failed", "said": text},
                    self.language_pack["relations"].get("context_replies", {}).get(
                        "input_understanding_failed", answer.get("answer", "")))
                self.history.append({"question": text, "claim": None, "evidence": None,
                                     "verdict": "입력이해실패", "sources": [], "learned": False})
                return finish(self._with_affect({"phase": "answer", "understanding": understanding,
                                                 "answer": answer, **semantic_failure}, affect))
            try:
                research = self.goals.research(text, language_pack=self.language_pack)
            except Exception as e:
                research = {"query": text, "search_terms": None, "sources": [], "verified": False,
                            "diagnosis": "external_retrieval_failed",
                            "need": {"kind": "external_fact", "topic": None, "resolved": False},
                            "error": "%s: %s" % (type(e).__name__, e)}
            # 미지는 답변에 자동 학습 KG를 쓰지 않는다. 다만 승인된 웹 사실은
            # 전용 overlay 대상에만 저장해 다음 독립 질의에서 검증 가능하게 한다.
            # 주워온 지식은 자가학습 그래프 옆에만 쌓는다. 라우터가 고른 KG
            # 옆에 쌓으면 다시 읽을 길이 없다 — `수집`을 읽는 것은 `_자가질문`
            # 뿐이고 그것은 자가학습 그래프가 활성일 때만 돈다. 실제로
            # `graph_AGI_최소지식.kg` 옆에 저장하려다, 그 그래프에는 질문
            # 껍데기를 벗길 `물음_` 표지가 없어 주제조차 못 뽑고 있었다.
            #
            # 계획은 만든 뒤 10분 동안 살아 있다가 승인된다. 그런데 계획이 들고
            # 가는 것은 경로 문자열뿐이라, 그 사이에 overlay 파일이 없어지면
            # 승인 순간 FileNotFoundError 가 화면에 그대로 튀어나왔다. 그래서
            # 계획을 세울 때 대상을 다시 깔아 둔다 — 이미 같은 내용이 있으면
            # `_materialize` 는 아무것도 안 쓴다.
            root = Path(self.conversations.project_root(str(conversation_id)) or self.project_roots.get(session_id, repo_root))
            plan = self.goals.plan_learning(text, research, approval_mode, learning_path, root,
                                            language_pack=self.language_pack)
            self.goals.remember(context_id, plan)
            return finish(self._with_affect({"phase": "research", "understanding": understanding, "answer": answer,
                                      "research": research, "web_answer": web_grounds_answer(research, self.language_pack["refusals"]), "plan": plan,
                                      **semantic_failure}, affect))

    def approve_goal(self, session_id, plan_id, plan_hash, action_ids, direct=False, conversation_id=None):
        session_id = str(session_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", session_id):
            raise ValueError("유효하지 않은 브라우저 세션입니다")
        with self.lock:
            context_id = "chat_" + str(conversation_id) if conversation_id else session_id
            return self.goals.approve(context_id, str(plan_id or ""), str(plan_hash or ""), action_ids, bool(direct))

    def reject_goal(self, session_id, plan_id, reason="", conversation_id=None):
        session_id = str(session_id or "").strip()
        with self.lock:
            context_id = "chat_" + str(conversation_id) if conversation_id else session_id
            plan = self.goals.pending.pop((context_id, str(plan_id or "")), None)
        return {"rejected": bool(plan), "plan_id": plan_id, "reason": str(reason or "")}

    def _is_general_question(self, question):
        graph = self.graph
        evidence, evidence_score = engine.match_evidence(question, graph)
        body = engine.erase_evidence(question, graph, evidence)
        pool = ([n for n in graph["사례층"] if n not in graph["증거"]]
                + list(graph["공통층"]))
        ranks = score(body, pool, graph)
        nulls = score(body, list(graph.get("무관층", {})), graph)
        winner = ranks[0][0] if ranks else None
        # 증거는 문자열으로만 매칭된다. 그래프의 사례·주장 벡터가 비슷하다는
        # 이유로 사용자의 질문을 다른 사실로 바꿔 답하지 않는다.
        if not evidence:
            answer = self._said({"act": "hold", "reason": "argument_no_evidence", "said": question},
                                self.language_pack["refusals"]["argument_no_evidence"])
            trace = {"mode": "argument", "question": question, "winner": winner,
                     "verdict": "근거불충분", "evidence": {"name": None, "score": 0.0},
                     "rankings": [[n, round(v, 3)] for n, v in ranks[:5]],
                     "null_rankings": [[n, round(v, 3)] for n, v in nulls[:3]],
                     "margin": round(ranks[0][1] - ranks[1][1], 3) if len(ranks) > 1 else None,
                     "path": [], "activated": []}
            self.history.append({"question": question, "claim": None, "evidence": None,
                                 "verdict": "근거불충분", "sources": [], "learned": False})
            return {"answer": answer, "answer_markdown": answer, "learned": False,
                    "known": False, "verdict": "근거불충분", "result": self.session.result(),
                    "trace": trace, "info": self.info()}
        # 한 문장짜리 정의 질문은 대화 상태의 모든 요건을 채울 때까지 기다릴
        # 이유가 없다. 엔진의 순수 판정기로 같은 근거에서 바로 결론을 확인한다.
        # 판정기가 미지이면 기존 다턴 상태 대화로 그대로 내려간다.
        # 정의뿐 아니라 "왜 있어/왜 그래"처럼 한 번에 답해야 하는 짧은
        # 관계 질문도 세션의 남은 요건을 억지로 나열하지 않는다. 판정기는
        # 여전히 원문 증거가 있는 경우에만 답을 돌려준다.
        direct_question = bool(re.search(r"(?:[?？]|뭐야|뭔데|무엇|뜻|정의|설명해|알려\s*줘|왜\s*(?:있어|그래|인가|야)?)\s*$", question))
        if direct_question:
            direct_verdict, direct_answer = engine.judge(graph, question)
            if direct_verdict not in ("미지", "B2"):
                route = path(graph, evidence or winner, graph["목표"])
                trace = {"mode": "argument", "question": question, "winner": winner,
                         "verdict": direct_verdict,
                         "evidence": {"name": evidence, "score": round(evidence_score, 3)},
                         "rankings": [[n, round(v, 3)] for n, v in ranks[:5]],
                         "null_rankings": [[n, round(v, 3)] for n, v in nulls[:3]],
                         "margin": round(ranks[0][1] - ranks[1][1], 3) if len(ranks) > 1 else None,
                         "path": route,
                         "activated": list(dict.fromkeys([x for x in [evidence, winner] if x]
                                                          + [n for e in route for n in (e[0], e[2])]))}
                self.history.append({"question": question, "claim": winner, "evidence": evidence,
                                     "verdict": direct_verdict, "sources": [], "learned": False})
                return {"answer": direct_answer, "answer_markdown": direct_answer, "learned": False,
                        "known": True, "verdict": direct_verdict, "result": self.session.result(),
                        "trace": trace, "info": self.info()}
        answer = self.session.reply(question)
        if self.session.verdict == "미지":
            # The graph holds: said from that meaning, not from the graph's own line.
            answer = self._said({"act": "hold", "reason": "no_evidence", "said": question}, answer)
        route = path(graph, evidence or winner, graph["목표"])
        trace = {"mode": "argument", "question": question, "winner": winner,
                 "verdict": self.session.verdict,
                 "evidence": {"name": evidence, "score": round(evidence_score, 3)},
                 "rankings": [[n, round(v, 3)] for n, v in ranks[:5]],
                 "null_rankings": [[n, round(v, 3)] for n, v in nulls[:3]],
                 "margin": round(ranks[0][1] - ranks[1][1], 3) if len(ranks) > 1 else None,
                 "path": route,
                 "activated": list(dict.fromkeys([x for x in [evidence, winner] if x]
                                                  + [n for e in route for n in (e[0], e[2])]))}
        self.history.append({"question": question, "claim": winner,
                             "evidence": evidence, "verdict": self.session.verdict,
                             "sources": [], "learned": False})
        return {"answer": answer, "answer_markdown": answer, "learned": False, "verdict": self.session.verdict,
                "result": self.session.result(), "trace": trace, "info": self.info()}

    def _self_claim(self, question):
        table = []
        for node, aliases in (self.graph.get("_주제별칭") or {}).items():
            table.extend((a, node) for a in aliases)
        return next((node for alias, node in sorted(table, key=lambda x: len(x[0]), reverse=True)
                    if alias and alias in question), None)

    def _self_trace(self, question, claim, learned):
        sources, facts, proof_edges = [], [], []
        if claim:
            for a, relation, b in self.graph.get("엣지", []):
                if relation == "충족" and b == claim and a.startswith("지식_"):
                    facts.append(a)
                    proof_edges.append([a, relation, b])
            for a, relation, b in self.graph.get("엣지", []):
                if relation == "증명" and b in facts:
                    if not any(s["node"] == a for s in sources):
                        sources.append({"node": a, "source": self.graph.get("출처", {}).get(a, "")})
                    proof_edges.append([a, relation, b])
            for a, relation, b in self.graph.get("엣지", []):
                if a == claim and relation in engine.forward_rels(self.graph):
                    proof_edges.append([a, relation, b])
        return {"mode": "self_learning", "question": question, "winner": claim,
                "verdict": "채택" if claim else "지식부족", "evidence": None,
                "rankings": [], "null_rankings": [], "margin": None,
                "path": proof_edges,
                "activated": ([claim] if claim else []) + facts + [s["node"] for s in sources],
                "sources": sources, "facts": facts, "learned": learned}

    def _is_self_question(self, question, allow_learning=True):
        known, answer = web_learn.ask(self.graph, question)
        if not known:
            # Not known: said from that meaning, not from the graph's own line.
            answer = self._said({"act": "hold", "reason": "no_evidence", "said": question}, answer)
        learned = False
        if not known and allow_learning:
            topic, _aliases = web_learn.extract_topic(self.graph, question)
            if topic:
                try:
                    fresh = web_learn.learn(str(self.graph_path), topic, question,
                                           count=5, min_source=2)
                except web_learn.LearnFailed as e:
                    return {"answer": "자동 학습을 완료하지 못했습니다: %s" % e,
                            "answer_markdown": "자동 학습을 완료하지 못했습니다: %s" % e,
                            "learned": False, "trace": None, "info": self.info()}
                if fresh:
                    self.graph = web_learn.load(str(self.graph_path))
                    known, answer = web_learn.ask(self.graph, question)
                    learned = known
                elif not known:
                    answer = self._said({"act": "hold", "reason": "web_learn_failed", "said": question},
                                        self.language_pack["refusals"]["web_learn_failed"])
        claim = self._self_claim(question) if known else None
        trace = self._self_trace(question, claim, learned)
        self.history.append({"question": question, "claim": claim,
                             "evidence": None, "verdict": trace["verdict"],
                             "sources": [s["source"] for s in trace["sources"]],
                             "learned": learned})
        return {"answer": answer, "answer_markdown": markdown_answer(answer, trace),
                "learned": learned, "known": known, "trace": trace, "info": self.info()}

    def ask(self, question, allow_learning=True):
        question = (question or "").strip()
        if not question:
            raise ValueError("질문이 비어 있습니다")
        with self.lock, self.model.encoder.activate():
            if self.graph_overlay is not None:
                self._sync_graph_overlay()
            if self.routing:
                self.combined_shape = None
                segments, candidate_scores = [], {}
                for part in question_passage(question):
                    name, score, candidates = engine.pick_graph(part, self.manager_index,
                                                                  min_n=0.45, count=5)
                    for candidate, value in candidates:
                        candidate_scores[candidate] = max(candidate_scores.get(candidate, 0), value)
                    # 한 의미 대목에는 최고 후보 하나만 실행한다. 점수 근처 후보를
                    # 전부 실행하면 '마라톤 순위' 같은 한 질문에 법·대출 KG가
                    # 줄줄이 붙어, 근거 부족 메시지만 여러 번 보여 주게 된다.
                    selected = [name] if name else []
                    # 문턱 미달은 '모름'이다. 자동 학습 그래프를 억지로 골라
                    # 가까운 문장을 답하는 것은 금지한다.
                    fallback = False
                    for selected_name in selected:
                        selected_score = next((c for n, c in candidates if n == selected_name), None)
                        segments.append({"question": part, "selected": selected_name,
                                         "score": selected_score,
                                         "best_score": score, "fallback": fallback,
                                         "candidates": [[n, c] for n, c in candidates]})
                if not segments:
                    self._clear_manager_route()
                    self.route = {"selected": None, "selected_all": [], "score": None,
                                  "best_score": max(candidate_scores.values(), default=0),
                                  "candidates": [[n, c] for n, c in sorted(
                                      candidate_scores.items(), key=lambda x: -x[1])[:5]],
                                  "fallback": False, "segments": []}
                    answer = self._said({"act": "hold", "reason": "no_graph_selected", "said": question},
                                        self.language_pack["refusals"]["no_graph_selected"])
                    return {"answer": answer, "answer_markdown": answer, "learned": False,
                            "trace": {"mode": "manager", "question": question, "winner": None,
                                      "verdict": "미지", "activated": [], "path": [],
                                      "route": self.route}, "info": self.info()}
                grouped = {}
                for segment in segments:
                    grouped.setdefault(segment["selected"], []).append(segment["question"])
                names = list(grouped)
                first = segments[0]
                self.routed_graphs = names
                self.route = {"selected": names[0], "selected_all": names,
                              "score": first["score"], "best_score": first["best_score"],
                              "candidates": [[n, c] for n, c in sorted(
                                  candidate_scores.items(), key=lambda x: -x[1])[:5]],
                              "fallback": any(x["fallback"] for x in segments),
                              "segments": segments}
                if len(names) > 1:
                    items, markdown_parts, plain_parts = [], [], []
                    for name in names:
                        part_question = ". ".join(grouped[name])
                        self._activate(name, force=True)
                        piece = self._is_self_question(part_question, allow_learning) if self.self_learning else self._is_general_question(part_question)
                        label = name.removeprefix("graphs/").removesuffix(".kg")
                        items.append({"graph": name, "question": part_question,
                                      "answer": piece.get("answer", ""),
                                      "trace": piece.get("trace"), "shape": graph_shape(self.graph)})
                        plain_parts.append("[%s]\n%s" % (label, piece.get("answer", "")))
                        markdown_parts.append("## %s\n\n%s" % (label, piece.get("answer", "")))
                    self.combined_shape = merge_shape(items)
                    trace = merge_trace(items, self.route)
                    part_known = [piece.get("known", (piece.get("trace") or {}).get("verdict")
                                  not in (None, "미지", "지식부족", "근거불충분", "B2")) for piece in items]
                    result = {"answer": "\n\n".join(plain_parts),
                              "answer_markdown": "\n\n".join(markdown_parts),
                              "learned": any((x.get("trace") or {}).get("learned") for x in items),
                              "known": bool(part_known) and all(part_known),
                              "trace": trace, "parts": items, "info": self.info()}
                    return result
                self._activate(names[0])
                question = ". ".join(grouped[names[0]])
            else:
                self.routed_graphs = []
                self.combined_shape = None
            result = self._is_self_question(question, allow_learning) if self.self_learning else self._is_general_question(question)
            if self.routing:
                trace = result.get("trace") or {"mode": "manager", "question": question,
                                                "winner": None, "verdict": "오류",
                                                "activated": [], "path": []}
                trace["route"] = self.route
                result["trace"] = trace
                result["info"] = self.info()
            return result


    _ACTION_BINDING_KEYS = ('conversation_id', 'model_content_sha256', 'model_effective_key', 'graph_id', 'root_id',
                            'effective_graph_sha256', 'view_key', 'language_projection_fingerprint',
                            'action_projection_fingerprint', 'parser_base_sha256', 'parser_grammar_sha256',
                            'installed_memory_head')
    _ACTION_STATE_BYTES = 1048576
    _ACTION_TRACE_BYTES = 2097152
    _ACTION_TEXT_BYTES = 65536

    def _action_grounding_native(self):
        from pack_model import PackModel
        return type(self.model) is PackModel and getattr(self.model, 'language_projection', None) is not None

    @staticmethod
    def _action_grounding_plain(value):
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))

    @staticmethod
    def _action_grounding_canonical(value):
        from marco.storage.snapshot import canonical
        return canonical(value)

    def _action_grounding_capture_entry(self):
        contexts = {}
        for cid, context in dict(self.reasoning_contexts).items():
            contexts[cid] = (context, context.snapshot())
        store = self.conversations
        return {'fields': {name: getattr(self, name, None) for name in (
                    'model', 'language_pack', 'active_name', 'route', 'routed_graphs', 'combined_shape',
                    'graph', 'session', 'graph_path')},
                'had_overlay_applied': hasattr(self, '_overlay_applied'),
                'overlay_applied': getattr(self, '_overlay_applied', None),
                'contexts': contexts,
                'had_action_states': hasattr(self, 'action_grounding_states'),
                'action_states': deepcopy(getattr(self, 'action_grounding_states', {})),
                'history': list(self.history),
                'had_binding': hasattr(store, 'binding'),
                'binding': deepcopy(getattr(store, 'binding', None)),
                'restored': False}

    def _action_grounding_restore_entry(self, entry):
        if entry is None or entry.get('restored'):
            return
        entry['restored'] = True
        try:
            for cid, (context, snap) in entry['contexts'].items():
                try:
                    unchanged = context.snapshot() == snap
                except Exception:
                    unchanged = False
                if not unchanged:
                    context.restore(snap)
        finally:
            for cid in list(self.reasoning_contexts):
                if cid not in entry['contexts']:
                    self.reasoning_contexts.pop(cid, None)
            for cid, (context, _snap) in entry['contexts'].items():
                self.reasoning_contexts[cid] = context
            if entry['had_action_states']:
                self.action_grounding_states = deepcopy(entry['action_states'])
            elif hasattr(self, 'action_grounding_states'):
                try:
                    delattr(self, 'action_grounding_states')
                except Exception:
                    pass
            self.history[:] = entry['history']
            for name, value in entry['fields'].items():
                setattr(self, name, value)
            if entry['had_overlay_applied']:
                self._overlay_applied = entry['overlay_applied']
            elif hasattr(self, '_overlay_applied'):
                try:
                    delattr(self, '_overlay_applied')
                except Exception:
                    pass
            store = self.conversations
            binding = getattr(store, 'binding', None)
            if isinstance(binding, dict) and isinstance(entry['binding'], dict):
                binding.clear()
                binding.update(deepcopy(entry['binding']))
            elif entry['had_binding']:
                try:
                    setattr(store, 'binding', deepcopy(entry['binding']))
                except Exception:
                    pass

    def _action_grounding_saved_seeds(self, context, saved):
        from marco.reasoning.readings import validate_ledger
        ledger = saved.get('reading_ledger') if isinstance(saved, dict) else None
        if ledger is None:
            return []
        validate_ledger(saved.get('observations'), saved.get('observation_ids'), ledger,
                        max_turns=context.max_turns, base=None, head_limit=None)
        seeds = []
        for entry in ledger['records'].values():
            for version in entry['versions']:
                seed = version.get('parser_base_sha256')
                if seed is None:
                    continue
                if not (isinstance(seed, str) and re.fullmatch(r'[0-9a-f]{64}', seed)):
                    raise ValueError('invalid saved reading ledger parser_base_sha256 seed')
                seeds.append(seed)
        return seeds

    def _action_grounding_context(self):
        from marco.reasoning.context import ReasoningContext
        context = ReasoningContext(model=self.model, companions=self.companions)
        base = context._grammar()
        if type(base) is not str or not re.fullmatch(r'[0-9a-f]{64}', base):
            raise ValueError('invalid_parser_base')
        context.parser_base_sha256 = base
        context.installed_memory_head = None
        return context

    def _action_grounding_carrier(self):
        try:
            envelope = getattr(self.model, 'action_grounding_projection', None)
        except Exception:
            return ('gap', None, None, 'action_projection_failed')
        if envelope is None:
            return (None, None, None, None)
        try:
            if type(envelope) is not dict or envelope.get('schema') != 'pack-action-grounding-projection-v1':
                return ('gap', None, None, 'action_projection_shape')
            if envelope.get('status') == 'gap':
                gaps = envelope.get('gaps')
                code = gaps[0].get('code') if isinstance(gaps, list) and gaps and isinstance(gaps[0], dict) else None
                return ('gap', None, None, code if isinstance(code, str) and code else 'action_projection_gap')
            projection, binding = envelope.get('projection'), envelope.get('binding')
            if (envelope.get('status') != 'paired' or type(projection) is not dict or type(binding) is not dict
                    or projection.get('schema') != 'graph-action-grounding-projection-v1'
                    or binding.get('schema') != 'selected-action-projection-binding-v1'
                    or projection.get('fingerprint') != binding.get('action_projection_fingerprint')
                    or projection.get('required_operators') != binding.get('required_operators')
                    or projection.get('hypothesis_scope') != binding.get('hypothesis_scope')):
                return ('gap', None, None, 'action_projection_shape')
            for operator in projection['required_operators']:
                if not self.model.permits(operator):
                    return ('gap', None, None, 'action_permission_missing')
            return ('paired', projection, binding, None)
        except Exception:
            return ('gap', None, None, 'action_projection_failed')

    def _action_learning_carrier(self, context):
        class Stop(Exception):
            pass

        def need(cond, code):
            if not cond:
                raise Stop(code)

        def hx(v):
            return type(v) is str and len(v) == 64 and all(c in '0123456789abcdef' for c in v)

        def st(v, n):
            if type(v) is not str or not 0 < len(v) <= n:
                return False
            v.encode('utf-8')
            return True

        def keys(d, ks):
            return type(d) is dict and set(d) == set(ks)

        def cb(v):
            return self._action_grounding_canonical(v)

        def sha(v):
            return hashlib.sha256(cb(v)).hexdigest()

        idk = ('graph_id', 'root_id', 'effective_graph_sha256', 'view_key', 'base_origin', 'source')
        try:
            envelope = self.model.action_learning_projection
            if envelope is None:
                return (None,) * 6
            need(keys(envelope, ('schema', 'status', 'projection', 'binding', 'gaps'))
                 and envelope['schema'] == 'pack-action-learning-projection-v1',
                 'action_learning_projection_shape')
            gaps = envelope['gaps']
            if envelope['status'] == 'gap':
                need(envelope['projection'] is None and envelope['binding'] is None
                     and type(gaps) is list and len(gaps) > 0
                     and all(keys(g, ('code', 'cause'))
                             and type(g['code']) is str and g['code']
                             and (g['cause'] is None or type(g['cause']) is str)
                             for g in gaps),
                     'action_learning_projection_shape')
                raise Stop('action_learning_projection_gap')
            need(envelope['status'] == 'paired' and type(gaps) is list and len(gaps) == 0
                 and type(envelope['projection']) is dict and type(envelope['binding']) is dict,
                 'action_learning_projection_shape')
            learning = self._action_grounding_plain(envelope['projection'])
            lbind = self._action_grounding_plain(envelope['binding'])
            need(keys(learning, ('schema', 'policy', 'forms', 'render', 'role_labels', 'source_maps',
                                 'provenance', 'parent_action_fingerprint',
                                 'language_projection_fingerprint', 'fingerprint'))
                 and learning['schema'] == 'graph-action-learning-projection-v1'
                 and keys(lbind, ('schema', 'graph_id', 'root_id', 'effective_graph_sha256', 'view_key',
                                  'base_origin', 'source', 'language_projection_fingerprint',
                                  'action_projection_fingerprint',
                                  'action_learning_projection_fingerprint'))
                 and lbind['schema'] == 'selected-action-learning-projection-binding-v1',
                 'action_learning_projection_shape')
            for k in ('policy', 'forms', 'render', 'role_labels', 'source_maps', 'provenance'):
                need(type(learning[k]) is dict, 'action_learning_projection_shape')
            need(learning['policy'].get('schema') == 'lexical-action-learning-policy-v1'
                 and st(learning['policy'].get('policy_id'), 128),
                 'action_learning_projection_shape')

            carrier = self._action_grounding_carrier()
            need(type(carrier) is tuple and len(carrier) == 4 and carrier[0] == 'paired',
                 'action_learning_parent_unavailable')
            action = self._action_grounding_plain(carrier[1])
            abind = self._action_grounding_plain(carrier[2])
            need(keys(action, ('schema', 'catalog', 'surface', 'policy', 'replies', 'required_operators',
                               'hypothesis_scope', 'entry_labels', 'source_maps', 'provenance',
                               'fingerprint', 'catalog_description'))
                 and action['schema'] == 'graph-action-grounding-projection-v1'
                 and keys(abind, ('schema', 'graph_id', 'root_id', 'effective_graph_sha256', 'view_key',
                                  'base_origin', 'source', 'language_projection_fingerprint',
                                  'action_projection_fingerprint', 'required_operators',
                                  'hypothesis_scope'))
                 and abind['schema'] == 'selected-action-projection-binding-v1'
                 and type(action['provenance']) is dict
                 and keys(action['catalog'], ('schema', 'catalog_id', 'graph', 'limits', 'programs'))
                 and action['catalog']['schema'] == 'nai-action-catalog-v1'
                 and type(action['catalog']['graph']) is dict,
                 'action_learning_parent_shape')
            lang = self._action_grounding_plain(self.model.language_projection)
            need(type(lang) is dict and lang.get('schema') == 'graph-dialogue-projection-v1'
                 and hx(lang.get('fingerprint')) and type(lang.get('provenance')) is dict,
                 'action_learning_parent_shape')
            need(cb(action['required_operators']) == cb(abind['required_operators'])
                 and cb(action['hypothesis_scope']) == cb(abind['hypothesis_scope']),
                 'action_learning_parent_shape')

            for k in ('fingerprint',):
                need(hx(action[k]) and hx(learning[k]), 'action_learning_parent_shape')
            need(hx(learning['parent_action_fingerprint']) and hx(learning['language_projection_fingerprint'])
                 and hx(abind['language_projection_fingerprint'])
                 and hx(abind['action_projection_fingerprint'])
                 and hx(lbind['language_projection_fingerprint'])
                 and hx(lbind['action_projection_fingerprint'])
                 and hx(lbind['action_learning_projection_fingerprint'])
                 and hx(lbind['effective_graph_sha256']) and hx(abind['effective_graph_sha256']),
                 'action_learning_parent_shape')

            refs = (action['provenance'], lang['provenance'], learning['provenance'], abind, lbind,
                    action['catalog']['graph'])
            for k in idk:
                for r in refs:
                    need(type(r) is dict and k in r, 'action_learning_identity_mismatch')
                    need(cb(r[k]) == cb(abind[k]), 'action_learning_identity_mismatch')
            need(hx(action['provenance']['effective_graph_sha256']), 'action_learning_identity_mismatch')

            lfp = lang['fingerprint']
            afp = action['fingerprint']
            need(lfp == abind['language_projection_fingerprint']
                 and lfp == lbind['language_projection_fingerprint']
                 and lfp == learning['language_projection_fingerprint'],
                 'action_learning_fingerprint_mismatch')
            need(afp == abind['action_projection_fingerprint']
                 and afp == lbind['action_projection_fingerprint']
                 and afp == learning['parent_action_fingerprint'],
                 'action_learning_fingerprint_mismatch')
            need(keys(action['catalog']['graph'], idk + ('projection_fingerprint',))
                 and action['catalog']['graph'].get('projection_fingerprint') == afp,
                 'action_learning_identity_mismatch')
            cat = action['catalog']
            pre = {'schema': action['schema'], 'required_operators': action['required_operators'],
                   'hypothesis_scope': action['hypothesis_scope'],
                   'catalog': {'catalog_id': cat['catalog_id'], 'limits': cat['limits'],
                               'programs': cat['programs']},
                   'surface': action['surface'], 'policy': action['policy'],
                   'replies': action['replies'], 'entry_labels': action['entry_labels'],
                   'source_maps': action['source_maps'], 'provenance': action['provenance']}
            need(sha(pre) == afp, 'action_learning_fingerprint_mismatch')
            lfp2 = learning['fingerprint']
            need(lfp2 == lbind['action_learning_projection_fingerprint']
                 and sha({k: v for k, v in learning.items() if k != 'fingerprint'}) == lfp2,
                 'action_learning_fingerprint_mismatch')

            need(context.model is self.model and context.installed_memory_head is None,
                 'action_learning_parser_binding_invalid')
            parser_base = context.parser_base_sha256
            grammar = context._grammar()
            need(hx(parser_base) and hx(grammar), 'action_learning_parser_binding_invalid')

            model_content = self._action_grounding_model_value('content_fingerprint')
            model_key = self._action_grounding_model_value('effective_key')
            policy = learning['policy']
            binding = {'schema': 'selected-action-learning-binding-v1',
                       'model_content_sha256': model_content,
                       'model_effective_key': model_key,
                       'graph_id': abind['graph_id'],
                       'root_id': abind['root_id'],
                       'effective_graph_sha256': abind['effective_graph_sha256'],
                       'view_key': abind['view_key'],
                       'base_origin': abind['base_origin'],
                       'source': abind['source'],
                       'language_projection_fingerprint': lfp,
                       'action_projection_fingerprint': afp,
                       'action_learning_projection_fingerprint': lfp2,
                       'catalog_id': cat['catalog_id'],
                       'catalog_sha256': sha({'catalog_id': cat['catalog_id'], 'limits': cat['limits'],
                                              'programs': cat['programs']}),
                       'policy_id': policy['policy_id'],
                       'policy_sha256': sha(policy),
                       'forms_sha256': sha(learning['forms']),
                       'render_sha256': sha(learning['render']),
                       'role_labels_sha256': sha(learning['role_labels']),
                       'parser_base_sha256': parser_base,
                       'parser_grammar_sha256': grammar}
            for k in ('model_content_sha256', 'model_effective_key', 'effective_graph_sha256',
                      'language_projection_fingerprint', 'action_projection_fingerprint',
                      'action_learning_projection_fingerprint', 'catalog_sha256', 'policy_sha256',
                      'forms_sha256', 'render_sha256', 'role_labels_sha256', 'parser_base_sha256',
                      'parser_grammar_sha256'):
                need(hx(binding[k]), 'action_learning_binding_invalid')
            need(st(binding['graph_id'], 1024) and st(binding['root_id'], 1024)
                 and st(binding['catalog_id'], 128) and st(binding['policy_id'], 128),
                 'action_learning_binding_invalid')
            vk = binding['view_key']
            need(type(vk) is list and len(vk) == 2 and type(vk[0]) is int
                 and 0 <= vk[0] <= 2147483647 and ((vk[0] == 0) == (vk[1] is None)),
                 'action_learning_binding_invalid')
            if vk[1] is not None:
                need(st(vk[1], 128), 'action_learning_binding_invalid')
            bo = binding['base_origin']
            need(keys(bo, ('kind', 'build_id')) and bo['kind'] == 'base',
                 'action_learning_binding_invalid')
            if bo['build_id'] is not None:
                need(st(bo['build_id'], 1024), 'action_learning_binding_invalid')
            src = binding['source']
            req = ('status', 'member_path', 'member_sha256', 'base_content_sha256')
            need(type(src) is dict and set(req) <= set(src) <= set(req) | {'base_build_id'}
                 and src['status'] == 'caller_supplied' and st(src['member_path'], 1024)
                 and hx(src['member_sha256']) and hx(src['base_content_sha256']),
                 'action_learning_binding_invalid')
            if src.get('base_build_id') is not None:
                need(st(src['base_build_id'], 1024), 'action_learning_binding_invalid')
            need(len(binding) == 21, 'action_learning_binding_invalid')
            digest = sha(binding)
            return ('paired', self._action_grounding_plain(action), self._action_grounding_plain(learning),
                    self._action_grounding_plain(binding), digest, None)
        except Stop as stop:
            return ('gap', None, None, None, None, stop.args[0])
        except (TypeError, ValueError, KeyError, AttributeError, UnicodeError, OverflowError,
                RecursionError):
            return ('gap', None, None, None, None, 'action_learning_carrier_failed')

    def _action_learning_open(self, context, session_id, conversation_id=None):
        import fcntl
        import inspect
        import stat as stat_mod
        keys = ("status", "gaps", "action_projection", "learning_projection", "binding",
                "graph_binding", "root_path", "archive_path", "ledger_source_id", "lock_fd",
                "lock_held", "ledger", "recorder", "conversation_id", "context_conversation_id",
                "runtime_stamp", "provenance", "closed")

        def blank(status, gaps):
            out = dict.fromkeys(keys)
            out.update(status=status, gaps=gaps, lock_held=False, closed=True)
            return out

        def gap(code):
            return blank("gap", [{"code": code}])

        def ident(value):
            return type(value) is str and 0 < len(value) <= 128

        carrier = self._action_learning_carrier(context)
        if type(carrier) is not tuple or len(carrier) != 6:
            return gap("action_learning_carrier_failed")
        tag, action, learning, binding, digest, carrier_code = carrier
        if tag is None or tag == "absent":
            return blank(None, [])
        if tag == "gap":
            return gap(carrier_code if type(carrier_code) is str and carrier_code
                       else "action_learning_carrier_failed")
        if tag != "paired" or action is None or learning is None or binding is None or digest is None:
            return gap("action_learning_carrier_failed")
        try:
            limits = learning["policy"]["limits"]
            max_bytes = limits["max_archive_bytes"]
            max_events = limits["max_archive_events"]
        except (TypeError, KeyError, AttributeError):
            return gap("action_learning_archive_limits_invalid")
        if (type(max_bytes) is not int or type(max_events) is not int
                or not 0 < max_bytes <= 16777216 or not 0 < max_events <= 65536):
            return gap("action_learning_archive_limits_invalid")
        try:
            from marco.trace import ledger as ledger_mod
            from marco.trace.runtime import TraceContractError
            from marco.runtime.dialogue_trace import DialogueTrace
            read_fn = ledger_mod.read
            ledger_cls = ledger_mod.Ledger
            ledger_error = ledger_mod.LedgerError
            if not callable(read_fn) or "max_bytes" not in inspect.signature(read_fn).parameters:
                return gap("action_learning_archive_dependency_unavailable")
        except (ImportError, AttributeError, TypeError, ValueError):
            return gap("action_learning_archive_dependency_unavailable")
        if not ident(session_id):
            return gap("action_learning_archive_identity_unavailable")
        if conversation_id is not None and not ident(conversation_id):
            return gap("action_learning_archive_identity_unavailable")
        chosen = conversation_id if conversation_id is not None else session_id
        context_conversation = getattr(context, "conversation_id", None)
        if not ident(context_conversation):
            return gap("action_learning_archive_identity_unavailable")
        try:
            model_fp = binding["model_content_sha256"]
            model_key = binding["model_effective_key"]
        except (TypeError, KeyError):
            return gap("action_learning_archive_identity_unavailable")
        overlay_resolved = self.overlay.resolve()
        root = self.learning_root.resolve()
        try:
            root.relative_to(overlay_resolved)
        except ValueError:
            return gap("action_learning_archive_scope_invalid")
        root.mkdir(parents=True, exist_ok=True)
        root = root.resolve()
        archive = (root / "dialogue.jsonl").resolve()
        try:
            root.relative_to(overlay_resolved)
            archive.relative_to(root)
            archive.relative_to(overlay_resolved)
        except ValueError:
            return gap("action_learning_archive_scope_invalid")

        def locator(path):
            return "hypomnema-file:" + hashlib.sha256(os.path.realpath(path).encode("utf-8")).hexdigest()

        res = blank("open", [])
        res.update(closed=False, action_projection=deepcopy(action), learning_projection=deepcopy(learning),
                   binding=deepcopy(binding), graph_binding=digest, root_path=str(root),
                   archive_path=str(archive), conversation_id=chosen,
                   context_conversation_id=context_conversation)

        def run():
            fd = os.open(str(archive), os.O_RDWR | os.O_CREAT, 0o600)
            res["lock_fd"] = fd
            info = os.fstat(fd)
            if not stat_mod.S_ISREG(info.st_mode):
                return "action_learning_archive_not_regular"
            path_info = os.stat(str(archive))
            if (path_info.st_dev, path_info.st_ino) != (info.st_dev, info.st_ino):
                return "action_learning_archive_source_changed"
            fcntl.flock(fd, fcntl.LOCK_EX)
            res["lock_held"] = True
            again = archive.resolve()
            try:
                again.relative_to(root)
                again.relative_to(overlay_resolved)
            except ValueError:
                return "action_learning_archive_source_changed"
            if again != archive:
                return "action_learning_archive_source_changed"
            path_info = os.stat(str(archive))
            info = os.fstat(fd)
            if (path_info.st_dev, path_info.st_ino) != (info.st_dev, info.st_ino):
                return "action_learning_archive_source_changed"
            if info.st_size >= max_bytes:
                return "action_learning_archive_capacity"
            try:
                events, problems = read_fn(archive, max_bytes=max_bytes)
            except ledger_error:
                return "action_learning_archive_invalid"
            if type(events) is not list or type(problems) is not list or problems:
                return "action_learning_archive_invalid"
            if len(events) >= max_events:
                return "action_learning_archive_capacity"
            expected = locator(archive)
            try:
                ledger = ledger_cls(root, name="dialogue.jsonl", runtime={"source_id": expected},
                                    fsync=True)
            except ledger_error:
                return "action_learning_archive_invalid"
            res["ledger"] = ledger
            if ledger.fsync is not True:
                return "action_learning_trace_contract_invalid"
            bound = Path(ledger.path).resolve()
            try:
                bound.relative_to(root)
                bound.relative_to(overlay_resolved)
            except ValueError:
                return "action_learning_archive_scope_invalid"
            bound_info = os.stat(str(bound))
            if (bound_info.st_dev, bound_info.st_ino) != (info.st_dev, info.st_ino):
                return "action_learning_archive_source_changed"
            bound_id = locator(bound)
            if bound_id != expected or ledger.runtime.get("source_id") != bound_id:
                return "action_learning_archive_source_changed"
            stamp = {"model": {"content_fingerprint": model_fp, "effective_key": model_key},
                     "action_learning_binding": deepcopy(binding),
                     "context_conversation_id": context_conversation}
            provenance = {"installed_memory_head": {"attached": False},
                          "partial_sections": ["sources"]}
            try:
                recorder = DialogueTrace(ledger, conversation=chosen, runtime_stamp=stamp,
                                         provenance=provenance)
            except (TraceContractError, ValueError, TypeError):
                return "action_learning_trace_contract_invalid"
            res["recorder"] = recorder
            res["ledger_source_id"] = bound_id
            res["runtime_stamp"] = stamp
            res["provenance"] = provenance
            return None

        try:
            code = run()
        except BaseException as exc:
            self._action_learning_close(res, exc)
            raise
        if code is not None:
            self._action_learning_close(res)
            return gap(code)
        return res

    def _action_learning_close(self, resources, error=None):
        import fcntl
        if resources.get("closed") is True:
            return
        errors = []
        ledger = resources.get("ledger")
        if ledger is not None:
            try:
                ledger.close()
                resources["ledger"] = None
                resources["recorder"] = None
            except BaseException as exc:
                errors.append(exc)
        fd = resources.get("lock_fd")
        if fd is not None:
            try:
                if resources.get("lock_held"):
                    fcntl.flock(fd, fcntl.LOCK_UN)
                    resources["lock_held"] = False
            except BaseException as exc:
                errors.append(exc)
            finally:
                try:
                    os.close(fd)
                    resources["lock_fd"] = None
                    resources["lock_held"] = False
                except BaseException as exc:
                    errors.append(exc)
        if not errors:
            resources["ledger"] = None
            resources["recorder"] = None
            resources["lock_fd"] = None
            resources["lock_held"] = False
            resources["closed"] = True
            return
        if error is not None:
            for item in errors:
                try:
                    error.add_note("archive cleanup failed: %r" % (item,))
                except Exception:
                    pass
            return
        first = errors[0]
        for item in errors[1:]:
            try:
                first.add_note("additional archive cleanup failure: %r" % (item,))
            except Exception:
                pass
        raise first

    def _action_learning_after(self, tx, outcome, adjunct, resource):
        """Source-only partial hook: three nested input utilities. NONACTIVATABLE."""

        def _al_load():
            gap = lambda code, path=None: {'code': code, 'path': path, 'candidate_id': None,
                                           'pending_id': None}
            ident = lambda v: type(v) is str and 0 < len(v) <= 128
            cb = self._action_grounding_canonical
            import stat as stat_mod
            try:
                from marco.trace import ledger as ledger_mod
                from marco.trace import runtime as rtm
                from marco.runtime.dialogue_trace import DialogueTrace, Attempt
                from marco.learning.memory import LearningMemory
            except ImportError:
                return None, gap('action_learning_archive_dependency_unavailable')
            try:
                context = tx['context']
            except (TypeError, KeyError):
                return None, gap('action_learning_context_unavailable')
            carrier = self._action_learning_carrier(context)
            if type(carrier) is not tuple or len(carrier) != 6:
                return None, gap('action_learning_carrier_failed')
            tag, action, learning, binding, digest, ccode = carrier
            if tag is None or tag == 'absent':
                return None, None
            if tag == 'gap':
                return None, gap(ccode if ident(ccode) else 'action_learning_carrier_failed')
            if tag != 'paired' or action is None or learning is None or binding is None or digest is None:
                return None, gap('action_learning_carrier_failed')
            res = resource
            keys22 = ('status', 'gaps', 'action_projection', 'learning_projection', 'binding',
                      'graph_binding', 'root_path', 'archive_path', 'ledger_source_id', 'lock_fd',
                      'lock_held', 'ledger', 'recorder', 'conversation_id', 'context_conversation_id',
                      'runtime_stamp', 'provenance', 'closed', 'attempt', 'memory', 'base_parser',
                      'previous_head')
            if type(res) is not dict or set(res) != set(keys22):
                return None, gap('action_learning_resource_shape')
            fd = res['lock_fd']
            if (res['status'] != 'open' or type(res['gaps']) is not list or res['gaps']
                    or res['closed'] is not False or res['lock_held'] is not True
                    or type(fd) is not int):
                return None, gap('action_learning_resource_not_open')
            try:
                if (cb(res['action_projection']) != cb(action) or cb(res['learning_projection']) != cb(learning)
                        or cb(res['binding']) != cb(binding) or res['graph_binding'] != digest):
                    return None, gap('action_learning_binding_mismatch')
            except (TypeError, ValueError):
                return None, gap('action_learning_binding_mismatch')
            try:
                host = rtm.plain_json(self._action_grounding_host_binding(context, binding), 'host_binding')
                if (type(host) is not dict or set(host) != set(self._ACTION_BINDING_KEYS)
                        or host['installed_memory_head'] is not None
                        or not ident(host['conversation_id'])
                        or host['conversation_id'] != context.conversation_id):
                    return None, gap('action_learning_host_binding_invalid')
                for k in ('model_content_sha256', 'model_effective_key', 'graph_id', 'root_id',
                          'effective_graph_sha256', 'view_key', 'language_projection_fingerprint',
                          'action_projection_fingerprint', 'parser_base_sha256', 'parser_grammar_sha256'):
                    if cb(host[k]) != cb(binding[k]):
                        return None, gap('action_learning_host_binding_invalid')
            except (TypeError, ValueError, KeyError, AttributeError, OverflowError, RecursionError):
                return None, gap('action_learning_host_binding_invalid')
            ledger, recorder, attempt = res['ledger'], res['recorder'], res['attempt']
            if (type(ledger) is not ledger_mod.Ledger or type(recorder) is not DialogueTrace
                    or type(attempt) is not Attempt or type(res['memory']) is not LearningMemory):
                return None, gap('action_learning_type_identity_invalid')
            if (context.model is not self.model or context.installed_memory_head is not None
                    or res['base_parser'] is None
                    or context._parser_instance is not res['base_parser']):
                return None, gap('action_learning_parser_binding_invalid')
            head = res['previous_head']
            if (type(head) is not dict or set(head) != {'seq', 'change_id'} or type(head['seq']) is not int
                    or head['seq'] < 0 or (head['seq'] == 0) != (head['change_id'] is None)
                    or (head['change_id'] is not None and not ident(head['change_id']))):
                return None, gap('action_learning_previous_head_invalid')
            honest = {'installed_memory_head': {'attached': False}, 'partial_sections': ['sources']}
            base_stamp = {'model': {'content_fingerprint': binding['model_content_sha256'],
                                    'effective_key': binding['model_effective_key']},
                          'action_learning_binding': deepcopy(binding),
                          'context_conversation_id': context.conversation_id}
            augmented = dict(base_stamp)
            augmented['action_binding'] = deepcopy(host)
            try:
                if (not ident(res['conversation_id']) or not ident(res['context_conversation_id'])
                        or res['context_conversation_id'] != context.conversation_id
                        or cb(rtm.plain_json(res['provenance'], 'provenance')) != cb(honest)
                        or cb(rtm.plain_json(res['runtime_stamp'], 'runtime_stamp')) != cb(base_stamp)):
                    return None, gap('action_learning_identity_invalid')
                if (recorder.ledger is not ledger or recorder.conversation != res['conversation_id']
                        or cb(rtm.plain_json(recorder.runtime_stamp, 'runtime_stamp')) != cb(base_stamp)
                        or cb(rtm.plain_json(recorder.provenance, 'provenance')) != cb(honest)):
                    return None, gap('action_learning_recorder_invalid')
                if (not ident(attempt.attempt_id) or not ident(attempt.input_id) or not ident(attempt.trace_id)
                        or type(attempt.text) is not str or attempt.conversation != res['conversation_id']
                        or type(attempt.turn) is not int or not 1 <= attempt.turn <= 65536
                        or type(attempt.runtime_stamp) is not dict or type(attempt.provenance) is not dict):
                    return None, gap('action_learning_attempt_invalid')
                if (cb(rtm.plain_json(attempt.runtime_stamp, 'runtime_stamp')) != cb(augmented)
                        or cb(rtm.plain_json(attempt.provenance, 'provenance')) != cb(honest)):
                    return None, gap('action_learning_attempt_invalid')
            except (TypeError, ValueError, AttributeError, OverflowError, RecursionError):
                return None, gap('action_learning_identity_invalid')
            if ledger.fsync is not True:
                return None, gap('action_learning_trace_contract_invalid')
            if getattr(ledger, '_broken', False) is True:
                raise OSError('ledger writer invalidated by an earlier write/fsync failure; '
                              'close and reopen it')
            if type(res['root_path']) is not str or type(res['archive_path']) is not str:
                return None, gap('action_learning_archive_scope_invalid')
            overlay = self.overlay.resolve()
            root = Path(res['root_path']).resolve()
            arch = Path(res['archive_path']).resolve()
            bound = Path(ledger.path).resolve()
            try:
                root.relative_to(overlay)
                arch.relative_to(root)
                arch.relative_to(overlay)
                bound.relative_to(root)
            except ValueError:
                return None, gap('action_learning_archive_scope_invalid')
            if bound != arch or self.learning_root.resolve() != root:
                return None, gap('action_learning_archive_source_changed')
            info = os.fstat(fd)
            pinfo = os.stat(str(arch))
            if not stat_mod.S_ISREG(info.st_mode):
                return None, gap('action_learning_archive_not_regular')
            if (pinfo.st_dev, pinfo.st_ino) != (info.st_dev, info.st_ino):
                return None, gap('action_learning_archive_source_changed')
            source_id = 'hypomnema-file:' + hashlib.sha256(
                os.path.realpath(ledger.path).encode('utf-8')).hexdigest()
            if (res['ledger_source_id'] != source_id or ledger.runtime.get('source_id') != source_id):
                return None, gap('action_learning_archive_source_changed')
            try:
                lim = learning['policy']['limits']
                raw_b, raw_e = lim['max_archive_bytes'], lim['max_archive_events']
            except (TypeError, KeyError, AttributeError):
                return None, gap('action_learning_archive_limits_invalid')
            if (type(lim) is not dict or type(raw_b) is not int or type(raw_e) is not int
                    or raw_b <= 0 or raw_e <= 0):
                return None, gap('action_learning_archive_limits_invalid')
            max_bytes, max_events = min(raw_b, 16777216), min(raw_e, 65536)
            try:
                events, problems = ledger_mod.read(arch, max_bytes=max_bytes)
            except ledger_mod.LedgerError:
                return None, gap('action_learning_archive_invalid')
            if type(events) is not list or type(problems) is not list or problems:
                return None, gap('action_learning_archive_invalid')
            if len(events) > max_events:
                return None, gap('action_learning_archive_capacity')
            by_id, positions = {}, {}
            withdrawn, superseded, error_traces = set(), set(), set()
            for i, ev in enumerate(events):
                by_id[ev['event_id']] = ev
                positions[ev['event_id']] = i
                if ev.get('supersedes') is not None:
                    superseded.add(ev['supersedes'])
                if ev['kind'] == 'conclusion_withdrawn':
                    old = ev['payload']['withdrawn']
                    if type(old) is not str:
                        return None, gap('action_learning_archive_invalid')
                    withdrawn.add(old)
                if ev['kind'] == 'error':
                    error_traces.add(ev['trace_id'])
            archive = {'action_projection': deepcopy(action), 'learning_projection': deepcopy(learning),
                       'binding': deepcopy(binding), 'graph_binding': digest,
                       'limits': deepcopy(lim),
                       'host_binding': host, 'ledger_source_id': source_id, 'events': events,
                       'by_id': by_id, 'positions': positions, 'withdrawn': withdrawn,
                       'superseded': superseded, 'error_traces': error_traces,
                       'current_input': None}
            current, found = _al_input(archive, attempt.input_id, current=True)
            if found is not None:
                return None, found
            archive['current_input'] = current
            return archive, None

        def _al_ancestors(archive, event_id):
            gap = lambda code, path=None: {'code': code, 'path': path, 'candidate_id': None,
                                           'pending_id': None}
            if type(event_id) is not str or not 0 < len(event_id) <= 128:
                return None, gap('action_learning_ancestor_id_invalid')
            events, positions = archive['events'], archive['positions']
            cap = min(len(events), archive['limits']['max_archive_events'])
            order, seen, i = [event_id], {event_id}, 0
            while i < len(order):
                cur = order[i]
                i += 1
                pos = positions.get(cur)
                if type(pos) is not int or not 0 <= pos < len(events):
                    return None, gap('action_learning_ancestor_missing', 'parent_ids')
                ev = events[pos]
                if (cur in archive['withdrawn'] or cur in archive['superseded']
                        or ev['trace_id'] in archive['error_traces']):
                    return None, gap('action_learning_ancestor_invalid', 'parent_ids')
                for pid in ev['parent_ids']:
                    ppos = positions.get(pid)
                    if type(ppos) is not int or ppos >= pos:
                        return None, gap('action_learning_ancestor_missing', 'parent_ids')
                    if pid not in seen:
                        seen.add(pid)
                        order.append(pid)
                        if len(order) > cap:
                            return None, gap('action_learning_ancestor_bound', 'parent_ids')
            return set(order[1:]), None

        def _al_input(archive, event_id, *, current=False):
            gap = lambda code, path=None: {'code': code, 'path': path, 'candidate_id': None,
                                           'pending_id': None}
            ident = lambda v: type(v) is str and 0 < len(v) <= 128
            cb = self._action_grounding_canonical
            if not ident(event_id):
                return None, gap('action_learning_input_id_invalid')
            pos = archive['positions'].get(event_id)
            if type(pos) is not int:
                return None, gap('action_learning_input_missing')
            event = archive['events'][pos]
            _anc, found = _al_ancestors(archive, event_id)
            if found is not None:
                return None, found
            if (event['kind'] != 'input_received' or event['status'] != 'success'
                    or event['epistemic_status'] != 'reported' or event['subsystem'] != 'dialogue'):
                return None, gap('action_learning_input_kind_invalid')
            payload, source, runtime = event['payload'], event['source'], event['runtime']
            raw, conv = payload.get('text'), payload.get('conversation')
            turn, aid = payload.get('turn'), payload.get('attempt_id')
            trace_id = event['trace_id']
            if (type(raw) is not str or not ident(conv) or not ident(aid) or not ident(trace_id)
                    or type(turn) is not int or not 1 <= turn <= 65536):
                return None, gap('action_learning_input_shape', 'payload')
            try:
                raw_bytes = raw.encode('utf-8')
            except UnicodeError:
                return None, gap('action_learning_input_shape', 'payload.text')
            lim = archive['limits']
            mib = lim.get('max_input_bytes') if type(lim) is dict else None
            if type(mib) is not int or mib <= 0:
                return None, gap('action_learning_archive_limits_invalid', 'limits.max_input_bytes')
            if len(raw_bytes) > min(mib, 32768) or len(raw) > 32768:
                return None, gap('action_learning_input_too_long', 'payload.text')
            legacy = hashlib.sha256(raw.strip().encode('utf-8')).hexdigest()
            if payload.get('sha256') != legacy:
                return None, gap('action_learning_input_digest_mismatch', 'payload.sha256')
            if (source.get('type') != 'dialogue_turn' or source.get('conversation') != conv
                    or type(source.get('turn')) is not int or source.get('turn') != turn):
                return None, gap('action_learning_input_source_mismatch', 'source')
            if runtime.get('source_id') != archive['ledger_source_id']:
                return None, gap('action_learning_input_source_mismatch', 'runtime.source_id')
            declared = runtime.get('declared_runtime')
            if type(declared) is not dict:
                return None, gap('action_learning_input_runtime_invalid', 'runtime.declared_runtime')
            try:
                if cb(declared.get('action_learning_binding')) != cb(archive['binding']):
                    return None, gap('action_learning_input_runtime_invalid',
                                     'runtime.declared_runtime.action_learning_binding')
            except (TypeError, ValueError):
                return None, gap('action_learning_input_runtime_invalid',
                                 'runtime.declared_runtime.action_learning_binding')
            context_cid = declared.get('context_conversation_id')
            if not ident(context_cid):
                return None, gap('action_learning_input_runtime_invalid',
                                 'runtime.declared_runtime.context_conversation_id')
            head = payload.get('installed_memory_head')
            if not (head is None or (type(head) is dict and cb(head) == cb({'attached': False}))):
                return None, gap('action_learning_input_head_invalid', 'payload.installed_memory_head')
            if current:
                from marco.trace import runtime as rtm
                attempt, recorder = resource['attempt'], resource['recorder']
                honest = {'installed_memory_head': {'attached': False}, 'partial_sections': ['sources']}
                try:
                    stamp = rtm.plain_json(attempt.runtime_stamp, 'runtime_stamp')
                    prov = rtm.plain_json(attempt.provenance, 'provenance')
                    first = rtm.contract_provenance(stamp, prov)['first']
                    expected_sel = cb(first['selected'])
                    expected_decl = cb(first['declared_runtime'])
                    actual_sel = cb(rtm.plain_json(runtime.get('selected'), 'selected'))
                    actual_decl = cb(rtm.plain_json(declared, 'declared_runtime'))
                    decl_binding = cb(declared.get('action_binding'))
                    decl_learning = cb(declared.get('action_learning_binding'))
                    stamp_binding = cb(stamp.get('action_binding'))
                    host_c = cb(archive['host_binding'])
                    binding_c = cb(archive['binding'])
                    prov_c = cb(prov)
                    head_c = cb(prov.get('installed_memory_head'))
                except (TypeError, ValueError, AttributeError, OverflowError, RecursionError):
                    return None, gap('action_learning_attempt_runtime_invalid')
                if (attempt.input_id != event_id or attempt.trace_id != trace_id
                        or attempt.text != raw or attempt.attempt_id != aid
                        or attempt.conversation != conv or attempt.turn != turn
                        or recorder.conversation != conv or resource['conversation_id'] != conv
                        or context_cid != resource['context_conversation_id']):
                    return None, gap('action_learning_attempt_mismatch')
                if actual_sel != expected_sel or actual_decl != expected_decl:
                    return None, gap('action_learning_attempt_runtime_invalid', 'runtime')
                if decl_binding != host_c or stamp_binding != host_c:
                    return None, gap('action_learning_attempt_runtime_invalid',
                                     'runtime.declared_runtime.action_binding')
                if decl_learning != binding_c:
                    return None, gap('action_learning_attempt_runtime_invalid',
                                     'runtime.declared_runtime.action_learning_binding')
                if (type(head) is not dict or cb(head) != cb({'attached': False})
                        or head_c != cb({'attached': False}) or prov_c != cb(honest)):
                    return None, gap('action_learning_attempt_provenance_invalid',
                                     'payload.installed_memory_head')
                for e in archive['events']:
                    if ((e['kind'] == 'output_created'
                         or e['kind'] == 'error' and e['payload'].get('terminal') is True)
                            and e['payload'].get('attempt_id') == aid):
                        return None, gap('action_learning_attempt_terminal')
            return {'event_id': event_id, 'conversation_id': conv, 'context_conversation_id': context_cid,
                    'turn': turn, 'attempt_id': aid, 'trace_id': trace_id, 'text': raw,
                    'raw_sha256': hashlib.sha256(raw_bytes).hexdigest(),
                    'legacy_sha256': legacy}, None

        def _al_output(archive, event_id):
            gap = lambda code, path=None: {'code': code, 'path': path, 'candidate_id': None,
                                           'pending_id': None}
            ident = lambda v: type(v) is str and 0 < len(v) <= 128
            if not ident(event_id):
                return None, gap('action_learning_output_id_invalid')
            pos = archive['positions'].get(event_id)
            if type(pos) is not int:
                return None, gap('action_learning_output_missing')
            event = archive['events'][pos]
            anc, found = _al_ancestors(archive, event_id)
            if found is not None:
                return None, found
            if (event['kind'] != 'output_created' or event['subsystem'] != 'dialogue'
                    or event['status'] not in ('answered', 'recorded', 'hold')):
                return None, gap('action_learning_output_kind_invalid')
            payload, runtime = event['payload'], event['runtime']
            if type(payload) is not dict or type(runtime) is not dict:
                return None, gap('action_learning_output_shape', 'payload')
            raw, conv = payload.get('text'), payload.get('conversation')
            turn, aid = payload.get('turn'), payload.get('attempt_id')
            trace_id = event['trace_id']
            if (type(raw) is not str or not ident(conv) or not ident(aid) or not ident(trace_id)
                    or type(turn) is not int or not 1 <= turn <= 65536):
                return None, gap('action_learning_output_shape', 'payload')
            if payload.get('status') != event['status']:
                return None, gap('action_learning_output_status_mismatch', 'payload.status')
            if runtime.get('source_id') != archive['ledger_source_id']:
                return None, gap('action_learning_output_source_mismatch', 'runtime.source_id')
            try:
                raw_bytes = raw.encode('utf-8')
            except UnicodeError:
                return None, gap('action_learning_output_shape', 'payload.text')
            lim = archive['limits']
            mqb = lim.get('max_question_bytes') if type(lim) is dict else None
            if type(mqb) is not int or mqb <= 0:
                return None, gap('action_learning_archive_limits_invalid', 'limits.max_question_bytes')
            if len(raw_bytes) > min(mqb, 65536):
                return None, gap('action_learning_output_too_long', 'payload.text')
            if payload.get('sha256') != hashlib.sha256(raw.strip().encode('utf-8')).hexdigest():
                return None, gap('action_learning_output_digest_mismatch', 'payload.sha256')
            prov = payload.get('provenance')
            if type(prov) is not dict:
                return None, gap('action_learning_output_provenance_invalid', 'payload.provenance')
            try:
                self._action_grounding_canonical(prov)
                prov = deepcopy(prov)
            except (TypeError, ValueError, OverflowError, RecursionError):
                return None, gap('action_learning_output_provenance_invalid', 'payload.provenance')
            matches = []
            for e in archive['events']:
                if e['kind'] != 'input_received' or e['trace_id'] != trace_id:
                    continue
                p = e['payload']
                if (p.get('attempt_id') == aid and p.get('conversation') == conv
                        and type(p.get('turn')) is int and p.get('turn') == turn):
                    matches.append(e['event_id'])
            if len(matches) != 1:
                return None, gap('action_learning_output_input_ambiguous', 'trace_id')
            iid = matches[0]
            if iid not in anc:
                return None, gap('action_learning_output_input_not_ancestor', 'parent_ids')
            inp, found = _al_input(archive, iid)
            if found is not None:
                return None, found
            if (inp['attempt_id'] != aid or inp['trace_id'] != trace_id
                    or inp['conversation_id'] != conv or inp['turn'] != turn):
                return None, gap('action_learning_output_input_mismatch', 'payload')
            return {'event_id': event_id, 'input_id': iid, 'conversation_id': conv, 'turn': turn,
                    'attempt_id': aid, 'trace_id': trace_id, 'text': raw,
                    'provenance': prov}, None

        def _al_questions(archive):
            gap = lambda code, path=None: {'code': code, 'path': path, 'candidate_id': None,
                                           'pending_id': None}
            ident = lambda v: type(v) is str and 0 < len(v) <= 128
            hx = lambda v: (type(v) is str and len(v) == 64
                            and all(c in '0123456789abcdef' for c in v))
            cb = self._action_grounding_canonical
            lim = archive['limits']
            if type(lim) is not dict:
                return None, gap('action_learning_archive_limits_invalid', 'limits')
            mtb, mqb, maq = (lim.get('max_target_bytes'), lim.get('max_question_bytes'),
                             lim.get('max_active_questions'))
            for v in (mtb, mqb, maq):
                if type(v) is not int or v <= 0:
                    return None, gap('action_learning_archive_limits_invalid', 'limits')
            current = archive['current_input']
            if type(current) is not dict:
                return None, gap('action_learning_current_input_invalid')
            cur_pos = archive['positions'].get(current['event_id'])
            if type(cur_pos) is not int:
                return None, gap('action_learning_current_input_invalid')
            cur_conv, cur_ctx = current['conversation_id'], current['context_conversation_id']
            learning, binding = archive['learning_projection'], archive['binding']
            try:
                template = learning['render']['question']
                template_sha = hashlib.sha256(template.encode('utf-8')).hexdigest()
                learn_fp = binding['action_learning_projection_fingerprint']
                binding_c = cb(binding)
            except (TypeError, KeyError, AttributeError, UnicodeError, ValueError):
                return None, gap('action_learning_question_declaration_invalid')
            keys13 = ('schema', 'pending_id', 'initiating_input_id', 'pending_creation_output_id',
                      'context_conversation_id', 'target', 'target_sha256', 'selection',
                      'learning_declaration_sha256', 'question_template_id',
                      'question_template_sha256', 'rendered_text_sha256', 'question_span')
            keys5 = ('schema', 'surface', 'role_pattern', 'role_pattern_sha256', 'terms')
            events, positions = archive['events'], archive['positions']
            rows, seen_in, seen_att = [], set(), set()
            for opos, ev in enumerate(events[:cur_pos]):
                if ev['kind'] != 'output_created':
                    continue
                payload = ev['payload']
                if type(payload) is not dict:
                    continue
                prov = payload.get('provenance')
                if type(prov) is not dict or 'meaning_question' not in prov:
                    continue
                oid = ev['event_id']
                # 1. actual owner facts of the output row (its own payload/trace, not question metadata)
                conv, turn, aid = payload.get('conversation'), payload.get('turn'), payload.get('attempt_id')
                trace_id = ev['trace_id']
                if (not ident(conv) or not ident(aid) or not ident(trace_id)
                        or type(turn) is not int or not 1 <= turn <= 65536):
                    return None, gap('action_learning_question_source_shape', 'payload')
                matches = []
                for e in events:
                    if e['kind'] != 'input_received' or e['trace_id'] != trace_id:
                        continue
                    p = e['payload']
                    if type(p) is not dict:
                        continue
                    if (p.get('attempt_id') == aid and p.get('conversation') == conv
                            and type(p.get('turn')) is int and p.get('turn') == turn):
                        matches.append(e['event_id'])
                if len(matches) != 1:
                    return None, gap('action_learning_question_source_ambiguous', 'trace_id')
                iid = matches[0]
                ipos = positions.get(iid)
                if type(ipos) is not int or not 0 <= ipos < opos:
                    return None, gap('action_learning_question_source_order', 'payload')
                anc, found = _al_ancestors(archive, oid)
                if found is not None:
                    return None, found
                if iid not in anc:
                    return None, gap('action_learning_question_source_not_ancestor', 'parent_ids')
                _ianc, found = _al_ancestors(archive, iid)
                if found is not None:
                    return None, found
                # 2. preliminary owner-input validation from its own actual source facts
                ie = events[ipos]
                if (ie['kind'] != 'input_received' or ie['status'] != 'success'
                        or ie['epistemic_status'] != 'reported' or ie['subsystem'] != 'dialogue'):
                    return None, gap('action_learning_question_source_kind_invalid')
                ip, isrc, irt = ie['payload'], ie['source'], ie['runtime']
                if type(ip) is not dict or type(isrc) is not dict or type(irt) is not dict:
                    return None, gap('action_learning_question_source_shape', 'payload')
                raw = ip.get('text')
                iconv, iturn, iaid = ip.get('conversation'), ip.get('turn'), ip.get('attempt_id')
                if (type(raw) is not str or not ident(iconv) or not ident(iaid)
                        or type(iturn) is not int or not 1 <= iturn <= 65536
                        or iconv != conv or iaid != aid or iturn != turn):
                    return None, gap('action_learning_question_source_shape', 'payload')
                try:
                    raw.encode('utf-8')
                except UnicodeError:
                    return None, gap('action_learning_question_source_shape', 'payload.text')
                if ip.get('sha256') != hashlib.sha256(raw.strip().encode('utf-8')).hexdigest():
                    return None, gap('action_learning_question_source_digest_mismatch', 'payload.sha256')
                if (isrc.get('type') != 'dialogue_turn' or isrc.get('conversation') != iconv
                        or type(isrc.get('turn')) is not int or isrc.get('turn') != iturn):
                    return None, gap('action_learning_question_source_mismatch', 'source')
                if irt.get('source_id') != archive['ledger_source_id']:
                    return None, gap('action_learning_question_source_mismatch', 'runtime.source_id')
                declared = irt.get('declared_runtime')
                if type(declared) is not dict:
                    return None, gap('action_learning_question_source_runtime_invalid',
                                     'runtime.declared_runtime')
                ictx = declared.get('context_conversation_id')
                if not ident(ictx):
                    return None, gap('action_learning_question_source_runtime_invalid',
                                     'runtime.declared_runtime.context_conversation_id')
                # 3. actual scope: a proven foreign conversation/Context owner is unrelated
                if iconv != cur_conv or ictx != cur_ctx:
                    continue
                # 4. chronology: first actual same-conversation input after the delivered output
                first = None
                for e in events[opos + 1:]:
                    if e['kind'] != 'input_received':
                        continue
                    p = e['payload']
                    if type(p) is not dict:
                        return None, gap('action_learning_question_chronology_invalid', 'payload')
                    pc = p.get('conversation')
                    if not ident(pc):
                        return None, gap('action_learning_question_chronology_invalid',
                                         'payload.conversation')
                    if pc == cur_conv:
                        first = e['event_id']
                        break
                if first is None:
                    return None, gap('action_learning_question_chronology_invalid', 'payload')
                if first != current['event_id']:
                    continue
                # 5. eligible current scope: full current-binding/source validation
                out, found = _al_output(archive, oid)
                if found is not None:
                    return None, found
                if (out['input_id'] != iid or out['conversation_id'] != conv or out['turn'] != turn
                        or out['attempt_id'] != aid or out['trace_id'] != trace_id):
                    return None, gap('action_learning_question_source_mismatch', 'payload')
                qin, found = _al_input(archive, iid)
                if found is not None:
                    return None, found
                if (qin['conversation_id'] != cur_conv or qin['context_conversation_id'] != cur_ctx
                        or type(current['turn']) is not int or qin['turn'] >= current['turn']):
                    return None, gap('action_learning_question_chronology_invalid', 'payload.turn')
                meta = out['provenance']['meaning_question']
                if type(meta) is not dict or set(meta) != set(keys13):
                    return None, gap('action_learning_question_metadata_shape', 'meaning_question')
                if (meta['schema'] != 'lexical-action-meaning-question-v1'
                        or not ident(meta['pending_id']) or not ident(meta['initiating_input_id'])
                        or not (meta['pending_creation_output_id'] is None
                                or ident(meta['pending_creation_output_id']))
                        or not ident(meta['context_conversation_id'])):
                    return None, gap('action_learning_question_metadata_invalid', 'meaning_question')
                if meta['context_conversation_id'] != qin['context_conversation_id']:
                    return None, gap('action_learning_question_context_mismatch',
                                     'meaning_question.context_conversation_id')
                if (not hx(meta['target_sha256']) or not hx(meta['learning_declaration_sha256'])
                        or not hx(meta['question_template_sha256'])
                        or not hx(meta['rendered_text_sha256'])
                        or meta['question_template_id'] != 'question'):
                    return None, gap('action_learning_question_metadata_invalid', 'meaning_question')
                target = meta['target']
                if (type(target) is not dict or set(target) != set(keys5)
                        or target['schema'] != 'lexical-action-meaning-target-v1'):
                    return None, gap('action_learning_question_target_invalid', 'meaning_question.target')
                stack, nodes = [target], 0
                while stack:
                    v = stack.pop()
                    nodes += 1
                    t = type(v)
                    if nodes > 65536 or t not in (dict, list, str, int, bool, type(None)):
                        return None, gap('action_learning_question_target_invalid',
                                         'meaning_question.target')
                    if t is dict:
                        if any(type(k) is not str for k in v):
                            return None, gap('action_learning_question_target_invalid',
                                             'meaning_question.target')
                        stack.extend(v.values())
                    elif t is list:
                        stack.extend(v)
                try:
                    tb = cb(target)
                    sel_c = cb(meta['selection'])
                except (TypeError, ValueError, OverflowError, RecursionError):
                    return None, gap('action_learning_question_target_invalid', 'meaning_question')
                if len(tb) > min(mtb, 32768) or hashlib.sha256(tb).hexdigest() != meta['target_sha256']:
                    return None, gap('action_learning_question_target_digest', 'meaning_question.target')
                if sel_c != binding_c:
                    return None, gap('action_learning_question_selection_mismatch',
                                     'meaning_question.selection')
                if (meta['learning_declaration_sha256'] != learn_fp
                        or meta['question_template_sha256'] != template_sha):
                    return None, gap('action_learning_question_declaration_mismatch',
                                     'meaning_question')
                text = out['text']
                tbytes = text.encode('utf-8')
                if len(tbytes) > min(mqb, 65536) or len(text) > 65536:
                    return None, gap('action_learning_question_too_long', 'payload.text')
                if hashlib.sha256(tbytes).hexdigest() != meta['rendered_text_sha256']:
                    return None, gap('action_learning_question_text_digest', 'meaning_question')
                span = meta['question_span']
                if (type(span) is not list or len(span) != 2 or type(span[0]) is not int
                        or type(span[1]) is not int or not 0 <= span[0] < span[1] <= len(text)):
                    return None, gap('action_learning_question_span_invalid',
                                     'meaning_question.question_span')
                if iid in seen_in or aid in seen_att:
                    return None, gap('action_learning_question_competing', 'meaning_question')
                seen_in.add(iid)
                seen_att.add(aid)
                rows.append({'question_output_id': oid, 'question_input_id': iid,
                             'metadata': deepcopy(meta), 'output_text': text})
            if len(rows) > maq:
                return None, gap('action_learning_question_ambiguous', 'meaning_question')
            return rows, None

        def _al_pending(archive, item):
            gap = lambda code, path=None: {'code': code, 'path': path, 'candidate_id': None,
                                           'pending_id': None}
            ident = lambda v: type(v) is str and 0 < len(v) <= 128
            hx = lambda v: (type(v) is str and len(v) == 64
                            and all(c in '0123456789abcdef' for c in v))
            turnok = lambda v: type(v) is int and 1 <= v <= 65536
            cb = self._action_grounding_canonical
            try:
                from marco.storage.snapshot import SnapshotError, validate_action_grounding_state
            except ImportError:
                return None, gap('action_learning_pending_dependency_unavailable')
            keys9 = ('id', 'text', 'created_input_turn', 'pre_observation_refs', 'binding', 'reading',
                     'original_outcome', 'status', 'reason')
            keys7 = ('schema', 'pending_id', 'source_input_id', 'context_conversation_id',
                     'created_input_turn', 'raw_text_sha256', 'binding_sha256')
            if type(item) is not dict or set(item) != set(keys9) or not ident(item['id']):
                return None, gap('action_learning_pending_item_invalid')
            state, post = tx['state'], tx['post']
            if type(state) is not dict or type(post) is not dict:
                return None, gap('action_learning_pending_state_unavailable')
            try:
                valid = validate_action_grounding_state(state, post)
            except (SnapshotError, TypeError, ValueError, KeyError, AttributeError, OverflowError,
                    RecursionError):
                return None, gap('action_learning_pending_state_invalid')
            host, current = archive['host_binding'], archive['current_input']
            if type(host) is not dict or type(current) is not dict:
                return None, gap('action_learning_current_input_invalid')
            try:
                same = [p for p in state['pending'] if type(p) is dict and p.get('id') == item['id']]
                if (len(same) != 1 or cb(same[0]) != cb(item) or cb(valid) != cb(state)
                        or cb(item['binding']) != cb(host) or cb(state['binding']) != cb(host)):
                    return None, gap('action_learning_pending_state_mismatch')
                bind_sha = hashlib.sha256(cb(item['binding'])).hexdigest()
                text_sha = hashlib.sha256(item['text'].encode('utf-8')).hexdigest()
            except (TypeError, ValueError, KeyError, AttributeError, UnicodeError, OverflowError,
                    RecursionError):
                return None, gap('action_learning_pending_state_mismatch')
            cturn, sturn = item['created_input_turn'], state['input_turn']
            if (item['status'] != 'active' or item['reason'] is not None
                    or host['installed_memory_head'] is not None or not turnok(cturn)
                    or not turnok(sturn) or cturn > sturn or len(item['text']) > 512
                    or host['conversation_id'] != current['context_conversation_id']):
                return None, gap('action_learning_pending_item_invalid')
            if cturn == sturn:
                if (item['text'] != current['text'] or text_sha != current['raw_sha256']
                        or current['conversation_id'] != resource['conversation_id']
                        or current['context_conversation_id'] != resource['context_conversation_id']):
                    return None, gap('action_learning_pending_current_mismatch')
                prior = tx['prior_state']
                if prior is not None:
                    try:
                        pv = validate_action_grounding_state(prior)
                    except (SnapshotError, TypeError, ValueError, KeyError, AttributeError,
                            OverflowError, RecursionError):
                        return None, gap('action_learning_pending_prior_invalid')
                    if any(p['id'] == item['id'] for p in pv['pending']):
                        return None, gap('action_learning_pending_conflict')
                reading = item['reading']
                try:
                    joined = (item['id'] == 'a%d' % (state['next_pending'] - 1)
                              and state['pending'] and state['pending'][-1] is not None
                              and cb(state['pending'][-1]) == cb(item)
                              and cb(item['pre_observation_refs']) == cb(tx['pre_refs'])
                              and cb(item['original_outcome']) == cb(tx['original_outcome'])
                              and type(reading) is dict and reading.get('status') == 'read'
                              and reading.get('search_complete') is True
                              and reading.get('truncated') is False
                              and type(reading.get('role_candidates')) is list
                              and bool(reading['role_candidates']))
                except (TypeError, ValueError, KeyError, AttributeError, OverflowError, RecursionError):
                    joined = False
                if not joined:
                    return None, gap('action_learning_pending_current_producer_mismatch')
                return {'source': {'schema': 'contextual-action-pending-source-v1',
                                   'pending_id': item['id'], 'source_input_id': current['event_id'],
                                   'context_conversation_id': current['context_conversation_id'],
                                   'created_input_turn': cturn, 'raw_text_sha256': current['raw_sha256'],
                                   'binding_sha256': bind_sha},
                        'pending_creation_output_id': None}, None
            events, positions = archive['events'], archive['positions']
            cur_pos = positions.get(current['event_id'])
            if type(cur_pos) is not int:
                return None, gap('action_learning_current_input_invalid')
            cur_conv, cur_ctx = current['conversation_id'], current['context_conversation_id']
            found_rows = []
            for opos, ev in enumerate(events[:cur_pos]):
                if ev['kind'] != 'output_created':
                    continue
                payload = ev['payload']
                if type(payload) is not dict:
                    continue
                prov = payload.get('provenance')
                if type(prov) is not dict or 'action_pending_created' not in prov:
                    continue
                oid = ev['event_id']
                conv, turn, aid = payload.get('conversation'), payload.get('turn'), payload.get('attempt_id')
                trace_id = ev['trace_id']
                if not ident(conv) or not ident(aid) or not ident(trace_id) or not turnok(turn):
                    return None, gap('action_learning_pending_scan_shape', 'payload')
                matches = []
                for e in events:
                    if e['kind'] != 'input_received' or e['trace_id'] != trace_id:
                        continue
                    p = e['payload']
                    if type(p) is not dict:
                        continue
                    if (p.get('attempt_id') == aid and p.get('conversation') == conv
                            and type(p.get('turn')) is int and p.get('turn') == turn):
                        matches.append(e['event_id'])
                if len(matches) != 1:
                    return None, gap('action_learning_pending_scan_ambiguous', 'trace_id')
                iid = matches[0]
                ipos = positions.get(iid)
                if type(ipos) is not int or not 0 <= ipos < opos:
                    return None, gap('action_learning_pending_scan_order', 'payload')
                anc, found = _al_ancestors(archive, oid)
                if found is not None:
                    return None, found
                if iid not in anc:
                    return None, gap('action_learning_pending_scan_not_ancestor', 'parent_ids')
                _ianc, found = _al_ancestors(archive, iid)
                if found is not None:
                    return None, found
                ie = events[ipos]
                if (ie['kind'] != 'input_received' or ie['status'] != 'success'
                        or ie['epistemic_status'] != 'reported' or ie['subsystem'] != 'dialogue'):
                    return None, gap('action_learning_pending_scan_kind_invalid')
                ip, isrc, irt = ie['payload'], ie['source'], ie['runtime']
                if type(ip) is not dict or type(isrc) is not dict or type(irt) is not dict:
                    return None, gap('action_learning_pending_scan_shape', 'payload')
                raw = ip.get('text')
                iconv, iturn, iaid = ip.get('conversation'), ip.get('turn'), ip.get('attempt_id')
                if (type(raw) is not str or not ident(iconv) or not ident(iaid) or not turnok(iturn)
                        or iconv != conv or iaid != aid or iturn != turn):
                    return None, gap('action_learning_pending_scan_shape', 'payload')
                try:
                    raw.encode('utf-8')
                except UnicodeError:
                    return None, gap('action_learning_pending_scan_shape', 'payload.text')
                if ip.get('sha256') != hashlib.sha256(raw.strip().encode('utf-8')).hexdigest():
                    return None, gap('action_learning_pending_scan_digest_mismatch', 'payload.sha256')
                if (isrc.get('type') != 'dialogue_turn' or isrc.get('conversation') != iconv
                        or type(isrc.get('turn')) is not int or isrc.get('turn') != iturn):
                    return None, gap('action_learning_pending_scan_source_mismatch', 'source')
                if irt.get('source_id') != archive['ledger_source_id']:
                    return None, gap('action_learning_pending_scan_source_mismatch', 'runtime.source_id')
                declared = irt.get('declared_runtime')
                if type(declared) is not dict or not ident(declared.get('context_conversation_id')):
                    return None, gap('action_learning_pending_scan_runtime_invalid',
                                     'runtime.declared_runtime')
                if iconv != cur_conv or declared['context_conversation_id'] != cur_ctx:
                    continue
                meta = prov['action_pending_created']
                if (type(meta) is not list or len(meta) != 1 or type(meta[0]) is not dict
                        or set(meta[0]) != set(keys7)):
                    return None, gap('action_learning_pending_source_shape', 'action_pending_created')
                src = meta[0]
                if (src['schema'] != 'contextual-action-pending-source-v1' or not ident(src['pending_id'])
                        or not ident(src['source_input_id']) or not ident(src['context_conversation_id'])
                        or not turnok(src['created_input_turn']) or not hx(src['raw_text_sha256'])
                        or not hx(src['binding_sha256'])):
                    return None, gap('action_learning_pending_source_shape', 'action_pending_created')
                if src['pending_id'] != item['id']:
                    continue
                found_rows.append((oid, iid, src))
            if not found_rows:
                return None, gap('action_learning_pending_source_missing')
            if len(found_rows) != 1:
                return None, gap('action_learning_pending_source_ambiguous')
            oid, iid, src = found_rows[0]
            if src['source_input_id'] != iid:
                return None, gap('action_learning_pending_source_input_mismatch', 'action_pending_created')
            out, found = _al_output(archive, oid)
            if found is not None:
                return None, found
            if out['input_id'] != src['source_input_id']:
                return None, gap('action_learning_pending_source_input_mismatch', 'action_pending_created')
            anc, found = _al_ancestors(archive, oid)
            if found is not None:
                return None, found
            inp, found = _al_input(archive, src['source_input_id'])
            if found is not None:
                return None, found
            if (src['source_input_id'] not in anc or positions[inp['event_id']] >= positions[oid]
                    or out['conversation_id'] != cur_conv or inp['conversation_id'] != cur_conv
                    or inp['context_conversation_id'] != cur_ctx
                    or src['context_conversation_id'] != inp['context_conversation_id']
                    or inp['text'] != item['text'] or inp['raw_sha256'] != text_sha
                    or src['raw_text_sha256'] != inp['raw_sha256']
                    or src['binding_sha256'] != bind_sha or src['created_input_turn'] != cturn):
                return None, gap('action_learning_pending_source_mismatch', 'action_pending_created')
            return {'source': deepcopy(src), 'pending_creation_output_id': oid}, None

        def _al_origin(archive, origin):
            gap = lambda code, path=None: {'code': code, 'path': path, 'candidate_id': None,
                                           'pending_id': None}
            ident = lambda v: type(v) is str and 0 < len(v) <= 128
            keys7 = ('kind', 'ledger_source_id', 'candidate_id', 'rule_id', 'rule_revision',
                     'accepted_change_id', 'teaching')
            if type(origin) is not dict or set(origin) != set(keys7):
                return None, gap('action_learning_origin_shape')
            if origin['kind'] != 'lexical_action_meaning':
                return None, gap('action_learning_origin_kind_invalid', 'kind')
            for k in ('ledger_source_id', 'candidate_id', 'rule_id', 'accepted_change_id'):
                v = origin[k]
                if not ident(v):
                    return None, gap('action_learning_origin_shape', k)
                try:
                    v.encode('utf-8')
                except UnicodeError:
                    return None, gap('action_learning_origin_shape', k)
            rev = origin['rule_revision']
            if type(rev) is not int or rev < 0:
                return None, gap('action_learning_origin_shape', 'rule_revision')
            teaching = origin['teaching']
            if type(teaching) is not dict or set(teaching) != {'conversation_id', 'turn_id'}:
                return None, gap('action_learning_origin_shape', 'teaching')
            for k in ('conversation_id', 'turn_id'):
                v = teaching[k]
                if not ident(v):
                    return None, gap('action_learning_origin_shape', 'teaching')
                try:
                    v.encode('utf-8')
                except UnicodeError:
                    return None, gap('action_learning_origin_shape', 'teaching')
            if origin['ledger_source_id'] != archive['ledger_source_id']:
                return None, gap('action_learning_origin_source_mismatch', 'ledger_source_id')
            current = archive['current_input']
            if type(current) is not dict:
                return None, gap('action_learning_current_input_invalid')
            cur_pos = archive['positions'].get(current['event_id'])
            tid = teaching['turn_id']
            pos = archive['positions'].get(tid)
            if type(cur_pos) is not int or type(pos) is not int or not 0 <= pos < cur_pos:
                return None, gap('action_learning_origin_chronology_invalid', 'teaching.turn_id')
            _anc, found = _al_ancestors(archive, tid)
            if found is not None:
                return None, found
            inp, found = _al_input(archive, tid, current=False)
            if found is not None:
                return None, found
            if inp['conversation_id'] != teaching['conversation_id']:
                return None, gap('action_learning_origin_conversation_mismatch', 'teaching.conversation_id')
            return inp, None

        import hashlib as _h
        import string as _st
        cb = self._action_grounding_canonical
        sha = lambda v: _h.sha256(cb(v)).hexdigest()
        rsha = lambda s: _h.sha256(s.encode('utf-8')).hexdigest()
        gaps, omit = [], {'targets': 0, 'matches': 0, 'gaps': 0}
        S = {'bind': None, 'decl': None, 'control': None, 'sel': None, 'targets': [], 'matches': [],
             'used': None, 'inc': False, 'prov': {}, 'persist': [], 'trace': None, 'cap': 65536}
        known = []
        orig = tx.get('original_outcome') if isinstance(tx, dict) else None
        nat = orig.get('answer') if isinstance(orig, dict) else None
        if not (type(nat) is str and nat):
            nat = None

        def addgap(code, path=None, cid=None, pid=None):
            row = {'code': str(code)[:128], 'path': None if path is None else str(path)[:512],
                   'candidate_id': cid if type(cid) is str and 0 < len(cid) <= 128 else None,
                   'pending_id': pid if type(pid) is str and 0 < len(pid) <= 128 else None}
            S['inc'] = True
            if row in gaps:
                return
            if len(gaps) < 32:
                gaps.append(row)
            else:
                omit['gaps'] += 1

        def addg(g, pid=None):
            addgap(g['code'], g['path'], g['candidate_id'], g['pending_id'] if g['pending_id'] else pid)

        def l5code(e):
            a = e.args
            if len(a) == 1 and type(a[0]) is tuple and len(a[0]) == 2:
                return 'action_learning_l5_' + str(a[0][0])[:100], (a[0][1] if type(a[0][1]) is str else None)
            return 'action_learning_l5_error', None

        def pack(status, answer=None, learned=False):
            comp = not S['inc'] and not any(omit.values())
            prov = dict(S['prov'])
            if status in ('question', 'used') and not comp:
                status, answer, learned = 'unavailable', None, False
                for k in ('meaning_question', 'sources', 'used_learning'):
                    prov.pop(k, None)
                S['used'] = None
                S['sel'] = None
            if any(type(r) is dict and r.get('head_after') is None for r in S['persist']):
                prov.pop('learning_memory_head', None)
                if status in ('question', 'used', 'admitted', 'already_active', 'denied', 'withdrawn'):
                    status, answer, learned = 'unavailable', None, False
                    for k in ('meaning_question', 'sources', 'used_learning'):
                        prov.pop(k, None)
                    S['used'] = None
                    S['sel'] = None
            if answer is not None and len(answer.encode('utf-8')) > S['cap']:
                answer = None
                if status in ('question', 'used'):
                    status, learned = 'unavailable', False
                    for k in ('meaning_question', 'sources', 'used_learning'):
                        prov.pop(k, None)
                    S['used'] = None
                    S['sel'] = None
            trace = {'schema': 'lexical-action-ordinary-trace-v1', 'status': status,
                     'binding_sha256': S['bind'], 'declaration': S['decl'], 'control': S['control'],
                     'selection': S['sel'], 'targets': list(S['targets']), 'matches': list(S['matches']),
                     'used': S['used'], 'gaps': list(gaps), 'complete': comp, 'omitted': dict(omit)}
            old = adjunct.get('trace') if isinstance(adjunct, dict) else None
            newt = S['trace'] if status == 'question' and S['trace'] is not None else old
            try:
                total = (len(cb(newt)) if newt is not None else 0) + len(cb(trace))
            except (TypeError, ValueError, OverflowError, RecursionError):
                total = None
            if total is None or total > self._ACTION_TRACE_BYTES - 4096:
                for k in ('meaning_question', 'sources', 'used_learning'):
                    prov.pop(k, None)
                trace = {'schema': 'lexical-action-ordinary-trace-v1', 'status': 'unavailable',
                         'binding_sha256': S['bind'], 'declaration': None, 'control': None,
                         'selection': None, 'targets': [], 'matches': [], 'used': None,
                         'gaps': [{'code': 'action_learning_trace_budget', 'path': None,
                                   'candidate_id': None, 'pending_id': None}],
                         'complete': False,
                         'omitted': {'targets': len(S['targets']) + omit['targets'],
                                     'matches': len(S['matches']) + omit['matches'],
                                     'gaps': len(gaps) + omit['gaps']}}
                answer, learned = None, False
            elif newt is not old:
                adjunct['trace'] = newt
            return {'answer': answer, 'learned': learned, 'trace': trace, 'provenance': prov,
                    'persistence': list(S['persist'])}

        def run():
            try:
                from marco.language.teaching import read_action_meaning_control
                from marco.language.frames import read_unknown_action
                from marco.reasoning import actions as l5
                from marco.learning.memory import MemoryLimitError
                from marco.storage.overlay import OverlayConflict
                mem = resource['memory']
                for n in ('learn_action_meaning', 'retract', 'active_action_meanings', 'action_meaning_origin'):
                    if not callable(getattr(mem, n, None)):
                        raise ImportError(n)
                for n in ('build_action_meaning_target', 'validate_action_meaning_target',
                          'render_action_meaning', 'match_action_meaning'):
                    if not callable(getattr(l5, n, None)):
                        raise ImportError(n)
            except (ImportError, TypeError, KeyError):
                addgap('action_learning_dependency_unavailable')
                return pack('unavailable')
            archive, g = _al_load()
            if g is not None:
                addg(g)
                return pack('unavailable')
            if archive is None:
                return pack('idle')
            ap, lp, bd = archive['action_projection'], archive['learning_projection'], archive['binding']
            lim = archive['limits']
            current = archive['current_input']
            S['bind'] = archive['graph_binding']
            try:
                S['decl'] = {'fingerprint': lp['fingerprint'], 'policy_id': bd['policy_id'],
                             'source_maps': deepcopy(lp['source_maps']), 'provenance': deepcopy(lp['provenance'])}
                S['cap'] = min(lim['max_question_bytes'], self._ACTION_TEXT_BYTES)
            except (KeyError, TypeError):
                addgap('action_learning_declaration_invalid')
                return pack('unavailable')
            head0 = resource['previous_head']

            def read_inv():
                try:
                    return mem.active_action_meanings(), None
                except MemoryLimitError as e:
                    return None, str(e)[:128]

            def fresh_head():
                r, code = read_inv()
                if r is None:
                    addgap(code or 'action_meaning_unavailable', 'persistence')
                    S['prov'].pop('learning_memory_head', None)
                    return None
                h = r.get('head') if type(r) is dict else None
                rgaps = r.get('gaps') if type(r) is dict else None
                if (r.get('schema') != 'lexical-action-meaning-inventory-v1' if type(r) is dict else True) \
                        or type(h) is not dict or type(rgaps) is not list or type(r.get('rows')) is not list \
                        or type(h.get('seq')) is not int or type(h.get('change_id')) not in (str, type(None)):
                    addgap('action_learning_post_head_invalid', 'persistence')
                    S['prov'].pop('learning_memory_head', None)
                    return None
                unavail = False
                for ig in rgaps:
                    if type(ig) is not dict or set(ig.keys()) != {'code', 'candidate_id'} \
                            or type(ig.get('code')) is not str or not 0 < len(ig['code']) <= 128 \
                            or type(ig.get('candidate_id')) not in (str, type(None)):
                        addgap('action_learning_post_head_invalid', 'persistence')
                        S['prov'].pop('learning_memory_head', None)
                        return None
                    gcode, gcid = ig['code'], ig['candidate_id']
                    addgap(gcode, 'persistence', gcid)
                    if gcode in ('action_meaning_unavailable:memory_head_changed',
                                 'action_meaning_feature_unavailable',
                                 'action_meaning_unavailable:feature_unavailable'):
                        unavail = True
                if unavail:
                    S['prov'].pop('learning_memory_head', None)
                    return None
                ha = {'seq': h['seq'], 'change_id': h['change_id']}
                S['prov']['learning_memory_head'] = dict(ha)
                return ha

            inv, code = read_inv()
            if inv is None:
                addgap(code or 'action_meaning_unavailable')
                return pack('unavailable')
            if (type(inv) is not dict or inv.get('schema') != 'lexical-action-meaning-inventory-v1'
                    or type(inv.get('rows')) is not list or type(inv.get('gaps')) is not list
                    or type(inv.get('head')) is not dict or cb(inv['head']) != cb(head0)):
                addgap('action_learning_inventory_head_invalid')
                return pack('unavailable')
            for ig in inv['gaps']:
                addgap(ig.get('code') if type(ig) is dict else 'action_learning_inventory_gap', None,
                       ig.get('candidate_id') if type(ig) is dict else None)
            S['prov']['learning_memory_head'] = {'seq': inv['head']['seq'], 'change_id': inv['head']['change_id']}
            st = tx.get('state') if isinstance(tx, dict) else None
            pend = ([p for p in st.get('pending', []) if type(p) is dict and p.get('status') == 'active']
                    if type(st) is dict else [])
            pcache = {}
            for item in pend:
                if item.get('created_input_turn') == st.get('input_turn'):
                    src, g = _al_pending(archive, item)
                    if g is not None:
                        addg(g, item.get('id'))
                        continue
                    pcache[item['id']] = src
                    if src['pending_creation_output_id'] is None:
                        S['prov']['action_pending_created'] = [deepcopy(src['source'])]
            bparser = resource['base_parser']
            ctl = read_action_meaning_control(bparser, current['text'], lp['forms'])
            if ctl is not None:
                ev = ctl['evidence']
                hold = ctl['kind'] == 'hold'
                S['control'] = {'kind': ctl['kind'], 'input_event_id': current['event_id'],
                                'form_id': ev['form_id'], 'form_sha256': ev['form_sha256'],
                                'declaration_sha256': ev['declaration_sha256'],
                                'span': None if hold else [ev['start'], ev['end']]}
                if hold:
                    return pack('idle')

                def render_status(name, expr):
                    try:
                        text = lp['render'][name].format(expression=expr)
                    except (KeyError, IndexError, ValueError, AttributeError):
                        return None
                    if not text or len(text.encode('utf-8')) > S['cap']:
                        return None
                    return text

                def prow(op, status, view, hb, ha, src):
                    v = view if type(view) is dict else {}
                    vg = []
                    for x in (v.get('gaps') or [])[:32]:
                        if type(x) is dict:
                            vg.append({'code': str(x.get('code'))[:128], 'path': None,
                                       'candidate_id': x.get('candidate_id'), 'pending_id': None})
                    return {'operation': op, 'status': status, 'candidate_id': v.get('candidate_id'),
                            'rule_id': v.get('rule_id'), 'rule_revision': v.get('rule_revision'),
                            'accepted_change_id': v.get('accepted_change_id'),
                            'accepted': v.get('accepted') if view is not None else None,
                            'active': v.get('active') if view is not None else None,
                            'head_before': deepcopy(hb), 'head_after': ha, 'source': src, 'gaps': vg}

                if ctl['kind'] in ('affirm', 'deny'):
                    if ctl['kind'] == 'affirm' and S['inc']:
                        addgap('action_learning_inventory_incomplete')
                        return pack('unavailable')
                    qrows, g = _al_questions(archive)
                    if g is not None:
                        addg(g)
                        return pack('unavailable')
                    if not qrows:
                        return pack('idle')
                    if len(qrows) != 1:
                        addgap('action_learning_question_count', 'meaning_question')
                        return pack('unavailable')
                    row = qrows[0]
                    meta, otext = row['metadata'], row['output_text']
                    try:
                        target = l5.validate_action_meaning_target(ap, lp, meta['target'], binding=bd)
                        if cb(target) != cb(meta['target']):
                            raise ValueError(('question_target_changed', 'meaning_question.target'))
                        qo = l5.render_action_meaning(ap, lp, target, binding=bd, kind='question', answer=None)
                        span = meta['question_span']
                        if not (qo['text'] == otext and qo['question_span'] == span):
                            segs, names = [''], []
                            for lit, name, spec, conv in _st.Formatter().parse(lp['render']['question_with_answer']):
                                segs[-1] += lit
                                if name is not None:
                                    if spec not in (None, '') or conv is not None:
                                        raise ValueError(('question_wrapper_invalid', 'render'))
                                    names.append(name)
                                    segs.append('')
                            if len(names) != 2 or sorted(names) != ['answer', 'question'] or len(segs) != 3:
                                raise ValueError(('question_wrapper_invalid', 'render'))
                            pre, mid, suf = segs
                            if not (type(span) is list and len(span) == 2 and type(span[0]) is int
                                    and type(span[1]) is int and 0 <= span[0] <= span[1] <= len(otext)
                                    and otext[span[0]:span[1]] == qo['text']
                                    and otext.count(qo['text']) == 1):
                                raise ValueError(('question_wrapper_mismatch', 'render'))
                            if not (otext.startswith(pre) and otext.endswith(suf)
                                    and len(otext) >= len(pre) + len(suf)):
                                raise ValueError(('question_wrapper_mismatch', 'render'))
                            rest = otext[len(pre):len(otext) - len(suf)]
                            if names[0] == 'answer':
                                tail = mid + qo['text']
                                if not rest.endswith(tail):
                                    raise ValueError(('question_wrapper_mismatch', 'render'))
                                ans = rest[:len(rest) - len(tail)]
                            else:
                                head = qo['text'] + mid
                                if not rest.startswith(head):
                                    raise ValueError(('question_wrapper_mismatch', 'render'))
                                ans = rest[len(head):]
                            if not ans:
                                raise ValueError(('question_answer_empty', 'render'))
                            qo = l5.render_action_meaning(ap, lp, target, binding=bd, kind='question', answer=ans)
                            if qo['text'] != otext or qo['question_span'] != span:
                                raise ValueError(('question_reconstruction_mismatch', 'render'))
                        if (qo['question_template_sha256'] != meta['question_template_sha256']
                                or qo['question_template_id'] != meta['question_template_id']):
                            raise ValueError(('question_template_mismatch', 'render'))
                    except ValueError as e:
                        c, p = l5code(e)
                        addgap(c, p)
                        return pack('unavailable')
                    refs = {'ledger_source_id': archive['ledger_source_id'],
                            'question_output_id': row['question_output_id'],
                            'confirmation_input_id': current['event_id']}
                    view, status = None, 'unavailable'
                    try:
                        view = mem.learn_action_meaning(target, refs, expected_head=head0, replaces=None)
                    except MemoryLimitError as e:
                        c = str(e)[:128]
                        if c == 'action_meaning_denied' and ctl['kind'] == 'deny':
                            status = 'denied'
                        else:
                            addgap(c, 'persistence')
                    except OverlayConflict:
                        addgap('action_meaning_conflict', 'persistence')
                    if view is None:
                        S['persist'].append(prow('admit', status, None, head0, fresh_head(), refs))
                        if status == 'denied':
                            text = render_status('denied', target['surface']['text']) if nat is None else None
                            return pack('denied', text)
                        return pack('unavailable')
                    if ctl['kind'] == 'deny':
                        if type(view) is dict and type(view.get('candidate_id')) is str:
                            known.append({'candidate_id': view.get('candidate_id'), 'rule_id': view.get('rule_id'),
                                          'accepted_change_id': view.get('accepted_change_id')})
                        S['persist'].append(prow('admit', view.get('status') if type(view) is dict else None,
                                                 view, head0, fresh_head(), refs))
                        addgap('action_learning_denial_not_authorized', 'persistence')
                        return pack('unavailable')
                    if type(view) is dict and type(view.get('candidate_id')) is str:
                        known.append({'candidate_id': view.get('candidate_id'), 'rule_id': view.get('rule_id'),
                                      'accepted_change_id': view.get('accepted_change_id')})
                    already = view.get('action_meaning_outcome') == 'already_active'
                    vstat = view.get('status')
                    pstat = 'already_active' if already else vstat
                    S['persist'].append(prow('admit', pstat, view, head0, fresh_head(), refs))
                    if already or (vstat == 'active' and view.get('active') is True):
                        out = 'already_active' if already else 'admitted'
                    elif vstat == 'rejected':
                        out = 'denied'
                    else:
                        out = 'unavailable'
                    text = None
                    if nat is None and out != 'unavailable':
                        text = render_status('denied' if out == 'denied' else 'admitted', target['surface']['text'])
                    return pack(out, text)
                # withdraw
                expr = ctl['fields'].get('expression')
                if S['inc']:
                    addgap('action_learning_inventory_incomplete')
                    return pack('unavailable')
                hits = []
                for r in inv['rows']:
                    try:
                        if r['payload']['surface']['text'] == expr:
                            hits.append(r)
                    except (KeyError, TypeError):
                        addgap('action_learning_inventory_row_invalid')
                        return pack('unavailable')
                if len(hits) != 1:
                    addgap('action_learning_withdraw_scope_not_unique', 'control')
                    return pack('unavailable')
                cid = hits[0]['origin']['candidate_id']
                refs = {'ledger_source_id': archive['ledger_source_id'], 'control_input_id': current['event_id']}
                view, status = None, 'unavailable'
                try:
                    view = mem.retract(cid, lp['policy']['retraction_scope'], expected_head=head0, source=refs)
                except MemoryLimitError as e:
                    addgap(str(e)[:128], 'persistence', cid)
                except OverlayConflict:
                    addgap('action_meaning_conflict', 'persistence', cid)
                if view is None:
                    S['persist'].append(prow('retract', status, None, head0, fresh_head(), refs))
                    return pack('unavailable')
                if type(view) is dict and type(view.get('candidate_id')) is str:
                    known.append({'candidate_id': view.get('candidate_id'), 'rule_id': view.get('rule_id'),
                                  'accepted_change_id': view.get('accepted_change_id')})
                S['persist'].append(prow('retract', view.get('status'), view, head0, fresh_head(), refs))
                if view.get('status') == 'retracted' and view.get('active') is False:
                    return pack('withdrawn', render_status('withdrawn', expr) if nat is None else None)
                return pack('unavailable')
            # noncontrol: future active use
            rows = inv['rows']
            if rows:
                reading = read_unknown_action(current['text'], ap['surface'])
                cl = getattr(mem, 'candidate_limit', 128)
                limit = min(cl if type(cl) is int and cl > 0 else 128, 128)
                hits = []
                for r in rows:
                    try:
                        origin, payload = r['origin'], r['payload']
                        cid = origin['candidate_id']
                        tsha = sha(payload)
                    except (KeyError, TypeError, ValueError):
                        addgap('action_learning_inventory_row_invalid')
                        continue
                    res = l5.match_action_meaning(ap, lp, payload, reading, binding=bd, text=current['text'])
                    if len(S['matches']) >= limit:
                        omit['matches'] += 1
                    else:
                        S['matches'].append({'candidate_id': cid, 'target_sha256': tsha,
                                             'origin': deepcopy(origin), 'result': res})
                    if (res.get('status') == 'gap' or res.get('search_complete') is not True
                            or res.get('truncated') is not False or res.get('gaps')):
                        addgap('action_learning_match_incomplete', 'matches', cid)
                    elif res.get('status') == 'matched':
                        hits.append((r, tsha, res))
                if len(hits) == 1 and len(hits[0][2]['matches']) == 1 and not S['inc']:
                    r, tsha, res = hits[0]
                    origin = r['origin']
                    cid = origin['candidate_id']
                    try:
                        fresh = mem.action_meaning_origin(cid)
                    except MemoryLimitError as e:
                        addgap(str(e)[:128], 'origin', cid)
                        return pack('unavailable')
                    if cb(fresh) != cb(origin):
                        addgap('action_learning_origin_changed', 'origin', cid)
                        return pack('unavailable')
                    inp, g = _al_origin(archive, origin)
                    if g is not None:
                        addg(g)
                        return pack('unavailable')
                    c2 = read_action_meaning_control(bparser, inp['text'], lp['forms'])
                    if c2 is None or c2['kind'] != 'affirm':
                        addgap('action_learning_origin_not_affirm', 'origin', cid)
                        return pack('unavailable')
                    try:
                        uo = l5.render_action_meaning(ap, lp, r['payload'], binding=bd, kind='used', answer=None)
                    except ValueError as e:
                        c, p = l5code(e)
                        addgap(c, p, cid)
                        return pack('unavailable')
                    if not uo['text']:
                        addgap('action_learning_used_text_empty', None, cid)
                        return pack('unavailable')
                    S['used'] = {'candidate_id': cid, 'target_sha256': tsha, 'origin': deepcopy(origin),
                                 'match': deepcopy(res['matches'][0]), 'text': uo['text']}
                    S['prov']['sources'] = [{'kind': 'dialogue_input', 'source_id': origin['ledger_source_id'],
                                             'input_event_id': inp['event_id'],
                                             'conversation_id': inp['conversation_id'], 'turn': inp['turn'],
                                             'text': inp['text'], 'sha256': inp['raw_sha256'],
                                             'span': [c2['evidence']['start'], c2['evidence']['end']]}]
                    S['prov']['used_learning'] = [{'kind': 'lexical_action_meaning',
                                                   'ledger_source_id': origin['ledger_source_id'],
                                                   'candidate_id': cid, 'rule_id': origin['rule_id'],
                                                   'rule_revision': origin['rule_revision'],
                                                   'accepted_change_id': origin['accepted_change_id'],
                                                   'teaching': deepcopy(origin['teaching'])}]
                    return pack('used', uo['text'] if nat is None else None, True)
            if S['inc']:
                return pack('unavailable')
            # question path
            scopes = set()
            for r in rows:
                try:
                    p = r['payload']
                    scopes.add(cb({'surface': p['surface'], 'role_pattern': p['role_pattern'],
                                   'role_pattern_sha256': p['role_pattern_sha256']}))
                except (KeyError, TypeError, ValueError):
                    addgap('action_learning_inventory_row_invalid')
                    return pack('unavailable')
            ext = {'trace': None}

            def considered(item):
                tr = ext['trace'] if ext['trace'] is not None else (
                    adjunct.get('trace') if isinstance(adjunct, dict) else None)
                if (not isinstance(tr, dict) or type(tr.get('results')) is not list
                        or tr.get('results_complete') is not True or tr.get('omitted_pending_ids')):
                    return None, 'action_learning_stagea_trace_incomplete'
                res = next((x for x in tr['results'] if isinstance(x, dict) and x.get('pending_id') == item['id']), None)
                if res is None:
                    status, proj, c3, cc = self._action_grounding_carrier()
                    compare = self._action_grounding_compare()
                    if status != 'paired' or compare is None:
                        return None, 'action_learning_comparison_unavailable'
                    g2 = []
                    res = self._action_grounding_one(tx, ap, archive['host_binding'], st, item, compare, g2)
                    if res is None or g2:
                        return None, 'action_learning_comparison_incomplete'
                    nt = self._action_grounding_trace(tx, proj, c3, list(tr['results']) + [res], list(tr['gaps']))
                    n = len(tr['results'])
                    if (nt['results'][:n] != tr['results'] or len(nt['results']) != n + 1
                            or nt['results'][n] != res or nt['results_complete'] is not True
                            or nt['omitted_pending_ids'] or nt['declaration'] != tr['declaration']
                            or nt['gaps'][:len(tr['gaps'])] != tr['gaps']):
                        return None, 'action_learning_trace_extension_invalid'
                    ext['trace'] = nt
                cands = res.get('candidates')
                ranking = res.get('ranking')
                if (res.get('status') not in ('conditional', 'clarify') or res.get('pending_id') != item['id']
                        or res.get('candidate_enumeration_complete') is not True
                        or res.get('observations_complete') is not True
                        or res.get('comparison_complete') is not True or res.get('truncated') is not False
                        or res.get('gaps') or type(cands) is not list or not cands or type(ranking) is not list):
                    return None, 'action_learning_candidates_incomplete'
                ids = [c.get('id') if isinstance(c, dict) else None for c in cands]
                ranked = []
                for grp in ranking:
                    if not isinstance(grp, dict) or type(grp.get('candidate_ids')) is not list:
                        return None, 'action_learning_rank_group_missing'
                    ranked.extend(grp['candidate_ids'])
                if (any(type(i) is not str or not i for i in ids) or len(set(ids)) != len(ids)
                        or sorted(ranked) != sorted(ids)):
                    return None, 'action_learning_candidates_incomplete'
                out = []
                for cand in cands:
                    rank = None
                    for gi, grp in enumerate(ranking):
                        if isinstance(grp, dict) and cand.get('id') in (grp.get('candidate_ids') or []):
                            rank = gi + 1
                            break
                    if type(rank) is not int or not 1 <= rank <= 64:
                        return None, 'action_learning_rank_group_missing'
                    try:
                        tgt = l5.build_action_meaning_target(ap, lp, item['reading'], cand, binding=bd,
                                                             text=item['text'])
                    except ValueError as e:
                        return None, l5code(e)[0]
                    scope = cb({'surface': tgt['surface'], 'role_pattern': tgt['role_pattern'],
                                'role_pattern_sha256': tgt['role_pattern_sha256']})
                    known_scope = scope in scopes
                    out.append({'pending_id': item['id'], 'candidate_id': cand['id'], 'rank_group': rank,
                                'target_sha256': sha(tgt), 'target': tgt,
                                'question_eligible': not known_scope,
                                'ineligible_reason': 'active_scope' if known_scope else None})
                return out, None

            chosen = None
            for item in pend:
                src = pcache.get(item['id'])
                if src is None:
                    src, g = _al_pending(archive, item)
                    if g is not None:
                        addg(g, item['id'])
                        return pack('unavailable')
                    pcache[item['id']] = src
                trows, why = considered(item)
                if trows is None:
                    addgap(why, 'pending', None, item['id'])
                    return pack('unavailable')
                S['targets'] = trows
                elig = [t for t in trows if t['question_eligible']]
                if elig:
                    elig.sort(key=lambda t: (t['rank_group'], t['target_sha256']))
                    chosen = (item, src, elig[0])
                    break
            if chosen is None:
                return pack('no_match' if S['matches'] else 'idle')
            item, src, tg = chosen
            try:
                qo = l5.render_action_meaning(ap, lp, tg['target'], binding=bd, kind='question', answer=nat)
            except ValueError as e:
                c, p = l5code(e)
                addgap(c, p, tg['candidate_id'], item['id'])
                return pack('unavailable')
            text = qo['text']
            if not text or len(text.encode('utf-8')) > S['cap']:
                addgap('action_learning_question_too_long', None, tg['candidate_id'], item['id'])
                return pack('unavailable')
            s7 = src['source']
            S['sel'] = {'pending_id': item['id'], 'initiating_input_id': s7['source_input_id'],
                        'pending_creation_output_id': src['pending_creation_output_id'],
                        'rank_group': tg['rank_group'], 'candidate_id': tg['candidate_id'],
                        'target_sha256': tg['target_sha256'], 'target': deepcopy(tg['target'])}
            S['prov']['meaning_question'] = {
                'schema': 'lexical-action-meaning-question-v1', 'pending_id': item['id'],
                'initiating_input_id': s7['source_input_id'],
                'pending_creation_output_id': src['pending_creation_output_id'],
                'context_conversation_id': s7['context_conversation_id'], 'target': deepcopy(tg['target']),
                'target_sha256': tg['target_sha256'], 'selection': deepcopy(bd),
                'learning_declaration_sha256': bd['action_learning_projection_fingerprint'],
                'question_template_id': 'question',
                'question_template_sha256': qo['question_template_sha256'],
                'rendered_text_sha256': rsha(text), 'question_span': list(qo['question_span'])}
            if ext['trace'] is not None:
                S['trace'] = ext['trace']
            return pack('question', text)

        try:
            return run()
        except Exception as exc:
            if known and hasattr(exc, 'add_note'):
                exc.add_note('action_learning_known_identities:' + json.dumps(known, sort_keys=True))
            raise

    def _action_grounding_model_value(self, name):
        value = getattr(self.model, name)
        return value() if callable(value) else value

    def _action_grounding_host_binding(self, context, c3, old=None):
        if c3 is None and old is None:
            return None
        binding = dict(old) if old else {}
        if c3 is not None:
            for key in ('graph_id', 'root_id', 'effective_graph_sha256', 'view_key',
                        'language_projection_fingerprint', 'action_projection_fingerprint'):
                binding[key] = deepcopy(c3[key])
        binding['conversation_id'] = context.conversation_id
        binding['model_content_sha256'] = self._action_grounding_model_value('content_fingerprint')
        binding['model_effective_key'] = self._action_grounding_model_value('effective_key')
        binding['parser_base_sha256'] = context.parser_base_sha256
        binding['parser_grammar_sha256'] = context._grammar()
        binding['installed_memory_head'] = context.installed_memory_head
        return {key: binding[key] for key in self._ACTION_BINDING_KEYS}

    def _action_grounding_stale(self, state, code):
        from marco.storage.snapshot import invalidate_action_grounding_state
        if any(item['status'] == 'active' for item in state['pending']):
            return invalidate_action_grounding_state(state, code)
        return state

    def _action_grounding_gap_add(self, state, code):
        gap = {'code': code}
        if gap not in state['gaps'] and len(state['gaps']) < 16:
            state['gaps'].append(gap)

    def _action_grounding_reconcile(self, context, state):
        status, projection, c3, code = self._action_grounding_carrier()
        if state is None:
            if status != 'paired':
                return None
            state = {'schema': 'contextual-action-state-v1',
                     'binding': self._action_grounding_host_binding(context, c3, None),
                     'input_turn': 0, 'next_pending': 1, 'observation_turns': [],
                     'pending': [], 'gaps': []}
            if context.snapshot().get('observation_ids'):
                self._action_grounding_gap_add(state, 'chronology_unavailable')
            return state
        state = deepcopy(state)
        if status == 'paired':
            host = self._action_grounding_host_binding(context, c3, state['binding'])
            if host != state['binding']:
                state = self._action_grounding_stale(state, 'action_binding_changed')
                state['binding'] = host
        else:
            state = self._action_grounding_stale(state, 'action_projection_unavailable')
        return state

    def _action_grounding_stage_context(self, conversation_id, store):
        context = self._action_grounding_context()
        state, bad = None, False
        if conversation_id:
            cid = str(conversation_id)
            saved = store.reasoning_state(cid)
            if self.graph_overlay is not None:
                saved = self._saved_reasoning_state(saved)
            if saved is not None:
                try:
                    seeds = self._action_grounding_saved_seeds(context, saved)
                except Exception:
                    seeds = None
                fresh = getattr(context, 'parser_base_sha256', None)
                seed_changed = bool(seeds) and fresh is not None and any(seed != fresh for seed in seeds)
                if seed_changed:
                    try:
                        state = store.action_grounding_state(cid)
                    except Exception:
                        state, bad = None, True
                    if state is not None:
                        try:
                            state = self._action_grounding_rebind(context, state, 'history_only_seed_changed', True)
                            self._action_grounding_gap_add(state, 'history_only_seed_changed')
                        except Exception:
                            state, bad = None, True
                else:
                    context.restore(saved)
                    try:
                        state = store.action_grounding_state(cid)
                    except Exception:
                        state, bad = None, True
        try:
            state = self._action_grounding_reconcile(context, state)
        except Exception:
            state, bad = None, True
        if bad and state is not None:
            self._action_grounding_gap_add(state, 'action_state_invalid')
        return context, state

    def _action_grounding_rebind(self, context, state, code, history_only):
        from marco.storage.snapshot import validate_action_grounding_state, invalidate_action_grounding_state
        state = deepcopy(state)
        if history_only:
            state = invalidate_action_grounding_state(state, code)
            state['observation_turns'] = []
        else:
            state = self._action_grounding_stale(state, code)
        status, projection, c3, _code = self._action_grounding_carrier()
        state['binding'] = self._action_grounding_host_binding(context, c3 if status == 'paired' else None,
                                                               state['binding'])
        return validate_action_grounding_state(state, context.snapshot())

    def _action_grounding_sync_native(self, head):
        from pack_model import PackModel
        entry = {'model': self.model, 'language_pack': self.language_pack,
                 'contexts': dict(self.reasoning_contexts), 'states': dict(self.action_grounding_states),
                 'applied': self._overlay_applied,
                 'binding': deepcopy(getattr(self.conversations, 'binding', None))}
        try:
            model = PackModel(self.manifest, self.data, language_overlay=self.graph_overlay, language_at=head[0])
            self.model = model
            self.language_pack = model.language
            contexts, states = {}, {}
            for cid, context in list(self.reasoning_contexts.items()):
                fresh = self._action_grounding_context()
                same = context.parser_base_sha256 == fresh.parser_base_sha256
                if same:
                    fresh.restore({k: v for k, v in context.snapshot().items() if k != 'replay'})
                code = 'overlay_head_changed' if same else 'history_only_seed_changed'
                state = self.action_grounding_states.get(cid)
                if state is not None:
                    state = self._action_grounding_rebind(fresh, state, code, not same)
                else:
                    state = self._action_grounding_reconcile(fresh, None)
                contexts[cid] = fresh
                if state is not None:
                    states[cid] = state
            self.reasoning_contexts.clear()
            self.reasoning_contexts.update(contexts)
            self.action_grounding_states.clear()
            self.action_grounding_states.update(states)
            self._overlay_applied = head
            self._bind_overlay_head()
            return True
        except BaseException:
            self.model = entry['model']
            self.language_pack = entry['language_pack']
            self.reasoning_contexts.clear()
            self.reasoning_contexts.update(entry['contexts'])
            self.action_grounding_states.clear()
            self.action_grounding_states.update(entry['states'])
            self._overlay_applied = entry['applied']
            binding = getattr(self.conversations, 'binding', None)
            if isinstance(binding, dict) and isinstance(entry['binding'], dict):
                binding.clear()
                binding.update(entry['binding'])
            raise

    def _action_grounding_active(self, snapshot):
        out = {}
        ledger = snapshot.get('reading_ledger')
        records = ledger.get('records') if isinstance(ledger, dict) else None
        if not isinstance(records, dict):
            return out
        for oid in snapshot.get('observation_ids') or []:
            entry = records.get(oid)
            active = entry.get('active') if isinstance(entry, dict) else None
            if type(active) is int and active >= 1:
                out[oid] = active
        return out

    def _action_grounding_pre_refs(self, snapshot):
        ledger = snapshot.get('reading_ledger')
        records = ledger.get('records') if isinstance(ledger, dict) else None
        ids = snapshot.get('observation_ids') or []
        if not isinstance(records, dict):
            return [] if not ids else None
        refs = []
        for oid in ids:
            entry = records.get(oid)
            active = entry.get('active') if isinstance(entry, dict) else None
            record = None
            if type(active) is int:
                for key in ('versions', 'readings', 'records', 'history'):
                    held = entry.get(key)
                    if isinstance(held, list):
                        record = next((r for r in held if isinstance(r, dict) and r.get('reading_revision') == active), None)
                    elif isinstance(held, dict):
                        record = held.get(active, held.get(str(active)))
                    if record is not None:
                        break
            if record is None:
                return None
            try:
                digest = hashlib.sha256(self._action_grounding_canonical(record)).hexdigest()
            except Exception:
                return None
            refs.append({'observation_id': oid, 'reading_revision': active, 'record_sha256': digest})
        return refs

    def _action_grounding_begin(self, text, context_id, conversation_id, entry=None):
        existing = self.reasoning_contexts.get(context_id)
        tx = {'context_id': context_id, 'had_context': existing is not None,
              'entry': entry,
              'history': list(self.history),
              'fields': {name: getattr(self, name, None) for name in (
                  'model', 'language_pack', 'active_name', 'route', 'routed_graphs', 'combined_shape',
                  'graph', 'session', 'graph_path')},
              'binding': deepcopy(getattr(self.conversations, 'binding', None)),
              'prior_state': deepcopy(self.action_grounding_states.get(context_id)),
              'gaps': [], 'changed': False, 'original_outcome': None, 'post': None}
        if existing is not None:
            context = existing
            try:
                state = self._action_grounding_reconcile(context, self.action_grounding_states.get(context_id))
            except Exception:
                state = None
                tx['gaps'].append({'code': 'action_state_invalid'})
        else:
            context, state = self._action_grounding_stage_context(conversation_id, self.conversations)
        pre = context.snapshot()
        tx['context'] = context
        tx['pre'] = pre
        tx['pre_active'] = self._action_grounding_active(pre)
        tx['pre_refs'] = self._action_grounding_pre_refs(pre)
        if state is not None:
            state['input_turn'] += 1
        tx['state'] = state
        if existing is None:
            self.reasoning_contexts[context_id] = context
        return tx

    def _action_grounding_after_turn(self, tx, outcome):
        context = tx['context']
        try:
            tx['original_outcome'] = self._action_grounding_plain(outcome)
        except Exception:
            tx['original_outcome'] = None
            tx['gaps'].append({'code': 'original_outcome_unavailable'})
        post = context.snapshot()
        tx['post'] = post
        state = tx['state']
        if state is None:
            return
        post_active = self._action_grounding_active(post)
        known = {(r['observation_id'], r['reading_revision']): r['input_turn'] for r in state['observation_turns']}
        rows, changed, missing = [], False, False
        for oid in post.get('observation_ids') or []:
            revision = post_active.get(oid)
            if revision is None:
                continue
            key = (oid, revision)
            if key in known:
                rows.append({'observation_id': oid, 'reading_revision': revision, 'input_turn': known[key]})
            elif tx['pre_active'].get(oid) == revision:
                missing = True
            else:
                rows.append({'observation_id': oid, 'reading_revision': revision, 'input_turn': state['input_turn']})
                changed = True
        if len(rows) > 128:
            rows = rows[-128:]
            self._action_grounding_gap_add(state, 'observation_rows_cap')
        state['observation_turns'] = rows
        if missing:
            self._action_grounding_gap_add(state, 'chronology_unavailable')
        tx['changed'] = changed

    def _action_grounding_rollback(self, tx):
        entry = tx.get('entry')
        if entry is not None:
            self._action_grounding_restore_entry(entry)
            return
        cid = tx['context_id']
        context = tx['context']
        try:
            if tx['had_context']:
                context.restore(tx['pre'])
                self.reasoning_contexts[cid] = context
            else:
                self.reasoning_contexts.pop(cid, None)
        finally:
            if tx['prior_state'] is None:
                self.action_grounding_states.pop(cid, None)
            else:
                self.action_grounding_states[cid] = deepcopy(tx['prior_state'])
            self.history[:] = tx['history']
            for name, value in tx['fields'].items():
                setattr(self, name, value)
            binding = getattr(self.conversations, 'binding', None)
            if isinstance(binding, dict) and isinstance(tx['binding'], dict):
                binding.clear()
                binding.update(deepcopy(tx['binding']))

    def _action_grounding_publish(self, tx):
        cid = tx['context_id']
        self.reasoning_contexts[cid] = tx['context']
        if tx['state'] is None:
            self.action_grounding_states.pop(cid, None)
        else:
            self.action_grounding_states[cid] = deepcopy(tx['state'])

    @staticmethod
    def _action_grounding_find(outcome, key):
        for holder in (outcome.get('meaning'), outcome.get('verification'), outcome):
            if isinstance(holder, dict) and key in holder:
                return holder[key]
        return None

    def _action_grounding_unsupported(self, tx, outcome):
        original = tx['original_outcome']
        forbid = {'operator_not_permitted', 'reply_authority', 'projection_schema', 'active_clarification',
                  'state_completion', 'query_pending'}
        if original is None:
            meaning = outcome.get('meaning') if isinstance(outcome, dict) else None
            return bool(isinstance(meaning, dict) and outcome.get('status') == 'unresolved'
                        and meaning.get('reason') == 'input_understanding_failed'
                        and isinstance(outcome.get('answer'), str) and outcome['answer'].strip())
        if not isinstance(original, dict) or original.get('status') != 'unresolved':
            return False
        meaning = original.get('meaning')
        if not isinstance(meaning, dict):
            return False
        seen = set()
        if isinstance(meaning.get('reason'), str):
            seen.add(meaning['reason'])
        verification = original.get('verification')
        checks = verification.get('checks') if isinstance(verification, dict) else None
        for check in checks if isinstance(checks, list) else []:
            if isinstance(check, dict) and isinstance(check.get('reason'), str):
                seen.add(check['reason'])
        tags = self._action_grounding_find(original, 'unsupported')
        tag_list = []
        for tag in tags if isinstance(tags, list) else []:
            tag = tag.get('tag') if isinstance(tag, dict) else tag
            if isinstance(tag, str):
                tag_list.append(tag)
        if (seen | set(tag_list)) & forbid:
            return False
        reason = meaning.get('reason')
        if reason in ('input_understanding_failed', 'unread_event', 'unknown_word'):
            return True
        if reason == 'language_graph_capability_gap':
            missing = self._action_grounding_find(original, 'missing_replies')
            return (isinstance(missing, list) and not missing and bool(tag_list)
                    and set(tag_list) <= {'advanced_input', 'multiclause'})
        return False

    def _action_grounding_compare(self):
        try:
            from marco.reasoning.actions import compare_contextual_action
        except Exception:
            return None
        if callable(compare_contextual_action):
            return compare_contextual_action
        return None

    def _action_grounding_trace(self, tx, projection, c3, results, gaps):
        canon = self._action_grounding_canonical
        budget = self._ACTION_TRACE_BYTES - 4096
        trace_gaps = []
        for gap in list(gaps) + list(tx.get('gaps') or []):
            if gap not in trace_gaps and len(trace_gaps) < 32:
                trace_gaps.append(gap)
        trace = {'schema': 'contextual-action-trace-v1', 'original_outcome': tx['original_outcome'],
                 'declaration': None, 'results': [], 'gaps': trace_gaps, 'results_complete': True,
                 'omitted_pending_ids': []}
        used = len(canon(trace))
        if projection is not None and c3 is not None:
            declaration = {'binding': deepcopy(c3), 'source_maps': deepcopy(projection['source_maps']),
                           'provenance': deepcopy(projection['provenance'])}
            size = len(canon(declaration))
            if used + size <= budget:
                trace['declaration'] = declaration
                used += size
            else:
                trace_gaps.append({'code': 'source_capsule_cap'})
        omitted = []
        for result in results:
            size = len(canon(result)) + 1
            if used + size > budget:
                pid = result.get('pending_id') if isinstance(result, dict) else None
                omitted.append(pid if isinstance(pid, str) else 'unknown')
                continue
            trace['results'].append(result)
            used += size
        if omitted:
            trace['omitted_pending_ids'] = omitted
            trace['results_complete'] = False
            trace_gaps.append({'code': 'trace_output_cap'})
        return trace

    def _action_grounding_render(self, replies, result):
        if not isinstance(result, dict):
            raise ValueError('action grounding result is not a mapping')
        status = result.get('status')
        if status not in ('conditional', 'clarify'):
            return None
        for flag, expected in (('candidate_enumeration_complete', True), ('observations_complete', True),
                               ('comparison_complete', True), ('truncated', False), ('known', False),
                               ('learned', False), ('unresolved', True)):
            if result.get(flag) is not expected:
                raise ValueError('action grounding result incomplete: %s' % flag)
        if result.get('gaps'):
            raise ValueError('action grounding result has gaps')
        expression = result['unknown']['text']
        if not isinstance(expression, str):
            raise ValueError('action grounding expression is not text')
        candidates = result.get('candidates')
        if not isinstance(candidates, list) or not candidates:
            raise ValueError('action grounding result has no candidates')
        if len(candidates) > 64:
            raise ValueError('action grounding candidate bound exceeded')

        def _count(value):
            if type(value) is not int or value < 0:
                raise ValueError('action grounding metric is not a nonnegative int')
            return value

        observation_ids = set()
        for obs in result.get('observations') or []:
            if isinstance(obs, dict) and isinstance(obs.get('id'), str) and obs['id']:
                observation_ids.add(obs['id'])

        def _refs(value):
            if not isinstance(value, list):
                raise ValueError('action grounding comparison refs are not a list')
            for ref in value:
                if not isinstance(ref, dict):
                    raise ValueError('action grounding comparison ref is not a mapping')
                for side in ('before', 'after'):
                    if ref.get(side) not in observation_ids:
                        raise ValueError('action grounding comparison ref not in observations')
            return value

        by_id = {}
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise ValueError('action grounding candidate is not a mapping')
            cid = candidate.get('id')
            if not isinstance(cid, str) or not cid.strip() or cid in by_id:
                raise ValueError('action grounding candidate id invalid or duplicate')
            terms = candidate.get('terms')
            if not isinstance(terms, list) or not terms:
                raise ValueError('action grounding candidate has no terms')
            metrics = candidate.get('metrics')
            comparison = candidate.get('comparison')
            if not isinstance(metrics, dict) or not isinstance(comparison, dict):
                raise ValueError('action grounding candidate lacks metrics or comparison')
            _count(metrics.get('support_count'))
            _count(metrics.get('conflict_count'))
            _count(metrics.get('term_count'))
            _refs(comparison.get('support_refs'))
            _refs(comparison.get('contrast_refs'))
            if not isinstance(comparison.get('unobserved_effects'), list):
                raise ValueError('action grounding unobserved effects are not a list')
            if not isinstance(comparison.get('unexplained_observation_refs'), list):
                raise ValueError('action grounding unexplained refs are not a list')
            by_id[cid] = candidate

        ranking = result.get('ranking')
        if not isinstance(ranking, list) or not ranking:
            raise ValueError('action grounding ranking missing')
        seen = set()
        ordered = []
        for rank, group in enumerate(ranking, 1):
            if not isinstance(group, dict):
                raise ValueError('action grounding rank group is not a mapping')
            ids = group.get('candidate_ids')
            if not isinstance(ids, list) or not ids:
                raise ValueError('action grounding rank group is empty')
            for cid in ids:
                if not isinstance(cid, str) or cid not in by_id or cid in seen:
                    raise ValueError('action grounding rank group id foreign or duplicate')
                seen.add(cid)
                ordered.append((rank, by_id[cid]))
        if len(seen) != len(by_id):
            raise ValueError('action grounding rank groups omit candidates')

        def _term_text(term):
            if not isinstance(term, dict):
                raise ValueError('action grounding term is not a mapping')
            label = str(term['label'])
            roles = term.get('roles') or {}
            if not isinstance(roles, dict):
                raise ValueError('action grounding roles are not a mapping')
            if roles:
                label += ' (' + ', '.join(json.dumps(str(value), ensure_ascii=False) for value in roles.values()) + ')'
            return label

        parts, leading_parts = [], []
        support, conflict, contrast, unobserved = [], [], [], []
        for number, (rank, candidate) in enumerate(ordered, 1):
            text = '%d. (#%d) %s' % (number, rank, ' + '.join(_term_text(t) for t in candidate['terms']))
            parts.append(text)
            if rank == 1:
                leading_parts.append(text)
                support.append((number, candidate['metrics']['support_count']))
                conflict.append((number, candidate['metrics']['conflict_count']))
                contrast.append((number, len(candidate['comparison']['contrast_refs'])))
                unobserved.append((number, len(candidate['comparison']['unobserved_effects'])))
        if not leading_parts:
            raise ValueError('action grounding has no leading group')

        def _vector(pairs):
            if len(pairs) == 1:
                return '%d' % pairs[0][1]
            return ', '.join('%d=%d' % (n, v) for n, v in pairs)

        values = {'expression': expression, 'candidates': '; '.join(parts),
                  'gaps': replies.get('gap', '') if result.get('gaps') else '',
                  'leading_candidates': '; '.join(leading_parts),
                  'leading_count': '%d' % len(leading_parts),
                  'leading_support_count': _vector(support),
                  'leading_conflict_count': _vector(conflict),
                  'leading_contrast_count': _vector(contrast),
                  'leading_unobserved_count': _vector(unobserved)}
        values['question'] = replies['question'].format(**values)
        rendered = replies[status].format(**values)
        return rendered

    def _action_grounding_create(self, tx, text, projection, state, host, gaps):
        from marco.language.frames import read_unknown_action
        if len(text) > 512:
            gaps.append({'code': 'source_text_cap'})
            return None
        refs = tx['pre_refs']
        if refs is None or len(refs) > 128:
            gaps.append({'code': 'pre_observation_refs_unavailable'})
            return None
        limit = ((projection.get('policy') or {}).get('limits') or {}).get('max_pending')
        if type(limit) is not int or limit < 1:
            gaps.append({'code': 'action_policy_pending_limit'})
            return None
        if len(state['pending']) >= min(limit, 64):
            gaps.append({'code': 'pending_capacity'})
            return None
        reading = read_unknown_action(text, projection['surface'])
        ok = (isinstance(reading, dict) and reading.get('status') == 'read' and reading.get('search_complete') is True
              and reading.get('truncated') is False and isinstance(reading.get('role_candidates'), list)
              and bool(reading['role_candidates']))
        if not ok:
            status = reading.get('status') if isinstance(reading, dict) else None
            gaps.append({'code': 'unknown_reading_' + status if status in ('gap', 'no_match')
                         else 'unknown_reading_incomplete'})
            return None
        entry = {'id': 'a%d' % state['next_pending'], 'text': text, 'created_input_turn': state['input_turn'],
                 'pre_observation_refs': deepcopy(refs), 'binding': deepcopy(host),
                 'reading': self._action_grounding_plain(reading),
                 'original_outcome': deepcopy(tx['original_outcome']), 'status': 'active', 'reason': None}
        candidate = deepcopy(state)
        candidate['next_pending'] += 1
        candidate['pending'].append(deepcopy(entry))
        if len(self._action_grounding_canonical(candidate)) > self._ACTION_STATE_BYTES:
            gaps.append({'code': 'pending_state_bytes_cap'})
            return None
        state['next_pending'] += 1
        state['pending'].append(entry)
        return entry

    def _action_grounding_one(self, tx, projection, host, state, item, compare, gaps):
        window = ((projection.get('policy') or {}).get('limits') or {}).get('max_window_turns')
        if type(window) is int and window > 0 and state['input_turn'] - item['created_input_turn'] > window:
            gaps.append({'code': 'pending_window_expired', 'pending_id': item['id']})
            return None
        if item['binding'] != host:
            gaps.append({'code': 'pending_binding_changed', 'pending_id': item['id']})
            return None
        post = tx['post']
        replay = post.get('replay')
        if not isinstance(replay, dict) or 'facts' not in replay:
            gaps.append({'code': 'archive_replay_unavailable', 'pending_id': item['id']})
            return None
        archive = {'schema': post.get('schema'), 'conversation': post.get('conversation'),
                   'observations': post.get('observations'), 'observation_ids': post.get('observation_ids'),
                   'reading_ledger': post.get('reading_ledger'),
                   'replay': {'facts': replay.get('facts'), 'fact_sources': replay.get('fact_sources')}}
        evidence = {'schema': 'contextual-action-evidence-v1', 'binding': deepcopy(host),
                    'pending': {'id': item['id'], 'text': item['text'],
                                'created_input_turn': item['created_input_turn'],
                                'pre_observation_refs': deepcopy(item['pre_observation_refs'])},
                    'current_input_turn': state['input_turn'],
                    'observation_turns': deepcopy(state['observation_turns']),
                    'archive': self._action_grounding_plain(archive)}
        result = compare(deepcopy(projection), deepcopy(item['reading']), evidence)
        return self._action_grounding_plain(result)

    def _action_grounding_adjunct(self, tx, text, outcome):
        if tx is None:
            return None
        try:
            return self._action_grounding_adjunct_run(tx, text, outcome)
        except Exception:
            try:
                return {'answer': None,
                        'trace': self._action_grounding_trace(tx, None, None, [], [{'code': 'adjunct_error'}])}
            except Exception:
                return None

    def _action_grounding_adjunct_run(self, tx, text, outcome):
        status, projection, c3, code = self._action_grounding_carrier()
        if status is None:
            return None
        state = deepcopy(tx['state']) if tx['state'] is not None else None
        unsupported = self._action_grounding_unsupported(tx, outcome)
        if status != 'paired':
            if not (unsupported or (state and state['pending'])):
                return None
            return {'answer': None, 'trace': self._action_grounding_trace(tx, None, None, [], [{'code': code}])}
        if state is None:
            return {'answer': None, 'trace': self._action_grounding_trace(
                tx, None, None, [], [{'code': 'action_state_unavailable'}])}
        host = self._action_grounding_host_binding(tx['context'], c3, state['binding'])
        if host != state['binding']:
            return {'answer': None, 'trace': self._action_grounding_trace(
                tx, None, None, [], [{'code': 'action_binding_changed'}])}
        gaps, results = [], []
        new_entry = None
        if unsupported:
            new_entry = self._action_grounding_create(tx, text, projection, state, host, gaps)
        targets = [item for item in state['pending']
                   if item['status'] == 'active' and (item is new_entry or tx['changed'])]
        if targets:
            compare = self._action_grounding_compare()
            if compare is None:
                gaps.append({'code': 'comparison_unavailable'})
            else:
                for item in targets:
                    result = self._action_grounding_one(tx, projection, host, state, item, compare, gaps)
                    if result is not None:
                        results.append(result)
        tx['state'] = state
        if not results and not gaps and not tx['gaps']:
            return None
        trace = self._action_grounding_trace(tx, projection, c3, results, gaps)
        answer = None
        if trace['declaration'] is not None:
            try:
                replies = projection['replies']
                by_id = {r.get('pending_id'): r for r in trace['results'] if isinstance(r, dict)}
                if new_entry is not None and new_entry['id'] in by_id:
                    answer = self._action_grounding_render(replies, by_id[new_entry['id']])
                elif outcome.get('status') == 'observed' and 'observed_with_hypothesis' in replies:
                    hypotheses = []
                    for item in targets:
                        if item['id'] in by_id:
                            rendered = self._action_grounding_render(replies, by_id[item['id']])
                            if rendered:
                                hypotheses.append(rendered)
                    if hypotheses:
                        answer = replies['observed_with_hypothesis'].format(
                            answer=outcome.get('answer') or '', hypothesis='\n'.join(hypotheses))
                if answer is not None and len(answer.encode('utf-8')) > self._ACTION_TEXT_BYTES:
                    answer = None
                    trace['gaps'].append({'code': 'render_output_cap'})
            except Exception:
                answer = None
                trace['gaps'].append({'code': 'render_failed'})
        return {'answer': answer, 'trace': trace}


def attach_to_manager(app, names):
    """자가학습이 들인 그래프를 매니저 그래프에 노드로 붙인다. -> 붙은 수

    매니저는 pack manifest 에서 오는데 pack 은 읽기 전용이라, 새로 지은
    그래프는 그 목록에 없다. 붙이지 않으면 화면의 '전체 지식 그래프' 가
    218개에서 멈춘 채 실제로는 244개인 상태가 된다 — 보여주는 것이 곧
    거짓이 되는 자리다.

    붙이면 라우터도 그 그래프를 후보로 본다. 매니저 색인을 같이 다시
    짓는 이유다."""
    attached = 0
    with app.lock, app.model.encoder.activate():
        present_ones = {n["path"] for n in app.manager.get("nodes", [])}
        for name in names:
            loc = "graphs/" + name if not name.startswith("graphs/") else name
            if loc in present_ones:
                continue
            try:
                g = engine.read_for_index(str(repo_root / loc))
            except Exception:
                continue
            app.manager.setdefault("nodes", []).append(
                {"path": loc, "role": g.get("역할") or "", "goal": g.get("목표") or "",
                 "examples": [], "new": True})
            app.manager.setdefault("edges", []).append([loc, "후보", "그래프고르기"])
            attached += 1
        if attached:
            app.manager_index = manager_index(app.manager)
    return attached


def detach_from_manager(app, names):
    """물린 그래프를 매니저에서 뺀다. 안 빼면 없는 그래프를 후보로 든다."""
    removed = {("graphs/" + n if not n.startswith("graphs/") else n) for n in names}
    with app.lock, app.model.encoder.activate():
        front = len(app.manager.get("nodes", []))
        app.manager["nodes"] = [n for n in app.manager.get("nodes", [])
                                if n["path"] not in removed]
        app.manager["edges"] = [e for e in app.manager.get("edges", [])
                                if e[0] not in removed]
        if len(app.manager["nodes"]) != front:
            app.manager_index = manager_index(app.manager)
        return front - len(app.manager["nodes"])


# ── 물음 기록 ──────────────────────────────────────────────────────────
# 물음기록.jsonl 은 자가학습(self_learning.py)이 '무엇을 틀렸나' 를 재는 재료다.
# 예전에는 views/물음판.py 만 이 파일을 썼는데, 화면을 이쪽으로 모으면서
# 그 판을 지웠다. 수집기를 같이 지우면 자가학습이 새 물음을 못 받는다.
question_log_dir = repo_root / "물음기록.jsonl"


def record_question(question, ans, verdict, graph, ms, author="사람"):
    """물어본 것을 한 줄씩 덧붙인다. 통째로 다시 쓰지 않으니 중간에 꺼도 남는다.

    쓴이를 같이 적는다. 기계가 쓴 질문은 코퍼스를 이미 읽고 쓴 것이라 어휘가
    새서, 사람 것과 같은 통에 넣되 섞이지는 않게 줄마다 남긴다."""
    try:
        line = {"질문": question, "판정": verdict, "답": ans or "", "그래프": graph,
             "밀리초": ms, "인코더": encoder.active_runtime().model_name, "쓴이": author,
             "때": time.strftime("%Y-%m-%d %H:%M:%S")}
        with io.open(str(question_log_dir), "a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except OSError:
        pass                            # 못 적어도 대화는 되어야 한다


# ── 자가학습 ───────────────────────────────────────────────────────────
# 한 바퀴가 몇 분이라 요청 안에서 돌리면 브라우저가 먼저 끊는다. 딴 실에서
# 돌리고 화면은 상태만 물어본다. 도는 바퀴는 하나뿐이다 — 둘이 겹치면
# 후보터를 서로 밟는다.
_growth = {"도나": False, "말": "", "탈": None, "끝난것": None}
_growth_lock = threading.Lock()


def growth_state():
    cycle = self_authoring.read_round(200)
    stacked, node, edge = [], 0, 0
    for x in cycle:
        node += x.get("노드", 0)
        edge += x.get("엣지", 0)
        stacked.append({"때": x.get("때"), "노드누적": node, "엣지누적": edge,
                "캠": x.get("캠", 0), "들임": x.get("들임", 0)})
    seen_at, headword_count, dropped_phrase = self_authoring.read_progress()
    import glob
    return {"바퀴": cycle, "쌓임": stacked, "돎": dict(_growth),
            "그래프수": len(glob.glob(str(repo_root / "graphs" / "*.kg"))),
            "진도": {"본데까지": seen_at, "표제수": headword_count, "버린말": len(dropped_phrase)},
            "합": {"노드": node, "엣지": edge,
                   "들임": sum(x.get("들임", 0) for x in cycle),
                   "버림": sum(x.get("버림", 0) for x in cycle)}}


def run_growth(max_n=200, dry_run=False):
    with _growth_lock:
        if _growth["도나"]:
            return {"ok": False, "why": "이미 도는 중이다"}
        _growth.update({"도나": True, "말": "캐고 짓고 거르는 중 … (몇 분 걸린다)",
                     "탈": None, "끝난것": None})

    def trunk():
        try:
            slot = self_authoring.one_round(max_n, dry_run=dry_run)
            admitted = [x.get("이름") for x in
                    ((slot.get("기록") or {}).get("들인것") or []) if x.get("이름")]
            attached = attach_to_manager(Handler.app, admitted) if admitted and Handler.app else 0
            _growth["끝난것"] = dict({k: v for k, v in slot.items() if k != "기록"}, **{"붙임": attached})
            _growth["말"] = "끝났다"
        except Exception as e:
            import traceback
            traceback.print_exc()
            _growth["탈"] = "%s: %s" % (type(e).__name__, e)
            _growth["말"] = "탈이 났다"
        finally:
            _growth["도나"] = False

    threading.Thread(target=trunk, daemon=True).start()
    return {"ok": True}


class Handler(BaseHTTPRequestHandler):
    app = None

    def log_message(self, *_args):
        pass

    def _send(self, body, content_type="application/json", status=200):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "%s; charset=utf-8" % content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _json(self, data, status=200):
        self._send(json.dumps(data, ensure_ascii=False), status=status)

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > 28 * 1024 * 1024:
            raise ValueError("요청이 너무 큽니다")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/growth":
            return self._json(growth_state())
        if path in ("/", "/index.html"):
            html = (Path(__file__).with_name("kgpack_ui.html")).read_bytes()
            return self._send(html, "text/html")
        if path == "/api/info":
            return self._json(self.app.info())
        if path == "/api/conversations":
            return self._json(self.app.conversations_api())
        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/growth/run":
                return self._json(run_growth(int(body.get("max") or 200),
                                          bool(body.get("dry"))))
            if path == "/api/growth/revert":
                if _growth["도나"]:
                    return self._json({"ok": False, "why": "도는 중이다"})
                erased = self_authoring.revert()
                detach_from_manager(self.app, erased)
                return self._json({"ok": True, "removed": len(erased)})
            if path == "/api/select":
                return self._json(self.app.select(body.get("graph")))
            if path == "/api/reset":
                return self._json(self.app.reset())
            if path == "/api/ask":
                _question = body.get("question")
                _start = time.time()
                ans = self.app.ask(_question)
                record_question(_question, ans.get("answer"),
                       (ans.get("trace") or {}).get("verdict"),
                       (ans.get("route") or {}).get("selected") or ans.get("graph"),
                       round(1000 * (time.time() - _start)),
                       author=body.get("writer") or "사람")
                return self._json(ans)
            if path == "/api/understand":
                return self._json(self.app.understand(body.get("input"), body.get("session")))
            if path == "/api/understanding/reset":
                return self._json(self.app.reset_understanding(body.get("session"), body.get("conversation_id")))
            if path == "/api/semantic/correct":
                return self._json(self.app.save_semantic_correction(body.get("session"), body.get("raw"),
                                                                       body.get("semantic_parse"), body.get("verification")))
            if path == "/api/project":
                return self._json(self.app.project(body.get("session"), body.get("path"), body.get("conversation_id")))
            if path == "/api/conversations":
                return self._json(self.app.conversations_api(body.get("action"), body.get("project_id"), body.get("chat_id"), body.get("name")))
            if path == "/api/affect":
                return self._json(self.app.affect(body.get("session"), body.get("enabled"), body.get("conversation_id")))
            if path == "/api/document":
                return self._json(self.app.document(body.get("session"), body.get("filename"), body.get("content_b64")))
            if path == "/api/turn":
                return self._json(self.app.turn(body.get("input"), body.get("session"), body.get("approval_mode", "risk"), body.get("conversation_id")))
            if path == "/api/approve":
                return self._json(self.app.approve_goal(body.get("session"), body.get("plan_id"), body.get("plan_hash"), body.get("action_ids"), body.get("direct"), body.get("conversation_id")))
            if path == "/api/reject":
                return self._json(self.app.reject_goal(body.get("session"), body.get("plan_id"), body.get("reason"), body.get("conversation_id")))
            self.send_error(404)
        except (ValueError, document_kg.DocumentKGError, kgpack.KGPackError, json.JSONDecodeError) as e:
            self._json({"error": str(e)}, status=400)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._json({"error": "%s: %s" % (type(e).__name__, e)}, status=500)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--pack", required=True)
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8766)
    p.add_argument("--overlay")
    args = p.parse_args(argv)
    app = AppState(args.pack, args.overlay)
    Handler.app = app
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print("kgpack: %s" % app.pack_path)
    print("그래프: %d개 · 기본 선택: %s" % (len(app.graphs), app.selected))
    print("overlay: %s" % app.overlay)
    print("http://%s:%d" % (args.host, args.port), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
