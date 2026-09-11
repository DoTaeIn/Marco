# -*- coding: utf-8 -*-
"""틀린 답에서 무엇을 모르는지 뽑아, 웹에서 받아, 다시 짓고, 나아졌는지 잰다.

    python self_learning.py --모름                # 무엇을 모르나 (틀린 물음에서만)
    python self_learning.py --배우다 --최대 8      # 위키에서 받아 data/웹 에 넣는다
    python self_learning.py --짓다                # docs/ko + data/웹 으로 다시 짓는다
    python self_learning.py --재본다              # 물음기록을 다시 풀어 전/후를 비교
    python self_learning.py --한바퀴 --최대 8      # 위 넷을 순서대로
    python self_learning.py --한바퀴 --넓히기      # 거절했던 주제까지 배운다
    python self_learning.py --한바퀴 --밀어붙이기   # 나빠져도 안 물린다 (사람이 볼 때만)

왜 틀린 답만 보는가. 맞힌 물음에는 배울 것이 없다. 지식은 제 지식에서 오류를
찾는 순간 자란다 — 그러니 회로의 구동력은 정답이 아니라 오답이어야 한다.

검색 결과를 답으로 쓰지 않는다. `collectors/wiki.py` 머리말의 규칙 그대로,
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

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
os.environ.setdefault("KG_ENCODER", "문자")

log_dir = os.path.join(here, "물음기록.jsonl")
graph_dir = os.path.join(here, "문서그래프.json")
corpus = [os.path.join(here, "docs/ko"), os.path.join(here, "data/웹")]


def prompts():
    if not os.path.exists(log_dir):
        return []
    out = []
    for line in io.open(log_dir, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def wrong_ones(lines, widen=False):
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
    out = []
    for d in lines:
        if d.get("갈래") == "잡음":
            continue                      # `asdf` 는 배울 것이 아니라 거를 것이다
        if d.get("기대") == "미지" and not widen:
            continue                      # 거절이 정답이다. 배울 것이 없다
        if d.get("표") == "틀림" or d.get("판정") == "미지":
            out.append(d)
    return out


def unknown_ones(lines=None, widen=False):
    """틀린 물음에서 그래프가 모르는 말을 셈해 돌려준다.

    -> [(말, 횟수, 그 말이 나온 물음 하나)]. 물음을 들고 다니는 이유는
    검색어로 쓰기 위해서다. 낱말 하나로 찾으면 `정리` 가 수학의 정리를
    물어 온다 — 사람은 그렇게 안 찾는다. 물음째로 넣으면 문맥이 가른다."""
    import build
    import explain
    g = explain.open_(explain._abs(graph_dir))
    known = set(g.get("어휘") or ())
    acc, seen_place = {}, {}
    for d in wrong_ones(lines if lines is not None else prompts(), widen):
        for w in build.extract_concepts(d["질문"]):
            if w not in known and len(w) >= 2:
                acc[w] = acc.get(w, 0) + 1
                seen_place.setdefault(w, d["질문"])
    return [(w, c, seen_place[w])
            for w, c in sorted(acc.items(), key=lambda kv: (-kv[1], kv[0]))]


_HANGUL_RE = lambda c: "가" <= c <= "힣"


def _title_calls(phrase, title):
    """제목이 그 말을 **낱말로** 부르는가. 글자가 끼어 있는 것과는 다르다.

    처음에는 `말 in 제목` 이었다. 그래서 `is` 를 배우려다 「Fromis 9」 를
    받아 왔다. 코퍼스에 아이돌 그룹 문서가 들어갔고 그 한 번으로 채점이
    121 -> 113 으로 떨어졌다. 한 글자 통과가 그만큼 비싸다."""
    en_stmt = phrase[:1].isascii()

    def attached(c):
        if not c:
            return False
        return (c.isascii() and c.isalnum()) if en_stmt else _HANGUL_RE(c)

    i = title.find(phrase)
    while i >= 0:
        front = title[i - 1] if i else ""
        rear = title[i + len(phrase):i + len(phrase) + 1]
        if not attached(front) and not attached(rear):
            return True
        i = title.find(phrase, i + 1)
    return False


def already_got():
    workdir = os.path.join(here, "data/웹")
    if not os.path.isdir(workdir):
        return set()
    return {f[len("위키_"):-len(".txt")].replace("_", " ")
            for f in os.listdir(workdir) if f.startswith("위키_") and f.endswith(".txt")}


def learn(phrases, max_n=8):
    """모르는 말을 검색어로 써서 글을 받아 온다. 사람이 주제를 안 정한다."""
    sys.path.insert(0, os.path.join(here, "collectors"))
    import importlib
    wiki = importlib.import_module("위키")
    seen = already_got()
    received = []
    for phrase, _count, prompt in phrases[:max_n]:
        try:
            cand = wiki.find(prompt, num=8) + wiki.find(phrase, num=5)
        except Exception as e:                 # 망이 끊겨도 회로는 멈추지 않는다
            print("  ! %s 검색 실패: %s" % (phrase, e))
            continue
        # 제목이 그 말을 실제로 부르는 것만 받는다. 이 문이 없으면 '부탁' 이
        # 엉뚱한 인물 문서를 물어 온다. 못 찾으면 안 배우는 편이 낫다 —
        # 아무거나 주워 오면 코퍼스가 더러워지고 그건 되돌리기 어렵다.
        hit = [x for x in cand if _title_calls(phrase, x["제목"])]
        if not hit:
            print("  - %s: 제목이 그 말을 부르는 문서가 없다 (안 배운다)" % phrase)
            continue
        title = hit[0]["제목"]
        if title in seen:
            print("  = %s -> 「%s」 이미 있음" % (phrase, title))
            continue
        body = wiki.receive(title)
        if not body or len(body) < 200:
            print("  - %s -> 「%s」 본문이 너무 짧다" % (phrase, title))
            continue
        path = wiki.save(title, body)
        seen.add(title)
        received.append((phrase, title, len(body), path))
        print("  + %s -> 「%s」 %d자" % (phrase, title, len(body)))
    return received


isolated_dir = os.path.join(here, "data/웹_되돌림")


def revert(received):
    """받아온 글을 코퍼스에서 빼고 격리한다. 지우지는 않는다 —
    무엇을 왜 물렸는지가 남아야 다음에 같은 것을 안 문다."""
    os.makedirs(isolated_dir, exist_ok=True)
    moved = []
    for _phrase_part, title, _n, path in received:
        if os.path.exists(path):
            new = os.path.join(isolated_dir, os.path.basename(path))
            os.replace(path, new)
            moved.append((title, new))
    return moved


def author():
    folder = [d for d in corpus if os.path.isdir(d)]
    cmd = [sys.executable, os.path.join(here, "build.py")] + folder + ["--out", graph_dir]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=here)
    for line in (r.stdout or "").splitlines():
        if line.strip() and "Quantization" not in line:
            print("  " + line)
    if r.returncode:
        print(r.stderr[-500:])
    return r.returncode == 0


def solve(graph=None):
    """물음기록 전체를 지금 그래프로 다시 푼다. -> {질문: (판정, 주제)}"""
    import explain
    g = explain.open_(explain._abs(graph or graph_dir))
    out = {}
    for d in prompts():
        meaning, _ans, topic = explain.ask(g, d["질문"])
        out[d["질문"]] = (meaning, topic)
    return out


def grade(lines, answers):
    hit = filled_cnt = 0
    for d in lines:
        q = d["질문"]
        if q not in answers:
            continue
        meaning, topic = answers[q]
        if d.get("기대"):
            ok = meaning == d["기대"]
        elif d.get("기대주제"):
            ok = topic in d["기대주제"]
        else:
            continue
        hit += ok
        filled_cnt += 1
    return hit, filled_cnt


def compare(before, after):
    """나아진 것과 나빠진 것을 둘 다 센다."""
    lines = prompts()
    better, worse, stale_label = [], [], []
    for d in lines:
        q = d["질문"]
        if q not in before or q not in after:
            continue
        def ok(ans):
            meaning, topic = ans
            if d.get("기대"):
                return meaning == d["기대"]
            if d.get("기대주제"):
                return topic in d["기대주제"]
            return None
        a, b = ok(before[q]), ok(after[q])
        if a is None:
            continue
        if not a and b:
            better.append((q, after[q]))
        elif a and not b:
            worse.append((q, before[q], after[q]))
            # 코퍼스 밖이라 미지를 기대했는데 이제 답한다면, 틀린 것이
            # 아니라 **라벨이 낡은 것**일 수 있다. 배웠으니까.
            if d.get("기대") == "미지" and after[q][0] == "설명":
                stale_label.append((q, after[q][1]))
    return better, worse, stale_label


def _selfcheck():
    line = [{"질문": "가", "표": "틀림", "판정": "설명"},
          {"질문": "나", "표": "맞음", "판정": "설명"},
          {"질문": "다", "판정": "미지"},
          {"질문": "라", "기대": "미지", "표": "틀림", "판정": "설명"}]
    t = [d["질문"] for d in wrong_ones(line)]
    assert t == ["가", "다"], t          # 맞힌 것도, 거절이 정답인 것도 연료가 아니다
    assert [d["질문"] for d in wrong_ones(line, widen=True)] == ["가", "다", "라"]
    assert _title_calls("정리", "정리 (수학)")
    assert not _title_calls("is", "Fromis 9")      # 이것 때문에 채점이 무너졌다
    assert _title_calls("PostgreSQL", "PostgreSQL")
    assert not _title_calls("노드", "노드르담")
    assert grade(line, {}) == (0, 0)        # 안 푼 것은 안 센다
    fake = [{"질문": "가", "기대": "미지"}]
    import types
    before, after = {"가": ("미지", None)}, {"가": ("설명", "노드")}
    global prompts
    orig = prompts
    prompts = lambda: fake
    try:
        img, fast, stale = compare(before, after)
        assert fast and stale, (fast, stale)       # 배워서 답하게 된 것은 라벨이 낡은 것
    finally:
        prompts = orig
    print("자가학습 selfcheck ok")


if __name__ == "__main__":
    max_n = int(sys.argv[sys.argv.index("--최대") + 1]) if "--최대" in sys.argv else 8
    widen = "--넓히기" in sys.argv

    if "--check" in sys.argv:
        _selfcheck()
        sys.exit(0)

    if "--모름" in sys.argv or "--한바퀴" in sys.argv:
        lines = prompts()
        template = wrong_ones(lines, widen)
        phrase = unknown_ones(lines, widen)
        print("물음 %d개 중 %s %d개" % (len(lines),
              "넓힐 거리" if widen else "고칠 거리", len(template)))
        print("거기서 그래프가 모르는 말 %d종:" % len(phrase))
        for w, c, q in phrase[:20]:
            print("   %-12s %d번   (%s)" % (w, c, q[:40]))
        if "--한바퀴" not in sys.argv:
            sys.exit(0)

    before = received = None
    if "--한바퀴" in sys.argv:
        # 기준을 먼저 잡는다. 받고 나서 지으면 무엇과 견주는지가 흐려진다.
        print("\n기준을 잡는다 (받기 전 코퍼스로):")
        author()
        before = solve()
        print("  기준 %d/%d" % grade(prompts(), before))

    if "--배우다" in sys.argv or "--한바퀴" in sys.argv:
        phrase = unknown_ones(widen=widen)
        print("\n웹에서 받는다 (최대 %d개):" % max_n)
        received = learn(phrase, max_n)
        print("받은 문서 %d개" % len(received))
        if "--한바퀴" not in sys.argv:
            sys.exit(0)

    if "--짓다" in sys.argv or "--한바퀴" in sys.argv:
        print("\n다시 짓는다:")
        if not author():
            sys.exit(1)
        if "--한바퀴" not in sys.argv:
            sys.exit(0)
        after = solve()
        lines = prompts()
        ㄱ, ㄴ = grade(lines, before), grade(lines, after)
        print("\n채점  전 %d/%d -> 후 %d/%d" % (ㄱ[0], ㄱ[1], ㄴ[0], ㄴ[1]))
        # 나빠졌으면 물린다. 이 한 줄이 회로를 안전하게 만든다 — 웹은 옳은
        # 것만 주지 않으므로, 받아들이는 쪽에 되돌리는 힘이 있어야 한다.
        # 사람의 승인을 기다리는 대신 **재서** 정한다.
        if received and ㄴ[0] < ㄱ[0] and "--밀어붙이기" not in sys.argv:
            print("\n나빠졌다. 이번에 받은 %d개를 물린다." % len(received))
            for title, new in revert(received):
                print("   되돌림: 「%s」 -> %s" % (title, os.path.relpath(new, here)))
            author()
            again = grade(prompts(), solve())
            print("되돌린 뒤 %d/%d" % again)
            if again[0] < ㄱ[0]:
                print("!! 되돌렸는데도 처음보다 낮다. 사람이 봐야 한다.")
            sys.exit(0)
        img, fast, stale = compare(before, after)
        print("나아진 물음 %d개 · 나빠진 물음 %d개" % (len(img), len(fast)))
        for q, (meaning, topic) in img[:10]:
            print("   + %-34s -> %s/%s" % (q[:34], meaning, topic))
        for q, ㄱ2, ㄴ2 in fast[:10]:
            print("   - %-34s %s/%s -> %s/%s" % (q[:34], ㄱ2[0], ㄱ2[1], ㄴ2[0], ㄴ2[1]))
        if stale:
            print("\n라벨이 낡았을 수 있는 것 %d개 — 배웠으니 이제 코퍼스 밖이 아니다:" % len(stale))
            for q, topic in stale:
                print("   ? %-34s -> %s" % (q[:34], topic))
        sys.exit(0)

    if "--재본다" in sys.argv:
        ans = solve()
        hit, filled_cnt = grade(prompts(), ans)
        print("지금 그래프로 %d/%d (%.0f%%)" % (hit, filled_cnt, 100 * hit / max(filled_cnt, 1)))
        sys.exit(0)

    print(__doc__)
