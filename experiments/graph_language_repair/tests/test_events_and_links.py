# -*- coding: utf-8 -*-
"""Event identity, its counterexamples, and proof-carrying completion.

Repairs under test: the prefix-first gate chain that rejected every
continuation, object identity treated as a merge licence, and the event split
that suppressed a fact already extracted (CORE-STATUS F1, F3, F4).
"""
from experiments.graph_language_repair.core import read_text
from experiments.graph_language_repair.tests.helpers import (events, hypotheses, reading,
                                                             role_values, roles, rows)


def _link(document, status=None):
    return hypotheses(document, "event_link", status)


def test_a_passive_continuation_of_a_unique_prior_transfer_is_one_event():
    document = reading("continuation_same_event")
    accepted = _link(document, "accepted")
    assert len(accepted) == 1
    assert accepted[0]["subjects"] == ["event:0", "event:1"]
    assert rows(document, "event:0", "same_event", "event:1")
    assert rows(document, "event:1", "same_event", "event:0")


def test_a_generic_pointing_head_also_continues_the_event():
    document = reading("continuation_generic_reference")
    accepted = _link(document, "accepted")
    assert len(accepted) == 1
    assert accepted[0]["rule"] == "event-link:rule_referring_expression_and_unique_prior"


def test_a_generic_pointing_head_pins_no_identity():
    """C2: the link is accepted, the entity question stays open."""
    document = reading("continuation_generic_reference")
    assert any(item["evidence"] == ["demonstrative_plus_generic_noun"]
               for item in document["entity_ambiguity"])
    pointing = [item for item in document["mentions"] if item["surface"] == "해당 항목"][0]
    named = [item for item in document["mentions"] if item["surface"] == "부품"][0]
    for entity in document["entities"]:
        assert not {pointing["id"], named["id"]} <= set(entity["mentions"])


def test_one_item_in_two_transfers_stays_two_events():
    """C1, the counterexample that must not merge."""
    for name in ("same_object_two_events", "same_object_two_events_generic"):
        document = reading(name)
        assert len(events(document)) == 2
        assert _link(document, "accepted") == []
        rejected = _link(document, "rejected")
        assert rejected and rejected[0]["rule"] == "event-link:reject_role_conflict"
        assert rows(document, "event:0", "same_event", "event:1") == []


def test_a_shared_item_alone_never_licenses_a_merge():
    """C1 at the mechanism level: identity holds, the link does not."""
    document = reading("two_priors_stay_candidate")
    assert _link(document, "accepted") == []
    candidates = _link(document, "candidate")
    assert candidates
    for item in candidates:
        kinds = {entry["kind"] for entry in item["evidence"]}
        assert "entity_identity" in kinds
        assert any(reason.startswith("insufficient_alone") for reason in item["blocked_by"])
        assert rows(document, item["subjects"][0], "same_event_candidate", item["subjects"][1])
        assert rows(document, item["subjects"][0], "same_event", item["subjects"][1]) == []


def test_two_prior_events_of_the_same_action_block_acceptance():
    one = reading("continuation_same_event")
    two = reading("two_priors_stay_candidate")
    assert _link(one, "accepted")
    assert not _link(two, "accepted")


def test_a_later_role_completes_an_earlier_event_with_a_proof():
    """C7, both directions, both spans retained."""
    document = reading("continuation_same_event")
    completed = roles(document, source="role_completion")
    assert {(item["event"], item["role"]) for item in completed} == {
        ("event:0", "destination"), ("event:1", "actor")}
    for item in completed:
        proof = [entry for entry in document["proofs"] if entry["id"] == item["proof"]][0]
        assert proof["kind"] == "role_completion"
        assert proof["policy"] == "event-link:rules"
        assert len(proof["spans"]) == 2
        row = [entry for entry in document["rows"] if entry["id"] == item["row"]][0]
        assert len(row["spans"]) == 2, "the earlier and the later span are both kept"
        assert row["hypotheses"]


def test_completion_never_happens_without_an_accepted_link():
    for name in ("same_object_two_events", "two_priors_stay_candidate", "report_then_check"):
        document = reading(name)
        assert roles(document, source="role_completion") == [], name


def test_a_completed_role_is_marked_and_the_clause_level_gap_is_still_visible():
    document = reading("continuation_same_event")
    event = [item for item in document["events"] if item["id"] == "event:0"][0]
    assert "destination" in event["filled_by_completion"]
    assert "destination" in event["missing_roles"], "the clause itself still lacks it"


def test_checking_a_transfer_is_not_the_same_event_as_the_transfer():
    document = reading("named_event_reference")
    assert _link(document) == []
    assert rows(document, "event:0", "same_event", "event:1") == []
    assert rows(document, "event:0", "verified_by", "event:1")


def test_a_polarity_conflict_blocks_a_link_and_is_recorded():
    document = reading("negative_check")
    rejected = _link(document, "rejected")
    assert rejected and rejected[0]["rule"] == "event-link:reject_polarity_conflict"


def test_an_exact_surface_repeat_is_one_entity_but_not_one_event():
    document = reading("repeated_name")
    first = [item for item in document["mentions"] if item["surface"] == "김민수"]
    assert len(first) == 2
    entities = [entity for entity in document["entities"]
                if {item["id"] for item in first} <= set(entity["mentions"])]
    assert len(entities) == 1, "two mentions, one identity"
    assert _link(document, "accepted") == [], "two different objects, two events"


def test_a_rejected_link_is_kept_as_a_hypothesis_with_its_reason():
    document = reading("same_object_two_events")
    rejected = _link(document, "rejected")
    assert rejected
    for item in rejected:
        assert item["blocked_by"]
        assert item["spans"]
        assert item["policy"] == "event-link:rules"


def test_a_candidate_link_requires_the_same_action():
    document = read_text("김민수가 부품을 이수진에게 전달했다. 검사관이 부품을 확인했다.")
    for item in hypotheses(document, "event_link"):
        subjects = [event for event in document["events"] if event["id"] in item["subjects"]]
        assert len({event["action"] for event in subjects}) == 1
