# -*- coding: utf-8 -*-
"""YOLO pose 결과를 자유 생성 없이 JSON 관찰값으로 내보낸다.

입력 이미지를 설명하지 않는다. 사람 상자와 17개 COCO 관절의 정규화 좌표·신뢰도만
반환한다. 자세나 상호작용 같은 후속 결론은 호출 측이 관절 기하와 다른 검출 근거를
함께 만족할 때에만 만든다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MODEL = ROOT / "data" / "models" / "yolo11n-pose.pt"


def detect(image: str | Path, threshold: float = .55) -> dict:
    if not MODEL.is_file():
        return {"people": [], "error": "YOLO pose 모델을 찾지 못했습니다"}
    try:
        from ultralytics import YOLO
        result = YOLO(str(MODEL))(str(image), conf=threshold, verbose=False)[0]
    except Exception as exc:
        return {"people": [], "error": str(exc)}
    height, width = result.orig_shape[:2]
    boxes = result.boxes
    keypoints = result.keypoints
    if boxes is None or keypoints is None or keypoints.xy is None:
        return {"people": []}
    xy = keypoints.xy.cpu().tolist()
    confidence = keypoints.conf.cpu().tolist() if keypoints.conf is not None else []
    result_people = []
    for index, box in enumerate(boxes.xyxy.cpu().tolist()):
        score = float(boxes.conf[index].item())
        points = []
        for point_index, point in enumerate(xy[index]):
            x, y = float(point[0]), float(point[1])
            point_confidence = float(confidence[index][point_index]) if index < len(confidence) else 0.0
            points.append({"x": x / width, "y": y / height, "confidence": point_confidence})
        x1, y1, x2, y2 = map(float, box)
        result_people.append({"box": [x1 / width, y1 / height, (x2 - x1) / width, (y2 - y1) / height],
                              "confidence": score, "keypoints": points})
    return {"people": result_people}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--threshold", type=float, default=.55)
    args = parser.parse_args(argv)
    print(json.dumps(detect(args.image, args.threshold), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
