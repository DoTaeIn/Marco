import pytest

from marco.language.representation import SemanticParser
from marco.reasoning.state import evaluate

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default


@pytest.mark.parametrize("text,expected", [
    ("9 + 2 * 6는?", "21입니다."),
    ("(9 + 2) * 6는?", "66입니다."),
    ("7z - 5 = 30이면?", "5입니다."),
    ("7x + 5 = 3x + 17이면?", "3입니다."),
    ("(4x + 2) / 2 = 9이면?", "4입니다."),
    ("2x + 1 = 2이면?", "1/2입니다."),
])
def test_complete_expression_composition(text, expected):
    result = evaluate(SemanticParser().parse(text), "graphs/graph_일상추론.kg")
    assert result["answer"] == expected
    assert result["transitions"]


def test_forged_operation_graph_is_rejected():
    state = SemanticParser().parse("9 + 2 * 6는?")
    state["relations"][0]["args"]["expression_graph"]["nodes"][0]["value"] = "100"
    assert evaluate(state, "graphs/graph_일상추론.kg")["status"] == "unknown"


@pytest.mark.parametrize("text", ["x*x + 1 = 9이면?", "3 / 0은?", "2x+1=2x+8이면?"])
def test_unsupported_equations_do_not_produce_partial_answers(text):
    assert evaluate(SemanticParser().parse(text), "graphs/graph_일상추론.kg")["status"] == "unknown"
