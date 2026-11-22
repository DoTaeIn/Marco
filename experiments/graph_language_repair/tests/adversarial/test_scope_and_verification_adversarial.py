# -*- coding: utf-8 -*-
"""Scope and verification adversarial controls (CONTRACT C5).

 * A checking action named only inside a report must never satisfy
   ``checks``/``verified_by``, even carrying the identical explicit-event
   cue that accepts the link when the same clause is stated directly
   (verification-policy.json ``forbidden_source_scopes``).
 * A negated checking action ("did not check") is an occurrence negation,
   not a verification outcome of "denied" -- AUDITOR.md Contract review 1,
   item 1: "A negative action is not a negative proposition result."
 * A checking action naming a *different* object than a nearby prior event
   must not be linked to it just because a check exists nearby.

Frozen public development tests. Passing them is not independent benchmark
evidence.

One test below (``test_negated_check_action_is_not_a_denied_outcome``) pins
down a live tension between AUDITOR.md's Contract review 1 and the literal
``outcome_from_polarity`` table in ``graphs/core/verification-policy.json``;
see ``.marco/graph-repair-20261111/audit/CONTROLS-STATUS.md``
for the exact wording and why this is written as the expected behavior
rather than a looser check.
"""

from .conftest import (
    assert_exact_value_spans,
    bound_values,
    claim_scope_kind,
    event_claim,
    ordered_events,
    query,
    rows_matching,
)


def test_explicit_reference_check_direct_vs_reported(read_text, search_rows):
    text = (
        "민수가 부품을 지은에게 전달했다. "
        "그 전달을 수진이 확인했다. "
        "태호에 따르면 지은이 그 전달을 확인했다."
    )
    reading = read_text(text)
    assert_exact_value_spans(reading)

    events = ordered_events(reading)
    # A single clause can now have sibling readings, so event allocation
    # order is not a stable clause/action identity. Select by graph metadata
    # and claim scope, then preserve all sibling checks in the assertions.
    transfer_events = [event for event in events if event.get("action") == "action:transfer"]
    check_events = [event for event in events if event.get("action") == "action:check"]
    assert transfer_events and check_events, (
        "expected a transfer and check events, got %r" % (events,)
    )
    transfer_ids = {event["id"] for event in transfer_events}
    direct_checks = [event for event in check_events
                     if claim_scope_kind(reading, event_claim(reading, event["id"]))
                     != "reported_claim"]
    reported_checks = [event for event in check_events
                       if claim_scope_kind(reading, event_claim(reading, event["id"]))
                       == "reported_claim"]
    assert direct_checks and reported_checks, (
        "expected direct and reported check claim groups, got %r" % (events,)
    )
    direct_ids = {event["id"] for event in direct_checks}
    reported_ids = {event["id"] for event in reported_checks}

    assert all(claim_scope_kind(reading, event_claim(reading, event_id)) == "reported_claim"
               for event_id in reported_ids), (
        "'태호에 따르면 ...' must put the inner clause's claim in scope_kind "
        "reported_claim (scope-policy.json:frame:report_prefix)"
    )
    assert all(claim_scope_kind(reading, event_claim(reading, event_id)) != "reported_claim"
               for event_id in direct_ids), (
        "the direct checking clause carries no report frame and must not "
        "be scoped as a report"
    )

    reported_links = [row for reported_check in reported_ids for transfer in transfer_ids
                      for row in rows_matching(reading, subject=reported_check,
                                               predicate="checks", obj=transfer)]
    assert not reported_links, (
        "CONTRACT C5 / verification-policy.json forbidden_source_scopes: a "
        "checking action named only inside a report ('...에 따르면') must "
        "never satisfy 'checks', whatever explicit-event cue it carries"
    )

    direct_links = (
        [row for direct_check in direct_ids for transfer in transfer_ids
         for row in rows_matching(reading, subject=direct_check,
                                  predicate="checks", obj=transfer)]
        + [row for direct_check in direct_ids for transfer in transfer_ids
           for row in rows_matching(reading, subject=transfer,
                                    predicate="verified_by", obj=direct_check)]
    )
    assert direct_links, (
        "positive half of the contrast: the identical cue ('그 전달을 "
        "확인했다'), stated directly, is verification-policy.json's "
        "documented accept rule (verification:rule_named via "
        "explicit_event_reference) and should produce 'checks'/"
        "'verified_by'"
    )


def test_negated_check_action_is_not_a_denied_outcome(read_text, search_rows):
    text = "민수가 부품을 확인하지 않았다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    ev0 = ordered_events(reading)[0]["id"]
    outcomes = bound_values(query(search_rows, reading, [ev0, "checking_outcome", "?x"]))
    assert "denied" not in outcomes, (
        "AUDITOR.md Contract review 1, item 1: '민수가 부품을 확인하지 "
        "않았다' means the check did not happen at all, not that a "
        "completed check denied the object. checking_outcome must not read "
        "as 'denied' here -- that would conflate action-occurrence polarity "
        "with a verification result. Got %r" % (outcomes,)
    )
    assert outcomes == ["unstated"], (
        "CONTRACT #4 enumerates checking_outcome as confirmed/denied/"
        "unstated: a matched-but-negated checking construction should read "
        "as the positive, queryable value 'unstated' (verification-policy.json "
        "no_checking_action), not merely as an absent match reached by "
        "suppressing 'denied' through row-level polarity inversion -- a "
        "consumer asking 'what is event:0's checking_outcome' must get an "
        "explicit answer, not silence indistinguishable from 'no checking "
        "event exists at all'. Got %r" % (outcomes,)
    )


def test_checked_then_separately_found_defective_stays_two_facts(read_text, search_rows):
    text = "민수가 부품을 확인했다. 그 부품은 불량이었다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    events = ordered_events(reading)
    assert len(events) >= 2, "expected a check event and a separate identify event, got %r" % (events,)
    check, identify = events[0]["id"], events[1]["id"]

    outcome = bound_values(query(search_rows, reading, [check, "checking_outcome", "?x"]))
    occurrence = bound_values(query(search_rows, reading, [check, "checking_occurred", "?x"]))
    assert occurrence == ["occurred"]
    assert outcome == ["unstated"], (
        "a bare positive checking action says it occurred but gives no "
        "result; it must read 'unstated' regardless of what the separate identify clause "
        "later says about the object; got %r" % (outcome,)
    )

    # action:check and action:identify are different actions; same_event
    # requires same_action (event-link-policy.json), so sharing the object
    # '그 부품' must not merge these into one event or launder the identify
    # clause's content into the check's checking_outcome.
    merged = (
        rows_matching(reading, subject=check, predicate="same_event", obj=identify)
        + rows_matching(reading, subject=identify, predicate="same_event", obj=check)
    )
    assert not merged, (
        "a checking clause and a separate identify clause about the same "
        "item are not one event (CONTRACT C1); 'checked and rejected' must "
        "stay two rows, not one fused outcome"
    )


def test_verifier_checking_a_different_object_does_not_link(read_text, search_rows):
    text = "민수가 부품을 지은에게 전달했다. 민수가 자료를 확인했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    events = ordered_events(reading)
    assert len(events) >= 2
    transfer, check = events[0]["id"], events[1]["id"]

    link = (
        rows_matching(reading, subject=check, predicate="checks", obj=transfer)
        + rows_matching(reading, subject=transfer, predicate="verified_by", obj=check)
    )
    assert not link, (
        "checking_object '자료' does not match the transfer's object "
        "'부품': a checking event naming a different object must not "
        "verify this transfer just because the same actor checked "
        "something nearby"
    )

    outcome = bound_values(query(search_rows, reading, [check, "checking_outcome", "?x"]))
    occurrence = bound_values(query(search_rows, reading, [check, "checking_occurred", "?x"]))
    assert occurrence == ["occurred"]
    assert outcome == ["unstated"], (
        "the check of '자료' still occurred but gives no result; it must report "
        "own outcome -- only the cross-event link to the unrelated "
        "transfer must be withheld; got %r" % (outcome,)
    )
