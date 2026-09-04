# -*- coding: utf-8 -*-
"""문서 속 그림·도표에서 검증 가능한 관찰값만 뽑는다.

이 모듈은 이미지를 자연어로 지어내지 않는다. macOS Vision과 Tesseract의 OCR
좌표를 합치고, 차트의 축/막대 같은 도형은 픽셀 구조로 확인한다. 결과의 각
관찰값은 이미지 영역, 신뢰도, 추출 방법을 보존한다. VLM이 없는 환경에서는
사진의 세밀한 사건·인과를 사실로 확정하지 않는다.
"""
from __future__ import annotations

from collections import deque
from difflib import SequenceMatcher
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any

import numpy as np
from PIL import Image, ImageOps


ROOT = Path(__file__).resolve().parent
VISION_SOURCE = ROOT / "document_vision.swift"
VISION_BINARY = ROOT / ".nai-tools" / "document_vision"
VLM_SOURCE = ROOT / "document_vlm.py"
VLM_PYTHON = ROOT / ".venv-vision" / "bin" / "python"
VLM_MODELS = (ROOT / "data" / "models" / "Qwen2.5-VL-3B-Instruct",
              ROOT / "data" / "models" / "SmolVLM2-500M-Video-Instruct")
OBJECT_SOURCE = ROOT / "document_objects.py"
OBJECT_MODEL = ROOT / "data" / "models" / "yolo11n.pt"
POSE_SOURCE = ROOT / "document_pose.py"
POSE_MODEL = ROOT / "data" / "models" / "yolo11n-pose.pt"


class VisualError(RuntimeError):
    pass


def _vision_binary() -> Path | None:
    if VISION_BINARY.is_file() and os.access(VISION_BINARY, os.X_OK):
        return VISION_BINARY
    swiftc = shutil.which("swiftc")
    if not swiftc or not VISION_SOURCE.is_file():
        return None
    VISION_BINARY.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([swiftc, str(VISION_SOURCE), "-o", str(VISION_BINARY)],
                          capture_output=True, text=True, timeout=90)
    return VISION_BINARY if proc.returncode == 0 and VISION_BINARY.is_file() else None


def _vision_words(path: Path) -> tuple[list[dict], list[dict], list[str]]:
    binary = _vision_binary()
    if not binary:
        return [], [], ["macOS Vision OCR을 준비하지 못했습니다"]
    proc = subprocess.run([str(binary), str(path)], capture_output=True, text=True, timeout=90)
    if proc.returncode:
        return [], [], ["macOS Vision 분석 실패: " + (proc.stderr.strip() or "알 수 없는 오류")]
    try:
        data = json.loads(proc.stdout)
        words = [{"text": str(x["text"]), "confidence": float(x["confidence"]),
                  "box": [float(v) for v in x["box"]], "method": "macos_vision"}
                 for x in data.get("words", []) if str(x.get("text", "")).strip()]
        labels = [{"text": str(x["text"]), "confidence": float(x["confidence"]),
                   "method": "macos_vision"} for x in data.get("labels", [])]
        return words, labels, []
    except (TypeError, ValueError, KeyError) as exc:
        return [], [], ["macOS Vision 결과를 해석하지 못했습니다: %s" % exc]


def _tesseract_words(path: Path) -> tuple[list[dict], list[str]]:
    executable = shutil.which("tesseract")
    if not executable:
        return [], ["Tesseract OCR을 찾지 못했습니다"]
    # sparse text가 많은 과학 그림·차트에 psm 11이 보통의 문단 모드보다 낫다.
    # 원본은 검은 본문에, 명도 반전본은 색 막대 안의 흰 숫자에 유리하다.
    with Image.open(path) as image:
        width, height = image.size
        inverted = ImageOps.invert(image.convert("L"))
        with tempfile.NamedTemporaryFile(suffix=".png") as temporary:
            inverted.save(temporary.name)
            candidates = [(str(path), "tesseract"), (temporary.name, "tesseract_inverted")]
            result, errors = [], []
            for candidate, method in candidates:
                proc = subprocess.run([executable, candidate, "stdout", "-l", "eng", "--psm", "11", "tsv"],
                                      capture_output=True, text=True, timeout=90)
                if proc.returncode:
                    errors.append(proc.stderr.strip() or "알 수 없는 오류")
                    continue
                lines = proc.stdout.splitlines()
                if not lines:
                    continue
                header = lines[0].split("\t")
                for line in lines[1:]:
                    row = dict(zip(header, line.split("\t")))
                    text = (row.get("text") or "").strip()
                    try:
                        confidence = float(row.get("conf", -1)) / 100.0
                        x, y = float(row.get("left", 0)), float(row.get("top", 0))
                        w, h = float(row.get("width", 0)), float(row.get("height", 0))
                    except ValueError:
                        continue
                    if text and confidence >= 0.35 and w > 0 and h > 0:
                        result.append({"text": text, "confidence": confidence,
                                       "box": [x / width, y / height, w / width, h / height],
                                       "method": method})
    if not result and errors:
        return [], ["Tesseract OCR 실패: " + "; ".join(errors)]
    return result, []


def _same_word(left: dict, right: dict) -> bool:
    a, b = left["box"], right["box"]
    ax, ay = a[0] + a[2] / 2, a[1] + a[3] / 2
    bx, by = b[0] + b[2] / 2, b[1] + b[3] / 2
    if abs(ax - bx) >= 0.05 or abs(ay - by) >= 0.05:
        return False
    # 서로 다른 OCR이 한 글자만 다르게 읽은 같은 상자는 충돌을 두 번
    # 주장으로 만들지 않는다. 전혀 다른 단어는 같은 위치여도 병합하지 않는다.
    a_text = "".join(ch for ch in left["text"].casefold() if ch.isalnum())
    b_text = "".join(ch for ch in right["text"].casefold() if ch.isalnum())
    return a_text == b_text or SequenceMatcher(None, a_text, b_text).ratio() >= .82


def _merge_words(vision: list[dict], tesseract: list[dict]) -> list[dict]:
    merged = list(vision)
    for word in tesseract:
        existing = next((item for item in merged if _same_word(item, word)), None)
        if existing:
            old, new = existing["text"], word["text"]
            old_cmp = "".join(ch for ch in old.casefold() if ch.isalnum())
            new_cmp = "".join(ch for ch in new.casefold() if ch.isalnum())
            # `Propagationy` 대 `Propagation`처럼 한 OCR의 끝 글자가
            # 덧붙은 경우에는 공통 접두어인 짧은 쪽을 선택한다. 그 밖의
            # 충돌은 더 높은 신뢰도의 문자열을 남긴다.
            if old_cmp.startswith(new_cmp) or new_cmp.startswith(old_cmp):
                existing["text"] = min((old, new), key=lambda text: len("".join(ch for ch in text if ch.isalnum())))
            elif word["confidence"] > existing["confidence"]:
                existing["text"] = new
            existing["confidence"] = max(existing["confidence"], word["confidence"])
            existing["method"] = "macos_vision+tesseract"
        else:
            merged.append(word)
    return sorted(merged, key=lambda x: (x["box"][1], x["box"][0]))


def _components(mask: np.ndarray, minimum: int) -> list[tuple[int, int, int, int, int]]:
    """Boolean mask의 4-이웃 성분: x, y, width, height, pixels."""
    height, width = mask.shape
    seen = np.zeros_like(mask, dtype=bool)
    found = []
    for start_y, start_x in zip(*np.where(mask & ~seen)):
        if seen[start_y, start_x]:
            continue
        queue = deque([(int(start_y), int(start_x))])
        seen[start_y, start_x] = True
        n = 0
        lo_x = hi_x = int(start_x); lo_y = hi_y = int(start_y)
        while queue:
            y, x = queue.popleft(); n += 1
            lo_x, hi_x = min(lo_x, x), max(hi_x, x)
            lo_y, hi_y = min(lo_y, y), max(hi_y, y)
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < height and 0 <= nx < width and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True; queue.append((ny, nx))
        if n >= minimum:
            found.append((lo_x, lo_y, hi_x - lo_x + 1, hi_y - lo_y + 1, n))
    return found


def _chart_structure(path: Path, words: list[dict], labels: list[dict]) -> dict:
    """보수적인 막대 차트 감지. 눈금/축 없이 색 덩어리만으로는 차트라 확정하지 않는다."""
    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((1400, 1400))
        rgb = np.asarray(image, dtype=np.uint8)
    height, width = rgb.shape[:2]
    mx, mn = rgb.max(axis=2), rgb.min(axis=2)
    saturation = (mx.astype(np.int16) - mn.astype(np.int16))
    # 설문 누적 막대는 아주 옅은 파스텔 면을 자주 쓴다. 채도 하한만 낮추고
    # 큰 면적·정렬·숫자 조건은 그대로 유지해 글자 색을 막대로 세지 않는다.
    colored = (saturation > 15) & (mx > 80) & (mn < 248)
    components = _components(colored, max(30, width * height // 25000))
    candidates = []
    for x, y, w, h, pixels in components:
        fill = pixels / max(w * h, 1)
        if fill < .48 or w < max(5, width * .012) or h < max(5, height * .012):
            continue
        # 값이 큰 막대는 그림 너비 대부분을 차지할 수 있다. 72% 같은
        # 임의 상한은 상위 범주를 잃게 하므로, 사실상 페이지 배경인 경우만 뺀다.
        if w > width * .96 or h > height * .96:
            continue
        if max(w / h, h / w) >= 1.35:
            candidates.append({"box": [x / width, y / height, w / width, h / height], "fill": round(fill, 3)})

    bars = candidates
    numeric_words = [word for word in words if any(char.isdigit() for char in word["text"])]
    numeric = len(numeric_words)
    # 흐름도 상자도 색칠된 긴 사각형처럼 보인다. 막대라면 보통 같은 기준선
    # (세로 막대) 또는 같은 시작선(가로 막대)을 공유하고, 각 막대의 끝/축
    # 근처에 눈금 숫자가 있다. 페이지 어딘가의 숫자를 세는 것은 충분한
    # 근거가 아니다.
    def near_number(bar: dict) -> bool:
        x, y, w, h = bar["box"]
        for word in numeric_words:
            wx, wy, ww, wh = word["box"]
            cx, cy = wx + ww / 2, wy + wh / 2
            if (x - .10 <= cx <= x + w + .10 and y - .10 <= cy <= y + h + .10):
                return True
        return False
    numeric_near = sum(near_number(bar) for bar in bars)
    vertical = sum(1 for bar in bars if sum(1 for other in bars
                   if abs((bar["box"][1] + bar["box"][3]) - (other["box"][1] + other["box"][3])) < .035) >= 3)
    horizontal = sum(1 for bar in bars if sum(1 for other in bars
                     if abs(bar["box"][0] - other["box"][0]) < .035) >= 3)
    chart_label = max((label["confidence"] for label in labels if label["text"] in ("chart", "diagram", "graph")), default=0.0)
    # 여러 직사각형 + 숫자 눈금은 색채만 쓰는 사진/일러스트보다 강한 근거다.
    # 범례의 짧은 색 선·문자 조각은 같은 y에 줄지어 있어도 막대가 아니다.
    # 실제 막대는 이미지 면적의 최소 0.1% 이상인 색 면을 하나 이상 가진다.
    largest_area = max((bar["box"][2] * bar["box"][3] for bar in bars), default=0.0)
    # 누적 가로 막대는 조각마다 시작점이 다르므로 위의 공통 시작/끝 조건으로는
    # 빠진다. 같은 y줄에 여러 조각이 이어지고 그러한 줄이 둘 이상일 때만 별도
    # 근거로 인정한다. 한 줄짜리 범례·진행 막대는 여기서 제외된다.
    rows: list[list[dict]] = []
    for bar in sorted(bars, key=lambda item: item["box"][1] + item["box"][3] / 2):
        center_y = bar["box"][1] + bar["box"][3] / 2
        row = next((group for group in rows
                    if abs(np.mean([item["box"][1] + item["box"][3] / 2 for item in group]) - center_y) < .035), None)
        if row is None:
            rows.append([bar])
        else:
            row.append(bar)
    stacked_rows = 0
    for row in rows:
        if len(row) < 2:
            continue
        left = min(item["box"][0] for item in row)
        right = max(item["box"][0] + item["box"][2] for item in row)
        if right - left >= .40:
            stacked_rows += 1
    stacked = stacked_rows >= 2 and len(bars) >= 5 and numeric >= 3
    # 각 행이 하나의 연한 막대로 칠해진 설문표는 시작점이 범주명 여백 때문에
    # 조금씩 다를 수 있다. 길고 높이가 같은 세 행 + 근처 수치를 요구한다.
    long_rows = [bar for bar in bars if bar["box"][2] >= .35]
    parallel_rows = len(long_rows) >= 3 and numeric_near >= 2 and (
        max(item["box"][3] for item in long_rows) - min(item["box"][3] for item in long_rows) <= .025
    )
    aligned_bars = numeric_near >= 2 and (vertical >= 3 or horizontal >= 3 or parallel_rows)
    is_bar = len(bars) >= 3 and largest_area >= .001 and (aligned_bars or stacked)
    is_chart = is_bar or (chart_label >= .65 and numeric >= 2)
    return {"type": "bar_chart" if is_bar else ("chart" if is_chart else "unknown"),
            "confidence": .86 if is_bar else (.70 if is_chart else 0.0),
            "bars": bars[:48], "numeric_tokens": numeric, "numeric_near_bars": numeric_near,
            "largest_bar_area": round(largest_area, 5),
            "classification_hint": chart_label}


def _line_chart_structure(path: Path, words: list[dict]) -> dict:
    """색상별 얇은 연속선을 이용해 선 그래프를 보수적으로 감지한다.

    축·문자 획을 선으로 세지 않기 위해 색채가 있고, x축의 넓은 범위를 지나며,
    각 x열에서 두께가 작은 색 성분만 후보로 삼는다. 막대의 넓은 색 면은 이
    조건을 통과하지 못한다.
    """
    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((1400, 1400))
        rgb = np.asarray(image, dtype=np.uint8)
    height, width = rgb.shape[:2]
    maximum, minimum = rgb.max(axis=2), rgb.min(axis=2)
    saturation = maximum.astype(np.int16) - minimum.astype(np.int16)
    # 언론 그래프의 가는 남색 선처럼 저채도 계열도 있어 55는 지나치게 높다.
    # 무채색 눈금은 제외하면서 20까지 허용하고, 이후 x-연속성/두께 조건으로
    # 문자와 장식선을 다시 걸러 낸다.
    colored = (saturation >= 20) & (maximum >= 80) & (minimum <= 235)
    if width < 80 or height < 80 or colored.sum() < 40:
        return {"type": "unknown", "confidence": 0.0, "series": 0}
    # 색상은 정확히 같지 않을 수 있으므로 지배 채널과 밝기만으로 12개 버킷을
    # 만든다. 안티앨리어싱된 같은 선은 보통 같은 버킷에 남는다.
    dominant = rgb.argmax(axis=2)
    brightness = (maximum // 64).clip(0, 3)
    series = []
    for channel in range(3):
        for level in range(4):
            mask = colored & (dominant == channel) & (brightness == level)
            columns = np.where(mask.any(axis=0))[0]
            if len(columns) < width * .28:
                continue
            thickness = [int(mask[:, column].sum()) for column in columns]
            median_thickness = float(np.median(thickness)) if thickness else 0.0
            # 선은 대다수 열에서 1~몇 픽셀이고, 긴 수평 밑줄은 수치 변화가
            # 거의 없으므로 제외한다.
            centers = [float(np.median(np.where(mask[:, column])[0])) for column in columns]
            if median_thickness > max(6.0, height * .018) or np.std(centers) < height * .018:
                continue
            series.append({"channel": int(channel), "brightness_bucket": int(level),
                           "x_coverage": round(len(columns) / width, 3),
                           "median_thickness": round(median_thickness, 2)})
    numeric = sum(1 for word in words if any(char.isdigit() for char in word["text"]))
    # 한 계열이어도 추세선일 수 있으나, 그 경우는 불확실하므로 그래프로
    # 확정하지 않는다. 서로 다른 두 색 얇은 계열과 수치 축을 요구한다.
    if len(series) >= 2 and numeric >= 2:
        return {"type": "line_chart", "confidence": .78, "series": len(series),
                "numeric_tokens": numeric, "series_evidence": series[:12]}
    return {"type": "unknown", "confidence": 0.0, "series": 0}


def _pie_chart_structure(path: Path, words: list[dict]) -> dict:
    """색 조각이 채운 원형 영역만으로 원형 차트를 감지한다."""
    with Image.open(path) as image:
        image = image.convert("RGB")
        image.thumbnail((1400, 1400))
        rgb = np.asarray(image, dtype=np.uint8)
    height, width = rgb.shape[:2]
    maximum, minimum = rgb.max(axis=2), rgb.min(axis=2)
    saturation = maximum.astype(np.int16) - minimum.astype(np.int16)
    colored = (saturation >= 24) & (maximum >= 90) & (minimum <= 242)
    components = _components(colored, max(100, width * height // 1000))
    candidates = []
    for x, y, w, h, pixels in components:
        ratio = w / max(h, 1)
        fill = pixels / max(w * h, 1)
        if not (.72 <= ratio <= 1.28 and fill >= .58 and min(w, h) >= min(width, height) * .18):
            continue
        region = rgb[y:y + h, x:x + w]
        region_max, region_min = region.max(axis=2), region.min(axis=2)
        region_colored = (region_max.astype(np.int16) - region_min.astype(np.int16) >= 24) & (region_max >= 90)
        dominant = region.argmax(axis=2)
        brightness = (region_max // 64).clip(0, 3)
        # 서로 다른 두 지배색이 원 내부의 충분한 면적을 차지해야 한다. 단색
        # 원형 아이콘이나 로고는 제외한다.
        colors = []
        for channel in range(3):
            for level in range(4):
                share = float((region_colored & (dominant == channel) & (brightness == level)).sum()) / max(int(region_colored.sum()), 1)
                if share >= .08:
                    colors.append((channel, level))
        if len(colors) < 2:
            continue
        candidates.append({"box": [x / width, y / height, w / width, h / height],
                           "fill": round(fill, 3), "color_groups": len(colors)})
    numeric = sum(1 for word in words if any(char.isdigit() for char in word["text"]))
    # 회색 조각은 saturation 마스크에서 빠져 다색 원 하나로 연결되지 않는다.
    # 그래서 색을 거칠게 양자화한 뒤, 서로 다른 세 조각의 합집합이 화면상
    # 원에 가까운 외접 상자를 이루는 경우도 검사한다. 텍스트 숫자와 세 조각을
    # 동시에 요구해 원형 로고를 차트로 오인하지 않도록 한다.
    quantized = (rgb // 48).astype(np.uint8)
    slice_boxes = []
    for color in np.unique(quantized.reshape(-1, 3), axis=0):
        if int(color.min()) >= 5:  # 거의 흰 배경
            continue
        mask = (quantized == color).all(axis=2)
        for x, y, w, h, pixels in _components(mask, max(100, width * height // 1000)):
            if pixels / max(width * height, 1) < .008:
                continue
            slice_boxes.append((x, y, w, h, pixels))
    grouped_pie = None
    if len(slice_boxes) >= 3:
        left, top = min(item[0] for item in slice_boxes), min(item[1] for item in slice_boxes)
        right = max(item[0] + item[2] for item in slice_boxes)
        bottom = max(item[1] + item[3] for item in slice_boxes)
        envelope_w, envelope_h = right - left, bottom - top
        # envelope_w/h는 이미 픽셀 단위다. 정규화 좌표의 종횡비를 다시 보정하면
        # 가로로 넓은 캔버스에서 직사각형 전체를 원으로 오인하게 된다.
        physical_ratio = envelope_w / max(envelope_h, 1)
        fill = sum(item[4] for item in slice_boxes) / max(envelope_w * envelope_h, 1)
        if .72 <= physical_ratio <= 1.28 and fill >= .42 and min(envelope_w, envelope_h) >= min(width, height) * .18:
            grouped_pie = {"box": [left / width, top / height, envelope_w / width, envelope_h / height],
                           "fill": round(fill, 3), "color_groups": len(slice_boxes)}
    if candidates and numeric >= 1:
        best = max(candidates, key=lambda item: item["fill"] * item["box"][2] * item["box"][3])
        return {"type": "pie_chart", "confidence": .82, "slices_at_least": best["color_groups"],
                "numeric_tokens": numeric, "circle": best}
    if grouped_pie and numeric >= 1:
        return {"type": "pie_chart", "confidence": .78, "slices_at_least": grouped_pie["color_groups"],
                "numeric_tokens": numeric, "circle": grouped_pie}
    return {"type": "unknown", "confidence": 0.0, "slices_at_least": 0}


def _runs(values: np.ndarray, threshold: float) -> list[tuple[int, int]]:
    """투영 비율이 threshold 이상인 연속 선 구간을 하나의 격자선으로 합친다."""
    active = values >= threshold
    result, start = [], None
    for index, hit in enumerate(active.tolist() + [False]):
        if hit and start is None:
            start = index
        elif not hit and start is not None:
            result.append((start, index - 1)); start = None
    return result


def _table_structure(path: Path) -> dict:
    """선이 있는 표만 확정한다. 텍스트 배열만으로 표라고 추정하지 않는다."""
    with Image.open(path) as image:
        image = image.convert("L")
        image.thumbnail((1600, 1600))
        gray = np.asarray(image, dtype=np.uint8)
    # 얇은 회색 표선도 잡되 글자 조각은 행/열의 대부분을 채우지 못한다.
    ink = gray < 205
    horizontal = _runs(ink.mean(axis=1), .42)
    vertical = _runs(ink.mean(axis=0), .42)
    # 서로 가까운 장식선·밑줄은 표가 아니다. 최소 2x2 셀 격자가 필요하다.
    if len(horizontal) < 3 or len(vertical) < 3:
        return {"type": "unknown", "confidence": 0.0, "rows": 0, "columns": 0}
    rows, columns = len(horizontal) - 1, len(vertical) - 1
    if rows < 2 or columns < 2 or rows * columns > 400:
        return {"type": "unknown", "confidence": 0.0, "rows": 0, "columns": 0}
    return {"type": "table", "confidence": .84, "rows": rows, "columns": columns,
            "horizontal_lines": len(horizontal), "vertical_lines": len(vertical)}


def _lines(words: list[dict]) -> list[dict]:
    rows: list[list[dict]] = []
    for word in sorted((w for w in words if w["confidence"] >= .62), key=lambda x: (x["box"][1], x["box"][0])):
        target = next((row for row in rows if abs(np.mean([w["box"][1] + w["box"][3] / 2 for w in row]) - (word["box"][1] + word["box"][3] / 2)) < .022), None)
        if target is None:
            rows.append([word])
        else:
            target.append(word)
    result = []
    for row in rows:
        row.sort(key=lambda x: x["box"][0])
        text = " ".join(w["text"] for w in row)
        if len(text) >= 3 and any(char.isalpha() for char in text):
            result.append({"text": text, "confidence": round(float(np.mean([w["confidence"] for w in row])), 3),
                           "method": "+".join(sorted({w["method"] for w in row}))})
    return result


def _vlm_hypothesis(path: Path) -> tuple[dict | None, list[str]]:
    """준비된 로컬 VLM만 호출한다. 모델의 자유 생성은 그래프 근거가 아니다."""
    # 기본값은 비토큰·검증 가능 분석이다. VLM은 자유 생성이므로 사용자가
    # 명시적으로 NAI_DOCUMENT_VLM=1을 준 보조 분석에서만 호출한다.
    if os.environ.get("NAI_DOCUMENT_VLM", "0") != "1":
        return None, []
    def complete(candidate: Path) -> bool:
        if (candidate / "model.safetensors").is_file():
            return True
        index = candidate / "model.safetensors.index.json"
        if not index.is_file():
            return False
        try:
            shards = set(json.loads(index.read_text(encoding="utf-8")).get("weight_map", {}).values())
        except (OSError, json.JSONDecodeError):
            return False
        return bool(shards) and all((candidate / shard).is_file() for shard in shards)
    model = next((candidate for candidate in VLM_MODELS if complete(candidate)), None)
    if not (VLM_PYTHON.is_file() and VLM_SOURCE.is_file() and model):
        return None, []
    try:
        proc = subprocess.run([str(VLM_PYTHON), str(VLM_SOURCE), str(path), "--model", str(model)],
                              capture_output=True, text=True, timeout=360)
        data = json.loads(proc.stdout or "{}")
        if proc.returncode or data.get("error"):
            return None, ["로컬 VLM 의미 분석 실패: " + str(data.get("error") or proc.stderr.strip())]
        return data, ([str(data["warning"])] if data.get("warning") else [])
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return None, ["로컬 VLM 의미 분석 실패: %s" % exc]


def _objects(path: Path) -> tuple[list[dict], list[str]]:
    """객체 검출은 토큰 생성 없이 상자와 class만 낸다."""
    if not (VLM_PYTHON.is_file() and OBJECT_SOURCE.is_file() and OBJECT_MODEL.is_file()):
        return [], []
    try:
        env = dict(os.environ, YOLO_CONFIG_DIR=str(ROOT / ".nai-tools" / "ultralytics"))
        proc = subprocess.run([str(VLM_PYTHON), str(OBJECT_SOURCE), str(path)], capture_output=True, text=True,
                              timeout=120, env=env)
        data = json.loads(proc.stdout or "{}")
        if proc.returncode or data.get("error"):
            return [], ["객체 검출 실패: " + str(data.get("error") or proc.stderr.strip())]
        return list(data.get("objects") or []), []
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return [], ["객체 검출 실패: %s" % exc]


def _people_pose(path: Path) -> tuple[list[dict], list[str]]:
    """사람 상자/관절만 읽는다. 행동 명칭은 이 단계에서 만들지 않는다."""
    if not (VLM_PYTHON.is_file() and POSE_SOURCE.is_file() and POSE_MODEL.is_file()):
        return [], []
    try:
        env = dict(os.environ, YOLO_CONFIG_DIR=str(ROOT / ".nai-tools" / "ultralytics"))
        proc = subprocess.run([str(VLM_PYTHON), str(POSE_SOURCE), str(path)], capture_output=True, text=True,
                              timeout=120, env=env)
        data = json.loads(proc.stdout or "{}")
        if proc.returncode or data.get("error"):
            return [], ["사람 자세 검출 실패: " + str(data.get("error") or proc.stderr.strip())]
        return list(data.get("people") or []), []
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return [], ["사람 자세 검출 실패: %s" % exc]


def _hand_object_contacts(people: list[dict], objects: list[dict]) -> list[dict]:
    """손 관절과 물체 상자의 접촉 후보를 좌표로만 판정한다.

    상자 가까움은 '들다' 같은 행위가 아니다. 반환값도 그 기하 관찰을 명시하며
    행동 추론은 별도의 HOI 모델/검증 데이터가 준비될 때까지 하지 않는다.
    """
    contacts, seen = [], set()
    for person_index, person in enumerate(people):
        keypoints = person.get("keypoints") or []
        for hand_name, point_index in (("왼손", 9), ("오른손", 10)):
            if point_index >= len(keypoints):
                continue
            point = keypoints[point_index]
            if float(point.get("confidence", 0)) < .62:
                continue
            px, py = float(point["x"]), float(point["y"])
            for item in objects:
                if item.get("label") == "person" or float(item.get("confidence", 0)) < .60:
                    continue
                x, y, width, height = [float(value) for value in item["box"]]
                pad = max(.025, min(.075, max(width, height) * .22))
                if x - pad <= px <= x + width + pad and y - pad <= py <= y + height + pad:
                    key = (person_index, hand_name, item["label"], round(x, 3), round(y, 3))
                    if key not in seen:
                        seen.add(key)
                        contacts.append({"person": person_index + 1, "hand": hand_name,
                                         "object": item["label"], "confidence": round(min(
                                             float(person.get("confidence", 0)), float(point["confidence"]),
                                             float(item["confidence"])), 3)})
    return contacts


def _spatial_relations(objects: list[dict]) -> list[dict]:
    """검출 상자에서 직접 증명되는 쌍별 공간 관계만 만든다."""
    relations = []
    for first_index, first in enumerate(objects[:16]):
        if float(first.get("confidence", 0)) < .60:
            continue
        ax, ay, aw, ah = [float(value) for value in first["box"]]
        acx, acy = ax + aw / 2, ay + ah / 2
        for second in objects[first_index + 1:16]:
            if float(second.get("confidence", 0)) < .60:
                continue
            bx, by, bw, bh = [float(value) for value in second["box"]]
            bcx, bcy = bx + bw / 2, by + bh / 2
            confidence = round(min(float(first["confidence"]), float(second["confidence"])), 3)
            # 중심 거리뿐 아니라 두 상자 크기도 고려해 서로 거의 겹친 대상에는
            # 좌/우·상/하를 강제하지 않는다.
            if abs(acx - bcx) >= max(.12, (aw + bw) * .55):
                relations.append({"subject": first["label"], "object": second["label"],
                                  "relation": "왼쪽" if acx < bcx else "오른쪽", "confidence": confidence})
            if abs(acy - bcy) >= max(.12, (ah + bh) * .55):
                relations.append({"subject": first["label"], "object": second["label"],
                                  "relation": "위" if acy < bcy else "아래", "confidence": confidence})
            # 작은 상자가 큰 상자 안쪽에 완전히 들어갈 때만 포함을 말한다.
            if bx <= ax and by <= ay and ax + aw <= bx + bw and ay + ah <= by + bh:
                relations.append({"subject": first["label"], "object": second["label"],
                                  "relation": "안", "confidence": confidence})
            elif ax <= bx and ay <= by and bx + bw <= ax + aw and by + bh <= ay + ah:
                relations.append({"subject": second["label"], "object": first["label"],
                                  "relation": "안", "confidence": confidence})
    return relations[:32]


def analyze_image(path: str | os.PathLike, location: str) -> dict[str, Any]:
    """한 이미지의 OCR/장면 단서/차트 구조와 그래프에 쓸 사실 후보를 반환한다."""
    image_path = Path(path)
    if not image_path.is_file():
        raise VisualError("이미지를 찾지 못했습니다: %s" % image_path)
    vision, labels, warnings = _vision_words(image_path)
    tess, tess_warnings = _tesseract_words(image_path)
    warnings.extend(tess_warnings)
    words = _merge_words(vision, tess)
    # 원형 차트는 색 조각이 문자·범례와 함께 작은 직사각형 성분을 만들 수
    # 있어 일반 막대/선 휴리스틱보다 먼저, 더 구체적인 원형 기하를 검사한다.
    structure = _pie_chart_structure(image_path, words)
    bars = _chart_structure(image_path, words, labels)
    # 회색 조각을 보완한 원형 추정(.78)은 강한 막대 증거보다 약하다.
    if structure["type"] == "pie_chart" and structure["confidence"] < .80 and bars["type"] == "bar_chart" and bars["largest_bar_area"] >= .01:
        structure = bars
    # 선의 x-연속성은 작은 색 문자 조각이 섞인 막대 후보보다 강한 구조 근거다.
    # 다만 실제 막대의 넓은 색 면이 여럿 있으면 그것이 더 직접적인 구조 증거다.
    if structure["type"] == "unknown":
        line = _line_chart_structure(image_path, words)
        if bars["type"] == "bar_chart" and bars["largest_bar_area"] >= .01:
            structure = bars
        elif line["type"] != "unknown":
            structure = line
        else:
            structure = bars
    table = _table_structure(image_path) if structure["type"] == "unknown" else None
    if table and table["type"] == "table":
        structure = table
    objects, object_warnings = _objects(image_path) if structure["type"] == "unknown" else ([], [])
    warnings.extend(object_warnings)
    # 객체 검출과 관절 검출이 모두 사람을 지지할 때만 관계를 계산한다. 사람 없는
    # 도표/PDF 페이지에 포즈 모델을 적용해 상황을 지어내지 않는다.
    people, pose_warnings = _people_pose(image_path) if any(item.get("label") == "person" for item in objects) else ([], [])
    warnings.extend(pose_warnings)
    contacts = _hand_object_contacts(people, objects)
    spatial_relations = _spatial_relations(objects)
    # CPU VLM은 매 그림마다 가중치를 다시 읽으면 문서 전체가 지나치게 느려진다.
    # 텍스트·막대 구조만으로 충분한 차트는 건너뛰고, 의미가 필요한 도식/사진에
    # 우선 배정한다. 모든 이미지를 보고 싶으면 환경 변수로 명시한다.
    needs_semantics = structure["type"] == "unknown" or os.environ.get("NAI_DOCUMENT_VLM_ALL") == "1"
    hypothesis, hypothesis_warnings = _vlm_hypothesis(image_path) if needs_semantics else (None, [])
    warnings.extend(hypothesis_warnings)
    facts = []
    for line in _lines(words):
        # OCR 두 엔진 모두 고신뢰이거나 Vision 하나가 매우 확실한 문장만 사실 후보.
        if line["confidence"] >= .82 or ("+" in line["method"] and line["confidence"] >= .70):
            facts.append({"kind": "visual_text", "text": "이미지에 '%s'라는 문구가 보인다." % line["text"],
                          "location": location, "confidence": line["confidence"], "method": line["method"]})
    if structure["type"] == "bar_chart":
        facts.append({"kind": "chart_structure", "text": "이미지의 픽셀 구조에서 막대 %d개와 수치 눈금이 확인되는 막대 차트가 감지된다." % len(structure["bars"]),
                      "location": location, "confidence": structure["confidence"], "method": "pixel_structure+ocr"})
    if structure["type"] == "line_chart":
        facts.append({"kind": "chart_structure", "text": "이미지의 색상별 얇은 연속선 %d개와 수치 눈금이 확인되는 선 그래프가 감지된다." % structure["series"],
                      "location": location, "confidence": structure["confidence"], "method": "pixel_line_structure+ocr"})
    if structure["type"] == "pie_chart":
        facts.append({"kind": "chart_structure", "text": "이미지의 채워진 원형 색 조각과 수치 표기에서 최소 %d개 범주의 원형 차트가 감지된다." % structure["slices_at_least"],
                      "location": location, "confidence": structure["confidence"], "method": "pixel_pie_structure+ocr"})
    if structure["type"] == "table":
        facts.append({"kind": "table_structure", "text": "이미지의 격자선에서 %d행 %d열 표 구조가 감지된다." % (structure["rows"], structure["columns"]),
                      "location": location, "confidence": structure["confidence"], "method": "pixel_table_structure"})
    for item in objects:
        facts.append({"kind": "visual_object", "text": "이미지에서 %s 객체가 검출된다." % item["label"],
                      "location": location, "confidence": float(item["confidence"]), "method": "yolo_object_detection"})
    for relation in spatial_relations:
        facts.append({"kind": "visual_relation", "text": "이미지에서 %s 객체는 %s 객체의 %s에 있다." %
                      (relation["subject"], relation["object"], relation["relation"]),
                      "location": location, "confidence": relation["confidence"],
                      "method": "yolo_spatial_boxes"})
    for contact in contacts:
        facts.append({"kind": "visual_contact_geometry",
                      "text": "이미지에서 사람 %d의 %s 관절이 %s 객체 상자와 겹치거나 매우 가깝다." %
                              (contact["person"], contact["hand"], contact["object"]),
                      "location": location, "confidence": contact["confidence"],
                      "method": "yolo_pose+yolo_object_boxes"})
    semantic = (hypothesis or {}).get("parsed") or {}
    semantic_type = str(semantic.get("image_type", "")).casefold().replace(" ", "_")
    if structure["type"] == "bar_chart" and semantic_type in ("bar_chart", "chart", "horizontal_bar_chart"):
        facts.append({"kind": "visual_semantic", "text": "이미지는 언어 시각 모델과 픽셀 구조 분석이 함께 막대 차트로 분류한다.",
                      "location": location, "confidence": .75, "method": "local_vlm+pixel_structure+ocr"})
    return {"location": location, "path": image_path.name, "words": words, "labels": labels,
            "structure": structure, "objects": objects, "people": people, "spatial_relations": spatial_relations,
            "situations": [{"type": "hand_object_proximity", "status": "geometry_observed_not_action",
                            **contact} for contact in contacts], "semantic_hypothesis": hypothesis,
            "facts": facts[:24], "warnings": list(dict.fromkeys(warnings))}
