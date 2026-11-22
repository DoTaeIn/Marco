# -*- coding: utf-8 -*-
"""Event identity adversarial controls.

A shared value never licenses merging two events (CONTRACT C1), and when two
prior events equally qualify, a continuation must stay unresolved rather than
be pinned to one of them by position, recency or span length (CONTRACT C6;
AUDITOR.md: audit for same-item-implies-same-event shortcuts and arbitrary
longest/shortest-span preference).

Frozen public development tests. Passing them is not independent benchmark
evidence.
"""

from .conftest import (
    assert_exact_value_spans,
    bound_values,
    ordered_events,
    query,
    rows_matching,
)


def test_same_object_two_different_transfers_do_not_link(read_text, search_rows):
    text = "민수가 부품을 지은에게 전달했다. 수진이 부품을 태호에게 전달했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    events = ordered_events(reading)
    assert len(events) >= 2, "expected two separate transfer events, got %r" % (events,)
    ev0, ev1 = events[0]["id"], events[1]["id"]

    dest0 = bound_values(query(search_rows, reading, [ev0, "destination", "?x"]))
    dest1 = bound_values(query(search_rows, reading, [ev1, "destination", "?x"]))
    assert dest0 == ["지은"], dest0
    assert dest1 == ["태호"], dest1

    link = (
        rows_matching(reading, subject=ev0, predicate="same_event", obj=ev1)
        + rows_matching(reading, subject=ev1, predicate="same_event", obj=ev0)
    )
    assert not link, (
        "CONTRACT C1: sharing the object '부품' must not merge two transfers "
        "to different destinations into one event; "
        "event-link-policy.json:event-link:role_value_conflict is declared "
        "blocking for exactly this case"
    )


def test_ambiguous_passive_continuation_is_not_arbitrarily_resolved(read_text, search_rows):
    text = (
        "부품이 민수에 의해 전달되었다. "
        "자료가 지은에 의해 전달되었다. "
        "수진에게 전달되었다."
    )
    reading = read_text(text)
    assert_exact_value_spans(reading)

    events = ordered_events(reading)
    assert len(events) >= 3, (
        "expected two named passive transfers plus the ambiguous "
        "agentless continuation, got %r" % (events,)
    )
    ev0, ev1, ev2 = events[0]["id"], events[1]["id"], events[2]["id"]

    # event-link-policy.json note on event-link:unique_prior_event_of_same_action:
    # "If two earlier events share the action, the continuation is genuinely
    # ambiguous and this cue is absent, so the link stays a candidate."
    # It must not become an *accepted* same_event to either side.
    link_to_0 = rows_matching(reading, subject=ev2, predicate="same_event", obj=ev0)
    link_to_1 = rows_matching(reading, subject=ev2, predicate="same_event", obj=ev1)
    assert not link_to_0, "continuation must not be pinned to the first prior transfer"
    assert not link_to_1, "continuation must not be pinned to the second prior transfer"

    # CONTRACT C7 role completion requires an *accepted* link. With no
    # accepted link, the continuation's destination must not be grafted onto
    # either prior event just because it is the only one left unaccounted
    # for.
    for ev in (ev0, ev1):
        bound = bound_values(query(search_rows, reading, [ev, "destination", "?x"]))
        assert "수진" not in bound, (
            "%s must not receive the unlinked continuation's destination "
            "'수진' without an accepted same_event link" % (ev,)
        )
