"""L1.1: the declared envelope, kinds and statuses, and a validator that names the offending field."""
import copy
from pathlib import Path
import re

import pytest

from marco.trace import schema

NOTE = Path(__file__).resolve().parents[2] / "docs/ko/2026-09-24-trace-logging-design.md"


def _event(**changes):
    event = {"schema": schema.SCHEMA, "event_id": "evt_01", "trace_id": "trace_01", "parent_ids": [],
             "timestamp": 1.5, "system": "MARCO", "subsystem": "reasoning", "kind": "rule_applied",
             "status": "success", "epistemic_status": "inferred", "subject": None, "input_refs": [],
             "output_refs": [], "source": {}, "operation": {}, "payload": {"operator": "relational_graph"},
             "runtime": {"build": "abc", "pack": "styles/english.json"}}
    event.update(changes)
    return event


def _section(number):
    text = NOTE.read_text(encoding="utf-8")
    start = text.index("## %d." % number)
    end = text.index("\n## ", start + 1)
    return text[start:end]


def test_the_minimal_envelope_of_section_38_is_declared():
    block = _section(38).split("```")[1]
    declared = set(re.findall(r'"([a-z_]+)":', block))
    assert "build" in declared and "build" in schema.RUNTIME      # runtime.build, a key inside runtime
    declared.discard("build")
    assert declared <= set(schema.FIELD_NAMES)
    # system and subsystem exist and are optional; scope and goal_id make room for post-gate work
    optional = {f.name for f in schema.FIELDS if not f.required}
    assert {"system", "subsystem", "scope", "goal_id"} <= optional
    assert set(schema.REQUIRED) == declared - {"system", "subsystem"}


def test_every_event_kind_of_section_39_is_declared_and_the_emitted_subset_is_marked():
    block = _section(39).split("```")[1]
    kinds = set(block.split())
    assert kinds == set(schema.KINDS)
    assert set(schema.EMITTED) == {
        "input_received", "observation_created", "routing_selected", "rule_applied", "evidence_found",
        "state_changed", "conclusion_created", "conclusion_withdrawn", "hypothesis_verified",
        "hypothesis_rejected", "contradiction_found", "hold", "output_created", "error"}
    for kind in schema.KINDS.values():
        assert kind.statuses and set(kind.statuses) <= set(schema.STATUSES)
        assert kind.tag and kind.category


def test_the_epistemic_statuses_of_section_16_are_declared():
    block = _section(16).split("```")[1]
    assert set(block.split()) == set(schema.EPISTEMIC)


def test_a_valid_event_passes():
    assert schema.problems(_event()) == []
    assert schema.validate(_event())["kind"] == "rule_applied"


@pytest.mark.parametrize("change, field", [
    ({"kind": "rule_invented"}, "kind"),
    ({"status": "fine"}, "status"),
    ({"status": "answered"}, "status"),                  # a real status, not one rule_applied has
    ({"epistemic_status": "certain"}, "epistemic_status"),
    ({"event_id": "e1"}, "event_id"),
    ({"trace_id": "t1"}, "trace_id"),
    ({"parent_ids": ["e1"]}, "parent_ids[0]"),
    ({"parent_ids": ["evt_01"]}, "parent_ids"),          # its own parent
    ({"timestamp": "now"}, "timestamp"),
    ({"subject": 7}, "subject"),
    ({"surprise": 1}, "surprise"),
    ({"payload": {}}, "payload.operator"),
    ({"runtime": {"build": "abc"}}, "runtime.pack"),
    ({"level": "LOUD"}, "level"),
])
def test_the_validator_names_the_offending_field(change, field):
    with pytest.raises(schema.SchemaError) as caught:
        schema.validate(_event(**change))
    assert caught.value.field == field
    assert field in str(caught.value)


@pytest.mark.parametrize("name", [f.name for f in schema.FIELDS if f.required])
def test_a_missing_required_field_is_named(name):
    event = _event()
    del event[name]
    with pytest.raises(schema.SchemaError) as caught:
        schema.validate(event)
    assert caught.value.field == name
    assert "missing" in str(caught.value)


def test_a_state_change_must_carry_before_after_and_cause():
    event = _event(kind="state_changed", payload={"field": "count", "before": 5, "after": 3})
    with pytest.raises(schema.SchemaError) as caught:
        schema.validate(event)
    assert caught.value.field == "payload.cause"
    event["payload"]["cause"] = "evt_00"
    schema.validate(event)


def test_optional_fields_may_be_left_out():
    event = _event()
    for name in ("schema", "system", "subsystem"):
        event.pop(name)
    schema.validate(event)
    schema.validate(_event(scope={"world": True, "holder": None}, goal_id="goal_1", supersedes="evt_00"))


def test_the_tables_are_data_the_validator_reads():
    kinds = copy.deepcopy(schema.KINDS)
    try:
        schema.KINDS["probe_kind"] = schema.Kind("OBSERVATION", "PRB", False, ("success",), (), "")
        schema.validate(_event(kind="probe_kind", payload={}))
    finally:
        schema.KINDS.clear()
        schema.KINDS.update(kinds)
    with pytest.raises(schema.SchemaError):
        schema.validate(_event(kind="probe_kind", payload={}))
