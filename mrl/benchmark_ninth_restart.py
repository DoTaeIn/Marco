"""Measure real file admission, durable checkpoint and prepared-engine restart.
Run: python -m mrl.benchmark_ninth_restart --sizes 10000 100000 --samples 3
Compilation and JSONL generation are outside the measured fresh-process runs.
"""
import argparse
import hashlib
import json
import math
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from mrl.toolchain import build_c

ROOT = Path(__file__).parent
HEADERS = ['knowledge_store.h','knowledge_engine.h','horn_jsonl.h','knowledge_persist.h','knowledge_cache.h','knowledge_journal.h','horn_runtime_v7.h']

def source(runtime_dir=ROOT / "runtime"):
    prelude = '#include <stdio.h>\n#include <stdlib.h>\n#include <stdint.h>\n#include <string.h>\nstatic void mrl_runtime_fail(const char*s){fprintf(stderr,"%s\\n",s);exit(90);}\n'
    headers = '\n'.join('\n'.join(line for line in (runtime_dir/name).read_text(encoding='utf-8').splitlines() if not line.startswith('#include "')) for name in HEADERS)
    return prelude + headers + r"""
#if defined(_WIN32)
static double now_ms(void){LARGE_INTEGER c,f;QueryPerformanceCounter(&c);QueryPerformanceFrequency(&f);return 1000.0*(double)c.QuadPart/(double)f.QuadPart;}
#else
#include <time.h>
static double now_ms(void){struct timespec t;clock_gettime(CLOCK_MONOTONIC,&t);return 1000.0*t.tv_sec+t.tv_nsec/1000000.0;}
#endif
int main(int argc,char**argv){if(argc!=5)return 1;int n=atoi(argv[4]);MrlHornPlanRule rule={"pq","1",1,{{"?x","p","?y"}},{"?x","q","?y"}};
 MrlHornPlanTemplate template={NULL,0,&rule,1,n*3+32,(size_t)1536*1024*1024};MrlHornPlan*p=mrl_horn_plan_new(&template);MrlHornLoadResult result;double start=now_ms(),load,query,save=0,commit=0;int expected=n*2;
 if(!strcmp(argv[1],"load")){result=mrl_horn_plan_load(&p,argv[2]);}else{result=mrl_horn_plan_restore(&p,argv[3]);if(!strcmp(argv[1],"journal"))expected+=2;}
 load=now_ms()-start;if(!result.ok){fprintf(stderr,"%s\n",result.error);return 2;}
 start=now_ms();int count=mrl_horn_plan_count(p,NULL,NULL,NULL);query=now_ms()-start;if(count!=expected){fprintf(stderr,"count %d != %d\n",count,expected);return 3;}
 puts("READY");fflush(stdout);
 if(!strcmp(argv[1],"load")){start=now_ms();result=mrl_horn_plan_save(p,argv[3]);save=now_ms()-start;if(!result.ok){fprintf(stderr,"%s\n",result.error);return 4;}}
 if(!strcmp(argv[1],"edit")){start=now_ms();if(!mrl_horn_plan_add(&p,"added","new","p","tail",true,"asserted",(MrlHornEvidence){0}))return 5;result=mrl_horn_plan_commit(&p,argv[3]);commit=now_ms()-start;if(!result.ok){fprintf(stderr,"%s\n",result.error);return 6;}}
 printf("{\"load_or_restore_ms\":%.6f,\"first_query_ms\":%.6f,\"checkpoint_ms\":%.6f,\"append_commit_ms\":%.6f,\"cache_hit\":%d,\"fact_count\":%d,\"peak_tracked_bytes\":%llu}\n",load,query,save,commit,p->cache_hit,count,(unsigned long long)mrl_knowledge_store_peak(p->store));mrl_horn_plan_release(p);return 0;}
"""

def summary(rows):
    return {key:{'median':statistics.median(row[key] for row in rows),'p95':sorted(row[key] for row in rows)[math.ceil(.95*len(rows))-1],'samples':[row[key] for row in rows]} for key in rows[0]}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--sizes',nargs='+',type=int,default=[10000,100000]);parser.add_argument('--samples',type=int,default=3);args=parser.parse_args()
    report={'samples':args.samples,'p95_method':'nearest rank; three samples means the maximum, not a tail-latency estimate','boundary':'Fresh native processes. OS filesystem cache is not flushed; this is restart measurement, not cold-disk latency. Source compilation excluded. Process wall includes startup, work, printing and cleanup. Restore validates/rebuilds indexes but does not re-infer checkpoint proofs.','source_sha256':{name:hashlib.sha256((ROOT/'runtime'/name).read_bytes()).hexdigest() for name in HEADERS},'sizes':{}}
    with tempfile.TemporaryDirectory(prefix='mrl-restart-') as temporary:
        directory=Path(temporary);c=directory/'restart.c';exe=directory/'restart.exe';c.write_text(source(),encoding='utf-8')
        try:build_c(c,exe)
        except subprocess.CalledProcessError as error:raise RuntimeError(error.stderr.decode(errors='replace')) from error
        for n in args.sizes:
            jsonl=directory/f'{n}.jsonl'
            with jsonl.open('w',encoding='utf-8',newline='\n') as stream:
                for i in range(n):stream.write(json.dumps({'id':f'f{i}','triple':[f's{i}','p',f'o{i}']},separators=(',',':'))+'\n')
            rows={mode:[] for mode in ['load','restore','edit','journal']}
            for sample in range(args.samples):
                checkpoint=directory/f'{n}-{sample}.bin'
                for mode in rows:
                    start=time.perf_counter();run=subprocess.Popen([str(exe),mode,str(jsonl),str(checkpoint),str(n)],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
                    ready=run.stdout.readline();first_answer=(time.perf_counter()-start)*1000
                    output,error=run.communicate(timeout=180);elapsed=(time.perf_counter()-start)*1000
                    if run.returncode or ready.strip()!='READY':raise RuntimeError(f'{mode}/{n}: {run.returncode}: {ready} {error}')
                    row=json.loads(output);row['first_answer_ms']=row['load_or_restore_ms']+row['first_query_ms'];row['process_to_first_answer_ms']=first_answer;row['process_wall_ms']=elapsed;rows[mode].append(row)
            report['sizes'][str(n)]={mode:summary(values) for mode,values in rows.items()};print(n,report['sizes'][str(n)],flush=True)
    (ROOT/'docs/NINTH_RESTART_BENCHMARK.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')

if __name__=='__main__':main()
