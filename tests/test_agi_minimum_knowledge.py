# -*- coding: utf-8 -*-
"""최소 AGI 지식팩의 영역별 회귀 문제.

이것은 MMLU/ARC 전체를 대체하지 않는다. 각 주장과 미지 경계를 재현 가능하게
고정한 소형 진단 세트다.
"""
import unittest
import engine


GRAPH = "graphs/graph_AGI_최소지식.kg"
# (질문, 근거 사례 노드, 결론 노드, 답변에 반드시 있어야 할 문구).
# 공식 MMLU/ARC/HellaSwag/CommonsenseQA 전체 점수를 주장하는 시험이 아니라,
# 이 KG가 선언한 여섯 영역의 결론과 미지 경계를 되돌려 보는 공개 진단 세트다.
CASES = {
    "유리잔을 바닥에 떨어뜨렸습니다": ("유리잔낙하", "유리잔파손가능", "깨질 수 있습니다"),
    "불에 손을 가까이 댔습니다": ("불접촉", "불뜨거움", "화상 위험"),
    "물통 안에 책상 전체를 넣을 수 있나요": ("용기크기", "용기크기제약", "넣을 수 없습니다"),
    "아침 다음은 무엇인가요": ("아침시각", "아침뒤점심", "아침 다음에는 점심"),
    "서울에서 부산까지 걸어서 한 시간에 갈 수 있나요": ("도시간도보", "서울부산도보한시간불가", "갈 수 없습니다"),
    "대한민국 수도는 어디인가요": ("수도질문", "대한민국수도서울", "수도는 서울"),
    "2 더하기 2는 얼마인가요": ("수학질문", "이더하기이는사", "2 더하기 2는 4"),
    "지구는 무엇 주위를 도나요": ("과학질문", "지구태양공전", "태양 주위를 공전"),
    "훈민정음은 누가 만들었나요": ("역사질문", "훈민정음세종창제", "세종대왕"),
    "프랑스 수도는 어디인가요": ("지리질문", "프랑스수도파리", "수도는 파리"),
    "계약 해지가 유효한지 단정해줘": ("법질문", "법률판단사실확인", "구체적 사실"),
    "가슴 통증이 있는데 응급실에 가야 하나요": ("의학질문", "가슴통증전문의료", "응급 서비스"),
    "레시피 순서대로 알려줘": ("레시피질문", "레시피순서준수", "재료를 준비한 뒤"),
    "프로그램을 만든 다음 무엇을 해야 하나요": ("코드절차질문", "프로그램작성뒤테스트", "테스트를 실행"),
    "가구 조립을 시작하기 전에 뭘 확인하나요": ("조립절차질문", "조립전설명서부품확인", "설명서와 부품"),
    "A가 B보다 크고 B가 C보다 크면 A와 C는 어떻게 되나요": ("부등식", "A는C보다큼", "A는 C보다 큽니다"),
    "아이스크림 판매와 익사는 함께 늘었으니 아이스크림이 원인인가요": ("상관인과", "상관인과구분", "원인이라고 할 수 없습니다"),
    "결과가 원인보다 먼저 일어나도 원인이라고 할 수 있나요": ("선후질문", "결과보다원인먼저", "원인이라고 할 수 없습니다"),
    "어제 비가 오지 않았다면 소풍을 갔을 텐데": ("반사실질문", "가정과실제구분", "반사실적 가정"),
    "친구가 짧게 답했으니 화난 건가요": ("감정질문", "감정단정불가", "단정할 수 없으니"),
    "이 말이 농담인지 어떻게 알아요": ("농담질문", "농담맥락확인", "맥락을 함께 확인"),
    "상대가 불편해 보이면 어떻게 말해야 하나요": ("예절질문", "불편상대배려표현", "괜찮은지 묻고"),
    "친구가 틀린 믿음을 가질 수도 있나요": ("신념질문", "타인틀린신념가능", "틀린 믿음"),
    "근거 없이 내일의 정확한 주가를 알려줘": ("모름질문", "근거부족추가정보요청", "추가 정보를 요청"),
    "이름도 증상도 없이 병을 확정해줘": ("정보부족질문", "근거부족추가정보요청", "추가 정보를 요청"),
}

# 대표 문제의 조사·어순·구어체 변형. 이 엔진은 사례 별칭을 근거로 사용하므로
# 검증된 변형을 그래프에 선언한 뒤 같은 결론으로 가는지를 별도로 고정한다.
VARIANT_CASES = {
    "유리컵을 높은 곳에서 떨어뜨렸어": ("유리잔낙하", "유리잔파손가능"),
    "불꽃 근처에 손을 대면 위험해?": ("불접촉", "불뜨거움"),
    "아침이 지나면 보통 어느 때가 와?": ("아침시각", "아침뒤점심"),
    "한국의 수도가 서울인가요": ("수도질문", "대한민국수도서울"),
    "코드를 작성했는데 다음 단계는 검사인가요": ("코드절차질문", "프로그램작성뒤테스트"),
    "친구의 짧은 답장만으로 기분을 알 수 있어?": ("감정질문", "감정단정불가"),
    "정보가 모자란데 병명을 확정해 줄 수 있니": ("정보부족질문", "근거부족추가정보요청"),
}


class MinimumKnowledgeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = engine.load(GRAPH)

    def test_all_six_areas_route_to_their_evidence(self):
        for question, (expected, _concept, _answer_fragment) in CASES.items():
            with self.subTest(question=question):
                actual, score = engine.match_evidence(question, self.graph)
                self.assertEqual(actual, expected, (actual, score))

    def test_questions_answer_from_the_expected_knowledge_area(self):
        for question, (_evidence, concept, answer_fragment) in CASES.items():
            with self.subTest(question=question):
                session = engine.세션(self.graph)
                tag, answer, _result = session.말하기(question)
                self.assertEqual(tag, "인정", answer)
                self.assertEqual(session.계획["주장"], concept)
                self.assertIn(answer_fragment, answer)

    def test_unknown_stays_unknown(self):
        session = engine.세션(self.graph)
        answer = session.대답("화성인 언어의 모든 문법을 확정해줘")
        self.assertIn("근거", answer)

    def test_declared_variants_keep_the_same_conclusion(self):
        for question, (evidence, concept) in VARIANT_CASES.items():
            with self.subTest(question=question):
                session = engine.세션(self.graph)
                tag, answer, _result = session.말하기(question)
                self.assertEqual(tag, "인정", answer)
                self.assertEqual(session.계획["근거"], evidence)
                self.assertEqual(session.계획["주장"], concept)


if __name__ == "__main__":
    unittest.main()
