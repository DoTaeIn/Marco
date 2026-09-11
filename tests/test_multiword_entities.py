from unittest.mock import patch

import pytest

import engine
from relational_semantics import RelationalParser
from reasoning_context import ReasoningContext

KG = "graphs/graph_일상추론.kg"


@pytest.mark.parametrize("first,second", [("작은 단추", "큰 단추"), ("파란 유리 구슬", "초록 유리 구슬")])
def test_multiword_quantities_remain_separate_through_updates(first, second):
    context = ReasoningContext()
    context.turn(f"{first}는 19개 있다. {second}는 11개 있다.", KG)
    context.turn(f"{second} 4개를 꺼냈다.", KG)
    assert context.turn(f"지금 {first}는 몇 개야?", KG)["answer"] == "19개입니다."
    assert context.turn(f"지금 {second}는 몇 개야?", KG)["answer"] == "7개입니다."


def test_multiword_location_and_actor_preserve_exact_subject():
    parser = RelationalParser()
    text = "오래된 지도는 작은 서랍에 있었다. 옆집 하루가 오래된 지도를 학교 창고로 옮겼다. 지금 오래된 지도는 어디에 있어?"
    parsed = parser.parse(text)
    assert all(item["triple"][0] == "오래된 지도" for item in parsed["facts"])
    assert parser.answer(parsed)["answer"] == "학교 창고에 있습니다."


def test_number_slot_does_not_absorb_a_second_clause():
    parser = RelationalParser()
    assert parser.parse("단추는 숫자를 모르지만 19개 있다. 지금 단추는 몇 개야?") is None


def test_ambiguous_multiword_boundaries_need_independent_entity_evidence():
    parser = RelationalParser()
    ambiguous = "오래된 지도는 작은 서랍에 있었다."
    assert parser.parse(ambiguous, partial=True) is None
    assert parser.parse(ambiguous + " 지금 돌은 몇 개야?") is None
    result = parser.parse(ambiguous + " 지금 오래된 지도는 어디에 있어?")
    assert result["facts"][0]["triple"] == ["오래된 지도", "location", "작은 서랍"]
    for fact in result["facts"]:
        span = fact["evidence"]
        text = ambiguous + " 지금 오래된 지도는 어디에 있어?"
        assert text[span["start"]:span["end"]] == span["text"]


def test_actual_engine_counts_only_requested_group_without_routing():
    with patch.object(engine, "pick_graph", side_effect=AssertionError("local quantity must not route")):
        result = engine.answer("작은 구슬은 21개, 큰 구슬은 9개다. 큰 구슬 7개를 꺼냈다. 작은 구슬은 몇 개 남았어?")
    assert result[2] == "21개입니다."
