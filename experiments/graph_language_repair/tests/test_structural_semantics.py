"""Public role-type and provenance controls."""
from experiments.graph_language_repair.core import read_text, search_rows


def event_with_lemma(document, lemma):
    return next(event for event in document["events"]
                if event["predicate_analysis"].get("lemma") == lemma)


def role(document, event, name):
    return next(item for item in document["roles"]
                if item["event"] == event["id"] and item["role"] == name)


def test_stative_unknown_predicate_has_subject_not_proven_agency():
    text = "날씨가 맑았다."
    document = read_text(text)
    event = event_with_lemma(document, "맑")
    assert event["semantic_status"] == "unknown"
    assert event["predicate_kind"] == "undetermined" and event["agency_status"] == "unknown"
    actor = role(document, event, "actor")
    assert actor["grammatical_role"] == "grammatical_subject"
    assert actor["semantic_role"] is None and actor["role_interpretation"] == "structural_alias"
    world = search_rows(document, [event["id"], "grammatical_subject", "날씨"])
    assert world["complete"] is True and world["matches"]
    ref = world["fact_sources"][0]["source_ref"]
    assert ref["semantic_role"] is None and ref["role_interpretation"] == "grammatical"
    proof = next(item for item in document["proofs"] if item["id"] == ref["proof"])
    assert proof["kind"] == "grammatical_role" and actor["row"] in proof["rows"]
    assert any(text[start:end] == "날씨" for start, end in ref["spans"])
    assert {actor["row"]} <= set(ref["depends_on"])


def test_opaque_active_predicate_structural_aliases_have_grounded_objects():
    document = read_text("서린이 목재를 도람했다.")
    event = event_with_lemma(document, "도람")
    assert event["semantic_status"] == "unknown" and event["agency_status"] == "unknown"
    for name, value, grammar in (("actor", "서린", "grammatical_subject"),
                                  ("object", "목재", "grammatical_object")):
        item = role(document, event, name)
        assert item["value"] == value and item["semantic_role"] is None
        world = search_rows(document, [event["id"], grammar, value])
        assert world["complete"] and world["matches"]
        assert world["fact_sources"][0]["source_ref"]["rows"]
        legacy = search_rows(document, [event["id"], name, value])
        ref = legacy["fact_sources"][0]["source_ref"]
        assert ref["role_interpretation"] == "structural_alias"
        assert ref["grammatical_role"] == grammar and ref["semantic_role"] is None


def test_opaque_passive_subject_is_not_conflated_with_semantic_object():
    document = read_text("목재가 서린에 의해 도람되었다.")
    event = event_with_lemma(document, "도람")
    item = role(document, event, "object")
    assert event["voice"] == "passive" and item["value"] == "목재"
    assert item["grammatical_role"] == "grammatical_subject"
    assert item["semantic_role"] is None and item["role_interpretation"] == "structural_alias"
    assert search_rows(document, [event["id"], "grammatical_subject", "목재"])["matches"]


def test_declared_transfer_and_check_retain_declared_semantic_roles():
    document = read_text("서린이 목재를 나린에게 전달했다. 감사팀이 그 전달을 확인했다.")
    transfer = next(event for event in document["events"] if event["action"] == "action:transfer")
    check = next(event for event in document["events"] if event["action"] == "action:check")
    assert transfer["semantic_status"] == check["semantic_status"] == "declared"
    for event, name in ((transfer, "actor"), (check, "checking_actor")):
        item = role(document, event, name)
        assert item["semantic_role"] == name and item["role_interpretation"] == "declared_semantic"
        source = search_rows(document, [event["id"], name, item["value"]])["fact_sources"][0]["source_ref"]
        assert source["semantic_role"] == name


def test_negative_reported_structural_roles_keep_scope_and_polarity_dependencies():
    document = read_text("보고서에 따르면 서린이 목재를 도람하지 않았다.")
    event = event_with_lemma(document, "도람")
    subject = role(document, event, "actor")
    rows = {item["id"]: item for item in document["rows"]}
    original = rows[subject["row"]]
    assert original["scope_kind"] == "attribution" and original["claim"] != "claim:0"
    assert event["polarity"] is False
    assert any(rows[key]["triple"][1] == "action" and rows[key]["polarity"] is False
               for key in original["depends_on"])


def test_predicate_typing_is_queryable_and_carried_through_action_source():
    document = read_text("서린이 목재를 도람했다.")
    event = event_with_lemma(document, "도람")
    for predicate in ("predicate_semantic_status", "agency_status"):
        world = search_rows(document, [event["id"], predicate, "unknown"])
        assert world["complete"] and world["matches"]
        assert world["fact_sources"][0]["source_ref"]["typing_policy"] == event["typing_policy"]
    world = search_rows(document, [event["id"], "action_type", event["action"]])
    source = world["fact_sources"][0]["source_ref"]
    assert (source["semantic_status"], source["predicate_kind"], source["agency_status"]) == (
        "unknown", "undetermined", "unknown")


def test_distinct_opaque_predicates_share_no_inferred_semantics():
    document = read_text("서린이 목재를 도람했다. 나린이 서류를 미결했다.")
    left = event_with_lemma(document, "도람")
    right = event_with_lemma(document, "미결")
    assert left["action"] != right["action"]
    assert left["semantic_status"] == right["semantic_status"] == "unknown"
    assert role(document, left, "object")["semantic_role"] is None
    assert role(document, right, "object")["semantic_role"] is None
