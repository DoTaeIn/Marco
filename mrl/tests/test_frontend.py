import unittest

from mrl.frontend import MrlError, compile_source, parse


class FrontendTests(unittest.TestCase):
    def test_ast_then_checked_ir_with_forward_call_and_precedence(self):
        source = """
# paired comment #
fn main() -> si {
  x = add(20, 22)
  dec limit = 100
  x := x + (limit * 0)
  return x
}
fn add(a: si32, b: si) -> si32 {
  return a + b
}
"""
        ast = parse(source)
        self.assertEqual(ast.functions[0].name, "main")
        ir = compile_source(source)
        self.assertEqual(ir["version"], 2)
        self.assertEqual(ir["functions"][0]["body"][-1]["value"]["type"], "si32")
        self.assertEqual(ir["functions"][1]["params"][0]["type"], "si32")

    def test_boolean_comparison_void_call_and_signed_minimum(self):
        ir = compile_source("""
fn note(value: si) { return }
fn main() -> si {
  x = -2147483648
  ok = x < 0
  note(x)
  return x + 2147483647 * 0
}
""")
        body = ir["functions"][1]["body"]
        self.assertEqual(body[0]["value"]["value"], -2147483648)
        self.assertEqual(body[1]["type"], "b")
        self.assertIsNone(body[2]["value"]["type"])

    def test_semantic_failures_are_located(self):
        cases = [
            "fn main() -> si { return 1 return 2 }",
            "fn main() -> si { return " + "9" * 5000 + " }",
            "fn main() -> si { return 2147483648 }",
            "fn main() -> si { return -2147483649 }",
            "fn main() -> si { dec x = 1 x := 2 return x }",
            "fn main() -> si { x = 1 x = 2 return x }",
            "fn main() -> si { x = 1 x := true return x }",
            "fn main() -> si { return missing }",
            "fn main() -> si { return later() } fn later(x: si) -> si { return x }",
            "fn main() -> si { return later(true) } fn later(x: si) -> si { return x }",
            "fn main() -> si { x = log() return x } fn log() { return }",
            "fn main() -> si { x = 1 }",
            "fn main() -> si { if = 1 return if }",
            "fn main() -> si { return ² }",
        ]
        for source in cases:
            with self.subTest(source=source), self.assertRaisesRegex(MrlError, r"^\d+:\d+:"):
                compile_source(source)

    def test_control_flow_scopes_and_definite_returns(self):
        ir = compile_source("""
fn count(n: si) -> si {
  total = 0
  for (i in 0..n) {
    if (i < 3) { total := total + i } else { total := total + 1 }
  }
  while (total < 10) { total := total + 1 }
  if (n == 0) { return total } else { return total + 1 }
}
fn main() -> si { return count(5) }
""")
        body = ir["functions"][0]["body"]
        self.assertEqual(ir["version"], 2)
        self.assertEqual(body[1]["kind"], "for")
        self.assertFalse(body[1]["body"][0]["else"] == [])
        self.assertEqual(body[2]["kind"], "while")
        self.assertEqual(body[3]["kind"], "if")

    def test_empty_and_descending_ranges_preserve_once_evaluated_bounds(self):
        ir = compile_source("""
fn main() -> si {
  total = 0
  for (i in 3..3) { total := total + i }
  for (j in 4..2) { total := total + j }
  return total
}
""")
        first, second = ir["functions"][0]["body"][1:3]
        self.assertEqual((first["start"]["value"], first["stop"]["value"]), (3, 3))
        self.assertEqual((second["start"]["value"], second["stop"]["value"]), (4, 2))

    def test_control_flow_failures_are_located(self):
        cases = [
            "fn main() -> si { if true { return 1 } else { return 2 } }",
            "fn main() -> si { if (1) { return 1 } else { return 2 } }",
            "fn main() -> si { while (1) { } return 0 }",
            "fn main() -> si { for (i in true..2) { } return 0 }",
            "fn main() -> si { for (i in 0..2) { i := 1 } return 0 }",
            "fn main() -> si { x = 1 if (true) { x = 2 } return x }",
            "fn main() -> si { if (true) { x = 1 } return x }",
            "fn main() -> si { if (true) { return 1 } }",
            "fn main() -> si { while (true) { return 1 } }",
            "fn main() -> si { if (true) { return 1 } else { return 2 } return 3 }",
        ]
        for source in cases:
            with self.subTest(source=source), self.assertRaisesRegex(MrlError, r"^\d+:\d+:"):
                compile_source(source)


if __name__ == "__main__":
    unittest.main()
