import json
from pathlib import Path
from unittest.mock import patch

import pytest

import engine
from numeral_semantics import parse_numeral

VOCAB = json.loads((Path(__file__).resolve().parents[1] / "styles/한국어.json").read_text())["관계해석"]["numerals"]


@pytest.mark.parametrize("text,expected", [("열두", "12"), ("서른둘", "32"), ("아흔 아홉", "99"),
                                          ("이백십칠", "217"), ("구천팔백칠십육", "9876"), ("영", "0")])
def test_composed_numerals(text, expected):
    assert parse_numeral(text, VOCAB) == expected


@pytest.mark.parametrize("text", ["이삼", "십백", "백백", "", "여러", "두세", "영십"])
def test_ambiguous_or_malformed_numerals_are_not_values(text):
    assert parse_numeral(text, VOCAB) is None


def test_multiple_groups_native_and_sino_numbers_reach_engine_without_lookup():
    text = "파란 구슬은 서른두 개 있다. 초록 구슬은 이백십칠 개 있다. 파란 구슬 다섯 개를 꺼냈다. 지금 파란 구슬은 몇 개야?"
    with patch.object(engine, "pick_graph", side_effect=AssertionError("must compute locally")):
        assert engine.answer(text)[2] == "27개입니다."


def test_number_words_in_entity_names_are_not_replaced():
    from relational_semantics import RelationalParser
    parsed = RelationalParser().parse("공은 여덟 개 있다. 지금 공은 몇 개야?")
    assert parsed["facts"][0]["triple"] == ["공", "count", "8"]
