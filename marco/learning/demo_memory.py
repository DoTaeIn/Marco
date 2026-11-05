"""Public bounded teaching demo; run each phase in a separate Python process.

The toy seed knows one comparison syntax and transitivity. A person explicitly
teaches a new wording with independent positive/negative examples. This is
supervised expression transfer, not discovery of a new fact or inference rule.
"""
from __future__ import annotations

import argparse
import json

from relational_semantics import RelationalParser
from marco.learning.expressions import semantics
from marco.learning.memory import LearningMemory


def seed_parser():
    return RelationalParser(data={
        "examples": [
            {"text": "Ada is taller than Bea", "slots": {"a": "Ada", "b": "Bea"},
             "meaning": {"triple": ["$a", "taller", "$b"]}},
            {"text": "Is Ada taller than Bea", "slots": {"a": "Ada", "b": "Bea"},
             "meaning": {"query": [{"triple": ["$a", "taller", "$b"],
                                     "render": ["$a", " is taller than ", "$b"]}]}}
        ],
        "rules": [{"id": "toy-transitive", "body": [
            ["?a", "taller", "?b"], ["?b", "taller", "?c"]],
            "head": ["?a", "taller", "?c"]}],
        "answer_suffix": ""
    }, language_pack={})


def teaching(*, reversed_roles=False):
    pairs = [("Bea", "Ada"), ("Ivo", "Nia"), ("Nia", "Ivo")]
    def equivalent(left, right):
        a, b = (left, right) if reversed_roles else (right, left)
        return a + " is taller than " + b
    return {"text": "Compared with Bea, Ada towers",
            "equivalent": equivalent(*pairs[0]),
            "validation": [
                {"id": "forward", "text": "Compared with Ivo, Nia towers",
                 "equivalent": equivalent(*pairs[1])},
                {"id": "reverse", "text": "Compared with Nia, Ivo towers",
                 "equivalent": equivalent(*pairs[2])},
                {"id": "negation", "text": "Compared with Ivo, Nia does not tower",
                 "unrecognized": True}]}


NOVEL_WORDING = "Compared with Orin, Vega towers"
NOVEL_QUESTION = (NOVEL_WORDING + ". Orin is taller than Lune. "
                  "Is Vega taller than Lune?")


def main():
    options = argparse.ArgumentParser(description=__doc__)
    options.add_argument("--store", required=True)
    options.add_argument("--phase", choices=("teach", "read", "retract"), required=True)
    args = options.parse_args()
    base = seed_parser()
    with LearningMemory(args.store, base) as memory:
        report = None
        if args.phase == "teach":
            report = memory.teach(teaching(), {"conversation_id": "public-demo", "turn_id": "1"})
            wrong = teaching()
            wrong["validation"][0]["equivalent"] = "Ivo is taller than Nia"
            rejected = memory.teach(wrong, {"conversation_id": "public-demo", "turn_id": "2"})
        elif args.phase == "retract":
            active = next(row for row in memory.candidates() if row["status"] == "active")
            report = memory.retract(active["candidate_id"], "The speaker withdrew this wording.")
        parser = memory.parser()
        parsed = parser.parse(NOVEL_QUESTION, partial=True)
        result = parser.answer(parsed) if parsed else None
        output = {"phase": args.phase, "supervision": "explicit_user_teaching",
                  "report": report, "novel_wording_meaning": semantics(parser, NOVEL_WORDING),
                  "novel_question": NOVEL_QUESTION, "answer": result,
                  "base_meaning": semantics(parser, "Mira is taller than Rook"),
                  "candidates": memory.candidates()}
        if args.phase == "teach":
            output["rejected_report"] = rejected
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
