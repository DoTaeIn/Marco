# -*- coding: utf-8 -*-
"""능력별로 갈라 재는 지능 시험. 한 숫자로 뭉뚱그리지 않는다.

    KG_ENCODER=문자 python intelligence_check.py
    python intelligence_check.py                # 신경 인코더

왜 갈라 재나. 합계 하나는 거짓말을 한다. 처음 돌렸을 때 97% 가 나왔는데,
'바꿔 말하기' 를 같은 노드의 별칭끼리 재고 있었기 때문이다. 사람이 손으로
적은 별칭은 서로 글자가 겹쳐서(‘CCTV’/‘시시티비’) 쉬운 문제다. 손으로 다시
쓴 말로 바꿔 재니 43% 였다. 그래서 대조군(별칭 그대로)을 같이 둔다 —
대조군이 100% 가 아니면 시험틀이 틀린 것이지 엔진이 틀린 것이 아니다.

그래프 수·라우터·상태 추론 경로는 계속 변한다. 위에 고정된 과거 백분율을
적어 두면 현재 코드를 잰 결과처럼 오해하게 되므로, 이 파일을 실행해 출력한
각 항목의 값만 기준으로 삼는다. 특히 1번은 후보 라우팅이 아니라 사용자가
실제로 받는 ``engine.안내()`` 결과를 재며, 6번은 답뿐 아니라 전제 오류를
검증된 거절로 구분한다.
"""
import sys, os, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("KG_ENCODER", "문자")
import engine
from progress import Bar

result = collections.OrderedDict()

def measure(name, items, decision):
    hit = 0; failure = []
    for x in Bar(items, name):
        try:
            ok, memo = decision(x)
        except Exception as e:
            ok, memo = False, "%s: %s" % (type(e).__name__, str(e)[:40])
        hit += bool(ok)
        if not ok:
            failure.append((x if isinstance(x, str) else str(x)[:50], memo))
    result[name] = (hit, len(items), failure)
    return hit, len(items)

# 1. 환각 안 하기 — 갈 곳 없는 물음에 아는 척하지 않는가
outside = json.load(open("data/benchmarks/라우팅_밖.json", encoding="utf-8"))
ix = engine.graph_index()
def _outside(q):
    # 후보 라우팅만 재면 전역 입구가 후보 그래프의 근거를 다시 확인하는
    # 안전 장치를 빼고 재게 된다. 사용자가 실제로 받는 안내() 결과로 잰다.
    pick, t, _phrase_part = engine.answer(q)
    return (pick, t) == (None, "미지"), "%s -> %s" % (pick or "거절", t)
measure("1. 환각 안 함", outside, _outside)

# 2. 증거 기반 판정 — 판례 회귀
regression = engine.regression()
measure("2. 증거 추론", regression, lambda x: (x["ok"], x.get("actual")))

# 3. 함정 물음 — 겉만 보면 딴 답이 나오는 것들
trap = [
    ("세차하러 가는데 걸어서 5분 차로 10분이면 뭐 타고 가지",
     lambda t: "자동차" in t or "차" in t, "대상이 차라 걸어가면 목적이 무너진다"),
    ("2등 선수를 추월했으면 나는 몇 등이야", lambda t: "2" in t, "1등이 아니라 2등"),
    ("반쪽짜리 구멍을 파려면 얼마나 걸려", lambda t: any(w in t for w in ("모르", "없", "아닙", "성립")),
     "반쪽 구멍은 없다 — 전제가 틀렸다"),
    ("바람의 기분은 몇 점일까", lambda t: any(w in t for w in ("모르", "없", "아닙")),
     "답이 없는 물음"),
]
def _trap(x):
    q, check, _why = x
    _, tag, phrase = engine.answer(q)
    return check(phrase or ""), "%s / %s" % (tag, (phrase or "")[:34])
measure("3. 함정 물음", trap, _trap)

# 4. 바꿔 말하기 — 별칭 글자를 안 쓰고 다시 쓴 말을 알아듣는가
#    처음엔 같은 노드의 별칭끼리 재서 98.3% 가 나왔는데, 손으로 쓴 별칭은
#    서로 글자가 겹쳐서 쉬운 문제였다. 제 자랑이라 버리고 손으로 다시 썼다.
swap = [
 ("graphs/graph.kg", "CCTV",         "방범 카메라에 찍힌 화면을 보시죠"),
 ("graphs/graph.kg", "목격자진술",     "그 자리에 있던 사람이 그렇게 말했습니다"),
 ("graphs/graph.kg", "진단서",        "병원에서 떼 온 상해 소견 서류가 있습니다"),
 ("graphs/graph_의료.kg", "심전도",    "가슴에 전극을 붙여 잰 파형을 보면"),
 ("graphs/graph_의료.kg", "트로포닌",   "피 검사에서 심장 효소 수치가 올랐습니다"),
 ("graphs/graph_의료.kg", "흉부CT",    "가슴 단층 촬영을 해 봤습니다"),
 ("graphs/graph_의료.kg", "문진기록",   "환자에게 물어본 내용을 적어 둔 것"),
 ("graphs/graph_코드리뷰.kg", "슬로우쿼리로그", "오래 걸린 질의 기록을 봤더니"),
 ("graphs/graph_코드리뷰.kg", "프로파일러",   "성능 측정 도구로 재 보니"),
 ("graphs/graph_코드리뷰.kg", "GC로그",     "가비지 컬렉터가 남긴 기록에"),
 ("graphs/graph_코드리뷰.kg", "APM트레이스",  "요청이 어디서 오래 머무는지 추적한 결과"),
 ("graphs/graph_대출.kg", "소득증빙",   "제가 얼마를 버는지 증명하는 서류입니다"),
 ("graphs/graph_대출.kg", "신용보고서",  "신용 등급을 조회한 결과입니다"),
 ("graphs/graph_대출.kg", "등기부등본",  "집 소유권이 적힌 공적 장부입니다"),
]
def _swap(x):
    p, n, phrase = x
    g = engine.load_graph(p)
    find, pt = engine.match(phrase, list(g["공통층"]) + list(g["사례층"]), g)
    return find == n, "%s (%.2f) 기대 %s" % (find, pt, n)
def _control(x):
    p, n, _ = x
    g = engine.load_graph(p)
    phrase = list(g["사례층"].get(n) or g["공통층"].get(n))[0]
    find, _pt = engine.match(phrase, list(g["공통층"]) + list(g["사례층"]), g)
    return find == n, find
measure("4. 대조(별칭그대로)", swap, _control)
measure("5. 바꿔 말하기", swap, _swap)

# 6. 의미 추론 — 겉으로는 산수처럼 보이는 것들
_meaning = json.load(open("data/benchmarks/semantic_reasoning.json", encoding="utf-8"))
def _judge_sense(x):
    _, _t, phrase = engine.answer(x["input"])
    if x.get("status") == "premise_invalid":
        return _t == "전제오류" and "전제" in (phrase or ""), "%s / %s" % (_t, (phrase or "")[:34])
    if x.get("status") == "unknown":
        return _t == "미지", "%s / %s" % (_t, (phrase or "")[:34])
    ans = (x.get("answer") or "").strip()
    phrase = phrase or ""
    if not ans:                          # 답이 없어야 맞는 물음(전제 오류·모름)
        return any(w in phrase for w in ("모르", "없", "아닙", "상관")), phrase[:34]
    core = ans.replace("입니다.", "").replace("칸", "").strip()
    return core in phrase, "%s / 기대 %s" % (phrase[:28], ans)
measure("6. 의미 추론", _meaning["held_out"], _judge_sense)

# 5. 여러 턴 — 값을 나르고 결론까지 가는가
def _multi_turn(x):
    file, phrases, expected = x
    s = engine.Session(engine.load(file))
    r = None
    for t in phrases:
        r = s.say(t)
    return r[2] == expected, "%s / %s" % (r[2], s.status())
multi_turn = [("graphs/graph.kg",
          ["압수된 흉기를 보십시오, 강도가 흉기를 들고 있었습니다",
           "현장 사진을 보면 출입문을 막고 있어서 나갈 수가 없었습니다",
           "목격자 진술대로 돈을 내놓으라고 협박했습니다",
           "진단서를 보면 피고인이 다쳤습니다",
           "CCTV 영상을 보면 강도가 흉기를 들고 있었습니다"], "성립"),
         ("graphs/graph.kg",
          ["CCTV 영상을 보면 강도가 흉기를 들고 있었습니다",
           "CCTV 보면 피고인이 의자를 먼저 집어 들었죠"], "무너짐")]
measure("7. 여러 턴", multi_turn, _multi_turn)

print()
print("=" * 62)
hit_before = before_total = 0
for name, (hit, total, failure) in result.items():
    hit_before += hit; before_total += total
    print("%-16s %3d/%-3d  %5.1f%%" % (name, hit, total, 100*hit/total if total else 0))
print("-" * 62)
print("%-16s %3d/%-3d  %5.1f%%" % ("합계", hit_before, before_total, 100*hit_before/before_total))
print("=" * 62)
for name, (hit, total, failure) in result.items():
    if failure:
        print("\n[%s] 틀린 것 %d개 중 앞 5개" % (name, len(failure)))
        for q, memo in failure[:5]:
            print("   %-44s %s" % (str(q)[:44], memo))
