#ifndef MRL_HORN_RUNTIME_H
#define MRL_HORN_RUNTIME_H
/* v6 owns fact text. Copies share immutable storage until a mutator detaches it. */
typedef struct { const char *id,*s,*p,*o,*modality; int polarity; MrlHornEvidence evidence; } MrlHornPlanFact;
typedef struct { MrlHornRule meta; const char *body[3],*head[3]; } MrlHornPlanRule;
typedef struct { const MrlHornPlanFact *facts; int32_t fact_count; const MrlHornPlanRule *rules; int32_t rule_count,capacity; } MrlHornPlanTemplate;
typedef struct { uint32_t refs; MrlHornIncremental value; } MrlHornSharedIncremental;
struct MrlHornPlan { MrlHornSharedIncremental *incremental; uint32_t refs; const MrlHornPlanTemplate *template; MrlHornPlanFact *facts; int32_t fact_count,capacity,version; };
struct MrlHornSnapshot { uint32_t refs; MrlHornPlan *plan; MrlHornResult result; int32_t version; };
typedef struct { bool ok; int32_t value; const char *error; } MrlHornLoadResult;
static void *mrl_horn_alloc(size_t n,size_t size){void *p=calloc(n?n:1,size);if(!p)mrl_runtime_fail("MRL horn allocation");return p;}
static char *mrl_horn_text_copy(const char *s){size_t n=strlen(s)+1;char *p=mrl_horn_alloc(n,1);memcpy(p,s,n);return p;}
static MrlHornPlanFact mrl_horn_fact_copy(MrlHornPlanFact f){f.id=mrl_horn_text_copy(f.id);f.s=mrl_horn_text_copy(f.s);f.p=mrl_horn_text_copy(f.p);f.o=mrl_horn_text_copy(f.o);f.modality=mrl_horn_text_copy(f.modality);if(f.evidence.present){f.evidence.source=mrl_horn_text_copy(f.evidence.source);f.evidence.text=mrl_horn_text_copy(f.evidence.text);}return f;}
static void mrl_horn_fact_free(MrlHornPlanFact *f){free((void*)f->id);free((void*)f->s);free((void*)f->p);free((void*)f->o);free((void*)f->modality);if(f->evidence.present){free((void*)f->evidence.source);free((void*)f->evidence.text);}memset(f,0,sizeof(*f));}
static MrlHornPlan *mrl_horn_plan_new(const MrlHornPlanTemplate *t){if(!t||t->capacity<64||t->capacity>16384||t->fact_count>t->capacity)mrl_runtime_fail("native_capacity");MrlHornPlan*p=mrl_horn_alloc(1,sizeof(*p));p->refs=1;p->incremental=mrl_horn_alloc(1,sizeof(*p->incremental));p->incremental->refs=1;p->template=t;p->capacity=t->capacity;p->fact_count=t->fact_count;p->facts=mrl_horn_alloc(p->capacity,sizeof(*p->facts));for(int32_t i=0;i<p->fact_count;i++)p->facts[i]=mrl_horn_fact_copy(t->facts[i]);return p;}
static MrlHornPlan *mrl_horn_plan_retain(MrlHornPlan*p){if(!p||p->refs==UINT32_MAX)mrl_runtime_fail("MRL horn reference overflow");p->refs++;return p;}
static MrlHornPlan *mrl_horn_plan_copy(MrlHornPlan*p){return mrl_horn_plan_retain(p);}
static void mrl_horn_plan_release(MrlHornPlan*p){if(p&&!--p->refs){for(int32_t i=0;i<p->fact_count;i++)mrl_horn_fact_free(&p->facts[i]);free(p->facts);if(!--p->incremental->refs){mrl_horn_incremental_free(&p->incremental->value);free(p->incremental);}free(p);}}
static void mrl_horn_plan_detach(MrlHornPlan**slot){MrlHornPlan*p=*slot;if(p->refs==1)return;MrlHornPlan*q=mrl_horn_alloc(1,sizeof(*q));*q=*p;q->refs=1;if(q->incremental->refs==UINT32_MAX)mrl_runtime_fail("MRL horn cache reference overflow");q->incremental->refs++;q->facts=mrl_horn_alloc(p->capacity,sizeof(*q->facts));for(int32_t i=0;i<p->fact_count;i++)q->facts[i]=mrl_horn_fact_copy(p->facts[i]);mrl_horn_plan_release(p);*slot=q;}
static int32_t mrl_horn_plan_version(const MrlHornPlan*p){return p->version;}
static bool mrl_horn_valid_text(const char*s){return s&&*s;}
static bool mrl_horn_valid_modality(const char*s){return s&&(!strcmp(s,"asserted")||!strcmp(s,"planned")||!strcmp(s,"conditional"));}
static bool mrl_horn_plan_add(MrlHornPlan**slot,const char*id,const char*s,const char*q,const char*o,bool polarity,const char*modality,MrlHornEvidence evidence){MrlHornPlan*p=*slot;if(!mrl_horn_valid_text(id)||!mrl_horn_valid_text(s)||!mrl_horn_valid_text(q)||!mrl_horn_valid_text(o)||!mrl_horn_valid_modality(modality))mrl_runtime_fail("invalid horn fact");for(int32_t i=0;i<p->fact_count;i++)if(!strcmp(p->facts[i].id,id))return false;if(p->fact_count>=p->capacity)mrl_runtime_fail("native_capacity");if(p->version==INT32_MAX)mrl_runtime_fail("MRL horn version overflow");MrlHornPlanFact f=mrl_horn_fact_copy((MrlHornPlanFact){id,s,q,o,modality,polarity,evidence});mrl_horn_plan_detach(slot);p=*slot;p->facts[p->fact_count++]=f;p->version++;return true;}
static bool mrl_horn_plan_remove(MrlHornPlan**slot,const char*id){MrlHornPlan*p=*slot;if(!mrl_horn_valid_text(id))mrl_runtime_fail("invalid horn fact");for(int32_t i=0;i<p->fact_count;i++)if(!strcmp(p->facts[i].id,id)){if(p->version==INT32_MAX)mrl_runtime_fail("MRL horn version overflow");mrl_horn_plan_detach(slot);p=*slot;mrl_horn_fact_free(&p->facts[i]);memmove(p->facts+i,p->facts+i+1,(size_t)(p->fact_count-i-1)*sizeof(*p->facts));p->fact_count--;memset(p->facts+p->fact_count,0,sizeof(*p->facts));p->version++;return true;}return false;}
static MrlHornLoadResult mrl_horn_plan_load(MrlHornPlan**slot,const char*path){MrlHornPlan*p=*slot;MrlHornJsonBatch b=mrl_horn_jsonl_load(path,32u*1024u*1024u,p->capacity-p->fact_count);if(b.error)return(MrlHornLoadResult){false,0,b.error};for(int32_t i=0;i<b.count;i++)for(int32_t j=0;j<p->fact_count;j++)if(!strcmp(b.facts[i].id,p->facts[j].id)){mrl_horn_jsonl_free(&b);return(MrlHornLoadResult){false,0,"duplicate horn fact id"};}if(!b.count){mrl_horn_jsonl_free(&b);return(MrlHornLoadResult){true,0,0};}if(p->version==INT32_MAX){mrl_horn_jsonl_free(&b);return(MrlHornLoadResult){false,0,"MRL horn version overflow"};}mrl_horn_plan_detach(slot);p=*slot;int32_t count=b.count;for(int32_t i=0;i<count;i++){MrlHornJsonFact*f=&b.facts[i];p->facts[p->fact_count++]=(MrlHornPlanFact){f->id,f->subject,f->predicate,f->object,f->modality,f->polarity,{f->evidence.source!=0,f->evidence.source,f->evidence.text,f->evidence.start,f->evidence.end}};memset(f,0,sizeof(*f));}p->version++;mrl_horn_jsonl_free(&b);return(MrlHornLoadResult){true,count,0};}
/* Intern rules first so append-only inputs keep old symbol IDs stable. */
typedef struct { const char **items; int32_t *table,count; size_t mask; } MrlHornSymbols;
static uint32_t mrl_horn_string_hash(const char*s){uint32_t h=2166136261u;for(;*s;s++){h^=(unsigned char)*s;h*=16777619u;}return h;}
static int32_t mrl_horn_symbol(MrlHornSymbols*t,const char*s){size_t at=mrl_horn_string_hash(s)&t->mask;while(t->table[at]){int32_t i=t->table[at]-1;if(!strcmp(t->items[i],s))return i;at=(at+1)&t->mask;}int32_t i=t->count++;t->items[i]=s;t->table[at]=i+1;return i;}
static int32_t mrl_horn_term(MrlHornSymbols*t,const MrlHornPlanRule*r,const char*s){if(s[0]!='?')return mrl_horn_symbol(t,s);for(int32_t i=0;i<r->meta.count;i++)if(!strcmp(s,r->meta.vars[i]))return-i-1;mrl_runtime_fail("unsafe_rule");return 0;}
static void mrl_horn_result_free(MrlHornResult*r){free(r->output);free((void*)r->symbols);free((void*)r->supports);free((void*)r->evidence);free((void*)r->rules);free(r->offsets);memset(r,0,sizeof(*r));}
static MrlHornSnapshot *mrl_horn_evaluate(MrlHornPlan*p,int32_t op,int32_t limit,int32_t proof_limit,int32_t search_limit,int has_target,const char*s,const char*q,const char*o){
 MrlHornSnapshot*snap=mrl_horn_alloc(1,sizeof(*snap));snap->refs=1;snap->plan=mrl_horn_plan_retain(p);snap->version=p->version;MrlHornResult*r=&snap->result;int32_t n=p->fact_count,nr=p->template->rule_count;size_t slots=(size_t)n*3+(size_t)nr*6+3,hash_size=1;while(hash_size<slots*2)hash_size<<=1;
 MrlHornSymbols symbols={mrl_horn_alloc(slots,sizeof(char*)),mrl_horn_alloc(hash_size,sizeof(int32_t)),0,hash_size-1};
 size_t words=7+(size_t)n*5+(size_t)nr*6;uint8_t*packet=mrl_horn_alloc(words,4);int32_t*encoded=mrl_horn_alloc((size_t)nr*6,sizeof(int32_t));
 MrlHornRule*rules=mrl_horn_alloc(nr,sizeof(*rules));const char**supports=mrl_horn_alloc(n,sizeof(*supports));MrlHornEvidence*evidence=mrl_horn_alloc(n,sizeof(*evidence));
 for(int32_t i=0;i<nr;i++){const MrlHornPlanRule*rule=&p->template->rules[i];rules[i]=rule->meta;for(int j=0;j<3;j++){encoded[i*3+j]=mrl_horn_term(&symbols,rule,rule->body[j]);encoded[nr*3+i*3+j]=mrl_horn_term(&symbols,rule,rule->head[j]);}}
 int32_t header[7]={MAGIC,op,n,nr,limit,proof_limit,search_limit};for(int i=0;i<7;i++)mrl_horn_put(packet+i*4,header[i]);
 for(int32_t i=0;i<n;i++){const MrlHornPlanFact*f=&p->facts[i];int32_t row[5]={mrl_horn_symbol(&symbols,f->s),mrl_horn_symbol(&symbols,f->p),mrl_horn_symbol(&symbols,f->o),f->polarity,!strcmp(f->modality,"asserted")};for(int j=0;j<5;j++)mrl_horn_put(packet+(7+(size_t)i*5+j)*4,row[j]);supports[i]=f->id;evidence[i]=f->evidence;}
 for(int32_t i=0;i<nr*6;i++)mrl_horn_put(packet+(7+(size_t)n*5+i)*4,encoded[i]);free(encoded);
 r->symbols=symbols.items;r->supports=supports;r->evidence=evidence;r->rules=rules;r->rule_count=nr;r->operation=op;r->has_target=has_target;
 const char*target[3]={s,q,o};for(int i=0;i<3;i++)r->target[i]=has_target?mrl_horn_symbol(&symbols,target[i]):-1;free(symbols.table);
 size_t state_bytes=mrl_graph_state_size_for(p->capacity);GraphState*state=mrl_horn_alloc(state_bytes,1);r->status=mrl_graph_prepare(packet,words*4,state,state_bytes);free(packet);
 int32_t stride=op==2?(proof_limit<MAX_PROOFS?proof_limit:MAX_PROOFS):0;
 if(op==2){size_t hs=1;while(hs<(size_t)(n?n:1)*2)hs<<=1;int32_t*table=mrl_horn_alloc(hs,sizeof(int32_t)),*counts=mrl_horn_alloc(n,sizeof(int32_t));for(int32_t i=0;i<n;i++){Input*f=&state->input[i];if(!f->polarity||!f->actual)continue;size_t at=fact_hash(f->s,f->p,f->o)&(hs-1);while(table[at]){Input*g=&state->input[table[at]-1];if(f->s==g->s&&f->p==g->p&&f->o==g->o)break;at=(at+1)&(hs-1);}if(!table[at])table[at]=i+1;int32_t count=++counts[table[at]-1];if(count>stride)stride=count;}free(table);free(counts);if(stride>MAX_PROOFS)stride=MAX_PROOFS;}
 r->output_capacity=4*(5+(size_t)p->capacity*(7+(size_t)stride*8));r->output=mrl_horn_alloc(r->output_capacity,1);
 if(!r->status){Context ctx={0};ctx.writer=(Writer){r->output,r->output_capacity,0,0};if(mrl_horn_incremental_eval(&p->incremental->value,state,&ctx))r->written=ctx.writer.pos;else r->status=mrl_graph_evaluate(state,state_bytes,r->output,r->output_capacity,&r->written);}free(state);
 if(!r->status&&r->written>=4){r->status=mrl_horn_get(r,0);if(!r->status&&r->written>=20){r->complete=mrl_horn_get(r,4);r->reason=mrl_horn_get(r,8);r->searches=mrl_horn_get(r,12);r->fact_count=mrl_horn_get(r,16);r->offsets=mrl_horn_alloc(r->fact_count,sizeof(size_t));size_t at=20;for(int32_t i=0;i<r->fact_count;i++){r->offsets[i]=at;int32_t proofs=mrl_horn_get(r,at+24);r->proof_count+=proofs;at+=28+(size_t)proofs*32;}}}
 if(r->written){void*smaller=realloc(r->output,r->written);if(smaller){r->output=smaller;r->output_capacity=r->written;}}r->ran=1;return snap;
}
static MrlHornSnapshot*mrl_horn_snapshot_retain(MrlHornSnapshot*s){if(!s||s->refs==UINT32_MAX)mrl_runtime_fail("MRL horn snapshot reference overflow");s->refs++;return s;}
static void mrl_horn_snapshot_release(MrlHornSnapshot*s){if(s&&!--s->refs){mrl_horn_result_free(&s->result);mrl_horn_plan_release(s->plan);free(s);}}
static int32_t mrl_horn_snapshot_version(const MrlHornSnapshot*s){return s->version;}
static int32_t mrl_horn_snapshot_fact_count(const MrlHornSnapshot*s){return s->result.fact_count;}
static int32_t mrl_horn_snapshot_proof_count(const MrlHornSnapshot*s){return s->result.proof_count;}
static int32_t mrl_horn_snapshot_searches(const MrlHornSnapshot*s){return s->result.searches;}
static bool mrl_horn_snapshot_complete(const MrlHornSnapshot*s){const MrlHornResult*r=&s->result;return !r->status&&r->complete&&(!r->has_target||mrl_horn_target(r)>=0);}
static const char*mrl_horn_snapshot_reason(const MrlHornSnapshot*s){return mrl_horn_reason_name(&s->result);}
static void mrl_horn_snapshot_print(const MrlHornSnapshot*s){mrl_horn_print_result(&s->result);}
#endif
