import copy
import unittest

from marco.reasoning import graph_vm


def program(expr):
    return {
        "schema": graph_vm.PROGRAM_SCHEMA,
        "entry": "r",
        "nodes": [{"id": "r", "op": "return", "value": expr}],
    }


def lit(value):
    return {"literal": value}


def comp(op, *args):
    return {"compute": {"op": op, "args": list(args)}}


class ValueExpressionTests(unittest.TestCase):
    def run_expr(self, expr, inputs=None, budget=4096):
        return graph_vm.run(program(expr), {} if inputs is None else inputs,
                            budget=budget)

    def assertValue(self, expr, expected, inputs=None):
        result = self.run_expr(expr, inputs)
        self.assertEqual(result["status"], "completed", result)
        self.assertEqual(result["value"], expected)

    def assertInvalid(self, expr, inputs=None):
        result = self.run_expr(expr, inputs)
        self.assertEqual(result["status"], "invalid", result)
        self.assertIsNone(result["value"])
        return result

    def test_nested_object_array_compute(self):
        expr = {"object": {
            "parts": comp("split", {"input": ["text"]}, lit(",")),
            "count": comp("len", comp("split", {"input": ["text"]}, lit(","))),
            "list": {"array": [lit(1), comp("add", lit(2), lit(3)), {"object": {}}, {"array": []}]},
        }}
        self.assertValue(expr, {"parts": ["a", "b", ""], "count": 3,
                                "list": [1, 5, {}, []]}, {"text": "a,b,"})

    def test_set_binding_then_var(self):
        prog = {
            "schema": graph_vm.PROGRAM_SCHEMA,
            "entry": "s",
            "nodes": [
                {"id": "s", "op": "set", "name": "x",
                 "value": {"object": {"k": comp("concat", lit("a"), lit("b"))}}, "next": "r"},
                {"id": "r", "op": "return", "value": comp("get", {"var": ["x"]}, lit("k"))},
            ],
        }
        result = graph_vm.run(prog, {})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["value"], "ab")

    def test_unicode_codepoints(self):
        text = "\u00e9\U0001F600,\u00fc,,x"
        self.assertValue(comp("split", lit(text), lit(",")),
                         ["\u00e9\U0001F600", "\u00fc", "", "x"])
        self.assertValue(comp("find", lit(text), lit("\u00fc")), 3)
        self.assertValue(comp("find", lit(text), lit("z")), -1)
        self.assertValue(comp("slice", lit(text), lit(1), lit(2)), "\U0001F600")
        self.assertValue(comp("len", lit(text)), 7)
        self.assertValue(comp("concat", lit("e\u0301"), lit(" "), lit("\u00e9")),
                         "e\u0301 \u00e9")
        self.assertValue(comp("slice", lit("abc"), lit(3), lit(3)), "")

    def test_get(self):
        self.assertValue(comp("get", lit(["a", "b"]), lit(1)), "b")
        self.assertValue(comp("get", lit({"k": [1]}), lit("k")), [1])
        self.assertInvalid(comp("get", lit({"k": 1}), lit("m")))
        self.assertInvalid(comp("get", lit([1]), lit(1)))
        self.assertInvalid(comp("get", lit([1]), lit(-1)))
        self.assertInvalid(comp("get", lit("abc"), lit(0)))
        self.assertInvalid(comp("get", lit([1, 2]), lit(True)))
        self.assertInvalid(comp("get", lit({"0": 1}), lit(0)))

    def test_exact_types(self):
        self.assertValue(comp("add", lit(2), lit(-5)), -3)
        self.assertInvalid(comp("add", lit(True), lit(1)))
        self.assertInvalid(comp("add", lit(1.5), lit(1)))
        self.assertInvalid(comp("add", lit("1"), lit(1)))
        self.assertInvalid(comp("concat", lit("a"), lit(1)))
        self.assertInvalid(comp("len", lit(5)))
        self.assertInvalid(comp("slice", lit("abc"), lit(False), lit(1)))
        self.assertInvalid(comp("slice", lit("abc"), lit(2), lit(1)))
        self.assertInvalid(comp("slice", lit("abc"), lit(0), lit(4)))
        self.assertInvalid(comp("slice", lit("abc"), lit(-1), lit(1)))
        self.assertInvalid(comp("split", lit("a"), lit("")))
        self.assertInvalid(comp("find", lit("a"), lit("")))

    def test_malformed_compute_rejected_before_execution(self):
        for expr in (
            comp("eval", lit("x")),
            comp("add", lit(1)),
            comp("len", lit("a"), lit("b")),
            comp("concat"),
            {"compute": {"op": "len", "args": [lit("a")], "extra": 1}},
            {"compute": {"op": "len"}},
            {"compute": {"op": "len", "args": lit("a")}},
            {"array": {"x": lit(1)}},
            {"object": [lit(1)]},
            {"array": [{"bogus": 1}]},
            {"object": {"k": comp("nope")}},
        ):
            result = self.assertInvalid(expr)
            self.assertEqual(result["used"], 0)
        self.assertInvalid(comp("concat", *[lit("a")] * 257))

    def test_literal_is_inert(self):
        data = {"compute": {"op": "eval", "args": []}}
        self.assertValue(lit(data), data)

    def test_no_mutation_or_aliasing(self):
        inputs = {"d": {"k": [1, {"z": 2}]}}
        snapshot = copy.deepcopy(inputs)
        expr = {"array": [comp("get", {"input": ["d"]}, lit("k")),
                          comp("get", {"input": ["d"]}, lit("k"))]}
        result = self.run_expr(expr, inputs)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(inputs, snapshot)
        first, second = result["value"]
        self.assertIsNot(first, second)
        first[1]["z"] = 99
        self.assertEqual(second[1]["z"], 2)
        self.assertEqual(inputs, snapshot)

    def test_split_piece_limit(self):
        ok = self.run_expr(comp("split", lit("," * 255), lit(",")))
        self.assertEqual(ok["status"], "completed")
        self.assertEqual(len(ok["value"]), 256)
        self.assertInvalid(comp("split", lit("," * 256), lit(",")))
        self.assertInvalid(comp("split", lit("," * 5000), lit(",")))

    def test_output_and_aggregate_limits(self):
        inputs = {"s": "a" * 70000}
        ref = {"input": ["s"]}
        self.assertInvalid(comp("concat", ref, ref), inputs)
        self.assertInvalid({"array": [ref, ref]}, inputs)
        self.assertInvalid({"object": {"a": ref, "b": ref}}, inputs)

    def test_shared_low_budget(self):
        expr = {"array": [comp("concat", lit("a"), lit("b")),
                          comp("len", lit("x" * 1000))]}
        full = self.run_expr(expr)
        self.assertEqual(full["status"], "completed")
        for budget in range(1, full["used"]):
            result = self.run_expr(expr, budget=budget)
            self.assertEqual(result["status"], "capacity")
            self.assertIsNone(result["value"])
            self.assertEqual(result["used"], budget)
        exact = self.run_expr(expr, budget=full["used"])
        self.assertEqual(exact, full)

    def test_legacy_program_unchanged(self):
        result = self.run_expr({"input": ["a", 0]}, {"a": [7]})
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["value"], 7)
        self.assertEqual(result["used"], 1)


if __name__ == "__main__":
    unittest.main()
