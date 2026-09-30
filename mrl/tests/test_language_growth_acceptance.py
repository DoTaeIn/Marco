"""Keep retained answer snapshots from invalidating the live incremental engine."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from mrl.tests.test_v7_runtime import _header
from mrl.toolchain import build_c


class RetainedAnswerGrowthTests(unittest.TestCase):
    def test_answer_snapshot_does_not_force_engine_rebuild_on_append(self):
        source = r'''#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
static void mrl_runtime_fail(const char*s){fprintf(stderr,"%s",s);exit(90);}
''' + "\n".join(_header(name) for name in (
            "knowledge_store.h", "knowledge_engine.h", "horn_jsonl.h",
            "knowledge_persist.h", "knowledge_cache.h", "knowledge_journal.h", "horn_runtime_v7.h")) + r'''
int main(void){
 MrlHornPlanFact facts[]={{"first","a","p","c","asserted",1,{0}}};
 MrlHornPlanRule rules[]={{"pq",NULL,1,{{"?x","p","?y"}},{"?x","q","?y"}}};
 MrlHornPlanTemplate t={facts,1,rules,1,16,3000000};
 MrlHornPlan*p=mrl_horn_plan_new(&t);
 MrlHornSnapshot*answer=mrl_horn_plan_select(p,"a","q","c");
 if(answer->count!=1||!p->engine_ready)return 1;
 if(!mrl_horn_plan_add(&p,"later","b","p","c",true,"asserted",(MrlHornEvidence){0}))return 2;
 if(!p->engine_ready){fputs("retained answer discarded incremental engine",stderr);return 3;}
 if(mrl_horn_plan_count(p,"b","q","c")!=1)return 4;
 if(answer->count!=1||strcmp(mrl_horn_snapshot_term(answer,0,0),"a"))return 5;
 if(!mrl_horn_plan_remove(&p,"first")||mrl_horn_plan_count(p,"a","q","c"))return 6;
 if(strcmp(mrl_horn_snapshot_term(answer,0,0),"a")||strcmp(mrl_horn_snapshot_proof_rule(answer,0,0),"pq"))return 7;
 mrl_horn_snapshot_release(answer);mrl_horn_plan_release(p);return 0;
}
'''
        with tempfile.TemporaryDirectory(prefix="mrl-growth-acceptance-") as directory:
            c, exe = Path(directory)/"check.c", Path(directory)/"check.exe"
            c.write_text(source,encoding="utf-8")
            build_c(c,exe)
            result=subprocess.run([str(exe)],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)


if __name__=="__main__":unittest.main()
