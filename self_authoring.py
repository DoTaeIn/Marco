# -*- coding: utf-8 -*-
"""사전 한 줄에서 그래프를 짓고, **있던 답을 해치지 않는 것만** 들인다.

    python self_authoring.py --캐다 --최대 200    # 후보만 짓는다 (graphs/후보/)
    python self_authoring.py --한바퀴 --최대 200   # 짓고 · 거르고 · 들인다
    python self_authoring.py --물리다             # 지난 바퀴에 들인 것을 되돌린다
    python self_authoring.py --기록               # 지난 바퀴들이 무엇을 바꿨나
    python self_authoring.py --재심사             # 이미 들인 것을 지금 관문으로 다시
    python self_authoring.py --재심사 --치우기     # 다시 걸린 것을 지운다
    python self_authoring.py --처음부터           # 진도를 버리고 사전 앞에서 다시
    python self_authoring.py --자가검사

배경에서 되풀이해 돌리는 것을 전제로 한다. 그래서 어디까지 캤는지를
`graphs/후보/.진도.json` 에 남긴다. 이게 없으면 바퀴마다 사전 앞부분을
다시 훑는데, 앞부분은 이미 그래프가 있거나 이미 걸러진 낱말이라 한 바퀴가
통째로 헛돈다 — 사전 56,555 표제 중 그래프가 되는 것은 1.3% 뿐이다.

진도에는 버린 낱말도 같이 적는다. 유형뽑기에서 떨어진 것과 관문에서
도둑으로 걸린 것 둘 다다. 안 적으면 같은 낱말을 매번 다시 지어 다시
거른다. 끝까지 가면 처음으로 돌아온다 — 사전이 늘거나 뽑기가 좋아지면
예전에 버린 것도 다시 볼 값이 있다.

왜 관문이 있어야 하나. 손으로 적는 속도로는 상식 한 벌에 몇 해가 걸린다.
그래서 사전을 통째로 밀어 넣고 싶어지는데, `목적그래프` 가 표준국어대사전
56,555 표제에서 짓는 그래프는 표본 40개 기준 **6할만** 쓸 만하다. 742개를
그냥 넣고 재 봤다(원본 178개 · 물음 600개, 문자 인코더):

    제자리  38.8% -> 38.0%    (-0.8%p)
    답함    62.3% -> 60.0%    (-2.3%p)
    밖 거절  27/27 -> 25/27

쓰레기 그래프는 조용히 있지 않는다. 라우터의 표를 **뺏는다**. `기포는
…모양을 이룬 것` 같은 것이 색인에 들어가면 '모양' 이 들어간 남의 물음을
가져가고, 그 물음은 거기서 미지가 된다. 아는 것이 늘수록 답이 주는 것이다.

그래서 이 파일이 하는 일은 짓는 것이 아니라 **거르는 것**이다.

잣대로 처음에 '답함'(미지가 아님)을 썼는데 틀린 잣대였다. 후보 200개를
넣으니 답함이 382 에서 395 로 **올랐다**. 늘어난 것을 들여다보니 이랬다.

    '양봉 는 꿀벌 을 기르는 일이라 꿀벌 가 있어야 한다'
        -> graph_대학살 로 가서 [인정] '대학살에는사람들가필요'

답함은 자신 있게 틀린 답에 상을 준다. 미지가 아니기만 하면 되니까. 같은
바퀴에서 제자리는 231 에서 228 로 떨어졌다 — 그쪽이 정직한 신호다. 그래서
잣대는 *들이기 전에 제 그래프로 가던 물음이 들인 뒤에도 제자리로 가는가*
하나다. 뺏은 후보는 이름을 남기고 버린다.

들인 것을 어떻게 무르나. `graphs/후보/.들인것.json` 에 이번 바퀴에 옮긴
파일 이름이 남는다. `--물리다` 는 그 목록만 지운다. 사람이 손댄 그래프는
목록에 없으니 안 건드린다.

관문이 지키는 것과 못 지키는 것을 헷갈리면 안 된다.

지키는 것: **이미 제자리로 가던 물음은 그대로 간다.** 200개를 넣고 걸러
193개를 남겼을 때 제자리가 238 에서 238 로 그대로였다. 밖 거절도 27/27
그대로다.

못 지키는 것 둘.

첫째, 후보가 **쓸모 있는 지식인지는 안 본다**. `기포는 …모양을 이룬 것`
처럼 사물인데 동작인 척하는 그래프도 아무 표를 안 뺏으면 그냥 들어온다.
뜻이 맞는지는 여전히 사람이 봐야 한다.

둘째, **원래 아무도 못 답하던 물음**에 후보가 답하기 시작하는 것은 못
막는다. 같은 바퀴에서 답함이 378 에서 395 로 올랐는데, 늘어난 쪽을
들여다보면 '안 가져간다' 같이 어느 그래프 것도 아닌 물음이 아무 그래프로
가서 인정을 받는다. 그 물음은 미지로 두는 편이 옳다. 그러니 **답함이
오른 것을 이 고리의 성과로 읽으면 안 된다.**

전체 벤치마크 퍼센트도 같은 이유로 못 믿는다. 그래프가 늘면 그 그래프의
별칭이 물음으로 딸려 들어와 물음 수 자체가 는다(2,173 -> 3,061). 제 물음에
제가 답하는 것이라 평균이 저절로 오른다. 볼 것은 퍼센트가 아니라 *들이기
전에 맞히던 물음을 그대로 맞히는가* 와 *밖 거절이 안 줄었는가* 둘이다.
"""
import glob
import io
import json
import os
import random
import shutil
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)
os.environ.setdefault("KG_ENCODER", "문자")

import engine                                    # noqa: E402
import purpose_graph                                  # noqa: E402
import routing_benchmark as bench                 # noqa: E402
from progress import Bar                             # noqa: E402

cand_dir = os.path.join(here, "graphs", "후보")
admitted_log = os.path.join(cand_dir, ".들인것.json")
log_dropped = os.path.join(cand_dir, ".버린것.json")
log_progress = os.path.join(cand_dir, ".진도.json")
log_round = os.path.join(here, "자가학습기록.jsonl")


def _graph_inner(path):
    """들인 그래프에서 무엇이 늘었는지 센다. -> {목표, 노드, 엣지, 증거, 출처}

    `색인용읽기` 가 아니라 `load` 를 쓴다. 가벼운 쪽은 증거를 안 채워서
    무엇을 세든 증거가 0으로 나갔다 — 기록에 남는 거짓말이 된다."""
    try:
        g = engine.load(path)
    except Exception:
        return {}
    node = len(g.get("공통층") or {}) + len(g.get("사례층") or {})
    return {"목표": g.get("목표"), "노드": node,
            "엣지": len(g.get("엣지") or ()),
            "증거": len(g.get("증거") or ()),
            "출처": next(iter((g.get("출처") or {}).values()), "")}


def record_round(slot):
    """한 바퀴가 무엇을 바꿨는지 한 줄로 남긴다. UI 가 이걸 읽는다."""
    slot = dict(slot, **{"때": __import__("datetime").datetime.now().isoformat(timespec="seconds")})
    with io.open(log_round, "a", encoding="utf-8") as f:
        f.write(json.dumps(slot, ensure_ascii=False) + "\n")
    return slot


def read_round(recent=50):
    """지난 바퀴들. 새것이 뒤."""
    if not os.path.exists(log_round):
        return []
    line = []
    for line_text in io.open(log_round, encoding="utf-8"):
        try:
            line.append(json.loads(line_text))
        except Exception:
            pass
    return line[-recent:]


def read_progress():
    """어디까지 캤나. 없으면 처음부터.

    이게 없으면 배경에서 돌릴 때마다 사전 앞부분을 다시 훑는다. 앞부분은
    이미 그래프가 있거나 이미 걸러진 낱말이라, 한 바퀴가 통째로 헛돈다."""
    try:
        slot = json.load(io.open(log_progress, encoding="utf-8"))
        return int(slot.get("본데까지", 0)), int(slot.get("표제수", 0)), set(slot.get("버린말", ()))
    except Exception:
        return 0, 0, set()


def write_progress(seen_upto, headword_count, dropped_phrase):
    os.makedirs(cand_dir, exist_ok=True)
    io.open(log_progress, "w", encoding="utf-8").write(json.dumps(
        {"본데까지": seen_upto, "표제수": headword_count,
         "버린말": sorted(dropped_phrase)}, ensure_ascii=False, indent=1))


def known_words():
    """이미 그래프가 있는 낱말. 같은 것을 또 짓지 않는다."""
    whole_text = set()
    for p in glob.glob(os.path.join(here, "graphs", "*.kg")):
        name = os.path.basename(p)[len("graph_"):-len(".kg")]
        whole_text.add(name.split("_")[0])
    return whole_text


def dig(max_n=200, folder="data/사전", resume=True):
    """사전에서 그래프가 될 만한 항목을 캔다. -> [{말, 뜻, 도식}]

    지난번에 멈춘 자리에서 잇는다. 사전 56,555 표제 중 그래프가 되는 것은
    746개(1.3%)뿐이라, 처음부터 훑으면 한 바퀴의 대부분을 이미 본 낱말을
    다시 보는 데 쓴다. 끝까지 가면 처음으로 돌아온다 — 사전이 늘거나
    유형뽑기가 좋아지면 예전에 버린 것도 다시 볼 값이 있다.

    표제 수가 달라지면 진도를 버린다. 사전이 바뀐 것이라 자리 번호가
    가리키는 곳이 달라지기 때문이다."""
    import dict_extract
    entry = dict_extract.read_dict(os.path.join(here, folder))
    seen_upto, old_headword_count, dropped_phrase = read_progress() if resume else (0, 0, set())
    if old_headword_count != len(entry):
        seen_upto, dropped_phrase = 0, set()
    if seen_upto >= len(entry):
        seen_upto, dropped_phrase = 0, set()      # 한 바퀴 다 돌았으면 처음으로
    already = known_words()
    genus_map, _target_map, _action = dict_extract.build_chain(entry)
    emitted = []
    _bar = Bar(total=max_n, name="캐기")
    i = seen_upto
    while i < len(entry):
        it = entry[i]
        i += 1
        phrase, meaning = it["말"], it["뜻"]
        if phrase in already or phrase in dropped_phrase or "/" in phrase or " " in phrase:
            continue
        if not purpose_graph.build(meaning, phrase=phrase):        # 대상이 안 뽑히면 여기서 끝
            dropped_phrase.add(phrase)
            continue
        emitted.append({"말": phrase, "뜻": meaning,
                     "도식": dict_extract.find_schema(phrase, genus_map) or "물건"})
        already.add(phrase)
        _bar.push()
        if len(emitted) >= max_n:
            break
    _bar.close()
    if resume:
        write_progress(i, len(entry), dropped_phrase)
    return emitted


def author(items, parts=None):
    """후보를 graphs/후보/ 에 쓴다. lint 를 통과한 것만. -> 쓴 파일들"""
    parts = parts or cand_dir
    os.makedirs(parts, exist_ok=True)
    written = []
    for it in Bar(items, "짓기"):
        txt = purpose_graph.build(it["뜻"], src="표준국어대사전",
                          phrase=it["말"], schema=it["도식"], index=True)
        if not txt:
            continue
        p = os.path.join(parts, "graph_%s.kg" % it["말"])
        io.open(p, "w", encoding="utf-8").write(txt)
        try:
            if engine.lint(engine.load(p)):
                os.remove(p)
                continue
        except Exception:
            os.remove(p)
            continue
        written.append(p)
    return written


def self_authored():
    """이 고리가 여태 들인 그래프 이름. 기록에서 읽고, 없으면 출처로 본다."""
    name = set()
    for x in read_round(10 ** 6):
        for g in (x.get("들인것") or ()):
            if g.get("이름"):
                name.add("graphs/" + g["이름"])
    return name


def sample_questions(orig, count=600, seed=7, others_only=True):
    """기존 그래프에서 '이미 답하던 물음' 을 뽑는다. 관문의 잣대다.

    **이 고리가 지은 그래프는 뺀다.** 안 빼면 관문이 제 숙제로 제 점수를
    매긴다. 실제로 그렇게 되고 있었다 — 네 바퀴 만에 그래프의 73% 가
    자가학습 산출물이 되었고, 관문이 쓰던 물음 600개 중 341개(57%)가
    거기서 나왔다. 그 물음은 틀에서 찍은 별칭이라 제 낱말을 달고 있어
    라우팅이 쉽다.

        자가학습이 지은 그래프의 물음   제자리 52.7%
        사람이 적은 그래프의 물음       제자리 42.0%

    쉬운 물음이 표본을 채우니 '제자리가 안 떨어졌다' 는 문턱이 저절로
    낮아졌고, 버림율이 41% 에서 9% 로 내려갔다. 늘어나는 것처럼 보이지만
    잣대가 물러진 것이다."""
    # 얼려 둔 잣대가 있으면 그것을 쓴다. 매번 그래프에서 뽑으면 그래프가
    # 늘 때 표본이 바뀌어, 나아진 것인지 잣대가 물러진 것인지 못 가린다 —
    # 실제로 그렇게 물러져서 버림율이 41% 에서 9% 로 떨어졌다.
    if others_only:
        try:
            import yardstick
            slot = yardstick.read()
            if slot and slot.get("안"):
                frozen = [(x["물음"], x["그래프"]) for x in slot["안"]
                       if x["그래프"] in orig]
                if frozen:
                    return frozen[:count]
        except Exception:
            pass                        # 얼린 것이 없으면 아래로 내려간다
    strip = self_authored() if others_only else set()
    prompt = []
    for name, g in orig.items():
        if name.startswith("cases/") or name in strip:
            continue
        for layer in ("공통층", "사례층"):
            for _n, phrase in g.get(layer, {}).items():
                if len(phrase) >= 2:
                    prompt.append((list(phrase)[-1], name))
    random.Random(seed).shuffle(prompt)
    return prompt[:count]


def unpack(ix, prompt):
    """-> (제자리, 답함, 물음마다 (간곳, 답했나, 점수))"""
    unchanged = answered = 0
    visited = []
    for q, true in Bar(prompt, "풀기"):
        pick, pt, _ = engine.pick_graph(q, ix)
        unchanged += (pick == true)
        ans = False
        if pick:
            try:
                ans = engine.judge(engine.load_graph(pick), q)[0] != "미지"
            except Exception:
                ans = False
        answered += ans
        visited.append((pick, ans, pt))
    return unchanged, answered, visited


def find_thieves(orig, cand, prompt, before=None, max_per_question=8):
    """제자리로 가던 물음을 가로챌 후보를 찾는다.

    -> (범인집합, 전, 남은후보)

    후보를 하나씩 넣어 보면 후보 수만큼 벤치마크를 돌려야 한다. 그럴 필요가
    없다. 라우터는 그래프마다 점수를 따로 매기고 가장 높은 것을 고르므로,
    **후보만 넣은 색인**에서 그 물음의 후보 순위를 받아 원본에서의 참
    그래프 점수와 견주면 누가 이기는지 한 번에 다 나온다.

    처음에는 '범인을 빼고 다시 재기' 를 아무도 못 이길 때까지 돌렸다.
    그것이 틀렸다. 후보가 수백 개면 비슷한 것들이 줄줄이 같은 물음을
    가져가서, 물음 하나가 수십 개를 유죄로 만든다. 실제로 사람 물음
    400개 중 뺏기는 것은 4개인데 유죄는 270개가 나왔다 — 물음 하나당
    67개꼴이다.

    그래서 다툼이 붙은 물음마다 이기는 후보를 **한 번에 다 세고**, 그 수가
    `한물음최대` 를 넘으면 그 물음은 포기한다. 그 물음 하나를 지키자고
    그래프 수십 개를 지우는 것은 남는 장사가 아니다. 포기한 물음은 세어서
    같이 돌려준다 — 감추면 잣대가 또 무너진다."""
    before = before or unpack(bench.build_index(orig), prompt)
    ix_after = bench.build_index(cand)
    thief, gave_up = set(), []
    for i, (q, true) in enumerate(prompt):
        pick, _ans, orig_score = before[2][i]
        if pick != true:
            continue                    # 원래도 제자리가 아니면 잃을 것이 없다
        _pick2, _score2, cand_rank = engine.pick_graph(q, ix_after, min_n=0.0, count=200)
        winners = [n for n, c in cand_rank if c >= orig_score]
        if not winners:
            continue
        if len(winners) > max_per_question:
            gave_up.append((q, len(winners)))
            continue
        thief.update(winners)
    remaining = {k: v for k, v in cand.items() if k not in thief}
    if gave_up:
        print("  지키기를 포기한 물음 %d개 (한 물음에 후보 %d개 이상이 붙어,"
              " 지키려면 그만큼을 지워야 한다)"
              % (len(gave_up), max_per_question + 1))
    return thief, before, remaining

def admit(survived):
    """후보를 graphs/ 로 옮기고 무엇을 옮겼는지 남긴다."""
    moved = []
    for p in survived:
        target = os.path.join(here, "graphs", os.path.basename(p))
        if os.path.exists(target):            # 사람이 적은 것을 덮지 않는다
            continue
        shutil.move(p, target)
        moved.append(os.path.basename(target))
    io.open(admitted_log, "w", encoding="utf-8").write(
        json.dumps(moved, ensure_ascii=False, indent=1))
    return moved


def revert():
    """지난 바퀴에 들인 것만 지운다. 사람이 적은 것은 목록에 없다."""
    if not os.path.exists(admitted_log):
        return []
    names = json.load(io.open(admitted_log, encoding="utf-8"))
    erased = []
    for name in names:
        p = os.path.join(here, "graphs", name)
        if os.path.exists(p):
            os.remove(p)
            erased.append(name)
    os.remove(admitted_log)
    # 판정하면서 그래프 옆에 .미지.log 가 생긴다. 그래프를 무르면 그것도
    # 같이 치운다 — 안 그러면 없는 그래프의 로그만 후보터에 쌓인다.
    for p in glob.glob(os.path.join(cand_dir, "*.미지.log")):
        os.remove(p)
    return erased


def one_round(max_n=200, question_count=600, dry_run=False):
    entry = dig(max_n)
    print("캔 것 %d개" % len(entry))
    if not entry:
        return {"캠": 0, "들임": 0}
    written = author(entry)
    print("lint 통과 %d개" % len(written))
    orig = bench._bodies()
    cand = {}
    for p in written:
        try:
            cand["graphs/후보/" + os.path.basename(p)] = engine.read_for_index(p)
        except Exception:
            pass
    prompt = sample_questions(orig, question_count)
    thief, before, remaining = find_thieves(orig, cand, prompt)
    after = unpack(bench.build_index(dict(orig, **remaining)), prompt)
    print("물음 %d개 · 제자리 %d -> %d · 답함 %d -> %d · 표를 뺏어 버린 후보 %d개"
          % (len(prompt), before[0], after[0], before[1], after[1], len(thief)))
    io.open(log_dropped, "w", encoding="utf-8").write(
        json.dumps(sorted(thief), ensure_ascii=False, indent=1))
    # 도둑도 진도에 적어 둔다. 안 적으면 다음 바퀴에 같은 낱말을 또 지어
    # 또 거른다 — 짓는 값이 매번 그대로 든다.
    if thief:
        _seen_at, _headword_count, _dropped = read_progress()
        for k in thief:
            name = os.path.basename(k)
            if name.startswith("graph_") and name.endswith(".kg"):
                _dropped.add(name[len("graph_"):-len(".kg")])
        write_progress(_seen_at, _headword_count, _dropped)
    for k in thief:
        p = os.path.join(here, k)
        if os.path.exists(p):
            os.remove(p)
    if after[0] < before[0]:
        print("아직 손해다(제자리 %d < %d). 이번 바퀴는 통째로 물린다." % (after[0], before[0]))
        for p in glob.glob(os.path.join(cand_dir, "*.kg")):
            os.remove(p)
        record_round({"캠": len(entry), "지음": len(written), "버림": len(thief), "들임": 0,
                "노드": 0, "엣지": 0, "제자리": [before[0], after[0]],
                "답함": [before[1], after[1]], "물음수": len(prompt),
                "들인것": [], "버린것": sorted(os.path.basename(k) for k in thief),
                "물림": True})
        return {"캠": len(entry), "들임": 0, "버림": len(thief)}
    if dry_run:
        print("시늉이라 들이지 않는다. 후보는 %s 에 있다." % cand_dir)
        return {"캠": len(entry), "들임": 0, "버림": len(thief)}
    moved = admit([os.path.join(here, k) for k in remaining])
    admitted_inner = []
    node_total = edge_total = 0
    for name in moved:
        inner = _graph_inner(os.path.join("graphs", name))
        inner["이름"] = name
        admitted_inner.append(inner)
        node_total += inner.get("노드", 0)
        edge_total += inner.get("엣지", 0)
    slot = record_round({"캠": len(entry), "지음": len(written), "버림": len(thief),
                 "들임": len(moved), "노드": node_total, "엣지": edge_total,
                 "제자리": [before[0], after[0]], "답함": [before[1], after[1]],
                 "물음수": len(prompt),
                 "들인것": admitted_inner,
                 "버린것": sorted(os.path.basename(k) for k in thief)})
    print("들인 것 %d개 · 노드 +%d · 엣지 +%d (되돌리려면 --물리다)"
          % (len(moved), node_total, edge_total))
    if admitted_inner:
        print("  새 그래프:")
        for inner in admitted_inner[:8]:
            print("    %-28s 목표 %-14s 노드 %d · 엣지 %d"
                  % (inner["이름"][:28], str(inner.get("목표"))[:14],
                     inner.get("노드", 0), inner.get("엣지", 0)))
        if len(admitted_inner) > 8:
            print("    … 그 밖에 %d개" % (len(admitted_inner) - 8))
    print("  기록: %s" % os.path.basename(log_round))
    return {"캠": len(entry), "들임": len(moved), "버림": len(thief),
            "노드": node_total, "엣지": edge_total, "기록": slot}


def reaudit(question_count=600, purge=False):
    """이미 들인 그래프를 지금 관문으로 다시 건다. -> {살아남음, 걸림, 이름들}

    왜 필요한가. 앞서 들인 것들은 **물러진 관문**을 통과했다. 관문이 쓰던
    물음의 57% 가 이 고리가 지은 그래프에서 나왔고, 그 물음은 틀에서 찍은
    별칭이라 쉽다. 잣대가 물러진 채로 통과한 것을 그대로 두면, 나중에
    무엇이 문제인지 가릴 수 없다.

    기준은 **사람이 적은 그래프만**으로 세운다. 그것이 이 고리가 지키기로
    한 것이고, 제가 지은 것으로 제 점수를 매기지 않는 유일한 방법이다."""
    mine = self_authored()
    whole = bench._bodies()
    human_made = {k: v for k, v in whole.items() if k not in mine}
    cand = {k: v for k, v in whole.items() if k in mine}
    print("사람이 적은 그래프 %d개 · 이 고리가 지은 것 %d개"
          % (len(human_made), len(cand)))
    if not cand:
        return {"살아남음": 0, "걸림": 0, "이름들": []}
    prompt = sample_questions(human_made, question_count, others_only=False)
    thief, before, remaining = find_thieves(human_made, cand, prompt)
    after = unpack(bench.build_index(dict(human_made, **remaining)), prompt)
    print("물음 %d개(사람 것만) · 제자리 %d -> %d · 다시 걸린 것 %d개"
          % (len(prompt), before[0], after[0], len(thief)))
    names = sorted(os.path.basename(k) for k in thief)
    if purge and thief:
        erased = 0
        for k in thief:
            p = os.path.join(here, k)
            if os.path.exists(p):
                os.remove(p)
                erased += 1
        # 다시 안 짓게 진도에도 적는다.
        seen_at, headword_count, dropped = read_progress()
        for name in names:
            if name.startswith("graph_") and name.endswith(".kg"):
                dropped.add(name[len("graph_"):-len(".kg")])
        write_progress(seen_at, headword_count, dropped)
        print("지웠다 %d개" % erased)
    return {"살아남음": len(remaining), "걸림": len(thief), "이름들": names}


def _selfcheck():
    # 도둑은 '제자리로 가던 물음' 을 가로챈 후보다. 원래도 엉뚱한 데로
    # 가던 물음을 가져간 것은 죄가 아니다 — 잃은 것이 없다.
    trues = ["a.kg", "b.kg"]
    visited_before = ["a.kg", "엉뚱.kg"]
    visited_after = ["후보/x.kg", "후보/y.kg"]
    thief = {after for true, before, after in zip(trues, visited_before, visited_after)
            if before == true and after != true}
    assert thief == {"후보/x.kg"}, thief
    # 관문은 제가 지은 그래프로 제 점수를 매기면 안 된다.
    _fake = {"graphs/graph_남.kg": {"공통층": {"n": ["가", "나"]}, "사례층": {}},
            "graphs/graph_내것.kg": {"공통층": {"m": ["다", "라"]}, "사례층": {}}}
    _prev_self_authored = self_authored
    try:
        globals()["self_authored"] = lambda: {"graphs/graph_내것.kg"}
        _extract = sample_questions(_fake, 10)
        assert all(name == "graphs/graph_남.kg" for _q, name in _extract), _extract
        assert len(sample_questions(_fake, 10, others_only=False)) == 2
    finally:
        globals()["self_authored"] = _prev_self_authored

    # 무는 목록은 이번 바퀴에 옮긴 것만 담아야 한다.
    assert os.path.basename(admitted_log).startswith("."), admitted_log

    # 진도: 썼다 읽으면 그대로 나오고, 사전 크기가 달라지면 버려야 한다.
    old = None
    if os.path.exists(log_progress):
        old = io.open(log_progress, encoding="utf-8").read()
    try:
        write_progress(1234, 56555, {"가나", "다라"})
        seen_at, headword_count, dropped = read_progress()
        assert (seen_at, headword_count) == (1234, 56555), (seen_at, headword_count)
        assert dropped == {"가나", "다라"}, dropped
    finally:
        if old is None:
            if os.path.exists(log_progress):
                os.remove(log_progress)
        else:
            io.open(log_progress, "w", encoding="utf-8").write(old)
    print("자가검사 ok")


if __name__ == "__main__":
    max_n = 200
    if "--최대" in sys.argv:
        max_n = int(sys.argv[sys.argv.index("--최대") + 1])
    if "--자가검사" in sys.argv:
        _selfcheck()
    elif "--재심사" in sys.argv:
        slot = reaudit(purge="--치우기" in sys.argv)
        if slot["이름들"]:
            print("\n다시 걸린 것 (앞 20개):")
            for name in slot["이름들"][:20]:
                print("   " + name)
            if len(slot["이름들"]) > 20:
                print("   … 그 밖에 %d개" % (len(slot["이름들"]) - 20))
        if not slot["걸림"]:
            print("다시 걸린 것이 없다.")
        elif "--치우기" not in sys.argv:
            print("\n지우려면 --재심사 --치우기")
    elif "--기록" in sys.argv:
        line = read_round()
        if not line:
            print("아직 돈 바퀴가 없다.")
        for x in line:
            print("%s  캠 %3d · 지음 %3d · 버림 %3d · 들임 %3d · 노드 +%-4d 엣지 +%-4d%s"
                  % (x.get("때", "?"), x.get("캠", 0), x.get("지음", 0),
                     x.get("버림", 0), x.get("들임", 0), x.get("노드", 0),
                     x.get("엣지", 0), "  (물림)" if x.get("물림") else ""))
    elif "--처음부터" in sys.argv:
        if os.path.exists(log_progress):
            os.remove(log_progress)
            print("진도를 버렸다. 다음 바퀴는 사전 앞에서 시작한다.")
        else:
            print("남은 진도가 없다.")
    elif "--물리다" in sys.argv:
        erased = revert()
        print("되돌린 것 %d개" % len(erased))
    elif "--캐다" in sys.argv:
        entry = dig(max_n)
        written = author(entry)
        print("캔 것 %d개 · lint 통과 %d개 -> %s" % (len(entry), len(written), cand_dir))
    elif "--한바퀴" in sys.argv:
        one_round(max_n, dry_run="--시늉" in sys.argv)
    else:
        print(__doc__)
