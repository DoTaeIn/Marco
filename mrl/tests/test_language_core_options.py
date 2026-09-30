import subprocess
import tempfile
import unittest
from pathlib import Path

from mrl.c_backend import emit_c
from mrl.frontend import MrlError, compile_source
from mrl.toolchain import build_c


def run(source):
    with tempfile.TemporaryDirectory(prefix="mrl-option-") as folder:
        c, exe = Path(folder) / "x.c", Path(folder) / "x.exe"
        c.write_text(emit_c(compile_source(source)), encoding="utf-8")
        build_c(c, exe)
        return subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)


class OptionalTests(unittest.TestCase):
    def test_some_none_managed_string_and_struct_payloads(self):
        result = run('''
struct Note { text: s }
fn size(value: Note?) -> si { match (value) { Some(note) { return note.text.len } none { return 0 } } }
fn main() -> si { value: Note? = Some(Note(text="hello")) return size(value) }''')
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, ["5"]))

    def test_optional_result_payload_and_diagnostics(self):
        result = run('''
fn pick(value: Result<s, s>?) -> si { match (value) { Some(result) { match (result) { Ok(text) { return text.len } Err(error) { return error.len } } } none { return 0 } } }
fn main() -> si { value: Result<s, s>? = Some(Ok("ok")) return pick(value) }''')
        self.assertEqual((result.returncode, result.stdout.splitlines()), (0, ["2"]))
        with self.assertRaisesRegex(MrlError, "exactly Some and none"):
            compile_source("fn main() -> si { x: si? = none match (x) { Some(v) { return v } } }")
        with self.assertRaisesRegex(MrlError, "requires an optional annotation"):
            compile_source("fn main() -> si { x = Some(1) return x }")


if __name__ == "__main__":
    unittest.main()
