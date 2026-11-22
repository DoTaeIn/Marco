"""QuestionPlan -> evaluation result.

Executes the declarative hop sequence in ``graphs/questions/plans.json``.
Every hop is exactly one ``core.search_rows`` call (transport onto the
existing, unchanged ``marco.reasoning.relation_hypotheses._evaluate_world``);
this module does no parsing and makes no decision about what a span means --
it only threads bound values from one hop's triple into the next's, and
reports which named gate stopped it when a hop finds nothing, or when a
required argument has more than one candidate and nothing here picks a
winner. Which gate a given empty or ambiguous result counts as, and which
bind is the answer, are the plan's own declared fields, not a branch written
here. A fact's own ``polarity`` (negated vs. asserted, CONTRACT.md section 4)
is read back through the same provenance path as its ``source_ref`` and
folded into the looked-up ``case`` value via ``outcome_polarity.json`` --
also a lookup, not a branch -- so a negated checking action is never read as
a negative checking result. Every ``search_rows`` call goes through
:func:`_safe_search`, which turns a transport-layer ``LookupError`` (the
engine's own support/search limit, AUDITOR.md review 7 / CORE-SECOND-AUDIT.md
A9) and a world whose own ``complete`` is ``False`` into the same
``_IncompleteSearch`` signal, caught once at the top of :func:`execute_plan`
and reported as the ``incomplete_search`` gate -- a single surviving match
from a non-exhaustive search is not treated as an authorized exact answer.
"""
import json
import os

from experiments.graph_language_repair.questions.compile import slot_value

_GRAPHS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "graphs", "questions")


def _load(name):
    with open(os.path.join(_GRAPHS_DIR, name), "r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_plans():
    return _load("plans.json")["plans"]


def _default_search_rows():
    from experiments.graph_language_repair.core import search_rows
    return search_rows


class _IncompleteSearch(Exception):
    """Raised when a hop's search cannot support an exact, authorized
    answer: the engine itself raised (AUDITOR.md review 7 /
    CORE-SECOND-AUDIT.md A9's uncaught ``LookupError`` on the support
    limit), returned something that isn't a world at all, or returned a
    world whose own ``complete`` is ``False`` -- rivals or supporting facts
    may have been truncated before this hop ever saw them, so a single
    surviving match there is not license to answer as if it were unique.
    """

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _world_matches(result):
    if result is None:
        return [], [], []
    world = result[0] if isinstance(result, tuple) else result
    if not isinstance(world, dict):
        return [], [], []
    return (world.get("matches", []) or [], world.get("fact_sources", []) or [],
            world.get("proof_bundles", []) or [])


def _safe_search(reading, search_rows, triple):
    """``search_rows(reading, triple)``, degraded to :class:`_IncompleteSearch`
    instead of a crash or a silently-accepted truncation.
    """
    try:
        result = search_rows(reading, triple)
    except LookupError as exc:
        raise _IncompleteSearch("search_error:%s" % exc) from exc
    world = result[0] if isinstance(result, tuple) else result
    if not isinstance(world, dict):
        raise _IncompleteSearch("invalid_world")
    if world.get("complete") is not True:
        raise _IncompleteSearch(world.get("reason") or "incomplete_search")
    return (world.get("matches", []) or [], world.get("fact_sources", []) or [],
            world.get("proof_bundles", []) or [])


def _premise_ids(support_ids, proof_bundles):
    """Proof-bundle row ids (``match["support_ids"]``) -> fact premise ids.

    ``_evaluate_world`` sets a match's ``support_ids`` to proof-bundle row
    ids (``bundle["id"]``, e.g. ``"support:baseline:0"``), not directly to a
    ``fact_sources`` ``premise_id`` -- the bundle's own ``premise_fact_ids``
    is the bridge (CONTRACT.md section 6). A support id with no matching
    bundle is treated as a premise id directly, so a fixture that skips
    proof bundles still works.
    """
    bundle_by_id = {}
    for entry in proof_bundles:
        for bundle in entry.get("bundles", []) or []:
            if bundle.get("id") is not None:
                bundle_by_id[bundle["id"]] = bundle
    premise_ids = set()
    for support_id in support_ids:
        bundle = bundle_by_id.get(support_id)
        if bundle is not None:
            premise_ids.update(bundle.get("premise_fact_ids", []) or [])
        else:
            premise_ids.add(support_id)
    return premise_ids


def _provenance(support_ids, fact_sources, proof_bundles):
    """``(source_refs, polarities)`` for the fact premises ``support_ids`` cites.

    ``polarities`` is the set of ``original_fact["polarity"]`` values seen
    (default ``True`` when the field is absent, per the general row
    convention that an unmarked row is a positive assertion).
    """
    premise_ids = _premise_ids(support_ids, proof_bundles)
    source_refs, polarities = [], set()
    if not premise_ids:
        raise _IncompleteSearch("unresolved_provenance")
    resolved = set()
    for descriptor in fact_sources:
        if descriptor.get("premise_id") not in premise_ids:
            continue
        reference = descriptor.get("source_ref")
        original = descriptor.get("original_fact") or {}
        if not isinstance(reference, dict) or not isinstance(original.get("polarity"), bool):
            raise _IncompleteSearch("unresolved_provenance")
        source_refs.append(reference)
        polarities.add(original["polarity"])
        resolved.add(descriptor["premise_id"])
    if resolved != premise_ids:
        raise _IncompleteSearch("unresolved_provenance")
    return source_refs, polarities


def _candidates(matches, fact_sources, proof_bundles, prior):
    out = []
    for match in matches:
        bindings = match.get("bindings") or {}
        if len(bindings) != 1:
            continue
        value = next(iter(bindings.values()))
        support_ids = list(match.get("support_ids", []) or [])
        source_refs, polarities = _provenance(support_ids, fact_sources, proof_bundles)
        if prior:
            for base in prior:
                # polarity is deliberately NOT inherited from an earlier hop: it
                # must reflect only the fact that produced *this* value (e.g. the
                # checking_outcome row itself), not an unrelated earlier hop's
                # fact (e.g. the checking_actor row used only to find the event).
                out.append({"value": value,
                             "support_ids": sorted(set(base["support_ids"]) | set(support_ids)),
                             "source_refs": base["source_refs"] + source_refs,
                             "polarities": set(polarities)})
        else:
            out.append({"value": value, "support_ids": support_ids,
                         "source_refs": source_refs, "polarities": polarities})
    return out


def _dedupe(candidates):
    seen = {}
    for cand in candidates:
        existing = seen.get(cand["value"])
        if existing is None:
            seen[cand["value"]] = {"value": cand["value"],
                                    "support_ids": list(cand["support_ids"]),
                                    "source_refs": list(cand["source_refs"]),
                                    "polarities": set(cand["polarities"])}
        else:
            existing["support_ids"] = sorted(set(existing["support_ids"]) | set(cand["support_ids"]))
            existing["source_refs"] = existing["source_refs"] + cand["source_refs"]
            existing["polarities"] = existing["polarities"] | cand["polarities"]
    return list(seen.values())


def _fill(atom, mapping):
    if isinstance(atom, str) and atom[:1] == "{" and atom[-1:] == "}" and atom[1:-1] in mapping:
        return mapping[atom[1:-1]]
    return atom


def _filter_existing(candidates, predicate, value, reading, search_rows):
    """Keep only candidates for which ``[candidate_value, predicate, value]``
    is an actual fact -- a fully-ground existence check, not a value lookup
    (``bind()`` on a variable-free triple returns ``{}`` on a match, so this
    does not go through :func:`_candidates`, which requires exactly one
    bound variable). Used to intersect a second, third, ... explicit role
    constraint onto the same event the anchor hop already found (AUDITOR.md
    review 8 item 1), and to require a question's named action to be the
    event's actual action (review 8 item 2).
    """
    out = []
    for cand in candidates:
        triple = [cand["value"], predicate, value]
        matches, fact_sources, proof_bundles = _safe_search(reading, search_rows, triple)
        if not matches:
            continue
        support_ids = []
        for match in matches:
            support_ids.extend(match.get("support_ids", []) or [])
        source_refs, _unused_polarities = _provenance(support_ids, fact_sources, proof_bundles)
        out.append({"value": cand["value"],
                     "support_ids": sorted(set(cand["support_ids"]) | set(support_ids)),
                     "source_refs": cand["source_refs"] + source_refs,
                     "polarities": set(cand["polarities"])})
    return out


def _filter_action(candidates, action, reading, search_rows):
    """Like :func:`_filter_existing` for ``[event, "action", action]``, but
    tolerant of a negated event: ``_filter_existing`` alone would wrongly
    reject every candidate there, because a negative-polarity action row is
    not retrievable by a plain positive triple query in this engine (the
    same reason ``plans.json``'s ``polarity_gate`` exists for checking
    rows) -- it is not evidence the action doesn't match, only that it
    can't be read this way. A candidate kept for this reason still goes
    through ``merge_event_polarity_into_answer`` afterwards, which is what
    actually discloses the negation in the rendered answer.
    """
    typed = _filter_existing(candidates, "action_type", action, reading, search_rows)
    known = {candidate["value"] for candidate in typed}
    return typed + _filter_existing([candidate for candidate in candidates if candidate["value"] not in known],
                                    "action", action, reading, search_rows)


def _intersect(a, b):
    by_value = {}
    for cand in a:
        by_value.setdefault(cand["value"], []).append(cand)
    out = []
    for cand in b:
        for other in by_value.get(cand["value"], []):
            out.append({"value": cand["value"],
                         "support_ids": sorted(set(cand["support_ids"]) | set(other["support_ids"])),
                         "source_refs": cand["source_refs"] + other["source_refs"],
                         "polarities": cand["polarities"] | other["polarities"]})
    return out


def _choose_anchor(plan, priority):
    """First grammatical function in ``priority`` actually present in the slots.

    Returns ``(function, value, status)``. Stops at the first function that
    has *any* occurrence rather than skipping an ambiguous one for a lower-
    priority function -- the question did mark that function, just more than
    once, which is itself the thing to disclose, not a reason to pretend a
    weaker candidate is what was asked.
    """
    for function in priority:
        value, status = slot_value(plan["slots"], function)
        if status != "missing":
            return function, value, status
    return None, None, "missing"


def _value_hop_anchor(plan, spec):
    if "anchor_value" in plan:
        # checking_role_question: compile.py already resolved exactly which
        # slot anchors the query and which checking predicate it is, because
        # that resolution depends on the cue's own role_query_predicates, not
        # on a plan-wide priority list.
        anchor = next((f for f, p in spec.get("function_to_predicate", {}).items()
                       if p == plan["anchor_predicate"] and slot_value(plan["slots"], f)[0] == plan["anchor_value"]), None)
        return anchor, plan["anchor_value"], plan["anchor_predicate"], "ok"
    priority = spec["value_function_priority"] if "value_function_priority" in spec \
        else plan.get("anchor_priority", [])
    function, value, status = _choose_anchor(plan, priority)
    predicate = plan.get("function_overrides", {}).get(function, spec["function_to_predicate"].get(function)) if function else None
    return function, value, predicate, status


def _polarity_key(polarities):
    if not polarities:
        return "polarity_unknown"
    if polarities == {True}:
        return "polarity_true"
    if polarities == {False}:
        return "polarity_false"
    return "polarity_mixed"


def _apply_outcome_polarity(intent, case, candidate, plan):
    """Fold a candidate's fact polarity into its ``case`` value via a lookup.

    Returns the effective value to use for template selection. A checking
    row whose own ``polarity`` is ``false`` means the checking *action* was
    negated (CONTRACT.md C5's own wording: "checking_outcome: denied from a
    negated [checking action]"), not that a performed check found a negative
    result; this is how that is told apart, driven entirely by
    ``outcome_polarity.json``, not a Python branch on the literal string
    "denied".
    """
    policy = _load("outcome_polarity.json")
    key = _polarity_key(candidate["polarities"])
    passthrough = policy.get("requested_polarity_passthrough", {}).get(intent, {}).get(case, {})
    if key in passthrough.get(plan.get("required_polarity"), []):
        return candidate["value"]
    table = policy.get(intent, {}).get(case, {})
    override = table.get(_polarity_key(candidate["polarities"]))
    return override if override is not None else candidate["value"]


def execute_plan(plan, reading, *, search_rows=None):
    """Run ``plan`` (from ``questions.compile.compile_question``) against ``reading``.

    Returns a dict ``{"intent", "gate", "reason", "case", "value",
    "raw_value", "candidates", "state"}``. ``gate`` is ``None`` on success.
    ``value`` has already been through :func:`_apply_outcome_polarity`;
    ``raw_value`` is the literal fact value before that lookup, kept for
    transparency. ``candidates`` holds the winning bind's deduplicated
    values with merged provenance (``support_ids``, ``source_refs`` --
    ``source_ref`` dicts from ``world["fact_sources"]`` per CONTRACT.md
    section 6 -- and ``polarities``). ``state`` exposes every intermediate
    bind (e.g. the occurrence plan's ``reporter`` bind) for templates that
    need supplementary attribution text.
    """
    if isinstance(reading, dict) and (reading.get("limits", {}).get("notes") or reading.get("limits", {}).get("complete") is False):
        return {"intent": plan.get("intent"), "gate": "incomplete_search", "reason": "reading_limit",
                "case": None, "value": None, "raw_value": None, "candidates": [], "state": {}}
    if plan.get("unresolved"):
        return {"intent": plan["intent"], "gate": "unresolved", "reason": "unresolved",
                 "case": None, "value": None, "raw_value": None, "candidates": [], "state": {}}

    intent = plan["intent"]
    aliases = _load("plans.json").get("goal_intents", {})
    intent = aliases.get(intent, {}).get(plan.get("goal"), intent)
    spec = _load_plans()[intent]
    if search_rows is None:
        search_rows = _default_search_rows()

    try:
        result = _run_plan(plan, reading, search_rows, intent, spec)
        # Only readings whose event survived every question constraint can
        # compete in the requested answer; expose this without discarding
        # full-reading contradictions or their raw provenance.
        if isinstance(reading, dict) and spec.get("value_hop"):
            event_bind = spec["value_hop"]["bind"]
            events = {c.get("value") for c in result.get("state", {}).get(event_bind, [])}
            result["compatible_events"] = sorted(events)
            result["compatible_readings"] = sorted(r["id"] for r in reading.get("readings", [])
                                                   if events.intersection(r.get("events", [])))
        if isinstance(reading, dict) and plan.get("asked_predicate") and result.get("gate") is None:
            answer_predicate = plan["asked_predicate"]
            ids = {rid for cand in result.get("candidates", []) for ref in cand.get("source_refs", [])
                   for rid in (ref.get("rows") or ([ref["row"]] if ref.get("row") else []))}
            relation_policy = _load("plans.json").get("role_typing_relations", {})
            typed = [{"row": row["id"], "role_interpretation": row.get("role_interpretation"),
                      "semantic_role": row.get("semantic_role"), "grammatical_role": row.get("grammatical_role"),
                      "relation": relation_policy.get(row.get("role_interpretation"))}
                     for row in reading.get("rows", []) if row.get("id") in ids
                     and row.get("triple", [None, None])[1] == answer_predicate
                     and row.get("role_interpretation") in relation_policy]
            if typed:
                result["answer_role_typing"] = typed
                relations = {item["relation"] for item in typed}
                if len(relations) == 1:
                    result["semantic_relation"] = next(iter(relations))
                    result["semantic_value"] = result.get("raw_value")
                    result["semantic_candidates"] = result.get("candidates", [])
        projection = spec.get("semantic_projection", {})
        if projection and result.get("gate") is None:
            projected = result.get("state", {}).get(projection.get("bind"), [])
            if len(projected) == 1:
                result["semantic_relation"] = projection["relation"]
                result["semantic_value"] = (result["value"] if result.get("case") == projection.get("effective_case")
                                            else projected[0]["value"])
                result["semantic_candidates"] = projected
        for field in ("answer_scope", "requested_type", "type_verification"):
            if field in plan:
                result[field] = plan[field]
        return result
    except _IncompleteSearch as exc:
        return {"intent": intent, "gate": "incomplete_search", "reason": exc.reason,
                 "case": None, "value": None, "raw_value": None, "candidates": [], "state": {}}


def _run_plan(plan, reading, search_rows, intent, spec):
    state = {}
    supported = set(spec.get("function_to_predicate", {}))
    extra = [function for function, values in plan.get("slots", {}).items() if values and function not in supported]
    if extra:
        return {"intent": intent, "gate": "unresolved", "reason": "unsupported_constraints:" + ",".join(extra),
                "case": None, "value": None, "raw_value": None, "candidates": [], "state": {}}
    if "value_hop" in spec:
        function, value, predicate, status = _value_hop_anchor(plan, spec)
        if status == "ambiguous":
            return {"intent": intent, "gate": "ambiguous_value_slot", "reason": "ambiguous_value_slot",
                     "case": None, "value": None, "raw_value": None, "candidates": [], "state": {}}
        value_hop = spec["value_hop"]
        candidates = []
        if value is None or predicate is None:
            if not plan.get("allow_event_enumeration"):
                return {"intent": intent, "gate": "no_value_slot", "reason": "no_value_slot",
                         "case": None, "value": None, "raw_value": None, "candidates": [], "state": {}}
            # One grounded object per search: all polarities are explored if
            # no predicate was named, so negated and rival events survive.
            actions = plan.get("required_actions") or ([plan["required_action"]] if plan.get("required_action") else [])
            triples = ([["?event", "action_type", action] for action in actions]
                       if actions else [["?event", "polarity", polarity] for polarity in ("true", "false")])
        else:
            triples = [[_fill(atom, {"value": value, "predicate": pred}) for atom in value_hop["triple"]]
                       for pred in (predicate if isinstance(predicate, list) else [predicate])]
        for triple in triples:
            matches, fact_sources, proof_bundles = _safe_search(reading, search_rows, triple)
            candidates.extend(_candidates(matches, fact_sources, proof_bundles, []))
        candidates = _dedupe(candidates)
        if not candidates:
            return {"intent": intent, "gate": "no_event_match", "reason": "no_event_match",
                     "case": None, "value": None, "raw_value": None, "candidates": [], "state": {}}

        # Every OTHER function the question also named must bind the SAME
        # event the anchor found, not be silently dropped (AUDITOR review 8
        # item 1): intersect each as an existence check.
        for other_function, other_predicate in spec.get("function_to_predicate", {}).items():
            if other_function == function:
                continue
            other_predicate = plan.get("function_overrides", {}).get(other_function, other_predicate)
            other_value, other_status = slot_value(plan["slots"], other_function)
            if other_status == "ambiguous":
                return {"intent": intent, "gate": "ambiguous_value_slot", "reason": "ambiguous_value_slot",
                        "case": None, "value": None, "raw_value": None, "candidates": [], "state": {}}
            if other_status != "ok":
                continue
            filtered = []
            for pred in other_predicate if isinstance(other_predicate, list) else [other_predicate]:
                filtered.extend(_filter_existing(candidates, pred, other_value, reading, search_rows))
            candidates = _dedupe(filtered)
            if not candidates:
                return {"intent": intent, "gate": "conflicting_constraints",
                         "reason": "conflicting_constraints", "case": None, "value": None,
                         "raw_value": None, "candidates": [], "state": {}}

        # The question's own named action, if any, must be the event's
        # actual action (review 8 item 2) -- not silently ignored because
        # the role markers alone happened to match a different event.
        required_actions = plan.get("required_actions") or ([plan["required_action"]] if plan.get("required_action") else [])
        if required_actions:
            alternatives = []
            for action in required_actions:
                alternatives.extend(_filter_action(candidates, action, reading, search_rows))
            candidates = _dedupe(alternatives)
            if not candidates:
                return {"intent": intent, "gate": "conflicting_constraints",
                         "reason": "conflicting_constraints", "case": None, "value": None,
                         "raw_value": None, "candidates": [], "state": {}}

        if plan.get("required_polarity"):
            candidates = _filter_existing(candidates, "polarity", plan["required_polarity"], reading, search_rows)
            if not candidates:
                return {"intent": intent, "gate": "conflicting_constraints", "reason": "conflicting_constraints",
                        "case": None, "value": None, "raw_value": None, "candidates": [], "state": {}}

        if plan.get("query_surface_voice"):
            candidates = _filter_existing(candidates, "voice", plan["query_surface_voice"], reading, search_rows)
            if not candidates:
                return {"intent": intent, "gate": "conflicting_constraints", "reason": "conflicting_constraints",
                        "case": None, "value": None, "raw_value": None, "candidates": [], "state": {}}

        if plan.get("requires_unique_event") and isinstance(reading, dict):
            candidate_ids = {c["value"] for c in candidates}
            clauses = {event.get("clause") for event in reading.get("events", []) if event.get("id") in candidate_ids}
            if len(clauses) > 1:
                return {"intent": intent, "gate": "ambiguous_reading", "reason": "multiple_target_events",
                        "case": None, "value": None, "raw_value": None, "candidates": candidates, "state": {}}
        state[value_hop["bind"]] = candidates

    static = {"asked_predicate": plan.get("asked_predicate")}
    for hop in spec.get("hops", []):
        bind_name = hop["bind"]
        if "intersect" in hop:
            a, b = hop["intersect"]
            state[bind_name] = _dedupe(_intersect(state.get(a, []), state.get(b, [])))
            if bind_name == spec.get("voice_filter_bind") and plan.get("query_surface_voice"):
                state[bind_name] = _filter_existing(state[bind_name], "voice", plan["query_surface_voice"], reading, search_rows)
            if bind_name == spec.get("voice_filter_bind") and plan.get("required_result"):
                state[bind_name] = _filter_existing(state[bind_name], "checking_outcome", plan["required_result"], reading, search_rows)
            continue
        if "slot" in hop:
            value, status = slot_value(plan["slots"], hop["slot"])
            if status != "ok":
                state[bind_name] = []
                continue
            triple = [_fill(atom, {"value": value}) for atom in hop["triple"]]
            matches, fact_sources, proof_bundles = _safe_search(reading, search_rows, triple)
            state[bind_name] = _dedupe(_candidates(matches, fact_sources, proof_bundles, []))
            continue
        if "from" in hop:
            from_bind = hop["from"]
            results = []
            for cand in state.get(from_bind, []):
                bases = [cand]
                if hop.get("require_relation"):
                    witness, sources, bundles = _safe_search(reading, search_rows,
                        [cand["value"], hop["require_relation"], "?witness"])
                    witness_candidates = _candidates(witness, sources, bundles, [cand])
                    bases = [{"value": cand["value"], "support_ids": witness_cand["support_ids"],
                              "source_refs": witness_cand["source_refs"], "polarities": cand["polarities"],
                              "witness_value": witness_cand["value"]}
                             for witness_cand in witness_candidates]
                if not bases:
                    continue
                triple = [_fill(_fill(atom, static), {from_bind: cand["value"]}) for atom in hop["triple"]]
                matches, fact_sources, proof_bundles = _safe_search(reading, search_rows, triple)
                for base in bases:
                    selected = _candidates(matches, fact_sources, proof_bundles, [base])
                    dependency_relation = hop.get("require_dependency_relation")
                    if dependency_relation and isinstance(reading, dict):
                        links, sources, bundles = _safe_search(reading, search_rows,
                            [base["witness_value"], dependency_relation, cand["value"]])
                        link_support = [sid for match in links for sid in match.get("support_ids", [])]
                        if not links:
                            continue
                        link_refs, _ = _provenance(link_support, sources, bundles)
                        link_rows = {row for ref in link_refs for row in ref.get("rows", [ref.get("row")])}
                        indexed = {row["id"]: row for row in reading.get("rows", [])}
                        filtered = []
                        for item in selected:
                            ids = {rid for ref in item["source_refs"] for rid in ref.get("rows", [ref.get("row")])}
                            answer_rows = [indexed[rid] for rid in ids if rid in indexed and indexed[rid].get("triple", [None, None])[1] == triple[1]]
                            accepted = {row["id"] for row in answer_rows if link_rows.intersection(row.get("depends_on", []))}
                            if accepted:
                                precise = []
                                for ref in item["source_refs"]:
                                    ref_ids = ref.get("rows") or ([ref["row"]] if ref.get("row") else [])
                                    is_answer = any(rid in indexed and indexed[rid].get("triple", [None, None])[1] == triple[1] for rid in ref_ids)
                                    if is_answer:
                                        kept = [rid for rid in ref_ids if rid in accepted]
                                        if kept:
                                            precise.append({"row": kept[0], "rows": kept})
                                    else:
                                        precise.append(ref)
                                item["source_refs"] = precise + link_refs
                                item["support_ids"] = sorted(set(item["support_ids"]) | set(link_support))
                                filtered.append(item)
                        selected = filtered
                    results.extend(selected)
            state[bind_name] = _dedupe(results)
            continue
        raise ValueError("plan hop has neither slot, from nor intersect: %r" % (hop,))

    # A surviving same-clause rival without the requested role remains a
    # live interpretation, unless explicit question constraints excluded it.
    if plan.get("asked_predicate") and isinstance(reading, dict) and "value_hop" in spec:
        events = state.get(spec["value_hop"]["bind"], [])
        event_ids = {c["value"] for c in events}
        by_event = {event: entry for entry in reading.get("readings", [])
                    for event in entry.get("events", [])}
        for event in events:
            entry = by_event.get(event["value"], {})
            rivals = {r.get("id"): r for r in reading.get("readings", [])}
            if not any(set(rivals.get(other, {}).get("events", [])) & event_ids
                       for other in entry.get("competes_with", [])):
                continue
            matches, _, _ = _safe_search(reading, search_rows,
                                           [event["value"], plan["asked_predicate"], "?answer"])
            if not matches:
                return {"intent": intent, "gate": "ambiguous_reading", "reason": "rival_missing_asked_role",
                        "case": None, "value": None, "raw_value": None,
                        "candidates": state.get(spec["answer_bind"], []), "state": state}

    # Scope is attached to the event through native search hops. A quoted
    # proposition or a question is not an asserted occurrence. A separate,
    # independently linked result may answer an occurrence question.
    restricted = set(spec.get("nonassertive_scope", []))
    scopes = {c["value"] for c in state.get("scope", [])}
    allowed_bind = spec.get("independent_evidence_bind")
    if scopes & restricted and not (allowed_bind and state.get(allowed_bind)):
        return {"intent": intent, "gate": "nonassertive_scope", "reason": "nonassertive_scope",
                "case": None, "value": None, "raw_value": None,
                "candidates": state.get(spec.get("answer_bind"), []), "state": state}

    merge_bind = spec.get("merge_event_polarity_into_answer")
    if merge_bind:
        polarity_candidates = state.get(merge_bind, [])
        if polarity_candidates:
            # The enclosing event is negated. A role value is not, by itself,
            # evidence that its event occurred (review 8 item 3): override
            # rather than union, because the role row's own polarity (almost
            # always True -- "object is 책" is a true statement about the
            # clause's structure even when the clause's action is negated)
            # would otherwise read as "polarity_mixed", which means
            # disagreement, not negation.
            for cand in state.get(spec["answer_bind"], []):
                cand["polarities"] = {c["value"] == "true" for c in polarity_candidates if c["value"] in ("true", "false")}

    gate_spec = spec.get("polarity_gate")
    if gate_spec:
        gate_candidates = state.get(gate_spec["bind"], [])
        if len(gate_candidates) == 1 and gate_candidates[0]["value"] == gate_spec["negated_value"]:
            winner = gate_candidates[0]
            return {"intent": intent, "gate": None, "reason": None, "case": gate_spec["case"],
                     "value": "action_not_performed", "raw_value": winner["value"],
                     "candidates": [winner], "state": state}

    for entry in spec["case_priority"]:
        candidates = state.get(entry["bind"], [])
        if not candidates:
            continue
        if len(candidates) > 1:
            override = spec.get("multiple_case_override", {}).get(entry["case"])
            if override and len({c["value"] for c in candidates}) > 1:
                return {"intent": intent, "gate": None, "reason": None, "case": entry["case"],
                        "value": override, "raw_value": None, "candidates": candidates, "state": state}
            return {"intent": intent, "gate": "multiple_answers", "reason": "multiple_answers",
                     "case": entry["case"], "value": None, "raw_value": None,
                     "candidates": candidates, "state": state}
        winner = candidates[0]
        scopes = {c["value"] for c in state.get("scope", [])}
        reporters = {c["value"] for c in state.get("reporter", [])}
        if len(scopes) > 1 or len(reporters) > 1:
            return {"intent": intent, "gate": "multiple_sources", "reason": "distinct_source_branches",
                    "case": entry["case"], "value": None, "raw_value": winner["value"],
                    "candidates": candidates, "state": state}
        if not winner["polarities"] or not winner["source_refs"]:
            raise _IncompleteSearch("unresolved_provenance")
        effective_value = _apply_outcome_polarity(intent, entry["case"], winner, plan)
        # Contradictions qualify only the exact premise rows in this answer's
        # support chain; merged source_refs expose every constituent row.
        overrides = spec.get("contradiction_overrides", {}).get(entry["case"], {})
        row_ids = {row for ref in winner["source_refs"] for row in
                   (ref.get("rows") or ([ref["row"]] if ref.get("row") else []))}
        # Derived answer rows retain the exact dependency chain. Contradiction
        # annotations on a dependency qualify the selected result as well.
        if isinstance(reading, dict):
            rows = {row.get("id"): row for row in reading.get("rows", [])}
            pending = list(row_ids)
            while pending:
                row = rows.get(pending.pop(), {})
                for dependency in row.get("depends_on", []):
                    if dependency not in row_ids:
                        row_ids.add(dependency)
                        pending.append(dependency)
        conflicts = [item for item in (reading or {}).get("contradictions", [])
                     if item.get("kind") in overrides and row_ids.intersection(item.get("rows", []))]
        if conflicts:
            values = {overrides[item["kind"]] for item in conflicts}
            if len(values) != 1:
                raise _IncompleteSearch("ambiguous_contradiction_policy")
            effective_value = next(iter(values))
            state["result_conflicts"] = conflicts
        return {"intent": intent, "gate": None, "reason": None, "case": entry["case"],
                 "value": effective_value, "raw_value": winner["value"],
                 "candidates": candidates, "state": state}

    return {"intent": intent, "gate": "no_answer_row", "reason": "no_answer_row",
             "case": None, "value": None, "raw_value": None, "candidates": [], "state": state}
