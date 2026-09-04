# -*- coding: utf-8 -*-
"""로컬 VLM에 그림의 '보이는 것'만 JSON으로 기술하게 하는 작은 어댑터.

이 출력은 독립 사실이 아니다. document_visual이 OCR·구조 근거와 대조하기 전에는
`hypothesis`로만 보관한다. 가중치와 런타임이 없으면 실패하지 않고 호출하지 않는다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROMPT = """Analyze this scientific/document image conservatively. Return JSON only.
Schema: {\"image_type\": one of [photo, chart, table, diagram, equation, unknown],
\"visible_entities\": [literal labels or objects],
\"visible_relationships\": [only directly drawn arrows, containment, or ordering],
\"uncertainties\": [unreadable or inferred parts]}.
Do not invent causes, names, numbers, or scientific facts. Do not repeat a label as a relationship.
If a chart/table/diagram cannot be read reliably, say so in uncertainties."""


def run(image: str, model: str) -> dict:
    try:
        import torch
        from PIL import Image
        from transformers import AutoModelForImageTextToText, AutoProcessor
    except ImportError as exc:
        raise RuntimeError("VLM 런타임이 준비되지 않았습니다: %s" % exc) from exc
    model_path = Path(model)
    if not ((model_path / "model.safetensors").is_file() or (model_path / "model.safetensors.index.json").is_file()):
        raise RuntimeError("VLM 가중치가 준비되지 않았습니다: %s" % model_path)
    processor = AutoProcessor.from_pretrained(model_path, local_files_only=True)
    # CPU fallback을 명시한다. Metal이 노출된 환경은 별도 MLX 어댑터가 담당한다.
    loaded = AutoModelForImageTextToText.from_pretrained(model_path, local_files_only=True,
                                                          torch_dtype=torch.float32)
    loaded.eval()
    picture = Image.open(image).convert("RGB")
    if getattr(loaded.config, "model_type", "").startswith("qwen2_5_vl"):
        # Qwen은 이미지 토큰 수를 원본 해상도에서 계산하므로 공식 helper로
        # 입력을 만든다. 이 경로도 로컬 파일만 읽는다.
        from qwen_vl_utils import process_vision_info
        messages = [{"role": "user", "content": [{"type": "image", "image": str(Path(image).resolve())},
                                                      {"type": "text", "text": PROMPT}]}]
        prompt = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        image_inputs, video_inputs = process_vision_info(messages)
        inputs = processor(text=[prompt], images=image_inputs, videos=video_inputs, padding=True, return_tensors="pt")
    else:
        messages = [{"role": "user", "content": [{"type": "image"}, {"type": "text", "text": PROMPT}]}]
        prompt = processor.apply_chat_template(messages, add_generation_prompt=True)
        inputs = processor(text=prompt, images=[picture], return_tensors="pt")
    with torch.inference_mode():
        generated = loaded.generate(**inputs, max_new_tokens=220, do_sample=False)
    completion = generated[0][inputs["input_ids"].shape[-1]:]
    raw = processor.decode(completion, skip_special_tokens=True).strip()
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        return {"raw": raw, "parsed": None, "warning": "VLM이 JSON 형식으로 답하지 않았습니다"}
    try:
        parsed = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return {"raw": raw, "parsed": None, "warning": "VLM JSON을 해석하지 못했습니다"}
    return {"raw": raw, "parsed": parsed, "warning": None}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("image")
    parser.add_argument("--model", default="data/models/Qwen2.5-VL-3B-Instruct")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(run(args.image, args.model), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"error": "%s: %s" % (type(exc).__name__, exc)}, ensure_ascii=False))
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
