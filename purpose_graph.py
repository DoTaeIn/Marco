# -*- coding: utf-8 -*-
"""정의문 한 줄 -> '목적이 수단을 제약하는' 그래프.

무엇을 푸나. `세차하러 가는데 걸어서 5분 차로 10분이면 차를 타야 하나` 는
시간 비교처럼 생겼지만 아니다. 세차의 대상이 차라서, 걸어가면 목적 자체가
무너진다. 시간은 미끼다.

엔진은 이 추론을 스스로 못 한다 — `증거 -> 사실 -> 요건 -> 목표` 에는
'이 행동의 목적이 무엇인가' 를 두는 자리가 없다. 지금까지는 사람이 그래프에
손으로 적는 수밖에 없었다.

이 파일은 그 한 줄을 **원문에서** 가져온다.

    "세차(洗車)는 자동차를 씻는 일이다"        <- 위키백과 첫 문장
        -> build.대상뽑기 -> ('자동차', '씻')
        -> 아래 짓기() -> .kg

낱말은 전부 원문 것이고, 공리 노드에 `@출처` 가 붙어 어느 문장에서 왔는지
남는다. 지어낸 것이 아니라 옮긴 것이다.

관계 이름(`갖춤`·`함의함`·`걸림돌`)은 엔진에 안 박혀 있다. 이 그래프가
머리말로 선언한다 — 법정 어휘(증명/충족/부정)를 한 개도 쓰지 않는다.

    python purpose_graph.py "세차(洗車)는 자동차를 씻는 일이다" --out graphs/graph_세차.kg
"""
from __future__ import annotations

import re
import sys

from build import extract_target

# 도식마다 다른 것은 **말버릇뿐**이다. 논증 뼈대는 셋 다 같다 —
# 대상이 그 자리에 있어야 목적이 서고, 없으면 무너진다. 구조가 다르다고
# 지어내지 않는다. 재본 것은 '대상이 물건이냐 장소냐 사람이냐' 하나다.
# 예시마다 낱말({말})을 심는 이유. 이 틀로 그래프를 200개 찍어 색인에
# 넣어 보니 서로를 못 갈랐다. `양봉 는 꿀벌 을 기르는 일이라…` 라는 물음이
# **graph_대학살** 로 가서 '대학살에는사람들가필요' 로 인정됐다. 예시가
# `가지고 간다`·`걸어서 간다` 처럼 글자까지 똑같았기 때문이다 — 대상 하나만
# 다르고 나머지는 전부 공유라, 라우터가 고를 근거가 없다.
#
# 그렇다고 맨 예시를 빼면 안 된다. 짧은 물음(공백 뺀 8자 이하)은 점수를
# 거꾸로 재기 때문에 — 예시가 물음에 얼마나 덮이나 — 낱말을 붙여 길어진
# 예시는 `걸어서 간다` 같은 짧은 말에 오히려 진다. 실제로 낱말만 붙였더니
# `걸어서 간다` 가 인정에서 미지로 떨어졌다. 그래서 둘 다 둔다: 신원용
# 긴 것을 앞에, 대화 중에 쓰일 짧은 것을 뒤에.
speech_habit = {
    "물건": {"함": "가져감", "안함": "두고감", "됨": "가져갔다", "안됨": "두고 갔다", "댐": "가져간다", "안댐": "두고 간다",
             "댐예": ["{말} 하러 {대} {조} 가져간다", "{대} {조} 챙겨서 {말} 하러 간다",
                     "{대} {조} 타고 간다", "가지고 간다"],
             "안댐예": ["{대} {조} 두고 {말} 하러 간다", "{대} 없이 {말} 한다",
                      "걸어서 간다", "안 가져간다"]},
    "장소": {"함": "감", "안함": "안감", "됨": "갔다", "안됨": "가지 않았다", "댐": "간다", "안댐": "안 간다",
             "댐예": ["{말} 하러 {대} 에 간다", "{대} 까지 올라가서 {말} 한다",
                     "거기로 간다", "{대} 에 간다"],
             "안댐예": ["{대} 에 안 가고 {말} 한다", "{말} 하러 안 가고 집에 있는다",
                      "집에 있는다", "가지 않는다"]},
    "사람": {"함": "부름", "안함": "안부름", "됨": "불렀다", "안됨": "안 불렀다", "댐": "부른다", "안댐": "안 부른다",
             "댐예": ["{말} 하러 {대} {조} 부른다", "{대} 와 함께 {말} 한다",
                     "같이 간다", "{대} {조} 부른다"],
             "안댐예": ["{대} 없이 {말} 한다", "{말} 을 혼자 한다",
                      "혼자 간다", "안 부른다"]},
}

_head = re.compile(r"^\s*([가-힣A-Za-z]{2,14})\s*(?:\([^)]*\))?\s*(?:은|는|이란|란)")
# 목적이 될 수 없는 표제어. `이중적`·`위생적` 은 성질이지 하는 일이 아니라서
# '이중적함' 이라는 목표 자체가 말이 안 된다. 그런데 이런 낱말의 정의문은
# `…성질을 가지고 있는 것` 처럼 유가 '것' 이라 동작류를 그대로 통과한다.
# 표준국어대사전 표본 30개에서 틀린 10개 중 6개가 이 한 갈래였다.
_not_purpose = re.compile(r"(?:적|성|히|이|스레)$")


def build(definition, src="", phrase=None, schema="물건", index=False):
    """정의문 -> .kg 글자. 대상을 못 뽑으면 None (억지로 짓지 않는다).

    도식은 `사전뽑기.도식찾기` 가 낸 것을 넘긴다. 모르면 '물건' 으로 둔다 —
    가장 흔하고, 틀려도 말버릇만 어색할 뿐 논증은 그대로 선다.

    색인을 켜면 라우터가 이 그래프를 찾을 수 있다. 기본은 꺼둔다 — 한 줄로
    지은 그래프가 조용히 색인에 끼면 남의 물음을 가져가서 거기서 미지가
    된다(742개를 그냥 넣으니 답함이 62.3% 에서 60.0% 로 떨어졌다).
    켜는 것은 `자가저작` 의 관문을 지난 뒤여야 한다."""
    habit = speech_habit.get(schema) or speech_habit["물건"]

    def particle(phrase, batchim_particle, plain_particle):
        """'책 를' 이 아니라 '책 을'. 노드 이름은 알 수 없으니 여기서 고른다."""
        import hangul
        return hangul.pick_particle(phrase, (batchim_particle, plain_particle))
    extract = extract_target(definition)
    if not extract:
        return None
    target, action = extract
    if phrase is None:
        m = _head.match(definition)
        if not m:
            return None
        phrase = m.group(1)
    if phrase == target:                       # '차는 차를 …' 같은 것은 그래프가 안 된다
        return None
    if _not_purpose.search(phrase):
        return None
    tail = ("@" + src) if src else ""
    return f"""# {phrase} — 목적이 수단을 제약하는 그래프.
# 사람이 적은 것이 아니라 아래 원문 한 줄에서 뽑았다.
#
#     {definition}
#
# 여기서 나온 것은 '{phrase} 의 대상은 {target}' 하나뿐이다. 나머지 뼈대는 그
# 관계가 늘 같은 모양이라 이 파일이 채운다 — 대상이 있어야 목적이 선다.
역할: {phrase} 상담
목표: {phrase}함{"" if index else chr(10) + "색인: 아니오"}
임계값: 0.50 / 0.60
전진관계: 갖춤, 함의함
부정관계: 걸림돌
근거관계: 갖춤

[개념]
# 개념은 **상태**를 말한다. 사례(행동)와 같은 문장을 쓰면 매처가 둘을 못 갈라
# '자동차 를 타고 간다' 가 '자동차없음' 으로 붙는다 — 실제로 그렇게 깨졌다.
{phrase}함:      "{phrase}를 할 수 있다" | "{phrase} 가 된다"
{target}있음:   "{target} 가 그 자리에 있다" | "{target} {particle(target,"을","를")} {habit["됨"]}"
{target}없음:   "{target} 가 없다" | "{target} {particle(target,"을","를")} {habit["안됨"]}"

[공리]
# 둘째 별칭으로 `{{말}} 는 {{대상}} 을 {{동작}}는 일이라 …` 를 달았었다.
# 낱말 둘만 다르고 나머지가 전부 같은 틀이라, 그래프를 여럿 찍으면 그
# 별칭끼리 서로를 삼킨다. 원문 한 줄이면 신원이 선다.
{phrase}에는{target}가필요{tail}: "{definition}" | "{phrase} 에는 {target} 가 있어야 한다"

[사례]
*{target}{habit["함"]}: {" | ".join('"%s"' % x.format(**{"대": target, "조": particle(target, "을", "를"), "말": phrase}) for x in habit["댐예"])}
*{target}{habit["안함"]}: {" | ".join('"%s"' % x.format(**{"대": target, "조": particle(target, "을", "를"), "말": phrase}) for x in habit["안댐예"])}

[무관]
# 걸리는 시간은 이 목표에 기여하지 않는다. 사례층에 두면 목표에 닿지 못해
# lint 가 잡는데, 그것이 곧 '미끼' 라는 뜻이다.
_시간비교: "걸어서 5분 차로 10분" | "걷는 게 더 빠르다" | "그게 더 오래 걸린다"

[논증]
{target}{habit["함"]} -갖춤-> {target}있음
{target}{habit["안함"]} -갖춤-> {target}없음
{target}없음 -걸림돌-> {target}있음
{target}있음 -함의함-> {phrase}함
{phrase}에는{target}가필요 -함의함-> {phrase}함

[대사]
B2: 그건 {phrase} 를 할 수 있느냐와 상관이 없다.
B2_강등: {phrase} 를 할 수 있느냐만 다룬다.
A: 혹시 {{claim}} 말인가?
근거없음: {{claim}} 는 무엇을 보고 하는 말인가?
인정: {{ev}} 니까 {{claim}} 다.
인정_반격: {{ev}} 는 그렇다. 그런데 {{bad}} 가 걸린다.
C: {{ev}} 만으로는 {{claim}} 까지 못 간다.
B1: {{claim}} 은 알겠다. {target} {particle(target,"을","를")} {habit["댐"]} 건지를 말해야 한다.
미지: 그건 모르겠다.
공리: {{claim}}
목표주장: {phrase} 를 하려면 {target} 를 어떻게 할 건지부터 정해야 한다.
"""


def build_concurrent(phrase, roles, unit, src=""):
    """사람이 확인한 동시 역할로만 별도 논증 뼈대를 만든다.

    역할·단위는 텍스트에서 추출하지 않는다. 빈 값/한 역할은 동시 구조가
    아니므로 거절한다. 이 함수는 시드 전파 뒤에도 같은 원본 시드를 받아야
    하며, 전파된 낱말이 역할을 덮어쓰지 못한다.
    """
    roles = tuple(dict.fromkeys(str(x).strip() for x in roles if str(x).strip()))
    if len(roles) < 2 or not str(unit).strip() or not str(phrase).strip():
        return None
    tail = ("@" + src) if src else ""
    case = "\n".join("*%s참여: \"%s 가 %s 에 참여한다\"" % (r, r, unit) for r in roles)
    argument = "\n".join("%s참여 -동시참여-> %s동시" % (r, phrase) for r in roles)
    return f'''# {phrase} — 사람이 확인한 동시작업 도식.
# 역할과 단위는 원문 추출값이 아니다. 아래 출처의 사람이 확인한 시드다.
역할: {phrase} 동시작업
목표: {phrase}성립
색인: 아니오
임계값: 0.50 / 0.60
전진관계: 동시참여, 함의함
부정관계: 걸림돌
근거관계: 동시참여

[개념]
{phrase}동시: "{unit} 에 모든 역할이 함께 참여한 상태"
{phrase}성립: "{phrase} 가 성립한다"

[공리]
{phrase}동시조건{tail}: "{phrase} 는 {', '.join(roles)} 가 {unit} 에 함께 참여해야 한다"

[사례]
{case}

[논증]
{argument}
{phrase}동시 -함의함-> {phrase}성립
{phrase}동시조건 -함의함-> {phrase}성립

[대사]
B2: 그건 {phrase} 의 동시 참여와 상관이 없다.
B2_강등: {phrase} 의 동시 참여만 다룬다.
A: 혹시 {{claim}} 말인가?
근거없음: {{claim}} 는 어떤 역할의 참여를 보고 하는 말인가?
인정: {{ev}} 니까 {{claim}} 다.
인정_반격: {{ev}} 는 그렇다. 그런데 {{bad}} 가 걸린다.
C: {{ev}} 만으로는 {{claim}} 까지 못 간다.
B1: {{claim}} 을 위해 어떤 역할이 {unit} 에 참여하는지 말해야 한다.
미지: 그건 모르겠다.
공리: {{claim}}
목표주장: {phrase} 를 하려면 역할들이 {unit} 에 함께 참여해야 한다.
'''


def _selfcheck():
    import engine
    txt = build("세차는 자동차를 씻는 일이다", src="위키백과 세차")
    assert txt and "자동차" in txt, txt
    # 성질을 나타내는 말은 목적이 될 수 없다. `이중적함` 은 목표가 아니다.
    # 그런데 그 뜻풀이는 `…성질을 가지고 있는 것` 이라 유가 '것' 이어서
    # 대상뽑기를 그냥 통과한다. 표제어에서 막는 수밖에 없다.
    assert build("이중적은 서로 다른 두 가지의 성질을 가지고 있는 것.") is None
    assert build("위생적은 건강에 도움이 되도록 조건을 갖춘 것.") is None
    path = "graphs/graph_목적_자가검사.kg"
    open(engine._abs(path), "w", encoding="utf-8").write(txt)
    g = engine.load(path)

    # 관계 어휘를 그래프가 정한다 — 법정 어휘가 한 개도 없다
    assert engine.forward_rels(g) == ("갖춤", "함의함"), engine.forward_rels(g)
    assert engine.negative_rels(g) == ("걸림돌",) and engine.grounds_rels(g) == ("갖춤",)
    assert engine.lint(g) == [], engine.lint(g)
    assert len(g["공리"]) == 1 and "자동차" in g["공리"][0], g["공리"]
    # 출처가 남는다. 지어낸 것이 아니라 옮긴 것이라는 표시다.
    assert g.get("출처", {}).get(g["공리"][0]) == "위키백과 세차", g.get("출처")

    # 시간 비교는 이 목표와 상관이 없다 -> 기각
    assert engine.judge(g, "걷는 게 더 빠르다")[0] in ("B2", "미지"), \
        engine.judge(g, "걷는 게 더 빠르다")
    # 두고 가면 목적이 무너진다 -> 반격이 뜬다
    tag, _ = engine.judge(g, "걸어서 간다")
    assert tag == "인정", tag
    assert "걸린다" in engine.Session(g).reply("걸어서 간다"), engine.Session(g).reply("걸어서 간다")
    # 가져가면 요건이 선다
    assert engine.judge(g, "자동차 를 타고 간다")[0] == "인정"
    assert "있음" in engine.Session(g).reply("자동차 를 타고 간다")

    # 동작이 아닌 정의문에는 억지로 그래프를 만들지 않는다
    assert build("서울은 대한민국의 수도이다") is None
    # 동시작업은 수동 역할 시드 없이는 만들지 않는다. 기존 보유 뼈대와 달리
    # 모든 역할의 동시 참여가 하나의 상태를 세운다.
    is_verb_hour_text = build_concurrent("교향악단", ("지휘자", "현악연주자", "관악연주자"), "한 악장", "사람 확인")
    assert is_verb_hour_text and "동시참여" in is_verb_hour_text
    open(engine._abs("graphs/graph_동시_자가검사.kg"), "w", encoding="utf-8").write(is_verb_hour_text)
    is_verb_hour_g = engine.load("graphs/graph_동시_자가검사.kg")
    assert engine.lint(is_verb_hour_g) == [], engine.lint(is_verb_hour_g)
    assert engine.judge(is_verb_hour_g, "지휘자 가 한 악장 에 참여한다")[0] == "인정"
    assert build_concurrent("교향악단", ("지휘자",), "한 악장") is None
    print("selfcheck ok")


if __name__ == "__main__":
    if "--check" in sys.argv:
        _selfcheck()
    elif len(sys.argv) > 1:
        argv = [a for a in sys.argv[1:] if not a.startswith("--")]
        out_edges = (sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else None)
        src = (sys.argv[sys.argv.index("--출처") + 1] if "--출처" in sys.argv else "")
        txt = build(argv[0], src=src)
        if not txt:
            print("대상을 못 뽑았다. '무엇을 …하는 일이다' 꼴이라야 한다.")
            sys.exit(1)
        if out_edges:
            open(out_edges, "w", encoding="utf-8").write(txt)
            print("-> %s" % out_edges)
        else:
            print(txt)
    else:
        print(__doc__)
