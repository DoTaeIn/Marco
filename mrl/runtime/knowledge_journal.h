#ifndef MRL_KNOWLEDGE_DELTA_JOURNAL_H
#define MRL_KNOWLEDGE_DELTA_JOURNAL_H
#include "knowledge_persist.h"

#define MRL_KNOWLEDGE_DELTA_SCHEMA 1u
#define MRL_KNOWLEDGE_DELTA_MAX (32u*1024u*1024u)

typedef struct { unsigned char*p; size_t n,cap; } MrlKnowledgeDeltaBuffer;
typedef struct { const unsigned char*p; size_t n,at; } MrlKnowledgeDeltaReader;
typedef struct { uint32_t*ids,*set; size_t count,cap,mask; } MrlKnowledgeDeltaIds;

static bool mrl_knowledge_delta_grow(MrlKnowledgeDeltaBuffer*b,size_t n){
 size_t cap=b->cap?b->cap:256;if(n>MRL_KNOWLEDGE_DELTA_MAX-b->n)return false;
 while(cap<b->n+n){if(cap>=MRL_KNOWLEDGE_DELTA_MAX){cap=MRL_KNOWLEDGE_DELTA_MAX;break;}cap*=2;if(cap>MRL_KNOWLEDGE_DELTA_MAX)cap=MRL_KNOWLEDGE_DELTA_MAX;}
 if(cap!=b->cap){void*p=realloc(b->p,cap);if(!p)return false;b->p=p;b->cap=cap;}return true;
}
static bool mrl_knowledge_delta_bytes(MrlKnowledgeDeltaBuffer*b,const void*p,size_t n){if(!mrl_knowledge_delta_grow(b,n))return false;memcpy(b->p+b->n,p,n);b->n+=n;return true;}
static bool mrl_knowledge_delta_u32(MrlKnowledgeDeltaBuffer*b,uint32_t v){unsigned char x[4]={(unsigned char)v,(unsigned char)(v>>8),(unsigned char)(v>>16),(unsigned char)(v>>24)};return mrl_knowledge_delta_bytes(b,x,4);}
static bool mrl_knowledge_delta_u64(MrlKnowledgeDeltaBuffer*b,uint64_t v){return mrl_knowledge_delta_u32(b,(uint32_t)v)&&mrl_knowledge_delta_u32(b,(uint32_t)(v>>32));}
static bool mrl_knowledge_delta_row(MrlKnowledgeDeltaBuffer*b,const MrlKnowledgeFact*r){return mrl_knowledge_delta_u32(b,r->fact_id)&&mrl_knowledge_delta_u32(b,r->id)&&mrl_knowledge_delta_u32(b,r->subject)&&mrl_knowledge_delta_u32(b,r->predicate)&&mrl_knowledge_delta_u32(b,r->object)&&mrl_knowledge_delta_u32(b,r->evidence)&&mrl_knowledge_delta_u32(b,r->evidence_source)&&mrl_knowledge_delta_u32(b,r->evidence_text)&&mrl_knowledge_delta_u32(b,r->start)&&mrl_knowledge_delta_u32(b,r->end)&&mrl_knowledge_delta_bytes(b,&r->polarity,1)&&mrl_knowledge_delta_bytes(b,&r->modality,1)&&mrl_knowledge_delta_bytes(b,&r->live,1);}
static bool mrl_knowledge_delta_get(MrlKnowledgeDeltaReader*r,void*p,size_t n){if(n>r->n-r->at)return false;memcpy(p,r->p+r->at,n);r->at+=n;return true;}
static bool mrl_knowledge_delta_get32(MrlKnowledgeDeltaReader*r,uint32_t*v){unsigned char x[4];if(!mrl_knowledge_delta_get(r,x,4))return false;*v=(uint32_t)x[0]|(uint32_t)x[1]<<8|(uint32_t)x[2]<<16|(uint32_t)x[3]<<24;return true;}
static bool mrl_knowledge_delta_get64(MrlKnowledgeDeltaReader*r,uint64_t*v){uint32_t a,b;return mrl_knowledge_delta_get32(r,&a)&&mrl_knowledge_delta_get32(r,&b)&&(*v=(uint64_t)a|((uint64_t)b<<32),true);}
static bool mrl_knowledge_delta_read_row(MrlKnowledgeDeltaReader*r,MrlKnowledgeFact*x){return mrl_knowledge_delta_get32(r,&x->fact_id)&&mrl_knowledge_delta_get32(r,&x->id)&&mrl_knowledge_delta_get32(r,&x->subject)&&mrl_knowledge_delta_get32(r,&x->predicate)&&mrl_knowledge_delta_get32(r,&x->object)&&mrl_knowledge_delta_get32(r,&x->evidence)&&mrl_knowledge_delta_get32(r,&x->evidence_source)&&mrl_knowledge_delta_get32(r,&x->evidence_text)&&mrl_knowledge_delta_get32(r,&x->start)&&mrl_knowledge_delta_get32(r,&x->end)&&mrl_knowledge_delta_get(r,&x->polarity,1)&&mrl_knowledge_delta_get(r,&x->modality,1)&&mrl_knowledge_delta_get(r,&x->live,1);}
static int mrl_knowledge_delta_compare_id(const void*a,const void*b){uint32_t x=*(const uint32_t*)a,y=*(const uint32_t*)b;return x>y?1:x<y?-1:0;}
static bool mrl_knowledge_delta_ids_add(MrlKnowledgeDeltaIds*d,uint32_t id){
 size_t at=(size_t)(id*UINT32_C(2654435761))&d->mask;while(d->set[at]&&d->set[at]!=id)at=(at+1)&d->mask;if(d->set[at])return true;d->set[at]=id;
 if(d->count==d->cap){size_t n=d->cap?d->cap*2:16;void*p=realloc(d->ids,n*sizeof(*d->ids));if(!p)return false;d->ids=p;d->cap=n;}d->ids[d->count++]=id;return true;
}
static bool mrl_knowledge_delta_record(MrlKnowledgeStore*s,uint64_t version,uint8_t kind,uint32_t id,uint32_t old,uint32_t now){
 if(!ks_ready_change(s))return false;*(MrlKnowledgeChange*)ks_cell(s->log,s->change_count++,sizeof(MrlKnowledgeChange))=(MrlKnowledgeChange){version,kind,id,old,now};return true;
}
static bool mrl_knowledge_delta_trim_tail(const char*path){
 FILE*f;long end,before;bool ok=true;
#if defined(_WIN32)
 f=mrl_knowledge_persist_open_file(path,L"r+b");
#else
 f=mrl_knowledge_persist_open_file(path,"r+b");
#endif
 if(!f)return true;if(fseek(f,0,SEEK_END)||(end=ftell(f))<0||fseek(f,0,SEEK_SET)){fclose(f);return false;}
 for(;;){void*p=NULL;uint32_t n=0;int r;before=ftell(f);r=mrl_knowledge_journal_read(f,&p,&n);free(p);if(r>0)continue;if(r<0){ok=false;break;}if(before!=end){
#if defined(_WIN32)
   ok=_chsize_s(_fileno(f),(__int64)before)==0&&mrl_knowledge_persist_sync(f);
#else
   ok=ftruncate(fileno(f),before)==0&&mrl_knowledge_persist_sync(f);
#endif
  }break;}
 return fclose(f)==0&&ok;
}
static const char*mrl_knowledge_delta_repair(const char*path){return path&&mrl_knowledge_delta_trim_tail(path)?NULL:"knowledge delta journal";}
static const char*mrl_knowledge_delta_commit(MrlKnowledgeStore*store,const char*path,uint64_t fingerprint,uint64_t base_version,uint32_t base_next_id,uint32_t base_symbol_count){
 static const unsigned char magic[8]={'M','R','L','K','D','L','0','1'};MrlKnowledgeStore*s;MrlKnowledgeDeltaBuffer out={0};MrlKnowledgeDeltaIds ids={0};size_t first=0,events,table=16;const char*err="knowledge delta write";
 if(!store||!path)return"knowledge delta arguments";s=mrl_knowledge_store_snapshot(store);if(!s)return"knowledge delta snapshot";
 if(base_version>s->version||base_next_id>s->next_id||base_symbol_count>s->symbols->next||s->next_id>MRL_KNOWLEDGE_PERSIST_MAX_ROWS||s->symbols->next>INT32_MAX){err="knowledge delta bounds";goto done;}
 {size_t lo=0,hi=s->change_count;while(lo<hi){size_t mid=lo+(hi-lo)/2;MrlKnowledgeChange*c=ks_cell(s->log,mid,sizeof(*c));if(c->version<=base_version)lo=mid+1;else hi=mid;}first=lo;}events=s->change_count-first;
 if(events>MRL_KNOWLEDGE_DELTA_MAX/43u){err="knowledge delta bounds";goto done;}while(table<events*2)table*=2;if(events){ids.set=calloc(table,sizeof(*ids.set));if(!ids.set){err="knowledge delta memory";goto done;}ids.mask=table-1;}
 for(size_t i=first;i<s->change_count;i++){MrlKnowledgeChange*c=ks_cell(s->log,i,sizeof(*c));if(!c->fact_id||c->fact_id>s->next_id||!mrl_knowledge_delta_ids_add(&ids,c->fact_id)){err="knowledge delta changes";goto done;}}
 qsort(ids.ids,ids.count,sizeof(*ids.ids),mrl_knowledge_delta_compare_id);
 if(!mrl_knowledge_delta_bytes(&out,magic,8)||!mrl_knowledge_delta_u32(&out,MRL_KNOWLEDGE_DELTA_SCHEMA)||!mrl_knowledge_delta_u64(&out,fingerprint)||!mrl_knowledge_delta_u64(&out,base_version)||!mrl_knowledge_delta_u64(&out,s->version)||!mrl_knowledge_delta_u32(&out,base_next_id)||!mrl_knowledge_delta_u32(&out,(uint32_t)s->next_id)||!mrl_knowledge_delta_u32(&out,base_symbol_count)||!mrl_knowledge_delta_u32(&out,s->symbols->next)||!mrl_knowledge_delta_u32(&out,s->symbols->next-base_symbol_count)||!mrl_knowledge_delta_u32(&out,(uint32_t)ids.count)){err="knowledge delta bounds";goto done;}
 for(uint32_t i=base_symbol_count+1;i<=s->symbols->next;i++){const char*x=mrl_knowledge_store_symbol(s,i);size_t n=x?strlen(x):0;if(n>MRL_KNOWLEDGE_PERSIST_MAX_TEXT||!mrl_knowledge_persist_utf8(x,n)||!mrl_knowledge_delta_u32(&out,(uint32_t)n)||!mrl_knowledge_delta_bytes(&out,x,n)){err="knowledge delta symbol";goto done;}}
 for(size_t i=0;i<ids.count;i++){MrlKnowledgeFact row;if(!mrl_knowledge_store_get_any_fact(s,ids.ids[i],&row)||!mrl_knowledge_persist_row_ok(s,&row,ids.ids[i],s->symbols->next)||!mrl_knowledge_delta_row(&out,&row)){err="knowledge delta row";goto done;}}
 /* ponytail: one bounded transaction keeps replay simple; split at 32 MiB if journal batches grow larger. */
 if(out.n>MRL_KNOWLEDGE_DELTA_MAX){err="knowledge delta bounds";goto done;}err=mrl_knowledge_journal_append(path,out.p,(uint32_t)out.n);
done:free(out.p);free(ids.ids);free(ids.set);mrl_knowledge_store_release(s);return err;
}

typedef struct { MrlKnowledgeStore*s; uint64_t fingerprint; const char*error; } MrlKnowledgeDeltaApply;
static bool mrl_knowledge_delta_apply(const void*p,uint32_t n,void*ctx){
 static const unsigned char magic[8]={'M','R','L','K','D','L','0','1'};MrlKnowledgeDeltaApply*a=ctx;MrlKnowledgeDeltaReader in={(const unsigned char*)p,n,0};unsigned char got[8];uint32_t schema,base_rows,new_rows,base_symbols,new_symbols,symbol_count,row_count,last=0;uint64_t fp,base_version,new_version;size_t first_change;
 if(!mrl_knowledge_delta_get(&in,got,8)||memcmp(got,magic,8)||!mrl_knowledge_delta_get32(&in,&schema)||schema!=MRL_KNOWLEDGE_DELTA_SCHEMA||!mrl_knowledge_delta_get64(&in,&fp)||fp!=a->fingerprint||!mrl_knowledge_delta_get64(&in,&base_version)||!mrl_knowledge_delta_get64(&in,&new_version)||!mrl_knowledge_delta_get32(&in,&base_rows)||!mrl_knowledge_delta_get32(&in,&new_rows)||!mrl_knowledge_delta_get32(&in,&base_symbols)||!mrl_knowledge_delta_get32(&in,&new_symbols)||!mrl_knowledge_delta_get32(&in,&symbol_count)||!mrl_knowledge_delta_get32(&in,&row_count)){a->error="knowledge delta corrupt";return false;}
 if(base_version!=a->s->version||base_rows!=a->s->next_id||base_symbols!=a->s->symbols->next||new_version<base_version||(row_count&&new_version==base_version)||new_rows<base_rows||new_symbols<base_symbols||new_rows>MRL_KNOWLEDGE_PERSIST_MAX_ROWS||new_symbols>INT32_MAX||symbol_count!=new_symbols-base_symbols||row_count>MRL_KNOWLEDGE_DELTA_MAX/43u){a->error="knowledge delta continuity";return false;}
 for(uint32_t i=base_symbols+1;i<=new_symbols;i++){uint32_t z,id;char*x;if(!mrl_knowledge_delta_get32(&in,&z)||z>MRL_KNOWLEDGE_PERSIST_MAX_TEXT||z>in.n-in.at){a->error="knowledge delta symbol";return false;}x=malloc((size_t)z+1);if(!x){a->error="knowledge delta memory";return false;}if(!mrl_knowledge_delta_get(&in,x,z)||!mrl_knowledge_persist_utf8(x,z)){free(x);a->error="knowledge delta symbol";return false;}x[z]=0;if(!mrl_knowledge_store_intern(a->s,x,&id)||id!=i){free(x);a->error="knowledge delta symbol";return false;}free(x);}
 first_change=a->s->change_count;
 for(uint32_t i=0;i<row_count;i++){MrlKnowledgeFact row,old;memset(&row,0,sizeof(row));if(!mrl_knowledge_delta_read_row(&in,&row)||!mrl_knowledge_persist_row_ok(a->s,&row,row.fact_id,new_symbols)){a->error="knowledge delta row";return false;}if(!row.fact_id||row.fact_id<=last||row.fact_id>new_rows){a->error="knowledge delta row";return false;}last=row.fact_id;
  if(row.fact_id==a->s->next_id+1){if(!mrl_knowledge_store_restore_row(a->s,row)||!mrl_knowledge_delta_record(a->s,new_version,row.live?1:2,row.fact_id,0,row.live?row.predicate:0)){a->error="knowledge delta restore";return false;}}
  else if(row.fact_id<=a->s->next_id&&mrl_knowledge_store_get_any_fact(a->s,row.fact_id,&old)){if(!old.live||(row.live? !mrl_knowledge_store_correct(a->s,row.fact_id,row):!mrl_knowledge_store_remove(a->s,row.fact_id))){a->error="knowledge delta apply";return false;}if(!row.live)*ks_fact(a->s,row.fact_id)=row;}
  else {a->error="knowledge delta row";return false;}
 }
 if(in.at!=in.n||a->s->next_id!=new_rows||a->s->symbols->next!=new_symbols){a->error="knowledge delta continuity";return false;}
 for(size_t i=first_change;i<a->s->change_count;i++)((MrlKnowledgeChange*)ks_cell(a->s->log,i,sizeof(MrlKnowledgeChange)))->version=new_version;a->s->version=new_version;return true;
}
static const char*mrl_knowledge_delta_replay(MrlKnowledgeStore**store,const char*path,uint64_t fingerprint){MrlKnowledgeDeltaApply apply;if(!store||!*store||!path)return"knowledge delta arguments";apply=(MrlKnowledgeDeltaApply){*store,fingerprint,NULL};const char*err=mrl_knowledge_journal_replay(path,mrl_knowledge_delta_apply,&apply);return apply.error?apply.error:err;}
#endif
