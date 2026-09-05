"""라우터가 안 본 말투로도 제 그래프를 찾는가.

이 값을 즉석 스크립트로 재다가 두 번 틀렸다. 한 번은 색인에 든 예시를
그대로 질문으로 써서 84.5% 가 나왔고(색인을 들여다본 셈이다), 한 번은
색인의 공통층만 바꾸고 vec 을 다시 안 만들어 세 조건이 똑같이 나왔다.
그래서 고정 시험으로 박는다.

  안: 노드마다 마지막 별칭을 색인에서 빼고, 그 별칭으로 물어 제 그래프로
      가는지 본다. 색인에 없는 말투라야 일반화를 재는 것이 된다.
  밖: 갈 그래프가 없는 질문 20개. 거절해야 맞다.

    python routing_benchmark.py            # 기본 인코더
    KG_ENCODER=문자 python routing_benchmark.py
    python routing_benchmark.py --상한 2 3 4 0   # 노드당 색인 예시 수를 쓸어본다
"""
import glob
import json
import os
import sys

import engine

밖경로 = "data/benchmarks/라우팅_밖.json"


def _본문들():
    파일 = [p for p in sorted(glob.glob(os.path.join(engine._여기, "graphs", "*.kg")))
            + sorted(glob.glob(os.path.join(engine._여기, "cases", "사건_*.kg")))
            if "템플릿" not in p]
    읽음 = {}
    for p in 파일:
        try:
            읽음[os.path.relpath(p, engine._여기).replace("\\", "/")] = engine.색인용읽기(p)
        except Exception:
            pass
    return 읽음


def 색인짓기(읽음, 상한=5, 빼기=True, 총량=180):
    """마지막 별칭을 빼고 색인을 짓는다. 빼야 안 본 말투로 잴 수 있다."""
    ix = {"역할": "안내", "목표": "그래프고르기",
          "임계값": {"A_MIN": 0.40, "OK_MIN": 0.60},
          "공통층": {}, "사례층": {}, "무관층": {},
          "엣지": [], "대사": {}, "수치조건": {}}

    def 담기(이름, g, 상한, 빼기):
        증거 = engine.증거뽑기(g)     # 증거는 짧아도 남기고, 앞에 놓는다
        예 = [g.get("목표") or ""]
        for n in 증거:
            말 = list(g["사례층"][n])
            말 = 말[:-1] if 빼기 else 말
            예 += [n] + (말[:상한] if 상한 else 말)
        for 층 in ("공통층", "사례층"):
            for n, 말 in g.get(층, {}).items():
                if n in 증거:
                    continue
                말 = list(말)[:-1] if 빼기 else list(말)
                예 += [x for x in [n] + (말[:상한] if 상한 else 말)
                       if len("".join(x.split())) >= 5]
        예 = [x for x in 예 if x][:총량]
        if 예:
            ix["공통층"][이름] = 예

    for 이름, g in 읽음.items():
        if g.get("색인") == "아니오":     # 자가검사 뼈대는 라우터가 안 본다
            continue
        담기(이름, g, 상한, 빼기)
    # 설명 그래프(.json)는 별칭이 발췌라 뺄 마지막이 없다. 그대로 넣는다.
    for p in engine.설명그래프찾기(engine._여기):
        try:
            담기(os.path.relpath(p, engine._여기).replace("\\", "/"),
                 engine.색인용읽기(p), 2, False)
        except Exception:
            pass
    ix["adj"], ix["증거"] = {}, []
    ix["vec"] = engine._예시벡터(ix)
    return ix


def 재기(읽음, ix, 답까지=False):
    """맞음 두 가지를 같이 센다.

    제자리: 질문을 뽑아온 그 파일로 갔는가. 엄격하지만 겹치는 그래프에서는
            정답표가 틀린다 — '여러 사람 앞에서 말했습니다' 는 graph.kg 에서
            뽑았어도 graph_명예훼손 으로 가는 편이 옳다.
    답함:   고른 그래프가 실제로 답을 했는가(미지가 아닌가). 사용자에게
            중요한 것은 이쪽이다."""
    맞 = 전 = 답 = 0
    샌것 = []
    for 이름, g in 읽음.items():
        if 이름.startswith("cases/"):      # 사건 파일은 같은 법리라 서로 겹친다
            continue
        for 층 in ("공통층", "사례층"):
            for _n, 말 in g.get(층, {}).items():
                if len(말) < 2:
                    continue
                전 += 1
                q = list(말)[-1]
                골, 점, _ = engine.그래프고르기(q, ix)
                if 골 == 이름:
                    맞 += 1
                else:
                    샌것.append((q, 이름, 골, 점))
                if 답까지 and 골:
                    try:
                        답 += engine.judge(engine.그래프불러오기(골), q)[0] != "미지"
                    except Exception:
                        pass
    # 밖 질문은 '모른다' 로 끝나야 한다. 라우터가 거절하는지만 보면 잘못
    # 잰다 — 어느 그래프로 갔더라도 그 그래프가 미지를 내면 사용자에게는
    # 맞는 답이다. 실제로 '서버가 지금 살아 있어' 가 감정대화 그래프로
    # 0.49 에 갔지만 판정은 미지였다. 그래프가 늘 때마다 라우터 거절만
    # 세면 값이 흔들리는데, 답으로 세면 안 흔들린다.
    밖 = json.load(open(engine._길(밖경로), encoding="utf-8"))
    거절 = 0
    for q in 밖:
        골, _, _ = engine.그래프고르기(q, ix)
        if not 골:
            거절 += 1
            continue
        try:
            거절 += engine.judge(engine.그래프불러오기(골), q)[0] in ("미지", "B2")
        except Exception:
            pass                     # 쓰는 중인 그래프는 건너뛴다
    return 맞, 전, 거절, len(밖), 샌것, 답


if __name__ == "__main__":
    읽음 = _본문들()
    상한들 = [5]
    if "--상한" in sys.argv:
        _뒤 = sys.argv[sys.argv.index("--상한") + 1:]
        상한들 = []
        for a in _뒤:
            if a.startswith("--"):
                break
            상한들.append(int(a))
    총량 = 180
    if "--총량" in sys.argv:
        총량 = int(sys.argv[sys.argv.index("--총량") + 1])
    for 상한 in 상한들:
        ix = 색인짓기(읽음, 상한, 총량=총량)
        맞, 전, 거절, 밖수, 샌것, 답 = 재기(읽음, ix, "--답" in sys.argv)
        print("상한 %-4s 총량 %-4s  제자리 %4d/%4d (%.1f%%)%s  밖 거절 %2d/%d"
              % (상한 or "없음", 총량, 맞, 전, 100 * 맞 / 전,
                 ("  답함 %4d (%.1f%%)" % (답, 100 * 답 / 전)) if "--답" in sys.argv else "",
                 거절, 밖수))
    if "--샌것" in sys.argv:
        for q, 참, 골, 점 in 샌것[:30]:
            print("  '%s'  %s -> %s (%.2f)"
                  % (q, 참.split("/")[-1], (골 or "모름").split("/")[-1], 점))
