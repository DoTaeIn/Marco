"""Public MARCO2 session development demo using the ordinary English pack.

Run each phase with a separate Python interpreter against the same --directory:
teach, read, replace, retract. The supplied wording pairs explicitly teach one
expression; independent holdouts gate admission. This is supervised expression
learning, not autonomous discovery of facts or of a new inference rule.

Historical assertions retain their identified original readings. A repeated
new utterance uses the current expression meaning and a distinct observation
identity. Conflicting assertions remain separately sourced, and dependent
questions ask for clarification while unrelated dialogue can continue.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import pack_model

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from marco.runtime.learning_dialogue import DialogueSession


def teaching(*, reversed_roles=False):
    def reference(left, right):
        taller, shorter = (left, right) if reversed_roles else (right, left)
        return taller + " is taller than " + shorter
    return {"text": "Compared with Bea, Ada towers",
            "equivalent": reference("Bea", "Ada"),
            "validation": [
                {"id": "forward", "text": "Compared with Ivo, Nia towers",
                 "equivalent": reference("Ivo", "Nia")},
                {"id": "reversed", "text": "Compared with Nia, Ivo towers",
                 "equivalent": reference("Nia", "Ivo")},
                {"id": "negative", "text": "Compared with Ivo, Nia does not tower",
                 "unrecognized": True}]}


NOVEL = "Compared with Orin, Vega towers."
QUESTION = "Who is taller, Vega or Lune?"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", required=True, type=Path)
    parser.add_argument("--phase", required=True, choices=("teach", "read", "replace", "retract"))
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    with DialogueSession(args.directory / "memory.sqlite", args.directory / "session.json",
                         language="english", conversation_id="public-builtin-demo",
                         model=pack_model.development_model("english")) as session:
        output = {"phase": args.phase, "model": "ordinary_builtin_english_pack",
                  "supervision": "explicit_user_teaching", "turns": []}
        if args.phase == "teach":
            output["turns"].append(session.respond("Kellan is taller than Marin."))
            output["learning"] = session.teach(teaching(), turn_id="teach-1")
            wrong = teaching()
            wrong["validation"][0]["equivalent"] = "Ivo is taller than Nia"
            output["rejected_learning"] = session.teach(wrong, turn_id="teach-2")
        elif args.phase == "read":
            for text in (NOVEL, "Orin is taller than Lune.", QUESTION, "Who is taller, Vega or Orin?"):
                output["turns"].append(session.respond(text))
        elif args.phase == "replace":
            active = next(row for row in session.memory.candidates() if row["status"] == "active")
            output["learning"] = session.teach(teaching(reversed_roles=True), turn_id="teach-3",
                                               replaces=active["candidate_id"])
            output["turns"].append(session.respond("Lune is taller than Rhea."))
            output["turns"].append(session.respond("Who is taller, Vega or Rhea?"))
            output["repeated_utterance"] = session.respond(NOVEL)
            output["turns"].append(session.respond("Compared with Sana, Theo towers."))
            output["turns"].append(session.respond("Who is taller, Sana or Theo?"))
        else:
            active = next(row for row in session.memory.candidates() if row["status"] == "active")
            output["learning"] = session.retract(active["candidate_id"], "The user withdrew this expression.")
            output["turns"].append(session.respond("Theo is taller than Umi."))
            output["turns"].append(session.respond("Who is taller, Sana or Umi?"))
            output["turns"].append(session.respond("Who is taller, Kellan or Marin?"))
            output["repeated_utterance"] = session.respond(NOVEL)
        output["snapshot"] = session.snapshot()
        output["candidate_states"] = [{"id": row["candidate_id"], "status": row["status"],
                                       "accepted": row["accepted"]} for row in session.memory.candidates()]
        output["limits"] = ["Explicit teaching and finite transfer validation.",
                            "Historical facts keep their original meaning.",
                            "New utterances use current meanings; contradictory questions are held locally.",
                            "Retrieved claims remain untrusted and never automatically enter the graph."]
        print(json.dumps(output, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
