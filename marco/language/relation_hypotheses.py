"""Pure selected relation-hypothesis proposal helper (counterfactual enumeration only).

For each explicit policy and each eligible single-word span, the span is replaced on a private
string by the selected canonical predicate and the unchanged seed role binder is asked whether it
binds. Results are uncommitted assumptions, never readings, proofs or learned aliases.
"""
import hashlib
import json
import re
from copy import deepcopy

from marco.language.frames import _bind_seed_roles, _compile_seed_predicate, _compound_word_blocked
from marco.storage.overlay import dumps

_MAX_SOURCE, _MAX_WORDS, _MAX_POLICIES, _MAX_GAPS, _MAX_BINDING = 512, 40, 16, 64, 65536
_MAX_PROBES = 4096
_MAX_NODES, _MAX_EDGES = 512, 1024
_SHA_RE = re.compile(r"[0-9a-f]{64}")
_POLICY_KEYS = {"index", "frame_index", "capture", "source_ref", "policy_source"}
_CAPSULE_KEYS = {"graph_id", "root_id", "rule_id", "sense_id", "effective_graph_sha256",
                 "view_key", "nodes", "edges"}
_IDENT = ("graph_id", "root_id", "effective_graph_sha256", "view_key")
_CHECKS = ("policy_opt_in", "installed_parser_hash_match", "selected_frame_source_match",
           "exact_virtual_predicate", "original_span_preserved", "complete_source_coverage",
           "counterfactual_only")
_MATERIAL = {"ambiguous_binding", "unsupported_scope", "unsupported_question", "source_limit",
             "candidate_limit"}


class _Refuse(Exception):
    pass


def _sint(v):
    return type(v) is int


def _sha(value):
    return hashlib.sha256(dumps(value).encode("utf-8")).hexdigest()


def _gap(reason, policy=None, frame=None, span=None):
    return {"reason": reason, "policy_index": policy, "frame_index": frame, "span": span}


def _result(source, binding, candidates, gaps):
    return {"source": source, "binding": deepcopy(binding), "candidates": candidates, "gaps": gaps}


def _native_parser(parser):
    try:
        from relational_semantics import RelationalParser
    except ImportError:
        return False
    return type(parser) is RelationalParser


def _check_binding(binding, parser):
    if not isinstance(binding, dict) or binding.get("schema") != "marco-source-parser-snapshot-v1" \
            or binding.get("state_scope") != "frozen_attempt_state":
        raise _Refuse("binding_invalid")
    for key in ("selected_model", "installed_memory", "active_parser"):
        if not isinstance(binding.get(key), dict):
            raise _Refuse("binding_invalid")
    try:
        json.dumps(binding, ensure_ascii=False, sort_keys=True, allow_nan=False)
        if len(dumps(binding).encode("utf-8")) > _MAX_BINDING:
            raise _Refuse("binding_invalid")
    except (TypeError, ValueError):
        raise _Refuse("binding_invalid")
    if not isinstance(binding.get("conversation_id"), str):
        raise _Refuse("binding_invalid")
    selected, memory = binding["selected_model"], binding["installed_memory"]
    for key in ("content_fingerprint", "effective_key", "declaration_sha256", "sources_sha256",
                "base_parser_sha256"):
        if not isinstance(selected.get(key), str) or not _SHA_RE.fullmatch(selected[key]):
            raise _Refuse("binding_invalid")
    if memory.get("scope") != "installed_attempt_state_not_usage":
        raise _Refuse("binding_invalid")
    head = memory.get("head")
    if not isinstance(head, dict) or set(head) != {"seq", "change_id"}:
        raise _Refuse("binding_invalid")
    seq, change_id = head["seq"], head["change_id"]
    if not _sint(seq) or seq < 0:
        raise _Refuse("binding_invalid")
    if seq == 0:
        if change_id is not None:
            raise _Refuse("binding_invalid")
    elif not isinstance(change_id, str) or not change_id.strip():
        raise _Refuse("binding_invalid")
    if not isinstance(memory.get("base_store_sha256"), str) \
            or not _SHA_RE.fullmatch(memory["base_store_sha256"]) \
            or not isinstance(memory.get("base_build_id"), (str, type(None))):
        raise _Refuse("binding_invalid")
    want = binding["active_parser"].get("data_language_sha256")
    if not isinstance(want, str) or not _SHA_RE.fullmatch(want):
        raise _Refuse("binding_invalid")
    try:
        have = _sha({"data": parser.data, "language_pack": parser.language_pack})
    except (AttributeError, TypeError, ValueError):
        raise _Refuse("parser_binding_mismatch")
    if have != want:
        raise _Refuse("parser_binding_mismatch")


def _question_marks(grammar):
    if not isinstance(grammar, dict):
        return []
    one = grammar.get("question_mark")
    if isinstance(one, str):
        return [one]
    return list(grammar.get("question_marks") or one or [])


def _check_projection(parser, projection):
    """Return (declaration, policies) after exact projection/parser coherence checks."""
    if projection.get("schema") != "graph-dialogue-projection-v1":
        raise _Refuse("projection_invalid")
    data, pack = projection.get("data"), projection.get("language_pack")
    prov = projection.get("provenance")
    if not isinstance(data, dict) or not isinstance(pack, dict) or not isinstance(prov, dict) \
            or not isinstance(projection.get("fingerprint"), str):
        raise _Refuse("projection_invalid")
    if "relation_hypotheses" not in projection:
        raise _Refuse("hypothesis_policy_unavailable")
    if not isinstance(projection["relation_hypotheses"], list):
        raise _Refuse("projection_invalid")
    policies = projection["relation_hypotheses"]
    if not policies:
        raise _Refuse("hypothesis_policy_unavailable")
    if len(policies) > _MAX_POLICIES:
        raise _Refuse("projection_invalid")
    decl = data.get("predicate_frames")
    if not isinstance(decl, dict) or decl.get("schema") != "predicate-frames-v2" \
            or "reference_forms" in decl:
        raise _Refuse("projection_invalid")
    pdata = parser.data
    if pdata.get("predicate_frames") != decl:
        raise _Refuse("projection_parser_mismatch")
    for key in ("ignore_case", "numerals", "context_replies"):
        if data.get(key) != pdata.get(key):
            raise _Refuse("projection_parser_mismatch")
    examples, installed = data.get("examples"), pdata.get("examples")
    if not isinstance(examples, list) or not isinstance(installed, list) \
            or installed[:len(examples)] != examples:
        raise _Refuse("projection_parser_mismatch")
    clauses = pack.get("clauses")
    marks = clauses.get("question_marks") if isinstance(clauses, dict) else None
    if not isinstance(marks, list) or not all(isinstance(q, str) for q in marks):
        raise _Refuse("projection_invalid")
    try:
        if marks != _question_marks(getattr(parser, "clause_grammar", None)):
            raise _Refuse("projection_parser_mismatch")
    except (TypeError, AttributeError):
        raise _Refuse("projection_parser_mismatch")
    frames = decl.get("frames")
    if not isinstance(frames, list) or not frames or len(frames) > 16 \
            or any(not isinstance(f, dict) for f in frames):
        raise _Refuse("projection_invalid")
    ident = {k: prov.get(k) for k in _IDENT}
    if any(not isinstance(ident[k], str) or not ident[k] for k in _IDENT[:3]) \
            or not isinstance(ident["view_key"], list):
        raise _Refuse("projection_invalid")
    top_nodes, top_edges = prov.get("nodes"), prov.get("edges")
    if not isinstance(top_nodes, dict) or not isinstance(top_edges, dict) \
            or len(top_nodes) > _MAX_NODES or len(top_edges) > _MAX_EDGES \
            or not isinstance(prov.get("base_origin"), dict) \
            or not isinstance(prov.get("source"), dict) \
            or not isinstance(prov["source"].get("status"), str):
        raise _Refuse("projection_invalid")

    def capsule(cap, outer_nodes, outer_edges):
        """Exact-subset capsule check against top provenance (and an outer capsule); returns it."""
        if not isinstance(cap, dict) or set(cap) != _CAPSULE_KEYS \
                or any(cap[k] != ident[k] for k in _IDENT) \
                or not isinstance(cap["nodes"], dict) or not isinstance(cap["edges"], dict) \
                or not isinstance(cap["rule_id"], str) or not cap["rule_id"] \
                or not isinstance(cap["sense_id"], str) or not cap["sense_id"]:
            raise _Refuse("projection_invalid")
        for sub, top, outer in ((cap["nodes"], top_nodes, outer_nodes),
                                (cap["edges"], top_edges, outer_edges)):
            for k, v in sub.items():
                if k not in top or top[k] != v or (outer is not None and (k not in outer or outer[k] != v)):
                    raise _Refuse("projection_invalid")
        if cap["root_id"] not in cap["nodes"] or cap["rule_id"] not in cap["nodes"] \
                or cap["sense_id"] not in cap["nodes"]:
            raise _Refuse("projection_invalid")
        return cap

    # Seed prefix and query sources (top-level) against the installed parser.
    count = decl.get("seed_count")
    if not _sint(count) or not 1 <= count <= len(examples):
        raise _Refuse("projection_invalid")
    qsources = projection.get("query_sources")
    if not isinstance(qsources, list) or len(qsources) != len(examples) - count:
        raise _Refuse("projection_invalid")
    for i, src in enumerate(qsources):
        if not isinstance(src, dict) or set(src) != {"index", "annotation_sha256", "graph_source"} \
                or src["index"] != count + i or not _sint(src["index"]) \
                or _digest(examples[count + i]) != src["annotation_sha256"]:
            raise _Refuse("projection_invalid")
        capsule(src["graph_source"], None, None)

    seen = set()
    for pi, policy in enumerate(policies):
        if not isinstance(policy, dict) or set(policy) != _POLICY_KEYS or policy["index"] != pi \
                or not _sint(policy["index"]):
            raise _Refuse("projection_invalid")
        fi = policy["frame_index"]
        if not _sint(fi) or not 0 <= fi < len(frames) or fi in seen \
                or policy["capture"] not in ("single-word", "contiguous-words"):
            raise _Refuse("projection_invalid")
        seen.add(fi)
        frame = frames[fi]
        ref = frame.get("source_ref")
        if not isinstance(ref, dict) or policy["source_ref"] != ref \
                or set(ref) != {"index", "annotation_sha256", "graph_source"}:
            raise _Refuse("projection_invalid")
        pcap = capsule(policy["policy_source"], None, None)
        fcap = capsule(ref["graph_source"], pcap["nodes"], pcap["edges"])
        if fcap["rule_id"] != frame.get("id") or fcap["sense_id"] != pcap["sense_id"] \
                or pcap["rule_id"] == fcap["rule_id"]:
            raise _Refuse("projection_invalid")
    return decl, policies


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def _frame_eligible(rec):
    ann = rec["annotation"]
    slots, meaning = ann["slots"], ann["meaning"]
    triple = meaning["triple"]
    return len(slots) == 2 and not any(v.isdecimal() for v in slots.values()) \
        and meaning.get("polarity", True) is True \
        and meaning.get("modality", "asserted") == "asserted" \
        and all(isinstance(t, str) for t in triple)


def _units(source, cuts):
    """Maximal nonwhitespace runs split only by the given single-character cuts."""
    out = []
    for m in re.finditer(r"\S+", source):
        start = None
        for i, ch in enumerate(m.group()):
            pos = m.start() + i
            if ch in cuts:
                if start is not None:
                    out.append((start, pos))
                start = None
            elif start is None:
                start = pos
        if start is not None:
            out.append((start, m.end()))
    return out


def _remap(span, vs, ve, a, b, delta):
    if not isinstance(span, list) or len(span) != 2 or not all(_sint(x) for x in span):
        return None
    x, y = span
    if (x, y) == (vs, ve):
        return [a, b]
    if y <= vs:
        return [x, y]
    if x >= ve:
        return [x - delta, y - delta]
    return None


def _original_trace(source, trace, a, b, canon):
    def span_ok(sp, n):
        """Exact-int half-open span strictly inside [0, n]."""
        return isinstance(sp, list) and len(sp) == 2 and all(_sint(x) for x in sp) \
            and 0 <= sp[0] < sp[1] <= n

    if not isinstance(source, str) or not isinstance(trace, dict) or not isinstance(canon, str) \
            or not canon or not _sint(a) or not _sint(b) or not 0 <= a < b <= len(source):
        return None
    delta = len(canon) - (b - a)
    vlen = len(source) + delta
    vspan = trace.get("predicate_span")
    if not span_ok(vspan, vlen) or vspan != [a, a + len(canon)]:
        return None
    vs, ve = vspan
    if not isinstance(trace.get("roles"), dict) or not isinstance(trace.get("markers"), list) \
            or not isinstance(trace.get("punctuation"), list) \
            or not isinstance(trace.get("coverage"), list):
        return None

    def remap(span):
        """Validated virtual span (in-bounds, no partial predicate overlap) mapped to original."""
        if not span_ok(span, vlen):
            return None
        sp = _remap(span, vs, ve, a, b, delta)
        if sp is None or not span_ok(sp, len(source)):
            return None
        return sp

    def sl(span):
        return source[span[0]:span[1]]

    roles, markers, punct = {}, [], []
    for slot, role in trace["roles"].items():
        if not isinstance(role, dict):
            return None
        sp = remap(role.get("span"))
        if sp is None or sp == [a, b] or sl(sp) != role.get("value"):
            return None
        roles[slot] = {"value": sl(sp), "span": sp}
    for m in trace["markers"]:
        if not isinstance(m, dict):
            return None
        sp = remap(m.get("span"))
        if sp is None or sp == [a, b] or sl(sp) != m.get("text"):
            return None
        markers.append({"slot": m.get("slot"), "kind": m.get("kind"), "text": sl(sp), "span": sp})
    for p in trace["punctuation"]:
        if not isinstance(p, dict):
            return None
        sp = remap(p.get("span"))
        if sp is None or sp == [a, b] or sl(sp) != p.get("text"):
            return None
        punct.append({"kind": p.get("kind"), "text": sl(sp), "span": sp})
    coverage = []
    for c in trace["coverage"]:
        sp = remap(c)
        if sp is None:
            return None
        coverage.append(sp)
    coverage.sort()
    owned = [0] * len(source)
    for x, y in coverage:
        for i in range(x, y):
            owned[i] += 1
    if any(n > 1 for n in owned) or any(n != 1 for i, n in enumerate(owned) if not source[i].isspace()):
        return None
    return {"source": source, "predicate_span": [a, b], "roles": roles, "markers": markers,
            "punctuation": punct, "coverage": coverage, "scope": [0, len(source)]}


def propose_relation_hypotheses(parser, text, *, projection, binding, candidate_limit=16):
    if not isinstance(text, str) or not _native_parser(parser) or not isinstance(projection, dict) \
            or not isinstance(binding, dict) or not _sint(candidate_limit) \
            or not 1 <= candidate_limit <= 16:
        raise ValueError("relation_hypothesis_invalid_argument")
    try:
        _check_binding(binding, parser)
        decl, policies = _check_projection(parser, projection)
    except _Refuse as refusal:
        return _result(text, binding, [], [_gap(str(refusal))])

    # Validate the whole native declaration with the unchanged binder (validation-only, empty
    # source, private clone) before any declaration indexing or enumeration.
    private = deepcopy(parser)
    frames = decl["frames"]
    try:
        for p in policies:
            _bind_seed_roles(private, "", decl, frames[p["frame_index"]])
        compiled = [_compile_seed_predicate(private, decl, f) for f in frames]
        seps, terms = decl["separators"], decl["terminators"]
        head = re.compile(decl["head_pattern"],
                          re.IGNORECASE if private.data.get("ignore_case") else 0)
    except (ValueError, AttributeError, TypeError, KeyError, IndexError, re.error):
        return _result(text, binding, [], [_gap("projection_parser_mismatch")])
    if any(not _frame_eligible(compiled[p["frame_index"]]) for p in policies):
        return _result(text, binding, [], [_gap("projection_invalid")])
    marks = _question_marks(parser.clause_grammar)
    cuts = set(seps) | set(terms) | {q for q in marks if len(q) == 1}
    words_all = list(re.finditer(r"\S+", text))
    if not text.strip() or len(text) > _MAX_SOURCE or len(words_all) > _MAX_WORDS:
        return _result(text, binding, [], [_gap("source_limit")])

    ign = bool(private.data.get("ignore_case"))
    fold = (lambda s: s.casefold()) if ign else (lambda s: s)
    head_ok = lambda stem: head.fullmatch(stem) is not None
    protected = set()
    for c in compiled:
        for f in c["forms"]:
            protected.update(fold(w) for w in f["text"].split())
    for row in frames:
        for r in row["roles"]:
            protected.update(fold(w) for m in r["prefixes"] + r["suffixes"] for w in m.split())
    for o in decl["operators"]:
        protected.update(fold(w) for w in o.split())
    suffixes = [s for row in frames for r in row["roles"] for s in r["suffixes"]]
    units = _units(text, cuts)
    if len(units) > _MAX_WORDS:
        return _result(text, binding, [], [_gap("source_limit")])
    spans, okay = [], []
    for a, b in units:
        word = text[a:b]
        bad = word.isdecimal() or fold(word) in protected or any(q in word for q in marks) \
            or private._protected_kind(word) in ("negation", "scope", "numeral", "counter") \
            or _compound_word_blocked(private, word, suffixes, head_ok, fold)
        okay.append(not bad)
        if not bad:
            spans.append((a, b))
    windows = []
    if any(p["capture"] == "contiguous-words" for p in policies):
        qocc = []
        for q in marks:
            if q:
                at = text.find(q)
                while at != -1:
                    qocc.append((at, at + len(q)))
                    at = text.find(q, at + 1)
        n = len(units)
        link = [k + 1 < n and text[units[k][1]:units[k + 1][0]].isspace() for k in range(n)]
        prot = list(qocc)
        for i in range(n):
            for j in range(i, n):
                if j > i and not link[j - 1]:
                    break
                if private._protected_kind(text[units[i][0]:units[j][1]]) in (
                        "negation", "scope", "numeral", "counter"):
                    prot.append((units[i][0], units[j][1]))
        for i in range(n):
            for j in range(i, n):
                if j > i and not link[j - 1]:
                    break
                if not okay[j]:
                    break
                a, b = units[i][0], units[j][1]
                if any(x < b and a < y for x, y in prot):
                    continue
                windows.append((a, b))
        windows.sort()
    plans = [windows if p["capture"] == "contiguous-words" else spans for p in policies]
    if sum(len(x) for x in plans) > _MAX_PROBES:
        return _result(text, binding, [], [_gap("probe_limit")])

    found, gaps, seen_gaps = [], [], set()
    for pi, policy in enumerate(policies):
        fi = policy["frame_index"]
        frame, canon = frames[fi], compiled[fi]["canonical_predicate"]
        for a, b in plans[pi]:
            virtual = text[:a] + canon + text[b:]
            try:
                outcome = _bind_seed_roles(private, virtual, decl, frame)
            except (ValueError, AttributeError, TypeError, KeyError):
                return _result(text, binding, [], [_gap("projection_parser_mismatch")])
            if outcome[0] != "ok":
                reason = outcome[1]
                key = (reason, pi, fi, a, b)
                if reason in _MATERIAL and key not in seen_gaps and len(gaps) < _MAX_GAPS:
                    seen_gaps.add(key)
                    gaps.append(_gap(reason, pi, fi, [a, b]))
                continue
            _ok, meaning, trace = outcome
            ref = frame["source_ref"]
            if trace.get("source") != virtual or trace.get("source_ref") != ref \
                    or trace.get("frame_id") != frame["id"] \
                    or trace.get("predicate_span") != [a, a + len(canon)] \
                    or meaning.get("polarity", True) is not True \
                    or meaning.get("modality", "asserted") != "asserted":
                continue
            original = _original_trace(text, trace, a, b, canon)
            if original is None:
                continue
            transformation = {"original_span": [a, b], "original_text": text[a:b],
                              "replacement": canon, "virtual_source": virtual,
                              "virtual_span": [a, a + len(canon)],
                              "offset_delta": len(canon) - (b - a)}
            cid = _sha({"binding": binding, "projection": projection["fingerprint"],
                        "policy_index": pi, "frame_index": fi, "source": text,
                        "span": [a, b], "transformation": transformation})
            found.append({
                "id": cid, "policy_index": pi, "frame_index": fi, "unknown_span": [a, b],
                "transformation": transformation, "assumed_fact": deepcopy(meaning),
                "source_ref": deepcopy(ref), "policy_source": deepcopy(policy["policy_source"]),
                "binding_trace": {"mode": "counterfactual_existing_binder",
                                  "virtual_trace": deepcopy(trace), "original_spans": original},
                "checks": {k: True for k in _CHECKS}})
    if len(found) > candidate_limit:
        return _result(text, binding, [], [_gap("candidate_limit")] + gaps[:_MAX_GAPS - 1])
    if not found:
        return _result(text, binding, [], [_gap("no_admissible_hypothesis")] + gaps[:_MAX_GAPS - 1])
    found.sort(key=lambda c: (c["policy_index"], c["unknown_span"][0], c["unknown_span"][1]))
    return _result(text, binding, found, gaps)
