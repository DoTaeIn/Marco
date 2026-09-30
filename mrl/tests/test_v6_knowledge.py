"""Capacity, atomic input, COW and snapshot lifetime through source-to-C."""
import json, subprocess, tempfile, unittest
from pathlib import Path
from mrl import oracle, toolchain
from mrl.c_backend import emit_c
from mrl.frontend import compile_source

RULE='Rule(id="r",body=Triple(subject="?x",predicate="p",object="?y"),head=Triple(subject="?x",predicate="q",object="?y"))'
RULES=[{"id":"r","body":[["?x","p","?y"]],"head":["?x","q","?y"]}]
ALLOCATORS='''#include <stdlib.h>
#include <stdio.h>
static long blocks;
static void *tmalloc(size_t n){void*p=malloc(n);if(p)blocks++;return p;}
static void *tcalloc(size_t n,size_t s){void*p=calloc(n,s);if(p)blocks++;return p;}
static void *trealloc(void*p,size_t n){void*q=realloc(p,n);if(!p&&q)blocks++;return q;}
static void tfree(void*p){if(p)blocks--;free(p);}
#define malloc tmalloc
#define calloc tcalloc
#define realloc trealloc
#define free tfree
'''

def record(i,subject=None):
    return {"id":str(i),"subject":str(i) if subject is None else subject,"predicate":"p","object":"o"}

def reference(rows,operation="closure",rules=RULES,**options):
    facts=[{"id":r["id"],"triple":[r["subject"],r["predicate"],r["object"]],"evidence":r.get("evidence",{})} for r in rows]
    return oracle.evaluate({"operation":operation,"facts":facts,"rules":rules,"options":{"limit":256,**options}})

def execute(source,files=None,allocations=False):
    with tempfile.TemporaryDirectory(prefix="mrl-v6-knowledge-") as folder:
        root=Path(folder); paths={}
        for name,rows in (files or {}).items():
            path=root/name;paths[name]=json.dumps(path.as_posix())
            path.write_text(rows if isinstance(rows,str) else "\n".join(json.dumps(r,ensure_ascii=False) for r in rows),encoding="utf-8")
        if callable(source):source=source(paths)
        ir=compile_source(source)
        if ir["version"]!=6:raise AssertionError(ir["version"])
        code=emit_c(ir)
        if allocations:
            code=ALLOCATORS+code.replace("int main(void)","int original_main(void)")+'\nint main(void){original_main();if(blocks){fprintf(stderr,"live blocks: %ld\\n",blocks);return 91;}return 0;}\n'
        c=root/"source.c";exe=c.with_suffix(".exe");c.write_text(code,encoding="utf-8")
        try:toolchain.build_c(c,exe)
        except subprocess.CalledProcessError as error:raise AssertionError(error.stderr.decode(errors="replace")) from error
        return subprocess.run([str(exe)],capture_output=True,text=True,encoding="utf-8",timeout=20)

@unittest.skipUnless(toolchain.find_compiler()[0] is not None,"no C compiler")
class V6KnowledgeTests(unittest.TestCase):
    def lines(self,result):
        self.assertEqual((result.returncode,result.stderr),(0,""));return result.stdout.splitlines()

    def test_large_load_function_values_and_provenance(self):
        rows=[record(i) for i in range(70)]
        rows[0]["evidence"]={"source":"가🙂b","start":0,"end":2,"text":"가🙂"}
        source=lambda paths:f'''fn changed(p: Horn) -> Horn {{ p.add(Fact(id="new",subject="new",predicate="p",object="o")) return p }}
fn capture(p: Horn) -> Snapshot {{ return closure_with_provenance(p,limit=256,proof_limit=8,search_limit=4096) }}
fn main() {{ p=Horn(capacity=256,facts=Facts(),rules=Rules({RULE}))
 match(p.load({paths["facts.jsonl"]})) {{ Ok(n) {{ print(n) }} Err(e) {{ print(e) }} }}
 before=capture(p) copy=changed(p) after=capture(copy)
 print(p.version) print(copy.version) print(before) print(after) print(before) }}'''
        lines=self.lines(execute(source,{"facts.jsonl":rows},True));self.assertEqual(lines[:3],["70","1","2"])
        before,after,again=map(json.loads,lines[3:]);self.assertEqual(before,again)
        self.assertEqual(before,reference(rows,"closure_with_provenance",proof_limit=8,search_limit=4096))
        self.assertEqual(after,reference(rows+[record("new")],"closure_with_provenance",proof_limit=8,search_limit=4096))

    def test_atomic_load_and_selected_capacity(self):
        source=lambda paths:f'''fn main() {{ p=Horn(capacity=128,facts=Facts(Fact(id="seed",subject="seed",predicate="p",object="o")),rules=Rules())
 match(p.load({paths["bad.jsonl"]})) {{ Ok(n) {{ print(n) }} Err(e) {{ print("error") }} }}
 print(p.version) s=closure(p,limit=256) print(s.fact_count)
 match(p.load({paths["large.jsonl"]})) {{ Ok(n) {{ print(n) }} Err(e) {{ print("capacity") }} }}
 print(p.version) s:=closure(p,limit=256) print(s.fact_count)
 match(p.load({paths["empty.jsonl"]})) {{ Ok(n) {{ print(n) }} Err(e) {{ print(e) }} }} print(p.version) }}'''
        files={"bad.jsonl":[record("new"),record("seed")],"large.jsonl":[record(i) for i in range(128)],"empty.jsonl":""}
        self.assertEqual(self.lines(execute(source,files,True)),["error","0","1","capacity","0","1","0","0"])
        entries=",".join('Fact(id="%d",subject="s",predicate="p",object="o")'%i for i in range(128))
        result=execute('fn main(){p=Horn(capacity=128,facts=Facts('+entries+'),rules=Rules()) p.add(Fact(id="overflow",subject="s",predicate="p",object="o"))}')
        self.assertNotEqual(result.returncode,0);self.assertIn("native_capacity",result.stderr)

    def test_snapshot_loops_and_delta_release_storage(self):
        source=f'''fn capture(p: Horn) -> Snapshot {{ return closure(p,limit=256) }}
fn main() {{ p=Horn(capacity=256,facts=Facts(Fact(id="a",subject="a",predicate="p",object="o")),rules=Rules({RULE}))
 old=capture(p) current=capture(p)
 for(i in 0..200) {{ current:=capture(p) temporary=capture(p) }}
 p.add(Fact(id="b",subject="b",predicate="p",object="o")) current:=capture(p)
 print(old.fact_count) print(current.fact_count) print(old.version) print(current.version)
 p.remove("a") current:=capture(p) print(current.fact_count) }}'''
        self.assertEqual(self.lines(execute(source,allocations=True)),["2","4","0","1","2"])

    def test_full_selected_16384_capacity(self):
        rows=[record(i) for i in range(16384)]
        source=lambda paths: 'fn main(){p=Horn(capacity=16384,facts=Facts(),rules=Rules()) match(p.load('+paths["facts.jsonl"]+')){Ok(n){print(n)}Err(e){print(e)}} result=closure(p,limit=16384) print(result.fact_count) print(result.complete)}'
        self.assertEqual(self.lines(execute(source,{"facts.jsonl":rows},True)),["16384","16384","true"])

    def test_asserted_supports_exceed_query_proof_budget(self):
        rows=[record(i,"same") for i in range(33)]
        source=lambda paths:f'''fn main() {{ p=Horn(capacity=128,facts=Facts(),rules=Rules())
 match(p.load({paths["facts.jsonl"]})) {{ Ok(n) {{ }} Err(e) {{ print(e) }} }}
 result=closure_with_provenance(p,limit=256,proof_limit=1,search_limit=4096) print(result) }}'''
        lines=self.lines(execute(source,{"facts.jsonl":rows},True))
        self.assertEqual(json.loads(lines[0]),reference(rows,"closure_with_provenance",rules=[],proof_limit=1,search_limit=4096))

if __name__=="__main__":unittest.main()
