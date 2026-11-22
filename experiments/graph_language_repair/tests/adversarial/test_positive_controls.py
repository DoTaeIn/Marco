# -*- coding: utf-8 -*-
"""Positive controls, kept alongside the adversarial negatives in this
directory so that a fix aimed at one of those negatives cannot silently
break the ordinary case it sits next to: an explicit event link, a
proof-carrying late role completion, and legal partial output under an
incomplete global parse (CONTRACT C6, C7, C8).

Frozen public development tests. Passing them is not independent benchmark
evidence.
"""

from .conftest import (
    assert_exact_value_spans,
    bound_values,
    ordered_events,
    query,
    rows_matching,
    span_within,
)


def test_explicit_event_link_demonstrative_and_unique_prior(read_text, search_rows):
    text = "민수가 부품을 전달했다. 그 부품을 지은에게 전달했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    events = ordered_events(reading)
    assert len(events) >= 2, "expected the first transfer plus its continuation, got %r" % (events,)
    ev0, ev1 = events[0]["id"], events[1]["id"]

    link = (
        rows_matching(reading, subject=ev0, predicate="same_event", obj=ev1)
        + rows_matching(reading, subject=ev1, predicate="same_event", obj=ev0)
    )
    assert link, (
        "event-link-policy.json:event-link:rule_demonstrative_and_unique_prior: "
        "a demonstrative repeat of the object ('그 부품'), the same action, "
        "a unique prior event of that action, no role conflict and an "
        "adjacent segment is the documented accept case for 'same_event', "
        "but no such row was found"
    )


def test_late_role_completion_preserves_both_spans(read_text, search_rows):
    text = "민수가 부품을 전달했다. 그 부품을 지은에게 전달했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    events = ordered_events(reading)
    ev0, ev1 = events[0]["id"], events[1]["id"]

    assert "destination" in events[0].get("missing_roles", []), (
        "the first clause states no recipient; destination should be "
        "recorded missing until completed, not guessed up front: got "
        "missing_roles %r" % (events[0].get("missing_roles"),)
    )

    dest = bound_values(query(search_rows, reading, [ev0, "destination", "?x"]))
    assert dest == ["지은"], (
        "CONTRACT C7: a role missing from an earlier event may be filled "
        "by a later linked clause's own evidence; got %r" % (dest,)
    )

    destination_row_ids = {
        row["id"] for row in rows_matching(reading, subject=ev0, predicate="destination")
    }
    completions = [
        proof
        for proof in reading.get("proofs", [])
        if proof.get("kind") == "role_completion"
        and destination_row_ids & set(proof.get("rows", []))
    ]
    assert completions, (
        "destination on the first event must carry a role_completion proof "
        "(event-link-policy.json:role_completion), not a bare value with no "
        "provenance"
    )

    spans = completions[0].get("spans", [])
    covers_ev0 = any(span_within([s, e], events[0]["span"]) for s, e in spans)
    covers_ev1 = any(span_within([s, e], events[1]["span"]) for s, e in spans)
    assert covers_ev0 and covers_ev1, (
        "CONTRACT C7 requires both the earlier event's span and the later "
        "evidence's span to be retained in the completion proof, neither "
        "replaced; proof spans were %r against ev0 %r / ev1 %r"
        % (spans, events[0]["span"], events[1]["span"])
    )


def test_partial_response_survives_an_unparseable_sentence(read_text, search_rows):
    text = "민수가 부품을 지은에게 전달했다. 외계인이 춤췄으."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    ev0 = ordered_events(reading)[0]["id"]
    for predicate, expected in (("actor", "민수"), ("object", "부품"), ("destination", "지은")):
        value = bound_values(query(search_rows, reading, [ev0, predicate, "?x"]))
        assert value == [expected], (predicate, value)

    assert reading["unresolved"], (
        "the malformed second sentence ('외계인이 춤췄으') must surface in 'unresolved' rather than "
        "silently vanish or abort the whole reading (C8)"
    )
    assert "limits" in reading, "every reading reports the caps in force (CONTRACT #7)"
