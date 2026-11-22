# -*- coding: utf-8 -*-
"""Regression controls for CORE-SECOND-AUDIT.md A3/A7 and AUDITOR.md review 6
("dropped query constraints"), plus the positive-result overclaim A3 also
names at the output layer.

 * A3 (output half) / coordinator qualification: a bare, positive checking
   construction ('확인했다') states only that the checking action occurred.
   It names no separate result. The rendered answer must not append an
   unsupported positive-result claim.
 * A7: an interrogative pronoun ('누가') must not be consumed into, or merged
   into, an ordinary argument slot's value -- the question layer needs to
   recognise it as the asked-for function, not a value to search for.
 * Review 6: "A question with two subjects/objects, a source frame, a
   preceding topic or a relative clause can therefore silently lose a
   constraint." Two public counterexamples: a report clause prefixed onto
   the question itself, and a relative clause naming the sought role.
 * Also included: a positive control for AUDITOR.md's coordinator
   qualification to A4 -- an explicitly independent, *direct* checking
   clause may legitimately target an event whose own content is only
   reported. This directory must not grow a test that blanket-forbids that;
   this control exists so nobody adds one by accident while fixing A3/A4.

Frozen public development tests. Passing them is not independent benchmark
evidence. Run via `run_controls.py` in this directory, or under pytest if
available (see `CONTROLS-STATUS.md` for current pass/fail).
"""

from .conftest import ask, assert_exact_value_spans, ordered_events, rows_matching


def test_a3_bare_check_occurrence_does_not_render_an_unsupported_result(
    read_text, search_rows, compile_question, execute_plan, render
):
    text = "검사팀은 창고 상태를 확인했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    _, result, rendered = ask(
        compile_question, execute_plan, render, reading, "검사팀이 창고 상태를 확인했나요?"
    )
    assert "맞음" not in rendered and result.get("value") == "unstated", (
        "CORE-SECOND-AUDIT A3 / AUDITOR.md coordinator qualification: "
        "'확인했다' states only that the checking action occurred; the source "
        "text names no separate result. The rendered answer must not append "
        "an unsupported positive-result claim; an explicit note that the "
        "result is unstated is correct. "
        "Got gate=%r value=%r render=%r"
        % (result.get("gate"), result.get("value"), rendered)
    )


def test_a7_who_word_is_not_merged_into_an_argument_value(
    read_text, search_rows, compile_question, execute_plan, render
):
    text = "박검사관이 부품을 확인했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    plan, result, rendered = ask(
        compile_question, execute_plan, render, reading, "누가 부품을 확인했나요?"
    )
    for function, slots in plan.get("slots", {}).items():
        for slot in slots:
            assert "누가" not in slot.get("text", "") and slot.get("text") != "누", (
                "CORE-SECOND-AUDIT A7: the interrogative '누가' must not be "
                "consumed into, or merged into, the %r slot's value span "
                "('vs the document's own named checker). Got slot %r"
                % (function, slot)
            )

    assert result.get("value") == "박검사관", (
        "the document names an explicit checker ('박검사관'); 'who checked "
        "the part' should answer it, not hold on a missing-argument gate. "
        "Got gate=%r value=%r render=%r"
        % (result.get("gate"), result.get("value"), rendered)
    )


def test_review6_report_clause_in_the_question_does_not_corrupt_the_subject(
    read_text, search_rows, compile_question, execute_plan, render
):
    text = "보고서에 따르면 김과장이 부품을 전달했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    plan, result, rendered = ask(
        compile_question, execute_plan, render, reading, "보고서에 따르면 김과장이 무엇을 전달했나요?"
    )
    subject_slots = plan.get("slots", {}).get("subject") or []
    subject_text = subject_slots[0]["text"] if subject_slots else None
    assert subject_text == "김과장", (
        "AUDITOR.md review 6: a report clause preceding the real subject "
        "('보고서에 따르면') is part of the question's own framing, not the "
        "constraint being asked about, and must not be absorbed into the "
        "subject span. Got subject slot text %r (full slots %r)"
        % (subject_text, plan.get("slots"))
    )

    plain_plan, plain_result, _ = ask(
        compile_question, execute_plan, render, reading, "김과장이 무엇을 전달했나요?"
    )
    assert result.get("value") == plain_result.get("value") == "부품", (
        "the same document, asked the same question with and without a "
        "report-clause prefix on the question itself, must target the same "
        "event and answer the same value. Got with-prefix=%r plain=%r "
        "render=%r" % (result.get("value"), plain_result.get("value"), rendered)
    )


def test_review6_relative_clause_naming_the_sought_role_is_not_a_literal_topic(
    read_text, search_rows, compile_question, execute_plan, render
):
    text = "박검사관이 창고에서 부품을 확인했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    plan, result, rendered = ask(
        compile_question,
        execute_plan,
        render,
        reading,
        "부품을 창고에서 확인한 사람은 누구인가요?",
    )
    topic_slots = plan.get("slots", {}).get("topic") or []
    topic_text = topic_slots[0]["text"] if topic_slots else None
    assert topic_text != "확인한 사람", (
        "AUDITOR.md review 6: a relative clause naming the sought role "
        "('확인한 사람' = 'the person who checked') names the WH target "
        "(checking_actor), not a value to search the graph for, and must "
        "not be bound as a literal topic constraint. Got topic slot text "
        "%r (full slots %r)" % (topic_text, plan.get("slots"))
    )


def test_independent_direct_check_may_target_a_previously_reported_event(read_text, search_rows):
    text = "보고서에 따르면 김과장이 부품을 박대리에게 전달했다. 박검사관이 그 전달을 확인했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    events = ordered_events(reading)
    assert len(events) >= 2
    transfer, check = events[0]["id"], events[1]["id"]

    link = (
        rows_matching(reading, subject=check, predicate="checks", obj=transfer)
        + rows_matching(reading, subject=transfer, predicate="verified_by", obj=check)
    )
    assert link, (
        "AUDITOR.md coordinator qualification to A4: an explicitly "
        "independent, direct checking clause ('그 전달을 확인했다', no report "
        "frame of its own) may legitimately target an event whose own "
        "content is only reported ('보고서에 따르면 ...'). This must not be "
        "blanket-blocked just because the TARGET's claim is attribution -- "
        "only the CHECK's own scope is tested against "
        "forbidden_source_scopes (CONTRACT C5). Got no checks/verified_by "
        "link at all for this positive case; a fix for A3/A4 must not "
        "regress this."
    )
