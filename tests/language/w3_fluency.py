"""W3.6: fluency sample 3 — 40 composed replies for the owner to judge, 20 per language.

    KG_ENCODER=문자 python tests/language/w3_fluency.py [--dataset data/benchmarks/dialogues_dev4]

Per language, two parts:

* 12 replies drawn at random (seed 20260924) from the replies the realizer composed on
  a development set (``data/benchmarks/dialogues_dev3/`` unless another is given),
  played through the composition gate's runner (the UI's ``AppState.turn``);
* 8 replies of the kinds round 3 adds, one each: fewer, a tie, the same number,
  different numbers, before and after an event or one of a thing (played as
  dialogues through ``ReasoningContext.turn``), a vague count and the user as a holder
  (round-4 plans, realized from the meaning blocks request ``docs/requests/W3-1.md``
  asks for, with the pack as it is).

Writes ``marco/language/measurements/fluency-sample-3.md`` with an empty judgement
column: fluency is judged by a person, not counted. Every reply in it was composed.
"""
import argparse
import os
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[2]
SEED = 20260924
FROM_SET = 12
OUT = ROOT / "marco/language/measurements/fluency-sample-3.md"
OTHER = {"english": "한국어", "한국어": "english"}
CODE = {"english": "en", "한국어": "ko"}

# Dialogues written for this sample; each keeps the replies named after it.
DIALOGUES = {
    "english": [
        (["Wren has 6 figs.", "Pell has 2 figs.", "Who has fewer figs, Wren or Pell?",
          "Do Wren and Pell have the same number of figs?", "Wren gave Pell 2 figs.",
          "How many figs did Pell have before Wren gave Pell 2 figs?", "Who has more figs, Wren or Pell?",
          "Do Wren and Pell have the same number of figs?"], {2: "fewer", 3: "different", 5: "before", 6: "tie",
                                                               7: "same"}),
        (["Wren has one ladle.", "How many ladles does Wren have?"], {1: "one of a thing"}),
    ],
    "한국어": [
        (["도하는 무화과가 6개 있어.", "세린은 무화과가 2개 있어.", "도하와 세린 중 누가 무화과가 더 적어?",
          "도하와 세린은 무화과가 같아?", "도하가 세린에게 무화과 2개를 줬어.",
          "도하가 세린에게 무화과를 주기 전에 세린은 무화과가 몇 개 있었어?", "도하와 세린 중 누가 무화과가 더 많아?",
          "도하와 세린은 무화과가 같아?", "도하가 세린에게 무화과를 준 뒤에 도하는 무화과가 몇 개 있었어?"],
         {2: "fewer", 3: "different", 5: "before", 6: "tie", 7: "same", 8: "after"}),
    ],
}


def _change(subject, before, after, said):
    return {"operation": "quantity_update", "subject": subject, "predicate": "count", "before": before,
            "after": after, "delta": after - before,
            "evidence": {"start": 0, "end": len(said), "text": said, "turn": 1, "source": said}}


# Round-4 meaning blocks (docs/requests/W3-1.md), with what the user said before them.
MEANINGS = {
    "english": [
        ("vague count", "Sol has some pears.",
         {"status": "observed", "meaning": {"act": "record", "reason": "vague_count", "subject": "Sol pears"}}),
        ("the user", "Who has more plums, me or Sol?",
         {"status": "answered", "transitions": [],
          "meaning": {"act": "inform", "kind": "more", "winner": "I plums", "subjects": ["I plums", "Sol plums"],
                      "values": [5, 3]}}),
    ],
    "한국어": [
        ("vague count", "솔은 배가 좀 있어.",
         {"status": "observed", "meaning": {"act": "record", "reason": "vague_count", "subject": "솔 배"}}),
        ("the user", "내가 솔에게 살구 2개를 줬어.",
         {"status": "observed",
          "meaning": {"act": "record", "reason": "observed_state",
                      "changes": [_change("나 살구", 5, 3, "내가 솔에게 살구 2개를 줬어"),
                                  _change("솔 살구", 1, 3, "내가 솔에게 살구 2개를 줬어")]}}),
    ],
}


def sample(report, answers, dialogues, seed=SEED):
    """``FROM_SET`` composed rows per language, drawn with ``seed``, in dialogue order, each reply whole."""
    whole = {"%s#%d" % (d["id"], t["n"]): (answers[d["id"]][i].get("answer") or "")
             for d in dialogues for i, t in enumerate(d["turns"]) if i < len(answers.get(d["id"]) or [])}
    chooser = random.Random(seed)
    chosen = {}
    for code in ("ko", "en"):
        rows = [row for row in report["rows"] if row["bucket"] == "composed" and row["language"] == code]
        picked = sorted(chooser.sample(rows, FROM_SET), key=lambda row: report["rows"].index(row))
        chosen[code] = [dict(row, spoken=whole.get(row["turn"], row["spoken"])) for row in picked]
    return chosen


def new_kinds(language):
    """The round-3 and round-4 kinds, one reply each, every one composed."""
    from marco.language.realizer import Realizer, last_report
    from pack_model import development_model
    from reasoning_context import ReasoningContext
    rows = []
    for lines, keep in DIALOGUES[language]:
        context = ReasoningContext(model=development_model(language), companions=[development_model(OTHER[language])])
        for index, line in enumerate(lines):
            result = context.turn(line)
            report = last_report() or {}
            if index in keep:
                assert result and result["status"] == "answered", (line, result and result.get("answer"))
                assert report.get("realized") and not report.get("held"), (line, report)
                assert report["text"] == result["answer"], line
                rows.append({"turn": keep[index], "act": "answer", "say": line, "spoken": result["answer"]})
    for kind, said, result in MEANINGS[language]:
        text, report = Realizer().realize_with_report(dict(result, answer=""), result["status"],
                                                      "styles/%s.json" % language)
        assert report["realized"] and not report["held"], (kind, report)
        act = "record" if result["meaning"]["act"] == "record" else "answer"
        rows.append({"turn": kind + " (W3-1 meaning)", "act": act, "say": said, "spoken": text})
    return rows


def table(report, chosen, added, dataset, seed=SEED):
    def cell(text):
        return str(text).replace("|", "\\|").replace("\n", " ")
    counted = report["total"]
    lines = ["# Fluency sample 3 — for the owner to judge", "",
             "Goal W3.6. 40 replies, 20 per language. Per language: %d drawn at random (seed %d) from the replies "
             "the realizer composed on `%s` (%d of %d spoken replies composed), played through `AppState.turn` as "
             "`bench/composition_gate.py` plays it; then 8 of the kinds round 3 adds, one each — fewer, a tie, the "
             "same number, different numbers, before and after an event or one of a thing (dialogues written for "
             "this sample, played through `ReasoningContext.turn`), a vague count and the user as a holder "
             "(round-4 meaning blocks as request `docs/requests/W3-1.md` asks for them, the pack as it is). "
             "The judgement column is empty on purpose: fluency is judged by a person, not counted."
             % (FROM_SET, seed, dataset, counted["composed"], counted["spoken"]),
             "", "Regenerate: `KG_ENCODER=문자 python tests/language/w3_fluency.py` "
             "(`--dataset data/benchmarks/dialogues_dev4` once that set is on the branch).", "",
             "| # | language | turn | act | input | composed reply | judgement |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    n = 0
    for code, language in (("ko", "한국어"), ("en", "english")):
        for row in chosen[code] + added[language]:
            n += 1
            lines.append("| %d | %s | %s | %s | %s | %s | |" % (n, code, row["turn"], row["act"], cell(row["say"]),
                                                                cell(row["spoken"])))
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dataset", default="data/benchmarks/dialogues_dev3")
    args = parser.parse_args(argv)
    if "dialogues_v1" in args.dataset or "reasoning_v1" in args.dataset:
        raise SystemExit("the frozen sets are scored by the owner only")
    os.environ.setdefault("KG_ENCODER", "문자")
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "bench"))
    import composition_gate as cg
    import dialogue_gate as gate
    dialogues = gate.load(ROOT / args.dataset)
    answers = cg.run(dialogues)
    report = cg.score(dialogues, answers)
    added = {language: new_kinds(language) for language in ("한국어", "english")}
    assert all(len(rows) == 20 - FROM_SET for rows in added.values()), {k: len(v) for k, v in added.items()}
    OUT.write_text(table(report, sample(report, answers, dialogues), added, args.dataset.rstrip("/") + "/"),
                   encoding="utf-8")
    print("wrote", OUT.relative_to(ROOT), "from", report["total"]["composed"], "composed of",
          report["total"]["spoken"])


if __name__ == "__main__":
    main()
