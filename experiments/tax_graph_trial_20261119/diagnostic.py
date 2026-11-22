"""Post-hoc diagnostic on frozen model and full context; one capture only."""
import hashlib
import json
import os
from pathlib import Path
import time
from . import runner
p=Path(__file__).resolve().parent
sha=lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
read=lambda name: json.loads((p/name).read_text(encoding='utf8'))
def capture():
 m=read('manifest.json')
 if runner.hashes()!=m['sha256'] or sha(p/'model.json')!=m['model_sha256']:
  raise ValueError('Original frozen inputs or source changed')
 frozen=read('diagnostic_manifest.json')
 if sha(p/'supplemental_questions.json')!=frozen['questions_sha256'] or sha(p/'diagnostic.py')!=frozen['runner_sha256'] or sha(p/'manifest.json')!=frozen['original_manifest_sha256']:
  raise ValueError('Diagnostic inputs or original manifest changed')
 questions=read('supplemental_questions.json'); contexts={c['id']:c for c in read('contexts.json')}; model=read('model.json')
 with (p/'diagnostic_first_results.jsonl').open('x',encoding='utf8') as out:
  for q in questions:
   context=contexts[q['context_id']]; start=time.perf_counter()
   result=runner.bounded_answer('graph',context,q['text'],model)
   row={'question_id':q['id'],'question':q['text'],'context_id':context['id'],'arm':'graph', 'sources':context['sources'], 'elapsed_seconds':time.perf_counter()-start,'manifest_sha256':frozen['original_manifest_sha256'],'model_sha256':m['model_sha256'],'diagnostic_manifest_sha256':sha(p/'diagnostic_manifest.json'),'result':result}
   out.write(json.dumps(row,ensure_ascii=False)+'\n'); out.flush(); os.fsync(out.fileno())
if __name__=='__main__': capture()
