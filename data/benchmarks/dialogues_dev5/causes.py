"""Cause tables from the trace ledger (goal G5.2), for dev set v4 or v5, one half at a time.

One run plays the dialogues through the UI turn handler exactly as the gate does, with the trace ledger on
(``marco.trace.drive.record``) and the engine sites writing their own events to the same ledger
(``ReasoningContext.trace``, ``engine.TRACE``: request L1-1, G5.0 b). From that one run:

* the gate's score (``bench.dialogue_gate.score``) and the ledger's statistics
  (``marco.trace.stats.table``: outputs by status, holds by reason, the record rate), with the gate's
  denominators;
* **record turns not correct** and **answerable turns not correct**, each counted once, under a cause:
  a root cause (``statement:<class>``: the first statement before it the reader cannot read on its own,
  counted under that statement's class; ``question:<class>``: every statement before it was recorded, so
  the question itself), a cascade (``statement:cascade``, ``after:<class>``: a statement read on its own
  whose holder an earlier missed statement left without a count), a realizer hold
  (``realizer:not_phrased``), or a wrong or unverifiable answer by its reason. Classes and the cascade
  rule are v4's (``dialogues_dev4/causes.py``: ``turn_class``, ``tables``), so both rounds count alike;
* **held turns by gap class**: ``payload.gap`` of the hold in each turn's own trace (the class the engine's
  own hold gave it, carried by the recorder, else the declared class of the hold's reason: request G5-1).

Each table sums to its total. Nothing of the frozen sets is read (``drive.load`` refuses them).

    python data/benchmarks/dialogues_dev5/causes.py data/benchmarks/dialogues_dev5 --split check --out DIR
"""
import argparse
import importlib.util
import json
import os
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("KG_ENCODER", "문자")
_spec = importlib.util.spec_from_file_location("dialogues_dev4_causes", HERE.parent / "dialogues_dev4" / "causes.py")
v4causes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(v4causes)


def gap_by_turn(events):
    """{(conversation, turn): gap}: the gap class on the hold of each turn's own trace (the engine's, carried
    there by the recorder, else the declared class of the hold's reason: request G5-1)."""
    turns, gaps = {}, {}
    for event in events:
        if event["kind"] == "input_received":
            turns[event["trace_id"]] = (event["payload"].get("conversation"), event["payload"].get("turn"))
        elif event["kind"] == "hold" and event["trace_id"] in turns:
            gaps[turns[event["trace_id"]]] = event["payload"].get("gap")
    return gaps


def run(dataset, split, out):
    from bench import dialogue_gate as gate
    from marco.trace import drive, stats
    from marco.trace.ledger import Ledger, read
    dialogues = drive.load(dataset, None, split)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    name = "%s_%s" % (Path(dataset).name, split or "all")
    path = out / (name + ".jsonl")
    if path.exists():
        path.unlink()
    ledger = Ledger(out, name)
    try:
        answers = drive.record(dialogues, ledger, engine_sites=True)
    finally:
        ledger.close()
    report = gate.score(dialogues, answers)
    (out / (name + "_report.json")).write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n",
                                               encoding="utf-8")
    events, _problems = read(path)
    table = stats.table(path)
    record, answerable, detail = v4causes.tables(report, dialogues)
    gaps = gap_by_turn(events)
    held_gaps = Counter()
    for r in report["rows"]:
        if r["bucket"] == "hold" and (r["label"] == "answerable" or r["act"] == "record"):
            held_gaps["%s:%s" % ("answerable" if r["label"] == "answerable" else "record",
                                 gaps.get((r["dialogue"], r["n"])) or "none")] += 1
    return {"dataset": str(dataset), "split": split, "gate": report["gate"], "other": report["other_labels"],
            "violations": {k: v["count"] for k, v in report["violations"].items()},
            "stats": {"outputs": table["outputs"], "holds_by_reason": table["holds_by_reason"],
                      "record": table["record"]},
            "record_causes": record, "answerable_causes": answerable, "held_by_gap": dict(held_gaps),
            "detail": [list(row[:5]) for row in detail]}


def format_tables(result):
    lines = ["%s %s" % (result["dataset"], result["split"] or "all")]
    g = result["gate"]
    rec = result["other"]["record"]
    lines.append("answerable %d/%d (%.1f%%) hold %d wrong %d unverifiable %d | record %d/%d (%.1f%%) | violations %s"
                 % (g["correct"], g["n"], 100.0 * g["correct"] / max(g["n"], 1), g["hold"], g["wrong"],
                    g["unverifiable"], rec["correct"], rec["n"], 100.0 * rec["correct"] / max(rec["n"], 1),
                    result["violations"]))
    for title, counts in (("record turns not correct", result["record_causes"]),
                          ("answerable turns not correct", result["answerable_causes"])):
        lines.append("%s: %d" % (title, sum(counts.values())))
        for key, n in sorted(v4causes.family_table(counts).items(), key=lambda kv: -kv[1]):
            lines.append("  %-40s %4d" % (key, n))
    lines.append("held turns by gap class (payload.gap of the turn's hold): %s" % json.dumps(
        dict(sorted(result["held_by_gap"].items())), ensure_ascii=False))
    reasons = result["stats"]["holds_by_reason"].get("answerable") or {}
    lines.append("ledger holds of answerable turns by reason: %s" % json.dumps(reasons, ensure_ascii=False))
    lines.append("ledger record rate: %s" % json.dumps(result["stats"]["record"], ensure_ascii=False))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--split")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run(args.dataset, args.split, args.out)
    name = "%s_%s" % (args.dataset.name, args.split or "all")
    (args.out / (name + "_causes.json")).write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n",
                                                    encoding="utf-8")
    print(format_tables(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
