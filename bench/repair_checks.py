"""Repair checks: what a bounded repair must accept, and what it must hold.

Development cases (not the frozen unseen set). A sentence that a repair should
place records the expected state and names the repair; a sentence whose
nearest reading would drop a typed word — including a negation — must be held,
with the hold naming what could not be placed. A hold is never counted as
solved, and a state recorded where a hold was due is a wrong assertion.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASES = [
    ("한국어", "민수는 사과 다섯 개가 있어", "repaired", {"민수 사과": "5"}),
    ("한국어", "지연은 사과 두 개가 있어", "repaired", {"지연 사과": "2"}),
    ("한국어", "민수 사과는 정말 다섯 개 있어", "held", {}),
    ("한국어", "민수는 사과 다섯 개가 없어", "held", {}),
    ("english", "Minsu really has five apples", "held", {}),
    ("english", "Minsu never has five apples", "held", {}),
    ("english", "Minsu has five apples", "direct", {"Minsu apples": "5"}),
]


def run(models=None):
    from pack_model import development_model
    from marco.reasoning.context import ReasoningContext
    from bench.seven_step_dialogue import _state
    models = models or {}
    rows = []
    for language, text, expected, state in CASES:
        context = ReasoningContext(model=models.get(language) or development_model(language))
        try:
            result = context.turn(text) or {}
        except Exception as exc:
            result = {"status": "error", "answer": "%s: %s" % (type(exc).__name__, exc)}
        got_state = _state(context) if result.get("status") != "error" else None
        repaired = bool(result.get("repair")) and result.get("status") == "observed"
        if expected == "held":
            outcome = "correct_hold" if not got_state else "wrong_assertion"
        elif result.get("status") == "error":
            outcome = "execution_error"
        elif got_state == state and (repaired if expected == "repaired" else not result.get("repair")):
            outcome = "solved"
        elif got_state:
            outcome = "wrong_assertion"
        else:
            outcome = "held"
        rows.append({"language": language, "input": text, "expected": expected, "outcome": outcome,
                     "state": got_state, "answer": result.get("answer")})
    counts = {}
    for row in rows:
        counts[row["outcome"]] = counts.get(row["outcome"], 0) + 1
    ok = sum(row["outcome"] in ("solved", "correct_hold") for row in rows)
    return {"passed": ok, "total": len(rows), "outcomes": counts, "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    args = parser.parse_args()
    report = run()
    if args.out:
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print("%d/%d" % (report["passed"], report["total"]), report["outcomes"])
    for row in report["rows"]:
        print(row["outcome"], row["language"], row["input"], "|", (row["answer"] or "")[:120])
