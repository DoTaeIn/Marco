"""Opt-in host for graph-proposed, question-bound contextual meanings.

The graph program proposes readings; this module only checks receipts, source
ownership, the live context, and the pending overlay proposal. A confirmed
reading is used for one unchanged source in one ground-language call.
"""
import hashlib
import json

from marco.reasoning.context import ReasoningContext
from marco.reasoning.graph_vm import run_recorded, validate_value
from marco.reasoning.proof_graph import build_proof_graph, verify_proof_graph
from marco.reasoning.readings import Obs, validate_ledger as validate_reading_ledger
from marco.runtime.ground_language_work import advance_ground_language
from marco.storage.ids import node_id
from marco.storage.overlay import OverlayStore, add_node, dumps
from tools.graph_reasoning_audit import verify_vm_record


SCHEMA = "marco-contextual-meaning-host-v2"
SESSION_SCHEMA = "marco-contextual-meaning-session-v2"
GRAPH_ID = "programs/contextual-meaning-candidates-ko-experimental.json"
_FACT_KEYS = {"id", "triple", "evidence", "polarity", "modality"}
_MARKER_NAMES = {"subject_markers", "object_markers", "orders", "seed_object_marker"}
_ERRORS = (ValueError, TypeError, KeyError, UnicodeEncodeError, RecursionError)


def _json(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))


def _canon(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_canon(value).encode("utf-8")).hexdigest()


def _text(value, limit):
    return type(value) is str and bool(value) and len(value) <= limit


def _source(value):
    if (type(value) is not dict or value.keys() != {"id", "text", "sha256"}
            or not _text(value["id"], 64) or not _text(value["text"], 1024)
            or type(value["sha256"]) is not str
            or hashlib.sha256(value["text"].encode("utf-8")).hexdigest() != value["sha256"]):
        raise ValueError("source")
    return _json(value)


def _model(value):
    model = validate_value(_json(value))
    if type(model) is not dict or model.keys() != {"labels", "labels_by_id", "patterns"}:
        raise ValueError("model")
    labels, first, label_ids = model["labels"], {}, set()
    if type(labels) is not list or len(labels) > 4:
        raise ValueError("labels")
    for label in labels:
        if (type(label) is not dict or label.keys() != {"id", "text"}
                or not _text(label["id"], 64) or label["id"] in label_ids
                or not _text(label["text"], 128)):
            raise ValueError("label")
        label_ids.add(label["id"])
        first[label["id"]] = label["text"]
    if model["labels_by_id"] != first:
        raise ValueError("labels_by_id")
    patterns, seen = model["patterns"], set()
    if type(patterns) is not list or len(patterns) > 12:
        raise ValueError("patterns")
    for pattern in patterns:
        if (type(pattern) is not dict
                or pattern.keys() != {"id", "kind", "relation", "polarity", "prefix", "between", "suffix"}
                or not _text(pattern["id"], 64) or pattern["id"] in seen
                or pattern["kind"] not in ("fact", "query") or not _text(pattern["relation"], 128)
                or type(pattern["polarity"]) is not bool
                or (pattern["kind"] == "query" and pattern["polarity"] is not True)
                or any(type(pattern[key]) is not str or len(pattern[key]) > 128
                       for key in ("prefix", "between", "suffix"))):
            raise ValueError("pattern")
        seen.add(pattern["id"])
    return model


def _markers(program):
    found = {}
    expected = {
        "composition_subject_markers": "subject_markers",
        "composition_object_markers": "object_markers",
        "composition_orders": "orders",
        "composition_seed_object_marker": "seed_object_marker",
    }
    if type(program) is not dict or type(program.get("nodes")) is not list:
        raise ValueError("language_program")
    for node in program["nodes"]:
        if type(node) is dict and (node.get("id") in expected or node.get("name") in _MARKER_NAMES):
            if (node.get("id") not in expected or expected[node["id"]] != node.get("name")
                    or node.get("op") != "set"):
                raise ValueError("marker_identity")
            name = expected[node["id"]]
            value = node.get("value")
            if (name in found or type(value) is not dict or value.keys() != {"literal"}):
                raise ValueError("marker_cell")
            found[name] = value["literal"]
    if found.keys() != _MARKER_NAMES:
        raise ValueError("marker_cells")
    if (type(found["subject_markers"]) is not list or not 1 <= len(found["subject_markers"]) <= 2
            or any(not _text(x, 64) for x in found["subject_markers"])
            or len(set(found["subject_markers"])) != len(found["subject_markers"])
            or type(found["object_markers"]) is not list or not 1 <= len(found["object_markers"]) <= 2
            or any(not _text(x, 64) for x in found["object_markers"])
            or len(set(found["object_markers"])) != len(found["object_markers"])
            or type(found["orders"]) is not list or len(found["orders"]) != 2
            or any(type(order) is not list or len(order) != 3 or any(type(i) is not int for i in order)
                   for order in found["orders"])
            or found["orders"] != [[0, 1, 2], [1, 0, 2]]
            or not _text(found["seed_object_marker"], 64)):
        raise ValueError("marker_shape")
    return _json(found)


def _live_context(context, current_source):
    if type(context) is not ReasoningContext:
        raise ValueError("live_context_required")
    # `snapshot()` replays through the native parser. A source that the native
    # parser archived as unavailable can make that operation raise even when
    # the raw source is useful to this opt-in graph-language path. Read only
    # the live owner's data fields here; never invoke native parsing or replay.
    observations = ReasoningContext.observations.fget(context)
    live_ids = list(ReasoningContext.observation_ids.fget(context))
    if (type(observations) is not list or len(observations) > 33
            or any(type(x) is not Obs for x in observations)):
        raise ValueError("context_observation_owner")
    raw = [str.__str__(x) for x in observations]
    ids = live_ids
    if (type(ids) is not list or len(ids) != len(raw) or len(set(ids)) != len(ids)
            or any(type(oid) is not str or not _text(oid, 64) for oid in ids)
            or any(obs.oid != oid or type(obs.rev) is not int or obs.rev < 1
                   for obs, oid in zip(observations, ids))
            or any(not _text(text, 1024) for text in raw)):
        raise ValueError("context_observation_identity")
    records = context.reading_ledger
    next_observation = context._next_observation
    max_turns = context.max_turns
    base = context.parser_base_sha256
    installed_head = context.installed_memory_head
    conversation = context.conversation_id
    if (type(records) is not dict or type(next_observation) is not int or next_observation < 1
            or type(max_turns) is not int or not 1 <= max_turns <= 128
            or (type(base) is not str and base is not None)
            or (base is not None and (len(base) != 64 or any(c not in "0123456789abcdef" for c in base)))
            or (type(installed_head) is not int and installed_head is not None)
            or (installed_head is not None and installed_head < 0)
            or not _text(conversation, 64)):
        raise ValueError("context_ledger")
    owner_ledger = _plain_context_json({"next": next_observation, "records": records})
    checked = validate_reading_ledger(raw, ids, owner_ledger, max_turns=max_turns,
                                      base=base, head_limit=installed_head)
    # The public validator checks ledger schema and owner relationships on the
    # detached raw view; its returned records are that same read-only copy.
    ledger_wire = checked
    if type(ledger_wire) is not dict or set(ledger_wire) != {"next", "records"}:
        raise ValueError("context_ledger_wire")
    ledger_records = ledger_wire["records"]
    sources, meta = [], []
    for text, oid, obs in zip(raw, ids, observations):
        entry = ledger_records.get(oid)
        versions = entry.get("versions") if type(entry) is dict else None
        active = entry.get("active") if type(entry) is dict else None
        if type(versions) is not list or type(active) is not int or not 1 <= active <= len(versions):
            raise ValueError("context_revision")
        record = versions[active - 1]
        if (type(record) is not dict or record.get("observation_id") != oid
                or record.get("reading_revision") != active or record.get("source") != text
                or obs.rev != active):
            raise ValueError("context_source_revision")
        source = _source({"id": oid, "text": text,
                          "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()})
        meta.append({"id": oid, "sha256": source["sha256"], "revision": active,
                     "native_unavailable": record["unavailable"],
                     "native_reason": record["reason"]})
        if oid == current_source["id"]:
            if source != current_source:
                raise ValueError("current_source_identity_mismatch")
            continue
        sources.append(source)
    ledger_sha256 = _digest(ledger_wire)
    raw_view = {"conversation_id": conversation, "parser_base_sha256": base,
                "installed_memory_head": installed_head, "max_turns": max_turns,
                "observation_ids": ids,
                "observations": [{"id": oid, "text": text, "revision": obs.rev}
                                 for oid, text, obs in zip(ids, raw, observations)],
                "reading_ledger_sha256": ledger_sha256}
    context_meta = {"schema": "marco-contextual-meaning-raw-context-v2",
                    "conversation_id": conversation, "parser_base_sha256": base,
                    "installed_memory_head": installed_head, "max_turns": max_turns,
                    "observation_ids": _json(ids), "observations": meta,
                    "reading_ledger_sha256": ledger_sha256,
                    "native_unavailable": any(row["native_unavailable"] for row in meta),
                    "raw_context_sha256": _digest(raw_view)}
    return raw_view, conversation, sources, context_meta


def _plain_context_json(value, *, max_depth=32, max_nodes=262144,
                        max_bytes=16 * 1024 * 1024):
    """Detach a bounded exact JSON ledger without consulting parser-owned state."""
    state = [0, 0]

    def walk(item, depth):
        if depth > max_depth:
            raise ValueError("context_ledger_depth")
        state[0] += 1
        if state[0] > max_nodes:
            raise ValueError("context_ledger_nodes")
        kind = type(item)
        if item is None or kind is bool or kind is int:
            if kind is int and item.bit_length() > 4096:
                raise ValueError("context_ledger_integer")
            return item
        if kind is float:
            if item != item or item in (float("inf"), float("-inf")):
                raise ValueError("context_ledger_float")
            return item
        if kind is str:
            size = len(item.encode("utf-8"))
            state[1] += size
            if state[1] > max_bytes:
                raise ValueError("context_ledger_bytes")
            return item
        if kind is list:
            return [walk(child, depth + 1) for child in item]
        if kind is dict:
            out = {}
            for key, child in item.items():
                if type(key) is not str:
                    raise ValueError("context_ledger_key")
                state[1] += len(key.encode("utf-8"))
                if state[1] > max_bytes:
                    raise ValueError("context_ledger_bytes")
                out[key] = walk(child, depth + 1)
            return out
        raise ValueError("context_ledger_value")

    detached = walk(value, 0)
    if len(_canon(detached).encode("utf-8")) > max_bytes:
        raise ValueError("context_ledger_bytes")
    return detached


def _overlay_identity(store):
    if type(store) is not OverlayStore or getattr(store, "writer", False) is not True:
        raise ValueError("live_overlay_writer_required")
    meta, head = OverlayStore.meta(store), OverlayStore.head(store)
    if (not {"base_sha256", "base_build_id", "format_version", "overlay_schema"} <= meta.keys()
            or type(head) is not tuple or len(head) != 2 or type(head[0]) is not int):
        raise ValueError("overlay_identity")
    return {"base_sha256": meta["base_sha256"], "base_build_id": meta["base_build_id"],
            "format_version": meta["format_version"], "overlay_schema": meta["overlay_schema"],
            "head": [head[0], head[1]]}


def _run_vm(program, inputs, budget, trace_limit):
    program, inputs = _json(program), validate_value(_json(inputs))
    receipt = run_recorded(program, inputs, budget=budget, trace_limit=trace_limit)
    verdict = verify_vm_record(_json(receipt), program, inputs, max_budget=budget)
    if (type(verdict) is not dict or verdict.get("valid") is not True
            or verdict.get("execution_completed") is not True
            or receipt.get("record", {}).get("budget") != budget
            or receipt.get("record", {}).get("trace_limit") != trace_limit
            or receipt.get("result", {}).get("status") != "completed"):
        raise ValueError("graph_receipt")
    return _json(receipt["result"]["value"]), _json(receipt)


def _verify_vm(program, inputs, receipt, budget, trace_limit):
    if (type(receipt) is not dict or receipt.get("record", {}).get("budget") != budget
            or receipt.get("record", {}).get("trace_limit") != trace_limit
            or receipt.get("result", {}).get("status") != "completed"):
        raise ValueError("saved_graph_receipt")
    verdict = verify_vm_record(_json(receipt), _json(program), validate_value(_json(inputs)), max_budget=budget)
    if type(verdict) is not dict or verdict.get("valid") is not True or verdict.get("execution_completed") is not True:
        raise ValueError("saved_graph_receipt")
    return _json(receipt["result"]["value"])


def _bridge(language, model, information, rules, sources, query, context_id, *, session=None,
            max_steps=128, budget=4096, trace_limit=256):
    statements = [{"source": _json(source), "caller_attested": True} for source in sources]
    return advance_ground_language(language, model, information, rules, statements, query, context_id,
                                   session=session, max_steps=max_steps, max_questions=2,
                                   budget=budget, trace_limit=trace_limit, limit=32,
                                   proof_limit=4, search_limit=256)


def _verified_context_facts(ground, sources):
    if type(ground) is not dict or type(ground.get("session")) is not dict:
        raise ValueError("context_reparse")
    facts = ground.get("information_work", {}).get("facts")
    if type(facts) is not list or len(facts) > 32:
        raise ValueError("context_facts")
    by_id = {source["id"]: source for source in sources}
    for fact in facts:
        if type(fact) is not dict or not _FACT_KEYS <= fact.keys():
            raise ValueError("context_fact")
        evidence = fact["evidence"]
        source = by_id.get(evidence.get("source_id")) if type(evidence) is dict else None
        if (source is None or evidence.get("kind") != "caller_attested_source"
                or evidence.get("caller_attested") is not True
                or evidence.get("sha256") != source["sha256"]
                or fact["id"] != "src-" + _digest({"source_id": source["id"], "sha256": source["sha256"]})[:32]
                or type(fact["triple"]) is not list or len(fact["triple"]) != 3):
            raise ValueError("context_fact_source")
    if len(facts) != len(sources) or {f["evidence"]["source_id"] for f in facts} != set(by_id):
        raise ValueError("context_fact_coverage")
    return _json(facts)


def _proofs(candidates, facts, rules):
    rows, conflicts = [], []
    for candidate in candidates:
        meaning = candidate["proposed_meaning"]
        target = meaning["triple"]
        record = build_proof_graph(facts, rules, target, limit=32, proof_limit=4, search_limit=256)
        verification = verify_proof_graph(record, facts, rules, target)
        if type(verification) is not dict or verification.get("valid") is not True:
            raise ValueError("context_proof")
        status = record.get("status")
        opposed = ((meaning["polarity"] is True and status in ("contradicted", "conflict"))
                   or (meaning["polarity"] is False and status in ("proved", "conflict")))
        rows.append({"candidate_id": candidate["candidate_id"], "target": _json(target),
                     "polarity": meaning["polarity"], "record": record, "verification": verification})
        if opposed:
            conflicts.append(candidate["candidate_id"])
    return rows, conflicts


def _validate_decomposition(out, source, model, markers):
    if (type(out) is not dict or out.keys() != {"action", "state", "reason", "decomposition", "candidates"}
            or out.get("action") != "done" or out.get("state") is not None or out.get("reason") != "candidates_ready"
            or type(out.get("decomposition")) is not dict or type(out.get("candidates")) is not list):
        raise ValueError("decomposition")
    d, rows = out["decomposition"], out["candidates"]
    if (d.get("source_id") != source["id"] or d.get("source_text") != source["text"]
            or d.get("kind") != "fact" or d.get("subject_id") not in model["labels_by_id"]
            or d.get("object_id") not in model["labels_by_id"]
            or not _text(d.get("unknown_surface"), 1024)
            or type(d.get("span")) is not dict or d["span"].keys() != {"start", "end"}
            or type(d["span"].get("start")) is not int or type(d["span"].get("end")) is not int
            or not 0 <= d["span"]["start"] < d["span"]["end"] <= len(source["text"])
            or source["text"][d["span"]["start"]:d["span"]["end"]] != d["unknown_surface"]):
        raise ValueError("decomposition_source")
    template = d.get("template")
    if (type(template) is not dict or template.keys() != {"prefix", "between", "suffix"}
            or type(template["prefix"]) is not str or template["between"] not in markers["subject_markers"]
            or template["suffix"] != markers["seed_object_marker"] + d["unknown_surface"]):
        raise ValueError("decomposition_template")
    fact_patterns = {p["id"]: p for p in model["patterns"] if p["kind"] == "fact"}
    if len(fact_patterns) != 6 or len(rows) != 6:
        raise ValueError("candidate_set_size")
    seen = set()
    for row in rows:
        if (type(row) is not dict or row.keys() != {"candidate_id", "source_id", "source_surface", "span",
                                                       "seed_pattern_id", "proposed_meaning", "display_text"}
                or row["source_id"] != source["id"] or row["source_surface"] != d["unknown_surface"]
                or row["span"] != d["span"] or row["seed_pattern_id"] not in fact_patterns
                or row["candidate_id"] != "candidate:" + row["seed_pattern_id"]
                or row["candidate_id"] in seen or not _text(row["display_text"], 1024)):
            raise ValueError("candidate")
        pat, meaning = fact_patterns[row["seed_pattern_id"]], row["proposed_meaning"]
        if (type(meaning) is not dict or meaning != {"kind": "fact",
                "triple": [d["subject_id"], pat["relation"], d["object_id"]], "polarity": pat["polarity"]}):
            raise ValueError("candidate_meaning")
        seen.add(row["candidate_id"])
    if seen != {"candidate:" + key for key in fact_patterns}:
        raise ValueError("candidate_coverage")
    return _json(d), _json(rows)


def _decompose(program, source, model, markers, budget, trace_limit, max_steps, saved=None):
    state, runs, final = None, [], None
    for index in range(max_steps):
        inputs = {"mode": "decompose", "text": source["text"], "source_id": source["id"],
                  "model": model, "markers": markers, "state": state}
        if saved is None:
            out, receipt = _run_vm(program, inputs, budget, trace_limit)
            runs.append({"input": _json(inputs), "receipt": receipt})
        else:
            if index >= len(saved) or type(saved[index]) is not dict or saved[index].get("input") != inputs:
                raise ValueError("decompose_history")
            receipt = saved[index]["receipt"]
            out = _verify_vm(program, inputs, receipt, budget, trace_limit)
            runs.append(_json(saved[index]))
        if (type(out) is not dict or out.keys() != {"action", "state", "reason", "decomposition", "candidates"}
                or out.get("action") not in ("continue", "done", "hold")):
            raise ValueError("decompose_output")
        if out["action"] == "hold":
            if out.get("state") is not None or out.get("decomposition") is not None or out.get("candidates") is not None:
                raise ValueError("decompose_hold_shape")
            if saved is not None and len(saved) != len(runs):
                raise ValueError("decompose_trailing")
            return None, runs, out.get("reason", "unsupported")
        if out["action"] == "done":
            if out.get("state") is not None:
                raise ValueError("decompose_done_state")
            final = out
            break
        state = out.get("state")
        if (type(state) is not dict or state.keys() != {"phase", "si", "oi", "pi", "found", "ambiguous",
                                                         "decomposition", "candidates", "signatures", "relations"}
                or out.get("reason") != "progress" or out.get("decomposition") is not None
                or out.get("candidates") is not None or state.get("phase") not in ("roles", "candidates")
                or any(type(state.get(k)) is not int or state[k] < 0 for k in ("si", "oi", "pi"))
                or state["si"] > len(model["labels"]) or state["oi"] > len(model["labels"])
                or state["pi"] > len(model["patterns"])
                or type(state.get("found")) is not list or len(state["found"]) > 1
                or type(state.get("ambiguous")) is not bool
                or type(state.get("candidates")) is not list or len(state["candidates"]) > 6
                or type(state.get("decomposition")) not in (dict, type(None))
                or type(state.get("signatures")) is not list or len(state["signatures"]) > 6
                or type(state.get("relations")) is not list or len(state["relations"]) > 3
                or any(type(x) is not str for x in state["relations"])
                or any(type(x) is not dict or x.keys() != {"relation", "polarity"}
                       or not _text(x["relation"], 128) or type(x["polarity"]) is not bool
                       for x in state["signatures"])):
            raise ValueError("decompose_state")
    if final is None or (saved is not None and len(saved) != len(runs)):
        raise ValueError("decompose_step_limit")
    return final, runs, None


def _question_id(source, pins, decomposition, candidates):
    return "qctx_" + _digest({"source": source, "pins": pins, "decomposition": decomposition,
                              "candidates": candidates})[:32]


def _overlay_request(store, pins, source, query, context_meta, decomposition, candidates,
                     proofs, question, qid, decompose_runs, clarify_receipt):
    oid = "cand_" + _digest({"pins": pins, "question_id": qid, "candidate_ids":
                              [c["candidate_id"] for c in candidates]})[:32]
    compact_proofs = [{"candidate_id": row["candidate_id"], "status": row["record"]["status"],
                       "proof_sha256": _digest(row["record"])} for row in proofs]
    evidence = {"schema": SESSION_SCHEMA, "candidate_id": oid, "pins": _json(pins),
                "source": _json(source), "query": _json(query), "context": _json(context_meta),
                "decomposition": _json(decomposition), "candidates": _json(candidates),
                "context_proofs": compact_proofs, "question": _json(question),
                "vm_receipt_sha256": {"decompose": [_digest(row["receipt"]) for row in decompose_runs],
                                      "clarify": _digest(clarify_receipt)}}
    data = {"schema": SESSION_SCHEMA, "candidate_id": oid, "pins": _json(pins),
            "source": _json(source), "candidate_ids": [c["candidate_id"] for c in candidates],
            "question_id": qid, "question_sha256": _digest(question)}
    delta = add_node(GRAPH_ID, oid, revision=0, data=data)
    deltas = [delta]
    return {"candidate_id": oid, "actor": "marco-contextual-meaning-host",
            "source": source["id"], "reason": "pending contextual meaning clarification",
            "evidence": evidence, "deltas": deltas, "request_digest": hashlib.sha256(
                dumps(deltas).encode("utf-8")).hexdigest(), "proposed_at_seq": pins["overlay"]["head"][0]}


def _confirmation_request(pins, question_proposal, source, query, answer, selected, question):
    qid = pins["question_id"]
    choice = next((row for row in question["choices"]
                   if row["candidate_id"] == selected["candidate_id"]), None)
    if choice is None or answer["text"] != choice["reply_text"]:
        raise ValueError("confirmation_choice")
    identity = {"question_candidate_id": question_proposal["candidate_id"], "question_id": qid}
    cid = "cand_" + _digest(identity)[:32]
    meaning = _json(selected["proposed_meaning"])
    evidence = {"schema": SESSION_SCHEMA, "kind": "contextual_meaning_confirmation",
                "candidate_id": cid, "pins": _json(pins),
                "question_candidate_id": question_proposal["candidate_id"], "question_id": qid,
                "source": _json(source), "query": _json(query), "reply_source": _json(answer),
                "reply_caller_attested": True, "reply_text": choice["reply_text"],
                "selected_candidate_id": selected["candidate_id"],
                "selected_meaning": meaning}
    data = {"schema": SESSION_SCHEMA, "kind": "contextual_meaning_confirmation",
            "candidate_id": cid, "pins": _json(pins),
            "question_candidate_id": question_proposal["candidate_id"], "question_id": qid,
            "reply_source_id": answer["id"], "reply_sha256": answer["sha256"],
            "reply_caller_attested": True, "selected_candidate_id": selected["candidate_id"],
            "selected_meaning": meaning}
    deltas = [add_node(GRAPH_ID, cid, revision=0, data=data)]
    return {"candidate_id": cid, "actor": "marco-contextual-meaning-host",
            "source": answer["id"], "reason": "pending question-bound meaning confirmation",
            "evidence": evidence, "deltas": deltas, "request_digest": hashlib.sha256(
                dumps(deltas).encode("utf-8")).hexdigest(), "proposed_at_seq": pins["overlay"]["head"][0]}


def _propose(store, proposal, identity):
    if _overlay_identity(store) != identity:
        raise ValueError("overlay_changed_before_proposal")
    actual_id = OverlayStore.propose(store, proposal["deltas"], actor=proposal["actor"],
        source=proposal["source"], reason=proposal["reason"], evidence=proposal["evidence"],
        candidate_id=proposal["candidate_id"])
    if actual_id != proposal["candidate_id"]:
        raise ValueError("overlay_candidate_id")
    if _overlay_identity(store) != identity:
        raise ValueError("overlay_changed_after_proposal")
    _candidate_matches(store, proposal, identity)


def _candidate_matches(store, proposal, identity):
    if _overlay_identity(store) != identity:
        raise ValueError("overlay_changed")
    row = OverlayStore.candidate(store, proposal["candidate_id"])
    if (type(row) is not dict or row.get("status") != "pending"
            or row.get("proposed_at_seq") != identity["head"][0]
            or row.get("actor") != proposal["actor"] or row.get("source") != proposal["source"]
            or row.get("reason") != proposal["reason"] or row.get("evidence") != proposal["evidence"]
            or row.get("deltas") != proposal["deltas"]
            or row.get("request_digest") != proposal["request_digest"]
            or hashlib.sha256(dumps(row.get("deltas")).encode("utf-8")).hexdigest()
            != proposal["request_digest"]):
        raise ValueError("overlay_candidate_changed")
    target = node_id(GRAPH_ID, proposal["candidate_id"])
    if OverlayStore.item(store, "node", target, at=identity["head"][0]) is not None:
        raise ValueError("overlay_candidate_active")


def _output(status, reason, session=None, **fields):
    return {"schema": SCHEMA, "status": status, "reason": reason,
            "question": None, "candidates": [], "overlay_candidate_id": None,
            "confirmation_candidate_id": None,
            "selected_candidate_id": None, "selected_meaning": None,
            "baseline_result": None, "ground_language": None, "session": session, **fields}


def _context_setup(language, model, information, rules, context, overlay_store, source, query,
                   graph_program, budget, trace_limit, max_steps):
    raw_view, context_id, context_sources, context_meta = _live_context(context, source)
    overlay = _overlay_identity(overlay_store)
    markers = _markers(language)
    limits = {"budget": budget, "trace_limit": trace_limit, "max_steps": max_steps}
    pins = {"graph": _digest(graph_program), "language": _digest(language), "model": _digest(model),
            "information_program": _digest(information), "rules": _digest(rules), "markers": markers,
            "source": _digest(source), "query": _digest(query), "context": context_meta,
            "overlay": overlay, "limits": limits, "source_caller_attested": True}
    ground = _bridge(language, model, information, rules, context_sources, query, context_id,
                     max_steps=max_steps, budget=budget, trace_limit=trace_limit)
    facts = _verified_context_facts(ground, context_sources)
    return raw_view, context_id, context_sources, context_meta, overlay, markers, pins, ground, facts


def _question(program, source, model, markers, pins, decomposition, candidates, proofs,
              conflicts, budget, trace_limit, saved_receipt=None):
    base_pins = _json(pins)
    pinned_qid = base_pins.pop("question_id", None)
    qid = _question_id(source, base_pins, decomposition, candidates)
    if pinned_qid is not None and pinned_qid != qid:
        raise ValueError("question_id_pin")
    inputs = {"mode": "clarify", "decomposition": decomposition, "candidates": candidates,
              "context_conflicts": conflicts, "question_id": qid, "state": None}
    out, receipt = (_run_vm(program, inputs, budget, trace_limit) if saved_receipt is None else
                    (_verify_vm(program, inputs, saved_receipt, budget, trace_limit), _json(saved_receipt)))
    if (type(out) is not dict or out.keys() != {"status", "reason", "question", "candidates"}
            or out.get("status") != "clarify"
            or out.get("reason") != "clarification_required" or type(out.get("question")) is not dict
            or type(out.get("candidates")) is not list):
        raise ValueError("clarify_output")
    question = out["question"]
    choices = question.get("choices")
    if (question.get("question_id") != qid or not _text(question.get("prompt"), 1024)
            or type(choices) is not list or len(choices) != 6):
        raise ValueError("question_shape")
    known = {c["candidate_id"]: c for c in candidates}
    replies, choice_ids = set(), set()
    expected_order = ([c["candidate_id"] for c in candidates if c["candidate_id"] not in set(conflicts)]
                      + [c["candidate_id"] for c in candidates if c["candidate_id"] in set(conflicts)])
    for choice in choices:
        if (type(choice) is not dict or choice.keys() != {"candidate_id", "display_text", "reply_text",
                                                           "context_compatibility"}
                or choice["candidate_id"] not in known or choice["display_text"] != known[choice["candidate_id"]]["display_text"]
                or choice["context_compatibility"] != ("conflict" if choice["candidate_id"] in conflicts else "unknown")
                or not _text(choice["reply_text"], 1024) or choice["reply_text"] in replies):
            raise ValueError("question_choice")
        replies.add(choice["reply_text"])
        choice_ids.add(choice["candidate_id"])
    returned = out["candidates"]
    if (choice_ids != set(known) or [c["candidate_id"] for c in choices] != expected_order
            or type(returned) is not list or len(returned) != 6
            or any(type(c) is not dict or c.get("candidate_id") not in known
                   or c != known[c["candidate_id"]] for c in returned)
            or [c["candidate_id"] for c in returned] != expected_order):
        raise ValueError("question_candidates")
    return qid, _json(inputs), receipt, _json(question), _json(out["candidates"])


def _pending_session(pins, source, query, context_meta, ground, decompose_runs, decomposition,
                     candidates, proofs, conflicts, clarify_input, clarify_receipt, question,
                     ordered_candidates, proposal):
    return {"schema": SESSION_SCHEMA, "status": "pending", "pins": _json(pins),
            "source": _json(source), "query": _json(query), "context": _json(context_meta),
            "context_grounding": _json(ground["session"]),
            "graph": {"decompose_runs": _json(decompose_runs), "decomposition": _json(decomposition),
                      "candidates": _json(candidates), "proofs": _json(proofs),
                      "context_conflicts": _json(conflicts), "clarify_input": _json(clarify_input),
                      "clarify_receipt": _json(clarify_receipt), "question": _json(question),
                      "ordered_candidates": _json(ordered_candidates)},
            "overlay": {"question": _json(proposal), "confirmation": None},
            "reply": None, "ground_language": None}


def _reply_selection(reply, question, pins, source, query, *, saved=False):
    keys = {"question_id", "source", "caller_attested"} | ({"candidate_id"} if saved else set())
    if (type(reply) is not dict or reply.keys() != keys or reply.get("caller_attested") is not True
            or reply.get("question_id") != pins["question_id"]):
        raise ValueError("reply_shape")
    answer = _source(reply["source"])
    forbidden_ids = {source["id"], query["id"], *pins["context"]["observation_ids"]}
    if answer["id"] in forbidden_ids:
        raise ValueError("reply_source_duplicate")
    matches = [choice for choice in question["choices"] if choice["reply_text"] == answer["text"]]
    if len(matches) != 1 or (saved and reply["candidate_id"] != matches[0]["candidate_id"]):
        raise ValueError("reply_not_exact_choice")
    return answer, matches[0]["candidate_id"]


def _validate_saved(session, program, language, model, information, rules, context_id, sources,
                    source, query, pins, facts, overlay_store, budget, trace_limit, max_steps):
    pending = {"schema", "status", "pins", "source", "query", "context", "context_grounding",
               "graph", "overlay", "reply", "ground_language"}
    confirmed = pending | {"selected_candidate_id", "selected_meaning", "grounding_proof"}
    if (type(session) is not dict or set(session.keys()) not in (pending, confirmed)
            or session["schema"] != SESSION_SCHEMA or session["status"] not in ("pending", "confirmed")
            or session["source"] != source or session["query"] != query
            or (session["status"] == "pending" and session.keys() != pending)
            or (session["status"] == "confirmed" and session.keys() != confirmed)):
        raise ValueError("session_pins")
    graph_keys = {"decompose_runs", "decomposition", "candidates", "proofs", "context_conflicts",
                  "clarify_input", "clarify_receipt", "question", "ordered_candidates"}
    if (type(session.get("graph")) is not dict or session["graph"].keys() != graph_keys
            or (session["status"] == "pending" and session.get("ground_language") is not None)
            or (session["status"] == "confirmed" and type(session.get("ground_language")) is not dict)):
        raise ValueError("session_shape")
    saved_pins = _json(session["pins"])
    saved_qid = saved_pins.pop("question_id", None)
    if (saved_pins != pins or session["context"] != pins["context"]
            or session["source"] != source or _digest(session["source"]) != pins["source"]
            or _digest(session["query"]) != pins["query"]):
        raise ValueError("session_pins")
    bridge = _bridge(language, model, information, rules, sources, query, context_id,
                     session=session["context_grounding"], max_steps=max_steps,
                     budget=budget, trace_limit=trace_limit)
    if bridge.get("session") is None:
        raise ValueError("context_grounding_replay")
    replay_facts = _verified_context_facts(bridge, sources)
    if replay_facts != facts or _digest(bridge["session"]) != _digest(session["context_grounding"]):
        raise ValueError("context_grounding_mismatch")
    graph = session["graph"]
    final, runs, held_reason = _decompose(program, session["source"], model, pins["markers"],
                                          budget, trace_limit, max_steps, graph.get("decompose_runs"))
    if final is None or held_reason:
        raise ValueError("decomposition_replay")
    decomposition, candidates = _validate_decomposition(final, session["source"], model, pins["markers"])
    qid = _question_id(source, pins, decomposition, candidates)
    if saved_qid != qid:
        raise ValueError("question_id_pin")
    pins = _json(pins)
    pins["question_id"] = qid
    proofs, conflicts = _proofs(candidates, facts, rules)
    if graph.get("decomposition") != decomposition or graph.get("candidates") != candidates \
            or graph.get("proofs") != proofs or graph.get("context_conflicts") != conflicts:
        raise ValueError("context_proof_pins")
    qid, clarify_input, clarify_receipt, question, ordered = _question(
        program, session["source"], model, pins["markers"], pins, decomposition, candidates, proofs,
        conflicts, budget, trace_limit, graph.get("clarify_receipt"))
    if (graph.get("clarify_input") != clarify_input or graph.get("question") != question
            or graph.get("ordered_candidates") != ordered or pins.get("question_id") != qid):
        raise ValueError("question_pins")
    proposal = _overlay_request(overlay_store, pins, session["source"], query, pins["context"],
                               decomposition, candidates, proofs, question, qid,
                               graph["decompose_runs"], graph["clarify_receipt"])
    stored_overlay = session.get("overlay")
    if (type(stored_overlay) is not dict or stored_overlay.keys() != {"question", "confirmation"}
            or stored_overlay.get("question") != proposal):
        raise ValueError("overlay_session_pins")
    _candidate_matches(overlay_store, proposal, pins["overlay"])
    selected, confirmation = None, None
    if session["status"] == "pending":
        if session.get("reply") is not None or stored_overlay.get("confirmation") is not None:
            raise ValueError("pending_reply_shape")
    else:
        answer, selected_id = _reply_selection(session.get("reply"), question, pins,
                                               session["source"], query, saved=True)
        selected = next(c for c in candidates if c["candidate_id"] == selected_id)
        if (session.get("selected_candidate_id") != selected_id
                or session.get("selected_meaning") != selected["proposed_meaning"]):
            raise ValueError("selected_meaning_pin")
        confirmation = _confirmation_request(pins, proposal, session["source"], query,
                                             answer, selected, question)
        if stored_overlay.get("confirmation") != confirmation:
            raise ValueError("confirmation_session_pins")
        _candidate_matches(overlay_store, confirmation, pins["overlay"])
        proof = session.get("grounding_proof")
        if proof is not None and (type(proof) is not dict or proof.keys() != {"record", "verification"}):
            raise ValueError("grounding_proof_shape")
    return session, bridge, candidates, decomposition, question, proposal, selected, confirmation


def _meaning_model(model, decomposition, candidate):
    meaning = candidate["proposed_meaning"]
    pattern = next((p for p in model["patterns"] if p["id"] == candidate["seed_pattern_id"]), None)
    if pattern is None or pattern["kind"] != "fact" or pattern["relation"] != meaning["triple"][1] \
            or pattern["polarity"] is not meaning["polarity"]:
        raise ValueError("selected_candidate")
    updated = _json(model)
    pid = "ctxp_" + hashlib.sha256((candidate["candidate_id"] + decomposition["unknown_surface"]).encode("utf-8")).hexdigest()[:28]
    if any(p["id"] == pid for p in updated["patterns"]) or len(updated["patterns"]) >= 12:
        raise ValueError("ephemeral_pattern_limit")
    template = decomposition["template"]
    updated["patterns"].append({"id": pid, "kind": "fact", "relation": meaning["triple"][1],
                                 "polarity": meaning["polarity"], "prefix": template["prefix"],
                                 "between": template["between"], "suffix": template["suffix"]})
    return updated, meaning


def _finish(language, model, information, rules, sources, query, context_id, session,
            selected, budget, trace_limit, max_steps, replay=False):
    updated, meaning = _meaning_model(model, session["graph"]["decomposition"], selected)
    statements = list(sources)
    if not any(x["id"] == session["source"]["id"] for x in statements):
        statements.append(session["source"])
    result = _bridge(language, updated, information, rules, statements, query, context_id,
                     session=session["ground_language"] if replay else None,
                     max_steps=max_steps, budget=budget, trace_limit=trace_limit)
    if result.get("session") is None:
        raise ValueError("meaning_grounding")
    _verified_context_facts(result, statements)
    work = result.get("information_work")
    if type(work) is not dict or type(work.get("facts")) is not list:
        raise ValueError("meaning_work")
    if not any((f.get("evidence", {}).get("source_id") == session["source"]["id"]
                and f.get("evidence", {}).get("sha256") == session["source"]["sha256"]
                and f.get("evidence", {}).get("caller_attested") is True) for f in work["facts"]):
        raise ValueError("original_source_not_grounded")
    record, target = work.get("goal_record"), work.get("goal")
    proof = None
    if type(record) is dict:
        verification = verify_proof_graph(record, work["facts"], rules, target)
        if type(verification) is not dict or verification.get("valid") is not True:
            raise ValueError("meaning_proof")
        proof = {"record": _json(record), "verification": _json(verification)}
    elif result.get("status") == "confirmed":
        raise ValueError("confirmed_without_proof")
    if result.get("status") == "confirmed" and proof["verification"].get("conclusion_verified") is not True:
        raise ValueError("meaning_proof")
    if replay and session.get("grounding_proof") != proof:
        raise ValueError("grounding_proof_mismatch")
    updated_session = _json(session)
    updated_session.update({"status": "confirmed", "reply": _json(session["reply"]),
                            "ground_language": _json(result["session"]),
                            "selected_candidate_id": selected["candidate_id"],
                            "selected_meaning": _json(meaning),
                            "grounding_proof": proof})
    confirmation_id = updated_session["overlay"]["confirmation"]["candidate_id"]
    return _output("scoped" if result.get("status") == "confirmed" else "held",
                   "meaning_scoped" if result.get("status") == "confirmed" else "ground_language_" + str(result.get("status")),
                   updated_session, selected_candidate_id=selected["candidate_id"],
                   selected_meaning=_json(meaning), ground_language=_json(result),
                   overlay_candidate_id=updated_session["overlay"]["question"]["candidate_id"],
                   confirmation_candidate_id=confirmation_id)


def advance_contextual_meaning(graph_program, language_program, model, information_program, rules,
                               context, overlay_store, unknown_source, query, *, session=None, reply=None,
                               budget=4096, trace_limit=256, max_steps=128):
    """Issue/replay a six-choice clarification for a caller-attested unknown source.

    The supplied Context and OverlayStore are live owners. This function reads
    the context owner's raw source and ledger view, reparses those sources for
    this graph scope, writes pending proposals, and returns evidence.
    `unknown_source` must explicitly be `{source: {id,text,sha256}, caller_attested: True}`;
    this records caller attribution and does not authenticate the source or establish truth.
    """
    try:
        if (type(budget) is not int or budget != 4096 or type(trace_limit) is not int
                or trace_limit != 256 or type(max_steps) is not int or not 1 <= max_steps <= 128):
            raise ValueError("fixed_limits")
        if (type(unknown_source) is not dict or unknown_source.keys() != {"source", "caller_attested"}
                or unknown_source.get("caller_attested") is not True):
            raise ValueError("source_attestation_required")
        source, query = _source(unknown_source["source"]), _source(query)
        if source["id"] == query["id"]:
            raise ValueError("source_id_collision")
        model = _model(model)
        graph_program = validate_value(_json(graph_program))
        language_program = validate_value(_json(language_program))
        information_program = validate_value(_json(information_program))
        rules = validate_value(_json(rules))
        setup = _context_setup(language_program, model, information_program, rules, context,
                               overlay_store, source, query, graph_program, budget, trace_limit, max_steps)
        raw_view, context_id, sources, context_meta, overlay, markers, pins, context_ground, facts = setup
        context_ids = set(context_meta["observation_ids"])
        if query["id"] in context_ids or any(source_row["id"] == query["id"] for source_row in sources):
            raise ValueError("query_source_id_collision")

        # The current parser owns all recognized fact and query forms. It gets first refusal.
        as_query = _bridge(language_program, model, information_program, rules, [], source, context_id,
                           max_steps=max_steps, budget=budget, trace_limit=trace_limit)
        if as_query.get("session") is not None:
            return _output("held", "known_query")
        known = _bridge(language_program, model, information_program, rules,
                        sources + [source], query, context_id, max_steps=max_steps,
                        budget=budget, trace_limit=trace_limit)
        if known.get("session") is not None:
            return _output("baseline", "known_source", baseline_result=_json(known))

        if session is None:
            if reply is not None:
                raise ValueError("reply_without_session")
            final, runs, held_reason = _decompose(graph_program, source, model, markers,
                                                  budget, trace_limit, max_steps)
            if final is None:
                return _output("held", "graph_" + str(held_reason))
            decomposition, candidates = _validate_decomposition(final, source, model, markers)
            proofs, conflicts = _proofs(candidates, facts, rules)
            qid = _question_id(source, pins, decomposition, candidates)
            pins = _json(pins)
            pins["question_id"] = qid
            qid, clarify_input, clarify_receipt, question, ordered = _question(
                graph_program, source, model, markers, pins, decomposition, candidates, proofs,
                conflicts, budget, trace_limit)
            proposal = _overlay_request(overlay_store, pins, source, query, context_meta,
                                       decomposition, candidates, proofs, question, qid, runs,
                                       clarify_receipt)
            _propose(overlay_store, proposal, overlay)
            ses = _pending_session(pins, source, query, context_meta, context_ground, runs,
                                   decomposition, candidates, proofs, conflicts, clarify_input,
                                   clarify_receipt, question, ordered, proposal)
        else:
            ses, _, candidates, decomposition, question, proposal, selected, confirmation = _validate_saved(
                session, graph_program, language_program, model, information_program, rules,
                context_id, sources, source, query, pins, facts, overlay_store,
                budget, trace_limit, max_steps)
            pins = _json(ses["pins"])
            if ses["status"] == "confirmed":
                if reply is not None:
                    answer, selected_id = _reply_selection(reply, question, pins,
                                                           ses["source"], query, saved=False)
                    if answer != ses["reply"]["source"] or selected_id != ses["selected_candidate_id"]:
                        raise ValueError("reply_already_bound")
                # Replay the saved language session through the same bridge and current inputs.
                return _finish(language_program, model, information_program, rules, sources, query,
                               context_id, ses, selected, budget, trace_limit, max_steps, replay=True)
            if reply is None:
                return _output("clarify", "clarification_required", ses, question=question,
                               candidates=ses["graph"]["ordered_candidates"],
                               overlay_candidate_id=proposal["candidate_id"])

        if reply is None:
            return _output("clarify", "clarification_required", ses, question=question,
                           candidates=ses["graph"]["ordered_candidates"],
                           overlay_candidate_id=proposal["candidate_id"])
        try:
            answer, selected_id = _reply_selection(reply, question, pins, source, query)
        except _ERRORS:
            return _output("clarify", "reply_rejected", ses, question=question,
                           candidates=ses["graph"]["ordered_candidates"],
                           overlay_candidate_id=proposal["candidate_id"])
        selected = next(c for c in candidates if c["candidate_id"] == selected_id)
        ses = _json(ses)
        ses["reply"] = {"question_id": pins["question_id"], "source": answer,
                        "caller_attested": True, "candidate_id": selected_id}
        confirmation = _confirmation_request(pins, proposal, source, query, answer, selected, question)
        _propose(overlay_store, confirmation, pins["overlay"])
        ses["overlay"]["confirmation"] = _json(confirmation)
        return _finish(language_program, model, information_program, rules, sources, query,
                       context_id, ses, selected, budget, trace_limit, max_steps)
    except _ERRORS as exc:
        return _output("held", "invalid_input:" + str(exc)[:96], session if type(session) is dict else None)
    except Exception as exc:
        return _output("held", "host_error:" + type(exc).__name__)
