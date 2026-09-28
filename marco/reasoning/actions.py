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
