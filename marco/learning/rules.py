"""Supervised rule induction from aligned, corrected proof examples.

Examples supply premises and a justified conclusion, not a handwritten rule.
This learns a hypothesis; a finite validation gate is not proof of universal truth.
"""
import hashlib
import json

from graph_inference import closure, current_facts


def validate_example(example):
    triples = example.get("premises", []) + [example.get("conclusion")]
    if not example.get("premises") or len(triples) > 33:
        raise ValueError("invalid_proof_size")
    for triple in triples:
        if (not isinstance(triple, list) or len(triple) != 3 or
                any(not isinstance(x, str) or not x or x.startswith("?") for x in triple)):
            raise ValueError("expected_ground_triples")


def entities(examples):
    return {t[i] for e in examples for t in e["premises"] + [e["conclusion"]] for i in (0, 2)}


def induce(examples):
    if len(examples) < 2:
        raise ValueError("need_multiple_corrected_proofs")
    for example in examples:
        validate_example(example)
    size = len(examples[0]["premises"])
    if any(len(e["premises"]) != size for e in examples):
        raise ValueError("unaligned_proofs")
    columns, patterns = {}, []
    for position in range(size + 1):
        triples = [(e["premises"] + [e["conclusion"]])[position] for e in examples]
        if len({t[1] for t in triples}) != 1:
            raise ValueError("unaligned_predicates")
        pattern = []
        for index in range(3):
            values = tuple(t[index] for t in triples)
            if len(set(values)) == 1:
                pattern.append(values[0])
            else:
                if values not in columns:
                    columns[values] = "?v%d" % len(columns)
                pattern.append(columns[values])
        patterns.append(pattern)
    if not columns:
        raise ValueError("no_generalization")
    body, head = patterns[:-1], patterns[-1]
    bound = {x for p in body for x in p if x.startswith("?")}
    if any(x.startswith("?") and x not in bound for x in head):
        raise ValueError("unbound_conclusion")
    payload = {"body": body, "head": head}
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]
    return {"id": "learned-" + digest, **payload}


def entails(model, example):
    facts = [{"triple": t, "evidence": {"example": example.get("id"), "index": i}}
             for i, t in enumerate(example["premises"])]
    facts, _ = current_facts(facts, model.get("mutable_predicates", []), model.get("numeric_updates", {}))
    return tuple(example["conclusion"]) in closure(facts, model["rules"])


def propose(model, corrections, validation):
    """Do not mutate a model or read evaluation labels during candidate induction."""
    candidate = induce(corrections)
    if not validation or {e.get("expected") for e in validation} != {True, False}:
        raise ValueError("need_positive_and_negative_validation")
    for example in validation:
        validate_example(example)
        if type(example.get("expected")) is not bool:
            raise ValueError("expected_boolean_label")
    if entities(corrections) & entities(validation):
        raise ValueError("training_validation_entity_overlap")
    existing = model["rules"]
    updated = dict(model, rules=existing + [candidate])
    rows = []
    for example in validation:
        before, after = entails(model, example), entails(updated, example)
        rows.append({"id": example.get("id"), "expected": example["expected"],
                     "before": before, "after": after})
    accepted = (all(entails(updated, e) for e in corrections)
                and all(r["after"] == r["expected"] for r in rows)
                and any(r["before"] != r["expected"] for r in rows)
                and not any(r["before"] == r["expected"] and r["after"] != r["expected"] for r in rows))
    return {"accepted": accepted, "candidate": candidate, "validation": rows,
            "reason": "validated_transfer" if accepted else "no_improvement_or_validation_failure",
            "supervision": "aligned corrected proofs; finite positive and negative validation"}
