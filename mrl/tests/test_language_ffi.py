import subprocess
import tempfile
import unittest
from pathlib import Path

from mrl.language_ffi import emit_ffi, lower_extern, lower_ffi_call, parse_extern, validate_extern, validate_ffi
from mrl.toolchain import build_c, find_compiler


class _Token:
    def __init__(self, kind, text):
        self.kind, self.text, self.line, self.column = kind, text, 1, 1


class _Parser:
    def __init__(self, tokens):
        self.tokens, self.index = tokens, 0

    def cur(self):
        return self.tokens[self.index]

    def take(self, kind):
        token = self.cur()
        if token.kind != kind:
            raise AssertionError((kind, token.kind))
        self.index += 1
        return token

    def match(self, kind):
        return self.take(kind) if self.cur().kind == kind else None

    def typ(self):
        value = self.take("name").text
        return "si32" if value == "si" else value


class LanguageFfiTests(unittest.TestCase):
    def test_parse_and_validate_extern_keeps_c_symbol(self):
        tokens = [_Token(kind, text) for kind, text in (
            ("extern", "extern"), ("fn", "fn"), ("name", "c_abs"), ("(", "("),
            ("name", "value"), (":", ":"), ("name", "si"), (")", ")"),
            ("->", "->"), ("name", "si"), ("=", "="), ("string", "abs"),
        )]
        declaration = parse_extern(_Parser(tokens))
        self.assertEqual(declaration["name"].text, "c_abs")
        self.assertEqual(declaration["symbol"], "abs")
        neutral = lower_extern(declaration)
        self.assertTrue(validate_extern(neutral, self.fail))
        tokens[-1] = _Token("string", "bad-symbol")
        with self.assertRaises(ValueError):
            parse_extern(_Parser(tokens))

    def test_lower_and_raw_validate_require_unsafe(self):
        token = _Token("name", "x")
        name = ("name", token, "x")
        call = ("call", token, ("name", token, "c_abs"), [(None, name)])
        env = {"x": ("si32", True), "$externs": {"c_abs": {"name": "c_abs", "params": [{"name": "value", "type": "si32"}], "return_type": "si32", "symbol": "abs"}}}
        errors = []
        lower_ffi_call(call, lambda value, scope: {"kind": "name", "type": "si32", "name": "x"}, env,
                       lambda where, message: errors.append(message))
        self.assertIn("unsafe", errors[-1])
        lowered = lower_ffi_call(call, lambda value, scope: {"kind": "name", "type": "si32", "name": "x"}, env,
                                 lambda where, message: self.fail(message), unsafe=True)
        self.assertEqual(lowered["symbol"], "abs")
        self.assertEqual(validate_ffi(lowered, lambda value: value["type"], self.fail, env["$externs"], unsafe=True), "si32")
        self.assertIsNone(validate_ffi(lowered, lambda value: value["type"], errors.append, env["$externs"]))
        self.assertIn("unsafe", errors[-1])

    def test_immutable_addr_is_rejected(self):
        token = _Token("name", "x")
        node = ("call", token, ("name", token, "addr"), [(None, ("name", token, "x"))])
        errors = []
        lower_ffi_call(node, lambda value, scope: {"type": "si32"}, {"x": ("si32", False)},
                       lambda where, message: errors.append(message), unsafe=True)
        self.assertIn("mutable", errors[-1])

    @unittest.skipUnless(find_compiler()[0], "no C11 compiler")
    def test_native_abs_and_local_pointer_load_store(self):
        with tempfile.TemporaryDirectory(prefix="mrl-ffi-") as directory:
            root = Path(directory)
            lines = []
            names = iter(("ptr", "loaded", "foreign"))
            ctype = lambda typ: "int32_t *" if typ == "ptr:si32" else "int32_t"
            add = lambda text, indent=0: lines.append("    " * indent + text)
            fresh = lambda prefix: next(names)
            own = lambda typ, value: value
            addr = {"kind": "ffi_addr", "type": "ptr:si32", "name": "value", "unsafe": True}
            pointer = emit_ffi(addr, lambda value, indent: "value", ctype, add, fresh, own)
            load = {"kind": "ffi_load", "type": "si32", "pointer": {"kind": "name", "type": "ptr:si32"}, "unsafe": True}
            loaded = emit_ffi(load, lambda value, indent: pointer, ctype, add, fresh, own)
            store = {"kind": "ffi_store", "type": None, "pointer": {"kind": "name", "type": "ptr:si32"},
                     "value": {"kind": "literal", "type": "si32", "value": 4}, "unsafe": True}
            emit_ffi(store, lambda value, indent: pointer if value is store["pointer"] else "4", ctype, add, fresh, own)
            foreign = {"kind": "ffi_call", "type": "si32", "name": "c_abs", "symbol": "abs",
                       "args": [{"kind": "name", "type": "si32"}], "unsafe": True}
            result = emit_ffi(foreign, lambda value, indent: loaded, ctype, add, fresh, own)
            source = "#include <stdint.h>\n#include <stdlib.h>\nint main(void) { int32_t value = -9;\n" + "\n".join(lines) + f"\nreturn {result} == 9 && value == 4 ? 0 : 1; }}\n"
            c_file, executable = root / "ffi.c", root / "ffi.exe"
            c_file.write_text(source, encoding="utf-8")
            build_c(c_file, executable)
            completed = subprocess.run([str(executable)], capture_output=True)
            self.assertEqual(completed.returncode, 0, completed.stderr.decode(errors="replace"))


if __name__ == "__main__":
    unittest.main()
