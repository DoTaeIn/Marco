# -*- coding: utf-8 -*-
"""Mention against identity.

Repair under test: coreference keyed on alias strings, where three subject
spans ending at the same marker survived the overlap filter and every
distinct-entity question came back unsupported (CORE-STATUS F6).
"""
from experiments.graph_language_repair.core import read_text
from experiments.graph_language_repair.tests.helpers import (entity_of, mention_at, reading,
                                                             rows)

ALIAS_GRAPH = [{"key": "alias:control", "kind": "alias", "surfaces": ["김민수", "김 검사관"]}]


def test_every_surface_occurrence_is_its_own_mention():
    document = reading("repeated_name")
    found = [item for item in document["mentions"] if item["surface"] == "김민수"]
    assert len(found) == 2
    assert found[0]["span"] != found[1]["span"]
    assert found[0]["id"] != found[1]["id"]


def test_a_mention_id_is_its_character_span():
    document = reading("active_transfer")
    for item in document["mentions"]:
        assert item["id"] == "mention:%d-%d" % tuple(item["span"])


def test_a_nested_span_is_its_own_mention_with_containment():
    document = reading("multiword_actor")
    outer = mention_at(document, "생산 라인 책임자")
    inner = mention_at(document, "책임자")
    assert inner["id"] in outer["contains"]
    assert outer["id"] in inner["contained_by"]


def test_a_prefix_modifier_nesting_is_never_merged():
    """C2: 생산 라인 책임자 and 생산 라인 are two things."""
    document = reading("multiword_actor")
    outer = mention_at(document, "생산 라인 책임자")
    part = mention_at(document, "생산 라인")
    assert entity_of(document, outer["id"]) != entity_of(document, part["id"])


def test_a_shared_title_across_sentences_is_not_a_shared_identity():
    document = reading("nested_entity")
    long_side = mention_at(document, "생산 라인 책임자")
    short_side = mention_at(document, "책임자", occurrence=1)
    assert entity_of(document, long_side["id"]) != entity_of(document, short_side["id"])
    recorded = [item for item in document["entity_ambiguity"]
                if sorted(item["mentions"]) == sorted([long_side["id"], short_side["id"]])]
    assert recorded, "the candidate identity is recorded, not merged"
    assert "head_suffix_match" in recorded[0]["evidence"]


def test_a_determiner_head_is_the_same_thing_as_its_head():
    document = reading("continuation_same_event")
    pointing = mention_at(document, "그 부품")
    head = [item for item in document["mentions"]
            if item["surface"] == "부품" and item["span"][0] > pointing["span"][0]][0]
    assert entity_of(document, pointing["id"]) == entity_of(document, head["id"])


def test_a_demonstrative_repeat_joins_the_earlier_mention():
    document = reading("continuation_same_event")
    first = mention_at(document, "부품")
    pointing = mention_at(document, "그 부품")
    assert entity_of(document, first["id"]) == entity_of(document, pointing["id"])


def test_an_alias_merges_only_when_it_is_declared():
    text = "김민수가 부품을 전달했다. 김 검사관이 부품을 확인했다."
    without = read_text(text)
    with_alias = read_text(text, extra_graphs=[ALIAS_GRAPH])
    left = mention_at(without, "김민수")
    right = mention_at(without, "김 검사관")
    assert entity_of(without, left["id"]) != entity_of(without, right["id"])
    left = mention_at(with_alias, "김민수")
    right = mention_at(with_alias, "김 검사관")
    assert entity_of(with_alias, left["id"]) == entity_of(with_alias, right["id"])


def test_no_alias_is_inferred_from_a_shared_key():
    """The core ships no alias of its own."""
    from experiments.graph_language_repair.core import load_graphs
    assert load_graphs().alias_pairs() == set()


def test_identity_rows_are_reachable_for_a_reference_question():
    document = reading("continuation_same_event")
    pointing = mention_at(document, "그 부품")
    entity = entity_of(document, pointing["id"])
    assert rows(document, pointing["id"], "mention_of", entity)
    assert rows(document, entity, "name", "부품")
    assert rows(document, pointing["id"], "surface", "그 부품")


def test_a_mention_with_no_evidence_is_its_own_entity():
    document = reading("active_transfer")
    actor = mention_at(document, "김민수")
    entity = [item for item in document["entities"]
              if actor["id"] in item["mentions"]][0]
    assert entity["mentions"] == [actor["id"]]
    assert entity["evidence"] == []


def test_each_accepted_entity_records_the_evidence_that_joined_it():
    document = reading("continuation_same_event")
    joined = [item for item in document["entities"] if len(item["mentions"]) > 1]
    assert joined
    for entity in joined:
        assert entity["evidence"]
        for item in entity["evidence"]:
            assert item["policy"].startswith("identity-policy:")
            assert len(item["spans"]) == 2
