import pytest

from semantic_parser import SemanticParser
from state_engine import evaluate

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default


def answer(text):
    return evaluate(SemanticParser().parse(text), "graphs/graph_일상추론.kg")


def test_quantity_updates_compose_with_source_trace():
    result = answer("상자에 돌이 23개 있다. 8개를 꺼내고 2개를 넣었다. 지금 돌은 몇 개야?")
    assert result["answer"] == "17개입니다."
    steps = [s for s in result["transitions"] if s.get("operation") == "quantity_update"]
    assert [(s["before"], s["after"]) for s in steps] == [(23, 15), (15, 17)]


def test_connected_clauses_keep_one_quantity_subject_without_a_chain_template():
    """절 경계·활용·빈 대상 결합이 순서대로 작동해야 한다.

    `있었고`를 다른 시작꼴로 바꾸거나, 문장 전체를 수량연쇄 사례로 등록해서
    맞추지 않는다. 각 절은 개별 사실이고, 비어 있는 대상만 앞의 유일한 상태와
    공통 상태 전이에서 잇는다.
    """
    text = "단추는 21개 있었고 4개를 꺼낸 뒤 두 개를 넣었어. 남은 단추는 몇 개야?"
    result = answer(text)
    assert result["answer"] == "19개입니다."
    changes = [step for step in result["transitions"] if step.get("operation") == "quantity_update"]
    assert [(step["subject"], step["before"], step["after"]) for step in changes] == [
        ("단추", 21, 17), ("단추", 17, 19)]
    assert all("꺼낸 뒤" not in str(step["subject"]) for step in changes)


def test_separate_turns_reuse_the_same_elided_quantity_subject():
    from reasoning_context import ReasoningContext

    context = ReasoningContext()
    assert context.turn("공을 14개 가지고 있었어", "graphs/graph_일상추론.kg")["status"] == "observed"
    changed = context.turn("다섯 개를 덜어낸 뒤 세 개를 보탰어", "graphs/graph_일상추론.kg")
    assert [(step["before"], step["after"]) for step in changed["transitions"]
            if step["operation"] == "quantity_update"] == [(14, 9), (9, 12)]
    assert context.turn("남은 공은 몇 개야?", "graphs/graph_일상추론.kg")["answer"] == "12개입니다."


@pytest.mark.parametrize("text, expected", [
    ("공 14개 중 다섯 개를 덜어낸 뒤 세 개를 보탰어. 남은 공은 몇 개야?", "12개입니다."),
    ("단추 21개 중 4개를 꺼낸 뒤 두 개를 넣었어. 남은 단추는 몇 개야?", "19개입니다."),
    ("공을 14개 가지고 있었는데 다섯 개를 덜어낸 뒤 세 개를 보탰어. 남은 공은 몇 개야?", "12개입니다."),
    ("단추는 21개 있었다가 4개를 꺼낸 뒤 두 개를 넣었어. 남은 단추는 몇 개야?", "19개입니다."),
])
def test_quantity_chain_binds_initial_amount_operations_and_remaining_question(text, expected):
    """물건·수·표면 동작이 달라도 선언한 연쇄 구조를 같은 전이로 읽는다."""
    result = answer(text)
    assert result["answer"] == expected
    assert [step["operation"] for step in result["transitions"][:3]] == [
        "state_update", "quantity_update", "quantity_update"]


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
    # round 5: the box said with 에 holds the stones (상자 돌), so the answer may name it (상자는 17개입니다)
    assert result["answer"]["answer"] in ("17개입니다.", "상자는 17개입니다.")


def test_ui_answers_declared_quantity_chain_without_research(tmp_path):
    from pathlib import Path
    from unittest.mock import patch
    import kgpack
    from views.kgpack_ui import AppState
    pack = tmp_path / "quantity-chain.kgpack"
    kgpack.write_pack(pack, [Path("graphs/graph_일상추론.kg")] + kgpack.model_files(Path(".")), root=Path("."))
    app = AppState(pack, overlay_root=tmp_path / "overlay")
    with patch.object(app.goals, "research") as research:
        result = app.turn("단추 21개 중 4개를 꺼낸 뒤 두 개를 넣었어. 남은 단추는 몇 개야?", "quantity_chain")
    research.assert_not_called()
    assert result["answer"]["answer"] == "19개입니다."


def test_ui_answers_declared_quantity_chain_start_form_without_research(tmp_path):
    from pathlib import Path
    from unittest.mock import patch
    import kgpack
    from views.kgpack_ui import AppState
    pack = tmp_path / "quantity-chain-start.kgpack"
    kgpack.write_pack(pack, [Path("graphs/graph_일상추론.kg")] + kgpack.model_files(Path(".")), root=Path("."))
    app = AppState(pack, overlay_root=tmp_path / "overlay")
    with patch.object(app.goals, "research") as research:
        result = app.turn("공을 14개 가지고 있었는데 다섯 개를 덜어낸 뒤 세 개를 보탰어. 남은 공은 몇 개야?",
                          "quantity_chain_start")
    research.assert_not_called()
    assert result["answer"]["answer"] == "12개입니다."


def test_ui_answers_connected_clauses_through_the_packed_dialogue_path(tmp_path):
    """구조 직접 입력이 아니라 팩을 다시 읽는 앱 대화에서도 같은 절을 잇는다."""
    from pathlib import Path
    from unittest.mock import patch
    import kgpack
    from views.kgpack_ui import AppState

    pack = tmp_path / "connected-clauses.kgpack"
    kgpack.write_pack(pack, [Path("graphs/graph_일상추론.kg")] + kgpack.model_files(Path(".")), root=Path("."))
    app = AppState(pack, overlay_root=tmp_path / "overlay")
    with patch.object(app.goals, "research") as research:
        result = app.turn("단추는 21개 있었고 4개를 꺼낸 뒤 두 개를 넣었어. 남은 단추는 몇 개야?",
                          "connected_clauses")
    research.assert_not_called()
    assert result["phase"] == "answer"
    assert result["answer"]["answer"] == "19개입니다."
