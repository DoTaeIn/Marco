"""The language seam: ``marco.language.realize`` and its one call in the dialogue.

The 20 phrasings listed in docs/ko/repair-and-english-2026-09-22/unseen-before.json
are played twice in the same run: once with ``realize`` replaced by the pre-seam
identity (the sentence the dialogue built), once through the real ``realize``.
A turn the realizer does not plan must come out byte for byte the same. A turn it
realizes (goal W1) says the same meaning in a composed sentence: its status is
unchanged and an answered one keeps the answer value of the pre-seam sentence.
Nothing the engine says is pinned here: what the engine understands may change
from round to round, what ``realize`` may change may not. ``None`` marks a turn
with no reply.
"""
import inspect
import json
import re
from pathlib import Path

import pytest

import marco.language
import marco.reasoning.context as reasoning_context
from marco.language.realizer import default_realizer
from pack_model import development_model
from marco.reasoning.context import ReasoningContext

ROOT = Path(__file__).resolve().parents[1]
IDS = [row["id"] for row in json.loads(
    (ROOT / "docs/ko/repair-and-english-2026-09-22/unseen-before.json").read_text("utf-8"))["rows"]]
CASES = {case["id"]: case for case in json.loads(
    (ROOT / "data/benchmarks/unseen_phrasing_v1.json").read_text("utf-8"))["cases"]}


def _answers(case, statuses=None):
    context = ReasoningContext(model=development_model(case["language"]))
    results = [context.turn(text) for text in case["turns"]]
    if statuses is not None:
        statuses.extend(None if result is None else result.get("status") for result in results)
    return [None if result is None else result.get("answer") for result in results]


def _before_the_seam(case, monkeypatch, statuses=None):
    """The same dialogue with ``realize`` returning the sentence the dialogue built."""
    with monkeypatch.context() as patch:
        patch.setattr(reasoning_context, "realize", lambda meaning, intent, language: meaning["answer"])
        return _answers(case, statuses)


def _through_the_seam(case, monkeypatch, statuses, planned):
    """The dialogue through the real ``realize``; ``planned`` gets, per reply, whether it was realized."""
    def recording(meaning, intent, language):
        text, report = default_realizer().realize_with_report(meaning, intent, language)
        planned.append(bool(report.get("realized")))
        return text

    with monkeypatch.context() as patch:
        patch.setattr(reasoning_context, "realize", recording)
        return _answers(case, statuses)


def _numbers(text):
    return re.findall(r"\d+", re.sub(r"\([^)]*\)|\"[^\"]*\"|'[^']*'", " ", text or ""))


def test_realize_is_exported_with_the_declared_signature():
    assert marco.language.__all__ == ["realize"]
    assert list(inspect.signature(marco.language.realize).parameters) == ["meaning", "intent", "language"]
    assert inspect.signature(marco.language.realize).return_annotation in (str, "str")


def test_the_twenty_phrasings_cover_every_recorded_case():
    assert len(IDS) == 20 and set(IDS) == set(CASES)


@pytest.mark.parametrize("case_id", IDS)
def test_unrealized_turns_are_byte_identical_and_realized_turns_keep_the_value(case_id, monkeypatch):
    case = CASES[case_id]
    statuses_before, statuses, planned = [], [], []
    before = _before_the_seam(case, monkeypatch, statuses_before)
    answers = _through_the_seam(case, monkeypatch, statuses, planned)
    assert len(answers) == len(before) and statuses == statuses_before
    replies = [index for index, answer in enumerate(before) if answer is not None]
    assert [index for index, answer in enumerate(answers) if answer is not None] == replies
    assert len(planned) == len(replies)
    realized = {index for index, was in zip(replies, planned) if was}
    for index, answer in enumerate(answers):
        if index not in realized:
            assert answer == before[index]
        elif statuses[index] == "answered":
            # The value the reasoning produced: its numbers, and the word that carries it.
            assert _numbers(answer)[-1:] == _numbers(before[index])[-1:], (before[index], answer)
            assert before[index].rstrip(".").split()[-1] in answer, (before[index], answer)


# Sums and comparisons (G2.0(c)): the answer is no single fact; the proof lists each
# member's count last, and the realized sentence once said the last member's count.
# Values here are the test's own arithmetic over the stated amounts, not engine output.
SUMS = {
    "english": {"turns": ["Nell has 5 jars and Oto has 4.", "Nell gave Oto 2 jars.",
                          "How many jars do Nell and Oto have together?",
                          "Who has more jars now, Nell or Oto?"],
                "total": (2, 5 + 4), "more": (3, "Oto", "Nell")},
    "한국어": {"turns": ["보라는 사탕이 다섯 개 있어.", "현수는 사탕이 네 개 있어.",
                        "보라가 현수에게 사탕 두 개를 줬어.", "두 사람 합치면 사탕 몇 개야?"],
              "total": (3, 5 + 4), "more": None},
}


@pytest.mark.parametrize("language", sorted(SUMS))
def test_a_total_and_a_comparison_keep_the_value_the_reasoning_produced(language, monkeypatch):
    spec = SUMS[language]
    case = {"language": language, "turns": spec["turns"]}
    before = _before_the_seam(case, monkeypatch)
    statuses = []
    after = _answers(case, statuses)
    turn, total = spec["total"]
    assert statuses[turn] == "answered"
    assert _numbers(after[turn]) == _numbers(before[turn]) == [str(total)]
    if spec["more"] is not None:
        turn, winner, other = spec["more"]
        assert statuses[turn] == "answered"
        for answer in (before[turn], after[turn]):
            assert winner in answer and other not in answer


def test_every_answered_turn_passes_through_realize_once(monkeypatch):
    calls = []

    def recording(meaning, intent, language):
        calls.append((intent, language))
        return marco.language.realize(meaning, intent, language)

    monkeypatch.setattr(reasoning_context, "realize", recording)
    replies = 0
    for case_id in IDS:
        replies += sum(answer is not None for answer in _answers(CASES[case_id]))
    assert replies and len(calls) == replies
    # The dialogue passes the model it speaks for (request W1-3); its language is the pack it carries.
    from marco.language.realizer.packs import stem_of
    assert all(hasattr(language, "parser") for _intent, language in calls)
    assert {stem_of(language) for _intent, language in calls} == {"한국어", "english"}
