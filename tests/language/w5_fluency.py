"""W5.4: fluency sample 5 — 40 composed replies from dev set v4's check half, 20 per language.

    KG_ENCODER=문자 python tests/language/w5_fluency.py

The check half of ``data/benchmarks/dialogues_dev4/`` (the dialogues whose ``variation.half`` is
``check``; seen data, phrased from structured scenarios) is played through the composition
gate's runner (the UI's ``AppState.turn``), and the realizer's report is kept for every turn.
Per language (the language of the reply), 20 composed replies:

* every reply round 5 changed how it is said (a plan or an expression declared in round 5:
  the corrected receiver, the Korean user in a total, a comparison or as a recipient, a
  holder's count said with the existence verb), at most ``ROUND5`` of them;
* then one reply of each act the sample does not have yet, drawn with a fixed seed;
* then replies drawn with the same seed until there are 20.

Writes ``marco/language/measurements/fluency-sample-5.md`` with an empty judgement column:
fluency is judged by a person, not counted. The frozen sets are never read.
"""
import collections
import os
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[2]
SEED = 20260925
DATASET = "data/benchmarks/dialogues_dev4"
OUT = ROOT / "marco/language/measurements/fluency-sample-5.md"
PER_LANGUAGE, ROUND5 = 20, 8
CODES = ("ko", "en")
ACTS = ("answer", "record", "hold", "correct", "ask", "explain")
# The expressions and plans round 5 declared (marco/language/realizer/*.json, W5.1, W5.2).
ROUND5_CANDIDATES = frozenset({
    "recipient_changed", "recipient_corrected_received", "recipient_corrected_side", "total_with_addressee",
    "same_count_addressee_alike", "same_count_addressee_not_alike", "transfer_receive_from",
    "heard_never_addressee", "known_never_came_up_addressee", "count_became_addressee",
    "withdrew_change_addressee", "withdrew_value_addressee", "count_topic_exist", "several_readings",
    "reading_fits_none"})


def play(dialogues):
    """The composition gate's rows for ``dialogues``, each with the realizer report of its turn."""
    import composition_gate as cg
    from views.kgpack_ui import AppState
    import marco.language.realizer as realizer
    reports = []
    original = AppState.turn

    def turn(self, *args, **kwargs):
        before = realizer.default_realizer().reports
        marker = before[-1] if before else None
        try:
            return original(self, *args, **kwargs)
        finally:
            after = realizer.default_realizer().reports
            reports.append(realizer.last_report() if after and after[-1] is not marker else None)
    AppState.turn = turn
    try:
        answers = cg.run(dialogues)
    finally:
        AppState.turn = original
    report = cg.score(dialogues, answers)
    rows = report["rows"]
    assert len(rows) == len(reports), (len(rows), len(reports))
    for row, said in zip(rows, reports):
        row["report"] = said or {}
    return report, rows


def round5(row):
    said = row["report"]
    used = {clause.get("candidate") for clause in said.get("clauses") or []}
    return bool(used & ROUND5_CANDIDATES) or (said.get("plan") or {}).get("fields") == {"field": "recipient"}


def pick(rows, seed=SEED):
    chooser = random.Random(seed)
    chosen = {}
    for code in CODES:
        pool = [row for row in rows if row["bucket"] == "composed" and row["language"] == code]
        new = [row for row in pool if round5(row)][:ROUND5]
        taken = list(new)
        rest = [row for row in pool if row not in taken]
        have = {row["act"] for row in taken}
        for act in ACTS:
            of_act = [row for row in rest if row["act"] == act]
            if act not in have and of_act:
                row = chooser.choice(of_act)
                taken.append(row)
                rest.remove(row)
                have.add(act)
        chooser.shuffle(rest)
        taken += rest[:PER_LANGUAGE - len(taken)]
        order = {row["turn"]: index for index, row in enumerate(rows)}
        chosen[code] = sorted(new, key=lambda row: order[row["turn"]]) + sorted(
            [row for row in taken if row not in new], key=lambda row: order[row["turn"]])
    return chosen


def table(report, chosen, dialogues, seed=SEED):
    def cell(text):
        return str(text).replace("|", "\\|").replace("\n", " ")
    counts = collections.Counter((row["language"], row["bucket"]) for row in report["rows"])
    lines = ["# Fluency sample 5 — for the owner to judge", "",
             "Goal W5.4. 40 replies, 20 per language, from the check half of `%s/` (%d dialogues whose "
             "`variation.half` is `check`; seen data, phrased from structured scenarios), played through "
             "`AppState.turn` as `bench/composition_gate.py` plays it. On that half the realizer composed "
             "%d of %d spoken replies (ko %d of %d, en %d of %d; held %d, passed through %d)." % (
                 DATASET, len(dialogues), report["total"]["composed"], report["total"]["spoken"],
                 counts[("ko", "composed")], sum(v for (c, _b), v in counts.items() if c == "ko"),
                 counts[("en", "composed")], sum(v for (c, _b), v in counts.items() if c == "en"),
                 report["total"]["held"], report["total"]["passed_through"]),
             "",
             "Per language: first every reply round 5 changed (marked *round 5*: a corrected receiver named, "
             "request G4-1; the Korean user said by the honorific in a total, a comparison or as a recipient, "
             "request G4-2; a holder's count said with the existence verb), at most %d; then one reply of each "
             "act not yet in the sample; then replies drawn at random (seed %d) until 20. The judgement column "
             "is empty on purpose: fluency is judged by a person, not counted." % (ROUND5, seed),
             "", "Regenerate: `KG_ENCODER=문자 python tests/language/w5_fluency.py`.", "",
             "| # | language | turn | act | round 5 | input | composed reply | judgement |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    n = 0
    for code in CODES:
        for row in chosen[code]:
            n += 1
            lines.append("| %d | %s | %s | %s | %s | %s | %s | |" % (
                n, code, row["turn"], row["act"], "round 5" if round5(row) else "", cell(row["say"]),
                cell(row["composed_text"])))
    return "\n".join(lines) + "\n"


def main():
    os.environ.setdefault("KG_ENCODER", "문자")
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "bench"))
    import dialogue_gate as gate
    dialogues = [d for d in gate.load(ROOT / DATASET) if (d.get("variation") or {}).get("half") == "check"]
    report, rows = play(dialogues)
    chosen = pick(rows)
    assert all(len(chosen[code]) == PER_LANGUAGE for code in CODES), {c: len(v) for c, v in chosen.items()}
    OUT.write_text(table(report, chosen, dialogues), encoding="utf-8")
    print("wrote", OUT.relative_to(ROOT), "from", report["total"]["composed"], "composed of",
          report["total"]["spoken"], "on", len(dialogues), "check dialogues;",
          "round 5 rows:", {code: sum(round5(r) for r in chosen[code]) for code in CODES})


if __name__ == "__main__":
    main()
