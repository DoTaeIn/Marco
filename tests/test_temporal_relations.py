from graph_inference import closure, current_facts
from semantic_parser import SemanticParser
from state_engine import evaluate


def answer(text):
    return evaluate(SemanticParser().parse(text), "graphs/graph_일상추론.kg")


def test_latest_location_and_other_object_stay_separate():
    result = answer("공책은 서랍에 있었다. 지도가 가방에 있었다. 서우가 공책을 창고로 옮겼다. 지금 공책은 어디에 있어?")
    # The unsupported particle in the distractor must not be silently discarded.
    assert result["status"] == "unknown"
    result = answer("공책은 서랍에 있었다. 지도는 가방에 있었다. 서우가 공책을 창고로 옮겼다. 지금 공책은 어디에 있어?")
    assert result["answer"] == "창고에 있습니다."
    assert any(x.get("before") == "서랍" and x.get("after") == "창고" for x in result["transitions"])


def test_repeated_moves_use_latest_observation():
    result = answer("공책은 서랍에 있었다. 서우가 공책을 창고로 옮겼다. 도아가 공책을 가방으로 옮겼다. 지금 공책은 어디에 있어?")
    assert result["answer"] == "가방에 있습니다."


def test_state_projection_prevents_stale_facts_entering_closure():
    facts = [{"triple": ["entity", "status", value], "evidence": value} for value in ("old", "new")]
    projected, changes = current_facts(facts, ["status"])
    rules = [{"id": "old_state", "body": [["?x", "status", "old"]], "head": ["?x", "eligible", "yes"]}]
    result = closure(projected, rules)
    assert ("entity", "eligible", "yes") not in result
    assert len(changes) == 2


def test_ui_uses_latest_location_without_research(tmp_path):
    from pathlib import Path
    from unittest.mock import patch
    import kgpack
    from views.kgpack_ui import AppState
    pack = tmp_path / "temporal.kgpack"
    kgpack.write_pack(pack, [Path("graphs/graph_일상추론.kg")] + kgpack.model_files(Path(".")), root=Path("."))
    app = AppState(pack, overlay_root=tmp_path / "overlay")
    with patch.object(app.goals, "research") as research:
        result = app.turn("공책은 서랍에 있었다. 서우가 공책을 창고로 옮겼다. 지금 공책은 어디에 있어?", "session_temporal1")
    research.assert_not_called()
    assert result["answer"]["answer"] == "창고에 있습니다."
    assert result["phase"] == "answer"
