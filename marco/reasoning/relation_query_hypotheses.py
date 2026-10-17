"""Pure connection of graph-linked L1 query readings to the unchanged hypothesis evaluator.

Groups genuine L1 readings by their whole virtual record and retains each complete native
evaluation. Structure mapping only: no parsing, answers, ranking or world combination.
"""

import re
from copy import deepcopy

from marco.reasoning.relation_hypotheses import (
    evaluate_relation_hypotheses, _valid_json, _canonical, _safe_echo, _safe_source_echo)
from marco.language.relation_hypotheses import (
    _native_parser, _check_binding, _check_projection, _sha, _Refuse)

_SCHEMA = "relation-query-hypothesis-evaluation-v1"
_QUERY_SCHEMA = "marco-relation-query-proposal-v1"
_MAX_READINGS = 16
_MAX_GAPS = 64
_OUTPUT_LIMIT = 1048576
_SOURCE_CHARS = 512
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_TOP_KEYS = {"schema", "binding", "source", "considered_candidates", "readings", "gaps"}
_READING_KEYS = {"id", "candidate_id", "policy_index", "frame_index", "query_index",
                 "unknown_span", "transformation", "virtual_record", "original_spans",
                 "query_ref", "association_source"}
_TRANSFORM_KEYS = {"original_span", "original_text", "replacement", "virtual_source",
                   "virtual_span", "offset_delta"}
_RECORD_KEYS = {"source", "parsed", "source_ref"}
_SPAN_KEYS = {"source", "virtual_source", "scope", "predicate", "known_slot",
              "fixed_literals", "terminal", "coverage", "native_record", "native_entry_span"}
_L1_GAP_KEYS = {"reason", "candidate_id", "policy_index", "frame_index", "query_index", "span"}
_NATIVE_ERRORS = (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError)


class _Stop(Exception):
    pass


def _int(value):
    return type(value) is int


def _hex(value):
    return type(value) is str and _HEX64.match(value) is not None


def _same(left, right):
    try:
        return _canonical(left) == _canonical(right)
    except (TypeError, ValueError, RecursionError):
        return False


def _span(value, limit):
    return (type(value) is list and len(value) == 2 and all(_int(v) for v in value)
            and 0 <= value[0] < value[1] <= limit)


def _wrapper_gap(reason, reading_id=None, candidate_id=None, group_id=None):
    return {"reason": reason, "reading_id": reading_id, "candidate_id": candidate_id,
            "group_id": group_id}


def _size_ok(result):
    try:
        return len(_canonical(result).encode("utf-8")) <= _OUTPUT_LIMIT
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        return False


def _assemble(binding, source, considered, query_proposal, groups, refs, gaps):
    return {"schema": _SCHEMA, "binding": binding, "source": source,
            "considered_candidates": considered, "query_proposal": query_proposal,
            "groups": groups, "reading_refs": refs, "gaps": gaps}


def _refusal(reason, binding_echo, source_echo, considered, query_echo):
    result = _assemble(binding_echo, source_echo, considered, query_echo, [], [],
                       [_wrapper_gap(reason)])
    if not _size_ok(result):
        result["query_proposal"] = None
    return result


def _candidate_summaries(proposal):
    if type(proposal) is not dict or set(proposal) != {"source", "binding", "candidates", "gaps"}:
        raise _Stop
    candidates = proposal["candidates"]
    if type(candidates) is not list or len(candidates) > _MAX_READINGS:
        raise _Stop
    rows, seen = [], set()
    for cand in candidates:
        if type(cand) is not dict:
            raise _Stop
        cid = cand.get("id")
        if not _hex(cid) or cid in seen or not _int(cand.get("policy_index")) \
                or not _int(cand.get("frame_index")):
            raise _Stop
        seen.add(cid)
        rows.append({"candidate_id": cid, "policy_index": cand["policy_index"],
                     "frame_index": cand["frame_index"]})
    return rows


def _check_l1_gaps(gaps):
    if type(gaps) is not list or len(gaps) > _MAX_GAPS:
        raise _Stop
    for gap in gaps:
        if type(gap) is not dict or set(gap) != _L1_GAP_KEYS or type(gap["reason"]) is not str:
            raise _Stop
        if gap["candidate_id"] is not None and type(gap["candidate_id"]) is not str:
            raise _Stop
        for key in ("policy_index", "frame_index", "query_index"):
            if gap[key] is not None and not _int(gap[key]):
                raise _Stop
        span = gap["span"]
        if span is not None and not (type(span) is list and all(_int(v) for v in span)):
            raise _Stop


def _association(projection, reading):
    rows = projection.get("relation_hypothesis_queries")
    if type(rows) is not list:
        raise _Stop
    found = [row for row in rows if type(row) is dict
             and row.get("policy_index") == reading["policy_index"]
             and row.get("frame_index") == reading["frame_index"]
             and row.get("query_index") == reading["query_index"]]
    if len(found) != 1:
        raise _Stop
    return found[0]


def _check_reading(reading, source, considered_by_id, seen_ids, binding, projection):
    if type(reading) is not dict or set(reading) != _READING_KEYS:
        raise _Stop
    rid, cid = reading["id"], reading["candidate_id"]
    if not _hex(rid) or rid in seen_ids or not _hex(cid) or cid not in considered_by_id:
        raise _Stop
    seen_ids.add(rid)
    row = considered_by_id[cid]
    if reading["policy_index"] != row["policy_index"] or not _int(reading["policy_index"]) \
            or reading["frame_index"] != row["frame_index"] or not _int(reading["frame_index"]) \
            or not _int(reading["query_index"]):
        raise _Stop
    trans = reading["transformation"]
    if type(trans) is not dict or set(trans) != _TRANSFORM_KEYS:
        raise _Stop
    n = len(source)
    if not _span(trans["original_span"], n) or not _span(reading["unknown_span"], n) \
            or reading["unknown_span"] != trans["original_span"]:
        raise _Stop
    a, b = trans["original_span"]
    assoc = _association(projection, reading)
    predicate = assoc.get("predicate")
    replacement = predicate.get("text") if type(predicate) is dict else None
    if type(replacement) is not str or trans["original_text"] != source[a:b] \
            or trans["replacement"] != replacement \
            or trans["virtual_source"] != source[:a] + replacement + source[b:]:
        raise _Stop
    vspan = trans["virtual_span"]
    if type(vspan) is not list or len(vspan) != 2 or not all(_int(v) for v in vspan) \
            or vspan != [a, a + len(replacement)] \
            or not _int(trans["offset_delta"]) \
            or trans["offset_delta"] != len(replacement) - (b - a):
        raise _Stop
    if not _same(reading["query_ref"], assoc.get("query_ref")) \
            or not _same(reading["association_source"], assoc.get("association_source")):
        raise _Stop
    record = reading["virtual_record"]
    if type(record) is not dict or set(record) != _RECORD_KEYS \
            or record["source"] != trans["virtual_source"] \
            or not _same(record["source_ref"], reading["query_ref"]):
        raise _Stop
    if type(reading["original_spans"]) is not dict or set(reading["original_spans"]) != _SPAN_KEYS:
        raise _Stop
    want = _sha({"binding": binding, "projection_fingerprint": projection["fingerprint"],
                 "candidate_id": cid, "association": assoc, "source": source,
                 "transformation": trans})
    if rid != want:
        raise _Stop


def _link(query_proposal, proposal, projection, binding):
    """Return (considered rows, readings) after minimal typed linkage; _Stop when malformed."""
    summaries = _candidate_summaries(proposal)
    considered = query_proposal["considered_candidates"]
    if not _same(considered, summaries):
        raise _Stop
    return summaries, considered


def _check_linkage(query_proposal, proposal, projection, binding, summaries):
    source = query_proposal["source"]
    readings = query_proposal["readings"]
    _check_l1_gaps(query_proposal["gaps"])
    if source is None:
        if readings or not query_proposal["gaps"]:
            raise _Stop
    else:
        if type(source) is not str or len(source) > _SOURCE_CHARS:
            raise _Stop
        try:
            source.encode("utf-8")
        except UnicodeEncodeError:
            raise _Stop
    by_id = {row["candidate_id"]: row for row in summaries}
    seen = set()
    for reading in readings:
        _check_reading(reading, source, by_id, seen, binding, projection)


def evaluate_relation_query_hypotheses(parser, context_snapshot, proposal, query_proposal, *,
                                       projection, binding):
    if not _native_parser(parser) or any(
            type(v) is not dict
            for v in (context_snapshot, proposal, query_proposal, projection, binding)):
        raise ValueError("relation_query_evaluation_invalid_argument")

    if not (_valid_json(context_snapshot, byte_limit=262144)
            and _valid_json(proposal, byte_limit=262144)
            and _valid_json(binding, byte_limit=65536)
            and _valid_json(projection, byte_limit=1048576)
            and _valid_json(query_proposal, byte_limit=1048576)
            and _valid_json([context_snapshot, proposal, query_proposal, projection, binding],
                            byte_limit=2097152)):
        return _refusal("input_invalid", _safe_echo(binding), _safe_source_echo(proposal), [], None)

    binding_echo = _safe_echo(binding)
    source_echo = _safe_source_echo(proposal)
    query_echo = _safe_echo(query_proposal)

    try:
        _check_binding(binding, parser)
        _check_projection(parser, projection)
    except _Refuse as refusal:
        return _refusal(str(refusal), binding_echo, source_echo, [], query_echo)

    considered_echo = []
    try:
        if set(query_proposal) != _TOP_KEYS or query_proposal["schema"] != _QUERY_SCHEMA \
                or not _same(query_proposal["binding"], binding) \
                or type(query_proposal["readings"]) is not list:
            raise _Stop
        readings = query_proposal["readings"]
        if len(readings) > _MAX_READINGS:
            return _refusal("work_limit", binding_echo, source_echo, [], query_echo)
        summaries, considered = _link(query_proposal, proposal, projection, binding)
        considered_echo = deepcopy(considered)
        _check_linkage(query_proposal, proposal, projection, binding, summaries)
    except (_Stop, KeyError, TypeError, AttributeError):
        return _refusal("query_proposal_invalid", binding_echo, source_echo, considered_echo,
                        query_echo)

    gaps = []
    groups, group_of = [], {}
    for reading in readings:
        record = reading["virtual_record"]
        key = _canonical(record)
        if key not in group_of:
            group_of[key] = len(groups)
            groups.append({"id": _sha({"binding": binding,
                                       "projection_fingerprint": projection["fingerprint"],
                                       "query_record": record}),
                           "query_record": deepcopy(record), "evaluation": None})
    if len(groups) > _MAX_READINGS:
        return _refusal("work_limit", binding_echo, source_echo, considered_echo, query_echo)

    for group in groups:
        try:
            group["evaluation"] = evaluate_relation_hypotheses(
                parser, deepcopy(context_snapshot), deepcopy(proposal),
                deepcopy(group["query_record"]),
                projection=deepcopy(projection), binding=deepcopy(binding))
        except _NATIVE_ERRORS:
            group["evaluation"] = None
            gaps.append(_wrapper_gap("native_evaluation_error", group_id=group["id"]))

    refs = []
    for reading in readings:
        group = groups[group_of[_canonical(reading["virtual_record"])]]
        cid = reading["candidate_id"]
        evaluation = group["evaluation"]
        outcomes = evaluation.get("outcomes") if type(evaluation) is dict else None
        hits = [i for i, o in enumerate(outcomes) if type(o) is dict
                and o.get("candidate_id") == cid] if type(outcomes) is list else []
        if len(hits) == 1:
            refs.append({"reading_id": reading["id"], "candidate_id": cid,
                         "group_id": group["id"], "outcome_index": hits[0],
                         "status": "mapped"})
        else:
            refs.append({"reading_id": reading["id"], "candidate_id": cid,
                         "group_id": group["id"], "outcome_index": None,
                         "status": "unmapped"})
            gaps.append(_wrapper_gap("candidate_mapping_unavailable", reading["id"], cid,
                                     group["id"]))

    if len(gaps) > _MAX_GAPS:
        return _refusal("gap_limit", binding_echo, source_echo, considered_echo, query_echo)
    result = _assemble(binding_echo, source_echo, considered_echo, deepcopy(query_proposal),
                       groups, refs, gaps)
    if not _size_ok(result):
        return _refusal("output_limit", binding_echo, source_echo, considered_echo, query_echo)
    return result
