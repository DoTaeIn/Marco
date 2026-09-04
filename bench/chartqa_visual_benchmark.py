# -*- coding: utf-8 -*-
"""ChartQA에서 구조 감지 자체가 답인 문항만 보수적으로 재는 벤치마크.

문자열 계산/상식 추론 문항은 이 측정의 대상이 아니다. `몇 개의 막대` 같은
질문에 한해서 pixel chart detector의 막대 수와 공개 정답을 비교한다.

    .venv-vision/bin/python chartqa_visual_benchmark.py --limit 12
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import re
import tempfile
from pathlib import Path

import pandas as pd

import document_visual


DEFAULT = Path("data/benchmarks/chartqa/data/test-00000-of-00001-e2cd0b7a0f9eb20d.parquet")
COUNT_BARS = re.compile(r"\bhow many\b.*\b(?:bars?|food items?)\b", re.I)


def numeric(labels):
    for label in labels or []:
        try:
            return int(float(str(label).replace(",", "")))
        except ValueError:
            continue
    return None


def run(path: Path = DEFAULT, limit: int = 12) -> dict:
    rows = pd.read_parquet(path)
    candidates = []
    seen = set()
    for _, row in rows.iterrows():
        expected = numeric(row["label"])
        image = row["image"]["bytes"]
        key = hash(image)
        if key in seen or expected is None or not COUNT_BARS.search(str(row["query"])):
            continue
        seen.add(key)
        candidates.append((image, str(row["query"]), expected))
        if len(candidates) >= limit:
            break
    results = []
    with tempfile.TemporaryDirectory(prefix="nai-chartqa-bench-") as directory:
        for index, (image, question, expected) in enumerate(candidates):
            file = Path(directory) / ("%d.png" % index)
            file.write_bytes(image)
            report = document_visual.analyze_image(file, "chartqa.%d" % index)
            actual = len(report["structure"].get("bars", [])) if report["structure"].get("type") == "bar_chart" else None
            results.append({"question": question, "expected": expected, "detected": actual,
                            "correct": actual == expected, "type": report["structure"].get("type")})
    return {"eligible": len(results), "correct": sum(item["correct"] for item in results), "results": results}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT)
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args(argv)
    result = run(args.data, args.limit)
    print("ChartQA bar-count: %d/%d" % (result["correct"], result["eligible"]))
    for item in result["results"]:
        print("%s | expected=%s detected=%s | %s" %
              ("OK" if item["correct"] else "MISS", item["expected"], item["detected"], item["question"]))


if __name__ == "__main__":
    main()
