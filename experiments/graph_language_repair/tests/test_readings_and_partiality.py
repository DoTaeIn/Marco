# -*- coding: utf-8 -*-
"""Surviving readings, recorded drops, contradictions, and partial readings.

Repairs under test: the gate chain that aborted a clause on a missing cue, and
the split that suppressed facts elsewhere in the document (CORE-STATUS F1, F4;
CONTRACT C6, C8, C9).
"""
from experiments.graph_language_repair.core import read_text
from experiments.graph_language_repair.tests.controls import CONTROLS
from experiments.graph_language_repair.tests.helpers import (events, reading, role_values,
                                                             rows)


def _readings_of(document, clause):
    return [item for item in document["readings"] if item["clause"] == clause]


def test_two_classes_of_one_marker_give_two_surviving_readings():
    """C6: nothing is picked when the policy cannot separate the readings."""
    document = reading("source_or_place")
    assert len(_readings_of(document, "clause:0")) == 2
    pair = _readings_of(document, "clause:0")
    assert pair[0]["competes_with"] == [pair[1]["id"]]
    assert pair[1]["competes_with"] == [pair[0]["id"]]
    assigned = {item["role"] for item in document["roles"]}
    assert {"checking_source", "place"} <= assigned


def test_competing_readings_are_separate_events_of_one_clause():
    document = reading("source_or_place")
    clause = {event["clause"] for event in document["events"]}
    assert clause == {"clause:0"}
    assert len(document["events"]) == 2
    assert len({event["reading"] for event in document["events"]}) == 2


def test_competing_readings_are_recorded_as_a_contradiction():
    document = reading("source_or_place")
    conflicts = [item for item in document["contradictions"]
                 if item["kind"] == "reading_conflict"]
    assert len(conflicts) == 1
    assert sorted(conflicts[0]["readings"]) == ["reading:0", "reading:1"]
    assert conflicts[0]["rows"]


def test_rows_carry_the_reading_that_produced_them():
    document = reading("source_or_place")
    content = [row for row in document["rows"] if row["layer"] == "content"]
    assert content
    for row in content:
        assert row["reading"] in {"reading:0", "reading:1"}


def test_expected_role_completeness_does_not_discard_an_instrument():
    document = reading("goal_or_instrument")
    assert len(document["events"]) == 2
    assert any(role["role"] == "destination" and role["value"] == "창고" for role in document["roles"])
    assert any(role["role"] == "instrument" and role["value"] == "창고" for role in document["roles"])
    assert not document["dropped_readings"]
    assert all(item["competes_with"] for item in document["readings"])


def test_instrument_and_destination_are_separate_readings():
    for text, value in (("서진이 전화로 소식을 전달했다.", "전화"),
                        ("서진이 수레로 부품을 전달했다.", "수레")):
        document = read_text(text)
        alternatives = {(role["role"], role["value"]) for role in document["roles"]}
        assert {("instrument", value), ("destination", value)} <= alternatives
        assert len(document["readings"]) == 2
        assert all(item["competes_with"] for item in document["readings"])


def test_nothing_is_dropped_where_the_policy_cannot_separate():
    assert reading("source_or_place")["dropped_readings"] == []


def test_an_undeclared_predicate_leaves_its_clause_unresolved():
    document = reading("unknown_predicate")
    reasons = {item["reason"] for item in document["unresolved"]}
    assert "no_predicate_match" in reasons
    gap = [item for item in document["unresolved"]
           if item["reason"] == "no_predicate_match"][0]
    start, end = gap["span"]
    assert "고쳤다" in document["text"][start:end]


def test_an_undeclared_predicate_does_not_suppress_the_rest():
    """C8: a correct partial answer must not need a complete parse."""
    document = reading("unknown_predicate")
    assert role_values(document, "event:0", "checking_actor") == ["검사관"]
    assert role_values(document, "event:0", "checking_object") == ["부품"]
    assert rows(document, "event:0", "action", "action:check")


def test_an_unmapped_marker_class_is_recorded_and_the_clause_still_solves():
    document = read_text("김민수가 부품을 창고에서 받았다.")
    assert role_values(document, "event:0", "actor") == ["김민수"]
    assert role_values(document, "event:0", "object") == ["부품"]
    assert role_values(document, "event:0", "origin") == ["창고"]


def test_a_predicate_with_no_arguments_still_produces_an_event():
    document = reading("predicate_without_arguments")
    assert len(events(document)) == 1
    assert events(document)[0]["notes"] == ["predicate_without_arguments"]
    assert rows(document, "event:0", "action", "action:transfer")
    assert document["roles"] == []
    assert events(document)[0]["missing_roles"] == ["actor", "object", "origin",
                                                    "destination"]


def test_a_polarity_contradiction_on_one_subject_is_recorded():
    """C9: both rows are kept and joined."""
    document = read_text("김민수가 부품을 이수진에게 전달했다. 그 부품은 이수진에게 전달되지 않았다.")
    conflicts = [item for item in document["contradictions"]
                 if item["kind"] == "polarity_across_events"]
    assert conflicts
    assert conflicts[0]["hypotheses"]
    assert len(document["events"]) == 2, "neither reading is deleted"


def test_every_control_reports_the_limits_that_were_in_force():
    for name in CONTROLS:
        document = reading(name)
        assert document["limits"]["applied"]["max_rows"] > 0
        assert document["limits"]["graph_files"]
        assert document["limits"]["notes"] == []


def test_a_text_over_the_cap_is_refused_rather_than_truncated_silently():
    from experiments.graph_language_repair.core import load_graphs
    cap = load_graphs().limits()["max_text_chars"]
    try:
        read_text("가" * (cap + 1))
    except ValueError as error:
        assert "max_text_chars" in str(error)
    else:
        raise AssertionError("an over-long text must be refused")


def test_a_declared_nonfinal_form_gives_the_clause_a_boundary():
    """A1: a conjoined clause must not let the next predicate absorb its arguments."""
    document = read_text("김과장이 부품을 전달했고 박검사관이 그 전달을 확인했다.")
    assert len(document["events"]) == 2
    transfer = [event for event in document["events"]
                if event["action"] == "action:transfer"][0]
    check = [event for event in document["events"]
             if event["action"] == "action:check"][0]
    assert role_values(document, transfer["id"], "actor") == ["김과장"]
    assert role_values(document, transfer["id"], "object") == ["부품"]
    assert role_values(document, check["id"], "checking_actor") == ["박검사관"]
    assert role_values(document, check["id"], "checking_object") == ["그 전달"]
    assert "김과장" not in role_values(document, check["id"], "checking_actor")


def test_an_undeclared_connective_yields_rival_readings_not_two_actors():
    """A1 backstop: one reading may never assert two fillers of a single-fill role.

    ``전달했는데`` is not a declared form, so the clause boundary is missed and
    the checking construction sees two candidate actors.  The core emits one
    reading per candidate, cross-listed, with the others recorded as rival
    bindings — it does not assert both with no uncertainty (C6).
    """
    document = read_text("김과장이 부품을 전달했는데 박검사관이 그 전달을 확인했다.")
    readings = {event["reading"] for event in document["events"]}
    assert len(readings) > 1
    assert any(event["rival_roles"] for event in document["events"])
    for event in document["events"]:
        assert len(role_values(document, event["id"], "checking_actor")) <= 1
    for item in document["readings"]:
        assert item["competes_with"]
    assert any(item["reason"].startswith("rival_role_binding") for item in document["readings"])
    rivals = [item for item in document["unresolved"]
              if item["reason"] == "rival_role_binding"]
    assert rivals, "the binding not taken is recorded, not dropped"
    assert [item for item in document["contradictions"]
            if item["kind"] == "reading_conflict"]


def test_an_adjunct_role_the_frame_allows_to_repeat_stays_in_one_reading():
    """A12: the dedup rule no longer decides a semantic question by itself."""
    document = read_text("검사관이 창고에서 사무실에서 부품을 확인했다.")
    both = [event for event in document["events"]
            if len(role_values(document, event["id"], "place")) == 2]
    assert both, "the nested-location reading survives"
    assert [item for item in document["contradictions"]
            if item["kind"] == "role_filled_twice"] == []


def test_a_well_formed_clause_is_never_flagged_that_way():
    for name in ("active_transfer", "passive_with_agent", "multiword_checker",
                 "report_suffix", "continuation_same_event"):
        document = reading(name)
        assert [item for item in document["contradictions"]
                if item["kind"] == "role_filled_twice"] == [], name
        for event in document["events"]:
            assert event["rival_roles"] == [], name


def test_core_solution_cap_marks_reading_incomplete_without_faking_a_drop():
    from experiments.graph_language_repair.core.graph_store import load_graphs
    store = load_graphs()
    original_limits = store.limits
    def limited():
        limits = original_limits()
        limits["max_solutions_per_segment"] = 1
        return limits
    store.limits = limited
    document = read_text("서진이 전화로 소식을 전달했다.", store=store)
    assert document["limits"]["complete"] is False
    assert "max_solutions_per_segment" in document["limits"]["notes"]
    assert "max_solutions_per_segment" in document["events"][0]["notes"]
    assert not document["dropped_readings"]
