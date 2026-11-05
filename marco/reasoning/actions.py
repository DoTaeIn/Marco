"""A small, data-only execution contract for learned actions.

The language reader is allowed to decide which Korean words fill a role.  It
is *not* allowed to decide a second time how an action changes state.  This
module is the boundary between those two jobs.  An action program is JSON
serialisable so its definition version, the roles it expects, constant values
and the effects it declares survive replay and can later be put in a pack.

The supported instructions are ``emit``, ``lookup``, ``select``, ``compute``,
``when`` and ``call``.  They deliberately have a common result shape, so the direct
event, completion, and hypothetical paths cannot invent incompatible little
event records.
"""
from __future__ import annotations

from copy import deepcopy


SCHEMA = "nai-action-program-v1"


def _triples(meaning):
    if not isinstance(meaning, dict):
        return []
    rows = meaning.get("triples")
    if rows is None and "triple" in meaning:
        rows = [meaning["triple"]]
    return deepcopy(rows) if isinstance(rows, list) else []


def compile_program(rule, *, version=None):
    """Turn an induced definition into the stable action-program contract.

    ``frame_induction`` remains responsible for learning a definition from a
    natural-language body.  This function contains no Korean word, predicate,
    or action name; it only records the resulting role/effect structure.
    """
    induced = rule.get("유도") or rule.get("induced") or {}
    action_version = version if version is not None else rule.get("때")
    steps = deepcopy(induced.get("프로그램단계") or [
        {"op": "emit", "triples": _triples(induced.get("뜻"))}])
    # Values produced by a lookup, calculation or selection are not caller
    # arguments.  Leaving them in the role signature would make an action ask
    # the user for the very value it is supposed to find.
    produced = {step.get("into") for step in steps
                if step.get("op") in {"lookup", "select", "compute"}
                and isinstance(step.get("into"), str) and step.get("into")}
    signature = {
        "role_slots": {key: value for key, value in (induced.get("자리") or {}).items()
                       if key not in produced},
        "open_roles": {key: value for key, value in
                       {**(induced.get("빈자리") or {}), **(induced.get("채울자리") or {})}.items()
                       if key not in produced},
        "fixed_values": {key: value for key, value in (induced.get("값") or {}).items()
                         if key not in produced},
    }
    return {
        "schema": SCHEMA,
        "action": str(rule.get("verb") or ""),
        "definition_version": action_version,
        "definition_evidence": deepcopy(rule.get("evidence") or {}),
        "references": deepcopy(rule.get("참조") or {}),
        "signature": signature,
        # Calls are preserved even where an older induction has already
        # inlined its effect.  A newer compiler may supply executable calls;
        # consumers can distinguish them without changing the event schema.
        "calls": deepcopy(induced.get("호출") or induced.get("calls") or []),
        # A pack example can declare a small program body (lookup/compute/
        # condition/call).  Older induced frames still become the equivalent
        # emit-only program, so no caller needs a second execution path.
        "steps": steps,
    }


def event_record(event_id, program, event, *, sequence, evidence, fills=(), overrides=(), state_fills=(),
                 conditions=()):
    """Return the one event identity used by normal, completed and planned calls."""
    return {
        "schema": "nai-action-event-v1",
        "id": event_id,
        "action": program.get("action"),
        "definition_version": program.get("definition_version"),
        "program": deepcopy(program),
        "domain": program.get("domain"),
        "references": deepcopy(program.get("references") or {}),
        "roles": deepcopy(event.get("자리") or {}),
        "role_candidates": deepcopy(event.get("자리후보") or []),
        "conditions": deepcopy(conditions or ()),
        "fills": deepcopy(fills or {}),
        "state_fills": deepcopy(state_fills or ()),
        "overrides": deepcopy(overrides or {}),
        "polarity": event.get("polarity", True),
        "modality": event.get("modality", "asserted"),
        "sequence": sequence,
        "evidence": deepcopy(evidence or event.get("evidence") or {}),
    }


def bind(program, roles, overrides=()):
    """Bind observed roles to one program without choosing missing values.

    The return values mirror the long-standing execution contract used by the
    context engine.  In particular, ``facts`` is empty whenever a role is
    missing or clashes with a fixed value.  Thus an incomplete action is never
    silently interpreted as a no-op.
    """
    if not isinstance(program, dict) or program.get("schema") != SCHEMA:
        raise ValueError("invalid_action_program")
    from relational_semantics import asserted, substitute

    signature = program["signature"]
    fixed = dict(signature.get("fixed_values") or {})
    slot_map = dict(signature.get("role_slots") or {})
    open_roles = dict(signature.get("open_roles") or {})
    observed = dict(roles or {})
    overrides = dict(overrides or {})
    values, conflicts = dict(fixed), {}

    # A supplied override is an explicit correction scope, not a best guess.
    for name, slot in slot_map.items():
        if slot in overrides:
            values[name] = overrides[slot]
    for name in open_roles:
        values.pop(name, None)

    open_slots = set(open_roles.values())
    for name, slot in {**slot_map, **open_roles}.items():
        if slot not in observed:
            continue
        if name in open_roles or slot in overrides:
            values[name] = overrides.get(slot, observed[slot])
        elif slot not in open_slots and fixed.get(name) != observed[slot]:
            conflicts[name] = {"definition": fixed.get(name), "event": observed[slot], "slot": slot}

    missing = {name: slot for name, slot in open_roles.items() if name not in values}
    used_slots = set(slot_map.values()) | set(open_roles.values())
    leftover = {slot: value for slot, value in observed.items() if slot not in used_slots}
    # A definition may fix a value while its explanatory surface places that
    # value inside a modifier (for example, "구슬 절반").  An event can still
    # state that same value as a normal argument.  Consume only an exact,
    # uniquely fixed match; every other explicit argument stays visible for
    # conflict/leftover handling.
    for slot, observed_value in list(leftover.items()):
        matches = [name for name, fixed_value in fixed.items()
                   if fixed_value == observed_value]
        if len(matches) == 1:
            del leftover[slot]
    emitted = []
    for step in program.get("steps") or []:
        if step.get("op") != "emit":
            continue
        emitted.extend(step.get("triples") or [])
    facts = asserted(substitute({"triples": emitted}, values))
    return {
        "facts": [] if (missing or conflicts) else facts,
        "missing": missing,
        "conflicts": conflicts,
        "leftover": leftover,
        "reachable": facts,
        "values": values,
    }


def _quantity_value(raw, quantities):
    return (quantities or {}).get(str(raw))


def resolve_state_values(facts, prior_facts, *, quantities, mutable_predicates, numeric_updates):
    """Reject expression values that skipped a declared program dataflow.

    Older frames encoded ``절반`` directly in an emitted numeric effect and
    inferred the source from whichever effect happened to decrease a value.
    That makes a source an implementation guess.  Programs must now declare
    ``lookup`` and ``compute`` explicitly; this final guard prevents a legacy
    emit-only frame from quietly reintroducing that inference.
    """
    expressions = {str(row[2]) for row in facts if len(row) == 3 and _quantity_value(row[2], quantities)}
    if not expressions:
        return deepcopy(facts), None, {}
    return [], "undeclared_state_value", {}


def execute(program, roles, *, prior_facts=(), quantities=None,
            mutable_predicates=(), numeric_updates=None, overrides=(), programs=None,
            provided=None, provided_facts=(), allowed_leftovers=(), event_id=None,
            depth=0, limit=32):
    """Bind, read state, calculate, then emit one action's effects.

    All callers receive the same unresolved reason instead of deciding locally
    whether a missing value means no change.  ``facts`` are suitable for both
    a real timeline and a caller-provided hypothetical timeline.
    """
    if depth >= limit:
        return {"facts": [], "missing": {}, "conflicts": {}, "leftover": {},
                "reachable": [], "values": {}, "reason": "call_limit", "bindings": {}}

    def nested_program(step):
        action, version = step.get("action"), step.get("definition_version")
        if not isinstance(action, str):
            return None
        # A recorded definition version is part of the action meaning.  Do
        # not fall back to a newer same-named program when that exact version
        # is missing; an unversioned direct program may still use its name.
        if version is not None:
            return (programs or {}).get("%s@%s" % (action, version))
        return (programs or {}).get(action)

    def possible(current, values, level=depth):
        """Conservative effects of a program whose inputs are still incomplete.

        A missing outer role must not hide effects inside a called action.  We
        retain unresolved variables in the footprint, which lets the state
        layer block an old answer for every named relation that could change.
        This is an uncertainty calculation, not a speculative execution.
        """
        if level >= limit:
            return []
        from relational_semantics import asserted, substitute

        def resolve(raw):
            if isinstance(raw, dict) and isinstance(raw.get("var"), str):
                return values.get(raw["var"], "$" + raw["var"])
            if isinstance(raw, str) and raw.startswith("$"):
                return values.get(raw[1:], raw)
            return raw

        out = []
        for step in current.get("steps") or []:
            if step.get("op") == "emit":
                out.extend(asserted(substitute({"triples": step.get("triples") or []}, values)))
            elif step.get("op") == "call":
                nested = nested_program(step)
                if not isinstance(nested, dict):
                    continue
                role_map = {slot: resolved for slot, raw in (step.get("roles") or {}).items()
                            for resolved in [resolve(raw)]
                            if not (isinstance(resolved, str) and resolved.startswith("$"))}
                child = bind(nested, role_map)
                out.extend(possible(nested, child["values"], level + 1))
        return out

    bound = bind(program, roles, overrides)
    # A caller may explicitly classify a surface role as event provenance
    # rather than a program input (the Korean doer on an actor-independent
    # selection is one example).  The executor itself never guesses such a
    # role: every other leftover blocks execution and stays visible.
    allowed_leftovers = set(allowed_leftovers or ())
    if allowed_leftovers:
        bound = {**bound, "leftover": {slot: value for slot, value in bound["leftover"].items()
                                        if slot not in allowed_leftovers}}
    if bound["missing"] or bound["conflicts"] or bound["leftover"]:
        return {**bound, "facts": [], "reachable": possible(program, bound["values"]),
                "reason": None, "bindings": {}}
    steps = program.get("steps") or []
    special = any(step.get("op") != "emit" for step in steps)
    emitted, bindings = (list(bound["facts"]), {}) if not special else ([], {})
    if special:
        from marco.reasoning.inference import current_facts
        from relational_semantics import asserted, substitute

        values = {**bound["values"], **dict(provided or {})}
        if event_id is not None:
            values["event_id"] = event_id
        supplied_facts = {tuple(row) for row in (provided_facts or ())
                          if isinstance(row, (list, tuple)) and len(row) == 3}

        def value(raw):
            if isinstance(raw, dict) and isinstance(raw.get("var"), str):
                return values.get(raw["var"])
            if isinstance(raw, str) and raw.startswith("$"):
                return values.get(raw[1:])
            if isinstance(raw, list):
                parts = [value(part) for part in raw]
                return " ".join(parts) if all(isinstance(part, str) for part in parts) else None
            return raw

        def potential():
            """Effects this event may still change if its missing read arrives.

            Even a failed lookup is not a no-op.  The state layer uses this
            footprint to avoid confirming an old value for a subject the
            incomplete action could have changed.
            """
            return possible(program, values)

        def state_now():
            # Steps are an ordered program, not an unordered effect list.
            # A lookup or guard after an emit must observe that earlier emit,
            # while a lookup before it still sees only the incoming state.
            return current_facts(list(prior_facts) + [
                {"triple": row, "evidence": {}} for row in emitted],
                mutable_predicates or [], numeric_updates or {})[0]

        for step in steps:
            op = step.get("op")
            if op == "lookup":
                subject, predicate = value(step.get("subject")), value(step.get("predicate"))
                name = step.get("into")
                if not isinstance(name, str) or not name:
                    return {**bound, "facts": [], "reachable": potential(), "reason": "invalid_program", "bindings": bindings}
                if name in (provided or {}):
                    values[name] = provided[name]; bindings[name] = provided[name]
                    continue
                state = state_now()
                found = [row["triple"][2] for row in state
                         if row["triple"][0] == subject and row["triple"][1] == predicate]
                if len(found) != 1:
                    missing_reason = step.get("missing_reason")
                    if not isinstance(missing_reason, str) or not missing_reason:
                        missing_reason = "lookup_missing" if not found else "lookup_ambiguous"
                    return {**bound, "facts": [], "reachable": potential(), "reason":
                            missing_reason, "bindings": bindings,
                            "need": {"kind": "lookup", "into": name, "subject": subject,
                                     "predicate": predicate, "candidates": found}}
                values[name] = found[0]; bindings[name] = found[0]
            elif op == "select":
                predicate, expected = value(step.get("predicate")), value(step.get("value"))
                name = step.get("into")
                if not isinstance(name, str) or not name:
                    return {**bound, "facts": [], "reachable": potential(), "reason": "invalid_program", "bindings": bindings}
                if name in (provided or {}):
                    values[name] = provided[name]; bindings[name] = provided[name]
                    continue
                state = state_now()
                found = [row["triple"][0] for row in state
                         if row["triple"][1] == predicate and row["triple"][2] == expected]
                if len(found) != 1:
                    return {**bound, "facts": [], "reachable": potential(), "reason":
                            "select_missing" if not found else "select_ambiguous", "bindings": bindings,
                            "need": {"kind": "select", "into": name, "predicate": predicate,
                                     "value": expected, "candidates": found}}
                values[name] = found[0]; bindings[name] = found[0]
            elif op == "compute":
                name, operator = step.get("into"), step.get("operator")
                left, right = value(step.get("left")), value(step.get("right"))
                if not isinstance(name, str) or not str(left).lstrip("-").isdigit() or not str(right).lstrip("-").isdigit():
                    return {**bound, "facts": [], "reachable": potential(), "reason": "compute_operand", "bindings": bindings}
                left, right = int(left), int(right)
                if operator == "+": result = left + right
                elif operator == "-": result = left - right
                elif operator == "*": result = left * right
                elif operator == "/" and right and left % right == 0: result = left // right
                elif operator == "/" and right:
                    return {**bound, "facts": [], "reachable": potential(),
                            "reason": "compute_indivisible", "bindings": bindings}
                else:
                    return {**bound, "facts": [], "reachable": potential(), "reason": "compute_undefined", "bindings": bindings}
                values[name] = str(result); bindings[name] = str(result)
            elif op == "when":
                wanted = step.get("fact")
                if not isinstance(wanted, list) or len(wanted) != 3:
                    return {**bound, "facts": [], "reachable": potential(), "reason": "invalid_program", "bindings": bindings}
                expected = tuple(value(part) for part in wanted)
                state = state_now()
                known = [tuple(row["triple"]) for row in state
                         if tuple(row["triple"][:2]) == expected[:2]]
                if expected not in known:
                    # A known value for this state property contradicts the
                    # guard.  No value leaves it unknown; absence must not
                    # masquerade as a confirmed no-op.
                    if expected in supplied_facts:
                        continue
                    # A false guard is a known no-op at this event time; it
                    # is not missing state and must not invite a later fact
                    # to rewrite the past.  Only the unknown branch exposes
                    # a fact request to the context layer.
                    if known:
                        return {**bound, "facts": [], "reachable": potential(),
                                "reason": "condition_false", "bindings": bindings,
                                "need": None}
                    reason = "condition_unknown"
                    return {**bound, "facts": [], "reachable": potential(), "reason": reason, "bindings": bindings,
                            "need": {"kind": "condition", "fact": list(expected)}}
            elif op == "relation":
                # A relationship occurrence is not the tuple of its
                # participants.  The event envelope supplies a stable id and
                # this generic instruction stores the participant indexes as
                # ordinary binary facts.  Consequently two promises between
                # the same people retain separate state and evidence.
                kind, actor, other = (value(step.get("kind")), value(step.get("actor")),
                                      value(step.get("other")))
                status = value(step.get("status"))
                into = step.get("into", "relation")
                predicate = value(step.get("predicate", "relation_status"))
                mode = step.get("mode", "create")
                if (not all(isinstance(part, str) and part for part in (kind, actor, other, status, predicate))
                        or not isinstance(into, str) or not into):
                    return {**bound, "facts": [], "reachable": potential(), "reason": "invalid_program", "bindings": bindings}
                state = state_now()
                rows = [tuple(row["triple"]) for row in state]
                indexed = {}
                for subject, relation, object_ in rows:
                    indexed.setdefault(subject, {})[relation] = object_
                candidates = sorted(subject for subject, fields in indexed.items()
                                    if fields.get("relation_kind") == kind
                                    and fields.get("relation_actor") == actor
                                    and fields.get("relation_other") == other
                                    and fields.get(predicate) == "active")
                selected = values.get(into)
                if mode == "create":
                    # `event_id` is injected by the shared event boundary.
                    # It is deliberately not an input role, and no surface
                    # form or domain action name appears in this algorithm.
                    event_id = values.get("event_id")
                    if not isinstance(event_id, str) or not event_id:
                        return {**bound, "facts": [], "reachable": potential(), "reason": "missing_event_identity", "bindings": bindings}
                    selected = "relation:" + event_id
                    values[into] = selected; bindings[into] = selected
                    emitted.extend([[selected, "relation_kind", kind],
                                    [selected, "relation_actor", actor],
                                    [selected, "relation_other", other],
                                    [selected, predicate, status]])
                elif mode == "update":
                    if selected is not None and selected not in candidates:
                        return {**bound, "facts": [], "reachable": potential(), "reason": "invalid_relation_choice", "bindings": bindings}
                    if selected is None:
                        if not candidates:
                            return {**bound, "facts": [], "reachable": potential(), "reason": "relation_missing", "bindings": bindings,
                                    "need": {"kind": "relation", "into": into, "relationship":
                                             {"kind": kind, "actor": actor, "other": other}, "candidates": []}}
                        if len(candidates) != 1:
                            return {**bound, "facts": [], "reachable": potential(), "reason": "relation_ambiguous", "bindings": bindings,
                                    "need": {"kind": "relation", "into": into, "relationship":
                                             {"kind": kind, "actor": actor, "other": other}, "candidates": candidates}}
                        selected = candidates[0]
                    values[into] = selected; bindings[into] = selected
                    emitted.append([selected, predicate, status])
                else:
                    return {**bound, "facts": [], "reachable": potential(), "reason": "invalid_program", "bindings": bindings}
            elif op == "call":
                target = step.get("action")
                nested = nested_program(step)
                role_map = {key: value(raw) for key, raw in (step.get("roles") or {}).items()}
                if not isinstance(nested, dict):
                    return {**bound, "facts": [], "reachable": potential(), "reason": "unknown_call", "bindings": bindings}
                called = execute(nested, role_map, prior_facts=list(prior_facts) + [
                    {"triple": row, "evidence": {}} for row in emitted], quantities=quantities,
                    mutable_predicates=mutable_predicates, numeric_updates=numeric_updates,
                    programs=programs, event_id=event_id, depth=depth + 1, limit=limit)
                if called.get("reason") or called.get("missing") or called.get("conflicts"):
                    return {**bound, "facts": [], "reachable": potential(), "reason": called.get("reason") or "call_unresolved",
                            "bindings": {**bindings, **called.get("bindings", {})}}
                emitted.extend(called["facts"]); bindings.update(called.get("bindings", {}))
            elif op == "emit":
                emitted.extend(asserted(substitute({"triples": step.get("triples") or []}, values)))
            else:
                return {**bound, "facts": [], "reachable": potential(), "reason": "invalid_program", "bindings": bindings}
    facts, reason, measured = resolve_state_values(
        emitted, prior_facts, quantities=quantities,
        mutable_predicates=mutable_predicates, numeric_updates=numeric_updates or {})
    return {**bound, "facts": facts if reason is None else [],
            "reachable": facts if reason is None else bound["reachable"],
            "reason": reason, "bindings": {**bindings, **measured}, "need": None}



import json as _json

_IDX_SCHEMA_IN = "nai-action-catalog-v1"
_IDX_SCHEMA_OUT = "nai-action-catalog-index-v1"
_IDX_CEIL = {"max_catalog_entries": 256, "max_candidate_terms": 2, "max_program_steps": 128,
             "max_call_depth": 32, "max_expanded_steps": 1024, "max_json_nodes": 4096,
             "max_catalog_bytes": 262144}
_IDX_FLAGS = {"identity_verified": False, "projection_adapter_pending": True,
              "footprints_available": False, "candidate_enumeration_ready": False,
              "step_semantics_validated": False}
_IDX_ENTRY_FIELDS = ("id", "version", "program", "composable", "roles", "allowed_compute_operators")


_IDX_MAX_NODES = 4096
_IDX_MAX_BYTES = 262144
_IDX_MAX_PATH = 1024


def _idx_path(path, seg):
    """Bounded path builder; segments are already size-validated, total length is capped."""
    if len(path) + len(seg) > _IDX_MAX_PATH:
        return path if path.endswith("...") else path + "..."
    return path + seg


def _idx_prewalk(root):
    """Iterative structure/resource check; returns (nodes, est_bytes, gaps) without copying.

    Node cap is reserved against visited + pending + new children (+ map keys) BEFORE any
    container is traversed or pushed; the byte budget is enforced incrementally."""
    nodes, size, pending = 0, 0, 1
    stack = [(root, "$", 0, ())]
    while stack:
        node, path, depth, active = stack.pop()
        pending -= 1
        nodes += 1
        if nodes > _IDX_MAX_NODES:
            return nodes, size, [{"code": "too_many_nodes", "path": path}]
        if depth > 64:
            return nodes, size, [{"code": "too_deep", "path": path}]
        if size > _IDX_MAX_BYTES:
            return nodes, size, [{"code": "too_many_bytes", "path": path}]
        t = type(node)
        if t is dict or t is list:
            for a in active:
                if a is node:
                    return nodes, size, [{"code": "cycle", "path": path}]
            count = len(node)
            reserve = 2 * count if t is dict else count
            if nodes + pending + reserve > _IDX_MAX_NODES:
                return nodes, size, [{"code": "too_many_nodes", "path": path}]
            size += 2 + count
            if size > _IDX_MAX_BYTES:
                return nodes, size, [{"code": "too_many_bytes", "path": path}]
            nxt = active + (node,)
            if t is dict:
                for k, v in node.items():
                    if type(k) is not str:
                        return nodes, size, [{"code": "non_string_key", "path": path}]
                    nodes += 1
                    if len(k) > _IDX_MAX_BYTES or size + len(k) > _IDX_MAX_BYTES:
                        return nodes, size, [{"code": "too_many_bytes", "path": path}]
                    try:
                        size += len(k.encode("utf-8")) + 4
                    except UnicodeError:
                        return nodes, size, [{"code": "bad_unicode", "path": path}]
                    if size > _IDX_MAX_BYTES:
                        return nodes, size, [{"code": "too_many_bytes", "path": path}]
                    stack.append((v, _idx_path(path, "." + k), depth + 1, nxt))
                    pending += 1
            else:
                for i, v in enumerate(node):
                    stack.append((v, _idx_path(path, "[%d]" % i), depth + 1, nxt))
                    pending += 1
        elif t is str:
            if len(node) > _IDX_MAX_BYTES or size + len(node) > _IDX_MAX_BYTES:
                return nodes, size, [{"code": "too_many_bytes", "path": path}]
            try:
                size += len(node.encode("utf-8")) + 2
            except UnicodeError:
                return nodes, size, [{"code": "bad_unicode", "path": path}]
            if size > _IDX_MAX_BYTES:
                return nodes, size, [{"code": "too_many_bytes", "path": path}]
        elif t is bool or node is None:
            size += 5
        elif t is int:
            if node.bit_length() > 1024:
                return nodes, size, [{"code": "integer_too_large", "path": path}]
            size += node.bit_length() // 3 + 2
        elif t is float:
            if node != node or node in (float("inf"), float("-inf")):
                return nodes, size, [{"code": "non_finite", "path": path}]
            size += 24
        else:
            return nodes, size, [{"code": "non_json", "path": path}]
    return nodes, size, []


def _idx_gap(gaps):
    out = {"schema": _IDX_SCHEMA_OUT, "status": "gap", "programs": [], "gaps": gaps}
    out.update(_IDX_FLAGS)
    return out


def _idx_str(v):
    return type(v) is str and v != ""


def _idx_slot_map(m, path, gaps):
    if type(m) is not dict:
        gaps.append({"code": "bad_slot_map", "path": path})
        return []
    valid = []
    for k, v in m.items():
        if not _idx_str(k) or not _idx_str(v):
            gaps.append({"code": "bad_slot", "path": path + "." + (k if type(k) is str else "<non-string-key>")})
        else:
            valid.append(v)
    return valid


def _idx_entry(e, path, limits, gaps):
    if type(e) is not dict:
        gaps.append({"code": "bad_entry", "path": path})
        return
    missing = [f for f in _IDX_ENTRY_FIELDS if f not in e]
    for f in missing:
        gaps.append({"code": "missing_field", "path": path + "." + f})
    if missing:
        return
    eid, ver, prog = e["id"], e["version"], e["program"]
    if not _idx_str(eid):
        gaps.append({"code": "bad_id", "path": path + ".id"})
    if not (_idx_str(ver) or type(ver) is int):
        gaps.append({"code": "bad_version", "path": path + ".version"})
    if type(e["composable"]) is not bool:
        gaps.append({"code": "bad_composable", "path": path + ".composable"})
    ops = e["allowed_compute_operators"]
    if type(ops) is not list or any(type(o) is not str for o in ops):
        gaps.append({"code": "bad_operator_list", "path": path + ".allowed_compute_operators"})
    if type(prog) is not dict:
        gaps.append({"code": "bad_program", "path": path + ".program"})
        return
    if prog.get("schema") != SCHEMA:
        gaps.append({"code": "schema_mismatch", "path": path + ".program.schema"})
    if prog.get("action") != eid:
        gaps.append({"code": "action_mismatch", "path": path + ".program.action"})
    dv = prog.get("definition_version")
    if type(dv) is not type(ver) or dv != ver:
        gaps.append({"code": "version_mismatch", "path": path + ".program.definition_version"})
    steps = prog.get("steps")
    if type(steps) is not list:
        gaps.append({"code": "bad_steps", "path": path + ".program.steps"})
    elif type(limits.get("max_program_steps")) is int and len(steps) > limits["max_program_steps"]:
        gaps.append({"code": "too_many_steps", "path": path + ".program.steps"})
    sig = prog.get("signature")
    if type(sig) is not dict:
        gaps.append({"code": "bad_signature", "path": path + ".program.signature"})
        return
    sp = path + ".program.signature"
    surface = _idx_slot_map(sig.get("role_slots"), sp + ".role_slots", gaps)
    surface += _idx_slot_map(sig.get("open_roles"), sp + ".open_roles", gaps)
    fixed = sig.get("fixed_values")
    if type(fixed) is not dict or any(not _idx_str(k) for k in fixed):
        gaps.append({"code": "bad_fixed_values", "path": sp + ".fixed_values"})
    roles = e["roles"]
    if type(roles) is not dict:
        gaps.append({"code": "bad_roles", "path": path + ".roles"})
        return
    if set(roles) != set(surface):
        gaps.append({"code": "role_coverage_mismatch", "path": path + ".roles"})
    for k, meta in roles.items():
        rp = path + ".roles." + str(k)
        if type(meta) is not dict or not _idx_str(meta.get("type_ref")) \
                or meta.get("presence") not in ("required", "optional") \
                or "coreference_group" not in meta \
                or not (meta["coreference_group"] is None or _idx_str(meta["coreference_group"])):
            gaps.append({"code": "bad_role_declaration", "path": rp})


def _idx_index_impl(catalog):
    nodes, est, gaps = _idx_prewalk(catalog)
    if gaps or est > 262144:
        return _idx_gap(gaps or [{"code": "too_many_bytes", "path": "$"}])
    try:
        encoded = _json.dumps(catalog, ensure_ascii=False, allow_nan=False).encode("utf-8")
        if len(encoded) > 262144:
            return _idx_gap([{"code": "too_many_bytes", "path": "$"}])
        cat = _json.loads(encoded)
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
        return _idx_gap([{"code": "malformed", "path": "$"}])
    if type(cat) is not dict:
        return _idx_gap([{"code": "bad_envelope", "path": "$"}])
    for f in ("schema", "catalog_id", "graph", "limits", "programs"):
        if f not in cat:
            gaps.append({"code": "missing_field", "path": "$." + f})
    if gaps:
        return _idx_gap(gaps)
    if cat["schema"] != _IDX_SCHEMA_IN:
        gaps.append({"code": "schema_mismatch", "path": "$.schema"})
    if not _idx_str(cat["catalog_id"]):
        gaps.append({"code": "bad_catalog_id", "path": "$.catalog_id"})
    graph, limits, programs = cat["graph"], cat["limits"], cat["programs"]
    if type(graph) is not dict:
        gaps.append({"code": "bad_graph", "path": "$.graph"})
    else:
        for f in ("graph_id", "projection_fingerprint"):
            if not _idx_str(graph.get(f)):
                gaps.append({"code": "bad_graph_field", "path": "$.graph." + f})
        sha = graph.get("effective_graph_sha256")
        if not (type(sha) is str and len(sha) == 64 and all(c in "0123456789abcdef" for c in sha)):
            gaps.append({"code": "bad_graph_sha256", "path": "$.graph.effective_graph_sha256"})
    if type(limits) is not dict:
        gaps.append({"code": "bad_limits", "path": "$.limits"})
        limits = {}
    else:
        for key, ceil in _IDX_CEIL.items():
            v = limits.get(key)
            if type(v) is not int or v < 1 or v > ceil:
                gaps.append({"code": "bad_limit", "path": "$.limits." + key})
        if type(limits.get("max_json_nodes")) is int and nodes > limits["max_json_nodes"]:
            gaps.append({"code": "too_many_nodes", "path": "$"})
        if type(limits.get("max_catalog_bytes")) is int and len(encoded) > limits["max_catalog_bytes"]:
            gaps.append({"code": "too_many_bytes", "path": "$"})
    if type(programs) is not list:
        gaps.append({"code": "bad_programs", "path": "$.programs"})
        return _idx_gap(gaps)
    if type(limits.get("max_catalog_entries")) is int and len(programs) > limits["max_catalog_entries"]:
        gaps.append({"code": "too_many_entries", "path": "$.programs"})
    seen = set()
    for i, e in enumerate(programs):
        p = "$.programs[%d]" % i
        _idx_entry(e, p, limits, gaps)
        if type(e) is dict and "id" in e and "version" in e:
            key = (e["id"], type(e["version"]).__name__, e["version"])
            try:
                dup = key in seen
                seen.add(key)
            except TypeError:
                dup = False
            if dup:
                gaps.append({"code": "duplicate_identity", "path": p})
    if gaps:
        return _idx_gap(gaps)
    out = {"schema": _IDX_SCHEMA_OUT, "status": "indexed", "catalog_id": cat["catalog_id"],
           "claimed_identity": {"catalog_id": cat["catalog_id"], "graph": graph},
           "limits": limits, "programs": programs, "gaps": []}
    out.update(_IDX_FLAGS)
    return out


def index_action_catalog(catalog):
    """Validate a catalog envelope and index claimed identities; nothing here is verified or derived.

    The whole call (prewalk, encoding, envelope validation) is guarded so malformed input
    always yields a gap result; valid gap flags are produced by the implementation, not swallowed."""
    try:
        return _idx_index_impl(catalog)
    except (TypeError, ValueError, OverflowError, RecursionError, UnicodeError):
        return _idx_gap([{"code": "malformed", "path": "$"}])


_FP_OPS = ('emit', 'lookup', 'select', 'compute', 'when', 'call')
_FP_SCHEMA = 'nai-action-catalog-footprint-v1'
_FP_CK = {'lookup': 'lookup_unique_success', 'select': 'select_unique_success',
          'compute': 'compute_numeric_success', 'when': 'when_present'}
_FP_RK = {'lookup': 'lookup_result', 'select': 'select_result', 'compute': 'compute_result'}
_FP_FIELDS = {'lookup': ('subject', 'predicate'), 'select': ('predicate', 'value'),
              'compute': ('left', 'right'), 'when': ('fact',)}


class _FpGap(Exception):
    pass


def _fp_id(path, kind, n):
    return _json.dumps(list(path) + [kind, n], separators=(',', ':'), ensure_ascii=False)


def _fp_ref(path, mode):
    return {'path': list(path), 'resolution_mode': mode}


def _fp_key(e):
    return (e['id'], type(e['version']).__name__, e['version'])


def _fp_env(d, status, programs, gaps, full):
    ok = status == 'described'
    flags = {'footprints_derived': ok, 'step_semantics_validated': ok, 'candidate_enumeration_ready': False}
    out = {'schema': _FP_SCHEMA, 'status': status, 'catalog_id': d.get('catalog_id'),
           'claimed_identity': d.get('claimed_identity'), 'identity_verified': False,
           'projection_adapter_pending': True}
    if full:
        out['limits'] = d.get('limits')
        flags.update({'identity_verified': False, 'projection_adapter_pending': True})
    out.update({'programs': programs, 'gaps': gaps, 'flags': flags})
    return out


def _fp_build(d):
    lim, progs = d['limits'], d['programs']
    depth_cap = min(lim['max_call_depth'], 32)
    root_cap = min(lim['max_expanded_steps'], 1024)
    glob_cap = min(lim['max_json_nodes'], 4096)
    byte_cap = min(lim['max_catalog_bytes'], 262144)
    reg, strs = {}, set()
    for i, e in enumerate(progs):
        s = '%s@%s' % (e['id'], e['version'])
        if s in strs:
            raise _FpGap('ambiguous_executor_registry_key')
        strs.add(s)
        reg[_fp_key(e)] = (i, e)
    st = {'nodes': 0, 'bytes': 0, 'steps': 0}

    def charge(obj):
        n, b, stack = 0, 1, [obj]
        esc = {'"': 2, '\\': 2, '\n': 2, '\r': 2, '\t': 2, '\b': 2, '\f': 2}

        def sb(s):
            nonlocal b
            b += 2
            for ch in s:
                o = ord(ch)
                if o < 0x20 or ch == '"' or ch == '\\':
                    b += esc.get(ch, 6)
                elif o < 0x80:
                    b += 1
                elif o < 0x800:
                    b += 2
                elif o < 0x10000:
                    b += 3
                else:
                    b += 4
                if st['bytes'] + b > byte_cap:
                    raise _FpGap('output_byte_cap_exhausted')

        while stack:
            x = stack.pop()
            n += 1
            if st['nodes'] + n > glob_cap:
                raise _FpGap('output_node_cap_exhausted')
            if type(x) is dict:
                n += len(x)
                if st['nodes'] + n + len(stack) + len(x) > glob_cap:
                    raise _FpGap('output_node_cap_exhausted')
                b += 2
                for k in x:
                    if type(k) is not str:
                        raise TypeError('non-str json key')
                    sb(k)
                    b += 2
                stack.extend(x.values())
            elif type(x) is list:
                if st['nodes'] + n + len(stack) + len(x) > glob_cap:
                    raise _FpGap('output_node_cap_exhausted')
                b += 2 + len(x)
                stack.extend(x)
            elif type(x) is str:
                sb(x)
            elif x is None or x is True:
                b += 4
            elif x is False:
                b += 5
            elif type(x) is int:
                b += len(str(x))
            elif type(x) is float:
                if st['bytes'] + b + 32 > byte_cap:
                    raise _FpGap('output_byte_cap_exhausted')
                b += len(_json.dumps(x))
            else:
                raise TypeError('non-json value')
            if st['bytes'] + b > byte_cap:
                raise _FpGap('output_byte_cap_exhausted')
        st['nodes'] += n
        st['bytes'] += b
        return obj

    charge(_fp_env(d, 'described', [], [], True))

    def inst(idx, e, path, encl, tail, pre, depth, active, T, rs, call_sid):
        prog = e['program']
        scope = _fp_id(path, 'scope', 0)
        tx = _fp_id(path, 'cond', 0)
        txs = [tx] + encl
        src = ['programs', idx, 'program']
        cnt = {}

        def nid(kind):
            cnt[kind] = cnt.get(kind, 0) + 1
            return _fp_id(path, kind, cnt[kind])

        for m in e['roles'].values():
            if m['presence'] != 'required':
                raise _FpGap('optional_role_execution_unproved')
        cur = [pre]
        pn = [1]

        def phase(added, req):
            pid = nid('phase')
            T['phases'].append(charge({'id': pid, 'scope_id': scope, 'ordinal': pn[0],
                                       'predecessor_phase_id': cur[0],
                                       'added_attempted_write_ids': list(added),
                                       'requires_condition_ids': list(req)}))
            pn[0] += 1
            cur[0] = pid

        succ, vars_, wids = [], {}, []
        for o, s in enumerate(prog['steps']):
            rs[0] += 1
            st['steps'] += 1
            if rs[0] > root_cap:
                raise _FpGap('expanded_step_cap_exhausted')
            if st['steps'] > glob_cap:
                raise _FpGap('global_expansion_cap_exhausted')
            if type(s) is not dict or type(s.get('op')) is not str:
                raise _FpGap('malformed_step')
            op = s['op']
            if op not in _FP_OPS:
                raise _FpGap('unsupported_instruction')
            sid = _fp_id(path, 'step', o)
            sref = src + ['steps', o]
            req = [tail[0]] if tail[0] else []
            pre_ph = cur[0]
            srd, spr, swr, refs = [], [], [], []
            pos = None
            if op == 'emit':
                rows = s.get('triples')
                if type(rows) is not list or any(type(r) is not list or len(r) != 3 for r in rows):
                    raise _FpGap('malformed_step')
                m = 'substitute_then_asserted_joined'
                refs = [_fp_ref(sref + ['triples'], m)]
                for j, r in enumerate(rows):
                    w = nid('write')
                    T['writes'].append(charge({
                        'id': w, 'source_step_id': sid, 'state_phase_id': cur[0], 'raw_template': r,
                        'template_ref': _fp_ref(sref + ['triples', j], m), 'resolution_mode': m,
                        'requires_condition_ids': req + txs, 'transaction_success_required': True}))
                    swr.append(w)
                if swr:
                    phase(swr, req)
                    wids.extend(swr)
            elif op == 'call':
                v = s.get('definition_version')
                if 'definition_version' not in s or not (_idx_str(v) or type(v) is int):
                    raise _FpGap('missing_exact_call_version')
                a = s.get('action')
                if not _idx_str(a) or (a, type(v).__name__, v) not in reg:
                    raise _FpGap('missing_call_target')
                roles = s.get('roles')
                if type(roles) is not dict or any(not _idx_str(k) for k in roles):
                    raise _FpGap('malformed_call_role_map')
                ti, ce = reg[(a, type(v).__name__, v)]
                if any(k not in ce['roles'] for k in roles):
                    raise _FpGap('unknown_child_role')
                if any(m['presence'] == 'required' and k not in roles for k, m in ce['roles'].items()):
                    raise _FpGap('missing_required_child_role')
                key = _fp_key(ce)
                if key in active:
                    raise _FpGap('call_cycle')
                if depth + 1 >= depth_cap:
                    raise _FpGap('call_depth_exhausted')
                cpath = path + ['steps', o, 'call', a, '@', v]
                ctx = _fp_id(cpath, 'cond', 0)
                pos = len(T['steps'])
                T['steps'].append(None)
                cw = inst(ti, ce, cpath, txs, [tail[0]], cur[0], depth + 1, active | {key}, T, rs, sid)
                cs = nid('cond')
                T['conds'].append(charge({'id': cs, 'kind': 'call_success', 'source_step_id': sid,
                                          'scope_id': scope, 'depends_on_ids': [ctx] + req}))
                succ.append(cs)
                tail[0] = cs
                rmap = []
                for k, rv in roles.items():
                    rr = _fp_ref(sref + ['roles', k], 'execute_value')
                    refs.append(rr)
                    rmap.append({'child_slot': k, 'raw_value': rv, 'value_ref': rr,
                                 'resolution_mode': 'execute_value'})
                if cw:
                    phase(cw, [cs])
                    wids.extend(cw)
                T['bounds'].append(charge({
                    'id': nid('call'), 'source_step_id': sid,
                    'target': {'id': a, 'version': v, 'key': '%s@%s' % (a, v)},
                    'parent_pre_phase_id': pre_ph, 'child_scope_id': _fp_id(cpath, 'scope', 0),
                    'child_transaction_condition_id': ctx, 'call_success_condition_id': cs,
                    'role_map': rmap, 'child_write_ids': list(cw), 'parent_post_phase_id': cur[0]}))
            else:
                fields = _FP_FIELDS[op]
                if any(f not in s for f in fields):
                    raise _FpGap('malformed_step')
                if op == 'when':
                    if type(s['fact']) is not list or len(s['fact']) != 3:
                        raise _FpGap('malformed_step')
                else:
                    if not _idx_str(s.get('into')):
                        raise _FpGap('malformed_step')
                    if op == 'compute':
                        oper = s.get('operator')
                        if type(oper) is not str:
                            raise _FpGap('malformed_step')
                        if oper not in ('+', '-', '*', '/') or oper not in e['allowed_compute_operators']:
                            raise _FpGap('unsupported_compute_operator')
                refs = [_fp_ref(sref + [f], 'execute_value') for f in fields]
                if op != 'compute':
                    rid = nid('read')
                    T['reads'].append(charge({
                        'id': rid, 'kind': op, 'source_step_id': sid, 'state_phase_id': cur[0],
                        'raw_template': s['fact'] if op == 'when' else [s[f] for f in fields],
                        'template_ref': _fp_ref(sref + ['fact'] if op == 'when' else sref, 'execute_value'),
                        'resolution_mode': 'execute_value', 'requires_condition_ids': req}))
                    srd.append(rid)
                if op != 'when':
                    pid = nid('producer')
                    T['producers'].append(charge({
                        'id': pid, 'source_step_id': sid, 'scope_id': scope, 'variable': s['into'],
                        'kind': _FP_RK[op], 'rebinds_producer_id': vars_.get(s['into']),
                        'resolution_mode': 'executor_result_if_step_succeeds'}))
                    vars_[s['into']] = pid
                    spr.append(pid)
                cid = nid('cond')
                T['conds'].append(charge({'id': cid, 'kind': _FP_CK[op], 'source_step_id': sid,
                                          'scope_id': scope, 'depends_on_ids': req}))
                succ.append(cid)
                tail[0] = cid
            rec = {'id': sid, 'path': path + ['steps', o], 'ordinal': o, 'op': op, 'input_refs': refs,
                   'read_ids': srd, 'producer_ids': spr, 'attempted_write_ids': swr,
                   'pre_phase_id': pre_ph, 'post_phase_id': cur[0], 'requires_condition_ids': req,
                   'transaction_success_required': True}
            if pos is None:
                T['steps'].append(charge(rec))
            else:
                T['steps'][pos] = charge(rec)
        T['conds'].append(charge({
            'id': tx, 'kind': 'root_transaction_success' if call_sid is None else 'child_transaction_success',
            'source_step_id': call_sid, 'scope_id': scope, 'depends_on_ids': succ}))
        return wids

    out = []
    for i, e in enumerate(progs):
        path = ['programs', i]
        src = ['programs', i, 'program']
        sig = e['program']['signature']
        T = {k: [] for k in ('phases', 'steps', 'reads', 'producers', 'writes', 'conds', 'bounds')}
        roles = [{'slot': k, 'type_ref': m['type_ref'], 'presence': m['presence'],
                  'coreference_group': m['coreference_group'],
                  'source_ref': _fp_ref(['programs', i, 'roles', k], 'static_pointer')}
                 for k, m in e['roles'].items()]
        scope = _fp_id(path, 'scope', 0)
        desc = {
            'program_ref': {'id': e['id'], 'version': e['version'],
                            'key': '%s@%s' % (e['id'], e['version']), 'path': path},
            'signature': {'action': e['program']['action'],
                          'definition_version': e['program']['definition_version'],
                          'role_slots': list(sig['role_slots'].values()),
                          'open_roles': list(sig['open_roles'].values()),
                          'fixed_values_ref': _fp_ref(src + ['signature', 'fixed_values'], 'static_pointer'),
                          'roles': roles},
            'scope_id': scope, 'transaction_condition_id': _fp_id(path, 'cond', 0),
            'informational_calls': {'mode': 'opaque_non_executable',
                                    'source_ref': _fp_ref(src + ['calls'], 'static_pointer')},
            'phases': T['phases'], 'steps': T['steps'], 'reads': T['reads'],
            'producers': T['producers'], 'attempted_writes': T['writes'],
            'conditions': T['conds'], 'call_boundaries': T['bounds'], 'gaps': []}
        charge(desc)
        ph0 = _fp_id(path, 'phase', 0)
        T['phases'].append(charge({'id': ph0, 'scope_id': scope, 'ordinal': 0,
                                   'predecessor_phase_id': None, 'added_attempted_write_ids': [],
                                   'requires_condition_ids': []}))
        inst(i, e, path, [], [None], ph0, 0, {_fp_key(e)}, T, [0], None)
        out.append(desc)
    return _fp_env(d, 'described', out, [], True)


def describe_action_catalog(catalog):
    idx = index_action_catalog(catalog)
    d = idx if isinstance(idx, dict) else {}
    if d.get('status') != 'indexed':
        g = d.get('gaps')
        gaps = list(g) if isinstance(g, list) and g else ['index_status_not_indexed' if d else 'index_unavailable']
        return _fp_env(d, 'gap', [], gaps, False)
    try:
        return _fp_build(d)
    except _FpGap as x:
        return _fp_env(d, 'gap', [], [x.args[0]], True)
    except (KeyError, TypeError, AttributeError, ValueError, IndexError):
        return _fp_env(d, 'gap', [], ['malformed_indexed_program'], True)


def _contextual_action_fail(code, path=None):
    raise ValueError((code, path))


def _contextual_action_canon(value):
    import json
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def _contextual_action_sha(value):
    import hashlib
    return hashlib.sha256(_contextual_action_canon(value).encode('utf-8')).hexdigest()


def _contextual_action_hex(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def _contextual_action_int(value, low=0):
    return type(value) is int and value >= low


def _contextual_action_span(span, limit):
    return (isinstance(span, list) and len(span) == 2 and all(type(v) is int for v in span)
            and 0 <= span[0] <= span[1] <= limit)


def _contextual_action_nodes(value, budget):
    stack, seen = [value], 0
    while stack:
        item = stack.pop()
        seen += 1
        if seen > budget:
            return None
        if isinstance(item, dict):
            for key, sub in item.items():
                if not isinstance(key, str):
                    return None
                stack.append(sub)
        elif isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, float):
            if item != item or item in (float('inf'), float('-inf')):
                return None
        elif not (item is None or isinstance(item, (bool, int, str))):
            return None
    return seen


def _contextual_action_policy(policy, roles, catalog_limits):
    fail = _contextual_action_fail
    keys = ('schema', 'policy_id', 'association', 'world', 'closed_predicates', 'evidence_kinds',
            'allowed_term_counts', 'allow_repeated_terms', 'ranking', 'limits')
    if not isinstance(policy, dict) or set(policy) != set(keys):
        fail('policy_shape', '/projection/policy')
    if policy['schema'] != 'contextual-action-policy-v1':
        fail('policy_schema', '/projection/policy/schema')
    pid = policy['policy_id']
    if not isinstance(pid, str) or not pid.strip() or len(pid) > 128:
        fail('policy_identity', '/projection/policy/policy_id')
    if (policy['world'] != 'open' or policy['closed_predicates'] != []
            or policy['evidence_kinds'] != ['archived_positive_fact_v1']):
        fail('policy_world_scope', '/projection/policy')
    assoc = policy['association']
    akeys = ('mode', 'key_slot', 'functional_predicates', 'before_selection', 'after_selection',
             'causal_status')
    if not isinstance(assoc, dict) or set(assoc) != set(akeys):
        fail('policy_association', '/projection/policy/association')
    if (assoc['mode'] != 'pending_role_functional_key_v1'
            or assoc['before_selection'] != 'latest_prior_independent_positive_v1'
            or assoc['after_selection'] != 'latest_later_independent_positive_v1'
            or assoc['causal_status'] != 'association_assumed_v1'):
        fail('policy_association_scope', '/projection/policy/association')
    if not isinstance(assoc['key_slot'], str) or assoc['key_slot'] not in roles:
        fail('policy_association_key_slot', '/projection/policy/association/key_slot')
    functional = assoc['functional_predicates']
    if (not isinstance(functional, list) or not 1 <= len(functional) <= 64
            or any(not isinstance(p, str) or not p for p in functional)
            or len(set(functional)) != len(functional)):
        fail('policy_functional_predicates', '/projection/policy/association/functional_predicates')
    if not isinstance(catalog_limits, dict):
        fail('catalog_limits', '/projection/catalog/limits')
    max_terms = catalog_limits.get('max_candidate_terms')
    if not _contextual_action_int(max_terms, 1) or max_terms > 2:
        fail('catalog_max_candidate_terms', '/projection/catalog/limits/max_candidate_terms')
    structural = {}
    for name in ('max_call_depth', 'max_expanded_steps'):
        value = catalog_limits.get(name)
        if not _contextual_action_int(value, 1) or value > _IDX_CEIL[name]:
            fail('catalog_limit_' + name, '/projection/catalog/limits/' + name)
        structural[name] = value
    counts = policy['allowed_term_counts']
    if (not isinstance(counts, list) or not counts or len(set(counts)) != len(counts)
            or any(type(c) is not int or c not in (1, 2) or c > max_terms for c in counts)):
        fail('policy_allowed_term_counts', '/projection/policy/allowed_term_counts')
    if type(policy['allow_repeated_terms']) is not bool:
        fail('policy_allow_repeated_terms', '/projection/policy/allow_repeated_terms')
    ranking = policy['ranking']
    if not isinstance(ranking, list) or any(
            not isinstance(r, dict) or set(r) != {'key', 'direction'}
            or r['key'] not in ('support_count', 'conflict_count', 'term_count')
            or r['direction'] not in ('asc', 'desc') for r in ranking):
        fail('policy_ranking', '/projection/policy/ranking')
    if len({r['key'] for r in ranking}) != len(ranking):
        fail('policy_ranking', '/projection/policy/ranking')
    ceilings = {'max_candidates': 64, 'max_observations': 64, 'max_window_turns': 128,
                'max_pending': 16, 'max_effect_triples': 128, 'max_output_bytes': 262144}
    limits = policy['limits']
    if not isinstance(limits, dict) or set(limits) != set(ceilings):
        fail('policy_limits', '/projection/policy/limits')
    for name, high in ceilings.items():
        if not _contextual_action_int(limits[name], 1) or limits[name] > high:
            fail('policy_limit_' + name, '/projection/policy/limits/' + name)
    return {'id': pid, 'declaration_sha256': _contextual_action_sha(policy),
            'association': {'mode': assoc['mode'], 'key_slot': assoc['key_slot'],
                            'functional_predicates': list(functional),
                            'before_selection': assoc['before_selection'],
                            'after_selection': assoc['after_selection'],
                            'causal_status': assoc['causal_status']},
            'key_slot': assoc['key_slot'], 'functional': list(functional), 'counts': sorted(counts),
            'repeat': policy['allow_repeated_terms'],
            'ranking': [{'key': r['key'], 'direction': r['direction']} for r in ranking],
            'limits': dict(limits), 'catalog_limits': structural}


def _contextual_action_projection(projection):
    fail = _contextual_action_fail
    keys = ('schema', 'catalog', 'surface', 'policy', 'replies', 'required_operators', 'hypothesis_scope',
            'entry_labels', 'source_maps', 'provenance', 'fingerprint', 'catalog_description')
    if not isinstance(projection, dict) or set(projection) != set(keys):
        fail('projection_keys', '/projection')
    if projection['schema'] != 'graph-action-grounding-projection-v1':
        fail('projection_schema', '/projection/schema')
    ops = projection['required_operators']
    if (not isinstance(ops, list) or len(ops) != 2
            or set(ops) != {'relational_graph', 'contextual_action_hypothesis'}):
        fail('projection_required_operators', '/projection/required_operators')
    if projection['hypothesis_scope'] != 'provisional_nonexecuting_v1':
        fail('projection_hypothesis_scope', '/projection/hypothesis_scope')
    prov = projection['provenance']
    if not isinstance(prov, dict) or not {'graph_id', 'root_id', 'effective_graph_sha256', 'view_key',
                                          'base_origin', 'source', 'nodes', 'edges'} <= set(prov):
        fail('projection_provenance', '/projection/provenance')
    if not isinstance(prov['view_key'], list):
        fail('projection_view_key', '/projection/provenance/view_key')
    fingerprint = projection['fingerprint']
    if not isinstance(fingerprint, str) or not fingerprint:
        fail('projection_fingerprint', '/projection/fingerprint')
    catalog = projection['catalog']
    if (not isinstance(catalog, dict) or set(catalog) != {'schema', 'catalog_id', 'graph', 'limits', 'programs'}
            or catalog['schema'] != 'nai-action-catalog-v1' or not isinstance(catalog['limits'], dict)
            or not isinstance(catalog['programs'], list)):
        fail('projection_catalog', '/projection/catalog')
    graph = catalog['graph']
    if (not isinstance(graph, dict) or graph.get('projection_fingerprint') != fingerprint
            or any(graph.get(k) != prov[k] for k in ('graph_id', 'root_id', 'effective_graph_sha256',
                                                      'view_key', 'base_origin', 'source'))):
        fail('projection_catalog_graph', '/projection/catalog/graph')
    entries = catalog['programs']
    if not 1 <= len(entries) <= 64:
        fail('catalog_entry_count', '/projection/catalog/programs')
    registry = {}
    for i, entry in enumerate(entries):
        path = '/projection/catalog/programs/%d' % i
        if not isinstance(entry, dict) or set(entry) != set(_IDX_ENTRY_FIELDS):
            fail('catalog_entry_fields', path)
        if not isinstance(entry['id'], str) or not entry['id'] or type(entry['version']) not in (int, str):
            fail('catalog_entry_identity', path)
        program = entry['program']
        if (not isinstance(program, dict) or program.get('schema') != SCHEMA
                or not isinstance(program.get('signature'), dict)):
            fail('catalog_entry_program', path + '/program')
        sig = program['signature']
        if not isinstance(sig.get('role_slots'), dict) or not isinstance(sig.get('open_roles'), dict):
            fail('catalog_entry_signature', path + '/program/signature')
        if type(entry['composable']) is not bool or not isinstance(entry['roles'], dict):
            fail('catalog_entry_shape', path)
        for slot, meta in entry['roles'].items():
            if (not isinstance(slot, str) or not isinstance(meta, dict)
                    or not {'type_ref', 'presence', 'coreference_group'} <= set(meta)):
                fail('catalog_entry_role', path + '/roles/' + str(slot))
        key = '%s@%s' % (entry['id'], entry['version'])
        if key in registry:
            fail('catalog_entry_duplicate', path)
        registry[key] = program
    desc = projection['catalog_description']
    if not isinstance(desc, dict):
        fail('catalog_description', '/projection/catalog_description')
    flags = desc.get('flags')
    verified = desc.get('identity_verified', flags.get('identity_verified') if isinstance(flags, dict) else None)
    if (desc.get('schema') != 'nai-action-catalog-footprint-v1'
            or desc.get('status') != 'described' or desc.get('gaps') != []
            or desc.get('claimed_identity') != {'catalog_id': catalog['catalog_id'], 'graph': graph}
            or verified is not False
            or not isinstance(desc.get('programs'), list) or len(desc['programs']) != len(entries)):
        fail('catalog_description', '/projection/catalog_description')
    for i, (entry, d) in enumerate(zip(entries, desc['programs'])):
        dpath = '/projection/catalog_description/programs/%d' % i
        if not isinstance(d, dict):
            fail('catalog_description_entry', dpath)
        ref = d.get('program_ref')
        key = '%s@%s' % (entry['id'], entry['version'])
        if (not isinstance(ref, dict) or ref.get('id') != entry['id'] or ref.get('version') != entry['version']
                or type(ref.get('version')) is not type(entry['version']) or ref.get('key') != key
                or ref.get('path') != ['programs', i]):
            fail('catalog_description_entry', dpath + '/program_ref')
        program = entry['program']
        sig, dsig = program['signature'], d.get('signature')
        if (not isinstance(dsig, dict) or dsig.get('action') != program.get('action')
                or dsig.get('definition_version') != program.get('definition_version')
                or dsig.get('role_slots') != list(sig['role_slots'].values())
                or dsig.get('open_roles') != list(sig['open_roles'].values())
                or not isinstance(dsig.get('roles'), list)):
            fail('catalog_description_signature', dpath + '/signature')
        droles = dsig['roles']
        if (any(not isinstance(r, dict) for r in droles)
                or [r.get('slot') for r in droles] != list(entry['roles'])):
            fail('catalog_description_roles', dpath + '/signature/roles')
        for r in droles:
            meta = entry['roles'][r['slot']]
            if (r.get('type_ref') != meta['type_ref'] or r.get('presence') != meta['presence']
                    or r.get('coreference_group') != meta['coreference_group']):
                fail('catalog_description_roles', dpath + '/signature/roles')
        if (not isinstance(d.get('steps'), list) or not isinstance(d.get('attempted_writes'), list)
                or not isinstance(d.get('call_boundaries'), list)):
            fail('catalog_description_entry', dpath)
    surface = projection['surface']
    if (not isinstance(surface, dict) or not isinstance(surface.get('surface_id'), str)
            or not surface['surface_id'] or not isinstance(surface.get('roles'), list)
            or not isinstance(surface.get('case_groups'), list) or not isinstance(surface.get('limits'), dict)):
        fail('projection_surface', '/projection/surface')
    groups = {}
    for i, group in enumerate(surface['case_groups']):
        gpath = '/projection/surface/case_groups/%d' % i
        if (not isinstance(group, dict) or set(group) != {'id', 'markers'} or not isinstance(group['id'], str)
                or group['id'] in groups or not isinstance(group['markers'], list)
                or any(not isinstance(m, str) for m in group['markers'])):
            fail('surface_case_group', gpath)
        groups[group['id']] = list(group['markers'])
    roles = {}
    for i, role in enumerate(surface['roles']):
        rpath = '/projection/surface/roles/%d' % i
        if (not isinstance(role, dict)
                or set(role) != {'case_group', 'slot', 'type_ref', 'presence', 'coreference_group'}
                or not isinstance(role['slot'], str) or not role['slot'] or role['slot'] in roles):
            fail('surface_role', rpath)
        if role['case_group'] not in groups:
            fail('surface_role_case_group', rpath + '/case_group')
        if role['presence'] not in ('required', 'optional'):
            fail('surface_role_presence', rpath + '/presence')
        if role['coreference_group'] is not None and not isinstance(role['coreference_group'], str):
            fail('surface_role_coreference', rpath + '/coreference_group')
        roles[role['slot']] = role
    limit = surface['limits'].get('max_source_chars')
    if not _contextual_action_int(limit, 1):
        fail('surface_text_limit', '/projection/surface/limits/max_source_chars')
    policy = _contextual_action_policy(projection['policy'], roles, catalog['limits'])
    labels = projection['entry_labels']
    if not isinstance(labels, (list, dict)) or (isinstance(labels, list) and len(labels) != len(entries)):
        fail('projection_entry_labels', '/projection/entry_labels')
    smaps = projection['source_maps']
    smap_entries = None
    if isinstance(smaps, dict) and isinstance(smaps.get('catalog'), dict):
        smap_entries = smaps['catalog'].get('entries')
    if not isinstance(smap_entries, list) or len(smap_entries) != len(entries):
        fail('projection_source_maps', '/projection/source_maps/catalog/entries')
    return {'prov': prov, 'fingerprint': fingerprint, 'entries': entries, 'registry': registry,
            'descriptors': desc['programs'], 'surface_id': surface['surface_id'], 'roles': roles,
            'groups': groups, 'text_limit': limit, 'policy': policy, 'labels': labels,
            'catalog_limits': catalog['limits']}


def _contextual_action_evidence(evidence, proj):
    fail = _contextual_action_fail
    if (not isinstance(evidence, dict) or set(evidence) != {'schema', 'binding', 'pending', 'current_input_turn',
                                                            'observation_turns', 'archive'}):
        fail('evidence_keys', '/evidence')
    if evidence['schema'] != 'contextual-action-evidence-v1':
        fail('evidence_schema', '/evidence/schema')
    binding = evidence['binding']
    names = ('conversation_id', 'model_content_sha256', 'model_effective_key', 'graph_id', 'root_id',
             'effective_graph_sha256', 'view_key', 'language_projection_fingerprint',
             'action_projection_fingerprint', 'parser_base_sha256', 'parser_grammar_sha256',
             'installed_memory_head')
    if not isinstance(binding, dict) or set(binding) != set(names):
        fail('binding_keys', '/evidence/binding')
    prov = proj['prov']
    for name in ('graph_id', 'root_id', 'effective_graph_sha256', 'view_key'):
        if binding[name] != prov[name]:
            fail('binding_projection_mismatch', '/evidence/binding/' + name)
    if binding['action_projection_fingerprint'] != proj['fingerprint']:
        fail('binding_projection_mismatch', '/evidence/binding/action_projection_fingerprint')
    for name in ('conversation_id', 'model_effective_key', 'language_projection_fingerprint'):
        if not isinstance(binding[name], str) or not binding[name]:
            fail('binding_field', '/evidence/binding/' + name)
    for name in ('model_content_sha256', 'parser_base_sha256', 'parser_grammar_sha256', 'model_effective_key'):
        if not _contextual_action_hex(binding[name]):
            fail('binding_digest', '/evidence/binding/' + name)
    head = binding['installed_memory_head']
    if head is not None and not _contextual_action_int(head):
        fail('binding_memory_head', '/evidence/binding/installed_memory_head')
    pending = evidence['pending']
    if (not isinstance(pending, dict)
            or set(pending) != {'id', 'text', 'created_input_turn', 'pre_observation_refs'}):
        fail('pending_keys', '/evidence/pending')
    if not isinstance(pending['id'], str) or not pending['id'] or len(pending['id']) > 256:
        fail('pending_id', '/evidence/pending/id')
    text = pending['text']
    if not isinstance(text, str) or not 1 <= len(text) <= proj['text_limit']:
        fail('pending_text', '/evidence/pending/text')
    created = pending['created_input_turn']
    if not _contextual_action_int(created):
        fail('pending_created_input_turn', '/evidence/pending/created_input_turn')
    refs = pending['pre_observation_refs']
    if not isinstance(refs, list) or any(
            not isinstance(r, dict) or set(r) != {'observation_id', 'reading_revision', 'record_sha256'}
            for r in refs):
        fail('pending_pre_observation_refs', '/evidence/pending/pre_observation_refs')
    current = evidence['current_input_turn']
    if not _contextual_action_int(current) or current < created:
        fail('current_input_turn', '/evidence/current_input_turn')
    if current - created > proj['policy']['limits']['max_window_turns']:
        fail('pending_window_exceeded', '/evidence/current_input_turn')
    turns = evidence['observation_turns']
    if not isinstance(turns, list):
        fail('observation_turns', '/evidence/observation_turns')
    chron, order = {}, []
    for i, row in enumerate(turns):
        if (not isinstance(row, dict) or set(row) != {'observation_id', 'reading_revision', 'input_turn'}
                or not isinstance(row['observation_id'], str)
                or not _contextual_action_int(row['reading_revision'], 1)
                or not _contextual_action_int(row['input_turn']) or row['observation_id'] in chron):
            fail('observation_turn_row', '/evidence/observation_turns/%d' % i)
        if row['input_turn'] > current:
            fail('observation_turn_future', '/evidence/observation_turns/%d' % i)
        chron[row['observation_id']] = (row['reading_revision'], row['input_turn'])
        order.append(row['observation_id'])
    archive = evidence['archive']
    if (not isinstance(archive, dict)
            or set(archive) != {'schema', 'conversation', 'observations', 'observation_ids', 'reading_ledger', 'replay'}
            or archive['schema'] != 'reasoning-context-v11'):
        fail('archive_keys', '/evidence/archive')
    if archive['conversation'] != binding['conversation_id']:
        fail('archive_conversation_mismatch', '/evidence/archive/conversation')
    texts, ids = archive['observations'], archive['observation_ids']
    if not isinstance(texts, list) or any(not isinstance(t, str) for t in texts):
        fail('archive_observations', '/evidence/archive/observations')
    from marco.reasoning.readings import validate_ledger
    ledger = None
    try:
        ledger = validate_ledger(texts, ids, archive['reading_ledger'], max_turns=len(texts) + 1,
                                 base=binding['parser_base_sha256'])
    except Exception:
        ledger = None
    if not isinstance(ledger, dict):
        fail('archive_ledger_invalid', '/evidence/archive/reading_ledger')
    replay = archive['replay']
    if (not isinstance(replay, dict) or set(replay) != {'facts', 'fact_sources'}
            or not isinstance(replay['facts'], list)):
        fail('archive_replay', '/evidence/archive/replay')
    sources = replay['fact_sources']
    if sources is not None and (not isinstance(sources, list) or len(sources) != len(replay['facts'])):
        fail('archive_fact_sources', '/evidence/archive/replay/fact_sources')
    active = []
    for oid in ids:
        entry = ledger['records'][oid]
        record = entry['versions'][entry['active'] - 1]
        active.append({'observation_id': oid, 'reading_revision': entry['active'],
                       'record_sha256': _contextual_action_sha(record)})
        if chron.get(oid, (None, None))[0] != entry['active']:
            fail('chronology_missing', '/evidence/observation_turns')
    if order != list(ids):
        fail('chronology_order', '/evidence/observation_turns')
    seq = [chron[oid][1] for oid in ids]
    if any(seq[k] > seq[k + 1] for k in range(len(seq) - 1)):
        fail('chronology_order', '/evidence/observation_turns')
    if refs != active[:len(refs)]:
        fail('stale_source_prefix', '/evidence/pending/pre_observation_refs')
    prefix = len(refs)
    if any(seq[k] >= created for k in range(prefix)):
        fail('stale_source_prefix', '/evidence/pending/pre_observation_refs')
    if any(seq[k] < created for k in range(prefix, len(seq))):
        fail('source_prefix_incomplete', '/evidence/pending/pre_observation_refs')
    return {'binding': binding, 'pending': pending, 'current': current, 'chron': chron, 'ids': ids,
            'texts': texts, 'ledger': ledger, 'facts': replay['facts'], 'sources': sources, 'active': active}


def _contextual_action_reading(reading, proj, text):
    fail = _contextual_action_fail
    keys = ('schema', 'status', 'surface_id', 'source_scope', 'offset_unit', 'unknown_span', 'unknown_text',
            'role_candidates', 'search_complete', 'truncated', 'gaps')
    if not isinstance(reading, dict) or set(reading) != set(keys):
        fail('reading_keys', '/reading')
    status = reading['status']
    if status not in ('read', 'no_match', 'gap'):
        fail('reading_status', '/reading/status')
    if (reading['schema'] != 'unknown-action-reading-v1' or reading['surface_id'] != proj['surface_id']
            or reading['source_scope'] != 'current_clause' or reading['offset_unit'] != 'unicode_codepoint'):
        fail('reading_envelope', '/reading')
    complete = reading['search_complete']
    if ((complete is not None and type(complete) is not bool) or type(reading['truncated']) is not bool
            or not isinstance(reading['gaps'], list) or len(reading['gaps']) > 64
            or any(not isinstance(g, dict) or set(g) != {'code', 'path'} or not isinstance(g['code'], str)
                   or not g['code'] or (g['path'] is not None and not isinstance(g['path'], str))
                   for g in reading['gaps'])):
        fail('reading_completeness', '/reading')
    span, utext = reading['unknown_span'], reading['unknown_text']
    if span is None or utext is None:
        if span is not None or utext is not None:
            fail('reading_unknown_span', '/reading/unknown_span')
    elif (not _contextual_action_span(span, len(text)) or span[0] == span[1]
            or utext != text[span[0]:span[1]]):
        fail('reading_unknown_span', '/reading/unknown_span')
    cands = reading['role_candidates']
    if not isinstance(cands, list) or len(cands) > 64:
        fail('reading_role_candidates', '/reading/role_candidates')
    if status == 'read' and (span is None or not cands or reading['gaps'] or complete is not True):
        fail('reading_read_shape', '/reading')
    if status == 'no_match' and cands:
        fail('reading_no_match_candidates', '/reading/role_candidates')
    if cands and span is None:
        fail('reading_unknown_span', '/reading/unknown_span')
    roles, groups = proj['roles'], proj['groups']
    required = {s for s, r in roles.items() if r['presence'] == 'required'}
    alts = []
    for ci, cand in enumerate(cands):
        path = '/reading/role_candidates/%d' % ci
        if (not isinstance(cand, dict) or set(cand) != {'bindings', 'omitted_slots'}
                or not isinstance(cand['bindings'], list) or not isinstance(cand['omitted_slots'], list)):
            fail('reading_candidate_keys', path)
        if not cand['bindings'] or len(cand['bindings']) > len(roles):
            fail('reading_binding_count', path + '/bindings')
        present, spans, coref, occupied = {}, [], {}, []
        for bi, b in enumerate(cand['bindings']):
            bpath = path + '/bindings/%d' % bi
            if not isinstance(b, dict) or set(b) != {'slot', 'value', 'span', 'marker_span', 'chunk_span',
                                                      'case_group', 'type_ref', 'presence', 'coreference_group'}:
                fail('reading_binding_keys', bpath)
            decl = roles.get(b['slot']) if isinstance(b['slot'], str) else None
            if decl is None or b['slot'] in present:
                fail('reading_binding_slot', bpath)
            if (b['case_group'] != decl['case_group'] or b['type_ref'] != decl['type_ref']
                    or b['presence'] != decl['presence'] or b['coreference_group'] != decl['coreference_group']):
                fail('reading_binding_declaration', bpath)
            s, m, c = b['span'], b['marker_span'], b['chunk_span']
            if (not _contextual_action_span(s, len(text)) or s[0] == s[1]
                    or b['value'] != text[s[0]:s[1]]):
                fail('reading_binding_value', bpath)
            if not _contextual_action_span(m, len(text)) or not _contextual_action_span(c, len(text)):
                fail('reading_binding_spans', bpath)
            if m[0] != s[1] or c != [s[0], m[1]] or c[1] > span[0]:
                fail('reading_binding_chunk', bpath)
            marker = text[m[0]:m[1]]
            if marker != '' and marker not in groups[decl['case_group']]:
                fail('reading_binding_marker', bpath)
            for prev in occupied:
                if c[0] < prev[1] and prev[0] < c[1]:
                    fail('reading_binding_overlap', bpath)
            occupied.append(c)
            group = b['coreference_group']
            if group is not None:
                if group in coref and coref[group] != b['value']:
                    fail('reading_coreference_value', bpath)
                coref[group] = b['value']
            present[b['slot']] = b['value']
            spans.append([b['slot'], list(s), list(m), list(c)])
        omitted = cand['omitted_slots']
        if (any(not isinstance(o, str) for o in omitted) or len(set(omitted)) != len(omitted)
                or sorted(omitted) != sorted(set(roles) - set(present))):
            fail('reading_omitted_slots', path + '/omitted_slots')
        if not required <= set(present):
            fail('reading_required_role_missing', path + '/bindings')
        alts.append({'index': ci, 'present': present, 'spans': spans})
    return alts


def _contextual_action_qualify(fact, src, ev, sections, excluded):
    binding, ids = ev['binding'], ev['ids']
    if (not isinstance(src, dict) or set(src) != {'observation_id', 'reading_revision'}
            or not isinstance(fact, dict)):
        return None
    oid, rev = src['observation_id'], src['reading_revision']
    entry = ev['ledger']['records'].get(oid) if isinstance(oid, str) else None
    if entry is None or entry['active'] != rev:
        return None
    record = entry['versions'][rev - 1]
    if record['unavailable'] or not isinstance(record.get('parsed'), dict):
        return None
    if (record.get('parser_base_sha256') != binding['parser_base_sha256']
            or not _contextual_action_hex(record.get('parser_grammar_sha256'))):
        return None
    head = record.get('installed_memory_head')
    if binding['installed_memory_head'] is None:
        if head is not None:
            return None
    elif head is not None and head > binding['installed_memory_head']:
        return None
    evidence = fact.get('evidence')
    if not isinstance(evidence, dict):
        return None
    turn = evidence.get('turn')
    if (type(turn) is not int or not 0 <= turn < len(ids) or ids[turn] != oid
            or evidence.get('source') != record['source'] or ev['texts'][turn] != record['source']):
        return None
    chron = ev['chron'].get(oid)
    if chron is None or chron[0] != rev:
        return None
    triple = fact.get('triple')
    if (not isinstance(triple, list) or len(triple) != 3 or any(type(v) is not str for v in triple)
            or fact.get('polarity', True) is not True or fact.get('modality', 'asserted') != 'asserted'
            or any(fact.get(k) for k in excluded) or 'action_event' in triple):
        return None
    parsed = record['parsed']
    archived = parsed.get('facts')
    if not isinstance(archived, list) or len(archived) != 1 or any(parsed.get(k) for k in sections):
        return None
    stripped = {k: v for k, v in fact.items() if k != 'evidence'}
    stripped['evidence'] = {k: v for k, v in evidence.items() if k not in ('turn', 'source')}
    if _contextual_action_canon(archived[0]) != _contextual_action_canon(stripped):
        return None
    record_sha = _contextual_action_sha(record)
    fact_sha = _contextual_action_sha(archived[0])
    row_id = _contextual_action_sha({'observation_id': oid, 'reading_revision': rev,
                                     'record_sha256': record_sha, 'archived_fact_sha256': fact_sha})
    return {'id': row_id, 'observation_id': oid, 'reading_revision': rev, 'observation_index': turn,
            'input_turn': chron[1], 'source_text_sha256': _contextual_action_sha(record['source']),
            'record_sha256': record_sha, 'archived_fact_index': 0, 'archived_fact_sha256': fact_sha,
            'triple': list(triple), 'parser_base_sha256': record['parser_base_sha256'],
            'parser_grammar_sha256': record['parser_grammar_sha256'], 'installed_memory_head': head}


def _contextual_action_observations(ev, proj, keys, state):
    functional = set(proj['policy']['functional'])
    created = ev['pending']['created_input_turn']
    current = ev['current']
    window = proj['policy']['limits']['max_window_turns']
    sections = ('query', 'events', 'event', 'definitions', 'definition', 'corrections', 'correction',
                'causes', 'cause', 'conditions', 'condition', 'hypotheses', 'hypothesis',
                '질문', '사건', '가정사건', '정의', '교정', '원인', '이유물음', '조건', '가정', '사건정정')
    excluded = ('derived', 'rule', 'resolve', 'bound', 'unnamed', 'at_least', 'hypothetical')
    facts = ev['facts']
    sources = ev['sources'] if ev['sources'] is not None else [None] * len(facts)
    rows, seen, gaps, complete, overflow = [], set(), [], True, 0
    for fi, (fact, src) in enumerate(zip(facts, sources)):
        triple = fact.get('triple') if isinstance(fact, dict) else None
        relevant = (isinstance(triple, list) and len(triple) == 3 and all(type(v) is str for v in triple)
                    and triple[0] in keys and triple[1] in functional
                    and fact.get('polarity', True) is True and fact.get('modality', 'asserted') == 'asserted'
                    and not any(fact.get(k) for k in excluded))
        pending = ev['pending']
        if (isinstance(src, dict) and set(src) == {'observation_id', 'reading_revision'}
                and type(src['observation_id']) is str
                and type(src['reading_revision']) is int and src['reading_revision'] > 0):
            oid, rev = src['observation_id'], src['reading_revision']
            chron_entry = ev['chron'].get(oid)
            ledger_entry = ev['ledger']['records'].get(oid)
            if (chron_entry is not None and ledger_entry is not None
                    and chron_entry == (rev, created) and ledger_entry['active'] == rev):
                continue
        row = _contextual_action_qualify(fact, src, ev, sections, excluded)
        if row is None:
            state['metrics']['records_rejected'] += 1
            if relevant:
                complete = False
                if len(gaps) < 16:
                    gaps.append({'code': 'observation_source_unqualified',
                                 'path': '/evidence/archive/replay/facts/%d' % fi})
                else:
                    overflow += 1
            continue
        state['metrics']['records_qualified'] += 1
        triple = row['triple']
        if triple[0] not in keys or triple[1] not in functional:
            continue
        if row['input_turn'] > current:
            complete = False
            if len(gaps) < 16:
                gaps.append({'code': 'observation_turn_future', 'path': '/evidence/archive/replay/facts/%d' % fi})
            else:
                overflow += 1
            continue
        if row['input_turn'] == created:
            continue
        if abs(row['input_turn'] - created) > window or row['id'] in seen:
            continue
        seen.add(row['id'])
        rows.append(row)
    if len(rows) > proj['policy']['limits']['max_observations']:
        _contextual_action_fail('observations_over_cap', '/evidence/archive/replay/facts')
    if overflow:
        gaps.append({'code': 'observation_source_gaps_truncated', 'path': '/evidence/archive/replay/facts'})
    state['gaps'].extend(gaps)
    state['obs_complete'] = complete
    rows.sort(key=lambda r: (r['input_turn'], r['observation_index'], r['id']))
    return rows


def _contextual_action_entry_gaps(idx, entry, proj):
    path = '/projection/catalog/programs/%d' % idx
    gaps = []
    program = entry['program']
    sig = program.get('signature') or {}
    open_roles = sig.get('open_roles') if isinstance(sig.get('open_roles'), dict) else {}
    open_slots = set(open_roles.values())
    if sig.get('fixed_values'):
        gaps.append({'code': 'catalog_fixed_values_unsupported', 'path': path + '/program/signature/fixed_values'})
    for slot, meta in entry['roles'].items():
        rpath = path + '/roles/' + str(slot)
        decl = proj['roles'].get(slot)
        if (not isinstance(meta, dict) or meta.get('presence') != 'required'
                or meta.get('coreference_group') is not None):
            gaps.append({'code': 'catalog_role_unsupported', 'path': rpath})
        if slot not in open_slots:
            gaps.append({'code': 'catalog_role_not_open', 'path': rpath})
        if decl is None:
            gaps.append({'code': 'catalog_role_not_in_surface', 'path': rpath})
        elif isinstance(meta, dict) and meta.get('type_ref') != decl.get('type_ref'):
            gaps.append({'code': 'catalog_role_type_mismatch', 'path': rpath})
    steps = program.get('steps')
    if not isinstance(steps, list):
        gaps.append({'code': 'program_steps_invalid', 'path': path + '/program/steps'})
    else:
        for si, step in enumerate(steps):
            if not isinstance(step, dict) or step.get('op') not in ('emit', 'call'):
                gaps.append({'code': 'program_op_unsupported', 'path': path + '/program/steps/%d' % si})
    return gaps


def _contextual_action_term(idx, entry, present, proj):
    key = '%s@%s' % (entry['id'], entry['version'])
    labels = proj['labels']
    label = labels[idx] if isinstance(labels, list) else labels.get(key)
    return {'id': entry['id'], 'version': entry['version'], 'execute_key': key, 'label': label,
            'roles': {slot: present[slot] for slot in entry['roles']},
            'source_ref': '/source_maps/catalog/entries/%d' % idx}


def _contextual_action_cap(name, proj):
    if name in ('max_call_depth', 'max_expanded_steps'):
        return proj['policy']['catalog_limits'][name]
    return proj['policy']['limits'][name]


def _contextual_action_execute(combo, entries, present, proj, state):
    gaps, ordered = [], []
    descriptors = proj['descriptors']

    def nesting(i):
        records = descriptors[i]['steps']
        if not isinstance(records, list):
            return None
        deepest = 0
        for rec in records:
            if not isinstance(rec, dict):
                return None
            p, op = rec.get('path'), rec.get('op')
            if type(op) is not str or not isinstance(p, list) or len(p) < 4 or (len(p) - 4) % 6 != 0:
                return None
            if p[0] != 'programs' or p[1] != i or p[-2] != 'steps' or type(p[-1]) is not int or p[-1] < 0:
                return None
            levels = (len(p) - 4) // 6
            for k in range(levels):
                b = 2 + 6 * k
                if (p[b] != 'steps' or type(p[b + 1]) is not int or p[b + 1] < 0 or p[b + 2] != 'call'
                        or type(p[b + 3]) is not str or p[b + 4] != '@'
                        or not (_idx_str(p[b + 5]) or type(p[b + 5]) is int)):
                    return None
            deepest = max(deepest, levels + 1 if op == 'call' else levels)
        if descriptors[i]['call_boundaries'] and deepest == 0:
            return None
        return deepest

    steps = sum(len(descriptors[i]['steps']) for i in combo)
    writes = sum(len(descriptors[i]['attempted_writes']) for i in combo)
    deepest = 0
    for i in sorted(set(combo)):
        d = nesting(i)
        if d is None:
            gaps.append({'code': 'call_depth_unknown',
                         'path': '/projection/catalog_description/programs/%d/call_boundaries' % i})
        else:
            deepest = max(deepest, d)
    if steps > _contextual_action_cap('max_expanded_steps', proj):
        gaps.append({'code': 'execution_refused_expanded_steps', 'path': '/projection/catalog/limits/max_expanded_steps'})
    if writes > _contextual_action_cap('max_effect_triples', proj):
        gaps.append({'code': 'execution_refused_effect_triples', 'path': '/projection/policy/limits/max_effect_triples'})
    if deepest >= _contextual_action_cap('max_call_depth', proj):
        gaps.append({'code': 'execution_refused_call_depth', 'path': '/projection/catalog/limits/max_call_depth'})
    if gaps:
        return [], gaps
    for i in combo:
        entry = entries[i]
        roles = {slot: present[slot] for slot in entry['roles']}
        out = execute(entry['program'], roles, programs=proj['registry'], numeric_updates={})
        if (not isinstance(out, dict) or out.get('reason') or out.get('missing') or out.get('conflicts')
                or out.get('leftover')):
            gaps.append({'code': 'term_unresolved', 'path': '/projection/catalog/programs/%d' % i})
            return [], gaps
        for row in out.get('facts') or []:
            triple = row.get('triple') if isinstance(row, dict) else row
            if not isinstance(triple, (list, tuple)) or len(triple) != 3 or any(type(v) is not str for v in triple):
                gaps.append({'code': 'effect_triple_invalid', 'path': '/projection/catalog/programs/%d' % i})
                return [], gaps
            ordered.append([triple[0], triple[1], triple[2]])
    state['metrics']['predicted_triples_processed'] += len(ordered)
    if len(ordered) > _contextual_action_cap('max_effect_triples', proj):
        gaps.append({'code': 'effect_cap_exceeded', 'path': '/projection/policy/limits/max_effect_triples'})
        return [], gaps
    return ordered, gaps


def _contextual_action_final(ordered, functional):
    from marco.reasoning.inference import current_facts
    try:
        facts, changes = current_facts([{'triple': list(t), 'evidence': {}} for t in ordered],
                                       mutable_predicates=set(functional), numeric_updates={})
    except (ValueError, TypeError, KeyError, IndexError, AttributeError):
        return None
    out = []
    for item in facts:
        triple = item.get('triple') if isinstance(item, dict) else None
        if not (isinstance(triple, list) and len(triple) == 3 and all(type(v) is str for v in triple)):
            return None
        out.append(list(triple))
    return out


def _contextual_action_latest(rows):
    if not rows:
        return None
    top = max(r['input_turn'] for r in rows)
    tied = sorted([r for r in rows if r['input_turn'] == top], key=lambda r: r['id'])
    if len({r['triple'][2] for r in tied}) != 1:
        return 'conflict'
    return tied[0]


def _contextual_action_compare(key, final, rows, functional, created):
    support, contrast, unexplained, unobserved, gaps = [], [], [], [], []
    predicted = {}
    for triple in final:
        if triple[0] == key:
            predicted.setdefault(triple[1], []).append(triple)
    covered = set()
    for pred in functional:
        relevant = [r for r in rows if r['triple'][0] == key and r['triple'][1] == pred]
        before = _contextual_action_latest([r for r in relevant if r['input_turn'] < created])
        after = _contextual_action_latest([r for r in relevant if r['input_turn'] > created])
        if before == 'conflict' or after == 'conflict':
            gaps.append({'code': 'equal_turn_observation_conflict', 'path': None})
            continue
        if before is None or after is None or before['triple'][2] == after['triple'][2]:
            continue
        preds = predicted.get(pred, [])
        if not preds:
            unexplained.append({'before': before['id'], 'after': after['id']})
            continue
        if len({p[2] for p in preds}) != 1:
            gaps.append({'code': 'predicted_final_value_ambiguous', 'path': None})
            continue
        covered.add(pred)
        ref = {'before': before['id'], 'after': after['id'], 'predicted_triple': list(preds[0]),
               'assumption': 'association_assumed_v1'}
        if preds[0][2] == after['triple'][2]:
            support.append(ref)
        else:
            contrast.append(ref)
    for triple in final:
        if not (triple[0] == key and triple[1] in covered):
            unobserved.append(list(triple))
    return ({'support_refs': support, 'contrast_refs': contrast, 'unobserved_effects': unobserved,
             'unexplained_observation_refs': unexplained}, gaps)


def _contextual_action_candidate(alt, combo, entries, entry_gaps, proj, ev, rows, state):
    policy = proj['policy']
    present = alt['present']
    gaps = []
    for i in combo:
        gaps.extend(entry_gaps[i])
    terms = [_contextual_action_term(i, entries[i], present, proj) for i in combo]
    ordered, final = [], []
    if not gaps:
        ordered, exec_gaps = _contextual_action_execute(combo, entries, present, proj, state)
        gaps.extend(exec_gaps)
    if ordered and not gaps:
        final = _contextual_action_final(ordered, policy['functional'])
        if final is None:
            final = []
            gaps.append({'code': 'final_value_projection_failed', 'path': None})
    key = present.get(policy['key_slot'])
    if key is None:
        gaps.append({'code': 'association_key_missing', 'path': None})
        cmp = {'support_refs': [], 'contrast_refs': [], 'unobserved_effects': [list(t) for t in final],
               'unexplained_observation_refs': []}
    else:
        cmp, cmp_gaps = _contextual_action_compare(key, final, rows, policy['functional'],
                                                   ev['pending']['created_input_turn'])
        gaps.extend(cmp_gaps)
    cid = _contextual_action_sha({'projection_fingerprint': proj['fingerprint'], 'pending_id': ev['pending']['id'],
                                  'reading_candidate_index': alt['index'], 'spans': alt['spans'],
                                  'terms': [[t['id'], t['version'], t['roles']] for t in terms]})
    return {'id': cid, 'reading_candidate_index': alt['index'], 'terms': terms,
            'consumed_slots': sorted(present),
            'prediction': {'kind': 'conditional_program_output_v1', 'ordered_triples': ordered,
                           'comparison_triples': final},
            'comparison': cmp,
            'metrics': {'support_count': len({(r['before'], r['after']) for r in cmp['support_refs']}),
                        'conflict_count': len({(r['before'], r['after']) for r in cmp['contrast_refs']}),
                        'term_count': len(terms)},
            'gaps': gaps}


def _contextual_action_rank(candidates, ranking):
    groups = {}
    for cand in candidates:
        values = tuple(cand['metrics'][r['key']] for r in ranking)
        groups.setdefault(values, []).append(cand['id'])
    items = sorted(groups.items(), key=lambda item: tuple(
        (-v if r['direction'] == 'desc' else v) for v, r in zip(item[0], ranking)))
    return [{'metric_values': list(values), 'candidate_ids': sorted(ids)} for values, ids in items]


def _contextual_action_result(state, status):
    return {'schema': 'contextual-action-comparison-v1', 'status': status,
            'pending_id': state.get('pending_id'), 'binding': state.get('binding'),
            'unknown': state.get('unknown'), 'reading': state.get('reading'),
            'projection_ref': state.get('projection_ref'), 'unresolved': True, 'known': False,
            'learned': False, 'candidate_enumeration_complete': state.get('enum_complete'),
            'observations_complete': state.get('obs_complete'),
            'comparison_complete': state.get('cmp_complete'), 'truncated': bool(state.get('truncated')),
            'candidates': list(state.get('candidates') or []), 'ranking': list(state.get('ranking') or []),
            'observations': list(state.get('observations') or []), 'assumptions': state.get('assumptions'),
            'gaps': list(state.get('gaps') or []), 'metrics': dict(state['metrics'])}


def _contextual_action_output(state, status):
    result = _contextual_action_result(state, status)
    cap = state.get('output_cap')

    def size(value):
        return len(_contextual_action_canon(value).encode('utf-8'))

    if cap is None or size(result) <= cap:
        return result
    removed = bool(state.get('candidates') or state.get('observations') or state.get('ranking')
                   or state.get('reading') is not None)
    state['gaps'] = list(state.get('gaps') or []) + [
        {'code': 'output_cap_exceeded', 'path': '/projection/policy/limits/max_output_bytes'}]
    state['candidates'] = [
        {'id': c['id'], 'reading_candidate_index': c['reading_candidate_index'], 'terms': [],
         'consumed_slots': c['consumed_slots'],
         'prediction': {'kind': 'conditional_program_output_v1', 'ordered_triples': [], 'comparison_triples': []},
         'comparison': {'support_refs': [], 'contrast_refs': [], 'unobserved_effects': [],
                        'unexplained_observation_refs': []},
         'metrics': c['metrics'], 'gaps': [{'code': 'output_cap_omitted', 'path': None}]}
        for c in (state.get('candidates') or [])]
    state['observations'] = []
    state['ranking'] = []
    state['reading'] = None
    state['cmp_complete'] = False
    state['truncated'] = bool(state.get('truncated')) or removed
    result = _contextual_action_result(state, 'gap')
    if size(result) <= cap:
        return result
    if state.get('candidates') or state.get('assumptions') is not None:
        removed = True
    state['candidates'] = []
    state['assumptions'] = None
    state['truncated'] = bool(state.get('truncated')) or removed
    result = _contextual_action_result(state, 'gap')
    if size(result) <= cap:
        return result
    if any(state.get(k) is not None for k in ('unknown', 'binding', 'projection_ref')) or state.get('gaps'):
        removed = True
    state['unknown'] = None
    state['binding'] = None
    state['projection_ref'] = None
    state['gaps'] = [{'code': 'output_cap_exceeded', 'path': '/projection/policy/limits/max_output_bytes'},
                     {'code': 'output_cap_minimal_envelope', 'path': None}]
    state['truncated'] = bool(state.get('truncated')) or removed
    result = _contextual_action_result(state, 'gap')
    if size(result) <= cap:
        return result
    state['metrics']['output_cap_bytes'] = cap
    state['gaps'] = list(state['gaps']) + [
        {'code': 'output_cap_below_minimum', 'path': '/projection/policy/limits/max_output_bytes'}]
    return _contextual_action_result(state, 'gap')


def _contextual_action_run(projection, reading, evidence, state):
    fail = _contextual_action_fail
    nodes, size = 0, 0
    for name, value in (('projection', projection), ('reading', reading), ('evidence', evidence)):
        count = _contextual_action_nodes(value, 65536)
        if count is None:
            fail('input_ceiling_nodes', '/' + name)
        nodes += count
        size += len(_contextual_action_canon(value).encode('utf-8'))
    if nodes > 65536 or size > 2 * 1024 * 1024:
        fail('input_ceiling', None)
    proj = _contextual_action_projection(projection)
    state['output_cap'] = proj['policy']['limits']['max_output_bytes']
    ev = _contextual_action_evidence(evidence, proj)
    state['pending_id'] = ev['pending']['id']
    alts = _contextual_action_reading(reading, proj, ev['pending']['text'])
    prov = proj['prov']
    policy = proj['policy']
    assoc = policy['association']
    state['binding'] = dict(ev['binding'])
    span = reading['unknown_span']
    state['unknown'] = {'text': reading['unknown_text'], 'span': list(span) if span is not None else None,
                        'surface_id': reading['surface_id']}
    state['reading'] = deepcopy(reading)
    state['projection_ref'] = {'fingerprint': proj['fingerprint'], 'graph_id': prov['graph_id'],
                               'root_id': prov['root_id'], 'effective_graph_sha256': prov['effective_graph_sha256'],
                               'view_key': list(prov['view_key']), 'base_origin': deepcopy(prov['base_origin']),
                               'source': deepcopy(prov['source'])}
    state['assumptions'] = {'policy_id': policy['id'], 'policy_declaration_sha256': policy['declaration_sha256'],
                            'association': {'mode': assoc['mode'], 'key_slot': assoc['key_slot']},
                            'functional_predicates': list(assoc['functional_predicates']),
                            'before_selection': assoc['before_selection'],
                            'after_selection': assoc['after_selection'],
                            'causal_status': assoc['causal_status'], 'world': 'open'}
    status = reading['status']
    diag = [g for g in reading['gaps'] if not (status == 'no_match' and g['code'] == 'no_structural_candidate')]
    for g in diag:
        state['gaps'].append({'code': 'reader_gap', 'path': _contextual_action_canon(g)[:256]})
    state['metrics']['reader_alternatives'] = len(alts)
    reader_complete = bool(reading['search_complete'] is True and not reading['truncated'] and not diag)
    state['truncated'] = bool(reading['truncated'])
    if status == 'no_match':
        state['enum_complete'] = reader_complete
        if not reader_complete:
            state['gaps'].append({'code': 'reader_incomplete', 'path': '/reading'})
        return _contextual_action_output(state, 'no_match')
    if not alts:
        state['gaps'].append({'code': 'reader_incomplete', 'path': '/reading'})
        state['enum_complete'] = False
        return _contextual_action_output(state, 'gap')
    state['obs_complete'] = False
    keys = {alt['present'][policy['key_slot']] for alt in alts if policy['key_slot'] in alt['present']}
    rows = _contextual_action_observations(ev, proj, keys, state)
    state['observations'] = rows
    state['enum_complete'] = False
    import itertools
    entries = proj['entries']
    entry_gaps = [_contextual_action_entry_gaps(i, e, proj) for i, e in enumerate(entries)]
    cap = policy['limits']['max_candidates']
    candidates, seen, truncated = [], set(), False
    for alt in alts:
        if truncated:
            break
        present = alt['present']
        slots = set(present)
        for count in policy['counts']:
            if truncated:
                break
            for combo in itertools.product(range(len(entries)), repeat=count):
                state['metrics']['term_tuples_visited'] += 1
                if count == 2 and (not all(entries[i]['composable'] for i in combo)
                                   or (not policy['repeat'] and combo[0] == combo[1])):
                    continue
                consumed, ok = set(), True
                for i in combo:
                    for slot, meta in entries[i]['roles'].items():
                        decl = proj['roles'].get(slot)
                        if slot not in present or decl is None or meta['type_ref'] != decl['type_ref']:
                            ok = False
                            break
                    if not ok:
                        break
                    consumed |= set(entries[i]['roles'])
                if not ok or consumed != slots:
                    continue
                dedup = _contextual_action_canon({'spans': alt['spans'], 'terms': [
                    [entries[i]['id'], entries[i]['version'], sorted(entries[i]['roles'])] for i in combo]})
                if dedup in seen:
                    continue
                seen.add(dedup)
                state['metrics']['admissible_candidates'] += 1
                if len(candidates) >= cap:
                    truncated = True
                    break
                candidates.append(_contextual_action_candidate(alt, combo, entries, entry_gaps, proj, ev, rows, state))
    state['truncated'] = bool(reading['truncated']) or truncated
    state['enum_complete'] = bool(reader_complete and not truncated)
    state['candidates'] = candidates
    state['metrics']['candidates_returned'] = len(candidates)
    state['ranking'] = _contextual_action_rank(candidates, policy['ranking'])
    if not reader_complete:
        state['gaps'].append({'code': 'reader_incomplete', 'path': '/reading'})
    candidate_gap = any(c['gaps'] for c in candidates)
    if truncated:
        state['gaps'].append({'code': 'candidate_cap_truncated', 'path': '/projection/policy/limits/max_candidates'})
    if candidate_gap:
        state['gaps'].append({'code': 'candidate_gaps_present', 'path': None})
    complete = bool(reader_complete and not truncated and state.get('obs_complete') is True
                    and not candidate_gap and not state['gaps'])
    state['cmp_complete'] = complete
    if not complete:
        return _contextual_action_output(state, 'gap')
    if any(c['metrics']['support_count'] > 0 for c in candidates):
        return _contextual_action_output(state, 'conditional')
    return _contextual_action_output(state, 'clarify')


def compare_contextual_action(projection, reading, evidence):
    state = {'gaps': [], 'metrics': {k: 0 for k in (
        'reader_alternatives', 'term_tuples_visited', 'admissible_candidates', 'candidates_returned',
        'records_qualified', 'records_rejected', 'predicted_triples_processed')}}
    try:
        return _contextual_action_run(projection, reading, evidence, state)
    except ValueError as exc:
        args = exc.args
        if len(args) == 1 and isinstance(args[0], tuple) and len(args[0]) == 2:
            code, path = args[0]
        else:
            code, path = 'computation_error', None
        state['gaps'].append({'code': str(code), 'path': path if isinstance(path, str) else None})
        return _contextual_action_output(state, 'gap')
    except (TypeError, KeyError, IndexError, AttributeError, OverflowError, RecursionError, UnicodeError):
        state['gaps'].append({'code': 'computation_error', 'path': None})
        return _contextual_action_output(state, 'gap')


# ---- inactive pure lexical action meaning target / render / match (L5) ----
# External producer, Memory origin inventory, archived-source gate and the
# route that pairs matches with active rows are absent dependencies.

_amt_f = _contextual_action_fail

_AMT_TEMPLATES = {
    'question': ('expression', 'role_pattern', 'meaning'), 'role': ('slot_label', 'markers'),
    'term': ('ordinal', 'program', 'bindings'), 'binding': ('program_role_label', 'surface_role_label'),
    'admitted': ('expression',), 'denied': ('expression',), 'stale': ('expression',),
    'withdrawn': ('expression',), 'used': ('expression', 'role_pattern', 'meaning'), 'gap': (),
    'question_with_answer': ('answer', 'question')}
_AMT_SEPARATORS = ('role_separator', 'term_separator', 'binding_separator', 'marker_separator')
_AMT_LIMIT_CEIL = {'max_forms': 16, 'max_form_chars': 512, 'max_input_bytes': 32768,
                   'max_question_bytes': 65536, 'max_target_bytes': 32768, 'max_active_questions': 1,
                   'max_terms': 2, 'max_roles': 64, 'max_archive_bytes': 16777216,
                   'max_archive_events': 65536}
_AMT_POLICY_FIXED = {
    'schema': 'lexical-action-learning-policy-v1',
    'admission_operator': 'explicit_user_lexical_action_confirmation_v1',
    'meaning_scope': 'surface_role_pattern_to_exhaustive_ordered_known_programs_v1',
    'evidence_kind': 'archived_dialogue_input_v1',
    'question_scope': 'next_external_input_same_conversation_v1',
    'question_selection': 'oldest_pending_rank_then_target_digest_v1',
    'retraction_scope': 'unique_active_surface_role_pattern_v1',
    'active_use_scope': 'conditional_nonexecuting_adjunct_v1'}
_AMT_LKEYS = ('schema', 'policy', 'forms', 'render', 'role_labels', 'source_maps', 'provenance',
              'parent_action_fingerprint', 'language_projection_fingerprint', 'fingerprint')
_AMT_BKEYS = ('schema', 'model_content_sha256', 'model_effective_key', 'effective_graph_sha256',
              'language_projection_fingerprint', 'action_projection_fingerprint',
              'action_learning_projection_fingerprint', 'catalog_sha256', 'policy_sha256', 'forms_sha256',
              'render_sha256', 'role_labels_sha256', 'parser_base_sha256', 'parser_grammar_sha256',
              'graph_id', 'root_id', 'view_key', 'base_origin', 'source', 'catalog_id', 'policy_id')
_AMT_PROV = ('graph_id', 'root_id', 'effective_graph_sha256', 'view_key', 'base_origin', 'source')


def _amt_utf8(value):
    try:
        return len(value.encode('utf-8'))
    except UnicodeEncodeError:
        _amt_f('malformed_utf8', None)


def _amt_plain(value, budget, allow_bool):
    f = _amt_f
    byte_cap = 2 * 1024 * 1024
    nodes, size, pending = 0, 0, 1
    stack = [(value, '$', 0, ())]
    while stack:
        item, path, depth, active = stack.pop()
        pending -= 1
        nodes += 1
        if nodes > budget:
            f('json_too_large', path)
        if depth > 64:
            f('json_too_deep', path)
        if size > byte_cap:
            f('json_too_large', path)
        kind = type(item)
        if kind is dict or kind is list:
            for a in active:
                if a is item:
                    f('json_cycle', path)
            count = len(item)
            reserve = 2 * count if kind is dict else count
            if nodes + pending + reserve > budget:
                f('json_too_large', path)
            size += 2 + count
            if size > byte_cap:
                f('json_too_large', path)
            nxt = active + (item,)
            if kind is dict:
                for key, sub in item.items():
                    if type(key) is not str:
                        f('json_not_plain', path)
                    nodes += 1
                    if len(key) > byte_cap or size + len(key) > byte_cap:
                        f('json_too_large', path)
                    size += _amt_utf8(key) + 4
                    if size > byte_cap:
                        f('json_too_large', path)
                    stack.append((sub, _idx_path(path, '.' + key), depth + 1, nxt))
                    pending += 1
            else:
                for i, sub in enumerate(item):
                    stack.append((sub, _idx_path(path, '[%d]' % i), depth + 1, nxt))
                    pending += 1
        elif kind is str:
            if len(item) > byte_cap or size + len(item) > byte_cap:
                f('json_too_large', path)
            size += _amt_utf8(item) + 2
            if size > byte_cap:
                f('json_too_large', path)
        elif kind is bool:
            if not allow_bool:
                f('json_not_plain', path)
            size += 5
        elif item is None:
            size += 5
        elif kind is int:
            if item.bit_length() > 1024:
                f('json_integer_too_large', path)
            size += item.bit_length() // 3 + 2
        elif kind is float:
            if item != item or item in (float('inf'), float('-inf')):
                f('json_not_plain', path)
            size += 24
        else:
            f('json_not_plain', path)
    return nodes, size


def _amt_parse(template, required):
    import string
    try:
        parts = list(string.Formatter().parse(template))
    except (ValueError, TypeError):
        _amt_f('render_template_parse', '/learning_projection/render')
    names = []
    for _lit, name, spec, conv in parts:
        if name is None:
            continue
        if spec not in (None, '') or conv is not None or not name.isidentifier():
            _amt_f('render_template_field', '/learning_projection/render')
        names.append(name)
    if sorted(names) != sorted(required):
        _amt_f('render_template_placeholders', '/learning_projection/render')
    return parts


def _amt_fill(parts, values):
    out, pos = '', {}
    for lit, name, _spec, _conv in parts:
        out += lit
        if name is not None:
            value = values[name]
            pos[name] = [len(out), len(out) + len(value)]
            out += value
    return out, pos


def _amt_policy(policy, proj):
    f = _amt_f
    path = '/learning_projection/policy'
    if not isinstance(policy, dict) or set(policy) != set(_AMT_POLICY_FIXED) | {'policy_id', 'limits'}:
        f('learning_policy_shape', path)
    for key, want in _AMT_POLICY_FIXED.items():
        if policy[key] != want:
            f('learning_policy_value', path + '/' + key)
    pid = policy['policy_id']
    if type(pid) is not str or not 1 <= len(pid) <= 128:
        f('learning_policy_id', path + '/policy_id')
    lim = policy['limits']
    if not isinstance(lim, dict) or set(lim) != set(_AMT_LIMIT_CEIL):
        f('learning_policy_limits', path + '/limits')
    for key, high in _AMT_LIMIT_CEIL.items():
        if type(lim[key]) is not int or not 1 <= lim[key] <= high:
            f('learning_policy_limit_' + key, path + '/limits')
    if lim['max_active_questions'] != 1:
        f('learning_policy_limit_max_active_questions', path + '/limits')
    if lim['max_terms'] > min(2, proj['catalog_limits']['max_candidate_terms']):
        f('learning_policy_limit_max_terms', path + '/limits/max_terms')
    if lim['max_roles'] > min(64, len(proj['roles'])):
        f('learning_policy_limit_max_roles', path + '/limits/max_roles')
    return dict(lim)


def _amt_forms(forms, lim):
    f = _amt_f
    path = '/learning_projection/forms'
    if (not isinstance(forms, dict) or set(forms) != {'schema', 'forms'}
            or forms['schema'] != 'selected-action-meaning-controls-v1'):
        f('learning_forms_shape', path)
    rows = forms['forms']
    if not isinstance(rows, list) or not 1 <= len(rows) <= lim['max_forms']:
        f('learning_forms_count', path + '/forms')
    kinds, ids = set(), set()
    keys = {'id', 'kind', 'ownership_prefix', 'text', 'slots', 'wide_slots'}
    for i, row in enumerate(rows):
        rpath = path + '/forms/%d' % i
        if not isinstance(row, dict) or set(row) != keys:
            f('learning_form_shape', rpath)
        text, prefix = row['text'], row['ownership_prefix']
        if (type(row['id']) is not str or not row['id'] or row['id'] in ids
                or row['kind'] not in ('affirm', 'deny', 'withdraw')
                or type(text) is not str or not 1 <= len(text) <= lim['max_form_chars']
                or chr(10) in text or chr(13) in text
                or type(prefix) is not str or not 1 <= len(prefix) <= lim['max_form_chars']
                or not isinstance(row['slots'], dict) or not isinstance(row['wide_slots'], list)):
            f('learning_form_value', rpath)
        slots = row['slots']
        if row['kind'] == 'withdraw':
            seed = slots.get('expression')
            if (set(slots) != {'expression'} or type(seed) is not str
                    or not 1 <= len(seed) <= lim['max_form_chars']
                    or row['wide_slots'] != ['expression']):
                f('learning_form_control', rpath)
        elif slots != {} or row['wide_slots'] != [] or prefix != text:
            f('learning_form_control', rpath)
        ids.add(row['id'])
        kinds.add(row['kind'])
    if kinds != {'affirm', 'deny', 'withdraw'}:
        f('learning_forms_kinds', path + '/forms')


def _amt_binding(b, ap, lp, proj, policy):
    f = _amt_f
    if not isinstance(b, dict) or set(b) != set(_AMT_BKEYS) or b['schema'] != 'selected-action-learning-binding-v1':
        f('binding_shape', '/binding')
    for key in _AMT_BKEYS:
        if key.endswith('sha256') or key.endswith('fingerprint') or key == 'model_effective_key':
            if not _contextual_action_hex(b[key]):
                f('binding_digest', '/binding/' + key)
    for key, high in (('graph_id', 1024), ('root_id', 1024), ('catalog_id', 128), ('policy_id', 128)):
        if type(b[key]) is not str or not 1 <= len(b[key]) <= high:
            f('binding_identity', '/binding/' + key)
    vk = b['view_key']
    if (not isinstance(vk, list) or len(vk) != 2 or type(vk[0]) is not int
            or not 0 <= vk[0] <= 2147483647
            or not (vk[1] is None or (type(vk[1]) is str and 1 <= len(vk[1]) <= 128))
            or (vk[0] == 0) != (vk[1] is None)):
        f('binding_view_key', '/binding/view_key')
    bo = b['base_origin']
    if (not isinstance(bo, dict) or set(bo) != {'kind', 'build_id'} or bo['kind'] != 'base'
            or not (bo['build_id'] is None or (type(bo['build_id']) is str and 1 <= len(bo['build_id']) <= 1024))):
        f('binding_base_origin', '/binding/base_origin')
    src = b['source']
    req = {'status', 'member_path', 'member_sha256', 'base_content_sha256'}
    if (not isinstance(src, dict) or not req <= set(src) or not set(src) <= req | {'base_build_id'}
            or src['status'] != 'caller_supplied' or type(src['member_path']) is not str
            or not 1 <= len(src['member_path']) <= 1024 or not _contextual_action_hex(src['member_sha256'])
            or not _contextual_action_hex(src['base_content_sha256'])
            or not (src.get('base_build_id') is None or (type(src['base_build_id']) is str
                                                       and 1 <= len(src['base_build_id']) <= 1024))):
        f('binding_source', '/binding/source')
    cat = ap['catalog']
    sha = _contextual_action_sha
    checks = (
        ('catalog_id', cat['catalog_id']), ('policy_id', policy['policy_id']),
        ('catalog_sha256', sha({'catalog_id': cat['catalog_id'], 'limits': cat['limits'],
                                'programs': cat['programs']})),
        ('policy_sha256', sha(lp['policy'])), ('forms_sha256', sha(lp['forms'])),
        ('render_sha256', sha(lp['render'])), ('role_labels_sha256', sha(lp['role_labels'])),
        ('action_projection_fingerprint', ap['fingerprint']),
        ('action_learning_projection_fingerprint', lp['fingerprint']),
        ('language_projection_fingerprint', lp['language_projection_fingerprint']))
    for key, want in checks:
        if b[key] != want:
            f('binding_mismatch', '/binding/' + key)
    lprov = lp['provenance']
    if not isinstance(lprov, dict):
        f('learning_provenance', '/learning_projection/provenance')
    for key in _AMT_PROV:
        if b[key] != ap['provenance'][key] or key not in lprov or lprov[key] != ap['provenance'][key]:
            f('binding_graph_mismatch', '/binding/' + key)


def _amt_ctx(ap, lp, binding):
    f = _amt_f
    nodes, size = 0, 0
    for name, value, allow in (('action_projection', ap, True), ('learning_projection', lp, True),
                               ('binding', binding, False)):
        n, s = _amt_plain(value, 65536, allow)
        nodes += n
        size += s
        if nodes > 65536 or size > 2 * 1024 * 1024:
            f('input_ceiling', '/' + name)
    exact = 0
    for name, value in (('action_projection', ap), ('learning_projection', lp), ('binding', binding)):
        exact += len(_contextual_action_canon(value).encode('utf-8'))
        if exact > 2 * 1024 * 1024:
            f('input_ceiling', '/' + name)
    proj = _contextual_action_projection(ap)
    desc = describe_action_catalog(deepcopy(ap['catalog']))
    if (not isinstance(desc, dict) or desc.get('status') != 'described' or desc.get('gaps') != []
            or _contextual_action_canon(desc) != _contextual_action_canon(ap['catalog_description'])):
        f('catalog_description_mismatch', '/action_projection/catalog_description')
    cat = ap['catalog']
    pre = {'schema': ap['schema'], 'required_operators': list(ap['required_operators']),
           'hypothesis_scope': ap['hypothesis_scope'],
           'catalog': {'catalog_id': cat['catalog_id'], 'limits': cat['limits'], 'programs': cat['programs']},
           'surface': ap['surface'], 'policy': ap['policy'], 'replies': ap['replies'],
           'entry_labels': ap['entry_labels'], 'source_maps': ap['source_maps'],
           'provenance': ap['provenance']}
    if _contextual_action_sha(pre) != ap['fingerprint']:
        f('action_fingerprint_mismatch', '/action_projection/fingerprint')
    if not isinstance(lp, dict) or set(lp) != set(_AMT_LKEYS):
        f('learning_keys', '/learning_projection')
    if (lp['schema'] != 'graph-action-learning-projection-v1'
            or lp['parent_action_fingerprint'] != ap['fingerprint']
            or not _contextual_action_hex(lp['language_projection_fingerprint'])):
        f('learning_parent', '/learning_projection')
    if lp['fingerprint'] != _contextual_action_sha({k: lp[k] for k in _AMT_LKEYS if k != 'fingerprint'}):
        f('learning_fingerprint', '/learning_projection/fingerprint')
    lim = _amt_policy(lp['policy'], proj)
    _amt_forms(lp['forms'], lim)
    labels = lp['role_labels']
    if (not isinstance(labels, dict) or set(labels) != set(proj['roles'])
            or any(type(v) is not str or not 1 <= len(v) <= 512 for v in labels.values())):
        f('learning_role_labels', '/learning_projection/role_labels')
    if not isinstance(lp['source_maps'], dict):
        f('learning_source_maps', '/learning_projection/source_maps')
    render = lp['render']
    if not isinstance(render, dict) or set(render) != set(_AMT_TEMPLATES) | set(_AMT_SEPARATORS):
        f('learning_render_keys', '/learning_projection/render')
    parts = {}
    for name, req in _AMT_TEMPLATES.items():
        text = render[name]
        if type(text) is not str or not text or _amt_utf8(text) > 4096:
            f('render_template_bounds', '/learning_projection/render/' + name)
        parts[name] = _amt_parse(text, req)
    for name in _AMT_SEPARATORS:
        if type(render[name]) is not str or not render[name] or _amt_utf8(render[name]) > 64:
            f('render_separator_bounds', '/learning_projection/render/' + name)
    _amt_binding(binding, ap, lp, proj, lp['policy'])
    index = {'%s@%s' % (e['id'], e['version']): i for i, e in enumerate(proj['entries'])}
    return {'ap': ap, 'lp': lp, 'proj': proj, 'limits': lim, 'labels': labels, 'render': render,
            'parts': parts, 'index': index, 'surface_sha': _contextual_action_sha(ap['surface'])}


def _amt_decl(ctx):
    return [{'slot': s, 'case_group': r['case_group'], 'type_ref': r['type_ref'],
             'presence': r['presence'], 'coreference_group': r['coreference_group']}
            for s, r in ctx['proj']['roles'].items()]


def _amt_entry_ok(ctx, idx):
    f = _amt_f
    proj = ctx['proj']
    entries, descs, index = proj['entries'], proj['descriptors'], ctx['index']
    seen, todo = set(), [idx]
    while todo:
        i = todo.pop()
        if i in seen:
            continue
        if len(seen) >= len(entries):
            f('catalog_entry_walk', '/projection/catalog/programs')
        seen.add(i)
        if _contextual_action_entry_gaps(i, entries[i], proj):
            f('catalog_entry_gap', '/projection/catalog/programs/%d' % i)
        dpath = '/projection/catalog_description/programs/%d/call_boundaries' % i
        desc = descs[i]
        bounds = desc.get('call_boundaries') if isinstance(desc, dict) else None
        if not isinstance(bounds, list):
            f('catalog_call_boundaries', dpath)
        for bi, bound in enumerate(bounds):
            bpath = dpath + '/%d/target' % bi
            tgt = bound.get('target') if isinstance(bound, dict) else None
            if not isinstance(tgt, dict) or set(tgt) != {'id', 'version', 'key'}:
                f('catalog_call_target_shape', bpath)
            tid, ver, key = tgt['id'], tgt['version'], tgt['key']
            if (type(tid) is not str or not tid or not (type(ver) is int or (type(ver) is str and ver))
                    or type(key) is not str or key != '%s@%s' % (tid, ver)):
                f('catalog_call_target_shape', bpath)
            j = index.get(key)
            if j is None:
                f('catalog_call_target_unavailable', bpath)
            e = entries[j]
            if e['id'] != tid or e['version'] != ver or type(e['version']) is not type(ver):
                f('catalog_call_target_mismatch', bpath)
            if j not in seen:
                todo.append(j)


def _amt_validate(ctx, payload):
    f = _amt_f
    proj, lim = ctx['proj'], ctx['limits']
    _, est = _amt_plain(payload, 65536, False)
    if est > 4 * lim['max_target_bytes'] + 65536:
        f('target_too_large', '/target')
    if len(_contextual_action_canon(payload).encode('utf-8')) > lim['max_target_bytes']:
        f('target_too_large', '/target')
    keys = {'schema', 'surface', 'role_pattern', 'role_pattern_sha256', 'terms'}
    if not isinstance(payload, dict) or set(payload) != keys or payload['schema'] != 'lexical-action-meaning-target-v1':
        f('target_keys', '/target')
    sf = payload['surface']
    if (not isinstance(sf, dict) or set(sf) != {'text', 'surface_id', 'declaration_sha256'}
            or type(sf['text']) is not str or not 1 <= len(sf['text']) <= 512
            or len(sf['text']) > proj['text_limit']
            or type(sf['surface_id']) is not str or not 1 <= len(sf['surface_id']) <= 512
            or sf['surface_id'] != proj['surface_id']
            or not _contextual_action_hex(sf['declaration_sha256'])
            or sf['declaration_sha256'] != ctx['surface_sha']):
        f('target_surface', '/target/surface')
    rp = payload['role_pattern']
    decl = _amt_decl(ctx)
    dkeys = {'slot', 'case_group', 'type_ref', 'presence', 'coreference_group'}
    if not isinstance(decl, list) or not 1 <= len(decl) <= min(8, lim['max_roles']):
        f('target_role_pattern_bounds', '/target/role_pattern/slots')
    for di, d in enumerate(decl):
        cg = d.get('coreference_group') if isinstance(d, dict) else None
        if (not isinstance(d, dict) or set(d) != dkeys
                or type(d['slot']) is not str or not 1 <= len(d['slot']) <= 128
                or type(d['case_group']) is not str or not 1 <= len(d['case_group']) <= 512
                or type(d['type_ref']) is not str or not 1 <= len(d['type_ref']) <= 1024
                or d['presence'] not in ('required', 'optional')
                or not (cg is None or (type(cg) is str and 1 <= len(cg) <= 512))):
            f('target_role_pattern_bounds', '/target/role_pattern/slots/%d' % di)
    if (not isinstance(rp, dict) or set(rp) != {'offset_unit', 'ordered_slots', 'slots', 'omitted_slots'}
            or rp['offset_unit'] != 'unicode_codepoint' or rp['slots'] != decl):
        f('target_role_pattern', '/target/role_pattern')
    names = [d['slot'] for d in decl]
    if len(set(names)) != len(names):
        f('target_role_pattern', '/target/role_pattern/slots')
    ordered, omitted = rp['ordered_slots'], rp['omitted_slots']
    if (not isinstance(ordered, list) or not isinstance(omitted, list) or not 1 <= len(ordered) <= 8
            or any(type(s) is not str or s not in names for s in ordered)
            or len(set(ordered)) != len(ordered)
            or omitted != [n for n in names if n not in ordered]
            or any(d['presence'] == 'required' and d['slot'] not in ordered for d in decl)):
        f('target_role_slots', '/target/role_pattern')
    if payload['role_pattern_sha256'] != _contextual_action_sha(rp):
        f('target_role_pattern_sha', '/target/role_pattern_sha256')
    terms = payload['terms']
    maxn = min(2, lim['max_terms'], proj['catalog_limits']['max_candidate_terms'])
    if (not isinstance(terms, list) or not 1 <= len(terms) <= maxn
            or len(terms) not in proj['policy']['counts']):
        f('target_term_count', '/target/terms')
    seen_keys, union, steps = set(), set(), 0
    tkeys = {'id', 'version', 'execute_key', 'source_ref', 'program_sha256', 'slot_map'}
    for i, t in enumerate(terms):
        p = '/target/terms/%d' % i
        if not isinstance(t, dict) or set(t) != tkeys:
            f('target_term_keys', p)
        tid, ver = t['id'], t['version']
        if (type(tid) is not str or not 1 <= len(tid) <= 128
                or not (type(ver) is int or (type(ver) is str and 1 <= len(ver) <= 128))
                or type(t['execute_key']) is not str or t['execute_key'] != '%s@%s' % (tid, ver)
                or len(t['execute_key']) > 257):
            f('target_term_identity', p)
        idx = ctx['index'].get(t['execute_key'])
        if idx is None:
            f('target_term_unknown', p)
        entry = proj['entries'][idx]
        if entry['id'] != tid or entry['version'] != ver or type(entry['version']) is not type(ver):
            f('target_term_identity', p)
        if (t['source_ref'] != '/source_maps/catalog/entries/%d' % idx
                or t['program_sha256'] != _contextual_action_sha(entry['program'])):
            f('target_term_source', p)
        sm = t['slot_map']
        if (not isinstance(sm, dict) or not 1 <= len(sm) <= 8 or set(sm) != set(entry['roles'])
                or any(type(k) is not str or not 1 <= len(k) <= 128 for k in sm)
                or any(type(v) is not str or not 1 <= len(v) <= 128 for v in sm.values())
                or any(k != v for k, v in sm.items()) or any(v not in ordered for v in sm.values())):
            f('target_term_slot_map', p + '/slot_map')
        if t['execute_key'] in seen_keys and not proj['policy']['repeat']:
            f('target_term_repeated', p)
        seen_keys.add(t['execute_key'])
        if len(terms) > 1 and not entry['composable']:
            f('target_term_not_composable', p)
        _amt_entry_ok(ctx, idx)
        dsteps = proj['descriptors'][idx].get('steps')
        if not isinstance(dsteps, list):
            f('catalog_descriptor_steps', '/projection/catalog_description/programs/%d/steps' % idx)
        steps += len(dsteps)
        if steps > proj['policy']['catalog_limits']['max_expanded_steps']:
            f('target_expanded_steps', '/target/terms')
        union |= set(sm.values())
    if union != set(ordered):
        f('target_term_roles', '/target/terms')
    return deepcopy(payload)


def _amt_guard(fn, *args):
    try:
        return fn(*args)
    except (TypeError, KeyError, IndexError, AttributeError, OverflowError, RecursionError, UnicodeError):
        _amt_f('malformed_input', None)


def _amt_build(ctx, reading, candidate, text):
    f = _amt_f
    proj, lim = ctx['proj'], ctx['limits']
    if type(text) is not str:
        f('text_type', '/text')
    if _amt_utf8(text) > lim['max_input_bytes'] or len(text) > proj['text_limit']:
        f('text_too_large', '/text')
    _amt_plain(reading, 65536, True)
    _amt_plain(candidate, 65536, True)
    alts = _contextual_action_reading(reading, proj, text)
    if (reading['status'] != 'read' or reading['search_complete'] is not True
            or reading['truncated'] is not False or reading['gaps']):
        f('reading_incomplete', '/reading')
    if not isinstance(candidate, dict) or candidate.get('gaps') != []:
        f('candidate_gaps', '/candidate')
    ci = candidate.get('reading_candidate_index')
    alt = next((a for a in alts if type(ci) is int and a['index'] == ci), None)
    if alt is None:
        f('candidate_index', '/candidate/reading_candidate_index')
    present = alt['present']
    if candidate.get('consumed_slots') != sorted(present):
        f('candidate_consumed_slots', '/candidate/consumed_slots')
    cterms = candidate.get('terms')
    if not isinstance(cterms, list):
        f('candidate_terms', '/candidate/terms')
    tkeys = {'id', 'version', 'execute_key', 'label', 'roles', 'source_ref'}
    terms = []
    for i, ct in enumerate(cterms):
        p = '/candidate/terms/%d' % i
        if not isinstance(ct, dict) or set(ct) != tkeys:
            f('candidate_term_keys', p)
        idx = ctx['index'].get(ct['execute_key'])
        if idx is None:
            f('candidate_term_unknown', p)
        entry = proj['entries'][idx]
        if (ct['id'] != entry['id'] or ct['version'] != entry['version']
                or type(ct['version']) is not type(entry['version'])
                or ct['source_ref'] != '/source_maps/catalog/entries/%d' % idx):
            f('candidate_term_identity', p)
        if (not isinstance(ct['roles'], dict) or set(ct['roles']) != set(entry['roles'])
                or any(s not in present or present[s] != ct['roles'][s] for s in entry['roles'])):
            f('candidate_term_roles', p + '/roles')
        terms.append({'id': entry['id'], 'version': entry['version'], 'execute_key': ct['execute_key'],
                      'source_ref': ct['source_ref'],
                      'program_sha256': _contextual_action_sha(entry['program']),
                      'slot_map': {s: s for s in entry['roles']}})
    order = [s[0] for s in sorted(alt['spans'], key=lambda s: s[3][0])]
    decl = _amt_decl(ctx)
    rp = {'offset_unit': 'unicode_codepoint', 'ordered_slots': order, 'slots': decl,
          'omitted_slots': [d['slot'] for d in decl if d['slot'] not in present]}
    payload = {'schema': 'lexical-action-meaning-target-v1',
               'surface': {'text': reading['unknown_text'], 'surface_id': proj['surface_id'],
                           'declaration_sha256': ctx['surface_sha']},
               'role_pattern': rp, 'role_pattern_sha256': _contextual_action_sha(rp), 'terms': terms}
    return _amt_validate(ctx, payload)


def _amt_render(ctx, target, kind, answer):
    f = _amt_f
    if kind not in ('question', 'used'):
        f('render_kind', '/kind')
    if answer is not None:
        if type(answer) is not str:
            f('render_answer', '/answer')
        _amt_utf8(answer)
    if kind == 'used' and answer:
        f('render_answer', '/answer')
    proj, render, parts, labels = ctx['proj'], ctx['render'], ctx['parts'], ctx['labels']
    roles_txt = []
    for slot in target['role_pattern']['ordered_slots']:
        d = proj['roles'][slot]
        markers = render['marker_separator'].join(proj['groups'][d['case_group']])
        roles_txt.append(_amt_fill(parts['role'], {'slot_label': labels[slot], 'markers': markers})[0])
    role_text = render['role_separator'].join(roles_txt)
    terms_txt = []
    for n, term in enumerate(target['terms']):
        idx = ctx['index'][term['execute_key']]
        entry = proj['entries'][idx]
        lab = proj['labels'][idx] if isinstance(proj['labels'], list) else proj['labels'].get(term['execute_key'])
        if type(lab) is not str or not lab:
            f('program_label_unavailable', '/projection/entry_labels')
        binds = [_amt_fill(parts['binding'], {'program_role_label': labels[k],
                                              'surface_role_label': labels[term['slot_map'][k]]})[0]
                 for k in entry['roles']]
        terms_txt.append(_amt_fill(parts['term'], {'ordinal': str(n + 1), 'program': lab,
                                                   'bindings': render['binding_separator'].join(binds)})[0])
    meaning = render['term_separator'].join(terms_txt)
    values = {'expression': target['surface']['text'], 'role_pattern': role_text, 'meaning': meaning}
    qtext = _amt_fill(parts[kind], values)[0]
    span, text = None, qtext
    if kind == 'question' and answer:
        text, pos = _amt_fill(parts['question_with_answer'], {'answer': answer, 'question': qtext})
        span = pos['question']
        if text.count(qtext) != 1 or text[span[0]:span[1]] != qtext:
            f('render_question_placement', '/render')
    elif kind == 'question':
        span = [0, len(qtext)]
    if _amt_utf8(text) > ctx['limits']['max_question_bytes']:
        f('render_too_large', '/render')
    if kind == 'used':
        return {'text': text, 'question_span': None, 'question_template_id': None,
                'question_template_sha256': None}
    import hashlib
    return {'text': text, 'question_span': span, 'question_template_id': 'question',
            'question_template_sha256': hashlib.sha256(render['question'].encode('utf-8')).hexdigest()}


def _amt_result(status, matches, complete, truncated, gaps):
    return {'schema': 'lexical-action-meaning-match-v1', 'status': status, 'matches': matches,
            'search_complete': complete, 'truncated': truncated, 'gaps': gaps}


def _amt_match(ctx, target, reading, text):
    f = _amt_f
    proj, lim = ctx['proj'], ctx['limits']
    if type(text) is not str:
        f('text_type', '/text')
    if _amt_utf8(text) > lim['max_input_bytes'] or len(text) > proj['text_limit']:
        f('text_too_large', '/text')
    _amt_plain(reading, 65536, True)
    alts = _contextual_action_reading(reading, proj, text)
    trunc = reading['truncated']
    status = reading['status']
    diag = [g for g in reading['gaps'] if not (status == 'no_match' and g['code'] == 'no_structural_candidate')]
    if (status not in ('read', 'no_match') or reading['search_complete'] is not True or trunc is not False
            or diag):
        gaps = [{'code': str(g['code'])[:128], 'path': g['path'] if isinstance(g['path'], str) else None}
                for g in diag]
        return _amt_result('gap', [], False, trunc is True,
                           gaps or [{'code': 'reader_incomplete', 'path': '/reading'}])
    if len(alts) > proj['policy']['limits']['max_candidates']:
        return _amt_result('gap', [], False, True, [{'code': 'reader_alternative_cap', 'path': '/reading'}])
    rp = target['role_pattern']
    names = [d['slot'] for d in rp['slots']]
    matches = []
    for alt in alts:
        present = alt['present']
        order = [s[0] for s in sorted(alt['spans'], key=lambda s: s[3][0])]
        if (reading['unknown_text'] != target['surface']['text'] or order != rp['ordered_slots']
                or [n for n in names if n not in present] != rp['omitted_slots']):
            continue
        rows = []
        for term in target['terms']:
            rows.append({'id': term['id'], 'version': term['version'], 'execute_key': term['execute_key'],
                         'source_ref': term['source_ref'], 'program_sha256': term['program_sha256'],
                         'roles': {k: present[v] for k, v in term['slot_map'].items()}})
        matches.append({'reading_candidate_index': alt['index'],
                        'slot_values': {s: present[s] for s in rp['ordered_slots']}, 'terms': rows})
    result = _amt_result('matched' if matches else 'no_match', matches, True, False, [])
    if len(_contextual_action_canon(result).encode('utf-8')) > proj['policy']['limits']['max_output_bytes']:
        return _amt_result('gap', [], False, True, [{'code': 'output_cap', 'path': None}])
    return result


def build_action_meaning_target(action_projection, learning_projection, reading, candidate, *, binding, text):
    ctx = _amt_guard(_amt_ctx, action_projection, learning_projection, binding)
    return _amt_guard(_amt_build, ctx, reading, candidate, text)


def validate_action_meaning_target(action_projection, learning_projection, payload, *, binding):
    ctx = _amt_guard(_amt_ctx, action_projection, learning_projection, binding)
    return _amt_guard(_amt_validate, ctx, payload)


def render_action_meaning(action_projection, learning_projection, payload, *, binding, kind='question',
                          answer=None):
    ctx = _amt_guard(_amt_ctx, action_projection, learning_projection, binding)
    target = _amt_guard(_amt_validate, ctx, payload)
    return _amt_guard(_amt_render, ctx, target, kind, answer)


def match_action_meaning(action_projection, learning_projection, payload, reading, *, binding, text):
    caps = ('text_too_large', 'target_too_large', 'json_too_large', 'json_too_deep', 'json_integer_too_large',
            'input_ceiling', 'output_cap', 'reader_alternative_cap', 'render_too_large',
            'target_expanded_steps', 'catalog_entry_walk')
    try:
        ctx = _amt_ctx(action_projection, learning_projection, binding)
        target = _amt_validate(ctx, payload)
        return _amt_match(ctx, target, reading, text)
    except ValueError as exc:
        args = exc.args
        if len(args) == 1 and isinstance(args[0], tuple) and len(args[0]) == 2:
            code, path = args[0]
        else:
            code, path = 'computation_error', None
    except (TypeError, KeyError, IndexError, AttributeError, OverflowError, RecursionError, UnicodeError):
        code, path = 'computation_error', None
    code = str(code)[:128]
    return _amt_result('gap', [], False, code in caps,
                       [{'code': code, 'path': path[:256] if isinstance(path, str) else None}])
