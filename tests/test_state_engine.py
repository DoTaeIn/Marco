"""상태 전이는 KG에 선언된 공리와 검증된 JSON이 함께 있어야만 답한다."""
from pathlib import Path

import state_engine


KG = Path("graphs/graph_일상추론.kg")


def state(relation, query_kind="value"):
    return {"accepted": True, "intent": "question", "relations": [relation],
            "query": {"kind": query_kind, "target": "answer"}}


def test_generic_state_transitions_are_grounded_in_daily_reasoning_kg():
    cases = (
        ({"type": "arithmetic", "args": {"operator": "+", "left": 1, "right": 1}}, "2입니다."),
        ({"type": "linear_equation", "args": {"variable": "x", "coefficient": 3, "constant": 1, "right": 7}}, "2입니다."),
        ({"type": "parallel_completion", "args": {"duration": 1, "unit": "시간", "simultaneous": True, "independent": True}}, "1시간입니다."),
        ({"type": "age_difference", "args": {"later_age": 70, "age_difference": 3}}, "67살입니다."),
        ({"type": "rank_overtake", "args": {"overtaken_rank": 2}}, "2등입니다."),
        ({"type": "co_moving_reference", "args": {"visible_count": 5, "same_reference_frame": True}}, "5칸입니다."),
        ({"type": "indivisible_process", "args": {"process": "임신 출산", "duration": 9, "unit": "개월", "single_output": True}}, "9개월입니다."),
    )
    for relation, answer in cases:
        outcome = state_engine.evaluate(state(relation), KG)
        assert outcome["status"] == "answered", outcome
        assert outcome["answer"] == answer
        assert outcome["verification"]["checks"][0]["ok"] is True


def test_unitary_premise_is_rejected_only_when_kg_declares_it():
    relation = {"type": "unitary_concept", "args": {"concept": "구멍", "fractional_premise": True}}
    outcome = state_engine.evaluate(state(relation, "validity"), KG)
    assert outcome["status"] == "premise_invalid"
    assert "전제" in outcome["answer"]


def test_undeclared_operator_does_not_answer_when_a_kg_is_present():
    relation = {"type": "comparison", "args": {"left": 1, "right": 2}}
    outcome = state_engine.evaluate(state(relation), KG)
    assert outcome["status"] == "unknown"
    assert outcome["verification"]["checks"][0]["reason"] == "operator_not_declared_in_kg"


def test_zero_coefficient_equation_is_not_promoted_to_an_answer():
    relation = {"type": "linear_equation", "args": {"coefficient": 0, "constant": 1, "right": 7}}
    outcome = state_engine.evaluate(state(relation), KG)
    assert outcome["status"] == "unknown"
    assert outcome["verification"]["checks"][0]["reason"] == "invalid_linear_equation"
