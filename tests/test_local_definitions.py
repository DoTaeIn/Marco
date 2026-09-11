"""로컬 위키 정의 색인의 입력 해석·원문 조회 회귀 시험."""
import json

from pathlib import Path

from local_definitions import DefinitionLookup
import engine


def test_definition_question_forms_and_domains():
    lookup = DefinitionLookup(Path("data/위키/정의문.jsonl"))
    cases = {
        "수학이 뭐야": "수학",
        "음계의 정의가 뭐야": "음계",
        "초월수란?": "초월수",
        "화학에 대해 설명해 줘": "화학",
        "DNA 뜻 알려 줘": "dna",
        "철학은 무엇인가": "철학",
        "문학에 관해 설명해줘": "문학",
        "중력이란 무엇인가요": "중력",
        "인공 지능이 뭐야": "인공지능",
        "기계학습이 뭐야": "기계 학습",
    }
    for question, expected_term in cases.items():
        result = lookup.lookup(question)
        assert result is not None, question
        assert result["term"] == expected_term, (question, result)
        assert result["definition"], question
        assert result["verified"] is True


def test_definition_lookup_refuses_dialogue_and_empty_disambiguation():
    lookup = DefinitionLookup(Path("data/위키/정의문.jsonl"))
    assert lookup.lookup("고마워") is None
    # '분수는 다음 뜻으로 쓰인다' 같은 안내문은 정의 답변으로 내보내지 않고,
    # 관계를 가진 수학 KG에 맡긴다.
    assert lookup.lookup("분수가 뭐야") is None


def test_engine_uses_local_definition_adapter_for_long_tail_term():
    """UI만이 아니라 표준 엔진 입구도 대량 정의 원문을 읽는다."""
    path, verdict, answer = engine.answer("초월수란?")
    assert path == "data/위키/정의문.jsonl"
    assert verdict == "원문정의"
    assert "초월수" in answer


def test_local_definition_comparison_requires_two_exact_terms():
    """비교는 모델의 차이 추정이 아니라 두 원문 정의의 병렬 조회여야 한다."""
    lookup = DefinitionLookup(Path("data/위키/정의문.jsonl"))
    result = lookup.compare("수학과 화학의 차이가 뭐야?")
    assert result and result["kind"] == "comparison"
    assert result["terms"] == ["수학", "화학"]
    assert all(entry["definition"] for entry in result["definitions"])
    assert lookup.compare("수학과 존재하지않는말의 차이가 뭐야?") is None

    path, verdict, answer = engine.answer("수학과 화학의 차이가 뭐야?")
    assert path == "data/위키/정의문.jsonl"
    assert verdict == "원문정의비교"
    assert "수학" in answer and "화학" in answer


def test_primary_definition_corpus_covers_hanja_definition_terms():
    """보조 한자 정의 표제어가 주 색인에서 빠지지 않는다."""
    primary = set()
    with Path("data/위키/정의문.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            primary.add(json.loads(line).get("말", "").strip().lower())
    missing = []
    with Path("data/위키/한자정의.jsonl").open(encoding="utf-8") as handle:
        for line in handle:
            term = json.loads(line).get("말", "").strip().lower()
            if term and term not in primary:
                missing.append(term)
    assert not missing, missing[:20]
