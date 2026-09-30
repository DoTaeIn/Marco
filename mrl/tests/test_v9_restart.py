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
class V9RestartTests(unittest.TestCase):
 def test_save_commit_restore_cache_and_journal_recovery(self):
  with tempfile.TemporaryDirectory(prefix="mrl-v9-restart-") as directory:
   path = json.dumps(str(Path(directory, "state.bin")).replace("\\", "/"))
   source = '''#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
static void mrl_runtime_fail(const char*message){fputs(message,stderr);exit(90);}
''' + _header("knowledge_store.h") + _header("knowledge_engine.h") + _header("horn_jsonl.h") + _header("knowledge_persist.h") + _header("knowledge_cache.h") + _header("knowledge_journal.h") + _header("horn_runtime_v7.h") + r'''
int main(void){
 MrlHornPlanRule rules[]={{"pq",NULL,1,{{"?x","p","?y"}},{"?x","q","?y"}}};
 MrlHornPlanTemplate t={0,0,rules,1,16,8000000};MrlHornPlan*p=mrl_horn_plan_new(&t),*fresh=mrl_horn_plan_new(&t),*unchanged=mrl_horn_plan_new(&t);MrlHornLoadResult r;MrlHornSnapshot*changes;FILE*f;
 if(!mrl_horn_plan_add(&p,"first","a","p","b",1,"asserted",(MrlHornEvidence){0}))return 1;
 r=mrl_horn_plan_save(p,''' + path + r''');if(!r.ok||r.value!=1||mrl_horn_plan_count(p,NULL,"q",NULL)!=1)return 2;
 if(!mrl_horn_plan_add(&p,"second","c","p","b",1,"asserted",(MrlHornEvidence){0})||(r=mrl_horn_plan_commit(&p,''' + path + r'''),!r.ok))return 3;
 r=mrl_horn_plan_restore(&fresh,''' + path + r''');if(!r.ok||!fresh->cache_hit||mrl_horn_plan_count(fresh,NULL,"q",NULL)!=2)return 4;
 changes=mrl_horn_plan_changes(fresh);if(!changes||changes->added!=2){if(changes)mrl_horn_snapshot_release(changes);return 5;}mrl_horn_snapshot_release(changes);
 if(!mrl_horn_plan_correct(&fresh,"first","a","r","b",1,"asserted",(MrlHornEvidence){0})||!mrl_horn_plan_remove(&fresh,"second")||(r=mrl_horn_plan_commit(&fresh,''' + path + r'''),!r.ok))return 6;
 mrl_horn_plan_release(fresh);fresh=mrl_horn_plan_new(&t);r=mrl_horn_plan_restore(&fresh,''' + path + r''');if(!r.ok||!fresh->cache_hit||fresh->store->count!=1||mrl_horn_plan_count(fresh,NULL,"q",NULL)!=0)return 7;
 f=fopen(fresh->durable_journal,"ab");if(!f||fwrite("bad",1,3,f)!=3||fclose(f))return 8;
 mrl_horn_plan_release(fresh);fresh=mrl_horn_plan_new(&t);r=mrl_horn_plan_restore(&fresh,''' + path + r''');if(!r.ok||!fresh->journal_needs_repair||fresh->store->count!=1)return 9;
 if(!mrl_horn_plan_add(&fresh,"third","z","p","b",1,"asserted",(MrlHornEvidence){0})||(r=mrl_horn_plan_commit(&fresh,''' + path + r'''),!r.ok))return 10;
 mrl_horn_plan_release(fresh);fresh=mrl_horn_plan_new(&t);r=mrl_horn_plan_restore(&fresh,''' + path + r''');if(!r.ok||mrl_horn_plan_count(fresh,NULL,"q",NULL)!=1)return 11;
 f=fopen(fresh->durable_journal,"r+b");if(!f||fseek(f,4,SEEK_SET)||fputc('X',f)==EOF||fclose(f))return 12;
 r=mrl_horn_plan_restore(&unchanged,''' + path + r''');if(r.ok||unchanged->store->count!=0)return 13;
 mrl_horn_plan_release(unchanged);mrl_horn_plan_release(fresh);mrl_horn_plan_release(p);return 0;
}'''
   c, exe = Path(directory, "restart.c"), Path(directory, "restart.exe")
   c.write_text(source, encoding="utf-8")
   try:
    build_c(c, exe)
   except subprocess.CalledProcessError as error:
    self.fail(error.stderr.decode(errors="replace"))
   result = subprocess.run([str(exe)], cwd=directory, capture_output=True, text=True)
   self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
 unittest.main()
