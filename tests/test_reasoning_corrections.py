from unittest.mock import patch

import pytest

from marco.reasoning.context import ReasoningContext
from tests.test_reasoning_persistence import create_app

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default

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


def test_definition_correction_rebuilds_its_later_action_without_changing_other_state():
    context = ReasoningContext()
    for text in ("공책은 서랍에 있었다.", "연필은 책상에 있었다.",
                 "보관하다는 물건을 가방으로 옮기는 것이다.", "하린이 공책을 보관했다."):
        context.turn(text, KG)
    changed = context.turn(
        "정정: 보관하다는 물건을 가방으로 옮기는 것이다. => 보관하다는 물건을 상자로 옮기는 것이다.", KG)
    assert changed["status"] == "observed"
    assert {(step.get("subject"), step.get("predicate")) for step in changed["transitions"]
            if step.get("operation") != "correction"} == {("공책", "location")}
    assert changed["verification"]["checks"][0]["affected_state"] == [["공책", "location"]]
    assert context.turn("지금 공책은 어디에 있어?", KG)["answer"] == "상자에 있습니다."
    assert context.turn("지금 연필은 어디에 있어?", KG)["answer"] == "책상에 있습니다."


def test_condition_correction_rebuilds_only_the_conditioned_event_result():
    context = ReasoningContext()
    context.turn("돌은 15개 있다.", KG)
    context.turn("공책은 4개 있다.", KG)
    context.turn("돌이 10개보다 많으면 돌 1개를 꺼냈다.", KG)
    changed = context.turn(
        "정정: 돌이 10개보다 많으면 돌 1개를 꺼냈다. => 돌이 20개보다 많으면 돌 1개를 꺼냈다.", KG)
    assert changed["status"] == "observed"
    assert context.turn("지금 돌은 몇 개야?", KG)["answer"] == "15개입니다."
    assert context.turn("지금 공책은 몇 개야?", KG)["answer"] == "4개입니다."


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
    assert saved["schema"] == "reasoning-context-v9"
    assert len(saved["corrections"]) == 1


def test_actual_ui_restart_preserves_a_definition_correction_and_its_later_effect(tmp_path):
    app = create_app(tmp_path)
    chat = app.conversations.create_chat()["id"]
    for text in ("공책은 서랍에 있었다.", "보관하다는 물건을 가방으로 옮기는 것이다.",
                 "하린이 공책을 보관했다.",
                 "정정: 보관하다는 물건을 가방으로 옮기는 것이다. => 보관하다는 물건을 상자로 옮기는 것이다."):
        app.turn(text, "definition_correction", conversation_id=chat)
    restarted = create_app(tmp_path)
    with patch.object(restarted.goals, "research") as research:
        result = restarted.turn("지금 공책은 어디에 있어?", "definition_correction_new", conversation_id=chat)
    research.assert_not_called()
    assert result["answer"]["answer"] == "상자에 있습니다."


def test_one_ui_conversation_learns_clarifies_corrects_and_reuses_without_touching_another_target(tmp_path):
    """설명 → 적용 → 짧은 보완 → 교정 → 다른 대상 재사용을 한 대화로 잇는다."""
    app = create_app(tmp_path)
    chat = app.conversations.create_chat()["id"]
    with patch.object(app.goals, "research", side_effect=AssertionError("state dialogue must stay local")):
        for text in ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
                     "민수 구슬은 8개 있다.", "지연 구슬은 3개 있다."):
            app.turn(text, "integrated_dialogue", conversation_id=chat)
        ask = app.turn("지연에게 베풀었다.", "integrated_dialogue", conversation_id=chat)
        assert ask["answer"]["trace"]["verdict"] == "조건부족"
        app.turn("민수야", "integrated_dialogue", conversation_id=chat)
        assert app.turn("지금 민수 구슬은 몇 개야?", "integrated_dialogue", conversation_id=chat)["answer"]["answer"] == "6개입니다."
        app.turn("정정: 민수 구슬은 8개 있다 => 민수 구슬은 10개 있다.",
                 "integrated_dialogue", conversation_id=chat)
        assert app.turn("지금 민수 구슬은 몇 개야?", "integrated_dialogue", conversation_id=chat)["answer"]["answer"] == "8개입니다."
        app.turn("가람 구슬은 7개 있다.", "integrated_dialogue", conversation_id=chat)
        app.turn("민수가 가람에게 베풀었다.", "integrated_dialogue", conversation_id=chat)
        assert app.turn("지금 가람 구슬은 몇 개야?", "integrated_dialogue", conversation_id=chat)["answer"]["answer"] == "9개입니다."
        assert app.turn("지금 민수 구슬은 몇 개야?", "integrated_dialogue", conversation_id=chat)["answer"]["answer"] == "6개입니다."
