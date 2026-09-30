import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from mrl.__main__ import _load_source, main


class ModuleDiagnosticTests(unittest.TestCase):
 def run_cli(self, source):
  errors = StringIO()
  with redirect_stderr(errors):
   result = main([str(source), "-o", str(source.with_suffix(".c"))])
  return result, errors.getvalue()

 def test_imported_source_diagnostic_keeps_original_file_and_line(self):
  with tempfile.TemporaryDirectory(prefix="mrl-module-error-") as directory:
   root = Path(directory); library = root / "library.mrl"; source = root / "main.mrl"
   library.write_text("\nfn broken() -> si { return @ }\n", encoding="utf-8")
   source.write_text('import "library.mrl"\nfn main() -> si { return broken() }\n', encoding="utf-8")
   result, error = self.run_cli(source)
   self.assertEqual(result, 1)
   self.assertIn(f"{library.resolve()}:2:28: unsupported character '@'", error)

 def test_diamond_import_emits_shared_module_once(self):
  with tempfile.TemporaryDirectory(prefix="mrl-module-diamond-") as directory:
   root = Path(directory); shared = root / "shared.mrl"; source = root / "main.mrl"
   shared.write_text("fn one() -> si { return 1 }\n", encoding="utf-8")
   (root / "left.mrl").write_text('import "shared.mrl"\nfn left() -> si { return one() }\n', encoding="utf-8")
   (root / "right.mrl").write_text('import "shared.mrl"\nfn right() -> si { return one() }\n', encoding="utf-8")
   source.write_text('import "left.mrl"\nimport "right.mrl"\nfn main() -> si { return left() + right() }\n', encoding="utf-8")
   text = _load_source(source)
   self.assertEqual(text.count("fn one"), 1)
   self.assertEqual(self.run_cli(source)[0], 0)

 def test_cycle_and_invalid_import_are_readable(self):
  with tempfile.TemporaryDirectory(prefix="mrl-module-cycle-") as directory:
   root = Path(directory); first = root / "first.mrl"; second = root / "second.mrl"
   first.write_text('import "second.mrl"\n', encoding="utf-8")
   second.write_text('import "first.mrl"\n', encoding="utf-8")
   result, error = self.run_cli(first)
   self.assertEqual(result, 1)
   self.assertIn("cyclic module import:", error)
   self.assertIn("first.mrl", error)
   self.assertIn("second.mrl", error)
   first.write_text('import "/not-relative.mrl"\n', encoding="utf-8")
   result, error = self.run_cli(first)
   self.assertEqual(result, 1)
   self.assertIn("invalid module import", error)


if __name__ == "__main__":
 unittest.main()
