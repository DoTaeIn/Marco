# -*- coding: utf-8 -*-
"""Frozen ResNet 특징 위 다중라벨 HOI 기준선. train/test parquet 은 절대 섞지 않는다.

무엇을 재나. 숫자 하나가 아니라 **표 하나**를 낸다.

    전부음성    아무것도 안 하는 모델. 이걸 못 넘으면 아무것도 아니다
    기하만      상자 12개 숫자만. 이 작업의 명분이 '기하 근접이 아닌 분류기'였다
    ResNet     사람·물체·합집합 crop 특징 6152차원

셋을 나란히 안 보면 속는다. 라벨당정확도는 전부음성에게도 87% 를 준다
(`hoi_eval.py --check` 가 실제로 찍어 보인다). 그래서 mAP 와 라벨별 F1 을 같이 낸다.

특징은 한 번만 뽑아 캐시한다. epoch 마다 다시 뽑으면 frozen 백본을 쓰는
뜻이 없고, 그 비용 때문에 표본을 256개로 줄이게 된다 — 6152차원 선형 헤드에
표본 256개는 파라미터가 표본보다 400배 많아 학습이 아니라 암기가 된다.

문턱은 학습셋에서 뗀 검증셋에서 고른다. 테스트에서 고르면 테스트를 두 번
보는 것이라 숫자가 부푼다.

    python train_hoi.py --check          # 데이터 없이 회로만 검사
    python train_hoi.py --train m_train.jsonl --test m_test.jsonl \
                        --train-parquet t.parquet --test-parquet e.parquet
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from torch import nn

import hoi_eval

# train/test 양쪽에서 100건 넘는 것만. 희소 라벨을 섞으면 우연히 높은 점수가
# 정확도처럼 보인다. 늘릴 때는 양쪽 표본 수를 먼저 세고 늘린다.
라벨들 = ["hold", "ride", "sit_on", "carry", "straddle", "wear", "stand_on", "jump",
          "read", "wield", "drive", "open", "stand_under", "race", "inspect", "swing"]


def 사례읽기(경로, 라벨들, 최대=None):
    """manifest jsonl -> (행, 정답벡터). 16개 중 하나도 없는 쌍은 뺀다.

    빼는 것은 범위를 좁히는 결정이다. 모델이 '이 중 아무것도 아니다' 를 배울
    일이 없고 테스트도 늘 정답이 있는 쌍만 나온다. 숫자를 적을 때 이 문장을
    같이 적어야 한다 — 안 적으면 다음 사람이 실사용 정확도로 읽는다."""
    나옴 = []
    with open(경로, encoding="utf-8") as f:
        for 줄 in f:
            줄 = 줄.strip()
            if not 줄:
                continue
            r = json.loads(줄)
            y = np.array([a in r["actions"] for a in 라벨들], dtype=bool)
            if y.any():
                나옴.append((r, y))
            if 최대 and len(나옴) >= 최대:
                break
    return 나옴


def 특징뽑기(사례들, 이미지바이트, 뽑개, 캐시=None):
    """한 번만 뽑아 캐시한다. (시각특징, 기하특징) 두 벌을 함께 돌려준다."""
    if 캐시 and Path(캐시).exists():
        d = np.load(캐시)
        if len(d["시각"]) == len(사례들):
            return d["시각"], d["기하"]
    시각, 기하 = [], []
    for i, (r, _y) in enumerate(사례들):
        raw = 이미지바이트(r["row"])
        시각.append(뽑개.pair(raw, r["bbox_human"], r["bbox_object"]).numpy())
        너비, 높이 = 뽑개.크기(raw)
        기하.append(hoi_eval.기하특징(r["bbox_human"], r["bbox_object"], 너비, 높이))
        if (i + 1) % 200 == 0:
            print("  특징 %d/%d" % (i + 1, len(사례들)), flush=True)
    시각, 기하 = np.asarray(시각, dtype=np.float32), np.asarray(기하, dtype=np.float32)
    if 캐시:
        Path(캐시).parent.mkdir(parents=True, exist_ok=True)
        np.savez(캐시, 시각=시각, 기하=기하)
    return 시각, 기하


def 헤드학습(X, Y, 회차=60, lr=2e-3, 씨=0):
    """frozen 특징 위 선형 헤드. 특징이 캐시돼 있으므로 회차를 넉넉히 돈다."""
    torch.manual_seed(씨)
    X = torch.tensor(np.asarray(X, dtype=np.float32))
    Y = torch.tensor(np.asarray(Y, dtype=np.float32))
    # 열마다 크기가 다르면 한 열이 학습을 독차지한다. 기하 12차원과
    # ResNet 6152차원을 같은 코드로 돌리려면 정규화가 필요하다.
    평균, 표준 = X.mean(0, keepdim=True), X.std(0, keepdim=True).clamp_min(1e-6)
    X = (X - 평균) / 표준
    헤드 = nn.Linear(X.shape[1], Y.shape[1])
    옵 = torch.optim.AdamW(헤드.parameters(), lr=lr, weight_decay=1e-2)
    for _ in range(회차):
        옵.zero_grad()
        손실 = nn.functional.binary_cross_entropy_with_logits(헤드(X), Y)
        손실.backward()
        옵.step()

    @torch.no_grad()
    def 점수내기(X2):
        X2 = torch.tensor(np.asarray(X2, dtype=np.float32))
        return 헤드((X2 - 평균) / 표준).sigmoid().numpy()
    return 점수내기


def 한판(이름, 학습X, 학습Y, 검증X, 검증Y, 시험X, 시험Y):
    """학습 -> 검증에서 문턱 -> 시험 한 번. 순서를 지킨다."""
    점수내기 = 헤드학습(학습X, 학습Y)
    검증점수 = 점수내기(검증X)
    문턱 = [hoi_eval.문턱고르기(np.asarray(검증Y)[:, i], 검증점수[:, i])
            for i in range(len(라벨들))]
    return hoi_eval.재기(시험Y, 점수내기(시험X), 라벨들, 문턱=문턱)


def 돌리기(학습사례, 시험사례, 학습시각, 학습기하, 시험시각, 시험기하, 쪼갬=0.8):
    학습Y = np.array([y for _r, y in 학습사례])
    시험Y = np.array([y for _r, y in 시험사례])
    자름 = max(1, int(len(학습사례) * 쪼갬))
    결과 = {"전부음성": hoi_eval.전부음성(시험Y, 라벨들)}
    for 이름, 학습X, 시험X in (("기하만", 학습기하, 시험기하),
                               ("ResNet", 학습시각, 시험시각)):
        결과[이름] = 한판(이름, 학습X[:자름], 학습Y[:자름],
                          학습X[자름:], 학습Y[자름:], 시험X, 시험Y)
    return 결과


def _selfcheck():
    """데이터 없이 회로만 본다. HICO 가 없어도 이 파일이 도는지 먼저 안다."""
    rng = np.random.default_rng(0)
    n, d = 300, 64

    class 가짜뽑개:
        """ResNet 자리에 끼우는 가짜. 백본 없이 회로만 본다."""

        def pair(self, raw, h, o):
            return torch.tensor(raw, dtype=torch.float32)

        def 크기(self, raw):
            return 640, 480

    def 만들기(n):
        """라벨은 시각특징에만 싣고 상자는 전부 같게 둔다.

        그러면 기하 대조군은 아무것도 못 가르고 시각 쪽만 맞혀야 한다 —
        표가 둘을 실제로 갈라내는지 보는 것이 이 검사의 요점이다."""
        사례, 창고 = [], {}
        for i in range(n):
            y = np.zeros(len(라벨들), dtype=bool)
            for j in rng.choice(len(라벨들), size=rng.integers(1, 4), replace=False):
                y[j] = True
            v = rng.normal(scale=0.3, size=d)
            v[:len(라벨들)] += y * 2.0            # 라벨이 특징에 실제로 실린다
            창고[i] = v
            사례.append(({"row": i, "bbox_human": [0, 0, 100, 200],
                          "bbox_object": [50, 50, 150, 220]}, y))
        return 사례, 창고

    뽑개 = 가짜뽑개()
    학습사례, 학습창고 = 만들기(n)
    시험사례, 시험창고 = 만들기(120)
    학습시각, 학습기하 = 특징뽑기(학습사례, lambda i: 학습창고[i], 뽑개)
    시험시각, 시험기하 = 특징뽑기(시험사례, lambda i: 시험창고[i], 뽑개)
    assert 학습시각.shape == (n, d), 학습시각.shape
    assert 학습기하.shape == (n, 12), 학습기하.shape

    결과 = 돌리기(학습사례, 시험사례, 학습시각, 학습기하, 시험시각, 시험기하)
    assert set(결과) == {"전부음성", "기하만", "ResNet"}, set(결과)
    # 바닥은 F1 이 0 인데 라벨당정확도는 높다 — 이 표를 쓰는 이유다
    assert 결과["전부음성"]["매크로F1"] == 0.0
    assert 결과["전부음성"]["라벨당정확도"] > 0.80, 결과["전부음성"]["라벨당정확도"]
    # 상자가 전부 같으므로 기하는 아무것도 못 가린다. 바닥과 같아야 옳다.
    assert abs(결과["기하만"]["mAP"] - 결과["전부음성"]["mAP"]) < 0.05, 결과["기하만"]["mAP"]
    # 그리고 신호가 실린 쪽은 기하를 확실히 넘어야 한다. 이 표가 둘을 못
    # 가르면 실제 HICO 에서도 못 가른다 — 채점기를 먼저 검사하는 이유다.
    assert 결과["ResNet"]["mAP"] > 결과["기하만"]["mAP"] + 0.15, (
        결과["ResNet"]["mAP"], 결과["기하만"]["mAP"])
    for r in 결과.values():
        assert 0.0 <= r["mAP"] <= 1.0 or np.isnan(r["mAP"])
    print(hoi_eval.표(결과))
    print("selfcheck ok")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--train", type=Path)
    p.add_argument("--test", type=Path)
    p.add_argument("--train-parquet", type=Path)
    p.add_argument("--test-parquet", type=Path)
    p.add_argument("--limit", type=int)
    p.add_argument("--cache", default="data/hoi특징")
    p.add_argument("--check", action="store_true")
    a = p.parse_args()
    if a.check:
        _selfcheck()
        return
    if not all([a.train, a.test, a.train_parquet, a.test_parquet]):
        p.error("--train/--test/--train-parquet/--test-parquet 가 모두 필요하다")

    import pandas as pd
    from hoi_features import HOIFeaturizer

    학습사례 = 사례읽기(a.train, 라벨들, a.limit)
    시험사례 = 사례읽기(a.test, 라벨들, a.limit)
    print("학습 %d 쌍 · 시험 %d 쌍 (16개 라벨 중 하나도 없는 쌍은 뺐다)"
          % (len(학습사례), len(시험사례)))
    학습이미지 = pd.read_parquet(a.train_parquet, columns=["image"])
    시험이미지 = pd.read_parquet(a.test_parquet, columns=["image"])
    뽑개 = HOIFeaturizer()
    학습시각, 학습기하 = 특징뽑기(학습사례, lambda i: 학습이미지.iloc[i].image["bytes"],
                                   뽑개, Path(a.cache) / "train.npz")
    시험시각, 시험기하 = 특징뽑기(시험사례, lambda i: 시험이미지.iloc[i].image["bytes"],
                                   뽑개, Path(a.cache) / "test.npz")
    결과 = 돌리기(학습사례, 시험사례, 학습시각, 학습기하, 시험시각, 시험기하)
    print()
    print(hoi_eval.표(결과, 라벨들))


if __name__ == "__main__":
    main()
