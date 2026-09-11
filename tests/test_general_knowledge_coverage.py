"""원문 정의와 관계 KG가 함께 지키는 최소 일반 지식 폭."""
from pathlib import Path

import engine
from local_definitions import DefinitionLookup


def test_local_definition_coverage_across_domains():
    lookup = DefinitionLookup(Path("data/위키/정의문.jsonl"))
    questions = (
        "인공지능이 뭐야", "수학은 무엇인가", "중력이란 무엇인가요",
        "음계의 정의가 뭐야", "철학 설명해 줘", "문학이 뭐야",
        "화학에 대해 알려 줘", "DNA 뜻 알려 줘", "인공 지능이 뭐야",
        "기계학습이 뭐야", "지진이 뭐야", "생태계가 뭐야",
    )
    for question in questions:
        result = lookup.lookup(question)
        assert result and result["definition"], question


def test_relation_graph_coverage_across_domains():
    cases = (
        ("graphs/graph_수학_기초.kg", "분수가 뭐야"),
        ("graphs/graph_물리_기초.kg", "중력이 뭐야"),
        ("graphs/graph_경제_기초.kg", "GDP가 뭐야"),
        ("graphs/graph_음악_기초.kg", "음계가 뭐야"),
        ("graphs/graph_역사_기초.kg", "사료가 뭐야"),
        ("graphs/graph_네트워크_기초.kg", "DNS가 뭐야"),
        ("graphs/graph_논리_기초.kg", "반례가 뭐야"),
        ("graphs/graph_통계_기초.kg", "중앙값이 뭐야"),
        ("graphs/graph_과학방법_기초.kg", "가설이 뭐야"),
        ("graphs/graph_교육_기초.kg", "피드백이 뭐야"),
        ("graphs/graph_사회_기초.kg", "사회 규범이 뭐야"),
        ("graphs/graph_심리_기초.kg", "동기란 뭐야"),
        ("graphs/graph_영양_기초.kg", "균형 잡힌 식사가 뭐야"),
        ("graphs/graph_정치시민_기초.kg", "민주주의가 뭐야"),
        ("graphs/graph_경영_기초.kg", "마케팅이 뭐야"),
        ("graphs/graph_커뮤니케이션_기초.kg", "맥락이 뭐야"),
        ("graphs/graph_디자인_기초.kg", "사용성이 뭐야"),
        ("graphs/graph_화학_기초.kg", "화학 반응이 뭐야"),
        ("graphs/graph_농업_기초.kg", "관개가 뭐야"),
        ("graphs/graph_스포츠_기초.kg", "스포츠 기록이 뭐야"),
        ("graphs/graph_미디어리터러시_기초.kg", "정보 검증이 뭐야"),
        ("graphs/graph_교통_기초.kg", "교통 신호가 뭐야"),
        ("graphs/graph_금융_기초.kg", "인플레이션이 뭐야"),
        ("graphs/graph_경제_기초.kg", "환율이 뭐야"),
        ("graphs/graph_전기_기초.kg", "전압이 뭐야"),
        ("graphs/graph_응급안전안내.kg", "가슴이 아픈데 무슨 병이야"),
        ("graphs/graph_재난안전_기초.kg", "재난 대비가 뭐야"),
        ("graphs/graph_인간관계_기초.kg", "관계의 경계가 뭐야"),
        ("graphs/graph_식물_기초.kg", "발아가 뭐야"),
        ("graphs/graph_동물_기초.kg", "포유류가 뭐야"),
        ("graphs/graph_에너지_기초.kg", "재생에너지가 뭐야"),
        ("graphs/graph_재료_기초.kg", "고분자가 뭐야"),
        ("graphs/graph_데이터_기초.kg", "데이터베이스가 뭐야"),
        ("graphs/graph_인공지능_기초.kg", "기계학습이 뭐야"),
        ("graphs/graph_인체_기초.kg", "순환계가 뭐야"),
        ("graphs/graph_전자_기초.kg", "반도체가 뭐야"),
        ("graphs/graph_지리_기초.kg", "유역이 뭐야"),
        ("graphs/graph_국제관계_기초.kg", "조약이 뭐야"),
        ("graphs/graph_음향_기초.kg", "공명이 뭐야"),
        ("graphs/graph_공학설계_기초.kg", "시제품이 뭐야"),
        ("graphs/graph_게임_기초.kg", "게임 밸런스가 뭐야"),
        ("graphs/graph_언론_기초.kg", "정정보도가 뭐야"),
        ("graphs/graph_영화_기초.kg", "몽타주가 뭐야"),
        ("graphs/graph_회계_기초.kg", "재무상태표가 뭐야"),
        ("graphs/graph_주거_기초.kg", "단열이 뭐야"),
        ("graphs/graph_조리과학_기초.kg", "마이야르반응이 뭐야"),
        ("graphs/graph_통신_기초.kg", "변조가 뭐야"),
        ("graphs/graph_소프트웨어공학_기초.kg", "버전관리가 뭐야"),
        ("graphs/graph_해양_기초.kg", "조석이 뭐야"),
        ("graphs/graph_의류섬유_기초.kg", "직물이 뭐야"),
        ("graphs/graph_지질학_기초.kg", "판 구조론이 뭐야"),
        ("graphs/graph_언어학_기초.kg", "형태소가 뭐야"),
        ("graphs/graph_생명공학_기초.kg", "유전자 편집이 뭐야"),
        ("graphs/graph_미생물_기초.kg", "세균과 바이러스 차이가 뭐야"),
        ("graphs/graph_광학_기초.kg", "빛의 굴절이 뭐야"),
        ("graphs/graph_기후학_기초.kg", "온실효과가 뭐야"),
        ("graphs/graph_고고학_기초.kg", "고고학 층위가 뭐야"),
        ("graphs/graph_로봇공학_기초.kg", "피드백 제어가 뭐야"),
        ("graphs/graph_사회학_기초.kg", "사회화가 뭐야"),
        ("graphs/graph_우주_기초.kg", "광년이 뭐야"),
        ("graphs/graph_컴퓨터_기초.kg", "CPU가 뭐야"),
        ("graphs/graph_심리_기초.kg", "인지 편향이 뭐야"),
        ("graphs/graph_지식표현_기초.kg", "온톨로지가 뭐야"),
        ("graphs/graph_정보이론_기초.kg", "정보 엔트로피가 뭐야"),
        ("graphs/graph_정보보안_기초.kg", "기밀성이 뭐야"),
    )
    for path, question in cases:
        verdict, answer = engine.judge(engine.load(path), question)
        assert verdict == "인정", (path, question, verdict, answer)
        assert answer


def test_recent_domain_questions_route_to_their_graphs():
    """새 기초 그래프가 패키지의 전역 라우터에서도 실제로 선택되는지 확인한다."""
    cases = (
        ("graphs/graph_사회_기초.kg", "사회 규범이 뭐야"),
        ("graphs/graph_영양_기초.kg", "단백질이 뭐야"),
        ("graphs/graph_정치시민_기초.kg", "선거가 뭐야"),
        ("graphs/graph_건축_기초.kg", "도면 축척이 뭐야"),
        ("graphs/graph_환경_기초.kg", "지속가능성이 뭐야"),
        ("graphs/graph_컴퓨터_기초.kg", "운영체제가 뭐야"),
        ("graphs/graph_행정_기초.kg", "증명서가 뭐야"),
        ("graphs/graph_도시_기초.kg", "기반시설이 뭐야"),
        ("graphs/graph_생활건강_기초.kg", "위생이 뭐야"),
        ("graphs/graph_응급안전안내.kg", "숨을 못 쉬겠어"),
        ("graphs/graph_재난안전_기초.kg", "경보가 뭐야"),
        ("graphs/graph_식물_기초.kg", "식물 뿌리가 뭐야"),
        ("graphs/graph_동물_기초.kg", "서식지가 뭐야"),
        ("graphs/graph_에너지_기초.kg", "화석연료가 뭐야"),
        ("graphs/graph_재료_기초.kg", "세라믹이 뭐야"),
        ("graphs/graph_데이터_기초.kg", "데이터 시각화가 뭐야"),
        ("graphs/graph_인공지능_기초.kg", "기계학습용 학습 데이터가 뭐야"),
        ("graphs/graph_인체_기초.kg", "신경계가 뭐야"),
        ("graphs/graph_전자_기초.kg", "트랜지스터가 뭐야"),
        ("graphs/graph_지리_기초.kg", "인구밀도가 뭐야"),
        ("graphs/graph_국제관계_기초.kg", "국제기구가 뭐야"),
        ("graphs/graph_음향_기초.kg", "데시벨이 뭐야"),
        ("graphs/graph_공학설계_기초.kg", "설계 검증이 뭐야"),
        ("graphs/graph_게임_기초.kg", "멀티플레이가 뭐야"),
        ("graphs/graph_언론_기초.kg", "뉴스 편집이 뭐야"),
        ("graphs/graph_영화_기초.kg", "다큐멘터리가 뭐야"),
        ("graphs/graph_회계_기초.kg", "회계에서 부채가 뭐야"),
        ("graphs/graph_주거_기초.kg", "환기가 뭐야"),
        ("graphs/graph_조리과학_기초.kg", "유화가 뭐야"),
        ("graphs/graph_통신_기초.kg", "통신 프로토콜이 뭐야"),
        ("graphs/graph_소프트웨어공학_기초.kg", "소프트웨어 테스트가 뭐야"),
        ("graphs/graph_해양_기초.kg", "산호초가 뭐야"),
        ("graphs/graph_의류섬유_기초.kg", "편물이 뭐야"),
        ("graphs/graph_지질학_기초.kg", "지층이 뭐야"),
        ("graphs/graph_언어학_기초.kg", "통사론이 뭐야"),
        ("graphs/graph_생명공학_기초.kg", "PCR이 뭐야"),
        ("graphs/graph_미생물_기초.kg", "균류가 뭐야"),
        ("graphs/graph_광학_기초.kg", "프리즘에서 색이 나뉘는 이유"),
        ("graphs/graph_기후학_기초.kg", "탄소 순환이 뭐야"),
        ("graphs/graph_고고학_기초.kg", "유물이 뭐야"),
        ("graphs/graph_로봇공학_기초.kg", "액추에이터가 뭐야"),
        ("graphs/graph_사회학_기초.kg", "관료제가 뭐야"),
        ("graphs/graph_우주_기초.kg", "블랙홀이 뭐야"),
        ("graphs/graph_컴퓨터_기초.kg", "RAM이 뭐야"),
        ("graphs/graph_심리_기초.kg", "지각이 뭐야"),
        ("graphs/graph_지식표현_기초.kg", "지식 그래프가 뭐야"),
        ("graphs/graph_정보이론_기초.kg", "무손실 압축이 뭐야"),
        ("graphs/graph_정보보안_기초.kg", "정보보안에서 무결성이 뭐야"),
    )
    index = engine.graph_index()
    for expected, question in cases:
        selected, score, _ = engine.pick_graph(question, index)
        assert selected == expected, (question, selected, score)


def test_exact_global_out_of_scope_examples_do_not_leak_to_unrelated_graphs():
    """한 그래프가 명시한 긴 무관 발화는 다른 그래프가 가로채지 않는다."""
    index = engine.graph_index()
    for question in ("오늘 뉴스 알려 줘", "재밌는 영화 추천해 줘"):
        selected, score, _ = engine.pick_graph(question, index)
        assert selected is None, (question, selected, score)
