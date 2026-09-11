"""Supervised expression proposals gated by separate semantic validation cases.

Validation labels never participate in template induction. These finite checks
demonstrate bounded transfer, not truth or general language understanding.
"""
import copy


def from_paraphrase(parser, text, equivalent):
    """Ground a user-declared equivalence in a single already parsed fact.

    Subject/object strings must occur exactly once in the new wording. Their
    roles come from the reference, never their order in the new sentence.
    """
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
    return {"text": text, "slots": slots, "meaning": meaning}


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


def propose(parser, correction, validation):
    from relational_semantics import RelationalParser
    trial = RelationalParser(data=parser.data, language_pack=parser.language_pack)
    changed = trial.learn(correction)
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
        parser._rebuild_inflections()
    return {"kind": "validated_supervised_expression", "accepted": accepted,
            "reason": "validated_transfer" if accepted else "no_improvement_or_validation_failure",
            "validation": rows}
