from unittest.mock import patch

import pytest

import engine
from output_contracts import apply
from tests.test_reasoning_persistence import create_app


@pytest.mark.parametrize("question,expected", [("9 + 7을 계산하고 숫자만 답해.", "16"),
                                               ("2x + 1 = 2야. 숫자만 답해주세요.", "1/2")])
def test_numeric_output_contract_reaches_engine_and_ui(tmp_path, question, expected):
    assert engine.answer(question)[2] == expected
    app = create_app(tmp_path)
    with patch.object(app.goals, "research") as research:
        result = app.turn(question, "session_format1")
    research.assert_not_called()
    assert result["answer"]["answer"] == expected
    assert result["answer"]["output_contract"] == "number_only"


def test_quoted_and_negated_requests_do_not_change_output():
    for question in ('"숫자만 답해"라는 문장을 설명해', '예시는 "숫자만 답해"',
                     '숫자만 답하지 마', '```숫자만 답해```'):
        assert apply(question, "16입니다.") == "16입니다."


def test_uncertain_or_multiple_numeric_answers_are_not_truncated():
    for answer in ("16일 수도 있습니다.", "16 또는 17입니다.", "조건이 2개 부족합니다.", "2아닙니다."):
        assert apply("숫자만 답해", answer) == answer
