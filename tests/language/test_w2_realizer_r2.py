"""W2: realizer round 2 — say everything, name the subject, clean the voice.

W2.1 every hold, clarify and refusal is composed from a language-free meaning;
W2.2 an answer names its subject unless the question named exactly one holder;
W2.3 why-answers say their rules in words, the ids stay in the trace;
W2.4 repair notes leave the spoken reply, the full note is returned when asked;
W2.5 the bare why works like the long form.

Every dialogue here is written for this file (names and things no other set uses).
"""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from marco.language.realizer import Realizer, follow_up, last_report
from marco.language.realizer.packs import Language, meaning_declarations
from pack_model import development_model
from marco.reasoning.context import ReasoningContext

ROOT = Path(__file__).resolve().parents[2]
OTHER = {"english": "한국어", "한국어": "english"}


def play(language, lines):
    """Each turn's result, with the realizer's report of that turn under ``_report``."""
    context = ReasoningContext(model=development_model(language),
                               companions=[development_model(OTHER[language])])
    results = []
    for line in lines:
        result = context.turn(line)
        if result is not None:
            result["_report"] = last_report()
        results.append(result)
    return results, context


def realized(result):
    """The reply was composed by the realizer and is exactly its sentence."""
    report = result["_report"]
    assert report["realized"] and not report["held"], report.get("reason") or report.get("clauses")
    assert report["text"] == result["answer"]
    return report


# W2.1 -----------------------------------------------------------------------------------

SAMPLE = {
    "english": {"subject": "Oona quills", "word": "blimped", "said": "Oona blimped Pim 3 quills.", "rest": "with",
                "declared": "2", "given": "3", "choices": ["this time only", "from now on"], "slots": ["to"], "slot_keys": ["to"],
                "items": ["Oona has 4 quills.", "Pim has 4 quills."], "value": "Pim", "scope": "this time only",
                "event": "Oona has 4 quills.", "old": "4", "words": ["three"], "before": "Oona has 4 quills.",
                "after": "Oona has 5 quills.", "relation": "location", "candidates": ["Oona", "Pim"],
                "excluded": "Oona", "other": "Pim"},
    "한국어": {"subject": "해솔 도토리", "word": "뭉갰어", "said": "해솔이 미르에게 도토리 세 개를 뭉갰어.", "rest": "로",
              "declared": "2", "given": "3", "choices": ["이번만", "앞으로"], "slots": ["은/는"], "slot_keys": ["은"],
              "items": ["해솔은 도토리가 네 개 있어.", "미르는 도토리가 네 개 있어."], "value": "미르", "scope": "이번만",
              "event": "해솔은 도토리가 네 개 있어.", "old": "4", "words": ["셋"], "before": "해솔은 도토리가 네 개 있어.",
              "after": "해솔은 도토리가 다섯 개 있어.", "relation": "location", "candidates": ["해솔", "미르"],
              "excluded": "해솔", "other": "미르"},
}


def hold_plans():
    """Every declared plan for a hold, a clarify, a refusal or a record reason, by (act, reason)."""
    for plan in meaning_declarations()["turn_plans"]:
        match = plan["match"]
        if match.get("act") not in ("hold", "ask", "refuse", "record", "revise"):
            continue
        if any(prop.get("from") == "held_repairs" for act in plan["acts"] for prop in act["props"]):
            continue          # said from the repair reports themselves (tests/test_repair_and_english.py)
        reasons = match.get("reason")
        for reason in reasons if isinstance(reasons, list) else [reasons]:
            yield match["act"], reason


@pytest.mark.parametrize("language", ["english", "한국어"])
@pytest.mark.parametrize("act,reason", sorted(set(hold_plans()), key=str))
def test_every_hold_clarify_and_refusal_plan_is_composed_in_both_languages(language, act, reason):
    fields = dict(SAMPLE[language], act=act, **({"reason": reason} if reason else {}), changes=[])
    text, report = Realizer().realize_with_report({"meaning": fields, "answer": "ENGINE", "status": "unresolved"},
                                                  "unresolved", "styles/%s.json" % language)
    assert report["realized"] and not report["held"], [c for c in report.get("clauses", []) if c.get("blocked")]
    assert text and "ENGINE" not in text


@pytest.mark.parametrize("language,lines", [
    ("english", ["Oona has 5 quills.", "How many quills does Zed have?"]),
    ("english", ["Oona has 5 quills.", "Pim has 3 quills.", "Actually it was six, not four."]),
    ("english", ["Why?"]),
    ("한국어", ["해솔은 도토리가 다섯 개 있어.", "여울은 도토리가 몇 개 있어?"]),
    ("한국어", ["해솔은 도토리가 다섯 개 있어.", "해솔이 미르에게 도토리 두 개를 뭉갰어."]),
    ("한국어", ["왜?"]),
])
def test_engine_holds_carry_a_meaning_and_are_composed(language, lines):
    results, _context = play(language, lines)
    last = results[-1]
    assert last["status"] == "unresolved" and last["meaning"]["act"] in ("hold", "ask", "refuse")
    realized(last)


def test_an_engine_refusal_line_carries_its_reason_to_the_seam():
    import engine
    line = engine._not_found_reply("?", [], {"ask_more": "ENGINE"})
    assert line == "ENGINE" and line.reason == "ask_more" == engine._not_found_reason("?", [])


# W2.2 -----------------------------------------------------------------------------------

STATE = {"english": ["Oona has 5 quills and Pim has 3."],
         "한국어": ["해솔은 도토리가 다섯 개 있어.", "미르는 도토리가 세 개 있어."]}
ONE_HOLDER = {"english": "How many quills does Oona have?", "한국어": "해솔은 도토리가 몇 개 있어?"}


@pytest.mark.parametrize("language,pointer,question,said,unsaid", [
    ("english", False, ONE_HOLDER["english"], ["5"], ["Oona"]),                         # one holder named
    ("english", True, "How many quills does she have?", ["Oona", "5"], []),             # a pointer names nobody
    ("english", False, "How many quills do Oona and Pim have together?", ["Oona", "Pim", "8"], []),
    ("english", False, "Who has more quills now, Oona or Pim?", ["Oona"], ["Pim"]),
    ("한국어", False, ONE_HOLDER["한국어"], ["5"], ["해솔"]),
    ("한국어", True, "그 사람은 도토리가 몇 개 있어?", ["해솔", "5"], []),
    ("한국어", False, "해솔과 미르는 도토리가 모두 몇 개야?", ["해솔", "미르", "8"], []),
    ("한국어", False, "해솔과 미르 중 누가 도토리가 더 많아?", ["해솔"], ["미르"]),
])
def test_an_answer_names_its_subject_unless_the_question_named_exactly_one(language, pointer, question, said,
                                                                           unsaid):
    # A pointer points at the holder the last answer was about.
    lines = STATE[language] + ([ONE_HOLDER[language]] if pointer else []) + [question]
    results, _context = play(language, lines)
    last = results[-1]
    assert last["status"] == "answered"
    realized(last)
    for word in said:
        assert word in last["answer"], last["answer"]
    for word in unsaid:
        assert word not in last["answer"], last["answer"]


def test_the_seven_step_answers_keep_their_ellipsis():
    from bench.seven_step_dialogue import run
    for language, expected in (("english", "4 apples."), ("한국어", "4개입니다.")):
        replies = run(language)["replies"]
        assert replies[2]["answer"] == expected


# W2.3 -----------------------------------------------------------------------------------

@pytest.mark.parametrize("language,lines,words", [
    ("english", ["Oona has 5 quills and Pim has 3.", "Oona gave Pim 2 quills.",
                 "How many quills does Pim have?", "Why did that happen?"],
     ["The giver loses that many.", "The receiver gains that many."]),
    ("한국어", ["해솔은 도토리가 다섯 개 있어.", "미르는 도토리가 세 개 있어.", "해솔이 미르에게 도토리 두 개를 줬어.",
              "미르는 도토리가 몇 개 있어?", "왜 그렇게 됐어?"],
     ["주는 쪽에서 그만큼 뺍니다.", "받는 쪽에 그만큼 더합니다."]),
])
def test_why_says_its_rules_in_words_and_keeps_the_ids_in_the_trace(language, lines, words):
    results, _context = play(language, lines)
    why = results[-1]
    assert why["status"] == "answered" and why["meaning"]["rules"] == ["count_remove", "count_add"]
    report = realized(why)
    assert report["trace"]["rules"] == ["count_remove", "count_add"]
    for sentence in words:
        assert sentence in why["answer"]
    assert not re.search(r"\((count_\w+)\)|count_remove|count_add", why["answer"])


# W2.4 -----------------------------------------------------------------------------------

def test_a_particle_repair_is_not_spoken_and_is_returned_when_asked():
    results, _context = play("한국어", ["해솔은 도토리 다섯 개가 있어.", "뭘 고쳤어?"])
    first, notes = results
    repairs = [r for r in first.get("repair") or [] if r.get("status") == "repaired"]
    silent = set(meaning_declarations()["repair_notes"]["silent_operations"])
    assert repairs and all(op["op"] in silent for r in repairs for op in r["operations"])
    # a particle moved, dropped or added changes no meaning: nothing of the note is said
    report = realized(first)
    assert not any(c["frame"] == "repair_note" for c in report["clauses"])
    for repair in repairs:
        assert repair["rule"] not in first["answer"] and repair["source"] not in first["answer"]
    assert "(" not in first["answer"] and "[" not in first["answer"]
    assert [r["rule"] for r in report["trace"]["repairs"]] == [r["rule"] for r in repairs]   # kept in full
    # asked, every repair is said in full: what was read, the rule, the cost
    assert notes["status"] == "answered" and notes["meaning"]["kind"] == "repairs"
    realized(notes)
    for repair in repairs:
        assert repair["rule"] in notes["answer"] and repair["source"] in notes["answer"]
        assert "%d/%d" % (repair["cost"], repair["bound"]) in notes["answer"]


def test_a_reading_that_reorders_words_says_one_short_clause():
    results, _context = play("english", ["Has Oona five quills.", "What did you change?"])
    first, notes = results
    assert [op["op"] for r in first["repair"] for op in r["operations"]] == ["adjacent_swap"]
    assert first["answer"].startswith('I read "Has Oona five quills" as ')
    assert first["repair"][0]["rule"] not in first["answer"]
    report = realized(first)
    assert report["trace"]["repairs"][0]["rule"] == first["repair"][0]["rule"]      # the full note is traced
    assert first["repair"][0]["rule"] in notes["answer"]


def test_nothing_changed_is_said_when_the_last_reply_read_no_repair():
    results, _context = play("english", ["Oona has 5 quills.", "What did you change?"])
    assert results[-1]["meaning"]["kind"] == "no_repairs"
    realized(results[-1])


def test_the_repair_label_is_the_pack_own_word():
    lang = Language("한국어")
    assert lang.decl["lexicon"]["repair"]["word"] in lang.parser.data["context_replies"]["repaired"]
    renamed = SimpleNamespace(data={"context_replies": {"repaired": "[RENAMED] {원문}"}})
    lang.parser = renamed
    lang._pack_words()
    assert lang.decl["lexicon"]["repair"]["word"] == "RENAMED"
    for stem in ("한국어", "english"):
        decl = json.loads((ROOT / ("marco/language/realizer/%s.json" % stem)).read_text(encoding="utf-8"))
        assert "word" not in decl["lexicon"]["repair"] and "repair_tag" not in decl["lexicon"]


# W2.5 -----------------------------------------------------------------------------------

@pytest.mark.parametrize("language,lines,bare,long", [
    ("english", ["Oona has 5 quills and Pim has 3.", "Oona gave Pim 2 quills.", "How many quills does Pim have?"],
     "Why?", "Why did that happen?"),
    ("한국어", ["해솔은 도토리가 다섯 개 있어.", "미르는 도토리가 세 개 있어.", "해솔이 미르에게 도토리 두 개를 줬어.",
              "미르는 도토리가 몇 개 있어?"], "왜?", "왜 그렇게 됐어?"),
])
def test_the_bare_why_works_like_the_long_form(language, lines, bare, long):
    short, _context = play(language, lines + [bare])
    full, _context = play(language, lines + [long])
    assert short[-1]["status"] == full[-1]["status"] == "answered"
    assert short[-1]["answer"] == full[-1]["answer"]
    assert follow_up(bare, "styles/%s.json" % language) == "why_last"


def test_follow_ups_are_only_the_declared_phrasings():
    assert follow_up("Why?", "styles/english.json") == "why_last"
    assert follow_up("what did you change", "styles/english.json") == "repairs"
    assert follow_up("뭘 고쳤어?", "styles/한국어.json") == "repairs"
    assert follow_up("Why did Oona change?", "styles/english.json") is None
    assert follow_up("왜 해솔은 다섯 개야?", "styles/한국어.json") is None


# through the UI turn ----------------------------------------------------------------------

def test_the_ui_says_its_own_holds_through_the_realizer():
    import sys
    sys.path.insert(0, str(ROOT / "bench"))
    import composition_gate as cg
    dialogues = [
        {"id": "w2-ui-en", "language": "en",
         "turns": [{"n": 1, "say": "Oona has 5 quills."}, {"n": 2, "say": "Blorp the wibble, kindly."},
                   {"n": 3, "say": "What did you change?"}, {"n": 4, "say": "Why?"}]},
        {"id": "w2-ui-ko", "language": "ko",
         "turns": [{"n": 1, "say": "해솔은 도토리가 다섯 개 있어."}, {"n": 2, "say": "뭉게뭉게 퐁당 해 줘."},
                   {"n": 3, "say": "뭘 고쳤어?"}, {"n": 4, "say": "왜?"}]},
    ]
    report = cg.score(dialogues, cg.run(dialogues))
    assert not report["execution_errors"]
    assert report["total"]["composed"] == report["total"]["spoken"] == 8, report["not_composed"]
