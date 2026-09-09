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
        """읽기 전용 조사. 저장은 절대 하지 않는다.

        원문을 고르는 잣대는 물음 전체가 아니라 물음의 내용 낱말이다. 물음을
        통째로 넘기면 페이지 문장 안에 그 물음이 그대로 들어 있어야 관련으로
        쳐져서, 사람이 말로 쓴 물음은 어느 것도 출처를 못 얻었다."""
        terms = web_learn.question_word(question) or question
        items, sources = web_learn.search(question, count=limit), []
        for item in items:
            try:
                title, sentences = web_learn.read_source(item["url"], terms, max_sentence=3)
            except Exception:
                continue
            if sentences:
                sources.append({"url": item["url"], "domain": item["도메인"], "title": title, "sentences": sentences})
            if len(sources) >= 2:
                break
        return {"query": question, "sources": sources, "verified": len({x["domain"] for x in sources}) >= 2}

    def plan_learning(self, question, research, mode, graph_path, workspace=None):
        actions, unsupported = [], []
        topic = None
        if research["verified"] and graph_path:
            try:
                topic, _aliases = web_learn.extract_topic(web_learn.load(graph_path), question)
            except (OSError, ValueError, UnicodeError) as e:
                unsupported.append("학습 대상 그래프를 읽을 수 없습니다: %s" % e)
            if topic:
                # 승인할 때 다시 그래프 상태를 보고 주제를 바꾸지 않는다. 사람이
                # 검토한 계획의 주제와 실제 저장 행동이 같아야 승인 기록도
                # 재현 가능하다.
                actions.append(self._action("knowledge.learn", "검증된 웹 지식을 overlay에 저장", target=str(graph_path), risk="write", expected="출처 연결 사실 노드 추가", payload={"question": question, "topic": topic}))
            elif not unsupported:
                unsupported.append("질문에서 학습할 주제를 추출하지 못해 지식을 저장하지 않습니다")
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
            if not path.is_file():        # 여기도 경로만 들고 온다. 같은 이유로 같이 막는다.
                return {"action": action["id"], "status": "failed",
                        "output": "읽을 파일이 없습니다: %s" % path}
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
            # 계획은 경로 문자열만 들고 있다. 승인까지 사이에 그 파일이 없어질
            # 수 있고, 그때 파이썬 예외를 그대로 올리면 화면에 트레이스백이
            # 나온다. 무엇이 없어졌고 무엇을 하면 되는지 말해주는 실패로 돌린다.
            if not Path(graph_path).exists():
                return {"action": action["id"], "status": "failed",
                        "output": "저장 대상 그래프가 사라졌습니다: %s\n"
                                  "질문을 다시 물어 계획을 새로 만들어 주세요." % graph_path}
            topic = str(action["payload"].get("topic") or "").strip()
            if not topic:
                return {"action": action["id"], "status": "failed",
                        "output": "승인된 계획에 학습 주제가 없습니다. 질문을 다시 물어 계획을 새로 만들어 주세요."}
            try:
                learned = bool(web_learn.save_verified_knowledge(
                    graph_path, topic, action["payload"]["question"],
                    (plan.get("research") or {}).get("sources") or [], min_source=2))
            except web_learn.LearnFailed as e:
                return {"action": action["id"], "status": "failed", "output": "저장할 수 없습니다: %s" % e}
            return {"action": action["id"], "status": "done" if learned else "failed", "output": "overlay 저장" if learned else "저장할 검증 지식을 만들지 못함"}
        raise ValueError("등록되지 않은 행동입니다: " + kind)
