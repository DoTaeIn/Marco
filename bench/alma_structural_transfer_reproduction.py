"""Direct structured-input reproduction for cross-action concept transfer."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from marco.learning.concepts import ExperienceConceptStore


def record(index, action, *, amount="2", conditions=None, modality="asserted"):
    giver, taker = "giver-%d" % index, "taker-%d" % index
    event = {"id": "event:%d" % index, "action": action, "definition_version": 0,
             "polarity": True, "modality": modality, "conditions": conditions or [],
             "roles": {"은": giver, "에게": taker},
             "program": {"signature": {"open_roles": {"giver": "은", "taker": "에게"},
                                       "role_slots": {"taker": "에게"},
                                       "fixed_values": {"item": "구슬", "n": amount}},
                         "steps": [{"op": "emit", "triples": [
                             [["$giver", "$item"], "count_remove", "$n"],
                             [["$taker", "$item"], "count_add", "$n"]]}]},
             "evidence": {"text": "%s structured experience %d" % (action, index)}}
    return {"event": event, "status": "executed",
            "effects": [[giver + " 구슬", "count_remove", amount],
                        [taker + " 구슬", "count_add", amount]]}


def run():
    actions = ("보냄", "나눔", "전달", "양도", "이관", "대여")
    records = [record(index, action) for index, action in enumerate(actions, start=1)]
    snapshot = ExperienceConceptStore().sync(records)
    candidate = next(row for row in snapshot["candidates"] if row["status"] == "active")
    applications = [row for row in snapshot["applications"] if row["phase"] == "application"]
    application_ids = [row["event_id"] for row in applications]
    restored = ExperienceConceptStore(); restored.restore(snapshot)
    resumed = restored.sync(records)
    disabled = ExperienceConceptStore(); disabled.disabled_ids.add(candidate["id"])
    without_structure = disabled.sync(records)
    conflict = ExperienceConceptStore().sync(records + [record(7, "변형", amount="3")])
    changed_effect = ExperienceConceptStore().sync(records + [record(7, "보냄", amount="3")])
    conditional = record(8, "조건부 보냄", conditions=[{"triple": ["날씨", "상태", "맑음"]}])
    planned = record(9, "계획 보냄", modality="planned")
    variants = ExperienceConceptStore().sync(records + [conditional, planned])
    active_actions = {action for row in variants["candidates"] if row["status"] == "active"
                      for action in row["scope"]["actions"]}
    used_evidence = {event_id for row in variants["candidates"]
                     for event_id in row["evidence_event_ids"] + row["support_event_ids"]}
    return {"input_mode": "direct_structured_event_records",
            "split": {"construction_event_ids": candidate["evidence_event_ids"],
                      "validation_event_ids": candidate["support_event_ids"],
                      "application_event_ids": candidate["application_event_ids"]},
            "functional_checks": [
                {"name": "cross_action_scope", "expected": sorted(actions),
                 "actual": candidate["scope"]["actions"], "ok": candidate["scope"]["actions"] == sorted(actions)},
                {"name": "separate_validation", "expected": ["event:4"],
                 "actual": candidate["support_event_ids"], "ok": candidate["support_event_ids"] == ["event:4"]},
                {"name": "held_out_unseen_action_applications", "expected": ["event:5", "event:6"],
                 "actual": application_ids, "ok": application_ids == ["event:5", "event:6"]},
                {"name": "cross_action_structure_survives_restore", "expected": snapshot["applications"],
                 "actual": resumed["applications"], "ok": resumed["applications"] == snapshot["applications"]},
                {"name": "off_removes_only_cross_action_structure", "expected": [],
                 "actual": without_structure["applications"], "ok": without_structure["applications"] == []},
                {"name": "different_structure_does_not_merge", "expected": True,
                 "actual": all("변형" not in row["scope"]["actions"] for row in conflict["candidates"]),
                 "ok": all("변형" not in row["scope"]["actions"] for row in conflict["candidates"])},
                {"name": "same_action_changed_effect_deactivates_structure", "expected": False,
                 "actual": any(row["status"] == "active" for row in changed_effect["candidates"]),
                 "ok": not any(row["status"] == "active" for row in changed_effect["candidates"])},
                {"name": "different_role_values_still_transfer", "expected": True,
                 "actual": application_ids == ["event:5", "event:6"]
                 and "giver-5" not in candidate["structural_definition"] and "giver-6" not in candidate["structural_definition"],
                 "ok": application_ids == ["event:5", "event:6"]
                 and "giver-5" not in candidate["structural_definition"] and "giver-6" not in candidate["structural_definition"]},
                {"name": "condition_change_is_not_merged", "expected": False,
                 "actual": "조건부 보냄" in active_actions, "ok": "조건부 보냄" not in active_actions},
                {"name": "planned_modality_is_not_training_evidence", "expected": False,
                 "actual": "event:9" in used_evidence, "ok": "event:9" not in used_evidence},
            ],
            "independent_problems": [{"id": "unseen-action-structure-5", "expected": "event:5",
                                      "actual": applications[0]["event_id"], "ok": applications[0]["event_id"] == "event:5"},
                                     {"id": "unseen-action-structure-6", "expected": "event:6",
                                      "actual": applications[1]["event_id"], "ok": applications[1]["event_id"] == "event:6"}],
            "outcomes": {"solved": 2 if application_ids == ["event:5", "event:6"] else 0,
                         "safe_hold": 0, "wrong": 0 if application_ids == ["event:5", "event:6"] else 1,
                         "execution_error": 0, "unverifiable": 0}}


def main(argv=None):
    parser = argparse.ArgumentParser(); parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report, code = run(), 0
    except Exception as exc:
        report, code = {"terminal": "execution_error", "error": repr(exc),
                        "outcomes": {"solved": 0, "safe_hold": 0, "wrong": 0,
                                     "execution_error": 1, "unverifiable": 0}}, 1
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    sys.stdout.buffer.write(payload.encode("utf-8"))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
