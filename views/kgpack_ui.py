# -*- coding: utf-8 -*-
"""단일 .kgpack을 사용하는 로컬 대화 UI.

    KG_ENCODER=문자 python views/kgpack_ui.py --pack NAI.kgpack --port 8766

pack은 읽기 전용이다. 자가학습으로 생긴 새 지식은 /private/tmp의 pack별 overlay에
쌓여, 대화 중에는 `pack + 새 지식`으로 읽힌다.
"""
from __future__ import annotations

import argparse
from collections import deque
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
import threading
from urllib.parse import urlparse

os.environ.setdefault("KG_ENCODER", "문자")
루트 = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(루트))

import engine  # noqa: E402
import kgpack  # noqa: E402
import web_learn  # noqa: E402
from encoder import _vec, 조각내기  # noqa: E402


매니저선택 = "__kg_manager__"


def 점수(본문, 후보, graph):
    조각들 = list(조각내기(본문)) or [본문]
    벡터들 = [_vec(x) for x in 조각들]
    out = []
    for node in 후보:
        if node in graph.get("vec", {}):
            out.append((node, max(float((graph["vec"][node] @ v).max()) for v in 벡터들)))
    return sorted(out, key=lambda x: -x[1])


def 경로(graph, start, end):
    if not start or start == end:
        return []
    seen, queue = {start: None}, deque([start])
    while queue:
        here = queue.popleft()
        for relation, nxt in graph["adj"].get(here, []):
            if relation not in engine.POS or nxt in seen:
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


def 그래프얼개(graph):
    requirements = set(engine.요건(graph))
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


def 매니저색인(manager):
    graph = {"역할": manager.get("role", "노드 매니저"),
             "목표": manager.get("goal", "그래프고르기"),
             "임계값": {"A_MIN": 0.40, "OK_MIN": 0.50},
             "공통층": {n["path"]: list(n.get("examples") or [n["path"]])
                       for n in manager.get("nodes", [])},
             "사례층": {}, "무관층": {}, "엣지": [], "대사": {},
             "수치조건": {}, "adj": {}, "증거": []}
    graph["vec"] = engine._예시벡터(graph)
    return graph


def 매니저얼개(manager):
    goal = manager.get("goal", "그래프고르기")
    nodes = [{"name": goal, "kind": "goal", "examples": ["질문에 알맞은 KG 선택"],
              "source": "kgpack manifest"}]
    nodes += [{"name": n["path"], "kind": "concept",
               "examples": list(n.get("examples") or []),
               "source": "%s · 목표 %s" % (n.get("role") or "역할 없음", n.get("goal") or "없음")}
              for n in manager.get("nodes", [])]
    return {"nodes": nodes, "edges": list(manager.get("edges") or []), "goal": goal,
            "requirements": [], "thresholds": {"route_min": 0.45}}


def 마크다운답(answer, trace):
    """완결된 지식 문장을 읽기 좋은 문서로 보여준다."""
    if not trace or trace.get("mode") != "self_learning" or not trace.get("winner"):
        return answer
    topic = trace["winner"].removeprefix("지식_")
    return "## %s\n\n%s" % (topic, answer)


def 세션상태(session):
    secured = session.확보()
    return {"secured": secured, "self_counter": sorted(session.자책),
            "patience": session.인내심, "turn": session.회차,
            "result": session.결과(), "learned_phrases": [list(x) for x in session.배운것]}


def 질문대목(question):
    """복합 질문을 KG를 따로 고를 수 있는 의미 대목으로 나눈다."""
    parts = []
    for raw in re.split(r"(?:\r?\n+|(?<=[.!?。！？])\s+|\s+(?:그리고|또한|동시에|한편)\s+)", question):
        part = re.sub(r"^(?:그리고|또한|동시에|한편)\s+", "", raw.strip(" ,;:\t"))
        if part:
            parts.append(part)
    return parts or [question]


def 병합얼개(items):
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


def 병합추적(items, route):
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


class 앱상태:
    def __init__(self, pack_path, overlay_root=None):
        self.pack_path = Path(pack_path).resolve()
        self.manifest, self.data = kgpack.읽기(self.pack_path)
        self.manager = self.manifest["manager"]
        self.manager_index = 매니저색인(self.manager)
        self.graphs = sorted(x["path"] for x in self.manifest["files"]
                           if x.get("kind") == "graph")
        if not self.graphs:
            raise kgpack.KGPackError("pack 안에 그래프가 없습니다")
        pack_id = hashlib.sha256(self.pack_path.read_bytes()).hexdigest()[:16]
        self.overlay = Path(overlay_root or "/private/tmp/nai-kgpack-overlay") / pack_id
        self.overlay.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.auto_graph = next((x for x in self.graphs if x.endswith("graph_자가학습.kg")), None)
        self.selected = 매니저선택
        self.active_name = self.route = None
        self.routed_graphs, self.combined_shape = [], None
        self.graph = self.session = self.graph_path = None
        self.history = []

    def _materialize(self, name):
        target = self.overlay / name
        target.parent.mkdir(parents=True, exist_ok=True)
        body = self.data[name]
        if not target.exists() or target.read_bytes() != body:
            temp = target.with_name(target.name + ".tmp-%d" % os.getpid())
            try:
                temp.write_bytes(body)
                os.replace(temp, target)
            finally:
                try:
                    temp.unlink()
                except FileNotFoundError:
                    pass
        return target

    @property
    def 자가학습(self):
        return bool(self.active_name and self.active_name.endswith("graph_자가학습.kg"))

    @property
    def 라우팅중(self):
        return self.selected == 매니저선택

    def _activate(self, name, force=False):
        if name not in self.graphs:
            raise ValueError("pack에 없는 그래프입니다")
        if not force and self.active_name == name and self.graph is not None:
            return
        self.active_name = name
        self.graph_path = self._materialize(name)
        self.graph = (web_learn.불러오기(str(self.graph_path))
                      if name.endswith("graph_자가학습.kg") else engine.load(str(self.graph_path)))
        self.session = None if name.endswith("graph_자가학습.kg") else engine.세션(self.graph)

    def select(self, name):
        with self.lock:
            self.selected = name
            self.route = None
            self.routed_graphs, self.combined_shape = [], None
            if name == 매니저선택:
                self.active_name = None
                self.graph = self.session = self.graph_path = None
            else:
                self._activate(name, force=True)
            self.history = []
            return self.info()

    def info(self):
        records = (web_learn.수집읽기(web_learn.수집경로(str(self.graph_path)))
                   if self.자가학습 else [])
        accepted = [r for r in records if r.get("수집형식") == 3 and r.get("문장들")
                    and web_learn.주제관련(r.get("주제"), r.get("본문"))]
        multi = self.라우팅중 and len(self.routed_graphs) > 1
        role = (("노드 매니저 → %d개 KG" % len(self.routed_graphs)) if multi else
                (("노드 매니저 → " + (self.graph.get("역할") or "역할 없음")) if self.라우팅중 and self.graph
                else (self.manager.get("role") if self.라우팅중 else self.graph.get("역할")))
                )
        goal = (self.combined_shape["goal"] if self.combined_shape else
                (self.graph.get("목표") if self.graph else self.manager.get("goal")))
        single_self = self.자가학습 and not multi
        return {
            "pack": self.pack_path.name,
            "pack_path": str(self.pack_path),
            "graphs": self.graphs,
            "selected": self.selected,
            "manager_selection": 매니저선택,
            "routing_mode": self.라우팅중,
            "routed_graph": self.routed_graphs[0] if self.라우팅중 and self.routed_graphs else None,
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
            "manager_graph": 매니저얼개(self.manager),
            "graph": (self.combined_shape or (그래프얼개(self.graph) if self.graph else
                      {"nodes": [], "edges": [], "goal": "KG선택대기",
                       "requirements": [], "thresholds": {}})),
            "dialogue": list(self.history),
            "session": None if single_self or multi or not self.session else 세션상태(self.session),
        }

    def reset(self):
        with self.lock:
            if self.라우팅중:
                self.active_name = self.route = None
                self.routed_graphs, self.combined_shape = [], None
                self.graph = self.session = self.graph_path = None
            elif not self.자가학습:
                self.session = engine.세션(self.graph)
            self.history = []
            return self.info()

    def _일반질문(self, question):
        graph = self.graph
        evidence, evidence_score = engine.match_evidence(question, graph)
        body = engine.증거지우기(question, graph, evidence)
        pool = ([n for n in graph["사례층"] if n not in graph["증거"]]
                + list(graph["공통층"]))
        ranks = 점수(body, pool, graph)
        nulls = 점수(body, list(graph.get("무관층", {})), graph)
        winner = ranks[0][0] if ranks else None
        answer = self.session.대답(question)
        route = 경로(graph, evidence or winner, graph["목표"])
        trace = {"mode": "argument", "question": question, "winner": winner,
                 "verdict": self.session.판정,
                 "evidence": {"name": evidence, "score": round(evidence_score, 3)},
                 "rankings": [[n, round(v, 3)] for n, v in ranks[:5]],
                 "null_rankings": [[n, round(v, 3)] for n, v in nulls[:3]],
                 "margin": round(ranks[0][1] - ranks[1][1], 3) if len(ranks) > 1 else None,
                 "path": route,
                 "activated": list(dict.fromkeys([x for x in [evidence, winner] if x]
                                                  + [n for e in route for n in (e[0], e[2])]))}
        self.history.append({"question": question, "claim": winner,
                             "evidence": evidence, "verdict": self.session.판정,
                             "sources": [], "learned": False})
        return {"answer": answer, "answer_markdown": answer, "learned": False, "verdict": self.session.판정,
                "result": self.session.결과(), "trace": trace, "info": self.info()}

    def _자가주장(self, question):
        table = []
        for node, aliases in (self.graph.get("_주제별칭") or {}).items():
            table.extend((a, node) for a in aliases)
        return next((node for alias, node in sorted(table, key=lambda x: len(x[0]), reverse=True)
                    if alias and alias in question), None)

    def _자가추적(self, question, claim, learned):
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
                if a == claim and relation in engine.POS:
                    proof_edges.append([a, relation, b])
        return {"mode": "self_learning", "question": question, "winner": claim,
                "verdict": "채택" if claim else "지식부족", "evidence": None,
                "rankings": [], "null_rankings": [], "margin": None,
                "path": proof_edges,
                "activated": ([claim] if claim else []) + facts + [s["node"] for s in sources],
                "sources": sources, "facts": facts, "learned": learned}

    def _자가질문(self, question):
        known, answer = web_learn.묻다(self.graph, question)
        learned = False
        if not known:
            topic, _aliases = web_learn.주제추출(self.graph, question)
            if topic:
                try:
                    fresh = web_learn.배우기(str(self.graph_path), topic, question,
                                           개수=5, 최소출처=2)
                except web_learn.학습실패 as e:
                    return {"answer": "자동 학습을 완료하지 못했습니다: %s" % e,
                            "answer_markdown": "자동 학습을 완료하지 못했습니다: %s" % e,
                            "learned": False, "trace": None, "info": self.info()}
                if fresh:
                    self.graph = web_learn.불러오기(str(self.graph_path))
                    known, answer = web_learn.묻다(self.graph, question)
                    learned = known
                elif not known:
                    answer = "서로 다른 원문 두 곳에서 완결된 지식을 만들지 못했습니다."
        claim = self._자가주장(question) if known else None
        trace = self._자가추적(question, claim, learned)
        self.history.append({"question": question, "claim": claim,
                             "evidence": None, "verdict": trace["verdict"],
                             "sources": [s["source"] for s in trace["sources"]],
                             "learned": learned})
        return {"answer": answer, "answer_markdown": 마크다운답(answer, trace),
                "learned": learned, "known": known, "trace": trace, "info": self.info()}

    def ask(self, question):
        question = (question or "").strip()
        if not question:
            raise ValueError("질문이 비어 있습니다")
        with self.lock:
            if self.라우팅중:
                self.combined_shape = None
                segments, candidate_scores = [], {}
                for part in 질문대목(question):
                    name, score, candidates = engine.그래프고르기(part, self.manager_index,
                                                                  최소=0.45, 개수=5)
                    for candidate, value in candidates:
                        candidate_scores[candidate] = max(candidate_scores.get(candidate, 0), value)
                    selected = ([n for n, value in candidates
                                if value >= 0.45 and value >= score - 0.05] if name else [])
                    fallback = False
                    if not selected and self.auto_graph:
                        selected, fallback = [self.auto_graph], True
                    for selected_name in selected:
                        selected_score = next((c for n, c in candidates if n == selected_name), None)
                        segments.append({"question": part, "selected": selected_name,
                                         "score": selected_score,
                                         "best_score": score, "fallback": fallback,
                                         "candidates": [[n, c] for n, c in candidates]})
                if not segments:
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
                        piece = self._자가질문(part_question) if self.자가학습 else self._일반질문(part_question)
                        label = name.removeprefix("graphs/").removesuffix(".kg")
                        items.append({"graph": name, "question": part_question,
                                      "answer": piece.get("answer", ""),
                                      "trace": piece.get("trace"), "shape": 그래프얼개(self.graph)})
                        plain_parts.append("[%s]\n%s" % (label, piece.get("answer", "")))
                        markdown_parts.append("## %s\n\n%s" % (label, piece.get("answer", "")))
                    self.combined_shape = 병합얼개(items)
                    trace = 병합추적(items, self.route)
                    result = {"answer": "\n\n".join(plain_parts),
                              "answer_markdown": "\n\n".join(markdown_parts),
                              "learned": any((x.get("trace") or {}).get("learned") for x in items),
                              "trace": trace, "parts": items, "info": self.info()}
                    return result
                self._activate(names[0])
                question = ". ".join(grouped[names[0]])
            else:
                self.routed_graphs = []
                self.combined_shape = None
            result = self._자가질문(question) if self.자가학습 else self._일반질문(question)
            if self.라우팅중:
                trace = result.get("trace") or {"mode": "manager", "question": question,
                                                "winner": None, "verdict": "오류",
                                                "activated": [], "path": []}
                trace["route"] = self.route
                result["trace"] = trace
                result["info"] = self.info()
            return result


class 손(BaseHTTPRequestHandler):
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
        if length > 1024 * 1024:
            raise ValueError("요청이 너무 큽니다")
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            html = (Path(__file__).with_name("kgpack_ui.html")).read_bytes()
            return self._send(html, "text/html")
        if path == "/api/info":
            return self._json(self.app.info())
        self.send_error(404)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            body = self._body()
            if path == "/api/select":
                return self._json(self.app.select(body.get("graph")))
            if path == "/api/reset":
                return self._json(self.app.reset())
            if path == "/api/ask":
                return self._json(self.app.ask(body.get("question")))
            self.send_error(404)
        except (ValueError, kgpack.KGPackError, json.JSONDecodeError) as e:
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
    app = 앱상태(args.pack, args.overlay)
    손.app = app
    server = ThreadingHTTPServer((args.host, args.port), 손)
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
