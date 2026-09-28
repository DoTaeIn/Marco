"""R2: §12 steps 3b, 5 and 6 composed from structure, Korean and English, §12 wording.

The turns are the §12 utterances as ``bench/seven_step_dialogue.py`` writes them.
The meaning each turn carries is the block ``docs/requests/W1-1.md`` asks the
engine to attach; ``w1_1_fields`` attaches it inside the test. The engine's
own sentence is replaced by a poison string before the realizer sees it, so a
passing turn cannot have been copied from it.
"""
import re

import pytest

import marco.reasoning.context as reasoning_context
from w1_harness import w1_1_fields

from bench.seven_step_dialogue import SCRIPTS, run
from marco.language.realizer import Realizer

POISON = "ENGINE-SENTENCE-NOT-READ"


class Poisoned(Realizer):
    """Realizes with the engine sentence replaced; remembers what the engine said."""

    def __init__(self):
        super().__init__()
        self.engine = []

    def realize(self, meaning, intent, language):
        self.engine.append(meaning.get("answer"))
        text, report = self.realize_with_report({**meaning, "answer": POISON}, intent, language)
        return meaning.get("answer") if not report["realized"] else text


@pytest.fixture(params=["english", "한국어"])
def dialogue(request, monkeypatch):
    language = request.param
    realizer = Poisoned()
    monkeypatch.setattr(reasoning_context, "realize", realizer.realize)
    with w1_1_fields():
        report = run(language)
    return language, report, realizer


def test_the_seven_steps_still_pass_their_structural_checks(dialogue):
    language, report, _realizer = dialogue
    assert report["passed"] == report["total"] == 7, [s for s in report["steps"] if not s["ok"]]


def _turn(report, text):
    return next(r for r in report["replies"] if r["input"] == text)


def test_3b_says_the_location_premise_is_missing_by_composition(dialogue):
    language, report, realizer = dialogue
    script = SCRIPTS[language]
    reply = _turn(report, script["turns"][3])
    realized = [r for r in realizer.reports if r.get("realized")]
    step = next(r for r in realized if "known" in [c["frame"] for c in r["clauses"]])
    assert reply["status"] == "unresolved" and POISON not in reply["answer"]
    assert step["held"] is False
    assert [c["frame"] for c in step["clauses"] if c["frame"] != "repair_note"] == ["known", "answered"]
    assert script["names"][1] in reply["answer"]
    assert not re.search(r"\d", reply["answer"].split("]")[-1] if language == "english" else
                         reply["answer"].split(")")[-1])
    assert [(m["frame"], m["polarity"]) for m in step["trace"]["meaning"] if m["frame"] != "repair_note"] == \
        [("known", False), ("answered", False)]
    assert reply["answer"] != realizer.engine[3]


def test_5_explains_the_correction_rules_and_evidence_by_composition(dialogue):
    language, report, realizer = dialogue
    script = SCRIPTS[language]
    reply = _turn(report, script["turns"][5])
    step = next(r for r in realizer.reports if r.get("realized") and "cause" in [c["frame"] for c in r["clauses"]])
    assert reply["status"] == "answered" and step["held"] is False
    frames = [c["frame"] for c in step["clauses"]]
    # conclusion first, then the correction, the rule of each effect and the statements used
    assert frames[:frames.index("cause")] == ["count", "count"]
    assert {"corrected", "new_event", "rule", "evidence"} <= set(frames)
    answer = reply["answer"]
    assert script["turns"][4] in answer                      # the correction, verbatim
    # The rules actually used: said in words, named by id only in the trace (goal W2.3).
    assert step["trace"]["rules"] == ["count_remove", "count_add"]
    assert "count_remove" not in answer and "count_add" not in answer
    assert answer != realizer.engine[5]


def test_6_names_the_candidates_and_picks_none_by_composition(dialogue):
    language, report, realizer = dialogue
    script = SCRIPTS[language]
    reply = _turn(report, script["turns"][6])
    step = next(r for r in realizer.reports if r.get("realized") and "choice" in [c["frame"] for c in r["clauses"]])
    assert reply["status"] == "unresolved" and step["held"] is False
    assert [c["frame"] for c in step["clauses"]] == ["reference", "choice"]
    assert all(name in reply["answer"] for name in script["names"])
    assert reply["answer"].rstrip().endswith("?")
    assert reply["answer"] != realizer.engine[6]


def test_every_turn_of_the_dialogue_is_realized_and_none_is_held(dialogue):
    _language, report, realizer = dialogue
    assert len(realizer.reports) == len(report["replies"])
    assert all(r["realized"] and not r["held"] for r in realizer.reports), \
        [r.get("reason") or r.get("clauses") for r in realizer.reports if not r["realized"] or r["held"]]


@pytest.mark.parametrize("language", ["english", "한국어"])
def test_the_live_seam_composes_3b_5_and_6(language, monkeypatch):
    """With the engine carrying its meaning (W1-1 applied), the live dialogue composes every step."""
    realizer = Realizer()
    monkeypatch.setattr(reasoning_context, "realize", realizer.realize)
    report = run(language)
    assert report["passed"] == 7
    steps = [realizer.reports[i] for i in (3, 5, 6)]
    assert all(r["realized"] and not r["held"] for r in steps), [r.get("reason") for r in steps]
    assert [c["frame"] for c in steps[2]["clauses"]] == ["reference", "choice"]
