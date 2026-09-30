import subprocess
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from mrl.c_backend import emit_c
from mrl.frontend import MrlError, compile_source
from mrl.toolchain import build_c
from mrl.__main__ import main as cli_main


def run(source):
    with tempfile.TemporaryDirectory(prefix="mrl-v6-") as directory:
        c, exe = Path(directory) / "x.c", Path(directory) / "x.exe"
        c.write_text(emit_c(compile_source(source)), encoding="utf-8")
        build_c(c, exe)
        result = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
    if result.returncode: raise AssertionError(result.stderr)
    return result.stdout.splitlines()


class V6LanguageTests(unittest.TestCase):
    def test_result_f32_and_static_horn_execute_together(self):
        source = '''
fn pass(x: Result<si,s>) -> Result<si,s> { return x }
fn main() -> si {
  dec xs: list<f32> = [1.0f, 2.0f]
  dec value: Result<si,s> = Ok(7)
  print(sum(xs))
  print(closure(Horn(facts = Facts(), rules = Rules())).fact_count)
  match (pass(value)) { Ok(n) { return n } Err(e) { return 1 } }
}
'''
        self.assertEqual(run(source), ["3", "0", "7"])

    def test_horn_load_ok_and_error_are_values(self):
        with tempfile.TemporaryDirectory(prefix="mrl-jsonl-") as directory:
            path = Path(directory) / "facts.jsonl"
            path.write_text('{"id":"f","subject":"a","predicate":"p","object":"b"}\n', encoding="utf-8")
            source = f'''fn main() -> si {{ h = Horn(facts = Facts(), rules = Rules()) match (h.load("{path.as_posix()}")) {{ Ok(n) {{ return n }} Err(e) {{ return 99 }} }} }}'''
            self.assertEqual(run(source), ["1"])
        self.assertEqual(run('fn main() -> si { h = Horn(facts = Facts(), rules = Rules()) match (h.load("missing.jsonl")) { Ok(n) { return 9 } Err(e) { print(e) return 1 } } }')[-1], "1")

    def test_v6_hostile_ir_is_rejected(self):
        ir = compile_source('fn main() { dec xs: list<f32> = [1.0f] }')
        bad = deepcopy(ir); bad["functions"][0]["body"][0]["type"] = "list:f32junk"
        with self.assertRaises(ValueError): emit_c(bad)
        bad = deepcopy(ir); bad["functions"][0]["body"][0]["type"] = "arr:f32:08"; bad["functions"][0]["body"][0]["value"]["type"] = "arr:f32:08"
        with self.assertRaises(ValueError): emit_c(bad)
        bad = deepcopy(ir); bad["functions"][0]["body"][0]["value"]["items"][0]["value"] = 1e100
        with self.assertRaises(ValueError): emit_c(bad)
        with self.assertRaises(MrlError): compile_source('fn main() { dec xs: list<f32> = [1.0f] dec ys: list<f32> = [2.0f] ys.push(1) }')

    def test_weighted_graph_remains_runnable_in_v6(self):
        source = '''
struct Node { name: s }
struct Edge { cost: si }
relation R { Go { polarity: positive evidence: none traverse: forward } }
graph g { node: Node relation: R edge: Edge }
fn main() -> si {
  dec xs: list<f32> = [1.0f]
  a = g.add(Node(name = "a")) b = g.add(Node(name = "b"))
  g.add(a, b, R.Go, Edge(cost = 2))
  r = g.find(a, b) { method: dijkstra cost: edge.cost }
  match (r) { Ok(p) { return p.cost } Err(e) { return 9 } }
}
'''
        self.assertEqual(run(source), ["2"])

    def test_kernel_operator_schema_is_checked(self):
        ir = compile_source('fn main() { dec xs: list<f32> = [1.0f] print(sum(xs)) }')
        kernel = ir["functions"][0]["body"][1]["value"]["value"]
        bad = deepcopy(ir); bad["functions"][0]["body"][1]["value"]["value"]["op"] = []
        with self.assertRaises(ValueError): emit_c(bad)

    def test_file_relative_module_import(self):
        with tempfile.TemporaryDirectory(prefix="mrl-module-") as directory:
            root = Path(directory); (root / "lib.mrl").write_text("fn one() -> si { return 1 }", encoding="utf-8")
            source, output = root / "main.mrl", root / "main.c"
            source.write_text('import "lib.mrl"\nfn main() -> si { return one() }', encoding="utf-8")
            self.assertEqual(cli_main([str(source), "-o", str(output)]), 0)
            exe = root / "main.exe"; build_c(output, exe)
            self.assertEqual(subprocess.run([str(exe)], capture_output=True, text=True).stdout.splitlines(), ["1"])

    def test_type_only_v6_signatures_select_v6(self):
        for typ in ("f32", "list<f32>", "Result<si,s>", "arr<si,2>"):
            source = f"fn id(x: {typ}) -> {typ} {{ return x }} fn main() -> si {{ return 1 }}"
            self.assertEqual(compile_source(source)["version"], 6)
            emit_c(compile_source(source))


if __name__ == "__main__": unittest.main()
