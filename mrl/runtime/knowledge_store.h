#ifndef MRL_KNOWLEDGE_STORE_H
#define MRL_KNOWLEDGE_STORE_H
#include <stdint.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
/* A budget covers physical allocations shared by one snapshot family, including
   indexes, symbols, changes and retained pages. No maximum-capacity preallocation.
   ponytail: immutable symbol IDs and change history are retained until the family
   is released; a checkpoint/reopen compacts history when long-running churn needs it. */
typedef uint32_t MrlKnowledgeSymbol,MrlKnowledgeFactId;
typedef struct { uint32_t refs; size_t budget,used,peak; } KsMemory;
typedef union { struct { KsMemory*memory;size_t bytes; } block; max_align_t alignment; } KsAllocation;
static void*ks_alloc(KsMemory*m,size_t bytes){
 if(bytes>SIZE_MAX-sizeof(KsAllocation))return NULL;size_t n=bytes+sizeof(KsAllocation);
 if(n>m->budget-m->used)return NULL;KsAllocation*a=calloc(1,n);if(!a)return NULL;
 a->block.memory=m;a->block.bytes=n;m->used+=n;if(m->used>m->peak)m->peak=m->used;return a+1;
}
static void ks_free(void*p){if(p){KsAllocation*a=(KsAllocation*)p-1;a->block.memory->used-=a->block.bytes;free(a);}}
/* Engine allocations can use the same physical family budget. */
static void*ks_resize_memory(void*context,void*pointer,size_t n){
 if(!n){ks_free(pointer);return NULL;}KsMemory*m=context;
 size_t old=pointer?((KsAllocation*)pointer-1)->block.bytes-sizeof(KsAllocation):0;
 if(n==old)return pointer;void*q=ks_alloc(m,n);if(!q)return NULL;if(pointer)memcpy(q,pointer,old<n?old:n);ks_free(pointer);return q;
}
static void ks_free_memory(void*context,void*pointer){(void)context;ks_free(pointer);}
typedef struct MrlKnowledgeSymbolRow{uint32_t id,hash;char*text;struct MrlKnowledgeSymbolRow*next;}MrlKnowledgeSymbolRow;
typedef struct KsSymbolBlock{struct KsSymbolBlock*next;size_t used,capacity;max_align_t alignment;unsigned char data[];}KsSymbolBlock;
typedef struct{uint32_t refs,next,restore_prefix;size_t buckets,id_cap;MrlKnowledgeSymbolRow**bucket,**by_id;KsSymbolBlock*restore_blocks;KsMemory*memory;}MrlKnowledgeSymbols;
typedef struct { MrlKnowledgeFactId fact_id;MrlKnowledgeSymbol id,subject,predicate,object,evidence;
 uint8_t polarity,modality,live;uint32_t evidence_source,evidence_text,start,end,next_pred,prev_pred;
} MrlKnowledgeFact;
typedef struct {uint64_t version;uint8_t kind;MrlKnowledgeFactId fact_id;MrlKnowledgeSymbol old_predicate,new_predicate;}MrlKnowledgeChange;
typedef struct {uint32_t refs;max_align_t alignment;unsigned char data[];}KsPage;
typedef struct {uint32_t refs;size_t pages,capacity,page_bytes;KsPage**page;}MrlKnowledgeRoot;
typedef struct {uint32_t fact,head,tail;}KsIndex;
typedef struct {uint32_t refs;uint64_t version;size_t budget,count,next_id,change_count;
 KsMemory*memory;MrlKnowledgeRoot*root,*index,*log;MrlKnowledgeSymbols*symbols;
} MrlKnowledgeStore;
typedef bool(*MrlKnowledgeFactCallback)(const MrlKnowledgeFact*,void*);
typedef bool(*MrlKnowledgeChangeCallback)(const MrlKnowledgeChange*,void*);
static uint32_t ks_hash(const char*s){uint32_t h=2166136261u;for(;*s;s++)h=(h^(unsigned char)*s)*16777619u;return h;}
static int ks_utf8(const char*s){const unsigned char*p=(const unsigned char*)s;if(!p)return 0;while(*p){uint32_t c=*p++;int n;uint32_t min;
 if(c<128)continue;if(c>=0xc2&&c<=0xdf){n=1;c&=31;min=128;}else if(c>=0xe0&&c<=0xef){n=2;c&=15;min=2048;}else if(c>=0xf0&&c<=0xf4){n=3;c&=7;min=65536;}else return 0;
 while(n--){uint32_t b=*p++;if((b&192)!=128)return 0;c=(c<<6)|(b&63);}if(c<min||c>0x10ffff||(c>=0xd800&&c<=0xdfff))return 0;}return 1;}
static MrlKnowledgeRoot*ks_root_new(KsMemory*m,size_t page_bytes,size_t capacity){
 if(capacity>(SIZE_MAX-sizeof(MrlKnowledgeRoot))/sizeof(KsPage*))return NULL;
 MrlKnowledgeRoot*r=ks_alloc(m,sizeof(*r)+capacity*sizeof(KsPage*));if(r){r->refs=1;r->capacity=capacity;r->page_bytes=page_bytes;r->page=(KsPage**)(r+1);}return r;
}
static void ks_root_release(MrlKnowledgeRoot*r){if(!r||--r->refs)return;for(size_t i=0;i<r->pages;i++)if(r->page[i]&&!--r->page[i]->refs)ks_free(r->page[i]);ks_free(r);}
static int ks_root_ready(KsMemory*m,MrlKnowledgeRoot**slot,size_t page){
 MrlKnowledgeRoot*r=*slot;size_t capacity=r->capacity?r->capacity:4;while(capacity<=page){if(capacity>SIZE_MAX/2)return 0;capacity*=2;}
 if(r->refs>1||capacity!=r->capacity){MrlKnowledgeRoot*q=ks_root_new(m,r->page_bytes,capacity);if(!q)return 0;q->pages=r->pages;
  for(size_t i=0;i<r->pages;i++){if(r->page[i]->refs==UINT32_MAX){ks_root_release(q);return 0;}q->page[i]=r->page[i];q->page[i]->refs++;}
  ks_root_release(r);*slot=r=q;}
 while(r->pages<=page){KsPage*p=ks_alloc(m,sizeof(*p)+r->page_bytes);if(!p)return 0;p->refs=1;r->page[r->pages++]=p;}
 if(r->page[page]->refs>1){KsPage*p=ks_alloc(m,sizeof(*p)+r->page_bytes);if(!p)return 0;p->refs=1;memcpy(p->data,r->page[page]->data,r->page_bytes);r->page[page]->refs--;r->page[page]=p;}return 1;
}
static void*ks_cell(const MrlKnowledgeRoot*r,size_t index,size_t size){size_t p=index/256;return p<r->pages?r->page[p]->data+(index%256)*size:NULL;}
static MrlKnowledgeFact*ks_fact(const MrlKnowledgeStore*s,uint32_t id){return id&&id<=s->next_id?ks_cell(s->root,id-1,sizeof(MrlKnowledgeFact)):NULL;}
static KsIndex*ks_index(const MrlKnowledgeStore*s,uint32_t id){return ks_cell(s->index,id,sizeof(KsIndex));}
static int ks_ready_fact(MrlKnowledgeStore*s,uint32_t id){return ks_root_ready(s->memory,&s->root,(id-1)/256);}
static int ks_ready_index(MrlKnowledgeStore*s,uint32_t id){return ks_root_ready(s->memory,&s->index,id/256);}
static int ks_ready_change(MrlKnowledgeStore*s){return s->version<UINT64_MAX&&ks_root_ready(s->memory,&s->log,s->change_count/256);}
static void ks_change(MrlKnowledgeStore*s,uint8_t kind,uint32_t id,uint32_t old,uint32_t now){
 MrlKnowledgeChange*c=ks_cell(s->log,s->change_count++,sizeof(*c));*c=(MrlKnowledgeChange){++s->version,kind,id,old,now};
}
static void ks_symbols_release(MrlKnowledgeSymbols*p){if(!p||--p->refs)return;for(size_t i=(size_t)p->restore_prefix+1;i<=p->next;i++)ks_free(p->by_id[i]);while(p->restore_blocks){KsSymbolBlock*b=p->restore_blocks;p->restore_blocks=b->next;ks_free(b);}ks_free(p->bucket);ks_free(p->by_id);ks_free(p);}
static MrlKnowledgeStore*mrl_knowledge_store_new(size_t budget){
 if(budget<sizeof(KsMemory))return NULL;KsMemory*m=calloc(1,sizeof(*m));if(!m)return NULL;m->refs=1;m->budget=budget;m->used=m->peak=sizeof(*m);
 MrlKnowledgeStore*s=ks_alloc(m,sizeof(*s));if(!s){free(m);return NULL;}s->refs=1;s->budget=budget;s->memory=m;
 s->root=ks_root_new(m,256*sizeof(MrlKnowledgeFact),0);s->index=ks_root_new(m,256*sizeof(KsIndex),0);s->log=ks_root_new(m,256*sizeof(MrlKnowledgeChange),0);s->symbols=ks_alloc(m,sizeof(*s->symbols));
 if(s->symbols){s->symbols->refs=1;s->symbols->memory=m;}
 if(!s->root||!s->index||!s->log||!s->symbols){ks_root_release(s->root);ks_root_release(s->index);ks_root_release(s->log);ks_symbols_release(s->symbols);ks_free(s);free(m);return NULL;}return s;
}
static uint32_t mrl_knowledge_store_find_symbol(const MrlKnowledgeStore*s,const char*t){
 if(!s||!t||!s->symbols->buckets)return 0;uint32_t h=ks_hash(t);for(MrlKnowledgeSymbolRow*r=s->symbols->bucket[h&(s->symbols->buckets-1)];r;r=r->next)if(r->hash==h&&!strcmp(r->text,t))return r->id;return 0;
}
/* Reserve immutable shared-symbol lookup capacity for IDs through count. */
static bool ks_symbols_reserve(MrlKnowledgeStore*s,size_t count){
 if(!s||!s->symbols||count>INT32_MAX)return false;MrlKnowledgeSymbols*p=s->symbols;
 if(p->next>INT32_MAX)return false;if(count<p->next)count=p->next;if(!count)return true;
 size_t bins=p->buckets?p->buckets:16,ids=p->id_cap?p->id_cap:16;
 while(count>bins-bins/4){if(bins>SIZE_MAX/2)return false;bins*=2;}
 while(ids<=count){if(ids>SIZE_MAX/2)return false;ids*=2;}
 if(bins>SIZE_MAX/sizeof(*p->bucket)||ids>SIZE_MAX/sizeof(*p->by_id)||p->id_cap>SIZE_MAX/sizeof(*p->by_id))return false;
 MrlKnowledgeSymbolRow**table=NULL,**by_id=NULL;
 if(bins!=p->buckets){table=ks_alloc(s->memory,bins*sizeof(*table));if(!table)return false;}
 if(ids!=p->id_cap){by_id=ks_alloc(s->memory,ids*sizeof(*by_id));if(!by_id){ks_free(table);return false;}if(p->by_id)memcpy(by_id,p->by_id,p->id_cap*sizeof(*by_id));}
 if(table){for(size_t i=1;i<=p->next;i++){MrlKnowledgeSymbolRow*x=p->by_id[i];size_t h=x->hash&(bins-1);x->next=table[h];table[h]=x;}ks_free(p->bucket);p->bucket=table;p->buckets=bins;}
 if(by_id){ks_free(p->by_id);p->by_id=by_id;p->id_cap=ids;}return true;
}
/* Checkpoint-only: text[n] is a validated NUL and IDs form the restored prefix. */
static bool ks_restore_symbol(MrlKnowledgeStore*s,const char*text,size_t n,uint32_t id){
 MrlKnowledgeSymbols*p;if(!s||!s->symbols||!text||n>SIZE_MAX-sizeof(MrlKnowledgeSymbolRow)-1)return false;p=s->symbols;
 if(p->next>=INT32_MAX||p->next!=p->restore_prefix||id!=p->next+1||!p->bucket||!p->by_id||id>=p->id_cap)return false;
 uint32_t hash=ks_hash(text);for(MrlKnowledgeSymbolRow*r=p->bucket[hash&(p->buckets-1)];r;r=r->next)if(r->hash==hash&&!strcmp(r->text,text))return false;
 size_t need=sizeof(MrlKnowledgeSymbolRow)+n+1,align=_Alignof(MrlKnowledgeSymbolRow),at=0;KsSymbolBlock*b=p->restore_blocks;
 if(b&&b->used<=b->capacity&&b->used<=SIZE_MAX-(align-1)){at=(b->used+align-1)&~(align-1);if(at>b->capacity||need>b->capacity-at)b=NULL;}
 else b=NULL;
 if(!b){size_t capacity=64u*1024u,available=s->memory->budget-s->memory->used,header=sizeof(*b)+sizeof(KsAllocation);if(available<header)return false;if(capacity<need)capacity=need;if(capacity>SIZE_MAX-header)return false;if(capacity>available-header)capacity=need;if(capacity>SIZE_MAX-header||capacity>available-header)return false;b=ks_alloc(s->memory,sizeof(*b)+capacity);if(!b)return false;b->capacity=capacity;at=0;}
 MrlKnowledgeSymbolRow*r=(MrlKnowledgeSymbolRow*)(b->data+at);char*copy=(char*)(r+1);memcpy(copy,text,n+1);*r=(MrlKnowledgeSymbolRow){id,hash,copy,p->bucket[hash&(p->buckets-1)]};b->used=at+need;
 if(b!=p->restore_blocks){b->next=p->restore_blocks;p->restore_blocks=b;}p->bucket[hash&(p->buckets-1)]=r;p->by_id[id]=r;p->next=id;p->restore_prefix=id;return true;
}
static bool mrl_knowledge_store_intern(MrlKnowledgeStore*s,const char*t,MrlKnowledgeSymbol*out){
 if(!s||!t||!out||!ks_utf8(t))return false;uint32_t found=mrl_knowledge_store_find_symbol(s,t);if(found){*out=found;return true;}
 MrlKnowledgeSymbols*p=s->symbols;if(p->next>=INT32_MAX)return false;size_t n=strlen(t)+1;
 if(n>SIZE_MAX-sizeof(MrlKnowledgeSymbolRow))return false;MrlKnowledgeSymbolRow*r=ks_alloc(s->memory,sizeof(*r)+n);if(!r)return false;
 if(!ks_symbols_reserve(s,(size_t)p->next+1)){ks_free(r);return false;}
 r->id=++p->next;r->hash=ks_hash(t);r->text=(char*)(r+1);memcpy(r->text,t,n);size_t at=r->hash&(p->buckets-1);r->next=p->bucket[at];p->bucket[at]=r;p->by_id[r->id]=r;*out=r->id;return true;
}
static const char*mrl_knowledge_store_symbol(const MrlKnowledgeStore*s,MrlKnowledgeSymbol id){return s&&id&&id<=s->symbols->next?s->symbols->by_id[id]->text:NULL;}
static MrlKnowledgeStore*mrl_knowledge_store_retain(MrlKnowledgeStore*s){if(!s||s->refs==UINT32_MAX)return NULL;s->refs++;return s;}
static void mrl_knowledge_store_release(MrlKnowledgeStore*s){if(!s||--s->refs)return;KsMemory*m=s->memory;ks_root_release(s->root);ks_root_release(s->index);ks_root_release(s->log);ks_symbols_release(s->symbols);ks_free(s);if(!--m->refs)free(m);}
static MrlKnowledgeStore*mrl_knowledge_store_snapshot(MrlKnowledgeStore*s){
 if(!s||s->memory->refs==UINT32_MAX||s->root->refs==UINT32_MAX||s->index->refs==UINT32_MAX||s->log->refs==UINT32_MAX||s->symbols->refs==UINT32_MAX)return NULL;
 MrlKnowledgeStore*q=ks_alloc(s->memory,sizeof(*q));if(!q)return NULL;*q=*s;q->refs=1;q->memory->refs++;q->root->refs++;q->index->refs++;q->log->refs++;q->symbols->refs++;return q;
}
static uint64_t mrl_knowledge_store_version(const MrlKnowledgeStore*s){return s?s->version:0;}
static size_t mrl_knowledge_store_fact_count(const MrlKnowledgeStore*s){return s?s->count:0;}
static size_t mrl_knowledge_store_bytes(const MrlKnowledgeStore*s){return s?s->memory->used:0;}
static size_t mrl_knowledge_store_peak(const MrlKnowledgeStore*s){return s?s->memory->peak:0;}
static bool mrl_knowledge_store_get_any_fact(const MrlKnowledgeStore*s,MrlKnowledgeFactId id,MrlKnowledgeFact*out){MrlKnowledgeFact*f=s?ks_fact(s,id):NULL;if(!f)return false;if(out)*out=*f;return true;}
static bool mrl_knowledge_store_get_fact(const MrlKnowledgeStore*s,MrlKnowledgeFactId id,MrlKnowledgeFact*out){MrlKnowledgeFact*f=s?ks_fact(s,id):NULL;if(!f||!f->live)return false;if(out)*out=*f;return true;}
static MrlKnowledgeFactId mrl_knowledge_store_find_id(const MrlKnowledgeStore*s,MrlKnowledgeSymbol id){KsIndex*i=s?ks_index(s,id):NULL;return id&&i?i->fact:0;}
static bool ks_append_row(MrlKnowledgeStore*s,MrlKnowledgeFact f,bool record){
 if(!s||s->next_id>=UINT32_MAX||f.polarity>1||f.modality>2||f.live>1)return false;
 if(f.live&&f.id&&mrl_knowledge_store_find_id(s,f.id))return false;
 uint32_t id=(uint32_t)s->next_id+1;KsIndex*old=ks_index(s,f.predicate);uint32_t tail=old?old->tail:0;
 if(!ks_ready_fact(s,id)||(record&&!ks_ready_change(s)))return false;
 if(f.live&&(!ks_ready_index(s,f.id)||!ks_ready_index(s,f.predicate)||(tail&&!ks_ready_fact(s,tail))))return false;
 f.fact_id=id;f.prev_pred=f.live?tail:0;f.next_pred=0;*(MrlKnowledgeFact*)ks_cell(s->root,id-1,sizeof(f))=f;s->next_id++;
 if(f.live){KsIndex*pi=ks_index(s,f.predicate);if(tail)ks_fact(s,tail)->next_pred=id;else pi->head=id;pi->tail=id;if(f.id)ks_index(s,f.id)->fact=id;s->count++;}
 if(record)ks_change(s,1,id,0,f.predicate);return true;
}
static bool mrl_knowledge_store_append(MrlKnowledgeStore*s,MrlKnowledgeFact f,uint8_t kind){(void)kind;f.live=1;return ks_append_row(s,f,true);}
static bool mrl_knowledge_store_restore_row(MrlKnowledgeStore*s,MrlKnowledgeFact f){return s&&f.fact_id==s->next_id+1&&ks_append_row(s,f,false);}
static int ks_edit_ready(MrlKnowledgeStore*s,const MrlKnowledgeFact*old,const MrlKnowledgeFact*next){
 if(!ks_ready_change(s)||!ks_ready_fact(s,old->fact_id)||!ks_ready_index(s,old->id)||!ks_ready_index(s,old->predicate))return 0;
 if(old->prev_pred&&!ks_ready_fact(s,old->prev_pred))return 0;if(old->next_pred&&!ks_ready_fact(s,old->next_pred))return 0;
 if(next){if(!ks_ready_index(s,next->id)||!ks_ready_index(s,next->predicate))return 0;KsIndex*pi=ks_index(s,next->predicate);if(pi->tail&&!ks_ready_fact(s,pi->tail))return 0;}return 1;
}
static void ks_unlink(MrlKnowledgeStore*s,const MrlKnowledgeFact*f){
 KsIndex*pi=ks_index(s,f->predicate);if(f->prev_pred)ks_fact(s,f->prev_pred)->next_pred=f->next_pred;else pi->head=f->next_pred;
 if(f->next_pred)ks_fact(s,f->next_pred)->prev_pred=f->prev_pred;else pi->tail=f->prev_pred;if(f->id)ks_index(s,f->id)->fact=0;
}
static bool mrl_knowledge_store_remove(MrlKnowledgeStore*s,MrlKnowledgeFactId id){
 MrlKnowledgeFact f;if(!mrl_knowledge_store_get_fact(s,id,&f)||!ks_edit_ready(s,&f,NULL))return false;ks_unlink(s,&f);
 MrlKnowledgeFact*row=ks_fact(s,id);row->live=0;row->next_pred=row->prev_pred=0;s->count--;ks_change(s,2,id,f.predicate,0);return true;
}
static bool mrl_knowledge_store_correct(MrlKnowledgeStore*s,MrlKnowledgeFactId id,MrlKnowledgeFact f){
 MrlKnowledgeFact old;if(!mrl_knowledge_store_get_fact(s,id,&old)||f.polarity>1||f.modality>2)return false;
 uint32_t occupied=mrl_knowledge_store_find_id(s,f.id);if(occupied&&occupied!=id)return false;
 if(!ks_edit_ready(s,&old,&f))return false;ks_unlink(s,&old);KsIndex*pi=ks_index(s,f.predicate);f.fact_id=id;f.live=1;f.prev_pred=pi->tail;f.next_pred=0;
 if(pi->tail)ks_fact(s,pi->tail)->next_pred=id;else pi->head=id;pi->tail=id;if(f.id)ks_index(s,f.id)->fact=id;*ks_fact(s,id)=f;ks_change(s,3,id,old.predicate,f.predicate);return true;
}
static bool mrl_knowledge_store_find_predicate(const MrlKnowledgeStore*s,MrlKnowledgeSymbol predicate,MrlKnowledgeFactCallback cb,void*ctx){
 KsIndex*pi=s?ks_index(s,predicate):NULL;if(!pi)return true;for(uint32_t i=pi->head;i;){MrlKnowledgeFact*f=ks_fact(s,i);uint32_t next=f->next_pred;if(!cb(f,ctx))return false;i=next;}return true;
}
static bool mrl_knowledge_store_changes_since(const MrlKnowledgeStore*s,uint64_t version,MrlKnowledgeChangeCallback cb,void*ctx){
 if(!s||!cb)return false;size_t lo=0,hi=s->change_count;while(lo<hi){size_t mid=lo+(hi-lo)/2;MrlKnowledgeChange*c=ks_cell(s->log,mid,sizeof(*c));if(c->version<=version)lo=mid+1;else hi=mid;}
 for(size_t i=lo;i<s->change_count;i++){MrlKnowledgeChange*c=ks_cell(s->log,i,sizeof(*c));if(!cb(c,ctx))return false;}return true;
}
#endif
