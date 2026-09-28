"""Fixed local autonomous-environment reproduction; no network or external account."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import time

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from alma.environment import run_local_environment
from alma.runtime import AlmaRuntime


KG = ROOT / "graphs" / "graph_일상추론.kg"


def scenario():
    return {
        "goal": {"text": "물 2개 확보", "condition": {"field": "water", "at_least": 2},
                 "information_gap": "water-source", "control": "high"},
        "initial_observation": {"text": "저장고 물은 0개 있다.", "measurements": {"water": 0}},
        "reads": [
            {"name": "weather-read", "provides": ["weather"],
             "responses": {"weather": {"text": "날씨는 맑다.", "measurements": {"water": 0}}}},
            {"name": "water-read", "provides": ["water-source"],
             "responses": {"water-source": {"text": "우물에서 물 2개를 확인했다.",
                                                "measurements": {"water": 2}, "item": "water-read"}}},
        ],
    }


def run():
    checks, costs = [], {}

    def check(name, expected, actual):
        checks.append({"name": name, "expected": expected, "actual": actual, "ok": expected == actual})

    def timed(name, fn):
        started = time.perf_counter(); result = fn()
        costs[name] = round((time.perf_counter() - started) * 1000, 3)
        return result

    with TemporaryDirectory(prefix="alma-environment-") as folder:
        state = Path(folder) / "life.json"
        config = scenario()
        paused = timed("initial_episode_ms", lambda: run_local_environment(
            AlmaRuntime(state, "environment-alma"), KG, config, step_budget=1))
        check("budget_stops_before_read", "paused_budget", paused["status"])
        resumed = timed("restart_resume_ms", lambda: run_local_environment(
            AlmaRuntime(state, "environment-alma"), KG, config, run_id=paused["id"], step_budget=4))
        snapshot = AlmaRuntime(state, "environment-alma").snapshot()
        goal = next(row for row in snapshot["goals"] if row["id"] == resumed["goal_id"])
        calls = snapshot["capability_runs"]
        failed_config = scenario()
        failed_config["reads"][1]["responses"] = {}
        failed = timed("failed_read_episode_ms", lambda: run_local_environment(
            AlmaRuntime(Path(folder) / "failed-life.json", "failed-environment-alma"), KG, failed_config,
            step_budget=4))
        failed_outcome = next(row["outcome"] for row in failed["results"]
                              if row.get("phase") == "seek_information")
        independent = [{"id": "environment-water-goal", "split": "independent environment outcome",
                        "expected": "achieved", "actual": goal["status"],
                        "ok": goal["status"] == "achieved"},
                       {"id": "environment-read-failure-hold", "split": "same initial observation, failed relevant read",
                        "expected": "safe_hold", "actual": failed["status"],
                        "ok": failed["status"] == "safe_hold"}]
        check("matching_contract_selected", "water-read", calls[0]["capability"] if calls else None)
        recall = next((row.get("memory_recall") for row in resumed["results"]
                       if row.get("phase") == "seek_information"), None)
        check("episodic_recall_anchors_information_action", resumed["initial_event_id"],
              (recall or {}).get("provenance", {}).get("source_event_id"))
        check("unrelated_read_not_called", 0, sum(row["capability"] == "weather-read" for row in calls))
        check("observation_changes_goal_assessment", ("threat", "resolved"),
              (resumed["initial_affect"]["label"], resumed["final_affect"]["label"]))
        check("state_continues_after_new_process", paused["id"], resumed["id"])
        check("failed_relevant_read_is_observed_and_held", ("safe_hold", "failed", "failed"),
              (failed["status"], failed["reason"], failed_outcome["capability_result"]["status"]))
        return {"environment": {"graph_sha256": hashlib.sha256(KG.read_bytes()).hexdigest(),
                                 "scenario_sha256": hashlib.sha256(json.dumps(config, ensure_ascii=False,
                                                                           sort_keys=True).encode("utf-8")).hexdigest(),
                                 "python": sys.version.split()[0]},
                "functional_checks": checks, "independent_problems": independent,
                "outcomes": {"solved": sum(row["ok"] and row["expected"] != "safe_hold" for row in independent),
                             "safe_hold": sum(row["ok"] and row["expected"] == "safe_hold" for row in independent),
                             "wrong": sum(not row["ok"] for row in independent),
                             "execution_error": 0, "unverifiable": 0},
                "costs": costs, "state_bytes": state.stat().st_size}


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
