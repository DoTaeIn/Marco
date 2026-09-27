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
    # A3. Partitive pronoun objects: "N of them", 그중 N개, used up or made into something.
    "A3": {
        "build": [
            (EN, ["Nora has 6 pens.", "Otto has 2 pens.", "Nora gave two of them to Otto.",
                  "How many pens does Otto have?"], 4),
            (EN, ["Lena has 9 cups.", "Bram has 4 cups.", "Lena gave one of them to Bram.",
                  "How many cups does Lena have?"], 8),
            (EN, ["Ivo has 12 kites.", "Ivo used three of them for the festival.", "How many kites does Ivo have?"], 9),
            (EN, ["Tessa has 5 spoons.", "Hugo has 3 spoons.", "Tessa lent Hugo two of them.",
                  "How many spoons does Hugo have?"], 5),
            (KO, ["보라는 연필이 다섯 개 있어.", "하늘은 연필이 세 개 있어.", "보라가 그중 2개를 하늘에게 줬어.",
                  "하늘은 연필이 몇 개 있어?"], 5),
            (KO, ["다온은 우표가 열두 장 있어요.", "서진은 우표가 네 장 있어요.", "다온이 그중 하나를 서진에게 줬어요.",
                  "서진은 우표가 몇 장 있어요?"], 5),
            (KO, ["지유는 사과가 여덟 개 있어.", "지유는 그중 세 개로 잼을 만들었어.", "지유는 사과가 몇 개 있어?"], 5),
            (KO, ["민재는 붓이 여섯 자루 있어요.", "수아는 붓이 두 자루 있어요.", "민재는 그중 두 자루를 수아에게 빌려줬어요.",
                  "민재는 붓이 몇 자루 있어요?"], 4),
        ],
        "check": [
            (EN, ["Rosa has 11 plates.", "Felix has 7 plates.", "Rosa gave seven of them to Felix.",
                  "How many plates does Felix have?"], 14),
            (EN, ["Mona has 13 candles.", "Mona used ten of them for the dinner.", "How many candles does Mona have?"],
             3),
            (EN, ["Ada has 15 ribbons.", "Cole has 10 ribbons.", "Ada gave Cole one of them.",
                  "How many ribbons does Cole have?"], 11),
            (EN, ["June has 14 mugs.", "Ravi has 11 mugs.", "June handed seven of them to Ravi.",
                  "How many mugs does June have?"], 7),
            (KO, ["윤서는 책이 열한 권 있어.", "도현은 책이 일곱 권 있어.", "윤서가 그중 한 권을 도현에게 줬어.",
                  "도현은 책이 몇 권 있어?"], 8),
            (KO, ["채원은 귤이 열다섯 개 있어요.", "채원은 그중 열 개로 주스를 만들었어요.", "채원은 귤이 몇 개 있어요?"], 5),
            (KO, ["하린은 쿠키가 열세 개 있어.", "준호는 쿠키가 열 개 있어.", "하린은 그중 하나를 준호한테 줬어.",
                  "하린은 쿠키가 몇 개 있어?"], 12),
            (KO, ["예나는 볼펜이 열네 자루 있어요.", "태민은 볼펜이 일곱 자루 있어요.", "예나가 태민에게 그중 일곱 자루를 빌려줬어요.",
                  "태민은 볼펜이 몇 자루 있어요?"], 14),
        ],
    },
    # A4. A count given in a following fragment: of a holding said without its count, or of a transfer.
    "A4": {
        "build": [
            (EN, ["Nora has some pens.", "Six, to be exact.", "How many pens does Nora have?"], 6),
            (EN, ["Lena has some cups.", "Twelve, to be exact.", "How many cups does Lena have?"], 12),
            (EN, ["Ivo has some kites.", "Exactly four.", "How many kites does Ivo have?"], 4),
            (EN, ["Tessa has 8 spoons.", "Hugo has 3 spoons.", "Tessa gave Hugo some spoons.", "Two, to be exact.",
                  "How many spoons does Hugo have?"], 5),
            (KO, ["보라한테 연필이 있어.", "여섯 개야.", "보라는 연필이 몇 개 있어?"], 6),
            (KO, ["다온은 우표가 좀 있어요.", "열두 장이에요.", "다온은 우표가 몇 장 있어요?"], 12),
            (KO, ["지유는 사과가 여덟 개 있어.", "은호는 사과가 한 개 있어.", "지유가 은호한테 사과를 줬어. 두 개.",
                  "은호는 사과가 몇 개 있어?"], 3),
            (KO, ["민재는 붓을 가지고 있어요.", "정확히는 네 자루예요.", "민재는 붓이 몇 자루 있어요?"], 4),
        ],
        "check": [
            (EN, ["Rosa has some plates.", "Nine, to be exact.", "How many plates does Rosa have?"], 9),
            (EN, ["Mona has some candles.", "Exactly seventeen.", "How many candles does Mona have?"], 17),
            (EN, ["Ada has 15 ribbons.", "Cole has 10 ribbons.", "Ada gave Cole some ribbons.", "Seven, to be exact.",
                  "How many ribbons does Cole have?"], 17),
            (EN, ["June has some mugs.", "Eleven of them.", "How many mugs does June have?"], 11),
            (KO, ["윤서한테 책이 있어.", "일곱 권이야.", "윤서는 책이 몇 권 있어?"], 7),
            (KO, ["채원은 귤이 좀 있어요.", "열다섯 개예요.", "채원은 귤이 몇 개 있어요?"], 15),
            (KO, ["하린은 쿠키가 열세 개 있어.", "준호는 쿠키가 열 개 있어.", "하린이 준호한테 쿠키를 줬어. 아홉 개.",
                  "준호는 쿠키가 몇 개 있어?"], 19),
            (KO, ["예나는 볼펜을 가지고 있어요.", "정확히는 열한 자루예요.", "예나는 볼펜이 몇 자루 있어요?"], 11),
        ],
    },
    # A5. Korean transfer verbs and compounds, and the giver left out in a second sentence of the turn.
    "A5": {
        "build": [
            (KO, ["보라는 연필이 아홉 개 있어.", "하늘은 연필이 두 개 있어.", "보라가 하늘에게 연필 네 개를 나눠 줬어.",
                  "하늘은 연필이 몇 개 있어?"], 6),
            (KO, ["다온은 우표가 열두 장 있어요.", "서진은 우표가 한 장 있어요.", "은호는 우표가 세 장 있어요.",
                  "다온이 서진에게 우표 두 장을 줬어요. 그리고 은호에게 네 장을 주었다.", "다온은 우표가 몇 장 있어요?"], 6),
            (KO, ["지유는 사과가 여덟 개 있어.", "은호는 사과가 한 개 있어.", "지유가 은호한테 사과 세 개를 보냈어.",
                  "은호는 사과가 몇 개 있어?"], 4),
            (KO, ["민재는 붓이 열두 자루 있어요.", "창고에는 붓이 두 자루 있어요.", "민재가 창고에 붓 다섯 자루를 맡겼어요.",
                  "창고에는 붓이 몇 자루 있어요?"], 7),
            (KO, ["수아는 공책이 여섯 권 있어.", "하늘은 공책이 두 권 있어.", "다온은 공책이 한 권 있어.",
                  "수아가 하늘에게 공책 세 권을 나눠 주었다. 그리고 다온에게 두 권을 나눠 주었다.", "수아는 공책이 몇 권 있어?"], 1),
            (KO, ["은호는 상자를 다섯 개 싣고 있어.", "은호는 상자가 몇 개 있어?"], 5),
        ],
        "check": [
            (KO, ["윤서는 책이 열한 권 있어.", "도현은 책이 일곱 권 있어.", "윤서가 도현에게 책 열 권을 나눠 줬어.",
                  "도현은 책이 몇 권 있어?"], 17),
            (KO, ["채원은 사진이 열아홉 장 있어요.", "시우는 사진이 열 장 있어요.", "준호는 사진이 열한 장 있어요.",
                  "채원이 시우에게 사진 일곱 장을 줬어요. 그리고 준호에게 열 장을 주었다.", "채원은 사진이 몇 장 있어요?"], 2),
            (KO, ["하린은 귤이 열세 개 있어.", "예나는 귤이 열 개 있어.", "하린이 예나한테 귤 일곱 개를 보냈어.",
                  "예나는 귤이 몇 개 있어?"], 17),
            (KO, ["태민은 볼펜이 열일곱 자루 있어요.", "가게에는 볼펜이 열한 자루 있어요.", "태민이 가게에 볼펜 열 자루를 맡겼어요.",
                  "가게에는 볼펜이 몇 자루 있어요?"], 21),
            (KO, ["시우는 쿠키가 열아홉 개 있어.", "도현은 쿠키가 열 개 있어.", "윤서는 쿠키가 열한 개 있어.",
                  "시우가 도현에게 쿠키 일곱 개를 나눠 주었다. 그리고 윤서에게 열 개를 나눠 주었다.", "시우는 쿠키가 몇 개 있어?"], 2),
            (KO, ["준호는 화분을 열네 개 싣고 있어.", "준호는 화분이 몇 개 있어?"], 14),
        ],
    },
    # A6. Being responsible for a count, the statement fronted by a purpose, and its question.
    "A6": {
        "build": [
            (EN, ["For the fair, Nora is responsible for six boxes.", "How many boxes is Nora responsible for?"], 6),
            (EN, ["Lena is responsible for 12 cups.", "Bram is responsible for 4 cups.", "Lena gave Bram 3 cups.",
                  "How many cups is Bram responsible for?"], 7),
            (EN, ["For the picnic, Ivo is responsible for two baskets.", "Pia has 5 baskets.", "Pia gave Ivo 3 baskets.",
                  "How many baskets does Ivo have?"], 5),
            (EN, ["At the market, Tessa is responsible for eight crates.", "How many crates is Tessa responsible for?"],
             8),
            (KO, ["행사에서 보라는 상자를 여섯 개 맡고 있어요.", "보라는 상자를 몇 개 맡고 있습니까?"], 6),
            (KO, ["다온은 의자를 열두 개 맡고 있어.", "서진은 의자를 세 개 맡고 있어.", "다온이 서진에게 의자 네 개를 넘겼어.",
                  "서진은 의자를 몇 개 맡고 있어?"], 7),
            (KO, ["바자회를 위해 은호는 컵을 여덟 개 맡고 있습니다.", "은호는 컵이 몇 개 있습니까?"], 8),
            (KO, ["민재는 책상을 다섯 개 맡고 있어요.", "수아는 책상을 한 개 맡고 있어요.", "민재가 수아에게 책상 두 개를 넘겼어요.",
                  "민재는 책상을 몇 개 맡고 있어요?"], 3),
        ],
        "check": [
            (EN, ["For the concert, Rosa is responsible for nine chairs.", "How many chairs is Rosa responsible for?"], 9),
            (EN, ["Mona is responsible for 17 lamps.", "Dirk is responsible for 10 lamps.", "Mona gave Dirk 7 lamps.",
                  "How many lamps is Dirk responsible for?"], 17),
            (EN, ["For the parade, Ada is responsible for eleven flags.", "Cole has 13 flags.", "Cole gave Ada 10 flags.",
                  "How many flags does Ada have?"], 21),
            (EN, ["At the festival, June is responsible for fifteen tents.", "How many tents is June responsible for?"],
             15),
            (KO, ["음악회에서 윤서는 탁자를 열한 개 맡고 있어요.", "윤서는 탁자를 몇 개 맡고 있습니까?"], 11),
            (KO, ["채원은 깃발을 열아홉 개 맡고 있어.", "시우는 깃발을 열 개 맡고 있어.", "채원이 시우에게 깃발 일곱 개를 넘겼어.",
                  "시우는 깃발을 몇 개 맡고 있어?"], 17),
            (KO, ["축제를 위해 하린은 텐트를 열세 개 맡고 있습니다.", "하린은 텐트가 몇 개 있습니까?"], 13),
            (KO, ["예나는 접시를 열일곱 개 맡고 있어요.", "태민은 접시를 열 개 맡고 있어요.", "예나가 태민에게 접시 열한 개를 넘겼어요.",
                  "예나는 접시를 몇 개 맡고 있어요?"], 6),
        ],
    },
    # B7. Leftover and remaining questions.
    "B7": {
        "build": [
            (EN, ["Nora has 9 pens.", "Otto has 2 pens.", "Nora gave 4 pens to Otto.", "How many pens are left with Nora?"],
             5),
            (EN, ["Lena has 12 cups.", "Lena used 3 cups.", "How many cups remain with Lena?"], 9),
            (EN, ["Ivo has 8 kites.", "Pia has 1 kite.", "Ivo gave Pia 2 kites.", "How many kites are left for Ivo?"], 6),
            (EN, ["Tessa has 6 spoons.", "Hugo has 3 spoons.", "Tessa lent Hugo 4 spoons.",
                  "How many spoons are left with Tessa now?"], 2),
            (KO, ["보라는 연필이 아홉 개 있어.", "하늘은 연필이 두 개 있어.", "보라가 하늘에게 연필 네 개를 줬어.",
                  "보라에게 남은 연필은 몇 개인가?"], 5),
            (KO, ["다온은 우표가 열두 장 있어요.", "다온이 우표 세 장을 썼어요.", "우표 몇 장 남았어요?"], 9),
            (KO, ["지유 님은 공책이 여덟 권 있습니다.", "은호 님은 공책이 한 권 있습니다.", "지유 님이 은호 님께 공책 두 권을 드렸습니다.",
                  "지유 님께 남은 공책은 몇 권입니까?"], 6),
            (KO, ["민재는 붓이 여섯 자루 있어.", "수아는 붓이 세 자루 있어.", "민재가 수아에게 붓 네 자루를 줬어.",
                  "민재한테 남은 붓은 몇 자루야?"], 2),
        ],
        "check": [
            (EN, ["Rosa has 17 plates.", "Felix has 7 plates.", "Rosa gave 10 plates to Felix.",
                  "How many plates are left with Rosa?"], 7),
            (EN, ["Mona has 15 candles.", "Mona used 11 candles.", "How many candles remain with Mona?"], 4),
            (EN, ["Ada has 19 ribbons.", "Cole has 10 ribbons.", "Ada gave Cole 13 ribbons.",
                  "How many ribbons are left for Ada?"], 6),
            (EN, ["June has 16 mugs.", "Ravi has 11 mugs.", "June lent Ravi 7 mugs.", "How many mugs are left with June now?"],
             9),
            (KO, ["윤서는 책이 열한 권 있어.", "도현은 책이 일곱 권 있어.", "윤서가 도현에게 책 열 권을 줬어.",
                  "윤서에게 남은 책은 몇 권인가?"], 1),
            (KO, ["채원은 귤이 열다섯 개 있어요.", "채원이 귤 일곱 개를 먹었어요.", "귤 몇 개 남았어요?"], 8),
            (KO, ["하린 님은 사진이 열아홉 장 있습니다.", "준호 님은 사진이 열 장 있습니다.", "하린 님이 준호 님께 사진 열세 장을 드렸습니다.",
                  "하린 님께 남은 사진은 몇 장입니까?"], 6),
            (KO, ["예나는 볼펜이 열일곱 자루 있어.", "태민은 볼펜이 열한 자루 있어.", "예나가 태민에게 볼펜 열 자루를 줬어.",
                  "예나한테 남은 볼펜은 몇 자루야?"], 7),
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


# Build dialogues left held on purpose: a fronted place phrase (At the market, 행사에서) may be the holder or only the
# setting, and the reader does not choose (read as the setting, 'At the shop, there are 3 figs' would lose its holder).
HELD_BUILD = {("A6", 3), ("A6", 4)}


@pytest.mark.parametrize("name,index", BUILD)
def test_the_build_half_is_read_and_answered(name, index):
    assert score(CASES[name]["build"][index]) == ("hold" if (name, index) in HELD_BUILD else "correct")


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


def test_a_transfer_left_unread_whose_giver_is_unsaid_holds_every_holders_count():
    # A5: across turns the giver is not carried; the statement could have moved anyone's count
    _ctx, rows = play(KO, ["하린은 쿠키가 열세 개 있어.", "준호는 쿠키가 열 개 있어.", "그중 하나를 준호한테 줬어.",
                           "하린은 쿠키가 몇 개 있어?"])
    assert rows[2]["status"] != "observed" and rows[3]["status"] != "answered"


def test_an_amount_alone_changes_no_statement_that_was_read_or_is_not_the_last_turn():
    # A4: the fragment goes only into the statement said just before it and left unread
    _ctx, rows = play(EN, ["Nora has 5 pens.", "Otto has 2 pens.", "Nora gave Otto some pens.",
                           "How many pens does Otto have?", "Three.", "How many pens does Otto have?"])
    assert rows[-1]["status"] != "answered"
    _ctx, rows = play(KO, ["보라는 연필이 다섯 개 있어. 두 개.", "보라는 연필이 몇 개 있어?"])
    assert rows[-1]["status"] != "answered"


def test_a_numeral_said_before_a_counter_is_not_a_noun_object():
    # A3: 두를 (a repair's reading) is not 2개를; a protected counter stays held (test_understanding_r2)
    _ctx, rows = play(KO, ["누리는 단추가 여섯 개 있어.", "다올은 단추가 두 개 있어.", "누리가 다올에게 단추 개를 두 줬어."])
    assert rows[-1]["status"] not in ("answered", "observed")


if __name__ == "__main__":
    import sys
    result, seconds = table()
    for name, halves in result.items():
        print(name, halves)
    print("seconds", round(seconds, 1))
