"""Compare an equivalent repeated source-level Dijkstra query with a Python heap search."""
import argparse
import hashlib
import heapq
import json
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import time

from mrl import toolchain
from mrl.frontend import compile_source
from mrl.c_backend import emit_c

ROOT = Path(__file__).parent
EDGES = ((0, 2, 9), (0, 1, 2), (1, 2, 2), (0, 2, 7), (1, 0, 0))


# Prepare adjacency once, as the native graph is also constructed outside its query loop.
NEIGHBORS = {node: [(target, distance) for _, (source, target, distance) in
                   sorted(enumerate(EDGES), key=lambda row: (row[1][1], row[0]))
                   if source == node] for node in range(3)}


def python_query():
    pending = [(0, 0, 0, (0,))]
    serial = 1
    while pending:
        cost, depth, _, path = heapq.heappop(pending)
        if path[-1] == 2:
            return depth, cost
        for target, distance in NEIGHBORS[path[-1]]:
            if target not in path:
                heapq.heappush(pending, (cost + distance, depth + 1, serial, (*path, target)))
                serial += 1
    raise AssertionError("no path")


def source_program(repeats):
    additions = " ".join(f"g.add(n{a}, n{b}, R.Link, Edge(distance = {cost}))"
                         for a, b, cost in EDGES)
    return """
struct Node { number: si }
struct Edge { distance: si }
relation R { Link { polarity: positive evidence: none traverse: forward } }
graph g { node: Node relation: R edge: Edge }
fn main() -> si {
    n0 = g.add(Node(number = 0))
    n1 = g.add(Node(number = 1))
    n2 = g.add(Node(number = 2))
""" + additions + """
    total = 0
    for (i in 0..""" + str(repeats) + """) {
        result = g.find(n0, n2) { method: dijkstra cost: edge.distance }
        match (result) {
            Ok(path) { total := total + path.len + path.cost }
            Err(error) { print(error) return -1 }
        }
    }
    return total
}
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeats", type=int, default=20000)
    parser.add_argument("--batches", type=int, default=7)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/SIXTH_DELIVERY_SEARCH_BENCHMARK.json")
    args = parser.parse_args()
    if not 1 <= args.repeats <= 1000000 or args.batches < 1:
        raise SystemExit("repeats must be 1..1000000 and batches positive")
    output = ROOT / ".build"
    output.mkdir(exist_ok=True)
    source = source_program(args.repeats)
    source_file, c_file, exe = [output / ("search_benchmark" + suffix) for suffix in (".mrl", ".c", ".exe")]
    source_file.write_text(source, encoding="utf-8")
    emitted = emit_c(compile_source(source))
    wrapper = r"""
#undef main
#ifdef _WIN32
#include <windows.h>
static double bench_now(void) {
    LARGE_INTEGER count, frequency;
    QueryPerformanceCounter(&count);
    QueryPerformanceFrequency(&frequency);
    return (double)count.QuadPart / (double)frequency.QuadPart;
}
#else
#include <time.h>
static double bench_now(void) {
    struct timespec stamp;
    timespec_get(&stamp, TIME_UTC);
    return (double)stamp.tv_sec + (double)stamp.tv_nsec / 1e9;
}
#endif
int main(void) {
    double started = bench_now();
    int status = mrl_benchmark_program_main();
    fprintf(stderr, "%.17g\n", bench_now() - started);
    return status;
}
"""
    c_file.write_text("#define main mrl_benchmark_program_main\n" + emitted + wrapper, encoding="utf-8")
    started = time.perf_counter_ns()
    toolchain.build_c(c_file, exe)
    build_ms = (time.perf_counter_ns() - started) / 1e6
    assert python_query() == (2, 4)
    expected = 6 * args.repeats

    def native():
        run = subprocess.run([str(exe.resolve())], capture_output=True, text=True,
                             timeout=60, check=True)
        assert run.stdout == str(expected) + "\n"
        duration = float(run.stderr.strip())
        assert duration > 0
        return duration

    def python():
        result = 0
        for _ in range(args.repeats):
            length, cost = python_query()
            result += length + cost
        assert result == expected
        return result

    native()
    python()
    samples = {"native_process": [], "native_execution": [], "python_loop": []}
    orders = []
    for batch in range(args.batches):
        order = ("native_process", "python_loop") if batch % 2 == 0 else ("python_loop", "native_process")
        orders.append(order)
        for name in order:
            started = time.perf_counter_ns()
            duration = {"native_process": native, "python_loop": python}[name]()
            if name == "native_process":
                samples["native_execution"].append(duration * 1e6 / args.repeats)
            samples[name].append((time.perf_counter_ns() - started) / 1000 / args.repeats)
    medians = {name: statistics.median(values) for name, values in samples.items()}
    result = {
        "schema": 1, "unit": "us_per_query", "repeats": args.repeats, "batches": args.batches,
        "workload": {"nodes": 3, "edges": EDGES, "source": 0, "target": 2,
                     "method": "dijkstra", "expected_length": 2, "expected_cost": 4,
                     "checksum": expected},
        "method": "Alternating batches; native_execution measures generated program inside the executable (graph construction and checksum output amortized), native_process also includes process startup; Python uses prebuilt adjacency, heap search/path tuples and consumes length/cost; compile excluded; no Horn memoization. Windows QueryPerformanceCounter; other platforms C11 timespec_get.",
        "orders": orders, "samples": samples, "median_us": medians,
        "python_over_native_ratio": medians["python_loop"] / medians["native_execution"],
        "build_ms_single_sample": build_ms, "executable_bytes": exe.stat().st_size,
        "environment": {"python": sys.version, "platform": platform.platform(),
                        "compiler": toolchain.find_compiler()[0]},
        "sha256": {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                   for path in (Path(__file__), ROOT / "frontend.py", ROOT / "c_backend.py",
                                ROOT / "runtime/graph_runtime.h", source_file)},
    }
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"median_us": medians, "python_over_native_ratio": result["python_over_native_ratio"]}))


if __name__ == "__main__":
    main()
