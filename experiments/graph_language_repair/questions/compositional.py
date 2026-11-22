"""Character-span compiler for compositional question query graphs.

The Python layer is a generic interpreter for graph-declared WH forms,
case-to-frame mappings, and query templates. It does no tokenization, NLP,
head-name lookup, or world-fact inference. Every value and gap decision keeps
its original character span and is emitted as a graph constraint or diagnostic.
"""
from __future__ import annotations

import json
import os
from itertools import product

_GRAMMAR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "graphs", "questions",
                        "grammar", "compositional_v1.json")
_CONSTRUCTIONS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "graphs", "questions",
                              "constructions.json")


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _grammar():
    return _read(_GRAMMAR)


def _trim(text, start, end):
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _forms_with_spans(text, start, end, forms):
    """Longest-first closed morpheme scan; returned spans never overlap."""
    specs = sorted(forms, key=lambda x: -len(x["form"]))
    out, cursor = [], start
    while cursor < end:
        hit = next((spec for spec in specs
                    if text.startswith(spec["form"], cursor)
                    and cursor + len(spec["form"]) <= end), None)
        if hit:
            out.append({**hit, "span": [cursor, cursor + len(hit["form"])]})
            cursor += len(hit["form"])
        else:
            cursor += 1
    return out


def _wh_specs(grammar):
    return list(grammar.get("wh_atomic", []))


def _descriptor(text, slot, grammar):
    """Retain the complete open NP and locate its WH determiner within it."""
    for form in sorted(grammar.get("wh_determiners", []), key=len, reverse=True):
        at = text.find(form, slot["span"][0], slot["span"][1])
        if at >= 0:
            return {"span": list(slot["span"]),
                    "surface": text[slot["span"][0]:slot["span"][1]],
                    "determiner": form, "determiner_span": [at, at + len(form)],
                    "head_status": "unknown", "type_status": "unknown",
                    "referential_constraint": "unknown", "uncertainty_class": "hard"}
    return None


def _argument_slots(text, chart, segment, start, stop, grammar):
    """Build argument spans from closing markers and protected atomic WH forms."""
    segment_id = segment["id"]
    wh = _forms_with_spans(text, start, stop, _wh_specs(grammar))
    atomic_spans = [tuple(item["span"]) for item in wh]
    roots = _forms_with_spans(text, start, stop, grammar.get("wh_roots", []))
    raw_markers = [m for m in chart.marker_hits
                   if m["segment"] == segment_id and start <= m["span"][0]
                   and m["span"][1] <= stop and m.get("attachment", "closing") == "closing"]
    used_markers = set()
    for root in roots:
        a, b = root["span"]
        attached = [m for m in raw_markers if m["span"][0] == b]
        if attached:
            marker = max(attached, key=lambda m: m["span"][1] - m["span"][0])
            root["span"] = [a, marker["span"][1]]
            root["classes"] = list(marker["classes"])
            root["attached_marker_span"] = list(marker["span"])
            root["function"] = next((name for name, cls in grammar.get("case_function_classes", {}).items()
                                     if cls in marker["classes"]), root.get("function"))
            used_markers.add(tuple(marker["span"]))
        root["form"] = text[a:root["span"][1]]
        root["kind"] = "wh"
    wh.extend(roots)
    wh.sort(key=lambda item: (item["span"][0], -(item["span"][1] - item["span"][0])))
    selected_wh, wh_cursor = [], start
    for item in wh:
        if item["span"][0] >= wh_cursor:
            selected_wh.append(item)
            wh_cursor = item["span"][1]
    wh = selected_wh
    wh_spans = [tuple(item["span"]) for item in wh]
    marker_hits = [m for m in raw_markers
                   if tuple(m["span"]) not in used_markers
                   and not any(m["span"][0] < b and m["span"][1] > a for a, b in wh_spans)]
    events = [(h["span"][0], h["span"][1], "wh", h) for h in wh]
    events += [(m["span"][0], m["span"][1], "marker", m) for m in marker_hits]
    events.sort(key=lambda x: (x[0], -(x[1] - x[0]), 0 if x[2] == "wh" else 1))

    slots, residue, cursor = [], [], start
    for a, b, kind, payload in events:
        if a < cursor:
            continue
        left, right = _trim(text, cursor, a)
        if right > left:
            slots.append({"span": [left, right], "surface": text[left:right],
                          "classes": [], "kind": "unmarked"})
        if kind == "wh":
            item = {"span": [a, b], "surface": text[a:b],
                    "classes": list(payload.get("classes", [])),
                    "kind": "wh", "wh": payload}
            slots.append(item)
            cursor = b
        else:
            if right > left:
                slots[-1].update({"classes": list(payload["classes"]),
                                  "marker_span": list(payload["span"]),
                                  "kind": "marked"})
            else:
                residue.append({"span": [a, b], "surface": text[a:b],
                                "reason": "marker_without_argument"})
            cursor = b
    left, right = _trim(text, cursor, stop)
    if right > left:
        residue.append({"span": [left, right], "surface": text[left:right],
                        "reason": "unmarked_argument_or_scope"})
    for slot in slots:
        slot["descriptor"] = _descriptor(text, slot, grammar)
        if slot["descriptor"]:
            d = slot["descriptor"]
            slot["query_value"] = (text[slot["span"][0]:d["determiner_span"][0]]
                                   + text[d["determiner_span"][1]:slot["span"][1]]).strip()
        else:
            slot["query_value"] = slot["surface"]
        slot["questioned"] = slot["kind"] == "wh" or slot["descriptor"] is not None
    return slots, residue, marker_hits


def _instantiate(grammar, production, bindings):
    return [bindings.get(atom[1:], atom) if atom.startswith("$") else atom
            for atom in grammar["query_patterns"][production]]


def _scope_patterns(grammar):
    return [_instantiate(grammar, "event_claim", {}),
            _instantiate(grammar, "claim_scope", {})]


def _event_alternative(text, pred, frame, slots, choices, grammar, extra_unresolved=()):
    voice_map = frame.get("roles", {}).get(pred["voice"], {})
    patterns = [_instantiate(grammar, "event_action", {"action": pred["action"]}),
                _instantiate(grammar, "polarity", {
                    "polarity": "true" if pred["polarity"] else "false"})]
    project = []
    unresolved = list(extra_unresolved)
    variable_index = 0
    for slot_index, roles in choices:
        slot = slots[slot_index]
        if slot["questioned"]:
            variable = grammar["query_project_variables"][variable_index]
            variable_index += 1
            patterns.append(_instantiate(grammar, "requested_role", {"role": roles, "answer": variable}))
            project.append(variable)
            if slot.get("descriptor"):
                unresolved.append({"reason": "unknown_descriptor", "uncertainty_class": "hard",
                                   "confirmation": "conditional", **slot["descriptor"]})
            if slot.get("wh"):
                unresolved.append({"reason": "unknown_wh_type", "uncertainty_class": "soft",
                                   "form": slot["wh"]["form"],
                                   "type": slot["wh"].get("type", "unknown"),
                                   "type_status": "unknown", "span": slot["span"]})
        else:
            patterns.append(_instantiate(grammar, "explicit_role_value", {
                "role": roles, "value": slot["query_value"]}))
            if slot.get("descriptor"):
                unresolved.append({"reason": "unknown_explicit_descriptor",
                                   "uncertainty_class": "hard", "confirmation": "conditional",
                                   **slot["descriptor"]})
    patterns.extend(_scope_patterns(grammar))
    if not project:
        return None
    if variable_index > 2:
        return None
    if pred.get("semantic_status") == "opaque":
        unresolved.append({"reason": "unknown_predicate_meaning", "uncertainty_class": "soft",
                           "lemma": pred["lemma"], "span": pred["stem_span"]})
    return {"id": "candidate", "patterns": patterns, "project": project,
            "scope": "reading", "coverage": "partial" if unresolved else "complete",
            "type_status": "unknown" if any(x.get("reason") in
                ("unknown_descriptor", "unknown_explicit_descriptor", "unknown_wh_type",
                 "unknown_predicate_meaning") for x in unresolved) else "known",
            "unresolved": unresolved}


def _roles_for_slot(slot, voice_map):
    if slot.get("wh"):
        item = slot["wh"]
        classes = slot.get("classes") or item.get("classes") or (
            [item["case_class"]] if item.get("case_class") else [])
        mapped = sorted({voice_map[c] for c in classes if c in voice_map})
        if mapped:
            return mapped
        if item.get("role_candidates"):
            return list(item["role_candidates"])
        if item.get("role"):
            return [item["role"]]
        return []
    return sorted({voice_map[c] for c in slot.get("classes", []) if c in voice_map})


def _paired_quote_ranges(text, grammar):
    ranges = []
    for pair in grammar.get("quote_pairs", []):
        opening, closing = pair
        cursor = 0
        while True:
            start = text.find(opening, cursor)
            if start < 0:
                break
            end = text.find(closing, start + len(opening))
            if end < 0:
                ranges.append([start, len(text)])
                break
            ranges.append([start, end + len(closing)])
            cursor = end + len(closing)
    return ranges


def _inside_any(span, ranges):
    return any(a <= span[0] and span[1] <= b for a, b in ranges)


def _unconsumed(text, consumed, grammar):
    covered = list(consumed)
    stripped, _, end = _strip_terminal(text, grammar)
    question_end = end
    for form in sorted(grammar.get("question_endings", []), key=len, reverse=True):
        if stripped.endswith(form):
            covered.append((question_end - len(form), question_end))
            break
    # Punctuation is functional only at the trimmed terminal edge. Internal
    # marks remain residue (including marks inside quoted/open arguments).
    end_cursor = len(text)
    while end_cursor and text[end_cursor - 1].isspace():
        end_cursor -= 1
    closing_quotes = {pair[1] for pair in grammar.get("quote_pairs", [])}
    while end_cursor and text[end_cursor - 1] in closing_quotes:
        end_cursor -= 1
    for form in sorted(grammar.get("terminal_punctuation", []), key=len, reverse=True):
        if end_cursor >= len(form) and text.startswith(form, end_cursor - len(form)):
            covered.append((end_cursor - len(form), end_cursor))
            break
    covered.sort()
    out, cursor = [], 0
    for start, end in covered:
        if start > cursor:
            a, b = _trim(text, cursor, start)
            if b > a:
                out.append({"span": [a, b], "surface": text[a:b]})
        cursor = max(cursor, end)
    if cursor < len(text):
        a, b = _trim(text, cursor, len(text))
        if b > a:
            out.append({"span": [a, b], "surface": text[a:b]})
    return out


def _query_program(alternatives):
    return {"version": "query-graph-v1", "alternatives": alternatives}


def _projection_metadata(alternatives):
    """Keep asked-role/type/span annotations outside the native graph schema."""
    rows = []
    for alt in alternatives:
        unresolved = alt.get("unresolved", [])
        for variable in alt.get("project", []):
            role = next((p[1] for p in alt.get("patterns", [])
                         if len(p) == 3 and p[0] == "?event" and p[2] == variable), None)
            asked = next((u for u in unresolved if u.get("reason") in
                          ("unknown_descriptor", "unknown_wh_type")), {})
            rows.append({"alternative": alt.get("id"), "variable": variable,
                         "role": role, "type_status": asked.get("type_status", "unknown"),
                         "surface": asked.get("surface", asked.get("form")),
                         "span": asked.get("span"),
                         "uncertainty_class": asked.get("uncertainty_class", "soft")})
    return rows


def _strip_terminal(text, grammar):
    start, end = _trim(text, 0, len(text))
    changed = True
    forms = sorted(grammar.get("terminal_punctuation", []), key=len, reverse=True)
    while changed:
        changed = False
        for form in forms:
            if text.startswith(form, start) and start + len(form) <= end:
                start += len(form); changed = True; break
            if end - len(form) >= start and text.startswith(form, end - len(form)):
                end -= len(form); changed = True; break
    return text[start:end], start, end


def _identity_question(text, chart, store, grammar, constructions):
    """Compile identity copulas from public WH and copular construction data."""
    identity_forms = [{"form": form, "identity_value": True, "type": "unknown"}
                      for form in constructions.get("identity_wh", [])]
    ordinary_forms = [{**entry, "identity_value": False}
                      for entry in grammar.get("wh_atomic", []) + grammar.get("wh_roots", [])]
    hits = _forms_with_spans(text, 0, len(text), identity_forms + ordinary_forms)
    if not hits:
        return None
    wh = hits[-1]
    core_tail, tail_start, tail_end = _strip_terminal(text[wh["span"][1]:], grammar)
    endings = sorted(constructions.get("identity_endings", [])
                     + constructions.get("nominal_question_heads", []), key=len, reverse=True)
    ending = next((form for form in endings if core_tail.endswith(form)), None)
    request = None
    request_span = None
    if ending is None:
        for form in endings:
            at = core_tail.find(form)
            if at >= 0 and core_tail[at + len(form):].strip() in constructions.get("identity_requests", []):
                ending = form
                request = core_tail[at + len(form):].strip()
                request_span = [wh["span"][1] + at + len(form),
                                wh["span"][1] + len(core_tail)]
                core_tail = core_tail[:at + len(form)]
                break
    if ending is None:
        return None
    complement = core_tail[:-len(ending)].strip() if ending else core_tail.strip()
    segment = chart.segment_of(tuple(wh["span"]))
    if segment is None:
        return None
    identity_frame_key = grammar.get("identity_frame_key")
    frame = store.get(identity_frame_key)
    identity_action = next(record for record in store.of_kind("action")
                           if record.get("frame") == identity_frame_key)
    identity_voice = next((form["voice"] for form in identity_action.get("forms", [])
                           if form.get("voice") in frame.get("roles", {})),
                          next(iter(frame.get("roles", {}))))
    voice_map = frame.get("roles", {}).get(identity_voice, {})
    identity_value_role = frame.get("final_unmarked_role")
    subject_roles = [role for role in frame.get("expected_roles", [])
                     if role != identity_value_role]
    slots, residue, marker_hits = _argument_slots(text, chart, segment, segment["span"][0],
                                                  wh["span"][0], grammar)
    anchor = next((slot for slot in reversed(slots) if slot.get("classes")), None)
    item_roles = sorted({voice_map[c] for c in (anchor or {}).get("classes", []) if c in voice_map})
    patterns = [_instantiate(grammar, "event_action", {"action": identity_action["key"]}),
                _instantiate(grammar, "polarity", {"polarity": "true"})]
    project = grammar["query_project_variables"][:1]
    unresolved = []
    if request:
        unresolved.append({"reason": "embedded_request_scope", "request": request})
    if wh.get("identity_value"):
        unresolved.append({"reason": "unknown_wh_type", "form": wh["form"], "type": "unknown",
                           "type_status": "unknown", "span": wh["span"]})
        if item_roles:
            patterns.append(_instantiate(grammar, "explicit_role_value", {
                "role": item_roles[0], "value": anchor["surface"]}))
            patterns.append(_instantiate(grammar, "requested_role", {
                "role": identity_value_role, "answer": project[0]}))
        else:
            patterns.append(_instantiate(grammar, "requested_role", {
                "role": subject_roles[0], "answer": grammar["identity_item_variable"]}))
            patterns.append(_instantiate(grammar, "requested_role", {
                "role": identity_value_role, "answer": project[0]}))
            project = [grammar["identity_item_variable"], project[0]]
            unresolved.append({"reason": "unknown_identity_subject"})
    else:
        wh_roles = _roles_for_slot({"wh": wh}, voice_map)
        if not wh_roles:
            return None
        # A closed wh form with more than one role is kept as separate alternatives.
        identity_value = complement
        if not identity_value:
            residue.append({"span": [wh["span"][1], tail_end],
                            "surface": text[wh["span"][1]:tail_end],
                            "reason": "missing_identity_value"})
        variants = []
        if wh.get("type") is not None:
            unresolved.append({"reason": "unknown_wh_type", "form": wh["form"],
                               "type": wh.get("type", "unknown"), "type_status": "unknown",
                               "span": wh["span"]})
        for role in wh_roles:
            ps = list(patterns)
            ps.append(_instantiate(grammar, "requested_role", {"role": role, "answer": project[0]}))
            if identity_value:
                ps.append(_instantiate(grammar, "explicit_role_value", {
                    "role": identity_value_role, "value": identity_value}))
            ps.extend(_scope_patterns(grammar))
            variants.append({"id": "identity:%d" % len(variants), "patterns": ps,
                             "project": project, "scope": "reading", "coverage": "partial",
                             "type_status": "unknown", "unresolved": unresolved + residue})
        request_residue = ([{"span": request_span, "surface": text[request_span[0]:request_span[1]],
                             "reason": "embedded_request_scope"}] if request_span else [])
        return {"program": _query_program(variants), "status": "partial",
                "unconsumed": residue + request_residue, "argument_spans": slots,
                "compiler_metadata": _projection_metadata(variants),
                "diagnostics": [{"reason": "identity_question"}]}
    patterns.extend(_scope_patterns(grammar))
    for slot in slots:
        if slot is anchor:
            continue
        roles = _roles_for_slot(slot, voice_map)
        if roles:
            patterns.append(_instantiate(grammar, "explicit_role_value", {
                "role": roles[0], "value": slot["query_value"]}))
        else:
            residue.append({"span": slot["span"], "surface": slot["surface"],
                            "reason": "unmapped_identity_argument"})
    alt = {"id": "identity:0", "patterns": patterns, "project": project,
           "scope": "reading", "coverage": "partial", "type_status": "unknown",
           "unresolved": unresolved + residue}
    consumed = [tuple(wh["span"])] + [tuple(s["span"]) for s in slots]
    consumed.extend(tuple(s["marker_span"]) for s in slots if s.get("marker_span"))
    consumed.extend(tuple(m["span"]) for m in marker_hits)
    consumed.append((wh["span"][1] + tail_start, wh["span"][1] + tail_end))
    unconsumed = _unconsumed(text, consumed, grammar)
    if request_span:
        unconsumed.append({"span": request_span, "surface": text[request_span[0]:request_span[1]],
                           "reason": "embedded_request_scope"})
    return {"program": _query_program([alt]), "status": "partial",
            "unconsumed": unconsumed + residue, "argument_spans": slots,
            "compiler_metadata": _projection_metadata([alt]),
            "diagnostics": [{"reason": "identity_question"}]}


def _relative_question(text, chart, store, grammar, constructions, analyses):
    """Compile relative-clause WHs from frame gaps, never from head-noun meaning."""
    ending_forms = (constructions.get("identity_endings", [])
                    + constructions.get("nominal_question_heads", []))
    core, _, _ = _strip_terminal(text, grammar)
    if not any(core.endswith(form) for form in ending_forms):
        return None
    relatives = [p for p in analyses if p.get("mood") == "relative"]
    if not relatives:
        return None
    alternatives, diagnostics, consumed = [], [], []
    for pindex, pred in enumerate(relatives):
        segment = chart.segment_of(tuple(pred["span"]))
        if segment is None:
            continue
        frame = store.get(pred["frame"]) if pred.get("frame") else {}
        voice_map = frame.get("roles", {}).get(pred["voice"], {})
        slots, residue, marker_hits = _argument_slots(text, chart, segment,
                                                      segment["span"][0], pred["span"][0], grammar)
        explicit = []
        wh_slots = []
        occupied = set()
        for slot_index, slot in enumerate(slots):
            roles = _roles_for_slot(slot, voice_map)
            if not roles:
                residue.append({"span": slot["span"], "surface": slot["surface"],
                                "reason": "unmapped_relative_argument"})
                continue
            if slot["questioned"]:
                wh_slots.append((slot_index, roles))
            else:
                explicit.append((slot_index, roles))
                occupied.update(roles)
        tail_start = pred["span"][1]
        later_wh = _forms_with_spans(text, tail_start, len(text),
                                     [{"form": form, "identity_wh": True, "type": "unknown"}
                                      for form in constructions.get("identity_wh", [])]
                                     + _wh_specs(grammar))
        unknown_valency = False
        gaps = []
        if not wh_slots:
            # expected_roles is often a preference list, not exhaustive
            # valency. Treat the declared role mapping as the candidate space
            # unless the frame explicitly says its valency is exhaustive.
            if frame.get("valency_exhaustive") is True:
                all_roles = set(frame.get("expected_roles", ()))
            else:
                all_roles = set(voice_map.values())
                unknown_valency = True
            definite_occupied = {roles[0] for _, roles in explicit if len(roles) == 1}
            gaps = sorted(all_roles - definite_occupied)
            if not gaps:
                diagnostics.append({"reason": "relative_gap_fully_occupied",
                                    "predicate_span": pred["span"],
                                    "occupied_roles": sorted(occupied)})
                continue
            if later_wh:
                head = later_wh[0]
            else:
                head = {"form": text[pred["span"][1]:], "span": [pred["span"][1], len(text)],
                        "type": "unknown", "identity_wh": False}
            pseudo = {"span": list(head.get("span", [pred["span"][1], len(text)])),
                      "surface": head.get("form", ""), "classes": [], "kind": "wh",
                      "wh": head, "questioned": True, "query_value": ""}
            slots.append(pseudo)
            wh_slots = [(len(slots) - 1, gaps)]
        if len(wh_slots) > 2:
            diagnostics.append({"reason": "relative_projection_width", "predicate_span": pred["span"]})
            continue
        selected_slots = wh_slots + explicit
        combination_count = 1
        for _, roles in selected_slots:
            combination_count *= len(roles)
        if combination_count > grammar.get("max_role_interpretations", 32):
            diagnostics.append({"reason": "relative_role_interpretation_limit",
                                "predicate_span": pred["span"]})
            continue
        before = len(alternatives)
        for branch, picked in enumerate(product(*(roles for _, roles in selected_slots))):
            chosen = [(selected_slots[j][0], role) for j, role in enumerate(picked)]
            end_core, _, _ = _strip_terminal(text, grammar)
            head_start = pred["span"][1]
            later_start = next((item["span"][0] for item in later_wh), len(end_core))
            head_end = min(later_start, len(end_core))
            unknown = []
            if head_end > head_start:
                unknown.append({"reason": "unknown_relative_head",
                                "span": [head_start, head_end],
                                "surface": text[head_start:head_end].strip(),
                                "type_status": "unknown"})
            if unknown_valency:
                unknown.append({"reason": "relative_valency_unknown",
                                "candidate_roles": gaps, "occupied_roles": sorted(occupied)})
            alt = _event_alternative(text, pred, frame, slots, chosen, grammar, unknown + residue)
            if alt is None:
                continue
            alt["id"] = "relative:%d:%d" % (pindex, branch)
            alt["coverage"] = "partial"
            alt["type_status"] = "unknown"
            alternatives.append(alt)
        if len(alternatives) > before:
            consumed.append(tuple(pred["span"]))
            for slot in slots:
                consumed.append(tuple(slot["span"]))
                if slot.get("marker_span"):
                    consumed.append(tuple(slot["marker_span"]))
                if slot.get("wh"):
                    consumed.append(tuple(slot["span"]))
            consumed.extend(tuple(m["span"]) for m in marker_hits)
    if not alternatives and not diagnostics:
        return None
    return {"program": _query_program(alternatives), "status": "partial",
            "unconsumed": _unconsumed(text, consumed, grammar) + diagnostics,
            "argument_spans": slots if relatives else [],
            "compiler_metadata": _projection_metadata(alternatives),
            "predicate_analyses": relatives,
            "diagnostics": diagnostics or [{"reason": "relative_question"}]}


def compile_question_graph(text, store=None):
    """Compile a bounded question to native query graph plus span diagnostics."""
    from experiments.graph_language_repair.core import analyze_predicates, load_graphs
    from experiments.graph_language_repair.core.chart import Chart

    grammar = _grammar()
    constructions = _read(_CONSTRUCTIONS)
    # The native graph contract reserves every ?-prefixed atom as a variable.
    # Until typed literal transport exists, keep such surface material intact
    # as an explicit hard hold rather than allowing Chart to trim the prefix.
    prefix = grammar.get("literal_prefix_unsupported", "?")
    if prefix and prefix in text:
        trailing = len(text.rstrip())
        allowed = set()
        closers = {pair[1] for pair in grammar.get("quote_pairs", [])}
        while trailing and text[trailing - 1] in closers:
            trailing -= 1
        for punctuation in grammar.get("terminal_punctuation", []):
            if trailing >= len(punctuation) and text.startswith(punctuation, trailing - len(punctuation)):
                allowed.add(trailing - len(punctuation))
                break
        # A terminal question mark may sit immediately before its paired
        # closing quote, followed by matrix-clause text.
        for i, char in enumerate(text):
            if char in grammar.get("terminal_punctuation", []) and i + 1 < len(text) \
                    and text[i + 1] in closers:
                allowed.add(i)
        bad = [i for i, char in enumerate(text) if char == prefix and i not in allowed]
        if bad:
            return {"program": _query_program([]), "status": "unparsed",
                    "unconsumed": [{"span": [0, len(text)], "surface": text}],
                    "diagnostics": [{"reason": "unsupported_literal_atom",
                                     "uncertainty_class": "hard",
                                     "spans": [[i, i + 1] for i in bad]}]}
    store = store or load_graphs()
    chart = Chart(text, store, store.limits())
    quote_ranges = _paired_quote_ranges(text, grammar)
    analyses = analyze_predicates(text, mode="question", store=store)
    question_roots = [p for p in analyses if p["mood"] in grammar.get("question_moods", [])]
    predicates = list(question_roots)
    if question_roots:
        composing_moods = set(grammar.get("composing_moods", []))
        protected = [tuple(item["span"]) for item in _forms_with_spans(
            text, 0, len(text), _wh_specs(grammar) +
            [{"form": form} for form in grammar.get("wh_determiners", [])])]
        for root in question_roots:
            root_segment = chart.segment_of(tuple(root["span"]))
            for candidate in analyses:
                if (candidate["mood"] in composing_moods
                        and candidate["span"][1] <= root["span"][0]
                        and chart.segment_of(tuple(candidate["span"])) == root_segment
                        and not any(candidate["span"][0] < b and candidate["span"][1] > a
                                    for a, b in protected)
                        and not any(candidate["span"] == old["span"] for old in predicates)):
                    predicates.append(candidate)
    predicates.sort(key=lambda p: p["span"])

    if not predicates:
        relative = _relative_question(text, chart, store, grammar, constructions, analyses)
        if relative is not None:
            return relative
        identity = _identity_question(text, chart, store, grammar, constructions)
        if identity is not None:
            if quote_ranges:
                for alt in identity["program"]["alternatives"]:
                    alt["coverage"] = "partial"
                    alt["unresolved"].append({"reason": "unsupported_embedded_scope"})
            return identity
        request_forms = grammar.get("request_endings", [])
        request = next((form for form in sorted(request_forms, key=len, reverse=True)
                       if form in text), None)
        reason = "unsupported_request_scope" if request else "no_predicate_analysis"
        return {"program": _query_program([]), "status": "unparsed",
                "unconsumed": [{"span": [0, len(text)], "surface": text}],
                "diagnostics": [{"reason": reason}]}

    alternatives, consumed, all_slots, residue_all = [], [], [], []
    ordered_predicates = sorted(predicates, key=lambda p: p["span"])
    for index, pred in enumerate(ordered_predicates):
        segment = chart.segment_of(tuple(pred["span"]))
        if segment is None:
            residue_all.append({"span": pred["span"], "surface": pred["surface"],
                                "reason": "predicate_outside_segment"})
            continue
        prior = [p for p in ordered_predicates[:index]
                 if p["span"][1] <= pred["span"][0]
                 and chart.segment_of(tuple(p["span"])) == segment]
        region_start = max((p["span"][1] for p in prior), default=segment["span"][0])
        frame = store.get(pred["frame"]) if pred.get("frame") else {}
        voice_map = frame.get("roles", {}).get(pred["voice"], {})
        slots, residue, marker_hits = _argument_slots(text, chart, segment,
                                                      region_start, pred["span"][0], grammar)
        all_slots.extend(slots)
        residue_all.extend(residue)
        descriptors = [slot["descriptor"] for slot in slots if slot.get("descriptor")]
        choices_by_slot = []
        missing_role_slots = []
        for slot_index, slot in enumerate(slots):
            role_choices = _roles_for_slot(slot, voice_map)
            slot["candidate_roles"] = role_choices
            if not role_choices:
                missing_role_slots.append(slot)
            else:
                choices_by_slot.append((slot_index, role_choices))
        if any((not slot["questioned"] and
                slot.get("query_value", "").startswith(grammar.get("literal_prefix_unsupported", "?")))
               for slot in slots):
            residue_all.append({"span": [region_start, pred["span"][0]],
                                "surface": text[region_start:pred["span"][0]],
                                "reason": "unsupported_literal_atom"})
            continue
        if missing_role_slots:
            for slot in missing_role_slots:
                residue_all.append({"span": slot["span"], "surface": slot["surface"],
                                    "reason": "unmapped_explicit_argument"})
            # Do not emit a query which forgot an argument with no declared role.
            continue
        if not choices_by_slot:
            residue_all.append({"span": pred["span"], "surface": pred["surface"],
                                "reason": "no_role_arguments"})
            continue
        # Each question slot receives its own answer variable. Explicit non-WH
        # arguments remain constants under the selected frame/voice role.
        wh_slot_indices = [i for i, _ in choices_by_slot if slots[i]["questioned"]]
        if len(wh_slot_indices) > 2:
            residue_all.append({"span": [region_start, pred["span"][1]],
                                "surface": text[region_start:pred["span"][1]],
                                "reason": "projection_width_exceeded"})
            continue
        count = 1
        for _, role_choices in choices_by_slot:
            count *= len(role_choices)
        if count > grammar.get("max_role_interpretations", 32):
            residue_all.append({"span": [region_start, pred["span"][1]],
                                "surface": text[region_start:pred["span"][1]],
                                "reason": "role_interpretation_limit"})
            continue
        before_alternatives = len(alternatives)
        for branch, selected in enumerate(product(*(roles for _, roles in choices_by_slot))):
            choice = [(choices_by_slot[i][0], role) for i, role in enumerate(selected)]
            extra = []
            unres = []
            if len(ordered_predicates) > 1:
                unres.append({"reason": "multiple_predicates",
                              "predicate_spans": [p["span"] for p in ordered_predicates]})
            if _inside_any(tuple(pred["span"]), quote_ranges):
                unres.append({"reason": "unsupported_embedded_scope"})
            unres.extend({"reason": "unparsed_question_material", **item} for item in residue)
            alt = _event_alternative(text, pred, frame, slots, choice, grammar, unres)
            if alt is None:
                residue_all.append({"span": pred["span"], "surface": pred["surface"],
                                    "reason": "unrepresentable_projection"})
                continue
            alt["id"] = "q%d_%d" % (index, branch)
            alternatives.append(alt)
        if len(alternatives) > before_alternatives:
            consumed.append(tuple(pred["span"]))
            for slot in slots:
                consumed.append(tuple(slot["span"]))
                if slot.get("marker_span"):
                    consumed.append(tuple(slot["marker_span"]))
                if slot.get("wh"):
                    consumed.append(tuple(slot["span"]))
            consumed.extend(tuple(m["span"]) for m in marker_hits)

    unconsumed = _unconsumed(text, consumed, grammar)
    # Unsupported embedded scope and unparsed material are never silently erased.
    unconsumed.extend(residue_all)
    if unconsumed:
        for alt in alternatives:
            alt["coverage"] = "partial"
            alt["unresolved"].append({"reason": "unparsed_question_material",
                                      "spans": [item.get("span") for item in unconsumed]})
    if len(ordered_predicates) > 1:
        for alt in alternatives:
            alt["coverage"] = "partial"
            alt["unresolved"].append({"reason": "multiple_predicates"})
    if quote_ranges:
        for alt in alternatives:
            alt["coverage"] = "partial"
            if not any(x.get("reason") == "unsupported_embedded_scope" for x in alt["unresolved"]):
                alt["unresolved"].append({"reason": "unsupported_embedded_scope"})
    return {"program": _query_program(alternatives),
            "status": "partial" if unconsumed or any(a["coverage"] != "complete" for a in alternatives)
                               else ("complete" if alternatives else "unparsed"),
            "unconsumed": unconsumed, "predicate_analyses": ordered_predicates,
            "compiler_metadata": _projection_metadata(alternatives),
            "argument_spans": all_slots,
            "diagnostics": [] if alternatives else [{"reason": "no_composable_role_question"}]}
