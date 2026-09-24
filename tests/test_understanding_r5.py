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
            summary = record_turn(ledger, ledger.new_trace_id(), line, result, None,
                                  conversation=current.conversation_id, turn=n, context_result=result,
                                  gap=current.trace_gap)
            current.flush_trace(ledger, summary["input"])
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
    # every event but an input rests on one: an engine trace rests on its turn's input
    inputs = [e for e in ledger.events if e["kind"] == "input_received"]
    assert [r["parent_ids"] for r in roots] == [[e["event_id"]] for e in inputs]
    assert all(e["parent_ids"] for e in ledger.events if e["kind"] != "input_received")
    # the turn's own hold carries the gap class the engine gave it (request G5-1)
    turn_holds = [e for e in ledger.events if e["kind"] == "hold"
                  and e["trace_id"] in {i["trace_id"] for i in inputs}]
    assert [h["payload"].get("gap") for h in turn_holds] == ["parser", "parser"]
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
    assert engine.flush_trace(ledger) and not engine.TRACE_PENDING
    (trace,) = engine_traces(ledger)
    assert [e["kind"] for e in trace] == ["routing_selected", "hold"]
    assert trace[0]["payload"]["candidates"] == [] and trace[0]["payload"]["threshold"] is not None
    assert trace[1]["payload"]["gap"] == "routing" and trace[1]["parent_ids"] == [trace[0]["event_id"]]
    # recording off: nothing is written and routing answers the same
    assert engine.pick_graph("anything at all", index={"공통층": {}}) == (None, 0.0, [])
    assert len(read(ledger.path)[0]) == 2


# G5.4 B: readings as candidates, checked against the state -------------------------------------------------
def asserted_numbers(text):
    import bench.dialogue_gate as gate
    return gate.quantities(gate.asserted(text or ""))


def test_the_readers_readings_come_the_readers_own_first_in_tier_order():
    parser = model("한국어").parser()
    text = "제 삼촌이 거실에서 부채 두 개를 가져갔어요."
    first = parser.parse(text, partial=True, events=True, repair=True)
    readings = parser.readings(text, partial=True, events=True, repair=True)
    assert len(readings) >= 2 and readings[0]["parsed"]["facts"] == first["facts"]
    assert [r["tier"] for r in readings] == sorted(r["tier"] for r in readings)
    assert len({r["said"] for r in readings}) == len(readings)


def test_a_reading_whose_holder_has_no_count_gives_way_to_the_one_whose_holder_has():
    current, rows = play("한국어", ["제 삼촌은 부채가 여섯 개 있어요.", "거실은 부채가 아홉 개 있어요.",
                                   "제 삼촌이 거실에서 부채 두 개를 가져갔어요.", "거실은 부채가 몇 개 있어요?"])
    taken = rows[2]
    assert taken["status"] == "observed"
    checked = [c for c in taken["verification"]["checks"] if c.get("reason") == "reading_checked"]
    assert checked and checked[0]["dropped"][0]["constraint"] == "holder_exists"
    assert rows[3]["status"] == "answered" and asserted_numbers(rows[3]["answer"]) == {7}
    # the choice is replayed: a later turn reads the conversation the same way
    assert current.turn("제 삼촌은 부채가 몇 개 있어요?")["status"] == "answered"


def _checked(language, lines, text, readings):
    current = context(language)
    for line in lines:
        current.turn(line)
    parser = current._parser()
    parser.readings = lambda said, **kw: readings(parser, said)
    return current, current._check_readings(parser, text, None, None, first_failure=None)


def _reading(parser, said, tier):
    parsed = parser.parse(said, partial=True, events=True, repair=True)
    return {"parsed": parsed, "tier": tier, "said": json.dumps([f["triple"] for f in parsed["facts"]]), "used": []}


def test_two_readings_of_one_tier_that_both_fit_and_differ_are_asked_about():
    lines = ["Ada has 6 trays.", "Bex has 4 trays."]
    current, result = _checked("english", lines, "Ada and Bex swapped 2 trays.", lambda parser, said: [
        _reading(parser, "Ada gave Bex 2 trays.", 0), _reading(parser, "Bex gave Ada 2 trays.", 0)])
    assert result["status"] == "unresolved" and result["meaning"]["act"] == "ask"
    assert result["meaning"]["reason"] == "ambiguous_reading"
    first, second = result["meaning"]["readings"]
    assert {(r["subject"], r["delta"]) for r in first["changes"]} == {("Ada trays", -2), ("Bex trays", 2)}
    assert {(r["subject"], r["delta"]) for r in second["changes"]} == {("Ada trays", 2), ("Bex trays", -2)}
    assert rc.gap_class("ambiguous_reading") == ("evidence", True)
    # nothing is recorded, and what the statement names is held until it is said again
    assert current.observations == lines
    assert current.turn("How many trays does Bex have?")["status"] == "unresolved"


def test_when_no_reading_fits_the_turn_holds_with_each_readings_failure_in_the_declared_order():
    lines = ["Ada has 1 tray.", "Bex has 4 trays."]
    current, result = _checked("english", lines, "Ada moved 3 trays.", lambda parser, said: [
        _reading(parser, "Ada gave Bex 3 trays.", 0), _reading(parser, "Cyd gave Bex 3 trays.", 1)])
    assert result["meaning"]["act"] == "hold" and result["meaning"]["reason"] == "no_reading"
    assert result["meaning"]["failed"] == [{"reading": 0, "constraint": "count_can_move"},
                                           {"reading": 1, "constraint": "holder_exists"}]
    order = [name for name, _doc, _failures in rc.READING_CONSTRAINTS]
    assert order == ["statement", "frame", "readable", "one_subject", "holder_exists", "count_can_move",
                     "within_limits"]
    assert set(ReasoningContext.UNPLACED) | set(ReasoningContext.CONTRADICTION) <= set(rc.CONSTRAINT_OF)
    assert current.observations == lines


def test_a_person_pointer_never_means_a_place():
    _ctx, rows = play("한국어", ["준영은 앨범이 열두 권 있어요.", "서점에는 앨범이 다섯 권 있어요.", "창민은 앨범이 열한 권 있어요.",
                                "지금 서점에 앨범이 몇 권 있어요?", "그분은 지금 앨범이 몇 권 있어요?"])
    assert rows[3]["status"] == "answered"
    assert rows[4]["status"] == "unresolved" and rows[4]["meaning"]["act"] == "ask"
    assert rows[4]["meaning"]["candidates"] and not any("서점" in str(n) for n in rows[4]["meaning"]["candidates"])


# G5.6: two questions in one turn, answered in order, each with its own evidence -----------------------------
SETUP = {
    "english": ["Mira has 9 lanyards.", "Teo has 4 lanyards.", "Mira sent Teo 3 lanyards."],
    "한국어": ["보영은 목도리가 아홉 개 있어요.", "태호는 목도리가 네 개 있어요.", "보영이 태호한테 목도리 세 개를 보냈어요."],
}
TWO_QUESTIONS = {
    "english": [("How many lanyards does Mira have? And how many does Teo have?", [6, 7]),
                ("How many lanyards does Teo have? How many does Mira have?", [7, 6]),
                ("How many lanyards does Mira have now? And Teo?", [6, 7]),
                ("How many lanyards has Teo got? And Mira?", [7, 6]),
                ("How many lanyards does Mira have left? How many lanyards does Teo have left?", [6, 7]),
                ("How many lanyards do Mira and Teo have in total? And how many does Mira have?", [13, 6]),
                ("How many lanyards does Teo have? And how many do Mira and Teo have in total?", [7, 13]),
                ("How many lanyards does Mira hold? And Teo?", [6, 7]),
                ("How many lanyards does Teo hold? How many lanyards does Mira hold?", [7, 6]),
                ("How many lanyards does Mira have? And how many lanyards does Teo have now?", [6, 7])],
    "한국어": [("보영은 목도리가 몇 개 있어요? 태호는요?", [6, 7]),
            ("태호는 목도리가 몇 개 있어요? 보영은 몇 개 있어요?", [7, 6]),
            ("보영은 지금 목도리가 몇 개 있어요? 태호는요?", [6, 7]),
            ("태호는 목도리를 몇 개 가지고 있어요? 보영은요?", [7, 6]),
            ("보영은 목도리가 몇 개 남았어요? 태호는 목도리가 몇 개 있어요?", [6, 7]),
            ("보영이랑 태호는 합쳐서 목도리가 몇 개 있어요? 보영은 몇 개 있어요?", [13, 6]),
            ("태호는 목도리가 몇 개 있어요? 보영이랑 태호는 합쳐서 목도리가 몇 개 있어요?", [7, 13]),
            ("보영한테 목도리가 몇 개 있어요? 태호한테는요?", [6, 7]),
            ("태호는 지금 목도리가 몇 개예요? 보영은 지금 몇 개예요?", [7, 6]),
            ("보영은 목도리를 몇 개 가지고 있어요? 태호는 목도리를 몇 개 가지고 있어요?", [6, 7])],
}


@pytest.mark.parametrize("language,case", [(lang, i) for lang in TWO_QUESTIONS for i in range(10)])
def test_two_questions_in_one_turn_are_answered_in_order_each_with_its_evidence(language, case):
    text, values = TWO_QUESTIONS[language][case]
    _ctx, rows = play(language, SETUP[language] + [text])
    result = rows[-1]
    assert result["status"] == "answered"
    meaning = result["meaning"]
    assert meaning["act"] == "inform" and meaning["kind"] == "queries" and len(meaning["answers"]) == 2
    assert [a["value"] if a.get("kind") == "total" else int(a["fact"][2]) for a in meaning["answers"]] == values
    for index, answer in enumerate(meaning["answers"]):
        sources = [e["source"] for e in (answer["evidence"] if isinstance(answer["evidence"], list)
                                         else [answer["evidence"]])]
        assert answer["status"] == "answered" and sources and set(sources) <= set(SETUP[language])
        assert any(row.get("part") == index and row.get("fact") for row in result["transitions"])
        assert any(c.get("part") == index and c.get("ok") for c in result["verification"]["checks"])


def test_a_statement_before_a_question_is_still_one_turn():
    _ctx, rows = play("english", ["Mira has 9 lanyards.", "Teo has 4 lanyards. How many lanyards does Teo have?"])
    assert (rows[-1].get("meaning") or {}).get("kind") != "queries"
