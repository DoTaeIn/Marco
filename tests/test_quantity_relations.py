import pytest

from semantic_parser import SemanticParser
from state_engine import evaluate


def answer(text):
    return evaluate(SemanticParser().parse(text), "graphs/graph_일상추론.kg")


def test_quantity_updates_compose_with_source_trace():
    result = answer("상자에 돌이 23개 있다. 8개를 꺼내고 2개를 넣었다. 지금 돌은 몇 개야?")
    assert result["answer"] == "17개입니다."
    steps = [s for s in result["transitions"] if s.get("operation") == "quantity_update"]
    assert [(s["before"], s["after"]) for s in steps] == [(23, 15), (15, 17)]


def test_explicit_quantity_subject_is_not_confused_with_distractor():
    result = answer("돌은 23개 있다. 사과는 7개 있다. 돌 8개를 꺼냈다. 지금 사과는 몇 개야?")
    assert result["answer"] == "7개입니다."


@pytest.mark.parametrize("text", [
    "돌은 23개 있다. 사과는 7개 있다. 8개를 꺼냈다. 지금 돌은 몇 개야?",
    "돌 8개를 꺼냈다. 지금 돌은 몇 개야?",
    "돌은 3개 있다. 돌 8개를 꺼냈다. 지금 돌은 몇 개야?",
    "상자에 돌이 23개 있다. 가방에 돌이 7개 있다. 2개를 꺼냈다. 지금 돌은 몇 개야?",
])
def test_quantity_preconditions_prevent_guessed_answers(text):
    assert answer(text)["status"] == "unknown"


def test_quantity_failure_has_actionable_diagnosis():
    from relational_semantics import RelationalParser
    report = RelationalParser().diagnose("돌 8개를 꺼냈다. 지금 돌은 몇 개야?")
    assert report["stage"] == "state_or_inference_precondition"
    assert report["reason"] == "missing_initial_quantity"


def test_quantity_expression_correction_transfers_after_model_reload(tmp_path, monkeypatch):
    import engine
    from relational_semantics import RelationalParser
    parser = RelationalParser()
    model = tmp_path / "model.json"
    parser.save(model)
    monkeypatch.setenv("NAI_RELATIONAL_MODEL", str(model))
    cases = [
        ("돌은 23개 있다. 돌 8개를 덜어냈다. 지금 돌은 몇 개야?", "15개입니다."),
        ("사과는 19개 있다. 사과 3개를 덜어냈다. 지금 사과는 몇 개야?", "16개입니다."),
    ]
    assert all(engine.answer(text)[1] == "미지" for text, _ in cases)
    parser.learn({"text": "구슬 4개를 덜어냈다", "slots": {"item": "구슬", "n": "4"},
                  "meaning": {"triple": ["$item", "count_remove", "$n"]}})
    parser.save(model)
    assert all(engine.answer(text)[2] == expected for text, expected in cases)


def test_ui_answers_quantity_events_without_research(tmp_path):
    from pathlib import Path
    from unittest.mock import patch
    import kgpack
    from views.kgpack_ui import AppState
    pack = tmp_path / "quantity.kgpack"
    kgpack.write_pack(pack, [Path("graphs/graph_일상추론.kg")] + kgpack.model_files(Path(".")), root=Path("."))
    app = AppState(pack, overlay_root=tmp_path / "overlay")
    with patch.object(app.goals, "research") as research:
        result = app.turn("상자에 돌이 23개 있다. 8개를 꺼내고 2개를 넣었다. 지금 돌은 몇 개야?", "session_quantity1")
    research.assert_not_called()
    assert result["phase"] == "answer"
    assert result["answer"]["answer"] == "17개입니다."
