# -*- coding: utf-8 -*-
"""공용 층: 문장 인코더와 경로. 논증·설명 양쪽이 이것만 공유한다.

신경망은 이 파일 하나에만 있다. 인코더 한 벌, forward pass 한 번 —
토큰을 하나씩 뽑는 자기회귀 루프가 없다. 나머지는 전부 그래프와 규칙이다.
"""
import json, os, re, sys
from collections import deque
from functools import lru_cache

os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")
os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
# torch/HF 가 매 실행마다 뿜는 경고는 이 프로그램과 무관하다. 유저가 볼 이유가 없다.
import logging
import warnings
warnings.filterwarnings("ignore")
for _n in ("torch", "transformers", "huggingface_hub", "sentence_transformers"):
    logging.getLogger(_n).setLevel(logging.ERROR)

# KG_ENCODER=문자 로 바꾸면 신경망이 아예 사라진다. 문자 n-gram 을 해시해
# 벡터로 만든다 — 토큰도, 모델 내려받기도, GPU 도 없다. 무엇을 잃고 무엇을
# 버는지는 채점기로 잰다(--score / --regress / --tune).
_방식 = os.environ.get("KG_ENCODER", "신경망")
_문자차원 = int(os.environ.get("KG_DIM", "2048"))
MODEL = ("문자ngram-%d" % _문자차원 if _방식 == "문자"
         else "jhgan/ko-sroberta-multitask")   # 768d
# CPU 고정. sentence-transformers 는 CUDA 가 보이면 말없이 GPU 로 올린다 —
# 그러면 "GPU 없이 돈다"는 이 프로젝트의 전제가 조용히 깨진 채로 측정된다.
# 환경변수 KG_DEVICE 로만 바꿀 수 있게 둔다.
DEVICE = os.environ.get("KG_DEVICE", "cpu")

_여기 = os.path.dirname(os.path.abspath(__file__))


def _길(p):
    """상대 경로는 일단 지금 자리에서, 없으면 이 파일 옆에서 찾는다.
    어느 폴더에서 부르든 예시 데이터가 딸려오게."""
    return p if os.path.isabs(p) or os.path.exists(p) else os.path.join(_여기, p)


_M = None


def _model():
    """모델을 처음 쓸 때 한 번 올린다.

    torch/HF 가 로드 중 stderr 로 뿜는 경고는 파이썬 warnings 로 안 잡힌다
    (C 레벨 로깅과 직접 print). 이 프로그램과 무관한 잡음이라 통째로 막는다."""
    global _M
    if _방식 == "문자":
        return _문자모델()
    if _M is None:
        널 = os.open(os.devnull, os.O_WRONLY)
        보관 = os.dup(2)
        try:
            os.dup2(널, 2)                # C 레벨 로깅까지 막으려면 fd 단위여야 한다
            from sentence_transformers import SentenceTransformer
            _M = SentenceTransformer(MODEL, device=DEVICE)
        finally:
            os.dup2(보관, 2)
            os.close(보관)
            os.close(널)
    return _M


_숫자 = re.compile(r"\d+(?:\.\d+)?")


def 숫자가리기(text):
    """노드 식별에서 숫자를 지운다.

    임베딩은 숫자 자체에 지배당한다 — 같은 문장인데 '820점'은 0.962,
    '320점'은 0.561 로 떨어졌다. 어느 노드에 대한 주장인지는 숫자와 무관하므로
    가리고 매칭하고, 크기 비교는 수치조건이 따로 한다."""
    return _숫자.sub("§", text)


def _문자벡터(글, 차원=None):
    """문자 n-gram 해시 벡터. 신경망도 토큰도 안 쓴다.

    한국어는 형태가 붙어 변하므로(해고/해고가/해고를) 글자 단위 n-gram 이
    형태 변화를 자연스럽게 흡수한다. 2~4 글자를 함께 보면 '부당해고' 와
    '해고' 가 겹치는 부분을 공유한다.

    못 하는 것은 동의어다 — '해고' 와 '면직' 이 글자를 안 겹치면 0 이다.
    그 자리는 그래프가 메운다: 노드마다 말 예시가 여럿 있고, 개념망이
    상위어에 하위어 표현을 붙여 준다. 그래서 이 엔진에서는 인코더가
    혼자 짊어질 짐이 적다."""
    import numpy as np
    차원 = 차원 or _문자차원
    v = np.zeros(차원, dtype=np.float32)
    t = "\x02" + 숫자가리기(글).strip() + "\x03"
    for n in (2, 3, 4):
        for i in range(len(t) - n + 1):
            조각 = t[i:i + n]
            h = hash(조각) % 차원
            v[h] += 1.0
    크기 = float(np.linalg.norm(v))
    return v / 크기 if 크기 else v


@lru_cache(maxsize=512)
def _vec(text):
    if _방식 == "문자":
        return _문자벡터(text)
    return _model().encode([숫자가리기(text)], normalize_embeddings=True)[0]


class _문자모델:
    """sentence-transformers 와 같은 모양으로 감싼다. 부르는 쪽은 안 바뀐다."""

    def encode(self, 문장들, normalize_embeddings=True, **_):
        import numpy as np
        return np.array([_문자벡터(x) for x in 문장들], dtype=np.float32)


def _자체검사():
    """문자 인코더가 벡터로서 갖춰야 할 성질. 신경망 없이 돈다."""
    import numpy as np
    v = _문자벡터("해고")
    assert abs(float(np.linalg.norm(v)) - 1.0) < 1e-5      # 정규화돼 있다
    assert float(_문자벡터("해고") @ _문자벡터("해고")) > 0.99
    # 형태 변화는 잡는다 — 한국어는 조사가 붙어 변한다
    assert float(_문자벡터("해고") @ _문자벡터("해고가")) > 0.3
    # 겹치는 글자가 없으면 0 이다. 동의어는 못 잡는다 — 그 자리는 그래프가
    # 메운다(노드마다 말 예시가 여럿, 개념망이 상위어에 하위어 표현을 붙임).
    assert float(_문자벡터("해고") @ _문자벡터("고양이")) < 0.01
    # 숫자는 가려서 본다. '820점' 과 '320점' 이 다른 노드가 되면 안 된다
    assert float(_문자벡터("820점입니다") @ _문자벡터("320점입니다")) > 0.9
    print("인코더 selfcheck ok")


_문장쪼개기 = re.compile(r"[.!?\n]+|(?<=니다)\s*[,;]\s*|(?<=습니다)\s+")


def 조각내기(text):
    """긴 발화를 문장 단위로 쪼갠다.

    실제 사용자는 '증거를 보면 A입니다. 따라서 B이고, 그러므로 C입니다' 처럼
    한 번에 여러 주장을 한다. 문장 하나 = 주장 하나로 가정하면 전체 평균이
    흐려져 아무 노드에도 안 걸리고 미지로 떨어진다."""
    조각 = [x.strip() for x in _문장쪼개기.split(text) if x and len(x.strip()) > 3]
    return ([text] + 조각) if len(조각) > 1 else [text]


if __name__ == "__main__":
    if "--check" in sys.argv:
        _자체검사()
