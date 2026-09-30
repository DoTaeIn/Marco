#ifndef MRL_HORN_RUNTIME_V7_H
#define MRL_HORN_RUNTIME_V7_H
#include <errno.h>
/* Included after knowledge_store, knowledge_engine, JSONL and persistence. */
typedef struct MrlHornPlan MrlHornPlan;
typedef struct MrlHornSnapshot MrlHornSnapshot;
typedef struct {int present;const char*source,*text;int32_t start,end;}MrlHornEvidence;
typedef struct {const char*id,*s,*p,*o,*modality;int polarity;MrlHornEvidence evidence;}MrlHornPlanFact;
typedef struct {const char*id,*version_json;int32_t body_count;const char*body[8][3];const char*head[3];}MrlHornPlanRule;
typedef struct {const MrlHornPlanFact*facts;int32_t fact_count;const MrlHornPlanRule*rules;int32_t rule_count,capacity;size_t memory_budget;}MrlHornPlanTemplate;
typedef struct {bool ok;int32_t value;const char*error;}MrlHornLoadResult;
struct MrlHornPlan {uint32_t refs;MrlKnowledgeStore*store;const MrlHornPlanTemplate*template;MrlKnowledgeEngine engine;uint64_t engine_version;int engine_ready,cache_hit,journal_needs_repair;char*durable_path,*durable_journal;uint64_t durable_version;uint32_t durable_rows,durable_symbols;};
typedef struct {int32_t rule,parent_count,parents[8][3];char*id,*parent_ids[8];}MrlHornAlternateProof;
typedef struct {int32_t s,p,o,rule,parent_count,parents[8][3];uint32_t support,support_count,*support_ids,parent_support_ids[8];char*node_id,*proof_node_id,*parent_ids[8];MrlHornAlternateProof*alternates;uint32_t alternate_count;unsigned alternates_loaded,removed,polarity;}MrlHornSnapshotRow;
typedef struct{int32_t s,p,o;uint32_t supports,denials;}MrlHornConflict;
struct MrlHornSnapshot {uint32_t refs;MrlKnowledgeStore*store;const MrlHornPlanTemplate*template;MrlKnowledgeEngine*proof_engine;MrlHornSnapshotRow*rows;size_t count,allocated,added,removed;MrlHornConflict*conflicts;size_t conflict_count,conflict_allocated;uint64_t version,work,proof_work;int32_t proof_limit,search_limit;bool complete;const char*reason;};
typedef struct MrlHornSnapshot MrlHornResult;

static void mrl_horn_v7_fail(const char*s){mrl_runtime_fail(s);}
static const char*mrl_horn_v7_status(int status){switch(status){case MKE_OK:return "complete";case MKE_WORK:return "work_limit";case MKE_LIMIT:return "fact_limit";case MKE_MEMORY:return "memory_budget";default:return "invalid_knowledge";}}
static int mrl_horn_v7_modality(const char*s){if(!strcmp(s,"asserted"))return 0;if(!strcmp(s,"planned"))return 1;if(!strcmp(s,"conditional"))return 2;return -1;}
static int32_t mrl_horn_v7_intern(MrlKnowledgeStore*s,const char*t){uint32_t id;if(!mrl_knowledge_store_intern(s,t,&id))return -1;return (int32_t)id;}
static int mrl_horn_v7_reserved_id(const char*id){return id&&!strncmp(id,"__mrl_history__:",16);}
static int mrl_horn_v7_historical_id(const MrlKnowledgeStore*s,const char*id){uint32_t name=mrl_knowledge_store_find_symbol(s,id);if(!name)return 0;for(uint32_t row=1;row<=s->next_id;row++){MrlKnowledgeFact fact;if(mrl_knowledge_store_get_any_fact(s,row,&fact)&&fact.id==name)return 1;}return 0;}
static int mrl_horn_v7_fact_mode(MrlKnowledgeStore*s,MrlHornPlanFact f,MrlKnowledgeFact*out,int internal){
 if(!internal&&mrl_horn_v7_reserved_id(f.id))return 0;
 if(!f.id||!*f.id||!f.s||!*f.s||!f.p||!*f.p||!f.o||!*f.o||!f.modality)return 0;int modality=mrl_horn_v7_modality(f.modality);if(modality<0)return 0;
 const char*t[4]={f.id,f.s,f.p,f.o};uint32_t ids[4];for(int i=0;i<4;i++)if(!mrl_knowledge_store_intern(s,t[i],&ids[i]))return 0;
 memset(out,0,sizeof(*out));out->id=ids[0];out->subject=ids[1];out->predicate=ids[2];out->object=ids[3];out->polarity=!!f.polarity;out->modality=(uint8_t)modality;out->live=1;
 if(f.evidence.present){if(!f.evidence.source||!f.evidence.text||f.evidence.start<0||f.evidence.end<f.evidence.start)return 0;
  const unsigned char*text=(const unsigned char*)f.evidence.source;size_t chars=0;if(!jutf(text,&chars)||(size_t)f.evidence.end>chars)return 0;
  size_t at=0,start=0,end=0;for(size_t c=0;c<=(size_t)f.evidence.end;c++){if(c==(size_t)f.evidence.start)start=at;if(c==(size_t)f.evidence.end){end=at;break;}at+=text[at]<128?1:(text[at]&224)==192?2:(text[at]&240)==224?3:4;}
  if(strlen(f.evidence.text)!=end-start||memcmp(text+start,f.evidence.text,end-start))return 0;
  if(!mrl_knowledge_store_intern(s,f.evidence.source,&out->evidence_source)||!mrl_knowledge_store_intern(s,f.evidence.text,&out->evidence_text))return 0;
  out->evidence=1;out->start=f.evidence.start;out->end=f.evidence.end;
 }return 1;
}
static int mrl_horn_v7_fact(MrlKnowledgeStore*s,MrlHornPlanFact f,MrlKnowledgeFact*out){return mrl_horn_v7_fact_mode(s,f,out,0);}
static MrlHornPlan*mrl_horn_plan_new(const MrlHornPlanTemplate*t){
 if(!t||t->capacity<1||t->rule_count<0||t->rule_count>128||t->fact_count<0||t->fact_count>t->capacity)mrl_horn_v7_fail("invalid Horn template");
 MrlKnowledgeStore*s=mrl_knowledge_store_new(t->memory_budget);if(!s)mrl_horn_v7_fail("memory_budget");MrlHornPlan*p=ks_alloc(s->memory,sizeof(*p));if(!p){mrl_knowledge_store_release(s);mrl_horn_v7_fail("memory_budget");}
 p->refs=1;p->store=s;p->template=t;for(int32_t i=0;i<t->fact_count;i++){MrlKnowledgeFact f;if(!mrl_horn_v7_fact(s,t->facts[i],&f)||!(f.fact_id=(uint32_t)s->next_id+1,mrl_knowledge_store_restore_row(s,f)))mrl_horn_v7_fail("invalid initial fact or memory_budget");}
 /* Initial facts form version zero, not an externally observed edit. */
 s->version=0;s->change_count=0;return p;
}
static MrlHornPlan*mrl_horn_plan_copy(MrlHornPlan*p){if(!p||p->refs==UINT32_MAX)mrl_horn_v7_fail("Horn reference overflow");p->refs++;return p;}
static void mrl_horn_plan_release(MrlHornPlan*p){if(p&&!--p->refs){MrlKnowledgeStore*s=p->store;if(p->engine_ready)mrl_knowledge_engine_free(&p->engine);ks_free(p->durable_path);ks_free(p->durable_journal);ks_free(p);mrl_knowledge_store_release(s);}}
static char*mrl_horn_v7_plan_string(KsMemory*m,const char*x){if(!x)return NULL;size_t n=strlen(x)+1;char*y=ks_alloc(m,n);if(y)memcpy(y,x,n);return y;}
static void mrl_horn_v7_detach(MrlHornPlan**slot){MrlHornPlan*p=*slot;if(p->refs==1)return;MrlKnowledgeStore*s=mrl_knowledge_store_snapshot(p->store);if(!s)mrl_horn_v7_fail("memory_budget");MrlHornPlan*q=ks_alloc(s->memory,sizeof(*q));if(!q){mrl_knowledge_store_release(s);mrl_horn_v7_fail("memory_budget");}q->refs=1;q->store=s;q->template=p->template;q->durable_path=mrl_horn_v7_plan_string(s->memory,p->durable_path);q->durable_journal=mrl_horn_v7_plan_string(s->memory,p->durable_journal);if((p->durable_path&&!q->durable_path)||(p->durable_journal&&!q->durable_journal)){ks_free(q->durable_path);ks_free(q->durable_journal);ks_free(q);mrl_knowledge_store_release(s);mrl_horn_v7_fail("memory_budget");}q->durable_version=p->durable_version;q->durable_rows=p->durable_rows;q->durable_symbols=p->durable_symbols;q->journal_needs_repair=p->journal_needs_repair;mrl_horn_plan_release(p);*slot=q;}
static int32_t mrl_horn_plan_version(const MrlHornPlan*p){if(p->store->version>INT32_MAX)mrl_horn_v7_fail("version exceeds si32");return (int32_t)p->store->version;}
static bool mrl_horn_plan_add(MrlHornPlan**slot,const char*id,const char*s,const char*q,const char*o,bool polarity,const char*modality,MrlHornEvidence evidence){
 MrlHornPlan*p=*slot;uint32_t name=mrl_knowledge_store_find_symbol(p->store,id);if(name&&mrl_knowledge_store_find_id(p->store,name))return false;
 if(p->store->count>=(size_t)p->template->capacity)mrl_horn_v7_fail("fact_limit");mrl_horn_v7_detach(slot);p=*slot;MrlKnowledgeFact f;
 if(!mrl_horn_v7_fact(p->store,(MrlHornPlanFact){id,s,q,o,modality,polarity,evidence},&f)||!mrl_knowledge_store_append(p->store,f,1))mrl_horn_v7_fail("invalid fact or memory_budget");return true;
}
static bool mrl_horn_plan_remove(MrlHornPlan**slot,const char*id){if(mrl_horn_v7_reserved_id(id))return false;MrlHornPlan*p=*slot;uint32_t name=mrl_knowledge_store_find_symbol(p->store,id),row=mrl_knowledge_store_find_id(p->store,name);if(!row)return false;mrl_horn_v7_detach(slot);if(!mrl_knowledge_store_remove((*slot)->store,row))mrl_horn_v7_fail("memory_budget");return true;}
static bool mrl_horn_plan_correct(MrlHornPlan**slot,const char*id,const char*s,const char*q,const char*o,bool polarity,const char*modality,MrlHornEvidence evidence){
 if(mrl_horn_v7_reserved_id(id))return false;
 MrlHornPlan*p=*slot;uint32_t name=mrl_knowledge_store_find_symbol(p->store,id),row=mrl_knowledge_store_find_id(p->store,name);if(!row)return false;mrl_horn_v7_detach(slot);p=*slot;MrlKnowledgeFact f;
 if(!mrl_horn_v7_fact(p->store,(MrlHornPlanFact){id,s,q,o,modality,polarity,evidence},&f)||!mrl_knowledge_store_correct(p->store,row,f))mrl_horn_v7_fail("invalid fact or memory_budget");return true;
}
static MrlHornSnapshot*mrl_horn_v7_snapshot(MrlHornPlan*p,bool complete);
static int mrl_horn_v7_target_derived(MrlHornPlan*p,const char*s,const char*q,const char*o,uint64_t budget);
static char*mrl_horn_v7_identity(MrlKnowledgeStore*store,uint64_t version,const char*kind,int32_t s,int32_t p,int32_t o,int32_t rule);
static void mrl_horn_v7_rollback_symbols(MrlKnowledgeStore*s,uint32_t before);
static bool mrl_horn_plan_withdraw(MrlHornPlan**slot,const char*id){return mrl_horn_plan_remove(slot,id);}
static bool mrl_horn_plan_replace_kind(MrlHornPlan**slot,const char*old_id,const char*new_id,const char*s,const char*q,const char*o,bool polarity,const char*modality,MrlHornEvidence evidence,const char*relation){
 if(!old_id||!new_id||!strcmp(old_id,new_id)||mrl_horn_v7_reserved_id(old_id)||mrl_horn_v7_reserved_id(new_id))return false;
 MrlHornPlan*p=*slot;uint32_t old_symbol=mrl_knowledge_store_find_symbol(p->store,old_id),old_fact_id=mrl_knowledge_store_find_id(p->store,old_symbol);if(!old_fact_id||mrl_horn_v7_historical_id(p->store,new_id))return false;
 size_t old_n=strlen(old_id),relation_n=strlen(relation);if(old_n>SIZE_MAX-relation_n-18)return false;size_t bytes=old_n+relation_n+18;char*history_id=malloc(bytes);if(!history_id)return false;snprintf(history_id,bytes,"__mrl_history__:%s:%s",relation,old_id);
 if(mrl_knowledge_store_find_id(p->store,mrl_knowledge_store_find_symbol(p->store,history_id))){free(history_id);return false;}
 mrl_horn_v7_detach(slot);p=*slot;MrlKnowledgeStore*stage=mrl_knowledge_store_snapshot(p->store);if(!stage){free(history_id);return false;}uint32_t symbols=stage->symbols->next;
 MrlKnowledgeFact replacement,history;int ok=mrl_horn_v7_fact(stage,(MrlHornPlanFact){new_id,s,q,o,modality,polarity,evidence},&replacement);
 if(ok)ok=mrl_knowledge_store_remove(stage,old_fact_id);
 if(ok&&stage->count>=(size_t)p->template->capacity)ok=0;
 if(ok)ok=mrl_knowledge_store_append(stage,replacement,1);
 if(ok)ok=mrl_horn_v7_fact_mode(stage,(MrlHornPlanFact){history_id,old_id,relation,new_id,"planned",true,{0}},&history,1);
 if(ok)ok=stage->count<(size_t)p->template->capacity&&mrl_knowledge_store_append(stage,history,1);
 free(history_id);if(!ok){mrl_horn_v7_rollback_symbols(stage,symbols);mrl_knowledge_store_release(stage);return false;}MrlKnowledgeStore*old=p->store;p->store=stage;mrl_knowledge_store_release(old);return true;
}
static bool mrl_horn_plan_supersede(MrlHornPlan**slot,const char*old_id,const char*new_id,const char*s,const char*q,const char*o,bool polarity,const char*modality,MrlHornEvidence evidence){return mrl_horn_plan_replace_kind(slot,old_id,new_id,s,q,o,polarity,modality,evidence,"mrl:supersededBy");}
static bool mrl_horn_plan_replace(MrlHornPlan**slot,const char*old_id,const char*new_id,const char*s,const char*q,const char*o,bool polarity,const char*modality,MrlHornEvidence evidence){return mrl_horn_plan_replace_kind(slot,old_id,new_id,s,q,o,polarity,modality,evidence,"mrl:replacedBy");}
static const char*mrl_horn_plan_superseded_by(const MrlHornPlan*p,const char*old_id,const char*relation){if(!p||!old_id||!relation)return "";for(uint32_t id=1;id<=p->store->next_id;id++){MrlKnowledgeFact f;if(!mrl_knowledge_store_get_fact(p->store,id,&f)||f.modality!=1)continue;if(!mrl_horn_v7_reserved_id(mrl_knowledge_store_symbol(p->store,f.id)))continue;if(!strcmp(mrl_knowledge_store_symbol(p->store,f.subject),old_id)&&!strcmp(mrl_knowledge_store_symbol(p->store,f.predicate),relation))return mrl_knowledge_store_symbol(p->store,f.object);}return "";}
static MrlHornSnapshot*mrl_horn_plan_history_fact(MrlHornPlan*p,const char*id){MrlHornSnapshot*s=mrl_horn_v7_snapshot(p,true);uint32_t name=mrl_knowledge_store_find_symbol(p->store,id);if(!name)return s;for(uint32_t row=1;row<=p->store->next_id;row++){MrlKnowledgeFact f;if(!mrl_knowledge_store_get_any_fact(p->store,row,&f)||f.live||f.id!=name)continue;if(s->allocated==0){s->rows=ks_alloc(s->store->memory,sizeof(*s->rows));if(!s->rows)mrl_horn_v7_fail("memory_budget");s->allocated=1;}MrlHornSnapshotRow*r=s->rows+s->count++;memset(r,0,sizeof(*r));r->s=(int32_t)f.subject;r->p=(int32_t)f.predicate;r->o=(int32_t)f.object;r->rule=-1;r->support=f.fact_id;r->support_count=1;r->removed=1;r->polarity=f.polarity;r->support_ids=ks_alloc(s->store->memory,sizeof(*r->support_ids));if(!r->support_ids)mrl_horn_v7_fail("memory_budget");r->support_ids[0]=f.fact_id;r->node_id=mrl_horn_v7_identity(s->store,s->version,"fact",r->s,r->p,r->o,-1);r->proof_node_id=mrl_horn_v7_identity(s->store,s->version,"proof",r->s,r->p,r->o,-1);if(!r->node_id||!r->proof_node_id)mrl_horn_v7_fail("memory_budget");break;}return s;}
static int32_t mrl_horn_v7_term(MrlKnowledgeStore*s,const char*t,const char**vars,int*count,int head){
 if(t[0]!='?'){int32_t id=mrl_horn_v7_intern(s,t);if(id<0)mrl_horn_v7_fail("memory_budget");return id;}for(int i=0;i<*count;i++)if(!strcmp(vars[i],t))return -i-1;
 if(head||*count==8)mrl_horn_v7_fail("unsafe rule or variable_limit");vars[(*count)++]=t;return -*count;
}
static int mrl_horn_v7_engine_start(MrlHornPlan*p){
 MrlKnowledgeRule rules[128];int32_t bodies[128][24];for(int r=0;r<p->template->rule_count;r++){
  const MrlHornPlanRule*t=p->template->rules+r;if(t->body_count<1||t->body_count>8)mrl_horn_v7_fail("premise_limit");const char*vars[8];int count=0;
  rules[r].body=bodies[r];rules[r].premises=t->body_count;rules[r].id=r;
  for(int k=0;k<t->body_count;k++)for(int j=0;j<3;j++)bodies[r][k*3+j]=mrl_horn_v7_term(p->store,t->body[k][j],vars,&count,0);
  for(int j=0;j<3;j++)rules[r].head[j]=mrl_horn_v7_term(p->store,t->head[j],vars,&count,1);
 }
 p->engine_ready=1;return mrl_knowledge_engine_init_with_allocator(&p->engine,rules,p->template->rule_count,UINT64_C(1000000000),p->store->memory,ks_resize_memory,ks_free_memory);
}
static int mrl_horn_v7_apply(MrlHornPlan*p,uint32_t id){
 MrlKnowledgeEngine*e=&p->engine;int32_t previous=mke_find_id(e,id);if(previous>=0&&e->assertions[previous].live&&!mrl_knowledge_remove(e,id))return 0;
 MrlKnowledgeFact f;if(!mrl_knowledge_store_get_fact(p->store,id,&f)||f.modality!=0)return 1;
 return f.polarity?mrl_knowledge_assert(e,id,f.subject,f.predicate,f.object):mrl_knowledge_deny(e,id,f.subject,f.predicate,f.object);
}
static bool mrl_horn_v7_change(const MrlKnowledgeChange*c,void*ctx){return mrl_horn_v7_apply(ctx,c->fact_id)!=0;}
static int mrl_horn_v7_sync(MrlHornPlan*p,int32_t limit,uint64_t work){
 int fresh=!p->engine_ready;
 if(p->engine_ready&&p->engine.status){mrl_knowledge_engine_free(&p->engine);p->engine_ready=0;fresh=1;}
 if(fresh&&!mrl_horn_v7_engine_start(p))return 0;
 MrlKnowledgeEngine*e=&p->engine;e->fact_limit=(size_t)limit;e->work=work;
 if(fresh){for(uint32_t i=1;i<=p->store->next_id;i++)if(!mrl_horn_v7_apply(p,i))return 0;}
 else if(p->engine_version!=p->store->version&&!mrl_knowledge_store_changes_since(p->store,p->engine_version,mrl_horn_v7_change,p))return 0;
 if(e->live_count>(size_t)limit){e->status=MKE_LIMIT;return 0;}if(!mrl_knowledge_close(e))return 0;p->engine_version=p->store->version;return 1;
}
static MrlHornSnapshot*mrl_horn_v7_snapshot(MrlHornPlan*p,bool complete){
 MrlKnowledgeStore*store=mrl_knowledge_store_snapshot(p->store);if(!store)mrl_horn_v7_fail("memory_budget");MrlHornSnapshot*s=ks_alloc(store->memory,sizeof(*s));if(!s){mrl_knowledge_store_release(store);mrl_horn_v7_fail("memory_budget");}
 s->refs=1;s->store=store;s->template=p->template;s->version=store->version;s->complete=complete;s->reason=mrl_horn_v7_status(p->engine.status);s->work=p->engine.candidates;s->proof_limit=32;s->search_limit=16384;
 return s;
}
static char*mrl_horn_v7_identity(MrlKnowledgeStore*store,uint64_t version,const char*kind,int32_t s,int32_t p,int32_t o,int32_t rule){char text[160];int n=snprintf(text,sizeof(text),"%s:%llu:%d:%d:%d:%d",kind,(unsigned long long)version,s,p,o,rule);if(n<0||(size_t)n>=sizeof(text))return NULL;char*out=ks_alloc(store->memory,(size_t)n+1);if(out)memcpy(out,text,(size_t)n+1);return out;}
static char*mrl_horn_v7_copy_text(MrlKnowledgeStore*store,const char*text){size_t n=strlen(text)+1;char*out=ks_alloc(store->memory,n);if(out)memcpy(out,text,n);return out;}
static void mrl_horn_v7_capture(MrlHornSnapshot*s,const MrlKnowledgeEngine*e,const MrlKnowledgeDerivedFact*f,unsigned removed){
 if(s->count==s->allocated){size_t n=s->allocated?s->allocated*2:16;MrlHornSnapshotRow*rows=ks_resize_memory(s->store->memory,s->rows,n*sizeof(*rows));if(!rows)mrl_horn_v7_fail("memory_budget");s->rows=rows;s->allocated=n;}
 MrlHornSnapshotRow*r=s->rows+s->count++;memset(r,0,sizeof(*r));r->s=f->s;r->p=f->p;r->o=f->o;r->rule=f->rule;r->support=(uint32_t)f->id;r->support_count=f->supports;r->parent_count=f->parent_count;r->removed=removed;r->polarity=1;
 r->node_id=mrl_horn_v7_identity(s->store,s->version,"fact",f->s,f->p,f->o,-1);r->proof_node_id=mrl_horn_v7_identity(s->store,s->version,"proof",f->s,f->p,f->o,f->rule);if(!r->node_id||!r->proof_node_id)mrl_horn_v7_fail("memory_budget");
 if(r->rule<0&&r->support_count){r->support_ids=ks_alloc(s->store->memory,(size_t)r->support_count*sizeof(*r->support_ids));if(!r->support_ids)mrl_horn_v7_fail("memory_budget");uint32_t n=0;for(int32_t a=f->support_head;a>=0&&n<r->support_count;a=e->assertions[a].next){if(e->assertions[a].live&&!e->assertions[a].denial)r->support_ids[n++]=(uint32_t)e->assertions[a].id;}r->support_count=n;if(r->support_count>(uint32_t)s->proof_limit){s->complete=false;s->reason="proof_limit";}}
 for(int i=0;i<f->parent_count;i++){const MrlKnowledgeDerivedFact*x=e->facts+f->parents[i];r->parents[i][0]=x->s;r->parents[i][1]=x->p;r->parents[i][2]=x->o;r->parent_support_ids[i]=(uint32_t)x->id;MrlKnowledgeFact parent;const char*id=x->id&&mrl_knowledge_store_get_any_fact(s->store,(uint32_t)x->id,&parent)?mrl_knowledge_store_symbol(s->store,parent.id):NULL;r->parent_ids[i]=id?mrl_horn_v7_copy_text(s->store,id):mrl_horn_v7_identity(s->store,s->version,"fact",x->s,x->p,x->o,-1);if(!r->parent_ids[i])mrl_horn_v7_fail("memory_budget");}
}
typedef struct {MrlHornSnapshot*s;MrlKnowledgeEngine*e;}MrlHornCapture;
static int mrl_horn_v7_capture_row(const MrlKnowledgeDerivedFact*f,void*ctx){MrlHornCapture*c=ctx;mrl_horn_v7_capture(c->s,c->e,f,0);return 1;}
static MrlHornSnapshot*mrl_horn_plan_select(MrlHornPlan*p,const char*s,const char*q,const char*o){
 bool ok=mrl_horn_v7_sync(p,p->template->capacity,UINT64_C(1000000000));MrlHornSnapshot*snap=mrl_horn_v7_snapshot(p,ok);if(!ok)return snap;
 const char*t[3]={s,q,o};int32_t ids[3];for(int i=0;i<3;i++){ids[i]=t[i]?(int32_t)mrl_knowledge_store_find_symbol(p->store,t[i]):-1;if(t[i]&&!ids[i])return snap;}
 MrlHornCapture c={snap,&p->engine};mrl_knowledge_query(&p->engine,ids[0],ids[1],ids[2],mrl_horn_v7_capture_row,&c);return snap;
}
typedef struct{MrlHornSnapshot*s;MrlKnowledgeEngine*e;size_t limit;}MrlHornLimitedCapture;
static int mrl_horn_v7_capture_limited(const MrlKnowledgeDerivedFact*f,void*ctx){MrlHornLimitedCapture*c=ctx;if(c->s->count>=c->limit){c->s->complete=false;c->s->reason="result_limit";return 0;}mrl_horn_v7_capture(c->s,c->e,f,0);return 1;}
static MrlHornSnapshot*mrl_horn_plan_select_dynamic(MrlHornPlan*p,const char*s,const char*q,const char*o,int32_t limit,int32_t proof_limit,int32_t search_limit){
 if(limit<1||proof_limit<1||search_limit<1)mrl_horn_v7_fail("invalid reasoning budget");bool ok=mrl_horn_v7_sync(p,p->template->capacity,(uint64_t)search_limit);MrlHornSnapshot*snap=mrl_horn_v7_snapshot(p,ok);snap->proof_limit=proof_limit;snap->search_limit=search_limit;if(!ok)return snap;
 const char*t[3]={s,q,o};int32_t ids[3];for(int i=0;i<3;i++){ids[i]=t[i]?(int32_t)mrl_knowledge_store_find_symbol(p->store,t[i]):-1;if(t[i]&&!ids[i])return snap;}
 MrlHornLimitedCapture c={snap,&p->engine,(size_t)limit};mrl_knowledge_query(&p->engine,ids[0],ids[1],ids[2],mrl_horn_v7_capture_limited,&c);return snap;
}
static int32_t mrl_horn_plan_count(MrlHornPlan*p,const char*s,const char*q,const char*o){
 if(!mrl_horn_v7_sync(p,p->template->capacity,UINT64_C(1000000000)))mrl_horn_v7_fail(mrl_horn_v7_status(p->engine.status));
 const char*t[3]={s,q,o};int32_t ids[3];for(int i=0;i<3;i++){ids[i]=t[i]?(int32_t)mrl_knowledge_store_find_symbol(p->store,t[i]):-1;if(t[i]&&!ids[i])return 0;}
 return (int32_t)mrl_knowledge_query(&p->engine,ids[0],ids[1],ids[2],NULL,NULL);
}
static int32_t mrl_horn_plan_count_dynamic(MrlHornPlan*p,const char*s,const char*q,const char*o,int32_t search_limit){if(search_limit<1)mrl_horn_v7_fail("invalid reasoning budget");if(!mrl_horn_v7_sync(p,p->template->capacity,(uint64_t)search_limit))mrl_horn_v7_fail(mrl_horn_v7_status(p->engine.status));const char*t[3]={s,q,o};int32_t ids[3];for(int i=0;i<3;i++){ids[i]=t[i]?(int32_t)mrl_knowledge_store_find_symbol(p->store,t[i]):-1;if(t[i]&&!ids[i])return 0;}return (int32_t)mrl_knowledge_query(&p->engine,ids[0],ids[1],ids[2],NULL,NULL);}
static const char*mrl_horn_plan_status(MrlHornPlan*p,const char*s,const char*q,const char*o,int32_t search_limit){
 if(search_limit<1)return "incomplete";if(!mrl_horn_v7_sync(p,p->template->capacity,(uint64_t)search_limit))return "incomplete";uint32_t a=mrl_knowledge_store_find_symbol(p->store,s),b=mrl_knowledge_store_find_symbol(p->store,q),c=mrl_knowledge_store_find_symbol(p->store,o);int32_t row=a&&b&&c?mke_lookup(&p->engine,(int32_t)a,(int32_t)b,(int32_t)c):-1;
 if(row>=0&&p->engine.facts[row].denials){if(p->engine.facts[row].supports)return "contradicted";int derived=mrl_horn_v7_target_derived(p,s,q,o,(uint64_t)search_limit);if(derived<0)return "incomplete";if(derived)return "contradicted";}if(row>=0&&p->engine.facts[row].live)return "known";for(uint32_t id=1;id<=p->store->next_id;id++){MrlKnowledgeFact f;if(mrl_knowledge_store_get_any_fact(p->store,id,&f)&&!f.live&&f.subject==a&&f.predicate==b&&f.object==c)return "withdrawn";}return "unknown";
}
static int32_t mrl_horn_plan_epistemic_state(MrlHornPlan*p,const char*s,const char*q,const char*o,int32_t search_limit){const char*state=mrl_horn_plan_status(p,s,q,o,search_limit);if(!strcmp(state,"known"))return 0;if(!strcmp(state,"unknown"))return 1;if(!strcmp(state,"ambiguous"))return 2;if(!strcmp(state,"contradicted"))return 3;if(!strcmp(state,"withdrawn"))return 4;return 5;}
static bool mrl_horn_plan_exists(MrlHornPlan*p,const char*s,const char*q,const char*o){return mrl_horn_plan_count(p,s,q,o)!=0;}
static MrlHornSnapshot*mrl_horn_plan_changes(MrlHornPlan*p){
 bool ok=mrl_horn_v7_sync(p,p->template->capacity,UINT64_C(1000000000));MrlHornSnapshot*s=mrl_horn_v7_snapshot(p,ok);if(!ok)return s;
 MrlKnowledgeEngine*e=&p->engine;s->added=e->added_count;s->removed=e->removed_count;
 for(size_t i=0;i<e->added_count;i++)mrl_horn_v7_capture(s,e,e->facts+e->added[i],0);
 for(size_t i=0;i<e->removed_count;i++)mrl_horn_v7_capture(s,e,e->facts+e->removed[i],1);return s;
}
static MrlHornSnapshot*mrl_horn_evaluate(MrlHornPlan*p,int32_t op,int32_t limit,int32_t proof_limit,int32_t search_limit,int has_target,const char*s,const char*q,const char*o){
 (void)proof_limit;bool ok=mrl_horn_v7_sync(p,limit,(uint64_t)search_limit);MrlHornSnapshot*snap=mrl_horn_v7_snapshot(p,ok);
 if(op!=1){snap->complete=false;snap->reason="v7 selected proofs only";return snap;}
 MrlHornCapture c={snap,&p->engine};if(ok)mrl_knowledge_query(&p->engine,-1,-1,-1,mrl_horn_v7_capture_row,&c);
 if(has_target&&ok){uint32_t a=mrl_knowledge_store_find_symbol(p->store,s),b=mrl_knowledge_store_find_symbol(p->store,q),d=mrl_knowledge_store_find_symbol(p->store,o);if(!a||!b||!d||!mrl_knowledge_has(&p->engine,a,b,d)){snap->complete=false;snap->reason="target_missing";}}return snap;
}
static MrlHornSnapshot*mrl_horn_snapshot_retain(MrlHornSnapshot*s){if(!s||s->refs==UINT32_MAX)mrl_horn_v7_fail("snapshot reference overflow");s->refs++;return s;}
static void mrl_horn_snapshot_release(MrlHornSnapshot*s){if(s&&!--s->refs){MrlKnowledgeStore*store=s->store;for(size_t i=0;i<s->count;i++){MrlHornSnapshotRow*r=s->rows+i;ks_free(r->support_ids);ks_free(r->node_id);ks_free(r->proof_node_id);for(int j=0;j<r->parent_count;j++)ks_free(r->parent_ids[j]);for(uint32_t a=0;a<r->alternate_count;a++){ks_free(r->alternates[a].id);for(int j=0;j<r->alternates[a].parent_count;j++)ks_free(r->alternates[a].parent_ids[j]);}ks_free(r->alternates);}ks_free(s->conflicts);ks_free(s->rows);ks_free(s);mrl_knowledge_store_release(store);}}
static int32_t mrl_horn_snapshot_version(const MrlHornSnapshot*s){return (int32_t)s->version;}
static int32_t mrl_horn_snapshot_fact_count(const MrlHornSnapshot*s){return (int32_t)s->count;}
typedef struct{MrlHornSnapshot*s;MrlHornSnapshotRow*row;const MrlKnowledgeRule*rule;int32_t rule_index,parents[8],bindings[8];}MrlHornAltMatch;
static void mrl_horn_v7_alt_add(MrlHornAltMatch*c){MrlHornSnapshot*s=c->s;MrlHornSnapshotRow*r=c->row;const MrlKnowledgeRule*q=c->rule;int32_t h[3];for(int k=0;k<3;k++)h[k]=mke_value(q->head[k],c->bindings);if(h[0]!=r->s||h[1]!=r->p||h[2]!=r->o)return;
 if(r->rule==c->rule_index&&r->parent_count==q->premises){int same=1;for(int k=0;k<q->premises;k++){MrlKnowledgeDerivedFact*f=s->proof_engine->facts+c->parents[k];if(f->s!=r->parents[k][0]||f->p!=r->parents[k][1]||f->o!=r->parents[k][2]){same=0;break;}}if(same)return;}
 if((uint64_t)r->alternate_count+1>=(uint32_t)s->proof_limit){s->complete=false;s->reason="proof_limit";c->parents[0]=-2;return;}
 if(r->alternate_count==UINT32_MAX){s->complete=false;s->reason="proof_limit";c->parents[0]=-2;return;}MrlHornAlternateProof*alts=ks_resize_memory(s->store->memory,r->alternates,(size_t)(r->alternate_count+1)*sizeof(*alts));if(!alts){s->complete=false;s->reason="memory_budget";c->parents[0]=-2;return;}r->alternates=alts;MrlHornAlternateProof*a=r->alternates+r->alternate_count;memset(a,0,sizeof(*a));a->rule=c->rule_index;a->parent_count=q->premises;
 char id[256];int n=snprintf(id,sizeof(id),"proof-alt:%llu:%d:%d:%d:%d",(unsigned long long)s->version,r->s,r->p,r->o,c->rule_index);for(int k=0;k<q->premises;k++){int32_t pi=c->parents[k];MrlKnowledgeDerivedFact*f=s->proof_engine->facts+pi;a->parents[k][0]=f->s;a->parents[k][1]=f->p;a->parents[k][2]=f->o;if(n<0||(size_t)n>=sizeof(id)){s->complete=false;s->reason="proof_id_limit";goto fail_alternate;}int wrote=snprintf(id+n,sizeof(id)-(size_t)n,":%d",pi);if(wrote<0||(size_t)wrote>=sizeof(id)-(size_t)n){s->complete=false;s->reason="proof_id_limit";goto fail_alternate;}n+=wrote;MrlKnowledgeFact source;const char*source_id=f->id&&mrl_knowledge_store_get_any_fact(s->store,(uint32_t)f->id,&source)?mrl_knowledge_store_symbol(s->store,source.id):NULL;a->parent_ids[k]=source_id?mrl_horn_v7_copy_text(s->store,source_id):mrl_horn_v7_identity(s->store,s->version,"fact",f->s,f->p,f->o,-1);if(!a->parent_ids[k]){s->complete=false;s->reason="memory_budget";goto fail_alternate;}}
 a->id=mrl_horn_v7_copy_text(s->store,id);if(!a->id){s->complete=false;s->reason="memory_budget";goto fail_alternate;}r->alternate_count++;return;
 fail_alternate:for(int k=0;k<q->premises;k++)ks_free(a->parent_ids[k]);ks_free(a->id);memset(a,0,sizeof(*a));c->parents[0]=-2;
}
static void mrl_horn_v7_alt_join(MrlHornAltMatch*c,int32_t depth){if(c->parents[0]==-2)return;if(depth==c->rule->premises){mrl_horn_v7_alt_add(c);return;}MrlKnowledgeEngine*e=c->s->proof_engine;int32_t original[8];memcpy(original,c->bindings,sizeof(original));for(size_t i=0;i<e->count;i++){if(c->s->work+c->s->proof_work>=(uint64_t)c->s->search_limit){c->s->complete=false;c->s->reason="proof_search_limit";c->parents[0]=-2;return;}c->s->proof_work++;MrlKnowledgeDerivedFact*f=e->facts+i;if(!f->live)continue;int32_t bound[8];memcpy(bound,original,sizeof(bound));const int32_t*t=c->rule->body+depth*3;if(mke_bind(t[0],f->s,bound)&&mke_bind(t[1],f->p,bound)&&mke_bind(t[2],f->o,bound)){c->parents[depth]=(int32_t)i;memcpy(c->bindings,bound,sizeof(bound));mrl_horn_v7_alt_join(c,depth+1);memcpy(c->bindings,original,sizeof(original));if(c->parents[0]==-2)return;}}}
static void mrl_horn_snapshot_enumerate_proofs(MrlHornSnapshot*s,int32_t index){MrlHornSnapshotRow*r=s->rows+index;if(r->alternates_loaded)return;r->alternates_loaded=1;if(r->removed)return;uint64_t spent=s->work+s->proof_work;if(spent>=(uint64_t)s->search_limit||s->store->next_id>(uint64_t)s->search_limit-spent){s->complete=false;s->reason="proof_search_limit";return;}s->proof_work+=s->store->next_id;MrlHornPlan temp={0};temp.refs=1;temp.template=s->template;temp.store=mrl_knowledge_store_snapshot(s->store);if(!temp.store){s->complete=false;s->reason="memory_budget";return;}uint64_t remaining=(uint64_t)s->search_limit-s->work-s->proof_work;if(!remaining||!mrl_horn_v7_sync(&temp,temp.template->capacity,remaining)){s->complete=false;s->reason=temp.engine.status?mrl_horn_v7_status(temp.engine.status):"proof_search_limit";if(temp.engine_ready)mrl_knowledge_engine_free(&temp.engine);mrl_knowledge_store_release(temp.store);return;}if(temp.engine.candidates>(uint64_t)s->search_limit-s->work-s->proof_work){s->complete=false;s->reason="proof_search_limit";mrl_knowledge_engine_free(&temp.engine);mrl_knowledge_store_release(temp.store);return;}s->proof_work+=temp.engine.candidates;s->proof_engine=&temp.engine;int32_t target=mke_lookup(&temp.engine,r->s,r->p,r->o);if(target<0||!temp.engine.facts[target].live){s->complete=false;s->reason="proof_target_missing";}else for(int32_t ri=0;ri<(int32_t)temp.engine.rule_count;ri++){MrlKnowledgeRule*q=temp.engine.rules+ri;MrlHornAltMatch c={.s=s,.row=r,.rule=q,.rule_index=ri};for(int k=0;k<8;k++)c.bindings[k]=-1;for(int k=0;k<q->premises;k++)c.parents[k]=-1;mrl_horn_v7_alt_join(&c,0);if(c.parents[0]==-2)break;}s->proof_engine=NULL;if(temp.engine_ready)mrl_knowledge_engine_free(&temp.engine);mrl_knowledge_store_release(temp.store);}
static int32_t mrl_horn_snapshot_base_proof_count(const MrlHornSnapshotRow*r){return r->rule<0?(int32_t)r->support_count:1;}
static int32_t mrl_horn_snapshot_proof_count_at(const MrlHornSnapshot*view,int32_t index){MrlHornSnapshot*s=(MrlHornSnapshot*)view;if(!s||index<0||(size_t)index>=s->count)mrl_horn_v7_fail("Horn snapshot index");MrlHornSnapshotRow*r=s->rows+index;if(!r->removed)mrl_horn_snapshot_enumerate_proofs(s,index);size_t n=(size_t)mrl_horn_snapshot_base_proof_count(r)+r->alternate_count;if(n>(size_t)s->proof_limit){s->complete=false;s->reason="proof_limit";n=s->proof_limit;}return (int32_t)n;}
static int32_t mrl_horn_snapshot_proof_count(const MrlHornSnapshot*s){return (int32_t)s->count;}
static const char*mrl_horn_snapshot_term(const MrlHornSnapshot*s,int32_t index,int field){if(!s||index<0||(size_t)index>=s->count||field<0||field>2)mrl_horn_v7_fail("Horn snapshot index");MrlHornSnapshotRow*r=s->rows+index;return mrl_knowledge_store_symbol(s->store,field==0?r->s:field==1?r->p:r->o);}
static bool mrl_horn_snapshot_polarity(const MrlHornSnapshot*s,int32_t index){if(!s||index<0||(size_t)index>=s->count)mrl_horn_v7_fail("Horn snapshot index");return s->rows[index].polarity!=0;}
static const char*mrl_horn_snapshot_fact_id(const MrlHornSnapshot*s,int32_t index){if(!s||index<0||(size_t)index>=s->count)mrl_horn_v7_fail("Horn snapshot index");MrlKnowledgeFact f;MrlHornSnapshotRow*r=s->rows+index;return r->support&&mrl_knowledge_store_get_any_fact(s->store,r->support,&f)?mrl_knowledge_store_symbol(s->store,f.id):r->node_id;}
static void mrl_horn_snapshot_proof_check(const MrlHornSnapshot*s,int32_t fact,int32_t proof){int32_t n=mrl_horn_snapshot_proof_count_at(s,fact);if(proof<0||proof>=n)mrl_horn_v7_fail("Horn proof index");}
static uint32_t mrl_horn_snapshot_proof_support(const MrlHornSnapshot*s,int32_t fact,int32_t proof){MrlHornSnapshotRow*r=s->rows+fact;return r->rule<0&&proof<mrl_horn_snapshot_base_proof_count(r)?r->support_ids[proof]:0;}
static const char*mrl_horn_snapshot_proof_id(const MrlHornSnapshot*s,int32_t fact,int32_t proof){mrl_horn_snapshot_proof_check(s,fact,proof);MrlHornSnapshotRow*r=s->rows+fact;if(proof>=mrl_horn_snapshot_base_proof_count(r))return r->alternates[proof-mrl_horn_snapshot_base_proof_count(r)].id;uint32_t id=mrl_horn_snapshot_proof_support(s,fact,proof);MrlKnowledgeFact f;return id&&mrl_knowledge_store_get_any_fact(s->store,id,&f)?mrl_knowledge_store_symbol(s->store,f.id):r->proof_node_id;}
static const char*mrl_horn_snapshot_proof_kind(const MrlHornSnapshot*s,int32_t fact,int32_t proof){mrl_horn_snapshot_proof_check(s,fact,proof);MrlHornSnapshotRow*r=s->rows+fact;return r->removed?"withdrawn":proof>=mrl_horn_snapshot_base_proof_count(r)?"derived":r->rule<0?"asserted":"derived";}
static int32_t mrl_horn_snapshot_proof_rule_index(const MrlHornSnapshot*s,int32_t fact,int32_t proof){MrlHornSnapshotRow*r=s->rows+fact;return proof>=mrl_horn_snapshot_base_proof_count(r)?r->alternates[proof-mrl_horn_snapshot_base_proof_count(r)].rule:r->rule;}
static int32_t mrl_horn_snapshot_proof_parent(const MrlHornSnapshot*s,int32_t fact,int32_t proof,int32_t premise,int32_t term){MrlHornSnapshotRow*r=s->rows+fact;if(proof>=mrl_horn_snapshot_base_proof_count(r))return r->alternates[proof-mrl_horn_snapshot_base_proof_count(r)].parents[premise][term];return r->parents[premise][term];}
static const char*mrl_horn_snapshot_proof_rule(const MrlHornSnapshot*s,int32_t fact,int32_t proof){mrl_horn_snapshot_proof_check(s,fact,proof);int32_t rule=mrl_horn_snapshot_proof_rule_index(s,fact,proof);return rule<0?"":s->template->rules[rule].id;}
static const char*mrl_horn_snapshot_proof_rule_version(const MrlHornSnapshot*s,int32_t fact,int32_t proof){mrl_horn_snapshot_proof_check(s,fact,proof);int32_t rule=mrl_horn_snapshot_proof_rule_index(s,fact,proof);return rule<0?"":s->template->rules[rule].version_json;}
static int32_t mrl_horn_snapshot_proof_premise_count(const MrlHornSnapshot*s,int32_t fact,int32_t proof){mrl_horn_snapshot_proof_check(s,fact,proof);MrlHornSnapshotRow*r=s->rows+fact;return mrl_horn_snapshot_proof_rule_index(s,fact,proof)<0?0:s->template->rules[mrl_horn_snapshot_proof_rule_index(s,fact,proof)].body_count;}
static const char*mrl_horn_snapshot_proof_premise_id(const MrlHornSnapshot*s,int32_t fact,int32_t proof,int32_t premise){mrl_horn_snapshot_proof_check(s,fact,proof);MrlHornSnapshotRow*r=s->rows+fact;int32_t n=mrl_horn_snapshot_proof_premise_count(s,fact,proof);if(premise<0||premise>=n)mrl_horn_v7_fail("Horn premise index");if(proof>=mrl_horn_snapshot_base_proof_count(r))return r->alternates[proof-mrl_horn_snapshot_base_proof_count(r)].parent_ids[premise];return r->parent_ids[premise];}
static int32_t mrl_horn_snapshot_binding(const MrlHornSnapshot*s,int32_t fact,int32_t proof,int32_t binding,const char**name,const char**value){mrl_horn_snapshot_proof_check(s,fact,proof);MrlHornSnapshotRow*r=s->rows+fact;int32_t ri=mrl_horn_snapshot_proof_rule_index(s,fact,proof);if(ri<0)mrl_horn_v7_fail("Horn binding index");const MrlHornPlanRule*q=s->template->rules+ri;const char*vars[8];int32_t vals[8],n=0;for(int k=0;k<q->body_count;k++)for(int j=0;j<3;j++){const char*t=q->body[k][j];if(t[0]!='?')continue;int at=0;while(at<n&&strcmp(vars[at],t))at++;if(at<n)continue;if(n==8)mrl_horn_v7_fail("Horn binding count");vars[n]=t;vals[n++]=mrl_horn_snapshot_proof_parent(s,fact,proof,k,j);}if(binding<0||binding>=n)mrl_horn_v7_fail("Horn binding index");*name=vars[binding];*value=mrl_knowledge_store_symbol(s->store,vals[binding]);return n;}
static int32_t mrl_horn_snapshot_proof_binding_count(const MrlHornSnapshot*s,int32_t fact,int32_t proof){mrl_horn_snapshot_proof_check(s,fact,proof);MrlHornSnapshotRow*r=s->rows+fact;int32_t ri=mrl_horn_snapshot_proof_rule_index(s,fact,proof);if(ri<0)return 0;const MrlHornPlanRule*q=s->template->rules+ri;const char*vars[8];int32_t n=0;for(int k=0;k<q->body_count;k++)for(int j=0;j<3;j++){const char*t=q->body[k][j];if(t[0]!='?')continue;int at=0;while(at<n&&strcmp(vars[at],t))at++;if(at==n){if(n==8)mrl_horn_v7_fail("Horn binding count");vars[n++]=t;}}return n;}
static const char*mrl_horn_snapshot_proof_binding_name(const MrlHornSnapshot*s,int32_t fact,int32_t proof,int32_t binding){const char*n,*v;mrl_horn_snapshot_binding(s,fact,proof,binding,&n,&v);return n;}
static const char*mrl_horn_snapshot_proof_binding_value(const MrlHornSnapshot*s,int32_t fact,int32_t proof,int32_t binding){const char*n,*v;mrl_horn_snapshot_binding(s,fact,proof,binding,&n,&v);return v;}
static bool mrl_horn_snapshot_proof_complete(const MrlHornSnapshot*s,int32_t fact,int32_t proof){mrl_horn_snapshot_proof_check(s,fact,proof);MrlHornSnapshotRow*r=s->rows+fact;if(!s->complete)return false;if(r->rule<0)return true;return r->parent_count==s->template->rules[r->rule].body_count;}

typedef struct{uint32_t refs;char*id;MrlHornSnapshot*meaning;}MrlCandidate;
typedef struct{uint32_t refs;MrlCandidate**items;size_t count;}MrlCandidates;
typedef struct{uint32_t refs;unsigned has_required,has_forbidden,consistent;char*required[3],*forbidden[3];}MrlConstraint;
typedef struct{uint32_t refs;MrlConstraint**items;size_t count;}MrlConstraints;
enum{MRL_INTERPRETATION_SELECTED,MRL_INTERPRETATION_AMBIGUOUS,MRL_INTERPRETATION_UNKNOWN,MRL_INTERPRETATION_CONTRADICTED,MRL_INTERPRETATION_INCOMPLETE};
typedef struct{uint32_t refs;int32_t status;char*candidate_id;const char*reason;bool complete;}MrlInterpretation;
static char*mrl_horn_heap_copy(const char*s){if(!s)return NULL;size_t n=strlen(s)+1;char*p=malloc(n);if(p)memcpy(p,s,n);return p;}
static MrlCandidate*mrl_candidate_new(const char*id,MrlHornSnapshot*meaning){if(!id||!*id||!meaning)mrl_horn_v7_fail("invalid Candidate");MrlCandidate*c=calloc(1,sizeof(*c));if(!c)mrl_horn_v7_fail("memory_budget");c->id=mrl_horn_heap_copy(id);if(!c->id){free(c);mrl_horn_v7_fail("memory_budget");}c->refs=1;c->meaning=mrl_horn_snapshot_retain(meaning);return c;}
static MrlCandidate*mrl_candidate_retain(MrlCandidate*c){if(!c||c->refs==UINT32_MAX)mrl_horn_v7_fail("Candidate reference overflow");c->refs++;return c;}
static void mrl_candidate_release(MrlCandidate*c){if(c&&!--c->refs){free(c->id);mrl_horn_snapshot_release(c->meaning);free(c);}}
static MrlCandidates*mrl_candidates_new(MrlCandidate*const*items,size_t count){if(count&&!items)mrl_horn_v7_fail("invalid Candidates");MrlCandidates*c=calloc(1,sizeof(*c));if(!c)mrl_horn_v7_fail("memory_budget");c->items=count?calloc(count,sizeof(*c->items)):NULL;if(count&&!c->items){free(c);mrl_horn_v7_fail("memory_budget");}c->refs=1;c->count=count;for(size_t i=0;i<count;i++)c->items[i]=mrl_candidate_retain(items[i]);return c;}
static MrlCandidates*mrl_candidates_retain(MrlCandidates*c){if(!c||c->refs==UINT32_MAX)mrl_horn_v7_fail("Candidates reference overflow");c->refs++;return c;}
static void mrl_candidates_release(MrlCandidates*c){if(c&&!--c->refs){for(size_t i=0;i<c->count;i++)mrl_candidate_release(c->items[i]);free(c->items);free(c);}}
static MrlConstraint*mrl_constraint_new(int has_required,const char*const required[3],int has_forbidden,const char*const forbidden[3],bool consistent){
 MrlConstraint*c=calloc(1,sizeof(*c));if(!c)mrl_horn_v7_fail("memory_budget");c->refs=1;c->has_required=!!has_required;c->has_forbidden=!!has_forbidden;c->consistent=consistent;
 for(int k=0;k<3;k++){
  if(c->has_required&&(!required||!required[k]||!(c->required[k]=mrl_horn_heap_copy(required[k])))){for(int j=0;j<3;j++)free(c->required[j]);free(c);mrl_horn_v7_fail("invalid Constraint");}
  if(c->has_forbidden&&(!forbidden||!forbidden[k]||!(c->forbidden[k]=mrl_horn_heap_copy(forbidden[k])))){for(int j=0;j<3;j++){free(c->required[j]);free(c->forbidden[j]);}free(c);mrl_horn_v7_fail("invalid Constraint");}
 }
 return c;
}
static MrlConstraint*mrl_constraint_retain(MrlConstraint*c){if(!c||c->refs==UINT32_MAX)mrl_horn_v7_fail("Constraint reference overflow");c->refs++;return c;}
static void mrl_constraint_release(MrlConstraint*c){if(c&&!--c->refs){for(int j=0;j<3;j++){free(c->required[j]);free(c->forbidden[j]);}free(c);}}
static MrlConstraints*mrl_constraints_new(MrlConstraint*const*items,size_t count){if(count&&!items)mrl_horn_v7_fail("invalid Constraints");MrlConstraints*c=calloc(1,sizeof(*c));if(!c)mrl_horn_v7_fail("memory_budget");c->items=count?calloc(count,sizeof(*c->items)):NULL;if(count&&!c->items){free(c);mrl_horn_v7_fail("memory_budget");}c->refs=1;c->count=count;for(size_t i=0;i<count;i++)c->items[i]=mrl_constraint_retain(items[i]);return c;}
static MrlConstraints*mrl_constraints_retain(MrlConstraints*c){if(!c||c->refs==UINT32_MAX)mrl_horn_v7_fail("Constraints reference overflow");c->refs++;return c;}
static void mrl_constraints_release(MrlConstraints*c){if(c&&!--c->refs){for(size_t i=0;i<c->count;i++)mrl_constraint_release(c->items[i]);free(c->items);free(c);}}
static int mrl_horn_snapshot_has_term(const MrlHornSnapshot*s,const char*const t[3],uint64_t*work,uint64_t budget){if(!s->complete)return -1;for(size_t i=0;i<s->count;i++){if(++*work>budget)return -1;MrlHornSnapshotRow*r=s->rows+i;if(!strcmp(mrl_knowledge_store_symbol(s->store,r->s),t[0])&&!strcmp(mrl_knowledge_store_symbol(s->store,r->p),t[1])&&!strcmp(mrl_knowledge_store_symbol(s->store,r->o),t[2]))return 1;}return 0;}
typedef struct{const MrlHornSnapshot*s;const char*target[3];const MrlHornPlanRule*rule;const char*names[8],*values[8];int count;uint64_t*work,budget;int result;}MrlHornDeniedMatch;
static int mrl_horn_v7_term_matches(const char*term,const char*value,const char**names,const char**values,int*count){if(term[0]!='?')return !strcmp(term,value);int i=0;while(i<*count&&strcmp(names[i],term))i++;if(i<*count)return !strcmp(values[i],value);if(*count==8)return 0;names[*count]=term;values[*count]=value;(*count)++;return 1;}
static void mrl_horn_v7_denied_join(MrlHornDeniedMatch*c,int depth,const char**names,const char**values,int count){if(c->result)return;if(depth==c->rule->body_count){for(int k=0;k<3;k++){const char*t=c->rule->head[k];const char*v=t[0]=='?'?NULL:t;if(t[0]=='?'){int i=0;while(i<count&&strcmp(names[i],t))i++;if(i==count)return;v=values[i];}if(strcmp(v,c->target[k]))return;}c->result=1;return;}for(size_t i=0;i<c->s->count;i++){if(++*c->work>c->budget){c->result=-1;return;}const MrlHornSnapshotRow*r=c->s->rows+i;const char*terms[3]={mrl_knowledge_store_symbol(c->s->store,r->s),mrl_knowledge_store_symbol(c->s->store,r->p),mrl_knowledge_store_symbol(c->s->store,r->o)};const char*next_names[8],*next_values[8];memcpy(next_names,names,(size_t)count*sizeof(*names));memcpy(next_values,values,(size_t)count*sizeof(*values));int next_count=count,ok=1;for(int k=0;k<3;k++)if(!mrl_horn_v7_term_matches(c->rule->body[depth][k],terms[k],next_names,next_values,&next_count)){ok=0;break;}if(ok)mrl_horn_v7_denied_join(c,depth+1,next_names,next_values,next_count);if(c->result)return;}}
static int mrl_horn_v7_target_derived(MrlHornPlan*p,const char*s,const char*q,const char*o,uint64_t budget){MrlHornSnapshot*snap=mrl_horn_v7_snapshot(p,true);MrlHornCapture capture={snap,&p->engine};mrl_knowledge_query(&p->engine,-1,-1,-1,mrl_horn_v7_capture_row,&capture);uint64_t work=p->engine.candidates;if(work>budget||snap->count>budget-work){mrl_horn_snapshot_release(snap);return -1;}work+=snap->count;const char*target[3]={s,q,o};int result=0;for(int32_t ri=0;ri<snap->template->rule_count;ri++){if(++work>budget){result=-1;break;}MrlHornDeniedMatch c={.s=snap,.target={target[0],target[1],target[2]},.rule=snap->template->rules+ri,.work=&work,.budget=budget};mrl_horn_v7_denied_join(&c,0,c.names,c.values,0);if(c.result){result=c.result;break;}}mrl_horn_snapshot_release(snap);return result;}
static int mrl_horn_snapshot_conflicted(const MrlHornSnapshot*s,uint64_t*work,uint64_t budget){for(uint32_t i=1;i<=s->store->next_id;i++){MrlKnowledgeFact denial;if(++*work>budget)return -1;if(!mrl_knowledge_store_get_fact(s->store,i,&denial)||denial.modality!=0||denial.polarity)continue;const char*target[3]={mrl_knowledge_store_symbol(s->store,denial.subject),mrl_knowledge_store_symbol(s->store,denial.predicate),mrl_knowledge_store_symbol(s->store,denial.object)};for(uint32_t j=1;j<=s->store->next_id;j++){MrlKnowledgeFact positive;if(++*work>budget)return -1;if(mrl_knowledge_store_get_fact(s->store,j,&positive)&&positive.modality==0&&positive.polarity&&positive.subject==denial.subject&&positive.predicate==denial.predicate&&positive.object==denial.object)return 1;}for(size_t j=0;j<s->count;j++){if(++*work>budget)return -1;const MrlHornSnapshotRow*r=s->rows+j;if(r->s==(int32_t)denial.subject&&r->p==(int32_t)denial.predicate&&r->o==(int32_t)denial.object)return 1;}for(int32_t ri=0;ri<s->template->rule_count;ri++){if(++*work>budget)return -1;MrlHornDeniedMatch c={.s=s,.target={target[0],target[1],target[2]},.rule=s->template->rules+ri,.work=work,.budget=budget};mrl_horn_v7_denied_join(&c,0,c.names,c.values,0);if(c.result)return c.result;}}return 0;}
static MrlInterpretation*mrl_horn_interpret(const MrlCandidates*candidates,const MrlConstraints*constraints,int32_t budget){if(!candidates||!constraints||budget<1)mrl_horn_v7_fail("invalid interpretation budget");MrlInterpretation*out=calloc(1,sizeof(*out));if(!out)mrl_horn_v7_fail("memory_budget");out->refs=1;out->status=MRL_INTERPRETATION_INCOMPLETE;out->reason="work_limit";out->complete=false;uint64_t work=0;size_t viable=0;int contradicted=0;const char*selected=NULL;
 for(size_t i=0;i<candidates->count;i++){if(++work>(uint64_t)budget)goto done;MrlCandidate*c=candidates->items[i];MrlHornSnapshot*s=c->meaning;if(!s->complete)goto done;int valid=1;for(size_t j=0;j<constraints->count;j++){if(++work>(uint64_t)budget)goto done;MrlConstraint*q=constraints->items[j];if(q->consistent){int conflict=mrl_horn_snapshot_conflicted(s,&work,(uint64_t)budget);if(conflict<0)goto done;if(conflict){contradicted=1;valid=0;break;}}
  if(q->has_required){int found=mrl_horn_snapshot_has_term(s,(const char*const*)q->required,&work,(uint64_t)budget);if(found<0)goto done;if(!found){valid=0;break;}}
  if(q->has_forbidden){int found=mrl_horn_snapshot_has_term(s,(const char*const*)q->forbidden,&work,(uint64_t)budget);if(found<0)goto done;if(found){valid=0;break;}}}
 if(valid){selected=c->id;if(++viable>1){out->status=MRL_INTERPRETATION_AMBIGUOUS;out->reason="multiple_candidates";out->complete=true;return out;}}}
 out->complete=true;if(viable==1){out->status=MRL_INTERPRETATION_SELECTED;out->reason="selected";out->candidate_id=mrl_horn_heap_copy(selected);if(!out->candidate_id)mrl_horn_v7_fail("memory_budget");}else if(contradicted){out->status=MRL_INTERPRETATION_CONTRADICTED;out->reason="inconsistent_meaning";}else{out->status=MRL_INTERPRETATION_UNKNOWN;out->reason="no_candidate";}return out;
 done:out->status=MRL_INTERPRETATION_INCOMPLETE;out->reason="work_limit";out->complete=false;return out;}
static MrlInterpretation*mrl_interpretation_retain(MrlInterpretation*i){if(!i||i->refs==UINT32_MAX)mrl_horn_v7_fail("Interpretation reference overflow");i->refs++;return i;}
static void mrl_interpretation_release(MrlInterpretation*i){if(i&&!--i->refs){free(i->candidate_id);free(i);}}
static int32_t mrl_interpretation_status(const MrlInterpretation*i){return i?i->status:MRL_INTERPRETATION_INCOMPLETE;}
static bool mrl_interpretation_candidate_id_some(const MrlInterpretation*i){return i&&i->status==MRL_INTERPRETATION_SELECTED&&i->candidate_id;}
static const char*mrl_interpretation_candidate_id(const MrlInterpretation*i){return i&&i->candidate_id?i->candidate_id:"";}
static const char*mrl_interpretation_reason(const MrlInterpretation*i){return i&&i->reason?i->reason:"invalid";}
static bool mrl_interpretation_complete(const MrlInterpretation*i){return i&&i->complete;}
static int32_t mrl_horn_snapshot_searches(const MrlHornSnapshot*s){return s->work>INT32_MAX?INT32_MAX:(int32_t)s->work;}
static bool mrl_horn_snapshot_complete(const MrlHornSnapshot*s){return s->complete;}
static const char*mrl_horn_snapshot_reason(const MrlHornSnapshot*s){return s->reason;}
static int32_t mrl_horn_snapshot_added_count(const MrlHornSnapshot*s){return (int32_t)s->added;}
static int32_t mrl_horn_snapshot_removed_count(const MrlHornSnapshot*s){return (int32_t)s->removed;}
static void mrl_horn_v7_string(const char*s){putchar('"');for(const unsigned char*p=(const unsigned char*)s;*p;p++){if(*p=='"'||*p=='\\'){putchar('\\');putchar(*p);}else if(*p<32)printf("\\u%04x",*p);else putchar(*p);}putchar('"');}
static void mrl_horn_v7_triple(const MrlHornSnapshot*s,int32_t a,int32_t p,int32_t o){putchar('[');mrl_horn_v7_string(mrl_knowledge_store_symbol(s->store,a));putchar(',');mrl_horn_v7_string(mrl_knowledge_store_symbol(s->store,p));putchar(',');mrl_horn_v7_string(mrl_knowledge_store_symbol(s->store,o));putchar(']');}
static void mrl_horn_snapshot_print(const MrlHornSnapshot*s){
 fputs("{\"known\":{\"$tuple_map\":[",stdout);for(size_t i=0;i<s->count;i++){const MrlHornSnapshotRow*r=s->rows+i;if(i)putchar(',');fputs("{\"key\":",stdout);mrl_horn_v7_triple(s,r->s,r->p,r->o);fputs(",\"value\":{\"fact\":",stdout);mrl_horn_v7_triple(s,r->s,r->p,r->o);
  if(r->rule>=0){fputs(",\"rule\":",stdout);mrl_horn_v7_string(s->template->rules[r->rule].id);fputs(",\"parents\":[",stdout);for(int j=0;j<r->parent_count;j++){if(j)putchar(',');mrl_horn_v7_triple(s,r->parents[j][0],r->parents[j][1],r->parents[j][2]);}putchar(']');}
  else{MrlKnowledgeFact f;fputs(",\"evidence\":{",stdout);if(mrl_knowledge_store_get_any_fact(s->store,r->support,&f)&&f.evidence){fputs("\"source\":",stdout);mrl_horn_v7_string(mrl_knowledge_store_symbol(s->store,f.evidence_source));printf(",\"start\":%u,\"end\":%u,\"text\":",f.start,f.end);mrl_horn_v7_string(mrl_knowledge_store_symbol(s->store,f.evidence_text));}putchar('}');}
  if(r->removed)fputs(",\"removed\":true",stdout);fputs("}}",stdout);
 }fputs("]},\"complete\":",stdout);fputs(s->complete?"true":"false",stdout);fputs(",\"reason\":",stdout);mrl_horn_v7_string(s->reason);printf(",\"version\":%llu}\n",(unsigned long long)s->version);
}

/* File admission builds a private page root and commits only a complete batch.
   Symbols added by a rejected single-threaded transaction are rolled back too. */
static void mrl_horn_v7_rollback_symbols(MrlKnowledgeStore*s,uint32_t before){MrlKnowledgeSymbols*p=s->symbols;while(p->next>before){MrlKnowledgeSymbolRow*r=p->by_id[p->next];MrlKnowledgeSymbolRow**at=&p->bucket[r->hash&(p->buckets-1)];while(*at&&*at!=r)at=&(*at)->next;if(*at)*at=r->next;p->by_id[p->next--]=NULL;ks_free(r);}}
static const char*mrl_horn_v7_load_line(MrlKnowledgeStore*s,const char*line,int32_t capacity,int32_t*count){
 const char*text=line;jws(&text);if(!*text)return NULL;MrlHornJsonFact f={0};if(!jfact(line,&f))return "JSONL syntax or Evidence";
 const char*error=NULL;MrlKnowledgeFact row;MrlHornEvidence ev={f.evidence.source!=NULL,f.evidence.source,f.evidence.text,f.evidence.start,f.evidence.end};
 if(s->count>=(size_t)capacity)error="fact_limit";
 else if(!mrl_horn_v7_fact(s,(MrlHornPlanFact){f.id,f.subject,f.predicate,f.object,f.modality,f.polarity,ev},&row))error="invalid fact or memory_budget";
 else if(mrl_knowledge_store_find_id(s,row.id))error="duplicate fact id";
 else if(!mrl_knowledge_store_append(s,row,1))error="memory_budget";else (*count)++;
 mrl_horn_json_fact_free(&f);return error;
}
static MrlHornLoadResult mrl_horn_plan_load(MrlHornPlan**slot,const char*path){
 MrlHornPlan*p=*slot;FILE*f=mrl_horn_jsonl_open(path);if(!f)return (MrlHornLoadResult){false,0,"JSONL file"};
 MrlKnowledgeStore*stage=mrl_knowledge_store_snapshot(p->store);if(!stage){fclose(f);return (MrlHornLoadResult){false,0,"memory_budget"};}
 uint32_t symbols=stage->symbols->next;size_t first_change=stage->change_count,bytes=0,length=0,capacity=0;uint64_t version=stage->version;int32_t count=0;char*line=NULL;int ch;const char*error=NULL;
 MrlHornJsonReader reader={f};while((ch=mrl_horn_jsonl_getc(&reader))!=EOF){
  if(++bytes>p->template->memory_budget){error="JSONL byte budget";break;}
  if(!ch){error="JSONL NUL";break;}
  if(ch=='\n'){if(!jput(&line,&length,&capacity,0)){error="JSONL allocation";break;}error=mrl_horn_v7_load_line(stage,line,p->template->capacity,&count);length=0;if(error)break;}
  else{if(length>=1024u*1024u){error="JSONL record exceeds 1 MiB";break;}if(!jput(&line,&length,&capacity,(unsigned char)ch)){error="JSONL allocation";break;}}
 }
 if(!error&&ferror(f))error="JSONL read";
 if(!error&&length){if(!jput(&line,&length,&capacity,0))error="JSONL allocation";else error=mrl_horn_v7_load_line(stage,line,p->template->capacity,&count);}
 free(line);fclose(f);
 if(error){mrl_horn_v7_rollback_symbols(stage,symbols);mrl_knowledge_store_release(stage);return (MrlHornLoadResult){false,0,error};}
 if(!count){mrl_knowledge_store_release(stage);return (MrlHornLoadResult){true,0,NULL};}
 stage->version=version+1;for(size_t i=first_change;i<stage->change_count;i++){MrlKnowledgeChange*c=ks_cell(stage->log,i,sizeof(*c));c->version=stage->version;}
 mrl_horn_v7_detach(slot);p=*slot;MrlKnowledgeStore*old=p->store;p->store=stage;mrl_knowledge_store_release(old);return (MrlHornLoadResult){true,count,NULL};
}
static uint64_t mrl_horn_v7_hash_string(uint64_t h,const char*s){if(!s)s="null";do{h^=(unsigned char)*s;h*=UINT64_C(1099511628211);}while(*s++);return h;}
static uint64_t mrl_horn_v7_fingerprint(const MrlHornPlanTemplate*t){
 uint64_t h=mrl_horn_v7_hash_string(UINT64_C(1469598103934665603),"MRL-Horn-v7-selected-proof-v1");
 for(int32_t r=0;r<t->rule_count;r++){const MrlHornPlanRule*q=t->rules+r;h=mrl_horn_v7_hash_string(h,q->id);h=mrl_horn_v7_hash_string(h,q->version_json);h^=(uint32_t)q->body_count;h*=UINT64_C(1099511628211);
  for(int k=0;k<q->body_count;k++)for(int j=0;j<3;j++)h=mrl_horn_v7_hash_string(h,q->body[k][j]);for(int j=0;j<3;j++)h=mrl_horn_v7_hash_string(h,q->head[j]);}return h;
}
static char*mrl_horn_v7_path(KsMemory*memory,const char*path,const char*suffix){size_t n=strlen(path),z=strlen(suffix);if(n>SIZE_MAX-z-1)return NULL;char*p=ks_alloc(memory,n+z+1);if(p){memcpy(p,path,n);memcpy(p+n,suffix,z+1);}return p;}
static int mrl_horn_v7_durable(MrlHornPlan*p,const char*path,uint64_t identity){
 char suffix[64];snprintf(suffix,sizeof(suffix),".journal.%016llx",(unsigned long long)identity);
 char*name=mrl_horn_v7_path(p->store->memory,path,""),*journal=mrl_horn_v7_path(p->store->memory,path,suffix);
 if(!name||!journal){ks_free(name);ks_free(journal);return 0;}ks_free(p->durable_path);ks_free(p->durable_journal);p->durable_path=name;p->durable_journal=journal;
 p->durable_version=p->store->version;p->durable_rows=(uint32_t)p->store->next_id;p->durable_symbols=p->store->symbols->next;return 1;
}
static MrlHornLoadResult mrl_horn_plan_save(MrlHornPlan*p,const char*path){
 if(!mrl_horn_v7_sync(p,p->template->capacity,UINT64_C(1000000000)))return (MrlHornLoadResult){false,0,mrl_horn_v7_status(p->engine.status)};
 uint64_t fp=mrl_horn_v7_fingerprint(p->template);const char*error=mrl_knowledge_persist_save(p->store,path,fp);
 if(error)return (MrlHornLoadResult){false,0,error};
 uint64_t identity=mrl_knowledge_cache_store_identity(p->store);char*cache=mrl_horn_v7_path(p->store->memory,path,".cache");if(!cache)return (MrlHornLoadResult){false,0,"memory_budget"};
 error=mrl_knowledge_engine_cache_save_identity(&p->engine,p->store,cache,fp,identity);ks_free(cache);if(error)return (MrlHornLoadResult){false,0,error};
 if(!mrl_horn_v7_durable(p,path,identity))return (MrlHornLoadResult){false,0,"memory_budget"};
 return (MrlHornLoadResult){true,(int32_t)p->store->count,NULL};
}
/* ponytail: one writer per checkpoint; immutable checkpoint generations keep a
   crash between checkpoint/cache writes safe. Old journal generations remain
   for recovery and can be removed after the owning checkpoint is retired. */
static MrlHornLoadResult mrl_horn_plan_commit(MrlHornPlan**slot,const char*path){
 MrlHornPlan*p=*slot;if(p->refs!=1||!p->durable_path||strcmp(p->durable_path,path))return (MrlHornLoadResult){false,0,"save or restore this unshared plan before commit"};
 if(p->durable_version==p->store->version)return (MrlHornLoadResult){true,0,NULL};
 if(p->journal_needs_repair){if(mrl_knowledge_delta_repair(p->durable_journal))return (MrlHornLoadResult){false,0,"knowledge journal repair"};p->journal_needs_repair=0;}
 const char*error=mrl_knowledge_delta_commit(p->store,p->durable_journal,mrl_horn_v7_fingerprint(p->template),p->durable_version,p->durable_rows,p->durable_symbols);
 if(error){/* A failed flush has an ambiguous commit outcome; reopen before retry. */ks_free(p->durable_path);p->durable_path=NULL;return (MrlHornLoadResult){false,0,error};}p->durable_version=p->store->version;p->durable_rows=(uint32_t)p->store->next_id;p->durable_symbols=p->store->symbols->next;
 return (MrlHornLoadResult){true,(int32_t)p->store->count,NULL};
}
static MrlHornLoadResult mrl_horn_plan_restore(MrlHornPlan**slot,const char*path){
 const MrlHornPlanTemplate*t=(*slot)->template;const char*error=NULL;uint64_t fp=mrl_horn_v7_fingerprint(t);
 MrlKnowledgeStore*store=mrl_knowledge_persist_open(path,t->memory_budget,fp,&error);
 if(!store)return (MrlHornLoadResult){false,0,error};if(store->count>(size_t)t->capacity){mrl_knowledge_store_release(store);return (MrlHornLoadResult){false,0,"fact_limit"};}
 MrlHornPlan*p=ks_alloc(store->memory,sizeof(*p));if(!p){mrl_knowledge_store_release(store);return (MrlHornLoadResult){false,0,"memory_budget"};}
 uint64_t identity=mrl_knowledge_cache_store_identity(store);p->refs=1;p->store=store;p->template=t;if(!mrl_horn_v7_durable(p,path,identity)){error="memory_budget";goto fail;}uint32_t symbols=store->symbols->next;
 if(mrl_horn_v7_engine_start(p)){
  char*cache=mrl_horn_v7_path(store->memory,path,".cache");
  p->cache_hit=cache&&!(store->symbols->next==symbols?mrl_knowledge_engine_cache_load_identity(&p->engine,store,cache,fp,identity):mrl_knowledge_engine_cache_load(&p->engine,store,cache,fp));ks_free(cache);
  if(p->cache_hit)p->engine_version=store->version;
 }
 if(!p->cache_hit){mrl_knowledge_engine_free(&p->engine);p->engine_ready=0;}
 /* Read the cache before applying the journal, so only new mutations infer. */
 errno=0;FILE*journal=mrl_horn_jsonl_open(p->durable_journal);
 if(!journal&&errno!=ENOENT){error="knowledge journal open";goto fail;}
 if(journal){fclose(journal);p->journal_needs_repair=1;error=mrl_knowledge_delta_replay(&p->store,p->durable_journal,fp);if(error)goto fail;}
 if(p->store->count>(size_t)t->capacity){error="fact_limit";goto fail;}
 p->durable_version=p->store->version;p->durable_rows=(uint32_t)p->store->next_id;p->durable_symbols=p->store->symbols->next;
 mrl_horn_plan_release(*slot);*slot=p;return (MrlHornLoadResult){true,(int32_t)p->store->count,NULL};
 fail:mrl_horn_plan_release(p);return (MrlHornLoadResult){false,0,error};
}
static MrlHornSnapshot*mrl_horn_plan_explain(MrlHornPlan*p,const char*s,const char*q,const char*o){
 bool ok=mrl_horn_v7_sync(p,p->template->capacity,UINT64_C(1000000000));MrlHornSnapshot*snap=mrl_horn_v7_snapshot(p,ok);if(!ok)return snap;
 uint32_t a=mrl_knowledge_store_find_symbol(p->store,s),b=mrl_knowledge_store_find_symbol(p->store,q),c=mrl_knowledge_store_find_symbol(p->store,o);int32_t target=a&&b&&c?mke_lookup(&p->engine,a,b,c):-1;
 if(target<0||!p->engine.facts[target].live){snap->complete=false;snap->reason="target_missing";return snap;}
 /* Iterative DFS keeps premises before conclusions, including shared DAG parents. */
 size_t bytes=p->engine.count;unsigned char*seen=ks_alloc(p->store->memory,bytes);typedef struct{int32_t row,next;}Frame;
 size_t allocated=16,length=1;Frame*stack=ks_alloc(p->store->memory,allocated*sizeof(*stack));
 if(!seen||!stack){ks_free(seen);ks_free(stack);mrl_horn_snapshot_release(snap);mrl_horn_v7_fail("memory_budget");}
 stack[0]=(Frame){target,0};seen[target]=1;
 while(length){Frame*top=stack+length-1;MrlKnowledgeDerivedFact*f=p->engine.facts+top->row;
  if(top->next<f->parent_count){int32_t at=f->parents[top->next++];if(seen[at]==2)continue;if(seen[at]==1)mrl_horn_v7_fail("cyclic selected proof");
   if(length==allocated){allocated*=2;Frame*next=ks_resize_memory(p->store->memory,stack,allocated*sizeof(*stack));if(!next)mrl_horn_v7_fail("memory_budget");stack=next;}
   seen[at]=1;stack[length++]=(Frame){at,0};
  }else{mrl_horn_v7_capture(snap,&p->engine,f,0);seen[top->row]=2;length--;}
 }
 ks_free(seen);ks_free(stack);return snap;
}

#endif
