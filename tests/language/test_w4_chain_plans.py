"""W4.2: the explain plans for a why chain (``act: explain``, ``kind: chain`` / ``chain_hold``).

The meanings here are written by hand in the shape ``marco/trace/explain.py`` builds from a
ledger (``tests/trace/test_trace_explain.py`` builds them from recorded dialogues). Each
plan says, in order, what was recorded, what changed and by which rule, what a correction
withdrew, and what was concluded; a held reply says the turn it held and its reason. Every
clause goes through the semantic check; an injected fault is caught and never said.

Every name and thing here is written for this file.
"""
import copy
import json

import pytest

from marco.language.realizer import Realizer, default_realizer, last_report
from marco.language.realizer.packs import HERE, meaning_declarations

LANGUAGES = ("english", "한국어")
PACK = {"english": "styles/english.json", "한국어": "styles/한국어.json"}
HOLD = {"english": "This answer is on hold.", "한국어": "답을 보류합니다."}

# One conversation per language: two statements, a transfer, a correction of it, a question.
SAID = {
    "english": {"subject": ["Tamsin quinces", "Oriel quinces"], "names": ("Tamsin", "Oriel"),
                "statements": ["Tamsin has 7 quinces and Oriel has 1.", "Tamsin gave Oriel 3 quinces."],
                "correction": "No, she gave 2, not 3.", "asked": "How many quinces does Oriel have?"},
    "한국어": {"subject": ["태린 모과", "오솔 모과"], "names": ("태린", "오솔"),
              "statements": ["태린은 모과가 7개, 오솔은 1개 있어.", "태린이 오솔에게 모과 3개를 줬어."],
              "correction": "아니, 3개가 아니라 2개야.", "asked": "오솔은 모과가 몇 개야?"},
}


def chain(language):
    s = SAID[language]
    giver, taker = s["subject"]
    return {
        "act": "explain", "kind": "chain", "status": "answered", "turns": [1, 2, 3, 4],
        "statements": [{"turn": 1, "said": s["statements"][0]}, {"turn": 2, "said": s["statements"][1]}],
        "changes": [
            {"subject": taker, "field": "count", "before": None, "after": 1, "operation": "state_update",
             "rules": [], "whole": True},
            {"subject": taker, "field": "count", "before": 1, "after": 3, "operation": "quantity_update",
             "rules": [], "whole": True, "delta": 2}],
        "rules": ["count_remove", "count_add"],
        "corrections": [{"turn": 2, "by": 3, "said": s["correction"]}],
        "withdrawn": [
            {"what": "observation", "turn": 2, "by": 3, "reason": "corrected", "superseded_by": "evt_b"},
            {"what": "change", "subject": taker, "field": "count", "before": 1, "after": 4, "whole": True,
             "reason": "recomputed_after_correction", "superseded_by": "evt_c"}],
        "asked": {"turn": 4, "said": s["asked"]},
        "facts": [{"subject": taker, "relation": "count", "value": 3}],
        "fact": [taker, "count", 3]}


def held(language, reason, **fields):
    s = SAID[language]
    meaning = {"act": "explain", "kind": "chain_hold", "status": "hold", "reason": reason,
               "statements": [], "changes": [], "corrections": [], "withdrawn": [], "rules": [], "facts": [],
               "held": {"turn": 4, "said": s["asked"]}, "missing": {},
               "reply": {"turn": 4, "said": HOLD[language]}}
    meaning.update(fields)
    return meaning


def result(meaning, language):
    return {"status": "unresolved" if meaning["kind"] == "chain_hold" else "answered", "answer": "ENGINE",
            "transitions": [], "meaning": dict(meaning, conversation_language=PACK[language])}


def say(meaning, language, realizer=None):
    realizer = realizer or default_realizer()
    text, report = realizer.realize_with_report(result(meaning, language), "answered", PACK[language])
    assert report["realized"], report.get("reason")
    assert "ENGINE" not in (text or "")
    return text, report


def composed(meaning, language, realizer=None):
    text, report = say(meaning, language, realizer)
    assert not report["held"], [c.get("attempts") for c in report.get("clauses", []) if c.get("blocked")]
    return text, report


def frames(report):
    return [p["frame"] for p in report["trace"]["meaning"]]


# the chain plan ------------------------------------------------------------------------

@pytest.mark.parametrize("language", LANGUAGES)
def test_the_chain_is_said_recorded_changed_withdrawn_concluded_in_that_order(language):
    text, report = composed(chain(language), language)
    assert frames(report) == ["chain_statement", "chain_statement", "count", "count_change", "rule", "rule",
                              "reading_corrected", "change_withdrawn", "chain_asked", "count"]
    assert report["acts"] == ["INFORM", "INFORM", "INFORM", "CORRECT", "INFORM", "INFORM"]
    s = SAID[language]
    quoted = s["statements"] + [s["correction"], s["asked"]]
    positions = [text.index('"%s"' % q) for q in quoted]
    assert positions == sorted(positions)
    # the conclusion comes last, after the lead the language declares for it
    assert text.rstrip(".").endswith("3개입니다" if language == "한국어" else "Oriel has 3 quinces")
    assert last_report()["realized"] is True


@pytest.mark.parametrize("language", LANGUAGES)
def test_every_clause_of_an_explanation_passes_the_check_and_counts_are_parsed_back(language):
    _text, report = composed(chain(language), language)
    clauses = [c for c in report["clauses"] if not c.get("omitted")]
    assert len(clauses) == 10
    for clause in clauses:
        assert clause["attempts"][-1]["check"]["ok"], clause
    parsed = [c["frame"] for c in clauses if c["parse"] == "parsed"]
    assert parsed == ["count", "count"]           # the stated count (past) and the conclusion


def test_the_turn_numbers_are_the_numbers_said():
    text, _report = composed(chain("english"), "english")
    for turn in (1, 2, 3, 4):
        assert "turn %d" % turn in text
    text, _report = composed(chain("한국어"), "한국어")
    for turn in (1, 2, 3, 4):
        assert "%d번째" % turn in text


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_chain_without_rules_corrections_or_a_question_says_only_what_it_has(language):
    meaning = chain(language)
    meaning.update(rules=[], corrections=[], withdrawn=[])
    meaning.pop("asked")
    _text, report = composed(meaning, language)
    assert frames(report) == ["chain_statement", "chain_statement", "count", "count_change", "count"]


def test_rows_say_only_what_a_case_covers():
    meaning = chain("english")
    meaning["statements"].append({"turn": 5, "said": ""})                    # no words: not said
    meaning["changes"].append({"subject": "Oriel quinces", "field": "count", "before": "1.5", "after": 3,
                               "whole": False})                             # not a whole number: not said
    meaning["changes"].append({"subject": "Oriel", "field": "location", "before": "barn", "after": "loft",
                               "whole": True})                              # another relation: optional
    meaning["rules"].append("rule_nobody_declared")                         # a rule with no words: left out
    text, report = composed(meaning, "english")
    assert frames(report).count("chain_statement") == 2
    assert frames(report).count("count_change") == 1
    # The English pack does not read a past location back: left out, as the plan allows; never unchecked.
    omitted = [c for c in report["clauses"] if c.get("omitted")]
    assert [c["frame"] for c in omitted] == ["location", "rule"]
    assert "loft" not in text and "1.5" not in text and "rule_nobody_declared" not in text


def test_an_explanation_is_the_state_it_explains_when_it_concluded_no_fact():
    meaning = chain("english")
    meaning["facts"] = [{"subject": "Tamsin quinces", "relation": "count", "value": 5},
                        {"subject": "Oriel quinces", "relation": "count", "value": 3}]
    text, _report = composed(meaning, "english")
    assert text.endswith("So Tamsin has 5 quinces and Oriel has 3.")


# the hold plan -------------------------------------------------------------------------

def _reason_fields(language, reason):
    s = SAID[language]
    giver, taker = s["subject"]
    pointer = "that one" if language == "english" else "그 사람"
    return {
        "unread_event": {"statement": {"turn": 2, "said": s["statements"][1], "own": False}},
        "which_referent": {"missing": {"word": pointer, "candidates": [giver, taker]}},
        "no_referent": {"missing": {"word": pointer}},
        "not_stated": {"missing": {"subject": s["names"][0]}},
        "premise_missing": {"missing": {"subject": taker, "relation": "location"}},
        "unknown_word": {"missing": {"word": "yeeted" if language == "english" else "튕겼어"}},
        "contradiction": {"statement": {"turn": 4, "said": s["statements"][0], "own": True}},
        "vague_count": {"missing": {"subject": taker}},
    }.get(reason, {})


REASONS = [key for key in meaning_declarations()["chain"]["hold_reasons"] if not key.startswith("_")]


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("reason", REASONS + ["a_reason_nobody_declared"])
def test_a_held_reply_is_explained_by_its_turn_and_its_reason(language, reason):
    meaning = held(language, reason, **_reason_fields(language, reason))
    text, report = composed(meaning, language)
    table = meaning_declarations()["chain"]["hold_reasons"]
    expected = (table.get(reason) or table["_default"])[0]["frame"]
    assert frames(report) == ["chain_held", expected]
    assert '"%s"' % SAID[language]["asked"] in text
    assert report["meaning"] == {"act": "explain", "reason": reason}
    assert report["plan"] == {"act": "explain", "kind": "chain_hold"}


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_reason_whose_fields_are_missing_falls_back_to_the_reply_as_said(language):
    meaning = held(language, "unread_event")                                 # no statement resolved
    text, report = composed(meaning, language)
    assert frames(report) == ["chain_held", "chain_replied"]
    assert '"%s"' % HOLD[language] in text


def test_a_hold_waiting_on_an_unread_statement_names_its_turn():
    text, _report = composed(held("english", "unread_event", **_reason_fields("english", "unread_event")),
                             "english")
    assert text == ('I held my answer to "How many quinces does Oriel have?" at turn 4. '
                    'I could not read "Tamsin gave Oriel 3 quinces." at turn 2.')
    text, _report = composed(held("한국어", "unread_event", **_reason_fields("한국어", "unread_event")), "한국어")
    assert text == ('4번째 말 "오솔은 모과가 몇 개야?"에는 답을 보류했습니다. '
                    '2번째 말 "태린이 오솔에게 모과 3개를 줬어."를 읽지 못했습니다.')


def test_candidates_are_said_by_their_owners_unless_two_share_one():
    meaning = held("english", "which_referent", **_reason_fields("english", "which_referent"))
    text, _report = composed(meaning, "english")
    assert text.endswith("I could not tell whether 'that one' meant Tamsin or Oriel.")
    meaning["missing"]["candidates"] = ["Tamsin quinces", "Tamsin plums"]
    text, report = composed(meaning, "english")
    assert frames(report) == ["chain_held", "chain_replied"]
    meaning = held("한국어", "which_referent", **_reason_fields("한국어", "which_referent"))
    text, _report = composed(meaning, "한국어")
    assert text.endswith("'그 사람'이 태린과 오솔 가운데 누구인지 알지 못했습니다.")


# the check catches what a faulty declaration would say --------------------------------

def _faulty(language, frame, change):
    decl = json.loads((HERE / ("%s.json" % language)).read_text(encoding="utf-8"))
    decl["lexicon"]["seven_w"] = {"word": "seven"}
    change(decl["expressions"][frame])
    return Realizer(overrides={language: decl})


def _replace_part(candidates, old, new):
    for candidate in candidates:
        candidate["parts"] = [copy.deepcopy(new) if part == old else part for part in candidate["parts"]]


FAULTS = {
    # the turn said as another number
    "number": ("chain_statement", lambda c: _replace_part(c, {"num": "turn"}, {"lex": "seven_w"})),
    # the value before a withdrawn change left out and the value after said twice
    "dropped value": ("change_withdrawn", lambda c: _replace_part(c, {"num": "before"}, {"num": "after"})),
    # a hold's reason said without its negation
    "polarity": ("chain_unread", lambda c: _replace_part(
        c, {"verb": "read", "predicate": True, "person": "first", "negation": "cannot"},
        {"verb": "read", "predicate": True, "person": "first"})),
    # a negation added to what was recorded
    "added negation": ("chain_statement", lambda c: _replace_part(c, {"lex": "i"}, {"lex": "never"})),
}


@pytest.mark.parametrize("fault", sorted(FAULTS))
def test_an_injected_fault_is_caught_and_never_said(fault):
    frame, change = FAULTS[fault]
    realizer = _faulty("english", frame, change)
    meaning = chain("english") if frame != "chain_unread" else held(
        "english", "unread_event", **_reason_fields("english", "unread_event"))
    meaning["corrections"] = meaning.get("corrections", [])
    text, report = say(meaning, "english", realizer)
    assert report["held"] and text == HOLD["english"]
    blocked = [c for c in report["clauses"] if c.get("blocked")]
    assert blocked and blocked[0]["frame"] == frame
    readers = {f["reader"] for a in blocked[0]["attempts"] for f in (a.get("check") or {}).get("failures", [])}
    assert readers & {"quantities", "polarity", "quotes"}


# the report and the declarations -------------------------------------------------------

def test_the_report_keeps_the_meaning_act_and_reason_even_when_nothing_is_composed():
    text, report = Realizer().realize_with_report(
        {"status": "unresolved", "answer": "ENGINE", "meaning": {"act": "hold", "reason": "a_reason_with_no_plan"}},
        "unresolved", PACK["english"])
    assert text == "ENGINE" and report["realized"] is False and report["reason"] == "no_plan"
    assert report["meaning"] == {"act": "hold", "reason": "a_reason_with_no_plan"}
    _text, report = composed(chain("english"), "english")
    assert report["meaning"] == {"act": "explain", "reason": None}
    assert report["plan"] == {"act": "explain", "kind": "chain"}


def test_the_declarations_carry_one_version():
    versions = {name: json.loads((HERE / name).read_text(encoding="utf-8"))["version"]["release"]
                for name in ("meaning.json", "english.json", "한국어.json")}
    assert len(set(versions.values())) == 1, versions
