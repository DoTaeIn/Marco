"""Realizer round 6: a record kept while its count is not said (W6.1), a correction that could point
to an unread statement (W6.2), why with a named holder and number (W6.3, request G6-3), a held count
whose holder's count before was never said (request G6-2), and the runtime release stamp (W6.4).

Every reply is composed from its meaning and every clause passes the semantic check; a number the
user restated that is not the count is never confirmed. Every name and thing here is written for this
file.
"""
import hashlib
import json
import re
from pathlib import Path

import pytest

from marco.language.realizer import Realizer
from marco.language.realizer.packs import HERE

LANGUAGES = ("english", "한국어")


def say(meaning, language, status="unresolved", transitions=None):
    result = {"status": status, "answer": "ENGINE", "meaning": meaning, "transitions": transitions or []}
    text, report = Realizer().realize_with_report(result, status, "styles/%s.json" % language)
    assert report["realized"] and not report["held"], [
        (c["frame"], c.get("attempts")) for c in report.get("clauses", []) if c.get("blocked")]
    assert "ENGINE" not in text
    for clause in report["clauses"]:
        assert clause["attempts"][-1]["check"]["ok"], clause
    return text, report


# W6.1 a record kept while its count is not said -------------------------------------------

KEPT = {
    "english": ["Wynn handed Pell 2 figs.", "Pell passed 3 figs along to Rook.", "I slid 4 figs over to Pell.",
                "Rook's aunt sent 5 figs over.", "Ms. Pell got 6 figs from the barn.", "Wynn palmed off a fig on Rook?"],
    "한국어": ["윤이 펠에게 무화과 2개를 건넸어요.", "펠이 록한테 무화과 세 개를 넘겼대.", "제가 펠한테 무화과 4개를 밀어줬어요.",
            "록 이모가 무화과 5개를 보냈어요.", "펠 씨가 헛간에서 무화과 여섯 개를 꺼냈어요.", "윤이 록에게 무화과를 떠넘겼나?"],
}
RECORDED = {"english": "Recorded.", "한국어": "반영했습니다."}
NOT_FIXED = {"english": "So I did not fix the current value.", "한국어": "그래서 지금 값을 정하지 않았습니다."}


@pytest.mark.parametrize("language,index", [(language, index) for language in LANGUAGES for index in range(6)])
def test_a_kept_record_says_it_was_recorded_and_why_the_count_is_not_given(language, index):
    said = KEPT[language][index]
    text, report = say({"act": "hold", "reason": "unread_event", "said": said, "kept": True}, language)
    assert text.startswith(RECORDED[language] + " "), text
    assert text.index('"%s"' % said) < text.index(NOT_FIXED[language]), text
    assert report["acts"] == ["INFORM", "REFUSE", "ASK"]
    assert report["plan"]["fields"] == {"kept": True}


@pytest.mark.parametrize("language", LANGUAGES)
def test_an_unread_hold_that_kept_nothing_does_not_say_recorded(language):
    text, report = say({"act": "hold", "reason": "unread_event", "said": KEPT[language][0]}, language)
    assert not text.startswith(RECORDED[language])
    assert report["plan"] == {"act": "hold", "reason": "unread_event"}


# W6.2 a correction that could point to an unread statement --------------------------------

WHICH_EVENT = {
    "english": [("Oh, it was 3, not 5.", ["Ada has 5 plums.", "Ada palmed off 5 plums on Bo."]),
                ("Sorry, 2 rather than 4.", ["Bo has 4 pears.", "Cy flicked 4 pears to Bo."]),
                ("I meant 7, not 9.", ["I have 9 kiwis.", "Dee lobbed me 9 kiwis."]),
                ("No, 1 instead of 6.", ["The shed has 6 limes.", "Eve shunted 6 limes into the shed."])],
    "한국어": [("아, 여덟 개가 아니라 여섯 개였어요.", ["아라는 자두가 여덟 개 있어요.", "보람한테 여덟 개를 쭈굴했어요."]),
            ("넷이 아니라 둘이에요.", ["보람은 배가 네 개 있어요.", "치우가 보람에게 배 네 개를 툭 던졌어요."]),
            ("아홉 말고 일곱이요.", ["저는 키위가 아홉 개 있어요.", "다은이 저한테 키위 아홉 개를 휙 넘겼어요."]),
            ("여섯이 아니라 하나예요.", ["창고에는 라임이 여섯 개 있어요.", "이브가 창고로 라임 여섯 개를 밀어넣었어요."])],
}


@pytest.mark.parametrize("language,index", [(language, index) for language in LANGUAGES for index in range(4)])
def test_a_correction_that_could_point_to_an_unread_statement_asks_naming_both(language, index):
    said, items = WHICH_EVENT[language][index]
    text, report = say({"act": "hold", "reason": "reference_which_event", "said": said, "items": items}, language)
    for item in items:
        assert '"%s"' % item in text, text
    assert text.index(items[0]) < text.index(items[1])
    assert report["acts"][-1] == "ASK"
    assert text.endswith({"english": "Please say which you mean.", "한국어": "어느 것인지 밝혀 주세요."}[language])


# W6.3 why with a named holder and number (request G6-3) -----------------------------------

def change(subject, before, after, said, turn):
    return {"operation": "quantity_update", "subject": subject, "predicate": "count", "before": before,
            "after": after, "delta": after - before,
            "evidence": {"start": 0, "end": len(said), "text": said, "turn": turn, "source": said}}


def explained(holder, value, giver, receiver, before, amount, statements, holders=None):
    event = statements[-1]
    giver_before, receiver_before = before
    meaning = {"act": "explain", "kind": "answer", "question": "?", "evidence": statements,
               "rules": ["count_remove", "count_add"],
               "changes": [change(giver, giver_before, giver_before - amount, event, 2),
                           change(receiver, receiver_before, receiver_before + amount, event, 2)],
               "about": {"holder": holder, "value": value}}
    if holders:
        meaning["holders"] = holders
    return meaning


EN_TOLD = ["Tam has 9 bowls.", "Uri has 2 bowls.", "Tam lent Uri 4 bowls."]
KO_TOLD = ["태오는 그릇이 아홉 개 있어.", "우리는 그릇이 두 개 있어.", "태오이 우리에게 그릇 네 개를 빌려줬어."]
EN_ME = ["I have 9 bowls.", "Uri has 2 bowls.", "I gave Uri 4 bowls."]
KO_ME = ["나는 그릇이 아홉 개 있어.", "우리는 그릇이 두 개 있어.", "내가 우리에게 그릇 네 개를 줬어."]

WHY = {
    "english": [
        ("explain", explained("Uri bowls", 6, "Tam bowls", "Uri bowls", (9, 2), 4, EN_TOLD), "Uri has 6 bowls."),
        ("explain", explained("Tam bowls", 5, "Tam bowls", "Uri bowls", (9, 2), 4, EN_TOLD), "Tam has 5 bowls."),
        ("explain", explained("I bowls", 5, "I bowls", "Uri bowls", (9, 2), 4, EN_ME), "You have 5 bowls."),
        ("explain", explained("Uri bowls", 6, "I bowls", "Uri bowls", (9, 2), 4, EN_ME), "Uri has 6 bowls."),
        ("differs", {"act": "hold", "reason": "unresolved", "said": "Why does Uri have 5?", "differs": True,
                     "about": {"holder": "Uri bowls", "value": 5, "recorded": 6}},
         "Uri has 6 bowls. Uri does not have 5 bowls."),
        ("differs", {"act": "hold", "reason": "unresolved", "said": "Why does Tam have 4 bowls?", "differs": True,
                     "about": {"holder": "Tam bowls", "value": 4, "recorded": 5}},
         "Tam has 5 bowls. Tam does not have 4 bowls."),
        ("differs", {"act": "hold", "reason": "unresolved", "said": "Why do I only have 3?", "differs": True,
                     "about": {"holder": "I bowls", "value": 3, "recorded": 5}},
         "You have 5 bowls. You do not have 3 bowls."),
        ("differs", {"act": "hold", "reason": "unresolved", "said": "Why is that number 12?", "differs": True,
                     "about": {"holder": "Uri bowls", "value": 12, "recorded": 0}},
         "Uri has no bowls. Uri does not have 12 bowls."),
        ("which", {"act": "ask", "reason": "which_referent", "word": "6", "candidates": ["Tam bowls", "Uri bowls"]},
         "I do not know whose number '6' is. Which of 'Tam bowls' and 'Uri bowls' do you mean?"),
        ("which", {"act": "ask", "reason": "which_referent", "word": "12", "candidates": ["Uri bowls", "Uri cups"]},
         "I do not know whose number '12' is. Which of 'Uri bowls' and 'Uri cups' do you mean?"),
    ],
    "한국어": [
        ("explain", explained("우리 그릇", 6, "태오 그릇", "우리 그릇", (9, 2), 4, KO_TOLD), "우리 그릇은 6개입니다."),
        ("explain", explained("태오 그릇", 5, "태오 그릇", "우리 그릇", (9, 2), 4, KO_TOLD), "태오 그릇은 5개입니다."),
        ("explain", explained("나 그릇", 5, "나 그릇", "우리 그릇", (9, 2), 4, KO_ME), "그릇은 5개 있으십니다."),
        ("explain", explained("우리 그릇", 6, "나 그릇", "우리 그릇", (9, 2), 4, KO_ME), "우리 그릇은 6개입니다."),
        ("differs", {"act": "hold", "reason": "unresolved", "said": "왜 우리가 5개야?", "differs": True,
                     "about": {"holder": "우리 그릇", "value": 5, "recorded": 6}},
         "우리 그릇은 6개입니다. 우리는 그릇이 5개 있지 않습니다."),
        ("differs", {"act": "hold", "reason": "unresolved", "said": "태오 그릇이 왜 4개가 되었습니까?", "differs": True,
                     "about": {"holder": "태오 그릇", "value": 4, "recorded": 5}},
         "태오 그릇은 5개입니다. 태오는 그릇이 4개 있지 않습니다."),
        ("differs", {"act": "hold", "reason": "unresolved", "said": "왜 나는 3개밖에 없어?", "differs": True,
                     "about": {"holder": "나 그릇", "value": 3, "recorded": 5}},
         "그릇은 5개 있으십니다. 그릇은 3개 있지 않으십니다."),
        ("differs", {"act": "hold", "reason": "unresolved", "said": "왜 12개예요?", "differs": True,
                     "about": {"holder": "우리 그릇", "value": 12, "recorded": 0}},
         "우리 그릇은 하나도 없습니다. 우리는 그릇이 12개 있지 않습니다."),
        ("which", {"act": "ask", "reason": "which_referent", "word": "6", "candidates": ["태오 그릇", "우리 그릇"]},
         "'6'이 누구의 수인지 알지 못합니다. '태오 그릇', '우리 그릇' 가운데 누구인가요?"),
        ("which", {"act": "ask", "reason": "which_referent", "word": "12", "candidates": ["우리 그릇", "우리 컵"]},
         "'12'가 누구의 수인지 알지 못합니다. '우리 그릇', '우리 컵' 가운데 누구인가요?"),
    ],
}


@pytest.mark.parametrize("language,index", [(language, index) for language in LANGUAGES for index in range(10)])
def test_why_with_a_named_holder_and_number(language, index):
    kind, meaning, first = WHY[language][index]
    status = "answered" if kind == "explain" else "unresolved"
    text, report = say(meaning, language, status=status)
    assert text.startswith(first), text
    if kind == "explain":
        # the holder's count first, then its derivation: the rules and the statements it rests on
        assert report["plan"]["fields_has"] == "about"
        for statement in meaning["evidence"]:
            assert statement in text
    if kind == "differs":
        # the recorded count is said; the number said only in the clause that denies it
        assert text == first
        negative = [clause for clause in report["clauses"] if str(meaning["about"]["value"]) in clause["text"]]
        assert negative and all({"english": " not ", "한국어": "않"}[language] in clause["text"] for clause in negative)
    if kind == "which":
        assert text == first and report["acts"] == ["ASK"]


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_name_as_the_word_keeps_the_who_question(language):
    word = {"english": "she", "한국어": "그녀"}[language]
    text, _ = say({"act": "ask", "reason": "which_referent", "word": word, "candidates": ["Tam", "Uri"]}, language)
    assert {"english": "I do not know who 'she' refers to.", "한국어": "'그녀'가 누구를 가리키는지"}[language] in text


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_differing_number_without_the_about_field_keeps_the_general_hold(language):
    _text, report = say({"act": "hold", "reason": "unresolved", "said": "?", "differs": True}, language)
    assert report["plan"] == {"act": "hold", "reason": "unresolved"}


# request G6-2: a held count whose holder's count before was never said -----------------

AT_LEAST = {
    "english": [
        ("Eli pens", 3, "Eli has some pens, but I do not know how many. I did not hear how many pens Eli had before. "
                        "Eli has at least 3 pens."),
        ("I pens", 2, "You have some pens, but I do not know how many. I did not hear how many pens you had before. "
                      "You have at least 2 pens."),
        ("Eli pens", 0, "Eli has some pens, but I do not know how many. I did not hear how many pens Eli had before."),
    ],
    "한국어": [
        ("하늘 연필", 3, "하늘은 연필이 있지만 몇 개인지 알 수 없습니다. 하늘은 처음에 연필이 몇 개 있었는지 듣지 못했습니다. "
                      "하늘은 연필이 적어도 3개 있습니다."),
        ("나 연필", 2, "연필이 있으시지만 몇 개인지 알 수 없습니다. 처음에 연필이 몇 개 있으셨는지 듣지 못했습니다. "
                     "연필이 적어도 2개 있으십니다."),
        ("하늘 연필", 0, "하늘은 연필이 있지만 몇 개인지 알 수 없습니다. 하늘은 처음에 연필이 몇 개 있었는지 듣지 못했습니다."),
    ],
}


@pytest.mark.parametrize("language,index", [(language, index) for language in LANGUAGES for index in range(3)])
def test_a_held_count_says_the_count_before_was_never_said_and_the_least_known(language, index):
    subject, least, expected = AT_LEAST[language][index]
    text, report = say({"act": "hold", "reason": "vague_count", "subject": subject, "at_least": least}, language)
    assert text == expected


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_vague_count_without_at_least_is_said_as_before(language):
    subject = {"english": "Eli pens", "한국어": "하늘 연필"}[language]
    text, report = say({"act": "hold", "reason": "vague_count", "subject": subject}, language)
    assert report["plan"] == {"act": "hold", "reason": "vague_count"}
    assert text == AT_LEAST[language][2][2].split(". ")[0] + "."


# W6.4 the runtime release stamp -------------------------------------------------------------

def test_the_runtime_release_stamp_carries_version_build_and_pack_digest(tmp_path):
    from marco.trace import runtime
    root = Path(runtime.ROOT)
    declared = re.search(r"""__version__\s*=\s*["']([^"']+)["']""",
                         (root / "mco" / "_version.py").read_text(encoding="utf-8")).group(1)
    pack = tmp_path / "p.kgpack"
    pack.write_bytes(b"pack bytes")
    stamp = runtime.release(pack)
    assert stamp == {"version": declared, "build": runtime.build(),
                     "pack_digest": hashlib.sha256(b"pack bytes").hexdigest()}
    first = runtime.first_stamp("styles/english.json", pack_file=pack)
    assert first["release"] == stamp
    assert runtime.release(None)["pack_digest"] is None


@pytest.mark.parametrize("stem", ["english", "한국어"])
def test_the_realizer_stamp_carries_the_declarations_release(stem):
    from marco.trace import runtime
    stamp = runtime.realizer_version(stem)
    meaning = json.loads((HERE / "meaning.json").read_text(encoding="utf-8"))["version"]["release"]
    own = json.loads((HERE / ("%s.json" % stem)).read_text(encoding="utf-8"))["version"]["release"]
    assert stamp["release"] == own and stamp["meaning_release"] == meaning == "0.6.0"
