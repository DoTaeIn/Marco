# -*- coding: utf-8 -*-
"""Regression controls for CORE-SECOND-AUDIT.md A1 and A2.

A1: an unrecognised clause conjunction lets one checking-action construction
absorb the previous clause's arguments too, so the actor of a *different*
event is falsely confirmed as the checker, and the real checker gets a hold.

A2: `event-link-policy.json`'s `rule_identity_and_unique_prior` accepts
`same_event` from a bundle of cues that are every one of them equally true of
two genuinely distinct repeated shipments whose second recipient is simply
unstated -- so a role gets invented for the second event from the first's
value, with no referring expression ever pointing back.

Frozen public development tests. Passing them is not independent benchmark
evidence. Run via `run_controls.py` in this directory, or under pytest if
available (see `CONTROLS-STATUS.md` for the exact command and for
current pass/fail against the live tree).
"""

from .conftest import (
    ask,
    assert_exact_value_spans,
    bound_values,
    ordered_events,
    query,
    rows_matching,
)


def test_a1_coordinated_clause_does_not_bind_a_wrong_actor_as_checker_confirmed(
    read_text, search_rows, compile_question, execute_plan, render
):
    text = "김과장이 부품을 전달했고 박검사관이 그 전달을 확인했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    _, wrong_result, wrong_rendered = ask(
        compile_question, execute_plan, render, reading, "김과장이 부품을 확인했나요?"
    )
    assert wrong_result.get("value") != "confirmed", (
        "CORE-SECOND-AUDIT A1: the document never states that 김과장 checked "
        "anything -- 김과장 is the *transfer* actor in the first, uncoordinated "
        "clause. A coordinated clause ('...전달했고 박검사관이...확인했다') must "
        "not let the checking construction absorb the preceding clause's "
        "subject as an extra checking_actor. Got gate=%r value=%r render=%r"
        % (wrong_result.get("gate"), wrong_result.get("value"), wrong_rendered)
    )

    _, real_result, real_rendered = ask(
        compile_question, execute_plan, render, reading, "박검사관이 그 전달을 확인했나요?"
    )
    assert real_result.get("value") != "confirmed", (
        "the source names the checking target as the transfer event, not the "
        "part item; a bare check also gives no result. The event-target "
        "question may establish occurrence, never a positive finding. Got "
        "gate=%r value=%r render=%r"
        % (real_result.get("gate"), real_result.get("value"), real_rendered)
    )


def test_a1_ambiguous_checking_actor_binding_is_not_silently_asserted(read_text, search_rows):
    text = "김과장이 부품을 전달했고 박검사관이 그 전달을 확인했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    events = ordered_events(reading)
    checking_events = [ev for ev in events if ev.get("action") == "action:check"]
    assert checking_events, "expected at least one checking event in this document"

    for ev in checking_events:
        actors = bound_values(query(search_rows, reading, [ev["id"], "checking_actor", "?x"]))
        if len(actors) <= 1:
            continue
        disclosed = (
            ev.get("complete") is False
            or bool(reading.get("unresolved"))
            or len(reading.get("readings", [])) > 1
        )
        assert disclosed, (
            "CORE-SECOND-AUDIT A1: %s binds checking_actor to more than one "
            "value (%r) from what reads as one coordinated clause, yet is "
            "reported complete=%r with an empty 'unresolved' and a single "
            "surviving reading -- a silent double-binding, not a disclosed "
            "ambiguity (CONTRACT C6/C8)" % (ev["id"], actors, ev.get("complete"))
        )


def test_a2_same_item_repeated_shipment_with_missing_recipient_is_not_joined(
    read_text, search_rows
):
    text = "김과장이 부품을 박대리에게 전달했다. 김과장이 부품을 전달했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    events = ordered_events(reading)
    assert len(events) >= 2, "expected two separate transfer clauses, got %r" % (events,)
    ev0, ev1 = events[0]["id"], events[1]["id"]

    link = (
        rows_matching(reading, subject=ev0, predicate="same_event", obj=ev1)
        + rows_matching(reading, subject=ev1, predicate="same_event", obj=ev0)
    )
    assert not link, (
        "CORE-SECOND-AUDIT A2: event-link-policy.json:rule_identity_and_unique_prior "
        "accepted same_event from entity_identity + same_action + "
        "unique_prior_event_of_same_action + compatible_roles_no_conflict + "
        "adjacent_segment alone. Every one of those five is equally true of "
        "two genuinely distinct repeated shipments whose second recipient is "
        "simply unstated -- none of them is a referring expression that "
        "actually points at the first happening. Got link rows %r" % (link,)
    )

    dest1 = bound_values(query(search_rows, reading, [ev1, "destination", "?x"]))
    assert dest1 == [], (
        "the second clause names no recipient at all; '박대리' must not be "
        "invented for event:1 via an unevidenced same_event link and a "
        "role_completion proof that was never licensed. Got %r" % (dest1,)
    )
