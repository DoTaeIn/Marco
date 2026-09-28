"""The seven-step dialogue of 2026-09-22-mco-integrated-roadmap.md §12, checked.

Each step is checked on structure, not on wording: the recorded state, the
status, whether a new event was appended, which rules and statements an
explanation cites, and that a hold stays a hold. The same checks run for the
Korean and the English pack; step 7 asks in the *other* language of the same
pack set and again after a restart from a snapshot.

``run(language, models=None)`` takes optional in-memory models so a caller can
inject a faulty pack (see ``bench/error_injection.py``) and see which steps
catch it.
"""
import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCRIPTS = {
    "english": {
        "turns": ["Minsu has five apples, and Jiyeon has two.",
                  "Minsu gave Jiyeon two.",
                  "How many does Jiyeon have now?",
                  "Where is that person?",
                  "Actually, the one given was one, not two.",
                  "Why did that happen?",
                  "What about the other person, not that one?"],
        "other_question": "지연은 지금 몇 개야?",
        "same_question": "How many apples does Jiyeon have now?",
        "giver": "Minsu apples", "taker": "Jiyeon apples", "names": ("Minsu", "Jiyeon"),
    },
    "한국어": {
        "turns": ["민수는 사과 다섯 개, 지연은 두 개가 있어.",
                  "민수가 지연에게 두 개 줬어.",
                  "지연은 지금 몇 개야?",
                  "그 사람은 어디 있어?",
                  "아까 준 건 두 개가 아니라 한 개야.",
                  "왜 그렇게 됐어?",
                  "그 사람 말고 다른 사람은?"],
        "other_question": "How many apples does Jiyeon have now?",
        "same_question": "지연은 지금 몇 개야?",
        "giver": "민수 사과", "taker": "지연 사과", "names": ("민수", "지연"),
    },
}


def _numbers(text):
    return re.findall(r"(?<![\d.])\d+(?!\d|\.\d)", text or "")


def _state(context):
    from marco.reasoning.inference import current_facts
    parser = context._parser()
    facts, _d, _p, _r = context._cached_replay(parser, context.observations, context.fills)
    state, _changes = current_facts(facts, parser.data.get("mutable_predicates", []),
                                    parser.data.get("numeric_updates", {}))
    return {row["triple"][0]: row["triple"][2] for row in state if row["triple"][1] == "count"}


def run(language, models=None):
    from pack_model import development_model
    from marco.reasoning.context import ReasoningContext
    script = SCRIPTS[language]
    other = "english" if language == "한국어" else "한국어"
    models = models or {}
    model = models.get(language) or development_model(language)
    companion = models.get(other) or development_model(other)
    context = ReasoningContext(model=model, companions=[companion])
    giver, taker = script["giver"], script["taker"]
    steps, replies = [], []

    def turn(text):
        try:
            result = context.turn(text) or {}
        except Exception as exc:  # an execution error is a failed step, never a hold
            result = {"status": "error", "answer": "%s: %s" % (type(exc).__name__, exc)}
        replies.append({"input": text, "status": result.get("status"), "answer": result.get("answer")})
        return result

    def check(step, ok, detail):
        steps.append({"step": step, "ok": bool(ok), "detail": detail})

    t = script["turns"]
    r1 = turn(t[0])
    check(1, r1.get("status") == "observed" and _state(context) == {giver: "5", taker: "2"},
          {"state": _state(context)})
    r2 = turn(t[1])
    moved = [row for row in r2.get("transitions", []) if row.get("operation") == "quantity_update"
             and (row.get("evidence") or {}).get("turn") == 1]
    check(2, r2.get("status") == "observed" and _state(context) == {giver: "3", taker: "4"}
          and {(row["subject"], row["delta"]) for row in moved} == {(giver, -2), (taker, 2)},
          {"state": _state(context), "effects": [(row["subject"], row["delta"]) for row in moved]})
    r3 = turn(t[2])
    r3b = turn(t[3])
    check(3, r3.get("status") == "answered" and _numbers(r3.get("answer")) == ["4"]
          and r3b.get("status") != "answered" and script["names"][1] in (r3b.get("answer") or ""),
          {"count": r3.get("answer"), "where": r3b.get("answer")})
    observations_before = len(context.observations)
    r4 = turn(t[4])
    check(4, r4.get("status") == "observed" and _state(context) == {giver: "4", taker: "3"}
          and len(context.observations) == observations_before and len(context.corrections) == 1,
          {"state": _state(context), "observations": len(context.observations),
           "corrections": len(context.corrections)})
    r5 = turn(t[5])
    answer5 = r5.get("answer") or ""
    # The rules the explanation used are in its meaning (the trace); the reply says them in words.
    check(5, r5.get("status") == "answered" and t[4] in answer5
          and {"count_remove", "count_add"} <= set((r5.get("meaning") or {}).get("rules") or [])
          and all(source.strip() in answer5 for source in context.observations),
          {"answer": answer5})
    state_before = _state(context)
    r6 = turn(t[6])
    check(6, r6.get("status") != "answered" and all(name in (r6.get("answer") or "")
                                                     for name in script["names"])
          and _state(context) == state_before, {"answer": r6.get("answer")})
    r7 = turn(script["other_question"])
    snapshot = json.loads(json.dumps(context.snapshot(), ensure_ascii=False))
    context = ReasoningContext(model=model, companions=[companion])
    context.restore(snapshot)
    r7b = turn(script["same_question"])
    r7c = turn(script["other_question"])
    sources = lambda r: sorted({(row.get("evidence") or {}).get("source") for row in r.get("transitions", [])
                                if (row.get("evidence") or {}).get("source")})
    check(7, all(r.get("status") == "answered" and _numbers(r.get("answer")) == ["3"] for r in (r7, r7b, r7c))
          and sources(r7) == sources(r7b) == sources(r7c) and sources(r7),
          {"other": r7.get("answer"), "restart_same": r7b.get("answer"), "restart_other": r7c.get("answer"),
           "evidence_sources": sources(r7)})
    return {"language": language, "passed": sum(s["ok"] for s in steps), "total": len(steps),
            "steps": steps, "replies": replies}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    args = parser.parse_args()
    reports = [run(language) for language in ("english", "한국어")]
    if args.out:
        Path(args.out).write_text(json.dumps(reports, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for report in reports:
        print(report["language"], "%d/%d" % (report["passed"], report["total"]),
              [s["step"] for s in report["steps"] if not s["ok"]])
