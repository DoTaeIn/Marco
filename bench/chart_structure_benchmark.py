# -*- coding: utf-8 -*-
"""ChartQA에서 질문이 차트 종류를 명시한 표본으로 구조 감지를 점검한다.

질문에 bar/line/pie가 직접 적힌 경우만 사용한다. 값 계산 문제는 평가하지 않고,
동일 이미지를 여러 질문이 공유해도 한 번만 측정한다.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import tempfile
from collections import defaultdict
from pathlib import Path

import pandas as pd

import document_visual


DEFAULT = Path("data/benchmarks/chartqa/data/test-00000-of-00001-e2cd0b7a0f9eb20d.parquet")


def expected_type(question: str) -> str | None:
    text = question.casefold()
    if re.search(r"\bpie\b", text):
        return "pie_chart"
    # "online"처럼 다른 낱말 내부의 line은 차트 유형 표지가 아니다.
    if re.search(r"\bline\b", text):
        return "line_chart"
    if re.search(r"\bbar\b", text):
        return "bar_chart"
    return None


def run(dataset: Path = DEFAULT, per_type: int = 8) -> dict:
    frame = pd.read_parquet(dataset, columns=["image", "query"])
    selected: dict[str, list[tuple[int, bytes]]] = defaultdict(list)
    seen: dict[str, set[str]] = defaultdict(set)
    for index, row in frame.iterrows():
        kind = expected_type(str(row["query"]))
        if not kind or len(selected[kind]) >= per_type:
            continue
        image = row["image"]["bytes"]
        digest = hashlib.sha256(image).hexdigest()
        if digest in seen[kind]:
            continue
        seen[kind].add(digest)
        selected[kind].append((int(index), image))
    results = {}
    with tempfile.TemporaryDirectory(prefix="nai-chart-type-") as directory:
        for kind, rows in selected.items():
            output = []
            for index, image in rows:
                path = Path(directory) / ("%s-%d.png" % (kind, index))
                path.write_bytes(image)
                actual = document_visual.analyze_image(path, "chartqa.%d" % index)["structure"]["type"]
                output.append({"index": index, "expected": kind, "actual": actual, "correct": actual == kind})
            results[kind] = {"correct": sum(row["correct"] for row in output), "total": len(output), "rows": output}
    return results


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT)
    parser.add_argument("--per-type", type=int, default=8)
    args = parser.parse_args(argv)
    for kind, result in run(args.data, args.per_type).items():
        print("%s: %d/%d" % (kind, result["correct"], result["total"]))
        for row in result["rows"]:
            if not row["correct"]:
                print("  MISS index=%d actual=%s" % (row["index"], row["actual"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
