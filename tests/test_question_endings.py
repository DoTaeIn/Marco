# -*- coding: utf-8 -*-
"""물음의 말끝은 적어 두는 것이 아니라 활용에서 만든다."""
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pack_model import development_model
from relational_semantics import RelationalParser


class QuestionEndingTest(unittest.TestCase):
    def setUp(self):
        model = development_model()
        self.data, self.language = model.relational_data, model.language
        self.parser = RelationalParser(data=self.data, language_pack=self.language)

    def answer(self, text, parser=None):
        parser = parser or self.parser
        parsed = parser.parse(text)
        return (parser.answer(parsed) or {}).get("answer") if parsed else None

    def test_one_question_reaches_every_declared_question_ending(self):
        base = ("서우는 도아보다 키가 크다. 도아는 라온보다 키가 크다. "
                "서우와 라온 중 누가 더 ")
        for tail in ("커", "커요", "크니", "큰가", "큰가요", "큽니까", "크죠", "클까"):
            with self.subTest(tail=tail):
                self.assertEqual(self.answer(base + tail), "서우입니다.")

    def test_a_removed_question_ending_is_lost_by_every_family(self):
        """어미 하나를 빼면 모든 갈래가 함께 그 꼴을 잃는다 — 곱해져 있다는 뜻이다."""
        language = json.loads(json.dumps(self.language))
        language["inflection"]["question_endings"] = [
            e for e in language["inflection"]["question_endings"] if e != "question_formal"]
        narrow = RelationalParser(data=self.data, language_pack=language)
        pairs = [("서우는 도아보다 키가 크다. 도아는 라온보다 키가 크다. 서우와 라온 중 누가 더 ",
                  "큽니까", "커"),
                 ("상자에 구슬이 18개 있다. 구슬은 몇 개 남았", "습니까", "어"),
                 ("하루가 연필을 책상으로 옮겼다. 지금 연필은 어디에 있", "습니까", "어")]
        for base, gone, kept in pairs:
            with self.subTest(base=base[:12]):
                self.assertIsNone(self.answer(base + gone, narrow))
                self.assertIsNotNone(self.answer(base + kept, narrow))
                self.assertIsNotNone(self.answer(base + gone))

    def test_a_question_is_never_realized_by_a_statement_ending(self):
        """물음을 서술 어미로 바꾸면 묻던 말이 단정하는 말이 된다. 그것은 같은 예시가 아니다."""
        base = ("서우는 도아보다 키가 크다. 도아는 라온보다 키가 크다. "
                "서우와 라온 중 누가 더 ")
        for tail in ("크다", "크고", "크지만", "큰데"):
            with self.subTest(tail=tail):
                self.assertIsNone(self.answer(base + tail))

    def test_widening_the_endings_does_not_widen_what_counts_as_evidence(self):
        for text in ("서우는 도아보다 키가 크다. 서우와 라온 중 누가 더 큰가요",
                     "상자에 구슬이 18개 있다. 단추는 몇 개 남았습니까",
                     "하루는 도린이다. 하루는 청소합니까"):
            with self.subTest(text=text[-16:]):
                self.assertIsNone(self.answer(text))

    def test_an_annotated_question_needs_declared_question_endings(self):
        language = json.loads(json.dumps(self.language))
        language["inflection"].pop("question_endings", None)
        with self.assertRaises(ValueError) as caught:
            RelationalParser(data=self.data, language_pack=language)
        self.assertIn("question_endings", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
