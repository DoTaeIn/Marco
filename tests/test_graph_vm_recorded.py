import copy
import hashlib
import json
import unittest
from unittest import mock

from marco.reasoning import graph_vm


def program(entry, *nodes):
    return {"schema": graph_vm.PROGRAM_SCHEMA, "entry": entry, "nodes": list(nodes)}


def lit(value):
    return {"literal": value}


def var(*path):
    return {"var": list(path)}


def inp(*path):
    return {"input": list(path)}


def canonical_sha(value):
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode("utf-8")).hexdigest()


RECORD_KEYS = {"schema", "program_sha256", "input_sha256", "budget",
               "trace_limit", "steps", "complete", "reason"}
STEP_KEYS = {"index", "node_id", "op", "used_before", "used_after", "next_node",
             "status", "bindings", "reads", "branch", "reason"}

MIXED = program(
    "xs",
    {"id": "xs", "op": "set", "name": "xs", "value": inp("items"), "next": "acc"},
    {"id": "acc", "op": "set", "name": "acc", "value": lit([]), "next": "s"},
    {"id": "s", "op": "scan", "source": var("xs"), "item": "it",
     "body": "br", "done": "both"},
    {"id": "br", "op": "branch", "left": var("it"), "right": lit("b"),
     "yes": "ap", "no": "s"},
    {"id": "ap", "op": "append", "name": "acc", "value": var("it"), "next": "s"},
    {"id": "both", "op": "intersect", "name": "both", "left": var("acc"),
     "right": inp("other"), "next": "m"},
    {"id": "m", "op": "match", "pattern": lit({"k": {"capture": "v"}}),
     "value": {"compute": {"op": "lookup",
                           "args": [inp("map"), lit("key"), lit(None)]}},
     "bindings": "cap", "yes": "ret", "no": "ret"},
    {"id": "ret", "op": "return", "value": var("both")},
)
MIXED_INPUTS = {"items": ["a", "b"], "other": ["b", "z"], "map": {"key": {"k": 7}}}
RETURN_ONE = program("r", {"id": "r", "op": "return", "value": lit(1)})


class RecordedRunTest(unittest.TestCase):
    def test_matches_run_and_records_actual_path(self):
        legacy = graph_vm.run(MIXED, MIXED_INPUTS)
        out = graph_vm.run_recorded(MIXED, MIXED_INPUTS)
        self.assertEqual(legacy["status"], "completed")
        self.assertEqual(legacy["value"], ["b"])
        self.assertEqual(out["result"], legacy)
        self.assertEqual(set(out), {"result", "record"})
        record = out["record"]
        self.assertEqual(set(record), RECORD_KEYS)
        self.assertEqual(record["schema"], "marco-graph-vm-receipt-v1")
        self.assertTrue(record["complete"])
        self.assertIsNone(record["reason"])
        steps = record["steps"]
        self.assertEqual([s["node_id"] for s in steps],
                         ["xs", "acc", "s", "br", "s", "br", "ap", "s",
                          "both", "m", "ret"])
        for i, step in enumerate(steps):
            self.assertEqual(set(step), STEP_KEYS)
            self.assertEqual(step["index"], i)
            self.assertEqual(step["status"], "completed")
            self.assertLessEqual(step["used_before"], step["used_after"])
            if i:
                self.assertEqual(step["used_before"], steps[i - 1]["used_after"])
            if i + 1 < len(steps):
                self.assertEqual(step["next_node"], steps[i + 1]["node_id"])
        self.assertEqual(steps[0]["used_before"], 0)
        self.assertEqual(steps[-1]["used_after"], legacy["used"])
        self.assertIsNone(steps[-1]["next_node"])
        self.assertEqual(steps[0]["reads"], [{"kind": "input", "path": ["items"]}])
        self.assertEqual(steps[0]["bindings"], {"xs": ["a", "b"]})
        self.assertEqual(steps[2]["reads"], [{"kind": "var", "path": ["xs"]}])
        self.assertEqual(steps[2]["bindings"], {"it": "a"})
        self.assertEqual(steps[4]["reads"], [])
        self.assertEqual(steps[4]["bindings"], {"it": "b"})
        self.assertEqual((steps[3]["branch"], steps[3]["reason"]), (False, "branch_false"))
        self.assertEqual((steps[5]["branch"], steps[5]["reason"]), (True, None))
        self.assertEqual(steps[6]["bindings"], {"acc": ["b"]})
        self.assertEqual(steps[7]["reason"], "scan_exhausted")
        self.assertEqual(steps[7]["bindings"], {})
        self.assertIsNone(steps[7]["branch"])
        self.assertEqual(steps[8]["reads"], [{"kind": "var", "path": ["acc"]},
                                             {"kind": "input", "path": ["other"]}])
        self.assertEqual(steps[8]["bindings"], {"both": ["b"]})
        self.assertEqual(steps[9]["reads"], [{"kind": "input", "path": ["map"]}])
        self.assertEqual(steps[9]["bindings"], {"cap": {"v": 7}})
        self.assertTrue(steps[9]["branch"])
        self.assertEqual(steps[10]["reads"], [{"kind": "var", "path": ["both"]}])

    def test_match_failure_is_structural_outcome(self):
        prog = program(
            "m",
            {"id": "m", "op": "match", "pattern": lit(1), "value": lit(2),
             "bindings": "b", "yes": "r", "no": "r"},
            {"id": "r", "op": "return", "value": lit(0)})
        out = graph_vm.run_recorded(prog, {})
        self.assertEqual(out["result"], graph_vm.run(prog, {}))
        step = out["record"]["steps"][0]
        self.assertEqual((step["branch"], step["reason"], step["status"]),
                         (False, "match_failed", "completed"))
        self.assertEqual(step["bindings"], {})
        self.assertEqual(step["next_node"], "r")

    def test_invalid_runtime_reference(self):
        prog = program("x", {"id": "x", "op": "set", "name": "y",
                             "value": var("missing"), "next": "x"})
        legacy = graph_vm.run(prog, {})
        out = graph_vm.run_recorded(prog, {})
        self.assertEqual(legacy["status"], "invalid")
        self.assertEqual(out["result"], legacy)
        record = out["record"]
        self.assertTrue(record["complete"])
        self.assertEqual(record["reason"], "invalid_expression")
        step, = record["steps"]
        self.assertEqual(step["node_id"], "x")
        self.assertEqual(step["status"], "invalid")
        self.assertEqual(step["reason"], "invalid_expression")
        self.assertIsNone(step["next_node"])
        self.assertEqual(step["reads"], [{"kind": "var", "path": ["missing"]}])
        self.assertEqual(step["used_after"], legacy["used"])

    def test_midnode_capacity(self):
        prog = program("x", {"id": "x", "op": "set", "name": "y",
                             "value": {"array": [lit(1)] * 10}, "next": "x"})
        legacy = graph_vm.run(prog, {}, budget=3)
        out = graph_vm.run_recorded(prog, {}, budget=3)
        self.assertEqual(legacy["status"], "capacity")
        self.assertEqual(out["result"], legacy)
        record = out["record"]
        self.assertEqual((record["complete"], record["reason"]), (True, "capacity"))
        step = record["steps"][-1]
        self.assertEqual((step["node_id"], step["status"], step["reason"]),
                         ("x", "capacity", "capacity"))
        self.assertEqual(step["used_after"], legacy["used"])
        self.assertEqual(record["budget"], 3)

    def test_pins_canonical_and_unsafe_inputs_rejected(self):
        first = graph_vm.run_recorded(RETURN_ONE, {"a": 1, "b": [2]})
        second = graph_vm.run_recorded(RETURN_ONE, {"b": [2], "a": 1})
        self.assertEqual(first["record"]["input_sha256"],
                         second["record"]["input_sha256"])
        self.assertEqual(first["record"]["input_sha256"],
                         canonical_sha({"a": 1, "b": [2]}))
        self.assertEqual(first["record"]["program_sha256"], canonical_sha(RETURN_ONE))
        for bad in ({"s": chr(0xD800)}, {"o": object()}, [float("nan")]):
            out = graph_vm.run_recorded(RETURN_ONE, bad)
            self.assertEqual(out["result"], graph_vm.run(RETURN_ONE, bad))
            self.assertEqual(out["result"]["status"], "invalid")
            record = out["record"]
            self.assertIsNone(record["input_sha256"])
            self.assertEqual(record["program_sha256"], canonical_sha(RETURN_ONE))
            self.assertEqual(record["steps"], [])
            self.assertFalse(record["complete"])
            self.assertIn(record["reason"], ("invalid_payload", "limit"))
        out = graph_vm.run_recorded({"schema": "x"}, {})
        self.assertEqual(out["record"]["reason"], "invalid_program")
        self.assertIsNone(out["record"]["program_sha256"])

    def test_zero_budget_and_invalid_config(self):
        out = graph_vm.run_recorded(RETURN_ONE, {}, budget=0)
        self.assertEqual(out["result"], graph_vm.run(RETURN_ONE, {}, budget=0))
        self.assertEqual(out["record"]["steps"], [])
        self.assertEqual((out["record"]["complete"], out["record"]["reason"]),
                         (True, "capacity"))
        invalid = {"schema": graph_vm.RESULT_SCHEMA, "status": "invalid",
                   "value": None, "used": 0}
        for budget in (True, -1, 1.0, graph_vm.MAXIMUM_BUDGET + 1):
            out = graph_vm.run_recorded(RETURN_ONE, {}, budget=budget)
            self.assertEqual(out["result"], invalid)
            self.assertEqual(out["record"]["reason"], "invalid_budget")
            self.assertIsNone(out["record"]["budget"])
            self.assertFalse(out["record"]["complete"])
        for limit in (True, 0, 257, 2.0):
            out = graph_vm.run_recorded(RETURN_ONE, {}, trace_limit=limit)
            self.assertEqual(out["result"], invalid)
            self.assertEqual(out["record"]["reason"], "invalid_trace_limit")
            self.assertIsNone(out["record"]["trace_limit"])
            self.assertFalse(out["record"]["complete"])

    def test_no_input_mutation_or_aliasing(self):
        inputs = copy.deepcopy(MIXED_INPUTS)
        out = graph_vm.run_recorded(MIXED, inputs)
        self.assertEqual(inputs, MIXED_INPUTS)
        out["record"]["steps"][0]["bindings"]["xs"].append("q")
        out["record"]["steps"][9]["reads"][0]["path"].append("q")
        out["result"]["value"].append("q")
        self.assertEqual(inputs, MIXED_INPUTS)
        self.assertEqual(MIXED["nodes"][0]["value"], inp("items"))
        self.assertEqual(graph_vm.run_recorded(MIXED, inputs)["result"],
                         graph_vm.run(MIXED, MIXED_INPUTS))

    def test_trace_limit_keeps_legacy_result(self):
        prog = program(
            "s",
            {"id": "s", "op": "scan", "source": inp("xs"), "item": "it",
             "body": "s", "done": "r"},
            {"id": "r", "op": "return", "value": lit(0)})
        inputs = {"xs": list(range(10))}
        out = graph_vm.run_recorded(prog, inputs, trace_limit=3)
        self.assertEqual(out["result"], graph_vm.run(prog, inputs))
        record = out["record"]
        self.assertEqual(len(record["steps"]), 3)
        self.assertEqual((record["complete"], record["reason"]), (False, "trace_limit"))
        self.assertEqual([s["bindings"] for s in record["steps"]],
                         [{"it": 0}, {"it": 1}, {"it": 2}])
        full = graph_vm.run_recorded(prog, inputs, trace_limit=12)
        self.assertTrue(full["record"]["complete"])
        self.assertEqual(len(full["record"]["steps"]), 12)

    def test_trace_size_limit_bounded(self):
        prog = program(
            "a",
            {"id": "a", "op": "set", "name": "a", "value": inp("s"), "next": "b1"},
            {"id": "b1", "op": "set", "name": "b", "value": var("a"), "next": "b2"},
            {"id": "b2", "op": "set", "name": "b", "value": var("a"), "next": "r"},
            {"id": "r", "op": "return", "value": lit(1)})
        inputs = {"s": "x" * 60000}
        legacy = graph_vm.run(prog, inputs)
        self.assertEqual(legacy["status"], "completed")
        out = graph_vm.run_recorded(prog, inputs)
        self.assertEqual(out["result"], legacy)
        record = out["record"]
        self.assertEqual((record["complete"], record["reason"]),
                         (False, "trace_size_limit"))
        self.assertLess(len(record["steps"]), 3)
        self.assertEqual(graph_vm.validate_value(record), record)
        encoded = json.dumps(record, ensure_ascii=False, sort_keys=True,
                             separators=(",", ":")).encode("utf-8")
        self.assertLessEqual(len(encoded), graph_vm.MAXIMUM_PAYLOAD_UTF8_BYTES)

    def test_single_execution_and_no_state_leak(self):
        with mock.patch.object(graph_vm, "_execute", wraps=graph_vm._execute) as spy:
            first = graph_vm.run_recorded(MIXED, MIXED_INPUTS)
        self.assertEqual(spy.call_count, 1)
        second = graph_vm.run_recorded(MIXED, MIXED_INPUTS)
        self.assertEqual(first, second)
        self.assertIsNot(first["record"]["steps"], second["record"]["steps"])

    def test_ordinary_run_keys_unchanged(self):
        self.assertEqual(set(graph_vm.run(MIXED, MIXED_INPUTS)),
                         {"schema", "status", "value", "used"})


if __name__ == "__main__":
    unittest.main()
