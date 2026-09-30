import unittest

from mrl import benchmark_v4


class BenchmarkV4Tests(unittest.TestCase):
    def test_real_cases_are_attributed_to_existing_matching_tests(self):
        rows = benchmark_v4._source_attribution()
        self.assertEqual(set(rows), set(benchmark_v4.real_cases()))
        self.assertTrue(all(row["source_sha256"] for row in rows.values()))

    def test_path_batches_rotate_and_reverse(self):
        calls = {name: (lambda: None) for name in benchmark_v4.PATHS}
        _, orders = benchmark_v4._measure_paths(calls, 7, 1)
        self.assertEqual(len(orders), 7)
        self.assertEqual({tuple(sorted(order)) for order in orders}, {tuple(sorted(benchmark_v4.PATHS))})
        self.assertNotEqual(orders[0], orders[1])

    def test_append_fact_uses_the_first_rule_pattern(self):
        case = benchmark_v4.workloads()["closure_chain"]
        self.assertEqual(benchmark_v4._append_fact(case)["triple"],
                         ["benchmark-subject", "p0", "benchmark-object"])

    def test_fanout_append_budget_rejection_has_a_headroom_comparison_base(self):
        case = benchmark_v4.workloads()["closure_fanout"]
        original = {**case, "facts": case["facts"] + [benchmark_v4._append_fact(case)]}
        self.assertEqual(benchmark_v4.oracle.evaluate(original), {"error": "graph_limit"})
        base, adjustment = benchmark_v4._update_base(case)
        self.assertEqual(len(base["facts"]), 31)
        self.assertIn("graph-limit budget", adjustment)
