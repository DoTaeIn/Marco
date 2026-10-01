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


# Experiment 6: the one wrong record. A transfer said after an unread statement by the same holder that names
# no thing (the thing left to a pronoun: used three of them) was recorded from the count before it, as if the
# unread statement had moved nothing (Nora has 7 pens, for 4). It is kept and held now, at every effort; an
# unread statement of another holder or of another thing holds nothing here.
UNREAD_PRONOUN = [
    ("english", [("Nora has 9 pens.", "rec"), ("Eli has 2 pens.", "rec"), ("Nora used three of them for a party.", "hold"),
                 ("Then Nora gave two pens to Eli.", "hold"), ("How many pens does Nora have?", "hold")]),
    ("english", [("Dr. Lambert has 9 pens.", "rec"), ("Eli has 2 pens.", "rec"),
                 ("Dr. Lambert used two of them for a craft class.", "hold"),
                 ("Dr. Lambert gave three pens to Eli.", "hold")]),
    ("한국어", [("한수는 연필이 9개 있어.", "rec"), ("은호는 연필이 2개 있어.", "rec"),
              ("한수가 그중 하나를 바자회 준비에 썼습니다.", "hold"), ("한수가 은호에게 연필을 두 개 줬어.", "hold")]),
]
UNREAD_OTHER = [
    ("english", [("Nora has 9 pens.", "rec"), ("Eli has 2 pens.", "rec"), ("Omar used three of them for a party.", "hold"),
                 ("Then Nora gave two pens to Eli.", "rec")]),
]


@pytest.mark.parametrize("n", range(len(UNREAD_PRONOUN)))
@pytest.mark.parametrize("effort", [0, 2])      # at effort 3 the use-up is read (experiment 7, ADJUNCT)
def test_a_transfer_after_an_unread_statement_of_its_giver_is_held(n, effort):
    language, dialogue = UNREAD_PRONOUN[n]
    assert play(language, effort, dialogue) == []


@pytest.mark.parametrize("n", range(len(UNREAD_OTHER)))
def test_an_unread_statement_of_another_holder_holds_no_transfer(n):
    language, dialogue = UNREAD_OTHER[n]
    assert play(language, 2, dialogue) == []


# Experiment 7: a use-up that names its holder and says what the things went to, in words that fill no slot
# (for a party, 전시 작품을 만들었다, 바자회 준비에 썼다). At effort 3 the statement read without one to three such
# words is a candidate (never a number or a word of a holder or thing of the conversation), a use-up by a
# counted holder, its thing from the conversation; any words may stand there (for a quink).
ADJUNCT = [
    ("english", [("Nora has 9 pens.", "rec"), ("Eli has 2 pens.", "rec"), ("Nora used three of them for a party.", "rec"),
                 ("Then Nora gave two pens to Eli.", "rec"), ("How many pens does Nora have?", 4),
                 ("How many pens does Eli have?", 4)]),
    ("english", [("Nora has 9 pens.", "rec"), ("Nora used four of them for a quink.", "rec"),
                 ("How many pens does Nora have?", 5)]),
    ("english", [("Nora has 9 pens.", "rec"), ("Nora has 4 cups.", "rec"),
                 ("Nora used two of them for the bake sale.", "rec"), ("How many cups does Nora have?", 2),
                 ("How many pens does Nora have?", 9)]),
    ("한국어", [("병훈은 서류가방이 24개 있습니다.", "rec"), ("병훈이 그중 4개로 전시 작품을 만들었습니다.", "rec"),
              ("병훈은 서류가방이 몇 개 있습니까?", 20)]),
    ("한국어", [("한수는 서류가방이 20개 있습니다.", "rec"), ("한수는 교과서가 3권 있습니다.", "rec"),
              ("한수가 시혁에게 서류가방을 두 개 보냈습니다.", "rec"), ("한수가 그중 하나를 바자회 준비에 썼습니다.", "rec"),
              ("한수는 서류가방이 몇 개 있습니까?", 17), ("한수는 교과서가 몇 권 있습니까?", 3)]),
]
ADJUNCT_HELD = [
    # the holder's count does not cover it: held
    ("english", [("Nora has 2 pens.", "rec"), ("Nora used three of them for a party.", "hold")]),
    # a holder the conversation never counted: held
    ("english", [("Nora has 9 pens.", "rec"), ("Omar used three of them for a party.", "hold")]),
]


@pytest.mark.parametrize("n", range(len(ADJUNCT)))
def test_a_use_up_with_a_phrase_that_fills_no_slot_is_read_at_effort_3(n):
    language, dialogue = ADJUNCT[n]
    assert play(language, 3, dialogue) == []


@pytest.mark.parametrize("n", [0, 1, 3, 4])
@pytest.mark.parametrize("effort", [0, 2])
def test_below_effort_3_the_use_up_is_not_read(n, effort):
    language, dialogue = ADJUNCT[n]
    at = next(i for i, (line, _e) in enumerate(dialogue) if "used" in line or "만들었" in line or "썼" in line)
    assert play(language, effort, dialogue[:at] + [(dialogue[at][0], "hold")]) == []


@pytest.mark.parametrize("n", range(len(ADJUNCT_HELD)))
def test_a_use_up_that_does_not_fit_is_held(n):
    language, dialogue = ADJUNCT_HELD[n]
    assert play(language, 3, dialogue) == []


def test_a_use_up_is_never_read_without_its_negation():
    # the words a repair may not change are never left out: 안 먹었어 is not 먹었어, didn't use is not used
    assert play("한국어", 3, [("누리는 단추가 다섯 개 있어.", "rec"), ("누리가 단추 두 개를 안 먹었어.", "hold"),
                            ("누리는 단추가 몇 개 있어?", "hold")]) == []
    # without its purpose phrase the English one is the negated statement main reads: nothing moves
    assert play("english", 3, [("Nora has 9 pens.", "rec"), ("Nora didn't use three of them for a party.", "rec"),
                               ("How many pens does Nora have?", 9)]) == []


# Identity graph, step 3 (statements): the reader names each fact's holder and thing, and the graph takes its
# nodes from them. A receiver said with a relation before its name (가윤 사위 태오에게) is the holder its name
# already is: one node, and the transfer moves its count (it recorded a new holder and answered 23 for 24).
def test_a_relation_named_receiver_is_one_node():
    current = context("한국어", 0)
    for line in ("가윤은 자두가 16개 있어.", "가윤 사위 태오는 자두가 23개 있어.", "가윤 삼촌 민혁은 자두가 7개 있어.",
                 "민혁이 가윤 사위 태오에게 자두 한 개 줬어."):
        current.turn(line, KG)
    graph = current.conversation_graph()
    assert sorted(node["name"] for node in graph.of_kind("holder")) == ["가윤", "민혁", "태오"]
    taeo, plum = graph.id_of("holder", "태오"), graph.id_of("thing", "자두")
    assert graph.value(taeo, plum) == 24
    assert "24" in current.turn("태오는 자두가 몇 개 있어?", KG)["answer"]


def test_a_list_of_two_things_names_one_holder_and_records_both():
    current = context("한국어", 0)
    current.turn("보늬는 연필 세 개, 컵 두 개를 가지고 있어.", KG)
    graph = current.conversation_graph()
    bonui = graph.id_of("holder", "보늬")
    assert [node["name"] for node in graph.of_kind("holder")] == ["보늬"]
    assert graph.value(bonui, graph.id_of("thing", "연필")) == 3 and graph.value(bonui, graph.id_of("thing", "컵")) == 2


# Identity graph, step 3 (statements): one thing, said three ways (two modifiers and a two-word name, one modifier
# and the last word, the modifier alone in a transfer), is one thing node; a mention whose words are all words of
# exactly one thing node, in order, is its alias (form short). Two things told apart by a modifier stay two; a
# bare head that fits both is its own node, never one of them.
def _things(language, lines, effort=3):
    current = context(language, effort)
    for line in lines:
        current.turn(line, KG)
    graph = current.conversation_graph()
    counts = {(graph.nodes[h]["name"], graph.nodes[t]["name"] if t else None): edge["value"]
              for (h, t), edge in graph.counts.items()}
    return graph, counts


def test_one_thing_said_three_ways_is_one_node():
    graph, counts = _things("english", ["Ada has five striped cotton beach towels.", "Bo has three striped towels.",
                                        "Ada gave two striped to Bo."])
    assert [n["name"] for n in graph.of_kind("thing")] == ["striped cotton beach towels"]
    assert counts == {("Ada", "striped cotton beach towels"): 3, ("Bo", "striped cotton beach towels"): 5}
    towels = graph.id_of("thing", "striped cotton beach towels")
    assert graph.id_of("thing", "striped towels") == towels
    assert ("striped towels", "short") in {(a["text"], a["form"]) for a in graph.aliases if a["node"] == towels}


def test_two_things_told_apart_by_a_modifier_stay_two_and_a_bare_head_is_its_own():
    graph, counts = _things("english", ["Ada has four red pens.", "Bo has two blue pens.", "Cy has three pens."])
    assert sorted(n["name"] for n in graph.of_kind("thing")) == ["blue pens", "pens", "red pens"]
    assert counts[("Cy", "pens")] == 3 and counts[("Ada", "red pens")] == 4 and counts[("Bo", "blue pens")] == 2


def test_a_short_mention_said_first_is_the_node_of_the_longer():
    graph, _counts = _things("english", ["Bo has three striped towels.", "Ada has five striped cotton beach towels."])
    assert [n["name"] for n in graph.of_kind("thing")] == ["striped towels"]


# Identity graph, step 3: a thing said with fewer of its words or in its other number (one striped towel, one towel,
# for striped cotton beach towels) is the holder's thing node; from effort 2 the statement is read with the key the
# conversation counts that node by, checked by replay; two thing nodes that fit (red towels, blue towels) tie: held.
TOWELS = [("Ada has five striped cotton beach towels.", "rec"), ("Bo has three striped towels.", "rec")]


@pytest.mark.parametrize("effort", [2, 3])
def test_a_thing_said_in_its_other_number_or_by_its_head_is_its_node(effort):
    assert play("english", effort, TOWELS + [("Ada gave two striped to Bo.", "rec"),
                                            ("Ada gave Bo one striped towel.", "rec"), ("Ada gave Bo one towel.", "rec"),
                                            ("How many striped cotton beach towels does Ada have?", 1),
                                            ("How many striped towels does Bo have?", 7)]) == []
    graph, _counts = _things("english", [line for line, _e in TOWELS] + ["Ada gave Bo one towel."], effort)
    assert sorted(n["name"] for n in graph.of_kind("holder")) == ["Ada", "Bo"]
    assert [n["name"] for n in graph.of_kind("thing")] == ["striped cotton beach towels"]


@pytest.mark.parametrize("effort", [0, 1])
def test_below_effort_2_a_thing_said_by_its_head_is_refused(effort):
    assert play("english", effort, TOWELS + [("Ada gave Bo one towel.", "hold")]) == []


def test_a_head_that_fits_two_things_of_the_holder_holds():
    assert play("english", 3, [("Ada has four red towels.", "rec"), ("Ada has two blue towels.", "rec"),
                               ("Bo has one red towel.", "rec"), ("Ada gave Bo one towel.", "hold")]) == []


# G7-5: a Korean holding with a modified thing names the holder by its name alone; what stands between the
# topic-marked name and the counted noun belongs to the thing (미경, 줄무늬 면 수건; not 미경 줄무늬 면, 수건).
@pytest.mark.parametrize("line", ["제 친구 미경은 줄무늬 면 수건이 5개 있어.", "미경한테 줄무늬 면 수건이 5개 있어.",
                                  "미경은 줄무늬 면 수건을 5개 가지고 있어."])
def test_a_modified_thing_stays_with_the_thing(line):
    graph, counts = _things("한국어", [line], 0)
    assert [n["name"] for n in graph.of_kind("holder")] == ["미경"]
    assert [n["name"] for n in graph.of_kind("thing")] == ["줄무늬 면 수건"]
    assert counts == {("미경", "줄무늬 면 수건"): 5}


# _read_unsaid_thing on nodes: a holder counted with its thing not said (기 대표님에게는 열 개 있어) and a transfer
# that names no thing from it: the thing node from the conversation, and that count keyed to it, one candidate.
@pytest.mark.parametrize("effort", [2, 3])
def test_a_transfer_with_no_thing_from_a_holder_counted_with_no_thing(effort):
    assert play("한국어", effort, [("세훈은 핸드백이 열한 개 있어.", "rec"), ("기 대표님에게는 열 개 있어.", "rec"),
                                  ("기 대표님이 세훈에게 세 개를 줬어.", "rec"), ("기 대표님은 핸드백이 몇 개 있어?", 7),
                                  ("세훈은 핸드백이 몇 개 있어?", 14)]) == []


def test_g7_5_a_name_reply_finds_the_holder_of_a_modified_thing():
    # docs/requests/G7-5.md: the holder is the name, the words before the counted noun are the thing
    assert play("한국어", 3, [("제 친구 미경은 줄무늬 면 수건이 5개 있어.", "rec"), ("제 친구 수아는 줄무늬 수건이 3개 있어.", "rec"),
                            ("그 친구는 수건이 몇 개야?", "hold"), ("수아요.", 3)]) == []
    graph, _counts = _things("한국어", ["제 친구 미경은 줄무늬 면 수건이 5개 있어.", "제 친구 수아는 줄무늬 수건이 3개 있어."])
    assert sorted(n["name"] for n in graph.of_kind("holder")) == ["미경", "수아"]
    assert [n["name"] for n in graph.of_kind("thing")] == ["줄무늬 면 수건"]


# A container and its content are two things. A thing name of container structure has a head (the container: the
# words before the pack's partitive word, packs of quills; a last declared counter noun, 깃펜 묶음) and a content
# (quills, 깃펜). A shorter mention is the same thing only when it has a word of the head (bags, for bags of flour;
# 묶음); the content said alone is another thing node, in either order of mention.
@pytest.mark.parametrize("language,lines,things,counts", [
    ("english", ["Nora has 43 packs of quills.", "Nora has 8 extra quills."], ["packs of quills", "quills"],
     {("Nora", "packs of quills"): 43, ("Nora", "quills"): 8}),
    ("english", ["Nora has 8 quills.", "Nora has 43 packs of quills."], ["packs of quills", "quills"],
     {("Nora", "packs of quills"): 43, ("Nora", "quills"): 8}),
    ("english", ["Omar has 6 boxes of pens.", "Omar has 20 pens."], ["boxes of pens", "pens"],
     {("Omar", "boxes of pens"): 6, ("Omar", "pens"): 20}),
    ("한국어", ["노라는 깃펜 묶음이 43개 있어.", "노라는 깃펜이 8개 있어."], ["깃펜", "깃펜 묶음"],
     {("노라", "깃펜 묶음"): 43, ("노라", "깃펜"): 8}),
    ("한국어", ["노라는 깃펜이 8자루 있어.", "노라는 깃펜 상자가 5개 있어."], ["깃펜", "깃펜 상자"],
     {("노라", "깃펜 상자"): 5, ("노라", "깃펜"): 8}),
])
def test_a_container_and_its_content_are_two_things(language, lines, things, counts):
    graph, found = _things(language, lines)
    assert sorted(n["name"] for n in graph.of_kind("thing")) == sorted(things)
    assert found == counts


def test_the_head_of_a_container_said_alone_is_still_the_container():
    graph, counts = _things("english", ["Nora has 5 bags of flour.", "Eli has 2 bags.", "Nora gave Eli one bag of flour."])
    assert [n["name"] for n in graph.of_kind("thing")] == ["bags of flour"]
    assert counts == {("Nora", "bags of flour"): 4, ("Eli", "bags of flour"): 3}
    graph, counts = _things("english", ["Nora has 5 bags of flour.", "Nora gave Eli two bags."])
    assert [n["name"] for n in graph.of_kind("thing")] == ["bags of flour"] and counts[("Nora", "bags of flour")] == 3
    graph, counts = _things("한국어", ["노라는 깃펜 상자가 5개 있어.", "수아는 상자가 2개 있어."])
    assert [n["name"] for n in graph.of_kind("thing")] == ["깃펜 상자"]
    assert counts == {("노라", "깃펜 상자"): 5, ("수아", "깃펜 상자"): 2}


def test_a_transfer_of_the_content_is_not_read_as_the_container():
    # quills said alone after packs of quills: the giver has no count of quills, and the packs are not moved
    assert play("english", 3, [("Nora has 43 packs of quills.", "rec"), ("Eli has 2 packs of quills.", "rec"),
                               ("Nora gave Eli five quills.", "hold"),
                               ("How many packs of quills does Eli have?", "hold")]) == []


# One thing counted in two units is two counts. 노라는 깃펜이 43묶음 있어. 노라는 깃펜이 8개 있어. said 8 in place of
# 43, and both 몇 개 and 몇 묶음 answered 8. From the second unit on, each count is kept by its unit (the pack's
# first unit under the key, another unit as the container thing: 깃펜 묶음); a question in the pack's first unit
# reads that count, any other is held (the reply's counter word is the first unit's: request G7-6); a change said
# in a unit moves that unit's count; nothing is converted.
TWO_UNITS = [("노라는 깃펜이 43묶음 있어.", "rec"), ("노라는 깃펜이 8개 있어.", "rec")]


@pytest.mark.parametrize("effort", [0, 3])
def test_one_thing_in_two_units_is_two_counts(effort):
    assert play("한국어", effort, TWO_UNITS + [("노라는 깃펜이 몇 개 있어?", 8), ("노라는 깃펜이 몇 묶음 있어?", "hold"),
                                              ("노라는 깃펜이 몇 자루 있어?", "hold")]) == []
    # the count kept in 묶음 is never said as pieces: the reply's counter word is the pack's first unit (G7-6)
    current = context("한국어", effort)
    for line, _e in TWO_UNITS:
        current.turn(line, KG)
    assert "43" not in str((current.turn("노라는 깃펜이 몇 묶음 있어?", KG) or {}).get("answer"))
    graph, counts = _things("한국어", [line for line, _e in TWO_UNITS], effort)
    assert sorted(n["name"] for n in graph.of_kind("thing")) == ["깃펜", "깃펜 묶음"]
    assert counts == {("노라", "깃펜 묶음"): 43, ("노라", "깃펜"): 8}


def test_a_change_said_in_a_unit_moves_that_units_count():
    lines = TWO_UNITS + [("수아는 깃펜이 2개 있어.", "rec"), ("노라가 수아에게 깃펜을 두 묶음 줬어.", "rec")]
    assert play("한국어", 3, lines + [("노라는 깃펜이 몇 묶음 있어?", "hold"), ("노라는 깃펜이 몇 개 있어?", 8),
                                     ("수아는 깃펜이 몇 개 있어?", 2)]) == []
    _graph, counts = _things("한국어", [line for line, _e in lines])
    assert counts[("노라", "깃펜 묶음")] == 41 and counts[("노라", "깃펜")] == 8 and counts[("수아", "깃펜")] == 2


def test_one_unit_said_in_two_counters_stays_one_count():
    # a count said in one unit and a change in another counter (자루, 개) is the same count, as before
    assert play("한국어", 3, [("노라는 연필이 다섯 자루 있어.", "rec"), ("수아는 연필이 2개 있어.", "rec"),
                            ("노라가 수아에게 연필을 두 개 줬어.", "rec"), ("노라는 연필이 몇 자루 있어?", 3),
                            ("수아는 연필이 몇 개 있어?", 4)]) == []


def test_a_measure_word_before_the_thing_heads_a_container():
    for lines in (["Nora has 43 dozen quills.", "Nora has 8 quills."], ["Nora has 8 quills.", "Nora has 43 dozen quills."]):
        graph, counts = _things("english", lines)
        assert sorted(n["name"] for n in graph.of_kind("thing")) == ["dozen quills", "quills"]
        assert counts == {("Nora", "dozen quills"): 43, ("Nora", "quills"): 8}
    assert play("english", 3, [("Nora has 43 dozen quills.", "rec"), ("Nora has 8 quills.", "rec"),
                               ("How many quills does Nora have?", 8),
                               ("How many dozen quills does Nora have?", 43)]) == []


# The readings a conversation kept for its statements (a candidate step's winner) are in its snapshot: a restored
# conversation replays those statements the same way. Without them a statement after the restart that needs a
# candidate step was refused, and the question after it held (the earlier statement was read fresh in the check).
@pytest.mark.parametrize("language,before,after", [
    ("english", ["Nora has 7 pens.", "Eli has 2 pens.", "Nora gave Eli three blorp."],
     [("Nora gave Eli two zeb.", "rec"), ("How many pens does Nora have?", 2)]),
    ("english", ["Ada has five striped cotton beach towels.", "Bo has three striped towels.", "Ada gave Bo one towel."],
     [("Ada gave Bo one striped towel.", "rec"), ("How many striped towels does Bo have?", 5)]),
    ("한국어", ["세훈은 핸드백이 열한 개 있어.", "기 대표님에게는 열 개 있어.", "기 대표님이 세훈에게 세 개를 줬어."],
     [("기 대표님이 세훈에게 두 개를 줬어.", "rec"), ("기 대표님은 핸드백이 몇 개 있어?", 5)]),
])
def test_a_restored_conversation_keeps_the_readings_it_chose(language, before, after):
    import json
    current = context(language, 3)
    for line in before:
        current.turn(line, KG)
    snapshot = json.loads(json.dumps(current.snapshot(), ensure_ascii=False))
    assert snapshot["readings"]
    restored = context(language, 3)
    restored.restore(snapshot)
    for line, expected in after:
        assert outcome(restored.turn(line, KG) or {}, expected), line


def test_a_snapshot_without_readings_restores_and_a_bad_one_is_refused():
    current = context("english", 3)
    current.turn("Nora has 7 pens.", KG)
    snapshot = current.snapshot()
    assert "readings" not in snapshot
    restored = context("english", 3)
    restored.restore(snapshot)
    assert outcome(restored.turn("How many pens does Nora have?", KG) or {}, 7)
    with pytest.raises(ValueError):
        context("english", 3).restore(dict(snapshot, readings=["Nora has 7 pens."]))
