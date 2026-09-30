"""Native regression coverage for unbounded graph slots and path ownership."""

import subprocess
import tempfile
import unittest
from pathlib import Path

from mrl.toolchain import build_c, find_compiler


@unittest.skipUnless(find_compiler()[0] is not None, "no complete C11 toolchain")
class DynamicGraphTests(unittest.TestCase):
    def test_grows_past_legacy_caps_and_releases_paths(self):
        runtime = (Path(__file__).parents[1] / "runtime" / "graph_runtime.h").read_text(encoding="utf-8")
        source = """#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
static void mrl_runtime_fail(const char *message) { fputs(message, stderr); exit(9); }
static uint32_t mrl_live_blocks;
static void *mrl_counted_calloc(size_t count, size_t size) { void *value = calloc(count, size); if (value) ++mrl_live_blocks; return value; }
static void *mrl_counted_realloc(void *old, size_t size) { void *value = realloc(old, size); if (value && !old) ++mrl_live_blocks; return value; }
static void mrl_counted_free(void *value) { if (value) --mrl_live_blocks; free(value); }
#define calloc mrl_counted_calloc
#define realloc mrl_counted_realloc
#define free mrl_counted_free
""" + runtime + r'''
int main(void) {
  MrlGraph graph; MrlRelationMeta meta[] = {{0, 0, 0}}; mrl_graph_init(&graph, 1, 0, meta, 1);
  MrlNode *nodes = calloc(70000, sizeof(*nodes)); if (!nodes) return 2;
  for (uint32_t i = 0; i < 70000; ++i) { nodes[i] = mrl_graph_add_node(&graph); if (nodes[i].id != i) return 3; }
  for (uint32_t i = 0; i < 300; ++i) mrl_graph_add_edge(&graph, nodes[i], nodes[i + 1], (MrlRelation){0, 0}, (MrlEvidence){0});
  uint16_t allowed[] = {0}; MrlSearchResult saved = mrl_graph_find_method(&graph, true, nodes[0], nodes[300], allowed, 1, 512, 1000, MRL_SEARCH_BFS, NULL, NULL);
  if (!saved.ok || saved.path.length != 300 || saved.path.nodes[300].id != nodes[300].id) return 4;
  for (uint32_t i = 301; i < 70000; ++i) mrl_graph_add_edge(&graph, nodes[i - 1], nodes[i], (MrlRelation){0, 0}, (MrlEvidence){0});
  if (saved.path.length != 300 || saved.path.nodes[300].id != nodes[300].id) return 5;
  MrlNode stale = nodes[500]; mrl_graph_remove(&graph, stale); MrlNode reused = mrl_graph_add_node(&graph);
  if (reused.id != stale.id || reused.generation == stale.generation || mrl_node_valid(&graph, stale)) return 6;
  uint32_t baseline = mrl_live_blocks;
  for (int i = 0; i < 1000; ++i) { MrlSearchResult query = mrl_graph_find_method(&graph, true, nodes[0], nodes[300], allowed, 1, 512, 1000, MRL_SEARCH_BFS, NULL, NULL); if (!query.ok) return 7; mrl_search_result_release(&query); if (mrl_live_blocks != baseline) return 8; }
  mrl_search_result_release(&saved); free(nodes); mrl_graph_destroy(&graph); return mrl_live_blocks != 0;
}
'''
        with tempfile.TemporaryDirectory() as folder:
            c_file, executable = Path(folder) / "dynamic.c", Path(folder) / "dynamic.exe"
            c_file.write_text(source, encoding="utf-8")
            build_c(c_file, executable, optimization="debug")
            result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=30)
        self.assertEqual((result.returncode, result.stderr), (0, ""))


if __name__ == "__main__":
    unittest.main()
