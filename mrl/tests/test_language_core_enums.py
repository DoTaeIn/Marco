import subprocess
import tempfile
import unittest
from pathlib import Path

from mrl.c_backend import emit_c
from mrl.frontend import MrlError, compile_source
from mrl.toolchain import build_c


def run(source):
    with tempfile.TemporaryDirectory(prefix="mrl-enum-") as folder:
        c, exe = Path(folder) / "x.c", Path(folder) / "x.exe"
        c.write_text(emit_c(compile_source(source)), encoding="utf-8")
        build_c(c, exe)
        return subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)


class EnumTests(unittest.TestCase):
    def test_enum_value_function_and_exhaustive_native_match(self):
        result = run('''
enum Color { Red Blue }
struct Box { color: Color }
fn score(box: Box) -> si { match (box.color) { Red { return 4 } Blue { return 9 } } }
fn main() -> si { return score(Box(color=Color.Blue)) }''')
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, ["9"]))

    def test_enum_match_diagnostics(self):
        with self.assertRaisesRegex(MrlError, "every member"):
            compile_source("enum Color { Red Blue } fn main() -> si { match (Color.Red) { Red { return 1 } } }")
        with self.assertRaisesRegex(MrlError, "duplicate match arm"):
            compile_source("enum Color { Red } fn main() -> si { match (Color.Red) { Red { return 1 } Red { return 2 } } }")
        with self.assertRaisesRegex(MrlError, "enum match requires"):
            compile_source("enum Color { Red } fn main() -> si { match (Color.Red) { Nope { return 1 } } }")


if __name__ == "__main__":
    unittest.main()
