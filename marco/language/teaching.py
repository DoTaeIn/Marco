"""Selected learning-control reader: private pure L1 unit."""

import copy
import hashlib
import json

_SCHEMA = "selected-learning-dialogue-v1"
_FORM_KEYS = {"id", "kind", "ownership_prefix", "text", "slots", "wide_slots"}
_KIND_ROLES = {
    "equivalence": ("expression", "reference"),
    "positive": ("expression", "reference"),
    "unrecognized": ("expression",),
    "approve": (),
}
_STOPS = ".!?\n"
_QUERY_SCHEMA = "selected-learning-dialogue-v2"
_QUERY_KIND = "query"
_QUERY_FORM_KEYS = _FORM_KEYS | {"expression_kind", "capture_terminals"}
_QUERY_INPUT_BYTES = 32768
_QUERY_MAX_TERMINALS = 16
_AM_SCHEMA = "selected-action-meaning-controls-v1"
_AM_DECL_KEYS = {"schema", "forms"}
_AM_KINDS = {"affirm": (), "deny": (), "withdraw": ("expression",)}
_AM_MAX_FORMS = 16
_AM_MAX_FORM_CHARS = 512
_AM_MAX_INPUT_BYTES = 32768
_AM_MAX_DEPTH = 6


def _declaration(parser):
    data = getattr(parser, "data", None)
    if not isinstance(data, dict):
        return None
    return data.get("learning_dialogue")


def _hash(decl):
    blob = json.dumps(decl, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=repr)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _layout(form):
    """Return (slot list [(start,end,role)] sorted, text); ValueError if unproven."""
    text = form.get("text")
    prefix = form.get("ownership_prefix")
    slots = form.get("slots")
    if not isinstance(text, str) or not text or not isinstance(prefix, str) or not prefix:
        raise ValueError("bad_text_or_prefix")
    if not isinstance(slots, dict):
        raise ValueError("bad_slots")
    spans = []
    for role, lit in slots.items():
        if not isinstance(role, str) or not isinstance(lit, str) or not lit:
            raise ValueError("bad_slot_literal")
        pos = text.find(lit)
        if pos < 0 or text.find(lit, pos + 1) >= 0:
            raise ValueError("slot_literal_not_unique")
        spans.append((pos, pos + len(lit), role))
    spans.sort()
    for a, b in zip(spans, spans[1:]):
        if a[1] > b[0]:
            raise ValueError("slot_overlap")
    first = spans[0][0] if spans else len(text)
    if text[:first] != prefix:
        raise ValueError("prefix_mismatch")
    return spans, text


def _delims(form):
    spans, text = _layout(form)
    out = {}
    for s, e, role in spans:
        if s == 0 or e >= len(text):
            raise ValueError("slot_not_enclosed")
        left, right = text[s - 1], text[e]
        for other in spans:
            if other[2] != role and (other[0] <= s - 1 < other[1] or other[0] <= e < other[1]):
                raise ValueError("slot_delimiter_not_fixed")
        if any(c.isspace() or c in _STOPS for c in (left, right)):
            raise ValueError("bad_delimiter")
        lit = text[s:e]
        if left in lit or right in lit or any(c in lit for c in _STOPS):
            raise ValueError("bad_slot_content")
        out[role] = (left, right)
    return out


def _query_marks(parser):
    grammar = getattr(parser, "clause_grammar", None)
    try:
        marks = grammar["question_marks"]
    except (TypeError, KeyError, IndexError):
        raise ValueError("bad_question_marks")
    if not isinstance(marks, (list, tuple)) or not marks or len(marks) > _QUERY_MAX_TERMINALS:
        raise ValueError("bad_question_marks")
    if any(not isinstance(m, str) or len(m) != 1 or m.isspace() or m.isalnum() for m in marks):
        raise ValueError("bad_question_marks")
    if len(set(marks)) != len(marks):
        raise ValueError("bad_question_marks")
    return tuple(marks)
def _query_delims(form, terminals):
    """Query-only delimiter proof over the original layout; declared terminals may sit inside seeds."""
    spans, text = _layout(form)
    out = {}
    for s, e, role in spans:
        if s == 0 or e >= len(text):
            raise ValueError("slot_not_enclosed")
        left, right = text[s - 1], text[e]
        for other in spans:
            if other[2] != role and (other[0] <= s - 1 < other[1] or other[0] <= e < other[1]):
                raise ValueError("slot_delimiter_not_fixed")
        if any(c.isspace() or c in _STOPS for c in (left, right)):
            raise ValueError("bad_delimiter")
        lit = text[s:e]
        if left in lit or right in lit or any(c in lit and c not in terminals for c in _STOPS):
            raise ValueError("bad_slot_content")
        out[role] = (left, right)
    return out
def _query_form(form, marks):
    if not isinstance(form, dict) or set(form) != _QUERY_FORM_KEYS or form["expression_kind"] != _QUERY_KIND:
        raise ValueError("bad_form_fields")
    if not isinstance(form["id"], str) or not form["id"]:
        raise ValueError("bad_id")
    kind = form["kind"]
    if not isinstance(kind, str) or kind not in _KIND_ROLES:
        raise ValueError("bad_kind")
    slots = form["slots"]
    if not isinstance(slots, dict) or set(slots) != set(_KIND_ROLES[kind]):
        raise ValueError("bad_slot_roles")
    wide = form["wide_slots"]
    if (not isinstance(wide, list) or any(not isinstance(member, str) for member in wide)
            or len(wide) != len(set(map(repr, wide))) or set(wide) != set(slots)):
        raise ValueError("bad_wide_slots")
    terminals = form["capture_terminals"]
    if (not isinstance(terminals, list) or len(terminals) > _QUERY_MAX_TERMINALS
            or any(not isinstance(c, str) or len(c) != 1 or c.isspace() or c.isalnum() for c in terminals)
            or len(set(terminals)) != len(terminals)):
        raise ValueError("bad_capture_terminals")
    if marks is not None and any(c not in marks for c in terminals):
        raise ValueError("bad_capture_terminals")
    text = form["text"]
    if not isinstance(text, str) or "\r" in text or "\n" in text or len(text) > 512:
        raise ValueError("bad_query_text")
    if any(not isinstance(lit, str) or lit.isdecimal() or "\r" in lit or "\n" in lit for lit in slots.values()):
        raise ValueError("bad_query_seed")
    spans, text = _layout(form)
    if kind == "approve" and form["ownership_prefix"] != text:
        raise ValueError("prefix_mismatch")
    return _query_delims(form, tuple(terminals))
def _query_sha(form):
    blob = json.dumps(form, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
def _query_evidence(source, decl, captures, fixed, status):
    try:
        blob = json.dumps(decl, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(blob.encode("utf-8")).hexdigest()
    except (TypeError, ValueError, RecursionError):
        digest = None
    return {
        "source": source,
        "start": 0,
        "end": len(source),
        "capture_spans": captures,
        "fixed_spans": fixed,
        "coverage_status": status,
        "declaration_source": "parser.data.learning_dialogue",
        "declaration_sha256": digest,
        "model_binding": None,
        "binding_status": "partial",
        "binding_reason": "parser_model_binding_unavailable",
        "expression_kind": _QUERY_KIND,
    }
def _query_hold(source, decl, reason, form=None):
    evidence = _query_evidence(source, decl, {}, [], "unproven")
    evidence["form_sha256"] = _query_sha(form) if form is not None else None
    return {"kind": "hold", "reason": reason, "evidence": evidence, "expression_kind": _QUERY_KIND}
def _check_form(form):
    if isinstance(form, dict) and "expression_kind" in form:
        return _query_form(form, None)
    if not isinstance(form, dict) or set(form) != _FORM_KEYS:
        raise ValueError("bad_form_fields")
    if not isinstance(form["id"], str) or not form["id"]:
        raise ValueError("bad_id")
    kind = form["kind"]
    if not isinstance(kind, str) or kind not in _KIND_ROLES:
        raise ValueError("bad_kind")
    slots = form["slots"]
    if not isinstance(slots, dict) or set(slots) != set(_KIND_ROLES[kind]):
        raise ValueError("bad_slot_roles")
    wide = form["wide_slots"]
    if (not isinstance(wide, list) or any(not isinstance(member, str) for member in wide)
            or len(wide) != len(set(map(repr, wide))) or set(wide) != set(slots)):
        raise ValueError("bad_wide_slots")
    if not kind == "approve" or True:
        spans, text = _layout(form)
        if kind == "approve" and form["ownership_prefix"] != text:
            raise ValueError("prefix_mismatch")
    return _delims(form)


def validate_learning_forms(parser):
    decl = _declaration(parser)
    if decl is None:
        return None
    if (not isinstance(decl, dict) or set(decl) != {"schema", "forms"}
            or decl["schema"] not in (_SCHEMA, _QUERY_SCHEMA)):
        raise ValueError("bad_declaration")
    forms = decl["forms"]
    if not isinstance(forms, list) or not forms:
        raise ValueError("bad_forms")
    v2 = decl["schema"] == _QUERY_SCHEMA
    marks = _query_marks(parser) if v2 else None
    if v2:
        if len(forms) > 16:
            raise ValueError("bad_forms")
        try:
            blob = json.dumps(decl, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        except (TypeError, RecursionError):
            raise ValueError("bad_declaration")
        if len(blob.encode("utf-8")) > 65536:
            raise ValueError("bad_declaration")
    seen = set()
    queries = 0
    for form in forms:
        query = isinstance(form, dict) and "expression_kind" in form
        if query and not v2:
            raise ValueError("bad_form_fields")
        _check_form(form)
        if v2 and len(form["text"]) > 512:
            raise ValueError("bad_query_text")
        if query:
            _query_form(form, marks)
            queries += 1
        if form["id"] in seen:
            raise ValueError("duplicate_id")
        seen.add(form["id"])
    if v2 and not queries:
        raise ValueError("bad_declaration")
    return copy.deepcopy(decl)


def _proved_prefix(form):
    if not isinstance(form, dict):
        return None
    try:
        _layout(form)
    except (ValueError, AttributeError, TypeError):
        return None
    return form["ownership_prefix"]


def _evidence(source, decl, captures, fixed, status):
    return {
        "source": source,
        "start": 0,
        "end": len(source),
        "capture_spans": captures,
        "fixed_spans": fixed,
        "coverage_status": status,
        "declaration_source": "parser.data.learning_dialogue",
        "declaration_sha256": _hash(decl),
        "model_binding": None,
        "binding_status": "partial",
        "binding_reason": "parser_model_binding_unavailable",
    }


def _hold(source, decl, reason):
    return {"kind": "hold", "reason": reason, "evidence": _evidence(source, decl, {}, [], "unproven")}


def _hits(parser, form, source, stripped, offset):
    """Return (valid hits dict key->(captures), saw_match)."""
    query = form.get("expression_kind") == _QUERY_KIND
    delims = _query_form(form, _query_marks(parser)) if query else _delims(form)
    example = copy.deepcopy(form)
    example["meaning"] = {"learning_control": form["kind"]}
    stops = _STOPS
    if query:
        terminals = tuple(form["capture_terminals"])
        stops = "".join(c for c in _STOPS if c not in terminals) + "\r"
        patterns, _ = parser.compile(example, capture_terminals=terminals)
    else:
        patterns, _ = parser.compile(example)
    hits = {}
    saw = False
    for pat in patterns:
        m = pat.fullmatch(stripped)
        if m is None:
            continue
        saw = True
        caps = {}
        ok = True
        for role, (left, right) in delims.items():
            if role not in pat.groupindex:
                ok = False
                break
            s, e = m.span(role)
            s += offset
            e += offset
            val = source[s:e]
            if (not val or any(c in val for c in stops) or left in val or right in val
                    or s < 1 or e >= len(source) or source[s - 1] != left or source[e] != right):
                ok = False
                break
            caps[role] = {"start": s, "end": e, "text": val}
        if ok:
            key = (form["id"], form["kind"], tuple(sorted((r, c["start"], c["end"]) for r, c in caps.items())))
            hits[key] = caps
    return hits, saw


def read_learning_control(parser, text):
    decl = _declaration(parser)
    if decl is None or not isinstance(text, str):
        return None
    forms = decl.get("forms") if isinstance(decl, dict) else None
    if not isinstance(forms, list):
        return None
    stripped = text.strip()
    offset = len(text) - len(text.lstrip())
    owned = False
    for form in forms:
        prefix = _proved_prefix(form)
        if prefix is not None and stripped.startswith(prefix):
            owned = True
            break
    if not owned:
        return None
    v2 = decl.get("schema") == _QUERY_SCHEMA
    selected = None

    def fail(reason):
        return _query_hold(text, decl, reason, selected) if v2 else _hold(text, decl, reason)
    if v2:
        try:
            oversize = len(text.encode("utf-8")) > _QUERY_INPUT_BYTES
        except UnicodeEncodeError:
            oversize = True
        if oversize:
            return fail("invalid_capture")
        if "\r" in text or "\n" in text:
            return fail("newline_unsupported")
    elif "\n" in text:
        return _hold(text, decl, "newline_unsupported")
    try:
        validate_learning_forms(parser)
    except ValueError:
        return fail("invalid_configuration")
    candidates = [f for f in forms if stripped.startswith(f["ownership_prefix"])]
    if v2 and len(candidates) == 1 and candidates[0].get("expression_kind") == _QUERY_KIND:
        selected = candidates[0]
    hits = {}
    saw = False
    matched = {}
    try:
        for form in forms:
            if not stripped.startswith(form["ownership_prefix"]):
                continue
            h, s = _hits(parser, form, text, stripped, offset)
            hits.update(h)
            for key in h:
                matched[key] = form
            saw = saw or s
    except Exception:
        return fail("compile_failed")
    if len(hits) > 1:
        return fail("ambiguous")
    if not hits:
        return fail("invalid_capture" if saw else "no_match")
    (fid, kind, _), caps = next(iter(hits.items()))
    fixed = []
    pos = 0
    for role, c in sorted(caps.items(), key=lambda kv: kv[1]["start"]):
        if c["start"] > pos:
            fixed.append({"start": pos, "end": c["start"], "text": text[pos:c["start"]]})
        pos = c["end"]
    if pos < len(text):
        fixed.append({"start": pos, "end": len(text), "text": text[pos:]})
    winner = matched[(fid, kind, next(iter(hits)))[2]] if False else matched[next(iter(hits))]
    if v2 and winner.get("expression_kind") == _QUERY_KIND:
        return {
            "kind": kind,
            "fields": {role: c["text"] for role, c in caps.items()},
            "evidence": {**_query_evidence(text, decl, caps, fixed, "complete"), "form_id": fid,
                         "form_sha256": _query_sha(winner)},
            "expression_kind": _QUERY_KIND,
        }
    return {
        "kind": kind,
        "fields": {role: c["text"] for role, c in caps.items()},
        "evidence": {**_evidence(text, decl, caps, fixed, "complete"), "form_id": fid},
    }


def _am_strict(value, depth=0):
    if depth > _AM_MAX_DEPTH:
        raise ValueError("invalid_action_meaning_forms")
    if isinstance(value, str):
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("invalid_action_meaning_forms")
        return
    if isinstance(value, list):
        for member in value:
            _am_strict(member, depth + 1)
        return
    if isinstance(value, dict):
        for key, member in value.items():
            if not isinstance(key, str):
                raise ValueError("invalid_action_meaning_forms")
            _am_strict(key, depth + 1)
            _am_strict(member, depth + 1)
        return
    raise ValueError("invalid_action_meaning_forms")


def _am_sha(value):
    blob = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def validate_action_meaning_forms(parser, declaration):
    bad = ValueError("invalid_action_meaning_forms")
    try:
        if not isinstance(declaration, dict) or set(declaration) != _AM_DECL_KEYS:
            raise bad
        if declaration["schema"] != _AM_SCHEMA:
            raise bad
        forms = declaration["forms"]
        if not isinstance(forms, list) or not 1 <= len(forms) <= _AM_MAX_FORMS:
            raise bad
        _am_strict(declaration)
        seen = set()
        kinds = set()
        for form in forms:
            if not isinstance(form, dict) or set(form) != _FORM_KEYS:
                raise bad
            fid = form["id"]
            kind = form["kind"]
            text = form["text"]
            prefix = form["ownership_prefix"]
            if not isinstance(fid, str) or not fid or fid in seen:
                raise bad
            seen.add(fid)
            if not isinstance(kind, str) or kind not in _AM_KINDS:
                raise bad
            kinds.add(kind)
            if (not isinstance(text, str) or not text or len(text) > _AM_MAX_FORM_CHARS
                    or "\n" in text or "\r" in text or text != text.strip()):
                raise bad
            if not isinstance(prefix, str) or not prefix:
                raise bad
            roles = _AM_KINDS[kind]
            slots = form["slots"]
            wide = form["wide_slots"]
            if not isinstance(slots, dict) or set(slots) != set(roles):
                raise bad
            if not isinstance(wide, list) or wide != list(roles):
                raise bad
            if not roles:
                if prefix != text:
                    raise bad
            else:
                _layout(form)
                _delims(form)
        if kinds != set(_AM_KINDS):
            raise bad
        return copy.deepcopy(declaration)
    except ValueError:
        raise ValueError("invalid_action_meaning_forms")
    except (TypeError, AttributeError, KeyError, RecursionError):
        raise ValueError("invalid_action_meaning_forms")


def _am_evidence(source, caps, fixed, status, form, dsha):
    return {
        "source": source,
        "start": 0,
        "end": len(source),
        "capture_spans": caps,
        "fixed_spans": fixed,
        "coverage_status": status,
        "form_id": form["id"] if form is not None else None,
        "form_sha256": _am_sha(form) if form is not None else None,
        "declaration_sha256": dsha,
    }


def _am_hold(source, reason, dsha):
    return {"kind": "hold", "reason": reason,
            "evidence": _am_evidence(source, {}, [], "unproven", None, dsha)}


def read_action_meaning_control(parser, text, declaration):
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    offset = len(text) - len(text.lstrip())
    try:
        decl = validate_action_meaning_forms(parser, declaration)
        dsha = _am_sha(decl)
        valid = True
    except ValueError:
        decl = declaration
        dsha = None
        valid = False
    forms = decl.get("forms") if isinstance(decl, dict) else None
    if not isinstance(forms, list):
        return None
    owned = False
    for form in forms:
        if not isinstance(form, dict):
            continue
        prefix = form.get("ownership_prefix")
        if isinstance(prefix, str) and prefix and stripped.startswith(prefix):
            owned = True
            break
    if not owned:
        return None
    if not valid:
        return _am_hold(text, "invalid_configuration", None)
    try:
        oversize = len(text.encode("utf-8")) > _AM_MAX_INPUT_BYTES
    except UnicodeEncodeError:
        oversize = True
    if oversize:
        return _am_hold(text, "invalid_capture", dsha)
    if "\r" in text or "\n" in text:
        return _am_hold(text, "newline_unsupported", dsha)
    hits = {}
    matched = {}
    saw = False
    try:
        for form in forms:
            if not stripped.startswith(form["ownership_prefix"]):
                continue
            if form["kind"] in ("affirm", "deny"):
                if stripped == form["text"]:
                    key = (form["id"], form["kind"], ())
                    hits[key] = {}
                    matched[key] = form
                    saw = True
                continue
            h, s = _hits(parser, form, text, stripped, offset)
            for key, caps in h.items():
                hits[key] = caps
                matched[key] = form
            saw = saw or s
    except Exception:
        return _am_hold(text, "compile_failed", dsha)
    if len(hits) > 1:
        return _am_hold(text, "ambiguous", dsha)
    if not hits:
        return _am_hold(text, "invalid_capture" if saw else "no_match", dsha)
    key = next(iter(hits))
    caps = hits[key]
    form = matched[key]
    fixed = []
    if not caps:
        fixed.append({"start": 0, "end": len(text), "text": text})
    else:
        pos = 0
        for role, c in sorted(caps.items(), key=lambda kv: kv[1]["start"]):
            if c["start"] > pos:
                fixed.append({"start": pos, "end": c["start"], "text": text[pos:c["start"]]})
            pos = c["end"]
        if pos < len(text):
            fixed.append({"start": pos, "end": len(text), "text": text[pos:]})
    return {
        "kind": form["kind"],
        "fields": {role: c["text"] for role, c in caps.items()},
        "evidence": _am_evidence(text, caps, fixed, "complete", form, dsha),
    }


def _query_origin_canonical(origin):
    """Canonical strict UTF-8 bytes of one exact original query-control origin, else ValueError."""
    def bad():
        return ValueError("query_origin_invalid")

    def hexed(value, size):
        return type(value) is str and len(value) == size and all(c in "0123456789abcdef" for c in value)

    def name(value):
        return type(value) is str and value != ""

    def where(o):
        if type(o) is not dict:
            return False
        if set(o) == {"kind", "build_id"}:
            return o["kind"] == "base" and (o["build_id"] is None or type(o["build_id"]) is str)
        keys = {"kind", "change_id", "seq", "actor", "source", "approved_by", "approved_at", "candidate_id"}
        return (set(o) == keys and o["kind"] == "overlay" and name(o["change_id"])
                and type(o["seq"]) is int and o["seq"] >= 0
                and type(o["actor"]) is str and type(o["source"]) is str
                and all(o[k] is None or type(o[k]) is str for k in ("approved_by", "approved_at", "candidate_id")))

    if (type(origin) is not dict or set(origin) != {"projection_fingerprint", "control_index", "control_source"}
            or not hexed(origin["projection_fingerprint"], 64)
            or type(origin["control_index"]) is not int or origin["control_index"] < 0):
        raise bad()
    row = origin["control_source"]
    if (type(row) is not dict or set(row) != {"id", "form_sha256", "graph_source"}
            or not name(row["id"]) or not hexed(row["form_sha256"], 64)):
        raise bad()
    capsule = row["graph_source"]
    keys = {"graph_id", "root_id", "rule_id", "sense_id", "effective_graph_sha256", "view_key", "nodes", "edges"}
    if (type(capsule) is not dict or set(capsule) != keys or not name(capsule["graph_id"])
            or not name(capsule["root_id"]) or type(capsule["rule_id"]) is not str
            or capsule["rule_id"] != row["id"] or capsule["sense_id"] is not None
            or not hexed(capsule["effective_graph_sha256"], 64)):
        raise bad()
    view = capsule["view_key"]
    if (type(view) is not list or len(view) != 2 or type(view[0]) is not int or view[0] < 0
            or (view[1] is None) != (view[0] == 0) or not (view[1] is None or name(view[1]))):
        raise bad()
    nodes, edges = capsule["nodes"], capsule["edges"]
    if type(nodes) is not dict or type(edges) is not dict:
        raise bad()
    if len(nodes) > 512 or len(edges) > 1024:
        raise ValueError("query_origin_overflow")
    if any(not name(k) or not where(v) for k, v in nodes.items()):
        raise bad()
    if any(not (type(k) is str and k.startswith("e:") and hexed(k[2:], 32)) or not where(v)
           for k, v in edges.items()):
        raise bad()
    spent, stack = 0, [origin]     # exact canonical JSON bytes, counted before any whole serialization
    while stack:
        item = stack.pop()
        if type(item) in (dict, list):
            spent += 2 + max(len(item) - 1, 0) + (len(item) if type(item) is dict else 0)
            stack.extend(item)
            stack.extend(item.values() if type(item) is dict else ())
        elif type(item) is str:    # canonical escaped UTF-8 cost per character, never a whole token
            spent += 2
            for ch in item:
                spent += (2 if ch in '"\\\b\f\n\r\t' else 6 if ch < " " else 1 if ch < "\x80"
                          else 2 if ch < "\u0800" else 3 if ch < "\U00010000" else 4)
                if spent > 262144:
                    raise ValueError("query_origin_overflow")
        elif type(item) is int and (room := 262144 - spent - (item < 0)) > 0 and (
                item.bit_length() * 30103 // 100000 < room or abs(item) < 10 ** room):
            try:    # digits are proven to fit the remaining canonical bytes before any decimal conversion
                spent += len(str(item))
            except ValueError: raise bad() from None    # native integer-to-text failure stays a controlled local error
        elif item is None:
            spent += 4
        else:
            raise ValueError("query_origin_overflow")
        if spent > 262144:
            raise ValueError("query_origin_overflow")
    try:
        data = json.dumps(origin, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        raise bad() from None
    if len(data) > 262144:
        raise ValueError("query_origin_overflow")
    return data


def _query_origin_encode(origin):
    """Detached exact versioned wire: one level-9 zlib member of the canonical bytes, padded base64."""
    import base64
    import zlib
    data = _query_origin_canonical(origin)
    packed = base64.b64encode(zlib.compress(data, 9)).decode("ascii")
    if len(packed) > 32768:
        raise ValueError("query_origin_overflow")
    wire = {"schema": "marco-query-control-origin-wire-v1", "codec": "zlib-json-base64-v1",
            "expanded_bytes": len(data), "expanded_sha256": hashlib.sha256(data).hexdigest(),
            "data": packed}
    if len(json.dumps(wire, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 32768:
        raise ValueError("query_origin_overflow")
    return wire


def _query_origin_decode(wire):
    """(logical origin, actual canonical bytes) of one exact versioned wire, else ValueError."""
    import base64
    import zlib

    def bad():
        return ValueError("query_origin_invalid")

    keys = {"schema", "codec", "expanded_bytes", "expanded_sha256", "data"}
    if (type(wire) is not dict or set(wire) != keys
            or type(wire["schema"]) is not str or wire["schema"] != "marco-query-control-origin-wire-v1"
            or type(wire["codec"]) is not str or wire["codec"] != "zlib-json-base64-v1"):
        raise bad()
    size, digest, packed = wire["expanded_bytes"], wire["expanded_sha256"], wire["data"]
    if type(size) is not int or not 1 <= size <= 262144:
        raise bad()
    if type(digest) is not str or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise bad()
    if (type(packed) is not str or not packed or len(packed) > 32768 or not packed.isascii()
            or len(packed) % 4):
        raise bad()
    try:
        if len(json.dumps(wire, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")) > 32768:
            raise bad()
    except (TypeError, ValueError, RecursionError):
        raise bad() from None
    try:
        raw = base64.b64decode(packed, validate=True)
        if base64.b64encode(raw).decode("ascii") != packed:
            raise bad()
        stream = zlib.decompressobj()    # one bounded pass over exactly one zlib member; never an unbounded flush
        data = stream.decompress(raw, size + 1)
        if len(data) != size or not stream.eof or stream.unconsumed_tail or stream.unused_data:
            raise bad()
        text = data.decode("utf-8")
    except (ValueError, zlib.error):
        raise bad() from None
    # bounded nesting before parsing (strings skipped; 92 is the JSON escape character)
    depth, quoted, escaped = 0, False, False
    for ch in text:
        if quoted:
            if escaped:
                escaped = False
            elif ord(ch) == 92:
                escaped = True
            elif ch == '"':
                quoted = False
        elif ch == '"':
            quoted = True
        elif ch in "[{":
            depth += 1
            if depth > 8:
                raise bad()
        elif ch in "]}":
            depth -= 1

    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise bad()
            out[key] = value
        return out

    def refuse(_):
        raise bad()

    try:
        logical = json.loads(text, object_pairs_hook=pairs, parse_constant=refuse, parse_float=refuse)
    except (ValueError, RecursionError):
        raise bad() from None
    canonical = _query_origin_canonical(logical)
    if canonical != data or len(canonical) != size or hashlib.sha256(canonical).hexdigest() != digest:
        raise bad()
    return logical, canonical
