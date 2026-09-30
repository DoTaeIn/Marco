"""Direct native knowledge admission benchmark; no Python is in the native timed loop."""
import argparse, hashlib, json, math, statistics, subprocess, sys, tempfile, time
from pathlib import Path

if str(Path(__file__).resolve().parents[1]) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mrl import oracle, toolchain

ROOT = Path(__file__).parent


def _summary(values):
    values = sorted(values)
    return {"p50_ns": statistics.median(values), "p95_ns": values[math.ceil(.95 * len(values)) - 1],
            "samples_ns": values, "sample_count": len(values), "p95_method": "nearest-rank"}


def _source():
    store = (ROOT / "runtime" / "knowledge_store.h").read_text(encoding="utf-8")
    engine = (ROOT / "runtime" / "knowledge_engine.h").read_text(encoding="utf-8")
    return r'''#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#ifdef _WIN32
#include <windows.h>
#include <psapi.h>
#endif
'''+store+engine+r'''
static uint64_t ticks(void){
#ifdef _WIN32
 LARGE_INTEGER n,f;QueryPerformanceFrequency(&f);QueryPerformanceCounter(&n);return (uint64_t)(n.QuadPart*1000000000ULL/f.QuadPart);
#else
 return (uint64_t)clock()*1000000000ULL/CLOCKS_PER_SEC;
#endif
}
static size_t rss(void){
#ifdef _WIN32
 PROCESS_MEMORY_COUNTERS x={sizeof(x)};return GetProcessMemoryInfo(GetCurrentProcess(),&x,sizeof(x))?x.PeakWorkingSetSize:0;
#else
 return 0;
#endif
}
int main(int argc,char**argv){size_t n=argc==2?(size_t)strtoull(argv[1],0,10):0;MrlKnowledgeStore*s,*old;MrlKnowledgeEngine e;MrlKnowledgeFact f={0},oldrow;MrlKnowledgeSymbol p,p2;uint64_t a,b,ad,ap,rm,co,q;size_t budget;
 if(!n||n>(SIZE_MAX-16777216)/192)return 2;budget=n*192+16777216;s=mrl_knowledge_store_new(budget);if(!s||!mrl_knowledge_store_intern(s,"edge",&p)||!mrl_knowledge_store_intern(s,"corrected",&p2)||!mrl_knowledge_engine_init(&e,NULL,0,UINT64_MAX))return 3;
 a=ticks();for(size_t i=0;i<n;i++){f=(MrlKnowledgeFact){.subject=(uint32_t)(i+100),.predicate=p,.object=(uint32_t)(i+200)};if(!mrl_knowledge_store_append(s,f,1)||!mrl_knowledge_assert(&e,(uint64_t)i+1,f.subject,f.predicate,f.object))return 4;}b=ticks();if(!mrl_knowledge_close(&e))return 5;ad=ticks()-a;uint64_t first_close=ticks()-b;
 old=mrl_knowledge_store_snapshot(s);if(!old)return 6;a=ticks();f=(MrlKnowledgeFact){.subject=(uint32_t)(n+100),.predicate=p,.object=(uint32_t)(n+200)};if(!mrl_knowledge_store_append(s,f,1)||!mrl_knowledge_assert(&e,(uint64_t)n+1,f.subject,f.predicate,f.object)||!mrl_knowledge_close(&e))return 7;ap=ticks()-a;
 a=ticks();if(!mrl_knowledge_store_remove(s,(uint32_t)(n/2+1))||!mrl_knowledge_remove(&e,(uint64_t)(n/2+1))||!mrl_knowledge_close(&e))return 8;rm=ticks()-a;
 a=ticks();f=(MrlKnowledgeFact){.subject=(uint32_t)(n/3+100),.predicate=p2,.object=(uint32_t)(n/3+200)};if(!mrl_knowledge_store_correct(s,(uint32_t)(n/3+1),f)||!mrl_knowledge_correct(&e,(uint64_t)(n/3+1),f.subject,f.predicate,f.object)||!mrl_knowledge_close(&e))return 9;co=ticks()-a;
 a=ticks();if(mrl_knowledge_query(&e,(int32_t)(n-1+100),p,(int32_t)(n-1+200),NULL,NULL)!=1) return 10;q=ticks()-a;
 if(!mrl_knowledge_store_get_fact(old,(uint32_t)(n/2+1),&oldrow)||oldrow.predicate!=p||e.live_count!=n)return 11;
 printf("{\"admission_ns\":%llu,\"first_close_ns\":%llu,\"append_ns\":%llu,\"remove_ns\":%llu,\"correct_ns\":%llu,\"query_ns\":%llu,\"store_peak_bytes\":%llu,\"store_used_bytes\":%llu,\"engine_bytes\":%llu,\"engine_rows\":%llu,\"engine_live\":%llu,\"os_peak_rss_bytes\":%llu}\n",(unsigned long long)ad,(unsigned long long)first_close,(unsigned long long)ap,(unsigned long long)rm,(unsigned long long)co,(unsigned long long)q,(unsigned long long)mrl_knowledge_store_peak(s),(unsigned long long)mrl_knowledge_store_bytes(s),(unsigned long long)e.bytes,(unsigned long long)e.count,(unsigned long long)e.live_count,(unsigned long long)rss());
 mrl_knowledge_store_release(old);mrl_knowledge_store_release(s);mrl_knowledge_engine_free(&e);return 0;}
'''


def _native(exe, size):
    run = subprocess.run([str(exe), str(size)], text=True, capture_output=True, check=False, timeout=180)
    if run.returncode:
        raise RuntimeError("native %d failed (%d): %s" % (size, run.returncode, run.stderr.strip()))
    return json.loads(run.stdout)


def _facts(size, corrected=False, appended=False, removed=False):
    rows = [{"id": str(i), "triple": ["s%d" % i, "edge", "o%d" % i], "evidence": {}} for i in range(size)]
    if removed: rows.pop(size // 2)
    if corrected:
        i = size // 3
        rows = [{"id": str(i), "triple": ["s%d" % i, "corrected", "o%d" % i], "evidence": {}} if row["id"] == str(i) else row for row in rows]
    if appended: rows.append({"id": str(size), "triple": ["s%d" % size, "edge", "o%d" % size], "evidence": {}})
    return rows


def _python(size, samples):
    timings = {"admission_ns": [], "append_ns": [], "remove_ns": [], "correct_ns": []}
    for _ in range(samples):
        for name, kwargs in (("admission_ns", {}), ("append_ns", {"appended": True}), ("remove_ns", {"appended": True, "removed": True}), ("correct_ns", {"appended": True, "removed": True, "corrected": True})):
            start = time.perf_counter_ns(); result = oracle.evaluate({"operation": "closure", "facts": _facts(size, **kwargs), "rules": [], "options": {"limit": size + 1}}); timings[name].append(time.perf_counter_ns() - start)
            if len(result["known"]["$tuple_map"]) != size + (1 if kwargs.get("appended") else 0) - (1 if kwargs.get("removed") else 0): raise AssertionError("oracle count")
    return {name: _summary(values) for name, values in timings.items()}


def run(sizes=(10_000, 100_000, 1_000_000), samples=5, python_max=10_000):
    if samples < 3: raise ValueError("samples must be at least 3")
    source = _source(); hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ("runtime/knowledge_store.h", "runtime/knowledge_engine.h", "oracle.py")}
    with tempfile.TemporaryDirectory(prefix="mrl-ninth-") as directory:
        c, exe = Path(directory) / "ninth.c", Path(directory) / "ninth.exe"; c.write_text(source, encoding="utf-8")
        try: toolchain.build_c(c, exe)
        except subprocess.CalledProcessError as error: raise RuntimeError(error.stderr.decode(errors="replace")) from error
        report = {"workload": "C11 direct-header native pipeline: intern predicate symbols, append store rows and engine assertions, retain a store snapshot, append/remove/correct, then exact indexed query. It does not exercise source parsing, JSON ingestion, persistence/restart, or cold startup.", "samples": samples, "source_sha256": hashes, "sizes": {}}
        for size in sizes:
            rows = [_native(exe, size) for _ in range(samples)]
            native = {key: _summary([row[key] for row in rows]) for key in ("admission_ns", "first_close_ns", "append_ns", "remove_ns", "correct_ns", "query_ns")}
            native["internal_peak_bytes"] = max(row["store_peak_bytes"] + row["engine_bytes"] for row in rows)
            native["os_peak_rss_bytes"] = max(row["os_peak_rss_bytes"] for row in rows)
            native["final_engine_rows"] = rows[-1]["engine_rows"]; native["final_engine_live"] = rows[-1]["engine_live"]
            entry = {"native": native, "snapshot": "one store snapshot retained across append/remove/correct; engine has no snapshot API"}
            entry["python_oracle"] = _python(size, samples) if size <= python_max else {"status": "excluded", "reason": "oracle has no native store/snapshot/indexed-query equivalent and size exceeds --python-max"}
            report["sizes"][str(size)] = entry
    report["boundaries"] = "Native timing excludes C compilation, source/JSON parsing, persistence/restart, cold process startup, and JSON formatting. Python comparison uses unchanged mrl.oracle closure with no rules; it excludes store persistence, snapshots, and targeted query because the oracle has no equivalent API."
    return report


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--sizes", default="10000,100000,1000000"); parser.add_argument("--samples", type=int, default=5); parser.add_argument("--python-max", type=int, default=10000); parser.add_argument("--output", type=Path)
    args = parser.parse_args(); report = run(tuple(int(x) for x in args.sizes.split(",") if x), args.samples, args.python_max); text = json.dumps(report, indent=2)+"\n"
    if args.output: args.output.write_text(text, encoding="utf-8")
    else: print(text)


if __name__ == "__main__": main()
