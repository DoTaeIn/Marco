"""Cause tables for development set v4 (goal G4.2).

Reads a gate report (``python bench/dialogue_gate.py run --dataset data/benchmarks/dialogues_dev4
--split build --report-out report.json``) and counts, by the scenario classes each turn carries:

* **record turns not correct**: a statement the parser reads on its own but the conversation did not
  apply (it names a holder an earlier missed statement left without a count) is a cascade, counted
  under the first missed statement before it (``after:<class>``); any other under its own class;
* **answerable turns not correct**: a hold after a statement the engine did not record is caused by
  the first such statement the parser cannot read on its own (``statement:<class>``), or by a cascade
  (``statement:cascade``); a hold the realizer made of a parsed answer is ``realizer:not_phrased``; a
  hold with every statement before it recorded is caused by the question (``question:<class>``); a
  wrong or unverifiable answer is counted by its reason.

A turn carries several classes; it is counted once, under the first family of ``PRIORITY`` it has
(its most specific surface class), so each table sums to its total.

    python data/benchmarks/dialogues_dev4/causes.py report.json [--dataset DIR] [--rows]
"""
import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
PRIORITY = ("zero_vague", "holders", "partitives", "fronting", "transfer_verbs", "referent_repairs",
            "question_forms", "corrections", "multi_fact")


def turn_class(turn, dialogue):
    """The one class a turn is counted under."""
    classes = turn.get("classes") or []
    for family in PRIORITY:
        hits = sorted(c for c in classes if c.split(":")[0] == family)
        if hits:
            return hits[0]
    if dialogue["language"] == "ko" and dialogue["variation"].get("register") in ("hapsyo", "banmal"):
        return "korean_register:" + dialogue["variation"]["register"]
    return "plain:" + (turn["expect"]["act"] if turn["expect"]["act"] != "answer" else
                       turn["expect"].get("relation") or "answer")


REALIZER_HOLD = ("This answer is on hold", "답을 보류")
_PARSERS = {}


def reads_alone(language, text):
    """True when the pack's parser reads the statement by itself (facts or a transfer)."""
    import os
    sys.path.insert(0, str(ROOT))
    os.environ.setdefault("KG_ENCODER", "문자")
    from pack_model import development_model
    name = "한국어" if language == "ko" else "english"
    if name not in _PARSERS:
        _PARSERS[name] = development_model(name).parser()
    parsed = _PARSERS[name].parse(text, partial=True, events=True, repair=True) or {}
    return bool(parsed.get("facts"))


def tables(report, dialogues):
    rows = {(r["dialogue"], r["n"]): r for r in report["rows"]}
    record, answerable, detail = {}, {}, []
    for d in dialogues:
        missed, root = None, None
        for t in d["turns"]:
            row = rows.get((d["id"], t["n"]))
            if row is None:
                continue
            if t["expect"]["act"] in ("record", "revise") and row["bucket"] != "correct":
                cls = turn_class(t, d)
                alone = t["expect"]["act"] == "record" and reads_alone(d["language"], t["say"])
                counted = ("after:" + missed[1]) if (alone and missed is not None) else cls
                if t["expect"]["act"] == "record":
                    record[counted] = record.get(counted, 0) + 1
                    detail.append(("record", counted, d["id"], t["n"], row["reason"], t["say"]))
                if missed is None:
                    missed = (t, cls)
                if root is None and not alone:
                    root = (t, cls)
            if t["label"] != "answerable" or row["bucket"] == "correct":
                continue
            if row["bucket"] == "hold" and any(mark in (row.get("answer") or "") for mark in REALIZER_HOLD):
                cause = "realizer:not_phrased"
            elif row["bucket"] == "hold":
                cause = ("statement:" + root[1]) if root is not None else (
                    "statement:cascade" if missed is not None else ("question:" + turn_class(t, d)))
            else:
                cause = "%s:%s" % (row["bucket"], str(row["reason"]).split(":")[0])
            answerable[cause] = answerable.get(cause, 0) + 1
            detail.append(("answerable", cause, d["id"], t["n"], row["reason"], t["say"]))
    return record, answerable, detail


def family_table(counts):
    out = {}
    for key, n in counts.items():
        head = key.split(":")[0] if not key.startswith(("statement:", "question:", "after:")) else \
            ":".join(key.split(":")[:2])
        out[head] = out.get(head, 0) + n
    return out


def main(argv=None):
    sys.path.insert(0, str(ROOT / "bench"))
    import dialogue_gate as gate
    parser = argparse.ArgumentParser()
    parser.add_argument("report", type=Path)
    parser.add_argument("--dataset", type=Path, default=HERE)
    parser.add_argument("--rows", action="store_true", help="list every counted turn")
    args = parser.parse_args(argv)
    report = json.loads(args.report.read_text(encoding="utf-8"))
    keep = {r["dialogue"] for r in report["rows"]}
    dialogues = [d for d in gate.load(args.dataset) if d["id"] in keep]
    record, answerable, detail = tables(report, dialogues)
    n_record = sum(1 for r in report["rows"] if r["act"] == "record")
    n_answer = sum(1 for r in report["rows"] if r["label"] == "answerable")
    print("record turns not correct: %d of %d" % (sum(record.values()), n_record))
    for key, n in sorted(family_table(record).items(), key=lambda kv: -kv[1]):
        print("  %-40s %4d" % (key, n))
    for key, n in sorted(record.items(), key=lambda kv: -kv[1]):
        print("      %-40s %4d" % (key, n))
    print("answerable turns not correct: %d of %d" % (sum(answerable.values()), n_answer))
    for key, n in sorted(family_table(answerable).items(), key=lambda kv: -kv[1]):
        print("  %-40s %4d" % (key, n))
    for key, n in sorted(answerable.items(), key=lambda kv: -kv[1]):
        print("      %-40s %4d" % (key, n))
    if args.rows:
        for kind, cause, did, n, reason, say in detail:
            print("%-10s %-36s %s#%d %s | %s" % (kind, cause, did, n, reason, say))
    return 0


if __name__ == "__main__":
    sys.exit(main())
