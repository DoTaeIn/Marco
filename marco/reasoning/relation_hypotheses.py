"""ROOT-approved pure relation-hypothesis evaluation carrier.

The private world assembly helper ``_evaluate_world`` reuses the existing
finite Horn engine unchanged and emits evidence-only, detached, JSON-finite
world carriers. The public ``evaluate_relation_hypotheses`` validates carrier
shape and finite limits only; it never parses, acquires snapshots, learns,
selects answers or authenticates sources. JSON coherence is not caller
ownership, source authentication, history usage or reality truth.
"""
import hashlib
import json
from copy import deepcopy

from marco.reasoning.inference import bind, closure_with_provenance, current_facts
from marco.reasoning.readings import Obs
from relational_semantics import substitute

_SUPPORT_LIMIT = 8
_WORLD_BYTES_LIMIT = 262144
_ENGINE_LIMIT = 64
_ENGINE_PROOF_LIMIT = 8
_ENGINE_SEARCH_LIMIT = 512
_ENGINE_OVERLAP_ID_BYTES = 8192


def _is_positive_asserted(item):
    return (item.get("modality", "asserted") == "asserted"
            and item.get("polarity", True) is True)


def _is_denial(item):
    return (item.get("modality", "asserted") == "asserted"
            and item.get("polarity") is False)


def _support_limit_exceeded(engine_facts):
    """True when any identical triple has more eligible positive supports than allowed."""
    forbidden = {tuple(item["triple"]) for item in engine_facts if _is_denial(item)}
    counts = {}
    for item in engine_facts:
        if not _is_positive_asserted(item):
            continue
        key = tuple(item["triple"])
        if key in forbidden:
            continue
        counts[key] = counts.get(key, 0) + 1
        if counts[key] > _SUPPORT_LIMIT:
            return True
    return False


def _serialize_world(world):
    """UTF-8 JSON bytes of the world; ValueError on non-finite values."""
    return json.dumps(world, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


_JSON_DEPTH_LIMIT = 32
_JSON_VISIT_LIMIT = 50000
_CONTEXT_SCHEMA = "reasoning-context-v11"
_CONTEXT_FACT_LIMIT = 64
_ATOM_BYTES_LIMIT = 128
_UNSUPPORTED_FACT_KEYS = ("scope", "parts", "resolve", "at_least")


class _Refuse(ValueError):
    pass


def _valid_json(value, *, byte_limit=262144):
    """True when ``value`` is a finite plain-JSON tree within the caps.

    Exact ``None``/``bool``/``int``/finite ``float``/``str``/``list``/``dict``
    (string keys) only; the native ``Obs`` string carrier counts as ``str``.
    Nothing is mutated and no custom object method is invoked.
    """
    budget = [_JSON_VISIT_LIMIT]

    def _walk(node, depth):
        budget[0] -= 1
        if budget[0] < 0:
            return False
        kind = type(node)
        if node is None or kind is bool or kind is int:
            return True
        if kind is float:
            return node == node and node != float("inf") and node != float("-inf")
        if kind is str or kind is Obs:
            return str.__len__(node) <= byte_limit
        if depth >= _JSON_DEPTH_LIMIT:
            return False
        if kind is list:
            for item in node:
                if not _walk(item, depth + 1):
                    return False
            return True
        if kind is dict:
            for key, item in node.items():
                if type(key) is not str or str.__len__(key) > byte_limit:
                    return False
                if not _walk(item, depth + 1):
                    return False
            return True
        return False

    if not _walk(value, 0):
        return False
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False,
                             separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, OverflowError, RecursionError):
        return False
    return len(encoded) <= byte_limit


def _exact_int(value):
    return type(value) is int


def _plain_str(value):
    return type(value) is str or type(value) is Obs


def _is_decimal_atom(text):
    """Plain numeric role term: Unicode decimal digits or signed ASCII integer/decimal."""
    body = str.__str__(text) if type(text) is Obs else text
    if body[:1] in ("+", "-"):
        body = body[1:]
    if not body:
        return False
    if all(ch.isdecimal() for ch in body):
        return True
    head, sep, tail = body.partition(".")
    if not sep or not head or not tail:
        return False
    digits = "0123456789"
    return all(ch in digits for ch in head) and all(ch in digits for ch in tail)


def _is_variable_atom(text):
    return text[:1] in ("?", "$")


def _binding_conversation(binding):
    if isinstance(binding, dict):
        return binding.get("conversation_id")
    return getattr(binding, "conversation_id", None)


def _check_unread(unread, source):
    if not isinstance(unread, list):
        raise _Refuse("context_invalid")
    found = False
    for row in unread:
        if not isinstance(row, dict):
            raise _Refuse("context_invalid")
        text, at = row.get("text"), row.get("at")
        if (_plain_str(text) and str.__eq__(text, source) is True
                and _exact_int(at) and at >= 0):
            found = True
    if not found:
        raise _Refuse("context_invalid")


def _check_asked(asked):
    if not isinstance(asked, list):
        raise _Refuse("context_invalid")
    for row in asked:
        if not isinstance(row, dict):
            raise _Refuse("context_invalid")
    for row in asked:
        if not row.get("해결"):
            raise _Refuse("unsupported_context")


def _check_unread_guard(guard):
    if guard is None:
        return
    if not isinstance(guard, list):
        raise _Refuse("context_invalid")
    for row in guard:
        if not isinstance(row, dict):
            raise _Refuse("context_invalid")
    for row in guard:
        if row.get("범용") is True:
            raise _Refuse("unsupported_context")


def _check_events(events):
    if not isinstance(events, list):
        raise _Refuse("context_invalid")
    for row in events:
        if not isinstance(row, dict) or not isinstance(row.get("event"), dict):
            raise _Refuse("context_invalid")
        for key in ("effects", "state_changes"):
            if key in row and row[key] is not None and not isinstance(row[key], list):
                raise _Refuse("context_invalid")
    for row in events:
        if row["event"].get("program"):
            raise _Refuse("unsupported_context")
        if row.get("effects") or row.get("state_changes"):
            raise _Refuse("unsupported_context")


def _check_fact(fact):
    if not isinstance(fact, dict):
        raise _Refuse("context_invalid")
    triple = fact.get("triple")
    if not isinstance(triple, list) or len(triple) != 3:
        raise _Refuse("context_invalid")
    for atom in triple:
        if not _plain_str(atom) or not str.strip(atom):
            raise _Refuse("context_invalid")
    evidence = fact.get("evidence")
    if not isinstance(evidence, dict) or not _valid_json(evidence):
        raise _Refuse("context_invalid")
    if "polarity" in fact and type(fact["polarity"]) is not bool:
        raise _Refuse("context_invalid")
    for atom in triple:
        if len(str.encode(atom, "utf-8")) > _ATOM_BYTES_LIMIT:
            raise _Refuse("unsupported_scope")
    if fact.get("modality", "asserted") != "asserted":
        raise _Refuse("unsupported_context")
    for atom in triple:
        if _is_variable_atom(atom):
            raise _Refuse("unsupported_context")
    for atom in triple[0], triple[2]:
        if _is_decimal_atom(atom) or any(ch.isspace() for ch in atom):
            raise _Refuse("unsupported_context")
    for key in _UNSUPPORTED_FACT_KEYS:
        if key == "at_least":
            if fact.get(key) is not None:
                raise _Refuse("unsupported_context")
        elif fact.get(key) is not None and fact.get(key):
            raise _Refuse("unsupported_context")
    if evidence.get("action_event"):
        raise _Refuse("unsupported_context")


def _check_fact_source(row, records):
    if row is None:
        return
    if type(row) is not dict or set(row) != {"observation_id", "reading_revision"}:
        raise _Refuse("context_invalid")
    oid, rev = row["observation_id"], row["reading_revision"]
    if not _plain_str(oid) or not str.strip(oid) or not _exact_int(rev) or rev < 1:
        raise _Refuse("context_invalid")
    entry = records.get(oid)
    versions = entry.get("versions") if isinstance(entry, dict) else None
    if not isinstance(versions, list) or rev > len(versions):
        raise _Refuse("context_invalid")
    record = versions[rev - 1]
    if (not isinstance(record, dict) or record.get("observation_id") != oid
            or not _exact_int(record.get("reading_revision"))
            or record["reading_revision"] != rev):
        raise _Refuse("context_invalid")


def _validated_context(context_snapshot, source, binding):
    """Gate a prior-validated context snapshot for the bounded flat replay unit.

    Returns ``(facts, fact_sources)`` as deepcopies or raises ``_Refuse`` with
    the exact reason. Nothing is mutated, no history is reparsed.
    """
    snap = context_snapshot
    if not isinstance(snap, dict) or snap.get("schema") != _CONTEXT_SCHEMA:
        raise _Refuse("context_invalid")
    conversation = snap.get("conversation")
    if type(conversation) is not str or conversation != _binding_conversation(binding):
        raise _Refuse("context_invalid")
    replay = snap.get("replay")
    if not isinstance(replay, dict):
        raise _Refuse("context_invalid")
    facts, fact_sources = replay.get("facts"), replay.get("fact_sources")
    if (not isinstance(facts, list) or not isinstance(fact_sources, list)
            or len(facts) != len(fact_sources)):
        raise _Refuse("context_invalid")
    definitions, programs = replay.get("definitions"), replay.get("programs")
    pending, read = replay.get("pending"), replay.get("read")
    if (not isinstance(definitions, dict) or not isinstance(programs, dict)
            or not isinstance(pending, list) or not isinstance(read, list)):
        raise _Refuse("context_invalid")
    observations, observation_ids = snap.get("observations"), snap.get("observation_ids")
    if (not isinstance(observations, list) or not isinstance(observation_ids, list)
            or len(observations) != len(observation_ids)):
        raise _Refuse("context_invalid")
    ledger = snap.get("reading_ledger")
    records = ledger.get("records") if isinstance(ledger, dict) else None
    if not isinstance(records, dict):
        raise _Refuse("context_invalid")
    _check_unread(snap.get("unread"), source)
    _check_asked(snap.get("asked", []))
    _check_unread_guard(snap.get("unread_guard"))
    _check_events(snap.get("events", []))
    if definitions or programs or pending:
        raise _Refuse("unsupported_context")
    if len(facts) > _CONTEXT_FACT_LIMIT:
        raise _Refuse("context_limit")
    for fact in facts:
        _check_fact(fact)
    for row in fact_sources:
        _check_fact_source(row, records)
    return deepcopy(facts), deepcopy(fact_sources)


_QUERY_SOURCE_CHARS = 512
_QUERY_SOURCE_WORDS = 40
_QUERY_ADVANCED_KEYS = ("definitions", "events", "condition", "assumption", "reason",
                        "correction", "repair", "정의", "사건", "가정사건", "조건",
                        "가정", "원인", "이유물음", "수선", "사건정정")
_SELECTION_HEADER = {"schema": "marco-entry-selection-v1",
                     "scope": "known_selected_input_clauses",
                     "status": "partial", "coordinate_space": "parser_view"}
_SELECTION_DIAGNOSTICS = ("origin_unavailable", "origin_unknown", "binding_unknown",
                          "origin_invalid", "origin_alignment_invalid",
                          "origin_index_unavailable")


def _annotation_digest(annotation):
    text = json.dumps(annotation, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _query_positions(triple):
    """``(asked, known)`` positions of one ``?``-asked / plain-known triple, else None."""
    if not isinstance(triple, list) or len(triple) != 3:
        return None
    for atom in triple:
        if not _plain_str(atom) or not str.strip(atom):
            return None
    if _is_variable_atom(triple[1]):
        return None
    asked = [pos for pos in (0, 2) if triple[pos][:1] == "?"]
    if len(asked) != 1:
        return None
    known = 2 - asked[0]
    return asked[0], known


def _check_request(request):
    if type(request) is not dict or set(request) != {"triple", "render"}:
        raise _Refuse("unsupported_query")
    triple, render = request["triple"], request["render"]
    positions = _query_positions(triple)
    if positions is None:
        raise _Refuse("unsupported_query")
    known = triple[positions[1]]
    if (_is_variable_atom(known) or _is_decimal_atom(known)
            or any(ch.isspace() for ch in known)):
        raise _Refuse("unsupported_query")
    if not isinstance(render, list) or not all(_plain_str(piece) for piece in render):
        raise _Refuse("unsupported_query")
    return positions


def _check_entry_selection(selection, source):
    """Return the selected item's exact ``compiler_index`` or raise query_invalid."""
    if type(selection) is not dict or set(selection) != set(_SELECTION_HEADER) | {"items", "gaps"}:
        raise _Refuse("query_invalid")
    for key, expected in _SELECTION_HEADER.items():
        if selection[key] != expected:
            raise _Refuse("query_invalid")
    items, gaps = selection["items"], selection["gaps"]
    if type(items) is not list or len(items) != 1 or type(gaps) is not list:
        raise _Refuse("query_invalid")
    item = items[0]
    if (type(item) is not dict or set(item) != {"clause_ordinal", "span", "compiler_index",
                                                 "origin", "targets", "derivation"}):
        raise _Refuse("query_invalid")
    if not _exact_int(item["clause_ordinal"]) or item["clause_ordinal"] != 0:
        raise _Refuse("query_invalid")
    index = item["compiler_index"]
    if not _exact_int(index):
        raise _Refuse("query_invalid")
    targets = item["targets"]
    if (type(targets) is not dict or set(targets) != {"facts", "query"}
            or targets["facts"] != [] or type(targets["query"]) is not list
            or len(targets["query"]) != 1 or not _exact_int(targets["query"][0])
            or targets["query"][0] != 0):
        raise _Refuse("query_invalid")
    if item["derivation"] is not None:
        raise _Refuse("query_invalid")
    span = item["span"]
    if (type(span) is not list or len(span) != 2 or not _exact_int(span[0])
            or not _exact_int(span[1]) or not 0 <= span[0] < span[1] <= len(source)):
        raise _Refuse("query_invalid")
    if item["origin"] is not None and type(item["origin"]) is not dict:
        raise _Refuse("query_invalid")
    for gap in gaps:
        if (type(gap) is not dict or gap.get("code") not in _SELECTION_DIAGNOSTICS
                or not _exact_int(gap.get("clause_ordinal")) or gap["clause_ordinal"] != 0):
            raise _Refuse("query_invalid")
    return index


def _validated_query(query_record, projection):
    """Gate one selected-record query and return the detached native request triple.

    Checks carrier shape, declared selection coherence and annotation/source
    identity against ``projection``; raises ``_Refuse`` with the exact reason.
    Nothing is mutated, no text is reparsed and no answer is substituted.
    """
    if type(query_record) is not dict or set(query_record) != {"source", "parsed", "source_ref"}:
        raise _Refuse("query_invalid")
    source, parsed, source_ref = (query_record["source"], query_record["parsed"],
                                  query_record["source_ref"])
    if (not _plain_str(source) or not str.strip(source)
            or str.__len__(source) > _QUERY_SOURCE_CHARS
            or len(str.split(source)) > _QUERY_SOURCE_WORDS):
        raise _Refuse("query_invalid")
    if type(parsed) is not dict:
        raise _Refuse("query_invalid")
    if parsed.get("facts") != [] or type(parsed.get("facts")) is not list:
        raise _Refuse("unsupported_query")
    query = parsed.get("query")
    if type(query) is not list or len(query) != 1:
        raise _Refuse("unsupported_query")
    for key in _QUERY_ADVANCED_KEYS:
        if parsed.get(key):
            raise _Refuse("unsupported_query")
    request = query[0]
    asked_pos, known_pos = _check_request(request)

    compiler_index = _check_entry_selection(parsed.get("entry_selection"), source)

    if (type(source_ref) is not dict
            or set(source_ref) != {"index", "annotation_sha256", "graph_source"}):
        raise _Refuse("query_invalid")
    index = source_ref["index"]
    if not _exact_int(index) or not _plain_str(source_ref["annotation_sha256"]):
        raise _Refuse("query_invalid")
    if type(projection) is not dict:
        raise _Refuse("query_invalid")
    query_sources = projection.get("query_sources")
    if type(query_sources) is not list or not query_sources:
        raise _Refuse("query_invalid")
    if index != compiler_index:
        raise _Refuse("query_invalid")
    record = None
    for row in query_sources:
        if (type(row) is dict and _exact_int(row.get("index"))
                and row["index"] == compiler_index):
            if record is not None:
                raise _Refuse("query_invalid")
            record = row
    if type(record) is not dict or record != source_ref:
        raise _Refuse("query_invalid")
    data = projection.get("data")
    frames = data.get("predicate_frames") if type(data) is dict else None
    seed_prefix = frames.get("seed_count") if type(frames) is dict else None
    if not _exact_int(seed_prefix):
        raise _Refuse("query_invalid")
    examples = data.get("examples")
    if (type(examples) is not list or index < seed_prefix
            or not 0 <= index < len(examples)):
        raise _Refuse("query_invalid")
    annotation = examples[index]
    if (type(annotation) is not dict or not _valid_json(annotation)
            or _annotation_digest(annotation) != source_ref["annotation_sha256"]):
        raise _Refuse("query_invalid")

    slots = annotation.get("slots")
    meaning = annotation.get("meaning")
    declared = meaning.get("query") if isinstance(meaning, dict) else None
    if (type(slots) is not dict or type(declared) is not list or len(declared) != 1
            or type(declared[0]) is not dict
            or set(declared[0]) != {"triple", "render"}):
        raise _Refuse("query_invalid")
    declared_positions = _query_positions(declared[0]["triple"])
    if declared_positions is None or declared_positions != (asked_pos, known_pos):
        raise _Refuse("query_invalid")
    declared_triple = declared[0]["triple"]
    if (declared_triple[1] != request["triple"][1]
            or declared_triple[asked_pos] != request["triple"][asked_pos]):
        raise _Refuse("query_invalid")
    known_term = declared_triple[known_pos]
    if known_term[:1] != "$" or known_term[1:] not in slots:
        raise _Refuse("query_invalid")
    instantiated = substitute(deepcopy(declared[0]),
                              {known_term[1:]: request["triple"][known_pos]})
    if (instantiated["triple"] != list(request["triple"])
            or instantiated["render"] != list(request["render"])):
        raise _Refuse("query_invalid")
    return deepcopy(list(request["triple"]))


_RULES_LIMIT = 16
_RULE_BODY_LIMIT = 4
_PARSER_HOOKS = ("rule_selector", "closure_selector", "closure_recorder")


def _atom_overflow(atom):
    return len(str.encode(atom, "utf-8")) > _ATOM_BYTES_LIMIT


def _check_rule_triple(triple, reason):
    """Validate one native rule triple; ``reason`` names the shape refusal."""
    if type(triple) is not list or len(triple) != 3:
        raise _Refuse(reason)
    for atom in triple:
        if not _plain_str(atom) or not str.strip(atom):
            raise _Refuse(reason)
    if triple[1][:1] == "?":
        raise _Refuse(reason)


def _check_rule(rule, seen_ids):
    if type(rule) is not dict:
        raise _Refuse("rule_invalid")
    rule_id = rule.get("id")
    if not _plain_str(rule_id) or not str.strip(rule_id) or rule_id in seen_ids:
        raise _Refuse("rule_invalid")
    seen_ids.add(rule_id)
    body, head = rule.get("body"), rule.get("head")
    if type(body) is not list or not body:
        raise _Refuse("rule_invalid")
    if len(body) > _RULE_BODY_LIMIT:
        raise _Refuse("rule_limit")
    for pattern in body:
        _check_rule_triple(pattern, "rule_invalid")
    _check_rule_triple(head, "rule_invalid")
    grounded = {x for pattern in body for x in pattern if x[:1] == "?"}
    if any(x[:1] == "?" and x not in grounded for x in head):
        raise _Refuse("rule_invalid")
    if not _valid_json(rule):
        raise _Refuse("rule_invalid")
    version = rule.get("version", rule.get("rule_version"))
    for item in (rule_id, version):
        if not _valid_json(item, byte_limit=_ATOM_BYTES_LIMIT):
            raise _Refuse("unsupported_scope")
    for pattern in body + [head]:
        for atom in pattern:
            if _atom_overflow(atom):
                raise _Refuse("unsupported_scope")


def _declared_predicates(data):
    """Reserved predicates from native mutable/numeric declarations, else unsupported_scope."""
    reserved = set()
    mutable = data.get("mutable_predicates", [])
    if type(mutable) is not list:
        raise _Refuse("unsupported_scope")
    for name in mutable:
        if not _plain_str(name) or not str.strip(name):
            raise _Refuse("unsupported_scope")
        reserved.add(name)
    numeric = data.get("numeric_updates", {})
    if type(numeric) is not dict:
        raise _Refuse("unsupported_scope")
    for key, spec in numeric.items():
        if not _plain_str(key) or not str.strip(key) or type(spec) is not dict:
            raise _Refuse("unsupported_scope")
        target = spec.get("target")
        if not _plain_str(target) or not str.strip(target):
            raise _Refuse("unsupported_scope")
        reserved.add(key)
        reserved.add(target)
    return reserved


def _validated_rules(parser, facts, candidates, query_triple):
    """Gate the selected parser's complete rules list and return a detached copy.

    Raises ``_Refuse`` with the exact reason. Parser hooks are only read, never
    invoked; no rule is dropped, reordered, grounded or rewritten.
    """
    for name in _PARSER_HOOKS:
        if getattr(parser, name, None) is not None:
            raise _Refuse("unsupported_scope")
    data = getattr(parser, "data", None)
    if type(data) is not dict:
        raise _Refuse("rule_invalid")
    rules = data.get("rules")
    if type(rules) is not list:
        raise _Refuse("rule_invalid")
    if len(rules) > _RULES_LIMIT:
        raise _Refuse("rule_limit")
    seen_ids = set()
    for rule in rules:
        _check_rule(rule, seen_ids)

    heads = {rule["head"][1] for rule in rules}
    bodies = {pattern[1] for rule in rules for pattern in rule["body"]}
    overlap = bool(heads & bodies)
    if overlap:
        for rule in rules:
            if type(rule["id"]) is not str:
                raise _Refuse("unsupported_scope")
            version = rule["version"] if "version" in rule else rule.get("rule_version")
            if type(version) not in (type(None), bool, int, float, str):
                raise _Refuse("unsupported_scope")

    touched = set(heads) | set(bodies)
    carried = [fact["triple"] for fact in facts]
    carried.extend(candidate["assumed_fact"]["triple"] for candidate in candidates)
    carried.append(query_triple)
    for triple in carried:
        _check_rule_triple(triple, "unsupported_scope")
        for atom in triple:
            if _atom_overflow(atom):
                raise _Refuse("unsupported_scope")
        touched.add(triple[1])

    reserved = _declared_predicates(data)
    if touched & reserved:
        raise _Refuse("unsupported_scope")
    if overlap and ({str.__str__(name) for name in touched}
                    & {str.__str__(name) for name in reserved}):
        raise _Refuse("unsupported_scope")
    return deepcopy(rules)


def _evaluate_world(facts, fact_sources, rules, query_triple, *, assumption=None):
    """Assemble one evidence-only world for ``query_triple``.

    Returns ``(world, gap_reason)``. ``world`` is exactly
    ``{matches, facts, proof_bundles, fact_sources, rules, complete, reason, searches}``
    or ``None`` when a gap prevents assembly. No supplied object is mutated.
    """
    heads = {rule["head"][1] for rule in rules}
    bodies = {pattern[1] for rule in rules for pattern in rule["body"]}
    overlap = bool(heads & bodies)
    engine_facts, descriptors = [], []
    for index, item in enumerate(facts):
        original = deepcopy(item)
        local = deepcopy(item)
        local["id"] = "baseline:%d" % index
        if overlap:
            local["triple"] = [str.__str__(atom) for atom in local["triple"]]
            if type(local.get("modality")) is Obs:
                local["modality"] = str.__str__(local["modality"])
        engine_facts.append(local)
        source_ref = fact_sources[index] if index < len(fact_sources) else None
        descriptors.append({"premise_id": local["id"],
                            "fact_index": index,
                            "original_fact": original,
                            "source_ref": deepcopy(source_ref) if source_ref is not None else None})
    if assumption is not None:
        local_assumption = deepcopy(assumption)
        if overlap:
            local_assumption["triple"] = [str.__str__(atom)
                                          for atom in local_assumption["triple"]]
            if type(local_assumption.get("modality")) is Obs:
                local_assumption["modality"] = str.__str__(local_assumption["modality"])
        engine_facts.append(local_assumption)
        descriptors.append({"premise_id": assumption["id"],
                            "fact_index": None,
                            "original_fact": deepcopy(assumption),
                            "source_ref": None})

    if _support_limit_exceeded(engine_facts):
        return None, "support_limit"

    engine_rules, engine_query = rules, query_triple
    if overlap:
        engine_rules = []
        for rule in rules:
            local_rule = deepcopy(rule)
            local_rule["head"] = [str.__str__(atom) for atom in rule["head"]]
            local_rule["body"] = [[str.__str__(atom) for atom in pattern]
                                  for pattern in rule["body"]]
            engine_rules.append(local_rule)
        engine_query = [str.__str__(atom) for atom in query_triple]

    try:
        projected, changes = current_facts(engine_facts, [], {})
        if changes:
            return None, "inference_error"
        if overlap:
            result = closure_with_provenance(projected, engine_rules,
                                             limit=_ENGINE_LIMIT,
                                             proof_limit=_ENGINE_PROOF_LIMIT,
                                             search_limit=_ENGINE_SEARCH_LIMIT,
                                             max_bundle_id_bytes=_ENGINE_OVERLAP_ID_BYTES)
        else:
            result = closure_with_provenance(projected, rules,
                                             limit=_ENGINE_LIMIT,
                                             proof_limit=_ENGINE_PROOF_LIMIT,
                                             search_limit=_ENGINE_SEARCH_LIMIT)
    except ValueError:
        return None, "inference_error"

    known = result["facts"]
    bundles = result["proof_bundles"]

    matches = []
    for key in known:
        bindings = bind(engine_query, list(key), {})
        if bindings is None:
            continue
        matches.append({"triple": list(key),
                        "bindings": deepcopy(bindings),
                        "support_ids": [row["id"] for row in bundles.get(key, [])]})

    world = {
        "matches": matches,
        "facts": [{"triple": list(key), "record": deepcopy(record)}
                  for key, record in known.items()],
        "proof_bundles": [{"triple": list(key), "bundles": deepcopy(rows)}
                          for key, rows in bundles.items()],
        "fact_sources": descriptors,
        "rules": deepcopy(list(rules)),
        "complete": result["complete"],
        "reason": result["reason"],
        "searches": result["searches"],
    }

    try:
        encoded = _serialize_world(world)
    except ValueError:
        return None, "world_limit"
    if len(encoded) > _WORLD_BYTES_LIMIT:
        return None, "world_limit"

    return world, (None if world["complete"] else "engine_incomplete")


from marco.language.relation_hypotheses import propose_relation_hypotheses

_OUTPUT_SCHEMA = "relation-hypothesis-evaluation-v1"
_INPUT_BYTES_LIMIT = 262144
_OUTPUT_BYTES_LIMIT = 1048576
_PROPOSAL_SOURCE_CHARS = 512
_CANDIDATE_LIMIT = 16
_PROPOSAL_KEYS = {"source", "binding", "candidates", "gaps"}
_AUTHORITY_GAPS = ("binding_invalid", "projection_invalid",
                   "projection_parser_mismatch", "projection_parser_invalid")
_HEX_DIGITS = "0123456789abcdef"


def _gap(reason, candidate_id=None):
    return {"reason": reason, "candidate_id": candidate_id}


def _canonical(value):
    """Canonical compact JSON text; keeps bool/int/float distinctions. ValueError if non-finite."""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":"))


def _safe_source_echo(proposal):
    source = proposal.get("source") if type(proposal) is dict else None
    if (_plain_str(source) and str.__len__(source) <= _PROPOSAL_SOURCE_CHARS
            and _valid_json(source)):
        return deepcopy(source)
    return None


def _safe_echo(value):
    return deepcopy(value) if _valid_json(value, byte_limit=_INPUT_BYTES_LIMIT) else None


def _plain_triple(triple):
    return [str.__str__(atom) for atom in triple]


def _gap_reason(gap):
    if type(gap) is dict:
        return gap.get("reason", gap.get("code"))
    return gap


def _authority_gap(reason):
    if not _plain_str(reason):
        return False
    if reason in ("parser_binding_mismatch", "hypothesis_policy_unavailable"):
        return True
    return reason in _AUTHORITY_GAPS or str.endswith(reason, "_invalid")


def _check_candidates(candidates):
    if type(candidates) is not list or len(candidates) > _CANDIDATE_LIMIT:
        raise _Refuse("proposal_invalid")
    seen = set()
    for candidate in candidates:
        if type(candidate) is not dict:
            raise _Refuse("proposal_invalid")
        cid = candidate.get("id")
        if (not _plain_str(cid) or str.__len__(cid) != 64
                or not all(ch in _HEX_DIGITS for ch in cid) or str.__str__(cid) in seen):
            raise _Refuse("proposal_invalid")
        seen.add(str.__str__(cid))
        assumed = candidate.get("assumed_fact")
        if type(assumed) is not dict or type(assumed.get("triple")) is not list:
            raise _Refuse("proposal_invalid")


def _validated_proposal(parser, proposal, projection, binding):
    """Re-derive the proposal once and return detached original candidates or raise ``_Refuse``."""
    if type(proposal) is not dict or set(proposal) != _PROPOSAL_KEYS:
        raise _Refuse("proposal_invalid")
    source = proposal["source"]
    if (not _plain_str(source) or not str.strip(source)
            or str.__len__(source) > _PROPOSAL_SOURCE_CHARS):
        raise _Refuse("proposal_invalid")
    try:
        fresh = propose_relation_hypotheses(parser, source, projection=projection,
                                            binding=binding, candidate_limit=_CANDIDATE_LIMIT)
    except ValueError:
        raise _Refuse("proposal_invalid")
    if type(fresh) is not dict:
        raise _Refuse("proposal_invalid")
    fresh_gaps = fresh.get("gaps")
    if type(fresh_gaps) is not list:
        raise _Refuse("proposal_invalid")
    for gap in fresh_gaps:
        if _authority_gap(_gap_reason(gap)):
            raise _Refuse("proposal_invalid")
    try:
        if _canonical(proposal["binding"]) != _canonical(binding):
            raise _Refuse("proposal_mismatch")
    except (TypeError, OverflowError, RecursionError):
        raise _Refuse("proposal_invalid")
    except ValueError as error:
        if isinstance(error, _Refuse):
            raise
        raise _Refuse("proposal_invalid")
    try:
        if _canonical(fresh) != _canonical(proposal):
            raise _Refuse("proposal_mismatch")
    except (TypeError, OverflowError, RecursionError):
        raise _Refuse("proposal_invalid")
    except ValueError as error:
        if isinstance(error, _Refuse):
            raise
        raise _Refuse("proposal_invalid")
    candidates = proposal["candidates"]
    if type(candidates) is list and not candidates:
        raise _Refuse("no_hypotheses")
    _check_candidates(candidates)
    return deepcopy(candidates)


def _hypothesis_fact(candidate, source):
    premise_id = "hypothesis:" + str.__str__(candidate["id"])
    return {"id": premise_id,
            "triple": deepcopy(candidate["assumed_fact"]["triple"]),
            "polarity": True,
            "modality": "asserted",
            "evidence": {"mode": "hypothetical",
                         "candidate_id": candidate["id"],
                         "source": source,
                         "unknown_span": deepcopy(candidate.get("unknown_span")),
                         "source_ref": deepcopy(candidate.get("source_ref")),
                         "policy_source": deepcopy(candidate.get("policy_source"))}}


def _conflicts(triple, facts, fact_sources):
    target = _plain_triple(triple)
    found = []
    for index, fact in enumerate(facts):
        if not _is_denial(fact) or _plain_triple(fact["triple"]) != target:
            continue
        source_ref = fact_sources[index] if index < len(fact_sources) else None
        found.append({"premise_id": "baseline:%d" % index,
                      "fact_index": index,
                      "original_fact": deepcopy(fact),
                      "source_ref": deepcopy(source_ref)})
    return found


def _assemble(binding_echo, source_echo, query_echo, baseline, outcomes, gaps):
    return {"schema": _OUTPUT_SCHEMA,
            "binding": binding_echo,
            "source": source_echo,
            "query": query_echo,
            "baseline": baseline,
            "outcomes": outcomes,
            "gaps": gaps}


def _finish(result, binding_echo, source_echo, query_echo):
    """Return ``result`` if it serializes finitely within the output cap, else output_limit."""
    try:
        encoded = _serialize_world(result)
    except (TypeError, ValueError, OverflowError, RecursionError):
        encoded = None
    if encoded is not None and len(encoded) <= _OUTPUT_BYTES_LIMIT:
        return result
    return _assemble(binding_echo, source_echo, query_echo, None, [], [_gap("output_limit")])


def evaluate_relation_hypotheses(parser, context_snapshot, proposal, query_record, *,
                                 projection, binding):
    """Evaluate a prior proposal against a prior-validated context replay as evidence-only worlds.

    Pure assembly: no parsing, snapshot acquisition, Session, learning, answer
    selection or source authentication happens here. Genuine fresh parser,
    exact binding, current unread/native query and a prior-validated context
    snapshot are caller prerequisites; JSON coherence is not ownership or truth.
    """
    source_echo = _safe_source_echo(proposal)
    binding_echo = _safe_echo(binding)
    query_echo = _safe_echo(query_record)
    gaps = []

    if not (all(_valid_json(member, byte_limit=_INPUT_BYTES_LIMIT)
                for member in (context_snapshot, proposal, query_record, binding))
            and _valid_json(projection, byte_limit=1048576)
            and _valid_json([context_snapshot, proposal, query_record, projection, binding],
                            byte_limit=2097152)):
        return _assemble(binding_echo, source_echo, query_echo, None, [], [_gap("input_invalid")])

    try:
        candidates = _validated_proposal(parser, proposal, projection, binding)
        source = proposal["source"]
        facts, fact_sources = _validated_context(context_snapshot, source, binding)
        triple = _validated_query(query_record, projection)
        rules = _validated_rules(parser, facts, candidates, triple)
    except _Refuse as refusal:
        return _assemble(binding_echo, source_echo, query_echo, None, [], [_gap(str(refusal))])

    baseline, reason = _evaluate_world(facts, fact_sources, rules, triple)
    if reason is not None:
        gaps.append(_gap(reason))

    outcomes = []
    for candidate in candidates:
        tempfact = _hypothesis_fact(candidate, source)
        world, reason = _evaluate_world(facts, fact_sources, rules, triple, assumption=tempfact)
        if reason is not None:
            gaps.append(_gap(reason, candidate["id"]))
        outcomes.append({"candidate_id": candidate["id"],
                         "assumption": {"candidate": deepcopy(candidate),
                                        "premise_id": tempfact["id"]},
                         "conditional": world,
                         "conflicts": _conflicts(candidate["assumed_fact"]["triple"],
                                                 facts, fact_sources)})

    result = _assemble(binding_echo, source_echo, query_echo, baseline, outcomes, gaps)
    return _finish(result, binding_echo, source_echo, query_echo)
