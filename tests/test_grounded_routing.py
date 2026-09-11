"""전역 라우팅은 유사도만으로 도메인 답변을 단정하지 않는다."""

import json
from pathlib import Path

import engine


def test_weak_graph_similarity_does_not_leak_an_unrelated_domain_reply():
    """후보가 있어도 그래프 안의 근거가 없으면 보편적인 미지로 끝낸다."""
    name, verdict, answer = engine.answer("서버 상태 확인해줘")

    assert name is None
    assert verdict == "미지"
    assert "반려동물" not in answer


def test_grounded_graph_answer_is_preserved_after_candidate_validation():
    name, verdict, answer = engine.answer("12만원 나왔어")

    assert name == "graphs/graph_정산_나눠내기.kg"
    assert verdict not in ("미지", "B2")
    assert answer


def test_dialogue_applies_the_same_grounding_gate_when_switching_topics():
    conversation = engine.Dialogue()
    name, verdict, answer = conversation.say("서버 상태 확인해줘")

    assert name is None
    assert verdict == "미지"
    assert "반려동물" not in answer


def test_dialogue_keeps_a_grounded_session_for_follow_up_values():
    conversation = engine.Dialogue()
    conversation.say("12만원 나왔어")
    name, verdict, answer = conversation.say("3명이야")

    assert name == "graphs/graph_정산_나눠내기.kg"
    assert verdict == "인정"
    assert "40000원" in answer


def test_out_of_scope_benchmark_never_uses_an_unconfirmed_graph_prompt():
    """실시간·개인 정보·추천 등 그래프 밖 요청은 전역 입구에서 보류한다."""
    benchmark = json.loads(Path("data/benchmarks/라우팅_밖.json").read_text(encoding="utf-8"))

    for item in benchmark:
        question = item["질문"] if isinstance(item, dict) else item
        name, verdict, _answer = engine.answer(question)
        assert (name, verdict) == (None, "미지"), question
