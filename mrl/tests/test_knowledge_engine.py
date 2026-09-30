import json,random,subprocess,tempfile,unittest
from pathlib import Path
from mrl import native_graph,oracle,toolchain
@unittest.skipUnless(native_graph.available(),"no C compiler")
class KnowledgeEngineTests(unittest.TestCase):
 def _run_c(self, source):
  with tempfile.TemporaryDirectory() as d:
   p,e=Path(d)/'x.c',Path(d)/'x.exe';p.write_text(source,encoding='utf-8')
   try: toolchain.build_c(p,e)
   except subprocess.CalledProcessError as error: self.fail(error.stderr.decode(errors='replace'))
   r=subprocess.run([str(e)],capture_output=True,text=True);self.assertEqual(r.returncode,0,r.stderr)
 def test_positive_fixture_edit_sequences(self):
  cases=json.loads((Path(__file__).parent/'fixtures'/'ninth_knowledge_cases.json').read_text())[:7]
  h=(Path(__file__).parents[1]/'runtime'/'knowledge_engine.h').read_text()
  for case in cases:
   symbols={x:i for i,x in enumerate(sorted({v for f in case['facts'] for v in f['triple']}|{v for r in case['rules'] for t in r['body']+[r['head']] for v in t if not v.startswith('?')}|{v for step in case['steps'] for x in step.values() if isinstance(x,dict) for v in x.get('triple',[]) }))}
   var={}; body=[]; rules=[]
   for ri,r in enumerate(case['rules']):
    var={}; flat=[]
    for triple in r['body']:
     for v in triple:
      flat.append(symbols[v] if not v.startswith('?') else var.setdefault(v,-len(var)-1))
    head=[symbols[v] if not v.startswith('?') else var[v] for v in r['head']]
    body.extend(flat); rules.append((len(body)-len(flat),len(r['body']),head,ri+1))
   lines=['#include <stdint.h>',h,'int main(){']
   lines.append('int32_t body[]={%s};'%(','.join(map(str,body)) or '0'))
   lines.append('MrlKnowledgeRule rules[]={'+','.join('{body+%d,%d,{%s},%d}'%(a,n,','.join(map(str,head)),rid) for a,n,head,rid in rules)+'};MrlKnowledgeEngine e;if(!mrl_knowledge_engine_init(&e,rules,%d,1000000))return 1;'%len(rules))
   ids={}; nextid=1
   for fact in case['facts']:
    if fact.get('modality')=='planned': continue
    ids[fact['id']]=nextid; admit='deny' if fact.get('polarity') is False else 'assert'; lines.append('if(!mrl_knowledge_%s(&e,%d,%d,%d,%d))return 2;'%(admit,nextid,*[symbols[x] for x in fact['triple']])); nextid+=1
   for si,step in enumerate([{}]+case['steps']):
    if step:
     if 'add' in step:
      f=step['add'];ids[f['id']]=nextid;lines.append('if(!mrl_knowledge_assert(&e,%d,%d,%d,%d))return 3;'%(nextid,*[symbols[x] for x in f['triple']]));nextid+=1
     elif 'remove' in step: lines.append('if(!mrl_knowledge_remove(&e,%d))return 4;'%ids[step['remove']])
     else:
      f=step['replace'];lines.append('if(!mrl_knowledge_correct(&e,%d,%d,%d,%d))return 5;'%(ids[f['id']],*[symbols[x] for x in f['triple']]))
    known=case['expected'][si]['known'];expected=[tuple(x['key']) for x in known.get('$tuple_map',[])]
    lines.append('if(!mrl_knowledge_close(&e)||e.live_count!=%d)return 6;'%len(expected))
    for t in expected: lines.append('if(!mrl_knowledge_has(&e,%d,%d,%d))return 7;'%tuple(symbols[x] for x in t))
   lines.append('mrl_knowledge_engine_free(&e);return 0;}')
   self._run_c('\n'.join(lines))
 def test_indexed_join_skips_unrelated_facts(self):
  h=(Path(__file__).parents[1]/'runtime'/'knowledge_engine.h').read_text()
  c='#include <stdint.h>\n'+h+r'''int main(){int32_t b[]={-1,1,-2,-2,2,-3};MrlKnowledgeRule r[]={{b,2,{-1,3,-3},1}};MrlKnowledgeEngine e;if(!mrl_knowledge_engine_init(&e,r,1,1000000))return 1;for(int i=0;i<100000;i++)if(!mrl_knowledge_assert(&e,(uint64_t)i+1,i,99,i))return 2;if(!mrl_knowledge_assert(&e,200001,7,1,8)||!mrl_knowledge_assert(&e,200002,8,2,9)||!mrl_knowledge_close(&e))return 3;if(!mrl_knowledge_has(&e,7,3,9)||e.candidates>100)return 4;mrl_knowledge_engine_free(&e);return 0;}'''
  self._run_c(c)
 def test_chain_join_and_cycle_retract(self):
  h=(Path(__file__).parents[1]/'runtime'/'knowledge_engine.h').read_text()
  c=r'''#include <stdint.h>
'''+h+r'''int main(){int32_t b[]={-1,1,-2,-1,2,-2},c[]={-1,2,-2};MrlKnowledgeRule r[]={{b,2,{-1,3,-2},1},{c,1,{-1,2,-2},2}};MrlKnowledgeEngine e;mrl_knowledge_engine_init(&e,r,2,10000);mrl_knowledge_assert(&e,1,10,1,20);mrl_knowledge_assert(&e,2,10,2,20);if(!mrl_knowledge_close(&e)||e.live_count!=3)return 1;if(!mrl_knowledge_retract(&e,1)||e.live_count!=1)return 2;mrl_knowledge_engine_free(&e);return 0;}'''
  self._run_c(c)
 def test_seeded_positive_edits_match_frozen_oracle(self):
  """Seeded cases keep the oracle comparison reproducible without changing it."""
  h=(Path(__file__).parents[1]/'runtime'/'knowledge_engine.h').read_text()
  rng=random.Random(913)
  for case_no in range(12):
   facts=[{'id':'f%d'%i,'triple':['s%d'%(i%7),'p%d'%(i%3),'o%d'%(i%5)],'evidence':{}} for i in range(18)]
   rules=[
    {'id':'r0','body':[['?x','p0','?y']],'head':['?x','p3','?y']},
    {'id':'r1','body':[['?x','p3','?y']],'head':['?x','p4','?y']},
    {'id':'r2','body':[['?x','p1','?y'],['?x','p2','?z']],'head':['?x','p5','?z']},
   ]
   rng.shuffle(facts)
   steps=[]
   for step in range(7):
    if step%3==0:
     f={'id':'a%d_%d'%(case_no,step),'triple':['s%d'%rng.randrange(7),'p%d'%rng.randrange(3),'o%d'%rng.randrange(5)],'evidence':{}}
     facts.append(f);steps.append({'add':f})
    elif step%3==1:
     live=[f for f in facts if f is not None]
     f=live[rng.randrange(len(live))];facts[facts.index(f)]=None;steps.append({'remove':f['id']})
    else:
     live=[f for f in facts if f is not None];old=live[rng.randrange(len(live))]
     new={'id':old['id'],'triple':['s%d'%rng.randrange(7),'p%d'%rng.randrange(3),'o%d'%rng.randrange(5)],'evidence':{}}
     facts[facts.index(old)]=new;steps.append({'replace':new})
   # Reconstruct each edit state for the unchanged Python oracle.
   initial=[{'id':'f%d'%i,'triple':['s%d'%(i%7),'p%d'%(i%3),'o%d'%(i%5)],'evidence':{}} for i in range(18)]
   rng2=random.Random(913)
   # The generated sequence is already concrete; native expectations come from replay below.
   current=[dict(f) for f in initial]; rng2.shuffle(current)
   symbols={v:i for i,v in enumerate(sorted({x for f in current for x in f['triple']}|{x for r in rules for t in r['body']+[r['head']] for x in t if not x.startswith('?')}|{x for s in steps for f in s.values() if isinstance(f,dict) for x in f['triple']}))}
   body=[-1,symbols['p0'],-2,-1,symbols['p3'],-2,-1,symbols['p1'],-2,-1,symbols['p2'],-3]
   lines=['#include <stdint.h>',h,'int main(){int32_t b[]={'+','.join(map(str,body))+'};MrlKnowledgeRule r[]={{b,1,{-1,'+str(symbols['p3'])+',-2},1},{b+3,1,{-1,'+str(symbols['p4'])+',-2},2},{b+6,2,{-1,'+str(symbols['p5'])+',-3},3}};MrlKnowledgeEngine e;if(!mrl_knowledge_engine_init(&e,r,3,1000000))return 1;']
   ids={};next_id=1
   for f in current:
    ids[f['id']]=next_id;lines.append('if(!mrl_knowledge_assert(&e,%d,%d,%d,%d))return 2;'%(next_id,*[symbols[x] for x in f['triple']]));next_id+=1
   replay=[current]
   for s in steps:
    current=[dict(f) for f in current]
    if 'add' in s: current.append(s['add'])
    elif 'remove' in s: current=[f for f in current if f['id']!=s['remove']]
    else: current=[s['replace'] if f['id']==s['replace']['id'] else f for f in current]
    replay.append(current)
   for at,state in enumerate(replay):
    if at:
     s=steps[at-1]
     if 'add' in s:
      f=s['add'];ids[f['id']]=next_id;lines.append('if(!mrl_knowledge_assert(&e,%d,%d,%d,%d))return 3;'%(next_id,*[symbols[x] for x in f['triple']]));next_id+=1
     elif 'remove' in s: lines.append('if(!mrl_knowledge_remove(&e,%d))return 4;'%ids[s['remove']])
     else:
      f=s['replace'];lines.append('if(!mrl_knowledge_correct(&e,%d,%d,%d,%d))return 5;'%(ids[f['id']],*[symbols[x] for x in f['triple']]))
    expected=oracle.evaluate({'operation':'closure','facts':state,'rules':rules})['known']['$tuple_map']
    triples={tuple(row['key']) for row in expected}
    lines.append('if(!mrl_knowledge_close(&e)||e.live_count!=%d)return 6;'%len(triples))
    for t in triples: lines.append('if(!mrl_knowledge_has(&e,%d,%d,%d))return 7;'%tuple(symbols[x] for x in t))
   lines.append('mrl_knowledge_engine_free(&e);return 0;}')
   self._run_c('\n'.join(lines))
 def test_proof_parents_duplicate_assertions_queries_and_limits(self):
  h=(Path(__file__).parents[1]/'runtime'/'knowledge_engine.h').read_text()
  self._run_c('#include <stdint.h>\n'+h+'''\nstatic int seen(const MrlKnowledgeDerivedFact*f,void*x){(*(int*)x)++;return 1;}
int main(){int32_t b[]={-1,1,-2,-1,2,-2};MrlKnowledgeRule r[]={{b,2,{-1,3,-2},9}};MrlKnowledgeEngine e;
 if(!mrl_knowledge_engine_init(&e,r,1,1000)||!mrl_knowledge_assert(&e,10,7,1,8)||!mrl_knowledge_assert(&e,11,7,1,8)||!mrl_knowledge_assert(&e,12,7,2,8)||!mrl_knowledge_close(&e))return 1;
 if(e.assertion_count!=3||e.count!=3||e.live_count!=3||!e.facts[2].live||e.facts[2].parent_count!=2)return 2;
 for(int k=0;k<2;k++){int p=e.facts[2].parents[k];if(p<0||(size_t)p>=e.count||!e.facts[p].live||e.facts[p].s!=7||e.facts[p].o!=8||e.facts[p].p!=k+1)return 3;}
 {int n=0;if(mrl_knowledge_query(&e,7,3,-1,seen,&n)!=1||n!=1)return 4;}
 if(!mrl_knowledge_remove(&e,10)||!mrl_knowledge_close(&e)||!mrl_knowledge_has(&e,7,3,8)||e.live_count!=3)return 5;
 if(!mrl_knowledge_remove(&e,11)||!mrl_knowledge_close(&e)||mrl_knowledge_has(&e,7,3,8)||e.live_count!=1||e.count!=3||e.removed_count!=2)return 6;
 mrl_knowledge_engine_free(&e);if(e.bytes||e.facts||e.assertions)return 7;
 if(!mrl_knowledge_engine_init(&e,r,1,1)||!mrl_knowledge_engine_limits(&e,99,1,e.bytes)||mrl_knowledge_assert(&e,1,1,1,1)||e.status!=MKE_MEMORY)return 8;mrl_knowledge_engine_free(&e);
 if(!mrl_knowledge_engine_init(&e,r,1,1)||!mrl_knowledge_engine_limits(&e,1,99,SIZE_MAX)||!mrl_knowledge_assert(&e,1,1,1,1)||mrl_knowledge_assert(&e,2,2,1,2)||e.status!=MKE_LIMIT)return 9;mrl_knowledge_engine_free(&e);
 if(!mrl_knowledge_engine_init(&e,r,1,1)||!mrl_knowledge_assert(&e,1,1,1,1)||!mrl_knowledge_assert(&e,2,1,2,1)||mrl_knowledge_close(&e)||e.status!=MKE_WORK)return 10;mrl_knowledge_engine_free(&e);
 if(!mrl_knowledge_engine_init(&e,r,1,1000)||!mrl_knowledge_assert(&e,20,5,6,7)||!mrl_knowledge_close(&e)||!mrl_knowledge_deny(&e,21,5,6,7)||!mrl_knowledge_close(&e)||mrl_knowledge_has(&e,5,6,7)||!mrl_knowledge_remove(&e,21)||!mrl_knowledge_close(&e)||!mrl_knowledge_has(&e,5,6,7))return 11;mrl_knowledge_engine_free(&e);
 return 0;}''')
 def test_shared_allocator_refuses_growth_and_releases_every_block(self):
  h=(Path(__file__).parents[1]/'runtime'/'knowledge_engine.h').read_text()
  self._run_c('#include <stdlib.h>\n#include <stdint.h>\n'+h+'''\ntypedef struct {size_t used,cap;} Budget;typedef struct {size_t n;} Block;
static void* resize_shared(void*ctx,void*p,size_t n){Budget*b=ctx;Block*old=p?(Block*)p-1:0;size_t was=old?old->n:0;if(n>was&&n-was>b->cap-b->used)return NULL;if(!n){if(old){b->used-=was;free(old);}return NULL;}Block*q=realloc(old,sizeof(*q)+n);if(!q)return NULL;q->n=n;b->used=b->used-was+n;return q+1;}
static void free_shared(void*ctx,void*p){Budget*b=ctx;Block*q=p?(Block*)p-1:0;if(q){b->used-=q->n;free(q);}}
int main(){int32_t b[]={-1,1,-2};MrlKnowledgeRule r[]={{b,1,{-1,2,-2},1}};MrlKnowledgeEngine e;Budget budget={0,100000};
 if(!mrl_knowledge_engine_init_with_allocator(&e,r,1,1000,&budget,resize_shared,free_shared)||!budget.used||budget.used!=e.bytes)return 1;budget.cap=budget.used;
 if(mrl_knowledge_assert(&e,1,1,1,1)||e.status!=MKE_MEMORY)return 2;mrl_knowledge_engine_free(&e);return budget.used?3:0;}''')
