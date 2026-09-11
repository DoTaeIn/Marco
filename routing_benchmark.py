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
from progress import Bar

outside_path = "data/benchmarks/라우팅_밖.json"


def _bodies():
    file = [p for p in sorted(glob.glob(os.path.join(engine._here, "graphs", "*.kg")))
            + sorted(glob.glob(os.path.join(engine._here, "cases", "사건_*.kg")))
            if "템플릿" not in p]
    loaded = {}
    for p in file:
        try:
            loaded[os.path.relpath(p, engine._here).replace("\\", "/")] = engine.read_for_index(p)
        except Exception:
            pass
    return loaded


def build_index(loaded, cap=5, strip=True, budget=180):
    """마지막 별칭을 빼고 색인을 짓는다. 빼야 안 본 말투로 잴 수 있다."""
    ix = {"역할": "안내", "목표": "그래프고르기",
          "임계값": {"A_MIN": 0.40, "OK_MIN": 0.60},
          "공통층": {}, "사례층": {}, "무관층": {},
          "엣지": [], "대사": {}, "수치조건": {}}

    def pack_vals(name, g, cap, strip):
        evidence = engine.extract_evidence(g)     # 증거는 짧아도 남기고, 앞에 놓는다
        # 줄마다 어느 노드에서 왔는지 같이 모은다. 라우터의 색인과 같은
        # 것을 재려면 여기서도 소속을 적어야 한다.
        ex, owner = [], []
        def take(node, lines):
            ex.extend(lines)
            owner.extend([node] * len(lines))
        take("", [g.get("목표") or ""])
        for n in evidence:
            phrase = list(g["사례층"][n])
            phrase = phrase[:-1] if strip else phrase
            take(n, [n] + (phrase[:cap] if cap else phrase))
        for layer in ("공통층", "사례층"):
            for n, phrase in g.get(layer, {}).items():
                if n in evidence:
                    continue
                phrase = list(phrase)[:-1] if strip else list(phrase)
                take(n, [x for x in [n] + (phrase[:cap] if cap else phrase)
                         if len("".join(x.split())) >= 5])
        owner = [o for o, x in zip(owner, ex) if x]
        # 개념망으로 별칭을 여기서 불린다. 벡터 만들 때 불리면 길이표는
        # 원본 개수로 계산돼 모양이 어긋난다 — 실제로 (180,) 대 (239,) 로 터졌다.
        ex = [x for x in engine.expand_examples(g, [x for x in ex if x])][:budget]
        # 불려서 새로 생긴 줄은 어느 노드 것인지 모른다. 빈 소속으로 두면
        # 받침에 안 끼고 점수는 그대로 낸다 — 모르는 것을 짐작하지 않는다.
        owner = (owner + [""] * len(ex))[:len(ex)]
        if ex:
            ix["공통층"][name] = ex
            ix.setdefault("소속", {})[name] = owner

    for name, g in loaded.items():
        if g.get("색인") == "아니오":     # 자가검사 뼈대는 라우터가 안 본다
            continue
        pack_vals(name, g, cap, strip)
    # 설명 그래프(.json)는 별칭이 발췌라 뺄 마지막이 없다. 그대로 넣는다.
    for p in engine.find_explain_graph(engine._here):
        try:
            pack_vals(os.path.relpath(p, engine._here).replace("\\", "/"),
                 engine.read_for_index(p), 2, False)
        except Exception:
            pass
    ix["adj"], ix["증거"] = {}, []
    ix["vec"] = engine._example_vecs(ix)
    # 엔진과 같은 자리에서 재려면 성김·길이까지 같아야 한다.
    import numpy as np
    length_table = {n: np.array([len("".join(x.split())) for x in ex], dtype=np.float32)
              for n, ex in ix["공통층"].items()}
    flip_table = {n: (np.array([engine._embed(x) for x in ex], dtype=np.float32)
                    if n.endswith(".kg") else None)
                for n, ex in ix["공통층"].items()}
    sparse = engine.sparse_vec(ix["vec"], length_table, flip_table)
    if sparse is not None:
        ix["성김"], ix["vec"] = sparse, {}
    return ix


def measure(loaded, ix, upto_answer=False):
    """맞음 두 가지를 같이 센다.

    제자리: 질문을 뽑아온 그 파일로 갔는가. 엄격하지만 겹치는 그래프에서는
            정답표가 틀린다 — '여러 사람 앞에서 말했습니다' 는 graph.kg 에서
            뽑았어도 graph_명예훼손 으로 가는 편이 옳다.
    답함:   고른 그래프가 실제로 답을 했는가(미지가 아닌가). 사용자에게
            중요한 것은 이쪽이다."""
    hit = before = ans = 0
    leaked = []
    _total = sum(len(g.get(layer, {})) for name, g in loaded.items()
              if not name.startswith("cases/") for layer in ("공통층", "사례층"))
    _bar = Bar(total=_total, name="안 물음")
    for name, g in loaded.items():
        if name.startswith("cases/"):      # 사건 파일은 같은 법리라 서로 겹친다
            continue
        for layer in ("공통층", "사례층"):
            for _n, phrase in g.get(layer, {}).items():
                _bar.push()
                if len(phrase) < 2:
                    continue
                before += 1
                q = list(phrase)[-1]
                pick, pt, _ = engine.pick_graph(q, ix)
                if pick == name:
                    hit += 1
                else:
                    leaked.append((q, name, pick, pt))
                if upto_answer and pick:
                    try:
                        ans += engine.judge(engine.load_graph(pick), q)[0] != "미지"
                    except Exception:
                        pass
    # 밖 질문은 '모른다' 로 끝나야 한다. 라우터가 거절하는지만 보면 잘못
    # 잰다 — 어느 그래프로 갔더라도 그 그래프가 미지를 내면 사용자에게는
    # 맞는 답이다. 실제로 '서버가 지금 살아 있어' 가 감정대화 그래프로
    # 0.49 에 갔지만 판정은 미지였다. 그래프가 늘 때마다 라우터 거절만
    # 세면 값이 흔들리는데, 답으로 세면 안 흔들린다.
    _bar.close()
    outside = json.load(open(engine._abs(outside_path), encoding="utf-8"))
    refused = 0
    for q in Bar(outside, "밖 물음"):
        pick, _, _ = engine.pick_graph(q, ix)
        if not pick:
            refused += 1
            continue
        try:
            refused += engine.judge(engine.load_graph(pick), q)[0] in ("미지", "B2")
        except Exception:
            pass                     # 쓰는 중인 그래프는 건너뛴다
    return hit, before, refused, len(outside), leaked, ans


if __name__ == "__main__":
    loaded = _bodies()
    caps = [5]
    if "--상한" in sys.argv:
        _tail = sys.argv[sys.argv.index("--상한") + 1:]
        caps = []
        for a in _tail:
            if a.startswith("--"):
                break
            caps.append(int(a))
    budget = 180
    if "--총량" in sys.argv:
        budget = int(sys.argv[sys.argv.index("--총량") + 1])
    for cap in caps:
        ix = build_index(loaded, cap, budget=budget)
        hit, before, refused, outside_count, leaked, ans = measure(loaded, ix, "--답" in sys.argv)
        print("상한 %-4s 총량 %-4s  제자리 %4d/%4d (%.1f%%)%s  밖 거절 %2d/%d"
              % (cap or "없음", budget, hit, before, 100 * hit / before,
                 ("  답함 %4d (%.1f%%)" % (ans, 100 * ans / before)) if "--답" in sys.argv else "",
                 refused, outside_count))
    if "--샌것" in sys.argv:
        for q, true, pick, pt in leaked[:30]:
            print("  '%s'  %s -> %s (%.2f)"
                  % (q, true.split("/")[-1], (pick or "모름").split("/")[-1], pt))
