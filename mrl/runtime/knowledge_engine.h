#ifndef MRL_KNOWLEDGE_ENGINE_H
#define MRL_KNOWLEDGE_ENGINE_H
/* Indexed positive Horn evaluation. Symbols are stable nonnegative IDs;
   -1..-8 are variables. Retraction recomputes affected predicate components.
   ponytail: dead tuple IDs stay stable until engine disposal; the byte budget
   bounds this history. Compact at an explicit version boundary if churn needs it. */
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>

enum { MKE_OK, MKE_WORK, MKE_LIMIT, MKE_MEMORY, MKE_INVALID };
typedef struct { uint64_t id; int32_t s,p,o; int asserted,rule,parent;
 int32_t parents[8],parent_count,next[3],support_head,support_tail;
 uint32_t supports,denials; unsigned live; uint64_t touched; unsigned previous_live;
} MrlKnowledgeDerivedFact;
typedef struct { const int32_t *body; int32_t premises,head[3],id; } MrlKnowledgeRule;
typedef struct { int32_t key,head,tail; size_t count,live_count; unsigned occupied,dirty; } MkeBucket;
typedef struct { uint64_t id; int32_t row,prev,next; unsigned live,denial; } MkeAssertion;
typedef struct {
 MrlKnowledgeDerivedFact *facts; size_t count,cap,live_count;
 MrlKnowledgeRule *rules; size_t rule_count;
 MkeBucket *index[3]; size_t index_cap;
 int32_t *tuples; size_t tuple_cap;
 MkeAssertion *assertions; size_t assertion_count,assertion_cap;
 int32_t *ids; size_t id_cap;
 int32_t *pending,*touched_rows,*dirty_preds,*added,*removed;
 size_t pending_count,pending_cap,touched_count,touched_cap,dirty_count,dirty_cap;
 size_t added_count,added_cap,removed_count,removed_cap;
 uint64_t version,work,candidates,rule_firings,epoch;
 size_t bytes,memory_budget,fact_limit;
 int status,editing,has_deletions,complete;
 void*allocator_context;void*(*resize_memory)(void*,void*,size_t);void(*free_memory)(void*,void*);
} MrlKnowledgeEngine;

static uint64_t mke_hash64(uint64_t x){x^=x>>30;x*=UINT64_C(0xbf58476d1ce4e5b9);x^=x>>27;x*=UINT64_C(0x94d049bb133111eb);return x^(x>>31);}
static uint64_t mke_hash3(int32_t s,int32_t p,int32_t o){return mke_hash64((uint32_t)s)^mke_hash64((uint64_t)(uint32_t)p+UINT64_C(0x12345678))^mke_hash64((uint64_t)(uint32_t)o+UINT64_C(0xabcdef00));}
static int mke_resize(MrlKnowledgeEngine*e,void**p,size_t old,size_t n){
 if(n>old&&(n-old>e->memory_budget-e->bytes)){e->status=MKE_MEMORY;return 0;}
 void*q=e->resize_memory?e->resize_memory(e->allocator_context,*p,n):(n?realloc(*p,n):NULL);if(n&&!q){e->status=MKE_MEMORY;return 0;}
 if(!n&&!e->resize_memory)free(*p);else if(n>old)memset((char*)q+old,0,n-old);
 *p=q;e->bytes=e->bytes-old+n;return 1;
}
static int mke_vec(MrlKnowledgeEngine*e,int32_t**p,size_t*cap,size_t needed){
 if(needed<=*cap)return 1;size_t n=*cap?*cap:64;
 while(n<needed){if(n>SIZE_MAX/2/sizeof(int32_t)){e->status=MKE_MEMORY;return 0;}n*=2;}
 if(!mke_resize(e,(void**)p,*cap*sizeof(int32_t),n*sizeof(int32_t)))return 0;*cap=n;return 1;
}
static MkeBucket*mke_bucket(MkeBucket*table,size_t n,int32_t key){
 size_t h=(size_t)mke_hash64((uint32_t)key)&(n-1);
 while(table[h].occupied&&table[h].key!=key)h=(h+1)&(n-1);return &table[h];
}
static int32_t mke_lookup(const MrlKnowledgeEngine*e,int32_t s,int32_t p,int32_t o){
 if(!e->tuple_cap)return -1;size_t h=(size_t)mke_hash3(s,p,o)&(e->tuple_cap-1);
 while(e->tuples[h]){int32_t i=e->tuples[h]-1;const MrlKnowledgeDerivedFact*f=e->facts+i;
  if(f->s==s&&f->p==p&&f->o==o)return i;h=(h+1)&(e->tuple_cap-1);}
 return -1;
}
static int mke_reindex(MrlKnowledgeEngine*e,size_t n){
 int32_t*t=NULL;MkeBucket*b[3]={0};size_t tb=n*sizeof(*t),bb=n*sizeof(**b);
 if(!mke_resize(e,(void**)&t,0,tb))return 0;
 for(int k=0;k<3;k++)if(!mke_resize(e,(void**)&b[k],0,bb)){
  mke_resize(e,(void**)&t,tb,0);for(int j=0;j<k;j++)mke_resize(e,(void**)&b[j],bb,0);return 0;}
 for(size_t i=0;i<e->count;i++){
  MrlKnowledgeDerivedFact*f=e->facts+i;size_t h=(size_t)mke_hash3(f->s,f->p,f->o)&(n-1);
  while(t[h])h=(h+1)&(n-1);t[h]=(int32_t)i+1;
  int32_t values[3]={f->s,f->p,f->o};
  for(int k=0;k<3;k++){MkeBucket*x=mke_bucket(b[k],n,values[k]);f->next[k]=-1;
   if(!x->occupied){x->occupied=1;x->key=values[k];x->head=x->tail=(int32_t)i;}
   else{e->facts[x->tail].next[k]=(int32_t)i;x->tail=(int32_t)i;}x->count++;if(f->live)x->live_count++;}
 }
 mke_resize(e,(void**)&e->tuples,e->tuple_cap*sizeof(*t),0);
 for(int k=0;k<3;k++)mke_resize(e,(void**)&e->index[k],e->index_cap*sizeof(**b),0);
 e->tuples=t;e->tuple_cap=e->index_cap=n;for(int k=0;k<3;k++)e->index[k]=b[k];return 1;
}
static int mke_id_index(MrlKnowledgeEngine*e,size_t n){
 int32_t*t=NULL;if(!mke_resize(e,(void**)&t,0,n*sizeof(*t)))return 0;
 for(size_t i=0;i<e->assertion_count;i++){size_t h=(size_t)mke_hash64(e->assertions[i].id)&(n-1);while(t[h])h=(h+1)&(n-1);t[h]=(int32_t)i+1;}
 mke_resize(e,(void**)&e->ids,e->id_cap*sizeof(*t),0);e->ids=t;e->id_cap=n;return 1;
}
static int32_t mke_find_id(const MrlKnowledgeEngine*e,uint64_t id){
 if(!e->id_cap)return -1;size_t h=(size_t)mke_hash64(id)&(e->id_cap-1);
 while(e->ids[h]){int32_t i=e->ids[h]-1;if(e->assertions[i].id==id)return i;h=(h+1)&(e->id_cap-1);}return -1;
}
static void mke_begin(MrlKnowledgeEngine*e){if(!e->editing){e->editing=1;e->epoch++;e->touched_count=e->added_count=e->removed_count=0;e->complete=0;}}
static int mke_set_live(MrlKnowledgeEngine*e,int32_t i,unsigned live){
 MrlKnowledgeDerivedFact*f=e->facts+i;if(f->live==live)return 1;
 if(f->touched!=e->epoch){if(!mke_vec(e,&e->touched_rows,&e->touched_cap,e->touched_count+1))return 0;
  f->touched=e->epoch;f->previous_live=f->live;e->touched_rows[e->touched_count++]=i;}
 if(live){if(e->live_count>=e->fact_limit){e->status=MKE_LIMIT;return 0;}
  if(!mke_vec(e,&e->pending,&e->pending_cap,e->pending_count+1))return 0;e->pending[e->pending_count++]=i;e->live_count++;}
 else e->live_count--;
 int32_t values[3]={f->s,f->p,f->o};for(int k=0;k<3;k++){MkeBucket*b=mke_bucket(e->index[k],e->index_cap,values[k]);if(live)b->live_count++;else b->live_count--;}
 f->live=live;return 1;
}
static int32_t mke_row(MrlKnowledgeEngine*e,int32_t s,int32_t p,int32_t o){
 int32_t found=mke_lookup(e,s,p,o);if(found>=0)return found;
 if(s<0||p<0||o<0||e->count>=INT32_MAX){e->status=MKE_INVALID;return -1;}
 if(!e->tuple_cap||e->count+1>e->tuple_cap/2)if(!mke_reindex(e,e->tuple_cap?e->tuple_cap*2:128))return -1;
 if(e->count==e->cap){size_t n=e->cap?e->cap*2:64;if(!mke_resize(e,(void**)&e->facts,e->cap*sizeof(*e->facts),n*sizeof(*e->facts)))return -1;e->cap=n;}
 int32_t i=(int32_t)e->count++;MrlKnowledgeDerivedFact*f=e->facts+i;memset(f,0,sizeof(*f));f->s=s;f->p=p;f->o=o;f->rule=f->parent=f->support_head=f->support_tail=-1;
 size_t h=(size_t)mke_hash3(s,p,o)&(e->tuple_cap-1);while(e->tuples[h])h=(h+1)&(e->tuple_cap-1);e->tuples[h]=i+1;
 int32_t values[3]={s,p,o};for(int k=0;k<3;k++){MkeBucket*b=mke_bucket(e->index[k],e->index_cap,values[k]);f->next[k]=-1;
  if(!b->occupied){b->occupied=1;b->key=values[k];b->head=b->tail=i;}else{e->facts[b->tail].next[k]=i;b->tail=i;}b->count++;}
 return i;
}
static int mrl_knowledge_engine_init_with_allocator(MrlKnowledgeEngine*e,const MrlKnowledgeRule*r,size_t n,uint64_t work,void*context,void*(*resize_fn)(void*,void*,size_t),void(*free_fn)(void*,void*)){
 memset(e,0,sizeof(*e));e->allocator_context=context;e->resize_memory=resize_fn;e->free_memory=free_fn;e->memory_budget=SIZE_MAX;e->fact_limit=INT32_MAX;e->work=work;e->epoch=1;
 if(n>128||!work){e->status=MKE_INVALID;return 0;}
 if(n&&!mke_resize(e,(void**)&e->rules,0,n*sizeof(*r)))return 0;e->rule_count=n;
 for(size_t i=0;i<n;i++){
  if(!r[i].body||r[i].premises<1||r[i].premises>8){e->status=MKE_INVALID;return 0;}
  unsigned bound=0;for(int k=0;k<r[i].premises*3;k++){int32_t t=r[i].body[k];if(t<-8){e->status=MKE_INVALID;return 0;}if(t<0)bound|=1u<<(-t-1);}
  for(int k=0;k<3;k++)if(r[i].head[k]<-8||(r[i].head[k]<0&&!(bound&(1u<<(-r[i].head[k]-1))))){e->status=MKE_INVALID;return 0;}
  int32_t*b=NULL;if(!mke_resize(e,(void**)&b,0,(size_t)r[i].premises*3*sizeof(*b)))return 0;
  memcpy(b,r[i].body,(size_t)r[i].premises*3*sizeof(*b));e->rules[i]=r[i];e->rules[i].body=b;
 }
 return 1;
}
static int mrl_knowledge_engine_init(MrlKnowledgeEngine*e,const MrlKnowledgeRule*r,size_t n,uint64_t work){return mrl_knowledge_engine_init_with_allocator(e,r,n,work,NULL,NULL,NULL);}
static void mke_free_owned(MrlKnowledgeEngine*e,void*p){if(e->free_memory)e->free_memory(e->allocator_context,p);else free(p);}
static int mrl_knowledge_engine_limits(MrlKnowledgeEngine*e,size_t facts,uint64_t work,size_t bytes){
 if(!facts||facts>INT32_MAX||!work||bytes<e->bytes){e->status=MKE_INVALID;return 0;}e->fact_limit=facts;e->work=work;e->memory_budget=bytes;return 1;
}
static void mrl_knowledge_engine_free(MrlKnowledgeEngine*e){
 for(size_t i=0;i<e->rule_count;i++)mke_free_owned(e,(void*)e->rules[i].body);
 mke_free_owned(e,e->rules);mke_free_owned(e,e->facts);mke_free_owned(e,e->tuples);
 for(int k=0;k<3;k++)mke_free_owned(e,e->index[k]);
 mke_free_owned(e,e->assertions);mke_free_owned(e,e->ids);mke_free_owned(e,e->pending);mke_free_owned(e,e->touched_rows);mke_free_owned(e,e->dirty_preds);mke_free_owned(e,e->added);mke_free_owned(e,e->removed);memset(e,0,sizeof(*e));
}
static int mrl_knowledge_has(const MrlKnowledgeEngine*e,int32_t s,int32_t p,int32_t o){int32_t i=mke_lookup(e,s,p,o);return i>=0&&e->facts[i].live;}
static int mke_dirty(MrlKnowledgeEngine*e,int32_t pred);
static int mke_assert_mode(MrlKnowledgeEngine*e,uint64_t id,int32_t s,int32_t p,int32_t o,unsigned denial){
 if(e->status||!id||s<0||p<0||o<0)return 0;int32_t a=mke_find_id(e,id);if(a>=0&&e->assertions[a].live)return 0;
 if(a<0){if(!e->id_cap||e->assertion_count+1>e->id_cap/2)if(!mke_id_index(e,e->id_cap?e->id_cap*2:128))return 0;
  if(e->assertion_count==e->assertion_cap){size_t n=e->assertion_cap?e->assertion_cap*2:64;if(!mke_resize(e,(void**)&e->assertions,e->assertion_cap*sizeof(*e->assertions),n*sizeof(*e->assertions)))return 0;e->assertion_cap=n;}
 }
 int32_t row=mke_row(e,s,p,o);if(row<0)return 0;if(denial&&!mke_dirty(e,p))return 0;mke_begin(e);if(!denial&&!e->facts[row].denials&&!mke_set_live(e,row,1))return 0;
 if(a<0){a=(int32_t)e->assertion_count++;size_t h=(size_t)mke_hash64(id)&(e->id_cap-1);while(e->ids[h])h=(h+1)&(e->id_cap-1);e->ids[h]=a+1;}
 MrlKnowledgeDerivedFact*f=e->facts+row;MkeAssertion*x=e->assertions+a;*x=(MkeAssertion){id,row,denial?-1:f->support_tail,-1,1,denial};
 if(denial){f->denials++;e->has_deletions=1;e->version++;return 1;}
 if(f->support_tail>=0)e->assertions[f->support_tail].next=a;else f->support_head=a;f->support_tail=a;f->supports++;f->asserted=1;f->id=id;f->rule=f->parent=-1;f->parent_count=0;e->version++;return 1;
}
static int mrl_knowledge_assert(MrlKnowledgeEngine*e,uint64_t id,int32_t s,int32_t p,int32_t o){return mke_assert_mode(e,id,s,p,o,0);}
static int mrl_knowledge_deny(MrlKnowledgeEngine*e,uint64_t id,int32_t s,int32_t p,int32_t o){return mke_assert_mode(e,id,s,p,o,1);}
static int mke_dirty(MrlKnowledgeEngine*e,int32_t pred){
 if(!e->index_cap)return 1;MkeBucket*b=mke_bucket(e->index[1],e->index_cap,pred);
 /* A head predicate may not have a fact yet. The queue itself covers it. */
 for(size_t i=0;i<e->dirty_count;i++)if(e->dirty_preds[i]==pred)return 1;
 if(!mke_vec(e,&e->dirty_preds,&e->dirty_cap,e->dirty_count+1))return 0;e->dirty_preds[e->dirty_count++]=pred;if(b->occupied)b->dirty=1;return 1;
}
static int mrl_knowledge_remove(MrlKnowledgeEngine*e,uint64_t id){
 if(e->status)return 0;int32_t a=mke_find_id(e,id);if(a<0||!e->assertions[a].live)return 0;
 MkeAssertion*x=e->assertions+a;MrlKnowledgeDerivedFact*f=e->facts+x->row;
 if(!mke_dirty(e,f->p))return 0;mke_begin(e);e->has_deletions=1;
 if(x->denial){x->live=0;f->denials--;e->version++;return 1;}
 if(x->prev>=0)e->assertions[x->prev].next=x->next;else f->support_head=x->next;
 if(x->next>=0)e->assertions[x->next].prev=x->prev;else f->support_tail=x->prev;
 x->live=0;f->supports--;f->asserted=f->supports!=0;f->id=f->supports?e->assertions[f->support_tail].id:0;e->version++;return 1;
}
static int mrl_knowledge_correct(MrlKnowledgeEngine*e,uint64_t id,int32_t s,int32_t p,int32_t o){
 /* Admission validates/reserves its transaction before applying engine edits. */
 return mrl_knowledge_remove(e,id)&&mrl_knowledge_assert(e,id,s,p,o);
}
static int mke_bind(int32_t term,int32_t value,int32_t*x){if(term>=0)return term==value;int i=-term-1;if(x[i]<0){x[i]=value;return 1;}return x[i]==value;}
static int32_t mke_value(int32_t term,const int32_t*x){return term>=0?term:x[-term-1];}
static int mke_emit(MrlKnowledgeEngine*e,const MrlKnowledgeRule*r,const int32_t*x,const int32_t*parents){
 int32_t s=mke_value(r->head[0],x),p=mke_value(r->head[1],x),o=mke_value(r->head[2],x);int32_t row=mke_row(e,s,p,o);if(row<0)return 0;
 if(e->facts[row].live||e->facts[row].denials)return 1;if(!mke_set_live(e,row,1))return 0;MrlKnowledgeDerivedFact*f=e->facts+row;
 f->asserted=0;f->rule=r->id;f->parent_count=r->premises;f->parent=parents[0];memcpy(f->parents,parents,(size_t)r->premises*sizeof(*parents));e->rule_firings++;return 1;
}
static int mke_join(MrlKnowledgeEngine*e,const MrlKnowledgeRule*r,int depth,const int32_t*x,int32_t*parents,size_t frozen,int pivot,int32_t anchor){
 if(depth==r->premises)return mke_emit(e,r,x,parents);
 const int32_t*t=r->body+depth*3;
 if(depth==pivot){MrlKnowledgeDerivedFact*f=e->facts+anchor;int32_t y[8];memcpy(y,x,sizeof(y));
  if(!f->live||!mke_bind(t[0],f->s,y)||!mke_bind(t[1],f->p,y)||!mke_bind(t[2],f->o,y))return 1;
  parents[depth]=anchor;return mke_join(e,r,depth+1,y,parents,frozen,pivot,anchor);
 }
 size_t best=SIZE_MAX;int position=-1;int32_t at=0;
 for(int k=0;k<3;k++){int32_t value=mke_value(t[k],x);if(value>=0){MkeBucket*b=mke_bucket(e->index[k],e->index_cap,value);if(!b->occupied)return 1;if(b->count<best){best=b->count;position=k;at=b->head;}}}
 while(at>=0&&(size_t)at<frozen){
  /* Emission may realloc the fact vector: retain values/next, never a row pointer. */
  MrlKnowledgeDerivedFact f=e->facts[at];int32_t next=position<0?at+1:f.next[position];
  if(f.live){if(++e->candidates>e->work){e->status=MKE_WORK;return 0;}int32_t y[8];memcpy(y,x,sizeof(y));
   if(mke_bind(t[0],f.s,y)&&mke_bind(t[1],f.p,y)&&mke_bind(t[2],f.o,y)){parents[depth]=at;if(!mke_join(e,r,depth+1,y,parents,frozen,pivot,anchor))return 0;}}
  at=next;
 }
 return 1;
}
static int mke_affected(MrlKnowledgeEngine*e,int32_t p){for(size_t i=0;i<e->dirty_count;i++)if(e->dirty_preds[i]==p)return 1;return 0;}
static int mke_prepare_delete(MrlKnowledgeEngine*e){
 int variable_head=0;for(size_t r=0;r<e->rule_count;r++)if(e->rules[r].head[1]<0)variable_head=1;
 if(variable_head){for(size_t i=0;i<e->index_cap;i++)if(e->index[1][i].occupied&&!mke_dirty(e,e->index[1][i].key))return 0;}
 for(size_t d=0;d<e->dirty_count;d++)for(size_t r=0;r<e->rule_count;r++){
  const MrlKnowledgeRule*q=e->rules+r;for(int k=0;k<q->premises;k++)if(q->body[k*3+1]<0||q->body[k*3+1]==e->dirty_preds[d]){if(q->head[1]>=0&&!mke_dirty(e,q->head[1]))return 0;break;}}
 for(size_t d=0;d<e->dirty_count;d++){MkeBucket*b=mke_bucket(e->index[1],e->index_cap,e->dirty_preds[d]);if(!b->occupied)continue;
  for(int32_t i=b->head;i>=0;i=e->facts[i].next[1]){MrlKnowledgeDerivedFact*f=e->facts+i;if(!mke_set_live(e,i,f->supports!=0&&!f->denials))return 0;if(f->supports){f->rule=-1;f->parent_count=0;}}}
 /* Rederive affected heads from all surviving supports, including unaffected
    premises. This avoids unsupported cycles and preserves alternate proofs. */
 size_t frozen=e->count;
 for(size_t r=0;r<e->rule_count;r++){MrlKnowledgeRule*q=e->rules+r;if(q->head[1]>=0&&!mke_affected(e,q->head[1]))continue;int32_t x[8],parents[8];for(int k=0;k<8;k++)x[k]=-1;if(!mke_join(e,q,0,x,parents,frozen,-1,-1))return 0;}
 return 1;
}
static int mrl_knowledge_close(MrlKnowledgeEngine*e){
 if(e->status)return 0;if(!e->editing){e->complete=1;return 1;}e->candidates=e->rule_firings=0;
 if(e->has_deletions&&!mke_prepare_delete(e))return 0;
 size_t begin=0;
 while(begin<e->pending_count){size_t end=e->pending_count,frozen=e->count;
  for(size_t r=0;r<e->rule_count;r++){const MrlKnowledgeRule*q=e->rules+r;
   for(int pivot=0;pivot<q->premises;pivot++)for(size_t d=begin;d<end;d++){
    int32_t anchor=e->pending[d];MrlKnowledgeDerivedFact f=e->facts[anchor];if(!f.live)continue;
    const int32_t*t=q->body+pivot*3;if((t[0]>=0&&t[0]!=f.s)||(t[1]>=0&&t[1]!=f.p)||(t[2]>=0&&t[2]!=f.o))continue;
    if(++e->candidates>e->work){e->status=MKE_WORK;return 0;}int32_t x[8],parents[8];for(int k=0;k<8;k++)x[k]=-1;
    if(!mke_bind(t[0],f.s,x)||!mke_bind(t[1],f.p,x)||!mke_bind(t[2],f.o,x))continue;
    if(!mke_join(e,q,0,x,parents,frozen,pivot,anchor))return 0;
   }
  }begin=end;
 }
 if(!mke_vec(e,&e->added,&e->added_cap,e->touched_count)||!mke_vec(e,&e->removed,&e->removed_cap,e->touched_count))return 0;
 for(size_t i=0;i<e->touched_count;i++){int32_t n=e->touched_rows[i];MrlKnowledgeDerivedFact*f=e->facts+n;if(f->live&&!f->previous_live)e->added[e->added_count++]=n;else if(!f->live&&f->previous_live)e->removed[e->removed_count++]=n;}
 for(size_t d=0;d<e->dirty_count;d++){MkeBucket*b=mke_bucket(e->index[1],e->index_cap,e->dirty_preds[d]);if(b->occupied)b->dirty=0;}
 e->pending_count=e->dirty_count=0;e->editing=e->has_deletions=0;e->complete=1;return 1;
}
static int mrl_knowledge_retract(MrlKnowledgeEngine*e,uint64_t id){return mrl_knowledge_remove(e,id)&&mrl_knowledge_close(e);}
typedef int(*MrlKnowledgeRowCallback)(const MrlKnowledgeDerivedFact*,void*);
/* Negative query terms are wildcards; exact membership uses the triple hash. */
static size_t mrl_knowledge_query(const MrlKnowledgeEngine*e,int32_t s,int32_t p,int32_t o,MrlKnowledgeRowCallback cb,void*ctx){
 if(s>=0&&p>=0&&o>=0){int32_t i=mke_lookup(e,s,p,o);if(i<0||!e->facts[i].live)return 0;if(cb)cb(e->facts+i,ctx);return 1;}
 if(!e->count)return 0;int32_t t[3]={s,p,o},at=0;int pos=-1;size_t best=SIZE_MAX,count=0;
 if(!cb){int bound=(s>=0)+(p>=0)+(o>=0);if(!bound)return e->live_count;if(bound==1){int k=s>=0?0:p>=0?1:2;MkeBucket*b=mke_bucket(e->index[k],e->index_cap,t[k]);return b->occupied?b->live_count:0;}}
 for(int k=0;k<3;k++)if(t[k]>=0){MkeBucket*b=mke_bucket(e->index[k],e->index_cap,t[k]);if(!b->occupied)return 0;if(b->count<best){best=b->count;pos=k;at=b->head;}}
 while(at>=0&&(size_t)at<e->count){const MrlKnowledgeDerivedFact*f=e->facts+at;if(f->live&&(s<0||s==f->s)&&(p<0||p==f->p)&&(o<0||o==f->o)){count++;if(cb&&!cb(f,ctx))break;}at=pos<0?at+1:f->next[pos];}return count;
}
#endif
