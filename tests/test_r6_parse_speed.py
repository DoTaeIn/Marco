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
    from marco.learning.expressions import propose
    parser = RelationalParser()
    correction, validation = payload()
    text = "소라의 키는 다미의 키를 웃돈다"
    assert parser.parse(text, partial=True) is None
    memo = parser._candidate_memo
    assert text in memo
    assert propose(parser, correction, validation)["accepted"]
    assert parser._candidate_memo is not memo and not parser._candidate_memo
    assert parser.parse(text, partial=True)["facts"][0]["triple"] == ["소라", "taller", "다미"]


def test_compiled_patterns_are_shared_by_text_and_flags_not_by_parser():
    import re
    from relational_semantics import _compiled, _patterns
    first = _compiled(r"r6-probe (\d+)")
    assert _compiled(r"r6-probe (\d+)") is first and _patterns[r"r6-probe (\d+)", 0] is first
    assert _compiled(r"r6-probe (\d+)", re.IGNORECASE) is not first
    assert _compiled(r"r6-probe (\d+)", re.IGNORECASE).match("R6-PROBE 4").group(1) == "4"
    # a pattern is a function of its text alone: a parser learning keeps what it compiled, and a
    # parser built after that reads with the same objects
    parser = RelationalParser()
    before = dict(_patterns)
    parser.learn(REMOVE)
    assert all(_patterns[key] is value for key, value in before.items())
    assert [p.pattern for p in parser.templates[-1][0]] == [
        p.pattern for p in RelationalParser.compile(REMOVE, parser.data.get("numerals", {}), parser.slot_particles,
                                                    counters=parser.counters, pointers=parser.pointers)[0]]


def test_two_conversations_on_one_model_do_not_share_what_one_learns():
    from marco.learning.expressions import propose
    from pack_model import _built_parsers, development_model
    from reasoning_context import ReasoningContext
    from tests.test_expression_learning import payload
    model = development_model("한국어")
    first, second = ReasoningContext(model=model), ReasoningContext(model=model)
    one, other = first._parser(), second._parser()
    assert one is not other and one.data is not other.data and one.templates is not other.templates
    assert one._inflection_trie is other._inflection_trie        # shared until one of them learns
    text = "소라의 키는 다미의 키를 웃돈다"
    assert other.parse(text, partial=True) is None
    correction, validation = payload()
    assert propose(one, correction, validation)["accepted"]
    one.learn(REMOVE)
    assert one.parse(text, partial=True)["facts"][0]["triple"] == ["소라", "taller", "다미"]
    assert one.answer(one.parse(QUESTION))["answer"] == "28개입니다."
    # the other conversation, a restart and the kept build read neither
    for parser in (other, ReasoningContext(model=model)._parser(), _built_parsers[model.fingerprint]):
        assert parser.parse(text, partial=True) is None and parser.parse(QUESTION) is None
        assert len(parser.data["examples"]) == len(parser.templates) == len(one.templates) - 2
    assert one._inflection_trie is not other._inflection_trie


def test_a_copied_parser_reads_as_a_fresh_build():
    from pack_model import development_model
    model = development_model("한국어")
    copied = model.parser()
    built = RelationalParser(data=model.relational_data, language_pack=model.language)
    assert copied.data == built.data and copied._inflection_trie == built._inflection_trie
    assert [[p.pattern for p in patterns] for patterns, _m in copied.templates] ==         [[p.pattern for p in patterns] for patterns, _m in built.templates]
    for text in (QUESTION, "하루가 모래에게 구슬 3개를 줬다", "소라의 키는 다미의 키를 웃돈다"):
        assert copied.parse(text, partial=True) == built.parse(text, partial=True)
