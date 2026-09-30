import subprocess
import tempfile
import unittest
from pathlib import Path

from mrl.toolchain import build_c, find_compiler


ROOT = Path(__file__).parents[1]


@unittest.skipUnless(find_compiler()[0], "toolchain")
class StartupSymbolTests(unittest.TestCase):
    def test_reserve_preserves_shared_ids_and_oom_state(self):
        with tempfile.TemporaryDirectory(prefix="mrl-symbols-") as directory:
            root = Path(directory)
            c, exe = root / "symbols.c", root / "symbols.exe"
            c.write_text(
                "#include <string.h>\n" + (ROOT / "runtime" / "knowledge_store.h").read_text(encoding="utf-8") + r'''
int main(void){
 MrlKnowledgeStore*s=mrl_knowledge_store_new(2000000),*old,*low,*packed,*packed_snapshot;MrlKnowledgeSymbol a,b,c;MrlKnowledgeFact f={0};size_t used,budget,buckets,ids;
 if(!s||!mrl_knowledge_store_intern(s,"alpha",&a)||!mrl_knowledge_store_intern(s,"beta",&b)||a!=1||b!=2||mrl_knowledge_store_find_symbol(s,"beta")!=b)return 1;
 old=mrl_knowledge_store_snapshot(s);if(!old||!ks_symbols_reserve(s,10000)||s->symbols!=old->symbols||s->symbols->buckets<10000||s->symbols->id_cap<=10000)return 2;
 if(!mrl_knowledge_store_intern(s,"gamma",&c)||c!=3||mrl_knowledge_store_find_symbol(old,"gamma")!=c||strcmp(mrl_knowledge_store_symbol(old,c),"gamma"))return 3;
 f.predicate=a;if(!mrl_knowledge_store_append(s,f,1)||mrl_knowledge_store_fact_count(s)!=1||mrl_knowledge_store_fact_count(old)!=0||s->root==old->root)return 4;
 mrl_knowledge_store_release(old);mrl_knowledge_store_release(s);
 low=mrl_knowledge_store_new(1000000);if(!low||!mrl_knowledge_store_intern(low,"stable",&a))return 5;
 used=low->memory->used;budget=low->memory->budget;buckets=low->symbols->buckets;ids=low->symbols->id_cap;
 low->memory->budget=used+sizeof(KsAllocation)+16384*sizeof(*low->symbols->bucket);
 if(ks_symbols_reserve(low,10000)||low->memory->used!=used||low->symbols->buckets!=buckets||low->symbols->id_cap!=ids||low->symbols->next!=1||mrl_knowledge_store_find_symbol(low,"stable")!=a)return 6;
 low->memory->budget=budget;if(!ks_symbols_reserve(low,10000)||!mrl_knowledge_store_intern(low,"after-oom",&b)||b!=2||mrl_knowledge_store_find_symbol(low,"after-oom")!=b)return 7;
 mrl_knowledge_store_release(low);
 packed=mrl_knowledge_store_new(1000000);if(!packed||!ks_symbols_reserve(packed,4))return 8;
 used=packed->memory->used;budget=packed->memory->budget;packed->memory->budget=used;
 if(ks_restore_symbol(packed,"one",3,1)||packed->memory->used!=used||packed->symbols->next||packed->symbols->restore_prefix)return 9;
 packed->memory->budget=used+sizeof(KsAllocation)+sizeof(KsSymbolBlock)+sizeof(MrlKnowledgeSymbolRow)+4;
 if(!ks_restore_symbol(packed,"one",3,1)||packed->symbols->restore_blocks->capacity!=sizeof(MrlKnowledgeSymbolRow)+4)return 10;
 packed->memory->budget=budget;if(packed->symbols->restore_prefix!=1||ks_restore_symbol(packed,"one",3,2)||ks_restore_symbol(packed,"two",3,3)||!ks_restore_symbol(packed,"two",3,2))return 11;
 packed_snapshot=mrl_knowledge_store_snapshot(packed);if(!packed_snapshot||!mrl_knowledge_store_intern(packed,"three",&c)||c!=3||mrl_knowledge_store_find_symbol(packed_snapshot,"three")!=3)return 11;
 mrl_knowledge_store_release(packed);if(mrl_knowledge_store_find_symbol(packed_snapshot,"one")!=1||mrl_knowledge_store_find_symbol(packed_snapshot,"two")!=2||mrl_knowledge_store_find_symbol(packed_snapshot,"three")!=3)return 12;
 mrl_knowledge_store_release(packed_snapshot);return 0;
}''',
                encoding="utf-8",
            )
            try:
                build_c(c, exe)
            except subprocess.CalledProcessError as error:
                self.fail(error.stderr.decode(errors="replace"))
            result = subprocess.run([str(exe)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
