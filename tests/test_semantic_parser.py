"""비토큰 구조 파서는 원문에 드러난 관계만 인증 후보로 낸다."""
import semantic_parser
import state_engine


KG = "graphs/graph_일상추론.kg"


def test_structural_parser_answers_train_and_held_out_relations():
    parser = semantic_parser.SemanticParser()
    cases = (
        ("1 더하기 1은 얼마야?", "2입니다."),
        ("7과 5를 더한 값은?", "12입니다."),
        ("3x + 1 = 7이래. x는 얼마야?", "2입니다."),
        ("달리던 중 3위 주자를 앞질렀다. 나는 몇 위인가?", "3등입니다."),
        ("독립 작업 열 개를 동시에 끝내면 한 작업의 1시간과 같은 시간이 걸린다.", "1시간입니다."),
        ("물에 뜬 배에 달린 사다리에서 수면 위로 보이는 5칸은 물이 오르면 몇 칸인가?", "5칸입니다."),
    )
    for text, answer in cases:
        parsed = parser.parse(text)
        assert parsed["accepted"], parsed
        assert parsed["relations"][0]["evidence"]["text"] == text
        outcome = state_engine.evaluate(parsed, KG)
        assert outcome["answer"] == answer, outcome


def test_structural_parser_certifies_each_declared_basic_arithmetic_operator():
    parser = semantic_parser.SemanticParser()
    for text, answer in (("8 빼기 3은 얼마야?", "5입니다."),
                         ("3 곱하기 4는 얼마야?", "12입니다."),
                         ("12 나누기 3은 얼마야?", "4입니다.")):
        parsed = parser.parse(text)
        outcome = state_engine.evaluate(parsed, KG)
        assert parsed["accepted"], parsed
        assert outcome["answer"] == answer, outcome

    zero = parser.parse("12 나누기 0은 얼마야?")
    assert state_engine.evaluate(zero, KG)["status"] == "unknown"


def test_structural_parser_rejects_unknown_and_keeps_unitary_premise_explicit():
    parser = semantic_parser.SemanticParser()
    assert not parser.parse("바람의 기분은 몇 점일까?")["accepted"]
    parsed = parser.parse("반쪽짜리 구멍을 파려면 얼마나 걸릴까?")
    assert parsed["accepted"]
    outcome = state_engine.evaluate(parsed, KG)
    assert outcome["status"] == "premise_invalid"


def test_structural_parser_solves_only_complete_single_variable_equations():
    parser = semantic_parser.SemanticParser()
    parsed = parser.parse("-x - 2 = 4이면 x는?")
    assert parsed["accepted"]
    assert parsed["relations"][0]["type"] == "linear_equation"
    assert state_engine.evaluate(parsed, KG)["answer"] == "-6입니다."
    assert not parser.parse("3x + 1은 얼마야?")["accepted"]
