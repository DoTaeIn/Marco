"""Compare fresh-process selective lookup with the frozen eager runtime.

python -B -m mrl.benchmark_scalable_startup --sizes 10000 100000 1000000 --samples 3
"""
import argparse
import hashlib
import json
import math
import platform
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

from mrl.benchmark_ninth_restart import HEADERS
from mrl.toolchain import build_c

ROOT = Path(__file__).resolve().parent
COMMIT = "2a7d4f9e29695dae4757d2024ca6c4b9902afa5b"
PRELUDE = r'''
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>
static void mrl_runtime_fail(const char *s) { fprintf(stderr,"%s\n",s); exit(90); }
'''
CLOCK = r'''
static double now_ms(void) {
    LARGE_INTEGER c,f; QueryPerformanceCounter(&c); QueryPerformanceFrequency(&f);
    return 1000.0*(double)c.QuadPart/(double)f.QuadPart;
}
static void require(int ok,const char *message) {
    if(!ok) { fprintf(stderr,"%s\n",message); exit(91); }
}
static void checked(const char *error) { if(error) mrl_runtime_fail(error); }
'''
INDEXED = r'''
static void verify(MrlKnowledgeIndexed *ix,int n,int round,int delta) {
    char s[64],o[64]; MrlKnowledgeFact fact;
    snprintf(s,sizeof(s),"s%d",n-1); snprintf(o,sizeof(o),"o%d",n-1);
    require(mrl_knowledge_indexed_find(ix,s,"p",o,&fact)&&fact.polarity,"original fact missing");
    if(round>=0) {
        snprintf(o,sizeof(o),"corrected%d",round);
        require(mrl_knowledge_indexed_find(ix,"s0","p",o,&fact)&&fact.polarity,"correction missing");
        require(!mrl_knowledge_indexed_find(ix,"s0","p","o0",&fact),"old value survived");
        if(round>0) {
            snprintf(o,sizeof(o),"corrected%d",round-1);
            require(!mrl_knowledge_indexed_find(ix,"s0","p",o,&fact),"previous correction survived");
        }
        int last=n+(round+1)*delta-1;
        snprintf(s,sizeof(s),"s%d",last); snprintf(o,sizeof(o),"o%d",last);
        require(mrl_knowledge_indexed_find(ix,s,"p",o,&fact)&&fact.polarity,"new fact missing");
    }
    require(!ix->error,"indexed query error");
}
int main(int argc,char **argv) {
    require(argc==6,"arguments");
    const char *mode=argv[1],*path=argv[2];
    int n=atoi(argv[3]),round=atoi(argv[4]),delta=atoi(argv[5]);
    char id[64],subject[64],object[64];
    if(!strcmp(mode,"build")) {
        MrlKnowledgeStore *store=mrl_knowledge_store_new((size_t)1536*1024*1024);
        require(store!=NULL,"store allocation");
        for(int k=0;k<n;k++) {
            MrlKnowledgeSymbol a,b,p,o;
            snprintf(id,sizeof(id),"f%d",k); snprintf(subject,sizeof(subject),"s%d",k);
            snprintf(object,sizeof(object),"o%d",k);
            require(mrl_knowledge_store_intern(store,id,&a)&&mrl_knowledge_store_intern(store,subject,&b)&&
                mrl_knowledge_store_intern(store,"p",&p)&&mrl_knowledge_store_intern(store,object,&o),"intern");
            require(mrl_knowledge_store_append(store,(MrlKnowledgeFact){k+1,a,b,p,o,0,1,0,1},1),"append");
        }
        MrlIndexedResult result=mrl_indexed_save(store,path);
        if(!result.ok) mrl_runtime_fail(result.error);
        mrl_knowledge_store_release(store); return 0;
    }
    MrlKnowledgeIndexed ix={0};
    checked(mrl_knowledge_indexed_open(&ix,path,NULL,MRL_INDEXED_ASSERTION_FINGERPRINT));
    double update_ms=0;
    if(!strcmp(mode,"append")) {
        double start=now_ms();
        MrlIxApi *api=(MrlIxApi*)ix.api; MrlIxDb *db=(MrlIxDb*)ix.db;
        uint32_t symbol=mrl_ix_next_id(api,db,"id"),fid=mrl_ix_next_id(api,db,"fact_id"),predicate=0;
        require(symbol&&fid&&mrl_ix_lookup_id(api,db,"p",&predicate)==1,"next ID");
        size_t count=(size_t)delta*3+1;
        MrlKnowledgeIndexedSymbol *symbols=calloc(count,sizeof(*symbols));
        char (*texts)[64]=calloc(count,sizeof(*texts));
        MrlKnowledgeFact *rows=calloc((size_t)delta+1,sizeof(*rows));
        require(symbols&&texts&&rows,"batch allocation");
        for(int k=0;k<delta;k++) {
            int value=n+round*delta+k; size_t at=(size_t)k*3;
            snprintf(texts[at],64,"f%d",value); snprintf(texts[at+1],64,"s%d",value);
            snprintf(texts[at+2],64,"o%d",value);
            for(int j=0;j<3;j++) symbols[at+j]=(MrlKnowledgeIndexedSymbol){symbol+(uint32_t)at+j,texts[at+j]};
            rows[k]=(MrlKnowledgeFact){fid+k,symbol+(uint32_t)at,symbol+(uint32_t)at+1,predicate,symbol+(uint32_t)at+2,0,1,0,1};
        }
        uint32_t original,unused;
        require(mrl_ix_fact_for_name(api,db,"f0",&original,&unused)==1&&mrl_ix_read_fact(api,db,original,&rows[delta]),"correction target");
        snprintf(texts[count-1],64,"corrected%d",round);
        symbols[count-1]=(MrlKnowledgeIndexedSymbol){symbol+(uint32_t)count-1,texts[count-1]};
        rows[delta].object=symbols[count-1].id;
        checked(mrl_knowledge_indexed_append(&ix,ix.version+1,symbols,count,rows,(size_t)delta+1,NULL));
        update_ms=now_ms()-start;
        free(rows); free(texts); free(symbols);
    } else verify(&ix,n,round,delta);
    MrlKnowledgeIndexedStats stats=mrl_knowledge_indexed_stats(&ix);
    puts("READY"); fflush(stdout);
    printf("{\"update_commit_ms\":%.6f,\"rows_read\":%llu,\"logical_payload_bytes\":%llu,\"vm_steps\":%llu,\"fullscan_steps\":%llu}\n",
        update_ms,(unsigned long long)stats.rows_read,(unsigned long long)stats.bytes_read,
        (unsigned long long)stats.vm_steps,(unsigned long long)stats.fullscan_steps);
    mrl_knowledge_indexed_close(&ix); return 0;
}
'''
EAGER = r'''
int main(int argc,char **argv) {
    require(argc==7,"arguments");
    const char *mode=argv[1],*jsonl=argv[2],*checkpoint=argv[3];
    int n=atoi(argv[4]),round=atoi(argv[5]),delta=atoi(argv[6]);
    MrlHornPlanTemplate template={NULL,0,NULL,0,n*2+32,(size_t)1536*1024*1024};
    MrlHornPlan *plan=mrl_horn_plan_new(&template);
    MrlHornLoadResult result=!strcmp(mode,"build")?mrl_horn_plan_load(&plan,jsonl):mrl_horn_plan_restore(&plan,checkpoint);
    require(result.ok,result.error?result.error:"load/restore");
    char id[64],subject[64],object[64]; double update_ms=0;
    if(!strcmp(mode,"build")) {
        result=mrl_horn_plan_save(plan,checkpoint); require(result.ok,result.error?result.error:"save");
        mrl_horn_plan_release(plan); return 0;
    }
    if(!strcmp(mode,"append")) {
        double start=now_ms();
        for(int k=0;k<delta;k++) {
            int value=n+round*delta+k;
            snprintf(id,sizeof(id),"f%d",value); snprintf(subject,sizeof(subject),"s%d",value);
            snprintf(object,sizeof(object),"o%d",value);
            require(mrl_horn_plan_add(&plan,id,subject,"p",object,true,"asserted",(MrlHornEvidence){0}),"add");
        }
        snprintf(object,sizeof(object),"corrected%d",round);
        require(mrl_horn_plan_correct(&plan,"f0","s0","p",object,true,"asserted",(MrlHornEvidence){0}),"correct");
        result=mrl_horn_plan_commit(&plan,checkpoint); require(result.ok,result.error?result.error:"commit");
        update_ms=now_ms()-start;
    } else {
        snprintf(subject,sizeof(subject),"s%d",n-1); snprintf(object,sizeof(object),"o%d",n-1);
        require(mrl_horn_plan_exists(plan,subject,"p",object),"original fact missing");
        if(round>=0) {
            snprintf(object,sizeof(object),"corrected%d",round);
            require(mrl_horn_plan_exists(plan,"s0","p",object),"correction missing");
            require(!mrl_horn_plan_exists(plan,"s0","p","o0"),"old value survived");
            if(round>0) {
                snprintf(object,sizeof(object),"corrected%d",round-1);
                require(!mrl_horn_plan_exists(plan,"s0","p",object),"previous correction survived");
            }
            int last=n+(round+1)*delta-1;
            snprintf(subject,sizeof(subject),"s%d",last); snprintf(object,sizeof(object),"o%d",last);
            require(mrl_horn_plan_exists(plan,subject,"p",object),"new fact missing");
        }
    }
    puts("READY"); fflush(stdout);
    printf("{\"update_commit_ms\":%.6f,\"peak_tracked_bytes\":%llu}\n",update_ms,
        (unsigned long long)mrl_knowledge_store_peak(plan->store));
    mrl_horn_plan_release(plan); return 0;
}
'''


def headers(directory, names):
    return "\n".join("\n".join(line for line in (directory/name).read_text(encoding="utf-8").splitlines()
                               if not line.startswith('#include "')) for name in names)


def run(executable, *arguments, measured=True):
    command = [str(executable), *map(str, arguments)]
    print("running", executable.stem, *map(str, arguments[::2]), flush=True)
    start = time.perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    ready = process.stdout.readline().strip() if measured else None
    first_ms = (time.perf_counter()-start)*1000
    output, error = process.communicate(timeout=900)
    if process.returncode or measured and ready != "READY":
        raise RuntimeError(f"{command}: exit {process.returncode}; ready={ready!r}; stdout={output}; stderr={error}")
    if not measured:
        return None
    row = json.loads(output)
    row.update(process_to_ready_ms=first_ms, process_wall_ms=(time.perf_counter()-start)*1000)
    return row


def aggregate(values):
    return {"samples_ms": values, "median_ms": statistics.median(values),
            "p95_ms": sorted(values)[math.ceil(.95*len(values))-1]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sizes", nargs="+", type=int, default=[10000, 100000, 1000000])
    parser.add_argument("--samples", type=int, default=3)
    parser.add_argument("--output", type=Path, default=ROOT/"docs/SCALABILITY_BENCHMARK.json")
    args = parser.parse_args()
    if platform.system() != "Windows":
        parser.error("indexed runtime currently requires Windows winsqlite3")
    if not 1 <= args.samples <= 50 or any(n < 2 for n in args.sizes):
        parser.error("use sizes >= 2 and 1..50 samples")
    names = ["knowledge_store.h", "knowledge_indexed.h"]
    report = {
        "baseline_commit": COMMIT, "samples": args.samples, "platform": platform.platform(),
        "boundary": "Fresh native process to flushed READY after verified exact asserted lookup; append READY follows durable commit.",
        "scope": "No Horn rules; same fact IDs/triples. Indexed native find and eager Horn exists. Source indexed API has separate end-to-end acceptance.",
        "cache": "OS cache not flushed; process restarts, not cold-disk measurements.",
        "excluded": ["compilation", "input generation", "initial indexed export", "initial eager checkpoint/cache export"],
        "updates": "Cumulative rounds: each appends 1% of initial N plus one correction, one durable transaction/commit per round. update_commit_ms excludes open/restore; process_to_ready_ms includes it.",
        "metrics": "Indexed bytes are materialized fact records, not disk I/O; VM/fullscan stats cover find statements. Baseline peak_tracked_bytes excludes untracked allocations.",
        "p95": "nearest rank; 3 samples gives max, not a tail-latency estimate",
        "source_sha256": {name: hashlib.sha256((ROOT/"runtime"/name).read_bytes()).hexdigest() for name in names},
        "sizes": {},
    }
    with tempfile.TemporaryDirectory(prefix="mrl-scale-") as temporary:
        directory = Path(temporary)
        old = directory/"baseline"
        old.mkdir()
        for name in HEADERS:
            result = subprocess.run(["git", "show", f"{COMMIT}:mrl/runtime/{name}"], cwd=ROOT.parent,
                                    check=True, capture_output=True)
            (old/name).write_bytes(result.stdout)
        report["baseline_source_sha256"] = {name: hashlib.sha256((old/name).read_bytes()).hexdigest() for name in HEADERS}
        index_source = PRELUDE+headers(ROOT/"runtime", names)+CLOCK+INDEXED
        eager_source = PRELUDE+headers(old, HEADERS)+CLOCK+EAGER
        report["generated_source_sha256"] = {"indexed": hashlib.sha256(index_source.encode()).hexdigest(),
                                             "baseline": hashlib.sha256(eager_source.encode()).hexdigest()}
        for name, source in [("indexed", index_source), ("eager", eager_source)]:
            path = directory/f"{name}.c"
            path.write_text(source, encoding="utf-8")
            build_c(path, directory/f"{name}.exe", optimization="release")
        for n in args.sizes:
            jsonl, db, checkpoint = directory/f"{n}.jsonl", directory/f"{n}.db", directory/f"{n}.bin"
            with jsonl.open("w", encoding="utf-8", newline="\n") as stream:
                for k in range(n):
                    stream.write(json.dumps({"id": f"f{k}", "triple": [f"s{k}", "p", f"o{k}"]}, separators=(",", ":"))+"\n")
            delta = max(1, n//100)
            commands = {
                "indexed": (directory/"indexed.exe", lambda mode, r: (mode, db, n, r, delta)),
                "baseline": (directory/"eager.exe", lambda mode, r: (mode, jsonl, checkpoint, n, r, delta)),
            }
            for executable, arguments in commands.values():
                run(executable, *arguments("build", -1), measured=False)
            initial = {name: [] for name in commands}
            for sample in range(args.samples):
                for name in list(commands)[::1 if sample%2 == 0 else -1]:
                    executable, arguments = commands[name]
                    initial[name].append(run(executable, *arguments("query", -1)))
            rounds = []
            for sample in range(args.samples):
                row = {"round": sample+1, "total_facts": n+(sample+1)*delta}
                for name in list(commands)[::1 if sample%2 == 0 else -1]:
                    executable, arguments = commands[name]
                    row[name] = {"append": run(executable, *arguments("append", sample)),
                                 "reopen": run(executable, *arguments("query", sample))}
                rounds.append(row)
            report["sizes"][str(n)] = {
                "delta_per_round": delta, "initial": initial, "growth_rounds": rounds,
                "summary": {name: {
                    "initial_first_answer": aggregate([row["process_to_ready_ms"] for row in initial[name]]),
                    "growing_reopen_verified": aggregate([row[name]["reopen"]["process_to_ready_ms"] for row in rounds]),
                    "update_commit": aggregate([row[name]["append"]["update_commit_ms"] for row in rounds]),
                } for name in commands},
            }
            args.output.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
            print("completed", n, json.dumps(report["sizes"][str(n)]["summary"]), flush=True)
    after = {name: hashlib.sha256((ROOT/"runtime"/name).read_bytes()).hexdigest() for name in names}
    if after != report["source_sha256"]:
        raise RuntimeError("runtime source changed during measurement; rerun")
    report["source_stable"] = True
    args.output.write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")


if __name__ == "__main__":
    main()
