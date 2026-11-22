# -*- coding: utf-8 -*-
"""Entity identity adversarial controls (CONTRACT C2, identity-policy.json).

A nested mention is not the same entity as the mention that contains it,
sharing a bare title suffix does not merge two differently named people, and
a repeated exact name does identify one person.

Frozen public development tests. Passing them is not independent benchmark
evidence.
"""

from .conftest import (
    assert_exact_value_spans,
    bound_values,
    identity_key,
    ordered_events,
    query,
)


def test_compound_actor_with_nested_person_phrase(read_text, search_rows):
    text = "생산 라인 책임자 김민수가 부품을 전달했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    ev0 = ordered_events(reading)[0]["id"]
    actor = bound_values(query(search_rows, reading, [ev0, "actor", "?x"]))
    assert actor == ["생산 라인 책임자 김민수"], (
        "the actor value span must be the full multiword phrase up to the "
        "subject marker, not a truncated token or only the title or only "
        "the name; got %r" % (actor,)
    )

    outer = next(
        m for m in reading["mentions"] if m["surface"] == "생산 라인 책임자 김민수"
    )
    nested = [m for m in reading["mentions"] if m["id"] in outer.get("contains", [])]
    assert nested, (
        "the name inside the title phrase must surface as its own mention "
        "node with its own span (CONTRACT C2), not be absorbed invisibly "
        "into the outer span"
    )
    for inner in nested:
        assert identity_key(reading, outer) != identity_key(reading, inner), (
            "identity-policy:nested_containment is declared 'never': a "
            "mention and a mention inside it ('%s' containing '%s') must "
            "not be merged into one entity by containment alone"
            % (outer["surface"], inner["surface"])
        )


def test_shared_title_suffix_is_not_same_person(read_text, search_rows):
    text = (
        "생산 라인 책임자 김민수가 부품을 전달했다. "
        "포장 라인 책임자 이지은이 자료를 확인했다."
    )
    reading = read_text(text)
    assert_exact_value_spans(reading)

    m_kim = next(
        m for m in reading["mentions"]
        if "김민수" in m["surface"] and "책임자" in m["surface"]
    )
    m_lee = next(
        m for m in reading["mentions"]
        if "이지은" in m["surface"] and "책임자" in m["surface"]
    )
    assert identity_key(reading, m_kim) != identity_key(reading, m_lee), (
        "identity-policy:head_suffix_match is declared insufficient_alone "
        "and no declared_alias exists in this text: sharing the bare title "
        "'책임자' must not merge two differently named people"
    )


def test_repeated_exact_name_is_one_person(read_text, search_rows):
    text = "김민수가 부품을 전달했다. 김민수가 자료를 확인했다."
    reading = read_text(text)
    assert_exact_value_spans(reading)

    kims = [m for m in reading["mentions"] if m["surface"] == "김민수"]
    assert len(kims) >= 2, (
        "expected two distinct mention nodes for the repeated name (a "
        "mention is one per surface occurrence, CONTRACT #3), got %r"
        % (kims,)
    )
    keys = {identity_key(reading, m) for m in kims}
    assert len(keys) == 1, (
        "identity-policy:exact_surface_repeat is declared sufficient: two "
        "assertions naming the exact same surface must resolve to one "
        "entity so that 'who transferred the part and who checked the "
        "material' can be answered as one person; got distinct keys %r"
        % (keys,)
    )
