from marco.language.realizer.composer import compare, compose
from unittest.mock import patch
from pathlib import Path
import pytest

from tests.test_reasoning_persistence import create_app

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default


def test_composer_selects_only_grounded_sentences_and_respects_the_limit():
    evidence = [
        {"text": "첫 근거입니다.", "source": "a"},
        {"text": "둘째 근거입니다.", "source": "b"},
        {"text": "출처 없는 말", "source": ""},
    ]
    result = compose("request.summary", evidence, limit=2)
    assert result["answer"] == "- 첫 근거입니다.\n- 둘째 근거입니다."
    assert result["selected"] == evidence[:2]
    assert "출처 없는" not in result["answer"]


def test_summary_uses_an_independent_source_before_more_sentences_from_the_first_one():
    result = compose("request.summary", [
        {"text": "첫 출처 첫 문장", "source": "a"},
        {"text": "첫 출처 둘째 문장", "source": "a"},
        {"text": "둘째 출처 첫 문장", "source": "b"},
    ], limit=3)
    assert result["selected"] == [
        {"text": "첫 출처 첫 문장", "source": "a"},
        {"text": "둘째 출처 첫 문장", "source": "b"},
        {"text": "첫 출처 둘째 문장", "source": "a"},
    ]


def test_composer_does_not_invent_a_comparison_claim():
    result = compare([
        {"label": "A", "text": "A의 정의", "source": "one"},
        {"label": "B", "text": "B의 정의", "source": "two"},
    ])
    assert result["answer"] == "**A** — A의 정의\n\n**B** — B의 정의"
    assert result["selected"][0]["source"] == "one"


def test_plan_keeps_only_source_backed_action_candidates():
    result = compose("request.plan", [
        {"text": "문제의 원인을 확인한다.", "source": "a", "actionable": False},
        {"text": "배출을 줄여야 한다.", "source": "b", "actionable": True},
    ])
    assert result["answer"] == "1. 배출을 줄여야 한다."
    assert result["selected"] == [{"text": "배출을 줄여야 한다.", "source": "b"}]


def test_structured_cause_and_dependencies_select_their_declared_relations():
    evidence = [
        {"id": "effect", "text": "물의 산성도가 높아진다.", "source": "a", "relation": "effect",
         "depends_on": ["cause"]},
        {"id": "cause", "text": "이산화탄소가 바닷물에 녹기 때문이다.", "source": "a", "relation": "cause"},
        {"id": "measure", "text": "배출량을 측정한다.", "source": "b", "actionable": True},
        {"id": "reduce", "text": "배출을 줄인다.", "source": "b", "actionable": True,
         "depends_on": ["measure"]},
    ]
    explained = compose("request.explain", evidence)
    assert explained["mode"] == "grounded_causal_explanation"
    assert explained["selected"] == [
        {"text": "이산화탄소가 바닷물에 녹기 때문이다.", "source": "a"},
        {"text": "물의 산성도가 높아진다.", "source": "a"},
    ]
    planned = compose("request.plan", list(reversed(evidence)))
    assert planned["mode"] == "grounded_dependency_plan"
    assert planned["answer"] == "1. 배출량을 측정한다.\n2. 배출을 줄인다."


def test_plan_selects_only_the_actions_that_reach_the_declared_goal_and_state():
    evidence = [
        {"id": "measure", "text": "배출량을 측정한다.", "source": "a", "actionable": True},
        {"id": "reduce", "text": "배출을 줄인다.", "source": "a", "actionable": True,
         "depends_on": ["measure"], "achieves": ["해양 산성화 완화"],
         "requires_state": [["배출량", "count", "10"]]},
        {"id": "distract", "text": "해변을 청소한다.", "source": "b", "actionable": True,
         "achieves": ["해변 미관 개선"]},
    ]
    planned = compose("request.plan", evidence, goal="해양 산성화",
                       state=[["배출량", "count", "10"]])
    assert planned["answer"] == "1. 배출량을 측정한다.\n2. 배출을 줄인다."
    assert compose("request.plan", evidence, goal="해양 산성화", state=[]) is None


def test_plan_uses_a_learned_action_result_to_supply_its_next_action_state():
    """현재 위치가 달라도 결과 상태를 만드는 행동을 먼저 제시한다."""
    evidence = [
        {"id": "shelve", "text": "공책을 책장으로 옮긴다.", "source": "a", "actionable": True,
         "effects": [["공책", "location", "책장"]]},
        {"id": "label", "text": "책장에 둔 공책에 분류표를 붙인다.", "source": "a", "actionable": True,
         "achieves": ["공책 정리"], "requires_state": [["공책", "location", "책장"]]},
    ]
    planned = compose("request.plan", evidence, goal="공책 정리",
                       state=[["공책", "location", "서랍"]])
    assert planned["answer"] == "1. 공책을 책장으로 옮긴다.\n2. 책장에 둔 공책에 분류표를 붙인다."


def test_plan_uses_quantity_effects_with_the_same_state_transition_structure():
    evidence = [
        {"id": "supply", "text": "구슬을 10개로 채운다.", "source": "a", "actionable": True,
         "effects": [["구슬", "count", "10"]]},
        {"id": "share", "text": "10개인 구슬을 나눈다.", "source": "a", "actionable": True,
         "achieves": ["구슬 나누기"], "requires_state": [["구슬", "count", "10"]]},
    ]
    planned = compose("request.plan", evidence, goal="구슬 나누기", state=[["구슬", "count", "3"]])
    assert planned["answer"] == "1. 구슬을 10개로 채운다.\n2. 10개인 구슬을 나눈다."


def test_unlinked_cause_and_effect_are_not_presented_as_one_causal_explanation():
    result = compose("request.explain", [
        {"id": "effect", "text": "물의 산성도가 높아진다.", "source": "a", "relation": "effect"},
        {"id": "cause", "text": "비가 내리기 때문이다.", "source": "b", "relation": "cause"},
    ])
    assert result["mode"] == "extractive_grounded_response"
    assert result["selected"] == [
        {"text": "물의 산성도가 높아진다.", "source": "a"},
        {"text": "비가 내리기 때문이다.", "source": "b"},
    ]


def test_attribute_comparison_uses_only_shared_declared_attributes():
    result = compare([
        {"label": "A", "text": "A 원문", "source": "one", "attributes": {"대상": "바다", "원인": "탄소"}},
        {"label": "B", "text": "B 원문", "source": "two", "attributes": {"대상": "대기", "원인": "탄소"}},
    ])
    assert result["mode"] == "grounded_attribute_comparison"
    assert result["answer"] == "**대상**\n- A: 바다\n- B: 대기"


def test_ui_summary_uses_a_local_definition_as_its_only_material(tmp_path):
    if not Path("data/위키/정의문.jsonl").is_file():
        pytest.skip("optional local definition corpus is not installed")
    app = create_app(tmp_path)
    with patch.object(app.goals, "research", side_effect=AssertionError("local source must not search")):
        result = app.turn("광합성 요약해줘", "summary_local")
    answer = result["answer"]
    assert result["phase"] == "answer"
    assert answer["trace"]["mode"] == "extractive_grounded_response"
    assert answer["composition"]["selected"] == answer["trace"]["sources"]
    assert "빛에너지를 화학 에너지로 전환" in answer["answer"]


def test_ui_compare_request_reuses_the_same_two_verified_definitions(tmp_path):
    if not Path("data/위키/정의문.jsonl").is_file():
        pytest.skip("optional local definition corpus is not installed")
    app = create_app(tmp_path)
    with patch.object(app.goals, "research", side_effect=AssertionError("local source must not search")):
        result = app.turn("수학과 알고리즘 비교해줘", "compare_local")
    answer = result["answer"]
    assert result["phase"] == "answer"
    assert answer["trace"]["verdict"] == "원문정의비교"
    assert [row["label"] for row in answer["composition"]["selected"]] == ["수학", "알고리즘"]
    assert all(row["source"] == "data/위키/정의문.jsonl" for row in answer["composition"]["selected"])
