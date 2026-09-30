import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from mrl.toolchain import build_c, find_compiler

ROOT = Path(__file__).parents[1]


def _header(name):
    return "\n".join(line for line in (ROOT / "runtime" / name).read_text(encoding="utf-8").splitlines() if not line.startswith('#include "')) + "\n"


@unittest.skipUnless(find_compiler()[0], "toolchain")
class V7RuntimeTests(unittest.TestCase):
    def test_denial_fixture_snapshots_scalars_proofs_and_cleanup(self):
        case = json.loads((ROOT / "tests/fixtures/ninth_knowledge_cases.json").read_text(encoding="utf-8"))[6]
        initial, after_remove = (len(row["known"]["$tuple_map"]) for row in case["expected"])
        source = '''#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
static size_t allocations;
static void* counted_calloc(size_t n,size_t s){void*p=calloc(n,s);if(p)allocations++;return p;}
static void counted_free(void*p){if(p)allocations--;free(p);}
#define calloc counted_calloc
#define free counted_free
static void mrl_runtime_fail(const char*message){fputs(message,stderr);exit(90);}
''' + _header("knowledge_store.h") + _header("knowledge_engine.h") + _header("horn_jsonl.h") + _header("knowledge_persist.h") + _header("knowledge_cache.h") + _header("knowledge_journal.h") + _header("horn_runtime_v7.h") + r'''
static int proof(const MrlHornSnapshot*s){for(size_t i=0;i<s->count;i++){const MrlHornSnapshotRow*r=s->rows+i;if(r->rule==0)return r->parent_count==1&&!strcmp(mrl_knowledge_store_symbol(s->store,r->parents[0][1]),"p");}return 0;}
int main(){
 MrlHornPlanFact facts[]={{"yes","a","p","b","asserted",1,{0}},{"deny","a","q","b","asserted",0,{0}},{"plan","z","p","b","planned",1,{0}},{"cond","w","p","b","conditional",1,{0}}};
 MrlHornPlanRule rules[]={{"pq",NULL,1,{{"?x","p","?y"}},{"?x","q","?y"}}};
 MrlHornPlanTemplate t={facts,4,rules,1,16,3000000};MrlHornPlan*p=mrl_horn_plan_new(&t);MrlHornSnapshot*old=mrl_horn_plan_select(p,NULL,NULL,NULL),*now,*changes;
 if(!old||old->count!=''' + str(initial) + r'''||!mrl_horn_plan_exists(p,"a","p","b")||mrl_horn_plan_exists(p,"a","q","b")||mrl_horn_plan_count(p,"z",NULL,NULL))return 1;
 if(!mrl_horn_plan_remove(&p,"deny"))return 2;now=mrl_horn_plan_select(p,NULL,NULL,NULL);if(!now||now->count!=''' + str(after_remove) + r'''||!mrl_horn_plan_exists(p,"a","q","b")||!proof(now)||old->count!=''' + str(initial) + r''')return 3;
 changes=mrl_horn_plan_changes(p);if(!changes||!changes->added||changes->removed){return 4;}mrl_horn_snapshot_release(changes);
 if(!mrl_horn_plan_correct(&p,"yes","x","p","b",true,"asserted",(MrlHornEvidence){0}))return 5;mrl_horn_snapshot_release(now);now=mrl_horn_plan_select(p,NULL,NULL,NULL);
 if(!now||now->count!=2||mrl_horn_plan_exists(p,"a","q","b")||!mrl_horn_plan_exists(p,"x","q","b")||old->count!=''' + str(initial) + r''')return 6;
 mrl_horn_snapshot_release(now);mrl_horn_snapshot_release(old);mrl_horn_plan_release(p);return allocations?7:0;}
'''
        with tempfile.TemporaryDirectory(prefix="mrl-v7-runtime-") as directory:
            c, exe = Path(directory) / "v7.c", Path(directory) / "v7.exe"
            c.write_text(source, encoding="utf-8")
            try:
                build_c(c, exe)
            except subprocess.CalledProcessError as error:
                self.fail(error.stderr.decode(errors="replace"))
            result = subprocess.run([str(exe)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_jsonl_load_is_atomic_and_checkpoint_rejects_other_rules(self):
        with tempfile.TemporaryDirectory(prefix="mrl-v7-files-") as directory:
            directory = Path(directory)
            valid, invalid, duplicate, empty, checkpoint = (directory / name for name in ("valid.jsonl", "invalid.jsonl", "duplicate.jsonl", "empty.jsonl", "state.bin"))
            valid.write_text('{"id":"유","triple":["가","p","🙂"],"evidence":{"source":"가🙂","text":"🙂","start":1,"end":2}}\n', encoding="utf-8")
            invalid.write_text(valid.read_text(encoding="utf-8") + '{"id":"broken"\n', encoding="utf-8")
            duplicate.write_text(valid.read_text(encoding="utf-8") * 2, encoding="utf-8")
            empty.write_text("\n\n", encoding="utf-8")
            quote = lambda path: json.dumps(str(path).replace("\\", "/"))
            source = '''#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
static size_t allocations;
static void* counted_calloc(size_t n,size_t s){void*p=calloc(n,s);if(p)allocations++;return p;}
static void counted_free(void*p){if(p)allocations--;free(p);}
#define calloc counted_calloc
#define free counted_free
static void mrl_runtime_fail(const char*message){fputs(message,stderr);exit(90);}
''' + _header("knowledge_store.h") + _header("knowledge_engine.h") + _header("horn_jsonl.h") + _header("knowledge_persist.h") + _header("knowledge_cache.h") + _header("knowledge_journal.h") + _header("horn_runtime_v7.h") + r'''
int main(){MrlHornPlanRule rules[]={{"pq",NULL,1,{{"?x","p","?y"}},{"?x","q","?y"}}},wrong[]={{"pr",NULL,1,{{"?x","p","?y"}},{"?x","r","?y"}}};MrlHornPlanTemplate t={0,0,rules,1,16,3000000},bad={0,0,wrong,1,16,3000000};MrlHornPlan*p=mrl_horn_plan_new(&t),*restored=mrl_horn_plan_new(&t),*other=mrl_horn_plan_new(&bad);MrlHornLoadResult r;size_t count=p->store->count;uint64_t version=p->store->version;uint32_t symbols=p->store->symbols->next;MrlHornSnapshot*x;
 r=mrl_horn_plan_load(&p,''' + quote(invalid) + r''');if(r.ok||p->store->count!=count||p->store->version!=version||p->store->symbols->next!=symbols)return 1;
 r=mrl_horn_plan_load(&p,''' + quote(duplicate) + r''');if(r.ok||p->store->count!=count||p->store->version!=version||p->store->symbols->next!=symbols)return 2;
 r=mrl_horn_plan_load(&p,''' + quote(empty) + r''');if(!r.ok||r.value||p->store->count!=count)return 3;
 r=mrl_horn_plan_load(&p,''' + quote(valid) + r''');if(!r.ok||r.value!=1||p->store->count!=1||!mrl_horn_plan_exists(p,"가","q","🙂"))return 4;
 x=mrl_horn_plan_explain(p,"가","q","🙂");if(!x||!x->complete||x->count!=2){return 5;}mrl_horn_snapshot_release(x);
 r=mrl_horn_plan_save(p,''' + quote(checkpoint) + r''');if(!r.ok||r.value!=1)return 6;r=mrl_horn_plan_restore(&restored,''' + quote(checkpoint) + r''');if(!r.ok||r.value!=1||!mrl_horn_plan_exists(restored,"가","q","🙂"))return 7;
 r=mrl_horn_plan_restore(&other,''' + quote(checkpoint) + r''');if(r.ok)return 8;mrl_horn_plan_release(other);mrl_horn_plan_release(restored);mrl_horn_plan_release(p);return allocations?9:0;}'''
            c, exe = directory / "files.c", directory / "files.exe"
            source = source.replace("#define calloc counted_calloc\n#define free counted_free\n", "")
            c.write_text(source, encoding="utf-8")
            try:
                build_c(c, exe)
            except subprocess.CalledProcessError as error:
                self.fail(error.stderr.decode(errors="replace"))
            result = subprocess.run([str(exe)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
