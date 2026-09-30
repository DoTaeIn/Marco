"""Source -> checked IR -> native graph, compared with an independent bounded BFS."""
from collections import deque
import json
from pathlib import Path
import random
import subprocess
import tempfile
import unittest

from mrl.frontend import MrlError, compile_source
from mrl.c_backend import emit_c
from mrl import toolchain

ROOT = Path(__file__).parents[1]
MODES = ("forward", "reverse", "both", "block")
MEMBERS = ("Forward", "Reverse", "Both", "Blocked")


def reference(nodes, edges, source, target, allowed, depth, expansions, directed=True):
    if source not in nodes or target not in nodes:
        return "InvalidNode"
    queue, seen, count, truncated = deque([(source, 0)]), {source}, 0, False
    while queue:
        current, distance = queue.popleft()
        if current == target:
            return str(distance)
        if count >= expansions:
            return "BudgetExceeded"
        count += 1
        candidates = []
        for order, (start, stop, relation) in enumerate(edges):
            if relation not in allowed or MODES[relation] == "block":
                continue
            mode = MODES[relation]
            if start == current and (not directed or mode in ("forward", "both")):
                candidates.append((relation, stop, order))
            if stop == current and (not directed or mode in ("reverse", "both")):
                candidates.append((relation, start, order))
        for _, neighbor, _ in sorted(candidates):
            if neighbor in seen:
                continue
            if distance >= depth:
                truncated = True
                continue
            seen.add(neighbor)
            queue.append((neighbor, distance + 1))
    return "DepthLimit" if truncated else "NoPath"


def declarations(directed=True):
    metadata = " ".join(f"{name} {{ polarity: positive evidence: optional traverse: {mode} }}"
                        for name, mode in zip(MEMBERS, MODES))
    return ("struct Concept { name: s } relation Logic { " + metadata + " } "
            "graph knowledge { node: Concept relation: Logic directed: "
            + ("true" if directed else "false") + " } ")


def query(index, source, target, allowed, depth, expansions):
    members = ", ".join("Logic." + MEMBERS[r] for r in sorted(allowed))
    return (f"result{index} = knowledge.find(n{source}, n{target}) {{ "
            f"relation in [{members}] max_depth: {depth} max_expansions: {expansions} method: bfs }} "
            f"match (result{index}) {{ Ok(path) {{ print(path.len) }} Err(error) {{ print(error) }} }} ")


@unittest.skipUnless(toolchain.find_compiler()[0] is not None, "no complete C compiler")
class SourceGraphIntegrationTests(unittest.TestCase):
    def run_source(self, source, cli=False):
        with tempfile.TemporaryDirectory(prefix="mrl-graph-integration-") as temp:
            root = Path(temp)
            input_file, output, executable = root / "case.mrl", root / "case.c", root / "case.exe"
            input_file.write_text(source, encoding="utf-8")
            if cli:
                from mrl.__main__ import main
                self.assertEqual(main([str(input_file), "-o", str(output)]), 0)
            else:
                output.write_text(emit_c(compile_source(source)), encoding="utf-8")
            toolchain.build_c(output, executable)
            return subprocess.run([str(executable)], capture_output=True, text=True,
                                  encoding="utf-8", timeout=10)

    def test_guide_graph_smoke_through_public_cli(self):
        source = (ROOT / "examples" / "graph_smoke.mrl").read_text(encoding="utf-8")
        self.assertEqual(compile_source(source)["version"], 3)
        result = self.run_source(source, cli=True)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "1\n", ""))

    def test_bfs_modes_filters_and_budgets_match_independent_reference(self):
        rng = random.Random(504)
        for directed in (True, False):
            edges = [(0, 1, 0), (1, 2, 0), (3, 2, 1), (3, 4, 2), (0, 5, 3)]
            edges += [(rng.randrange(6), rng.randrange(6), rng.randrange(4)) for _ in range(8)]
            queries = [(0, 0, set(), 0, 0), (0, 2, {0}, 0, 10),
                       (0, 2, {0}, 1, 10), (0, 2, {0}, 8, 0),
                       (0, 2, {0}, 8, 1), (0, 5, {3}, 8, 100),
                       (4, 0, {0, 1, 2}, 8, 100)]
            queries += [(rng.randrange(6), rng.randrange(6), {0, 1, 2},
                         rng.randrange(5), rng.randrange(8)) for _ in range(15)]
            statements = [f'n{i} = knowledge.add(Concept(name = "n{i}"))' for i in range(6)]
            statements += [f"knowledge.add(n{a}, n{b}, Logic.{MEMBERS[r]})" for a, b, r in edges]
            statements += [query(i, *args) for i, args in enumerate(queries)]
            source = declarations(directed) + "fn main() { " + " ".join(statements) + " }"
            expected = [reference(set(range(6)), edges, *args, directed=directed) for args in queries]
            result = self.run_source(source)
            with self.subTest(directed=directed):
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.splitlines(), expected)

    def test_extended_control_flow_and_named_fields_preserve_evaluation_order(self):
        source = """struct Pair { a: si b: si }
        fn mark(v: si) -> si { print(v) return v }
        fn main() {
            p = Pair(b = mark(2), a = mark(1))
            print(p.a) print(p.b)
            n = 3 total = 0
            for (i in 0..n) { n := 0 total := total + 1 }
            print(total)
        }"""
        result = self.run_source(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["2", "1", "1", "2", "3"])

    def test_stale_handle_does_not_revive_after_slot_reuse(self):
        source = declarations() + """
        fn main() {
            old = knowledge.add(Concept(name = "old"))
            target = knowledge.add(Concept(name = "target"))
            knowledge.add(old, target, Logic.Forward)
            knowledge.remove(old)
            replacement = knowledge.add(Concept(name = "replacement"))
            stale = knowledge.find(old, target) {}
            match (stale) { Ok(path) { print(path.len) } Err(error) { print(error) } }
            fresh = knowledge.find(replacement, target) {}
            match (fresh) { Ok(path) { print(path.len) } Err(error) { print(error) } }
            knowledge.add(replacement, target, Logic.Forward)
            linked = knowledge.find(replacement, target) {}
            match (linked) { Ok(path) { print(path.len) } Err(error) { print(error) } }
        }
        """
        result = self.run_source(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["InvalidNode", "NoPath", "1"])

    def test_unicode_evidence_struct_values_and_checked_capacity(self):
        literal = json.dumps("가🙂z", ensure_ascii=False)
        source = ("struct Concept { name: s } relation Logic { Required { polarity: positive "
                  "evidence: required traverse: forward } } graph knowledge { node: Concept relation: Logic } "
                  f"fn main() {{ name = {literal} print(name.len) "
                  "value = Concept(name = name) print(value.name) "
                  'a = knowledge.add(value) b = knowledge.add(Concept(name = "b")) '
                  f'knowledge.add(a, b, Logic.Required, Evidence(source = {literal}, start = 1, end = 2, text = "🙂")) '
                  "found = knowledge.find(a, b) {} match (found) { Ok(path) { print(path.len) } Err(error) { print(error) } } }")
        result = self.run_source(source)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.splitlines(), ["3", "가🙂z", "1"])
        overflow = declarations() + 'fn main() { for (i in 0..65) { n = knowledge.add(Concept(name = "n")) } }'
        failed = self.run_source(overflow)
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("capacity", failed.stderr.lower())


class SourceGraphAdmissionTests(unittest.TestCase):
    def test_ownership_evidence_and_unsupported_strings_are_located_errors(self):
        prefix = declarations() + "graph other { node: Concept relation: Logic } "
        bad = [prefix + 'fn main() { a = knowledge.add(Concept(name = "a")) b = other.add(Concept(name = "b")) knowledge.add(a, b, Logic.Forward) }',
               declarations() + 'fn main() { value = "\\u0000" print(value.len) }',
               declarations() + 'fn main() { value = "\\ud800" print(value.len) }',
               declarations() + 'fn main() { a = knowledge.add(Concept(name = "a")) r = knowledge.find(a,a) {} print(r.len) }']
        required = ("struct Concept { name: s } relation Logic { Required { polarity: positive "
                    "evidence: required traverse: forward } } graph knowledge { node: Concept relation: Logic } "
                    'fn main() { a = knowledge.add(Concept(name = "a")) b = knowledge.add(Concept(name = "b")) ')
        bad += [required + "knowledge.add(a,b,Logic.Required) }",
                required + 'knowledge.add(a,b,Logic.Required,Evidence(source = "abc",start = 0,end = 2,text = "wrong")) }']
        for source in bad:
            with self.subTest(source=source), self.assertRaises(MrlError) as caught:
                compile_source(source)
            self.assertRegex(str(caught.exception), r"^\d+:\d+:")


if __name__ == "__main__":
    unittest.main()
