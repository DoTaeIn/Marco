import subprocess
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path

from mrl.__main__ import main as cli_main
from mrl.c_backend import emit_c
from mrl.frontend import compile_source
from mrl.toolchain import build_c, find_compiler


def _compiler():
    return find_compiler()


def _build(compiler, uses_cmd, c_file, exe):
    build_c(c_file, exe)


def program(body, functions=None):
    return {"version": 1, "functions": (functions or []) + [{"name": "main", "params": [], "return_type": "si32", "body": body}]}


def literal(value): return {"kind": "literal", "type": "si32", "value": value}
def binary(op, left, right): return {"kind": "binary", "type": "si32", "op": op, "left": left, "right": right}
def boolean(value): return {"kind": "literal", "type": "b", "value": value}


class BackendTests(unittest.TestCase):
    def test_emits_checked_arithmetic_and_int_min(self):
        code = emit_c(program([{"kind": "return", "value": binary("+", literal(-(2**31)), literal(1))}]))
        self.assertIn("mrl_add", code)
        self.assertIn("INT32_MIN", code)
        self.assertIn("int64_t r", code)

    def test_rejects_bad_ir_and_immutable_assignment(self):
        ir = program([
            {"kind": "let", "name": "x", "type": "si32", "mutable": False, "value": literal(1)},
            {"kind": "assign", "name": "x", "value": literal(2)},
            {"kind": "return", "value": literal(0)},
        ])
        with self.assertRaisesRegex(ValueError, "immutable"):
            emit_c(ir)
        with self.assertRaisesRegex(ValueError, "main"):
            emit_c({"version": 1, "functions": []})

    def test_rejects_malformed_boundary_values(self):
        cases = [
            program([{ "kind": [] }]),
            program([{ "kind": "return", "value": [] }]),
            {"version": True, "functions": []},
            program([{"kind": "return", "value": {"kind": "literal", "type": None, "value": 1}}]),
            program([{"kind": "return", "value": {"kind": "binary", "type": "b", "op": [], "left": literal(1), "right": literal(1)}}]),
            program([{"kind": "return", "value": {"kind": "literal", "type": [], "value": 1}}]),
        ]
        for ir in cases:
            with self.subTest(ir=ir):
                with self.assertRaises(ValueError):
                    emit_c(ir)

    def test_v2_rejects_bad_scopes_conditions_and_unvalidated_else(self):
        base = {"version": 2, "functions": [{"name": "main", "params": [], "return_type": "si32", "body": []}]}
        cases = [
            [{"kind": "if", "condition": literal(1), "then": [{"kind": "return", "value": literal(1)}], "else": [{"kind": "return", "value": literal(2)}]}],
            [{"kind": "if", "condition": boolean(True), "then": [], "else": [{"kind": "assign", "name": "missing", "value": literal(1)}]}],
            [{"kind": "for", "name": "i", "start": literal(0), "stop": boolean(True), "body": []}, {"kind": "return", "value": literal(0)}],
            [{"kind": "for", "name": "i", "start": literal(0), "stop": literal(1), "body": [{"kind": "assign", "name": "i", "value": literal(1)}]}, {"kind": "return", "value": literal(0)}],
        ]
        for body in cases:
            ir = {"version": base["version"], "functions": [{**base["functions"][0], "body": body}]}
            with self.subTest(body=body), self.assertRaises(ValueError):
                emit_c(ir)

    def test_cli_requires_mrl_and_never_overwrites_source(self):
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            text_file, source = directory / "input.txt", directory / "input.mrl"
            text_file.write_text("ignored", encoding="utf-8")
            source.write_text("fn main() -> si { return 0 }", encoding="utf-8")
            errors = StringIO()
            with redirect_stderr(errors):
                self.assertEqual(cli_main([str(text_file), "-o", str(directory / "out.c")]), 1)
                self.assertEqual(cli_main([str(source), "-o", str(source)]), 1)
            self.assertIn(".mrl", errors.getvalue())
            self.assertIn("overwrite", errors.getvalue())

    def test_native_smoke_and_overflow_when_compiler_exists(self):
        compiler, uses_cmd = _compiler()
        if compiler is None:
            self.skipTest("no complete C11 toolchain found")
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory); c_file, exe = directory / "main.c", directory / "main.exe"
            source = (Path(__file__).parents[1] / "examples" / "primitive.mrl").read_text(encoding="utf-8")
            c_file.write_text(emit_c(compile_source(source)), encoding="utf-8")
            _build(compiler, uses_cmd, c_file, exe)
            result = subprocess.run([str(exe)], check=True, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.stdout, "42\n")
            c_file.write_text(emit_c(program([{"kind": "return", "value": binary("+", literal(2**31 - 1), literal(1))}])), encoding="utf-8")
            _build(compiler, uses_cmd, c_file, exe)
            result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("overflow", result.stderr)
