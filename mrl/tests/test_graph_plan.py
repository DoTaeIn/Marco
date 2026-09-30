import tempfile
import unittest
import ctypes
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

from mrl.graph_plan import compile_plan, emit_plan, make_plan
from mrl import native_graph
from mrl import toolchain


CASE = {"operation": "closure", "facts": [
    {"id": "seed", "triple": ["a", "p", "a"], "evidence": {}}],
    "rules": [{"id": "repeat", "body": [["?node", "p", "?node"]],
               "head": ["?node", "q", "?node"]}]}


class GraphPlanTests(unittest.TestCase):
    def test_plan_uses_adapter_interning_and_specializes_repeated_slots(self):
        ir = make_plan(CASE)
        self.assertEqual(ir["version"], 1)
        body, head = ir["rules"][0]["body"], ir["rules"][0]["head"]
        self.assertEqual((body[0], body[2], head[0], head[2]), (-1, -1, -1, -1))
        header = emit_plan(ir)
        self.assertIn("fact->o != fact->s", header)
        self.assertIn("slots[0] = fact->s", header)
        self.assertIn("MRL_GRAPH_PLAN_ACCEPTS", header)
        self.assertNotIn("bind(", header)

    def test_rejects_unsafe_and_malformed_plans(self):
        unsafe = {"version": 1, "kind": "horn_graph_plan",
                  "rules": [{"body": [-1, 2, -2], "head": [-3, 4, -2]}]}
        for ir in (unsafe, {}, {"version": 1, "kind": "horn_graph_plan", "rules": [{"body": [0, 1], "head": [0, 1, 2]}]}):
            with self.subTest(ir=ir), self.assertRaises(ValueError):
                emit_plan(ir)

    def test_make_plan_rejects_unsafe_adapter_input(self):
        case = {**CASE, "rules": [{"id": "unsafe", "body": [["?x", "p", "?y"]],
                                    "head": ["?z", "q", "?y"]}]}
        with self.assertRaises(ValueError):
            make_plan(case)

    def test_cache_hit_and_invalidation_are_content_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "wrapper.c"
            source.write_text("int x;", encoding="utf-8")
            builds = []
            def build(_source, output, *, optimization):
                builds.append(optimization); Path(output).write_bytes(b"library")
            compiler = (["fake-cc"], False)
            with mock.patch.object(toolchain, "_TOOLS", root / "tools"), \
                 mock.patch.object(toolchain, "find_compiler", return_value=compiler), \
                 mock.patch.object(toolchain, "build_shared", side_effect=build):
                first = toolchain.cached_shared(source, extra_files={"plan.h": b"a"})
                with mock.patch.object(toolchain, "build_shared", side_effect=AssertionError("cache miss")):
                    self.assertEqual(toolchain.cached_shared(source, extra_files={"plan.h": b"a"}), first)
                toolchain.cached_shared(source, optimization="debug", extra_files={"plan.h": b"a"})
                toolchain.cached_shared(source, extra_files={"plan.h": b"b"})
                self.assertEqual(builds, ["release", "debug", "release"])
                with mock.patch.object(toolchain, "build_shared", side_effect=RuntimeError("failed")):
                    with self.assertRaises(RuntimeError):
                        toolchain.cached_shared(source, extra_files={"bad.h": b"x"})
                failed = toolchain.build_identity(source, extra_files={"bad.h": b"x"})
                self.assertFalse((root / "tools" / "native" / failed["cache_key"] / "ready.json").exists())
                with self.assertRaises(ValueError):
                    toolchain.cached_shared(source, extra_files={"wrapper.c": b"collision"})

    def test_concurrent_cache_builds_publish_only_complete_libraries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "wrapper.c"
            source.write_text("int x;", encoding="utf-8")
            def build(_source, output, *, optimization):
                Path(output).write_bytes(b"complete-" + optimization.encode())
            with mock.patch.object(toolchain, "_TOOLS", root / "tools"), \
                 mock.patch.object(toolchain, "find_compiler", return_value=(["fake-cc"], False)), \
                 mock.patch.object(toolchain, "build_shared", side_effect=build):
                with ThreadPoolExecutor(max_workers=4) as pool:
                    paths = list(pool.map(lambda _: toolchain.cached_shared(source), range(8)))
                self.assertTrue(all(path.is_file() and path.read_bytes() == b"complete-release" for path in paths))

    def test_plan_version_is_strict_and_rule_capacity_is_checked(self):
        valid = {"version": True, "kind": "horn_graph_plan", "rules": []}
        oversized = {"version": 1, "kind": "horn_graph_plan",
                     "rules": [{"body": [0, 1, 2], "head": [0, 1, 2]}] * 33}
        for ir in (valid, oversized):
            with self.subTest(ir=ir), self.assertRaises(ValueError):
                emit_plan(ir)

    @unittest.skipUnless(toolchain.find_compiler()[0] is not None, "no C compiler available")
    def test_compiled_plan_accepts_only_its_exact_rule_layout(self):
        library = ctypes.CDLL(str(compile_plan(CASE)))
        size = library.mrl_graph_state_size
        size.restype = ctypes.c_size_t
        prepare = library.mrl_graph_prepare
        prepare.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_size_t]
        prepare.restype = ctypes.c_int
        state = ctypes.create_string_buffer(size())
        packet = native_graph._prepare(CASE)[0]
        self.assertEqual(prepare(ctypes.create_string_buffer(packet), len(packet), state, len(state)), 0)
        mismatch = {**CASE, "rules": [{"id": "repeat", "body": [["?node", "p", "?node"]],
                                        "head": ["?node", "p", "?node"]}]}
        bad = native_graph._prepare(mismatch)[0]
        self.assertNotEqual(packet, bad)
        self.assertEqual(prepare(ctypes.create_string_buffer(bad), len(bad), state, len(state)), 4)


if __name__ == "__main__":
    unittest.main()
