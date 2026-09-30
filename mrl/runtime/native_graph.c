#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif
enum { OK=0, GRAPH_LIMIT=1, CLOSURE=1, PROVENANCE=2, UNSAFE=3, UNSUPPORTED=4,
       MALFORMED=5, NATIVE_CAPACITY=6 };
enum { MAX_FACTS=64, MAX_GROWING_FACTS=16384, MAX_RULES=32, MAX_PROOFS=128, MAGIC=0x4d524c32 };
typedef struct { int32_t s,p,o,polarity,actual; } Input;
typedef struct { int32_t body[3],head[3]; } Rule;
typedef struct { int32_t s,p,o,rule,parent,evidence; } Fact;
typedef struct { int32_t asserted,rule,asserted_input,parent_fact,parent_bundle,bind[3]; } Proof;
typedef struct {
 uint32_t tag,version; uintptr_t owner; int32_t op,input_count,rule_count,limit,proof_limit,search_limit,capacity;
 Rule rules[MAX_RULES]; Input input[];
} GraphState;
typedef struct { const uint8_t *bytes; size_t size,pos; } Reader;
typedef struct { uint8_t *bytes; size_t capacity,pos; int failed; } Writer;
typedef struct { Reader reader; Writer writer; } Context;
typedef struct { int32_t key,head,tail,count; } Bucket;
#ifdef _WIN32
#define MRL_GRAPH_API __declspec(dllexport)
#else
#define MRL_GRAPH_API __attribute__((visibility("default")))
#endif
#define STATE_BYTES(capacity) (offsetof(GraphState,input)+(size_t)(capacity)*sizeof(Input))
enum { MAX_INPUT=4*(7+MAX_FACTS*5+MAX_RULES*6), MAX_OUTPUT=4*(5+MAX_FACTS*(7+MAX_PROOFS*8)) };
enum { STATE_TAG=0x4d475234u, STATE_VERSION=2 };
static const char graph_owner_token=0;

static int bind(int32_t term,int32_t value,int32_t *slots) {
    int32_t index; if(term>=0) return term==value; index=-term-1; if(index>2) return 0;
    if(slots[index]>=0) return slots[index]==value; slots[index]=value; return 1;
}
#ifdef MRL_GRAPH_PLAN_HEADER
#include MRL_GRAPH_PLAN_HEADER
#endif
#ifndef MRL_GRAPH_MATCH
#define MRL_GRAPH_MATCH(rule_index, rule_pointer, fact_pointer, binding_slots) \
 (bind((rule_pointer)->body[0],(fact_pointer)->s,(binding_slots)) && \
  bind((rule_pointer)->body[1],(fact_pointer)->p,(binding_slots)) && \
  bind((rule_pointer)->body[2],(fact_pointer)->o,(binding_slots)))
#endif
#ifndef MRL_GRAPH_PLAN_ACCEPTS
#define MRL_GRAPH_PLAN_ACCEPTS(rules, rule_count) 1
#endif

static int read_buffer(Reader *reader,int32_t *value) {
    const uint8_t *b; uint32_t word;
    if(reader->size-reader->pos<4) return 0;
    b=reader->bytes+reader->pos; reader->pos+=4;
    word=(uint32_t)b[0]|((uint32_t)b[1]<<8)|((uint32_t)b[2]<<16)|((uint32_t)b[3]<<24);
    *value=(int32_t)(word&INT32_MAX);
    if(word&0x80000000u){*value-=INT32_MAX;*value-=1;}
    return 1;
}
static void write_buffer(Writer *writer,int32_t value) {
    uint32_t word=(uint32_t)value; unsigned char b[4];
    if(writer->failed) return;
    if(writer->capacity-writer->pos<4){writer->failed=1;return;}
    b[0]=(unsigned char)word;
    b[1]=(unsigned char)(word>>8);
    b[2]=(unsigned char)(word>>16);
    b[3]=(unsigned char)(word>>24);
    for(int i=0;i<4;i++) writer->bytes[writer->pos++]=b[i];
}
static int same(const Fact *fact,int32_t s,int32_t p,int32_t o) { return fact->s==s&&fact->p==p&&fact->o==o; }
static int32_t value_of(int32_t term,const int32_t *slots) { return term>=0?term:slots[-term-1]; }
static void write_status(Writer *writer,int32_t value) { write_buffer(writer,value); }
#define read_word(value) read_buffer(&ctx->reader,(value))
#define write_word(value) write_buffer(&ctx->writer,(value))
#define status(value) write_status(&ctx->writer,(value))
static int parse_state(const uint8_t *input,size_t input_bytes,GraphState *state,int32_t capacity) {
 Reader reader={input,input_bytes,0}; int32_t magic,i,j,k;
 if(!input || input_bytes>4u*(7u+(size_t)capacity*5u+(size_t)MAX_RULES*6u)||!read_buffer(&reader,&magic)||!read_buffer(&reader,&state->op)||
    !read_buffer(&reader,&state->input_count)||!read_buffer(&reader,&state->rule_count)||
    !read_buffer(&reader,&state->limit)||!read_buffer(&reader,&state->proof_limit)||!read_buffer(&reader,&state->search_limit)) return MALFORMED;
 if(magic!=MAGIC||state->op<CLOSURE||state->op>PROVENANCE||state->input_count<0||state->rule_count<0||state->limit<1||state->proof_limit<1||state->search_limit<1) return MALFORMED;
 if(state->input_count>capacity||state->rule_count>MAX_RULES) return NATIVE_CAPACITY;
 for(i=0;i<state->input_count;i++) if(!read_buffer(&reader,&state->input[i].s)||!read_buffer(&reader,&state->input[i].p)||!read_buffer(&reader,&state->input[i].o)||!read_buffer(&reader,&state->input[i].polarity)||!read_buffer(&reader,&state->input[i].actual)||state->input[i].s<0||state->input[i].p<0||state->input[i].o<0||state->input[i].polarity<0||state->input[i].polarity>1||state->input[i].actual<0||state->input[i].actual>1) return MALFORMED;
 for(i=0;i<state->rule_count;i++) for(j=0;j<3;j++) if(!read_buffer(&reader,&state->rules[i].body[j])||state->rules[i].body[j]<-3) return MALFORMED;
 for(i=0;i<state->rule_count;i++) for(j=0;j<3;j++) if(!read_buffer(&reader,&state->rules[i].head[j])||state->rules[i].head[j]<-3) return MALFORMED;
 if(reader.pos!=reader.size) return MALFORMED;
 for(i=0;i<state->rule_count;i++) for(j=0;j<3;j++) if(state->rules[i].head[j]<0){int seen=0;for(k=0;k<3;k++)if(state->rules[i].head[j]==state->rules[i].body[k])seen=1;if(!seen)return UNSAFE;}
 if(!MRL_GRAPH_PLAN_ACCEPTS(state->rules,state->rule_count)) return UNSUPPORTED;
 state->tag=STATE_TAG; state->version=STATE_VERSION; state->owner=(uintptr_t)&graph_owner_token; state->capacity=capacity; return OK;
}
static uint32_t fact_hash(int32_t s,int32_t p,int32_t o) { uint32_t h=(uint32_t)s*0x9e3779b1u^(uint32_t)p*0x85ebca6bu^(uint32_t)o*0xc2b2ae35u; return h^(h>>16); }
static int fact_find(const int32_t *table,size_t mask,const Fact *facts,int32_t s,int32_t p,int32_t o) { uint32_t at=fact_hash(s,p,o)&(uint32_t)mask; for(size_t i=0;i<=mask;i++,at=(at+1)&(uint32_t)mask){int32_t n=table[at];if(!n)return -1;if(same(&facts[n-1],s,p,o))return n-1;}return -1; }
static void fact_put(int32_t *table,size_t mask,const Fact *facts,int32_t index) { uint32_t at=fact_hash(facts[index].s,facts[index].p,facts[index].o)&(uint32_t)mask; while(table[at])at=(at+1)&(uint32_t)mask; table[at]=index+1; }
static int blocked(const int32_t *table,size_t mask,const Input *input,int32_t s,int32_t p,int32_t o) { uint32_t at=fact_hash(s,p,o)&(uint32_t)mask; for(size_t i=0;i<=mask;i++,at=(at+1)&(uint32_t)mask){int32_t n=table[at];if(!n)return 0;const Input *row=&input[n-1];if(row->s==s&&row->p==p&&row->o==o)return 1;}return 0; }
static void blocked_put(int32_t *table,size_t mask,const Input *input,int32_t index) { uint32_t at=fact_hash(input[index].s,input[index].p,input[index].o)&(uint32_t)mask; while(table[at]) {const Input *row=&input[table[at]-1];if(row->s==input[index].s&&row->p==input[index].p&&row->o==input[index].o)return;at=(at+1)&(uint32_t)mask;}table[at]=index+1; }
static Bucket *bucket_find(Bucket *table,size_t mask,int32_t key) { uint32_t at=(uint32_t)key*0x9e3779b1u&(uint32_t)mask; for(size_t i=0;i<=mask;i++,at=(at+1)&(uint32_t)mask){Bucket *row=&table[at];if(row->head==-2)return 0;if(row->key==key)return row;}return 0; }
static Bucket *bucket_get(Bucket *table,size_t mask,int32_t key) { uint32_t at=(uint32_t)key*0x9e3779b1u&(uint32_t)mask; for(;;at=(at+1)&(uint32_t)mask){Bucket *row=&table[at];if(row->head==-2){row->key=key;row->head=row->tail=-1;row->count=0;return row;}if(row->key==key)return row;} }
static Proof *proof_at(Proof *proofs,int32_t proof_capacity,int32_t fact,int32_t proof) { return proofs+(size_t)fact*(size_t)proof_capacity+proof; }
static int run_graph(const GraphState *state,Context *ctx){
 int32_t op,n,nr,limit,plimit,slimit,capacity,i,j,k,nf=0,search=0,complete=1,reason=0,changed=1,proof_capacity;
 size_t hash_capacity=1,mask; Input *in=(Input *)state->input; Rule *r=(Rule *)state->rules;
 Fact *f=0; Proof *p=0; int32_t *pc=0,*table=0,*denials=0,*next=0; Bucket *buckets=0;
 op=state->op;n=state->input_count;nr=state->rule_count;limit=state->limit;plimit=state->proof_limit;slimit=state->search_limit;capacity=state->capacity;proof_capacity=plimit<MAX_PROOFS?plimit:MAX_PROOFS;
 while(hash_capacity<(size_t)capacity*2u)hash_capacity<<=1;mask=hash_capacity-1;
 f=(Fact *)calloc((size_t)capacity,sizeof(*f));table=(int32_t *)calloc(hash_capacity,sizeof(*table));denials=(int32_t *)calloc(hash_capacity,sizeof(*denials));next=(int32_t *)malloc((size_t)capacity*3u*sizeof(*next));buckets=(Bucket *)malloc(hash_capacity*3u*sizeof(*buckets));
 if(op==PROVENANCE)pc=(int32_t *)calloc((size_t)capacity,sizeof(*pc));
 if(!f||!table||!denials||!next||!buckets||(op==PROVENANCE&&!pc)){status(NATIVE_CAPACITY);goto done;}
 for(i=0;i<n;i++)if(in[i].actual&&!in[i].polarity)blocked_put(denials,mask,in,i);
 for(i=0;i<n;i++) if(in[i].actual&&in[i].polarity&&!blocked(denials,mask,in,in[i].s,in[i].p,in[i].o)){
   j=fact_find(table,mask,f,in[i].s,in[i].p,in[i].o);
   if(j<0){if(nf>=capacity){status(NATIVE_CAPACITY);goto done;} if(nf>=limit&&op==CLOSURE){status(GRAPH_LIMIT);goto done;} j=nf;f[nf]=(Fact){in[i].s,in[i].p,in[i].o,-1,-1,i};fact_put(table,mask,f,nf);nf++;}
   if(op==CLOSURE) f[j].evidence=i;
   if(op==PROVENANCE){if(pc[j]>=MAX_PROOFS){status(NATIVE_CAPACITY);goto done;}pc[j]++;}
 }
 if(op==PROVENANCE){for(i=0;i<nf;i++)if(pc[i]>proof_capacity)proof_capacity=pc[i];/* ponytail: duplicate supports can require the 128-proof native ceiling. */
  p=(Proof *)calloc((size_t)capacity*(size_t)proof_capacity,sizeof(*p));if(!p){status(NATIVE_CAPACITY);goto done;}memset(pc,0,(size_t)capacity*sizeof(*pc));
  for(i=0;i<n;i++)if(in[i].actual&&in[i].polarity&&!blocked(denials,mask,in,in[i].s,in[i].p,in[i].o)){j=fact_find(table,mask,f,in[i].s,in[i].p,in[i].o);*proof_at(p,proof_capacity,j,pc[j]++)=(Proof){1,-1,i,-1,-1,{-1,-1,-1}};}
 }
 if(op==PROVENANCE&&nf>limit){complete=0;reason=1;}
 while(complete){int32_t snap=nf,before_proofs=0,after_proofs=0;
  for(size_t at=0;at<hash_capacity*3u;at++)buckets[at].head=-2;
  for(i=0;i<snap;i++)for(k=0;k<3;k++){int32_t key=k==0?f[i].s:k==1?f[i].p:f[i].o;Bucket *bucket=bucket_get(buckets+(size_t)k*hash_capacity,mask,key);next[(size_t)k*(size_t)capacity+i]=-1;if(bucket->tail>=0)next[(size_t)k*(size_t)capacity+bucket->tail]=i;else bucket->head=i;bucket->tail=i;bucket->count++;}
  if(op==PROVENANCE)for(i=0;i<nf;i++)before_proofs+=pc[i];changed=0;
  for(i=0;i<nr&&complete;i++){int32_t chosen=-1,best=INT32_MAX,success=0,candidate;Bucket *selected=0;
   for(k=0;k<3;k++)if(r[i].body[k]>=0){Bucket *bucket=bucket_find(buckets+(size_t)k*hash_capacity,mask,r[i].body[k]);int32_t count=bucket?bucket->count:0;if(count<best){best=count;chosen=k;selected=bucket;}}
   for(candidate=chosen<0?0:(selected?selected->head:-1);candidate>=0&&candidate<snap&&complete;candidate=chosen<0?candidate+1:next[(size_t)chosen*(size_t)capacity+candidate]){int32_t x[3]={-1,-1,-1},s,q,o,t,old,parent_count,b;
    if(candidate>=snap)continue;if(op==PROVENANCE){search++;if(search>slimit){complete=0;reason=2;break;}}if(!MRL_GRAPH_MATCH(i,&r[i],&f[candidate],x))continue;
    success++;if(op==CLOSURE&&success>(int64_t)limit*4){status(GRAPH_LIMIT);goto done;}
    s=value_of(r[i].head[0],x);q=value_of(r[i].head[1],x);o=value_of(r[i].head[2],x);if(s<0||q<0||o<0){status(UNSAFE);goto done;}if(blocked(denials,mask,in,s,q,o))continue;
    t=fact_find(table,mask,f,s,q,o);
    if(t<0){if(nf>=limit){if(op==CLOSURE){status(GRAPH_LIMIT);goto done;}complete=0;reason=2;break;}if(nf>=capacity){status(NATIVE_CAPACITY);goto done;}t=nf;f[nf]=(Fact){s,q,o,i,candidate,-1};fact_put(table,mask,f,nf);nf++;changed=1;}
    if(op==CLOSURE)continue;old=pc[t];parent_count=pc[candidate]<plimit?pc[candidate]:plimit;
    for(k=0;k<parent_count;k++){int exists=0;for(b=0;b<pc[t];b++){Proof *row=proof_at(p,proof_capacity,t,b);if(!row->asserted&&row->rule==i&&row->parent_fact==candidate&&row->parent_bundle==k&&row->bind[0]==x[0]&&row->bind[1]==x[1]&&row->bind[2]==x[2])exists=1;}if(!exists){if(pc[t]>=plimit){complete=0;reason=2;break;}if(pc[t]>=MAX_PROOFS){status(NATIVE_CAPACITY);goto done;}*proof_at(p,proof_capacity,t,pc[t]++)=(Proof){0,i,-1,candidate,k,{x[0],x[1],x[2]}};}}
    if(pc[t]>old)changed=1;
   }
  }
  if(op==PROVENANCE)for(i=0;i<nf;i++)after_proofs+=pc[i];if(nf==snap&&after_proofs==before_proofs)break;
 }
 status(OK);write_word(complete);write_word(reason);write_word(search);write_word(nf);
 for(i=0;i<nf;i++) {
   write_word(f[i].s);write_word(f[i].p);write_word(f[i].o);
   write_word(f[i].rule);write_word(f[i].parent);write_word(f[i].evidence);
   write_word(op==PROVENANCE?pc[i]:0);
   for(j=0;op==PROVENANCE&&j<pc[i];j++) {
      Proof *row=proof_at(p,proof_capacity,i,j);
      write_word(row->asserted);write_word(row->rule);write_word(row->asserted_input);
      write_word(row->parent_fact);write_word(row->parent_bundle);
      write_word(row->bind[0]);write_word(row->bind[1]);write_word(row->bind[2]);
   }
 }
done:
 free(p);free(pc);free(buckets);free(next);free(denials);free(table);free(f);
 return ctx->writer.failed?1:0;
}
#undef status
#undef write_word
#undef read_word

MRL_GRAPH_API int mrl_native_graph_run(const uint8_t *input,size_t input_bytes,
                                       uint8_t *output,size_t output_capacity,size_t *written) {
 union { uintptr_t align; uint8_t bytes[STATE_BYTES(MAX_FACTS)]; } storage; Context ctx; GraphState *state=(GraphState *)(void *)storage.bytes; int code;
 if(written) *written=0;
 if(!output||!written||(!input&&input_bytes)) return 2;
 memset(&storage,0,sizeof(storage));
 ctx.writer.bytes=output;ctx.writer.capacity=output_capacity;ctx.writer.pos=0;ctx.writer.failed=0;
 code=parse_state(input,input_bytes,state,MAX_FACTS);
 if(code!=OK) write_status(&ctx.writer,code); else if(run_graph(state,&ctx)) return 1;
 if(ctx.writer.failed) return 1;
 *written=ctx.writer.pos;
 return 0;
}

MRL_GRAPH_API size_t mrl_graph_state_size(void) { return STATE_BYTES(MAX_FACTS); }
MRL_GRAPH_API size_t mrl_graph_state_size_for(size_t capacity) { return capacity<MAX_FACTS||capacity>MAX_GROWING_FACTS?0:STATE_BYTES(capacity); }

MRL_GRAPH_API int mrl_graph_prepare(const uint8_t *input,size_t input_bytes,void *state,size_t state_bytes) {
 int32_t capacity;
 if(!state||state_bytes<STATE_BYTES(MAX_FACTS)||state_bytes>STATE_BYTES(MAX_GROWING_FACTS)||((state_bytes-offsetof(GraphState,input))%sizeof(Input))||(!input&&input_bytes)) return MALFORMED;
 capacity=(int32_t)((state_bytes-offsetof(GraphState,input))/sizeof(Input));memset(state,0,state_bytes);return parse_state(input,input_bytes,(GraphState *)state,capacity);
}

MRL_GRAPH_API int mrl_graph_evaluate(const void *state,size_t state_bytes,uint8_t *out,size_t cap,size_t *written) {
 const GraphState *graph=(const GraphState *)state; Context ctx;
 if(written) *written=0;
 if(!out||!written||!state||state_bytes<STATE_BYTES(MAX_FACTS)||graph->tag!=STATE_TAG||graph->version!=STATE_VERSION||graph->owner!=(uintptr_t)&graph_owner_token||graph->op<CLOSURE||graph->op>PROVENANCE||graph->input_count<0||graph->rule_count<0||graph->rule_count>MAX_RULES||graph->limit<1||graph->proof_limit<1||graph->search_limit<1||graph->capacity<MAX_FACTS||graph->capacity>MAX_GROWING_FACTS||state_bytes<STATE_BYTES(graph->capacity)||graph->input_count>graph->capacity) return 2;
 ctx.writer.bytes=out;ctx.writer.capacity=cap;ctx.writer.pos=0;ctx.writer.failed=0;
 if(run_graph(graph,&ctx)||ctx.writer.failed) return 1;
 *written=ctx.writer.pos;
 return 0;
}

MRL_GRAPH_API int mrl_graph_append(void *state,size_t state_bytes,const uint8_t *delta,size_t delta_bytes) {
 GraphState *graph=(GraphState *)state; Reader reader; int32_t count,i;
 if(!state||!delta||state_bytes<STATE_BYTES(MAX_FACTS)||graph->tag!=STATE_TAG||graph->version!=STATE_VERSION||graph->owner!=(uintptr_t)&graph_owner_token||graph->op<CLOSURE||graph->op>PROVENANCE||graph->input_count<0||graph->rule_count<0||graph->rule_count>MAX_RULES||graph->limit<1||graph->proof_limit<1||graph->search_limit<1||graph->capacity<MAX_FACTS||graph->capacity>MAX_GROWING_FACTS||state_bytes<STATE_BYTES(graph->capacity)||graph->input_count>graph->capacity) return MALFORMED;
 reader=(Reader){delta,delta_bytes,0};
 if(!read_buffer(&reader,&count)||count<0) return MALFORMED;
 if(count>graph->capacity-graph->input_count) return NATIVE_CAPACITY;
 for(i=0;i<count;i++){Input row;if(!read_buffer(&reader,&row.s)||!read_buffer(&reader,&row.p)||!read_buffer(&reader,&row.o)||!read_buffer(&reader,&row.polarity)||!read_buffer(&reader,&row.actual)||row.s<0||row.p<0||row.o<0||row.polarity<0||row.polarity>1||row.actual<0||row.actual>1)return MALFORMED;}
 if(reader.pos!=reader.size) return MALFORMED;
 reader=(Reader){delta,delta_bytes,0};read_buffer(&reader,&count);
 for(i=0;i<count;i++){read_buffer(&reader,&graph->input[graph->input_count+i].s);read_buffer(&reader,&graph->input[graph->input_count+i].p);read_buffer(&reader,&graph->input[graph->input_count+i].o);read_buffer(&reader,&graph->input[graph->input_count+i].polarity);read_buffer(&reader,&graph->input[graph->input_count+i].actual);}
 graph->input_count+=count;
 return OK;
}

#ifndef MRL_GRAPH_SHARED
int main(void) {
 uint8_t input[MAX_INPUT+1],output[MAX_OUTPUT]; size_t input_bytes,written=0;
 int extra,code;
#ifdef _WIN32
 _setmode(_fileno(stdin), _O_BINARY); _setmode(_fileno(stdout), _O_BINARY);
#endif
 input_bytes=fread(input,1,sizeof(input),stdin);
 if(input_bytes==sizeof(input) && (extra=fgetc(stdin))!=EOF) input_bytes=0;
 code=mrl_native_graph_run(input,input_bytes,output,sizeof(output),&written);
 if(code!=0) return 1;
 return fwrite(output,1,written,stdout)==written?0:1;
}
#endif
