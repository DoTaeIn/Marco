# -*- coding: utf-8 -*-
"""사람이 라벨한 문장에서 **배우는** 발췌 분류 부품.

손으로 규칙을 쓰지 않는다. 낱말 목록을 파이썬에 적으면 말투가 하나 늘 때마다
코드가 늘고, 다른 언어에서는 아무것도 따라오지 않는다. 여기서는 사람이 적어 둔
라벨만 재료로 쓰고, 글자 n-gram 은 이미 있는 부품(``encoder._character_grams``)을
그대로 쓴다.

정확도는 **한 번도 안 본 문장**으로만 말한다. 임계값은 학습 안 교차검증으로
고른다 — 학습 적합도로 고르면 98%가 나오지만 그 값은 일반화되지 않는다(실제로
그렇게 골랐을 때 평가가 22.2%로 최빈 기준선보다 나빴다).
"""
from __future__ import annotations

import collections
import json
import math
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
LABELS = ROOT / "docs" / "ko" / "_발췌꼴.json"

# 학습 안 5겹 교차검증이 고른 값. 평가 자료는 이 선택에 쓰이지 않았다.
THRESHOLD = 0.20
# 한 문장에만 나온 gram 은 외우기 쉬운 특징이라 뺀다.
MIN_DOCS = 2
SMOOTHING = 0.5


def _rows(path):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    return [(sentence, [x for x in form.split(",") if x])
            for form, sentences in (doc.get("꼴") or {}).items()
            for sentence in sentences]


class LabelLearnedClassifier:
    """``PassageBackend`` 규약. 라벨 자료가 없으면 아무것도 단정하지 않는다."""

    component_id = "label-learned-passage-v1"

    def __init__(self, labels=None, threshold=THRESHOLD):
        self.path = Path(labels or os.environ.get("NAI_PASSAGE_LABELS") or LABELS)
        self.threshold = threshold
        self._model = None

    def _train(self):
        from encoder import _character_grams
        rows = _rows(self.path)
        frequency = collections.Counter()
        for sentence, _ in rows:
            frequency.update(set(_character_grams(sentence)))
        keep = {gram for gram, count in frequency.items() if count >= MIN_DOCS}
        per_label = collections.defaultdict(collections.Counter)
        total = collections.Counter()
        for sentence, labels in rows:
            grams = {g: n for g, n in _character_grams(sentence).items() if g in keep}
            total.update(grams)
            for label in labels:
                per_label[label].update(grams)
        self._model = {
            "keep": keep, "per_label": per_label, "total": total,
            "labels": sorted(per_label),
            "sum": {label: sum(counts.values()) for label, counts in per_label.items()},
            "grand": sum(total.values()), "vocabulary": max(len(total), 1),
        }
        return self._model

    def scores(self, text):
        from encoder import _character_grams
        model = self._model or self._train()
        grams = {g: n for g, n in _character_grams(text).items() if g in model["keep"]}
        out = {}
        for label in model["labels"]:
            rest = model["grand"] - model["sum"][label]
            score = 0.0
            for gram, n in grams.items():
                here = (model["per_label"][label][gram] + SMOOTHING) / (
                    model["sum"][label] + SMOOTHING * model["vocabulary"])
                elsewhere = (model["total"][gram] - model["per_label"][label][gram]
                             + SMOOTHING) / (rest + SMOOTHING * model["vocabulary"])
                score += n * math.log(here / elsewhere)
            out[label] = score / max(len(grams), 1)
        return out

    def classify(self, text):
        if not text or not str(text).strip():
            return []
        if not self.path.is_file():
            # 배울 자료가 없으면 꼴을 지어내지 않는다. 부르는 쪽이 '진술' 로 둔다.
            return []
        scores = self.scores(str(text))
        if not scores:
            return []
        chosen = [label for label, value in scores.items() if value > self.threshold]
        return chosen or [max(scores, key=scores.get)]
