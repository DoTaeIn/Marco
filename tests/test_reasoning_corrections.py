from unittest.mock import patch

import pytest

from reasoning_context import ReasoningContext
from tests.test_reasoning_persistence import create_app

KG = "graphs/graph_일상추론.kg"


def test_correction_replays_later_quantity_events_instead_of_resetting_total():
    context = ReasoningContext()
    context.turn("돌은 23개 있다.", KG)
    context.turn("돌 8개를 꺼냈다.", KG)
    result = context.turn("정정: 돌은 23개 있다 => 돌은 31개 있다.", KG)
    assert result["status"] == "observed"
    assert len(context.observations) == 2
    for _ in range(2):
        assert context.turn("지금 돌은 몇 개야?", KG)["answer"] == "23개입니다."
    assert context.snapshot()["corrections"][0]["before"] == "돌은 23개 있다."


def test_correction_retracts_derived_conclusions_and_preserves_unrelated_facts():
    context = ReasoningContext()
    context.turn("소라는 다미보다 키가 크다.", KG)
    context.turn("다미는 유리보다 키가 크다.", KG)
    assert context.turn("소라와 유리 중 누가 더 커?", KG)["answer"] == "소라입니다."
    context.turn("정정: 소라는 다미보다 키가 크다 => 소라는 다미보다 키가 크지 않다.", KG)
    assert context.turn("소라와 유리 중 누가 더 커?", KG)["status"] == "unresolved"
    assert context.turn("다미와 유리 중 누가 더 커?", KG)["answer"] == "다미입니다."


def test_invalid_correction_is_atomic_and_duplicate_targets_are_ambiguous():
    context = ReasoningContext()
    context.turn("돌은 23개 있다.", KG)
    context.turn("돌 8개를 꺼냈다.", KG)
    snapshot = context.snapshot()
    assert context.turn("정정: 돌은 23개 있다 => 돌은 3개 있다.", KG)["status"] == "unresolved"
    assert context.snapshot() == snapshot
    context.turn("돌 8개를 꺼냈다.", KG)
    assert context.turn("정정: 돌 8개를 꺼냈다 => 돌 2개를 꺼냈다.", KG)["status"] == "unresolved"
    assert not context.corrections


def test_actual_ui_restart_preserves_correction_and_save_failure_rolls_back(tmp_path):
    app = create_app(tmp_path)
    chat = app.conversations.create_chat()["id"]
    for text in ("돌은 23개 있다.", "돌 8개를 꺼냈다."):
        app.turn(text, "session_correct1", conversation_id=chat)
    correction = "정정: 돌은 23개 있다 => 돌은 31개 있다."
    with patch.object(app.conversations, "_save", side_effect=OSError("disk unavailable")):
        with pytest.raises(OSError):
            app.turn(correction, "session_correct1", conversation_id=chat)
    assert not app.conversations.reasoning_state(chat)["corrections"]
    with patch.object(app.goals, "research") as research:
        app.turn(correction, "session_correct1", conversation_id=chat)
    research.assert_not_called()
    restarted = create_app(tmp_path)
    result = restarted.turn("지금 돌은 몇 개야?", "session_correct2", conversation_id=chat)
    assert result["answer"]["answer"] == "23개입니다."
    saved = restarted.conversations.reasoning_state(chat)
    assert saved["schema"] == "reasoning-context-v2"
    assert len(saved["corrections"]) == 1
