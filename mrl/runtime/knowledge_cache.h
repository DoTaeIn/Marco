#ifndef MRL_KNOWLEDGE_CACHE_H
#define MRL_KNOWLEDGE_CACHE_H
#include "knowledge_engine.h"
#include "knowledge_persist.h"
#define MRL_KNOWLEDGE_CACHE_SCHEMA 2u
static uint64_t mrl_knowledge_cache_mix(uint64_t h,const void*p,size_t n){const unsigned char*b=p;while(n--){h^=*b++;h*=UINT64_C(1099511628211);}return h;}
static uint64_t mrl_knowledge_cache_u32(uint64_t h,uint32_t v){unsigned char b[4]={(unsigned char)v,(unsigned char)(v>>8),(unsigned char)(v>>16),(unsigned char)(v>>24)};return mrl_knowledge_cache_mix(h,b,4);}
static uint64_t mrl_knowledge_cache_store_identity(const MrlKnowledgeStore*s){uint64_t h=mrl_knowledge_cache_u32(0x6d726c6361636865ull,(uint32_t)s->symbols->next);for(uint32_t i=1;i<=s->symbols->next;i++){const char*x=mrl_knowledge_store_symbol(s,i);h=mrl_knowledge_cache_u32(h,(uint32_t)strlen(x));h=mrl_knowledge_cache_mix(h,x,strlen(x));}h=mrl_knowledge_cache_u32(h,(uint32_t)s->next_id);for(uint32_t i=1;i<=s->next_id;i++){MrlKnowledgeFact r;mrl_knowledge_store_get_any_fact(s,i,&r);h=mrl_knowledge_cache_u32(h,r.fact_id);h=mrl_knowledge_cache_u32(h,r.id);h=mrl_knowledge_cache_u32(h,r.subject);h=mrl_knowledge_cache_u32(h,r.predicate);h=mrl_knowledge_cache_u32(h,r.object);h=mrl_knowledge_cache_u32(h,r.evidence);h=mrl_knowledge_cache_u32(h,r.evidence_source);h=mrl_knowledge_cache_u32(h,r.evidence_text);h=mrl_knowledge_cache_u32(h,r.start);h=mrl_knowledge_cache_u32(h,r.end);h=mrl_knowledge_cache_u32(h,r.polarity);h=mrl_knowledge_cache_u32(h,r.modality);h=mrl_knowledge_cache_u32(h,r.live);}return h^s->version;}
static uint64_t mrl_knowledge_cache_rules_identity(const MrlKnowledgeEngine*e){uint64_t h=0x72756c6573ull;for(size_t i=0;i<e->rule_count;i++){const MrlKnowledgeRule*r=e->rules+i;h=mrl_knowledge_cache_u32(h,(uint32_t)r->id);h=mrl_knowledge_cache_u32(h,(uint32_t)r->premises);for(int k=0;k<3;k++)h=mrl_knowledge_cache_u32(h,(uint32_t)r->head[k]);for(int k=0;k<r->premises*3;k++)h=mrl_knowledge_cache_u32(h,(uint32_t)r->body[k]);}return h;}
static bool mrl_knowledge_cache_puti(MrlKnowledgePersistStream*s,int32_t v){return mrl_knowledge_persist_put32(s,(uint32_t)v);}
static bool mrl_knowledge_cache_geti(MrlKnowledgePersistStream*s,int32_t*v){uint32_t x;if(!mrl_knowledge_persist_get32(s,&x))return false;*v=(int32_t)x;return true;}
static void mrl_knowledge_cache_encode(unsigned char*p,uint32_t x){p[0]=(unsigned char)x;p[1]=(unsigned char)(x>>8);p[2]=(unsigned char)(x>>16);p[3]=(unsigned char)(x>>24);}
static uint32_t mrl_knowledge_cache_decode(const unsigned char*p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static bool mrl_knowledge_cache_fact_write(MrlKnowledgePersistStream*s,const MrlKnowledgeDerivedFact*f){
 uint32_t words[22]={(uint32_t)f->id,(uint32_t)(f->id>>32),(uint32_t)f->s,(uint32_t)f->p,(uint32_t)f->o,(uint32_t)f->asserted,(uint32_t)f->rule,(uint32_t)f->parent,(uint32_t)f->parent_count,(uint32_t)f->support_head,(uint32_t)f->support_tail,f->supports,f->denials,f->live};
 unsigned char bytes[88];for(int i=0;i<8;i++)words[14+i]=(uint32_t)f->parents[i];for(int i=0;i<22;i++)mrl_knowledge_cache_encode(bytes+i*4,words[i]);return mrl_knowledge_persist_write(s,bytes,sizeof(bytes));
}
static bool mrl_knowledge_cache_fact_read(MrlKnowledgePersistStream*s,MrlKnowledgeDerivedFact*f){
 unsigned char bytes[88];uint32_t x[22];if(!mrl_knowledge_persist_read(s,bytes,sizeof(bytes)))return false;for(int i=0;i<22;i++)x[i]=mrl_knowledge_cache_decode(bytes+i*4);
 f->id=(uint64_t)x[0]|(uint64_t)x[1]<<32;f->s=(int32_t)x[2];f->p=(int32_t)x[3];f->o=(int32_t)x[4];f->asserted=(int32_t)x[5];f->rule=(int32_t)x[6];f->parent=(int32_t)x[7];f->parent_count=(int32_t)x[8];f->support_head=(int32_t)x[9];f->support_tail=(int32_t)x[10];f->supports=x[11];f->denials=x[12];f->live=x[13];for(int i=0;i<8;i++)f->parents[i]=(int32_t)x[14+i];return f->live<=1&&f->asserted>=0&&f->asserted<=1&&f->parent_count>=0&&f->parent_count<=8;
}
static bool mrl_knowledge_cache_assert_write(MrlKnowledgePersistStream*s,const MkeAssertion*a){uint32_t x[7]={(uint32_t)a->id,(uint32_t)(a->id>>32),(uint32_t)a->row,(uint32_t)a->prev,(uint32_t)a->next,a->live,a->denial};unsigned char bytes[28];for(int i=0;i<7;i++)mrl_knowledge_cache_encode(bytes+i*4,x[i]);return mrl_knowledge_persist_write(s,bytes,sizeof(bytes));}
static bool mrl_knowledge_cache_assert_read(MrlKnowledgePersistStream*s,MkeAssertion*a){unsigned char bytes[28];uint32_t x[7];if(!mrl_knowledge_persist_read(s,bytes,sizeof(bytes)))return false;for(int i=0;i<7;i++)x[i]=mrl_knowledge_cache_decode(bytes+i*4);a->id=(uint64_t)x[0]|(uint64_t)x[1]<<32;a->row=(int32_t)x[2];a->prev=(int32_t)x[3];a->next=(int32_t)x[4];a->live=x[5];a->denial=x[6];return a->live<=1&&a->denial<=1;}

/* Cache rows retain stable IDs, so a repaired proof may point to a newer row.
   Validate the actual proof DAG, not the numeric order of its slots. */
static bool mrl_knowledge_cache_valid(MrlKnowledgeEngine*e,const MrlKnowledgeStore*s,size_t live){
 size_t actual=0;for(size_t i=0;i<e->count;i++){MrlKnowledgeDerivedFact*f=e->facts+i;f->touched=f->previous_live=0;
  if(mke_lookup(e,f->s,f->p,f->o)!=(int32_t)i||f->support_head< -1||f->support_tail< -1||
   (f->support_head>=0&&(size_t)f->support_head>=e->assertion_count)||(f->support_tail>=0&&(size_t)f->support_tail>=e->assertion_count))return false;
  for(int j=0;j<f->parent_count;j++)if(f->parents[j]<0||(size_t)f->parents[j]>=e->count)return false;
  actual+=f->live;
 }
 if(actual!=live||actual>e->fact_limit)return false;
 for(size_t i=0;i<e->assertion_count;i++){MkeAssertion*a=e->assertions+i;
  if(!a->id||a->id>s->next_id||a->row<0||(size_t)a->row>=e->count||mke_find_id(e,a->id)!=(int32_t)i||a->prev< -1||a->next< -1||
   (a->prev>=0&&(size_t)a->prev>=e->assertion_count)||(a->next>=0&&(size_t)a->next>=e->assertion_count))return false;
  if(a->live){MrlKnowledgeDerivedFact*f=e->facts+a->row;if(a->denial)f->previous_live++;else f->touched++;}
 }
 for(uint32_t id=1;id<=s->next_id;id++){MrlKnowledgeFact f;if(!mrl_knowledge_store_get_any_fact(s,id,&f))return false;int32_t at=mke_find_id(e,id);
  if(f.live&&f.modality==0){if(at<0||!e->assertions[at].live||e->assertions[at].denial!=(unsigned)!f.polarity)return false;
   MrlKnowledgeDerivedFact*x=e->facts+e->assertions[at].row;if(x->s!=(int32_t)f.subject||x->p!=(int32_t)f.predicate||x->o!=(int32_t)f.object)return false;
  }else if(at>=0&&e->assertions[at].live)return false;
 }
 for(size_t i=0;i<e->count;i++){MrlKnowledgeDerivedFact*f=e->facts+i;size_t n=0;int32_t at=f->support_head,prev=-1;
  while(at>=0){MkeAssertion*a=e->assertions+at;if(++n>e->assertion_count||!a->live||a->denial||a->row!=(int32_t)i||a->prev!=prev)return false;prev=at;at=a->next;}
  if(n!=f->supports||prev!=f->support_tail||f->touched!=f->supports||f->previous_live!=f->denials||f->asserted!=(f->supports!=0)||
   (f->denials&&f->live)||(f->supports&&!f->denials&&!f->live)||(f->supports&&f->id!=e->assertions[f->support_tail].id))return false;
  f->touched=f->previous_live=0;
  if(!f->live)continue;
  if(f->supports){if(f->rule!=-1||f->parent_count)return false;continue;}
  if(f->rule<0)return false;
  size_t r;for(r=0;r<e->rule_count&&e->rules[r].id!=f->rule;r++);if(r==e->rule_count||f->parent_count!=e->rules[r].premises)return false;
  int32_t bindings[8],values[3]={f->s,f->p,f->o};for(int k=0;k<8;k++)bindings[k]=-1;
  for(int j=0;j<f->parent_count;j++){const MrlKnowledgeDerivedFact*q=e->facts+f->parents[j];const int32_t*t=e->rules[r].body+j*3;
   if(!q->live||!mke_bind(t[0],q->s,bindings)||!mke_bind(t[1],q->p,bindings)||!mke_bind(t[2],q->o,bindings))return false;}
  for(int k=0;k<3;k++)if(mke_value(e->rules[r].head[k],bindings)!=values[k])return false;
 }
 typedef struct{int32_t row,next;}Frame;unsigned char*state=NULL;Frame*stack=NULL;size_t state_bytes=e->count,stack_bytes=e->count*sizeof(*stack);bool valid=false;
 if(!mke_resize(e,(void**)&state,0,state_bytes))return false;
 if(!mke_resize(e,(void**)&stack,0,stack_bytes)){mke_resize(e,(void**)&state,state_bytes,0);return false;}
 for(size_t i=0;i<e->count;i++){if(!e->facts[i].live||state[i])continue;size_t depth=1;stack[0]=(Frame){(int32_t)i,0};state[i]=1;
  while(depth){Frame*top=stack+depth-1;MrlKnowledgeDerivedFact*f=e->facts+top->row;
   if(top->next<f->parent_count){int32_t parent=f->parents[top->next++];if(state[parent]==1)goto done;if(state[parent]==2)continue;state[parent]=1;stack[depth++]=(Frame){parent,0};}
   else{state[top->row]=2;depth--;}
  }
 }
 valid=true;
 done:mke_resize(e,(void**)&state,state_bytes,0);mke_resize(e,(void**)&stack,stack_bytes,0);return valid;
}
/* The identity variants are private to a caller that just computed the exact
   identity. Public entry points always recompute it at their trust boundary. */
static const char*mrl_knowledge_engine_cache_save_identity(const MrlKnowledgeEngine*e,const MrlKnowledgeStore*store,const char*path,uint64_t fp,uint64_t identity){
 static const unsigned char magic[8]={'M','R','L','K','C','A','0','1'};FILE*f=NULL;char*temp;MrlKnowledgePersistStream w;const char*error="knowledge cache write";
 if(!e||!store||!path||!e->complete||e->editing||e->status||e->count>INT32_MAX||e->assertion_count>INT32_MAX)return "knowledge cache incomplete";
 temp=mrl_knowledge_persist_temp_name(path);if(!temp)return "knowledge cache path";
#if defined(_WIN32)
 f=mrl_knowledge_persist_open_file(temp,L"wb");
#else
 f=mrl_knowledge_persist_open_file(temp,"wb");
#endif
 if(!f){error="knowledge cache open";goto done;}w=(MrlKnowledgePersistStream){f,~0u};
 if(!mrl_knowledge_persist_write(&w,magic,8)||!mrl_knowledge_persist_put32(&w,MRL_KNOWLEDGE_CACHE_SCHEMA)||!mrl_knowledge_persist_put64(&w,fp)||
  !mrl_knowledge_persist_put64(&w,identity)||!mrl_knowledge_persist_put64(&w,mrl_knowledge_cache_rules_identity(e))||
  !mrl_knowledge_persist_put64(&w,e->version)||!mrl_knowledge_persist_put32(&w,(uint32_t)e->count)||!mrl_knowledge_persist_put32(&w,(uint32_t)e->assertion_count)||!mrl_knowledge_persist_put32(&w,(uint32_t)e->live_count))goto done;
 for(size_t i=0;i<e->count;i++)if(!mrl_knowledge_cache_fact_write(&w,e->facts+i))goto done;
 for(size_t i=0;i<e->assertion_count;i++)if(!mrl_knowledge_cache_assert_write(&w,e->assertions+i))goto done;
 if(!mrl_knowledge_write_u32(f,~w.crc)||!mrl_knowledge_persist_sync(f))goto done;
 if(fclose(f)){f=NULL;goto done;}f=NULL;
 if(!mrl_knowledge_persist_replace(temp,path)){error="knowledge cache replace";goto done;}error=NULL;
 done:if(f)fclose(f);if(error)mrl_knowledge_persist_remove(temp);free(temp);return error;
}
static const char*mrl_knowledge_engine_cache_save(const MrlKnowledgeEngine*e,const MrlKnowledgeStore*store,const char*path,uint64_t fp){if(!e||!store||!path)return "knowledge cache incomplete";return mrl_knowledge_engine_cache_save_identity(e,store,path,fp,mrl_knowledge_cache_store_identity(store));}
static const char*mrl_knowledge_engine_cache_load_identity(MrlKnowledgeEngine*e,const MrlKnowledgeStore*store,const char*path,uint64_t fp,uint64_t expected_identity){
 static const unsigned char magic[8]={'M','R','L','K','C','A','0','1'};FILE*f;MrlKnowledgePersistStream r;unsigned char got[8];
 uint32_t schema,n,a,live;uint64_t identity,rules,version,wanted;MrlKnowledgeEngine t={0};const char*error="knowledge cache stale";
 if(!e||!store||!path)return error;
#if defined(_WIN32)
 f=mrl_knowledge_persist_open_file(path,L"rb");
#else
 f=mrl_knowledge_persist_open_file(path,"rb");
#endif
 if(!f)return "knowledge cache missing";r=(MrlKnowledgePersistStream){f,~0u};
 if(!mrl_knowledge_persist_read(&r,got,8)||memcmp(got,magic,8)||!mrl_knowledge_persist_get32(&r,&schema)||schema!=MRL_KNOWLEDGE_CACHE_SCHEMA||
  !mrl_knowledge_persist_get64(&r,&wanted)||wanted!=fp||!mrl_knowledge_persist_get64(&r,&identity)||identity!=expected_identity||
  !mrl_knowledge_persist_get64(&r,&rules)||rules!=mrl_knowledge_cache_rules_identity(e)||!mrl_knowledge_persist_get64(&r,&version)||
  !mrl_knowledge_persist_get32(&r,&n)||!mrl_knowledge_persist_get32(&r,&a)||!mrl_knowledge_persist_get32(&r,&live)||n>INT32_MAX||a>INT32_MAX||live>n||live>e->fact_limit)goto done;
 if(!mrl_knowledge_engine_init_with_allocator(&t,e->rules,e->rule_count,e->work,e->allocator_context,e->resize_memory,e->free_memory)||
  !mrl_knowledge_engine_limits(&t,e->fact_limit,e->work,e->memory_budget))goto done;
 size_t nc=64,ac=64;while(nc<=n)nc*=2;while(ac<=a)ac*=2;
 if(!mke_resize(&t,(void**)&t.facts,0,nc*sizeof(*t.facts)))goto done;t.cap=nc;
 if(!mke_resize(&t,(void**)&t.assertions,0,ac*sizeof(*t.assertions)))goto done;t.assertion_cap=ac;t.count=n;t.assertion_count=a;
 for(uint32_t i=0;i<n;i++){MrlKnowledgeDerivedFact*x=t.facts+i;
  if(!mrl_knowledge_cache_fact_read(&r,x)||x->s<=0||x->p<=0||x->o<=0||!mrl_knowledge_store_symbol(store,x->s)||!mrl_knowledge_store_symbol(store,x->p)||!mrl_knowledge_store_symbol(store,x->o))goto done;}
 for(uint32_t i=0;i<a;i++)if(!mrl_knowledge_cache_assert_read(&r,t.assertions+i))goto done;
 if(!mrl_knowledge_persist_end(&r))goto done;
 size_t z=128;while(z<(size_t)n*2||z<(size_t)a*2)z*=2;
 if(!mke_reindex(&t,z)||!mke_id_index(&t,z)||!mrl_knowledge_cache_valid(&t,store,live))goto done;
 t.live_count=live;t.version=version;t.complete=1;fclose(f);mrl_knowledge_engine_free(e);*e=t;return NULL;
 done:fclose(f);mrl_knowledge_engine_free(&t);return error;
}
static const char*mrl_knowledge_engine_cache_load(MrlKnowledgeEngine*e,const MrlKnowledgeStore*store,const char*path,uint64_t fp){if(!e||!store||!path)return "knowledge cache stale";return mrl_knowledge_engine_cache_load_identity(e,store,path,fp,mrl_knowledge_cache_store_identity(store));}
#endif
