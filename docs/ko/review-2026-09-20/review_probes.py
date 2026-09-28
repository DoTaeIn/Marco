"""Read-only review probes; all runtime mutations use temporary state files."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("KG_ENCODER", "문자")

from alma.runtime import AlmaRuntime
from graph_inference import closure
from marco.learning.chunking import evaluate, propose


def run():
    findings = {}
    with tempfile.TemporaryDirectory(prefix="marco-completion-review-") as directory:
        temp = Path(directory)
        path = temp / "identity.json"
        first = AlmaRuntime(path, "agent-a")
        first.set_goal("preserve this life")
        wrong_identity = AlmaRuntime(path, "agent-b")
        wrong_identity.set_goal("another life")
        disk = json.loads(path.read_text(encoding="utf-8"))
        original = AlmaRuntime(path, "agent-a")
        findings["identity_mismatch_overwrites_state"] = {
            "saved_identity": disk["identity"],
            "saved_goals": [g["goal"] for g in disk["goals"]],
            "original_identity_restored_goal_count": len(original.state["goals"]),
        }

        corrupt = temp / "corrupt.json"
        corrupt.write_text('{"schema":', encoding="utf-8")
        recovered = AlmaRuntime(corrupt, "agent-a")
        recovered.set_goal("fresh life silently replaces corrupt file")
        findings["corrupt_state_silently_replaced"] = {
            "raised": False,
            "saved_goals": [g["goal"] for g in json.loads(corrupt.read_text(encoding="utf-8"))["goals"]],
        }

        rules = [
            {"id": "r1", "version": 1, "body": [["?x", "a", "?y"]], "head": ["?x", "b", "?y"]},
            {"id": "r2", "version": 1, "body": [["?x", "b", "?y"]], "head": ["?x", "c", "?y"]},
            {"id": "r3", "version": 1, "body": [["?x", "c", "?y"]], "head": ["?x", "d", "?y"]},
            {"id": "branch", "version": 1, "body": [["?x", "b", "?y"]], "head": ["?x", "independent", "?y"]},
        ]
        facts = [{"triple": ["n", "a", "m"], "evidence": {}}]
        shortcut = propose(rules, ["r1", "r2", "r3"])
        shortcut["active"] = True
        measured_scans = []

        def measured_closure(*args, **kwargs):
            result = closure(*args, **kwargs)
            measured_scans.append(kwargs.get("metrics", {}).get("rule_scans", 0))
            return result

        with patch("marco.learning.chunking.closure", side_effect=measured_closure):
            result = evaluate(facts, rules, shortcut, ("n", "d", "m"))
        baseline = closure(facts, rules)
        findings["shortcut_drops_branch_and_runs_both_closures"] = {
            "used": result["used"],
            "target_preserved": ("n", "d", "m") in result["facts"],
            "lost_facts": sorted(set(baseline) - set(result["facts"])),
            "closure_calls": len(measured_scans),
            "actual_rule_scans": sum(measured_scans),
            "baseline_rule_scans": result["original_metrics"]["rule_scans"],
            "reported_accelerated_scans": result["accelerated_metrics"]["rule_scans"],
        }

        runtime = AlmaRuntime(temp / "shortcut.json", "agent-a")
        proposal = runtime.propose_proof_shortcut(rules, ["r1", "r2", "r3"])
        runtime.propose_proof_shortcut(rules, ["r1", "r2", "r3"])
        activated = runtime.activate_proof_shortcut(proposal["id"])
        findings["duplicate_proposals_activate_without_experience"] = {
            "active": activated["active"], "observations": activated["observations"],
            "event_count": len(runtime.state["event_index"]),
        }

        runtime = AlmaRuntime(temp / "approval.json", "agent-a")
        calls = []
        runtime.register_capability({"name": "harmless-test-write", "permission": "write"},
                                    lambda payload: calls.append(payload) or {"done": True})
        blocked = runtime.call_capability("harmless-test-write", {}, request_id="same-request")
        approved = runtime.call_capability("harmless-test-write", {}, approved=True, request_id="same-request")
        findings["approval_receipt_prevents_approved_retry"] = {
            "first_status": blocked["status"], "approved_retry_status": approved["status"],
            "adapter_calls": len(calls),
        }

        path = temp / "interrupted.json"
        runtime = AlmaRuntime(path, "agent-a")
        calls = []
        spec = {"name": "local-test-counter", "permission": "write"}
        runtime.register_capability(spec, lambda payload: calls.append("effect") or {"done": True})
        with patch.object(runtime, "_save", side_effect=OSError("simulated checkpoint interruption")):
            try:
                runtime.call_capability("local-test-counter", {}, approved=True, request_id="crash-retry")
            except OSError:
                pass
        restarted = AlmaRuntime(path, "agent-a")
        # Reattach the same adapter implementation without changing its saved contract.
        restarted.adapters["local-test-counter"] = lambda payload: calls.append("effect") or {"done": True}
        retried = restarted.call_capability("local-test-counter", {}, approved=True, request_id="crash-retry")
        findings["interrupted_checkpoint_reexecutes_same_request"] = {
            "same_request_adapter_calls": len(calls), "retry_status": retried["status"],
        }

        runtime = AlmaRuntime(temp / "preference.json", "agent-a")
        options = [{"id": "tea", "utility": 1}, {"id": "coffee", "utility": 9}]
        before = runtime.choose(options)
        preference = runtime.experience_preference("tea", utility=1, affect_label="resolved", event_id="nonexistent")
        after = runtime.choose(options)
        findings["supplied_label_changes_preference_without_experience"] = {
            "before": before["id"], "after": after["id"], "event_count": len(runtime.state["event_index"]),
            "affect_cause_count": len(runtime.state["affect"]["causes"]), "accepted_event_id": preference["event_id"],
        }
        milestone = runtime.record_milestone_observation("FIRST_EXISTENTIAL_QUESTION", {
            "decision_id": "nonexistent", "input": "ordinary unrelated text"})
        findings["milestone_accepts_nonexistent_evidence"] = {
            "recorded": milestone is not None, "evidence": milestone["evidence"],
        }
    return findings


if __name__ == "__main__":
    result = run()
    output = Path(__file__).with_name("review-probes.json")
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
