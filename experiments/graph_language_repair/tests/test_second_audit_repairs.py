# -*- coding: utf-8 -*-
"""Regressions for the second audit's findings, one test per anchor.

Each test names the finding it closes and states what the old behaviour was, so
a later change that reopens one of them fails here with its history attached.
Findings owned by the question/output layer (A7, A8, A15) are not tested here.
"""
from experiments.graph_language_repair.core import load_graphs, read_text
from experiments.graph_language_repair.tests.helpers import (claims_of_kind, hypotheses,
                                                             mention_at, reading,
                                                             role_values, rows)


# -- A1: clause boundary --------------------------------------------------

def test_a1_nonfinal_forms_are_declared_data_not_a_python_branch():
    store = load_graphs()
    nonfinal = [form for record in store.of_kind("action")
                for form in record["forms"] if form.get("finality") == "nonfinal"]
    assert nonfinal, "a clause boundary must come from declared forms"
    for form in nonfinal:
        assert form["voice"] and "polarity" in form


def test_a1_a_negated_nonfinal_clause_keeps_its_own_polarity():
    document = read_text("김과장이 부품을 전달하지 않고 박검사관이 그 전달을 확인했다.")
    transfer = [event for event in document["events"]
                if event["action"] == "action:transfer"][0]
    assert transfer["polarity"] is False
    assert role_values(document, transfer["id"], "actor") == ["김과장"]


# -- A2: same_event needs a referring expression ---------------------------

def test_a2_repeated_values_alone_do_not_merge_two_events():
    """The exact second-audit repro: no referring expression anywhere."""
    document = read_text("김과장이 부품을 박대리에게 전달했다. 김과장이 부품을 전달했다.")
    assert hypotheses(document, "event_link", "accepted") == []
    assert rows(document, "event:0", "same_event", "event:1") == []
    candidates = hypotheses(document, "event_link", "candidate")
    assert candidates and candidates[0]["blocked_by"]
    assert role_values(document, "event:1", "destination") == [], "no role is invented"
    assert [item for item in document["roles"]
            if item["source"] == "role_completion"] == []


def test_a2_every_accept_rule_demands_a_referring_expression():
    store = load_graphs()
    policy = store.get("event-link:rules")
    referring = set(policy["requires_referring_evidence"])
    assert referring
    for rule in policy["accept_rules"]:
        used = set(rule.get("all_of", ())) | set(rule.get("any_of", ()))
        assert used & referring, rule.get("id")


def test_a2_the_prior_count_is_over_clauses_not_readings():
    """Reading multiplicity may neither manufacture nor remove the cue."""
    one = read_text("김과장이 부품을 전달했다. 그 부품은 박대리에게 전달되었다.")
    assert hypotheses(one, "event_link", "accepted")
    store = load_graphs()
    assert store.get("event-link:rules")["prior_count_over"] == "clause"
    record = store.get("event-link:unique_prior_event_of_same_action")
    assert record["comparator_args"]["count_over"] == "clause"


def test_a2_a_referring_continuation_still_merges_and_completes():
    for text in ("김과장이 부품을 전달했다. 그 부품은 박대리에게 전달되었다.",
                 "김과장이 부품을 전달했다. 해당 항목은 박대리에게 전달되었다."):
        document = read_text(text)
        accepted = hypotheses(document, "event_link", "accepted")
        assert accepted, text
        assert rows(document, "event:0", "same_event", "event:1"), text
        completed = [item for item in document["roles"]
                     if item["source"] == "role_completion"]
        assert completed, text
        for item in completed:
            assert item["proof"]


# -- A5: hearsay ----------------------------------------------------------

def test_a5_agentless_hearsay_keeps_its_predicate_and_invents_no_reporter():
    document = read_text("부품이 창고에서 전달되었다고 한다.")
    assert len(document["events"]) == 2
    assert all(role_values(document, event["id"], "object") == ["부품"] for event in document["events"])
    assert any(role_values(document, event["id"], "origin") == ["창고"] for event in document["events"])
    assert any(role_values(document, event["id"], "place") == ["창고"] for event in document["events"])
    reported = claims_of_kind(document, "reported_claim")
    assert len(reported) == 1
    assert reported[0]["reporter"] is None
    assert reported[0]["reporter_mention"] is None
    assert rows(document, predicate="reporter") == []
    assert all(event["claim"] == reported[0]["id"] for event in document["events"])


def test_a5_the_hearsay_frame_declares_that_it_has_no_reporter():
    store = load_graphs()
    record = store.get("frame:report_hearsay")
    assert record["reporter_from"] == "none"
    assert record["reporter_required"] is False
    suffix = store.get("frame:report_suffix")
    assert "다고 한다" not in suffix["forms"], "the form that ate the predicate is gone"


# -- A6: reporter span ----------------------------------------------------

def test_a6_a_reporter_span_does_not_swallow_a_preceding_adverbial():
    document = read_text("어제 회의에서 김과장은 부품이 전달되었다고 말했다.")
    reported = claims_of_kind(document, "reported_claim")[0]
    assert reported["reporter"] == "김과장"
    assert rows(document, reported["id"], "reporter", "김과장")


def test_a6_a_prefix_reporter_span_starts_at_the_previous_consumed_end():
    document = read_text("어제 회의에서 경찰에 따르면 부품이 전달되었다.")
    reported = claims_of_kind(document, "reported_claim")[0]
    assert reported["reporter"] == "경찰"


# -- A10: marker inside verb morphology -----------------------------------

def test_a10_an_adnominal_ending_is_not_read_as_a_topic_marker():
    document = read_text("부품은 창고에 있는 것이 아니었다.")
    for item in document["roles"]:
        assert item["value"] not in ("있", "하", "되"), item
    assert document["coverage"]["regions_without_predicate"] >= 1


def test_a10_the_host_block_is_declared_data():
    store = load_graphs()
    records = store.of_kind("marker_host_policy")
    assert records
    for record in records:
        for rule in record["rules"]:
            assert rule["marker_classes"] and rule["host_ends_with"]
            assert rule["because"]


def test_a10_a_plain_topic_marker_still_works():
    document = read_text("부품은 박대리에게 전달되었다.")
    assert role_values(document, "event:0", "object") == ["부품"]


# -- A11: composite case marking ------------------------------------------

def test_a11_a_closing_marker_takes_a_following_internal_marker_into_its_span():
    document = read_text("부품이 창고에서부터 서울로 전달되었다.")
    assert role_values(document, "event:0", "origin") == ["창고"]
    assert role_values(document, "event:0", "destination") == ["서울"]
    origin = [item for item in document["roles"] if item["role"] == "origin"][0]
    start, end = origin["marker_span"]
    assert document["text"][start:end] == "에서부터"


def test_a11_the_extension_is_declared_policy():
    store = load_graphs()
    for record in store.of_kind("policy"):
        if record.get("role") == "chunk":
            assert record["extend_closing_marker_over_internal_forms"] is True
            return
    raise AssertionError("the chunk policy must declare the extension")


# -- A13: undecided is not refuted ----------------------------------------

def test_a13_an_undecided_identity_pair_is_unaccepted_not_rejected():
    document = read_text("생산 라인 책임자가 부품을 확인했다. 책임자가 서류를 전달했다.")
    long_side = mention_at(document, "생산 라인 책임자")
    short_side = mention_at(document, "책임자", occurrence=1)
    pair = [item for item in hypotheses(document, "entity_identity")
            if sorted(item["subjects"]) == sorted([long_side["id"], short_side["id"]])]
    assert pair, "the candidate identity must be published"
    assert pair[0]["status"] == "unaccepted"
    assert pair[0]["blocked_by"] == [], "nothing refused it"
    assert pair[0]["ambiguity_rules"] == ["identity-policy:ambiguous_head"]


def test_a13_a_refused_identity_pair_names_the_rule_that_refused_it():
    document = read_text("생산 라인 책임자가 부품을 확인했다.")
    nested = [item for item in hypotheses(document, "entity_identity")
              if item["status"] == "rejected"]
    assert nested
    for item in nested:
        assert item["rule"] == "identity-policy:reject_nested"
        assert item["blocked_by"] == ["identity-policy:reject_nested"]


# -- A14 / C10: no language inventory in Python ----------------------------

def test_a14_the_whitespace_inventory_comes_from_the_graph():
    store = load_graphs()
    assert store.mark_forms("space")
    document = read_text("생산 라인 책임자가 부품을 확인했다. 책임자가 서류를 전달했다.")
    assert [item for item in document["entity_ambiguity"]
            if "head_suffix_match" in item["evidence"]]


# -- unsupported clauses --------------------------------------------------

def test_the_coordinators_probe_document_is_now_read_in_full():
    """The probe said the first clause was lost with ``unresolved`` empty.

    The verb it used is declared now, so the clause is read rather than
    merely recorded as a gap, and the two clauses link through the
    demonstrative in the second one.
    """
    document = read_text("누리가 우산을 건넸다. 그 우산은 다온에게 전달되었다.")
    coverage = document["coverage"]
    assert coverage["segments"] == 2
    assert coverage["events"] == 2
    assert coverage["regions_without_predicate"] == 0
    first = [event for event in document["events"] if event["segment"] == "seg:0"][0]
    assert role_values(document, first["id"], "actor") == ["누리"]
    assert role_values(document, first["id"], "object") == ["우산"]
    assert hypotheses(document, "event_link", "accepted")


def test_an_undeclared_predicate_is_counted_and_located():
    """A clause the inventory cannot read is reported, with its span."""
    document = read_text("누리가 우산을 고쳤다. 그 우산은 다온에게 전달되었다.")
    coverage = document["coverage"]
    assert coverage["segments"] == 2
    assert coverage["events"] == 1
    assert coverage["regions_without_predicate"] == 1
    span = coverage["unsupported_spans"][0]
    assert document["text"][span[0]:span[1]] == "누리가 우산을 고쳤다"
    assert [item for item in document["unresolved"]
            if item["reason"] == "no_predicate_match"]


def test_a_missing_event_is_distinguishable_from_a_refused_link():
    missing = read_text("누리가 우산을 고쳤다. 그 우산은 다온에게 전달되었다.")
    refused = read_text("김과장이 부품을 박대리에게 전달했다. 같은 부품이 지은에게 전달되었다.")
    assert hypotheses(missing, "event_link") == []
    assert missing["coverage"]["regions_without_predicate"] == 1
    assert hypotheses(refused, "event_link", "rejected")
    assert refused["coverage"]["regions_without_predicate"] == 0


def test_coverage_is_reported_for_every_reading():
    for name in ("active_transfer", "continuation_same_event", "report_suffix"):
        coverage = reading(name)["coverage"]
        assert coverage["segments"] >= 1
        assert coverage["events"] >= 1
        assert coverage["regions_without_predicate"] == 0
