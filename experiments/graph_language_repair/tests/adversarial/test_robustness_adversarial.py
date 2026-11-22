# -*- coding: utf-8 -*-
"""Robustness control: an irrelevant, unparseable second sentence must not
change a correct answer already established by the first sentence (CONTRACT
C8: a correct partial answer must not require a complete global parse).

Frozen public development test. Passing it is not independent benchmark
evidence.
"""

from .conftest import assert_exact_value_spans, bound_values, ordered_events, query


def test_irrelevant_unresolved_second_sentence_does_not_change_first_sentence_answer(read_text, search_rows):
    base = "민수가 부품을 지은에게 전달했다."
    noisy = base + " 오늘 날씨가 맑았스."

    reading_base = read_text(base)
    reading_noisy = read_text(noisy)
    assert_exact_value_spans(reading_base)
    assert_exact_value_spans(reading_noisy)

    ev0_base = ordered_events(reading_base)[0]["id"]
    ev0_noisy = ordered_events(reading_noisy)[0]["id"]

    for predicate, expected in (("actor", "민수"), ("object", "부품"), ("destination", "지은")):
        base_value = bound_values(query(search_rows, reading_base, [ev0_base, predicate, "?x"]))
        noisy_value = bound_values(query(search_rows, reading_noisy, [ev0_noisy, predicate, "?x"]))
        assert base_value == [expected], (predicate, base_value)
        assert noisy_value == [expected], (
            "appending an unrelated, unparseable sentence changed the "
            "first sentence's %r answer: %r -> %r" % (predicate, base_value, noisy_value)
        )

    assert reading_noisy["unresolved"], (
        "the malformed tail ('오늘 날씨가 맑았스') must surface in 'unresolved', not be silently "
        "absorbed, dropped, or made to abort the whole reading (C8)"
    )
