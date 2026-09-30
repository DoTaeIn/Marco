import subprocess, tempfile, unittest
from pathlib import Path
from mrl.toolchain import build_c, find_compiler
ROOT=Path(__file__).parents[1]
@unittest.skipUnless(find_compiler()[0],"toolchain")
class StoreTests(unittest.TestCase):
 def _run_c(self, source):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);c=p/'x.c';e=p/'x.exe';c.write_text(source,encoding='utf-8')
   try: build_c(c,e)
   except subprocess.CalledProcessError as error: self.fail(error.stderr.decode(errors='replace'))
   r=subprocess.run([str(e)],capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
 def test_symbol_pool(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);h=(ROOT/'runtime/knowledge_store.h').read_text();c=p/'s.c';e=p/'s.exe'
   c.write_text('#include <stdio.h>\n'+h+'''\nint main(){MrlKnowledgeStore*s=mrl_knowledge_store_new(30000000),*old;char b[32];MrlKnowledgeSymbol a,z;for(int i=0;i<100000;i++){sprintf(b,"id%d",i);if(!mrl_knowledge_store_intern(s,b,&a))return 1;}if(!mrl_knowledge_store_intern(s,"지식🙂",&z)||strcmp(mrl_knowledge_store_symbol(s,z),"지식🙂"))return 2;old=mrl_knowledge_store_snapshot(s);if(!mrl_knowledge_store_intern(s,"id42",&a)||a!=43||strcmp(mrl_knowledge_store_symbol(old,z),"지식🙂"))return 3;mrl_knowledge_store_release(old);mrl_knowledge_store_release(s);return 0;}''',encoding='utf-8')
   build_c(c,e);self.assertEqual(subprocess.run([str(e)]).returncode,0)
 def test_pages_snapshot_and_budget(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d); h=(ROOT/'runtime/knowledge_store.h').read_text(); c=p/'x.c'; e=p/'x.exe'
   c.write_text('#include <stdio.h>\n'+h+'''\nint main(){MrlKnowledgeStore*s=mrl_knowledge_store_new(30000000);MrlKnowledgeFact f={0};for(int i=0;i<100000;i++){f.predicate=i%11;if(!mrl_knowledge_store_append(s,f,1))return 1;}MrlKnowledgeStore*old=mrl_knowledge_store_snapshot(s);MrlKnowledgeFact a,b;f.predicate=99;if(!mrl_knowledge_store_get_fact(old,50000,&a)||!mrl_knowledge_store_append(s,f,1)||!mrl_knowledge_store_remove(s,50000)||!mrl_knowledge_store_correct(s,50001,f)||!mrl_knowledge_store_get_fact(old,50000,&b)||a.fact_id!=b.fact_id||b.predicate!=49999%11)return 2;MrlKnowledgeStore*low=mrl_knowledge_store_new(sizeof(MrlKnowledgeStore));if(low)return 3;mrl_knowledge_store_release(old);mrl_knowledge_store_release(s);return 0;}''',encoding='utf-8')
   build_c(c,e); r=subprocess.run([str(e)],capture_output=True); self.assertEqual(r.returncode,0)
 def test_indexes_changes_cow_and_shared_allocation_accounting(self):
  h=(ROOT/'runtime/knowledge_store.h').read_text()
  self._run_c(r'''#include <stdlib.h>
#include <string.h>
#include <stddef.h>
static size_t allocations;
static void* counted_calloc(size_t n,size_t s){void*p=calloc(n,s);if(p)allocations++;return p;}
static void counted_free(void*p){if(p)allocations--;free(p);}
#define calloc counted_calloc
#define free counted_free
'''+h+r'''
typedef struct {int n;uint64_t last;unsigned kinds;} Changes;
static bool predicate_row(const MrlKnowledgeFact*f,void*ctx){int*n=ctx;if(!f->live)return false;(*n)++;return true;}
static bool change_row(const MrlKnowledgeChange*c,void*ctx){Changes*x=ctx;if(c->version<=x->last)return false;x->last=c->version;x->kinds|=1u<<c->kind;x->n++;return true;}
int main(){MrlKnowledgeStore*s=mrl_knowledge_store_new(30000000),*old,*tiny;MrlKnowledgeFact f={0},before,now;MrlKnowledgeSymbol key;size_t base,after_snapshot;Changes changes={0};
 if(!s||!mrl_knowledge_store_intern(s,"stable-id",&key)||mrl_knowledge_store_find_symbol(s,"stable-id")!=key||!mrl_knowledge_store_symbol(s,key))return 1;
 for(int i=0;i<1000;i++){f=(MrlKnowledgeFact){.subject=(uint32_t)i,.predicate=(uint32_t)(i%3+1),.object=(uint32_t)(i+1)};if(!mrl_knowledge_store_append(s,f,1))return 2;}
 f=(MrlKnowledgeFact){.id=key,.subject=99,.predicate=1,.object=100};if(!mrl_knowledge_store_append(s,f,1)||mrl_knowledge_store_find_id(s,key)!=1001)return 3;
 base=mrl_knowledge_store_bytes(s);old=mrl_knowledge_store_snapshot(s);if(!old||old->root!=s->root||old->index!=s->index||old->log!=s->log||old->symbols!=s->symbols)return 4;
 after_snapshot=mrl_knowledge_store_bytes(s);if(after_snapshot<=base||after_snapshot-base>=2*(sizeof(MrlKnowledgeStore)+sizeof(KsAllocation)))return 5;
 if(!mrl_knowledge_store_get_fact(old,300,&before)||before.predicate!=3)return 6;
 f=(MrlKnowledgeFact){.subject=300,.predicate=9,.object=301};if(!mrl_knowledge_store_correct(s,300,f)||s->root==old->root||s->root->page[0]!=old->root->page[0]||s->root->page[1]==old->root->page[1])return 7;
 if(!mrl_knowledge_store_remove(s,700)||s->root->page[2]==old->root->page[2])return 8;
 f=(MrlKnowledgeFact){.id=key,.subject=101,.predicate=9,.object=102};if(!mrl_knowledge_store_correct(s,1001,f)||mrl_knowledge_store_find_id(s,key)!=1001)return 9;
 {int n=0;if(!mrl_knowledge_store_find_predicate(s,9,predicate_row,&n)||n!=2)return 10;}
 if(!mrl_knowledge_store_get_fact(old,300,&now)||now.predicate!=3||!mrl_knowledge_store_get_fact(old,700,&now)||mrl_knowledge_store_find_id(old,key)!=1001)return 11;
 if(mrl_knowledge_store_get_fact(s,700,&now)||!mrl_knowledge_store_get_any_fact(s,700,&now)||now.live)return 12;
 if(!mrl_knowledge_store_changes_since(s,mrl_knowledge_store_version(old),change_row,&changes)||changes.n!=3||changes.kinds!=(1u<<2|1u<<3))return 13;
 tiny=mrl_knowledge_store_new(100000);if(!tiny)return 14;base=tiny->memory->used;tiny->memory->budget=base+sizeof(MrlKnowledgeStore)+sizeof(KsAllocation)-1;if(mrl_knowledge_store_snapshot(tiny))return 15;mrl_knowledge_store_release(tiny);
 tiny=mrl_knowledge_store_new(100000);f=(MrlKnowledgeFact){.fact_id=1,.predicate=2,.live=1};if(!tiny||!mrl_knowledge_store_restore_row(tiny,f)||mrl_knowledge_store_restore_row(tiny,f)||!mrl_knowledge_store_get_fact(tiny,1,&now)||now.predicate!=2)return 16;mrl_knowledge_store_release(tiny);
 if(mrl_knowledge_store_peak(s)<mrl_knowledge_store_bytes(s))return 17;mrl_knowledge_store_release(s);if(!old->memory->used||old->memory->refs!=1)return 18;mrl_knowledge_store_release(old);return allocations?19:0;}''')
