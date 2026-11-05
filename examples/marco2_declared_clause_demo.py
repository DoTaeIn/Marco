"""Public selected-model fixture and runnable constituent-composition demo.

All vocabulary, role/meaning mappings, operators and responses below are model
assets. The executor must not contain any of these particular domain words.
Run from the project root: PYTHONPATH=. python examples/marco2_declared_clause_demo.py
"""
import copy
import json
from pack_model import PackModel


def selected_model(reverse=False, *, declarations=True):
    relation = "cobalt_order" if reverse else "amber_order"
    triple = ["$target", relation, "$actor"] if reverse else ["$actor", relation, "$target"]
    frames = {
        "schema": "predicate-frames-v1",
        "head_pattern": "[A-Z][a-z]+",
        "modifiers": ["senior", "junior"],
        "terminators": ["."],
        "operators": [
            {"id": "deny", "form": "not", "metadata": {"polarity": False}},
            {"id": "suppose", "form": "if", "metadata": {"modality": "conditional"}},
        ],
        "frames": [{
            "id": "selected-order", "forms": ["outranks"],
            "roles": [
                {"name": "actor", "marker": "from", "side": "before"},
                {"name": "target", "marker": "to", "side": "after"},
            ],
            "meaning": {"triple": triple},
        }],
    }
    relational = {
        "schema": "annotated-relations-v1", "answer_suffix": "", "numerals": {},
        "examples": [
            {"text": "Ada outranks Bea", "slots": {"actor": "Ada", "target": "Bea"},
             "meaning": {"triple": triple}},
            {"text": "Does Ada lead Bea", "slots": {"actor": "Ada", "target": "Bea"},
             "meaning": {"query": [{"triple": triple,
                                    "render": ["B confirmed" if reverse else "A confirmed"]}]}},
        ],
    }
    relational["examples"].append({"text": "Who outranks Bea", "slots": {"target": "Bea"},
        "meaning": {"query": [{"triple": ["?actor" if t == "$actor" else t for t in triple],
                                "render": ["$actor"]}]}})
    if declarations:
        relational["predicate_frames"] = frames
    style = {"인코더": {"mode": "문자", "dimensions": 4096, "jamo_weight": 0.5,
              "smoothing": 0, "route_threshold": 0.43, "cluster_threshold": 0.3,
              "goal_similarity_threshold": 0.62, "device": "cpu"}, "conversation": {}, "문장분리": {"question_marks": ["?"],
              "hypothetical_prefixes": ["if", "perhaps"]}, "관계해석": relational}
    rules = [] if reverse else [{"id": "selected-transitivity",
        "body": [["?x", relation, "?y"], ["?y", relation, "?z"]],
        "head": ["?x", relation, "?z"]}]
    manifest = {"version": 3, "model": {"format": "nai-model", "version": 1,
        "language": "styles/selected.json", "axioms": ["axioms/selected.json"]}}
    assets = {"styles/selected.json": json.dumps(style).encode(),
              "axioms/selected.json": json.dumps({"schema": "nai-axioms-v1", "rules": rules}).encode()}
    return PackModel(copy.deepcopy(manifest), assets)


PUBLIC_COMBINATIONS = [
    "to junior Nia from senior Oren outranks",
    "outranks to junior Nia from senior Oren",
    "from senior Oren to junior Nia outranks",
]


def main():
    report = []
    for reverse in (False, True):
        parser = selected_model(reverse).parser()
        old = selected_model(reverse, declarations=False).parser()
        for text in PUBLIC_COMBINATIONS:
            parsed = parser.parse(text, partial=True, events=True, repair=True)
            report.append({"model": "B" if reverse else "A", "input": text,
                "old_template_parse": old.parse(text, partial=True),
                "facts": parsed["facts"] if parsed else None})
        first = parser.parse("Oren outranks Nia", partial=True)
        second = parser.parse("Nia outranks Kira", partial=True)
        question = parser.parse("Does Oren lead Kira?", partial=True)
        combined = {**question, "facts": first["facts"] + second["facts"]}
        report.append({"model": "B" if reverse else "A", "query": "Does Oren lead Kira?",
                       "answer": parser.answer(combined)})
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
