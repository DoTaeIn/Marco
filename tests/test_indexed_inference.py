import itertools
import random

import pytest

from graph_inference import bind, closure


def reference(facts, rules):
    """Small exhaustive Cartesian-product oracle, independent of index selection."""
    known = {tuple(f["triple"]): {"fact": list(f["triple"]), "evidence": f["evidence"]} for f in facts}
    while True:
        snapshot = list(known)
        before = len(known)
        for rule in rules:
            for parents in itertools.product(snapshot, repeat=len(rule["body"])):
                bindings = {}
                for pattern, fact in zip(rule["body"], parents):
                    bindings = bind(pattern, fact, bindings)
                    if bindings is None:
                        break
                if bindings is None:
                    continue
                head = tuple(bindings.get(term, term) for term in rule["head"])
                if head not in known:
                    known[head] = {"fact": list(head), "rule": rule["id"],
                                   "parents": [list(f) for f in parents]}
        if len(known) == before:
            return known


def test_indexed_join_preserves_proofs_with_variable_predicates_repeated_variables_and_cycles():
    triples = [["a", "p", "b"], ["b", "p", "c"], ["c", "p", "a"], ["a", "other", "a"]]
    rules = [
        {"id": "chain", "body": [["?a", "p", "?b"], ["?b", "p", "?c"]],
         "head": ["?a", "p", "?c"]},
        {"id": "self", "body": [["?a", "?relation", "?a"]],
         "head": ["?a", "self_relation", "?relation"]},
    ]
    for seed in range(8):
        shuffled = list(triples)
        random.Random(seed).shuffle(shuffled)
        facts = [{"triple": triple, "evidence": index} for index, triple in enumerate(shuffled)]
        assert closure(facts, rules) == reference(facts, rules)


def test_streaming_join_retains_limit_for_duplicate_derivations():
    facts = [{"triple": [str(i), "p", "v"], "evidence": i} for i in range(8)]
    rule = {"id": "product", "body": [["?a", "p", "v"], ["?b", "p", "v"]],
            "head": ["?a", "p", "v"]}
    with pytest.raises(ValueError, match="join_limit"):
        closure(facts, [rule], limit=8)
