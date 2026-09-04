# -*- coding: utf-8 -*-
import unittest

import input_understanding


class InputUnderstandingTest(unittest.TestCase):
    def test_question_request_and_constraints(self):
        result = input_understanding.understand("이 문서를 3줄 불릿으로 요약해줘")
        segment = result["segments"][0]
        self.assertEqual(segment["act_candidates"][0]["kind"], "request.summary")
        self.assertIn("3줄", segment["modifiers"]["constraints"])
        self.assertIn("bullets", segment["modifiers"]["format"])

    def test_context_is_same_history_only(self):
        prior = input_understanding.understand("소고기뭇국 레시피를 설명해줘")
        result = input_understanding.understand("그거 세 줄로 요약해줘", [prior])
        reference = result["segments"][0]["context_refs"][0]
        self.assertTrue(reference["resolved_to"])
        isolated = input_understanding.understand("그거 세 줄로 요약해줘", [])
        self.assertIsNone(isolated["segments"][0]["context_refs"][0]["resolved_to"])

    def test_code_url_and_shell_are_preserved_and_never_executed(self):
        result = input_understanding.understand("`rm -rf ./tmp`와 https://example.test/a;b 를 비교해줘")
        self.assertEqual(len(result["segments"]), 1)
        command = input_understanding.understand("rm -rf ./tmp")["segments"][0]["command"]
        self.assertTrue(command["present"])
        self.assertEqual(command["risk"], "destructive")
        self.assertFalse(command["execution_allowed"])

    def test_noise_keeps_uncertainty(self):
        result = input_understanding.understand("@@@ ###")
        self.assertTrue(result["needs_clarification"])
        self.assertEqual(result["overall"]["primary"]["kind"], "unknown.noise")

    def test_subject_without_known_act_asks_back_instead_of_crashing(self):
        """주제만 잡히고 행동이 안 걸리는 말에서 max() 가 터졌다.

        '저녁 메뉴 추천해줘' 가 UI 를 오류 한 줄로 만들었다. '추천' 은 규칙에
        없어 행동 후보가 0개인데, '저녁 메뉴' 가 주제로 잡혀 잡음 분기도
        안 걸렸다. 못 알아듣는 것과 죽는 것은 다르다 — 되묻어야 한다."""
        for 말 in ("저녁 메뉴 추천해줘", "추천해줘"):
            결과 = input_understanding.understand(말)
            self.assertEqual(결과["overall"]["primary"]["kind"], "unknown.no_act", 말)
            self.assertTrue(결과["needs_clarification"], 말)
            # 잡음으로 단정하지 않는다. 무엇에 대한 말인지는 알아들었다.
            self.assertNotEqual(결과["overall"]["primary"]["kind"], "unknown.noise", 말)
            self.assertEqual(결과["segments"][0]["goal"]["kind"], "clarify", 말)


if __name__ == "__main__":
    unittest.main()
