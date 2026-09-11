from pathlib import Path
from unittest.mock import patch

import pytest
import kgpack
from conversation_store import ConversationStore
from reasoning_context import ReasoningContext
from views.kgpack_ui import AppState


def create_app(tmp_path):
    pack = tmp_path / "saved.kgpack"
    if not pack.exists():
        kgpack.write_pack(pack, [Path("graphs/graph_일상추론.kg")] + kgpack.model_files(Path(".")), root=Path("."))
    app = AppState(pack, overlay_root=tmp_path / "overlay")
    app.conversations = ConversationStore(tmp_path / "conversations.json")
    return app


def test_actual_app_restart_restores_only_committed_observations(tmp_path):
    app = create_app(tmp_path)
    chat = app.conversations.create_chat()["id"]
    other = app.conversations.create_chat()["id"]
    for text in ("돌은 23개 있다.", "돌 8개를 꺼냈다.", "돌 99개를 꺼냈다."):
        app.turn(text, "session_saved1", conversation_id=chat)
    saved = app.conversations.reasoning_state(chat)
    assert len(saved["observations"]) == 2
    restarted = create_app(tmp_path)
    with patch.object(restarted.goals, "research") as research:
        for _ in range(2):
            result = restarted.turn("지금 돌은 몇 개야?", "session_new123", conversation_id=chat)
            assert result["answer"]["answer"] == "15개입니다."
        isolated = restarted.turn("지금 돌은 몇 개야?", "session_new123", conversation_id=other)
    research.assert_not_called()
    assert isolated["answer"]["trace"]["verdict"] == "조건부족"
    assert len(restarted.conversations.reasoning_state(chat)["observations"]) == 2


def test_save_failure_rolls_back_both_chat_and_memory(tmp_path):
    app = create_app(tmp_path)
    chat = app.conversations.create_chat()["id"]
    app.turn("돌은 23개 있다.", "session_saved1", conversation_id=chat)
    with patch.object(app.conversations, "_save", side_effect=OSError("disk unavailable")):
        with pytest.raises(OSError):
            app.turn("돌 8개를 꺼냈다.", "session_saved1", conversation_id=chat)
    assert len(app.conversations.get_chat(chat)["turns"]) == 1
    app.turn("돌 8개를 꺼냈다.", "session_saved1", conversation_id=chat)
    result = app.turn("지금 돌은 몇 개야?", "session_saved1", conversation_id=chat)
    assert result["answer"]["answer"] == "15개입니다."


def test_legacy_chat_is_not_reinterpreted_as_verified_memory(tmp_path):
    app = create_app(tmp_path)
    chat = app.conversations.create_chat()["id"]
    app.conversations.append_turn(chat, "돌은 999개 있다.", "검증되지 않은 답변", "answer")
    result = app.turn("지금 돌은 몇 개야?", "session_legacy1", conversation_id=chat)
    assert result["answer"]["trace"]["verdict"] == "조건부족"


def test_invalid_snapshot_does_not_replace_valid_memory():
    context = ReasoningContext()
    context.restore({"schema": "reasoning-context-v1", "observations": ["돌은 23개 있다."]})
    with pytest.raises(ValueError):
        context.restore({"schema": "reasoning-context-v1", "observations": [123]})
    assert context.observations == ["돌은 23개 있다."]
