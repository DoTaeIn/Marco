# -*- coding: utf-8 -*-
"""Transport onto the pre-existing search.

``marco.reasoning.relation_hypotheses._evaluate_world`` is the search of this
repository and is used unchanged.  This module only projects reading rows into
the fact shape that helper accepts and hands the row provenance through as
``fact_sources``, so every match comes back with its spans, its claim and its
scope attached.

No search, closure, ranking or selection is implemented here.

Two properties this module is responsible for:

*   **Identical triples are one fact, with every source kept.**  The reading
    emits a per-reading copy of a row, and the existing engine refuses a world
    where one triple has more than ``_SUPPORT_LIMIT`` positive supports.  A
    merged fact carries the union of its rows' spans, claims, scopes, readings,
    hypotheses and proofs, so merging costs no provenance.  Polarity and
    modality are part of the merge key, so a denial is never merged into an
    assertion and a contradiction survives as two facts.
*   **Incompleteness is never hidden.**  ``search_rows`` returns whatever the
    helper assembled, including ``complete: False`` and the helper's reason, and
    returns an explicit incomplete carrier rather than raising when no world
    could be assembled at all.  ``matches`` refuses to hand back bindings from
    an incomplete world unless the caller asks for them, because rivals or
    support may have been truncated.
"""
from marco.reasoning.relation_hypotheses import _evaluate_world


class IncompleteSearch(LookupError):
    """The existing search did not assemble a complete world.

    Carries the helper's ``reason`` and the world it did assemble, so a caller
    can report the gap instead of answering from truncated evidence.
    """

    def __init__(self, reason, world=None):
        super(IncompleteSearch, self).__init__(
            "the existing search returned an incomplete world: %s" % (reason,))
        self.reason = reason
        self.world = world


def _merge_source(into, row):
    for key, plural in (("claim", "claims"), ("scope_kind", "scope_kinds"),
                        ("reading", "readings"), ("layer", "layers"),
                        ("construction", "constructions"),
                        ("grammatical_role", "grammatical_roles"),
                        ("semantic_role", "semantic_roles"),
                        ("role_interpretation", "role_interpretations"),
                        ("typing_policy", "typing_policies"),
                        ("semantic_status", "semantic_statuses"),
                        ("predicate_kind", "predicate_kinds"),
                        ("agency_status", "agency_statuses")):
        value = row.get(key)
        if value not in into[plural]:
            into[plural].append(value)
    for span in row["spans"]:
        span = list(span)
        if span not in into["spans"]:
            into["spans"].append(span)
    for item in row.get("hypotheses") or ():
        if item not in into["hypotheses"]:
            into["hypotheses"].append(item)
    for item in row.get("depends_on") or ():
        if item not in into["depends_on"]:
            into["depends_on"].append(item)
    if row.get("proof") and row["proof"] not in into["proofs"]:
        into["proofs"].append(row["proof"])
        if into["proof"] is None:
            into["proof"] = row["proof"]
    if row["id"] not in into["rows"]:
        into["rows"].append(row["id"])


def _new_source(row):
    source = {"row": row["id"], "rows": [], "spans": [],
              "claim": row["claim"], "claims": [],
              "scope_kind": row.get("scope_kind"), "scope_kinds": [],
              "layer": row.get("layer"), "layers": [],
              "construction": row.get("construction"), "constructions": [],
              "reading": row.get("reading"), "readings": [],
              "hypotheses": [], "depends_on": [], "proof": row.get("proof"),
              "proofs": [],
              "grammatical_role": row.get("grammatical_role"), "grammatical_roles": [],
              "semantic_role": row.get("semantic_role"), "semantic_roles": [],
              "role_interpretation": row.get("role_interpretation"), "role_interpretations": [],
              "typing_policy": row.get("typing_policy"), "typing_policies": [],
              "semantic_status": row.get("semantic_status"), "semantic_statuses": [],
              "predicate_kind": row.get("predicate_kind"), "predicate_kinds": [],
              "agency_status": row.get("agency_status"), "agency_statuses": []}
    _merge_source(source, row)
    return source


def project_rows(reading, rows=None):
    """``(facts, fact_sources)`` for the existing search helper.

    One fact per distinct ``(triple, modality, polarity)``; its source carries
    every row that supports it.
    """
    chosen = reading["rows"] if rows is None else rows
    order, facts, sources = [], {}, {}
    for row in chosen:
        triple = [str(atom) for atom in row["triple"]]
        modality = row.get("modality", "asserted")
        polarity = bool(row["polarity"])
        key = (tuple(triple), modality, polarity)
        if key not in facts:
            order.append(key)
            facts[key] = {"id": row["id"], "triple": triple,
                          "modality": modality, "polarity": polarity}
            sources[key] = _new_source(row)
        else:
            _merge_source(sources[key], row)
    return [facts[key] for key in order], [sources[key] for key in order]


def select_rows(reading, subjects=None, predicates=None, claims=None, scope_kinds=None,
                layers=None, readings=None):
    """Rows of a reading narrowed by their own fields.

    The pre-existing search assembles a finite world and reports
    ``complete: False`` with ``reason: "graph_limit"`` once a projection grows
    past its fact limit.  That limit belongs to the search and is not changed
    here, so a caller working on a long document projects the rows its query
    needs and reads the rest in a second projection.  This is a field filter
    over rows, not a search: it ranks nothing and infers nothing.
    """
    found = []
    for row in reading["rows"]:
        subject, predicate, _ = row["triple"]
        if subjects is not None and subject not in subjects:
            continue
        if predicates is not None and predicate not in predicates:
            continue
        if claims is not None and row["claim"] not in claims:
            continue
        if scope_kinds is not None and row.get("scope_kind") not in scope_kinds:
            continue
        if layers is not None and row.get("layer") not in layers:
            continue
        if readings is not None and row.get("reading") not in readings:
            continue
        found.append(row)
    return found


def search_rows(reading, query_triple, rules=(), rows=None):
    """Run the unchanged native search over an explicitly identified projection.

    Without rules, fixed query atoms cannot match any other triple; retain all
    rows compatible with those atoms, including both polarities and every
    source. Rules may derive across predicates, so their inputs stay whole.
    Caller-supplied rows limit the source universe and are identified as such.
    """
    query = [str(atom) for atom in query_triple]
    rules = list(rules)
    chosen = list(reading["rows"] if rows is None else rows)
    direct = not rules and len(query) == 3
    if direct:
        chosen_for_query = [row for row in chosen
                            if len(row["triple"]) == 3 and all(
                                atom[:1] in ("?", "$") or atom == str(value)
                                for atom, value in zip(query, row["triple"]))]
    else:
        chosen_for_query = chosen
    facts, sources = project_rows(reading, chosen_for_query)
    projection = {"kind": "direct_query" if direct else "full_input",
                  "input_scope": "reading" if rows is None else "caller_rows",
                  "input_rows": len(chosen), "projected_rows": len(chosen_for_query),
                  "projected_facts": len(facts),
                  "all_matching_rows_included": direct,
                  "whole_reading_included": rows is None and len(chosen_for_query) == len(chosen),
                  "reading_complete": reading.get("limits", {}).get("complete")}
    world, gap = _evaluate_world(facts, sources, rules, query)
    if world is None:
        return {"matches": [], "facts": [], "proof_bundles": [],
                "fact_sources": [{"premise_id": None, "fact_index": index,
                                  "original_fact": fact, "source_ref": source}
                                 for index, (fact, source) in
                                 enumerate(zip(facts, sources))],
                "rules": rules, "complete": False, "reason": gap,
                "searches": 0, "assembled": False, "projection": projection}
    world = dict(world)
    world["assembled"] = True
    world["projection"] = projection
    return world


def _premise_ids(world, support_id):
    """The premise fact ids a support actually rests on.

    Read from ``proof_bundles``, the structure the engine publishes, rather
    than by stripping a prefix off the support id: a bundle may rest on more
    than one premise, and a change to the id shape must not silently point the
    evidence at the wrong premise or lose it.
    """
    found = []
    for bundle_group in world.get("proof_bundles", ()):
        for bundle in bundle_group.get("bundles", ()):
            if bundle.get("id") != support_id:
                continue
            for premise in bundle.get("premise_fact_ids", ()):
                if premise not in found:
                    found.append(premise)
    return found


def matches(reading, query_triple, rules=(), rows=None, require_complete=True):
    """``(bindings, source_refs, triple)`` for a query, in the search's order.

    Raises ``IncompleteSearch`` when the world is not complete, unless the
    caller passes ``require_complete=False`` and takes responsibility for the
    truncation: an exact answer may not be read out of truncated evidence.
    """
    world = search_rows(reading, query_triple, rules, rows)
    if require_complete and not world.get("complete"):
        raise IncompleteSearch(world.get("reason"), world)
    by_premise = {item["premise_id"]: item for item in world["fact_sources"]}
    found = []
    for match in world["matches"]:
        refs = []
        for support in match["support_ids"]:
            premises = _premise_ids(world, support)
            for premise in premises:
                entry = by_premise.get(premise)
                if entry and entry.get("source_ref") and entry["source_ref"] not in refs:
                    refs.append(entry["source_ref"])
        found.append((match["bindings"], refs, match["triple"]))
    return found
