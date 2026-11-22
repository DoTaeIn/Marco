# -*- coding: utf-8 -*-
"""Regression controls for AUDITOR.md "Review 8 — EXECUTED critical
question-constraint/polarity loss".

Generic invented public names (가람/나래/책/우산/다온/소이), none reused
verbatim from round 1 or round 2's documents, with changed word order on
several of the counterexamples as instructed.

 1. `event_role_question` anchors on exactly one grammatical function
    (`_choose_anchor`/`_value_hop_anchor` in `questions/select.py`, by
    priority) and never checks any other role the question also named. Two
    explicit role constraints that name two different real events must bind
    the SAME event or the question must hold -- not silently answer from
    whichever event the first-priority constraint alone happens to match.
 2. The plan has no action/predicate-identity hop at all for
    `event_role_question` -- a question naming an action the document never
    performed (a loan, when only a transfer exists) must not be answered
    from an unrelated existing action just because the role markers
    (subject/object/recipient) happen to match.
 3. A role-value hop's own provenance never touches the enclosing event's
    `[event, 'action', ...]`/`[event, 'polarity', ...]` row, so a negated
    event's role values come back with the same polarities and the same
    rendered text as the non-negated case. Role values are not, by
    themselves, evidence that the event occurred (CONTRACT.md's general
    polarity convention, extended by review 8 beyond verification
    questions).

Every regression below is paired with a positive counterpart using the same
document shape so a vacuously-empty or always-failing assertion would be
caught by its own sibling passing.

Frozen public development tests. Passing them is not independent benchmark
evidence. Run via `run_controls.py` in this directory, or under pytest
(see `CONTROLS-STATUS.md` for the exact command and current
pass/fail against the live tree, which is being actively repaired).
"""

from .conftest import ask, assert_exact_value_spans


def test_two_role_constraints_must_bind_the_same_event(
    read_text, search_rows, compile_question, execute_plan, render
):
    text = "가람이 책을 나래에게 전달했다. 다온이 우산을 소이에게 전달했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    # Regression: subject from the first event, object from the second.
    # No single event has both 가람 as actor and 우산 as object.
    _, mismatched, mismatched_render = ask(
        compile_question, execute_plan, render, reading, "가람이 우산을 누구에게 전달했나요?"
    )
    assert mismatched.get("value") not in ("나래", "소이"), (
        "AUDITOR.md review 8 item 1: 'event_role_question' anchors on only "
        "the first-priority slot present (subject here) and never checks "
        "that the object slot ('우산') also names a role of the SAME event. "
        "가람's event has object '책', not '우산'; 소이's event has subject "
        "'다온', not '가람'. No event satisfies both constraints, so this "
        "must not resolve to either event's destination. Got gate=%r "
        "value=%r render=%r"
        % (mismatched.get("gate"), mismatched.get("value"), mismatched_render)
    )

    # Positive counterpart 1: both constraints correctly name event 0.
    _, correct0, _ = ask(
        compile_question, execute_plan, render, reading, "가람이 책을 누구에게 전달했나요?"
    )
    assert correct0.get("value") == "나래", (
        "both constraints correctly name the first event; got %r" % (correct0,)
    )

    # Positive counterpart 2: both constraints correctly name event 1 --
    # proves the harness isn't just defaulting to "first event" generally.
    _, correct1, _ = ask(
        compile_question, execute_plan, render, reading, "다온이 우산을 누구에게 전달했나요?"
    )
    assert correct1.get("value") == "소이", (
        "both constraints correctly name the second event; got %r" % (correct1,)
    )


def test_loan_question_must_not_answer_from_a_transfer_event(
    read_text, search_rows, compile_question, execute_plan, render
):
    text = "가람이 책을 나래에게 전달했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    # Regression, original word order.
    _, loan_result, loan_render = ask(
        compile_question, execute_plan, render, reading, "가람이 책을 누구에게 대여했나요?"
    )
    assert loan_result.get("value") != "나래", (
        "AUDITOR.md review 8 item 2: the document contains a transfer, not "
        "a loan ('대여'). 'event_role_question' has no action/predicate "
        "hop at all, so the question's verb is never checked against the "
        "document's actual action -- the recipient-marker cue alone pulls "
        "the transfer's destination. Got gate=%r value=%r render=%r"
        % (loan_result.get("gate"), loan_result.get("value"), loan_render)
    )

    # Regression, changed word order (object fronted).
    _, loan_result_reordered, loan_render_reordered = ask(
        compile_question, execute_plan, render, reading, "책을 가람이 누구에게 대여했나요?"
    )
    assert loan_result_reordered.get("value") != "나래", (
        "same defect with the object fronted ahead of the subject; got "
        "gate=%r value=%r render=%r"
        % (
            loan_result_reordered.get("gate"),
            loan_result_reordered.get("value"),
            loan_render_reordered,
        )
    )

    # Positive counterpart: the same document, asked about the action it
    # actually contains, legitimately answers.
    _, transfer_result, _ = ask(
        compile_question, execute_plan, render, reading, "가람이 책을 누구에게 전달했나요?"
    )
    assert transfer_result.get("value") == "나래", (
        "the real transfer question must still answer correctly -- this "
        "control is about an unrecognised action, not about breaking the "
        "recipient-marker hop generally; got %r" % (transfer_result,)
    )


def test_negated_event_role_answer_is_not_rendered_as_plain_positive(
    read_text, search_rows, compile_question, execute_plan, render
):
    negated_text = "가람이 책을 나래에게 전달하지 않았다."
    positive_text = "가람이 책을 나래에게 전달했다."
    negated_reading = read_text(negated_text)
    positive_reading = read_text(positive_text)
    assert_exact_value_spans(negated_reading)
    assert_exact_value_spans(positive_reading)

    _, negated_result, negated_render = ask(
        compile_question, execute_plan, render, negated_reading, "가람이 무엇을 전달했나요?"
    )
    _, positive_result, positive_render = ask(
        compile_question, execute_plan, render, positive_reading, "가람이 무엇을 전달했나요?"
    )

    # Positive counterpart / sanity: the non-negated document legitimately
    # answers a plain positive value with polarity-true provenance, so the
    # harness itself is not simply broken or inert.
    assert positive_result.get("value") == "책"
    assert positive_result["candidates"][0]["polarities"] == {True}

    # Previously the positive question returned event_negated and exposed its
    # negative candidate. It now holds because the requested polarity differs.
    assert negated_result["gate"] == "conflicting_constraints"
    _, requested_result, requested_render = ask(
        compile_question, execute_plan, render, negated_reading,
        "가람이 전달하지 않은 물건은 무엇이었나요?",
    )
    assert requested_result["value"] == "책"
    assert requested_result["candidates"][0]["polarities"] == {False}
    assert "하지 않았다는" in requested_render
    assert requested_render != positive_render
