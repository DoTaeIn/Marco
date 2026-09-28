"""Fixed evaluation for evidence-derived concept overlays."""

from marco.learning.concepts import ExperienceConceptStore
from reasoning_context import ReasoningContext
import pytest

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default


KG = "graphs/graph_일상추론.kg"


def _experiences(context):
    for text in (
        "베풀다는 상대에게 구슬 2개를 주는 것이다.",
        "민수 구슬은 8개 있다. 지연 구슬은 3개 있다. 가람 구슬은 8개 있다. 하루 구슬은 3개 있다. 서준 구슬은 8개 있다. 유나 구슬은 3개 있다. 도윤 구슬은 8개 있다. 소라 구슬은 3개 있다. 하늘 구슬은 8개 있다. 별 구슬은 3개 있다.",
        "민수가 지연에게 베풀었다.", "가람이 하루에게 베풀었다.",
        "서준이 유나에게 베풀었다.", "도윤이 소라에게 베풀었다.", "하늘이 별에게 베풀었다."):
        assert context.turn(text, KG)["status"] == "observed"


def test_three_distinct_events_create_then_holdout_validates_and_applies_concept():
    context = ReasoningContext()
    for text in (
        "베풀다는 상대에게 구슬 2개를 주는 것이다.",
        "민수 구슬은 8개 있다. 지연 구슬은 3개 있다. 가람 구슬은 8개 있다. 하루 구슬은 3개 있다. 서준 구슬은 8개 있다. 유나 구슬은 3개 있다. 도윤 구슬은 8개 있다. 소라 구슬은 3개 있다. 하늘 구슬은 8개 있다. 별 구슬은 3개 있다.",
        "민수가 지연에게 베풀었다.", "가람이 하루에게 베풀었다.",
        "서준이 유나에게 베풀었다."):
        context.turn(text, KG)
    off = context.snapshot()
    assert not off["experience_concepts"]["applications"]
    assert not [row for row in off["inference_bundles"]["bundles"]
                if row.get("kind") == "concept_application"]
    # The fourth event validates the candidate.  A later, separate event is
    # the first post-activation application; validation evidence cannot also
    # prove application.
    assert context.turn("도윤이 소라에게 베풀었다.", KG)["status"] == "observed"
    assert not [row for row in context.snapshot()["experience_concepts"]["applications"]
                if row.get("phase") == "application"]
    assert context.turn("하늘이 별에게 베풀었다.", KG)["status"] == "observed"
    snapshot = context.snapshot()
    concepts = snapshot["experience_concepts"]
    candidate = next(row for row in concepts["candidates"] if row["scope"]["action"] == "베풀")
    assert candidate["status"] == "active"
    assert len(candidate["evidence_event_ids"]) == 3
    assert len(candidate["support_event_ids"]) == 1
    application = next(row for row in concepts["applications"]
                       if row["candidate_id"] == candidate["id"] and row.get("phase") == "application")
    assert application["event_id"] == candidate["application_event_ids"][0]
    assert set(candidate["lineage"]["validation_event_ids"]).isdisjoint(candidate["lineage"]["application_event_ids"])
    bundles = snapshot["inference_bundles"]["bundles"]
    support = next(row for row in bundles
                   if row["id"] == "support:" + application["id"])
    assert support["premise_fact_ids"] == [application["id"]]
    derived = next(row for row in bundles
                   if row["conclusion"] == application["derived_conclusion"])
    assert derived["rule"] == "concept-classification-with-executed-event"
    assert support["id"] in derived["premise_fact_ids"]
    assert "support:%s:status" % application["event_id"] in derived["premise_fact_ids"]


def test_same_declared_structure_can_span_distinct_action_names_without_mixing_shapes():
    def record(index, action):
        giver, taker = "giver-%d" % index, "taker-%d" % index
        event = {"id": "event:%d" % index, "action": action, "definition_version": 0,
                 "polarity": True, "modality": "asserted", "conditions": [],
                 "roles": {"은": giver, "에게": taker},
                 "program": {"signature": {"open_roles": {"giver": "은", "taker": "에게"},
                                           "role_slots": {"taker": "에게"},
                                           "fixed_values": {"item": "구슬", "n": "2"}},
                             "steps": [{"op": "emit", "triples": [
                                 [["$giver", "$item"], "count_remove", "$n"],
                                 [["$taker", "$item"], "count_add", "$n"]]}]},
                 "evidence": {"text": "%s experience %d" % (action, index)}}
        return {"event": event, "status": "executed",
                "effects": [[giver + " 구슬", "count_remove", "2"],
                            [taker + " 구슬", "count_add", "2"]]}

    store = ExperienceConceptStore()
    snapshot = store.sync([record(index, action) for index, action in enumerate(
        ("보냄", "나눔", "전달", "양도", "이관"), start=1)])
    candidate = next(row for row in snapshot["candidates"] if row["status"] == "active")
    assert candidate["scope"]["actions"] == ["나눔", "보냄", "양도", "이관", "전달"]
    assert candidate["scope"]["action"] is None
    application = next(row for row in snapshot["applications"] if row["phase"] == "application")
    assert application["event_id"] == "event:5"
    restored = ExperienceConceptStore()
    restored.restore(snapshot)
    assert restored.sync([record(index, action) for index, action in enumerate(
        ("보냄", "나눔", "전달", "양도", "이관"), start=1)])["applications"] == snapshot["applications"]


def test_cross_domain_program_skeleton_requires_three_domains_and_keeps_exact_effects_separate():
    def record(index, domain, action, predicate_pair):
        source, target = "source-%d" % index, "target-%d" % index
        event = {"id": "event:%d" % index, "domain": domain, "action": action,
                 "definition_version": 0, "polarity": True, "modality": "asserted",
                 "conditions": [], "roles": {"source": source, "target": target},
                 "program": {"signature": {"open_roles": {"source": "source", "target": "target"},
                                           "role_slots": {"target": "target"},
                                           "fixed_values": {"item": domain}},
                             "steps": [{"op": "emit", "triples": [
                                 [["$source", "$item"], predicate_pair[0], "removed"],
                                 [["$target", "$item"], predicate_pair[1], "added"]]}]},
                 "evidence": {"text": "%s/%s experience %d" % (domain, action, index)}}
        return {"event": event, "status": "executed",
                "effects": [[source, predicate_pair[0], "removed"], [target, predicate_pair[1], "added"]]}

    records = [record(1, "Quantity", "share", ("count_remove", "count_add")),
               record(2, "Location", "move", ("location_leave", "location_enter")),
               record(3, "Social", "link", ("relation_remove", "relation_add")),
               record(4, "Quantity", "share", ("count_remove", "count_add")),
               record(5, "Social", "link", ("relation_remove", "relation_add"))]
    store = ExperienceConceptStore()
    snapshot = store.sync(records)
    candidate = next(row for row in snapshot["candidates"]
                     if row["scope"].get("structural_level") == "cross_domain")
    assert candidate["status"] == "active"
    assert candidate["scope"]["domains"] == ["Location", "Quantity", "Social"]
    assert len(candidate["member_shape_ids"]) == 3
    assert [len(candidate[key]) for key in ("evidence_event_ids", "support_event_ids",
                                             "application_event_ids")] == [3, 1, 1]
    assert set(candidate["support_event_ids"]).isdisjoint(candidate["application_event_ids"])
    application = next(row for row in snapshot["applications"]
                       if row["candidate_id"] == candidate["id"] and row["phase"] == "application")
    assert application["event_id"] == "event:5"

    restored = ExperienceConceptStore(); restored.restore(snapshot)
    assert restored.sync(records)["applications"] == snapshot["applications"]
    store.disabled_ids.add(candidate["id"])
    assert not [row for row in store.sync(records)["applications"] if row["candidate_id"] == candidate["id"]]

    changed = records + [record(6, "Social", "link", ("relation_remove", "relation_add"))]
    changed[-1]["event"]["program"]["steps"][0]["op"] = "relation"
    conflicted = ExperienceConceptStore().sync(changed)
    invalid = next(row for row in conflicted["candidates"] if row["id"] == candidate["id"])
    assert invalid["status"] == "inactive" and invalid["counterexample_event_ids"] == ["event:6"]


def test_repeated_identical_record_does_not_count_and_counterexample_deactivates_after_restore():
    repeated = ReasoningContext()
    for text in ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
                 "민수 구슬은 12개 있다. 지연 구슬은 3개 있다.",
                 "민수가 지연에게 베풀었다.", "민수가 지연에게 베풀었다.",
                 "민수가 지연에게 베풀었다."):
        repeated.turn(text, KG)
    assert repeated.snapshot()["experience_concepts"]["candidates"] == []

    context = ReasoningContext()
    _experiences(context)
    restored = ReasoningContext()
    restored.restore(context.snapshot())
    # This definition revision changes the declared amount, hence its event
    # is a structural counterexample rather than a renamed support example.
    for text in ("베풀다는 상대에게 구슬 3개를 주는 것이다.",
                 "라온 구슬은 8개 있다. 마루 구슬은 3개 있다.",
                 "라온이 마루에게 베풀었다."):
        restored.turn(text, KG)
    concepts = restored.snapshot()["experience_concepts"]
    old = next(row for row in concepts["candidates"]
               if row["scope"]["action"] == "베풀" and row["structural_definition"]["fixed_values"])
    assert old["status"] == "inactive"
    assert old["counterexample_event_ids"]
    assert not [row for row in concepts["applications"] if row["candidate_id"] == old["id"]]


def test_two_independently_supported_structures_are_held_as_conflict_not_activated():
    context = ReasoningContext()
    for text in (
        "베풀다는 상대에게 구슬 2개를 주는 것이다.",
        "민수 구슬은 8개 있다. 지연 구슬은 3개 있다. 가람 구슬은 8개 있다. 하루 구슬은 3개 있다. 서준 구슬은 8개 있다. 유나 구슬은 3개 있다.",
        "민수가 지연에게 베풀었다.", "가람이 하루에게 베풀었다.", "서준이 유나에게 베풀었다.",
        "베풀다는 상대에게 구슬 3개를 주는 것이다.",
        "라온 구슬은 8개 있다. 마루 구슬은 3개 있다. 다온 구슬은 8개 있다. 루아 구슬은 3개 있다. 하린 구슬은 8개 있다. 태오 구슬은 3개 있다.",
        "라온이 마루에게 베풀었다.", "다온이 루아에게 베풀었다.", "하린이 태오에게 베풀었다."):
        context.turn(text, KG)
    candidates = context.snapshot()["experience_concepts"]["candidates"]
    assert len(candidates) == 2 and all(row["status"] == "conflict" for row in candidates)
    assert all(row["conflicts"] for row in candidates)
    assert not context.snapshot()["experience_concepts"]["applications"]


def test_correcting_a_source_experience_withdraws_active_application():
    context = ReasoningContext()
    _experiences(context)
    before = context.snapshot()["experience_concepts"]
    assert before["applications"]
    # This corrects an original event rather than appending a new one.  It
    # becomes a planned record, so it is no longer evidence for an actual
    # repeated experience and the previous holdout application is withdrawn.
    context.turn("정정: 민수가 지연에게 베풀었다. => 민수가 지연에게 베풀 예정이다.", KG)
    after = context.snapshot()["experience_concepts"]
    assert not after["applications"]
    assert any(row["status"] == "candidate" for row in after["candidates"])


def test_restoring_a_corrected_source_revalidates_its_original_concept_lineage():
    context = ReasoningContext()
    _experiences(context)
    active = next(row for row in context.snapshot()["experience_concepts"]["candidates"]
                  if row["status"] == "active")
    context.turn("정정: 민수가 지연에게 베풀었다. => 민수가 지연에게 베풀 예정이다.", KG)
    context.turn("정정: 민수가 지연에게 베풀 예정이다. => 민수가 지연에게 베풀었다.", KG)
    restored = next(row for row in context.snapshot()["experience_concepts"]["candidates"]
                    if row["id"] == active["id"])
    assert restored["status"] == "active"
    assert restored["lineage"]["construction_event_ids"] == active["lineage"]["construction_event_ids"]
    assert restored["lineage"]["validation_event_ids"] == active["lineage"]["validation_event_ids"]


def test_app_dialogue_persists_active_overlay_and_its_derived_application(tmp_path):
    from tests.test_reasoning_persistence import create_app

    app = create_app(tmp_path)
    chat = app.conversations.create_chat()["id"]
    for text in (
        "베풀다는 상대에게 구슬 2개를 주는 것이다.",
        "민수 구슬은 8개 있다. 지연 구슬은 3개 있다. 가람 구슬은 8개 있다. 하루 구슬은 3개 있다. 서준 구슬은 8개 있다. 유나 구슬은 3개 있다. 도윤 구슬은 8개 있다. 소라 구슬은 3개 있다. 하늘 구슬은 8개 있다. 별 구슬은 3개 있다.",
        "민수가 지연에게 베풀었다.", "가람이 하루에게 베풀었다.",
        "서준이 유나에게 베풀었다.", "도윤이 소라에게 베풀었다.", "하늘이 별에게 베풀었다."):
        app.turn(text, "concept_overlay", conversation_id=chat)
    saved = app.conversations.reasoning_state(chat)["experience_concepts"]
    assert any(row["status"] == "active" for row in saved["candidates"])
    assert saved["applications"]
    restarted = create_app(tmp_path)
    # Loading the actual persisted AppState conversation restores the overlay
    # before a new query; it remains isolated from every other conversation.
    restarted.turn("지금 지연 구슬은 몇 개야?", "concept_overlay", conversation_id=chat)
    restored = restarted.reasoning_contexts["chat_" + chat].snapshot()["experience_concepts"]
    assert restored["applications"] == saved["applications"]


def test_active_concept_changes_a_natural_app_query_and_exposes_its_learning_chain(tmp_path):
    from tests.test_reasoning_persistence import create_app

    app = create_app(tmp_path)
    chat = app.conversations.create_chat()["id"]
    for text in (
        "베풀다는 상대에게 구슬 2개를 주는 것이다.",
        "민수 구슬은 8개 있다. 지연 구슬은 3개 있다. 가람 구슬은 8개 있다. 하루 구슬은 3개 있다. 서준 구슬은 8개 있다. 유나 구슬은 3개 있다. 도윤 구슬은 8개 있다. 소라 구슬은 3개 있다. 하늘 구슬은 8개 있다. 별 구슬은 3개 있다.",
        "민수가 지연에게 베풀었다.", "가람이 하루에게 베풀었다.",
        "서준이 유나에게 베풀었다.", "도윤이 소라에게 베풀었다.", "하늘이 별에게 베풀었다."):
        app.turn(text, "concept_answer", conversation_id=chat)
    question = "하늘이 별에게 베푼 것은 어떤 개념이야?"
    enabled = app.turn(question, "concept_answer", conversation_id=chat)["answer"]
    assert enabled["trace"]["verdict"] == "계산완료"
    learned = next(row for row in enabled["reasoning"]["transitions"]
                   if row.get("evidence", {}).get("kind") == "concept_application")
    candidate_id = learned["evidence"]["candidate_id"]
    assert learned["evidence"]["premise_event_ids"]
    assert learned["evidence"]["validation_event_ids"]
    derived = next(row for row in enabled["reasoning"]["transitions"]
                   if row.get("rule") == "concept-classification-with-executed-event")
    assert len(derived["parents"]) == 2
    assert derived["fact"][1] == "classified_by"

    # This is the A/B evaluation switch: the same conversation, model, pack,
    # state and question, with only this learned overlay candidate disabled.
    context = app.reasoning_contexts["chat_" + chat]
    context.concepts.disabled_ids.add(candidate_id)
    disabled = app.turn(question, "concept_answer_disabled", conversation_id=chat)["answer"]
    assert disabled["trace"]["verdict"] == "조건부족"
    # Unrelated native state reasoning is unchanged by the overlay switch.
    assert app.turn("지금 지연 구슬은 몇 개야?", "concept_answer_disabled", conversation_id=chat)["answer"]["answer"] == "5개입니다."
    context.concepts.disabled_ids.clear()
    app.turn("정정: 민수가 지연에게 베풀었다. => 민수가 지연에게 베풀 예정이다.",
             "concept_answer_retract", conversation_id=chat)
    withdrawn = app.turn(question, "concept_answer_retract", conversation_id=chat)["answer"]
    assert withdrawn["trace"]["verdict"] == "조건부족"
    restarted = create_app(tmp_path)
    restarted.turn(question, "concept_answer_retract", conversation_id=chat)
    assert not restarted.reasoning_contexts["chat_" + chat].snapshot()["experience_concepts"]["applications"]


def test_concept_membership_and_pack_rule_use_the_regular_parser_answer_path():
    context = ReasoningContext()
    _experiences(context)
    parser = context._parser()
    application = context.snapshot()["experience_concepts"]["applications"][0]
    facts = context._common_inference_facts(parser)
    membership = parser.answer({"facts": facts,
                                "query": [{"triple": [application["event_id"], "instance_of", "?concept"],
                                           "render": ["$concept"]}]})
    classified = parser.answer({"facts": facts,
                                "query": [{"triple": [application["event_id"], "classified_by", "?concept"],
                                           "render": ["$concept"]}]})
    assert membership["answer"] == classified["answer"] == application["candidate_id"]
    assert any(row.get("rule") == "concept-classification-with-executed-event"
               for row in classified["transitions"])

    # Only disabling the learned application removes both ordinary queries;
    # the independent execution premise remains an asserted event fact.
    context.concepts.disabled_ids.add(application["candidate_id"])
    disabled = context._common_inference_facts(parser)
    assert any(row["triple"] == [application["event_id"], "event_status", "executed"]
               for row in disabled)
    assert parser.answer({"facts": disabled,
                          "query": [{"triple": [application["event_id"], "instance_of", "?concept"],
                                     "render": ["$concept"]}]}) is None
    assert parser.answer({"facts": disabled,
                          "query": [{"triple": [application["event_id"], "classified_by", "?concept"],
                                     "render": ["$concept"]}]}) is None
