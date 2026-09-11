from relational_semantics import RelationalParser


def test_all_unrecognized_clauses_are_located_without_discarding_them():
    parser = RelationalParser()
    text = "돌은 23개 있다. 새 표현을 아직 모른다. 또 다른 표현도 모른다. 지금 돌은 몇 개야?"
    report = parser.diagnose(text)
    assert report["stage"] == "semantic_parse"
    assert report["answer"] is None
    assert len(report["diagnostics"]) == 2
    for row in report["diagnostics"]:
        span = row["evidence"]
        assert text[span["start"]:span["end"]] == span["text"]
        assert row["reason"] == "unrecognized_clause"
    assert parser.parse(text) is None


def test_ambiguity_report_preserves_competing_structures():
    report = RelationalParser().diagnose("오래된 지도는 작은 서랍에 있었다.")
    row = report["diagnostics"][0]
    assert row["reason"] == "ambiguous_clause"
    assert len(row["candidates"]) == 2
    assert ["오래된 지도", "location", "작은 서랍"] in [c["triple"] for c in row["candidates"]]


def test_missing_query_is_distinct_from_unknown_words():
    report = RelationalParser().diagnose("돌은 23개 있다.")
    assert report["diagnostics"] == [{"reason": "missing_query"}]


def test_missing_proof_is_distinct_from_two_conflicting_answers():
    parser = RelationalParser()
    missing = parser.diagnose("소라는 다미보다 키가 크다. 유리는 다미보다 키가 크다. 소라와 유리 중 누가 더 커?")
    assert missing["reason"] == "missing_proof"
    assert missing["candidates"] == []
    conflict = parser.diagnose("소라는 다미보다 키가 크다. 다미는 소라보다 키가 크다. 소라와 다미 중 누가 더 커?")
    assert conflict["reason"] == "nonunique_proof"
    assert len(conflict["candidates"]) == 2
    assert all(candidate["proof"] for candidate in conflict["candidates"])
