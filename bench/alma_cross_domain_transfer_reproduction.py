"""Fixed direct-input evaluation for one safe cross-domain program skeleton."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from marco.learning.concepts import ExperienceConceptStore


def record(index, domain, action, predicates):
    source, target = "source-%d" % index, "target-%d" % index
    event = {"id": "event:%d" % index, "domain": domain, "action": action,
             "definition_version": 0, "polarity": True, "modality": "asserted",
             "conditions": [], "roles": {"source": source, "target": target},
             "program": {"signature": {"open_roles": {"source": "source", "target": "target"},
                                       "role_slots": {"target": "target"},
                                       "fixed_values": {"item": domain}},
                         "steps": [{"op": "emit", "triples": [
                             [["$source", "$item"], predicates[0], "removed"],
                             [["$target", "$item"], predicates[1], "added"]]}]},
             "evidence": {"text": "%s/%s experience %d" % (domain, action, index)}}
    return {"event": event, "status": "executed",
            "effects": [[source, predicates[0], "removed"], [target, predicates[1], "added"]]}


def run():
    records = [record(1, "Quantity", "share", ("count_remove", "count_add")),
               record(2, "Location", "move", ("location_leave", "location_enter")),
               record(3, "Social", "link", ("relation_remove", "relation_add")),
               record(4, "Quantity", "share", ("count_remove", "count_add")),
               record(5, "Social", "link", ("relation_remove", "relation_add")),
               record(6, "Location", "move", ("location_leave", "location_enter"))]
    store = ExperienceConceptStore(); snapshot = store.sync(records)
    candidate = next(row for row in snapshot["candidates"]
                     if row["scope"].get("structural_level") == "cross_domain")
    application_ids = [row["event_id"] for row in snapshot["applications"]
                       if row["candidate_id"] == candidate["id"] and row["phase"] == "application"]
    restored = ExperienceConceptStore(); restored.restore(snapshot)
    restored_snapshot = restored.sync(records)
    disabled = ExperienceConceptStore(); disabled.disabled_ids.add(candidate["id"])
    changed = records + [record(7, "Social", "link", ("relation_remove", "relation_add"))]
    changed[-1]["event"]["program"]["steps"][0]["op"] = "relation"
    conflicted = ExperienceConceptStore().sync(changed)
    invalid = next(row for row in conflicted["candidates"] if row["id"] == candidate["id"])
    checks = [
        {"name": "three_declared_domains", "expected": ["Location", "Quantity", "Social"],
         "actual": candidate["scope"]["domains"], "ok": candidate["scope"]["domains"] == ["Location", "Quantity", "Social"]},
        {"name": "exact_predicates_remain_distinct", "expected": 3,
         "actual": len(candidate["member_shape_ids"]), "ok": len(candidate["member_shape_ids"]) == 3},
        {"name": "construction_validation_application_split", "expected": [3, 1, 2],
         "actual": [len(candidate[key]) for key in ("evidence_event_ids", "support_event_ids", "application_event_ids")],
         "ok": [len(candidate[key]) for key in ("evidence_event_ids", "support_event_ids", "application_event_ids")] == [3, 1, 2]},
        {"name": "applications_are_distinct_held_out_events", "expected": ["event:5", "event:6"],
         "actual": candidate["application_event_ids"],
         "ok": candidate["application_event_ids"] == ["event:5", "event:6"]},
        {"name": "applications_are_emitted_by_active_candidate", "expected": ["event:5", "event:6"],
         "actual": application_ids, "ok": application_ids == ["event:5", "event:6"]},
        {"name": "restore_preserves_application", "expected": snapshot["applications"],
         "actual": restored_snapshot["applications"], "ok": restored_snapshot["applications"] == snapshot["applications"]},
        {"name": "off_removes_only_cross_domain_application", "expected": [],
         "actual": [row for row in disabled.sync(records)["applications"] if row["candidate_id"] == candidate["id"]],
         "ok": not [row for row in disabled.sync(records)["applications"] if row["candidate_id"] == candidate["id"]]},
        {"name": "changed_operation_withdraws_candidate", "expected": "inactive", "actual": invalid["status"],
         "ok": invalid["status"] == "inactive" and invalid["counterexample_event_ids"] == ["event:7"]},
    ]
    independent = [{"id": "unseen-action-structure-%s" % expected.rsplit(":", 1)[-1],
                    "split": ("post-activation application" if index == 0
                              else "final independent evaluation"), "expected": expected,
                    "actual": application_ids[index] if index < len(application_ids) else None,
                    "ok": index < len(application_ids) and application_ids[index] == expected}
                   for index, expected in enumerate(candidate["application_event_ids"])]
    return {"input_mode": "direct_structured_event_records", "functional_checks": checks,
            "independent_problems": independent,
            "outcomes": {"solved": sum(row["ok"] for row in independent), "safe_hold": 0,
                         "wrong": 0 if all(row["ok"] for row in checks) else 1,
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
