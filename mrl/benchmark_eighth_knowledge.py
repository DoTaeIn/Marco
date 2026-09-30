"""Resident native evaluation versus exact positive-append incremental closure."""
import ctypes, hashlib, json, math, statistics, subprocess, sys, tempfile, time
from pathlib import Path
from mrl.toolchain import build_shared, build_identity
ROOT=Path(__file__).parent
SAMPLES=15

def summary(values):
    return {"median_ns":statistics.median(values),"p95_ns":sorted(values)[math.ceil(.95*len(values))-1],"raw_ns":values}

def main():
    native=(ROOT/'runtime/native_graph.c').read_text(encoding='utf-8')
    incremental=(ROOT/'runtime/horn_incremental.h').read_text(encoding='utf-8')
    c_source='#define MRL_GRAPH_SHARED\n'+native+'\n'+incremental+r'''
typedef struct {GraphState*g;size_t bytes,output_bytes,written[2];uint8_t*out[2];MrlHornIncremental inc;int32_t next;} Benchmark;
MRL_GRAPH_API void*bench_new(int32_t n,int32_t capacity){
 Benchmark*b=calloc(1,sizeof(*b));if(!b)return NULL;b->bytes=mrl_graph_state_size_for(capacity);b->g=calloc(1,b->bytes);b->output_bytes=4*(5+(size_t)capacity*7);b->out[0]=malloc(b->output_bytes);b->out[1]=malloc(b->output_bytes);if(!b->g||!b->out[0]||!b->out[1])return NULL;
 size_t words=7+(size_t)n*5+6;int32_t*packet=calloc(words,4);if(!packet)return NULL;int32_t h[7]={MAGIC,CLOSURE,n,1,capacity,32,1000000};memcpy(packet,h,sizeof(h));for(int32_t i=0;i<n;i++){int32_t row[5]={i,10,20,1,1};memcpy(packet+7+i*5,row,sizeof(row));}int32_t rules[6]={-1,10,-2,-1,11,-2};memcpy(packet+7+n*5,rules,sizeof(rules));int status=mrl_graph_prepare((uint8_t*)packet,words*4,b->g,b->bytes);free(packet);if(status)return NULL;b->next=n;return b;
}
MRL_GRAPH_API int bench_append(Benchmark*b,int32_t n){int32_t*p=calloc(1+(size_t)n*5,4);if(!p)return -1;p[0]=n;for(int32_t i=0;i<n;i++){int32_t row[5]={b->next+i,10,20,1,1};memcpy(p+1+i*5,row,sizeof(row));}int status=mrl_graph_append(b->g,b->bytes,(uint8_t*)p,(1+(size_t)n*5)*4);free(p);if(!status)b->next+=n;return status;}
MRL_GRAPH_API int bench_eval(Benchmark*b,int32_t delta){if(delta){Context ctx={0};ctx.writer=(Writer){b->out[1],b->output_bytes,0,0};if(!mrl_horn_incremental_eval(&b->inc,b->g,&ctx))return -1;b->written[1]=ctx.writer.pos;return 0;}return mrl_graph_evaluate(b->g,b->bytes,b->out[0],b->output_bytes,&b->written[0]);}
MRL_GRAPH_API int bench_equal(Benchmark*b){return b->written[0]==b->written[1]&&!memcmp(b->out[0],b->out[1],b->written[0])&&((int32_t*)b->out[0])[0]==OK&&((int32_t*)b->out[0])[4]==b->next*2;}
MRL_GRAPH_API uint64_t bench_work(Benchmark*b,int32_t reused){return reused?b->inc.reused:b->inc.new_matches;}
MRL_GRAPH_API void bench_free(Benchmark*b){if(b){mrl_horn_incremental_free(&b->inc);free(b->g);free(b->out[0]);free(b->out[1]);free(b);}}
'''
    with tempfile.TemporaryDirectory(prefix='mrl-delta-bench-') as folder:
        c=Path(folder)/'bench.c'; dll=c.with_suffix('.dll' if sys.platform=='win32' else '.so');c.write_text(c_source,encoding='utf-8')
        before=time.perf_counter_ns();build_shared(c,dll);build_ns=time.perf_counter_ns()-before
        identity=build_identity(c);before=time.perf_counter_ns();lib=ctypes.CDLL(str(dll));load_ns=time.perf_counter_ns()-before
        ptr=ctypes.c_void_p;i32=ctypes.c_int32
        lib.bench_new.argtypes=[i32,i32];lib.bench_new.restype=ptr
        for name in ('bench_append','bench_eval'):getattr(lib,name).argtypes=[ptr,i32];getattr(lib,name).restype=i32
        lib.bench_equal.argtypes=[ptr];lib.bench_equal.restype=i32
        lib.bench_work.argtypes=[ptr,i32];lib.bench_work.restype=ctypes.c_uint64
        lib.bench_free.argtypes=[ptr];lib.bench_free.restype=None
        rows=[]
        for n in (64,512,4096):
            batch=max(1,n//64);capacity=2*(n+batch*SAMPLES);handle=lib.bench_new(n,capacity)
            if not handle:raise AssertionError('benchmark prepare')
            cold=[]
            for mode in (0,1):
                before=time.perf_counter_ns();status=lib.bench_eval(handle,mode);cold.append(time.perf_counter_ns()-before)
                if status:raise AssertionError(('cold',n,mode,status))
            if not lib.bench_equal(handle):raise AssertionError(('cold parity',n))
            full=[];delta=[];work=[]
            for iteration in range(SAMPLES):
                if lib.bench_append(handle,batch):raise AssertionError('append')
                timings={}
                for mode in (iteration%2,1-iteration%2):
                    before=time.perf_counter_ns();status=lib.bench_eval(handle,mode);timings[mode]=time.perf_counter_ns()-before
                    if status:raise AssertionError(('eval',n,mode,status))
                if not lib.bench_equal(handle):raise AssertionError(('changed parity',n,iteration))
                full.append(timings[0]);delta.append(timings[1]);work.append({'new_rule_evaluations':lib.bench_work(handle,0),'reused_consequences':lib.bench_work(handle,1)})
            rows.append({'initial_inputs':n,'append_batch':batch,'final_inputs':n+batch*SAMPLES,'capacity':capacity,'cold_full_ns':cold[0],'cold_incremental_ns':cold[1],'changed_full':summary(full),'changed_incremental':summary(delta),'work':work,'full_wire_equal_every_query':True})
            lib.bench_free(handle)
        if sys.platform=='win32':
            release=ctypes.WinDLL('kernel32').FreeLibrary;release.argtypes=[ptr];release.restype=ctypes.c_int;release(lib._handle)
        del lib
    report={'schema':2,'scope':'resident native closure kernel; positive appended facts, one nonrecursive rule; includes ctypes call and complete wire result, excludes source compilation/file parsing/string interning/process startup','samples_per_size':SAMPLES,'timing':'perf_counter_ns, alternating evaluation order','build_ns':build_ns,'load_ns':load_ns,'identity':identity,'source_sha256':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (ROOT/'runtime/native_graph.c',ROOT/'runtime/horn_incremental.h')},'rows':rows}
    (ROOT/'docs/EIGHTH_KNOWLEDGE_BENCHMARK.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    for row in rows:print(row['initial_inputs'],row['changed_full']['median_ns'],row['changed_incremental']['median_ns'],row['work'][-1])

if __name__=='__main__':main()
