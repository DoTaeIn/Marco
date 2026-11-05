"""Public MARCO2 development demo: actual sessions and append-only causal logs.

Run teach, read, retract, error with separate Python interpreters and the same
--directory. This demonstrates explicit expression teaching, archived readings,
local missing-premise holds and source reporting from an OFFLINE fixture. It is
not a web-fetch or autonomous-learning demonstration or a protected exam result.
Exact declaration-to-learning use and actual realizer collection remain absent;
all output provenance therefore stays explicitly incomplete.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pack_model
from examples.marco2_dialogue_demo import teaching
from marco.runtime.learning_dialogue import DialogueSession
from marco.trace import Ledger
from marco.trace.why import Graph


def source_fixture(query):
    """Caller-supplied public fixture; nothing is fetched or admitted to the graph."""
    return {"status": "observed", "query": query, "mode": "offline_public_fixture",
            "sources": [{"url": "https://example.org/public", "title": "Synthetic source fixture"}],
            "claims": [{"text": "A source reported a synthetic observation."}]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--phase", required=True, choices=("teach", "read", "retract", "error"))
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    model = pack_model.development_model("english")  # explicit public development graph
    result = {"phase": args.phase, "mode": "public_development_fixture", "actions": []}
    with Ledger(args.directory / "trace", "session", fsync=True) as ledger:
        first = len(ledger.events)
        with DialogueSession(args.directory / "memory.sqlite", args.directory / "session.json",
                             model=model, conversation_id="public-session-trace-demo",
                             trace_ledger=ledger, research_hook=source_fixture) as session:
            def record(label, operation):
                value = operation()
                result["actions"].append({"action": label, "result": value})
                return value

            if args.phase == "teach":
                record("respond", lambda: session.respond("Kellan is taller than Marin."))
                record("teach", lambda: session.teach(teaching(), turn_id="public-teach-1"))
            elif args.phase == "read":
                record("respond", lambda: session.respond("Compared with Orin, Vega towers."))
                record("respond", lambda: session.respond("Orin is taller than Lune."))
                record("transitive_question", lambda: session.respond("Who is taller, Vega or Lune?"))
                record("local_missing_question", lambda: session.respond("Who is taller, Juno or Milo?"))
                record("continue_grounded_question", lambda: session.respond("Who is taller, Kellan or Marin?"))
                before = session.snapshot()
                record("research_fixture", lambda: session.research("Synthetic public source query"))
                result["research_changed_context"] = session.snapshot() != before
            elif args.phase == "retract":
                active = next(row for row in session.memory.candidates() if row["status"] == "active")
                record("retract", lambda: session.retract(active["candidate_id"], "Public teaching withdrawn."))
                record("historical_question", lambda: session.respond("Who is taller, Vega or Lune?"))
                # A new use is not licensed by the withdrawn expression; history is retained.
                result["withdrawn_expression_recognized_now"] = bool(
                    (session.memory.parser().parse("Compared with Sena, Tavi towers.") or {}).get("events"))
            else:
                original = OSError("Public injected session-save fault")
                with patch.object(session, "_save_state", side_effect=original):
                    try:
                        session.respond("Who is taller, Kellan or Marin?")
                    except OSError as error:
                        if error is not original:
                            raise
                        result["actions"].append({"action": "injected_save_failure", "error_type": type(error).__name__})
                    else:
                        raise AssertionError("The public injected save failure was swallowed")
                record("continue_after_error", lambda: session.respond("Who is taller, Kellan or Marin?"))
            result.update(model_content_fingerprint=model.content_fingerprint,
                          semantic_turn_counter=session.turn_counter, installed_memory_head=session._binding())
        graph = Graph(ledger.events)
        result["trace_path"] = str(ledger.path)
        result["outputs"] = []
        for event in ledger.events[first:]:
            if event["kind"] != "output_created":
                continue
            payload = event["payload"]
            chain = graph.chain(event["event_id"])
            result["outputs"].append({
                "event_id": event["event_id"], "attempt_id": payload["attempt_id"],
                "attempt_turn": payload["turn"], "status": event["status"], "text": payload["text"],
                "provenance_status": payload["provenance_status"],
                "provenance_missing": payload["provenance_missing"],
                "used_readings": payload["provenance"].get("used_readings"),
                "used_learning_collected": "used_learning" in payload["provenance"],
                "criterion_result": payload["criterion_result"], "check_event": payload["check_event"],
                "world_truth_status": payload["world_truth_status"],
                "causal_event_kinds": [row["kind"] for row in chain]})
        result["limits"] = ["Explicit teaching and finite transfer checks; not autonomous discovery.",
                            "Offline source fixture; no live internet request in this demo.",
                            "Installed memory head does not establish actual learning rule use.",
                            "Provenance remains incomplete until exact use collectors exist."]
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
