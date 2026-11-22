"""One-shot rerun of fixed inputs, no training and no output retries."""
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from experiments.tax_graph_trial_20261119 import runner as original

HERE=Path(__file__).resolve().parent
BASE=HERE.parent
ROOT=original.ROOT
PROTECTED=['lessons.json','contexts.json','questions.json','supplemental_questions.json','facts.json','model.json','manifest.json','first_results.jsonl','diagnostic_first_results.jsonl','diagnostic_manifest.json','REPORT.md','rerun_after_length_fix_20261119/manifest.json','rerun_after_length_fix_20261119/first_results.jsonl','rerun_after_length_fix_20261119/REPORT.md','rerun_after_length_fix_20261119/postcheck.json']
EXPECTED={'rerun_after_length_fix_20261119/first_results.jsonl':'30ad2e334df56fab60f1dbd9d5194af77f2e69c566566df1373b19dec0921e99','model.json':'b4a9cdeaf3fb67af41e4386480c25b490101db1f71e47e67ea73388fed0a2fda','manifest.json':'1f6972280a86b930d44c41eb965af19cd74d3cf19a66cbfc16ba324bff8aa9a1','first_results.jsonl':'a8ebaac4210fc774c3526bce7dd04431ad9783a4c9d1f18391136c8bfb12ef35','diagnostic_first_results.jsonl':'c52e76d2543022bcacfb725b39e7dcdc5635e24803c7b05317b5f75d4d9ff150','questions.json':'21f8ec52e370d7f85de705900d9c8235c4d8e4eec251b507937080092c609253','supplemental_questions.json':'e1426dfb8d2d1547b5d093060847d04b87a756cb1b2f5d4c9cd6fcb0451863b3'}
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p): return json.loads(p.read_text(encoding='utf8'))
def inputs(): return {x:sha(BASE/x) for x in PROTECTED}
def sources(): return {str(p.relative_to(ROOT)):sha(p) for p in original.SOURCES}
def save(path,obj):
 with path.open('x',encoding='utf8') as f:
  json.dump(obj,f,ensure_ascii=False,indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
def freeze():
 hashes=inputs()
 assert all(hashes[k]==v for k,v in EXPECTED.items())
 q=read(BASE/'questions.json'); extra=read(BASE/'supplemental_questions.json'); c=read(BASE/'contexts.json'); lessons=read(BASE/'lessons.json'); facts=read(BASE/'facts.json')
 assert (len(q),len(extra),len(c),len(lessons),len(facts))==(24,4,1,44,14)
 assert all(x['context_id']=='tax-all' for x in q+extra) and c[0]['id']=='tax-all'
 src=sources()
 for name in src:
  dest=HERE/'source_snapshot'/name; dest.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(ROOT/name,dest)
 assert all(sha(HERE/'source_snapshot'/name)==value for name,value in src.items())
 save(HERE/'manifest.json',{'inputs':hashes,'sources':src,'runner_sha256':sha(HERE/'run.py'),'model_sha256':hashes['model.json'],'question_count':24,'supplemental_count':4,'graph_timeout_seconds':20,'text_timeout_seconds':10,'workers':2,'snapshot':'source_snapshot'})
def check(m):
 return inputs()==m['inputs'] and sources()==m['sources'] and sha(HERE/'run.py')==m['runner_sha256'] and all(sha(HERE/'source_snapshot'/n)==h for n,h in m['sources'].items())
def capture():
 m=read(HERE/'manifest.json')
 if not check(m): raise ValueError('Frozen source or input mismatch')
 model=read(BASE/'model.json'); contexts={c['id']:c for c in read(BASE/'contexts.json')}
 jobs=[(q,arm,'main') for q in read(BASE/'questions.json') for arm in ('graph','end_to_end')]+[(q,'graph','supplemental') for q in read(BASE/'supplemental_questions.json')]
 def call(job):
  q,arm,group=job; context=contexts[q['context_id']]; start=time.perf_counter()
  try: result=original.bounded_answer(arm,context,q['text'],model)
  except Exception as e: result={'status':'error','answers':[],'reason':repr(e)}
  return {'question_id':q['id'],'question':q['text'],'group':group,'arm':arm,'context_id':context['id'],'sources':context['sources'],'elapsed_seconds':time.perf_counter()-start,'manifest_sha256':sha(HERE/'manifest.json'),'model_sha256':m['model_sha256'],'result':result}
 with (HERE/'first_results.jsonl').open('x',encoding='utf8') as out:
  with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
   futures=[pool.submit(call,job) for job in jobs]
   for future in concurrent.futures.as_completed(futures):
    out.write(json.dumps(future.result(),ensure_ascii=False)+'\n'); out.flush(); os.fsync(out.fileno())
 save(HERE/'postcheck.json',{'inputs_and_sources_unchanged':check(m),'post_inputs':inputs(),'post_sources':sources(),'results_sha256':sha(HERE/'first_results.jsonl')})
if __name__=='__main__':
 import sys
 {'freeze':freeze,'run':capture}[sys.argv[1]]()
