"""Realizer round 5: the corrected receiver (W5.1), the Korean user by the honorific (W5.2),
and the plans for goal G5's new meanings (W5.5).

W5.1, request G4-1 part two: a receiver corrected in place is the ``revise`` act with
``field: recipient``, ``old_holder`` and ``new_holder``; its plan names the two receivers
instead of quoting the sentence before and after (the engine's rewrite of it is never said).

W5.2, request G4-2: the Korean realizer leaves the user unsaid and says them by the declared
honorific of the clause's predicate, now also inside a total, a comparison, and as a recipient.
A clause that would leave the user unsaid with no predicate honouring them is refused.

W5.5: two answers in one turn (``kind: queries``, request W5-1) and a choice between the
readings of an ambiguous sentence (``reason: ambiguous_reading``, request W5-2), in the
meaning fields those requests assume. Every clause is checked; an injected fault is caught.

Every name and thing here is written for this file.
"""
import copy
import json

import pytest

from marco.language.realizer import Realizer
from marco.language.realizer.packs import HERE

LANGUAGES = ("english", "한국어")
HOLD = {"english": "This answer is on hold.", "한국어": "답을 보류합니다."}


def say(result, language, realizer=None):
    text, report = (realizer or Realizer()).realize_with_report(result, result["status"], "styles/%s.json" % language)
    assert report["realized"], report.get("reason")
    assert "ENGINE" not in (text or "")
    return text, report


def composed(result, language, realizer=None):
    text, report = say(result, language, realizer)
    assert not report["held"], [(c["frame"], c.get("attempts")) for c in report.get("clauses", []) if c.get("blocked")]
    return text


def change(subject, before, after, said, turn=2):
    return {"operation": "quantity_update", "subject": subject, "predicate": "count", "before": before,
            "after": after, "delta": after - before,
            "evidence": {"start": 0, "end": len(said), "text": said, "turn": turn, "source": said}}


def stated(subject, after, said, turn=2):
    return {"operation": "state_update", "subject": subject, "predicate": "count", "before": None, "after": after,
            "evidence": {"start": 0, "end": len(said), "text": said, "turn": turn, "source": said}}


# W5.1 the corrected receiver --------------------------------------------------------------

def revised(before, old, new, changes, holders=None):
    meaning = {"act": "revise", "index": 2, "before": before, "after": "REWRITTEN BY THE ENGINE",
               "field": "recipient", "old_holder": old, "new_holder": new, "changes": changes}
    if holders:
        meaning["holders"] = holders
    return {"status": "observed", "answer": "ENGINE", "meaning": meaning, "transitions": []}


EN_EVENT, KO_EVENT = "Wynn gave Pell 2 figs.", "윤이 펠에게 무화과 2개를 줬어요."
EN_AFTER = [change("Wynn figs", 5, 3, EN_EVENT), change("Rook figs", 1, 3, EN_EVENT)]
KO_AFTER = [change("윤 무화과", 5, 3, KO_EVENT), change("록 무화과", 1, 3, KO_EVENT)]
TO_USER = {"english": [change("Wynn figs", 5, 3, EN_EVENT), change("I figs", 1, 3, EN_EVENT)],
           "한국어": [change("윤 무화과", 5, 3, KO_EVENT), change("나 무화과", 1, 3, KO_EVENT)]}

RECIPIENTS = {
    "english": [
        (revised(EN_EVENT, "Pell", "Rook", EN_AFTER),
         'I changed the receiver in the same event "Wynn gave Pell 2 figs." from Pell to Rook.'),
        (revised(EN_EVENT, "Pell", "I", TO_USER["english"]),
         'I changed the receiver in the same event "Wynn gave Pell 2 figs." from Pell to you.'),
        (revised("Wynn gave me 2 figs.", "I", "Rook", EN_AFTER),
         'I changed the receiver in the same event "Wynn gave me 2 figs." from you to Rook.'),
        (revised("Pell took 2 figs from the barn.", "Pell", "Rook", EN_AFTER, holders={"barn": {"kind": "place"}}),
         'I changed the receiver in the same event "Pell took 2 figs from the barn." from Pell to Rook.'),
        (revised("Wynn gave Ms. Pell 2 figs.", "Pell", "Rook", EN_AFTER,
                 holders={"Pell": {"kind": "named", "said": "Ms. Pell"}}),
         'I changed the receiver in the same event "Wynn gave Ms. Pell 2 figs." from Ms. Pell to Rook.'),
        (revised("Wynn put 2 figs in the barn.", "barn", "loft", EN_AFTER,
                 holders={"barn": {"kind": "place"}, "loft": {"kind": "place"}}),
         'I changed the receiver in the same event "Wynn put 2 figs in the barn." from the barn to the loft.'),
    ],
    "한국어": [
        (revised(KO_EVENT, "펠", "록", KO_AFTER),
         '같은 사건 "윤이 펠에게 무화과 2개를 줬어요."에서 펠이 받은 것을 록이 받은 것으로 고쳤습니다.'),
        (revised(KO_EVENT, "펠", "나", TO_USER["한국어"]),
         '같은 사건 "윤이 펠에게 무화과 2개를 줬어요."에서 펠이 받은 것을 받으신 것으로 고쳤습니다.'),
        (revised("윤이 저한테 무화과 2개를 줬어요.", "나", "록", KO_AFTER),
         '같은 사건 "윤이 저한테 무화과 2개를 줬어요."에서 받으신 것을 록이 받은 것으로 고쳤습니다.'),
        (revised("펠이 헛간에서 무화과 2개를 가져갔어요.", "펠", "록", KO_AFTER, holders={"헛간": {"kind": "place"}}),
         '같은 사건 "펠이 헛간에서 무화과 2개를 가져갔어요."에서 펠이 받은 것을 록이 받은 것으로 고쳤습니다.'),
        (revised("윤이 펠 씨에게 무화과 2개를 줬어요.", "펠", "록", KO_AFTER,
                 holders={"펠": {"kind": "named", "said": "펠 씨"}}),
         '같은 사건 "윤이 펠 씨에게 무화과 2개를 줬어요."에서 펠 씨가 받은 것을 록이 받은 것으로 고쳤습니다.'),
        (revised("윤이 헛간에 무화과 2개를 뒀어요.", "헛간", "다락", KO_AFTER,
                 holders={"헛간": {"kind": "place"}, "다락": {"kind": "place"}}),
         '같은 사건 "윤이 헛간에 무화과 2개를 뒀어요."의 받는 쪽을 헛간에서 다락으로 고쳤습니다.'),
    ],
}


@pytest.mark.parametrize("language,index", [(language, index) for language in LANGUAGES for index in range(6)])
def test_a_corrected_receiver_names_the_two_receivers(language, index):
    result, first = RECIPIENTS[language][index]
    text, report = say(result, language)
    assert not report["held"]
    assert text.startswith(first), text
    assert "REWRITTEN" not in text
    assert report["plan"]["fields"] == {"field": "recipient"}
    assert report["acts"][:2] == ["CORRECT", "REASSURE"]
    for clause in report["clauses"]:
        assert clause["attempts"][-1]["check"]["ok"], clause


def test_the_whole_reply_says_no_new_event_and_the_state_after():
    assert composed(RECIPIENTS["english"][1][0], "english") == (
        'I changed the receiver in the same event "Wynn gave Pell 2 figs." from Pell to you. '
        'No new event was added. Now Wynn has 3 figs and you have 3 figs.')
    assert composed(RECIPIENTS["한국어"][1][0], "한국어") == (
        '같은 사건 "윤이 펠에게 무화과 2개를 줬어요."에서 펠이 받은 것을 받으신 것으로 고쳤습니다. '
        '새 사건은 더하지 않았습니다. 이제 윤 무화과는 3개, 무화과는 3개 있으십니다.')


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_revision_that_names_no_receivers_still_quotes_the_sentences(language):
    result = revised("Wynn gave Pell 2 figs.", "Pell", "Rook", EN_AFTER)
    result["meaning"]["after"] = "Wynn gave Rook 2 figs."
    del result["meaning"]["field"], result["meaning"]["old_holder"], result["meaning"]["new_holder"]
    _text, report = say(result, language)
    assert report["plan"] == {"act": "revise"}


# W5.2 the Korean user by the honorific ----------------------------------------------------

def compared(kind, subjects, **fields):
    return {"status": "answered", "answer": "ENGINE", "transitions": [],
            "meaning": dict({"act": "inform", "kind": kind, "subjects": list(subjects)}, **fields)}


def recorded(changes):
    return {"status": "observed", "answer": "ENGINE", "transitions": list(changes),
            "meaning": {"act": "record", "reason": "observed_state", "changes": list(changes)}}


def resolved(rows):
    for row in rows:
        row["resolved_from"] = "그"
    return rows


def before_giving(subject, value):
    said = "오다가 나에게 자두 2개를 줬어"
    meaning = {"act": "inform", "query": [subject, "count", "?n"], "asked": [subject, "count", "?n"],
               "time": {"order": "before", "event": said,
                        "changes": [change("오다 자두", 5, 3, said, 1), change("나 자두", 1, 3, said, 1)]}}
    return {"status": "answered", "answer": "ENGINE", "meaning": meaning,
            "transitions": [{"fact": [subject, "count", value], "evidence": {"turn": 0, "text": said}}]}


KOREAN_USER = [
    (compared("total", ["나 자두", "오다 자두"], value=8), "오다와 합쳐서 자두가 8개 있으십니다."),
    (compared("total", ["오다 자두", "나 자두", "토베 자두"], value=12), "오다와 토베와 합쳐서 자두가 12개 있으십니다."),
    (compared("tie", ["나 자두", "오다 자두"], value=4), "자두는 오다와 똑같이 4개 있으십니다."),
    (compared("same", ["나 자두", "오다 자두"], value=4), "네, 자두는 오다와 똑같이 4개 있으십니다."),
    (compared("different", ["나 자두", "오다 자두"], values=[5, 3]),
     "아니요, 자두 수가 오다와 같지 않으십니다. 자두는 5개 있으시고, 오다는 3개입니다."),
    (recorded(resolved([change("오다 자두", 5, 3, "오다가 나에게 자두 2개를 줬어"),
                        change("나 자두", 1, 3, "오다가 나에게 자두 2개를 줬어")])),
     "반영했습니다. 오다에게서 자두 2개를 받으셨습니다. 이제 오다 자두는 3개, 자두는 3개 있으십니다."),
    (before_giving("나 자두", "1"), "오다에게서 자두를 받으시기 전에는 1개 있으셨습니다."),
    ({"status": "unresolved", "answer": "ENGINE", "meaning": {"act": "hold", "reason": "not_stated", "subject": "나 배"}},
     "이 대화에서 가지신 배에 대한 말은 나온 적이 없습니다. 그래서 답하지 않았습니다."),
]


@pytest.mark.parametrize("index", range(len(KOREAN_USER)))
def test_the_korean_user_is_said_by_the_honorific(index):
    result, said = KOREAN_USER[index]
    text = composed(result, "한국어")
    assert text == said
    # The user is never named with a first-person word (the user's own words for themself).
    assert not {"나", "내", "저", "제", "나와", "저와", "나에게"} & set(text.replace(".", " ").split())


ENGLISH_USER = [
    (compared("total", ["I plums", "Oda plums"], value=8), "You and Oda have 8 plums together."),
    (compared("same", ["I plums", "Oda plums"], value=4), "Yes, you and Oda both have 4 plums."),
    (recorded(resolved([change("Oda plums", 5, 3, "Oda gave me 2 plums"), change("I plums", 1, 3, "Oda gave me 2 plums")])),
     "Recorded. Oda gave you 2 plums. Now Oda has 3 plums and you have 3 plums."),
    ({"status": "unresolved", "answer": "ENGINE", "meaning": {"act": "hold", "reason": "not_stated", "subject": "I pears"}},
     "This conversation never mentioned your pears. So I did not answer."),
]


@pytest.mark.parametrize("index", range(len(ENGLISH_USER)))
def test_english_says_the_same_meanings_with_you(index):
    result, said = ENGLISH_USER[index]
    assert composed(result, "english") == said


def _faulty(language, frame, change_candidates):
    decl = json.loads((HERE / ("%s.json" % language)).read_text(encoding="utf-8"))
    change_candidates(decl["expressions"][frame])
    return Realizer(overrides={language: decl})


def test_a_clause_that_leaves_the_user_unsaid_without_an_honorific_is_refused():
    def drop_the_honorific(candidates):
        for candidate in candidates:
            for part in candidate["parts"]:
                part.pop("honor", None)
    for frame, result in (("total", KOREAN_USER[0][0]), ("heard", KOREAN_USER[7][0])):
        realizer = _faulty("한국어", frame, drop_the_honorific)
        text, report = say(result, "한국어", realizer)
        assert report["held"] and text == HOLD["한국어"], text
        errors = [a.get("error") for c in report["clauses"] for a in c["attempts"]]
        assert any("unmarked_addressee" in str(error) for error in errors), errors


def test_a_negated_honorific_predicate_takes_it_on_the_auxiliary():
    text = composed(KOREAN_USER[4][0], "한국어")
    assert "같지 않으십니다" in text and "같으시지" not in text


# W5.5 two answers in one turn -------------------------------------------------------------

def answer(fact, **fields):
    return dict({"status": "answered", "act": "inform", "query": [fact[0], fact[1], "?n"],
                 "asked": [fact[0], fact[1], "?n"], "fact": list(fact),
                 "evidence": {"turn": 0, "start": 0, "end": 1, "text": "x", "source": "x"}}, **fields)


def queries(*answers, transitions=()):
    return {"status": "answered", "answer": "ENGINE", "transitions": list(transitions),
            "meaning": {"act": "inform", "kind": "queries", "answers": list(answers)}}


QUERIES = {
    "english": [
        (queries(answer(["Oda plums", "count", "3"]), answer(["Tove pears", "count", "2"])),
         "Oda has 3 plums and Tove has 2 pears."),
        (queries(answer(["Oda plums", "count", "0"]), answer(["I plums", "count", "4"])),
         "Oda has no plums. You have 4 plums."),
        (queries(answer(["Oda plums", "count", "3"]),
                 {"status": "unresolved", "act": "hold", "reason": "not_stated", "subject": "Tove pears"}),
         "Oda has 3 plums. This conversation never mentioned Tove's pears. So I did not answer."),
        (queries(answer(["Oda plums", "count", "3"]),
                 {"status": "answered", "act": "inform", "kind": "total", "subjects": ["Oda plums", "Tove plums"],
                  "value": 7}),
         "Oda has 3 plums. Oda and Tove have 7 plums together."),
        # The turn's own transitions carry both facts: the plan for several answers comes first.
        (queries(answer(["Oda plums", "count", "3"]), answer(["Tove plums", "count", "5"]),
                 transitions=[{"fact": ["Oda plums", "count", "3"]}, {"fact": ["Tove plums", "count", "5"]}]),
         "Oda has 3 plums and Tove has 5 plums."),
    ],
    "한국어": [
        (queries(answer(["오다 자두", "count", "3"]), answer(["토베 배", "count", "2"])), "오다는 3개, 토베는 2개입니다."),
        (queries(answer(["오다 자두", "count", "0"]), answer(["나 자두", "count", "4"])),
         "오다는 하나도 없습니다. 4개 있으십니다."),
        (queries(answer(["오다 자두", "count", "3"]),
                 {"status": "unresolved", "act": "hold", "reason": "not_stated", "subject": "토베 배"}),
         "오다는 3개입니다. 이 대화에서 토베 배에 대한 말은 나온 적이 없습니다. 그래서 답하지 않았습니다."),
        (queries(answer(["오다 자두", "count", "3"]),
                 {"status": "answered", "act": "inform", "kind": "total", "subjects": ["오다 자두", "토베 자두"],
                  "value": 7}),
         "오다는 3개입니다. 오다와 토베는 합쳐서 자두 7개입니다."),
        (queries(answer(["오다 자두", "count", "3"]), answer(["토베 자두", "count", "5"]),
                 transitions=[{"fact": ["오다 자두", "count", "3"]}, {"fact": ["토베 자두", "count", "5"]}]),
         "오다는 3개, 토베는 5개입니다."),
    ],
}


@pytest.mark.parametrize("language,index", [(language, index) for language in LANGUAGES for index in range(5)])
def test_two_answers_in_one_turn_are_said_in_order_each_naming_whose(language, index):
    result, said = QUERIES[language][index]
    text, report = say(result, language)
    assert not report["held"] and text == said
    assert report["plan"] == {"act": "inform", "kind": "queries"}
    parsed = [c for c in report["clauses"] if c.get("parse") == "parsed"]
    assert len(parsed) >= (2 if index != 2 and index != 3 else 1)


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_turn_with_an_answer_no_plan_says_is_not_said_in_part(language):
    result = queries(answer(["Oda plums", "count", "3"]),
                     {"status": "unresolved", "act": "hold", "reason": "a_reason_nobody_declared"})
    text, report = say(result, language)
    assert text == HOLD[language] and "3" not in text


# W5.5 a choice between readings -----------------------------------------------------------

def ambiguous(said, *readings):
    return {"status": "unresolved", "answer": "ENGINE", "transitions": [],
            "meaning": {"act": "ask", "reason": "ambiguous_reading", "said": said,
                        "readings": [{"changes": list(rows)} for rows in readings]}}


EN_SAID, KO_SAID = "Wynn gave Pell's 3 figs", "윤이 무화과 세 개 펠 줬어"
READINGS = {
    "english": [
        (ambiguous(EN_SAID, [change("Wynn figs", 5, 2, EN_SAID), change("Pell figs", 1, 4, EN_SAID)],
                   [change("Pell figs", 5, 2, EN_SAID), change("Wynn figs", 1, 4, EN_SAID)]),
         "Did you mean that Wynn gave Pell 3 figs, or that Pell gave Wynn 3 figs?"),
        (ambiguous(EN_SAID, [stated("Wynn figs", "3", EN_SAID)], [stated("Pell figs", "3", EN_SAID)]),
         "Did you mean that Wynn has 3 figs, or that Pell has 3 figs?"),
        (ambiguous(EN_SAID, [change("Wynn figs", 5, 2, EN_SAID), change("I figs", 1, 4, EN_SAID)],
                   [stated("I figs", "3", EN_SAID)]),
         "Did you mean that Wynn gave you 3 figs, or that you have 3 figs?"),
        (ambiguous(EN_SAID, [], []), '"Wynn gave Pell\'s 3 figs" can be read in several ways. Please say which you mean.'),
    ],
    "한국어": [
        (ambiguous(KO_SAID, [change("윤 무화과", 5, 2, KO_SAID), change("펠 무화과", 1, 4, KO_SAID)],
                   [change("펠 무화과", 5, 2, KO_SAID), change("윤 무화과", 1, 4, KO_SAID)]),
         "윤이 펠에게 무화과 3개를 줬다는 말씀인가요, 펠이 윤에게 무화과 3개를 줬다는 말씀인가요?"),
        (ambiguous(KO_SAID, [stated("윤 무화과", "3", KO_SAID)], [stated("펠 무화과", "3", KO_SAID)]),
         # One-syllable names the pack does not read before 은: the copula form, quoted (3개라는).
         "윤 무화과는 3개라는 말씀인가요, 펠 무화과는 3개라는 말씀인가요?"),
        (ambiguous(KO_SAID, [change("윤 무화과", 5, 2, KO_SAID), change("나 무화과", 1, 4, KO_SAID)],
                   [stated("나 무화과", "3", KO_SAID)]),
         "윤에게서 무화과 3개를 받으셨다는 말씀인가요, 무화과는 3개 있으시다는 말씀인가요?"),
        (ambiguous(KO_SAID, [], []), '"윤이 무화과 세 개 펠 줬어"는 여러 가지로 읽힙니다. 어느 것인지 밝혀 주세요.'),
    ],
}


@pytest.mark.parametrize("language,index", [(language, index) for language in LANGUAGES for index in range(4)])
def test_an_ambiguous_sentence_asks_which_reading_was_meant(language, index):
    result, said = READINGS[language][index]
    text, report = say(result, language)
    assert not report["held"] and text == said
    options = [c for c in report["clauses"] if "option" in c]
    if index < 3:
        # Each reading is said as a choice and read back by the pack: none is asserted, none chosen.
        assert [c["option"] for c in options] == [0, 1] and all(c["parse"] == "parsed" for c in options)
    else:
        assert options == []


@pytest.mark.parametrize("language,said", [
    ("english", 'No interpretation of "Wynn gave Pell\'s 3 figs" fits this conversation. Please say it another way.'),
    ("한국어", '"윤이 무화과 세 개 펠 줬어"는 이 대화와 맞는 읽기가 없습니다. 다른 말로 다시 말해 주세요.'),
])
def test_a_sentence_no_reading_of_which_fits_is_held_and_asked_again(language, said):
    result = {"status": "unresolved", "answer": "ENGINE",
              "meaning": {"act": "hold", "reason": "no_reading", "said": EN_SAID if language == "english" else KO_SAID,
                          "failed": [{"reading": 0, "constraint": "recipient_is_holder"}]}}
    assert composed(result, language) == said


def test_a_korean_count_offered_as_a_choice_prefers_the_existence_verb():
    said = "민서 도윤 무화과 세 개"
    text = composed(ambiguous(said, [stated("민서 무화과", "3", said)], [stated("도윤 무화과", "3", said)]), "한국어")
    assert text == "민서는 무화과가 3개 있다는 말씀인가요, 도윤은 무화과가 3개 있다는 말씀인가요?"


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_same_reading_twice_is_not_a_choice(language):
    rows = [change("Wynn figs", 5, 2, EN_SAID), change("Pell figs", 1, 4, EN_SAID)]
    text, report = say(ambiguous(EN_SAID, rows, copy.deepcopy(rows)), language)
    assert not [c for c in report["clauses"] if "option" in c]


def test_an_option_said_wrong_is_caught_and_never_asked():
    def swap_the_holders(candidates):
        for candidate in candidates:
            for part in candidate["parts"]:
                if part.get("np") == ["giver"]:
                    part["np"] = ["receiver"]
                elif part.get("np") == ["receiver"]:
                    part["np"] = ["giver"]
    realizer = _faulty("english", "transfer", swap_the_holders)
    text, report = say(READINGS["english"][0][0], "english", realizer)
    assert report["held"] and text == HOLD["english"]
    blocked = [c for c in report["clauses"] if c.get("blocked")]
    assert blocked and blocked[0]["frame"] == "transfer" and blocked[0]["option"] == 0
