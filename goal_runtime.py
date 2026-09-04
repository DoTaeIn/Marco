# -*- coding: utf-8 -*-
"""목적 → 승인 가능한 행동 계획 → 등록 도구 실행.

여기에는 자유 셸 실행기가 없다. 모든 효과는 이 파일의 등록 도구를 거친다.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

import web_learn


DIRECT_RISKS = {"destructive", "external", "credential_or_unknown", "unknown"}


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]


def _inside(root, target):
    root, target = root.resolve(), (root / target).resolve()
    if target != root and root not in target.parents:
        raise ValueError("작업공간 밖 경로는 실행할 수 없습니다")
    return target


class GoalRuntime:
    def __init__(self, workspace):
        self.workspace = Path(workspace).resolve()
        self.pending = {}

    def _action(self, kind, label, *, target=None, risk="write", expected="", reversible=True, payload=None):
        return {"id": kind + "-" + _hash([kind, target, payload])[:8], "kind": kind, "label": label,
                "target": target, "risk": risk, "expected_change": expected, "reversible": reversible,
                "requires_direct_approval": risk in DIRECT_RISKS, "payload": payload or {}}

    def plan_work(self, text, understanding, mode, graph_path=None, workspace=None):
        segment = next((x for x in understanding["segments"] if x["goal"]["kind"] == "perform"), understanding["segments"][0])
        command = segment["command"]
        entities = [x["text"] for x in segment.get("entities", []) if x["kind"] == "path_or_file"]
        target = entities[0] if entities else None
        lowered = text.lower()
        actions, unsupported = [], []
        if command["risk"] == "read" and target:
            actions.append(self._action("workspace.read", "작업공간 파일 읽기", target=target, risk="read", expected="내용을 화면에 반환"))
        elif ("테스트" in text or re.search(r"\b(test|unittest)\b", lowered)):
            actions.append(self._action("workspace.tests", "프로젝트 테스트 실행", risk="write", expected="테스트 출력만 기록", payload={"command": ["python", "-m", "unittest"]}))
        elif command["risk"] == "write" and target:
            quoted = re.search(r"[\"'“”](.+?)[\"'“”]", text)
            if quoted:
                actions.append(self._action("workspace.write_text", "명시한 텍스트 파일 저장", target=target, risk="write", expected="새 파일 또는 내용 변경", payload={"content": quoted.group(1)}))
            else:
                unsupported.append("파일에 저장할 정확한 따옴표 내용이 없습니다")
        elif command["risk"] in DIRECT_RISKS:
            unsupported.append("고위험·외부 명령은 등록된 전용 도구가 있어야 실행할 수 있습니다")
        else:
            unsupported.append("이 목적에 맞는 등록 작업 도구를 찾지 못했습니다")
        plan = {"type": "work", "input": text, "mode": mode, "actions": actions, "unsupported": unsupported,
                "created_at": time.time(), "expires_at": time.time() + 600,
                "graph_path": str(graph_path) if graph_path else None,
                "workspace": str(Path(workspace or self.workspace).resolve())}
        plan["plan_id"] = _hash(plan)
        plan["plan_hash"] = _hash({k: v for k, v in plan.items() if k not in ("created_at", "expires_at")})
        return plan

    def research(self, question, limit=5):
        """읽기 전용 조사. 저장은 절대 하지 않는다."""
        items, sources = web_learn.검색(question, 개수=limit), []
        for item in items:
            try:
                title, sentences = web_learn.원문읽기(item["url"], question, 최대문장=3)
            except Exception:
                continue
            if sentences:
                sources.append({"url": item["url"], "domain": item["도메인"], "title": title, "sentences": sentences})
            if len(sources) >= 2:
                break
        return {"query": question, "sources": sources, "verified": len({x["domain"] for x in sources}) >= 2}

    def plan_learning(self, question, research, mode, graph_path, workspace=None):
        actions, unsupported = [], []
        if research["verified"] and graph_path:
            actions.append(self._action("knowledge.learn", "검증된 웹 지식을 overlay에 저장", target=str(graph_path), risk="write", expected="출처 연결 사실 노드 추가", payload={"question": question}))
        else:
            unsupported.append("서로 다른 두 원문 출처가 없어 지식을 저장하지 않습니다")
        plan = {"type": "learning", "input": question, "mode": mode, "actions": actions, "unsupported": unsupported,
                "research": research, "created_at": time.time(), "expires_at": time.time()+600,
                "graph_path": str(graph_path) if graph_path else None,
                "workspace": str(Path(workspace or self.workspace).resolve())}
        plan["plan_id"] = _hash(plan); plan["plan_hash"] = _hash({k:v for k,v in plan.items() if k not in ("created_at", "expires_at")})
        return plan

    def remember(self, session, plan):
        self.pending[(session, plan["plan_id"])] = plan

    def approve(self, session, plan_id, plan_hash, action_ids, direct=False):
        plan = self.pending.get((session, plan_id))
        if not plan or plan["plan_hash"] != plan_hash or plan["expires_at"] < time.time():
            raise ValueError("승인할 계획이 없거나 만료되었습니다")
        allowed = [a for a in plan["actions"] if a["id"] in set(action_ids or [])]
        if plan["mode"] == "all_steps" and len(allowed) != 1:
            raise ValueError("모든 단계 승인 모드에서는 한 행동만 승인할 수 있습니다")
        blocked = [a for a in allowed if a["requires_direct_approval"] and not direct]
        run = [a for a in allowed if a not in blocked]
        results = [self._run(action, plan) for action in run]
        return {"plan_id": plan_id, "executed": results, "needs_direct_approval": blocked,
                "remaining": [a for a in plan["actions"] if a not in run]}

    def _run(self, action, plan):
        kind = action["kind"]
        workspace = Path(plan.get("workspace") or self.workspace)
        if kind == "workspace.read":
            path = _inside(workspace, action["target"])
            return {"action": action["id"], "status": "done", "output": path.read_text(encoding="utf-8")[:12000]}
        if kind == "workspace.write_text":
            path = _inside(workspace, action["target"]); path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(action["payload"]["content"], encoding="utf-8")
            return {"action": action["id"], "status": "done", "output": str(path)}
        if kind == "workspace.tests":
            p = subprocess.run(action["payload"]["command"], cwd=workspace, capture_output=True, text=True, timeout=120)
            return {"action": action["id"], "status": "done" if p.returncode == 0 else "failed", "output": (p.stdout+p.stderr)[-12000:], "returncode": p.returncode}
        if kind == "knowledge.learn":
            graph_path = plan.get("graph_path")
            if not graph_path:
                raise ValueError("overlay 대상 그래프가 없습니다")
            topic, _ = web_learn.주제추출(web_learn.불러오기(graph_path), action["payload"]["question"])
            learned = bool(topic and web_learn.배우기(graph_path, topic, action["payload"]["question"], 개수=5, 최소출처=2))
            return {"action": action["id"], "status": "done" if learned else "failed", "output": "overlay 저장" if learned else "저장할 검증 지식을 만들지 못함"}
        raise ValueError("등록되지 않은 행동입니다: " + kind)
