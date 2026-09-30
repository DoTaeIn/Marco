from copy import deepcopy
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from mrl import native_graph, oracle, toolchain

FIXTURE = Path(__file__).parent / "fixtures" / "graph_inference_golden.json"


@unittest.skipUnless(native_graph.available(), "no C compiler available")
class NativeGraphGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
        cls.directory = tempfile.TemporaryDirectory()
        source = Path(cls.directory.name) / "native_graph.c"
        cls.executable = source.with_suffix(".exe")
        shutil.copyfile(native_graph.SOURCE, source)
        toolchain.build_c(source, cls.executable)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def test_frozen_fixture_inputs_match_native_output(self):
        for case in self.cases:
            with self.subTest(case=case["id"]):
                original = deepcopy(case)
                self.assertEqual(case["expected"], native_graph.evaluate(case))
                self.assertEqual(case["expected"], native_graph.evaluate_subprocess(case, self.executable))
                self.assertEqual(case["expected"], native_graph.evaluate(case))
                self.assertEqual(case, original)

    def test_nonactual_and_negated_facts_do_not_infer(self):
        case = {"operation": "closure", "facts": [
            {"triple": ["a", "p", "b"], "evidence": {}, "polarity": False},
            {"triple": ["a", "q", "b"], "evidence": {}, "modality": "planned"}],
            "rules": [{"id": "r", "body": [["?x", "p", "?y"]], "head": ["?x", "z", "?y"]}]}
        self.assertEqual(native_graph.evaluate(case)["known"], {})

    def test_unsafe_rule_is_rejected(self):
        case = {"operation": "closure", "facts": [], "rules": [
            {"id": "unsafe", "body": [["?x", "p", "?y"]], "head": ["?z", "q", "?y"]}]}
        self.assertEqual(native_graph.evaluate(case), {"error": "unsafe_rule"})

    def test_self_loop_snapshots_parent_proofs_before_appending(self):
        case = {"operation": "closure_with_provenance", "facts": [
            {"id": "seed", "triple": ["a", "p", "b"], "evidence": {}}],
            "rules": [{"id": "self", "body": [["?x", "p", "?y"]], "head": ["?x", "p", "?y"]}],
            "options": {"proof_limit": 2}}
        self.assertEqual(native_graph.evaluate(case), oracle.evaluate(case))

    def test_invalid_operation_and_options_are_rejected_before_dispatch(self):
        for case in ({"operation": "unknown", "facts": [], "rules": []}, {"operation": "closure", "facts": [], "rules": [], "options": {"limit": "1"}}, {"operation": "closure", "facts": [], "rules": [], "options": {"proof_limit": 0}}):
            with self.subTest(case=case):
                with self.assertRaises(ValueError): native_graph.evaluate(case)

    def test_duplicate_semantic_ids_are_rejected_before_dispatch(self):
        duplicate_rule = {"operation": "closure", "facts": [], "rules": [{"id": "same", "body": [["?a", "p", "?b"]], "head": ["?a", "q", "?b"]}, {"id": "same", "body": [["?a", "r", "?b"]], "head": ["?a", "s", "?b"]}]}
        duplicate_support = {"operation": "closure", "facts": [{"id": "same", "triple": ["a", "p", "b"], "evidence": {}}, {"id": "same", "triple": ["c", "p", "d"], "evidence": {}}], "rules": []}
        for case in (duplicate_rule, duplicate_support):
            with self.subTest(case=case):
                with self.assertRaises(ValueError): native_graph.evaluate(case)
