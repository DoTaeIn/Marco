#!/usr/bin/env python3
"""HICO-DET parquet을 사람-물체-행동(다중 라벨) 학습 사례로 정규화한다.

원본 이미지 바이트는 복제하지 않는다. 각 사례는 parquet 행과 원본 bbox를
가리키므로, train/test가 섞이지 않는 상태로 이후 특징 추출·학습에 사용한다.
"""
from __future__ import annotations

import ast
import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


def _literal(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    try:
        result = ast.literal_eval(str(value))
        return result if isinstance(result, list) else []
    except (SyntaxError, ValueError):
        return []


def normalize_rows(parquet: Path, split: str, limit: int | None = None) -> Iterable[dict[str, Any]]:
    """행마다 객체명별 positive action을 보존한 bbox 사례를 만든다."""
    frame = pd.read_parquet(parquet, columns=["image", "objects", "positive_captions"])
    if limit is not None:
        frame = frame.iloc[:limit]
    for row_index, row in frame.iterrows():
        captions = _literal(row["positive_captions"])
        actions: dict[str, list[str]] = {}
        for item in captions:
            if not isinstance(item, (tuple, list)) or len(item) != 2:
                continue
            object_name, action = str(item[0]), str(item[1])
            if action != "no_interaction":
                actions.setdefault(object_name, []).append(action)
        for pair_index, pair in enumerate(_literal(row["objects"])):
            if not isinstance(pair, dict):
                continue
            human, obj = pair.get("bbox_human"), pair.get("bbox_object")
            if not (isinstance(human, list) and len(human) == 4 and isinstance(obj, list) and len(obj) == 4):
                continue
            # HICO의 object id만으로 이름을 안전하게 복원할 수 없으므로 라벨이
            # 하나뿐인 이미지에서만 이 단계의 bbox 쌍에 붙인다. 다의적인 행은
            # 억지 연결 대신 review로 남기며 이후 공식 mapping으로 보완한다.
            if len(actions) != 1:
                continue
            object_name, labels = next(iter(actions.items()))
            yield {"split": split, "row": int(row_index), "pair": pair_index,
                   "image_path": row["image"].get("path", ""), "object": object_name,
                   "actions": sorted(set(labels)), "bbox_human": human, "bbox_object": obj}


def build_manifest(parquet: Path, output: Path, split: str, limit: int | None = None) -> dict[str, Any]:
    rows = list(normalize_rows(parquet, split, limit))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    action_counts = Counter(action for row in rows for action in row["actions"])
    return {"split": split, "examples": len(rows), "actions": len(action_counts),
            "top_actions": action_counts.most_common(12), "manifest": str(output)}


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("parquet", type=Path); parser.add_argument("output", type=Path)
    parser.add_argument("--split", default="train"); parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    print(json.dumps(build_manifest(args.parquet, args.output, args.split, args.limit), ensure_ascii=False, indent=2))
