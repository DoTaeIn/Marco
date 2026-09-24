"""Reading accuracy per sentence against the gold scenario (goal G5.4), and agreement across surface variants.

Every dialogue of dev sets v4 and v5 was phrased from a scenario whose statements are structured events
(``expect.events``: has, transfer, use) and whose corrections name the state after them
(``expect.state``). This plays each dialogue through a ``ReasoningContext`` (the development packs, the
other language as companion, as the tests do) and reads, for each statement turn, what the turn itself
changed (the transitions whose evidence is this turn's observation), in context:

* ``correct``: every gold event is there -- a has as the holder's count after the turn; a transfer as the
  giver's change of minus the amount and the receiver's of plus the amount; a use as the holder's change
  of minus the amount; a count said vaguely as a count not known -- and no other holder changed;
* ``wrong``: the turn was recorded, but not as the gold events (another holder, another amount, a
  direction reversed, a change nobody made);
* ``ask`` / ``hold``: the turn was not recorded; the context asked (several readings, a referent) or held.

A correction turn is read against the state its scenario says follows it (``expect.state``). The reading
of a turn is the set of (holder, item, change) rows it recorded, so the three phrasings of one scenario
(``triples.txt``) can be compared: a scenario agrees when, turn by turn, all three gave the same reading.

    python data/benchmarks/dialogues_dev5/readings.py data/benchmarks/dialogues_dev4 --split check [--out f.json]
    python data/benchmarks/dialogues_dev5/readings.py data/benchmarks/dialogues_dev5 --triples
"""
import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("KG_ENCODER", "문자")
LANGUAGES = {"ko": "한국어", "en": "english"}
_MODELS = {}


def _model(name):
    if name not in _MODELS:
        from pack_model import development_model
        _MODELS[name] = development_model(name)
    return _MODELS[name]


def _mentions(subject, name):
    subject, name = str(subject).lower(), str(name).lower()
    if re.fullmatch(r"[a-z .'-]+", name):
        return re.search(r"(?<![a-z])%s(?![a-z])" % re.escape(name), subject) is not None
    return name in subject


def _stem(item):
    word = str(item).lower().split()[-1]
    return word[:4] if re.fullmatch(r"[a-z]+", word) else word


def _row_of(subject, holders, item):
    """The gold holder a recorded subject names (the longest name it contains), when it names the item."""
    if _stem(item) not in str(subject).lower():
        return None
    named = [h for h in holders if _mentions(subject, h)]
    return max(named, key=len) if named else None


def _number(value):
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def classify(turn, result, index, holders):
    """(outcome, reading): outcome correct / wrong / ask / hold; reading a sorted tuple of what it changed."""
    expect = turn["expect"]
    status = (result or {}).get("status")
    if result is None or status != "observed":
        act = ((result or {}).get("meaning") or {}).get("act")
        return ("ask" if act == "ask" else "hold"), None
    rows = [r for r in result.get("transitions") or [] if r.get("operation") in ("state_update", "quantity_update")]
    if expect["act"] == "revise":
        state = {}
        for r in rows:
            state[str(r.get("subject"))] = r.get("after")
        reading = tuple(sorted((str(s), str(v)) for s, v in state.items()))
        # (a holder the correction did not change is not in its rows: only the rows it gives are checked)
        for gold in expect["state"]:
            subject = next((s for s in state if _row_of(s, holders, gold["item"]) == gold["entity"]), None)
            if subject is not None and _number(state[subject]) != gold["quantity"]:
                return "wrong", reading
        return "correct", reading
    mine = [r for r in rows if (r.get("evidence") or {}).get("turn") == index]
    reading = tuple(sorted((str(r.get("subject")), str(r.get("predicate")), str(r.get("before")), str(r.get("after")))
                           for r in mine))
    wanted = {}
    for ev in expect["events"]:
        if ev["type"] == "has":
            wanted[(ev["holder"], ev["item"])] = ("after", ev["quantity"])
        elif ev["type"] == "use":
            wanted[(ev["holder"], ev["item"])] = ("delta", -ev["quantity"])
        else:
            wanted[(ev["from"], ev["item"])] = ("delta", -ev["quantity"])
            wanted[(ev["to"], ev["item"])] = ("delta", ev["quantity"])
    got = {}
    for r in mine:
        for (holder, item) in wanted:
            if _row_of(r.get("subject"), holders, item) == holder:
                got[(holder, item)] = r
                break
        else:
            return "wrong", reading                  # a change nobody made in the scenario
    for key, (kind, value) in wanted.items():
        row = got.get(key)
        if kind == "after" and value is None:
            # a count said vaguely is recorded as a count not known, which changes no count: no row is right,
            # a row with a count is not
            if row is not None and _number(row.get("after")) is not None:
                return "wrong", reading
            continue
        if row is None:
            return "wrong", reading
        if kind == "after":
            if _number(row.get("after")) != value:
                return "wrong", reading
        else:
            before, after = _number(row.get("before")), _number(row.get("after"))
            delta = row.get("delta")
            delta = _number(delta) if delta is not None else (after - before if None not in (before, after) else None)
            if delta != value:
                return "wrong", reading
    return "correct", reading


def play(dialogue):
    """[(turn, outcome, reading)] for the statement and correction turns of one dialogue."""
    from reasoning_context import ReasoningContext
    name = LANGUAGES[dialogue["language"]]
    other = "english" if name == "한국어" else "한국어"
    context = ReasoningContext(model=_model(name), companions=[_model(other)])
    holders = sorted({h for t in dialogue["turns"] for ev in (t["expect"].get("events") or [])
                      for h in (ev.get("holder"), ev.get("from"), ev.get("to")) if h}
                     | {row["entity"] for t in dialogue["turns"] for row in t["expect"].get("state") or []},
                     key=len, reverse=True)
    out = []
    for turn in dialogue["turns"]:
        before = len(context.observations)
        try:
            result = context.turn(turn["say"])
        except Exception as exc:     # noqa: BLE001 -- an execution error is its own outcome
            result = {"status": "error", "meaning": {"act": "error", "reason": type(exc).__name__}}
        if turn["expect"]["act"] in ("record", "revise"):
            index = len(context.observations) - 1 if len(context.observations) > before else before
            outcome, reading = classify(turn, result, index, holders)
            out.append((turn["n"], outcome, reading))
    return out


def load(dataset, split=None):
    from bench import dialogue_gate as gate
    from marco.trace.drive import guard
    guard(dataset)
    return gate.load(Path(dataset), split)


def measure(dataset, split=None):
    rows = {}
    for d in load(dataset, split):
        rows[d["id"]] = {"language": d["language"], "turns": play(d)}
    return rows


def summary(rows):
    out = {}
    for did, row in rows.items():
        for key in ("all", row["language"]):
            c = out.setdefault(key, Counter())
            for _n, outcome, _reading in row["turns"]:
                c[outcome] += 1
                c["n"] += 1
    return {k: dict(v) for k, v in out.items()}


def agreement(rows, triples_path):
    """Per triple: all three phrasings gave the same reading, turn by turn; and the same and correct."""
    same = correct = total = 0
    by_lang = Counter()
    for line in Path(triples_path).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) != 4 or not all(p in rows for p in parts[1:]):
            continue
        plays = [rows[p]["turns"] for p in parts[1:]]
        total += 1
        lang = rows[parts[1]]["language"]
        by_lang[lang + "_n"] += 1
        if len({len(p) for p in plays}) == 1 and all(
                len({(o if o in ("ask", "hold") else "read", r) for _n, o, r in column}) == 1
                for column in zip(*plays)):
            same += 1
            by_lang[lang + "_same"] += 1
            if all(o == "correct" for p in plays for _n, o, _r in p):
                correct += 1
                by_lang[lang + "_same_correct"] += 1
    return {"triples": total, "same_reading": same, "same_and_correct": correct, **dict(by_lang)}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("--split")
    parser.add_argument("--triples", action="store_true", help="also the agreement across each triple's phrasings")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    rows = measure(args.dataset, args.split)
    result = {"dataset": str(args.dataset), "split": args.split, "summary": summary(rows)}
    if args.triples:
        result["agreement"] = agreement(rows, args.dataset / "triples.txt")
    if args.out:
        args.out.write_text(json.dumps({**result, "rows": rows}, ensure_ascii=False) + "\n", encoding="utf-8")
    for key, c in result["summary"].items():
        print("%-4s n %4d  correct %4d (%.1f%%)  wrong %3d  ask %3d  hold %3d" % (
            key, c.get("n", 0), c.get("correct", 0), 100.0 * c.get("correct", 0) / max(c.get("n", 1), 1),
            c.get("wrong", 0), c.get("ask", 0), c.get("hold", 0)))
    if args.triples:
        print("agreement", json.dumps(result["agreement"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
