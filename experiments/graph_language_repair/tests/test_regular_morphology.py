"""Public structural controls for graph-composed regular predicates."""
import pytest
from experiments.graph_language_repair.core import analyze_predicates, read_text, search_rows


def analysis(text, stem, mode):
    return next(item for item in analyze_predicates(text, mode=mode) if item["lemma"] == stem)


@pytest.mark.parametrize("stem,past,question,relative", [
    ("묶", "묶었다", "묶었나요", "묶은"),
    ("접", "접었다", "접었나요", "접은"),
    ("놓", "놓았다", "놓았나요", "놓은"),
    ("두", "두었다", "뒀나요", "둔"),
    ("나누", "나누었다", "나눴나요", "나눈"),
    ("솔묶", "솔묶었다", "솔묶었나요", "솔묶은"),
])
def test_body_question_and_relative_share_evidenced_stem(stem, past, question, relative):
    text = "라미가 작은 상자를 " + past + "."
    document = read_text(text)
    body = analysis(text, stem, "document")
    query = analysis("라미가 무엇을 " + question + "?", stem, "question")
    rel = analysis(relative + " 사람은 누구인가요?", stem, "question")
    assert body["action"] == query["action"] == rel["action"]
    assert body["semantic_status"] == "opaque"
    assert text[slice(*body["span"])] == past
    world = search_rows(document, ["?event", "action_type", query["action"]])
    assert world["complete"] is True and world["matches"]
    event = next(item for item in document["events"] if item["action"] == body["action"])
    object_world = search_rows(document, [event["id"], "object", "작은 상자"])
    assert object_world["matches"] and object_world["complete"] is True
    if len([item for item in document["events"] if item["action_span"] == event["action_span"]]) > 1:
        siblings = [item for item in document["events"] if item["action_span"] == event["action_span"]]
        assert len({item["clause"] for item in siblings}) == 1
        assert all(next(r for r in document["readings"] if r["id"] == item["reading"])["competes_with"] for item in siblings)


def test_negative_known_unknown_and_unsupported_moods_remain_distinct():
    text = "보고서에 따르면 누리가 끈을 묶지 않았다."
    document = read_text(text)
    event = next(item for item in document["events"] if item["predicate_analysis"].get("lemma") == "묶")
    assert event["polarity"] is False
    assert next(claim for claim in document["claims"] if claim["id"] == event["claim"])["kind"] == "attribution"
    assert analysis("누리가 끈을 묶지 않았나요?", "묶", "question")["polarity"] is False
    assert analysis("누리가 끈을 접었나요?", "접", "question")["action"] != event["action"]
    assert not read_text("누리가 끈을 묶겠다.")["events"]
    assert not analyze_predicates("누리가 끈을 묶었다면", mode="question")
    assert next(event for event in read_text("누리가 물건을 받았다.")["events"])["action"] == "action:receive"


def test_unmatched_embedded_noun_ending_does_not_create_predicate():
    document = read_text("누리가 묶었다연구소를 도람했다.")
    assert len(document["events"]) == 1
    assert any(role["value"] == "묶었다연구소" for role in document["roles"])
    assert not read_text("부품은 창고에 있는 것이 아니었다.")["events"]
