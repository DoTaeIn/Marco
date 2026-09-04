# -*- coding: utf-8 -*-
"""HOI 다중라벨 채점기와 대조군.

왜 따로 두나. 다중라벨에서 '라벨당 정확도'는 아무것도 안 하는 모델에게
높은 점수를 준다. 라벨 16개에 양성이 평균 2개면 전부 0으로 찍어도 87.5%다.
그 숫자를 먼저 보면 학습이 된 줄 알고 다음 단계로 넘어간다.

그래서 이 파일은 세 가지를 같이 낸다.

    mAP            라벨마다 순위를 매겨 재므로 문턱과 무관하다
    라벨별 P/R/F1   어느 행동이 되고 어느 행동이 안 되는지 보인다
    대조군          전부음성 · 기하만. 이걸 못 넘으면 아무것도 아니다

기하 대조군이 특히 중요하다. 이 작업의 명분이 '기하 근접 추정이 아닌 실제
행동 분류기'였으므로, ResNet 특징이 상자 12개 숫자를 못 이기면 백본을 깐
이유가 없어진다. HOI 에서 이 대조군은 세다 — ride/sit_on/straddle 은 상자
겹침만으로도 상당히 갈린다.
"""
from __future__ import annotations

import numpy as np


def 평균정밀도(정답, 점수):
    """한 라벨의 AP. 문턱을 안 고르고 순위만 본다.

    양성이 하나도 없으면 정의되지 않는다 — 0 으로 세면 희소 라벨이 평균을
    끌어내려 모델이 나쁜 것처럼 보인다. nan 으로 두고 평균에서 뺀다."""
    정답 = np.asarray(정답, dtype=bool)
    점수 = np.asarray(점수, dtype=float)
    if 정답.size == 0 or not 정답.any():
        return float("nan")
    차례 = np.argsort(-점수, kind="mergesort")     # 동점은 들어온 순서를 지킨다
    맞음 = 정답[차례]
    정밀도 = np.cumsum(맞음) / (np.arange(맞음.size) + 1)
    return float((정밀도 * 맞음).sum() / 맞음.sum())


def 문턱고르기(정답, 점수):
    """라벨마다 F1 이 가장 큰 문턱. **검증셋에서만 부른다.**

    0.5 를 그냥 쓰면 안 된다. 학습이 덜 된 헤드의 시그모이드 출력은 0.5 근처에
    안 모이고, 라벨마다 양성 비율이 달라 좋은 문턱도 다르다. 테스트에서 고르면
    테스트를 두 번 보는 것이라 숫자가 부푼다."""
    정답 = np.asarray(정답, dtype=bool)
    점수 = np.asarray(점수, dtype=float)
    if not 정답.any():
        return 0.5
    후보 = np.unique(점수)
    if 후보.size > 512:                              # 큰 검증셋에서 O(n^2) 를 막는다
        후보 = np.quantile(점수, np.linspace(0, 1, 512))
    best, best_f1 = 0.5, -1.0
    for t in 후보:
        예측 = 점수 >= t
        tp = int((예측 & 정답).sum())
        if not tp:
            continue
        정밀 = tp / int(예측.sum())
        재현 = tp / int(정답.sum())
        f1 = 2 * 정밀 * 재현 / (정밀 + 재현)
        if f1 > best_f1:
            best, best_f1 = float(t), f1
    return best


def _prf(정답, 예측):
    tp = int((예측 & 정답).sum())
    정밀 = tp / int(예측.sum()) if 예측.any() else 0.0
    재현 = tp / int(정답.sum()) if 정답.any() else float("nan")
    f1 = 2 * 정밀 * 재현 / (정밀 + 재현) if tp else 0.0
    return 정밀, 재현, f1


def 재기(정답, 점수, 라벨들, 문턱=None):
    """정답·점수는 (표본수, 라벨수) 행렬. 문턱은 라벨마다 하나, 없으면 0.5.

    `라벨당정확도` 를 일부러 같이 낸다. 빼면 다음 사람이 또 그걸로 잰다 —
    옆에 `전부음성` 을 나란히 두면 그 숫자가 얼마나 헐거운지 바로 보인다."""
    정답 = np.asarray(정답, dtype=bool)
    점수 = np.asarray(점수, dtype=float)
    if 정답.shape != 점수.shape:
        raise ValueError("정답 %s 와 점수 %s 의 꼴이 다르다" % (정답.shape, 점수.shape))
    if 정답.shape[1] != len(라벨들):
        raise ValueError("라벨 %d 개인데 열이 %d 개다" % (len(라벨들), 정답.shape[1]))
    문턱 = [0.5] * len(라벨들) if 문턱 is None else list(문턱)
    예측 = 점수 >= np.asarray(문턱, dtype=float)

    라벨별 = {}
    for i, 이름 in enumerate(라벨들):
        정밀, 재현, f1 = _prf(정답[:, i], 예측[:, i])
        라벨별[이름] = {"AP": 평균정밀도(정답[:, i], 점수[:, i]),
                        "정밀도": 정밀, "재현율": 재현, "F1": f1,
                        "양성수": int(정답[:, i].sum()), "문턱": 문턱[i]}
    ap들 = [v["AP"] for v in 라벨별.values() if not np.isnan(v["AP"])]
    f1들 = [v["F1"] for v in 라벨별.values() if v["양성수"]]
    tp = int((예측 & 정답).sum())
    미정밀 = tp / int(예측.sum()) if 예측.any() else 0.0
    미재현 = tp / int(정답.sum()) if 정답.any() else 0.0
    return {"mAP": float(np.mean(ap들)) if ap들 else float("nan"),
            "매크로F1": float(np.mean(f1들)) if f1들 else 0.0,
            "마이크로F1": (2 * 미정밀 * 미재현 / (미정밀 + 미재현)) if tp else 0.0,
            # 아래 둘은 '속기 쉬운 숫자'다. 대조군과 나란히 볼 때만 뜻이 있다.
            "라벨당정확도": float((예측 == 정답).mean()),
            "표본수": int(정답.shape[0]),
            "쌍당평균양성": float(정답.sum(axis=1).mean()) if 정답.size else 0.0,
            "라벨별": 라벨별}


def 전부음성(정답, 라벨들):
    """아무것도 안 하는 모델. 넘어야 할 바닥이다."""
    정답 = np.asarray(정답, dtype=bool)
    return 재기(정답, np.zeros(정답.shape), 라벨들,
                문턱=[1.1] * len(라벨들))          # 절대 안 켜지는 문턱


def 기하특징(사람, 물체, 너비, 높이):
    """상자 둘만으로 만드는 12차원. 기하 대조군의 입력이다.

    ResNet 6152차원이 이 12개를 못 이기면 백본이 값을 못 한 것이다."""
    너비, 높이 = float(너비) or 1.0, float(높이) or 1.0
    hx1, hy1, hx2, hy2 = [float(v) for v in 사람]
    ox1, oy1, ox2, oy2 = [float(v) for v in 물체]
    hw, hh = max(hx2 - hx1, 1e-6), max(hy2 - hy1, 1e-6)
    ow, oh = max(ox2 - ox1, 1e-6), max(oy2 - oy1, 1e-6)
    겹침w = max(0.0, min(hx2, ox2) - max(hx1, ox1))
    겹침h = max(0.0, min(hy2, oy2) - max(hy1, oy1))
    겹침 = 겹침w * 겹침h
    iou = 겹침 / (hw * hh + ow * oh - 겹침 + 1e-9)
    return [hx1 / 너비, hy1 / 높이, hw / 너비, hh / 높이,
            ox1 / 너비, oy1 / 높이, ow / 너비, oh / 높이,
            ((ox1 + ox2) - (hx1 + hx2)) / 2 / 너비,      # 중심 x 차
            ((oy1 + oy2) - (hy1 + hy2)) / 2 / 높이,      # 중심 y 차
            iou,
            (ow * oh) / (hw * hh)]                       # 넓이 비


def 표(이름별결과, 라벨들=None):
    """대조군과 나란히 한 표로. 숫자 하나만 보면 또 속는다."""
    줄 = ["%-14s %7s %8s %9s %13s" % ("", "mAP", "매크로F1", "마이크로F1", "라벨당정확도"),
          "-" * 56]
    for 이름, r in 이름별결과.items():
        줄.append("%-14s %7.3f %8.3f %9.3f %13.3f"
                  % (이름, r["mAP"] if not np.isnan(r["mAP"]) else 0.0,
                     r["매크로F1"], r["마이크로F1"], r["라벨당정확도"]))
    if 라벨들:
        마지막 = list(이름별결과.values())[-1]
        줄 += ["", "%-14s %6s %8s %8s %7s" % ("라벨", "양성", "AP", "F1", "재현율")]
        for 이름 in 라벨들:
            v = 마지막["라벨별"][이름]
            줄.append("%-14s %6d %8.3f %8.3f %7.3f"
                      % (이름, v["양성수"],
                         0.0 if np.isnan(v["AP"]) else v["AP"], v["F1"],
                         0.0 if np.isnan(v["재현율"]) else v["재현율"]))
    return "\n".join(줄)


def _selfcheck():
    라벨들 = ["hold", "ride", "sit_on", "carry"] + ["x%d" % i for i in range(12)]
    rng = np.random.default_rng(0)
    n = 400
    정답 = np.zeros((n, len(라벨들)), dtype=bool)
    for i in range(n):                                   # 쌍당 양성 1~3개
        for j in rng.choice(len(라벨들), size=rng.integers(1, 4), replace=False):
            정답[i, j] = True

    # 1) 아무것도 안 하는 모델이 '라벨당정확도' 에서 높게 나온다 — 이 파일의 존재 이유
    바닥 = 전부음성(정답, 라벨들)
    assert 바닥["라벨당정확도"] > 0.80, 바닥["라벨당정확도"]
    assert 바닥["매크로F1"] == 0.0 and 바닥["마이크로F1"] == 0.0
    assert 바닥["mAP"] < 0.30, 바닥["mAP"]                # 순위 기반이라 안 속는다

    # 2) 정답을 그대로 아는 모델은 전부 1.0
    완벽 = 재기(정답, 정답.astype(float), 라벨들)
    assert abs(완벽["mAP"] - 1.0) < 1e-9, 완벽["mAP"]
    assert abs(완벽["마이크로F1"] - 1.0) < 1e-9

    # 3) AP 는 순위만 본다. 점수를 단조 변환해도 안 바뀐다.
    점수 = rng.random((n, len(라벨들)))
    a = 재기(정답, 점수, 라벨들)["mAP"]
    b = 재기(정답, 점수 * 3.7 - 2.0, 라벨들)["mAP"]
    assert abs(a - b) < 1e-9, (a, b)

    # 4) 문턱은 검증셋에서 고른다. 고르면 F1 이 0.5 고정보다 낫거나 같다.
    치우침 = 점수 + 정답 * 0.35                          # 신호가 조금 있는 점수
    기본 = 재기(정답, 치우침, 라벨들)["매크로F1"]
    고른문턱 = [문턱고르기(정답[:, i], 치우침[:, i]) for i in range(len(라벨들))]
    고름 = 재기(정답, 치우침, 라벨들, 문턱=고른문턱)["매크로F1"]
    assert 고름 >= 기본 - 1e-9, (기본, 고름)

    # 5) 기하특징: 겹치면 IoU 가 크고, 떨어지면 0 이다
    붙음 = 기하특징([0, 0, 100, 200], [10, 10, 90, 190], 640, 480)
    떨어짐 = 기하특징([0, 0, 100, 200], [500, 400, 600, 470], 640, 480)
    assert len(붙음) == 12 and 붙음[10] > 0.5, 붙음[10]
    assert 떨어짐[10] == 0.0, 떨어짐[10]

    # 6) 꼴이 안 맞으면 조용히 넘어가지 않는다
    for 나쁜 in (lambda: 재기(정답, 점수[:, :3], 라벨들),
                 lambda: 재기(정답, 점수, 라벨들[:3])):
        try:
            나쁜(); raise AssertionError("꼴이 틀렸는데 통과했다")
        except ValueError:
            pass

    print("전부음성 대조군이 라벨당정확도 %.1f%% 를 받는다 — 이래서 그 숫자로 재면 안 된다."
          % (바닥["라벨당정확도"] * 100))
    print("selfcheck ok")


if __name__ == "__main__":
    import sys
    if "--check" in sys.argv:
        _selfcheck()
    else:
        print(__doc__)
