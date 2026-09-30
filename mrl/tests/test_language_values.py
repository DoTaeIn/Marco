import subprocess
import tempfile
import unittest
from pathlib import Path

from mrl.c_backend import emit_c
from mrl.frontend import compile_source
from mrl.toolchain import build_c


class LanguageValuesTests(unittest.TestCase):
    def test_raw_ffi_call_requires_an_unsafe_block(self):
        ir = {"version": 6, "structs": [], "enums": [], "relations": [], "graphs": [],
              "externs": [{"name": "c_abs", "params": [{"name": "value", "type": "si32"}], "return_type": "si32", "symbol": "abs"}],
              "functions": [{"name": "main", "params": [], "return_type": "si32", "body": [{"kind": "return", "value": {"kind": "ffi_call", "type": "si32", "name": "c_abs", "symbol": "abs", "args": [{"kind": "literal", "type": "si32", "value": 1}], "unsafe": True}}]}]}
        with self.assertRaisesRegex(ValueError, "unsafe block"):
            emit_c(ir)

    def test_managed_records_and_integer_map_keys_survive_iteration(self):
        source = '''
            struct Row { label: s }
            fn main() -> si {
                rows: list<Row> = [Row(label="a"), Row(label="bb")]
                words: list<s> = ["x"]
                labels: map<ui32,s> = Map()
                labels.set(7, "ok")
                fixed: arr<Row,2> = [Row(label="a"), Row(label="b")]
                fixed := [Row(label="c"), Row(label="d")]
                total: si = 0
                for (row in rows) { total := total + row.label.len }
                for (word in words) { total := total + word.len }
                for (key in labels) { total := total + 1 }
                match (labels.get(7)) { Ok(text) { total := total + text.len } Err(error) { return 99 } }
                return total + labels.len + fixed.len
            }
        '''
        with tempfile.TemporaryDirectory(prefix="mrl-language-values-") as directory:
            root = Path(directory)
            c_file, executable = root / "values.c", root / "values.exe"
            c_file.write_text(emit_c(compile_source(source)), encoding="utf-8")
            build_c(c_file, executable)
            run = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
        self.assertEqual((run.returncode, run.stdout.splitlines()), (0, ["10"]))


if __name__ == "__main__":
    unittest.main()
