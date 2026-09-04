# -*- coding: utf-8 -*-
"""비토큰 객체 검출기(YOLO)의 상자 결과를 JSON으로 내보낸다."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "data" / "models" / "yolo11n.pt"


def detect(image: str) -> dict:
    from ultralytics import YOLO
    if not MODEL.is_file():
        raise RuntimeError("YOLO 가중치를 찾지 못했습니다: %s" % MODEL)
    result = YOLO(str(MODEL))(image, verbose=False)[0]
    height, width = result.orig_shape
    items = []
    for cls, confidence, box in zip(result.boxes.cls, result.boxes.conf, result.boxes.xyxy):
        score = float(confidence)
        if score < .55:
            continue
        x1, y1, x2, y2 = [float(value) for value in box]
        items.append({"label": result.names[int(cls)], "confidence": score,
                      "box": [x1 / width, y1 / height, (x2 - x1) / width, (y2 - y1) / height]})
    return {"objects": items}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(detect(args.image), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"error": "%s: %s" % (type(exc).__name__, exc)}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
