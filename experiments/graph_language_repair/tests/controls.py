# -*- coding: utf-8 -*-
"""Public controls for the reading core.

Every text here was written for this experiment to exercise one stated
mechanism or one counterexample.  None of them is a benchmark item, a frozen
case or a sentence taken from any saved evaluation; the names and the objects
are deliberately plain.  A control states what the mechanism must do and, where
it matters, what it must refuse to do.
"""

CONTROLS = {
    # -- roles and spans -------------------------------------------------
    "active_transfer": {
        "text": "김민수가 부품을 이수진에게 전달했다.",
        "exercises": "active transfer: actor, object, destination",
    },
    "passive_transfer": {
        "text": "부품이 이수진에게 전달되었다.",
        "exercises": "passive transfer: the subject marker carries the object",
    },
    "passive_with_agent": {
        "text": "부품이 김민수에 의해 이수진에게 전달되었다.",
        "exercises": "passive transfer: the agent marker carries the actor",
    },
    "passive_with_origin": {
        "text": "부품이 김민수에게서 이수진에게 전달되었다.",
        "exercises": "passive transfer with an origin; the longer source form wins",
    },
    "multiword_actor": {
        "text": "생산 라인 책임자가 부품을 확인했다.",
        "exercises": "a three-chunk actor span binds as one value",
    },
    "multiword_object": {
        "text": "검사관이 생산 라인 점검 기록을 확인했다.",
        "exercises": "a four-chunk checked object span binds as one value",
    },
    "possessive_value": {
        "text": "김민수가 회사의 부품을 이수진에게 전달했다.",
        "exercises": "a genitive marker stays inside the value span",
    },
    "coordinated_value": {
        "text": "김민수가 부품과 서류를 이수진에게 전달했다.",
        "exercises": "a conjunct marker stays inside the value span",
    },

    # -- events ----------------------------------------------------------
    "continuation_same_event": {
        "text": "김민수가 부품을 전달했다. 그 부품은 이수진에게 전달되었다.",
        "exercises": "an adjacent passive continuation of a unique prior transfer is one event",
    },
    "continuation_generic_reference": {
        "text": "김민수가 부품을 전달했다. 해당 항목은 이수진에게 전달되었다.",
        "exercises": "a generic pointing head continues the event without pinning identity",
    },
    "same_object_two_events": {
        "text": "김민수가 부품을 이수진에게 전달했다. 같은 부품이 박지훈에게 전달되었다.",
        "exercises": "counterexample: one item, two transfers, two events",
    },
    "same_object_two_events_generic": {
        "text": "김민수가 부품을 이수진에게 전달했다. 해당 항목은 박지훈에게 전달되었다.",
        "exercises": "counterexample: a pointing head does not override a conflicting destination",
    },
    "two_priors_stay_candidate": {
        "text": ("김민수가 부품을 이수진에게 전달했다. 박지훈이 부품을 이수진에게 전달했다. "
                 "그 부품은 이수진에게 전달되었다."),
        "exercises": "counterexample: with two prior transfers the continuation stays a candidate",
    },
    "named_event_reference": {
        "text": "김민수가 부품을 이수진에게 전달했다. 검사관이 그 전달을 확인했다.",
        "exercises": "a named event reference licenses verification of that event",
    },

    # -- attribution and verification ------------------------------------
    "report_prefix": {
        "text": "경찰에 따르면 부품이 이수진에게 전달되었다.",
        "exercises": "a prefix reporting frame scopes the clause to a reported claim",
    },
    "report_suffix": {
        "text": "경찰은 김민수가 부품을 이수진에게 전달했다고 밝혔다.",
        "exercises": "a suffix reporting frame; the reporter is consumed before the inner clause",
    },
    "attribution_speech_noun": {
        "text": "회사 발표에 따르면 부품이 이수진에게 전달되었다.",
        "exercises": "a speech noun in the reporter makes the scope an attribution",
    },
    "report_then_check": {
        "text": "경찰에 따르면 부품이 이수진에게 전달되었다. 검사관이 부품을 확인했다.",
        "exercises": "a later direct check does not turn the report into truth",
    },
    "reported_check_only": {
        "text": "김민수가 부품을 이수진에게 전달했다. 경찰은 검사관이 그 전달을 확인했다고 밝혔다.",
        "exercises": "counterexample: a reported check verifies nothing",
    },
    "inherited_attribution": {
        "text": "경찰에 따르면 부품이 전달되었다. 그 부품은 이수진에게 전달되었다.",
        "exercises": "an accepted link makes the continuation inherit the reported claim",
    },
    "negative_check": {
        "text": "김민수가 부품을 이수진에게 전달했다. 검사관이 그 전달을 확인하지 않았다.",
        "exercises": "negative checking is a finding with polarity false, not an absence",
    },
    "negative_transfer": {
        "text": "김민수가 부품을 이수진에게 전달하지 않았다.",
        "exercises": "a negated predicate keeps its roles and records polarity false",
    },
    "no_check_at_all": {
        "text": "김민수가 부품을 이수진에게 전달했다.",
        "exercises": "with no checking action there is no verification row at all",
    },
    "multiword_checker": {
        "text": "김민수가 부품을 이수진에게 전달했다. 생산 라인 책임자가 그 전달을 확인했다.",
        "exercises": "a multiword checker actor binds and the verification is accepted",
    },

    # -- mentions and identity -------------------------------------------
    "nested_entity": {
        "text": "생산 라인 책임자가 부품을 확인했다. 책임자가 서류를 전달했다.",
        "exercises": "counterexample: a shared title is not a shared identity",
    },
    "repeated_name": {
        "text": "김민수가 부품을 전달했다. 김민수가 서류를 전달했다.",
        "exercises": "an exact surface repeat is one entity across two events",
    },

    # -- ambiguity and partiality ----------------------------------------
    "source_or_place": {
        "text": "검사관이 창고에서 부품을 확인했다.",
        "exercises": "one marker, two classes, neither expected by the frame: two surviving readings",
    },
    "goal_or_instrument": {
        "text": "김민수가 부품을 창고로 전달했다.",
        "exercises": "one marker, two classes: the reading the frame expects dominates, the other is recorded",
    },
    "unknown_predicate": {
        "text": "김민수가 부품을 고쳤다. 검사관이 부품을 확인했다.",
        "exercises": "an undeclared predicate leaves that clause unresolved and the rest intact",
    },
    "predicate_without_arguments": {
        "text": "전달되었다.",
        "exercises": "a predicate with nothing to bind still produces an event",
    },
}


def text(name):
    return CONTROLS[name]["text"]
