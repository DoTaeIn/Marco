"""Answer-blind runtime evaluation; never train on these expected outputs.

Run from any directory. Exact answer scoring is deliberately explicit: failures
may need human review for equivalent wording, and this is not a GPT-3 comparison.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run(path=None, answerer=None):
    path = Path(path or ROOT / "data/benchmarks/reasoning_transfer_v1.json")
    raw = path.read_bytes()
    cases = json.loads(raw)["cases"]
    if answerer is None:
        import engine
        answerer = engine.answer
    rows = []
    families = defaultdict(lambda: {"passed": 0, "total": 0})
    for case in cases:
        start = time.perf_counter()
        try:
            source, verdict, answer = answerer(case["input"])
            abstained = verdict == "미지"
            ok = abstained if case.get("unknown") else (
                not abstained and str(answer).strip() in case["answers"])
            failure = None if ok else ("unexpected_abstention" if abstained else "incorrect_answer")
            row = {"source": source, "verdict": verdict, "answer": answer, "failure": failure}
        except Exception as exc:
            ok = False
            row = {"failure": "runtime_error", "error": f"{type(exc).__name__}: {exc}"}
        row.update(id=case["id"], family=case["family"], input=case["input"],
                   ok=ok, elapsed_ms=round((time.perf_counter() - start) * 1000, 2))
        rows.append(row)
        families[case["family"]]["total"] += 1
        families[case["family"]]["passed"] += int(ok)
    return {"schema": "reasoning-transfer-result-v1", "dataset_sha256": hashlib.sha256(raw).hexdigest(),
            "scope": "development diagnostic, not blind or GPT-3 equivalence",
            "passed": sum(r["ok"] for r in rows), "total": len(rows),
            "families": dict(families), "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run(args.dataset)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
