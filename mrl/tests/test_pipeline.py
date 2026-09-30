"""One integration check at the frontend-to-backend boundary."""
import unittest
import subprocess
import tempfile
from pathlib import Path

from mrl.frontend import compile_source
from mrl.c_backend import emit_c


class PipelineTest(unittest.TestCase):
    def test_typed_program_emits_checked_c(self):
        source = """
        fn add(a: si, b: si) -> si { return a + b }
        fn main() -> si {
            dec START = 4
            value = START
            value := add(value, 2)
            return value * 7
        }
        """
        ir = compile_source(source)
        self.assertEqual(ir["version"], 2)
        self.assertEqual(ir["functions"][0]["return_type"], "si32")
        code = emit_c(ir)
        self.assertIn("int32_t", code)
        self.assertIn("main", code)
        self.assertEqual(code, emit_c(compile_source(source)))


class NativeControlFlowTest(unittest.TestCase):
    def test_control_flow_semantics_survive_c_lowering(self):
        from mrl.toolchain import build_c, find_compiler
        if find_compiler()[0] is None:
            self.skipTest("complete native C toolchain unavailable")
        cases = [
            ("x = 0 while (x + 0 < 3) { x := x + 1 } return x", "3"),
            ("n = 3 total = 0 for (i in 0..n) { n := 0 total := total + 1 } return total", "3"),
            ("total = 0 for (i in 2147483646..2147483647) { total := total + 1 } return total", "1"),
            ("total = 0 for (i in 3..0) { total := total + 1 } return total", "0"),
            ("if (false) { return 2 } else { return 7 }", "7"),
        ]
        with tempfile.TemporaryDirectory() as directory:
            for index, (body, expected) in enumerate(cases):
                with self.subTest(body=body):
                    source = "fn main() -> si { " + body + " }"
                    c_file = Path(directory) / f"case_{index}.c"
                    exe = c_file.with_suffix(".exe")
                    c_file.write_text(emit_c(compile_source(source)), encoding="utf-8")
                    build_c(c_file, exe)
                    run = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
                    self.assertEqual(run.returncode, 0, run.stderr)
                    self.assertEqual(run.stdout.strip(), expected)


if __name__ == "__main__":
    unittest.main()
