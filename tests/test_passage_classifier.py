# -*- coding: utf-8 -*-
"""발췌 분류 부품. **정확도는 한 번도 안 본 문장으로만 말한다.**

이 파일이 지키는 것은 점수가 아니라 재는 방법이다. 부품은 사람 라벨 전부로
학습하므로(그게 쓰기에는 옳다) 그 라벨 파일로 다시 재면 외운 값이 나온다 —
실제로 86.9%가 나오고, 홀드아웃으로 재면 34.3%다. 이 둘을 섞으면 안 된다.
"""
import hashlib
import json
from pathlib import Path

from marco.language.passages import LabelLearnedClassifier
import pytest

pytestmark = pytest.mark.language("한국어")  # Korean input: select the Korean pack, do not rely on the default

ROOT = Path(__file__).resolve().parents[1]
LABELS = ROOT / "docs" / "ko" / "_발췌꼴.json"


def _rows():
    doc = json.loads(LABELS.read_text(encoding="utf-8"))
    return [(s, [x for x in form.split(",") if x])
            for form, sentences in doc["꼴"].items() for s in sentences]


def _split(sentence):
    """문장 해시로 고정한다. 순서나 튜닝으로 움직이지 않는다."""
    return "평가" if int(hashlib.sha256(sentence.encode()).hexdigest(), 16) % 10 < 3 else "학습"


def test_component_keeps_the_protocol_and_invents_nothing_without_labels(tmp_path):
    classifier = LabelLearnedClassifier()
    assert isinstance(classifier.classify("임계값은 기준을 말한다."), list)
    assert classifier.classify("   ") == []
    # 배울 자료가 없으면 꼴을 지어내지 않는다. 부르는 쪽이 '진술' 로 둔다.
    empty = LabelLearnedClassifier(labels=tmp_path / "없음.json")
    assert empty.classify("임계값은 기준을 말한다.") == []


def test_held_out_accuracy_beats_the_majority_label_baseline(tmp_path):
    rows = _rows()
    train = [r for r in rows if _split(r[0]) == "학습"]
    held = [r for r in rows if _split(r[0]) == "평가"]
    assert len(held) >= 50, len(held)

    # 학습 쪽만 담은 라벨 파일로 다시 학습한다. 평가 문장은 모형이 못 본다.
    forms = {}
    for sentence, labels in train:
        forms.setdefault(",".join(labels), []).append(sentence)
    path = tmp_path / "학습만.json"
    path.write_text(json.dumps({"꼴": forms}, ensure_ascii=False), encoding="utf-8")

    classifier = LabelLearnedClassifier(labels=path)
    exact = sum(1 for s, labels in held if set(classifier.classify(s)) == set(labels))

    # 가장 흔한 라벨만 찍는 기준선. 이것을 못 넘으면 배운 값이 없는 것이다.
    common = max({l for _, ls in rows for l in ls},
                 key=lambda l: sum(1 for _, ls in rows if l in ls))
    baseline = sum(1 for _, labels in held if set(labels) == {common})
    assert exact > baseline, (exact, baseline)


def test_measuring_the_shipped_model_on_its_own_labels_is_memorisation():
    """외운 값을 정확도로 쓰지 않도록 그 차이를 시험으로 남긴다."""
    rows = _rows()
    held = [r for r in rows if _split(r[0]) == "평가"]
    shipped = LabelLearnedClassifier()          # 317개 전부로 학습한다
    seen = sum(1 for s, labels in held if set(shipped.classify(s)) == set(labels))
    assert seen > 0.7 * len(held), seen         # 외우면 높게 나온다 — 정확도가 아니다
