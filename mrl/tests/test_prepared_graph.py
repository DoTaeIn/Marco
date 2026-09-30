"""Resident graph parity, transactional appends and Python/native ownership."""
from copy import deepcopy
import json
import random
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import unittest

from mrl import native_graph, oracle

FIXTURE = Path(__file__).parent / "fixtures" / "graph_inference_golden.json"


def case():
    return {"operation": "closure_with_provenance", "facts": [
        {"id": "seed", "triple": ["a", "p", "b"], "evidence": {"source": "seed"}}],
        "rules": [
            {"id": "p_to_q", "body": [["?x", "p", "?y"]], "head": ["?x", "q", "?y"]},
            {"id": "q_to_r", "body": [["?x", "q", "?y"]], "head": ["?x", "r", "?y"]}],
        "options": {"limit": 64, "proof_limit": 8, "search_limit": 512}}


@unittest.skipUnless(native_graph.available(), "no C compiler available")
class PreparedGraphTests(unittest.TestCase):
    def test_frozen_cases_match_both_resident_paths(self):
        cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
        for row in cases:
            for specialized in (False, True):
                with self.subTest(case=row["id"], specialized=specialized):
                    if row["expected"] == {"error": "unsafe_rule"}:
                        with self.assertRaisesRegex(ValueError, "unsafe"):
                            native_graph.PreparedGraph(row, specialized=specialized)
                    else:
                        graph = native_graph.PreparedGraph(row, specialized=specialized)
                        self.assertEqual(graph.evaluate(), row["expected"])
                        self.assertEqual(graph.evaluate(), row["expected"])

    def test_delta_updates_preserve_symbol_ids_supports_and_denials(self):
        for specialized in (False, True):
            with self.subTest(specialized=specialized):
                current = case()
                graph = native_graph.PreparedGraph(current, specialized=specialized)
                additions = [
                    [{"id": "new_symbols", "triple": ["new", "p", "object"], "evidence": {}}],
                    [{"id": "alternate", "triple": ["a", "p", "b"], "evidence": {"source": "other"}}],
                    [{"id": "denial", "triple": ["a", "q", "b"], "evidence": {}, "polarity": False}],
                    [{"id": "planned", "triple": ["future", "p", "object"], "evidence": {}, "modality": "planned"}],
                    [],
                ]
                for rows in additions:
                    graph.append_facts(rows)
                    current["facts"].extend(deepcopy(rows))
                    self.assertEqual(graph.evaluate(), oracle.evaluate(current))

    def test_failed_append_does_not_modify_native_or_python_state(self):
        for specialized in (False, True):
            graph = native_graph.PreparedGraph(case(), specialized=specialized)
            before = graph.evaluate()
            invalid = [
                [{"id": "seed", "triple": ["duplicate", "p", "b"], "evidence": {}}],
                [{"id": "wrong", "triple": ["a", "p", 9], "evidence": {}}],
                [{"id": "large%d" % i, "triple": [str(i), "p", "b"], "evidence": {}} for i in range(64)],
            ]
            for rows in invalid:
                with self.assertRaises(ValueError):
                    graph.append_facts(rows)
                self.assertEqual(graph.evaluate(), before)
            valid = [{"id": "after_failure", "triple": ["valid", "p", "b"], "evidence": {}}]
            graph.append_facts(valid)
            expected = case()
            expected["facts"].extend(valid)
            self.assertEqual(graph.evaluate(), oracle.evaluate(expected))

    def test_mixed_constant_buckets_and_limits_match_oracle(self):
        rng = random.Random(407)
        for number in range(8):
            facts = [{"id": "f%d" % i,
                      "triple": ["n%d" % rng.randrange(3), "p%d" % rng.randrange(3), "n%d" % rng.randrange(3)],
                      "evidence": {}, "polarity": i != 5} for i in range(6)]
            rules = []
            for i in range(3):
                subject = rng.choice(["?subject", "n0", "n1"])
                obj = rng.choice(["?object", "n0", "n2"])
                rules.append({"id": "r%d" % i,
                              "body": [[subject, "p%d" % i, obj]],
                              "head": [subject, "p%d" % (i + 1), obj]})
            candidate = {"operation": "closure_with_provenance" if number % 2 else "closure",
                         "facts": facts, "rules": rules, "options": {"limit": 32}}
            if number % 2:
                candidate["options"].update(proof_limit=3, search_limit=number * 3)
            expected = oracle.evaluate(candidate)
            for specialized in (False, True):
                with self.subTest(number=number, specialized=specialized):
                    self.assertEqual(native_graph.PreparedGraph(candidate, specialized=specialized).evaluate(), expected)

    def test_inputs_and_results_are_independent_and_calls_can_overlap(self):
        original = case()
        expected = oracle.evaluate(deepcopy(original))
        graphs = [native_graph.PreparedGraph(original, specialized=flag) for flag in (False, True)]
        original["facts"][0]["evidence"]["source"] = "changed by caller"
        for graph in graphs:
            result = graph.evaluate()
            result["facts"]["$tuple_map"][0]["value"]["evidence"]["source"] = "changed output"
            self.assertEqual(graph.evaluate(), expected)
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(lambda i: graphs[i % 2].evaluate(), range(12)))
        self.assertEqual(results, [expected] * 12)


if __name__ == "__main__":
    unittest.main()

