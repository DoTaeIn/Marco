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
    parser = model("english").parser()
    text = "Oona's got seven ladles and three kettles."
    first = parser.parse(text, partial=True, events=True, repair=True)
    readings = parser.readings(text, partial=True, events=True, repair=True)
    assert len(readings) >= 2 and readings[0]["parsed"]["facts"] == first["facts"]
    assert [r["tier"] for r in readings] == sorted(r["tier"] for r in readings)
    assert len({r["said"] for r in readings}) == len(readings)


def test_a_reading_whose_holder_has_no_count_gives_way_to_the_one_whose_holder_has():
    # (round 5's batch 6 took the natural case away at its root: 가져가다 with a place said with 에서 is no longer
    # read as the place giving; the two readings are given here as the reader would give them)
    lines = ["제 삼촌은 부채가 여섯 개 있어요.", "거실은 부채가 아홉 개 있어요."]
    current, taken = _checked("한국어", lines, "제 삼촌이 거실에서 부채 두 개를 가져갔어요.", lambda parser, said: [
        _reading(parser, "모루가 삼촌한테 부채 두 개를 줬어요.", 0), _reading(parser, "거실이 삼촌한테 부채 두 개를 줬어요.", 1)])
    assert taken["status"] == "observed"
    checked = [c for c in taken["verification"]["checks"] if c.get("reason") == "reading_checked"]
    assert checked and checked[0]["dropped"][0]["constraint"] == "holder_exists"
    del current._parser().readings
    assert current.turn("거실은 부채가 몇 개 있어요?")["status"] == "answered"
    # the choice is replayed: a later turn reads the conversation the same way
    assert asserted_numbers(current.turn("제 삼촌은 부채가 몇 개 있어요?")["answer"]) == {8}


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


def facts_of(language, text):
    parsed = model(language).parser().parse(text, partial=True, events=True, repair=True) or {}
    return sorted(tuple(map(str, row["triple"])) for row in parsed.get("facts", []))


# G5.3 batch 1: forms request W5-3 found misread (declared, both halves of every rule a closed class) --------
def test_the_thing_as_topic_and_the_holder_after_it_is_the_holders_count():
    assert facts_of("한국어", "귤 일곱 개는 제가 맡고 있어요.") == [("나 귤", "count", "7")]
    assert facts_of("한국어", "도마 네 개는 창민이 보관하고 있습니다.") == [("창민 도마", "count", "4")]


def test_a_relative_clause_of_holding_names_the_holder():
    assert facts_of("한국어", "약사 은비 씨가 보관하고 있는 쟁반이 세 개 있어요.") == [("은비 쟁반", "count", "3")]
    assert facts_of("한국어", "형준이 가지고 있는 거울이 두 개 있어.") == [("형준 거울", "count", "2")]


def test_a_verb_of_holding_is_never_part_of_a_name():
    for text in ("현재 컵 다섯 개는 제가 들고 있어요.", "상우가 갖고 있는 퍼즐이 여덟 개 있어요."):
        assert not any(word in holder for holder, _p, _n in facts_of("한국어", text)
                       for word in ("가지고", "갖고", "들고", "보관", "맡고", "있는"))


def test_two_holders_joined_by_a_conjunction_are_asked_about_together():
    _ctx, rows = play("한국어", ["효진은 액자가 다섯 개 있어요.", "승민은 액자가 세 개 있어요.",
                                "효진과 승민은 액자가 몇 개 있어요?", "효진이랑 승민이랑 지금 액자가 몇 개예요?"])
    assert [asserted_numbers(r["answer"]) for r in rows[2:]] == [{8}, {8}]
    _ctx, rows = play("한국어", ["저는 액자가 두 개 있어요.", "승민은 액자가 세 개 있어요.", "저와 승민이는 액자가 몇 개 있습니까?"])
    assert rows[2]["status"] == "answered" and asserted_numbers(rows[2]["answer"]) == {5}


def test_a_name_that_begins_like_the_first_person_is_a_name():
    _ctx, rows = play("한국어", ["나은 지갑은 4개다.", "나은이 지갑 지금 몇 개야?"])
    assert rows[0]["meaning"]["changes"][0]["subject"] == "나은 지갑"
    assert rows[1]["status"] == "answered" and asserted_numbers(rows[1]["answer"]) == {4}


# G5.3 batch 2: only-counts, places said with 'at', totals of the user, a relation or two places --------------
def test_an_only_count_in_every_declared_form_is_the_count():
    for text in ("Wren has just 13 kettles.", "Wren only has 13 kettles.", "Wren has just 13 kettles, nothing else.",
                 "Wren only has 13 kettles, and that's all.", "The only thing Wren has is kettles, 13 of them.",
                 "All Wren has is 13 kettles.", "Wren merely has 13 kettles."):
        assert facts_of("english", text) == [("Wren kettles", "count", "13")], text
    assert facts_of("english", "The only thing the attic room has is kettles, 13 of them.") == [
        ("attic room kettles", "count", "13")]
    assert facts_of("english", "I only have 4 kettles.") == [("I kettles", "count", "4")]


def test_a_place_holds_what_is_at_it_and_a_vague_count_of_it_said_things_first():
    assert facts_of("english", "There are 7 trays at the bike shop.") == [("bike shop trays", "count", "7")]
    assert facts_of("english", "Some trays are in the bike shop.") == [("bike shop trays", "count_unknown", "some")]
    _ctx, rows = play("english", ["There are 7 trays at the bike shop.", "How many trays are at the bike shop?"])
    assert asserted_numbers(rows[1]["answer"]) == {7}


def test_a_total_of_the_user_a_relation_or_two_places_is_asked_together():
    _ctx, rows = play("english", ["I have 4 trays.", "Dr. Kell has 3 trays.", "My niece has 2 trays.",
                                  "The bike shop has 5 trays.", "The boat shed has 6 trays.",
                                  "How many trays do I and Dr. Kell have in total?",
                                  "How many trays do my niece and Dr. Kell have in total?",
                                  "How many trays do the bike shop and the boat shed have in total?"])
    assert [asserted_numbers(r["answer"]) for r in rows[5:]] == [{7}, {5}, {11}]


def test_a_count_in_digits_is_never_part_of_the_thing_counted():
    assert not any(any(ch.isdigit() for ch in holder) for holder, _p, _n in
                   facts_of("english", "Wren only has 7 kettles, 7 of them."))
    _ctx, rows = play("english", ["Wren only has 7 kettles, 7 of them.", "How many kettles does Wren have?"])
    assert asserted_numbers(rows[1]["answer"]) == {7}


# G5.3 batch 3 (Korean): a place with 에 holds, a one-syllable relation, titled givers, only-counts, orders ----
def test_a_place_marked_with_e_holds_what_is_in_it():
    _ctx, rows = play("한국어", ["옷방에 액자가 여섯 개 있어요.", "혜린은 액자가 두 개 있어요.", "혜린이 옷방에서 액자 한 개를 가져갔어요.",
                                "옷방에 액자가 몇 개 있어요?", "혜린은 액자가 몇 개 있어요?"])
    assert [asserted_numbers(r["answer"]) for r in rows[3:]] == [{5}, {3}]


def test_a_one_syllable_relation_noun_and_a_titled_giver_keep_their_holders():
    assert facts_of("한국어", "제 딸이 지선한테 컵 세 개를 줬어요.") == [("딸 컵", "count_remove", "3"), ("지선 컵", "count_add", "3")]
    assert facts_of("한국어", "지선 씨가 제 딸한테서 컵 두 개를 받았어요.") == [("딸 컵", "count_remove", "2"),
                                                                      ("지선 컵", "count_add", "2")]
    assert facts_of("한국어", "해진이 옥 소장님한테서 컵 네 개를 받았습니다.") == [("옥 소장 컵", "count_remove", "4"),
                                                                        ("해진 컵", "count_add", "4")]


def test_korean_only_counts_places_first_moves_and_count_first_leaving():
    assert facts_of("한국어", "윤호가 가진 건 퍼즐 열두 개뿐이에요.") == [("윤호 퍼즐", "count", "12")]
    assert facts_of("한국어", "윤호한테는 퍼즐 열두 개뿐입니다.") == [("윤호 퍼즐", "count", "12")]
    assert facts_of("한국어", "옥상에서 옷방으로 퍼즐 세 개를 옮겼어요.") == [("옥상 퍼즐", "count_remove", "3"),
                                                                    ("옷방 퍼즐", "count_add", "3")]
    assert facts_of("한국어", "퍼즐 두 개를 윤호가 옥상에 두고 왔어요.") == sorted([("윤호 퍼즐", "count_remove", "2"),
                                                                          ("옥상 퍼즐", "count_add", "2")])


def test_the_speakers_possessive_before_a_thing_is_the_speaker():
    _ctx, rows = play("한국어", ["저는 앨범이 다섯 권 있어요.", "제 앨범은 지금 몇 권 있어요?", "제 동료는 앨범이 두 권 있어요.",
                                "제 동료는 앨범이 몇 권 있어요?"])
    assert [asserted_numbers(r["answer"]) for r in (rows[1], rows[3])] == [{5}, {2}]


def test_a_title_abbreviation_ends_no_sentence_so_a_hold_names_the_whole_statement():
    _ctx, rows = play("english", ["Nell has 6 stools.", "I have 4 stools.", "I zorped Mr. Quill one stool.",
                                  "How many stools does Nell have?", "How many stools do I have?"])
    assert rows[4]["meaning"]["reason"] == "unread_event"
    assert rows[4]["meaning"]["said"] == "I zorped Mr. Quill one stool."


DETERMINISM = {
    "a": ["Rhea has 8 clocks.", "I have 2 clocks.", "I sent Mr. Vole one clock and also blurped two.",
          "How many clocks do I have?", "How many clocks does Rhea have?"],
    "b": ["Ossi has 5 clocks.", "Pim has 3 clocks.", "Ossi gave Pim 2 clocks.", "How many clocks does Pim have?",
          "Why?"],
}


def test_a_conversations_replies_do_not_depend_on_another_played_before_it():
    def replies(order):
        out = {}
        for key in order:
            _ctx, rows = play("english", DETERMINISM[key])
            out[key] = [(r.get("status"), r.get("answer"), json.dumps((r.get("meaning") or {}).get("said"))) for r in rows]
        return out
    assert replies(["a", "b"]) == replies(["b", "a"])


def test_a_statement_before_a_question_is_still_one_turn():
    _ctx, rows = play("english", ["Mira has 9 lanyards.", "Teo has 4 lanyards. How many lanyards does Teo have?"])
    assert (rows[-1].get("meaning") or {}).get("kind") != "queries"


# G5.3 batch 4: the only-thing frames and closing tags in full, a pointer holder read as each person, and a
# record that would rest on an unread statement ------------------------------------------------------------------
def test_the_only_thing_frames_and_closing_tags_are_the_count():
    assert facts_of("english", "The only thing Ulla has is 7 goblets.") == [("Ulla goblets", "count", "7")]
    assert facts_of("english", "The only thing the boathouse has is 7 goblets.") == [
        ("boathouse goblets", "count", "7")]
    assert facts_of("english", "The only thing in the boathouse is 7 goblets.") == [
        ("boathouse goblets", "count", "7")]
    assert facts_of("english", "The only thing in the boathouse is goblets, 7 of them.") == [
        ("boathouse goblets", "count", "7")]
    assert facts_of("english", "Ulla only has 7 goblets, and that's the only thing she has.") == [
        ("Ulla goblets", "count", "7")]


def test_a_pointer_holder_is_never_a_person_the_same_statement_names():
    _ctx, rows = play("english", ["Ulla has 7 goblets.", "Dr. Voss only has goblets, 3 of them.",
                                  "He got two goblets from Ulla.", "How many goblets does Dr. Voss have?"])
    assert rows[2]["status"] == "observed"
    assert asserted_numbers(rows[3]["answer"]) == {5}


def test_a_pointer_holder_that_could_be_two_people_is_asked_about():
    _ctx, rows = play("english", ["I have 4 goblets.", "Ulla has 7 goblets.", "Brit has 6 goblets.",
                                  "She passed 1 goblet to me."])
    assert rows[3]["status"] == "unresolved"
    assert rows[3]["meaning"]["reason"] == "ambiguous_reading" and len(rows[3]["meaning"]["readings"]) == 2


def test_a_record_that_would_rest_on_an_unread_statement_does_not_say_the_count():
    _ctx, rows = play("english", ["Ulla has 7 goblets.", "The boathouse has 2 goblets.",
                                  "Ulla florped 3 goblets.", "Ulla left 1 goblet at the boathouse."])
    assert rows[3]["status"] == "unresolved"
    assert rows[3]["meaning"] == {"act": "hold", "reason": "unread_event", "said": "Ulla florped 3 goblets.", "kept": True,
                                  "conversation": rows[3]["meaning"]["conversation"]}
    _ctx, rows = play("english", ["Ulla has 7 goblets.", "The boathouse has 2 goblets.",
                                  "Ulla florped 3 goblets.", "Ulla has 4 goblets.",
                                  "Ulla left 1 goblet at the boathouse."])
    assert rows[4]["status"] == "observed"


def test_a_relation_giver_keeps_its_verb_and_its_recipient():
    assert facts_of("english", "My aunt lent Ulla 3 goblets.") == [("Ulla goblets", "count_add", "3"),
                                                                   ("aunt goblets", "count_remove", "3")]
    assert facts_of("english", "My aunt Brit lent Ulla 3 goblets.") == [("Brit goblets", "count_remove", "3"),
                                                                        ("Ulla goblets", "count_add", "3")]


def test_a_corrected_recipient_is_written_back_in_the_users_own_forms():
    # request W5-3 item 7: the title and the stacked particle of the replaced holder, and the speaker as said
    ctx, rows = play("한국어", ["미소는 컵이 아홉 개 있어요.", "저는 컵이 여덟 개 있어요.", "해솔 씨는 컵이 열한 개 있어요.",
                               "해솔 씨한테는 제가 컵 다섯 개를 보냈어요.", "아, 해솔 씨가 아니라 미소한테 줬어요."])
    assert rows[-1]["status"] == "observed" and ctx.observations[3] == "미소한테는 제가 컵 다섯 개를 보냈어요."
    ctx, rows = play("한국어", ["미소는 컵이 아홉 개 있어요.", "저는 컵이 여덟 개 있어요.", "해솔 씨는 컵이 열한 개 있어요.",
                               "미소가 해솔 씨에게서 컵 한 개를 받았어요.", "아, 미소가 아니라 제가 받았어요."])
    assert rows[-1]["status"] == "observed" and ctx.observations[3] == "제가 해솔 씨에게서 컵 한 개를 받았어요."


def test_a_total_is_asked_with_either_present_auxiliary():
    for aux in ("do", "does"):
        _ctx, rows = play("english", ["Ulla has 7 goblets.", "Brit has 2 goblets.",
                                      "How many goblets %s Ulla and Brit have in total?" % aux])
        assert asserted_numbers(rows[2]["answer"]) == {9}
        _ctx, rows = play("english", ["The boathouse has 7 goblets.", "The pantry has 2 goblets.",
                                      "How many goblets %s the boathouse and the pantry have in total?" % aux])
        assert asserted_numbers(rows[2]["answer"]) == {9}


# G5.3 batch 5: a relation or titled holder named as the user said it, a word that fills no slot, and a
# correction whose amount a later unread statement also carried --------------------------------------------------
def test_a_relation_or_titled_holder_is_named_as_the_user_said_it_whatever_the_verb():
    _ctx, rows = play("english", ["I own 9 kettles.", "my uncle keeps 12 kettles.", "my uncle gave me 2 kettles."])
    assert rows[2]["meaning"]["holders"]["uncle"] == {"kind": "named", "said": "my uncle"}
    _ctx, rows = play("english", ["Ulla has 5 kettles.", "Mr. Brand keeps 3 kettles.", "Ulla gave Mr. Brand 2 kettles."])
    assert rows[2]["meaning"]["holders"]["Brand"] == {"kind": "named", "said": "Mr. Brand"}


def test_a_word_that_fills_no_slot_is_never_part_of_a_holder_or_a_thing():
    assert facts_of("한국어", "지금은 미소가 컵 세 개를 가지고 있어요.") == [("미소 컵", "count", "3")]
    assert facts_of("한국어", "오늘은 미소가 컵을 세 개 가지고 있어요.") == [("미소 컵", "count", "3")]
    assert facts_of("한국어", "사서 해솔 씨가 지금은 컵 아홉 개를 보관하고 있어요.") == [("해솔 컵", "count", "9")]


def test_a_why_cites_the_statement_that_named_the_holder_of_a_count_said_without_it():
    _ctx, rows = play("english", ["I have 12 ladles.", "My neighbor Ivo has some ladles too.", "There are 6 ladles, by the way.",
                                  "Ivo got 2 ladles from me.", "How many ladles does Ivo have now?",
                                  "Why does Ivo have that many ladles now?"])
    assert "My neighbor Ivo has some ladles too." in rows[-1]["meaning"]["evidence"]


def test_a_correction_whose_amount_a_later_unread_statement_carried_is_asked_back():
    _ctx, rows = play("한국어", ["미소는 컵이 다섯 개 있어요.", "해솔은 컵이 아홉 개 있어요.", "미소가 해솔한테 컵 다섯 개를 쭈굴했어요.",
                                "참, 다섯 개가 아니라 두 개였어요."])
    assert rows[3]["status"] == "unresolved"
    assert rows[3]["meaning"]["reason"] == "reference_which_event"
    assert rows[3]["meaning"]["items"] == ["미소는 컵이 다섯 개 있어요.", "미소가 해솔한테 컵 다섯 개를 쭈굴했어요."]


def test_a_total_of_a_name_and_a_titled_holder_keeps_both_words_of_the_title():
    _ctx, rows = play("한국어", ["약사 해솔 씨가 컵이 여덟 개 있어요.", "문 차장님은 컵만 다섯 개 있어요.",
                                "해솔 씨와 문 차장님이 합쳐서 컵이 몇 개 있어요?"])
    assert rows[2]["meaning"]["subjects"] == ["해솔 컵", "문 차장 컵"] and rows[2]["meaning"]["value"] == 13
    assert rows[2]["meaning"]["holders"]["문 차장"] == {"kind": "named", "said": "문 차장님"}


# G5.3 batch 6 (Korean, from the v5 build half): a relation noun with its topic particle, the aspect adverbs, the
# words of holding in a count question, places said in other orders, taking from a place ---------------------------
def test_a_one_syllable_relation_noun_with_its_topic_particle_is_the_relation():
    assert facts_of("한국어", "제 형은 국자만 아홉 개 있어요.") == [("형 국자", "count", "9")]


def test_a_count_question_with_an_aspect_adverb_or_a_relative_clause_of_holding():
    _ctx, rows = play("한국어", ["미소는 국자가 아홉 개 있어요.", "미소는 아직 국자가 몇 개 있어요?",
                                "미소가 가지고 있는 국자는 지금 몇 개예요?"])
    assert [asserted_numbers(r["answer"]) for r in rows[1:]] == [{9}, {9}]


def test_places_said_in_other_orders_and_taking_from_a_place():
    assert facts_of("한국어", "국자가 여섯 개가 다락방에 있어요.") == [("다락방 국자", "count", "6")]
    assert facts_of("한국어", "다락방에 국자가 좀 있어요.") == [("다락방 국자", "count_unknown", "some")]
    assert facts_of("한국어", "미소가 다락방에서 국자 두 개를 가져왔어요.") == [("다락방 국자", "count_remove", "2"),
                                                                ("미소 국자", "count_add", "2")]
    assert facts_of("한국어", "미소가 뒷마당 창고에서 국자 두 개를 가져갔습니다.") == [
        ("뒷마당 창고 국자", "count_remove", "2"), ("미소 국자", "count_add", "2")]
