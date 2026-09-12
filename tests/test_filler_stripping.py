# -*- coding: utf-8 -*-
"""말머리 군말은 뜻을 안 나른다. 떼되, 뗀 것이 발화 전부가 되면 안 된다."""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import encoder


class FillerStrippingTest(unittest.TestCase):
    def test_a_declared_head_is_removed(self):
        for head in ("저기요", "죄송한데", "그래서", "아니 근데", "ㅋㅋ 그래서"):
            with self.subTest(head=head):
                self.assertEqual(encoder.strip_fillers(head + " 손해배상 얼마나 나와요"),
                                 "손해배상 얼마나 나와요")

    def test_stacked_heads_come_off_together(self):
        self.assertEqual(encoder.strip_fillers("아 근데 저기요 손해배상 얼마나 나와요"),
                         "손해배상 얼마나 나와요")

    def test_an_utterance_made_only_of_fillers_is_left_alone(self):
        """'ㅋㅋ' 하나는 군말이 아니라 그 자체가 발화다."""
        for text in ("ㅋㅋ", "그래서", "저기요", "음..."):
            with self.subTest(text=text):
                self.assertEqual(encoder.strip_fillers(text), "")

    def test_a_one_letter_head_needs_punctuation_after_it(self):
        """'그' 는 대개 지시어다. '그 방법' 의 '그' 를 떼면 뜻이 바뀐다."""
        self.assertEqual(encoder.strip_fillers("그 방법 말고는 없었습니다"), "")
        self.assertEqual(encoder.strip_fillers("저 사람이 먼저 밀었습니다"), "")
        self.assertEqual(encoder.strip_fillers("음... 손해배상 얼마나 나와요"),
                         "손해배상 얼마나 나와요")

    def test_nothing_is_claimed_without_a_declaration(self):
        """언어팩이 안 적은 말은 안 뗀다. 코드가 한국어를 따로 알지 않는다."""
        self.assertEqual(encoder.strip_fillers("저기요 손해배상 얼마나 나와요",
                                               {"fillers": {}}), "")

    def test_the_stripped_form_leads_and_the_original_survives(self):
        """뗀 쪽이 제 무게로 겨루고, 잘못 뗐으면 원문이 받는다."""
        got = encoder.split_fragments("저기요 손해배상 얼마나 나와요")
        self.assertEqual(got[0], "손해배상 얼마나 나와요")
        self.assertIn("저기요 손해배상 얼마나 나와요", got)


if __name__ == "__main__":
    unittest.main()
