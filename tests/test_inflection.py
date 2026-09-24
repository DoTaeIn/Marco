"""Declared stems + shared jamo operations, with semantic and provenance gates."""
import copy

import pytest

from hangul import inflect
from language_components import load_reasoning_language
from relational_semantics import RelationalParser

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default


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
    # 굴리다 (roll) is declared in no verb class of the pack: its computed forms
    # read no relation. (먹다 was the stand-in until it was declared a verb of
    # consumption in round 2.)
    assert parser.parse("돌은 23개 있었는데 8개를 굴렸어. 지금 돌은 몇 개야?") is None
    assert parser.parse("사과가 23개 있었는데 8개를 굴렸어", partial=True) is None
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
    # 활용꼴이 늘어도 주석 하나에 항목 하나다. 숫자를 남겨 두는 것은 예문이
    # 문장마다 불어나는 것을 막는 파수꾼이다 — 늘려야 한다면 낱말이 아니라
    # **틀**이 늘어야 한다. 42 -> 45 는 뜻풀이·사건·부정 틀 셋을 더한 것이다.
    # 45 -> 44 로 줄었다. 손으로 적었던 뜻풀이 틀과 사건 틀 둘이 빠지고,
    # 뜻풀이의 **겉틀** 하나와 주고받기를 적은 **보통 문장** 하나가 들어왔다.
    # 짜임도 사건 꼴도 이제 적지 않는다 — 읽어서 꺼낸다.
    # 45 -> 46 은 계사 틀 하나다. `개다` 는 줄어든 꼴이라 꼬리가 `이다` 로 안
    # 끝나고, 그래서 활용표가 과거를 못 만들었다. 줄지 않은 꼴을 하나 적어 두면
    # `였다` 는 계산해서 나온다. **낱말이 아니라 맺음이 는 것이다** — 구슬 하나로
    # 단추도 연필도 읽힌다. 낱말마다 사례를 더하면 이 숫자가 막아야 할 쪽이다.
    # 46 -> 48 은 견주기 틀 둘이다. `보다` 는 이미 조사라 견줄 값은 읽히고
    # 있었고, 모자랐던 것은 그 절을 조건으로 읽는 길뿐이었다. 두 줄인 것은
    # 낱말이 둘이어서가 아니라 **연산이 둘**(`>`·`<`)이기 때문이다 — 무엇을
    # 견주는지는 공리가 정하므로, 자리나 관계를 견주게 되어도 여기는 안 는다.
    # 이후 상태·대화·원인 구조가 각각 팩의 선언 틀로 들어와 52개가 됐고,
    # 52 -> 53은 같은 주어라도 다른 결과에 원인을 붙이지 않기 위한 일반
    # `reason_query` 틀 하나다. 특정 사람·원인·질문 문장을 위한 분기가 아니다.
    # 53 -> 72: possession state syntax, two independently declared
    # remove/add lexemes, an elided-location event shape, then four
    # action-program shapes (state lookup, unique selection, a state
    # condition, and a role-composed quantity lookup). These are reusable
    # linguistic meanings; the three Social promise/create/cancel/status
    # examples are likewise pack data. Clause connection and role completion remain
    # algorithms rather than whole-sentence examples.
    # 72 -> 78: a transfer with its item left out, the count question with the
    # adverb after the subject, a location question without `지금`, a reference
    # correction of one earlier event, `왜 그렇게 됐어`, and `X 말고 다른 사람은`.
    # Each is one reusable shape; what fills the slots is not listed.
    # 78 -> 99 (round 4, natural language): places as holders (에는 … 있다, N개가 장소에 있다,
    # 장소에서 가져갔다, 장소에 두고 왔다/뒀다/맡겼다, 장소에서 장소로 옮겼다/옮겨졌다, and the place
    # with 좀), the count not known (좀 있다, 좀 가지고 있다, 도 좀 있다, N개 있고 (,) Y도 좀 있다), the
    # amount said later without its holder (18개이다), 만 (구슬만 18개 있다/를 가지고 있다, 구슬 18개만
    # 있다/가지고 있다, 구슬 18개를 가지고 있다), and a thing used for a purpose (잔치에 썼다). 21 shapes,
    # each a class of the round's cause table; no word of a development set.
    # 99 -> 101 (round 5, batch 1): the thing as topic with the holder after it (구슬 18개는 하루가 가지고
    # 있다) and the holder in a relative clause of holding (하루가 가지고 있는 구슬이 18개 있다).
    # 101 -> 106 (round 5, batch 3): only-counts (가진 것은/건 ... 뿐이다, 한테는 ... 뿐이다), a move said
    # places first, leaving things said count first.
    # 106 -> 109 (round 5, batch 6): a place count said thing and amount first (구슬이 18개가 상자에), a count
    # not known of a place with 에, the thing as topic without its amount.
    assert len(parser.templates) == len(parser.data["examples"]) == 109
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
