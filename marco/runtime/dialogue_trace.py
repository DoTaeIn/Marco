"""Opt-in recorder contract; no session, parser, memory or model discovery.

``begin`` durably records an input before a caller executes it. ``finish``
records the supplied result and flushes caller pending events before output.
``run(text, execute)`` calls ``execute(attempt)`` and returns result + trace;
an optional ``save(attempt, result)`` runs before output. Persistence reports
are distinct from semantic use: a committed head never identifies a used rule.
The recorder is not wired to production dialogue by this module.
"""
from dataclasses import dataclass
import uuid

from marco.trace.from_turn import record_turn, session_for, sha
from marco.trace import runtime as rt


class TraceWriteError(RuntimeError):
    """A trace could not be written; never a claim that an output was logged."""

    def __init__(self, attempt_id, stage, path):
        self.attempt_id, self.stage, self.path = attempt_id, stage, str(path)
        super().__init__("trace_write_failed: attempt=%s stage=%s path=%s" % (attempt_id, stage, path))


def _note(error, text):
    """Attach a trace note to an exception that keeps its identity (``add_note`` on Python 3.11+)."""
    add_note = getattr(error, "add_note", None)
    if callable(add_note):
        add_note(text)


@dataclass(frozen=True)
class Attempt:
    attempt_id: str
    input_id: str
    trace_id: str
    text: str
    conversation: str
    turn: int
    runtime_stamp: dict
    provenance: dict


class DialogueTrace:
    def __init__(self, ledger, *, conversation="default", runtime_stamp=None, provenance=None):
        if ledger.fsync is not True:
            raise ValueError("DialogueTrace requires a fsync-enabled ledger")
        if not isinstance(conversation, str) or not conversation:
            raise ValueError("conversation must be a non-empty string")
        self.ledger, self.conversation = ledger, conversation
        self.runtime_stamp = rt.plain_json(runtime_stamp, "runtime_stamp") if runtime_stamp is not None else {}
        self.provenance = rt.plain_json(provenance, "provenance") if provenance is not None else {}
        rt.contract_provenance(self.runtime_stamp, self.provenance)

    def _append(self, kind, trace_id, *, attempt_id, stage, **fields):
        try:
            return self.ledger.append(kind, trace_id, **fields)
        except OSError as error:
            raise TraceWriteError(attempt_id, stage, self.ledger.path) from error

    def begin(self, text, *, turn=None, runtime_stamp=None, provenance=None):
        if not isinstance(text, str):
            raise TypeError("text must be a string")
        if turn is not None and (type(turn) is not int or turn < 1):
            raise ValueError("turn must be a positive integer")
        stamp = rt.plain_json(self.runtime_stamp if runtime_stamp is None else runtime_stamp, "runtime_stamp")
        declared = rt.plain_json(self.provenance if provenance is None else provenance, "provenance")
        contract = rt.contract_provenance(stamp, declared)
        attempt_id, trace_id = "attempt_" + uuid.uuid4().hex, self.ledger.new_trace_id()
        turn = turn if turn is not None else session_for(self.ledger, self.conversation).turns + 1
        event = self._append("input_received", trace_id, attempt_id=attempt_id, stage="input",
            subsystem="dialogue", epistemic_status="reported", runtime=contract["first"],
            source={"type": "dialogue_turn", "conversation": self.conversation, "turn": turn},
            payload={"text": text, "sha256": sha(text), "conversation": self.conversation, "turn": turn,
                     "attempt_id": attempt_id, "execution_status": "not_started",
                     "installed_memory_head": rt.plain_json(declared.get("installed_memory_head"), "installed_memory_head"),
                     "provenance_status": contract["status"], "provenance_missing": contract["missing"]})
        return Attempt(attempt_id, event["event_id"], trace_id, text, self.conversation, turn, stamp, declared)

    def _open(self, attempt):
        if not isinstance(attempt, Attempt) or attempt.conversation != self.conversation:
            raise rt.TraceContractError("attempt does not belong to this recorder conversation")
        event = self.ledger.get(attempt.input_id)
        if event is None or event["kind"] != "input_received" or event["payload"].get("attempt_id") != attempt.attempt_id:
            raise rt.TraceContractError("attempt input is not in this ledger")
        if event["trace_id"] != attempt.trace_id or event["payload"].get("conversation") != attempt.conversation \
                or event["payload"].get("text") != attempt.text or event["payload"].get("sha256") != sha(attempt.text):
            raise rt.TraceContractError("attempt identity does not match its input")
        if event["payload"].get("turn") != attempt.turn or event["source"].get("turn") != attempt.turn \
                or event["source"].get("conversation") != attempt.conversation:
            raise rt.TraceContractError("attempt turn does not match its input")
        first = rt.contract_provenance(attempt.runtime_stamp, attempt.provenance)["first"]
        if event["runtime"].get("selected") != first["selected"] \
                or event["runtime"].get("declared_runtime") != first["declared_runtime"]:
            raise rt.TraceContractError("attempt runtime does not match its input")
        if event["payload"].get("installed_memory_head") != attempt.provenance.get("installed_memory_head"):
            raise rt.TraceContractError("attempt provenance does not match its input")
        if any((e["kind"] == "output_created" or e["kind"] == "error" and e["payload"].get("terminal") is True)
               and e["payload"].get("attempt_id") == attempt.attempt_id for e in self.ledger.events):
            raise rt.TraceContractError("attempt is already terminal")

    def _persistence_refs(self, attempt):
        return [e["event_id"] for e in self.ledger.events
                if e["operation"].get("type") == "persistence"
                and e["payload"].get("attempt_id") == attempt.attempt_id
                and e["source"].get("input_event_id") == attempt.input_id]

    def _written(self, input_id, attempt_id):
        """Events already written for one attempt: its own, plus pending ones resting on its input.

        A pending callback may append input-bound events (without attempt identity) before it raises;
        an event of another attempt, or one not descending from this input, is never adopted.
        """
        start = self.ledger.position(input_id)
        reach, out = {input_id}, []
        for event in self.ledger.events[start + 1:]:
            owner = event["payload"].get("attempt_id")
            if owner not in (None, attempt_id) or event["kind"] in ("input_received", "output_created"):
                continue
            # Carrying this attempt's id is not enough: the event must also descend from this input,
            # or a callback's event rooted in another input would poison the error's ancestry.
            if any(p in reach for p in event["parent_ids"]):
                reach.add(event["event_id"])
                out.append(event["event_id"])
        return out

    def mark_persistence(self, attempt, operation, outcome, details=None):
        """Record a caller-reported operation outcome; do not infer candidate use or store contents."""
        self._open(attempt)
        if not isinstance(operation, str) or not operation or not isinstance(outcome, str) or not outcome:
            raise ValueError("operation and outcome must be non-empty strings")
        details = rt.plain_json(details, "persistence.details")
        common = dict(parent_ids=[attempt.input_id], subsystem="runtime", epistemic_status="reported",
            runtime=rt.contract_provenance(attempt.runtime_stamp, attempt.provenance)["base"],
            source={"type": "caller_report", "input_event_id": attempt.input_id},
            operation={"type": "persistence", "id": operation})
        payload = {"attempt_id": attempt.attempt_id, "operation": operation, "outcome": outcome,
                   "details": details, "terminal": False}
        if outcome == "failed":
            common.update(status="error", payload={**payload, "problem": "persistence_failure"})
            kind = "error"
        else:
            common.update(subject=attempt.attempt_id, payload={**payload, "field": "persistence." + operation,
                          "before": "unknown", "after": outcome, "cause": attempt.input_id})
            kind = "state_changed"
        return self._append(kind, attempt.trace_id, attempt_id=attempt.attempt_id, stage="persistence", **common)["event_id"]

    def finish(self, attempt, envelope, realizer_report=None, *, provenance=None, pending_flush=None,
               error=None, stage=None, **options):
        self._open(attempt)
        declared = attempt.provenance if provenance is None else rt.plain_json(provenance, "provenance")
        rt.contract_provenance(attempt.runtime_stamp, declared)

        def flush(ledger, input_id, trace_id):
            refs = self._persistence_refs(attempt)
            if pending_flush is not None:
                pending = pending_flush(ledger, input_id, trace_id)
                if pending is not None:
                    if not isinstance(pending, (list, tuple)):
                        raise rt.TraceContractError("pending_flush must return event IDs")
                    refs += list(pending)
            if error is not None:
                refs += [x for x in self._written(input_id, attempt.attempt_id) if x not in refs]
            return refs

        try:
            return record_turn(self.ledger, attempt.trace_id, attempt.text, envelope, realizer_report,
                conversation=attempt.conversation, turn=attempt.turn, prewritten_input=attempt.input_id,
                runtime_stamp=attempt.runtime_stamp, provenance=declared, attempt_id=attempt.attempt_id,
                pending_flush=flush, error=error, stage=stage, **options)
        except OSError as cause:
            raise TraceWriteError(attempt.attempt_id, "output", self.ledger.path) from cause

    def run(self, text, execute, *, save=None, pending_flush=None, realizer_report=None,
            provenance=None, turn=None, **options):
        """Call execute(attempt), then optional save(attempt, result); preserve raised execution/save errors.

        A successful save callback is only a completed callback, not a claim
        about a memory/session transaction. Caller reports those independently.
        """
        attempt = self.begin(text, turn=turn, provenance=provenance)
        stage = "execution"
        result = None
        try:
            result = execute(attempt)
            if save is not None:
                stage = "save_callback"
                try:
                    save(attempt, result)
                except Exception as error:
                    try:
                        self.mark_persistence(attempt, "save_callback", "failed", {"type": type(error).__name__})
                    except TraceWriteError as trace_error:
                        # The failed-save report could not be written: the save error keeps its
                        # identity and the unwritten trace is its explicit cause.
                        raise error from trace_error
                    raise
                self.mark_persistence(attempt, "save_callback", "completed")
            stage = "finalization"
            summary = self.finish(attempt, result, realizer_report, provenance=provenance,
                                  pending_flush=pending_flush, **options)
            return {"result": result, "trace": summary}
        except TraceWriteError:
            raise
        except Exception as error:
            # The pending callback is not retried: it may already have appended
            # events before raising. Record the failure against the same input.
            self._record_failure(attempt, result, error, stage, provenance)
            raise error

    def _record_failure(self, attempt, result, error, stage, provenance):
        """Write the terminal error of a failed attempt; the original exception is always what propagates.

        A trace that could not be written never disappears: it becomes the original error's ``__cause__``
        (a ``TraceWriteError`` or the metadata error that stopped the fallback), with a note on the error.
        """
        try:
            self.finish(attempt, result, error=error, stage=stage, provenance=provenance)
            return
        except TraceWriteError as trace_error:
            raise error from trace_error
        except Exception as malformed:
            first = malformed
        # Malformed result metadata is not retried: the terminal error still rests on the input, once, without it.
        try:
            self.finish(attempt, None, error=error, stage=stage, provenance=provenance)
        except TraceWriteError as trace_error:
            _note(error, "trace_result_omitted: %s: %s" % (type(first).__name__, first))
            raise error from trace_error
        except Exception as second:
            _note(error, "trace_not_written: %s: %s" % (type(second).__name__, second))
            raise error from second
        _note(error, "trace_result_omitted: %s: %s" % (type(first).__name__, first))

    def recover_interrupted(self):
        """Append one terminal interruption per unfinished durable input; never invent an output or restore state."""
        terminal = {e["payload"].get("attempt_id") for e in self.ledger.events
                    if e["kind"] == "output_created" or e["kind"] == "error" and e["payload"].get("terminal") is True}
        recovered = []
        for event in list(self.ledger.events):
            payload = event["payload"]
            aid = payload.get("attempt_id")
            if event["kind"] != "input_received" or not isinstance(aid, str) or aid in terminal:
                continue
            if payload.get("conversation") != self.conversation:
                continue
            refs = self._written(event["event_id"], aid)
            interruption = self._append("error", self.ledger.new_trace_id(), attempt_id=aid, stage="recovery",
                parent_ids=[event["event_id"]] + refs, status="error", subsystem="runtime",
                epistemic_status="unknown", runtime=dict(event["runtime"]),
                payload={"problem": "interrupted_attempt", "attempt_id": aid, "terminal": True,
                         "input_event_id": event["event_id"], "execution_outcome": "unknown",
                         "persistence_outcome": "see_caller_reports", "restoration": "not_performed"})
            recovered.append(interruption["event_id"])
            terminal.add(aid)
        return recovered
