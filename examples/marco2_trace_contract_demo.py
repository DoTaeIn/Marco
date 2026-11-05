"""Public offline synthetic trace-contract demo; no parser, learning store or live session."""
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from marco.trace import Ledger
from marco.trace.schema import problems
from marco.trace.why import Graph
from marco.runtime.dialogue_trace import DialogueTrace


def selected():
    return {"build": "public-synthetic-build", "pack": "public-synthetic-model",
            "model": {"content_fingerprint": "a" * 64, "effective_key": "a" * 64},
            "encoder": {"reference": "public-declared-encoder", "declaration_digest": "b" * 64},
            "realizer": {"reference": "public-declared-realizer", "declaration_digest": "c" * 64},
            "replay_status": "exact"}


def declared():
    return {"used_readings": [], "assumptions": [], "rules": [], "sources": [], "used_learning": [],
            "composition": [], "criterion": {"id": "public-synthetic-criterion", "scope": {"kind": "caller-report"}},
            "installed_memory_head": {"seq": 41, "change_id": "public-installed-head-41"}}


def result():
    return {"status": "answered", "operator": "public-synthetic-operator", "answer": "Public synthetic output",
            "verification": {"checks": [{"ok": True, "reason": "public-synthetic-check"}]}}


def demo(directory):
    directory = Path(directory)
    summaries = []
    with Ledger(directory, "public-synthetic-contract", fsync=True) as ledger:
        recorder = DialogueTrace(ledger, conversation="public-synthetic-conversation",
                                 runtime_stamp=selected(), provenance=declared())

        def pending(active, inp, trace):
            event = active.append("routing_selected", active.new_trace_id(), parent_ids=[inp],
                runtime={"build": "public-synthetic-build", "pack": "public-synthetic-model"},
                epistemic_status="inferred", payload={"selected": "public-synthetic-reading"})
            return [event["event_id"]]

        summaries.append(recorder.run("Public installed-only request", lambda _: result(), pending_flush=pending)["trace"])
        used = declared()
        used["used_learning"] = [{"candidate_id": "public-candidate-1", "rule_id": "public-rule-1",
            "rule_revision": 0, "accepted_change_id": "public-change-3",
            "teaching": {"conversation_id": "public-teaching-conversation", "turn_id": "public-teaching-turn"}}]
        summaries.append(recorder.run("Public explicitly reported use", lambda _: result(), provenance=used)["trace"])
        held = {**result(), "status": "unresolved", "answer": None,
                "meaning": {"act": "hold", "reason": "missing_declared_output_time"}}
        held_provenance = declared()
        held_provenance.update(proof={"root": "public-synthetic-proof", "complete": True},
            scope_assumption={"kind": "caller_declared_interpretation", "value": "public-scope", "sourced_time": False},
            truth_status="source_observed")
        summaries.append(recorder.run("Public local hold", lambda _: held, provenance=held_provenance)["trace"])

        def committed(attempt):
            recorder.mark_persistence(attempt, "memory", "committed", {"change_id": "public-memory-change-42"})
            return result()

        def failed_save(_, __):
            raise OSError("public synthetic save failure")

        try:
            recorder.run("Public save failure", committed, save=failed_save)
        except OSError:
            pass
        interrupted = recorder.begin("Public interrupted request")
        path = ledger.path

    with Ledger(directory, "public-synthetic-contract", fsync=True) as ledger:
        recorder = DialogueTrace(ledger, conversation="public-synthetic-conversation")
        recovered = recorder.recover_interrupted()
        again = recorder.recover_interrupted()
        graph = Graph(ledger.events)
        outputs = []
        for event in ledger.events:
            if event["kind"] != "output_created":
                continue
            payload = event["payload"]
            chain = graph.chain(event["event_id"])
            outputs.append({"event_id": event["event_id"], "attempt_id": payload["attempt_id"],
                "status": event["status"], "epistemic_status": event["epistemic_status"],
                "criterion_result": payload["criterion_result"], "world_truth_status": payload["world_truth_status"],
                "used_learning": payload["provenance"].get("used_learning"),
                "chain_kinds": [row["kind"] for row in chain],
                "why_inputs": [row["event_id"] for row in graph.inputs(event["event_id"])]})
        return {"mode": "offline_synthetic_contract", "log": str(path), "events": len(ledger.events),
            "validation_problems": [issue for event in ledger.events for issue in problems(event)],
            "outputs": outputs, "interrupted_attempt_id": interrupted.attempt_id,
            "recovered_event_ids": recovered, "second_recovery": again,
            "production_session_logging": False, "actual_used_declaration_collection": False,
            "world_truth_verified": False}


if __name__ == "__main__":
    directory = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp(prefix="marco2-public-trace-demo-")
    print(json.dumps(demo(directory), ensure_ascii=False, indent=2))
