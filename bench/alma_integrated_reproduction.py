"""Fixed, local reproduction of one resumable ALMA life (no network)."""
import argparse
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time

ROOT = Path(__file__).resolve().parents[1]
import sys
import tracemalloc
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import resource
except ImportError:
    resource = None

from alma.runtime import AlmaRuntime
from graph_inference import closure


KG = ROOT / "graphs" / "graph_일상추론.kg"


def _outcomes(problems, *, execution_error=0):
    return {name: sum(row["outcome"] == name for row in problems) + (execution_error if name == "execution_error" else 0)
            for name in ("solved", "safe_hold", "wrong", "execution_error", "unverifiable")}


def _run(progress):
    checks, times, independent = progress["checks"], progress["costs"], progress["independent_problems"]
    tracemalloc.start()

    def check(name, expected, actual):
        checks.append({"name": name, "expected": expected, "actual": actual,
                       "ok": expected == actual})

    def timed(name, fn):
        began = time.perf_counter(); value = fn()
        times[name] = round((time.perf_counter() - began) * 1000, 3)
        return value

    with TemporaryDirectory(prefix="alma-integrated-") as folder:
        state = Path(folder) / "life.json"
        progress["state"] = state
        runtime = AlmaRuntime(state, "fixed-alma")
        plan_only = AlmaRuntime(Path(folder) / "plan-only.json", "plan-only")
        for text in ("베풀다는 상대에게 구슬 2개를 주는 것이다.", "민수 구슬은 8개 있다.",
                     "옮기다는 내가 물건을 서랍으로 옮기는 것이다.", "공책은 책상에 있었다.",
                     "약속하다는 내가 상대에게 약속을 만드는 것이다.",
                     "민수가 지연에게 베풀 예정이다.", "하루가 공책을 옮길 예정이다.",
                     "민수가 지연에게 약속할 예정이다.",
                     "다은은 내일 관찰할 거라고 기대해.", "라온은 내일 관찰할 거라고 기대해."):
            plan_only.turn(text, KG)
        first_plans = {row["domain"]: row for row in plan_only.snapshot()["event_index"]
                       if row.get("modality") == "planned"}
        resumed_plans = AlmaRuntime(Path(folder) / "plan-only.json", "plan-only")
        resumed_plan_rows = {row["domain"]: row for row in resumed_plans.snapshot()["event_index"]
                             if row.get("modality") == "planned"}
        check("first_natural_world_plans_stay_planned_without_prior_execution",
              [["planned", "planned", "planned"], ["8개입니다.", "책상에 있습니다.", "unresolved"],
               ["planned", "planned", "planned"]],
              [[first_plans[domain]["execution_status"] for domain in ("Quantity", "Location", "Social")],
               [plan_only.turn("지금 민수 구슬은 몇 개야?", KG)["answer"],
                plan_only.turn("지금 공책은 어디에 있어?", KG)["answer"],
                plan_only.turn("민수와 지연의 약속 상태가 어때?", KG)["status"]],
               [resumed_plan_rows[domain]["execution_status"] for domain in ("Quantity", "Location", "Social")]])
        plan_only_contract = plan_only.event_contract_transfer()
        plan_only_recall = plan_only.recall("semantic", "four-domain-event-contract")
        check("planned_world_events_do_not_activate_four_domain_contract", ["candidate", "safe_hold"],
              [plan_only_contract["status"], plan_only_recall["status"]])
        independent.append({
            "id": "four-domain-plans-only-hold", "split": "planned_world:3, natural_mental:2",
            "expected": "safe_hold", "actual": plan_only_recall["status"],
            "outcome": "safe_hold" if plan_only_recall["status"] == "safe_hold" else "wrong",
        })
        quantity = ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
                    "민수 구슬은 8개 있다. 지연 구슬은 3개 있다. 가람 구슬은 8개 있다. 하루 구슬은 3개 있다. 서준 구슬은 8개 있다. 유나 구슬은 3개 있다. 도윤 구슬은 8개 있다. 소라 구슬은 3개 있다.",
                    "민수가 지연에게 베풀었다.", "가람이 하루에게 베풀었다.",
                    "서준이 유나에게 베풀었다.", "도윤이 소라에게 베풀었다.")
        location = ("옮기다는 내가 물건을 서랍으로 옮기는 것이다.", "공책은 책상에 있었다.",
                    "하루가 공책을 옮겼다.", "가람이 연필을 옮겼다.",
                    "서준이 공을 옮겼다.", "도윤이 지우개를 옮겼다.")
        social = ("약속하다는 내가 상대에게 약속을 만드는 것이다.",
                  "취소하다는 내가 상대와 약속을 취소 상태로 만드는 것이다.",
                  "민수가 지연에게 약속했다.", "가람이 하루에게 약속했다.",
                  "서준이 유나에게 약속했다.", "도윤이 소라에게 약속했다.",
                  "민수가 하루에게 약속했다.")
        progress["stage"] = "learning"
        timed("learning_ms", lambda: [runtime.turn(text, KG) for text in quantity + location + social])
        first_event = next(row for row in runtime.snapshot()["event_index"]
                           if row["execution_status"] == "executed")
        annotated = runtime.annotate_event(first_event["id"], effective_at="day-0", place="마당")
        check("event_metadata_is_not_world_replay", "day-0", annotated["effective_at"])
        action = runtime.propose_next_action(source_event_id=first_event["id"],
                                             information_gap="지연의 현재 위치")
        check("observed_gap_creates_pending_action", ("seek_information", "pending"),
              (action["kind"], action["status"]))
        check("quantity_transfer", "5개입니다.", runtime.turn("지금 소라 구슬은 몇 개야?", KG)["answer"])
        check("location_transfer", "서랍에 있습니다.", runtime.turn("지금 지우개는 어디에 있어?", KG)["answer"])
        check("social_transfer", "active입니다.", runtime.turn("민수와 지연의 약속 상태가 어때?", KG)["answer"])
        semantic_memories = runtime.memories("semantic")
        check("three_independent_domain_semantics", ["베풀", "약속하", "옮기"],
              sorted(row["concept"]["scope"]["action"] for row in semantic_memories
                     if row["concept"]["scope"].get("action") is not None))
        natural_cross_domain = next((row["concept"] for row in semantic_memories
                                     if row["concept"]["scope"].get("structural_level")
                                     == "cross_domain_event_contract"), None)
        check("natural_cross_domain_event_contract", ["Location", "Quantity", "Social"],
              natural_cross_domain and natural_cross_domain["scope"]["domains"])
        check("natural_cross_domain_lineage", [3, 1, True],
              ([len(natural_cross_domain["evidence_event_ids"]),
                len(natural_cross_domain["support_event_ids"]),
                bool(natural_cross_domain["application_event_ids"])]
               if natural_cross_domain else None))
        social_concept = next(row["concept"] for row in runtime.memories("semantic")
                              if row["concept"]["scope"]["action"] == "약속하")
        check("social_construction_validation_application_split", [3, 1, 1],
              [len(social_concept["evidence_event_ids"]), len(social_concept["support_event_ids"]),
               len(social_concept["application_event_ids"])])
        check("social_application_is_held_out_from_validation", True,
              set(social_concept["support_event_ids"]).isdisjoint(social_concept["application_event_ids"]))
        social_application = runtime.turn("민수가 하루에게 약속한 것은 어떤 개념이야?", KG)
        check("social_learned_structure_answers_new_application", "answered", social_application["status"])
        independent.append({
            "id": "social-post-activation-application",
            "split": "construction:3, validation:1, post_activation_application:1",
            "source_event_id": social_concept["application_event_ids"][0],
            "expected": "answered", "actual": social_application["status"],
            "outcome": "solved" if social_application["status"] == "answered" else "wrong",
        })
        social_hypothesis = runtime.turn(
            "만약 도윤이 하루에게 약속했으면 도윤과 하루의 약속 상태가 어때?", KG)
        hypothetical_social_event = next(step["event"] for step in social_hypothesis["transitions"]
                                         if step.get("operation") == "hypothetical_action")
        check("social_hypothesis_stays_private", ["active입니다.", "hypothetical", "unresolved"],
              [social_hypothesis["answer"], hypothetical_social_event["modality"],
               runtime.turn("도윤과 하루의 약속 상태가 어때?", KG)["status"]])

        for planned_text in ("도윤이 소라에게 베풀 예정이다.",
                             "도윤이 지우개를 옮길 예정이다.",
                             "도윤이 소라에게 약속할 예정이다."):
            runtime.turn(planned_text, KG)
        planned_mental = runtime.update_mental("다은", "expectation", "내일 관찰", modality="planned")
        planned_domains = {row.get("domain"): row for row in runtime.snapshot()["event_index"]
                           if row.get("modality") == "planned"}
        check("four_domain_plans_remain_nonactual", ["planned", "planned", "planned", "private", True],
              [planned_domains["Quantity"]["execution_status"], planned_domains["Location"]["execution_status"],
               planned_domains["Social"]["execution_status"], planned_domains["Mental"]["execution_status"],
               all(row["effects"] == [] and row["state_changes"] == []
                   for row in planned_domains.values())
               and planned_domains["Mental"]["source"]["mental_id"] == planned_mental["id"]])
        for negative_text in ("민수가 지연에게 베풀지 않았다.",
                              "하루가 공책을 옮기지 않았다.",
                              "민수가 지연에게 약속하지 않았다."):
            runtime.turn(negative_text, KG)
        negative_mental = runtime.update_mental("다은", "belief", "내일 관찰", polarity=False)
        negative_domains = {row.get("domain"): row for row in runtime.snapshot()["event_index"]
                            if row.get("polarity") is False}
        check("four_domain_negative_events_remain_nonactual", ["negative", "negative", "negative", "private", True],
              [negative_domains["Quantity"]["execution_status"], negative_domains["Location"]["execution_status"],
               negative_domains["Social"]["execution_status"], negative_domains["Mental"]["execution_status"],
               all(row["effects"] == [] and row["state_changes"] == []
                   for row in negative_domains.values())
               and negative_domains["Mental"]["source"]["mental_id"] == negative_mental["id"]])
        for conditional_text in ("민수 구슬이 20개보다 많으면 민수가 지연에게 베풀었다.",
                                 "민수 구슬이 20개보다 많으면 하루가 공책을 옮겼다.",
                                 "민수 구슬이 20개보다 많으면 민수가 지연에게 약속했다."):
            runtime.turn(conditional_text, KG)
        false_conditions = {row.get("domain"): row for row in runtime.snapshot()["event_index"]
                            if row.get("execution_status") == "condition_false"}
        check("three_domain_false_conditions_remain_nonactual", ["condition_false", "condition_false", "condition_false", True],
              [false_conditions["Quantity"]["execution_status"], false_conditions["Location"]["execution_status"],
               false_conditions["Social"]["execution_status"],
               all(row["effects"] == [] and row["state_changes"] == []
                   for row in false_conditions.values())])

        mistaken_belief = runtime.update_mental("지연", "belief", ["민수 구슬", "count", "99"])
        runtime.revise_mental(mistaken_belief["id"], ["민수 구슬", "count", "6"],
                               reason="fixed_world_observation")
        check("mental_correction_stays_outside_world", "6", runtime.mental("지연")[0]["content"][-1])
        mental_past = runtime.query_mental("지연", "belief", as_of=mistaken_belief["at"])
        mental_current = runtime.query_mental("지연", "belief")
        check("mental_historical_query_separates_revision_from_current", ["99", "6", False],
              [mental_past["content"][-1], mental_current["content"][-1], mental_past["world_asserted"]])
        for modality in ("planned", "conditional", "hypothetical"):
            runtime.update_mental("지연", "expectation", ["다음 행동", modality], modality=modality,
                                  conditions=["관찰 근거 있음"] if modality == "conditional" else [])
        mental_modalities = {row["modality"] for row in runtime.mental("지연")}
        check("mental_transfer_preserves_plan_condition_hypothesis", True,
              {"belief", "planned", "conditional", "hypothetical"} <= mental_modalities)
        runtime.update_mental("수아", "expectation", ["다음 행동", "관찰"], modality="conditional",
                              source_event_id=first_event["id"], effective_at="tomorrow",
                              conditions=[{"event_id": first_event["id"]}])
        mental_reason = runtime.turn("수아의 기대의 이유는 뭐야?", KG)["mental"]
        check("mental_reason_natural_provenance", ["conditional", first_event["id"], "tomorrow", False],
              [mental_reason["status"], mental_reason["explanation"]["source_event_id"],
               mental_reason["explanation"]["effective_at"], mental_reason["explanation"]["world_asserted"]])
        mental_condition = runtime.turn("수아의 기대 조건이 충족됐어?", KG)["mental"]
        check("mental_condition_natural_uses_observed_event_without_world_assertion", ["answered", True, False],
              [mental_condition["status"], mental_condition["condition_proof"][0]["observed"],
               mental_condition["world_asserted"]])
        natural_mental = runtime.turn("다은은 내일 관찰할 거라고 기대해.", KG)
        check("natural_mental_statement_stays_private", ["observed", "expectation", False],
              [natural_mental["status"], natural_mental["mental"]["kind"],
               natural_mental["verification"]["world_asserted"]])
        private_event = next(row for row in runtime.snapshot()["event_index"]
                             if row.get("id") == natural_mental["mental"]["event_id"])
        world_event = next(row for row in runtime.snapshot()["event_index"]
                           if row.get("id") == first_event["id"])
        common_event_fields = {"id", "kind", "observed_at", "processed_at", "processed_sequence", "roles",
                               "conditions", "modality", "polarity", "source"}
        check("natural_mental_uses_common_private_event_contract", ["world", "mental", "private", True, True, True],
              [world_event["kind"], private_event["kind"], private_event["execution_status"],
               {"id", "observed_at", "processed_at", "processed_sequence", "roles", "conditions",
                "modality", "polarity", "source"} <= set(private_event),
               common_event_fields <= set(world_event) and common_event_fields <= set(private_event),
               (private_event["source"]["mental_id"] == natural_mental["mental"]["id"]
                and private_event["effects"] == [] and private_event["state_changes"] == [])])
        runtime.turn("라온은 내일 관찰할 거라고 기대해.", KG)
        four_domain_contract = runtime.event_contract_transfer()
        check("natural_four_domain_event_contract_stays_private", ["active", ["Quantity", "Location", "Social", "Mental"], [3, 1, True], False, False],
              [four_domain_contract["status"], four_domain_contract["domains"],
               [len(four_domain_contract["evidence_event_ids"]), len(four_domain_contract["support_event_ids"]),
                bool(four_domain_contract["application_event_ids"])],
               four_domain_contract["world_asserted"], four_domain_contract["effect_transfer"]])
        contract_recall = runtime.turn("일반적으로 아는 것: four-domain-event-contract", KG)
        check("natural_four_domain_contract_is_semantic_memory", ["answered", "event_contract_transfer"],
              [contract_recall["status"], contract_recall["memory"]["record"]["source"]])
        independent.append({
            "id": "four-domain-post-activation-recall", "split": "world_construction:3, natural_mental_validation:1, natural_mental_application:1",
            "source_event_id": four_domain_contract["application_event_ids"][0],
            "expected": "answered", "actual": contract_recall["status"],
            "outcome": "solved" if contract_recall["status"] == "answered" else "wrong",
        })
        runtime.revise_mental(natural_mental["mental"]["id"], natural_mental["mental"]["content"],
                             polarity=False, reason="four_domain_counterexample")
        withdrawn_contract = runtime.event_contract_transfer()
        withdrawn_recall = runtime.recall("semantic", "four-domain-event-contract")
        check("four_domain_counterexample_withdraws_semantic_contract", ["validated", "safe_hold"],
              [withdrawn_contract["status"], withdrawn_recall["status"]])
        independent.append({
            "id": "four-domain-counterexample-hold", "split": "world_construction:3, natural_mental_validation:1, counterexample:1",
            "expected": "safe_hold", "actual": withdrawn_recall["status"],
            "outcome": "safe_hold" if withdrawn_recall["status"] == "safe_hold" else "wrong",
        })
        reactivated_mental = runtime.turn("윤호는 내일 관찰할 거라고 기대해.", KG)
        reactivated_contract = runtime.event_contract_transfer()
        reactivated_recall = runtime.recall("semantic", "four-domain-event-contract")
        check("four_domain_new_natural_observation_reactivates_contract", ["active", "answered"],
              [reactivated_contract["status"], reactivated_recall["status"]])
        independent.append({
            "id": "four-domain-post-counterexample-recall",
            "split": "world_construction:3, natural_mental_validation:1, new_natural_application:1",
            "source_event_id": reactivated_mental["mental"]["event_id"],
            "expected": "answered", "actual": reactivated_recall["status"],
            "outcome": "solved" if reactivated_recall["status"] == "answered" else "wrong",
        })
        goal = runtime.set_goal("관계 유지", relation="동료", control="low")
        runtime.assess_goal(goal["id"], threatened=False, expected_loss=0, cause_event_id=first_event["id"])
        runtime.register_capability({"name": "fixed-read", "permission": "read",
                                     "input_schema": {"type": "object", "required": ["id"]},
                                     "output_schema": {"type": "object", "required": ["seen"]}},
                                    lambda payload: {"seen": payload["id"]})
        selected = runtime.select_capability_for_action(action["id"])
        check("gap_selects_single_read_capability", "fixed-read", selected.get("capability"))
        selected_execution = runtime.execute_selected_action(action["id"], {"id": "day-1"},
                                                              request_id="selected-read-1")
        check("selected_gap_action_calls_its_capability", ("completed", {"seen": "day-1"}),
              (selected_execution["status"], selected_execution["capability_result"]["output"]))
        progress["stage"] = "cycle_first_budget"
        cycle = timed("cycle_first_budget_ms", lambda: runtime.start_cycle(KG, [
            {"kind": "goal_assessment", "goal_id": goal["id"], "threatened": True, "expected_loss": 2,
             "cause_event_id": first_event["id"]},
            {"kind": "preference", "item": "차", "utility": 1, "affect_label": "resolved", "context": "밤",
             "event_id": first_event["id"]},
            {"kind": "capability", "name": "fixed-read", "payload": {"id": "day-2"}, "request_id": "fixed-read-1"},
            {"kind": "choice", "options": [{"id": "차", "utility": 1}, {"id": "커피", "utility": 9}], "context": "밤"},
        ], step_budget=2))
        check("budget_pause", "paused_budget", cycle["status"])
        runtime = AlmaRuntime(state, "fixed-alma")
        runtime.register_capability({"name": "fixed-read", "permission": "read"},
                                    lambda payload: {"seen": payload["id"]})
        progress["stage"] = "restart_resume"
        complete = timed("restart_resume_ms", lambda: runtime.resume_cycle(cycle["id"], KG, step_budget=8))
        check("cycle_restart", "completed", complete["status"])
        check("natural_four_domain_event_contract_survives_restart", "active",
              runtime.event_contract_transfer()["status"])
        check("natural_four_domain_contract_memory_survives_restart", "answered",
              runtime.recall("semantic", "four-domain-event-contract")["status"])
        check("four_domain_reactivation_lineage_survives_restart", [reactivated_mental["mental"]["event_id"]],
              runtime.event_contract_transfer()["application_event_ids"])
        nonactual_after_restart = [row for row in runtime.snapshot()["event_index"]
                                   if (row.get("modality") == "planned" or row.get("polarity") is False
                                       or row.get("execution_status") == "condition_false")]
        check("four_domain_nonactual_events_survive_restart", True,
              len(nonactual_after_restart) >= 11
              and all(row["effects"] == [] and row["state_changes"] == [] for row in nonactual_after_restart))
        check("goal_cause_changes_choice", "contact-colleague", runtime.choose([
            {"id": "contact-colleague", "utility": 0, "supports_relation": "동료"},
            {"id": "wait", "utility": 0},
        ])["id"])
        protection = runtime.propose_next_action(source_event_id=first_event["id"], goal_id=goal["id"])
        runtime.resolve_goal(goal["id"], "achieved", source_event_id=first_event["id"])
        check("goal_resolution_cancels_protection", "cancelled", next(
            row for row in runtime.snapshot()["action_candidates"] if row["id"] == protection["id"])["status"])
        revised = runtime.revise_preference(complete["results"][1]["result"]["id"], affect_label="threat",
                                            reason="fixed_counterexample")
        check("preference_correction_changes_choice", "커피", runtime.choose(
            [{"id": "차", "utility": 1}, {"id": "커피", "utility": 9}], context="밤")["id"])
        check("preference_correction_keeps_link", True, bool(revised.get("supersedes")))
        runtime.turn("민수가 지연과 취소했다.", KG)
        check("social_correction_after_restart", "cancelled입니다.", runtime.turn("민수와 지연의 약속 상태가 어때?", KG)["answer"])
        check("mental_is_not_world", "6개입니다.", runtime.turn("지금 민수 구슬은 몇 개야?", KG)["answer"])

        corrections = [{"premises": [["a", "p", "b"]], "conclusion": ["a", "q", "b"]},
                       {"premises": [["c", "p", "d"]], "conclusion": ["c", "q", "d"]}]
        validation = [{"premises": [["e", "p", "f"]], "conclusion": ["e", "q", "f"], "expected": True},
                      {"premises": [["g", "r", "h"]], "conclusion": ["g", "q", "h"], "expected": False}]
        proposal = runtime.propose_rule_change(corrections, validation)
        rule_benchmark = runtime.benchmark_rule_change(proposal["id"],
                                                        [{"triple": ["e", "p", "f"], "evidence": {}}],
                                                        ["e", "q", "f"])
        check("rule_change_benchmark_ab", (False, True), (rule_benchmark["before"], rule_benchmark["after"]))
        runtime.approve_rule_change(proposal["id"])
        check("approved_rule_changes_closure", True, ("e", "q", "f") in closure(
            [{"triple": ["e", "p", "f"], "evidence": {}}], runtime.context._parser().data["rules"]))
        runtime.rollback_rule_change(proposal["id"], "fixed_counterexample")

        shortcut_rules = [
            {"id": "s1", "version": 1, "body": [["?x", "a", "?y"]], "head": ["?x", "b", "?y"]},
            {"id": "s2", "version": 1, "body": [["?x", "b", "?y"]], "head": ["?x", "c", "?y"]},
        ]
        shortcut_observations = [row["id"] for row in runtime.snapshot()["event_index"][:2]]
        shortcut = runtime.propose_proof_shortcut(shortcut_rules, ["s1", "s2"], observation_id=shortcut_observations[0])
        shortcut = runtime.propose_proof_shortcut(shortcut_rules, ["s1", "s2"], observation_id=shortcut_observations[1])
        runtime.activate_proof_shortcut(shortcut["id"])
        shortcut_run = runtime.run_proof_shortcut(shortcut["id"],
                                                   [{"triple": ["n", "a", "m"], "evidence": {}}],
                                                   shortcut_rules, ["n", "c", "m"])
        shortcut_preparation = shortcut_run
        shortcut_run = runtime.run_proof_shortcut(shortcut["id"],
                                                   [{"triple": ["n", "a", "m"], "evidence": {}}],
                                                   shortcut_rules, ["n", "c", "m"])
        progress["shortcut_costs"] = {
            "preparation_validation_rule_scans": shortcut_preparation["total_metrics"],
            "repeated_rule_scans": shortcut_run["total_metrics"],
            "original_rule_scans": shortcut_run["original_metrics"],
            "source_rule_ids": [row["id"] for row in shortcut_run["shortcut"]["source"]],
        }
        check("shortcut_reduces_real_rule_scans", True, shortcut_run["used"] and
              shortcut_run["total_metrics"]["rule_scans"] < shortcut_run["original_metrics"]["rule_scans"])
        runtime.invalidate_proof_shortcut(shortcut["id"], "fixed_counterexample")

        runtime.turn("정정: 민수가 지연에게 베풀었다. => 민수가 지연에게 베풀 예정이다.", KG)
        check("correction_withdraws_only_dependent_semantic", ["four-domain-event-contract", "약속하", "옮기"],
              sorted(row["concept"]["scope"]["action"] for row in runtime.memories("semantic")
                     if row["concept"]["scope"].get("action") is not None))
        progress["stage"] = "episodic_save"
        timed("episodic_save_ms", lambda: runtime.compress_episodic(keep=2))
        runtime = AlmaRuntime(state, "fixed-alma")
        check("post_correction_restart", "서랍에 있습니다.", runtime.turn("지금 지우개는 어디에 있어?", KG)["answer"])
        resumed_social = next(row["concept"] for row in runtime.memories("semantic")
                              if row["concept"]["scope"]["action"] == "약속하")
        check("social_application_lineage_survives_restart", 1,
              len(resumed_social["application_event_ids"]))
        progress["stage"] = "long_term_search"
        search_rows = timed("long_term_search_ms", lambda: runtime.search("민수"))
        check("long_term_search_after_restart", True, bool(search_rows))
        snapshot = runtime.snapshot()
        check("three_log_kinds", True, {"SYSTEM", "COGNITION", "LIFE"} <= {row["kind"] for row in snapshot["logs"]})
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024 if resource else None
        return {"input_mode": "natural_language_dialogue",
                "environment": {"graph_sha256": hashlib.sha256(KG.read_bytes()).hexdigest(),
                                  "python": sys.version.split()[0]}, "checks": checks,
                # These are feature checks, not independently sampled
                # problems.  Keep their count separate from outcome classes
                # so a green implementation checklist cannot masquerade as a
                # task-solution score.
                "functional_checks": {"solved": sum(row["ok"] for row in checks),
                                      "wrong": sum(not row["ok"] for row in checks)},
                "independent_problems": independent, "outcomes": _outcomes(independent),
                "costs": times, "shortcut_costs": progress.get("shortcut_costs"), "state_bytes": state.stat().st_size,
                "tracemalloc_peak_bytes": peak, "process_max_rss_bytes": rss,
                "process_max_rss_supported": resource is not None}


def run():
    """Return partial evidence on every evaluator failure; ``main`` still fails."""
    progress = {"checks": [], "costs": {}, "shortcut_costs": None, "independent_problems": [],
                "stage": "prepare", "state": None}
    try:
        return _run(progress)
    except Exception as exc:
        _, peak = tracemalloc.get_traced_memory() if tracemalloc.is_tracing() else (None, 0)
        if tracemalloc.is_tracing():
            tracemalloc.stop()
        state = progress["state"]
        return {"input_mode": "natural_language_dialogue",
                "environment": {"graph_sha256": hashlib.sha256(KG.read_bytes()).hexdigest(),
                                "python": sys.version.split()[0]}, "checks": progress["checks"],
                "functional_checks": {"solved": sum(row["ok"] for row in progress["checks"]),
                                      "wrong": sum(not row["ok"] for row in progress["checks"])},
                "independent_problems": progress["independent_problems"],
                "outcomes": _outcomes(progress["independent_problems"], execution_error=1),
                "costs": progress["costs"], "shortcut_costs": progress.get("shortcut_costs"), "terminal": "execution_error",
                "failed_stage": progress["stage"], "error": repr(exc),
                "state_bytes": state.stat().st_size if state and state.exists() else None,
                "tracemalloc_peak_bytes": peak,
                "process_max_rss_bytes": None, "process_max_rss_supported": resource is not None}


def main(argv=None):
    options = argparse.ArgumentParser(); options.add_argument("--output", type=Path)
    args = options.parse_args(argv)
    try:
        report = run(); code = 0 if report["outcomes"]["wrong"] == 0 and not report.get("terminal") else 1
    except Exception as exc:
        report, code = {"terminal": "execution_error", "error": repr(exc)}, 1
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    sys.stdout.buffer.write(payload.encode("utf-8"))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
