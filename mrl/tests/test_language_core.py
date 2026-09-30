import subprocess
import tempfile
import unittest
from pathlib import Path

from mrl.c_backend import emit_c
from mrl.frontend import MrlError, compile_source
from mrl.toolchain import build_c


def run(source):
    with tempfile.TemporaryDirectory(prefix="mrl-language-core-") as folder:
        c, exe = Path(folder) / "x.c", Path(folder) / "x.exe"
        c.write_text(emit_c(compile_source(source)), encoding="utf-8")
        build_c(c, exe)
        return subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)


class LanguageCoreTests(unittest.TestCase):
    def test_checked_division_modulus_and_short_circuit(self):
        source = '''
fn trap() -> b { return 1 / 0 == 1 }
fn main() -> si {
  if (false and trap()) { return 9 }
  if (true or trap()) { return 17 / 3 + (-17 % 3) }
  return 8
}'''
        result = run(source)
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, ["3"]))
        self.assertNotIn("division by zero", result.stderr)

    def test_else_if_break_continue_and_fixed_width_values(self):
        source = '''
fn main() {
  a: ui64 = 18446744073709551615
  i: si = 0
  while (i < 10) { i := i + 1 if (i == 2) { continue } if (i == 4) { break } }
  if (i == 4) { print(a) } else if (false) { print(0) } else { print(1) }
}'''
        result = run(source)
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, ["18446744073709551615"]))

    def test_zero_division_is_runtime_error_and_break_needs_loop(self):
        result = run("fn main() -> si { return 1 / 0 }")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MRL division by zero", result.stderr)
        with self.assertRaises(MrlError):
            compile_source("fn main() { break }")

    def test_fixed_width_checked_cast_and_contextual_minimum(self):
        result = run("fn main() { x: si64 = -9223372036854775808 print(x) print(ui8(255)) }")
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, ["-9223372036854775808", "255"]))
        result = run("fn main() { print(ui8(256)) }")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("MRL checked cast", result.stderr)

    def test_checked_wide_integer_edges(self):
        result = run("fn main(){ x: ui64 = 18446744073709551615 print(x + 1) }")
        self.assertNotEqual(result.returncode, 0)
        result = run("fn main(){ x: si64 = -9223372036854775808 print(x / -1) }")
        self.assertNotEqual(result.returncode, 0)


if __name__ == "__main__":
    unittest.main()
