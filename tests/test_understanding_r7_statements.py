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
