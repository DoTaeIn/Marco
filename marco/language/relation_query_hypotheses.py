"""First pure L1 unknown-query helper (marco-relation-query-proposal-v1).

Pure, detached, no IO: given an accepted original assertion proposal, enumerate virtual query
readings of ``query_text`` in which the original unknown expression is replaced by the linked
query predicate, witnessed only by the unchanged native parser on a private clone.
"""
import math
import re
from copy import deepcopy

from marco.language.relation_hypotheses import (_Refuse, _check_binding, _check_projection,
                                                _native_parser, _question_marks, _remap, _sha,
                                                _units, propose_relation_hypotheses)
from marco.storage.overlay import dumps
from relational_semantics import substitute

SCHEMA = "marco-relation-query-proposal-v1"
_MAX_SOURCE, _MAX_WORDS, _MAX_UNITS = 512, 40, 40
_MAX_DEPTH, _MAX_VISITS = 32, 50000
_MAX_BINDING, _MAX_PROPOSAL, _MAX_PROJECTION, _MAX_COMBINED = 65536, 262144, 1048576, 2097152
_MAX_CANDIDATES, _MAX_ASSOC, _MAX_WORK, _MAX_GAPS, _MAX_OUTPUT = 16, 16, 640, 64, 1048576
_ROW_KEYS = {"policy_index", "frame_index", "query_index", "query_ref", "predicate", "known_slot",
             "roles", "terminal", "association_source"}
_CAPSULE_KEYS = {"graph_id", "root_id", "rule_id", "sense_id", "effective_graph_sha256",
                 "view_key", "nodes", "edges"}
_IDENT = ("graph_id", "root_id", "effective_graph_sha256", "view_key")
_ORIGIN_CODES = {"origin_unavailable", "origin_unknown", "binding_unknown", "origin_invalid",
                 "origin_alignment_invalid", "origin_index_unavailable"}
_PARSE_ERRORS = (ValueError, TypeError, KeyError, IndexError, AttributeError, RecursionError,
                 re.error)
_AUTHORITY = {"binding_invalid", "parser_binding_mismatch", "projection_invalid",
              "projection_parser_mismatch", "hypothesis_policy_unavailable"}
_SEMANTIC_KEYS = {"definitions", "events", "condition", "assumption", "reason", "correction",
                  "repair", "정의", "사건", "가정사건", "조건", "가정", "원인", "이유물음", "수선",
                  "사건정정"}


class _Gap(Exception):
    """Private control flow: an atomic or field-level named local gap."""

    def __init__(self, reason, span=None):
        super().__init__(reason)
        self.reason, self.span = reason, span


def _sint(v):
    return type(v) is int


def _span_ok(span, limit):
    return isinstance(span, list) and len(span) == 2 and all(_sint(x) for x in span) \
        and 0 <= span[0] < span[1] <= limit


def _admit(value, budget, depth=0):
    """Native finite carrier admission; budget is a one-item list of remaining visits."""
    budget[0] -= 1
    if budget[0] < 0 or depth > _MAX_DEPTH:
        raise _Gap("input_limit")
    kind = type(value)
    if value is None or kind is bool or kind is int:
        return
    if kind is float:
        if not math.isfinite(value):
            raise _Gap("input_invalid")
        return
    if kind is str:
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise _Gap("input_invalid")
        return
    if kind is list:
        for item in value:
            _admit(item, budget, depth + 1)
        return
    if kind is dict:
        for k, v in value.items():
            if type(k) is not str:
                raise _Gap("input_invalid")
            budget[0] -= 1
            if budget[0] < 0:
                raise _Gap("input_limit")
            try:
                k.encode("utf-8")
            except UnicodeEncodeError:
                raise _Gap("input_invalid")
            _admit(v, budget, depth + 1)
        return
    raise _Gap("input_invalid")


def _size(value, limit):
    try:
        n = len(dumps(value).encode("utf-8"))
    except (TypeError, ValueError):
        raise _Gap("input_invalid")
    if n > limit:
        raise _Gap("input_limit")
    return n


def _gap(reason, cid=None, pi=None, fi=None, qi=None, span=None):
    return {"reason": reason, "candidate_id": cid, "policy_index": pi, "frame_index": fi,
            "query_index": qi, "span": span}


def _out(binding, source, considered, readings, gaps):
    return {"schema": SCHEMA, "binding": deepcopy(binding), "source": source,
            "considered_candidates": considered, "readings": readings, "gaps": gaps}


def _source_limited(text, cuts):
    return not text.strip() or len(text) > _MAX_SOURCE \
        or len(re.findall(r"\S+", text)) > _MAX_WORDS or len(_units(text, cuts)) > _MAX_UNITS


def _capsule(cap, ident, top_nodes, top_edges):
    if not isinstance(cap, dict) or set(cap) != _CAPSULE_KEYS \
            or any(dumps(cap[k]) != dumps(ident[k]) for k in _IDENT) \
            or not isinstance(cap["nodes"], dict) or not isinstance(cap["edges"], dict) \
            or not isinstance(cap["rule_id"], str) or not cap["rule_id"] \
            or not isinstance(cap["sense_id"], str) or not cap["sense_id"]:
        raise _Refuse("projection_invalid")
    for sub, top in ((cap["nodes"], top_nodes), (cap["edges"], top_edges)):
        for k, v in sub.items():
            if k not in top or dumps(top[k]) != dumps(v):
                raise _Refuse("projection_invalid")
    if cap["root_id"] not in cap["nodes"] or cap["rule_id"] not in cap["nodes"] \
            or cap["sense_id"] not in cap["nodes"]:
        raise _Refuse("projection_invalid")


def _sub_capsule(sub, cap, ident, top_nodes, top_edges):
    """A policy/frame/query capsule must be an exact origin subset of the association capsule."""
    _capsule(sub, ident, top_nodes, top_edges)
    if sub["sense_id"] != cap["sense_id"]:
        raise _Refuse("projection_invalid")
    for key in ("nodes", "edges"):
        for k, v in sub[key].items():
            if k not in cap[key] or dumps(cap[key][k]) != dumps(v):
                raise _Refuse("projection_invalid")


def _associations(projection, decl, policies, candidates, marks):
    """Validate current relation_hypothesis_queries rows; returns {policy_index: row}."""
    rows = projection.get("relation_hypothesis_queries")
    if rows is None or rows == []:
        raise _Gap("query_association_unavailable")
    if not isinstance(rows, list) or len(rows) > _MAX_ASSOC:
        raise _Refuse("projection_invalid")
    data, prov = projection["data"], projection["provenance"]
    examples, count = data["examples"], decl["seed_count"]
    qsources = projection["query_sources"]
    ident = {k: prov.get(k) for k in _IDENT}
    by_policy = {}
    for c in candidates:
        by_policy.setdefault(c["policy_index"], c)
    out, last = {}, -1
    for row in rows:
        if not isinstance(row, dict) or set(row) != _ROW_KEYS:
            raise _Refuse("projection_invalid")
        pi, fi, qi = row["policy_index"], row["frame_index"], row["query_index"]
        if not _sint(pi) or not _sint(fi) or not _sint(qi) or pi <= last \
                or not 0 <= pi < len(policies) or policies[pi]["frame_index"] != fi:
            raise _Refuse("projection_invalid")
        last = pi
        cand = by_policy.get(pi)
        if cand is not None and cand["frame_index"] != fi:
            raise _Refuse("projection_invalid")
        if not count <= qi < len(examples) or qi - count >= len(qsources):
            raise _Refuse("projection_invalid")
        ann = examples[qi]
        ref = row["query_ref"]
        if not isinstance(ref, dict) or dumps(ref) != dumps(qsources[qi - count]) \
                or not _sint(ref.get("index")) or ref.get("index") != qi \
                or ref.get("annotation_sha256") != _sha(ann):
            raise _Refuse("projection_invalid")
        pred, slot, roles, term = row["predicate"], row["known_slot"], row["roles"], row["terminal"]
        if not isinstance(ann, dict) or not isinstance(ann.get("text"), str) \
                or not isinstance(ann.get("slots"), dict) or len(ann["slots"]) != 1 \
                or not isinstance(pred, dict) or set(pred) != {"text", "span"} \
                or not isinstance(slot, dict) or set(slot) != {"name", "span"} \
                or not isinstance(roles, dict) or set(roles) != {"subject_id", "object_id", "asked_id"} \
                or not all(isinstance(v, str) and v for v in roles.values()) \
                or not isinstance(term, str) or not term:
            raise _Refuse("projection_invalid")
        text = ann["text"]
        name = slot["name"]
        if not isinstance(name, str) or name not in ann["slots"] \
                or not isinstance(ann["slots"][name], str) or not ann["slots"][name] \
                or not isinstance(pred["text"], str) or not pred["text"] \
                or not _span_ok(pred["span"], len(text)) or not _span_ok(slot["span"], len(text)) \
                or text[pred["span"][0]:pred["span"][1]] != pred["text"] \
                or text[slot["span"][0]:slot["span"][1]] != ann["slots"][name]:
            raise _Refuse("projection_invalid")
        a, b = sorted([pred["span"], slot["span"]])
        if a[1] > b[0]:
            raise _Refuse("projection_invalid")
        meaning = ann.get("meaning")
        query = meaning.get("query") if isinstance(meaning, dict) else None
        if not isinstance(query, list) or len(query) != 1 or not isinstance(query[0], dict) \
                or set(query[0]) != {"triple", "render"} \
                or not isinstance(query[0]["triple"], list) or len(query[0]["triple"]) != 3 \
                or not all(isinstance(t, str) for t in query[0]["triple"]):
            raise _Refuse("projection_invalid")
        triple = query[0]["triple"]
        asked = [t for t in triple if t.startswith("?")]
        known = [t for t in triple if t == "$" + name]
        if len(asked) != 1 or len(known) != 1 or triple[1].startswith(("?", "$")) \
                or len(asked[0]) < 2 or asked[0][1:] == name or triple[0] == triple[2]:
            raise _Refuse("projection_invalid")
        if term not in marks or term in text:
            raise _Refuse("projection_invalid")
        subject_id, object_id, asked_id = roles["subject_id"], roles["object_id"], roles["asked_id"]
        if subject_id == object_id or asked_id not in (subject_id, object_id) \
                or (asked_id == subject_id) != triple[0].startswith("?"):
            raise _Refuse("projection_invalid")
        cap = row["association_source"]
        _capsule(cap, ident, prov["nodes"], prov["edges"])
        if any(i not in cap["nodes"] for i in (subject_id, object_id)):
            raise _Refuse("projection_invalid")
        qcap = ref.get("graph_source")
        _sub_capsule(qcap, cap, ident, prov["nodes"], prov["edges"])
        if any(i not in qcap["nodes"] for i in (subject_id, object_id)):
            raise _Refuse("projection_invalid")
        # B: genuine policy_source / frame.source_ref.graph_source capsules, never skipped.
        policy = policies[pi]
        frames = decl.get("frames")
        if not isinstance(policy, dict) or not isinstance(frames, list) or not 0 <= fi < count \
                or fi >= len(frames) or not isinstance(frames[fi], dict):
            raise _Refuse("projection_invalid")
        frame, fact = frames[fi], examples[fi]
        pcap, fref, pref = policy.get("policy_source"), frame.get("source_ref"), policy.get("source_ref")
        if not isinstance(fref, dict) or set(fref) != {"index", "annotation_sha256", "graph_source"} \
                or dumps(pref) != dumps(fref) or fref["index"] != fi or not _sint(fref["index"]) \
                or fref["annotation_sha256"] != _sha(fact):
            raise _Refuse("projection_invalid")
        fcap = fref["graph_source"]
        _sub_capsule(pcap, cap, ident, prov["nodes"], prov["edges"])
        _sub_capsule(fcap, cap, ident, prov["nodes"], prov["edges"])
        if fcap["rule_id"] != frame.get("id") or cap["rule_id"] != pcap["rule_id"] \
                or qcap["sense_id"] != pcap["sense_id"] or fcap["sense_id"] != pcap["sense_id"]:
            raise _Refuse("projection_invalid")
        if any(i not in fcap["nodes"] for i in (subject_id, object_id)):
            raise _Refuse("projection_invalid")
        # C: bind the selected fact's binary triple to the query triple orientation.
        fslots = fact.get("slots") if isinstance(fact, dict) else None
        fmeaning = fact.get("meaning") if isinstance(fact, dict) else None
        ftriple = fmeaning.get("triple") if isinstance(fmeaning, dict) else None
        if not isinstance(fslots, dict) or len(fslots) != 2 or not isinstance(frame.get("roles"), list) \
                or len(frame["roles"]) != 2 or not isinstance(ftriple, list) or len(ftriple) != 3 \
                or not all(isinstance(t, str) for t in ftriple) \
                or not ftriple[0].startswith("$") or not ftriple[2].startswith("$") \
                or ftriple[1] != triple[1] or ftriple[0] == ftriple[2] \
                or ftriple[0][1:] not in fslots or ftriple[2][1:] not in fslots:
            raise _Refuse("projection_invalid")
        asked_slot = asked[0][1:]
        if name not in fslots or asked_slot not in fslots or asked_slot == name:
            raise _Refuse("projection_invalid")
        known_pos = 0 if ftriple[0] == "$" + name else 2
        asked_pos = 2 - known_pos
        if ftriple[known_pos] != "$" + name or ftriple[asked_pos] != "$" + asked_slot \
                or triple[known_pos] != "$" + name or triple[asked_pos] != "?" + asked_slot:
            raise _Refuse("projection_invalid")
        out[pi] = row
    return out


def _tiles(spans, length, start=0):
    ordered = sorted(spans)
    at = start
    for x, y in ordered:
        if x != at or y <= x:
            return False
        at = y
    return at == length


def _reading(private, original, cand, row, ann, a, b, cuts):
    """One planned case; returns a reading dict or raises _Gap."""
    pred_text, pname = row["predicate"]["text"], row["known_slot"]["name"]
    lp = len(pred_text)
    virtual = original[:a] + pred_text + original[b:]
    vs, ve = a, a + lp
    delta = lp - (b - a)
    try:
        parsed = private.parse(virtual, partial=True, events=True, repair=True,
                               _entry_selection=True)
    except _PARSE_ERRORS:
        raise _Gap("unsupported_query", [a, b])
    if not isinstance(parsed, dict) or parsed.get("facts") != [] \
            or not isinstance(parsed.get("query"), list) or len(parsed["query"]) != 1:
        raise _Gap("unsupported_query", [a, b])
    for k, v in parsed.items():
        if k in _SEMANTIC_KEYS and v is not None and v != [] and v != {} and v != "":
            raise _Gap("unsupported_query", [a, b])
    q = parsed["query"][0]
    if not isinstance(q, dict) or set(q) != {"triple", "render"} \
            or not isinstance(q["triple"], list) or len(q["triple"]) != 3 \
            or not all(isinstance(t, str) for t in q["triple"]):
        raise _Gap("unsupported_query", [a, b])
    triple = q["triple"]
    if sum(t.startswith("?") for t in triple) != 1 or triple[1].startswith(("?", "$")):
        raise _Gap("unsupported_query", [a, b])
    sel = parsed.get("entry_selection")
    if not isinstance(sel, dict) or not isinstance(sel.get("items"), list) \
            or len(sel["items"]) != 1 or not isinstance(sel.get("gaps"), list):
        raise _Gap("query_selection_invalid", [a, b])
    item = sel["items"][0]
    if not isinstance(item, dict) or item.get("clause_ordinal") != 0 \
            or item.get("compiler_index") != row["query_index"] \
            or not _sint(item.get("compiler_index")) \
            or item.get("targets") != {"facts": [], "query": [0]} \
            or item.get("derivation") is not None or not _span_ok(item.get("span"), len(virtual)):
        raise _Gap("query_selection_invalid", [a, b])
    for g in sel["gaps"]:
        if not isinstance(g, dict) or g.get("clause_ordinal") not in (0, None) \
                or g.get("code") not in _ORIGIN_CODES:
            raise _Gap("query_selection_invalid", [a, b])

    # v2 whole-phase source view: strip, drop at most the ONE linked terminal, rstrip.
    lead = len(virtual) - len(virtual.lstrip())
    stripped = virtual.strip()
    end = lead + len(stripped)
    term, term_span = row["terminal"], None
    core = stripped
    if stripped.endswith(term) and len(stripped) > len(term):
        term_span = [end - len(term), end]
        core = stripped[:-len(term)].rstrip()
    else:
        term = None
    try:
        selection = private._clause_selection(core, source=virtual, phase="whole")
    except _PARSE_ERRORS:
        raise _Gap("query_selection_invalid", [a, b])
    records = selection.get("records") if isinstance(selection, dict) else None
    if not isinstance(records, dict):
        raise _Gap("query_selection_invalid", [a, b])
    hits = [r for r in records.values() if isinstance(r, dict)
            and r.get("example_index") == row["query_index"] and r.get("source") == virtual
            and r.get("annotation_sha256") == row["query_ref"]["annotation_sha256"]
            and r.get("reader_kind") == "query" and r.get("canonical") == core
            and isinstance(r.get("meaning"), dict)
            and dumps(r["meaning"].get("query")) == dumps(parsed["query"])]
    if len(hits) != 1:
        raise _Gap("query_selection_invalid", [a, b])
    rec = hits[0]
    caps, fixed = rec.get("capture_spans"), rec.get("fixed_spans")
    if rec.get("normalization") is not None or rec.get("grammar_scope") is not None \
            or not isinstance(caps, dict) or not isinstance(fixed, list):
        raise _Gap("query_alignment_unavailable", [a, b])
    if set(caps) != {pname} or not isinstance(caps[pname], dict):
        raise _Gap("query_alignment_unavailable", [a, b])
    value, cspan = caps[pname].get("value"), caps[pname].get("span")
    if not isinstance(value, str) or not value or len(value.split()) != 1 or value.isdecimal() \
            or value.startswith(("$", "?")) or not _span_ok(cspan, len(virtual)) \
            or virtual[cspan[0]:cspan[1]] != value:
        raise _Gap("query_alignment_unavailable", [a, b])
    text, seed = ann["text"], ann["slots"][pname]
    k0, k1 = row["known_slot"]["span"]
    if text[:k0] + value + text[k1:] != core:
        raise _Gap("query_alignment_unavailable", [a, b])
    shift = len(value) - len(seed)

    def to_virtual(x, y):
        # annotation coordinate -> virtual coordinate (after lead; intervals after the known
        # seed shift by the captured value width; the known slot itself takes the value width)
        if [x, y] == [k0, k1]:
            return [lead + k0, lead + k0 + len(value)]
        s = shift if x >= k1 else 0
        return [lead + x + s, lead + y + s]

    if to_virtual(k0, k1) != list(cspan):
        raise _Gap("query_alignment_unavailable", [a, b])
    p0, p1 = row["predicate"]["span"]
    if to_virtual(p0, p1) != [vs, ve] or not (ve <= cspan[0] or cspan[1] <= vs):
        raise _Gap("query_alignment_unavailable", [a, b])
    try:
        expected = substitute(deepcopy(ann["meaning"]["query"][0]), {pname: value})
    except _PARSE_ERRORS:
        raise _Gap("query_alignment_unavailable", [a, b])
    if dumps(expected) != dumps(q):
        raise _Gap("query_alignment_unavailable", [a, b])
    espan = item["span"]
    if espan not in ([lead, lead + len(core)], [lead, end]):
        raise _Gap("query_alignment_unavailable", [a, b])

    # Native once-only coverage, split at predicate/terminal boundaries, then remap.
    for f in fixed:
        if not _span_ok(f, len(virtual)):
            raise _Gap("query_alignment_unavailable", [a, b])
    if not _tiles([tuple(cspan)] + [tuple(f) for f in fixed], len(virtual)):
        raise _Gap("query_alignment_unavailable", [a, b])
    bounds = {vs, ve} | ({term_span[0], term_span[1]} if term_span else set())
    pieces = []
    for x, y in fixed:
        cut = sorted({x, y} | {c for c in bounds if x < c < y})
        pieces.extend([cut[i], cut[i + 1]] for i in range(len(cut) - 1))
    pred_pieces = [p for p in pieces if vs <= p[0] and p[1] <= ve]
    if not _tiles([tuple(p) for p in pred_pieces], ve, vs):
        raise _Gap("query_alignment_unavailable", [a, b])
    if term_span is not None:
        tp = sorted(p for p in pieces if term_span[0] <= p[0] and p[1] <= term_span[1])
        if not tp or tp[0][0] != term_span[0] or tp[-1][1] != term_span[1] \
                or any(x[1] != y[0] for x, y in zip(tp, tp[1:])):
            raise _Gap("query_alignment_unavailable", [a, b])
    rest = [p for p in pieces if not (vs <= p[0] and p[1] <= ve)]
    for p in rest:
        if p[0] < ve and p[1] > vs:
            raise _Gap("query_alignment_unavailable", [a, b])
    virt_cov = sorted([list(cspan), [vs, ve]] + rest)
    orig_cov = []
    for p in virt_cov:
        o = _remap(p, vs, ve, a, b, delta)
        if o is None or not _span_ok(o, len(original)):
            raise _Gap("query_alignment_unavailable", [a, b])
        if p != [vs, ve] and original[o[0]:o[1]] != virtual[p[0]:p[1]]:
            raise _Gap("query_alignment_unavailable", [a, b])
        orig_cov.append(o)
    if not _tiles([tuple(o) for o in orig_cov], len(original)):
        raise _Gap("query_alignment_unavailable", [a, b])
    known_orig = _remap(list(cspan), vs, ve, a, b, delta)
    terminal = None
    if term_span is not None:
        t_orig = _remap(term_span, vs, ve, a, b, delta)
        if t_orig is None or original[t_orig[0]:t_orig[1]] != term:
            raise _Gap("query_alignment_unavailable", [a, b])
        terminal = {"text": term, "original_span": t_orig, "virtual_span": term_span}
    literals = []
    at = 0
    for x, y in sorted([[p0, p1], [k0, k1]]) + [[len(text), len(text)]]:
        if x > at:
            v = to_virtual(at, x)
            o = _remap(v, vs, ve, a, b, delta)
            piece = text[at:x]
            if o is None or virtual[v[0]:v[1]] != piece or original[o[0]:o[1]] != piece:
                raise _Gap("query_alignment_unavailable", [a, b])
            literals.append({"annotation_span": [at, x], "original_span": o, "virtual_span": v,
                             "text": piece})
        at = max(at, y)
    transformation = {"original_span": [a, b], "original_text": original[a:b],
                      "replacement": pred_text, "virtual_source": virtual,
                      "virtual_span": [vs, ve], "offset_delta": delta}
    original_spans = {
        "source": original, "virtual_source": virtual,
        "scope": {"original": [0, len(original)], "virtual": [0, len(virtual)]},
        "predicate": {"original_span": [a, b], "virtual_span": [vs, ve],
                      "original_text": original[a:b], "replacement": pred_text},
        "known_slot": {"name": pname, "value": value, "original_span": known_orig,
                       "virtual_span": list(cspan)},
        "fixed_literals": literals, "terminal": terminal,
        "coverage": {"original": orig_cov, "virtual": virt_cov},
        "native_record": deepcopy(rec), "native_entry_span": list(espan)}
    return {"candidate_id": cand["id"], "policy_index": cand["policy_index"],
            "frame_index": cand["frame_index"], "query_index": row["query_index"],
            "unknown_span": [a, b], "transformation": transformation,
            "virtual_record": {"source": virtual, "parsed": deepcopy(parsed),
                               "source_ref": deepcopy(row["query_ref"])},
            "original_spans": original_spans, "query_ref": deepcopy(row["query_ref"]),
            "association_source": deepcopy(row["association_source"]),
            "association_row": deepcopy(row)}


def propose_relation_query_hypotheses(parser, query_text, *, proposal, projection, binding,
                                      candidate_limit=16):
    if type(query_text) is not str or type(proposal) is not dict \
            or type(projection) is not dict or type(binding) is not dict \
            or not _native_parser(parser) or not _sint(candidate_limit) \
            or not 1 <= candidate_limit <= 16:
        raise ValueError("relation_query_hypothesis_invalid_argument")
    echo = query_text if len(query_text) <= _MAX_SOURCE else None
    # Mechanical finite admission before any canonicalization/cloning.
    try:
        try:
            query_text.encode("utf-8")
        except UnicodeEncodeError:
            echo = None
            raise _Gap("input_invalid")
        budget = [_MAX_VISITS]
        for carrier in (binding, proposal, projection):
            _admit(carrier, budget)
        total = _size(binding, _MAX_BINDING) + _size(proposal, _MAX_PROPOSAL) \
            + _size(projection, _MAX_PROJECTION)
        if total > _MAX_COMBINED:
            raise _Gap("input_limit")
    except _Gap as g:
        return _out(None, echo, [], [], [_gap(g.reason)])

    try:
        _check_binding(binding, parser)
        decl, policies = _check_projection(parser, projection)
    except _Refuse as r:
        return _out(binding, echo, [], [], [_gap(str(r))])
    except _PARSE_ERRORS:
        return _out(binding, echo, [], [], [_gap("projection_parser_mismatch")])

    source = proposal.get("source")
    if not isinstance(source, str):
        return _out(binding, echo, [], [], [_gap("proposal_mismatch")])
    try:
        derived = propose_relation_hypotheses(parser, source, projection=projection,
                                              binding=binding, candidate_limit=16)
        if not isinstance(derived, dict) or not isinstance(derived.get("gaps"), list) \
                or not isinstance(derived.get("candidates"), list):
            raise _Gap("proposal_mismatch")
        native = [g for g in derived["gaps"] if isinstance(g, dict) and g.get("reason") in _AUTHORITY]
        if native and not derived["candidates"]:
            return _out(binding, echo, [], [], [_gap(g.get("reason")) for g in native])
        if dumps(derived) != dumps(proposal):
            raise _Gap("proposal_mismatch")
    except (_Gap, ValueError, TypeError):
        return _out(binding, echo, [], [], [_gap("proposal_mismatch")])
    candidates = derived["candidates"]
    if not candidates:
        gaps = [_gap(g.get("reason"), None, g.get("policy_index"), g.get("frame_index"), None,
                     g.get("span")) for g in derived["gaps"] if isinstance(g, dict)]
        return _out(binding, echo, [], [], gaps)
    if len(candidates) > _MAX_CANDIDATES:
        return _out(binding, echo, [], [], [_gap("candidate_limit")])
    considered = [{"candidate_id": c["id"], "policy_index": c["policy_index"],
                   "frame_index": c["frame_index"]} for c in candidates]

    try:
        marks = _question_marks(parser.clause_grammar)
        cuts = set(decl["separators"]) | set(decl["terminators"]) | {q for q in marks if len(q) == 1}
    except (TypeError, AttributeError, KeyError):
        return _out(binding, echo, [], [], [_gap("projection_parser_mismatch")])
    if _source_limited(query_text, cuts):
        return _out(binding, echo, considered, [], [_gap("source_limit")])

    try:
        rows = _associations(projection, decl, policies, candidates, set(marks))
    except _Refuse as r:
        return _out(binding, echo, considered, [], [_gap(str(r))])
    except _Gap as g:
        return _out(binding, echo, considered, [], [_gap(g.reason)])
    except _PARSE_ERRORS:
        return _out(binding, echo, considered, [], [_gap("projection_invalid")])

    # Plan every case before any native call.
    units = _units(query_text, cuts)
    plan, gaps = [], []
    for c in candidates:
        row = rows.get(c["policy_index"])
        if row is None:
            gaps.append(_gap("query_association_unavailable", c["id"], c["policy_index"],
                             c["frame_index"]))
            continue
        need = c["transformation"]["original_text"]
        for i, (a, b) in enumerate(units):
            e = b
            for k in range(i, len(units)):
                if k > i:
                    if not query_text[e:units[k][0]].isspace():
                        break
                    e = units[k][1]
                if e - a > len(need):
                    break
                if e - a == len(need):
                    if query_text[a:e] == need:
                        plan.append((c, row, a, e))
                    break
    if len(plan) > _MAX_WORK:
        return _out(binding, echo, considered, [], [_gap("work_limit")])
    # Atomic preflight: any planned virtual source over the named caps refuses the whole call.
    for c, row, a, b in plan:
        if _source_limited(query_text[:a] + row["predicate"]["text"] + query_text[b:], cuts):
            return _out(binding, echo, considered, [], [_gap("source_limit")])

    private = deepcopy(parser)
    examples = projection["data"]["examples"]
    readings = []
    for c, row, a, b in plan:
        try:
            readings.append(_reading(private, query_text, c, row, examples[row["query_index"]],
                                     a, b, cuts))
        except _Gap as g:
            gaps.append(_gap(g.reason, c["id"], c["policy_index"], c["frame_index"],
                             row["query_index"], g.span))
    if len(readings) > candidate_limit:
        return _out(binding, echo, considered, [], [_gap("candidate_limit")])
    if len(gaps) > _MAX_GAPS:
        return _out(binding, echo, considered, [], [_gap("gap_limit")])
    fingerprint = projection["fingerprint"]
    for r in readings:
        r["id"] = _sha({"binding": binding, "projection_fingerprint": fingerprint,
                        "candidate_id": r["candidate_id"], "association": r["association_row"],
                        "source": query_text, "transformation": r["transformation"]})
    order = {c["id"]: i for i, c in enumerate(candidates)}
    readings.sort(key=lambda r: (order[r["candidate_id"]], r["unknown_span"][0],
                                 r["unknown_span"][1], r["query_index"]))
    readings = [{k: r[k] for k in ("id", "candidate_id", "policy_index", "frame_index",
                                   "query_index", "unknown_span", "transformation",
                                   "virtual_record", "original_spans", "query_ref",
                                   "association_source")} for r in readings]
    result = _out(binding, query_text, considered, readings, gaps)
    try:
        if len(dumps(result).encode("utf-8")) > _MAX_OUTPUT:
            raise _Gap("output_limit")
    except (_Gap, TypeError, ValueError):
        return _out(binding, echo, considered, [], [_gap("output_limit")])
    return result
