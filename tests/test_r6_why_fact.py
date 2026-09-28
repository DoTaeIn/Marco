"""G6.4: a why that restates the fact (class 13) is a why about the named holder's current count.

Each case plays a dialogue and asks one why. The reply is scored as the dialogue gate would read the
act: ``explained`` (the named holder's count, through the existing explain path, about the right
holder and value), ``asked`` (which holder), ``held``, ``wrong`` (explained a holder or a number that
is not the current one), or ``unread``. The build half and the check half share no name, item or
amount; the fixes were made against the build half only.
"""
import json

import pytest

from pack_model import development_model
from marco.reasoning.context import ReasoningContext

_MODELS = {}


def model(language):
    if language not in _MODELS:
        _MODELS[language] = development_model(language)
    return _MODELS[language]


def context(language):
    other = "english" if language == "한국어" else "한국어"
    return ReasoningContext(model=model(language), companions=[model(other)])


def play(language, lines):
    """The turns of one conversation; the marker ``RESTART`` saves and restores the context there."""
    current, row = context(language), None
    for line in lines:
        if line == RESTART:
            fresh = context(language)
            fresh.restore(json.loads(json.dumps(current.snapshot(), ensure_ascii=False)))
            current = fresh
            continue
        row = current.turn(line) or {"status": None}
    return row


RESTART = object()

# Vocabulary of each half: names, items, amounts (disjoint between the halves).
EN = {
    "build": dict(A="Petra", B="Oskar", X="ladles", Y="cups", a0=9, b0=2, g=4, a1=5, b1=6, w=7, c=5, ca=4, cb=7,
                  b1w="six", g1="4"),
    "check": dict(A="Greta", B="Milo", X="buttons", Y="stamps", a0=20, b0=3, g=8, a1=12, b1=11, w=14, c=10, ca=10,
                  cb=13, b1w="eleven", g1="8"),
}
KO = {
    "build": dict(A="보라", B="누리", X="국자", Y="수저", a0="아홉", b0="두", g="네", a1=5, b1=6, w=7, c=5, ca=4, cb=7,
                  b1w="여섯", g1="4", b0n=2),
    "check": dict(A="세리", B="도하", X="단추", Y="우표", a0="스무", b0="세", g="여덟", a1=12, b1=11, w=14, c=10, ca=10,
                  cb=13, b1w="열한", g1="8", b0n=3),
}


def english_cases(v, half):
    s = ["{A} has {a0} {X}.", "{B} has {b0} {X}.", "{A} lent {B} {g} {X}."]
    q = ["How many {X} does {B} have?"]
    B, A, I = "{B} {X}", "{A} {X}", "I {X}"
    cases = [
        ("holder and number", s + q + ["Why does {B} have {b1}?"], ("explain", B, "b1")),
        ("holder, number, thing", s + q + ["Why does {A} have {a1} {X}?"], ("explain", A, "a1")),
        ("end up with", s + q + ["Why does {B} end up with {b1}?" if half == "build"
                                else "Why did {B} end up with {b1} {X}?"], ("explain", B, "b1")),
        ("what is the reason", s + q + ["What is the reason {B} has {b1}?"], ("explain", B, "b1")),
        ("that number", s + q + ["Why is that number {b1}?"], ("explain", B, "b1")),
        ("how it came about", s + q + ["How did that come about?" if half == "build" else "Why is that?"],
         ("explain", None, None)),
        ("only, the user", ["I have {a0} {X}.", "{B} has {b0} {X}.", "I gave {B} {g} {X}.", "How many {X} do I have?",
                            "Why do I only have {a1}?"], ("explain", I, "a1")),
        ("how come", s + q + ["How come {A} has {a1} {X}?" if half == "build" else "How come {A} only has {a1}?"],
         ("explain", A, "a1")),
        ("number as a word", s + q + ["Why does {B} have {b1w}?"], ("explain", B, "b1")),
        ("thing from the last answer", ["{A} has {a0} {X}.", "{A} has {b0} {Y}.", "How many {Y} does {A} have?",
                                        "Why does {A} have {b0}?"], ("explain", "{A} {Y}", "b0")),
        ("after a correction", s + ["The one {A} lent was {c}, not {g1}.", "How many {X} does {B} have?",
                                    "Why does {B} have {cb}?"], ("explain", B, "cb")),
        ("after restore", s + [RESTART, "Why does {B} have {b1}?"], ("explain", B, "b1")),
        # counterexamples
        ("wrong number", s + q + ["Why does {B} have {w}?"], ("hold",)),
        ("the count before the correction", s + ["The one {A} lent was {c}, not {g1}.", "How many {X} does {B} have?",
                                                 "Why does {B} have {b1}?"], ("hold",)),
        ("a pointer to two holders", s + ["Why does he have {b1}?"], ("ask",)),
        ("the thing not settled", ["{A} has {a0} {X}.", "{A} has {b0} {Y}.", "{B} has {g} {X}.",
                                   "How many {X} does {B} have?", "Why does {A} have {b0}?"], ("ask",)),
        ("nothing answered yet", s + ["Why is that number {b1}?"], ("hold",)),
    ]
    return cases


def korean_cases(v, half):
    s = ["{A}는 {X}가 {a0} 개 있어요.", "{B}는 {X}가 {b0} 개 있어요.", "{A}가 {B}한테 {X} {g} 개를 빌려줬어요."]
    q = ["{B}는 {X}가 몇 개 있어요?"]
    B, A, I = "{B} {X}", "{A} {X}", "나 {X}"
    cases = [
        ("holder and number", s + q + ["왜 {B}가 {b1}개야?"], ("explain", B, "b1")),
        ("number only", s + q + ["왜 {b1}개예요?"], ("explain", B, "b1")),
        ("the reason noun", s + q + ["{B}의 {X}가 {b1}개가 된 까닭은 무엇인가?"], ("explain", B, "b1")),
        ("formal, why inside", s + q + ["{B} {X}가 왜 {b1}개가 되었습니까?"], ("explain", B, "b1")),
        ("the other holder", s + q + ["왜 {A}가 {a1}개야?" if half == "build" else "왜 {A}는 {a1}개예요?"],
         ("explain", A, "a1")),
        ("how it came about", s + q + ["어떻게 그렇게 됐어?" if half == "build" else "왜 그렇게 된 거예요?"],
         ("explain", None, None)),
        ("only, the user", ["나는 {X}가 {a0} 개 있어.", "{B}는 {X}가 {b0} 개 있어.", "내가 {B}한테 {X} {g} 개를 줬어.",
                            "나는 {X}가 몇 개 있어?", "왜 나는 {a1}개밖에 없어?"], ("explain", I, "a1")),
        ("number as a word", s + q + ["왜 {B}는 {X}가 {b1w} 개야?"], ("explain", B, "b1")),
        ("thing from the last answer", ["{A}는 {X}가 {a0} 개 있어요.", "{A}는 {Y}가 {b0} 개 있어요.",
                                        "{A}는 {Y}가 몇 개 있어요?", "왜 {A}가 {b0n}개야?"], ("explain", "{A} {Y}", "b0n")),
        ("after a correction", s + ["아까 빌려준 건 {g1}개가 아니라 {c}개야.", "{B}는 {X}가 몇 개 있어요?",
                                    "왜 {B}가 {cb}개야?"], ("explain", B, "cb")),
        ("after restore", s + [RESTART, "왜 {B}가 {b1}개야?"], ("explain", B, "b1")),
        # counterexamples
        ("wrong number", s + q + ["왜 {B}가 {w}개야?"], ("hold",)),
        ("the count before the correction", s + ["아까 빌려준 건 {g1}개가 아니라 {c}개야.", "{B}는 {X}가 몇 개 있어요?",
                                                 "왜 {B}가 {b1}개야?"], ("hold",)),
        ("a pointer to two holders", s + ["왜 그 사람이 {b1}개야?"], ("ask",)),
        ("the thing not settled", ["{A}는 {X}가 {a0} 개 있어요.", "{A}는 {Y}가 {b0} 개 있어요.", "{B}는 {X}가 {g} 개 있어요.",
                                   "{B}는 {X}가 몇 개 있어요?", "왜 {A}가 {b0n}개야?"], ("ask",)),
        ("nothing answered yet", s + ["왜 {b1}개예요?"], ("hold",)),
    ]
    return cases


def filled(v, lines, expected):
    lines = [line if line is RESTART else line.format(**v) for line in lines]
    if expected[0] == "explain" and expected[1] is not None:
        expected = ("explain", expected[1].format(**v), v[expected[2]])
    return lines, expected


def cases_of(language, half):
    v = (EN if language == "english" else KO)[half]
    make = english_cases if language == "english" else korean_cases
    return [(name, *filled(v, lines, expected)) for name, lines, expected in make(v, half)]


def scored(row, expected):
    meaning = row.get("meaning") or {}
    if row.get("status") is None:
        return "unread"
    if meaning.get("act") == "ask":
        return "asked"
    if meaning.get("act") == "explain" and row.get("status") == "answered":
        if expected[0] != "explain":
            return "wrong"
        if expected[1] is None:
            return "explained"
        about = meaning.get("about") or {}
        told = {tuple(t.get("fact") or ()) for t in row.get("transitions") or []}
        if (about.get("holder"), about.get("value")) == expected[1:] and \
                (expected[1], "count", str(expected[2])) in told:
            return "explained"
        return "wrong"
    if row.get("status") == "answered":
        return "wrong"
    return "held"


WANT = {"explain": "explained", "ask": "asked", "hold": "held"}
# Check-half turns still unread after the fixes (none was made against the check half): a bare why in a
# phrasing no pack declares ("Why is that?", "왜 그렇게 된 거예요?"). Unread, never wrong.
CHECK_UNREAD = {("english", "how it came about"), ("한국어", "how it came about")}
ALL = [pytest.param(language, half, case, id="%s-%s-%s" % (language, half, case[0]),
                    marks=[pytest.mark.xfail(strict=True, reason="check half, unread")]
                    if half == "check" and (language, case[0]) in CHECK_UNREAD else [])
       for language in ("english", "한국어") for half in ("build", "check") for case in cases_of(language, half)]


@pytest.mark.parametrize("language,half,case", ALL)
def test_a_why_that_restates_the_fact(language, half, case):
    name, lines, expected = case
    row = play(language, lines)
    assert scored(row, expected) == WANT[expected[0]], (row.get("meaning"), row.get("answer"))
    if name == "after a correction":
        # the count explained rests on the statement as corrected, never on the withdrawn one
        withdrawn = lines[2]
        assert all((t.get("evidence") or {}).get("source") != withdrawn for t in row["transitions"])


@pytest.mark.parametrize("language", ["english", "한국어"])
def test_with_the_ledger_on_a_why_about_another_holder_does_not_say_the_last_answers_chain(language, tmp_path):
    from marco.trace.from_turn import record_turn
    from marco.trace.ledger import Ledger
    ledger = Ledger(tmp_path, "why-fact")
    v = (EN if language == "english" else KO)["build"]
    lines, _ = filled(v, (english_cases if language == "english" else korean_cases)(v, "build")[0][1], ("hold",))
    other = "Why does {A} have {a1}?" if language == "english" else "왜 {A}가 {a1}개야?"
    current = context(language)
    current.trace = ledger
    rows = []
    for n, line in enumerate(lines[:-1] + [lines[-1], other.format(**v)], 1):
        result = current.turn(line)
        rows.append(result)
        summary = record_turn(ledger, ledger.new_trace_id(), line, result, None,
                              conversation=current.conversation_id, turn=n, context_result=result,
                              gap=current.trace_gap)
        current.flush_trace(ledger, summary["input"])
    same, another = rows[-2], rows[-1]
    assert same["meaning"]["kind"] == "chain" and same["meaning"]["about"]["holder"] == "{B} {X}".format(**v)
    assert another["meaning"]["kind"] == "answer" and another["meaning"]["about"] == {
        "holder": "{A} {X}".format(**v), "value": v["a1"]}


def test_each_language_has_twenty_cases_and_the_halves_share_no_name_item_or_amount():
    for language in ("english", "한국어"):
        assert len(cases_of(language, "build")) + len(cases_of(language, "check")) >= 20
        vocab = EN if language == "english" else KO
        build = {str(x) for x in vocab["build"].values()}
        check = {str(x) for x in vocab["check"].values()}
        assert not build & check


if __name__ == "__main__":
    import sys
    from collections import Counter
    for language in ("english", "한국어"):
        for half in sys.argv[1:] or ("build", "check"):
            counts, misses = Counter(), []
            for name, lines, expected in cases_of(language, half):
                got = scored(play(language, lines), expected)
                counts[got] += 1
                if got != WANT[expected[0]]:
                    misses.append((name, got))
            print(language, half, dict(counts), "misses:", misses)
