"""W3: realizer round 3 — close the round-3 requests, say every kind.

W3.1 (G3-1) no realizer string carries the old repair word; the label is the pack's;
W3.2 (G3-2) a count of one agrees in both languages; English irregular plurals and
     singulars come from the pack's declared table ("1 knives" and held geese are gone);
W3.3 (G3-3) a reply the realizer holds makes the turn a hold, with a reason the scorers read;
W3.4 (G3-4) fewer, the same number, a tie, and the state before or after an event are
     composed in both languages.

Every dialogue here is written for this file (names and things no other set uses).
"""
import copy
import json
from pathlib import Path
import re
import sys

import pytest

from marco.language.realizer import default_realizer, last_report
from marco.language.realizer.grammar import Grammar
from marco.language.realizer.packs import HERE, Language
from pack_model import development_model
from reasoning_context import ReasoningContext

ROOT = Path(__file__).resolve().parents[2]
OTHER = {"english": "한국어", "한국어": "english"}
if str(ROOT / "bench") not in sys.path:
    sys.path.insert(0, str(ROOT / "bench"))
import composition_gate as cg  # noqa: E402
import dialogue_gate as gate  # noqa: E402


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


def composed(result):
    """The reply was composed by the realizer, is exactly its sentence, and was not held."""
    report = result["_report"]
    assert report["realized"] and not report["held"], report.get("reason") or report.get("clauses")
    assert report["text"] == result["answer"]
    return report


# W3.1 -----------------------------------------------------------------------------------

OLD_REPAIR_WORD = "수선"      # the word the owner replaced (G3.7); spelled by code point here


def test_no_realizer_string_carries_the_old_repair_word():
    files = sorted(p for p in (ROOT / "marco/language/realizer").iterdir() if p.suffix in (".py", ".json"))
    assert len(files) >= 10
    carrying = [p.name for p in files if OLD_REPAIR_WORD in p.read_text(encoding="utf-8")]
    assert carrying == []


def test_the_spoken_repair_label_is_the_word_the_pack_encloses():
    lang = Language("한국어")
    template = lang.parser.data["context_replies"]["repaired"]
    label = template.split("[", 1)[1].split("]", 1)[0]
    assert lang.decl["lexicon"]["repair"]["word"] == label != OLD_REPAIR_WORD
    results, _context = play("한국어", ["해솔은 도토리 다섯 개가 있어", "해솔은 도토리가 몇 개야?", "왜?"])
    why = results[-1]
    composed(why)
    assert label + "으로 읽은 말" in why["answer"] and OLD_REPAIR_WORD not in why["answer"]


# W3.2 -----------------------------------------------------------------------------------

def english_grammar():
    return Grammar(Language("english"))


@pytest.mark.parametrize("plural,one", [
    ("knives", "knife"), ("geese", "goose"), ("children", "child"), ("sheep", "sheep"), ("wolves", "wolf"),
    ("Geese", "Goose"), ("plums", "plum"), ("jars", "jar"), ("shoes", "shoe"), ("knife", "knife"),
    ("goose", "goose"),
])
def test_the_singular_comes_from_the_packs_declared_table_then_its_rules(plural, one):
    assert english_grammar().singular_of(plural) == one


@pytest.mark.parametrize("plural,said,one", [
    ("boxes", "Ilse has one box.", "box"), ("cookies", "Ilse has a cookie", "cookie"),
    ("berries", "Ilse has one berry", "berry"),
])
def test_two_singulars_the_rules_allow_are_told_apart_only_by_the_users_words(plural, said, one):
    grammar = english_grammar()
    assert grammar.singular_of(plural) is None
    assert grammar.singular_of(plural, said.split()) == one
    assert grammar.singular_of(plural, "Ilse has one".split()) is None


def test_a_word_linked_to_a_thing_agrees_with_its_count():
    grammar = english_grammar()
    assert grammar.choose_number(["goose", "geese"], "1") == "goose"
    assert grammar.choose_number(["goose", "geese"], "3") == "geese"
    assert grammar.choose_number(["knives", "knife"], "2") == "knives"
    assert grammar.choose_number(["goose"], "4") == "geese"           # the table's plural of a listed singular
    assert grammar.choose_number(["sled"], "2") == "sled"             # no pair declared: said as linked


@pytest.mark.parametrize("statement,question,said", [
    ("Haru has one knife.", "How many knives does Haru have?", "1 knife."),
    ("Ilse has one goose.", "How many geese does Ilse have?", "1 goose."),
    ("Ilse has one child.", "How many children does Ilse have?", "1 child."),
    ("Ilse has one sheep.", "How many sheep does Ilse have?", "1 sheep."),
    ("Ilse has one jar of quince jam.", "How many jars of quince jam does Ilse have?", "1 jar of quince jam."),
    ("Ilse has one cookie.", "How many cookies does Ilse have?", "1 cookie."),
    ("Ilse has one box of chalk.", "How many boxes of chalk does Ilse have?", "1 box of chalk."),
    ("Ilse has 3 wolves.", "How many wolves does Ilse have?", "3 wolves."),
])
def test_one_of_a_thing_is_said_in_the_singular_and_answered(statement, question, said):
    results, _context = play("english", [statement, question])
    answer = results[-1]
    assert answer["status"] == "answered"
    composed(answer)
    assert answer["answer"] == said


def test_a_change_that_leaves_one_says_one():
    results, _context = play("english", ["Haru has 3 knives and Ilse has 2 knives.", "Haru gave Ilse one knife.",
                                         "Haru gave Ilse one knife.", "Ilse has 2 geese.", "Ilse lost one goose."])
    assert results[2]["answer"] == "Recorded. Now Haru has 1 knife and Ilse has 4."
    assert results[4]["answer"] == "Recorded. Now Ilse has 1 goose."
    for result in results[1:]:
        composed(result)


def test_korean_counts_one_with_its_counter_and_no_plural():
    results, _context = play("한국어", ["하루는 칼이 1개 있어.", "하루는 칼이 몇 개 있어?"])
    assert results[-1]["answer"] == "1개입니다."
    composed(results[-1])
    lang = Language("한국어")
    assert lang.decl["grammar"]["noun_number"] is None and not Grammar(lang).declared_number()
    assert Grammar(lang).singular_head(["칼"], "1") == ["칼"]


def test_one_of_a_thing_from_another_language_is_answered_not_held():
    # A Korean word with no English sense is shown as it is; the English pack keys "one X" on
    # X's plural by rule, and the check accepts exactly that keying for a count of one.
    results, _context = play("한국어", ["해랑은 썰매가 4개, 다온은 2개 있습니다.", "다온이 해랑에게 썰매 1개를 줬습니다.",
                                      "How many does Daon have now?"])
    answer = results[-1]
    assert answer["status"] == "answered" and answer["_report"]["language"] == "english"
    composed(answer)
    assert answer["answer"] == "1 썰매."


# W3.3 -----------------------------------------------------------------------------------

@pytest.fixture
def no_count_expression(monkeypatch):
    """The default realizer with every count expression of English removed: no answer about a count
    can be said, so the realizer holds it (a declaration fault, injected)."""
    decl = json.loads((HERE / "english.json").read_text(encoding="utf-8"))
    decl["expressions"]["count"] = []
    realizer = default_realizer()
    monkeypatch.setattr(realizer, "overrides", {"english": decl})
    monkeypatch.setattr(realizer, "_languages", {})
    return realizer


def test_a_held_answer_is_a_hold_with_the_realizers_reason(no_count_expression):
    results, context = play("english", ["Juno has 4 figs.", "How many figs does Juno have?", "Why?"])
    held = results[1]
    assert held["_report"]["held"] and held["answer"] == "This answer is on hold."
    assert held["status"] == "unresolved"
    assert held["meaning"]["act"] == "hold" and held["meaning"]["reason"] == "not_phrased"
    assert held["meaning"]["held"]["act"] == "inform" and held["meaning"]["held"]["query"][0] == "Juno figs"
    check = held["verification"]["checks"][-1]
    assert check == {"ok": False, "reason": "realizer_hold", "blocked": ["count"]}
    # A later why does not explain an answer that was never given.
    assert results[2]["meaning"]["reason"] == "explain_nothing"


def test_a_said_answer_keeps_its_status():
    results, _context = play("english", ["Juno has 4 figs.", "How many figs does Juno have?"])
    assert results[1]["status"] == "answered" and results[1]["meaning"]["act"] == "inform"
    assert not any(c.get("reason") == "realizer_hold" for c in results[1]["verification"]["checks"])


def test_the_scorers_read_a_held_answer_as_a_hold(no_count_expression):
    dialogue = {"id": "w3-held", "language": "en",
                "turns": [{"n": 1, "say": "Juno has 4 figs."}, {"n": 2, "say": "How many figs does Juno have?"}]}
    answers = cg.run([dialogue])
    asked = answers["w3-held"][1]
    assert asked["verdict"] == "조건부족" and asked["known"] is False
    assert gate.status(asked) == "held"
    report = cg.score([dialogue], answers)
    assert report["total"]["passed_through"] == 0
    assert report["by_act"]["hold"]["held"] == 1 and report["by_act"]["answer"]["spoken"] == 0


# W3.4 -----------------------------------------------------------------------------------

KINDS = {
    "english": {
        "state": ["Tove has 5 plums.", "Una has 3 plums."],
        "fewer": ("Who has fewer plums, Tove or Una?", "Una has fewer plums."),
        "more": ("Who has more plums, Tove or Una?", "Tove has more plums."),
        "different": ("Do Tove and Una have the same number of plums?",
                      "No, Tove and Una do not have the same number of plums. Tove has 5 plums and Una has 3."),
        "event": "Tove gave Una 2 plums.",
        "before": ("How many plums did Una have before Tove gave Una 2 plums?",
                   "Before Tove gave Una plums, Una had 3 plums.", 3),
        "after": ("After Tove gave Una 2 plums, how many plums did Tove have?",
                  "After Tove gave Una plums, Tove had 3 plums.", 3),
        "evened": "Una gave Tove 1 plum.",
        "tie": ("Who has more plums, Tove or Una?", "Tove and Una both have 4 plums."),
        "tie_fewer": ("Who has fewer plums, Tove or Una?", "Tove and Una both have 4 plums."),
        "same": ("Do Tove and Una have the same number of plums?", "Yes, Tove and Una both have 4 plums."),
        "one_side": "Tove ate 1 plum.",
        "quoted": ("How many plums did Tove have before Tove ate 1 plum?",
                   'Before "Tove ate 1 plum", Tove had 4 plums.', 4),
    },
    "한국어": {
        "state": ["아라는 자두가 5개 있어.", "보라는 자두가 3개 있어."],
        "fewer": ("아라와 보라 중 누가 자두가 더 적어?", "자두는 보라가 더 적습니다."),
        "more": ("아라와 보라 중 누가 자두가 더 많아?", "자두는 아라가 더 많습니다."),
        "different": ("아라와 보라는 자두가 같아?",
                      "아니요, 아라와 보라는 자두 수가 같지 않습니다. 아라 자두는 5개, 보라는 3개입니다."),
        "event": "아라가 보라에게 자두 2개를 줬어.",
        "before": ("아라가 보라에게 자두를 주기 전에 보라는 자두가 몇 개 있었어?", "아라가 보라에게 자두를 주기 전에는 3개였습니다.", 3),
        "after": ("아라가 보라에게 자두를 준 뒤에 아라는 자두가 몇 개 있었어?", "아라가 보라에게 자두를 준 뒤에는 3개였습니다.", 3),
        "evened": "보라가 아라에게 자두 1개를 줬어.",
        "tie": ("아라와 보라 중 누가 자두가 더 많아?", "아라와 보라는 자두가 4개로 같습니다."),
        "tie_fewer": ("아라와 보라 중 누가 자두가 더 적어?", "아라와 보라는 자두가 4개로 같습니다."),
        "same": ("아라와 보라는 자두가 같아?", "네, 아라와 보라는 자두가 4개로 같습니다."),
        "one_side": "아라가 자두 1개를 먹었어.",
        "quoted": ("아라가 자두를 먹기 전에 아라는 자두가 몇 개 있었어?",
                   '"아라가 자두 1개를 먹었어"라는 일이 있기 전에는 4개였습니다.', 4),
    },
}
ORDER = ["fewer", "more", "different", "event", "before", "after", "evened", "tie", "tie_fewer", "same",
         "one_side", "quoted"]


def kinds_dialogue(language):
    spec = KINDS[language]
    lines = list(spec["state"])
    for key in ORDER:
        lines.append(spec[key][0] if isinstance(spec[key], tuple) else spec[key])
    return lines


@pytest.mark.parametrize("language", ["english", "한국어"])
def test_every_comparison_and_time_kind_is_composed(language):
    spec = KINDS[language]
    results, _context = play(language, kinds_dialogue(language))
    by_key = dict(zip(ORDER, results[len(spec["state"]):]))
    for key in ORDER:
        result = by_key[key]
        composed(result)
        if not isinstance(spec[key], tuple):
            assert result["status"] == "observed"
            continue
        assert result["status"] == "answered", (key, result["answer"])
        assert result["answer"] == spec[key][1], key
    kinds = {key: by_key[key]["meaning"].get("kind") for key in ("fewer", "more", "different", "tie", "tie_fewer",
                                                                    "same")}
    assert kinds == {"fewer": "fewer", "more": "more", "different": "different", "tie": "tie",
                     "tie_fewer": "tie", "same": "same"}
    for key in ("before", "after", "quoted"):
        # One quantity is stated, the answer's: the event is named without its amount, or quoted.
        assert gate.quantities(gate.asserted(by_key[key]["answer"])) == {spec[key][2]}, key
        assert by_key[key]["meaning"]["time"]["order"] in ("before", "after")


@pytest.mark.parametrize("language", ["english", "한국어"])
def test_a_lead_that_answers_yes_or_no_agrees_with_its_sentence(language):
    from marco.language.realizer import Realizer
    realizer = Realizer()
    lang = realizer.language(language)
    grammar = Grammar(lang)
    from marco.language.realizer.check import Checker
    from marco.language.realizer.grammar import ClauseRealizer
    checker = Checker(lang, grammar, lambda: ClauseRealizer(grammar))
    no = realizer._lead(lang, grammar, checker, "answer_no", "formal", polarity=False)
    yes = realizer._lead(lang, grammar, checker, "answer_yes", "formal", polarity=True)
    answers = lang.parser.data["comparison_answers"]
    assert no == answers["different"][0].rstrip() and yes == answers["same"][0].rstrip()
    assert realizer._lead(lang, grammar, checker, "answer_no", "formal", polarity=True) is None
    assert realizer._lead(lang, grammar, checker, "answer_yes", "formal", polarity=False) is None
    # a no said where the pack's words read yes is refused by the check
    swapped = copy.deepcopy(lang.decl)
    swapped["leads"]["answer_no"]["parts"] = [{"lex": "answer_yes"}]
    faulty = Realizer(overrides={language: swapped})
    flang = faulty.language(language)
    fgrammar = Grammar(flang)
    fchecker = Checker(flang, fgrammar, lambda: ClauseRealizer(fgrammar))
    assert faulty._lead(flang, fgrammar, fchecker, "answer_no", "formal", polarity=False) is None


def test_the_seven_step_the_twenty_phrasings_and_these_kinds_are_all_composed():
    own = [{"id": "w3-kinds-%s" % code, "language": code,
            "turns": [{"n": n, "say": line} for n, line in enumerate(kinds_dialogue(language), 1)]}
           for language, code in (("english", "en"), ("한국어", "ko"))]
    dialogues = cg.seven_step_dialogues() + cg.phrasing_dialogues() + own
    report = cg.score(dialogues, cg.run(dialogues))
    assert not report["execution_errors"]
    assert report["total"]["composed"] == report["total"]["spoken"], report["not_composed"]
    assert report["total"]["spoken"] == sum(len(d["turns"]) for d in dialogues)
    said = {row["turn"]: row["spoken"] for row in report["rows"]}
    assert said["w3-kinds-en#%d" % (2 + ORDER.index("fewer") + 1)] == KINDS["english"]["fewer"][1]
    assert re.search(r"4개로 같습니다", said["w3-kinds-ko#%d" % (2 + ORDER.index("tie") + 1)])
