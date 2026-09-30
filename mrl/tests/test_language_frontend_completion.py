import unittest

from mrl.frontend import MrlError, compile_source


class FrontendCompletionTests(unittest.TestCase):
    def test_io_calls_lower_to_neutral_nodes(self):
        ir = compile_source('fn main() -> si { code = argc() path = argv(code) return code }')
        values = [row["value"] for row in ir["functions"][0]["body"] if row["kind"] == "let"]
        self.assertEqual((values[0]["kind"], values[0]["operation"], values[1]["type"]), ("io_call", "argc", "result:s:s"))

    def test_unsafe_scope_and_extern_are_preserved(self):
        ir = compile_source('''
            extern fn c_abs(value: si) -> si = "abs"
            fn main() -> si {
                value: si = -4
                unsafe { pointer: ptr<si> = addr(value) result = c_abs(value) store(pointer, 7) }
                return value
            }
        ''')
        self.assertEqual(ir["externs"][0]["symbol"], "abs")
        unsafe = ir["functions"][0]["body"][1]
        self.assertEqual(unsafe["kind"], "unsafe")
        self.assertEqual([row["value"]["kind"] for row in unsafe["body"][:2]], ["ffi_addr", "ffi_call"])

    def test_generic_map_keys_and_alias_and_qualified_enum_fallback(self):
        ir = compile_source('''
            enum State { Known Unknown }
            fn main() -> si {
                values: map<ui32, s> = Map()
                values.set(1, "ready")
                state: State = State.Known
                match (state) { State.Known { return values.len } _ { return 0 } }
            }
        ''')
        body = ir["functions"][0]["body"]
        self.assertEqual(body[0]["type"], "map:ui32:s")
        self.assertEqual(body[1]["value"]["kind"], "map_set")
        self.assertEqual(body[3]["kind"], "match_enum")

    def test_epistemic_state_is_a_closed_builtin_enum(self):
        ir = compile_source('''
            fn main() -> si {
                state: EpistemicState = EpistemicState.known
                match (state) { known { return 1 } unknown { return 2 } ambiguous { return 3 } contradicted { return 4 } withdrawn { return 5 } incomplete { return 6 } }
            }
        ''')
        self.assertEqual(ir["functions"][0]["body"][0]["type"], "enum:EpistemicState")

    def test_foreign_calls_require_unsafe_scope(self):
        with self.assertRaisesRegex(MrlError, "unsafe"):
            compile_source('extern fn c_abs(value: si) -> si = "abs" fn main() -> si { return c_abs(1) }')

    def test_unsafe_float_pointer_is_admitted(self):
        ir = compile_source('fn main() -> si { value: f32 = 1.0 unsafe { pointer: ptr<f32> = addr(value) store(pointer, 2.0) } return 0 }')
        self.assertEqual(ir["functions"][0]["body"][1]["body"][0]["type"], "ptr:f32")


if __name__ == "__main__":
    unittest.main()
