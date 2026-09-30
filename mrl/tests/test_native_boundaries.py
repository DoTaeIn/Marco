"""Adversarial checks for the native single-premise wire v2 boundary."""

import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

from mrl import native_graph, oracle, toolchain


MAGIC = 0x4D524C32
MALFORMED = 5
CAPACITY = 6
INT_MIN = -(2**31)
SOURCE = Path(__file__).parents[1] / "runtime" / "native_graph.c"


def words(operation=1, facts=(), rules=(), limit=64, proof_limit=32, search_limit=512):
    """Make one valid v2 packet; rules already use wire term IDs."""
    packet = [MAGIC, operation, len(facts), len(rules), limit, proof_limit, search_limit]
    packet += [word for fact in facts for word in fact]
    packet += [word for body, _ in rules for word in body]
    packet += [word for _, head in rules for word in head]
    return packet


@unittest.skipUnless(toolchain.find_compiler()[0] is not None, "no C compiler available")
class NativeWireBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        root = Path(cls.directory.name)
        source, cls.exe = root / "native_graph.c", root / "native_graph.exe"
        shutil.copyfile(SOURCE, source)
        # A present compiler that cannot build is a test failure, not a skip.
        toolchain.build_c(source, cls.exe)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def raw(self, packet):
        run = subprocess.run([str(self.exe)], input=packet, capture_output=True,
                             timeout=3, check=False)
        self.assertEqual(run.returncode, 0, run.stderr.decode("utf-8", "replace"))
        self.assertGreaterEqual(len(run.stdout), 4)
        self.assertEqual(len(run.stdout) % 4, 0)
        return struct.unpack("<%di" % (len(run.stdout) // 4), run.stdout)

    def status(self, packet):
        result = self.raw(packet)
        self.assertEqual(len(result), 1)
        return result[0]

    def test_malformed_wire_is_rejected_without_a_crash(self):
        header = struct.pack("<6i", MAGIC, 1, 0, 0, 1, 1)
        payload_missing_fact = struct.pack("<7i", MAGIC, 1, 1, 0, 1, 1, 1)
        invalid_variable = struct.pack("<%di" % len(words(rules=[((INT_MIN, 0, 0), (-1, 0, 0))])),
                                       *words(rules=[((INT_MIN, 0, 0), (-1, 0, 0))]))
        trailing = struct.pack("<%di" % len(words()), *words()) + b"x"
        negative_count = struct.pack("<7i", MAGIC, 1, -1, 0, 1, 1, 1)
        for packet in (header, payload_missing_fact, invalid_variable, trailing, negative_count):
            with self.subTest(size=len(packet)):
                self.assertEqual(self.status(packet), MALFORMED)

    def test_native_capacity_is_distinct_from_malformed_input(self):
        packet = struct.pack("<7i", MAGIC, 1, 65, 0, 65, 1, 1)
        self.assertEqual(self.status(packet), CAPACITY)

    def test_windows_ctrl_z_in_a_26_fact_header_is_binary_data(self):
        facts = [(index, 0, index + 26, 1, 1) for index in range(26)]
        result = self.raw(struct.pack("<%di" % len(words(facts=facts)), *words(facts=facts)))
        self.assertEqual(result[0], 0)
        self.assertEqual(result[4], 26)

    def test_admitted_cases_match_the_frozen_oracle(self):
        cases = [
            {"operation": "closure_with_provenance", "facts": [
                {"id": "ab", "triple": ["a", "p", "b"], "evidence": {}},
                {"id": "ac", "triple": ["a", "p", "c"], "evidence": {}},
                {"id": "db", "triple": ["d", "q", "b"], "evidence": {}},
            ], "rules": [{"id": "all_constants", "body": [["a", "p", "b"]],
                            "head": ["a", "r", "b"]}]},
            {"operation": "closure", "facts": [
                {"id": "first", "triple": ["a", "p", "b"], "evidence": {"which": "first"}},
                {"id": "last", "triple": ["a", "p", "b"], "evidence": {"which": "last"}},
            ], "rules": []},
            {"operation": "closure_with_provenance", "facts": [
                {"id": "first", "triple": ["a", "p", "b"], "evidence": {"which": "first"}},
                {"id": "last", "triple": ["a", "p", "b"], "evidence": {"which": "last"}},
            ], "rules": []},
            {"operation": "closure_with_provenance", "facts": [
                {"id": "first", "triple": ["a", "p", "b"], "evidence": {"which": "first"}},
                {"id": "last", "triple": ["a", "p", "b"], "evidence": {"which": "last"}},
                {"id": "other", "triple": ["c", "p", "d"], "evidence": {}},
            ], "rules": [], "options": {"limit": 1}},
            {"operation": "closure_with_provenance", "facts": [
                {"id": "seed", "triple": ["a", "p", "b"], "evidence": {}},
            ], "rules": [{"id": "names", "body": [["?subject_long", "p", "?object_9"]],
                            "head": ["?subject_long", "r", "?object_9"]}]},
        ]
        for case in cases:
            with self.subTest(case=case["operation"]):
                self.assertEqual(native_graph.evaluate(case), oracle.evaluate(case))

        bucket = native_graph.evaluate(cases[0])
        # The first round derives r; the fixed-point confirmation rescans the
        # smallest predicate bucket (two candidates) once more.
        self.assertEqual(bucket["searches"], 4)
        closure = native_graph.evaluate(cases[1])
        self.assertEqual(closure["known"]["$tuple_map"][0]["value"]["evidence"]["which"], "last")
        provenance = native_graph.evaluate(cases[2])
        row = provenance["proof_bundles"]["$tuple_map"][0]["value"]
        self.assertEqual(provenance["facts"]["$tuple_map"][0]["value"]["evidence"]["which"], "first")
        self.assertEqual([proof["id"] for proof in row], ["support:first", "support:last"])
        initial_overflow = native_graph.evaluate(cases[3])
        self.assertFalse(initial_overflow["complete"])
        self.assertEqual((initial_overflow["reason"], initial_overflow["searches"]), ("graph_limit", 0))

    def test_self_loop_uses_snapshot_proof_options_and_full_search_count(self):
        case = {"operation": "closure_with_provenance", "facts": [
            {"id": "seed", "triple": ["a", "p", "b"], "evidence": {}}],
            "rules": [{"id": "self", "body": [["?x", "p", "?y"]], "head": ["?x", "p", "?y"]}],
            "options": {"proof_limit": 3}}
        self.assertEqual(native_graph.evaluate(case), oracle.evaluate(case))
        result = native_graph.evaluate(case)
        self.assertFalse(result["complete"])
        self.assertEqual(result["searches"], 3)


if __name__ == "__main__":
    unittest.main()
