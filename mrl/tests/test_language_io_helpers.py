import unittest

from mrl.language_io import emit_io, lower_io_call, validate_io


class LanguageIoLoweringTests(unittest.TestCase):
    def _call(self, name, values):
        token = type("Token", (), {"line": 4, "column": 7})()
        return ("call", token, ("name", token, name), [(None, value) for value in values])

    def _literal(self, typ, value):
        token = type("Token", (), {"line": 4, "column": 8})()
        return ("literal", token, value)

    def test_lower_and_validate_io_signatures(self):
        lower = lower_io_call(self._call("argv", [self._literal("si32", 1)]),
                              lambda node, env: {"kind": "literal", "type": "si32", "value": 1}, {},
                              lambda token, message: (_ for _ in ()).throw(AssertionError(message)))
        self.assertEqual(lower["kind"], "io_call")
        self.assertEqual(lower["type"], "result:s:s")
        self.assertEqual(validate_io(lower, lambda value: value["type"], self.fail), "result:s:s")

    def test_lower_rejects_wrong_argument_type_and_named_arguments(self):
        errors = []
        bad = self._call("read_text", [self._literal("si32", 1)])
        lower_io_call(bad, lambda node, env: {"type": "si32"}, {}, lambda token, message: errors.append(message))
        self.assertIn("must be s", errors[-1])
        named = ("call", bad[1], bad[2], [(type("Field", (), {"text": "path"})(), bad[3][0][1])])
        lower_io_call(named, lambda node, env: {"type": "s"}, {}, lambda token, message: errors.append(message))
        self.assertIn("positional", errors[-1])

    def test_emit_uses_native_abi_and_owned_result(self):
        lines, names, owned = [], iter(("mrl_io_0", "mrl_io_error_1")), []
        node = {"kind": "io_call", "type": "result:si32:s", "operation": "write_text",
                "args": [{"kind": "literal", "type": "s", "value": "out"},
                         {"kind": "literal", "type": "s", "value": "text"}]}
        result = emit_io(node, lambda value, indent: "mrl_arg", lambda typ: "MrlResult_si32_s",
                         lambda text, indent: lines.append(text), lambda prefix: next(names),
                         lambda typ, value: owned.append((typ, value)) or value)
        self.assertEqual(result, "mrl_io_0")
        self.assertEqual(owned, [("result:si32:s", "mrl_io_0")])
        self.assertTrue(any("mrl_io_write_utf8" in line for line in lines))
        self.assertTrue(any("strlen(mrl_arg)" in line for line in lines))

    def test_emit_wraps_native_owned_string_result(self):
        lines, names = [], iter(("mrl_io_0", "mrl_io_raw_1"))
        node = {"kind": "io_call", "type": "result:s:s", "operation": "read_text",
                "args": [{"kind": "literal", "type": "s", "value": "input"}]}
        emit_io(node, lambda value, indent: "mrl_path", lambda typ: "MrlResult_s_s",
                lambda text, indent: lines.append(text), lambda prefix: next(names),
                lambda typ, value: value)
        self.assertTrue(any("MrlIoStringResult mrl_io_raw_1" in line for line in lines))
        self.assertTrue(any("value_owned = mrl_io_raw_1.ok" in line for line in lines))


if __name__ == "__main__":
    unittest.main()
