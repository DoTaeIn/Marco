"""공개된 최소 상식 지식팩의 직접 근거 회귀 검사."""
import unittest

import engine


class MinimumKnowledgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = engine.load("graphs/graph_AGI_최소지식.kg")

    def test_direct_facts_and_rules(self):
        checks = {
            "1 더하기 1은 얼마야?": "1 더하기 1은 2다.",
            "대한민국 수도가 어디야?": "대한민국의 수도는 서울이다.",
            "지구는 무엇 주위를 돌아?": "지구는 태양 주위를 돈다.",
            "길 건널 때 뭐 해야 해?": "차가 다니는 길을 건널 때는 좌우를 살핀다.",
            "프로그램 수정 후 테스트해야 해": "프로그램을 바꾼 뒤에는 테스트한다.",
            "답장이 짧으면 화난 거야?": "짧은 답장만으로 상대 감정을 단정할 수 없다.",
        }
        for question, expected in checks.items():
            with self.subTest(question=question):
                self.assertEqual(engine.reply(self.graph, question), expected)

    def test_out_of_scope_realtime_request_is_not_invented(self):
        answer = engine.reply(self.graph, "오늘 서울 날씨가 뭐야?")
        self.assertIn("범위", answer)


if __name__ == "__main__":
    unittest.main()
