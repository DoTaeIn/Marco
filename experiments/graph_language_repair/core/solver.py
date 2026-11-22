# -*- coding: utf-8 -*-
"""Clause solving as a constraint product, not an ordered gate chain.

A clause is one predicate hit plus the closing marker hits before it.  Each
marker element offers the syntactic classes its marker declares; the frame of
the predicate, at the predicate's voice, says which role a class fills.  Every
consistent combination is a solution and every surviving solution becomes a
reading.  A cue that is missing removes solutions; it never aborts the clause.

Nothing in this module names a marker, a role, a predicate or a language.
"""
import itertools

from experiments.graph_language_repair.core.chart import trim_span


class ClauseElement(object):
    """One marker-closed value span, with the classes its marker offers."""

    def __init__(self, value_span, marker_hit):
        self.value_span = value_span
        self.marker_hit = marker_hit

    @property
    def classes(self):
        return self.marker_hit["classes"] if self.marker_hit else ()


class ClauseDraft(object):
    def __init__(self, predicate_hit, clause_span, claim_id, segment):
        self.predicate = predicate_hit
        self.clause_span = clause_span
        self.claim_id = claim_id
        self.segment = segment
        self.solutions = []
        self.notes = []
        self.dropped = []


def _solution_policy(store):
    for record in store.of_kind("policy"):
        if record["key"].startswith("solution-policy:"):
            return record
    return {}


def _canonical(solution):
    roles = tuple(sorted((item["role"], item["value_span"]) for item in solution["roles"]))
    unused = tuple(sorted(item["value_span"] for item in solution["unused"]))
    return (roles, unused)


def _elements(chart, clause_span, segment_id, consumed=(), literal_markers=()):
    """Value spans closed by markers, left to right, plus the trailing residue."""
    elements, unhosted = [], []
    cursor = clause_span[0]
    for hit in chart.markers_within(clause_span, segment_id, attachment="closing"):
        if hit["span"] in literal_markers:
            continue
        for start_bound, end_bound in consumed:
            if cursor <= start_bound and end_bound <= hit["span"][0]:
                cursor = end_bound
        if any(hit["span"][0] < end_bound and start_bound < hit["span"][1]
               for start_bound, end_bound in consumed):
            cursor = max(cursor, hit["span"][1])
            continue
        if hit["span"][0] < cursor:
            continue
        start, end = chart.trimmed(cursor, hit["span"][0])
        if start >= end:
            unhosted.append(hit)
            cursor = max(cursor, hit["span"][1])
            continue
        elements.append(ClauseElement((start, end), hit))
        cursor = hit["span"][1]
    for start_bound, end_bound in consumed:
        if cursor <= start_bound:
            cursor = end_bound
    residue = chart.trimmed(cursor, clause_span[1])
    if residue[0] >= residue[1]:
        residue = None
    return elements, residue, unhosted


def solve_region(chart, store, region_span, segment, claim_id, limits):
    """Clause drafts of one region of one segment, each with its solutions."""
    drafts = []
    actions = chart.actions_within(region_span, segment["id"])
    cursor = region_span[0]
    previous_span = None
    previous_clause_span = None
    for hit in actions:
        if hit["span"] == previous_span:
            clause_span = previous_clause_span
        else:
            clause_span = chart.trimmed(cursor, hit["span"][0])
            cursor = hit["span"][1]
            previous_span = hit["span"]
            previous_clause_span = clause_span
        draft = ClauseDraft(hit, clause_span, claim_id, segment)
        frame = store.get(hit["frame"]) if hit.get("frame") else None
        if frame is None:
            draft.notes.append("predicate_declares_no_frame")
            drafts.append(draft)
            continue
        role_map = frame.get("roles", {}).get(hit["voice"])
        if role_map is None:
            draft.notes.append("frame_has_no_role_map_for_voice")
            drafts.append(draft)
            continue
        if clause_span[0] >= clause_span[1]:
            draft.notes.append("predicate_without_arguments")
            drafts.append(draft)
            continue
        draft.solutions = _solutions(chart, store, draft, frame, role_map, limits)
        if not draft.solutions:
            draft.notes.append("no_solution_met_min_roles")
        drafts.append(draft)
    return drafts


def _inside_quote(chart, store, start, end):
    policies = store.of_kind("scope_boundary_policy")
    if not policies:
        return False
    stack = []
    for index, char in enumerate(chart.text):
        if stack and char == stack[-1][1]:
            left, _ = stack.pop()
            if left < start and end <= index:
                return True
            continue
        for opening, closing in policies[0].get("quote_pairs", ()):
            if char == opening:
                stack.append((index, closing))
                break
    return False


def _adjunct_ends(text, start, end, spec):
    """Interpret graph-declared literal and compositional character spans."""
    ends = {start + len(form) for form in spec.get("forms", ())
            if text.startswith(form, start) and start + len(form) <= end}
    for pattern in spec.get("patterns", ()):
        positions = {start}
        for part in pattern.get("parts", ()):
            following = set()
            for position in positions:
                for form in part.get("forms", ()):
                    if text.startswith(form, position) and position + len(form) <= end:
                        following.add(position + len(form))
                if part.get("character_class") == "decimal":
                    cursor = position
                    while cursor < end and text[cursor].isdecimal():
                        cursor += 1
                    if cursor > position:
                        following.add(cursor)
            positions = following
        ends.update(positions)
    return sorted(ends)


def _solutions(chart, store, draft, frame, role_map, limits):
    # A frame can reserve complete, boundary-attached construction forms before
    # ordinary marker interpretation. Partial matches inside a value do not bind.
    starts = set(chart.chunk_starts_within(draft.clause_span))
    consumed = set()
    for spec in frame.get("bound_form_roles", ()):
        for form in store.form_class(spec["form_class"]):
            pos = chart.text.find(form, draft.clause_span[0], draft.clause_span[1])
            while pos != -1:
                end = pos + len(form)
                if (pos in starts and end <= draft.clause_span[1]
                        and (end == draft.clause_span[1]
                             or chart.text[end:end + 1] in chart.boundary_forms)):
                    consumed.add((pos, end))
                pos = chart.text.find(form, pos + 1, draft.clause_span[1])
    policy = _solution_policy(store)
    markers = [hit for hit in chart.markers_within(draft.clause_span, draft.segment["id"],
                                                   attachment="closing")
               if not any(hit["span"][0] < end and start < hit["span"][1]
                          for start, end in consumed)]
    # A terminal marked element cannot be skipped without leaving an unmarked
    # residue; internal marker-shaped spans may instead remain inside a value.
    optional = []
    if policy.get("literal_marker_alternatives"):
        next_classes = set(policy.get("literal_marker_next_classes", ()))
        for index, hit in enumerate(markers[:-1]):
            following = markers[index + 1]
            later_roles = {role_map.get(name) for candidate in markers[index + 1:]
                           for name in candidate["classes"] if name in role_map}
            current_roles = {role_map.get(name) for name in hit["classes"] if name in role_map}
            if next_classes.intersection(following["classes"]) or current_roles.intersection(later_roles):
                optional.append(hit)
    cap = limits.get("max_solutions_per_segment")
    final_role = frame.get("final_unmarked_role")
    raw = []
    masks = itertools.product((False, True), repeat=len(optional))
    for mask in masks:
        literal = {hit["span"] for hit, skip in zip(optional, mask) if skip}
        elements, residue, unhosted = _elements(
            chart, draft.clause_span, draft.segment["id"], sorted(consumed), literal)
        options = []
        for element in elements:
            usable = [name for name in element.classes if name in role_map]
            alternatives = [(element, name, ()) for name in usable] or [(element, None, ())]
            for spec in store.of_kind("unmarked_adjunct"):
                start, end = element.value_span
                for split in _adjunct_ends(chart.text, start, end, spec):
                    if (split < end
                            and chart.text[split:split + 1] in chart.boundary_forms
                            and not _inside_quote(chart, store, start, end)):
                        new_start, new_end = chart.trimmed(split, end)
                        if new_start < new_end:
                            sliced = ClauseElement((new_start, new_end), element.marker_hit)
                            adjunct = {"role": spec["role"], "value_span": (start, split),
                                       "marker": None, "marker_span": None,
                                       "marker_class": None, "derivation_policy": spec["key"]}
                            alternatives.extend((sliced, name, (adjunct,)) for name in usable)
            options.append(alternatives)
        combinations = itertools.product(*options) if options else [()]
        for combination in combinations:
            if cap is not None and len(raw) >= cap:
                draft.notes.append("max_solutions_per_segment")
                break
            roles, unused = [], []
            for element, class_name, adjuncts in combination:
                roles.extend(adjuncts)
                if class_name is None:
                    unused.append({"value_span": element.value_span,
                                   "marker": element.marker_hit["marker"],
                                   "marker_span": element.marker_hit["span"],
                                   "reason": "marker_class_not_in_frame"})
                else:
                    roles.append({"role": role_map[class_name],
                                  "value_span": element.value_span,
                                  "marker": element.marker_hit["marker"],
                                  "marker_span": element.marker_hit["span"],
                                  "marker_class": class_name})
            if residue is not None:
                if final_role:
                    roles.append({"role": final_role, "value_span": residue,
                                  "marker": None, "marker_span": None,
                                  "marker_class": None})
                else:
                    unused.append({"value_span": residue, "marker": None,
                                   "marker_span": None, "reason": "unmarked_residue"})
            for hit in unhosted:
                unused.append({"value_span": hit["span"], "marker": hit["marker"],
                               "marker_span": hit["span"], "reason": "marker_without_host"})
            if len(roles) >= int(frame.get("min_roles", 0)):
                raw.append({"roles": roles, "unused": unused})
        if cap is not None and len(raw) >= cap and (literal or optional):
            # Conservatively disclose a possibly unexplored lattice branch.
            draft.notes.append("max_solutions_per_segment")
            break

    kept, dropped = _prefer(store, raw)
    draft.dropped.extend(dropped)
    return _expand_rivals(store, draft, frame, kept, limits)


def _expand_rivals(store, draft, frame, solutions, limits):
    """One reading per filler where a single-fill role has several fillers.

    A frame declares which roles may legitimately repeat.  For the rest, a
    clause that offers two fillers is ambiguous, not doubly true: asserting
    both in one reading is how an unrecognised clause boundary produced two
    actors with no uncertainty at all.  Nothing is dropped — each filler
    becomes its own reading and the others are recorded as rival bindings.
    """
    policy = _solution_policy(store)
    if not policy.get("expand_single_fill_duplicates_into_rival_readings"):
        return solutions
    multi = set(frame.get("multi_fill_roles", ()))
    cap = limits.get("max_rival_readings_per_clause")
    expanded = []
    for solution in solutions:
        groups = {}
        for item in solution["roles"]:
            groups.setdefault(item["role"], []).append(item)
        contested = sorted(name for name, items in groups.items()
                           if len(items) > 1 and name not in multi)
        if not contested:
            expanded.append(solution)
            continue
        draft.notes.append("single_fill_role_contested")
        options = [groups[name] for name in contested]
        for index, choice in enumerate(itertools.product(*options)):
            if cap is not None and index >= cap:
                draft.notes.append("max_rival_readings_per_clause")
                break
            chosen = {id(item) for item in choice}
            roles, rivals = [], []
            for item in solution["roles"]:
                if item["role"] in contested and id(item) not in chosen:
                    rivals.append({"value_span": item["value_span"],
                                   "marker": item["marker"],
                                   "marker_span": item["marker_span"],
                                   "reason": "rival_role_binding",
                                   "role": item["role"]})
                    continue
                roles.append(item)
            expanded.append({"roles": roles,
                             "unused": list(solution["unused"]) + rivals,
                             "rival_roles": contested})
    return expanded


def _prefer(store, solutions):
    """Deduplicate identical solutions while recording each removal."""
    if not solutions:
        return [], []
    policy = _solution_policy(store)
    kept, dropped = list(solutions), []

    seen, unique = set(), []
    for item in kept:
        key = _canonical(item)
        if key in seen:
            dropped.append({"reason": "duplicate_of_another_solution",
                            "policy": policy.get("key"),
                            "roles": [(role["role"], role["value_span"])
                                      for role in item["roles"]]})
            continue
        seen.add(key)
        unique.append(item)
    return unique, dropped
