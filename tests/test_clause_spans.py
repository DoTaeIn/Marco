"""Clause boundaries preserve source and do not turn suffix guesses into facts."""
import copy
import json

import pytest

from encoder import split_fragments
from hangul import canonical_clauses, clause_spans
from language_components import load_clause_grammar, load_language_pack
from relational_semantics import RelationalParser


def grammar():
    return load_language_pack()["clauses"]


def test_connected_clause_endings_and_original_offsets_survive():
    text = "  철수는 영수보다 크고\t영수는 민호보다 크다.\n철수와 민호 중 누가 더 커?"
    parser = RelationalParser()
    parsed = parser.parse(text)
    assert parser.answer(parsed)["answer"] == "철수입니다."
    assert [fact["evidence"]["text"] for fact in parsed["facts"]] == [
        "철수는 영수보다 크고", "영수는 민호보다 크다"]
    for fact in parsed["facts"]:
        span = fact["evidence"]
        assert text[span["start"]:span["end"]] == span["text"]
    assert "철수는 영수보다 크고" in split_fragments(text)
    assert "철수는 영수보다 크" not in split_fragments(text)
    normalization = parsed["facts"][0]["evidence"]["normalization"]
    assert normalization["canonical"] == "철수는 영수보다 크다"
    assert normalization["rule"] == "hangul-inflection-v1"
    assert normalization["stem"] == "크"
    assert "normalization" not in parsed["facts"][1]["evidence"]


def test_segmenter_can_locate_endings_not_yet_understood_semantically():
    text = "사과가 23개 있었는데 8개를 꺼냈어"
    assert [part["text"] for part in clause_spans(text, grammar())] == [
        "사과가 23개 있었는데", "8개를 꺼냈어"]
    # Locating a boundary does not establish tense, meaning or omitted subject.
    assert RelationalParser().parse(text, partial=True) is None


@pytest.mark.parametrize("item,total,remove,add", [
    ("사과", 23, 8, 2), ("우표", 41, 13, 7), ("바다 유리", 52, 9, 11)])
def test_shared_endings_transfer_across_predicates_entities_and_numbers(item, total, remove, add):
    text = f"{item}는 {total}개 있고 {remove}개를 꺼냈고 {add}개를 넣었다. 지금 {item}는 몇 개야?"
    parser = RelationalParser()
    parsed = parser.parse(text)
    assert parser.answer(parsed)["answer"] == f"{total - remove + add}개입니다."
    assert len(parsed["facts"]) == 3
    for fact in parsed["facts"]:
        evidence = fact["evidence"]
        assert text[evidence["start"]:evidence["end"]] == evidence["text"]


def test_noun_suffix_inside_unknown_entity_is_not_a_semantic_boundary():
    parser = RelationalParser()
    text = "학교 창고 물건은 서랍에 있었다. 지금 학교 창고 물건은 어디에 있어?"
    parsed = parser.parse(text)
    assert len(parsed["facts"]) == 1
    assert parsed["facts"][0]["triple"] == ["학교 창고 물건", "location", "서랍"]
    assert parser.answer(parsed)["answer"] == "서랍에 있습니다."


def test_auxiliary_is_not_discarded_after_connective():
    assert split_fragments("칼을 들고 있었습니다") == ["칼을 들고 있었습니다"]
    parser = RelationalParser()
    assert parser.parse("소라는 다미보다 키가 크고 싶다. 소라와 다미 중 누가 더 커?") is None


@pytest.mark.parametrize("ending", ["고", "지만"])
def test_negation_remains_attached_to_connected_clause(ending):
    parser = RelationalParser()
    text = f"소라는 다미보다 키가 크지 않{ending} 다미는 유리보다 키가 크다. 소라와 유리 중 누가 더 커?"
    parsed = parser.parse(text)
    assert parsed["facts"][0]["polarity"] is False
    assert parser.answer(parsed) is None


@pytest.mark.parametrize("suffix", ["다면", "다고", "겠다고"])
def test_nonasserted_endings_are_not_rewritten_as_assertions(suffix):
    parser = RelationalParser()
    assert parser.parse(f"소라는 다미보다 키가 크{suffix}. 소라와 다미 중 누가 더 커?") is None


def test_unknown_remainder_is_reported_not_dropped():
    parser = RelationalParser()
    text = "돌은 23개 있고 아직 모르는 일을 했다. 지금 돌은 몇 개야?"
    report = parser.diagnose(text)
    assert report["stage"] == "semantic_parse"
    assert report["diagnostics"][0]["evidence"]["text"] == "아직 모르는 일을 했다"


def test_truncated_workaround_is_removed_without_changing_the_answer_rules():
    parser = RelationalParser()
    assert not any(ex["text"].endswith("키가 크") for ex in parser.data["examples"])
    assert "clause_pattern" not in parser.data
    assert parser.parse("소라는 다미보다 키가 크", partial=True) is None
    assert parser.parse("소라는 다미보다 키가 크고", partial=True)


@pytest.mark.parametrize("protected", [
    "'소라는 다미보다 크고, 다미는 유리보다 크다.'",
    '"소라는 다미보다 크고, 다미는 유리보다 크다."',
    '“소라는 다미보다 크고. 다미는 유리보다 크다.”',
    '`소라는 다미보다 크고, 다미는 유리보다 크다.`',
    '```소라는 다미보다 크고.\n다미는 유리보다 크다.```',
    'https://example.test/a.b?q=1,2',
])
def test_quoted_code_and_url_spans_stay_whole(protected):
    text = protected + " 뒤의 문장. 다음 문장."
    parts = clause_spans(text, grammar(), commas=True)
    assert [part["text"] for part in parts] == [protected + " 뒤의 문장", "다음 문장"]
    for span in parts:
        assert text[span["start"]:span["end"]] == span["text"]


def test_decimal_and_thousands_separator_are_not_sentence_boundaries():
    text = "값은 3.14, 다른 값은 1,234.5다."
    assert [x["text"] for x in clause_spans(text, grammar(), commas=True)] == [
        "값은 3.14", "다른 값은 1,234.5다"]


def test_retrieval_comma_after_sentence_ending_keeps_prior_fragment_policy():
    text = "첫 번째 문장입니다, 다음 문장입니다"
    assert split_fragments(text) == [text, "첫 번째 문장입니다", "다음 문장입니다"]


def test_empty_language_pack_never_borrows_ending_rules():
    parser = RelationalParser(language_pack={})
    assert parser.parse("소라는 다미보다 키가 크고", partial=True) is None
    assert parser.parse("소라는 다미보다 키가 크다", partial=True)
    text = "앞 절이고 뒤 절이다"
    assert clause_spans(text, {}) == [{"start": 0, "end": len(text), "text": text}]
    assert list(canonical_clauses(text, {})) == [(text, None)]
    assert split_fragments(text, language_pack={}) == [text]


def test_language_rules_are_injected_and_not_hidden_in_python():
    pack = copy.deepcopy(load_language_pack())
    pack["clauses"]["canonical_endings"] = [
        {"id": "test-ending", "suffix": "zz", "replacements": ["다"]}]
    pack["inflection"] = {}
    parser = RelationalParser(language_pack=pack)
    assert parser.parse("소라는 다미보다 키가 크zz", partial=True)
    assert parser.parse("소라는 다미보다 키가 크고", partial=True) is None


def test_learning_cannot_override_existing_meaning_by_changing_only_ending():
    parser = RelationalParser()
    before = copy.deepcopy(parser.data)
    with pytest.raises(ValueError, match="conflicts"):
        parser.learn({"text": "하루는 모래보다 키가 크고", "slots": {"a": "하루", "b": "모래"},
                      "meaning": {"triple": ["$b", "taller", "$a"]}})
    assert parser.data == before


def test_a_learned_predicate_uses_the_shared_ending_rule():
    parser = RelationalParser()
    parser.learn({"text": "구슬 4개를 덜어냈다", "slots": {"item": "구슬", "n": "4"},
                  "meaning": {"triple": ["$item", "count_remove", "$n"]}})
    text = "우표는 41개 있고 우표 13개를 덜어냈고 7개를 넣었다. 지금 우표는 몇 개야?"
    assert parser.answer(parser.parse(text))["answer"] == "35개입니다."
    assert not any("덜어냈고" in ex["text"] for ex in parser.data["examples"])


def test_clause_cache_tracks_replaced_style_and_accepts_legacy_style(tmp_path):
    path = tmp_path / "style.json"
    path.write_text(json.dumps({"문장분리": {"candidate_suffixes": ["abc"]}}), encoding="utf-8")
    assert load_clause_grammar(str(path))["candidate_suffixes"] == ["abc"]
    path.write_text(json.dumps({"문장분리": {"candidate_suffixes": ["defghi"]}}), encoding="utf-8")
    assert load_clause_grammar(str(path))["candidate_suffixes"] == ["defghi"]
    path.write_text('{"이름":"legacy"}', encoding="utf-8")
    assert load_clause_grammar(str(path)) == {}


@pytest.mark.parametrize("clauses", [[], {"candidate_suffixes": [""]},
                                    {"canonical_endings": [{"id": "broken"}]}])
def test_invalid_clause_configuration_fails_on_load(tmp_path, clauses):
    path = tmp_path / "broken.json"
    path.write_text(json.dumps({"문장분리": clauses}), encoding="utf-8")
    with pytest.raises(ValueError, match="문장분리"):
        load_clause_grammar(str(path))


def test_connected_reasoning_reaches_ui_without_web(tmp_path):
    from pathlib import Path
    from unittest.mock import patch
    import kgpack
    from views.kgpack_ui import AppState
    pack = tmp_path / "clauses.kgpack"
    kgpack.write_pack(pack, [Path("graphs/graph_일상추론.kg")] + kgpack.model_files(Path(".")), root=Path("."))
    app = AppState(pack, overlay_root=tmp_path / "overlay")
    with patch.object(app.goals, "research", side_effect=AssertionError("local proof must not use web")):
        result = app.turn("철수는 영수보다 크고 영수는 민호보다 크다. 철수와 민호 중 누가 더 커?", "session_clauses1")
    assert result["answer"]["answer"] == "철수입니다."
