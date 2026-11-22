# -*- coding: utf-8 -*-
"""Graph-declared character-span predicate composition, shared with questions."""
from experiments.graph_language_repair.core.graph_store import load_graphs


def analyze_predicates(text, mode="document", store=None):
    """Return composed predicate analyses with exact spans and derivation.

    Observed identities encode the exact lexical stem; they assert no synonymy.
    The span scan uses declared character boundaries and finite ending rules.
    """
    if mode not in ("document", "question"):
        raise ValueError("unknown analysis mode")
    store = store or load_graphs()
    cap = store.limits().get("max_text_chars")
    if cap is not None and len(text) > cap:
        raise ValueError("text exceeds predicate analysis limit")
    boundaries = tuple(store.mark_forms("boundary_after_marker"))
    enders = tuple(store.mark_forms("segment_ender"))
    separators = set(boundaries + enders)
    report_starts = {form for record in store.of_kind("report_frame")
                     for form in record.get("forms", ())}
    marker_forms = [(form, record) for record in store.of_kind("marker")
                    if record.get("attachment", "closing") == "closing"
                    for form in record.get("forms", ())]
    results = []
    for grammar in store.of_kind("morphology"):
        known = {}
        for record in store.of_kind("action"):
            for stem in record.get(grammar.get("known_stem_field"), ()):
                known.setdefault(stem, []).append(record)
        for ending in grammar.get("endings", ()):
            if mode == "document" and ending["mood"] != "declarative":
                continue
            form = ending["form"]
            index = text.find(form)
            while index >= 0:
                end = index + len(form)
                follows = (end == len(text) or text[end:end + 1] in separators
                           or any(text.startswith(x, end) for x in report_starts))
                start = index
                while start > 0 and text[start - 1:start] not in separators:
                    start -= 1
                stem = text[start:index]
                valid = (follows and grammar.get("min_stem_chars", 1) <= len(stem)
                         <= grammar.get("max_stem_chars", 24)
                         and all(ch.isalpha() for ch in stem))
                if valid and mode == "document":
                    left = start
                    while left > 0 and text[left - 1:left] not in enders:
                        left -= 1
                    # A marker must close an earlier, nonempty value in this clause.
                    valid = any(pos > left and pos + len(marker) <= start
                                and text.startswith(marker, pos)
                                and (pos + len(marker) == len(text)
                                     or text[pos + len(marker):pos + len(marker) + 1] in separators)
                                for pos in range(left, start) for marker, _ in marker_forms)
                if valid:
                    options = known.get(stem, ())
                    declared = options[0] if len(options) == 1 else None
                    action = (declared["key"] if declared else
                              grammar["action_prefix"] + stem.encode("utf-8").hex())
                    results.append({"span": [start, end], "stem_span": [start, index],
                                    "ending_span": [index, end], "surface": text[start:end],
                                    "lemma": stem, "action": action,
                                    "frame": declared["frame"] if declared else grammar["frame"],
                                    "voice": ending["voice"], "polarity": ending["polarity"],
                                    "mood": ending["mood"],
                                    "semantic_status": "declared" if declared else "opaque",
                                    "derivation": {"grammar": grammar["key"],
                                                   "ending": form,
                                                   "known_stem": bool(declared)}})
                index = text.find(form, index + 1)
    for grammar in store.of_kind("morphology_jamo"):
        known, incompatible = {}, set()
        for record in store.of_kind("action"):
            for form in record.get(grammar.get("known_form_field"), ()):
                for item in _regular_raw(form["surface"], grammar, separators, (), "document", anchored=False):
                    if item["span"] != [0, len(form["surface"])]:
                        continue
                    if (form.get("voice", "active") == item["voice"]
                            and bool(form.get("polarity", True)) == item["polarity"]):
                        known.setdefault(item["lemma"], set()).add(record["key"])
                    else:
                        incompatible.add(item["lemma"])
        for item in _regular_raw(text, grammar, separators, report_starts, mode):
            start = item["span"][0]
            if mode == "document":
                left = start
                while left > 0 and text[left - 1:left] not in enders:
                    left -= 1
                if not any(pos > left and pos + len(marker) <= start
                           and text.startswith(marker, pos)
                           and (pos + len(marker) == len(text)
                                or text[pos + len(marker):pos + len(marker) + 1] in separators)
                           for pos in range(left, start) for marker, _ in marker_forms):
                    continue
            if any(old["span"] == item["span"] and old["derivation"]["grammar"]
                   in {record["key"] for record in store.of_kind("morphology")} for old in results):
                continue
            candidates = known.get(item["lemma"], set())
            if not candidates and item["lemma"] in incompatible:
                continue
            action = next(iter(candidates)) if len(candidates) == 1 else None
            item["action"] = action or grammar["action_prefix"] + item["lemma"].encode("utf-8").hex()
            item["frame"] = store.get(action)["frame"] if action else grammar["frame"]
            item["semantic_status"] = "declared" if action else "opaque"
            item["derivation"]["known_stem"] = bool(action)
            results.append(item)
    # Longer ending analyses subsume shorter suffix analyses for the same stem.
    kept = []
    for item in sorted(results, key=lambda x: (-(x["span"][1] - x["span"][0]), x["span"][0], x["action"])):
        if any(other["span"][0] <= item["span"][0] and other["span"][1] >= item["span"][1]
               and other["span"] != item["span"] for other in kept):
            continue
        if item not in kept:
            kept.append(item)
    return sorted(kept, key=lambda item: (item["span"][0], item["span"][1], item["action"]))


def _regular_raw(text, grammar, separators, report_starts, mode, anchored=True):
    """Mechanically invert only graph-declared ending and syllable rules."""
    import unicodedata

    def boundary(end):
        return end == len(text) or text[end:end + 1] in separators or any(
            text.startswith(form, end) for form in report_starts)

    def relative_head(end):
        while end < len(text) and text[end:end + 1] in separators:
            end += 1
        return any(text.startswith(form, end) for form in grammar.get("relative_heads", ()))

    def start_of(index):
        while index > 0 and text[index - 1:index] not in separators:
            index -= 1
        return index

    def emit(start, stem_end, end, lemma, rule, ending_start=None):
        if not grammar.get("min_stem_chars", 1) <= len(lemma) <= grammar.get("max_stem_chars", 24):
            return None
        if not all(ch.isalpha() for ch in lemma):
            return None
        if mode == "document" and rule["mood"] != "declarative":
            return None
        if rule["mood"] == "relative" and anchored and not relative_head(end):
            return None
        if not boundary(end):
            return None
        return {"span": [start, end], "stem_span": [start, stem_end],
                "ending_span": [ending_start if ending_start is not None else stem_end, end],
                "surface": text[start:end], "lemma": lemma,
                "voice": rule.get("voice", "active"), "polarity": rule.get("polarity", True),
                "mood": rule["mood"], "derivation": {"grammar": grammar["key"],
                "ending": rule["form"], "inversion": rule.get("inversion", "identity")}}

    results = []
    for rule in grammar.get("endings", ()):
        form = rule["form"]
        index = text.find(form)
        while index >= 0:
            start = start_of(index)
            lemma = text[start:index]
            if lemma and rule.get("requires_coda"):
                parts = unicodedata.normalize("NFD", lemma[-1])
                if len(parts) != 3:
                    index = text.find(form, index + 1)
                    continue
            item = emit(start, index, index + len(form), lemma, rule)
            if item:
                results.append(item)
            index = text.find(form, index + 1)
    for rule in grammar.get("contracted_past_endings", ()):
        index = text.find(rule["form"])
        while index >= 0:
            start = start_of(index)
            if index > start:
                parts = unicodedata.normalize("NFD", text[index - 1])
                if len(parts) == 3 and parts[2] == grammar["past_coda"]:
                    for mapping in grammar.get("vowel_rewrites", ()):
                        if parts[1] != mapping["surface"]:
                            continue
                        for vowel in mapping.get("stems", ()):
                            restored = unicodedata.normalize("NFC", parts[0] + vowel)
                            lemma = text[start:index - 1] + restored
                            spec = dict(rule, polarity=True, voice="active", inversion="vowel_coda")
                            item = emit(start, index, index + len(rule["form"]), lemma,
                                        spec, ending_start=index - 1)
                            if item:
                                results.append(item)
            index = text.find(rule["form"], index + 1)
    if mode == "question":
        for index, character in enumerate(text):
            parts = unicodedata.normalize("NFD", character)
            if len(parts) != 3 or parts[2] != grammar["contracted_relative_coda"]:
                continue
            start = start_of(index)
            lemma = text[start:index] + unicodedata.normalize("NFC", parts[0] + parts[1])
            spec = {"form": grammar["contracted_relative_coda"], "mood": "relative",
                    "polarity": True, "voice": "active", "inversion": "coda"}
            item = emit(start, index + 1, index + 1, lemma, spec, ending_start=index)
            if item:
                results.append(item)
    return results
