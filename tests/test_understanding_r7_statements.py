"""Round 7, statements (goal G7-S): statements refused or held by a state check are read again through
candidates from the conversation, validated by replaying it, ranked (``_rank_candidates``), and kept only
on a clear win (amendments A1, A2, A4).

Batch 1, S3: a transfer whose giver or receiver has no count under its key, where an earlier statement
counted the same holder and thing under another key because a case particle stayed in the name (the thing
left unsaid: 도 부장님에게는 열한 권 있어 -> ``도 부장에게``; a place phrase: 보람은 트럭에 사과를 12개 싣고 있어 ->
``보람 트럭에 사과``). At effort 2 and above the earlier statement is keyed as the transfer names it when that
makes the conversation fit; at effort 0 and 1 the statement is refused or held as on main.

Expected per turn: "rec" recorded, "hold" any hold, "vague" the count-not-known hold, an int the answered
count. "#SNAP" snapshots the context and restores it into a new one.
"""
import re

import pytest

from pack_model import development_model
from marco.reasoning.context import ReasoningContext

KG = "graphs/graph_일상추론.kg"
_MODELS = {}


def model(language):
    if language not in _MODELS:
        _MODELS[language] = development_model(language)
    return _MODELS[language]


def context(language, effort):
    other = "english" if language == "한국어" else "한국어"
    return ReasoningContext(model=model(language), companions=[model(other)], effort=effort)


def outcome(result, expected):
    status = result.get("status")
    meaning = result.get("meaning") or {}
    answer = str(result.get("answer") or "")
    if isinstance(expected, int):
        return status == "answered" and re.search(r"(?<!\d)%d(?!\d)" % expected, answer) is not None
    if expected == "rec":
        return status == "observed"
    if expected == "vague":
        return status == "unresolved" and meaning.get("reason") == "vague_count"
    return status == "unresolved"


def play(language, effort, dialogue):
    current, failed = context(language, effort), []
    for step in dialogue:
        if step == "#SNAP":
            saved = current.snapshot()
            current = context(language, effort)
            current.restore(saved)
            continue
        line, expected = step
        result = current.turn(line, KG) or {}
        if not outcome(result, expected):
            failed.append((line, expected, result.get("status"), (result.get("meaning") or {}).get("reason"),
                           str(result.get("answer"))[:80]))
    return failed


# (dialogue at effort 2 and 3, the same dialogue's expectations at effort 0 and 1)
OTHER_KEY = [
    # a place phrase kept in the giver's name
    ([("보람은 트럭에 사과를 12개 싣고 있어.", "rec"), ("시온은 사과가 4개 있어.", "rec"),
      ("보람이 시온에게 사과를 5개 줬어.", "rec"), ("보람은 사과가 몇 개 있어?", 7), ("시온은 사과가 몇 개 있어?", 9)],
     [("보람은 트럭에 사과를 12개 싣고 있어.", "rec"), ("시온은 사과가 4개 있어.", "rec"),
      ("보람이 시온에게 사과를 5개 줬어.", "hold"), ("보람은 사과가 몇 개 있어?", "hold")]),
    # a place phrase kept in the receiver's name, a titled giver
    ([("시온은 수레에 귤을 6개 싣고 있어.", "rec"), ("남 과장님은 귤이 10개 있어.", "rec"),
      ("남 과장님이 시온에게 귤을 3개 줬어.", "rec"), ("시온은 귤이 몇 개 있어?", 9), ("남 과장님은 귤이 몇 개 있어?", 7)],
     [("시온은 수레에 귤을 6개 싣고 있어.", "rec"), ("남 과장님은 귤이 10개 있어.", "rec"),
      ("남 과장님이 시온에게 귤을 3개 줬어.", "hold"), ("시온은 귤이 몇 개 있어?", "hold")]),
    # the thing left unsaid and the case kept on a titled holder; a native numeral; after a snapshot
    ([("다온은 공책이 8권 있어.", "rec"), ("도 부장님에게는 열한 권 있어.", "rec"),
      ("도 부장님이 다온에게 공책을 두 권 주었어.", "rec"), "#SNAP", ("도 부장님은 공책이 몇 권 있어?", 9),
      ("다온은 공책이 몇 권 있어?", 10), ("도 부장님이 다온에게 공책을 세 권 주었어.", "rec"),
      ("도 부장님은 공책이 몇 권 있어?", 6)],
     [("다온은 공책이 8권 있어.", "rec"), ("도 부장님에게는 열한 권 있어.", "rec"),
      ("도 부장님이 다온에게 공책을 두 권 주었어.", "hold"), ("다온은 공책이 몇 권 있어?", "hold")]),
    # the first person with a place phrase
    ([("나는 수레에 귤을 열다섯 개 싣고 있어.", "rec"), ("하진은 귤이 2개 있어.", "rec"),
      ("내가 하진에게 귤을 네 개 빌려줬어.", "rec"), ("하진은 귤이 몇 개 있어?", 6)],
     [("나는 수레에 귤을 열다섯 개 싣고 있어.", "rec"), ("하진은 귤이 2개 있어.", "rec"),
      ("내가 하진에게 귤을 네 개 빌려줬어.", "hold")]),
]

# held at every effort: no candidate survives, or two tie
HELD = [
    # the earlier count does not cover the transfer: the candidate breaks count_can_move
    [("보람은 트럭에 사과를 2개 싣고 있어.", "rec"), ("보람이 시온에게 사과를 5개 줬어.", "hold"),
     ("보람은 사과가 몇 개 있어?", "hold")],
    # two earlier counts of the same holder and thing under two keys: a tie, nothing is chosen
    [("하진은 트럭에 귤을 5개 싣고 있어.", "rec"), ("하진은 수레에 귤을 4개 싣고 있어.", "rec"),
     ("하진이 시온에게 귤을 2개 줬어.", "hold"), ("하진은 귤이 몇 개 있어?", "hold")],
    # another holder's key with a place phrase is no candidate
    [("시온은 트럭에 사과를 9개 싣고 있어.", "rec"), ("보람이 시온에게 사과를 1개 줬어.", "hold")],
]


@pytest.mark.parametrize("n", range(len(OTHER_KEY)))
@pytest.mark.parametrize("effort", [2, 3])
def test_other_key_is_read_at_effort_2_and_above(n, effort):
    assert play("한국어", effort, OTHER_KEY[n][0]) == []


@pytest.mark.parametrize("n", range(len(OTHER_KEY)))
@pytest.mark.parametrize("effort", [0, 1])
def test_other_key_is_held_below_effort_2(n, effort):
    assert play("한국어", effort, OTHER_KEY[n][1]) == []


@pytest.mark.parametrize("n", range(len(HELD)))
@pytest.mark.parametrize("effort", [0, 3])
def test_no_survivor_or_a_tie_holds(n, effort):
    assert play("한국어", effort, HELD[n]) == []


def test_the_choice_and_its_ranking_are_in_the_trace():
    current = context("한국어", 3)
    for line in ("보람은 트럭에 사과를 12개 싣고 있어.", "시온은 사과가 4개 있어."):
        current.turn(line, KG)
    result = current.turn("보람이 시온에게 사과를 5개 줬어.", KG)
    assert result["status"] == "observed"
    assert [r["winner"] for r in current._trace_rankings] == ["보람 트럭에 사과 -> 보람 사과"]
    assert current._trace_rankings[0]["decided_by"] == "only"


# Experiment 2: a statement that names no thing (Nora gave Eli three., 가람이 나래에게 세 개를 줬어.) when its
# holder counts two things. At effort 2 and above each thing a named holder counts, and the thing of the
# statement just before, is a candidate; the one that fits and agrees with the conversation wins. Below
# effort 2 the statement is refused as on main.
UNSAID_THING = [
    ("english",
     [("Nora has 7 pens.", "rec"), ("Nora has 3 cups.", "rec"), ("Eli has 2 pens.", "rec"),
      ("Nora gave Eli three.", "rec"), ("How many pens does Nora have?", 4), ("How many cups does Nora have?", 3),
      ("How many pens does Eli have?", 5), ("Nora gave Eli two cups.", "rec"), ("Nora lost one.", "rec"),
      ("How many pens does Nora have?", 4)],
     [("Nora has 7 pens.", "rec"), ("Nora has 3 cups.", "rec"), ("Eli has 2 pens.", "rec"),
      ("Nora gave Eli three.", "hold"), ("How many pens does Eli have?", "hold")]),
    ("english",
     [("Mr. Keller has twelve spoons.", "rec"), ("Mr. Keller has four bowls.", "rec"), ("Ada has one spoon.", "rec"),
      ("Mr. Keller handed Ada five.", "rec"), ("How many spoons does Mr. Keller have?", 7),
      ("How many spoons does Ada have?", 6)],
     [("Mr. Keller has twelve spoons.", "rec"), ("Mr. Keller has four bowls.", "rec"), ("Ada has one spoon.", "rec"),
      ("Mr. Keller handed Ada five.", "hold")]),
    ("한국어",
     [("가람은 연필이 7개 있어.", "rec"), ("가람은 컵이 3개 있어.", "rec"), ("나래는 연필이 2개 있어.", "rec"),
      ("가람이 나래에게 세 개를 줬어.", "rec"), ("가람은 연필이 몇 개 있어?", 4), ("나래는 연필이 몇 개 있어?", 5),
      ("가람은 두 개를 썼어.", "rec"), ("가람은 연필이 몇 개 있어?", 2), ("가람은 컵이 몇 개 있어?", 3)],
     [("가람은 연필이 7개 있어.", "rec"), ("가람은 컵이 3개 있어.", "rec"), ("나래는 연필이 2개 있어.", "rec"),
      ("가람이 나래에게 세 개를 줬어.", "hold"), ("나래는 연필이 몇 개 있어?", "hold")]),
]

UNSAID_HELD = [
    # only one of the two things covers the amount, and it is the other thing the conversation talked about
    # last: state decides, the one that covers it
    ("english", [("Nora has 7 pens.", "rec"), ("Nora has 2 cups.", "rec"), ("Nora gave Eli five.", "rec"),
                 ("How many pens does Nora have?", 2), ("How many cups does Nora have?", 2)]),
    # neither covers it: held, and so is the count it may have moved
    ("english", [("Nora has 3 pens.", "rec"), ("Nora has 2 cups.", "rec"), ("Nora gave Eli five.", "hold"),
                 ("How many pens does Nora have?", "hold")]),
    # both cover it and nothing in the conversation prefers one: a tie, held, and so is the count it may have moved
    ("한국어", [("가람은 연필이 7개 있어.", "rec"), ("가람은 컵이 6개 있어.", "rec"), ("나래는 접시가 2개 있어.", "rec"),
              ("가람이 나래에게 세 개를 줬어.", "hold"), ("가람은 연필이 몇 개 있어?", "hold")]),
]


@pytest.mark.parametrize("n", range(len(UNSAID_THING)))
@pytest.mark.parametrize("effort", [2, 3])
def test_an_unsaid_thing_is_read_at_effort_2_and_above(n, effort):
    language, dialogue, _below = UNSAID_THING[n]
    assert play(language, effort, dialogue) == []


@pytest.mark.parametrize("n", range(len(UNSAID_THING)))
@pytest.mark.parametrize("effort", [0, 1])
def test_an_unsaid_thing_is_refused_below_effort_2(n, effort):
    language, _dialogue, below = UNSAID_THING[n]
    assert play(language, effort, below) == []


@pytest.mark.parametrize("n", range(len(UNSAID_HELD)))
def test_an_unsaid_thing_is_chosen_by_state_or_held(n):
    language, dialogue = UNSAID_HELD[n]
    assert play(language, 3, dialogue) == []


# Experiment 3: a Korean holding said with the thing left out and the count with its subject particle
# (X에게는 N개가 있어, X한테는 N개가 있습니다): one declared form (하루에게는 18개가 있다, elided) reads it as the
# holder's count of a thing not said; the thing comes from the conversation (experiment 2's candidates) from
# effort 2. The seven-step location question (그 사람은 어디 있어?) still reads as a location question.
UNSAID_HOLDING = [
    [("용호한테 살구가 14개 있습니다.", "rec"), ("천 차장님에게는 열 개가 있습니다.", "rec"),
     ("우 차장님한테는 여덟 개가 있습니다.", "rec"), ("천 차장님이 감 소장님한테 살구 다섯 개를 주었습니다.", "rec"),
     ("천 차장님은 살구가 몇 개 있습니까?", 5), ("우 차장님은 살구가 몇 개 있습니까?", 8)],
    [("누리는 단추가 아홉 개 있어.", "rec"), ("누리 동생 다올에게는 세 개가 있어.", "rec"),
     ("다올은 단추가 몇 개 있어?", 3), ("누리가 다올에게 단추를 두 개 줬어.", "rec"), ("다올은 단추가 몇 개 있어?", 5)],
]


@pytest.mark.parametrize("n", range(len(UNSAID_HOLDING)))
@pytest.mark.parametrize("effort", [2, 3])
def test_a_holding_with_the_thing_left_out_is_read(n, effort):
    assert play("한국어", effort, UNSAID_HOLDING[n]) == []


def test_a_holding_with_the_thing_left_out_at_effort_0_answers_nothing_wrong():
    assert play("한국어", 0, [("용호한테 살구가 14개 있습니다.", "rec"), ("천 차장님에게는 열 개가 있습니다.", "rec"),
                            ("천 차장님이 감 소장님한테 살구 다섯 개를 주었습니다.", "hold"),
                            ("천 차장님은 살구가 몇 개 있습니까?", "hold")]) == []


def test_the_location_question_is_still_a_location_question():
    current = context("한국어", 3)
    for line in ("민수는 사과가 두 개 있어.", "민수는 부엌에 있어."):
        current.turn(line, KG)
    result = current.turn("그 사람은 어디 있어?", KG)
    assert result["status"] == "answered" and "부엌" in str(result["answer"])


# Experiment 4: a statement read completely whose thing slot holds a word that is no thing of this
# conversation, refused by the state (the giver has no count under "<giver> <word>"). From effort 2 the reading
# without the word is a candidate, its thing from the conversation; the reading as said is one too. The slot is
# found by position, so any word can stand there, including ones no pack declares (blorp, zeb zeb, quix, 뿌뿌).
# A word that could be a counted noun (a plural after an amount above one, or any word in a language without
# number marking, or after an amount of one) stays the thing unless it is a word of a counted thing or a
# declared counter: taking out a thing that was said would answer about another.
PENS = [("Nora has 7 pens.", "rec"), ("Eli has 2 pens.", "rec"), ("Dr. Lambert has nine pens.", "rec"),
        ("Ms. Daniels has three pens.", "rec")]
WRONG_THING = [
    ("english", PENS + [("Nora gave Eli three blorp.", "rec"), ("How many pens does Nora have?", 4),
                        ("How many pens does Eli have?", 5)]),
    ("english", PENS + [("Nora handed Eli two zeb zeb.", "rec"), ("How many pens does Nora have?", 5)]),
    ("english", PENS + [("Nora gave three zeb zeb to Eli.", "rec"), ("How many pens does Eli have?", 5)]),
    ("english", PENS + [("Dr. Lambert gave three quix to Ms. Daniels.", "rec"),
                        ("How many pens does Dr. Lambert have?", 6), ("How many pens does Ms. Daniels have?", 6)]),
    ("english", PENS + [("Dr. Lambert lent Ms. Daniels four vorn.", "rec"),
                        ("How many pens does Dr. Lambert have?", 5)]),
    # a counter of the counted thing, the giver counting two things: the thing of the statement before wins
    ("english", [("Nora has 5 bundles of herbs.", "rec"), ("Nora has 3 cups.", "rec"),
                 ("Eli has 2 bundles of herbs.", "rec"), ("Nora gave Eli three bundles.", "rec"),
                 ("How many bundles of herbs does Nora have?", 2), ("How many bundles of herbs does Eli have?", 5),
                 ("How many cups does Nora have?", 3)]),
    ("한국어", [("가람은 서류가 일곱 묶음 있어.", "rec"), ("나래는 서류가 두 묶음 있어.", "rec"),
              ("가람이 나래에게 묶음 세 개를 줬어.", "rec"), ("가람은 서류가 몇 묶음 있어?", 4)]),
]
WRONG_THING_HELD = [
    # a plural noun after three: a thing said, never counted for Nora; not read as her pens
    ("english", PENS + [("Nora gave Eli three apples.", "hold"), ("How many pens does Nora have?", "hold")]),
    # after one, any word agrees as a noun: held
    ("english", PENS + [("Nora gave Eli one blorp.", "hold")]),
    # Korean marks no number: an unknown word in the thing slot stays the thing
    ("한국어", [("가람은 서류가 일곱 묶음 있어.", "rec"), ("나래는 서류가 두 묶음 있어.", "rec"),
              ("가람이 나래에게 뿌뿌 세 개를 줬어.", "hold")]),
    # the reading without the word does not fit either: the giver cannot cover it
    ("english", PENS + [("Nora gave Eli nine blorp.", "hold"), ("How many pens does Nora have?", "hold")]),
]


@pytest.mark.parametrize("n", range(len(WRONG_THING)))
@pytest.mark.parametrize("effort", [2, 3])
def test_a_word_in_the_thing_slot_that_is_no_thing_is_read_without(n, effort):
    language, dialogue = WRONG_THING[n]
    assert play(language, effort, dialogue) == []


@pytest.mark.parametrize("n", range(len(WRONG_THING)))
@pytest.mark.parametrize("effort", [0, 1])
def test_below_effort_2_the_word_stays_the_thing_and_is_refused(n, effort):
    language, dialogue = WRONG_THING[n]
    at = next(i for i, (_line, expected) in enumerate(dialogue) if i >= 2 and _line.count(" ") >= 4
              and expected == "rec" and ("gave" in _line or "handed" in _line or "lent" in _line or "줬어" in _line))
    assert play(language, effort, dialogue[:at] + [(dialogue[at][0], "hold")]) == []


@pytest.mark.parametrize("n", range(len(WRONG_THING_HELD)))
@pytest.mark.parametrize("effort", [0, 3])
def test_a_word_that_could_be_the_thing_is_held(n, effort):
    language, dialogue = WRONG_THING_HELD[n]
    assert play(language, effort, dialogue) == []
