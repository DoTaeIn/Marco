# -*- coding: utf-8 -*-
"""데이터 파이프라인 에이전트 — 계획과 복구는 graphs/graph_범용작업.kg 에서 온다.

이 파일에는 **도구만** 있다. 무엇을 어떤 차례로 할지, 어떤 에러에 무엇으로
복구할지는 한 줄도 여기 없다. 그건 .kg 에 있고 act.py 가 읽어 온다.
그래서 새 에러 유형을 다루려면 이 파일이 아니라 그래프를 고친다.

도구는 에러를 일부러 만들지 않는다. 파일이 없으면 진짜 FileNotFoundError 가
나고, 숫자로 못 읽는 값이 있으면 진짜 ValueError 가 난다. 그걸 act.py 가
그래프에 던져 복구 행동을 찾는다.

사용법
  python universal_agent.py                                   # raw_data.txt → result.json
  python universal_agent.py --입력 자료.txt --출력 결과.json
  python universal_agent.py --요청 "데이터 처리해줘"
  python universal_agent.py --check
"""
import json
import sys

import act

graph = "graphs/graph_범용작업.kg"


# ── 도구 ────────────────────────────────────────────────────────────────
# 각 함수는 맥락(dict) 하나를 받고, 사람이 읽을 관찰 문자열을 돌려준다.
# 실패는 예외로 낸다. 삼키면 act.py 가 복구를 못 건다.

def read_file(context):
    path = context["입력"]
    with open(path, encoding="utf-8") as f:
        context["원문"] = f.read()
    return "%s 에서 %d자를 읽었다" % (path, len(context["원문"]))


def clean_data(context):
    table = []
    for line in context.get("원문", "").splitlines():
        line = line.strip()
        if not line:
            continue
        key, _, value = line.partition(":")
        table.append({key.strip(): float(value.strip())})       # 못 읽으면 ValueError
    context["표"] = table
    return "%d행을 수치로 바꿨다" % len(table)


def save_data(context):
    path = context["출력"]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(context.get("표", []), f, ensure_ascii=False, indent=2)
    return "%s 에 %d행을 썼다" % (path, len(context.get("표", [])))


def make_dummy_file(context):
    """원본이 없을 때 최소 입력을 만든다. 값을 지어내지 않는다는 표시로
    빈 표 하나만 둔다 — 여기서 그럴듯한 숫자를 넣으면 없는 데이터를 만든 것이 된다."""
    path = context["입력"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("price:0\n")
    return "%s 가 없어 최소 입력(price:0)을 만들었다" % path


def impute(context):
    """수치로 못 읽는 값만 0 으로 바꾸고, 무엇을 바꿨는지 돌려준다.

    조용히 고치면 복구가 곧 데이터 위조가 된다. 바꾼 자리를 반드시 보고한다."""
    fixed, new_line = [], []
    for line in context.get("원문", "").splitlines():
        key, phrase_min_, value = line.partition(":")
        if phrase_min_ and value.strip():
            try:
                float(value.strip())
            except ValueError:
                fixed.append("%s=%s" % (key.strip(), value.strip()))
                line = "%s:0" % key
        new_line.append(line)
    if not fixed:
        raise ValueError("수치로 못 읽는 값을 찾지 못했다. 다른 원인이다")
    context["원문"] = "\n".join(new_line)
    context.setdefault("고친값", []).extend(fixed)
    return "기본값 0 으로 치환: %s" % ", ".join(fixed)


tool_table = {
    "행동_파일읽기": read_file,
    "행동_데이터정제": clean_data,
    "행동_데이터저장": save_data,
    "행동_더미파일생성": make_dummy_file,
    "행동_결측치복구": impute,
}


# ── CLI ─────────────────────────────────────────────────────────────────
def _main():
    argv = sys.argv[1:]
    if "-h" in argv or "--help" in argv:
        return print(__doc__.strip())
    if "--check" in argv:
        return act.check(graph, tool_table)

    def value(name, default):
        return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else default

    context = {"입력": value("--입력", "raw_data.txt"), "출력": value("--출력", "result.json")}
    phrase = value("--요청", "데이터 변환 파이프라인 실행해줘")

    g = act.load(graph)
    result = act.run(g, phrase, tool_table, context)
    act.report(result, g)
    if context.get("고친값"):
        print("[주의] 원본에 없던 값을 0 으로 채웠다: %s" % ", ".join(context["고친값"]))
    print("[자취] %s" % act.trace_path(g))
    return 0 if result["완료"] else 1


if __name__ == "__main__":
    sys.exit(_main() or 0)
