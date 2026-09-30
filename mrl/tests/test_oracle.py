import json
import unittest
from pathlib import Path

from mrl import oracle


FIXTURE = Path(__file__).parent / "fixtures" / "graph_inference_golden.json"


class GraphInferenceGoldenTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_fixture_is_pinned_to_the_baseline_and_oracle(self):
        metadata = self.fixture["metadata"]
        self.assertEqual(metadata["baseline_sha"], oracle.BASELINE_SHA)
        self.assertEqual(metadata["graph_inference_sha256"], oracle.graph_inference_sha256())
        self.assertEqual(metadata["oracle_sha256"], oracle.source_sha256())

    def test_cases_match_the_structured_oracle_snapshot(self):
        for case in self.fixture["cases"]:
            with self.subTest(case=case["id"]):
                self.assertEqual(case["expected"], oracle.evaluate(case))
