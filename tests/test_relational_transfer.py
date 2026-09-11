import copy
import pytest

from graph_inference import closure, proof
from relational_semantics import RelationalParser
from semantic_parser import SemanticParser
from state_engine import evaluate


def test_unseen_entities_and_three_step_chain():
    text = "서우는 도아보다 키가 크다. 도아는 해솔보다 키가 크다. 해솔은 라온보다 키가 크다. 서우와 라온 중 누가 더 커?"
    parsed = SemanticParser().parse(text)
    result = evaluate(parsed, "graphs/graph_일상추론.kg")
    assert result["answer"] == "서우입니다."
    assert sum("evidence" in step for step in result["transitions"]) == 3
    assert sum("rule" in step for step in result["transitions"]) == 2


def test_generic_rule_join_does_not_assume_relation_names():
    facts = [{"triple": ["a", "p", "b"], "evidence": "source1"},
             {"triple": ["b", "q", "c"], "evidence": "source2"}]
    rules = [{"id": "composition", "body": [["?x", "p", "?y"], ["?y", "q", "?z"]],
              "head": ["?x", "r", "?z"]}]
    result = closure(facts, rules)
    assert ("a", "r", "c") in result
    assert ("c", "r", "a") not in result
    assert len(proof(result, ["a", "r", "c"])) == 3


def test_cycle_and_unknown_relation_do_not_select_arbitrary_winner():
    parser = RelationalParser()
    for text in (
        "서우는 도아보다 키가 크다. 도아는 서우보다 키가 크다. 서우와 도아 중 누가 더 커?",
        "서우는 해솔보다 키가 크다. 도아는 해솔보다 키가 크다. 서우와 도아 중 누가 더 커?",
    ):
        assert parser.answer(parser.parse(text)) is None


def test_correction_transfers_to_unseen_names_without_changing_rules():
    parser = RelationalParser()
    question = "서우는 도아에 비해 키가 크다. 도아는 라온보다 키가 크다. 서우와 라온 중 누가 더 커?"
    assert parser.parse(question) is None
    old_rules = copy.deepcopy(parser.data["rules"])
    parser.learn({"text": "하루는 모래에 비해 키가 크다", "slots": {"a": "하루", "b": "모래"},
                  "meaning": {"triple": ["$a", "taller", "$b"]}})
    assert parser.answer(parser.parse(question))["answer"] == "서우입니다."
    assert parser.data["rules"] == old_rules
    assert "서우" not in str(parser.data)


def test_invented_relation_is_rejected_by_runtime():
    parsed = SemanticParser().parse("서우는 도아보다 키가 크다. 서우와 도아 중 누가 더 커?")
    parsed["relations"][0]["args"]["facts"][0]["triple"][0] = "라온"
    assert evaluate(parsed, "graphs/graph_일상추론.kg")["status"] == "unknown"


def test_correction_survives_reload_and_reaches_actual_entry():
    from bench.relational_learning import run
    report = run()
    assert report["before_passed"] == 0
    assert report["after_passed"] == report["total"] == 3


def test_conflicting_correction_is_rejected_without_mutation():
    parser = RelationalParser()
    before = copy.deepcopy(parser.data)
    with pytest.raises(ValueError, match="conflicts"):
        parser.learn({"text": "하루는 모래보다 키가 크다", "slots": {"a": "하루", "b": "모래"},
                      "meaning": {"triple": ["$b", "taller", "$a"]}})
    assert parser.data == before


def test_unseen_classes_compose_to_an_action():
    text = "모든 타빈은 제론이다. 모든 제론은 파로이다. 모든 파로는 노래한다. 루미는 타빈이다. 루미는 노래하는가?"
    result = evaluate(SemanticParser().parse(text), "graphs/graph_일상추론.kg")
    assert result["answer"] == "네, 루미는 노래합니다."
    assert sum("rule" in step for step in result["transitions"]) == 3


def test_ui_answers_graph_chain_without_web_research(tmp_path):
    from pathlib import Path
    from unittest.mock import patch
    import kgpack
    from views.kgpack_ui import AppState
    pack = tmp_path / "sample.kgpack"
    kgpack.write_pack(pack, [Path("graphs/graph_일상추론.kg")] + kgpack.model_files(Path(".")), root=Path("."))
    app = AppState(pack, overlay_root=tmp_path / "overlay")
    with patch.object(app.goals, "research") as research:
        result = app.turn("서우는 도아보다 키가 크다. 도아는 라온보다 키가 크다. 서우와 라온 중 누가 더 커?", "session_graph123")
    research.assert_not_called()
    assert result["phase"] == "answer"
    assert result["answer"]["answer"] == "서우입니다."
    assert result["answer"]["reasoning"]["transitions"]
