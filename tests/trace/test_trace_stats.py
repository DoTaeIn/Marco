"""L1.5: failure statistics use the dialogue gate's denominators.

The ledgers here are written by hand from the round-3 dev set's labels (seen data;
no engine run), so the check is on counting, not on the engine.
"""
from pathlib import Path

import pytest

from bench import dialogue_gate
from marco.trace import stats
from marco.trace.ledger import Ledger

ROOT = Path(__file__).resolve().parents[2]
DEV3 = ROOT / "data/benchmarks/dialogues_dev3"
RT = {"build": "test", "pack": None}


def _turn(book, conversation, n, *, label=None, act=None, status="answered", reason=None, changes=0,
          parents=(), missing=None):
    trace = book.new_trace_id()
    payload = {"text": "t", "sha256": "0", "conversation": conversation, "turn": n}
    if label:
        payload.update(label=label, act=act)
    said = book.append("input_received", trace, epistemic_status="reported", payload=payload, runtime=RT)
    last = [said["event_id"]]
    for _ in range(changes):
        last = [book.append("state_changed", trace, parent_ids=[said["event_id"]], runtime=RT,
                            payload={"field": "count", "before": 1, "after": 2,
                                     "cause": said["event_id"]})["event_id"]]
    if status in ("hold", "refused"):
        last = [book.append("hold", trace, parent_ids=last, status=status, runtime=RT,
                            payload={"reason": reason, "reason_source": "meaning",
                                     "missing": missing or {}})["event_id"]]
    if status == "answered":
        last = [book.append("conclusion_created", trace, parent_ids=last + list(parents),
                            runtime=RT)["event_id"]]
    gate = {"answered": "answered", "recorded": "observed", "hold": "held", "refused": "held",
            "dialogue": "chat"}[status]
    out = book.append("output_created", trace, parent_ids=last, status=status, runtime=RT,
                      payload={"text": "r", "realized": True, "gate_status": gate})
    return said, out


def test_denominators_match_the_gate_on_the_dev3_labels(tmp_path):
    dialogues = dialogue_gate.load(DEV3)
    assert dialogues
    book = Ledger(tmp_path, "dev3-labels")
    for d in dialogues:
        for t in d["turns"]:
            _turn(book, d["id"], t["n"], label=t["label"], act=t["expect"]["act"])
    report = dialogue_gate.score(dialogues, dialogue_gate.synthesize(dialogues, "perfect"))
    result = stats.table(book)
    assert result["labelled"]
    assert result["outputs"]["answerable"]["n"] == report["gate"]["n"]
    for name, counts in report["other_labels"].items():
        assert result["outputs"][name]["n"] == counts["n"], name
    assert result["outputs"]["all"]["n"] == report["dataset"]["turns"]
    assert result["record"]["n"] == report["other_labels"]["record"]["n"]


def test_holds_by_reason_record_rate_and_graph_checks(tmp_path):
    book = Ledger(tmp_path, "small")
    statement, _ = _turn(book, "c", 1, label="hold", act="record", status="recorded", changes=1)
    _turn(book, "c", 2, label="hold", act="record", status="recorded", changes=0)
    _turn(book, "c", 3, label="answerable", act="answer", status="hold", reason="unknown_word")
    _turn(book, "c", 4, label="answerable", act="answer", status="refused", reason="premise_missing")
    _turn(book, "c", 5, label="answerable", act="answer", status="hold", reason="unknown_word")
    _turn(book, "c", 6, label="ambiguous", act="clarify", status="hold", reason="which_referent")
    rested = book.events[1]["event_id"]                   # the state change of turn 1
    _turn(book, "c", 7, label="answerable", act="answer", parents=[rested])
    book.withdraw(rested, book.new_trace_id(), parent_ids=[rested], reason="test", runtime=RT)
    _turn(book, "c", 8, label="answerable", act="answer", parents=[rested])
    _turn(book, "c", 9, label="answerable", act="answer")
    result = stats.table(book)
    assert result["outputs"]["answerable"] == {"n": 6, "answered": 3, "recorded": 0, "hold": 2, "refused": 1,
                                                "dialogue": 0, "error": 0, "unknown": 0}
    assert result["holds_by_reason"]["answerable"] == {"unknown_word": 2, "premise_missing": 1}
    assert result["holds_by_reason"]["all"] == {"unknown_word": 2, "premise_missing": 1, "which_referent": 1}
    assert (result["record"]["n"], result["record"]["with_state_changed"], result["record"]["rate"]) == (2, 1, 0.5)
    # turn 7 rests on turn 1 before the withdrawal; turn 8 after it; turn 9 on nothing but itself
    assert result["graph_checks"] == {"answered": 3, "no_statement_or_source": 1, "withdrawn_evidence_used": 1}
    text = stats.format_table(result)
    assert "unknown_word" in text and "record rate: 1/2" in text


def test_a_hold_about_an_earlier_unread_turn_is_counted_as_waiting_on_it(tmp_path):
    book = Ledger(tmp_path, "cascade")
    unread, _ = _turn(book, "c", 1, label="hold", act="record", status="hold", reason="unknown_word")
    _turn(book, "c", 2, label="answerable", act="answer", status="hold", reason="unread_event",
          missing={"said": unread["event_id"]})
    _turn(book, "c", 3, label="answerable", act="answer", status="hold", reason="input_understanding_failed")
    result = stats.table(book)
    assert result["holds_waiting"]["answerable"] == {"held": 2, "on_earlier_turn": {"record turn hold": 1}}
    assert result["hold_missing"]["answerable"]["unread_event"] == {"said": 1}
    assert "about an earlier turn 1: record turn hold 1" in stats.format_table(result)


def test_an_unlabelled_ledger_counts_statements_the_engine_recorded(tmp_path):
    book = Ledger(tmp_path, "plain")
    _turn(book, "c", 1, status="recorded", changes=2)
    _turn(book, "c", 2, status="dialogue")
    result = stats.table(book)
    assert list(result["outputs"]) == ["all"]
    assert result["record"]["n"] == 1 and result["record"]["rate"] == 1.0


@pytest.mark.parametrize("status", ["answered", "recorded", "hold", "refused", "dialogue"])
def test_every_output_status_is_counted(tmp_path, status):
    book = Ledger(tmp_path, status)
    _turn(book, "c", 1, status=status, reason="r" if status in ("hold", "refused") else None)
    assert stats.table(book)["outputs"]["all"][status] == 1
