"""One fixed ALMA life: learn, recall, act in a local environment, restart, correct."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alma.environment import run_local_environment
from alma.runtime import AlmaRuntime
import marco.storage.kgpack as kgpack
from bench.alma_environment_reproduction import scenario


KG = ROOT / "graphs" / "graph_일상추론.kg"


def run():
    checks = []
    started = time.perf_counter()
    tracemalloc.start()
    costs = {"unit": "seconds", "measurement": "time.perf_counter",
             "memory_unit": "bytes", "memory_measurement": "tracemalloc"}

    def check(name, expected, actual):
        checks.append({"name": name, "expected": expected, "actual": actual, "ok": expected == actual})

    with TemporaryDirectory(prefix="alma-unified-") as folder:
        state = Path(folder) / "life.json"
        preparation_started = time.perf_counter()
        runtime = AlmaRuntime(state, "unified-alma")
        for text in (
            "베풀다는 상대에게 구슬 2개를 주는 것이다.",
            "민수 구슬은 8개 있다. 지연 구슬은 3개 있다. 가람 구슬은 8개 있다. 하루 구슬은 3개 있다. 서준 구슬은 8개 있다. 유나 구슬은 3개 있다. 도윤 구슬은 8개 있다. 소라 구슬은 3개 있다. 하늘 구슬은 8개 있다. 별 구슬은 3개 있다."):
            runtime.turn(text, KG)
        costs["initial_preparation"] = time.perf_counter() - preparation_started
        learning_started = time.perf_counter()
        for text in (
            "민수가 지연에게 베풀었다.", "가람이 하루에게 베풀었다.", "서준이 유나에게 베풀었다.",
            "도윤이 소라에게 베풀었다.", "하늘이 별에게 베풀었다."):
            runtime.turn(text, KG)
        costs["candidate_learning_validation_application"] = time.perf_counter() - learning_started
        for text in ("옮기다는 내가 물건을 서랍으로 옮기는 것이다.",
                     "공책은 책상에 있었다.", "하루가 공책을 옮겼다."):
            runtime.turn(text, KG)
        action_events = [row for row in runtime.snapshot()["event_index"]
                         if row["execution_status"] == "executed"]
        for index, event in enumerate(action_events, start=1):
            runtime.annotate_event(event["id"], effective_at=index)
        past_state = {(row["subject"], row["predicate"]): row["value"]
                      for row in runtime.project_state_at(3)["state"]}
        check("timed_past_projection_uses_event_effects", 6,
              past_state[("민수 구슬", "count")])
        timed_location = {(row["subject"], row["predicate"]): row["value"]
                          for row in runtime.project_state_at(6)["state"]}
        check("timed_location_projection_uses_event_effect", "서랍",
              timed_location[("공책", "location")])
        question_started = time.perf_counter()
        learned = runtime.turn("하늘이 별에게 베푼 것은 어떤 개념이야?", KG)
        repeated = runtime.turn("하늘이 별에게 베푼 것은 어떤 개념이야?", KG)
        costs["repeated_question"] = time.perf_counter() - question_started
        check("learned_structure_answers_new_application", "answered", learned["status"])
        check("repeated_question_keeps_answer", learned["answer"], repeated["answer"])
        explanation_started = time.perf_counter()
        decision = next(row for row in reversed(runtime.snapshot()["logs"])
                        if row.get("kind") == "COGNITION" and row.get("event") == "turn")
        explanation = runtime.decision(decision["decision_id"])
        costs["durable_decision_explanation_read"] = time.perf_counter() - explanation_started
        check("decision_explanation_is_durable", decision["decision_id"], explanation["decision_id"])
        memory_started = time.perf_counter()
        procedural = runtime.recall("procedural", "베풀")
        costs["memory_read"] = time.perf_counter() - memory_started
        check("procedural_recall_has_source", "answered", procedural["status"])
        source = runtime.snapshot()["event_index"][0]["id"]
        natural_past = runtime.turn("과거 경험: " + source, KG)
        natural_general = runtime.turn("일반적으로 아는 것: 베풀", KG)
        natural_procedure = runtime.turn("하는 방법: 베풀", KG)
        check("korean_memory_questions_keep_typed_provenance", ["episodic", "semantic", "procedural"],
              [natural_past["memory"]["memory_kind"], natural_general["memory"]["memory_kind"],
               natural_procedure["memory"]["memory_kind"]])
        sentence_memory = [runtime.turn(source + "의 과거 경험은 뭐야?", KG),
                           runtime.turn("베풀에 대한 일반 지식은 뭐야?", KG),
                           runtime.turn("베풀의 절차는 뭐야?", KG)]
        check("sentence_memory_questions_keep_typed_provenance", ["episodic", "semantic", "procedural"],
              [row["memory"]["memory_kind"] for row in sentence_memory])
        memory_write_started = time.perf_counter()
        runtime.update_mental("unified-alma", "expectation", ["물", "count", "2"],
                              source_event_id=source, modality="conditional", conditions=["water-source"])
        natural_mental = runtime.turn("unified-alma의 기대는 뭐야?", KG)
        check("mental_remains_conditional", "conditional",
              runtime.query_mental("unified-alma", "expectation")["status"])
        check("korean_mental_question_stays_holder_scoped", ("conditional", False),
              (natural_mental["status"], natural_mental["mental"]["world_asserted"]))
        sentence_mental = runtime.turn("unified-alma는 무엇을 기대해?", KG)
        check("sentence_mental_question_stays_holder_scoped", ("conditional", False),
              (sentence_mental["status"], sentence_mental["mental"]["world_asserted"]))
        grounded_mental = runtime.update_mental("unified-alma", "expectation", ["물", "count", "2", "observed"],
                                                 source_event_id=source, modality="conditional",
                                                 conditions=[{"event_id": source}])
        grounded_query = runtime.query_mental("unified-alma", "expectation", content=grounded_mental["content"],
                                               observed_event_ids=[source])
        costs["memory_write_and_condition_query"] = time.perf_counter() - memory_write_started
        check("mental_condition_uses_event_proof_without_world_assertion", True,
              grounded_query["status"] == "answered" and grounded_query["world_asserted"] is False)

        environment = Path(folder) / "environment.json"
        environment.write_text(json.dumps(scenario(), ensure_ascii=False), encoding="utf-8")
        paused = run_local_environment(runtime, KG, scenario(), step_budget=1)
        check("environment_budget_pause", "paused_budget", paused["status"])
        recovery_started = time.perf_counter()
        resumed_process = subprocess.run(
            [sys.executable, str(ROOT / "alma/cli.py"), "--state", str(state), "--identity", "unified-alma",
             "--graph", str(KG), "--environment", str(environment), "--resume-environment", paused["id"],
             "--step-budget", "4"], cwd=ROOT, check=True, capture_output=True, encoding="utf-8")
        resumed = json.loads(resumed_process.stdout)
        resumed_runtime = AlmaRuntime(state, "unified-alma")
        costs["recovery"] = time.perf_counter() - recovery_started
        check("environment_resume_is_new_process", 0, resumed_process.returncode)
        check("environment_restart_completion", "completed", resumed["status"])
        check("environment_observation_resolves_goal", "resolved", resumed["final_affect"]["label"])
        check("semantic_survives_environment_restart", "answered", resumed_runtime.recall("semantic", "베풀")["status"])

        resumed_runtime.turn("정정: 민수가 지연에게 베풀었다. => 민수가 지연에게 베풀 예정이다.", KG)
        withdrawn = resumed_runtime.turn("하늘이 별에게 베푼 것은 어떤 개념이야?", KG)
        check("correction_withdraws_dependent_learning", "unresolved", withdrawn["status"])
        resumed_runtime.turn("정정: 민수가 지연에게 베풀 예정이다. => 민수가 지연에게 베풀었다.", KG)
        resumed_runtime = AlmaRuntime(state, "unified-alma")
        reactivated = resumed_runtime.turn("일반적으로 아는 것: 베풀", KG)
        check("restored_source_revalidates_semantic_memory_after_new_process", "answered", reactivated["status"])

        def preference_observation(target, goal, text, threatened):
            target.turn(text, KG)
            source = target.snapshot()["event_index"][-1]["id"]
            label = "threat" if threatened else "resolved"
            target.assess_goal(goal["id"], threatened=threatened, expected_loss=int(threatened),
                               cause_event_id=source)
            return source, label

        preference_goal = resumed_runtime.set_goal("밤 안전")
        night_sources = []
        for index, threatened in enumerate((False, False, True, True), start=1):
            source, label = preference_observation(resumed_runtime, preference_goal, "밤 취향 관찰 %d" % index, threatened)
            night_sources.append(source)
            resumed_runtime.experience_preference("차", utility=1, affect_label=label, context="밤", event_id=source)
        resumed_runtime.experience_preference("차", utility=1, affect_label="threat", context="밤",
                                              event_id=night_sources[-1])
        night_rows = [row for row in resumed_runtime.snapshot()["preferences"] if row["context"] == "밤"]
        check("preference_confidence_uses_independent_events_not_duplicate", (4, 4),
              (len(night_rows), len({row["event_id"] for row in night_rows})))
        check("conflicting_night_experience_changes_choice", "커피", resumed_runtime.choose(
            [{"id": "차", "utility": 1}, {"id": "커피", "utility": 9}], context="밤")["id"])
        morning_source, morning_label = preference_observation(resumed_runtime, preference_goal, "아침 취향 관찰", False)
        resumed_runtime.experience_preference("커피", utility=1, affect_label=morning_label, context="아침",
                                              event_id=morning_source)
        check("preference_context_changes_choice", "커피", resumed_runtime.choose(
            [{"id": "차", "utility": 1}, {"id": "커피", "utility": 1}], context="아침")["id"])
        preference_restart = AlmaRuntime(state, "unified-alma")
        check("preference_conflict_survives_restart", "커피", preference_restart.choose(
            [{"id": "차", "utility": 1}, {"id": "커피", "utility": 9}], context="밤")["id"])
        other_state = Path(folder) / "other-life.json"
        other = AlmaRuntime(other_state, "other-alma")
        other_goal = other.set_goal("밤 안전")
        other_source, other_label = preference_observation(other, other_goal, "다른 밤 관찰", False)
        other.experience_preference("차", utility=1, affect_label=other_label, context="밤", event_id=other_source)
        check("preference_isolation_allows_different_agent_choice", ("other-alma", "차"),
              (other.snapshot()["identity"], other.choose(
                  [{"id": "차", "utility": 1}, {"id": "커피", "utility": 9}], context="밤")["id"]))
        final = AlmaRuntime(state, "unified-alma").snapshot()
        check("environment_goal_persists_after_learning_correction", "achieved",
              next(row["status"] for row in final["goals"] if row["id"] == resumed["goal_id"]))
        check("three_ledgers_linked", True, {"SYSTEM", "COGNITION", "LIFE"} <= {row["kind"] for row in final["logs"]})
        future_goal = resumed_runtime.set_goal("다음 관찰 뒤 협력 관계 유지", relation="협력자",
                                               control="read", prompted=True)
        relation_source = resumed_runtime.snapshot()["event_index"][0]["id"]
        resumed_runtime.update_mental("협력자", "expectation", ["다음", "관찰", "대기"],
                                      source_event_id=relation_source, modality="planned")
        continuity = AlmaRuntime(state, "unified-alma").snapshot()
        continuity_observed = (continuity["identity"] == "unified-alma"
                                and any(row["id"] == future_goal["id"] and row["relation"] == "협력자"
                                        for row in continuity["goals"])
                                and any(row["holder"] == "협력자" and row["kind"] == "expectation"
                                        for row in continuity["mental"])
                                and bool(continuity["memories"]["episodic"]))
        check("continuity_experiment_observes_goal_relation_memory_identity", True, continuity_observed)
        backup = Path(folder) / "personal-backup.json"
        AlmaRuntime(state, "unified-alma").backup_state(backup)
        backup_process = subprocess.run(
            [sys.executable, str(ROOT / "alma/cli.py"), "--state", str(backup), "--identity", "unified-alma",
             "--recall", "procedural", "--recall-key", "베풀"], cwd=ROOT, check=True,
            capture_output=True, encoding="utf-8")
        check("personal_backup_restores_procedural_memory_in_new_process", "answered",
              json.loads(backup_process.stdout)["status"])
        clean = Path(folder) / "packed-restart"; clean.mkdir()
        pack, packed_state, packed_backup = clean / "knowledge.kgpack", clean / "life.json", clean / "life-backup.json"
        kgpack.write_pack(pack, [KG] + kgpack.model_files(ROOT), root=ROOT, language="styles/한국어.json")
        packed_base = [sys.executable, str(ROOT / "alma/cli.py"), "--pack", str(pack),
                       "--state", str(packed_state), "--identity", "packed-unified-alma"]
        for text in ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
                     "민수 구슬은 8개 있다. 지연 구슬은 3개 있다.",
                     "민수가 지연에게 베풀었다."):
            subprocess.run(packed_base + ["--turn", text], cwd=clean, check=True,
                           capture_output=True, encoding="utf-8")
        subprocess.run(packed_base + ["--backup-state", str(packed_backup)], cwd=clean, check=True,
                       capture_output=True, encoding="utf-8")
        packed_restart = subprocess.run(
            [*packed_base[:4], "--state", str(packed_backup), "--identity", "packed-unified-alma",
             "--turn", "지금 지연 구슬은 몇 개야?"], cwd=clean, check=True,
            capture_output=True, encoding="utf-8")
        check("pack_and_personal_backup_restore_without_loose_graph_files", "5개입니다.",
              json.loads(packed_restart.stdout)["answer"] if not list(clean.glob("*.kg")) else None)
        independent = [{"id": "unseen-application", "expected": "answered", "actual": learned["status"],
                        "ok": learned["status"] == "answered"},
                       {"id": "environment-goal-after-restart", "expected": "achieved",
                        "actual": next(row["status"] for row in final["goals"] if row["id"] == resumed["goal_id"]),
                        "ok": next(row["status"] for row in final["goals"] if row["id"] == resumed["goal_id"]) == "achieved"}]
        _current, peak = tracemalloc.get_traced_memory()
        costs["whole_scenario"] = time.perf_counter() - started
        costs["tracemalloc_peak_bytes"] = peak
        tracemalloc.stop()
        return {"input_mode": "natural_language_dialogue", "functional_checks": checks,
                "independent_problems": independent, "costs": costs,
                "continuity_experiment": {"subjective_experience_claim": False,
                                          "observed": {"identity": continuity["identity"],
                                                       "future_goal_id": future_goal["id"],
                                                       "relation_holder": "협력자",
                                                       "episodic_memory_count": len(continuity["memories"]["episodic"])}},
                "outcomes": {"solved": sum(row["ok"] for row in independent), "safe_hold": 0,
                             "wrong": sum(not row["ok"] for row in independent),
                             "execution_error": 0, "unverifiable": 0},
                "state_bytes": state.stat().st_size}


def main(argv=None):
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report, code = run(), 0
    except Exception as exc:
        report, code = {"terminal": "execution_error", "error": repr(exc),
                        "outcomes": {"solved": 0, "safe_hold": 0, "wrong": 0,
                                     "execution_error": 1, "unverifiable": 0}}, 1
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    sys.stdout.buffer.write(payload.encode("utf-8"))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
