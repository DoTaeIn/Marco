from alma.environment import run_local_environment
from alma.runtime import AlmaRuntime
import pytest

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default


KG = "graphs/graph_일상추론.kg"


def _environment():
    return {
        "goal": {"text": "물 2개 확보", "condition": {"field": "water", "at_least": 2},
                 "information_gap": "water-source", "control": "high"},
        "initial_observation": {"text": "저장고 물은 0개 있다.", "measurements": {"water": 0}},
        "reads": [
            {"name": "weather-read", "provides": ["weather"],
             "responses": {"weather": {"text": "날씨는 맑다.", "measurements": {"water": 0}}}},
            {"name": "water-read", "provides": ["water-source"],
             "responses": {"water-source": {"text": "우물에서 물 2개를 확인했다.",
                                                "measurements": {"water": 2}, "item": "water-read"}}},
        ],
    }


def test_local_environment_uses_matching_read_observation_and_resumes(tmp_path):
    state, config = tmp_path / "alma.json", _environment()
    first = run_local_environment(AlmaRuntime(state, "agent-a"), KG, config, step_budget=1)
    assert first["status"] == "paused_budget"

    resumed = run_local_environment(AlmaRuntime(state, "agent-a"), KG, config,
                                    run_id=first["id"], step_budget=4)
    assert resumed["status"] == "completed"
    assert resumed["initial_affect"]["label"] == "threat"
    assert resumed["final_affect"]["label"] == "resolved"

    state_after = AlmaRuntime(state, "agent-a").snapshot()
    run = state_after["autonomous_runs"][0]
    assert run["id"] == resumed["id"]
    recalled = next(row for row in run["results"] if row["phase"] == "seek_information")["memory_recall"]
    assert recalled["status"] == "answered" and recalled["provenance"]["source_event_id"] == run["initial_event_id"]
    assert next(row for row in state_after["goals"] if row["id"] == run["goal_id"])["status"] == "achieved"
    calls = state_after["capability_runs"]
    assert len(calls) == 1 and calls[0]["capability"] == "water-read" and calls[0]["status"] == "done"
    assert state_after["preferences"][0]["item"] == "water-read"


def test_capability_contract_uses_relevant_read_and_holds_when_none_match(tmp_path):
    runtime = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    runtime.turn("알 수 없는 관찰값이다.", KG)
    source = runtime.snapshot()["event_index"][0]["id"]
    runtime.register_capability({"name": "weather", "permission": "read", "provides": ["weather"]},
                                lambda _payload: {"ok": True})
    action = runtime.propose_next_action(source_event_id=source, information_gap="water")
    held = runtime.select_capability_for_action(action["id"])
    assert held["status"] == "safe_hold" and held["reason"] == "no_matching_read_capability"
    runtime.register_capability({"name": "water", "permission": "read", "provides": ["water"]},
                                lambda _payload: {"ok": True})
    assert runtime.select_capability_for_action(action["id"])["capability"] == "water"


def test_environment_rejects_an_existing_read_with_a_different_io_contract(tmp_path):
    runtime = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    runtime.register_capability({"name": "water-read", "permission": "read", "provides": ["water-source"],
                                 "input_schema": {"type": "object", "required": ["other"]},
                                 "output_schema": {"type": "object", "required": ["text", "measurements"]}},
                                lambda _payload: {"text": "unused", "measurements": {"water": 0}})
    with pytest.raises(ValueError, match="environment_capability_contract_mismatch"):
        run_local_environment(runtime, KG, _environment())
