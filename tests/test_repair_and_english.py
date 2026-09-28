"""Repair-and-report, English as the core language, and the checks behind them.

Every test names its language explicitly (a model or a language argument);
none relies on which pack happens to be the default, except the test of the
default itself.
"""
import ast
import json
from pathlib import Path
import re

import pytest

from pack_model import development_model
from reasoning_context import ReasoningContext

ROOT = Path(__file__).resolve().parents[1]


def korean():
    return ReasoningContext(model=development_model("한국어"))


def english():
    return ReasoningContext(model=development_model("english"))


def state(context):
    from bench.seven_step_dialogue import _state
    return _state(context)


def test_english_is_the_one_declared_default():
    from language_components import default_language, _language_path
    flags = [p.stem for p in (ROOT / "styles").glob("*.json")
             if json.loads(p.read_text(encoding="utf-8")).get("default_model_language") is True]
    assert flags == ["english"]
    assert default_language() == "english"
    assert _language_path().name == "english.json"
    assert development_model().sources[0]["path"] == "styles/english.json"


def test_unmatched_korean_is_repaired_reported_and_answered_in_one_turn():
    context = korean()
    result = context.turn("민수는 사과 다섯 개가 있어")
    assert result["status"] == "observed"
    report = result["repair"][0]
    assert report["rule"] == "구슬은 18개 있다"
    assert [step["op"] for step in report["operations"]] == ["particle_drop", "particle_move"]
    assert report["cost"] <= report["bound"]
    # The note leaves the spoken reply (goal W2.4): a particle-only reading changes no meaning,
    # so nothing of it is said; the full note is returned when asked what was changed.
    assert "구슬은 18개 있다" not in result["answer"] and "[" not in result["answer"]
    assert state(context) == {"민수 사과": "5"}
    assert "구슬은 18개 있다" in context.turn("뭘 고쳤어?")["answer"]
    assert context.turn("민수 사과는 몇 개 남았어?")["answer"] == "5개입니다."


def test_repair_over_the_bound_is_held_and_names_what_was_needed():
    result = korean().turn("민수 사과는 정말 다섯 개 있어")
    assert result["status"] == "unresolved"
    assert result["repair"][0]["status"] == "over_bound"
    assert result["repair"][0]["cost"] > result["repair"][0]["bound"]
    assert "'정말' 건너뛰기" in result["answer"]
    held = english().turn("Minsu really has five apples.")
    assert held["status"] == "unresolved" and "skip 'really'" in held["answer"]


def test_repair_only_moves_drops_or_adds_declared_forms():
    parser = development_model("한국어").parser()
    declared = set(parser.repair["insert_particles"]) | set(parser.case_particles)
    for text in ["민수는 사과 다섯 개가 있어", "그 사람은 어디 있어", "민수가 지연에게 두 개 줬어"]:
        _meanings, _derivations, report = parser._repair(text)
        typed = text.split()
        for word in report["reading"].split():
            assert word in typed or any(word == stem + p for stem in [w for t in typed for w in (t,) + tuple(
                t[:-len(q)] for q in declared if t.endswith(q))] for p in declared | {""}), (text, word)


def test_state_under_a_repair_says_so_and_a_correction_retracts_it():
    context = korean()
    context.turn("민수는 사과 다섯 개가 있어")
    facts = context.snapshot()["replay"]["facts"]
    assert facts[0]["evidence"]["normalization"]["repair"]["status"] == "repaired"
    context.turn("정정: 민수는 사과 다섯 개가 있어 => 민수 사과는 3개 있다.")
    assert state(context) == {"민수 사과": "3"}
    assert "repair" not in (context.snapshot()["replay"]["facts"][0]["evidence"].get("normalization") or {})


def test_why_names_every_repair_the_answer_rests_on():
    context = korean()
    for text in ["민수는 사과 다섯 개, 지연은 두 개가 있어.", "민수가 지연에게 두 개 줬어.", "지연은 지금 몇 개야?"]:
        context.turn(text)
    why = context.turn("왜 그렇게 됐어?")
    assert why["status"] == "answered"
    assert '"지연은 두 개가 있어" → "지연은 두 개 있어"' in why["answer"]


@pytest.mark.parametrize("language", ["english", "한국어"])
def test_seven_step_dialogue_runs_in_each_language(language):
    from bench.seven_step_dialogue import run
    report = run(language)
    assert report["passed"] == report["total"] == 7, [s for s in report["steps"] if not s["ok"]]


@pytest.mark.parametrize("language", ["english", "한국어"])
def test_seven_step_dialogue_runs_through_the_ui_turn_handler(language):
    from bench.seven_step_ui import run
    report = run(language)
    assert report["passed"] == report["total"], [r for r in report["rows"] if not r["ok"]]


def test_removing_a_declared_rule_stops_the_sentence_that_needed_it():
    from bench.removal_test import run
    report = run()
    assert report["passed"] == report["total"], [r for r in report["rows"] if not r["ok"]]


def test_a_wrong_repair_rule_and_a_wrong_composition_rule_are_caught():
    from bench.error_injection import run
    report = run()
    assert report["caught"] == report["total"], [r for r in report["rows"] if not r["caught"]]
    assert {row["kind"] for row in report["rows"]} == {"wrong_repair_rule", "wrong_composition_rule"}


def test_repair_checks_hold_what_they_must_hold():
    from bench.repair_checks import run
    report = run()
    assert report["passed"] == report["total"], report["rows"]
    assert "wrong_assertion" not in report["outcomes"]


def test_two_packs_in_one_process_do_not_share_declarations():
    ko, en = development_model("한국어").parser(), development_model("english").parser()
    assert en.case_particles == [] and en.slot_particles == [] and en.particle_mates == {}
    assert ko.case_particles and ko.romanization and not en.romanization
    first, second = korean(), english()
    first.turn("민수 사과는 5개 있다.")
    second.turn("Minsu has 5 apples.")
    assert first.turn("민수 사과는 몇 개 남았어?")["answer"] == "5개입니다."
    assert second.turn("How many apples does Minsu have?")["answer"] == "5 apples."
    assert state(first) == {"민수 사과": "5"} and state(second) == {"Minsu apples": "5"}


def test_english_forms_come_from_the_declared_lexicon_or_the_declared_suffix():
    from marco.language.hangul import inflect
    grammar = development_model("english").parser().inflection_grammar
    assert [f["text"] for f in inflect("give", "past", "participle", grammar, kind="regular")] == ["given"]
    assert [f["text"] for f in inflect("walk", "past", "participle", grammar, kind="regular")] == ["walked"]
    assert [f["text"] for f in inflect("give", "past", "plain", grammar, kind="regular")] == ["gave"]


def test_names_are_matched_across_scripts_by_the_declared_romanization():
    from marco.language.hangul import romanize
    table = development_model("한국어").parser().romanization
    assert [romanize(name, table) for name in ["민수", "지연", "서연"]] == ["minsu", "jiyeon", "seoyeon"]


def test_a_question_in_the_other_language_uses_the_same_events():
    context = ReasoningContext(model=development_model("한국어"), companions=[development_model("english")])
    context.turn("민수 사과는 5개 있다.")
    context.turn("지연 사과는 2개 있다.")
    context.turn("민수가 지연에게 사과 2개를 줬다.")
    asked = context.turn("How many apples does Jiyeon have now?")
    assert asked["status"] == "answered" and asked["answer"] == "4 apples."
    assert asked["cross_language"]["mapping"] == {"Jiyeon": "지연", "apples": "사과"}
    assert context.turn("How many apples does Sora have now?")["status"] == "unresolved"


# The dialogue path must carry no language: no Hangul sentence, word list or
# pattern in these modules. What may remain are internal state tags and pack
# schema keys — single tokens without spaces or punctuation.
DIALOGUE_MODULES = ["reasoning_context.py", "relational_semantics.py", "marco/language/frames.py",
                    "graph_inference.py", "marco/language/numerals.py", "pack_model.py", "action_runtime.py",
                    "marco/learning/concepts.py", "language_components.py"]


PROSE = re.compile("[\uac00-\ud7a3]+ +[\uac00-\ud7a3]+|[\uac00-\ud7a3][.!?]\\s*$")


def test_the_prose_detector_sees_a_korean_sentence():
    assert PROSE.search("이 대화에서 확인한 조건만으로는 답을 결정할 수 없습니다.")
    assert PROSE.search("입니다.")
    assert not PROSE.search("language pack '부정' needs 연결, 어간 and 갈래")
    assert not PROSE.search("조회")


def test_no_korean_text_left_on_the_dialogue_path():
    hangul = re.compile("[가-힣ㄱ-ㆎ]")
    offenders = []
    for name in DIALOGUE_MODULES:
        tree = ast.parse((ROOT / name).read_text(encoding="utf-8"))
        docstrings = {id(node.body[0].value) for node in ast.walk(tree)
                      if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef))
                      and node.body and isinstance(node.body[0], ast.Expr)
                      and isinstance(node.body[0].value, ast.Constant)}
        for node in ast.walk(tree):
            if (isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings
                    and hangul.search(node.value)):
                # A schema key or tag is one token; an English message may
                # quote a pack key. Korean prose has two Hangul words in a row
                # or ends a Hangul word with sentence punctuation.
                prose = PROSE.search(node.value)
                if prose:
                    offenders.append((name, node.lineno, node.value))
    assert offenders == []
