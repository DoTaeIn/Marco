"""Parity-gated v4 benchmark for the native graph paths."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import platform
import statistics
import subprocess
import sys
import tempfile
import time
import shutil
from copy import deepcopy
from pathlib import Path

from mrl import native_graph, oracle, toolchain
from mrl.benchmark import workloads

MARCO_ROOT = Path(__file__).parents[1]
MRL_ROOT = Path(__file__).parent
PATHS = ("oracle", "stateless_debug", "stateless_release", "resident_generic", "resident_specialized")


def _fact(a, p, b, **metadata):
    return {"triple": [a, p, b], "evidence": {"text": f"{a} {p} {b}"}, **metadata}


def real_cases():
    """Exact bounded copies of named Marco test inputs; these are not coverage claims."""
    return {
        "real_event_alternatives": (
            {"operation": "closure_with_provenance", "facts": [
                {"id": "fact:p", "triple": ["a", "p", "b"], "evidence": {}},
                {"id": "fact:q", "triple": ["a", "q", "b"], "evidence": {}},
            ], "rules": [
                {"id": "via-p", "version": "r1", "body": [["?x", "p", "?y"]], "head": ["?x", "reachable", "?y"]},
                {"id": "via-q", "version": "r2", "body": [["?x", "q", "?y"]], "head": ["?x", "reachable", "?y"]},
            ]},
            "tests/test_event_provenance.py:test_independent_proof_bundles_survive_one_support_becoming_invalid",
            ("fact:p", "fact:q", "via-p", "via-q", "reachable"),
        ),
        "real_signed_block": (
            {"operation": "closure", "facts": [
                _fact("x", "p", "y"), _fact("x", "q", "y", polarity=False), _fact("u", "p", "v"),
            ], "rules": [
                {"id": "first", "body": [["?a", "p", "?b"]], "head": ["?a", "q", "?b"]},
                {"id": "second", "body": [["?a", "q", "?b"]], "head": ["?a", "r", "?b"]},
            ]},
            "tests/test_signed_inference.py:test_denied_intermediate_cannot_support_downstream_conclusion",
            ("test_denied_intermediate_cannot_support_downstream_conclusion", "fact(\"x\", \"p\", \"y\")", "polarity=False", "first", "second"),
        ),
    }


def _sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _source_attribution():
    """Reject a report when an attributed test or copied input marker drifts."""
    rows = {}
    for name, (_, attribution, markers) in real_cases().items():
        path_text, test_name = attribution.split(":", 1)
        path = MARCO_ROOT / path_text
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        function = next((node for node in tree.body
                         if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == test_name), None)
        if function is None:
            raise AssertionError("attributed test missing: " + attribution)
        if not all(marker in source for marker in markers):
            raise AssertionError("copied input differs: " + attribution)
        case = real_cases()[name][0]
        assignments = {node.targets[0].id: ast.literal_eval(node.value) for node in function.body
                       if isinstance(node, ast.Assign) and len(node.targets) == 1
                       and isinstance(node.targets[0], ast.Name) and node.targets[0].id in {"facts", "rules"}}
        if name == "real_event_alternatives":
            equivalent = assignments.get("facts") == case["facts"] and assignments.get("rules") == case["rules"]
        else:
            call = next((node.value for node in function.body if isinstance(node, ast.Assign)
                         and isinstance(node.value, ast.Call) and getattr(node.value.func, "id", None) == "closure"), None)
            source_facts = [] if call is None else [_fact(*[ast.literal_eval(arg) for arg in row.args],
                                                   **{keyword.arg: ast.literal_eval(keyword.value) for keyword in row.keywords})
                                             for row in call.args[0].elts]
            equivalent = source_facts == case["facts"] and assignments.get("rules") == case["rules"]
        if not equivalent:
            raise AssertionError("copied input differs: " + attribution)
        rows[name] = {"source": attribution, "source_sha256": _sha256(path),
                      "input_validation": "named test exists; copied facts and rules equal the source AST"}
    return rows


def _tail(samples):
    return max(samples)


def _measure_paths(calls, batches, repeats):
    samples = {name: [] for name in PATHS}
    orders = []
    for batch in range(batches):
        order = list(PATHS[batch % len(PATHS):] + PATHS[:batch % len(PATHS)])
        if batch % 2:
            order.reverse()
        orders.append(order)
        for name in order:
            start = time.perf_counter_ns()
            for _ in range(repeats):
                calls[name]()
            samples[name].append((time.perf_counter_ns() - start) / repeats)
    oracle_median = statistics.median(samples["oracle"])
    return ({name: {"median_ns": statistics.median(values), "batch_tail_ns": _tail(values),
                    "batch_tail_method": "maximum mean of recorded batches", "raw_batch_ns": values,
                    "ratio_to_oracle": statistics.median(values) / oracle_median}
             for name, values in samples.items()}, orders)


def _append_fact(case):
    body = case["rules"][0]["body"][0]
    return {"id": "benchmark:append", "triple": [
        "benchmark-subject" if value.startswith("?") and value != "?y" else
        "benchmark-object" if value == "?y" else value for value in body], "evidence": {}}


def _append_measure(case, expected, batches, repeats):
    delta = [_append_fact(case)]
    evolved = {**deepcopy(case), "facts": deepcopy(case["facts"]) + deepcopy(delta)}
    if oracle.evaluate(evolved) != expected:
        raise AssertionError("append oracle parity")
    names = ("oracle", "resident_generic", "resident_specialized")
    samples, orders = {name: [] for name in names}, []
    for batch in range(batches):
        order = list(names[batch % len(names):] + names[:batch % len(names)])
        if batch % 2:
            order.reverse()
        orders.append(order)
        for name in order:
            # Independent base inputs are deliberately prepared outside append+evaluate timing.
            if name == "oracle":
                inputs = [deepcopy(case) for _ in range(repeats + 1)]
                calls = [lambda item=item: (item["facts"].extend(delta), oracle.evaluate(item))[1]
                         for item in inputs]
            else:
                graphs = [native_graph.PreparedGraph(case, specialized=name.endswith("specialized"))
                          for _ in range(repeats + 1)]
                calls = [lambda graph=graph: (graph.append_facts(delta), graph.evaluate())[1]
                         for graph in graphs]
            if calls[0]() != expected:
                raise AssertionError("append parity: " + name)
            start = time.perf_counter_ns()
            for call in calls[1:]:
                call()
            samples[name].append((time.perf_counter_ns() - start) / repeats)
    oracle_median = statistics.median(samples["oracle"])
    return ({name: {"median_ns": statistics.median(values), "batch_tail_ns": _tail(values),
                    "batch_tail_method": "maximum mean of recorded batches", "raw_batch_ns": values,
                    "ratio_to_oracle": statistics.median(values) / oracle_median}
             for name, values in samples.items()}, orders, delta)


def _append_rejection(case, expected, delta):
    """Record an expected bounded-update rejection separately from timed successes."""
    observed = {}
    for name, specialized in (("resident_generic", False), ("resident_specialized", True)):
        graph = native_graph.PreparedGraph(case, specialized=specialized)
        try:
            graph.append_facts(delta)
            observed[name] = graph.evaluate()
        except ValueError as error:
            observed[name] = {"exception": str(error)}
    if any(value != expected for value in observed.values()):
        raise AssertionError("append rejection parity")
    return {"parity": True, "expected_rejection": True, "rejection_kind": "graph_limit_budget",
            "oracle": expected, "delta": delta, "native_observed": observed}


def _update_base(case):
    """Leave fan-out input out only until its append fits the declared budget."""
    candidate = deepcopy(case)
    while candidate["facts"]:
        delta = [_append_fact(candidate)]
        evolved = {**deepcopy(candidate), "facts": candidate["facts"] + deepcopy(delta)}
        result = oracle.evaluate(evolved)
        count = len(result.get("known", {}).get("$tuple_map", result.get("known", {})))
        if "error" not in result and count <= 64:
            omitted = len(case["facts"]) - len(candidate["facts"])
            return candidate, None if not omitted else (
                "%d asserted fan-out seed omitted so append stays within the declared graph-limit budget" % omitted)
        candidate["facts"] = candidate["facts"][:-1]
    raise AssertionError("no successful append update base")


def _fresh_cache_hit(optimization):
    code = (
        "from mrl import toolchain, native_graph\n"
        "toolchain.build_shared=lambda *a, **k: (_ for _ in ()).throw(RuntimeError('compiled on cache hit'))\n"
        "print(toolchain.cached_shared(native_graph.SOURCE, optimization=%r))\n" % optimization)
    start = time.perf_counter_ns()
    run = subprocess.run([sys.executable, "-B", "-c", code], cwd=MARCO_ROOT,
                         env={**os.environ, "PYTHONPATH": str(MARCO_ROOT)}, text=True,
                         capture_output=True, check=False, timeout=30)
    elapsed = time.perf_counter_ns() - start
    if run.returncode or not run.stdout.strip():
        raise AssertionError("fresh-process cache miss: " + run.stderr)
    return {"startup_ns": elapsed, "library": run.stdout.strip(), "compiler_launched": False}


def _build_time():
    suffix = ".dll" if os.name == "nt" else ".so"
    with tempfile.TemporaryDirectory(prefix="mrl-v4-build-") as directory:
        source = Path(directory) / native_graph.SOURCE.name
        shutil.copyfile(native_graph.SOURCE, source)
        start = time.perf_counter_ns()
        toolchain.build_shared(source, Path(directory) / ("native_graph" + suffix), optimization="release")
        return time.perf_counter_ns() - start


def _cached_libraries():
    root = MRL_ROOT / ".tools" / "native"
    return {path.resolve() for path in root.glob("*/native-*") if path.is_file()}


def _construction_record(graph, elapsed, before):
    path = Path(graph._library._name).resolve()
    return {"elapsed_ns": elapsed, "library": str(path),
            "library_cache_state": "reused" if path in before else "generated"}


def run(batches=7, repeats=200):
    if batches < 7 or repeats < 200:
        raise ValueError("v4 requires batches >= 7 and repeats >= 200")
    attribution = _source_attribution()
    cases = {**workloads(), **{name: row[0] for name, row in real_cases().items()}}
    identity = toolchain.build_identity(native_graph.SOURCE, optimization="release")
    hashes = (Path(__file__), Path(native_graph.__file__), Path(oracle.__file__), Path(toolchain.__file__),
              MRL_ROOT / "graph_plan.py", native_graph.SOURCE, MARCO_ROOT / "graph_inference.py")
    report = {"version": 4, "batches": batches, "repeats": repeats,
              "method": "full structural outputs are parity-gated before timing; batch-tail is not per-request p95",
              "production_coverage": False,
              "metadata": {"python": sys.version, "platform": platform.platform(), "compiler": identity["compiler"],
                           "release_build_identity": identity,
                           "source_hashes": {str(path.relative_to(MARCO_ROOT)): _sha256(path) for path in hashes},
                           "real_case_attribution": attribution},
              "startup": {"explicit_release_build_ns": _build_time(),
                          "explicit_release_build_note": "compiler invocation; its own compiler cache may already be warm"}, "cases": {}}
    native_graph.evaluate(next(iter(cases.values())), optimization="release")
    report["startup"]["fresh_process_release_cache_hit"] = _fresh_cache_hit("release")
    for name, case in cases.items():
        expected = oracle.evaluate(case)
        before = _cached_libraries(); start = time.perf_counter_ns(); generic = native_graph.PreparedGraph(case); generic_startup = time.perf_counter_ns() - start
        generic_record = _construction_record(generic, generic_startup, before)
        before = _cached_libraries(); start = time.perf_counter_ns(); specialized = native_graph.PreparedGraph(case, specialized=True); specialized_startup = time.perf_counter_ns() - start
        specialized_record = _construction_record(specialized, specialized_startup, before)
        calls = {"oracle": lambda: oracle.evaluate(case),
                 "stateless_debug": lambda: native_graph.evaluate(case, optimization="debug"),
                 "stateless_release": lambda: native_graph.evaluate(case),
                 "resident_generic": generic.evaluate, "resident_specialized": specialized.evaluate}
        actual = {label: call() for label, call in calls.items()}
        if any(result != expected for result in actual.values()):
            raise AssertionError("full-output parity: " + name)
        timings, orders = _measure_paths(calls, batches, repeats)
        rejection = None
        original_delta = [_append_fact(case)]
        original_evolved = {**deepcopy(case), "facts": deepcopy(case["facts"]) + deepcopy(original_delta)}
        original_expected = oracle.evaluate(original_evolved)
        if "error" in original_expected or len(original_expected.get("known", {}).get("$tuple_map", original_expected.get("known", {}))) > 64:
            rejection = _append_rejection(case, original_expected, original_delta)
        update_case, headroom = _update_base(case)
        evolved = {**deepcopy(update_case), "facts": deepcopy(update_case["facts"]) + [_append_fact(update_case)]}
        append, append_orders, delta = _append_measure(update_case, oracle.evaluate(evolved), batches, repeats)
        result = expected.get("facts", expected.get("known", {}))
        report["cases"][name] = {"parity": True, "complete": expected.get("complete", True),
                                  "result_bytes": len(json.dumps(expected, ensure_ascii=False, sort_keys=True).encode()),
                                  "result_fact_count": len(result.get("$tuple_map", result)),
                                  "construction": {"resident_generic": generic_record, "resident_specialized": specialized_record},
                                  "timings": timings, "path_order_by_batch": orders,
                                  "append_evaluate": {"parity": True, "delta": delta, "timings": append,
                                                     "path_order_by_batch": append_orders,
                                                     "base_adjustment": headroom},
                                  "append_capacity_rejection": rejection}
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--batches", type=int, default=7)
    parser.add_argument("--repeats", type=int, default=200)
    args = parser.parse_args()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(run(args.batches, args.repeats), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
