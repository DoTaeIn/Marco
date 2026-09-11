"""전역 입구는 인증된 상태 추론만 그래프 공리로 계산한다."""

import json
from pathlib import Path

import engine


def test_global_entry_uses_daily_reasoning_kg_for_held_out_state_relations():
    held_out = json.loads(Path("data/benchmarks/semantic_reasoning.json").read_text(encoding="utf-8"))["held_out"]

    for case in held_out:
        path, verdict, answer = engine.answer(case["input"])
        if case.get("answer"):
            assert (path, verdict, answer) == (
                "graphs/graph_일상추론.kg", "상태추론", case["answer"])
        elif case["id"] == "invalid-premise":
            assert (path, verdict) == ("graphs/graph_일상추론.kg", "전제오류")
            assert "전제" in answer
        else:
            assert (path, verdict) == (None, "미지")


def test_state_entry_keeps_the_full_source_graph_path_for_traceability():
    path, verdict, answer = engine.answer("1 더하기 1은 얼마야?")

    assert path == "graphs/graph_일상추론.kg"
    assert verdict == "상태추론"
    assert answer == "2입니다."


def test_global_state_entry_uses_declared_multiply_and_divide_axioms():
    for question, expected in (("3 곱하기 4는 얼마야?", "12입니다."),
                               ("12 나누기 3은 얼마야?", "4입니다.")):
        path, verdict, answer = engine.answer(question)
        assert (path, verdict, answer) == ("graphs/graph_일상추론.kg", "상태추론", expected)


def test_reported_linear_equation_stays_on_the_verified_state_path():
    path, verdict, answer = engine.answer("3x + 1 = 7이래. x는 얼마야?")

    assert (path, verdict, answer) == ("graphs/graph_일상추론.kg", "상태추론", "2입니다.")


def test_division_by_zero_is_not_promoted_to_a_state_answer():
    path, verdict, _answer = engine.answer("12 나누기 0은 얼마야?")

    assert (path, verdict) == (None, "미지")


def test_dialogue_entry_uses_the_same_verified_state_path_as_single_turn_guide():
    conversation = engine.Dialogue()
    for question, expected in (("7과 5를 더한 값은?", "12입니다."),
                               ("달리던 중 3위 주자를 앞질렀다. 나는 몇 위인가?", "3등입니다.")):
        assert conversation.say(question) == (
            "graphs/graph_일상추론.kg", "상태추론", expected)
