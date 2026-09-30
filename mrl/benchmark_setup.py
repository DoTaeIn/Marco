"""Reproduce the bounded specialized-plan construction benchmark."""
import argparse
import hashlib
import json
import platform
import statistics
import sys
import time
from pathlib import Path

from mrl import graph_plan, native_graph, toolchain


CASE = {"operation": "closure", "facts": [
    {"id": "seed", "triple": ["a", "p", "a"], "evidence": {}}],
    "rules": [{"id": "repeat", "body": [["?node", "p", "?node"]],
               "head": ["?node", "q", "?node"]}]}


def _hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _sample(specialized):
    start = time.perf_counter_ns()
    native_graph.PreparedGraph(CASE, specialized=specialized)
    return (time.perf_counter_ns() - start) / 1_000_000


def _samples(specialized, count, clear):
    values = []
    for _ in range(count):
        clear()
        values.append(_sample(specialized))
    return values


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--batches", type=int, default=7)
    parser.add_argument("--repeats", type=int, default=50)
    parser.add_argument("--output", type=Path,
                        default=Path(__file__).with_name("docs") / "FIFTH_DELIVERY_SETUP.json")
    args = parser.parse_args()
    if args.batches < 1 or args.repeats < 1:
        raise SystemExit("batches and repeats must be positive")
    if not native_graph.available():
        raise SystemExit("no complete local C11 toolchain")

    # Persistent artifacts are retained; process-local loader and plan caches start empty.
    native_graph._load_library.cache_clear()
    native_graph._load_path.cache_clear()
    graph_plan._compiled_plan.cache_clear()
    initial = {"generic": _sample(False), "specialized": _sample(True)}
    # Populate both paths before controlled persistent-cache lookup samples.
    native_graph.PreparedGraph(CASE)
    native_graph.PreparedGraph(CASE, specialized=True)
    generic_lookup = _samples(False, args.batches, native_graph._load_library.cache_clear)
    specialized_lookup = _samples(True, args.batches, graph_plan._compiled_plan.cache_clear)
    warm = {"generic": [], "specialized": []}
    for batch in range(args.batches):
        order = (False, True) if batch % 2 == 0 else (True, False)
        for specialized in order:
            name = "specialized" if specialized else "generic"
            warm[name].append(sum(_sample(specialized) for _ in range(args.repeats)) / args.repeats)
    result = {"schema": 1, "unit": "ms", "workload": CASE,
              "method": "PreparedGraph construction; ordered batches, full validation and plan emission retained",
              "source_hashes": {"graph_plan.py": _hash(graph_plan.__file__),
                                "native_graph.py": _hash(native_graph.__file__),
                                "native_graph.c": _hash(graph_plan._SOURCE),
                                "toolchain.py": _hash(toolchain.__file__)},
              "environment": {"python": sys.version, "platform": platform.platform(),
                              "compiler": toolchain.find_compiler()[0]},
              "cache_states": [
                  {"name": "process_initial_persistent_libraries", "samples": initial,
                   "reset": "clear generic loader, ctypes loader and plan cache before the ordered generic then specialized samples"},
                  {"name": "generic_persistent_library_lookup", "samples": generic_lookup,
                   "reset": "clear _load_library before each sample; persistent DLL and ctypes handle retained"},
                  {"name": "specialized_plan_cache_miss", "samples": specialized_lookup,
                   "reset": "clear _compiled_plan before each sample; persistent DLL and ctypes handle retained"},
                  {"name": "process_warm_ordered_batches", "repeats_per_batch": args.repeats,
                   "orders": ["generic,specialized" if i % 2 == 0 else "specialized,generic" for i in range(args.batches)],
                   "samples": warm}],
              "median_ms": {name: statistics.median(values) for name, values in
                            {"generic_persistent_library_lookup": generic_lookup,
                             "specialized_plan_cache_miss": specialized_lookup,
                             "generic_process_warm": warm["generic"],
                             "specialized_process_warm": warm["specialized"]}.items()}}
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(args.output)


if __name__ == "__main__":
    main()
