from pathlib import Path
from unittest.mock import patch

import engine
import kgpack
from reasoning_context import ReasoningContext
from views.kgpack_ui import AppState

KG = "graphs/graph_일상추론.kg"


def test_dialogue_replays_events_once_and_does_not_share_memory():
    first, second = engine.Dialogue(), engine.Dialogue()
    assert first.say("돌은 23개 있다.")[1] == "상태기억"
    assert first.say("돌 8개를 꺼냈다.")[1] == "상태기억"
    for _ in range(2):
        assert first.say("지금 돌은 몇 개야?")[2] == "15개입니다."
    assert second.say("지금 돌은 몇 개야?")[1] == "미지"


def test_context_combines_facts_across_turns_with_source_turn_ids():
    context = ReasoningContext()
    context.turn("서우는 도아보다 키가 크다.", KG)
    context.turn("도아는 라온보다 키가 크다.", KG)
    result = context.turn("서우와 라온 중 누가 더 커?", KG)
    assert result["answer"] == "서우입니다."
    assert {step["evidence"]["turn"] for step in result["transitions"] if "evidence" in step} == {0, 1}


def test_invalid_event_is_not_committed_and_unknown_text_is_not_a_fact():
    context = ReasoningContext()
    context.turn("돌은 3개 있다.", KG)
    assert context.turn("돌 8개를 꺼냈다.", KG)["status"] == "unresolved"
    assert context.turn("만약 돌을 전부 없애면 어떻게 될까?", KG) is None
    assert len(context.observations) == 1
    assert context.turn("지금 돌은 몇 개야?", KG)["answer"] == "3개입니다."


def test_whole_question_fact_is_not_replayed_twice():
    context = ReasoningContext()
    text = "돌은 23개 있다. 돌 8개를 꺼냈다. 지금 돌은 몇 개야?"
    assert context.turn(text, KG)["answer"] == "15개입니다."
    assert context.turn("지금 돌은 몇 개야?", KG)["answer"] == "15개입니다."


def test_ui_remembers_observation_and_separates_sessions(tmp_path):
    pack = tmp_path / "context.kgpack"
    kgpack.write_pack(pack, [Path(KG)] + kgpack.model_files(Path(".")), root=Path("."))
    app = AppState(pack, overlay_root=tmp_path / "overlay")
    with patch.object(app.goals, "research") as research:
        first = app.turn("공책은 서랍에 있었다.", "session_context1")
        moved = app.turn("서우가 공책을 창고로 옮겼다.", "session_context1")
        answer = app.turn("지금 공책은 어디에 있어?", "session_context1")
        other = app.turn("지금 공책은 어디에 있어?", "session_context2")
    research.assert_not_called()
    assert first["answer"]["trace"]["verdict"] == moved["answer"]["trace"]["verdict"] == "상태기억"
    assert answer["answer"]["answer"] == "창고에 있습니다."
    assert other["answer"]["trace"]["verdict"] == "조건부족"
