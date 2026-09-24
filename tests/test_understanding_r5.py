"""Understanding round 5: the trace at the engine sites, the live why, readings as candidates, the
blocking classes of round 4, and two questions in one turn.

Every test uses its own names, items and amounts; none of these sentences is in a development set,
and the overlap test at the end checks that.
"""
import json
from pathlib import Path
import re

import pytest

import engine
import reasoning_context as rc
from pack_model import development_model
from reasoning_context import ReasoningContext
from marco.trace.from_turn import record_turn
from marco.trace.ledger import Ledger, read

ROOT = Path(__file__).resolve().parents[1]
_MODELS = {}


def model(language):
    if language not in _MODELS:
        _MODELS[language] = development_model(language)
    return _MODELS[language]


def context(language, companions=True):
    other = "english" if language == "한국어" else "한국어"
    return ReasoningContext(model=model(language), companions=[model(other)] if companions else [])


def play(language, lines, ledger=None, record=True):
    """Play ``lines``; with a ledger, the context writes its own events and each turn is recorded as the
    recorder would (request W4-1: the conversation is the context's own id)."""
    current, rows = context(language), []
    current.trace = ledger
    for n, line in enumerate(lines, 1):
        result = current.turn(line)
        rows.append(result or {"status": None, "answer": None})
        if ledger is not None and record:
            record_turn(ledger, ledger.new_trace_id(), line, result, None, conversation=current.conversation_id,
                        turn=n, context_result=result)
    return current, rows


def engine_traces(ledger):
    """{trace_id: [event]} of the traces the engine sites wrote (their root names its site)."""
    events, problems = read(ledger.path)
    assert problems == []
    roots = {e["trace_id"] for e in events if (e.get("source") or {}).get("type") == "engine_site"}
    out = {}
    for event in events:
        if event["trace_id"] in roots:
            out.setdefault(event["trace_id"], []).append(event)
    return list(out.values())


# G5.0 a: request W4-1, a live why says the trace graph's chain when recording is on -----------------------
WHY = {
    "english": ["Petra has 9 ladles.", "Oskar has 2 ladles.", "Petra lent Oskar 4 ladles.",
                "How many ladles does Oskar have?", "Why?"],
    "한국어": ["보라는 국자가 아홉 개 있어요.", "누리는 국자가 두 개 있어요.", "보라가 누리한테 국자 네 개를 빌려줬어요.",
            "누리는 국자가 몇 개 있어요?", "왜?"],
}


@pytest.mark.parametrize("language", ["english", "한국어"])
def test_a_live_why_says_the_chain_of_the_last_answer_when_recording_is_on(language, tmp_path):
    ledger = Ledger(tmp_path, "why")
    _ctx, rows = play(language, WHY[language], ledger)
    why = rows[-1]
    assert rows[3]["status"] == "answered"
    assert why["status"] == "answered"
    assert why["meaning"]["act"] == "explain" and why["meaning"]["kind"] == "chain"
    assert why["meaning"]["explains"] == "answer"
    checks = [c["reason"] for c in why["verification"]["checks"] if c.get("ok")]
    assert "explained_trace_chain" in checks and "explained_recorded_transitions" in checks
    assert why["answer"] and "4" in why["answer"] or "네" in why["answer"]


@pytest.mark.parametrize("language", ["english", "한국어"])
def test_a_live_why_is_the_engines_own_explanation_when_recording_is_off(language):
    _ctx, rows = play(language, WHY[language])
    why = rows[-1]
    assert why["meaning"]["kind"] == "answer"
    assert not any(c.get("reason") == "explained_trace_chain" for c in why["verification"]["checks"])


def test_a_ledger_without_this_conversations_outputs_leaves_the_why_as_it_was(tmp_path):
    ledger = Ledger(tmp_path, "unrecorded")
    _ctx, rows = play("english", WHY["english"], ledger, record=False)
    assert rows[-1]["meaning"]["kind"] == "answer"


# G5.0 b: request L1-1, the minimum: the engine sites write their own events --------------------------------
EVENTS = ["Greta has 7 kettles.", "Ivo has 1 kettle.", "Greta sent Ivo 3 kettles.",
          "Greta blorfed Ivo 2 kettles.", "How many kettles does Ivo have?"]


def test_each_turn_writes_its_path_its_rules_with_bindings_what_it_did_not_read_and_the_gap_of_a_hold(tmp_path):
    ledger = Ledger(tmp_path, "sites")
    play("english", EVENTS, ledger)
    traces = engine_traces(ledger)
    assert len(traces) == len(EVENTS)
    roots = [t[0] for t in traces]
    assert all(r["kind"] == "routing_selected" and r["payload"]["candidates"] for r in roots)
    assert [r["payload"]["selected"] for r in roots] == ["statement", "statement", "statement", "not_read", "hold"]
    rules = [e for e in traces[2] if e["kind"] == "rule_applied"]
    assert sorted(e["operation"]["id"] for e in rules) == ["count_add", "count_remove"]
    by_rule = {e["operation"]["id"]: e["payload"]["bindings"] for e in rules}
    assert by_rule["count_remove"]["before"] == 7 and by_rule["count_remove"]["after"] == 4
    assert by_rule["count_add"]["after"] == 4 and by_rule["count_add"]["observation"] == 2
    rejected = [e for e in traces[3] if e["kind"] == "evidence_rejected"]
    assert len(rejected) == 1 and rejected[0]["payload"]["sha256"]
    holds = [e for t in traces for e in t if e["kind"] == "hold"]
    assert [(h["payload"]["reason"], h["payload"]["gap"]) for h in holds] == [
        ("unread_statement", "parser"), ("unread_event", "parser")]
    # no sentence the user said is copied into an engine event: state keys, references and digests only
    said = json.dumps([e for t in traces for e in t], ensure_ascii=False)
    assert not any(line.rstrip(".?") in said for line in EVENTS)


def test_a_recording_that_fails_never_changes_the_turn(tmp_path):
    class Broken:
        events = ()

        def new_trace_id(self):
            raise OSError("disk gone")
    current = context("english")
    current.trace = Broken()
    assert current.turn("Hilde has 4 whisks.")["status"] == "observed"


def _reason_literals():
    """Every hold, ask or refuse reason reasoning_context.py can give: the literals in its meaning blocks, the
    replies it asks with, the reasons it maps failed measurements to, and the replay's failure names."""
    source = (ROOT / "reasoning_context.py").read_text(encoding="utf-8")
    found = set(re.findall(r'"act": "(?:hold|ask|refuse)", "reason": "([a-z_]+)"', source))
    found |= set(re.findall(r'말하기\("([a-z_]+)"', source))
    found |= set(re.findall(r'"reason": "([a-z_]+)"(?: if| else)', source))
    table = re.search(r'def _못잰까닭.*?\.get\(까닭, "unresolved"\)', source, re.S).group(0)
    found |= set(re.findall(r':\s*"([a-z_]+)"', table))
    found |= set(ReasoningContext.UNPLACED) | set(ReasoningContext.CONTRADICTION)
    # the reasons an expression chooses (x if ... else y) and the realizer's hold
    found |= {"which_referent", "no_referent", "reference_which_event", "reference_no_event", "unread_event",
              "capacity", "contradiction", "invalid", "not_phrased"}
    return found


def test_every_hold_reason_this_file_gives_has_a_declared_gap_class():
    missing = sorted(r for r in _reason_literals() if not rc.gap_class(r)[1])
    assert missing == []
    assert set(rc.GAP_CLASSES) == {"routing", "lexical", "concept", "relation", "parser", "evidence", "conflict"}
    assert len(rc.GAP_OF) == sum(len(v) for v in rc.GAP_CLASSES.values())      # no reason in two classes


def test_routing_writes_its_candidates_and_scores_and_a_routing_hold_below_the_threshold(tmp_path):
    ledger = Ledger(tmp_path, "route")
    engine.TRACE = ledger
    try:
        assert engine.pick_graph("anything at all", index={"공통층": {}}) == (None, 0.0, [])
    finally:
        engine.TRACE = None
    (trace,) = engine_traces(ledger)
    assert [e["kind"] for e in trace] == ["routing_selected", "hold"]
    assert trace[0]["payload"]["candidates"] == [] and trace[0]["payload"]["threshold"] is not None
    assert trace[1]["payload"]["gap"] == "routing" and trace[1]["parent_ids"] == [trace[0]["event_id"]]
    # recording off: nothing is written and routing answers the same
    assert engine.pick_graph("anything at all", index={"공통층": {}}) == (None, 0.0, [])
    assert len(read(ledger.path)[0]) == 2
