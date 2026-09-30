"""Independent small-graph reference checks for compiled source search."""
from dataclasses import dataclass
from pathlib import Path
import subprocess
import tempfile
import unittest

from mrl import toolchain
from mrl.__main__ import main


@dataclass(frozen=True)
class Edge:
    source: int
    target: int
    member: str
    traverse: str
    cost: int


MEMBERS = ("Forward", "Reverse", "Both", "Block")


def destination(edge, node, directed):
    if edge.traverse == "block":
        return None
    if not directed:
        return edge.target if edge.source == node else edge.source if edge.target == node else None
    if edge.traverse in {"forward", "both"} and edge.source == node:
        return edge.target
    if edge.traverse in {"reverse", "both"} and edge.target == node:
        return edge.source
    return None


def simple_paths(edges, directed, allowed):
    """Enumerate paths independently of the runtime's frontier implementation."""
    found = []
    def walk(node, seen, path):
        if node == 3:
            found.append(path)
            return
        choices = []
        for order, edge in enumerate(edges):
            to = destination(edge, node, directed)
            if edge.member in allowed and to is not None and to not in seen:
                choices.append((MEMBERS.index(edge.member), to, order, edge))
        for _, to, order, edge in sorted(choices):
            walk(to, seen | {to}, path + ((order, to, edge.cost),))
    walk(0, {0}, ())
    return found


def reference(edges, directed, method, allowed):
    paths = simple_paths(edges, directed, set(allowed or MEMBERS))
    def key(path):
        steps = tuple((MEMBERS.index(edges[order].member), to, order) for order, to, _ in path)
        cost = sum(value for _, _, value in path) if method in {"dijkstra", "astar"} else len(path)
        if method == "bfs":
            return len(path), steps
        if method == "dfs":
            return steps
        return cost, len(path), steps
    rows = []
    for path in sorted(paths, key=key):
        rows.append((len(path), sum(value for _, _, value in path) if method in {"dijkstra", "astar"} else len(path)))
    return rows


def source_for(edges, directed, queries):
    metadata = " ".join(f"{member} {{ polarity: positive evidence: none traverse: {traverse} }}" for member, traverse in zip(MEMBERS, ("forward", "reverse", "both", "block")))
    graph = "graph g { node: Node relation: Link edge: Edge" + (" directed: false" if not directed else "") + " }"
    setup = " ".join(f"n{i} = g.add(Node(name = \"n{i}\"))" for i in range(4))
    additions = " ".join(f"g.add(n{edge.source}, n{edge.target}, Link.{edge.member}, Edge(cost = {edge.cost}))" for edge in edges)
    blocks = []
    for index, (method, allowed) in enumerate(queries):
        options = f"method: {method}"
        if method in {"dijkstra", "astar"}:
            options += " cost: edge.cost"
        if method == "astar":
            options += " heuristic: zero(node, goal)"
        if allowed is not None:
            options += " relation in [" + ", ".join("Link." + member for member in allowed) + "]"
        blocks.append(f'''q{index} = g.find_all(n0, n3) {{ {options} }}
print("q{index}")
match (q{index}) {{ Ok(paths) {{ print(paths.len) print(paths.complete) for (i in 0..paths.len) {{ path = paths[i] print(path.len) print(path.cost) }} }} Err(error) {{ print(error) }} }}''')
    return f'''struct Node {{ name: s }}
struct Edge {{ cost: si }}
relation Link {{ {metadata} }}
{graph}
fn zero(node: Node, goal: Node) -> si {{ return 0 }}
fn main() {{ {setup} {additions} {' '.join(blocks)} }}
'''


@unittest.skipUnless(toolchain.find_compiler()[0] is not None, "no complete C11 toolchain")
class SearchReferenceTests(unittest.TestCase):
    def assert_reference(self, edges, directed, queries):
        source = source_for(edges, directed, queries)
        expected = []
        for index, (method, allowed) in enumerate(queries):
            expected.append(f"q{index}")
            rows = reference(edges, directed, method, allowed)
            if not rows:
                expected.append("NoPath")
            else:
                expected.extend((str(len(rows)), "true"))
                expected.extend(str(value) for row in rows for value in row)
        with tempfile.TemporaryDirectory(prefix="mrl-search-reference-") as folder:
            source_file = Path(folder) / "case.mrl"
            output, executable = source_file.with_suffix(".c"), source_file.with_suffix(".exe")
            source_file.write_text(source, encoding="utf-8")
            self.assertEqual(main([str(source_file), "-o", str(output)]), 0)
            toolchain.build_c(output, executable, optimization="release")
            result = subprocess.run([str(executable)], capture_output=True, text=True, encoding="utf-8", timeout=15)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        # Equal observable pairs can arise from parallel edges, so edge identity is intentionally not asserted.
        self.assertEqual(result.stdout.splitlines(), expected)

    def test_directed_metadata_parallel_and_weighted_paths(self):
        edges = (
            Edge(0, 1, "Forward", "forward", 2), Edge(1, 3, "Forward", "forward", 1),
            Edge(2, 0, "Reverse", "reverse", 3), Edge(2, 3, "Both", "both", 0),
            Edge(0, 3, "Forward", "forward", 5), Edge(0, 3, "Forward", "forward", 4),
            Edge(0, 3, "Block", "block", 0),
        )
        queries = (("bfs", None), ("dfs", None), ("dijkstra", None), ("astar", None),
                   ("bfs", ("Forward",)), ("dijkstra", ("Reverse", "Both")), ("bfs", ("Block",)))
        self.assert_reference(edges, True, queries)

    def test_undirected_ignores_forward_reverse_but_not_block(self):
        edges = (
            Edge(1, 0, "Forward", "forward", 0), Edge(3, 1, "Reverse", "reverse", 2),
            Edge(0, 3, "Both", "both", 7), Edge(0, 3, "Both", "both", 4),
            Edge(2, 3, "Block", "block", 0),
        )
        queries = (("bfs", None), ("dfs", None), ("dijkstra", None), ("astar", None),
                   ("dijkstra", ("Forward", "Reverse")), ("bfs", ("Block",)))
        self.assert_reference(edges, False, queries)


if __name__ == "__main__":
    unittest.main()
