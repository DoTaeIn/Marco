# -*- coding: utf-8 -*-
import tempfile
import unittest
from pathlib import Path

from goal_runtime import GoalRuntime
import input_understanding


class GoalRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runtime = GoalRuntime(self.root)
        self.session = "test_session_123"

    def tearDown(self):
        self.temp.cleanup()

    def test_write_waits_for_plan_approval(self):
        text = 'note.txt에 "hello" 저장해줘'
        plan = self.runtime.plan_work(text, input_understanding.understand(text), "risk")
        self.runtime.remember(self.session, plan)
        self.assertFalse((self.root / "note.txt").exists())
        self.assertEqual(plan["workspace"], str(self.root.resolve()))
        result = self.runtime.approve(self.session, plan["plan_id"], plan["plan_hash"], [plan["actions"][0]["id"]])
        self.assertEqual(result["executed"][0]["status"], "done")
        self.assertEqual((self.root / "note.txt").read_text(), "hello")

    def test_high_risk_action_cannot_run_without_direct_approval(self):
        plan = {"plan_id": "danger", "plan_hash": "hash", "expires_at": 9e9, "mode": "risk",
                "actions": [self.runtime._action("workspace.fake", "삭제", risk="destructive")]}
        self.runtime.remember(self.session, plan)
        result = self.runtime.approve(self.session, "danger", "hash", [plan["actions"][0]["id"]])
        self.assertFalse(result["executed"])
        self.assertEqual(len(result["needs_direct_approval"]), 1)

    def test_all_steps_requires_one_action(self):
        plan = {"plan_id": "one", "plan_hash": "hash", "expires_at": 9e9, "mode": "all_steps",
                "actions": [self.runtime._action("workspace.read", "a", target="a", risk="read"), self.runtime._action("workspace.read", "b", target="b", risk="read")]}
        self.runtime.remember(self.session, plan)
        with self.assertRaises(ValueError):
            self.runtime.approve(self.session, "one", "hash", [x["id"] for x in plan["actions"]])


if __name__ == "__main__":
    unittest.main()
