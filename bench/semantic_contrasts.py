"""Measure semantic coverage separately from answer abstention on fixed contrasts."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def run():
    from semantic_parser import SemanticParser
    from state_engine import evaluate
    raw = (ROOT / "data/benchmarks/semantic_contrasts_v1.json").read_bytes()
    parser = SemanticParser()
    rows = []
    for case in json.loads(raw)["cases"]:
        parsed = parser.parse(case["input"])
        result = evaluate(parsed, ROOT / "graphs/graph_일상추론.kg")
        answer_ok = result["status"] == "unknown" if case.get("unknown") else (
            result["status"] == "answered" and result["answer"] in case["answers"])
        rows.append({"id": case["id"], "family": case["family"],
                     "parsed": parsed["accepted"], "answer_ok": answer_ok,
                     "ok": parsed["accepted"] and answer_ok, "result": result})
    return {"schema": "semantic-contrasts-result-v1", "dataset_sha256": hashlib.sha256(raw).hexdigest(),
            "scope": "development semantic/state path, not end-to-end UI or blind evaluation",
            "passed": sum(row["ok"] for row in rows), "total": len(rows), "rows": rows}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run()
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, ensure_ascii=False))
