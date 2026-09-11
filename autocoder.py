# -*- coding: utf-8 -*-
"""코드 조립 · 실행 · 자율 디버깅 — 계획과 복구는 graphs/graph_개발_디버깅.kg 에서 온다.

이 파일에는 **도구와 템플릿만** 있다. 어떤 요청이 어떤 기획이 되는지, 어떤 에러에
어떤 수정을 거는지는 한 줄도 여기 없다. 그건 .kg 에 있고 act.py 가 읽어 온다.

템플릿에 대해 — 이건 LLM 처럼 코드를 창작하는 게 아니라 템플릿 보관소다.
그리고 보관소의 템플릿에는 **묵은 버그가 들어 있을 수 있다.** 그게 이 루프가
다루려는 상황이므로, 아래 템플릿 중 둘은 일부러 그 상태로 둔 시험용 고정물이다.
`--흠 없음` 을 주면 성한 템플릿이 나가고 루프는 수리 없이 한 번에 끝난다 —
루프가 '항상 고치는 시늉'을 하는 게 아니라는 것을 그걸로 확인할 수 있다.

수정 도구는 정답 파일을 통째로 갈아끼우지 않는다. 조립된 파일을 실제로 고치고
무엇을 고쳤는지 돌려준다. (예전 판은 FIXES 딕셔너리에 완성된 정답이 들어 있어서,
'디버깅'이 파일 교체였다.)

사용법
  python autocoder.py                        # 계산기 · 타입 흠이 있는 템플릿
  python autocoder.py --흠 이름              # NameError 경로
  python autocoder.py --흠 없음              # 성한 템플릿, 수리 없이 완료
  python autocoder.py --요청 "웹 서버 만들어줘"   # 도구 없음을 정직하게 보고
  python autocoder.py --check
"""
import re
import subprocess
import sys

import act

graph = "graphs/graph_개발_디버깅.kg"


# ── 템플릿 보관소 ───────────────────────────────────────────────────────
template = {
    # 인자를 정수로 바꾸지 않는다 → TypeError
    "타입": 'import sys\n'
            'result = sys.argv[1] + 10\n'
            'print("결과: " + result)\n',
    # sys 를 임포트하지 않는다 → NameError
    "이름": 'result = int(sys.argv[1]) + 10\n'
            'print("결과: " + str(result))\n',
    "없음": 'import sys\n'
            'result = int(sys.argv[1]) + 10\n'
            'print("결과: " + str(result))\n',
}


# ── 도구 ────────────────────────────────────────────────────────────────
def calc(context):
    """한 번만 조립하고, 그 다음부터는 실행만 한다.

    재시도마다 다시 조립하면 방금 건 수정을 스스로 지운다. 실제로 그렇게
    짰다가 무한히 같은 에러를 봤다."""
    target = context["대상"]
    did = "재실행"
    if not context.get("조립됨"):
        with open(target, "w", encoding="utf-8") as f:
            f.write(template[context.get("흠", "타입")])
        context["조립됨"] = True
        did = "조립"
    p = subprocess.run([sys.executable, target, str(context.get("인자", 5))],
                       capture_output=True, text=True)
    if p.returncode != 0:
        # 마지막 줄이 주된 에러다. 이 문자열이 그대로 그래프로 간다.
        raise RuntimeError(p.stderr.strip().splitlines()[-1] if p.stderr.strip()
                           else "종료코드 %d" % p.returncode)
    return "%s 후 실행 성공 · %s" % (did, p.stdout.strip())


def cast(context):
    """조립된 파일에 실제 수정을 건다. 정답 파일로 갈아끼우지 않는다."""
    target = context["대상"]
    txt = open(target, encoding="utf-8").read()
    fixed = []
    new_text, n = re.subn(r"(?<!int\()sys\.argv\[(\d+)\]", r"int(sys.argv[\1])", txt)
    if n:
        fixed.append("sys.argv[...] %d곳을 int() 로 감쌌다" % n)
    new_text, n = re.subn(r'(\+\s*)(?!str\()([A-Za-z_]\w*)(\s*\))', r"\1str(\2)\3", new_text)
    if n:
        fixed.append("문자열 결합 %d곳을 str() 로 감쌌다" % n)
    if not fixed:
        raise RuntimeError("타입 캐스팅을 걸 자리를 찾지 못했다")
    with open(target, "w", encoding="utf-8") as f:
        f.write(new_text)
    return " · ".join(fixed)


_name = re.compile(r"name '([^']+)' is not defined|No module named '([^']+)'")


def import_module(context):
    """에러 원문에서 빠진 이름을 뽑아 맨 위에 import 를 넣는다.

    맥락['에러'] 는 act.py 가 복구 도구를 부르기 직전에 채워 준다."""
    m = _name.search(context.get("에러", ""))
    if not m:
        raise RuntimeError("에러 문장에서 빠진 이름을 못 찾았다: %r" % context.get("에러"))
    name = m.group(1) or m.group(2)
    target = context["대상"]
    txt = open(target, encoding="utf-8").read()
    line = "import %s" % name
    if line in txt:
        raise RuntimeError("'%s' 는 이미 임포트되어 있다. 다른 원인이다" % name)
    with open(target, "w", encoding="utf-8") as f:
        f.write(line + "\n" + txt)
    return "맨 위에 '%s' 를 넣었다" % line


# 기획_웹서버 는 일부러 비워 둔다. 그래프에는 있고 도구는 없는 상태가
# 어떻게 보고되는지가 이 루프의 정직함이다 — 예전 판은 여기서 템플릿이
# None 인 채로 f.write(None) 을 해서 TypeError 로 죽었다.
tool_table = {
    "기획_계산기": calc,
    "수정_타입캐스팅": cast,
    "수정_모듈임포트": import_module,
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

    context = {"대상": value("--대상", "generated_app.py"),
            "흠": value("--흠", "타입"), "인자": value("--인자", "5")}
    if context["흠"] not in template:
        return print("--흠 은 %s 중 하나다" % " / ".join(template))
    phrase = value("--요청", "터미널에서 숫자 더하는 계산기 만들어줘")

    g = act.load(graph)
    result = act.run(g, phrase, tool_table, context)
    act.report(result, g)
    print("[자취] %s" % act.trace_path(g))
    return 0 if result["완료"] else 1


if __name__ == "__main__":
    sys.exit(_main() or 0)
