"""A transfer to a holder whose count was never said.

The giver's count moves and is answered; the receiver's count is not known (count_unknown, the state
"has some" already uses): a question about it is held, until a count for the receiver is said, which is
its count now. A giver with no count said, and taking away more than a holder is known to have, stay
holds; giving more than a stated count is a contradiction.

Two halves with disjoint names, things and amounts: BUILD was used while fixing, CHECK was run once
at the end. Expected outcome per turn: "rec" recorded, "hold" any hold, "vague" the count-not-known
hold, "contra" the contradiction hold, an int the answered count. "#SNAP" snapshots the context and
restores it into a new one.
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


def context(language):
    other = "english" if language == "한국어" else "한국어"
    return ReasoningContext(model=model(language), companions=[model(other)])


BUILD = {
    "english": [
        [("Nora has 7 pens.", "rec"), ("Nora gave 3 pens to Eli.", "rec"),
         ("How many pens does Nora have?", 4), ("How many pens does Eli have?", "vague")],
        [("Nora has 8 pens.", "rec"), ("Nora gave 2 pens to Eli.", "rec"), ("Eli has 5 pens.", "rec"),
         ("How many pens does Eli have?", 5), ("How many pens does Nora have?", 6)],
        [("Mira has 9 cups.", "rec"), ("Mira lent Tom 2 cups.", "rec"), ("Mira handed 3 cups to Tom.", "rec"),
         ("How many cups does Tom have?", "vague"), ("How many cups does Mira have?", 4)],
        [("Mira has 6 cups.", "rec"), ("Mira gave Tom 1 cup.", "rec"), ("Mira gave Tom 2 cups.", "rec"), "#SNAP",
         ("How many cups does Tom have?", "vague"), ("How many cups does Mira have?", 3)],
        [("Tom gave 2 cups to Mira.", "hold"), ("How many cups does Mira have?", "hold")],
        [("Sam has 2 pens.", "rec"), ("Sam gave 5 pens to Pia.", "contra"), ("How many pens does Sam have?", "hold")],
        [("Sam has 7 pens.", "rec"), ("Sam gave Pia 3 pens.", "rec"),
         ("correct: Sam gave Pia 3 pens. => Sam gave Pia 1 pen.", "rec"),
         ("How many pens does Sam have?", 6), ("How many pens does Pia have?", "vague")],
        [("Nils has 9 cups.", "rec"), ("Nils gave 4 cups to Ola.", "rec"), ("Ola gave 1 cup to Pia.", "rec"),
         ("How many cups does Ola have?", "vague"), ("How many cups does Nils have?", 5),
         ("How many cups does Pia have?", "vague")],
        [("Nils has 9 cups.", "rec"), ("Nils gave 2 cups to Ola.", "rec"), ("Ola gave 5 cups to Pia.", "hold"),
         ("How many cups does Ola have?", "hold")],
        [("Eli got 3 pens.", "rec"), ("How many pens does Eli have?", "vague"), ("Eli has 4 pens.", "rec"),
         ("How many pens does Eli have?", 4)],
        [("Ola lost 2 cups.", "hold"), ("How many cups does Ola have?", "hold")],
        [("Tom has 7 pens.", "rec"), ("Eli got 2 pens from Tom.", "rec"),
         ("How many pens do Tom and Eli have together?", "hold"), ("How many pens does Tom have?", 5)],
        [("Pia has 5 cups.", "rec"), ("Sam has 2 cups.", "rec"), ("Pia gave 3 cups to Sam.", "rec"),
         ("How many cups does Sam have?", 5), ("How many cups does Pia have?", 2)],
    ],
    "한국어": [
        [("보라는 연필 7개가 있어.", "rec"), ("보라가 하늘에게 연필 3개를 줬어.", "rec"),
         ("보라는 연필이 몇 개야?", 4), ("하늘은 연필이 몇 개야?", "vague")],
        [("보라는 연필이 8개 있어.", "rec"), ("보라가 하늘에게 연필 2개를 줬어.", "rec"), ("하늘은 연필이 5개 있어.", "rec"),
         ("하늘은 연필이 몇 개야?", 5), ("보라는 연필이 몇 개야?", 6)],
        [("미나는 컵이 9개 있어.", "rec"), ("미나가 준호한테 컵 2개를 빌려줬어.", "rec"), ("미나가 준호에게 컵 3개를 줬어.", "rec"),
         ("준호는 컵이 몇 개야?", "vague"), ("미나는 컵이 몇 개야?", 4)],
        [("미나는 컵이 6개 있어.", "rec"), ("미나가 준호에게 컵 1개를 줬어.", "rec"), ("미나가 준호에게 컵 2개를 줬어.", "rec"),
         "#SNAP", ("준호는 컵이 몇 개야?", "vague"), ("미나는 컵이 몇 개야?", 3)],
        [("준호가 미나에게 컵 2개를 줬어.", "hold"), ("미나는 컵이 몇 개야?", "hold")],
        [("세라는 연필이 2개 있어.", "rec"), ("세라가 지유에게 연필 5개를 줬어.", "contra"), ("세라는 연필이 몇 개야?", "hold")],
        [("세라는 연필이 7개 있어.", "rec"), ("세라가 지유에게 연필 3개를 줬어.", "rec"),
         ("정정: 세라가 지유에게 연필 3개를 줬어. => 세라가 지유에게 연필 1개를 줬어.", "rec"),
         ("세라는 연필이 몇 개야?", 6), ("지유는 연필이 몇 개야?", "vague")],
        [("하람이는 컵이 9개 있어.", "rec"), ("하람이가 도윤이에게 컵 4개를 줬어.", "rec"), ("도윤이가 지유에게 컵 1개를 줬어.", "rec"),
         ("도윤이는 컵이 몇 개야?", "vague"), ("하람이는 컵이 몇 개야?", 5), ("지유는 컵이 몇 개야?", "vague")],
        [("하람이는 컵이 9개 있어.", "rec"), ("하람이가 도윤이에게 컵 2개를 줬어.", "rec"),
         ("도윤이가 지유에게 컵 5개를 줬어.", "hold"), ("도윤이는 컵이 몇 개야?", "hold")],
        [("하늘이는 연필 3개를 샀어.", "rec"), ("하늘이는 연필이 몇 개야?", "vague"), ("하늘이는 연필이 4개 있어.", "rec"),
         ("하늘이는 연필이 몇 개야?", 4)],
        [("도윤이는 컵 2개를 잃어버렸어.", "hold"), ("도윤이는 컵이 몇 개야?", "hold")],
        [("준호는 연필이 7개 있어.", "rec"), ("하늘이가 준호에게서 연필 2개를 받았어.", "rec"),
         ("준호와 하늘이는 연필이 모두 몇 개야?", "hold"), ("준호는 연필이 몇 개야?", 5)],
        [("지유는 컵이 5개 있어.", "rec"), ("세라는 컵이 2개 있어.", "rec"), ("지유가 세라에게 컵 3개를 줬어.", "rec"),
         ("세라는 컵이 몇 개야?", 5), ("지유는 컵이 몇 개야?", 2)],
    ],
}

CHECK = {
    "english": [
        [("Greta has 15 stamps.", "rec"), ("Greta gave 12 stamps to Hugo.", "rec"),
         ("How many stamps does Hugo have?", "vague"), ("How many stamps does Greta have?", 3)],
        [("Ines has 20 spoons.", "rec"), ("Ines gave Jonas 10 spoons.", "rec"), ("Jonas has 13 spoons.", "rec"),
         ("How many spoons does Jonas have?", 13), ("How many spoons does Ines have?", 10)],
        [("Kai has 30 candles.", "rec"), ("Kai lent Lena 11 candles.", "rec"), ("Kai handed 12 candles to Lena.", "rec"),
         ("How many candles does Lena have?", "vague"), ("How many candles does Kai have?", 7)],
        [("Omar has 18 ribbons.", "rec"), ("Omar gave Rosa 10 ribbons.", "rec"), "#SNAP",
         ("How many ribbons does Omar have?", 8), ("How many ribbons does Rosa have?", "vague")],
        [("Rosa gave 14 ribbons to Omar.", "hold"), ("How many ribbons does Omar have?", "hold")],
        [("Greta has 11 spoons.", "rec"), ("Greta gave 14 spoons to Ines.", "contra"),
         ("How many spoons does Greta have?", "hold")],
        [("Hugo has 22 candles.", "rec"), ("Hugo gave Kai 12 candles.", "rec"),
         ("correct: Hugo gave Kai 12 candles. => Hugo gave Kai 10 candles.", "rec"),
         ("How many candles does Hugo have?", 12), ("How many candles does Kai have?", "vague")],
        [("Lena has 26 stamps.", "rec"), ("Lena gave 16 stamps to Jonas.", "rec"), ("Jonas gave 10 stamps to Rosa.", "rec"),
         ("How many stamps does Jonas have?", "vague"), ("How many stamps does Lena have?", 10),
         ("How many stamps does Rosa have?", "vague")],
        [("Lena has 26 stamps.", "rec"), ("Lena gave 11 stamps to Jonas.", "rec"), ("Jonas gave 13 stamps to Rosa.", "hold"),
         ("How many stamps does Jonas have?", "hold")],
        [("Omar got 17 candles.", "rec"), ("How many candles does Omar have?", "vague"), ("Omar has 19 candles.", "rec"),
         ("How many candles does Omar have?", 19)],
        [("Ines lost 12 ribbons.", "hold"), ("How many ribbons does Ines have?", "hold")],
        [("Kai has 24 spoons.", "rec"), ("Hugo got 14 spoons from Kai.", "rec"),
         ("How many spoons do Kai and Hugo have together?", "hold"), ("How many spoons does Kai have?", 10)],
        [("Rosa has 20 candles.", "rec"), ("Greta received 13 candles from Rosa.", "rec"), ("Greta has 15 candles.", "rec"),
         ("Greta gave 10 candles to Rosa.", "rec"), ("How many candles does Rosa have?", 17),
         ("How many candles does Greta have?", 5)],
    ],
    "한국어": [
        [("서준이는 우표가 15장 있어요.", "rec"), ("서준이가 유나에게 우표 12장을 줬어요.", "rec"),
         ("유나는 우표가 몇 장이에요?", "vague"), ("서준이는 우표가 몇 장이에요?", 3)],
        [("태오는 숟가락이 20개 있어.", "rec"), ("태오가 은비한테 숟가락 10개를 줬어.", "rec"), ("은비는 숟가락이 13개 있어.", "rec"),
         ("은비는 숟가락이 몇 개야?", 13), ("태오는 숟가락이 몇 개야?", 10)],
        [("민재는 양초가 30개 있어.", "rec"), ("민재가 소라에게 양초 11개를 빌려줬어.", "rec"), ("민재가 소라에게 양초 12개를 줬어.", "rec"),
         ("소라는 양초가 몇 개야?", "vague"), ("민재는 양초가 몇 개야?", 7)],
        [("윤호는 리본이 18개 있어.", "rec"), ("윤호가 다은이에게 리본 10개를 줬어.", "rec"), "#SNAP",
         ("윤호는 리본이 몇 개야?", 8), ("다은이는 리본이 몇 개야?", "vague")],
        [("다은이가 윤호에게 리본 14개를 줬어.", "hold"), ("윤호는 리본이 몇 개야?", "hold")],
        [("서준이는 숟가락이 11개 있어.", "rec"), ("서준이가 태오에게 숟가락 14개를 줬어.", "contra"),
         ("서준이는 숟가락이 몇 개야?", "hold")],
        [("유나는 양초가 22개 있어.", "rec"), ("유나가 민재에게 양초 12개를 줬어.", "rec"),
         ("정정: 유나가 민재에게 양초 12개를 줬어. => 유나가 민재에게 양초 10개를 줬어.", "rec"),
         ("유나는 양초가 몇 개야?", 12), ("민재는 양초가 몇 개야?", "vague")],
        [("소라는 우표가 26장 있어.", "rec"), ("소라가 은비에게 우표 16장을 줬어.", "rec"), ("은비가 다은이에게 우표 10장을 줬어.", "rec"),
         ("은비는 우표가 몇 장이야?", "vague"), ("소라는 우표가 몇 장이야?", 10), ("다은이는 우표가 몇 장이야?", "vague")],
        [("소라는 우표가 26장 있어.", "rec"), ("소라가 은비에게 우표 11장을 줬어.", "rec"),
         ("은비가 다은이에게 우표 13장을 줬어.", "hold"), ("은비는 우표가 몇 장이야?", "hold")],
        [("윤호는 양초 17개를 샀어.", "rec"), ("윤호는 양초가 몇 개야?", "vague"), ("윤호는 양초가 19개 있어.", "rec"),
         ("윤호는 양초가 몇 개야?", 19)],
        [("태오는 리본 12개를 잃어버렸어.", "hold"), ("태오는 리본이 몇 개야?", "hold")],
        [("민재는 숟가락이 24개 있어.", "rec"), ("유나가 민재에게서 숟가락 14개를 받았어.", "rec"),
         ("민재와 유나는 숟가락이 모두 몇 개야?", "hold"), ("민재는 숟가락이 몇 개야?", 10)],
        [("다은이는 양초가 20개 있어.", "rec"), ("서준이가 다은이에게서 양초 13개를 받았어.", "rec"),
         ("서준이는 양초가 15개 있어.", "rec"), ("서준이가 다은이에게 양초 10개를 줬어.", "rec"),
         ("다은이는 양초가 몇 개야?", 17), ("서준이는 양초가 몇 개야?", 5)],
    ],
}
BUILD_WORDS = {"Nora", "Eli", "Mira", "Tom", "Sam", "Pia", "Nils", "Ola", "pens", "cups",
               "보라", "하늘", "미나", "준호", "세라", "지유", "하람", "도윤", "연필", "컵"}
CHECK_WORDS = {"Greta", "Hugo", "Ines", "Jonas", "Kai", "Lena", "Omar", "Rosa", "stamps", "spoons", "candles",
               "ribbons", "서준", "유나", "태오", "은비", "민재", "소라", "윤호", "다은", "우표", "숟가락", "양초", "리본"}


def outcome(result, expected):
    """(turn ok, question score): score is None for a statement, else correct / hold / wrong."""
    status = result.get("status")
    meaning = result.get("meaning") or {}
    answer = str(result.get("answer") or "")
    if isinstance(expected, int):
        if status != "answered":
            return False, "hold"
        good = re.search(r"(?<!\d)%d(?!\d)" % expected, answer) is not None
        return good, "correct" if good else "wrong"
    if expected == "rec":
        return status == "observed", None
    if expected == "contra":
        return status == "unresolved" and meaning.get("reason") == "contradiction", None
    held = status == "unresolved"
    if expected == "vague":
        good = held and meaning.get("reason") == "vague_count"
        return good, "correct" if good else "hold" if held else "wrong"
    return held, "correct" if held else "wrong"


def play(language, dialogue):
    """[(line, expected, ok, score)] for every turn of ``dialogue``."""
    current, rows = context(language), []
    for step in dialogue:
        if step == "#SNAP":
            saved = current.snapshot()
            current = context(language)
            current.restore(saved)
            continue
        line, expected = step
        ok, score = outcome(current.turn(line, KG) or {}, expected)
        rows.append((line, expected, ok, score))
    return rows


def tally(half):
    counts = {"correct": 0, "hold": 0, "wrong": 0}
    for language, dialogues in half.items():
        for dialogue in dialogues:
            for _line, expected, _ok, score in play(language, dialogue):
                if score is not None:
                    counts[score] += 1
    return counts


CASES = [(half, language, n) for half, table in (("build", BUILD), ("check", CHECK))
         for language, dialogues in table.items() for n in range(len(dialogues))]


@pytest.mark.parametrize("half,language,n", CASES)
def test_dialogue(half, language, n):
    dialogue = (BUILD if half == "build" else CHECK)[language][n]
    failed = [(line, expected) for line, expected, ok, _score in play(language, dialogue) if not ok]
    assert failed == []


def test_names_things_and_amounts_of_the_halves_are_disjoint():
    def lines(table):
        return [step[0] for dialogues in table.values() for d in dialogues for step in d if step != "#SNAP"]

    def amounts(table):
        return {n for line in lines(table) for n in re.findall(r"\d+", line)}

    assert not BUILD_WORDS & CHECK_WORDS and not amounts(BUILD) & amounts(CHECK)
    assert not any(word in line for line in lines(CHECK) for word in BUILD_WORDS)
    assert not any(word in line for line in lines(BUILD) for word in CHECK_WORDS)


def test_the_giver_moves_the_receiver_is_not_known_and_nothing_is_counted_twice():
    """The state rows themselves: the receiver's row has no before or after, a count said later replaces it."""
    from marco.reasoning.inference import current_facts
    updates = {"count_add": {"target": "count", "factor": 1}, "count_remove": {"target": "count", "factor": -1}}
    ev = {"text": "x"}
    facts = [{"triple": ["A pens", "count", "7"], "evidence": ev},
             {"triple": ["A pens", "count_remove", "3"], "evidence": ev},
             {"triple": ["B pens", "count_add", "3"], "evidence": ev}]
    state, changes = current_facts(facts, ["count"], updates)
    assert ["A pens", "count", "4"] in [f["triple"] for f in state]
    assert [f["at_least"] for f in state if f["triple"] == ["B pens", "count_unknown", "some"]] == [3]
    assert changes[-1]["before"] is None and changes[-1]["after"] is None and changes[-1]["delta"] == 3
    later = facts + [{"triple": ["B pens", "count", "5"], "evidence": ev}]
    state, changes = current_facts(later, ["count"], updates)
    assert [f["triple"] for f in state if f["triple"][0] == "B pens"] == [["B pens", "count", "5"]]
    assert changes[-1]["before"] is None
    for bad in ([{"triple": ["C pens", "count_remove", "1"], "evidence": ev}],
                facts + [{"triple": ["B pens", "count_remove", "4"], "evidence": ev}]):
        with pytest.raises(ValueError, match="missing_initial_quantity"):
            current_facts(bad, ["count"], updates)
