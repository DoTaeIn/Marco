"""Public controls for quoted and interrogative event boundaries."""
import pytest
from experiments.graph_language_repair.core import read_text, search_rows


def events(document):
    claims = {claim["id"]: claim for claim in document["claims"]}
    return [(event, claims[event["claim"]]) for event in document["events"]
            if event["action"].startswith("action:observed:")]


@pytest.mark.parametrize("text", [
    '“미린이 도면을 색인했다.”라는 문장은 거짓이다.',
    '“루아가 붉은 조각을 도람했다.”라는 말은 틀렸다.',
])
def test_quoted_predicate_in_host_is_not_direct_assertion(text):
    document = read_text(text)
    event, claim = events(document)[0]
    assert claim["kind"] == "quoted_text"
    assert text[slice(*claim["span"])].startswith("“")
    assert text[slice(*claim["span"])].endswith("”")
    role = next(row for row in document["rows"] if row["triple"][0] == event["id"] and row["triple"][1] == "object")
    assert role["claim"] == claim["id"] and role["scope_kind"] == "quoted_text"
    assert document["limits"]["complete"] is True
    assert search_rows(document, [event["id"], "object", "?x"])["complete"] is True


@pytest.mark.parametrize("text,kind", [
    ("루아가 돌을 도람했다?", "interrogative"),
    ("루아가 돌을 도람했다.", "direct_text"),
    ("루아가 '돌'을 도람했다.", "direct_text"),
    ('보고서에 따르면 “루아가 돌을 도람했다.”', "attribution"),
    ('“루아가 돌을 도람했다?”', "interrogative"),
])
def test_scope_depends_on_predicate_not_presence_of_quoted_value(text, kind):
    document = read_text(text)
    event, claim = events(document)[0]
    assert claim["kind"] == kind
    assert event["predicate_analysis"]["lemma"] == "도람"
    assert any(role["event"] == event["id"] and role["role"] == "object" for role in document["roles"])


def test_nonassertive_check_cannot_independently_verify():
    document = read_text('미린이 도면을 전달했다. “감사팀이 그 전달을 사실로 확인했다.”라는 문장은 거짓이다.')
    check = next(event for event in document["events"] if event["emits_verification"])
    claim = next(item for item in document["claims"] if item["id"] == check["claim"])
    assert claim["kind"] == "quoted_text"
    assert not any(row["triple"][1] == "verified_by" for row in document["rows"])
