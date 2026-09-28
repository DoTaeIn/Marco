"""MARCO 1 composition gate: every spoken reply composed, never picked (goal F2, gate condition 5).

Plays any dialogue directory in the dialogue-gate format through the dialogue
gate's own runner (``bench/dialogue_gate.py`` ``run``: ``AppState.turn``, the
call behind the UI's ``POST /api/turn``, research stubbed, ``restart_before``
honoured) and, after each reply, reads the realizer's per-reply report
(``marco.language.realizer.last_report()``).  Nothing in the engine or the
realizer changes; the run only watches.

Each spoken reply is counted once:

  composed        the realizer composed the sentence from a meaning
                  (``realized`` and not ``held``) and the reply the UI returned
                  is that sentence -- nothing outside it.  A quoted graph node or
                  user sentence counts only inside a composed sentence: a
                  reply whose composed text is nothing but quotation, or that
                  carries text outside the composed sentence, is not composed.
  passed_through  anything else that was said: the realizer passed the engine's
                  sentence through (``realized`` false, with its reason), the
                  turn never reached the realizer, or the reply differs from
                  what the realizer composed.
  held            the realizer found no declared expression that kept the
                  meaning and said the declared hold instead.

Counted per act (answer, hold, record, explain, ask, correct -- from the engine
result's ``meaning.act``, else its status) and per language (the reply's
language as the realizer reports it, else the dialogue's).  Execution errors are
not spoken replies; they are counted apart.

Sources (at least one; there is no default, so no development run touches the
frozen dialogues by accident):

  --dataset DIR     any dialogue directory in the dialogue-gate format
                    (the owner: ``--dataset data/benchmarks/dialogues_v1``)
  --seven-step      the fixed 7-step dialogue in both languages, as
                    ``bench/seven_step_ui.py`` plays it (10 turns each)
  --phrasings [F]   the 20 phrasings of ``data/benchmarks/unseen_phrasing_v1.json``
                    (``docs/ko/repair-and-english-2026-09-22/unseen-before.json``)
  --reasoning [D]   the reasoning set (``data/benchmarks/reasoning_v1``), each
                    problem played as one dialogue in its play order
"""
import argparse
import collections
import contextlib
import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "bench") not in sys.path:
    sys.path.insert(0, str(ROOT / "bench"))
import dialogue_gate as gate  # noqa: E402

ACTS = ("answer", "hold", "record", "explain", "ask", "correct")
BUCKETS = ("composed", "passed_through", "held")
MEANING_ACTS = {"inform": "answer", "answer": "answer", "refuse": "hold", "hold": "hold", "record": "record",
                "explain": "explain", "ask": "ask", "correct": "correct", "revise": "correct"}
STATUS_ACTS = {"answered": "answer", "observed": "record", "unresolved": "hold"}
PAYLOAD_ACTS = {"answered": "answer", "observed": "record", "held": "hold", "chat": "answer", "unknown": "hold"}
STEMS = {"한국어": "ko", "english": "en"}
PHRASINGS = ROOT / "data/benchmarks/unseen_phrasing_v1.json"
_EDGE = " \t\r\n.!?。…,;:"


# ---------------------------------------------------------------------------
# fixed dialogue sets in the dialogue-gate shape
# ---------------------------------------------------------------------------
def seven_step_dialogues():
    """The §12 dialogue per language as ``bench/seven_step_ui.py`` plays it: 7 turns, the other
    language's question, then a restart from the saved conversation and both questions again."""
    import seven_step_dialogue
    out = []
    for style, code in (("한국어", "ko"), ("english", "en")):
        script = seven_step_dialogue.SCRIPTS[style]
        other = "en" if code == "ko" else "ko"
        turns = [{"say": text} for text in script["turns"]]
        turns += [{"say": script["other_question"], "lang": other},
                  {"say": script["same_question"], "restart_before": True},
                  {"say": script["other_question"], "lang": other}]
        for n, turn in enumerate(turns, 1):
            turn["n"] = n
        out.append({"id": "seven-step-%s" % code, "language": code, "turns": turns})
    return out


def phrasing_dialogues(path=PHRASINGS):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [{"id": "phrasing-" + case["id"], "language": STEMS[case["language"]],
             "turns": [{"n": n, "say": text} for n, text in enumerate(case["turns"], 1)]}
            for case in data["cases"]]


# ---------------------------------------------------------------------------
# classification (pure)
# ---------------------------------------------------------------------------
def _same(a, b):
    return re.sub(r"\s+", " ", a or "").strip() == re.sub(r"\s+", " ", b or "").strip()


def classify(spoken, report):
    """(bucket, reason) for one spoken reply and the realizer report made during its turn (or None)."""
    if report is None:
        return "passed_through", "no_realizer_report"
    if not report.get("realized"):
        return "passed_through", "realizer:%s" % (report.get("reason") or "not_realized")
    if report.get("held"):
        return "held", "realizer_hold"
    composed = report.get("text") or ""
    if not re.search(r"\w", gate.asserted(composed)):
        return "passed_through", "quotation_only"
    if _same(spoken, composed):
        return "composed", "composed"
    text = re.sub(r"\s+", " ", spoken or "").strip()
    inner = re.sub(r"\s+", " ", composed).strip()
    if inner and inner in text and not text.replace(inner, "", 1).strip(_EDGE):
        return "composed", "composed"
    if inner and inner in text:
        return "passed_through", "text_outside_composed_sentence"
    return "passed_through", "spoken_differs_from_composed"


def report_of(obs):
    """The realizer report recorded for one observed turn, or None when the turn made none."""
    c = obs.get("composition") or {}
    if c.get("realized") is None:
        return None
    return {"realized": c["realized"], "held": c.get("held"), "reason": c.get("reason"), "text": c.get("text")}


def act_of(meaning, status, payload_status):
    if isinstance(meaning, dict) and MEANING_ACTS.get(meaning.get("act")):
        return MEANING_ACTS[meaning["act"]]
    if status in STATUS_ACTS:
        return STATUS_ACTS[status]
    return PAYLOAD_ACTS.get(payload_status, "hold")


# ---------------------------------------------------------------------------
# run: the dialogue gate's runner, watched
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def watching(code_root=ROOT):
    """Watch each AppState.turn: the realizer reports made during it and the engine result's act.

    Yields the list the dialogue gate's ``observe`` fills: one composition
    record per observed turn.  Nothing is changed in the engine or realizer.
    """
    gate._import_code(code_root)
    from views.kgpack_ui import AppState
    from marco.reasoning.context import ReasoningContext
    import marco.language.realizer as realizer
    pending, results = {}, []
    original_turn, original_context_turn, original_observe = AppState.turn, ReasoningContext.turn, gate.observe

    def turn(self, *args, **kwargs):
        pending.clear()
        reports = realizer.default_realizer().reports
        marker = reports[-1] if reports else None
        pending["engine"] = []
        try:
            return original_turn(self, *args, **kwargs)
        finally:
            fresh = []
            for entry in reversed(reports):
                if entry is marker:
                    break
                fresh.append(entry)
            pending["reports"] = len(fresh)
            pending["report"] = realizer.last_report() if fresh else None

    def context_turn(self, *args, **kwargs):
        result = original_context_turn(self, *args, **kwargs)
        if isinstance(result, dict) and "engine" in pending:
            meaning = result.get("meaning") if isinstance(result.get("meaning"), dict) else None
            pending["engine"].append({"status": result.get("status"),
                                      "act": (meaning or {}).get("act"), "reason": (meaning or {}).get("reason")})
        return result

    def observe(result, research_calls, elapsed_ms):
        row = original_observe(result, research_calls, elapsed_ms)
        engine = (pending.get("engine") or [None])[-1] or {}
        report = pending.get("report")
        row["composition"] = {
            "reports": pending.get("reports", 0),
            "realized": None if report is None else bool(report.get("realized")),
            "held": None if report is None else bool(report.get("held")),
            "reason": None if report is None else report.get("reason"),
            "language": None if report is None else report.get("language"),
            "acts": None if report is None else report.get("acts"),
            "text": None if report is None else report.get("text"),
            "engine_status": engine.get("status"), "engine_act": engine.get("act"),
            "engine_reason": engine.get("reason")}
        results.append(row["composition"])
        return row

    AppState.turn, ReasoningContext.turn, gate.observe = turn, context_turn, observe
    try:
        yield results
    finally:
        AppState.turn, ReasoningContext.turn, gate.observe = original_turn, original_context_turn, original_observe


def run(dialogues, code_root=ROOT, progress=None):
    """{dialogue id: [observation per turn, each with its ``composition`` record]}."""
    with watching(code_root):
        return gate.run(dialogues, code_root, progress)


def score(dialogues, answers, meta=None):
    rows, errors = [], []
    for d in dialogues:
        got = answers.get(d["id"]) or []
        for index, t in enumerate(d["turns"]):
            obs = got[index] if index < len(got) else {"error": "no observation recorded"}
            where = "%s#%d" % (d["id"], t["n"])
            if obs.get("error"):
                errors.append({"turn": where, "error": obs["error"]})
                continue
            c = obs.get("composition") or {}
            spoken = obs.get("answer") or ""
            bucket, reason = classify(spoken, report_of(obs))
            language = STEMS.get(c.get("language")) or t.get("lang") or d["language"]
            act = act_of({"act": c.get("engine_act")}, c.get("engine_status"), gate.status(obs))
            rows.append({"turn": where, "say": t["say"], "language": language, "act": act, "bucket": bucket,
                         "reason": reason, "spoken": spoken[:300], "composed_text": (c.get("text") or "")[:300],
                         "reports": c.get("reports"), "realizer_acts": c.get("acts")})

    def counts(chosen):
        out = {b: sum(r["bucket"] == b for r in chosen) for b in BUCKETS}
        out["spoken"] = len(chosen)
        return out
    total = counts(rows)
    return {"schema": "marco1-composition-gate-v1-report", "meta": meta or {},
            "dialogues": len(dialogues), "turns": sum(len(d["turns"]) for d in dialogues),
            "total": dict(total, denominator="every reply the UI returned for a dialogue turn (%d); execution "
                                             "errors are not spoken replies and are listed apart (%d)" % (
                                                 total["spoken"], len(errors))),
            "by_act": {a: counts([r for r in rows if r["act"] == a]) for a in ACTS},
            "by_language": {c: counts([r for r in rows if r["language"] == c]) for c in STEMS.values()},
            "reasons": dict(collections.Counter(r["reason"] for r in rows if r["bucket"] != "composed")
                            .most_common()),
            "execution_errors": errors,
            "not_composed": [r for r in rows if r["bucket"] != "composed"],
            "rows": rows}


def format_report(report):
    t = report["total"]
    lines = ["composed %d / %d spoken replies  (passed through %d, held %d; execution errors %d)" % (
        t["composed"], t["spoken"], t["passed_through"], t["held"], len(report["execution_errors"])),
        "denominator: " + t["denominator"], "",
        "%-10s %8s %9s %14s %6s" % ("act", "spoken", "composed", "passed_through", "held")]
    for name, c in report["by_act"].items():
        lines.append("%-10s %8d %9d %14d %6d" % (name, c["spoken"], c["composed"], c["passed_through"], c["held"]))
    for name, c in report["by_language"].items():
        lines.append("%-10s %8d %9d %14d %6d" % ("lang " + name, c["spoken"], c["composed"], c["passed_through"],
                                                c["held"]))
    lines += ["", "not composed, by reason: %s" % json.dumps(report["reasons"], ensure_ascii=False)]
    for r in report["not_composed"][:40]:
        lines.append("  %-22s %-8s %-15s %s" % (r["turn"], r["act"], r["bucket"], r["reason"]))
    if len(report["not_composed"]) > 40:
        lines.append("  ... %d more in the JSON report" % (len(report["not_composed"]) - 40))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--dataset", type=Path, help="dialogue directory in the dialogue-gate format")
    parser.add_argument("--seven-step", action="store_true", help="the fixed 7-step dialogue, both languages")
    parser.add_argument("--phrasings", nargs="?", const=PHRASINGS, type=Path,
                        help="the 20 unseen phrasings (default file: data/benchmarks/unseen_phrasing_v1.json)")
    parser.add_argument("--reasoning", nargs="?", const=ROOT / "data/benchmarks/reasoning_v1", type=Path,
                        help="the reasoning set, one dialogue per problem (default: data/benchmarks/reasoning_v1)")
    parser.add_argument("--code-root", default=str(ROOT))
    parser.add_argument("--report-out", type=Path)
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(argv)
    dialogues = []
    if args.dataset:
        dialogues += gate.load(args.dataset.resolve())
    if args.seven_step:
        dialogues += seven_step_dialogues()
    if args.phrasings:
        dialogues += phrasing_dialogues(args.phrasings)
    if args.reasoning:
        import reasoning_gate
        dialogues += reasoning_gate.as_dialogues(reasoning_gate.load(args.reasoning))
    if not dialogues:
        parser.error("give --dataset DIR, --seven-step, --phrasings and/or --reasoning")
    os.environ.setdefault("KG_ENCODER", "문자")
    start = time.perf_counter()
    progress = None if args.quiet else (lambda did, rows: print(did, "".join(
        "E" if r.get("error") else classify(r.get("answer") or "", report_of(r))[0][0] for r in rows), flush=True))
    answers = run(dialogues, args.code_root, progress)
    meta = {"sources": [str(source) for source in (args.dataset, "seven_step" if args.seven_step else None,
                                                   args.phrasings, args.reasoning) if source],
            "entry": "views.kgpack_ui.AppState.turn", "report": "marco.language.realizer.last_report()",
            "encoder": os.environ.get("KG_ENCODER"), "seconds": round(time.perf_counter() - start, 1)}
    try:
        meta["code_commit"] = gate._git("rev-parse", "HEAD") if Path(args.code_root).resolve() == ROOT else None
    except Exception:  # noqa: BLE001 -- a missing git is not a scoring failure
        meta["code_commit"] = None
    report = score(dialogues, answers, meta)
    if args.report_out:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(json.dumps(report, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(format_report(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
