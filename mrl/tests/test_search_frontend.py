import unittest

from mrl.frontend import MrlError, compile_source


SOURCE = '''
struct Node { name: s }
struct Road { distance: si }
relation Link { Go { polarity: positive evidence: optional traverse: forward } }
graph roads { node: Node relation: Link edge: Road }
fn estimate(node: Node, goal: Node) -> si { return 0 }
fn main() {
  a = roads.add(Node(name = "a"))
  b = roads.add(Node(name = "b"))
  roads.add(a, b, Link.Go, Road(distance = 3))
  result = roads.find_all(a, b) { method: astar cost: edge.distance heuristic: estimate(node, goal) max_paths: 2 }
  match (result) { Ok(paths) { path = paths[0] print(path.cost) print(paths.complete) print(paths.reason) } Err(error) { print(error) } }
}
'''


class SearchFrontendTests(unittest.TestCase):
    def test_typed_search_lowers_to_v4_shapes(self):
        ir = compile_source(SOURCE)
        self.assertEqual(ir["version"], 4)
        self.assertEqual(ir["graphs"][0]["edge_type"], "Road")
        body = ir["functions"][-1]["body"]
        edge = body[2]["value"]
        self.assertEqual((edge["kind"], edge["payload"]["type"], edge["evidence"]), ("graph_add_edge", "struct:Road", None))
        find = body[3]["value"]
        self.assertEqual({key: find[key] for key in ("kind", "type", "method", "cost", "heuristic", "max_paths")}, {"kind": "graph_find_all", "type": "result:paths:roads", "method": "astar", "cost": "distance", "heuristic": "estimate", "max_paths": 2})
        path = body[4]["ok"][0]["value"]
        self.assertEqual(path, {"kind": "index", "type": "path:roads", "value": {"kind": "name", "type": "paths:roads", "name": "paths"}, "index": {"kind": "literal", "type": "si32", "value": 0}})

    def test_search_constraints_are_checked_at_source_boundary(self):
        cases = (
            (SOURCE.replace("method: astar cost: edge.distance heuristic: estimate(node, goal) max_paths: 2", "method: bfs cost: edge.distance"), "cost is only valid"),
            (SOURCE.replace("max_paths: 2", "max_paths: 257"), "at most 256"),
            (SOURCE.replace("find_all", "find").replace("method: astar cost: edge.distance heuristic: estimate(node, goal) max_paths: 2", "max_paths: 2"), "only valid for find_all"),
            (SOURCE.replace(", Road(distance = 3)", ""), "requires payload"),
            (SOURCE.replace("return 0", "print(0) return 0"), "transitively pure"),
            (SOURCE.replace("graph roads { node: Node relation: Link edge: Road }", "graph roads { node: Node node: Node relation: Link edge: Road }"), "duplicate graph field"),
        )
        for source, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(MrlError, message):
                compile_source(source)

    def test_astar_heuristic_rejects_horn_persistence(self):
        source = SOURCE.replace('fn estimate(node: Node, goal: Node) -> si { return 0 }', '''fn estimate(node: Node, goal: Node) -> si {
  p: Horn = Horn(memory_budget = 4, facts = Facts(), rules = Rules())
  saved = p.save("checkpoint")
  return 0
}''')
        with self.assertRaisesRegex(MrlError, "transitively pure"):
            compile_source(source)

    def test_horn_only_void_main_and_void_access_are_checked(self):
        horn = 'fn main() { result = closure(Horn(facts = Facts(), rules = Rules())) print(result) }'
        self.assertEqual(compile_source(horn)["version"], 4)
        self.assertEqual(compile_source('fn main() { print(closure(Horn(facts = Facts(), rules = Rules()))) }')["version"], 4)
        named = 'fn main() { ledger = Horn(facts = Facts(), rules = Rules()) print(ledger.version) }'
        self.assertEqual(compile_source(named)["version"], 5)
        for source in ('fn main() -> si { print(1).len return 0 }', 'fn main() -> si { print(1)[0] return 0 }'):
            with self.subTest(source=source), self.assertRaises(MrlError):
                compile_source(source)

    def test_mutable_horn_plan_lowers_to_ordered_v5_operations(self):
        source = '''
fn main() {
  ledger = Horn(facts = Facts(), rules = Rules())
  id = "support"
  added = ledger.add(Fact(modality = "planned", id = id, subject = "a", predicate = "p", object = "b", polarity = false, evidence = Evidence(source = "ab", start = 0, end = 1, text = "a")))
  before = closure(ledger, limit = 3, target = Triple("a", "p", "b"))
  version = ledger.version
  removed = ledger.remove(id)
  after = closure_with_provenance(ledger, proof_limit = 2)
  print(before.version)
  print(after.reason)
}
'''
        ir = compile_source(source)
        self.assertEqual(ir["version"], 5)
        body = ir["functions"][0]["body"]
        self.assertEqual(body[0]["value"], {"kind": "horn_plan", "type": "horn_plan", "plan": {"facts": [], "rules": []}})
        add = body[2]["value"]
        self.assertEqual((add["kind"], add["type"], add["plan"]), ("horn_add", "b", {"kind": "name", "type": "horn_plan", "name": "ledger"}))
        self.assertEqual([field["name"] for field in add["fact"]], ["modality", "id", "subject", "predicate", "object", "polarity", "evidence"])
        self.assertEqual(add["fact"][0]["value"], {"kind": "literal", "type": "s", "value": "planned"})
        self.assertEqual(add["fact"][-1]["value"]["kind"], "evidence")
        query = body[3]["value"]
        self.assertEqual({key: query[key] for key in ("kind", "type", "operation", "limit", "proof_limit", "search_limit", "target")}, {"kind": "horn_evaluate", "type": "horn_snapshot", "operation": "closure", "limit": 3, "proof_limit": 32, "search_limit": 24, "target": ["a", "p", "b"]})
        self.assertEqual(body[4]["value"], {"kind": "horn_version", "type": "si32", "plan": {"kind": "name", "type": "horn_plan", "name": "ledger"}})
        self.assertEqual(body[5]["value"]["kind"], "horn_remove")
        self.assertEqual(body[6]["value"]["type"], "horn_snapshot")
        self.assertEqual(body[7]["value"]["value"]["name"], "version")

    def test_horn_plan_mutation_requires_mutable_string_plan_fields(self):
        self.assertEqual(compile_source('fn main() { ledger = Horn(facts = Facts(), rules = Rules()) }')["version"], 5)
        source = 'fn main() { dec ledger = Horn(facts = Facts(), rules = Rules()) ledger.add(Fact(id = "x", subject = "a", predicate = "p", object = "b")) }'
        with self.assertRaisesRegex(MrlError, "mutable name"):
            compile_source(source)
        source = 'fn main() { ledger = Horn(facts = Facts(), rules = Rules()) ledger.add(Fact(id = 1, subject = "a", predicate = "p", object = "b")) }'
        with self.assertRaisesRegex(MrlError, "must be s"):
            compile_source(source)
        cases = (
            ('Fact(id = "x", subject = "a", predicate = "p", object = "b", polarity = "true")', "must be b"),
            ('Fact(id = "x", subject = "a", predicate = "p", object = "b", extra = true)', "invalid dynamic Fact fields"),
            ('Fact(id = "x", subject = "a", predicate = "p", object = "b", evidence = Evidence(source = "a", start = 0, end = 1, text = "x"))', "invalid Evidence source span"),
        )
        for fact, message in cases:
            source = 'fn main() { ledger = Horn(facts = Facts(), rules = Rules()) ledger.add(' + fact + ') }'
            with self.subTest(message=message), self.assertRaisesRegex(MrlError, message):
                compile_source(source)

    def test_v6_horn_handles_and_numeric_collection_annotations(self):
        source = '''
fn pass(ledger: Horn) -> Horn { return ledger }
fn snapshot(ledger: Horn) -> Snapshot { return closure(ledger) }
fn main() {
  dec xs: list<f32> = [1.0f, 2.0f]
  dec fixed: arr<si32,2> = [1, 2]
  ledger = Horn(facts = Facts(), rules = Rules())
  next = pass(ledger)
  before = snapshot(next)
}
'''
        ir = compile_source(source)
        self.assertEqual(ir["version"], 6)
        self.assertEqual(ir["functions"][0]["params"][0]["type"], "horn_plan")
        body = ir["functions"][-1]["body"]
        self.assertEqual(body[0]["type"], "list:f32")
        self.assertEqual(body[1]["type"], "arr:si32:2")


if __name__ == "__main__":
    unittest.main()
