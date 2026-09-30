"""End-to-end checks for v5 named mutable Horn plans."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from mrl import oracle, toolchain
from mrl.__main__ import main
from mrl.c_backend import emit_c
from mrl.frontend import MrlError, compile_source


ROOT = Path(__file__).parents[1]


def compile_run(source):
    with tempfile.TemporaryDirectory(prefix="mrl-mutable-horn-") as folder:
        source_file = Path(folder) / "source.mrl"
        c_file, executable = source_file.with_suffix(".c"), source_file.with_suffix(".exe")
        source_file.write_text(source, encoding="utf-8")
        if main([str(source_file), "-o", str(c_file)]) != 0:
            raise AssertionError("source compilation failed")
        toolchain.build_c(c_file, executable)
        result = subprocess.run([str(executable)], capture_output=True, text=True,
                                encoding="utf-8", timeout=15)
    return result


def run_source(source):
    result = compile_run(source)
    if (result.returncode, result.stderr) != (0, ""):
        raise AssertionError((result.returncode, result.stderr))
    return result.stdout.splitlines()


def facts(result):
    rows = result.get("facts", result.get("known", {})).get("$tuple_map", [])
    return {tuple(row["key"]): row["value"] for row in rows}


def bundles(result, triple):
    rows = result.get("proof_bundles", {}).get("$tuple_map", [])
    return next(row["value"] for row in rows if row["key"] == list(triple))


PLAN = '''
Horn(
    facts = Facts(Fact(id = "a", subject = "a", predicate = "p", object = "b")),
    rules = Rules(Rule(id = "p_to_q", version = 1,
        body = Triple(subject = "?x", predicate = "p", object = "?y"),
        head = Triple(subject = "?x", predicate = "q", object = "?y")))
)'''


RULES = [{"id": "p_to_q", "version": 1,
          "body": [["?x", "p", "?y"]], "head": ["?x", "q", "?y"]}]


def source_fact(ident, subject, predicate, obj, **extra):
    return {"id": ident, "triple": [subject, predicate, obj], "evidence": {}, **extra}


def provenance(*rows):
    return {"operation": "closure_with_provenance", "facts": list(rows), "rules": RULES,
            "options": {"limit": 64, "proof_limit": 8, "search_limit": 256}}


@unittest.skipUnless(toolchain.find_compiler()[0] is not None, "no complete C11 toolchain")
class MutableHornSourceTests(unittest.TestCase):
    def test_runnable_knowledge_updates_example(self):
        lines = run_source((ROOT / "examples" / "knowledge_updates.mrl").read_text(encoding="utf-8"))
        self.assertEqual(lines[:4], ["true", "true", "true", "3"])
        results = [json.loads(line) for line in lines[4:]]
        self.assertEqual([len(facts(result)) for result in results], [2, 4, 3, 4])
        self.assertTrue(all("version" not in result for result in results))

    def test_plan_updates_snapshots_proofs_and_callsite_isolation(self):
        source = f'''
        fn nested(n: si) -> si {{
            local = Horn(facts = Facts(), rules = Rules(Rule(id = "r", version = 1,
                body = Triple(subject = "?x", predicate = "p", object = "?y"),
                head = Triple(subject = "?x", predicate = "q", object = "?y"))))
            if (n > 0) {{
                local.add(Fact(id = "local", subject = "n", predicate = "p", object = "v"))
                inner = nested(n - 1)
            }}
            snapshot = closure(local, limit = 64)
            return snapshot.fact_count
        }}
        fn main() {{
            ledger = {PLAN}
            before = closure_with_provenance(ledger, limit = 64, proof_limit = 8, search_limit = 256)
            duplicate = ledger.add(Fact(id = "a", subject = "other", predicate = "p", object = "value"))
            print(duplicate)
            print(ledger.version)
            added = ledger.add(Fact(id = "b", subject = "a", predicate = "p", object = "b",
                evidence = Evidence(source = "가🙂b", start = 0, end = 2, text = "가🙂")))
            print(added)
            print(ledger.version)
            both = closure_with_provenance(ledger, limit = 64, proof_limit = 8, search_limit = 256)
            removed_a = ledger.remove("a")
            print(removed_a)
            print(ledger.version)
            retained = closure_with_provenance(ledger, limit = 64, proof_limit = 8, search_limit = 256)
            removed_b = ledger.remove("b")
            print(removed_b)
            print(ledger.version)
            empty = closure_with_provenance(ledger, limit = 64, proof_limit = 8, search_limit = 256)
            readded = ledger.add(Fact(id = "a", subject = "a", predicate = "p", object = "b"))
            print(readded)
            print(ledger.version)
            denied = ledger.add(Fact(id = "deny", subject = "a", predicate = "q", object = "b", polarity = false))
            print(denied)
            print(ledger.version)
            blocked = closure_with_provenance(ledger, limit = 64, proof_limit = 8, search_limit = 256)
            restored_denial = ledger.remove("deny")
            print(restored_denial)
            print(ledger.version)
            restored = closure_with_provenance(ledger, limit = 64, proof_limit = 8, search_limit = 256)
            copy = ledger
            copy_added = copy.add(Fact(id = "copy", subject = "c", predicate = "p", object = "d"))
            print(copy_added)
            print(copy.version)
            print(ledger.version)
            base_after_copy = closure_with_provenance(ledger, limit = 64, proof_limit = 8, search_limit = 256)
            copy_after = closure_with_provenance(copy, limit = 64, proof_limit = 8, search_limit = 256)
            static_result = closure(Horn(facts = Facts(Fact(id = "static", subject = "s", predicate = "p", object = "t")),
                rules = Rules(Rule(id = "static_rule", body = Triple(subject = "?x", predicate = "p", object = "?y"),
                head = Triple(subject = "?x", predicate = "q", object = "?y")))), limit = 64)
            print(before)
            print(both)
            print(retained)
            print(empty)
            print(blocked)
            print(restored)
            print(base_after_copy)
            print(copy_after)
            print(static_result)
            print(before)
            print(before.version)
            print(both.version)
            print(retained.version)
            print(empty.version)
            print(blocked.version)
            print(restored.version)
            print(base_after_copy.version)
            print(copy_after.version)
            print(nested(1))
            print(nested(0))
        }}
        '''
        lines = run_source(source)
        self.assertEqual(lines[:17], ["false", "0", "true", "1", "true", "2", "true", "3",
                                      "true", "4", "true", "5", "true", "6", "true", "7", "6"])
        before, both, retained, empty, blocked, restored, base, copied, static, before_again = map(json.loads, lines[17:27])
        self.assertEqual(lines[27:35], ["0", "1", "2", "3", "5", "6", "6", "7"])
        self.assertEqual(lines[35:], ["2", "0"])
        self.assertEqual(before, before_again)
        expected = [
            oracle.evaluate(provenance(source_fact("a", "a", "p", "b"))),
            oracle.evaluate(provenance(source_fact("a", "a", "p", "b"),
                                       source_fact("b", "a", "p", "b", evidence={"source": "가🙂b", "start": 0, "end": 2, "text": "가🙂"}))),
            oracle.evaluate(provenance(source_fact("b", "a", "p", "b", evidence={"source": "가🙂b", "start": 0, "end": 2, "text": "가🙂"}))),
            oracle.evaluate(provenance()),
            oracle.evaluate(provenance(source_fact("a", "a", "p", "b"),
                                       source_fact("deny", "a", "q", "b", polarity=False))),
            oracle.evaluate(provenance(source_fact("a", "a", "p", "b"))),
            oracle.evaluate(provenance(source_fact("a", "a", "p", "b"))),
            oracle.evaluate(provenance(source_fact("a", "a", "p", "b"), source_fact("copy", "c", "p", "d"))),
            oracle.evaluate({"operation": "closure", "facts": [source_fact("static", "s", "p", "t")],
                             "rules": [{"id": "static_rule", "body": [["?x", "p", "?y"]], "head": ["?x", "q", "?y"]}],
                             "options": {"limit": 64}}),
        ]
        self.assertEqual([before, both, retained, empty, blocked, restored, base, copied, static], expected)
        self.assertEqual([len(facts(item)) for item in (before, both, retained, empty, blocked, restored, base, copied, static)],
                         [2, 2, 2, 0, 1, 2, 2, 4, 2])
        self.assertEqual({row["id"] for row in bundles(both, ("a", "p", "b"))}, {"support:a", "support:b"})
        self.assertEqual([row["premise_fact_ids"] for row in bundles(retained, ("a", "q", "b"))], [["support:b"]])
        self.assertNotIn(("a", "q", "b"), facts(blocked))
        self.assertIn(("a", "q", "b"), facts(restored))
        self.assertNotIn(("c", "q", "d"), facts(base))
        self.assertIn(("c", "q", "d"), facts(copied))

    def test_fact_arguments_evaluate_in_written_order(self):
        source = '''
        fn mark(value: s) -> s { print(value) return value }
        fn main() {
            ledger = Horn(facts = Facts(), rules = Rules())
            added = ledger.add(Fact(object = mark("object"), id = mark("id"), predicate = mark("predicate"), subject = mark("subject")))
            snapshot = closure(ledger, limit = 64)
            print(added)
            print(snapshot.fact_count)
        }
        '''
        self.assertEqual(run_source(source), ["object", "id", "predicate", "subject", "true", "1"])

    def test_snapshot_summary_target_and_loop_results_are_values(self):
        source = f'''
        fn main() {{
            ledger = {PLAN}
            old = closure(ledger, limit = 64)
            ledger.add(Fact(id = "b", subject = "c", predicate = "p", object = "d"))
            recent = closure(ledger, limit = 64)
            for (i in 0..3) {{ recent := closure(ledger, limit = 64) }}
            first = {PLAN}
            first_snapshot = closure(first, limit = 64)
            for (i in 0..3) {{ temporary = Horn(facts = Facts(), rules = Rules()) }}
            first_again = closure(first, limit = 64)
            missed = closure(ledger, limit = 64, target = Triple(subject = "missing", predicate = "p", object = "value"))
            print(old.fact_count)
            print(old.version)
            print(recent.fact_count)
            print(recent.version)
            print(first_snapshot)
            print(first_again)
            print(missed.complete)
            print(missed.reason)
            print(missed)
        }}
        '''
        lines = run_source(source)
        self.assertEqual(lines[:4], ["2", "0", "4", "1"])
        first, again, missed = json.loads(lines[4]), json.loads(lines[5]), json.loads(lines[8])
        self.assertEqual(lines[6], "false")
        self.assertEqual(lines[7], "target_not_found")
        self.assertEqual(first, again)
        self.assertEqual(len(facts(missed)), 4)
        self.assertFalse(missed["complete"])
        self.assertEqual(missed["reason"], "target_not_found")

    def test_dynamic_invalid_facts_and_default_capacity_fail_at_runtime(self):
        bad_facts = [
            'Fact(id = "", subject = "s", predicate = "p", object = "o")',
            'Fact(id = "id", subject = "", predicate = "p", object = "o")',
            'Fact(id = "id", subject = "s", predicate = "p", object = "o", modality = "unknown")',
        ]
        for fact in bad_facts:
            with self.subTest(fact=fact):
                source = f'''fn main() {{ ledger = Horn(facts = Facts(), rules = Rules()) ledger.add({fact}) }}'''
                result = compile_run(source)
                self.assertNotEqual(result.returncode, 0)
                self.assertTrue(result.stderr)
        additions = " ".join('ledger.add(Fact(id = "f%d", subject = "s%d", predicate = "p", object = "o"))' % (i, i)
                              for i in range(65))
        result = compile_run("fn main() { ledger = Horn(facts = Facts(), rules = Rules()) " + additions + " }")
        self.assertNotEqual(result.returncode, 0)
        self.assertTrue(result.stderr)

    def test_v5_keeps_weighted_search_and_rejects_forged_nodes(self):
        source = f'''
        struct Node {{ name: s }}
        struct Edge {{ distance: si }}
        relation R {{ Link {{ polarity: positive evidence: optional traverse: forward }} }}
        graph g {{ node: Node relation: R edge: Edge }}
        fn main() {{
            ledger = {PLAN}
            snapshot = closure(ledger, limit = 64)
            s = g.add(Node(name = "s"))
            via = g.add(Node(name = "via"))
            t = g.add(Node(name = "t"))
            g.add(s, t, R.Link, Edge(distance = 8))
            g.add(s, via, R.Link, Edge(distance = 1))
            g.add(via, t, R.Link, Edge(distance = 1))
            path = g.find(s, t) {{ method: dijkstra cost: edge.distance }}
            match (path) {{ Ok(found) {{ print(found.len) print(found.cost) }} Err(error) {{ print(error) }} }}
            print(snapshot.fact_count)
        }}
        '''
        self.assertEqual(run_source(source), ["2", "2", "2"])
        ir = compile_source(source)
        self.assertEqual(ir["version"], 5)
        bad = deepcopy(ir)
        next(statement for statement in bad["functions"][-1]["body"]
             if statement.get("value", {}).get("kind") == "horn_evaluate")["value"]["operation"] = []
        with self.assertRaises(ValueError):
            emit_c(bad)
        bad = deepcopy(ir)
        bad["graphs"][0]["edge_type"] = "missing"
        with self.assertRaises(ValueError):
            emit_c(bad)

    def test_v5_admission_rejects_mutation_of_constant_plan_and_bad_ir(self):
        immutable = f'''fn main() {{ dec ledger = {PLAN} ledger.add(Fact(id = "x", subject = "x", predicate = "p", object = "y")) }}'''
        with self.assertRaises(MrlError):
            compile_source(immutable)
        source = f'''fn main() {{ ledger = {PLAN} ledger.add(Fact(id = "x", subject = "x", predicate = "p", object = "y")) }}'''
        ir = compile_source(source)
        body = ir["functions"][0]["body"]
        add_index = next(index for index, statement in enumerate(body)
                         if statement.get("value", {}).get("kind") == "horn_add")
        add = body[add_index]["value"]
        for bad in (dict(add, fact=add["fact"] + [deepcopy(add["fact"][0])]),
                    dict(add, plan={"kind": "name", "type": "horn_plan", "name": "missing"})):
            candidate = deepcopy(ir)
            candidate["functions"][0]["body"][add_index]["value"] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                emit_c(candidate)
        static = compile_source('fn main() { print(closure(Horn(facts = Facts(), rules = Rules()), limit = 64)) }')
        self.assertEqual(static["version"], 4)
        static["functions"][0]["body"][0]["value"]["value"] = add
        with self.assertRaises(ValueError):
            emit_c(static)


if __name__ == "__main__":
    unittest.main()
