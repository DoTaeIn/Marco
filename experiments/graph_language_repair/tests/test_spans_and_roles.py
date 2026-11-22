# -*- coding: utf-8 -*-
"""Character coordinates, voice, and multiword values.

Repairs under test: the fixed role shape that expected a named role followed by
a nominal value and a copular ending, and the single-token actor requirement
that stopped checker binding (CORE-STATUS F2, F7).
"""
from experiments.graph_language_repair.core import read_text
from experiments.graph_language_repair.tests.controls import CONTROLS
from experiments.graph_language_repair.tests.helpers import (events, reading, role_values,
                                                             roles)


def test_every_value_span_is_exact_in_every_control():
    """C3 across the whole control set."""
    for name in CONTROLS:
        document = reading(name)
        for item in document["roles"]:
            start, end = item["value_span"]
            assert document["text"][start:end] == item["value"], (name, item)


def test_every_row_span_is_inside_the_text():
    for name in CONTROLS:
        document = reading(name)
        length = len(document["text"])
        for row in document["rows"]:
            assert row["spans"]
            for start, end in row["spans"]:
                assert 0 <= start < end <= length, (name, row)


def test_active_transfer_roles():
    document = reading("active_transfer")
    assert role_values(document, "event:0", "actor") == ["김민수"]
    assert role_values(document, "event:0", "object") == ["부품"]
    assert role_values(document, "event:0", "destination") == ["이수진"]
    assert events(document)[0]["voice"] == "active"


def test_passive_subject_is_the_object_not_the_actor():
    document = reading("passive_transfer")
    assert role_values(document, "event:0", "object") == ["부품"]
    assert role_values(document, "event:0", "actor") == []
    assert "actor" in events(document)[0]["missing_roles"]
    assert events(document)[0]["voice"] == "passive"


def test_a_passive_agent_marker_carries_the_actor():
    document = reading("passive_with_agent")
    assert role_values(document, "event:0", "actor") == ["김민수"]
    assert role_values(document, "event:0", "object") == ["부품"]
    assert role_values(document, "event:0", "destination") == ["이수진"]


def test_a_longer_case_form_is_not_shadowed_by_the_shorter_one_inside_it():
    document = reading("passive_with_origin")
    assert role_values(document, "event:0", "origin") == ["김민수"]
    assert role_values(document, "event:0", "destination") == ["이수진"]


def test_both_voices_use_one_frame_and_the_same_role_names():
    active = reading("active_transfer")
    passive = reading("passive_with_agent")
    assert events(active)[0]["frame"] == events(passive)[0]["frame"]
    assert events(active)[0]["construction"] != events(passive)[0]["construction"]
    assert role_values(active, "event:0", "object") == role_values(passive, "event:0", "object")


def test_a_multiword_actor_binds_as_one_span():
    document = reading("multiword_actor")
    found = roles(document, "event:0", "checking_actor")
    assert len(found) == 1
    assert found[0]["value"] == "생산 라인 책임자"
    assert found[0]["value"].count(" ") == 2


def test_a_multiword_checked_object_binds_as_one_span():
    document = reading("multiword_object")
    found = roles(document, "event:0", "checking_object")
    assert [item["value"] for item in found] == ["생산 라인 점검 기록"]


def test_an_internal_marker_stays_inside_the_value():
    assert role_values(reading("possessive_value"), "event:0", "object") == ["회사의 부품"]
    assert role_values(reading("coordinated_value"), "event:0", "object") == ["부품과 서류"]


def test_segments_are_split_and_every_event_names_its_segment():
    document = reading("continuation_same_event")
    assert len(document["segments"]) == 2
    assert {event["segment"] for event in document["events"]} == {"seg:0", "seg:1"}


def test_a_negated_predicate_keeps_its_roles_and_records_polarity():
    document = reading("negative_transfer")
    assert role_values(document, "event:0", "actor") == ["김민수"]
    assert events(document)[0]["polarity"] is False
    action = [row for row in document["rows"] if row["triple"][1] == "action"]
    assert action and action[0]["polarity"] is False
    polarity = [row for row in document["rows"] if row["triple"][1] == "polarity"]
    assert polarity and polarity[0]["triple"][2] == "false"


def test_no_role_is_read_from_a_whitespace_count():
    """The same roles must survive extra spacing, which a token index would not."""
    spaced = read_text("김민수가   부품을    이수진에게   전달했다.")
    assert role_values(spaced, "event:0", "actor") == ["김민수"]
    assert role_values(spaced, "event:0", "object") == ["부품"]
    assert role_values(spaced, "event:0", "destination") == ["이수진"]
