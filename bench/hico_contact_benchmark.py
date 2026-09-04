# -*- coding: utf-8 -*-
"""HICO-DET 라벨로 비토큰 손-물체 기하 관찰의 범위를 잰다.

이 도구는 `손이 대상 상자에 가깝다`를 `hold` 정답과 동일시하지 않는다. 검출된
대상 클래스가 HICO의 hold 대상과 일치하는 경우만 평가 모수로 삼아, 검출 실패와
기하 규칙 실패를 분리한다.
"""
from __future__ import annotations

import argparse
import ast
import json
import tempfile
from pathlib import Path

import pandas as pd

import document_visual


DEFAULT = Path("data/benchmarks/hico_det/data/test-00000-of-00004.parquet")


def canonical(name: str) -> str:
    return str(name).casefold().replace("_", " ").replace("-", " ").strip()


def run(dataset: Path = DEFAULT, limit: int = 12) -> dict:
    frame = pd.read_parquet(dataset, columns=["image", "positive_captions"])
    selected = []
    for index, row in frame.iterrows():
        labels = ast.literal_eval(row["positive_captions"])
        holds = {canonical(obj) for obj, verb in labels if verb == "hold"}
        if holds:
            selected.append((index, row, holds))
        if len(selected) >= limit:
            break
    rows = []
    with tempfile.TemporaryDirectory(prefix="nai-hico-contact-") as directory:
        for index, row, holds in selected:
            image = Path(directory) / ("%d.jpg" % index)
            image.write_bytes(row["image"]["bytes"])
            report = document_visual.analyze_image(image, "hico.%d" % index)
            detected = {canonical(item["label"]) for item in report["objects"] if item.get("label") != "person"}
            eligible = holds & detected
            contacts = {canonical(item["object"]) for item in report["situations"]}
            matched = eligible & contacts
            false_contacts = contacts - holds
            rows.append({"index": int(index), "holds": sorted(holds), "detected": sorted(detected),
                         "eligible": sorted(eligible), "contacts": sorted(contacts),
                         "matched": sorted(matched), "false_contacts": sorted(false_contacts)})
    eligible = sum(len(row["eligible"]) for row in rows)
    matched = sum(len(row["matched"]) for row in rows)
    predicted = sum(len(row["contacts"]) for row in rows)
    return {"samples": len(rows), "eligible_hold_objects": eligible,
            "matched_contacts": matched, "predicted_contacts": predicted,
            "geometry_recall_when_object_detected": (matched / eligible) if eligible else None,
            "geometry_precision_against_hold": (matched / predicted) if predicted else None,
            "rows": rows}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, default=DEFAULT)
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args(argv)
    print(json.dumps(run(args.data, args.limit), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
