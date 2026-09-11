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
import self_authoring  # noqa: E402
import affect_state  # noqa: E402
import conversation_store  # noqa: E402
import document_kg  # noqa: E402
import goal_runtime  # noqa: E402
import input_understanding  # noqa: E402
import kgpack  # noqa: E402
import local_definitions  # noqa: E402
import semantic_parser  # noqa: E402
import state_engine  # noqa: E402
import web_learn  # noqa: E402
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


def web_grounds_answer(research):
    """생성 요약 대신 원문 완결 문장으로 답한다. 출처 없는 문장을 만들지 않는다."""
    sources = research.get("sources") or []
    if not sources:
        return "## 웹 근거 답변\n\n검증 가능한 원문을 찾지 못했습니다."
    parts = ["## 웹 근거 답변", "KG에는 충분한 근거가 없어 원문에서 확인한 문장을 제시합니다."]
    for source in sources:
        heading = source.get("title") or source.get("domain") or "원문"
        parts.append("### %s\n출처: %s\n\n> %s" % (heading, source.get("url", ""),
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
    def __init__(self, pack_path, overlay_root=None):
        self.pack_path = Path(pack_path).resolve()
        self.manifest, self.data = kgpack.read(self.pack_path)
        from pack_model import PackModel
        self.model = PackModel(self.manifest, self.data)
        self.language_pack = self.model.language
        self.manager = self.manifest["manager"]
        self.manager_index = manager_index(self.manager)
        self.graphs = sorted(x["path"] for x in self.manifest["files"]
                           if x.get("kind") == "graph")
        if not self.graphs:
            raise kgpack.KGPackError("pack 안에 그래프가 없습니다")
        pack_id = hashlib.sha256(self.pack_path.read_bytes()).hexdigest()[:16]
        self.overlay = Path(overlay_root or "/private/tmp/nai-kgpack-overlay") / pack_id
        self.overlay.mkdir(parents=True, exist_ok=True)
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
        # 정서 표현 상태는 브라우저 세션마다 분리하고 메모리에만 둔다.
        # KG, overlay, 승인 기록의 내용·판정에는 절대 섞지 않는다.
        self.affect_sessions = {}
        self.project_roots = {}
        self.document_history = {}
        self.conversations = conversation_store.ConversationStore(repo_root / ".nai" / "conversations.json")
        self.definitions = local_definitions.DefinitionLookup(repo_root / "data" / "위키" / "정의문.jsonl")
        self.goals = goal_runtime.GoalRuntime(repo_root)
        # 모델은 답변기가 아니다. 이 객체는 모델 후보를 검증된 상태 JSON으로
        # 축소하는 경계이며, 테스트는 CallableBackend를 주입해 모델 품질과
        # 상태 계산을 독립적으로 검사한다.
        self.semantic_parser = semantic_parser.SemanticParser(model=self.model)

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
            if not target.exists() or (not current.endswith(".학습.jsonl") and target.read_bytes() != body):
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
        with self.lock:
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
        with self.lock:
            if self.routing:
                self.active_name = self.route = None
                self.routed_graphs, self.combined_shape = [], None
                self.graph = self.session = self.graph_path = None
            elif not self.self_learning:
                self.session = engine.Session(self.graph)
            self.history = []
            return self.info()

    def understand(self, text, session_id):
        """입력 분석 전용 경로: KG·검색·overlay·답변 엔진을 전혀 호출하지 않는다."""
        text = (text or "").strip()
        if not text:
            raise ValueError("입력이 비어 있습니다")
        session_id = str(session_id or "").strip()
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", session_id):
            raise ValueError("유효하지 않은 브라우저 세션입니다")
        with self.lock:
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
        with self.lock:
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
        with self.lock:
            if conversation_id:
                self.conversations.get_chat(str(conversation_id))
            context_id = "chat_" + str(conversation_id) if conversation_id else session_id
            prior_context_snapshot = None
            def finish(payload):
                answer = payload.get("answer")
                output = ((answer.get("answer_markdown") or answer.get("answer") or "") if isinstance(answer, dict)
                          else (payload.get("web_answer") or "계획을 만들었습니다. 승인 전에는 실행하지 않습니다."))
                if conversation_id:
                    context = self.reasoning_contexts.get(context_id)
                    try:
                        payload["conversation"] = self.conversations.append_turn(
                            str(conversation_id), text, output, payload.get("phase"),
                            reasoning_state=context.snapshot() if context else None)
                    except OSError:
                        if context is not None and prior_context_snapshot is not None:
                            context.restore(prior_context_snapshot)
                        raise
                return payload
            history = self.understanding_history.setdefault(context_id, [])
            understanding = input_understanding.understand(text, history, language_pack=self.language_pack)
            history.append(understanding); del history[:-30]
            affect = affect_state.update(self.affect_sessions.get(context_id), text, language_pack=self.language_pack)
            self.affect_sessions[context_id] = affect
            is_work = any(x["goal"]["kind"] == "perform" for x in understanding["segments"])
            if is_work:
                root = Path(self.conversations.project_root(str(conversation_id)) or self.project_roots.get(session_id, repo_root))
                plan = self.goals.plan_work(text, understanding, approval_mode, self.graph_path, root)
                self.goals.remember(context_id, plan)
                return finish(self._with_affect({"phase": "plan", "understanding": understanding, "plan": plan}, affect))
            if self.model.permits("relational_graph"):
                from reasoning_context import ReasoningContext
                if context_id not in self.reasoning_contexts:
                    context = ReasoningContext(model=self.model)
                    saved = self.conversations.reasoning_state(str(conversation_id)) if conversation_id else None
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
            # 정의형 질문은 모델이나 유사도보다 먼저 로컬 원문 표제어를 정확히 찾는다.
            # 일치하지 않으면 아무것도 추정하지 않고 기존 KG/웹 흐름으로 넘긴다.
            # 단일 표제어 정의는 기존처럼 KG보다 먼저 쓴다. 반면 A와 B의
            # 비교는 세균·바이러스처럼 전문 KG가 관계 자체를 명시했을 수 있다.
            # 이때는 라우터 점수가 아니라 실제 KG 판정이 '인정'인지로만
            # 선점 여부를 정한다. 약하게 잘못 라우팅된 그래프가 비교를 막지
            # 않도록 근거없음·미지는 정의 비교에 자리를 내준다.
            definition = self.definitions.lookup(text)
            if not definition:
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
                    answer_text = "\n\n".join("**%s** — %s" % (entry["term"], entry["definition"])
                                              for entry in entries)
                    winner, activated = " · ".join(definition["terms"]), definition["terms"]
                    sources = [{"node": entry["term"], "source": entry["source"]} for entry in entries]
                    verdict = "원문정의비교"
                else:
                    answer_text = "**%s** — %s" % (definition["term"], definition["definition"])
                    winner, activated = definition["term"], [definition["term"]]
                    sources, verdict = [{"node": definition["term"], "source": definition["source"]}], "원문정의"
                trace = {"mode": "local_definition", "question": text, "winner": winner,
                         "verdict": verdict, "activated": activated, "path": [], "sources": sources}
                answer = {"answer": answer_text, "answer_markdown": answer_text, "learned": False,
                         "known": True, "trace": trace, "info": self.info(), "definition": definition}
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
                answer_text = engine._not_found_reply(text, [])
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
            # 자가학습 KG도 여기서는 학습을 막는다. 웹 저장은 승인 행동으로만 가능하다.
            answer = self.ask(text, allow_learning=False)
            answer.update(semantic_failure)
            if not answer.get("known"):
                answer.setdefault("trace", {}).update(semantic_failure)
            verdict = (answer.get("trace") or {}).get("verdict")
            known = answer.get("known", verdict not in (None, "미지", "지식부족", "B2"))
            if known:
                return finish(self._with_affect({"phase": "answer", "understanding": understanding, "answer": answer}, affect))
            try:
                research = self.goals.research(text)
            except Exception as e:
                research = {"query": text, "sources": [], "verified": False, "error": "%s: %s" % (type(e).__name__, e)}
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
            learning_path = self._materialize(self.auto_graph) if self.auto_graph else self.graph_path
            root = Path(self.conversations.project_root(str(conversation_id)) or self.project_roots.get(session_id, repo_root))
            plan = self.goals.plan_learning(text, research, approval_mode, learning_path, root)
            self.goals.remember(context_id, plan)
            return finish(self._with_affect({"phase": "research", "understanding": understanding, "answer": answer,
                                      "research": research, "web_answer": web_grounds_answer(research), "plan": plan,
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
            answer = "선택된 KG에서 질문과 정확히 일치하는 근거를 찾지 못했습니다. 유사도만으로 답하지 않습니다."
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
                    answer = "서로 다른 원문 두 곳에서 완결된 지식을 만들지 못했습니다."
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
        with self.lock:
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
                    answer = "이 질문을 맡을 KG를 고르지 못했습니다."
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


def attach_to_manager(app, names):
    """자가학습이 들인 그래프를 매니저 그래프에 노드로 붙인다. -> 붙은 수

    매니저는 pack manifest 에서 오는데 pack 은 읽기 전용이라, 새로 지은
    그래프는 그 목록에 없다. 붙이지 않으면 화면의 '전체 지식 그래프' 가
    218개에서 멈춘 채 실제로는 244개인 상태가 된다 — 보여주는 것이 곧
    거짓이 되는 자리다.

    붙이면 라우터도 그 그래프를 후보로 본다. 매니저 색인을 같이 다시
    짓는 이유다."""
    attached = 0
    with app.lock:
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
    with app.lock:
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
             "밀리초": ms, "인코더": engine.MODEL, "쓴이": author,
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
