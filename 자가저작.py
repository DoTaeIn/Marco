# -*- coding: utf-8 -*-
"""사전 한 줄에서 그래프를 짓고, **있던 답을 해치지 않는 것만** 들인다.

    python 자가저작.py --캐다 --최대 200    # 후보만 짓는다 (graphs/후보/)
    python 자가저작.py --한바퀴 --최대 200   # 짓고 · 거르고 · 들인다
    python 자가저작.py --물리다             # 지난 바퀴에 들인 것을 되돌린다
    python 자가저작.py --기록               # 지난 바퀴들이 무엇을 바꿨나
    python 자가저작.py --처음부터           # 진도를 버리고 사전 앞에서 다시
    python 자가저작.py --자가검사

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

여기 = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, 여기)
os.environ.setdefault("KG_ENCODER", "문자")

import engine                                    # noqa: E402
import 목적그래프                                  # noqa: E402
import routing_benchmark as 재기틀                 # noqa: E402
from 진행 import 막대                             # noqa: E402

후보터 = os.path.join(여기, "graphs", "후보")
들인기록 = os.path.join(후보터, ".들인것.json")
버린기록 = os.path.join(후보터, ".버린것.json")
진도기록 = os.path.join(후보터, ".진도.json")
바퀴기록 = os.path.join(여기, "자가학습기록.jsonl")


def _그래프속(경로):
    """들인 그래프에서 무엇이 늘었는지 센다. -> {목표, 노드, 엣지, 증거, 출처}

    `색인용읽기` 가 아니라 `load` 를 쓴다. 가벼운 쪽은 증거를 안 채워서
    무엇을 세든 증거가 0으로 나갔다 — 기록에 남는 거짓말이 된다."""
    try:
        g = engine.load(경로)
    except Exception:
        return {}
    노드 = len(g.get("공통층") or {}) + len(g.get("사례층") or {})
    return {"목표": g.get("목표"), "노드": 노드,
            "엣지": len(g.get("엣지") or ()),
            "증거": len(g.get("증거") or ()),
            "출처": next(iter((g.get("출처") or {}).values()), "")}


def 바퀴적기(칸):
    """한 바퀴가 무엇을 바꿨는지 한 줄로 남긴다. UI 가 이걸 읽는다."""
    칸 = dict(칸, 때=__import__("datetime").datetime.now().isoformat(timespec="seconds"))
    with io.open(바퀴기록, "a", encoding="utf-8") as f:
        f.write(json.dumps(칸, ensure_ascii=False) + "\n")
    return 칸


def 바퀴읽기(최근=50):
    """지난 바퀴들. 새것이 뒤."""
    if not os.path.exists(바퀴기록):
        return []
    줄 = []
    for 줄글 in io.open(바퀴기록, encoding="utf-8"):
        try:
            줄.append(json.loads(줄글))
        except Exception:
            pass
    return 줄[-최근:]


def 진도읽기():
    """어디까지 캤나. 없으면 처음부터.

    이게 없으면 배경에서 돌릴 때마다 사전 앞부분을 다시 훑는다. 앞부분은
    이미 그래프가 있거나 이미 걸러진 낱말이라, 한 바퀴가 통째로 헛돈다."""
    try:
        칸 = json.load(io.open(진도기록, encoding="utf-8"))
        return int(칸.get("본데까지", 0)), int(칸.get("표제수", 0)), set(칸.get("버린말", ()))
    except Exception:
        return 0, 0, set()


def 진도쓰기(본데까지, 표제수, 버린말):
    os.makedirs(후보터, exist_ok=True)
    io.open(진도기록, "w", encoding="utf-8").write(json.dumps(
        {"본데까지": 본데까지, "표제수": 표제수,
         "버린말": sorted(버린말)}, ensure_ascii=False, indent=1))


def 아는낱말():
    """이미 그래프가 있는 낱말. 같은 것을 또 짓지 않는다."""
    본 = set()
    for p in glob.glob(os.path.join(여기, "graphs", "*.kg")):
        이름 = os.path.basename(p)[len("graph_"):-len(".kg")]
        본.add(이름.split("_")[0])
    return 본


def 캐다(최대=200, 폴더="data/사전", 이어서=True):
    """사전에서 그래프가 될 만한 항목을 캔다. -> [{말, 뜻, 도식}]

    지난번에 멈춘 자리에서 잇는다. 사전 56,555 표제 중 그래프가 되는 것은
    746개(1.3%)뿐이라, 처음부터 훑으면 한 바퀴의 대부분을 이미 본 낱말을
    다시 보는 데 쓴다. 끝까지 가면 처음으로 돌아온다 — 사전이 늘거나
    유형뽑기가 좋아지면 예전에 버린 것도 다시 볼 값이 있다.

    표제 수가 달라지면 진도를 버린다. 사전이 바뀐 것이라 자리 번호가
    가리키는 곳이 달라지기 때문이다."""
    import 사전뽑기
    항목 = 사전뽑기.사전읽기(os.path.join(여기, 폴더))
    본데까지, 옛표제수, 버린말 = 진도읽기() if 이어서 else (0, 0, set())
    if 옛표제수 != len(항목):
        본데까지, 버린말 = 0, set()
    if 본데까지 >= len(항목):
        본데까지, 버린말 = 0, set()      # 한 바퀴 다 돌았으면 처음으로
    이미 = 아는낱말()
    유맵, _대상맵, _동작 = 사전뽑기.사슬짓기(항목)
    나옴 = []
    _자 = 막대(총=최대, 이름="캐기")
    i = 본데까지
    while i < len(항목):
        it = 항목[i]
        i += 1
        말, 뜻 = it["말"], it["뜻"]
        if 말 in 이미 or 말 in 버린말 or "/" in 말 or " " in 말:
            continue
        if not 목적그래프.짓기(뜻, 말=말):        # 대상이 안 뽑히면 여기서 끝
            버린말.add(말)
            continue
        나옴.append({"말": 말, "뜻": 뜻,
                     "도식": 사전뽑기.도식찾기(말, 유맵) or "물건"})
        이미.add(말)
        _자.밀기()
        if len(나옴) >= 최대:
            break
    _자.닫기()
    if 이어서:
        진도쓰기(i, len(항목), 버린말)
    return 나옴


def 짓다(항목들, 난=None):
    """후보를 graphs/후보/ 에 쓴다. lint 를 통과한 것만. -> 쓴 파일들"""
    난 = 난 or 후보터
    os.makedirs(난, exist_ok=True)
    쓴것 = []
    for it in 막대(항목들, "짓기"):
        글 = 목적그래프.짓기(it["뜻"], 출처="표준국어대사전",
                          말=it["말"], 도식=it["도식"], 색인=True)
        if not 글:
            continue
        p = os.path.join(난, "graph_%s.kg" % it["말"])
        io.open(p, "w", encoding="utf-8").write(글)
        try:
            if engine.lint(engine.load(p)):
                os.remove(p)
                continue
        except Exception:
            os.remove(p)
            continue
        쓴것.append(p)
    return 쓴것


def 물음뽑기(원본, 개수=600, 씨=7):
    """기존 그래프에서 '이미 답하던 물음' 을 뽑는다. 관문의 잣대다."""
    물음 = []
    for 이름, g in 원본.items():
        if 이름.startswith("cases/"):
            continue
        for 층 in ("공통층", "사례층"):
            for _n, 말 in g.get(층, {}).items():
                if len(말) >= 2:
                    물음.append((list(말)[-1], 이름))
    random.Random(씨).shuffle(물음)
    return 물음[:개수]


def 풀기(ix, 물음):
    """-> (제자리, 답함, 물음마다 (간곳, 답했나, 점수))"""
    제자리 = 답함 = 0
    간곳 = []
    for q, 참 in 막대(물음, "풀기"):
        골, 점, _ = engine.그래프고르기(q, ix)
        제자리 += (골 == 참)
        답 = False
        if 골:
            try:
                답 = engine.judge(engine.그래프불러오기(골), q)[0] != "미지"
            except Exception:
                답 = False
        답함 += 답
        간곳.append((골, 답, 점))
    return 제자리, 답함, 간곳


def 도둑찾기(원본, 후보, 물음, 전=None):
    """제자리로 가던 물음을 가로챌 후보를 **전부** 찾는다.

    -> (범인집합, 전, 남은후보)

    후보를 하나씩 넣어 보면 후보 수만큼 벤치마크를 돌려야 한다(200번).
    그럴 필요가 없다. 라우터는 그래프마다 점수를 따로 매기고 가장 높은
    것을 고르므로, **후보만 넣은 색인**에서 최고점을 받아 원본에서의
    참 그래프 점수와 견주면 된다. 후보가 더 높으면 그 물음은 뺏긴다.

    그걸 한 번만 해서는 모자란다. 범인을 빼면 그 물음을 다음 후보가
    가져가기 때문이다 — 첫 회차에는 앞 후보에 가려 죄가 안 보였을 뿐이다.
    실제로 한 번만 걸렀더니 제자리가 230 에서 228 로만 돌아왔고, 회차마다
    한 명씩 잡히며 여섯 바퀴를 돌아도 안 끝났다. 그래서 다툼이 붙은
    물음만 추려 아무도 못 이길 때까지 돈다. 그 물음은 수십 개뿐이라
    회차가 늘어도 싸다."""
    전 = 전 or 풀기(재기틀.색인짓기(원본), 물음)
    다툼 = [(i, 물음[i][0], 전[2][i][2]) for i in range(len(물음))
            if 전[2][i][0] == 물음[i][1]]        # 원래 제자리로 가던 것만
    남은, 범인 = dict(후보), set()
    while 남은:
        ix후 = 재기틀.색인짓기(남은)
        이번 = set()
        for _i, q, 원점 in 다툼:
            골, 점, _ = engine.그래프고르기(q, ix후)
            if 골 and 점 >= 원점:
                이번.add(골)
        if not 이번:
            break
        범인 |= 이번
        남은 = {k: v for k, v in 남은.items() if k not in 이번}
    return 범인, 전, 남은


def 들이다(살아남은):
    """후보를 graphs/ 로 옮기고 무엇을 옮겼는지 남긴다."""
    옮김 = []
    for p in 살아남은:
        대상 = os.path.join(여기, "graphs", os.path.basename(p))
        if os.path.exists(대상):            # 사람이 적은 것을 덮지 않는다
            continue
        shutil.move(p, 대상)
        옮김.append(os.path.basename(대상))
    io.open(들인기록, "w", encoding="utf-8").write(
        json.dumps(옮김, ensure_ascii=False, indent=1))
    return 옮김


def 물리다():
    """지난 바퀴에 들인 것만 지운다. 사람이 적은 것은 목록에 없다."""
    if not os.path.exists(들인기록):
        return []
    이름들 = json.load(io.open(들인기록, encoding="utf-8"))
    지움 = []
    for 이름 in 이름들:
        p = os.path.join(여기, "graphs", 이름)
        if os.path.exists(p):
            os.remove(p)
            지움.append(이름)
    os.remove(들인기록)
    # 판정하면서 그래프 옆에 .미지.log 가 생긴다. 그래프를 무르면 그것도
    # 같이 치운다 — 안 그러면 없는 그래프의 로그만 후보터에 쌓인다.
    for p in glob.glob(os.path.join(후보터, "*.미지.log")):
        os.remove(p)
    return 지움


def 한바퀴(최대=200, 물음수=600, 시늉=False):
    항목 = 캐다(최대)
    print("캔 것 %d개" % len(항목))
    if not 항목:
        return {"캠": 0, "들임": 0}
    쓴것 = 짓다(항목)
    print("lint 통과 %d개" % len(쓴것))
    원본 = 재기틀._본문들()
    후보 = {}
    for p in 쓴것:
        try:
            후보["graphs/후보/" + os.path.basename(p)] = engine.색인용읽기(p)
        except Exception:
            pass
    물음 = 물음뽑기(원본, 물음수)
    범인, 전, 남은 = 도둑찾기(원본, 후보, 물음)
    후 = 풀기(재기틀.색인짓기(dict(원본, **남은)), 물음)
    print("물음 %d개 · 제자리 %d -> %d · 답함 %d -> %d · 표를 뺏어 버린 후보 %d개"
          % (len(물음), 전[0], 후[0], 전[1], 후[1], len(범인)))
    io.open(버린기록, "w", encoding="utf-8").write(
        json.dumps(sorted(범인), ensure_ascii=False, indent=1))
    # 도둑도 진도에 적어 둔다. 안 적으면 다음 바퀴에 같은 낱말을 또 지어
    # 또 거른다 — 짓는 값이 매번 그대로 든다.
    if 범인:
        _본데, _표제수, _버린 = 진도읽기()
        for k in 범인:
            이름 = os.path.basename(k)
            if 이름.startswith("graph_") and 이름.endswith(".kg"):
                _버린.add(이름[len("graph_"):-len(".kg")])
        진도쓰기(_본데, _표제수, _버린)
    for k in 범인:
        p = os.path.join(여기, k)
        if os.path.exists(p):
            os.remove(p)
    if 후[0] < 전[0]:
        print("아직 손해다(제자리 %d < %d). 이번 바퀴는 통째로 물린다." % (후[0], 전[0]))
        for p in glob.glob(os.path.join(후보터, "*.kg")):
            os.remove(p)
        바퀴적기({"캠": len(항목), "지음": len(쓴것), "버림": len(범인), "들임": 0,
                "노드": 0, "엣지": 0, "제자리": [전[0], 후[0]],
                "답함": [전[1], 후[1]], "물음수": len(물음),
                "들인것": [], "버린것": sorted(os.path.basename(k) for k in 범인),
                "물림": True})
        return {"캠": len(항목), "들임": 0, "버림": len(범인)}
    if 시늉:
        print("시늉이라 들이지 않는다. 후보는 %s 에 있다." % 후보터)
        return {"캠": len(항목), "들임": 0, "버림": len(범인)}
    옮김 = 들이다([os.path.join(여기, k) for k in 남은])
    들인속 = []
    노드합 = 엣지합 = 0
    for 이름 in 옮김:
        속 = _그래프속(os.path.join("graphs", 이름))
        속["이름"] = 이름
        들인속.append(속)
        노드합 += 속.get("노드", 0)
        엣지합 += 속.get("엣지", 0)
    칸 = 바퀴적기({"캠": len(항목), "지음": len(쓴것), "버림": len(범인),
                 "들임": len(옮김), "노드": 노드합, "엣지": 엣지합,
                 "제자리": [전[0], 후[0]], "답함": [전[1], 후[1]],
                 "물음수": len(물음),
                 "들인것": 들인속,
                 "버린것": sorted(os.path.basename(k) for k in 범인)})
    print("들인 것 %d개 · 노드 +%d · 엣지 +%d (되돌리려면 --물리다)"
          % (len(옮김), 노드합, 엣지합))
    if 들인속:
        print("  새 그래프:")
        for 속 in 들인속[:8]:
            print("    %-28s 목표 %-14s 노드 %d · 엣지 %d"
                  % (속["이름"][:28], str(속.get("목표"))[:14],
                     속.get("노드", 0), 속.get("엣지", 0)))
        if len(들인속) > 8:
            print("    … 그 밖에 %d개" % (len(들인속) - 8))
    print("  기록: %s" % os.path.basename(바퀴기록))
    return {"캠": len(항목), "들임": len(옮김), "버림": len(범인),
            "노드": 노드합, "엣지": 엣지합, "기록": 칸}


def _자가검사():
    # 도둑은 '제자리로 가던 물음' 을 가로챈 후보다. 원래도 엉뚱한 데로
    # 가던 물음을 가져간 것은 죄가 아니다 — 잃은 것이 없다.
    참들 = ["a.kg", "b.kg"]
    전간곳 = ["a.kg", "엉뚱.kg"]
    후간곳 = ["후보/x.kg", "후보/y.kg"]
    범인 = {후 for 참, 전, 후 in zip(참들, 전간곳, 후간곳)
            if 전 == 참 and 후 != 참}
    assert 범인 == {"후보/x.kg"}, 범인
    # 무는 목록은 이번 바퀴에 옮긴 것만 담아야 한다.
    assert os.path.basename(들인기록).startswith("."), 들인기록

    # 진도: 썼다 읽으면 그대로 나오고, 사전 크기가 달라지면 버려야 한다.
    옛것 = None
    if os.path.exists(진도기록):
        옛것 = io.open(진도기록, encoding="utf-8").read()
    try:
        진도쓰기(1234, 56555, {"가나", "다라"})
        본데, 표제수, 버린 = 진도읽기()
        assert (본데, 표제수) == (1234, 56555), (본데, 표제수)
        assert 버린 == {"가나", "다라"}, 버린
    finally:
        if 옛것 is None:
            if os.path.exists(진도기록):
                os.remove(진도기록)
        else:
            io.open(진도기록, "w", encoding="utf-8").write(옛것)
    print("자가검사 ok")


if __name__ == "__main__":
    최대 = 200
    if "--최대" in sys.argv:
        최대 = int(sys.argv[sys.argv.index("--최대") + 1])
    if "--자가검사" in sys.argv:
        _자가검사()
    elif "--기록" in sys.argv:
        줄 = 바퀴읽기()
        if not 줄:
            print("아직 돈 바퀴가 없다.")
        for x in 줄:
            print("%s  캠 %3d · 지음 %3d · 버림 %3d · 들임 %3d · 노드 +%-4d 엣지 +%-4d%s"
                  % (x.get("때", "?"), x.get("캠", 0), x.get("지음", 0),
                     x.get("버림", 0), x.get("들임", 0), x.get("노드", 0),
                     x.get("엣지", 0), "  (물림)" if x.get("물림") else ""))
    elif "--처음부터" in sys.argv:
        if os.path.exists(진도기록):
            os.remove(진도기록)
            print("진도를 버렸다. 다음 바퀴는 사전 앞에서 시작한다.")
        else:
            print("남은 진도가 없다.")
    elif "--물리다" in sys.argv:
        지움 = 물리다()
        print("되돌린 것 %d개" % len(지움))
    elif "--캐다" in sys.argv:
        항목 = 캐다(최대)
        쓴것 = 짓다(항목)
        print("캔 것 %d개 · lint 통과 %d개 -> %s" % (len(항목), len(쓴것), 후보터))
    elif "--한바퀴" in sys.argv:
        한바퀴(최대, 시늉="--시늉" in sys.argv)
    else:
        print(__doc__)
