"""End-to-end source checks for search extensions and bounded Horn queries."""
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from mrl import oracle, toolchain
from mrl.__main__ import main
from mrl.frontend import compile_source

ROOT = Path(__file__).parents[1]
DECLARATIONS = """
struct Node { name: s }
struct Edge { distance: si }
relation R { Link { polarity: positive evidence: optional traverse: forward } }
graph g { node: Node relation: R edge: Edge }
fn zero(node: Node, goal: Node) -> si { return 0 }
"""
TRAP = """
s = g.add(Node(name = "s"))
x = g.add(Node(name = "x"))
u = g.add(Node(name = "u"))
t = g.add(Node(name = "t"))
g.add(s, x, R.Link, Edge(distance = 0))
g.add(x, u, R.Link, Edge(distance = 0))
g.add(s, u, R.Link, Edge(distance = 5))
g.add(u, t, R.Link, Edge(distance = 0))
g.add(u, x, R.Link, Edge(distance = 0))
"""


def quoted(value):
    return json.dumps(value, ensure_ascii=False)


def triple(row):
    return "Triple(" + ", ".join(f"{k} = {quoted(v)}" for k, v in
                                zip(("subject", "predicate", "object"), row)) + ")"


def source_query(case):
    facts = []
    for row in case["facts"]:
        fields = [f"id = {quoted(row['id'])}"]
        fields += [f"{key} = {quoted(value)}" for key, value in
                   zip(("subject", "predicate", "object"), row["triple"])]
        if row.get("evidence"):
            fields.append("evidence = Evidence(" + ", ".join(
                f"{key} = {quoted(value)}" for key, value in row["evidence"].items()) + ")")
        if "polarity" in row:
            fields.append("polarity = " + str(row["polarity"]).lower())
        if "modality" in row:
            fields.append("modality = " + quoted(row["modality"]))
        facts.append("Fact(" + ", ".join(fields) + ")")
    rules = []
    for row in case["rules"]:
        fields = [f"id = {quoted(row['id'])}", "body = " + triple(row["body"][0]),
                  "head = " + triple(row["head"])]
        if "version" in row:
            fields.append("version = " + quoted(row["version"]))
        rules.append("Rule(" + ", ".join(fields) + ")")
    plan = "Horn(facts = Facts(" + ", ".join(facts) + "), rules = Rules(" + ", ".join(rules) + "))"
    args = [plan] + [f"{key} = {value}" for key, value in case.get("options", {}).items()]
    if "target" in case:
        args.append("target = " + triple(case["target"]))
    return case["operation"] + "(" + ", ".join(args) + ")"


def horn_cases():
    evidence = {"source": "가🙂x", "start": 0, "end": 2, "text": "가🙂"}
    facts = [
        {"id": "seed", "triple": ["a", "p", "b"], "evidence": evidence},
        {"id": "second", "triple": ["a", "p", "b"], "evidence": {}},
        {"id": "denied", "triple": ["c", "p", "d"], "evidence": {}},
        {"id": "deny", "triple": ["c", "p", "d"], "evidence": {}, "polarity": False},
        {"id": "future", "triple": ["e", "p", "f"], "evidence": {}, "modality": "planned"},
    ]
    rules = [
        {"id": "r1", "version": 'v"1', "body": [["?x", "p", "?y"]], "head": ["?x", "q", "?y"]},
        {"id": "r2", "version": 2, "body": [["?x", "q", "?y"]], "head": ["?x", "r", "?y"]},
    ]
    return [
        {"operation": "closure", "facts": facts, "rules": rules, "target": ["a", "r", "b"]},
        {"operation": "closure_with_provenance", "facts": facts, "rules": rules},
        {"operation": "closure_with_provenance", "facts": facts, "rules": rules,
         "options": {"limit": 64, "proof_limit": 1, "search_limit": 1}},
    ]


@unittest.skipUnless(toolchain.find_compiler()[0] is not None, "no complete C11 toolchain")
class SourceExtensionTests(unittest.TestCase):
    def run_source(self, source, mode="release"):
        with tempfile.TemporaryDirectory(prefix="mrl-source-extensions-") as folder:
            input_file = Path(folder) / "source.mrl"
            output, executable = input_file.with_suffix(".c"), input_file.with_suffix(".exe")
            input_file.write_text(source, encoding="utf-8")
            self.assertEqual(main([str(input_file), "-o", str(output)]), 0)
            toolchain.build_c(output, executable, optimization=mode)
            return subprocess.run([str(executable)], capture_output=True, text=True,
                                  encoding="utf-8", timeout=15)

    def test_runnable_weighted_search_example(self):
        source = (ROOT / "examples/search_paths.mrl").read_text(encoding="utf-8")
        self.assertEqual(compile_source(source)["version"], 4)
        expected = ["bfs", "1", "1", "dfs", "2", "2", "dijkstra", "2", "4",
                    "astar", "2", "4", "all", "3", "true", "Complete", "2", "4", "1", "7", "1", "9"]
        for mode in ("release", "debug"):
            with self.subTest(mode=mode):
                result = self.run_source(source, mode)
                self.assertEqual((result.returncode, result.stderr), (0, ""))
                self.assertEqual(result.stdout.splitlines(), expected)

    def test_weighted_depth_bound_preserves_costlier_shallow_state(self):
        rows = []
        for method in ("dijkstra", "astar"):
            options = f"method: {method} cost: edge.distance max_depth: 2"
            if method == "astar":
                options += " heuristic: zero(node, goal)"
            rows.append("result = g.find(s, t) { " + options + " } "
                        "match (result) { Ok(path) { print(path.len) print(path.cost) } Err(error) { print(error) } }")
        # Separate scopes permit each test query to use the same result variable.
        source = DECLARATIONS + "fn main() { " + TRAP + " if (true) { " + rows[0] + " } if (true) { " + rows[1] + " } }"
        result = self.run_source(source)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(result.stdout.splitlines(), ["2", "5", "2", "5"])

    def test_find_all_marks_partial_results_and_handles_zero_budgets(self):
        start = """
        s = g.add(Node(name = "s"))
        via = g.add(Node(name = "via"))
        t = g.add(Node(name = "t"))
        g.add(s, t, R.Link, Edge(distance = 8))
        g.add(s, via, R.Link, Edge(distance = 1))
        g.add(via, t, R.Link, Edge(distance = 1))
        """
        queries = [
            ("s", "t", "max_paths: 1"),
            ("s", "t", "max_paths: 16 max_depth: 1"),
            ("s", "t", "max_paths: 0"),
            ("s", "t", "max_depth: 0"),
            ("s", "t", "relation in []"),
            ("s", "s", "max_depth: 0 max_expansions: 0"),
        ]
        body = []
        for i, (a, b, options) in enumerate(queries):
            body.append(f"r{i} = g.find_all({a}, {b}) {{ {options} }} "
                        f"match (r{i}) {{ Ok(paths) {{ print(paths.len) print(paths.complete) print(paths.reason) }} Err(error) {{ print(error) }} }}")
        result = self.run_source(DECLARATIONS + "fn main() { " + start + " ".join(body) + " }")
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(result.stdout.splitlines(), [
            "1", "false", "PathLimit", "1", "false", "DepthLimit",
            "BudgetExceeded", "DepthLimit", "NoPath", "1", "true", "Complete"])

    def test_saved_path_results_survive_later_query_at_same_callsite(self):
        source = DECLARATIONS + """
        fn main() {
            s = g.add(Node(name = "s"))
            via = g.add(Node(name = "via"))
            t = g.add(Node(name = "t"))
            g.add(s, t, R.Link, Edge(distance = 8))
            g.add(s, via, R.Link, Edge(distance = 1))
            g.add(via, t, R.Link, Edge(distance = 1))
            saved = g.find_all(s, t) {}
            for (i in 0..2) {
                fresh = g.find_all(s, t) {}
                if (i == 0) { saved := fresh g.remove(via) }
            }
            match (saved) {
                Ok(paths) { print(paths.len) print(paths[1].len) }
                Err(error) { print(error) }
            }
        }
        """
        result = self.run_source(source, "debug")
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(result.stdout.splitlines(), ["2", "2"])

    def test_path_results_are_local_to_recursive_function_invocations(self):
        source = DECLARATIONS + """
        fn count(n: si) -> si {
            a = g.add(Node(name = "a"))
            b = g.add(Node(name = "b"))
            g.add(a, b, R.Link, Edge(distance = 1))
            if (n > 0) { g.add(a, b, R.Link, Edge(distance = 1)) }
            saved = g.find_all(a, b) {}
            if (n > 0) { inner = count(n - 1) }
            match (saved) {
                Ok(paths) { return paths.len }
                Err(error) { print(error) return -1 }
            }
        }
        fn main() -> si { return count(1) }
        """
        result = self.run_source(source, "debug")
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(result.stdout.splitlines(), ["2"])

    def test_match_path_bindings_are_value_snapshots(self):
        source = DECLARATIONS + """
        fn count(n: si) -> si {
            a = g.add(Node(name = "a"))
            b = g.add(Node(name = "b"))
            g.add(a, b, R.Link, Edge(distance = 1))
            if (n > 0) { g.add(a, b, R.Link, Edge(distance = 1)) }
            match (g.find_all(a, b) {}) {
                Ok(paths) {
                    if (n > 0) { inner = count(n - 1) }
                    return paths.len
                }
                Err(error) { return -1 }
            }
        }
        fn main() {
            print(count(1))
            a = g.add(Node(name = "a"))
            b = g.add(Node(name = "b"))
            g.add(a, b, R.Link, Edge(distance = 1))
            old = g.find_all(a, b) {}
            g.add(a, b, R.Link, Edge(distance = 1))
            fresh = g.find_all(a, b) {}
            match (old) {
                Ok(paths) {
                    old := fresh
                    print(paths.len)
                    copied = paths
                    match (fresh) {
                        Ok(new_paths) { copied := new_paths print(copied.len) }
                        Err(error) { print(error) }
                    }
                    print(paths.len)
                }
                Err(error) { print(error) }
            }
        }
        """
        result = self.run_source(source, "debug")
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual(result.stdout.splitlines(), ["2", "1", "2", "1"])

    def test_source_horn_json_matches_structural_oracle(self):
        cases = horn_cases()
        source = "fn main() { " + " ".join(f"r{i} = {source_query(case)} print(r{i})"
                                          for i, case in enumerate(cases)) + " }"
        result = self.run_source(source)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        self.assertEqual([json.loads(line) for line in result.stdout.splitlines()],
                         [oracle.evaluate(case) for case in cases])

    def test_search_and_horn_share_one_native_translation_unit(self):
        case = horn_cases()[1]
        example = (ROOT / "examples/search_paths.mrl").read_text(encoding="utf-8")
        source = example.replace('print("bfs")', "reasoning = " + source_query(case) +
                                 ' print(reasoning.complete) print(reasoning.fact_count) print(reasoning) print("bfs")')
        result = self.run_source(source)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        lines = result.stdout.splitlines()
        self.assertEqual(lines[:2], ["true", "3"])
        self.assertEqual(json.loads(lines[2]), oracle.evaluate(case))
        self.assertEqual(lines[3], "bfs")


if __name__ == "__main__":
    unittest.main()
