# -*- coding: utf-8 -*-
"""남의 말을 빨아들이는 노드를 찾는다. 바꿔 말하기가 왜 지는지의 자리.

    python alias_diag.py                    # 전체 그래프
    python alias_diag.py graphs/graph_의료.kg
    python alias_diag.py --개수 30

지능 시험에서 바꿔 말하기가 42.9% 였다. 파 보니 고칠 데가 알고리즘이
아니었다. 다섯 가지를 재보고 다 접었다.

    되묻기 바닥(A_MIN)을 낮춘다     건진 것 0개 · 엉뚱한 되묻기 1 -> 8 · 밖 27 -> 26
    틀 n그램을 눌러본다(IDF)        5/14 -> 1/14 로 **더 나빠진다**
    사전 뜻을 별칭으로 붙인다        등수 44 -> 19, 45 -> 15. 1등엔 못 간다
    말뭉치에서 같이 나오는 것을 센다   재료가 없다(트로포닌 0문서 · 목격자 6문서)
    긴 별칭을 길이로 눌러본다        2/14 -> 3/14. +1

노드 이름은 대개 지어낸 복합어라 사전이 못 덮는다(기초사전 2.0% · 위키
정의문 2.6%). 증거 매칭은 0/14 인데 그건 원래 글자 그대로 찾는 길이다.

그래도 하나는 깨끗하게 갈렸다. 노드마다 '남의 별칭을 대면 이 노드가 받는
평균 점수' 를 재면 이렇게 나온다.

    침해의현재성 0.346  적법행위 0.345  과잉방위불벌 0.341   <- 개념 노드
    압수된흉기 0.063  CCTV 0.058  근무일지 0.050         <- 증거 노드

개념 노드는 별칭이 16~24자짜리 문장이고 증거 노드는 5~8자짜리 이름이다.
포함도는 '물음의 조각이 별칭에 얼마나 덮이나' 라서, 긴 문장은 아무 물음의
말투('~있습니다', '~보면')를 통째로 덮는다. 그래서 '병원에서 떼 온 상해
소견 서류가 있습니다' 가 진단서(0.14)가 아니라 상당성(0.59)으로 간다.
내용이 아니라 길이가 이긴 것이다.

이 파일은 그 자리를 센다. 흡수력이 높은 노드는 둘 중 하나다.

    별칭이 설명문이다   -> 짧게 줄이거나, 설명은 [공리] 로 옮긴다
    쓰임이 실제로 넓다   -> 그대로 두되, 그 그래프에서 증거가 밀린다는 뜻이다

지어내지 않는다. 이 파일은 목록만 내고 아무것도 고치지 않는다.

**별칭을 몇 개까지 써야 하나.** 별칭 하나를 빼고 그 말로 물어 재 봤다
(뺀 말 2,775개, 자가학습 산출물 제외):

    남은 별칭 1개      17.1%
    남은 별칭 2개      17.2%
    남은 별칭 3~4개    27.3%
    남은 별칭 5개 이상  41.7%

하나에서 둘로는 소용이 없고 **셋을 넘으면 뛴다.** 지금 노드 대부분이
별칭 둘(2,014개)이라 바로 그 문턱 아래에 몰려 있다. 그래서 이 파일은
'별칭이 셋 미만인 노드' 를 같이 낸다 — 한 개만 더 쓰면 문턱을 넘는
자리가 어디인지가 곧 할 일 목록이다.

**재 봤지만 안 되는 지표** — 적어 둔다. '별칭이 몇 개인가' 와 '별칭끼리
얼마나 다른가(넓이)' 로 위험을 예측해 보려 했는데 못 가른다. 놓친 노드의
넓이가 0.67~2.78, 맞힌 노드가 0.90~3.97 로 겹친다. 별칭 하나를 빼고 그
별칭으로 되찾는 시험도 1.1% 만 걸리는데, 손으로 적은 별칭끼리는 글자가
겹쳐서 쉬운 문제이기 때문이다. 결과는 그 노드가 아니라 **같은 그래프에
누가 같이 있느냐**가 정한다. 그래서 흡수력만 낸다.
"""
import glob
import itertools
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
os.environ.setdefault("KG_ENCODER", "문자")

import engine                                    # noqa: E402
from progress import Bar                             # noqa: E402

_sample = 40                                       # 노드당 남의 말 몇 개까지 볼까


def graphs(argv):
    if argv:
        return [p for p in argv if p.endswith(".kg")]
    return sorted(glob.glob(os.path.join(here, "graphs", "*.kg")))


def _char_count(s):
    return len("".join(s.split()))


def absorption(path):
    """-> [(흡수력, 노드, 별칭최대길이, 별칭수)] 높은 순."""
    name = os.path.relpath(path, here).replace("\\", "/")
    g = engine.load_graph(name)
    by_layer = {}
    for layer in ("공통층", "사례층"):
        for n, phrases in (g.get(layer) or {}).items():
            by_layer[n] = list(phrases) or [n]
    table = []
    for n, own_aliases in by_layer.items():
        other = [m for k, phrases in by_layer.items() if k != n for m in phrases][:_sample]
        if not other:
            continue
        pt = [max(float(engine._embed_sub(q) @ engine._embed(b)) for b in own_aliases) for q in other]
        table.append((sum(pt) / len(pt), n,
                   max(_char_count(x) for x in own_aliases), len(own_aliases)))
    return sorted(table, reverse=True)


_THRESH = 3          # 별칭이 이만큼은 되어야 처음 보는 말투가 붙기 시작한다


def missing_aliases(path, self_authored):
    """별칭이 문턱 아래인 노드. -> [(별칭수, 노드)] 적은 순"""
    name = os.path.relpath(path, here).replace("\\", "/")
    if name in self_authored or "템플릿" in name:
        return []                       # 틀에서 찍은 것은 사람이 쓸 자리가 아니다
    g = engine.load_graph(name)
    emitted = []
    for layer in ("공통층", "사례층"):
        for n, phrases in (g.get(layer) or {}).items():
            num = len(list(phrases))
            if num < _THRESH:
                emitted.append((num, n))
    return sorted(emitted)


def view(argv):
    count = 20
    if "--개수" in argv:
        count = int(argv[argv.index("--개수") + 1])
    files = graphs([a for a in argv if not a.startswith("--")])
    every = []
    for p in Bar(files, "흡수력"):
        try:
            for pt, n, loc, num in absorption(p):
                every.append((pt, os.path.basename(p), n, loc, num))
        except Exception:
            continue
    if not every:
        print("잴 노드가 없다.")
        return
    every.sort(reverse=True)
    mid = every[len(every) // 2][0]
    print("\n노드 %d개 · 흡수력 중앙값 %.3f" % (len(every), mid))
    print("\n남의 말을 가장 많이 빨아들이는 노드:")
    for pt, file, n, loc, num in every[:count]:
        print("  %.3f  %-24s %-18s 별칭 %d개 · 최대 %d자"
              % (pt, file[:24], n[:18], num, loc))
    print("\n가장 안 빨아들이는 노드 (짧은 증거 이름이 여기 모인다):")
    for pt, file, n, loc, num in every[-5:]:
        print("  %.3f  %-24s %-18s 별칭 %d개 · 최대 %d자"
              % (pt, file[:24], n[:18], num, loc))

    # 별칭이 문턱 아래인 노드 — 한 개만 더 쓰면 넘는 자리다.
    try:
        import self_authoring
        mine = self_authoring.self_authored()
    except Exception:
        mine = set()
    shortfall = []
    for p in files:
        try:
            for num, n in missing_aliases(p, mine):
                shortfall.append((num, os.path.basename(p), n))
        except Exception:
            continue
    if shortfall:
        one = sum(1 for num, _f, _n in shortfall if num <= 1)
        print("\n별칭이 %d개 미만인 노드 %d개 (그중 하나뿐인 것 %d개)"
              % (_THRESH, len(shortfall), one))
        print("  하나만 더 쓰면 문턱을 넘는다 — 그때부터 안 배운 말투도 붙는다.")
        for num, file, n in sorted(shortfall)[:count]:
            print("  별칭 %d개  %-26s %s" % (num, file[:26], n[:30]))


def _selfcheck():
    # 긴 별칭이 짧은 별칭보다 남의 말을 더 덮는다 — 이 파일의 전제다.
    long = "피고인이 그 자리에서 계속 때렸다고 보입니다"
    short = "CCTV"
    prompt = "병원에서 떼 온 상해 소견 서류가 있습니다"
    v = engine._embed_sub(prompt)
    assert float(v @ engine._embed(long)) > float(v @ engine._embed(short)), "전제가 깨졌다"
    assert _char_count("가 나 다") == 3
    assert graphs(["graphs/graph.kg"]) == ["graphs/graph.kg"]
    assert graphs([]), "그래프를 못 찾는다"
    print("자가검사 ok")


if __name__ == "__main__":
    argv = sys.argv[1:]
    if "--자가검사" in argv:
        _selfcheck()
    else:
        view(argv)
