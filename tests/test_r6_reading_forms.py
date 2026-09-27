"""Round 6, reading forms: statements and questions the reader did not read (goal G6, classes 1, 3, 4, 5,
6, 7 and 11, the narrowed subset).

Every class has a build half and a check half with disjoint names, things and amounts. Fixes were made
against the build half only; the check half is scored and must never be wrong (a hold is allowed there).
Each dialogue states every holder's starting count before any transfer and ends with the question whose
answer depends on the class's sentence.
"""
import time

import pytest

from tests.test_understanding_r5 import asserted_numbers, play

EN, KO = "english", "한국어"

CASES = {
    # A1. Counts as words: English compound number words, Korean native numerals with counters.
    "A1": {
        "build": [
            (EN, ["Nora has twenty-four pens.", "Otto has three pens.", "Nora gave eleven pens to Otto.",
                  "How many pens does Otto have?"], 14),
            (EN, ["Lena has twenty-one cups.", "Bram has twelve cups.", "Lena gave Bram fifteen cups.",
                  "How many cups does Lena have?"], 6),
            (EN, ["Ivo has one kite.", "Pia has twenty-three kites.", "Pia handed two kites to Ivo.",
                  "How many kites does Ivo have?"], 3),
            (EN, ["Tessa has fourteen spoons.", "Hugo has eight spoons.", "Tessa lent Hugo five spoons.",
                  "How many spoons does Hugo have?"], 13),
            (KO, ["보라는 공책이 스물네 권 있어.", "하늘은 공책이 두 권 있어.", "보라가 하늘에게 공책 열한 권을 줬어.",
                  "하늘은 공책이 몇 권 있어?"], 13),
            (KO, ["다온은 우표가 스무 장 있어요.", "서진은 우표가 세 장 있어요.", "다온이 서진에게 우표 여섯 장을 줬어요.",
                  "다온은 우표가 몇 장 있어요?"], 14),
            (KO, ["지유는 꽃이 다섯 묶음 있어.", "은호는 꽃이 한 묶음 있어.", "지유가 은호한테 꽃 두 묶음을 줬어.",
                  "은호는 꽃이 몇 묶음 있어?"], 3),
            (KO, ["민재는 붓이 열두 자루 있어요.", "수아는 붓이 네 자루 있어요.", "민재가 수아에게 붓 여덟 자루를 빌려줬어요.",
                  "수아는 붓이 몇 자루 있어요?"], 12),
        ],
        "check": [
            (EN, ["Rosa has seventeen plates.", "Felix has nine plates.", "Rosa gave seven plates to Felix.",
                  "How many plates does Felix have?"], 16),
            (EN, ["Mona has twenty-two candles.", "Dirk has ten candles.", "Mona gave Dirk nine candles.",
                  "How many candles does Mona have?"], 13),
            (EN, ["Ada has nineteen ribbons.", "Cole has seven ribbons.", "Cole handed seven ribbons to Ada.",
                  "How many ribbons does Ada have?"], 26),
            (EN, ["June has eighteen mugs.", "Ravi has sixteen mugs.", "June lent Ravi ten mugs.",
                  "How many mugs does June have?"], 8),
            (KO, ["윤서는 책이 열아홉 권 있어.", "도현은 책이 일곱 권 있어.", "윤서가 도현에게 책 아홉 권을 줬어.",
                  "도현은 책이 몇 권 있어?"], 16),
            (KO, ["채원은 사진이 스물두 장 있어요.", "시우는 사진이 열 장 있어요.", "채원이 시우에게 사진 열일곱 장을 줬어요.",
                  "채원은 사진이 몇 장 있어요?"], 5),
            (KO, ["하린은 파가 열여섯 묶음 있어.", "준호는 파가 아홉 묶음 있어.", "하린이 준호한테 파 일곱 묶음을 줬어.",
                  "준호는 파가 몇 묶음 있어?"], 16),
            (KO, ["예나는 볼펜이 열여덟 자루 있어요.", "태민은 볼펜이 일곱 자루 있어요.", "예나가 태민에게 볼펜 열 자루를 빌려줬어요.",
                  "태민은 볼펜이 몇 자루 있어요?"], 17),
        ],
    },
}


def score(case):
    """``correct``, ``hold`` or ``wrong`` for the dialogue's last turn."""
    language, lines, expected = case
    _ctx, rows = play(language, lines)
    last = rows[-1]
    if last.get("status") != "answered":
        return "hold"
    return "correct" if asserted_numbers(last.get("answer")) == {expected} else "wrong"


def table():
    """{class: {half: (correct, hold, wrong)}} and the seconds all of it took."""
    out, started = {}, time.perf_counter()
    for name, halves in CASES.items():
        for half, cases in halves.items():
            results = [score(case) for case in cases]
            out.setdefault(name, {})[half] = tuple(results.count(k) for k in ("correct", "hold", "wrong"))
    return out, time.perf_counter() - started


BUILD = [(name, i) for name in CASES for i in range(len(CASES[name]["build"]))]
CHECK = [(name, i) for name in CASES for i in range(len(CASES[name]["check"]))]


@pytest.mark.parametrize("name,index", BUILD)
def test_the_build_half_is_read_and_answered(name, index):
    assert score(CASES[name]["build"][index]) == "correct"


@pytest.mark.parametrize("name,index", CHECK)
def test_the_check_half_is_never_answered_wrong(name, index):
    assert score(CASES[name]["check"][index]) != "wrong"


def test_the_halves_share_no_name():
    import re
    for name, halves in CASES.items():
        words = [{w for _l, lines, _e in halves[h] for line in lines for w in re.findall(r"\b[A-Z][a-z]+\b", line)
                  if w not in {"How", "Why", "And", "What", "The", "For", "I", "It", "Six"}}
                 for h in ("build", "check")]
        assert not words[0] & words[1], name


if __name__ == "__main__":
    import sys
    result, seconds = table()
    for name, halves in result.items():
        print(name, halves)
    print("seconds", round(seconds, 1))
