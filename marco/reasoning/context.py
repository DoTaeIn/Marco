"""Per-conversation evidence ledger, replayed rather than incrementally reapplied.

Only fully recognized user clauses enter memory. Queries and assistant replies
never become facts. Model changes reparse source text before using old evidence.
"""
from copy import deepcopy
import json
import os
import re
import uuid

from marco.reasoning.inference import current_facts
from relational_semantics import RelationalParser


def _scoped_native_eq(a, b):
    """Exact type-sensitive plain-JSON equality (bounded depth)."""
    def eq(x, y, depth):
        if depth > 32 or type(x) is not type(y):
            return False
        if type(x) is dict:
            return set(x) == set(y) and all(eq(x[k], y[k], depth + 1) for k in x)
        if type(x) is list:
            return len(x) == len(y) and all(eq(p, q, depth + 1) for p, q in zip(x, y))
        if x is None:
            return True
        return type(x) in (str, int, bool, float) and x == y
    return eq(a, b, 0)


def _scoped_canon(v):
    """Canonical V4 JSON text (sorted, compact, finite, non-ASCII kept)."""
    return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _scoped_size(v):
    """Canonical UTF-8 byte size of plain JSON, else None."""
    try:
        return len(_scoped_canon(v).encode("utf-8"))
    except (TypeError, ValueError, UnicodeEncodeError, RecursionError):
        return None


def _scoped_sha(v, limit=65536):
    """Lowercase canonical SHA-256 of bounded plain JSON, else None."""
    import hashlib
    size = _scoped_size(v)
    if size is None or size > limit:
        return None
    return hashlib.sha256(_scoped_canon(v).encode("utf-8")).hexdigest()


def _scoped_positive_meaning(meaning, triple):
    """Actual authenticated positive witness meaning for `triple`, shape preserved, else None.

    Supported shapes are {triple} and {triple, polarity}; polarity, when present, must be exactly
    bool True. An omitted polarity is kept omitted (never added).
    """
    if (type(meaning) is not dict or type(triple) is not list or len(triple) != 3
            or "triple" not in meaning or not set(meaning) <= {"triple", "polarity"}
            or not _scoped_native_eq(meaning["triple"], list(triple))):
        return None
    if "polarity" in meaning and meaning["polarity"] is not True:
        return None
    if meaning.get("polarity", True) is not True:
        return None
    return deepcopy(meaning)


def _scoped_tree_sha(v, depth=0):
    """Deterministic componentwise bounded canonical digest of plain JSON, else None.

    Components <=65536 canonical bytes hash directly; larger dict/list values hash an ordered
    manifest of their children's digests (type, key/index, order and count preserved). A
    leaf that is itself oversized, a non-plain value, or excessive depth/count fails closed.
    """
    import hashlib
    leaf = _scoped_sha(v)
    if leaf is not None:
        return "L:" + leaf
    if depth >= 8 or type(v) not in (dict, list) or len(v) > 65536:
        return None
    h = hashlib.sha256()
    h.update(_scoped_canon([type(v).__name__, len(v)]).encode("utf-8"))
    if type(v) is dict:
        if not all(type(k) is str for k in v):
            return None
        pairs = sorted(v.items())
    else:
        pairs = list(enumerate(v))
    for k, x in pairs:
        sub = _scoped_tree_sha(x, depth + 1)
        if sub is None:
            return None
        try:
            h.update(_scoped_canon([k, sub]).encode("utf-8"))
            h.update(b"\n")
        except (TypeError, ValueError, UnicodeEncodeError):
            return None
    return "T:" + type(v).__name__ + ":" + str(len(v)) + ":" + h.hexdigest()


def _scoped_authority_digest(projection, auth):
    """Compact ordered digest manifest of an already-validated own-native authority, else None."""
    if type(projection) is not dict or type(auth) is not dict:
        return None
    for group in (auth.get("frame_full"), auth.get("original_full"), auth.get("derived_full")):
        if type(group) is not list:
            return None
        sizes = [_scoped_size(r) for r in group]
        if None in sizes or any(s > 65536 for s in sizes):
            return None
    derived = auth["derived_full"]
    if len(derived) > 4 or sum(_scoped_size(r) for r in derived) > 262144:
        return None
    caps = []
    for name in ("negative_binary", "conditional_binary"):
        cap = _scoped_cap(auth, name)
        caps.append(None if cap is None else _scoped_sha(cap))
        if cap is not None and caps[-1] is None:
            return None
    parts = [_scoped_tree_sha(projection), _scoped_tree_sha(auth.get("data")), _scoped_tree_sha(auth.get("frames")),
             _scoped_tree_sha(auth["frame_full"]), _scoped_tree_sha(auth["original_full"]),
             _scoped_tree_sha(derived), _scoped_tree_sha(auth.get("question_marks"))]
    if any(p is None for p in parts) or not _scoped_hex(auth.get("scope_sha256")):
        return None
    manifest = {"schema": "scoped-authority-manifest-v1", "parts": parts,
                "counts": [len(auth["frame_full"]), len(auth["original_full"]), len(derived)],
                "caps": caps, "scope_sha256": auth["scope_sha256"]}
    return _scoped_sha(manifest)


def _scoped_plain(text):
    """Trusted str/Obs normalized once to an exact plain str (content preserved), else None."""
    if not isinstance(text, str):
        return None
    out = str.__str__(text)
    return out if type(out) is str else None


def _scoped_text(x):
    """Exact plain str or trusted Obs (str-backed) detached via str.__str__, else None (no user __str__)."""
    if type(x) is str:
        return str.__str__(x)
    if type(x) is Obs and isinstance(x, str):
        out = str.__str__(x)
        return out if type(out) is str else None
    return None


def _scoped_wire(value):
    """(True, detached string-normalized copy) of exact plain JSON, else (False, None).

    Only exact dict/list containers and None/bool/int/finite float primitives (types preserved);
    only plain str or trusted Obs strings are normalized; dict keys must be strings, collisions
    rejected. Tuples, custom objects and unknown str subclasses are rejected. Bounded depth 12,
    4096 items, 65536 canonical bytes (final strict UTF-8 canonical JSON length enforced).
    """
    state = [0, 0]

    def walk(x, depth):
        if depth > 12:
            return False, None
        state[0] += 1
        if state[0] > 4096:
            return False, None
        t = type(x)
        if x is None or t is bool or t is int:
            out, size = x, len(repr(x))
        elif t is float:
            if x != x or x in (float("inf"), float("-inf")):
                return False, None
            out, size = x, len(repr(x))
        elif t is dict:
            out, size = {}, 2
            for k, v in x.items():
                key = _scoped_text(k)
                if key is None or key in out:
                    return False, None
                ok, val = walk(v, depth + 1)
                if not ok:
                    return False, None
                out[key] = val
                size += len(key.encode("utf-8", "surrogatepass")) + 4
        elif t is list:
            out, size = [], 2
            for v in x:
                ok, val = walk(v, depth + 1)
                if not ok:
                    return False, None
                out.append(val)
                size += 1
        else:
            got = _scoped_text(x)
            if got is None:
                return False, None
            out, size = got, len(got.encode("utf-8", "surrogatepass")) + 2
        state[1] += size
        if state[1] > 65536:
            return False, None
        return True, out

    ok, detached = walk(value, 0)
    if not ok:
        return False, None
    try:
        data = json.dumps(
            detached,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (UnicodeEncodeError, ValueError, TypeError, RecursionError):
        return False, None
    if len(data) > 65536:
        return False, None
    return True, detached


def _scoped_hex(v):
    return type(v) is str and re.fullmatch(r"[0-9a-f]{64}", v) is not None


def _scoped_compact_ok(r):
    return (type(r) is dict and set(r) == {"index", "annotation_sha256", "source_ref_sha256"}
            and type(r["index"]) is int and _scoped_hex(r["annotation_sha256"])
            and _scoped_hex(r["source_ref_sha256"]))


def _scoped_compact(full):
    """Exact compact ref of one FULL native source ref, else None."""
    if type(full) is not dict or type(full.get("index")) is not int or not _scoped_hex(full.get("annotation_sha256")):
        return None
    digest = _scoped_sha(full)
    if digest is None:
        return None
    return {"index": full["index"], "annotation_sha256": full["annotation_sha256"], "source_ref_sha256": digest}


def _scoped_resolve(pool, compact):
    """Unique own-native FULL ref whose compact form equals `compact`, else None."""
    if not _scoped_compact_ok(compact) or type(pool) is not list:
        return None
    hits = [full for full in pool if _scoped_native_eq(_scoped_compact(full), compact)]
    return hits[0] if len(hits) == 1 else None


def _scoped_scope(inflection, negation, clauses):
    """Canonical normalized language scope {inflection, negation, clauses}, else None."""
    if type(clauses) is not dict or type(negation) is not dict:
        return None
    sfx = clauses.get("candidate_suffixes", [])
    marks = clauses.get("question_marks", [])
    if type(sfx) is not list or type(marks) is not list:
        return None
    return {"inflection": inflection, "negation": negation,
            "clauses": {"candidate_suffixes": sfx, "question_marks": marks}}


def _scoped_authority(projection, parser):
    """Own-native selected authority bound to the held parser (boundary, scope, refs), else None."""
    native = projection.get("data") if type(projection) is dict else None
    pack = projection.get("language_pack") if type(projection) is dict else None
    held = getattr(parser, "data", None)
    ppack = getattr(parser, "language_pack", None)
    if type(native) is not dict or type(held) is not dict or type(pack) is not dict or type(ppack) is not dict:
        return None
    frames = native.get("predicate_frames")
    if (type(frames) is not dict or type(frames.get("frames")) is not list
            or not _scoped_native_eq(frames, held.get("predicate_frames"))
            or "semantic_capabilities" not in native
            or not _scoped_native_eq(native["semantic_capabilities"], held.get("semantic_capabilities"))):
        return None

    def negation(src):
        raw = src.get("negation")
        return {} if raw is None else raw

    mine = _scoped_scope(getattr(parser, "inflection_grammar", None), negation(ppack),
                         getattr(parser, "clause_grammar", None))
    own = _scoped_scope(pack.get("inflection"), negation(pack), pack.get("clauses"))
    scope_sha = _scoped_sha(mine) if mine is not None else None
    if scope_sha is None or own is None or not _scoped_native_eq(mine, own):
        return None
    frame_full = [row["source_ref"] for row in frames["frames"]
                  if type(row) is dict and type(row.get("source_ref")) is dict]
    originals = projection.get("query_sources")
    derived = native.get("semantic_query_sources", [])
    if type(originals) is not list or type(derived) is not list or len(derived) > 4:
        return None
    if not all(type(r) is dict for r in derived):
        return None
    sizes = [_scoped_size(r) for r in derived]
    if None in sizes or any(s > 65536 for s in sizes) or sum(sizes) > 262144:
        return None
    original_full = [r.get("source_ref", r) for r in originals if type(r) is dict]
    return {"data": native, "frames": frames, "scope_sha256": scope_sha,
            "question_marks": mine["clauses"]["question_marks"], "frame_full": frame_full,
            "original_full": [r for r in original_full if type(r) is dict], "derived_full": derived}


def _scoped_cap(auth, name):
    """One live selected capability under own-native V4 compact/basis authority, else None."""
    data = auth.get("data") if type(auth) is dict else None
    caps = data.get("semantic_capabilities") if type(data) is dict else None
    schema = {"negative_binary": "selected-negative-binary-v1",
              "conditional_binary": "selected-conditional-binary-v1"}.get(name)
    if (type(caps) is not dict or schema is None
            or caps.get("schema") != "selected-binary-semantic-capabilities-v1"
            or not set(caps) <= {"schema", "negative_binary", "conditional_binary"} or len(caps) < 2):
        return None
    cap = caps.get(name)
    if type(cap) is not dict or set(cap) != {"schema", "basis", "capability_sha256", "query_refs"}:
        return None
    basis, refs, digest = cap["basis"], cap["query_refs"], cap["capability_sha256"]
    if (cap["schema"] != schema or type(basis) is not dict
            or set(basis) != {"schema", "grammar_reference", "frame_refs", "original_query_refs",
                              "normalized_language_scope_sha256"}
            or basis["normalized_language_scope_sha256"] != auth["scope_sha256"]
            or type(basis["frame_refs"]) is not list or not 1 <= len(basis["frame_refs"]) <= 16
            or type(basis["original_query_refs"]) is not list or type(refs) is not list
            or not all(_scoped_compact_ok(r) for r in basis["frame_refs"] + basis["original_query_refs"] + refs)
            or not _scoped_hex(digest)):
        return None
    if name == "conditional_binary" and (basis["original_query_refs"] or refs):
        return None
    if name == "negative_binary" and (len(refs) > 2 or len(refs) != len(basis["original_query_refs"])):
        return None
    for group in (basis["frame_refs"], basis["original_query_refs"], refs):
        if len({_scoped_canon(r) for r in group}) != len(group):
            return None
    queries = basis["original_query_refs"] + refs
    if len({r["index"] for r in queries}) != len(queries):
        return None
    if _scoped_sha(basis) != digest or _scoped_size(cap) is None or _scoped_size(cap) > 65536:
        return None
    if any(_scoped_resolve(auth["frame_full"], r) is None for r in basis["frame_refs"]):
        return None
    if any(_scoped_resolve(auth["original_full"], r) is None for r in basis["original_query_refs"]):
        return None
    for r in refs:
        full = _scoped_resolve(auth["derived_full"], r)
        derived = full.get("negative_derivation") if full is not None else None
        if (type(derived) is not dict
                or set(derived) != {"original_query_ref", "grammar_reference", "capability_sha256"}
                or derived["capability_sha256"] != digest
                or not _scoped_native_eq(derived["grammar_reference"], basis["grammar_reference"])
                or not _scoped_compact_ok(derived["original_query_ref"])
                or not any(_scoped_native_eq(derived["original_query_ref"], o)
                           for o in basis["original_query_refs"])):
            return None
    return cap


def _scoped_cert(parser, auth, source, cert, kind, cap, meaning):
    """Detached result (FULL own-native ref) for one exact current-source certificate of `kind`, else None.

    `meaning` is the exact type-sensitive witness meaning built from the full signed current row.
    """
    import hashlib
    source = _scoped_plain(source)
    if (source is None or type(auth) is not dict or type(cert) is not dict or type(cap) is not dict
            or type(meaning) is not dict
            or set(cert) != {"schema", "kind", "capability_sha256", "source_sha256", "source_span",
                             "compiler_index", "source_ref", "witness", "meaning"}
            or cert["schema"] != "selected-binary-source-certificate-v1" or cert["kind"] != kind
            or type(cert["capability_sha256"]) is not str
            or cert["capability_sha256"] != cap.get("capability_sha256")):
        return None
    try:
        own = hashlib.sha256(source.encode("utf-8")).hexdigest()
    except UnicodeEncodeError:
        return None
    size = _scoped_size(cert)
    span, ref, witness, index = cert["source_span"], cert["source_ref"], cert["witness"], cert["compiler_index"]
    if (size is None or size > 65536 or cert["source_sha256"] != own or type(span) is not list or len(span) != 2
            or not all(type(v) is int for v in span) or not 0 <= span[0] < span[1] <= len(source)
            or type(index) is not int or not _scoped_compact_ok(ref) or ref["index"] != index
            or type(witness) is not dict or len(witness) != 11 or type(witness.get("source")) is not str
            or witness["source"] != source[span[0]:span[1]]
            or not _scoped_native_eq(cert["meaning"], meaning)
            or not _scoped_native_eq(witness.get("meaning"), meaning)):
        return None
    if kind == "negative_query":
        rows = meaning.get("query")
        if set(meaning) != {"query"} or type(rows) is not list or len(rows) != 1 or type(rows[0]) is not dict:
            return None
        triple, pool, member = rows[0].get("triple"), auth["derived_full"], cap["query_refs"]
    else:
        triple, pool, member = meaning.get("triple"), auth["frame_full"], cap["basis"]["frame_refs"]
    full = _scoped_resolve(pool, ref)
    if full is None or not any(_scoped_native_eq(ref, r) for r in member):
        return None
    verify = getattr(parser, "verify_selected_binary_certificate", None)
    witnessed = getattr(parser, "verify_selected_binary_witness", None)
    if not callable(verify) or not callable(witnessed):
        return None
    got = verify(source, cert)
    if (type(got) is not dict or set(got) != {"kind", "triple", "polarity", "compiler_index", "source_ref"}
            or got["kind"] != kind or type(got["compiler_index"]) is not int or got["compiler_index"] != index
            or not _scoped_native_eq(got["source_ref"], full)
            or not _scoped_native_eq(_scoped_compact(got["source_ref"]), ref)
            or type(got["triple"]) is not list or len(got["triple"]) != 3
            or not all(type(p) is str and p for p in got["triple"]) or type(got["polarity"]) is not bool
            or got["polarity"] is not (kind == "positive_guard")
            or not _scoped_native_eq(got["triple"], triple)):
        return None
    seen = witnessed(witness["source"], witness, kind)
    if (type(seen) is not dict or set(seen) != {"source_ref", "compiler_index", "meaning", "capability_sha256"}
            or type(seen["compiler_index"]) is not int or seen["compiler_index"] != index
            or not _scoped_native_eq(seen["source_ref"], full)
            or not _scoped_native_eq(seen["meaning"], cert["meaning"])
            or seen["capability_sha256"] != cap["capability_sha256"]):
        return None
    return {"kind": kind, "triple": list(got["triple"]), "polarity": got["polarity"], "compiler_index": index,
            "source_ref": deepcopy(full), "span": list(span)}


def _scoped_guard(parser, auth, cap, cond, actual_source):
    """Detached positive_guard result for one own selected condition, else None. Truth-independent.

    The condition's source_original must exactly equal the actual replayed source content."""
    if type(cond) is not dict:
        return None
    actual = _scoped_text(actual_source)
    if actual is None or _scoped_text(cond.get("source_original")) != actual:
        return None
    triple, ev = cond.get("triple"), cond.get("evidence")
    source = _scoped_plain(cond.get("source_original"))
    if (type(triple) is not list or len(triple) != 3 or cond.get("polarity", True) is not True
            or source is None or type(ev) is not dict):
        return None
    cert = cond.get("source_certificate")
    seen_w = cert.get("witness") if type(cert) is dict else None
    meaning = _scoped_positive_meaning(seen_w.get("meaning") if type(seen_w) is dict else None, triple)
    if meaning is None:
        return None
    got = _scoped_cert(parser, auth, source, cert, "positive_guard", cap, meaning)
    if (got is None or type(ev.get("start")) is not int or type(ev.get("end")) is not int
            or [ev["start"], ev["end"]] != got["span"] or type(ev.get("text")) is not str
            or ev["text"] != source[ev["start"]:ev["end"]]):
        return None
    return got


def _scoped_guard_ids(parser, conds, projection, actual_source):
    """ids of conditions when ALL are independently authenticated own positive guards, else empty."""
    if type(conds) is not list:
        return frozenset()
    scoped = [c for c in conds if isinstance(c, dict)
              and ("source_certificate" in c or "source_original" in c)]
    if not scoped or len(scoped) != len(conds) or len(scoped) > 16:
        return frozenset()
    actual = _scoped_text(actual_source)
    if actual is None or any(_scoped_text(c.get("source_original")) != actual for c in scoped):
        return frozenset()
    auth = _scoped_authority(projection, parser)
    cap = _scoped_cap(auth, "conditional_binary") if auth is not None else None
    if cap is None:
        return frozenset()
    if any(_scoped_guard(parser, auth, cap, c, actual) is None for c in scoped):
        return frozenset()
    return frozenset(id(c) for c in scoped)


def realize(meaning, intent, language) -> str:
    from marco.language import realize as _realize
    return _realize(meaning, intent, language)


from marco.reasoning import readings as _readings
from marco.reasoning.readings import Obs, ReadingUnavailable, TENTATIVE


# ---------------------------------------------------------------------------
# Trace emission at this file's sites (request L1-1, the minimum; goal G5.0 b)
# ---------------------------------------------------------------------------
# The gap class of every reason a turn of this context is held for, in the seven classes of the
# adaptive note's taxonomy that goal G5 names (docs/ko/2026-09-24-adaptive-intelligence-design.md §3):
# routing: the turn reached a place that cannot take it (a limit, another component's request);
# lexical: a word is not known; concept: what a known word means is not known; relation: how two
# known things relate is not known; parser: the words were not read into a structure, or read more
# than one way; evidence: a fact the turn needs was never given, or cannot be told apart; conflict:
# what was said does not fit what is recorded. The table is the closed class of reasons this file
# gives (a test reads every reason literal in it); a reason missing here is emitted as parser with
# ``gap_declared`` false, so the table can be completed from the ledger.
GAP_CLASSES = {
    "routing": ("capacity", "graph_limit", "join_limit", "below_threshold", "no_graph_selected",
                "language_graph_capability_gap"),
    "lexical": ("unknown_word",),
    "concept": ("unreadable_definition", "conflicting_definition"),
    "relation": ("cause_effect_missing_or_ambiguous", "time_unresolved"),
    "parser": ("unrecognized_observation", "ambiguous_quantity_subject", "ambiguous_state_subject",
               "ambiguous_property_scope", "repair_over_bound", "repair_protected", "repair_ambiguous",
               "too_many_readings", "extra_argument", "extra_event", "correction_invalid", "answer_unclear",
               "role_mismatch", "unread_event", "unread_statement", "input_understanding_failed",
               "not_phrased", "invalid", "no_reading"),
    "evidence": ("not_stated", "premise_missing", "vague_count", "explain_nothing", "nothing_to_explain",
                 "unfilled_role", "unsettled_event", "unresolved", "which_referent", "no_referent",
                 "which_event", "ambiguous_reading", "reference_which_event", "reference_no_event",
                 "reference_value_unclear", "recipient_reference_no_event", "correction_target",
                 "unknown_basis", "unknown_lookup", "ambiguous_lookup", "unmeasured_condition",
                 "condition_false", "missing_initial_quantity"),
    "conflict": ("contradiction", "conflicting_event", "conflict_scope_unclear", "indivisible_amount",
                 "invalid_quantity_result", "invalid_quantity_delta", "invalid_initial_quantity", "unit_mismatch"),
}
GAP_OF = {reason: gap for gap, reasons in GAP_CLASSES.items() for reason in reasons}


def gap_class(reason):
    """``(gap, declared)`` for a hold reason: its class in ``GAP_CLASSES``, or parser and False."""
    reason = str(reason or "unresolved")
    if reason in GAP_OF:
        return GAP_OF[reason], True
    if reason.startswith("event_reference_"):
        return "evidence", True
    return "parser", False


# Readings as candidates (goal G5.4 B, the design note's hybrid scope). When the reader's first reading of a
# statement cannot be applied, or the reader left the statement unread because a clause read two ways at one
# rank, every reading the reader gives (RelationalParser.readings) is checked against the conversation's
# state. The constraints, in the order they drop a reading, each with the replay's failures it stands for
# (graph_inference.current_facts, ReasoningContext._replay); the reader's own particle and name guards come
# first and are applied inside the reader (a reading that breaks one is never returned):
READING_CONSTRAINTS = (
    ("statement", "the reading states something (a fact or an event), not a question or a request",
     ("not_a_statement",)),
    ("frame", "a transfer moves the thing from one holder to another, not to the same one", ("same_holder",)),
    ("kinds", "a thing the conversation counts is not a holder: its word never stands where a holder does",
     ("thing_as_holder",)),
    ("readable", "the conversation, replayed with the reading, reads every statement", ("unrecognized_observation",)),
    ("one_subject", "each change names one holder", ("ambiguous_quantity_subject", "ambiguous_state_subject",
                                                    "ambiguous_property_scope")),
    ("holder_exists", "a holder that loses some has a count said before, or at least that many received; "
                      "a receiver with none said keeps a count not known",
     ("missing_initial_quantity",)),
    ("count_can_move", "no count falls below zero or contradicts one said before; a change said in a unit that "
                       "holds several pieces does not move a count said in a unit of one piece, nor the reverse",
     ("invalid_quantity_result", "invalid_quantity_delta", "invalid_initial_quantity", "unit_mismatch")),
    ("within_limits", "the replay stays within the graph's limits", ("graph_limit", "join_limit")),
)
CONSTRAINT_OF = {failure: name for name, _doc, failures in READING_CONSTRAINTS for failure in failures}
# Of the readings no constraint drops, those of the reader's best tier stand (a declared example as written
# before a derived one, the reader's own order); one of them is used; several that would record different
# things are asked about (reason which_reading); none: the turn holds with every reading's failure.


def _sha(text):
    import hashlib
    return hashlib.sha256(str(text).strip().encode("utf-8")).hexdigest()


class PendingTrace:
    """The events one call of an engine site made, kept until the recorder writes them, as one trace, after
    the turn's own input event, so each rests on it (every event but an input has a parent). It takes the
    ledger's ``append`` with local ids; ``write`` gives the events their ledger ids."""

    def __init__(self):
        self.events = []

    def new_trace_id(self):
        return "pending"

    def append(self, kind, _trace_id, **fields):
        local = "local%d" % len(self.events)
        self.events.append((local, kind, fields))
        return {"event_id": local}

    def write(self, ledger, parent=None):
        """Write the events to ``ledger`` as one new trace; a root rests on ``parent`` (the turn's input)."""
        ids, trace_id = {}, ledger.new_trace_id()
        for local, kind, fields in self.events:
            fields = dict(fields)
            parents = [ids[ref] for ref in fields.pop("parent_ids", []) if ref in ids]
            if not parents and parent:
                parents = [parent]
            ids[local] = ledger.append(kind, trace_id, parent_ids=parents, **fields)["event_id"]
        return list(ids.values())


class UnknownWord(ValueError):
    """뜻을 아직 모르는 낱말로 된 사건. 틀린 조건이 아니라 **모르는 말**이다."""

    def __init__(self, word, said):
        super().__init__("unknown_word:%s" % word)
        self.word, self.said = word, said


class DefinitionTable(dict):
    """Latest definitions plus versioned programs from one replay.

    The mapping remains stem-to-rule for all existing readers.  Program
    versions live on an attribute, rather than in synthetic mapping keys, so
    verb lookup cannot mistake execution metadata for a learned word.
    """
    def __init__(self, latest, programs):
        super().__init__(latest)
        self.programs = programs


class ReasoningContext:
    # The trace ledger this context writes its own events to (marco.trace.ledger.Ledger), or None:
    # recording is off unless a recorder or a test sets it (request L1-1, W4-1). Never saved in a snapshot.
    trace = None
    # 말을 어디에 놓을지 몰라서 터진 자리들.
    UNPLACED = {"unrecognized_observation", "missing_initial_quantity",
                "ambiguous_quantity_subject", "ambiguous_state_subject",
                "ambiguous_property_scope", "unit_mismatch",
                "graph_limit", "join_limit"}
    # 읽기는 읽었는데 **앞서 들은 것과 맞지 않는** 자리들. 3개에서 8개를 꺼낼 수는
    # 없다 — 그러나 그것이 "안 일어난 일" 이라는 뜻은 아니다. 처음 수량이 틀렸거나
    # 중간 사건이 빠졌을 수 있다. 우리가 어느 쪽인지 고르지 않고 묻는다.
    CONTRADICTION = {"invalid_quantity_result", "invalid_quantity_delta",
                     "invalid_initial_quantity"}

    # How far the candidate search goes when a turn does not read or a state check refuses it (goal G7,
    # amendment A2): 0 the first reading only; 1 the readings the reader gives; 2 plus slot and referent
    # candidates from the conversation; 3 plus one repair step and a retry. The checks are the same at every
    # level. Set per context, else by the environment (MARCO_EFFORT), else the highest.
    EFFORT_LEVELS = (0, 1, 2, 3)

    @staticmethod
    def _declared_effort(effort=None):
        if effort is None:
            effort = os.environ.get("MARCO_EFFORT", "").strip() or ReasoningContext.EFFORT_LEVELS[-1]
        effort = int(effort)
        if effort not in ReasoningContext.EFFORT_LEVELS:
            raise ValueError("effort must be one of %s" % (ReasoningContext.EFFORT_LEVELS,))
        return effort

    def _effort_allows(self, level):
        """Whether this context's effort budget reaches ``level``."""
        return self.effort >= level

    def _candidate_dropped(self, level, kind, candidate, why):
        """A candidate the search tried and dropped (``why``), for the trace of this turn."""
        dropped = getattr(self, "_trace_candidates", None)
        if dropped is None:
            dropped = self._trace_candidates = []
        dropped.append({"level": level, "kind": kind, "candidate": candidate, "why": why})

    # The declared order candidates are ranked by (amendment A4; G5 design note §11 made lexicographic):
    # each check's fit, higher first; the repair cost, lower first. No weights: a later check decides only
    # when every earlier one is equal.
    RANK_ORDER = ("state", "reasoning", "grammar", "context", "cost")

    def _rank_candidates(self, candidates, kind="reading"):
        """``candidates``: the survivors of the checks, each ``{"label": str, "fit": {check: value}, ...}`` with
        a fit per check of ``RANK_ORDER`` (a bool or a count of declared checks passed, higher is better;
        ``cost`` a count of repair steps, lower is better; a check left out is 0; anything else raises). Returns ``(winner or None, deciding check, ranking)``: the top candidate when it
        beats the runner-up on one check, the first in the declared order where they differ; ``"only"`` for a
        single survivor; ``(None, "tie", ranking)`` when the top two are equal on every check (ask);
        ``(None, None, [])`` for none (hold). The ranking and the deciding check go to the trace."""
        for candidate in candidates or []:
            for check, value in (candidate.get("fit") or {}).items():
                # a fit is a bool or a count of declared checks passed, a cost a count of repair steps: never a
                # hand-set fraction, which would be a tuned weight again
                if check not in self.RANK_ORDER or not isinstance(value, int) or (check == "cost" and value < 0):
                    raise ValueError("fit %s=%r of %r is not a declared check's count" % (
                        check, value, candidate.get("label")))

        def key(candidate):
            fit = candidate.get("fit") or {}
            return tuple(-int(fit.get(check) or 0) if check != "cost" else int(fit.get(check) or 0)
                         for check in self.RANK_ORDER)
        ranking = sorted(candidates or [], key=key)
        if not ranking:
            winner, deciding = None, None
        elif len(ranking) == 1:
            winner, deciding = ranking[0], "only"
        else:
            top, runner = key(ranking[0]), key(ranking[1])
            deciding = next((check for check, a, b in zip(self.RANK_ORDER, top, runner) if a != b), "tie")
            winner = ranking[0] if deciding != "tie" else None
        rankings = getattr(self, "_trace_rankings", None)
        if rankings is None:
            rankings = self._trace_rankings = []
        rankings.append({"kind": kind, "effort": self.effort, "decided_by": deciding,
                         "winner": (winner or {}).get("label"),
                         "ranking": [{"label": c.get("label"), "fit": dict(c.get("fit") or {})} for c in ranking]})
        return winner, deciding, ranking

    def __init__(self, max_turns=128, *, model=None, companions=(), language=None, effort=None):
        self.effort = self._declared_effort(effort)
        # One authoritative, bounded ledger: observation slot -> every reading version, one active.
        # ``parser.chosen_readings`` / ``parser.chosen_programs`` are views of it, keyed by identity.
        self.max_turns = max_turns
        self._obs, self.reading_ledger, self._next_observation = [], {}, 1
        self.parser_base_sha256, self.installed_memory_head = None, None
        self.observations = []
        self.corrections = []
        # Allocation is independent of parsed role values: correcting a role
        # changes an event revision, not the identity of the original event.
        self.event_ids = {}
        self.event_revisions = []
        # Once a snapshot supplied event envelopes, retain them as semantic
        # records.  A later snapshot must not parse historical source merely
        # to rediscover a negative/unresolved event that has no emitted fact.
        self._stored_event_records = None
        self._event_records_count = 0
        # A per-conversation overlay learned solely from durable event
        # envelopes.  It is never written into the base pack.
        from marco.learning.concepts import ExperienceConceptStore
        self.concepts = ExperienceConceptStore()
        # The last concept-backed relation request is semantic state, not a
        # canned answer.  A following "why" recomputes its evidence against
        # the current event/concept ledger, so a correction cannot surface
        # discarded support.
        self.last_concept_relation = None
        # 자리를 못 채워 **되물어 둔** 사건들. 뒤에 온 말이 그 자리를 채우면
        # 그 말은 새 사건이 아니라 **이 사건의 보완**이다. 되묻지 않았으면
        # 잇지 않는다 — 같은 동사에 자리 몇 개가 겹친다는 것만으로는 모자라다.
        # 되물어 둔 것이 여럿일 수 있으므로 하나만 들고 있지 않는다.
        self.asked = []
        # 막아 둔 물음. 짧은 답으로 자리가 채워지면 그 자리에서 이어 답한다.
        self.held_question = None
        # 마지막으로 답한 물음이 무엇에 대한 것이었나. 지시어를 풀 때 쓴다.
        self.last_subject = None
        # The last answered question and its subject, for a follow-up that
        # names only another person ("And Moru?"), and a question held because
        # its pointer had several candidates, for a reply that names one.
        self.last_question = None
        self.pending_pointer = None
        self._in_name_reply = False
        # The frame of the last question read, answered or held: its words and the slots they fill
        # (holder, item), for a follow-up that names one slot only (G7-Q.1, effort 2).
        self.last_frame = None
        # 최근에 명시된 역할값. 지시어를 단순히 "마지막 낱말"에 붙이지 않고,
        # 다음 사건이 요구한 **같은 역할**에만 이어 붙인다. 원문 사건에는
        # 해석 전 값과 근거가 남고, 이 표는 다음 입력의 문맥 후보일 뿐이다.
        self.last_referents = {}
        # 마지막 답이나 교정을 어떻게 얻었는지. `왜 그렇게 됐어?` 가 이것을 설명한다.
        self.last_explanation = None
        # (observation index, subject): an amount said without its holder right after a question held
        # for that count not known yet is that count (the question fixed what the amount is about)
        self.bind_hints = []
        self._vague_asked = None
        # 마지막 답·교정에 걸린 사람들. 여럿이면 지시어를 고르지 않는다.
        self.last_mentioned = []
        # The people a pointer may mean: whom the last question named, and
        # whom every statement since named (see ``_salient_person``).
        self.salient = []
        # 되물어서 받은 답들. **어느 사건의 어느 역할을 어떤 값으로 채웠다.**
        # 원문을 고쳐 쓰지 않으므로 근거와 차례와 그때의 뜻이 그대로 남는다.
        self.fills = []
        # 이해하지 못한 말. 버리지 않는다 — 버리면 그 말이 바꿨을 상태를
        # 예전 값 그대로 확정하게 된다. 기억을 통째로 지우지도 않는다.
        self.unread = []
        # 원문 보류는 대화 한도 안에서만 두되, 밀려난 사건의 안전 효과는
        # 별도 보류로 남긴다. 메모리 한도 때문에 옛 상태를 확정하지 않는다.
        self.unread_guard = []
        self.max_turns = max_turns
        self.model = model
        # 같은 팩의 다른 언어 모델. 이 대화의 상태는 하나이고, 다른 언어로 온
        # 물음은 그 언어 팩으로 읽은 뒤 선언된 대조표로 이 대화의 이름에 맞춘다.
        self.companions = tuple(companions)
        # 모델 없이 도는 개발 경로에서 쓸 언어. 없으면 팩 선언의 기본 언어다.
        self.language = language
        # A stable id of this conversation, carried in each turn's ``meaning``.
        # The realizer scopes expressions learned from it to it.
        self.conversation_id = uuid.uuid4().hex
        self._companion_parsers = {}
        # 한 대화의 언어·공리 선택은 생성 뒤 바뀌지 않는다. 매 턴 같은 사례
        # 틀을 다시 컴파일하지 않고, 대화마다 따로 가진 파서를 재사용한다.
        # 파서는 원문을 기억하지 않으므로 다른 대화의 사실이 섞이지 않는다.
        self._parser_instance = None
        # 마지막으로 검증한 관찰열. 물음은 상태를 바꾸지 않으므로, 같은 열에
        # 대한 반복 질의가 원문 전체를 다시 읽을 이유는 없다. 이 값은 저장하지
        # 않으며 관찰·보완·교정이 달라지면 열쇠가 즉시 달라진다.
        self._replay_cache = None
        # 이번 상태가 어느 재생 범위에서 검증됐는지 답의 검증 근거에 남긴다.
        # 속도 주장과 의미 보존 범위를 같은 관찰로 확인할 수 있게 한다.
        self._last_replay_scope = "none"
        # 활용형 표도 관찰열의 접두어에만 붙인다. 새 말 한 개가 왔다고 앞선
        # 정의문을 다시 훑지 않는다.
        self._verb_cache = None

    @staticmethod
    def _numeric_targets(parser):
        return {rule.get("target") for rule in (parser.data.get("numeric_updates") or {}).values()}

    @staticmethod
    def _counts_something(said, parser):
        """이 말이 수를 담고 있나. 아라비아 숫자만 보면 `세 개를 더 넣었다` 를 놓친다.

        수사는 언어팩이 선언한다. 코드가 한국어 수사를 따로 알 필요는 없다.
        """
        from marco.language.frames import split_particle
        from marco.language.numerals import parse_numeral
        numerals = parser.data.get("numerals") or {}
        for token in said.replace(".", " ").split():
            if any(char.isdigit() for char in token):
                return True
            # 낱말째로 본다. 글자로 보면 `단추 이야기는 재밌다` 의 `다` 가
            # `다섯` 에 걸려 잡담까지 수량 사건이 된다.
            if parse_numeral(token, numerals) is not None:
                return True
            # 조사를 단 수사도 수다. `그중 하나를 빌려줬어` 의 `하나를` 을 놓치면, 못 읽은
            # 그 말이 누군가의 수를 옮겼는데도 옛 값을 답으로 낸다.
            # Only the native numerals said as nouns (하나를, 셋을): the Sino-Korean digits are also
            # common words (일은, 이가), and a determiner form (두, 세) stands before a counter.
            nouns = (getattr(parser, "word_order_forms", None) or {}).get("numeral_nouns") or {}
            bare = split_particle(token, getattr(parser, "case_particles", ()) or (),
                                  getattr(parser, "slot_particles", ()) or ()) if nouns else None
            native = {k: v for k, v in numerals.items() if k in ("atoms", "tens")}
            if (bare and not bare[0].endswith(tuple(nouns.get("determiners", [])))
                    and parse_numeral(bare[0], native) is not None):
                return True
        return False

    @staticmethod
    def _segments(text, parser):
        """한 덩어리를 문장 단위로 나눈다.

        `구슬 3개를 더 넣었다. 지금 구슬은 몇 개야?` 는 사건 하나와 물음 하나다.
        메시지가 물음표로 끝난다는 이유로 앞의 사건까지 물음으로 치면, 못 읽은
        사건이 기록에서 빠지고 옛 값이 그대로 확정된다.
        """
        marks = parser.clause_grammar.get("question_marks", [])
        stops = "".join(marks) + ".!…"
        # a declared abbreviation's full stop (Mr., Dr.) ends no sentence
        abbreviations = tuple(parser.clause_grammar.get("abbreviations", []))

        def abbreviated(buffer):
            tail = buffer.rstrip()
            return any(tail.endswith(a) and (len(tail) == len(a) or not tail[-len(a) - 1].isalpha())
                       for a in abbreviations)
        out, buffer = [], ""
        for char in text:
            buffer += char
            if char in stops and buffer.strip() and not (char == "." and abbreviated(buffer)):
                out.append(buffer); buffer = ""
        if buffer.strip():
            out.append(buffer)
        return [(piece.strip(), any(piece.rstrip().endswith(mark) for mark in marks))
                for piece in out if piece.strip()]

    def _remember_unread(self, entry):
        """원문 보류를 유한하게 보관하되, 넘친 보류의 안전 효과는 남긴다."""
        if self.trace is not None:
            # L1-1 B8: a statement the reader did not read is evidence rejected (by digest, never its text)
            self.__dict__.setdefault("_trace_buffer", []).append(
                ("evidence_rejected", {"reason": str(entry.get("까닭") or "unread"), "at": entry.get("at"),
                                       "sha256": _sha(entry["text"]), "general": bool(entry.get("범용"))}))
        if any(item["text"] == entry["text"] for item in self.unread):
            return
        self.unread.append(entry)
        overflow = self.unread[:-self.max_turns]
        del self.unread[:-self.max_turns]
        for item in overflow:
            if not any(old["text"] == item["text"] for old in self.unread_guard):
                self.unread_guard.append(deepcopy(item))
        limit = max(16, self.max_turns * 4)
        if len(self.unread_guard) > limit:
            newest = self.unread_guard[-limit:]
            # 합친 보류는 어느 대상의 어느 시점인지 잃는다. 따라서 그 안에서
            # 가장 늦은 미확인 시점으로 남겨, 그보다 앞의 못 박은 값을 다시
            # 확정하지 않는다.
            latest = max(item["at"] for item in self.unread_guard)
            graph_text = None
            from pack_model import PackModel
            if type(self.model) is PackModel and self.model.language_projection is not None:
                graph_text = next((item["text"] for item in self.unread_guard if item["at"] == latest), None)
            self.unread_guard = [{"text": graph_text if graph_text is not None
                                  else self._parser().data["ledger_labels"]["overflow"],
                                  "at": latest, "까닭": "한도", "범용": True}] + newest

    def _forget_heard(self, heard):
        self.unread = [entry for entry in self.unread if entry["text"] not in heard]
        self.unread_guard = [entry for entry in self.unread_guard
                             if entry["text"] not in heard]

    def _blocked_by(self, query, parser, facts):
        """이 물음이 가리키는 것에 대해 못 읽은 사건이 있으면 그 말을 돌려준다.

        해소 조건은 하나뿐이다 — **미해석 사건보다 나중에, 같은 대상의 같은
        속성을 실제로 못 박은 관찰.** 딴 대상의 관찰도, 또 다른 증감 사건도
        총량을 확정하지 못한다. 반례마다 조건을 덧붙이지 않는다.
        """
        numeric = self._numeric_targets(parser)
        # Only the holders the question names are pinned. The predicate (`count`) and a count's value are
        # no holder: no observation pins them, so a later statement of the count never released the hold.
        named = set()
        for item in query or []:
            subject, predicate, value = (list(item.get("triple") or []) + [None] * 3)[:3]
            named.update(word for word in (subject, None if predicate in numeric else value)
                         if isinstance(word, str) and not word.startswith(("?", "$")))
        asks_number = any((item.get("triple") or [None, None])[1] in numeric
                          for item in (query or []))
        asked_predicates = {(item.get("triple") or [None, None])[1]
                            for item in (query or [])}
        known = named | {fact["triple"][0] for fact in facts
                         if isinstance(fact.get("triple", [None])[0], str)}
        # 이 대상의 값을 마지막으로 못 박은 관찰이 몇 번째였나. 증감 사건은
        # 못 박는 것이 아니라 흔드는 것이므로 세지 않는다.
        pinned = {name: max([fact["evidence"].get("turn", -1) for fact in facts
                             if fact["triple"][0] == name and fact["triple"][1] in numeric] or [-1])
                  for name in named or {None}}
        # W5-3 (b): the statement named is the earliest unread one that blocks the question, in the
        # conversation's order; looping over the names first made it follow the set's hash order.
        graph = self.conversation_graph() if asks_number else None
        for entry in self.unread_guard + self.unread:
            said = entry["text"]
            if graph is not None and entry.get("대상") is None:
                # an unread statement that mentions a thing node shakes every count of that thing; a holder asked
                # about is held while a count of theirs it shook (the thing asked, or another thing they hold:
                # 23 quills in each pack) has not been said again since
                mentioned = self._things_mentioned(parser, graph, said)
                for name in pinned:
                    pair = graph.of_key(name) if name else None
                    if pair is None or not mentioned:
                        continue
                    for key, thing in graph.keys_of_holder(pair[0]):
                        last = max([fact["evidence"].get("turn", -1) for fact in facts
                                    if fact["triple"][0] == key and fact["triple"][1] in numeric] or [-1])
                        if thing in mentioned and entry["at"] > last:
                            return said, entry.get("까닭")
            for name in pinned:
                # 이름이 여러 낱말이면 낱말째로 본다. 물음은 `민수 구슬` 인데
                # 못 읽은 말은 `민수가 지연에게 베풀었다` 라 통째로는 안 걸린다.
                parts = [word for word in (name or "").split() if word]
                if entry.get("대상") is not None:
                    # An unapplied correction names the statements it concerned.
                    touches = any(word in entry["대상"] for word in parts) or name is None
                else:
                    touches = (any(word in said for word in parts)
                               or entry.get("관계") in asked_predicates) or (
                        asks_number and self._counts_something(said, parser)
                        and not any(other and other in said for other in known)) or (
                        asks_number and self._moves_someone_unnamed(said, parser)) or (
                        asks_number and self._points_at_someone(said, parser))
                if (entry.get("범용") or touches) and entry["at"] > pinned[name]:
                    return said, entry.get("까닭")
        return None

    def _things_mentioned(self, parser, graph, said):
        """The thing nodes an unread statement mentions: a word of it (its particle off, or in the plural the pack
        declares for it) is one of the node's names, or the first or the last word of one (pack, for packs of
        quills; never a word in the middle)."""
        from relational_semantics import declared_plural
        cache = self.__dict__.setdefault("_things_mentioned_cache", {})
        stamp = (said, len(graph.aliases))
        if stamp in cache:
            return cache[stamp]
        fold = (lambda v: v.lower()) if parser.data.get("ignore_case") else (lambda v: v)
        particles = self._frame_particles(parser)
        number = getattr(parser, "noun_number", None) or {}
        words = set()
        for word in re.split(r"[\s,.!?？。]+", said):
            if not word:
                continue
            stem = next((word[:-len(p)] for p in particles if word.endswith(p) and len(word) > len(p)), word)
            for form in (word, stem):
                words.add(fold(form))
                plural = declared_plural(form, number)
                if plural:
                    words.add(fold(plural))
        found = set()
        for row in graph.aliases:
            node = graph.nodes.get(row["node"])
            if node is None or node["kind"] != "thing" or row["form"] not in ("key", "short", "number"):
                continue
            parts = [fold(w) for w in row["text"].split()]
            if parts and (fold(row["text"]) in words or parts[0] in words or parts[-1] in words):
                found.add(node["id"])
        cache[stamp] = found
        return found

    def _points_at_someone(self, said, parser):
        """An unread statement that names its holder by a pointer the pack declares (Then they vanished. / 그는
        다 잃어버렸어.): the pointer may be any holder, so it may have changed any holder's count."""
        fold = (lambda v: v.lower()) if parser.data.get("ignore_case") else (lambda v: v)
        particles = self._frame_particles(parser)
        words = [fold(w) for w in re.split(r"[\s,.!?？。]+", said) if w]
        stems = [next((w[:-len(p)] for p in particles if w.endswith(p) and len(w) > len(p)), w) for w in words]
        flat = " %s " % " ".join(words)
        return any(" %s " % fold(p) in flat or (" " not in p and fold(p) in stems) for p in parser.pointers or [])

    def _moves_someone_unnamed(self, said, parser):
        """An unread statement whose reading moves an amount from or to a holder it leaves unsaid (``그중
        하나를 준호한테 줬어`` after two holders: the giver could be anyone). It may have changed any holder's
        count, so no count is said as known after it (G6)."""
        cache = self.__dict__.setdefault("_unnamed_mover_cache", {})
        if said not in cache:
            targets = {name for name, spec in (parser.data.get("numeric_updates") or {}).items()
                       if isinstance(spec, dict)}
            read = parser.parse(said, partial=True, events=True, repair=True) or {}
            cache[said] = any(f["triple"][0] is None and f["triple"][1] in targets for f in read.get("facts", []))
        return cache[said]

    def _shaken_by_unread(self, parser, facts, changes):
        """G5.3 safety: an earlier statement the reader left unread that names a holder this turn moved (every
        word of the holder's state key, a plural s aside), said after the last observation that fixed that
        holder's count; None when there is none. The event is kept, but what it makes the holder's count is not
        said as known: it would rest on a statement that was never applied. A word said in the singular
        names the key's plural when the pack declares that plural (명사수)."""
        from relational_semantics import declared_plural
        numeric = self._numeric_targets(parser)
        number = getattr(parser, "noun_number", None) or {}
        things = {str(fact["triple"][0]).split()[-1].lower() for fact in facts
                  if isinstance(fact["triple"][0], str) and len(str(fact["triple"][0]).split()) > 1
                  and fact["triple"][1] in numeric}
        for change in changes:
            subject = change.get("subject")
            if not isinstance(subject, str) or change.get("predicate") not in numeric:
                continue
            words = [word.lower() for word in subject.split() if word]
            pinned = max([fact["evidence"].get("turn", -1) for fact in facts
                          if fact["triple"][0] == subject and fact["triple"][1] in numeric] or [-1])
            turn = (change.get("evidence") or {}).get("turn", -1)
            for entry in self.unread_guard + self.unread:
                said = entry["text"].lower()
                tokens = re.findall(r"\w+", said)
                plurals = {(declared_plural(token, number) or "").lower() for token in tokens}
                named = lambda word: word in said or word in plurals
                # G7-S: an unread statement that names the holder and counts something, but names no thing
                # the conversation counts (the thing left to a pronoun: used three of them), may have moved
                # this holder's count too; what the transfer makes it is not said as known (it was said as
                # the stale count: a wrong record)
                unnamed_thing = len(words) > 1 and all(named(word) for word in words[:-1]) and not any(
                    named(thing) or thing in tokens for thing in things)
                if (pinned < entry["at"] <= turn and self._counts_something(entry["text"], parser)
                        and (all(named(word) for word in words) or unnamed_thing)):
                    return entry["text"]
            # A holder whose count was never said under this key, but an earlier statement counted a key with
            # every word of it (민혁 트럭에 자두 for 민혁 자두, a place phrase kept in the name): that statement may be
            # this holder's count, so what the transfer makes it is not said as known (G6).
            if change.get("before") is None and pinned < 0:
                other = next((fact for fact in facts if fact["triple"][1] in numeric and fact["triple"][0] != subject
                              and isinstance(fact["triple"][0], str)
                              and (fact.get("evidence") or {}).get("turn", -1) < turn
                              and all(word in fact["triple"][0].lower().split() for word in words)), None)
                if other is not None:
                    return (other.get("evidence") or {}).get("text") or other["triple"][0]
        return None

    def _rekeyed_fit(self, parser, text, verbs, turns, old, new, parts=None):
        """The conversation replayed with ``text`` and with the statements at ``turns`` read with ``old``
        keyed as ``new`` (their facts naming ``parts``, the holder and thing of ``new``): ``(fit, readings)`` when
        no constraint breaks and every change this statement makes to ``new`` starts from a count; else the
        reason it does not fit. Nothing is kept."""
        table = parser.__dict__.setdefault("chosen_readings", {})
        readings = self._rekeyed_readings(parser, verbs, turns, old, new, parts)
        if readings is None:
            return "not_in_reading"
        saved = {source: table.get(source) for source in readings}
        updates = parser.data.get("numeric_updates") or {}
        try:
            table.update(readings)
            facts, _d, _p, _r = self._replay(parser, self.observations + [text], self.fills,
                                             deepcopy(self.event_ids) if self.event_ids is not None else None,
                                             projection=getattr(self.model, "language_projection", None))
            facts = self._unit_keys(parser, self._bind_unnamed_counts(parser, [], facts, getattr(self, "bind_hints", [])))
            _state, changes = current_facts(facts, parser.data.get("mutable_predicates", []), updates)
        except ValueError as exc:
            return str(exc).split(":")[0]
        finally:
            for source, before in saved.items():
                if before is None:
                    table.pop(source, None)
                else:
                    table[source] = before
        index = len(self.observations)
        mine = [row for row in changes if row.get("subject") == new
                and (row.get("evidence") or {}).get("turn") == index]
        if not mine or any(row.get("before") is None for row in mine):
            return "no_count_before"
        return {"state": 1, "cost": 1}, readings

    def _rekeyed_readings(self, parser, verbs, turns, old, new, parts=None):
        """The readings of the statements at ``turns`` with ``old`` keyed as ``new`` ({source: reading}), their facts
        naming ``parts`` (the holder and thing of ``new``) when given, or None when one of them does not read
        ``old``."""
        readings = {}
        for i in turns:
            if not (isinstance(i, int) and 0 <= i < len(self.observations)):
                continue
            source = self.observations[i].oid
            reading = deepcopy(self._read_source(parser, self.observations[i], events=True, verbs=verbs))
            if not reading or not any(isinstance(f.get("triple"), list) and f["triple"][0] == old
                                      for f in reading.get("facts", [])):
                return None
            for fact in reading["facts"]:
                if isinstance(fact.get("triple"), list) and fact["triple"][0] == old:
                    fact["triple"][0] = new
                    if parts:
                        fact["parts"] = dict(parts)
                    else:
                        fact.pop("parts", None)
            readings[source] = reading
        return readings or None

    def _read_other_keys(self, parser, text, current, verbs):
        """G7-S, effort 2 (a referent candidate from the conversation's graph; amendment A1): a statement that
        moves an amount from or to a holder with no count under the key it names, where the conversation's graph
        counts that holder node under another key, for the same thing node or for a thing not said (기 대표님에게는
        열 개 있어: 기 대표, thing not said; 경아는 승합차에 형광펜을 싣고 있어: 경아's 형광펜 kept with its place), is
        tried with that earlier statement keyed the way this one names it, when that is the node's own key (its
        holder's and its thing's names; a thing said by other words is ``_read_thing_alias``'s). A candidate survives when the replay
        breaks no constraint and the holder has a count before this statement (``_rekeyed_fit``); the survivors
        are ranked (``_rank_candidates``), and a clear winner becomes the earlier statement's reading for this
        conversation (``chosen_readings``). Givers first: a receiver's candidate is checked with the giver's
        already kept. A tie or no survivor changes nothing, and the statement goes on as before."""
        updates = parser.data.get("numeric_updates") or {}
        rows = [f for f in current.get("facts", []) if isinstance(f.get("triple"), list)
                and isinstance(f["triple"][0], str) and f["triple"][1] in updates]
        rows.sort(key=lambda f: float((updates[f["triple"][1]] or {}).get("factor", 1) or 1) > 0)
        if not rows or not self.observations:
            return None
        try:
            facts, _d, _p, _r = self._cached_replay(parser, self.observations, self.fills)
            state, _c = current_facts(facts, parser.data.get("mutable_predicates", []), updates)
        except ValueError:
            return None
        graph = self.conversation_graph()
        counted = {row["triple"][0] for row in state}
        kept = []
        for fact in rows:
            subject = fact["triple"][0]
            parts = fact.get("parts") if isinstance(fact.get("parts"), dict) else None
            if subject in counted or not parts or not parts.get("thing") \
                    or " ".join((parts["holder"], parts["thing"])) != subject:
                continue
            holders = graph.find(parts["holder"], kinds=("holder",))
            if len(holders) != 1:
                continue
            thing = graph.id_of("thing", parts["thing"])
            own = "%s %s" % (graph.nodes[holders[0]]["name"], graph.nodes[thing]["name"]) if thing is not None else None
            if thing is not None and own != subject:
                # the statement names the thing by other words than its node: it is read with the node's key
                # (``_read_thing_alias``), the earlier statements keep theirs
                continue
            others = [(key, "same_thing") for key in (graph.keys_of(holders[0], thing) if thing else []) if key != subject]
            others += [(key, "thing_not_said") for key in graph.keys_of(holders[0], None) if key != subject]
            survivors = []
            for key, kind in others:
                turns = sorted({(f.get("evidence") or {}).get("turn") for f in facts if f["triple"][0] == key}
                               - {None})
                label = "%s -> %s" % (key, subject)
                fit = self._rekeyed_fit(parser, text, verbs, turns, key, subject,
                                        {"holder": parts["holder"], "thing": parts["thing"]})
                if isinstance(fit, str):
                    self._candidate_dropped(2, kind, label, fit)
                    continue
                survivors.append({"label": label, "fit": fit[0], "readings": fit[1], "kind": kind,
                                  "from": key, "to": subject})
            if not survivors:
                continue
            winner, deciding, _ranking = self._rank_candidates(survivors, kind="other_key")
            if winner is None:
                continue
            self._revise_readings(winner["readings"], "referent_resolution")
            self.__dict__.setdefault("_trace_buffer", []).append(("hypothesis_verified", {"checks": [{
                "ok": True, "reason": "other_key", "kind": winner["kind"], "from": winner["from"],
                "to": winner["to"], "decided_by": deciding, "effort": self.effort}]}))
            kept.append(winner["label"])
            counted.add(subject)
        return kept or None

    def _read_unsaid_thing(self, parser, text, current, verbs, knowledge_path):
        """G7-S experiment 2, effort 2 (a slot candidate from the conversation; amendment A1): a statement that
        moves or states an amount of a thing it does not name (Nora gave Eli three., 가람이 나래에게 세 개를 줬어.)
        names holders whose keys carry no thing. When the conversation cannot take the thing from one key of
        the holder alone (the holder counts two things, or none), each thing a named holder counts, and the
        thing of the statement just before, is a candidate (``_unsaid_thing_candidates``); the survivors are
        ranked (``_rank_candidates``) and a clear winner is kept (``_keep_reading``); a tie or none returns None
        and the statement goes on as before."""
        survivors = self._unsaid_thing_candidates(parser, text, current, verbs)
        if not survivors:
            return None
        winner, _deciding, _ranking = self._rank_candidates(survivors, kind="unsaid_thing")
        return self._keep_reading(parser, text, winner, knowledge_path, "unsaid_thing")

    def _unsaid_thing_candidates(self, parser, text, current, verbs, cost=0, label=""):
        """The candidates of ``_read_unsaid_thing`` for the reading ``current`` of ``text``, on the conversation's
        graph: every holder the statement names without a thing takes one thing node, each thing node a named
        holder node counts and the thing node of the statement just before. A holder counted only with its thing
        not said (기 대표님에게는 열 개 있어) takes the candidate thing with that earlier count keyed to it (one
        more step). Each is checked against the conversation (``_reading_failure``). Fit: state, every holder
        that loses some has a count before; context, the thing is that of the statement just before, and a
        receiver already counts it; cost, ``cost`` plus the thing put in (and the earlier count keyed). None when
        no holder of the reading lacks its thing (or its one thing node already gives it); [] when none survives."""
        updates = parser.data.get("numeric_updates") or {}
        numeric = self._numeric_targets(parser)
        rows = [f for f in current.get("facts", []) if isinstance(f.get("triple"), list)
                and isinstance(f["triple"][0], str) and (f["triple"][1] in updates or f["triple"][1] in numeric)]
        if not rows or not self.observations:
            return None
        graph = self.conversation_graph()
        if not graph.of_kind("thing"):
            return None

        def node_of(name):
            found = graph.find(name, kinds=("holder", "place"))
            return found[0] if len(found) == 1 else None

        def things_of(holder):
            return [t for t in graph.things_of(holder)] if holder else []
        # a holder named without a thing: its fact names no thing, or its key is a holder node's name and no key
        thingless = {}
        for fact in rows:
            subject = fact["triple"][0]
            parts = fact.get("parts") if isinstance(fact.get("parts"), dict) else None
            if graph.of_key(subject) is not None:
                continue
            if parts and parts.get("holder") and not parts.get("thing") and parts.get("key", parts["holder"]) == subject:
                thingless[subject] = parts["holder"]
            elif fact.get("resolve") or len(subject.split()) == 1 or node_of(subject):
                if not (parts and parts.get("thing")):
                    thingless[subject] = subject
        if not thingless:
            return None
        nodes = {subject: node_of(name) for subject, name in thingless.items()}
        unsaid = {subject: graph.keys_of(node, None) if node else [] for subject, node in nodes.items()}
        if all(len(things_of(node)) == 1 and not unsaid[subject] for subject, node in nodes.items()):
            return None             # every holder has one thing node: the key's leading words already find it
        previous = self._read_source(parser, self.observations[-1], events=True, verbs=verbs) or {}
        before = [graph.of_key(f["triple"][0]) for f in previous.get("facts", []) if isinstance(f.get("triple"), list)
                  and isinstance(f["triple"][0], str)]
        before_thing = next((pair[1] for pair in before if pair and pair[1]), None)

        def removing(row):
            return row[1] in updates and float((updates[row[1]] or {}).get("factor", 1) or 1) < 0
        takers = [f["triple"][0] for f in rows if f["triple"][1] in updates and not removing(f["triple"])
                  and f["triple"][0] in thingless]
        candidates = [t for node in nodes.values() for t in things_of(node)] + ([before_thing] if before_thing else [])
        if not any(f["triple"][1] in updates for f in rows):
            # a holding that names no thing moves nothing that could tell the thing: it takes the conversation's
            # thing only when the conversation counts one; with two or more it stays not said, for a later
            # statement to tell (주 원장님에게는 14개 있어 after 반지 and 라임)
            candidates = [n["id"] for n in graph.of_kind("thing")]
            if len(candidates) != 1:
                return None
        survivors = []
        table = parser.__dict__.setdefault("chosen_readings", {})
        for thing in dict.fromkeys(candidates):
            thing_name = graph.nodes[thing]["name"]
            parsed = deepcopy(current)
            rekeyed, several = {}, False
            for fact in parsed.get("facts", []):
                subject = fact["triple"][0] if isinstance(fact.get("triple"), list) else None
                if subject not in thingless:
                    continue
                holder_name, node = thingless[subject], nodes[subject]
                keys = graph.keys_of(node, thing) if node else []
                if len(keys) > 1:
                    several = True
                key = keys[0] if keys else "%s %s" % (holder_name, thing_name)
                fact["triple"][0], fact["parts"] = key, {"holder": holder_name, "thing": key[len(holder_name) + 1:]}
                if not keys and unsaid.get(subject):
                    # the holder was counted with its thing not said: that count is keyed to this thing
                    for old in unsaid[subject]:
                        turns = sorted({(row.get("evidence") or {}).get("turn") for row in
                                        self._cached_replay(parser, self.observations, self.fills)[0]
                                        if row["triple"][0] == old} - {None})
                        readings = self._rekeyed_readings(parser, verbs, turns, old, key,
                                                          {"holder": holder_name, "thing": thing_name})
                        if readings:
                            rekeyed.update(readings)
            if several:
                self._candidate_dropped(2, "unsaid_thing", label + thing_name, "several_keys")
                continue
            saved = {source: table.get(source) for source in rekeyed}
            try:
                table.update(rekeyed)
                failure, changes = self._reading_failure(parser, text, parsed)
            finally:
                for source, before_reading in saved.items():
                    if before_reading is None:
                        table.pop(source, None)
                    else:
                        table[source] = before_reading
            if failure is not None:
                self._candidate_dropped(2, "unsaid_thing", label + thing_name, failure[1])
                continue
            known = all(row.get("before") is not None for row in changes if (row.get("delta") or 0) < 0)
            survivors.append({"label": label + thing_name, "parsed": parsed, "readings": rekeyed,
                              "fit": {"state": int(known),
                                      "context": int(thing == before_thing)
                                      + int(bool(takers) and all(thing in things_of(nodes.get(s)) for s in takers)),
                                      "cost": cost + 1 + int(bool(rekeyed))}})
        return survivors

    def _read_thing_alias(self, parser, text, current, verbs, knowledge_path):
        """G7-S, identity graph step 3, effort 2 (a referent candidate from the conversation's graph): a statement
        refused because a holder has no count under the key it names (Ada gave Bo one towel., one striped towel,
        for the thing the conversation counts as striped cotton beach towels) names the holder's thing with fewer
        of its words, or in its other number. Candidates are nodes: each thing node the named holder counts
        whose name holds every word of the mention in order (singular or plural; a container's content alone is
        another thing: ``_one_thing``); every holder of
        the statement then counts that thing node, under the key the conversation counts it by. Each is checked
        against the conversation (``_reading_failure``), ranked (``_rank_candidates``), and a clear winner is
        kept for this conversation (``_keep_reading``); two things that fit (towels, between red towels and blue
        towels) tie and hold."""
        updates = parser.data.get("numeric_updates") or {}
        rows = [f for f in current.get("facts", []) if isinstance(f.get("triple"), list)
                and isinstance(f["triple"][0], str) and f["triple"][1] in updates]
        if not rows or not self.observations:
            return None
        graph = self.conversation_graph()
        fits = self._one_thing(parser)
        named = {}
        for fact in rows:
            subject = fact["triple"][0]
            if graph.of_key(subject) is not None:
                continue
            parts = fact.get("parts") if isinstance(fact.get("parts"), dict) else None
            if parts and parts.get("thing") and " ".join((parts["holder"], parts["thing"])) == subject:
                holder_name, mention = parts["holder"], parts["thing"]
            else:
                holder_name = next((n["name"] for n in sorted(graph.of_kind("holder") + graph.of_kind("place"),
                                                              key=lambda n: -len(n["name"]))
                                    if subject.startswith(n["name"] + " ")), None)
                mention = subject[len(holder_name) + 1:] if holder_name else None
            nodes = graph.find(holder_name, kinds=("holder", "place")) if holder_name else []
            if not mention or len(nodes) > 1:
                return None
            named[subject] = (holder_name, nodes[0] if nodes else None, mention)
        if not named:
            return None
        givers = [node for _name, node, _m in named.values() if node is not None]
        things = []
        for holder in givers:
            for thing in graph.things_of(holder):
                name = graph.nodes[thing]["name"]
                if all(fits(m.split(), name.split()) for _n, _h, m in named.values()) and thing not in things:
                    things.append(thing)
        survivors = []
        for thing in things:
            parsed = deepcopy(current)
            rename = {}
            several = False
            for subject, (holder_name, holder, _m) in named.items():
                keys = graph.keys_of(holder, thing) if holder is not None else []
                if len(keys) > 1:
                    # the holder counts the thing under two keys (in the truck, in the cart): which is not said
                    several = True
                    break
                key = keys[0] if keys else "%s %s" % (holder_name, graph.nodes[thing]["name"])
                # the holder and thing the key names, so the graph keeps the nodes (no string is split)
                rename[subject] = (key, {"holder": holder_name, "thing": key[len(holder_name) + 1:]})
            if several:
                self._candidate_dropped(2, "thing_alias", graph.nodes[thing]["name"], "several_keys")
                continue
            for fact in parsed.get("facts", []):
                if isinstance(fact.get("triple"), list) and fact["triple"][0] in rename:
                    fact["triple"][0], fact["parts"] = rename[fact["triple"][0]][0], dict(rename[fact["triple"][0]][1])
            label = ", ".join("%s -> %s" % (old, new[0]) for old, new in rename.items())
            failure, changes = self._reading_failure(parser, text, parsed)
            if failure is not None:
                self._candidate_dropped(2, "thing_alias", label, failure[1])
                continue
            known = all(row.get("before") is not None for row in changes if (row.get("delta") or 0) < 0)
            survivors.append({"label": label, "parsed": parsed, "fit": {"state": int(known), "cost": 1}})
        if not survivors:
            return None
        winner, _deciding, _ranking = self._rank_candidates(survivors, kind="thing_alias")
        return self._keep_reading(parser, text, winner, knowledge_path, "thing_alias")

    def _read_wrong_thing(self, parser, text, current, verbs, knowledge_path):
        """G7-S experiment 4, effort 2 (amendment A1): a statement read completely whose reading the state
        refuses, with a word in its thing slot that is a word of a thing this conversation counts or a declared
        counter (Nora gave Eli three bundles. for bundles of herbs): the word may be the thing, or not. A word
        that is neither (an unfamiliar thing said) is never taken out: the statement stays unread. Candidates:
        the reading as it is (the word is a new thing), and the reading with the word taken out of every
        holder's key, whose thing then comes from the conversation (``_unsaid_thing_candidates``: each thing a
        named holder counts, the thing of the statement before) or from the holder's one key (the leading
        words). The thing slot is found by position (the words every moved holder's key ends with, or those
        after the holder's name), never by a word list: any word may stand there. Each candidate is checked
        against the conversation (``_reading_failure``), ranked (``_rank_candidates``: state, every holder that
        loses some has a count before; context; cost, the word taken out and the thing put in), and a clear
        winner is kept for this conversation (``_keep_reading``); a tie or none returns None."""
        updates = parser.data.get("numeric_updates") or {}
        numeric = self._numeric_targets(parser)
        facts_now = [f for f in current.get("facts", []) if isinstance(f.get("triple"), list)
                     and isinstance(f["triple"][0], str) and f["triple"][1] in updates]
        if not facts_now or not self.observations or current.get("query"):
            return None
        try:
            facts, _d, _p, _r = self._cached_replay(parser, self.observations, self.fills)
            state, _c = current_facts(facts, parser.data.get("mutable_predicates", []), updates)
        except ValueError:
            return None
        keys = [row["triple"][0] for row in state if isinstance(row["triple"][0], str)
                and row["triple"][1] in numeric | {"count_unknown"} and len(row["triple"][0].split()) > 1]
        things = {key.split()[-1] for key in keys}
        holders = {" ".join(key.split()[:-1]) for key in keys}
        subjects = list(dict.fromkeys(f["triple"][0] for f in facts_now))
        split = [s.split() for s in subjects]
        if len(split) > 1:
            # the words every moved holder's key ends with
            size = 0
            while all(len(words) > size + 1 for words in split) and len({tuple(w[-size - 1:]) for w in split}) == 1:
                size += 1
        else:
            # the words after the longest holder name the conversation knows
            size = next((len(split[0]) - n for n in range(len(split[0]) - 1, 0, -1)
                         if " ".join(split[0][:n]) in holders), 0)
        word = split[0][-size:] if size else []
        if not word or word[-1] in things or any(s in keys for s in subjects):
            return None
        # Only a word of a thing this conversation counts, or a declared counter (three bundles for bundles of
        # herbs), may be no thing of its own. Any other word is a thing that was said and never counted: it
        # stays the thing, whatever its shape (singular or plural), and the statement is not read without it,
        # because that would move the count of another thing.
        counted_words = {w for key in keys for w in key.split()[1:]} | set(
            ((parser.language_pack or {}).get("counters") or {}).get("units") or [])
        if not all(w in counted_words for w in word):
            return None
        part = (getattr(parser, "ellipsis", None) or {}).get("part_reference")
        stripped = deepcopy(current)
        for fact in stripped.get("facts", []):
            if isinstance(fact.get("triple"), list) and fact["triple"][0] in subjects:
                fact["triple"][0] = " ".join(fact["triple"][0].split()[:-size])
                if part:
                    fact["resolve"] = part
        label = "without '%s' " % " ".join(word)
        survivors = self._unsaid_thing_candidates(parser, text, stripped, verbs, cost=1, label=label)
        if survivors is None:
            failure, changes = self._reading_failure(parser, text, stripped)
            if failure is not None:
                self._candidate_dropped(2, "wrong_thing", label.strip(), failure[1])
                survivors = []
            else:
                known = all(row.get("before") is not None for row in changes if (row.get("delta") or 0) < 0)
                survivors = [{"label": label.strip(), "parsed": stripped, "fit": {"state": int(known), "cost": 1}}]
        failure, changes = self._reading_failure(parser, text, current)
        if failure is not None:
            self._candidate_dropped(2, "wrong_thing", "as said", failure[1])
        else:
            known = all(row.get("before") is not None for row in changes if (row.get("delta") or 0) < 0)
            survivors.append({"label": "as said", "parsed": current, "fit": {"state": int(known), "cost": 0}})
        if not survivors:
            return None
        winner, _deciding, _ranking = self._rank_candidates(survivors, kind="wrong_thing")
        return self._keep_reading(parser, text, winner, knowledge_path, "wrong_thing")

    def _read_without_adjunct(self, parser, text, current, verbs, knowledge_path):
        """G7-S experiment 7, effort 3 (one repair step: a phrase that fills no slot; amendment A1): a use-up
        that names its holder and says what the things went to (Nora used three of them for a party., 병훈이
        그중 4개로 전시 작품을 만들었습니다., 한수가 그중 하나를 바자회 준비에 썼습니다.) reads as nothing, as an event
        of a verb not known, or only through a repair that misplaces a word. The purpose or product phrase may
        be any words. Candidates: the statement as read, and the statement read without one to three
        contiguous words that are no number, no word a repair may not change (a negation, a scope word, a
        counter) and no word of a holder or thing this conversation counts; a
        candidate must read as a use-up only (every amount it moves goes away) by a holder the conversation
        counts, and takes a thing it leaves out from the conversation (``_unsaid_thing_candidates``) or from the
        holder's one key. Each is checked against the conversation (``_reading_failure``), ranked
        (``_rank_candidates``: state, the holder's count covers the amount; cost, the words left out and a
        repair's own cost), and a clear winner is kept for this conversation (``_keep_reading``)."""
        from marco.language.numerals import parse_numeral
        updates = parser.data.get("numeric_updates") or {}
        numeric = self._numeric_targets(parser)
        try:
            facts, _d, _p, _r = self._cached_replay(parser, self.observations, self.fills)
            state, _c = current_facts(facts, parser.data.get("mutable_predicates", []), updates)
        except ValueError:
            return None
        keys = [row["triple"][0] for row in state if isinstance(row["triple"][0], str)
                and row["triple"][1] in numeric | {"count_unknown"} and len(row["triple"][0].split()) > 1]
        if not keys:
            return None
        known = {w.lower() for key in keys for w in key.split()}
        numerals = parser.data.get("numerals") or {}
        words = str(text).strip().split()
        tail = ""
        if words and words[-1][-1:] in ".!?" and len(words[-1]) > 1:
            tail, words = words[-1][-1], words[:-1] + [words[-1][:-1]]

        def protected(word):
            # never a word the reader's repairs may not change either (a negation, a scope word, a numeral, a
            # counter: 안 먹었어 is not 먹었어), nor a word of a holder or thing of the conversation
            bare = word.strip(",").lower()
            return (any(char.isdigit() for char in bare) or parse_numeral(bare, numerals) is not None
                    or parser._protected_kind(word) is not None
                    or any(bare.startswith(k) for k in known if len(k) > 1))

        def removing(row):
            return row[1] in updates and float((updates[row[1]] or {}).get("factor", 1) or 1) < 0
        survivors, seen = [], set()

        def offer(parsed, cost, label):
            rows = [f["triple"] for f in parsed.get("facts", []) if isinstance(f.get("triple"), list)]
            moved = [t for t in rows if t[1] in updates]
            if parsed.get("query") or not moved or not all(removing(t) and isinstance(t[0], str) for t in moved) \
                    or not all(any(k == t[0] or k.startswith(t[0] + " ") for k in keys) for t in moved):
                return
            found = self._unsaid_thing_candidates(parser, text, parsed, verbs, cost=cost, label=label)
            if found is None:
                failure, changes = self._reading_failure(parser, text, parsed)
                if failure is not None:
                    self._candidate_dropped(3, "adjunct", label.strip(), failure[1])
                    return
                known_before = all(row.get("before") is not None for row in changes if (row.get("delta") or 0) < 0)
                found = [{"label": label.strip(), "parsed": parsed, "fit": {"state": int(known_before), "cost": cost}}]
            for candidate in found:
                mark = json.dumps(sorted(json.dumps(f["triple"], ensure_ascii=False)
                                         for f in candidate["parsed"].get("facts", [])), ensure_ascii=False)
                if mark not in seen:
                    seen.add(mark)
                    survivors.append(candidate)
        if current is not None and current.get("facts"):
            offer(current, sum(int(r.get("cost") or 0) for r in current.get("수선") or []
                               if r.get("status") == "repaired"), "as said ")
        for size in (1, 2, 3, 4):
            for start in range(1, len(words) - size + 1):
                span = words[start:start + size]
                if len(words) - size < 2 or any(protected(word) for word in span):
                    continue
                said = " ".join(words[:start] + words[start + size:]) + tail
                parsed = parser.parse(said, partial=True, events=True, repair=True, verbs=verbs)
                if parsed and parsed.get("facts") and not any(
                        r.get("status") == "repaired" for r in parsed.get("수선") or []):
                    offer(parsed, size, "without '%s' " % " ".join(span))
        if not survivors:
            return None
        winner, _deciding, _ranking = self._rank_candidates(survivors, kind="adjunct")
        return self._keep_reading(parser, text, winner, knowledge_path, "adjunct")

    def _keep_reading(self, parser, text, winner, knowledge_path, reason):
        """A ranked winner kept as the statement's reading for this conversation (``chosen_readings``), the turn
        played with it; None, and nothing kept, when there is no winner or the turn is then not recorded."""
        if winner is None:
            return None
        text = _readings.tentative(text)
        said = text.oid
        parser.__dict__.setdefault("chosen_readings", {})[said] = winner["parsed"]
        self._replay_cache = None
        self._rereading = True
        try:
            result = self._turn(text, knowledge_path)
        finally:
            self._rereading = False
        if result is None or result.get("status") != "observed":
            parser.chosen_readings.pop(said, None)
            self._replay_cache = None
            return None
        result.setdefault("verification", {}).setdefault("checks", []).append({
            "ok": True, "reason": reason, "reading": winner["label"], "effort": self.effort})
        return result



    @staticmethod
    def _못잰까닭(까닭):
        """못 잰 까닭마다 제 문구. **남의 까닭을 빌려 쓰지 않는다.**

        멈추는 것은 맞아도 엉뚱한 설명을 붙이면 사용자는 없는 문제를 고치려
        든다 — 조건을 못 잰 것을 "나누어떨어지지 않는다" 고 말하는 식이다.
        여기 없는 까닭은 새로 생긴 까닭이므로, 아무 문구나 고르지 않고
        무엇을 못 했는지만 말하는 쪽으로 남긴다.
        """
        return {"기준": "unknown_basis", "나눔": "indivisible_amount",
                "조건": "unmeasured_condition", "lookup_missing": "unknown_lookup",
                "lookup_ambiguous": "ambiguous_lookup", "select_missing": "unknown_lookup",
                "select_ambiguous": "ambiguous_lookup",
                "condition_false": "condition_false",
                "condition_unknown": "unmeasured_condition"}.get(까닭, "unresolved")

    @staticmethod
    def _holds(parser, 조건들, start, 앞선사실, projection=None, actual_source=None, *, evidence_out=None):
        """이 자리에 걸린 조건이 참인가. 참/거짓/**못 잼(None)** 을 가른다.

        견줄 성질도 연산도 공리가 선언한다 — 여기는 어느 성질인지 모른 채 잰다.
        **차례를 지켜 앞선 사실까지만** 접어서 본다. 못 재면 거짓이라고 하지 않는다.

        Selected scoped conditions are fully re-verified against the own native projection
        before any evidence filter; without that authority they fail closed (None), never vacuous True.
        """
        scoped = [c for c in 조건들 if isinstance(c, dict)
                  and ("source_certificate" in c or "source_original" in c)]
        if scoped:
            if len(scoped) != len(조건들) or len(scoped) > 16 or type(start) is not int or start < 0:
                return None
            actual = _scoped_text(actual_source)
            if actual is None:
                return None
            for 조건 in scoped:
                if _scoped_text(조건.get("source_original")) != actual:
                    return None
            auth = _scoped_authority(projection, parser)
            cap = _scoped_cap(auth, "conditional_binary") if auth is not None else None
            if cap is None:
                return None
            verified = []
            for 조건 in scoped:
                got = _scoped_guard(parser, auth, cap, 조건, actual)
                if got is None:
                    return None
                verified.append(got)
            collect = (evidence_out if type(evidence_out) is dict and not evidence_out and len(scoped) == 1
                       else None)
            걸린것 = [c for c in scoped if c["evidence"]["end"] <= start]
            if not 걸린것:
                return True
            상태, _변화 = current_facts(앞선사실, parser.data.get("mutable_predicates", []),
                                     parser.data.get("numeric_updates", {}))
            결과 = []
            for 조건 in 걸린것:
                triple = list(조건["triple"])
                found = {row.get("polarity", True) for row in 상태
                         if isinstance(row, dict) and row.get("modality", "asserted") == "asserted"
                         and isinstance(row.get("triple"), (list, tuple)) and list(row["triple"]) == triple}
                결과.append(True if found == {True} else False if found == {False} else None)
                if (collect is not None and len(걸린것) == 1 and all(type(p) is bool for p in found)
                        and (not found or found == {True, False})):
                    ref = _scoped_compact(verified[0].get("source_ref"))
                    if _scoped_compact_ok(ref):
                        both = found == {True, False}
                        collect.update({"outcome": "conflicting_evidence" if both else "missing_premise",
                                        "guard_ref": ref, "positive_support": both,
                                        "negative_support": both})
            if False in 결과:
                return False
            if None in 결과:
                return None
            return True
        걸린것 = [c for c in 조건들 if c["evidence"].get("end", 0) <= start]
        if not 걸린것:
            return True
        표 = parser.data.get("comparisons", {})
        상태, _변화 = current_facts(앞선사실, parser.data.get("mutable_predicates", []),
                                 parser.data.get("numeric_updates", {}))
        for 조건 in 걸린것:
            주어, 술어, 값 = 조건["triple"]
            잼 = 표.get(술어)
            if 잼 is None or not str(값).isdecimal():
                return None
            지금 = next((row["triple"][2] for row in 상태
                       if row["triple"][0] == 주어 and row["triple"][1] == 잼["target"]), None)
            if 지금 is None or not str(지금).isdecimal():
                return None
            왼, 오 = int(지금), int(값)
            맞음 = (왼 > 오) if 잼["op"] == ">" else (왼 < 오) if 잼["op"] == "<" else (왼 == 오)
            if not 맞음:
                return False
        return True

    @staticmethod
    def _event_id(at, stem, 자리, 차례):
        """사건을 가리키는 이름. **글자 자리도 원문도 아니다.**

        몇 번째 말에서 · 어떤 낱말로 · 어떤 자리를 이미 짚은 · 몇 번째 사건인가.
        보완해도 이 넷은 안 바뀐다 — 보완이 원문을 고치지 않고 **빈 자리에 값을
        얹기만** 하기 때문이다. 원문도, 근거도, 그 사건의 차례와 그때의 뜻도
        건드리지 않는다.
        """
        return json.dumps([at, stem, sorted(자리.items()), 차례], ensure_ascii=False)

    def _live(self):
        """아직 답을 못 받은 되물음."""
        return [ask for ask in self.asked if not ask.get("해결")]

    def _settle(self, ask):
        """이 되물음은 답을 받았다. **베낀 기록이 아니라 이름으로** 지운다."""
        for kept in self.asked:
            if kept.get("id") == ask.get("id"):
                kept["해결"] = True

    def _refresh_role_asks(self, unsettled):
        """재생 결과를 기준으로 빈자리 되물음을 갱신한다.

        보완 한 번이 모든 실행 요건을 채웠다는 뜻은 아니다. 원문 사건 ID는
        그대로 두고, 재생기가 실제로 남긴 빈자리만 다음 되물음으로 유지한다.
        그래야 `한 자리 채움`과 `사건 실행 가능`을 같은 것으로 취급하지 않는다.
        """
        pending = {item["id"]: item for item in unsettled if item.get("id") is not None}
        for ask in self.asked:
            if ask.get("종류") not in ("빈자리", "조회"):
                continue
            item = pending.get(ask.get("사건"))
            if item is None:
                self._settle(ask)
                continue
            if ask.get("종류") == "조회":
                ask["필요"] = deepcopy(item.get("필요"))
                ask["해결"] = False
                continue
            if not item.get("빈자리"):
                self._settle(ask)
                continue
            ask["자리"] = dict(item["자리"])
            ask["빈자리"] = dict(item["빈자리"])
            ask["해결"] = False

    def _completion(self, parser, current, verbs, 사는것):
        """되물어 둔 자리를 채워 준 **문장**인가. 맞으면 (되물음, 채운 값)들을 준다.

        **되묻지 않았으면 안 잇는다.** 같은 동사에 자리 몇 개가 겹친다는 것만으로
        두 말을 한 사건으로 합치면, 묻지도 않고 남의 말을 고쳐 읽는 것이다.
        이미 알려진 역할이 같은 사건을 하나로 좁히고, 새 문장이 비어 있던
        역할을 적어도 하나 채울 때만 보완이다. 따라서 `민수가 베풀었다`처럼
        여러 미완성 사건 중 어느 것인지 모르는 말은 붙이지 않지만,
        `민수가 지연에게 베풀었다`처럼 수신자를 다시 짚은 말은 지연 사건의
        행위자만 먼저 채울 수 있다.
        """
        events = current.get("사건", [])
        if not 사는것 or not events or current["facts"] or current.get("정의"):
            return None
        남은, 기움 = list(사는것), []
        for event in events:
            # A reply can complete only an actual affirmative event.  The same
            # surface roles occur in a denial or a plan, but filling a missing
            # role must never turn either into an executed change.
            if event.get("polarity", True) is not True or event.get("modality", "asserted") != "asserted":
                return None
            stem = self._lookup(parser, event, set(), verbs)
            후보 = event.get("자리후보") or [event.get("자리", {})]
            matches = []
            for ask in 남은:
                for 자리 in 후보:
                    비었던 = set(ask["빈자리"].values())
                    채움 = {key: 자리[key] for key in 비었던 if key in 자리}
                    # 이미 있던 역할과 새 문장이 공통으로 가리킨 값이 사건의
                    # 닻이다. 후보가 여럿이면 이 닻 없이는 행위자 하나만으로
                    # 어느 사건인지 정할 수 없다.
                    닻 = set(자리) & set(ask["자리"])
                    맞음 = (ask["동사"] == stem and bool(채움)
                            and all(자리[key] == value for key, value in ask["자리"].items()
                                    if key in 자리)
                            and (len(남은) == 1 or bool(닻)))
                    if 맞음:
                        matches.append((ask, 채움))
            # 둘 이상의 사건·역할 읽기가 남으면, 이번 문장은 보완이 아니다.
            # 처음 맞은 것을 택하면 이후 상태를 틀리게 확정한다.
            if len(matches) != 1:
                return None
            selected = matches[0]
            남은.remove(selected[0])
            기움.append(selected)
        return 기움

    @staticmethod
    def _state_completion(current, asks):
        """Match one stated fact to one explicitly requested program need.

        This never treats a later fact as if it had existed at event time by
        itself.  The link is made only when the engine previously requested
        this exact fact for this exact event ID.
        """
        if (not current or current.get("query") or current.get("정의") or current.get("사건")
                or current.get("가정사건") or len(current.get("facts") or []) != 1):
            return None
        fact = list(current["facts"][0].get("triple") or [])
        if len(fact) != 3:
            return None
        matches = []
        for ask in asks:
            if ask.get("종류") != "조회" or not ask.get("필요"):
                continue
            need = ask["필요"]
            if need.get("kind") == "condition" and fact == need.get("fact"):
                matches.append((ask, {"사실": fact}))
            elif (need.get("kind") == "lookup"
                  and fact[:2] == [need.get("subject"), need.get("predicate")]):
                matches.append((ask, {"변수": need.get("into"), "값": fact[2], "사실": fact}))
            elif (need.get("kind") == "select"
                  and fact[1:] == [need.get("predicate"), need.get("value")]):
                matches.append((ask, {"변수": need.get("into"), "값": fact[0], "사실": fact}))
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _relation_completion(parser, text, asks):
        """Choose one bounded relationship occurrence already asked about.

        The pack owns ordinal spellings.  This routine only maps a declared
        ordinal onto the stored candidate list, so an arbitrary relation id
        can never be injected as an event fill.
        """
        open_asks = [ask for ask in asks if ask.get("종류") == "조회"
                     and not ask.get("해결")
                     and (ask.get("필요") or {}).get("kind") == "relation"]
        if len(open_asks) != 1:
            return None
        said = text.strip().rstrip(".!?…")
        choices = [index for index, words in (parser.relation_choice_words or {}).items()
                   if any(said == word for word in words)]
        if len(choices) != 1 or not str(choices[0]).isdigit():
            return None
        ask = open_asks[0]
        candidates = list((ask.get("필요") or {}).get("candidates") or [])
        index = int(choices[0])
        if not 0 <= index < len(candidates):
            return None
        return ask, {"변수": ask["필요"].get("into"), "값": candidates[index]}

    @staticmethod
    def _choice(text, 표):
        """적어 둔 낱말 가운데 어느 쪽을 말했나. 없으면 None — 넘겨짚지 않는다."""
        said = text.strip().rstrip(".!?…")
        # **앞부분만 보고 뒤를 안 읽으면 안 된다.** `정정 아냐` 가 `정정` 으로,
        # `바꾸지 마` 가 `바꿔` 로 실행된다. 적어 둔 말과 **그대로 같을 때만** 받는다.
        고른 = [name for name, words in (표 or {}).items()
              if any(word and said == word for word in words)]
        return 고른[0] if len(고른) == 1 else None

    def _answer_to_ask(self, parser, text, 사는것, 이름):
        """되물은 것에 대한 **짧은 답**인가. 무엇으로 못 쓰는지까지 돌려준다.

        받아들일 꼴은 정해 두었다 — 이름 **한 낱말**에, 언어팩이 적은 짧은 답
        꼬리나 조사가 붙은 것. 이것은 **지금 지원하는 범위**이지 자연어의 뜻을
        일반적으로 가려낸 것이 아니다. 낱말이 둘 이상이거나 물음표가 붙었거나
        꼬리가 낯설면 빈자리를 그대로 둔다.

        답이 **자리를 밝혔으면 그 자리를 지킨다.** `민수에게` 는 받는이를 말한
        것이지 누가 했는지를 말한 것이 아니다.
        """
        from marco.language.frames import particle_key, split_particle
        said = text.strip().rstrip(".!…")
        if not said or said != said.rstrip("?") or len(said.split()) != 1:
            return ("못씀", None, None)
        후보 = []
        조각 = split_particle(said, parser.case_particles, parser.slot_particles)
        if 조각 and 조각[0] in 이름:
            후보.append((조각[0], 조각[1]))
        꼬리들 = set(parser.short_tails)
        for name in 이름:
            if name and said.startswith(name) and said[len(name):] in 꼬리들:
                후보.append((name, None))
        if not 후보:
            return ("못씀", None, None)
        name, 역할 = max(후보, key=lambda pair: len(pair[0]))
        if len(사는것) != 1:
            return ("여럿", None, None)
        ask = 사는것[0]
        바라는 = next(iter(ask["빈자리"].values()))
        if 역할 is not None and particle_key(역할, parser.slot_particles) != 바라는:
            return ("역할다름", ask, (name, 역할))
        return ("채움", ask, (name, 바라는))

    def _permitted(self, knowledge_path):
        from marco.reasoning.state import _knowledge
        return (self.model.permits("relational_graph") if self.model is not None
                else "relational_graph" in _knowledge(knowledge_path)["axioms"])

    def _parser(self):
        if self._parser_instance is None:
            self._parser_instance = (RelationalParser(language=self.language) if self.model is None
                                     else self.model.parser())
            # the reader's own candidates (a declared question frame) are read from effort 1 on
            self._parser_instance.effort = self.effort
            self._grammar_cache = (self._parser_instance, _readings.grammar_fingerprint(self._parser_instance))
        return self._parser_instance

    def _grammar(self):
        """Fingerprint of the installed parser; a wrapper that installs a parser sets ``_grammar_cache``."""
        parser = self._parser()
        cached = getattr(self, "_grammar_cache", None)
        if cached is None or cached[0] is not parser:
            cached = self._grammar_cache = (parser, _readings.grammar_fingerprint(parser))
        return cached[1]

    # --- observation identity and the reading ledger ------------------------------------

    @property
    def observations(self):
        return self._obs

    @observations.setter
    def observations(self, items):
        self._commit_observations(list(items))

    @property
    def observation_ids(self):
        return [source.oid for source in self._obs]

    def _active_record(self, source):
        entry = self.reading_ledger.get(_readings.oid_of(source))
        return entry["versions"][entry["active"] - 1] if entry else None

    @staticmethod
    def _marked_carrier(parsed):
        """Require the one non-executing carrier shape of a marked parsed reading; raise otherwise.

        A marked reading may only be the ordinary parser container (its eleven fixed scope keys plus
        an optional ``entry_selection`` dict) whose only content is exactly one ``사건`` dict that
        carries BOTH ``structural_reading`` and ``selected_action_binding`` dicts, a read
        unknown-action reading, no tail, no truncation, no raw executable/marker key, and whose raw
        ``자리후보``/``자리`` correspond exactly to the reader's ``role_candidates`` in order.  Every
        original candidate, binding, span and binding declaration is preserved untouched.  Any other
        marked shape fails before full replay so the ledger can never hide an effect of a malformed
        carrier.  ``entry_selection`` is origin metadata only, never a semantic assertion.
        """
        bad = ReadingUnavailable("structural_archive_invalid")
        if type(parsed) is not dict:
            raise bad
        if ReasoningContext._unread_json(parsed, 65536) is None:
            raise bad
        empty_lists = ("facts", "정의", "가정사건", "조건", "가정", "원인", "이유물음", "수선", "사건정정")
        required = set(empty_lists) | {"query", "사건"}
        keys = set(parsed)
        if keys != required and keys != required | {"entry_selection"}:
            raise bad
        for key in empty_lists:
            if type(parsed[key]) is not list or parsed[key] != []:
                raise bad
        if parsed["query"] is not None:
            raise bad
        if "entry_selection" in parsed and type(parsed["entry_selection"]) is not dict:
            raise bad
        events = parsed["사건"]
        if type(events) is not list or len(events) != 1 or type(events[0]) is not dict:
            raise bad
        event = events[0]
        for marker in ("실행", "program", "negative", "hypothetical", "hypothesis"):
            if marker in event:
                raise bad
        if "polarity" in event and event["polarity"] is not True:
            raise bad
        if "modality" in event and (type(event["modality"]) is not str
                                   or event["modality"] != "asserted"):
            raise bad
        reading = event.get("structural_reading")
        binding = event.get("selected_action_binding")
        if type(reading) is not dict or type(binding) is not dict:
            raise bad
        if (reading.get("schema") != "unknown-action-reading-v1" or reading.get("status") != "read"
                or reading.get("search_complete") is not True or reading.get("truncated") is not False
                or type(reading.get("gaps")) is not list or reading.get("gaps") != []):
            raise bad
        verb = event.get("verb")
        unknown = reading.get("unknown_text")
        if type(verb) is not str or not verb or type(unknown) is not str or verb != unknown:
            raise bad
        tail = event.get("꼬리")
        if type(tail) is not str or tail != "" or event.get("잘림") is not False:
            raise bad
        candidates = reading.get("role_candidates")
        raw_maps = event.get("자리후보")
        raw_shared = event.get("자리")
        if (type(candidates) is not list or not candidates or type(raw_maps) is not list
                or len(raw_maps) != len(candidates) or type(raw_shared) is not dict):
            raise bad
        maps = []
        for candidate, raw_map in zip(candidates, raw_maps):
            if type(candidate) is not dict or type(raw_map) is not dict:
                raise bad
            bindings = candidate.get("bindings")
            if type(bindings) is not list or not bindings:
                raise bad
            row = {}
            for item in bindings:
                if type(item) is not dict:
                    raise bad
                slot, value = item.get("slot"), item.get("value")
                if type(slot) is not str or not slot or type(value) is not str or not value:
                    raise bad
                if slot in row:
                    raise bad
                row[slot] = value
            if not ReasoningContext._unread_native_equal(row, raw_map):
                raise bad
            maps.append(row)
        shared = {slot: value for slot, value in maps[0].items()
                  if all(slot in other and other[slot] == value for other in maps[1:])}
        if not ReasoningContext._unread_native_equal(shared, raw_shared):
            raise bad
        return parsed

    @staticmethod
    def _structural_marked(item):
        """True when a parsed reading or event carries any structural marker (presence only)."""
        if not isinstance(item, dict):
            return False
        if "structural_reading" in item or "selected_action_binding" in item:
            return True
        run = item.get("실행")
        if isinstance(run, dict) and ("structural_reading" in run or "selected_action_binding" in run):
            return True
        events = item.get("사건")
        return isinstance(events, list) and any(
            isinstance(event, dict) and ReasoningContext._structural_marked(event) for event in events)

    def _marked_archive(self, source):
        """The actual active archived reading of ``source`` when it carries a structural marker.

        None when the source is not an archived observation or its active reading has no marker.
        A marker found on a record whose identity does not check out fails honestly.
        """
        oid = _readings.oid_of(source)
        if not isinstance(source, Obs) or type(oid) is not str or not oid.strip() or oid == TENTATIVE:
            return None
        held = self.reading_ledger.get(oid)
        if type(held) is not dict:
            return None
        try:
            record = self._active_record(source)
        except (KeyError, IndexError, TypeError):
            record = None
        if type(record) is not dict:
            versions = held.get("versions")
            if isinstance(versions, list) and any(
                    type(version) is dict and self._structural_marked(version.get("parsed"))
                    for version in versions):
                raise ReadingUnavailable("structural_archive_invalid")
            return None
        parsed = record.get("parsed")
        if not self._structural_marked(parsed):
            return None
        revision = record.get("reading_revision")
        archived = record.get("source")
        if (type(revision) is not int or revision < 1
                or type(held.get("active")) is not int or revision != held.get("active")
                or type(getattr(source, "rev", None)) is not int or source.rev != revision
                or type(record.get("observation_id")) is not str or record.get("observation_id") != oid
                or record.get("unavailable") is not False or type(archived) is not str
                or archived != str(source)):
            raise ReadingUnavailable("structural_archive_invalid")
        self._marked_carrier(parsed)
        return {"source": source, "record": record, "parsed": parsed}

    def _marked_archive_events(self):
        """Raw marked events of the actual active archives of this conversation's observations."""
        out = []
        for index, source in enumerate(self.observations):
            found = self._marked_archive(source)
            if found is None:
                continue
            for ordinal, raw in enumerate(found["parsed"]["사건"]):
                if type(raw) is not dict:
                    raise ReadingUnavailable("structural_archive_invalid")
                if self._structural_marked(raw):
                    out.append({"index": index, "ordinal": ordinal, "raw": raw,
                                "parsed": found["parsed"], "record": found["record"]})
        return out

    def _marker_sources(self, parser, sources):
        """Refusal gate only: any supplied source whose archive, staged or chosen reading carries a marker.

        Every supplied source is validated (no early return).  A committed marked source requires the
        installed chosen view to exist and equal its actual archived parsed reading exactly; a proper
        ``correct()`` trial (old actual observation, rev == active + 1, reason ``correction``, explicit
        staged reading) requires the chosen view to equal that staged reading.  Any missing or drifted
        view fails honestly; nothing here repairs, rewrites or allocates.
        """
        bad = ReadingUnavailable("structural_archive_invalid")
        chosen = getattr(parser, "chosen_readings", None) or {}
        marked = False
        for source in sources:
            staged = getattr(source, "reading", None)
            oid = _readings.oid_of(source)
            view = chosen.get(oid) if isinstance(chosen, dict) and oid is not None else None
            staged_marked = self._structural_marked(staged)
            view_marked = self._structural_marked(view)
            if staged_marked:
                self._marked_carrier(staged)
            if view_marked:
                self._marked_carrier(view)
            held = (self.reading_ledger.get(oid)
                    if isinstance(source, Obs) and type(oid) is str and oid.strip() and oid != TENTATIVE
                    else None)
            if type(held) is not dict:
                # staged/tentative or unarchived: refusal-only, no admission or provenance
                marked = marked or staged_marked or view_marked
                continue
            active = held.get("active")
            rev = getattr(source, "rev", None)
            if (getattr(source, "reason", None) == "correction" and staged is not None
                    and type(active) is int and type(rev) is int and rev == active + 1):
                # separately authorized correct() trial: check the ACTUAL old observation, not the staged one
                old = next((obs for obs in self.observations
                            if isinstance(obs, Obs) and _readings.oid_of(obs) == oid
                            and getattr(obs, "rev", None) == active), None)
                if old is None:
                    if staged_marked or view_marked:
                        raise bad
                    continue
                old_marked = self._marked_archive(old) is not None
                if not (staged_marked or view_marked or old_marked):
                    continue
                if (view is None or self._unread_json(staged, 65536) is None
                        or not self._unread_native_equal(view, staged)):
                    raise bad
                marked = True
                continue
            archive_marked = self._marked_archive(source) is not None
            if not (archive_marked or staged_marked or view_marked):
                continue
            try:
                record = self._active_record(source)
            except (KeyError, IndexError, TypeError):
                record = None
            if (type(record) is not dict or type(active) is not int or type(rev) is not int
                    or rev != active or record.get("reading_revision") != active
                    or type(record.get("observation_id")) is not str or record.get("observation_id") != oid
                    or record.get("unavailable") is not False or type(record.get("source")) is not str
                    or record.get("source") != str(source)):
                raise bad
            parsed = record.get("parsed")
            if (view is None or self._unread_json(parsed, 65536) is None
                    or not self._unread_native_equal(view, parsed)):
                raise bad
            marked = True
        return marked

    def _unread_marked(self, entry):
        """An unread entry bound to a marked source stays held; malformed marked binding stays held too."""
        candidates = []
        at = entry.get("at") if isinstance(entry, dict) else None
        obs = getattr(self, "_obs", None)
        if type(at) is int and isinstance(obs, (list, tuple)) and 0 <= at < len(obs):
            candidates.append(obs[at])
        if isinstance(entry, dict) and isinstance(entry.get("source"), Obs):
            candidates.append(entry["source"])
        for source in candidates:
            if self._structural_marked(getattr(source, "reading", None)):
                return True
            try:
                if self._marked_archive(source) is not None:
                    return True
            except ReadingUnavailable:
                return True
        return False

    def _archive(self, oid, revision, item, parsed, reason, prior):
        """Append one reading version (raw parsed JSON plus source binding) and make it the active one."""
        try:
            parsed = json.loads(json.dumps(parsed, allow_nan=False)) if parsed is not None else None
        except (TypeError, ValueError):
            parsed = deepcopy(parsed)
        held = self.reading_ledger.get(oid)
        if len(held["versions"] if held else ()) != revision - 1 or sum(
                len(e["versions"]) for e in self.reading_ledger.values()) >= self.max_turns * 8:
            raise ValueError("reading_capacity")
        entry = self.reading_ledger.setdefault(oid, {"active": revision, "versions": []})
        entry["versions"].append(_readings.make_record(
            oid, revision, item, parsed, base=self.parser_base_sha256, head=self.installed_memory_head,
            reason="unavailable" if parsed is None else reason, prior=prior, unavailable=parsed is None,
            grammar=self._grammar()))
        entry["active"] = revision
        view = self._parser().__dict__.setdefault("chosen_readings", {})
        if parsed is None:
            view.pop(oid, None)
        else:
            view[oid] = deepcopy(parsed)
        return Obs(str(item), oid, revision)

    def _commit_observations(self, items):
        """The one place observation slots are created, revised or dropped; keeps IDs and ledger aligned."""
        if not items and not self._obs and not self.reading_ledger:
            return
        parser = self._parser()
        view = parser.__dict__.setdefault("chosen_readings", {})
        provisional = (view.pop(TENTATIVE, None)
                       if any(_readings.oid_of(i) == TENTATIVE for i in items) else None)
        verbs, out = None, []
        for item in items:
            oid = _readings.oid_of(item)
            entry = self.reading_ledger.get(oid) if oid not in (None, TENTATIVE) else None
            if entry is not None and getattr(item, "rev", entry["active"]) <= entry["active"]:
                out.append(Obs(str(item), oid, entry["active"]))
                continue
            parsed = getattr(item, "reading", None)
            reason = getattr(item, "reason", None)
            if entry is None:
                reason = reason or "initial"
                if oid == TENTATIVE and provisional is not None:
                    parsed, reason, provisional = provisional, "candidate_reading", None
            if parsed is None:
                if verbs is None:
                    verbs = self._verbs_for(parser, items)
                parsed = self._read_source(parser, str(item), events=True, verbs=verbs)
            if entry is None:
                oid = "o%d" % self._next_observation
                self._next_observation += 1
                out.append(self._archive(oid, 1, item, parsed, reason, None))
            else:
                out.append(self._archive(oid, entry["active"] + 1, item, parsed, reason or "correction",
                                         [oid, entry["active"]]))
        live = {source.oid for source in out}
        for gone in set(self.reading_ledger) - live:
            self.reading_ledger.pop(gone)
            view.pop(gone, None)
        self._obs = out

    def _revise_readings(self, updates, reason):
        """Explicit reading revisions of named slots ({oid: raw reading}); other slots are untouched."""
        for index, source in enumerate(self._obs):
            if source.oid in updates:
                entry = self.reading_ledger[source.oid]
                self._obs[index] = self._archive(source.oid, entry["active"] + 1, source,
                                                 updates[source.oid], reason, [source.oid, entry["active"]])
        self._replay_cache = None

    def _verbs_for(self, parser, sources):
        """이전 관찰 접두어의 활용표는 유지하고, 새 원문만 더 읽는다."""
        source_key = tuple(sources)
        grammar = self._grammar()
        if self._verb_cache is not None and (len(self._verb_cache) < 4 or self._verb_cache[3] != grammar):
            self._verb_cache = None     # forms derived under another installed grammar are never reused
        if self._verb_cache is not None and self._verb_cache[0] == source_key:
            return deepcopy(self._verb_cache[2])
        if (self._verb_cache is not None
                and source_key[:len(self._verb_cache[0])] == self._verb_cache[0]):
            stems = set(self._verb_cache[1])
            for source in source_key[len(self._verb_cache[0]):]:
                parsed = self._definitions_read(parser, source)
                if parsed is not None:
                    stems.update(rule["verb"] for rule in parsed.get("정의", []))
            forms = self._forms_of(parser, stems)
        elif (self._verb_cache is not None and len(source_key) == len(self._verb_cache[0])
              and source_key[:-1] == self._verb_cache[0][:-1]):
            # A role reply or query is not an observation.  Consecutive
            # transient inputs share the persisted observation prefix; parse
            # only the new final input instead of treating that sibling cache
            # key as a reason to reread the whole conversation.
            stems = set(self._verb_cache[1])
            parsed = self._definitions_read(parser, source_key[-1])
            if parsed is not None:
                stems.update(rule["verb"] for rule in parsed.get("정의", []))
            forms = self._forms_of(parser, stems)
        else:
            stems = set()
            for source in source_key:
                parsed = self._definitions_read(parser, source)
                if parsed is not None:
                    stems.update(rule["verb"] for rule in parsed.get("정의", []))
            forms = self._forms_of(parser, stems)
        self._verb_cache = (source_key, frozenset(stems), deepcopy(forms), grammar)
        return forms

    @staticmethod
    def _incremental_source(parser, source):
        """앞 상태를 바꾸지 않는 직접 사실 원문만 접두어 재사용 대상으로 삼는다.

        정의·배운 사건·조건은 앞 원문의 뜻이나 이후 상태에 닿을 수 있다. 그것을
        억지로 부분 계산하지 않고 기존 전체 재생으로 돌려 안전성을 지킨다.
        """
        parsed = ReasoningContext._read_source(parser, source, events=True, verbs=set())
        return (parsed is not None and not parsed.get("정의") and not parsed.get("사건")
                and not parsed.get("조건"))

    def _incremental_replay(self, parser, key, sources, fills):
        """직접 사실열의 추가·교정은 바뀐 꼬리만 다시 읽는다.

        반환값 ``None``은 부분 재생을 증명할 수 없다는 뜻이며, 호출자는 반드시
        완전 재생으로 되돌아간다. 따라서 빠른 길이 의미 보존보다 우선하지 않는다.
        """
        # A restored semantic ledger has stronger continuation paths below.
        # Do not let the older text-oriented optimisation inspect its changed
        # suffix first, because that would parse historical observations.
        if self._stored_event_records is not None:
            return None
        cached = self._replay_cache
        if cached is None or len(cached) != 3:
            return None
        old_key, old_result, reusable = cached
        old_sources, old_fills = old_key
        if old_fills != key[1] or old_result[2]:
            return None
        new_sources = tuple(sources)
        is_append = False
        if new_sources[:len(old_sources)] == old_sources:
            start = len(old_sources)
            is_append = True
        elif len(new_sources) == len(old_sources):
            differences = [index for index, pair in enumerate(zip(old_sources, new_sources))
                           if pair[0] != pair[1]]
            if len(differences) != 1:
                return None
            start = differences[0]
        else:
            return None
        if not all(self._incremental_source(parser, source) for source in new_sources[start:]):
            return None
        direct_flags = tuple(reusable.get("direct", ()))
        # 새 직접 사실을 끝에 붙이는 일은 앞서 확정된 배운 동작·조건의 과거
        # 의미를 바꾸지 않는다. 중간 교정도 **그 지점 뒤가 모두 직접 사실**이면
        # 앞의 복잡한 결과는 고정하고 영향 꼬리만 다시 접을 수 있다. 반대로
        # 뒤에 배운 동작·조건·보완이 있으면 그 의미가 바뀔 수 있어 전체로 간다.
        if not reusable["append"] or (not is_append and not all(direct_flags[start:])):
            return None
        # 앞 구간은 이미 원문 근거(turn/source 포함)까지 검증된 직접 사실이다.
        # 교정점 뒤만 새로 읽고 붙이면, 현재 상태 접기는 바뀐 값의 의존 꼬리만
        # 다시 적용한다.
        facts = [deepcopy(item) for item in old_result[0]
                 if item.get("evidence", {}).get("turn", -1) < start]
        for index, source in enumerate(new_sources[start:], start):
            parsed = self._read_source(parser, source, events=True, verbs=set())
            for item in parsed.get("facts", []):
                item = deepcopy(item)
                item["evidence"].update(turn=index, source=source)
                facts.append(item)
        return facts, deepcopy(old_result[1]), [], set(old_result[3])

    def _append_semantic_replay(self, parser, key, sources, fills):
        """Apply one new, fully understood observation to saved semantics.

        This path is intentionally narrow: it is used only when the saved
        timeline has no unresolved event and the new source has neither a
        definition nor a condition that could reinterpret earlier material.
        The old event programs/facts are copied from the replay record; only
        the newly typed source is parsed.  More complex edits still take the
        conservative correction replay path.
        """
        if self._stored_event_records is None:
            return None
        cached = self._replay_cache
        if cached is None or len(cached) != 3:
            return None
        old_key, old_result, _reusable = cached
        old_sources, old_fills = old_key
        new_sources = tuple(sources)
        if (old_fills != key[1] or old_result[2] or len(new_sources) != len(old_sources) + 1
                or new_sources[:-1] != old_sources):
            return None
        index, source = len(old_sources), new_sources[-1]
        definitions = DefinitionTable(deepcopy(dict(old_result[1])),
                                      deepcopy(getattr(old_result[1], "programs", {})))
        forms = self._forms_of(parser, definitions)
        parsed = self._read_source(parser, source, events=True, verbs=forms)
        if (parsed is None or parsed.get("정의") or parsed.get("원인")
                or parsed.get("이유물음") or parsed.get("가정") or parsed.get("가정사건")):
            return None
        facts, pending = deepcopy(old_result[0]), []
        names = {part for row in facts for part in str(row["triple"][0]).split()}
        role_fills, value_fills, fact_fills, overrides = {}, {}, {}, []
        for fill in fills:
            if fill.get("범위") in ("앞으로", "설명정정", "이번만"):
                overrides.append(fill)
            elif fill.get("변수"):
                value_fills.setdefault(fill["사건"], {})[fill["변수"]] = fill["값"]
            elif fill.get("사실"):
                fact_fills.setdefault(fill["사건"], []).append(fill["사실"])
            else:
                role_fills.setdefault(fill["사건"], {})[fill["역할"]] = fill["값"]

        def event_overrides(event_id, stem):
            return {fill["역할"]: fill["값"] for fill in overrides
                    if ((fill["범위"] == "이번만" and fill.get("사건") == event_id)
                        or (fill["범위"] == "앞으로" and fill.get("동사") == stem
                            and index >= fill.get("부터", 0))
                        or (fill["범위"] == "설명정정" and fill.get("동사") == stem))}

        rows = []
        for ordinal, raw in enumerate(parsed.get("사건", [])):
            stem = self._lookup(parser, raw, definitions, forms)
            rule = definitions.get(stem) if stem else None
            slot = "%d:%d" % (index, ordinal)
            event_id = (self._event_id(index, stem, raw.get("자리", {}), ordinal)
                        if self.event_ids is None else self.event_ids.setdefault(slot, "event:%s" % slot))
            if rule is None:
                # An unknown new event must remain observable and block the
                # affected state; use the existing full path that records it.
                return None
            received, overridden = role_fills.get(event_id, {}), event_overrides(event_id, stem)
            supplied, supplied_facts = value_fills.get(event_id, {}), fact_fills.get(event_id, [])
            from marco.reasoning.actions import event_record
            envelope = event_record(event_id, rule["프로그램"], raw, sequence=index,
                                    evidence=raw.get("evidence"), fills=received,
                                    overrides=overridden, state_fills=supplied_facts)
            if raw.get("polarity") is False:
                continue
            applied = self._triples(parser, rule, {**raw, "실행": envelope}, names, received,
                                    overridden, facts + [row for _start, row in rows],
                                    programs=definitions.programs, 조회값=supplied,
                                    조회사실=supplied_facts)
            if (applied["빈자리"] or applied["충돌"] or applied["헛자리"]
                    or raw.get("잘림") or applied.get("못잼")):
                pending.append({"text": source, "at": index, "동사": stem, "id": event_id,
                                "잘림": bool(raw.get("잘림")), "차례": index,
                                "못잼": applied.get("못잼"),
                                "거짓조건": applied.get("못잼") == "condition_false",
                                "조각": raw.get("evidence"), "자리": dict(raw.get("자리") or {}),
                                "빈자리": applied["빈자리"], "충돌": applied["충돌"],
                                "헛자리": applied["헛자리"], "닿는곳": applied["닿는곳"],
                                "필요": applied.get("필요"), "실행": envelope})
                continue
            truth = self._holds(parser, parsed.get("조건", []),
                                raw.get("evidence", {}).get("start", 0),
                                facts + [row for _start, row in rows],
                                getattr(self.model, "language_projection", None),
                                actual_source=source)
            if truth is None:
                pending.append({"text": source, "at": index, "동사": stem, "id": event_id,
                                "잘림": bool(raw.get("잘림")), "차례": index,
                                "못잼": "조건", "거짓조건": False,
                                "조각": raw.get("evidence"), "자리": dict(raw.get("자리") or {}),
                                "빈자리": {}, "충돌": {}, "헛자리": {},
                                "닿는곳": applied["닿는곳"], "필요": None, "실행": envelope})
                continue
            if truth is False:
                continue
            modality = {"modality": raw["modality"]} if raw.get("modality") else {}
            rows.extend((raw.get("evidence", {}).get("start", 0),
                         {"triple": triple, **modality,
                          "evidence": {**raw.get("evidence", {}), "turn": index, "source": source,
                                       "action_event": envelope}})
                        for triple in applied["사실"])
        for item in parsed.get("facts", []):
            item = deepcopy(item)
            item["evidence"].update(turn=index, source=source)
            rows.append((item["evidence"].get("start", 0), item))
        facts.extend(row for _start, row in sorted(rows, key=lambda row: row[0]))
        return facts, definitions, pending, set(old_result[3])

    def _append_semantic_definition(self, parser, key, sources, fills):
        """Add one newly taught definition without rereading old dialogue.

        A definition changes what *future* surface actions can mean.  It does
        not reinterpret stored programs or direct facts just because it has
        the same verb as an older rule.  The saved definition table is thus
        the execution authority; only the new definition body is parsed and
        compiled here.
        """
        if self._stored_event_records is None:
            return None
        cached = self._replay_cache
        if cached is None or len(cached) != 3:
            return None
        old_key, old_result, _reusable = cached
        old_sources, old_fills = old_key
        new_sources = tuple(sources)
        if (old_fills != key[1] or old_result[2]
                or len(new_sources) != len(old_sources) + 1
                or new_sources[:-1] != old_sources):
            return None
        index, source = len(old_sources), new_sources[-1]
        # Archived raw events whose action had no definition when they were
        # read are not ``pending`` and so are invisible to the check above.
        # A definition that now covers one of them must not leave it a no-op:
        # decline the shortcut so the full archived-reading replay (ledger
        # readings, same event ids, no reparse of historical text) applies it.
        # Surface forms (e.g. inflections) may map to a new stem only through
        # the full replay, so any programless uninterpreted event declines.
        if any(isinstance(row, dict) and row.get("status") == "uninterpreted"
               and isinstance(row.get("event"), dict) and not row["event"].get("program")
               for row in self._stored_event_records):
            return None
        prior = DefinitionTable(deepcopy(dict(old_result[1])),
                                deepcopy(getattr(old_result[1], "programs", {})))
        parsed = self._read_source(parser, source, events=True,
                                   verbs=self._forms_of(parser, prior))
        if (parsed is None or not parsed.get("정의") or parsed.get("facts")
                or parsed.get("사건") or parsed.get("조건") or parsed.get("가정")
                or parsed.get("가정사건")):
            return None
        # Reconstruct only the already compiled semantic table.  `_rule`
        # reads this just-added body, while its references point to saved
        # programs rather than to historical definition text.
        prior_versions = {}
        for stem, rule in prior.items():
            version = (rule.get("프로그램") or {}).get("definition_version")
            prior_versions[stem] = 0 if version is None else version
        learned = {"뜻": {stem: rule.get("유도") for stem, rule in prior.items()
                          if isinstance(rule.get("유도"), dict)},
                   "때": prior_versions,
                   "꼴": {surface: found["stem"] for surface, found in
                            self._forms_of(parser, prior).items() if not found["물음"]}}
        definitions = DefinitionTable(deepcopy(dict(prior)), deepcopy(prior.programs))
        read = set(old_result[3])
        for rule in parsed["정의"]:
            usable = self._rule(parser, rule, learned)
            if usable is None:
                return None
            usable["프로그램"] = {**usable["프로그램"], "definition_version": index}
            definitions[rule["verb"]] = usable
            definitions.programs["%s@%s" % (rule["verb"], index)] = usable["프로그램"]
            read.add(rule.get("몸통"))
            learned["뜻"][rule["verb"]] = usable.get("유도")
            learned["때"][rule["verb"]] = index
        return deepcopy(old_result[0]), definitions, deepcopy(old_result[2]), read

    def _resume_semantic_replay(self, parser, key, sources, fills):
        """Re-run end-of-timeline pending events from their saved envelopes.

        A clarification changes a fill, not the original utterance.  If every
        affected pending event is at the end of the saved timeline, its
        recorded program and pre-event facts are sufficient to resume without
        parsing historical text.  Older/interleaved pending events deliberately
        fall back to the conservative replay path because their later
        dependencies need a full semantic timeline.
        """
        if self._stored_event_records is None:
            return None
        cached = self._replay_cache
        if cached is None or len(cached) != 3:
            return None
        old_key, old_result, _reusable = cached
        old_sources, _old_fills = old_key
        if tuple(sources) != old_sources or not old_result[2]:
            return None
        index = len(old_sources) - 1
        if any(item.get("at") != index or not isinstance(item.get("실행"), dict)
               for item in old_result[2]):
            return None
        definitions = DefinitionTable(deepcopy(dict(old_result[1])),
                                      deepcopy(getattr(old_result[1], "programs", {})))
        facts, pending = deepcopy(old_result[0]), []
        role_fills, value_fills, fact_fills = {}, {}, {}
        for fill in fills:
            if fill.get("범위") in ("앞으로", "설명정정", "이번만"):
                continue
            if fill.get("변수"):
                value_fills.setdefault(fill["사건"], {})[fill["변수"]] = fill["값"]
            elif fill.get("사실"):
                fact_fills.setdefault(fill["사건"], []).append(fill["사실"])
            else:
                role_fills.setdefault(fill["사건"], {})[fill["역할"]] = fill["값"]
        for item in old_result[2]:
            envelope = deepcopy(item["실행"])
            program = envelope.get("program")
            event_id = envelope.get("id")
            if not isinstance(program, dict) or not isinstance(event_id, str):
                return None
            raw = {"자리": deepcopy(envelope.get("roles") or {}),
                   "자리후보": deepcopy(envelope.get("role_candidates") or []),
                   "polarity": envelope.get("polarity", True),
                   "modality": envelope.get("modality", "asserted"),
                   "evidence": deepcopy(envelope.get("evidence") or {}), "실행": envelope}
            names = {part for row in facts for part in str(row["triple"][0]).split()}
            applied = self._triples(parser, {"프로그램": program}, raw, names,
                                    role_fills.get(event_id, {}), (), facts,
                                    programs=definitions.programs,
                                    조회값=value_fills.get(event_id, {}),
                                    조회사실=fact_fills.get(event_id, []))
            if (applied["빈자리"] or applied["충돌"] or applied["헛자리"]
                    or applied.get("못잼")):
                pending.append({**deepcopy(item), "빈자리": applied["빈자리"],
                                "충돌": applied["충돌"], "헛자리": applied["헛자리"],
                                "닿는곳": applied["닿는곳"], "못잼": applied.get("못잼"),
                                "필요": applied.get("필요")})
                continue
            for triple in applied["사실"]:
                facts.append({"triple": triple,
                              # The stored envelope is the authority for an
                              # resumed event.  In particular, a completed
                              # plan must remain a plan after restart; leaving
                              # this field out made `current_facts` treat its
                              # otherwise identical effects as asserted.
                              "polarity": raw.get("polarity", True),
                              "modality": raw.get("modality", "asserted"),
                              "evidence": {**raw["evidence"], "turn": index,
                                           "source": old_sources[index], "action_event": envelope}})
        return facts, definitions, pending, set(old_result[3])

    def _semantic_correction_replay(self, parser, key, sources, fills):
        """Rebuild a direct-fact correction from saved facts and event programs.

        The replacement itself is parsed, but historical definitions/actions
        come exclusively from their persisted envelopes.  This deliberately
        covers the common state-correction case; definition/condition edits
        retain the existing conservative source replay because they change
        language meaning rather than only a fact value.
        """
        cached = self._replay_cache
        if cached is None or self._stored_event_records is None:
            return None
        old_key, old_result, _reusable = cached
        old_sources, old_fills = old_key
        new_sources = tuple(sources)
        if old_fills != key[1] or len(new_sources) != len(old_sources) or old_result[2]:
            return None
        # Same guard as ``_append_semantic_definition``: an archived raw event whose action had no
        # program when it was read is replayed only from its ledger reading.  This shortcut rebuilds
        # from stored envelopes alone, so it would silently drop that event's effects (the records
        # stay programless even after a later definition covered them).  Decline; the full
        # archived-reading replay keeps the same event ids and does not reparse historical text.
        if any(isinstance(row, dict) and row.get("status") == "uninterpreted"
               and isinstance(row.get("event"), dict) and not row["event"].get("program")
               for row in self._stored_event_records):
            return None
        changed = [at for at, pair in enumerate(zip(old_sources, new_sources)) if pair[0] != pair[1]]
        if len(changed) != 1:
            return None
        at = changed[0]
        forms = self._forms_of(parser, old_result[1])
        replacement = self._read_source(parser, new_sources[at], events=True, verbs=forms)
        replacement_events = None
        if replacement and replacement.get("사건"):
            if (replacement.get("정의") or replacement.get("facts") or replacement.get("조건")
                    or replacement.get("가정") or replacement.get("가정사건")):
                return None
            originals = [deepcopy(record["event"]) for record in self._stored_event_records
                         if isinstance(record, dict) and isinstance(record.get("event"), dict)
                         and record["event"].get("sequence") == at]
            raws = replacement["사건"]
            if (len(originals) != len(raws)
                    or any(old.get("action") != self._lookup(parser, raw, set(), forms)
                           for old, raw in zip(originals, raws))):
                return None
            from marco.reasoning.actions import event_record
            replacement_events = [event_record(
                old["id"], old["program"], raw, sequence=at, evidence=raw.get("evidence"),
                fills=old.get("fills") or {}, overrides=old.get("overrides") or {},
                state_fills=old.get("state_fills") or (), conditions=[])
                for old, raw in zip(originals, raws)]
        if (replacement is None or (replacement.get("사건") and replacement_events is None)
                or replacement.get("조건") or replacement.get("가정")
                or replacement.get("가정사건")
                or (not replacement.get("facts") and replacement_events is None)):
            # A corrected definition is semantic input, not a request to
            # parse old definitions/actions again.  Recompile just the
            # replacement and replay the saved envelopes which captured that
            # definition version.  This deliberately leaves later
            # redefinitions and their events alone.
            if not (replacement and len(replacement.get("정의") or []) == 1
                    and not replacement.get("사건") and not replacement.get("조건")
                    and not replacement.get("facts")):
                return None
            changed_rule = replacement["정의"][0]
            prior = DefinitionTable(deepcopy(dict(old_result[1])),
                                    deepcopy(getattr(old_result[1], "programs", {})))
            learned = {"뜻": {stem: rule.get("유도") for stem, rule in prior.items()
                              if stem != changed_rule["verb"] and isinstance(rule.get("유도"), dict)},
                       "때": {stem: (rule.get("프로그램") or {}).get("definition_version", 0)
                              for stem, rule in prior.items() if stem != changed_rule["verb"]},
                       "꼴": {surface: found["stem"] for surface, found in
                                self._forms_of(parser, prior).items() if not found["물음"]}}
            usable = self._rule(parser, changed_rule, learned)
            if usable is None:
                return None
            usable["프로그램"] = {**usable["프로그램"], "definition_version": at}
            definitions = DefinitionTable(deepcopy(dict(prior)), deepcopy(prior.programs))
            definitions[changed_rule["verb"]] = usable
            definitions.programs["%s@%s" % (changed_rule["verb"], at)] = usable["프로그램"]
            direct, events = {}, []
            for fact in old_result[0]:
                evidence = fact.get("evidence") or {}
                if not evidence.get("action_event") and type(evidence.get("turn")) is int:
                    direct.setdefault(evidence["turn"], []).append(deepcopy(fact))
            for record in self._stored_event_records:
                event = record.get("event") if isinstance(record, dict) else None
                if not (isinstance(event, dict) and record.get("status") == "executed"
                        and isinstance(event.get("program"), dict)):
                    continue
                copied = deepcopy(event)
                if (copied.get("action") == changed_rule["verb"]
                        and copied.get("definition_version") == at):
                    copied["program"] = deepcopy(usable["프로그램"])
                events.append(copied)
            facts, pending = [], []
            for turn in range(len(new_sources)):
                facts.extend(deepcopy(direct.get(turn, [])))
                for event in sorted((row for row in events if row.get("sequence") == turn),
                                    key=lambda row: row.get("id", "")):
                    raw = {"자리": deepcopy(event.get("roles") or {}),
                           "자리후보": deepcopy(event.get("role_candidates") or []),
                           "polarity": event.get("polarity", True),
                           "modality": event.get("modality", "asserted"),
                           "evidence": deepcopy(event.get("evidence") or {}), "실행": event}
                    names = {part for row in facts for part in str(row["triple"][0]).split()}
                    applied = self._triples(parser, {"프로그램": event["program"]}, raw, names,
                                            event.get("fills") or {}, event.get("overrides") or {}, facts,
                                            programs=definitions.programs,
                                            조회사실=event.get("state_fills") or ())
                    if (applied["빈자리"] or applied["충돌"] or applied["헛자리"]
                            or applied.get("못잼")):
                        return None
                    for triple in applied["사실"]:
                        facts.append({"triple": triple, "polarity": raw["polarity"],
                                      "modality": raw["modality"],
                                      "evidence": {**raw["evidence"], "turn": turn,
                                                   "source": new_sources[turn], "action_event": event}})
            return facts, definitions, pending, set(old_result[3]) | {changed_rule.get("몸통")}
        if replacement.get("정의"):
            return None
        definitions = DefinitionTable(deepcopy(dict(old_result[1])),
                                      deepcopy(getattr(old_result[1], "programs", {})))
        direct = {}
        for fact in old_result[0]:
            evidence = fact.get("evidence") or {}
            if evidence.get("action_event"):
                continue
            turn = evidence.get("turn")
            if type(turn) is int:
                direct.setdefault(turn, []).append(deepcopy(fact))
        direct[at] = []
        if replacement_events is None:
            for fact in replacement["facts"]:
                row = deepcopy(fact)
                row["evidence"].update(turn=at, source=new_sources[at])
                direct[at].append(row)
        events = []
        for record in self._stored_event_records:
            event = record.get("event") if isinstance(record, dict) else None
            if not isinstance(event, dict) or record.get("status") != "executed":
                continue
            if replacement_events is not None and event.get("sequence") == at:
                continue
            if not isinstance(event.get("program"), dict) or type(event.get("sequence")) is not int:
                return None
            events.append(deepcopy(event))
        if replacement_events is not None:
            events.extend(event for event in replacement_events if event.get("polarity", True))
        events.sort(key=lambda event: (event["sequence"], event["id"]))
        facts, pending = [], []
        for turn in range(len(new_sources)):
            for event in (item for item in events if item["sequence"] == turn):
                raw = {"자리": deepcopy(event.get("roles") or {}),
                       "자리후보": deepcopy(event.get("role_candidates") or []),
                       "polarity": event.get("polarity", True),
                       "modality": event.get("modality", "asserted"),
                       "evidence": deepcopy(event.get("evidence") or {}), "실행": event}
                names = {part for row in facts for part in str(row["triple"][0]).split()}
                applied = self._triples(parser, {"프로그램": event["program"]}, raw, names,
                                        event.get("fills") or {}, event.get("overrides") or {}, facts,
                                        programs=definitions.programs)
                if (applied["빈자리"] or applied["충돌"] or applied["헛자리"]
                        or applied.get("못잼")):
                    return None
                for triple in applied["사실"]:
                    facts.append({"triple": triple,
                                  "polarity": raw.get("polarity", True),
                                  "modality": raw.get("modality", "asserted"),
                                  "evidence": {**raw["evidence"], "turn": turn,
                                               "source": new_sources[turn], "action_event": event}})
            facts.extend(deepcopy(direct.get(turn, [])))
        return facts, definitions, pending, set(old_result[3])

    def _cached_replay(self, parser, sources, fills):
        key = (tuple(sources), json.dumps(fills, ensure_ascii=False, sort_keys=True,
                                          separators=(",", ":")))
        # A structurally marked source never takes a cached or incremental shortcut: only the
        # full archived-reading replay, whose lookup refuses marked events.
        marked = self._marker_sources(parser, sources)
        # Authority stamp is kept beside (not inside) the two-element replay key ABI. It is bound to
        # the verified own-native authority for this parser; any drift drops every cached/incremental
        # shortcut and forces a full replay under the current own projection.
        projection = getattr(self.model, "language_projection", None)
        auth = _scoped_authority(projection, parser)
        stamp = (None if auth is None else
                 (id(projection), _scoped_authority_digest(projection, auth), auth["scope_sha256"]))
        drift = getattr(self, "_replay_authority", None) != stamp or (auth is not None and stamp[1] is None)
        if drift:
            self._replay_cache = None
        self._replay_authority = stamp
        if drift and auth is not None and stamp[1] is None:
            self._replay_authority = ("unbound", object())
        marked = marked or drift
        if not marked and self._replay_cache is not None and self._replay_cache[0] == key:
            self._last_replay_scope = "same_input"
            return deepcopy(self._replay_cache[1])
        result = None if marked else self._incremental_replay(parser, key, sources, fills)
        reusable = {"append": False, "direct": ()}
        if result is None:
            result = None if marked else self._resume_semantic_replay(parser, key, sources, fills)
            if result is not None:
                self._last_replay_scope = "semantic_resume"
            elif not marked:
                result = self._append_semantic_replay(parser, key, sources, fills)
            if result is not None:
                if self._last_replay_scope != "semantic_resume":
                    self._last_replay_scope = "semantic_append"
            if result is None and not marked:
                result = self._append_semantic_definition(parser, key, sources, fills)
                if result is not None:
                    self._last_replay_scope = "semantic_definition"
            if result is None and not marked:
                result = self._semantic_correction_replay(parser, key, sources, fills)
                if result is not None:
                    self._last_replay_scope = "semantic_correction"
            if result is None:
                result = self._replay(parser, sources, fills, self.event_ids, projection=projection)
                self._last_replay_scope = "full"
                if marked:
                    reusable = {"append": False, "direct": tuple(False for _source in sources)}
                else:
                    direct = tuple(self._incremental_source(parser, source) for source in sources)
                    reusable = {"append": not result[2] and not fills, "direct": direct}
        else:
            old_sources = self._replay_cache[0][0]
            self._last_replay_scope = ("append_suffix"
                                       if tuple(sources)[:len(old_sources)] == old_sources
                                       else "correction_suffix")
            old_reusable = self._replay_cache[2]
            old_direct = tuple(old_reusable.get("direct", ()))
            new_direct = tuple(True for _source in tuple(sources)[len(old_sources):])
            if tuple(sources)[:len(old_sources)] == old_sources:
                direct = old_direct + new_direct
            else:
                start = next(index for index, pair in enumerate(zip(old_sources, tuple(sources)))
                             if pair[0] != pair[1])
                direct = old_direct[:start] + tuple(True for _source in tuple(sources)[start:])
            reusable = {"append": True, "direct": direct}
        # Every replay path binds a count said without its holder the same way (a pass over the
        # facts in order; one already bound is not bound again).
        result = (self._bind_unnamed_counts(parser, [], result[0], getattr(self, "bind_hints", [])),) + tuple(result[1:])
        # ... and keeps one thing counted in two units as two counts (``_unit_keys``)
        result = (self._unit_keys(parser, result[0]),) + tuple(result[1:])
        self._replay_cache = (key, deepcopy(result), reusable)
        if self._last_replay_scope in {"semantic_append", "semantic_resume", "semantic_correction",
                                       "semantic_definition"}:
            stems = frozenset(result[1])
            self._verb_cache = (tuple(sources), stems, self._forms_of(parser, stems), self._grammar())
        return result

    def current_state(self):
        """현재 대화에서 확인된 상태만, 계획 선택에 넘길 수 있는 꼴로 낸다.

        아직 못 읽은 사건이나 답을 기다리는 빈자리가 있으면 그 사건이 바꿨을
        값을 전제로 계획하지 않는다. 이 메서드는 대화를 추가·수정하지 않으며,
        이미 검증한 재생 결과만 상태 사실로 접는다.
        """
        if self.unread or self.unread_guard or self._live():
            return []
        parser = self._parser()
        facts, _defined, pending, _read = self._cached_replay(
            parser, self.observations, self.fills)
        if any(not item.get("거짓조건") for item in pending):
            return []
        state, _changes = current_facts(
            facts, parser.data.get("mutable_predicates", []),
            parser.data.get("numeric_updates", {}))
        return [list(item["triple"]) for item in state]

    def learned_action_candidates(self):
        """Expose learned definitions as grounded, non-executing plan options.

        This deliberately exports a definition rather than replaying an old
        action sentence as an imperative.  A plan consumer can choose it only
        when its requested goal names the learned action; the original
        definition/version and still-required role slots remain visible.
        """
        parser = self._parser()
        _facts, defined, _pending, _read = self._cached_replay(
            parser, self.observations, self.fills)
        candidates = []
        for stem, rule in sorted(defined.items()):
            program = rule.get("프로그램") or {}
            signature = program.get("signature") or {}
            slots = sorted(set((signature.get("open_roles") or {}).values()))
            evidence = program.get("definition_evidence") or rule.get("evidence") or {}
            source_text = str(evidence.get("text") or rule.get("몸통") or "").strip()
            if not source_text:
                continue
            required = ", ".join(slots)
            labels = parser.data["ledger_labels"]
            text = (labels["action_rule"] % (stem, source_text)
                    + (labels["required_roles"] % required if required else ""))
            version = program.get("definition_version")
            candidates.append({"id": "learned-action:%s@%s" % (stem, version),
                               "text": text, "source": labels["definition_source"] % (stem, version),
                               "actionable": True, "achieves": [stem, source_text],
                               "definition_version": version,
                               "required_roles": slots,
                               "effects": []})
        return candidates

    def execution_evidence(self, subject):
        """Return compact explanation material grounded in executed events.

        An action definition is not proof that an action happened.  This
        method therefore reads only replayed emitted facts that retain an
        action-event envelope, and declines the whole route while a real
        pending event could still change the timeline.
        """
        target = str(subject or "").strip()
        if not target:
            return []
        parser = self._parser()
        facts, _defined, pending, _read = self._cached_replay(
            parser, self.observations, self.fills)
        if any(not item.get("거짓조건") for item in pending):
            return []
        rows, seen = [], set()
        for fact in facts:
            triple = fact.get("triple") or []
            event = (fact.get("evidence") or {}).get("action_event") or {}
            if (len(triple) != 3 or not event or target not in str(triple[0])):
                continue
            event_id = str(event.get("id") or "")
            key = (event_id, tuple(str(value) for value in triple))
            if not event_id or key in seen:
                continue
            seen.add(key)
            source_text = str((event.get("evidence") or {}).get("text") or "").strip()
            if not source_text:
                continue
            rows.append({"id": "executed-action:%s" % event_id,
                         "text": "%s → %s — %s — %s" % (source_text, triple[0], triple[1], triple[2]),
                         "source": parser.data["ledger_labels"]["event_source"] % event_id,
                         "relation": "effect", "actionable": False})
        return rows

    def _verification(self, knowledge_path, checks):
        if self.model is None:
            return {"sources": [str(knowledge_path)], "checks": checks,
                    "replay_scope": self._last_replay_scope}
        return {"sources": [item["path"] for item in self.model.sources], "checks": checks,
                "model": self.model.fingerprint, "model_assets": self.model.sources,
                "replay_scope": self._last_replay_scope}

    def _event_ledger(self):
        """Materialise the event-side of the replay ledger for persistence.

        Facts remain the input to state projection, while this compact index
        lets a saved conversation inspect raw text, bound roles, program and
        unresolved reason without treating an assistant answer as evidence.
        It is rebuilt from the already verified replay result and carries the
        stable id allocated in ``event_ids``.
        """
        parser = self._parser()
        facts, definitions, pending, _read = self._cached_replay(
            parser, self.observations, self.fills)
        rows = {}
        for fact in facts:
            event = (fact.get("evidence") or {}).get("action_event")
            if not isinstance(event, dict) or not event.get("id"):
                continue
            status = "executed" if (event.get("polarity", True)
                                      and event.get("modality", "asserted") == "asserted") else event.get("modality", "planned")
            row = rows.setdefault(event["id"], {"event": deepcopy(event), "status": status,
                                                  "effects": [], "state_changes": []})
            # Planned and other non-asserted events retain their envelope but
            # are never reported as executed effects or current state.
            if status == "executed":
                row["effects"].append(deepcopy(fact["triple"]))
        for item in pending:
            event = item.get("실행")
            if not isinstance(event, dict) or not event.get("id"):
                continue
            modality = event.get("modality", "asserted")
            status = ("negative" if event.get("polarity", True) is False
                      else modality if modality != "asserted"
                      else "condition_false" if item.get("못잼") == "condition_false"
                      else "pending")
            rows[event["id"]] = {"event": deepcopy(event), "status": status,
                                 "reason": ("%s_observation" % status if status in {"negative", "planned", "hypothetical"}
                                            else "condition_false" if status == "condition_false"
                                            else item.get("못잼") or "role_or_state_unresolved"),
                                 "effects": [], "state_changes": []}
        # State projection is a separate, ordered phase.  Persist its before
        # and after values alongside the event rather than forcing a later
        # inspector to infer state changes from emitted triples.
        _state, changes = current_facts(
            facts, parser.data.get("mutable_predicates", []), parser.data.get("numeric_updates", {}))
        for change in changes:
            event = (change.get("evidence") or {}).get("action_event") or {}
            row = rows.get(event.get("id"))
            # A planned/conditional event may be structurally executable, but
            # its projected transition is only a hypothetical possibility.
            # Keeping it in ``state_changes`` made durable ALMA rows look like
            # actual state effects despite their empty ``effects`` list.
            if row is not None and row.get("status") == "executed":
                row["state_changes"].append(deepcopy(change))
        # Negative and still-uninterpreted events have no emitted fact (by
        # design), yet must not disappear from the event graph.  Retain their
        # raw parsed roles and modality as a non-executed ledger entry.  This
        # pass never promotes them to state.
        revised_ids = {revision.get("event_id") for revision in self.event_revisions
                       if isinstance(revision, dict)}
        if self._stored_event_records is not None:
            for record in self._stored_event_records:
                event = record.get("event") if isinstance(record, dict) else None
                if (isinstance(event, dict) and isinstance(event.get("id"), str)
                        and event["id"] not in revised_ids):
                    rows.setdefault(event["id"], deepcopy(record))
        # Replay rows cover emitted effects, but a later negative or
        # uninterpreted observation has no fact to add.  Re-scan the bounded
        # source ledger on every rebuild and keep existing rows by event ID.
        corrected_indices = {revision.get("index") for revision in self.event_revisions
                             if isinstance(revision, dict) and type(revision.get("index")) is int}
        indices = sorted(set(range(self._event_records_count, len(self.observations)))
                         | {index for index in corrected_indices if 0 <= index < len(self.observations)})
        if indices:
            # A restored context has a saved inflection table for its whole
            # history.  Read only the new suffix: reparsing the old prefix
            # would violate the saved-semantic replay contract.
            fresh = (self._verb_cache is not None and len(self._verb_cache) > 3
                     and self._verb_cache[3] == self._grammar())
            verbs = deepcopy(self._verb_cache[2]) if fresh else self._verbs_for(parser, self.observations)
            marked_at = {item["index"] for item in self._marked_archive_events()}
            for index in indices:
                source = self.observations[index]
                if index in marked_at:
                    continue    # reconciled from the actual archive below, never reread
                parsed = self._read_source(parser, source, events=True, verbs=verbs)
                if parsed is None:
                    continue
                for ordinal, raw in enumerate(parsed.get("사건", [])):
                    if self._structural_marked(raw):
                        continue
                    slot = "%d:%d" % (index, ordinal)
                    event_id = (self._event_id(index, raw.get("verb"), raw.get("자리", {}), ordinal)
                                if self.event_ids is None else self.event_ids.setdefault(slot, "event:%s" % slot))
                    if event_id in rows:
                        continue
                    stem = self._lookup(parser, raw, definitions, verbs) or raw.get("verb")
                    rule = definitions.get(stem)
                    program = deepcopy((rule or {}).get("프로그램"))
                    evidence = raw.get("evidence") or {}
                    prior = [fact for fact in facts if (
                        (fact.get("evidence") or {}).get("turn", -1) < index
                        or ((fact.get("evidence") or {}).get("turn") == index
                            and (fact.get("evidence") or {}).get("start", 0) < evidence.get("start", 0)))]
                    truth = self._holds(parser, parsed.get("조건") or [], evidence.get("start", 0), prior,
                                        getattr(self.model, "language_projection", None),
                                        actual_source=source)
                    modality = raw.get("modality", "asserted")
                    status = ("negative" if raw.get("polarity", True) is False
                              else modality if modality != "asserted"
                              else "condition_false" if truth is False
                              else "pending" if truth is None and parsed.get("조건")
                              else "uninterpreted")
                    rows[event_id] = {"event": {
                        "schema": "nai-action-event-v1", "id": event_id,
                        "action": stem,
                        "definition_version": (program or {}).get("definition_version"),
                        # A negative event has no emitted fact from which to
                        # inherit its program.  It still names the known
                        # action contract so its domain/roles can be audited
                        # without turning its effects into world state.
                        "program": program, "domain": (program or {}).get("domain"), "references": {},
                        "roles": deepcopy(raw.get("자리") or {}),
                        "role_candidates": deepcopy(raw.get("자리후보") or []),
                        "conditions": deepcopy(parsed.get("조건") or []),
                        "fills": deepcopy([fill for fill in self.fills
                                            if fill.get("사건") == event_id]),
                        "state_fills": [], "overrides": {},
                        "polarity": raw.get("polarity", True),
                        "modality": raw.get("modality", "asserted"), "sequence": index,
                        "evidence": deepcopy(evidence)},
                        "status": status,
                        "reason": ("negative_observation" if status == "negative"
                                   else "%s_observation" % status if status in {"planned", "hypothetical"}
                                   else "condition_false" if status == "condition_false"
                                   else "condition_unmeasured" if status == "pending"
                                   else "definition_unavailable"),
                        "effects": [], "state_changes": []}
        # Every actual active archived marked event (restored prefix included) is reconciled as an
        # uninterpreted row: no program, no effects, never a stale row for the same ID.
        for item in self._marked_archive_events():
            index, ordinal, raw = item["index"], item["ordinal"], item["raw"]
            roles = raw.get("자리") if isinstance(raw.get("자리"), dict) else {}
            slot = "%d:%d" % (index, ordinal)
            event_id = (self._event_id(index, None, roles, 0) if self.event_ids is None
                        else self.event_ids.setdefault(slot, "event:%s" % slot))
            event = {"schema": "nai-action-event-v1", "id": event_id, "action": raw.get("verb"),
                     "definition_version": None, "program": None, "domain": None, "references": {},
                     "roles": deepcopy(roles),
                     "role_candidates": deepcopy(raw.get("자리후보") or []),
                     "conditions": [], "fills": [], "state_fills": [], "overrides": {},
                     "polarity": True, "modality": "asserted", "sequence": index,
                     "evidence": deepcopy(raw.get("evidence") or {})}
            run = raw.get("실행") if isinstance(raw.get("실행"), dict) else {}
            for name in ("structural_reading", "selected_action_binding"):
                for carrier in (raw, run, item["parsed"]):
                    if name in carrier:
                        event[name] = deepcopy(carrier[name])
                        break
            rows[event_id] = {"event": event, "status": "uninterpreted", "reason": "unknown_word",
                              "effects": [], "state_changes": []}
        for row in rows.values():
            if isinstance(row, dict) and self._structural_marked(row.get("event")):
                row.update(status="uninterpreted", reason="unknown_word", effects=[], state_changes=[])
        result = [rows[key] for key in sorted(rows)]
        self._stored_event_records = deepcopy(result)
        self._event_records_count = len(self.observations)
        return result

    def _common_inference_facts(self, parser, facts=None):
        """Build the ordinary fact input shared by answers and proof storage.

        Learned classifications are facts with stable application ids, rather
        than annotations appended after inference.  The independent
        ``event_status`` premise is emitted from the durable event envelope;
        a pack rule must therefore join it with ``instance_of`` before it may
        derive a classification.  This keeps the event ledger, normal KG
        query path, and serialised proof graph on one set of inputs.
        """
        if facts is None:
            facts, _definitions, _pending, _read = self._cached_replay(
                parser, self.observations, self.fills)
        # Historical transition facts stay in the event ledger, but closure
        # explanations for a *current* answer must start from the same
        # single-valued projection that the answer path uses.  Otherwise an
        # obsolete location can remain as a proof premise after a move.
        facts, _changes = current_facts(
            facts, parser.data.get("mutable_predicates", []),
            parser.data.get("numeric_updates", {}))
        identified = []
        for index, fact in enumerate(facts):
            item = deepcopy(fact)
            event = (item.get("evidence") or {}).get("action_event") or {}
            item["id"] = "%s:effect:%d" % (event["id"], index) if event.get("id") else "fact:%d" % index
            identified.append(item)
        records = self._event_ledger()
        self.concepts.sync(records)
        # Event envelopes are durable semantic records.  Expose their actual
        # execution status as a normal (non-mutable) fact so a pack-declared
        # rule can require it independently of the learned membership.
        for record in records:
            event = record.get("event") or {}
            event_id = event.get("id")
            if event_id and record.get("status") == "executed":
                identified.append({"id": "%s:status" % event_id,
                                   "triple": [event_id, "event_status", "executed"],
                                   "evidence": {"kind": "event_status",
                                                "event_id": event_id}})
                signature = (event.get("program") or {}).get("signature") or {}
                role_slots = {**(signature.get("role_slots") or {}),
                              **(signature.get("open_roles") or {})}
                roles = event.get("roles") or {}
                # Roles are represented as ordinary occurrence nodes.  This
                # avoids language-specific predicates (or tuple encoding)
                # while letting pack rules join a learned program role to an
                # independently asserted fact about its current participant.
                for role_name, slot in role_slots.items():
                    value = roles.get(slot)
                    if not isinstance(value, str) or not value:
                        continue
                    occurrence = "eventrole:%s:%s" % (event_id, role_name)
                    identified.extend([
                        {"id": "%s:role" % occurrence,
                         "triple": [event_id, "event_role", occurrence],
                         "evidence": {"kind": "event_role", "event_id": event_id,
                                      "role": role_name, "value": value}},
                        {"id": "%s:name" % occurrence,
                         "triple": [occurrence, "role_name", role_name],
                         "evidence": {"kind": "event_role", "event_id": event_id,
                                      "role": role_name, "value": value}},
                        {"id": "%s:value" % occurrence,
                         "triple": [occurrence, "role_value", value],
                         "evidence": {"kind": "event_role", "event_id": event_id,
                                      "role": role_name, "value": value}},
                    ])
        contract_candidates = {candidate.get("id") for candidate in self.concepts.candidates
                               if candidate.get("scope", {}).get("structural_level")
                               == "cross_domain_event_contract"}
        for application in self.concepts.applications:
            # An event-contract candidate is durable semantic evidence, not a
            # competing answer to a user's action-specific "what concept"
            # question.  Its applications remain in the concept ledger.
            if application.get("valid") and application.get("candidate_id") not in contract_candidates:
                identified.append({"id": application["id"],
                                   "triple": list(application["conclusion"]),
                                   "evidence": {"kind": "concept_application",
                                                "event_id": application["event_id"],
                                                "candidate_id": application["candidate_id"],
                                                "premise_event_ids": list(application["premise_event_ids"]),
                                                "validation_event_ids": list(application["validation_event_ids"])}})
        for candidate in self.concepts.candidates:
            if candidate.get("status") != "active":
                continue
            for predicate in (candidate.get("structural_definition") or {}).get("effect_predicates") or []:
                identified.append({"id": "%s:effect:%s" % (candidate["id"], predicate),
                                   "triple": [candidate["id"], "concept_effect", predicate],
                                   "evidence": {"kind": "learned_concept_structure",
                                                "candidate_id": candidate["id"],
                                                "property": "effect_predicate",
                                                "value": predicate,
                                                "definition_versions": list((candidate.get("scope") or {}).get("definition_versions") or [])}})
        return identified

    def _resolve_event_reference(self, parser, request):
        """Resolve a pack-declared role map to exactly one durable event."""
        forms = self._verbs_for(parser, self.observations)
        stem = self._lookup(parser, {"verb": request.get("action")}, set(), forms)
        if stem is None:
            return None
        roles = request.get("roles") or {}
        matches = []
        for record in self._event_ledger():
            event = record.get("event") or {}
            if (record.get("status") == "executed" and event.get("action") == stem
                    and all((event.get("roles") or {}).get(slot) == value
                            for slot, value in roles.items())):
                matches.append(event.get("id"))
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _render_reason(parts, values):
        return "".join(re.sub(r"\$([a-z_][a-z0-9_]*)",
                               lambda matched: str(values.get(matched.group(1), "")), part)
                       for part in parts)

    def _concept_relation_reason(self, parser, request, event_id, outcome, facts):
        """Select explanation content from the proof of this conclusion."""
        application = next((row for row in self.concepts.applications
                            if row.get("event_id") == event_id and row.get("valid")), None)
        if application is None:
            # Validation is queryable after activation, but remains separate
            # from recorded post-activation applications in the learning
            # lineage.  Construct only an explanation view here.
            candidate_for_validation = next((row for row in self.concepts.candidates
                                             if row.get("status") == "active"
                                             and event_id in row.get("support_event_ids", [])), None)
            if candidate_for_validation is not None:
                application = {"event_id": event_id, "candidate_id": candidate_for_validation["id"],
                               "premise_event_ids": list(candidate_for_validation.get("evidence_event_ids", [])),
                               "validation_event_ids": list(candidate_for_validation.get("support_event_ids", [])),
                               "valid": True, "phase": "validation_projection"}
        candidate = next((row for row in self.concepts.candidates
                          if application and row.get("id") == application.get("candidate_id")), None)
        if application is None or candidate is None:
            return None
        premise_predicate = request.get("premise_predicate")
        event = next((row.get("event") for row in self._event_ledger()
                      if (row.get("event") or {}).get("id") == event_id), {}) or {}
        conclusion = [event_id, request.get("predicate"), request.get("value")]
        proof = next((row for row in outcome.get("transitions", [])
                      if row.get("rule") and row.get("fact") == conclusion), None)
        if proof is None:
            return None
        premise = next((row for row in proof.get("parents", [])
                        if len(row) == 3 and row[1] == premise_predicate), None)
        if premise is None:
            return None
        rule = proof["rule"]
        # The normal answer path retains the exact parent triple.  Its
        # provenance ledger additionally gives the rule binding and durable
        # premise id, so an explanation never re-selects a lookalike fact.
        from marco.reasoning.inference import closure_with_provenance
        provenance = closure_with_provenance(facts, parser.data.get("rules", []))
        bundle = next((row for row in provenance["proof_bundles"].get(tuple(conclusion), [])
                       if row.get("rule") == rule
                       and row.get("bindings", {}).get("?event") == event_id), None)
        fact_ids = {}
        for index, row in enumerate(facts):
            fact_ids.setdefault(tuple(row.get("triple") or []), []).append(
                str(row.get("id") or (row.get("evidence") or {}).get("fact_id") or "fact:%d" % index))
        premise_id = next((fact_id for fact_id in fact_ids.get(tuple(premise), [])
                           if not bundle or "support:%s" % fact_id in bundle.get("premise_fact_ids", [])), None)
        return {"request": deepcopy(request), "event_id": event_id,
                "event": (event.get("evidence") or {}).get("text", event_id),
                "concept": candidate["id"],
                "structure": ", ".join((candidate.get("structural_definition") or {}).get("effect_predicates") or []),
                "premise": " ".join(premise), "premise_triple": list(premise),
                "premise_id": premise_id, "rule": rule,
                "definition_version": event.get("definition_version"),
                "rule_version": next((row.get("version", row.get("rule_version"))
                                      for row in (parser.data.get("rules") or [])
                                      if row.get("id") == rule), None),
                "conclusion": outcome.get("answer"), "proof": bundle,
                "missing": False}

    def _concept_relation_premise_state(self, parser, request, event_id, facts):
        """Find the pack-declared missing premise without guessing a role."""
        matches = []
        for rule in parser.data.get("rules") or []:
            head = rule.get("head") or []
            if len(head) != 3 or head[1:] != [request.get("predicate"), request.get("value")]:
                continue
            premise = next((row for row in rule.get("body") or []
                            if len(row) == 3 and row[1] == request.get("premise_predicate")), None)
            if premise is None:
                continue
            subject = premise[0]
            role_value = next((row for row in rule.get("body") or []
                               if len(row) == 3 and row[1] == "role_value" and row[2] == subject), None)
            if role_value is None:
                continue
            role_name = next((row[2] for row in rule.get("body") or []
                              if len(row) == 3 and row[1] == "role_name" and row[0] == role_value[0]), None)
            role_ids = {row[2] for row in (item.get("triple") or [] for item in facts)
                        if len(row) == 3 and row[0] == event_id and row[1] == "event_role"}
            value = next((row[2] for row in (item.get("triple") or [] for item in facts)
                          if len(row) == 3 and row[0] in role_ids and row[1] == "role_value"
                          and any(name == [row[0], "role_name", role_name]
                                  for name in (item.get("triple") or [] for item in facts))), None)
            if isinstance(value, str):
                matches.append((rule, [value, premise[1], premise[2]]))
        if len({tuple(row[1]) for row in matches}) != 1:
            return {"request": deepcopy(request), "event_id": event_id,
                    "premise_state": "unverifiable", "missing": True}
        rule, triple = matches[0]
        rows = [row for row in facts if row.get("triple") == triple
                and row.get("modality", "asserted") == "asserted"]
        positive = [row for row in rows if row.get("polarity", True)]
        negative = [row for row in rows if row.get("polarity", True) is False]
        state = "conflict" if positive and negative else "positive" if positive else "negative" if negative else "unknown"
        return {"request": deepcopy(request), "event_id": event_id,
                "premise_label": request.get("premise_label", ""), "premise": " ".join(triple),
                "premise_triple": triple, "premise_state": state, "missing": not positive,
                "rule": rule.get("id"), "rule_version": rule.get("version", rule.get("rule_version"))}

    def _answer_event_relation_query(self, parser, query):
        requests = [row.get("event_relation_query") for row in (query or [])
                    if isinstance(row, dict) and isinstance(row.get("event_relation_query"), dict)]
        if len(requests) != 1 or len(query or []) != 1:
            return None
        request = requests[0]
        event_id = self._resolve_event_reference(parser, request)
        if event_id is None:
            return None
        facts = self._common_inference_facts(parser)
        expected = request.get("value")
        outcome = parser.answer({"facts": facts,
                                 "query": [{"triple": [event_id, request["predicate"], expected],
                                            "render": list(request.get("render") or [])}]})
        if outcome is None:
            # Preserve the request so a direct follow-up reason can identify
            # the absent premise rather than asserting a negative conclusion.
            self.last_concept_relation = self._concept_relation_premise_state(parser, request, event_id, facts)
            return None
        self.last_concept_relation = self._concept_relation_reason(parser, request, event_id, outcome, facts)
        return outcome

    def _answer_concept_reason(self, parser):
        reason = self.last_concept_relation
        if not isinstance(reason, dict):
            return None
        # Re-evaluate the stored request from current semantic records.  This
        # makes a correction visible even when the user asks "why" directly.
        outcome = self._answer_event_relation_query(parser, [{"event_relation_query": reason["request"]}])
        current = self.last_concept_relation
        if outcome is None:
            current = self.last_concept_relation or reason
            state = current.get("premise_state")
            render = (parser.data.get("concept_reason_negative_render") if state == "negative"
                      else parser.data.get("concept_reason_conflict_render") if state == "conflict"
                      else parser.data.get("concept_reason_missing_render") if state in {"unknown", "unverifiable"}
                      else parser.data.get("concept_reason_unavailable_render")) or []
            if not isinstance(render, list):
                return None
            current["premise"] = current.get("premise") or reason["request"].get("premise_label", "")
            current["premise_label"] = current.get("premise_label") or reason["request"].get("premise_label", "")
            return {"answer": self._render_reason(render, current),
                    "transitions": [{"operation": "concept_relation_reason", **deepcopy(current)}]}
        render = parser.data.get("concept_reason_render") or []
        if not isinstance(render, list) or not current:
            return None
        return {"answer": self._render_reason(render, current),
                "transitions": [{"operation": "concept_relation_reason", **deepcopy(current)}]}

    def _inference_ledger(self, *, max_bundle_id_bytes=None):
        """Serialisable proof bundles for the same inputs a normal answer sees."""
        from marco.reasoning.inference import closure_with_provenance
        parser = self._parser()
        identified = self._common_inference_facts(parser)
        result = (closure_with_provenance(identified, parser.data.get("rules", []))
                  if max_bundle_id_bytes is None else
                  closure_with_provenance(identified, parser.data.get("rules", []),
                                          max_bundle_id_bytes=max_bundle_id_bytes))
        bundles = [bundle for rows in result["proof_bundles"].values() for bundle in rows]
        return {"complete": result["complete"], "reason": result["reason"],
                "searches": result["searches"],
                "bundles": bundles}

    def _answer_concept_query(self, parser, query):
        """Resolve a natural event reference through the active concept overlay.

        The candidate is consulted before producing an answer.  With the
        overlay disabled there is no matching derived classification and this
        routine returns ``None``; it is not a presentation-time annotation.
        """
        requests = [row.get("concept_query") for row in (query or [])
                    if isinstance(row, dict) and isinstance(row.get("concept_query"), dict)]
        if len(requests) != 1 or len(query or []) != 1:
            return None
        request = requests[0]
        records = self._event_ledger()
        forms = self._verbs_for(parser, self.observations)
        stem = self._lookup(parser, {"verb": request["action"]}, set(), forms)
        if stem is None:
            return None
        matches = []
        for record in records:
            event = record.get("event") or {}
            roles = event.get("roles") or {}
            if (event.get("action") == stem and roles.get("은") == request["actor"]
                    and roles.get("에게") == request["other"]):
                matches.append(event.get("id"))
        if len(matches) != 1:
            return None
        # This is a normal KG query over the same derived inputs used by
        # every other answer.  Resolving a natural event reference supplies
        # only its subject id; it never chooses a concept or synthesises a
        # conclusion outside the parser/rule closure.
        return parser.answer({"facts": self._common_inference_facts(parser),
                              "query": [{"triple": [matches[0], "classified_by", "?concept"],
                                         "render": list(parser.data["concept_answer_render"])}]})

    def snapshot(self, *, max_bundle_id_bytes=None):
        # Keep the established envelope version: added fields are optional so
        # existing local stores and callers remain forward-compatible.
        parser = self._parser()
        facts, definitions, pending, read = self._cached_replay(
            parser, self.observations, self.fills)
        # This is the verified semantic input for a restored context.  Raw
        # observations remain audit material, but a read-only turn after
        # restart does not need to reinterpret those old strings to recover
        # state, action programs, or pending reasons.
        replay = {"facts": deepcopy(facts), "definitions": deepcopy(dict(definitions)),
                  "programs": deepcopy(getattr(definitions, "programs", {})),
                  "pending": deepcopy(pending), "read": sorted(read)}

        def _fact_source_row(fact, ids, base):
            evidence = fact.get("evidence") if isinstance(fact, dict) else None
            source = evidence.get("source") if isinstance(evidence, dict) else None
            if not isinstance(source, Obs):
                return None
            oid, rev = source.oid, source.rev
            if not isinstance(oid, str) or not oid.strip():
                return None
            if type(rev) is not int or rev < 1:
                return None
            turn = evidence.get("turn") if isinstance(evidence, dict) else None
            if type(turn) is not int or not 0 <= turn < len(ids) or ids[turn] != oid:
                return None
            entry = self.reading_ledger.get(oid)
            versions = entry.get("versions") if isinstance(entry, dict) else None
            if not isinstance(versions, list) or rev > len(versions):
                return None
            record = versions[rev - 1]
            if not isinstance(record, dict):
                return None
            rec_rev = record.get("reading_revision")
            rec_base = record.get("parser_base_sha256")
            if (record.get("observation_id") != oid or type(rec_rev) is not int
                    or rec_rev != rev or not isinstance(record.get("source"), str)
                    or record["source"] != str(source)
                    or not isinstance(rec_base, str) or len(rec_base) != 64
                    or any(c not in "0123456789abcdef" for c in rec_base)
                    or rec_base != base):
                return None
            row = {"observation_id": oid, "reading_revision": rev}
            try:
                encoded = json.dumps(row, allow_nan=False).encode("utf-8")
            except (TypeError, ValueError, OverflowError, RecursionError):
                return None
            return row if len(encoded) <= 8192 else None

        _ids = list(self.observation_ids)
        replay["fact_sources"] = [
            _fact_source_row(fact, _ids, self.parser_base_sha256)
            for fact in facts]
        events = self._event_ledger()
        concepts = self.concepts.sync(events)
        # The ledger is the only semantic source of historical readings (``parser.chosen_*`` are views).
        ledger = deepcopy({"next": self._next_observation, "records": self.reading_ledger})
        for (who, number), kept in (parser.__dict__.get("chosen_programs") or {}).items():
            entry = ledger["records"].get(who[0])
            if entry and who[1] <= len(entry["versions"]):
                record = entry["versions"][who[1] - 1]
                try:
                    record.setdefault("programs", {})[str(number)] = json.loads(
                        json.dumps(kept, allow_nan=False))
                except (TypeError, ValueError):
                    # the original program cannot be archived: mark it unavailable, never re-induce it
                    lost = record.setdefault("programs_unavailable", [])
                    if str(number) not in lost:
                        lost.append(str(number))
        return {"schema": "reasoning-context-v11", "observations": [str(source) for source in self.observations],
                "observation_ids": self.observation_ids, "reading_ledger": ledger,
                # the conversation identity graph (M1): nodes, aliases with their turns, count edges, frames
                "graph": self.conversation_graph().to_dict(),
                "corrections": deepcopy(self.corrections), "unread": deepcopy(self.unread),
                "unread_guard": deepcopy(self.unread_guard),
                "asked": deepcopy(self.asked), "held_question": self.held_question,
                "fills": deepcopy(self.fills), "last_subject": self.last_subject,
                "salient": list(self.salient),
                # the last question's frame, for a follow-up after a restart (effort 2)
                **({"last_frame": deepcopy(self.last_frame)} if self.last_frame and self._effort_allows(2) else {}),
                "last_referents": deepcopy(self.last_referents),
                "last_concept_relation": deepcopy(self.last_concept_relation),
                "event_ids": deepcopy(self.event_ids),
                "event_revisions": deepcopy(self.event_revisions),
                "events": events,
                "experience_concepts": concepts,
                "inference_bundles": (self._inference_ledger()
                                      if max_bundle_id_bytes is None else
                                      self._inference_ledger(
                                          max_bundle_id_bytes=max_bundle_id_bytes)),
                "conversation": self.conversation_id,
                "replay": replay}

    def restore(self, snapshot):
        if (not isinstance(snapshot, dict) or snapshot.get("schema") not in {
                "reasoning-context-v1", "reasoning-context-v2",
                "reasoning-context-v3", "reasoning-context-v4",
                "reasoning-context-v5", "reasoning-context-v6",
                "reasoning-context-v7", "reasoning-context-v8",
                "reasoning-context-v9", "reasoning-context-v10", "reasoning-context-v11"}
                or not isinstance(snapshot.get("observations"), list)
                or len(snapshot["observations"]) > self.max_turns
                or any(not isinstance(x, str) or not x.strip() for x in snapshot["observations"])):
            raise ValueError("invalid_reasoning_context_snapshot")
        corrections = snapshot.get("corrections", [])
        if (not isinstance(corrections, list) or len(corrections) > self.max_turns
                or any(not isinstance(x, dict) or type(x.get("index")) is not int
                       or not 0 <= x["index"] < len(snapshot["observations"])
                       or any(not isinstance(x.get(k), str) or not x[k].strip() for k in ("before", "after"))
                       for x in corrections)):
            raise ValueError("invalid_reasoning_context_snapshot")
        replay = snapshot.get("replay")
        if replay is not None:
            if not isinstance(replay, dict):
                raise ValueError("invalid_reasoning_context_snapshot")
            facts, definitions = replay.get("facts"), replay.get("definitions")
            programs, pending, read = (replay.get("programs"), replay.get("pending"),
                                        replay.get("read"))
            if (not isinstance(facts, list) or len(facts) > self.max_turns * 16
                    or any(not isinstance(row, dict) or not isinstance(row.get("triple"), list)
                           or len(row["triple"]) != 3 or not isinstance(row.get("evidence"), dict)
                           for row in facts)
                    or not isinstance(definitions, dict)
                    or any(not isinstance(key, str) or not isinstance(value, dict)
                           for key, value in definitions.items())
                    or not isinstance(programs, dict)
                    or any(not isinstance(key, str) or not isinstance(value, dict)
                           for key, value in programs.items())
                    or not isinstance(pending, list)
                    or any(not isinstance(row, dict) for row in pending)
                    or not isinstance(read, list) or any(not isinstance(value, str) for value in read)):
                raise ValueError("invalid_reasoning_context_snapshot")
        unread = snapshot.get("unread", [])
        if not isinstance(unread, list) or len(unread) > self.max_turns:
            raise ValueError("invalid_reasoning_context_snapshot")
        # v3 은 글자만 담았다. 순서를 모르면 가장 이른 것으로 읽는다 — 덜 푸는 쪽이다.
        unread = [{"text": x, "at": 0} if isinstance(x, str) else x for x in unread]
        if any(not isinstance(x, dict) or not isinstance(x.get("text"), str)
               or not x["text"].strip() or type(x.get("at")) is not int or x["at"] < 0
               for x in unread):
            raise ValueError("invalid_reasoning_context_snapshot")
        unread_guard = snapshot.get("unread_guard", [])
        guard_limit = max(16, self.max_turns * 4) + 1
        if (not isinstance(unread_guard, list) or len(unread_guard) > guard_limit
                or any(not isinstance(x, dict) or not isinstance(x.get("text"), str)
                       or not x["text"].strip() or type(x.get("at")) is not int
                       or x["at"] < 0 or ("범용" in x and type(x["범용"]) is not bool)
                       for x in unread_guard)):
            raise ValueError("invalid_reasoning_context_snapshot")
        readings = snapshot.get("readings")
        if readings is not None and (not isinstance(readings, dict) or len(readings) > self.max_turns or any(
                not isinstance(source, str) or not isinstance(reading, dict)
                or not isinstance(reading.get("facts", []), list)
                or any(not isinstance(row, dict) or not isinstance(row.get("triple"), list) or len(row["triple"]) != 3
                       for row in reading.get("facts", []))
                for source, reading in readings.items())):
            raise ValueError("invalid_reasoning_context_snapshot")
        texts = list(snapshot["observations"])
        if snapshot["schema"] == "reasoning-context-v11":
            ids, ledger = snapshot.get("observation_ids"), snapshot.get("reading_ledger")
            ledger = _readings.validate_ledger(texts, ids, ledger, max_turns=self.max_turns,
                                               base=self.parser_base_sha256,
                                               head_limit=self.installed_memory_head)
        else:
            # A bare older snapshot never kept the original reads: carry the verified replay state, mark every
            # slot without a kept choice unavailable, and never reparse with the latest grammar as "original".
            ids, ledger = _readings.legacy_ledger(texts, readings, base=self.parser_base_sha256,
                                                  head=self.installed_memory_head)
        # Everything below only validates and prepares values.  Nothing on ``self`` (or on the parser
        # views) changes until every field of the snapshot has been accepted: a rejected snapshot must
        # leave the live context exactly as it was.
        ledger = deepcopy(ledger)
        view, programs, blocked = {}, {}, set()
        current = self._grammar()
        for oid, entry in ledger["records"].items():
            active = entry["versions"][entry["active"] - 1]
            who = (oid, active["reading_revision"])
            if active["parsed"] is not None:
                view[oid] = deepcopy(active["parsed"])
            for number, kept in (active.get("programs") or {}).items():
                if isinstance(kept, dict) and isinstance(kept.get("usable"), dict) \
                        and isinstance(kept.get("origins"), dict) and number.isdigit():
                    programs[(who, int(number))] = deepcopy(kept)
            stale = active.get("parser_grammar_sha256") != current
            for number in range(len((active["parsed"] or {}).get("정의") or [])):
                if (who, number) not in programs and (stale or str(number) in active.get("programs_unavailable", [])):
                    blocked.add((who, number))
        new_obs = [Obs(text, oid, ledger["records"][oid]["active"]) for text, oid in zip(texts, ids)]
        asked = snapshot.get("asked") or []
        asked = [asked] if isinstance(asked, dict) else asked
        # 옛 갈무리의 되물음은 꼴이 다르다. 못 알아보면 **안 이어 붙인다** — 덜
        # 잇는 쪽이다. 되물음 하나를 잃을 뿐 값이 틀어지지는 않는다.
        asked = [x for x in asked if isinstance(x, dict) and isinstance(x.get("사건"), str)]
        if (not isinstance(asked, list) or len(asked) > self.max_turns
                or any(not isinstance(x.get("id"), str)
                       or not isinstance(x.get("동사"), str)
                       or not isinstance(x.get("자리"), dict)
                       or not isinstance(x.get("빈자리"), dict) for x in asked)):
            raise ValueError("invalid_reasoning_context_snapshot")
        fills = snapshot.get("fills") or []
        def valid_fill(fill):
            if not isinstance(fill, dict) or not isinstance(fill.get("사건"), str):
                return False
            if fill.get("사실") is not None:
                fact = fill["사실"]
                if not (isinstance(fact, list) and len(fact) == 3
                        and all(isinstance(value, str) and value for value in fact)):
                    return False
            if fill.get("변수") is not None:
                return isinstance(fill["변수"], str) and isinstance(fill.get("값"), str)
            if fill.get("사실") is not None:
                return True
            return isinstance(fill.get("역할"), str) and isinstance(fill.get("값"), str)
        if (not isinstance(fills, list) or len(fills) > self.max_turns
                or any(not valid_fill(item) for item in fills)):
            raise ValueError("invalid_reasoning_context_snapshot")
        마지막 = snapshot.get("last_subject")
        if 마지막 is not None and not isinstance(마지막, str):
            raise ValueError("invalid_reasoning_context_snapshot")
        salient = snapshot.get("salient")
        if salient is not None and (not isinstance(salient, list)
                                    or any(not isinstance(name, str) or not name for name in salient)):
            raise ValueError("invalid_reasoning_context_snapshot")
        # An older snapshot has no salient set: the last subject stands in for it.
        new_salient = list(salient) if salient is not None else (
            [마지막.split()[0]] if isinstance(마지막, str) and 마지막.strip() else [])
        graph = snapshot.get("graph")
        if graph is not None and not isinstance(graph, dict):
            raise ValueError("invalid_reasoning_context_snapshot")
        graph_carried = None
        if graph:
            from marco.reasoning.identity import ConversationGraph
            graph_carried = ConversationGraph.from_dict(graph).carried()
        frame = snapshot.get("last_frame")
        if frame is not None and not (isinstance(frame, dict) and isinstance(frame.get("text"), str)
                                      and isinstance(frame.get("holders"), list)
                                      and all(isinstance(h, str) for h in frame["holders"])
                                      and (frame.get("item") is None or isinstance(frame.get("item"), str))):
            raise ValueError("invalid_reasoning_context_snapshot")
        최근역할 = snapshot.get("last_referents", {})
        if (not isinstance(최근역할, dict)
                or any(not isinstance(key, str) or not isinstance(value, str) or not value
                       for key, value in 최근역할.items())):
            raise ValueError("invalid_reasoning_context_snapshot")
        last_concept_relation = snapshot.get("last_concept_relation")
        if last_concept_relation is not None and not isinstance(last_concept_relation, dict):
            raise ValueError("invalid_reasoning_context_snapshot")
        event_ids = snapshot.get("event_ids", None)
        if event_ids is not None and (not isinstance(event_ids, dict)
                                      or any(not isinstance(key, str) or not isinstance(value, str)
                                             or not value for key, value in event_ids.items())):
            raise ValueError("invalid_reasoning_context_snapshot")
        revisions = snapshot.get("event_revisions", [])
        if (not isinstance(revisions, list) or len(revisions) > self.max_turns
                or any(not isinstance(row, dict) or not isinstance(row.get("event_id"), str)
                       for row in revisions)):
            raise ValueError("invalid_reasoning_context_snapshot")
        stored_events = snapshot.get("events")
        if stored_events is not None and (
                not isinstance(stored_events, list)
                or any(not isinstance(record, dict) or not isinstance(record.get("event"), dict)
                       or not isinstance(record["event"].get("id"), str)
                       for record in stored_events)):
            raise ValueError("invalid_reasoning_context_snapshot")
        concepts = snapshot.get("experience_concepts")
        new_concepts = None
        if concepts is not None:
            # The concept store validates while it assigns, so restore into a fresh store and
            # only adopt it once the whole snapshot is accepted.
            from marco.learning.concepts import ExperienceConceptStore
            new_concepts = ExperienceConceptStore(support_limit=self.concepts.support_limit,
                                                  candidate_limit=self.concepts.candidate_limit,
                                                  validation_limit=self.concepts.validation_limit)
            new_concepts.restore(concepts)
        held = snapshot.get("held_question")
        if held is not None and (not isinstance(held, str) or not held.strip()):
            raise ValueError("invalid_reasoning_context_snapshot")
        parser = self._parser()
        replay_cache = verb_cache = None
        if replay is not None:
            restored_facts = deepcopy(replay["facts"])
            fact_sources = replay.get("fact_sources")
            records = ledger.get("records") if isinstance(ledger, dict) else None
            base = self.parser_base_sha256
            if (isinstance(fact_sources, list) and isinstance(records, dict)
                    and len(fact_sources) == len(restored_facts)):
                for fact, row in zip(restored_facts, fact_sources):
                    if type(row) is not dict or set(row) != {"observation_id",
                                                             "reading_revision"}:
                        continue
                    oid, rev = row["observation_id"], row["reading_revision"]
                    if not isinstance(oid, str) or not oid.strip():
                        continue
                    if type(rev) is not int or rev < 1:
                        continue
                    try:
                        encoded = json.dumps(row, allow_nan=False).encode("utf-8")
                    except (TypeError, ValueError, OverflowError, RecursionError):
                        continue
                    if len(encoded) > 8192:
                        continue
                    entry = records.get(oid)
                    versions = entry.get("versions") if isinstance(entry, dict) else None
                    if not isinstance(versions, list) or rev > len(versions):
                        continue
                    record = versions[rev - 1]
                    if not isinstance(record, dict):
                        continue
                    rec_rev = record.get("reading_revision")
                    rec_base = record.get("parser_base_sha256")
                    rec_source = record.get("source")
                    if (record.get("observation_id") != oid
                            or type(rec_rev) is not int or rec_rev != rev
                            or not isinstance(rec_source, str)
                            or not isinstance(rec_base, str) or len(rec_base) != 64
                            or any(c not in "0123456789abcdef" for c in rec_base)
                            or rec_base != base):
                        continue
                    evidence = fact.get("evidence") if isinstance(fact, dict) else None
                    source = evidence.get("source") if isinstance(evidence, dict) else None
                    turn = evidence.get("turn") if isinstance(evidence, dict) else None
                    if (not isinstance(source, str) or str(source) != rec_source
                            or type(turn) is not int or not 0 <= turn < len(ids)
                            or ids[turn] != oid):
                        continue
                    evidence["source"] = Obs(str(source), oid, rev)
            restored = (restored_facts,
                        DefinitionTable(deepcopy(replay["definitions"]),
                                        deepcopy(replay["programs"])),
                        deepcopy(replay["pending"]), set(replay["read"]))
            key = (tuple(new_obs), json.dumps(fills, ensure_ascii=False,
                                               sort_keys=True, separators=(",", ":")))
            replay_cache = (key, restored, {"append": False, "direct": ()})
            # The saved definition programs also supply inflected learned
            # verb forms; only a newly typed sentence needs parsing now.
            stems = frozenset(replay["definitions"])
            verb_cache = (tuple(new_obs), stems, self._forms_of(parser, stems), self._grammar())
        # ---- N1b3: optional structural marker coherence (staged values only; no mutation) ----
        def _n1b3_check():
            def refuse():
                raise ValueError("invalid_reasoning_context_snapshot")
            same = ReasoningContext._unread_native_equal
            keys = ("structural_reading", "selected_action_binding")
            marked = {}

            def _n1b3_name(value, limit=512):
                return type(value) is str and 0 < len(value) <= limit

            def _n1b3_span(value, limit):
                return (type(value) is list and len(value) == 2
                        and type(value[0]) is int and type(value[1]) is int
                        and 0 <= value[0] < value[1] <= limit)

            def _n1b3_blank(piece):
                return type(piece) is str and piece.strip() == ""

            def _n1b3_solid(piece):
                return type(piece) is str and piece != "" and not any(c.isspace() for c in piece)

            def _n1b3_source_check(record, reading, raw):
                # Exact original-source anchoring only: no live archive, graph, surface or parser
                # lookup; this cannot prove historical surface policy or dropped candidates.
                source = record["source"]
                if (reading.get("source_scope") != "current_clause"
                        or reading.get("offset_unit") != "unicode_codepoint"
                        or not _n1b3_name(reading.get("surface_id"))
                        or not _n1b3_span(reading.get("unknown_span"), len(source))):
                    refuse()
                ustart, uend = reading["unknown_span"]
                unknown = reading["unknown_text"]
                if (source[ustart:uend] != unknown or unknown != raw["verb"]
                        or not _n1b3_solid(unknown)):
                    refuse()
                candidates = reading.get("role_candidates")
                if type(candidates) is not list or not candidates:
                    refuse()
                prefix = source[:ustart]
                fields = ("slot", "value", "case_group", "type_ref", "presence", "coreference_group")
                meta, universe, witnessed, omitted_all = {}, None, set(), set()
                for candidate in candidates:
                    if type(candidate) is not dict:
                        refuse()
                    bindings, omitted = candidate.get("bindings"), candidate.get("omitted_slots")
                    if type(bindings) is not list or not bindings or type(omitted) is not list:
                        refuse()
                    cursor, slots, groups, corefs = 0, set(), set(), {}
                    for item in bindings:
                        if type(item) is not dict or not all(k in item for k in fields):
                            refuse()
                        f = {k: item.get(k) for k in fields}
                        if (not all(_n1b3_name(f[k]) for k in fields[:4])
                                or type(f["presence"]) is not str
                                or f["presence"] not in ("required", "optional")
                                or (f["coreference_group"] is not None
                                    and not _n1b3_name(f["coreference_group"]))):
                            refuse()
                        sp, mk, ch = item.get("span"), item.get("marker_span"), item.get("chunk_span")
                        if not (_n1b3_span(sp, ustart) and _n1b3_span(mk, ustart)
                                and _n1b3_span(ch, ustart)):
                            refuse()
                        start, vend = sp
                        if (mk[0] != vend or ch[0] != start or ch[1] != mk[1] or start < cursor
                                or source[start:vend] != f["value"]
                                or not _n1b3_solid(source[vend:mk[1]])
                                or not _n1b3_blank(prefix[cursor:start])):
                            refuse()
                        cursor = mk[1]
                        if f["slot"] in slots or f["case_group"] in groups:
                            refuse()
                        slots.add(f["slot"])
                        groups.add(f["case_group"])
                        if (f["coreference_group"] is not None
                                and corefs.setdefault(f["coreference_group"], f["value"]) != f["value"]):
                            refuse()
                        decl = (f["case_group"], f["type_ref"], f["presence"], f["coreference_group"])
                        if meta.setdefault(f["slot"], decl) != decl:
                            refuse()
                        if f["presence"] == "required":
                            witnessed.add(f["slot"])
                    if not _n1b3_blank(prefix[cursor:]):
                        refuse()
                    omitted_set = set()
                    for name in omitted:
                        if not _n1b3_name(name) or name in omitted_set or name in slots:
                            refuse()
                        omitted_set.add(name)
                    omitted_all |= omitted_set
                    roles = slots | omitted_set
                    if universe is None:
                        universe = roles
                    elif roles != universe:
                        refuse()
                if witnessed & omitted_all:
                    refuse()
            for index, (text, oid) in enumerate(zip(texts, ids)):
                entry = ledger["records"].get(oid)
                if type(entry) is not dict:
                    continue
                versions, active = entry.get("versions"), entry.get("active")
                if (type(active) is not int or not isinstance(versions, list)
                        or not 1 <= active <= len(versions)):
                    continue
                record = versions[active - 1]
                parsed = record.get("parsed") if type(record) is dict else None
                if not ReasoningContext._structural_marked(parsed):
                    continue
                if (record.get("observation_id") != oid or type(oid) is not str
                        or type(record.get("reading_revision")) is not int
                        or record["reading_revision"] != active
                        or type(record.get("source")) is not str or record["source"] != str(text)
                        or record.get("unavailable") is not False or type(parsed) is not dict
                        or ReasoningContext._unread_json(record, 65536) is None):
                    refuse()
                run = parsed.get("실행")
                if any(k in parsed for k in keys) or (
                        isinstance(run, dict) and any(k in run for k in keys)):
                    refuse()
                events = parsed.get("사건")
                if type(events) is not list or len(events) != 1:
                    refuse()
                for key, value in parsed.items():
                    if key == "사건" or value in (None, [], {}, "", False):
                        continue
                    if (key != "entry_selection" or type(value) is not dict
                            or value.get("schema") != "marco-entry-selection-v1"
                            or value.get("scope") != "known_selected_input_clauses"
                            or value.get("status") != "partial"
                            or value.get("coordinate_space") != "parser_view"
                            or type(value.get("items")) is not list or value["items"]
                            or type(value.get("gaps")) is not list):
                        refuse()
                raw = events[0]
                if type(raw) is not dict or not all(k in raw for k in keys):
                    refuse()
                reading, binding = raw["structural_reading"], raw["selected_action_binding"]
                if (type(reading) is not dict or type(binding) is not dict
                        or reading.get("schema") != "unknown-action-reading-v1"
                        or reading.get("status") != "read"
                        or reading.get("search_complete") is not True
                        or reading.get("truncated") is not False
                        or type(reading.get("gaps")) is not list or reading["gaps"]
                        or type(reading.get("unknown_text")) is not str
                        or type(raw.get("verb")) is not str
                        or raw["verb"] != reading["unknown_text"]
                        or raw.get("꼬리", "") not in ("", None, [])
                        or raw.get("잘림", False) is not False
                        or type(raw.get("자리", {})) is not dict):
                    refuse()
                try:
                    ReasoningContext._marked_carrier(parsed)
                except ReadingUnavailable:
                    refuse()
                _n1b3_source_check(record, reading, raw)
                if isinstance(event_ids, dict):
                    eid = event_ids.get("%d:0" % index)
                    if type(eid) is not str or not eid:
                        refuse()
                else:
                    eid = ReasoningContext._event_id(index, None, raw.get("자리", {}), 0)
                if eid in marked:
                    refuse()
                marked[eid] = {"index": index, "oid": oid, "rev": active,
                               "text": record["source"], "raw": raw}
            rows = stored_events if isinstance(stored_events, list) else []
            if not marked:
                if any(ReasoningContext._structural_marked(r["event"]) for r in rows):
                    refuse()
            stored, srows = {}, {}
            for row in rows:
                event = row["event"]
                eid = event.get("id")
                if eid not in marked:
                    if ReasoningContext._structural_marked(event):
                        refuse()
                    continue
                if eid in stored:
                    refuse()
                stored[eid] = event
                srows[eid] = row
            for eid, item in marked.items():
                event, raw, srow = stored.get(eid), item["raw"], srows.get(eid)
                if event is None or type(srow) is not dict:
                    refuse()
                if (type(event.get("sequence")) is not int or event["sequence"] != item["index"]
                        or event.get("action") != raw["verb"] or type(event.get("action")) is not str
                        or not same(event.get("roles"), raw.get("자리", {}))
                        or not same(event.get("role_candidates"), raw.get("자리후보"))
                        or not all(k in event and same(event[k], raw[k]) for k in keys)
                        or event.get("schema") != "nai-action-event-v1"
                        or any(event.get(k) is not None
                               for k in ("program", "domain", "definition_version"))
                        or srow.get("status") != "uninterpreted"
                        or not same(srow.get("effects"), [])
                        or not same(srow.get("state_changes"), [])
                        or any(not same(event.get(k), v) for k, v in (
                            ("references", {}),
                            ("conditions", []), ("fills", []), ("state_fills", []),
                            ("overrides", {}), ("polarity", True), ("modality", "asserted")))):
                    refuse()
            if replay is None:
                return
            smarked = ReasoningContext._structural_marked
            indices = {item["index"] for item in marked.values()}
            oids = {item["oid"] for item in marked.values()}
            mtexts = {item["text"] for item in marked.values()}
            positions = {oid: index for index, oid in enumerate(ids)}
            facts = replay["facts"]
            sources = replay.get("fact_sources")
            usable = isinstance(sources, list) and len(sources) == len(facts)

            def active_record(oid):
                entry = ledger["records"].get(oid) if type(oid) is str else None
                if type(entry) is not dict:
                    return None
                versions, active = entry.get("versions"), entry.get("active")
                if (type(active) is not int or not isinstance(versions, list)
                        or not 1 <= active <= len(versions)):
                    return None
                record = versions[active - 1]
                return (record, active) if type(record) is dict else None

            def unmarked_join(oid, rev, turn, text):
                if type(oid) is not str or oid in oids or oid not in positions:
                    return False
                index = positions[oid]
                if turn is not None and turn != index:
                    return False
                found = active_record(oid)
                if found is None:
                    return False
                record, active = found
                if rev is not None and (type(rev) is not int or rev != active):
                    return False
                if (record.get("observation_id") != oid
                        or type(record.get("source")) is not str
                        or record["source"] != text or str(texts[index]) != text
                        or record.get("unavailable") is not False
                        or smarked(record.get("parsed"))):
                    return False
                return True

            for position, fact in enumerate(facts):
                evidence = fact["evidence"]
                turn, source = evidence.get("turn"), evidence.get("source")
                action = evidence.get("action_event")
                if action is not None:
                    if smarked(action):
                        refuse()
                    if marked and isinstance(action, dict):
                        aid = action.get("id")
                        if type(aid) is str and aid in marked:
                            refuse()
                        aseq = action.get("sequence")
                        if type(aseq) is int and aseq in indices:
                            refuse()
                if not marked:
                    continue
                soid = getattr(source, "oid", None)
                srev = getattr(source, "rev", None)
                if type(soid) is str and soid in oids:
                    refuse()
                meta = sources[position] if usable else None
                meta_ok = (type(meta) is dict
                           and set(meta) == {"observation_id", "reading_revision"}
                           and type(meta["observation_id"]) is str
                           and type(meta["reading_revision"]) is int)
                if meta_ok and meta["observation_id"] in oids:
                    refuse()
                valid = type(turn) is int and 0 <= turn < len(ids)
                if valid and turn in indices:
                    refuse()
                if not isinstance(source, str) or str(source) not in mtexts:
                    continue
                text = str(source)
                if turn is not None and not valid:
                    refuse()
                if soid is not None or srev is not None:
                    if meta_ok and (meta["observation_id"] != soid
                                    or meta["reading_revision"] != srev):
                        refuse()
                    if not unmarked_join(soid, srev, turn, text):
                        refuse()
                elif meta_ok:
                    if not unmarked_join(meta["observation_id"], meta["reading_revision"],
                                         turn, text):
                        refuse()
                elif valid:
                    if text != str(texts[turn]) or not unmarked_join(ids[turn], None, turn, text):
                        refuse()
                else:
                    refuse()

            for row in replay["pending"]:
                if not isinstance(row, dict):
                    continue
                old = row.get("event")
                if any(k in row for k in keys) or (isinstance(old, dict) and smarked(old)):
                    refuse()
                run = row.get("실행")
                env = run if isinstance(run, dict) else None
                at = row.get("at")
                bearing = env is not None and smarked(env)
                if not marked and not bearing:
                    continue
                eid = env.get("id") if env is not None else None
                seq = env.get("sequence") if env is not None else None
                named = ((type(eid) is str and eid in marked)
                         or (type(seq) is int and seq in indices)
                         or (type(at) is int and at in indices))
                if not named and not bearing:
                    continue
                if (env is None or not bearing or type(eid) is not str
                        or eid not in marked):
                    refuse()
                item = marked[eid]
                if (type(seq) is not int or seq != item["index"]
                        or type(at) is not int or at != item["index"]):
                    refuse()
                if any(env.get(k) is not None
                       for k in ("program", "domain", "definition_version")):
                    refuse()
                for carrier in (row, env):
                    for k in ("effects", "state_changes"):
                        value = carrier.get(k)
                        if value is not None and not same(value, []):
                            refuse()
                if not all(k in env for k in keys) or not same(env, stored[eid]):
                    refuse()
        _n1b3_check()
        # ---- commit: the snapshot is fully validated; nothing below can raise ----
        parser.__dict__["chosen_readings"], parser.__dict__["chosen_programs"] = view, programs
        parser.__dict__["blocked_programs"] = blocked
        self.reading_ledger, self._next_observation = ledger["records"], ledger["next"]
        self._obs = new_obs
        self._replay_cache = replay_cache
        if isinstance(snapshot.get("conversation"), str) and snapshot["conversation"]:
            self.conversation_id = snapshot["conversation"]
        self.corrections = deepcopy(corrections)
        # 옛 갈무리에는 이 칸이 없다. 없으면 못 읽은 말도 없는 것으로 읽는다.
        self.unread = deepcopy(unread)
        self.unread_guard = deepcopy(unread_guard)
        self.fills = deepcopy(fills)
        self.last_subject = 마지막
        self.salient = new_salient
        if graph_carried is not None:
            self._graph_carried = graph_carried
        self._graph_cache = None
        self.last_frame = deepcopy(frame)
        self.last_referents = deepcopy(최근역할)
        self.last_concept_relation = deepcopy(last_concept_relation)
        # Older snapshots retain their content-addressed ids so their saved
        # completion records still join correctly during a compatibility replay.
        self.event_ids = deepcopy(event_ids) if event_ids is not None else None
        self.event_revisions = deepcopy(revisions)
        self._stored_event_records = deepcopy(stored_events) if stored_events is not None else None
        self._event_records_count = len(new_obs) if stored_events is not None else 0
        if new_concepts is not None:
            self.concepts = new_concepts
        # 되물은 기억이 없으면 아무것도 안 이어 붙인다 — 덜 잇는 쪽이다.
        self.asked = deepcopy(asked)
        # 막아 둔 물음도 이어져야 한다. 안 그러면 다시 묻게 만든다.
        self.held_question = held
        if verb_cache is not None:
            self._verb_cache = verb_cache

    @staticmethod
    def _triples(parser, rule, event, 이름=(), 받은값=(), 덮기=(), 앞선사실=(), programs=None,
                 조회값=(), 조회사실=()):
        """뜻풀이와 사건을 자리로 맞춰 사실을 낸다.

        맞추는 방법은 하나다 — 조사가 짚는 자리. 같은 자리에 올 수 있는 조사는
        한 이름으로 부른다. 못 채운 자리는 **못 채웠다고** 돌려준다.

        자리를 어디서 끊을지가 여럿이면(`사과 상자를`) **뜻풀이가 고른다** —
        빈 자리를 채우고 어긋나지 않으며 남는 자리가 적은 자름이 옳은 자름이다.
        낱말만 봐서는 못 가르는 것을 개체 증거로 가르는 자리다.
        """
        if isinstance(event, dict) and (
                "structural_reading" in event or "selected_action_binding" in event
                or (isinstance(event.get("실행"), dict)
                    and ("structural_reading" in event["실행"]
                         or "selected_action_binding" in event["실행"]))):
            return {"사실": [], "빈자리": {}, "충돌": {}, "남은자리": set(),
                    "닿는곳": [], "못잼": "structural_uninterpreted",
                    "계산값": {}, "필요": None, "헛자리": {}}
        from marco.reasoning.actions import execute
        from marco.language.frames import particle_key
        임자 = particle_key(parser.doer_particle, parser.slot_particles)
        best = None
        for 후보 in event.get("자리후보") or [event.get("자리", {})]:
            자리 = {particle_key(key, parser.slot_particles): value
                   for key, value in 후보.items()}
            # 되물어 받은 답은 **값으로** 얹는다. 원문을 고쳐 쓰지 않는다.
            자리.update(받은값 or {})
            bound = execute(rule["프로그램"], 자리, overrides=덮기,
                            prior_facts=앞선사실, quantities=parser.quantities,
                            mutable_predicates=parser.data.get("mutable_predicates", []),
                            numeric_updates=parser.data.get("numeric_updates", {}),
                            programs=programs, provided=조회값,
                            provided_facts=조회사실,
                            event_id=((event.get("실행") or {}).get("id")),
                            # A parsed doer is retained in the action event
                            # envelope even where a program intentionally
                            # selects its subject from state and has no doer
                            # input.  Other explicit arguments remain errors.
                            allowed_leftovers=(임자,))
            # Keep the established Korean-facing keys at this boundary.  The
            # binding itself lives in action_runtime so direct calls and a
            # later simulation/call instruction cannot grow different role
            # conflict rules.
            # A program's facts are keyed as parsed facts are: the leading name
            # without the pack's name suffix (``canonical_name``), so a thing a
            # program moved and a question about it meet on one key.
            applied = {"사실": [[parser.canonical_name(triple[0]) if isinstance(triple[0], str) else triple[0]]
                              + list(triple[1:]) for triple in bound["facts"]],
                       "빈자리": bound["missing"],
                       "충돌": {name: {"뜻": value["definition"],
                                       "사건": value["event"], "자리": value["slot"]}
                                for name, value in bound["conflicts"].items()},
                       "남은자리": set(bound["leftover"]), "닿는곳": bound["reachable"],
                       "못잼": {"basis": "기준", "indivisible": "나눔",
                                  "compute_indivisible": "나눔",
                                  "undeclared_state_value": "기준",
                                  "operator": "연산"}.get(bound.get("reason"), bound.get("reason")),
                       "계산값": bound.get("bindings", {}), "필요": bound.get("need")}
            # 뜻풀이가 안 쓰는 자리가 남으면 그 사건은 **뜻풀이가 모르는 것**을
            # 말한 것이다. 처음 보는 이름이라고 넘기면 `단추 4개를 담았다` 가
            # 구슬을 늘린다. 누가 했는지만은 뜻풀이가 안 써도 그만이다.
            헛자리 = {key for key in applied["남은자리"] if key != 임자}
            # 이 대화가 모르는 이름을 자리에 앉힌 자름은 덜 좋은 읽기다. `작은
            # 구슬을` 을 `작` + `구슬을` 로 끊으면 아무도 모르는 `작` 이 주는이가
            # 된다. 어느 자름이 옳은지는 개체 증거가 정한다.
            앎 = sum(1 for value in 자리.values() if value in 이름)
            모름 = len(자리) - 앎
            # 아는 이름을 **많이** 짚고 모르는 이름을 **적게** 만드는 자름이 옳다.
            # 모르는 것만 세면 통째로 삼킨 자름이 이기고(자리가 하나뿐이니까),
            # 아는 것만 세면 `작` 같은 부스러기를 남긴 자름이 이긴다.
            # An unrecognised proper name is weaker evidence than a role the
            # program can actually bind.  Prefer a complete, conflict-free
            # role reading before using the current entity list to choose a
            # shorter fragment; otherwise a first use such as `하린이 공책을`
            # is split into one invented item and a missing actor.
            score = (len(헛자리), len(applied["빈자리"]) + len(applied["충돌"]),
                     -앎, 모름, -len(자리))
            if best is None or score < best[0]:
                best = (score, {**applied, "헛자리": {key: 자리[key] for key in 헛자리}})
        return best[1]

    def _slot_question(self, parser, 빈자리):
        """빈 자리를 사람 말로 되묻는다. 안 적힌 자리는 조사 이름을 보인다."""
        물음 = [parser.slot_questions.get(key) or
              parser.data["context_replies"]["empty_slot"].format(**{"자리": self._slot_name(parser, key)})
              for key in sorted(set(빈자리.values()))]
        return " ".join(물음)

    @staticmethod
    def _slot_name(parser, key):
        """빈 자리를 사람이 알아볼 이름으로. 한 자리를 채우는 조사를 다 보인다."""
        for group in parser.slot_particles:
            if key in group:
                return "/".join(group)
        return key

    def _unsettled(self, query, parser, pending):
        """자리를 못 채운 사건이 건드릴 수 있었던 값은 확정하지 않는다.

        **어느 값이 움직였는지 모른다는 것과 아무 값도 안 움직였다는 것은 다르다.**
        가르지 않으면 해석 실패가 옛 값을 확정하는 쪽으로 샌다.
        """
        numeric = parser.data.get("numeric_updates", {})
        for item in pending:
            # A measured false condition is a known non-execution, not an
            # unknown change.  Its event remains in the replay record, while
            # the old state is safe to answer.
            if item.get("거짓조건"):
                continue
            # 뜻풀이 밖에 놓인 자리가 가리킨 것도 확정하지 않는다. 그 사건이
            # 무엇에 대한 말이었는지를 모르는 채로 그 값을 못 박으면 안 된다.
            for value in item["헛자리"].values():
                for asked in (query or []):
                    subject = str((asked.get("triple") or [""])[0])
                    if any(word and word in value for word in subject.split()):
                        return item
            for triple in item["닿는곳"]:
                target = (numeric.get(triple[1]) or {}).get("target", triple[1])
                known = [piece for piece in str(triple[0]).split() if "$" not in piece]
                for asked in (query or []):
                    asked_triple = asked.get("triple") or [None, None]
                    # **낱말이 하나라도 겹치면** 그 값은 확정하지 않는다. 전부
                    # 겹쳐야 막으면, 못 읽어 대상이 더럽혀진 사건(`민수 가진 구슬`)이
                    # `민수 구슬` 물음을 못 막고 옛 값이 그대로 확정된다.
                    if (asked_triple[1] == target
                            and (not known
                                 or any(piece in str(asked_triple[0]) for piece in known))):
                        return item
        return None

    @staticmethod
    def _forms_of(parser, stems):
        """뜻풀이로 받은 어간들이 어떤 꼴로 나타날 수 있나. 활용은 언어팩이 계산한다.

        임의의 어간을 되돌려 쪼개지 않는다 — 이 대화에서 **이미 설명받은** 어간만
        펼쳐 놓고 견준다. 그래서 모르는 말을 멋대로 어간으로 오려내는 일이 없다.

        꼴마다 **어간과 함께 물음인지도** 적는다. 어간만 나르면 `베풉니까` 가
        `베풀` 로 이어지면서 물음이라는 것이 사라져, 물어본 일이 실제로 일어난다.
        묻기에만 쓰는 꼬리라야 물음의 표다 — `베풀었어요` 는 서술로도 쓴다.
        """
        from marco.language.hangul import inflect
        grammar = parser.inflection_grammar or {}
        asking = parser._asking(grammar)
        table = {}
        for stem in stems:
            for kind in grammar.get("kinds", []):
                for tense in grammar.get("tenses", {}):
                    for ending in grammar.get("endings", {}):
                        try:
                            forms = inflect(stem, tense, ending, grammar, kind=kind)
                        except ValueError:
                            continue
                        for form in forms:
                            entry = table.setdefault(form["text"],
                                                     {"stem": stem, "물음": True})
                            if ending not in asking:
                                entry["물음"] = False
                            if ending in grammar.get("condition_endings", []):
                                entry["조건"] = True
        return table

    @staticmethod
    def _lookup(parser, event, keys, table=None):
        """사건에 나온 꼴을 뜻풀이의 어간에 잇는다."""
        if isinstance(event, dict) and (
                "structural_reading" in event or "selected_action_binding" in event
                or (isinstance(event.get("실행"), dict)
                    and ("structural_reading" in event["실행"]
                         or "selected_action_binding" in event["실행"]))):
            return None
        verb = event["verb"]
        if verb in keys:
            return verb
        surface = verb + event.get("꼬리", "")
        if table is None:
            table = ReasoningContext._forms_of(parser, keys)
        found = table.get(surface)
        return found["stem"] if found else None

    @staticmethod
    def _declared_event_domain(parser, program):
        """Return the one pack-declared domain matching a program's effects."""
        predicates = {triple[1] for step in program.get("steps") or []
                      for triple in step.get("triples") or []
                      if isinstance(triple, list) and len(triple) == 3 and isinstance(triple[1], str)}
        predicates.update(step["predicate"] for step in program.get("steps") or []
                          if isinstance(step.get("predicate"), str))
        operations = {step.get("op") for step in program.get("steps") or []
                      if isinstance(step.get("op"), str)}
        matches = [row.get("name") for row in parser.language_pack.get("event_domains", [])
                   if isinstance(row, dict) and isinstance(row.get("name"), str)
                   and set(row.get("effect_predicates") or []) <= predicates
                   and set(row.get("operations") or []) <= operations
                   and (row.get("effect_predicates") or row.get("operations"))]
        return matches[0] if len(matches) == 1 else None

    @staticmethod
    def _rule(parser, rule, 배운것=None):
        """뜻풀이 하나를 쓸 수 있는 꼴로 만든다. 못 읽으면 None.

        틀은 어디에도 적혀 있지 않다. **몸통을 이미 아는 문장꼴로 읽어** 꺼낸다.
        끝내 못 읽으면 그 말은 모르는 말로 남는다 — 못 읽은 뜻풀이를 반쯤
        쓰느니 그 말이 건드린 값을 확정하지 않는 쪽이 낫다.

        ``배운것`` 은 **이 뜻풀이보다 먼저** 설명받은 동작들이다. 뒤에 배운 것은
        안 넘긴다 — 그래야 옛 사건이 나중 설명으로 무단히 바뀌지 않는다.
        어느 시점의 뜻을 참조했는지는 `참조` 에 남긴다.
        """
        body = rule.get("몸통")
        if not body:
            return None
        뜻표 = (배운것 or {}).get("뜻") or {}
        열쇠 = (body, tuple(sorted((stem, 때) for stem, 때 in
                                  ((배운것 or {}).get("때") or {}).items())))
        cache = parser.induced_frames
        if 열쇠 not in cache:
            from marco.language.frames import induce
            cache[열쇠] = induce(parser, body, 배운것)
        유도 = cache[열쇠]
        if 유도 is None:
            return None
        쓴동사 = list(유도.get("쓴동사") or ())
        # 제 뜻을 제 몸통에 쓰면 풀 수가 없다. 앞선 뜻이 있으면 그것을 가리킨
        # 것이므로 괜찮다 — 그때는 `참조` 에 그 시점이 남는다.
        if rule["verb"] in 쓴동사 and rule["verb"] not in 뜻표:
            return None
        참조 = {stem: ((배운것 or {}).get("때") or {}).get(stem) for stem in 쓴동사}
        from marco.reasoning.actions import compile_program
        compiled = {**rule, "유도": 유도, "쓴동사": 쓴동사, "참조": 참조}
        program = compile_program(compiled)
        domain = ReasoningContext._declared_event_domain(parser, program)
        if domain:
            program["domain"] = domain
        return {**compiled, "프로그램": program}

    @staticmethod
    def _learned(parser, timeline, 꼴모음):
        """지금까지 배운 동작들. 뜻틀과 그 꼴, 그리고 **언제 배운 것인지**."""
        stems = tuple(sorted(timeline))
        if stems not in 꼴모음:
            표 = ReasoningContext._forms_of(parser, set(stems))
            꼴모음[stems] = {surface: found["stem"] for surface, found in 표.items()
                          if not found["물음"]}
        return {"뜻": {stem: rows[-1][1]["유도"] for stem, rows in timeline.items()},
                "때": {stem: rows[-1][0] for stem, rows in timeline.items()},
                "꼴": 꼴모음[stems]}

    def _resolve_pointers(self, parser, query, facts):
        """물음이 **앞서 말한 것을 도로 가리키면** 무엇인지 찾는다.

        고르지 않는다. 가리킬 것이 여럿이면 묻고, 없으면 못 찾았다고 말한다.
        마지막으로 답한 물음의 대상이 후보에 있으면 그것이 가장 가까운 것이다.

        가리킴말이 자리의 **일부**일 수도 있다 — `그 사람 구슬` 은 `구슬` 로 끝나는
        대상 가운데 하나다. 그래서 가리킴말을 뺀 나머지가 맞는 것만 후보로 둔다.
        """
        말들 = [w for w in sorted(parser.pointers or [], key=len, reverse=True) if w]
        if not 말들 or not query:
            return query, None
        차례표 = {}
        # A pointer (he, she, 그 사람) names someone other than the speaker: the speaker's
        # own key (the pack's 임자자리말, I / 나) is never what it points back to.
        speaker = parser.speaker_placeholder
        for item in facts:
            이름 = str(item["triple"][0])
            if speaker and self._person_of(이름) == speaker:
                continue
            차례표[이름] = max(차례표.get(이름, -1), item["evidence"].get("turn", -1))
            if parser.ellipsis.get("part_reference") == "leading_words" and len(이름.split()) > 1:
                # 앞말만으로 대상을 가리키는 언어라면 그 앞말도 가리킬 수 있는 것이다 (the holder as one identity, step 3).
                앞말 = self._person_of(이름)
                차례표[앞말] = max(차례표.get(앞말, -1), item["evidence"].get("turn", -1))
        풀림 = []
        for asked in query:
            triple = list(asked.get("triple") or [])
            대상 = str(triple[0]) if triple else ""
            # 가리킴말은 낱말 단위로 찾는다. 글자로 찾으면 `the` 안의 `he` 도 걸린다.
            낱말 = 대상.split()
            말 = next((w for w in 말들 if w and any(
                낱말[i:i + len(w.split())] == w.split() for i in range(len(낱말)))), None)
            if 말 is None:
                풀림.append(asked)
                continue
            나머지 = " ".join(x for x in 낱말 if x not in 말.split()).strip()
            후보 = [(차례, 이름) for 이름, 차례 in 차례표.items()
                  if (not 나머지 and 이름) or (나머지 and 이름 != 나머지
                                            and 이름.endswith(나머지))]
            if 말 in ((parser.language_pack or {}).get("person_pointers") or []):
                # A pointer to a person (사람지시어: he, she, 그분) never means a place things are kept in (G5).
                장소 = {place for item in facts for place in item.get("places") or [] if isinstance(place, str)}
                후보 = [(차례, 이름) for 차례, 이름 in 후보
                      if not any(이름 == place or 이름.startswith(place + " ") for place in 장소)]
            if not 후보 and self._effort_allows(2) and len(나머지.split()) >= 2:
                # 그 친구 공책: a pointer with a word that describes the holder (a relation, a title) and the thing;
                # the holders that word was said with in a statement, else every holder of the thing (G7-Q)
                *describe, thing = 나머지.split()
                of_thing = [(차례, 이름) for 이름, 차례 in 차례표.items() if 이름.endswith(" " + thing)]
                described = [(차례, 이름) for 차례, 이름 in of_thing if any(
                    re.search(r"(?<![\w])%s\s+%s" % (re.escape(" ".join(describe)), re.escape(이름[:-len(thing)].strip())),
                              source) for source in self.observations)]
                후보 = described or of_thing
                if 후보:
                    말 = "%s %s" % (말, " ".join(describe))     # the reply that names one replaces both words
            이름들 = [이름 for _차례, 이름 in sorted(후보, reverse=True)]
            고른것 = self._salient_choice(이름들)
            if 고른것 is None and len(이름들) == 1 and self._alone(이름들[0]):
                고른것 = 이름들[0]
            if 고른것 is None:
                return query, {"말": 말, "후보": 이름들}
            self._graph_alias(고른것, 말, "pointer")
            풀림.append({**asked, "triple": [고른것] + triple[1:]})
        return 풀림, None

    def _person_of(self, key):
        """The holder a key names, as one identity (step 3): the holder node's name at effort 2 and above (a holder
        of several words, 김 과장, red shed, is one person), the key's leading word below (main's behaviour)."""
        key = str(key or "")
        if not key.split():
            return key
        if not self._effort_allows(2) or not self._permitted(None):
            return key.split()[0]
        try:
            graph = self.conversation_graph()
        except Exception:    # noqa: BLE001
            return key.split()[0]
        known = graph.of_key(key)
        if known is not None:
            return graph.nodes[known[0]]["name"]
        named = [n["name"] for n in graph.nodes.values() if n["kind"] in ("holder", "place")
                 and (key == n["name"] or key.startswith(n["name"] + " "))]
        return max(named, key=len) if named else key.split()[0]

    def _salient_person(self):
        """The one person the discourse fixes for a pointer, or None (G3.0 a).

        The last question that named someone fixes whom it named; every
        statement since adds whom it names. Before any such question, every
        statement's people count. A pointer is read as a person only when
        that set is exactly one person; with two or more it is asked back.
        """
        people = []
        speaker = self._parser().speaker_placeholder if self._permitted(None) else ""
        for name in self.salient:
            if name not in people and name != speaker:
                people.append(name)
        return people[0] if len(people) == 1 else None

    def _alone(self, name):
        """No other person the discourse names could be meant instead of ``name``."""
        return set(self.salient) <= {self._person_of(name)}

    def _salient_choice(self, names):
        """The candidate among ``names`` that is the salient person, or None."""
        person = self._salient_person()
        if person is None:
            return None
        same = [name for name in names if name == person or name.startswith(person + " ")]
        if self.last_subject in same:
            return self.last_subject
        if person in same:
            return person
        return same[0] if len(same) == 1 else None

    def _named_people(self, parser, rows):
        """The people a question names: the leading word of each subject it asks
        about, the members of a sum, the two sides of a comparison. A subject
        that holds a declared pointer names nobody yet."""
        pointers = [word for word in (parser.pointers or []) if word]
        out = []

        def add(value):
            if not isinstance(value, str) or not value.strip() or value.startswith(("?", "$")):
                return
            words = value.split()
            if any(words[i:i + len(p.split())] == p.split() for p in pointers for i in range(len(words))):
                return
            person = self._person_of(value)
            if person not in out:
                out.append(person)
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            triple = row.get("triple")
            if isinstance(triple, list) and triple:
                add(triple[0])
            total = row.get("total") if isinstance(row.get("total"), dict) else {}
            if isinstance(total.get("members"), list):
                for member in total["members"]:
                    add(member)
            for kind in ("more", "fewer", "same"):
                compared = row.get(kind) if isinstance(row.get(kind), dict) else {}
                for side in ("a", "b"):
                    add(compared.get(side))
            why = row.get("why_count") if isinstance(row.get("why_count"), dict) else {}
            if isinstance(why.get("subject"), list) and why["subject"]:
                add(" ".join(str(part) for part in why["subject"]))
        return out

    @staticmethod
    def _same_word(word, source, other, target):
        """Is ``word`` (read by ``source``) the same as ``other`` (in ``target``)?

        Same spelling, the same declared concept id, or the same name written
        in another script by a declared romanization. Nothing else counts.
        """
        from marco.language.hangul import romanize
        if word.lower() == other.lower():
            return True
        concept = source.senses.get(word) or source.senses.get(word.lower())
        if concept and concept == (target.senses.get(other) or target.senses.get(other.lower())):
            return True
        for hangul, latin, table in ((other, word, target.romanization), (word, other, source.romanization)):
            spelled = romanize(hangul, table)
            if spelled and spelled == latin.lower():
                return True
        # A counted noun written in the same letters in both languages (LED, USB):
        # the asking pack's declared plural of it is the same thing (LEDs).
        from relational_semantics import declared_plural
        for plural_of, one, many in ((source, other, word), (target, word, other)):
            declared = getattr(plural_of, "noun_number", None) or {}
            spelled = declared_plural(one, declared)
            if spelled and spelled.lower() == many.lower() and one.isascii():
                return True
        return False

    def _companion_turn(self, parser, text, knowledge_path):
        """A question in another language of the same pack, about this conversation.

        The question is read by its own language pack; each word of its
        subject is matched to this conversation's words by `_same_word`, and
        the answer is realized by that pack's own render. Statements are not
        taken across languages — only questions. If a word matches nothing, or
        more than one thing, the question is held.
        """
        for model in self.companions:
            key = id(model)
            if key not in self._companion_parsers:
                self._companion_parsers[key] = model.parser()
                self._companion_parsers[key].effort = self.effort
            other = self._companion_parsers[key]
            read = self._read_source(other, text, events=True)
            if not read or not read.get("query") or read.get("facts") or read.get("사건") or read.get("정의"):
                continue
            if not all(isinstance(q, dict) and isinstance(q.get("triple"), list) for q in read["query"]):
                continue
            facts, _defined, _pending, _read = self._cached_replay(parser, self.observations, self.fills)
            state_words = sorted({word for item in facts for value in (item["triple"][0], item["triple"][2])
                                  if isinstance(value, str) for word in value.split()})
            replies = other.data["context_replies"]
            translated, mapping = [], {}
            for query in read["query"]:
                subject = query["triple"][0]
                if not isinstance(subject, str) or subject.startswith(("?", "$")):
                    translated.append(query)
                    continue
                words = []
                for at, word in enumerate(subject.split()):
                    matches = [w for w in state_words if self._same_word(word, other, w, parser)]
                    if not matches and words and self._effort_allows(2):
                        # the holder matched and the thing did not (the pack declares no word for it): the
                        # things that holder counts are the candidates, ranked, a clear winner only (G7-Q)
                        held_by = " ".join(words)
                        things = sorted({str(row["triple"][0])[len(held_by):].strip() for row in facts
                                         if isinstance(row.get("triple"), list) and isinstance(row["triple"][0], str)
                                         and row["triple"][1] == "count"
                                         and str(row["triple"][0]).startswith(held_by + " ")} - {""})
                        # (no word says which of two things: two ask, the last question's thing is no evidence)
                        asked = " ".join(subject.split()[at:])
                        concept = other.senses.get(asked) or other.senses.get(asked.lower())
                        # a thing both packs declare a concept for, and not the same one, is another thing
                        things = [t for t in things if not (concept and (parser.senses.get(t) or parser.senses.get(
                            t.lower())) and (parser.senses.get(t) or parser.senses.get(t.lower())) != concept)]
                        # only a word in another writing system may name it: written in the same letters it would
                        # have matched by spelling, so it is another thing (USBx is not USB)
                        script = (lambda w: "hangul" if re.search("[가-힣]", w) else "latin")
                        things = [t for t in things if script(t) != script(asked)]
                        winner, deciding, ranking = self._rank_candidates(
                            [{"label": thing, "fit": {"state": 1}} for thing in things], kind="cross_language_thing")
                        if winner is not None:
                            words += winner["label"].split()
                            mapping[" ".join(subject.split()[at:])] = winner["label"]
                            break
                        matches = [c["label"] for c in ranking]
                    if len(matches) != 1:
                        return {"operator": "relational_graph", "status": "unresolved", "transitions": [],
                                "meaning": {"act": "ask", "reason": "which_referent" if matches else "no_referent",
                                            "word": word, "candidates": list(matches),
                                            "answer_language": (getattr(model, "sources", None) or [{}])[0].get("path")},
                                "answer": (replies["which_referent"].format(**{"말": word, "목록": ", ".join(
                                    "'%s'" % m for m in matches)}) if matches else
                                    replies["no_referent"].format(**{"말": word})),
                                "verification": self._verification(knowledge_path, [{
                                    "ok": False, "reason": "cross_language_unmatched", "word": word}])}
                    words.append(matches[0])
                    mapping[word] = matches[0]
                translated.append({**query, "triple": [" ".join(words)] + query["triple"][1:]})
            # A question in the other language reads the same state, so what
            # holds it in this language holds it there: an unread or corrected-
            # but-unapplied statement about the asked holder (G3.0 b).
            blocked = self._blocked_by(translated, parser, facts)
            if blocked is not None:
                said, reason = blocked
                key = ("contradiction" if reason == "어긋남" else
                       "capacity" if reason == "용량" else "unread_event")
                return {"operator": "relational_graph", "status": "unresolved", "transitions": [],
                        "meaning": {"act": "hold", "reason": key, "said": said,
                                    "answer_language": (getattr(model, "sources", None) or [{}])[0].get("path")},
                        "answer": replies[key].format(**{"말": said}),
                        "verification": self._verification(knowledge_path, [{
                            "ok": False, "reason": "cross_language_" + key}])}
            outcome = other.answer({"facts": facts, "query": translated})
            checks = [{"ok": outcome is not None, "reason": "cross_language_question",
                       "language": (getattr(model, "sources", None) or [{}])[0].get("path", ""),
                       "mapping": mapping}]
            if outcome is None:
                missing = self._missing_premise(other, translated, facts)
                premise = self._premise_missing(other, translated, facts) if missing else None
                return {"operator": "relational_graph", "status": "unresolved", "transitions": [],
                        "answer": missing or replies["unresolved"],
                        "meaning": ({"act": "refuse", "reason": "premise_missing", **premise,
                                     "answer_language": checks[0]["language"]} if premise
                                    else {"act": "hold", "reason": "unresolved"}),
                        "verification": self._verification(knowledge_path, checks)}
            return {"operator": "relational_graph", "status": "answered", **outcome,
                    "cross_language": {"mapping": mapping},
                    "meaning": {"act": "inform", "query": deepcopy(translated[0].get("triple")),
                                "render": deepcopy(translated[0].get("render")),
                                # What the question named, in this conversation's words.
                                "asked": deepcopy(translated[0].get("triple")),
                                "answer_language": checks[0]["language"]},
                    "verification": self._verification(knowledge_path, checks)}
        return None

    @staticmethod
    def _repairs_under(transitions):
        """Every repair the given evidence rests on, once each."""
        seen, found = set(), []
        for row in transitions:
            evidence = row.get("evidence") or {}
            report = (evidence.get("normalization") or {}).get("repair")
            if report and report.get("status") == "repaired" and report["source"] not in seen:
                seen.add(report["source"])
                found.append(report)
        return found

    def _explain_count(self, parser, request, text, facts, knowledge_path):
        """``Why does Bo have that many figs?``: explain that holder's current count.

        The count is read as the count question would read it; the explanation
        is the one ``why`` gives for an answer (rules and statements). A holder
        whose count is not known, or is held by an unread event, is not
        explained.

        G6 class 13: the why may restate the count (``value``) and may name no
        holder. With no holder it is about the last answer's holder; a last
        answer that named none or several is asked back. A holder named
        without its thing takes the thing of the last answer when only the
        thing differs among the holder's counts, otherwise it is asked back. A
        restated number that is not the current count is held, not explained.
        """
        replies = parser.data["context_replies"]
        said, value = text.strip(), request.get("value")
        last = self.last_explanation or {}
        answered = last.get("subject") or (
            (self.last_question or {}).get("subject")
            if last.get("kind") == "answer" and (self.last_question or {}).get("text") == last.get("question") else None)

        def held(reason, check, **fields):
            return {"operator": "relational_graph", "status": "unresolved", "transitions": [],
                    "answer": replies.get(reason, replies["unresolved"]),
                    "meaning": {"act": "hold", "reason": reason, "said": said, **fields},
                    "verification": self._verification(knowledge_path, [{"ok": False, "reason": check}])}

        def ask(word, candidates):
            reason = "which_referent" if candidates else "no_referent"
            return {"operator": "relational_graph", "status": "unresolved", "transitions": [],
                    "answer": replies[reason].format(**{"말": word, "목록": ", ".join("'%s'" % c for c in candidates)}),
                    "meaning": {"act": "ask", "reason": reason, "word": word, "candidates": list(candidates)},
                    "verification": self._verification(knowledge_path, [{"ok": False, "reason": reason}])}

        if request.get("subject"):
            subject = parser.canonical_name(" ".join(request["subject"]))
            resolved, pointer = self._resolve_pointers(parser, [{"triple": [subject, "count", "?n"]}], facts)
            if pointer is not None:
                return ask(pointer["말"], pointer["후보"])
            subject = resolved[0]["triple"][0]
            held_counts = {str(row["triple"][0]) for row in facts if row["triple"][1] == "count"}
            named = sorted(name for name in held_counts if name.startswith(subject + " "))
            if subject not in held_counts and len(named) == 1:
                subject = named[0]
            elif subject not in held_counts and len(named) > 1:
                # the thing left out: the last answer's, when the counts differ in their thing only
                if answered in named and len({tuple(name.split()[:-1]) for name in named}) == 1:
                    subject = answered
                else:
                    return ask(subject, named)
        elif not last:
            return held("explain_nothing", "nothing_to_explain")
        elif answered:
            subject = answered
        else:
            told = sorted({str(row["fact"][0]) for row in last.get("transitions") or []
                           if isinstance(row.get("fact"), list) and len(row["fact"]) == 3 and row["fact"][1] == "count"})
            return ask(str(value) if value is not None else said, told)
        query = [{"triple": [subject, "count", "?n"], "render": ["$n"]}]
        blocked = self._blocked_by(query, parser, facts)
        outcome = None if blocked is not None else parser.answer({"facts": facts, "query": query})
        if outcome is None:
            return held("explain_nothing", "nothing_to_explain")
        recorded = str(outcome.get("answer"))
        about = {"holder": subject, "value": int(recorded) if recorded.lstrip("-").isdigit() else recorded}
        if value is not None and str(value) != recorded:
            # the restated number is not the count: never explain a number that is not true (request G6-3)
            return held("unresolved", "restated_count_differs", about={**about, "value": value, "recorded": about["value"]},
                        differs=True)
        self.last_explanation = {"kind": "answer", "question": said, "answer": outcome.get("answer"),
                                 "transitions": deepcopy(outcome.get("transitions", [])), "subject": subject}
        result = self._explain_last(parser, knowledge_path, chain=subject == answered)
        result["meaning"] = {**result["meaning"], "about": about}
        return result

    def _explain_last(self, parser, knowledge_path, chain=True):
        """`왜 그렇게 됐어?`: the last answer or correction, its rules and its evidence.

        Composed from the recorded transitions only: the evidence sentences
        are the user's own words, the rule names are the pack's, and a reading
        that rested on a repair says which repair. Nothing is explained that
        was not recorded.
        """
        replies = parser.data["context_replies"]
        rule_names = parser.data.get("rule_names", {})
        last = self.last_explanation
        if not last:
            return {"operator": "relational_graph", "status": "unresolved", "transitions": [],
                    "answer": replies["explain_nothing"],
                    "meaning": {"act": "hold", "reason": "explain_nothing"},
                    "verification": self._verification(knowledge_path, [{"ok": False, "reason": "nothing_to_explain"}])}
        transitions = last["transitions"]
        updates = parser.data.get("numeric_updates", {})
        rules, rule_ids, evidence = [], [], []
        for row in transitions:
            # a count said without its holder rests also on the statement that named the holder (G5)
            named_in = str(((row.get("evidence") or {}).get("bound") or {}).get("named_in") or "").strip()
            if named_in and named_in not in evidence:
                evidence.append(named_in)
            text = ((row.get("evidence") or {}).get("source") or (row.get("evidence") or {}).get("text") or "").strip()
            if text and text not in evidence:
                evidence.append(text)
        # A statement corrected in place is cited as it now reads, and also as
        # the user first said it and as they corrected it.
        said = []
        for source in evidence:
            record = next((r for r in self.corrections if r.get("after", "").strip() == source), None)
            for text in [source] + ([record["before"].strip(), record.get("utterance", "").strip()] if record else []):
                if text and text not in said:
                    said.append(text)
        evidence = said
        for source in evidence:
            parsed = self._read_source(parser, source, events=True,
                                       verbs=self._verbs_for(parser, self.observations)) or {}
            for fact in parsed.get("facts", []):
                name = fact["triple"][1]
                if name in updates and name in rule_names and rule_names[name] not in rules:
                    rules.append(rule_names[name])
                    rule_ids.append(name)
        changes = [row for row in transitions if row.get("operation") == "quantity_update"]
        repairs = self._repairs_under(transitions)
        repair_note = (replies["explain_repairs"].format(**{"목록": "; ".join(
            '"%s" → "%s"' % (r["source"], r["reading"]) for r in repairs)}) if repairs else "")
        values = {"근거": ", ".join('"%s"' % e for e in evidence),
                  "규칙": ", ".join(rules) or replies.get("explain_no_rule", ""),
                  "목록": parser.render_changes(changes), "수선": repair_note}
        meaning = {"act": "explain", "kind": last["kind"], "question": last.get("question"),
                   "evidence": list(evidence), "rules": list(rule_ids),
                   "changes": deepcopy(changes),
                   "repairs": [{"source": r["source"], "reading": r["reading"]} for r in repairs]}
        if last["kind"] == "correction":
            record = last["correction"]
            meaning["correction"] = {"utterance": record.get("utterance", ""), "before": record["before"].strip(),
                                     "after": record["after"].strip(), "old": record["reference"]["old"],
                                     "new": record["reference"]["new"]}
            answer = replies["explain_correction"].format(**{
                **values, "정정": record.get("utterance", ""), "전사건": record["before"].strip(),
                "후사건": record["after"].strip(), "전": record["reference"]["old"],
                "후": record["reference"]["new"]})
        else:
            answer = replies["explain_answer"].format(**{**values, "물음": last["question"],
                                                        "답": last["answer"]})
        people = sorted({self._person_of(row.get("subject", "")) for row in changes if row.get("subject")})
        self.last_mentioned = people
        self.last_subject = people[0] if len(people) == 1 else None
        if people:
            self.salient = list(people)
        result = {"operator": "relational_graph", "status": "answered", "answer": answer,
                  "meaning": meaning,
                  "transitions": deepcopy(transitions),
                  "verification": self._verification(knowledge_path, [{
                      "ok": True, "reason": "explained_recorded_transitions",
                      "evidence": evidence, "repairs": len(repairs)}])}
        # the ledger's chain is that of the last output: said only when the explanation is about it
        return self._with_trace_chain(result, last["kind"]) if chain else result

    def _with_trace_chain(self, result, explains):
        """Request W4-1: with a trace ledger on (``self.trace``), a bare why says the why chain of this
        conversation's last explainable output (``marco.trace.explain``), composed by the realizer from
        ``chain_meaning``; everything else of the result stays as the engine built it. With recording off,
        with no explainable output of this conversation in the ledger, or with a ledger that cannot be
        read, the result is the engine's own explanation, unchanged."""
        if self.trace is None:
            return result
        try:
            from marco.trace.explain import chain_meaning, last_explainable
            from marco.trace.why import Graph
            graph = Graph(self.trace)
            output = last_explainable(graph, getattr(self, "trace_conversation", None) or self.conversation_id)
            if output is None:
                return result
            meaning = {**chain_meaning(graph, output), "explains": explains}
        except Exception:        # noqa: BLE001 -- LedgerError, a missing event: the engine's explanation
            return result
        result["meaning"] = meaning
        result["verification"]["checks"].append({"ok": True, "reason": "explained_trace_chain", "output": output})
        return result

    def _answer_other_than(self, parser, request, facts, knowledge_path):
        """`그 사람 말고 다른 사람은?`: never pick a referent the context does not fix."""
        replies = parser.data["context_replies"]
        excluded = request["excluded"]
        pointers = set(parser.pointers or [])

        def unresolved(key, fields=None, **values):
            return {"operator": "relational_graph", "status": "unresolved", "transitions": [],
                    "answer": replies[key].format(**values),
                    "meaning": {"act": "ask", "reason": key, "word": request["excluded"], **(fields or {})},
                    "verification": self._verification(knowledge_path, [{"ok": False, "reason": key}])}
        people = sorted({self._person_of(item["triple"][0]) for item in facts
                         if isinstance(item.get("triple", [None])[0], str)
                         and len(str(item["triple"][0]).split()) > 1})
        if excluded in pointers:
            if isinstance(self.last_subject, str) and self.last_subject in people and len(self.last_mentioned) <= 1:
                excluded = self.last_subject
            else:
                candidates = [name for name in (self.last_mentioned or people) if name in people]
                return unresolved("which_referent", {"candidates": candidates}, 말=request["excluded"],
                                  목록=", ".join("'%s'" % name for name in candidates))
        others = [name for name in people if name != excluded]
        if len(others) != 1:
            return unresolved("which_referent" if others else "no_referent",
                              {"excluded": excluded, "candidates": others}, 말=request["excluded"],
                              목록=", ".join("'%s'" % name for name in others))
        last = self.last_explanation or {}
        question = last.get("question")
        return unresolved("other_than_confirm", {"excluded": excluded, "other": others[0], "candidates": others},
                          말=request["excluded"], 제외=excluded, 다른=others[0])

    @staticmethod
    def _contrast(parser, text):
        """``{old, new}`` from a declared contrast of two quantities, or None.

        The pack declares the marker and which side is the new value
        (대조정정). One number must stand on each side, next to the marker:
        the last one before it and the first one after it.
        """
        from marco.language.numerals import parse_numeral
        spec = parser.language_pack.get("contrast_correction") or {}
        numerals = parser.data.get("numerals", {})
        folded = text.lower() if parser.data.get("ignore_case") else text

        def numbers(segment):
            words = [word for word in re.split(r"[\s,.!?]+", segment) if word]
            return [value for value in (ReasoningContext._amount_of(parser, word) for word in words)
                    if value is not None]
        for marker in spec.get("markers", []):
            marker = marker.lower() if parser.data.get("ignore_case") else marker
            if folded.count(marker) != 1:
                continue
            left, right = folded.split(marker)
            before, after = numbers(left), numbers(right)
            if not before or not after:
                continue
            if spec.get("order") == "new_old":
                new, old = before[-1], after[0]
            else:
                old, new = before[-1], after[0]
            if old == new:
                continue
            return {"verb": None, "old": old, "new": new,
                    "evidence": {"text": text.strip(), "contrast": marker}}
        return None

    @staticmethod
    def _is_request(parser, piece):
        """The utterance is in a request form the pack declares (요청)."""
        spec = getattr(parser, "request", None) or {}
        said = piece.strip().rstrip(".!?？。 ")
        folded = said.lower() if parser.data.get("ignore_case") else said
        heads = [h.lower() if parser.data.get("ignore_case") else h for h in spec.get("heads", [])]
        tails = [t.lower() if parser.data.get("ignore_case") else t for t in spec.get("tails", [])]
        if any(folded == h or folded.startswith(h + " ") for h in heads) or any(folded.endswith(t) for t in tails):
            return True
        # a bare imperative (요청.imperative): a declared request verb in its base form opens the sentence, with no
        # subject before it, and a declared object opener follows it (Order a new box of quills.). A later verb
        # form the reader knows, or a word the pack's regular past ending makes, makes it a statement instead
        # (Order the general imposed held the city.), and it is kept as any unread statement is
        bare = spec.get("imperative") or {}
        fold = (lambda v: v.lower()) if parser.data.get("ignore_case") else (lambda v: v)
        words = [w.strip(",") for w in said.split()]
        if len(words) < 3 or fold(words[0]) not in {fold(v) for v in bare.get("verbs", [])} \
                or fold(words[1]) not in {fold(o) for o in bare.get("objects", [])}:
            return False
        endings = set()
        for rules in ((parser.inflection_grammar or {}).get("endings") or {}).values():
            for rule in rules:
                if (rule.get("when") or {}).get("tense") == "present":
                    continue
                for step in rule.get("steps", []):
                    for op in (step, step.get("else") or {}):
                        if op.get("op") == "append" and op.get("text"):
                            endings.add(fold(op["text"]))
        later = parser.open_reading(" ".join(words[1:]))["tokens"]
        return not any(t["kind"] in ("verb", "marker") or any(
            fold(t["text"]).endswith(e) and len(t["text"]) > len(e) + 1 for e in endings) for t in later)

    @staticmethod
    def _amount_of(parser, word):
        """The amount a typed word says: a numeral word or digits, or one written
        together with a counter the pack declares (``1개가``, ``3개였어요``)."""
        from marco.language.numerals import parse_numeral
        numerals = parser.data.get("numerals", {})
        value = parse_numeral(word, numerals)
        if value is not None:
            return value
        for unit in sorted((parser.counters or {}).get("units", []), key=len, reverse=True):
            at = word.find(unit)
            if at > 0:
                return parse_numeral(word[:at], numerals)
        # a numeral said as a noun with the copula after it (하나였습니다, 둘이에요): the pack's amount tails
        tails = (parser.language_pack.get("contrast_correction") or {}).get("amount_tails", [])
        for tail in sorted(tails, key=len, reverse=True):
            if word.endswith(tail) and len(word) > len(tail):
                value = parse_numeral(word[:-len(tail)], numerals)
                if value is not None:
                    return value
        return None

    def _restatement(self, parser, text):
        """``잘못 말했다, 한 개 준 거야``: one new amount for the one event its verb names.

        The pack declares the heads that say an earlier statement was wrong
        (대조정정.restate_heads). The verb is named by its declared reference
        form; exactly one earlier change made by that verb must exist, and its
        amount is the old one. Anything else is not read here.
        """
        from marco.language.numerals import parse_numeral
        spec = parser.language_pack.get("contrast_correction") or {}
        fold = (lambda value: value.lower()) if parser.data.get("ignore_case") else (lambda value: value)
        heads = [head for head in spec.get("restate_heads", []) if head and fold(head) in fold(text)]
        if not heads:
            return None
        at = fold(text).index(fold(heads[0])) + len(heads[0])
        rest = text[at:]
        numerals = parser.data.get("numerals", {})
        words = [word for word in re.split(r"[\s,.!?]+", rest) if word]
        values = [value for value in (self._amount_of(parser, word) for word in words) if value is not None]
        if len(values) != 1:
            return None
        updates = parser.data.get("numeric_updates", {})
        verbs = self._verbs_for(parser, self.observations)
        found = []
        for index, source in enumerate(self.observations):
            parsed = self._read_source(parser, source, events=True, verbs=verbs) or {}
            for fact in parsed.get("facts", []):
                stem = ((fact["evidence"].get("normalization") or {}).get("stem") or fact.get("verb")
                        or self._declared_stem(parser, fact["evidence"]["text"]))
                if not stem or fact["triple"][1] not in updates:
                    continue
                forms = self._frame_reference_forms(parser, stem, every_form=True)
                named = next((word for word in words if word in forms), None)
                if named is not None and (index, fact["triple"][2], named) not in found:
                    found.append((index, fact["triple"][2], named))
        events = {index for index, _value, _word in found}
        if len(events) != 1 or len({value for _i, value, _w in found}) != 1:
            return None
        _index, old, named = found[0]
        if old == values[0]:
            return None
        return {"verb": named, "old": old, "new": values[0],
                "evidence": {"text": text.strip(), "restated": heads[0]}}

    def _frame_reference_forms(self, parser, stem, every_form=False):
        """The reference forms of ``stem`` and of every verb read in its frame.

        A frame is the shape of the changes a declared example makes (a
        transfer changes a giver and a taker by one amount): every example verb
        of the same shape, and every verb the pack reads as one of them
        (같은틀 ``same_frame``, 역할바꿈 ``role_swaps``), names the same kind of
        event -- ``the one Haru handed`` a transfer stated with ``received``.
        """
        shapes = {}
        for example in parser.data.get("examples", []):
            verb = example.get("event_verb") or (example.get("inflection") or {}).get("stem")
            meaning = example.get("meaning") or {}
            rows = meaning.get("triples") or ([meaning["triple"]] if "triple" in meaning else [])
            if verb and rows:
                shapes.setdefault(verb, set()).add(tuple(sorted(str(row[1]) for row in rows
                                                                if isinstance(row, list) and len(row) == 3)))
        klass = {verb for verb, shape in shapes.items() if shape & shapes.get(stem, set())} | {stem}
        forms = {verb: self._reference_forms(parser, verb) | {verb} for verb in klass}
        for row in list(getattr(parser, "same_frame", []) or []) + list(getattr(parser, "role_swaps", []) or []):
            target = row.get("as") or row.get("read_as")
            if any(target == verb or target in shown for verb, shown in forms.items()):
                for other in row.get("stems") or [row.get("stem")]:
                    if other and other not in forms:
                        forms[other] = self._reference_forms(parser, other) | {other}
        if every_form:
            # A restated event is said again as a statement (``1개를 줬어``,
            # ``Ada gave Bo 1``): every form the inflection grammar computes.
            grammar = parser.inflection_grammar or {}
            for verb in list(forms):
                for tense in grammar.get("tenses", {}):
                    for ending in grammar.get("endings", {}):
                        for kind in grammar.get("kinds", []):
                            try:
                                forms[verb] |= set(parser._inflected_forms(verb, tense, ending, kind))
                            except (ValueError, KeyError):
                                continue
        return set().union(*forms.values())

    def _reference_forms(self, parser, stem):
        """The forms by which the pack says a past event is referred back to."""
        spec = parser.data.get("event_reference", {})
        grammar = parser.inflection_grammar
        forms = set()
        for tense in spec.get("tenses", []):
            for ending in spec.get("endings", []):
                for kind in grammar.get("kinds", []):
                    try:
                        forms.update(parser._inflected_forms(stem, tense, ending, kind))
                    except ValueError:
                        continue
        return forms

    @staticmethod
    def _declared_stem(parser, clause):
        """The verb stem the matched rule declares, for a clause read without inflection."""
        matched = {}
        parser._clause_meanings(clause, matched=matched)
        stems = {(parser.data["examples"][index].get("inflection") or {}).get("stem")
                 or parser.data["examples"][index].get("event_verb") for index in matched.values()}
        stems.discard(None)
        return stems.pop() if len(stems) == 1 else None

    def _correct_by_reference(self, parser, request, text, knowledge_path, only=None):
        """``아까 준 건 두 개가 아니라 한 개야``: fix the value of one earlier event.

        The event is found by the declared reference form of its verb and by
        the old value it carried; the same observation is corrected in place
        and everything after it is replayed. No new transfer is executed.
        Nothing is picked when zero or several events fit.
        """
        from marco.language.numerals import parse_numeral
        replies = parser.data["context_replies"]
        numerals = parser.data.get("numerals", {})
        updates = parser.data.get("numeric_updates", {})
        said = request["evidence"]["text"]
        verbs = self._verbs_for(parser, self.observations)
        candidates = []
        # A contrast names no verb: any stated count or change that carried the
        # old value is a candidate, and more than one is asked back.
        counted = set(updates) | {spec.get("target") for spec in updates.values() if isinstance(spec, dict)}
        for index, source in enumerate(self.observations):
            parsed = self._read_source(parser, source, events=True, verbs=verbs) or {}
            for fact in parsed.get("facts", []):
                if request["verb"] is None:
                    if fact["triple"][1] in counted and fact["triple"][2] == request["old"]:
                        if index not in candidates:
                            candidates.append(index)
                    continue
                stem = ((fact["evidence"].get("normalization") or {}).get("stem") or fact.get("verb")
                        or self._declared_stem(parser, fact["evidence"]["text"]))
                if (stem and fact["triple"][1] in updates and fact["triple"][2] == request["old"]
                        and request["verb"] in self._frame_reference_forms(
                            parser, stem, every_form="restated" in request["evidence"])):
                    if index not in candidates:
                        candidates.append(index)
        # Which declared reading named the event: a verb's reference form, a
        # contrast of two amounts, or a restatement head (request G1-2).
        if only is not None:
            # the one event a correction frame chose (effort 2)
            candidates = [index for index in candidates if index == only]
        by = ("contrast" if "contrast" in request["evidence"] else
              "restatement" if "restated" in request["evidence"] else "reference")

        def reply(key, fields=None, **values):
            # The user said an earlier statement was wrong and it could not be
            # applied: the values that statement touched are not fixed any more.
            # Questions on them hold until a later statement pins them again.
            # Named by the holders the statements were read as (the leading word
            # of each subject), so a question naming a holder bare (``보라는 몇
            # 개야``) is held too (G3.0 b), and a holder the statements did not
            # name is not held merely for sharing the item word.
            touched = set()
            for i in candidates:
                read = self._read_source(parser, self.observations[i], events=True, verbs=verbs) or {}
                for fact in read.get("facts", []):
                    subject = (fact.get("triple") or [None])[0]
                    if isinstance(subject, str) and subject.split():
                        touched.add(subject.split()[0])
            touched = sorted(touched or {word for i in candidates for word in self.observations[i].split()})
            self._remember_unread({"text": said, "at": len(self.observations),
                                   **({"대상": touched} if candidates else {})})
            return {"operator": "relational_graph", "status": "unresolved", "transitions": [],
                    "answer": replies[key].format(**values),
                    "meaning": {"act": "hold", "reason": key, "said": said, "by": by, **(fields or {})},
                    "verification": self._verification(knowledge_path, [{
                        "ok": False, "reason": "event_reference_" + key}])}
        if not candidates and only is None and self._effort_allows(2):
            # the declared contrast found no event carrying its old amount: the correction frame may (the one,
            # a direction said the other way round)
            framed = self._correction_frame(parser, text, knowledge_path)
            if framed is not None and (framed.get("status") == "observed"
                                       or (framed.get("meaning") or {}).get("reason") == "unread_event"):
                return framed           # corrected, or held naming the unread statement it corrects
        if not candidates:
            return reply("reference_no_event", 말=said)

        def carries_old(sentence):
            for word in sentence.split():
                core = word.strip(".,!?")
                digits = re.match(r"\d+", core)
                if parse_numeral(core, numerals) == request["old"] or (digits and str(int(digits.group())) == request["old"]):
                    return True
            return False
        # A statement said after every candidate that carried the old amount but was left unread may be the
        # one the user means: asked back with it, never an older statement corrected in its place (G5 safety).
        later = [entry["text"] for entry in self.unread_guard + self.unread
                 if entry.get("대상") is None and not entry.get("범용") and entry["at"] > candidates[-1]
                 and entry["text"] != said and carries_old(entry["text"])]
        if later:
            items = [self.observations[i].strip() for i in candidates] + [text.strip() for text in later]
            return reply("reference_which_event", {"items": items}, 말=said,
                         목록=", ".join('"%s"' % item for item in items))
        if len(candidates) > 1 and request["verb"] is None and candidates[-1] == len(self.observations) - 1:
            # A contrast right after an event that carried the old amount, where every statement that
            # carried it was an event, corrects the latest one: the narrative's latest change is what "it"
            # was. Where a stated count also carried it, the contrast is asked back (G3.0 b).
            def is_event(index):
                read = self._read_source(parser, self.observations[index], events=True, verbs=verbs) or {}
                rows = [fact for fact in read.get("facts", []) if fact["triple"][2] == request["old"]]
                return bool(rows) and all(fact["triple"][1] in updates for fact in rows)
            if all(is_event(index) for index in candidates):
                candidates = candidates[-1:]
        if len(candidates) > 1:
            return reply("reference_which_event",
                         {"items": [self.observations[i].strip() for i in candidates]}, 말=said,
                         목록=", ".join('"%s"' % self.observations[i].strip() for i in candidates))
        index = candidates[0]
        source = self.observations[index]
        tokens = source.split(" ")
        # Replace the typed numeral of the old value by the typed numeral of
        # the new one. Both surfaces were typed; nothing is invented.
        def numeral_positions(words, value):
            found = []
            for position, word in enumerate(words):
                core = word.strip(".,!?")
                digits = re.match(r"\d+", core)
                if parse_numeral(core, numerals) == value or (digits and digits.group() == core.rstrip()
                                                               and str(int(digits.group())) == value):
                    found.append(position)
                elif digits and str(int(digits.group())) == value:
                    found.append(position)
            return found
        positions = numeral_positions(tokens, request["old"])
        if len(positions) != 1:
            return reply("reference_value_unclear", {"event": source.strip(), "old": request["old"]},
                         사건=source.strip(), 전=request["old"])
        said_words = said.split(" ")
        # The new amount as typed, and only the amount: a counter or an ending
        # written onto its digits (``3마리이다``) is not carried into the event.
        typed_new = [re.match(r"\d+", word).group() if re.match(r"\d+", word) else word
                     for word in (said_words[i].strip(".,!?")
                                  for i in numeral_positions(said_words, request["new"]))]
        old_word = tokens[positions[0]]
        digits = re.match(r"\d+", old_word)
        if digits and digits.group() != old_word.strip(".,!?"):
            new_word = request["new"] + old_word[digits.end():]
        else:
            trailing = old_word[len(old_word.rstrip(".,!?")):]
            new_word = (typed_new[0] if len(typed_new) == 1 else request["new"]) + trailing
        replacement = " ".join(tokens[:positions[0]] + [new_word] + tokens[positions[0] + 1:])
        # A thing counted as one is written in the singular; the new amount
        # takes the plural the pack declares (``one plum`` -> ``two plums``).
        agreed = self._agree_number(parser, tokens, positions[0], request["old"], new_word)
        corrected = None

        def shape(sentence):
            read = self._read_source(parser, sentence, events=True, verbs=verbs) or {}
            return self._node_rows(parser, read.get("facts", []))
        # The corrected statement must read as the same facts with the amount
        # changed and nothing else: a rewrite that drops, adds or reshapes an
        # event is not the correction the user asked for (G3.4).
        expected = sorted((s, p, str(request["new"]) if v == str(request["old"]) else v) for s, p, v in shape(source))
        record = self._active_record(source) or {}
        for attempt in [replacement] + ([agreed] if agreed and agreed != replacement else []):
            if shape(attempt) != expected:
                continue
            carried = None
            if record.get("reason") in _readings.CARRIED_REASONS and record.get("parsed") is not None:
                # the statement was read by a reading kept for it (its thing through the thing node): the corrected
                # statement is read the same way, with only the amount changed (step 3)
                carried = self._reading_rewritten(
                    deepcopy(record["parsed"]), source, attempt, request["old"], request["new"], updates)
            try:
                corrected = self.correct(index, attempt, knowledge_path, reading=carried)
                break
            except ValueError:
                continue
        if corrected is None:
            return reply("reference_value_unclear", {"event": source.strip(), "old": request["old"]},
                         사건=source.strip(), 전=request["old"])
        record = self.corrections[-1]
        record.update({"utterance": text.strip(), "reference": {
            "verb": request["verb"], "old": request["old"], "new": request["new"]}})
        changes = [row for row in corrected["transitions"] if row.get("operation") == "quantity_update"
                   and (row.get("evidence") or {}).get("turn", index) == index]
        self.last_explanation = {"kind": "correction", "correction": deepcopy(record),
                                 "transitions": deepcopy(corrected["transitions"])}
        # 고친 사건에 둘 이상이 걸리면 뒤의 지시어가 누구를 가리키는지 정해지지 않는다.
        touched = sorted({self._person_of(row.get("subject", "")) for row in changes if row.get("subject")})
        self.last_subject = touched[0] if len(touched) == 1 else None
        self.last_mentioned = touched
        self.salient += [person for person in touched if person not in self.salient]
        return {**corrected, "status": "observed",
                "meaning": {"act": "correct", "event": source.strip(), "old": request["old"],
                            "new": request["new"], "new_event": False, "by": by, "changes": deepcopy(changes)},
                "answer": replies["reference_corrected"].format(**{
                    "사건": source.strip(), "전": request["old"], "후": request["new"],
                    "목록": parser.render_changes(changes)})}

    def _node_rows(self, parser, facts):
        """A reading's facts as (key, predicate, value) rows, each key the one the replay counts its holder node and
        thing node under (step 3): a statement read again after a correction says the same event whatever words
        it keeps for the thing (Ivo bags, for Ivo bags of flour). A key that names no holder and thing node of
        this conversation is kept as said."""
        graph = self.conversation_graph()
        keys = sorted(dict.fromkeys(self._holder_keys(parser)), key=lambda k: -len(k.split()))
        rows = []
        for fact in facts:
            subject, predicate, value = (str(part) for part in fact["triple"])
            pair = graph.of_key(subject)
            if pair is None:
                holder = next((k for k in keys if subject == k or subject.startswith(k + " ")), None)
                node = holder and (graph.id_of("holder", holder) or graph.id_of("place", holder))
                rest = subject[len(holder):].strip() if holder else ""
                things = self._graph_nodes(parser, graph, rest, None, ("thing",)) if rest else []
                if node and (not rest or len(things) == 1):
                    pair = (node, things[0] if rest else None)
            rows.append((graph.key(*pair) if pair else subject, predicate, value))
        return sorted(rows)

    @staticmethod
    def _reading_rewritten(reading, source, attempt, old, new, updates):
        """A kept reading of ``source`` as the reading of its rewrite ``attempt`` (one amount changed): the amount
        is the new one, and every piece of evidence is the rewrite's own words over the same span, never the
        withdrawn wording of the statement it replaces."""
        reading = deepcopy(reading)
        source, attempt = str(source), str(attempt)
        at = next((i for i, (x, y) in enumerate(zip(source, attempt)) if x != y), min(len(source), len(attempt)))
        delta = len(attempt) - len(source)
        # the word the rewrite changed, as typed in each (3 -> 4), for the evidence's normalised wording too
        pairs = [(x, y) for x, y in zip(source.split(), attempt.split()) if x != y]
        was, now = (pairs[0][0].strip(",.!?"), pairs[0][1].strip(",.!?")) if len(pairs) == 1 else (None, None)

        def moved(evidence):
            if not isinstance(evidence, dict):
                return evidence
            evidence = dict(evidence)
            start, end = evidence.get("start"), evidence.get("end")
            if isinstance(start, int) and isinstance(end, int):
                start, end = (start + delta if start > at else start), (end + delta if end > at else end)
                evidence.update(start=start, end=end, text=attempt[start:end])
            elif evidence.get("text") == source.strip():
                evidence["text"] = attempt.strip()
            if evidence.get("source") == source:
                evidence["source"] = attempt
            norm = evidence.get("normalization")
            if was and isinstance(norm, dict) and isinstance(norm.get("canonical"), str):
                evidence["normalization"] = dict(norm, canonical=re.sub(
                    r"(?<!\w)%s(?!\w)" % re.escape(was), now, norm["canonical"], count=1))
            return evidence
        for key, rows in reading.items():
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if key == "facts" and str(row["triple"][2]) == str(old) and row["triple"][1] in updates:
                    row["triple"][2] = type(row["triple"][2])(new)
                if "evidence" in row:
                    row["evidence"] = moved(row["evidence"])
        return reading

    def _correction_frame(self, parser, text, knowledge_path):
        """A correction no declared form reads (``No, three.``, ``Not two, three.``, ``Actually, it was three.``,
        ``No, Bo gave them to Nora, the other way around.``, ``아니, 보라가 노라한테 준 거야.``), at effort 2: a
        partial frame over the last events. The turn carries a correction word the pack declares
        (대조정정.frame.cues); its amounts and the holders it names are the slots it fills. Each of the last
        events is a candidate for each slot: its amount changed to the one said (the other amount said, if
        any, must be the event's own), or, for a transfer whose giver and receiver the turn names both, the two
        swapped. A candidate must read as the same event with only that slot changed and replay with no
        broken constraint; survivors are ranked (state, reasoning, grammar, context: the later event first),
        a clear win is corrected in place, a tie asks which event, none leaves the turn unread."""
        spec = (parser.language_pack.get("contrast_correction") or {}).get("frame") or {}
        if not self._effort_allows(2) or not spec or not self.observations:
            return None
        fold = (lambda v: v.lower()) if parser.data.get("ignore_case") else (lambda v: v)
        said = text.strip()
        flat = " %s " % " ".join(re.split(r"[\s,.!?]+", fold(said))).strip()
        if not any(" %s " % fold(cue) in flat for cue in spec.get("cues", [])):
            return None
        # every sentence of it states nothing else (an unread statement with a correction word is not a
        # correction); a sentence that reads as the transfer said the other way round is the correction itself
        keys = list(dict.fromkeys(self._holder_keys(parser)))  # (a key listed twice is one)
        verbs_known = self._verbs_for(parser, self.observations)
        restated = []
        for piece, asking in self._segments(said, parser):
            try:
                partial = parser.parse(piece, partial=True, events=True, verbs=verbs_known) or {}
            except Exception:    # noqa: BLE001
                partial = {}
            if asking or partial.get("query"):
                return None
            if partial.get("facts"):
                restated.append(partial["facts"])
        swap_word = any(" %s " % fold(w) in flat for w in spec.get("swap_words", []))
        # "the one", "that one" name someone, not the amount one
        counted_words = " %s " % " ".join(re.split(r"[\s,.!?]+", said))
        for phrase in sorted(spec.get("pronoun_ones", []), key=len, reverse=True):
            counted_words = re.sub(r"(?i)(?<=\s)%s(?=\s)" % re.escape(phrase), " ", counted_words)
        words = [w for w in counted_words.split() if w]
        amounts = [str(v) for v in (self._amount_of(parser, w) for w in words) if v is not None]
        # the amount a negation marks is the old one (not five; 다섯 개가 아니라): read from the words as said
        spoken = words
        negated = None
        for at, word in enumerate(spoken):
            value = self._amount_of(parser, word)
            if value is None:
                continue
            after = spoken[at + 1:at + 3]
            before = spoken[max(0, at - 1):at]
            # where the negation stands is the pack's: after the amount where the new side comes after the
            # contrast (다섯 개가 아니라 두 개), before it where the new side comes first (two, not five)
            if spec.get("new_after"):
                marks_it = any(parser._protected_kind(w) == "negation" or any(
                    fold(w).startswith(fold(c)) for c in spec.get("new_after", [])) for w in after)
            else:
                marks_it = any(parser._protected_kind(w) == "negation" and fold(w) not in
                               {fold(c) for c in spec.get("discourse_no", [])} for w in before)
            if marks_it:
                negated = str(value)
                break
        words = [w for w in re.split(r"[\s,.!?]+", said) if w]
        every_named = [k for k in (self._holder_of(parser, w, keys) for w in words) if k is not None]
        # the side of a contrast that says the new version (… 아니라 NEW; NEW, not …) names the holders in order
        side = said
        for cue in spec.get("new_after", []):
            if fold(cue) in fold(side):
                side = side[fold(side).rindex(fold(cue)) + len(cue):]
        for cue in spec.get("new_before", []):
            if fold(cue) in fold(side):
                side = side[:fold(side).index(fold(cue))]
        words = [w for w in re.split(r"[\s,.!?]+", side) if w and w.lower() not in ("",)] or words
        named = []
        for width in (3, 2, 1):
            for at in range(len(words) - width + 1):
                key = self._holder_of(parser, " ".join(words[at:at + width]), keys)
                if key is not None and key not in [k for k, _a in named] and not any(
                        a <= at < a + w for _k, a, w in [(k, a, len(k.split())) for k, a in named]):
                    named.append((key, at))
        named = [key for key, _at in sorted(named, key=lambda row: row[1])]
        # a verb said from the taker's side (got … from, 받았어) names the receiver first
        takers_first = any(fold(w).startswith(tuple(fold(v) for v in spec.get("taker_verbs", []))) for w in words)
        updates = parser.data.get("numeric_updates", {})
        counted = set(updates) | {s.get("target") for s in updates.values() if isinstance(s, dict)}
        adds = {n for n, s in updates.items() if isinstance(s, dict) and s.get("factor", 0) > 0}
        removes = {n for n, s in updates.items() if isinstance(s, dict) and s.get("factor", 0) < 0}
        verbs = self._verbs_for(parser, self.observations)

        def rows_of(sentence):
            read = self._read_source(parser, sentence, events=True, verbs=verbs) or {}
            return self._node_rows(parser, read.get("facts", []))

        def holder(subject):
            return next((k for k in sorted(keys, key=lambda k: -len(k.split())) if subject == k
                         or subject.startswith(k + " ")), subject.split()[0])

        def replays(index, sentence):
            try:
                self._replay(parser, self.observations[:index] + [sentence] + self.observations[index + 1:], self.fills,
                             projection=getattr(self.model, "language_projection", None))
                return True
            except ValueError:
                return False
        facts, _d, _p, _r = self._cached_replay(parser, self.observations, self.fills)
        all_things = {fold(str(r["triple"][0])[len(holder(str(r["triple"][0]))):].strip()) for r in facts
                      if isinstance(r.get("triple"), list) and isinstance(r["triple"][0], str)} - {""}
        typed = {fold(w) for w in re.split(r"[\s,.!?]+", said) if w}
        said_items = {t for t in all_things if t in typed or any(w.startswith(t) and len(w) - len(t) <= 2
                                                                for w in typed)}
        recent = [i for i in range(len(self.observations) - 1, -1, -1)
                  if any(p in counted for _s, p, _v in rows_of(self.observations[i]))]
        # an old amount said names its event wherever it is; otherwise only the last events are in reach
        stated_old = len(amounts) >= 2
        recent = recent if stated_old else recent[:int(spec.get("reach", 3))]
        candidates = []
        for distance, index in enumerate(recent):
            source = self.observations[index]
            rows = rows_of(source)
            values = {v for _s, p, v in rows if p in counted}
            givers = [holder(s) for s, p, _v in rows if p in removes]
            takers = [holder(s) for s, p, _v in rows if p in adds]
            involved = {holder(s) for s, _p, _v in rows}
            things = {s[len(holder(s)):].strip() for s, _p, _v in rows}
            if said_items and not said_items & {fold(t) for t in things}:
                self._candidate_dropped(2, "correction_frame", "event:%d" % index, "other_thing_named")
                continue
            context = len(recent) - distance
            # the giver and the receiver swapped: both named, in the other order or with a word that says so
            pair = list(dict.fromkeys(named + every_named))[:2]
            first = named[0] if named else None
            reversed_said = any(
                {holder(str(f["triple"][0])) for f in facts_ if f["triple"][1] in removes} == {takers[0]}
                and {holder(str(f["triple"][0])) for f in facts_ if f["triple"][1] in adds} == {givers[0]}
                for facts_ in restated) if len(givers) == 1 and len(takers) == 1 else False
            if restated and not reversed_said:
                continue
            # "the other way round" with no holder and no amount said: the event's own two are the pair (effort 2)
            unnamed = swap_word and not every_named and not amounts
            if len(givers) == 1 and len(takers) == 1 and (set(pair) == {givers[0], takers[0]} or unnamed) \
                    and (swap_word or reversed_said or (first == takers[0] and not takers_first)
                         or (first == givers[0] and takers_first)) and len(set(amounts) - values) == 0:
                tokens = source.split()
                a = self._frame_span(parser, tokens, givers[0], "holder")
                b = self._frame_span(parser, tokens, takers[0], "holder")
                if a and b and (a[1] <= b[0] or b[1] <= a[0]):
                    first, second = (a, b) if a[0] < b[0] else (b, a)

                    def said_as(span, particle):
                        body = " ".join(tokens[span[0]:span[1]])
                        stem = body[:len(body) - len(span[2])] if span[2] else body
                        stem = stem.rstrip(",.?!")
                        if not particle:
                            return stem
                        tail = stem.split()[-1]
                        return stem + (parser._particle_form(tail, particle) if particle in parser.particle_mates
                                       else particle)
                    closing = lambda span: tokens[span[1] - 1][len(tokens[span[1] - 1].rstrip(",.?!")):]
                    swapped = (tokens[:first[0]] + [said_as(second, first[2]) + closing(first)]
                               + tokens[first[1]:second[0]] + [said_as(first, second[2]) + closing(second)]
                               + tokens[second[1]:])
                    rewritten = " ".join(swapped)
                    flip = {givers[0]: takers[0], takers[0]: givers[0]}
                    expected = sorted((s.replace(holder(s), flip.get(holder(s), holder(s)), 1), p, v) for s, p, v in rows)
                    label = "swap:%d" % index
                    if rows_of(rewritten) != expected:
                        self._candidate_dropped(2, "correction_frame", label, "not_the_same_event")
                    elif not replays(index, rewritten):
                        self._candidate_dropped(2, "correction_frame", label, "replay_refused")
                    else:
                        candidates.append({"label": label, "index": index, "rewritten": rewritten, "slot": "direction",
                                           "fit": {"state": 1, "reasoning": 1, "grammar": 1, "context": context}})
                continue
            # the amount changed: the one amount said that the event does not carry
            if not amounts or len(values) != 1 or any(k not in involved for k in named):
                continue
            old = next(iter(values))
            if negated is not None and negated != old:
                # the negated amount is the old one; an event that does not carry it is not the one corrected
                self._candidate_dropped(2, "correction_frame", "amount:%d" % index, "negated_amount_not_carried")
                continue
            news = [v for v in amounts if v != old]
            if len(set(news)) != 1 or len(amounts) - len(news) > 1:
                continue
            if len(amounts) == len(news) and distance > 0 and not said_items:
                # an amount said with no old one and no thing corrects only the event said just before
                self._candidate_dropped(2, "correction_frame", "amount:%d" % index, "not_the_last_event")
                continue
            new = news[0]
            label = "amount:%d" % index
            tokens = source.split()
            at = [i for i, w in enumerate(tokens) if self._amount_of(parser, w.strip(",.!?")) is not None
                  and str(self._amount_of(parser, w.strip(",.!?"))) == old]
            if len(at) != 1:
                self._candidate_dropped(2, "correction_frame", label, "amount_not_typed_once")
                continue
            word = tokens[at[0]]
            digits = re.match(r"\d+", word)
            new_word = (new + word[digits.end():]) if digits else new + word[len(word.rstrip(",.!?")):]
            rewritten = " ".join(tokens[:at[0]] + [new_word] + tokens[at[0] + 1:])
            agreed = self._agree_number(parser, tokens, at[0], old, new_word)
            expected = sorted((s, p, new if v == old else v) for s, p, v in rows)
            fits = [r for r in [rewritten] + ([agreed] if agreed and agreed != rewritten else [])
                    if rows_of(r) == expected]
            if not fits:
                self._candidate_dropped(2, "correction_frame", label, "not_the_same_event")
            elif not replays(index, fits[0]):
                self._candidate_dropped(2, "correction_frame", label, "replay_refused")
            else:
                # with the old amount said, two events that carried it are a tie (asked), never the later one
                candidates.append({"label": label, "index": index, "old": old, "new": new, "slot": "amount",
                                   "fit": {"state": 1, "reasoning": int(len(amounts) - len(news) == 1),
                                           "grammar": 1, "context": 0 if stated_old else context}})
        if not candidates and amounts:
            # the statement corrected was kept unread (its numbers did not add up, or it was not read): it is said
            # again with the new amount, and taken if it now reads and replays
            for entry in reversed((self.unread_guard + self.unread)[-3:]):
                source = entry["text"]
                tokens = source.split()
                spots = [i for i, w in enumerate(tokens) if self._amount_of(parser, w.strip(",.!?")) is not None]
                carried = [str(self._amount_of(parser, tokens[i].strip(",.!?"))) for i in spots]
                if negated is not None:
                    old = negated
                elif len(set(amounts)) == 2:
                    olds = [a for a in dict.fromkeys(amounts) if a in carried]
                    old = olds[0] if len(olds) == 1 else None
                else:
                    last_said = entry.get("at") == len(self.observations)
                    old = carried[0] if last_said and len(carried) == 1 else None
                news = [a for a in dict.fromkeys(amounts) if a != old]
                label = "unread:%s" % source[:40]
                if old is None or carried.count(old) != 1 or len(news) != 1:
                    self._candidate_dropped(2, "correction_frame", label, "amount_not_carried_once")
                    continue
                spot = spots[carried.index(old)]
                word = tokens[spot]
                digits = re.match(r"\d+", word)
                new_word = (news[0] + word[digits.end():]) if digits else news[0] + word[len(word.rstrip(",.!?")):]
                if not digits and not word.rstrip(",.!?").isalpha():
                    # a numeral written with its counter (다섯 개가 / 5개를): the counter stays
                    unit = next((u for u in sorted((parser.counters or {}).get("units", []), key=len, reverse=True)
                                 if u in word and word.index(u) > 0), None)
                    new_word = (news[0] + word[word.index(unit):]) if unit else new_word
                rewritten = " ".join(tokens[:spot] + [new_word] + tokens[spot + 1:])
                try:
                    reread = parser.parse(rewritten, partial=True, events=True, verbs=verbs_known, repair=True) or {}
                except Exception:    # noqa: BLE001
                    reread = {}
                if not reread.get("facts"):
                    self._candidate_dropped(2, "correction_frame", label, "still_not_read")
                    continue
                if not replays(len(self.observations), rewritten):
                    self._candidate_dropped(2, "correction_frame", label, "replay_refused")
                    continue
                candidates.append({"label": label, "slot": "unread_amount", "entry": entry, "rewritten": rewritten,
                                   "old": old, "new": news[0],
                                   "fit": {"state": 1, "reasoning": int(negated is not None or len(set(amounts)) == 2),
                                           "grammar": 1, "context": 0}})
        winner, deciding, ranking = self._rank_candidates(candidates, kind="correction_frame")
        replies = parser.data["context_replies"]
        if winner is None and deciding == "tie":
            items = [self.observations[c["index"]].strip() for c in ranking[:2]]
            # the correction is said and not applied: what the events it may mean count is not known until it
            # is settled, so their holders are held as an unapplied correction (as _correct_by_reference's asks)
            graph = self.conversation_graph()
            touched = set()
            for c in candidates:
                for subject, _p, _v in rows_of(self.observations[c["index"]]) if "index" in c else []:
                    pair = graph.of_key(subject)
                    # the holder node's words (a question may name the holder bare), else the key's leading word
                    touched.update(graph.nodes[pair[0]]["name"].split() if pair else subject.split()[:1])
            touched = sorted(touched)
            if touched:
                self._remember_unread({"text": said, "at": len(self.observations), "대상": touched})
            return {"operator": "relational_graph", "status": "unresolved", "transitions": [],
                    "answer": replies["reference_which_event"].format(
                        말=said, 목록=", ".join('"%s"' % item for item in items)),
                    "meaning": {"act": "hold", "reason": "reference_which_event", "said": said, "by": "contrast",
                                "items": items},
                    "verification": self._verification(knowledge_path, [{"ok": False, "reason": "correction_tie"}])}
        if winner is None:
            return None
        if winner["slot"] == "unread_amount":
            # the statement corrected was never recorded: recording it now would add an event at this turn, which a
            # correction never does; the correction is held naming the statement it waits on (the statement as it
            # would read corrected is kept with it, for the trace)
            entry = winner["entry"]
            entry.setdefault("corrections", []).append({"said": said, "old": winner["old"], "new": winner["new"],
                                                         "reads_as": winner["rewritten"]})
            return {"operator": "relational_graph", "status": "unresolved", "transitions": [],
                    "answer": replies["unread_event"].format(**{"말": entry["text"]}),
                    "meaning": {"act": "hold", "reason": "unread_event", "said": entry["text"]},
                    "verification": self._verification(knowledge_path, [{
                        "ok": False, "reason": "correction_of_unread_statement"}])}
        if winner["slot"] == "amount":
            return self._correct_by_reference(parser, {"verb": None, "old": winner["old"], "new": winner["new"],
                                                       "evidence": {"text": said, "contrast": "frame"}},
                                              text, knowledge_path, only=winner["index"])
        index, source = winner["index"], self.observations[winner["index"]]
        try:
            corrected = self.correct(index, winner["rewritten"], knowledge_path)
        except ValueError:
            return None
        record = self.corrections[-1]
        record.update({"utterance": said, "reference": {"field": "direction"}})
        changes = [row for row in corrected["transitions"] if row.get("operation") == "quantity_update"
                   and (row.get("evidence") or {}).get("turn", index) == index]
        self.last_explanation = {"kind": "correction", "correction": deepcopy(record),
                                 "transitions": deepcopy(corrected["transitions"])}
        touched = sorted({self._person_of(row.get("subject", "")) for row in changes if row.get("subject")})
        self.last_subject = None
        self.last_mentioned = touched
        self.salient += [person for person in touched if person not in self.salient]
        return {**corrected, "status": "observed",
                "meaning": {**corrected["meaning"], "field": "direction", "event": source.strip()}}

    @staticmethod
    def _declared_words(parser):
        """The words a count question may say besides its holders and things: every word the pack declares
        for questions (the question frame, the count question, the name reply and its follow-ups, the phrases
        read as nothing, the question forms of the count predicates), folded."""
        cached = getattr(parser, "_question_word_cache", None)
        if cached is not None:
            return cached
        fold = (lambda v: v.lower()) if parser.data.get("ignore_case") else (lambda v: v)
        found = set()

        def walk(value):
            if isinstance(value, str):
                found.update(fold(w) for w in value.split())
            elif isinstance(value, dict):
                for key, inner in value.items():
                    if key not in ("render", "predicates"):
                        walk(inner)
            elif isinstance(value, list):
                for inner in value:
                    walk(inner)
        walk(parser.count_question or {})
        walk(parser.language_pack.get("name_reply") or {})
        walk([row.get("from") for row in parser.phrase_variants if row.get("to", None) == ""])
        found |= {fold(w) for w in parser._count_predicate_forms()}
        found |= {fold(w) for w in (parser.counters or {}).get("askers", [])}
        parser._question_word_cache = found
        return found

    def _count_render(self, parser, item):
        """How the pack says a count of ``item``: the count question's render, else the render of the pack's
        own count question example for a holder and a thing, its thing filled."""
        render = (parser.count_question or {}).get("render")
        if render:
            return list(render)
        for example in parser.data.get("examples", []):
            query = (example.get("meaning") or {}).get("query") or []
            row = query[0] if query and isinstance(query[0], dict) else {}
            if row.get("triple") == [["$owner", "$item"], "count", "?n"] and row.get("render"):
                return [item if part == "$item" else part for part in row["render"]]
        return ["$n"]

    def _ground_question(self, parser, text, knowledge_path):
        """A question the reader leaves unread, grounded against the conversation (G7-Q, partial readings,
        effort 2): the parser's partial reading gives each word and its kind; every word must be one the pack
        declares for questions, a holder or a thing of this conversation, or one name it never said. Open slots
        are filled by candidates: a holder named with no thing takes each thing that holder counts (ranked,
        the thing the last question asked first; a tie asks which); a name the conversation never said is a
        question about a holder with no count, held naming it. Anything else (a number, a negation, a word
        nobody declared) leaves the turn unread, as before. Returns a reading for the turn to go on with, a
        reply, or None."""
        if not self._effort_allows(2):
            return None
        read = parser.parse(text, partial=True, events=True, open_slots=True) or {}
        reading = read.get("partial")
        if not reading or not reading["question"] or reading["markers"] or reading["numbers"]:
            return None
        if not any(t["kind"] == "asker" for t in reading["tokens"]):
            return None
        fold = (lambda v: v.lower()) if parser.data.get("ignore_case") else (lambda v: v)
        declared = self._declared_words(parser)
        graph = self.conversation_graph()
        holders, named_things, unknown = [], [], []
        for token in reading["tokens"]:
            if token["kind"] in ("asker", "counter"):
                continue
            word, stem = token["text"], token["stem"]
            if parser._protected_kind(word) or parser._protected_kind(stem):
                # a scope word, a numeral or a negation the reader did not place: the round-2 guard holds it
                return None
            if fold(word) in declared or fold(stem) in declared:
                continue
            holder_nodes = self._graph_nodes(parser, graph, word, stem, ("holder", "place"))
            thing_nodes = self._graph_nodes(parser, graph, word, stem, ("thing",))
            if len(holder_nodes) > 1 or len(thing_nodes) > 1:
                return None             # one word naming two nodes: not read here
            if holder_nodes and graph.things_of(holder_nodes[0]):
                if holder_nodes[0] not in holders:
                    holders.append(holder_nodes[0])
            elif thing_nodes and graph.holders_of(thing_nodes[0]):
                if thing_nodes[0] not in named_things:
                    named_things.append(thing_nodes[0])
            elif token["kind"] == "name" or (word != stem and stem):
                unknown.append(parser.canonical_name(stem))
            else:
                self._candidate_dropped(2, "partial_question", word, "word_not_declared_or_known")
                return None
        if len(named_things) > 1 or len(holders) > 1 or len(unknown) > 1 or (holders and unknown):
            return None
        if unknown:
            # a holder the conversation never counted: asked as such, held naming it and the thing
            name = unknown[0]
            if named_things:
                return self._grounded_reading(parser, "%s %s" % (name, graph.nodes[named_things[0]]["name"]),
                                              graph.nodes[named_things[0]]["name"])
            return self._grounded_reading(parser, name, None)
        if not holders:
            return None
        holder = holders[0]
        if named_things:
            return self._grounded_reading(parser, graph.key(holder, named_things[0]),
                                          graph.nodes[named_things[0]]["name"])
        # the thing left open: each thing this holder counts is a candidate (the last question's thing first)
        before = (getattr(self, "_frame_before_turn", None) or self.last_frame or {}).get("item")
        before_node = graph.id_of("thing", before) if before else None
        candidates = [{"label": graph.key(holder, thing), "thing": graph.nodes[thing]["name"],
                       "fit": {"state": 1, "context": int(thing == before_node)}}
                      for thing in sorted(graph.things_of(holder), key=lambda t: graph.key(holder, t))]
        winner, deciding, ranking = self._rank_candidates(candidates, kind="partial_question")
        if winner is None and deciding == "tie":
            replies = parser.data.get("context_replies", {})
            names = [c["label"] for c in ranking]
            word = graph.nodes[holder]["name"]
            return {"operator": "relational_graph", "status": "unresolved", "transitions": [],
                    "meaning": {"act": "ask", "reason": "which_referent", "word": word, "candidates": names},
                    "answer": replies.get("which_referent", "").format(**{
                        "말": word, "목록": ", ".join("'%s'" % n for n in names)}),
                    "verification": self._verification(knowledge_path, [{"ok": False, "reason": "partial_tie"}])}
        if winner is None:
            return self._grounded_reading(parser, graph.nodes[holder]["name"], None)
        return self._grounded_reading(parser, winner["label"], winner["thing"])

    def _ground_lookup(self, parser, query, facts):
        """A count question read under a key the state does not count (G7-Q, effort 2; step 3 by node): the count
        edges it may name are the candidates -- the same holder and the thing by its other declared number (pen /
        pens), a holder whose name ends in the words asked (the shed for the red shed, 과장님 for 김 과장), a holder a
        statement named with the relation word asked (my uncle for My uncle Tom; the nurse for The nurse, Mia,), a
        holder asked alone or with its particle left on (its one thing, else the thing the question before asked),
        a holder and one declared word or a part of its one thing's name. Exactly one candidate is asked instead;
        two ask which, naming every one; none leaves the question as it was read."""
        rows = [q for q in query if isinstance(q, dict)]
        if not self._effort_allows(2) or len(rows) != 1 or not isinstance(rows[0].get("triple"), list):
            return query, None
        triple = rows[0]["triple"]
        if len(triple) != 3 or triple[1] != "count" or not isinstance(triple[0], str) or triple[0].startswith(("?", "$")):
            return query, None
        fold = (lambda v: v.lower()) if parser.data.get("ignore_case") else (lambda v: v)
        graph = self.conversation_graph()
        if graph.of_key(triple[0]) in graph.counts and graph.value(*graph.of_key(triple[0])) is not None:
            return query, None
        try:
            if parser.answer({"facts": facts, "query": query}) is not None:
                return query, None      # the question as read has its answer (a leading-word referent, …)
        except Exception:    # noqa: BLE001
            pass
        particles = self._frame_particles(parser)
        titles = [fold(t) for t in (parser.holder_forms or {}).get("name_titles", [])]

        def bare_of(text):
            for title in titles:
                if fold(text).endswith(title) and len(text) > len(title):
                    text = text[:-len(title)]
            return text

        def holders_named(text):
            nodes = self._graph_nodes(parser, graph, text, bare_of(text), ("holder", "place"), forms=("key", "title"))
            if not nodes and len(text.split()) == 1:
                # a holder word with its particle still on it (a one-syllable name before 은/는)
                stem = next((text[:-len(p)] for p in particles if text.endswith(p) and len(text) > len(p)), None)
                nodes = self._graph_nodes(parser, graph, stem, None, ("holder", "place"), forms=("key", "title")) \
                    if stem else []
            return nodes

        def counted(holder):
            return [t for t in graph.things_of(holder) if graph.value(holder, t) is not None]
        words = triple[0].split()
        alone = holders_named(triple[0])
        if len(alone) == 1:
            # a holder asked with no thing: the one thing it counts, else the thing the question before asked
            own = counted(alone[0])
            before = (getattr(self, "_frame_before_turn", None) or self.last_frame or {}).get("item")
            before_node = graph.id_of("thing", before) if before else None
            pick = own if len(own) == 1 else [t for t in own if t == before_node]
            if len(pick) == 1:
                return [dict(rows[0], triple=[graph.key(alone[0], pick[0]), "count", "?n"])], None
        if len(words) == 2:
            first = holders_named(words[0])
            if len(first) == 1:
                # a holder and one word that is no thing of the state: a word the pack declares (a title, a relation,
                # a word for "the thing(s)"), or a part of the holder's one thing, names that thing; any other noun
                # may be a thing never mentioned, and is left as asked
                own = counted(first[0])
                said = next((words[1][:-len(p)] for p in particles if words[1].endswith(p) and len(words[1]) > len(p)),
                            words[1])
                forms = parser.holder_forms or {}
                known = self._declared_words(parser) | {fold(w) for w in list(forms.get("job_titles", []))
                                                       + list(forms.get("name_titles", [])) + list(forms.get("role_titles", []))
                                                       + list(forms.get("relation_nouns", []))}
                is_thing = bool(self._graph_nodes(parser, graph, said, None, ("thing",)))
                if len(own) == 1 and not is_thing:
                    thing = graph.nodes[own[0]]["name"]
                    if fold(said) in known or fold(words[1]) in known or (
                            len(said) > 1 and (fold(thing).endswith(fold(said)) or fold(said).endswith(fold(thing)))):
                        return [dict(rows[0], triple=[graph.key(first[0], own[0]), "count", "?n"])], None
        found = {}
        for k in range(1, len(words)):
            asked_holder, asked_thing = " ".join(words[:k]), " ".join(words[k:])
            things = self._graph_nodes(parser, graph, asked_thing, None, ("thing",), forms=("key", "number"))
            if not things:
                continue
            bare = bare_of(asked_holder)
            named = set(holders_named(asked_holder))
            described = set(graph.find(bare, kinds=("holder", "place"), fold=fold, forms=("relation", "possessive")))
            for thing in things:
                for holder in graph.holders_of(thing):
                    if graph.value(holder, thing) is None:
                        continue
                    name = graph.nodes[holder]["name"]
                    if holder in named:
                        why = "number"
                    elif fold(name).endswith(" " + fold(bare)):
                        why = "part"
                    elif holder in described:
                        why = "relation"
                    else:
                        continue
                    found[graph.key(holder, thing)] = (why, asked_holder)
        winner, deciding, ranking = self._rank_candidates(
            [{"label": subject, "fit": {"state": 1}} for subject in sorted(found)], kind="lookup")
        if winner is None and deciding == "tie":
            # the words asked describe several holders the state counts: which one is asked back, naming every one
            return query, {"word": found[ranking[0]["label"]][1], "candidates": [c["label"] for c in ranking]}
        if winner is None:
            return query, None
        return [dict(rows[0], triple=[winner["label"], "count", "?n"])], None

    def _ask_which(self, parser, text, which, result):
        """Ask which of several holders a question's words mean (which_referent), keeping the question so the
        reply that names one fills it (the pointer is the holder's words as the question said them)."""
        tokens = text.strip().split()
        span = self._frame_span(parser, tokens, which["word"], "holder")
        said = " ".join(tokens[span[0]:span[1]]) if span else which["word"]
        if span and span[2]:
            said = said[:-len(span[2])] if said.endswith(span[2]) else said
        said = said.strip(",.?!")
        self.held_question = text
        self.pending_pointer = {"question": text.strip(), "pointer": said, "candidates": list(which["candidates"])}
        if which.get("item"):
            # the thing the ask is about, for the reply's question that names only the holder
            self.last_frame = {"text": text.strip(), "holders": [said], "item": which["item"]}
        replies = parser.data["context_replies"]
        return {**result, "status": "unresolved",
                "meaning": {"act": "ask", "reason": "which_referent", "word": said,
                            "candidates": list(which["candidates"])},
                "answer": replies["which_referent"].format(**{
                    "말": said, "목록": ", ".join("'%s'" % name for name in which["candidates"])})}

    def _which_person(self, parser, text, knowledge_path):
        """A count question that names no holder and no thing, the person pointed at or described instead
        (How many does her brother have now? / How many does the other one have? / 그 친구는 지금 몇 권이야?), at
        effort 2: the thing is the conversation's (the last question's, else the one thing it counts), the
        candidates are the holders of that thing, narrowed to those a statement said with the describing words
        right before them (My brother Tom). One described holder answers; two or more are asked back naming
        every one, the question kept for the reply; one holder nobody described leaves the question as it was.
        A name alone is not a description (How many does Zed have? is a question about Zed)."""
        if not self._effort_allows(2) or not self.observations:
            return None
        reading = parser.open_reading(text)
        tokens = reading["tokens"]
        fold = (lambda v: v.lower()) if parser.data.get("ignore_case") else (lambda v: v)
        # "the one", "the other one" point at someone; they are no amount
        ones = [fold(p) for p in ((parser.language_pack.get("contrast_correction") or {}).get("frame") or {})
                .get("pronoun_ones", [])]
        flat = " %s " % " ".join(fold(w) for w in re.split(r"[\s,.?!]+", text) if w)
        pronoun_one = any(" %s " % p in flat for p in ones)
        determiners = {fold(w) for w in (parser.holder_forms or {}).get("determiners", [])} | {
            fold(p.split()[0]) for p in ones if len(p.split()) > 1}
        spoken = [fold(w) for w in re.split(r"[\s,.?!]+", text) if w]
        # "one" with a determiner one or two words before it (the tall one) points at someone too
        pronoun_one = pronoun_one or any(w == fold("one") and set(spoken[max(0, i - 2):i]) & determiners
                                         for i, w in enumerate(spoken))
        numbers = [t for t in reading["numbers"] if not (pronoun_one and t["value"] == "1")]
        if not reading["question"] or numbers or reading["markers"] \
                or not any(t["kind"] == "asker" for t in tokens):
            return None
        if any(parser._protected_kind(t["text"]) in ("scope", "negation") for t in tokens):
            return None
        graph = self.conversation_graph()
        # the things counted with a value, and their holders, are nodes of the conversation (step 2)
        things = {thing for (_h, thing), edge in graph.counts.items() if thing and edge["value"] is not None}
        declared = self._declared_words(parser)
        forms = parser.holder_forms or {}
        cues = {fold(w) for w in list(forms.get("determiners", [])) + list(forms.get("possessives", []))
                + list(forms.get("relation_nouns", [])) + list(forms.get("job_titles", []))}
        # the words of the pack's pointers (that of that person, this of this one) point too
        cues |= {fold(w) for pointer in parser.pointers or [] for w in pointer.split()}
        pointers = sorted(parser.pointers or [], key=len, reverse=True)
        describing, pointed = [], False
        said_things = set()
        low = fold(text)
        for pointer in pointers:
            if re.search(r"(?<![\w])%s(?![\w])" % re.escape(fold(pointer)), low) or \
                    any(fold(t["text"]) == fold(pointer) or fold(t["stem"]) == fold(pointer) for t in tokens):
                pointed = True
                break
        for t in tokens:
            if t["kind"] in ("asker", "counter"):
                continue
            word, stem = fold(t["text"]), fold(t["stem"])
            if self._graph_nodes(parser, graph, t["text"], t["stem"], ("holder", "place"), forms=("key", "title")):
                return None             # a holder named: the readers' question, not this one
            named_thing = set(self._graph_nodes(parser, graph, t["text"], t["stem"], ("thing",))) & things
            if named_thing:
                # the thing named, the person only described: the thing is that node (one, or not this question)
                said_things |= named_thing
                continue
            if word in declared or stem in declared or (t["kind"] == "number" and pronoun_one):
                continue
            describing.append(t["stem"])
        cued = pointed or any(fold(w) in cues for w in re.split(r"[\s,.?!]+", text) if w)
        if not cued or len(describing) > 3:
            return None
        if len(said_things) > 1:
            return None
        before = (getattr(self, "_frame_before_turn", None) or self.last_frame or {}).get("item")
        thing = next(iter(said_things)) if said_things else (graph.id_of("thing", before) if before else None)
        if thing not in things:
            thing = next(iter(things)) if len(things) == 1 else None
        if thing is None:
            return None
        holders = [h for h in graph.holders_of(thing) if graph.value(h, thing) is not None]
        # a description narrows them to the holders a statement named with those words (a relation, a title)
        said_as = {node for word in describing for node in graph.find(
            word, kinds=("holder", "place"), fold=fold, forms=("relation", "title", "possessive"))}
        of_thing = sorted(graph.key(h, thing) for h in holders)
        described = sorted(graph.key(h, thing) for h in holders if h in said_as)
        thing = graph.nodes[thing]["name"]
        candidates = described or of_thing
        if len(candidates) == 1 and not described:
            return None
        if len(candidates) == 1:
            return self._grounded_reading(parser, candidates[0], thing)
        # the words that point or describe, as the question said them, are what the reply replaces
        words = text.strip().rstrip("?.!？ ").split()
        particles = self._frame_particles(parser)

        def stem_of(word):
            word = fold(word.strip(","))
            return next((word[:-len(p)] for p in particles if word.endswith(p) and len(word) > len(p)), word)
        span = [i for i, w in enumerate(words) if stem_of(w) in cues or fold(w.strip(",")) in cues or any(
            fold(w).startswith(fold(p)) for p in pointers) or any(fold(w).startswith(fold(d)) for d in describing)]
        if span:
            # the holder's words run from the first pointing word to the word that carries the holder's particle,
            # or to the verb of having
            having = {fold(w) for w in ((parser.count_question or {}).get("frame") or {}).get("predicates", [])}
            end = span[0]
            for i in range(span[0], len(words)):
                if fold(words[i]) in having:
                    break
                end = i
                if stem_of(words[i]) != fold(words[i].strip(",")):
                    break
            span = [span[0], end]
        said = " ".join(words[span[0]:span[-1] + 1]) if span else " ".join(describing)
        tail = next((p for p in self._frame_particles(parser) if said.endswith(p) and len(said) > len(p)), "")
        said = said[:-len(tail)] if tail else said
        return self._ask_which(parser, text, {"word": said, "candidates": candidates, "item": thing},
                               {"operator": "relational_graph", "transitions": [],
                                "verification": self._verification(knowledge_path, [{
                                    "ok": False, "reason": "which_person"}])})

    def _named_reply(self, parser, text, knowledge_path):
        """After an ask of which holder, a reply that names exactly one candidate with at most two other words
        that say nothing the pack protects (Tom, I think. / 수아 말이에요 아마.): read as that name (effort 2)."""
        if not self._effort_allows(2) or not self.pending_pointer:
            return None
        graph = self.conversation_graph()
        # the asked candidates as holder nodes, and the reply's words as nodes (step 2)
        asked = {(graph.of_key(c) or (graph.id_of("holder", c) or graph.id_of("place", c),))[0]
                 for c in self.pending_pointer.get("candidates") or []} - {None}
        words = [w for w in re.split(r"[\s,.!?]+", text) if w]
        # a word with a tail the name reply declares (이보요): the name is the word before it
        tails = sorted((t.strip() for t in (parser.language_pack.get("name_reply") or {}).get("tails", [])
                        if t.strip() and " " not in t.strip()), key=len, reverse=True)
        found = []
        for at, word in enumerate(words):
            bare = next((word[:-len(t)] for t in tails if word.endswith(t) and len(word) > len(t)), None)
            nodes = [n for n in self._graph_nodes(parser, graph, word, bare, ("holder", "place"), forms=("key", "title"))
                     if n in asked]
            if len(nodes) == 1:
                found.append((at, word, nodes[0]))
        if len({node for _a, _w, node in found}) != 1 or len(words) - 1 > 2:
            return None
        if any(parser._protected_kind(w) for w in words):
            return None
        return self._name_reply(parser, found[0][1], knowledge_path)

    def _ground_pair(self, parser, query, facts):
        """A total or a comparison over "the two" (How many do the two of them have? / Which of the two has more?
        / 둘 중 누가 더 많아?), at effort 2: the thing left unsaid is the one the question before asked; the two
        holders are the two the last questions named, else the two holders of that thing. Exactly two holders
        counting the thing, or the question is left as it was read."""
        rows = [q for q in query if isinstance(q, dict)]
        if not self._effort_allows(2) or len(rows) != 1:
            return query
        row = rows[0]
        kind = next((k for k in ("total", "more", "fewer", "same") if isinstance(row.get(k), dict)), None)
        if kind is None:
            return query
        spec = dict(row[kind])
        pair = kind != "total" and spec.get("pair")
        if not pair and not (kind == "total" and spec.get("members") in ("two", "all") and not spec.get("item")):
            return query
        recent = list(reversed(getattr(self, "_recent_before_turn", None) or []))
        # the thing: the question's own, else the one the latest question with a thing asked
        item = spec.get("item") or next((frame.get("item") for frame in recent if frame.get("item")), None)
        graph = self.conversation_graph()
        thing = graph.id_of("thing", item) if item else None
        if thing is None:
            return query
        # the holders of the thing, and the ones the last questions named, as nodes (step 2)
        counting = [h for h in graph.holders_of(thing) if graph.value(h, thing) is not None]
        holders_of = sorted(graph.nodes[h]["name"] for h in counting)
        named = []
        for frame in recent:
            for name in frame.get("holders") or []:
                node = graph.id_of("holder", name) or graph.id_of("place", name)
                if node in counting and name not in named:
                    named.append(name)
        if kind == "total":
            spec["item"] = item
            if spec.get("members") == "two":
                if len(named) >= 2 and len(holders_of) != 2:
                    spec["members"] = list(reversed(named[:2]))
                elif len(holders_of) != 2:
                    return query
            return [dict(row, **{kind: spec}, render=self._count_render(parser, item))]
        pair_of = named[:2] if len(named) >= 2 else (holders_of if len(holders_of) == 2 else [])
        winner, _deciding, _ranking = self._rank_candidates(
            [{"label": " / ".join(pair_of), "fit": {"state": 1}}] if len(pair_of) == 2 else [], kind="pair")
        if winner is None:
            return query
        spec.pop("pair", None)
        spec.update(a=pair_of[1] if named else pair_of[0], b=pair_of[0] if named else pair_of[1], item=item)
        return [dict(row, **{kind: spec})]

    def _grounded_reading(self, parser, subject, item):
        """A count question on ``subject`` as the reader would have read it, for the turn to go on with."""
        return {"facts": [], "query": [{"triple": [subject, "count", "?n"],
                                        "render": self._count_render(parser, item or "")}],
                "정의": [], "사건": [], "가정사건": [], "조건": [], "가정": [], "원인": [], "이유물음": [],
                "수선": [], "사건정정": [], "grounded": True}

    @staticmethod
    def _same_in_number(parser):
        """Two words are one when they are, or one is the other's plural by the pack's number rules (명사수): towel,
        towels."""
        from relational_semantics import declared_plural
        number = getattr(parser, "noun_number", None) or {}

        def same(a, b):
            a, b = a.lower(), b.lower()
            return a == b or (declared_plural(a, number) or "").lower() == b or (declared_plural(b, number) or "").lower() == a
        return same

    @staticmethod
    def _within(short, long, same=None):
        """Every word of ``short`` in ``long``, in order (``same`` says when two words are one)."""
        same = same or (lambda a, b: a == b)
        at = 0
        for word in long:
            if at < len(short) and same(word, short[at]):
                at += 1
        return at == len(short)

    @staticmethod
    def _unit_said(parser, text, after_asker=False):
        """The declared counter (수량단위.units) a clause says its amount in: the unit right after its first number
        (43묶음, 세 개를), written on to the number or as the next word; with ``after_asker`` the unit a question
        asks in (몇 묶음). None in a pack that declares no counters, or when no unit is said."""
        from marco.language.numerals import parse_numeral
        counters = (parser.language_pack or {}).get("counters") or {}
        units = sorted(counters.get("units") or [], key=len, reverse=True)
        if not units:
            return None
        askers = counters.get("askers") or []
        numerals = parser.data.get("numerals") or {}
        words = [w.strip(".,!?") for w in str(text).split()]

        def unit_of(word):
            return next((u for u in units if word.startswith(u)), None)
        for i, word in enumerate(words):
            if after_asker:
                asker = next((a for a in askers if word.startswith(a)), None)
                if asker is None:
                    continue
                rest = word[len(asker):]
            else:
                digits = len(word) - len(word.lstrip("0123456789"))
                if digits:
                    rest = word[digits:]
                elif parse_numeral(word, numerals) is not None:
                    rest = ""
                else:
                    continue
            if rest:
                return unit_of(rest)
            return unit_of(words[i + 1]) if i + 1 < len(words) else None
        return None

    @staticmethod
    def _unit_keys(parser, facts):
        """One thing counted in two units is two counts (G7-S): 노라는 깃펜이 43묶음 있어. 노라는 깃펜이 8개 있어. says
        43 bundles and 8 pieces, not 8 in place of 43. A count is not said in a unit until a second count of the
        same holder and thing is said in another declared unit; from then every count of that key is kept by its
        unit: the pack's first unit (개) under the key itself, another unit under the key with the unit after it
        (노라 깃펜 묶음: the thing 깃펜 묶음, its container), and a change said in one of those units goes to that
        count, with the other holders of the same statement (a transfer moves one thing). Nothing is converted
        between units. The pass runs over the facts in order on every replay path, and gives the same keys when
        run again (each fact keeps the key it was read with, ``unit_key``)."""
        counters = (parser.language_pack or {}).get("counters") or {}
        units = counters.get("units") or []
        if not units:
            return facts
        default = units[0]
        updates = parser.data.get("numeric_updates") or {}
        targets = ReasoningContext._numeric_targets(parser)

        def base(fact):
            return fact.get("unit_key") or fact["triple"][0]

        def unit(fact):
            if "unit" not in fact:
                fact["unit"] = ReasoningContext._unit_said(parser, (fact.get("evidence") or {}).get("text") or "")
            return fact["unit"]
        counted = [f for f in facts if isinstance(f.get("triple"), list) and isinstance(f["triple"][0], str)
                   and (f["triple"][1] in targets or f["triple"][1] in updates)]
        said = {}
        for fact in counted:
            if fact["triple"][1] in targets and unit(fact):
                seen = said.setdefault(base(fact), [])
                if unit(fact) not in seen:
                    seen.append(unit(fact))
        split = {key: seen for key, seen in said.items() if len(seen) > 1}
        if not split and not any("unit_key" in f for f in counted):
            return facts
        moved = {}                  # (turn, unit, thing) of a change that went to a unit's count
        for fact in counted:
            key, u = base(fact), unit(fact)
            fact["unit_key"] = key
            target = key if key not in split or not u or u == default or u not in split[key] and \
                fact["triple"][1] not in targets else "%s %s" % (key, u)
            if target != key and fact["triple"][1] in updates:
                moved[((fact.get("evidence") or {}).get("turn"), u, key.split()[-1])] = True
            fact["triple"][0] = target
        for fact in counted:
            key, u = fact["unit_key"], fact["unit"]
            if fact["triple"][0] == key and fact["triple"][1] in updates and u and u != default \
                    and moved.get(((fact.get("evidence") or {}).get("turn"), u, key.split()[-1])):
                fact["triple"][0] = "%s %s" % (key, u)      # the other holder of the same transfer
        for fact in counted:
            key = fact["unit_key"]
            parts = fact.get("parts") if isinstance(fact.get("parts"), dict) else None
            if fact["triple"][0] != key:
                if parts and parts.get("holder") and key.startswith(parts["holder"] + " "):
                    fact["parts"] = {"holder": parts["holder"], "thing": fact["triple"][0][len(parts["holder"]) + 1:]}
                else:
                    fact.pop("parts", None)
            elif parts and parts.get("thing") and key.startswith(parts.get("holder", "") + " ") \
                    and "key" not in parts:
                fact["parts"] = {"holder": parts["holder"], "thing": key[len(parts["holder"]) + 1:]}
        return facts

    @staticmethod
    def _unit_kinds_differ(parser, facts, turn):
        """``{"subject", "units": [said, changed]}`` when a change of the statement at ``turn`` is said in a unit of
        another kind than the unit its count was said in, else None. The pack declares the units that hold or
        group several pieces (수량단위.담는단위: 묶음, 상자, 병 ...); every other unit counts one piece (개, 자루, 권
        ...). A count said in one kind is not moved by a change said in the other (서류가 5묶음, then 2개를 줬어 was 3,
        bundles less pieces), nor between two different units that hold several (상자, 묶음). Units of one piece
        (다섯 자루, 두 개) are one count as before, and a count or a change said in no unit is not judged. A said
        count of none is said in no unit (한 개도 없어 is none in bundles too): the first change after it moves the
        count and sets its unit, and a later change in a unit of another kind is held against that. The
        declaration adds no reading; it only holds."""
        counters = (parser.language_pack or {}).get("counters") or {}
        holding = set(counters.get("containers") or [])
        if not holding:
            return None
        updates = parser.data.get("numeric_updates") or {}
        targets = ReasoningContext._numeric_targets(parser)
        said = {}
        ZERO = object()

        def unit(fact):
            return fact.get("unit") or ReasoningContext._unit_said(parser, (fact.get("evidence") or {}).get("text") or "")
        def none(value):
            try:
                return float(value) == 0
            except (TypeError, ValueError):
                return False
        for fact in facts:
            triple = fact.get("triple")
            if not isinstance(triple, list) or not isinstance(triple[0], str):
                continue
            if triple[1] in targets:
                # a said count of none is none in every unit (한 개도 없어): it carries no unit, and the first
                # change after it sets the unit
                said[triple[0]] = ZERO if none(triple[2]) else unit(fact)
            elif triple[1] in updates:
                key = triple[0] if triple[0] in said else next(
                    iter([k for k in said if k.startswith(triple[0] + " ")][:1] if len(
                        [k for k in said if k.startswith(triple[0] + " ")]) == 1 else []), None)
                before, now = said.get(key), unit(fact)
                if before is ZERO:
                    said[key] = now
                elif (fact.get("evidence") or {}).get("turn") == turn and before and now and before != now \
                        and (before in holding or now in holding):
                    return {"subject": key, "units": [before, now]}
        return None

    def _holder_unsaid(self, parser, text, parsed):
        """A reading that changes a count whose holder it does not say, where the statement has a phrase in the
        subject or giver place that the reading did not take for that holder (``_subject_passed_over``): the
        reading of 기 대표님이 세훈에게 세 개를 줬어 that takes 기 대표 세훈 for the receiver. The replay would give the
        change to the conversation's one counted holder, a person the statement passes over for the one it names
        (가람 연필 7 -> 4, and the reply said 가람 gave them). Such a reading is no reading of a new statement, at any
        effort: the statement is held. Not held: a change with no subject phrase at all (세 개를 잃어버렸어, 세훈에게
        세 개를 줬어: the subject is dropped, and the one counted holder is the reading a listener makes); a clause
        that continues the clause before it in one turn (그리고 나래에게 세 개를 주었다: its holder comes from the
        reader); and a change in a conversation whose one count has no holder at all (구슬은 18개 있다. 다섯 개를
        꺼냈다.: the count is the thing's own, and no person is charged). A language that marks no subject with a
        particle does not drop its subject: there every such reading is held."""
        updates = parser.data.get("numeric_updates") or {}
        if not any(isinstance(f.get("triple"), list) and f["triple"][0] is None and f["triple"][1] in updates
                   for f in (parsed or {}).get("facts", [])):
            return False
        try:
            facts, _d, _p, _r = self._cached_replay(parser, self.observations, self.fills)
        except ValueError:
            return True
        numeric = self._numeric_targets(parser)
        counted = {}
        for fact in facts:
            triple = fact.get("triple") or [None, None]
            if isinstance(triple[0], str) and triple[1] in numeric | {"count_unknown"}:
                parts = fact.get("parts") if isinstance(fact.get("parts"), dict) else {}
                counted[triple[0]] = bool(parts.get("holder") and parts.get("thing")) or len(triple[0].split()) > 1
        # the one count the change would go to: its own thing (no holder), or a holder's
        if len(counted) == 1 and not next(iter(counted.values())):
            return False
        return self._subject_passed_over(parser, text, parsed, {w for key in counted for w in key.split()})

    @staticmethod
    def _subject_passed_over(parser, text, parsed, known):
        """Whether ``text`` has a phrase in the subject or giver place that the reading ``parsed`` did not take
        for a holder of its own: a word with a subject particle (the pack's slot group of the doer particle, and
        the forms read as one of them: 이 가 은 는 께서) that is no numeral or counter, no word outside names (오늘은),
        no word of a counted key (``known``: the thing, a known holder) and not the last word of a holder the
        reading names (세훈이 in a reading that names 세훈); or a titled word (대표님, 팀장) that the reading took into
        the name of the receiver before the receiver's own word (기 대표님 세훈에게 read as the receiver 기 대표 세훈).
        A word before the receiver that has no title (김 세훈에게) is the receiver's name as the reader reads it."""
        doer = getattr(parser, "doer_particle", "") or ""
        subject = next((set(group) for group in parser.slot_particles if doer in group), set())
        if not subject:
            return True
        subject |= {row["from"] for row in parser.particle_variants if row.get("from") and row.get("to") in subject}
        forms = parser.holder_forms or {}
        particles = sorted({p for group in parser.slot_particles for p in group} | set(parser.case_particles)
                           | {row["from"] for row in parser.particle_variants if row.get("from")}
                           | set(forms.get("delimiters") or []), key=len, reverse=True)
        name_titles = sorted(forms.get("name_titles") or [], key=len, reverse=True)
        job_titles = set(forms.get("job_titles") or [])

        def untitled(word):
            return next((word[:-len(t)] for t in name_titles if word.endswith(t) and len(word) > len(t)), word)
        keys = [f["triple"][0].split() for f in (parsed or {}).get("facts", [])
                if isinstance(f.get("triple"), list) and isinstance(f["triple"][0], str) and f["triple"][0]]
        named = {key[-1] for key in keys}
        inside = {w for key in keys for w in key[:-1]}
        words = [w.strip(".,!?\"'") for w in str(text).split()]
        for word in [w for w in words if w][:-1]:
            particle = next((p for p in particles if word.endswith(p) and len(word) > len(p)
                             and parser._particle_form(word[:-len(p)], p) == p), None)
            stem = word[:-len(particle)] if particle else word
            bare = untitled(stem)
            if particle in subject:
                if parser._protected_kind(word) or stem.lower() in parser.outside_names or bare in known \
                        or stem in known or bare in named or stem in named:
                    continue
                return True
            if particle is None and bare in inside and (bare != stem or stem in job_titles):
                return True
        return False

    def _asked_in_unit(self, parser, text, query, facts):
        """``(query, None)``, or ``(query, hold)`` for a count question about a holder and thing the conversation
        counts in two units (``_unit_keys``). A question that asks in the pack's first unit (몇 개), the unit the
        reply's counter word names, reads that unit's count; a question in another kept unit (몇 묶음), in no
        unit, in a unit not counted, or a sum or comparison over such a count is held, ``hold`` naming the subject
        and the units with their keys: one unit's count is never said for another, and nothing is converted."""
        counted = {}
        for fact in facts:
            base = fact.get("unit_key")
            if base and isinstance(fact.get("triple"), list) and isinstance(fact["triple"][0], str):
                counted.setdefault(base, {})[fact.get("unit")] = fact["triple"][0]
        split = {base: by_unit for base, by_unit in counted.items() if len(set(by_unit.values())) > 1}
        if not split:
            return query, None
        numeric = self._numeric_targets(parser)
        asked = self._unit_said(parser, text, after_asker=True)
        default = (((parser.language_pack or {}).get("counters") or {}).get("units") or [None])[0]
        out = []
        for row in query:
            triple = row.get("triple") if isinstance(row, dict) else None
            named = [name for name in ([triple[0]] if isinstance(triple, list) else []) + [
                str(h) for kind in ("total", "more", "fewer", "same") for h in (row.get(kind) or [])
                if isinstance(row, dict) and isinstance(row.get(kind), (list, tuple))] if isinstance(name, str)]
            hit = next((name for name in named if name in split), None)
            if hit is None:
                out.append(row)
                continue
            by_unit = split[hit]
            # only the pack's first unit is answered: the reply's counter word is that unit's (43개입니다 to 몇 묶음
            # would say the bundles as pieces); a count asked in another kept unit is held until the reply can
            # name the unit asked (request G7-6)
            if isinstance(triple, list) and triple[0] == hit and triple[1] in numeric and asked == default \
                    and asked in by_unit and not any(row.get(kind) for kind in ("total", "more", "fewer", "same")):
                out.append({**row, "triple": [by_unit[asked]] + list(triple[1:])})
                continue
            return query, {"subject": hit, "units": [{"unit": u, "key": k} for u, k in by_unit.items() if u]}
        return out, None

    @staticmethod
    def _container_parts(parser, words):
        """``(head, content)`` of a thing name of container structure, or None. The head is the container or
        measure, the content what it holds: in a pack that declares a partitive word (명사수.partitive: of), the
        words before it and after it (packs of quills: packs, quills); in a pack whose counters are nouns
        (수량단위.units), a last word that is one of them after the content (깃펜 묶음: 묶음, 깃펜); in a pack that
        declares measure words (명사수.measure), a first word that is one before the content (dozen quills: dozen,
        quills). The classes are the pack's; nothing here names a word."""
        partitive = {str(w).lower() for w in ((getattr(parser, "noun_number", None) or {}).get("partitive") or [])}
        at = next((i for i, w in enumerate(words) if w.lower() in partitive and 0 < i < len(words) - 1), None)
        if at is not None:
            return words[:at], words[at + 1:]
        units = set(((parser.language_pack or {}).get("counters") or {}).get("units") or [])
        if len(words) > 1 and words[-1] in units:
            return words[-1:], words[:-1]
        measure = {str(w).lower() for w in ((getattr(parser, "noun_number", None) or {}).get("measure") or [])}
        if len(words) > 1 and words[0].lower() in measure:
            return words[:1], words[1:]             # dozen quills: the measure, then what it measures
        return None

    @staticmethod
    def _one_thing(parser):
        """``fits(short, long)``: a mention's words name the thing of a longer name when they stand within it in
        order (singular or plural, ``_same_in_number``) and, when the longer name has container structure
        (``_container_parts``), one of them is a word of its head: bags, for bags of flour; 묶음, for 깃펜 묶음. A
        mention made of the content's words alone (quills, for packs of quills; 깃펜, for 깃펜 묶음) is the content,
        another thing than its container."""
        same = ReasoningContext._same_in_number(parser)

        def fits(short, long):
            if not ReasoningContext._within(short, long, same):
                return False
            parts = ReasoningContext._container_parts(parser, long)
            return parts is None or len(short) == len(long) or any(same(a, b) for a in short for b in parts[0])
        return fits

    @staticmethod
    def _thing_node(graph, thing, turn, fits=None):
        """The node of a thing mention (G7-S, step 3): its own, when the conversation said it so before; else the
        one existing thing whose words and the mention's are one within the other, in order (striped towels and
        striped cotton beach towels: one thing, the mention an alias of form ``short``), when exactly one fits
        (``fits``: ``_one_thing``; a container and its content are two things). Two that fit (pens, between red
        pens and blue pens) or none: a node of its own; a mention with a word the node lacks is another thing
        (red pens, blue pens)."""
        known = graph.id_of("thing", thing)
        if known is not None:
            return graph.node("thing", thing, turn)

        within = fits or ReasoningContext._within
        words = thing.split()
        fits = [n["id"] for n in graph.of_kind("thing")
                if within(words, n["name"].split()) or within(n["name"].split(), words)]
        if len(fits) == 1:
            return graph.join("thing", thing, fits[0], "short", turn)
        return graph.node("thing", thing, turn)

    def conversation_graph(self):
        """The conversation identity graph (``marco.reasoning.identity``), built from the replayed facts: a node
        per holder, thing and place, their aliases with the turn each came from (the key, the words said right
        before it in its statement, the thing's other declared number), a count edge per holder and thing with its
        value, whether a statement said it or replay computed it, and the turns it rests on. The node ids, and the
        aliases and frames no statement can give, are carried from turn to turn and in the snapshot."""
        from marco.reasoning.identity import ConversationGraph
        from marco.reasoning.inference import current_facts
        from relational_semantics import declared_plural
        parser = self._parser()
        facts, _d, _p, _r = self._cached_replay(parser, self.observations, self.fills)
        carried = getattr(self, "_graph_carried", None) or {}
        cache_key = (tuple(self.observations), json.dumps(self.fills, sort_keys=True, ensure_ascii=False, default=str),
                     json.dumps(carried, sort_keys=True, ensure_ascii=False, default=str))
        cached = getattr(self, "_graph_cache", None)
        if cached is not None and cached[0] == cache_key:
            return cached[1]
        graph = ConversationGraph.from_dict({key: carried[key] for key in ("ids", "next") if key in carried})
        updates = parser.data.get("numeric_updates", {})
        counted = set(updates) | {spec.get("target") for spec in updates.values() if isinstance(spec, dict)}
        counted |= {"count", "count_unknown"}
        keys = sorted(dict.fromkeys(self._holder_keys(parser)), key=lambda k: -len(k.split()))
        places = {place for row in facts for place in row.get("places") or [] if isinstance(place, str)}

        def split(subject):
            place = next((p for p in sorted(places, key=len, reverse=True) if subject == p or subject.startswith(p + " ")),
                         None)
            holder = place or next((k for k in keys if subject == k or subject.startswith(k + " ")), subject.split()[0])
            thing = subject[len(holder):].strip() or None
            return ("place" if place else "holder"), holder, thing
        last_of = {}
        turns_of = {}
        for row in facts:
            triple = row.get("triple") or [None, None]
            subject = triple[0]
            if not isinstance(subject, str) or not subject.strip() or triple[1] not in counted:
                continue
            turn = (row.get("evidence") or {}).get("turn")
            parts = row.get("parts") if isinstance(row.get("parts"), dict) else None
            if parts and parts.get("holder") and parts.get(
                    "key", " ".join(w for w in (parts.get("holder"), parts.get("thing")) if w)) == subject:
                # the reader named the holder and the thing (G7-S, step 3): no string is split
                holder, thing = parts["holder"], parts.get("thing") or None
                kind = "place" if holder in places else "holder"
            else:
                kind, holder, thing = split(subject)
            h = graph.node(kind, holder, turn)
            t = self._thing_node(graph, thing, turn, self._one_thing(parser)) if thing else None
            graph.keyed(subject, h, t)
            last_of[subject] = triple[1]
            turns_of.setdefault(subject, []).append(turn)
            text = (row.get("evidence") or {}).get("text") or ""
            for form, said in self._said_around_key(parser, text, holder):
                graph.alias(h, said, form, turn)
            if t is not None:
                # the thing's other declared number: its plural, or the singular whose plural it is
                number = getattr(parser, "noun_number", None) or {}
                other = declared_plural(thing, number)
                if not other or other == thing or other == thing + thing[-1:]:
                    irregular = {plural: one for one, plural in (number.get("irregular") or {}).items()}
                    other = irregular.get(thing) or next((thing[:-n] for n in (1, 2, 3) if len(thing) > n
                                                          and declared_plural(thing[:-n], number) == thing), None)
                if other and other != thing:
                    graph.alias(t, other, "number", turn)
        state, _changes = current_facts(facts, parser.data.get("mutable_predicates", []), updates)
        for row in state:
            triple = row.get("triple") or [None, None, None]
            subject = triple[0]
            if not isinstance(subject, str) or triple[1] not in ("count", "count_unknown") or graph.of_key(subject) is None:
                continue
            h, t = graph.of_key(subject)
            value = int(triple[2]) if triple[1] == "count" and str(triple[2]).lstrip("-").isdigit() else None
            origin = "said" if last_of.get(subject) in ("count", "count_unknown") else "computed"
            graph.count(h, t, value, origin, [x for x in turns_of.get(subject, []) if isinstance(x, int)])
        for row in carried.get("aliases") or []:
            graph.alias(row.get("node"), row.get("text"), row.get("form"), row.get("turn"))
        graph.frames = [dict(f) for f in carried.get("frames") or []]
        self._graph_cache = (cache_key, graph)
        return graph

    def _said_around_key(self, parser, text, holder):
        """The ways a statement named a holder around its key, as alias edges: a title before it (Dr. Kim) or
        after it (김 과장님, 준호 씨), a possessive before it (my cousin Lena, 제 친구 미경) and the relation word
        between (cousin, 친구). Only the words the pack declares for holders; a particle after the key is allowed."""
        forms = parser.holder_forms or {}
        fold = (lambda v: v.lower()) if parser.data.get("ignore_case") else (lambda v: v)
        titles = {fold(w) for w in forms.get("prefix_titles") or []}
        after_titles = sorted(forms.get("name_titles") or [], key=len, reverse=True)
        possessives = {fold(w) for w in list(forms.get("possessives") or []) + list(forms.get("determiners") or [])}
        relations = {fold(w) for w in forms.get("relation_nouns") or []} | {fold(w) for w in forms.get("job_titles") or []}
        tails = "|".join(re.escape(p) for p in self._frame_particles(parser)) or "(?!)"
        found = re.search(r"(?<![\w'])%s(\s?(?:%s))?(?:%s)?(?![\w'])" % (
            re.escape(holder), "|".join(map(re.escape, after_titles)) or "(?!)", tails), text,
            re.IGNORECASE if parser.data.get("ignore_case") else 0)
        if not found:
            return []
        out = []
        behind = (found.group(1) or "")
        if behind:
            out.append(("title", holder + behind))
        # an apposition around the name: "The nurse, Mia, …" / "Mia, the nurse, …"
        before_comma = re.search(r"(\w+)\s+(\w+),\s*$", text[:found.start()])
        if before_comma and fold(before_comma.group(1)) in possessives:
            out.append(("relation", before_comma.group(2)))
            out.append(("possessive", "%s %s" % (before_comma.group(1), before_comma.group(2))))
        after_comma = re.match(r"\s*,\s*(\w+)\s+(\w+)\s*,", text[found.end():])
        if after_comma and fold(after_comma.group(1)) in possessives:
            out.append(("relation", after_comma.group(2)))
            out.append(("possessive", "%s %s" % (after_comma.group(1), after_comma.group(2))))
        ahead = text[:found.start()].split()[-2:]
        if ahead and fold(ahead[-1]) in titles:
            out.append(("title", "%s %s" % (ahead[-1], holder)))
        elif len(ahead) == 2 and fold(ahead[0]) in possessives and ahead[1].isalpha():
            out.append(("possessive", "%s %s %s" % (ahead[0], ahead[1], holder)))
            out.append(("relation", ahead[1]))
            out.append(("possessive", "%s %s" % (ahead[0], ahead[1])))
        elif ahead and fold(ahead[-1]) in relations:
            out.append(("relation", ahead[-1]))
        return out

    def _graph_alias(self, subject, text, form):
        """A way of naming a holder no statement gave (a pointer resolved, a which-person reply), kept with its
        turn in the graph's carried part."""
        try:
            graph = self.conversation_graph()
        except Exception:    # noqa: BLE001
            return
        node = (graph.of_key(subject) or (None,))[0] or next(iter(graph.find(subject, kinds=("holder", "place"),
                                                                              forms=("key",))), None)
        if node is None or not isinstance(text, str) or not text.strip():
            return
        carried = dict(getattr(self, "_graph_carried", None) or graph.carried())
        carried["aliases"] = list(carried.get("aliases") or []) + [{"node": node, "text": text.strip(), "form": form,
                                                                   "turn": len(self.observations)}]
        carried.update({key: value for key, value in graph.carried().items() if key in ("ids", "next")})
        self._graph_carried = carried

    def _graph_nodes(self, parser, graph, word, stem=None, kinds=("holder", "place"), forms=None):
        """The nodes a word names (G7-Q step 2): an alias of theirs (the key, a title, a relation, the other number)
        as typed or without its particle; for a holder, else the key the pack's holder forms read it as."""
        fold = (lambda v: v.lower()) if parser.data.get("ignore_case") else (lambda v: v)
        for text in [word] + ([stem] if stem and stem != word else []):
            found = graph.find(text, kinds=kinds, fold=fold, forms=forms)
            if found:
                return found
        if "thing" in kinds and (not forms or "key" in forms):
            # a thing said with some of its words, in order (striped, towels, for striped cotton towels): the one
            # thing node they are words of (step 3); a word the pack declares for questions names none
            declared = self._declared_words(parser)
            for text in [word] + ([stem] if stem and stem != word else []):
                if not text or all(fold(w) in declared for w in text.split()):
                    continue
                found = graph.part_of(text, kinds=("thing",), fold=fold)
                if len(found) == 1:
                    return found
        if any(kind in kinds for kind in ("holder", "place")):
            keys = list(dict.fromkeys(self._holder_keys(parser)))
            key = self._holder_of(parser, word, keys)
            node = key and (graph.id_of("holder", key) or graph.id_of("place", key))
            if node and graph.nodes[node]["kind"] in kinds:
                return [node]
        return []

    def _graph_frame(self, holders, item):
        """Record the frame of a question just read, as node ids, in the graph's carried part."""
        try:
            graph = self.conversation_graph()
        except Exception:    # noqa: BLE001 -- the graph is a record of the conversation, never a cause of the turn
            return
        ids = [graph.find(name, kinds=("holder", "place"), forms=("key",)) for name in holders]
        thing = graph.find(item, kinds=("thing",), forms=("key",)) if item else []
        carried = dict(getattr(self, "_graph_carried", None) or graph.carried())
        frames = list(carried.get("frames") or []) + [{"turn": len(self.observations), "holders": [i[0] for i in ids if i],
                                                      "thing": thing[0] if thing else None}]
        carried["frames"] = frames[-8:]
        carried.update({key: value for key, value in graph.carried().items() if key in ("ids", "next")})
        self._graph_carried = carried

    def _nodes_read(self, result):
        """The node ids a turn's answer rests on, for the trace."""
        meaning = (result or {}).get("meaning") if isinstance((result or {}).get("meaning"), dict) else {}
        subjects = []
        query = meaning.get("query")
        if isinstance(query, list) and query and isinstance(query[0], str):
            subjects.append(query[0])
        subjects += [s for s in meaning.get("subjects") or [] if isinstance(s, str)]
        subjects += [meaning[k] for k in ("winner", "than") if isinstance(meaning.get(k), str)]
        if not subjects:
            return []
        try:
            graph = self.conversation_graph()
        except Exception:    # noqa: BLE001
            return []
        out = []
        for subject in subjects:
            for node in graph.of_key(subject) or ():
                if node and node not in out:
                    out.append(node)
        return out

    def _holder_keys(self, parser):
        """The holders this conversation's facts name, by their leading word (the key a
        holder form reads as: Morales for Dr. Morales, I for me, 나 for 저)."""
        facts, _d, _p, _r = self._cached_replay(parser, self.observations, self.fills)
        keys = []
        for item in facts:
            subject = item.get("triple", [None])[0]
            if isinstance(subject, str) and subject.split() and subject.split()[0] not in keys:
                keys.append(subject.split()[0])
        # a place of several words is one holder: its whole name before the counted thing
        for item in facts:
            subject = item.get("triple", [None])[0]
            if isinstance(subject, str) and len(subject.split()) > 2:
                keys.append(" ".join(subject.split()[:-1]))
        return keys

    def _holder_of(self, parser, surface, keys):
        """The one holder key ``surface`` names (as typed, or as the pack's holder forms, titles and
        particles read it), or None."""
        surface = surface.strip(" ,.!?")
        if not surface:
            return None
        if self._effort_allows(2) and self._permitted(None):
            # the graph's aliases first (step 3): the key, a title, a possessive phrase, a which-person reply
            try:
                graph = self.conversation_graph()
                fold = (lambda v: v.lower()) if parser.data.get("ignore_case") else (lambda v: v)
                nodes = graph.find(surface, kinds=("holder", "place"), fold=fold,
                                   forms=("key", "title", "possessive", "reply"))
                names = {graph.nodes[n]["name"] for n in nodes}
                if len(names) == 1 and next(iter(names)) in keys:
                    return next(iter(names))
            except Exception:    # noqa: BLE001
                pass
        tried = [surface, parser.canonical_name(surface)]
        tried += [literal for literal, _notes in parser._variant_literals(surface)]
        particles = sorted({p for group in parser.slot_particles for p in group} | set(parser.case_particles)
                           | {row["from"] for row in parser.particle_variants if row.get("from")}, key=len, reverse=True)
        for word in list(tried):
            for particle in particles:
                if word.endswith(particle) and len(word) > len(particle):
                    stem = word[:-len(particle)]
                    tried += [stem, parser.canonical_name(stem)]
                    tried += [literal for literal, _notes in parser._variant_literals(stem)]
                    break
        fold = (lambda v: v.lower()) if parser.data.get("ignore_case") else (lambda v: v)
        for word in tried:
            word = str(word).strip(" ,.!?")
            match = [key for key in keys if fold(key) == fold(word)]
            if len(match) == 1:
                return match[0]
        return None

    def _recipient_contrast(self, parser, text):
        """``They went to me, not Arthur`` / ``동훈이 아니라 연서한테 줬어요``: the receiver of the
        last transfer to the old one was the new one (대조정정, the same markers and order as the
        contrast of two amounts, with a holder on each side and no amount)."""
        if not self.observations:
            return None
        spec = parser.language_pack.get("contrast_correction") or {}
        folded = text.lower() if parser.data.get("ignore_case") else text
        keys = self._holder_keys(parser)
        for marker in spec.get("markers", []):
            mark = marker.lower() if parser.data.get("ignore_case") else marker
            if folded.count(mark) != 1:
                continue
            at = folded.index(mark)
            left, right = text[:at], text[at + len(mark):]
            if self._amount_of(parser, left.split()[-1] if left.split() else "") is not None:
                continue
            left_words = [w for w in re.split(r"\s+", left.strip(" ,.!?")) if w]
            right_words = [w for w in re.split(r"\s+", right.strip(" ,.!?")) if w]
            # Korean markers carry the old side's case particle (가 아니라): put it back on the word.
            particle = marker.strip().split()[0] if not marker.startswith(",") else ""
            if particle and left_words and marker.startswith(particle):
                left_words[-1] = left_words[-1] + particle
            before_side = [" ".join(left_words[-k:]) for k in (1, 2, 3) if len(left_words) >= k]
            after_side = [" ".join(right_words[:k]) for k in (1, 2, 3) if len(right_words) >= k]
            after_side += [" ".join(right_words[1:1 + k]) for k in (1, 2, 3)
                           if len(right_words) > k and right_words[0].lower() in ("to", "the")]
            first = next((key for key in (self._holder_of(parser, s, keys) for s in before_side) if key), None)
            second = next((key for key in (self._holder_of(parser, s, keys) for s in after_side) if key), None)
            if first is None or second is None or first == second:
                continue
            if spec.get("order") == "new_old":
                new, old = first, second
                new_said = next(s for s in before_side if self._holder_of(parser, s, keys) == first)
            else:
                old, new = first, second
                new_said = next(s for s in after_side if self._holder_of(parser, s, keys) == second)
            return {"old": old, "new": new, "new_said": new_said,
                    "evidence": {"text": text.strip(), "contrast": marker}}
        return None

    def _correct_recipient(self, parser, request, text, knowledge_path):
        """The receiver of one earlier transfer, corrected in place: the latest statement whose
        transfer added to the old receiver is said again with the new one, and must read as the
        same facts with only that receiver changed. Nothing else is rewritten; no new event."""
        replies = parser.data["context_replies"]
        verbs = self._verbs_for(parser, self.observations)
        updates = parser.data.get("numeric_updates", {})
        adds = {name for name, spec in updates.items() if isinstance(spec, dict) and spec.get("factor", 0) > 0}
        removes = {name for name, spec in updates.items() if isinstance(spec, dict) and spec.get("factor", 0) < 0}
        keys = self._holder_keys(parser)
        said = request["evidence"]["text"]

        def shape(sentence):
            read = self._read_source(parser, sentence, events=True, verbs=verbs) or {}
            return sorted((str(f["triple"][0]), str(f["triple"][1]), str(f["triple"][2]))
                          for f in read.get("facts", []))
        target = None
        for index in range(len(self.observations) - 1, -1, -1):
            rows = shape(self.observations[index])
            took = [r for r in rows if r[1] in adds and r[0].split()[:1] == [request["old"]]]
            gave = [r for r in rows if r[1] in removes]
            if took and gave:
                target = (index, rows)
                break
        if target is None:
            # The statement it corrects is not found: what the user called wrong is not fixed
            # any more; every holder is held until a later statement pins them (G3.0 b).
            self._remember_unread({"text": said, "at": len(self.observations), "범용": True})
            return {"operator": "relational_graph", "status": "unresolved", "transitions": [],
                    "answer": replies["reference_no_event"].format(말=said),
                    "meaning": {"act": "hold", "reason": "reference_no_event", "said": said, "by": "contrast"},
                    "verification": self._verification(knowledge_path, [{
                        "ok": False, "reason": "recipient_reference_no_event"}])}
        index, rows = target
        source = self.observations[index]
        old, new = request["old"], request["new"]
        expected = sorted((new + r[0][len(old):] if r[1] in adds and r[0].split()[:1] == [old] else r[0], r[1], r[2])
                          for r in rows)
        tokens = source.split(" ")
        forms = (parser.holder_forms or {}) if isinstance(getattr(parser, "holder_forms", None), dict) else {}
        # the particle a holder word ends in, a case particle with its delimiter stacked (한테는) as one
        particles = sorted({p for group in parser.slot_particles for p in group} | set(parser.case_particles)
                           | {row["from"] for row in parser.particle_variants if row.get("from")}
                           | set(forms.get("delimiters") or []), key=len, reverse=True)
        news = [request["new_said"], new] + [w for w, _n in parser._variant_literals(request["new_said"])]
        speaker = parser.speaker_placeholder
        # the speaker said as the user says it (제가), not as the key with a particle (나가): W5-3 item 7
        own = (forms.get("self") or {}).get("particle_forms") or {}
        said_by_user = request["new_said"].strip(" ,.!?")
        attempts = []
        for start in range(len(tokens)):
            # the widest span first: a titled holder (다온 씨한테는) is replaced whole, title and particle
            for width in (3, 2, 1):
                span = tokens[start:start + width]
                if len(span) < width:
                    continue
                raw = " ".join(span)
                core = raw.rstrip(".,!?")
                trailing = raw[len(core):]
                if self._holder_of(parser, core, keys) != old:
                    continue
                tail = next((p for p in particles if core.endswith(p) and len(core) > len(p)), "")
                for said_new in news + ([speaker] if speaker and new == speaker else []):
                    word = said_new.strip(" ,.!?")
                    if tail:
                        stem = next((word[:-len(p)] for p in particles if word.endswith(p) and len(word) > len(p)
                                     and self._holder_of(parser, word[:-len(p)], keys) == new), word)
                        word = stem + parser._particle_form(stem, tail) if tail in parser.particle_mates else stem + tail
                    if new == speaker:
                        users = [form for form, key_form in own.items() if key_form == word]
                        if users:
                            word = said_by_user if said_by_user in users else users[0]
                    attempts.append(" ".join(tokens[:start] + [word + trailing] + tokens[start + width:]))
        corrected = None
        for attempt in attempts:
            if shape(attempt) != expected:
                continue
            try:
                corrected = self.correct(index, attempt, knowledge_path)
                break
            except ValueError:
                continue
        if corrected is None:
            touched = sorted({r[0].split()[0] for r in rows if r[0].split()} | {new})
            self._remember_unread({"text": said, "at": len(self.observations), "대상": touched})
            return {"operator": "relational_graph", "status": "unresolved", "transitions": [],
                    "answer": replies["reference_value_unclear"].format(사건=source.strip(), 전=old),
                    "meaning": {"act": "hold", "reason": "reference_value_unclear", "said": said, "by": "contrast",
                                "event": source.strip(), "field": "recipient", "old_holder": old},
                    "verification": self._verification(knowledge_path, [{
                        "ok": False, "reason": "recipient_rewrite_unread"}])}
        record = self.corrections[-1]
        record.update({"utterance": text.strip(), "reference": {"field": "recipient", "old": old, "new": new}})
        changes = [row for row in corrected["transitions"] if row.get("operation") == "quantity_update"
                   and (row.get("evidence") or {}).get("turn", index) == index]
        self.last_explanation = {"kind": "correction", "correction": deepcopy(record),
                                 "transitions": deepcopy(corrected["transitions"])}
        touched = sorted({self._person_of(row.get("subject", "")) for row in changes if row.get("subject")})
        self.last_subject = None
        self.last_mentioned = touched
        self.salient += [person for person in touched if person not in self.salient]
        # The in-place revision's own meaning, with which receiver it replaced (request G4-2:
        # the realizer has no plan yet for a corrected receiver; the amounts of the correct
        # act are numbers).
        return {**corrected, "status": "observed",
                "meaning": {**corrected["meaning"], "field": "recipient", "old_holder": old, "new_holder": new}}

    @staticmethod
    def _agree_number(parser, tokens, position, old, new_word):
        """The event sentence with its new amount and the counted noun after it in
        the declared plural, when the old amount was the pack's singular count."""
        declared = getattr(parser, "noun_number", None) or {}
        if not declared or str(old) != str(declared.get("count_slot_value", 1)) or position + 1 >= len(tokens):
            return None
        from relational_semantics import declared_plural
        word = tokens[position + 1]
        core = word.rstrip(".,!?")
        trailing = word[len(core):]
        plural = declared_plural(core, declared)
        if plural is None:
            return None
        return " ".join(tokens[:position] + [new_word, plural + trailing] + tokens[position + 2:])

    @staticmethod
    def _missing_premise(parser, queries, facts):
        """Say which premise is missing when the subject is known but the relation is not.

        ``그 사람은 어디 있어?`` after only counts: the person is known, a
        location was never stated. The words come from the pack; an undeclared
        relation name falls back to the general unresolved reply.
        """
        replies = parser.data.get("context_replies", {})
        names = parser.data.get("relation_names", {})
        if "missing_premise" not in replies:
            return None
        found = ReasoningContext._premise_missing(parser, queries, facts)
        if found is None:
            return None
        return replies["missing_premise"].format(**{"대상": found["subject"], "관계": names[found["relation"]]})

    @staticmethod
    def _unknown_subject(queries, facts):
        """The subject of the first question none of whose names the conversation ever mentioned."""
        known = set()
        for item in facts:
            for value in (item.get("triple") or [None, None, None])[::2]:
                if isinstance(value, str):
                    known.update(value.split())
        for query in queries:
            triple = query.get("triple") if isinstance(query, dict) else None
            if not (isinstance(triple, list) and len(triple) == 3 and isinstance(triple[0], str)):
                continue
            subject = triple[0]
            if subject.startswith(("?", "$")) or subject.split()[0] in known:
                continue
            return subject
        return None

    @staticmethod
    def _premise_missing(parser, queries, facts):
        """The subject and relation of the first missing premise, or None."""
        names = parser.data.get("relation_names", {})
        known = set()
        for item in facts:
            subject = item.get("triple", [None])[0]
            if isinstance(subject, str):
                known.add(subject)
                known.add(subject.split()[0])
        for query in queries:
            triple = query.get("triple") if isinstance(query, dict) else None
            if not (isinstance(triple, list) and len(triple) == 3 and isinstance(triple[0], str)):
                continue
            subject, predicate = triple[0], triple[1]
            if subject.startswith(("?", "$")) or subject not in known or predicate not in names:
                continue
            if any(item.get("triple", [None, None])[1] == predicate
                   and str(item["triple"][0]).split()[:len(subject.split())] == subject.split()
                   for item in facts):
                continue
            return {"subject": subject, "relation": predicate}
        return None

    def _resolve_event_referents(self, parser, current, facts):
        """Resolve declared discourse pointers in event roles, or ask safely.

        Queries already have their own pointer resolver because their target
        is a graph triple.  Events carry several typed roles, so their
        antecedent is first looked up under the same role key (actor, object,
        destination, …).  A graph candidate is used only when it is unique.
        This keeps two unfinished events and two conversation topics from
        being merged merely because both contain a pronoun.
        """
        if not current or not (current.get("사건") or current.get("가정사건")):
            return current, None
        pointers = [word for word in sorted(parser.pointers or [], key=len, reverse=True) if word]
        if not pointers:
            return current, None
        names = sorted({str(row["triple"][0]) for row in facts
                        if isinstance(row.get("triple"), list) and row["triple"]
                        and isinstance(row["triple"][0], str)})

        def resolve(slot, raw):
            if not isinstance(raw, str):
                return raw, None
            pointer = next((word for word in pointers if raw == word or raw.startswith(word + " ")), None)
            if pointer is None:
                return raw, None
            tail = raw[len(pointer):].strip()
            candidates = [name for name in names if not tail or name.endswith(tail)]
            remembered = self.last_referents.get(slot)
            if remembered in candidates:
                return remembered, None
            salient = self._salient_choice(candidates)
            if salient is not None:
                return salient, None
            if len(candidates) == 1 and self._alone(candidates[0]):
                return candidates[0], None
            return raw, {"말": pointer, "후보": candidates}

        copied = deepcopy(current)
        for family in ("사건", "가정사건"):
            rewritten = []
            for event in copied.get(family, []):
                candidates = []
                for roles in event.get("자리후보") or [event.get("자리", {})]:
                    updated = {}
                    for slot, value in roles.items():
                        resolved, ambiguity = resolve(slot, value)
                        if ambiguity is not None:
                            return current, ambiguity
                        updated[slot] = resolved
                    candidates.append(updated)
                event["자리후보"] = candidates
                event["자리"] = dict(candidates[0]) if candidates else dict(event.get("자리", {}))
                rewritten.append(event)
            copied[family] = rewritten
        return copied, None

    def _remember_referents(self, current):
        """Record only explicit role bindings from a successfully read turn."""
        if not current:
            return
        subjects = []
        for fact in current.get("facts", []):
            triple = fact.get("triple") or []
            if triple and isinstance(triple[0], str) and not triple[0].startswith(("?", "$")):
                if triple[0] not in subjects:
                    subjects.append(triple[0])
        if subjects:
            # A turn that names several people fixes none of them for a later
            # pointer: "A gave B one" followed by "how many marbles does she have" is
            # asked back, never resolved to whichever fact came last.
            people = []
            for subject in subjects:
                if self._person_of(subject) not in people:
                    people.append(self._person_of(subject))
            self.last_subject = subjects[-1] if len(people) == 1 else None
            self.last_mentioned = people
            # A statement adds whom it names to the people a pointer may mean.
            self.salient += [person for person in people if person not in self.salient]
        for family in ("사건", "가정사건"):
            for event in current.get(family, []):
                for slot, value in (event.get("자리") or {}).items():
                    if isinstance(value, str) and value and not value.startswith(("?", "$")):
                        self.last_referents[slot] = value
                actor = (event.get("자리") or {}).get("은")
                if isinstance(actor, str) and actor:
                    self.last_subject = actor
                    if self._person_of(actor) not in self.salient:
                        self.salient.append(self._person_of(actor))

    def _name_reply(self, parser, text, knowledge_path):
        """A reply that only names a person: ``And Moru?``, ``모래는?``, ``I mean Haru``.

        After a pointer question was held for its candidates, the name takes
        the pointer's place in that question. Otherwise the name takes the
        place of the person in the last answered question (as many leading
        words of its subject as the name has). The pack declares the words
        that may stand around the name; nothing else is read, and a name that
        is not exactly one known person is not used.
        """
        spec = parser.language_pack.get("name_reply") or {}
        if self._in_name_reply or not spec or not (self.pending_pointer or self.last_question):
            return None
        said = text.strip().rstrip(".?!？。 ")
        folded = said.lower()
        # The declared heads may stand one after another ("and how about Haru",
        # "그럼 그리고 ..."): each is taken off in turn, none is guessed.
        stripped = True
        while stripped:
            stripped = False
            for head in sorted(spec.get("heads", []), key=len, reverse=True):
                folded = said.lower()
                # a head stands before the name as a word of its own, after a space or a comma
                if folded == head.lower() or folded.startswith((head.lower() + " ", head.lower() + ",")):
                    said = said[len(head):].strip(" ,")
                    stripped = True
                    break
        for tail in sorted(spec.get("tails", []), key=len, reverse=True):
            if said.lower().endswith(tail.lower()) and len(said) > len(tail):
                said = said[:-len(tail)]
                break
        name = parser.canonical_name(said.strip(" ,"))
        if not name:
            return None
        facts, _d, _p, _r = self._cached_replay(parser, self.observations, self.fills)
        people = set()
        for item in facts:
            subject = item.get("triple", [None])[0]
            if isinstance(subject, str):
                words = subject.split()
                people.update(" ".join(words[:k]) for k in range(1, len(words) + 1))
        match = [person for person in people if person.lower() == name.lower()]
        if not match:
            # The name as the pack reads a holder said with a title or a relation (Dr. Morales,
            # 예린 씨): the forms its phrase variants and holder forms read it as.
            for variant, _notes in parser._variant_literals(name):
                match = [person for person in people if person.lower() == variant.strip(" ,").lower()]
                if match:
                    break
        if len(match) != 1:
            return None
        name = match[0]
        if self.pending_pointer:
            question, old = self.pending_pointer["question"], self.pending_pointer["pointer"]
            if not any(candidate == name or candidate.startswith(name + " ")
                       for candidate in self.pending_pointer["candidates"]):
                return None
            self._graph_alias(name, old, "reply")
        else:
            question = self.last_question["text"]
            old = " ".join(self.last_question["subject"].split()[:len(name.split())])
            if self._effort_allows(2):
                # the name replaces the holder of the last question, as one identity (step 3)
                holder = self._person_of(self.last_question["subject"])
                if re.search(r"(?<!\w)" + re.escape(holder) + r"(?![A-Za-z])", question,
                             re.IGNORECASE if parser.data.get("ignore_case") else 0):
                    old = holder
        # The replaced words start a word; Latin letters may not continue them
        # (so "Moru" is not found in "Morula"), a particle may.
        pattern = re.compile(r"(?<!\w)" + re.escape(old) + r"(?![A-Za-z])",
                             re.IGNORECASE if parser.data.get("ignore_case") else 0)
        if not pattern.search(question):
            # The last question named its person by a pointer (he, 그분): the name takes the
            # pointer's place, when the question holds exactly one.
            flags = re.IGNORECASE if parser.data.get("ignore_case") else 0
            particles = "|".join(re.escape(x) for x in sorted(
                {x for group in parser.slot_particles for x in group} | set(parser.case_particles)
                | {row["from"] for row in parser.particle_variants if row.get("from")}, key=len, reverse=True)) or "(?!)"
            found = []
            for w in sorted(parser.pointers or [], key=len, reverse=True):
                m = re.search(r"(?<![\w])%s(?=(?:%s)?(?![\w]))" % (re.escape(w), particles), question, flags)
                if m and not any(m.start() >= f.start() and m.end() <= f.end() for f in found):
                    found.append(m)
            if len(found) != 1:
                return None
            at = found[0]
            tail = re.match(r"(?:%s)(?![\w])" % particles, question[at.end():])
            said_particle = tail.group(0) if tail else ""
            question = (question[:at.start()] + old + said_particle + question[at.end() + len(said_particle):])
            pattern = re.compile(r"(?<!\w)" + re.escape(old) + re.escape(said_particle) + r"(?![A-Za-z])", flags)
            name_particle = parser._particle_form(name, said_particle) if said_particle in parser.particle_mates \
                else said_particle
            name = name + name_particle
        rewritten = pattern.sub(lambda _m: name, question, count=1)
        self._in_name_reply = True
        try:
            result = self._turn_reply(rewritten, knowledge_path)
        finally:
            self._in_name_reply = False
        if result is not None:
            # The meaning is the rewritten question's own; the reply adds only the
            # user's words and the one name they supplied (request G1-2).
            meaning = dict(result["meaning"]) if isinstance(result.get("meaning"), dict) else {}
            result = {**result, "name_reply": {"said": text.strip(), "read_as": rewritten},
                      "meaning": {**meaning, "name_reply": {"said": text.strip(), "name": name}}}
        return result

    def _record_frame(self, parser, text, query):
        """Keep the frame of a question just read (answered or held): its text, and the holder and item slots
        its query fills. A count names one holder and its item; a total or a comparison its holders and the
        item. A follow-up that names one slot only is read against it (``_partial_frame``)."""
        row = next((q for q in query or [] if isinstance(q, dict)), None)
        if row is None:
            return
        triple = row.get("triple")
        if isinstance(triple, list) and len(triple) == 3 and triple[1] == "count" and isinstance(triple[0], str) \
                and triple[0].strip() and not triple[0].startswith(("?", "$")):
            known = self.conversation_graph().of_key(triple[0]) if self._effort_allows(2) else None
            if known is not None:
                # the frame's slots are the graph's nodes for that key (step 2)
                graph = self.conversation_graph()
                holders = [graph.nodes[known[0]]["name"]]
                item = graph.nodes[known[1]]["name"] if known[1] else None
            else:
                keys = sorted(self._holder_keys(parser), key=lambda k: -len(k.split()))
                holder = next((k for k in keys if triple[0].startswith(k + " ") or triple[0] == k), triple[0].split()[0])
                holders, item = [holder], triple[0][len(holder):].strip() or None
        else:
            kind = next((k for k in ("total", "more", "fewer", "same") if isinstance(row.get(k), dict)), None)
            if kind is None:
                return
            spec = row[kind]
            members = spec.get("members") if kind == "total" else [spec.get("a"), spec.get("b")]
            holders = [m for m in members if isinstance(m, str)] if isinstance(members, list) else []
            item = spec.get("item") if isinstance(spec.get("item"), str) else None
        self.last_frame = {"text": text.strip(), "holders": holders, "item": item}
        self._graph_frame(holders, item)
        # the last few frames, for a question over "the two" of them
        self.recent_frames = (list(getattr(self, "recent_frames", None) or []) + [dict(self.last_frame)])[-4:]

    @staticmethod
    def _frame_particles(parser, extra=()):
        return sorted({p for group in parser.slot_particles for p in group} | set(parser.case_particles)
                      | set((parser.count_question or {}).get("delimiters", []))
                      | {row["from"] for row in parser.particle_variants if row.get("from")} | set(extra),
                      key=len, reverse=True)

    def _frame_span(self, parser, tokens, value, slot):
        """(begin, end, particle) of the words that say ``value`` in a question's tokens, or None. A holder's
        span takes in the words the pack says may stand before a holder (a title, a possessive, an article)."""
        fold = (lambda v: v.lower()) if parser.data.get("ignore_case") else (lambda v: v)
        words = [fold(w) for w in str(value).split()]
        if not words:
            return None
        extra = (parser.language_pack.get("name_reply") or {}).get("follow_up") or {}
        particles = self._frame_particles(parser, extra.get("place_cases", [])) + [""]
        titles = [""] + list((parser.holder_forms or {}).get("name_titles", [])) if slot == "holder" else [""]
        bare = [fold(t.strip(",.?!")) for t in tokens]
        for start in range(len(bare) - len(words) + 1):
            if bare[start:start + len(words) - 1] != words[:-1]:
                continue
            last = bare[start + len(words) - 1]
            # the last word as typed: the value, a title the pack puts after a name (님, 씨), a particle
            found = next(((title, p) for title in titles for p in particles if last == words[-1] + fold(title) + fold(p)),
                         None)
            if found is None:
                continue
            particle = found[1]
            begin = start
            if slot == "holder":
                forms = parser.holder_forms or {}
                before = {fold(w) for w in list(forms.get("prefix_titles", [])) + list(forms.get("possessives", []))
                          + list(forms.get("determiners", []))}
                while begin > 0 and bare[begin - 1] in before:
                    begin -= 1
            return begin, start + len(words), particle
        return None

    def _partial_frame(self, parser, text, knowledge_path):
        """A follow-up that names one slot of the last question's frame (``And cups?``, ``And in the shed?``,
        ``Hector, I mean.``, ``연습실은 어떻습니까?``, ``드라이버는?``), at effort 2: the named words are tried in
        each slot of the frame (its holder, its item); each candidate is the last question with those words in
        that slot, checked against the conversation: it must read as a question, and every holder and item it
        asks about must be in the state (or named by a statement not read yet, which then holds it). The
        survivors are ranked (state, grammar, context); a clear win is asked, a tie asks which, none leaves the
        turn unread. The words around the named ones are the pack's (이름답 heads and tails, and
        이름답.follow_up: more tails, the markers and cases of a place, articles)."""
        if not self._effort_allows(2) or self._in_name_reply or not self.last_frame:
            return None
        spec = parser.language_pack.get("name_reply") or {}
        extra = spec.get("follow_up") or {}
        fold = (lambda v: v.lower()) if parser.data.get("ignore_case") else (lambda v: v)
        said = text.strip().rstrip(".?!？。 ")
        stripped = True
        while stripped:
            stripped = False
            for head in sorted(list(spec.get("heads", [])) + list(extra.get("heads", [])), key=len, reverse=True):
                if fold(said) == fold(head) or fold(said).startswith((fold(head) + " ", fold(head) + ",")):
                    said, stripped = said[len(head):].strip(" ,"), True
                    break
        for tail in sorted(list(extra.get("tails", [])) + list(spec.get("tails", [])), key=len, reverse=True):
            if fold(said).endswith(fold(tail)) and len(said) > len(tail):
                said = said[:-len(tail)].strip(" ,")
                break
        # the words the pack declares as saying nothing in a follow-up (please, maybe; 좀, 혹시) come off anywhere
        ignorable = {fold(w) for w in extra.get("ignorable", [])}
        words = [w for w in said.split() if fold(w.strip(",.!?")) not in ignorable]
        said = " ".join(words).strip(" ,")
        words = said.split()
        place = False
        if words and fold(words[0]) in {fold(m) for m in extra.get("place_markers", [])}:
            words, place = words[1:], True
        if not words or len(words) > 4:
            return None
        # the named words' own particle comes off (드라이버는, 헛간에는: a place's case says it is a place)
        last = words[-1]
        for particle in self._frame_particles(parser, extra.get("place_cases", [])):
            if last.endswith(particle) and len(last) > len(particle):
                place = place or particle in extra.get("place_cases", [])
                words = words[:-1] + [last[:-len(particle)]]
                break
        articles = {fold(a) for a in extra.get("articles", [])}
        core = words[1:] if len(words) > 1 and fold(words[0]) in articles else words
        named, plain = " ".join(core), " ".join(words)
        frame = self.last_frame
        tokens = frame["text"].rstrip().split()
        graph = self.conversation_graph()
        unread = " ".join(entry["text"] for entry in self.unread_guard + self.unread)
        slots = [("holder", frame["holders"][0])] if len(frame["holders"]) == 1 else []
        slots += [("item", frame["item"])] if frame.get("item") else []
        candidates, tried = [], set()
        for slot, value in slots:
            label = "%s=%s" % (slot, named)
            span = self._frame_span(parser, tokens, value, slot)
            if span is None:
                self._candidate_dropped(2, "partial_frame", label, "slot_not_in_question")
                continue
            begin, end, particle = span
            new = plain if slot == "holder" else named
            if particle:
                head, _sp, tail = new.rpartition(" ")
                tail += parser._particle_form(tail, particle) if particle in parser.particle_mates else particle
                new = (head + " " + tail) if head else tail
            closing = tokens[end - 1][len(tokens[end - 1].rstrip(",.?!")):]
            rewritten = " ".join(tokens[:begin] + [new + closing] + tokens[end:])
            if rewritten in tried or fold(rewritten) == fold(frame["text"]):
                continue
            tried.add(rewritten)
            try:
                query = (parser.parse(rewritten, partial=True) or {}).get("query") or []
            except Exception:    # noqa: BLE001 -- a candidate that cannot be read is dropped, never raised
                query = []
            asked = []
            for row in query:
                if not isinstance(row, dict):
                    continue
                triple = row.get("triple")
                if isinstance(triple, list) and len(triple) == 3 and isinstance(triple[0], str):
                    asked.append(triple[0])
                for kind in ("total", "more", "fewer", "same"):
                    if isinstance(row.get(kind), dict):
                        members = row[kind].get("members") if kind == "total" else [row[kind].get("a"),
                                                                                  row[kind].get("b")]
                        thing = row[kind].get("item")
                        asked += ["%s %s" % (m, thing) if thing else str(m) for m in members or []
                                  if isinstance(m, str)]
            if not asked:
                self._candidate_dropped(2, "partial_frame", label, "not_a_question")
                continue
            # every holder and thing the candidate asks about is a count edge of the graph (step 2)
            in_state = all(graph.of_key(key) in graph.counts for key in asked)
            waits = fold(named) in fold(unread)
            if not in_state and not waits:
                self._candidate_dropped(2, "partial_frame", label, "not_in_state")
                continue
            if slot == "holder":
                known = bool(place or self._graph_nodes(parser, graph, plain, named, ("holder", "place"),
                                                         forms=("key", "title"))
                             or any(fold(node["name"]).endswith(" " + fold(named))
                                    for node in graph.nodes.values() if node["kind"] in ("holder", "place")))
            else:
                known = bool(self._graph_nodes(parser, graph, named, None, ("thing",)))
            if not known and not waits:
                # the named words are no holder, thing or place of this conversation: not a follow-up
                self._candidate_dropped(2, "partial_frame", label, "not_named_before")
                continue
            if waits and not in_state:
                # named only by a statement kept unread: the particle that statement put on it says its role
                # (다온은 / 다온에게: a holder; 다온을: a thing); 이/가 say neither
                roles = extra.get("unread_roles") or {}
                said_with = re.findall(r"(?<![\w])%s(\w*)" % re.escape(named), unread)
                known = known or any(tail in roles.get(slot, []) for tail in said_with)
            candidates.append({"label": label, "slot": slot, "rewritten": rewritten,
                               "fit": {"state": int(in_state), "grammar": 1, "context": int(bool(known)), "cost": 0}})
        if not candidates and len(core) == 1 and slots and slots[0][0] == "holder" and self._effort_allows(2):
            # one name the conversation never counted, said as a follow-up (Zed? / 제드는?): the last question
            # asked of it, held naming what is missing, never left unread
            word = core[0]
            name_like = (bool(re.fullmatch((parser.holder_forms or {}).get("name") or "(?!)", word))
                         and not re.fullmatch((parser.holder_forms or {}).get("name") or "(?!)", word.lower()))
            marked = last != words[-1] or text.strip().rstrip("?.!？。 ") != said
            if (name_like or (marked and not parser.data.get("ignore_case"))) and not parser._protected_kind(word) \
                    and fold(word) not in self._declared_words(parser):
                span = self._frame_span(parser, tokens, slots[0][1], "holder")
                if span is not None:
                    begin, end, particle = span
                    new = word + ((parser._particle_form(word, particle) if particle in parser.particle_mates
                                   else particle) if particle else "")
                    closing = tokens[end - 1][len(tokens[end - 1].rstrip(",.?!")):]
                    candidates.append({"label": "holder=%s" % word, "slot": "holder", "fit": {"state": 0},
                                       "rewritten": " ".join(tokens[:begin] + [new + closing] + tokens[end:])})
        winner, deciding, ranking = self._rank_candidates(candidates, kind="partial_frame")
        if winner is None and deciding == "tie":
            replies = parser.data.get("context_replies", {})
            return {"operator": "relational_graph", "status": "unresolved", "transitions": [],
                    "meaning": {"act": "ask", "reason": "which_referent", "word": named,
                                "candidates": [c["rewritten"] for c in ranking[:2]]},
                    "answer": replies.get("which_referent", "").format(**{
                        "말": named, "목록": ", ".join("'%s'" % c["rewritten"] for c in ranking[:2])}),
                    "verification": self._verification(knowledge_path, [{"ok": False, "reason": "partial_frame_tie"}])}
        if winner is None:
            return None
        self._in_name_reply = True
        try:
            result = self._turn_reply(winner["rewritten"], knowledge_path)
        finally:
            self._in_name_reply = False
        if result is not None:
            meaning = dict(result["meaning"]) if isinstance(result.get("meaning"), dict) else {}
            result = {**result, "partial_frame": {"said": text.strip(), "read_as": winner["rewritten"],
                                                  "slot": winner["slot"], "decided_by": deciding},
                      "meaning": {**meaning, "partial_frame": {"said": text.strip(), "slot": winner["slot"]}}}
        return result

    @staticmethod
    def _read_source(parser, source, **kw):
        """원문으로 읽고, 안 되면 **선언된 말머리 군말을 뗀 꼴**로도 읽어 본다.

        지우는 규칙이 아니다 — 원문은 그대로 남고 읽기 후보가 하나 는 것뿐이다.
        군말은 뜻을 안 나르므로, 떼어 낸 쪽이 읽히면 그쪽이 옳은 읽기다. 군말만으로
        된 말은 언어팩이 이미 안 뗀다 — 그건 군말이 아니라 그 자체가 발화다.

        A statement this conversation read by another of the reader's readings (G5.4 B) is read that
        way again: the choice is kept on the conversation's parser (``chosen_readings``) and replayed.
        """
        oid = _readings.oid_of(source)
        if oid is not None:
            chosen = (getattr(parser, "chosen_readings", None) or {}).get(oid)
            if chosen is not None:
                return deepcopy(chosen)
            if oid != TENTATIVE:
                raise ReadingUnavailable("historical_reading_unavailable")
        import inspect
        from encoder import strip_fillers
        kw = dict(kw)
        if "_entry_selection" not in kw:
            try:
                declared = inspect.signature(parser.parse).parameters.get("_entry_selection")
            except (TypeError, ValueError):
                declared = None
            if declared is not None and declared.kind in (inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                                          inspect.Parameter.KEYWORD_ONLY):
                kw["_entry_selection"] = True
        읽음 = parser.parse(source, partial=True, repair=True, **kw)
        벗긴말 = strip_fillers(source, parser.language_pack)
        if not 벗긴말 or 벗긴말 == source.strip():
            return 읽음
        벗김 = parser.parse(벗긴말, partial=True, repair=True, **kw)
        if 벗김 is None:
            return 읽음
        capsule = 벗김.get("entry_selection") if isinstance(벗김, dict) else None
        if isinstance(capsule, dict) and capsule.get("schema") == "marco-entry-selection-v1" \
                and capsule.get("scope") == "known_selected_input_clauses" \
                and capsule.get("status") == "partial" and capsule.get("coordinate_space") == "parser_view" \
                and isinstance(capsule.get("gaps"), list):
            capsule = deepcopy(capsule)
            capsule["gaps"].append({"clause_ordinal": None, "code": "filler_source_offset_unproven"})
            벗김 = dict(벗김, entry_selection=capsule)
        return 벗김

    @staticmethod
    def _known_verbs(parser, sources):
        """이 말들에서 설명받은 어간들의 꼴 → {어간, 물음}."""
        stems = set()
        for source in sources:
            parsed = ReasoningContext._definitions_read(parser, source)
            if parsed is not None:
                stems |= {rule["verb"] for rule in parsed.get("정의", [])}
        return ReasoningContext._forms_of(parser, stems)

    @staticmethod
    def _definitions_read(parser, source):
        """Definition discovery goes through the bound raw reading; only unidentified or provisional
        inputs are parsed fresh by the installed parser."""
        oid = _readings.oid_of(source)
        if oid is not None:
            chosen = (getattr(parser, "chosen_readings", None) or {}).get(oid)
            if chosen is not None:
                return chosen
            if oid != TENTATIVE:
                raise ReadingUnavailable("historical_reading_unavailable")
        return parser.parse(source, partial=True)

    @staticmethod
    def _replay(parser, sources, fills=(), event_ids=None, *, projection=None):
        """관찰을 다시 읽어 사실을 만든다. (사실, 뜻이 정해진 낱말, 못 채운 사건, 읽힌 몸통).

        ``fills`` 는 되물어서 받은 답이다 — **어느 사건의 어느 역할을 어떤 값으로
        채웠다.** 원문을 고쳐 쓰지 않는다. 한국어 문장을 새로 지어 다시 읽으면
        역할도 사건 이름도 흔들리고, 조사 만들기에도 기대게 된다.

        사건은 **제 차례의 뜻**으로 푼다 — 앞 사건에 뒤에 고친 뜻을 소급하지
        않는다. 다만 그때 아무 뜻도 없었다면, **나중에 들은 설명으로 이어 푼다.**
        끝내 뜻이 없는 사건은 사실을 만들지 않는다. 버리는 것이 아니라
        그 사건이 건드린 값을 확정하지 못하게 막는 쪽으로 남는다.

        사건은 뜻을 몰라도 꼴로 읽는다. 다만 **물음인지는 알아야** 하므로,
        먼저 뜻풀이만 걷어 활용표를 만들고 그 표를 쥐고 다시 읽는다.
        """
        table = ReasoningContext._forms_of(parser, {
            rule["verb"] for source in sources
            for parsed in [ReasoningContext._definitions_read(parser, source)] if parsed is not None
            for rule in parsed.get("정의", [])})
        archive = parser.__dict__.setdefault("chosen_programs", {})
        origin = {}
        read = []
        for source in sources:
            parsed = ReasoningContext._read_source(parser, source, events=True, verbs=table)
            if parsed is None:
                raise ValueError("unrecognized_observation")
            read.append(parsed)
        # 시간표는 **차례대로** 쌓는다. 그래야 각 뜻풀이가 그때까지 배운 것만
        # 재료로 쓰고, 뒤에 배운 것이 앞 사건에 소급되지 않는다.
        timeline, 꼴모음, 읽힌몸통 = {}, {}, set()
        for index, parsed in enumerate(read):
            who = _readings.oid_of(sources[index])
            who = (who, getattr(sources[index], "rev", 1)) if who not in (None, TENTATIVE) else None
            for number, rule in enumerate(parsed.get("정의", [])):
                배운것 = ReasoningContext._learned(parser, timeline, 꼴모음)
                # An archived induced/compiled rule is reused while every definition version its calls
                # captured is still the same identified reading; an explicit correction of a referenced
                # definition changes that identity and rebuilds it.  Ordinary parser learning never does.
                kept = archive.get((who, number)) if who else None
                if kept is not None and kept["origins"] == {
                        "%s@%s" % (c.get("action"), c.get("definition_version")):
                        origin.get((c.get("action"), c.get("definition_version")))
                        for c in kept["usable"]["프로그램"].get("calls") or []}:
                    usable = deepcopy(kept["usable"])
                else:
                    if kept is None and who and (who, number) in parser.__dict__.get("blocked_programs", ()):
                        # original program not archived and its grammar is unknown or changed
                        raise ReadingUnavailable("historical_reading_unavailable")
                    usable = ReasoningContext._rule(parser, rule, 배운것)
                    if usable is not None and who:
                        archive[(who, number)] = {"usable": deepcopy(usable), "origins": {
                            "%s@%s" % (c.get("action"), c.get("definition_version")):
                            origin.get((c.get("action"), c.get("definition_version")))
                            for c in usable["프로그램"].get("calls") or []}}
                if usable is not None:
                    # The definition's position is part of its identity.  A
                    # later redefinition must not silently change an older
                    # event that is replayed or completed.
                    usable["프로그램"] = {**usable["프로그램"], "definition_version": index}
                    origin[(rule["verb"], index)] = list(who) if who else None
                    timeline.setdefault(rule["verb"], []).append((index, usable))
                    읽힌몸통.add(rule.get("몸통"))

        def rule_for(verb, at):
            before = [r for i, r in timeline.get(verb, []) if i <= at]
            if before:
                return before[-1]
            after = timeline.get(verb, [])
            return after[0][1] if after else None

        def programs_for(rule):
            """Resolve calls by the definition version captured in the body.

            The registry is an execution input, not text reconstructed from a
            definition.  A later redefinition of `보관하다` therefore cannot
            change a `준비하다` definition which explicitly learned the older
            `보관하다` version.
            """
            registry, seen = {}, set()

            def add(program):
                for call in program.get("calls") or []:
                    action, version = call.get("action"), call.get("definition_version")
                    key = (action, version)
                    if key in seen:
                        continue
                    seen.add(key)
                    nested = next((candidate["프로그램"] for at, candidate
                                   in timeline.get(action, []) if at == version), None)
                    if nested is None:
                        continue
                    registry["%s@%s" % key] = nested
                    add(nested)

            add(rule["프로그램"])
            return registry

        stems = set(timeline)
        채움, 조회값, 조회사실, 덮기 = {}, {}, {}, []
        for fill in fills:
            if fill.get("범위") in ("앞으로", "설명정정", "이번만"):
                덮기.append(fill)
            else:
                if fill.get("변수"):
                    조회값.setdefault(fill["사건"], {})[fill["변수"]] = fill["값"]
                if fill.get("사실"):
                    조회사실.setdefault(fill["사건"], []).append(fill["사실"])
                if not fill.get("변수") and not fill.get("사실"):
                    채움.setdefault(fill["사건"], {})[fill["역할"]] = fill["값"]

        def 덮을것(이름표, stem, at):
            """이 사건에 미치는 덮기. 범위를 넘어 과거를 통째로 바꾸지 않는다."""
            out = {}
            for fill in 덮기:
                if fill["범위"] == "이번만" and fill.get("사건") == 이름표:
                    out[fill["역할"]] = fill["값"]
                elif (fill["범위"] == "앞으로" and fill.get("동사") == stem
                      and at >= fill.get("부터", 0)):
                    out[fill["역할"]] = fill["값"]
                elif fill["범위"] == "설명정정" and fill.get("동사") == stem:
                    out[fill["역할"]] = fill["값"]
            return out
        happened, 차례표, event_ordinal = [], {}, {}
        for index, parsed in enumerate(read):
            for event in parsed.get("사건", []):
                stem = ReasoningContext._lookup(parser, event, stems, table)
                key = (index, stem, json.dumps(sorted(event["자리"].items()),
                                               ensure_ascii=False))
                차례 = 차례표.get(key, 0)
                차례표[key] = 차례 + 1
                ordinal = event_ordinal.get(index, 0)
                event_ordinal[index] = ordinal + 1
                slot = "%d:%d" % (index, ordinal)
                # A new context allocates an id at the first observation and
                # keeps it when correction changes roles.  ``None`` is the
                # compatibility mode for v1-v9 snapshots whose fills point
                # to the original content-addressed identifier.
                이름표 = (ReasoningContext._event_id(index, stem, event["자리"], 차례)
                         if event_ids is None else event_ids.setdefault(slot, "event:%s" % slot))
                rule = rule_for(stem, index) if stem else None
                if rule is None or event.get("polarity") is False:
                    continue        # 뜻을 모르거나, 안 한 일이다
                받은값, 덮을값 = 채움.get(이름표, {}), 덮을것(이름표, stem, index)
                보완값, 보완사실 = 조회값.get(이름표, {}), 조회사실.get(이름표, [])
                from marco.reasoning.actions import event_record
                # The evidence attached to each emitted fact is an immutable
                # action envelope.  It makes a replayed fact distinguishable
                # from a direct assertion and preserves definition version,
                # role fills, polarity/modality, order and source together.
                event = {**event, "실행": event_record(
                    이름표, rule["프로그램"], event, sequence=index,
                    evidence=event.get("evidence"), fills=받은값, overrides=덮을값,
                    state_fills=보완사실, conditions=parsed.get("조건", []))}
                happened.append((index, stem, event, rule, 이름표, 받은값, 덮을값,
                                 보완값, 보완사실))

        # 이 대화가 이름으로 아는 것들. 어느 자름이 옳은지 가르는 증거다.
        이름 = set()
        for parsed in read:
            for item in parsed["facts"]:
                subject = str(item["triple"][0])
                이름.add(subject)
                이름.update(subject.split())
        facts, pending = [], []
        for index, (parsed, source) in enumerate(zip(read, sources)):
            # 한 말 안에서도 **적힌 차례**를 지킨다. 사건을 사실보다 먼저 놓으면
            # `민수 구슬은 8개 있다. 지연에게 베풀었다` 에서 덜어내기가 처음 수량
            # 보다 앞서고, 처음 수량이 없다며 통째로 막힌다.
            rows, 조건들 = [], parsed.get("조건", [])
            인증 = _scoped_guard_ids(parser, 조건들, projection, source)
            미정 = False
            for at, stem, event, rule, 이름표, 받은값, 덮을값, 보완값, 보완사실 in happened:
                if at != index:
                    continue
                # One program execution performs role binding, state lookup,
                # calculation and emission.  It sees only earlier facts, so a
                # definition cannot read a value that its own later effect
                # creates.
                applied = ReasoningContext._triples(
                    parser, rule, event, 이름, 받은값, 덮을값,
                    facts + [row for _start, row in rows], programs_for(rule),
                    조회값=보완값, 조회사실=보완사실)
                잰것, 못잼 = applied["사실"], applied.get("못잼")
                if (applied["빈자리"] or applied["충돌"] or applied["헛자리"]
                        or event.get("잘림") or 못잼):
                    pending.append({"text": source, "at": index, "동사": stem,
                                    "id": 이름표, "잘림": bool(event.get("잘림")),
                                    "차례": at, "못잼": 못잼,
                                    "거짓조건": 못잼 == "condition_false",
                                    "조각": event["evidence"], "자리": dict(event["자리"]),
                                    "빈자리": applied["빈자리"], "충돌": applied["충돌"],
                                    "헛자리": applied["헛자리"], "닿는곳": applied["닿는곳"],
                                    "필요": applied.get("필요"),
                                    "실행": event["실행"]})
                    continue
                # 앞절이 조건이면 **재고 나서** 적용한다. 조건이 거짓이면 아무
                # 값도 안 바뀐 것이고(그건 아는 것이다), 조건을 못 재면 바뀌었는지
                # 자체를 모르는 것이다 — 뒤쪽은 보류로 넘겨 옛 값을 확정하지 못하게 한다.
                참 = ReasoningContext._holds(parser, 조건들, event["evidence"].get("start", 0),
                                            facts + [row for _start, row in rows], projection,
                                            actual_source=source)
                if 참 is None:
                    pending.append({"text": source, "at": index, "동사": stem,
                                    "id": 이름표, "잘림": bool(event.get("잘림")),
                                    "차례": at, "못잼": "조건",
                                    "조각": event["evidence"], "자리": dict(event["자리"]),
                                    "빈자리": applied["빈자리"], "충돌": applied["충돌"],
                                    "헛자리": applied["헛자리"], "닿는곳": applied["닿는곳"],
                                    "실행": event["실행"]})
                    continue
                if 참 is False:
                    continue
                # 아직 안 일어난 일은 **사실이 아니다.** 기록으로만 남기고 상태를
                # 안 바꾼다 — `current_facts` 가 비실제 관찰로 적어 둔다.
                갈래 = {"modality": event["modality"]} if event.get("modality") else {}
                rows += [(event["evidence"].get("start", 0),
                          {"triple": triple, **갈래,
                           "evidence": {**event["evidence"], "turn": index, "source": source,
                                        "action_event": event["실행"]}})
                         for triple in 잰것]
            for item in parsed["facts"]:
                # 조건 뒤에 적힌 것이 사건이 아니라 값일 수도 있다. 같은 시험을
                # 거치지 않으면 `…면 3개다` 가 조건과 상관없이 못 박힌다.
                참 = ReasoningContext._holds(parser, 조건들, item["evidence"].get("start", 0),
                                            facts + [row for _start, row in rows], projection,
                                            actual_source=source)
                if 참 is None and 인증:
                    미정 = True
                if 참 is not True:
                    continue
                item = deepcopy(item)
                item["evidence"].update(turn=index, source=source)
                rows.append((item["evidence"].get("start", 0), item))
            # 조건을 적었는데 **잴 수 없거나 걸릴 데가 없으면** 아직 못 다룬 말이다.
            # 조용히 버리면 뒤 물음이 옛 값을 그대로 확정한다 — `줬으면` 처럼 앞절이
            # 견주기가 아니라 **사건**인 가정이 바로 여기 걸린다. 못 다룬 것을
            # 변화 없음으로 접지 않으려고, 그 조건이 건드릴 값을 확정하지 못하게 남긴다.
            표 = parser.data.get("comparisons", {})
            가정근거 = {(item["evidence"].get("start"), item["evidence"].get("end"),
                        tuple(item["triple"])) for item in parsed.get("가정", [])}
            def 가정인가(item):
                return (item["evidence"].get("start"), item["evidence"].get("end"),
                        tuple(item["triple"])) in 가정근거
            # 물음 속 가정은 여기의 실제 상태를 막지 않는다. 그 물음에 답할 때만
            # 아래 `turn`에서 임시 투영한다. 그렇지 않으면 가정도 실제 조건도
            # 같은 보류가 되어, 계산 가능한 가정을 버리게 된다.
            못잴조건 = [c for c in 조건들 if not 가정인가(c)
                        and c["triple"][1] not in 표 and id(c) not in 인증]
            걸린수 = sum(1 for 하나 in happened if 하나[0] == index) + len(parsed["facts"])
            실제조건 = [c for c in 조건들 if not 가정인가(c)]
            if 실제조건 and (못잴조건 or not 걸린수 or 미정):
                pending.append({"text": source, "at": index, "동사": None,
                                "id": None, "잘림": False, "차례": index,
                                "못잼": "조건" if (못잴조건 or not 걸린수) else "condition_unknown",
                                "조각": 조건들[0]["evidence"],
                                "자리": {}, "빈자리": {}, "충돌": {}, "헛자리": {},
                                "닿는곳": [c["triple"] for c in 조건들]})
            facts += [row for _start, row in sorted(rows, key=lambda row: row[0])]
        # Keep the compiled program as well as its name.  Query-time
        # hypothetical execution needs the identical definition version that
        # a real event would use; a bare set of stems cannot provide that.
        latest = {stem: rows[-1][1] for stem, rows in timeline.items()}
        versions = {"%s@%s" % (stem, at): candidate["프로그램"]
                    for stem, rows in timeline.items() for at, candidate in rows}
        return facts, DefinitionTable(latest, versions), pending, 읽힌몸통

    @staticmethod
    def _bind_unnamed_counts(parser, facts, rows, hints=()):
        """A count said without its holder is the count of the one count not known yet it fits.

        ``Haru has some marbles`` records a count not known (count_unknown). A later count with no
        holder (``12 of them``: no subject), with the thing alone (``it's 12 marbles``) or with the
        holder alone (``Haru has 12 of them``) is bound to the open count not known that it fits:
        the latest one when nothing is named, else the only one whose subject has the word named.
        Nothing is bound when no open one fits or two fit.
        """
        targets = {spec["target"] for spec in (parser.data.get("numeric_updates") or {}).values()
                   if isinstance(spec, dict)}
        out = []
        for row in rows:
            triple = row.get("triple") or [None, None, None]
            if triple[1] in targets and not row.get("resolve"):
                seen = facts + out
                known = {str(f["triple"][0]) for f in seen if f["triple"][1] in targets}
                open_ = []
                for f in seen:
                    if f["triple"][1] == "count_unknown" and isinstance(f["triple"][0], str):
                        name = f["triple"][0]
                        if name not in open_ and name not in known:
                            open_.append(name)
                subject = triple[0]
                hinted = [name for at, name in hints if at == (row.get("evidence") or {}).get("turn") and name in open_]
                if hinted and (subject is None or (isinstance(subject, str) and subject not in known
                                                   and any(w in hinted[0].split() for w in subject.split()))):
                    open_ = hinted[:1]
                if subject is None and not open_:
                    # No count is open: an amount said again without its holder in the same statement
                    # (정확히는 아홉 자루라고 다시 말할 때) is the count stated just before it in that statement.
                    turn = (row.get("evidence") or {}).get("turn")
                    same = [f for f in seen if (f.get("evidence") or {}).get("turn") == turn
                            and f["triple"][1] in targets and isinstance(f["triple"][0], str)]
                    fits = [same[-1]["triple"][0]] if same and str(same[-1]["triple"][2]) == str(triple[2]) else []
                elif subject is None:
                    fits = open_[-1:]
                elif isinstance(subject, str) and subject not in known and len(subject.split()) == 1:
                    fits = [name for name in open_ if subject in name.split()]
                else:
                    fits = []
                if len(fits) == 1:
                    # the statement that opened the count names its holder: an explanation cites it (G5)
                    opener = next((f for f in seen if f["triple"][0] == fits[0]
                                   and f["triple"][1] == "count_unknown"), None)
                    named_in = ((opener or {}).get("evidence") or {})
                    named_in = named_in.get("source") or named_in.get("text")
                    row = {**row, "triple": [fits[0]] + list(triple[1:]),
                           "evidence": {**row["evidence"], "bound": {"from": subject, "to": fits[0],
                                                                     **({"named_in": named_in} if named_in else {})}}}
            out.append(row)
        return out

    def correct(self, index, replacement, knowledge_path=None, reading=None):
        """Replace one identified observation atomically, then replay all events.

        A correction is not a new event appended to the current quantity. Later
        observations retain their ordering and derived conclusions are rebuilt.
        """
        if not self._permitted(knowledge_path):
            raise ValueError("operator_not_declared_in_kg")
        if type(index) is not int or not 0 <= index < len(self.observations):
            raise ValueError("unknown_correction_target")
        if len(self.corrections) >= self.max_turns:
            raise ValueError("correction_capacity")
        parser = self._parser()
        parsed = reading
        if parsed is None:
            parsed = parser.parse(replacement, partial=True, events=True, repair=True)
        # 정정 대상은 초기 사실만이 아니다. 배운 뜻풀이와 조건은 뒤 사건의
        # 해석·발생 여부를 바꾸므로, 같은 원문 자리에서 교체하고 이후 근거를
        # 다시 검증한다. 물음이나 빈 말은 관찰을 대체할 수 없다.
        if (not parsed or parsed["query"] or not (parsed["facts"] or parsed.get("정의")
                                                   or parsed.get("사건") or parsed.get("조건"))):
            raise ValueError("correction_requires_observation")
        # The committed revision needs one more ledger version; refuse before any trial state exists.
        slot = self.reading_ledger.get(self.observations[index].oid)
        if slot is not None and sum(len(e["versions"]) for e in self.reading_ledger.values()) >= self.max_turns * 8:
            raise ValueError("reading_capacity")
        before_facts, _defined, _unsettled, _read = self._cached_replay(
            parser, self.observations, self.fills)
        before_state, _before_changes = current_facts(
            before_facts, parser.data.get("mutable_predicates", []),
            parser.data.get("numeric_updates", {}))
        pending = list(self.observations)
        before = pending[index]
        # Same slot, next reading revision (also when the text is unchanged): only this slot is re-read;
        # every other archived interpretation is kept.  The new reading is visible to the trial replay
        # only for this identity and is withdrawn if the replay fails.
        pending[index] = Obs(str(replacement), before.oid, before.rev + 1, parsed, "correction")
        view = parser.__dict__.setdefault("chosen_readings", {})
        programs = parser.__dict__.setdefault("chosen_programs", {})
        saved = {"view": dict(view), "programs": dict(programs),
                 "ledger": deepcopy(getattr(self, "reading_ledger", None)),
                 "next": getattr(self, "_next_observation", None),
                 "event_ids": deepcopy(self.event_ids),
                 "event_revisions": list(self.event_revisions),
                 "scope": getattr(self, "_last_replay_scope", None),
                 "verb": getattr(self, "_verb_cache", None),
                 "obs": list(self._obs), "corrections": list(self.corrections)}
        view[before.oid] = deepcopy(parsed)
        try:
            facts, _defined, _unsettled, _읽힘 = self._cached_replay(parser, pending, self.fills)
            after_state, changes = current_facts(facts, parser.data.get("mutable_predicates", []),
                                                 parser.data.get("numeric_updates", {}))
            self.observations = pending
        except BaseException:
            self._obs = saved["obs"]
            self.corrections[:] = saved["corrections"]
            view.clear()
            view.update(saved["view"])
            programs.clear()
            programs.update(saved["programs"])
            self.reading_ledger, self._next_observation = saved["ledger"], saved["next"]
            self.event_ids, self.event_revisions = saved["event_ids"], saved["event_revisions"]
            self._last_replay_scope, self._verb_cache = saved["scope"], saved["verb"]
            # the failed trial's revision is never reusable: drop the cache, which the original sources re-fill
            self._replay_cache = None
            raise
        before_values = {(row["triple"][0], row["triple"][1]): row["triple"][2]
                         for row in before_state}
        after_values = {(row["triple"][0], row["triple"][1]): row["triple"][2]
                        for row in after_state}
        affected = {key for key in set(before_values) | set(after_values)
                    if before_values.get(key) != after_values.get(key)}
        # 재생은 정의·조건의 시점 의미를 보존하려 전체로 할 수 있지만, 교정 결과
        # 밖으로는 실제로 달라진 대상·관계 전이만 낸다. 무관한 상태가 “갱신됐다”는
        # 인상을 주지 않으며, 원문 전체와 재생 근거는 그대로 남는다.
        changes = [change for change in changes
                   if (change.get("subject"), change.get("predicate")) in affected]
        record = {"index": index, "before": before, "after": replacement}
        self.corrections.append(record)
        # The observation slot is stable.  Keep an append-only revision link
        # for every event originally introduced by that input instead of
        # inventing a replacement event id after reparsing the correction.
        if self.event_ids is not None:
            for slot, event_id in self.event_ids.items():
                if slot.startswith("%d:" % index):
                    self.event_revisions.append({"event_id": event_id, "index": index,
                                                 "before": before, "after": replacement,
                                                 "kind": "correction"})
        return {"operator": "relational_graph", "status": "observed",
                "answer": parser.data["context_replies"].get("corrected", parser.data["context_replies"]["observed"]),
                "meaning": {"act": "revise", "index": index, "before": before, "after": replacement,
                            "changes": deepcopy(changes)},
                "transitions": [{"operation": "correction", **record}] + changes,
                "verification": self._verification(knowledge_path, [
                    {"ok": True, "observation_turns": len(pending),
                     "affected_state": [list(key) for key in sorted(affected)]}])}

    def _capture_current_query_read(self, text, parser, current):
        carrier = None
        try:
            import hashlib, json, math
            carrier = self.__dict__.get("_current_query_read")
            if not isinstance(carrier, dict) or set(carrier) != {"source", "calls", "parser", "value", "gap"}:
                carrier = None
                return
            calls = carrier["calls"]
            if type(calls) is not int or calls < 0:
                carrier.update(parser=None, value=None, gap="current_read_carrier_invalid")
                return
            carrier["calls"] = calls + 1
            if calls + 1 > 1 or carrier["value"] is not None or carrier["parser"] is not None:
                carrier.update(parser=None, value=None, gap="current_read_nested")
                return
            if (carrier["source"] is not text or not isinstance(text, str) or _readings.oid_of(text) != TENTATIVE
                    or TENTATIVE in (getattr(parser, "chosen_readings", None) or {})
                    or self.__dict__.get("_rereading") is True):
                carrier.update(parser=None, value=None, gap="current_read_source_mismatch")
                return

            def index_ok(x, allow_none=False):
                return (x is None and allow_none) or (type(x) is int and x >= 0)

            def detach(obj, depth=0):
                if depth > 32:
                    raise ValueError("depth")
                if obj is None or type(obj) in (bool, int, str):
                    return obj
                if type(obj) is float:
                    if not math.isfinite(obj):
                        raise ValueError("nonfinite")
                    return obj
                if type(obj) is list:
                    return [detach(item, depth + 1) for item in obj]
                if type(obj) is dict:
                    if any(type(key) is not str for key in obj):
                        raise ValueError("key")
                    return {key: detach(item, depth + 1) for key, item in obj.items()}
                raise ValueError("type")
            advanced = ("definitions", "events", "condition", "assumption", "reason", "correction", "repair",
                        "정의", "사건", "가정사건", "조건", "가정", "원인", "이유물음", "수선", "사건정정")
            query = current.get("query") if isinstance(current, dict) else None
            if (not isinstance(current, dict) or current.get("facts") != []
                    or any(current.get(key) not in (None, [], {}, "") for key in advanced)
                    or not isinstance(query, list) or len(query) != 1 or not isinstance(query[0], dict)
                    or set(query[0]) != {"triple", "render"}):
                carrier["gap"] = "unsupported_query"
                return
            triple, render = query[0]["triple"], query[0]["render"]
            if (not isinstance(triple, list) or len(triple) != 3
                    or any(type(x) is not str or not x for x in triple)
                    or not isinstance(render, list) or not render
                    or any(type(x) is not str for x in render)
                    or triple[1].startswith(("$", "?"))):
                carrier["gap"] = "unsupported_query"
                return
            asked = [i for i in (0, 2) if triple[i].startswith("?")]
            if (len(asked) != 1 or len(triple[asked[0]]) < 2
                    or triple[2 - asked[0]].startswith(("$", "?"))):
                carrier["gap"] = "unsupported_query"
                return
            selection = current.get("entry_selection")
            if (not isinstance(selection, dict)
                    or set(selection) != {"schema", "scope", "status", "coordinate_space", "items", "gaps"}
                    or selection["schema"] != "marco-entry-selection-v1"
                    or selection["scope"] != "known_selected_input_clauses"
                    or selection["status"] != "partial" or selection["coordinate_space"] != "parser_view"
                    or not isinstance(selection["items"], list) or not isinstance(selection["gaps"], list)):
                carrier["gap"] = "native_selection_unavailable"
                return
            if len(selection["gaps"]) > 64:
                carrier["gap"] = "native_selection_overflow"
                return
            for gap in selection["gaps"]:
                if (not isinstance(gap, dict) or set(gap) != {"clause_ordinal", "code"}
                        or not index_ok(gap["clause_ordinal"], allow_none=True)
                        or type(gap["code"]) is not str or not gap["code"].strip()):
                    carrier["gap"] = "native_selection_invalid"
                    return
            items = selection["items"]
            if len(items) != 1 or not isinstance(items[0], dict) or set(items[0]) != {
                    "clause_ordinal", "span", "compiler_index", "origin", "targets", "derivation"}:
                carrier["gap"] = "native_selection_invalid"
                return
            item = items[0]
            span, targets = item["span"], item["targets"]
            if (item["clause_ordinal"] != 0 or type(item["clause_ordinal"]) is not int
                    or not index_ok(item["compiler_index"], allow_none=True)
                    or item["origin"] is not None and not isinstance(item["origin"], dict)
                    or item["derivation"] is not None
                    or not isinstance(targets, dict) or set(targets) != {"facts", "query"}
                    or targets["facts"] != [] or not isinstance(targets["query"], list)
                    or len(targets["query"]) != 1 or type(targets["query"][0]) is not int
                    or targets["query"][0] != 0
                    or not isinstance(span, list) or len(span) != 2
                    or not all(type(x) is int for x in span)
                    or not 0 <= span[0] < span[1] <= len(text)):
                carrier["gap"] = "native_selection_invalid"
                return
            unaligned = ("relative_source_offset_unproven", "filler_source_offset_unproven",
                         "derivation_unavailable", "uncollected_scope", "uncollected_index")
            native_codes = [gap["code"] for gap in selection["gaps"] if gap["code"] in unaligned]
            if item["compiler_index"] is None and not any(
                    gap["code"] == "uncollected_index" and gap["clause_ordinal"] == 0
                    for gap in selection["gaps"]):
                carrier["gap"] = "native_selection_invalid"
                return
            cached = self.__dict__.get("_grammar_cache")
            grammar = cached[1] if isinstance(cached, tuple) and len(cached) == 2 else None
            if (cached is None or cached[0] is not parser or type(grammar) is not str
                    or len(grammar) != 64 or any(c not in "0123456789abcdef" for c in grammar)):
                carrier["gap"] = "grammar_cache_unavailable"
                return
            value = detach({"text_sha256": hashlib.sha256(str.encode(text, "utf-8")).hexdigest(),
                            "parser_base_sha256": getattr(self, "parser_base_sha256", None),
                            "parser_grammar_sha256": grammar,
                            "installed_memory_head": getattr(self, "installed_memory_head", None),
                            "query": query, "entry_selection": selection})
            encoded = json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
            if len(encoded) > 65536:
                carrier["gap"] = "value_overflow"
                return
            if native_codes:
                # Passive transport only: the bounded native selection/gaps travel intact and
                # Session rejects admission locally; a single native code is exposed unrewritten.
                carrier.update(parser=parser, value=value,
                               gap=native_codes[0] if len(native_codes) == 1 else "native_alignment_unproven")
                return
            carrier.update(parser=parser, value=value)
        except Exception:
            try:
                if isinstance(carrier, dict):
                    carrier.update(parser=None, value=None, gap="capture_failed")
            except Exception:
                pass
    _UNREAD_JSON_BOUNDS = (4096, 32)
    _UNREAD_FRAME_FIELDS = ("source", "calls", "parser", "current", "model", "nested", "gap",
                            "pending_witness")
    _UNREAD_PENDING_TEXT_BYTES = 8192
    _UNREAD_PENDING_SCHEMA_V2 = "graph-unread-continuation-policy-v2"

    def _unread_pending_sha(self, value):
        """Hex SHA-256 of canonical JSON, or None when the value is not plain/bounded JSON."""
        import hashlib
        text = self._unread_json(value, 65536)
        if text is None:
            return None
        try:
            encoded = text.encode("utf-8")
        except UnicodeEncodeError:
            return None
        return hashlib.sha256(encoded).hexdigest()

    def _unread_pending_shape(self, entry):
        """Classify one native pending entry by exact shape; returns (kind, metadata) or None.

        Only ``{text, at}`` and ``{text, at, 말, 꼬리}`` plain dicts qualify.  No parsing, no
        evidence admission: control text that stays unresolved is simply kind ``text``.
        """
        if type(entry) is not dict:
            return None
        keys = set(entry)
        if keys == {"text", "at"}:
            kind = "text"
        elif keys == {"text", "at", "말", "꼬리"}:
            kind = "unknown_word"
        else:
            return None
        text, at = entry["text"], entry["at"]
        if not isinstance(text, str) or not str(text).strip():
            return None
        try:
            if len(str(text).encode("utf-8")) > self._UNREAD_PENDING_TEXT_BYTES:
                return None
        except UnicodeEncodeError:
            return None
        count = len(self._obs)
        if type(at) is not int or at < 0 or at > count:
            return None
        meta = {"kind": kind, "at": at, "text": str(text)}
        if kind == "unknown_word":
            word, tail = entry["말"], entry["꼬리"]
            if at >= count or type(word) is not str or not word.strip() or type(tail) is not str:
                return None
            meta["말"], meta["꼬리"] = word, tail
        return kind, meta

    def _unread_pending_unknown_binding(self, meta):
        """Bind an unknown-word entry to its actual archived reading; None when anything is off."""
        source = self._obs[meta["at"]]
        if not isinstance(source, Obs):
            return None
        oid = _readings.oid_of(source)
        if type(oid) is not str or not oid.strip() or oid == TENTATIVE:
            return None
        held = self.reading_ledger.get(oid)
        record = self._active_record(source)
        if type(held) is not dict or type(record) is not dict:
            return None
        revision = record.get("reading_revision")
        archived = record.get("source")
        parsed = record.get("parsed")
        source_rev = getattr(source, "rev", None)
        if type(revision) is not int or revision < 1 or revision != held.get("active") \
                or type(source_rev) is not int or source_rev != revision \
                or type(record.get("observation_id")) is not str or record.get("observation_id") != oid:
            return None
        if record.get("unavailable") or not isinstance(archived, str) or str(archived).strip() != meta["text"]:
            return None
        if type(parsed) is not dict or not isinstance(parsed.get("사건"), list):
            return None
        matches = [event for event in parsed["사건"] if type(event) is dict
                   and event.get("verb") == meta["말"] and event.get("꼬리", "") == meta["꼬리"]]
        if len(matches) != 1:
            return None
        record_sha256 = self._unread_pending_sha(record)
        if record_sha256 is None:
            return None
        return {"source": source, "record": record, "archived": archived,
                "public": {"observation_id": oid, "reading_revision": revision,
                           "record_sha256": record_sha256}}

    def _unread_pending_v2(self, max_pending):
        """Pure witness of every actual pending entry, or None.  Private refs are never public."""
        pending = getattr(self, "unread", None)
        if type(max_pending) is not int or not 1 <= max_pending <= 8:
            return None
        if getattr(self, "unread_guard", None) or not isinstance(pending, list):
            return None
        if not 1 <= len(pending) <= max_pending:
            return None
        import hashlib
        refs, public, total = [], [], 0
        for index, entry in enumerate(pending):
            shape = self._unread_pending_shape(entry)
            if shape is None:
                return None
            kind, meta = shape
            try:
                text_bytes = meta["text"].encode("utf-8")
            except UnicodeEncodeError:
                return None
            # Joined-with-newline byte budget: separators count, kind is a separate descriptor.
            total += len(text_bytes) + (1 if index else 0)
            if total > self._UNREAD_PENDING_TEXT_BYTES:
                return None
            text_sha256 = hashlib.sha256(text_bytes).hexdigest()
            entry_sha256 = self._unread_pending_sha({key: meta[key] for key in meta if key != "kind"})
            if text_sha256 is None or entry_sha256 is None:
                return None
            item = {"unread_index": index, "kind": kind, "at": meta["at"], "text_sha256": text_sha256,
                    "entry_sha256": entry_sha256, "resolved": False}
            binding = None
            if kind == "unknown_word":
                binding = self._unread_pending_unknown_binding(meta)
                if binding is None:
                    return None
                item["archive"] = binding["public"]
            refs.append({"entry": entry, "text": entry["text"], "meta": meta, "binding": binding})
            public.append(item)
        set_sha256 = self._unread_pending_sha(public)
        if set_sha256 is None:
            return None
        return {"public": {"count": len(public), "max_pending": max_pending,
                           "set_sha256": set_sha256, "entries": public},
                "refs": refs}

    def _unread_pending_v2_same(self, witness):
        """True iff the actual pending set is still exactly the witnessed one.  No mutations."""
        if type(witness) is not dict or set(witness) != {"public", "refs"}:
            return False
        public, refs = witness["public"], witness["refs"]
        if type(public) is not dict or not isinstance(refs, list):
            return False
        current = self._unread_pending_v2(public.get("max_pending"))
        if current is None or not self._unread_native_equal(current["public"], public) \
                or len(current["refs"]) != len(refs):
            return False
        for old, new in zip(refs, current["refs"]):
            if type(old) is not dict or old.get("entry") is not new["entry"] or old.get("text") is not new["text"]:
                return False
            if not self._unread_native_equal(old.get("meta"), new["meta"]):
                return False
            held, binding = old.get("binding"), new["binding"]
            if (held is None) != (binding is None):
                return False
            if binding is not None and (type(held) is not dict
                                        or held.get("source") is not binding["source"]
                                        or held.get("record") is not binding["record"]
                                        or held.get("archived") is not binding["archived"]
                                        or not self._unread_native_equal(held.get("public"), binding["public"])):
                return False
        return True
    _UNREAD_FRAME_ATTR = "_unread_continuation_frame"

    @staticmethod
    def _unread_json(value, max_bytes):
        """Canonical finite plain JSON of ``value`` or None.

        Plain JSON only: dict with str keys, list, str, bool, int, finite float, None.  Primitive
        identity is exact (a bool is not an int, a subclass is not its base).  Node budget 4096,
        depth 32, and the caller's UTF-8 byte bound are all enforced; any refusal is None.
        """
        if type(max_bytes) is not int or max_bytes <= 0:
            return None
        node_budget, max_depth = ReasoningContext._UNREAD_JSON_BOUNDS
        nodes = 0
        stack = [(value, 1)]
        while stack:
            node, depth = stack.pop()
            nodes += 1
            if nodes > node_budget or depth > max_depth:
                return None
            kind = type(node)
            if node is None or kind is bool or kind is int or kind is str:
                continue
            if kind is float:
                if node != node or node in (float("inf"), float("-inf")):
                    return None
                continue
            if kind is list:
                stack.extend((item, depth + 1) for item in node)
                continue
            if kind is dict:
                for key, item in node.items():
                    if type(key) is not str:
                        return None
                    stack.append((item, depth + 1))
                continue
            return None
        try:
            rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                                  allow_nan=False)
        except (TypeError, ValueError):
            return None
        try:
            encoded = rendered.encode("utf-8")
        except UnicodeEncodeError:
            return None
        if len(encoded) > max_bytes:
            return None
        return rendered

    @staticmethod
    def _unread_native_equal(left, right):
        """Structural equality of two plain JSON values with exact primitive identity.

        Types must match exactly at every node (bool/int distinguished, str subclasses distinguished
        from str).  Floats must be finite.  Depth and node budgets match ``_unread_json``; exceeding
        either, or meeting a non-JSON node, is False rather than an exception.
        """
        node_budget, max_depth = ReasoningContext._UNREAD_JSON_BOUNDS
        nodes = 0
        stack = [(left, right, 1)]
        while stack:
            a, b, depth = stack.pop()
            nodes += 1
            if nodes > node_budget or depth > max_depth:
                return False
            kind = type(a)
            if kind is not type(b):
                return False
            if a is None:
                continue
            if kind is bool or kind is int or kind is str:
                if a != b:
                    return False
                continue
            if kind is float:
                if a != a or b != b or a in (float("inf"), float("-inf")) or a != b:
                    return False
                continue
            if kind is list:
                if len(a) != len(b):
                    return False
                stack.extend((x, y, depth + 1) for x, y in zip(a, b))
                continue
            if kind is dict:
                if len(a) != len(b):
                    return False
                for key in b:
                    if type(key) is not str:
                        return False
                for key, item in a.items():
                    if type(key) is not str or key not in b:
                        return False
                    stack.append((item, b[key], depth + 1))
                continue
            return False
        return True

    def _unread_continuation_enter(self, text, previous):
        """Open the ephemeral frame for one turn; returns the new frame dict (never installs it).

        ``text`` must be the actual tentative ``Obs`` the turn made; the reference is retained, not
        copied.  ``previous`` is whatever frame was active before (None when none).  An active
        previous frame means a nested turn: both it and the new frame are marked nested and carry a
        gap, so neither is eligible.  A frame opened inside ``_name_reply`` is likewise ineligible.
        """
        frame = {"source": text, "calls": 0, "parser": None, "current": None, "model": None,
                 "nested": False, "gap": None, "pending_witness": None}
        projection = getattr(getattr(self, "model", None), "language_projection", None)
        projected = projection.get("data") if isinstance(projection, dict) else None
        policy = projected.get("unread_continuation") if isinstance(projected, dict) else None
        if (type(policy) is dict and policy.get("schema") == self._UNREAD_PENDING_SCHEMA_V2
                and type(policy.get("max_pending")) is int):
            # Captured before the current turn touches anything; v1 / no policy leaves None.
            frame["pending_witness"] = self._unread_pending_v2(policy["max_pending"])
        if not isinstance(text, Obs) or _readings.oid_of(text) != TENTATIVE:
            frame["gap"] = "input_owner_unavailable"
        if previous is not None:
            frame["nested"] = True
            if frame["gap"] is None:
                frame["gap"] = "input_scope_unsupported"
            if isinstance(previous, dict) and set(previous) == set(self._UNREAD_FRAME_FIELDS):
                previous["nested"] = True
                if previous["gap"] is None:
                    previous["gap"] = "input_scope_unsupported"
        if getattr(self, "_in_name_reply", False) and frame["gap"] is None:
            frame["gap"] = "input_scope_unsupported"
        return frame

    def _unread_continuation_read(self, text, parser, current):
        """Record the one actual ``_read_source`` of the turn into the active frame.

        Returns the frame (or None when no well-formed frame is active, a pure no-op).  The read
        count saturates at 2; only the first read captures, and it keeps the actual ``parser``,
        ``current`` and ``self.model`` references.  A second read, a source object that is not the
        frame's own, a parser other than the installed instance, a name reply or a nested frame
        sets a finite gap code and leaves any first capture untouched.  Nothing is parsed, copied
        or cached here.
        """
        frame = getattr(self, self._UNREAD_FRAME_ATTR, None)
        if not isinstance(frame, dict) or set(frame) != set(self._UNREAD_FRAME_FIELDS) \
                or type(frame["calls"]) is not int:
            return None
        first = frame["calls"] == 0
        frame["calls"] = min(frame["calls"] + 1, 2)
        if not first:
            if frame["gap"] is None:
                frame["gap"] = "input_scope_unsupported"
            return frame
        if text is not frame["source"] or parser is None \
                or parser is not getattr(self, "_parser_instance", None):
            if frame["gap"] is None:
                frame["gap"] = "input_owner_unavailable"
            return frame
        if frame["nested"] or getattr(self, "_in_name_reply", False) \
                or getattr(self, "_rereading", False):
            if frame["gap"] is None:
                frame["gap"] = "input_scope_unsupported"
            return frame
        frame["parser"], frame["current"], frame["model"] = parser, current, self.model
        return frame

    def _unread_continuation_start(self, text, current, parser, facts, unsettled, blocker, result, replies):
        """Stage B: guarded start of the known-support continuation; returns the private continuation or None.

        Called (by Stage C) right after the unchanged ``_blocked_by`` has produced ``blocker``.  With no
        selected graph policy this is an immediate no-op.  Every refusal is a finite code in the
        ephemeral ``frame["gap"]`` only; nothing else is touched and the original unread hold runs.  On
        success the saved exact native ``unread_event`` hold is kept for the later finish refusal.  No
        parsing, closure reconstruction, archive mutation, hook or answer call happens here.
        """
        from pack_model import PackModel
        model = self.model
        if type(model) is not PackModel:
            return None
        projection = model.language_projection
        if projection is None:
            return None
        projected = projection.get("data") if isinstance(projection, dict) else None
        policy = projected.get("unread_continuation") if isinstance(projected, dict) else None
        installed = parser.data.get("unread_continuation") if parser is not None \
            and isinstance(getattr(parser, "data", None), dict) else None
        if policy is None and installed is None:
            return None

        frame = getattr(self, self._UNREAD_FRAME_ATTR, None)
        well_formed = isinstance(frame, dict) and set(frame) == set(self._UNREAD_FRAME_FIELDS)

        max_text, max_canonical, hex_len = 8192, 65536, 64

        # ---- selected policy: identical in projection and actual parser ------------------------
        if policy is None or installed is None:
            if well_formed and frame["gap"] is None:
                frame["gap"] = "policy_unavailable"
            return None
        policy_fields = {"schema", "scope", "render", "source", "declaration_sha256"}
        policy_v2 = isinstance(policy, dict) and set(policy) == policy_fields | {"max_pending"}
        if not isinstance(policy, dict) or not (set(policy) == policy_fields or policy_v2):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "policy_invalid"
            return None
        max_pending = policy["max_pending"] if policy_v2 else None
        if policy_v2 and (type(max_pending) is not int or not 1 <= max_pending <= 8):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "policy_invalid"
            return None
        expected_schema = self._UNREAD_PENDING_SCHEMA_V2 if policy_v2 else "graph-unread-continuation-policy-v1"
        if policy["schema"] != expected_schema \
                or policy["scope"] != "direct_positive_immutable_binary" \
                or not (type(policy["declaration_sha256"]) is str and len(policy["declaration_sha256"]) == hex_len
                        and all(ch in "0123456789abcdef" for ch in policy["declaration_sha256"])):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "policy_invalid"
            return None
        render = policy["render"]
        if type(render) is not str or not render.strip() or len(render) > 1024:
            if well_formed and frame["gap"] is None:
                frame["gap"] = "policy_invalid"
            return None
        try:
            render_bytes = len(render.encode("utf-8"))
        except UnicodeEncodeError:
            render_bytes = None
        if (render_bytes or 4097) > 4096:
            if well_formed and frame["gap"] is None:
                frame["gap"] = "policy_invalid"
            return None
        capsule = policy["source"]
        if not isinstance(capsule, dict) or set(capsule) != {"graph_id", "root_id", "rule_id", "sense_id",
                                                             "effective_graph_sha256", "view_key", "nodes",
                                                             "edges"}:
            if well_formed and frame["gap"] is None:
                frame["gap"] = "policy_invalid"
            return None
        view_key = capsule["view_key"]
        if not all(type(capsule[key]) is str and capsule[key].strip() for key in ("graph_id", "root_id", "rule_id")) \
                or capsule["sense_id"] is not None \
                or not (type(capsule["effective_graph_sha256"]) is str
                        and len(capsule["effective_graph_sha256"]) == hex_len
                        and all(ch in "0123456789abcdef" for ch in capsule["effective_graph_sha256"])) \
                or not isinstance(view_key, list) or len(view_key) != 2 \
                or type(view_key[0]) is not int or view_key[0] < 0 \
                or not (view_key[1] is None or (type(view_key[1]) is str and view_key[1].strip())) \
                or type(capsule["nodes"]) is not dict or len(capsule["nodes"]) > 512 \
                or type(capsule["edges"]) is not dict or len(capsule["edges"]) > 1024:
            if well_formed and frame["gap"] is None:
                frame["gap"] = "policy_invalid"
            return None
        provenance = projection.get("provenance")
        projection_fingerprint = projection.get("fingerprint")
        if projection.get("schema") != "graph-dialogue-projection-v1" or not isinstance(provenance, dict) \
                or any(not self._unread_native_equal(provenance.get(key), capsule[key])
                       for key in ("graph_id", "root_id", "effective_graph_sha256", "view_key")) \
                or not (type(projection_fingerprint) is str and len(projection_fingerprint) == hex_len
                        and all(ch in "0123456789abcdef" for ch in projection_fingerprint)):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "policy_invalid"
            return None
        declared_keys = ("schema", "scope", "render", "max_pending", "source") if policy_v2 \
            else ("schema", "scope", "render", "source")
        declaration_json = self._unread_json({key: policy[key] for key in declared_keys}, max_canonical)
        policy_json = self._unread_json(policy, max_canonical)
        if declaration_json is None or policy_json is None \
                or _sha(declaration_json) != policy["declaration_sha256"] \
                or not self._unread_native_equal(policy, installed):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "policy_invalid"
            return None

        # ---- ephemeral frame ownership ----------------------------------------------------------
        if not well_formed:
            return None
        if frame["gap"] is not None:
            return None
        if frame["source"] is not text or not isinstance(text, Obs) or _readings.oid_of(text) != TENTATIVE:
            if well_formed and frame["gap"] is None:
                frame["gap"] = "input_owner_unavailable"
            return None
        if frame["nested"] is not False or type(frame["calls"]) is not int or frame["calls"] != 1 \
                or getattr(self, "_in_name_reply", False) or getattr(self, "_rereading", False):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "input_scope_unsupported"
            return None
        if frame["parser"] is None or frame["parser"] is not parser \
                or parser is not getattr(self, "_parser_instance", None) \
                or frame["model"] is not model or frame["current"] is not current:
            if well_formed and frame["gap"] is None:
                frame["gap"] = "input_owner_unavailable"
            return None

        # ---- grammar cache / head chronology of the current parser -------------------------------
        cache = getattr(self, "_grammar_cache", None)
        if type(cache) is not tuple or len(cache) != 2 or cache[0] is not parser:
            if well_formed and frame["gap"] is None:
                frame["gap"] = "support_identity_mismatch"
            return None
        current_grammar = cache[1]
        current_base = self.parser_base_sha256
        current_head = self.installed_memory_head
        conversation_id = getattr(self, "conversation_id", None)
        model_content = getattr(model, "content_fingerprint", None)
        model_effective = getattr(model, "effective_key", None)
        if not all(type(item) is str and len(item) == hex_len and all(ch in "0123456789abcdef" for ch in item)
                   for item in (current_grammar, current_base, model_content)) \
                or not (current_head is None or (type(current_head) is int and current_head >= 0)) \
                or type(conversation_id) is not str or not conversation_id.strip() \
                or type(model_effective) is not str or len(model_effective) != hex_len \
                or not all(ch in "0123456789abcdef" for ch in model_effective):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "support_identity_mismatch"
            return None

        # ---- the one actual blocker / pending record ---------------------------------------------
        if blocker is None or not isinstance(blocker, tuple) or len(blocker) != 2 or blocker[1] is not None:
            if well_formed and frame["gap"] is None:
                frame["gap"] = "pending_scope_unsupported"
            return None
        witness = frame["pending_witness"]
        pending_meta = None
        blocker_index = 0
        if policy_v2:
            if type(witness) is not dict or not self._unread_pending_v2_same(witness) \
                    or type(witness["public"]["max_pending"]) is not int \
                    or witness["public"]["max_pending"] != policy["max_pending"] \
                    or not isinstance(self.unread, list) or len(witness["refs"]) != len(self.unread):
                if well_formed and frame["gap"] is None:
                    frame["gap"] = "pending_scope_unsupported"
                return None
            hits = [index for index, ref in enumerate(witness["refs"]) if ref["text"] is blocker[0]]
            if len(hits) != 1:
                if well_formed and frame["gap"] is None:
                    frame["gap"] = "pending_scope_unsupported"
                return None
            blocker_index = hits[0]
            ref = witness["refs"][blocker_index]
            entry = ref["entry"]
            if entry is not self.unread[blocker_index] or type(entry) is not dict \
                    or entry["text"] is not blocker[0] or type(ref["meta"]) is not dict:
                if well_formed and frame["gap"] is None:
                    frame["gap"] = "pending_scope_unsupported"
                return None
            pending_meta = {key: ref["meta"][key] for key in ref["meta"] if key != "kind"}
        else:
            if self.unread_guard or len(self.unread) != 1:
                if well_formed and frame["gap"] is None:
                    frame["gap"] = "pending_scope_unsupported"
                return None
            entry = self.unread[0]
            if not isinstance(entry, dict) or set(entry) != {"text", "at"} or entry["text"] is not blocker[0]:
                if well_formed and frame["gap"] is None:
                    frame["gap"] = "pending_scope_unsupported"
                return None
        at = entry["at"]
        if type(at) is not int or at < 0 or at > len(self.observations):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "pending_scope_unsupported"
            return None
        pending_text = str(entry["text"])
        try:
            pending_bytes = len(pending_text.encode("utf-8"))
        except UnicodeEncodeError:
            pending_bytes = None
        if pending_bytes is None or pending_bytes > max_text:
            if well_formed and frame["gap"] is None:
                frame["gap"] = "qualification_over_bound"
            return None

        # ---- one plain one-variable query --------------------------------------------------------
        if not isinstance(current, dict) or current.get("facts"):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "query_scope_unsupported"
            return None
        advanced = ("사건", "가정사건", "사건정정", "정의", "원인", "이유물음", "조건", "events", "definition",
                    "cause", "reason", "correction", "condition", "hypothesis", "가정", "수선")
        if any(current.get(key) for key in advanced):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "query_scope_unsupported"
            return None
        query = current.get("query")
        if not isinstance(query, list) or len(query) != 1 or not isinstance(query[0], dict) \
                or set(query[0]) != {"triple", "render"}:
            if well_formed and frame["gap"] is None:
                frame["gap"] = "query_scope_unsupported"
            return None
        triple, render_words = query[0]["triple"], query[0]["render"]
        if not isinstance(triple, (list, tuple)) or len(triple) != 3 \
                or not all(type(part) is str and part.strip() for part in triple) \
                or sum(part.startswith("?") for part in (triple[0], triple[2])) != 1 \
                or triple[1].startswith("?") or any("$" in part for part in triple) \
                or (isinstance(triple[0], str) and re.fullmatch(r"[+-]?\d+(\.\d+)?", triple[0].strip()) is not None) \
                or (isinstance(triple[2], str) and re.fullmatch(r"[+-]?\d+(\.\d+)?", triple[2].strip()) is not None) \
                or not isinstance(render_words, list) or not render_words \
                or not all(type(item) is str for item in render_words):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "query_scope_unsupported"
            return None
        predicate = triple[1]
        grounded = triple[2] if triple[0].startswith("?") else triple[0]
        data = parser.data
        updates = data.get("numeric_updates") or {}
        excluded = set(data.get("mutable_predicates") or []) | set(updates) \
            | set(data.get("comparisons") or {}) \
            | {spec.get("target") for spec in updates.values() if isinstance(spec, dict)}
        if predicate in excluded:
            if well_formed and frame["gap"] is None:
                frame["gap"] = "query_scope_unsupported"
            return None
        words = grounded.split()
        speaker = getattr(parser, "speaker_placeholder", "")
        if speaker and (speaker in words or grounded == speaker):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "query_scope_unsupported"
            return None
        for pointer in getattr(parser, "pointers", []) or []:
            if not isinstance(pointer, str) or not pointer.strip():
                continue
            sequence = pointer.split()
            if any(words[i:i + len(sequence)] == sequence for i in range(len(words))):
                if well_formed and frame["gap"] is None:
                    frame["gap"] = "query_scope_unsupported"
                return None
        if frame["current"] is not current or not self._unread_native_equal(query, current.get("query")):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "query_scope_unsupported"
            return None
        question_text = str(text)
        try:
            question_bytes = len(question_text.encode("utf-8"))
        except UnicodeEncodeError:
            question_bytes = None
        render_json = self._unread_json(render_words, max_text)
        if question_bytes is None or question_bytes > max_text or render_json is None:
            if well_formed and frame["gap"] is None:
                frame["gap"] = "qualification_over_bound"
            return None

        # ---- exactly one direct positive asserted immutable support, no denial -------------------
        try:
            from . import inference as _inference
        except ImportError:
            from marco.reasoning import inference as _inference
        if not isinstance(facts, list) or len(facts) > 2048:
            if well_formed and frame["gap"] is None:
                frame["gap"] = "qualification_over_bound"
            return None
        support = None
        matched = 0
        for fact in facts:
            if not isinstance(fact, dict):
                continue
            row = fact.get("triple")
            if not isinstance(row, (list, tuple)) or len(row) != 3 \
                    or not all(type(part) is str for part in row):
                continue
            if _inference.bind(list(triple), list(row), {}) is None:
                continue
            matched += 1
            polarity = fact.get("polarity", True)
            if polarity is False:
                if well_formed and frame["gap"] is None:
                    frame["gap"] = "support_unavailable"
                return None
            if matched > 1:
                if well_formed and frame["gap"] is None:
                    frame["gap"] = "support_unavailable"
                return None
            support = fact
        if support is None:
            if well_formed and frame["gap"] is None:
                frame["gap"] = "support_unavailable"
            return None
        evidence = support.get("evidence")
        modality = support.get("modality", "asserted")
        if support.get("polarity", True) is not True or type(modality) is not str or modality != "asserted" \
                or support.get("unnamed") or any(key in support for key in ("at_least", "resolve", "bound")) \
                or not isinstance(evidence, dict) or "action_event" in evidence \
                or (type(evidence.get("mode")) is str and evidence.get("mode") == "hypothetical") \
                or any(key in evidence for key in ("at_least", "resolve", "unnamed", "bound", "derived", "rule")):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "support_unavailable"
            return None

        # ---- actual active archive ownership -----------------------------------------------------
        import hashlib
        turn_index = evidence.get("turn")
        source = evidence.get("source")
        if type(turn_index) is not int or turn_index < 0 or turn_index >= len(self.observations) \
                or not isinstance(source, Obs):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "support_identity_mismatch"
            return None
        oid = _readings.oid_of(source)
        source_rev = getattr(source, "rev", None)
        active_obs = self.observations[turn_index]
        if type(oid) is not str or not oid.strip() or oid == TENTATIVE \
                or type(source_rev) is not int or source_rev < 1 \
                or not isinstance(active_obs, Obs) \
                or type(_readings.oid_of(active_obs)) is not str or _readings.oid_of(active_obs) != oid \
                or type(getattr(active_obs, "rev", None)) is not int or active_obs.rev != source_rev \
                or str(active_obs) != str(source):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "support_identity_mismatch"
            return None
        ledger_entry = self.reading_ledger.get(oid)
        if not isinstance(ledger_entry, dict):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "support_unavailable"
            return None
        revision = ledger_entry.get("active")
        versions = ledger_entry.get("versions")
        if type(revision) is not int or revision < 1 or revision != source_rev or not isinstance(versions, list) \
                or len(versions) < revision or len(versions) > min(self.max_turns * 8, 2048):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "support_identity_mismatch"
            return None
        record = versions[revision - 1]
        if not isinstance(record, dict) or type(record.get("observation_id")) is not str \
                or record.get("observation_id") != oid \
                or type(record.get("reading_revision")) is not int or record.get("reading_revision") != revision \
                or type(record.get("source")) is not str or record.get("source") != str(source) \
                or record.get("unavailable") is not False \
                or not isinstance(record.get("parsed"), dict):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "support_identity_mismatch"
            return None
        if record.get("parser_base_sha256") != current_base \
                or not (type(record.get("parser_grammar_sha256")) is str
                        and len(record.get("parser_grammar_sha256")) == hex_len
                        and all(ch in "0123456789abcdef" for ch in record.get("parser_grammar_sha256"))):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "support_identity_mismatch"
            return None
        archived_head = record.get("installed_memory_head")
        if archived_head is not None:
            if type(archived_head) is not int or archived_head < 0 \
                    or current_head is None or archived_head > current_head:
                if well_formed and frame["gap"] is None:
                    frame["gap"] = "support_identity_mismatch"
                return None
        parsed = record["parsed"]
        archived_facts = parsed.get("facts")
        if not isinstance(archived_facts, list) \
                or (not 1 <= len(archived_facts) <= 2 if policy_v2 else len(archived_facts) != 1) \
                or parsed.get("query") is not None and (type(parsed.get("query")) is not list or parsed.get("query")) \
                or any(parsed.get(key) for key in advanced):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "support_unavailable"
            return None
        replay_view = {key: value for key, value in support.items() if key != "evidence"}
        replay_view["evidence"] = {key: value for key, value in evidence.items() if key not in ("turn", "source")}
        if policy_v2 and len(archived_facts) == 2 \
                and self._fact_batch_admissible(record["source"], record["parsed"], parser) is not True:
            if well_formed and frame["gap"] is None:
                frame["gap"] = "support_unavailable"
            return None
        archived_hits = [index for index, row in enumerate(archived_facts)
                         if isinstance(row, dict) and self._unread_native_equal(row, replay_view)]
        if len(archived_hits) != 1:
            if well_formed and frame["gap"] is None:
                frame["gap"] = "support_identity_mismatch"
            return None
        archived_fact_index = archived_hits[0]
        archived_fact = archived_facts[archived_fact_index]
        source_text = str(source)
        try:
            source_bytes = len(source_text.encode("utf-8"))
        except UnicodeEncodeError:
            source_bytes = None
        record_json = self._unread_json(record, max_canonical)
        fact_json = self._unread_json(archived_fact, max_text)
        evidence_json = self._unread_json(archived_fact.get("evidence"), max_text)
        entry_json = self._unread_json(pending_meta if pending_meta is not None
                                       else {"text": pending_text, "at": at}, max_text)
        if source_bytes is None or source_bytes > max_text or record_json is None \
                or fact_json is None or evidence_json is None or entry_json is None:
            if well_formed and frame["gap"] is None:
                frame["gap"] = "qualification_over_bound"
            return None

        # ---- saved exact native unread_event hold for the later finish refusal -------------------
        if not isinstance(result, dict) or not isinstance(replies, dict) \
                or not isinstance(replies.get("unread_event"), str):
            if well_formed and frame["gap"] is None:
                frame["gap"] = "native_answer_unavailable"
            return None
        unread = blocker[0]
        hold = {**result, "status": "unresolved",
                "meaning": {"act": "hold", "reason": "unread_event", "said": unread},
                "answer": replies["unread_event"].format(**{"말": unread})}

        continuation = {
            "frame": frame, "text": text, "current": current, "parser": parser, "model": model,
            "policy": policy, "policy_sha256": _sha(policy_json),
            "binding": {"conversation_id": conversation_id, "model_content_sha256": model_content,
                        "model_effective_key": model_effective, "projection_fingerprint": projection_fingerprint,
                        "parser_base_sha256": current_base, "parser_grammar_sha256": current_grammar,
                        "installed_memory_head": current_head},
            "question": {"triple": list(triple), "text_sha256": hashlib.sha256(question_text.encode("utf-8")).hexdigest(),
                         "render_sha256": hashlib.sha256(render_json.encode("utf-8")).hexdigest()},
            "pending": {"entry": entry, "unread_index": blocker_index, "at": at, "text_sha256": hashlib.sha256(pending_text.encode("utf-8")).hexdigest(),
                        "entry_sha256": hashlib.sha256(entry_json.encode("utf-8")).hexdigest(), "resolved": False},
            "support": {"fact": support, "source": source, "record": record,
                        "observation_id": oid, "reading_revision": revision, "turn": turn_index,
                        "triple": list(support["triple"]), "polarity": True, "modality": "asserted",
                        "source_text_sha256": hashlib.sha256(source_text.encode("utf-8")).hexdigest(), "record_sha256": hashlib.sha256(record_json.encode("utf-8")).hexdigest(),
                        "archived_fact_index": archived_fact_index, "archived_fact_sha256": hashlib.sha256(fact_json.encode("utf-8")).hexdigest(),
                        "archived_parser_base_sha256": record["parser_base_sha256"],
                        "archived_parser_grammar_sha256": record["parser_grammar_sha256"],
                        "archived_installed_memory_head": archived_head,
                        "archived_evidence_sha256": hashlib.sha256(evidence_json.encode("utf-8")).hexdigest()},
            "hold": hold,
        }
        if policy_v2:
            continuation["pending_set"] = witness
            continuation["blocker_index"] = blocker_index
            continuation["support"]["archived_fact_count"] = len(archived_facts)
        return continuation

    def _unread_continuation_finish(self, continuation, text, current, parser, resolved_queries, facts, outcome):
        """Qualify one successful native answer by the accepted B continuation, or refuse with None.

        Called by the C2 hook only after the sole original ``parser.answer`` succeeded inside the
        same question branch.  Every identity the B start captured is rechecked against the actual
        live objects (frame, source, parser, current, model, cache, policy, pending entry, support
        record/source).  The native outcome must be exactly one direct ``fact``/``evidence`` leaf
        whose fact is the chosen support triple and whose evidence is the chosen support evidence.
        Refusal is a finite private ``frame["gap"]`` code and ``None``; the caller restores the
        saved native hold.  Success is a shallow copy of the native outcome with only ``answer``
        replaced and ``qualification`` added.  Nothing is parsed, stored, logged or taught here.
        """
        import hashlib
        from marco.language.graph_projection import _render_unread_qualification
        frame = getattr(self, self._UNREAD_FRAME_ATTR, None)
        if not isinstance(frame, dict) or set(frame) != set(self._UNREAD_FRAME_FIELDS):
            return None
        if frame["gap"] is not None:
            return None
        gap = None
        hexdigits = "0123456789abcdef"
        fields = {"frame", "text", "current", "parser", "model", "policy", "policy_sha256", "binding",
                  "question", "pending", "support", "hold"}
        # B2: a genuine v2 continuation carries exactly the two extra B1 fields; nothing else changes.
        policy_v2 = isinstance(continuation, dict) and "pending_set" in continuation
        if policy_v2:
            fields = fields | {"pending_set", "blocker_index"}
        if not isinstance(continuation, dict) or set(continuation) != fields \
                or continuation["frame"] is not frame:
            gap = "input_owner_unavailable"
        if gap is None and (continuation["text"] is not text or frame["source"] is not text
                            or not isinstance(text, Obs) or _readings.oid_of(text) != TENTATIVE):
            gap = "input_owner_unavailable"
        if gap is None and (type(frame["calls"]) is not int or frame["calls"] != 1
                            or frame["nested"] is not False or getattr(self, "_in_name_reply", False)
                            or getattr(self, "_rereading", False)):
            gap = "input_scope_unsupported"
        if gap is None and (parser is None or frame["parser"] is not parser
                            or continuation["parser"] is not parser
                            or parser is not getattr(self, "_parser_instance", None)
                            or current is None or frame["current"] is not current
                            or continuation["current"] is not current
                            or frame["model"] is not self.model or continuation["model"] is not self.model):
            gap = "input_owner_unavailable"
        policy, policy_sha256 = (continuation["policy"], continuation["policy_sha256"]) if gap is None else (None, None)
        if gap is None and not isinstance(policy, dict):
            gap = "policy_unavailable"
        policy_fields = {"schema", "scope", "render", "source", "declaration_sha256"}
        if policy_v2:
            policy_fields = policy_fields | {"max_pending"}
        if gap is None and set(policy) != policy_fields:
            gap = "policy_invalid"
        # B2: continuation shape and declared schema must agree; v2 needs an exact int bound 1..8.
        if gap is None and (policy_v2 != (policy["schema"] == self._UNREAD_PENDING_SCHEMA_V2)
                            or (policy_v2 and (type(policy["max_pending"]) is not int
                                               or not 1 <= policy["max_pending"] <= 8))):
            gap = "policy_invalid"
        render = policy.get("render") if gap is None else None
        source = policy.get("source") if gap is None else None
        if gap is None:
            policy_json = self._unread_json(policy, 65536)
            declaration = {"schema": policy["schema"], "scope": policy["scope"], "render": render, "source": source}
            if policy_v2:
                declaration["max_pending"] = policy["max_pending"]
            declaration_json = self._unread_json(declaration, 65536)
            if policy_json is None or declaration_json is None or type(policy_sha256) is not str \
                    or hashlib.sha256(policy_json.encode("utf-8")).hexdigest() != policy_sha256 \
                    or type(policy["declaration_sha256"]) is not str \
                    or hashlib.sha256(declaration_json.encode("utf-8")).hexdigest() != policy["declaration_sha256"]:
                gap = "policy_invalid"
        if gap is None and (not isinstance(source, dict) or set(source) != {
                "graph_id", "root_id", "rule_id", "sense_id", "effective_graph_sha256", "view_key", "nodes", "edges"}
                or source["sense_id"] is not None):
            gap = "policy_invalid"
        if gap is None:
            view_key = source["view_key"]
            for value in (policy["schema"], policy["scope"], render,
                          source["rule_id"], source["graph_id"], source["root_id"]):
                if type(value) is not str or not value.strip():
                    gap = "policy_invalid"
            for value in (policy["declaration_sha256"], source["effective_graph_sha256"]):
                if type(value) is not str or len(value) != 64 or set(value) - set("0123456789abcdef"):
                    gap = "policy_invalid"
            if type(view_key) is not list or len(view_key) != 2 or type(view_key[0]) is not int \
                    or view_key[0] < 0 or not (view_key[1] is None
                                               or (type(view_key[1]) is str and view_key[1].strip())):
                gap = "policy_invalid"
        binding = continuation["binding"] if gap is None else None
        if gap is None and (not isinstance(binding, dict) or set(binding) != {
                "conversation_id", "model_content_sha256", "model_effective_key", "projection_fingerprint",
                "parser_base_sha256", "parser_grammar_sha256", "installed_memory_head"}):
            gap = "input_owner_unavailable"
        if gap is None:
            cached = getattr(self, "_grammar_cache", None)
            model = self.model
            head = binding["installed_memory_head"]
            frame = continuation["frame"]
            if type(binding["conversation_id"]) is not str or not binding["conversation_id"].strip() \
                    or binding["conversation_id"] != self.conversation_id \
                    or not isinstance(cached, tuple) or len(cached) != 2 or cached[0] is not parser \
                    or parser is not continuation["parser"] \
                    or not isinstance(frame, dict) \
                    or frame is not getattr(self, "_unread_continuation_frame", None) \
                    or frame.get("parser") is not parser or frame.get("current") is not current \
                    or frame.get("model") is not model \
                    or binding["parser_grammar_sha256"] != cached[1] \
                    or binding["parser_base_sha256"] != self.parser_base_sha256 \
                    or model is None or model is not continuation["model"] \
                    or binding["model_content_sha256"] != getattr(model, "content_fingerprint", None) \
                    or binding["model_effective_key"] != getattr(model, "effective_key", None) \
                    or type(head) is not type(self.installed_memory_head) \
                    or head != self.installed_memory_head \
                    or not (head is None or (type(head) is int and head >= 0)):
                gap = "input_owner_unavailable"
            for value in (binding["model_content_sha256"], binding["model_effective_key"],
                          binding["projection_fingerprint"], binding["parser_base_sha256"],
                          binding["parser_grammar_sha256"]):
                if type(value) is not str or len(value) != 64 or set(value) - set("0123456789abcdef"):
                    gap = "input_owner_unavailable"
        if gap is None:
            projection = getattr(model, "language_projection", None)
            parser_data = getattr(parser, "data", None)
            if not isinstance(projection, dict) or not isinstance(projection.get("data"), dict) \
                    or not isinstance(projection.get("provenance"), dict) \
                    or projection.get("fingerprint") != binding["projection_fingerprint"] \
                    or not self._unread_native_equal(projection["data"].get("unread_continuation"), policy) \
                    or not isinstance(parser_data, dict) \
                    or not self._unread_native_equal(parser_data.get("unread_continuation"), policy) \
                    or not self._unread_native_equal(projection["provenance"].get("graph_id"), source["graph_id"]) \
                    or not self._unread_native_equal(projection["provenance"].get("root_id"), source["root_id"]) \
                    or not self._unread_native_equal(projection["provenance"].get("effective_graph_sha256"),
                                                     source["effective_graph_sha256"]) \
                    or not self._unread_native_equal(projection["provenance"].get("view_key"), view_key):
                gap = "input_owner_unavailable"
        question = continuation["question"] if gap is None else None
        if gap is None and (not isinstance(question, dict)
                            or set(question) != {"triple", "text_sha256", "render_sha256"}):
            gap = "query_scope_unsupported"
        if gap is None:
            try:
                text_digest = hashlib.sha256(str(text).encode("utf-8")).hexdigest()
            except UnicodeEncodeError:
                text_digest = None
            if text_digest is None or question["text_sha256"] != text_digest \
                    or len(str(text).encode("utf-8", "replace")) > 8192:
                gap = "query_scope_unsupported"
            value = question["render_sha256"]
            if type(value) is not str or len(value) != 64 or set(value) - set("0123456789abcdef"):
                gap = "query_scope_unsupported"
        if gap is None and (not isinstance(current, dict) or not isinstance(resolved_queries, list)
                            or len(resolved_queries) != 1
                            or not self._unread_native_equal(resolved_queries, current.get("query"))
                            or not isinstance(resolved_queries[0], dict)
                            or set(resolved_queries[0]) != {"triple", "render"}
                            or not self._unread_native_equal(resolved_queries[0].get("triple"), question["triple"])
                            or type(question["triple"]) is not list or len(question["triple"]) != 3
                            or not all(type(part) is str and part.strip() for part in question["triple"])):
            gap = "query_scope_unsupported"
        if gap is None:
            render_json = self._unread_json(resolved_queries[0]["render"], 65536)
            if render_json is None \
                    or hashlib.sha256(render_json.encode("utf-8")).hexdigest() != question["render_sha256"]:
                gap = "query_scope_unsupported"
        pending = continuation["pending"] if gap is None else None
        pending_text = None
        if gap is None and (not isinstance(pending, dict) or set(pending) != {
                "entry", "unread_index", "at", "text_sha256", "entry_sha256", "resolved"}):
            gap = "pending_scope_unsupported"
        unread_text = None
        witness = None
        blocker_index = None
        if gap is None and policy_v2:
            # B2 v2 branch: the complete B0 witness must still be the live pending set, and the
            # primary descriptor must correspond exactly to the selected blocker entry.
            witness = continuation["pending_set"]
            blocker_index = continuation["blocker_index"]
            unread = getattr(self, "unread", None)
            entry = pending["entry"]
            owned_text = entry.get("text") if isinstance(entry, dict) else None
            if isinstance(owned_text, str):
                pending_text = str(owned_text)
            public = witness["public"] if type(witness) is dict and type(witness.get("public")) is dict else None
            refs = witness.get("refs") if type(witness) is dict else None
            entries = public.get("entries") if public is not None else None
            if witness is None or witness is not frame["pending_witness"] \
                    or public is None or not isinstance(refs, list) or not isinstance(entries, list) \
                    or not self._unread_pending_v2_same(witness) \
                    or type(public.get("max_pending")) is not int \
                    or public["max_pending"] != policy["max_pending"] \
                    or not isinstance(unread, list) or getattr(self, "unread_guard", None) \
                    or len(refs) != len(unread) or len(entries) != len(refs) \
                    or type(blocker_index) is not int or not 0 <= blocker_index < len(refs) \
                    or type(refs[blocker_index]) is not dict or type(entries[blocker_index]) is not dict \
                    or type(pending["unread_index"]) is not int or pending["unread_index"] != blocker_index \
                    or pending["resolved"] is not False:
                gap = "pending_scope_unsupported"
            else:
                ref = refs[blocker_index]
                descriptor = entries[blocker_index]
                meta = ref.get("meta")
                if ref.get("entry") is not entry or entry is not unread[blocker_index] \
                        or type(entry) is not dict or ref.get("text") is not entry.get("text") \
                        or type(pending_text) is not str or not pending_text.strip() \
                        or type(meta) is not dict or meta.get("text") != pending_text \
                        or type(pending["at"]) is not int or pending["at"] < 0 \
                        or pending["at"] > len(self.observations) \
                        or meta.get("at") != pending["at"] or entry.get("at") != pending["at"] \
                        or descriptor.get("unread_index") != blocker_index \
                        or descriptor.get("at") != pending["at"] \
                        or descriptor.get("text_sha256") != pending["text_sha256"] \
                        or descriptor.get("entry_sha256") != pending["entry_sha256"] \
                        or descriptor.get("resolved") is not False:
                    gap = "pending_scope_unsupported"
                else:
                    try:
                        encoded = pending_text.encode("utf-8")
                    except UnicodeEncodeError:
                        encoded = None
                    entry_json = self._unread_json({key: meta[key] for key in meta if key != "kind"}, 65536)
                    if encoded is None or len(encoded) > 8192 \
                            or hashlib.sha256(encoded).hexdigest() != pending["text_sha256"]:
                        gap = "pending_scope_unsupported"
                    value = pending["entry_sha256"]
                    if type(value) is not str or len(value) != 64 or set(value) - set("0123456789abcdef") \
                            or entry_json is None \
                            or hashlib.sha256(entry_json.encode("utf-8")).hexdigest() != value:
                        gap = "pending_scope_unsupported"
                    if gap is None:
                        if any(type(item) is not dict or not isinstance(item.get("text"), str) for item in refs):
                            gap = "pending_scope_unsupported"
                        else:
                            joined = "\n".join(str(item["text"]) for item in refs)
                            try:
                                joined_bytes = joined.encode("utf-8")
                            except UnicodeEncodeError:
                                joined_bytes = None
                            if joined_bytes is None or len(joined_bytes) > 8192:
                                gap = "qualification_over_bound"
                            else:
                                unread_text = joined
        elif gap is None:
            unread = getattr(self, "unread", None)
            entry = pending["entry"]
            owned_text = entry.get("text") if isinstance(entry, dict) else None
            if isinstance(owned_text, str):
                pending_text = str(owned_text)
            if not isinstance(unread, list) or len(unread) != 1 or unread[0] is not entry \
                    or getattr(self, "unread_guard", None) \
                    or not isinstance(entry, dict) or set(entry) != {"text", "at"} \
                    or type(pending["unread_index"]) is not int or pending["unread_index"] != 0 \
                    or type(pending["at"]) is not int or pending["at"] < 0 \
                    or pending["at"] > len(self.observations) \
                    or type(entry["at"]) is not int or entry["at"] != pending["at"] \
                    or pending["resolved"] is not False or type(pending_text) is not str \
                    or not pending_text.strip():
                gap = "pending_scope_unsupported"
            else:
                try:
                    encoded = pending_text.encode("utf-8")
                except UnicodeEncodeError:
                    encoded = None
                entry_json = self._unread_json({"text": pending_text, "at": entry["at"]}, 65536)
                if encoded is None or len(encoded) > 8192 \
                        or hashlib.sha256(encoded).hexdigest() != pending["text_sha256"]:
                    gap = "pending_scope_unsupported"
                value = pending["entry_sha256"]
                if type(value) is not str or len(value) != 64 or set(value) - set("0123456789abcdef") \
                        or entry_json is None \
                        or hashlib.sha256(entry_json.encode("utf-8")).hexdigest() != value:
                    gap = "pending_scope_unsupported"
        support = continuation["support"] if gap is None else None
        public_support = ("observation_id", "reading_revision", "turn", "triple", "polarity", "modality",
                          "source_text_sha256", "record_sha256", "archived_fact_index",
                          "archived_fact_sha256", "archived_parser_base_sha256",
                          "archived_parser_grammar_sha256", "archived_installed_memory_head",
                          "archived_evidence_sha256")
        if policy_v2:
            public_support = public_support + ("archived_fact_count",)
        if gap is None and (not isinstance(support, dict)
                            or set(support) != {"fact", "source", "record"} | set(public_support)):
            gap = "support_unavailable"
        if gap is None:
            source, record, fact = support["source"], support["record"], support["fact"]
            oid = _readings.oid_of(source)
            turn = support["turn"]
            if not isinstance(source, Obs) or type(oid) is not str or not oid.strip() or oid == TENTATIVE \
                    or oid != support["observation_id"] \
                    or type(getattr(source, "rev", None)) is not int or source.rev < 1 \
                    or type(support["reading_revision"]) is not int \
                    or source.rev != support["reading_revision"] \
                    or type(turn) is not int or turn < 0 or turn >= len(self.observations) \
                    or not isinstance(record, dict) \
                    or not isinstance(fact, dict) or not isinstance(fact.get("evidence"), dict):
                gap = "support_unavailable"
        if gap is None:
            active_obs = self.observations[turn]
            ledger_entry = self.reading_ledger.get(oid)
            active = ledger_entry.get("active") if isinstance(ledger_entry, dict) else None
            versions = ledger_entry.get("versions") if isinstance(ledger_entry, dict) else None
            if not isinstance(active_obs, Obs) or _readings.oid_of(active_obs) != oid \
                    or type(getattr(active_obs, "rev", None)) is not int or active_obs.rev != source.rev \
                    or str(active_obs) != str(source) \
                    or type(active) is not int or active < 1 or active != source.rev \
                    or not isinstance(versions, list) or len(versions) < active \
                    or len(versions) > min(self.max_turns * 8, 2048) \
                    or versions[active - 1] is not record \
                    or type(record.get("observation_id")) is not str or record.get("observation_id") != oid \
                    or type(record.get("reading_revision")) is not int \
                    or record.get("reading_revision") != active \
                    or type(record.get("source")) is not str or record.get("source") != str(source) \
                    or record.get("unavailable") is not False \
                    or fact["evidence"].get("source") is not source \
                    or type(fact["evidence"].get("turn")) is not int or fact["evidence"]["turn"] != turn:
                gap = "support_identity_mismatch"
        if gap is None:
            try:
                encoded = str(source).encode("utf-8")
            except UnicodeEncodeError:
                encoded = None
            if encoded is None or len(encoded) > 8192 \
                    or hashlib.sha256(encoded).hexdigest() != support["source_text_sha256"]:
                gap = "support_identity_mismatch"
            parsed = record.get("parsed")
            archived = parsed.get("facts") if isinstance(parsed, dict) else None
            index = support["archived_fact_index"]
            replay_view = {key: value for key, value in fact.items() if key != "evidence"}
            replay_view["evidence"] = {key: value for key, value in fact["evidence"].items()
                                       if key not in ("turn", "source")}
            fact_bound = 2 if policy_v2 else 1
            if type(index) is not int or not isinstance(archived, list) \
                    or not 1 <= len(archived) <= fact_bound \
                    or not 0 <= index < len(archived) or (not policy_v2 and index != 0) \
                    or not isinstance(archived[index], dict) \
                    or (policy_v2 and (type(support["archived_fact_count"]) is not int
                                       or support["archived_fact_count"] != len(archived))) \
                    or parsed.get("query") is not None and (type(parsed.get("query")) is not list or parsed.get("query")) \
                    or not self._unread_native_equal(archived[index], replay_view) \
                    or type(support["triple"]) is not list \
                    or not self._unread_native_equal(list(fact.get("triple", [])), support["triple"]) \
                    or sum(1 for item in archived if isinstance(item, dict)
                           and item.get("polarity", True) is True
                           and item.get("modality", "asserted") == "asserted"
                           and self._unread_native_equal(list(item.get("triple", [])), support["triple"])) != 1:
                gap = "support_identity_mismatch"
            if support["polarity"] is not True or support["modality"] != "asserted" \
                    or type(support["modality"]) is not str \
                    or fact.get("polarity", True) is not True \
                    or fact.get("modality", "asserted") != "asserted" \
                    or support["archived_parser_base_sha256"] != record.get("parser_base_sha256") \
                    or support["archived_parser_grammar_sha256"] != record.get("parser_grammar_sha256") \
                    or support["archived_installed_memory_head"] != record.get("installed_memory_head") \
                    or not (support["archived_installed_memory_head"] is None
                            or (type(support["archived_installed_memory_head"]) is int
                                and support["archived_installed_memory_head"] >= 0)):
                gap = "support_identity_mismatch"
            for value in (support["record_sha256"], support["archived_fact_sha256"],
                          support["archived_parser_base_sha256"], support["archived_parser_grammar_sha256"],
                          support["archived_evidence_sha256"]):
                if type(value) is not str or len(value) != 64 or value != value.lower() \
                        or any(c not in hexdigits for c in value):
                    gap = "support_identity_mismatch"
        if (gap is None and policy_v2 and len(archived) == 2
                and self._fact_batch_admissible(record["source"], record["parsed"], parser) is not True):
            gap = "support_identity_mismatch"
        if gap is None:
            record_json = self._unread_json(record, 65536)
            fact_json = self._unread_json(archived[index], 8192)
            evidence_json = self._unread_json(archived[index].get("evidence"), 8192)
            if record_json is None or fact_json is None or evidence_json is None \
                    or hashlib.sha256(record_json.encode("utf-8")).hexdigest() != support["record_sha256"] \
                    or hashlib.sha256(fact_json.encode("utf-8")).hexdigest() != support["archived_fact_sha256"] \
                    or hashlib.sha256(evidence_json.encode("utf-8")).hexdigest() != support["archived_evidence_sha256"]:
                gap = "support_identity_mismatch"
        if gap is None and (not isinstance(outcome, dict) or type(outcome.get("answer")) is not str
                            or not isinstance(outcome.get("transitions"), list)):
            gap = "native_answer_unavailable"
        if gap is None:
            transitions = outcome["transitions"]
            leaf = transitions[0] if len(transitions) == 1 and isinstance(transitions[0], dict) else None
            if leaf is None or set(leaf) != {"fact", "evidence"} \
                    or not self._unread_native_equal(list(leaf["fact"]) if isinstance(leaf["fact"], list)
                                                     else None, support["triple"]):
                gap = "native_answer_identity_mismatch"
        if gap is None:
            evidence, chosen = leaf["evidence"], fact["evidence"]
            native_source = evidence.get("source") if isinstance(evidence, dict) else None
            if not isinstance(evidence, dict) or not isinstance(native_source, Obs) \
                    or not (type(_readings.oid_of(native_source)) is str
                            and _readings.oid_of(native_source).strip()
                            and _readings.oid_of(native_source) != TENTATIVE
                            and _readings.oid_of(native_source) == _readings.oid_of(source)) \
                    or not (type(getattr(native_source, "rev", None)) is int
                            and native_source.rev >= 1 and native_source.rev == source.rev) \
                    or str(native_source) != str(source) \
                    or self._active_record(native_source) is not record \
                    or not isinstance(chosen.get("source"), Obs) \
                    or not (type(_readings.oid_of(chosen["source"])) is str
                            and _readings.oid_of(chosen["source"]).strip()
                            and _readings.oid_of(chosen["source"]) != TENTATIVE
                            and _readings.oid_of(chosen["source"]) == _readings.oid_of(source)) \
                    or not (type(getattr(chosen["source"], "rev", None)) is int
                            and chosen["source"].rev >= 1 and chosen["source"].rev == source.rev) \
                    or str(chosen["source"]) != str(source) \
                    or type(evidence.get("turn")) is not int or evidence["turn"] != support["turn"] \
                    or set(evidence) != set(chosen) \
                    or not self._unread_native_equal({k: v for k, v in evidence.items() if k != "source"},
                                                     {k: v for k, v in chosen.items() if k != "source"}):
                gap = "native_answer_identity_mismatch"
        if gap is None and policy_v2:
            # Actual-facts closure: native may augment the ``facts`` argument after the B start chose
            # its support, so re-establish exactly one direct positive support in the actual list
            # (no denial, no duplicate) and bind it to the chosen support by payload and source.
            try:
                from . import inference as _inference
            except ImportError:
                from marco.reasoning import inference as _inference
            actual = None
            if not isinstance(facts, list) or len(facts) > 2048:
                gap = "support_unavailable"
            else:
                actual_matched = 0
                for item in facts:
                    if not isinstance(item, dict):
                        continue
                    row = item.get("triple")
                    if not isinstance(row, (list, tuple)) or len(row) != 3 \
                            or not all(type(part) is str for part in row):
                        continue
                    if _inference.bind(list(question["triple"]), list(row), {}) is None:
                        continue
                    actual_matched += 1
                    if item.get("polarity", True) is False or actual_matched > 1:
                        gap = "support_unavailable"
                        break
                    actual = item
                if gap is None and actual is None:
                    gap = "support_unavailable"
            if gap is None:
                actual_evidence = actual.get("evidence")
                actual_modality = actual.get("modality", "asserted")
                if actual.get("polarity", True) is not True or type(actual_modality) is not str \
                        or actual_modality != "asserted" or actual.get("unnamed") \
                        or any(key in actual for key in ("at_least", "resolve", "bound")) \
                        or not isinstance(actual_evidence, dict) or "action_event" in actual_evidence \
                        or (type(actual_evidence.get("mode")) is str
                            and actual_evidence.get("mode") == "hypothetical") \
                        or any(key in actual_evidence for key in (
                            "at_least", "resolve", "unnamed", "bound", "derived", "rule")):
                    gap = "support_unavailable"
            if gap is None:
                actual_source = actual_evidence.get("source")
                actual_view = {k: v for k, v in actual.items() if k not in ("evidence", "id")}
                support_view = {k: v for k, v in fact.items() if k != "evidence"}
                if not self._unread_native_equal(actual_view, support_view) \
                        or set(actual_evidence) != set(chosen) \
                        or not self._unread_native_equal(
                            {k: v for k, v in actual_evidence.items() if k != "source"},
                            {k: v for k, v in chosen.items() if k != "source"}) \
                        or not isinstance(actual_source, Obs) \
                        or not (type(_readings.oid_of(actual_source)) is str
                                and _readings.oid_of(actual_source).strip()
                                and _readings.oid_of(actual_source) != TENTATIVE
                                and _readings.oid_of(actual_source) == oid) \
                        or type(getattr(actual_source, "rev", None)) is not int \
                        or actual_source.rev < 1 or actual_source.rev != source.rev \
                        or str(actual_source) != str(source) \
                        or self._active_record(actual_source) is not record:
                    gap = "support_identity_mismatch"
        if gap is None:
            answer = outcome["answer"]
            try:
                encoded = answer.encode("utf-8")
            except UnicodeEncodeError:
                encoded = None
            if encoded is None or len(encoded) > 8192:
                gap = "qualification_over_bound"
        qualified = None
        if gap is None:
            native_answer_sha256 = hashlib.sha256(encoded).hexdigest()
            try:
                qualified = _render_unread_qualification(render, answer,
                                                         unread_text if policy_v2 else pending_text)
            except ValueError:
                qualified = None
            if type(qualified) is not str:
                gap = "qualification_over_bound"
            else:
                try:
                    encoded = qualified.encode("utf-8")
                except UnicodeEncodeError:
                    encoded = None
                if encoded is None or len(encoded) > 24576:
                    gap = "qualification_over_bound"
        if gap is None:
            qualification = {
                "schema": ("marco-known-support-with-pending-set-v2" if policy_v2
                           else "marco-known-support-with-pending-input-v1"),
                "scope": ("archived_known_direct_support_with_complete_unresolved_inputs" if policy_v2
                          else "current_known_direct_support_with_unresolved_input"),
                "policy": {"declaration_sha256": policy["declaration_sha256"],
                           "graph_id": policy["source"]["graph_id"],
                           "root_id": policy["source"]["root_id"],
                           "policy_id": policy["source"]["rule_id"],
                           "effective_graph_sha256": policy["source"]["effective_graph_sha256"],
                           "view_key": list(policy["source"]["view_key"])},
                "binding": {key: binding[key] for key in (
                    "conversation_id", "model_content_sha256", "model_effective_key", "projection_fingerprint",
                    "parser_base_sha256", "parser_grammar_sha256", "installed_memory_head")},
                "question": {"text_sha256": question["text_sha256"],
                             "triple": list(question["triple"]),
                             "render_sha256": question["render_sha256"]},
                "pending": {key: pending[key] for key in (
                    "unread_index", "at", "text_sha256", "entry_sha256", "resolved")},
                "support": {key: (list(support[key]) if key == "triple" else support[key])
                            for key in public_support},
                "native_answer_sha256": native_answer_sha256,
            }
            if policy_v2:
                import copy
                public = witness["public"]
                qualification["pending_set"] = {
                    "complete": True,
                    "count": public["count"],
                    "max_pending": public["max_pending"],
                    "set_sha256": public["set_sha256"],
                    "blocker_index": blocker_index,
                    "entries": copy.deepcopy(public["entries"]),
                    "rendered_unread_sha256": hashlib.sha256(unread_text.encode("utf-8")).hexdigest(),
                }
            if self._unread_json(qualification, 65536) is None:
                gap = "qualification_over_bound"
        if gap is not None:
            if frame["gap"] is None:
                frame["gap"] = gap
            return None
        result = dict(outcome)
        result["answer"] = qualified
        result["qualification"] = qualification
        return result

    def turn(self, text, knowledge_path=None):
        """One turn. Its sentence comes from ``marco.language.realize``."""
        self._trace_buffer, self._trace_readings, self._readings_dropped = [], None, []
        self._trace_candidates, self._trace_rankings = [], []
        # the last question's frame as it stood before this turn (the turn's own question replaces it)
        self._frame_before_turn = self.last_frame
        self._recent_before_turn = list(getattr(self, "recent_frames", None) or [])
        observed_before = len(self.observations)
        result, path = None, "reply"
        # The utterance gets an isolated provisional identity; it is bound to a real slot only if committed.
        text = _readings.tentative(text)
        previous_frame = getattr(self, self._UNREAD_FRAME_ATTR, None)
        setattr(self, self._UNREAD_FRAME_ATTR, self._unread_continuation_enter(text, previous_frame))
        self._current_query_read = {"source": text, "calls": 0, "parser": None, "value": None, "gap": None}
        self._query_work = None
        self._thinking_work = None
        self._thinking_exhaustion = None
        try:
            result = self._turn_said(text, knowledge_path)
            work = self.__dict__.get("_query_work")
            if type(result) is dict and type(work) is dict:
                result["reasoning_work"] = deepcopy(work)
            thinking = self.__dict__.get("_thinking_work")
            if type(result) is dict and type(thinking) is dict:
                result["thinking_work"] = deepcopy(thinking)
            path = self._trace_path
            return result
        finally:
            self.__dict__.pop("_query_work", None)
            self.__dict__.pop("_thinking_work", None)
            self.__dict__.pop("_thinking_exhaustion", None)
            if previous_frame is not None:
                setattr(self, self._UNREAD_FRAME_ATTR, previous_frame)
            else:
                self.__dict__.pop(self._UNREAD_FRAME_ATTR, None)
            self._parser().__dict__.setdefault("chosen_readings", {}).pop(TENTATIVE, None)
            if self.trace is not None:
                self._emit_turn(text, result, path, observed_before)
            self._trace_buffer = []

    def _question_parts(self, text):
        """G5.6 (Diairesis): the questions of a turn that asks two or more, each ended by a declared question
        mark, in the order said; None for any other turn (a statement before a question stays one turn)."""
        if not self._permitted(None):
            return None
        marks = self._parser().clause_grammar.get("question_marks", [])
        if not marks or sum(str(text).count(mark) for mark in marks) < 2:
            return None
        pieces = [piece.strip() for piece in re.split("(?<=[%s])\\s+" % re.escape("".join(marks)), str(text).strip())
                  if piece.strip()]
        if len(pieces) < 2 or not all(any(piece.endswith(mark) for mark in marks) for piece in pieces):
            return None
        return pieces

    def _answer_parts(self, pieces, knowledge_path):
        """Each question answered in order, as the turn it would be alone (its reading, its evidence); the
        turn's meaning is ``kind: queries`` with one entry per answer (request W5-1): the answer's own
        meaning, its ``status``, and for an answered fact its ``fact`` and that fact's ``evidence``. The
        transitions carry every answer's rows, each marked with its ``part``; the checks likewise."""
        parser = self._parser()
        results = []
        for piece in pieces:
            part = self._turn_reply(piece, knowledge_path)
            if part is None:
                part = {"operator": "relational_graph", "status": "unresolved", "transitions": [],
                        "meaning": {"act": "hold", "reason": "unresolved", "said": piece},
                        "verification": self._verification(knowledge_path, [{"ok": False, "reason": "part_unread"}])}
            results.append(part)
        answers = []
        for part in results:
            entry = {key: value for key, value in (part.get("meaning") or {}).items() if key != "conversation"}
            entry["status"] = "answered" if part.get("status") == "answered" else "unresolved"
            facts = [r for r in part.get("transitions") or [] if isinstance(r, dict)
                     and isinstance(r.get("fact"), (list, tuple)) and len(r["fact"]) == 3]
            if entry["status"] == "answered" and entry.get("kind") == "total":
                # a total is its members' counts summed (the value the single turn says), with their rows
                latest = {str(r["fact"][0]): r for r in facts}
                members = [latest.get(str(member)) for member in entry.get("subjects") or []]
                if members and all(m is not None and str(m["fact"][2]).lstrip("-").isdigit() for m in members):
                    entry["value"] = sum(int(m["fact"][2]) for m in members)
                    entry["evidence"] = [deepcopy(m.get("evidence")) for m in members]
            elif entry["status"] == "answered" and facts and not entry.get("kind"):
                entry["fact"] = [str(x) for x in facts[-1]["fact"]]
                entry["evidence"] = deepcopy(facts[-1].get("evidence"))
            answers.append(entry)
        answered = all(entry["status"] == "answered" for entry in answers)
        held = next((entry for entry in answers if entry["status"] != "answered"), None)
        replies = parser.data["context_replies"]
        checks = [dict(check, part=index) for index, part in enumerate(results)
                  for check in ((part.get("verification") or {}).get("checks") or []) if isinstance(check, dict)]
        return {"operator": "relational_graph", "status": "answered" if answered else "unresolved",
                "answer": " ".join(str(part.get("answer") or replies["unresolved"]).strip() for part in results),
                "transitions": [dict(row, part=index) for index, part in enumerate(results)
                                for row in part.get("transitions") or [] if isinstance(row, dict)],
                "meaning": {"act": "inform", "kind": "queries", "answers": answers,
                            **({"reason": held.get("reason") or "unresolved"} if held else {})},
                "verification": self._verification(knowledge_path, checks)}

    def _fragment_amount(self, parser, spec, piece):
        """The amount of a sentence that states a quantity without its holder:
        (the amount as it goes into a statement, its value), else None. The
        words around it are the pack's: its fragment heads, the phrases its variants read as nothing, the
        copula tails and the counters."""
        from marco.language.numerals import parse_numeral
        flags = re.IGNORECASE if parser.data.get("ignore_case") else 0
        rest = piece.strip().rstrip(".!…").strip()
        for phrase in sorted(list(spec.get("heads", [])) + [row["from"] for row in parser.phrase_variants
                                                             if row.get("from") and row.get("to", "") == ""],
                             key=len, reverse=True):
            rest = re.sub(r"(?<![\w])%s(?![\w])" % re.escape(phrase), " ", rest, flags=flags)
        rest = re.sub(r"\s+", " ", rest.replace(",", " ")).strip()
        for tail in sorted(spec.get("tails", []), key=len, reverse=True):
            if rest.endswith(tail) and len(rest) > len(tail):
                rest = rest[:-len(tail)].strip()
                break
        units = sorted(parser.counters.get("units", []), key=len, reverse=True)
        counter = next((u for u in units if rest.endswith(u) and len(rest) > len(u)), "")
        number = rest[:-len(counter)].strip() if counter else rest
        value = number if number.isdigit() else parse_numeral(number.lower() if flags else number,
                                                              parser.data.get("numerals", {}))
        if not number or value is None:
            return None
        if spec.get("insert") == "before_verb":
            return (rest if counter else "%s%s" % (value, spec.get("counter", ""))), str(value)
        return str(value), str(value)

    def _spliced_fragment(self, text):
        """A statement said without its amount and the amount said after it as a fragment, in the same turn
        (``지유가 은호한테 사과를 줬어. 두 개.``) or as the very next turn after the statement went unread
        (``Tessa gave Hugo some spoons.`` / ``Two, to be exact.``), read as one statement: the amount takes
        the place of the vague word the pack declares, or stands right before the verb (fragment_amount).
        Returns the statement to read and the unread statement it replaces, or None."""
        if not self._permitted(None):
            return None
        parser = self._parser()
        spec = (getattr(parser, "word_order_forms", None) or {}).get("fragment_amount") or {}
        if not spec:
            return None
        segments = self._segments(text, parser)
        if not segments or segments[-1][1]:
            return None
        amount = self._fragment_amount(parser, spec, segments[-1][0])
        if amount is None:
            return None
        replaced = None
        if len(segments) >= 2:
            statement = " ".join(piece for piece, _q in segments[:-1])
            if any(question for _p, question in segments[:-1]):
                return None
            read = parser.parse(statement, partial=True, events=True, repair=True) or {}
            if read.get("facts") or read.get("query"):
                return None
        else:
            last = getattr(self, "_last_said", None)
            entry = self.unread[-1] if self.unread else None
            # the unread statement is the last thing said: left out of the observations, or kept as the last one
            # for a word to be explained later (가람이 나래에게 연필을 줬어 with no amount reads as an unknown event)
            kept = bool(self.observations) and self.observations[-1].strip() == last
            if (not last or entry is None or entry["text"].strip() != last
                    or entry.get("at") != len(self.observations) - (1 if kept else 0)):
                return None
            # a question left unread takes no amount (그 사람은 어디 있어? / 여섯 개.)
            if any(question for _p, question in self._segments(last, parser)):
                return None
            statement, replaced = last, entry["text"]
        flags = re.IGNORECASE if parser.data.get("ignore_case") else 0
        body = statement.strip()
        stop = body[-1] if body[-1:] in ".!…" else ""
        body = body[:-1].strip() if stop else body
        # a phrase the pack reads as a vague word is that word (a few, a couple of -> some)
        vagues = list(spec.get("vague", [])) + [row["from"] for row in parser.phrase_variants if row.get("from")
                                                 and row.get("to") in spec.get("vague", [])]
        vague = [w for w in sorted(vagues, key=len, reverse=True) if re.search(r"(?<![\w])%s(?![\w])" % re.escape(w), body, flags)]
        if len(vague) == 1:
            spliced = re.sub(r"(?<![\w])%s(?![\w])" % re.escape(vague[0]), amount[0], body, count=1, flags=flags)
        elif not vague and spec.get("insert") == "before_verb" and " " in body:
            head, verb = body.rsplit(" ", 1)
            spliced = "%s %s %s" % (head, amount[0], verb)
        else:
            return None
        spliced += stop or "."
        read = parser.parse(spliced, partial=True, events=True, repair=True) or {}
        if not read.get("facts") or any(f.get("unnamed") for f in read["facts"]) or read.get("query"):
            return None
        return spliced, replaced

    def _repair_and_question(self, text, knowledge_path):
        """A referent repair followed by the question in the same turn (``I mean Nora. How many pens does Nora
        have?``, ``다솜 말입니다. 몇 장입니까?``): the first sentence is read as the name reply it is; then the
        question, answered on its own when it can be, else the repaired question stands as the answer."""
        if not self._permitted(knowledge_path) or self._live() or not (
                self.pending_pointer or self.last_question or (self.last_frame and self._effort_allows(2))):
            return None
        parser = self._parser()
        segments = self._segments(text, parser)
        if len(segments) < 2 or segments[0][1] or not segments[-1][1]:
            return None
        named = self._name_reply(parser, segments[0][0], knowledge_path)
        if named is None:
            # the name of one asked candidate with at most two other words (Ivo, I think.), effort 2
            named = self._named_reply(parser, segments[0][0], knowledge_path)
        if named is None:
            # the repair as one slot of the last question's frame (effort 2)
            named = self._partial_frame(parser, segments[0][0], knowledge_path)
        if named is None:
            return None
        asked = self._turn_reply(" ".join(piece for piece, _q in segments[1:]), knowledge_path)
        return asked if asked is not None and asked.get("status") == "answered" else named

    def _turn_said(self, text, knowledge_path=None):
        from pack_model import PackModel
        projection = (self.model.language_projection
                      if type(self.model) is PackModel else None)
        if projection is not None:
            return self._graph_dialogue_turn(text, knowledge_path, projection)
        spliced = self._spliced_fragment(text)
        if spliced is not None:
            text, replaced = spliced
            text = _readings.tentative(text) if _readings.oid_of(text) is None else text
            if replaced is not None:
                self._forget_heard({replaced})
                # the statement kept as an observation is replaced by the one with its amount, not read twice
                if self.observations and self.observations[-1].strip() == replaced.strip():
                    self.observations.pop()
        self._last_said = str(text).strip()
        language = self.language or next((source["path"] for source in getattr(self.model, "sources", ())
                                          if source["path"].startswith("styles/")), None)
        explained = self.last_explanation
        repaired = self._repair_and_question(text, knowledge_path)
        parts = None if repaired is not None else self._question_parts(text)
        result = repaired if repaired is not None else (
            self._answer_parts(parts, knowledge_path) if parts else self._follow_up(text, knowledge_path, language))
        self._trace_path = "follow_up" if result is not None and not parts else "reply"
        if result is None:
            result = self._turn_reply(text, knowledge_path)
            if result is None and self._permitted(knowledge_path) and not self._live():
                # a turn not read may name one slot of the last question (effort 2); kept as unread just now, it
                # is not unread when it reads so
                kept = [entry for entry in self.unread if entry["text"].strip() == str(text).strip()]
                self.unread = [entry for entry in self.unread if entry not in kept]
                result = self._partial_frame(self._parser(), text, knowledge_path)
                if result is None:
                    self.unread += kept
                if result is not None:
                    self._trace_path = "follow_up"
            # What the last reply's readings changed, for "what did you change?".
            self._last_repairs = [deepcopy(report) for report in (result or {}).get("repair") or []
                                  if report.get("status") == "repaired"]
            if result is None and self._permitted(knowledge_path) and self.observations:
                # A turn this conversation did not read (another topic, a request)
                # breaks the thread a pointer follows: after it, a pointer may mean
                # anyone the conversation named, and two or more are asked back (G3.0 a).
                parser = self._parser()
                facts, _d, _p, _r = self._cached_replay(parser, self.observations, self.fills)
                self.salient = sorted({self._person_of(row["triple"][0]) for row in facts
                                       if isinstance(row["triple"][0], str) and str(row["triple"][0]).strip()})
        if result is not None and "answer" in result:
            if isinstance(result.get("meaning"), dict):
                result["meaning"] = {**result["meaning"], "conversation": self.conversation_id}
            self._declare_holders(result)
            from marco.language.realizer import default_realizer
            reports = default_realizer().reports
            before = reports[-1] if reports else None
            speaker = self._speaker(result, language)
            from marco.language.realizer.packs import selected_scope
            with selected_scope(self.model, speaker, self.conversation_id):
                result["answer"] = realize(result, result.get("status"), speaker)
            report = reports[-1] if reports and reports[-1] is not before else None
            if report is not None and report.get("held") and report.get("text") == result["answer"] \
                    and result.get("status") == "answered":
                # Nothing of the answer was said (request G3-3): the turn is a hold, with the
                # realizer's reason, and a later "why" does not explain an answer never given.
                self.last_explanation = explained
                result["status"] = "unresolved"
                result["meaning"] = {"act": "hold", "reason": report.get("reason") or "not_phrased",
                                     "held": {key: value for key, value in (result.get("meaning") or {}).items()
                                              if key != "conversation"},
                                     "conversation": self.conversation_id}
                checks = (result.get("verification") or {}).get("checks")
                if isinstance(checks, list):
                    checks.append({"ok": False, "reason": "realizer_hold",
                                   "blocked": [clause.get("frame") for clause in report.get("clauses") or []
                                               if clause.get("blocked")]})
        return result

    def _graph_dialogue_turn(self, text, knowledge_path, projection):
        self._last_said = str(text).strip()
        self._trace_path = "reply"
        parser = self._parser()
        required = ("observed", "unresolved", "unread_event", "unknown_word", "input_understanding_failed",
                    "no_reading", "ambiguous_reading", "capacity", "invalid", "contradiction")
        bundle = projection if isinstance(projection, dict) else {}
        data = bundle.get("data") if isinstance(bundle.get("data"), dict) else {}
        installed = parser.data.get("context_replies")
        missing = [key for key in required
                   if not (isinstance(installed, dict) and isinstance(installed.get(key), str)
                           and installed[key].strip())]
        capabilities = data.get("semantic_capabilities")
        if (isinstance(capabilities, dict)
                and capabilities.get("schema") == "selected-binary-semantic-capabilities-v1"
                and "conditional_binary" in capabilities):
            conditional_missing = [key for key in ("unmeasured_condition", "condition_false")
                                   if not (isinstance(installed, dict)
                                           and isinstance(installed.get(key), str)
                                           and installed[key].strip())]
            missing.extend(key for key in conditional_missing if key not in missing)
        unsupported = []
        if not isinstance(projection, dict) or bundle.get("schema") != "graph-dialogue-projection-v1":
            unsupported.append("projection_schema")
        if not self._permitted(knowledge_path):
            unsupported.append("operator_not_permitted")
        if installed != data.get("context_replies"):
            unsupported.append("reply_authority")
        if missing or unsupported:
            return self._graph_dialogue_gap(text, knowledge_path, missing_replies=missing,
                                            unsupported=unsupported)
        result = self._turn(text, knowledge_path)
        if result is None:
            marker = self.__dict__.get("_thinking_exhaustion")
            self.__dict__["_thinking_exhaustion"] = None
            source = _scoped_text(text)
            if (type(marker) is not dict or set(marker) != {"source", "parser"}
                    or marker["source"] is not text or marker["parser"] is not parser
                    or source is None or not source.strip()
                    or len(source.encode("utf-8", "surrogatepass")) > 65536):
                return None
            auth = _scoped_authority(projection, parser)
            if auth is None or not _scoped_hex(auth.get("scope_sha256")):
                return None
            native = data.get("context_replies")
            if type(installed) is not dict or type(native) is not dict or not _scoped_native_eq(installed, native):
                return None
            evidence = {"scope": "selected_reader_processing_failure", "outcome": "exhausted",
                        "authority_sha256": auth["scope_sha256"]}
            return self._failure_dispatch(text, knowledge_path, None, evidence, installed, text, False)
        if result is not None and "answer" in result and isinstance(result.get("meaning"), dict):
            result["meaning"] = {**result["meaning"], "conversation": self.conversation_id}
        return result

    def _graph_dialogue_gap(self, text, knowledge_path, *, missing_replies=(), unsupported=()):
        missing, tags = sorted(set(missing_replies)), sorted(set(unsupported))
        return {"operator": "relational_graph", "status": "unresolved", "answer": None, "transitions": [],
                "meaning": {"act": "hold", "reason": "language_graph_capability_gap", "said": str(text),
                            "missing_replies": missing, "unsupported": tags,
                            "conversation": self.conversation_id},
                "verification": self._verification(knowledge_path, [{
                    "ok": False, "reason": "language_graph_capability_gap",
                    "missing_replies": missing, "unsupported": tags}])}

    _FACT_BATCH_IDENTITY = ('graph_id', 'root_id', 'effective_graph_sha256', 'view_key')

    def _fact_batch_capsule_ok(self, capsule, provenance):
        """Capsule identity equals the installed projection provenance (exact plain-JSON types)."""
        if not isinstance(capsule, dict) or not isinstance(provenance, dict):
            return False
        if any(key not in capsule or key not in provenance for key in self._FACT_BATCH_IDENTITY):
            return False
        ident = {key: capsule[key] for key in self._FACT_BATCH_IDENTITY}
        expect = {key: provenance[key] for key in self._FACT_BATCH_IDENTITY}
        if self._unread_json(ident, 8192) is None or not self._unread_native_equal(ident, expect):
            return False
        return type(capsule.get('rule_id')) is str and bool(capsule['rule_id'])

    def _fact_batch_policy(self, parser=None):
        import hashlib
        projection = getattr(self.model, 'language_projection', None)
        if not isinstance(projection, dict):
            return None
        data = projection.get('data')
        provenance = projection.get('provenance')
        policy = data.get('fact_batch') if isinstance(data, dict) else None
        if (not isinstance(policy, dict) or not isinstance(provenance, dict)
                or set(policy) != {'schema', 'scope', 'max_rows', 'source', 'declaration_sha256'}
                or policy['schema'] != 'graph-fact-batch-policy-v1'
                or policy['scope'] != 'direct_positive_asserted_binary_fact_batch'
                or type(policy['max_rows']) is not int or policy['max_rows'] != 2
                or not isinstance(policy['source'], dict)
                or type(policy['declaration_sha256']) is not str
                or not re.fullmatch(r'[0-9a-f]{64}', policy['declaration_sha256'])):
            return None
        try:
            declared = {k: v for k, v in policy.items() if k != 'declaration_sha256'}
            rendered = json.dumps(declared, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                                  allow_nan=False)
            digest = hashlib.sha256(rendered.encode('utf-8')).hexdigest()
            full = json.dumps(policy, sort_keys=True, separators=(',', ':'), ensure_ascii=False,
                              allow_nan=False)
            if len(full.encode('utf-8')) > 65536:
                return None
        except (TypeError, ValueError, UnicodeEncodeError):
            return None
        if digest != policy['declaration_sha256']:
            return None
        # Declared preimage and full policy must be bounded plain JSON (65536 bytes, 4096 nodes, depth 32).
        if self._unread_json(declared, 65536) is None or self._unread_json(policy, 65536) is None:
            return None
        if not self._fact_batch_capsule_ok(policy['source'], provenance):
            return None
        head = {k: policy[k] for k in ('schema', 'scope', 'max_rows', 'declaration_sha256')}
        if self._unread_json(head, 4096) is None:
            return None
        if parser is not None:
            held = getattr(parser, 'data', None)
            installed = held.get('fact_batch') if isinstance(held, dict) else None
            # Full bounded exact comparison: installed policy (including source nodes/edges) equals native.
            if (not isinstance(installed, dict) or set(installed) != set(policy)
                    or not isinstance(installed['source'], dict)
                    or self._unread_json(installed, 65536) is None
                    or not self._unread_native_equal(installed, policy)
                    or not self._fact_batch_capsule_ok(installed['source'], provenance)):
                return None
        return policy

    def _fact_batch_admissible(self, text, current, parser):
        try:
            return bool(self._fact_batch_check(text, current, parser))
        except (TypeError, ValueError, KeyError, AttributeError, IndexError):
            return False

    def _fact_batch_check(self, text, current, parser):
        facts = current.get('facts')
        if (not isinstance(facts, list) or len(facts) != 2 or current.get('query')
                or not isinstance(text, str) or self._live()):
            return False
        policy = self._fact_batch_policy(parser)
        if policy is None or len(facts) > policy['max_rows']:
            return False
        try:
            if len(text.encode('utf-8')) > 8192:
                return False
        except UnicodeEncodeError:
            return False
        if any(current.get(key) for key in ('사건', '가정사건', '사건정정', '정의', '원인', '이유물음', '조건',
                                            '수선', '가정', 'events', 'definition', 'cause', 'reason',
                                            'correction', 'condition', 'hypothesis', 'repairs')):
            return False
        data = getattr(parser, 'data', None)
        data = data if isinstance(data, dict) else {}
        blocked = set()
        for key in ('numeric_updates', 'mutable_predicates', 'comparisons', 'comparison_predicates'):
            held = data.get(key)
            if isinstance(held, (dict, list, tuple, set, frozenset)):
                blocked.update(k for k in held if isinstance(k, str))
        # Declared numeric update specs also block their target predicate.
        updates = data.get('numeric_updates')
        specs = updates.values() if isinstance(updates, dict) else updates
        if isinstance(specs, (list, tuple)) or isinstance(updates, dict):
            for spec in specs:
                if isinstance(spec, dict) and isinstance(spec.get('target'), str) and spec['target']:
                    blocked.add(spec['target'])
        frames = data.get('predicate_frames')
        frames = frames if isinstance(frames, dict) else {}
        marks = set()
        grammar = getattr(parser, 'clause_grammar', None)
        for held in (frames.get('separators'), frames.get('terminators'),
                     grammar.get('question_marks') if isinstance(grammar, dict) else None):
            if isinstance(held, (list, tuple)):
                marks.update(m for m in held if isinstance(m, str) and m)
        number = r'[+-]?\d+(\.\d+)?'
        for fact in facts:
            if not isinstance(fact, dict) or fact.get('unnamed') or fact.get('resolve') or fact.get('elided'):
                return False
            triple = fact.get('triple')
            if not isinstance(triple, (list, tuple)) or len(triple) != 3:
                return False
            if not all(isinstance(part, str) and part.strip() and '$' not in part and '?' not in part
                       for part in triple):
                return False
            if (fact.get('polarity', True) is not True or fact.get('modality', 'asserted') != 'asserted'
                    or re.fullmatch(number, triple[2].strip()) or re.fullmatch(number, triple[0].strip())
                    or triple[1] in blocked):
                return False
            evidence = fact.get('evidence')
            if (not isinstance(evidence, dict) or evidence.get('normalization') or evidence.get('repair')
                    or evidence.get('ellipsis') or fact.get('ellipsis') or fact.get('derived')
                    or fact.get('negation') or fact.get('variables')):
                return False
        import hashlib
        selection = current.get('entry_selection')
        if (not isinstance(selection, dict) or selection.get('schema') != 'marco-entry-selection-v1'
                or selection.get('scope') != 'known_selected_input_clauses'
                or selection.get('status') != 'partial'
                or selection.get('coordinate_space') != 'parser_view'
                or not isinstance(selection.get('gaps'), list)
                or not isinstance(selection.get('items'), list)
                or len(selection['items']) != 2):
            return False
        # Native source authority: installed predicate frames / examples are the projection's own.
        projection = self.model.language_projection
        native = projection.get('data') if isinstance(projection, dict) else None
        provenance = projection.get('provenance') if isinstance(projection, dict) else None
        if not isinstance(native, dict) or not isinstance(provenance, dict):
            return False
        native_frames = native.get('predicate_frames')
        held_frames = frames.get('frames')
        native_held = native_frames.get('frames') if isinstance(native_frames, dict) else None
        seed_count = native_frames.get('seed_count') if isinstance(native_frames, dict) else None
        seed_sha256 = native_frames.get('seed_sha256') if isinstance(native_frames, dict) else None
        examples = native.get('examples')
        installed = data.get('examples')
        if (not isinstance(native_frames, dict) or native_frames.get('schema') != 'predicate-frames-v2'
                or frames.get('schema') != 'predicate-frames-v2'
                or type(seed_count) is not int or seed_count <= 0
                or type(frames.get('seed_count')) is not int or frames['seed_count'] != seed_count
                or type(seed_sha256) is not str or frames.get('seed_sha256') != seed_sha256
                or not isinstance(held_frames, list) or not isinstance(native_held, list)
                or len(held_frames) != len(native_held)
                or not isinstance(examples, list) or not isinstance(installed, list)
                or len(examples) < seed_count or len(installed) < seed_count):
            return False
        try:
            seed_text = json.dumps(examples[:seed_count], sort_keys=True, separators=(',', ':'),
                                   ensure_ascii=False, allow_nan=False)
            if hashlib.sha256(seed_text.encode('utf-8')).hexdigest() != seed_sha256:
                return False
        except (TypeError, ValueError, UnicodeEncodeError):
            return False
        for row in range(seed_count):
            if (not isinstance(examples[row], dict) or examples[row].get('derived')
                    or not self._unread_native_equal(installed[row], examples[row])):
                return False
        for held, own in zip(held_frames, native_held):
            if (not isinstance(held, dict) or not isinstance(own, dict)
                    or not isinstance(held.get('source_ref'), dict) or not isinstance(own.get('source_ref'), dict)
                    or not self._unread_native_equal({k: v for k, v in held.items() if k != 'source_ref'},
                                                     {k: v for k, v in own.items() if k != 'source_ref'})
                    or not self._unread_native_equal(
                        {k: held['source_ref'].get(k) for k in ('index', 'annotation_sha256')},
                        {k: own['source_ref'].get(k) for k in ('index', 'annotation_sha256')})
                    or not self._fact_batch_capsule_ok(own['source_ref'].get('graph_source'), provenance)
                    or not self._fact_batch_capsule_ok(held['source_ref'].get('graph_source'), provenance)
                    # Full bounded exact native equality of graph_source (rule/sense/nodes/edges included).
                    or self._unread_json(own['source_ref'].get('graph_source'), 65536) is None
                    or self._unread_json(held['source_ref'].get('graph_source'), 65536) is None
                    or not self._unread_native_equal(held['source_ref'].get('graph_source'),
                                                     own['source_ref'].get('graph_source'))):
                return False
        vector = getattr(parser, '_entry_origins', None)
        if not isinstance(vector, list) or len(vector) != len(installed):
            return False
        spans, expected_gaps = [], []
        item_keys = {'clause_ordinal', 'span', 'compiler_index', 'origin', 'targets', 'derivation'}
        for index, (fact, item) in enumerate(zip(facts, selection['items'])):
            evidence = fact['evidence']
            start, end = evidence.get('start'), evidence.get('end')
            if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text)
                    or evidence.get('text') != text[start:end]):
                return False
            if (not isinstance(item, dict) or set(item) != item_keys
                    or item.get('clause_ordinal') != index or type(item['clause_ordinal']) is not int
                    or not self._unread_native_equal(item.get('span'), [start, end])
                    or not self._unread_native_equal(item.get('targets'), {'facts': [index], 'query': []})
                    or item.get('derivation') is not None
                    or type(item.get('compiler_index')) is not int
                    or not 0 <= item['compiler_index'] < seed_count):
                return False
            # Distinct clauses may share one compiler_index / native frame; no uniqueness demanded.
            ci = item['compiler_index']
            if self._unread_json(examples[ci], 65536) is None:
                return False
            matches = [f for f in native_held if isinstance(f, dict) and isinstance(f.get('source_ref'), dict)
                       and type(f['source_ref'].get('index')) is int and f['source_ref']['index'] == ci]
            if len(matches) != 1:
                return False
            ref = matches[0]['source_ref']
            if (type(ref.get('annotation_sha256')) is not str
                    or not re.fullmatch(r'[0-9a-f]{64}', ref['annotation_sha256'])
                    or not isinstance(ref.get('graph_source'), dict)
                    or matches[0].get('id') != ref['graph_source'].get('rule_id')
                    or self._unread_json(ref['annotation_sha256'], 256) is None):
                return False
            held_origin = vector[ci]
            origin = item.get('origin')
            if held_origin is None:
                # Native default: truthful persisted unknown origin; only this exact gap is permitted.
                if origin is not None:
                    return False
                expected_gaps.append({'clause_ordinal': index, 'code': 'origin_unknown'})
            elif (not isinstance(origin, dict) or not origin or not isinstance(held_origin, dict)
                    or self._unread_json(origin, 8192) is None
                    or not self._unread_native_equal(origin, held_origin)):
                return False
            spans.append((start, end))
        if not self._unread_native_equal(selection['gaps'], expected_gaps):
            return False
        if spans[0][1] > spans[1][0]:
            return False
        gaps = (text[:spans[0][0]], text[spans[0][1]:spans[1][0]], text[spans[1][1]:])
        for gap in gaps:
            rest = gap
            for mark in sorted(marks, key=len, reverse=True):
                rest = rest.replace(mark, ' ')
            if rest.strip():
                return False
        rendered = json.dumps({'facts': facts, 'entry_selection': selection}, sort_keys=True,
                              ensure_ascii=False, allow_nan=False)
        return len(rendered.encode('utf-8')) <= 65536

    def _admit_structural_observation(self, text, current, parser, verbs, knowledge_path):
        """One-commit transactional admission of a native structural unknown-action observation.

        None when the existing pure preflight declines. Otherwise either the raw capacity hold (no
        commit) or exactly one ``_commit_observations`` plus the unread binding; any other error
        restores the original containers and propagates. No parse/replay/answer/turn is added.
        """
        bundle = self._prepare_structural_observation(text, current, parser, verbs)
        if bundle is None:
            return None
        equal = self._unread_native_equal
        source, parsed, word = bundle["source"], bundle["parsed"], bundle["word"]
        old_count = bundle["old_count"]
        raw = source.strip()
        saved = dict(self.__dict__)
        obs_ref, obs_items = self._obs, list(self._obs)
        ledger_ref = self.reading_ledger
        ledger_items = dict(ledger_ref)
        ledger_shape = {key: (held, held["active"], len(held["versions"])) for key, held in ledger_items.items()}
        parser_dict = parser.__dict__
        chosen_present = "chosen_readings" in parser_dict
        chosen_ref = parser_dict.get("chosen_readings")
        chosen_items = dict(chosen_ref) if chosen_present and isinstance(chosen_ref, dict) else None
        unread_ref, unread_items = self.unread, list(self.unread)
        guard_ref, guard_items = self.unread_guard, list(self.unread_guard)
        next_id = self._next_observation
        trace_present = "_trace_buffer" in self.__dict__
        trace_ref = self.__dict__.get("_trace_buffer")
        trace_len = len(trace_ref) if trace_ref is not None else 0

        def rollback():
            state = self.__dict__
            for key in [k for k in state if k not in saved]:
                del state[key]
            state.update(saved)
            obs_ref[:] = obs_items
            self._obs = obs_ref
            ledger_ref.clear()
            ledger_ref.update(ledger_items)
            self.reading_ledger = ledger_ref
            if chosen_present:
                parser_dict["chosen_readings"] = chosen_ref
                if chosen_items is not None:
                    chosen_ref.clear()
                    chosen_ref.update(chosen_items)
            else:
                parser_dict.pop("chosen_readings", None)
            unread_ref[:] = unread_items
            guard_ref[:] = guard_items
            self.unread, self.unread_guard = unread_ref, guard_ref
            self._next_observation = next_id
            if trace_present and trace_ref is not None:
                del trace_ref[trace_len:]

        def capacity_hold():
            self._remember_unread({"text": raw, "at": old_count, "까닭": "용량"})
            return {"operator": "relational_graph", "status": "unresolved", "answer": bundle["capacity_reply"],
                    "transitions": [], "meaning": {"act": "hold", "reason": "capacity"},
                    "verification": self._verification(knowledge_path, [{"ok": False, "reason": "capacity",
                                                                         "source": source}])}

        def mismatch():
            raise ReadingUnavailable("structural_binding_mismatch")

        try:
            if bundle["capacity"]:
                return capacity_hold()
            if len(self._obs) != old_count or self._next_observation != next_id:
                mismatch()
            new = Obs(source, TENTATIVE, 1, reading=deepcopy(parsed), reason="candidate_reading")
            try:
                self._commit_observations(list(obs_items) + [new])
            except ValueError as exc:
                if type(exc) is ValueError and exc.args == ("reading_capacity",):
                    rollback()
                    return capacity_hold()
                raise
            current_obs = self._obs
            if type(current_obs) is not list or len(current_obs) != old_count + 1 \
                    or self._next_observation != next_id + 1 or self.reading_ledger is not ledger_ref:
                mismatch()
            actual = current_obs[-1]
            oid = _readings.oid_of(actual)
            if (not isinstance(actual, Obs) or oid != "o%d" % next_id or getattr(actual, "rev", None) != 1
                    or str(actual) != source):
                mismatch()
            for old, kept in zip(obs_items, current_obs[:old_count]):
                if (str(old) != str(kept) or _readings.oid_of(old) != _readings.oid_of(kept)
                        or getattr(old, "rev", None) != getattr(kept, "rev", None)):
                    mismatch()
            if list(ledger_ref) != list(ledger_items) + [oid]:
                mismatch()
            for key, (held, active, count) in ledger_shape.items():
                if ledger_ref[key] is not held or held["active"] != active or len(held["versions"]) != count:
                    mismatch()
            entry = ledger_ref[oid]
            record = self._active_record(actual)
            if (type(entry) is not dict or entry.get("active") != 1 or len(entry["versions"]) != 1
                    or type(record) is not dict or record is not entry["versions"][0]
                    or record.get("observation_id") != oid or record.get("reading_revision") != 1
                    or record.get("source") != source or record.get("unavailable") is not False
                    or record.get("reason") != "candidate_reading" or not equal(record.get("parsed"), parsed)):
                mismatch()
            view = parser_dict.get("chosen_readings")
            if (type(view) is not dict or (chosen_present and view is not chosen_ref) or oid not in view
                    or not equal(view[oid], parsed)):
                mismatch()
            if self._unread_json(record, 65536) is None:
                mismatch()
            obs_ref[:] = list(obs_items) + [actual]
            self._obs = obs_ref
            self._forget_heard({raw})
            pending = {"text": raw, "at": old_count, "말": word, "꼬리": ""}
            self._remember_unread(pending)
            if not any(item is pending for item in self.unread):
                mismatch()
            shaped = self._unread_pending_shape(pending)
            if shaped is None or shaped[0] != "unknown_word":
                mismatch()
            bound = self._unread_pending_unknown_binding(shaped[1])
            if (bound is None or bound["source"] is not actual or bound["record"] is not record
                    or bound["archived"] != source
                    or bound["record"].get("parsed") is not record.get("parsed")):
                mismatch()
            result = {"operator": "relational_graph", "status": "unresolved", "answer": bundle["unknown_reply"],
                      "transitions": [],
                      "meaning": {"act": "hold", "reason": "unknown_word", "word": word, "said": source},
                      "verification": self._verification(knowledge_path, [{"ok": False, "reason": "unknown_word",
                                                                           "source": str(actual)}])}
            for name in ("_replay_cache", "_verb_cache", "_graph_cache"):
                if name in self.__dict__:
                    cache = self.__dict__[name]
                    self.__dict__[name] = {} if type(cache) is dict else [] if type(cache) is list else None
            return result
        except BaseException:
            rollback()
            raise

    def _prepare_structural_observation(self, text, current, parser, verbs):
        """Pure eligibility/preflight for a native structural unknown-action observation.

        Returns None when ineligible, else the evidence bundle. Writes nothing (apart from the
        existing ``_grammar`` fingerprint cache) and publishes no IDs. The predicted next oid is
        used only to shape-check the prospective record and is never returned.
        Owner fields are the actual ones used by ``__init__``/``_archive``/``_commit_observations``:
        ``_next_observation``, ``reading_ledger``, ``max_turns``, ``parser_base_sha256``,
        ``installed_memory_head`` and the parser-owned ``chosen_readings`` view.
        """
        from pack_model import PackModel
        equal = self._unread_native_equal
        if type(self.model) is not PackModel:
            return None
        if not isinstance(text, Obs) or _readings.oid_of(text) != TENTATIVE:
            return None
        if parser is None or parser is not getattr(self, "_parser_instance", None):
            return None
        source = str(text)
        frame = getattr(self, self._UNREAD_FRAME_ATTR, None)
        if not isinstance(frame, dict) or set(frame) != set(self._UNREAD_FRAME_FIELDS):
            return None
        if (frame["source"] is not text or frame["current"] is not current
                or frame["parser"] is not parser or frame["model"] is not self.model
                or type(frame["calls"]) is not int or frame["calls"] != 1
                or frame["nested"] is not False or frame["gap"] is not None):
            return None
        if (self._live() or self.pending_pointer is not None or self.held_question is not None
                or getattr(self, "_in_name_reply", False) or getattr(self, "_rereading", False)):
            return None

        def pair(value):
            return (type(value) is list and len(value) == 2 and all(type(x) is int for x in value)
                    and 0 <= value[0] < value[1] <= len(source))

        grounding = self.model.action_grounding_projection
        if (type(grounding) is not dict or grounding.get("schema") != "pack-action-grounding-projection-v1"
                or grounding.get("status") != "paired" or grounding.get("gaps") != []):
            return None
        projection = grounding.get("projection")
        binding = grounding.get("binding")
        if type(projection) is not dict or type(binding) is not dict:
            return None
        surface = projection.get("surface")
        if type(surface) is not dict:
            return None
        language_pack = parser.language_pack
        declaration = language_pack.get("selected_action_surface") if isinstance(language_pack, dict) else None
        if type(declaration) is not dict or set(declaration) != {"surface", "binding"}:
            return None
        if not equal(declaration, {"surface": surface, "binding": binding}):
            return None

        language = self.model.language_projection
        if type(language) is not dict or language.get("schema") != "graph-dialogue-projection-v1":
            return None
        data = language.get("data")
        replies = data.get("context_replies") if type(data) is dict else None
        installed = parser.data.get("context_replies")
        if type(replies) is not dict or not equal(installed, replies):
            return None
        required = ("observed", "unresolved", "unread_event", "unknown_word", "input_understanding_failed",
                    "no_reading", "ambiguous_reading", "capacity", "invalid", "contradiction")
        if not all(type(replies.get(key)) is str and replies[key].strip() for key in required):
            return None

        # Normal parser container: only one raw 사건, optional entry_selection dict (may be empty).
        if type(current) is not dict:
            return None
        empty_lists = ("facts", "정의", "가정사건", "조건", "가정", "원인", "이유물음", "수선", "사건정정")
        base_keys = set(empty_lists) | {"query", "사건"}
        keys = set(current)
        if keys != base_keys and keys != base_keys | {"entry_selection"}:
            return None
        if any(type(current[key]) is not list or current[key] != [] for key in empty_lists):
            return None
        if current["query"] is not None:
            return None
        if "entry_selection" in current and type(current["entry_selection"]) is not dict:
            return None
        events = current["사건"]
        if type(events) is not list or len(events) != 1 or type(events[0]) is not dict:
            return None
        event = events[0]
        if any(marker in event for marker in ("실행", "program", "negative", "hypothetical", "hypothesis")):
            return None
        if "polarity" in event and event["polarity"] is not True:
            return None
        if "modality" in event and (type(event["modality"]) is not str or event["modality"] != "asserted"):
            return None
        if not equal(event.get("selected_action_binding"), binding):
            return None
        reading = event.get("structural_reading")
        if type(reading) is not dict:
            return None
        if (reading.get("schema") != "unknown-action-reading-v1" or reading.get("status") != "read"
                or reading.get("search_complete") is not True or reading.get("truncated") is not False
                or type(reading.get("gaps")) is not list or reading.get("gaps") != []):
            return None
        surface_id = reading.get("surface_id")
        if "surface_id" not in surface:
            return None
        declared_id = surface["surface_id"]
        if type(surface_id) is not str or not surface_id or not equal(surface_id, declared_id):
            return None
        unknown = reading.get("unknown_text")
        verb = event.get("verb")
        if type(unknown) is not str or not unknown or type(verb) is not str or verb != unknown:
            return None
        if type(event.get("꼬리")) is not str or event["꼬리"] != "" or event.get("잘림") is not False:
            return None

        # Supplied verbs table: a known key or stem rejects (marker-denied lookup is not evidence).
        table = {} if verbs is None else verbs
        if not isinstance(table, dict):
            return None
        if unknown in table:
            return None
        for found in table.values():
            if (found.get("stem") if isinstance(found, dict) else found) == unknown:
                return None

        # Spans: exact Unicode codepoint offsets into str(text).
        unknown_span = reading.get("unknown_span")
        if not pair(unknown_span) or source[unknown_span[0]:unknown_span[1]] != unknown:
            return None
        roles = surface.get("roles")
        if type(roles) is not list or not all(type(role) is dict for role in roles):
            return None
        candidates = reading.get("role_candidates")
        raw_maps = event.get("자리후보")
        raw_shared = event.get("자리")
        if (type(candidates) is not list or not candidates or type(raw_maps) is not list
                or len(raw_maps) != len(candidates) or type(raw_shared) is not dict):
            return None
        declared_keys = ("case_group", "slot", "type_ref", "presence", "coreference_group")
        # Declared role order: distinct non-empty slot names, used for exact omitted-role lists.
        declared_slots = [role.get("slot") for role in roles]
        if (not all(type(slot) is str and slot for slot in declared_slots)
                or len(set(declared_slots)) != len(declared_slots)):
            return None
        maps = []
        for candidate, raw_map in zip(candidates, raw_maps):
            if type(candidate) is not dict or type(raw_map) is not dict:
                return None
            bindings = candidate.get("bindings")
            if type(bindings) is not list or not bindings:
                return None
            seen = set()
            row = {}
            for item in bindings:
                if type(item) is not dict:
                    return None
                slot, value = item.get("slot"), item.get("value")
                if type(slot) is not str or not slot or type(value) is not str or not value:
                    return None
                if slot in seen:
                    return None
                seen.add(slot)
                span = item.get("span")
                if not pair(span) or source[span[0]:span[1]] != value:
                    return None
                marker, chunk = item.get("marker_span"), item.get("chunk_span")
                if not pair(marker) or not pair(chunk):
                    return None
                # Reader emits span=[st,ve], marker_span=[ve,e], chunk_span=[st,e].
                if span[1] != marker[0] or chunk[0] != span[0] or chunk[1] != marker[1]:
                    return None
                matches = [role for role in roles if role.get("slot") == slot]
                if len(matches) != 1:
                    return None
                if not all(equal(item.get(key), matches[0].get(key)) for key in declared_keys):
                    return None
                row[slot] = value
            # F01: exact omitted roles in declaration order; every required role must be bound.
            omitted = [slot for slot in declared_slots if slot not in seen]
            if "omitted_slots" not in candidate or not equal(candidate["omitted_slots"], omitted):
                return None
            if any(role.get("presence") == "required" and role["slot"] not in seen for role in roles):
                return None
            # F02: raw per-candidate slot map must equal the reader-order binding map.
            if not equal(row, raw_map):
                return None
            maps.append(row)
        # F02: raw shared 자리 must equal the identical slot/value intersection across ALL maps,
        # checked here regardless of record fitting/capacity.
        shared = {slot: value for slot, value in maps[0].items()
                  if all(slot in other and other[slot] == value for other in maps[1:])}
        if not equal(shared, raw_shared):
            return None

        # Existing provisional view (parser-owned ``chosen_readings``, read without creating it):
        # absent, or a TENTATIVE entry bounded-native-equal to ``current``. Never overwritten here.
        chosen = parser.__dict__.get("chosen_readings")
        if chosen is not None:
            if not isinstance(chosen, dict):
                return None
            if TENTATIVE in chosen and not equal(chosen[TENTATIVE], current):
                return None

        # Allocator and capacity: the actual ledger owner fields, no fallbacks.
        allocated = self._next_observation
        if type(allocated) is not int or allocated <= 0:
            raise ReadingUnavailable("structural_allocator_invalid")
        oid = "o%d" % allocated
        ledger = self.reading_ledger
        if type(ledger) is not dict:
            raise ReadingUnavailable("structural_allocator_invalid")
        if oid in ledger or any(_readings.oid_of(old) == oid for old in self._obs):
            raise ReadingUnavailable("structural_allocator_invalid")
        max_turns = self.max_turns
        if type(max_turns) is not int or max_turns <= 0:
            raise ReadingUnavailable("structural_capacity_unavailable")
        old_count = len(self._obs)
        versions = sum(len(entry["versions"]) for entry in ledger.values())
        capacity = old_count >= max_turns or versions >= max_turns * 8
        record = _readings.make_record(oid, 1, source, current, base=self.parser_base_sha256,
                                       head=self.installed_memory_head,
                                       reason="candidate_reading", prior=None, unavailable=False,
                                       grammar=self._grammar())
        if self._unread_json(record, 65536) is None:
            capacity = True
        else:
            try:
                self._marked_carrier(current)
            except ReadingUnavailable:
                return None
        return {"source": source, "parsed": current, "word": unknown, "old_count": old_count,
                "capacity": capacity,
                "unknown_reply": replies["unknown_word"].format(말=unknown),
                "capacity_reply": replies["capacity"]}

    def _scoped_admission(self, text, current, parser):
        """Selected signed/conditional scope name after full V4 own-native source verification, else None."""
        text = _scoped_plain(text)
        auth = _scoped_authority(getattr(self.model, "language_projection", None), parser)
        if (auth is None or text is None or type(current) is not dict
                or self._unread_json(auth["data"]["semantic_capabilities"], 65536) is None):
            return None
        facts = current.get("facts") or []
        query = current.get("query") or []
        if current.get("조건") and current.get("condition"):
            return None
        conds = current.get("조건") or current.get("condition") or []
        env = current.get("entry_selection")
        if (type(facts) is not list or type(query) is not list or type(conds) is not list
                or type(env) is not dict
                or set(env) != {"schema", "scope", "status", "coordinate_space", "items", "gaps"}
                or env["schema"] != "marco-entry-selection-v1" or env["scope"] != "known_selected_input_clauses"
                or env["status"] != "partial" or env["coordinate_space"] != "parser_view"
                or type(env["items"]) is not list or type(env["gaps"]) is not list
                or len(env["items"]) != 1 or len(env["gaps"]) > 2):
            return None
        if any(current.get(key) for key in ("사건", "가정사건", "사건정정", "정의", "원인", "이유물음", "events",
                                            "definition", "cause", "reason", "correction", "hypothesis", "가정")):
            return None
        item, gaps = env["items"][0], env["gaps"]
        base = {"clause_ordinal", "span", "compiler_index", "origin", "targets", "derivation"}
        extra = set(item) - base if type(item) is dict else None
        if (extra is None or not base <= set(item) or len(extra) != 1
                or not extra <= {"source_certificate", "source_witness"}
                or type(item["clause_ordinal"]) is not int or type(item["compiler_index"]) is not int
                or type(item["span"]) is not list or len(item["span"]) != 2
                or not all(type(v) is int for v in item["span"])
                or not 0 <= item["span"][0] < item["span"][1] <= len(text)
                or type(item["targets"]) is not dict or set(item["targets"]) != {"facts", "query"}
                or not all(type(v) is list and all(type(i) is int for i in v) for v in item["targets"].values())):
            return None

        def gap_of(code, same):
            return [g for g in gaps if type(g) is dict and set(g) == {"clause_ordinal", "code"}
                    and g["code"] == code and type(g["clause_ordinal"]) is int
                    and (g["clause_ordinal"] == item["clause_ordinal"]) is same]

        unknown = gap_of("origin_unknown", True)
        scopes = gap_of("condition_scope_uncollected", False)
        if (len(unknown) + len(scopes) != len(gaps) or len(unknown) > 1 or len(scopes) > 1
                or (unknown and item["origin"] is not None)):
            return None
        frames = auth["frames"]
        qmarks = [m for m in auth["question_marks"] if type(m) is str and m]

        def declared(key):
            got = frames.get(key)
            return ([m for m in got if type(m) is str and m.strip() and m.strip() == m and m not in qmarks]
                    if type(got) is list else [])

        terms, seps = declared("terminators"), declared("separators")

        def edge(chunk, allowed):
            core = chunk.strip()
            return core == "" or core in allowed

        def evidence_at(row, span):
            ev = row.get("evidence") if type(row) is dict else None
            if not (type(ev) is dict and type(ev.get("start")) is int and type(ev.get("end")) is int
                    and [ev["start"], ev["end"]] == span):
                return False
            plain = _scoped_text(ev.get("text"))
            if plain is None:
                return False
            return plain == text[span[0]:span[1]]

        def plain(part, var_ok=False):
            return (type(part) is str and bool(part.strip()) and "$" not in part
                    and (var_ok or "?" not in part) and not re.fullmatch(r"[+-]?\d+(\.\d+)?", part.strip()))

        def triple_ok(row, var_ok=False):
            t = row.get("triple") if type(row) is dict else None
            return type(t) is list and len(t) == 3 and all(plain(p, var_ok) for p in t)

        native_keys = {"rule", "source", "seed_count", "seed_sha256", "source_ref", "frame_id",
                       "declaration_sha256", "predicate_span", "roles", "markers", "punctuation",
                       "coverage", "inflection", "operators", "scope"}

        def native_ok(der, want, cap):
            # Canonical flat (normalization None) native trace only, positive-fact consequent only,
            # called after independent witness/cert verification. Sole rederivation: pure existing
            # frames._bind_seed_roles on the own-native frame; never _declared_route/parse/events.
            if want is None or type(cap) is not dict or type(der) is not dict or set(der) != native_keys:
                return False
            ok, trace = _scoped_wire(der)
            if not ok or trace["rule"] != "seed-constituents-v2":
                return False
            tsrc = trace["source"]
            if type(tsrc) is not str or not tsrc.strip() or any(q in tsrc for q in qmarks):
                return False
            lo, hi = item["span"]
            core = text[lo:hi]
            lead = len(tsrc) - len(tsrc.lstrip())
            body = tsrc.strip()
            if body != core and not any(body.endswith(m) and body[:-len(m)].rstrip() == core
                                        for m in terms):
                return False
            start = lo - lead
            if start < 0 or text[start:start + len(tsrc)] != tsrc:
                return False
            if not _scoped_native_eq(trace["scope"], [0, len(tsrc)]):
                return False
            ref, fid = trace["source_ref"], trace["frame_id"]
            if (type(ref) is not dict or type(fid) is not str or type(ref.get("index")) is not int
                    or ref["index"] != item["compiler_index"]):
                return False
            compact = _scoped_compact(ref)
            if (compact is None or not _scoped_native_eq(_scoped_resolve(auth["frame_full"], compact), ref)
                    or not any(_scoped_native_eq(compact, r) for r in cap["basis"]["frame_refs"])):
                return False
            decl = deepcopy(frames)
            hits = [i for i, row in enumerate(decl["frames"])
                    if type(row) is dict and type(row.get("id")) is str and row["id"] == fid
                    and _scoped_native_eq(row.get("source_ref"), ref)]
            if len(hits) != 1:
                return False
            from marco.language import frames as _seed_frames
            try:
                res = _seed_frames._select_unique_seed_flat(parser, tsrc, decl)
            except ValueError:
                return False
            if type(res) is not tuple or len(res) != 3 or res[0] != "ok":
                return False
            ok_t, native_trace = _scoped_wire(res[2])
            ok_m, native_meaning = _scoped_wire(res[1])
            ok_w, wanted = _scoped_wire(want)
            return (ok_t and ok_m and ok_w
                    and _scoped_native_eq(native_trace, trace) and _scoped_native_eq(trace, native_trace)
                    and _scoped_native_eq(native_meaning, wanted) and _scoped_native_eq(wanted, native_meaning))

        def derived_ok(src, want=None, cap=None):
            # Called only after pure verification of the 11-key source witness `src`. Entry derivation
            # is the legacy producer's DERIVATION SUMMARY of src's verified normalization; rebuild the
            # exact expected summary from the closed normalization shapes and compare type-sensitively
            # (None vs dict included) over detached string-normalized wire copies. Unknown
            # shapes/ids/repair variants are rejected. No early acceptance. A canonical-flat native
            # seed-constituents-v2 trace is proved separately by native_ok.
            if (type(src) is not dict or len(src) != 11 or "normalization" not in src
                    or _scoped_text(src.get("canonical")) is None):
                return False
            der, norm = item["derivation"], src["normalization"]
            if norm is None and type(der) is dict and der.get("rule") == "seed-constituents-v2":
                return native_ok(der, want, cap)
            if norm is None:
                expected = None
            elif type(norm) is not dict:
                return False
            elif set(norm) == {"id", "canonical", "example_index", "polarity"}:
                if (norm["id"] != "declared-negation-v1" or type(norm["id"]) is not str
                        or _scoped_text(norm["canonical"]) is None
                        or _scoped_text(norm["canonical"]) != _scoped_text(src["canonical"])
                        or type(norm["example_index"]) is not int or type(norm["polarity"]) is not bool):
                    return False
                expected = {"rule": norm["id"], "canonical": src["canonical"]}
            elif set(norm) == {"id", "stem", "tense", "ending", "operations", "example_index"}:
                if (type(norm["id"]) is not str or not norm["id"] or norm["id"] == "declared-negation-v1"
                        or type(norm["example_index"]) is not int
                        or type(norm["stem"]) is not str or type(norm["ending"]) is not str
                        or type(norm["operations"]) is not list):
                    return False
                expected = {"rule": norm["id"], "canonical": src["canonical"], "stem": norm["stem"],
                            "tense": norm["tense"], "ending": norm["ending"],
                            "operations": deepcopy(norm["operations"])}
            else:
                return False
            if expected is None:
                return der is None
            if type(der) is not dict:
                return False
            ok_e, wire_e = _scoped_wire(expected)
            ok_d, wire_d = _scoped_wire(der)
            return (ok_e and ok_d and _scoped_native_eq(wire_e, wire_d)
                    and _scoped_native_eq(wire_d, wire_e))

        if len(facts) == 1 and not query and not conds:
            fact = facts[0]
            cap = _scoped_cap(auth, "negative_binary")
            if (cap is None or scopes or extra != {"source_certificate"} or not triple_ok(fact)
                    or fact.get("unnamed") or fact.get("polarity") is not False
                    or fact.get("modality", "asserted") != "asserted" or any(m in text for m in qmarks)
                    or not _scoped_native_eq(item["targets"], {"facts": [0], "query": []})):
                return None
            got = _scoped_cert(parser, auth, text, item["source_certificate"], "negative_fact", cap,
                               {"triple": list(fact["triple"]), "polarity": False})
            if (got is None or got["compiler_index"] != item["compiler_index"] or got["span"] != item["span"]
                    or not evidence_at(fact, got["span"]) or text[:got["span"][0]].strip()
                    or not edge(text[got["span"][1]:], terms)
                    or not derived_ok(item["source_certificate"]["witness"])):
                return None
            return "negative_fact"
        if len(query) == 1 and not facts and not conds:
            asked = query[0]
            cap = _scoped_cap(auth, "negative_binary")
            if (cap is None or scopes or extra != {"source_certificate"} or type(asked) is not dict
                    or set(asked) != {"triple", "render", "polarity"} or asked["polarity"] is not False
                    or not triple_ok(asked, True)
                    or not _scoped_native_eq(item["targets"], {"facts": [], "query": [0]})):
                return None
            triple, render = asked["triple"], asked["render"]
            if (sum(p.startswith("?") for p in (triple[0], triple[2])) != 1 or "?" in triple[1]
                    or type(render) is not list or not render or not all(type(r) is str for r in render)):
                return None
            got = _scoped_cert(parser, auth, text, item["source_certificate"], "negative_query", cap,
                               {"query": [deepcopy(asked)]})
            derived = got["source_ref"].get("negative_derivation") if got is not None else None
            if (got is None or got["compiler_index"] != item["compiler_index"] or got["span"] != item["span"]
                    or type(derived) is not dict or derived.get("capability_sha256") != cap["capability_sha256"]
                    or text[:got["span"][0]].strip() or not edge(text[got["span"][1]:], terms + qmarks)
                    or not derived_ok(item["source_certificate"]["witness"])):
                return None
            return "negative_query"
        if len(facts) == 1 and not query and len(conds) == 1:
            fact, cond = facts[0], conds[0]
            cap = _scoped_cap(auth, "conditional_binary")
            if (cap is None or len(scopes) != 1 or scopes[0]["clause_ordinal"] >= item["clause_ordinal"]
                    or extra != {"source_witness"} or not triple_ok(fact) or not triple_ok(cond)
                    or fact.get("unnamed") or fact.get("polarity", True) is not True
                    or fact.get("modality", "asserted") != "asserted" or cond.get("polarity", True) is not True
                    or _scoped_plain(cond.get("source_original")) != text or any(m in text for m in qmarks)
                    or not _scoped_native_eq(item["targets"], {"facts": [0], "query": []})):
                return None
            g_cert = cond.get("source_certificate")
            g_wit = g_cert.get("witness") if type(g_cert) is dict else None
            g_meaning = _scoped_positive_meaning(g_wit.get("meaning") if type(g_wit) is dict else None,
                                                 cond["triple"])
            if g_meaning is None:
                return None
            guard = _scoped_cert(parser, auth, text, g_cert, "positive_guard", cap, g_meaning)
            if guard is None or not evidence_at(cond, guard["span"]):
                return None
            witness = item["source_witness"]
            witnessed = getattr(parser, "verify_selected_binary_witness", None)
            want = _scoped_positive_meaning(witness.get("meaning") if type(witness) is dict else None,
                                            fact["triple"])
            if (want is None or not callable(witnessed) or type(witness) is not dict or len(witness) != 11
                    or type(witness.get("source")) is not str or not witness["source"].strip()
                    or not _scoped_native_eq(witness.get("meaning"), want)):
                return None
            seen = witnessed(witness["source"], witness, "positive_fact")
            full = seen.get("source_ref") if type(seen) is dict else None
            compact = _scoped_compact(full)
            if (type(seen) is not dict
                    or set(seen) != {"source_ref", "compiler_index", "meaning", "capability_sha256"}
                    or seen["capability_sha256"] != cap["capability_sha256"]
                    or not _scoped_native_eq(seen["meaning"], want) or compact is None
                    or not _scoped_native_eq(_scoped_resolve(auth["frame_full"], compact), full)
                    or not any(_scoped_native_eq(compact, r) for r in cap["basis"]["frame_refs"])
                    or type(seen["compiler_index"]) is not int or seen["compiler_index"] != full["index"]
                    or seen["compiler_index"] != item["compiler_index"]):
                return None
            (g_lo, g_hi), (c_lo, c_hi) = guard["span"], item["span"]
            if (not g_hi <= c_lo or text[c_lo:c_hi] != witness["source"] or not evidence_at(fact, item["span"])
                    or text[:g_lo].strip() or not edge(text[g_hi:c_lo], seps) or not edge(text[c_hi:], terms)
                    or not derived_ok(witness, want, cap)):
                return None
            return "conditional"
        return None

    def _selected_positive_query_input(self, parser, text, current):
        """True only for a parser-proved, independently re-verified canonical selected original positive query.

        Bounded per-turn source validation only: never parses, evaluates, asserts or completes an answer.
        """
        source = _scoped_text(text)
        if source is None:
            return False
        try:
            if len(source.encode("utf-8")) > 65536:
                return False
        except UnicodeEncodeError:
            return False
        keys = {"facts", "query", "정의", "사건", "가정사건", "조건", "가정", "원인", "이유물음", "수선",
                "사건정정", "entry_selection"}
        if type(current) is not dict or set(current) != keys:
            return False
        size = _scoped_size(current)
        if size is None or size > 65536:
            return False
        for key in keys - {"query", "entry_selection"}:
            if type(current[key]) is not list or current[key]:
                return False
        query = current["query"]
        if type(query) is not list or len(query) != 1:
            return False
        row = query[0]
        if type(row) is not dict or set(row) != {"triple", "render"}:
            return False
        triple, render = row["triple"], row["render"]
        if (type(triple) is not list or len(triple) != 3
                or not all(type(t) is str and t.strip() for t in triple)
                or any("$" in t for t in triple) or "?" in triple[1]
                or sum(1 for t in (triple[0], triple[2]) if t.startswith("?")) != 1
                or sum(t.count("?") for t in triple) != 1):
            return False
        if type(render) is not list or not render or not all(type(r) is str for r in render):
            return False
        projection = getattr(self.model, "language_projection", None)
        auth = _scoped_authority(projection, parser)
        if auth is None:
            return False
        neg = _scoped_cap(auth, "negative_binary")
        if neg is None or _scoped_cap(auth, "conditional_binary") is None:
            return False
        env = current["entry_selection"]
        if (type(env) is not dict
                or set(env) != {"schema", "scope", "status", "coordinate_space", "items", "gaps"}
                or not all(_scoped_native_eq(env[k], v) for k, v in (
                    ("schema", "marco-entry-selection-v1"), ("scope", "known_selected_input_clauses"),
                    ("status", "partial"), ("coordinate_space", "parser_view")))):
            return False
        items, gaps = env["items"], env["gaps"]
        if type(items) is not list or len(items) != 1 or type(gaps) is not list:
            return False
        item = items[0]
        if (type(item) is not dict
                or set(item) != {"clause_ordinal", "span", "compiler_index", "origin", "targets", "derivation"}
                or type(item["clause_ordinal"]) is not int or item["clause_ordinal"] != 0
                or type(item["compiler_index"]) is not int or item["compiler_index"] < 0
                or type(item["span"]) is not list or len(item["span"]) != 2
                or not all(type(v) is int for v in item["span"])
                or not 0 <= item["span"][0] < item["span"][1] <= len(source)
                or not _scoped_native_eq(item["targets"], {"facts": [], "query": [0]})
                or item["derivation"] is not None):
            return False
        origin = item["origin"]
        if origin is None:
            if not _scoped_native_eq(gaps, [{"clause_ordinal": 0, "code": "origin_unknown"}]):
                return False
        else:
            if gaps or type(origin) is not dict or origin.get("graph_binding") is None:
                return False
            from marco.language.entry_origins import validated_entry_origin
            try:
                checked = validated_entry_origin(origin)
            except (ValueError, TypeError):
                return False
            if not _scoped_native_eq(checked, origin):
                return False
        pack = projection["language_pack"]
        slots = pack.get("slot_particles", [])
        counters = pack.get("counters", {})
        if counters is None:
            counters = {}
        pointers = pack.get("pointers", [])
        if (type(slots) is not list or type(counters) is not dict or type(pointers) is not list
                or not all(_scoped_wire(v)[0] for v in (slots, counters, pointers))
                or not _scoped_native_eq(getattr(parser, "slot_particles", None), slots)
                or not _scoped_native_eq(getattr(parser, "counters", None), counters)
                or not _scoped_native_eq(getattr(parser, "pointers", None), pointers)):
            return False
        native, held = auth["data"], parser.data
        mine_num, held_num = native.get("numerals", {}), held.get("numerals", {})
        if (type(mine_num) is not dict or type(held_num) is not dict or not _scoped_wire(mine_num)[0]
                or not _scoped_native_eq(mine_num, held_num)
                or ("ignore_case" in native) != ("ignore_case" in held)):
            return False
        if "ignore_case" in native and (type(native["ignore_case"]) is not bool
                                        or not _scoped_native_eq(native["ignore_case"], held["ignore_case"])):
            return False
        verify = getattr(parser, "verify_selected_positive_query", None)
        if not callable(verify):
            return False
        from marco.reasoning import query_work as _qw
        work = getattr(self, "_query_work", None)
        if type(work) is not dict:
            work = _qw.new_query_work(deepcopy(query))
        work, allowed = _qw.claim_validation(work)
        self._query_work = work
        if allowed is not True:
            return False
        accepted, evidence = self._positive_query_proof_ok(
            verify, parser, source, current, row, item, auth, neg, env)
        accepted = accepted is True
        self._query_work = _qw.finish_validation(
            work, accepted, evidence if accepted else None,
            None if accepted else "input_understanding_failed")
        return accepted

    def _positive_query_proof_ok(self, verify, parser, source, current, row, item, auth, neg, env):
        """(True, compact own source ref) when the parser proof survives all independent checks, else (False, None)."""
        proof = verify(source, deepcopy(current))
        if proof is None or proof is False:
            return False, None
        ok, proof = _scoped_wire(proof)
        if not ok or type(proof) is not dict or set(proof) != {"compiler_index", "source_ref", "meaning", "source_span"}:
            return False, None
        size = _scoped_size(proof)
        if size is None or size > 65536:
            return False, None
        index = proof["compiler_index"]
        if type(index) is not int or index != item["compiler_index"]:
            return False, None
        full = proof["source_ref"]
        if type(full) is not dict or type(full.get("index")) is not int or full["index"] != index:
            return False, None
        compact = _scoped_compact(full)
        if compact is None or compact["index"] != index:
            return False, None
        own = _scoped_resolve(auth["original_full"], compact)
        if own is None or not _scoped_native_eq(own, full) or not _scoped_native_eq(full, own):
            return False, None
        if sum(1 for r in auth["original_full"] if _scoped_native_eq(_scoped_compact(r), compact)) != 1:
            return False, None
        if not any(_scoped_native_eq(compact, r) for r in neg["basis"]["original_query_refs"]):
            return False, None
        if not any(type(r) is dict and "negative_derivation" not in r and _scoped_native_eq(r, own)
                   for r in auth["derived_full"]):
            return False, None
        mine = auth["data"].get("examples")
        held = parser.data.get("examples")
        if (type(mine) is not list or type(held) is not list or not 0 <= index < len(mine)
                or index >= len(held) or not _scoped_native_eq(mine[index], held[index])):
            return False, None
        if own.get("annotation_sha256") != _scoped_sha(mine[index]):
            return False, None
        meaning = proof["meaning"]
        if (type(meaning) is not dict or set(meaning) != {"query"} or type(meaning["query"]) is not list
                or len(meaning["query"]) != 1 or not _scoped_native_eq(meaning["query"][0], row)):
            return False, None
        span = proof["source_span"]
        if (type(span) is not list or len(span) != 2 or not all(type(s) is int for s in span)
                or not 0 <= span[0] < span[1] <= len(source)):
            return False, None
        if not _scoped_native_eq(item["span"], span):
            return False, None
        lo, hi = span
        core = source[lo:hi]
        if not core.strip() or core != core.strip() or source[:lo].strip():
            return False, None
        tail = source[hi:].strip()
        terms = auth["frames"].get("terminators")
        terms = terms if type(terms) is list else []
        marks = [m for m in terms + list(auth["question_marks"])
                 if type(m) is str and m and m.strip() == m]
        if tail and tail not in marks:
            return False, None
        return True, compact

    def _selected_negative_answer_input(self, parser, text, current, facts, query):
        """Answer input: ordinary dict unchanged; a scoped signed-negative query only with its re-verified proof."""
        env = current.get("entry_selection") if type(current) is dict else None
        items = env.get("items") if type(env) is dict else None
        claimed = type(items) is list and any(type(i) is dict and "source_certificate" in i for i in items)
        signed = type(query) is list and any(type(q) is dict and q.get("polarity") is False for q in query)
        if not claimed or not signed:
            return {"facts": facts, "query": query}
        source = _scoped_plain(text)
        if (source is None or type(current.get("query")) is not list or len(query) != 1
                or not _scoped_native_eq(query, current["query"])
                or self._scoped_admission(source, current, parser) != "negative_query"):
            return None
        cert = items[0].get("source_certificate") if len(items) == 1 and type(items[0]) is dict else None
        if type(cert) is not dict:
            return None
        return {"facts": facts, "query": query,
                "selected_query_source": {"source_original": source, "source_certificate": deepcopy(cert)}}

    def _selected_conditional_status_reply(self, text, knowledge_path, current, parser, facts, pending):
        """Hold reply for one ordinary query about the consequent of one archived selected conditional.

        Routes an actual typed-binary conditional whose guard is False or unmeasured (None) to the existing
        native condition_false/unmeasured_condition replies. Never asserts, settles or replays anything new;
        any unsupported state returns None (existing routing).
        """
        # Refuse any live/unread/rereading conversation state before closure, read or replay.
        if (self.unread or self.unread_guard or self._live() or self.fills
                or getattr(self, "_rereading", False) or getattr(self, "_in_name_reply", False)):
            return None
        keys = {"facts", "query", "정의", "사건", "가정사건", "조건", "가정", "원인", "이유물음", "수선",
                "사건정정", "entry_selection"}
        advanced = keys - {"facts", "query", "entry_selection"}
        # Exact current shape (same accepted shape as the selected-query source proof).
        if type(current) is not dict or set(current) != keys:
            return None
        for key in keys - {"query", "entry_selection"}:
            if type(current[key]) is not list or current[key]:
                return None
        query = current["query"]
        if type(query) is not list or len(query) != 1:
            return None
        row = query[0]
        if type(row) is not dict or set(row) != {"triple", "render"}:
            return None
        asked, render = row["triple"], row["render"]
        if (type(asked) is not list or len(asked) != 3
                or not all(type(t) is str and t.strip() for t in asked)
                or any("$" in t for t in asked) or "?" in asked[1]
                or sum(1 for t in (asked[0], asked[2]) if t.startswith("?")) != 1
                or sum(t.count("?") for t in asked) != 1):
            return None
        if type(render) is not list or not render or not all(type(r) is str for r in render):
            return None
        projection = getattr(self.model, "language_projection", None)
        data = projection.get("data") if type(projection) is dict else None
        if type(data) is not dict:
            return None
        asked = list(asked)
        if pending is not None and type(pending) is not list:
            return None
        pending = list(pending or [])
        if len(pending) > 1:
            return None
        observations = list(self.observations)
        if not observations or len(observations) > self.max_turns:
            return None
        chosen = getattr(parser, "chosen_readings", None)
        if type(chosen) is not dict:
            return None
        # Every source must already own an exact archived chosen native reading before any read/replay.
        for obs in observations:
            if not isinstance(obs, Obs):
                return None
            oid = _readings.oid_of(obs)
            rev = getattr(obs, "rev", None)
            if (type(oid) is not str or not oid.strip() or oid == TENTATIVE
                    or type(rev) is not int or rev < 1
                    or getattr(obs, "reading", None) is not None
                    or getattr(obs, "reason", None) == "correction"):
                return None
            entry = self.reading_ledger.get(oid)
            if type(entry) is not dict:
                return None
            active, versions = entry.get("active"), entry.get("versions")
            if (type(active) is not int or active != rev or type(versions) is not list
                    or not 1 <= active <= len(versions)):
                return None
            record = self._active_record(obs)
            view = chosen.get(oid)
            if (type(record) is not dict
                    or type(record.get("observation_id")) is not str or record.get("observation_id") != oid
                    or type(record.get("reading_revision")) is not int or record.get("reading_revision") != rev
                    or record.get("unavailable") is not False
                    or type(record.get("source")) is not str or record.get("source") != str(obs)
                    or view is None or self._structural_marked(view)
                    or self._unread_json(record.get("parsed"), 65536) is None
                    or not self._unread_native_equal(view, record.get("parsed"))):
                return None
            parsed = record.get("parsed")
            if type(parsed) is not dict or set(parsed) != keys or not _scoped_native_eq(view, parsed):
                return None
        from marco.reasoning.inference import bind as _bind
        read = [self._read_source(parser, obs) for obs in observations]
        matched = []
        for index, (obs, stored) in enumerate(zip(observations, read)):
            if type(stored) is not dict or set(stored) != keys:
                return None
            if (type(stored["facts"]) is not list or stored["query"] is not None
                    or any(type(stored[key]) is not list for key in advanced)
                    or any(stored[key] for key in advanced - {"조건"})):
                return None
            conds = stored["조건"]
            if not conds:
                continue
            if self._scoped_admission(obs, stored, parser) != "conditional":
                return None
            rows = stored["facts"]
            if len(conds) != 1 or len(rows) != 1:
                return None
            guard, fact = conds[0], rows[0]
            if (type(guard) is not dict or type(guard.get("triple")) is not list
                    or "evidence" not in guard or type(fact) is not dict):
                return None
            triple = fact.get("triple")
            if (type(triple) is not list or len(triple) != 3
                    or not all(type(t) is str and t.strip() for t in triple)
                    or fact.get("polarity", True) is not True
                    or fact.get("modality", "asserted") != "asserted"
                    or type(fact.get("modality", "asserted")) is not str):
                return None
            if triple[1] == asked[1] and _bind(asked, list(triple), {}) is not None:
                matched.append((index, obs, conds, fact))
        if len(matched) != 1:
            return None
        index, source, conds, fact = matched[0]
        evidence = fact.get("evidence")
        start = evidence.get("start") if type(evidence) is dict else None
        if type(start) is not int:
            return None
        guard = conds[0]

        def same_source(other):
            return (other is source
                    or (isinstance(other, Obs) and type(_readings.oid_of(other)) is str
                        and _readings.oid_of(other) == _readings.oid_of(source)
                        and type(getattr(other, "rev", None)) is int
                        and getattr(other, "rev", None) == getattr(source, "rev", None)
                        and str(other) == str(source)))

        fields = {"text", "at", "동사", "id", "잘림", "차례", "못잼", "조각", "자리", "빈자리", "충돌", "헛자리",
                  "닿는곳"}
        for item in pending:
            if (type(item) is not dict or set(item) != fields
                    or type(item["at"]) is not int or item["at"] != index
                    or not same_source(item["text"])):
                return None
        prior, _d, _p, _r = self._cached_replay(parser, observations[:index], [])
        diagnosis = {}
        result = self._holds(parser, conds, start, prior, projection, actual_source=source,
                             evidence_out=diagnosis)
        if result is True:
            return None
        if result is False:
            if pending:
                return None
            reason = "condition_false"
        elif result is None:
            if len(pending) != 1:
                return None
            item = pending[0]
            if (item["동사"] is not None or item["id"] is not None or item["잘림"] is not False
                    or type(item["차례"]) is not int or item["차례"] != index
                    or type(item["못잼"]) is not str or item["못잼"] != "condition_unknown"
                    or any(type(item[key]) is not dict or item[key]
                           for key in ("자리", "빈자리", "충돌", "헛자리"))
                    or not _scoped_native_eq(item["조각"], guard["evidence"])
                    or not _scoped_native_eq(item["닿는곳"], [guard["triple"]])):
                return None
            reason = self._못잰까닭("condition_unknown")
        else:
            return None
        if type(reason) is not str or reason not in ("condition_false", "unmeasured_condition"):
            return None
        # Eligible status established: host closure callbacks stay owned by the original answer route.
        if (getattr(parser, "rule_selector", None) is not None
                or getattr(parser, "closure_selector", None) is not None
                or getattr(parser, "closure_recorder", None) is not None):
            return None
        from marco.reasoning.inference import current_facts as _current_facts
        state, _changes = _current_facts(facts, parser.data.get("mutable_predicates", []),
                                         parser.data.get("numeric_updates", {}))
        known = parser._closure(state)
        for key in known:
            if _bind(asked, list(key), {}) is not None:
                return None
        if self._selected_positive_query_input(parser, text, current) is not True:
            return self._graph_dialogue_gap(text, knowledge_path, unsupported=["query_pending"])
        installed = parser.data.get("context_replies")
        native = data.get("context_replies")
        if type(installed) is not dict or type(native) is not dict or not _scoped_native_eq(installed, native):
            return self._graph_dialogue_gap(text, knowledge_path, unsupported=["reply_authority"])
        evidence = None
        if (result is None and reason == "unmeasured_condition"
                and set(diagnosis) == {"outcome", "guard_ref", "positive_support", "negative_support"}
                and _scoped_compact_ok(diagnosis["guard_ref"])
                and type(diagnosis["positive_support"]) is bool and type(diagnosis["negative_support"]) is bool):
            outcome = diagnosis["outcome"]
            pos, neg = diagnosis["positive_support"], diagnosis["negative_support"]
            if ((outcome == "missing_premise" and pos is False and neg is False)
                    or (outcome == "conflicting_evidence" and pos is True and neg is True)):
                evidence = {"scope": "selected_binary_guard", "outcome": outcome,
                            "guard_ref": deepcopy(diagnosis["guard_ref"]),
                            "positive_support": pos, "negative_support": neg}
        if evidence is not None:
            return self._failure_dispatch(text, knowledge_path, deepcopy(current["query"]), evidence,
                                          installed, source, True)
        reply = installed.get(reason)
        if type(reply) is not str or not reply.strip():
            return self._graph_dialogue_gap(text, knowledge_path, missing_replies=[reason])
        self.held_question = text
        return {"operator": "relational_graph", "status": "unresolved",
                "answer": reply.format(말=str(source).strip()), "transitions": [],
                "meaning": {"act": "hold", "reason": reason, "said": str(source),
                            "conversation": self.conversation_id},
                "verification": self._verification(knowledge_path, [])}

    def _failure_dispatch(self, text, knowledge_path, query, evidence, replies, said, hold):
        """Claim one bounded failure-response operation, then build the existing native reply for its action."""
        import hashlib
        from marco.reasoning.query_work import (new_thinking_work, choose_thinking_operation,
                                                finish_thinking_operation)
        work = self.__dict__.get("_thinking_work")
        if work is None:
            digest = hashlib.sha256(str(text).encode("utf-8", "surrogatepass")).hexdigest()
            work = new_thinking_work({"input_sha256": digest, "query": query}, evidence)
        work, action = choose_thinking_operation(work)
        self._thinking_work = deepcopy(work)
        if action is None:
            return self._graph_dialogue_gap(text, knowledge_path, unsupported=["capacity"])
        branches = {"emit_existing_gap": "input_understanding_failed",
                    "emit_existing_information_gap": "unmeasured_condition",
                    "emit_existing_conflict": "contradiction"}
        if type(action) is not str or action not in branches:
            raise RuntimeError("failure response action mismatch")
        if type(replies) is not dict:
            return self._graph_dialogue_gap(text, knowledge_path, unsupported=["reply_authority"])
        key = branches[action]
        reply = replies.get(key)
        if type(reply) is not str or not reply.strip():
            return self._graph_dialogue_gap(text, knowledge_path, missing_replies=[key])
        response = {"operator": "relational_graph", "status": "unresolved",
                    "answer": reply.format(말=str(said).strip()), "transitions": [],
                    "meaning": {"act": "hold", "reason": branches[action], "said": str(said),
                                "conversation": self.conversation_id},
                    "verification": self._verification(knowledge_path, [])}
        self._thinking_work = deepcopy(finish_thinking_operation(work, action))
        if hold:
            self.held_question = text
        return response

    def _graph_dialogue_guard(self, text, knowledge_path, current, parser):
        from pack_model import PackModel
        if type(self.model) is not PackModel or self.model.language_projection is None:
            return None
        unsupported = []
        facts = (current or {}).get("facts") or []
        query = (current or {}).get("query") or []
        if current is None:
            if self._live():
                unsupported.append("active_clarification")
        else:
            scoped = self._scoped_admission(text, current, parser)
        if current is not None and scoped is not None:
            if scoped == "negative_query":
                _f, _d, pending, _r = self._cached_replay(parser, self.observations, self.fills)
                if pending and self._unsettled(query, parser, pending) is not None:
                    unsupported.append("query_pending")
            elif self._state_completion(current, self._live()) is not None:
                unsupported.append("state_completion")
        elif current is not None:
            if any(current.get(key) for key in ("사건", "가정사건", "사건정정", "정의", "원인", "이유물음", "조건",
                                                "events", "definition", "cause", "reason", "correction",
                                                "condition", "hypothesis", "가정")):
                unsupported.append("advanced_input")
            batch = len(facts) == 2 and not query and self._fact_batch_admissible(text, current, parser)
            if len(facts) + len(query) != 1 and not batch:
                unsupported.append("multiclause")
            elif facts:
                fact = facts[0] if isinstance(facts[0], dict) else {}
                triple = fact.get("triple")
                value = triple[2] if isinstance(triple, (list, tuple)) and len(triple) == 3 else None
                if (not isinstance(facts[0], dict) or fact.get("unnamed") or not isinstance(value, str)
                        or fact.get("polarity", True) is not True
                        or fact.get("modality", "asserted") != "asserted"
                        or re.fullmatch(r"[+-]?\d+(\.\d+)?", value.strip())
                        or (isinstance(triple[0], str) and re.fullmatch(r"[+-]?\d+(\.\d+)?", triple[0].strip()))
                        or not all(isinstance(part, str) and part.strip() and "$" not in part
                                   and "?" not in part for part in triple)):
                    unsupported.append("advanced_input")
                elif self._state_completion(current, self._live()) is not None:
                    unsupported.append("state_completion")
            else:
                asked = query[0]
                triple = asked.get("triple") if isinstance(asked, dict) else None
                render = asked.get("render") if isinstance(asked, dict) else None
                if (not isinstance(triple, (list, tuple)) or len(triple) != 3
                        or set(asked) - {"triple", "render"}
                        or not all(isinstance(part, str) and part.strip() for part in triple)
                        or sum(part.startswith("?") for part in (triple[0], triple[2])) != 1
                        or triple[1].startswith("?") or "$" in triple[1]
                        or any("$" in part for part in triple)
                        or re.fullmatch(r"[+-]?\d+(\.\d+)?", triple[0].strip())
                        or re.fullmatch(r"[+-]?\d+(\.\d+)?", triple[2].strip())
                        or not isinstance(render, list) or not render
                        or not all(isinstance(item, str) for item in render)):
                    unsupported.append("advanced_input")
                else:
                    _f, _d, pending, _r = self._cached_replay(parser, self.observations, self.fills)
                    held = self._selected_conditional_status_reply(text, knowledge_path, current, parser,
                                                                   _f, pending)
                    if held is not None:
                        return held
                    if pending and self._unsettled(query, parser, pending) is not None:
                        unsupported.append("query_pending")
        if unsupported:
            return self._graph_dialogue_gap(text, knowledge_path, unsupported=unsupported)
        return None

    @staticmethod
    def _is_statement(parsed):
        """A reading that states facts the state records (an event of a learned verb, a definition, a
        condition or a question is not one this check chooses between)."""
        return bool(parsed) and bool(parsed.get("facts")) and not any(
            parsed.get(key) for key in ("query", "사건", "사건정정", "정의", "원인", "이유물음", "조건", "가정사건"))

    def _thing_as_holder(self, parser, rows):
        """G5.4 B, the constraint ``kinds``: a row of a reading whose holder begins with a word the conversation
        already counts as a thing (the last word of a counted state key)."""
        if not self.observations:
            return False
        try:
            facts, _d, _p, _r = self._cached_replay(parser, self.observations, self.fills)
        except ValueError:
            return False
        numeric = self._numeric_targets(parser)
        things = {str(f["triple"][0]).split()[-1] for f in facts
                  if isinstance(f["triple"][0], str) and len(str(f["triple"][0]).split()) >= 2
                  and f["triple"][1] in numeric}
        return any(isinstance(row[0], str) and len(row[0].split()) >= 2
                   and row[0].split()[0] in things for row in rows)

    def _reading_failure(self, parser, text, parsed):
        """``(failure, changes)``: the first constraint (``READING_CONSTRAINTS``) the conversation breaks with
        ``parsed`` as the reading of ``text``, as ``(constraint, reason)``, or None when every one holds with
        it; and the state rows the reading would record (``current_facts``' changes of this statement)."""
        if not self._is_statement(parsed):
            return ("statement", "not_a_statement"), []
        if self._holder_unsaid(parser, text, parsed):
            return ("one_subject", "ambiguous_quantity_subject"), []
        rows = [f["triple"] for f in parsed.get("facts", []) if isinstance(f.get("triple"), list)]
        updates = parser.data.get("numeric_updates") or {}
        removed = {str(t[0]).split()[0] for t in rows if isinstance(t[0], str) and t[1] in updates
                   and float((updates[t[1]] or {}).get("factor", 1) or 1) < 0}
        added = {str(t[0]).split()[0] for t in rows if isinstance(t[0], str) and t[1] in updates
                 and float((updates[t[1]] or {}).get("factor", 1) or 1) > 0}
        if removed and removed == added:
            return ("frame", "same_holder"), []
        if self._thing_as_holder(parser, rows):
            return ("kinds", "thing_as_holder"), []
        text = _readings.tentative(text)
        key = text.oid
        table = parser.__dict__.setdefault("chosen_readings", {})
        before = table.get(key)
        table[key] = parsed
        index = len(self.observations)
        try:
            facts, _d, _p, _r = self._replay(parser, self.observations + [text], self.fills,
                                             deepcopy(self.event_ids) if self.event_ids is not None else None,
                                             projection=getattr(self.model, "language_projection", None))
            facts = self._unit_keys(parser, self._bind_unnamed_counts(parser, [], facts, getattr(self, "bind_hints", [])))
            _state, changes = current_facts(facts, parser.data.get("mutable_predicates", []), updates)
            if self._unit_kinds_differ(parser, facts, index) is not None:
                raise ValueError("unit_mismatch")
        except ReadingUnavailable:
            # a missing historical reading is not a constraint this statement breaks
            raise
        except ValueError as exc:
            reason = str(exc).split(":")[0]
            return (CONSTRAINT_OF.get(reason, "readable"), reason), []
        finally:
            if before is None:
                table.pop(key, None)
            else:
                table[key] = before
        mine = [deepcopy(row) for row in changes if (row.get("evidence") or {}).get("turn") == index
                and row.get("operation") in ("state_update", "quantity_update")]
        if self._pointer_unknown(parser, mine):
            return ("holder_exists", "missing_initial_quantity"), []
        return None, mine

    @staticmethod
    def _pointer_unknown(parser, changes):
        """A count not known started for a holder that is a pointer as written (the pack's 지시어: he, 그분):
        a pointer names someone already said, never a new holder; the pointer readings choose whom."""
        pointers = [w.lower().split() for w in parser.pointers or [] if w]
        return any(row.get("operation") == "quantity_update" and row.get("before") is None
                   and row.get("after") is None and isinstance(row.get("subject"), str)
                   and any(row["subject"].lower().split()[:len(p)] == p for p in pointers)
                   for row in changes)

    def _pointer_readings(self, parser, readings):
        """G5.3: a statement whose holder is a person pointer (the pack's 사람지시어: he, she, 그분) is read
        once for each person the conversation named who holds the same thing: never the speaker, never a place,
        never a person the same statement names (a pointer and a name in one clause are two people). Each is one
        more reading after the reader's own; the constraints choose, and two that fit are asked back."""
        pointers = sorted({w.lower() for w in (parser.language_pack or {}).get("person_pointers") or [] if w},
                          key=len, reverse=True)
        if not pointers or not readings or not self.observations:
            return []
        facts, _d, _p, _r = self._cached_replay(parser, self.observations, self.fills)
        speaker = (parser.speaker_placeholder or "").lower()
        places = {place for item in facts for place in item.get("places") or [] if isinstance(place, str)}
        known = []
        for item in facts:
            name = item["triple"][0]
            if isinstance(name, str) and name not in known:
                known.append(name)
        out = []
        for reading in readings:
            rows = reading["parsed"].get("facts", [])
            for row in rows:
                subject = row["triple"][0]
                words = subject.split() if isinstance(subject, str) else []
                pointer = next((w for w in pointers
                                if [x.lower() for x in words[:len(w.split())]] == w.split()), None)
                if pointer is None:
                    continue
                tail = " ".join(words[len(pointer.split()):])

                def holder(name):
                    return name[:-len(tail)].strip() if tail and name.endswith(" " + tail) else name.split()[0]
                named = {holder(str(r["triple"][0])).lower() for r in rows
                         if isinstance(r["triple"][0], str) and r["triple"][0] != subject}
                for name in known:
                    who = holder(name)
                    if (tail and not name.endswith(" " + tail)) or not who or who.lower() == speaker \
                            or who.lower() in named or who.lower() in pointers \
                            or any(name == place or name.startswith(place + " ") for place in places):
                        continue
                    parsed = deepcopy(reading["parsed"])
                    for fact in parsed.get("facts", []):
                        if fact["triple"][0] == subject:
                            fact["triple"][0] = name
                    said = re.sub(r"(?<!\w)%s(?!\w)" % re.escape(pointer), who, reading["said"], count=1,
                                  flags=re.IGNORECASE)
                    out.append({**reading, "parsed": parsed,
                                "said": said if said != reading["said"] else "%s [%s]" % (reading["said"], who)})
                break
        return out

    def _check_readings(self, parser, text, verbs, knowledge_path, first_failure=None):
        """G5.4 B: every reading the reader gives for a statement it could not apply (or left unread for a
        clause read two ways at one rank), each checked against the state (``READING_CONSTRAINTS``, in order).
        One reading of the best tier left: the turn is played again with it (the choice is kept for replay).
        Several that would record different things: the turn asks which (``ambiguous_reading``, request W5-2).
        None, when the reader had readings to choose between: the turn holds (``no_reading``) with each
        reading's failure. With nothing to choose between: None, and the caller holds as before. The dropped
        readings and their reasons go to the trace and the checks."""
        # the reader's readings that state something; with fewer than two there is nothing to choose between
        import inspect
        extra = {}
        try:
            parse_has = inspect.signature(parser.parse).parameters.get("_entry_selection")
            read_params = inspect.signature(parser.readings).parameters
        except (TypeError, ValueError):
            parse_has, read_params = None, {}
        keyword_kinds = (inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY)
        read_has = read_params.get("_entry_selection")
        if parse_has is not None and parse_has.kind in keyword_kinds and (
                (read_has is not None and read_has.kind in keyword_kinds)
                or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in read_params.values())):
            extra["_entry_selection"] = True
        readings = [r for r in parser.readings(text, partial=True, events=True, repair=True, verbs=verbs, **extra)
                    if self._is_statement(r["parsed"])]
        pointed = self._pointer_readings(parser, readings)
        for pointer_reading in pointed:
            parsed = pointer_reading.get("parsed")
            capsule = parsed.get("entry_selection") if isinstance(parsed, dict) else None
            if isinstance(capsule, dict) and capsule.get("schema") == "marco-entry-selection-v1" \
                    and capsule.get("scope") == "known_selected_input_clauses" \
                    and capsule.get("status") == "partial" and capsule.get("coordinate_space") == "parser_view" \
                    and isinstance(capsule.get("gaps"), list):
                capsule = deepcopy(capsule)
                capsule["gaps"].append({"clause_ordinal": None, "code": "referent_resolution_uncollected"})
                pointer_reading["parsed"] = dict(parsed, entry_selection=capsule)
        readings += pointed
        if first_failure is None and len(readings) < 1:
            return None
        if first_failure is not None and len(readings) < 2:
            return None
        survivors, dropped = [], []
        for index, reading in enumerate(readings):
            if index == 0 and first_failure is not None:
                failure, changes = (CONSTRAINT_OF.get(first_failure, "readable"), first_failure), []
            else:
                failure, changes = self._reading_failure(parser, text, reading["parsed"])
            if failure is None:
                survivors.append(dict(reading, changes=changes, index=index))
            else:
                dropped.append((index, reading, failure))
        buffer = self.__dict__.setdefault("_trace_buffer", [])
        for index, reading, (constraint, failure) in dropped:
            buffer.append(("hypothesis_rejected", {"checks": [{"ok": False, "reason": failure}],
                                                   "constraint": constraint, "tier": reading["tier"],
                                                   "reading": index, "said": _sha(reading["said"])}))
        self._trace_readings = [[_sha(r["said"])[:16], r["tier"]] for r in readings]
        self._readings_dropped = [{"reading": i, "constraint": c, "reason": f, "tier": r["tier"]}
                                  for i, r, (c, f) in dropped]
        replies = parser.data["context_replies"]
        said = str(text).strip()
        if not survivors:
            if len(readings) < 2 and first_failure is None:
                return None
            self._remember_unread({"text": said, "at": len(self.observations)})
            failed = [{"reading": d["reading"], "constraint": d["constraint"]} for d in self._readings_dropped]
            return {"operator": "relational_graph", "status": "unresolved", "transitions": [],
                    "answer": replies["no_reading"].format(**{"말": said}),
                    "meaning": {"act": "hold", "reason": "no_reading", "said": said, "failed": failed},
                    "verification": self._verification(knowledge_path, [{
                        "ok": False, "reason": "no_reading", "readings": len(readings),
                        "dropped": self._readings_dropped}])}
        tier = min(r["tier"] for r in survivors)
        best = [r for r in survivors if r["tier"] == tier]
        if len({r["said"] for r in best}) == 1:
            text = _readings.tentative(text)
            parser.__dict__.setdefault("chosen_readings", {})[text.oid] = best[0]["parsed"]
            self._replay_cache = None        # a replay made with the first reading is not this one
            self._rereading = True
            try:
                result = self._turn(text, knowledge_path)
            finally:
                self._rereading = False
            if result is not None and isinstance(result.get("verification"), dict):
                result["verification"].setdefault("checks", []).append({
                    "ok": True, "reason": "reading_checked", "readings": len(readings), "tier": tier,
                    "dropped": self._readings_dropped})
            if result is None or result.get("status") != "observed":
                parser.chosen_readings.pop(text.oid, None)
                self._replay_cache = None
            return result
        self._remember_unread({"text": said, "at": len(self.observations)})
        return {"operator": "relational_graph", "status": "unresolved", "transitions": [],
                "answer": replies["ambiguous_reading"].format(**{"말": said}),
                "meaning": {"act": "ask", "reason": "ambiguous_reading", "said": said,
                            "readings": [{"changes": r["changes"]} for r in best]},
                "verification": self._verification(knowledge_path, [{
                    "ok": False, "reason": "ambiguous_reading", "readings": len(best), "tier": tier,
                    "dropped": self._readings_dropped}])}

    def _emit_turn(self, text, result, path, observed_before):
        """This turn's events (request L1-1, the minimum), kept in ``trace_pending`` until the recorder writes
        them after the turn's input (``flush_trace``): the path the turn took (``routing_selected``, with the
        readings it chose between when there were several), each state update it recorded with the rule and
        its bindings (``rule_applied``), each statement it did not read (``evidence_rejected``), each reading a
        constraint dropped (``hypothesis_rejected``), and a hold with its reason and gap class (``hold``,
        ``payload.gap``; also ``trace_gap``). References, state keys and digests only; a recording problem never
        changes the turn."""
        pending = PendingTrace()
        self.trace_pending, self.trace_gap = pending, None
        try:
            self._emit_turn_events(pending, text, result, path, observed_before)
        except Exception:        # noqa: BLE001 -- the ledger is a record of the turn, never its cause
            self.trace_pending = None

    def flush_trace(self, ledger, parent=None):
        """Write the last turn's pending events to ``ledger`` as one trace resting on ``parent`` (the turn's
        ``input_received``); returns their ids. The recorder calls it after it recorded the turn."""
        pending, self.trace_pending = getattr(self, "trace_pending", None), None
        return pending.write(ledger, parent) if pending is not None else []

    def _emit_turn_events(self, ledger, text, result, path, observed_before):
        from marco.trace import runtime as rt
        pack = next((source["path"] for source in getattr(self.model, "sources", ())
                     if source["path"].startswith("styles/")), None) or self.language
        stamp = rt.stamp(pack)
        trace_id = ledger.new_trace_id()
        meaning = (result or {}).get("meaning") if isinstance((result or {}).get("meaning"), dict) else {}
        status = (result or {}).get("status")
        act = meaning.get("act")
        if result is None:
            selected = "not_read"
        elif path == "follow_up":
            selected = "follow_up:%s" % (meaning.get("kind") or act)
        else:
            selected = {"record": "statement", "revise": "correction", "explain": "explain", "hold": "hold",
                        "ask": "ask", "refuse": "hold"}.get(act, "question" if status == "answered" else
                                                            ("statement" if status == "observed" else str(act)))
        readings = [[str(name), rank] for name, rank in (getattr(self, "_trace_readings", None) or [])]
        root = ledger.append(
            "routing_selected", trace_id, subsystem="reasoning", epistemic_status="inferred",
            runtime={**stamp, **rt.first_stamp(pack)},
            source={"type": "engine_site", "site": "ReasoningContext.turn", "conversation": self.conversation_id,
                    "sha256": _sha(text)},
            payload={"selected": selected, "candidates": readings or [[selected, None]], "status": status,
                     "act": act, "observations": len(self.observations), "effort": self.effort,
                     "nodes_read": self._nodes_read(result),
                     "candidates_dropped": list(getattr(self, "_trace_candidates", None) or []),
                     "rankings": list(getattr(self, "_trace_rankings", None) or [])})["event_id"]
        parents = []
        for kind, payload in list(getattr(self, "_trace_buffer", None) or []):
            status_of = "failed" if kind in ("rule_blocked", "hypothesis_rejected") else "success"
            parents.append(ledger.append(kind, trace_id, parent_ids=[root], status=status_of,
                                         subsystem="reasoning", epistemic_status="unknown" if status_of == "failed"
                                         else "observed", runtime=stamp,
                                         payload=dict(payload, **({"checks": payload.get("checks", [])}
                                                                  if kind == "hypothesis_rejected" else {})))["event_id"])
        # L1-1 B3 at this file's site: each state update this turn recorded, with its rule and bindings
        index = len(self.observations) - 1
        if result is not None and status == "observed" and len(self.observations) > observed_before:
            rules = {}
            try:
                parsed = self._read_source(self._parser(), self.observations[index], events=True,
                                           verbs=self._verbs_for(self._parser(), self.observations)) or {}
                for fact in parsed.get("facts", []):
                    triple = fact.get("triple") or []
                    if len(triple) == 3 and isinstance(triple[0], str):
                        rules.setdefault(triple[0], str(triple[1]))
            except Exception:    # noqa: BLE001
                rules = {}
            for row in result.get("transitions") or []:
                evidence = row.get("evidence") if isinstance(row.get("evidence"), dict) else {}
                if row.get("operation") not in ("state_update", "quantity_update") or evidence.get("turn") != index:
                    continue
                subject = str(row.get("subject"))
                rule = rules.get(subject) or next((r for s_, r in rules.items() if s_.split()[:1] == subject.split()[:1]),
                                                  None) or str(row.get("predicate"))
                ledger.append("rule_applied", trace_id, parent_ids=[root], subsystem="reasoning",
                              epistemic_status="inferred", runtime=stamp,
                              operation={"type": "rule", "id": rule, "operation": row.get("operation")},
                              payload={"operator": str(result.get("operator") or "relational_graph"),
                                       "bindings": {"subject": subject, "predicate": str(row.get("predicate")),
                                                    "before": row.get("before"), "after": row.get("after"),
                                                    "delta": row.get("delta"), "observation": index},
                                       "normalization": (evidence.get("normalization") or {}).get("rule")})
        if act == "explain" and meaning.get("rules"):
            # L1-1 B13: the rules an explanation names, as ids
            ledger.append("rule_applied", trace_id, parent_ids=[root], subsystem="reasoning",
                          epistemic_status="inferred", runtime=stamp,
                          operation={"type": "explanation", "rules": [str(r) for r in meaning["rules"]]},
                          payload={"operator": "explain", "bindings": {"kind": meaning.get("kind"),
                                                                      "changes": len(meaning.get("changes") or [])}})
        held = status == "unresolved" or act in ("hold", "ask", "refuse")
        if result is None and any(kind == "evidence_rejected" for kind, _p in getattr(self, "_trace_buffer", []) or []):
            held, reason = True, "unread_statement"
        else:
            reason = meaning.get("reason") or "unresolved"
        if held:
            detail = next((c.get("reason") for c in ((result or {}).get("verification") or {}).get("checks") or []
                           if isinstance(c, dict) and not c.get("ok") and c.get("reason")), None)
            gap, declared = gap_class(detail if reason == "invalid" and detail in GAP_OF else reason)
            self.trace_gap = gap
            ledger.append("hold", trace_id, parent_ids=parents or [root],
                          status="refused" if act == "refuse" else "hold", subsystem="reasoning",
                          epistemic_status="unknown", runtime=stamp,
                          subject=meaning.get("subject") if isinstance(meaning.get("subject"), str) else None,
                          payload={"reason": str(reason), "gap": gap, "gap_declared": declared, "act": act,
                                   "detail": detail})

    def _declare_holders(self, result):
        """The meaning block's holders (request W3-1): each place this conversation's statements read
        as a holder, when the meaning names it, as ``{key: {"kind": "place"}}``."""
        meaning = result.get("meaning") if isinstance(result.get("meaning"), dict) else None
        if meaning is None or not self._permitted(None) or not self.observations:
            return
        try:
            facts, _d, _p, _r = self._cached_replay(self._parser(), self.observations, self.fills)
        except ValueError:
            return
        places = {place for fact in facts for place in fact.get("places") or [] if isinstance(place, str)}
        said = json.dumps(meaning, ensure_ascii=False)
        holders = {place: {"kind": "place"} for place in sorted(places) if place and place in said}
        # A titled or relational holder (request W3-1 item 1, W5-3 item 6): the key the facts use, said as the
        # user said it where a declared holder form rewrote the words to the key (the typed words that stand
        # where the reading has the key; the latest statement that named it so).
        for fact in facts:
            evidence = fact.get("evidence") or {}
            canonical = (evidence.get("normalization") or {}).get("canonical")
            typed = evidence.get("text")
            subject = fact.get("triple", [None])[0]
            if not isinstance(typed, str) or not isinstance(subject, str):
                continue
            key = " ".join(subject.split()[:-1])        # the holder part of "<holder> <thing>"
            if self._effort_allows(2):
                # the holder node's name: a thing of two words (과자 봉지) is no part of the holder (step 3)
                person = self._person_of(subject)
                key = person if person != subject else key
            if not key:
                continue
            by_form = (evidence.get("normalization") or {}).get("rule") == "declared-holder-forms-v1"
            at = canonical.find(key) if by_form and isinstance(canonical, str) else -1
            before, after = (canonical[:at], canonical[at + len(key):]) if at >= 0 else ("", "")
            if at < 0 or not (typed.startswith(before) and typed.endswith(after)) \
                    or len(typed) < len(before) + len(after):
                # another variant rewrote a word around the holder (keeps -> has, me -> I): the words the
                # pack declares before a holder, as typed before the key (G5 batch 4)
                words = self._said_before_key(typed, key)
            else:
                # a phrase variant dropped before the holder ("After that, my aunt") leaves its words in the
                # difference; the holder's own words are those after the last comma
                words = typed[len(before):len(typed) - len(after)].split(",")[-1].strip()
            if words and words != key and key in words and key in said and key not in places:
                holders[key] = {"kind": "named", "said": words}
        if holders:
            result["meaning"] = {**meaning, "holders": {**(meaning.get("holders") or {}), **holders}}

    def _said_before_key(self, typed, key):
        """The holder as typed: ``key`` with the declared words before it (가진쪽꼴): a title before a name
        (Mr. Fischer), a possessive (my wife), a possessive and one relation word before a name (my tenant
        Eliana); None when the words before the key are none of these."""
        parser = self._parser()
        spec = getattr(parser, "holder_forms", None) or {}
        lead = {w.lower() for w in list(spec.get("possessives") or []) + list(spec.get("self_possessives") or [])}
        titles = set(spec.get("prefix_titles") or [])
        found, behind = None, ""
        suffixes = sorted(spec.get("name_titles") or [], key=len, reverse=True)
        if suffixes and len(key.split()) > 1:
            # a title after a key of several words (황 팀장님): said with it, so the realizer keeps the key whole
            # (W5-3 item 6); a one-word name keeps the realizer's own form (서준 씨 is said 서준)
            found = re.search(r"(?<![\w'])%s(\s?(?:%s))" % (re.escape(key), "|".join(map(re.escape, suffixes))), typed)
            behind = found.group(1) if found else ""
        if found is None:
            found = re.search(r"(?<![\w'])%s(?![\w'])" % re.escape(key), typed)
        if found is None:
            return None
        ahead = typed[:found.start()].split()
        taken = []
        if ahead and ahead[-1] in titles:
            taken = ahead[-1:]
        elif ahead and ahead[-1].lower() in lead:
            taken = ahead[-1:]
        elif (len(ahead) >= 2 and ahead[-2].lower() in lead and ahead[-1].isalpha()
              and ahead[-1].lower() not in parser._frame_words()
              and (spec.get("relation_nouns") is None or ahead[-1] in spec["relation_nouns"])):
            # (where the pack declares its relation nouns, the word between is one of them, bare: 제 팀원이 서준
            # names two holders)
            taken = ahead[-2:]
        if not taken and not behind:
            return None
        if taken and taken[0].lower() in lead:
            taken[0] = taken[0].lower()
        return " ".join(taken + [key]) + behind

    def _follow_up(self, text, knowledge_path, language):
        """A question about this conversation's own last reply, as the language declares them
        (``marco.language.realizer.follow_up``): the bare why, or what a reading changed."""
        from marco.language.realizer import follow_up
        if not self._permitted(knowledge_path):
            return None
        kind = follow_up(text, self.model if hasattr(self.model, "parser") else language)
        if kind == "why_last":
            return self._explain_last(self._parser(), knowledge_path)
        if kind != "repairs":
            return None
        parser = self._parser()
        notes = list(getattr(self, "_last_repairs", []))
        fields = [{key: report.get(key) for key in ("source", "reading", "rule", "operations", "cost", "bound")}
                  for report in notes]
        return {"operator": "relational_graph", "status": "answered", "transitions": [],
                "meaning": {"act": "explain", "kind": "repairs" if fields else "no_repairs", "repairs_full": fields},
                "answer": " ".join(parser.render_repair(report, parser.data.get("context_replies", {}))
                                   for report in notes),
                "verification": self._verification(knowledge_path, [{
                    "ok": True, "reason": "repair_notes", "repairs": len(notes)}])}

    @staticmethod
    def _compared(asked, transitions):
        """A total or a comparison as meaning: the holders its proof read, and the sum, the one
        with more or fewer, or whether they hold the same number (request G3-4). Two equal
        counts asked which has more or fewer are a tie. A count another listed count rests on
        is not a holder."""
        spec = asked if isinstance(asked, dict) else {}
        kind = next((key for key in ("total", "more", "fewer", "same") if isinstance(spec.get(key), dict)), None)
        if kind is None:
            return {}
        rows = [row for row in transitions or [] if isinstance(row.get("fact"), list) and len(row["fact"]) == 3
                and row["fact"][1] == "count" and str(row["fact"][2]).lstrip("-").isdigit()]
        parents = {tuple(parent) for row in rows for parent in row.get("parents") or []
                   if isinstance(parent, (list, tuple))}
        held = {row["fact"][0]: int(row["fact"][2]) for row in rows if tuple(row["fact"]) not in parents}
        named = spec["total"].get("members") if kind == "total" else [spec[kind].get("a"), spec[kind].get("b")]
        named = [name for name in named or [] if isinstance(name, str)] if isinstance(named, list) else []
        subjects = sorted(held, key=lambda subject: (next(
            (i for i, name in enumerate(named) if str(subject).startswith(name)), len(named)), str(subject)))
        if kind == "total":
            return {"kind": "total", "subjects": subjects, "value": sum(held.values())} if len(held) >= 2 else {}
        if len(held) != 2:
            return {}
        values = [held[subject] for subject in subjects]
        if values[0] == values[1]:
            return {"kind": "same" if kind == "same" else "tie", "subjects": subjects, "value": values[0]}
        if kind == "same":
            return {"kind": "different", "subjects": subjects, "values": values}
        pick = max if kind == "more" else min
        winner = pick(held, key=held.get)
        return {"kind": kind, "winner": winner, "than": next(s for s in subjects if s != winner)}

    def _speaker(self, result, language):
        """The model the reply is said in (request W1-3): this conversation's model, or the
        companion that answered. A caller without a model keeps the language path."""
        def path(model):
            return next((source["path"] for source in getattr(model, "sources", ())
                         if source["path"].startswith("styles/")), None)
        meaning = result.get("meaning") if isinstance(result.get("meaning"), dict) else None
        answering = (meaning or {}).get("answer_language")
        model = next((m for m in self.companions if answering and path(m) == answering), self.model)
        if model is None or not hasattr(model, "parser") or path(model) is None:
            return language
        if meaning is not None and model is not self.model:
            result["meaning"] = {**meaning, "conversation_language": language}
        return model

    def _answer_in_time(self, parser, text, knowledge_path):
        """``How many figs did Ada have before Ada gave Bo 2?``: a question about the
        state just before (or just after) one earlier event.

        The pack declares the connectives of order in time (문장분리.time_order).
        One side of the connective must read as a question and nothing else; the
        other names the event: every holder it names took part in it, and an
        amount it names is the event's. Exactly one earlier event must fit; the
        question is then answered from the statements before it (before) or up
        to it (after). Anything else is not read here.
        """
        spec = (parser.clause_grammar or {}).get("time_order") or {}
        if not spec or not self.observations:
            return None
        said = text.strip()
        ignore = bool(parser.data.get("ignore_case"))
        fold = (lambda value: value.lower()) if ignore else (lambda value: value)
        marks = "".join(parser.clause_grammar.get("question_marks", [])) + ".!"
        for order in ("before", "after"):
            for marker in sorted(spec.get(order, []), key=len, reverse=True):
                pattern = re.compile((r"(?<!\w)" if marker[:1].isalnum() and marker.isascii() else "")
                                     + re.escape(marker) + r"(?!\w)", re.IGNORECASE if ignore else 0)
                found = pattern.search(said)
                if not found:
                    continue
                left, right = said[:found.start()].strip(" ,"), said[found.end():].strip()
                if not left.strip(marks + " "):
                    event, _comma, question = right.partition(",")
                    splits = [(event, question)]
                else:
                    splits = [(right, left), (left, right)]
                for event, question in splits:
                    event, question = event.strip(" ," + marks), question.strip(" ,")
                    if not event or not question:
                        continue
                    asked = self._read_source(parser, question, events=True)
                    if not asked or not asked.get("query") or asked.get("facts") or asked.get("사건"):
                        continue
                    return self._timed_answer(parser, order, event, asked["query"], said, knowledge_path)
        return None

    def _timed_answer(self, parser, order, event, query, said, knowledge_path):
        replies = parser.data["context_replies"]
        facts, _defined, _pending, _read = self._cached_replay(parser, self.observations, self.fills)
        # An event is a statement that changed a value already known: an amount
        # added or taken, a thing moved from where it was. A first statement of
        # a value is not an event to be before or after.
        _state, changes = current_facts(facts, parser.data.get("mutable_predicates", []),
                                        parser.data.get("numeric_updates", {}))
        changed_turns = {(change.get("evidence") or {}).get("turn") for change in changes
                         if change.get("operation") == "quantity_update"
                         or (change.get("operation") == "state_update" and change.get("before") is not None)}
        updates = set(parser.data.get("numeric_updates", {})) | set(parser.data.get("mutable_predicates", []))
        holders = {str(item["triple"][0]).split()[0] for item in facts if isinstance(item["triple"][0], str)}
        typed = [word.strip(",.!?") for word in event.split()]
        # A holder is named by a word that is its name, with a particle after it
        # where the language writes particles on the word.
        named = {holder for holder in holders
                 if any(word.lower() == holder.lower() if holder.isascii() else word.startswith(holder)
                        for word in typed)}
        amounts = {str(value) for value in (self._amount_of(parser, word) for word in typed) if value is not None}
        turns = {}
        for item in facts:
            triple = item["triple"]
            if triple[1] in updates and isinstance(triple[0], str):
                turns.setdefault(item["evidence"].get("turn"), []).append(item)
        def says(turn, holder):
            words = [word.strip(",.!?") for word in self.observations[turn].split()]
            return any(word.lower() == holder.lower() if holder.isascii() else word.startswith(holder)
                       for word in words)
        fitting = sorted(turn for turn, rows in turns.items() if turn in changed_turns
                         and isinstance(turn, int) and 0 <= turn < len(self.observations)
                         and named and all(says(turn, holder) for holder in named)
                         and (not amounts or amounts & {str(row["triple"][2]) for row in rows}))
        if len(fitting) > 1:
            # The event's verb, said in any form of its frame, tells events apart.
            def verbs(turn):
                forms = set()
                for row in turns[turn]:
                    stem = ((row["evidence"].get("normalization") or {}).get("stem") or row.get("verb")
                            or self._declared_stem(parser, row["evidence"]["text"]))
                    if stem:
                        forms |= self._frame_reference_forms(parser, stem, every_form=True)
                return forms
            by_verb = [turn for turn in fitting if set(typed) & verbs(turn)]
            fitting = by_verb or fitting
        if len(fitting) != 1:
            key = "reference_which_event" if fitting else "reference_no_event"
            return {"operator": "relational_graph", "status": "unresolved", "transitions": [],
                    "meaning": {"act": "hold", "reason": key, "said": said,
                                **({"items": [self.observations[i].strip() for i in fitting]} if fitting else {})},
                    "answer": replies[key].format(**{"말": said, "목록": ", ".join(
                        '"%s"' % self.observations[i].strip() for i in fitting)}),
                    "verification": self._verification(knowledge_path, [{"ok": False, "reason": "time_" + key}])}
        at = fitting[0]
        window = [item for item in facts if (item["evidence"].get("turn", 0) < at if order == "before"
                                             else item["evidence"].get("turn", 0) <= at)]
        outcome = parser.answer({"facts": window, "query": query})
        if outcome is None:
            return {"operator": "relational_graph", "status": "unresolved", "transitions": [],
                    "meaning": {"act": "hold", "reason": "unresolved"}, "answer": replies["unresolved"],
                    "verification": self._verification(knowledge_path, [{"ok": False, "reason": "time_unresolved"}])}
        first = query[0] if query and isinstance(query[0], dict) else {}
        return {"operator": "relational_graph", "status": "answered", **outcome,
                "meaning": {"act": "inform", "query": deepcopy(first.get("triple")), "render": deepcopy(first.get("render")),
                            # The event as recorded too (request G3-4): the reply says it from its changes.
                            "time": {"order": order, "event": self.observations[at].strip(),
                                     "changes": deepcopy([change for change in changes
                                                          if (change.get("evidence") or {}).get("turn") == at])}},
                "verification": self._verification(knowledge_path, [{
                    "ok": True, "reason": "state_%s_event" % order, "event_turn": at}])}

    def _turn_reply(self, text, knowledge_path=None):
        """One turn. A reading that rests on a repair says so in the same reply.

        The repair is reported, then the turn continues under it — nothing
        waits for confirmation. A clause that a repair could only place above
        the pack's bound, or in two equally near ways, is held and the hold
        names what could not be placed.
        """
        self._turn_repairs = []
        if self._permitted(knowledge_path) and not self._live():
            # A reply that is only a known person's name, said while a question
            # waits for it, is read before anything else can mistake it for an
            # unknown event ("I mean Haru", "가람이 말이야").
            frame = self.last_frame
            named = self._name_reply(self._parser(), text, knowledge_path)
            if named is None:
                # after an ask of which holder, one candidate named with a word or two besides (effort 2)
                named = self._named_reply(self._parser(), text, knowledge_path)
            if named is not None and named.get("status") != "answered" and self._effort_allows(2):
                # the name put in the wrong words of the last question (a title after a surname: 전 팀장님) is
                # one candidate; the last question's frame gives the others (effort 2)
                held_frame, self.last_frame = self.last_frame, frame
                framed = self._partial_frame(self._parser(), text, knowledge_path)
                if framed is not None and framed.get("status") == "answered":
                    return framed
                self.last_frame = held_frame
            if named is not None:
                return named
        if self._permitted(knowledge_path) and not self._live():
            timed = self._answer_in_time(self._parser(), text, knowledge_path)
            if timed is not None:
                return timed
        result = self._turn(text, knowledge_path)
        if not self._permitted(knowledge_path):
            return result
        parser = self._parser()
        replies = parser.data.get("context_replies", {})
        if result is None and self.companions:
            result = self._companion_turn(parser, text, knowledge_path)
            if result is not None:
                return result
        if result is None:
            # 한도 밖 보류가 이 턴을 맡는 것은 **놓지 못한 부분이 좁을 때**뿐이다.
            # 여러 곳을 고쳐야 겨우 닿는 규칙이면 이 말은 이 해석기의 몫이 아닐
            # 수 있으므로, 다른 부품이 읽도록 넘긴다. 그 폭은 팩이 정한다.
            widest = parser.repair.get("hold_max_edits", 1)
            # 같은 비용의 읽기가 여럿이면 가장 가까운 규칙이 하나가 아니다. 그 보류는
            # 턴을 맡지 않고 진단에만 남는다.
            held = [report for report in parser.repair_reports(text)
                    if (report["status"] == "over_bound" and len(report["operations"]) <= widest)
                    or (report["status"] == "protected" and "repair_protected" in replies
                        and report["cost"] <= report["bound"])]
            if not held or not all(key in replies for key in ("repair_over_bound", "repair_ambiguous")):
                return None
            # A repair that would change a numeral, counter, scope word or
            # negation is held and says which word (G2.5).
            guarded = [row for report in held if report["status"] == "protected" for row in report["changed"]]
            marks = parser.clause_grammar.get("question_marks", [])
            if guarded and not any(text.rstrip().endswith(mark) for mark in marks):
                # A statement held this way still said something happened: the
                # values it names stay open until a later statement pins them.
                self._remember_unread({"text": text.strip(), "at": len(self.observations)})
            return {"operator": "relational_graph", "status": "unresolved", "transitions": [],
                    "answer": " ".join(parser.render_repair(report, replies) for report in held),
                    "meaning": ({"act": "hold", "reason": "repair_protected", "said": text.strip(),
                                 "changed": guarded, "words": [row.get("word") for row in guarded]} if guarded else
                                {"act": "hold", "reason": "repair_over_bound"}),
                    "repair": held,
                    "verification": self._verification(knowledge_path, [{
                        "ok": False, "reason": "repair_" + held[0]["status"]}])}
        repairs = [report for report in self._turn_repairs if report.get("status") == "repaired"]
        if repairs and "repaired" in replies:
            notes = " ".join(parser.render_repair(report, replies) for report in repairs)
            result = {**result, "repair": repairs,
                      "answer": notes + " " + (result.get("answer") or "")}
        return result

    def _turn(self, text, knowledge_path=None):
        if not self._permitted(knowledge_path):
            return None
        parser = self._parser()
        correction = parser.data.get("context_correction", {})
        for prefix in correction.get("prefixes", []):
            if text.strip().startswith(prefix):
                body = text.strip()[len(prefix):].strip()
                parts = body.split(correction["separator"])
                try:
                    if len(parts) != 2 or not all(part.strip() for part in parts):
                        raise ValueError("invalid_correction_syntax")
                    normalize = lambda value: re.sub(r"[.!?]+$", "", value.strip()).strip()
                    matches = [i for i, old in enumerate(self.observations)
                               if normalize(old) == normalize(parts[0])]
                    if len(matches) != 1:
                        raise ValueError("ambiguous_or_missing_correction_target")
                    return self.correct(matches[0], parts[1].strip(), knowledge_path)
                except ReadingUnavailable:
                    # not an invalid correction: an original reading is missing; the adapter decides
                    raise
                except ValueError as exc:
                    return {"operator": "relational_graph", "status": "unresolved",
                            "answer": parser.data["context_replies"]["correction_invalid"], "transitions": [],
                            "meaning": {"act": "hold", "reason": "correction_invalid"},
                            "verification": self._verification(knowledge_path, [{"ok": False, "reason": str(exc)}])}
        asked, self._vague_asked = getattr(self, "_vague_asked", None), None
        if asked is not None and asked[1] == len(self.observations):
            self.bind_hints = [hint for hint in getattr(self, "bind_hints", []) if hint[0] != asked[1]] + [asked[::-1]]
        verbs = self._verbs_for(parser, self.observations + [text])
        current = self._read_source(parser, text, events=True, verbs=verbs)
        self._unread_continuation_read(text, parser, current)
        self._capture_current_query_read(text, parser, current)
        structural = self._admit_structural_observation(text, current, parser, verbs, knowledge_path)
        if structural is not None:
            return structural
        gap = self._graph_dialogue_guard(text, knowledge_path, current, parser)
        if gap is not None:
            return gap
        if current is not None and current.get("facts") and all(f.get("unnamed") for f in current["facts"]) \
                and not any(current.get(key) for key in ("query", "사건", "정의", "원인", "조건")):
            # An amount said with no holder at all (18 of them, 3명이야) is the count not known yet that
            # the conversation left open; with none open it is no statement (a short answer, perhaps).
            facts, _d, _p, _r = self._cached_replay(parser, self.observations, self.fills)
            counted = {f["triple"][0] for f in facts if f["triple"][1] == "count"}
            if not any(f["triple"][1] == "count_unknown" and f["triple"][0] not in counted for f in facts):
                current = None
        self._turn_repairs = list((current or {}).get("수선", []))
        if (self._effort_allows(3) and self.observations and not getattr(self, "_rereading", False)
                and not any(str(text).rstrip().endswith(mark)
                            for mark in parser.clause_grammar.get("question_marks", []))
                and (current is None
                     or (not current.get("facts") and current.get("사건") and not current.get("query")
                         and all(self._lookup(parser, event, set(), verbs) is None for event in current["사건"]))
                     or any(r.get("status") == "repaired" for r in self._turn_repairs))):
            # G7-S experiment 7: a use-up whose purpose or product phrase fills no slot (effort 3)
            adjunct = self._read_without_adjunct(parser, text, current, verbs, knowledge_path)
            if adjunct is not None:
                return adjunct
        if current is None or not any(current.get(key) for key in (
                "query", "사건정정", "정의", "원인", "이유물음", "조건")):
            # "Actually it was one, not two" / "두 개가 아니라 한 개야":
            # a declared contrast of two values corrects the one earlier
            # statement that carried the old value. It is a correction even
            # when a statement reader (or a repair) also reads part of it:
            # read as a new statement, the event would happen twice.
            contrast = self._contrast(parser, text) or self._restatement(parser, text)
            if contrast is not None:
                self._turn_repairs = []
                return self._correct_by_reference(parser, contrast, text, knowledge_path)
            if self._effort_allows(2) and (current is None or not current.get("facts")):
                # a correction the frame of the last events reads (checked by replay) comes before the declared
                # receiver contrast, which reads 노라가 아니라 민석이 … as a new receiver
                framed = self._correction_frame(parser, text, knowledge_path)
                if framed is not None and framed.get("status") == "observed":
                    self._turn_repairs = []
                    return framed
            recipient = self._recipient_contrast(parser, text)
            if recipient is not None:
                self._turn_repairs = []
                return self._correct_recipient(parser, recipient, text, knowledge_path)
            swap = any(" %s " % word in " %s " % " ".join(re.split(r"[\s,.!?]+", text.lower())).strip()
                       for word in ((parser.language_pack.get("contrast_correction") or {}).get("frame") or {})
                       .get("swap_words", []))
            if current is None or not (current.get("facts") or current.get("사건")) or swap:
                # a correction no declared form reads: a partial frame over the last events (effort 2)
                framed = self._correction_frame(parser, text, knowledge_path)
                if framed is not None:
                    self._turn_repairs = []
                    return framed
        빠진전제 = None
        if current is not None and current.get("사건정정"):
            return self._correct_by_reference(parser, current["사건정정"][0], text, knowledge_path)
        replies = parser.data["context_replies"]
        문맥채움 = []
        if current is not None and (current.get("사건") or current.get("가정사건")):
            # Resolve an unambiguous pointer against evidence that predates
            # this utterance.  The chosen value is saved as an event fill so
            # replay/snapshot never have to reinterpret its original text.
            before_facts, _before_defined, _before_pending, _before_read = self._cached_replay(
                parser, self.observations, self.fills)
            raw_current = deepcopy(current)
            current, referent_problem = self._resolve_event_referents(parser, current, before_facts)
            if referent_problem is not None:
                style = "which_referent" if referent_problem["후보"] else "no_referent"
                return {"operator": "relational_graph", "status": "unresolved", "transitions": [],
                        "meaning": {"act": "ask", "reason": style, "word": referent_problem["말"],
                                    "candidates": list(referent_problem["후보"])},
                        "answer": replies[style].format(**{
                            "말": referent_problem["말"],
                            "목록": ", ".join("'%s'" % name for name in referent_problem["후보"])}),
                        "verification": self._verification(knowledge_path, [{
                            "ok": False, "reason": "event_referent_ambiguous"}])}
            counters = {}
            for event_ordinal, (raw_event, resolved_event) in enumerate(zip(
                    raw_current.get("사건", []), current.get("사건", []))):
                stem = self._lookup(parser, raw_event, set(), verbs)
                marker = (stem, json.dumps(sorted(raw_event["자리"].items()), ensure_ascii=False))
                ordinal = counters.get(marker, 0)
                counters[marker] = ordinal + 1
                slot = "%d:%d" % (len(self.observations), event_ordinal)
                event_id = (self._event_id(len(self.observations), stem, raw_event["자리"], ordinal)
                            if self.event_ids is None else
                            self.event_ids.setdefault(slot, "event:%s" % slot))
                for slot, original in raw_event["자리"].items():
                    resolved = resolved_event["자리"].get(slot)
                    if resolved != original:
                        문맥채움.append({"사건": event_id, "역할": slot, "값": resolved,
                                         "문맥": True, "근거": raw_event["evidence"]["text"]})
        사는것 = self._live()
        상태보완 = self._state_completion(current, 사는것)

        # 원인 관찰과 이유 물음은 수량 상태로 환원하지 않는다. 과거 원인 기록과
        # 이번 물음의 결과 사건 표지를 그대로 모아 파서에 맡긴다. 따라서 원인
        # 하나를 같은 주어의 모든 질문에 붙이지 않으며, 물음 자체도 관찰로
        # 저장하지 않는다.
        if current is not None and current.get("이유물음"):
            origins = []
            sources = list(self.observations) + ([text] if current.get("원인") else [])
            for turn, source in enumerate(sources):
                prior = self._read_source(parser, source, events=True, verbs=verbs)
                for record in (prior or {}).get("원인", []):
                    copied = deepcopy(record)
                    copied["evidence"] = {**copied["evidence"], "turn": turn, "source": source}
                    origins.append(copied)
            causal = parser.answer({"facts": [], "query": None,
                                    "원인": origins, "이유물음": current["이유물음"]})
            if causal is not None:
                return {"operator": "relational_graph", "status": "answered",
                        "answer": causal["answer"], "transitions": causal["transitions"],
                        "verification": self._verification(knowledge_path, [{
                            "ok": True, "reason": "cause_effect_bound",
                            "cause_turns": [row["evidence"]["turn"] for row in origins]}])}
            return {"operator": "relational_graph", "status": "unresolved",
                    "answer": replies["unresolved"], "transitions": [],
                    "meaning": {"act": "hold", "reason": "unresolved"},
                    "verification": self._verification(knowledge_path, [{
                        "ok": False, "reason": "cause_effect_missing_or_ambiguous"}])}

        def 말하기(key, _meaning=None, **값):
            return {"operator": "relational_graph", "transitions": [], "status": "unresolved",
                    "answer": replies[key].format(**값),
                    "meaning": {"act": "ask", "reason": key, **(_meaning or {})},
                    "verification": self._verification(knowledge_path, [])}

        def 고를말(표):
            # The choices a reply may give, each by its first declared word.
            return [words[0] for words in (표 or {}).values() if words]

        def 자리들(빈자리):
            return [self._slot_name(parser, key) for key in sorted(set(빈자리.values()))]

        # 되물은 것에 대한 **답**. 아무 틀에도 안 맞는 말이라 여기서 본다.
        # 답은 상태를 바꾸는 사건이 아니다 — 못 알아들어도 못 읽은 사건으로
        # 남기지 않는다. 남기면 틀리게 답한 말이 영영 값을 막는다.
        짧은답, 관계보완, 새덮기, 정해짐 = None, None, [], None
        굳은것 = [ask for ask in 사는것 if ask["종류"] in ("충돌", "정정대상")]
        if current is None and 굳은것:
            ask = 굳은것[0]
            if ask["종류"] == "정정대상":
                고름 = self._choice(text, parser.target_words)
                if 고름 is None:
                    return 말하기("correction_target", {"choices": 고를말(parser.target_words)})
                self._settle(ask)
                새덮기 = [{"범위": "설명정정" if 고름 == "설명" else "이번만",
                        "동사": ask["동사"], "사건": ask["사건"],
                        "역할": ask["역할"], "값": ask["값"], "근거": text.strip()}]
            else:
                범위 = self._choice(text, parser.scope_words)
                if 범위 is None:
                    return 말하기("conflict_scope_unclear", {"said": text.strip(),
                                                             "choices": 고를말(parser.scope_words)},
                                 말=text.strip())
                if 범위 == "정정":
                    # 무엇을 정정하는지는 우리가 고를 일이 아니다. 갈라 묻는다.
                    self._settle(ask)
                    self.asked.append({**ask, "id": ask["id"] + "?대상",
                                       "종류": "정정대상", "해결": False})
                    return 말하기("correction_target", {"choices": 고를말(parser.target_words)})
                self._settle(ask)
                새덮기 = [{"범위": 범위, "동사": ask["동사"], "사건": ask["사건"],
                        "부터": ask["차례"], "역할": ask["역할"], "값": ask["값"],
                        "근거": text.strip()}]
            current = {"facts": [], "query": None, "정의": [], "사건": []}
            정해짐 = 새덮기[0]["범위"]
        if current is None and 사는것 and not 굳은것:
            관계보완 = self._relation_completion(parser, text, 사는것)
            if 관계보완 is not None:
                current = {"facts": [], "query": None, "정의": [], "사건": []}
        if current is None and 사는것 and not 굳은것:
            _f, _d, 지금, _읽힘 = self._cached_replay(parser, self.observations, self.fills)
            # A clarification is bound against verified semantic facts and
            # the pending event's recorded roles.  Do not reparse the whole
            # conversation merely to reconstruct a candidate-name list.
            # Relationship indexes keep actors/participants in object
            # position.  A role answer may legitimately name either one, so
            # build candidates from every binary term rather than only a
            # state subject.
            이름 = {part for item in _f for value in item["triple"] for part in str(value).split()}
            for item in 지금:
                이름.update(str(value) for value in (item.get("자리") or {}).values()
                            if isinstance(value, str))
            갈래, ask, 값 = self._answer_to_ask(parser, text, 사는것, 이름)
            if 갈래 == "여럿":
                return 말하기("which_event", {"items": [next(iter(a["자리"].values()), a["동사"])
                                                         for a in 사는것]}, 목록=", ".join(
                    '"%s"' % next(iter(a["자리"].values()), a["동사"]) for a in 사는것))
            if 갈래 == "역할다름":
                return 말하기("role_mismatch", {"said": text.strip(), "value": 값[0],
                                                "slots": 자리들(ask["빈자리"])}, 말=text.strip(), 값=값[0],
                             물음=self._slot_question(parser, ask["빈자리"]))
            if 갈래 != "채움":
                return 말하기("answer_unclear", {"said": text.strip()}, 말=text.strip(),
                             물음=self._slot_question(parser, 사는것[0]["빈자리"]))
            if (not ask.get("가정사건")
                    and all(item["id"] != ask["사건"] for item in 지금)):
                self._settle(ask)      # 이미 풀린 물음이다. 답을 억지로 안 붙인다
                return 말하기("answer_unclear", {"said": text.strip()}, 말=text.strip(),
                             물음=self._slot_question(parser, ask["빈자리"]))
            짧은답 = [(ask, {값[1]: 값[0]})]
        if 짧은답 is not None:
            current = {"facts": [], "query": None, "정의": [], "사건": []}
        if current is None and not getattr(self, "_rereading", False):
            # G5.4 B: a statement the reader left unread only because a clause read two ways at one rank
            checked = self._check_readings(parser, text, verbs, knowledge_path, first_failure=None)
            if checked is not None:
                return checked
        if current is None and not getattr(self, "_rereading", False):
            # a question the reader left unread is grounded against the conversation before it is kept as
            # unread (G7-Q partial readings, effort 2): its open slots from the state, a clear winner only
            grounded = self._ground_question(parser, text, knowledge_path)
            if grounded is None and not self._in_name_reply:
                # an unread question that points at or describes a holder and names no holder and no thing
                grounded = self._which_person(parser, text, knowledge_path)
            if grounded is not None and "query" not in grounded:
                return grounded
            current = grounded
        if current is None:
            # 못 읽은 말을 구간마다 적어 둔다. 이 대화의 어느 값을 흔들었는지
            # 모르므로, 그 말이 가리킨 것에 대해서는 지금 값을 확정하지 않는다.
            # 물음은 사건이 아니다 — 묻는 말은 아무 상태도 안 바꾼다. 다만 그
            # 판단은 **메시지 전체가 아니라 구간마다** 해야 한다.
            attest = ("_thinking_exhaustion" in self.__dict__ and self.__dict__["_thinking_exhaustion"] is None
                      and not getattr(self, "_rereading", False) and not getattr(self, "_in_name_reply", False)
                      and type(getattr(self.model, "language_projection", None)) is dict
                      and type(self.__dict__.get("_current_query_read")) is dict
                      and self.__dict__["_current_query_read"].get("source") is text
                      and self._permitted(knowledge_path) and not self._live())
            kept = 0
            for piece, asking in self._segments(text, parser):
                notes = []
                if asking:
                    attest = False
                    continue
                read = parser.parse(piece, partial=True, events=True, verbs=verbs, repair=True, _diagnostics=notes)
                # nothing of this turn was applied. A piece read as a question states nothing; any other piece
                # states something the turn did not apply, whether it reads on its own (Nora gave Ivo 2 quills.,
                # said with a sentence nobody reads), only as the shape of an event (이보는 상대방한테 받았다가
                # 돌려줬어) or not at all: it is kept, and what it names is not said as known
                if read is not None and read.get("query") and not read.get("facts"):
                    attest = False
                    continue
                # 묻는 말은 못 읽은 사건이 아니다. 아무 상태도 안 바꾼다.
                if any(note.get("reason") == "question_is_not_an_observation"
                       for note in notes):
                    attest = False
                    continue
                # A request asks for an action; it reports no event.
                if self._is_request(parser, piece):
                    attest = False
                    continue
                # An unread piece that says an earlier statement was wrong (a declared contrast,
                # "..., not ...") may retract any statement: every value is held until a later
                # statement pins it again (G3.0 b), not only the ones it names.
                markers = (parser.language_pack.get("contrast_correction") or {}).get("markers", [])
                fold = (lambda v: v.lower()) if parser.data.get("ignore_case") else (lambda v: v)
                general = any(fold(marker) in fold(piece) for marker in markers)
                self._remember_unread({"text": piece, "at": len(self.observations),
                                       **({"범용": True} if general else {})})
                kept += 1
            if attest and kept and not self._is_request(parser, text):
                self._thinking_exhaustion = {"source": text, "parser": parser}
            return None
        # 같은 말이 뒤늦게 읽히면 매듭이 풀린 것이다.
        heard = {piece for piece, _asking in self._segments(text, parser)}
        self._forget_heard(heard)
        marks = parser.clause_grammar.get("question_marks", [])
        if (current.get("query") and not current.get("facts")
                and not any(text.rstrip().endswith(mark) for mark in marks) and self._counts_something(text, parser)
                and self._scoped_admission(text, current, parser) != "negative_query"
                and not self._selected_positive_query_input(parser, text, current)):
            # Read only as a question though it asks nothing and states an amount: it may be a statement
            # this reader did not read, so what it names is not fixed until a later statement pins it.
            self._remember_unread({"text": text.strip(), "at": len(self.observations)})
        result = {"operator": "relational_graph", "transitions": [],
                  "verification": self._verification(knowledge_path, [])}
        if (current["facts"] or current.get("정의") or current.get("사건") or current.get("원인")
                or current.get("조건")) and len(self.observations) >= self.max_turns:
            # 한도를 넘긴 사건은 실행 기록에는 넣지 못하지만, 없던 일로 만들면
            # 다음 물음에서 한도 직전의 값을 사실처럼 확정하게 된다. 어느 대상이
            # 흔들렸는지 알 수 없는 보류 사건으로 남겨 그 대상의 답을 막는다.
            said = text.strip()
            self._remember_unread({"text": said, "at": len(self.observations), "까닭": "용량"})
            return {**result, "status": "unresolved", "answer": replies["capacity"],
                    "meaning": {"act": "hold", "reason": "capacity", "said": said}}
        # 조건만 적힌 말도 남길 것이 있는 말이다. 빼놓으면 조건이 기록에서
        # 사라지고, 뒤따르는 일이 조건 없이 일어난 것처럼 셈된다.
        keeps = bool(current["facts"] or current.get("정의") or current.get("사건") or current.get("원인")
                     or current.get("조건"))
        # 되물어 둔 자리를 채워 준 말이면 **새 사건이 아니라 그 사건의 보완**이다.
        # 원래 자리에 놓아야 그때의 뜻으로 풀린다.
        completion = 짧은답 or self._completion(parser, current, verbs, 사는것)
        pending = (list(self.observations) if (completion is not None or 상태보완 is not None or 관계보완 is not None or 새덮기)
                   else self.observations + ([text] if keeps else []))
        # 보완은 **원문을 안 고친다.** 어느 사건의 어느 역할을 어떤 값으로 채웠다고
        # 적어 두고 다시 셈할 뿐이다. 원문도 근거도 차례도 그때의 뜻도 그대로다.
        # A hypothetical answer belongs to its held query, not the actual
        # replay ledger.  It is still keyed by the same action event ID.
        for ask, 값들 in (completion or []):
            if ask.get("가정사건"):
                ask["가정채움"] = {**ask.get("가정채움", {}), **값들}
        새채움 = [{"사건": ask["사건"], "역할": key, "값": value, "근거": text.strip()}
                for ask, 값들 in (completion or []) if not ask.get("가정사건")
                for key, value in 값들.items()]
        if 상태보완 is not None:
            ask, fill = 상태보완
            # A state fact supplied for a hypothetical query belongs to that
            # query's isolated world just like a role reply does.  Do not put
            # it in the real replay ledger: it answered what the event could
            # read *if* it happened, not a new actual observation.
            if ask.get("가정사건"):
                if fill.get("변수"):
                    ask["가정조회값"] = {**ask.get("가정조회값", {}),
                                      fill["변수"]: fill["값"]}
                if fill.get("사실"):
                    ask["가정조회사실"] = [*ask.get("가정조회사실", []), fill["사실"]]
            else:
                새채움.append({"사건": ask["사건"], **fill, "근거": text.strip()})
        if 관계보완 is not None:
            ask, fill = 관계보완
            새채움.append({"사건": ask["사건"], **fill, "근거": text.strip()})
        새채움 += 문맥채움 + 새덮기
        if (keeps and self._is_statement(current) and not current.get("query") and not getattr(self, "_rereading", False)
                and completion is None and self._thing_as_holder(
                    parser, [f["triple"] for f in current.get("facts", []) if isinstance(f.get("triple"), list)])):
            # G5.4 B: the first reading puts a thing the conversation counts where a holder stands (청소기는 창민이
            # N대 가지고 있어요 read as the 청소기's 창민): the reader's other readings are checked
            checked = self._check_readings(parser, text, verbs, knowledge_path, first_failure="thing_as_holder")
            if checked is not None:
                return checked
        if (keeps and self._effort_allows(2) and self._is_statement(current) and not current.get("query")
                and completion is None and 상태보완 is None and 관계보완 is None and not 새덮기
                and not getattr(self, "_rereading", False)):
            # G7-S: a holder this statement moves, counted before under another key (effort 2)
            self._read_other_keys(parser, text, current, verbs)
            # G7-S experiment 2: a statement that names no thing, its holders counting two things or none
            unsaid = self._read_unsaid_thing(parser, text, current, verbs, knowledge_path)
            if unsaid is not None:
                return unsaid
        try:
            if keeps and completion is None and not current.get("query") and self._holder_unsaid(parser, text, current):
                # a change whose holder the reading does not say, in a statement with a subject phrase the reading
                # passed over, is not charged to the one holder that has a count (``_holder_unsaid``): the
                # statement is held, and remembered as unread
                raise ValueError("ambiguous_quantity_subject")
            facts, defined, unsettled, 읽힘 = self._cached_replay(
                parser, pending, self.fills + 새채움)
            # A valid completion remains evidence even when replay exposes a
            # later requirement and returns early below.  Otherwise the role
            # answer disappears between the first and second clarification.
            if completion is not None or 상태보완 is not None or 관계보완 is not None or 문맥채움 or 새덮기:
                self.fills += 새채움
                del self.fills[:-self.max_turns]
            # `result`는 재생 전 만든 껍데기다. 실제로 고른 재생 범위를 검증
            # 근거에 반영해, 답이 캐시인지 영향 꼬리인지 확인 가능하게 한다.
            result["verification"] = self._verification(knowledge_path, [])
            # 뜻을 알게 된 낱말의 사건은 더 이상 막지 않는다 — 설명을 듣고 이어 푼다.
            self.unread = [entry for entry in self.unread if entry.get("말") is None
                           or self._unread_marked(entry)
                           or self._lookup(parser, {"verb": entry["말"], "꼬리": entry.get("꼬리", "")},
                                           defined) is None]
            self.unread_guard = [entry for entry in self.unread_guard if entry.get("말") is None
                                 or self._unread_marked(entry)
                                 or self._lookup(parser, {"verb": entry["말"], "꼬리": entry.get("꼬리", "")},
                                                 defined) is None]
            # Validate a new observation even if no question has been asked yet.
            _, changes = current_facts(facts, parser.data.get("mutable_predicates", []),
                                       parser.data.get("numeric_updates", {}))
            self._unit_conflict = self._unit_kinds_differ(parser, facts, len(pending) - 1) if keeps else None
            if self._unit_conflict is not None:
                # a change said in a unit of another kind than its count's: not moved, the statement is held
                raise ValueError("unit_mismatch")
            if keeps and self._pointer_unknown(parser, [row for row in changes if (row.get("evidence") or {})
                                                        .get("turn") == len(pending) - 1]):
                # A pointer as a new holder is no holder: fail as a holder without a count, so the
                # pointer readings are checked (G6, receiver count), or the statement is held as before.
                raise ValueError("missing_initial_quantity")
            # 설명을 듣긴 했는데 몸통을 못 읽었다면 그렇다고 말한다. "모르는
            # 낱말" 이라고만 하면 방금 설명한 사람에게는 틀린 말로 들린다.
            # 다시 읽기가 **그때까지 배운 것**을 쥐고 이미 판정했다. 여기서 맨손으로
            # 또 읽으면, 배운 동작을 재료로 쓴 뜻풀이를 못 읽었다고 잘못 말한다.
            unreadable = next((rule["몸통"] for rule in current.get("정의", [])
                               if rule.get("몸통") and rule["몸통"] not in 읽힘), None)
            if unreadable is not None:
                self.observations = pending
                return {**result, "status": "unresolved",
                        "meaning": {"act": "hold", "reason": "unreadable_definition", "said": unreadable},
                        "answer": replies["unreadable_definition"].format(**{"몸통": unreadable})}
            unknown = next((event["verb"] for event in current.get("사건", [])
                            if self._lookup(parser, event, defined) is None), None)
            if unknown is not None:
                # 모르는 말은 틀린 조건이 아니다. 무엇을 모르는지 짚어서 물어본다.
                # 관찰로는 **남긴다** — 나중에 설명을 들으면 이어서 풀어야 한다.
                self.observations = pending
                said = text.strip()
                꼬리 = next((event.get("꼬리", "") for event in current.get("사건", [])
                            if event["verb"] == unknown), "")
                self._remember_unread({"text": said, "at": len(self.observations) - 1,
                                     "말": unknown, "꼬리": 꼬리})
                return {**result, "status": "unresolved",
                        "meaning": {"act": "hold", "reason": "unknown_word", "word": unknown, "said": said},
                        "answer": replies["unknown_word"].format(**{"말": unknown})}
            # 자리를 못 채운 사건. 무슨 일이 있었는지는 읽었지만 누구의 값이
            # 움직였는지를 모른다. "반영했습니다" 라고 하면 그 값을 옛 값 그대로
            # 확정하게 된다 — 해석 실패를 변화 없음으로 바꾸는 자리다.
            # A short role reply replays an older source.  Its newly exposed
            # lookup need is therefore attached to that source, not to the
            # reply text; include exactly the events this reply completed.
            just_filled = {ask["사건"] for ask, _values in (completion or [])
                           if not ask.get("가정사건")}
            # Keep an existing role question while other role slots remain.
            # Only a role-complete event is allowed to expose a new state
            # requirement in this same turn.
            role_complete = {item.get("id") for item in unsettled
                             if item.get("id") in just_filled and not item.get("빈자리")}
            fresh = [item for item in unsettled
                     if item["text"] == text or item.get("id") in role_complete]
            unfilled = fresh[0] if fresh else None
            # 이 메시지에서 자리를 못 채운 사건들을 **하나씩** 적어 둔다. 하나만
            # 들고 있으면 앞엣것이 영영 되물어지지 않은 채로 남는다.
            # A settled role question must not suppress the next requirement
            # of the same event (for example, role completion followed by a
            # state lookup).  Only an outstanding question owns the event.
            적힌것 = {ask["사건"] for ask in self.asked
                     if not ask.get("해결") and ask["사건"] not in role_complete}
            새되물음 = [{"id": "%s#%d" % (item["id"], len(self.asked) + n),
                     "종류": "빈자리", "사건": item["id"], "동사": item["동사"],
                     "자리": dict(item["자리"]), "빈자리": dict(item["빈자리"]),
                     "해결": False}
                    for n, item in enumerate(fresh)
                    if item["빈자리"] and item["id"] not in 적힌것]
            self.asked += 새되물음
            조회되물음 = [{"id": "%s?조회" % item["id"], "종류": "조회",
                         "사건": item["id"], "동사": item["동사"],
                         "자리": dict(item["자리"]), "빈자리": {},
                         "필요": deepcopy(item["필요"]), "해결": False}
                        for item in fresh if item.get("필요") and not item.get("거짓조건")
                        and item["id"] not in 적힌것]
            self.asked += 조회되물음
            del self.asked[:-self.max_turns]
            if unfilled is not None and unfilled.get("못잼"):
                # 값을 지어내지 않는다. 기준을 모르는 것과 나누어떨어지지 않는
                # 것은 다른 까닭이므로 갈라서 말한다.
                self.observations = pending
                말투 = self._못잰까닭(unfilled["못잼"])
                return {**result, "status": "unresolved",
                        "meaning": {"act": "hold", "reason": 말투, "said": text.strip()},
                        "answer": replies[말투].format(**{"말": text.strip()})}
            if (unfilled is not None and unfilled.get("잘림")
                    and not (unfilled["빈자리"] or unfilled["충돌"] or unfilled["헛자리"])):
                self.observations = pending
                return {**result, "status": "unresolved",
                        "meaning": {"act": "hold", "reason": "too_many_readings", "said": text.strip()},
                        "answer": replies["too_many_readings"].format(**{"말": text.strip()})}
            if unfilled is not None and unfilled["헛자리"] and not unfilled["충돌"]:
                self.observations = pending
                return {**result, "status": "unresolved",
                        "meaning": {"act": "hold", "reason": "extra_argument", "said": text.strip(),
                                    "rest": ", ".join(sorted(unfilled["헛자리"].values()))},
                        "answer": replies["extra_argument"].format(**{
                            "말": text.strip(),
                            "남은": ", ".join(sorted(unfilled["헛자리"].values()))})}
            if unfilled is not None and unfilled["충돌"]:
                # 빈 자리를 채운 것이 아니라 뜻풀이가 정한 값과 어긋난 것이다.
                # 어느 쪽이 맞는지는 우리가 고를 일이 아니다 — **어디까지인지** 묻는다.
                self.observations = pending
                name, 값 = next(iter(unfilled["충돌"].items()))
                if unfilled["id"] not in {a["사건"] for a in self.asked if a["종류"] == "충돌"}:
                    self.asked.append({"id": unfilled["id"] + "?충돌", "종류": "충돌",
                                       "사건": unfilled["id"], "동사": unfilled["동사"],
                                       "차례": unfilled["차례"], "역할": 값["자리"],
                                       "값": 값["사건"], "자리": dict(unfilled["자리"]),
                                       "빈자리": {}, "해결": False})
                    del self.asked[:-self.max_turns]
                return {**result, "status": "unresolved",
                        "meaning": {"act": "ask", "reason": "conflicting_definition", "said": text.strip(),
                                    "declared": 값["뜻"], "given": 값["사건"],
                                    "choices": [words[0] for words in parser.scope_words.values() if words]},
                        "answer": replies["conflicting_definition"].format(**{
                            "말": text.strip(), "정한값": 값["뜻"], "온값": 값["사건"]})}
            if unfilled is not None:
                self.observations = pending
                return {**result, "status": "unresolved",
                        "meaning": {"act": "ask", "reason": "unfilled_role", "said": text.strip(),
                                    "slots": [self._slot_name(parser, key)
                                              for key in sorted(set(unfilled["빈자리"].values()))],
                                    "slot_keys": sorted(set(unfilled["빈자리"].values()))},
                        "answer": replies["unfilled_role"].format(**{
                            "말": text.strip(),
                            "물음": self._slot_question(parser, unfilled["빈자리"])})}
            # A question that names people fixes them for a later pointer, held
            # or answered (G3.0 a). A pointer it holds is fixed once resolved.
            asked_people = self._named_people(parser, current["query"])
            if asked_people:
                self.salient = asked_people
            self._record_frame(parser, text, current["query"])
            unread = self._blocked_by(current["query"], parser, facts)
            unread_continuation = self._unread_continuation_start(text, current, parser, facts, unsettled, unread, result, replies)
            if unread is not None and unread_continuation is None:
                unread, 까닭 = unread
                self.held_question = text
                # 못 읽은 말과 앞말과 어긋난 말은 막는 까닭이 다르다. 어긋난 것을
                # "못 읽었다" 고 하면 방금 또렷이 말한 사람에게 틀린 말이 된다.
                까닭 = 까닭 or next((entry.get("까닭") for entry in self.unread_guard + self.unread
                                      if entry["text"] == unread), None)
                말투 = ("contradiction" if 까닭 == "어긋남" else
                        "capacity" if 까닭 == "용량" else "unread_event")
                return {**result, "status": "unresolved",
                        "meaning": {"act": "hold", "reason": 말투, "said": unread},
                        "answer": replies[말투].format(**{"말": unread})}
            blocked = self._unsettled(current["query"], parser, unsettled)
            if blocked is not None and blocked.get("못잼"):
                self.held_question = text
                말투 = self._못잰까닭(blocked["못잼"])
                return {**result, "status": "unresolved",
                        "meaning": {"act": "hold", "reason": 말투, "said": blocked["text"].strip()},
                        "answer": replies[말투].format(**{"말": blocked["text"].strip()})}
            if (blocked is not None and blocked.get("잘림")
                    and not (blocked["빈자리"] or blocked["충돌"] or blocked["헛자리"])):
                self.held_question = text
                return {**result, "status": "unresolved",
                        "meaning": {"act": "hold", "reason": "too_many_readings", "said": blocked["text"].strip()},
                        "answer": replies["too_many_readings"].format(**{
                            "말": blocked["text"].strip()})}
            if blocked is not None and blocked["헛자리"] and not blocked["충돌"]:
                self.held_question = text
                return {**result, "status": "unresolved",
                        "meaning": {"act": "hold", "reason": "extra_event", "said": blocked["text"].strip(),
                                    "rest": ", ".join(sorted(blocked["헛자리"].values()))},
                        "answer": replies["extra_event"].format(**{
                            "말": blocked["text"].strip(),
                            "남은": ", ".join(sorted(blocked["헛자리"].values()))})}
            if blocked is not None and blocked["충돌"]:
                self.held_question = text
                name, 값 = next(iter(blocked["충돌"].items()))
                return {**result, "status": "unresolved",
                        "meaning": {"act": "hold", "reason": "conflicting_event", "said": blocked["text"].strip(),
                                    "declared": 값["뜻"], "given": 값["사건"]},
                        "answer": replies["conflicting_event"].format(**{
                            "말": blocked["text"].strip(), "정한값": 값["뜻"], "온값": 값["사건"]})}
            if blocked is not None:
                self.held_question = text
                return {**result, "status": "unresolved",
                        "meaning": {"act": "hold", "reason": "unsettled_event", "said": blocked["text"].strip(),
                                    "slots": sorted({self._slot_name(parser, key)
                                                     for key in blocked["빈자리"].values()})},
                        "answer": replies["unsettled_event"].format(**{
                            "말": blocked["text"].strip(),
                            "자리": ", ".join(sorted({self._slot_name(parser, key)
                                                    for key in blocked["빈자리"].values()}))})}
            concept_answer = self._answer_concept_query(parser, current["query"])
            if any(isinstance(row, dict) and row.get("concept_query") for row in (current["query"] or [])):
                if concept_answer is None:
                    return {**result, "status": "unresolved", "answer": replies["unresolved"],
                            "meaning": {"act": "hold", "reason": "unresolved"}}
                return {**result, **concept_answer, "status": "answered"}
            relation_answer = self._answer_event_relation_query(parser, current["query"])
            if any(isinstance(row, dict) and row.get("event_relation_query") for row in (current["query"] or [])):
                if relation_answer is None:
                    return {**result, "status": "unresolved", "answer": replies["unresolved"],
                            "meaning": {"act": "hold", "reason": "unresolved"}}
                return {**result, **relation_answer, "status": "answered"}
            if any(isinstance(row, dict) and row.get("concept_reason_query") for row in (current["query"] or [])):
                concept_reason = self._answer_concept_reason(parser)
                if concept_reason is None:
                    return {**result, "status": "unresolved", "answer": replies["unresolved"],
                            "meaning": {"act": "hold", "reason": "unresolved"}}
                return {**result, **concept_reason, "status": "answered"}
            if any(isinstance(row, dict) and row.get("why_last") for row in (current["query"] or [])):
                return self._explain_last(parser, knowledge_path)
            why_count = next((row["why_count"] for row in (current["query"] or [])
                              if isinstance(row, dict) and row.get("why_count")), None)
            if why_count is not None:
                return self._explain_count(parser, why_count, text, facts, knowledge_path)
            other = next((row["other_than"] for row in (current["query"] or [])
                          if isinstance(row, dict) and row.get("other_than")), None)
            if other is not None:
                return self._answer_other_than(parser, other, facts, knowledge_path)
            풀린물음, 가리킴 = self._resolve_pointers(parser, current["query"], facts)
            if 가리킴 is not None and not 가리킴["후보"] and self._effort_allows(2) and not self._in_name_reply:
                # a pointer that finds no holder: the holders of the conversation's thing, as a description
                which = self._which_person(parser, text, knowledge_path)
                if which is not None and "query" not in which:
                    return which
                if which is not None:
                    풀린물음, 가리킴 = which["query"], None
            if 가리킴 is not None:
                self.held_question = text
                if 가리킴["후보"]:
                    self.pending_pointer = {"question": text.strip(), "pointer": 가리킴["말"],
                                            "candidates": list(가리킴["후보"])}
                말투 = "which_referent" if 가리킴["후보"] else "no_referent"
                return {**result, "status": "unresolved",
                        "meaning": {"act": "ask", "reason": 말투, "word": 가리킴["말"],
                                    "candidates": list(가리킴["후보"])},
                        "answer": replies[말투].format(**{
                            "말": 가리킴["말"],
                            "목록": ", ".join("'%s'" % 이름 for 이름 in 가리킴["후보"])})}
            # A pointer read as one person fixes that person now.
            resolved = [self._person_of(new["triple"][0]) for old, new in zip(current["query"] or [], 풀린물음 or [])
                        if isinstance(new, dict) and isinstance(new.get("triple"), list) and new["triple"]
                        and isinstance(new["triple"][0], str) and new["triple"][0].strip()
                        and new["triple"][0] != (old.get("triple") or [None])[0]]
            if resolved:
                self.salient = resolved[:1]
            답사실, 가정전이, assumed = facts, [], []
            if current.get("가정") or current.get("가정사건"):
                # A hypothesis is a separate execution world.  Direct
                # numeric premises and learned action calls both contribute
                # ordinary transition triples to that world, then the same
                # current_facts projection answers this one question only.
                assumed.extend({"triple": item["triple"],
                                "evidence": {**item["evidence"], "mode": "hypothetical"}}
                               for item in current.get("가정", []))
                이름 = {part for item in facts for part in str(item["triple"][0]).split()}
                for event in current.get("가정사건", []):
                    stem = self._lookup(parser, event, defined, verbs)
                    rule = defined.get(stem) if stem else None
                    if rule is None:
                        self.held_question = text
                        return {**result, "status": "unresolved",
                                "meaning": {"act": "hold", "reason": "unknown_word", "word": event["verb"],
                                            "said": text.strip()},
                                "answer": replies["unknown_word"].format(**{"말": event["verb"]})}
                    event_key = "hypothesis:" + self._event_id(
                        len(self.observations), stem, event["자리"], 0)
                    supplied = next((ask.get("가정채움", {}) for ask in self.asked
                                     if ask.get("가정사건") == event_key), {})
                    supplied_values = next((ask.get("가정조회값", {}) for ask in self.asked
                                            if ask.get("가정사건") == event_key), {})
                    supplied_facts = next((ask.get("가정조회사실", []) for ask in self.asked
                                           if ask.get("가정사건") == event_key), [])
                    from marco.reasoning.actions import event_record
                    hypothetical_event = {**event, "modality": "hypothetical"}
                    record = event_record(event_key, rule["프로그램"], hypothetical_event,
                        sequence=len(self.observations), evidence=event["evidence"], fills=supplied)
                    applied = self._triples(parser, rule, {**hypothetical_event, "실행": record}, 이름, supplied, (), facts,
                                            programs=getattr(defined, "programs", None),
                                            조회값=supplied_values, 조회사실=supplied_facts)
                    if applied["빈자리"]:
                        # Hypotheses have no observation row.  Keep a stable
                        # event key on the question so a short answer fills
                        # this action only, then reruns the held query.
                        existing = next((ask for ask in self.asked
                                         if ask.get("가정사건") == event_key and not ask.get("해결")), None)
                        if existing is None:
                            self.asked.append({"id": event_key + "?빈자리", "종류": "빈자리",
                                               "사건": event_key, "가정사건": event_key,
                                               "동사": stem, "자리": dict(event["자리"]),
                                               "빈자리": dict(applied["빈자리"]), "해결": False})
                            del self.asked[:-self.max_turns]
                        self.held_question = text
                        return {**result, "status": "unresolved",
                                "meaning": {"act": "ask", "reason": "unfilled_role", "said": text.strip(),
                                            "slots": [self._slot_name(parser, key)
                                                      for key in sorted(set(applied["빈자리"].values()))],
                                            "slot_keys": sorted(set(applied["빈자리"].values()))},
                                "answer": replies["unfilled_role"].format(**{
                                    "말": text.strip(), "물음": self._slot_question(parser, applied["빈자리"])})}
                    if applied.get("필요"):
                        # State reads are also missing inputs.  The question
                        # is keyed to the hypothetical action, so its answer
                        # reruns this same program without becoming a real
                        # timeline fact.
                        existing = next((ask for ask in self.asked
                                         if ask.get("가정사건") == event_key
                                         and ask.get("종류") == "조회" and not ask.get("해결")), None)
                        if existing is None:
                            self.asked.append({"id": event_key + "?조회", "종류": "조회",
                                               "사건": event_key, "가정사건": event_key,
                                               "동사": stem, "자리": dict(event["자리"]),
                                               "빈자리": {}, "필요": deepcopy(applied["필요"]),
                                               "해결": False})
                            del self.asked[:-self.max_turns]
                        self.held_question = text
                        return {**result, "status": "unresolved",
                                "meaning": {"act": "hold", "reason": self._못잰까닭(applied.get("못잼")),
                                            "said": text.strip()},
                                "answer": replies[self._못잰까닭(applied.get("못잼"))].format(**{
                                    "말": text.strip()})}
                    if applied["충돌"] or applied["헛자리"] or applied.get("못잼"):
                        self.held_question = text
                        return {**result, "status": "unresolved",
                                "meaning": {"act": "hold", "reason": self._못잰까닭(applied.get("못잼")),
                                            "said": text.strip()},
                                "answer": replies[self._못잰까닭(applied.get("못잼"))].format(**{
                                    "말": text.strip()})}
                    assumed.extend({"triple": triple,
                                    "evidence": {**event["evidence"], "mode": "hypothetical",
                                                 "action_event": record}}
                                   for triple in applied["사실"])
                    가정전이.append({"operation": "hypothetical_action", "event": record,
                                     "bindings": applied.get("계산값", {})})
                # 가정은 대화 사실에 합치지 않는다. 이 답을 내는 동안에만
                # `asserted`로 투영하고, 근거에는 가정임을 남긴다.
                답사실, 투영전이 = current_facts(
                    facts + assumed, parser.data.get("mutable_predicates", []),
                    parser.data.get("numeric_updates", {}))
                가정전이 += [{"operation": "hypothetical_assumption", "fact": item["triple"],
                              "evidence": item["evidence"]} for item in assumed]
                가정전이 += [item for item in 투영전이
                            if item.get("evidence", {}).get("mode") == "hypothetical"]
            if 풀린물음:
                # Keep the ordinary no-overlay path byte-for-byte compatible
                # with its existing state trace.  Once an active application
                # exists, however, every normal query shares the augmented
                # facts and pack rules; a hypothetical branch merely supplies
                # temporary facts and cannot create a real application.
                # Activation needs at least three independent records and a
                # holdout.  Before four observations it is impossible, so do
                # not materialise an event ledger merely for an unrelated
                # state lookup (doing so would perturb its replay cache).
                if len(self.observations) >= 4:
                    records = self._event_ledger()
                    self.concepts.sync(records)
                    if self.concepts.applications:
                        답사실 = self._common_inference_facts(parser, 답사실)
            if (any(isinstance(row, dict) and any(row.get(kind) for kind in ("total", "more", "fewer", "same"))
                    for row in 풀린물음 or [])
                    and (self.unread or self.unread_guard or unsettled)):
                # A sum or a comparison reads several holders at once; an
                # unread or unsettled event may have moved any of them.
                self.held_question = text
                said = (self.unread_guard + self.unread)[0]["text"] if (self.unread or self.unread_guard) \
                    else unsettled[0]["text"]
                return {**result, "status": "unresolved",
                        "meaning": {"act": "hold", "reason": "unread_event", "said": said},
                        "answer": replies["unread_event"].format(**{"말": said})}
            if 풀린물음 and not (self.unread or self.unread_guard):
                # a total or a comparison over "the two" takes its holders and thing from the conversation
                풀린물음 = self._ground_pair(parser, 풀린물음, 답사실)
            if 풀린물음:
                # G7-S: a thing counted in two units is asked in one of them, or held (never one count for the other)
                풀린물음, units = self._asked_in_unit(parser, text, 풀린물음, 답사실)
                if units is not None:
                    self.held_question = text
                    return {**result, "status": "unresolved",
                            "meaning": {"act": "hold", "reason": "unresolved", **units},
                            "answer": replies["unresolved"]}
            if 풀린물음 and not (self.unread or self.unread_guard):
                # a count asked under a key the state does not have may name a key it has (G7-Q, effort 2); words
                # that describe several holders are asked back with every candidate
                풀린물음, which = self._ground_lookup(parser, 풀린물음, 답사실)
                if which is not None:
                    return self._ask_which(parser, text, which, result)
            outcome = ((parser.answer(_selected) if (_selected := self._selected_negative_answer_input(
                parser, text, current, 답사실, 풀린물음)) is not None else None) if 풀린물음 else None)
            if unread_continuation is not None:
                qualified = self._unread_continuation_finish(unread_continuation, text, current, parser, 풀린물음, 답사실, outcome)
                if qualified is None:
                    self.held_question = text
                    return unread_continuation["hold"]
                outcome = qualified
            if (outcome is None and 풀린물음 and self._effort_allows(2) and not self._in_name_reply
                    and not (self.unread or self.unread_guard)):
                # a holder the state does not count, said as a description (the tall one, her brother): the
                # holders of the conversation's thing
                which = self._which_person(parser, text, knowledge_path)
                if which is not None and "query" not in which:
                    return which
                if which is not None:
                    풀린물음 = which["query"]
                    outcome = (parser.answer(_selected) if (_selected := self._selected_negative_answer_input(
                        parser, text, current, 답사실, 풀린물음)) is not None else None)
            if outcome is None and 풀린물음:
                빠진전제 = self._missing_premise(parser, 풀린물음, 답사실)
                if 빠진전제 is None:
                    # Nobody in the question was ever mentioned: say whom.
                    모르는것 = self._unknown_subject(풀린물음, 답사실)
                    if 모르는것 is not None and "not_stated" in replies:
                        빠진전제 = replies["not_stated"].format(**{"대상": 모르는것})
                        self._not_stated = 모르는것
            if outcome is not None and 가정전이:
                outcome["transitions"] = 가정전이 + outcome.get("transitions", [])
            if outcome is not None and 풀린물음:
                # 무엇에 대해 답했는지 적어 둔다. 다음 지시어가 이것을 가리킨다.
                대상 = (풀린물음[0].get("triple") or [None])[0]
                if isinstance(대상, str) and not 대상.startswith(("?", "$")):
                    self.last_subject = 대상
                    self.last_question = {"text": text.strip(), "subject": 대상}
                    self.pending_pointer = None
        except ReadingUnavailable:
            raise
        except ValueError as exc:
            # **못 읽은 것과 앞말과 안 맞는 것은 다르다 — 그러나 둘 다 버리지 않는다.**
            #   못 읽음  — 말을 어디에 놓을지 몰랐다.
            #   안 맞음  — 읽었는데 앞서 들은 것과 셈이 안 맞는다. 사용자가
            #              일어났다고 말한 일을 우리가 "안 일어났다" 로 바꿀 수는
            #              없다. 처음 수량이 틀렸을 수도, 중간 사건이 빠졌을 수도
            #              있다. 두 말을 다 남기고 값은 확정하지 않은 채 묻는다.
            said, reason = text.strip(), str(exc)
            if (reason in self.UNPLACED | self.CONTRADICTION and keeps and not current.get("query")
                    and not getattr(self, "_rereading", False)):
                if reason == "missing_initial_quantity" and self._effort_allows(2) and completion is None:
                    # identity graph: the thing said with fewer of its words, or in its other number
                    alias = self._read_thing_alias(parser, text, current, verbs, knowledge_path)
                    if alias is not None:
                        return alias
                    # G7-S experiment 4: the word in the thing slot may not be the thing
                    wrong = self._read_wrong_thing(parser, text, current, verbs, knowledge_path)
                    if wrong is not None:
                        return wrong
                # G5.4 B: the reader's first reading does not fit the state; its other readings are checked
                checked = self._check_readings(parser, text, verbs, knowledge_path, first_failure=reason)
                if checked is not None:
                    return checked
            if reason in self.UNPLACED | self.CONTRADICTION and keeps:
                # 대상이 생략된 가변 상태 변화는 어느 기존 대상을 바꿨는지
                # 모르므로, 원문에 이름이 없더라도 같은 관계의 질의를 막는다.
                # 이를 남기지 않으면 모호한 `창고로 옮겼다` 뒤에 공책의 옛
                # 위치를 사실처럼 답하게 된다.
                relations = [row["triple"][1] for row in current.get("facts", [])
                             if row.get("triple") and row["triple"][0] is None]
                self._remember_unread({"text": said, "at": len(self.observations),
                                     **({"까닭": "어긋남"} if reason in self.CONTRADICTION
                                        else {}),
                                     **({"관계": relations[0]} if len(set(relations)) == 1 else {})})
            result["verification"]["checks"].append({"ok": False, "reason": reason})
            answer = (replies["contradiction"].format(**{"말": said})
                      if reason in self.CONTRADICTION else replies["invalid"])
            return {**result, "status": "unresolved", "answer": answer,
                    "meaning": {"act": "hold", "reason": "contradiction" if reason in self.CONTRADICTION
                                else "invalid", "said": said,
                                **(dict(self._unit_conflict) if reason == "unit_mismatch"
                                   and getattr(self, "_unit_conflict", None) else {})}}
        self._refresh_role_asks(unsettled)
        self.observations = pending
        if keeps:
            self._remember_referents(current)
        result["verification"]["checks"].append({"ok": True, "observation_turns": len(pending)})
        # 이번 보완이 일부 자리만 채웠다면 그 사건은 여전히 실행되지 않았다.
        # 성공 메시지나 보류 물음 재시도로 그 사실을 가리지 않는다.
        incomplete = next((item for item in unsettled
                           if any(ask.get("사건") == item.get("id")
                                  for ask, _values in (completion or []))), None)
        if incomplete is not None:
            return {**result, "status": "unresolved",
                    "meaning": {"act": "ask", "reason": "unfilled_role", "said": incomplete["text"].strip(),
                                "slots": [self._slot_name(parser, key)
                                          for key in sorted(set(incomplete["빈자리"].values()))],
                                "slot_keys": sorted(set(incomplete["빈자리"].values()))},
                    "answer": replies["unfilled_role"].format(**{
                        "말": incomplete["text"].strip(),
                        "물음": self._slot_question(parser, incomplete["빈자리"])}),
                    "transitions": changes}
        if outcome:
            self.last_explanation = {"kind": "answer", "question": text.strip(),
                                     "answer": outcome.get("answer"),
                                     "transitions": deepcopy(outcome.get("transitions", []))}
            self.last_mentioned = [self.last_subject] if isinstance(self.last_subject, str) else []
            asked = (current["query"] or [None])[0]
            return {**result, **outcome, "status": "answered",
                    "meaning": {"act": "inform", "query": deepcopy((풀린물음[0] if 풀린물음 else {}).get("triple")),
                                "render": deepcopy((풀린물음[0] if 풀린물음 else {}).get("render")),
                                # The question's own words before a pointer was resolved: whom it named.
                                "asked": deepcopy(asked.get("triple")) if isinstance(asked, dict) else None,
                                **self._compared(풀린물음[0] if 풀린물음 else None, outcome.get("transitions"))}}
        # 짧은 답으로 자리가 채워졌으면 막아 두었던 물음에 이어서 답한다.
        if (짧은답 is not None or 상태보완 is not None) and self.held_question and not current["query"]:
            question, self.held_question = self.held_question, None
            again = self._turn_reply(question, knowledge_path)
            if again is not None and again.get("status") == "answered":
                return again
        # 이번 말이 바꾼 것만 말한다. 앞선 턴의 변화는 이미 말했다.
        this_turn = [change for change in changes
                     if (change.get("evidence") or {}).get("turn") == len(self.observations) - 1]
        shaken = None if current["query"] else self._shaken_by_unread(parser, facts, this_turn)
        if shaken is not None:
            # G5.3 safety: kept, but a count resting on an unread statement is not said as fixed.
            return {**result, "status": "unresolved",
                    "meaning": {"act": "hold", "reason": "unread_event", "said": shaken, "kept": True},
                    "answer": replies["unread_event"].format(**{"말": shaken}),
                    "transitions": changes}
        spoken = parser.render_changes(this_turn) if "observed_state" in replies else ""
        settled = (replies["scope_settled"].format(**{"범위": 정해짐}) if 정해짐
                   else replies["filled_role"] if completion is not None
                   else replies["observed_state"].format(**{"목록": spoken}) if spoken
                   else replies["observed"])
        if current["query"]:
            premise = self._premise_missing(parser, 풀린물음, 답사실) if 빠진전제 else None
            unknown, self._not_stated = getattr(self, "_not_stated", None), None
            # A count the conversation gave only as "some" (request W3-1: vague_count).
            asked = [str((q.get("triple") or [None])[0]) for q in (풀린물음 or []) if isinstance(q, dict)]
            try:
                # A holder that received something but whose count was never said is count_unknown after
                # the projection (graph_inference.current_facts), with the least it is known to hold.
                projected = current_facts(답사실 or [], parser.data.get("mutable_predicates", []),
                                          parser.data.get("numeric_updates", {}))[0]
            except ValueError:
                projected = 답사실 or []
            vague_fact = next((f for f in projected
                               if f["triple"][1] == "count_unknown" and str(f["triple"][0]) in asked), None)
            vague = str(vague_fact["triple"][0]) if vague_fact else None
            self._vague_asked = (vague, len(self.observations)) if vague else None
            meaning = ({"act": "hold", "reason": "vague_count", "subject": vague,
                        # G6-2: the count was never said and something was added since (at least this many)
                        **({"at_least": vague_fact["at_least"]} if "at_least" in vague_fact else {})} if vague
                       else {"act": "refuse", "reason": "premise_missing", **premise} if premise
                       else {"act": "hold", "reason": "not_stated", "subject": unknown} if unknown and 빠진전제
                       else {"act": "hold", "reason": "unresolved"})
        else:
            said_vague = [str(f["triple"][0]) for f in current.get("facts", [])
                          if f["triple"][1] == "count_unknown"]
            meaning = {"act": "record",
                       "reason": ("scope_settled" if 정해짐 else "filled_role" if completion is not None
                                  else "observed_state" if spoken
                                  else "vague_count" if said_vague else "observed"),
                       "turn": len(self.observations) - 1, "changes": deepcopy(this_turn)}
            if said_vague and not spoken:
                meaning["subject"] = said_vague[0]
            if 정해짐:
                # The scope as the user's language declares its first word.
                meaning["scope"] = (parser.scope_words.get(정해짐) or [정해짐])[0]
        return {**result, "status": "unresolved" if current["query"] else "observed",
                "answer": (빠진전제 or replies["unresolved"]) if current["query"] else settled,
                "meaning": meaning,
                "transitions": changes}
