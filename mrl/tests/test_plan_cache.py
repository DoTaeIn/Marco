"""Process-local specialized-plan setup cache checks."""
from copy import deepcopy
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from mrl import graph_plan


CASE = {"operation": "closure", "facts": [
    {"id": "seed", "triple": ["a", "p", "a"], "evidence": {}}],
    "rules": [{"id": "repeat", "body": [["?node", "p", "?node"]],
               "head": ["?node", "q", "?node"]}]}


class PlanSetupCacheTests(unittest.TestCase):
    def setUp(self):
        graph_plan._compiled_plan.cache_clear()

    def tearDown(self):
        graph_plan._compiled_plan.cache_clear()

    def test_reuses_validated_plan_and_invalidates_source_plan_and_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "native_graph.c"
            source.write_bytes(b"first source")
            calls = []

            def cached(wrapper, *, optimization, extra_files):
                calls.append((Path(wrapper).read_bytes(), optimization, extra_files))
                return Path(directory) / ("plan-%d.dll" % len(calls))

            with mock.patch.object(graph_plan, "_SOURCE", source), \
                 mock.patch.object(graph_plan.toolchain, "cached_shared", side_effect=cached):
                first = graph_plan.compile_plan(CASE)
                self.assertEqual(graph_plan.compile_plan(deepcopy(CASE)), first)
                self.assertEqual(len(calls), 1)
                self.assertEqual(calls[0][0], graph_plan._WRAPPER)
                self.assertEqual(calls[0][2]["native_graph.c"], b"first source")
                with self.assertRaises(ValueError):
                    graph_plan.compile_plan(CASE, optimization=[])
                unsafe = deepcopy(CASE)
                unsafe["rules"][0]["head"][0] = "?other"
                with self.assertRaises(ValueError):
                    graph_plan.compile_plan(unsafe)
                self.assertEqual(len(calls), 1)

                source.write_bytes(b"changed source")
                graph_plan.compile_plan(CASE)
                changed = deepcopy(CASE)
                changed["rules"][0]["head"][0] = "a"
                graph_plan.compile_plan(changed)
                graph_plan.compile_plan(CASE, optimization="debug")
                self.assertEqual(len(calls), 4)
                self.assertEqual(calls[-1][1], "debug")
                self.assertNotEqual(calls[1][2]["native_graph.c"], calls[0][2]["native_graph.c"])
                self.assertNotEqual(calls[2][2]["graph_plan.h"], calls[1][2]["graph_plan.h"])


if __name__ == "__main__":
    unittest.main()
