"""Question text -> QuestionPlan.

Pure character-span matching over the explicit graph data in
``graphs/questions/markers.json``, ``cues.json`` and ``role_words.json``. No
neural, statistical or token-prediction method is used anywhere in this
module; every decision traces to a substring match or a particle-boundary
scan over Unicode code points.

A grammatical *function* (subject/object/topic/origin/destination) is not a
semantic role: the matched cue or role word decides which row predicate a
function fills (see ``plans.json``). Keeping the two separate is what lets
multiword arguments and reordered arguments both work -- the particle marks
the function regardless of where the argument sits in the sentence.
"""
import json
import os

_GRAPHS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "graphs", "questions")
_CORE_GRAPHS_DIR = os.path.join(os.path.dirname(_GRAPHS_DIR), "core")


def _load(name):
    with open(os.path.join(_GRAPHS_DIR, name), "r", encoding="utf-8") as handle:
        return json.load(handle)


def _boundary_followers():
    return tuple(_load("boundary_followers.json")["followers"])


def _core_action_event_nouns():
    """``[(action_key, [event_noun, ...]), ...]`` read from the core's own
    declared action lexicon (``graphs/core/actions.json``), read-only. The
    question side keeps no second action vocabulary: recognizing which
    action a question names reuses exactly the inventory the core uses to
    recognize it in the document, so the two can never silently diverge.
    """
    path = os.path.join(_CORE_GRAPHS_DIR, "actions.json")
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return [(record["key"], record.get("event_nouns") or []) for record in data["records"]]


def implied_actions(text):
    """Every declared action (CONTRACT.md action key) named in ``text``.

    A plain substring test against each action's declared ``event_nouns``,
    the same bare-noun forms the core itself matches on. Zero results means
    the question names an action the system has no concept of at all (e.g.
    a loan, when only "action:transfer" is declared); more than one means
    the question is ambiguous between two action concepts. Neither is
    silently resolved by the caller.
    """
    aliases = _load("cues.json").get("action_aliases", {})
    return [key for key, nouns in _core_action_event_nouns()
            if any(noun in text for noun in nouns + aliases.get(key, []))]


def _marker_forms():
    """[(form, function), ...] sorted longest-form-first so a longer particle wins."""
    data = _load("markers.json")
    forms = []
    for marker in data["markers"]:
        for form in marker["forms"]:
            forms.append((form, marker["function"]))
    forms.sort(key=lambda pair: -len(pair[0]))
    return forms


def _char_at(text, index):
    return text[index] if 0 <= index < len(text) else None


def _opaque_word_spans(text, words):
    """Every occurrence of a fixed interrogative word (who_words/role_words).

    These are indivisible lexical units, not an argument-plus-particle
    combination -- "누가" ("who") happens to end in the subject particle
    "가", but it is not "누구 + 가" for this scanner's purposes. Spans here
    are excluded from marker matching so a cue word's own tail is never
    mistaken for a second argument's case marker.
    """
    spans = []
    for word in words:
        start = 0
        while True:
            index = text.find(word, start)
            if index == -1:
                break
            spans.append((index, index + len(word)))
            start = index + 1
    return spans


def _within_opaque_span(start, end, opaque_spans):
    return any(start < span_end and end > span_start for span_start, span_end in opaque_spans)


def _opaque_span_starting_at(index, opaque_spans):
    for span_start, span_end in opaque_spans:
        if span_start == index:
            return span_end
    return None


def scan_marker_slots(text, marker_forms=None, opaque_spans=()):
    """Return ``{function: [{"text": surface, "span": [start, end]}, ...]}``.

    Scans left to right. Each marker occurrence is accepted only when the
    character immediately after it is a boundary follower (whitespace, final
    punctuation or end of string) -- a plain, stated rule, not a statistical
    one -- and when it does not fall inside an ``opaque_spans`` entry (see
    :func:`_opaque_word_spans`). The argument span runs from the end of the
    previous accepted marker (or the start of the text) to the start of this
    marker, trimmed of surrounding whitespace, so a multiword phrase crossing
    spaces is kept whole. Every occurrence of a function is kept, in order --
    a second subject-marked phrase is never dropped by keeping only the
    first; callers reading one value out of a slot must go through
    :func:`slot_value` and treat more than one occurrence as reported
    ambiguity, not a free pick. An ``opaque_spans`` region (see
    :func:`_opaque_word_spans`) is skipped as a whole: it is never itself
    captured into a neighboring argument's span, so a following marker starts
    a fresh phrase right after it rather than absorbing it.
    """
    if marker_forms is None:
        marker_forms = _marker_forms()
    boundary_followers = _boundary_followers()
    slots = {}
    cursor = 0
    i = 0
    while i < len(text):
        opaque_end = _opaque_span_starting_at(i, opaque_spans)
        if opaque_end is not None:
            cursor = opaque_end
            i = opaque_end
            continue
        matched = None
        for form, function in marker_forms:
            end = i + len(form)
            if (text[i:end] == form and _char_at(text, end) in boundary_followers
                    and not _within_opaque_span(i, end, opaque_spans)):
                matched = (form, function, end)
                break
        if matched is not None:
            form, function, end = matched
            raw_start, raw_end = cursor, i
            start = raw_start
            while start < raw_end and text[start].isspace():
                start += 1
            stop = raw_end
            while stop > start and text[stop - 1].isspace():
                stop -= 1
            if stop > start:
                slots.setdefault(function, []).append({"text": text[start:stop], "span": [start, stop]})
            cursor = end
            i = end
        else:
            i += 1
    return slots


def slot_value(slots, function):
    """Resolve one grammatical function to a single value, or report why not.

    Returns ``(text, status)`` where ``status`` is ``"ok"`` (exactly one
    occurrence), ``"missing"`` (none) or ``"ambiguous"`` (more than one --
    the question marked two spans with the same function and nothing here
    picks a winner; the caller must disclose it).
    """
    occurrences = slots.get(function) or []
    if not occurrences:
        return None, "missing"
    if len(occurrences) > 1:
        return None, "ambiguous"
    return occurrences[0]["text"], "ok"


def _find_all(text, forms):
    """Every form from ``forms`` that occurs as a substring of ``text``."""
    return [form for form in forms if form in text]


def _compile_legacy(text):
    """Compile one Korean question into a plan.

    Returns a dict with at least ``{"text", "intent", "cue_id", "slots",
    "unresolved"}``. ``slots`` maps a grammatical function to a *list* of
    occurrences (see :func:`scan_marker_slots`); nothing in this module
    collapses a multi-occurrence slot to "the first one". ``unresolved`` is
    non-empty exactly when the question cannot be represented as one of the
    declared intents, is missing an argument a recognized cue requires, has
    more than one candidate for a required argument, or names more than one
    non-equivalent asked role -- a recognized cue or role word is never
    silently answered with its target dropped or picked arbitrarily; each of
    these is reported as unresolved instead.
    """
    cues_data = _load("cues.json")
    role_words = _load("role_words.json")["role_words"]
    opaque_spans = (_opaque_word_spans(text, cues_data["who_words"])
                     + _opaque_word_spans(text, list(role_words))
                     + _opaque_word_spans(text, cues_data.get("frame_phrases", [])))
    slots = scan_marker_slots(text, opaque_spans=opaque_spans)
    # A declared relative head makes the preceding clause the event target.
    for relative in cues_data.get("relative_questions", []):
        for head in relative["head_forms"]:
            pos = text.find(head)
            if pos < 0:
                continue
            prefix = text[:pos]
            relative_slots = scan_marker_slots(prefix, opaque_spans=_opaque_word_spans(prefix, list(role_words)))
            actions = implied_actions(prefix)
            if len(actions) != 1:
                return {"text": text, "intent": None, "cue_id": None, "slots": relative_slots,
                        "unresolved": [{"reason": "ambiguous_action" if actions else "unrecognized_action", "candidates": actions}]}
            override = relative.get("action_overrides", {}).get(actions[0], {})
            return {"text": text, "intent": relative["cue_intent"], "cue_id": "relative_head",
                    "function_overrides": override.get("function_to_predicate", {}),
                    "slots": relative_slots, "asked_predicate": override.get("asked_predicate", relative["asked_predicate"]),
                    "anchor_priority": relative["anchor_priority"], "required_action": actions[0],
                    "required_voice": next((voice for voice, forms in cues_data.get("voice_forms", {}).items()
                                            if any(form in prefix for form in forms)), None), "unresolved": []}

    who_present = bool(_find_all(text, cues_data["who_words"]))

    matched_cues = []
    for cue in cues_data["cues"]:
        if not _find_all(text, cue["forms"]):
            continue
        if cue["requires_who_word"] and not who_present:
            continue
        matched_cues.append(cue)

    # A reporting verb is the outer question; other cues in its complement
    # identify the target rather than competing intents.
    reporting = [c for c in matched_cues if c["intent"] == "source_question"]
    if reporting:
        matched_cues = reporting
    if len(matched_cues) > 1:
        return {"text": text, "intent": None, "cue_id": None, "slots": slots,
                 "unresolved": [{"reason": "ambiguous_intent",
                                  "candidates": [c["id"] for c in matched_cues]}]}

    if matched_cues:
        cue = matched_cues[0]
        missing, problems = [], []
        for function in cue["requires_functions"]:
            value, status = slot_value(slots, function)
            if status == "missing":
                missing.append(function)
                problems.append({"reason": "missing_argument", "cue_id": cue["id"],
                                   "missing": [function]})
            elif status == "ambiguous":
                problems.append({"reason": "ambiguous_argument", "cue_id": cue["id"],
                                   "function": function,
                                   "candidates": [o["text"] for o in slots[function]]})

        role_query = cue.get("role_query_predicates")
        if role_query and len(missing) == 1 and len(problems) == 1:
            asked_function = missing[0]
            other_functions = [f for f in cue["requires_functions"] if f != asked_function]
            plain_target = cues_data.get("function_to_plain_predicate", {}).get(asked_function)
            asked_role_word_present = any(
                spec["asked_predicate"] == plain_target and form in text
                for form, spec in role_words.items())
            if (asked_function in role_query and plain_target and asked_role_word_present
                    and len(other_functions) == 1):
                anchor_function = other_functions[0]
                anchor_value, anchor_status = slot_value(slots, anchor_function)
                if anchor_status == "ok" and anchor_function in role_query:
                    return {"text": text, "intent": "checking_role_question",
                             "cue_id": cue["id"], "slots": slots,
                             "asked_predicate": role_query[asked_function],
                             "anchor_predicate": role_query[anchor_function],
                             "anchor_value": anchor_value, "required_action": cue.get("action"),
                             "required_voice": next((voice for voice, forms in cues_data.get("voice_forms", {}).items()
                                                     if any(form in text for form in forms)), None),
                             "unresolved": []}

        target = text
        if cue["intent"] == "source_question":
            positions = [text.find(form) for form in cue["forms"] if form in text]
            target = text[:min(positions)] if positions else text
        actions = implied_actions(target)
        # Target modalities outside the declared occurrence polarity cannot
        # be reduced to a positive or negative occurrence claim.
        if cue["intent"] in ("source_question", "occurrence_question") and any(
                form in target for form in cues_data.get("unsupported_target_forms", [])):
            problems.append({"reason": "unsupported_target_modality"})
        # Explicit complements and occurrence questions require an identified target.
        explicit_target = any(marker in target for marker in cues_data.get("target_complement_markers", [])
                              + cues_data.get("target_predicate_endings", []))
        if cue["intent"] in ("source_question", "occurrence_question") and (len(actions) > 1 or (not actions and explicit_target)):
            problems.append({"reason": "ambiguous_action" if actions else "unrecognized_action", "candidates": actions})
        return {"text": text, "intent": cue["intent"], "cue_id": cue["id"], "slots": slots,
                 "required_action": actions[0] if len(actions) == 1 else cue.get("action"),
                 "required_voice": next((voice for voice, forms in cues_data.get("voice_forms", {}).items() if any(form in target for form in forms)), None),
                 "required_polarity": ("false" if any(form in target for form in cues_data.get("negative_target_forms", [])) else "true")
                    if actions and explicit_target and cue["intent"] in ("source_question", "occurrence_question") else None,
                 "unresolved": problems}

    role_hits = [(form, role_words[form]) for form in role_words if form in text]
    if role_hits:
        predicates = {spec["asked_predicate"] for _, spec in role_hits}
        if len(predicates) > 1:
            return {"text": text, "intent": None, "cue_id": None, "slots": slots,
                     "unresolved": [{"reason": "ambiguous_role_question",
                                      "candidates": sorted(predicates)}]}
        form, spec = role_hits[0]
        actions = implied_actions(text)
        if len(actions) != 1:
            reason = "ambiguous_action" if actions else "unrecognized_action"
            return {"text": text, "intent": None, "cue_id": "role_word:%s" % form, "slots": slots,
                     "unresolved": [{"reason": reason, "candidates": actions}]}
        return {"text": text, "intent": "event_role_question", "cue_id": "role_word:%s" % form,
                 "slots": slots, "asked_predicate": spec["asked_predicate"],
                 "anchor_priority": spec["anchor_priority"], "required_action": actions[0],
                 "required_voice": next((voice for voice, forms in cues_data.get("voice_forms", {}).items() if any(form in text for form in forms)), None),
                 "unresolved": []}

    return {"text": text, "intent": None, "cue_id": None, "slots": slots,
             "unresolved": [{"reason": "no_recognized_cue"}]}


def _starts_at_boundary(text, end):
    return end == len(text) or text[end] in _boundary_followers()


def _uncovered_prefix(text, end, slots, opaque):
    covered = set()
    for start, stop in opaque:
        covered.update(range(start, min(stop, end)))
    for occurrences in slots.values():
        for occurrence in occurrences:
            start, stop = occurrence["span"]
            covered.update(range(start, min(stop, end)))
            for form, _function in _marker_forms():
                if text.startswith(form, stop) and _char_at(text, stop + len(form)) in _boundary_followers():
                    covered.update(range(stop, min(stop + len(form), end)))
                    break
    return [i for i in range(end) if i not in covered and not text[i].isspace()]


def _anaphor_spans(text, forms):
    return [(start, end) for start, end in _opaque_word_spans(text, forms)
            if not any(text.startswith(form, end) and _char_at(text, end + len(form)) in _boundary_followers()
                       for form, _function in _marker_forms())]


def _predicate_alternatives(analyses):
    """Coextensive morphological branches with the same grammatical scope."""
    if not analyses:
        return None
    signatures = {(tuple(p["span"]), p["voice"], p["polarity"], p["mood"], p["frame"]) for p in analyses}
    if len(signatures) != 1:
        return None
    return sorted({p["action"] for p in analyses})


def _action_fields(analyses):
    actions = _predicate_alternatives(analyses)
    if actions is None:
        return {}
    return {"required_action": actions[0] if len(actions) == 1 else None,
            "required_actions": actions if len(actions) > 1 else []}


def _closed_tail(text, rules):
    """Remove terminal punctuation only; other material must be accounted for."""
    return text.strip().rstrip(''.join(rules.get("terminal_punctuation", []))).rstrip()


def _identity_tail(text, role, rules):
    tail = _closed_tail(text, rules)
    for root, roles in rules.get("identity_compatibility", {}).items():
        if role not in roles:
            continue
        for copula in rules.get("identity_morphology", []):
            for mood in copula["moods"]:
                prefix = root + copula["copula"] + mood
                if tail == prefix:
                    return {"wh": root, "copula": copula["copula"],
                            "tense": copula["tense"], "mood": mood, "request": None}
                if mood in rules.get("embedded_identity_moods", []) and tail.startswith(prefix):
                    remainder = tail[len(prefix):].strip()
                    if remainder in rules.get("identity_requests", []):
                        return {"wh": root, "copula": copula["copula"],
                                "tense": copula["tense"], "mood": mood, "request": remainder}
        for ending in rules["identity_endings"]:
            prefix = root + ending
            if tail == prefix:
                return {"wh": root, "ending": ending, "request": None}
            if ending == "인지" and tail.startswith(prefix):
                remainder = tail[len(prefix):].strip()
                if remainder in rules.get("identity_requests", []):
                    return {"wh": root, "ending": ending, "request": remainder}
    return None


def _composition(text):
    """Assemble a question from graph-declared WH/head nodes and shared morphology."""
    from experiments.graph_language_repair.core import analyze_predicates
    rules = _load("constructions.json")
    analyses = analyze_predicates(text, mode="question")
    # Outer report action and inner proposition are distinct graph nodes.
    reporting = [p for p in analyses if p["mood"] == "interrogative" and p["lemma"] in rules["reporting_lemmas"]]
    targets = [p for p in analyses if p["mood"] == "complement"]
    who_spans = _opaque_word_spans(text, rules["who_forms"])
    if reporting and targets and who_spans:
        if any(p["polarity"] is not True or p["voice"] != "active" for p in reporting):
            return {"text": text, "intent": None, "cue_id": "source_composition", "slots": {},
                    "unresolved": [{"reason": "unsupported_outer_scope"}]}
        if _predicate_alternatives(targets) is None:
            return {"text": text, "intent": None, "cue_id": "source_composition", "slots": {},
                    "unresolved": [{"reason": "ambiguous_predicate"}]}
        target = targets[0]
        source_opaque = who_spans + _opaque_word_spans(text, _load("cues.json").get("frame_phrases", []))
        slots = scan_marker_slots(text[:target["span"][0]], opaque_spans=source_opaque)
        if _uncovered_prefix(text, target["span"][0], slots, source_opaque):
            return {"text": text, "intent": None, "cue_id": "source_composition", "slots": slots,
                    "unresolved": [{"reason": "unparsed_question_material"}]}
        return {"text": text, "intent": "source_question", "cue_id": "source_composition", "slots": slots,
                **_action_fields(targets), "required_voice": target["voice"],
                "required_polarity": "true" if target["polarity"] else "false",
                "function_overrides": rules["checking_functions"] if target["action"] == "action:check" else {},
                "allow_event_enumeration": True, "question_graph": {"target_predicates": targets, "report_predicates": reporting},
                "unresolved": []}
    role_hits = []
    opaque = _opaque_word_spans(text, _load("cues.json").get("frame_phrases", []))
    # A frame at the beginning includes its source noun, not just its suffix.
    if opaque and min(start for start, _ in opaque) > 0:
        first = min(opaque)
        if not any(form in text[:first[0]] for form, _ in _marker_forms()):
            opaque.append((0, first[1]))
    from experiments.graph_language_repair.core import load_graphs
    for pred in analyses:
        if pred["action"] != "action:check":
            continue
        prefix = text[:pred["span"][0]].rstrip()
        for cls in ("result_positive", "result_negative"):
            for form in load_graphs().form_class(cls):
                start = len(prefix) - len(form)
                if start >= 0 and prefix.endswith(form) and (start == 0 or prefix[start - 1].isspace()):
                    opaque.append((start, len(prefix)))
    # A longer closed interrogative excludes overlapping shorter ones.
    for entry in sorted(rules["wh_forms"], key=lambda x: -len(x["form"])):
        for start in range(len(text)):
            end = start + len(entry["form"])
            if text[start:end] != entry["form"]:
                continue
            if not _starts_at_boundary(text, end):
                ends = [end + len(marker) for marker in rules.get("wh_particle_forms", [])
                        if text.startswith(marker, end) and _starts_at_boundary(text, end + len(marker))]
                if not ends:
                    continue
                end = max(ends)
            if not _within_opaque_span(start, end, opaque):
                role_hits.append((entry["role"], [start, end], "wh"))
                opaque.append((start, end))
    # Interrogative determiner + role head + particle, each graph-declared.
    for determiner in rules.get("determiners", []):
        for start in range(len(text)):
            if text[start:start + len(determiner)] != determiner:
                continue
            hstart = start + len(determiner)
            while hstart < len(text) and text[hstart].isspace():
                hstart += 1
            for head in rules["relative_heads"]:
                end = hstart + len(head["form"])
                if text[hstart:end] != head["form"]:
                    continue
                for marker, marker_role in rules.get("head_marker_roles", {}).items():
                    mend = end + len(marker)
                    if text[end:mend] == marker and _starts_at_boundary(text, mend):
                        role = head["role"] if marker_role == "actor" else marker_role
                        role_hits.append((role, [start, mend], "determiner_head"))
                        opaque.append((start, mend))
    # Relative predicate + role head + particle + interrogative is a graph
    # construction, independent of the question-ending spelling.
    relative = []
    for pred in analyses:
        if pred["mood"] != "relative":
            continue
        suffix_start = pred["span"][1]
        while suffix_start < len(text) and text[suffix_start].isspace():
            suffix_start += 1
        for head in rules["relative_heads"]:
            end = suffix_start + len(head["form"])
            if text[suffix_start:end] != head["form"]:
                continue
            for marker in rules["head_particles"]:
                mend = end + len(marker)
                if text[end:mend] != marker or not _starts_at_boundary(text, mend):
                    continue
                remainder = text[mend:].lstrip()
                identity = _identity_tail(remainder, head["role"], rules)
                if identity:
                    relative.append((pred, head["role"], [suffix_start, mend], identity))
            for prop in rules.get("identity_property_forms", []):
                for marker in rules["head_particles"]:
                    mend = end + len(prop) + len(marker)
                    if text[end:mend] == prop + marker and not _closed_tail(text[mend:], rules):
                        relative.append((pred, head["role"], [suffix_start, mend], {"property": prop}))
    if relative:
        if (len({role for _, role, _, _ in relative}) != 1 or
                _predicate_alternatives([p for p, _, _, _ in relative]) is None):
            return {"text": text, "intent": None, "cue_id": "composition", "slots": {},
                    "unresolved": [{"reason": "ambiguous_predicate"}]}
        pred, role, head_span, identity = relative[0]
        slots = scan_marker_slots(text[:pred["span"][0]], opaque_spans=opaque)
        chosen = [p for p, _, _, _ in relative]
        role_hits = [(role, head_span, "relative_head")]
        gap_policy = rules.get("relative_gap_policy", {})
        occupied_map = gap_policy.get("occupied_functions", {}).get(pred["voice"], {})
        occupied = {r for function, values in slots.items() if values
                    for r in occupied_map.get(function, [])}
        candidates = set(gap_policy.get("candidate_roles", {}).get(role, [role])) - occupied
        voice_default = gap_policy.get("voice_head_defaults", {}).get(pred["voice"], {}).get(role, role)
        # A head's lexical type is not evidence that an already filled role
        # is the gap, nor that an alternative argument has that type. Keep
        # the competing roles and the complete parsed clause on a hold.
        gap = {"head_role": role, "occupied_roles": sorted(occupied),
               "candidate_roles": sorted(candidates), "voice_default": voice_default}
        if len(candidates) != 1 or voice_default not in candidates or voice_default != role:
            return {"text": text, "intent": None, "cue_id": "composition", "slots": slots,
                    "question_graph": {"predicate_analyses": chosen, "identity": identity,
                                       "relative_gap": gap,
                                       "wh": [{"role": role, "span": head_span, "construction": "relative_head"}]},
                    "unresolved": [{"reason": "unresolved_relative_gap", **gap}]}
    else:
        if not role_hits:
            interrogatives = [p for p in analyses if p["mood"] == "interrogative"]
            if _predicate_alternatives(interrogatives) is None:
                return None
            pred = interrogatives[0]
            prefix_opaque = opaque + _anaphor_spans(text, rules["anaphors"])
            slots = scan_marker_slots(text[:pred["span"][0]], opaque_spans=prefix_opaque)
            if _uncovered_prefix(text, pred["span"][0], slots, prefix_opaque):
                return {"text": text, "intent": None, "cue_id": "composition", "slots": slots,
                        "unresolved": [{"reason": "unparsed_question_material"}]}
            return {"text": text, "intent": "proposition_question", "cue_id": "composition",
                    "slots": slots, **_action_fields(interrogatives), "required_voice": pred["voice"],
                    "function_overrides": rules["checking_functions"] if pred["action"] == "action:check" else {},
                    "allow_event_enumeration": True, "requires_unique_event": False,
                    "question_graph": {"predicate_analyses": interrogatives}, "unresolved": []}
        roles = {entry[0] for entry in role_hits}
        if len(roles) != 1:
            return None  # legacy gives the established ambiguity disclosure
        chosen = [p for p in analyses if p["mood"] == "interrogative"]
        # A relative predicate can also close a direct WH question through a
        # nominalized copula. Require the whole remaining tail to be licensed.
        nominal = [p for p in analyses if p["mood"] == "relative" and
                   _closed_tail(text[p["span"][1]:], rules) in rules.get("nominal_question_heads", [])]
        if not chosen and nominal:
            chosen = nominal
        if not chosen and any(p["mood"] == "relative" for p in analyses):
            return {"text": text, "intent": None, "cue_id": "composition", "slots": {},
                    "question_graph": {"predicate_analyses": analyses},
                    "unresolved": [{"reason": "unsupported_predicate_scope"}]}
        if chosen and _predicate_alternatives(chosen) is None:
            return {"text": text, "intent": None, "cue_id": "composition", "slots": {},
                    "unresolved": [{"reason": "ambiguous_predicate"}]}
        cut = chosen[0]["span"][0] if chosen else len(text)
        slots = scan_marker_slots(text[:cut], opaque_spans=opaque + _anaphor_spans(text, rules["anaphors"]))
        role = role_hits[0][0]
    if not chosen and not slots and not any(x in text for x in rules["anaphors"]):
        return None
    if not chosen:
        end = len(text.rstrip())
        while end and text[end - 1] in rules.get("terminal_punctuation", []):
            end -= 1
        if _uncovered_prefix(text, end, slots, opaque + _anaphor_spans(text, rules["anaphors"])):
            return {"text": text, "intent": None, "cue_id": "composition", "slots": slots,
                    "unresolved": [{"reason": "unparsed_question_material"}]}
    pred = chosen[0] if chosen else None
    if pred and _uncovered_prefix(text, pred["span"][0], slots, opaque):
        return {"text": text, "intent": None, "cue_id": "composition", "slots": slots,
                "unresolved": [{"reason": "unparsed_question_material"}]}
    action = pred["action"] if pred else None
    if (role == "grammatical_subject" and pred and
            (pred["voice"] != "active" or any(text[s[0]:s[1]] in rules.get("active_subject_role_forms", [])
                                              for _, s, _ in role_hits))):
        role = rules.get("declared_subject_roles", {}).get(pred["voice"], role)
    checking = action == "action:check"
    mapped_role = rules["checking_roles"].get(role, role) if checking else role
    return {"text": text, "intent": "checking_role_question" if checking else "event_role_question",
            "cue_id": "composition", "slots": slots, "asked_predicate": mapped_role,
            "anchor_priority": rules["anchor_priority"],
            "function_overrides": rules["checking_functions"] if checking else {},
            **(_action_fields(chosen) if chosen else {"required_action": None}), "required_voice": pred["voice"] if pred else None,
            "required_polarity": ("true" if pred["polarity"] else "false") if pred else None,
            "allow_event_enumeration": True, "requires_unique_event": pred is None,
            "question_graph": {"wh": [{"role": r, "span": span, "construction": kind} for r, span, kind in role_hits],
                               "predicate_analyses": chosen,
                               **({"relative_gap": gap} if relative else {}),
                               **({"nominal_wrapper": _closed_tail(text[pred["span"][1]:], rules)}
                                  if pred and pred["mood"] == "relative" and not relative else {}),
                               **({"identity": identity} if relative else {})},
            "unresolved": ([{"reason": "unsupported_identity_property", "property": identity["property"]}]
                           if relative and "property" in identity else [])}


def _compile_question(text):
    """Build a question graph from shared predicate morphology and WH constructions."""
    # Existing source and checking-outcome scope constructions have distinct
    # semantics and remain in charge until their compositional graph matches.
    legacy = _compile_legacy(text)
    composed = _composition(text)
    if composed and (composed.get("question_graph", {}).get("identity") or
                     composed.get("question_graph", {}).get("nominal_wrapper")):
        return composed
    if legacy.get("intent") in ("source_question", "occurrence_question"):
        from experiments.graph_language_repair.core import analyze_predicates
        targets = [p for p in analyze_predicates(text, mode="question") if p["mood"] == "complement"]
        unique = {(p["action"], p["voice"], p["polarity"]) for p in targets}
        if targets and _predicate_alternatives(targets) is not None:
            target = targets[0]
            legacy.update(_action_fields(targets))
            legacy["required_voice"] = target["voice"]
            legacy["required_polarity"] = "true" if target["polarity"] else "false"
            legacy["question_graph"] = {"predicate_analyses": targets}
            legacy["unresolved"] = [issue for issue in legacy["unresolved"]
                                    if issue.get("reason") != "unrecognized_action"]
        elif len(unique) > 1:
            legacy["unresolved"].append({"reason": "ambiguous_predicate"})
    if legacy.get("intent") == "verification_question":
        from experiments.graph_language_repair.core import analyze_predicates, load_graphs
        predicates = [p for p in analyze_predicates(text, mode="question") if p["action"] == "action:check"]
        if len(predicates) == 1:
            end = predicates[0]["span"][0]
            prefix = text[:end].rstrip()
            found = [(value, form) for cls, value in (("result_positive", "confirmed"), ("result_negative", "denied"))
                     for form in load_graphs().form_class(cls)
                     if prefix.endswith(form) and (len(prefix) == len(form) or prefix[-len(form)-1].isspace())]
            values = {value for value, _ in found}
            if len(values) == 1:
                legacy["required_result"] = next(iter(values))
            elif len(values) > 1:
                legacy["unresolved"].append({"reason": "ambiguous_result"})
    if legacy.get("intent") in ("source_question", "occurrence_question", "verification_question"):
        composed = _composition(text)
        if composed and (composed.get("cue_id") == "source_composition" or
                         (legacy.get("intent") == "verification_question" and
                          any(item.get("reason") == "unparsed_question_material" for item in composed.get("unresolved", [])))):
            return composed
        return legacy
    if legacy.get("intent") and not legacy.get("unresolved"):
        candidate = _composition(text)
        if candidate and any(item.get("reason") == "unparsed_question_material" for item in candidate.get("unresolved", [])):
            return candidate
        if candidate and candidate.get("required_actions"):
            return candidate
        if candidate and candidate.get("required_action"):
            if (candidate.get("question_voice", candidate.get("required_voice")) == "passive" and
                    any(item.get("role") == "grammatical_subject" for item in candidate.get("question_graph", {}).get("wh", [])) and
                    candidate.get("asked_predicate") != legacy.get("asked_predicate")):
                return candidate
            if legacy.get("required_action") != candidate.get("required_action"):
                return candidate
            if candidate.get("required_polarity"):
                legacy["required_polarity"] = candidate["required_polarity"]
                legacy["question_graph"] = candidate["question_graph"]
        return legacy
    if any(item.get("reason") == "ambiguous_role_question"
           for item in legacy.get("unresolved", [])):
        return legacy
    composed = _composition(text)
    if any(item.get("reason") == "ambiguous_action" for item in legacy.get("unresolved", [])) and (
            not composed or composed.get("unresolved")):
        return legacy
    return composed if composed is not None else legacy


def compile_question(text):
    """Compile grammatical voice into semantic role constraints."""
    plan = _compile_question(text)
    rules = _load("constructions.json")
    if plan.get("intent") == "occurrence_question":
        from experiments.graph_language_repair.core import analyze_predicates
        relative = [p for p in analyze_predicates(text, mode="question") if p["mood"] == "relative"]
        targets = []
        for pred in relative:
            rest = text[pred["span"][1]:].lstrip()
            if any(rest.startswith(head + marker) for head in rules.get("event_heads", [])
                   for marker in rules.get("head_particles", [])):
                targets.append(pred)
        if targets and _predicate_alternatives(targets) is not None:
            target = targets[0]
            prefix = text[:target["span"][0]]
            opaque = _opaque_word_spans(prefix, _load("cues.json").get("frame_phrases", []))
            slots = scan_marker_slots(prefix, opaque_spans=opaque)
            if not _uncovered_prefix(text, target["span"][0], slots, opaque):
                plan["slots"] = slots
                plan.update(_action_fields(targets))
                plan["required_voice"] = target["voice"]
                plan["required_polarity"] = "true" if target["polarity"] else "false"
                plan["question_graph"] = {"predicate_analyses": targets}
                plan["unresolved"] = [issue for issue in plan.get("unresolved", [])
                                      if issue.get("reason") not in ("unrecognized_action", "ambiguous_action")]
    if (plan.get("intent") == "verification_question" and
            any(form in text for form in rules.get("checking_occurrence_goal_forms", []))):
        from experiments.graph_language_repair.core import analyze_predicates
        checks = [p for p in analyze_predicates(text, mode="question")
                  if p["action"] == "action:check" and p["mood"] == "relative"]
        if len(checks) == 1:
            pred = checks[0]
            between = text[pred["span"][1]:].lstrip()
            if any(between.startswith(form) for form in rules["checking_occurrence_goal_forms"]):
                plan["slots"] = scan_marker_slots(text[:pred["span"][0]],
                    opaque_spans=_opaque_word_spans(text, _load("cues.json").get("frame_phrases", [])))
                problems = []
                for function in ("subject", "object"):
                    _, status = slot_value(plan["slots"], function)
                    if status != "ok":
                        problems.append({"reason": "missing_argument" if status == "missing" else "ambiguous_argument",
                                         "cue_id": plan["cue_id"], "missing": [function], "function": function,
                                         "candidates": [x["text"] for x in plan["slots"].get(function, [])]})
                plan["unresolved"] = problems
                plan["goal"] = "checking_occurrence"
                plan["asked_relation"] = "checking_occurred"
                plan["question_graph"] = {"predicate_analyses": checks}
    voice = plan.get("required_voice")
    if voice:
        rules = _load("constructions.json")
        checking = (plan.get("intent") in ("checking_role_question", "verification_question") or
                    plan.get("required_action") == "action:check")
        table = "checking_voice_function_overrides" if checking else "voice_function_overrides"
        override = rules.get(table, {}).get(voice, {})
        plan["function_overrides"] = {**plan.get("function_overrides", {}), **override}
        if plan.get("anchor_value"):
            for function, predicate in override.items():
                if slot_value(plan.get("slots", {}), function)[0] == plan["anchor_value"]:
                    plan["anchor_predicate"] = predicate
        # Voice identifies the question's construction; it does not demand
        # that an equivalent event in the document use the same voice.
        plan["question_voice"] = voice
    policy = rules.get("role_answer_scope", {})
    if plan.get("intent") in policy.get("intents", []):
        graph = plan.get("question_graph") or {}
        identity = graph.get("identity") or {}
        forms = [identity.get("wh", "")]
        for item in graph.get("wh", []):
            span = item.get("span") or []
            if len(span) == 2:
                forms.append(text[span[0]:span[1]])
        cue = plan.get("cue_id") or ""
        if cue.startswith("role_word:"):
            forms.append(cue.split(":", 1)[1])
        if plan.get("intent") == "source_question":
            forms.extend(form for form in policy.get("source_type_forms", []) if form in text)
        requested = policy.get("default_requested_type")
        for form in forms:
            for prefix, kind in policy.get("type_by_prefix", {}).items():
                if form.startswith(prefix):
                    requested = kind
                    break
            if requested != policy.get("default_requested_type"):
                break
        plan.update(answer_scope=policy.get("answer_scope"), requested_type=requested,
                    type_verification=policy.get("type_verification"))
    return plan
