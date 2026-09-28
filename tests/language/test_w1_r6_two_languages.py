"""R6: one reasoning pass, two languages.

The §12 dialogue runs once in each language. The reasoning path
(``ReasoningContext._turn`` and the parser's ``answer``) is counted; then every
turn's Meaning Graph, built once, is realized in Korean and in English. The
counts do not move while realizing, both realizations pass the check, and
they say the same numbers.
"""
import copy
import re

import pytest

import marco.reasoning.context as reasoning_context
import relational_semantics
from w1_harness import play

from bench.seven_step_dialogue import SCRIPTS
from marco.language.realizer import Realizer


def _numbers(text):
    return sorted(re.findall(r"\d+", re.sub(r"\"[^\"]*\"|'[^']*'|\([^)]*\)", " ", text)))


@pytest.mark.parametrize("language", ["한국어", "english"])
def test_one_pass_two_languages(language, monkeypatch):
    calls = {"turn": 0, "answer": 0}
    turn, answer = reasoning_context.ReasoningContext._turn, relational_semantics.RelationalParser.answer

    def counted_turn(self, *args, **kwargs):
        calls["turn"] += 1
        return turn(self, *args, **kwargs)

    def counted_answer(self, *args, **kwargs):
        calls["answer"] += 1
        return answer(self, *args, **kwargs)
    monkeypatch.setattr(reasoning_context.ReasoningContext, "_turn", counted_turn)
    monkeypatch.setattr(relational_semantics.RelationalParser, "answer", counted_answer)

    script = SCRIPTS[language]
    other = "english" if language == "한국어" else "한국어"
    rows, _context = play(language, script["turns"], companion=other)
    assert calls["turn"] == len(script["turns"])
    reasoning = dict(calls)

    realizer = Realizer()
    said = 0
    for _text, result, _report in rows:
        graph = realizer.build_graph(copy.deepcopy(result), "styles/%s.json" % language)
        assert graph is not None
        ko, ko_report = realizer.realize_graph(copy.deepcopy(graph), "한국어")
        en, en_report = realizer.realize_graph(copy.deepcopy(graph), "english")
        assert not ko_report["held"] and not en_report["held"], (ko_report, en_report)
        assert ko_report["trace"]["meaning"] == en_report["trace"]["meaning"]
        assert ko_report["trace"]["intent"] == en_report["trace"]["intent"]
        assert _numbers(ko) == _numbers(en), (ko, en)
        said += 1
    assert said == len(script["turns"])
    assert calls == reasoning          # realizing twice ran no reasoning


def test_names_and_items_cross_by_declared_links_not_by_spelling():
    realizer = Realizer()
    result = {"status": "answered", "answer": "x",
              "transitions": [{"fact": ["지연 사과", "count", "4"], "evidence": {"turn": 1}}]}
    graph = realizer.build_graph(result, "styles/한국어.json")
    prop = graph["props"][0]
    prop.pop("focus"), prop.pop("answer")
    graph["acts"][0]["props"] = [prop]
    english, report = realizer.realize_graph(graph, "english")
    # 지연 -> Jiyeon by the pack's romanization table; 사과 -> apples by its sense link.
    assert english == "Jiyeon has 4 apples." and report["trace"]["check"] == ["parsed"]
    unlinked = {"status": "answered", "answer": "x",
                "transitions": [{"fact": ["지연 연필", "count", "4"], "evidence": {"turn": 1}}]}
    graph = realizer.build_graph(unlinked, "styles/한국어.json")
    text, _report = realizer.realize_graph(graph, "english")
    assert "연필" in text      # a word with no sense link stays in its own language, untranslated
