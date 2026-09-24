"""W5.3 (request W4-2 item 2): the realizer's report carries what a reply was said from into the ledger.

``output_created`` keeps the meaning's act and reason (ids, no text) and, for a composed reply, the
match of the turn plan that said it; a hold whose envelope gave no meaning takes its reason from
the realizer's report. Recorded from outside the engine, as ``marco/trace/drive.py`` records.

Every name and thing here is written for this file.
"""
import json

import pytest

from marco.trace import drive, from_turn, schema
from marco.trace.ledger import Ledger
from marco.language.realizer.packs import meaning_declarations

PACKS = {"en": "styles/english.json", "ko": "styles/한국어.json"}
PLANS = [plan["match"] for plan in meaning_declarations()["turn_plans"]]


@pytest.fixture(scope="module")
def seven_step(tmp_path_factory):
    folder = tmp_path_factory.mktemp("w5-trace")
    books = {}
    for code in PACKS:
        book = Ledger(folder, "seven-%s" % code)
        drive.record([drive.seven_step(code)], book)
        books[code] = book
    return books


def _outputs(book):
    return [event for event in book.events if event["kind"] == "output_created"]


@pytest.mark.parametrize("code", sorted(PACKS))
def test_every_realized_output_names_the_act_reason_and_plan_it_was_said_from(seven_step, code):
    outputs = _outputs(seven_step[code])
    assert len(outputs) == 10
    for event in outputs:
        schema.validate(event)
        payload = event["payload"]
        assert payload["realized"] is True
        assert set(payload["meaning"]) == {"act", "reason"}
        assert payload["meaning"]["act"] in ("record", "inform", "refuse", "ask", "correct", "explain", None)
        # The plan is one of the declared plans' matches, as declared: ids, no words.
        assert payload["plan"] in PLANS
        assert len(json.dumps(payload["plan"], ensure_ascii=False).encode("utf-8")) < 400


@pytest.mark.parametrize("code", sorted(PACKS))
def test_the_seven_step_holds_are_traced_with_their_reasons(seven_step, code):
    outputs = _outputs(seven_step[code])
    # Step 3b (a relation never stated) and step 6 (a pointer to two people).
    assert outputs[3]["payload"]["meaning"] == {"act": "refuse", "reason": "premise_missing"}
    assert outputs[3]["payload"]["plan"] == {"act": "refuse", "reason": "premise_missing"}
    assert outputs[6]["payload"]["meaning"] == {"act": "ask", "reason": "which_referent"}
    answered = [event for event in outputs if event["status"] == "answered"]
    assert answered and all(event["payload"]["plan"].get("source") == "fact" for event in answered
                            if event["payload"]["meaning"]["act"] in (None, "inform")
                            and "kind" not in event["payload"]["plan"])


UI_HOLD = {"phase": "answer", "answer": {"known": False, "answer": "held", "trace": {"verdict": "조건부족"}}}


def test_a_hold_with_no_meaning_in_its_envelope_takes_the_reason_from_the_report(tmp_path):
    book = Ledger(tmp_path, "report-reason")
    report = {"realized": True, "held": False, "text": "held", "language": "english",
              "meaning": {"act": "hold", "reason": "unread_event"}, "plan": {"act": "hold", "reason": "unread_event"},
              "acts": ["REFUSE", "ASK"]}
    said = from_turn.record_turn(book, book.new_trace_id(), "How many?", UI_HOLD, report, pack=PACKS["en"])
    hold = next(book.get(e) for e in said["events"] if book.get(e)["kind"] == "hold")
    assert hold["payload"]["reason"] == "unread_event" and hold["payload"]["reason_source"] == "realizer"
    output = book.get(said["output"])
    assert output["payload"]["meaning"] == {"act": "hold", "reason": "unread_event"}
    assert output["payload"]["plan"] == {"act": "hold", "reason": "unread_event"}
    schema.validate(output)


def test_the_envelopes_own_meaning_comes_first_and_a_turn_without_a_report_names_none(tmp_path):
    book = Ledger(tmp_path, "meaning-first")
    report = {"realized": False, "reason": "no_plan", "text": None,
              "meaning": {"act": "hold", "reason": "a_reason_with_no_plan"}}
    said = from_turn.record_turn(book, book.new_trace_id(), "x", UI_HOLD, report, pack=PACKS["en"],
                                 meaning={"act": "hold", "reason": "not_stated", "subject": "Una pears"})
    hold = next(book.get(e) for e in said["events"] if book.get(e)["kind"] == "hold")
    assert hold["payload"]["reason"] == "not_stated" and hold["payload"]["reason_source"] == "meaning"
    output = book.get(said["output"])["payload"]
    # Not composed: the meaning it was not said from is kept, no plan matched.
    assert output["realizer"] == "no_plan" and output["meaning"]["reason"] == "a_reason_with_no_plan"
    assert "plan" not in output
    bare = from_turn.record_turn(book, book.new_trace_id(), "y", UI_HOLD, None, pack=PACKS["en"])
    payload = book.get(bare["output"])["payload"]
    assert payload["realizer"] == "not_called" and "meaning" not in payload and "plan" not in payload
