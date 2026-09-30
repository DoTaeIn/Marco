"""Independent v3 C-backend and bounded graph-runtime checks."""

import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from mrl.c_backend import emit_c
from mrl.toolchain import build_c, find_compiler


def literal(value, typ="si32"):
    return {"kind": "literal", "type": typ, "value": value}


def name(value, typ):
    return {"kind": "name", "type": typ, "name": value}


def program():
    construct = lambda label: {"kind": "construct", "type": "struct:Concept", "fields": [{"name": "label", "value": literal(label, "s")}]} 
    relation = lambda: {"kind": "relation", "type": "relation:Link", "member": "Edge"}
    add = lambda label: {"kind": "graph_add_node", "type": "node:g", "graph": "g", "value": construct(label)}
    edge = lambda left, right: {"kind": "graph_add_edge", "type": None, "graph": "g", "source": name(left, "node:g"), "target": name(right, "node:g"), "relation": relation(), "evidence": None}
    find = {"kind": "graph_find", "type": "result:path:g", "graph": "g", "source": name("a", "node:g"), "target": name("b", "node:g"), "relations": ["Edge"], "max_depth": 1, "max_expansions": 4, "method": "bfs"}
    return {"version": 3,
            "structs": [{"name": "Concept", "fields": [{"name": "label", "type": "s"}]}],
            "relations": [{"name": "Link", "members": [{"name": "Edge", "polarity": "positive", "evidence": "none", "traverse": "forward"}]}],
            "graphs": [{"name": "g", "node_type": "Concept", "relation": "Link", "directed": True}],
            "functions": [{"name": "main", "params": [], "return_type": None, "body": [
                {"kind": "let", "name": "a", "type": "node:g", "mutable": False, "value": add("α")},
                {"kind": "let", "name": "b", "type": "node:g", "mutable": False, "value": add("β")},
                {"kind": "expr", "value": edge("a", "b")},
                {"kind": "let", "name": "result", "type": "result:path:g", "mutable": False, "value": find},
                {"kind": "match", "value": name("result", "result:path:g"), "ok_name": "path", "ok": [
                    {"kind": "expr", "value": {"kind": "print", "type": None, "value": {"kind": "len", "type": "si32", "value": name("path", "path:g")}}}],
                 "err_name": "error", "err": [{"kind": "expr", "value": {"kind": "print", "type": None, "value": name("error", "search_error")}}]}]}]}


class GraphBackendTests(unittest.TestCase):
    def build_run(self, source, *args):
        if find_compiler()[0] is None:
            self.skipTest("no complete C11 toolchain found")
        with tempfile.TemporaryDirectory() as directory:
            c_file, exe = Path(directory) / "graph.c", Path(directory) / "graph.exe"
            c_file.write_text(source, encoding="utf-8")
            build_c(c_file, exe)
            return subprocess.run([str(exe), *args], capture_output=True, text=True, timeout=10)

    def test_emitted_graph_program_runs_with_utf8_literals(self):
        result = self.build_run(emit_c(program()))
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "1\n", ""))

    def test_runtime_path_tie_uses_insertion_order_and_retains_evidence(self):
        runtime = (Path(__file__).parents[1] / "runtime" / "graph_runtime.h").read_text(encoding="utf-8")
        source = """#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static void mrl_runtime_fail(const char *message) { fputs(message, stderr); exit(9); }
""" + runtime + """
int main(int argc, char **argv) {
    MrlGraph graph; const MrlRelationMeta meta[] = {{0, 1, 0}};
    mrl_graph_init(&graph, 7, 0, meta, 1);
    MrlNode source = mrl_graph_add_node(&graph), temporary = mrl_graph_add_node(&graph), target = mrl_graph_add_node(&graph);
    MrlRelation relation = {0, 0}; MrlEvidence old = {"src", "old", 0, 3}, newer = {"src", "new", 0, 3};
    mrl_graph_add_edge(&graph, source, temporary, relation, old);
    mrl_graph_add_edge(&graph, source, target, relation, old);
    mrl_graph_remove(&graph, temporary);
    mrl_graph_add_edge(&graph, source, target, relation, newer);
    uint16_t allowed[] = {0}; MrlSearchResult result = mrl_graph_find(&graph, true, source, target, allowed, 1, 1, 3);
    if (!result.ok || result.path.length != 1 || result.path.nodes[1].id != target.id || result.path.edges[0] != 1) return 2;
    if (strcmp(graph.edges[result.path.edges[0]].evidence.text, "old") != 0) return 3;
    if (argc > 1) mrl_graph_add_edge(&graph, source, target, (MrlRelation){1, 0}, newer);
    return 0;
}
"""
        result = self.build_run(source)
        self.assertEqual((result.returncode, result.stderr), (0, ""))
        foreign = self.build_run(source, "foreign")
        self.assertEqual((foreign.returncode, foreign.stderr), (9, "MRL invalid graph edge"))

    def test_rejects_hostile_evidence_and_cross_graph_handle(self):
        cases = []
        nul = program(); nul["functions"][0]["body"][0]["value"]["value"]["fields"][0]["value"]["value"] = "bad\0literal"; cases.append(nul)
        surrogate = program(); surrogate["functions"][0]["body"][0]["value"]["value"]["fields"][0]["value"]["value"] = "\ud800"; cases.append(surrogate)
        foreign = program(); foreign["functions"][0]["body"][3]["value"]["source"]["type"] = "node:other"; cases.append(foreign)
        for ir in cases:
            with self.subTest(ir=ir), self.assertRaises(ValueError):
                emit_c(ir)

    def test_v3_validator_never_skips_or_crashes_on_hostile_shapes(self):
        cases = []
        bad_else = program(); bad_else["functions"][0]["body"] = [{"kind": "if", "condition": literal(True, "b"), "then": [], "else": [{"kind": []}]}]; cases.append(bad_else)
        bad_err = program(); bad_err["functions"][0]["body"][-1]["err"] = [{"kind": []}]; cases.append(bad_err)
        none_field = program(); none_field["functions"][0]["body"].append({"kind": "expr", "value": {"kind": "field", "type": None, "value": name("a", "node:g"), "name": "x"}}); cases.append(none_field)
        none_len = program(); none_len["functions"][0]["body"].append({"kind": "expr", "value": {"kind": "len", "type": "si32", "value": {"kind": "graph_remove", "type": None, "graph": "g", "value": name("a", "node:g")}}}); cases.append(none_len)
        none_match = program(); none_match["functions"][0]["body"].append({"kind": "match", "value": {"kind": "graph_remove", "type": None, "graph": "g", "value": name("a", "node:g")}, "ok_name": "p", "ok": [], "err_name": "e", "err": []}); cases.append(none_match)
        bad_kind = program(); bad_kind["functions"][0]["body"][0]["kind"] = []; cases.append(bad_kind)
        bad_metadata = program(); bad_metadata["relations"][0]["members"][0]["polarity"] = []; cases.append(bad_metadata)
        bad_relation_entry = program(); bad_relation_entry["functions"][0]["body"][3]["value"]["relations"] = [[]]; cases.append(bad_relation_entry)
        pseudo_struct = program(); pseudo_struct["graphs"][0]["node_type"] = "$graphs"; cases.append(pseudo_struct)
        for ir in cases:
            with self.subTest(ir=ir), self.assertRaises(ValueError):
                emit_c(deepcopy(ir))
        too_many_relations = program(); too_many_relations["relations"] = [None] * 65537
        with self.assertRaises(ValueError):
            emit_c(too_many_relations)
