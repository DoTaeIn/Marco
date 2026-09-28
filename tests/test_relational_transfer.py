import copy
import pytest

from graph_inference import closure, proof
from relational_semantics import RelationalParser
from marco.language.representation import SemanticParser
from state_engine import evaluate

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default


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


def test_converse_category_question_keeps_missing_reverse_proof_as_unknown():
    text = "모든 라핀은 수영한다. 나루는 수영한다. 이것만으로 나루가 라핀이라고 할 수 있는가?"
    parser = RelationalParser()
    parsed = parser.parse(text)
    assert parser.answer(parsed)["answer"] == "알 수 없습니다."
    # 반대로 소속 사실이 원문에 있으면 정방향 증거로만 긍정한다.
    proven = parser.parse("나루는 라핀이다. 이것만으로 나루가 라핀이라고 할 수 있는가?")
    assert parser.answer(proven)["answer"] == "네, 나루는 라핀입니다."


@pytest.mark.parametrize("text, expected", [
    ("준호는 우산이 없어서 비가 그칠 때까지 도서관에서 기다렸다. 준호가 바로 나가지 않은 이유는?",
     "우산이 없어서입니다."),
    ("민지는 신발이 없어서 역에서 기다렸다. 민지가 바로 나가지 않은 이유는?", "신발이 없어서입니다."),
    ("김 민수는 우산이 없어서 도서관에서 기다렸다. 김 민수가 바로 나가지 않은 이유는?",
     "우산이 없어서입니다."),
    ("준호는 비가 와서 도서관에서 기다렸다. 준호가 바로 나가지 않은 이유는?", "비가 와서입니다."),
    ("민지는 길이 막혀서 역에서 기다렸다. 민지가 바로 나가지 않은 이유는?", "길이 막혀서입니다."),
])
def test_cause_clause_and_reason_question_bind_through_the_same_subject(text, expected):
    parser = RelationalParser()
    parsed = parser.parse(text)
    assert parsed["원인"][0]["effect"] == parsed["이유물음"][0]["effect"] == "wait"
    result = parser.answer(parsed)
    assert result["answer"] == expected
    assert result["transitions"][0]["operation"] == "cause_for_effect"


def test_multiple_causes_for_one_subject_are_not_collapsed_to_one_reason():
    parser = RelationalParser()
    text = ("준호는 우산이 없어서 도서관에서 기다렸다. "
            "준호는 신발이 없어서 역에서 기다렸다. 준호가 바로 나가지 않은 이유는?")
    assert parser.answer(parser.parse(text)) is None


def test_a_reason_question_for_a_different_effect_does_not_take_the_waiting_cause():
    parser = RelationalParser()
    text = "준호는 우산이 없어서 도서관에서 기다렸다. 준호가 밥을 먹지 않은 이유는?"
    parsed = parser.parse(text)
    # 이해한 질문이라도 기다림의 원인을 식사하지 않은 결과에 붙이지 않는다.
    assert parsed["이유물음"][0]["effect"] == "밥을 먹지 않은"
    assert parser.answer(parsed) is None


def test_actual_dialogue_keeps_cause_and_binds_it_only_to_the_asked_effect(tmp_path):
    """원인은 대화에 남지만, 다른 결과의 이유로 재사용되지는 않는다."""
    from pathlib import Path
    import kgpack
    from views.kgpack_ui import AppState

    pack = tmp_path / "sample.kgpack"
    kgpack.write_pack(pack, [Path("graphs/graph_일상추론.kg")] + kgpack.model_files(Path(".")), root=Path("."))
    app = AppState(pack, overlay_root=tmp_path / "overlay")
    assert app.turn("준호는 우산이 없어서 도서관에서 기다렸다.", "cause_binding")["phase"] == "answer"
    answer = app.turn("준호가 바로 나가지 않은 이유는?", "cause_binding")
    assert answer["answer"]["answer"] == "우산이 없어서입니다."
    assert answer["answer"]["trace"]["reasoning"]["transitions"][0]["effect"] == "wait"
    mismatch = app.turn("준호가 밥을 먹지 않은 이유는?", "cause_binding")
    assert mismatch["answer"]["trace"]["verdict"] == "조건부족"
    assert mismatch["answer"]["answer"] != "우산이 없어서입니다."


def test_saved_dialogue_rebinds_the_causal_event_after_restart():
    from pathlib import Path
    from reasoning_context import ReasoningContext

    context = ReasoningContext()
    context.turn("준호는 우산이 없어서 도서관에서 기다렸다.", Path("graphs/graph_일상추론.kg"))
    restored = ReasoningContext()
    restored.restore(context.snapshot())
    result = restored.turn("준호가 바로 나가지 않은 이유는?", Path("graphs/graph_일상추론.kg"))
    assert result["status"] == "answered"
    assert result["answer"] == "우산이 없어서입니다."


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
