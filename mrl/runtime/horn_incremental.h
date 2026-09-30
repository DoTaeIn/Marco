#ifndef MRL_HORN_INCREMENTAL_H
#define MRL_HORN_INCREMENTAL_H
/* A narrow exact fast path: positive append-only inputs and nonrecursive
   constant-predicate rules. Output replay preserves native insertion/proof order. */
typedef struct { int matched; int32_t s,p,o; } MrlHornConsequence;
typedef struct {
 Input *prefix; Fact *asserted; MrlHornConsequence *consequences;
 int32_t count,asserted_count,allocated,rule_count; Rule rules[MAX_RULES];
 uint64_t new_matches,reused;
} MrlHornIncremental;
static void mrl_horn_incremental_free(MrlHornIncremental*c){if(c){free(c->prefix);free(c->asserted);free(c->consequences);memset(c,0,sizeof(*c));}}
static int mrl_horn_incremental_ok(const GraphState*g){
 if(g->op!=CLOSURE)return 0;
 for(int32_t i=0;i<g->input_count;i++)if(!g->input[i].actual||!g->input[i].polarity)return 0;
 for(int32_t r=0;r<g->rule_count;r++){
  if(g->rules[r].body[1]<0||g->rules[r].head[1]<0)return 0;
  for(int32_t j=0;j<g->rule_count;j++)if(g->rules[r].head[1]==g->rules[j].body[1])return 0;
 }return 1;
}
static int mrl_horn_incremental_eval(MrlHornIncremental*c,const GraphState*g,Context*ctx){
 int32_t n=g->input_count,nr=g->rule_count;size_t hash_size=1;int32_t*table=NULL;Fact*full=NULL;
 c->new_matches=c->reused=0;
 if(!mrl_horn_incremental_ok(g)){mrl_horn_incremental_free(c);return 0;}
 if(c->count&&(n<c->count||nr!=c->rule_count||memcmp(c->rules,g->rules,(size_t)nr*sizeof(Rule))||memcmp(c->prefix,g->input,(size_t)c->count*sizeof(Input)))){mrl_horn_incremental_free(c);return 0;}
 if(n>c->allocated){
  Input*inputs=realloc(c->prefix,(size_t)n*sizeof(Input));if(!inputs)goto fallback;c->prefix=inputs;
  Fact*facts=realloc(c->asserted,(size_t)n*sizeof(Fact));if(!facts)goto fallback;c->asserted=facts;
  if(nr){MrlHornConsequence*rows=realloc(c->consequences,(size_t)n*(size_t)nr*sizeof(*rows));if(!rows)goto fallback;c->consequences=rows;}
  c->allocated=n;
 }
 c->rule_count=nr;memcpy(c->rules,g->rules,(size_t)nr*sizeof(Rule));
 while(hash_size<(size_t)(n?n:1)*2)hash_size<<=1;
 table=calloc(hash_size,sizeof(*table));if(!table)goto fallback;
 int32_t old_unique=c->asserted_count;
 for(int32_t i=0;i<c->asserted_count;i++)fact_put(table,hash_size-1,c->asserted,i);
 for(int32_t i=c->count;i<n;i++){
  const Input*in=&g->input[i];int32_t at=fact_find(table,hash_size-1,c->asserted,in->s,in->p,in->o);
  if(at<0){at=c->asserted_count++;c->asserted[at]=(Fact){in->s,in->p,in->o,-1,-1,i};fact_put(table,hash_size-1,c->asserted,at);
   for(int32_t r=0;r<nr;r++){
    MrlHornConsequence*out=&c->consequences[(size_t)at*nr+r];int32_t x[3]={-1,-1,-1};c->new_matches++;
    out->matched=bind(g->rules[r].body[0],in->s,x)&&bind(g->rules[r].body[1],in->p,x)&&bind(g->rules[r].body[2],in->o,x);
    if(out->matched){out->s=value_of(g->rules[r].head[0],x);out->p=value_of(g->rules[r].head[1],x);out->o=value_of(g->rules[r].head[2],x);}
   }
  }else c->asserted[at].evidence=i;
 }
 free(table);table=NULL;
 if(c->asserted_count>g->limit)goto fallback;
 size_t work_capacity=(size_t)c->asserted_count*(size_t)(nr+1);if(work_capacity>(size_t)g->capacity)work_capacity=g->capacity;if(!work_capacity)work_capacity=1;
 hash_size=1;while(hash_size<work_capacity*2)hash_size<<=1;
 table=calloc(hash_size,sizeof(*table));full=calloc(work_capacity,sizeof(*full));if(!table||!full)goto fallback;
 int32_t count=c->asserted_count;
 if(count)memcpy(full,c->asserted,(size_t)count*sizeof(*full));
 for(int32_t i=0;i<count;i++)fact_put(table,hash_size-1,full,i);
 for(int32_t r=0;r<nr;r++)for(int32_t i=0;i<c->asserted_count;i++){
  const MrlHornConsequence*row=&c->consequences[(size_t)i*nr+r];if(i<old_unique)c->reused++;
  if(!row->matched||fact_find(table,hash_size-1,full,row->s,row->p,row->o)>=0)continue;
  if(count>=g->limit||count>=g->capacity)goto fallback;
  full[count]=(Fact){row->s,row->p,row->o,r,i,-1};fact_put(table,hash_size-1,full,count++);
 }
 write_status(&ctx->writer,OK);write_buffer(&ctx->writer,1);write_buffer(&ctx->writer,0);write_buffer(&ctx->writer,0);write_buffer(&ctx->writer,count);
 for(int32_t i=0;i<count;i++){const Fact*f=&full[i];write_buffer(&ctx->writer,f->s);write_buffer(&ctx->writer,f->p);write_buffer(&ctx->writer,f->o);write_buffer(&ctx->writer,f->rule);write_buffer(&ctx->writer,f->parent);write_buffer(&ctx->writer,f->evidence);write_buffer(&ctx->writer,0);}
 if(n)memcpy(c->prefix,g->input,(size_t)n*sizeof(Input));c->count=n;free(table);free(full);return !ctx->writer.failed;
fallback:
 free(table);free(full);mrl_horn_incremental_free(c);return 0;
}
#endif
