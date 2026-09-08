# -*- coding: utf-8 -*-
"""잣대를 얼린다. 그래프가 늘어도 재는 자가 안 바뀌게.

    python 평가.py --얼리기      # 고정 물음 세트를 새로 만든다 (한 번만)
    python 평가.py              # 그 세트로 잰다
    python 평가.py --자세히      # 틀린 것까지 본다

왜 얼리나. 이 저장소에서 잣대가 네 번 틀렸고 **네 번 다 좋아 보이는
쪽으로** 틀렸다.

    지능시험    97% 로 나왔다. 바꿔 말하기를 손으로 쓴 별칭끼리 쟀다 -> 실제 82%
    관문 1차    '답함'(미지가 아님)이 자신 있게 틀린 답에 상을 줬다
    관문 2차    물음의 57% 가 그 고리가 스스로 지은 그래프에서 나왔다
    관문 3차    물음 4개를 지키자고 그래프 270개를 유죄로 만들었다

우연이 아니라 성향이다. 그래서 잣대는 세 가지를 지켜야 한다.

  얼려 둔다      물음을 파일에 박는다. 매번 그래프에서 뽑으면 그래프가 늘 때
                 표본이 바뀌어, 나아진 것인지 잣대가 물러진 것인지 못 가린다.
  남의 것으로만  사람이 적은 그래프에서만 뽑는다. 자가학습이 지은 그래프의
                 물음은 틀에서 찍은 별칭이라 쉽다(제자리 52.7% 대 42.0%).
                 제 숙제로 제 점수를 매기면 안 된다.
  대조군을 둔다  별칭을 그대로 물어보는 묶음을 같이 둔다. 이게 100% 가
                 아니면 엔진이 아니라 **시험틀**이 틀린 것이다.

무엇을 얼리나. 노드마다 별칭 하나를 빼서 그것으로 묻는다 — 색인에 없는
말이라야 '외운 것' 이 아니라 '일반화' 를 재는 것이 된다. 뺀 별칭과 그
노드, 그래프를 같이 적어 두므로 나중에 왜 틀렸는지 되짚을 수 있다.

고정 세트는 data/benchmarks/고정물음.json 에 들어가고 저장소에 올린다.
캐시가 아니라 잣대라서다 — 지우면 지난 값과 견줄 수 없게 된다.
"""
import glob
import io
import json
import os
import random
import sys

여기 = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, 여기)
os.environ.setdefault("KG_ENCODER", "문자")

import engine                                    # noqa: E402
from 진행 import 막대                             # noqa: E402

고정터 = os.path.join(여기, "data", "benchmarks", "고정물음.json")
밖터 = os.path.join(여기, "data", "benchmarks", "라우팅_밖.json")


def _자가학습이지은것():
    """자가저작이 들인 그래프. 잣대에서 뺀다."""
    try:
        import 자가저작
        return 자가저작.내가지은것()
    except Exception:
        return set()


def 얼리기(개수=400, 씨=11):
    """사람이 적은 그래프에서만 물음을 뽑아 파일에 박는다. -> 얼린 칸"""
    빼기 = _자가학습이지은것()
    안, 대조 = [], []
    파일 = sorted(glob.glob(os.path.join(여기, "graphs", "*.kg")))
    # 어느 말이 그래프 몇 개에 들어 있나. 둘 이상에 똑같이 있으면 그 말로는
    # 채점을 할 수 없다 — 라벨이 어느 쪽이든 자의적이라서다. 실제로
    # '온도 를 가져간다' 가 난방과 냉방 양쪽에 같은 글자로 있고 점수가
    # 1.00 이었다. 틀에서 찍은 그래프끼리 이런 것이 흔하다.
    몇곳에 = {}
    for p in 막대(파일, "겹침 세기"):
        try:
            g = engine.색인용읽기(p)
        except Exception:
            continue
        for 층 in ("공통층", "사례층"):
            for _n, 말들 in (g.get(층) or {}).items():
                for m in set(말들):
                    몇곳에[m] = 몇곳에.get(m, 0) + 1
    for p in 막대(파일, "얼리기"):
        이름 = os.path.relpath(p, 여기).replace("\\", "/")
        if 이름 in 빼기 or "템플릿" in 이름:
            continue
        try:
            g = engine.색인용읽기(p)
        except Exception:
            continue
        for 층 in ("공통층", "사례층"):
            for n, 말들 in (g.get(층) or {}).items():
                말들 = [m for m in 말들 if 몇곳에.get(m, 0) == 1]
                if len(말들) < 2:
                    continue
                # 마지막 별칭을 빼서 묻는다. 색인에 없는 말이라야 일반화다.
                안.append({"물음": 말들[-1], "그래프": 이름, "노드": n})
                # 대조군은 첫 별칭 그대로. 이게 틀리면 시험틀이 틀린 것이다.
                대조.append({"물음": 말들[0], "그래프": 이름, "노드": n})
    random.Random(씨).shuffle(안)
    random.Random(씨).shuffle(대조)
    칸 = {"판": 2, "씨": 씨,
          "설명": "사람이 적은 그래프에서만 뽑은 고정 물음. 자가학습 산출물과,"
                  " 여러 그래프에 똑같이 들어 있어 라벨이 자의적인 말은 뺐다.",
          "그래프수": len(파일), "뺀그래프수": len(빼기),
          "안": 안[:개수], "대조": 대조[:개수]}
    os.makedirs(os.path.dirname(고정터), exist_ok=True)
    io.open(고정터, "w", encoding="utf-8").write(
        json.dumps(칸, ensure_ascii=False, indent=1))
    return 칸


def 뺀색인(뺄말들):
    """그 말들을 별칭에서 지운 색인. 안 지우면 외운 것을 재게 된다."""
    import routing_benchmark as 재기틀
    뺄 = set(뺄말들)
    읽음 = {}
    for 이름, g in 재기틀._본문들().items():
        새g = dict(g)
        for 층 in ("공통층", "사례층"):
            if 층 in g:
                새g[층] = {n: [m for m in 말들 if m not in 뺄]
                          for n, 말들 in g[층].items()}
        읽음[이름] = 새g
    # 빼기=False. 마지막 별칭을 또 빼면 두 번 빼는 셈이라, 무엇을 재는지
    # 알 수 없게 된다. 뺄 것은 위에서 이미 정확히 뺐다.
    return 재기틀.색인짓기(읽음, 빼기=False)


def 읽기():
    if not os.path.exists(고정터):
        return None
    return json.load(io.open(고정터, encoding="utf-8"))


def 재기(자세히=False):
    칸 = 읽기()
    if not 칸:
        print("고정 물음이 없다. 먼저 `python 평가.py --얼리기`.")
        return None
    # 색인에서 그 물음을 **실제로** 빼야 한다. 처음엔 기록에서만 빼고
    # engine.그래프색인() 을 그대로 썼는데, 그러면 물어보는 말이 색인 안에
    # 그대로 있어 외운 것을 재게 된다. 대조군 90.8% 와 안 물음 90.0% 이
    # 거의 같았던 것이 그 증거다 — 진짜로 뺐다면 벌어져야 한다.
    ix = 뺀색인([x["물음"] for x in 칸["안"]])
    결과, 틀린것 = {}, {}

    def 한묶음(이름, 줄들):
        맞 = 셋안 = 0
        틀 = []
        for x in 막대(줄들, 이름):
            골, _점, 후보 = engine.그래프고르기(x["물음"], ix, 개수=3)
            ok = (골 == x["그래프"])
            맞 += ok
            # 겹치는 그래프에서는 정답표가 틀린다. '2등을 추월하면 몇 등이야'
            # 는 일상추론에서 뽑았지만 순위_추월로 가는 편이 오히려 옳다.
            # 그래서 '적힌 그래프가 상위 셋 안에 들었나' 도 같이 센다.
            셋안 += x["그래프"] in [n for n, _c in 후보]
            if not ok:
                틀.append((x["물음"], x["그래프"], 골))
        결과[이름] = (맞, len(줄들))
        결과[이름 + " · 셋 안"] = (셋안, len(줄들))
        틀린것[이름] = 틀

    한묶음("대조(별칭그대로)", 칸["대조"])
    한묶음("안 물음(뺀 별칭)", 칸["안"])

    밖 = json.load(io.open(밖터, encoding="utf-8"))
    거절 = 0
    for q in 막대(밖, "밖 물음"):
        골, _, _ = engine.그래프고르기(q, ix)
        if not 골:
            거절 += 1
            continue
        try:
            거절 += engine.judge(engine.그래프불러오기(골), q)[0] in ("미지", "B2")
        except Exception:
            pass
    결과["밖 거절"] = (거절, len(밖))

    print("\n고정 물음 %d개 · 얼릴 때 그래프 %d개(자가학습 %d개 뺌)"
          % (len(칸["안"]), 칸.get("그래프수", 0), 칸.get("뺀그래프수", 0)))
    print("=" * 52)
    for 이름, (맞, 총) in 결과.items():
        print("%-18s %4d/%-4d  %5.1f%%" % (이름, 맞, 총, 100 * 맞 / max(총, 1)))
    print("=" * 52)
    ㄷ, ㄷ총 = 결과["대조(별칭그대로)"]
    ㄷ3, _ = 결과["대조(별칭그대로) · 셋 안"]
    if ㄷ3 < ㄷ총 * 0.95:
        print("\n[조심] 별칭을 그대로 물었는데 상위 셋에도 못 드는 것이"
              " %d개다. 이건 시험틀이 틀렸을 수 있다는 신호다."
              % (ㄷ총 - ㄷ3))
    elif ㄷ < ㄷ총 * 0.95:
        print("\n대조군 제자리가 %.1f%% 인데 셋 안은 %.1f%% 다. 모자란 만큼은"
              " 겹치는 그래프다 — 정답표가 하나만 맞다고 적혀 있을 뿐,"
              " 고른 쪽이 틀린 것이 아닐 수 있다."
              % (100 * ㄷ / max(ㄷ총, 1), 100 * ㄷ3 / max(ㄷ총, 1)))
    if 자세히:
        for 이름, 틀 in 틀린것.items():
            if not 틀:
                continue
            print("\n[%s] 틀린 것 %d개 중 앞 8개" % (이름, len(틀)))
            for q, 참, 골 in 틀[:8]:
                print("   '%s'" % q[:44])
                print("       %s -> %s" % (참.split("/")[-1][:26],
                                           (골 or "없음").split("/")[-1][:26]))
    return 결과


def _자가검사():
    # 얼린 물음에는 어디서 왔는지가 같이 있어야 한다. 없으면 왜 틀렸는지
    # 되짚을 수 없고, 되짚을 수 없는 잣대는 고칠 수도 없다.
    칸 = 읽기()
    if 칸:
        for x in 칸["안"][:5] + 칸["대조"][:5]:
            assert {"물음", "그래프", "노드"} <= set(x), x
        # 자가학습이 지은 그래프가 섞이면 제 숙제로 제 점수를 매기게 된다.
        빼기 = _자가학습이지은것()
        샌것 = [x for x in 칸["안"] if x["그래프"] in 빼기]
        assert not 샌것, 샌것[:3]
    assert os.path.basename(고정터) == "고정물음.json"
    # 뺀색인은 그 말을 정말로 지워야 한다. 안 지우면 외운 것을 재게 된다.
    if 칸 and 칸["안"]:
        _말 = 칸["안"][0]["물음"]
        _ix = 뺀색인([_말])
        _샘 = [e for 예 in _ix["공통층"].values() for e in 예 if e == _말]
        assert not _샘, "뺀 말이 색인에 그대로 남았다: %r" % _말
    print("자가검사 ok")


if __name__ == "__main__":
    if "--자가검사" in sys.argv:
        _자가검사()
    elif "--얼리기" in sys.argv:
        칸 = 얼리기()
        print("얼렸다 — 안 물음 %d개 · 대조 %d개 -> %s"
              % (len(칸["안"]), len(칸["대조"]),
                 os.path.relpath(고정터, 여기)))
    else:
        재기("--자세히" in sys.argv)
