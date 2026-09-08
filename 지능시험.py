# -*- coding: utf-8 -*-
"""능력별로 갈라 재는 지능 시험. 한 숫자로 뭉뚱그리지 않는다.

    KG_ENCODER=문자 python 지능시험.py
    python 지능시험.py                # 신경 인코더

왜 갈라 재나. 합계 하나는 거짓말을 한다. 처음 돌렸을 때 97% 가 나왔는데,
'바꿔 말하기' 를 같은 노드의 별칭끼리 재고 있었기 때문이다. 사람이 손으로
적은 별칭은 서로 글자가 겹쳐서(‘CCTV’/‘시시티비’) 쉬운 문제다. 손으로 다시
쓴 말로 바꿔 재니 43% 였다. 그래서 대조군(별칭 그대로)을 같이 둔다 —
대조군이 100% 가 아니면 시험틀이 틀린 것이지 엔진이 틀린 것이 아니다.

잰 값 (그래프 186개 기준):

                    문자(기본)   신경
    1 환각 안 함        100.0%    74.1%
    2 증거 추론         100.0%   100.0%
    3 함정 물음          50.0%    75.0%
    4 대조(별칭그대로)    100.0%   100.0%
    5 바꿔 말하기         42.9%    71.4%
    6 의미 추론          40.0%    40.0%
    7 여러 턴          100.0%   100.0%
    ----------------------------------
      합계             81.9%    79.2%

두 인코더가 서로 반대로 못한다. 문자는 밖을 하나도 안 물지만(27/27) 바꿔
말한 것을 절반도 못 알아듣고, 신경은 바꿔 말한 것을 더 알아듣지만 밖
질문 7개를 문다. 합계가 비슷하다고 같은 물건이 아니다.
"""
import sys, os, json, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("KG_ENCODER", "문자")
import engine
from 진행 import 막대

결과 = collections.OrderedDict()

def 재기(이름, 항목들, 판단):
    맞 = 0; 실패 = []
    for x in 막대(항목들, 이름):
        try:
            ok, 메모 = 판단(x)
        except Exception as e:
            ok, 메모 = False, "%s: %s" % (type(e).__name__, str(e)[:40])
        맞 += bool(ok)
        if not ok:
            실패.append((x if isinstance(x, str) else str(x)[:50], 메모))
    결과[이름] = (맞, len(항목들), 실패)
    return 맞, len(항목들)

# 1. 환각 안 하기 — 갈 곳 없는 물음에 아는 척하지 않는가
밖 = json.load(open("data/benchmarks/라우팅_밖.json", encoding="utf-8"))
ix = engine.그래프색인()
def _밖(q):
    골, _, _ = engine.그래프고르기(q, ix)
    if not 골:
        return True, "거절"
    t = engine.judge(engine.그래프불러오기(골), q)[0]
    return t in ("미지", "B2"), "%s -> %s" % (골.split("/")[-1], t)
재기("1. 환각 안 함", 밖, _밖)

# 2. 증거 기반 판정 — 판례 회귀
회귀 = engine.회귀()
재기("2. 증거 추론", 회귀, lambda x: (x["ok"], x.get("actual")))

# 3. 함정 물음 — 겉만 보면 딴 답이 나오는 것들
함정 = [
    ("세차하러 가는데 걸어서 5분 차로 10분이면 뭐 타고 가지",
     lambda t: "자동차" in t or "차" in t, "대상이 차라 걸어가면 목적이 무너진다"),
    ("2등 선수를 추월했으면 나는 몇 등이야", lambda t: "2" in t, "1등이 아니라 2등"),
    ("반쪽짜리 구멍을 파려면 얼마나 걸려", lambda t: any(w in t for w in ("모르", "없", "아닙", "성립")),
     "반쪽 구멍은 없다 — 전제가 틀렸다"),
    ("바람의 기분은 몇 점일까", lambda t: any(w in t for w in ("모르", "없", "아닙")),
     "답이 없는 물음"),
]
def _함정(x):
    q, 검사, _왜 = x
    _, tag, 말 = engine.안내(q)
    return 검사(말 or ""), "%s / %s" % (tag, (말 or "")[:34])
재기("3. 함정 물음", 함정, _함정)

# 4. 바꿔 말하기 — 별칭 글자를 안 쓰고 다시 쓴 말을 알아듣는가
#    처음엔 같은 노드의 별칭끼리 재서 98.3% 가 나왔는데, 손으로 쓴 별칭은
#    서로 글자가 겹쳐서 쉬운 문제였다. 제 자랑이라 버리고 손으로 다시 썼다.
바꿔 = [
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
def _바꿔(x):
    p, n, 말 = x
    g = engine.그래프불러오기(p)
    찾, 점 = engine.match(말, list(g["공통층"]) + list(g["사례층"]), g)
    return 찾 == n, "%s (%.2f) 기대 %s" % (찾, 점, n)
def _대조(x):
    p, n, _ = x
    g = engine.그래프불러오기(p)
    말 = list(g["사례층"].get(n) or g["공통층"].get(n))[0]
    찾, _점 = engine.match(말, list(g["공통층"]) + list(g["사례층"]), g)
    return 찾 == n, 찾
재기("4. 대조(별칭그대로)", 바꿔, _대조)
재기("5. 바꿔 말하기", 바꿔, _바꿔)

# 6. 의미 추론 — 겉으로는 산수처럼 보이는 것들
_뜻 = json.load(open("data/benchmarks/semantic_reasoning.json", encoding="utf-8"))
def _뜻판단(x):
    _, _t, 말 = engine.안내(x["input"])
    답 = (x.get("answer") or "").strip()
    말 = 말 or ""
    if not 답:                          # 답이 없어야 맞는 물음(전제 오류·모름)
        return any(w in 말 for w in ("모르", "없", "아닙", "상관")), 말[:34]
    핵 = 답.replace("입니다.", "").replace("칸", "").strip()
    return 핵 in 말, "%s / 기대 %s" % (말[:28], 답)
재기("6. 의미 추론", _뜻["held_out"], _뜻판단)

# 5. 여러 턴 — 값을 나르고 결론까지 가는가
def _여러턴(x):
    파일, 말들, 기대 = x
    s = engine.세션(engine.load(파일))
    r = None
    for t in 말들:
        r = s.말하기(t)
    return r[2] == 기대, "%s / %s" % (r[2], s.현황())
여러턴 = [("graphs/graph.kg",
          ["압수된 흉기를 보십시오, 강도가 흉기를 들고 있었습니다",
           "현장 사진을 보면 출입문을 막고 있어서 나갈 수가 없었습니다",
           "목격자 진술대로 돈을 내놓으라고 협박했습니다",
           "진단서를 보면 피고인이 다쳤습니다",
           "CCTV 영상을 보면 강도가 흉기를 들고 있었습니다"], "승"),
         ("graphs/graph.kg",
          ["CCTV 영상을 보면 강도가 흉기를 들고 있었습니다",
           "CCTV 보면 피고인이 의자를 먼저 집어 들었죠"], "패")]
재기("7. 여러 턴", 여러턴, _여러턴)

print()
print("=" * 62)
전맞 = 전총 = 0
for 이름, (맞, 총, 실패) in 결과.items():
    전맞 += 맞; 전총 += 총
    print("%-16s %3d/%-3d  %5.1f%%" % (이름, 맞, 총, 100*맞/총 if 총 else 0))
print("-" * 62)
print("%-16s %3d/%-3d  %5.1f%%" % ("합계", 전맞, 전총, 100*전맞/전총))
print("=" * 62)
for 이름, (맞, 총, 실패) in 결과.items():
    if 실패:
        print("\n[%s] 틀린 것 %d개 중 앞 5개" % (이름, len(실패)))
        for q, 메모 in 실패[:5]:
            print("   %-44s %s" % (str(q)[:44], 메모))
