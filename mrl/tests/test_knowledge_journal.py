import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from mrl.toolchain import build_c, find_compiler

ROOT = Path(__file__).parents[1]


@unittest.skipUnless(find_compiler()[0], "toolchain")
class KnowledgeJournalTests(unittest.TestCase):
 def test_checkpoint_delta_replay_torn_and_crc(self):
  with tempfile.TemporaryDirectory(prefix="mrl-journal-") as directory:
   root = Path(directory)
   for name in ("knowledge_store.h", "knowledge_persist.h", "knowledge_journal.h"):
    shutil.copyfile(ROOT / "runtime" / name, root / name)
   source, executable = root / "journal.c", root / "journal.exe"
   source.write_text(r'''
#include <stdio.h>
#include <string.h>
#include "knowledge_journal.h"
static int copy(const char*a,const char*b){FILE*x=fopen(a,"rb"),*y=fopen(b,"wb");int c;if(!x||!y)return 0;while((c=fgetc(x))!=EOF)if(fputc(c,y)==EOF)return 0;return !fclose(x)&&!fclose(y);}
static int cut(const char*a,const char*b){FILE*x=fopen(a,"rb"),*y=fopen(b,"wb");int c,last=-1;if(!x||!y)return 0;while((c=fgetc(x))!=EOF){if(last>=0&&fputc(last,y)==EOF)return 0;last=c;}return last>=0&&!fclose(x)&&!fclose(y);}
int main(void){
 const char*check="base.bin",*journal="delta.bin";const uint64_t fp=UINT64_C(0x123456789abcdef0);const char*e=0;MrlKnowledgeStore*s=mrl_knowledge_store_new(8000000),*r;MrlKnowledgeSymbol id1,id2,id3,id4,sub,pred,obj,obj2;MrlKnowledgeFact a={0},b={0},f;uint64_t v;uint32_t rows,syms;FILE*x;
 if(!s||!mrl_knowledge_store_intern(s,"one",&id1)||!mrl_knowledge_store_intern(s,"two",&id2)||!mrl_knowledge_store_intern(s,"three",&id3)||!mrl_knowledge_store_intern(s,"alice",&sub)||!mrl_knowledge_store_intern(s,"likes",&pred)||!mrl_knowledge_store_intern(s,"tea",&obj)||!mrl_knowledge_store_intern(s,"coffee",&obj2))return 1;
 a=(MrlKnowledgeFact){0,id1,sub,pred,obj,0,1,0,1};b=(MrlKnowledgeFact){0,id2,sub,pred,obj,0,0,0,1};if(!mrl_knowledge_store_append(s,a,0)||!mrl_knowledge_store_append(s,b,0)||mrl_knowledge_checkpoint_save(s,check,fp))return 2;
 v=s->version;rows=(uint32_t)s->next_id;syms=s->symbols->next;if(!mrl_knowledge_store_intern(s,"four",&id4)||(f=(MrlKnowledgeFact){0,id1,sub,pred,obj2,0,1,0,1},!mrl_knowledge_store_correct(s,1,f))||!mrl_knowledge_store_remove(s,1)||(f=(MrlKnowledgeFact){0,id2,sub,pred,obj2,0,0,0,1},!mrl_knowledge_store_correct(s,2,f))||(f=(MrlKnowledgeFact){0,id3,sub,pred,obj,0,1,0,1},!mrl_knowledge_store_append(s,f,0))||(f=(MrlKnowledgeFact){0,id4,sub,pred,obj,0,1,0,1},!mrl_knowledge_store_append(s,f,0))||!mrl_knowledge_store_remove(s,4)||mrl_knowledge_delta_commit(s,journal,fp,v,rows,syms))return 3;
 v=s->version;rows=(uint32_t)s->next_id;syms=s->symbols->next;f=(MrlKnowledgeFact){0,id3,sub,pred,obj2,0,1,0,1};if(!mrl_knowledge_store_correct(s,3,f)||mrl_knowledge_delta_commit(s,journal,fp,v,rows,syms)||!cut(journal,"torn.bin"))return 4;
 r=mrl_knowledge_checkpoint_open(check,8000000,fp,&e);if(!r||mrl_knowledge_delta_replay(&r,"torn.bin",fp)||r->version!=v||r->next_id!=4||r->count!=2||mrl_knowledge_store_get_fact(r,1,&f)||!mrl_knowledge_store_get_any_fact(r,1,&f)||f.live||f.object!=obj2||!mrl_knowledge_store_get_fact(r,2,&f)||f.object!=obj2||!mrl_knowledge_store_get_fact(r,3,&f)||f.object!=obj||!mrl_knowledge_store_get_any_fact(r,4,&f)||f.live||strcmp(mrl_knowledge_store_symbol(r,id4),"four"))return 5;
 v=r->version;rows=(uint32_t)r->next_id;syms=r->symbols->next;f=(MrlKnowledgeFact){0,id3,sub,pred,obj2,0,1,0,1};if(!mrl_knowledge_store_correct(r,3,f)||mrl_knowledge_delta_repair("torn.bin")||mrl_knowledge_delta_commit(r,"torn.bin",fp,v,rows,syms))return 6;mrl_knowledge_store_release(r);
 r=mrl_knowledge_checkpoint_open(check,8000000,fp,&e);if(!r||mrl_knowledge_delta_replay(&r,"torn.bin",fp)||!mrl_knowledge_store_get_fact(r,3,&f)||f.object!=obj2)return 7;mrl_knowledge_store_release(r);
 if(!copy("torn.bin","corrupt.bin"))return 8;x=fopen("corrupt.bin","r+b");if(!x||fseek(x,4,SEEK_SET)||fputc('X',x)==EOF||fclose(x))return 9;r=mrl_knowledge_checkpoint_open(check,8000000,fp,&e);if(!r||!mrl_knowledge_delta_replay(&r,"corrupt.bin",fp))return 10;mrl_knowledge_store_release(r);mrl_knowledge_store_release(s);return 0;
}''', encoding="utf-8")
   build_c(source, executable)
   result = subprocess.run([str(executable)], cwd=root, capture_output=True, text=True)
   self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
 unittest.main()
