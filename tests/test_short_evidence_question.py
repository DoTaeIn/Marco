# -*- coding: utf-8 -*-
"""증거 별칭만으로 된 짧은 물음이 구두점 때문에 미지가 되지 않는지 확인한다."""
import unittest
import engine


class ShortEvidenceQuestionTest(unittest.TestCase):
    def test_question_mark_after_exact_evidence_keeps_source_text(self):
        graph = engine.load("graphs/graph_CCTV_기초.kg")
        tag, answer, _result = engine.Session(graph).say("CCTV가 뭐야?")
        self.assertEqual(tag, "인정")
        self.assertIn("CCTV는 영상을 기록하는 장치", answer)

    def test_irrelevant_still_rejected(self):
        graph = engine.load("graphs/graph_CCTV_기초.kg")
        tag, _answer, _result = engine.Session(graph).say("점심 메뉴가 고민이다")
        self.assertEqual(tag, "B2")


if __name__ == "__main__":
    unittest.main()
