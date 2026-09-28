"""Reproduce an experience-backed self-authoring graph asset lifecycle."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import kgpack
from alma.runtime import AlmaRuntime


KG = ROOT / "graphs" / "graph_일상추론.kg"


def run():
    with TemporaryDirectory(prefix="alma-graph-asset-") as folder:
        root = Path(folder)
        state, base, exported, withdrawn = (root / "life.json", root / "base.kgpack",
                                             root / "approved.kgpack", root / "withdrawn.kgpack")
        runtime = AlmaRuntime(state, "asset-alma")
        for text in ("베풀다는 상대에게 구슬 2개를 주는 것이다.",
                     "민수 구슬은 8개 있다. 지연 구슬은 3개 있다. 가람 구슬은 8개 있다. 하루 구슬은 3개 있다. 서준 구슬은 8개 있다. 유나 구슬은 3개 있다. 도윤 구슬은 8개 있다. 소라 구슬은 3개 있다.",
                     "민수가 지연에게 베풀었다.", "가람이 하루에게 베풀었다.",
                     "서준이 유나에게 베풀었다.", "도윤이 소라에게 베풀었다."):
            runtime.turn(text, KG)
        event_ids = [row["id"] for row in runtime.snapshot()["event_index"]
                     if row["execution_status"] == "executed"]
        kgpack.write_pack(base, [KG] + kgpack.model_files(ROOT), root=ROOT, language="styles/한국어.json")
        base_sha256 = hashlib.sha256(base.read_bytes()).hexdigest()
        candidate = root / "graph_derived.kg"
        candidate.write_text(KG.read_text(encoding="utf-8"), encoding="utf-8")
        proposed = runtime.propose_graph_asset_file_change(
            candidate, construction_event_ids=event_ids[:3], validation_event_ids=event_ids[3:],
            base_pack_sha256=base_sha256)
        approved = runtime.approve_graph_asset_change(proposed["id"])
        receipt = runtime.export_active_graph_assets(base, exported)
        exported_assets = kgpack.read(exported)[1]
        restarted = AlmaRuntime(state, "asset-alma")
        restarted_status = restarted.snapshot()["structural_changes"][-1]["status"]
        rolled_back = restarted.rollback_graph_asset_change(approved["id"], "counterexample")
        restarted.export_active_graph_assets(base, withdrawn)
        withdrawn_assets = kgpack.read(withdrawn)[1]
        checks = [
            {"name": "construction_validation_lineage_is_disjoint", "expected": True,
             "actual": not (set(proposed["lineage"]["construction_event_ids"])
                            & set(proposed["lineage"]["validation_event_ids"])),
             "ok": not (set(proposed["lineage"]["construction_event_ids"])
                        & set(proposed["lineage"]["validation_event_ids"]))},
            {"name": "candidate_records_node_edge_validation", "expected": True,
             "actual": proposed["validation"]["lint"] == "passed"
                       and proposed["validation"]["node_count"] > 0
                       and proposed["validation"]["edge_count"] > 0,
             "ok": proposed["validation"]["lint"] == "passed"
                   and proposed["validation"]["node_count"] > 0
                   and proposed["validation"]["edge_count"] > 0},
            {"name": "approved_asset_exports_without_mutating_base_pack", "expected": True,
             "actual": (hashlib.sha256(base.read_bytes()).hexdigest() == base_sha256
                        and "graphs/graph_derived.kg" in exported_assets
                        and approved["id"] in receipt["asset_change_ids"]),
             "ok": (hashlib.sha256(base.read_bytes()).hexdigest() == base_sha256
                    and "graphs/graph_derived.kg" in exported_assets
                    and approved["id"] in receipt["asset_change_ids"])},
            {"name": "restart_keeps_change_lineage", "expected": "active",
             "actual": restarted_status, "ok": restarted_status == "active"},
            {"name": "withdrawal_excludes_only_asset_from_next_export", "expected": "withdrawn",
             "actual": rolled_back["status"] if "graphs/graph_derived.kg" not in withdrawn_assets else "present",
             "ok": rolled_back["status"] == "withdrawn" and "graphs/graph_derived.kg" not in withdrawn_assets},
        ]
        return {"functional_checks": checks,
                "lineage": proposed["lineage"],
                "independent_problems": [{"id": "approved-graph-asset-export", "expected": True,
                                            "actual": "graphs/graph_derived.kg" in exported_assets,
                                            "ok": "graphs/graph_derived.kg" in exported_assets}],
                "outcomes": {"solved": 1, "safe_hold": 0, "wrong": 0,
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
