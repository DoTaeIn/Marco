"""Declared stems + shared jamo operations, with semantic and provenance gates."""
import copy

import pytest

from hangul import inflect
from language_components import load_reasoning_language
from relational_semantics import RelationalParser


def forms(stem, tense, ending, kind="regular", grammar=None):
    grammar = load_reasoning_language()["inflection"] if grammar is None else grammar
    return {form["text"] for form in inflect(stem, tense, ending, grammar, kind=kind)}


@pytest.mark.parametrize("stem,tense,ending,kind,expected", [
    ("가", "present", "cause", "regular", "가서"),
    ("먹", "present", "cause", "regular", "먹어서"),
    ("막", "present", "cause", "regular", "막아서"),
    ("보", "present", "cause", "regular", "봐서"),
    ("주", "present", "cause", "regular", "줘서"),
    ("마시", "present", "cause", "regular", "마셔서"),
    ("쓰", "present", "cause", "regular", "써서"),
    ("아프", "present", "cause", "descriptive", "아파서"),
    ("잠그", "present", "cause", "regular", "잠가서"),
    ("하", "present", "cause", "regular", "해서"),
    ("크", "present", "background", "descriptive", "큰데"),
    ("높", "present", "background", "descriptive", "높은데"),
    ("멀", "present", "background", "descriptive", "먼데"),
    ("있", "present", "background", "existential", "있는데"),
    ("먹", "present", "background", "regular", "먹는데"),
    ("살", "present", "background", "regular", "사는데"),
    ("먹", "present", "reason", "regular", "먹으니까"),
    ("가", "present", "reason", "regular", "가니까"),
    ("살", "present", "reason", "regular", "사니까"),
    ("만들", "present", "indicative", "regular", "만든다"),
    ("꺼내", "past", "informal", "regular", "꺼냈어"),
    ("옮기", "past", "polite", "regular", "옮겼어요"),
    ("높", "past", "informal", "descriptive", "높았어"),
    ("가", "past", "polite", "regular", "갔어요"),
    ("크", "past", "plain", "descriptive", "컸다"),
])
def test_jamo_rules_transfer_to_stems_not_in_semantic_examples(stem, tense, ending, kind, expected):
    assert expected in forms(stem, tense, ending, kind)


def test_tense_and_class_block_wrong_allomorphs():
    assert "높았아" not in forms("높", "past", "informal", "descriptive")
    assert "크는데" not in forms("크", "present", "background", "descriptive")
    assert "살니까" not in forms("살", "present", "reason")
    assert "만들는다" not in forms("만들", "present", "indicative")
    assert "있은데" not in forms("있", "present", "background", "existential")


def test_declaration_selects_rules_and_missing_or_unknown_classes_do_not_fallback():
    grammar = copy.deepcopy(load_reasoning_language()["inflection"])
    grammar["endings"]["go"] = [{"steps": [{"op": "append", "text": "ZZ"}]}]
    assert forms("크", "present", "go", "descriptive", grammar) == {"크ZZ"}
    with pytest.raises(ValueError, match="unsupported_inflection"):
        forms("걷", "present", "informal", "d-irregular")
    with pytest.raises(ValueError, match="unsupported_inflection"):
        forms("크", "present", "go", "descriptive", {})
    grammar["max_forms"] = 1
    with pytest.raises(ValueError, match="inflection_form_limit"):
        forms("하", "past", "plain", grammar=grammar)


@pytest.mark.parametrize("item,total,delta,expected", [
    ("사과", "23", "8", "15"), ("우표", "41", "13", "28"),
    ("파란 구슬", "서른두", "다섯", "27"),
])
def test_connected_past_quantity_and_informal_event(item, total, delta, expected):
    parser = RelationalParser()
    text = f"{item}는 {total}개 있었는데 {delta}개를 꺼냈어. 지금 {item}는 몇 개야?"
    parsed = parser.parse(text)
    assert parser.answer(parsed)["answer"] == expected + "개입니다."
    assert len(parsed["facts"]) == 2
    for fact in parsed["facts"]:
        source = fact["evidence"]
        assert text[source["start"]:source["end"]] == source["text"]
        assert source["normalization"]["tense"] == "past"
        assert source["normalization"]["operations"]


def test_comparison_uses_consonant_ending_and_vowel_elision_in_one_chain():
    parser = RelationalParser()
    text = "철수는 영수보다 큰데 영수는 민호보다 커요. 철수와 민호 중 누가 더 커?"
    parsed = parser.parse(text)
    assert parser.answer(parsed)["answer"] == "철수입니다."
    assert parsed["facts"][0]["evidence"]["text"].endswith("큰데")


def test_form_support_does_not_invent_a_new_relation():
    parser = RelationalParser()
    assert parser.parse("돌은 23개 있었는데 8개를 먹었어. 지금 돌은 몇 개야?") is None
    assert parser.parse("사과가 23개 있었는데 8개를 꺼냈어", partial=True) is None
    assert parser.parse("그다음 알 수 없는 일이 있었는데 8개를 꺼냈어", partial=True) is None


def test_computed_negative_form_remains_negative_and_cannot_support_transitivity():
    parser = RelationalParser()
    text = "소라는 다미보다 키가 크지 않은데 다미는 유리보다 키가 커. 소라와 유리 중 누가 더 커?"
    parsed = parser.parse(text)
    assert parsed["facts"][0]["polarity"] is False
    assert parser.answer(parsed) is None


@pytest.mark.parametrize("tail", ["크다고", "크다면", "크겠어", "크는데"])
def test_unlicensed_or_wrong_forms_do_not_become_facts(tail):
    parser = RelationalParser()
    assert parser.parse(f"소라는 다미보다 키가 {tail}.", partial=True) is None


def test_legacy_shortcut_cannot_bypass_annotated_stem_class():
    parser = RelationalParser()
    assert parser.parse("모든 도린은 청소한고", partial=True) is None
    assert parser.parse("모든 도린은 청소하고", partial=True)


@pytest.mark.parametrize("punctuation", ["?", " ?", "？", " ？"])
def test_question_does_not_write_observation_even_when_form_is_known(punctuation):
    from reasoning_context import ReasoningContext
    text = "돌은 23개 있었어" + punctuation
    parser = RelationalParser()
    assert parser.parse(text, partial=True) is None
    assert parser.diagnose(text)["diagnostics"][0]["reason"] == "question_is_not_an_observation"
    context = ReasoningContext()
    assert context.turn(text, "graphs/graph_일상추론.kg") is None
    assert context.observations == []


def test_past_removal_form_does_not_admit_future_quotation_or_question():
    parser = RelationalParser()
    for text in ("8개를 꺼내겠어", "8개를 꺼냈다고", "8개를 꺼냈어?"):
        assert parser.parse(text, partial=True) is None
    assert parser.parse("8개를 꺼냈어", partial=True)


def test_new_inflected_predicate_survives_supervised_learning_and_reload(tmp_path):
    parser = RelationalParser()
    question = "우표는 41개 있었는데 우표 13개를 덜었어. 지금 우표는 몇 개야?"
    assert parser.parse(question) is None
    parser.learn({"text": "구슬 4개를 덜었다", "slots": {"item": "구슬", "n": "4"},
                  "inflection": {"stem": "덜", "kind": "regular", "tense": "past", "ending": "plain"},
                  "meaning": {"triple": ["$item", "count_remove", "$n"]}})
    path = tmp_path / "learned.json"
    parser.save(path)
    restored = RelationalParser(model_path=path)
    assert restored.answer(restored.parse(question))["answer"] == "28개입니다."
    assert not any("덜었어" in example["text"] for example in restored.data["examples"])


def test_invalid_stem_annotation_does_not_partially_mutate_learning():
    parser = RelationalParser()
    before = copy.deepcopy(parser.data)
    with pytest.raises(ValueError, match="does_not_match"):
        parser.learn({"text": "구슬 4개를 덜었다", "slots": {"item": "구슬", "n": "4"},
                      "inflection": {"stem": "가", "kind": "regular", "tense": "past", "ending": "plain"},
                      "meaning": {"triple": ["$item", "count_remove", "$n"]}})
    assert parser.data == before


def test_template_count_stays_constant_and_empty_component_lacks_new_forms():
    parser = RelationalParser()
    assert len(parser.templates) == len(parser.data["examples"]) == 42
    pack = copy.deepcopy(load_reasoning_language())
    pack["inflection"] = {}
    old = RelationalParser(language_pack=pack)
    assert old.parse("8개를 꺼냈어", partial=True) is None
    assert old.parse("8개를 꺼냈다", partial=True)


def test_inflected_location_move_reaches_ui_without_research(tmp_path):
    from pathlib import Path
    from unittest.mock import patch
    import kgpack
    from views.kgpack_ui import AppState
    path = tmp_path / "forms.kgpack"
    kgpack.write_pack(path, [Path("graphs/graph_일상추론.kg")] + kgpack.model_files(Path(".")), root=Path("."))
    app = AppState(path, overlay_root=tmp_path / "overlay")
    with patch.object(app.goals, "research", side_effect=AssertionError("local proof must not use web")):
        result = app.turn("우표는 봉투에 있었어. 소라가 우표를 서랍으로 옮겼어요. 지금 우표는 어디에 있어?", "session_forms1")
    assert result["answer"]["answer"] == "서랍에 있습니다."


def test_declared_generic_action_suffix_can_inflect_after_unseen_action_slot():
    parser = RelationalParser()
    text = "모든 타빈은 제론이다. 모든 제론은 노래해. 루미는 타빈이다. 루미는 노래하는가?"
    result = parser.answer(parser.parse(text))
    assert result["answer"] == "네, 루미는 노래합니다."
