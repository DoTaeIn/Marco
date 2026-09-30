import unittest

from mrl.frontend import MrlError, compile_source, lower, parse


SOURCE = '''
struct Concept { name: s }
relation Logic {
  Supports { polarity: positive evidence: optional traverse: forward }
  Proves { polarity: positive evidence: required traverse: both }
}
graph knowledge { node: Concept relation: Logic }
fn main() {
  a = knowledge.add(Concept(name = "apple"))
  b = knowledge.add(Concept(name = "fruit"))
  knowledge.add(a, b, Logic.Supports)
  result = knowledge.find(a, b) { relation in [Logic.Supports] depth <= 8 method: bfs }
  match (result) { Ok(path) { print(path.len) } Err(error) { print(error) } }
}
'''


class GraphFrontendTests(unittest.TestCase):
    def test_graph_source_lowers_to_frozen_v3_shapes(self):
        ir = compile_source(SOURCE)
        self.assertEqual(ir["version"], 3)
        self.assertEqual(ir["structs"][0]["fields"], [{"name": "name", "type": "s"}])
        self.assertEqual(ir["relations"][0]["members"][0]["traverse"], "forward")
        body = ir["functions"][0]["body"]
        self.assertEqual(body[0]["value"]["kind"], "graph_add_node")
        self.assertEqual(body[2]["value"]["kind"], "graph_add_edge")
        find = body[3]["value"]
        self.assertEqual((find["kind"], find["relations"], find["max_depth"], find["method"]), ("graph_find", ["Supports"], 8, "bfs"))
        self.assertEqual(body[4]["kind"], "match")
        self.assertEqual(body[4]["ok"][0]["value"]["kind"], "print")

    def test_required_evidence_and_cross_graph_handles_are_checked(self):
        required = SOURCE.replace("knowledge.add(a, b, Logic.Supports)", "knowledge.add(a, b, Logic.Proves)")
        with self.assertRaisesRegex(MrlError, "requires Evidence"):
            compile_source(required)
        cross = SOURCE.replace("graph knowledge { node: Concept relation: Logic }", "graph other { node: Concept relation: Logic }\ngraph knowledge { node: Concept relation: Logic }")
        cross = cross.replace("knowledge.add(a, b, Logic.Supports)", "other.add(a, b, Logic.Supports)")
        with self.assertRaisesRegex(MrlError, "another graph"):
            compile_source(cross)

    def test_literal_evidence_and_string_boundaries_are_checked(self):
        evidence = SOURCE.replace("knowledge.add(a, b, Logic.Supports)", 'knowledge.add(a, b, Logic.Proves, Evidence(source = "apple", start = 0, end = 5, text = "apple"))')
        self.assertEqual(compile_source(evidence)["functions"][0]["body"][2]["value"]["evidence"]["kind"], "evidence")
        for bad in ['fn main() { print("a' + "\0" + '") }', 'fn main() { print("' + chr(0xD800) + '") }']:
            with self.subTest(bad=bad), self.assertRaisesRegex(MrlError, "NUL or surrogate"):
                compile_source(bad)

    def test_string_len_and_equality_preserve_result_types(self):
        self.assertEqual(compile_source('struct S { text: s } graph g { node: S relation: R } relation R { X { polarity: neutral evidence: none traverse: forward } } fn main() { print("한글".len) }')["functions"][0]["body"][0]["value"]["value"]["kind"], "len")
        equality = compile_source('fn main() { print("a" == "a") }')
        self.assertEqual(equality["functions"][0]["body"][0]["value"]["value"]["type"], "b")
        with self.assertRaisesRegex(MrlError, "return"):
            compile_source('fn main() -> si { return "a" == "a" }')

    def test_constructor_ir_preserves_source_evaluation_order_and_match_binders_do_not_shadow(self):
        source = '''
struct Pair { a: si b: si }
fn mark(n: si) -> si { return n }
fn main() -> si { pair = Pair(b = mark(2), a = mark(1)) return pair.a }
'''
        fields = compile_source(source)["functions"][1]["body"][0]["value"]["fields"]
        self.assertEqual([field["name"] for field in fields], ["b", "a"])
        shadow = SOURCE.replace("Ok(path)", "Ok(result)")
        with self.assertRaisesRegex(MrlError, "cannot shadow"):
            compile_source(shadow)

    def test_omitted_relation_filter_means_all_members_but_empty_is_none(self):
        all_members = compile_source(SOURCE.replace("relation in [Logic.Supports] depth <= 8", "depth <= 8"))
        empty_members = compile_source(SOURCE.replace("[Logic.Supports]", "[]"))
        self.assertEqual(all_members["functions"][0]["body"][3]["value"]["relations"], ["Supports", "Proves"])
        self.assertEqual(empty_members["functions"][0]["body"][3]["value"]["relations"], [])

    def test_backend_graph_declaration_limits_fail_in_frontend(self):
        for key, count, message in (("relations", 65_537, "relation declarations"), ("graphs", 65_536, "graph declarations"), ("members", 257, "relation members")):
            program = parse(SOURCE)
            if key == "members": program.relations[0]["members"] *= count
            else: setattr(program, key, getattr(program, key) * count)
            with self.subTest(key=key), self.assertRaisesRegex(MrlError, message):
                lower(program)


if __name__ == "__main__":
    unittest.main()
