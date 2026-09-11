from graph_inference import closure, current_facts
from relational_semantics import RelationalParser


def fact(a, p, b, **metadata):
    return {"triple": [a, p, b], "evidence": {"text": f"{a} {p} {b}"}, **metadata}


def test_denied_intermediate_cannot_support_downstream_conclusion():
    rules = [
        {"id": "first", "body": [["?a", "p", "?b"]], "head": ["?a", "q", "?b"]},
        {"id": "second", "body": [["?a", "q", "?b"]], "head": ["?a", "r", "?b"]},
    ]
    known = closure([fact("x", "p", "y"), fact("x", "q", "y", polarity=False),
                     fact("u", "p", "v")], rules)
    assert ("x", "p", "y") in known
    assert ("x", "r", "y") not in known
    assert ("u", "r", "v") in known


def test_planned_numeric_update_does_not_change_current_quantity():
    facts = [fact("item", "count", "10"), fact("item", "add", "7", modality="planned")]
    projected, changes = current_facts(facts, ["count"], {"add": {"target": "count", "factor": 1}})
    assert projected[0]["triple"] == ["item", "count", "10"]
    assert changes[-1]["operation"] == "nonactual_observation"


def test_negative_annotation_learning_transfers_after_reload(tmp_path):
    parser = RelationalParser()
    correction = {"text": "하루의 키는 모래를 넘지 않는다", "slots": {"a": "하루", "b": "모래"},
                  "meaning": {"triple": ["$a", "taller", "$b"], "polarity": False}}
    assert parser.learn(correction)
    path = tmp_path / "model.json"
    parser.save(path)
    restored = RelationalParser(model_path=path)
    text = "유나의 키는 미소를 넘지 않는다. 유나와 미소 중 누가 더 커?"
    parsed = restored.parse(text)
    assert parsed["facts"][0]["polarity"] is False
    assert restored.answer(parsed) is None


def test_engine_does_not_route_away_from_recognized_conflict():
    from unittest.mock import patch
    import engine
    text = "소라는 다미보다 키가 크다. 소라는 다미보다 키가 크지 않다. 소라와 다미 중 누가 더 커?"
    with patch.object(engine, "pick_graph", side_effect=AssertionError("conflict must not become retrieval")):
        assert engine.answer(text)[1] == "미지"


def test_ui_preserves_location_for_planned_move_without_web(tmp_path):
    from pathlib import Path
    from unittest.mock import patch
    import kgpack
    from views.kgpack_ui import AppState
    pack = tmp_path / "sample.kgpack"
    kgpack.write_pack(pack, [Path("graphs/graph_일상추론.kg")] + kgpack.model_files(Path(".")), root=Path("."))
    app = AppState(pack, overlay_root=tmp_path / "overlay")
    with patch.object(app.goals, "research") as research:
        result = app.turn("우표는 봉투에 있었다. 소라가 우표를 서랍으로 옮길 예정이다. 지금 우표는 어디에 있어?", "session_modal123")
    research.assert_not_called()
    assert result["answer"]["answer"] == "봉투에 있습니다."
