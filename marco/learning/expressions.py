"""Supervised expression proposals gated by separate semantic validation cases.

Validation labels never participate in template induction. These finite checks
demonstrate bounded transfer, not truth or general language understanding.
"""
import copy


def from_paraphrase(parser, text, equivalent, *, inherit_declared_slots=True, expression_kind="fact"):
    """Ground a user-declared equivalence in a single already parsed fact.

    Subject/object strings must occur exactly once in the new wording. Their
    roles come from the reference, never their order in the new sentence.
    """
    def _strict_int(value):
        return isinstance(value, int) and not isinstance(value, bool)

    def _selected_example(parser, parsed, reference):
        """Return the one native example selected for fact 0, else raise."""
        if not isinstance(parsed, dict):
            raise ValueError("entry_selection_unavailable")
        selection = parsed.get("entry_selection")
        if not isinstance(selection, dict):
            raise ValueError("entry_selection_unavailable")
        if selection.get("schema") != "marco-entry-selection-v1":
            raise ValueError("entry_selection_malformed")
        if selection.get("scope") != "known_selected_input_clauses":
            raise ValueError("entry_selection_malformed")
        if selection.get("coordinate_space") != "parser_view":
            raise ValueError("entry_selection_malformed")
        items = selection.get("items")
        if not isinstance(items, list):
            raise ValueError("entry_selection_malformed")
        matches = []
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("entry_selection_malformed")
            targets = item.get("targets")
            if not isinstance(targets, dict):
                raise ValueError("entry_selection_malformed")
            facts = targets.get("facts")
            query = targets.get("query")
            if not isinstance(facts, list) or not isinstance(query, list):
                raise ValueError("entry_selection_malformed")
            if query:
                continue
            if len(facts) != 1 or not _strict_int(facts[0]) or facts[0] != 0:
                continue
            matches.append(item)
        if len(matches) != 1:
            raise ValueError("entry_selection_requires_one_fact_item")
        index = matches[0].get("compiler_index")
        if not _strict_int(index):
            raise ValueError("entry_selection_index_invalid")
        data = getattr(parser, "data", None)
        examples = data.get("examples") if isinstance(data, dict) else None
        templates = getattr(parser, "templates", None)
        if not isinstance(examples, list) or templates is None:
            raise ValueError("entry_selection_unavailable")
        try:
            template_count = len(templates)
        except TypeError:
            raise ValueError("entry_selection_unavailable")
        if len(examples) != template_count:
            raise ValueError("entry_selection_unavailable")
        if not 0 <= index < len(examples) or not 0 <= index < template_count:
            raise ValueError("entry_selection_index_out_of_range")
        example = examples[index]
        if not isinstance(example, dict):
            raise ValueError("entry_selection_example_malformed")
        return example

    def _declared_word_slots(example, fact):
        """Map the selected example's word_slots onto subject/object roles."""
        if "word_slots" not in example:
            return None
        word_slots = example["word_slots"]
        if word_slots == []:
            return None
        if not isinstance(word_slots, list) or not word_slots:
            raise ValueError("word_slots_invalid")
        declared = example.get("slots")
        if not isinstance(declared, dict):
            raise ValueError("word_slots_requires_declared_slots")
        seen = set()
        for name in word_slots:
            if not isinstance(name, str) or not name or name in seen:
                raise ValueError("word_slots_invalid")
            if name not in declared:
                raise ValueError("word_slots_undeclared")
            seen.add(name)
        meaning = example.get("meaning")
        triple = meaning.get("triple") if isinstance(meaning, dict) else None
        if not isinstance(triple, list) or len(triple) != 3:
            raise ValueError("word_slots_requires_flat_triple")
        roles = {}
        for position, role in ((0, "subject"), (2, "object")):
            ref = triple[position]
            if not isinstance(ref, str) or not ref.startswith("$") or len(ref) < 2:
                raise ValueError("word_slots_requires_slot_references")
            slot_name = ref[1:]
            if slot_name not in declared or slot_name in roles:
                raise ValueError("word_slots_requires_slot_references")
            roles[slot_name] = role
        relation = triple[1]
        if not isinstance(relation, str) or relation != fact["triple"][1]:
            raise ValueError("word_slots_relation_mismatch")
        for name in word_slots:
            if name not in roles:
                raise ValueError("word_slots_not_binary_role")
        ordered = []
        for slot_name, role in roles.items():
            if slot_name in seen:
                ordered.append(role)
        ordered.sort(key=("subject", "object").index)
        return ordered

    def _query_annotation():
        """Ground the one selected query example in the reference's known entity."""
        from relational_semantics import substitute
        parsed = parser.parse(equivalent, partial=True, _entry_selection=True)
        if not isinstance(parsed, dict):
            raise ValueError("equivalent_requires_one_known_query")
        # Native advanced semantic fields (engine API vocabulary, not language
        # knowledge). Empty None/[]/{}/"" keeps its empty meaning; anything else
        # is an advanced record the generic facts/query carrier cannot hold.
        for key in ("definitions", "events", "condition", "assumption", "reason",
                    "correction", "repair",
                    "정의", "사건", "가정사건", "조건", "가정", "원인", "이유물음", "수선", "사건정정"):
            if key in parsed and parsed[key] not in (None, [], {}, ""):
                raise ValueError("equivalent_requires_one_known_query")
        query = parsed.get("query") or []
        if parsed.get("facts") or not isinstance(query, list) or len(query) != 1:
            raise ValueError("equivalent_requires_one_known_query")
        selection = parsed.get("entry_selection")
        if not isinstance(selection, dict):
            raise ValueError("entry_selection_unavailable")
        if (selection.get("schema") != "marco-entry-selection-v1"
                or selection.get("scope") != "known_selected_input_clauses"
                or selection.get("status") != "partial"
                or selection.get("coordinate_space") != "parser_view"
                or not isinstance(selection.get("items"), list)
                or not isinstance(selection.get("gaps"), list)):
            raise ValueError("entry_selection_malformed")
        # Passive provenance gaps are honest incomplete origin metadata; any
        # other gap is a blocked reader/alignment/derivation and is rejection.
        passive_gaps = ("origin_unavailable", "origin_unknown", "binding_unknown",
                        "origin_invalid", "origin_alignment_invalid", "origin_index_unavailable")
        for gap in selection["gaps"]:
            if (not isinstance(gap, dict) or not _strict_int(gap.get("clause_ordinal"))
                    or not isinstance(gap.get("code"), str)):
                raise ValueError("entry_selection_malformed")
            if gap["code"] not in passive_gaps:
                raise ValueError("entry_selection_blocked")
        items = selection["items"]
        if len(items) != 1 or not isinstance(items[0], dict):
            raise ValueError("entry_selection_requires_one_query_item")
        if not _strict_int(items[0].get("clause_ordinal")) or items[0]["clause_ordinal"] != 0:
            raise ValueError("entry_selection_malformed")
        span = items[0].get("span")
        if (not isinstance(span, list) or len(span) != 2 or not all(_strict_int(x) for x in span)
                or not 0 <= span[0] < span[1] <= len(equivalent)):
            raise ValueError("entry_selection_span_invalid")
        if items[0].get("derivation", None) is not None:
            raise ValueError("entry_selection_derived_rejected")
        targets = items[0].get("targets")
        if not isinstance(targets, dict):
            raise ValueError("entry_selection_malformed")
        facts, query_targets = targets.get("facts"), targets.get("query")
        if (facts != [] or not isinstance(query_targets, list) or len(query_targets) != 1
                or not _strict_int(query_targets[0]) or query_targets[0] != 0):
            raise ValueError("entry_selection_requires_one_query_item")
        index = items[0].get("compiler_index")
        if not _strict_int(index):
            raise ValueError("entry_selection_index_invalid")
        data = getattr(parser, "data", None)
        examples = data.get("examples") if isinstance(data, dict) else None
        templates = getattr(parser, "templates", None)
        if not isinstance(examples, list) or templates is None:
            raise ValueError("entry_selection_unavailable")
        try:
            template_count = len(templates)
        except TypeError:
            raise ValueError("entry_selection_unavailable")
        if len(examples) != template_count:
            raise ValueError("entry_selection_unavailable")
        if not 0 <= index < len(examples):
            raise ValueError("entry_selection_index_out_of_range")
        example = examples[index]
        if not isinstance(example, dict):
            raise ValueError("entry_selection_example_malformed")
        declared = example.get("slots")
        meaning = example.get("meaning")
        if not isinstance(declared, dict) or len(declared) != 1:
            raise ValueError("query_requires_one_known_slot")
        known = next(iter(declared))
        if not isinstance(known, str) or not known:
            raise ValueError("query_requires_one_known_slot")
        if not isinstance(meaning, dict) or set(meaning) != {"query"}:
            raise ValueError("query_requires_selected_query_meaning")
        records = meaning["query"]
        if not isinstance(records, list) or len(records) != 1 or not isinstance(records[0], dict) \
                or set(records[0]) != {"triple", "render"}:
            raise ValueError("query_requires_selected_query_meaning")
        triple, render = records[0]["triple"], records[0]["render"]
        if (not isinstance(triple, list) or len(triple) != 3
                or any(not isinstance(x, str) or not x for x in triple)):
            raise ValueError("query_requires_selected_query_meaning")
        if (not isinstance(render, list) or not render
                or any(not isinstance(x, str) for x in render)):
            raise ValueError("query_requires_selected_render")
        if triple[1].startswith(("$", "?")):
            raise ValueError("query_requires_literal_relation")
        known_ref = "$" + known
        positions = [i for i in (0, 2) if triple[i] == known_ref]
        if len(positions) != 1:
            raise ValueError("query_requires_one_known_endpoint")
        asked = triple[2 - positions[0]]
        if not asked.startswith("?") or len(asked) < 2 or asked[1:] == known:
            raise ValueError("query_requires_one_asked_endpoint")
        ref_query = query[0]
        if not isinstance(ref_query, dict) or set(ref_query) != {"triple", "render"}:
            raise ValueError("query_requires_selected_query_meaning")
        ref_triple = ref_query["triple"]
        if not isinstance(ref_triple, list) or len(ref_triple) != 3:
            raise ValueError("query_requires_selected_query_meaning")
        entity = ref_triple[positions[0]]
        if not isinstance(entity, str) or not entity:
            raise ValueError("query_requires_known_entity")
        copied = copy.deepcopy(meaning)
        if substitute(copied, {known: entity})["query"] != query:
            raise ValueError("query_reference_not_reproduced_by_selected_meaning")
        word_slots = example.get("word_slots") if "word_slots" in example else None
        if word_slots is not None and word_slots != []:
            if (not isinstance(word_slots, list) or len(word_slots) != 1
                    or not isinstance(word_slots[0], str) or word_slots[0] != known):
                raise ValueError("word_slots_invalid")
        else:
            word_slots = None
        if not isinstance(text, str) or not text.strip():
            raise ValueError("empty_paraphrase")
        core = text.strip()
        frames = parser.data.get("predicate_frames")
        grammar = getattr(parser, "clause_grammar", None)
        marks = [m for m in [*((frames.get("terminators") or []) if isinstance(frames, dict) else []),
                             *((grammar.get("question_marks", []) if isinstance(grammar, dict) else []))]
                 if isinstance(m, str) and m]
        for mark in sorted(marks, key=len, reverse=True):
            if core.endswith(mark) and len(core) > len(mark):
                core = core[:-len(mark)]
                break
        core = core.rstrip()
        if not core or core.count(entity) != 1:
            raise ValueError("paraphrase_requires_unambiguous_shared_entities")
        result = {"text": core, "slots": {known: entity}, "meaning": copied}
        if word_slots:
            result["word_slots"] = [known]
        return result

    if expression_kind not in ("fact", "query") or type(expression_kind) is not str:
        raise ValueError("invalid_expression_kind")
    if type(inherit_declared_slots) is not bool:
        raise ValueError("inherit_declared_slots_requires_bool")
    if expression_kind == "query":
        if not inherit_declared_slots:
            raise ValueError("query_requires_selected_inheritance")
        return _query_annotation()
    word_slots = None
    if inherit_declared_slots:
        parsed = parser.parse(equivalent, partial=True, _entry_selection=True)
        if not isinstance(parsed, dict):
            raise ValueError("equivalent_requires_one_known_fact")
        reference = {
            "facts": [{k: v for k, v in item.items() if k != "evidence"}
                      if isinstance(item, dict) else item
                      for item in (parsed.get("facts") or [])],
            "query": parsed.get("query") or [],
        }
        if reference["query"] or len(reference["facts"]) != 1:
            raise ValueError("equivalent_requires_one_known_fact")
        if not isinstance(reference["facts"][0], dict):
            raise ValueError("equivalent_requires_one_known_fact")
        example = _selected_example(parser, parsed, reference)
        word_slots = _declared_word_slots(example, reference["facts"][0])
    else:
        reference = semantics(parser, equivalent)
        if not reference or reference["query"] or len(reference["facts"]) != 1:
            raise ValueError("equivalent_requires_one_known_fact")
    if not isinstance(text, str) or not text.strip():
        raise ValueError("empty_paraphrase")
    text = text.strip().rstrip(".!?")
    meaning = copy.deepcopy(reference["facts"][0])
    if set(meaning) - {"triple", "polarity", "modality"}:
        raise ValueError("unsupported_paraphrase_metadata")
    slots = {}
    for position, name in ((0, "subject"), (2, "object")):
        literal = meaning["triple"][position]
        if not isinstance(literal, str) or not literal or text.count(literal) != 1:
            raise ValueError("paraphrase_requires_unambiguous_shared_entities")
        slots[name] = literal
        meaning["triple"][position] = "$" + name
    result = {"text": text, "slots": slots, "meaning": meaning}
    if word_slots:
        result["word_slots"] = word_slots
    return result


def propose_paraphrase(parser, payload):
    correction = from_paraphrase(parser, payload["text"], payload["equivalent"])
    validation = []
    for case in payload["validation"]:
        if "equivalent" in case:
            expected = semantics(parser, case["equivalent"])
            if not expected or not expected["facts"] or expected["query"]:
                raise ValueError("validation_reference_not_understood")
        elif case.get("unrecognized") is True:
            expected = None
        else:
            raise ValueError("validation_requires_equivalent_or_unrecognized")
        validation.append({"id": case.get("id"), "text": case["text"], "expected": expected})
    result = propose(parser, correction, validation)
    return {**result, "kind": "validated_paraphrase", "inferred_annotation": correction,
            "supervision": "user-declared equivalent wording and independent validation pairs"}


def semantics(parser, text):
    parsed = parser.parse(text, partial=True)
    if parsed is None:
        return None
    return {"facts": [{k: v for k, v in item.items() if k != "evidence"}
                      for item in parsed["facts"]], "query": parsed["query"]}


def propose(parser, correction, validation, *, entry_origin=None, expression_kind="fact"):
    if expression_kind not in ("fact", "query") or type(expression_kind) is not str:
        raise ValueError("invalid_expression_kind")
    from relational_semantics import RelationalParser
    from marco.language.entry_origins import EntryOriginError
    if len(parser.data["examples"]) != len(parser.templates):
        raise EntryOriginError("entry_origins_misaligned")
    current_origins = None
    if "_entry_origins" in parser.__dict__:
        current_origins = parser.__dict__["_entry_origins"]
        if (not isinstance(current_origins, list)
                or len(current_origins) != len(parser.data["examples"])
                or len(current_origins) != len(parser.templates)):
            raise EntryOriginError("entry_origins_misaligned")
    trial = RelationalParser(data=parser.data, language_pack=parser.language_pack,
                             entry_origins=current_origins)
    if expression_kind == "query":
        changed = trial.learn(correction, entry_origin=entry_origin, expression_kind="query")
    else:
        changed = trial.learn(correction, entry_origin=entry_origin)
    if not isinstance(validation, list) or not validation:
        raise ValueError("expression_requires_transfer_validation")
    if any(not isinstance(case, dict) for case in validation):
        raise ValueError("invalid_expression_validation")
    if not any(x.get("expected") is None for x in validation) or not any(
            isinstance(x.get("expected"), dict) for x in validation):
        raise ValueError("need_positive_and_negative_expression_validation")
    rows = []
    for case in validation:
        if not isinstance(case.get("text"), str) or not case["text"].strip() or "expected" not in case:
            raise ValueError("invalid_expression_validation")
        expected = case["expected"]
        if expected is not None and (not isinstance(expected, dict)
                or set(expected) != {"facts", "query"} or not isinstance(expected["facts"], list)):
            raise ValueError("invalid_expected_semantics")
        def _supported_query(record):
            """One grounded binary query: ?asked endpoint, known endpoint, literal relation."""
            if not isinstance(record, dict) or set(record) != {"triple", "render"}:
                return False
            triple, render = record["triple"], record["render"]
            if (not isinstance(triple, list) or len(triple) != 3
                    or any(not isinstance(x, str) or not x for x in triple)):
                return False
            if not isinstance(render, list) or not render or any(not isinstance(x, str) for x in render):
                return False
            if triple[1].startswith(("$", "?")):
                return False
            asked = [i for i in (0, 2) if triple[i].startswith("?")]
            if len(asked) != 1 or len(triple[asked[0]]) < 2:
                return False
            return not triple[2 - asked[0]].startswith(("$", "?"))

        if (expression_kind == "query" and expected is not None
                and (expected["facts"] != [] or not isinstance(expected["query"], list)
                     or len(expected["query"]) != 1 or not _supported_query(expected["query"][0]))):
            raise ValueError("invalid_expected_semantics")
        if any(entity in case["text"] for entity in correction["slots"].values()):
            raise ValueError("training_validation_entity_overlap")
        before, after = semantics(parser, case["text"]), semantics(trial, case["text"])
        rows.append({"id": case.get("id"), "before_ok": before == expected,
                     "after_ok": after == expected, "before": before, "after": after,
                     "expected": expected})
    accepted = (changed and all(row["after_ok"] for row in rows)
                and any(not row["before_ok"] for row in rows))
    if accepted:
        parser.data = copy.deepcopy(trial.data)
        parser.templates = list(trial.templates)
        parser._entry_origins = copy.deepcopy(trial._entry_origins)
        parser._rebuild_inflections()
    return {"kind": "validated_supervised_expression", "accepted": accepted,
            "reason": "validated_transfer" if accepted else "no_improvement_or_validation_failure",
            "validation": rows}


def induce_pattern_graph(base, demonstrations):
    """Delegate to the pure bounded choice-graph inducer."""
    from marco.learning.expression_graph import induce_pattern_graph as _impl
    return _impl(base, demonstrations)


def graph_annotations(graph):
    """Delegate to the strict choice-graph compiler."""
    from marco.learning.expression_graph import graph_annotations as _impl
    return _impl(graph)


def propose_pattern_graph(parser, graph, validation, *, entry_origin=None):
    """Delegate to the atomic choice-graph proposal gate."""
    from marco.learning.expression_graph import propose_pattern_graph as _impl
    return _impl(parser, graph, validation, entry_origin=entry_origin)
