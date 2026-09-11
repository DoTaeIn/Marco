from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import time

import pytest

from goal_runtime import GoalRuntime


@pytest.mark.parametrize("status", ["done", "failed", "exception"])
def test_repeated_and_concurrent_approval_runs_once(tmp_path, status):
    runtime = GoalRuntime(tmp_path)
    action = runtime._action("knowledge.learn", "learn")
    plan = {"plan_id": "plan", "plan_hash": "hash", "expires_at": time.time() + 60,
            "mode": "risk", "actions": [action]}
    runtime.remember("session", plan)
    result = {"action": action["id"], "status": status, "output": "result"}
    with patch.object(runtime, "_run", return_value=result,
                      side_effect=OSError("failed") if status == "exception" else None) as run:
        with ThreadPoolExecutor(max_workers=4) as pool:
            replies = list(pool.map(lambda _: runtime.approve("session", "plan", "hash", [action["id"]]), range(4)))
    assert run.call_count == 1
    assert sum(len(reply["executed"]) for reply in replies) == 1
    assert all(not reply["remaining"] for reply in replies)
    assert sum(len(reply["already_executed"]) for reply in replies) == 3


def test_direct_approval_denial_does_not_consume_action(tmp_path):
    runtime = GoalRuntime(tmp_path)
    action = runtime._action("external", "external", risk="external")
    plan = {"plan_id": "plan", "plan_hash": "hash", "expires_at": time.time() + 60,
            "mode": "risk", "actions": [action]}
    runtime.remember("session", plan)
    with patch.object(runtime, "_run", return_value={"status": "done"}) as run:
        first = runtime.approve("session", "plan", "hash", [action["id"]])
        assert first["needs_direct_approval"] == [action]
        run.assert_not_called()
        assert runtime.approve("session", "plan", "hash", [action["id"]], direct=True)["executed"]
    assert run.call_count == 1
