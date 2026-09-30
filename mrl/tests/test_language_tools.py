import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest import mock

from mrl.__main__ import _load_source, _source_and_c, main


class LanguageToolTests(unittest.TestCase):
    def _source(self, root, text, name="main.mrl"):
        path = root / name
        path.write_text(text, encoding="utf-8")
        return path

    def test_alias_qualification_is_token_aware_and_deduplicated(self):
        with tempfile.TemporaryDirectory(prefix="mrl-tools-") as directory:
            root = Path(directory)
            self._source(root, 'fn add(x: si) -> si { return x + 1 }\nfn phrase() -> s { return "lib.add" }\n', "lib.mrl")
            source = self._source(root, 'import "lib.mrl" as lib\nimport "lib.mrl" as lib\nfn main() -> si { return lib.add(4) }\n')
            expanded = _load_source(source)
            self.assertEqual(expanded.count("fn lib__add"), 1)
            self.assertIn('"lib.add"', expanded)
            self.assertIn("lib__add(4)", expanded)

    def test_paired_comments_and_local_fields_are_not_rewritten(self):
        with tempfile.TemporaryDirectory(prefix="mrl-tools-") as directory:
            root = Path(directory)
            self._source(root, 'fn helper() -> si { return 1 }\nfn fake() -> si { return 2 }\n', "a.mrl")
            self._source(root, 'fn helper() -> si { return 3 }\nfn fake() -> si { return 4 }\n', "b.mrl")
            source = self._source(root, '#\nimport "b.mrl" as hidden\n#\nimport "a.mrl" as left\nimport "b.mrl" as right\nstruct record { helper: si }\nfn main(helper: si) -> si { let fake: si = helper; return left.helper() + right.helper() + fake }\n')
            expanded = _load_source(source)
            self.assertNotIn("hidden__helper", expanded)
            self.assertIn("struct record { helper: si }", expanded)
            self.assertIn("left__helper() + right__helper() + fake", expanded)
            self.assertNotIn("left__fake: si", expanded)

    def test_module_function_local_can_shadow_imported_name(self):
        with tempfile.TemporaryDirectory(prefix="mrl-tools-") as directory:
            root = Path(directory)
            self._source(root, "fn value() -> si { return 1 }\nfn local() -> si { value = 9 return value }\n", "lib.mrl")
            source = self._source(root, 'import "lib.mrl" as lib\nfn main() -> si { return lib.local() }\n')
            expanded = _load_source(source)
            self.assertIn("fn lib__local()", expanded)
            self.assertIn("value = 9 return value", expanded)
            self.assertNotIn("lib__value = 9", expanded)
            _source_and_c(source)

    def test_output_cannot_replace_imported_module(self):
        with tempfile.TemporaryDirectory(prefix="mrl-tools-") as directory:
            root = Path(directory)
            library = self._source(root, "fn helper() -> si { return 1 }\n", "lib.mrl")
            source = self._source(root, 'import "lib.mrl"\nfn main() -> si { return helper() }\n')
            errors = StringIO()
            with redirect_stderr(errors):
                result = main([str(source), "-o", str(library)])
            self.assertEqual(result, 1)
            self.assertIn("refusing to overwrite", errors.getvalue())
            self.assertIn("helper", library.read_text(encoding="utf-8"))

    def test_check_and_legacy_compile(self):
        with tempfile.TemporaryDirectory(prefix="mrl-tools-") as directory:
            root = Path(directory)
            source = self._source(root, "fn main() -> si { return 0 }\n")
            output = root / "out.c"
            self.assertEqual(main(["check", str(source)]), 0)
            self.assertEqual(main([str(source), "-o", str(output)]), 0)
            self.assertIn("int main", output.read_text(encoding="utf-8"))

    @unittest.skipUnless(os.name == "nt", "native executable suffix check is Windows-specific")
    def test_run_returns_native_status(self):
        with tempfile.TemporaryDirectory(prefix="mrl-tools-") as directory:
            root = Path(directory)
            source = self._source(root, "fn main() -> si { return 7 }\n")
            self.assertEqual(main(["run", str(source)]), 0)

    def test_native_diagnostic_keeps_existing_output(self):
        with tempfile.TemporaryDirectory(prefix="mrl-tools-") as directory:
            root = Path(directory)
            source = self._source(root, "fn main() -> si { return 0 }\n")
            output = root / "program.exe"
            output.write_bytes(b"old")
            failure = subprocess.CalledProcessError(1, ["cc"], stderr=b"program.c:1: error: broken")
            with mock.patch("mrl.toolchain.build_c", side_effect=failure):
                errors = StringIO()
                with redirect_stderr(errors):
                    result = main(["build", str(source), "-o", str(output)])
            self.assertEqual(result, 1)
            self.assertEqual(output.read_bytes(), b"old")
            self.assertIn("broken", errors.getvalue())

    def test_run_forwards_argv_and_inherits_working_directory(self):
        with tempfile.TemporaryDirectory(prefix="mrl-tools-") as directory:
            source = self._source(Path(directory), "fn main() -> si { return 0 }\n")
            with mock.patch("mrl.toolchain.build_c"), mock.patch("mrl.__main__.subprocess.run", return_value=subprocess.CompletedProcess([], 7)) as run:
                self.assertEqual(main(["run", str(source), "--", "file name.json"]), 7)
            command, = run.call_args.args
            self.assertEqual(command[1:], ["file name.json"])
            self.assertNotIn("cwd", run.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
