import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from mrl.toolchain import build_c, find_compiler

ROOT = Path(__file__).parents[1]


@unittest.skipUnless(find_compiler()[0], "toolchain")
class KnowledgePersistTests(unittest.TestCase):
 def test_checkpoint_and_journal_recovery(self):
  with tempfile.TemporaryDirectory(prefix="mrl-persist-") as directory:
   root = Path(directory)
   for name in ("knowledge_store.h", "knowledge_persist.h", "knowledge_engine.h", "knowledge_cache.h"):
    shutil.copyfile(ROOT / "runtime" / name, root / name)
   source = root / "persist.c"
   executable = root / "persist.exe"
   source.write_text(r'''
#include <stdio.h>
#include <string.h>
#include "knowledge_cache.h"
static int seen;
static bool replay(const void *p,uint32_t n,void *x){(void)x;return (n==3&&((const char*)p)[0]=='o')||(n==3&&((const char*)p)[0]=='t')?(++seen,true):false;}
static int cut(const char *from,const char *to){FILE *a=fopen(from,"rb"),*b=fopen(to,"wb");int c,last=-1;if(!a||!b)return 0;while((c=fgetc(a))!=EOF){if(last>=0&&fputc(last,b)==EOF)return 0;last=c;}fclose(a);fclose(b);return last>=0;}
int main(void){
 const char *checkpoint="check-\354\247\200\354\213\235\360\237\231\202.bin",*journal="updates.bin";
 MrlKnowledgeStore*s=mrl_knowledge_store_new(8000000),*r;MrlKnowledgeSymbol id,id2,sub,pred,obj,src,txt;MrlKnowledgeFact a={0},b={0},row;const char*error=0;FILE*f;
 if(!s||!mrl_knowledge_store_intern(s,"fact",&id)||!mrl_knowledge_store_intern(s,"fact2",&id2)||!mrl_knowledge_store_intern(s,"\354\243\274\354\226\264",&sub)||!mrl_knowledge_store_intern(s,"knows",&pred)||!mrl_knowledge_store_intern(s,"\360\237\231\202",&obj)||!mrl_knowledge_store_intern(s,"source",&src)||!mrl_knowledge_store_intern(s,"our",&txt))return 1;
 a=(MrlKnowledgeFact){0,id,sub,pred,obj,1,1,2,1,src,txt,1,4}; b=(MrlKnowledgeFact){0,id2,sub,pred,obj,0,0,0,1,0,0,0,0};
 if(!mrl_knowledge_store_append(s,a,0)||!mrl_knowledge_store_append(s,b,0)||!mrl_knowledge_store_remove(s,1)||mrl_knowledge_checkpoint_save(s,checkpoint,0x123456789abcdef0ull))return 2;
 r=mrl_knowledge_checkpoint_open(checkpoint,8000000,0x123456789abcdef0ull,&error);
 if(!r)return 31;if(r->version!=s->version)return 32;if(r->next_id!=2)return 33;if(r->count!=1)return 34;if(!mrl_knowledge_store_get_any_fact(r,1,&row)||row.live||row.evidence_text!=txt)return 35;if(!mrl_knowledge_store_get_fact(r,2,&row))return 36;if(row.subject!=sub)return 37;if(strcmp(mrl_knowledge_store_symbol(r,obj),"\360\237\231\202"))return 39;
 mrl_knowledge_store_release(r);r=mrl_knowledge_checkpoint_open(checkpoint,8000000,7,&error);if(r||!error)return 4;
 if(mrl_knowledge_checkpoint_save(s,"check.bin",0x123456789abcdef0ull))return 5;
 f=fopen("check.bin","r+b");if(!f||fseek(f,20,SEEK_SET)||fputc(7,f)==EOF||fclose(f))return 6;
 r=mrl_knowledge_checkpoint_open("check.bin",8000000,0x123456789abcdef0ull,&error);if(r||!error)return 7;
 if(mrl_knowledge_checkpoint_save(s,"check.bin",0x123456789abcdef0ull)||!cut("check.bin","torn.bin"))return 8;
 r=mrl_knowledge_checkpoint_open("torn.bin",8000000,0x123456789abcdef0ull,&error);if(r||!error)return 8;
 if(mrl_knowledge_journal_append(journal,"one",3)||mrl_knowledge_journal_append(journal,"two",3))return 9;
 f=fopen(journal,"ab");if(!f||!mrl_knowledge_write_u32(f,9)||fclose(f))return 10;seen=0;
 if(mrl_knowledge_journal_replay(journal,replay,0)||seen!=2)return 11;
 f=fopen(journal,"r+b");if(!f||fseek(f,4,SEEK_SET)||fputc('X',f)==EOF||fclose(f))return 12;
 if(!mrl_knowledge_journal_replay(journal,replay,0))return 13;
 {MrlKnowledgeStore*cache=mrl_knowledge_store_new(1000000);MrlKnowledgeEngine e,c;if(!cache||!mrl_knowledge_engine_init(&e,0,0,1000)||!mrl_knowledge_close(&e)||mrl_knowledge_engine_cache_save(&e,cache,"prepared.cache",0x123456789abcdef0ull)||!mrl_knowledge_engine_init(&c,0,0,1000)||mrl_knowledge_engine_cache_load(&c,cache,"prepared.cache",0x123456789abcdef0ull)||!c.complete)return 14;mrl_knowledge_engine_free(&e);mrl_knowledge_engine_free(&c);mrl_knowledge_store_release(cache);}
 mrl_knowledge_store_release(s);return 0;
}''', encoding="utf-8")
   build_c(source, executable)
   result = subprocess.run([str(executable)], cwd=root, capture_output=True, text=True)
   self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
 unittest.main()
