"""The trace event, declared: envelope fields, event kinds, statuses, epistemic statuses.

Design note ``docs/ko/2026-09-24-trace-logging-design.md``: §38 is the minimal
envelope, §39 the event kinds, §16 the epistemic statuses, §8 the categories,
§32 the pretty tags. Everything here is data; ``validate`` reads only these
tables, so adding a kind or a status is a table row, not code.

Only the standard library.
"""
from collections import namedtuple

SCHEMA = "marco-event-v1"
EVENT_PREFIX = "evt_"
TRACE_PREFIX = "trace_"
SYSTEM = "MARCO"


class SchemaError(ValueError):
    """An event does not match the declared schema. ``field`` names the offending field."""

    def __init__(self, field, message):
        super().__init__("%s: %s" % (field, message))
        self.field = field


# ---------------------------------------------------------------------------
# §38 minimal envelope
# ---------------------------------------------------------------------------
Field = namedtuple("Field", "name types required nullable doc")

FIELDS = (
    Field("schema", (str,), False, False, "schema id; the ledger writes %r" % SCHEMA),
    Field("event_id", (str,), True, False, "evt_ + 26 characters, unique in the ledger"),
    Field("trace_id", (str,), True, False, "trace_ + 26 characters; one request (one dialogue turn)"),
    Field("parent_ids", (list,), True, False, "direct causes: earlier events of the same ledger (a DAG)"),
    Field("timestamp", (int, float), True, False, "seconds since the epoch when the event was written"),
    Field("system", (str,), False, False, "MARCO; SOMA, ALMA, POLO after the gate"),
    Field("subsystem", (str,), False, True, "dialogue, routing, reasoning, state, verification, realizer, trace"),
    Field("kind", (str,), True, False, "one of KINDS"),
    Field("status", (str,), True, False, "one of the statuses KINDS allows for the kind"),
    Field("epistemic_status", (str,), True, False, "one of EPISTEMIC (§16)"),
    Field("subject", (str,), True, True, "what the event is about: an entity, observation:<k>, or null"),
    Field("input_refs", (list,), True, False, "earlier events this one read (statements an operator used)"),
    Field("output_refs", (list,), True, False, "what this event produced, by reference"),
    Field("source", (dict,), True, False, "where an observation came from (§17): references and digests only"),
    Field("operation", (dict,), True, False, "the rule, operator or component that acted, with its version"),
    Field("payload", (dict,), True, False, "kind-specific fields; PAYLOAD lists the required ones"),
    Field("runtime", (dict,), True, False, "build and language pack on every event (§19); RUNTIME lists them"),
    Field("supersedes", (str,), False, True, "the earlier event this one replaces (§21); never an edit"),
    Field("scope", (dict,), False, True, "world or holder perspective (§27); post-gate, room only"),
    Field("goal_id", (str,), False, True, "goal branch (§30, §31); post-gate, room only"),
    Field("level", (str,), False, False, "log level (§35), separate from the kind"),
)
FIELD_NAMES = tuple(f.name for f in FIELDS)
REQUIRED = tuple(f.name for f in FIELDS if f.required)

LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")

# Every event's runtime carries these keys (§19, goal L1.6). The value may be
# null when it cannot be known (a ledger's own recovery event has no pack).
RUNTIME = ("build", "pack")
# The first event of a trace also carries these.
RUNTIME_FIRST = ("pack_digest", "model_digest", "encoder", "realizer", "replay_status")
REPLAY_STATUSES = ("exact", "approximate")


# ---------------------------------------------------------------------------
# §16 epistemic statuses
# ---------------------------------------------------------------------------
EPISTEMIC = {
    "observed": "seen by a sensor or read directly from input",
    "reported": "a user or another agent said it; not a verified fact",
    "hypothesized": "a candidate reading built from observations",
    "inferred": "derived by a rule or an operator",
    "assumed": "a premise held for hypothetical reasoning",
    "verified": "meets a declared verification criterion",
    "contradicted": "conflicts with other evidence",
    "withdrawn": "was active, has been withdrawn",
    "unknown": "not enough evidence to judge",
}


# ---------------------------------------------------------------------------
# statuses (the event's own ``status`` field)
# ---------------------------------------------------------------------------
STATUSES = {
    "success": "the step completed",
    "failed": "a check or rule did not hold",
    "error": "an execution error",
    "hold": "the turn was held: no answer given",
    "refused": "the turn was declined: a premise is missing",
    "answered": "an answer was said",
    "recorded": "a statement was recorded",
    "dialogue": "a conversational reply, no fact asserted",
    "unknown": "the envelope did not say",
}
# The statuses an ``output_created`` event can carry (goal L1.5 counts them).
OUTPUT_STATUSES = ("answered", "recorded", "hold", "refused", "dialogue", "error", "unknown")


# ---------------------------------------------------------------------------
# §39 event kinds, §8 categories, §32 tags
# ---------------------------------------------------------------------------
# emitted: this round's adapter (marco/trace/from_turn.py) or the ledger writes it.
# statuses: allowed ``status`` values; payload: required payload keys.
Kind = namedtuple("Kind", "category tag emitted statuses payload doc")
_OK = ("success",)
_OK_FAIL = ("success", "failed")

KINDS = {
    "input_received": Kind("OBSERVATION", "IN", True, _OK, ("text", "sha256"),
                           "a user turn arrived; epistemic status reported"),
    "observation_created": Kind("OBSERVATION", "OBS", True, _OK, ("index",),
                                "the engine stored a statement as observation <index>"),
    "observation_updated": Kind("OBSERVATION", "OBS", False, _OK, (), ""),
    "hypothesis_created": Kind("INTERPRETATION", "HYP", False, _OK, (), ""),
    "hypothesis_rejected": Kind("INTERPRETATION", "HYP", True, ("failed",), ("checks",),
                                "a verification check failed for a reason other than a contradiction"),
    "hypothesis_verified": Kind("INTERPRETATION", "VER", True, _OK, ("checks",),
                                "every verification check of the turn held"),
    "routing_candidates": Kind("DECISION", "RTE", False, _OK, (), ""),
    "routing_selected": Kind("DECISION", "RTE", True, _OK, ("selected",),
                             "the turn went to this path (no reasoning operator named)"),
    "evidence_found": Kind("REASONING", "EVD", True, _OK, ("ref",),
                           "a source the answer cites, by reference"),
    "evidence_rejected": Kind("REASONING", "EVD", False, _OK, (), ""),
    "rule_applied": Kind("REASONING", "INF", True, _OK, ("operator",),
                         "the reasoning operator ran over the statements it names"),
    "rule_blocked": Kind("REASONING", "INF", False, ("failed",), (), ""),
    "contradiction_found": Kind("REASONING", "CTR", True, ("failed",), ("checks",),
                                "a verification check found a contradiction"),
    "conclusion_created": Kind("REASONING", "CON", True, _OK, (),
                               "a fact or an explanation the answer states"),
    "conclusion_withdrawn": Kind("MUTATION", "WDR", True, _OK, ("withdrawn",),
                                 "an earlier event is no longer active (§21); it is not edited"),
    "goal_created": Kind("GOAL", "GOL", False, _OK, (), "post-gate"),
    "goal_completed": Kind("GOAL", "GOL", False, _OK, (), "post-gate"),
    "goal_failed": Kind("GOAL", "GOL", False, ("failed",), (), "post-gate"),
    "subgoal_created": Kind("GOAL", "GOL", False, _OK, (), "post-gate"),
    "state_changed": Kind("MUTATION", "STA", True, _OK, ("field", "before", "after", "cause"),
                          "a recorded state value changed (§20)"),
    "memory_created": Kind("MEMORY", "MEM", False, _OK, (), "post-gate"),
    "memory_recalled": Kind("MEMORY", "MEM", False, _OK, (), "post-gate"),
    "memory_withdrawn": Kind("MEMORY", "MEM", False, _OK, (), "post-gate"),
    "belief_created": Kind("BELIEF", "BEL", False, _OK, (), "post-gate (ALMA)"),
    "belief_revised": Kind("BELIEF", "BEL", False, _OK, (), "post-gate (ALMA)"),
    "appraisal_created": Kind("AFFECT", "AFF", False, _OK, (), "post-gate (ALMA)"),
    "affect_changed": Kind("AFFECT", "AFF", False, _OK, (), "post-gate (ALMA)"),
    "action_proposed": Kind("ACTION", "ACT", False, _OK, (), "post-gate"),
    "action_approved": Kind("ACTION", "ACT", False, _OK, (), "post-gate"),
    "action_executed": Kind("ACTION", "ACT", False, _OK, (), "post-gate"),
    "action_failed": Kind("ACTION", "ACT", False, ("failed",), (), "post-gate"),
    "output_created": Kind("OUTPUT", "OUT", True, OUTPUT_STATUSES, ("text", "realized"),
                           "what the user was shown; a result, never a cause"),
    "unknown": Kind("FAILURE", "UNK", False, _OK_FAIL, (), ""),
    "hold": Kind("FAILURE", "HLD", True, ("hold", "refused"), ("reason",),
                 "the turn was held; payload carries the reason and what is missing"),
    "error": Kind("FAILURE", "ERR", True, ("error",), ("problem",),
                  "an execution error, or a ledger recovery (a truncated line)"),
}

EMITTED = tuple(name for name, kind in KINDS.items() if kind.emitted)


def emitted_kinds():
    return EMITTED


# ---------------------------------------------------------------------------
# validator
# ---------------------------------------------------------------------------
def _is_event_id(value):
    return isinstance(value, str) and value.startswith(EVENT_PREFIX) and len(value) > len(EVENT_PREFIX)


def problems(event):
    """Every schema problem of ``event`` as ``(field, message)``; empty when it is valid."""
    out = []
    if not isinstance(event, dict):
        return [("event", "not an object")]
    for name in event:
        if name not in FIELD_NAMES:
            out.append((name, "unknown field"))
    for field in FIELDS:
        if field.name not in event:
            if field.required:
                out.append((field.name, "missing field"))
            continue
        value = event[field.name]
        if value is None:
            if not field.nullable:
                out.append((field.name, "must not be null"))
            continue
        if isinstance(value, bool) or not isinstance(value, field.types):
            out.append((field.name, "expected %s, got %s" % (
                "/".join(t.__name__ for t in field.types), type(value).__name__)))
    if out:
        return out
    if event.get("schema", SCHEMA) != SCHEMA:
        out.append(("schema", "unknown schema %r" % event["schema"]))
    if not _is_event_id(event["event_id"]):
        out.append(("event_id", "must start with %r" % EVENT_PREFIX))
    if not (event["trace_id"].startswith(TRACE_PREFIX) and len(event["trace_id"]) > len(TRACE_PREFIX)):
        out.append(("trace_id", "must start with %r" % TRACE_PREFIX))
    for name in ("parent_ids", "input_refs"):
        for i, ref in enumerate(event[name]):
            if not _is_event_id(ref):
                out.append(("%s[%d]" % (name, i), "not an event id: %r" % (ref,)))
        if len(set(event[name])) != len(event[name]):
            out.append((name, "duplicate id"))
    if event["event_id"] in event["parent_ids"]:
        out.append(("parent_ids", "an event cannot be its own parent"))
    for i, ref in enumerate(event["output_refs"]):
        if not isinstance(ref, str):
            out.append(("output_refs[%d]" % i, "not a string"))
    if event.get("supersedes") is not None and not _is_event_id(event["supersedes"]):
        out.append(("supersedes", "not an event id: %r" % (event["supersedes"],)))
    kind = KINDS.get(event["kind"])
    if kind is None:
        out.append(("kind", "unknown kind %r" % event["kind"]))
    elif event["status"] not in kind.statuses:
        out.append(("status", "%r is not a status of %s (allowed: %s)" % (
            event["status"], event["kind"], ", ".join(kind.statuses))))
    if event["status"] not in STATUSES:
        out.append(("status", "unknown status %r" % event["status"]))
    if event["epistemic_status"] not in EPISTEMIC:
        out.append(("epistemic_status", "unknown epistemic status %r" % event["epistemic_status"]))
    if kind is not None:
        for key in kind.payload:
            if key not in event["payload"]:
                out.append(("payload.%s" % key, "missing field (required for %s)" % event["kind"]))
    for key in RUNTIME:
        if key not in event["runtime"]:
            out.append(("runtime.%s" % key, "missing field"))
    replay = event["runtime"].get("replay_status")
    if replay is not None and replay not in REPLAY_STATUSES:
        out.append(("runtime.replay_status", "unknown replay status %r" % replay))
    if "level" in event and event["level"] not in LEVELS:
        out.append(("level", "unknown level %r" % event["level"]))
    return out


def validate(event):
    """Raise ``SchemaError`` naming the first offending field, or return the event."""
    found = problems(event)
    if found:
        field, message = found[0]
        raise SchemaError(field, message)
    return event
