import subprocess
import tempfile
import unittest
from pathlib import Path

from mrl.c_backend import emit_c
from mrl.frontend import compile_source
from mrl.toolchain import build_c


SOURCE = '''
struct Pack { xs: list<si> ready: Result<list<si>,s> table: Result<map<s,si>,s> }
struct Row { xs: list<si> }
fn make() -> Pack { return Pack(xs=[4], ready=Ok([5,6]), table=Ok(Map())) }
fn pass(x: Pack) -> Pack { return x }
fn nested() -> Result<Result<si,s>,s> { return Ok(Ok(9)) }
fn wrapped() -> Result<Row,s> { return Ok(Row(xs=[7])) }
fn main() -> si {
  m: map<s,s> = Map()
  m.set("answer", "alive")
  got = m.get("answer")
  m := Map()
  p: Pack = pass(make())
  row: Result<Row,s> = wrapped()
  match (got) { Ok(text) { print(text) } Err(e) { return 1 } }
  match (p.ready) { Ok(xs) {
    match (p.table) { Ok(table) {
      match (nested()) { Ok(inner) { match (inner) { Ok(n) { match (row) { Ok(value) { return n + p.xs.len + xs.len + table.len + value.xs.len } Err(e) { return 2 } } } Err(e) { return 3 } } } Err(e) { return 4 } }
    } Err(e) { return 5 } }
  } Err(e) { return 6 } }
}
'''


class V9ManagedValuesTests(unittest.TestCase):
    def test_nested_results_records_and_map_string_release(self):
        self.check_ownership(SOURCE)

    def test_ir7_keeps_managed_values_and_horn_branch_ownership(self):
        setup = 'knowledge: Horn = Horn(memory_budget=4000000, capacity=32, facts=Facts(), rules=Rules()) knowledge.add(Fact(id="a", subject="a", predicate="p", object="b")) alias: Horn = knowledge alias.remove("a") print(knowledge.count()) snap: Snapshot = closure(knowledge) print(snap.fact_count) '
        self.check_ownership(SOURCE.replace("fn main() -> si {", "fn main() -> si {" + setup), ["1", "1", "alive", "13"])

    def check_ownership(self, source_text, expected=None):
        code = emit_c(compile_source(source_text))
        hook = '''static int mrl_blocks;
static void *mrl_malloc(size_t n){void*p=malloc(n);if(p)++mrl_blocks;return p;}
static void *mrl_calloc(size_t a,size_t b){void*p=calloc(a,b);if(p)++mrl_blocks;return p;}
static void *mrl_realloc(void*p,size_t n){if(!p){void*q=realloc(p,n);if(q)++mrl_blocks;return q;}return realloc(p,n);}
static void mrl_free(void*p){if(p)--mrl_blocks;free(p);}
#define calloc mrl_calloc
#define malloc mrl_malloc
#define realloc mrl_realloc
#define free mrl_free
'''
        code = code.replace("static void mrl_runtime_fail", hook + "static void mrl_runtime_fail", 1)
        code = code.replace("    return 0;\n}", "    return mrl_blocks ? 99 : 0;\n}", 1)
        with tempfile.TemporaryDirectory(prefix="mrl-v9-values-") as directory:
            source, executable = Path(directory) / "source.c", Path(directory) / "source.exe"
            source.write_text(code, encoding="utf-8")
            build_c(source, executable)
            run = subprocess.run([str(executable)], capture_output=True, text=True, timeout=10)
        self.assertEqual((run.returncode, run.stdout.splitlines()), (0, expected or ["alive", "13"]))


if __name__ == "__main__": unittest.main()
