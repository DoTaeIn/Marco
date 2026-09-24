"""L1.3, L1.4, L1.6, L1.7 on the fixed seven-step dialogue, both languages, through AppState.turn.

The dialogue is played as bench/seven_step_ui.py plays it (seven turns, the question in
the other language, a restart from the saved conversation, the question in both), with
the dialogue gate's player; every turn is recorded from outside the engine.
"""
import json
from pathlib import Path
import re

import pytest

from bench import dialogue_gate
from marco.trace import drive, from_turn, pretty, runtime, schema, stats
from marco.trace.__main__ import main
from marco.trace.ledger import Ledger, read
from marco.trace.why import Graph, why

ROOT = Path(__file__).resolve().parents[2]
LANGUAGES = ("en", "ko")
PACKS = {"en": "styles/english.json", "ko": "styles/한국어.json"}
TURNS = 10
# Gate status per turn (bench/seven_step_ui.py expects these verdicts).
EXPECTED = ["observed", "observed", "answered", "held", "observed", "answered", "held",
            "answered", "answered", "answered"]


@pytest.fixture(scope="module")
def recorded(tmp_path_factory):
    folder = tmp_path_factory.mktemp("trace-seven")
    out = {}
    for code in LANGUAGES:
        dialogue = drive.seven_step(code)
        book = Ledger(folder, "seven-%s" % code)
        answers = drive.record([dialogue], book)
        out[code] = {"ledger": book, "answers": answers[dialogue["id"]], "dialogue": dialogue, "folder": folder}
    return out


def _by_turn(book):
    turns = {}
    for event in book.events:
        if event["kind"] == "input_received":
            turns[event["trace_id"]] = event["payload"]["turn"]
    grouped = {}
    for event in book.events:
        grouped.setdefault(turns[event["trace_id"]], []).append(event)
    return grouped


def _kinds(events, kind):
    return [e for e in events if e["kind"] == kind]


# ---------------------------------------------------------------------------
# L1.3 the adapter
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("code", LANGUAGES)
def test_the_dialogue_plays_as_the_seven_step_bench_expects(recorded, code):
    rows = recorded[code]["answers"]
    assert [dialogue_gate.status(row) for row in rows] == EXPECTED
    assert not any(row.get("error") or row.get("research_calls") for row in rows)


@pytest.mark.parametrize("code", LANGUAGES)
def test_every_event_validates_and_rereads_identically(recorded, code):
    book = recorded[code]["ledger"]
    events, problems = read(book.path)
    assert problems == [] and events == book.events
    for event in events:
        schema.validate(event)
        assert event["kind"] in schema.EMITTED


@pytest.mark.parametrize("code", LANGUAGES)
def test_every_event_but_the_input_has_a_parent_and_each_turn_one_output(recorded, code):
    book = recorded[code]["ledger"]
    for event in book.events:
        if event["kind"] == "input_received":
            assert event["parent_ids"] == [] and event["epistemic_status"] == "reported"
        else:
            assert event["parent_ids"], event["kind"]
    grouped = _by_turn(book)
    assert sorted(grouped) == list(range(1, TURNS + 1))
    for turn, events in grouped.items():
        assert len(_kinds(events, "input_received")) == 1
        assert len(_kinds(events, "output_created")) == 1
        assert events[0]["kind"] == "input_received" and events[-1]["kind"] == "output_created"
        assert len({e["trace_id"] for e in events}) == 1


@pytest.mark.parametrize("code", LANGUAGES)
def test_the_output_is_what_the_user_was_shown_with_the_gate_status(recorded, code):
    book, rows = recorded[code]["ledger"], recorded[code]["answers"]
    outputs = _kinds(book.events, "output_created")
    for row, output in zip(rows, outputs):
        assert output["payload"]["text"] == row["answer"]
        assert output["payload"]["realized"] is True
        assert output["payload"]["gate_status"] == dialogue_gate.status(row)
    assert [o["status"] for o in outputs] == ["recorded", "recorded", "answered", "refused", "recorded",
                                              "answered", "hold", "answered", "answered", "answered"]


@pytest.mark.parametrize("code", LANGUAGES)
def test_the_operator_names_the_statements_it_used(recorded, code):
    grouped = _by_turn(recorded[code]["ledger"])
    for turn, events in grouped.items():
        operators = _kinds(events, "rule_applied")
        assert len(operators) == 1 and operators[0]["payload"]["operator"] == "relational_graph"
    ledger = recorded[code]["ledger"]
    asked = _kinds(grouped[3], "rule_applied")[0]
    used = [ledger.get(ref) for ref in asked["input_refs"]]
    assert [(e["kind"], e["payload"]["index"]) for e in used] == [("observation_created", 0),
                                                                  ("observation_created", 1)]


@pytest.mark.parametrize("code", LANGUAGES)
def test_statements_become_state_changes_with_before_after_and_cause(recorded, code):
    book = recorded[code]["ledger"]
    grouped = _by_turn(book)
    giver, taker = ("Minsu apples", "Jiyeon apples") if code == "en" else ("민수 사과", "지연 사과")
    first = _kinds(grouped[1], "state_changed")
    assert [(e["subject"], e["payload"]["before"], e["payload"]["after"]) for e in first] == [
        (giver, None, "5"), (taker, None, "2")]
    second = _kinds(grouped[2], "state_changed")
    assert [(e["subject"], e["payload"]["before"], e["payload"]["after"]) for e in second] == [
        (giver, 5, 3), (taker, 2, 4)]
    observation = _kinds(grouped[2], "observation_created")[0]
    assert all(e["payload"]["cause"] == observation["event_id"] for e in second)
    # the whole state is replayed on every turn, but written once
    for turn in (3, 4, 6, 7, 8, 9, 10):
        assert not _kinds(grouped[turn], "state_changed")


@pytest.mark.parametrize("code", LANGUAGES)
def test_a_correction_supersedes_and_withdraws_never_edits(recorded, code):
    book = recorded[code]["ledger"]
    grouped = _by_turn(book)
    changed = _kinds(grouped[5], "state_changed")
    withdrawn = _kinds(grouped[5], "conclusion_withdrawn")
    assert [e["payload"]["field"] for e in changed] == ["observation", "count", "count"]
    assert [(e["payload"]["before"], e["payload"]["after"]) for e in changed[1:]] == [(5, 4), (2, 3)]
    old = [_kinds(grouped[2], "observation_created")[0]] + _kinds(grouped[2], "state_changed")
    assert [e["supersedes"] for e in changed] == [e["event_id"] for e in old]
    assert [w["payload"]["withdrawn"] for w in withdrawn] == [e["event_id"] for e in old]
    assert all(book.is_withdrawn(e["event_id"]) for e in old)
    # the correction's reading rests on the corrected statement and on the correction
    assert set(changed[0]["parent_ids"]) >= {_kinds(grouped[2], "input_received")[0]["event_id"]}
    assert changed[0]["payload"]["cause"] == _kinds(grouped[5], "input_received")[0]["event_id"]


@pytest.mark.parametrize("code", LANGUAGES)
def test_verification_holds_and_outputs_are_linked(recorded, code):
    book = recorded[code]["ledger"]
    grouped = _by_turn(book)
    for turn in (1, 2, 3, 5, 6, 8, 9, 10):
        assert _kinds(grouped[turn], "hypothesis_verified")
    rejected = _kinds(grouped[7], "hypothesis_rejected")
    assert rejected and rejected[0]["payload"]["checks"][0]["reason"] == "which_referent"
    refused = _kinds(grouped[4], "hold")[0]
    assert refused["status"] == "refused" and refused["payload"]["reason"] == "premise_missing"
    assert refused["payload"]["reason_source"] == "meaning"
    assert set(refused["payload"]["missing"]) == {"subject", "relation"}
    asked = _kinds(grouped[7], "hold")[0]
    assert asked["status"] == "hold" and asked["payload"]["reason"] == "which_referent"
    assert len(asked["payload"]["missing"]["candidates"]) == 2
    for turn, events in grouped.items():
        output = _kinds(events, "output_created")[0]
        parents = {book.get(p)["kind"] for p in output["parent_ids"]}
        expected = {"answered": {"conclusion_created"}, "hold": {"hold"}, "refused": {"hold"},
                    "recorded": {"state_changed"}}[output["status"]]
        assert parents == expected, (turn, parents)


def test_the_adapter_reads_the_gate_and_engine_tables_it_mirrors():
    from reasoning_context import ReasoningContext
    assert from_turn.GATE_OBSERVED == dialogue_gate.OBSERVED
    assert from_turn.GATE_HELD == dialogue_gate.HELD
    assert from_turn.GATE_CHAT == dialogue_gate.CHAT
    assert from_turn.CONTRADICTION_CHECKS == ReasoningContext.CONTRADICTION
    source = (ROOT / "views/kgpack_ui.py").read_text(encoding="utf-8")
    for status, verdict in from_turn.STATUS_VERDICT.items():
        assert '"%s": "%s"' % (status, verdict) in source


@pytest.mark.parametrize("envelope, expected", [
    ({"phase": "research", "answer": {"known": False, "trace": {"verdict": "미지"}}}, "held"),
    ({"phase": "answer", "answer": {"known": True, "trace": {"verdict": "대화"}}}, "chat"),
    ({"phase": "answer", "answer": {"known": True, "trace": {"verdict": "원문정의"}}}, "answered"),
    ({"phase": "answer", "answer": {"known": False, "trace": {"verdict": "원문정의"}}}, "held"),
    ({"phase": "answer", "answer": {"trace": {"verdict": "새것"}}}, "unknown"),
    ({"phase": "answer", "answer": {"known": True, "trace": {"verdict": "입력이해실패"}}}, "held"),
])
def test_gate_status_agrees_with_the_gate_on_other_paths(envelope, expected):
    got = from_turn.gate_status(from_turn.view(envelope))
    assert got == expected == dialogue_gate.status(dialogue_gate.observe(envelope, 0, 0.0))


def test_a_reasoning_context_result_and_an_error_are_recorded(tmp_path):
    book = Ledger(tmp_path, "shapes")
    said = from_turn.record_turn(book, book.new_trace_id(), "x", {
        "status": "unresolved", "operator": "relational_graph", "answer": "?", "transitions": [],
        "verification": {"checks": [{"ok": False, "reason": "invalid_quantity_result"}]},
        "meaning": {"act": "hold", "reason": "contradiction", "said": "x"}}, None, pack=PACKS["en"])
    kinds = [book.get(e)["kind"] for e in said["events"]]
    assert kinds == ["input_received", "rule_applied", "contradiction_found", "hold", "output_created"]
    assert said["status"] == "hold" and said["reason"] == "contradiction"
    assert book.get(said["output"])["payload"]["realizer"] == "not_called"
    failed = from_turn.record_turn(book, book.new_trace_id(), "y", None, None, pack=PACKS["en"],
                                   error=RuntimeError("boom"))
    kinds = [book.get(e)["kind"] for e in failed["events"]]
    assert kinds == ["input_received", "error", "output_created"] and failed["status"] == "error"


def _context(status, rows, act):
    return {"status": status, "operator": "relational_graph", "answer": "a", "transitions": rows,
            "meaning": {"act": act},
            "verification": {"checks": [{"ok": True, "observation_turns": 2 if len(rows) > 1 else 1}],
                             "sources": [PACKS["en"]], "model": "0" * 64}}


def _row(before, after, turn, operation="quantity_update"):
    return {"operation": operation, "subject": "X apples", "predicate": "count", "before": before,
            "after": after, "evidence": {"turn": turn, "start": 0, "end": 5}}


def test_an_answer_resting_on_a_withdrawn_value_is_caught_and_a_restored_value_is_not(tmp_path):
    book = Ledger(tmp_path, "withdrawn")
    first = _row(None, "5", 0, "state_update")
    fixed = {"operation": "correction", "index": 1, "before": "gave two", "after": "gave one"}
    back = {"operation": "correction", "index": 1, "before": "gave one", "after": "gave two"}
    fact = {"fact": ["X apples", "count", "3"], "evidence": {"turn": 1}}
    turns = [("observed", [first], "record"),
             ("observed", [first, _row(5, 3, 1)], "record"),
             ("observed", [fixed, first, _row(5, 4, 1)], "revise"),
             ("answered", [fixed, first, _row(5, 3, 1), fact], "inform"),       # rests on the old 5 -> 3
             ("observed", [fixed, back, first, _row(5, 3, 1)], "revise"),       # a second correction restores it
             ("answered", [fixed, back, first, _row(5, 3, 1), fact], "inform"),
             ("answered", [fixed, back, first, _row(5, 3, 1)], "explain")]       # why, after both corrections
    summaries = [from_turn.record_turn(book, book.new_trace_id(), "t%d" % n, _context(status, rows, act), None,
                                       conversation="c", pack=PACKS["en"])
                 for n, (status, rows, act) in enumerate(turns, 1)]
    assert [s["used_withdrawn"] for s in summaries] == [0, 0, 0, 1, 0, 0, 0]
    assert [s["new_state"] for s in summaries] == [1, 1, 2, 0, 2, 0, 0]
    result = stats.table(book)
    assert result["graph_checks"] == {"answered": 3, "no_statement_or_source": 0, "withdrawn_evidence_used": 1}
    graph = Graph(book)
    # the stale change and the statement reading it rests on, both withdrawn by the correction
    assert sorted(e["kind"] for e in graph.withdrawn_in_chain(summaries[3]["output"])) == [
        "observation_created", "state_changed"]
    assert graph.withdrawn_in_chain(summaries[5]["output"]) == []
    assert graph.withdrawn_in_chain(summaries[6]["output"]) == []


# ---------------------------------------------------------------------------
# L1.4 why chain, pretty projection, CLI
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("code", LANGUAGES)
def test_the_why_chain_reaches_the_inputs_an_output_rests_on(recorded, code):
    book = recorded[code]["ledger"]
    outputs = _kinds(book.events, "output_created")
    expected = {1: [1], 2: [1, 2], 3: [1, 2, 3], 4: [4], 5: [1, 2, 5], 6: [1, 2, 5, 6], 7: [7],
                8: [1, 2, 5, 8], 9: [1, 2, 5, 9], 10: [1, 2, 5, 10]}
    graph = Graph(book)
    for output in outputs:
        inputs = why(book, output["event_id"])
        turns = [e["payload"]["turn"] for e in inputs]
        assert turns == expected[output["payload"]["turn"]]
        assert len({e["event_id"] for e in inputs}) == len(inputs)
        assert graph.withdrawn_in_chain(output["event_id"]) == []
    # along input_refs too, the refused turn reaches the statements its operator read
    refused = outputs[3]
    assert [e["payload"]["turn"] for e in why(book, refused["event_id"], ("parent_ids", "input_refs"))] == [1, 2, 4]


@pytest.mark.parametrize("code", LANGUAGES)
def test_pretty_is_one_line_per_event_with_time_tag_subject_summary(recorded, code):
    book = recorded[code]["ledger"]
    lines = pretty.lines(book.events)
    assert len(lines) == len(book.events)
    tags = {k.tag for k in schema.KINDS.values()}
    for line, event in zip(lines, book.events):
        assert "\n" not in line
        stamp, tag = line.split()[:2]
        assert re.fullmatch(r"\d\d:\d\d:\d\d\.\d{3}", stamp) and tag in tags
        assert tag == schema.KINDS[event["kind"]].tag


def test_the_command_line_records_a_text_dialogue_and_reads_it_back(recorded, tmp_path, capsys):
    dialogue = drive.seven_step("en")
    lines = []
    for turn in dialogue["turns"]:
        if turn.get("restart_before"):
            lines.append(drive.RESTART)
        lines.append(turn["say"])
    text = tmp_path / "seven.txt"
    text.write_text("# the seven-step dialogue\n" + "\n".join(lines) + "\n", encoding="utf-8")
    assert main(["record", str(text), "--language", "en", "--out", str(tmp_path), "--name", "cli"]) == 0
    printed = capsys.readouterr().out
    assert "turns 10" in printed
    book = Ledger(tmp_path, "cli")
    assert len(_kinds(book.events, "output_created")) == TURNS
    assert _kinds(book.events, "input_received")[8]["payload"].get("restart") is True
    last = _kinds(book.events, "output_created")[-1]["event_id"]
    assert main(["why", str(book.path), last]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == 4
    assert main(["why", str(book.path), last, "--chain"]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) > 4
    assert main(["pretty", str(book.path)]) == 0
    assert len(capsys.readouterr().out.strip().splitlines()) == len(book.events)
    assert main(["stats", str(tmp_path / "cli.jsonl"), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["outputs"]["all"]["n"] == TURNS


def test_the_frozen_exam_sets_are_refused_before_they_are_touched(tmp_path, capsys):
    for frozen in drive.FROZEN:
        with pytest.raises(drive.FrozenSetRefused):
            drive.guard(ROOT / frozen)
        with pytest.raises(drive.FrozenSetRefused):
            drive.guard(ROOT / frozen / "any.json")
        assert main(["record", str(ROOT / frozen), "--out", str(tmp_path)]) == 2
    assert "refused" in capsys.readouterr().out
    assert not list(tmp_path.iterdir())


# ---------------------------------------------------------------------------
# L1.5 stats over the recorded dialogue
# ---------------------------------------------------------------------------
def test_stats_over_both_languages(recorded, tmp_path):
    events = recorded["en"]["ledger"].events + recorded["ko"]["ledger"].events
    result = stats.table(events)
    assert not result["labelled"]
    row = result["outputs"]["all"]
    assert (row["n"], row["answered"], row["recorded"], row["hold"], row["refused"]) == (20, 10, 6, 2, 2)
    assert result["holds_by_reason"]["all"] == {"premise_missing": 2, "which_referent": 2}
    assert result["record"]["rate"] == 1.0
    assert result["graph_checks"] == {"answered": 10, "no_statement_or_source": 0, "withdrawn_evidence_used": 0}


# ---------------------------------------------------------------------------
# L1.6 runtime stamp and replay
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("code", LANGUAGES)
def test_every_event_carries_the_build_and_pack_and_each_trace_its_digests(recorded, code):
    book = recorded[code]["ledger"]
    for event in book.events:
        assert event["runtime"]["build"] == runtime.build() and event["runtime"]["pack"] == PACKS[code]
    for first in _kinds(book.events, "input_received"):
        stamp = first["runtime"]
        assert re.fullmatch(r"[0-9a-f]{64}", stamp["pack_digest"])
        assert re.fullmatch(r"[0-9a-f]{64}", stamp["model_digest"])
        assert stamp["encoder"] == "문자" and stamp["replay_status"] == "exact"
        assert stamp["realizer"]["declarations"].endswith("%s.json" % Path(PACKS[code]).stem)
        assert stamp["realizer"]["meaning_schema"] == "marco-meaning-v1"
    digests = {e["runtime"]["pack_digest"] for e in _kinds(book.events, "input_received")}
    assert len(digests) == 1         # the restart reads the same pack


def _masked(events):
    names = {}

    def name(value):
        return names.setdefault(value, "id%d" % len(names))
    out = []
    for event in json.loads(json.dumps(events)):
        event.pop("timestamp")
        for key in ("event_id", "trace_id", "supersedes"):
            if key in event:
                event[key] = name(event[key])
        for key in ("parent_ids", "input_refs"):
            event[key] = [name(x) for x in event[key]]
        for key in ("cause", "withdrawn", "superseded_by"):
            if isinstance(event["payload"].get(key), str):
                event["payload"][key] = name(event["payload"][key])
        out.append(event)
    return out


@pytest.mark.parametrize("code", LANGUAGES)
def test_recording_twice_gives_the_same_events_once_ids_and_times_are_masked(recorded, code):
    again = Ledger(recorded[code]["folder"], "seven-%s-again" % code)
    drive.record([drive.seven_step(code)], again)
    assert _masked(again.events) == _masked(recorded[code]["ledger"].events)


# ---------------------------------------------------------------------------
# L1.7 cost
# ---------------------------------------------------------------------------
def test_recording_is_off_unless_a_ledger_is_named(tmp_path, monkeypatch):
    from marco.trace import ledger as ledger_module
    monkeypatch.delenv("MARCO_TRACE_DIR", raising=False)
    monkeypatch.setattr(ledger_module, "DEFAULT_DIR", tmp_path / "default")
    dialogue = drive.seven_step("en")
    dialogue["turns"] = dialogue["turns"][:3]
    rows = drive.record([dialogue], None)[dialogue["id"]]
    assert len(rows) == 3 and not (tmp_path / "default").exists()
    monkeypatch.setenv("MARCO_TRACE_DIR", str(tmp_path / "named"))
    drive.record([dialogue], None)
    files = list((tmp_path / "named").glob("*.jsonl"))
    assert len(files) == 1 and len(_kinds(read(files[0])[0], "output_created")) == 3


def test_recording_costs_little_and_copies_no_pack_or_graph_content(recorded):
    result = drive.cost("en", repeat=3)
    assert result["record_pct_of_off"] < 10, result
    assert result["bytes_per_turn"] < 8000, result
    phrases = set()

    def collect(node):
        if isinstance(node, dict):
            for value in node.values():
                collect(value)
        elif isinstance(node, list):
            for value in node:
                collect(value)
        elif isinstance(node, str) and len(node) >= 16 and " " in node.strip():
            phrases.add(node.strip())
    for pack in PACKS.values():
        collect(json.loads((ROOT / pack).read_text(encoding="utf-8")))
    for line in (ROOT / "graphs/graph_일상추론.kg").read_text(encoding="utf-8").splitlines():
        if len(line.strip()) >= 16:
            phrases.add(line.strip())
    assert len(phrases) > 100
    for code in LANGUAGES:
        for event in recorded[code]["ledger"].events:
            copy = json.loads(json.dumps(event))
            if copy["kind"] in ("input_received", "output_created"):
                copy["payload"].pop("text")          # what the user said and was shown
            serialized = json.dumps(copy, ensure_ascii=False)
            assert len(serialized.encode("utf-8")) < 2048
            assert not [p for p in phrases if p in serialized], copy["kind"]
