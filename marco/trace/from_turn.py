"""Adapter: one dialogue turn's envelope -> ledger events (goal L1.3).

The engine is not edited. ``record_turn`` reads what a turn already returns:

* the UI envelope, what ``views.kgpack_ui.AppState.turn`` returns (``phase``,
  ``answer.trace`` with mode, winner and verdict, ``answer.reasoning`` with
  ``operator`` and ``transitions``, ``answer.verification``), or a
  ``ReasoningContext.turn`` result (``status``, ``operator``, ``transitions``,
  ``verification``, ``meaning``);
* optionally the ``ReasoningContext.turn`` result behind a UI envelope
  (``context_result``), or the meaning a UI hold was said from (``meaning``,
  ``AppState._said``): the UI envelope drops the ``meaning`` block, which
  names a hold's reason and what is missing (request L1-1 names the gap);
* the realizer's report for the reply (``marco.language.realizer``), or None
  when the turn did not pass through it. Its ``meaning`` (the act and reason the
  reply was said from, ids only) and ``plan`` (the matched turn plan's match) go
  into ``output_created`` (request W4-2); a hold whose envelope gave no meaning
  takes its reason from the report.

Per turn, one trace (design note §6):

    input_received      the user said it (epistemic status: reported)
    observation_created the engine stored the statement as observation <k>
    rule_applied        the reasoning operator, input_refs = the statements it used
      | routing_selected  when no operator is named: the path the turn took
    state_changed       each new transition, before/after/cause (§20); a changed
                        one supersedes the old event and withdraws it (§21)
    evidence_found      each cited source, by reference
    conclusion_created  each answered fact (or the explanation)
    hypothesis_verified | contradiction_found | hypothesis_rejected   the checks
    hold                a held turn: meaning.reason and what is missing
    output_created      parents: the conclusions, the hold, or the recorded changes

A transition the ledger already holds is referenced, not written again: the
envelope replays the whole conversation's state on every turn. Every event
except ``input_received`` has at least one parent (§44 principle 4).

Only the standard library.
"""
import hashlib
import json
import uuid

from marco.trace import runtime as rt

# bench/dialogue_gate.py: its verdict vocabulary (OBSERVED, HELD, CHAT) and status().
# tests/trace/test_trace_from_turn.py checks these against the gate's own code.
GATE_OBSERVED = frozenset({"상태기억"})
GATE_HELD = frozenset({"조건부족", "입력이해실패", "근거불충분", "미지", "B2", "지식부족", "근거없음", "전제불성립"})
GATE_CHAT = frozenset({"대화"})
# views/kgpack_ui.py AppState.turn: a ReasoningContext status as the verdict the UI shows.
STATUS_VERDICT = {"answered": "계산완료", "observed": "상태기억", "unresolved": "조건부족"}
# reasoning_context.ReasoningContext.CONTRADICTION (checked by a test), and the
# meaning reasons that name a contradiction.
CONTRADICTION_CHECKS = frozenset({"invalid_quantity_result", "invalid_quantity_delta", "invalid_initial_quantity"})
CONTRADICTION_REASONS = frozenset({"contradiction", "conflicting_event", "conflicting_definition"})

OUTPUT_OF_GATE = {"answered": "answered", "observed": "recorded", "chat": "dialogue", "error": "error",
                  "unknown": "unknown"}
STATE_OPERATIONS = ("state_update", "quantity_update")
# meaning fields that say what a held turn is missing.
MISSING_KEYS = ("subject", "relation", "slots", "slot_keys", "word", "candidates", "missing")
SOURCES_KEPT = 10


def sha(text):
    return hashlib.sha256(str(text).strip().encode("utf-8")).hexdigest()


def _scalar(value):
    return value if value is None or isinstance(value, (str, int, float, bool)) else str(value)


def _plain(value):
    """A declared value (a turn plan's match) as plain JSON: dicts, lists and scalars."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    return _scalar(value)


def _unique(ids):
    return list(dict.fromkeys(x for x in ids if x))


# ---------------------------------------------------------------------------
# the envelope, read
# ---------------------------------------------------------------------------
def _request_kind(understanding):
    """``understanding.overall.primary.kind`` of the UI envelope, or None."""
    node = understanding
    for key in ("overall", "primary", "kind"):
        node = node.get(key) if isinstance(node, dict) else None
    return node if isinstance(node, str) else None


_CQ_V2 = "marco-known-support-with-pending-set-v2"
_CQ_CAPTURE_SCHEMA = "marco-context-qualification-capture-v1"
_CQ_MAX_BYTES = 65536
_CQ_MAX_ANSWER_BYTES = 24576
_CQ_MAX_NODES = 8192
_CQ_MAX_DEPTH = 32
_CQ_MAX_INT_BITS = _CQ_MAX_BYTES * 4


class _CqInvalid(Exception):
    pass


def _cq_bound(value, depth, ancestors, count):
    """Bound nodes, depth, int size and string length with exact plain types (identity checks only),
    before any copy or serialization."""
    count[0] += 1
    if count[0] > _CQ_MAX_NODES or depth > _CQ_MAX_DEPTH:
        raise _CqInvalid()
    kind = type(value)
    if kind is str:
        if len(value) > _CQ_MAX_BYTES:
            raise _CqInvalid()
    elif kind is bool or value is None:
        return
    elif kind is int:
        if value.bit_length() > _CQ_MAX_INT_BITS:
            raise _CqInvalid()
    elif kind is float:
        if value != value or value == float("inf") or value == float("-inf"):
            raise _CqInvalid()
    elif kind is list or kind is dict:
        if id(value) in ancestors:
            raise _CqInvalid()
        inner = ancestors | {id(value)}
        if kind is list:
            for item in value:
                _cq_bound(item, depth + 1, inner, count)
        else:
            for key, item in value.items():
                if type(key) is not str:
                    raise _CqInvalid()
                _cq_bound(key, depth + 1, inner, count)
                _cq_bound(item, depth + 1, inner, count)
    else:
        raise _CqInvalid()


def _cq_canonical_digest(copied):
    """Streamed canonical digest equal to sha256 of the canonical json.dumps bytes, without allocating the
    full serialization; raises _CqInvalid once cumulative UTF-8 bytes would exceed _CQ_MAX_BYTES."""
    encoder = json.JSONEncoder(sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    digest = hashlib.sha256()
    total = 0
    for chunk in encoder.iterencode(copied):
        if type(chunk) is not str:
            raise _CqInvalid()
        remaining = _CQ_MAX_BYTES - total
        if len(chunk) > remaining:
            raise _CqInvalid()
        data = chunk.encode("utf-8")
        if len(data) > remaining:
            raise _CqInvalid()
        total += len(data)
        digest.update(data)
    return digest.hexdigest()


def _cq_pick_field(data, name):
    """Callback-free bounded exact-str field pick from an exact external dict: (found, value).

    Never performs a hash lookup (no data[key] / data.get, which may invoke a stored non-plain
    key's __eq__). Iterates built-in dict.items, compares only exact str keys to the own literal
    field name and uses the yielded value directly. Non-plain or other keys are skipped; an
    oversized or unreadable dict is reported as not found."""
    if type(data) is not dict or type(name) is not str:
        return (False, None)
    try:
        if len(data) > _CQ_MAX_NODES:
            return (False, None)
        visits = 0
        for item in dict.items(data):
            visits += 1
            if visits > _CQ_MAX_NODES:
                return (False, None)
            key = item[0]
            if type(key) is str and key == name:
                return (True, item[1])
    except Exception:
        return (False, None)
    return (False, None)


def _capture_context_qualification(source):
    """The capture artifact of a recognized v2 qualification in a Context return, else None (add nothing).

    Only hashes and the qualification metadata are kept, never the answer text."""
    if type(source) is not dict:
        return None
    found, qualification = _cq_pick_field(source, "qualification")
    if not found or type(qualification) is not dict:
        return None
    found, schema = _cq_pick_field(qualification, "schema")
    if not found or type(schema) is not str or schema != _CQ_V2:
        return None

    def unavailable(reason):
        return {"schema": _CQ_CAPTURE_SCHEMA, "basis": "context_return_copy", "status": "unavailable",
                "reason": reason}
    try:
        found, answer = _cq_pick_field(source, "answer")
        if not found or type(answer) is not str or len(answer) > _CQ_MAX_ANSWER_BYTES:
            return unavailable("invalid_answer")
        answer_bytes = answer.encode("utf-8")
        if len(answer_bytes) > _CQ_MAX_ANSWER_BYTES:
            return unavailable("invalid_answer")
    except Exception:
        return unavailable("invalid_answer")
    try:
        _cq_bound(qualification, 0, frozenset(), [0])
        copied = rt.plain_json(qualification, "context_qualification")
        qualification_sha256 = _cq_canonical_digest(copied)
    except Exception:
        return unavailable("invalid_qualification")
    return {"schema": _CQ_CAPTURE_SCHEMA, "basis": "context_return_copy", "status": "captured",
            "qualification": copied, "qualification_sha256": qualification_sha256,
            "qualified_answer_sha256": hashlib.sha256(answer_bytes).hexdigest()}


def view(envelope, context_result=None, error=None, meaning=None):
    """The fields of a turn the adapter reads, from either envelope shape.

    ``meaning``: the meaning a UI hold was said from (``AppState._said``), used
    when there is no ``context_result``.
    """
    env = envelope if isinstance(envelope, dict) else {}
    context = context_result if isinstance(context_result, dict) else None
    if context is None and isinstance(meaning, dict):
        context = {"meaning": meaning}
    if "phase" in env or isinstance(env.get("answer"), dict):
        answer = env.get("answer") if isinstance(env.get("answer"), dict) else {}
        trace = answer.get("trace") if isinstance(answer.get("trace"), dict) else {}
        reasoning = answer.get("reasoning") or trace.get("reasoning") or {}
        verification = answer.get("verification") or trace.get("verification") or {}
        text = answer.get("answer") if isinstance(answer.get("answer"), str) else env.get("web_answer")
        out = {"shape": "ui", "phase": env.get("phase"), "verdict": trace.get("verdict"),
               "known": answer.get("known"), "mode": trace.get("mode"), "winner": trace.get("winner"),
               "operator": reasoning.get("operator") if isinstance(reasoning, dict) else None,
               "transitions": (reasoning.get("transitions") if isinstance(reasoning, dict) else None) or [],
               "verification": verification if isinstance(verification, dict) else {},
               "text": text if isinstance(text, str) else "",
               "retrieval": trace.get("retrieval") if isinstance(trace.get("retrieval"), dict) else {},
               "sources": trace.get("sources") if isinstance(trace.get("sources"), list) else [],
               "rankings": trace.get("rankings") if isinstance(trace.get("rankings"), list) else [],
               "route": trace.get("route") if isinstance(trace.get("route"), dict) else {},
               "semantic_model": (answer.get("semantic_parse") or trace.get("semantic_parse") or {}).get("model")
               if isinstance(answer.get("semantic_parse") or trace.get("semantic_parse"), dict) else None,
               "request": _request_kind(env.get("understanding")),
               "meaning": (context or {}).get("meaning") if isinstance((context or {}).get("meaning"), dict) else None}
    else:
        status = env.get("status")
        out = {"shape": "context", "phase": "answer" if env else None, "verdict": STATUS_VERDICT.get(status),
               "known": (status == "answered") if status else None, "mode": "situation",
               "winner": env.get("operator"), "operator": env.get("operator"),
               "transitions": env.get("transitions") or [], "verification": env.get("verification") or {},
               "text": env.get("answer") if isinstance(env.get("answer"), str) else "",
               "retrieval": {}, "sources": [], "rankings": [], "route": {}, "semantic_model": None,
               "request": None,
               "meaning": env.get("meaning") if isinstance(env.get("meaning"), dict) else None}
    capture = _capture_context_qualification(
        env if out["shape"] == "context" else context_result if isinstance(context_result, dict) else None)
    if capture is not None:
        out["context_qualification_capture"] = capture
    out["error"] = error
    out["transitions"] = [row for row in out["transitions"] if isinstance(row, dict)]
    raw_checks = out["verification"].get("checks")
    raw_checks = [] if raw_checks is None else rt.plain_json(raw_checks, "checks")
    if not isinstance(raw_checks, list) or any(not isinstance(row, dict) for row in raw_checks):
        raise rt.TraceContractError("checks must be a plain JSON list of objects")
    out["checks"] = raw_checks
    return out


def gate_status(v):
    """``bench.dialogue_gate.status`` on the same envelope, from the declared verdict tables."""
    if v["error"] is not None:
        return "error"
    if v["phase"] != "answer":
        return "held"          # research or plan: no local answer was given
    if v["verdict"] in GATE_OBSERVED:
        return "observed"
    if v["verdict"] in GATE_HELD:
        return "held"
    if v["verdict"] in GATE_CHAT:
        return "chat"
    if v["known"] is True:
        return "answered"
    if v["known"] is False:
        return "held"
    return "unknown"


def _acts(report):
    if not isinstance(report, dict):
        return []
    acts = report.get("acts") or (report.get("trace") or {}).get("intent") or []
    return [str(a) for a in acts]


def output_status(v, gate):
    """``refused`` only when the meaning's act is ``refuse`` (a missing premise, declined).
    The realizer's REFUSE intent is not used: it says many kinds of hold."""
    if gate == "held":
        return "refused" if (v["meaning"] or {}).get("act") == "refuse" else "hold"
    return OUTPUT_OF_GATE[gate]


def hold_reason(v, report=None):
    """``(reason, where it came from)``: the meaning first, then the meaning the realizer said the
    reply from (request W4-2), then what the envelope says."""
    meaning = v["meaning"] or {}
    if meaning.get("reason"):
        return str(meaning["reason"]), "meaning"
    said_from = (report or {}).get("meaning")
    if isinstance(said_from, dict) and said_from.get("reason"):
        return str(said_from["reason"]), "realizer"
    if v["retrieval"].get("diagnosis"):
        return str(v["retrieval"]["diagnosis"]), "retrieval"
    failed = [c.get("reason") for c in v["checks"] if not c.get("ok") and c.get("reason")]
    if failed:
        return str(failed[0]), "verification"
    if v["phase"] not in (None, "answer"):
        return str(v["phase"]), "phase"
    if v["verdict"]:
        return str(v["verdict"]), "verdict"
    return "unknown", "none"


def _missing(v, session):
    meaning = v["meaning"] or {}
    out = {key: meaning[key] for key in MISSING_KEYS if meaning.get(key) not in (None, "", [], {})}
    if isinstance(meaning.get("said"), str) and meaning["said"].strip():
        # The statement the hold is about (an unread event, an unknown word's sentence), by reference.
        said = sha(meaning["said"])
        out["said"] = session.digests.get(said) or said
    need = v["retrieval"].get("need")
    if isinstance(need, dict) and need:
        out["need"] = {k: _scalar(need[k]) for k in ("kind", "topic", "resolved") if k in need}
    return out


# ---------------------------------------------------------------------------
# per-conversation adapter state, kept on the ledger and rebuilt from it
# ---------------------------------------------------------------------------
class Session:
    """What the ledger already holds for one conversation."""

    def __init__(self, conversation):
        self.conversation = conversation
        self.turns = 0
        self.observations = 0            # observation count the engine last reported
        self.obs = {}                    # observation index -> {"event", "input"}
        self.digests = {}                # sha256 of a statement's text -> event id
        self.rows = {}                   # transition key -> [{"event", "value"}] oldest first
        self.corrections = {}            # (index, before sha, after sha) -> event id

    @classmethod
    def rebuild(cls, ledger, conversation):
        """The session state from the ledger's own events (the ledger is the record)."""
        session, traces = cls(conversation), set()
        for event in ledger.events:
            payload = event["payload"]
            if event["kind"] == "input_received":
                if payload.get("conversation") != conversation:
                    continue
                traces.add(event["trace_id"])
                session.turns = max(session.turns, payload.get("turn") or 0)
                session.digests[payload["sha256"]] = event["event_id"]
                continue
            if event["trace_id"] not in traces:
                continue
            if event["kind"] == "observation_created":
                session.obs[payload["index"]] = {"event": event["event_id"], "input": event["parent_ids"][0]}
                session.observations = max(session.observations, payload["index"] + 1)
            elif event["kind"] == "state_changed" and payload.get("field") == "observation":
                index = payload.get("index")
                previous = session.obs.get(index, {})
                session.obs[index] = {"event": event["event_id"], "input": previous.get("input")}
                session.digests[payload["after"]["sha256"]] = event["event_id"]
                session.corrections[(index, payload["before"]["sha256"], payload["after"]["sha256"])] = \
                    event["event_id"]
            elif event["kind"] == "state_changed" and payload.get("row"):
                session.rows.setdefault(tuple(payload["row"]), []).append(
                    {"event": event["event_id"], "value": [payload["before"], payload["after"]],
                     "cause": payload.get("cause")})
        return session


def session_for(ledger, conversation):
    if conversation not in ledger.sessions:
        ledger.sessions[conversation] = Session.rebuild(ledger, conversation)
    return ledger.sessions[conversation]


def _row_key(row, occurrence):
    evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
    turn = evidence.get("turn") if isinstance(evidence.get("turn"), int) else None
    return (str(row.get("operation")), str(row.get("subject")), str(row.get("predicate")), turn, occurrence)


def _repair(evidence):
    repair = ((evidence.get("normalization") or {}).get("repair")) if isinstance(evidence, dict) else None
    if not isinstance(repair, dict):
        return None
    # The repair's rule is a pack sentence and its reading is derived text: by index only (§18).
    return {"status": repair.get("status"), "cost": repair.get("cost"), "bound": repair.get("bound"),
            "rule_index": repair.get("rule_index"), "operations": len(repair.get("operations") or [])}


# ---------------------------------------------------------------------------
# the adapter
# ---------------------------------------------------------------------------
def record_turn(ledger, trace_id, text, envelope, realizer_report, *, conversation="default", turn=None,
                context_result=None, meaning=None, label=None, act=None, restart=False, pack=None,
                pack_file=None, error=None, gap=None, runtime_stamp=None, provenance=None,
                prewritten_input=None, pending_flush=None, attempt_id=None, stage=None):
    """Write one turn's events to ``ledger`` under ``trace_id``. Returns a summary dict.

    ``conversation`` keys the adapter state (which statements and state changes
    the ledger already holds). ``context_result``: the ``ReasoningContext.turn``
    result behind a UI envelope; ``meaning``: the meaning a UI hold was said
    from, when there is no context result. ``label``/``act``: the dataset's
    expectation for the turn, when there is one (stats use the gate's
    denominators). ``pack``: the language pack path (else read from the
    envelope's verification sources). ``pack_file``: the ``.kgpack`` file, for
    its digest. ``error``: the exception the turn raised; ``envelope`` is then None. ``gap``: the gap class
    the engine gave its own hold of the turn (request G5-1); else the declared class of the hold's reason.

    Trace contract (optional metadata from a trusted caller; missing metadata is explicit on every call):
    ``runtime_stamp``: the actual selected model/encoder/realizer data; ``provenance``: what the answer used
    (``rt.SECTIONS``), kept exactly; neither is read from the host, a name not supplied is listed as missing.
    ``prewritten_input``: the id of an ``input_received`` event the runtime wrote before executing; it is reused
    (kind, trace, conversation, text and ``attempt_id`` are checked), never written twice. ``pending_flush``:
    ``f(ledger, input_event_id, trace_id)`` called after the input exists and before any output; it appends the
    engine's pending events and returns their ids, which become parents of the operator or error event.
    ``attempt_id``: this attempt's identity (independent of ``turn``); ``stage``: where an ``error`` happened.
    A check result is a parent of the output; the output is never ``verified``: ``world_truth_status`` is
    ``unverified`` and ``verified`` means the declared criterion held, nothing more.
    """
    v = view(envelope, context_result, error, meaning)
    session = session_for(ledger, conversation)
    meaning = v["meaning"] or {}
    report = realizer_report if isinstance(realizer_report, dict) else None
    sources = v["verification"].get("sources") or []
    pack = pack or next((s for s in sources if isinstance(s, str) and s.startswith("styles/")), None)
    contract = rt.contract_provenance(runtime_stamp, provenance, pack=pack, has_checks=bool(v["checks"]))
    # Preflight plain-JSON metadata before anything is appended, so bad checks cannot leave a partial record.
    rt.plain_json(v["checks"], "checks")
    rt.plain_json(v["verification"].get("replay_scope"), "replay_scope")
    source_model_digest = rt.plain_json(v["verification"].get("model"), "source_model_digest")
    stamp, prior = contract["base"], None
    if attempt_id is not None and (not isinstance(attempt_id, str) or not attempt_id):
        raise rt.TraceContractError("attempt_id must be a non-empty string")
    if prewritten_input is not None:
        prior = _prewritten(ledger, prewritten_input, trace_id, text, conversation, attempt_id)
        attempt_id = prior["payload"]["attempt_id"]
        if turn is not None and prior["payload"].get("turn") != turn:
            raise rt.TraceContractError("prewritten_input turn does not match this attempt")
        if prior["runtime"].get("selected") != contract["first"]["selected"] \
                or prior["runtime"].get("declared_runtime") != contract["first"]["declared_runtime"]:
            raise rt.TraceContractError("prewritten_input selected runtime does not match this attempt")
    attempt_id = attempt_id or "attempt_" + uuid.uuid4().hex
    if prior is None and any(e["kind"] == "input_received" and e["payload"].get("attempt_id") == attempt_id
                             for e in ledger.events):
        raise rt.TraceContractError("attempt_id already has an input; use prewritten_input")
    session.turns = turn if turn is not None else session.turns + 1
    cx = {"attempt_id": attempt_id, "provenance_status": contract["status"],
          "provenance_missing": list(contract["missing"])}
    gate = gate_status(v)
    written = []

    def emit(kind, **fields):
        fields.setdefault("runtime", stamp)
        fields["payload"] = {**(fields.get("payload") or {}), "attempt_id": attempt_id}
        event = ledger.append(kind, trace_id, **fields)
        written.append(event["event_id"])
        return event["event_id"]

    # 1. the input -------------------------------------------------------------------
    first = contract["first"]
    first["source_model_digest"] = source_model_digest
    if pack_file is not None:
        first["pack_digest"] = rt.pack_digest(pack_file)
    said = {"text": text, "sha256": sha(text), "conversation": conversation, "turn": session.turns}
    for key, value in (("label", label), ("act", act)):
        if value is not None:
            said[key] = value
    if restart:
        said["restart"] = True
    if prior is not None:
        inp = prior["event_id"]
        written.append(inp)
    else:
        said["attempt_id"] = attempt_id
        said["installed_memory_head"] = contract["declared"].get("installed_memory_head")
        inp = emit("input_received", subsystem="dialogue", epistemic_status="reported", runtime=first,
                   source={"type": "dialogue_turn", "conversation": conversation, "turn": session.turns},
                   payload=said)
    session.digests[said["sha256"]] = inp
    summary = {"trace_id": trace_id, "input": inp, "gate_status": gate, "new_state": 0, "withdrawn": 0,
               "events": written}
    pending = _flush(ledger, pending_flush, inp, trace_id) if pending_flush is not None else []
    summary["attempt_id"] = attempt_id
    summary["pending"] = pending
    base = [inp] + pending

    if v["error"] is not None:
        checked = None
        passed = bool(v["checks"]) and all(c.get("ok") is True for c in v["checks"])
        if v["checks"]:
            criteria_known = not any(name.startswith("provenance.criterion") for name in contract["missing"])
            checked = emit("hypothesis_verified" if passed else "hypothesis_rejected", parent_ids=base,
                status="success" if passed else "failed", subsystem="verification",
                epistemic_status="verified" if passed and criteria_known else "inferred" if passed else "unknown",
                payload={**cx, "checks": rt.plain_json(v["checks"], "checks"),
                         "criterion": contract["declared"].get("criterion"),
                         "assumptions": contract["declared"].get("assumptions"),
                         "criterion_declared": criteria_known, "world_truth_status": "unverified",
                         "verified_scope": "declared_criterion_only" if criteria_known else "unspecified"})
        problem = {"problem": "execution_error", "type": type(v["error"]).__name__,
                   "message": str(v["error"])[:200]}
        if stage is not None:
            problem["stage"] = str(stage)
        err = emit("error", parent_ids=_unique(base + [checked]), status="error", epistemic_status="observed", subsystem="dialogue",
                   payload={**problem, **cx})
        v["text"] = ""     # execution may have calculated an answer before a save/trace failure; it was not delivered
        # The computed answer was never delivered: neither report text nor its realized flag is logged.
        summary["output"] = _output(emit, v, None, "error", gate, [err], session, conversation, None,
                                    _extra(cx, contract, checked, passed))
        summary["status"] = "error"
        return summary

    # 2. statements the engine stored ----------------------------------------------------
    counts = [c["observation_turns"] for c in v["checks"] if isinstance(c.get("observation_turns"), int)]
    new_obs = []
    if counts and max(counts) > session.observations:
        for index in range(session.observations, max(counts)):
            event = emit("observation_created", parent_ids=[inp], subsystem="state", epistemic_status="reported",
                         subject="observation:%d" % index,
                         payload={"index": index, "sha256": said["sha256"]})
            session.obs[index] = {"event": event, "input": inp}
            new_obs.append(event)
        session.observations = max(counts)

    def statement(index):
        return (session.obs.get(index) or {}).get("event") if isinstance(index, int) else None

    # 3. the operator ------------------------------------------------------------------
    refs = []
    for row in v["transitions"]:
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        refs.append(statement(evidence.get("turn")))
    cited = [x for c in v["checks"] for x in (c.get("evidence") or []) if isinstance(x, str)]
    cited += [x for x in (meaning.get("evidence") or []) if isinstance(x, str)]
    refs += [session.digests.get(sha(x)) for x in cited]
    refs = _unique(refs)
    if v["operator"]:
        operation = {"type": "operator", "id": str(v["operator"])}
        if meaning.get("rules"):
            operation["rules"] = [str(r) for r in meaning["rules"]]
        op = emit("rule_applied", parent_ids=base, input_refs=refs, subsystem="reasoning",
                  epistemic_status="inferred", operation=operation,
                  payload={"operator": str(v["operator"]), "mode": v["mode"], "verdict": v["verdict"],
                           "transitions": len(v["transitions"]), "statements": len(refs)})
    else:
        ranked = v["route"].get("candidates") if isinstance(v["route"].get("candidates"), list) else v["rankings"]
        candidates = [[_scalar(r[0]), _scalar(r[1])] for r in ranked[:5]
                      if isinstance(r, (list, tuple)) and len(r) >= 2]
        op = emit("routing_selected", parent_ids=base, input_refs=refs, subsystem="routing",
                  epistemic_status="inferred",
                  payload={"selected": _scalar(v["winner"]) if v["winner"] is not None else v["mode"],
                           "mode": v["mode"], "verdict": v["verdict"], "phase": v["phase"],
                           "request": v["request"], "candidates": candidates})

    # 4. transitions -> state changes ---------------------------------------------------------
    touched, new_state, corrections, used_withdrawn = [], [], [], []
    last = {}                        # (subject, predicate) -> event of its latest row in this replay
    occurrences = {}
    for row in v["transitions"]:
        operation = row.get("operation")
        if operation == "correction":
            index = row.get("index")
            key = (index, sha(row.get("before")), sha(row.get("after")))
            if key in session.corrections:
                if not ledger.is_withdrawn(session.corrections[key]):   # a later correction replaced it
                    touched.append(session.corrections[key])
                continue
            current = session.obs.get(index)
            payload = {"field": "observation", "index": index, "before": {"sha256": key[1]},
                       "after": {"sha256": key[2]}, "cause": inp, "attempt_id": attempt_id}
            fields = dict(parent_ids=_unique([op, (current or {}).get("input")]), subsystem="state",
                          epistemic_status="reported", subject="observation:%s" % index,
                          operation={"type": "correction"}, payload=payload, runtime=stamp)
            if current:
                new, gone = ledger.correct(current["event"], "state_changed", trace_id, reason="corrected",
                                           **fields)
                written += [new["event_id"], gone["event_id"]]
                summary["withdrawn"] += 1
                event = new["event_id"]
            else:
                event = emit("state_changed", **fields)
            session.obs[index] = {"event": event, "input": (current or {}).get("input") or inp}
            session.digests[key[2]] = event
            session.corrections[key] = event
            corrections.append(event)
            new_state.append(event)
            continue
        if operation not in STATE_OPERATIONS:
            continue
        prefix = (operation, str(row.get("subject")), str(row.get("predicate")),
                  (row.get("evidence") or {}).get("turn") if isinstance(row.get("evidence"), dict) else None)
        occurrences[prefix] = occurrences.get(prefix, -1) + 1
        key = _row_key(row, occurrences[prefix])
        value = [_scalar(row.get("before")), _scalar(row.get("after"))]
        versions = session.rows.setdefault(key, [])
        current = next((x for x in reversed(versions) if not ledger.is_withdrawn(x["event"])), None)
        pair = (key[1], key[2])
        cause = statement(key[3])
        # The same change read from a corrected statement: its cause is the revision now, not the
        # withdrawn reading (a corrected receiver leaves the giver's change as it was).
        recaused = current is not None and cause is not None and current.get("cause") not in (None, cause)
        if current is not None and current["value"] == value and not recaused:
            touched.append(current["event"])
            last[pair] = current["event"]
            continue
        stale = None if corrections or recaused else \
            next((x for x in reversed(versions) if x["value"] == value), None)
        if stale is not None:
            # The envelope rests on a version the ledger already withdrew (on a correction
            # turn the same values are a new change: a second correction may restore them).
            touched.append(stale["event"])
            used_withdrawn.append(stale["event"])
            last[pair] = stale["event"]
            continue
        evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
        payload = {"attempt_id": attempt_id, "field": key[2], "before": value[0], "after": value[1], "cause": cause or inp,
                   "row": list(key), "observation": key[3]}
        if row.get("delta") is not None:
            payload["delta"] = _scalar(row["delta"])
        if cause is None:
            payload["cause_unmapped"] = True
        repair = _repair(evidence)
        if repair:
            payload["repair"] = repair
        span = [evidence.get("start"), evidence.get("end")] if "start" in evidence else None
        fields = dict(parent_ids=_unique([op, cause, last.get(pair)]), subsystem="state",
                      epistemic_status="reported" if operation == "state_update" else "inferred",
                      subject=key[1], operation={"type": operation},
                      source={"observation": key[3], "span": span} if span else {},
                      payload=payload, runtime=stamp)
        if current is not None:
            new, gone = ledger.correct(current["event"], "state_changed", trace_id,
                                       reason="recomputed_after_correction" if corrections else "recomputed",
                                       **fields)
            written += [new["event_id"], gone["event_id"]]
            summary["withdrawn"] += 1
            event = new["event_id"]
        else:
            event = emit("state_changed", **fields)
        versions.append({"event": event, "value": value, "cause": payload["cause"]})
        new_state.append(event)
        last[pair] = event
    if corrections:
        # A correction replays the whole conversation: a change it no longer makes is withdrawn.
        # When the engine names the states the correction changed (``affected_state``), its rows
        # are those states' only: a change to any other state still stands and is not withdrawn.
        scopes = [c["affected_state"] for c in v["checks"] if isinstance(c.get("affected_state"), list)]
        affected = {tuple(str(x) for x in k[:2]) for scope in scopes for k in scope
                    if isinstance(k, (list, tuple)) and len(k) >= 2}
        seen = set(touched) | set(new_state)
        for key, versions in session.rows.items():
            if scopes and (key[1], key[2]) not in affected:
                continue
            current = next((x for x in reversed(versions) if not ledger.is_withdrawn(x["event"])), None)
            if current is not None and current["event"] not in seen:
                gone = ledger.withdraw(current["event"], trace_id, parent_ids=corrections,
                                       reason="not_in_replay_after_correction", runtime=stamp,
                                       payload={"attempt_id": attempt_id})
                written.append(gone["event_id"])
                summary["withdrawn"] += 1
    summary["new_state"] = len(new_state)

    # 5. cited sources -------------------------------------------------------------------
    evidence_events = []
    for item in v["sources"][:SOURCES_KEPT]:
        if not isinstance(item, dict):
            continue
        ref = item.get("source") or item.get("node")
        if not ref:
            continue
        payload = {"ref": _scalar(ref)}
        if item.get("text"):
            payload["sha256"] = sha(item["text"])
        evidence_events.append(emit("evidence_found", parent_ids=[op], subsystem="reasoning",
                                    epistemic_status="reported", subject=_scalar(item.get("node")),
                                    payload=payload))

    # 6. conclusions ----------------------------------------------------------------------
    conclusions = []
    if gate == "answered":
        by_fact = {}
        for row in v["transitions"]:
            fact = row.get("fact")
            if not isinstance(fact, (list, tuple)) or len(fact) < 3:
                continue
            fact = [str(x) for x in fact[:3]]
            evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
            parents = [op, last.get((fact[0], fact[1])), statement(evidence.get("turn"))]
            parents += [by_fact.get(tuple(str(x) for x in p)) for p in row.get("parents") or []
                        if isinstance(p, (list, tuple))]
            event = emit("conclusion_created", parent_ids=_unique(parents), subsystem="reasoning",
                         epistemic_status="inferred", subject=fact[0],
                         payload={"fact": fact, "observation": evidence.get("turn")})
            by_fact[tuple(fact)] = event
            conclusions.append(event)
        if not conclusions:
            kind = meaning.get("kind") if meaning.get("act") == "explain" else None
            payload = {"kind": "explanation" if meaning.get("act") == "explain" else "answer"}
            if kind:
                payload["explains"] = str(kind)
            parents = _unique([op] + touched + new_state + evidence_events)
            conclusions.append(emit("conclusion_created", parent_ids=parents, subsystem="reasoning",
                                    epistemic_status="inferred", payload=payload))

    # 7. verification ----------------------------------------------------------------------
    verification = None
    if v["checks"]:
        failed = [c for c in v["checks"] if c.get("ok") is not True]
        payload = {"checks": rt.plain_json(v["checks"], "checks"),
                   "replay_scope": rt.plain_json(v["verification"].get("replay_scope"), "replay_scope")}
        declared = contract["declared"]
        criterion_declared = not any(name.startswith("provenance.criterion") for name in contract["missing"])
        payload.update(cx, criterion=declared.get("criterion"), assumptions=declared.get("assumptions"),
                       criterion_declared=criterion_declared, world_truth_status="unverified",
                       verified_scope="declared_criterion_only" if criterion_declared else "unspecified")
        parents = conclusions or new_state or new_obs or [op]
        if not failed:
            verification = emit("hypothesis_verified", parent_ids=parents, subsystem="verification",
                                epistemic_status="verified" if criterion_declared else "inferred", payload=payload)
        elif any(c.get("reason") in CONTRADICTION_CHECKS for c in failed) or \
                meaning.get("reason") in CONTRADICTION_REASONS:
            verification = emit("contradiction_found", parent_ids=parents, status="failed",
                                subsystem="verification", epistemic_status="contradicted", payload=payload)
        else:
            verification = emit("hypothesis_rejected", parent_ids=parents, status="failed",
                                subsystem="verification", epistemic_status="unknown", payload=payload)
    verified = bool(verification) and ledger.get(verification)["kind"] == "hypothesis_verified"

    # 8. hold ------------------------------------------------------------------------------
    status = output_status(v, gate)
    hold = None
    if gate == "held":
        reason, where = hold_reason(v, report)
        payload = {"reason": reason, "reason_source": where, "verdict": v["verdict"], "phase": v["phase"],
                   "act": meaning.get("act"), "missing": _missing(v, session)}
        gap = _gap(reason, gap)
        if gap is not None:
            payload["gap"] = gap        # the gap class of the hold (request G5-1, the adaptive note's taxonomy)
        payload.update(cx)
        parents = _unique([op, verification])    # a passed check before a local hold is still a cause
        subject = meaning.get("subject") if isinstance(meaning.get("subject"), str) else None
        hold = emit("hold", parent_ids=parents, status=status, subsystem="dialogue", epistemic_status="unknown",
                    subject=subject, payload=payload)
        summary["reason"] = reason

    # 9. output -----------------------------------------------------------------------------
    if status == "answered":
        parents = conclusions
    elif hold is not None:
        parents = [hold]
    elif status == "recorded":
        parents = new_state or new_obs or ([verification] if verification else []) or [op]
    else:
        parents = [op]
    parents = _unique(parents + [op, verification])    # every status keeps operator/routing (and pending) ancestry
    summary["output"] = _output(emit, v, report, status, gate, parents, session, conversation, None,
                                _extra(cx, contract, verification, verified,
                                       v.get("context_qualification_capture")))
    summary["status"] = status
    summary["used_withdrawn"] = len(used_withdrawn)
    return summary


def _gap(reason, given=None):
    """The gap class of a held turn (request G5-1): the one the engine gave its own hold of the turn
    (``given``, the recorder passes it), else the class ``reasoning_context.gap_class`` declares for the
    reason; None when neither is known (the adapter runs without the engine too)."""
    if given:
        return given
    try:
        from marco.reasoning.context import gap_class
    except ImportError:
        return None
    gap, declared = gap_class(reason)
    return gap if declared else None


def _prewritten(ledger, event_id, trace_id, text, conversation, attempt_id):
    """The input event the runtime wrote before executing, when it matches this turn; else an error."""
    event = ledger.get(event_id) if isinstance(event_id, str) else None
    if event is None or event["kind"] != "input_received":
        raise rt.TraceContractError("prewritten_input %r is not an input_received event of this ledger" % (event_id,))
    payload = event["payload"]
    for name, ok in (("trace_id", event["trace_id"] == trace_id), ("conversation", payload.get("conversation") == conversation),
                     ("text", payload.get("text") == text and payload.get("sha256") == sha(text)),
                     ("attempt_id", isinstance(payload.get("attempt_id"), str) and bool(payload["attempt_id"])
                      and attempt_id in (None, payload.get("attempt_id")))):
        if not ok:
            raise rt.TraceContractError("prewritten_input %s does not match this turn" % name)
    if ledger.is_withdrawn(event_id) or any(
            (e["kind"] == "output_created" or e["kind"] == "error" and e["payload"].get("terminal") is True)
            and e["payload"].get("attempt_id") == payload["attempt_id"] for e in ledger.events):
        raise rt.TraceContractError("attempt %s already has its output" % payload["attempt_id"])
    return event


def _flush(ledger, callback, input_id, trace_id):
    """Flush pending events before output; each returned event must rest on this input in this ledger.

    Existing context flushers allocate their own trace IDs, so ancestry (not equal trace IDs) binds them.
    """
    ids = callback(ledger, input_id, trace_id)
    ids = [] if ids is None else ids
    if not isinstance(ids, (list, tuple)) or any(not isinstance(ref, str) for ref in ids) or len(set(ids)) != len(ids):
        raise rt.TraceContractError("pending_flush must return a list of distinct event ids")
    start = ledger.position(input_id)
    for ref in ids:
        event = ledger.get(ref) if isinstance(ref, str) else None
        if event is None or ledger.position(ref) <= start or event["kind"] in {"input_received", "output_created"}:
            raise rt.TraceContractError("pending event %r is not a pending event after the input" % (ref,))
        todo, seen = list(event["parent_ids"]), set()
        while todo:
            parent = todo.pop()
            if parent in seen:
                continue
            seen.add(parent)
            todo.extend((ledger.get(parent) or {}).get("parent_ids", []))
        if input_id not in seen:
            raise rt.TraceContractError("pending event %r does not rest on this input" % (ref,))
    return list(ids)


def _extra(cx, contract, verification, verified, capture=None):
    """Output payload fields of the trace contract: identity, provenance, and what verification does not mean."""
    extra = {**cx, "world_truth_status": "unverified", "provenance": contract["declared"],
             "criterion_result": None if verification is None else ("passed" if verified else "failed"),
             "check_event": verification, "provenance_basis": "caller_reported_usage"}
    if capture is not None:
        extra["context_qualification"] = capture
    return extra


def _output(emit, v, report, status, gate, parents, session, conversation, epistemic, extra=None):
    text = report.get("text") if report and isinstance(report.get("text"), str) else v["text"]
    payload = {"text": text or "", "sha256": sha(text or ""), "realized": bool(report and report.get("realized")),
               "status": status, "gate_status": gate, "turn": session.turns, "conversation": conversation,
               "acts": _acts(report)}
    if report is None:
        payload["realizer"] = "not_called"
    elif not report.get("realized"):
        payload["realizer"] = report.get("reason") or ("held" if report.get("held") else "passthrough")
    if report and report.get("language"):
        payload["language"] = report["language"]
    if report and isinstance(report.get("meaning"), dict):
        # What the reply was said from (request W4-2): the meaning's act and reason, ids only, and
        # for a composed reply the match of the turn plan that said it.
        payload["meaning"] = {key: _scalar(report["meaning"].get(key)) for key in ("act", "reason")}
        if isinstance(report.get("plan"), dict):
            payload["plan"] = _plain(report["plan"])
    if v["text"] and text != v["text"]:
        payload["reply_sha256"] = sha(v["text"])     # the UI changed the realized text (affect, format)
    if epistemic is None:
        epistemic = {"answered": "inferred", "recorded": "reported"}.get(status, "unknown")
    payload.update(extra or {})
    captured = payload.get("context_qualification")
    if isinstance(captured, dict) and captured.get("status") == "captured":
        # qualified_answer_sha256 is raw UTF-8, whereas payload["sha256"] is normalized (sha() strips).
        # Compare on the same raw basis against the actual output text selected by _output; the
        # comparator is transient and the displayed hash is not persisted again. A mismatch is truthful.
        _raw_display_sha256 = hashlib.sha256(str.encode(payload["text"], "utf-8")).hexdigest()
        payload["context_qualification"] = {
            **captured,
            "display_match_basis": "raw_utf8_output_text",
            "matches_display": captured.get("qualified_answer_sha256") == _raw_display_sha256,
        }
    return emit("output_created", parent_ids=parents, status=status, subsystem="dialogue",
                epistemic_status=epistemic, payload=payload)
