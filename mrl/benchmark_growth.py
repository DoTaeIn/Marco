"""Parity-gated growth measurements for the bounded resident Horn graph."""
from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).parents[1]
SNAPSHOT = ROOT / ".build" / "growth-baseline-snapshot"
SIZES = (1, 4, 8, 16)


def _case(operation, seeds, derived_per_seed=3, capacity=64):
    facts = [{"id": "seed:%d" % index,
              "triple": ["subject:%d" % index, "p0", "object:%d" % index],
              "evidence": {}} for index in range(seeds)]
    rules = [{"id": "p%d_to_p%d" % (index, index + 1),
              "body": [["?subject", "p%d" % index, "?object"]],
              "head": ["?subject", "p%d" % (index + 1), "?object"]}
             for index in range(derived_per_seed)]
    case = {"operation": operation, "facts": facts, "rules": rules,
            "options": {"limit": capacity}}
    if operation == "closure_with_provenance":
        case["options"].update(proof_limit=8, search_limit=capacity * 32)
    return case


def _oracle_module():
    """Load the frozen oracle file directly, never through a benchmarked package."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    spec = importlib.util.spec_from_file_location("growth_frozen_oracle", ROOT / "mrl" / "oracle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _runtime(snapshot):
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    if snapshot:
        frozen = SNAPSHOT / "mrl"
        if not (frozen / "native_graph.py").is_file():
            raise RuntimeError("growth baseline snapshot is missing")
        for name in tuple(sys.modules):
            if name == "mrl" or name.startswith("mrl."):
                del sys.modules[name]
        sys.path.insert(0, str(SNAPSHOT))
    native = importlib.import_module("mrl.native_graph")
    toolchain = importlib.import_module("mrl.toolchain")
    if snapshot:
        # Reuse the existing on-disk DLL cache while the imported sources remain frozen.
        toolchain._ROOT = ROOT / "mrl"
        toolchain._TOOLS = toolchain._ROOT / ".tools"
    return native, toolchain


def _canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _digest(value):
    payload = _canonical(value)
    return {"sha256": hashlib.sha256(payload).hexdigest(), "bytes": len(payload)}


def _fact_count(result):
    rows = result.get("facts", result.get("known", {}))
    return len(rows.get("$tuple_map", rows))


def _checked_expected(result, expected_total):
    if "error" in result or _fact_count(result) != expected_total or ("complete" in result and not result["complete"]):
        raise AssertionError("controlled growth case did not reach its declared complete fact count")
    return result


def _prepared(native, case, capacity):
    return native.PreparedGraph(case) if capacity == 64 else native.PreparedGraph(case, capacity=capacity)


def _summary(samples):
    ordered = sorted(samples)
    return {"p50_ns": statistics.median(ordered),
            "p95_ns": ordered[math.ceil(len(ordered) * .95) - 1],
            "samples_ns": samples,
            "sample_count": len(samples),
            "p95_method": "nearest-rank per-request sample"}


def _peak_working_set_bytes():
    if os.name != "nt":
        return None
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong),
                    ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                    ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                    ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                    ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t),
                    ("PrivateUsage", ctypes.c_size_t)]
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    kernel32, psapi = ctypes.WinDLL("kernel32"), ctypes.WinDLL("psapi")
    kernel32.GetCurrentProcess.restype = ctypes.c_void_p
    psapi.GetProcessMemoryInfo.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong)
    psapi.GetProcessMemoryInfo.restype = ctypes.c_int
    if not psapi.GetProcessMemoryInfo(kernel32.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    return counters.PeakWorkingSetSize


def _first_answer(native, oracle, case, samples, capacity):
    expected = _checked_expected(oracle.evaluate(case), len(case["facts"]) * (len(case["rules"]) + 1))
    probe = _prepared(native, case, capacity)
    if probe.evaluate() != expected:
        raise AssertionError("first-answer parity")
    times = []
    for _ in range(samples):
        start = time.perf_counter_ns()
        actual = _prepared(native, case, capacity).evaluate()
        times.append(time.perf_counter_ns() - start)
        if actual != expected:
            raise AssertionError("first-answer nondeterminism")
    return {**_summary(times), "parity": True, "result_fact_count": _fact_count(expected),
            "complete": expected.get("complete", True), "returned": _digest(expected)}


def _warm_answer(native, oracle, case, samples, capacity):
    expected = _checked_expected(oracle.evaluate(case), len(case["facts"]) * (len(case["rules"]) + 1))
    graph = _prepared(native, case, capacity)
    if graph.evaluate() != expected:
        raise AssertionError("warm-answer parity")
    native_times, python_times = [], []
    for index in range(samples):
        calls = (("native", graph.evaluate), ("python", lambda: oracle.evaluate(case)))
        if index % 2:
            calls = calls[::-1]
        for name, call in calls:
            start = time.perf_counter_ns(); actual = call(); elapsed = time.perf_counter_ns() - start
            (native_times if name == "native" else python_times).append(elapsed)
            if actual != expected:
                raise AssertionError("warm %s nondeterminism" % name)
    return {"parity": True, "result_fact_count": _fact_count(expected), "complete": expected.get("complete", True),
            "native_resident": _summary(native_times), "python_oracle": _summary(python_times),
            "returned": _digest(expected), "result_cache": "none; every sample evaluates the full input"}


def _append_answer(native, oracle, operation, seeds, repetitions, derived_per_seed, capacity):
    times = [{"native": [], "python": []} for _ in range(seeds)]
    latest = None
    for _ in range(repetitions):
        native_case, python_case = _case(operation, 0, derived_per_seed, capacity), _case(operation, 0, derived_per_seed, capacity)
        graph = _prepared(native, native_case, capacity)
        for index in range(seeds):
            template = [_case(operation, index + 1, derived_per_seed, capacity)["facts"][-1]]
            native_delta, python_delta = deepcopy(template), deepcopy(template)
            start = time.perf_counter_ns(); graph.append_facts(native_delta); actual = graph.evaluate()
            times[index]["native"].append(time.perf_counter_ns() - start)
            start = time.perf_counter_ns(); python_case["facts"].extend(python_delta); expected = oracle.evaluate(python_case)
            times[index]["python"].append(time.perf_counter_ns() - start)
            if actual != expected:
                raise AssertionError("append parity at seed %d" % index)
            latest = expected
    return {"parity": True, "delta_rows_each": 1, "sequence_repetitions": repetitions,
            "steps": [{"seed_count": index + 1, "native_append_evaluate": _summary(row["native"]),
                       "python_append_evaluate": _summary(row["python"]),
                       "result_fact_count": _fact_count(oracle.evaluate(_case(operation, index + 1, derived_per_seed, capacity))),
                       "returned": _digest(oracle.evaluate(_case(operation, index + 1, derived_per_seed, capacity)))}
                      for index, row in enumerate(times)],
            "latest_answer": _digest(latest), "result_cache": "none; each append changes resident input"}


def _append_endpoint(native, oracle, operation, seeds, repetitions, derived_per_seed, capacity):
    if seeds < 1:
        raise ValueError("endpoint needs at least one seed")
    native_times, python_times, latest = [], [], None
    for _ in range(repetitions):
        native_case = _case(operation, seeds - 1, derived_per_seed, capacity)
        python_case = deepcopy(native_case)
        graph = _prepared(native, native_case, capacity)
        template = [_case(operation, seeds, derived_per_seed, capacity)["facts"][-1]]
        native_delta, python_delta = deepcopy(template), deepcopy(template)
        start = time.perf_counter_ns(); graph.append_facts(native_delta); actual = graph.evaluate()
        native_times.append(time.perf_counter_ns() - start)
        start = time.perf_counter_ns(); python_case["facts"].extend(python_delta); expected = oracle.evaluate(python_case)
        python_times.append(time.perf_counter_ns() - start)
        if actual != expected:
            raise AssertionError("endpoint append parity")
        latest = expected
    return {"parity": True, "base_seed_count": seeds - 1, "final_seed_count": seeds,
            "sequence_repetitions": repetitions, "delta_rows": 1,
            "native_append_evaluate": _summary(native_times), "python_append_evaluate": _summary(python_times),
            "result_fact_count": _fact_count(latest), "complete": latest.get("complete", True),
            "latest_answer": _digest(latest), "result_cache": "none; every sample appends a new final input"}


def _denial_answer(native, oracle, operation, derived_per_seed, capacity):
    current = _case(operation, 1, derived_per_seed, capacity)
    graph = _prepared(native, current, capacity)
    before = graph.evaluate()
    denial = [{"id": "deny:p1", "triple": ["subject:0", "p1", "object:0"],
               "evidence": {}, "polarity": False}]
    start = time.perf_counter_ns(); graph.append_facts(deepcopy(denial)); actual = graph.evaluate(); elapsed = time.perf_counter_ns() - start
    current["facts"].extend(deepcopy(denial)); expected = oracle.evaluate(current)
    if actual != expected or actual == before:
        raise AssertionError("denial update parity")
    return {"parity": True, "native_append_evaluate_ns": elapsed,
            "first_answer": _digest(before), "latest_answer": _digest(actual), "delta_rows": 1}


def _capacity_refusal(native, capacity):
    base = {"operation": "closure", "facts": [
        {"id": "planned:%d" % index, "triple": ["cap:%d" % index, "p", "o"],
         "evidence": {}, "modality": "planned"} for index in range(capacity)], "rules": [], "options": {"limit": capacity}}
    graph = _prepared(native, base, capacity)
    before = graph.evaluate()
    try:
        graph.append_facts([{"id": "planned:%d" % capacity, "triple": ["cap:%d" % capacity, "p", "o"],
                             "evidence": {}, "modality": "planned"}])
    except ValueError as error:
        if str(error) != "native_capacity":
            raise AssertionError("unexpected capacity refusal: " + str(error))
        if graph.evaluate() != before:
            raise AssertionError("rejected capacity append changed state")
        return {"attempted_input_facts": capacity + 1, "accepted": False, "exception": str(error),
                "status": "expected_native_capacity_refusal", "state_unchanged": True}
    raise AssertionError("65th input fact was accepted")


def _worker(path, operation, seeds, snapshot, capacity, derived_per_seed):
    started = time.perf_counter_ns()
    native, _ = _runtime(snapshot)
    if path == "native":
        # A fresh worker must use a prebuilt disk DLL. Compilation is measured separately.
        native.toolchain.build_shared = lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("fresh worker compiled"))
        call = lambda: _prepared(native, _case(operation, seeds, derived_per_seed, capacity), capacity).evaluate()
    else:
        oracle = _oracle_module()
        call = lambda: oracle.evaluate(_case(operation, seeds, derived_per_seed, capacity))
    imported = time.perf_counter_ns()
    result = call()
    completed = time.perf_counter_ns()
    peak = _peak_working_set_bytes()
    responded = time.perf_counter_ns()
    return {"worker_runtime_import_ns": imported - started, "worker_operation_ns": completed - imported,
            "worker_first_response_ns": responded - started, "returned": _digest(result),
            "peak_working_set_bytes": peak}


def _fresh_process(operation, seeds, snapshot, samples, capacity, derived_per_seed):
    expected_result = _checked_expected(_oracle_module().evaluate(_case(operation, seeds, derived_per_seed, capacity)),
                                       seeds * (derived_per_seed + 1))
    expected = _digest(expected_result)
    paths = {"python_oracle": [], "native_resident": []}
    orders = []
    for index in range(samples):
        order = ("python_oracle", "native_resident") if index % 2 == 0 else ("native_resident", "python_oracle")
        orders.append(order)
        for name in order:
            command = [sys.executable, "-B", str(Path(__file__).resolve()), "--worker", name.split("_", 1)[0],
                       "--operation", operation, "--seeds", str(seeds), "--capacity", str(capacity),
                       "--derived-per-seed", str(derived_per_seed)]
            if snapshot:
                command.append("--snapshot")
            start = time.perf_counter_ns()
            run = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False, timeout=30)
            wall = time.perf_counter_ns() - start
            if run.returncode:
                raise AssertionError("fresh %s failed: %s" % (name, run.stderr.strip()))
            row = json.loads(run.stdout)
            if row["returned"] != expected:
                raise AssertionError("fresh %s parity" % name)
            paths[name].append({"controller_subprocess_wall_ns": wall, "worker_runtime_import_ns": row["worker_runtime_import_ns"],
                                "worker_operation_ns": row["worker_operation_ns"], "worker_first_response_ns": row["worker_first_response_ns"],
                                "peak_working_set_bytes": row["peak_working_set_bytes"]})
    def summarize(rows, key):
        value = _summary([row[key] for row in rows])
        value["peak_working_set_bytes"] = [row["peak_working_set_bytes"] for row in rows]
        return value
    return {"parity": True, "result_fact_count": _fact_count(expected_result),
            "complete": expected_result.get("complete", True),
            "controller_subprocess_wall_scope": "whole child process wall time including interpreter bootstrap, JSON serialization, and IPC",
            "first_response_scope": "inside-worker time after Python bootstrap; includes runtime import and evaluation, excludes result JSON serialization",
            "process_state": "warm disk DLL / OS cache; not an OS-cold claim",
            "peak_memory_scope": "fresh process lifetime: runtime imports plus evaluated output, captured before result JSON serialization",
            "path_order_by_pair": orders,
            "python_oracle": {"controller_subprocess_wall": summarize(paths["python_oracle"], "controller_subprocess_wall_ns"),
                              "runtime_import": summarize(paths["python_oracle"], "worker_runtime_import_ns"),
                              "operation": summarize(paths["python_oracle"], "worker_operation_ns"),
                              "first_response_before_json": summarize(paths["python_oracle"], "worker_first_response_ns")},
            "native_resident": {"controller_subprocess_wall": summarize(paths["native_resident"], "controller_subprocess_wall_ns"),
                                "runtime_import": summarize(paths["native_resident"], "worker_runtime_import_ns"),
                                "operation": summarize(paths["native_resident"], "worker_operation_ns"),
                                "first_response_before_json": summarize(paths["native_resident"], "worker_first_response_ns")}}


def _compile_time(native, toolchain):
    suffix = ".dll" if os.name == "nt" else ".so"
    with tempfile.TemporaryDirectory(prefix="growth-build-") as directory:
        copied = Path(directory) / "native_graph.c"
        shutil.copyfile(native.SOURCE, copied)
        start = time.perf_counter_ns()
        toolchain.build_shared(copied, Path(directory) / ("native_graph" + suffix))
        return time.perf_counter_ns() - start


def _hashes(snapshot):
    source_root = SNAPSHOT / "mrl" if snapshot else ROOT / "mrl"
    names = ("__init__.py", "native_graph.py", "toolchain.py", "graph_plan.py", "runtime/native_graph.c")
    hashes = {name: hashlib.sha256((source_root / name).read_bytes()).hexdigest() for name in names}
    hashes["oracle.py"] = hashlib.sha256((ROOT / "mrl" / "oracle.py").read_bytes()).hexdigest()
    hashes["graph_inference.py"] = hashlib.sha256((ROOT / "graph_inference.py").read_bytes()).hexdigest()
    hashes["benchmark_growth.py"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return hashes


def run(*, snapshot=False, samples=7, warm_samples=25, append_samples=None, sizes=SIZES,
        capacity=64, derived_per_seed=3, append_endpoint_only=False):
    if samples < 5 or warm_samples < 5:
        raise ValueError("samples and warm_samples must both be at least 5")
    if append_samples is None:
        append_samples = samples
    if append_samples < 5 or capacity < 64 or derived_per_seed < 1:
        raise ValueError("invalid growth benchmark limits")
    native, toolchain = _runtime(snapshot)
    oracle = _oracle_module()
    source_hashes = _hashes(snapshot)
    report = {"version": 1, "baseline_snapshot": snapshot, "sizes": list(sizes), "samples": samples,
              "warm_samples": warm_samples, "append_samples": append_samples, "capacity": capacity,
              "derived_facts_per_seed": derived_per_seed, "method": "full structural parity is checked before and outside every timed region; p95 uses nearest-rank individual requests",
              "linkage": {"native_graph": str(Path(native.__file__).resolve()), "native_source": str(native.SOURCE.resolve()),
                          "toolchain": str(Path(toolchain.__file__).resolve()), "toolchain_cache": str(toolchain._TOOLS.resolve()),
                          "oracle": str((ROOT / "mrl" / "oracle.py").resolve()), "graph_inference": str((ROOT / "graph_inference.py").resolve()),
                          "source_sha256": source_hashes}, "operations": {}}
    # Fresh-process measurements run before build identity/platform probes to retain startup cost.
    for operation in ("closure", "closure_with_provenance"):
        report["operations"][operation] = {}
        for seeds in sizes:
            case = _case(operation, seeds, derived_per_seed, capacity)
            report["operations"][operation][str(seeds)] = {
                "seed_count": seeds, "expected_derived_facts": seeds * derived_per_seed,
                "expected_total_facts": seeds * (derived_per_seed + 1),
                "fresh_process": _fresh_process(operation, seeds, snapshot, samples, capacity, derived_per_seed),
                "first_answer": _first_answer(native, oracle, case, samples, capacity),
                "warm_repeated_evaluate": _warm_answer(native, oracle, case, warm_samples, capacity),
                "append_evaluate": (_append_endpoint(native, oracle, operation, seeds, append_samples, derived_per_seed, capacity)
                                    if append_endpoint_only else _append_answer(native, oracle, operation, seeds, append_samples, derived_per_seed, capacity))}
        report["operations"][operation]["denial_update"] = _denial_answer(native, oracle, operation, derived_per_seed, capacity)
    report["capacity_refusal"] = _capacity_refusal(native, capacity)
    report["explicit_compile_ns"] = _compile_time(native, toolchain)
    if _hashes(snapshot)["oracle.py"] != source_hashes["oracle.py"] or _hashes(snapshot)["graph_inference.py"] != source_hashes["graph_inference.py"]:
        raise AssertionError("oracle source changed during benchmark")
    report["explicit_compile_note"] = "separate compiler invocation; compiler cache may already be warm"
    report["metadata"] = {"python": sys.version, "platform": importlib.import_module("platform").platform(),
                          "compiler": toolchain.find_compiler()[0]}
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output")
    parser.add_argument("--snapshot", action="store_true")
    parser.add_argument("--samples", type=int, default=7)
    parser.add_argument("--warm-samples", type=int, default=25)
    parser.add_argument("--append-samples", type=int)
    parser.add_argument("--sizes", default=",".join(map(str, SIZES)))
    parser.add_argument("--capacity", type=int, default=64)
    parser.add_argument("--derived-per-seed", type=int, default=3)
    parser.add_argument("--append-endpoint-only", action="store_true")
    parser.add_argument("--worker", choices=("python", "native"))
    parser.add_argument("--operation", choices=("closure", "closure_with_provenance"))
    parser.add_argument("--seeds", type=int)
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(_worker(args.worker, args.operation, args.seeds, args.snapshot, args.capacity, args.derived_per_seed), sort_keys=True))
        return
    default_name = "GROWTH_BASELINE.json" if args.snapshot else "GROWTH_AFTER.json"
    output = Path(args.output) if args.output else Path(__file__).parent / "docs" / default_name
    output.parent.mkdir(parents=True, exist_ok=True)
    sizes = tuple(int(value) for value in args.sizes.split(",") if value)
    output.write_text(json.dumps(run(snapshot=args.snapshot, samples=args.samples, warm_samples=args.warm_samples,
                                     append_samples=args.append_samples, sizes=sizes, capacity=args.capacity,
                                     derived_per_seed=args.derived_per_seed, append_endpoint_only=args.append_endpoint_only), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
