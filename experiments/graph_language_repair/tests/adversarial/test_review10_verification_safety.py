# -*- coding: utf-8 -*-
"""Regression controls for AUDITOR.md "Review 10 — EXECUTED post-repair
verification safety (core owner)".

Core now splits a checking clause into three declared channels (confirmed
against the live `reading`, not assumed from CONTRACT.md's row table, which
does not yet list two of them -- `checking_occurred` and `independent_result`
are both real rows on the live tree as of this round, documented in
`core/events.py::EventLinker.verifications`'s own docstring and
`verification-policy.json`'s `channel_note`; `checking_outcome` is unchanged
from CONTRACT.md):

 * `[event, 'checking_occurred', 'occurred'|'not_performed']` -- did the
   checking action happen at all;
 * `[event, 'checking_outcome', 'confirmed'|'denied'|'unstated']` -- what the
   checking clause itself states as a result, from a declared result form;
 * `[target, 'independent_result', 'confirmed'|'denied'|'unstated']` -- what
   that result establishes about a *specific* target event.

Three things wrong with how those channels are filled, all confirmed live:

 1. `core/reading.py::_checking_channels` detects a result form with a plain
    `if form in surface` substring test over the whole checking clause, not
    structural attachment -- an invented object or actor name that merely
    *contains* a declared result form invents a finding, and when a
    positive-class form and a negative-class form are both present (e.g. one
    from the actor's name, one from the object's), `sorted(...).items()`
    always checks `result_negative` before `result_positive` (alphabetical:
    'n' < 'p'), so a negative reading silently wins by iteration order, not
    by any textual or structural precedence.
 2. `core/events.py::EventLinker.verifications` evaluates every (target,
    check) pair independently with no cross-target uniqueness check, so an
    event-reference cue that is genuinely ambiguous between two prior events
    accepts `verified_by` for *both*, simultaneously, with `blocked_by: []`
    on each.
 3. `verification-policy.json`'s `result_requires_target_scope` lists only
    `["direct_text", "checking_action"]`, excluding `attribution` -- so a
    direct, explicit, genuinely result-bearing check on a target that was
    merely *introduced* via a report has its `independent_result` forced to
    `unstated` purely by the target's scope, even though the check's own
    source, occurrence and result are all independently evidenced and fine.
    AUDITOR.md's coordinator qualification to A4 already settled that a
    report-introduced target may legitimately be independently verified;
    this is the same category of over-correction applied to the result
    channel instead of the link itself.

Every regression here is paired with a positive counterpart that must keep
passing, using fresh invented names distinct from AUDITOR.md's own examples
where the point is "this isn't about one blacklisted word".

Frozen public development tests. Passing them is not independent benchmark
evidence. Run via `run_controls.py` in this directory, or under pytest (see
`CONTROLS-STATUS.md` for the exact command and current pass/fail).
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


# -- item 3: result form must be structurally attached, not substring-matched

def test_result_form_inside_an_invented_object_name_is_not_a_result(read_text, search_rows):
    text = "하람이 사실로텍을 확인했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    ev0 = ordered_events(reading)[0]["id"]
    outcome = bound_values(query(search_rows, reading, [ev0, "checking_outcome", "?x"]))
    assert outcome != ["confirmed"], (
        "AUDITOR.md review 10 item 3: '사실로텍' is only the checked "
        "object's invented name; it happens to start with the declared "
        "result form '사실로' (noun:result_positive), but the clause "
        "states no result at all. _checking_channels's `if form in "
        "surface` substring test over the whole clause invents a positive "
        "finding from the object's name. Got checking_outcome=%r" % (outcome,)
    )


def test_result_form_inside_an_invented_actor_name_is_not_a_result(read_text, search_rows):
    text = "허위로은행이 문서를 확인했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    ev0 = ordered_events(reading)[0]["id"]
    outcome = bound_values(query(search_rows, reading, [ev0, "checking_outcome", "?x"]))
    assert outcome != ["denied"], (
        "same defect, actor side, a fresh invented name distinct from "
        "AUDITOR.md's own object-side example: '허위로은행' is only the "
        "checker's name and happens to start with the declared negative "
        "result form '허위로' (noun:result_negative); the clause states no "
        "result. Got checking_outcome=%r" % (outcome,)
    )


def test_structurally_separate_result_form_may_be_a_positive_result(read_text, search_rows):
    """Positive counterpart: this is the shape AUDITOR.md explicitly says
    MAY legitimately become a positive result -- kept here so a fix for the
    two tests above cannot regress the genuine case into always abstaining."""
    text = "서진이 그 전달을 사실로 확인했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    ev0 = ordered_events(reading)[0]["id"]
    outcome = bound_values(query(search_rows, reading, [ev0, "checking_outcome", "?x"]))
    assert outcome == ["confirmed"], (
        "'그 전달을 사실로 확인했다': the result form '사실로' is its own "
        "token, syntactically separate from the checked object ('그 "
        "전달'), genuinely stating a result -- this positive case must "
        "keep working. Got %r" % (outcome,)
    )


def test_competing_result_forms_are_not_silently_resolved_alphabetically(read_text, search_rows):
    text = "사실로텍이 허위로청을 확인했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    ev0 = ordered_events(reading)[0]["id"]
    outcome = bound_values(query(search_rows, reading, [ev0, "checking_outcome", "?x"]))
    assert outcome != ["denied"], (
        "AUDITOR.md review 10 item 3: this clause's surface contains BOTH "
        "a 'result_positive' form ('사실로', from the actor's invented "
        "name) and a 'result_negative' form ('허위로', from the object's "
        "invented name). _checking_channels iterates "
        "`sorted(result_from_form_class.items())`, and the string "
        "'result_negative' sorts before 'result_positive', so the negative "
        "class is always checked first and wins by iteration order alone "
        "-- not by textual order, not by structural attachment, not by any "
        "declared priority. Neither name states a real result; a confident "
        "'denied' reached this way must not be asserted silently. Got "
        "checking_outcome=%r" % (outcome,)
    )


# -- item 1: an ambiguous target reference must not verify every candidate

def test_ambiguous_target_must_not_verify_both_prior_events(read_text, search_rows):
    text = "서진이 부품을 다온에게 전달했다. 라온이 서류를 다온에게 전달했다. 감사팀이 그 전달을 확인했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    events = ordered_events(reading)
    assert len(events) >= 3, "expected two independent prior transfers plus one check"
    transfer0, transfer1, check = events[0]["id"], events[1]["id"], events[2]["id"]

    link0 = rows_matching(reading, subject=transfer0, predicate="verified_by", obj=check)
    link1 = rows_matching(reading, subject=transfer1, predicate="verified_by", obj=check)
    assert not (link0 and link1), (
        "AUDITOR.md review 10 item 1: '그 전달' has two equally plausible "
        "prior transfer events (서진's and 라온's, both 다온-destined); "
        "positive event-reference evidence is necessary but does not "
        "uniquely identify which one is meant. "
        "core/events.py::EventLinker.verifications evaluates each "
        "(target, check) pair independently with no cross-target "
        "uniqueness check, so both accept with blocked_by=[]. verified_by "
        "must not be asserted for both simultaneously -- an unresolved "
        "reference should stay a candidate/competing target binding, not "
        "two positive verifications. Got verified_by(%s)=%r "
        "verified_by(%s)=%r" % (transfer0, bool(link0), transfer1, bool(link1))
    )


def test_unique_prior_transfer_is_verified_normally(read_text, search_rows):
    """Positive counterpart: with exactly one candidate, '그 전달' is
    genuinely unambiguous and must still verify normally."""
    text = "서진이 부품을 다온에게 전달했다. 감사팀이 그 전달을 확인했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    events = ordered_events(reading)
    transfer, check = events[0]["id"], events[1]["id"]
    link = rows_matching(reading, subject=transfer, predicate="verified_by", obj=check)
    assert link, (
        "a single, unambiguous prior transfer must still be verified; got "
        "no verified_by link at all for %r" % (text,)
    )


# -- item 2: a report-introduced target may still get an independent result

def test_direct_check_on_a_reported_target_may_have_an_independent_result(read_text, search_rows):
    text = "보고서에 따르면 서진이 부품을 다온에게 전달했다. 감사팀이 그 전달을 사실로 확인했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    events = ordered_events(reading)
    assert len(events) >= 2
    transfer, check = events[0]["id"], events[1]["id"]

    # The original report claim must be preserved, not overwritten.
    transfer_claim = event_claim(reading, transfer)
    assert claim_scope_kind(reading, transfer_claim) == "attribution", (
        "the transfer's own claim must stay attributed to the report "
        "('보고서에 따르면'), not get silently upgraded or discarded; got %r"
        % (claim_scope_kind(reading, transfer_claim),)
    )

    # The direct checking proof itself must be intact: this control is
    # about independent_result specifically, not about whether the check
    # or the link is (correctly) allowed to exist at all.
    occurrence = bound_values(query(search_rows, reading, [check, "checking_occurred", "?x"]))
    own_result = bound_values(query(search_rows, reading, [check, "checking_outcome", "?x"]))
    link = rows_matching(reading, subject=transfer, predicate="verified_by", obj=check)
    assert occurrence == ["occurred"] and own_result == ["confirmed"] and link, (
        "the checking clause itself is direct and explicit ('그 전달을 "
        "사실로 확인했다') and genuinely states a result -- its own "
        "occurrence, its own result and the verified_by link must all "
        "stand unchanged. Got occurrence=%r own_result=%r link=%r"
        % (occurrence, own_result, bool(link))
    )

    independent = bound_values(query(search_rows, reading, [transfer, "independent_result", "?x"]))
    assert independent == ["confirmed"], (
        "AUDITOR.md review 10 item 2: verification-policy.json's "
        "result_requires_target_scope=['direct_text','checking_action'] "
        "excludes 'attribution', so independent_result is forced to "
        "'unstated' (blocked_by "
        "'independent_result_withheld_target_scope:attribution') purely "
        "because the TARGET was first introduced in a report -- contrary "
        "to the coordinator's A4 qualification, extended here from the "
        "link itself to the result channel: independence concerns the "
        "source of the check/result and the exactness of the target "
        "binding (both fine here -- direct check, unambiguous explicit "
        "reference), not whether the target happened to be reported "
        "first. Got independent_result=%r" % (independent,)
    )


def test_direct_target_with_explicit_result_is_the_positive_baseline(read_text, search_rows):
    """Positive baseline, no report involved at all: the same direct,
    explicit, result-bearing check on a plain direct-text target must read
    independent_result='confirmed'. If this one ever fails too, the defect
    is broader than target-scope handling specifically."""
    text = "서진이 부품을 다온에게 전달했다. 감사팀이 그 전달을 사실로 확인했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    transfer = ordered_events(reading)[0]["id"]
    independent = bound_values(query(search_rows, reading, [transfer, "independent_result", "?x"]))
    assert independent == ["confirmed"], (
        "positive baseline (no report): got independent_result=%r"
        % (independent,)
    )
