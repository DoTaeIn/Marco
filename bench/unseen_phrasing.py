"""Frozen unseen phrasings: answered / held / wrong / error, counted apart.

The cases in ``data/benchmarks/unseen_phrasing_v1.json`` were written before
the repair and English work and are not edited to pass.  Only the last turn is
scored.  A hold on an answerable case is a failure, never a solve.
"""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def _has_value(text, expected):
    if expected.isdecimal():
        return any(value == expected for value in re.findall(r"(?<![\d.])\d+(?!\d|\.\d)", text))
    return expected in text


def run(path=None):
    from pack_model import development_model
    from marco.reasoning.context import ReasoningContext
    data = json.loads(Path(path or ROOT / "data/benchmarks/unseen_phrasing_v1.json").read_text("utf-8"))
    rows = []
    for case in data["cases"]:
        context = ReasoningContext(model=development_model(case["language"]))
        row = {"id": case["id"], "language": case["language"]}
        try:
            results = [context.turn(text) for text in case["turns"]]
            last = results[-1] or {}
            status, text = last.get("status"), last.get("answer") or ""
            row.update(status=status, answer=text,
                       repaired=bool(any((r or {}).get("repair") for r in results)))
            answered = status == "answered"
            if case.get("unknown"):
                row["outcome"] = "correct_hold" if not answered else "wrong"
            elif not answered:
                row["outcome"] = "held"
            else:
                row["outcome"] = "answered" if _has_value(text, case["answer"]) else "wrong"
        except Exception as exc:  # counted apart, never as a hold
            row.update(outcome="error", error="%s: %s" % (type(exc).__name__, exc))
        rows.append(row)
    summary = {}
    for row in rows:
        summary[row["outcome"]] = summary.get(row["outcome"], 0) + 1
    solved = sum(row["outcome"] in ("answered", "correct_hold") for row in rows)
    return {"dataset": data["id"], "total": len(rows), "solved": solved, "outcomes": summary,
            "failures": [row for row in rows if row["outcome"] not in ("answered", "correct_hold")],
            "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--data")
    parser.add_argument("--out")
    args = parser.parse_args()
    report = run(args.data)
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("total", "solved", "outcomes")}, ensure_ascii=False))
    for row in report["failures"]:
        print(row["id"], row["outcome"], row.get("answer") or row.get("error"))
