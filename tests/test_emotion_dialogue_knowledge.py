"""감정 그래프는 공감은 하되 감정·진단을 단정하지 않아야 한다."""
import os
import unittest

os.environ.setdefault("KG_ENCODER", "문자")

import engine


class EmotionDialogueKnowledgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.graph = engine.load("graphs/graph_감정대화_기초.kg")

    def test_expressed_emotion_is_received(self):
        self.assertIn("힘들다고 말한 감정은 먼저 받아들인다", engine.reply(self.graph, "나 너무 힘들어"))

    def test_new_direct_emotion_expressions_are_received(self):
        cases = {
            "요즘 너무 외로워": ("혼자인 느낌이 든다고 말해 줘서 고마워", "외로운 마음을 혼자 견딜 필요는 없다", "지금은 누군가와 연결되고 싶은지 물어볼 수 있다"),
            "오늘 정말 기뻐": ("좋은 일이 생겼다니 함께 기뻐", "기쁜 마음을 나눠 줘서 고마워", "그 기쁨을 조금 더 들려줘도 좋다"),
            "너무 지쳤어": ("계속 버티느라 많이 지쳤겠다", "지쳤다는 신호를 무시하지 않아도 된다", "지금 가장 덜 부담스러운 도움이 무엇인지 물어볼 수 있다"),
        }
        for phrase, expected in cases.items():
            with self.subTest(phrase=phrase):
                verdict, _answer = engine.judge(self.graph, phrase)
                self.assertEqual(verdict, "인정")
                self.assertTrue(any(text in engine.reply(self.graph, phrase) for text in expected))

    def test_observation_does_not_become_mind_reading(self):
        self.assertEqual(
            engine.reply(self.graph, "답장이 짧아"),
            "짧은 답장만으로 화났다고 단정할 수 없다.",
        )

    def test_immediate_danger_routes_to_safety_help(self):
        answer = engine.reply(self.graph, "나를 다치게 할 것 같아")
        self.assertIn("즉시 도움", answer)


if __name__ == "__main__":
    unittest.main()
