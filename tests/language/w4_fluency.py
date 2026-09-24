"""W4.4: fluency sample of explanations — why each reply was said, composed from its why chain.

    KG_ENCODER=문자 python tests/language/w4_fluency.py [--ledger LEDGER]

The round-3 dev set (``data/benchmarks/dialogues_dev3/``, seen data) is recorded as
``python -m marco.trace record data/benchmarks/dialogues_dev3 --out DIR --name dev3`` records
it (``--ledger`` reuses such a ledger). From its outputs, drawn with a fixed seed: 20 answered
(10 per language: 3 whose chain carries a correction, 7 others) and 10 held (5 per language,
one reason after another, the commonest first). Each output's why chain is composed by the realizer in the
dialogue's own language (``marco.trace.explain.explain``). Every output of the ledger is also
composed in both languages, and the counts go in the header.

Writes ``marco/language/measurements/fluency-sample-why.md`` with an empty judgement column:
fluency is judged by a person, not counted. The frozen sets are never read.
"""
import argparse
import collections
import os
from pathlib import Path
import random
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
SEED = 20260924
DATASET = "data/benchmarks/dialogues_dev3"
OUT = ROOT / "marco/language/measurements/fluency-sample-why.md"
ANSWERED, WITH_CORRECTION, HELD = 10, 3, 5
CODES = ("ko", "en")


def record(directory):
    """The dev set recorded by the trace command line; the ledger's path."""
    from marco.trace.__main__ import main as trace
    assert trace(["record", str(ROOT / DATASET), "--out", str(directory), "--name", "dev3"]) == 0
    return Path(directory) / "dev3.jsonl"


def rows(graph):
    """Every output with its chain meaning, its dialogue language, its input and its reply."""
    from marco.trace.explain import chain_meaning
    inputs = {e["trace_id"]: e for e in graph.events if e["kind"] == "input_received"}
    out = []
    for event in graph.events:
        if event["kind"] != "output_created":
            continue
        meaning = chain_meaning(graph, event["event_id"])
        code = "ko" if (meaning.get("conversation_language") or "").endswith("한국어.json") else "en"
        out.append({"output": event["event_id"], "code": code, "meaning": meaning,
                    "turn": "%s#%s" % (event["payload"]["conversation"], event["payload"]["turn"]),
                    "status": event["status"], "input": inputs[event["trace_id"]]["payload"]["text"],
                    "reply": event["payload"]["text"]})
    return out


def pick(all_rows, seed=SEED):
    chooser = random.Random(seed)
    chosen = {}
    for code in CODES:
        answered = [r for r in all_rows if r["code"] == code and r["meaning"]["kind"] == "chain"
                    and r["status"] == "answered"]
        corrected = [r for r in answered if r["meaning"]["withdrawn"]]
        plain = [r for r in answered if not r["meaning"]["withdrawn"]]
        take = chooser.sample(corrected, WITH_CORRECTION) + chooser.sample(plain, ANSWERED - WITH_CORRECTION)
        by_reason = collections.defaultdict(list)
        for r in all_rows:
            if r["code"] == code and r["meaning"]["kind"] == "chain_hold":
                by_reason[r["meaning"]["reason"]].append(r)
        for reason in sorted(by_reason):
            chooser.shuffle(by_reason[reason])
        # The commonest reasons first (on dev3: an unread earlier statement, a pointer to two people).
        held, reasons = [], sorted(by_reason, key=lambda reason: (-len(by_reason[reason]), reason))
        while len(held) < HELD and any(by_reason.values()):
            for reason in reasons:
                if by_reason[reason] and len(held) < HELD:
                    held.append(by_reason[reason].pop())
        order = {r["output"]: i for i, r in enumerate(all_rows)}
        chosen[code] = sorted(take, key=lambda r: order[r["output"]]) + sorted(held, key=lambda r: order[r["output"]])
    return chosen


def compose_all(graph, all_rows):
    """Every output composed in its own language and in the other: counts of composed, held, passed."""
    from marco.trace.explain import explain
    counts = collections.Counter()
    for row in all_rows:
        for code in CODES:
            _text, report = explain(graph, row["output"], code)
            which = "own" if code == row["code"] else "other"
            state = "composed" if report.get("realized") and not report.get("held") else (
                "held" if report.get("realized") else "passed_through")
            counts[(which, state)] += 1
    return counts


def table(chosen, counts, total, ledger_name, seed=SEED):
    from marco.trace.explain import explain
    from marco.language.realizer import last_report

    def cell(text):
        return str(text).replace("|", "\\|").replace("\n", " ")
    lines = ["# Fluency sample of explanations — for the owner to judge", "",
             "Goal W4.4. 30 explanations of why a reply was said, each composed by the realizer from the reply's "
             "why chain in the trace ledger (`marco/trace/explain.py`, plans `chain` and `chain_hold` in "
             "`marco/language/realizer/meaning.json`), in the dialogue's own language. The ledger records "
             "`%s/` (seen data, 88 dialogues) as `python -m marco.trace record %s --out <dir> --name dev3` "
             "does. Drawn with seed %d, per language: %d answered replies (%d whose chain carries a correction, "
             "%d others) and %d held replies, one hold reason after another, the commonest first. The "
             "judgement column is empty on purpose: fluency is judged by a person, not counted." % (
                 DATASET, DATASET, seed, ANSWERED, WITH_CORRECTION, ANSWERED - WITH_CORRECTION, HELD), "",
             "Every output of the ledger (%d) was composed this way: in its own language %d composed, "
             "%d held, %d passed through; in the other language %d composed, %d held, %d passed through." % (
                 total, counts[("own", "composed")], counts[("own", "held")], counts[("own", "passed_through")],
                 counts[("other", "composed")], counts[("other", "held")], counts[("other", "passed_through")]),
             "", "Regenerate: `KG_ENCODER=문자 python tests/language/w4_fluency.py` "
             "(`--ledger <dev3.jsonl>` reuses a recorded ledger). A single explanation: "
             "`python -m marco.trace why <ledger> <output event id> --say ko|en`.", "",
             "| # | language | turn | reply status | hold reason | input | reply as said | why, composed | judgement |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    n = 0
    for code in CODES:
        for row in chosen[code]:
            text, report = explain(ledger_name, row["output"], code)
            assert report["realized"] and not report["held"] and last_report()["text"] == text, row["turn"]
            n += 1
            lines.append("| %d | %s | %s | %s | %s | %s | %s | %s | |" % (
                n, code, row["turn"], row["status"], row["meaning"].get("reason") or "", cell(row["input"]),
                cell(row["reply"]), cell(text)))
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--ledger", help="a ledger of the dev set recorded by python -m marco.trace record")
    args = parser.parse_args(argv)
    if args.ledger and ("dialogues_v1" in args.ledger or "reasoning_v1" in args.ledger):
        raise SystemExit("the frozen sets are scored by the owner only")
    os.environ.setdefault("KG_ENCODER", "문자")
    sys.path.insert(0, str(ROOT))
    from marco.trace.why import Graph
    with tempfile.TemporaryDirectory(prefix="w4-fluency-") as directory:
        ledger = Path(args.ledger) if args.ledger else record(directory)
        graph = Graph(ledger)
        all_rows = rows(graph)
        chosen = pick(all_rows)
        counts = compose_all(graph, all_rows)
        OUT.write_text(table(chosen, counts, len(all_rows), graph), encoding="utf-8")
    print("wrote", OUT.relative_to(ROOT), "from", len(all_rows), "outputs;", dict(counts))


if __name__ == "__main__":
    main()
