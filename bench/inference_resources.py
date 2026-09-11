"""Synthetic reasoning resource probe, not an intelligence benchmark.

Checks every expected reachability fact and fingerprints proof records. Timing
excludes tracemalloc; a separate run measures Python allocation peak (not RSS).
"""
import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time
import tracemalloc

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from graph_inference import closure


def run():
    rows = []
    rule = {"id": "transitivity", "body": [["?a", "p", "?b"], ["?b", "p", "?c"]],
            "head": ["?a", "p", "?c"]}
    for size in (12, 24):
        facts = [{"triple": [str(i), "p", str(i + 1)], "evidence": i} for i in range(size)]
        facts += [{"triple": [str(i), "unrelated", "value"], "evidence": i} for i in range(256)]
        durations = []
        for _ in range(3):
            start = time.perf_counter()
            known = closure(facts, [rule])
            durations.append((time.perf_counter() - start) * 1000)
        expected = {(str(a), "p", str(b)) for a in range(size) for b in range(a + 1, size + 1)}
        expected |= {(str(i), "unrelated", "value") for i in range(256)}
        assert set(known) == expected
        encoded = json.dumps(sorted(known.values(), key=lambda row: row["fact"]), sort_keys=True).encode()
        tracemalloc.start()
        closure(facts, [rule])
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        rows.append({"chain_edges": size, "distractors": 256, "derived_and_input_facts": len(known),
                     "median_ms": round(statistics.median(durations), 3), "python_peak_bytes": peak,
                     "proof_sha256": hashlib.sha256(encoded).hexdigest(), "correct": True})
    return {"scope": "synthetic positive Horn closure, not whole-app memory or intelligence",
            "python": sys.version, "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run()
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
