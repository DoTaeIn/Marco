"""Public synthetic structural tests; no sealed evaluation data."""
import pytest
from experiments.graph_language_repair.core import analyze_predicates, read_text, search_rows


@pytest.mark.parametrize("stem", ["도람", "미결", "나톱"])
def test_observed_stem_is_stable_across_voice_tense_question_and_negation(stem):
    forms = [
        ("라미가 푸른 조각을 " + stem + "했다.", "document", True, "active"),
        ("라미가 푸른 조각을 " + stem + "하지 않았다.", "document", False, "active"),
        ("푸른 조각이 라미에 의해 " + stem + "되었다.", "document", True, "passive"),
        ("라미가 무엇을 " + stem + "했나요?", "question", True, "active"),
        ("라미가 " + stem + "한 것은 무엇인가요?", "question", True, "active"),
    ]
    found = [analyze_predicates(text, mode=mode)[0] for text, mode, _, _ in forms]
    assert len({item["action"] for item in found}) == 1
    assert all(item["semantic_status"] == "opaque" and item["lemma"] == stem for item in found)
    for (text, _, polarity, voice), item in zip(forms, found):
        assert item["polarity"] is polarity and item["voice"] == voice
        assert text[slice(*item["stem_span"])] == stem
        assert text[slice(*item["span"])] == item["surface"]
    doc = read_text(forms[0][0])
    assert doc["events"][0]["action"] == found[0]["action"]
    assert any(role["role"] == "object" and role["value"] == "푸른 조각" for role in doc["roles"])
    world = search_rows(doc, ["?event", "action_type", found[0]["action"]])
    assert world["complete"] is True and world["matches"]


def test_distinct_unknown_stems_and_noun_suffix_are_not_equated():
    document = read_text("소미가 단지를 나톱했다고재단에 전달했다. 루아가 상자를 도람했다.")
    assert len({event["clause"] for event in document["events"]}) == 2
    assert all(event.get("predicate_analysis", {}).get("lemma") != "나톱" for event in document["events"])
    assert any(role["value"] == "나톱했다고재단" for role in document["roles"])
    first = analyze_predicates("누리가 종이를 도람했다.")[0]
    second = analyze_predicates("누리가 종이를 미결했다.")[0]
    assert first["action"] != second["action"]
    assert first["action"].startswith("action:observed:")


def test_nonfinal_clauses_and_report_scope_keep_identity_and_roles():
    text = "보고서에 따르면 라미가 돌을 도람했고 소미가 판을 미결했다."
    document = read_text(text)
    assert len(document["events"]) == 2
    assert all(event["claim"] != "claim:0" for event in document["events"])
    roles = {(role["event"], role["role"], role["value"]) for role in document["roles"]}
    assert {("event:0", "actor", "라미"), ("event:0", "object", "돌"),
            ("event:1", "actor", "소미"), ("event:1", "object", "판")} <= roles


def test_complement_predicates_match_body_identity_and_preserve_polarity():
    body = analyze_predicates("아라가 상자를 나톱했다.")[0]
    for suffix, polarity in (("했다고", True), ("하지 않았다고", False)):
        text = "아라가 상자를 나톱" + suffix + " 누가 보고했나요?"
        analyses = analyze_predicates(text, mode="question")
        target = next(item for item in analyses if item["lemma"] == "나톱")
        assert target["action"] == body["action"]
        assert target["polarity"] is polarity and target["mood"] == "complement"
        assert text[slice(*target["span"])] == "나톱" + suffix


def test_negated_passive_has_same_identity_and_no_positive_occurrence():
    body = read_text("푸른 조각이 라미에 의해 도람되지 않았다.")
    event = body["events"][0]
    action = next(row for row in body["rows"] if row["triple"] == [event["id"], "action", event["action"]])
    assert event["voice"] == "passive" and event["polarity"] is False
    assert action["polarity"] is False
    assert event["action"] == analyze_predicates("누가 조각을 도람했나요?", mode="question")[0]["action"]
