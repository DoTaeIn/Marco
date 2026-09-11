import unittest

import affect_state


class AffectStateTests(unittest.TestCase):
    def test_off_mode_never_changes_answer(self):
        state = affect_state.update(affect_state.initial(False), "나 너무 힘들어")
        self.assertFalse(state["enabled"])
        self.assertEqual(affect_state.decorate("검증된 답", state), "검증된 답")

    def test_direct_distress_changes_expression_not_fact(self):
        state = affect_state.update(affect_state.initial(True), "나 너무 힘들어")
        self.assertEqual(state["mode"], "care")
        self.assertIn("검증된 답", affect_state.decorate("검증된 답", state))
        self.assertEqual(state["signals"], ["직접 표현한 정서"])

    def test_short_reply_is_not_a_mind_reading_signal(self):
        state = affect_state.update(affect_state.initial(True), "답장이 짧아")
        self.assertEqual(state["mode"], "focus")
        self.assertEqual(state["signals"], [])


if __name__ == "__main__":
    unittest.main()
