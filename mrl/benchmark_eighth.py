"""Measure changed list<f32> construction and kernels, including startup."""
import ctypes
import json
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).parent
LENGTH, SAMPLES = 4096, 15


def python_case(seed):
    left = [float((i + seed) % 97) / 97.0 for i in range(LENGTH)]
    right = [float((i * 3 + seed) % 89) / 89.0 for i in range(LENGTH)]
    return sum(left) + sum(a * b for a, b in zip(left, right)) + sum(a * a for a in left) ** .5


def summary(values):
    values = sorted(values)
    return {"median_ns": statistics.median(values), "p95_ns": values[(len(values) * 95 + 99) // 100 - 1]}


def main():
    from mrl.toolchain import build_c, build_shared, build_identity
    header = (ROOT / "runtime" / "value_runtime.h").read_text(encoding="utf-8")
    source_text = f'''#include <stdio.h>
#include <stdlib.h>
static void mrl_runtime_fail(const char *message) {{ fputs(message, stderr); exit(2); }}
{header}
float bench(int seed) {{
  MrlList *a = mrl_list_new_f32({LENGTH}), *b = mrl_list_new_f32({LENGTH});
  for (int i = 0; i < {LENGTH}; ++i) {{ float x=(float)((i+seed)%97)/97.0f, y=(float)((i*3+seed)%89)/89.0f; mrl_list_push(a,&x); mrl_list_push(b,&y); }}
  float result=mrl_f32_sum(a)+mrl_f32_dot(a,b)+mrl_f32_norm(a); mrl_list_release(a); mrl_list_release(b); return result;
}}
size_t bench_list_size(void) {{ return sizeof(MrlList); }}
int main(int argc, char **argv) {{ printf("%.9g\\n", (double)bench(argc > 1 ? atoi(argv[1]) : 0)); return 0; }}'''
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder); source = root / "bench.c"; exe = source.with_suffix(".exe"); shared = root / "bench.dll"; source.write_text(source_text, encoding="utf-8")
        started = time.perf_counter_ns(); build_c(source, exe); native_build_ns = time.perf_counter_ns() - started
        started = time.perf_counter_ns(); build_shared(source, shared); shared_build_ns = time.perf_counter_ns() - started
        identity = build_identity(source, optimization="release")
        native_whole, python_whole = [], []
        for seed in range(SAMPLES):
            started = time.perf_counter_ns(); native = float(subprocess.check_output([str(exe), str(seed)], text=True)); native_whole.append(time.perf_counter_ns() - started)
            child = "import sys; n=4096;s=int(sys.argv[1]);a=[((i+s)%97)/97.0 for i in range(n)];b=[((i*3+s)%89)/89.0 for i in range(n)];print(sum(a)+sum(x*y for x,y in zip(a,b))+sum(x*x for x in a)**.5)"
            started = time.perf_counter_ns(); reference = float(subprocess.check_output([sys.executable, "-c", child, str(seed)], text=True)); python_whole.append(time.perf_counter_ns() - started)
            if abs(native - reference) > 0.02: raise AssertionError((seed, native, reference))
        started = time.perf_counter_ns(); library = ctypes.CDLL(str(shared)); native_load_ns = time.perf_counter_ns() - started
        library.bench.argtypes = [ctypes.c_int]; library.bench.restype = ctypes.c_float
        library.bench_list_size.restype = ctypes.c_size_t; list_size = library.bench_list_size()
        native_resident, python_resident = [], []
        for seed in range(SAMPLES):
            started = time.perf_counter_ns(); native = library.bench(seed); native_resident.append(time.perf_counter_ns() - started)
            started = time.perf_counter_ns(); reference = python_case(seed); python_resident.append(time.perf_counter_ns() - started)
            if abs(native - reference) > 0.02: raise AssertionError((seed, native, reference))
        if sys.platform == "win32":
            free_library = ctypes.WinDLL("kernel32", use_last_error=True).FreeLibrary
            free_library.argtypes, free_library.restype = [ctypes.c_void_p], ctypes.c_bool
            free_library(ctypes.c_void_p(library._handle))
        del library
    print(json.dumps({"schema": 1, "workload": "construct two changed list<f32> values, then sum+dot+norm and return the result", "numeric_reference": "Python uses f64 accumulation; each full result is accepted within 0.02 of native f32", "length": LENGTH, "samples": SAMPLES,
                      "build": {"native_executable_ns": native_build_ns, "native_shared_ns": shared_build_ns, "shared_load_ns": native_load_ns, "identity": identity},
                      "whole_process": {"native": summary(native_whole), "python": summary(python_whole), "raw_ns": {"native": native_whole, "python": python_whole}}, "resident_compute": {"native_ctypes": summary(native_resident), "python": summary(python_resident), "raw_ns": {"native_ctypes": native_resident, "python": python_resident}},
                      "native_list_storage_bytes": 2 * (LENGTH * 4 + list_size)}, indent=2))


if __name__ == "__main__": main()
