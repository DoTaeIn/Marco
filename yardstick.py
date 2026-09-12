# -*- coding: utf-8 -*-
"""잣대를 얼린다. 그래프가 늘어도 재는 자가 안 바뀌게.

    python yardstick.py --얼리기      # 고정 물음 세트를 새로 만든다 (한 번만)
    python yardstick.py              # 그 세트로 잰다
    python yardstick.py --자세히      # 틀린 것까지 본다

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
import copy
import io
import json
import os
import random
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
os.environ.setdefault("KG_ENCODER", "문자")

import engine                                    # noqa: E402
from progress import Bar                             # noqa: E402

frozen_dir = os.path.join(here, "data", "benchmarks", "고정물음.json")
outside_dir = os.path.join(here, "data", "benchmarks", "라우팅_밖.json")


def _self_learning_authored():
    """자가저작이 들인 그래프. 잣대에서 뺀다."""
    try:
        import self_authoring
        return self_authoring.self_authored()
    except Exception:
        return set()


def freeze(count=400, seed=11):
    """사람이 적은 그래프에서만 물음을 뽑아 파일에 박는다. -> 얼린 칸"""
    strip = _self_learning_authored()
    inside, control = [], []
    file = sorted(glob.glob(os.path.join(here, "graphs", "*.kg")))
    # 어느 말이 그래프 몇 개에 들어 있나. 둘 이상에 똑같이 있으면 그 말로는
    # 채점을 할 수 없다 — 라벨이 어느 쪽이든 자의적이라서다. 실제로
    # '온도 를 가져간다' 가 난방과 냉방 양쪽에 같은 글자로 있고 점수가
    # 1.00 이었다. 틀에서 찍은 그래프끼리 이런 것이 흔하다.
    in_how_many = {}
    for p in Bar(file, "겹침 세기"):
        try:
            g = engine.read_for_index(p)
        except Exception:
            continue
        for layer in ("공통층", "사례층"):
            for _n, phrases in (g.get(layer) or {}).items():
                for m in set(phrases):
                    in_how_many[m] = in_how_many.get(m, 0) + 1
    for p in Bar(file, "얼리기"):
        name = os.path.relpath(p, here).replace("\\", "/")
        if name in strip or "템플릿" in name:
            continue
        try:
            g = engine.read_for_index(p)
        except Exception:
            continue
        for layer in ("공통층", "사례층"):
            for n, phrases in (g.get(layer) or {}).items():
                phrases = [m for m in phrases if in_how_many.get(m, 0) == 1]
                if len(phrases) < 2:
                    continue
                # 마지막 별칭을 빼서 묻는다. 색인에 없는 말이라야 일반화다.
                inside.append({"물음": phrases[-1], "그래프": name, "노드": n})
                # 대조군은 첫 별칭 그대로. 이게 틀리면 시험틀이 틀린 것이다.
                control.append({"물음": phrases[0], "그래프": name, "노드": n})
    random.Random(seed).shuffle(inside)
    random.Random(seed).shuffle(control)
    slot = {"판": 2, "씨": seed,
          "설명": "사람이 적은 그래프에서만 뽑은 고정 물음. 자가학습 산출물과,"
                  " 여러 그래프에 똑같이 들어 있어 라벨이 자의적인 말은 뺐다.",
          "그래프수": len(file), "뺀그래프수": len(strip),
          "안": inside[:count], "대조": control[:count]}
    os.makedirs(os.path.dirname(frozen_dir), exist_ok=True)
    io.open(frozen_dir, "w", encoding="utf-8").write(
        json.dumps(slot, ensure_ascii=False, indent=1))
    return slot


def index_without(words_to_remove):
    """그 말들을 별칭에서 지운 색인. 안 지우면 외운 것을 재게 된다."""
    import routing_benchmark as bench
    remove = set(words_to_remove)
    loaded = {}
    for name, g in bench._bodies().items():
        new_g = dict(g)
        for layer in ("공통층", "사례층"):
            if layer in g:
                new_g[layer] = {n: [m for m in phrases if m not in remove]
                          for n, phrases in g[layer].items()}
        loaded[name] = new_g
    # 빼기=False. 마지막 별칭을 또 빼면 두 번 빼는 셈이라, 무엇을 재는지
    # 알 수 없게 된다. 뺄 것은 위에서 이미 정확히 뺐다.
    return bench.build_index(loaded, strip=False)


def read():
    if not os.path.exists(frozen_dir):
        return None
    return json.load(io.open(frozen_dir, encoding="utf-8"))


def measure(verbose=False):
    slot = read()
    if not slot:
        print("고정 물음이 없다. 먼저 `python yardstick.py --얼리기`.")
        return None
    # 색인에서 그 물음을 **실제로** 빼야 한다. 처음엔 기록에서만 빼고
    # engine.그래프색인() 을 그대로 썼는데, 그러면 물어보는 말이 색인 안에
    # 그대로 있어 외운 것을 재게 된다. 대조군 90.8% 와 안 물음 90.0% 이
    # 거의 같았던 것이 그 증거다 — 진짜로 뺐다면 벌어져야 한다.
    ix = index_without([x["물음"] for x in slot["안"]])
    result, wrong_ones = {}, {}

    def one_group(name, lines):
        hit = three_inside = 0
        template = []
        for x in Bar(lines, name):
            pick, _pt, cand = engine.pick_graph(x["물음"], ix, count=3)
            ok = (pick == x["그래프"])
            hit += ok
            # 겹치는 그래프에서는 정답표가 틀린다. '2등을 추월하면 몇 등이야'
            # 는 일상추론에서 뽑았지만 순위_추월로 가는 편이 오히려 옳다.
            # 그래서 '적힌 그래프가 상위 셋 안에 들었나' 도 같이 센다.
            three_inside += x["그래프"] in [n for n, _c in cand]
            if not ok:
                template.append((x["물음"], x["그래프"], pick))
        result[name] = (hit, len(lines))
        result[name + " · 셋 안"] = (three_inside, len(lines))
        wrong_ones[name] = template

    def evidence_group(name, lines):
        """라우터 셋을 판정까지 열어 보고 고르면 몇이나 맞나.

        위의 줄들은 라우터만 잰다. 그런데 실제로 답할 때는 후보를 세션으로
        열어 근거가 서는지 본다(engine.answer). 라우터는 표면을 보고 판정은
        근거를 보는데 근거 쪽이 더 센 신호라, 재는 자리가 다르면 시스템이
        하는 일을 못 본다.

        새 답을 만들지 않는다 — 이미 각 그래프가 가진 증거로 묻는 것뿐이다.
        """
        hit = 0
        for x in Bar(lines, name):
            _pick, _pt, cand = engine.pick_graph(x["물음"], ix, count=3)
            best = ((-1, -1.0), None)
            for graph_name, score in cand:
                if not graph_name.endswith(".kg"):
                    continue
                try:
                    verdict, _answer = engine.judge(engine.load(graph_name), x["물음"])
                except Exception:
                    continue
                key = (engine._verdict_rank(verdict), score)
                if key > best[0]:
                    best = (key, graph_name)
            hit += best[1] == x["그래프"]
        result[name] = (hit, len(lines))
        wrong_ones[name] = []

    one_group("대조(별칭그대로)", slot["대조"])
    one_group("안 물음(뺀 별칭)", slot["안"])
    evidence_group("안 물음 · 근거까지 봄", slot["안"])

    def node_group(name, lines, strip):
        """고른 그래프 **안에서** 그 개념을 짚나. 라우팅과 다른 층이다.

        왜 따로 재나. 위의 두 줄은 '905개 중 어느 그래프냐' 만 본다. 그런데
        바꿔 말하기가 막히는 자리는 그래프를 맞게 골라 준 다음이다.

        왜 두 가지로 세나. 개념 하나가 그래프에 두 노드로 들어가 있다.

            마일스톤은프로젝트진행에서...시점이다      <- 정의
            *마일스톤질문                            <- 물음
            마일스톤질문 -설명함-> 마일스톤은...시점이다  <- 같다고 적혀 있다

        '중요 단계가 끝나는 시점' 을 물으면 매처는 정의 노드로 **정확히**
        간다. 정답표는 질문 노드만 적어 두므로 0점이 된다. 그래서 사람이
        `설명함` 이라 적어 이어 둔 것까지 세는 줄을 나란히 둔다. 문턱을
        낮추는 것이 아니라 그래프에 적힌 지식을 읽는 것이다 —
        `이어짐`·`충족`·`부정` 은 논증 관계라 접지 않는다."""
        import collections
        by_graph = collections.defaultdict(list)
        for x in lines:
            if x.get("그래프") and x.get("노드"):
                by_graph[x["그래프"]].append(x)
        exact = folded = seen = 0
        for path, group in Bar(sorted(by_graph.items()), name):
            try:
                g = copy.deepcopy(engine.read_kg(path))
            except Exception:
                continue
            if strip:
                drop = {x["물음"] for x in group}
                for layer in ("공통층", "사례층"):
                    for n, phrases in list(g.get(layer, {}).items()):
                        left = [p for p in phrases if p not in drop]
                        if left:
                            g[layer][n] = left
            g["vec"] = engine._example_vecs(g)
            cands = list(g["공통층"]) + list(g["사례층"])
            same = {(x, y) for x, rel, y in g.get("엣지", []) if rel == "설명함"}
            for x in group:
                if x["노드"] not in cands:
                    continue
                seen += 1
                got, _pt = engine.match(x["물음"], cands, g)
                if got == x["노드"]:
                    exact += 1
                    folded += 1
                elif (got, x["노드"]) in same or (x["노드"], got) in same:
                    folded += 1
        result[name] = (exact, seen)
        result[name + " · 설명함까지"] = (folded, seen)

    node_group("노드 대조(별칭그대로)", slot["대조"], False)
    node_group("노드 안 물음(뺀 별칭)", slot["안"], True)

    outside = json.load(io.open(outside_dir, encoding="utf-8"))
    refused = 0
    for q in Bar(outside, "밖 물음"):
        pick, _, _ = engine.pick_graph(q, ix)
        if not pick:
            refused += 1
            continue
        try:
            refused += engine.judge(engine.load_graph(pick), q)[0] in ("미지", "B2")
        except Exception:
            pass
    result["밖 거절"] = (refused, len(outside))

    print("\n고정 물음 %d개 · 얼릴 때 그래프 %d개(자가학습 %d개 뺌)"
          % (len(slot["안"]), slot.get("그래프수", 0), slot.get("뺀그래프수", 0)))
    print("=" * 52)
    for name, (hit, total) in result.items():
        print("%-18s %4d/%-4d  %5.1f%%" % (name, hit, total, 100 * hit / max(total, 1)))
    print("=" * 52)
    print("위 네 줄은 905개 중 어느 그래프냐(라우팅), 아래 네 줄은 그 그래프"
          " 안에서 어느 개념이냐. 바꿔 말하기가 막히는 자리는 아래쪽이다.")
    n_ctl, n_total = result.get("노드 대조(별칭그대로) · 설명함까지", (0, 0))
    if n_total and n_ctl < n_total * 0.95:
        print("\n[조심] 노드 대조군이 %.1f%% 다. 별칭을 그대로 물었으면 그"
              " 노드로 가야 한다. 낮으면 매처가 아니라 그래프나 시험틀을"
              " 봐야 한다 — 같은 별칭이 두 노드에 달린 것이 흔한 원인이다."
              % (100 * n_ctl / n_total))
    ㄷ, ctl_total = result["대조(별칭그대로)"]
    ㄷ3, _ = result["대조(별칭그대로) · 셋 안"]
    if ㄷ3 < ctl_total * 0.95:
        print("\n[조심] 별칭을 그대로 물었는데 상위 셋에도 못 드는 것이"
              " %d개다. 이건 시험틀이 틀렸을 수 있다는 신호다."
              % (ctl_total - ㄷ3))
    elif ㄷ < ctl_total * 0.95:
        print("\n대조군 제자리가 %.1f%% 인데 셋 안은 %.1f%% 다. 모자란 만큼은"
              " 겹치는 그래프다 — 정답표가 하나만 맞다고 적혀 있을 뿐,"
              " 고른 쪽이 틀린 것이 아닐 수 있다."
              % (100 * ㄷ / max(ctl_total, 1), 100 * ㄷ3 / max(ctl_total, 1)))
    if verbose:
        for name, template in wrong_ones.items():
            if not template:
                continue
            print("\n[%s] 틀린 것 %d개 중 앞 8개" % (name, len(template)))
            for q, true, pick in template[:8]:
                print("   '%s'" % q[:44])
                print("       %s -> %s" % (true.split("/")[-1][:26],
                                           (pick or "없음").split("/")[-1][:26]))
    return result


def _selfcheck():
    # 얼린 물음에는 어디서 왔는지가 같이 있어야 한다. 없으면 왜 틀렸는지
    # 되짚을 수 없고, 되짚을 수 없는 잣대는 고칠 수도 없다.
    slot = read()
    if slot:
        for x in slot["안"][:5] + slot["대조"][:5]:
            assert {"물음", "그래프", "노드"} <= set(x), x
        # 자가학습이 지은 그래프가 섞이면 제 숙제로 제 점수를 매기게 된다.
        strip = _self_learning_authored()
        leaked = [x for x in slot["안"] if x["그래프"] in strip]
        assert not leaked, leaked[:3]
    assert os.path.basename(frozen_dir) == "고정물음.json"
    # 뺀색인은 그 말을 정말로 지워야 한다. 안 지우면 외운 것을 재게 된다.
    if slot and slot["안"]:
        _phrase_part = slot["안"][0]["물음"]
        _ix = index_without([_phrase_part])
        _leak = [e for ex in _ix["공통층"].values() for e in ex if e == _phrase_part]
        assert not _leak, "뺀 말이 색인에 그대로 남았다: %r" % _phrase_part
    print("자가검사 ok")


if __name__ == "__main__":
    if "--자가검사" in sys.argv:
        _selfcheck()
    elif "--얼리기" in sys.argv:
        slot = freeze()
        print("얼렸다 — 안 물음 %d개 · 대조 %d개 -> %s"
              % (len(slot["안"]), len(slot["대조"]),
                 os.path.relpath(frozen_dir, here)))
    else:
        measure("--자세히" in sys.argv)
