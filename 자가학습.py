# -*- coding: utf-8 -*-
"""틀린 답에서 무엇을 모르는지 뽑아, 웹에서 받아, 다시 짓고, 나아졌는지 잰다.

    python 자가학습.py --모름                # 무엇을 모르나 (틀린 물음에서만)
    python 자가학습.py --배우다 --최대 8      # 위키에서 받아 data/웹 에 넣는다
    python 자가학습.py --짓다                # docs/ko + data/웹 으로 다시 짓는다
    python 자가학습.py --재본다              # 물음기록을 다시 풀어 전/후를 비교
    python 자가학습.py --한바퀴 --최대 8      # 위 넷을 순서대로
    python 자가학습.py --한바퀴 --넓히기      # 거절했던 주제까지 배운다
    python 자가학습.py --한바퀴 --밀어붙이기   # 나빠져도 안 물린다 (사람이 볼 때만)

왜 틀린 답만 보는가. 맞힌 물음에는 배울 것이 없다. 지식은 제 지식에서 오류를
찾는 순간 자란다 — 그러니 회로의 구동력은 정답이 아니라 오답이어야 한다.

검색 결과를 답으로 쓰지 않는다. `collectors/위키.py` 머리말의 규칙 그대로,
받은 글은 `data/웹/` 에 출처 URL 과 받은 날을 달고 놓이고, 거기서 그래프가
된다. 그래서 나중에 그 지식으로 답할 때 어디서 배웠는지가 발췌의 `곳` 으로
따라 나온다. 자동으로 도는 회로여도 영수증은 그대로다.

퇴화도 같이 센다. 아는 것이 늘면 헷갈리는 것도 는다. 나아진 것만 세면
회로가 스스로를 속인다.
"""
import io
import json
import os
import subprocess
import sys

여기 = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, 여기)
os.environ.setdefault("KG_ENCODER", "문자")

기록터 = os.path.join(여기, "물음기록.jsonl")
그래프터 = os.path.join(여기, "문서그래프.json")
코퍼스 = [os.path.join(여기, "docs/ko"), os.path.join(여기, "data/웹")]


def 물음들():
    if not os.path.exists(기록터):
        return []
    출 = []
    for 줄 in io.open(기록터, encoding="utf-8"):
        줄 = 줄.strip()
        if not 줄:
            continue
        try:
            출.append(json.loads(줄))
        except ValueError:
            continue
    return 출


def 틀린것(줄들, 넓히기=False):
    """**답했어야 하는데 못한 것**만. 이것이 이 회로의 연료다.

    거절이 정답인 물음은 오류가 아니다. 처음에는 `표=="틀림"` 을 전부 연료로
    썼더니 회로가 `asdf`·`가나다라마바사`·`감기`·`강아지` 를 배우겠다고 했다.
    잡음과 '코퍼스 밖이라 미지가 맞는' 물음까지 오답으로 센 것이다.

    무엇을 연료로 삼느냐가 곧 이 AI 가 무엇이 되느냐다. 틀린 것을 다 배우면
    아무거나 아는 것이 되지 이 일을 잘하게 되지는 않는다. 그래서 연료는
    '기대 미지' 가 아닌 물음 중 못 맞힌 것으로 한정한다. 코퍼스 밖 물음이
    새어 답한 것(누출)은 여기서 못 고친다 — 그건 더 배워서 될 일이 아니라
    문턱과 관문의 일이다.

    `넓히기` 는 다른 결정이다. 코퍼스 밖이라 거절한 물음까지 연료로 삼는다 —
    오류를 고치는 것이 아니라 **아는 범위를 넓히는** 쪽이다. 문서 안내자로
    남을 것인지 자라는 지식체가 될 것인지의 선택이라 기본값으로 두지 않는다.
    사람이 `--넓히기` 라고 말해야 켜진다."""
    출 = []
    for d in 줄들:
        if d.get("갈래") == "잡음":
            continue                      # `asdf` 는 배울 것이 아니라 거를 것이다
        if d.get("기대") == "미지" and not 넓히기:
            continue                      # 거절이 정답이다. 배울 것이 없다
        if d.get("표") == "틀림" or d.get("판정") == "미지":
            출.append(d)
    return 출


def 모르는것(줄들=None, 넓히기=False):
    """틀린 물음에서 그래프가 모르는 말을 셈해 돌려준다.

    -> [(말, 횟수, 그 말이 나온 물음 하나)]. 물음을 들고 다니는 이유는
    검색어로 쓰기 위해서다. 낱말 하나로 찾으면 `정리` 가 수학의 정리를
    물어 온다 — 사람은 그렇게 안 찾는다. 물음째로 넣으면 문맥이 가른다."""
    import build
    import explain
    g = explain.열기(explain._길(그래프터))
    앎 = set(g.get("어휘") or ())
    셈, 나온곳 = {}, {}
    for d in 틀린것(줄들 if 줄들 is not None else 물음들(), 넓히기):
        for w in build.개념뽑기(d["질문"]):
            if w not in 앎 and len(w) >= 2:
                셈[w] = 셈.get(w, 0) + 1
                나온곳.setdefault(w, d["질문"])
    return [(w, c, 나온곳[w])
            for w, c in sorted(셈.items(), key=lambda kv: (-kv[1], kv[0]))]


_한글 = lambda c: "가" <= c <= "힣"


def _제목이부르나(말, 제목):
    """제목이 그 말을 **낱말로** 부르는가. 글자가 끼어 있는 것과는 다르다.

    처음에는 `말 in 제목` 이었다. 그래서 `is` 를 배우려다 「Fromis 9」 를
    받아 왔다. 코퍼스에 아이돌 그룹 문서가 들어갔고 그 한 번으로 채점이
    121 -> 113 으로 떨어졌다. 한 글자 통과가 그만큼 비싸다."""
    영문 = 말[:1].isascii()

    def 붙었나(c):
        if not c:
            return False
        return (c.isascii() and c.isalnum()) if 영문 else _한글(c)

    i = 제목.find(말)
    while i >= 0:
        앞 = 제목[i - 1] if i else ""
        뒤 = 제목[i + len(말):i + len(말) + 1]
        if not 붙었나(앞) and not 붙었나(뒤):
            return True
        i = 제목.find(말, i + 1)
    return False


def 이미받은():
    터 = os.path.join(여기, "data/웹")
    if not os.path.isdir(터):
        return set()
    return {f[len("위키_"):-len(".txt")].replace("_", " ")
            for f in os.listdir(터) if f.startswith("위키_") and f.endswith(".txt")}


def 배우다(말들, 최대=8):
    """모르는 말을 검색어로 써서 글을 받아 온다. 사람이 주제를 안 정한다."""
    sys.path.insert(0, os.path.join(여기, "collectors"))
    import importlib
    위키 = importlib.import_module("위키")
    본것 = 이미받은()
    받음 = []
    for 말, _횟수, 물음 in 말들[:최대]:
        try:
            후보 = 위키.찾기(물음, 수=8) + 위키.찾기(말, 수=5)
        except Exception as e:                 # 망이 끊겨도 회로는 멈추지 않는다
            print("  ! %s 검색 실패: %s" % (말, e))
            continue
        # 제목이 그 말을 실제로 부르는 것만 받는다. 이 문이 없으면 '부탁' 이
        # 엉뚱한 인물 문서를 물어 온다. 못 찾으면 안 배우는 편이 낫다 —
        # 아무거나 주워 오면 코퍼스가 더러워지고 그건 되돌리기 어렵다.
        맞 = [x for x in 후보 if _제목이부르나(말, x["제목"])]
        if not 맞:
            print("  - %s: 제목이 그 말을 부르는 문서가 없다 (안 배운다)" % 말)
            continue
        제목 = 맞[0]["제목"]
        if 제목 in 본것:
            print("  = %s -> 「%s」 이미 있음" % (말, 제목))
            continue
        본문 = 위키.받기(제목)
        if not 본문 or len(본문) < 200:
            print("  - %s -> 「%s」 본문이 너무 짧다" % (말, 제목))
            continue
        경로 = 위키.저장(제목, 본문)
        본것.add(제목)
        받음.append((말, 제목, len(본문), 경로))
        print("  + %s -> 「%s」 %d자" % (말, 제목, len(본문)))
    return 받음


격리터 = os.path.join(여기, "data/웹_되돌림")


def 되돌리기(받음):
    """받아온 글을 코퍼스에서 빼고 격리한다. 지우지는 않는다 —
    무엇을 왜 물렸는지가 남아야 다음에 같은 것을 안 문다."""
    os.makedirs(격리터, exist_ok=True)
    옮김 = []
    for _말, 제목, _n, 경로 in 받음:
        if os.path.exists(경로):
            새 = os.path.join(격리터, os.path.basename(경로))
            os.replace(경로, 새)
            옮김.append((제목, 새))
    return 옮김


def 짓다():
    폴더 = [d for d in 코퍼스 if os.path.isdir(d)]
    명령 = [sys.executable, os.path.join(여기, "build.py")] + 폴더 + ["--out", 그래프터]
    r = subprocess.run(명령, capture_output=True, text=True, cwd=여기)
    for 줄 in (r.stdout or "").splitlines():
        if 줄.strip() and "Quantization" not in 줄:
            print("  " + 줄)
    if r.returncode:
        print(r.stderr[-500:])
    return r.returncode == 0


def 풀어보기(그래프=None):
    """물음기록 전체를 지금 그래프로 다시 푼다. -> {질문: (판정, 주제)}"""
    import explain
    g = explain.열기(explain._길(그래프 or 그래프터))
    출 = {}
    for d in 물음들():
        뜻, _답, 주제 = explain.물어보기(g, d["질문"])
        출[d["질문"]] = (뜻, 주제)
    return 출


def 채점(줄들, 답들):
    맞 = 채 = 0
    for d in 줄들:
        q = d["질문"]
        if q not in 답들:
            continue
        뜻, 주제 = 답들[q]
        if d.get("기대"):
            ok = 뜻 == d["기대"]
        elif d.get("기대주제"):
            ok = 주제 in d["기대주제"]
        else:
            continue
        맞 += ok
        채 += 1
    return 맞, 채


def 견주기(전, 후):
    """나아진 것과 나빠진 것을 둘 다 센다."""
    줄들 = 물음들()
    나아짐, 나빠짐, 낡은라벨 = [], [], []
    for d in 줄들:
        q = d["질문"]
        if q not in 전 or q not in 후:
            continue
        def ok(답):
            뜻, 주제 = 답
            if d.get("기대"):
                return 뜻 == d["기대"]
            if d.get("기대주제"):
                return 주제 in d["기대주제"]
            return None
        a, b = ok(전[q]), ok(후[q])
        if a is None:
            continue
        if not a and b:
            나아짐.append((q, 후[q]))
        elif a and not b:
            나빠짐.append((q, 전[q], 후[q]))
            # 코퍼스 밖이라 미지를 기대했는데 이제 답한다면, 틀린 것이
            # 아니라 **라벨이 낡은 것**일 수 있다. 배웠으니까.
            if d.get("기대") == "미지" and 후[q][0] == "설명":
                낡은라벨.append((q, 후[q][1]))
    return 나아짐, 나빠짐, 낡은라벨


def _자가검사():
    줄 = [{"질문": "가", "표": "틀림", "판정": "설명"},
          {"질문": "나", "표": "맞음", "판정": "설명"},
          {"질문": "다", "판정": "미지"},
          {"질문": "라", "기대": "미지", "표": "틀림", "판정": "설명"}]
    t = [d["질문"] for d in 틀린것(줄)]
    assert t == ["가", "다"], t          # 맞힌 것도, 거절이 정답인 것도 연료가 아니다
    assert [d["질문"] for d in 틀린것(줄, 넓히기=True)] == ["가", "다", "라"]
    assert _제목이부르나("정리", "정리 (수학)")
    assert not _제목이부르나("is", "Fromis 9")      # 이것 때문에 채점이 무너졌다
    assert _제목이부르나("PostgreSQL", "PostgreSQL")
    assert not _제목이부르나("노드", "노드르담")
    assert 채점(줄, {}) == (0, 0)        # 안 푼 것은 안 센다
    가짜 = [{"질문": "가", "기대": "미지"}]
    import types
    전, 후 = {"가": ("미지", None)}, {"가": ("설명", "노드")}
    global 물음들
    원 = 물음들
    물음들 = lambda: 가짜
    try:
        나, 빠, 낡 = 견주기(전, 후)
        assert 빠 and 낡, (빠, 낡)       # 배워서 답하게 된 것은 라벨이 낡은 것
    finally:
        물음들 = 원
    print("자가학습 selfcheck ok")


if __name__ == "__main__":
    최대 = int(sys.argv[sys.argv.index("--최대") + 1]) if "--최대" in sys.argv else 8
    넓히기 = "--넓히기" in sys.argv

    if "--check" in sys.argv:
        _자가검사()
        sys.exit(0)

    if "--모름" in sys.argv or "--한바퀴" in sys.argv:
        줄들 = 물음들()
        틀 = 틀린것(줄들, 넓히기)
        말 = 모르는것(줄들, 넓히기)
        print("물음 %d개 중 %s %d개" % (len(줄들),
              "넓힐 거리" if 넓히기 else "고칠 거리", len(틀)))
        print("거기서 그래프가 모르는 말 %d종:" % len(말))
        for w, c, q in 말[:20]:
            print("   %-12s %d번   (%s)" % (w, c, q[:40]))
        if "--한바퀴" not in sys.argv:
            sys.exit(0)

    전 = 받음 = None
    if "--한바퀴" in sys.argv:
        # 기준을 먼저 잡는다. 받고 나서 지으면 무엇과 견주는지가 흐려진다.
        print("\n기준을 잡는다 (받기 전 코퍼스로):")
        짓다()
        전 = 풀어보기()
        print("  기준 %d/%d" % 채점(물음들(), 전))

    if "--배우다" in sys.argv or "--한바퀴" in sys.argv:
        말 = 모르는것(넓히기=넓히기)
        print("\n웹에서 받는다 (최대 %d개):" % 최대)
        받음 = 배우다(말, 최대)
        print("받은 문서 %d개" % len(받음))
        if "--한바퀴" not in sys.argv:
            sys.exit(0)

    if "--짓다" in sys.argv or "--한바퀴" in sys.argv:
        print("\n다시 짓는다:")
        if not 짓다():
            sys.exit(1)
        if "--한바퀴" not in sys.argv:
            sys.exit(0)
        후 = 풀어보기()
        줄들 = 물음들()
        ㄱ, ㄴ = 채점(줄들, 전), 채점(줄들, 후)
        print("\n채점  전 %d/%d -> 후 %d/%d" % (ㄱ[0], ㄱ[1], ㄴ[0], ㄴ[1]))
        # 나빠졌으면 물린다. 이 한 줄이 회로를 안전하게 만든다 — 웹은 옳은
        # 것만 주지 않으므로, 받아들이는 쪽에 되돌리는 힘이 있어야 한다.
        # 사람의 승인을 기다리는 대신 **재서** 정한다.
        if 받음 and ㄴ[0] < ㄱ[0] and "--밀어붙이기" not in sys.argv:
            print("\n나빠졌다. 이번에 받은 %d개를 물린다." % len(받음))
            for 제목, 새 in 되돌리기(받음):
                print("   되돌림: 「%s」 -> %s" % (제목, os.path.relpath(새, 여기)))
            짓다()
            다시 = 채점(물음들(), 풀어보기())
            print("되돌린 뒤 %d/%d" % 다시)
            if 다시[0] < ㄱ[0]:
                print("!! 되돌렸는데도 처음보다 낮다. 사람이 봐야 한다.")
            sys.exit(0)
        나, 빠, 낡 = 견주기(전, 후)
        print("나아진 물음 %d개 · 나빠진 물음 %d개" % (len(나), len(빠)))
        for q, (뜻, 주제) in 나[:10]:
            print("   + %-34s -> %s/%s" % (q[:34], 뜻, 주제))
        for q, ㄱ2, ㄴ2 in 빠[:10]:
            print("   - %-34s %s/%s -> %s/%s" % (q[:34], ㄱ2[0], ㄱ2[1], ㄴ2[0], ㄴ2[1]))
        if 낡:
            print("\n라벨이 낡았을 수 있는 것 %d개 — 배웠으니 이제 코퍼스 밖이 아니다:" % len(낡))
            for q, 주제 in 낡:
                print("   ? %-34s -> %s" % (q[:34], 주제))
        sys.exit(0)

    if "--재본다" in sys.argv:
        답 = 풀어보기()
        맞, 채 = 채점(물음들(), 답)
        print("지금 그래프로 %d/%d (%.0f%%)" % (맞, 채, 100 * 맞 / max(채, 1)))
        sys.exit(0)

    print(__doc__)
