"""W6.5: fluency sample 6 — 40 composed replies, 20 per language, 20 of them why answers.

    KG_ENCODER=문자 python tests/language/w6_fluency.py

Per language (the language of the reply):

* 10 why answers: the check half of the why-with-a-restated-fact cases of goal G6
  (``tests/test_r6_why_fact.py``; names, things and amounts the fixes never saw), each dialogue
  played through ``ReasoningContext.turn`` and its last reply kept: every explained case the reader
  reads, then the counterexamples (a number that is not the count, a count before a correction, a
  pointer to two holders, a thing not settled, nothing answered yet) until 10;
* 10 replies from the check half of ``data/benchmarks/dialogues_dev5/`` played as
  ``bench/composition_gate.py`` plays it (``tests/language/w5_fluency.py``'s runner): first every
  reply a round-6 plan said (at most 5), then one reply of each act not yet in the sample, then
  replies drawn with a fixed seed until 10.

Every reply kept was composed (its realizer report realized and not held). Writes
``marco/language/measurements/fluency-sample-6.md`` with an empty judgement column: fluency is
judged by a person, not counted. The frozen sets are never read.
"""
import os
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[2]
SEED = 20260928
DATASET = "data/benchmarks/dialogues_dev5"
OUT = ROOT / "marco/language/measurements/fluency-sample-6.md"
WHY_PER_LANGUAGE, OTHER_PER_LANGUAGE, ROUND6 = 10, 10, 5
CODES = {"한국어": "ko", "english": "en"}
ACTS = ("answer", "record", "hold", "correct", "ask", "explain")
# The plans round 6 declared (marco/language/realizer/meaning.json), by their match.
ROUND6_PLANS = (
    {"act": "hold", "reason": "unread_event", "fields": {"kept": True}},
    {"act": "hold", "reason": "vague_count", "fields_has": "at_least"},
    {"act": "hold", "reason": "unresolved", "fields": {"differs": True}, "fields_has": "about"},
    {"act": "ask", "reason": "which_referent", "fields_number": "word"},
    {"act": "explain", "kind": "answer", "fields_has": "about"},
    {"act": "explain", "kind": "chain", "fields_has": "about"},
)


def round6(report):
    plan = (report or {}).get("plan")
    return plan in ROUND6_PLANS or (plan == {"act": "hold", "reason": "reference_which_event"})


def why_rows(language):
    """The last reply of each check-half why case, with its realizer report."""
    import marco.language.realizer as realizer
    sys.path.insert(0, str(ROOT / "tests"))
    import test_r6_why_fact as why
    rows = []
    for name, lines, expected in why.cases_of(language, "check"):
        if (language, name) in why.CHECK_UNREAD:
            continue
        current, row = why.context(language), None
        for line in lines:
            if line is why.RESTART:
                import json
                fresh = why.context(language)
                fresh.restore(json.loads(json.dumps(current.snapshot(), ensure_ascii=False)))
                current = fresh
                continue
            row = current.turn(line) or {}
        report = realizer.last_report() or {}
        if not report.get("realized") or report.get("held"):
            raise AssertionError("not composed: %s %s %r" % (language, name, row.get("answer")))
        rows.append({"case": name, "kind": expected[0], "say": lines[-1], "text": row.get("answer"),
                     "report": report, "language": CODES[language]})
    explained = [row for row in rows if row["kind"] == "explain"]
    others = [row for row in rows if row["kind"] != "explain"]
    keep = others[:WHY_PER_LANGUAGE]
    keep = explained[:WHY_PER_LANGUAGE - len(keep)] + keep
    return keep


def other_rows(seed=SEED):
    sys.path.insert(0, str(ROOT / "bench"))
    sys.path.insert(0, str(ROOT / "tests" / "language"))
    import dialogue_gate as gate
    import w5_fluency
    dialogues = [d for d in gate.load(ROOT / DATASET) if (d.get("variation") or {}).get("half") == "check"]
    report, rows = w5_fluency.play(dialogues)
    chooser = random.Random(seed)
    chosen = {}
    for code in CODES.values():
        pool = [row for row in rows if row["bucket"] == "composed" and row["language"] == code]
        new = [row for row in pool if round6(row["report"])][:ROUND6]
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
        taken += rest[:OTHER_PER_LANGUAGE - len(taken)]
        order = {row["turn"]: index for index, row in enumerate(rows)}
        chosen[code] = sorted(taken, key=lambda row: order[row["turn"]])
    return report, dialogues, chosen


def table(why, report, dialogues, chosen):
    def cell(text):
        return str(text).replace("|", "\\|").replace("\n", " ")
    lines = ["# Fluency sample 6 — for the owner to judge", "",
             "Goal W6.5. 40 replies, 20 per language; 20 of them why answers.", "",
             "Why answers (10 per language): the check half of goal G6's why-with-a-restated-fact cases "
             "(`tests/test_r6_why_fact.py`; names, things and amounts no fix saw), each dialogue played through "
             "`ReasoningContext.turn`, its last reply kept: the explained cases, then every counterexample (a "
             "number that is not the count, a count before a correction, a pointer to two holders, a thing not "
             "settled, nothing answered yet). The explained ones say the holder's count first (W6.3); a number "
             "that is not the count is said as the recorded count and denied (request G6-3 item 1); a number "
             "no holder was named for asks whose count it is (item 3).", "",
             "Other replies (10 per language): the check half of `%s/` (%d dialogues whose `variation.half` "
             "is `check`), played through `AppState.turn` as `bench/composition_gate.py` plays it; composed %d "
             "of %d spoken replies (held %d, passed through %d). First every reply a round-6 plan said (marked "
             "*round 6*), at most %d; then one reply of each act not yet in the sample; then replies drawn at "
             "random (seed %d)." % (DATASET, len(dialogues), report["total"]["composed"],
                                   report["total"]["spoken"], report["total"]["held"],
                                   report["total"]["passed_through"], ROUND6, SEED), "",
             "Every reply here was composed by the realizer. The judgement column is empty on purpose: fluency "
             "is judged by a person, not counted.", "",
             "Regenerate: `KG_ENCODER=문자 python tests/language/w6_fluency.py`.", "",
             "| # | language | source | act | round 6 | input | composed reply | judgement |",
             "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    n = 0
    for code in CODES.values():
        for row in why[code]:
            n += 1
            lines.append("| %d | %s | why: %s | %s | %s | %s | %s | |" % (
                n, code, row["case"], row["report"].get("plan", {}).get("act", ""),
                "round 6" if round6(row["report"]) else "", cell(row["say"]), cell(row["text"])))
        for row in chosen[code]:
            n += 1
            lines.append("| %d | %s | %s | %s | %s | %s | %s | |" % (
                n, code, row["turn"], row["act"], "round 6" if round6(row["report"]) else "", cell(row["say"]),
                cell(row["report"].get("text") or row["composed_text"])))
    return "\n".join(lines) + "\n"


def main():
    os.environ.setdefault("KG_ENCODER", "문자")
    sys.path.insert(0, str(ROOT))
    why = {CODES[language]: why_rows(language) for language in CODES}
    report, dialogues, chosen = other_rows()
    assert all(len(why[c]) == WHY_PER_LANGUAGE and len(chosen[c]) == OTHER_PER_LANGUAGE for c in CODES.values()), \
        ({c: len(v) for c, v in why.items()}, {c: len(v) for c, v in chosen.items()})
    OUT.write_text(table(why, report, dialogues, chosen), encoding="utf-8")
    print("wrote", OUT.relative_to(ROOT), "; round 6 why:", {c: sum(round6(r["report"]) for r in why[c]) for c in why},
          "; round 6 dev5:", {c: sum(round6(r["report"]) for r in chosen[c]) for c in chosen})


if __name__ == "__main__":
    main()
