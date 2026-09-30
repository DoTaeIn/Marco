import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
APP = ROOT / "examples" / "language_app" / "main.mrl"
ENV = {**os.environ, "PYTHONPATH": str(ROOT.parent) + os.pathsep + os.environ.get("PYTHONPATH", "")}


class LanguageAppE2ETests(unittest.TestCase):
    maxDiff = None
    def test_write_and_fresh_process_restore_from_relative_caller_paths(self):
        with tempfile.TemporaryDirectory(prefix="mrl-language-app-") as directory:
            cwd = Path(directory)
            (cwd / "input.txt").write_text("안녕🙂", encoding="utf-8")
            write = subprocess.run([sys.executable, "-m", "mrl", "run", str(APP), "--", "write", "input.txt", "state.mrlk"],
                                   cwd=cwd, env=ENV, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual((write.returncode, write.stderr), (0, ""), write.stdout)
            self.assertEqual(write.stdout.splitlines(), ["안녕🙂", "contains_to_known", "input", "write-ok", "0"])
            self.assertTrue((cwd / "state.mrlk").is_file())
            restore = subprocess.run([sys.executable, "-m", "mrl", "run", str(APP), "--", "restore", "unused", "state.mrlk"],
                                     cwd=cwd, env=ENV, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual((restore.returncode, restore.stderr), (0, ""), restore.stdout)
            self.assertEqual(restore.stdout.splitlines(), ["안녕🙂", "payload", "restore-ok", "0"])
            self.assertFalse((ROOT / "state.mrlk").exists())

    def test_source_ffi_abs_and_pointer_program(self):
        source = '''extern fn c_abs(value: si) -> si = "abs"
fn main() -> si {
    value: si = -9
    unsafe {
        pointer = addr(value)
        store(pointer, 4)
        return c_abs(load(pointer))
    }
}
'''
        with tempfile.TemporaryDirectory(prefix="mrl-source-ffi-") as directory:
            source_file = Path(directory) / "ffi.mrl"
            source_file.write_text(source, encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "mrl", "run", str(source_file)],
                                    cwd=directory, env=ENV, capture_output=True, text=True, encoding="utf-8", timeout=30)
            self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "4\n", ""))


if __name__ == "__main__":
    unittest.main()
