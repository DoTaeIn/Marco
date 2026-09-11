# -*- coding: utf-8 -*-
"""그래프가 고른 행동을 실제로 실행한다.

web_learn.py 가 "웹에서 주워온 것을 그래프에 얹는다"면 이 파일은 그 반대편이다.
그래프에 적힌 것을 꺼내서 **돌린다.** 지키는 규칙은 같은 자리에 있다.

1. 계획을 코드에 적지 않는다. 요청 노드에서 -증명-> 로 나가는 노드가 곧 작업 큐다.
   차례도 .kg 에 적힌 차례를 따른다. 파이썬 리스트에 하드코딩하지 않는다.
2. 에러 로그도 발화로 취급한다. engine.match_evidence 가 관찰 노드를 찾고
   -증명-> 상태 -충족-> 행동 이 복구 행동이다. if "no such file" in ... 을 쓰지 않는다.
   새 에러 유형은 코드가 아니라 .kg 에 는다.
3. 도구가 등록된 노드만 돈다. 그래프에 행동 노드가 있어도 손으로 등록한 함수가
   없으면 실행하지 않고 그 사실을 결과에 남긴다. 그래프가 코드를 만들지는 못한다.
4. **실패를 성공이라고 말하지 않는다.** 계획의 모든 노드가 성공하고 그 중 하나가
   목표에 닿을 때만 완료다. 중간에 끊기면 어디서 왜 끊겼는지가 결과에 남는다.
   (예전 universal_agent.py 는 break 로 빠져나온 뒤에도 "성공적으로 완료"를 찍었다.)
5. 원본 .kg 를 수정하지 않는다. 실행 자취는 옆의 .실행.jsonl 에 쌓인다.
   .학습.jsonl / .수집.jsonl 과 같은 자리, 같은 규칙이다.

요청과 에러는 둘 다 문자열 포함(match_evidence)으로 먼저 잰다. 에러 메시지는
원래 정해진 문자열이고 요청도 별칭이 짧아서, 임베딩보다 정확하고 공짜다.
안 걸릴 때만 임베딩으로 넘어간다.

인코더는 KG_ENCODER=문자 를 기본으로 둔다. 토큰을 쓰지 않는다.
"""
import json
import os
import sys
import time

os.environ.setdefault("KG_ENCODER", "문자")   # 토큰 없는 인코더가 이 파일의 기본값이다

import engine as eng


# ── 그래프 읽기 ─────────────────────────────────────────────────────────
def load(kg_path):
    """engine.load() 그대로. 어느 파일에서 왔는지만 들려 보낸다(자취 파일 경로용)."""
    g = eng.load(kg_path)
    g["_경로"] = str(kg_path)
    return g


def trace_path(g):
    return os.path.splitext(g.get("_경로") or "graph.kg")[0] + ".실행.jsonl"


def _proof_targets(g, node):
    return [d for r, d in g["adj"].get(node, []) if r == "증명"]


def _satisfy_targets(g, node):
    return [d for r, d in g["adj"].get(node, []) if r == "충족"]


# ── 발화 → 증거 노드 ────────────────────────────────────────────────────
def pick_evidence(g, phrase):
    """→ (증거노드, 점수, 방법). 못 찾으면 (None, 점수, "미지").

    포함 검사가 먼저다. 에러 로그는 파이썬이 정해 놓은 문자열이라 별칭과 글자가
    그대로 겹치고, 임베딩으로 재면 오히려 뭉개진다(engine.match_evidence 주석).
    표현이 바뀐 사용자 요청만 임베딩으로 넘어간다."""
    node, score = eng.match_evidence(phrase, g)
    if node:
        return node, score, "포함"
    node, score = eng.match(phrase, g["증거"], g)
    if node and score >= g["임계값"]["A_MIN"]:
        return node, score, "임베딩"
    return None, score, "미지"


def find_action(g, evidence, tool_table):
    """증거 노드에서 실제로 돌릴 수 있는 행동 노드까지 내려간다.

    두 모양을 다 받는다. 어느 쪽인지 코드가 미리 알지 않는다 — 도구가 붙은
    노드에 닿을 때까지 내려갈 뿐이다. 그래서 '요청'과 '관찰'을 이름으로
    구분하지 않아도 되고, 새 그래프가 다른 낱말을 써도 그대로 돈다.

        요청 -증명-> 행동(도구 있음)                ... 계획
        관찰 -증명-> 상태 -충족-> 행동(도구 있음)    ... 복구

    → (행동들, 경유들, 도구없음)
      도구없음 은 그래프엔 있는데 등록된 도구가 없어 실행할 수 없는 노드다.
      조용히 건너뛰면 '계획을 다 했다'가 거짓말이 되므로 결과에 싣는다."""
    action, via, missing = [], [], []
    for n in _proof_targets(g, evidence):
        if n in tool_table:
            if n not in action:
                action.append(n)
            continue
        bottom = [m for m in _satisfy_targets(g, n) if m in tool_table]
        if bottom:
            via.append(n)
            for m in bottom:
                if m not in action:
                    action.append(m)
        else:
            missing.append(n)
    return action, via, missing


# ── 루프 ────────────────────────────────────────────────────────────────
def run(g, phrase, tool_table, context=None, cap=3, write=True):
    """관찰-복구-전진 루프. → 결과 딕셔너리.

    상한: 같은 행동을 몇 번까지 시도하나. 복구가 실제로는 아무것도 못 고칠 때
    무한히 도는 것을 막는다. 예전 self_learning_agent.py 에는 이게 없어서
    주입이 조용히 실패하면 RecursionError 까지 갔다."""
    # 복사하지 않는다. 도구들은 맥락으로 상태를 주고받고, 무엇이 바뀌었는지는
    # 호출자도 봐야 한다 — 결측치를 0 으로 채웠다는 사실이 여기 담긴다.
    # 복사했더니 그 경고가 조용히 사라졌다.
    context = {} if context is None else context
    trace = []

    evidence, score, method = pick_evidence(g, phrase)
    result = {"말": phrase, "그래프": g.get("_경로"), "증거": evidence, "점수": score,
            "방법": method, "계획": [], "도구없음": [], "성공": [], "자취": trace,
            "완료": False, "왜": None, "시각": time.strftime("%Y-%m-%dT%H:%M:%S")}

    if not evidence:
        result["왜"] = "이 요청에 맞는 노드가 그래프에 없다 (최고점 %.3f)" % score
        return _finish(g, result, write)

    plan, via, missing = find_action(g, evidence, tool_table)
    result.update({"계획": plan, "경유": via, "도구없음": missing})
    if not plan:
        result["왜"] = ("'%s' 는 그래프에 있으나 실행할 도구가 등록되지 않았다: %s"
                      % (evidence, ", ".join(missing) or "(증명 대상 없음)"))
        return _finish(g, result, write)

    queue, success, tries, stuck = list(plan), [], {}, None
    while queue:
        node = queue.pop(0)
        tries[node] = tries.get(node, 0) + 1
        try:
            observe = tool_table[node](context)
        except Exception as e:
            error_text = "%s: %s" % (type(e).__name__, e)
            trace.append({"행동": node, "결과": "실패", "에러": error_text})

            if tries[node] >= cap:
                stuck = "%s 를 %d번 시도했다. 상한(%d)이다" % (node, tries[node], cap)
                break

            # 에러 로그를 그대로 그래프에 던진다. 여기가 if 문이 아니라는 것이 요점이다.
            evidence2, score2, method2 = pick_evidence(g, error_text)
            if not evidence2:
                stuck = "이 에러에 맞는 관찰 노드가 그래프에 없다 (최고점 %.3f)" % score2
                break
            restore, via2, missing2 = find_action(g, evidence2, tool_table)
            # 실패한 그 행동으로 복구하라는 답은 무한루프다. 그래프가 그렇게 적혀
            # 있어도 여기서 끊는다.
            restore = [m for m in restore if m != node]
            if not restore:
                stuck = ("%s 까지는 왔는데 복구 행동에 도구가 없다: %s"
                        % (evidence2, ", ".join(via2 + missing2) or "(증명 대상 없음)"))
                break
            trace.append({"복구": restore, "증거": evidence2, "경유": via2,
                         "방법": method2, "점수": score2})
            context["에러"] = error_text          # 복구 도구가 에러 원문을 볼 수 있게 한다
            queue = restore + [node] + queue        # 복구 먼저, 그 다음 실패한 작업 재시도
            continue

        trace.append({"행동": node, "결과": "성공", "관찰": observe})
        if node not in success:
            success.append(node)

    result["성공"] = success
    reach = [n for n in plan if g["목표"] in eng.reachable(g, n)]
    result["목표에닿음"] = reach

    if stuck:
        result["왜"] = stuck
    elif missing:
        result["왜"] = "계획 일부에 도구가 없어 건너뛰었다: " + ", ".join(missing)
    elif set(plan) - set(success):
        result["왜"] = "실행 못 한 계획이 남았다: " + ", ".join(set(plan) - set(success))
    elif not reach:
        result["왜"] = "계획을 다 했지만 '%s' 에 닿는 행동이 하나도 없다" % g["목표"]
    else:
        result["완료"] = True
    return _finish(g, result, write)


def _finish(g, result, write):
    """실행 자취를 옆파일에 쌓는다. 원본 .kg 는 건드리지 않는다."""
    if write and g.get("_경로"):
        try:
            with open(trace_path(g), "a", encoding="utf-8") as f:
                f.write(json.dumps(result, ensure_ascii=False, default=str) + "\n")
        except OSError:
            pass                        # 못 써도 실행 결과 자체는 옳다
    return result


# ── 보고 ────────────────────────────────────────────────────────────────
def report(result, g=None):
    """사람이 읽는 형태로 찍는다. 완료가 아니면 완료라고 쓰지 않는다."""
    print("\n[요청] %s" % result["말"])
    if not result["증거"]:
        print("[!] %s" % result["왜"])
        return result["완료"]
    print("[매칭] %s  (%s, %.3f)" % (result["증거"], result["방법"], result["점수"]))
    if result.get("경유"):
        print("[경유] %s" % " · ".join(result["경유"]))
    print("[계획] %s" % (" → ".join(result["계획"]) or "(없음)"))
    if result["도구없음"]:
        print("[도구없음] %s" % ", ".join(result["도구없음"]))

    for slot in result["자취"]:
        if "복구" in slot:
            print("   ↻ %s → %s → 복구: %s"
                  % (slot["증거"], " · ".join(slot["경유"]) or "-", ", ".join(slot["복구"])))
        elif slot["결과"] == "성공":
            print("   ✓ %-18s %s" % (slot["행동"], slot.get("관찰", "")))
        else:
            print("   ✗ %-18s %s" % (slot["행동"], slot["에러"]))

    if result["완료"]:
        print("[완료] %s 도달 · 요건 %s"
              % (g["목표"] if g else "목표", ", ".join(result.get("목표에닿음", []))))
    else:
        print("[미완료] %s" % result["왜"])
    return result["완료"]


# ── 등록기 점검 ─────────────────────────────────────────────────────────
def check(kg_path, tool_table, show=True):
    """그래프와 도구 등록기가 서로 맞는지 본다. 실행은 하지 않는다.

    두 방향을 다 본다. 도구는 있는데 노드가 없으면 그 도구는 영원히 안 불린다
    (오타 하나로 조용히 죽는다). 노드는 있는데 도구가 없으면 그 요청은 실행이
    안 되는데, 그건 정상일 수도 있으므로 실패가 아니라 알림으로 낸다."""
    problem, notice = [], []
    g = load(kg_path)

    node = set(g["공통층"]) | set(g["사례층"])
    for name in tool_table:
        if name not in node:
            drift = "_타죄명:" + name in g.get("무관층", {})
            problem.append("도구 '%s' 에 맞는 노드가 그래프에 없다%s"
                        % (name, " (목표와 안 이어져 무관층으로 밀렸다)" if drift else ""))

    for evidence in g["증거"]:
        action, via, missing = find_action(g, evidence, tool_table)
        if not action and not missing:
            problem.append("'%s' 가 증명하는 것이 없다" % evidence)
        elif not action:
            notice.append("'%s' → %s : 도구 없음 (실행 요청이 오면 그 사실을 보고한다)"
                        % (evidence, ", ".join(missing)))
        elif missing:
            notice.append("'%s' 의 계획 일부에 도구가 없다: %s" % (evidence, ", ".join(missing)))

    if show:
        print("점검 %s: %s" % (kg_path, "통과" if not problem else "%d건 실패" % len(problem)))
        for x in problem:
            print("   - " + x)
        for x in notice:
            print("   · " + x)
    return 1 if problem else 0


# ── 자체검사 ────────────────────────────────────────────────────────────
def _selfcheck(kg="graphs/graph_범용작업.kg"):
    """진짜 그래프 + 가짜 도구로 다섯 갈래를 다 밟는다.

    도구를 가짜로 두는 이유는 실패를 마음대로 일으키기 위해서다. 그래프와
    루프는 진짜다 — 검사가 통과한다는 것은 계획과 복구가 .kg 에서 나온다는 뜻이다."""
    problem = []
    g = load(kg)

    def tools(to_expand=None, remove=(), once=True):
        """터질것: {노드: 예외}. 한번만=True 면 첫 시도에만 터진다."""
        to_expand, remaining = to_expand or {}, dict(to_expand or {})

        def make(name):
            def f(context):
                if name in remaining:
                    e = remaining.pop(name) if once else to_expand[name]
                    raise e
                return "ok"
            return f
        table = {n: make(n) for n in g["공통층"] if n.startswith("행동_")}
        for n in remove:
            table.pop(n, None)
        return table

    phrase = "데이터 변환 파이프라인 실행해줘"

    # 1. 다 성공하면 완료다
    r = run(g, phrase, tools(), write=False)
    if not r["완료"]:
        problem.append("정상 경로가 완료가 아니다: %s" % r["왜"])
    if r["계획"] != ["행동_파일읽기", "행동_데이터정제", "행동_데이터저장"]:
        problem.append("계획이 .kg 의 증명 차례와 다르다: %s" % r["계획"])

    # 2. 아는 에러는 그래프가 복구를 찾아 준다
    r = run(g, phrase, tools({"행동_파일읽기": FileNotFoundError(
        "[Errno 2] No such file or directory: 'x.txt'")}), write=False)
    if not r["완료"]:
        problem.append("파일없음 복구가 완료로 안 끝났다: %s" % r["왜"])
    if not any("복구" in c and "행동_더미파일생성" in c["복구"] for c in r["자취"]):
        problem.append("복구 행동을 그래프에서 못 찾았다")

    r = run(g, phrase, tools({"행동_데이터정제": ValueError(
        "could not convert string to float: '알수없음'")}), write=False)
    if not r["완료"] or not any("행동_결측치복구" in c.get("복구", []) for c in r["자취"]):
        problem.append("데이터오류 복구 경로가 안 잡힌다: %s" % r["왜"])

    # 3. 모르는 에러는 멈춘다. 그리고 완료라고 말하지 않는다 — 옛 버그가 여기였다
    r = run(g, phrase, tools({"행동_파일읽기": PermissionError(
        "Operation not permitted: /etc/passwd")}), write=False)
    if r["완료"]:
        problem.append("모르는 에러인데 완료라고 했다")
    if "그래프에 없다" not in (r["왜"] or ""):
        problem.append("모르는 에러의 사유가 엉뚱하다: %s" % r["왜"])

    # 4. 복구해도 계속 터지면 상한에서 끊는다
    r = run(g, phrase, tools({"행동_파일읽기": FileNotFoundError("No such file or directory")},
                          once=False), cap=3, write=False)
    if r["완료"] or "상한" not in (r["왜"] or ""):
        problem.append("재시도 상한이 안 걸린다: %s" % r["왜"])

    # 5. 도구가 없으면 조용히 건너뛰지 않는다
    r = run(g, phrase, tools(remove=["행동_데이터저장"]), write=False)
    if r["완료"]:
        problem.append("도구 없는 계획인데 완료라고 했다")
    if "행동_데이터저장" not in r["도구없음"]:
        problem.append("도구 없는 노드를 결과에 안 실었다: %s" % r["도구없음"])

    # 6. 그래프에 없는 요청은 미지다
    r = run(g, "오늘 서울 날씨 알려줘", tools(), write=False)
    if r["완료"] or r["증거"]:
        problem.append("무관한 요청이 계획으로 잡혔다: %s" % r["증거"])

    print("act 자체검사: %s" % ("통과" if not problem else "%d건 실패" % len(problem)))
    for x in problem:
        print("   - " + x)
    return 1 if problem else 0


if __name__ == "__main__":
    sys.exit(_selfcheck(sys.argv[1] if len(sys.argv) > 1 else "graphs/graph_범용작업.kg"))
