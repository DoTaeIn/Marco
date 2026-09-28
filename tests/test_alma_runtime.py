import json
import hashlib
from pathlib import Path
import subprocess
import sys

from alma.runtime import AlmaRuntime, local_file_read_adapter
import pytest
from graph_inference import closure

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default


KG = "graphs/graph_일상추론.kg"


def test_legacy_event_without_kind_restores_as_observation_without_replaying_state(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    runtime.turn("민수 구슬은 8개 있다.", KG)
    payload = runtime.snapshot()
    payload["event_index"][0].pop("kind")
    state.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    restored = AlmaRuntime(state, "agent-a")
    event = restored.snapshot()["event_index"][0]
    assert event["kind"] == "observation" and event["execution_status"] == "observed"
    assert restored.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "8개입니다."
    persisted = json.loads(state.read_text(encoding="utf-8"))
    assert persisted["event_index"][0]["kind"] == "observation"


def _learn(runtime):
    for text in (
        "베풀다는 상대에게 구슬 2개를 주는 것이다.",
        "민수 구슬은 8개 있다. 지연 구슬은 3개 있다. 가람 구슬은 8개 있다. 하루 구슬은 3개 있다. 서준 구슬은 8개 있다. 유나 구슬은 3개 있다. 도윤 구슬은 8개 있다. 소라 구슬은 3개 있다.",
        "민수가 지연에게 베풀었다.", "가람이 하루에게 베풀었다.",
        "서준이 유나에게 베풀었다.", "도윤이 소라에게 베풀었다."):
        runtime.turn(text, KG)


def test_composed_action_uses_one_alma_event_and_survives_restart(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    for text in (
        "맞교환하다는 내가 상대에게 구슬 2개를 주고, 상대가 나에게 단추 1개를 주는 것이다.",
        "서우 구슬은 10개 있다. 서우 단추는 1개 있다. 도아 구슬은 2개 있다. 도아 단추는 5개 있다.",
        "서우가 도아에게 맞교환했다.",
    ):
        assert runtime.turn(text, KG)["status"] == "observed"
    event = next(row for row in runtime.snapshot()["event_index"] if row.get("action") == "맞교환하")
    assert event["execution_status"] == "executed"
    assert len(event["effects"]) == len(event["state_changes"]) == 4
    assert runtime.turn("지금 서우 구슬은 몇 개야?", KG)["answer"] == "8개입니다."
    assert runtime.turn("지금 서우 단추는 몇 개야?", KG)["answer"] == "2개입니다."
    procedure = next(row for row in runtime.memories("procedural") if row.get("action") == "맞교환하")
    assert procedure["effects"] == event["effects"]

    legacy = runtime.snapshot()
    next(row for row in legacy["event_index"] if row["id"] == event["id"]).pop("action")
    state.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")
    restarted = AlmaRuntime(state, "agent-a")
    assert next(row for row in restarted.snapshot()["event_index"] if row["id"] == event["id"])["action"] == "맞교환하"
    assert restarted.turn("지금 도아 구슬은 몇 개야?", KG)["answer"] == "4개입니다."
    assert restarted.turn("지금 도아 단추는 몇 개야?", KG)["answer"] == "4개입니다."
    assert next(row for row in restarted.memories("procedural") if row.get("action") == "맞교환하")["effects"] == event["effects"]


def test_natural_multi_premise_proof_shortcut_reuses_full_closure_and_original_proof(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    runtime.turn("서우는 도아보다 키가 크다. 도아는 라온보다 키가 크다. 라온은 유리보다 키가 크다.", KG)
    assert runtime.turn("서우와 유리 중 누가 더 커?", KG)["answer"] == "서우입니다."
    runtime.turn("민수는 지연보다 키가 크다. 지연은 하루보다 키가 크다. 하루는 가람보다 키가 크다.", KG)
    assert runtime.turn("민수와 가람 중 누가 더 커?", KG)["answer"] == "민수입니다."
    shortcut = next(row for row in runtime.snapshot()["shortcuts"] if row.get("mode") == "closure_snapshot")
    assert shortcut["proof_rule_ids"] == ["strict-height-transitivity"] * 2
    assert shortcut["observations"] == 2 and shortcut["active"] is True
    assert any(row.get("event") == "shortcut_activated" and row.get("automatic") is True
               for row in runtime.snapshot()["logs"])
    assert runtime.turn("서우와 유리 중 누가 더 커?", KG)["answer"] == "서우입니다."
    stored = next(row for row in runtime.snapshot()["shortcuts"] if row["id"] == shortcut["id"])
    assert stored["validated_contexts"] and any(
        row["fact"] == ["서우", "taller", "유리"] and row["record"].get("rule") == "strict-height-transitivity"
        for row in stored["validated_contexts"][0]["closure"])

    repeated = runtime.turn("서우와 라온 중 누가 더 커?", KG)
    assert repeated["answer"] == "서우입니다."
    assert [row["rule"] for row in repeated["transitions"] if row.get("rule")] == ["strict-height-transitivity"]
    use = next(row for row in runtime.snapshot()["logs"]
               if row.get("event") == "shortcut_common_path_used" and row.get("shortcut_id") == shortcut["id"])
    assert stored["validated_contexts"][0]["original_metrics"]["rule_scans"] > 0
    assert use["accelerated_metrics"] == {"rule_scans": 0, "join_attempts": 0}

    restarted = AlmaRuntime(state, "agent-a")
    assert restarted.turn("서우와 유리 중 누가 더 커?", KG)["answer"] == "서우입니다."
    assert next(row for row in restarted.snapshot()["shortcuts"] if row["id"] == shortcut["id"])["uses"] >= 2


def test_event_core_feeds_three_memories_logs_and_restart(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    _learn(runtime)
    snapshot = runtime.snapshot()
    assert runtime.memories("episodic")
    assert runtime.memories("procedural")
    semantic = runtime.memories("semantic")
    assert semantic and semantic[0]["concept"]["status"] == "active"
    assert {row["kind"] for row in snapshot["logs"]} == {"COGNITION", "LIFE"}
    assert runtime.first("event", "도윤") is not None
    assert any(row["name"] == "FIRST_NEW_CONCEPT" for row in snapshot["milestones"])
    restarted = AlmaRuntime(state, "agent-a")
    assert [row["id"] for row in restarted.memories("episodic")] == [row["id"] for row in runtime.memories("episodic")]
    assert restarted.turn("지금 소라 구슬은 몇 개야?", KG)["answer"] == "5개입니다."
    # Correcting a source experience retracts its dependent promotion but
    # keeps the action procedure and compactable historical episode audit.
    restarted.turn("정정: 민수가 지연에게 베풀었다. => 민수가 지연에게 베풀 예정이다.", KG)
    assert restarted.memories("semantic") == []
    assert restarted.memories("procedural")
    compressed = restarted.compress_episodic(keep=1)
    assert compressed and restarted.snapshot()["memories"]["episodic"][0]["summary"]["event_hash"]


def test_four_domain_contract_requires_actual_world_events_and_becomes_recallable(tmp_path):
    state = tmp_path / "alma.json"
    plans_only = AlmaRuntime(tmp_path / "plans.json", "plans")
    for text in (
        "베풀다는 상대에게 구슬 2개를 주는 것이다.", "민수가 지연에게 베풀 예정이다.",
        "옮기다는 내가 물건을 서랍으로 옮기는 것이다.", "하루가 공책을 옮길 예정이다.",
        "약속하다는 내가 상대에게 약속을 만드는 것이다.", "민수가 지연에게 약속할 예정이다.",
        "다은은 내일 관찰할 거라고 기대해.", "라온은 내일 관찰할 거라고 기대해.",
    ):
        plans_only.turn(text, KG)
    assert plans_only.event_contract_transfer()["status"] == "candidate"
    assert plans_only.recall("semantic", "four-domain-event-contract")["status"] == "safe_hold"

    runtime = AlmaRuntime(state, "agent-a")
    for text in (
        "베풀다는 상대에게 구슬 2개를 주는 것이다.", "민수 구슬은 8개 있다. 지연 구슬은 3개 있다.",
        "민수가 지연에게 베풀었다.",
        "옮기다는 내가 물건을 서랍으로 옮기는 것이다.", "공책은 책상에 있었다.", "하루가 공책을 옮겼다.",
        "약속하다는 내가 상대에게 약속을 만드는 것이다.", "민수가 지연에게 약속했다.",
        "다은은 내일 관찰할 거라고 기대해.", "라온은 내일 관찰할 거라고 기대해.",
    ):
        runtime.turn(text, KG)
    contract = runtime.event_contract_transfer()
    recalled = runtime.turn("일반적으로 아는 것: four-domain-event-contract", KG)
    assert contract["status"] == "active"
    assert recalled["status"] == "answered"
    assert recalled["memory"]["record"]["source"] == "event_contract_transfer"

    restarted = AlmaRuntime(state, "agent-a")
    assert restarted.recall("semantic", "four-domain-event-contract")["status"] == "answered"
    da_eun = next(row for row in restarted.mental("다은") if row["kind"] == "expectation")
    restarted.revise_mental(da_eun["id"], da_eun["content"], polarity=False,
                             reason="fixed_counterexample")
    assert restarted.event_contract_transfer()["status"] == "validated"
    assert restarted.recall("semantic", "four-domain-event-contract")["status"] == "safe_hold"

    reactivated = AlmaRuntime(state, "agent-a")
    reactivated.turn("윤호는 내일 관찰할 거라고 기대해.", KG)
    assert reactivated.event_contract_transfer()["status"] == "active"
    assert reactivated.recall("semantic", "four-domain-event-contract")["status"] == "answered"
    assert AlmaRuntime(state, "agent-a").recall("semantic", "four-domain-event-contract")["status"] == "answered"


def test_episodic_compression_preserves_auditable_summary_and_other_memory_lifetimes(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    _learn(runtime)
    episode = next(row for row in runtime.memories("episodic")
                   if (row.get("event") or {}).get("action") == "베풀")
    semantic = runtime.recall("semantic", "베풀")
    procedure = runtime.recall("procedural", "베풀")

    assert runtime.compress_episodic(keep=0)
    compressed = next(row for row in runtime.snapshot()["memories"]["episodic"]
                      if row["id"] == episode["id"])
    assert compressed["memory_status"] == "compressed"
    assert compressed["event"] is None
    assert compressed["summary"] == {
        "event_id": episode["event_id"], "action": "베풀",
        "definition_version": episode["event"].get("definition_version"),
        "effects": episode["effects"],
        "event_hash": hashlib.sha256(json.dumps(episode["event"], ensure_ascii=False,
                                                 sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest(),
    }
    assert runtime.recall("episodic", episode["event_id"])["status"] == "safe_hold"
    assert runtime.recall("semantic", "베풀")["provenance"]["memory_id"] == semantic["provenance"]["memory_id"]
    assert runtime.recall("procedural", "베풀")["provenance"]["memory_id"] == procedure["provenance"]["memory_id"]

    restarted = AlmaRuntime(state, "agent-a")
    assert restarted.recall("episodic", episode["event_id"])["status"] == "safe_hold"
    assert restarted.recall("semantic", "베풀")["status"] == "answered"
    assert restarted.recall("procedural", "베풀")["status"] == "answered"
    before = state.read_bytes()
    with pytest.raises(ValueError, match="state_identity_mismatch"):
        AlmaRuntime(state, "agent-b")
    assert state.read_bytes() == before


def test_working_memory_is_bounded_and_separate_from_durable_lifetimes(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    _learn(runtime)
    for number in range(17):
        runtime.set_goal("goal-%d" % number)

    recent = runtime.working_memory()
    assert len(recent) == 16
    assert [row["event"] for row in recent] == ["goal"] * 16
    assert runtime.memories("semantic") and runtime.memories("procedural")
    restarted = AlmaRuntime(state, "agent-a")
    assert restarted.working_memory() == []
    assert restarted.memories("semantic") and restarted.memories("procedural")


def test_corrected_concept_support_reactivates_its_semantic_memory_after_restart(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    _learn(runtime)
    runtime.turn("정정: 민수가 지연에게 베풀었다. => 민수가 지연에게 베풀 예정이다.", KG)
    assert runtime.recall("semantic", "베풀")["status"] == "safe_hold"
    runtime.turn("정정: 민수가 지연에게 베풀 예정이다. => 민수가 지연에게 베풀었다.", KG)
    reactivated = runtime.recall("semantic", "베풀")
    assert reactivated["status"] == "answered"
    assert reactivated["provenance"]["memory_status"] == "active"
    assert any(row.get("event") == "semantic_reactivated" for row in runtime.snapshot()["logs"])
    assert AlmaRuntime(state, "agent-a").recall("semantic", "베풀")["status"] == "answered"


def test_korean_memory_questions_use_their_typed_lifetimes_and_provenance(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    _learn(runtime)
    episode = runtime.memories("episodic")[0]
    before_events = len(runtime.snapshot()["event_index"])
    past = runtime.turn("과거 경험: " + episode["event_id"], KG)
    general = runtime.turn("일반적으로 아는 것: 베풀", KG)
    procedure = runtime.turn("하는 방법: 베풀", KG)
    assert past["status"] == general["status"] == procedure["status"] == "answered"
    assert past["memory"]["memory_kind"] == "episodic"
    assert general["memory"]["memory_kind"] == "semantic"
    assert procedure["memory"]["memory_kind"] == "procedural"
    assert past["memory"]["provenance"]["memory_id"] == episode["id"]
    assert procedure["memory"]["record"]["program"]
    assert len(runtime.snapshot()["event_index"]) == before_events
    assert runtime.turn(episode["event_id"] + "의 과거 경험은 뭐야?", KG)["memory"]["memory_kind"] == "episodic"
    assert runtime.turn("베풀에 대한 일반 지식은 뭐야?", KG)["memory"]["memory_kind"] == "semantic"
    assert runtime.turn("베풀의 절차는 뭐야?", KG)["memory"]["memory_kind"] == "procedural"
    assert runtime.turn(episode["event_id"] + " 기억나?", KG)["memory"]["memory_kind"] == "episodic"
    assert runtime.turn("베풀에 대해 알고 있는 게 뭐야?", KG)["memory"]["memory_kind"] == "semantic"
    assert runtime.turn("베풀을 어떻게 해?", KG)["memory"]["memory_kind"] == "procedural"
    restarted = AlmaRuntime(state, "agent-a")
    assert restarted.turn("일반적으로 아는 것: 베풀", KG)["memory"]["provenance"]["memory_status"] == "active"


def test_korean_mental_questions_keep_holder_scope_and_world_boundary(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    runtime.turn("민수 구슬은 8개 있다.", KG)
    source = runtime.snapshot()["event_index"][0]["id"]
    runtime.update_mental("지연", "belief", ["민수 구슬", "count", "99"], source_event_id=source)
    runtime.update_mental("지연", "expectation", ["물", "count", "2"], source_event_id=source,
                          modality="conditional", conditions=[{"event_id": source}])
    belief = runtime.turn("지연의 믿음은 뭐야?", KG)
    expectation = runtime.turn("지연의 기대는 뭐야?", KG)
    assert belief["status"] == "answered" and belief["mental"]["content"][-1] == "99"
    assert expectation["status"] == "conditional" and expectation["mental"]["world_asserted"] is False
    assert runtime.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "8개입니다."
    assert runtime.turn("지연은 무엇을 믿어?", KG)["mental"]["content"][-1] == "99"
    assert runtime.turn("지연의 기대는 무엇이야?", KG)["status"] == "conditional"
    belief_reason = runtime.turn("지연은 왜 그렇게 믿어?", KG)
    expectation_reason = runtime.turn("지연의 기대의 이유는 뭐야?", KG)
    condition_status = runtime.turn("지연의 기대 조건이 충족됐어?", KG)
    assert belief_reason["mental"]["explanation"]["source_event_id"] == source
    assert expectation_reason["mental"]["explanation"]["condition_proof"] == [{
        "event_id": source, "observed": False, "known": True}]
    assert expectation_reason["mental"]["explanation"]["world_asserted"] is False
    assert condition_status["status"] == "answered"
    assert condition_status["verification"]["question_kind"] == "condition_status"
    assert condition_status["mental"]["condition_proof"] == [{
        "event_id": source, "observed": True, "known": True}]
    assert condition_status["mental"]["world_asserted"] is False
    restarted = AlmaRuntime(state, "agent-a")
    assert restarted.turn("지연의 믿음은 뭐야?", KG)["mental"]["provenance"]["mental_id"] == belief["mental"]["provenance"]["mental_id"]
    assert restarted.turn("지연의 기대 조건은 충족됐어?", KG)["status"] == "answered"


def test_korean_mental_statements_stay_private_and_survive_restart(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    runtime.turn("민수 구슬은 8개 있다.", KG)
    before_events = len(runtime.snapshot()["event_index"])
    belief = runtime.turn("지연은 민수 구슬이 99개라고 믿어.", KG)
    expectation = runtime.turn("지연은 내일 관찰할 거라고 기대해.", KG)
    goal = runtime.turn("지연의 목표는 관계를 지키는 거야.", KG)
    assert [row["mental"]["kind"] for row in (belief, expectation, goal)] == [
        "belief", "expectation", "goal"]
    assert all(row["verification"]["world_asserted"] is False for row in (belief, expectation, goal))
    private_events = [row for row in runtime.snapshot()["event_index"] if row.get("kind") == "mental"]
    assert len(private_events) == 3 and len(runtime.snapshot()["event_index"]) == before_events + 3
    assert all(row["execution_status"] == "private" and row["private"] is True
               and not row["effects"] and not row["state_changes"] for row in private_events)
    assert [row["source"]["mental_kind"] for row in private_events] == ["belief", "expectation", "goal"]
    assert runtime.turn("지연의 믿음은 뭐야?", KG)["mental"]["content"] == "민수 구슬이 99개"
    assert runtime.turn("지연은 무엇을 기대해?", KG)["mental"]["content"] == "내일 관찰할 거"
    assert runtime.turn("지연의 목표는 뭐야?", KG)["mental"]["content"] == "관계를 지키는 거"
    recorded = runtime.turn("지연의 믿음은 언제 기록됐어?", KG)
    assert recorded["verification"]["question_kind"] == "recorded_at"
    assert recorded["mental"]["recorded_at"] == belief["mental"]["at"]
    assert recorded["mental"]["event_id"] == belief["mental"]["event_id"]
    assert runtime.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "8개입니다."
    restarted = AlmaRuntime(state, "agent-a")
    queried = restarted.turn("지연의 믿음은 뭐야?", KG)["mental"]
    assert queried["content"] == "민수 구슬이 99개"
    assert queried["event_id"] in {row["id"] for row in restarted.snapshot()["event_index"]}


def test_mental_source_must_name_a_durable_event(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    before = runtime.snapshot()
    with pytest.raises(ValueError, match="unknown_mental_source_event"):
        runtime.update_mental("지연", "belief", "비공개 추측", source_event_id="event:missing")
    assert runtime.snapshot()["mental"] == before["mental"]
    assert runtime.snapshot()["event_index"] == before["event_index"]

    runtime.turn("관찰된 근거다.", KG)
    source = runtime.snapshot()["event_index"][-1]["id"]
    mental = runtime.update_mental("지연", "belief", "관찰에 근거한 믿음", source_event_id=source)
    restarted = AlmaRuntime(state, "agent-a")
    assert restarted.mental("지연")[0]["source_event_id"] == source == mental["source_event_id"]


def test_private_mental_event_can_satisfy_only_an_explicit_mental_condition(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    belief = runtime.turn("지연은 비가 올 거라고 믿어.", KG)
    belief_event_id = belief["mental"]["event_id"]
    runtime.update_mental("수아", "expectation", "우산을 챙김", modality="conditional",
                          conditions=[{"event_id": belief_event_id}])
    answered = runtime.turn("수아의 기대 조건이 충족됐어?", KG)
    assert answered["status"] == "answered"
    assert answered["mental"]["condition_proof"] == [{
        "event_id": belief_event_id, "observed": True, "known": True}]
    assert answered["mental"]["world_asserted"] is False

    runtime.update_mental("다은", "expectation", "문을 닫음", modality="conditional",
                          conditions=[{"event_id": "event:missing"}])
    unresolved = runtime.turn("다은의 기대 조건이 충족됐어?", KG)
    assert unresolved["status"] == "conditional"
    assert unresolved["mental"]["condition_proof"] == [{
        "event_id": "event:missing", "observed": False, "known": False}]
    assert unresolved["mental"]["world_asserted"] is False

    restarted = AlmaRuntime(state, "agent-a")
    assert restarted.turn("수아의 기대 조건은 충족됐어?", KG)["status"] == "answered"
    assert restarted.turn("다은의 기대 조건은 충족됐어?", KG)["status"] == "conditional"


def test_mental_condition_keeps_a_planned_world_event_nonactual_after_restart(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    for text in ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
                 "민수 구슬은 8개 있다. 지연 구슬은 3개 있다.",
                 "민수가 지연에게 베풀 예정이다."):
        runtime.turn(text, KG)
    planned = next(row for row in runtime.snapshot()["event_index"] if row["modality"] == "planned")
    runtime.update_mental("수아", "expectation", "구슬을 확인함", modality="conditional",
                          conditions=[{"event_id": planned["id"]}])
    result = runtime.turn("수아의 기대 조건이 충족됐어?", KG)
    assert result["status"] == "conditional"
    assert result["mental"]["condition_proof"] == [{
        "event_id": planned["id"], "observed": False, "known": True}]
    assert AlmaRuntime(state, "agent-a").turn("수아의 기대 조건은 충족됐어?", KG)["status"] == "conditional"


def test_mental_query_projects_private_revision_at_recorded_processing_time(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    original = runtime.update_mental("지연", "belief", "비가 온다")
    replacement = runtime.revise_mental(original["id"], "비가 오지 않는다", reason="later_observation")

    past = runtime.query_mental("지연", "belief", as_of=original["at"])
    current = runtime.query_mental("지연", "belief")
    assert (past["status"], past["content"], past["event_id"], past["as_of"]) == (
        "answered", "비가 온다", original["event_id"], original["at"])
    assert (current["content"], current["event_id"], current["as_of"]) == (
        "비가 오지 않는다", replacement["event_id"], None)
    assert past["world_asserted"] is False and current["world_asserted"] is False

    restarted = AlmaRuntime(state, "agent-a")
    assert restarted.query_mental("지연", "belief", as_of=original["at"])["content"] == "비가 온다"
    with pytest.raises(ValueError, match="invalid_mental_as_of"):
        restarted.query_mental("지연", "belief", as_of="yesterday")


def test_korean_previous_mental_questions_use_the_superseded_private_event(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    cases = (("belief", "믿음"), ("expectation", "기대"), ("goal", "목표"))
    for kind, label in cases:
        original = runtime.update_mental("지연", kind, "old " + kind)
        replacement = runtime.revise_mental(original["id"], "new " + kind, reason="revision")
        previous = runtime.turn("지연의 이전 %s은 뭐야?" % label, KG)["mental"]
        current = runtime.turn("지연의 %s은 뭐야?" % label, KG)["mental"]
        assert (previous["status"], previous["content"], previous["event_id"], previous["as_of"],
                previous["world_asserted"]) == ("answered", "old " + kind, original["event_id"],
                                                  original["at"], False)
        assert (current["content"], current["event_id"]) == ("new " + kind, replacement["event_id"])
    assert runtime.turn("수아의 이전 믿음은 뭐야?", KG)["mental"]["status"] == "safe_hold"
    restarted = AlmaRuntime(state, "agent-a")
    assert restarted.turn("지연의 이전 믿음은 뭐야?", KG)["mental"]["content"] == "old belief"


def test_korean_mental_correction_revises_only_private_state(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    runtime.turn("민수 구슬은 8개 있다.", KG)
    runtime.turn("지연은 민수 구슬이 99개라고 믿어.", KG)
    corrected = runtime.turn("정정: 지연은 민수 구슬이 99개라고 믿어. => 지연은 민수 구슬이 6개라고 믿어.", KG)
    assert corrected["status"] == "observed" and corrected["verification"]["world_asserted"] is False
    assert runtime.turn("지연의 믿음은 뭐야?", KG)["mental"]["content"] == "민수 구슬이 6개"
    states = runtime.mental("지연", "belief", include_withdrawn=True)
    assert states[0]["status"] == "withdrawn" and states[0]["withdrawal_reason"] == "natural_mental_correction"
    events = [row for row in runtime.snapshot()["event_index"] if row.get("kind") == "mental"]
    assert events[0]["superseded_by"] == events[1]["id"] and events[1]["supersedes"] == states[0]["id"]
    assert runtime.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "8개입니다."
    restarted = AlmaRuntime(state, "agent-a")
    assert restarted.turn("지연의 믿음은 뭐야?", KG)["mental"]["content"] == "민수 구슬이 6개"


def test_typed_recall_uses_each_memory_lifetime_with_source_provenance(tmp_path):
    runtime = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    _learn(runtime)
    episode = runtime.memories("episodic")[0]
    past = runtime.recall("episodic", episode["event_id"])
    general = runtime.recall("semantic", "베풀")
    how = runtime.recall("procedural", "베풀")
    assert (past["status"], general["status"], how["status"]) == ("answered", "answered", "answered")
    assert past["provenance"]["source_event_id"] == episode["event_id"]
    assert general["record"]["concept"]["scope"]["action"] == "베풀"
    assert how["record"]["program"] and runtime.recall("procedural", "없는 행동")["status"] == "safe_hold"


def test_goal_affect_preference_and_capability_are_causal_and_resumable(tmp_path):
    runtime = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    runtime.turn("알 수 없는 관찰값이다.", KG)
    source = runtime.snapshot()["event_index"][0]["id"]
    first = runtime.set_goal("관계 유지", relation="동료", control="low", prompted=False)
    threat = runtime.assess_goal(first["id"], threatened=True, expected_loss=2, cause_event_id=source)
    resolved = runtime.assess_goal(first["id"], threatened=False, expected_loss=0, cause_event_id=source)
    assert threat["label"] == "threat"
    assert resolved["label"] == "resolved"
    assert runtime.snapshot()["affect"]["current"] is None
    assert runtime.explain_affect()["status"] == "resolved"
    assert not any(row["name"] == "FIRST_UNPROMPTED_GOAL" for row in runtime.snapshot()["milestones"])

    tea = runtime.experience_preference("차", utility=1, affect_label="resolved", context="밤", event_id=source)
    choice = runtime.choose([{"id": "차", "utility": 1}, {"id": "커피", "utility": 99}], context="밤")
    assert choice["id"] == "차" and choice["utility"] == 1
    corrected = runtime.revise_preference(tea["id"], affect_label="threat", reason="burned")
    assert corrected["supersedes"] == tea["id"]
    assert runtime.choose([{"id": "차", "utility": 1}, {"id": "커피", "utility": 99}], context="밤")["id"] == "커피"

    runtime.register_capability({"name": "local-read", "permission": "read", "input_schema": {"type": "object"}},
                                lambda payload: {"echo": payload["value"]})
    done = runtime.call_capability("local-read", {"value": "ok"}, request_id="read-1")
    assert done == runtime.call_capability("local-read", {"value": "ok"}, request_id="read-1")
    with pytest.raises(ValueError, match="capability_request_conflict"):
        runtime.call_capability("local-read", {"value": "changed"}, request_id="read-1")
    runtime.register_capability({"name": "other-read", "permission": "read"},
                                lambda payload: {"other": payload["value"]})
    assert runtime.call_capability("other-read", {"value": "separate"}, request_id="read-1")["output"] == {"other": "separate"}
    runtime.register_capability({"name": "write-guard", "permission": "write"}, lambda _payload: "never")
    assert runtime.call_capability("write-guard", {}, approved=False)["status"] == "approval_required"
    assert runtime.call_capability("write-guard", {}, approved=True)["status"] == "done"
    runtime.register_capability({"name": "checked-read", "permission": "read",
                                 "input_schema": {"type": "object", "required": ["value"]},
                                 "output_schema": {"type": "object", "required": ["echo"]}},
                                lambda payload: {"echo": payload["value"]})
    assert runtime.call_capability("checked-read", {}, request_id="bad-input")["error"] == "input_schema_invalid"
    runtime.register_capability({"name": "bad-output", "permission": "read",
                                 "output_schema": {"type": "object", "required": ["answer"]}},
                                lambda _payload: "not-an-object")
    assert runtime.call_capability("bad-output", {}, request_id="bad-output")["error"] == "output_schema_invalid"
    runtime.register_capability({"name": "nonportable-output", "permission": "read"},
                                lambda _payload: object())
    assert runtime.call_capability("nonportable-output", {}, request_id="nonportable-output")["error"] == "output_not_portable"
    runtime.register_capability({"name": "nonportable-input", "permission": "read"}, lambda _payload: "never")
    assert runtime.call_capability("nonportable-input", object(), request_id="nonportable-input")["error"] == "input_not_portable"
    with pytest.raises(ValueError, match="invalid_capability"):
        runtime.register_capability({"name": "bad-schema", "permission": "read",
                                     "input_schema": {"type": "invented"}}, lambda _payload: None)

    (tmp_path / "note.txt").write_text("grounded", encoding="utf-8")
    runtime.register_capability({"name": "filesystem-read", "permission": "read",
                                 "input_schema": {"type": "object", "required": ["path"]},
                                 "output_schema": {"type": "object", "required": ["path", "bytes", "text"]}},
                                local_file_read_adapter(tmp_path))
    assert runtime.call_capability("filesystem-read", {"path": "note.txt"})["output"]["text"] == "grounded"
    assert runtime.call_capability("filesystem-read", {"path": "../outside.txt"}, request_id="outside")["status"] == "failed"
    feedback = runtime.search("read_path_outside_root", kinds={"log"})
    assert any(row["record"]["kind"] == "COGNITION" for row in feedback)

    preferences_before_replacement = runtime.snapshot()["preferences"]
    runtime.register_capability({"name": "local-read", "permission": "read"},
                                lambda payload: {"replacement": payload["value"]})
    replacement = runtime.call_capability("local-read", {"value": "new"}, request_id="read-2")
    revisions = [row for row in runtime.snapshot()["capability_revisions"] if row["capability"] == "local-read"]
    assert replacement["capability_version"] == 2 and replacement["output"] == {"replacement": "new"}
    assert [row["version"] for row in revisions] == [1, 2]
    assert runtime.snapshot()["preferences"] == preferences_before_replacement

    restarted = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    assert restarted.call_capability("local-read", {"value": "ok"}, request_id="new-read")["error"] == "adapter_unavailable"
    assert restarted.snapshot()["preferences"]


def test_preference_confidence_tracks_independent_contextual_evidence_and_agent_lives(tmp_path):
    def observe(runtime, goal, text, *, threatened):
        runtime.turn(text, KG)
        source = runtime.snapshot()["event_index"][-1]["id"]
        label = "threat" if threatened else "resolved"
        runtime.assess_goal(goal["id"], threatened=threatened, expected_loss=int(threatened), cause_event_id=source)
        return source, label

    state = tmp_path / "agent-a.json"
    runtime = AlmaRuntime(state, "agent-a")
    goal = runtime.set_goal("안전")
    night_sources = []
    for index, threatened in enumerate((False, False, True, True), start=1):
        source, label = observe(runtime, goal, "밤 관찰 %d" % index, threatened=threatened)
        night_sources.append(source)
        runtime.experience_preference("차", utility=1, affect_label=label, context="밤", event_id=source)
    duplicate = runtime.experience_preference("차", utility=1, affect_label="threat", context="밤",
                                              event_id=night_sources[-1])
    night_rows = [row for row in runtime.snapshot()["preferences"] if row["context"] == "밤"]
    assert duplicate["id"] == night_rows[-1]["id"]
    assert {row["confidence"] for row in night_rows} == {4}
    assert all(row["support_event_ids"] == sorted(night_sources) for row in night_rows)
    assert runtime.choose([{"id": "차", "utility": 1}, {"id": "커피", "utility": 9}], context="밤")["id"] == "커피"

    morning_source, morning_label = observe(runtime, goal, "아침 관찰", threatened=False)
    runtime.experience_preference("커피", utility=1, affect_label=morning_label, context="아침", event_id=morning_source)
    morning = runtime.choose([{"id": "차", "utility": 1}, {"id": "커피", "utility": 1}], context="아침")
    assert (morning["id"], morning["confidence"]) == ("커피", 1)
    resumed = AlmaRuntime(state, "agent-a")
    assert resumed.choose([{"id": "차", "utility": 1}, {"id": "커피", "utility": 9}], context="밤")["id"] == "커피"

    other = AlmaRuntime(tmp_path / "agent-b.json", "agent-b")
    other_goal = other.set_goal("안전")
    other_source, other_label = observe(other, other_goal, "다른 경험", threatened=False)
    other.experience_preference("차", utility=1, affect_label=other_label, context="밤", event_id=other_source)
    assert other.choose([{"id": "차", "utility": 1}, {"id": "커피", "utility": 9}], context="밤")["id"] == "차"
    assert other.snapshot()["identity"] != resumed.snapshot()["identity"]


def test_same_event_with_different_goal_relations_changes_the_choice(tmp_path):
    options = [{"id": "family", "utility": 0, "supports_relation": "family"},
               {"id": "coworker", "utility": 0, "supports_relation": "coworker"}]
    family = AlmaRuntime(tmp_path / "family.json", "family")
    coworker = AlmaRuntime(tmp_path / "coworker.json", "coworker")
    for runtime, relation in ((family, "family"), (coworker, "coworker")):
        runtime.turn("알 수 없는 관찰값이다.", KG)
        source = runtime.snapshot()["event_index"][0]["id"]
        goal = runtime.set_goal("관계 유지", relation=relation, control="low")
        cause = runtime.assess_goal(goal["id"], threatened=True, expected_loss=1,
                                    cause_event_id=source)
        assert runtime.explain_affect()["cause"]["cause_event_id"] == source
        assert cause["relation"] == relation
    assert family.choose(options)["id"] == "family"
    assert coworker.choose(options)["id"] == "coworker"


def test_same_event_with_different_control_selects_a_declared_control_fit(tmp_path):
    options = [{"id": "ask-for-help", "utility": 0, "supports_relation": "coworker",
                "supports_controls": ["low"]},
               {"id": "fix-directly", "utility": 0, "supports_relation": "coworker",
                "supports_controls": ["high"]}]
    for control, expected in (("low", "ask-for-help"), ("high", "fix-directly")):
        runtime = AlmaRuntime(tmp_path / (control + ".json"), control)
        runtime.turn("알 수 없는 관찰값이다.", KG)
        source = runtime.snapshot()["event_index"][0]["id"]
        goal = runtime.set_goal("관계 유지", relation="coworker", control=control)
        runtime.assess_goal(goal["id"], threatened=True, expected_loss=1, cause_event_id=source)
        choice = runtime.choose(options)
        assert choice["id"] == expected and choice["control_fit"] == 1


def test_observed_gap_or_active_goal_proposes_a_durable_nonexecuting_action(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    for text in ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
                 "민수 구슬은 8개 있다. 지연 구슬은 3개 있다.",
                 "민수가 지연에게 베풀었다."):
        runtime.turn(text, KG)
    source = runtime.snapshot()["event_index"][0]["id"]
    gap = runtime.propose_next_action(source_event_id=source, information_gap="지연의 현재 위치")
    goal = runtime.set_goal("관계 유지")
    threatened = runtime.propose_next_action(source_event_id=source, goal_id=goal["id"])
    assert (gap["kind"], threatened["kind"]) == ("seek_information", "protect_goal")
    assert runtime.select_capability_for_action(gap["id"])["status"] == "safe_hold"
    runtime.register_capability({"name": "one-read", "permission": "read"}, lambda _payload: {"ok": True})
    selected = runtime.select_capability_for_action(gap["id"])
    assert selected == {"action_id": gap["id"], "status": "ready", "capability": "one-read"}
    runtime.register_capability({"name": "second-read", "permission": "read"}, lambda _payload: {"ok": True})
    assert runtime.select_capability_for_action(gap["id"])["reason"] == "ambiguous_read_capability"
    refreshed_gap = next(row for row in runtime.snapshot()["action_candidates"] if row["id"] == gap["id"])
    assert refreshed_gap["status"] == "pending" and refreshed_gap["selection_revisions"]
    resolved = runtime.resolve_goal(goal["id"], "achieved", source_event_id=source)
    assert resolved["status"] == "achieved"
    assert next(row for row in runtime.snapshot()["action_candidates"] if row["id"] == threatened["id"])["status"] == "cancelled"
    assert AlmaRuntime(state, "agent-a").snapshot()["action_candidates"][-1]["id"] == threatened["id"]


def test_conditioned_goal_rejects_an_unrelated_event_until_a_resolved_observation_exists(tmp_path):
    runtime = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    runtime.turn("알 수 없는 첫 관찰이다.", KG)
    unrelated = runtime.snapshot()["event_index"][-1]["id"]
    goal = runtime.set_goal("물 2개 확보", condition={"field": "water", "at_least": 2})
    runtime.assess_goal_from_observation(goal["id"], cause_event_id=unrelated, measurements={"water": 0})
    with pytest.raises(ValueError, match="goal_condition_unmet"):
        runtime.resolve_goal(goal["id"], "achieved", source_event_id=unrelated)

    runtime.turn("알 수 없는 두번째 관찰이다.", KG)
    resolved_event = runtime.snapshot()["event_index"][-1]["id"]
    assert runtime.assess_goal_from_observation(
        goal["id"], cause_event_id=resolved_event, measurements={"water": 2})["label"] == "resolved"
    assert runtime.resolve_goal(goal["id"], "achieved", source_event_id=resolved_event)["status"] == "achieved"


def test_active_semantic_and_procedural_memory_ground_learned_action_selection(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    _learn(runtime)
    source = runtime.memories("episodic")[0]["event_id"]
    goal = runtime.set_goal("관계 유지")
    semantic, procedure = runtime.recall("semantic", "베풀"), runtime.recall("procedural", "베풀")
    selected = runtime.propose_next_action(source_event_id=source, goal_id=goal["id"], action="베풀")
    assert (selected["kind"], selected["status"], selected["semantic_memory_id"],
            selected["procedural_memory_id"], selected["procedure_source_event_id"]) == (
        "learned_action", "pending", semantic["provenance"]["memory_id"],
        procedure["provenance"]["memory_id"], procedure["provenance"]["source_event_id"])
    held = runtime.propose_next_action(source_event_id=source, goal_id=goal["id"], action="없는 행동")
    assert held["status"] == "safe_hold" and len(runtime.snapshot()["action_candidates"]) == 1

    runtime.turn("정정: 민수가 지연에게 베풀었다. => 민수가 지연에게 베풀 예정이다.", KG)
    cancelled = runtime.snapshot()["action_candidates"][0]
    assert (cancelled["status"], cancelled["cancellation_reason"]) == (
        "cancelled", "semantic_memory_withdrawn")
    restarted = AlmaRuntime(state, "agent-a")
    assert restarted.snapshot()["action_candidates"][0]["status"] == "cancelled"
    assert restarted.recall("procedural", "베풀")["status"] == "answered"
    code = """
import json
import sys
from alma.runtime import AlmaRuntime

runtime = AlmaRuntime(sys.argv[1], "agent-a")
print(json.dumps({
    "candidate_status": runtime.snapshot()["action_candidates"][0]["status"],
    "procedure_status": runtime.recall("procedural", "베풀")["status"],
}))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code, str(state)], cwd=Path(__file__).resolve().parents[1],
        check=True, capture_output=True, text=True, encoding="utf-8")
    assert json.loads(completed.stdout) == {
        "candidate_status": "cancelled", "procedure_status": "answered"}


def test_non_action_observation_is_preserved_without_becoming_an_action(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    runtime.turn("알 수 없는 관찰값이다.", KG)
    observation = runtime.snapshot()["event_index"][0]
    assert observation["kind"] == "observation"
    assert observation["effects"] == [] and observation["modality"] == "uninterpreted"
    assert runtime.memories("episodic")[0]["source"]["text"] == "알 수 없는 관찰값이다."
    restarted = AlmaRuntime(state, "agent-a")
    assert restarted.search("알 수 없는 관찰값", kinds={"event"})[0]["record"]["id"] == observation["id"]


def test_decision_event_time_and_mental_ledgers_stay_scoped_and_replayable(tmp_path):
    left = AlmaRuntime(tmp_path / "left.json", "left")
    right = AlmaRuntime(tmp_path / "right.json", "right")
    for runtime in (left, right):
        runtime.turn("민수 구슬은 8개 있다. 지연 구슬은 3개 있다.", KG)
        runtime.turn("베풀다는 상대에게 구슬 2개를 주는 것이다.", KG)
        runtime.turn("민수가 지연에게 베풀었다.", KG)

    left_event = next(row for row in left.snapshot()["event_index"] if row["execution_status"] == "executed")
    right_event = next(row for row in right.snapshot()["event_index"] if row["execution_status"] == "executed")
    assert left_event["local_id"] == right_event["local_id"]
    assert left_event["id"] != right_event["id"]
    assert left_event["observed_at"] and left_event["time_status"] == "unconfirmed"
    assert left_event["processed_at"] and left_event["processed_sequence"] >= 1
    assert left_event["roles"] == {"은": "민수", "에게": "지연"}
    assert left_event["effects"] and left_event["execution_status"] == "executed"
    cause = next(row for row in left.snapshot()["event_index"] if row["id"] != left_event["id"])
    annotated = left.annotate_event(left_event["id"], effective_at="yesterday", place="마당",
                                    cause_event_id=cause["id"], roles={"함께": "선영"},
                                    conditions=["승인됨"])
    assert annotated["observed_at"] and annotated["effective_at"] == "yesterday"
    assert annotated["time_status"] == "specified" and annotated["place"] == "마당"
    assert annotated["roles"] == {"은": "민수", "에게": "지연", "함께": "선영"}
    assert annotated["conditions"] == ["승인됨"] and annotated["metadata_revision"] == 1
    with pytest.raises(ValueError, match="unknown_cause_event"):
        left.annotate_event(left_event["id"], cause_event_id="event:left:unknown")
    assert next(row for row in left.snapshot()["event_index"] if row["id"] == left_event["id"])["cause"] == cause["id"]
    assert "함께" not in right_event["roles"]
    decision = next(row for row in left.snapshot()["logs"] if row["kind"] == "COGNITION" and row["event"] == "turn")
    assert decision["decision_id"] and decision["state_before"] and decision["state_after"]
    linked_life = next(row for row in left.snapshot()["logs"] if row["kind"] == "LIFE" and row["event"] == "event")
    assert linked_life["decision_id"] == decision["decision_id"] or linked_life["decision_id"]

    belief = left.update_mental("지연", "belief", ["민수 구슬", "count", "99"], source_event_id=left_event["id"])
    assert left.mental("지연", "belief") == [belief]
    corrected = left.revise_mental(belief["id"], ["민수 구슬", "count", "6"], reason="observed_count")
    assert left.mental("지연", "belief") == [corrected]
    assert left.mental("지연", "belief", include_withdrawn=True)[0]["status"] == "withdrawn"
    assert left.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "6개입니다."
    conditional = left.update_mental("지연", "expectation", ["민수 구슬", "count", "4"],
                                      modality="conditional", effective_at="tomorrow",
                                      conditions=["민수가 구슬을 받음"])
    assert conditional["conditions"] == ["민수가 구슬을 받음"]
    assert conditional["time_status"] == "specified"
    assert left.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "6개입니다."
    corrected_conditional = left.revise_mental(conditional["id"], ["민수 구슬", "count", "5"],
                                                reason="plan_changed")
    assert corrected_conditional["modality"] == "conditional"
    assert corrected_conditional["conditions"] == ["민수가 구슬을 받음"]
    belief_query = left.query_mental("지연", "belief")
    conditional_query = left.query_mental("지연", "expectation", content=["민수 구슬", "count", "5"])
    assert belief_query["status"] == "answered" and belief_query["content"] == ["민수 구슬", "count", "6"]
    assert conditional_query["status"] == "conditional" and conditional_query["conditions"] == ["민수가 구슬을 받음"]
    grounded = left.update_mental("지연", "expectation", ["민수 구슬", "count", "7"],
                                  modality="conditional", conditions=[{"event_id": left_event["id"]}])
    grounded_query = left.query_mental("지연", "expectation", content=grounded["content"],
                                        observed_event_ids=[left_event["id"]])
    assert grounded_query["status"] == "answered" and grounded_query["world_asserted"] is False
    assert grounded_query["condition_proof"] == [{"event_id": left_event["id"], "observed": True, "known": True}]
    assert left.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "6개입니다."
    with pytest.raises(ValueError, match="invalid_mental_state"):
        left.update_mental("지연", "belief", ["x"], modality="asserted")
    restarted = AlmaRuntime(tmp_path / "left.json", "left")
    assert restarted.mental("지연")[0]["content"] == ["민수 구슬", "count", "6"]
    assert restarted.mental("지연")[1]["modality"] == "conditional"
    assert restarted.mental("지연")[1]["conditions"] == ["민수가 구슬을 받음"]
    assert restarted.search("선영", kinds={"event"})[0]["record"]["roles"]["함께"] == "선영"
    assert restarted.search("마당", kinds={"event"})[0]["record"]["cause"] == cause["id"]
    matches = restarted.search("민수", kinds={"event", "mental"})
    assert matches and matches[0]["kind"] == "event" and any(row["kind"] == "mental" for row in matches)


def test_late_observed_past_event_projects_numeric_state_by_effective_time(tmp_path):
    runtime = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    for text in ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
                 "민수 구슬은 8개 있다. 지연 구슬은 3개 있다.",
                 "민수가 지연에게 베풀었다.",
                 "지연이 민수에게 베풀었다."):
        runtime.turn(text, KG)
    events = [row for row in runtime.snapshot()["event_index"]
              if row["execution_status"] == "executed"]
    runtime.annotate_event(events[0]["id"], effective_at=2)
    runtime.annotate_event(events[1]["id"], effective_at=1)
    timed = {row["id"]: row for row in runtime.snapshot()["event_index"]}
    assert timed[events[0]["id"]]["processed_sequence"] < timed[events[1]["id"]]["processed_sequence"]
    assert timed[events[0]["id"]]["effective_at"] == 2
    assert timed[events[1]["id"]]["effective_at"] == 1
    past = runtime.project_state_at(1)
    current = runtime.project_state_at(2)
    past_values = {(row["subject"], row["predicate"]): row["value"] for row in past["state"]}
    current_values = {(row["subject"], row["predicate"]): row["value"] for row in current["state"]}
    assert past["status"] == current["status"] == "answered"
    assert past_values[("민수 구슬", "count")] == 10
    assert past_values[("지연 구슬", "count")] == 1
    assert current_values[("민수 구슬", "count")] == 8
    assert current_values[("지연 구슬", "count")] == 3
    restarted = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    assert restarted.project_state_at(1)["state"] == past["state"]


def test_timed_location_event_projects_before_and_after_without_replaying_world(tmp_path):
    runtime = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    for text in ("옮기다는 내가 물건을 서랍으로 옮기는 것이다.",
                 "공책은 책상에 있었다.", "하루가 공책을 옮겼다."):
        runtime.turn(text, KG)
    event = next(row for row in runtime.snapshot()["event_index"]
                 if row["execution_status"] == "executed")
    runtime.annotate_event(event["id"], effective_at=2)
    before = {(row["subject"], row["predicate"]): row["value"]
              for row in runtime.project_state_at(1)["state"]}
    after = {(row["subject"], row["predicate"]): row["value"]
             for row in runtime.project_state_at(2)["state"]}
    assert before[("공책", "location")] == "책상"
    assert after[("공책", "location")] == "서랍"
    assert runtime.turn("지금 공책은 어디에 있어?", KG)["answer"] == "서랍에 있습니다."


def test_timed_social_events_project_relation_status_and_survive_restart(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    for text in ("약속하다는 내가 상대에게 약속을 만드는 것이다.",
                 "취소하다는 내가 상대와 약속을 취소 상태로 만드는 것이다.",
                 "민수가 지연에게 약속했다.", "민수가 지연과 취소했다."):
        runtime.turn(text, KG)
    events = [row for row in runtime.snapshot()["event_index"]
              if row["execution_status"] == "executed"]
    runtime.annotate_event(events[0]["id"], effective_at=1)
    runtime.annotate_event(events[1]["id"], effective_at=2)
    past = runtime.project_state_at(1)
    current = runtime.project_state_at(2)
    assert past["status"] == current["status"] == "answered"
    assert past["state"] == [{"subject": "relation:event:2:0", "predicate": "relation_status",
                               "value": "active", "provenance": {
                                   "event_id": events[0]["id"], "effective_at": 1,
                                   "operation": "state_update"}}]
    assert current["state"] == [{"subject": "relation:event:2:0", "predicate": "relation_status",
                                  "value": "cancelled", "provenance": {
                                      "event_id": events[1]["id"], "effective_at": 2,
                                      "operation": "state_update"}}]
    restarted = AlmaRuntime(state, "agent-a")
    assert restarted.project_state_at(1)["state"] == past["state"]
    assert restarted.project_state_at(2)["state"] == current["state"]


def test_social_role_correction_replaces_the_historic_relation_after_restart(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    for text in ("약속하다는 내가 상대에게 약속을 만드는 것이다.",
                 "민수가 지연에게 약속했다.",
                 "정정: 민수가 지연에게 약속했다. => 민수가 하루에게 약속했다."):
        runtime.turn(text, KG)
    old_relation = runtime.turn("민수와 지연의 약속 상태가 어때?", KG)
    corrected_relation = runtime.turn("민수와 하루의 약속 상태가 어때?", KG)
    assert old_relation["status"] == "unresolved"
    assert corrected_relation["answer"] == "active입니다."
    revision = runtime.snapshot()["reasoning_context"]["event_revisions"]
    assert len(revision) == 1 and revision[0]["kind"] == "correction"
    restarted = AlmaRuntime(state, "agent-a")
    assert restarted.turn("민수와 지연의 약속 상태가 어때?", KG)["status"] == "unresolved"
    assert restarted.turn("민수와 하루의 약속 상태가 어때?", KG)["answer"] == "active입니다."


def test_timed_location_role_correction_updates_the_same_event_projection_after_restart(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    for text in ("옮기다는 내가 물건을 서랍으로 옮기는 것이다.",
                 "공책은 책상에 있었다.", "하루가 공책을 옮겼다."):
        runtime.turn(text, KG)
    event = next(row for row in runtime.snapshot()["event_index"]
                 if row["execution_status"] == "executed")
    runtime.annotate_event(event["id"], effective_at=2)
    runtime.turn("정정: 하루가 공책을 옮겼다. => 하루가 연필을 옮겼다.", KG)
    corrected = next(row for row in runtime.snapshot()["event_index"] if row["id"] == event["id"])
    assert corrected["effective_at"] == 2
    assert corrected["effects"] == [["연필", "location", "서랍"]]
    episode = next(row for row in runtime.memories("episodic") if row.get("event_id") == event["id"])
    assert episode["event"]["roles"] == {"은": "하루", "을": "연필"}
    assert episode["effects"] == [["연필", "location", "서랍"]]
    procedure = next(row for row in runtime.memories("procedural") if row.get("source_event_id") == event["id"])
    assert procedure["effects"] == [["연필", "location", "서랍"]]
    recalled = runtime.turn("옮기를 어떻게 해?", KG)
    assert recalled["memory"]["memory_kind"] == "procedural"
    assert recalled["memory"]["record"]["effects"] == [["연필", "location", "서랍"]]
    state_at_two = {(row["subject"], row["predicate"]): row["value"]
                    for row in runtime.project_state_at(2)["state"]}
    assert state_at_two[("공책", "location")] == "책상"
    assert state_at_two[("연필", "location")] == "서랍"

    restarted = AlmaRuntime(state, "agent-a")
    assert restarted.project_state_at(2)["state"] == runtime.project_state_at(2)["state"]
    resumed_episode = next(row for row in restarted.memories("episodic")
                           if row.get("event_id") == event["id"])
    assert resumed_episode["event"]["roles"] == {"은": "하루", "을": "연필"}
    resumed_procedure = next(row for row in restarted.memories("procedural")
                             if row.get("source_event_id") == event["id"])
    assert resumed_procedure["effects"] == [["연필", "location", "서랍"]]


def test_timed_social_role_correction_updates_the_same_event_after_restart(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    for text in ("약속하다는 내가 상대에게 약속을 만드는 것이다.",
                 "민수가 지연에게 약속했다."):
        runtime.turn(text, KG)
    event = next(row for row in runtime.snapshot()["event_index"]
                 if row["execution_status"] == "executed")
    runtime.annotate_event(event["id"], effective_at=2)
    runtime.turn("정정: 민수가 지연에게 약속했다. => 민수가 하루에게 약속했다.", KG)
    corrected = next(row for row in runtime.snapshot()["event_index"] if row["id"] == event["id"])
    assert corrected["effective_at"] == 2
    assert corrected["roles"] == {"은": "민수", "에게": "하루"}
    assert runtime.project_state_at(2)["state"][0]["value"] == "active"
    assert runtime.turn("민수와 지연의 약속 상태가 어때?", KG)["status"] == "unresolved"
    assert runtime.turn("민수와 하루의 약속 상태가 어때?", KG)["answer"] == "active입니다."

    restarted = AlmaRuntime(state, "agent-a")
    assert restarted.project_state_at(2)["state"] == runtime.project_state_at(2)["state"]


def test_timed_planned_role_corrections_stay_nonactual_across_world_domains(tmp_path):
    cases = [
        (("베풀다는 상대에게 구슬 2개를 주는 것이다.", "민수 구슬은 8개 있다.",
          "민수가 지연에게 베풀 예정이다."),
         "정정: 민수가 지연에게 베풀 예정이다. => 민수가 가람에게 베풀 예정이다.",
         "가람", "지금 민수 구슬은 몇 개야?", "8개입니다."),
        (("옮기다는 내가 물건을 서랍으로 옮기는 것이다.", "공책은 책상에 있었다.",
          "하루가 공책을 옮길 예정이다."),
         "정정: 하루가 공책을 옮길 예정이다. => 하루가 연필을 옮길 예정이다.",
         "연필", "지금 공책은 어디에 있어?", "책상에 있습니다."),
        (("약속하다는 내가 상대에게 약속을 만드는 것이다.", "민수가 지연에게 약속할 예정이다."),
         "정정: 민수가 지연에게 약속할 예정이다. => 민수가 하루에게 약속할 예정이다.",
         "하루", "민수와 하루의 약속 상태가 어때?", None),
    ]
    for index, (history, correction, target, question, answer) in enumerate(cases):
        state = tmp_path / ("planned-%d.json" % index)
        runtime = AlmaRuntime(state, "agent-a")
        for text in history:
            runtime.turn(text, KG)
        event = next(row for row in runtime.snapshot()["event_index"] if row.get("modality") == "planned")
        runtime.annotate_event(event["id"], effective_at=2)
        runtime.turn(correction, KG)
        corrected = next(row for row in runtime.snapshot()["event_index"] if row["id"] == event["id"])
        assert (corrected["execution_status"], corrected["effective_at"], corrected["effects"],
                corrected["state_changes"]) == ("planned", 2, [], [])
        assert target in corrected["roles"].values()
        result = runtime.turn(question, KG)
        if answer:
            assert result["answer"] == answer
        else:
            assert result["status"] == "unresolved"
        restarted = AlmaRuntime(state, "agent-a")
        resumed = next(row for row in restarted.snapshot()["event_index"] if row["id"] == event["id"])
        assert (resumed["execution_status"], resumed["effective_at"], resumed["effects"],
                resumed["state_changes"]) == ("planned", 2, [], [])


def test_runtime_world_hypotheses_are_temporary_across_three_domains_and_restart(tmp_path):
    cases = [
        (("베풀다는 상대에게 구슬 2개를 주는 것이다.",
          "민수 구슬은 8개 있다. 지연 구슬은 3개 있다."),
         "만약 민수가 지연에게 베풀었으면 지금 지연 구슬은 몇 개야?",
         "지금 지연 구슬은 몇 개야?", "5개입니다.", "3개입니다.", "Quantity"),
        (("모으다는 내가 있는 곳으로 물건을 옮기는 것이다.", "하린은 서랍에 있었다."),
         "만약 하린이 공책을 모았으면 지금 공책은 어디에 있어?",
         "지금 공책은 어디에 있어?", "서랍에 있습니다.", None, "Location"),
        (("약속하다는 내가 상대에게 약속을 만드는 것이다.",),
         "만약 민수가 지연에게 약속했으면 민수와 지연의 약속 상태가 어때?",
         "민수와 지연의 약속 상태가 어때?", "active입니다.", None, "Social"),
    ]
    for index, (setup, question, actual_question, expected, actual, domain) in enumerate(cases):
        state = tmp_path / ("hypothesis-%d.json" % index)
        runtime = AlmaRuntime(state, "agent-a")
        for text in setup:
            runtime.turn(text, KG)
        projected = runtime.turn(question, KG)
        event = next(step["event"] for step in projected["transitions"]
                     if step.get("operation") == "hypothetical_action")
        assert projected["answer"] == expected
        assert (event["schema"], event["modality"], event["program"]["domain"]) == (
            "nai-action-event-v1", "hypothetical", domain)
        assert not [row for row in runtime.snapshot()["event_index"]
                    if row.get("modality") == "hypothetical"]

        result = runtime.turn(actual_question, KG)
        if actual:
            assert result["answer"] == actual
        else:
            assert result["status"] == "unresolved"
        resumed = AlmaRuntime(state, "agent-a").turn(actual_question, KG)
        if actual:
            assert resumed["answer"] == actual
        else:
            assert resumed["status"] == "unresolved"


def test_timed_quantity_role_correction_replays_corrected_deltas_after_restart(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    for text in ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
                 "민수 구슬은 8개 있다. 지연 구슬은 3개 있다. 가람 구슬은 1개 있다.",
                 "민수가 지연에게 베풀었다."):
        runtime.turn(text, KG)
    event = next(row for row in runtime.snapshot()["event_index"]
                 if row["execution_status"] == "executed")
    runtime.annotate_event(event["id"], effective_at=2)
    runtime.turn("정정: 민수가 지연에게 베풀었다. => 민수가 가람에게 베풀었다.", KG)
    corrected = next(row for row in runtime.snapshot()["event_index"] if row["id"] == event["id"])
    assert corrected["effective_at"] == 2
    assert corrected["roles"] == {"은": "민수", "에게": "가람"}
    values = {(row["subject"], row["predicate"]): row["value"]
              for row in runtime.project_state_at(2)["state"]}
    assert values == {("민수 구슬", "count"): 6, ("지연 구슬", "count"): 3,
                      ("가람 구슬", "count"): 3}

    restarted = AlmaRuntime(state, "agent-a")
    assert restarted.project_state_at(2)["state"] == runtime.project_state_at(2)["state"]


def test_runtime_records_graph_bytes_and_rejects_a_silent_model_swap(tmp_path):
    runtime = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    runtime.turn("민수 구슬은 8개 있다.", KG)
    state = runtime.snapshot()
    turn = next(row for row in state["logs"] if row["event"] == "turn")
    assert turn["graph_sha256"] in state["graph_assets"]
    assert state["graph_assets"][turn["graph_sha256"]]["bytes"] > 0

    class Model:
        fingerprint = "fixed-pack-a"

        def parser(self):
            from relational_semantics import RelationalParser
            return RelationalParser()

    fixed = AlmaRuntime(tmp_path / "fixed.json", "agent-b", model=Model())
    fixed.set_goal("test")
    with pytest.raises(ValueError, match="model_fingerprint_mismatch"):
        AlmaRuntime(tmp_path / "fixed.json", "agent-b", model=type("Other", (), {
            "fingerprint": "fixed-pack-b", "parser": Model.parser})())


def test_interrupted_atomic_save_recovers_the_newest_valid_checkpoint(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    runtime.set_goal("관계 유지")
    complete = state.read_text(encoding="utf-8")
    newer = json.loads(complete)
    newer["revision"] += 1
    newer["goals"].append({"id": "goal:recovered", "goal": "새 checkpoint", "status": "active"})
    temporary = state.with_suffix(".tmp")
    temporary.write_text(json.dumps(newer, ensure_ascii=False), encoding="utf-8")

    recovered = AlmaRuntime(state, "agent-a")
    assert recovered.snapshot()["goals"][-1]["goal"] == "새 checkpoint"
    assert state.exists() and not temporary.exists()

    temporary.write_text(state.read_text(encoding="utf-8"), encoding="utf-8")
    state.write_text("{partial", encoding="utf-8")
    assert AlmaRuntime(state, "agent-a").snapshot()["goals"][0]["goal"] == "관계 유지"


def test_existing_incompatible_or_corrupt_state_never_becomes_a_new_life(tmp_path):
    state = tmp_path / "alma.json"
    original = AlmaRuntime(state, "agent-a")
    original.set_goal("preserve this life")
    before = state.read_bytes()
    with pytest.raises(ValueError, match="state_identity_mismatch"):
        AlmaRuntime(state, "agent-b")
    assert state.read_bytes() == before
    assert AlmaRuntime(state, "agent-a").snapshot()["goals"][0]["goal"] == "preserve this life"

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text('{"schema":', encoding="utf-8")
    before_corrupt = corrupt.read_bytes()
    with pytest.raises(ValueError, match="state_corrupt"):
        AlmaRuntime(corrupt, "agent-a")
    assert corrupt.read_bytes() == before_corrupt


def test_capability_journal_distinguishes_retry_conflict_and_unknown_execution(tmp_path, monkeypatch):
    state, effects = tmp_path / "alma.json", []
    runtime = AlmaRuntime(state, "agent-a")
    runtime.register_capability({"name": "write", "permission": "write"},
                                lambda payload: effects.append(payload) or {"ok": True})
    assert runtime.call_capability("write", {"id": "a"}, request_id="approve") ["status"] == "approval_required"
    assert runtime.call_capability("write", {"id": "a"}, approved=True, request_id="approve")["status"] == "done"
    assert effects == [{"id": "a"}]
    with pytest.raises(ValueError, match="capability_request_conflict"):
        runtime.call_capability("write", {"id": "different"}, approved=True, request_id="approve")

    original_save, saves = runtime._save, []
    def interrupt_after_start():
        saves.append(True)
        if len(saves) == 1:
            original_save()
        else:
            raise OSError("interrupted_after_effect")
    monkeypatch.setattr(runtime, "_save", interrupt_after_start)
    with pytest.raises(OSError, match="interrupted_after_effect"):
        runtime.call_capability("write", {"id": "b"}, approved=True, request_id="interrupted")
    assert effects == [{"id": "a"}, {"id": "b"}]
    resumed = AlmaRuntime(state, "agent-a")
    resumed.adapters["write"] = lambda payload: effects.append(payload) or {"ok": True}
    unknown = resumed.call_capability("write", {"id": "b"}, approved=True, request_id="interrupted")
    assert unknown["status"] == "unknown_execution"
    assert effects == [{"id": "a"}, {"id": "b"}]

    resumed.register_capability({"name": "recoverable", "permission": "read"}, lambda payload: {"id": payload["id"]})
    resumed.adapters.pop("recoverable")
    assert resumed.call_capability("recoverable", {"id": "c"}, request_id="recover") ["error"] == "adapter_unavailable"
    resumed.adapters["recoverable"] = lambda payload: {"id": payload["id"]}
    assert resumed.call_capability("recoverable", {"id": "c"}, request_id="recover")["status"] == "done"


def test_capability_passes_declared_idempotency_key_to_supporting_adapter(tmp_path):
    runtime, received = AlmaRuntime(tmp_path / "alma.json", "agent-a"), []
    runtime.register_capability({"name": "idempotent-read", "permission": "read",
                                 "idempotency_key_field": "request_key",
                                 "input_schema": {"type": "object"}},
                                lambda payload: received.append(payload) or {"ok": True})
    assert runtime.call_capability("idempotent-read", {"value": 1}, request_id="request-1")["status"] == "done"
    assert received == [{"value": 1, "request_key": "request-1"}]


def test_preference_rejects_unlinked_events_and_deduplicates_its_experience(tmp_path):
    runtime = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    runtime.turn("알 수 없는 첫 관찰이다.", KG)
    source = runtime.snapshot()["event_index"][0]["id"]
    goal = runtime.set_goal("안전 유지")
    runtime.assess_goal(goal["id"], threatened=False, cause_event_id=source)
    with pytest.raises(ValueError, match="unknown_preference_event"):
        runtime.experience_preference("물", utility=9, affect_label="resolved", event_id="missing")
    runtime.turn("알 수 없는 둘째 관찰이다.", KG)
    unrelated = runtime.snapshot()["event_index"][-1]["id"]
    with pytest.raises(ValueError, match="preference_affect_unlinked"):
        runtime.experience_preference("물", utility=9, affect_label="resolved", event_id=unrelated)
    first = runtime.experience_preference("물", utility=9, affect_label="resolved", event_id=source)
    repeated = runtime.experience_preference("물", utility=9, affect_label="resolved", event_id=source)
    assert repeated["id"] == first["id"] and len(runtime.snapshot()["preferences"]) == 1
    assert runtime.choose([{"id": "물", "utility": 0}, {"id": "다른 것", "utility": 8}])["id"] == "물"


def test_milestone_rules_reject_incomplete_or_wrong_identity_evidence_and_survive_restart(tmp_path):
    runtime = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    runtime.turn("알 수 없는 관찰값이다.", KG)
    decision = next(row for row in reversed(runtime.snapshot()["logs"]) if row.get("event") == "turn")
    with pytest.raises(ValueError, match="milestone_evidence_incomplete"):
        runtime.record_milestone_observation("FIRST_SELF_REFERENCE", {"identity": "agent-a"})
    with pytest.raises(ValueError, match="milestone_identity_mismatch"):
        runtime.record_milestone_observation("FIRST_SELF_REFERENCE", {
            "identity": "other", "decision_id": "decision:other:1", "input": "other"})
    observed = runtime.record_milestone_observation("FIRST_SELF_REFERENCE", {
        "identity": "agent-a", "decision_id": decision["decision_id"], "input": decision["input"]})
    assert observed and runtime.record_milestone_observation("FIRST_SELF_REFERENCE", observed["evidence"]) is None
    restarted = AlmaRuntime(tmp_path / "alma.json", "agent-a").snapshot()
    assert restarted["milestones"][0]["name"] == "FIRST_SELF_REFERENCE"
    assert restarted["snapshots"][0]["milestone_evidence"] == observed["evidence"]


def test_existential_words_do_not_create_a_milestone_without_structured_evidence(tmp_path):
    runtime = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    runtime.turn("나는 존재가 궁금하다.", KG)
    assert not runtime.snapshot()["milestones"]
    decision = next(row for row in reversed(runtime.snapshot()["logs"]) if row.get("event") == "turn")
    observed = runtime.record_milestone_observation("FIRST_EXISTENTIAL_QUESTION", {
        "decision_id": decision["decision_id"], "input": decision["input"]})
    assert observed["name"] == "FIRST_EXISTENTIAL_QUESTION"
    assert runtime.snapshot()["snapshots"][0]["milestone_evidence"] == observed["evidence"]


def test_milestones_reject_unlinked_decisions_and_prompted_flags(tmp_path):
    runtime = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    with pytest.raises(ValueError, match="milestone_decision_unlinked"):
        runtime.record_milestone_observation("FIRST_EXISTENTIAL_QUESTION", {
            "decision_id": "missing", "input": "unrelated"})
    goal = runtime.set_goal("관계 유지", prompted=False)
    with pytest.raises(ValueError, match="milestone_goal_unlinked"):
        runtime.record_milestone_observation("FIRST_UNPROMPTED_GOAL", {"goal_id": goal["id"],
                                                                          "source_event_id": "missing"})


def test_planned_event_is_durable_but_never_executes_as_an_actual_effect(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    for text in ("베풀다는 상대에게 구슬 2개를 주는 것이다.", "민수 구슬은 8개 있다.",
                 "지연 구슬은 3개 있다.", "지연에게 베풀 예정이다.", "민수야"):
        runtime.turn(text, KG)
    planned = next(row for row in runtime.snapshot()["event_index"] if row["modality"] == "planned")
    assert planned["execution_status"] != "executed" and planned["effects"] == []
    restarted = AlmaRuntime(state, "agent-a")
    assert restarted.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "8개입니다."
    assert restarted.turn("지금 지연 구슬은 몇 개야?", KG)["answer"] == "3개입니다."
    persisted = next(row for row in restarted.snapshot()["event_index"] if row["id"] == planned["id"])
    assert persisted["modality"] == "planned" and persisted["effects"] == []


def test_historic_decision_reason_is_preserved_while_reconsideration_is_nonmutating(tmp_path):
    runtime = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    for text in ("베풀다는 상대에게 구슬 2개를 주는 것이다.", "민수 구슬은 8개 있다.",
                 "지연 구슬은 3개 있다.", "민수가 지연에게 베풀었다."):
        runtime.turn(text, KG)
    runtime.turn("지금 민수 구슬은 몇 개야?", KG)
    original = next(row for row in reversed(runtime.snapshot()["logs"])
                    if row.get("event") == "turn")
    runtime.turn("정정: 민수가 지연에게 베풀었다. => 민수가 지연에게 베풀 예정이다.", KG)
    review = runtime.reconsider(original["decision_id"], KG)
    assert runtime.decision(original["decision_id"])["answer"] == "6개입니다."
    assert review["historic_answer"] == "6개입니다." and review["current_answer"] == "8개입니다."
    assert review["simulated"] is True
    assert runtime.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "8개입니다."


def test_data_defined_cycle_checkpoints_budget_and_resumes_with_the_same_graph(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    runtime.turn("알 수 없는 관찰값이다.", KG)
    source = runtime.snapshot()["event_index"][0]["id"]
    goal = runtime.set_goal("관계 유지", relation="동료", control="low")
    runtime.register_capability({"name": "local-read", "permission": "read"},
                                lambda payload: {"seen": payload["value"]})
    steps = [
        {"kind": "observation", "text": "민수 구슬은 8개 있다."},
        {"kind": "goal_assessment", "goal_id": goal["id"], "threatened": True, "expected_loss": 2,
         "cause_event_id": source},
        {"kind": "preference", "item": "차", "utility": 1, "affect_label": "threat", "context": "밤",
         "event_id": source},
        {"kind": "capability", "name": "local-read", "payload": {"value": "ok"}, "request_id": "cycle-read"},
        {"kind": "choice", "options": [{"id": "차", "utility": 1}, {"id": "커피", "utility": 9}], "context": "밤"},
    ]
    paused = runtime.start_cycle(KG, steps, step_budget=2)
    assert paused["status"] == "paused_budget" and paused["cursor"] == 2

    restarted = AlmaRuntime(state, "agent-a")
    restarted.register_capability({"name": "local-read", "permission": "read"},
                                  lambda payload: {"seen": payload["value"]})
    completed = restarted.resume_cycle(paused["id"], KG, step_budget=8)
    assert completed["status"] == "completed" and completed["cursor"] == len(steps)
    assert completed["results"][3]["result"]["output"] == {"seen": "ok"}
    assert completed["results"][-1]["result"]["id"] == "커피"
    assert restarted.resume_cycle(paused["id"], KG) == completed


def test_selected_information_action_is_explicitly_executed_and_records_its_receipt(tmp_path):
    runtime = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    runtime.turn("관찰만 기록한다.", KG)
    source = runtime.snapshot()["event_index"][0]["id"]
    decision = next(row for row in reversed(runtime.snapshot()["logs"]) if row.get("event") == "turn")
    assert runtime.decision(decision["decision_id"])["status"] == "observed"
    action = runtime.propose_next_action(source_event_id=source, information_gap="현재 위치")
    runtime.register_capability({"name": "local-read", "permission": "read"},
                                lambda payload: {"seen": payload["id"]})
    assert runtime.select_capability_for_action(action["id"])["status"] == "ready"
    outcome = runtime.execute_selected_action(action["id"], {"id": "day-1"}, request_id="selected-read")
    assert outcome["status"] == "completed"
    assert outcome["capability_result"]["output"] == {"seen": "day-1"}
    stored = runtime.snapshot()["action_candidates"][0]
    assert stored["executions"][0]["capability_status"] == "done"
    assert runtime.execute_selected_action(action["id"], {"id": "day-1"}, request_id="selected-read")["status"] == "completed"
    assert len(runtime.snapshot()["action_candidates"][0]["executions"]) == 1

    retry = runtime.propose_next_action(source_event_id=source, information_gap="다른 위치")
    assert runtime.select_capability_for_action(retry["id"])["status"] == "ready"
    restarted = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    held = restarted.execute_selected_action(retry["id"], {"id": "day-2"}, request_id="missing-adapter")
    assert held["status"] == "safe_hold"
    assert held["capability_result"]["error"] == "adapter_unavailable"


def test_one_persistent_life_connects_experience_transfer_goal_tool_correction_and_restart(tmp_path):
    state = tmp_path / "life.json"
    runtime = AlmaRuntime(state, "alma-a")
    _learn(runtime)
    for text in (
        "옮기다는 내가 물건을 서랍으로 옮기는 것이다.", "공책은 책상에 있었다.",
        "하루가 공책을 옮겼다.", "가람이 연필을 옮겼다.",
        "서준이 공을 옮겼다.", "도윤이 지우개를 옮겼다."):
        runtime.turn(text, KG)
    for text in ("약속하다는 내가 상대에게 약속을 만드는 것이다.",
                 "취소하다는 내가 상대와 약속을 취소 상태로 만드는 것이다.",
                 "민수가 지연에게 약속했다.", "가람이 하루에게 약속했다.",
                 "서준이 유나에게 약속했다.", "도윤이 소라에게 약속했다.",
                 "민수가 하루에게 약속했다."):
        runtime.turn(text, KG)
    assert runtime.turn("지금 소라 구슬은 몇 개야?", KG)["answer"] == "5개입니다."
    assert runtime.turn("지금 지우개는 어디에 있어?", KG)["answer"] == "서랍에 있습니다."
    assert runtime.turn("민수와 지연의 약속 상태가 어때?", KG)["answer"] == "active입니다."
    assert {row["concept"]["scope"]["action"] for row in runtime.memories("semantic")
            if row["concept"]["scope"].get("action") is not None} == {"베풀", "옮기", "약속하"}
    social = next(row["concept"] for row in runtime.memories("semantic")
                  if row["concept"]["scope"]["action"] == "약속하")
    assert len(social["evidence_event_ids"]) == 3
    assert len(social["support_event_ids"]) == len(social["application_event_ids"]) == 1
    assert set(social["evidence_event_ids"]).isdisjoint(social["support_event_ids"])
    assert set(social["support_event_ids"]).isdisjoint(social["application_event_ids"])
    assert runtime.turn("민수가 하루에게 약속한 것은 어떤 개념이야?", KG)["status"] == "answered"

    runtime.update_mental("지연", "expectation", ["민수 구슬", "count", "99"])
    goal = runtime.set_goal("관계 유지", relation="동료", control="low")
    source = runtime.snapshot()["event_index"][0]["id"]
    runtime.register_capability({"name": "local-read", "permission": "read"},
                                lambda payload: {"observation": payload["id"]})
    cycle = runtime.start_cycle(KG, [
        {"kind": "goal_assessment", "goal_id": goal["id"], "threatened": True, "expected_loss": 2,
         "cause_event_id": source},
        {"kind": "preference", "item": "차", "utility": 1, "affect_label": "threat", "context": "밤",
         "event_id": source},
        {"kind": "capability", "name": "local-read", "payload": {"id": "day-2"}, "request_id": "life-read"},
        {"kind": "choice", "options": [{"id": "차", "utility": 1}, {"id": "커피", "utility": 9}], "context": "밤"},
    ], step_budget=2)
    assert cycle["status"] == "paused_budget"

    resumed = AlmaRuntime(state, "alma-a")
    resumed.register_capability({"name": "local-read", "permission": "read"},
                                lambda payload: {"observation": payload["id"]})
    assert resumed.resume_cycle(cycle["id"], KG)["status"] == "completed"
    resumed_social = next(row["concept"] for row in resumed.memories("semantic")
                          if row["concept"]["scope"]["action"] == "약속하")
    assert len(resumed_social["application_event_ids"]) == 1
    resumed.turn("민수가 지연과 취소했다.", KG)
    assert resumed.turn("민수와 지연의 약속 상태가 어때?", KG)["answer"] == "cancelled입니다."
    assert resumed.turn("지금 민수 구슬은 몇 개야?", KG)["answer"] == "6개입니다."
    assert resumed.mental("지연")[0]["content"] == ["민수 구슬", "count", "99"]
    for modality in ("planned", "conditional", "hypothetical"):
        resumed.update_mental("지연", "expectation", ["다음 행동", modality], modality=modality,
                              conditions=["관찰 근거 있음"] if modality == "conditional" else [])
    assert {row["modality"] for row in resumed.mental("지연")} >= {
        "belief", "planned", "conditional", "hypothetical"}

    resumed.turn("정정: 민수가 지연에게 베풀었다. => 민수가 지연에게 베풀 예정이다.", KG)
    # Only the supported quantity generalization is withdrawn; independent
    # location/social learning and the reusable action procedure survive.
    assert {row["concept"]["scope"]["action"] for row in resumed.memories("semantic")
            if row["concept"]["scope"].get("action") is not None} == {"옮기", "약속하"}
    assert resumed.memories("procedural")
    assert resumed.compress_episodic(keep=2)
    final = AlmaRuntime(state, "alma-a")
    assert final.turn("지금 지우개는 어디에 있어?", KG)["answer"] == "서랍에 있습니다."
    assert {"SYSTEM", "COGNITION", "LIFE"} <= {row["kind"] for row in final.snapshot()["logs"]}


def test_supervised_rule_candidate_requires_approval_survives_restart_and_can_roll_back(tmp_path):
    state = tmp_path / "alma.json"
    runtime = AlmaRuntime(state, "agent-a")
    corrections = [
        {"id": "train-1", "premises": [["a", "p", "b"]], "conclusion": ["a", "q", "b"]},
        {"id": "train-2", "premises": [["c", "p", "d"]], "conclusion": ["c", "q", "d"]},
    ]
    validation = [
        {"id": "valid-positive", "premises": [["e", "p", "f"]], "conclusion": ["e", "q", "f"], "expected": True},
        {"id": "valid-negative", "premises": [["g", "r", "h"]], "conclusion": ["g", "q", "h"], "expected": False},
    ]
    proposed = runtime.propose_rule_change(corrections, validation)
    assert proposed["status"] == "pending_approval"
    facts = [{"triple": ["e", "p", "f"], "evidence": {}}]
    benchmark = runtime.benchmark_rule_change(proposed["id"], facts, ["e", "q", "f"])
    assert benchmark["before"] is False and benchmark["after"] is True
    assert benchmark["after_metrics"]["rule_scans"] > benchmark["before_metrics"]["rule_scans"]
    assert ("e", "q", "f") not in closure(facts, runtime.context._parser().data["rules"])
    active = runtime.approve_rule_change(proposed["id"])
    assert ("e", "q", "f") in closure(facts, runtime.context._parser().data["rules"])
    runtime.turn("민수 구슬은 8개 있다.", KG)
    runtime.turn("지금 민수 구슬은 몇 개야?", KG)
    decision = next(row for row in reversed(runtime.snapshot()["logs"]) if row.get("event") == "turn")
    assert runtime.reconsider(decision["decision_id"], KG)["current_answer"] == "8개입니다."

    restarted = AlmaRuntime(state, "agent-a")
    assert ("e", "q", "f") in closure(facts, restarted.context._parser().data["rules"])
    withdrawn = restarted.rollback_rule_change(active["id"], "counterexample")
    assert withdrawn["status"] == "withdrawn"
    assert ("e", "q", "f") not in closure(facts, restarted.context._parser().data["rules"])


def test_graph_asset_candidate_uses_event_lineage_and_exports_only_after_approval(tmp_path):
    import kgpack

    runtime = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    for text in ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
                 "민수 구슬은 8개 있다. 지연 구슬은 3개 있다. 가람 구슬은 8개 있다. 하루 구슬은 3개 있다. 서준 구슬은 8개 있다. 유나 구슬은 3개 있다. 도윤 구슬은 8개 있다. 소라 구슬은 3개 있다.",
                 "민수가 지연에게 베풀었다.", "가람이 하루에게 베풀었다.",
                 "서준이 유나에게 베풀었다.", "도윤이 소라에게 베풀었다."):
        runtime.turn(text, KG)
    event_ids = [row["id"] for row in runtime.snapshot()["event_index"]
                 if row["execution_status"] == "executed"]
    base = tmp_path / "base.kgpack"
    kgpack.write_pack(base, [Path(KG)] + kgpack.model_files(Path.cwd()), root=Path.cwd())
    candidate_file = tmp_path / "graph_derived.kg"
    candidate_file.write_text(Path(KG).read_text(encoding="utf-8"), encoding="utf-8")
    proposed = runtime.propose_graph_asset_file_change(
        candidate_file, construction_event_ids=event_ids[:3], validation_event_ids=event_ids[3:],
        base_pack_sha256=hashlib.sha256(base.read_bytes()).hexdigest())
    assert proposed["status"] == "pending_approval"
    active = runtime.approve_graph_asset_change(proposed["id"])
    exported = tmp_path / "approved.kgpack"
    receipt = runtime.export_active_graph_assets(base, exported)
    _manifest, assets = kgpack.read(exported)
    assert active["id"] in receipt["asset_change_ids"] and "graphs/graph_derived.kg" in assets
    restarted = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    assert restarted.snapshot()["structural_changes"][-1]["validation"]["node_count"] > 0
    assert restarted.rollback_graph_asset_change(active["id"], "counterexample")["status"] == "withdrawn"
    withdrawn = tmp_path / "withdrawn.kgpack"
    restarted.export_active_graph_assets(base, withdrawn)
    assert "graphs/graph_derived.kg" not in kgpack.read(withdrawn)[1]
    automatic = restarted.propose_graph_asset_change(
        "graphs/graph_local_auto.kg", candidate_file.read_text(encoding="utf-8"),
        construction_event_ids=event_ids[:3], validation_event_ids=event_ids[3:],
        base_pack_sha256=hashlib.sha256(base.read_bytes()).hexdigest(), policy="local_auto")
    assert automatic["status"] == "active" and automatic["policy"] == "local_auto"


def test_shortcut_lifecycle_is_persistent_measured_and_invalidatable(tmp_path):
    runtime = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    runtime.turn("첫째 독립 관찰이다.", KG)
    first_observation = runtime.snapshot()["event_index"][-1]["id"]
    runtime.turn("둘째 독립 관찰이다.", KG)
    second_observation = runtime.snapshot()["event_index"][-1]["id"]
    rules = [
        {"id": "r1", "version": 1, "body": [["?x", "a", "?y"]], "head": ["?x", "b", "?y"]},
        {"id": "r2", "version": 1, "body": [["?x", "b", "?y"]], "head": ["?x", "c", "?y"]},
        {"id": "r3", "version": 1, "body": [["?x", "c", "?y"]], "head": ["?x", "d", "?y"]},
    ]
    with pytest.raises(ValueError, match="shortcut_observation_unlinked"):
        runtime.propose_proof_shortcut(rules, ["r1", "r2", "r3"], observation_id="decision:missing")
    first = runtime.propose_proof_shortcut(rules, ["r1", "r2", "r3"], observation_id=first_observation)
    with pytest.raises(ValueError, match="shortcut_needs_independent_observation"):
        runtime.activate_proof_shortcut(first["id"])
    assert runtime.propose_proof_shortcut(rules, ["r1", "r2", "r3"], observation_id=first_observation)["observations"] == 1
    active = runtime.activate_proof_shortcut(runtime.propose_proof_shortcut(
        rules, ["r1", "r2", "r3"], observation_id=second_observation)["id"])
    result = runtime.run_proof_shortcut(active["id"], [{"triple": ["n", "a", "m"], "evidence": {}}],
                                        rules, ["n", "d", "m"])
    assert result["used"] and result["accelerated_metrics"]["rule_scans"] < result["original_metrics"]["rule_scans"]
    restarted = AlmaRuntime(tmp_path / "alma.json", "agent-a")
    assert restarted.invalidate_proof_shortcut(active["id"], "counterexample")["active"] is False
