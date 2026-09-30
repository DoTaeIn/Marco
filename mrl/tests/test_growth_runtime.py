"""The opt-in resident graph grows beyond the frozen 64-fact transport."""

from copy import deepcopy
import ctypes
import struct
import unittest

from mrl import native_graph, oracle


def fact(index):
    return {"id": "f%d" % index, "triple": ["n%d" % index, "p", "v"], "evidence": {}}


def case(count):
    return {"operation": "closure", "facts": [fact(index) for index in range(count)],
            "rules": [{"id": "p_to_q", "body": [["?x", "p", "?y"]],
                       "head": ["?x", "q", "?y"]}]}


@unittest.skipUnless(native_graph.available(), "no C compiler available")
class GrowingResidentGraphTests(unittest.TestCase):
    def test_explicit_capacity_preserves_large_growth_and_failed_append(self):
        current = case(40)
        graph = native_graph.PreparedGraph(current, capacity=128)
        self.assertEqual(graph.evaluate(), oracle.evaluate(current))

        delta = [fact(index) for index in range(40, 60)]
        graph.append_facts(delta)
        current["facts"].extend(deepcopy(delta))
        self.assertEqual(graph.evaluate(), oracle.evaluate(current))

        before = graph.evaluate()
        with self.assertRaisesRegex(ValueError, "native_capacity"):
            graph.append_facts([fact(index) for index in range(60, 129)])
        self.assertEqual(graph.evaluate(), before)

    def test_default_capacity_remains_the_legacy_limit(self):
        with self.assertRaisesRegex(ValueError, "native_capacity"):
            native_graph.PreparedGraph(case(65))

    def test_asserted_proofs_still_exceed_a_small_proof_limit(self):
        current = {"operation": "closure_with_provenance", "facts": [
            {"id": "f%d" % index, "triple": ["a", "p", "b"], "evidence": {}}
            for index in range(10)], "rules": [], "options": {"proof_limit": 1}}
        self.assertEqual(native_graph.PreparedGraph(current).evaluate(), oracle.evaluate(current))

    def test_large_provenance_support_set_is_not_truncated_by_proof_limit(self):
        current = {"operation": "closure_with_provenance", "facts": [
            {"id": "f%d" % index, "triple": ["a", "p", "b"], "evidence": {}}
            for index in range(128)], "rules": [], "options": {"proof_limit": 1}}
        self.assertEqual(native_graph.PreparedGraph(current, capacity=128).evaluate(), oracle.evaluate(current))

    def test_denial_append_recomputes_derived_intermediate(self):
        current = {"operation": "closure", "facts": [fact(0)], "rules": [
            {"id": "p_to_q", "body": [["?x", "p", "?y"]], "head": ["?x", "q", "?y"]},
            {"id": "q_to_r", "body": [["?x", "q", "?y"]], "head": ["?x", "r", "?y"]}]}
        graph = native_graph.PreparedGraph(current)
        graph.append_facts([{"id": "deny", "triple": ["n0", "q", "v"], "evidence": {}, "polarity": False}])
        current["facts"].append({"id": "deny", "triple": ["n0", "q", "v"], "evidence": {}, "polarity": False})
        self.assertEqual(graph.evaluate(), oracle.evaluate(current))

    def test_all_variable_body_still_uses_the_snapshot_bound(self):
        current = {"operation": "closure", "facts": [fact(0), fact(1)], "rules": [
            {"id": "any_to_q", "body": [["?x", "?predicate", "?y"]], "head": ["?x", "q", "?y"]}]}
        self.assertEqual(native_graph.PreparedGraph(current).evaluate(), oracle.evaluate(current))

    def test_capacity_requires_an_explicit_supported_integer(self):
        for value in (True, "64", 63, 16385):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "invalid_native_capacity"):
                native_graph.PreparedGraph(case(1), capacity=value)

    def test_corrupted_resident_budget_is_rejected_and_restorable(self):
        graph = native_graph.PreparedGraph(case(1))
        before = graph.evaluate()

        class Header(ctypes.Structure):
            _fields_ = [("tag", ctypes.c_uint32), ("version", ctypes.c_uint32),
                       ("owner", ctypes.c_void_p), ("op", ctypes.c_int32),
                       ("input_count", ctypes.c_int32), ("rule_count", ctypes.c_int32),
                       ("limit", ctypes.c_int32), ("proof_limit", ctypes.c_int32),
                       ("search_limit", ctypes.c_int32), ("capacity", ctypes.c_int32)]

        original = graph._state.raw[:ctypes.sizeof(Header)]
        Header.from_buffer(graph._state).search_limit = 0
        output, written = ctypes.create_string_buffer(len(graph._output)), ctypes.c_size_t(99)
        self.assertEqual(graph._library.mrl_graph_evaluate(
            graph._state, len(graph._state), output, len(output), ctypes.byref(written)), 2)
        self.assertEqual(written.value, 0)
        self.assertEqual(graph._library.mrl_graph_append(
            graph._state, len(graph._state), ctypes.create_string_buffer(struct.pack("<i", 0)), 4), 5)
        ctypes.memmove(graph._state, original, len(original))
        self.assertEqual(graph.evaluate(), before)


if __name__ == "__main__":
    unittest.main()
