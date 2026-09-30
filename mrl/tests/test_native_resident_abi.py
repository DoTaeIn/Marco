"""Resident native state is reusable and append is all-or-nothing."""
import ctypes
import struct
import unittest

from mrl import native_graph, toolchain
from mrl import oracle


@unittest.skipUnless(native_graph.available(), "no C compiler available")
class NativeResidentAbiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.library = ctypes.CDLL(str(toolchain.cached_shared(native_graph.SOURCE)))
        word, size = ctypes.c_void_p, ctypes.c_size_t
        cls.library.mrl_graph_prepare.argtypes = [word, size, word, size]
        cls.library.mrl_graph_evaluate.argtypes = [word, size, word, size, ctypes.POINTER(size)]
        cls.library.mrl_graph_append.argtypes = [word, size, word, size]

    def test_recompute_and_transactional_append(self):
        case = {"operation": "closure", "facts": [
            {"triple": ["a", "p", "b"], "evidence": {}}],
            "rules": [{"id": "r", "body": [["?x", "p", "?y"]], "head": ["?x", "q", "?y"]}]}
        packet, symbols, names, provenance = native_graph._prepare(case)
        size = self.library.mrl_graph_state_size()
        state = ctypes.create_string_buffer(size)
        self.assertEqual(self.library.mrl_graph_prepare(ctypes.create_string_buffer(packet), len(packet), state, size), 0)

        def evaluate(current=case):
            output = ctypes.create_string_buffer(native_graph._MAX_CLOSURE_RESPONSE)
            written = ctypes.c_size_t()
            self.assertEqual(self.library.mrl_graph_evaluate(state, size, output, len(output), ctypes.byref(written)), 0)
            current_packet, current_symbols, current_names, current_provenance = native_graph._prepare(current)
            return native_graph._decode(output.raw[:written.value], current, current_symbols, current_names, current_provenance)

        self.assertEqual(evaluate(), native_graph.evaluate(case))
        invalid = struct.pack("<6i", 1, 9, 9, 1, 2, 0)
        self.assertEqual(self.library.mrl_graph_append(state, size, ctypes.create_string_buffer(invalid), len(invalid)), 5)
        self.assertEqual(evaluate(), native_graph.evaluate(case))

        delta = struct.pack("<6i", 1, 0, 1, 0, 1, 1)
        self.assertEqual(self.library.mrl_graph_append(state, size, ctypes.create_string_buffer(delta), len(delta)), 0)
        extended = {**case, "facts": case["facts"] + [{"triple": ["a", "p", "a"], "evidence": {}}]}
        self.assertEqual(evaluate(extended), native_graph.evaluate(extended))

    def test_snapshot_buckets_keep_constant_match_order_and_missing_keys_safe(self):
        case = {"operation": "closure_with_provenance", "facts": [
            {"id": "b", "triple": ["a", "p", "b"], "evidence": {}},
            {"id": "c", "triple": ["a", "p", "c"], "evidence": {}}],
            "rules": [{"id": "constant", "body": [["a", "p", "?x"]], "head": ["a", "q", "?x"]}]}
        self.assertEqual(native_graph.evaluate(case), oracle.evaluate(case))
        full = {"operation": "closure", "facts": [
            {"triple": ["s%d" % i, "p%d" % i, "o%d" % i], "evidence": {}}
            for i in range(64)],
            "rules": [{"id": "absent", "body": [["missing", "also_missing", "?x"]],
                       "head": ["missing", "q", "?x"]}]}
        self.assertEqual(native_graph.evaluate(full), oracle.evaluate(full))

    def test_state_is_rejected_by_a_different_compiled_library(self):
        from mrl.graph_plan import compile_plan
        case = {"operation": "closure", "facts": [
            {"triple": ["a", "p", "b"], "evidence": {}}], "rules": []}
        packet = native_graph._prepare(case)[0]
        size = self.library.mrl_graph_state_size()
        state = ctypes.create_string_buffer(size)
        self.assertEqual(self.library.mrl_graph_prepare(ctypes.create_string_buffer(packet), len(packet), state, size), 0)
        other = ctypes.CDLL(str(compile_plan(case)))
        other.mrl_graph_evaluate.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                             ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
        other.mrl_graph_append.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
        output, written = ctypes.create_string_buffer(native_graph._MAX_CLOSURE_RESPONSE), ctypes.c_size_t()
        self.assertEqual(other.mrl_graph_evaluate(state, size, output, len(output), ctypes.byref(written)), 2)
        delta = ctypes.create_string_buffer(struct.pack("<i", 0))
        self.assertEqual(other.mrl_graph_append(state, size, delta, len(delta)), 5)


if __name__ == "__main__":
    unittest.main()
