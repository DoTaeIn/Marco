"""Round 6, reading 2: a held count released by a later statement of it, and the classes that still
failed on dialogues written outside the repository."""
import pytest

from pack_model import development_model
from reasoning_context import ReasoningContext

KG = "graphs/graph_일상추론.kg"


def context(language):
    other = "english" if language == "한국어" else "한국어"
    return ReasoningContext(model=development_model(language), companions=[development_model(other)])


def run(language, lines):
    current = context(language)
    return [current.turn(line, KG) for line in lines]


# --- A. a held count is released only by a later statement of that holder's count ---

def test_a_later_statement_of_the_count_releases_the_hold():
    *_, asked = run("한국어", ["다래가 부채 여섯 개를 가지고 있어.", "그중 하나를 빌려줬어.",
                               "다래는 부채 5개가 있어.", "다래는 부채가 몇 개야?"])
    assert asked["status"] == "answered" and "5" in asked["answer"]


def test_without_a_later_statement_the_count_stays_held():
    *_, asked = run("한국어", ["다래가 부채 여섯 개를 가지고 있어.", "그중 하나를 빌려줬어.",
                               "다래는 부채가 몇 개야?"])
    assert asked["status"] != "answered"


def test_a_later_statement_of_another_holders_count_does_not_release_it():
    *_, other, asked = run("한국어", ["다래가 부채 여섯 개를 가지고 있어.", "보라가 부채 세 개를 가지고 있어.",
                                      "그중 하나를 빌려줬어.", "보라는 부채 5개가 있어.",
                                      "보라는 부채가 몇 개야?", "다래는 부채가 몇 개야?"])
    assert other["status"] == "answered" and "5" in other["answer"]
    assert asked["status"] != "answered"


# --- B. classes that still failed on dialogues written outside the repository ---
# Each class has a build half and a check half with disjoint names and things. Both halves were scored
# before the first fix; fixes were made against the build half only.

EN, KO = "english", "한국어"

CASES = {
    # Partitive objects with the giver or the receiver left out or moved.
    "partitive": {
        "build": [
            (EN, ["Gwen has 8 marbles.", "Tobias has 3 marbles.", "She gave three of them to Tobias.",
                  "How many marbles does Gwen have?"], 5),
            (EN, ["Wren has 9 stamps.", "Wren gave away four of them.", "How many stamps does Wren have?"], 5),
            (EN, ["Silas has 7 pencils.", "Maeve has 2 pencils.", "Silas lent Maeve two of them.",
                  "How many pencils does Maeve have?"], 4),
            (EN, ["Jonah has 12 cookies.", "Jonah ate five of them.", "How many cookies does Jonah have?"], 7),
            (EN, ["Iris has 10 kites.", "Leo has 1 kite.", "Leo got four of them from Iris.",
                  "How many kites does Iris have?"], 6),
            (KO, ["가람은 연필이 여덟 개 있어.", "나래는 연필이 세 개 있어.", "가람이 그중 두 개를 나래한테 빌려줬어.",
                  "나래는 연필이 몇 개 있어?"], 5),
            (KO, ["다솔은 우표가 아홉 장 있어요.", "다솔은 그중 네 장을 팔았어요.", "다솔은 우표가 몇 장 있어요?"], 5),
            (KO, ["라온은 사과가 열 개 있어.", "마루는 사과가 두 개 있어.", "마루가 라온한테서 그중 세 개를 받았어.",
                  "라온은 사과가 몇 개 있어?"], 7),
            (KO, ["보늬는 공책이 일곱 권 있어요.", "보늬가 그중 한 권을 잃어버렸어요.", "보늬는 공책이 몇 권 있어요?"], 6),
            (KO, ["소담은 붓이 여섯 자루 있어.", "아라는 붓이 한 자루 있어.", "소담은 아라에게 그중 두 자루를 줬어.",
                  "아라는 붓이 몇 자루 있어?"], 3),
        ],
        "check": [
            (EN, ["Hazel has 14 plates.", "Rufus has 6 plates.", "She gave five of them to Rufus.",
                  "How many plates does Hazel have?"], 9),
            (EN, ["Ines has 11 candles.", "Ines gave away two of them.", "How many candles does Ines have?"], 9),
            (EN, ["Milo has 13 ribbons.", "Vera has 4 ribbons.", "Milo lent Vera six of them.",
                  "How many ribbons does Vera have?"], 10),
            (EN, ["Oscar has 15 mugs.", "Oscar used seven of them.", "How many mugs does Oscar have?"], 8),
            (EN, ["Delia has 16 tickets.", "Kurt has 2 tickets.", "Kurt got nine of them from Delia.",
                  "How many tickets does Delia have?"], 7),
            (KO, ["한결은 귤이 열한 개 있어.", "누리는 귤이 네 개 있어.", "한결이 그중 다섯 개를 누리한테 빌려줬어.",
                  "누리는 귤이 몇 개 있어?"], 9),
            (KO, ["도담은 사진이 열세 장 있어요.", "도담은 그중 여섯 장을 팔았어요.", "도담은 사진이 몇 장 있어요?"], 7),
            (KO, ["루다는 컵이 열네 개 있어.", "미르는 컵이 한 개 있어.", "미르가 루다한테서 그중 일곱 개를 받았어.",
                  "루다는 컵이 몇 개 있어?"], 7),
            (KO, ["별하는 책이 열두 권 있어요.", "별하가 그중 두 권을 잃어버렸어요.", "별하는 책이 몇 권 있어요?"], 10),
            (KO, ["솔비는 볼펜이 열다섯 자루 있어.", "온유는 볼펜이 두 자루 있어.", "솔비는 온유에게 그중 아홉 자루를 줬어.",
                  "온유는 볼펜이 몇 자루 있어?"], 11),
        ],
    },
    # Leftover questions: the holder in different positions, polite endings.
    "leftover": {
        "build": [
            (EN, ["Clara has 9 marbles.", "Ezra has 2 marbles.", "Clara gave 4 marbles to Ezra.",
                  "How many marbles does Clara have left?"], 5),
            (EN, ["Gwen has 12 stamps.", "Gwen used 5 stamps.", "How many stamps has Gwen got left?"], 7),
            (EN, ["Tobias has 8 pencils.", "Tobias lost 3 pencils.", "Tobias has how many pencils left?"], 5),
            (EN, ["Wren has 10 cookies.", "Wren ate 4 cookies.", "How many cookies does Wren have left now?"], 6),
            (EN, ["Silas has 7 kites.", "Maeve has 1 kite.", "Silas gave Maeve 2 kites.",
                  "So how many kites does Silas have left?"], 5),
            (KO, ["가람은 연필이 아홉 개 있어.", "나래는 연필이 두 개 있어.", "가람이 나래에게 연필 네 개를 줬어.",
                  "가람에게 연필이 몇 개 남았어?"], 5),
            (KO, ["다솔은 우표가 열두 장 있어요.", "다솔이 우표 다섯 장을 썼어요.", "다솔은 우표가 몇 장 남았어요?"], 7),
            (KO, ["라온은 사과가 여덟 개 있어.", "라온이 사과 세 개를 먹었어.", "사과는 라온한테 몇 개 남아 있어?"], 5),
            (KO, ["보늬 님은 공책이 열 권 있습니다.", "보늬 님이 공책 네 권을 쓰셨습니다.", "보늬 님께 남은 공책은 몇 권이세요?"], 6),
            (KO, ["소담은 붓이 일곱 자루 있어요.", "아라는 붓이 한 자루 있어요.", "소담이 아라에게 붓 두 자루를 줬어요.",
                  "소담한테 남은 붓이 몇 자루예요?"], 5),
        ],
        "check": [
            (EN, ["Hazel has 16 plates.", "Rufus has 3 plates.", "Hazel gave 7 plates to Rufus.",
                  "How many plates does Hazel have left?"], 9),
            (EN, ["Ines has 13 candles.", "Ines used 6 candles.", "How many candles has Ines got left?"], 7),
            (EN, ["Milo has 15 ribbons.", "Milo lost 8 ribbons.", "Milo has how many ribbons left?"], 7),
            (EN, ["Vera has 14 mugs.", "Vera sold 3 mugs.", "How many mugs does Vera have left now?"], 11),
            (EN, ["Oscar has 17 tickets.", "Delia has 2 tickets.", "Oscar gave Delia 9 tickets.",
                  "So how many tickets does Oscar have left?"], 8),
            (KO, ["한결은 귤이 열여섯 개 있어.", "누리는 귤이 세 개 있어.", "한결이 누리에게 귤 일곱 개를 줬어.",
                  "한결에게 귤이 몇 개 남았어?"], 9),
            (KO, ["도담은 사진이 열세 장 있어요.", "도담이 사진 여섯 장을 썼어요.", "도담은 사진이 몇 장 남았어요?"], 7),
            (KO, ["루다는 컵이 열다섯 개 있어.", "루다가 컵 여덟 개를 팔았어.", "컵은 루다한테 몇 개 남아 있어?"], 7),
            (KO, ["미르 님은 책이 열네 권 있습니다.", "미르 님이 책 세 권을 파셨습니다.", "미르 님께 남은 책은 몇 권이세요?"], 11),
            (KO, ["별하는 볼펜이 열일곱 자루 있어요.", "솔비는 볼펜이 두 자루 있어요.", "별하가 솔비에게 볼펜 아홉 자루를 줬어요.",
                  "별하한테 남은 볼펜이 몇 자루예요?"], 8),
        ],
    },
    # Transfer verbs: lend, send, pass, hand, return, sell, use up, buy, with and without "to".
    "transfer": {
        "build": [
            (EN, ["Leo has 9 marbles.", "Clara has 2 marbles.", "Leo sent Clara 3 marbles.",
                  "How many marbles does Clara have?"], 5),
            (EN, ["Ezra has 7 stamps.", "Iris has 4 stamps.", "Ezra passed 2 stamps to Iris.",
                  "How many stamps does Ezra have?"], 5),
            (EN, ["Jonah has 3 pencils.", "Gwen has 10 pencils.", "Jonah returned 2 pencils to Gwen.",
                  "How many pencils does Gwen have?"], 12),
            (EN, ["Maeve has 11 cookies.", "Silas has 1 cookie.", "Maeve sold Silas 4 cookies.",
                  "How many cookies does Silas have?"], 5),
            (EN, ["Wren has 8 kites.", "Wren bought 5 kites.", "How many kites does Wren have?"], 13),
            (EN, ["Tobias has 12 cards.", "Tobias used up 4 cards.", "How many cards does Tobias have?"], 8),
            (EN, ["Iris has 10 buttons.", "Leo has 2 buttons.", "Leo bought 3 buttons from Iris.",
                  "How many buttons does Iris have?"], 7),
            (EN, ["Ezra has 9 coins.", "Clara has 3 coins.", "Ezra handed 4 coins over to Clara.",
                  "How many coins does Clara have?"], 7),
            (KO, ["가람은 연필이 열 개 있어.", "나래는 연필이 두 개 있어.", "가람이 나래에게 연필 세 개를 빌려줬어.",
                  "나래는 연필이 몇 개 있어?"], 5),
            (KO, ["다솔은 우표가 여덟 장 있어요.", "라온은 우표가 한 장 있어요.", "다솔이 라온한테 우표 네 장을 건네줬어요.",
                  "다솔은 우표가 몇 장 있어요?"], 4),
            (KO, ["마루는 사과가 세 개 있어.", "보늬는 사과가 아홉 개 있어.", "마루가 보늬에게 사과 두 개를 돌려줬어.",
                  "보늬는 사과가 몇 개 있어?"], 11),
            (KO, ["소담은 공책이 열두 권 있어요.", "아라는 공책이 두 권 있어요.", "소담이 아라에게 공책 다섯 권을 팔았어요.",
                  "아라는 공책이 몇 권 있어요?"], 7),
            (KO, ["서하는 붓이 여섯 자루 있어.", "서하가 붓 세 자루를 샀어.", "서하는 붓이 몇 자루 있어?"], 9),
            (KO, ["하람은 초가 열한 개 있어요.", "하람이 초 네 개를 다 썼어요.", "하람은 초가 몇 개 있어요?"], 7),
            (KO, ["가람은 단추가 일곱 개 있어.", "라온은 단추가 한 개 있어.", "라온이 가람한테서 단추 두 개를 샀어.",
                  "가람은 단추가 몇 개 있어?"], 5),
            (KO, ["나래는 구슬이 아홉 개 있어요.", "다솔은 구슬이 세 개 있어요.", "나래가 다솔에게 구슬 네 개를 넘겨줬어요.",
                  "다솔은 구슬이 몇 개 있어요?"], 7),
        ],
        "check": [
            (EN, ["Kurt has 14 plates.", "Zara has 3 plates.", "Kurt sent Zara 6 plates.",
                  "How many plates does Zara have?"], 9),
            (EN, ["Abel has 13 candles.", "Hazel has 5 candles.", "Abel passed 7 candles to Hazel.",
                  "How many candles does Abel have?"], 6),
            (EN, ["Rufus has 4 ribbons.", "Ines has 15 ribbons.", "Rufus returned 3 ribbons to Ines.",
                  "How many ribbons does Ines have?"], 18),
            (EN, ["Milo has 16 mugs.", "Vera has 2 mugs.", "Milo sold Vera 8 mugs.", "How many mugs does Vera have?"], 10),
            (EN, ["Oscar has 6 tickets.", "Oscar bought 11 tickets.", "How many tickets does Oscar have?"], 17),
            (EN, ["Delia has 17 napkins.", "Delia used up 9 napkins.", "How many napkins does Delia have?"], 8),
            (EN, ["Zara has 18 shells.", "Kurt has 1 shell.", "Kurt bought 8 shells from Zara.",
                  "How many shells does Zara have?"], 10),
            (EN, ["Hazel has 12 spoons.", "Abel has 4 spoons.", "Hazel handed 5 spoons over to Abel.",
                  "How many spoons does Abel have?"], 9),
            (KO, ["한결은 귤이 열네 개 있어.", "누리는 귤이 세 개 있어.", "한결이 누리에게 귤 여섯 개를 빌려줬어.",
                  "누리는 귤이 몇 개 있어?"], 9),
            (KO, ["도담은 사진이 열다섯 장 있어요.", "루다는 사진이 두 장 있어요.", "도담이 루다한테 사진 일곱 장을 건네줬어요.",
                  "도담은 사진이 몇 장 있어요?"], 8),
            (KO, ["미르는 컵이 네 개 있어.", "별하는 컵이 열세 개 있어.", "미르가 별하에게 컵 세 개를 돌려줬어.",
                  "별하는 컵이 몇 개 있어?"], 16),
            (KO, ["솔비는 책이 열여섯 권 있어요.", "온유는 책이 한 권 있어요.", "솔비가 온유에게 책 여덟 권을 팔았어요.",
                  "온유는 책이 몇 권 있어요?"], 9),
            (KO, ["재이는 볼펜이 열 자루 있어.", "재이가 볼펜 열한 자루를 샀어.", "재이는 볼펜이 몇 자루 있어?"], 21),
            (KO, ["초롱은 비누가 열일곱 개 있어요.", "초롱이 비누 아홉 개를 다 썼어요.", "초롱은 비누가 몇 개 있어요?"], 8),
            (KO, ["한결은 양말이 열여덟 켤레 있어.", "누리는 양말이 한 켤레 있어.", "누리가 한결한테서 양말 다섯 켤레를 샀어.",
                  "한결은 양말이 몇 켤레 있어?"], 13),
            (KO, ["도담은 수건이 열아홉 장 있어요.", "루다는 수건이 네 장 있어요.", "도담이 루다에게 수건 열 장을 넘겨줬어요.",
                  "루다는 수건이 몇 장 있어요?"], 14),
        ],
    },
    # Number words above twenty; Korean native numerals with different counters.
    "number": {
        "build": [
            (EN, ["Gwen has thirty-five marbles.", "Tobias has 4 marbles.", "Gwen gave Tobias twenty-one marbles.",
                  "How many marbles does Gwen have?"], 14),
            (EN, ["Wren has forty stamps.", "Wren used twenty-six stamps.", "How many stamps does Wren have?"], 14),
            (EN, ["Silas has fifty-two pencils.", "Maeve has thirty pencils.", "Silas gave thirty-three pencils to Maeve.",
                  "How many pencils does Maeve have?"], 63),
            (EN, ["Jonah has sixty cookies.", "Jonah ate twenty-eight cookies.", "How many cookies does Jonah have?"], 32),
            (EN, ["Iris has twenty-nine kites.", "Leo has one kite.", "Iris lent Leo twenty-five kites.",
                  "How many kites does Leo have?"], 26),
            (KO, ["가람은 연필이 서른 자루 있어.", "나래는 연필이 네 자루 있어.", "가람이 나래에게 연필 열두 자루를 줬어.",
                  "나래는 연필이 몇 자루 있어?"], 16),
            (KO, ["다솔은 우표가 스물다섯 장 있어요.", "다솔이 우표 여덟 장을 썼어요.", "다솔은 우표가 몇 장 있어요?"], 17),
            (KO, ["라온은 사과가 마흔 개 있어.", "마루는 사과가 세 개 있어.", "라온이 마루한테 사과 스물한 개를 줬어.",
                  "라온은 사과가 몇 개 있어?"], 19),
            (KO, ["보늬는 장미가 서른두 송이 있어요.", "소담은 장미가 여섯 송이 있어요.", "보늬가 소담에게 장미 열다섯 송이를 줬어요.",
                  "소담은 장미가 몇 송이 있어요?"], 21),
            (KO, ["아라는 금붕어가 스물세 마리 있어.", "아라가 서하에게 금붕어 일곱 마리를 줬어.", "아라는 금붕어가 몇 마리 있어?"], 16),
        ],
        "check": [
            (EN, ["Hazel has forty-seven plates.", "Rufus has 8 plates.", "Hazel gave Rufus thirty-one plates.",
                  "How many plates does Hazel have?"], 16),
            (EN, ["Ines has fifty candles.", "Ines used thirty-eight candles.", "How many candles does Ines have?"], 12),
            (EN, ["Milo has seventy-three ribbons.", "Vera has forty ribbons.", "Milo gave fifty-four ribbons to Vera.",
                  "How many ribbons does Vera have?"], 94),
            (EN, ["Oscar has eighty mugs.", "Oscar sold forty-five mugs.", "How many mugs does Oscar have?"], 35),
            (EN, ["Delia has thirty-six tickets.", "Kurt has two tickets.", "Delia lent Kurt thirty-two tickets.",
                  "How many tickets does Kurt have?"], 34),
            (KO, ["한결은 볼펜이 마흔다섯 자루 있어.", "누리는 볼펜이 일곱 자루 있어.", "한결이 누리에게 볼펜 스물네 자루를 줬어.",
                  "누리는 볼펜이 몇 자루 있어?"], 31),
            (KO, ["도담은 사진이 쉰 장 있어요.", "도담이 사진 열아홉 장을 썼어요.", "도담은 사진이 몇 장 있어요?"], 31),
            (KO, ["루다는 귤이 서른여덟 개 있어.", "미르는 귤이 두 개 있어.", "루다가 미르한테 귤 스물여섯 개를 줬어.",
                  "루다는 귤이 몇 개 있어?"], 12),
            (KO, ["별하는 국화가 스물일곱 송이 있어요.", "솔비는 국화가 아홉 송이 있어요.", "별하가 솔비에게 국화 열세 송이를 줬어요.",
                  "솔비는 국화가 몇 송이 있어요?"], 22),
            (KO, ["온유는 병아리가 서른세 마리 있어.", "온유가 재이에게 병아리 열네 마리를 줬어.", "온유는 병아리가 몇 마리 있어?"], 19),
        ],
    },
    # A count given in a fragment after a transfer, in its own turn or the transfer's.
    "fragment": {
        "build": [
            (EN, ["Clara has 9 marbles.", "Ezra has 2 marbles.", "Clara gave Ezra some marbles.", "Three, to be exact.",
                  "How many marbles does Ezra have?"], 5),
            (EN, ["Gwen has 12 stamps.", "Tobias has 1 stamp.", "Gwen gave some stamps to Tobias. Four of them.",
                  "How many stamps does Gwen have?"], 8),
            (EN, ["Wren has 10 pencils.", "Silas has 3 pencils.", "Wren lent Silas a few pencils.", "Exactly two.",
                  "How many pencils does Silas have?"], 5),
            (EN, ["Maeve has 11 cookies.", "Jonah has 5 cookies.", "Maeve gave Jonah some cookies. Six, to be exact.",
                  "How many cookies does Maeve have?"], 5),
            (EN, ["Iris has 8 kites.", "Leo has 4 kites.", "Leo sent Iris some kites.", "It was three.",
                  "How many kites does Iris have?"], 11),
            (KO, ["가람은 연필이 아홉 개 있어.", "나래는 연필이 두 개 있어.", "가람이 나래에게 연필을 줬어.", "세 개.",
                  "나래는 연필이 몇 개 있어?"], 5),
            (KO, ["다솔은 우표가 열두 장 있어요.", "라온은 우표가 한 장 있어요.", "다솔이 라온에게 우표를 좀 줬어요. 네 장이요.",
                  "다솔은 우표가 몇 장 있어요?"], 8),
            (KO, ["마루는 사과가 열 개 있어.", "보늬는 사과가 세 개 있어.", "마루가 보늬한테 사과를 빌려줬어.", "정확히는 두 개야.",
                  "보늬는 사과가 몇 개 있어?"], 5),
            (KO, ["소담은 공책이 열한 권 있어요.", "아라는 공책이 다섯 권 있어요.", "소담이 아라에게 공책을 줬어요. 여섯 권.",
                  "소담은 공책이 몇 권 있어요?"], 5),
            (KO, ["서하는 붓이 여덟 자루 있어.", "하람은 붓이 네 자루 있어.", "하람이 서하에게 붓을 보냈어.", "세 자루였어.",
                  "서하는 붓이 몇 자루 있어?"], 11),
        ],
        "check": [
            (EN, ["Hazel has 15 plates.", "Rufus has 4 plates.", "Hazel gave Rufus some plates.", "Seven, to be exact.",
                  "How many plates does Rufus have?"], 11),
            (EN, ["Ines has 17 candles.", "Milo has 6 candles.", "Ines gave some candles to Milo. Nine of them.",
                  "How many candles does Ines have?"], 8),
            (EN, ["Vera has 14 ribbons.", "Oscar has 1 ribbon.", "Vera lent Oscar a few ribbons.", "Exactly eight.",
                  "How many ribbons does Oscar have?"], 9),
            (EN, ["Delia has 18 mugs.", "Kurt has 7 mugs.", "Delia gave Kurt some mugs. Ten, to be exact.",
                  "How many mugs does Delia have?"], 8),
            (EN, ["Zara has 13 tickets.", "Abel has 6 tickets.", "Abel sent Zara some tickets.", "It was five.",
                  "How many tickets does Zara have?"], 18),
            (KO, ["한결은 귤이 열다섯 개 있어.", "누리는 귤이 네 개 있어.", "한결이 누리에게 귤을 줬어.", "일곱 개.",
                  "누리는 귤이 몇 개 있어?"], 11),
            (KO, ["도담은 사진이 열일곱 장 있어요.", "루다는 사진이 여섯 장 있어요.", "도담이 루다에게 사진을 좀 줬어요. 아홉 장이요.",
                  "도담은 사진이 몇 장 있어요?"], 8),
            (KO, ["미르는 컵이 열네 개 있어.", "별하는 컵이 한 개 있어.", "미르가 별하한테 컵을 빌려줬어.", "정확히는 여덟 개야.",
                  "별하는 컵이 몇 개 있어?"], 9),
            (KO, ["솔비는 책이 열여덟 권 있어요.", "온유는 책이 일곱 권 있어요.", "솔비가 온유에게 책을 줬어요. 열 권.",
                  "솔비는 책이 몇 권 있어요?"], 8),
            (KO, ["재이는 볼펜이 열세 자루 있어.", "초롱은 볼펜이 여섯 자루 있어.", "초롱이 재이에게 볼펜을 보냈어.", "다섯 자루였어.",
                  "재이는 볼펜이 몇 자루 있어?"], 18),
        ],
    },
}


@pytest.mark.parametrize("verb", ["샀어", "얻었어", "구했어요"])
def test_getting_from_a_source_is_the_source_giving(verb):
    # a wrong answer on main: the source was read into the buyer's name, and the seller kept the old count
    *_, seller, buyer = run(KO, ["가람은 단추가 일곱 개 있어.", "라온은 단추가 한 개 있어.",
                                 f"라온이 가람한테서 단추 두 개를 {verb}.", "가람은 단추가 몇 개 있어?",
                                 "라온은 단추가 몇 개 있어?"])
    assert "5" in seller["answer"] and "3" in buyer["answer"]
    # without a source, getting is only getting
    *_, buyer = run(KO, ["라온은 단추가 한 개 있어.", "라온이 단추 두 개를 샀어.", "라온은 단추가 몇 개 있어?"])
    assert "3" in buyer["answer"]


def test_a_subject_with_do_in_a_clause_that_leaves_the_thing_out_is_not_read():
    # a wrong answer on main: 단추도 was read as a holder of marbles, and the total of marbles said 5 (G5-2 item 10)
    *_, total, own = run(KO, ["하루는 구슬이 두 개 있고 단추도 세 개 있어.", "다들 구슬을 합치면 몇 개야?",
                              "하루는 구슬이 몇 개 있어?"])
    assert total["status"] != "answered" and own["status"] != "answered"
    # the holder said with 도 and its thing is read (모루도 구슬이 세 개 있어: 모루's marbles)
    *_, asked = run(KO, ["하루는 구슬이 두 개 있어.", "모루도 구슬이 세 개 있어.", "모루는 구슬이 몇 개 있어?"])
    assert "3" in asked["answer"]


def score(case):
    from tests.test_r6_reading_forms import score as scored
    return scored(case)


def table():
    """{class: {half: (correct, hold, wrong)}}."""
    return {name: {half: tuple([score(case) for case in cases].count(k) for k in ("correct", "hold", "wrong"))
                   for half, cases in halves.items()} for name, halves in CASES.items()}


BUILD = [(name, i) for name in CASES for i in range(len(CASES[name]["build"]))]
CHECK = [(name, i) for name in CASES for i in range(len(CASES[name]["check"]))]

# Build dialogues left held on purpose: selling with no buyer said (다솔은 그중 네 장을 팔았어요) may have moved the
# count to a holder of the conversation; the reader does not choose.
HELD_BUILD = {("partitive", 6)}


@pytest.mark.parametrize("name,index", BUILD)
def test_the_build_half_is_read_and_answered(name, index):
    assert score(CASES[name]["build"][index]) == ("hold" if (name, index) in HELD_BUILD else "correct")


@pytest.mark.parametrize("name,index", CHECK)
def test_the_check_half_is_never_answered_wrong(name, index):
    assert score(CASES[name]["check"][index]) != "wrong"


def test_the_halves_share_no_name_and_no_thing():
    import re
    for name, halves in CASES.items():
        # the holder and the thing of each statement of a starting count (Gwen has 8 marbles, 가람은 연필이 여덟 개 있어)
        start = re.compile(r"^([A-Z][a-z]+) has \S+ (\w+)\.$|^([가-힣]{2})(?: 님)?[은는] ([가-힣]+)[이가] ")
        found = [{w for _l, lines, _e in halves[h] for line in lines for m in [start.match(line)] if m
                  for w in m.groups() if w} for h in ("build", "check")]
        assert found[0] and found[1] and not found[0] & found[1], (name, found[0] & found[1])


def test_a_fragment_replaces_a_statement_kept_for_its_unknown_word():
    # the statement said without its amount is kept as an observation; the fragment's reading replaces it
    *_, fragment, asked = run(KO, ["누리는 구슬이 열 개 있어.", "다올은 구슬이 두 개 있어.", "누리가 다올에게 구슬을 줬어.",
                                  "네 개.", "누리는 구슬이 몇 개 있어?"])
    assert fragment["status"] == "observed" and "6" in asked["answer"]
    # an amount alone after a statement that was read goes into nothing: it is held, never read into that statement
    *_, fragment, asked = run(EN, ["Nora has 5 pens.", "Otto has 2 pens.", "Nora gave Otto 2 pens.", "It was three.",
                                   "How many pens does Otto have?"])
    assert (fragment or {}).get("status") != "observed" and asked["status"] != "answered"


if __name__ == "__main__":
    import sys
    import time
    started = time.perf_counter()
    for name, halves in CASES.items():
        for half, cases in halves.items():
            for index, case in enumerate(cases):
                result = score(case)
                print(name, half, index, result, "" if result == "correct" else " / ".join(case[1]))
    print("seconds", round(time.perf_counter() - started, 1))
