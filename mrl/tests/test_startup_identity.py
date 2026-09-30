import json
import tempfile
import unittest
from pathlib import Path

from mrl.horn_bridge import emit_v7_support
from mrl.toolchain import build_c, find_compiler


@unittest.skipUnless(find_compiler()[0], "toolchain")
class StartupIdentityTests(unittest.TestCase):
    def test_cache_identity_survives_rule_startup_and_journal_restore(self):
        plan = {"facts": [{"id": "base", "triple": ["a", "p", "b"], "polarity": True,
                 "modality": "asserted", "evidence": {}}], "rules": [{"id": "rule", "version": None,
                 "body": [["constant", "p", "x"]], "head": ["constant", "q", "x"]}],
                "capacity": 8, "memory_budget": 8_000_000}
        support = emit_v7_support([plan])
        with tempfile.TemporaryDirectory(prefix="mrl-startup-id-") as directory:
            root = Path(directory)
            source, executable = root / "identity.c", root / "identity.exe"
            (root / "bad.jsonl").write_text(json.dumps({"id": "new", "triple": ["new-s", "new-p", "new-o"]}) + "\n{bad}\n", encoding="utf-8")
            source.write_text("#include <stdlib.h>\nstatic void mrl_runtime_fail(const char *message){(void)message;abort();}\n" + support + r'''
int main(void){
 const uint64_t fp=mrl_horn_v7_fingerprint(&mrl_horn_plan_0); MrlHornPlan *p=mrl_horn_plan_new(&mrl_horn_plan_0),*q=mrl_horn_plan_new(&mrl_horn_plan_0),*r=mrl_horn_plan_new(&mrl_horn_plan_0); MrlHornLoadResult result; char journal[512]; size_t facts; uint64_t version; uint32_t symbols,base;
 if(strcmp(mrl_knowledge_engine_cache_save(NULL,NULL,NULL,0),"knowledge cache incomplete")||strcmp(mrl_knowledge_engine_cache_load(NULL,NULL,NULL,0),"knowledge cache stale"))return 11;
 if(mrl_knowledge_persist_save(p->store,"pre.bin",fp))return 1;
 if(!mrl_horn_v7_sync(p,p->template->capacity,1000000))return 2;
 if(mrl_knowledge_engine_cache_save(&p->engine,p->store,"pre.bin.cache",fp))return 3;
 result=mrl_horn_plan_restore(&q,"pre.bin"); if(!result.ok||!q->cache_hit)return 4;
 facts=q->store->count;version=q->store->version;symbols=q->store->symbols->next;base=mrl_knowledge_store_find_symbol(q->store,"base");
 result=mrl_horn_plan_load(&q,"bad.jsonl");if(result.ok||q->store->count!=facts||q->store->version!=version||q->store->symbols->next!=symbols||mrl_knowledge_store_find_symbol(q->store,"base")!=base||mrl_knowledge_store_find_symbol(q->store,"new"))return 13;
 result=mrl_horn_plan_save(q,"state.bin"); if(!result.ok)return 5;
 if(strlen(q->durable_journal)>=sizeof(journal))return 6; strcpy(journal,q->durable_journal);
 if(!mrl_horn_plan_add(&q,"row","a","p","b",true,"asserted",(MrlHornEvidence){0}))return 7;
 result=mrl_horn_plan_commit(&q,"state.bin"); if(!result.ok)return 8;
 result=mrl_horn_plan_restore(&r,"state.bin"); if(!result.ok||r->store->count!=2||strcmp(journal,r->durable_journal))return 9;
 {MrlKnowledgeStore *one=mrl_knowledge_store_new(1000000),*two=mrl_knowledge_store_new(1000000);MrlKnowledgeEngine saved,loaded;uint32_t id;
  if(!one||!two||!mrl_knowledge_store_intern(one,"one",&id)||!mrl_knowledge_store_intern(two,"two",&id)||!mrl_knowledge_engine_init(&saved,0,0,1000)||!mrl_knowledge_close(&saved)||mrl_knowledge_engine_cache_save(&saved,one,"different.cache",7)||!mrl_knowledge_engine_init(&loaded,0,0,1000)||!mrl_knowledge_engine_cache_load(&loaded,two,"different.cache",7))return 10;
  mrl_knowledge_engine_free(&saved);mrl_knowledge_engine_free(&loaded);mrl_knowledge_store_release(one);mrl_knowledge_store_release(two);}
 mrl_horn_plan_release(p);mrl_horn_plan_release(q);mrl_horn_plan_release(r);return 0;
}''', encoding="utf-8")
            build_c(source, executable)
            self.assertEqual(__import__("subprocess").run([str(executable)], cwd=root, timeout=10).returncode, 0)


if __name__ == "__main__": unittest.main()
