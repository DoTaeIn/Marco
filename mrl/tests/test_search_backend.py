import subprocess
import tempfile
import unittest
from pathlib import Path

from mrl.__main__ import main
from mrl.c_backend import emit_c
from mrl.frontend import compile_source
from mrl.toolchain import build_c, find_compiler


@unittest.skipUnless(find_compiler()[0] is not None, "no complete C11 toolchain")
class SearchBackendTests(unittest.TestCase):
    def run_source(self, source):
        with tempfile.TemporaryDirectory() as folder:
            source_file = Path(folder) / "search.mrl"
            c_file, executable = source_file.with_suffix(".c"), source_file.with_suffix(".exe")
            source_file.write_text(source, encoding="utf-8")
            self.assertEqual(main([str(source_file), "-o", str(c_file)]), 0)
            build_c(c_file, executable, optimization="debug")
            return subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)

    def run_c(self, body):
        with tempfile.TemporaryDirectory() as folder:
            c_file, executable = Path(folder) / "search.c", Path(folder) / "search.exe"
            runtime = (Path(__file__).parents[1] / "runtime" / "graph_runtime.h").read_text(encoding="utf-8")
            c_file.write_text("""#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
static void mrl_runtime_fail(const char *message) { fputs(message, stderr); exit(1); }
""" + runtime + "\n" + body, encoding="utf-8")
            build_c(c_file, executable, optimization="debug")
            return subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)

    def test_parallel_weighted_paths_and_limit(self):
        source = '''
struct N { id: si }
struct E { weight: si }
relation R { Edge { polarity: positive evidence: none traverse: forward } }
graph g { node: N relation: R edge: E }
fn zero(node: N, goal: N) -> si { return 0 }
fn main() {
  a = g.add(N(id = 0)) b = g.add(N(id = 1)) c = g.add(N(id = 2))
  g.add(a, b, R.Edge, E(weight = 5)) g.add(a, b, R.Edge, E(weight = 1)) g.add(b, c, R.Edge, E(weight = 0))
  r = g.find_all(a, c) { method: dijkstra cost: edge.weight max_paths: 2 }
  match (r) { Ok(paths) { print(paths.len) print(paths.complete) print(paths.reason) for (i in 0..paths.len) { print(paths[i].cost) } } Err(error) { print(error) } }
  s = g.find(a, c) { method: astar cost: edge.weight heuristic: zero(node, goal) }
  match (s) { Ok(path) { print(path.cost) } Err(error) { print(error) } }
}
'''
        result = self.run_source(source)
        self.assertEqual((result.returncode, result.stderr, result.stdout.splitlines()), (0, "", ["2", "false", "PathLimit", "1", "5", "1"]))

    def test_v4_bfs_keeps_frozen_node_global_budget_behavior(self):
        source = '''
struct N { id: si }
struct E { weight: si }
relation R { Edge { polarity: positive evidence: none traverse: forward } }
graph g { node: N relation: R edge: E }
fn main() {
  s = g.add(N(id = 0)) a = g.add(N(id = 1)) t = g.add(N(id = 2))
  g.add(s, a, R.Edge, E(weight = 1)) g.add(s, a, R.Edge, E(weight = 1)) g.add(a, t, R.Edge, E(weight = 1))
  r = g.find(s, t) { method: bfs max_expansions: 2 }
  match (r) { Ok(path) { print(path.cost) } Err(error) { print(error) } }
}
'''
        result = self.run_source(source)
        self.assertEqual((result.returncode, result.stderr, result.stdout), (0, "", "2\n"))

    def test_v4_rejects_non_string_method_without_typeerror(self):
        source = '''
struct N { id: si }
struct E { weight: si }
relation R { Edge { polarity: positive evidence: none traverse: forward } }
graph g { node: N relation: R edge: E }
fn main() { a = g.add(N(id = 0)) b = g.add(N(id = 1)) g.add(a, b, R.Edge, E(weight = 1)) r = g.find(a, b) { method: bfs } match (r) { Ok(path) { print(path.cost) } Err(error) { print(error) } } }
'''
        ir = compile_source(source)
        ir["functions"][0]["body"][3]["value"]["method"] = []
        with self.assertRaises(ValueError):
            emit_c(ir)

    def test_weighted_tie_uses_relation_order_not_edge_slot(self):
        result = self.run_c('''
int main(void) {
  MrlGraph graph; MrlRelationMeta meta[] = {{0, 0, 0}, {0, 0, 0}};
  mrl_graph_init(&graph, 1, 0, meta, 2);
  MrlNode source = mrl_graph_add_node(&graph), target = mrl_graph_add_node(&graph);
  uint16_t high = mrl_graph_add_edge(&graph, source, target, (MrlRelation){0, 1}, (MrlEvidence){0});
  uint16_t low = mrl_graph_add_edge(&graph, source, target, (MrlRelation){0, 0}, (MrlEvidence){0});
  int32_t costs[MRL_MAX_EDGES] = {0}; uint16_t allowed[] = {0, 1}; MrlPathSet paths;
  MrlPathsResult found = mrl_graph_find_all(&graph, true, source, target, allowed, 2, 64, 10, 2, MRL_SEARCH_DIJKSTRA, costs, NULL, &paths);
  return !found.ok || paths.length != 2 || paths.paths[0].edges[0] != low || paths.paths[1].edges[0] != high;
}
''')
        self.assertEqual((result.returncode, result.stderr), (0, ""))


if __name__ == "__main__":
    unittest.main()
