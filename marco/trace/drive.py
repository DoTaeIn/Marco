"""Play dialogues through the UI turn handler and record every turn (goal L1.3, L1.5, L1.7).

Dialogues run exactly as ``bench/dialogue_gate.py`` runs them (``run``: one
pack per language built with ``kgpack.write_pack``, one ``AppState`` per
dialogue, ``restart_before`` builds a new one over the same conversation
store, web research stubbed and counted). Recording wraps two calls from the
outside, without editing them:

* ``views.kgpack_ui.AppState.turn``: after it returns, ``record_turn`` writes
  the turn's events;
* ``reasoning_context.ReasoningContext.turn`` and ``AppState._said``: the
  context's result and the meaning of a hold the UI says itself are kept,
  because the UI envelope drops the ``meaning`` block (request L1-1).

The realizer's report for the reply is the newest one in
``marco.language.realizer.default_realizer().reports`` if the turn added one.

Recording is off unless a ledger is passed or ``MARCO_TRACE_DIR`` is set: with
neither, ``record`` runs the gate's player untouched.

The frozen exam sets (``data/benchmarks/dialogues_v1/``, ``reasoning_v1/``) are
refused before anything under them is read.

This module imports the engine (lazily); the rest of ``marco.trace`` does not.
"""
import json
import os
from pathlib import Path
import re
import statistics
import tempfile
import time
from unittest.mock import patch

from marco.trace.from_turn import record_turn
from marco.trace.ledger import Ledger, from_env

ROOT = Path(__file__).resolve().parents[2]
FROZEN = ("data/benchmarks/dialogues_v1", "data/benchmarks/reasoning_v1")
CODES = {"ko": "ko", "en": "en", "한국어": "ko", "english": "en"}
STYLES = {"ko": "한국어", "en": "english"}
RESTART = "---restart---"


class FrozenSetRefused(ValueError):
    pass


def guard(path):
    """Refuse a path inside a frozen exam set, before it is opened, listed or even stat-ed.

    The first check is on the path's text alone; the second resolves symbolic links.
    """
    plain = Path(os.path.normpath(os.path.abspath(path)))
    for frozen in FROZEN:
        top = Path(os.path.normpath(ROOT / frozen))
        if plain == top or top in plain.parents:
            raise FrozenSetRefused("%s is a frozen exam set: a development run never reads it" % frozen)
    resolved = plain.resolve()
    for frozen in FROZEN:
        top = ROOT / frozen              # ROOT is resolved; the frozen folder itself is never touched
        if resolved == top or top in resolved.parents:
            raise FrozenSetRefused("%s is a frozen exam set: a development run never reads it" % frozen)
    return resolved


def seven_step(language):
    """The fixed seven-step dialogue as ``bench/seven_step_ui.py`` plays it: the seven turns, the
    question in the other language, a restart from the saved conversation, the question in both."""
    from bench.seven_step_dialogue import SCRIPTS
    code = CODES[language]
    script = SCRIPTS["한국어" if code == "ko" else "english"]
    said = list(script["turns"]) + [script["other_question"]]
    turns = [{"n": i + 1, "say": text} for i, text in enumerate(said)]
    turns.append({"n": len(turns) + 1, "say": script["same_question"], "restart_before": True})
    turns.append({"n": len(turns) + 1, "say": script["other_question"]})
    return {"id": "seven_step_%s" % code, "language": code, "turns": turns}


def load(path, language=None, split=None):
    """Dialogues from a gate-schema JSON file, a directory of them, or a text file.

    A text file holds one turn per line; ``---restart---`` on its own line restarts
    the app before the next turn; ``#`` starts a comment line. It needs ``language``.
    """
    path = guard(path)
    code = CODES[language] if language else None
    if path.is_dir():
        from bench.dialogue_gate import load as gate_load
        dialogues = gate_load(path, split)
    elif path.suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        dialogues = data if isinstance(data, list) else [data]
    else:
        if code is None:
            raise ValueError("a text dialogue needs --language")
        turns, restart = [], False
        for raw in path.read_text(encoding="utf-8").splitlines():
            text = raw.strip()
            if not text or text.startswith("#"):
                continue
            if text == RESTART:
                restart = True
                continue
            turns.append({"n": len(turns) + 1, "say": text, **({"restart_before": True} if restart else {})})
            restart = False
        dialogues = [{"id": re.sub(r"[^A-Za-z0-9_-]", "_", path.stem) or "dialogue", "language": code,
                      "turns": turns}]
    if code:
        dialogues = [d for d in dialogues if d.get("language") == code]
    return dialogues


def _pack_name(app):
    return next((s["path"] for s in getattr(app.model, "sources", ()) if s["path"].startswith("styles/")), None)


def record(dialogues, ledger=None, *, code_root=ROOT, timing=None):
    """Play ``dialogues`` through ``AppState.turn``; record each turn when a ledger is on.

    Returns the gate's per-turn observations ``{dialogue id: [observation]}``
    (``bench.dialogue_gate.run``), so the same run can be scored by the gate.
    ``timing``: a dict that receives the recording's own cost (``record_s``, ``turns``).
    """
    from bench import dialogue_gate
    ledger = ledger if ledger is not None else from_env()
    if ledger is None:
        return dialogue_gate.run(dialogues, code_root)
    os.environ.setdefault("KG_ENCODER", "문자")
    from views.kgpack_ui import AppState
    from reasoning_context import ReasoningContext
    from marco.language.realizer import default_realizer
    by_session = {"dialoguegate_" + re.sub(r"[^A-Za-z0-9_-]", "_", d["id"]): d for d in dialogues}
    # A dialogue played again into the same ledger is another conversation: <id>#2, <id>#3, ...
    taken = {e["payload"].get("conversation") for e in ledger.events if e["kind"] == "input_received"}
    names = {}
    for d in dialogues:
        name, k = d["id"], 2
        while name in taken:
            name, k = "%s#%d" % (d["id"], k), k + 1
        taken.add(name)
        names[d["id"]] = name
    counters, captured, holds = {}, [], []
    app_turn, context_turn, app_said = AppState.turn, ReasoningContext.turn, AppState._said
    timing = timing if timing is not None else {}
    timing.setdefault("record_s", 0.0)
    timing.setdefault("turns", 0)

    def keep_context(self, text, knowledge_path=None):
        result = context_turn(self, text, knowledge_path)
        captured.append(result)
        return result

    def keep_said(self, meaning, text):
        holds.append(meaning)
        return app_said(self, meaning, text)

    def recorded_turn(self, text, session_id, approval_mode="risk", conversation_id=None):
        dialogue = by_session.get(session_id)
        if dialogue is None:
            return app_turn(self, text, session_id, approval_mode, conversation_id)
        n = counters[session_id] = counters.get(session_id, 0) + 1
        expected = dialogue["turns"][n - 1] if n <= len(dialogue["turns"]) else {}
        reports = default_realizer().reports
        before = reports[-1] if reports else None
        del captured[:]
        del holds[:]
        result, error = None, None
        try:
            result = app_turn(self, text, session_id, approval_mode, conversation_id)
        except Exception as exc:  # recorded as an error event, then raised as before
            error = exc
        start = time.perf_counter()
        report = reports[-1] if reports and reports[-1] is not before else None
        record_turn(ledger, ledger.new_trace_id(), text, result, report, conversation=names[dialogue["id"]],
                    turn=n, context_result=captured[-1] if captured else None,
                    meaning=holds[-1] if holds else None, label=expected.get("label"),
                    act=(expected.get("expect") or {}).get("act"),
                    restart=bool(expected.get("restart_before")), pack=_pack_name(self),
                    pack_file=getattr(self, "pack_path", None), error=error)
        timing["record_s"] += time.perf_counter() - start
        timing["turns"] += 1
        if error is not None:
            raise error
        return result

    with patch.object(AppState, "turn", recorded_turn), patch.object(AppState, "_said", keep_said), \
            patch.object(ReasoningContext, "turn", keep_context):
        return dialogue_gate.run(dialogues, code_root)


def cost(language="en", repeat=5, directory=None):
    """Seven-step dialogue wall time with recording off and on (goal L1.7).

    One warm-up run loads the caches; then ``repeat`` pairs alternate off/on.
    Turn time is the gate player's own ``elapsed_ms`` around ``AppState.turn``,
    which with recording on includes ``record_turn``.
    """
    from marco.trace import runtime
    runtime.build()                      # once per process, not part of a turn
    dialogue = seven_step(language)
    turns = len(dialogue["turns"])
    record([dialogue], None)
    off, on, own, sizes, events = [], [], [], [], []

    def total(answers):
        return sum(row.get("elapsed_ms", 0.0) for row in answers[dialogue["id"]])
    with tempfile.TemporaryDirectory(prefix="marco-trace-cost-") as temporary:
        for i in range(repeat):
            order = ("off", "on") if i % 2 == 0 else ("on", "off")
            for mode in order:
                if mode == "off":
                    off.append(total(record([dialogue], None)))
                    continue
                ledger = Ledger(directory or temporary, "cost-%s-%d" % (CODES[language], i))
                timing = {}
                on.append(total(record([dialogue], ledger, timing=timing)))
                own.append(timing["record_s"] * 1000)
                sizes.append(ledger.bytes_written)
                events.append(len(ledger.events))
                ledger.close()
    off_ms, on_ms = statistics.median(off), statistics.median(on)
    return {"language": CODES[language], "turns": turns, "repeat": repeat,
            "off_ms_per_turn": round(off_ms / turns, 2), "on_ms_per_turn": round(on_ms / turns, 2),
            "overhead_pct": round(100.0 * (on_ms - off_ms) / off_ms, 1),
            "record_ms_per_turn": round(statistics.median(own) / turns, 3),
            "record_pct_of_off": round(100.0 * statistics.median(own) / off_ms, 1),
            "bytes_per_turn": round(statistics.median(sizes) / turns),
            "events_per_turn": round(statistics.median(events) / turns, 1),
            "off_runs_ms": [round(x, 1) for x in off], "on_runs_ms": [round(x, 1) for x in on]}
