"""Detached typed language program reader (foundation unit).

Reads a language program stored as ordinary graph nodes (string-example lists in
layer mappings) and same-graph edge triples through a pinned ``GraphView``. Only
``view.graph_with_origins``, ``view.key`` and ``view.base_origin`` are touched;
nothing is written. ``project_predicate_frames`` projects the root's ordered rules
into detached predicate-frame data, reading each rule with a fresh reader.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
import json
import re
import unicodedata

from marco.storage import ids as _ids

__all__ = ["LanguageProjectionGap", "project_predicate_frames", "project_language_dialogue", "project_action_grounding", "project_action_learning"]

_EDGE_LISTS = ("엣지", "개념엣지")
_MAX_NODES = 512
_MAX_EDGES = 1024
_MAX_ITEMS = 64
_INT_RE = re.compile(r"^(0|-?[1-9][0-9]*)$")

#: Outgoing program relation whitelist per operation: relation -> required flag.
_SHAPES = {
    "root": {"op": True, "rules": True, "head-pattern": True, "ignore-case": True,
             "separators": True, "terminators": True, "operators": True,
             "queries": False, "replies": False, "question-marks": False,
             "hypotheses": False, "learning-controls": False,
             "unread-continuation": False, "action-grounding": False,
             "fact-batch": False, "grammar-ref": False},
    "sequence": {"op": True, "first": False},
    "grammar-ref": {"op": True, "member-path": True, "sha256": True, "schema": True},
    "inflection-ref": {"op": True, "stem": True, "tense": True, "ending": True,
                       "kind": True, "endings": True},
    "rule": {"op": True, "reads": True, "binds": True, "emits": True,
             "allowed-endings": True, "realizes": False, "inflection-ref": False},
    "role": {"op": True, "name": True, "seed": True, "mode": True, "markers": True, "side": False},
    "meaning": {"op": True, "subjects": True, "relation": True, "object": True,
                "polarity": False, "modality": False},
    "scalar": {"op": True, "next": False, "value": True},
    "literal": {"op": True, "next": False, "value": True},
    "predicate": {"op": True, "next": False, "value": True},
    "rule-ref": {"op": True, "next": False, "target": True},
    "role-ref": {"op": True, "next": False, "target": True},
    "slot": {"op": True, "next": False, "role": True},
    "sense": {"op": True},
    "query-ref": {"op": True, "next": False, "target": True},
    "reply-ref": {"op": True, "next": False, "target": True},
    "query-rule": {"op": True, "reads": True, "binds": True, "emits": True,
                   "answers": True, "terminal": True, "inflection-ref": False},
    "query-meaning": {"op": True, "subject": True, "relation": True, "object": True, "asked": True},
    "reply": {"op": True, "key": True, "value": True},
    "hypothesis-ref": {"op": True, "next": False, "target": True},
    "relation-hypothesis": {"op": True, "frame": True, "capture": True, "query": False},
    "learning-control-ref": {"op": True, "next": False, "target": True},
    "learning-control": {"op": True, "kind": True, "ownership-prefix": True, "text": True,
                         "slots": True, "expression-kind": False, "capture-terminals": False},
    "learning-slot": {"op": True, "next": False, "role": True, "seed": True},
    "known-evidence-policy": {"op": True, "scope": True, "render": True},
    "fact-batch-policy": {"op": True, "scope": True, "max-rows": True},
    "action-catalog": {"op": True, "catalog-id": True, "limits": True, "programs": True},
    "action-entry": {"op": True, "id": True, "version": True, "composable": True, "roles": True,
                     "program": True, "allowed-compute-operators": True, "label": True},
    "action-program": {"op": True, "steps": True},
    "known-evidence-policy-v2": {"op": True, "scope": True, "render": True, "max-pending": True},
    "action-role": {"op": True, "variable": True, "slot": True, "type-ref": True, "presence": True,
                    "coreference-group": True, "binding-mode": True},
    "action-type": {"op": True, "name": True},
    "action-value": {"op": True, "kind": True, "role": False, "literal": False},
    "action-emit": {"op": True, "triples": True, "next": False},
    "action-triple": {"op": True, "subject": True, "predicate": True, "object": True, "next": False},
    "action-call": {"op": True, "target": True, "bindings": True, "next": False},
    "action-call-binding": {"op": True, "role": True, "value": True, "next": False},
    "action-ref": {"op": True, "target": True, "next": False},
    "action-role-ref": {"op": True, "target": True, "next": False},
    "action-limits": {"op": True, "max-catalog-entries": True, "max-candidate-terms": True,
                      "max-program-steps": True, "max-call-depth": True,
                      "max-expanded-steps": True, "max-json-nodes": True,
                      "max-catalog-bytes": True},
    "action-grounding": {"op": True, "catalog": True, "surface": True, "policy": True,
                         "replies": True, "required-operators": True, "hypothesis-scope": True,
                         "learning": False},
    "action-sense-ref": {"op": True, "target": True, "next": False},
    "action-surface": {"op": True, "surface-id": True, "boundary": True, "case-groups": True,
                       "roles": True, "known-action-surfaces": True,
                       "coreference-policy": True, "limits": True},
    "action-boundary": {"op": True, "kind": True, "token-separator": True, "terminators": True,
                        "question-marks": True, "clause-separators": True,
                        "excluded-final-forms": True, "excluded-final-suffixes": True},
    "action-case-group": {"op": True, "id": True, "markers": True, "next": False},
    "action-surface-role": {"op": True, "case-group": True, "slot": True, "type-ref": True,
                            "presence": True, "coreference-group": True, "next": False},
    "action-surface-limits": {"op": True, "max-source-chars": True, "max-tokens": True,
                              "max-case-groups": True, "max-markers": True,
                              "max-role-candidates": True, "max-search-steps": True,
                              "max-json-nodes": True, "max-output-bytes": True},
    "action-policy": {"op": True, "policy-id": True, "association": True, "world": True,
                      "closed-predicates": True, "evidence-kinds": True,
                      "allowed-term-counts": True, "allow-repeated-terms": True,
                      "ranking": True, "limits": True},
    "action-association": {"op": True, "mode": True, "key-slot": True,
                           "functional-predicates": True, "before-selection": True,
                           "after-selection": True, "causal-status": True},
    "action-rank": {"op": True, "key": True, "direction": True, "next": False},
    "action-policy-limits": {"op": True, "max-candidates": True, "max-observations": True,
                             "max-window-turns": True, "max-pending": True,
                             "max-effect-triples": True, "max-output-bytes": True},
    "action-reply": {"op": True, "key": True, "text": True, "next": False},
    "action-learning": {"op": True, "policy-id": True, "admission": True, "meaning-scope": True,
                        "evidence-kind": True, "question-scope": True, "question-selection": True,
                        "retraction-scope": True, "active-use-scope": True, "forms": True,
                        "renders": True, "role-labels": True, "limits": True},
    "action-learning-role-label": {"op": True, "slot": True, "label": True, "next": False},
    "action-learning-limits": {"op": True, "max-forms": True, "max-form-chars": True,
                               "max-input-bytes": True, "max-question-bytes": True,
                               "max-target-bytes": True, "max-active-questions": True,
                               "max-terms": True, "max-roles": True, "max-archive-bytes": True,
                               "max-archive-events": True},
}
_ITEM_OPS = frozenset({"scalar", "literal", "predicate", "rule-ref", "role-ref", "slot",
                       "query-ref", "reply-ref", "hypothesis-ref", "learning-control-ref", "learning-slot",
                       "action-ref", "action-role-ref", "action-emit", "action-triple",
                       "action-call", "action-call-binding", "action-sense-ref",
                       "action-case-group", "action-surface-role", "action-rank",
                       "action-reply", "action-learning-role-label"})


class LanguageProjectionGap(ValueError):
    """Every refusal of the reader; ``.gap`` is a stable code string."""

    def __init__(self, message, gap):
        super().__init__(message)
        self.gap = str(gap)


def _digest(value):
    text = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _nfc(value):
    return unicodedata.normalize("NFC", value)


class _Program:
    """One detached read of a language program rooted at ``root`` in ``graph_id``."""

    def __init__(self, view, graph_id, root):
        try:
            self.graph_id = _ids.graph_id(graph_id)
        except TypeError as exc:
            raise LanguageProjectionGap(str(exc), "unsupported_shape") from exc
        if not isinstance(root, str) or not root:
            raise LanguageProjectionGap("root must be a non-empty node name", "missing_root")
        self.root = root
        graph, origins = view.graph_with_origins(graph_id)
        if not isinstance(graph, Mapping) or not isinstance(origins, Mapping):
            raise LanguageProjectionGap("graph payload is not a mapping", "unsupported_shape")
        self._graph = deepcopy(graph)
        self._origins = deepcopy(origins)
        self.effective_graph_sha256 = _digest(self._graph)
        self.view_key = list(deepcopy(view.key))
        self.base_origin = deepcopy(dict(view.base_origin))
        self._layers = {}
        for key in ("공통층", "사례층", "무관층"):
            section = self._graph.get(key)
            if not isinstance(section, Mapping):
                continue
            self._layers[key] = section
        self._edges = []
        for key in _EDGE_LISTS:
            rows = self._graph.get(key, [])
            if rows is None:
                continue
            if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
                raise LanguageProjectionGap("edge list %r is not a list" % key, "unsupported_shape")
            for row in rows:
                if (not isinstance(row, Sequence) or isinstance(row, (str, bytes))
                        or len(row) != 3 or not all(isinstance(p, str) for p in row)):
                    raise LanguageProjectionGap("malformed edge row in %r" % key, "unsupported_shape")
                self._edges.append((row[0], row[1], row[2]))
        self._out = {}
        for src, rel, dst in self._edges:
            self._out.setdefault(src, []).append((rel, dst))
        self._nodes = {}        # scoped id -> origin
        self._node_names = {}   # scoped id -> selected name
        self._edge_ids = {}     # scoped edge id -> origin
        self._edge_rows = {}    # (src, rel, dst) -> edge id
        self._node_cache = {}   # name -> detached node
        self._grammar = None
        _base = getattr(view, "base", None)
        _member = getattr(_base, "authenticated_member", None)
        self._member = _member if callable(_member) else None
        if self.op(root) != "root":
            raise LanguageProjectionGap("root %r is not op=root" % root, "missing_root")

    # ----- nodes -----
    def node(self, name):
        if not isinstance(name, str) or not name:
            raise LanguageProjectionGap("node name must be a non-empty string", "dangling_ref")
        cached = self._node_cache.get(name)
        if cached is not None:
            return deepcopy(cached)
        found = [(layer, section[name]) for layer, section in self._layers.items() if name in section]
        if not found:
            raise LanguageProjectionGap("node %r does not exist" % name, "dangling_ref")
        if len(found) > 1:
            raise LanguageProjectionGap("node %r is in several layers" % name, "duplicate_ref")
        layer, examples = found[0]
        if (not isinstance(examples, Sequence) or isinstance(examples, (str, bytes))
                or len(examples) != 1 or not isinstance(examples[0], str)):
            raise LanguageProjectionGap("node %r needs exactly one string example" % name, "unsupported_shape")
        nodes_origin = self._origins.get("nodes")
        origin = nodes_origin.get(name) if isinstance(nodes_origin, Mapping) else None
        if not isinstance(origin, Mapping):
            raise LanguageProjectionGap("node %r has no origin" % name, "missing_origin")
        try:
            scoped = _ids.node_id(self.graph_id, name)
        except TypeError as exc:
            raise LanguageProjectionGap(str(exc), "unsupported_shape") from exc
        previous = self._node_names.get(scoped)
        if previous is not None and previous != name:
            raise LanguageProjectionGap("nodes %r and %r share id %r" % (previous, name, scoped), "duplicate_ref")
        if scoped not in self._nodes and len(self._nodes) >= _MAX_NODES:
            raise LanguageProjectionGap("more than %d consumed nodes" % _MAX_NODES, "cap_overflow")
        self._nodes[scoped] = deepcopy(dict(origin))
        self._node_names[scoped] = name
        record = {"id": scoped, "name": name, "layer": layer, "examples": list(examples)}
        self._node_cache[name] = record
        return deepcopy(record)

    def scalar(self, name):
        node = self.node(name)
        if self._program_edges(name):
            raise LanguageProjectionGap("scalar leaf %r has outgoing edges" % name, "invalid_scalar")
        return self._decode(name, node["examples"][0])

    @staticmethod
    def _decode(name, text):
        if text.startswith("s="):
            return text[2:]
        if text == "b=true":
            return True
        if text == "b=false":
            return False
        if text == "n=null":
            return None
        if text.startswith("i="):
            body = text[2:]
            if not _INT_RE.fullmatch(body):
                raise LanguageProjectionGap("noncanonical integer in %r" % name, "invalid_scalar")
            try:
                return int(body)
            except ValueError as exc:
                raise LanguageProjectionGap("unconvertible integer in %r" % name, "invalid_scalar") from exc
        raise LanguageProjectionGap("unknown scalar encoding in %r" % name, "invalid_scalar")

    # ----- edges -----
    def _program_edges(self, name):
        return self._out.get(name, [])

    def _consume_edge(self, src, rel, dst):
        try:
            eid = _ids.edge_id(self.graph_id, src, rel, dst)
        except (TypeError, ValueError) as exc:
            raise LanguageProjectionGap(str(exc), "unsupported_shape") from exc
        row = (src, rel, dst)
        if eid in self._edge_ids and self._edge_rows.get(row) != eid:
            raise LanguageProjectionGap("edge id collision on %r" % (row,), "duplicate_ref")
        edges_origin = self._origins.get("edges")
        origin = edges_origin.get(eid) if isinstance(edges_origin, Mapping) else None
        if not isinstance(origin, Mapping):
            raise LanguageProjectionGap("edge %r has no origin" % (row,), "missing_origin")
        if eid not in self._edge_ids and len(self._edge_ids) >= _MAX_EDGES:
            raise LanguageProjectionGap("more than %d consumed edges" % _MAX_EDGES, "cap_overflow")
        self._edge_ids[eid] = deepcopy(dict(origin))
        self._edge_rows[row] = eid
        return eid

    def link(self, name, relation, optional=False):
        self.node(name)
        matches = [dst for rel, dst in self._program_edges(name) if rel == relation]
        if not matches:
            if optional:
                return None
            raise LanguageProjectionGap("%r lacks required %r" % (name, relation), "dangling_ref")
        if len(matches) > 1:
            code = "duplicate_ref" if len(set(matches)) < len(matches) else "ambiguous_sequence"
            raise LanguageProjectionGap("%r has several %r edges" % (name, relation), code)
        target = matches[0]
        self.node(target)
        self._consume_edge(name, relation, target)
        return target

    # ----- operations -----
    def op(self, name):
        node = self.node(name)
        if node["examples"][0] != "n=null":
            raise LanguageProjectionGap("structural node %r must be n=null" % name, "unsupported_shape")
        ops = [dst for rel, dst in self._program_edges(name) if rel == "op"]
        if len(ops) != 1:
            raise LanguageProjectionGap("%r needs exactly one op edge" % name, "unknown_op" if not ops else "duplicate_ref")
        value = self.scalar(ops[0])
        if not isinstance(value, str) or value not in _SHAPES:
            raise LanguageProjectionGap("unknown operation %r on %r" % (value, name), "unknown_op")
        self._consume_edge(name, "op", ops[0])
        if value == "sense":
            return value
        shape = _SHAPES[value]
        seen = {}
        for rel, dst in self._program_edges(name):
            if rel not in shape:
                raise LanguageProjectionGap("relation %r not allowed on op %r" % (rel, value), "unsupported_shape")
            seen.setdefault(rel, []).append(dst)
        for rel, targets in seen.items():
            if len(targets) > 1:
                code = "duplicate_ref" if len(set(targets)) < len(targets) else "ambiguous_sequence"
                raise LanguageProjectionGap("%r has several %r edges" % (name, rel), code)
        for rel, required in shape.items():
            if required and rel not in seen:
                raise LanguageProjectionGap("%r (op %s) lacks required %r" % (name, value, rel), "dangling_ref")
        for rel, required in shape.items():
            if rel != "op" and rel in seen and not (value == "relation-hypothesis" and rel == "query"):
                self.link(name, rel, optional=not required)
        return value

    def sequence(self, name, allowed_ops):
        if self.op(name) != "sequence":
            raise LanguageProjectionGap("%r is not op=sequence" % name, "unknown_op")
        allowed = frozenset(allowed_ops)
        items = []
        seen = set()
        current = self.link(name, "first", optional=True)
        while current is not None:
            if current in seen or current == name:
                raise LanguageProjectionGap("sequence %r revisits %r" % (name, current), "sequence_cycle")
            if len(items) >= _MAX_ITEMS:
                raise LanguageProjectionGap("sequence %r exceeds %d items" % (name, _MAX_ITEMS), "cap_overflow")
            item_op = self.op(current)
            if item_op not in _ITEM_OPS or item_op not in allowed:
                raise LanguageProjectionGap("item %r op %r not allowed in %r" % (current, item_op, name), "unknown_op")
            seen.add(current)
            items.append(current)
            current = self.link(current, "next", optional=True)
        return items

    # ----- capsule -----
    def capsule(self, rule=None, sense=None):
        def ref(value):
            if value is None:
                return None
            return self.node(value)["id"]
        return {
            "graph_id": self.graph_id,
            "root_id": self.node(self.root)["id"],
            "rule_id": ref(rule),
            "sense_id": ref(sense),
            "effective_graph_sha256": self.effective_graph_sha256,
            "view_key": list(self.view_key),
            "nodes": deepcopy(self._nodes),
            "edges": deepcopy(self._edge_ids),
        }


_MAX_LIST = 16
_SOURCE_KEYS = ("member_path", "member_sha256", "base_content_sha256", "base_build_id")
_SHA_RE = re.compile(r"[0-9a-f]{64}")


def _scalar_list(p, seq):
    values = []
    for item in p.sequence(seq, {"scalar"}):
        if p.op(item) != "scalar":
            raise LanguageProjectionGap("item %r is not op=scalar" % item, "unsupported_shape")
        values.append(p.scalar(p.link(item, "value")))
    return values


def _string_list(p, root, relation, check):
    values = _scalar_list(p, p.link(root, relation))
    if len(values) > _MAX_LIST:
        raise LanguageProjectionGap("%r exceeds %d entries" % (relation, _MAX_LIST), "cap_overflow")
    for value in values:
        if not isinstance(value, str):
            raise LanguageProjectionGap("%r entries must be strings" % relation, "unsupported_shape")
        check(value)
    if len(set(values)) != len(values):
        raise LanguageProjectionGap("%r has duplicate entries" % relation, "invalid_binding")
    return values


def _root_settings(p):
    root = p.root
    if p.op(root) != "root":
        raise LanguageProjectionGap("root %r is not op=root" % root, "unsupported_shape")
    head = p.scalar(p.link(root, "head-pattern"))
    ignore_case = p.scalar(p.link(root, "ignore-case"))
    if not isinstance(head, str) or not head.strip():
        raise LanguageProjectionGap("head-pattern must be a nonblank string", "unsupported_shape")
    if len(head) > 128:
        raise LanguageProjectionGap("head-pattern exceeds 128 characters", "cap_overflow")
    if type(ignore_case) is not bool:
        raise LanguageProjectionGap("ignore-case must be a bool", "unsupported_shape")
    try:
        compiled = re.compile(head, re.IGNORECASE if ignore_case else 0)
    except re.error as exc:
        raise LanguageProjectionGap("head-pattern is not a valid regex", "unsupported_shape") from exc
    if compiled.fullmatch(""):
        raise LanguageProjectionGap("head-pattern matches the empty string", "unsupported_shape")

    def punctuation(value):
        if len(value) != 1 or value.isspace() or value.isalnum():
            raise LanguageProjectionGap("punctuation must be one nonwhitespace, nonalphanumeric character", "unsupported_shape")

    def operator(value):
        if not value.strip() or value != value.strip():
            raise LanguageProjectionGap("operators must be nonblank and trimmed", "unsupported_shape")

    separators = _string_list(p, root, "separators", punctuation)
    terminators = _string_list(p, root, "terminators", punctuation)
    operators = _string_list(p, root, "operators", operator)
    if set(separators) & set(terminators):
        raise LanguageProjectionGap("separators and terminators overlap", "invalid_binding")
    settings = {"head_pattern": head, "ignore_case": ignore_case, "separators": separators,
                "terminators": terminators, "operators": operators}
    grammar = _read_grammar(p)
    p._grammar = grammar
    if grammar is not None:
        settings["grammar"] = grammar
    return settings


def _source_descriptor(p, source):
    if source is None:
        return {"status": "unavailable"}
    if not isinstance(source, Mapping):
        raise LanguageProjectionGap("source descriptor must be a mapping", "invalid_source_descriptor")
    fields = {}
    for key, value in source.items():
        if key not in _SOURCE_KEYS:
            raise LanguageProjectionGap("unknown source descriptor key %r" % (key,), "invalid_source_descriptor")
        if value is not None:
            if key in ("member_sha256", "base_content_sha256"):
                if not isinstance(value, str) or not _SHA_RE.fullmatch(value):
                    raise LanguageProjectionGap("%s must be a lowercase sha256" % key, "invalid_source_descriptor")
            elif not isinstance(value, str):
                raise LanguageProjectionGap("%s must be a string" % key, "invalid_source_descriptor")
        fields[key] = value
    build = fields.get("base_build_id")
    if build is not None and build != p.base_origin.get("build_id"):
        raise LanguageProjectionGap("base_build_id does not match the pinned base", "source_identity_mismatch")
    return deepcopy({"status": "caller_supplied", **fields})


def _role_projection(p, role_name):
    if p.op(role_name) != "role":
        raise LanguageProjectionGap("%r is not op=role" % role_name, "unsupported_shape")
    node = p.node(role_name)
    slot = p.scalar(p.link(role_name, "name"))
    seed = p.scalar(p.link(role_name, "seed"))
    mode = p.scalar(p.link(role_name, "mode"))
    markers = _scalar_list(p, p.link(role_name, "markers"))
    side_name = p.link(role_name, "side", optional=True)
    side = p.scalar(side_name) if side_name is not None else None
    if not isinstance(slot, str) or not slot.strip() or not slot.isidentifier():
        raise LanguageProjectionGap("role slot must be an identifier", "invalid_binding")
    if not isinstance(seed, str) or not seed:
        raise LanguageProjectionGap("role seed must be a nonempty string", "unsupported_shape")
    if mode not in ("prefix", "suffix", "bare") or not isinstance(mode, str):
        raise LanguageProjectionGap("role mode must be prefix, suffix or bare", "unsupported_shape")
    if len(markers) > _MAX_LIST:
        raise LanguageProjectionGap("role markers exceed %d entries" % _MAX_LIST, "cap_overflow")
    for marker in markers:
        if not isinstance(marker, str) or not marker:
            raise LanguageProjectionGap("role markers must be nonempty strings", "unsupported_shape")
    if len(set(markers)) != len(markers):
        raise LanguageProjectionGap("role markers repeat", "invalid_binding")
    if mode == "bare":
        if markers:
            raise LanguageProjectionGap("bare role takes no markers", "invalid_binding")
        if side not in ("before", "after") or not isinstance(side, str):
            raise LanguageProjectionGap("bare role needs side before/after", "invalid_binding")
        role = {"slot": slot, "prefixes": [], "suffixes": [], "bare_side": side}
    else:
        if not markers or side_name is not None:
            raise LanguageProjectionGap("%s role needs markers and no side" % mode, "invalid_binding")
        for marker in markers:
            if mode == "prefix" and (not marker.strip() or marker != marker.strip()):
                raise LanguageProjectionGap("prefix markers must be nonblank and trimmed", "invalid_binding")
            if mode == "suffix" and any(ch.isspace() for ch in marker):
                raise LanguageProjectionGap("suffix markers must not contain whitespace", "invalid_binding")
        role = {"slot": slot, "prefixes": list(markers) if mode == "prefix" else [],
                "suffixes": list(markers) if mode == "suffix" else [], "bare_side": None}
    return {"node_id": node["id"], "name": node["name"], "slot": slot, "seed": seed, "role": role}


def _rule_binds(p, binds):
    refs = p.sequence(binds, {"role-ref"})
    if len(refs) not in (2, 3):
        raise LanguageProjectionGap("binds needs exactly 2 or 3 roles", "invalid_binding")
    roles = {}
    for ref in refs:
        target = p.link(ref, "target")
        if target in roles:
            raise LanguageProjectionGap("role %r bound twice" % target, "invalid_binding")
        roles[target] = _role_projection(p, target)
    projected = list(roles.values())
    if len({r["node_id"] for r in projected}) != len(projected):
        raise LanguageProjectionGap("bound role ids repeat", "invalid_binding")
    if len({r["slot"] for r in projected}) != len(projected):
        raise LanguageProjectionGap("bound role slots repeat", "invalid_binding")
    owners = set()
    for r in projected:
        for marker in r["role"]["prefixes"] + r["role"]["suffixes"]:
            if marker in owners:
                raise LanguageProjectionGap("marker %r has several owners" % marker, "invalid_binding")
            owners.add(marker)
    bare = [r for r in projected if r["role"]["bare_side"] is not None]
    sides = [r["role"]["bare_side"] for r in bare]
    if len(projected) == 2:
        if len(bare) == 2 and sides[0] == sides[1]:
            raise LanguageProjectionGap("bare sides must differ", "invalid_binding")
    else:
        if sides.count("before") > 1 or sides.count("after") > 2:
            raise LanguageProjectionGap("too many bare roles on one side", "invalid_binding")
    return roles


def _rule_reads(p, reads, roles):
    items = p.sequence(reads, {"literal", "slot", "predicate"})
    if not items:
        raise LanguageProjectionGap("reads must not be empty", "invalid_binding")
    text = ""
    spans = {}
    predicate = None
    used = set()
    for item in items:
        kind = p.op(item)
        if kind == "slot":
            target = p.link(item, "role")
            if target not in roles:
                raise LanguageProjectionGap("slot refers to unbound role %r" % target, "invalid_binding")
            if target in used:
                raise LanguageProjectionGap("role %r read twice" % target, "invalid_binding")
            used.add(target)
            seed = roles[target]["seed"]
            spans[target] = (len(text), len(text) + len(seed))
            text += seed
            continue
        value = p.scalar(p.link(item, "value"))
        if not isinstance(value, str) or (kind == "predicate" and not value):
            raise LanguageProjectionGap("%s value must be a string" % kind, "unsupported_shape")
        if kind == "predicate":
            if predicate is not None:
                raise LanguageProjectionGap("reads has several predicates", "invalid_binding")
            predicate = (len(text), len(text) + len(value))
        text += value
    if predicate is None:
        raise LanguageProjectionGap("reads lacks a predicate", "invalid_binding")
    if used != set(roles):
        raise LanguageProjectionGap("every bound role must be read once", "invalid_binding")
    if not text:
        raise LanguageProjectionGap("reads text is empty", "invalid_binding")
    if len(text) > 512 or len(text.split()) > 40:
        raise LanguageProjectionGap("reads text exceeds caps", "cap_overflow")
    seeds = [r["seed"] for r in roles.values()]
    if len(set(seeds)) != len(seeds):
        raise LanguageProjectionGap("role seeds repeat", "invalid_binding")
    for name, r in roles.items():
        seed = r["seed"]
        starts = []
        at = text.find(seed)
        while at >= 0:
            starts.append(at)
            at = text.find(seed, at + 1)
        if starts != [spans[name][0]]:
            raise LanguageProjectionGap("seed of %r must occur exactly once" % name, "invalid_binding")
    ordered = sorted(spans.values())
    for left, right in zip(ordered, ordered[1:]):
        if left[1] > right[0]:
            raise LanguageProjectionGap("seed spans overlap", "invalid_binding")
    for start, end in ordered:
        if start < predicate[1] and predicate[0] < end:
            raise LanguageProjectionGap("predicate overlaps a slot", "invalid_binding")
    slots = {r["slot"]: r["seed"] for r in roles.values()}
    return text, slots, [predicate[0], predicate[1]]


def _rule_meaning(p, emits, roles):
    if p.op(emits) != "meaning":
        raise LanguageProjectionGap("emits is not op=meaning", "unsupported_shape")
    subjects = [p.link(ref, "target") for ref in p.sequence(p.link(emits, "subjects"), {"role-ref"})]
    sense_name = p.link(emits, "relation")
    sense = p.node(sense_name)
    if sense["layer"] != "공통층" or p.op(sense_name) != "sense":
        raise LanguageProjectionGap("relation must be a common-layer sense", "unsupported_shape")
    if not sense["name"] or sense["name"].startswith("$"):
        raise LanguageProjectionGap("sense name is not usable", "unsupported_shape")
    obj = p.link(emits, "object")
    if p.op(obj) != "role":
        raise LanguageProjectionGap("meaning object must be op=role", "unsupported_shape")
    meaning = {}
    polarity_name = p.link(emits, "polarity", optional=True)
    if polarity_name is not None:
        polarity = p.scalar(polarity_name)
        if type(polarity) is not bool:
            raise LanguageProjectionGap("polarity must be a bool", "unsupported_shape")
        meaning["polarity"] = polarity
    modality_name = p.link(emits, "modality", optional=True)
    if modality_name is not None:
        modality = p.scalar(modality_name)
        if not isinstance(modality, str) or modality not in ("asserted", "planned", "conditional"):
            raise LanguageProjectionGap("modality is not allowed", "unsupported_shape")
        meaning["modality"] = modality
    for target in subjects + [obj]:
        if target not in roles:
            raise LanguageProjectionGap("meaning refers to unbound role %r" % target, "invalid_binding")
    members = subjects + [obj]
    if len(set(members)) != len(members) or set(members) != set(roles):
        raise LanguageProjectionGap("every bound role must appear once in meaning", "invalid_binding")
    if len(subjects) != len(roles) - 1:
        raise LanguageProjectionGap("subject count does not fit the bound roles", "unsupported_shape")
    slot = lambda name: "$" + roles[name]["slot"]
    if len(roles) == 2:
        left = slot(subjects[0])
    else:
        decimal = [n for n, r in roles.items() if r["seed"].isdecimal()]
        if decimal != [obj]:
            raise LanguageProjectionGap("exactly the object must have a decimal seed", "invalid_binding")
        left = [slot(subjects[0]), slot(subjects[1])]
        after = [r for r in roles.values() if r["role"]["bare_side"] == "after"]
        if len(after) == 2 and sum(1 for r in after if r["seed"].isdecimal()) != 1:
            raise LanguageProjectionGap("two after roles need one scalar and one reference", "invalid_binding")
    meaning = {"triple": [left, sense["name"], slot(obj)], **meaning}
    return meaning, sense_name


def _rule_output(p, realizes, roles):
    components = []
    for item in p.sequence(realizes, {"literal", "slot", "predicate"}):
        kind = p.op(item)
        node_id = p.node(item)["id"]
        if kind == "slot":
            target = p.link(item, "role")
            if target not in roles:
                raise LanguageProjectionGap("output slot refers to unbound role %r" % target, "invalid_binding")
            components.append({"id": node_id, "op": kind, "role_id": roles[target]["node_id"],
                               "slot": roles[target]["slot"]})
            continue
        value = p.scalar(p.link(item, "value"))
        if not isinstance(value, str) or (kind == "predicate" and not value):
            raise LanguageProjectionGap("%s value must be a string" % kind, "unsupported_shape")
        components.append({"id": node_id, "op": kind, "value": value})
    return p.node(realizes)["id"], components


def _grammar_gap(code="invalid_grammar"):
    return LanguageProjectionGap("selected grammar is not usable", code)


def _grammar_pairs(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise _grammar_gap()
        out[key] = value
    return out


def _grammar_refuse(_):
    raise _grammar_gap()


def _grammar_walk(value, depth, count):
    count[0] += 1
    if depth > 12 or count[0] > 4096:
        raise _grammar_gap("cap_overflow")
    if isinstance(value, str):
        if len(value) > 256:
            raise _grammar_gap("cap_overflow")
    elif isinstance(value, dict):
        for key, item in value.items():
            _grammar_walk(key, depth + 1, count)
            _grammar_walk(item, depth + 1, count)
    elif isinstance(value, list):
        for item in value:
            _grammar_walk(item, depth + 1, count)
    elif value is None or type(value) in (bool, int):
        pass
    else:
        raise _grammar_gap()


def _gtext(value, high, spaces=False):
    if (not isinstance(value, str) or not value or len(value) > high or value != value.strip()
            or (not spaces and any(ch.isspace() for ch in value))):
        raise _grammar_gap()
    return value


def _gdict(value, required, optional=()):
    if not isinstance(value, dict):
        raise _grammar_gap()
    keys = set(value)
    if not set(required) <= keys or keys - set(required) - set(optional):
        raise _grammar_gap()
    return value


def _glist(value, low, high):
    if not isinstance(value, list) or not low <= len(value) <= high:
        raise _grammar_gap()
    return value


def _gchar(value, alphabet):
    if not isinstance(value, str) or len(value) != 1 or value == " " or value not in alphabet:
        raise _grammar_gap()
    return value


def _gunique(items):
    if len(set(items)) != len(items):
        raise _grammar_gap()


def _normalize_grammar(doc):
    from marco.language import hangul as _h
    codas = _h._CODAS[1:]
    v2 = isinstance(doc, dict) and doc.get("schema") == "selected-scoped-grammar-v2"
    if v2:
        doc = _gdict(doc, ("schema", "language_pack", "semantic_capabilities"))
    else:
        doc = _gdict(doc, ("schema", "language_pack"))
        if doc["schema"] != "selected-positive-grammar-v1":
            raise _grammar_gap()
    pack = _gdict(doc["language_pack"], ("inflection", "case_particles"),
                  ("slot_particles", "negation", "clauses") if v2 else ("slot_particles",))
    infl = _gdict(pack["inflection"],
                  ("id", "kinds", "max_forms", "tenses", "endings", "parsing_endings",
                   "question_endings"),
                  ("vowel_join", "condition_endings", "boundary_endings") if v2 else ("vowel_join",))
    _gtext(infl["id"], 64)
    kinds = _glist(infl["kinds"], 1, 8)
    for kind in kinds:
        _gtext(kind, 32)
    _gunique(kinds)
    max_forms = infl["max_forms"]
    if type(max_forms) is not int or not 1 <= max_forms <= 8:
        raise _grammar_gap()
    if infl["tenses"] != {"present": []}:
        raise _grammar_gap()
    endings = infl["endings"]
    if not isinstance(endings, dict) or not 1 <= len(endings) <= 16:
        raise _grammar_gap()
    uses_vowel = False
    for key, rules in endings.items():
        _gtext(key, 32)
        rules = _glist(rules, 1, 8)
        whens, open_count = [], 0
        for position, rule in enumerate(rules):
            rule = _gdict(rule, ("steps",), ("when",))
            if "when" in rule:
                when = rule["when"]
                if not isinstance(when, dict) or not when or set(when) - {"kind", "tense"}:
                    raise _grammar_gap()
                if "kind" in when and (not isinstance(when["kind"], str) or when["kind"] not in kinds):
                    raise _grammar_gap()
                if "tense" in when and when["tense"] != "present":
                    raise _grammar_gap()
                tag = _digest(when)
                if tag in whens:
                    raise _grammar_gap()
                whens.append(tag)
            else:
                if position != len(rules) - 1:
                    raise _grammar_gap()
                open_count += 1
            for step in _glist(rule["steps"], 1, 4):
                if not isinstance(step, dict):
                    raise _grammar_gap()
                op = step.get("op")
                if op == "append":
                    _gdict(step, ("op", "text"))
                    _gtext(step["text"], 32)
                elif op == "vowel":
                    _gdict(step, ("op",))
                    uses_vowel = True
                elif op == "coda_suffix":
                    _gdict(step, ("op", "coda", "open", "closed", "drop_codas"))
                    if step["coda"] != "":
                        _gchar(step["coda"], codas)
                    _gtext(step["open"], 32)
                    _gtext(step["closed"], 32)
                    drops = _glist(step["drop_codas"], 0, 8)
                    for drop in drops:
                        _gchar(drop, codas)
                    _gunique(drops)
                else:
                    raise _grammar_gap()
        if open_count != 1:
            raise _grammar_gap()
    if uses_vowel != ("vowel_join" in infl):
        raise _grammar_gap()
    if "vowel_join" in infl:
        join = _gdict(infl["vowel_join"], ("onset", "bright_vowels", "bright", "dark"))
        _gchar(join["onset"], _h._ONSETS)
        _gchar(join["bright"], _h._NUCLEI)
        _gchar(join["dark"], _h._NUCLEI)
        bright = _glist(join["bright_vowels"], 1, 21)
        for vowel in bright:
            _gchar(vowel, _h._NUCLEI)
        _gunique(bright)
    for key in ("parsing_endings", "question_endings"):
        names = _glist(infl[key], 1, 16)
        for name in names:
            if not isinstance(name, str) or name not in endings:
                raise _grammar_gap()
        _gunique(names)
    case = _glist(pack["case_particles"], 0, 64)
    for particle in case:
        _gtext(particle, 16)
    _gunique(case)
    normalized = {"inflection": deepcopy(infl),
                  "case_particles": sorted(case, key=len, reverse=True)}
    if "slot_particles" in pack:
        seen, groups = set(), []
        for group in _glist(pack["slot_particles"], 0, 16):
            group = _glist(group, 2, 16)
            for particle in group:
                _gtext(particle, 16)
                if particle in seen:
                    raise _grammar_gap()
                seen.add(particle)
            groups.append(sorted(group, key=len, reverse=True))
        normalized["slot_particles"] = groups
    if v2:
        caps = _gdict(doc["semantic_capabilities"], (), ("negative_binary", "conditional_binary"))
        if not caps:
            raise _grammar_gap()
        has_neg = "negative_binary" in caps
        has_cond = "conditional_binary" in caps
        if (has_neg != ("negation" in pack) or has_cond != ("condition_endings" in infl)
                or has_cond != ("boundary_endings" in infl)
                or ("clauses" in pack and not has_cond)):
            raise _grammar_gap()
        for key in ("condition_endings", "boundary_endings"):
            if key in infl:
                names = _glist(infl[key], 1, 16)
                for name in names:
                    if not isinstance(name, str) or name not in endings:
                        raise _grammar_gap()
                _gunique(names)
        if has_neg:
            neg = _gdict(pack["negation"], ("연결", "어간", "갈래"))
            _gtext(neg["연결"], 16)
            _gtext(neg["어간"], 32)
            if not isinstance(neg["갈래"], str) or neg["갈래"] not in kinds:
                raise _grammar_gap()
            normalized["negation"] = deepcopy(neg)
        if "clauses" in pack:
            clauses = _gdict(pack["clauses"], ("candidate_suffixes",))
            suffixes = _glist(clauses["candidate_suffixes"], 1, 16)
            for suffix in suffixes:
                _gtext(suffix, 16)
            _gunique(suffixes)
            normalized["clauses"] = deepcopy(clauses)
        if has_neg:
            cap = _gdict(caps["negative_binary"], ("frame_indices", "query_ordinals"))
            frames_ = _glist(cap["frame_indices"], 1, 16)
            for i in frames_:
                if type(i) is not int or i < 0:
                    raise _grammar_gap()
            _gunique(frames_)
            ords = _glist(cap["query_ordinals"], 0, 2)
            for i in ords:
                if type(i) is not int or not 0 <= i <= 7:
                    raise _grammar_gap()
            _gunique(ords)
        if has_cond:
            cap = _gdict(caps["conditional_binary"], ("frame_indices",))
            frames_ = _glist(cap["frame_indices"], 1, 16)
            for i in frames_:
                if type(i) is not int or i < 0:
                    raise _grammar_gap()
            _gunique(frames_)
        normalized["semantic_capabilities"] = deepcopy(caps)
    return normalized


def _read_grammar(p):
    ref = p.link(p.root, "grammar-ref", optional=True)
    if ref is None:
        return None
    if p.op(ref) != "grammar-ref":
        raise LanguageProjectionGap("grammar-ref is not op=grammar-ref", "unsupported_shape")
    path = p.scalar(p.link(ref, "member-path"))
    sha = p.scalar(p.link(ref, "sha256"))
    schema = p.scalar(p.link(ref, "schema"))
    if (not isinstance(path, str) or not path or not isinstance(sha, str)
            or not _SHA_RE.fullmatch(sha)
            or schema not in ("selected-positive-grammar-v1", "selected-scoped-grammar-v2")):
        raise _grammar_gap("unsupported_shape")
    member = p._member
    if member is None:
        raise _grammar_gap("grammar_unavailable")
    try:
        data = member(path, sha, 65536)
    except LanguageProjectionGap:
        raise
    except Exception as exc:
        raise _grammar_gap("grammar_unavailable") from exc
    if type(data) is not bytes or len(data) > 65536 or hashlib.sha256(data).hexdigest() != sha:
        raise _grammar_gap("source_identity_mismatch")
    try:
        doc = json.loads(data.decode("utf-8"), object_pairs_hook=_grammar_pairs,
                         parse_constant=_grammar_refuse)
    except LanguageProjectionGap:
        raise
    except (UnicodeDecodeError, ValueError, RecursionError) as exc:
        raise _grammar_gap() from exc
    _grammar_walk(doc, 1, [0])
    if not isinstance(doc, dict) or doc.get("schema") != schema:
        raise _grammar_gap()
    pack = _normalize_grammar(doc)
    caps = pack.pop("semantic_capabilities", None)
    result = {"reference": {"member_path": path, "sha256": sha, "schema": schema},
              "language_pack": pack}
    if caps is not None:
        result["semantic_capabilities"] = caps
    return result


def _inflection_annotation(p, name, key, text, slots, predicate_span):
    if p.op(name) != "inflection-ref":
        raise LanguageProjectionGap("%r is not op=inflection-ref" % name, "unsupported_shape")
    grammar = p._grammar
    if grammar is None:
        raise LanguageProjectionGap("inflection-ref requires a selected grammar", "unsupported_inflection")
    infl = grammar["language_pack"]["inflection"]
    stem = p.scalar(p.link(name, "stem"))
    tense = p.scalar(p.link(name, "tense"))
    ending = p.scalar(p.link(name, "ending"))
    kind = p.scalar(p.link(name, "kind"))
    names = _scalar_list(p, p.link(name, "endings"))
    if (not isinstance(stem, str) or not 1 <= len(stem) <= 64
            or any(not "가" <= ch <= "힣" for ch in stem)):
        raise LanguageProjectionGap("inflection stem must be 1..64 Hangul syllables", "unsupported_inflection")
    if tense != "present":
        raise LanguageProjectionGap("inflection tense must be present", "unsupported_inflection")
    if not isinstance(ending, str) or ending not in infl["endings"]:
        raise LanguageProjectionGap("inflection ending is not declared", "unsupported_inflection")
    if not isinstance(kind, str) or kind not in infl["kinds"]:
        raise LanguageProjectionGap("inflection kind is not declared", "unsupported_inflection")
    allowed = infl[key]
    if (not 1 <= len(names) <= 16 or len(set(names)) != len(names)
            or any(not isinstance(n, str) or n not in allowed for n in names)
            or ending not in names):
        raise LanguageProjectionGap("inflection endings are not a valid selected subset", "unsupported_inflection")
    from marco.language.hangul import inflect
    try:
        forms = inflect(stem, tense, ending, infl, kind=kind)
    except ValueError as exc:
        raise LanguageProjectionGap("inflection annotation cannot be realized", "unsupported_inflection") from exc
    if (not isinstance(predicate_span, (list, tuple)) or len(predicate_span) != 2
            or any(type(v) is not int for v in predicate_span)):
        raise LanguageProjectionGap("inflection predicate span is invalid", "unsupported_inflection")
    pred_start, pred_end = predicate_span
    if not 0 <= pred_start < pred_end == len(text):
        raise LanguageProjectionGap("inflection predicate span must end the text", "unsupported_inflection")
    slot_end = max((text.index(v) + len(v) for v in slots.values()), default=0)
    floor = max(slot_end, pred_start)
    matches = {f["text"] for f in forms
               if text.endswith(f["text"]) and len(text) - len(f["text"]) >= floor}
    if len(matches) != 1:
        raise LanguageProjectionGap("inflection does not match the literal predicate tail", "unsupported_inflection")
    return {"stem": stem, "tense": tense, "ending": ending, "kind": kind, "endings": list(names)}


def _rule_projection(p, rule_name, index):
    if type(index) is not int or not 0 <= index < _MAX_LIST:
        raise LanguageProjectionGap("rule index must be an int in [0, %d)" % _MAX_LIST, "cap_overflow")
    if p.op(rule_name) != "rule":
        raise LanguageProjectionGap("%r is not op=rule" % rule_name, "unsupported_shape")
    reads = p.link(rule_name, "reads")
    binds = p.link(rule_name, "binds")
    emits = p.link(rule_name, "emits")
    endings = p.link(rule_name, "allowed-endings")
    realizes = p.link(rule_name, "realizes", optional=True)
    allowed = _scalar_list(p, endings)
    inflection_name = p.link(rule_name, "inflection-ref", optional=True)
    if inflection_name is None and allowed:
        raise LanguageProjectionGap("allowed-endings must be empty", "unsupported_inflection")
    roles = _rule_binds(p, binds)
    text, slots, span = _rule_reads(p, reads, roles)
    meaning, sense_name = _rule_meaning(p, emits, roles)
    output = None
    if realizes is not None:
        sequence_id, components = _rule_output(p, realizes, roles)
    annotation = {"text": text, "slots": slots, "meaning": meaning}
    if inflection_name is not None:
        annotation["inflection"] = _inflection_annotation(p, inflection_name, "parsing_endings", text, slots, span)
        if list(allowed) != annotation["inflection"]["endings"]:
            raise LanguageProjectionGap("allowed-endings must equal the inflection endings", "unsupported_inflection")
    graph_source = p.capsule(rule_name, sense_name)
    if realizes is not None:
        output = {"rule_id": graph_source["rule_id"], "sense_id": graph_source["sense_id"],
                  "sequence_id": sequence_id, "components": components,
                  "graph_source": deepcopy(graph_source)}
    frame = {"id": graph_source["rule_id"],
             "source_ref": {"index": index, "annotation_sha256": _digest(annotation),
                            "graph_source": deepcopy(graph_source)},
             "predicate_span": span,
             "roles": [deepcopy(r["role"]) for r in roles.values()],
             "allowed_endings": list(allowed)}
    return deepcopy({"annotation": annotation, "frame": frame, "output": output})


def _read_rule_targets(p):
    settings = _root_settings(p)
    items = p.sequence(p.link(p.root, "rules"), {"rule-ref"})
    if not items:
        raise LanguageProjectionGap("root rules must not be empty", "invalid_binding")
    if len(items) > _MAX_LIST:
        raise LanguageProjectionGap("root rules exceed %d entries" % _MAX_LIST, "cap_overflow")
    targets = [p.link(item, "target") for item in items]
    ids = [p.node(target)["id"] for target in targets]
    if len(set(targets)) != len(targets) or len(set(ids)) != len(ids):
        raise LanguageProjectionGap("root rules repeat a target", "duplicate_ref")
    return settings, targets


def _same_reader_identity(first, other):
    same = (first.graph_id == other.graph_id
            and first.node(first.root)["id"] == other.node(other.root)["id"]
            and first.effective_graph_sha256 == other.effective_graph_sha256
            and first.view_key == other.view_key
            and first.base_origin == other.base_origin)
    if not same:
        raise LanguageProjectionGap("rule readers disagree on the pinned source", "source_identity_mismatch")


def _merge_reader(p, nodes, edges, names, rows):
    for scoped, name in p._node_names.items():
        if names.setdefault(scoped, name) != name:
            raise LanguageProjectionGap("scoped id %r maps to several nodes" % scoped, "duplicate_ref")
    for row, eid in p._edge_rows.items():
        if rows.setdefault(eid, row) != row:
            raise LanguageProjectionGap("scoped edge id %r maps to several rows" % eid, "duplicate_ref")
    for target, source, cap in ((nodes, p._nodes, _MAX_NODES), (edges, p._edge_ids, _MAX_EDGES)):
        for key, origin in source.items():
            if key in target:
                if target[key] != origin:
                    raise LanguageProjectionGap("origin of %r differs between readers" % key,
                                                "source_identity_mismatch")
                continue
            if len(target) >= cap:
                raise LanguageProjectionGap("more than %d merged entries" % cap, "cap_overflow")
            target[key] = deepcopy(origin)


def project_predicate_frames(view, graph_id, root, *, source=None):
    """Project the root's ordered rules into detached predicate-frame data."""
    first = _Program(view, graph_id, root)
    settings, targets = _read_rule_targets(first)
    nodes, edges, names, rows = {}, {}, {}, {}
    _merge_reader(first, nodes, edges, names, rows)
    examples, frames, output_rules = [], [], []
    for index, target in enumerate(targets):
        p = _Program(view, graph_id, root)
        _same_reader_identity(first, p)
        again, again_targets = _read_rule_targets(p)
        if again != settings or again_targets != targets:
            raise LanguageProjectionGap("root changed between readers", "source_identity_mismatch")
        projected = _rule_projection(p, target, index)
        _merge_reader(p, nodes, edges, names, rows)
        examples.append(projected["annotation"])
        frames.append(projected["frame"])
        if projected["output"] is not None:
            output_rules.append(projected["output"])
    seed_sha256 = _digest(examples)
    provenance = {"graph_id": first.graph_id, "root_id": first.node(first.root)["id"],
                  "effective_graph_sha256": first.effective_graph_sha256,
                  "view_key": list(first.view_key), "base_origin": deepcopy(first.base_origin),
                  "source": _source_descriptor(first, source), "nodes": nodes, "edges": edges}
    return deepcopy({
        "schema": "graph-predicate-projection-v1",
        "data": {
            "schema": "annotated-relations-v1", "examples": examples,
            "ignore_case": settings["ignore_case"], "numerals": {},
            "predicate_frames": {
                "schema": "predicate-frames-v2", "seed_count": len(examples),
                "seed_sha256": seed_sha256, "head_pattern": settings["head_pattern"],
                "separators": settings["separators"], "terminators": settings["terminators"],
                "operators": settings["operators"], "frames": frames},
        },
        "language_pack": (deepcopy(settings["grammar"]["language_pack"]) if "grammar" in settings else {}),
        "output_rules": output_rules, "provenance": provenance,
        "fingerprint": _digest({"schema": "graph-predicate-projection-v1",
                                "provenance": provenance, "seed_sha256": seed_sha256,
                                **({"grammar": settings["grammar"]} if "grammar" in settings else {})}),
    })


def _ref_targets(p, relation, op_name):
    seq = p.link(p.root, relation, optional=True)
    if seq is None:
        return []
    items = p.sequence(seq, {op_name})
    if len(items) > _MAX_LIST:
        raise LanguageProjectionGap("root %s exceed %d entries" % (relation, _MAX_LIST), "cap_overflow")
    targets = [p.link(item, "target") for item in items]
    ids = [p.node(target)["id"] for target in targets]
    if len(set(targets)) != len(targets) or len(set(ids)) != len(ids):
        raise LanguageProjectionGap("root %s repeat a target" % relation, "duplicate_ref")
    return targets


def _read_dialogue_targets(p):
    settings, rules = _read_rule_targets(p)
    queries = _ref_targets(p, "queries", "query-ref")
    replies = _ref_targets(p, "replies", "reply-ref")
    marks = []
    seq = p.link(p.root, "question-marks", optional=True)
    if seq is not None:
        marks = _scalar_list(p, seq)
        if len(marks) > _MAX_LIST:
            raise LanguageProjectionGap("question-marks exceed %d entries" % _MAX_LIST, "cap_overflow")
        for mark in marks:
            if (not isinstance(mark, str) or len(mark) != 1 or mark.isspace() or mark.isalnum()):
                raise LanguageProjectionGap("question mark must be one nonspace, nonalphanumeric character",
                                            "unsupported_shape")
        if len(set(marks)) != len(marks):
            raise LanguageProjectionGap("question-marks repeat", "invalid_binding")
        if set(marks) & (set(settings["separators"]) | set(settings["terminators"])):
            raise LanguageProjectionGap("question-marks overlap separators or terminators", "invalid_binding")
    if queries and not marks:
        raise LanguageProjectionGap("queries need nonempty question-marks", "invalid_binding")
    hypotheses = _read_hypothesis_targets(p, rules)
    controls = None
    if p.link(p.root, "learning-controls", optional=True) is not None:
        controls = _ref_targets(p, "learning-controls", "learning-control-ref")
        if not controls:
            raise LanguageProjectionGap("learning-controls must declare at least one control", "invalid_binding")
    continuation = p.link(p.root, "unread-continuation", optional=True)
    fact_batch = p.link(p.root, "fact-batch", optional=True)
    return {"settings": settings, "rules": rules, "queries": queries, "replies": replies, "marks": marks,
            "hypotheses": hypotheses, "controls": controls, "continuation": continuation,
            "fact_batch": fact_batch}


def _read_hypothesis_targets(p, rules):
    """None when the root declares no hypotheses link, else the ordered policy target names.

    Routing only: reads root/sequence/reference nodes, never policy op/frame/capture bodies.
    """
    if p.link(p.root, "hypotheses", optional=True) is None:
        return None
    return _ref_targets(p, "hypotheses", "hypothesis-ref")


def _hypothesis_eligible(annotation):
    slots = annotation.get("slots")
    meaning = annotation.get("meaning")
    if not isinstance(slots, dict) or len(slots) != 2 or not isinstance(meaning, dict):
        raise LanguageProjectionGap("hypothesis frame must have exactly two slots", "invalid_binding")
    triple = meaning.get("triple")
    if (not isinstance(triple, list) or len(triple) != 3 or not isinstance(triple[0], str)
            or not isinstance(triple[1], str) or not isinstance(triple[2], str)):
        raise LanguageProjectionGap("hypothesis frame must be a flat binary triple", "invalid_binding")
    refs = {"$" + slot for slot in slots}
    if triple[0] == triple[2] or {triple[0], triple[2]} != refs:
        raise LanguageProjectionGap("hypothesis triple must use the two distinct roles", "invalid_binding")
    if any(not isinstance(seed, str) or seed.isdecimal() for seed in slots.values()):
        raise LanguageProjectionGap("hypothesis role seeds must be nondecimal", "invalid_binding")
    if meaning.get("polarity", True) is not True or meaning.get("modality", "asserted") != "asserted":
        raise LanguageProjectionGap("hypothesis frame must be positive and asserted", "invalid_binding")
    if set(meaning) - {"triple", "polarity", "modality"}:
        raise LanguageProjectionGap("hypothesis frame meaning is not eligible", "invalid_binding")


def _hypothesis_projection(p, policy, rules, index, facts, frames):
    if p.op(policy) != "relation-hypothesis":
        raise LanguageProjectionGap("%r is not op=relation-hypothesis" % policy, "unsupported_shape")
    frame = p.link(policy, "frame")
    capture = p.scalar(p.link(policy, "capture"))
    if frame not in rules:
        raise LanguageProjectionGap("hypothesis frame %r is not a selected root rule" % frame,
                                    "invalid_binding")
    if not isinstance(capture, str) or capture not in ("single-word", "contiguous-words"):
        raise LanguageProjectionGap("unknown hypothesis capture", "invalid_binding")
    frame_index = rules.index(frame)
    projected = _rule_projection(p, frame, frame_index)
    if projected["annotation"] != facts[frame_index]:
        raise LanguageProjectionGap("hypothesis frame differs from its fact", "source_identity_mismatch")
    _hypothesis_eligible(projected["annotation"])
    bound = _rule_binds(p, p.link(frame, "binds"))
    _, sense_name = _rule_meaning(p, p.link(frame, "emits"), bound)
    return {"index": index, "frame_index": frame_index, "capture": capture,
            "source_ref": deepcopy(frames[frame_index]["source_ref"]),
            "policy_source": p.capsule(policy, sense_name)}


def _query_projection_coordinates(p, query, known_name, annotation):
    """Predicate and known-slot spans of a query body already validated by _query_projection."""
    known = _role_projection(p, known_name)
    terminal = p.scalar(p.link(query, "terminal"))
    text, predicate, slot = "", None, None
    for item in p.sequence(p.link(query, "reads"), {"literal", "slot", "predicate"}):
        kind = p.op(item)
        if kind == "slot":
            slot = [len(text), len(text) + len(known["seed"])]
            text += known["seed"]
            continue
        value = p.scalar(p.link(item, "value"))
        if kind == "predicate":
            predicate = {"text": value, "span": [len(text), len(text) + len(value)]}
        text += value
    if (predicate is None or slot is None or text != annotation["text"]
            or {known["slot"]: known["seed"]} != annotation["slots"]):
        raise LanguageProjectionGap("query coordinates differ from the compiled query", "source_identity_mismatch")
    if len(text) > 512 or len(text.split()) > 40:
        raise LanguageProjectionGap("query reads text exceeds caps", "cap_overflow")
    if not isinstance(terminal, str) or terminal in text:
        raise LanguageProjectionGap("query terminal is not usable", "invalid_binding")
    spans = sorted([predicate["span"], slot])
    for start, end in spans:
        if (type(start) is not int or type(end) is not int or not 0 <= start < end <= len(text)):
            raise LanguageProjectionGap("query span is out of bounds", "invalid_binding")
    if spans[0][1] > spans[1][0]:
        raise LanguageProjectionGap("predicate overlaps the known slot", "invalid_binding")
    if (text[predicate["span"][0]:predicate["span"][1]] != predicate["text"]
            or text[slot[0]:slot[1]] != annotation["slots"][known["slot"]]):
        raise LanguageProjectionGap("query span text differs", "invalid_binding")
    return predicate, {"name": known["slot"], "span": slot}, terminal


def _hypothesis_query_projection(view, graph_id, root, first, targets, record, policy,
                                 facts, queries, query_sources, marks, fact_roles, fact_senses):
    """(association row, its fresh reader), or None when the policy declares no query link."""
    p = _fresh_dialogue_reader(first, view, graph_id, root, targets)
    if p.op(policy) != "relation-hypothesis":
        raise LanguageProjectionGap("%r is not op=relation-hypothesis" % policy, "unsupported_shape")
    ref = p.link(policy, "query", optional=True)
    if ref is None:
        return None
    frame = p.link(policy, "frame")
    p.scalar(p.link(policy, "capture"))
    if frame not in targets["rules"] or targets["rules"].index(frame) != record["frame_index"]:
        raise LanguageProjectionGap("association frame is not the compiled policy frame", "invalid_binding")
    frame_index = record["frame_index"]
    if p.op(ref) != "query-ref":
        raise LanguageProjectionGap("%r is not op=query-ref" % ref, "unsupported_shape")
    target = p.link(ref, "target")
    if target not in targets["queries"]:
        raise LanguageProjectionGap("association query %r is not a selected root query" % target,
                                    "invalid_binding")
    position = targets["queries"].index(target)
    query_index = len(facts) + position
    source = query_sources[position]
    if source["index"] != query_index or source["annotation_sha256"] != _digest(queries[position]):
        raise LanguageProjectionGap("association query source differs", "source_identity_mismatch")
    projected = _rule_projection(p, frame, frame_index)
    if projected["annotation"] != facts[frame_index]:
        raise LanguageProjectionGap("association frame differs from its fact", "source_identity_mismatch")
    _hypothesis_eligible(projected["annotation"])
    bound = _rule_binds(p, p.link(frame, "binds"))
    emits = p.link(frame, "emits")
    _, sense_name = _rule_meaning(p, emits, bound)
    subjects = [p.link(r, "target") for r in p.sequence(p.link(emits, "subjects"), {"role-ref"})]
    if len(subjects) != 1:
        raise LanguageProjectionGap("association frame needs one subject role", "invalid_binding")
    annotation, _ = _query_projection(p, target, query_index, marks, fact_roles, fact_senses)
    if annotation != queries[position]:
        raise LanguageProjectionGap("association query differs from its compiled query", "source_identity_mismatch")
    q_emits = p.link(target, "emits")
    q_subject, q_object = p.link(q_emits, "subject"), p.link(q_emits, "object")
    asked = p.link(q_emits, "asked")
    fact_object = p.link(emits, "object")
    ids = lambda name: p.node(name)["id"]
    if (ids(q_subject) != ids(subjects[0]) or ids(q_object) != ids(fact_object)
            or ids(p.link(q_emits, "relation")) != ids(sense_name)):
        raise LanguageProjectionGap("association query roles or sense differ from the frame", "invalid_binding")
    if asked not in (q_subject, q_object):
        raise LanguageProjectionGap("asked must be the subject or object role", "invalid_binding")
    known_name = q_object if asked == q_subject else q_subject
    predicate, known_slot, terminal = _query_projection_coordinates(p, target, known_name, annotation)
    row = {"policy_index": record["index"], "frame_index": frame_index, "query_index": query_index,
           "query_ref": deepcopy(source), "predicate": predicate, "known_slot": known_slot,
           "roles": {"subject_id": ids(q_subject), "object_id": ids(q_object), "asked_id": ids(asked)},
           "terminal": terminal, "association_source": p.capsule(policy, sense_name)}
    return row, p


def _fresh_dialogue_reader(first, view, graph_id, root, targets):
    p = _Program(view, graph_id, root)
    _same_reader_identity(first, p)
    if _read_dialogue_targets(p) != targets:
        raise LanguageProjectionGap("root changed between readers", "source_identity_mismatch")
    return p


def _query_projection(p, name, index, marks, fact_roles, fact_senses):
    if p.op(name) != "query-rule":
        raise LanguageProjectionGap("%r is not op=query-rule" % name, "unsupported_shape")
    reads = p.link(name, "reads")
    binds = p.link(name, "binds")
    emits = p.link(name, "emits")
    answers = p.link(name, "answers")
    terminal = p.scalar(p.link(name, "terminal"))
    refs = p.sequence(binds, {"role-ref"})
    if len(refs) != 2:
        raise LanguageProjectionGap("query binds needs exactly 2 roles", "invalid_binding")
    roles = {}
    for ref in refs:
        target = p.link(ref, "target")
        if target in roles:
            raise LanguageProjectionGap("role %r bound twice" % target, "invalid_binding")
        roles[target] = _role_projection(p, target)
    projected = list(roles.values())
    if (len({r["node_id"] for r in projected}) != 2 or len({r["slot"] for r in projected}) != 2):
        raise LanguageProjectionGap("query role ids or slots repeat", "invalid_binding")
    for r in projected:
        if r["node_id"] not in fact_roles:
            raise LanguageProjectionGap("query role %r is not a selected fact role" % r["name"], "invalid_binding")
    if p.op(emits) != "query-meaning":
        raise LanguageProjectionGap("emits is not op=query-meaning", "unsupported_shape")
    subject = p.link(emits, "subject")
    obj = p.link(emits, "object")
    sense_name = p.link(emits, "relation")
    asked = p.link(emits, "asked")
    if subject == obj or set((subject, obj)) != set(roles):
        raise LanguageProjectionGap("query subject/object must be the two bound roles", "invalid_binding")
    sense = p.node(sense_name)
    if sense["layer"] != "공통층" or p.op(sense_name) != "sense":
        raise LanguageProjectionGap("relation must be a common-layer sense", "unsupported_shape")
    if not sense["name"] or sense["name"].startswith("$") or sense["id"] not in fact_senses:
        raise LanguageProjectionGap("query relation is not a usable selected sense", "invalid_binding")
    if asked not in (subject, obj):
        raise LanguageProjectionGap("asked must be the subject or object role", "invalid_binding")
    asked_name, known_name = (subject, obj) if asked == subject else (obj, subject)
    known = roles[known_name]
    if not isinstance(terminal, str):
        raise LanguageProjectionGap("terminal must be a string", "unsupported_shape")
    if terminal not in marks:
        raise LanguageProjectionGap("terminal is not a declared question mark", "invalid_binding")
    items = p.sequence(reads, {"literal", "slot", "predicate"})
    if not items:
        raise LanguageProjectionGap("query reads must not be empty", "invalid_binding")
    text, span, predicates, pred_span = "", None, 0, None
    for item in items:
        kind = p.op(item)
        if kind == "slot":
            if p.link(item, "role") != known_name or span is not None:
                raise LanguageProjectionGap("reads needs exactly the non-asked slot once", "invalid_binding")
            span = len(text)
            text += known["seed"]
            continue
        value = p.scalar(p.link(item, "value"))
        if not isinstance(value, str) or (kind == "predicate" and not value):
            raise LanguageProjectionGap("%s value must be a string" % kind, "unsupported_shape")
        if kind == "predicate":
            predicates += 1
            pred_span = (len(text), len(text) + len(value))
        text += value
    if span is None or predicates != 1:
        raise LanguageProjectionGap("reads needs one slot and one predicate", "invalid_binding")
    if not text:
        raise LanguageProjectionGap("query reads text is empty", "invalid_binding")
    if terminal in text:
        raise LanguageProjectionGap("query reads text must not contain the terminal", "invalid_binding")
    if len(text) > 512 or len(text.split()) > 40:
        raise LanguageProjectionGap("query reads text exceeds caps", "cap_overflow")
    starts, at = [], text.find(known["seed"])
    while at >= 0:
        starts.append(at)
        at = text.find(known["seed"], at + 1)
    if starts != [span]:
        raise LanguageProjectionGap("known seed must occur exactly once", "invalid_binding")
    pieces = []
    for item in p.sequence(answers, {"literal", "slot"}):
        if p.op(item) == "slot":
            target = p.link(item, "role")
            if target not in roles:
                raise LanguageProjectionGap("answer slot refers to unbound role %r" % target, "invalid_binding")
            pieces.append("$" + roles[target]["slot"])
            continue
        value = p.scalar(p.link(item, "value"))
        if not isinstance(value, str):
            raise LanguageProjectionGap("answer literal must be a string", "unsupported_shape")
        if value in ("$" + roles[subject]["slot"], "$" + roles[obj]["slot"]):
            raise LanguageProjectionGap("answer literal collides with a bound slot reference", "invalid_binding")
        pieces.append(value)
    if not pieces:
        raise LanguageProjectionGap("answers must not be empty", "invalid_binding")
    terms = {known_name: "$" + known["slot"], asked_name: "?" + roles[asked_name]["slot"]}
    annotation = {"text": text, "slots": {known["slot"]: known["seed"]},
                  "meaning": {"query": [{"triple": [terms[subject], sense["name"], terms[obj]],
                                         "render": pieces}]}}
    inflection_name = p.link(name, "inflection-ref", optional=True)
    if inflection_name is not None:
        annotation["inflection"] = _inflection_annotation(
            p, inflection_name, "question_endings", text, annotation["slots"], pred_span)
    source = {"index": index, "annotation_sha256": _digest(annotation),
              "graph_source": p.capsule(name, sense_name)}
    return annotation, source


def _reply_projection(p, name):
    import string
    reply_keys = frozenset({"observed", "unresolved", "unread_event", "unknown_word",
                            "input_understanding_failed", "no_reading", "ambiguous_reading",
                            "capacity", "invalid", "contradiction",
                            "unmeasured_condition", "condition_false"})
    learning_keys = frozenset({"learning_control_invalid", "learning_target_unavailable",
                               "learning_model_changed", "learning_accepted_resubmit_required",
                               "learning_draft_conflict", "learning_need_equivalent",
                               "learning_need_positive", "learning_need_unrecognized",
                               "learning_need_approval", "learning_rejected"})
    reply_keys = reply_keys | learning_keys
    if p.op(name) != "reply":
        raise LanguageProjectionGap("%r is not op=reply" % name, "unsupported_shape")
    key = p.scalar(p.link(name, "key"))
    value = p.scalar(p.link(name, "value"))
    if (not isinstance(key, str) or not key.strip() or not isinstance(value, str)
            or not value.strip()):
        raise LanguageProjectionGap("reply key and value must be nonblank strings", "invalid_binding")
    relation_fields = {"relation_conditional": ("assumption", "answer"),
                       "relation_meaning_question": ("expression", "reference")}
    if key not in reply_keys and key not in relation_fields:
        raise LanguageProjectionGap("unsupported reply key %r" % key, "invalid_binding")
    if key in relation_fields or key in learning_keys:
        if len(value) > 1024:
            raise LanguageProjectionGap("reply template exceeds 1024 characters", "cap_overflow")
        try:
            encoded = value.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise LanguageProjectionGap("reply template is not valid UTF-8", "cap_overflow") from exc
        if len(encoded) > 4096:
            raise LanguageProjectionGap("reply template exceeds 4096 bytes", "cap_overflow")
    try:
        parsed = list(string.Formatter().parse(value))
    except ValueError as exc:
        raise LanguageProjectionGap("reply format syntax is invalid", "invalid_binding") from exc
    if key in relation_fields:
        allowed = relation_fields[key]
        seen = set()
        for _, field, spec, conv in parsed:
            if field is not None:
                if field not in allowed or spec or conv:
                    raise LanguageProjectionGap("reply uses an unsupported field", "invalid_binding")
                seen.add(field)
        if seen != set(allowed):
            raise LanguageProjectionGap("reply must use every required field", "invalid_binding")
        return key, value, p.capsule(name, None)
    for _, field, spec, conv in parsed:
        if field is not None and (field != "말" or spec or conv):
            raise LanguageProjectionGap("reply may only use the {말} field", "invalid_binding")
    return key, value, p.capsule(name, None)


def _learning_control_projection(p, name, marks):
    import hashlib
    import json
    from marco.language.teaching import _query_form, _check_form
    kinds = frozenset({"equivalence", "positive", "unrecognized", "approve"})
    if p.op(name) != "learning-control":
        raise LanguageProjectionGap("%r is not op=learning-control" % name, "unsupported_shape")
    form_id = p.node(name)["id"]
    kind = p.scalar(p.link(name, "kind"))
    prefix = p.scalar(p.link(name, "ownership-prefix"))
    text = p.scalar(p.link(name, "text"))
    if not isinstance(kind, str) or kind not in kinds:
        raise LanguageProjectionGap("learning-control %r has unsupported kind" % name, "invalid_binding")
    if not isinstance(prefix, str) or not isinstance(text, str):
        raise LanguageProjectionGap("learning-control %r needs string prefix and text" % name, "invalid_binding")
    if len(text) > 512:
        raise LanguageProjectionGap("learning-control %r exceeds 512 characters" % name, "cap_overflow")
    slots = {}
    for item in p.sequence(p.link(name, "slots"), {"learning-slot"}):
        if p.op(item) != "learning-slot":
            raise LanguageProjectionGap("item %r is not op=learning-slot" % item, "unsupported_shape")
        role = p.scalar(p.link(item, "role"))
        seed = p.scalar(p.link(item, "seed"))
        if not isinstance(role, str) or not isinstance(seed, str):
            raise LanguageProjectionGap("learning-slot %r needs string role and seed" % item, "invalid_binding")
        if role in slots or seed in slots.values():
            raise LanguageProjectionGap("learning-slot %r repeats a role or seed" % item, "duplicate_ref")
        slots[role] = seed
    expression_kind = "fact"
    kind_node = p.link(name, "expression-kind", optional=True)
    if kind_node is not None:
        expression_kind = p.scalar(kind_node)
        if expression_kind not in ("fact", "query"):
            raise LanguageProjectionGap("learning-control %r has unsupported expression-kind" % name,
                                        "invalid_binding")
    if expression_kind == "query" and not marks:
        raise LanguageProjectionGap("query control %r needs nonempty question-marks" % name, "invalid_binding")
    terminals_seq = p.link(name, "capture-terminals", optional=True)
    terminals = None
    if expression_kind == "fact":
        if terminals_seq is not None:
            raise LanguageProjectionGap("fact control %r cannot declare capture-terminals" % name,
                                        "invalid_binding")
    elif terminals_seq is None:
        if not marks:
            raise LanguageProjectionGap("query control %r needs nonempty question-marks" % name, "invalid_binding")
        terminals = list(marks)
    else:
        terminals = _scalar_list(p, terminals_seq)
        if len(terminals) > _MAX_LIST:
            raise LanguageProjectionGap("capture-terminals exceed %d entries" % _MAX_LIST, "cap_overflow")
        if (any(not isinstance(c, str) for c in terminals) or len(set(terminals)) != len(terminals)
                or any(c not in marks for c in terminals)):
            raise LanguageProjectionGap("capture-terminals must be a unique subset of question-marks",
                                        "invalid_binding")
    form = {"id": form_id, "kind": kind, "ownership_prefix": prefix, "text": text,
            "slots": slots, "wide_slots": list(slots)}
    if expression_kind == "query":
        form["expression_kind"] = "query"
        form["capture_terminals"] = terminals
    try:
        if expression_kind == "query":
            _query_form(form, list(marks))
        else:
            _check_form(form)
    except (ValueError, TypeError, AttributeError) as exc:
        raise LanguageProjectionGap("learning-control %r is invalid: %s" % (name, exc), "invalid_binding") from exc
    blob = json.dumps(form, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    form_sha256 = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    return form, {"id": form_id, "form_sha256": form_sha256, "graph_source": p.capsule(name, None)}
_UNREAD_SCHEMA = "graph-unread-continuation-policy-v1"
_UNREAD_SCHEMA_V2 = "graph-unread-continuation-policy-v2"
_UNREAD_OPS = ("known-evidence-policy", "known-evidence-policy-v2")
_UNREAD_SCOPE = "direct_positive_immutable_binary"
_UNREAD_RENDER_CAPS = (1024, 4096)


def _unread_template(render):
    import string
    if not isinstance(render, str) or not render.strip():
        raise LanguageProjectionGap("unread-continuation render must be a nonblank string", "invalid_binding")
    if len(render) > _UNREAD_RENDER_CAPS[0]:
        raise LanguageProjectionGap("unread-continuation render exceeds %d characters" % _UNREAD_RENDER_CAPS[0],
                                    "cap_overflow")
    try:
        encoded = render.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise LanguageProjectionGap("unread-continuation render is not valid UTF-8", "cap_overflow") from exc
    if len(encoded) > _UNREAD_RENDER_CAPS[1]:
        raise LanguageProjectionGap("unread-continuation render exceeds %d bytes" % _UNREAD_RENDER_CAPS[1],
                                    "cap_overflow")
    try:
        parsed = list(string.Formatter().parse(render))
    except ValueError as exc:
        raise LanguageProjectionGap("unread-continuation render syntax is invalid", "invalid_binding") from exc
    seen = []
    for _, field, spec, conv in parsed:
        if field is not None:
            if field not in ("answer", "unread") or spec or conv:
                raise LanguageProjectionGap("unread-continuation render uses an unsupported field", "invalid_binding")
            seen.append(field)
    if sorted(seen) != ["answer", "unread"]:
        raise LanguageProjectionGap("unread-continuation render must use {answer} and {unread} once each",
                                    "invalid_binding")
    return parsed


def _unread_policy_projection(p, name):
    op = p.op(name)
    if op not in _UNREAD_OPS:
        raise LanguageProjectionGap("%r is not op=known-evidence-policy" % name, "unsupported_shape")
    scope = p.scalar(p.link(name, "scope"))
    render = p.scalar(p.link(name, "render"))
    if not isinstance(scope, str) or scope != _UNREAD_SCOPE:
        raise LanguageProjectionGap("unsupported unread-continuation scope", "invalid_binding")
    _unread_template(render)
    declared = {"schema": _UNREAD_SCHEMA, "scope": scope, "render": render, "source": p.capsule(name, None)}
    if op == _UNREAD_OPS[1]:
        max_pending = p.scalar(p.link(name, "max-pending"))
        if type(max_pending) is not int or not 1 <= max_pending <= 8:
            raise LanguageProjectionGap("unsupported unread-continuation max-pending", "invalid_binding")
        declared = {"schema": _UNREAD_SCHEMA_V2, "scope": scope, "render": render,
                    "max_pending": max_pending, "source": p.capsule(name, None)}
    stack = [(declared, 0)]
    nodes = 1
    while stack:
        value, depth = stack.pop()
        nodes += 1
        if nodes > 4096:
            raise LanguageProjectionGap("unread-continuation policy exceeds 4096 JSON nodes", "cap_overflow")
        if depth > 32:
            raise LanguageProjectionGap("unread-continuation policy exceeds JSON depth 32", "cap_overflow")
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise LanguageProjectionGap("unread-continuation policy has a non-string key", "unsupported_shape")
                stack.append((item, depth + 1))
        elif isinstance(value, list):
            for item in value:
                stack.append((item, depth + 1))
        elif isinstance(value, float):
            if value != value or value in (float("inf"), float("-inf")):
                raise LanguageProjectionGap("unread-continuation policy has a non-finite number", "unsupported_shape")
        elif value is not None and not isinstance(value, (bool, int, str)):
            raise LanguageProjectionGap("unread-continuation policy has a non-JSON value", "unsupported_shape")
    try:
        declaration_sha256 = _digest(declared)
    except UnicodeEncodeError as exc:
        raise LanguageProjectionGap("unread-continuation policy declaration is not valid UTF-8", "cap_overflow") from exc
    except (TypeError, ValueError) as exc:
        raise LanguageProjectionGap("unread-continuation policy declaration is not plain JSON", "unsupported_shape") from exc
    policy = {**declared, "declaration_sha256": declaration_sha256}
    try:
        text = json.dumps(policy, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise LanguageProjectionGap("unread-continuation policy is not plain JSON", "unsupported_shape") from exc
    try:
        encoded = text.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise LanguageProjectionGap("unread-continuation policy is not valid UTF-8", "cap_overflow") from exc
    if len(encoded) > 65536:
        raise LanguageProjectionGap("unread-continuation policy exceeds 65536 bytes", "cap_overflow")
    return policy


def _render_unread_qualification(render, answer, unread):
    _unread_template(render)
    if not isinstance(answer, str) or not isinstance(unread, str):
        raise LanguageProjectionGap("answer and unread must be strings", "invalid_binding")
    for label, text in (("answer", answer), ("unread", unread)):
        try:
            encoded = text.encode("utf-8")
        except UnicodeEncodeError as exc:
            raise LanguageProjectionGap("unread-continuation %s is not valid UTF-8" % label, "cap_overflow") from exc
        if len(encoded) > 8192:
            raise LanguageProjectionGap("unread-continuation %s exceeds 8192 bytes" % label, "cap_overflow")
    result = render.format(answer=answer, unread=unread)
    try:
        encoded = result.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise LanguageProjectionGap("unread-continuation result is not valid UTF-8", "cap_overflow") from exc
    if len(encoded) > 24576:
        raise LanguageProjectionGap("unread-continuation result exceeds 24576 bytes", "cap_overflow")
    return result


_FACT_BATCH_SCHEMA = "graph-fact-batch-policy-v1"
_FACT_BATCH_SCOPE = "direct_positive_asserted_binary_fact_batch"


def _fact_batch_policy_projection(p, name):
    if p.op(name) != "fact-batch-policy":
        raise LanguageProjectionGap("%r is not op=fact-batch-policy" % name, "unsupported_shape")
    scope = p.scalar(p.link(name, "scope"))
    rows = p.scalar(p.link(name, "max-rows"))
    if not isinstance(scope, str) or scope != _FACT_BATCH_SCOPE:
        raise LanguageProjectionGap("unsupported fact-batch scope", "invalid_binding")
    if type(rows) is not int or rows != 2:
        raise LanguageProjectionGap("fact-batch max-rows must be 2", "invalid_binding")
    declared = {"schema": _FACT_BATCH_SCHEMA, "scope": scope, "max_rows": rows,
                "source": p.capsule(name, None)}
    try:
        policy = {**declared, "declaration_sha256": _digest(declared)}
        encoded = json.dumps(policy, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                             allow_nan=False).encode("utf-8")
    except UnicodeEncodeError as exc:
        raise LanguageProjectionGap("fact-batch policy is not valid UTF-8", "cap_overflow") from exc
    except (TypeError, ValueError) as exc:
        raise LanguageProjectionGap("fact-batch policy is not plain JSON", "unsupported_shape") from exc
    if len(encoded) > 65536:
        raise LanguageProjectionGap("fact-batch policy exceeds 65536 bytes", "cap_overflow")
    return policy


def _scoped_semantics(grammar, facts, frames, queries, query_sources, marks):
    """Derive explicit negative queries and capability data from a v2 grammar (appends to queries)."""
    from marco.language.hangul import inflect
    pack = grammar["language_pack"]
    infl = pack["inflection"]
    caps = grammar["semantic_capabilities"]
    reference = deepcopy(grammar["reference"])
    originals = len(queries)
    selected = []

    def compact(ref, example):
        return {'index': ref['index'],
                'annotation_sha256': ref['annotation_sha256'] if example is None else _digest(example),
                'source_ref_sha256': sha_of(ref)}

    def frame_refs(indices):
        refs = []
        for i in indices:
            if i >= len(facts) or i >= len(frames):
                raise _grammar_gap("invalid_binding")
            meaning = facts[i].get("meaning")
            triple = meaning.get("triple") if isinstance(meaning, dict) else None
            if (not isinstance(triple, list) or len(triple) != 3 or "query" in meaning
                    or meaning.get("polarity") is False):
                raise _grammar_gap("invalid_binding")
            refs.append(compact(frames[i]["source_ref"], facts[i]))
        return refs

    def sha_of(basis):
        return hashlib.sha256(json.dumps(basis, ensure_ascii=False, sort_keys=True, allow_nan=False,
                                         separators=(",", ":")).encode("utf-8")).hexdigest()

    out = {"schema": "selected-binary-semantic-capabilities-v1"}
    scope = sha_of({'inflection': infl, 'negation': pack.get('negation', {}),
                    'clauses': {'candidate_suffixes': pack.get('clauses', {}).get('candidate_suffixes', []),
                                'question_marks': list(marks)}})
    if "negative_binary" in caps:
        cap = caps["negative_binary"]
        ordinals = cap["query_ordinals"]
        for o in ordinals:
            if o >= originals:
                raise _grammar_gap("invalid_binding")
        basis = {"schema": "selected-negative-binary-basis-v1", "grammar_reference": reference,
                 "frame_refs": frame_refs(cap["frame_indices"]),
                 "original_query_refs": [compact(query_sources[o], queries[o]) for o in ordinals],
                 "normalized_language_scope_sha256": scope}
        sha = sha_of(basis)
        neg = pack["negation"]
        derived, sources = [], []
        for o in ordinals:
            ann = queries[o]
            a_infl = ann.get("inflection")
            if not isinstance(a_infl, dict):
                raise _grammar_gap("unsupported_inflection")
            text, slots = ann["text"], ann["slots"]
            slot_end = max((text.index(v) + len(v) for v in slots.values()), default=0)
            try:
                forms = inflect(a_infl["stem"], "present", a_infl["ending"], infl, kind=a_infl["kind"])
                aux = inflect(neg["어간"], "present", a_infl["ending"], infl, kind=neg["갈래"])
            except ValueError as exc:
                raise _grammar_gap("unsupported_inflection") from exc
            suffixes = {f["text"] for f in forms
                        if text.endswith(f["text"]) and len(text) - len(f["text"]) >= slot_end}
            auxes = {f["text"] for f in aux}
            endings = [e for e in a_infl["endings"] if e in infl["question_endings"]]
            query = ann["meaning"].get("query")
            if (len(suffixes) != 1 or len(auxes) != 1 or a_infl["ending"] not in endings
                    or not isinstance(query, list) or not query or not isinstance(query[0], dict)):
                raise _grammar_gap("unsupported_inflection")
            suffix, auxform = next(iter(suffixes)), next(iter(auxes))
            item = deepcopy(ann)
            item["text"] = text[:len(text) - len(suffix)] + a_infl["stem"] + neg["연결"] + " " + auxform
            item["meaning"]["query"][0]["polarity"] = False
            item["inflection"] = {"stem": neg["어간"], "tense": "present", "ending": a_infl["ending"],
                                  "kind": neg["갈래"], "endings": endings}
            source = {"index": len(facts) + originals + len(derived),
                      "annotation_sha256": _digest(item),
                      "graph_source": deepcopy(query_sources[o]["graph_source"]),
                      "negative_derivation": {"original_query_ref": compact(query_sources[o], queries[o]),
                                              "grammar_reference": deepcopy(reference),
                                              "capability_sha256": sha}}
            derived.append(item)
            sources.append(source)
        queries.extend(derived)
        query_sources.extend(sources)
        selected = [deepcopy(query_sources[o]) for o in ordinals] + deepcopy(sources)
        out["negative_binary"] = {"schema": "selected-negative-binary-v1", "basis": basis,
                                  "capability_sha256": sha, "query_refs": [compact(s, None) for s in sources]}
    if "conditional_binary" in caps:
        basis = {"schema": "selected-conditional-binary-basis-v1", "grammar_reference": reference,
                 "frame_refs": frame_refs(caps["conditional_binary"]["frame_indices"]),
                 "original_query_refs": [], "normalized_language_scope_sha256": scope}
        out["conditional_binary"] = {"schema": "selected-conditional-binary-v1", "basis": basis,
                                     "capability_sha256": sha_of(basis), "query_refs": []}
    sizes = [len(json.dumps(s, ensure_ascii=False, sort_keys=True, separators=(',', ':'),
                            allow_nan=False).encode('utf-8')) for s in selected]
    if (len(selected) > 4 or len({s['index'] for s in selected}) != len(selected)
            or any(n > 65536 for n in sizes) or sum(sizes) > 262144):
        raise _grammar_gap("cap_overflow")
    return out, selected


def project_language_dialogue(view, graph_id, root, *, source=None):
    """Project facts, queries and replies into detached dialogue projection data."""
    first = _Program(view, graph_id, root)
    targets = _read_dialogue_targets(first)
    settings, marks = targets["settings"], targets["marks"]
    nodes, edges, names, rows = {}, {}, {}, {}
    _merge_reader(first, nodes, edges, names, rows)
    facts, frames, output_rules = [], [], []
    fact_roles, fact_senses = set(), set()
    for index, target in enumerate(targets["rules"]):
        p = _fresh_dialogue_reader(first, view, graph_id, root, targets)
        projected = _rule_projection(p, target, index)
        bound = _rule_binds(p, p.link(target, "binds"))
        _, sense_name = _rule_meaning(p, p.link(target, "emits"), bound)
        fact_roles.update(r["node_id"] for r in bound.values())
        fact_senses.add(p.node(sense_name)["id"])
        _merge_reader(p, nodes, edges, names, rows)
        facts.append(projected["annotation"])
        frames.append(projected["frame"])
        if projected["output"] is not None:
            output_rules.append(projected["output"])
    queries, query_sources = [], []
    for target in targets["queries"]:
        p = _fresh_dialogue_reader(first, view, graph_id, root, targets)
        annotation, graph_source = _query_projection(
            p, target, len(facts) + len(queries), marks, fact_roles, fact_senses)
        _merge_reader(p, nodes, edges, names, rows)
        queries.append(annotation)
        query_sources.append(graph_source)
    semantic_caps, semantic_sources = None, None
    if "grammar" in settings and "semantic_capabilities" in settings["grammar"]:
        semantic_caps, semantic_sources = _scoped_semantics(
            settings["grammar"], facts, frames, queries, query_sources, marks)
    replies, reply_sources = {}, {}
    for target in targets["replies"]:
        p = _fresh_dialogue_reader(first, view, graph_id, root, targets)
        key, value, graph_source = _reply_projection(p, target)
        if key in replies:
            raise LanguageProjectionGap("reply key %r repeats" % key, "invalid_binding")
        _merge_reader(p, nodes, edges, names, rows)
        replies[key] = value
        reply_sources[key] = graph_source
    learning_dialogue, control_sources = None, None
    if targets["controls"] is not None:
        import json
        forms, control_sources = [], []
        for target in targets["controls"]:
            p = _fresh_dialogue_reader(first, view, graph_id, root, targets)
            form, row = _learning_control_projection(p, target, marks)
            _merge_reader(p, nodes, edges, names, rows)
            forms.append(form)
            control_sources.append(row)
        learning_schema = ("selected-learning-dialogue-v2"
                           if any(form.get("expression_kind") == "query" for form in forms)
                           else "selected-learning-dialogue-v1")
        learning_dialogue = {"schema": learning_schema, "forms": forms}
        declared = json.dumps(learning_dialogue, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        if len(declared.encode("utf-8")) > 65536:
            raise LanguageProjectionGap("learning declaration exceeds 65536 UTF-8 bytes", "cap_overflow")
    unread_policy = None
    if targets["continuation"] is not None:
        p = _fresh_dialogue_reader(first, view, graph_id, root, targets)
        unread_policy = _unread_policy_projection(p, targets["continuation"])
        _merge_reader(p, nodes, edges, names, rows)
    fact_batch_policy = None
    if targets["fact_batch"] is not None:
        p = _fresh_dialogue_reader(first, view, graph_id, root, targets)
        fact_batch_policy = _fact_batch_policy_projection(p, targets["fact_batch"])
        _merge_reader(p, nodes, edges, names, rows)
    hypotheses = None
    if targets["hypotheses"] is not None:
        hypotheses, seen_frames = [], set()
        for index, policy in enumerate(targets["hypotheses"]):
            p = _fresh_dialogue_reader(first, view, graph_id, root, targets)
            record = _hypothesis_projection(p, policy, targets["rules"], index, facts, frames)
            frame_key = (record["frame_index"], p.node(targets["rules"][record["frame_index"]])["id"])
            if record["frame_index"] in {k[0] for k in seen_frames} or frame_key[1] in {k[1] for k in seen_frames}:
                raise LanguageProjectionGap("hypothesis frame %r is referenced twice"
                                            % targets["rules"][record["frame_index"]], "invalid_binding")
            seen_frames.add(frame_key)
            _merge_reader(p, nodes, edges, names, rows)
            hypotheses.append(record)
    associations = []
    if hypotheses is not None:
        for record, policy in zip(hypotheses, targets["hypotheses"]):
            linked = _hypothesis_query_projection(view, graph_id, root, first, targets, record, policy,
                                                  facts, queries, query_sources, marks,
                                                  fact_roles, fact_senses)
            if linked is None:
                continue
            if len(associations) >= _MAX_LIST:
                raise LanguageProjectionGap("more than %d associations" % _MAX_LIST, "cap_overflow")
            _merge_reader(linked[1], nodes, edges, names, rows)
            associations.append(linked[0])
    seed_sha256 = _digest(facts)
    query_sha256 = _digest({"examples": queries, "sources": query_sources})
    reply_sha256 = _digest({"replies": replies, "sources": reply_sources})
    provenance = {"graph_id": first.graph_id, "root_id": first.node(first.root)["id"],
                  "effective_graph_sha256": first.effective_graph_sha256,
                  "view_key": list(first.view_key), "base_origin": deepcopy(first.base_origin),
                  "source": _source_descriptor(first, source), "nodes": nodes, "edges": edges}
    schema = "graph-dialogue-projection-v1"
    fingerprint = {"schema": schema, "provenance": provenance,
                   "seed_sha256": seed_sha256, "query_sha256": query_sha256,
                   "reply_sha256": reply_sha256}
    extra = {}
    if "grammar" in settings:
        fingerprint["grammar"] = settings["grammar"]
    if hypotheses is not None:
        fingerprint["relation_hypotheses"] = hypotheses
        extra["relation_hypotheses"] = hypotheses
    if associations:
        fingerprint["relation_hypothesis_queries"] = associations
        extra["relation_hypothesis_queries"] = associations
    data_extra = {}
    if learning_dialogue is not None:
        fingerprint["learning_dialogue"] = {"declaration": learning_dialogue, "sources": control_sources}
        data_extra["learning_dialogue"] = learning_dialogue
        extra["control_sources"] = control_sources
    if semantic_caps is not None:
        fingerprint["semantic_capabilities"] = semantic_caps
        fingerprint["semantic_query_sources"] = semantic_sources
        data_extra["semantic_capabilities"] = semantic_caps
        data_extra["semantic_query_sources"] = semantic_sources
    if unread_policy is not None:
        fingerprint["unread_continuation"] = unread_policy
        data_extra["unread_continuation"] = unread_policy
    if fact_batch_policy is not None:
        fingerprint["fact_batch"] = fact_batch_policy
        data_extra["fact_batch"] = fact_batch_policy
    return deepcopy({
        **extra,
        "schema": schema,
        "data": {
            "schema": "annotated-relations-v1", "examples": facts + queries,
            "ignore_case": settings["ignore_case"], "numerals": {},
            "predicate_frames": {
                "schema": "predicate-frames-v2", "seed_count": len(facts),
                "seed_sha256": seed_sha256, "head_pattern": settings["head_pattern"],
                "separators": settings["separators"], "terminators": settings["terminators"],
                "operators": settings["operators"], "frames": frames},
            "context_replies": replies, **data_extra,
        },
        "language_pack": {**(deepcopy(settings["grammar"]["language_pack"]) if "grammar" in settings else {}),
                          "clauses": {**deepcopy((settings["grammar"]["language_pack"] if "grammar" in settings else {}).get("clauses", {})),
                                      "question_marks": list(marks)}},
        "output_rules": output_rules, "query_sources": query_sources,
        "reply_sources": reply_sources, "provenance": provenance,
        "fingerprint": _digest(fingerprint),
    })


def _agc_fail(message, gap):
    raise LanguageProjectionGap(message, gap)


def _agc_text(value, what):
    if not isinstance(value, str) or not value.strip():
        _agc_fail('%s must be a nonblank string' % what, 'invalid_action_catalog')
    return value


def _agc_id(p, name):
    return p.node(name)['id']


def _agc_limits(p, name):
    if p.op(name) != 'action-limits':
        _agc_fail('limits must be op=action-limits', 'unknown_op')
    ceil = {'max_catalog_entries': 256, 'max_candidate_terms': 2, 'max_program_steps': 128,
            'max_call_depth': 32, 'max_expanded_steps': 1024, 'max_json_nodes': 4096,
            'max_catalog_bytes': 262144}
    limits = {}
    for key, top in ceil.items():
        value = p.scalar(p.link(name, key.replace('_', '-')))
        if type(value) is not int or value < 1 or value > top:
            _agc_fail('limit %s is outside its ceiling' % key, 'cap_overflow')
        limits[key] = value
    return limits


def _agc_role(p, node):
    if p.op(node) != 'action-role':
        _agc_fail('role %r is not op=action-role' % node, 'unknown_op')
    variable = p.scalar(p.link(node, 'variable'))
    slot = p.scalar(p.link(node, 'slot'))
    for what, text in (('role variable', variable), ('role slot', slot)):
        _agc_text(text, what)
        if text != text.strip() or '$' in text or '?' in text:
            _agc_fail('%s is not a plain name' % what, 'invalid_action_catalog')
        if len(text) > 128:
            _agc_fail('%s exceeds 128 characters' % what, 'cap_overflow')
    type_node = p.link(node, 'type-ref')
    if p.op(type_node) != 'action-type':
        _agc_fail('type-ref is not op=action-type', 'unknown_op')
    _agc_text(p.scalar(p.link(type_node, 'name')), 'type name')
    if (p.scalar(p.link(node, 'presence')) != 'required'
            or p.scalar(p.link(node, 'coreference-group')) is not None
            or p.scalar(p.link(node, 'binding-mode')) != 'open'):
        _agc_fail('only open required uncoupled roles are supported', 'unsupported_scope')
    return {'variable': variable, 'slot': slot, 'role_node_id': _agc_id(p, node),
            'type_node_id': _agc_id(p, type_node)}


def _agc_entry(p, node, seen):
    if p.op(node) != 'action-entry':
        _agc_fail('entry %r is not op=action-entry' % node, 'unknown_op')
    ident = _agc_text(p.scalar(p.link(node, 'id')), 'action id')
    if len(ident) > 128:
        _agc_fail('action id exceeds 128 characters', 'cap_overflow')
    version = p.scalar(p.link(node, 'version'))
    if not (type(version) is int or (isinstance(version, str) and version)):
        _agc_fail('version must be an int or nonempty string', 'invalid_action_catalog')
    composable = p.scalar(p.link(node, 'composable'))
    if type(composable) is not bool:
        _agc_fail('composable must be a bool', 'invalid_action_catalog')
    label_node = p.link(node, 'label')
    label = _agc_text(p.scalar(label_node), 'label')
    if len(label) > 512:
        _agc_fail('label exceeds 512 characters', 'cap_overflow')
    if p.sequence(p.link(node, 'allowed-compute-operators'), ()):
        _agc_fail('compute operators are unsupported', 'unsupported_scope')
    key = '%s@%s' % (ident, version)
    typed = (ident, type(version).__name__, version)
    node_id = _agc_id(p, node)
    if typed in seen['typed'] or key in seen['keys'] or node_id in seen['entries']:
        _agc_fail('duplicate action identity', 'duplicate_ref')
    program = p.link(node, 'program')
    program_id = _agc_id(p, program)
    roles, by_node, variables, slots = [], {}, set(), set()
    for item in p.sequence(p.link(node, 'roles'), {'action-role-ref'}):
        role_node = p.link(item, 'target')
        role = _agc_role(p, role_node)
        if role_node in by_node or role['variable'] in variables or role['slot'] in slots:
            _agc_fail('duplicate role', 'duplicate_ref')
        variables.add(role['variable'])
        slots.add(role['slot'])
        by_node[role_node] = role
        roles.append(role)
    seen['typed'].add(typed)
    seen['keys'].add(key)
    seen['entries'].add(node_id)
    return {'id': ident, 'version': version, 'key': key, 'node': node, 'node_id': node_id,
            'program_node': program, 'program_id': program_id, 'label': label,
            'label_id': _agc_id(p, label_node), 'composable': composable,
            'roles': roles, 'by_node': by_node}


def _agc_value(p, name, rec, literal_ok):
    if p.op(name) != 'action-value':
        _agc_fail('value %r is not op=action-value' % name, 'unknown_op')
    kind = p.scalar(p.link(name, 'kind'))
    edges = {rel for rel, _ in p._program_edges(name)}
    if kind == 'variable' and 'literal' not in edges:
        role = rec['by_node'].get(p.link(name, 'role'))
        if role is None:
            _agc_fail('value role is not a role of this action', 'invalid_binding')
        return '$' + role['variable'], _agc_id(p, name), role
    if kind == 'literal' and 'role' not in edges:
        if not literal_ok:
            _agc_fail('literal call binding is unsupported', 'unsupported_literal_call_binding')
        text = _agc_text(p.scalar(p.link(name, 'literal')), 'literal')
        if '$' in text or '?' in text:
            _agc_fail('literal contains variable syntax', 'invalid_action_catalog')
        return text, _agc_id(p, name), None
    _agc_fail('malformed action-value', 'unsupported_shape')


def _agc_steps(p, rec, members, limits):
    program = rec['program_node']
    if p.op(program) != 'action-program':
        _agc_fail('program is not op=action-program', 'unknown_op')
    items = p.sequence(p.link(program, 'steps'), {'action-emit', 'action-call'})
    if not items:
        _agc_fail('program needs at least one step', 'invalid_action_catalog')
    if len(items) > limits['max_program_steps']:
        _agc_fail('program exceeds max_program_steps', 'cap_overflow')
    out = {'steps': [], 'calls': [], 'refs': {}, 'maps': [], 'targets': []}
    for index, item in enumerate(items):
        step_id = _agc_id(p, item)
        if p.op(item) == 'action-emit':
            rows, refs = [], []
            for row in p.sequence(p.link(item, 'triples'), {'action-triple'}):
                subject = _agc_value(p, p.link(row, 'subject'), rec, True)
                predicate = p.link(row, 'predicate')
                pnode = p.node(predicate)
                if pnode.get('layer') != '공통층' or p.op(predicate) != 'sense':
                    _agc_fail('predicate is not a common-layer op=sense', 'unknown_op')
                pname = pnode.get('name')
                if not isinstance(pname, str) or not pname or pname.startswith('$'):
                    _agc_fail('predicate name is unusable', 'invalid_action_catalog')
                obj = _agc_value(p, p.link(row, 'object'), rec, True)
                rows.append([subject[0], pname, obj[0]])
                refs.append({'triple_node_id': _agc_id(p, row), 'subject_node_id': subject[1],
                             'predicate_node_id': _agc_id(p, predicate),
                             'object_node_id': obj[1]})
            if not rows:
                _agc_fail('emit needs at least one triple', 'invalid_action_catalog')
            out['steps'].append({'op': 'emit', 'triples': rows})
            out['maps'].append({'index': index, 'op': 'emit', 'step_node_id': step_id,
                                'triples': refs, 'target_entry_node_id': None, 'bindings': []})
            continue
        target = members.get(p.link(item, 'target'))
        if target is None:
            _agc_fail('call target is not a catalog member', 'unknown_action_call')
        bound, refs, role_map = set(), [], {}
        for binding in p.sequence(p.link(item, 'bindings'), {'action-call-binding'}):
            child = p.link(binding, 'role')
            child_role = target['by_node'].get(child)
            if child_role is None:
                _agc_fail('binding role does not belong to target', 'invalid_binding')
            if child in bound:
                _agc_fail('target role bound twice', 'duplicate_ref')
            value = _agc_value(p, p.link(binding, 'value'), rec, False)
            if value[2]['type_node_id'] != child_role['type_node_id']:
                _agc_fail('binding type mismatch', 'invalid_binding')
            bound.add(child)
            role_map[child_role['slot']] = value[0]
            refs.append({'binding_node_id': _agc_id(p, binding),
                         'child_role_node_id': child_role['role_node_id'],
                         'value_node_id': value[1]})
        if bound != set(target['by_node']):
            _agc_fail('call does not cover target roles exactly once', 'invalid_binding')
        out['steps'].append({'op': 'call', 'action': target['id'],
                             'definition_version': target['version'], 'roles': dict(role_map)})
        out['calls'].append({'action': target['id'], 'definition_version': target['version'],
                             'roles': dict(role_map)})
        out['refs'][target['key']] = target['version']
        out['targets'].append(target['key'])
        out['maps'].append({'index': index, 'op': 'call', 'step_node_id': step_id,
                            'triples': [], 'target_entry_node_id': target['node_id'],
                            'bindings': refs})
    return out


def _agc_graph(records, limits):
    by_key = {r['key']: r for r in records}
    waiting = {k: len(set(r['targets'])) for k, r in by_key.items()}
    users = {k: [] for k in by_key}
    for k, r in by_key.items():
        for t in set(r['targets']):
            users[t].append(k)
    ready = [k for k, n in waiting.items() if n == 0]
    height, total, done = {}, {}, 0
    while ready:
        k = ready.pop()
        r = by_key[k]
        done += 1
        height[k] = 1 + max((height[t] for t in r['targets']), default=-1)
        total[k] = r['direct'] + sum(total[t] for t in r['targets'])
        if height[k] >= limits['max_call_depth']:
            _agc_fail('call depth reaches max_call_depth', 'call_depth_exceeded')
        if total[k] > limits['max_expanded_steps']:
            _agc_fail('expanded steps exceed max_expanded_steps', 'expanded_steps_exceeded')
        for u in users[k]:
            waiting[u] -= 1
            if waiting[u] == 0:
                ready.append(u)
    if done != len(by_key):
        _agc_fail('action calls contain a cycle', 'call_cycle')


def _action_catalog_projection(p, catalog_name):
    if p.op(catalog_name) != 'action-catalog':
        _agc_fail('catalog must be op=action-catalog', 'unknown_op')
    id_node = p.link(catalog_name, 'catalog-id')
    catalog_id = _agc_text(p.scalar(id_node), 'catalog-id')
    limits_node = p.link(catalog_name, 'limits')
    limits = _agc_limits(p, limits_node)
    programs_node = p.link(catalog_name, 'programs')
    items = p.sequence(programs_node, {'action-ref'})
    if not items:
        _agc_fail('catalog needs at least one entry', 'invalid_action_catalog')
    if len(items) > limits['max_catalog_entries']:
        _agc_fail('catalog exceeds max_catalog_entries', 'cap_overflow')
    seen = {'typed': set(), 'keys': set(), 'entries': set()}
    records = [_agc_entry(p, p.link(item, 'target'), seen) for item in items]
    members = {r['node']: r for r in records}
    programs, labels, entry_maps = [], {}, []
    for rec in records:
        built = _agc_steps(p, rec, members, limits)
        rec['targets'] = built['targets']
        rec['direct'] = len(built['steps'])
        signature = {'role_slots': {r['variable']: r['slot'] for r in rec['roles']},
                     'open_roles': {r['variable']: r['slot'] for r in rec['roles']},
                     'fixed_values': {}}
        program = {'schema': 'nai-action-program-v1', 'action': rec['id'],
                   'definition_version': rec['version'],
                   'definition_evidence': {'kind': 'native_action_definition_ref',
                                           'entry_node_id': rec['node_id'],
                                           'program_node_id': rec['program_id']},
                   'references': built['refs'], 'signature': signature,
                   'calls': built['calls'], 'steps': built['steps']}
        programs.append({
            'id': rec['id'], 'version': rec['version'], 'program': program,
            'composable': rec['composable'],
            'roles': {r['slot']: {'type_ref': r['type_node_id'], 'presence': 'required',
                                  'coreference_group': None} for r in rec['roles']},
            'allowed_compute_operators': []})
        labels[rec['key']] = rec['label']
        entry_maps.append({
            'id': rec['id'], 'version': rec['version'], 'execute_key': rec['key'],
            'entry_node_id': rec['node_id'], 'program_node_id': rec['program_id'],
            'label_node_id': rec['label_id'],
            'roles': [{'variable': r['variable'], 'slot': r['slot'],
                       'role_node_id': r['role_node_id'], 'type_node_id': r['type_node_id']}
                      for r in rec['roles']],
            'steps': built['maps']})
    _agc_graph(records, limits)
    return {'catalog_id': catalog_id, 'limits': limits, 'programs': programs,
            'entry_labels': labels,
            'source_maps': {'catalog': {'catalog_node_id': _agc_id(p, catalog_name),
                                        'id_node_id': _agc_id(p, id_node),
                                        'limits_node_id': _agc_id(p, limits_node),
                                        'programs_node_id': _agc_id(p, programs_node)},
                            'entries': entry_maps}}


def _agp_gap(msg, code):
    return LanguageProjectionGap(msg, code)


def _agp_id(p, name):
    return p.node(name)['id']


def _agp_node(p, name, op):
    if p.op(name) != op:
        raise _agp_gap('%r is not op=%s' % (name, op), 'unknown_op')
    return name


def _agp_field(p, name, rel):
    return p.scalar(p.link(name, rel))


def _agp_scalars(p, seq):
    out = []
    for item in p.sequence(seq, {'scalar'}):
        if p.op(item) != 'scalar':
            raise _agp_gap('item %r is not op=scalar' % item, 'unsupported_shape')
        vn = p.link(item, 'value')
        out.append((p.scalar(vn), _agp_id(p, item), _agp_id(p, vn)))
    return out


def _agp_name(v, cap=512):
    return type(v) is str and 0 < len(v) <= cap


def _agp_ints(p, node, rels, ceil):
    out = {}
    for rel in rels:
        key = rel.replace('-', '_')
        v = p.scalar(p.link(node, rel))
        if type(v) is not int or not 1 <= v <= ceil[key]:
            raise _agp_gap('invalid limit %s' % key, 'invalid_limit')
        out[key] = v
    return out


def _agp_strs(v, path, cap, nows, single):
    if type(v) is not list:
        return 'malformed', path
    if len(v) > cap:
        return 'input_cap', path
    for x in v:
        if type(x) is not str or not x or len(x) > 512:
            return 'malformed', path
        if single and len(x) != 1:
            return 'unsupported_boundary', path
        if nows and any(c.isspace() for c in x):
            return 'malformed', path
    if len(set(v)) != len(v):
        return 'malformed', path
    return None


def _agp_scan(obj, cap):
    stack, n = [obj], 0
    while stack:
        x = stack.pop()
        n += 1
        if n > cap:
            return 'input_cap'
        t = type(x)
        if t is dict or t is list:
            if n + len(x) + len(stack) > cap:
                return 'input_cap'
            if t is dict:
                for k, v in x.items():
                    if type(k) is not str or len(k) > 512:
                        return 'malformed'
                    stack.append(v)
            else:
                stack.extend(x)
        elif t is str:
            if len(x) > 512:
                return 'input_cap'
        elif not (t is int or t is bool or x is None):
            return 'malformed'
    return None


def _agp_surface_check(s):
    ceil = {'max_source_chars': 512, 'max_tokens': 40, 'max_case_groups': 8,
            'max_markers': 64, 'max_role_candidates': 64, 'max_search_steps': 4096,
            'max_json_nodes': 2048, 'max_output_bytes': 65536}
    lim = s['limits']
    for k, c in ceil.items():
        if type(lim.get(k)) is not int or not 1 <= lim[k] <= c:
            return 'malformed', 'limits.' + k
    if not _agp_name(s['surface_id']):
        return 'malformed', 'surface_id'
    b = s['boundary']
    if b['kind'] != 'final_token_case_groups_v1':
        return 'unsupported_boundary', 'boundary.kind'
    if b['token_separator'] != 'unicode_whitespace_v1':
        return 'unsupported_tokenizer', 'boundary.token_separator'
    for k in ('terminators', 'question_marks', 'clause_separators'):
        g = _agp_strs(b[k], 'boundary.' + k, 64, True, True)
        if g:
            return g
    for k in ('excluded_final_forms', 'excluded_final_suffixes'):
        g = _agp_strs(b[k], 'boundary.' + k, 64, False, False)
        if g:
            return g
    g = _agp_strs(s['known_action_surfaces'], 'known_action_surfaces', 64, False, False)
    if g:
        return g
    if s['coreference_policy'] != 'exact_raw_value_v1':
        return 'unsupported_coreference_policy', 'coreference_policy'
    groups = s['case_groups']
    if len(groups) > min(8, lim['max_case_groups']):
        return 'input_cap', 'case_groups'
    ids, total = set(), 0
    for i, g in enumerate(groups):
        p = 'case_groups.%d' % i
        if not _agp_name(g['id']) or g['id'] in ids:
            return 'malformed', p + '.id'
        ids.add(g['id'])
        r = _agp_strs(g['markers'], p + '.markers', 64, True, False)
        if r:
            return r
        total += len(g['markers'])
    if total > min(64, lim['max_markers']):
        return 'input_cap', 'case_groups'
    roles = s['roles']
    if len(roles) != len(groups):
        return 'malformed', 'roles'
    cgs, slots = set(), set()
    for i, r in enumerate(roles):
        p = 'roles.%d' % i
        if not _agp_name(r['case_group']) or r['case_group'] in cgs:
            return 'malformed', p + '.case_group'
        if not _agp_name(r['slot']) or r['slot'] in slots:
            return 'malformed', p + '.slot'
        if not _agp_name(r['type_ref']):
            return 'malformed', p + '.type_ref'
        if type(r['presence']) is not str or r['presence'] not in ('required', 'optional'):
            return 'malformed', p + '.presence'
        if r['coreference_group'] is not None and not _agp_name(r['coreference_group']):
            return 'malformed', p + '.coreference_group'
        cgs.add(r['case_group'])
        slots.add(r['slot'])
    if cgs != ids:
        return 'malformed', 'roles'
    return None


def _agp_surface(p, node):
    _agp_node(p, node, 'action-surface')
    sid = _agp_field(p, node, 'surface-id')
    bn = _agp_node(p, p.link(node, 'boundary'), 'action-boundary')
    bnd = {'kind': _agp_field(p, bn, 'kind'),
           'token_separator': _agp_field(p, bn, 'token-separator')}
    for rel in ('terminators', 'question-marks', 'clause-separators',
                'excluded-final-forms', 'excluded-final-suffixes'):
        bnd[rel.replace('-', '_')] = [v[0] for v in _agp_scalars(p, p.link(bn, rel))]
    gn = p.link(node, 'case-groups')
    groups, gmaps, gnode = [], [], {}
    for item in p.sequence(gn, {'action-case-group'}):
        gid = _agp_field(p, item, 'id')
        mn = p.link(item, 'markers')
        groups.append({'id': gid, 'markers': [v[0] for v in _agp_scalars(p, mn)]})
        gmaps.append({'id': gid, 'node_id': _agp_id(p, item), 'markers_node_id': _agp_id(p, mn)})
        gnode[item] = gid
    roles, rmaps = [], []
    for item in p.sequence(p.link(node, 'roles'), {'action-surface-role'}):
        cg = p.link(item, 'case-group')
        if cg not in gnode:
            raise _agp_gap('role case-group is not an included group', 'dangling_ref')
        tn = p.link(item, 'type-ref')
        _agp_node(p, tn, 'action-type')
        tname = _agp_field(p, tn, 'name')
        if type(tname) is not str or not tname.strip():
            raise _agp_gap('action-type name is blank', 'invalid_type_ref')
        slot = _agp_field(p, item, 'slot')
        roles.append({'case_group': gnode[cg], 'slot': slot, 'type_ref': _agp_id(p, tn),
                      'presence': _agp_field(p, item, 'presence'),
                      'coreference_group': _agp_field(p, item, 'coreference-group')})
        rmaps.append({'slot': slot, 'node_id': _agp_id(p, item),
                      'case_group_node_id': _agp_id(p, cg), 'type_node_id': _agp_id(p, tn)})
    known = [v[0] for v in _agp_scalars(p, p.link(node, 'known-action-surfaces'))]
    coref = _agp_field(p, node, 'coreference-policy')
    ln = _agp_node(p, p.link(node, 'limits'), 'action-surface-limits')
    ceil = {'max_source_chars': 512, 'max_tokens': 40, 'max_case_groups': 8,
            'max_markers': 64, 'max_role_candidates': 64, 'max_search_steps': 4096,
            'max_json_nodes': 2048, 'max_output_bytes': 65536}
    limits = _agp_ints(p, ln, ('max-source-chars', 'max-tokens', 'max-case-groups',
                               'max-markers', 'max-role-candidates', 'max-search-steps',
                               'max-json-nodes', 'max-output-bytes'), ceil)
    surface = {'schema': 'unknown-action-surface-v1', 'surface_id': sid, 'boundary': bnd,
               'case_groups': groups, 'roles': roles, 'known_action_surfaces': known,
               'coreference_policy': coref, 'limits': limits}
    bad = _agp_surface_check(surface)
    if bad:
        raise _agp_gap('invalid action surface at %s' % bad[1], 'action_surface_' + bad[0])
    if _agp_scan(surface, limits['max_json_nodes']):
        raise _agp_gap('action surface exceeds declared json nodes', 'action_surface_input_cap')
    smap = {'node_id': _agp_id(p, node), 'boundary_node_id': _agp_id(p, bn),
            'limits_node_id': _agp_id(p, ln), 'case_groups': gmaps, 'roles': rmaps}
    return surface, smap


def _agp_refs(p, seq):
    out = []
    for item in p.sequence(seq, {'action-sense-ref'}):
        tn = p.link(item, 'target')
        if p.op(tn) != 'sense':
            raise _agp_gap('sense ref target is not op=sense', 'unknown_op')
        rec = p.node(tn)
        name = rec['name']
        if rec['layer'] != '공통층' or not name or name.startswith('$'):
            raise _agp_gap('invalid selected sense', 'invalid_sense_ref')
        out.append((name, _agp_id(p, item), rec['id']))
    return out


def _agp_policy(p, node, slots, max_terms):
    _agp_node(p, node, 'action-policy')
    pid = _agp_field(p, node, 'policy-id')
    if type(pid) is not str or not pid.strip() or len(pid) > 128:
        raise _agp_gap('invalid policy id', 'invalid_policy')
    an = _agp_node(p, p.link(node, 'association'), 'action-association')
    refs = _agp_refs(p, p.link(an, 'functional-predicates'))
    names = [r[0] for r in refs]
    if not 1 <= len(names) <= 64 or len(set(names)) != len(names):
        raise _agp_gap('invalid functional predicates', 'invalid_policy')
    assoc = {'mode': _agp_field(p, an, 'mode'), 'key_slot': _agp_field(p, an, 'key-slot'),
             'functional_predicates': names,
             'before_selection': _agp_field(p, an, 'before-selection'),
             'after_selection': _agp_field(p, an, 'after-selection'),
             'causal_status': _agp_field(p, an, 'causal-status')}
    if (assoc['mode'] != 'pending_role_functional_key_v1'
            or assoc['before_selection'] != 'latest_prior_independent_positive_v1'
            or assoc['after_selection'] != 'latest_later_independent_positive_v1'
            or assoc['causal_status'] != 'association_assumed_v1'):
        raise _agp_gap('unsupported association', 'unsupported_scope')
    if type(assoc['key_slot']) is not str or assoc['key_slot'] not in slots:
        raise _agp_gap('key slot is not a surface slot', 'invalid_policy')
    world = _agp_field(p, node, 'world')
    if _agp_refs(p, p.link(node, 'closed-predicates')) or world != 'open':
        raise _agp_gap('only open world is supported', 'unsupported_scope')
    evidence = [v[0] for v in _agp_scalars(p, p.link(node, 'evidence-kinds'))]
    if evidence != ['archived_positive_fact_v1']:
        raise _agp_gap('unsupported evidence kinds', 'unsupported_scope')
    counts = [v[0] for v in _agp_scalars(p, p.link(node, 'allowed-term-counts'))]
    if (not counts or len(set(counts)) != len(counts)
            or any(type(c) is not int or c not in (1, 2) or c > max_terms for c in counts)):
        raise _agp_gap('invalid allowed term counts', 'invalid_policy')
    repeated = _agp_field(p, node, 'allow-repeated-terms')
    if type(repeated) is not bool:
        raise _agp_gap('allow-repeated-terms must be bool', 'invalid_policy')
    ranking, rmaps, seen = [], [], set()
    for item in p.sequence(p.link(node, 'ranking'), {'action-rank'}):
        key = _agp_field(p, item, 'key')
        direction = _agp_field(p, item, 'direction')
        if (type(key) is not str or key not in ('support_count', 'conflict_count', 'term_count')
                or key in seen or type(direction) is not str or direction not in ('asc', 'desc')):
            raise _agp_gap('invalid ranking entry', 'invalid_policy')
        seen.add(key)
        ranking.append({'key': key, 'direction': direction})
        rmaps.append({'key': key, 'node_id': _agp_id(p, item)})
    ln = _agp_node(p, p.link(node, 'limits'), 'action-policy-limits')
    ceil = {'max_candidates': 64, 'max_observations': 64, 'max_window_turns': 128,
            'max_pending': 16, 'max_effect_triples': 128, 'max_output_bytes': 262144}
    limits = _agp_ints(p, ln, ('max-candidates', 'max-observations', 'max-window-turns',
                               'max-pending', 'max-effect-triples', 'max-output-bytes'), ceil)
    policy = {'schema': 'contextual-action-policy-v1', 'policy_id': pid, 'association': assoc,
              'world': world, 'closed_predicates': [], 'evidence_kinds': evidence,
              'allowed_term_counts': counts, 'allow_repeated_terms': repeated,
              'ranking': ranking, 'limits': limits}
    pmap = {'node_id': _agp_id(p, node), 'association_node_id': _agp_id(p, an),
            'limits_node_id': _agp_id(p, ln),
            'functional_predicates': [{'name': r[0], 'ref_node_id': r[1], 'sense_node_id': r[2]}
                                      for r in refs],
            'ranking': rmaps}
    return policy, pmap


def _agp_replies(p, node):
    import string
    leading = ('leading_candidates', 'leading_count', 'leading_support_count',
               'leading_conflict_count', 'leading_contrast_count', 'leading_unobserved_count')
    allowed = {'conditional': ('expression', 'candidates', 'question') + leading,
               'clarify': ('expression', 'question', 'gaps') + leading,
               'question': ('expression', 'candidates', 'gaps') + leading,
               'observed_with_hypothesis': ('answer', 'hypothesis'),
               'gap': ()}
    out, maps, uses_gaps = {}, [], False
    for item in p.sequence(node, {'action-reply'}):
        key = _agp_field(p, item, 'key')
        tn = p.link(item, 'text')
        text = p.scalar(tn)
        if type(key) is not str or key not in allowed:
            raise _agp_gap('unknown reply key', 'invalid_reply')
        if key in out:
            raise _agp_gap('duplicate reply key', 'invalid_reply')
        if type(text) is not str or not text.strip() or len(text.encode('utf-8')) > 4096:
            raise _agp_gap('invalid reply text', 'invalid_reply')
        try:
            parsed = list(string.Formatter().parse(text))
        except ValueError as exc:
            raise _agp_gap('malformed reply template', 'invalid_reply') from exc
        count = 0
        for _lit, field, spec, conv in parsed:
            if field is None:
                continue
            count += 1
            if count > 64 or field not in allowed[key] or conv is not None or spec != '':
                raise _agp_gap('invalid reply placeholder', 'invalid_reply')
            if field == 'gaps':
                uses_gaps = True
        out[key] = text
        maps.append({'key': key, 'node_id': _agp_id(p, item), 'text_node_id': _agp_id(p, tn)})
    for req in ('conditional', 'clarify', 'question'):
        if req not in out:
            raise _agp_gap('missing required reply', 'invalid_reply')
    if uses_gaps and 'gap' not in out:
        raise _agp_gap('gap reply is required', 'invalid_reply')
    return out, maps


def _agp_source(p, source):
    d = _source_descriptor(p, source)
    if d.get('status') != 'caller_supplied':
        raise _agp_gap('source descriptor is required', 'source_required')
    for k in ('member_path', 'member_sha256', 'base_content_sha256'):
        v = d.get(k)
        if type(v) is not str or not v:
            raise _agp_gap('source field %s is required' % k, 'source_required')
    try:
        gid = _ids.graph_id(d['member_path'])
    except TypeError as exc:
        raise _agp_gap('invalid source member path', 'invalid_source_descriptor') from exc
    if gid != p.graph_id:
        raise _agp_gap('source member does not match graph', 'source_identity_mismatch')
    return d


def _agp_build(p, gn, source):
    from marco.reasoning.actions import describe_action_catalog
    src = _agp_source(p, source)
    _agp_node(p, gn, 'action-grounding')
    cname = p.link(gn, 'catalog')
    sn = p.link(gn, 'surface')
    pn = p.link(gn, 'policy')
    rn = p.link(gn, 'replies')
    on = p.link(gn, 'required-operators')
    hn = p.link(gn, 'hypothesis-scope')
    cat = _action_catalog_projection(p, cname)
    ops = _agp_scalars(p, on)
    values = [o[0] for o in ops]
    if (len(values) != 2 or any(type(v) is not str for v in values) or len(set(values)) != 2
            or set(values) != {'relational_graph', 'contextual_action_hypothesis'}):
        raise _agp_gap('invalid required operators', 'invalid_capability_scope')
    if p.scalar(hn) != 'provisional_nonexecuting_v1':
        raise _agp_gap('unsupported hypothesis scope', 'unsupported_scope')
    surface, smap = _agp_surface(p, sn)
    policy, pmap = _agp_policy(p, pn, {r['slot'] for r in surface['roles']},
                               cat['limits']['max_candidate_terms'])
    replies, rmap = _agp_replies(p, rn)
    smaps = {'action_grounding': {'node_id': _agp_id(p, gn), 'catalog_node_id': _agp_id(p, cname),
                                  'surface_node_id': _agp_id(p, sn), 'policy_node_id': _agp_id(p, pn),
                                  'replies_node_id': _agp_id(p, rn),
                                  'required_operators_node_id': _agp_id(p, on),
                                  'hypothesis_scope_node_id': _agp_id(p, hn),
                                  'required_operators': [{'value': o[0], 'item_node_id': o[1],
                                                          'value_node_id': o[2]} for o in ops]},
             'catalog': cat['source_maps'], 'surface': smap, 'policy': pmap, 'replies': rmap}
    root_id = _agp_id(p, p.root)
    provenance = {'graph_id': p.graph_id, 'root_id': root_id,
                  'effective_graph_sha256': p.effective_graph_sha256,
                  'view_key': list(p.view_key), 'base_origin': deepcopy(p.base_origin),
                  'source': deepcopy(src), 'nodes': deepcopy(p._nodes),
                  'edges': deepcopy(p._edge_ids)}
    decl = {'catalog_id': cat['catalog_id'], 'limits': cat['limits'], 'programs': cat['programs']}
    pre = {'schema': 'graph-action-grounding-projection-v1', 'required_operators': values,
           'hypothesis_scope': 'provisional_nonexecuting_v1', 'catalog': decl,
           'surface': surface, 'policy': policy, 'replies': replies,
           'entry_labels': cat['entry_labels'], 'source_maps': smaps, 'provenance': provenance}
    fingerprint = _digest(pre)
    graph = {'graph_id': provenance['graph_id'], 'root_id': root_id,
             'effective_graph_sha256': provenance['effective_graph_sha256'],
             'view_key': list(provenance['view_key']),
             'base_origin': deepcopy(provenance['base_origin']),
             'source': deepcopy(src), 'projection_fingerprint': fingerprint}
    catalog = {'schema': 'nai-action-catalog-v1', 'catalog_id': cat['catalog_id'],
               'graph': graph, 'limits': cat['limits'], 'programs': cat['programs']}
    desc = describe_action_catalog(deepcopy(catalog))
    if (not isinstance(desc, dict) or desc.get('schema') != 'nai-action-catalog-footprint-v1'
            or desc.get('status') != 'described' or desc.get('gaps') != []
            or desc.get('claimed_identity') != {'catalog_id': catalog['catalog_id'],
                                                'graph': catalog['graph']}):
        raise _agp_gap('action catalog helper refused the catalog', 'action_catalog_helper_gap')
    return deepcopy({'schema': 'graph-action-grounding-projection-v1', 'catalog': catalog,
                     'surface': surface, 'policy': policy, 'replies': replies,
                     'required_operators': values,
                     'hypothesis_scope': 'provisional_nonexecuting_v1',
                     'entry_labels': cat['entry_labels'], 'source_maps': smaps,
                     'provenance': provenance, 'fingerprint': fingerprint,
                     'catalog_description': desc})


def project_action_grounding(view, graph_id, root, *, source=None):
    p = _Program(view, graph_id, root)
    gn = p.link(root, 'action-grounding', optional=True)
    if gn is None:
        return None
    try:
        return _agp_build(p, gn, source)
    except LanguageProjectionGap:
        raise
    except (TypeError, ValueError, KeyError, AttributeError, UnicodeError,
            OverflowError, RecursionError) as exc:
        raise LanguageProjectionGap('action grounding projection failed',
                                    'action_grounding_malformed') from exc


_AGL_PARENT_KEYS = ('schema', 'catalog', 'surface', 'policy', 'replies', 'required_operators',
                    'hypothesis_scope', 'entry_labels', 'source_maps', 'provenance',
                    'fingerprint', 'catalog_description')
_AGL_FIXED = (
    ('admission_operator', 'admission', 'explicit_user_lexical_action_confirmation_v1'),
    ('meaning_scope', 'meaning-scope', 'surface_role_pattern_to_exhaustive_ordered_known_programs_v1'),
    ('evidence_kind', 'evidence-kind', 'archived_dialogue_input_v1'),
    ('question_scope', 'question-scope', 'next_external_input_same_conversation_v1'),
    ('question_selection', 'question-selection', 'oldest_pending_rank_then_target_digest_v1'),
    ('retraction_scope', 'retraction-scope', 'unique_active_surface_role_pattern_v1'),
    ('active_use_scope', 'active-use-scope', 'conditional_nonexecuting_adjunct_v1'),
)
_AGL_CEIL = {'max_forms': 16, 'max_form_chars': 512, 'max_input_bytes': 32768,
             'max_question_bytes': 65536, 'max_target_bytes': 32768,
             'max_active_questions': 1, 'max_terms': 2, 'max_roles': 64,
             'max_archive_bytes': 16777216, 'max_archive_events': 65536}
_AGL_LIMIT_RELS = tuple(k.replace('_', '-') for k in _AGL_CEIL)
_AGL_TEMPLATES = {
    'question': ('expression', 'role_pattern', 'meaning'),
    'role': ('slot_label', 'markers'),
    'term': ('ordinal', 'program', 'bindings'),
    'binding': ('program_role_label', 'surface_role_label'),
    'admitted': ('expression',),
    'denied': ('expression',),
    'stale': ('expression',),
    'withdrawn': ('expression',),
    'used': ('expression', 'role_pattern', 'meaning'),
    'gap': (),
    'question_with_answer': ('answer', 'question'),
}
_AGL_SEPARATORS = ('role_separator', 'term_separator', 'binding_separator', 'marker_separator')


def _agl_field(p, node, rel):
    tn = p.link(node, rel)
    return p.scalar(tn), _agp_id(p, tn)


def _agl_parents(p, view, graph_id, root, source, ap, lp):
    if (type(ap) is not dict or set(ap) != set(_AGL_PARENT_KEYS)
            or ap.get('schema') != 'graph-action-grounding-projection-v1'):
        raise _agp_gap('action projection is not the exact parent shape', 'learning_parent_invalid')
    src = source
    if src is None:
        s = ap['provenance'].get('source') if isinstance(ap.get('provenance'), Mapping) else None
        if not isinstance(s, Mapping):
            raise _agp_gap('action projection has no source', 'learning_parent_invalid')
        src = {k: v for k, v in s.items() if k != 'status'}
    rebuilt = project_action_grounding(view, graph_id, root, source=src)
    if rebuilt != ap:
        raise _agp_gap('action projection does not match the opened view', 'learning_parent_mismatch')
    if (type(lp) is not dict or lp.get('schema') != 'graph-dialogue-projection-v1'
            or type(lp.get('fingerprint')) is not str or not _SHA_RE.fullmatch(lp['fingerprint'])):
        raise _agp_gap('language projection is not a dialogue projection', 'learning_parent_invalid')
    lprov = lp.get('provenance')
    aprov = ap['provenance']
    if not isinstance(lprov, Mapping):
        raise _agp_gap('language projection lacks provenance', 'learning_parent_invalid')
    for k in ('graph_id', 'root_id', 'effective_graph_sha256', 'view_key', 'base_origin', 'source', 'nodes', 'edges'):
        if k not in lprov:
            raise _agp_gap('language projection provenance lacks %s' % k, 'learning_parent_invalid')
    if lprov['source'] != aprov['source']:
        raise _agp_gap('language projection source mismatch', 'learning_parent_mismatch')
    rebuilt_language = project_language_dialogue(view, graph_id, root, source=src)
    if rebuilt_language != lp:
        raise _agp_gap('language projection does not match the opened view', 'learning_parent_mismatch')


def _agl_limits(p, node, ap):
    if p.op(node) != 'action-learning-limits':
        raise _agp_gap('%r is not op=action-learning-limits' % node, 'unknown_op')
    lim = _agp_ints(p, node, _AGL_LIMIT_RELS, _AGL_CEIL)
    if lim['max_active_questions'] != 1:
        raise _agp_gap('max_active_questions must be 1', 'invalid_limit')
    if lim['max_terms'] > ap['catalog']['limits']['max_candidate_terms']:
        raise _agp_gap('max_terms exceeds catalog', 'invalid_limit')
    if lim['max_roles'] > len(ap['surface']['roles']):
        raise _agp_gap('max_roles exceeds surface roles', 'invalid_limit')
    ids = {rel.replace('-', '_'): _agp_id(p, p.link(node, rel)) for rel in _AGL_LIMIT_RELS}
    return lim, {'node_id': _agp_id(p, node), 'limit_node_ids': ids}


def _agl_forms(p, seq, lim):
    refs = p.sequence(seq, {'learning-control-ref'})
    if not 1 <= len(refs) <= lim['max_forms']:
        raise _agp_gap('form count out of range', 'cap_overflow')
    rows, maps, seen = [], [], set()
    for ref in refs:
        if p.op(ref) != 'learning-control-ref':
            raise _agp_gap('item %r is not a control ref' % ref, 'unsupported_shape')
        name = p.link(ref, 'target')
        if p.op(name) != 'learning-control':
            raise _agp_gap('%r is not op=learning-control' % name, 'unknown_op')
        for rel, _dst in p._program_edges(name):
            if rel in ('expression-kind', 'capture-terminals'):
                raise _agp_gap('control %r declares a forbidden relation' % name, 'invalid_binding')
        fid = _agp_id(p, name)
        if fid in seen:
            raise _agp_gap('duplicate form id', 'duplicate_ref')
        seen.add(fid)
        kind, kind_id = _agl_field(p, name, 'kind')
        prefix, prefix_id = _agl_field(p, name, 'ownership-prefix')
        text, text_id = _agl_field(p, name, 'text')
        if type(kind) is not str or kind not in ('affirm', 'deny', 'withdraw'):
            raise _agp_gap('unsupported control kind', 'invalid_binding')
        if type(prefix) is not str or type(text) is not str or not text:
            raise _agp_gap('control needs string prefix and nonempty text', 'invalid_binding')
        if len(text) > lim['max_form_chars']:
            raise _agp_gap('control text too long', 'cap_overflow')
        if '\n' in text or '\r' in text:
            raise _agp_gap('control text has a line break', 'invalid_binding')
        slots, smaps = {}, []
        sn = p.link(name, 'slots')
        for item in p.sequence(sn, {'learning-slot'}):
            if p.op(item) != 'learning-slot':
                raise _agp_gap('item %r is not op=learning-slot' % item, 'unsupported_shape')
            role, role_id = _agl_field(p, item, 'role')
            seed, seed_id = _agl_field(p, item, 'seed')
            if type(role) is not str or type(seed) is not str:
                raise _agp_gap('slot needs string role and seed', 'invalid_binding')
            if role in slots or seed in slots.values():
                raise _agp_gap('slot repeats a role or seed', 'duplicate_ref')
            slots[role] = seed
            smaps.append({'role': role, 'seed': seed, 'item_node_id': _agp_id(p, item),
                          'role_node_id': role_id, 'seed_node_id': seed_id})
        if kind == 'withdraw':
            if 'expression' not in slots or set(slots) != {'expression'}:
                raise _agp_gap('withdraw needs the expression slot', 'invalid_binding')
        elif slots or prefix != text:
            raise _agp_gap('affirm/deny need no slots and prefix equal to text', 'invalid_binding')
        rows.append({'id': fid, 'kind': kind, 'ownership_prefix': prefix, 'text': text,
                     'slots': slots, 'wide_slots': list(slots)})
        maps.append({'id': fid, 'ref_node_id': _agp_id(p, ref), 'node_id': fid,
                     'kind_node_id': kind_id, 'prefix_node_id': prefix_id,
                     'text_node_id': text_id, 'slots_node_id': _agp_id(p, sn), 'slots': smaps})
    if {r['kind'] for r in rows} != {'affirm', 'deny', 'withdraw'}:
        raise _agp_gap('each control kind is required', 'invalid_binding')
    forms = {'schema': 'selected-action-meaning-controls-v1', 'forms': rows}
    from marco.language.teaching import validate_action_meaning_forms
    try:
        validate_action_meaning_forms(None, deepcopy(forms))
    except (ValueError, TypeError, AttributeError, KeyError) as exc:
        raise _agp_gap('control forms are invalid: %s' % exc, 'invalid_binding') from exc
    return forms, maps


def _agl_render(p, seq):
    import string
    out, maps = {}, []
    for item in p.sequence(seq, {'action-reply'}):
        key, _kid = _agl_field(p, item, 'key')
        tn = p.link(item, 'text')
        text = p.scalar(tn)
        if type(key) is not str or (key not in _AGL_TEMPLATES and key not in _AGL_SEPARATORS):
            raise _agp_gap('unknown render key', 'invalid_reply')
        if key in out:
            raise _agp_gap('duplicate render key', 'invalid_reply')
        if type(text) is not str:
            raise _agp_gap('invalid render text', 'invalid_reply')
        size = len(text.encode('utf-8'))
        if key in _AGL_SEPARATORS:
            if not text or size > 64:
                raise _agp_gap('invalid separator', 'invalid_reply')
            required = ()
        else:
            if not text.strip() or size > 4096:
                raise _agp_gap('invalid render template', 'invalid_reply')
            required = _AGL_TEMPLATES[key]
        try:
            parsed = list(string.Formatter().parse(text))
        except ValueError as exc:
            raise _agp_gap('malformed render template', 'invalid_reply') from exc
        fields = []
        for _lit, field, spec, conv in parsed:
            if field is None:
                continue
            if conv is not None or spec != '':
                raise _agp_gap('invalid render placeholder', 'invalid_reply')
            fields.append(field)
        if sorted(fields) != sorted(required):
            raise _agp_gap('render placeholders do not match', 'invalid_reply')
        out[key] = text
        maps.append({'key': key, 'key_node_id': _kid, 'node_id': _agp_id(p, item),
                     'text_node_id': _agp_id(p, tn)})
    if set(out) != set(_AGL_TEMPLATES) | set(_AGL_SEPARATORS):
        raise _agp_gap('render keys are not exact', 'invalid_reply')
    return out, maps


def _agl_labels(p, seq, ap):
    wanted = [r['slot'] for r in ap['surface']['roles']]
    labels, maps = {}, []
    for item in p.sequence(seq, {'action-learning-role-label'}):
        if p.op(item) != 'action-learning-role-label':
            raise _agp_gap('item %r is not a role label' % item, 'unsupported_shape')
        slot, slot_id = _agl_field(p, item, 'slot')
        label, label_id = _agl_field(p, item, 'label')
        if type(slot) is not str or slot in labels or slot not in wanted:
            raise _agp_gap('role label slot is invalid or repeated', 'invalid_binding')
        if not _agp_name(label):
            raise _agp_gap('role label is invalid', 'invalid_binding')
        labels[slot] = label
        maps.append({'slot': slot, 'node_id': _agp_id(p, item), 'slot_node_id': slot_id,
                     'label_node_id': label_id})
    if set(labels) != set(wanted):
        raise _agp_gap('role labels do not cover every surface slot', 'invalid_binding')
    return labels, maps


def _agl_build(p, view, graph_id, root, gn, ln, source, ap, lp):
    _agl_parents(p, view, graph_id, root, source, ap, lp)
    _agp_node(p, ln, 'action-learning')
    pid, pid_node = _agl_field(p, ln, 'policy-id')
    if not _agp_name(pid):
        raise _agp_gap('invalid policy id', 'learning_policy_invalid')
    policy = {'schema': 'lexical-action-learning-policy-v1', 'policy_id': pid}
    pmap = {'policy_id': pid_node}
    for key, rel, expected in _AGL_FIXED:
        value, nid = _agl_field(p, ln, rel)
        if type(value) is not str or value != expected:
            raise _agp_gap('unsupported learning policy field %s' % key, 'learning_policy_invalid')
        policy[key] = value
        pmap[key] = nid
    limits, lmap = _agl_limits(p, p.link(ln, 'limits'), ap)
    policy['limits'] = limits
    forms, fmaps = _agl_forms(p, p.link(ln, 'forms'), limits)
    render, rmaps = _agl_render(p, p.link(ln, 'renders'))
    labels, lbmaps = _agl_labels(p, p.link(ln, 'role-labels'), ap)
    smaps = {'anchor': {'action_grounding_node_id': _agp_id(p, gn), 'learning_node_id': _agp_id(p, ln)},
             'policy': pmap, 'limits': lmap, 'forms': fmaps, 'render': rmaps,
             'role_labels': lbmaps}
    provenance = {'graph_id': p.graph_id, 'root_id': _agp_id(p, p.root),
                  'effective_graph_sha256': p.effective_graph_sha256,
                  'view_key': list(p.view_key), 'base_origin': deepcopy(p.base_origin),
                  'source': deepcopy(ap['provenance']['source']),
                  'nodes': deepcopy(p._nodes), 'edges': deepcopy(p._edge_ids)}
    pre = {'schema': 'graph-action-learning-projection-v1', 'policy': policy, 'forms': forms,
           'render': render, 'role_labels': labels, 'source_maps': smaps,
           'provenance': provenance, 'parent_action_fingerprint': ap['fingerprint'],
           'language_projection_fingerprint': lp['fingerprint']}
    out = dict(pre)
    out['fingerprint'] = _digest(pre)
    return deepcopy(out)


def project_action_learning(view, graph_id, root, *, source=None, action_projection, language_projection):
    p = _Program(view, graph_id, root)
    gn = p.link(root, 'action-grounding', optional=True)
    if gn is None:
        return None
    try:
        _agp_node(p, gn, 'action-grounding')
        ln = p.link(gn, 'learning', optional=True)
        if ln is None:
            return None
        return _agl_build(p, view, graph_id, root, gn, ln, source,
                          action_projection, language_projection)
    except LanguageProjectionGap:
        raise
    except (TypeError, ValueError, KeyError, AttributeError, UnicodeError,
            OverflowError, RecursionError) as exc:
        raise LanguageProjectionGap('action learning projection failed',
                                    'action_learning_malformed') from exc
