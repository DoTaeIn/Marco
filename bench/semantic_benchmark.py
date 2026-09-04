# -*- coding: utf-8 -*-
"""의미 파서 평가 결과를 학습·보류 세트별로 기록하는 작은 러너.

실제 로컬 모델은 출력 품질을 측정할 대상이며, 실패를 정답으로 바꾸지 않는다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from semantic_parser import SemanticParser
import state_engine


ROOT = Path(__file__).resolve().parent


def run(path=ROOT / "data/benchmarks/semantic_reasoning.json", parser=None):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    parser = parser or SemanticParser()
    kg = ROOT / "graphs/graph_일상추론.kg"
    results = {"model": parser.model_id, "splits": {}}
    for split in ("train", "held_out"):
        rows = []
        for item in data[split]:
            semantic = parser.parse(item["input"])
            outcome = state_engine.evaluate(semantic, kg)
            expected_status = item.get("status", "answered")
            ok = outcome["status"] == expected_status and (not item.get("answer") or outcome.get("answer") == item["answer"])
            rows.append({"id": item["id"], "ok": ok, "expected_relation": item.get("relation"),
                         "actual_relation": outcome.get("operator"), "status": outcome["status"],
                         "answer": outcome.get("answer"), "parse_accepted": semantic["accepted"]})
        results["splits"][split] = {"passed": sum(x["ok"] for x in rows), "total": len(rows), "rows": rows}
    return results


if __name__ == "__main__":
    args = argparse.ArgumentParser().parse_args()
    print(json.dumps(run(), ensure_ascii=False, indent=2))
