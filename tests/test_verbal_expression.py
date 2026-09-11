from unittest.mock import patch

import pytest

import engine
import expression_graph
from tests.test_reasoning_persistence import create_app


@pytest.mark.parametrize("text,expected", [
    ("어떤 수의 네 배에 6을 더하면 34가 돼. 그 수는 얼마야?", "7입니다."),
    ("어떤 수의 다섯 배에서 7을 빼면 18이 된다. 그 수는 얼마야?", "5입니다."),
    ("어떤 수의 두 배의 세 배에 1을 더하면 43이 됩니다. 그 수는 얼마인가요?", "7입니다."),
    ("어떤 수를 둘로 나누면 9가 돼. 그 수는 얼마야?", "18입니다."),
])
def test_composition_reuses_graph_solver_and_actual_entry(text, expected):
    graph = expression_graph.parse(text)
    assert graph and graph["variable"] == "x"
    with patch.object(engine, "pick_graph", side_effect=AssertionError("must solve locally")):
        assert engine.answer(text)[2] == expected


def test_full_input_required_and_unknown_parts_not_discarded():
    for text in ("어떤 수의 배에 6을 더하면 34가 돼. 그 수는 얼마야?",
                 "아마 어떤 수의 네 배에 6을 더하면 34가 돼. 그 수는 얼마야?",
                 "어떤 수의 네 배에 6을 더하면 34가 돼. 다른 조건도 있어. 그 수는 얼마야?"):
        assert expression_graph.parse(text) is None


def test_ui_solves_verbal_equation_without_research(tmp_path):
    app = create_app(tmp_path)
    with patch.object(app.goals, "research") as research:
        result = app.turn("어떤 수의 여섯 배에 2를 더하면 44가 돼. 그 수는 얼마야?", "session_verbal01")
    research.assert_not_called()
    assert result["answer"]["answer"] == "7입니다."
