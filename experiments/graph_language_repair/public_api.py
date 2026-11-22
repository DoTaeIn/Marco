# -*- coding: utf-8 -*-
"""Public integration entry for the graph language repair experiment.

``answer(reading, question)`` takes a reading that was ALREADY extracted by
``core.read_text`` and one natural-language question, runs the existing
public pipeline (``questions.compile.compile_question`` ->
``questions.select.execute_plan`` -> ``questions.respond.render``) over that
same reading, and returns one detached, JSON-finite record.  The document is
never re-read here; an oracle arm and a natural arm can therefore share one
reading and one set of facts.

What this module does, and all it does:

* transport: call the three existing functions, record every search hop the
  selector issues through the existing ``core.search_rows`` (completeness and
  the engine's own reason are kept, never hidden);
* provenance: resolve the selector's ``source_refs`` back to the reading's own
  rows by id, keep each row's own spans paired with its own claim, and follow
  the row's declared ``proof`` / ``depends_on`` / ``hypotheses`` links to the
  records the reading already holds -- no fact is invented and no span is
  attributed to a claim it was not stated in;
* status: look up the selector's gate, the recorded search completeness and
  the reading's own contradiction / competing-reading records in the
  declarative policy ``graphs/interface/status-policy.json`` (the one graph
  file this module owns) to produce ``status`` and ``abstained``;
* serialisation: convert Python sets, tuples and non-finite floats into
  JSON-finite values deterministically, preserving every key.

It makes no semantic decision: it does not pick between candidates, does not
re-rank, does not add wording, and does not override a gate.  Standard
library only, plus the experiment's own public modules.
"""
import json
import os

from experiments.graph_language_repair.core import READING_SCHEMA
from experiments.graph_language_repair.core import read_text as _core_read_text
from experiments.graph_language_repair.core import search_rows as _core_search_rows
from experiments.graph_language_repair.questions.compile import compile_question as _compile_question
from experiments.graph_language_repair.questions.respond import render as _render
from experiments.graph_language_repair.questions.select import execute_plan as _execute_plan

API_SCHEMA = "graph-language-repair-public-api-v1"
STATUS_POLICY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "graphs", "interface", "status-policy.json")

_MAX_DEPTH = 64


# --------------------------------------------------------------------------
# JSON-finite conversion
# --------------------------------------------------------------------------

def to_json_finite(value):
    """A detached, JSON-finite copy of ``value``.

    * ``dict`` / ``list`` / ``tuple`` are copied (tuples become lists);
      ``set`` / ``frozenset`` become lists sorted by their members' canonical
      JSON text, so the order is deterministic.
    * ``str`` (including subclasses, read through ``str.__str__``), ``bool``,
      ``int``, finite ``float`` and ``None`` pass through.  A non-finite float
      becomes ``{"__float__": "nan" | "inf" | "-inf"}``.
    * ``bytes`` become ``{"__bytes__": <hex>}``.
    * A dict whose converted keys are not all strings becomes
      ``{"__pairs__": [[key, value], ...]}`` so no key is lost.
    * Anything else is opaque: it becomes ``{"__opaque__": <type name>}``.
      Its ``__str__``/``__repr__``/custom methods are never called.
    * A container reached again on the current path becomes
      ``{"__cycle__": true}``; nesting past ``_MAX_DEPTH`` becomes
      ``{"__depth_exceeded__": true}``.

    Containers are iterated through the builtin type's own methods
    (``dict.items``, ``list.__iter__`` ...) so a subclass override is not
    executed.  Nothing in ``value`` is mutated.
    """
    return _finite(value, (), 0)


def _type_name(kind):
    module = getattr(kind, "__module__", None)
    name = getattr(kind, "__qualname__", None) or getattr(kind, "__name__", "?")
    return "%s.%s" % (module, name) if module else name


def _sort_key(item):
    return json.dumps(item, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"))


def _finite(value, active, depth):
    if value is None:
        return None
    kind = type(value)
    if kind is bool or kind is int:
        return value
    if isinstance(value, str):
        return str.__str__(value)
    if kind is float:
        if value != value:
            return {"__float__": "nan"}
        if value == float("inf"):
            return {"__float__": "inf"}
        if value == float("-inf"):
            return {"__float__": "-inf"}
        return value
    if kind is bytes:
        return {"__bytes__": bytes.hex(value)}
    if kind in (dict, list, tuple, set, frozenset):
        if depth >= _MAX_DEPTH:
            return {"__depth_exceeded__": True}
        ident = id(value)
        if ident in active:
            return {"__cycle__": True}
        inner = active + (ident,)
        if kind is dict:
            pairs = []
            plain = True
            for key, item in dict.items(value):
                converted_key = _finite(key, inner, depth + 1)
                if type(converted_key) is not str:
                    plain = False
                pairs.append((converted_key, _finite(item, inner, depth + 1)))
            if plain:
                return {key: item for key, item in pairs}
            return {"__pairs__": [[key, item] for key, item in pairs]}
        if kind is list:
            return [_finite(item, inner, depth + 1) for item in list.__iter__(value)]
        if kind is tuple:
            return [_finite(item, inner, depth + 1) for item in tuple.__iter__(value)]
        iterate = set.__iter__ if kind is set else frozenset.__iter__
        members = [_finite(item, inner, depth + 1) for item in iterate(value)]
        return sorted(members, key=_sort_key)
    return {"__opaque__": _type_name(kind)}


# --------------------------------------------------------------------------
# Policy
# --------------------------------------------------------------------------

def load_status_policy():
    """The declarative status policy (``graphs/interface/status-policy.json``)."""
    with open(STATUS_POLICY_PATH, "r", encoding="utf-8") as handle:
        return json.load(handle)


# --------------------------------------------------------------------------
# Search recording
# --------------------------------------------------------------------------

class _RecordingSearch(object):
    """Pass-through onto a ``search_rows`` callable that records every hop.

    The world is returned to the selector untouched.  Only a summary is kept:
    the query triple, whether the engine assembled a world, whether it
    reported it complete, and the engine's own reason.
    """

    def __init__(self, inner):
        self._inner = inner
        self.hops = []

    def __call__(self, reading, query_triple, *args, **kwargs):
        world = self._inner(reading, query_triple, *args, **kwargs)
        self.hops.append(_summarize_world(query_triple, world))
        return world


def _summarize_world(query_triple, world):
    entry = {"triple": to_json_finite(query_triple)}
    candidate = world[0] if isinstance(world, tuple) and world else world
    if not isinstance(candidate, dict):
        entry.update({"assembled": False, "complete": False,
                      "reason": "no_world:%s" % _type_name(type(candidate)),
                      "matches": 0, "facts": 0, "searches": None})
        return entry
    entry.update({"assembled": bool(candidate.get("assembled", True)),
                  "complete": candidate.get("complete") is True,
                  "reason": to_json_finite(candidate.get("reason")),
                  "matches": len(candidate.get("matches") or []),
                  "facts": len(candidate.get("facts") or []),
                  "searches": to_json_finite(candidate.get("searches")),
                  "projection": to_json_finite(candidate.get("projection"))})
    return entry


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------

def _span_record(text, span):
    """``{"start", "end", "quote"}`` for one ``[start, end)`` span over ``text``.

    ``quote`` is exactly ``text[start:end]`` (CONTRACT.md section 1).  A span
    that is not two ints inside the text is kept with ``quote: None`` and
    ``valid: False`` rather than dropped or repaired.
    """
    ok = (isinstance(span, (list, tuple)) and len(span) == 2
          and type(span[0]) is int and type(span[1]) is int
          and 0 <= span[0] <= span[1] <= len(text))
    if ok:
        return {"start": span[0], "end": span[1], "quote": text[span[0]:span[1]]}
    return {"start": to_json_finite(span[0]) if isinstance(span, (list, tuple)) and span else None,
            "end": to_json_finite(span[1]) if isinstance(span, (list, tuple)) and len(span) > 1 else None,
            "quote": None, "valid": False}


def _span_records(text, spans):
    return [_span_record(text, span) for span in (spans or [])]


def _overlaps(a, b):
    return (isinstance(a, (list, tuple)) and isinstance(b, (list, tuple))
            and len(a) == 2 and len(b) == 2
            and all(type(x) is int for x in (a[0], a[1], b[0], b[1]))
            and a[0] < b[1] and b[0] < a[1])


def _by_id(records):
    index = {}
    for record in records or ():
        if isinstance(record, dict) and isinstance(record.get("id"), str):
            index.setdefault(record["id"], record)
    return index


def _support_row_ids(candidate):
    """Row ids a selector candidate's ``source_refs`` cite, in order, deduplicated.

    The core's projection merges identical facts and lists every merged row
    under ``source_ref["rows"]``; the singular ``row`` is only the first of
    them (AUDITOR.md, source merge coordination).  Both are read.
    """
    found = []
    for ref in candidate.get("source_refs") or ():
        if not isinstance(ref, dict):
            continue
        ids = list(ref.get("rows") or ())
        if ref.get("row") is not None and ref["row"] not in ids:
            ids.insert(0, ref["row"])
        for row_id in ids:
            if row_id not in found:
                found.append(row_id)
    return found


def _row_subject_and_object(row):
    triple = row.get("triple")
    if isinstance(triple, (list, tuple)) and len(triple) == 3:
        return triple[0], triple[2]
    return None, None


def _evidence_record(text, row, role, via, answer_values):
    record = to_json_finite(row)
    record["spans"] = _span_records(text, row.get("spans"))
    record["value_span"] = (_span_record(text, row["value_span"])
                            if row.get("value_span") is not None else None)
    record["role"] = role
    record["via"] = via
    subject, obj = _row_subject_and_object(row)
    record["carries_answer"] = bool(answer_values) and (
        (obj is not None and obj in answer_values) or (subject is not None and subject in answer_values))
    return record


def _chain(reading, support_ids, answer_values):
    """Support rows plus every row/proof/hypothesis they declare they rest on.

    Breadth-first over ``row["proof"] -> proof["rows"]`` and
    ``row["depends_on"]``; ``row["hypotheses"]`` are collected as records.
    Each chained row says which row and which link brought it in (``via``).
    A cited id with no record in the reading is reported as missing, not
    invented.
    """
    text = reading["text"]
    rows_by_id = _by_id(reading.get("rows"))
    proofs_by_id = _by_id(reading.get("proofs"))
    hyps_by_id = _by_id(reading.get("hypotheses"))
    evidence, proofs, hypotheses, missing = [], [], [], []
    seen_rows, seen_proofs, seen_hyps = set(), set(), set()
    queue = [(row_id, "support", []) for row_id in support_ids]
    while queue:
        row_id, role, via = queue.pop(0)
        if row_id in seen_rows:
            continue
        seen_rows.add(row_id)
        row = rows_by_id.get(row_id)
        if row is None:
            missing.append({"kind": "row", "id": to_json_finite(row_id), "role": role, "via": via})
            continue
        evidence.append(_evidence_record(text, row, role, via, answer_values))
        proof_id = row.get("proof")
        if proof_id:
            proof = proofs_by_id.get(proof_id)
            if proof is None:
                missing.append({"kind": "proof", "id": to_json_finite(proof_id), "cited_by": row_id})
            else:
                if proof_id not in seen_proofs:
                    seen_proofs.add(proof_id)
                    proof_record = to_json_finite(proof)
                    proof_record["spans"] = _span_records(text, proof.get("spans"))
                    proof_record["cited_by"] = [row_id]
                    proofs.append(proof_record)
                else:
                    for proof_record in proofs:
                        if proof_record.get("id") == proof_id and row_id not in proof_record["cited_by"]:
                            proof_record["cited_by"].append(row_id)
                for proof_row in proof.get("rows") or ():
                    queue.append((proof_row, "chain",
                                  via + [{"from": row_id, "link": proof_id, "kind": "proof"}]))
        for dependency in row.get("depends_on") or ():
            queue.append((dependency, "chain",
                          via + [{"from": row_id, "link": dependency, "kind": "depends_on"}]))
        for hyp_id in row.get("hypotheses") or ():
            if hyp_id in seen_hyps:
                for hyp_record in hypotheses:
                    if hyp_record.get("id") == hyp_id and row_id not in hyp_record["cited_by"]:
                        hyp_record["cited_by"].append(row_id)
                continue
            seen_hyps.add(hyp_id)
            hyp = hyps_by_id.get(hyp_id)
            if hyp is None:
                missing.append({"kind": "hypothesis", "id": to_json_finite(hyp_id), "cited_by": row_id})
                continue
            hyp_record = to_json_finite(hyp)
            hyp_record["spans"] = _span_records(text, hyp.get("spans"))
            hyp_record["cited_by"] = [row_id]
            hypotheses.append(hyp_record)
    return evidence, proofs, hypotheses, missing


def _events_for(reading, evidence):
    text = reading["text"]
    events_by_id = _by_id(reading.get("events"))
    found, seen = [], set()
    for record in evidence:
        subject, _ = _row_subject_and_object(record)
        if subject in events_by_id and subject not in seen:
            seen.add(subject)
            event = to_json_finite(events_by_id[subject])
            event["span"] = (_span_record(text, events_by_id[subject]["span"])
                             if events_by_id[subject].get("span") is not None else None)
            event["action_span"] = (_span_record(text, events_by_id[subject]["action_span"])
                                    if events_by_id[subject].get("action_span") is not None else None)
            found.append(event)
    return found


def _sources_for(reading, evidence):
    """One entry per claim the evidence rows were stated in.

    Each entry lists exactly the evidence rows carrying that claim id with
    those rows' own spans -- the pairing comes from the row, so a span is
    never attributed to a claim its row does not carry.
    """
    text = reading["text"]
    claims_by_id = _by_id(reading.get("claims"))
    order, grouped = [], {}
    for record in evidence:
        claim_id = record.get("claim")
        if claim_id not in grouped:
            order.append(claim_id)
            grouped[claim_id] = []
        grouped[claim_id].append({"row": record.get("id"), "triple": record.get("triple"),
                                  "layer": record.get("layer"), "role": record.get("role"),
                                  "spans": record.get("spans"), "value_span": record.get("value_span"),
                                  "carries_answer": record.get("carries_answer")})
    sources = []
    for claim_id in order:
        claim = claims_by_id.get(claim_id)
        if claim is None:
            entry = {"claim": to_json_finite(claim_id), "missing": True}
        else:
            entry = to_json_finite(claim)
            entry["claim"] = claim["id"]
            entry["span"] = _span_record(text, claim["span"]) if claim.get("span") is not None else None
            entry["reporter_span"] = (_span_record(text, claim["reporter_span"])
                                      if claim.get("reporter_span") is not None else None)
        entry["rows"] = grouped[claim_id]
        entry["carries_answer"] = any(row.get("carries_answer") for row in grouped[claim_id])
        sources.append(entry)
    return sources


def _conflicts_for(reading, evidence, events, policy, answer_predicate=None,
                  compatible_readings=None, selected_value=None,
                  source_answer_readings=None):
    """Reading-level conflict records that touch the evidence.

    Mechanics only: id intersection and ``[start, end)`` overlap.  Whether a
    touching record changes the status is the policy's call, and the
    A reading conflict is reconciled only against selector-compatible
    readings and selected evidence for the requested predicate/value. Merely
    sharing an answer value or listing all alternatives is not evidence for
    both propositions.
    """
    text = reading["text"]
    support_rows = {record.get("id") for record in evidence}
    support_readings = {record.get("reading") for record in evidence if record.get("reading")}
    support_hyps = set()
    support_spans = []
    for record in evidence:
        support_hyps.update(record.get("hypotheses") or ())
        for span in record.get("spans") or ():
            if span.get("quote") is not None:
                support_spans.append([span["start"], span["end"]])
    for event in events:
        span = event.get("span")
        if span and span.get("quote") is not None:
            support_spans.append([span["start"], span["end"]])

    contradictions = []
    for contra in reading.get("contradictions") or ():
        if not isinstance(contra, dict):
            continue
        via = []
        if set(contra.get("rows") or ()) & support_rows:
            via.append("shared_row")
        if set(contra.get("readings") or ()) & support_readings:
            via.append("shared_reading")
        if set(contra.get("hypotheses") or ()) & support_hyps:
            via.append("shared_hypothesis")
        if any(_overlaps(span, other) for span in (contra.get("spans") or ())
               for other in support_spans):
            via.append("span_overlap")
        if not via:
            continue
        record = to_json_finite(contra)
        record["spans"] = _span_records(text, contra.get("spans"))
        record["touches_support_via"] = via
        contra_rows = set(contra.get("rows") or ())
        allowed = set(policy.get("conflict_detection", {}).get("agreement_kinds", ()))
        answer_readings = {
            item.get("reading") for item in evidence
            if item.get("carries_answer") and item.get("reading")
            and answer_predicate is not None
            and selected_value is not None
            and isinstance(item.get("triple"), (list, tuple))
            and len(item["triple"]) == 3 and item["triple"][1] == answer_predicate
            and (item["triple"][2] == selected_value or item["triple"][0] == selected_value)
        }
        listed = set(contra.get("readings") or ())
        applicable_readings = (listed & set(compatible_readings)
                               if compatible_readings is not None else listed)
        source_agreement = (contra.get("kind") == "reading_conflict"
                            and source_answer_readings is not None
                            and bool(applicable_readings)
                            and applicable_readings <= source_answer_readings)
        record["agreed_across_support_readings"] = source_agreement or (
            contra.get("kind") in allowed and bool(applicable_readings)
            and applicable_readings <= answer_readings
        )
        record["query_compatible_readings"] = sorted(applicable_readings)
        record["excluded_by_question_constraints"] = bool(listed) and not applicable_readings
        record["answer_supported_in_readings"] = sorted(
            (answer_readings | (source_answer_readings or set())) & applicable_readings)
        contradictions.append(record)

    readings_by_id = _by_id(reading.get("readings"))
    competing = []
    active_support_readings = (support_readings & set(compatible_readings)
                               if compatible_readings is not None else support_readings)
    for reading_id in sorted(active_support_readings):
        record = readings_by_id.get(reading_id)
        if record is None:
            continue
        rivals = list(record.get("competes_with") or ())
        if not rivals:
            continue
        entry = to_json_finite(record)
        entry["reading"] = reading_id
        entry["rivals"] = [to_json_finite(readings_by_id[rival]) if rival in readings_by_id
                           else {"id": to_json_finite(rival), "missing": True} for rival in rivals]
        active_rivals = (set(rivals) & set(compatible_readings)
                         if compatible_readings is not None else set(rivals))
        entry["rivals_outside_support"] = [rival for rival in rivals
                                           if rival in active_rivals and rival not in support_readings]
        competing.append(entry)

    dropped = []
    for item in reading.get("dropped_readings") or ():
        if not isinstance(item, dict):
            continue
        if any(_overlaps(item.get("span"), other) for other in support_spans):
            record = to_json_finite(item)
            record["span"] = _span_record(text, item["span"]) if item.get("span") is not None else None
            record["roles"] = [dict(to_json_finite(role),
                                    value_span=_span_record(text, role["value_span"])
                                    if isinstance(role, dict) and role.get("value_span") is not None else None)
                               for role in (item.get("roles") or ())]
            dropped.append(record)

    return {"contradictions": contradictions, "competing_readings": competing,
            "dropped_readings": dropped}


# --------------------------------------------------------------------------
# Status
# --------------------------------------------------------------------------

def _status(policy, error, plan, result, hops, conflicts, provenance_incomplete=False):
    statuses = policy["statuses"]
    signals = []

    def add(name):
        if name not in statuses:
            name = policy["unknown_gate_status"]
        if name not in signals:
            signals.append(name)

    if error is not None:
        add(policy["error_status"])
    if plan is not None and plan.get("unresolved"):
        add(policy["gates"].get("unresolved", policy["unknown_gate_status"]))
    gate = result.get("gate") if isinstance(result, dict) else None
    if result is not None and gate is not None:
        add(policy["gates"].get(gate, policy["unknown_gate_status"]))
    result_value = result.get("value") if isinstance(result, dict) else None
    for mapped in policy.get("result_status_values", ()):
        if result_value in mapped.get("values", ()):
            add(mapped["status"])
    if isinstance(result, dict):
        for condition in policy.get("result_status_conditions", ()):
            if (result.get("intent") == condition.get("intent")
                    and result_value == condition.get("value")):
                add(condition["status"])
    if any(not hop.get("complete") or not hop.get("assembled") for hop in hops):
        add(policy["incomplete_search_status"])
    if provenance_incomplete:
        add(policy.get("provenance_incomplete_status", "provenance_incomplete"))
    if any(not item.get("agreed_across_support_readings")
           and not item.get("excluded_by_question_constraints")
           for item in conflicts["contradictions"]):
        add(policy["conflict_statuses"]["contradiction"])
    if any(item.get("rivals_outside_support") for item in conflicts["competing_readings"]):
        add(policy["conflict_statuses"]["competing_reading"])
    if error is None and isinstance(result, dict) and gate is None:
        if result.get("case") is None:
            add(policy["unknown_gate_status"])
        else:
            add(policy["answered_status"])
    if not signals:
        add(policy["unknown_gate_status"])

    chosen = None
    for name in policy["precedence"]:
        if name in signals:
            chosen = name
            break
    if chosen is None:
        chosen = signals[0]
    ordered = [name for name in policy["precedence"] if name in signals]
    ordered += [name for name in signals if name not in ordered]
    return chosen, bool(statuses[chosen]["abstained"]), ordered


def _qualifications(policy, evidence):
    table = policy.get("scope_qualifications") or {}
    found = []
    for record in evidence:
        label = table.get(record.get("scope_kind"))
        if label and label not in found:
            found.append(label)
    return found


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------

def read(text, extra_graphs=()):
    """Convenience pass-through onto ``core.read_text``.  ``answer`` never calls it."""
    return _core_read_text(text, extra_graphs=extra_graphs)


def answer(reading, question, *, search_rows=None):
    """Answer ``question`` from the already-extracted ``reading``.

    Returns a new dict (see API.md for every field).  Never re-reads the
    text.  Never mutates ``reading``.  Never raises for a pipeline failure:
    a compile / execute / render exception is reported under ``error`` with
    ``status: "error"``.  Raises ``TypeError`` only when ``reading`` is not a
    dict or ``question`` is not a str.

    ``search_rows`` is a diagnostic override of the search transport, with
    the same signature as ``core.search_rows``; it is for tests of this
    module.  An evaluation must leave it ``None``.
    """
    if not isinstance(reading, dict):
        raise TypeError("reading must be the dict core.read_text returns")
    if not isinstance(question, str):
        raise TypeError("question must be a str")
    return _run(reading, question, None, search_rows)


def answer_plan(reading, plan, *, search_rows=None):
    """Like ``answer`` but for a plan already produced by ``compile_question``
    (or a structurally equivalent supplied query).  The plan is used as given;
    nothing is compiled.  ``question`` in the record is ``plan["text"]`` when
    present."""
    if not isinstance(reading, dict):
        raise TypeError("reading must be the dict core.read_text returns")
    if not isinstance(plan, dict):
        raise TypeError("plan must be the dict compile_question returns")
    question = plan.get("text") if isinstance(plan.get("text"), str) else None
    return _run(reading, question, plan, search_rows)


def _error_record(where, exc):
    return {"where": where, "type": _type_name(type(exc)), "message": str(exc)}


def _reading_problems(reading):
    problems = []
    if not isinstance(reading.get("text"), str):
        problems.append("text is not a str")
    if not isinstance(reading.get("rows"), list):
        problems.append("rows is not a list")
    return problems


def _run(reading, question, supplied_plan, search_override):
    policy = load_status_policy()
    warnings = []
    if reading.get("schema") != READING_SCHEMA:
        warnings.append("reading_schema_mismatch:%s" % to_json_finite(reading.get("schema")))
    error = None
    problems = _reading_problems(reading)
    if problems:
        error = {"where": "reading", "type": "InvalidReading", "message": "; ".join(problems)}

    plan = supplied_plan
    if error is None and plan is None:
        try:
            plan = _compile_question(question)
        except Exception as exc:  # reported, not raised: the caller gets the record
            error = _error_record("compile", exc)

    recorder = _RecordingSearch(search_override if search_override is not None else _core_search_rows)
    result = None
    if error is None:
        try:
            result = _execute_plan(plan, reading, search_rows=recorder)
        except Exception as exc:
            error = _error_record("execute", exc)

    rendered = None
    if error is None:
        try:
            rendered = _render(result, plan)
        except Exception as exc:
            error = _error_record("render", exc)
    if rendered is not None and not isinstance(rendered, str):
        warnings.append("render_returned_non_str:%s" % _type_name(type(rendered)))
        rendered = None

    text = reading.get("text") if isinstance(reading.get("text"), str) else ""
    rows = reading.get("rows") if isinstance(reading.get("rows"), list) else []
    usable = {"text": text, "rows": rows,
              "proofs": reading.get("proofs"), "hypotheses": reading.get("hypotheses"),
              "events": reading.get("events"), "claims": reading.get("claims"),
              "contradictions": reading.get("contradictions"),
              "readings": reading.get("readings"),
              "dropped_readings": reading.get("dropped_readings")}

    gate = result.get("gate") if isinstance(result, dict) else None
    raw_value = result.get("raw_value") if isinstance(result, dict) else None
    selected_values = {raw_value} if gate is None and raw_value is not None else set()

    candidates = []
    selected_evidence, selected_proofs, selected_hyps, selected_missing = [], [], [], []
    for candidate in (result.get("candidates") or ()) if isinstance(result, dict) else ():
        if not isinstance(candidate, dict):
            candidates.append({"opaque": to_json_finite(candidate)})
            continue
        value = candidate.get("value")
        answer_values = {value} if value is not None else set()
        evidence, proofs, hyps, missing = _chain(usable, _support_row_ids(candidate), answer_values)
        selected = gate is None and value in selected_values
        entry = {"value": to_json_finite(value),
                 "polarities": to_json_finite(candidate.get("polarities")),
                 "support_ids": to_json_finite(candidate.get("support_ids")),
                 "support_rows": [record.get("id") for record in evidence if record.get("role") == "support"],
                 "selected": selected,
                 "evidence": evidence, "proofs": proofs, "hypotheses": hyps,
                 "missing_references": missing}
        candidates.append(entry)
        if selected:
            selected_evidence, selected_proofs, selected_hyps, selected_missing = evidence, proofs, hyps, missing

    # A selector conflict is a derived result over competing candidate values,
    # not a raw value candidate. Preserve both sides' actual supports as the
    # evidence for that result so the conflict answer remains fully auditable.
    result_value = result.get("value") if isinstance(result, dict) else None
    conflict_values = {value for mapping in policy.get("result_status_values", ())
                       if mapping.get("status") == policy["conflict_statuses"]["contradiction"]
                       for value in mapping.get("values", ())}
    if gate is None and raw_value is None and result_value in conflict_values:
        seen = set()
        for candidate in candidates:
            if candidate.get("opaque") is not None:
                continue
            candidate["supports_result"] = True
            for evidence_record in candidate.get("evidence", ()):
                row_id = evidence_record.get("id")
                if row_id in seen:
                    continue
                seen.add(row_id)
                selected_evidence.append(evidence_record)
            for field, target in (("proofs", selected_proofs),
                                  ("hypotheses", selected_hyps),
                                  ("missing_references", selected_missing)):
                for reference in candidate.get(field, ()):
                    if reference not in target:
                        target.append(reference)

    events = _events_for(usable, selected_evidence)
    sources = _sources_for(usable, selected_evidence)
    decision_evidence, decision_proofs, decision_hyps, decision_missing = [], [], [], []
    decision_sources = []
    decision_gate = gate if isinstance(gate, str) else None
    decision_modes = policy.get("decision_evidence_gates", {})
    if decision_gate in decision_modes:
        state = result.get("state") if isinstance(result, dict) else None
        support_ids = []
        if decision_modes[decision_gate] == "selector_state" and isinstance(state, dict):
            for entries in state.values():
                if not isinstance(entries, list):
                    continue
                for entry in entries:
                    if not isinstance(entry, dict):
                        continue
                    for row_id in _support_row_ids(entry):
                        if row_id not in support_ids:
                            support_ids.append(row_id)
        (decision_evidence, decision_proofs, decision_hyps,
         decision_missing) = _chain(usable, support_ids, set())
        for item in decision_evidence:
            item["decision_basis"] = decision_gate
            item["carries_answer"] = False
        decision_sources = _sources_for(usable, decision_evidence)
    conflict_basis = selected_evidence if selected_evidence else [
        record for entry in candidates for record in entry.get("evidence", ())]
    conflict_events = events if selected_evidence else _events_for(usable, conflict_basis)
    answer_predicate = plan.get("asked_predicate") if isinstance(plan, dict) else None
    compatible_readings = (result.get("compatible_readings")
                           if isinstance(result, dict)
                           and isinstance(result.get("compatible_readings"), list) else None)
    source_answer_readings = None
    if (isinstance(result, dict) and result.get("intent") == "source_question"
            and result.get("case") == "reporter" and raw_value is not None
            and compatible_readings):
        # A source question selects a reporter for a query-constrained claim.
        # Its answer is invariant over same-frame alternatives when the
        # selected candidate's support includes each compatible reading.
        # Multiple reporter values still follow the selector's ambiguity gate.
        selected_candidates = [item for item in candidates
                               if item.get("value") == raw_value]
        reporter_row = any(
            isinstance(item.get("triple"), (list, tuple))
            and len(item["triple"]) == 3
            and item["triple"][1] == "reporter"
            and item["triple"][2] == raw_value
            for item in selected_evidence)
        candidate_readings = set()
        for item in selected_candidates:
            candidate_readings.update(
                record.get("reading") for record in item.get("evidence", ())
                if record.get("reading"))
        if reporter_row and set(compatible_readings) <= candidate_readings:
            source_answer_readings = set(compatible_readings)
    conflicts = _conflicts_for(usable, conflict_basis, conflict_events, policy,
                               answer_predicate, compatible_readings,
                               raw_value if gate is None else None,
                               source_answer_readings)
    selected_support_ids = set()
    for candidate in (result.get("candidates") or ()) if isinstance(result, dict) else ():
        if isinstance(candidate, dict) and gate is None and candidate.get("value") == raw_value:
            selected_support_ids.update(_support_row_ids(candidate))
    is_result_conflict = gate is None and raw_value is None and result_value in conflict_values
    provenance_incomplete = bool(selected_missing or decision_missing) or any(
        record.get("missing") for record in sources
    ) or (gate is None and bool(selected_support_ids) and not selected_evidence)
    if decision_evidence and (any(not item.get("spans") or any(
            span.get("quote") is None for span in item.get("spans", ()))
            for item in decision_evidence)
            or any(source.get("missing") for source in decision_sources)):
        provenance_incomplete = True
    if gate is None and raw_value is not None:
        provenance_incomplete = provenance_incomplete or any(
            not record.get("spans") or any(span.get("quote") is None for span in record.get("spans", ()))
            for record in selected_evidence
        )
        limits = reading.get("limits")
        if isinstance(limits, dict) and limits.get("complete") is not True:
            provenance_incomplete = True
    # A selector must cite at least one resolvable premise for an exact answer.
    if gate is None and raw_value is not None and not selected_support_ids:
        provenance_incomplete = True
    if is_result_conflict and (not selected_evidence or selected_missing):
        provenance_incomplete = True

    semantic_candidates = []
    for candidate in (result.get("semantic_candidates") or ()) if isinstance(result, dict) else ():
        if not isinstance(candidate, dict):
            semantic_candidates.append({"opaque": to_json_finite(candidate)})
            continue
        candidate_value = candidate.get("value")
        evidence, proofs, hypotheses, missing = _chain(
            usable, _support_row_ids(candidate),
            {candidate_value} if candidate_value is not None else set())
        semantic_candidates.append({
            "value": to_json_finite(candidate_value),
            "support_ids": to_json_finite(candidate.get("support_ids")),
            "support_rows": [item.get("id") for item in evidence if item.get("role") == "support"],
            "source_refs": to_json_finite(candidate.get("source_refs")),
            "evidence": evidence,
            "proofs": proofs,
            "hypotheses": hypotheses,
            "missing_references": missing,
        })
    status, abstained, signals = _status(policy, error, plan, result, recorder.hops, conflicts,
                                         provenance_incomplete)
    answer_suppression = None
    conflict_policy = policy.get("conflict_response_policy", {})
    conflict_status_names = set(policy.get("conflict_statuses", {}).values())
    qualified_conflict_scopes = set(conflict_policy.get("qualified_scopes", ()))
    has_qualified_scope = any(record.get("scope_kind") in qualified_conflict_scopes
                              for record in selected_evidence)
    has_qualified_conflict_result = result_value in set(
        conflict_policy.get("qualified_result_values", ()))
    if (conflict_policy.get("suppress_unqualified_answer") is True
            and status in conflict_status_names and rendered is not None
            and not has_qualified_scope and not has_qualified_conflict_result):
        rendered = None
        answer_suppression = {"reason": conflict_policy.get("suppression_reason"),
                              "status": status}
    # The public record cannot present an exact answer as usable when the
    # search transport or its selected premise chain is incomplete.
    if status in (policy["incomplete_search_status"],
                  policy.get("provenance_incomplete_status", "provenance_incomplete")):
        rendered = None
    answer_spans = []
    for record in selected_evidence:
        if not record.get("carries_answer"):
            continue
        spans = [record["value_span"]] if record.get("value_span") else list(record.get("spans") or ())
        for span in spans:
            answer_spans.append(dict(span, row=record.get("id")))

    hops = list(recorder.hops)
    incomplete_reasons = [hop.get("reason") for hop in hops
                          if not hop.get("complete") or not hop.get("assembled")]

    return {
        "schema": API_SCHEMA,
        "reading_schema": to_json_finite(reading.get("schema")),
        "question": question,
        "answer": rendered,
        "answer_suppression": answer_suppression,
        "status": status,
        "abstained": abstained,
        "signals": signals,
        "intent": to_json_finite(result.get("intent")) if isinstance(result, dict) else to_json_finite(plan.get("intent")) if isinstance(plan, dict) else None,
        "gate": to_json_finite(gate),
        "reason": to_json_finite(result.get("reason")) if isinstance(result, dict) else None,
        "case": to_json_finite(result.get("case")) if isinstance(result, dict) else None,
        "value": to_json_finite(result.get("value")) if isinstance(result, dict) else None,
        "raw_value": to_json_finite(raw_value),
        "semantic_relation": to_json_finite(result.get("semantic_relation")) if isinstance(result, dict) else None,
        "semantic_value": to_json_finite(result.get("semantic_value")) if isinstance(result, dict) else None,
        "semantic_candidates": semantic_candidates,
        "answer_scope": to_json_finite(plan.get("answer_scope")) if isinstance(plan, dict) else None,
        "requested_type": to_json_finite(plan.get("requested_type")) if isinstance(plan, dict) else None,
        "type_verification": to_json_finite(plan.get("type_verification")) if isinstance(plan, dict) else None,
        "compatible_events": to_json_finite(result.get("compatible_events")) if isinstance(result, dict) else None,
        "compatible_readings": to_json_finite(result.get("compatible_readings")) if isinstance(result, dict) else None,
        "qualifications": list(dict.fromkeys(
            _qualifications(policy, selected_evidence)
            + _qualifications(policy, decision_evidence))),
        "answer_spans": answer_spans,
        "evidence": selected_evidence,
        "proofs": selected_proofs,
        "hypotheses": selected_hyps,
        "events": events,
        "sources": sources,
        "decision_evidence": decision_evidence,
        "decision_proofs": decision_proofs,
        "decision_hypotheses": decision_hyps,
        "decision_sources": decision_sources,
        "decision_missing_references": decision_missing,
        "missing_references": selected_missing,
        "candidates": candidates,
        "conflicts": conflicts,
        "search": {"hops": hops,
                   "complete": bool(hops) and all(hop.get("complete") and hop.get("assembled") for hop in hops),
                   "incomplete_reasons": incomplete_reasons},
        "reading_notes": {
            "text_length": len(text),
            "rows": len(rows),
            "unresolved": to_json_finite(reading.get("unresolved")),
            "entity_ambiguity": to_json_finite(reading.get("entity_ambiguity")),
            "contradictions": len(reading.get("contradictions") or ()),
            "readings": len(reading.get("readings") or ()),
            "dropped_readings": len(reading.get("dropped_readings") or ()),
            "limits": to_json_finite(reading.get("limits")),
        },
        "facts": to_json_finite(rows),
        "plan": to_json_finite(plan),
        "result": to_json_finite(result),
        "error": to_json_finite(error),
        "warnings": warnings,
        "policy": {"schema": policy.get("schema"), "path": STATUS_POLICY_PATH},
    }


__all__ = ["API_SCHEMA", "STATUS_POLICY_PATH", "answer", "answer_plan", "read",
           "to_json_finite", "load_status_policy"]
