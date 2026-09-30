"""Parity-gated measurements for the bounded native Horn fixture slice."""
from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import tempfile
import shutil
import sys
import time
from pathlib import Path

from mrl import native_graph, oracle, toolchain


def _fact(index, predicate="p"):
    return {"id": "f%d" % index, "triple": ["n%d" % index, predicate, "v"], "evidence": {}}


def workloads():
    chain = [_fact(0)]
    rules = []
    for index in range(4):
        rules.append({"id": "c%d" % index, "body": [["?x", "p%d" % index, "?y"]], "head": ["?x", "p%d" % (index + 1), "?y"]})
    chain[0]["triple"][1] = "p0"
    return {
        "closure_chain": {"operation": "closure", "facts": chain, "rules": rules},
        "closure_fanout": {"operation": "closure", "facts": [_fact(i) for i in range(32)], "rules": [{"id": "fan", "body": [["?x", "p", "?y"]], "head": ["?x", "q", "?y"]}], "options": {"limit": 64}},
        "provenance_chain": {"operation": "closure_with_provenance", "facts": chain, "rules": rules},
        "provenance_alternatives": {"operation": "closure_with_provenance", "facts": [_fact(0), {"id": "fq", "triple": ["n0", "q", "v"], "evidence": {}}], "rules": [{"id": "via_p", "body": [["?x", "p", "?y"]], "head": ["?x", "r", "?y"]}, {"id": "via_q", "body": [["?x", "q", "?y"]], "head": ["?x", "r", "?y"]}, {"id": "r_to_s", "body": [["?x", "r", "?y"]], "head": ["?x", "s", "?y"]}]},
    }


def _median(call, batches=5, repeats=200):
    samples = []
    for _ in range(batches):
        start = time.perf_counter_ns()
        for _ in range(repeats): call()
        samples.append((time.perf_counter_ns() - start) / repeats)
    return statistics.median(samples), samples


def run(batches=5, repeats=200):
    report = {"python": sys.version, "platform": platform.platform(), "compiler": toolchain.find_compiler()[0], "method": "native ABI includes validation/marshal/decode; subprocess includes process launch", "batches": batches, "repeats": repeats, "workloads": {}}
    cases = workloads()
    cold_case = next(iter(cases.values()))
    start = time.perf_counter_ns(); native_graph.evaluate(cold_case); report["first_native_call_ns"] = time.perf_counter_ns() - start
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory); source, executable = root / "native_graph.c", root / "native_graph.exe"
        shutil.copyfile(native_graph.SOURCE, source)
        start = time.perf_counter_ns(); toolchain.build_c(source, executable); report["subprocess_build_ns"] = time.perf_counter_ns() - start
        for name, case in cases.items():
         expected = oracle.evaluate(case)
         actual = native_graph.evaluate(case)
         if actual != expected:
             raise AssertionError("native parity failed: " + name)
         if native_graph.evaluate(case) != actual:
             raise AssertionError("native nondeterminism: " + name)
         python_samples, native_samples = [], []
         for batch in range(batches):
             first, second = ((lambda: oracle.evaluate(case)), (lambda: native_graph.evaluate(case))) if batch % 2 == 0 else ((lambda: native_graph.evaluate(case)), (lambda: oracle.evaluate(case)))
             first_ns, _ = _median(first, 1, repeats); second_ns, _ = _median(second, 1, repeats)
             if batch % 2 == 0: python_samples.append(first_ns); native_samples.append(second_ns)
             else: native_samples.append(first_ns); python_samples.append(second_ns)
         python_ns, native_ns = statistics.median(python_samples), statistics.median(native_samples)
         if native_graph.evaluate_subprocess(case, executable) != expected:
             raise AssertionError("subprocess parity failed: " + name)
         subprocess_ns, subprocess_samples = _median(lambda: native_graph.evaluate_subprocess(case, executable), 5, 1)
         report["workloads"][name] = {"parity": True, "python_median_ns": python_ns,
                                      "native_median_ns": native_ns, "native_over_python": native_ns / python_ns,
                                      "python_batches_ns": python_samples, "native_batches_ns": native_samples,
                                      "subprocess_median_ns": subprocess_ns, "subprocess_batches_ns": subprocess_samples, "facts": len(case["facts"]), "rules": len(case["rules"]), "complete": actual.get("complete", True), "known_facts": len(actual.get("facts", actual.get("known", {})).get("$tuple_map", actual.get("facts", actual.get("known", {})))), "proof_rows": sum(len(row["value"]) for row in actual.get("proof_bundles", {}).get("$tuple_map", []))}
    for path in (Path(native_graph.__file__), Path(oracle.__file__), native_graph.SOURCE, Path(toolchain.__file__), Path(native_graph.SOURCE).parents[2] / "graph_inference.py"):
        report.setdefault("sha256", {})[str(path)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--batches", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=200)
    args = parser.parse_args()
    if args.batches < 5 or args.repeats < 1: raise SystemExit("batches >= 5 and repeats >= 1 required")
    output = Path(args.output); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(run(args.batches, args.repeats), indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__": main()
