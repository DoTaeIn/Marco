"""Speed memos of the relational parser (round 6): each one is dropped by the change that makes it stale.

The answers these memos serve must be the ones a parser without them gives; the tests mutate a parser
the ways the code does (learn, expression_learning.propose) and check the memo started over.
"""
import pytest

from relational_semantics import RelationalParser

pytestmark = pytest.mark.language("한국어")

QUESTION = "우표는 41개 있었는데 우표 13개를 덜었어. 지금 우표는 몇 개야?"
REMOVE = {"text": "구슬 4개를 덜었다", "slots": {"item": "구슬", "n": "4"},
          "inflection": {"stem": "덜", "kind": "regular", "tense": "past", "ending": "plain"},
          "meaning": {"triple": ["$item", "count_remove", "$n"]}}


def test_literal_memos_repeat_the_first_reading():
    parser = RelationalParser()
    literal = "우표 13개를 덜었어"
    first = list(parser._clause_candidates(literal))
    assert literal in parser._candidate_memo and literal in parser._variant_memo
    assert list(parser._clause_candidates(literal)) == first
    assert first == list(RelationalParser()._all_clause_candidates(literal))
    assert parser._variant_literals(literal) == RelationalParser()._variant_literals_of(literal)


def test_learn_drops_the_literal_memos():
    parser = RelationalParser()
    assert parser.parse(QUESTION) is None          # fills the memos with the readings before learning
    assert parser._candidate_memo
    parser.learn(REMOVE)
    assert not parser._candidate_memo and not parser._variant_memo
    # the learned inflection adds candidates for 덜었어: a kept memo would still read nothing
    assert parser.answer(parser.parse(QUESTION))["answer"] == "28개입니다."


def test_expression_learning_drops_the_literal_memos():
    from tests.test_expression_learning import payload
    from expression_learning import propose
    parser = RelationalParser()
    correction, validation = payload()
    text = "소라의 키는 다미의 키를 웃돈다"
    assert parser.parse(text, partial=True) is None
    memo = parser._candidate_memo
    assert text in memo
    assert propose(parser, correction, validation)["accepted"]
    assert parser._candidate_memo is not memo and not parser._candidate_memo
    assert parser.parse(text, partial=True)["facts"][0]["triple"] == ["소라", "taller", "다미"]
