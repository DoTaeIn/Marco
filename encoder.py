# -*- coding: utf-8 -*-
"""공용 층: 문장 인코더와 경로. 논증·설명 양쪽이 이것만 공유한다.

신경망은 이 파일 하나에만 있다. 인코더 한 벌, forward pass 한 번 —
토큰을 하나씩 뽑는 자기회귀 루프가 없다. 나머지는 전부 그래프와 규칙이다.
"""
import json, os, re, sys, zlib
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
_mode = os.environ.get("KG_ENCODER", "신경망")
_character_dimensions = int(os.environ.get("KG_DIM", "2048"))
_jamo_weight = float(os.environ.get("KG_JAMO", "0.5"))
# 이름에 방식을 적어 둔다. 캐시 키가 MODEL 을 쓰므로, 구현을 바꾸고 이름을
# 안 바꾸면 낡은 벡터를 그대로 읽는다 — 음절에서 자모로 바꿨을 때 실제로
# 그래서 적중률이 100%에서 4%로 무너졌다.
MODEL = ("문자ngram-%d-자모%.1f" % (_character_dimensions, _jamo_weight) if _mode == "문자"
         else "jhgan/ko-sroberta-multitask")   # 768d
# CPU 고정. sentence-transformers 는 CUDA 가 보이면 말없이 GPU 로 올린다 —
# 그러면 "GPU 없이 돈다"는 이 프로젝트의 전제가 조용히 깨진 채로 측정된다.
# 환경변수 KG_DEVICE 로만 바꿀 수 있게 둔다.
DEVICE = os.environ.get("KG_DEVICE", "cpu")

_here = os.path.dirname(os.path.abspath(__file__))


def _path(p):
    """상대 경로는 일단 지금 자리에서, 없으면 이 파일 옆에서 찾는다.
    어느 폴더에서 부르든 예시 데이터가 딸려오게."""
    return p if os.path.isabs(p) or os.path.exists(p) else os.path.join(_here, p)


_길 = _path


_M = None


def _model():
    """모델을 처음 쓸 때 한 번 올린다.

    torch/HF 가 로드 중 stderr 로 뿜는 경고는 파이썬 warnings 로 안 잡힌다
    (C 레벨 로깅과 직접 print). 이 프로그램과 무관한 잡음이라 통째로 막는다."""
    global _M
    if _mode == "문자":
        return _CharacterModel()
    if _M is None:
        null_fd = os.open(os.devnull, os.O_WRONLY)
        saved_stderr = os.dup(2)
        try:
            os.dup2(null_fd, 2)                # C 레벨 로깅까지 막으려면 fd 단위여야 한다
            from sentence_transformers import SentenceTransformer
            _M = SentenceTransformer(MODEL, device=DEVICE)
        finally:
            os.dup2(saved_stderr, 2)
            os.close(saved_stderr)
            os.close(null_fd)
    return _M


_number_pattern = re.compile(r"\d+(?:\.\d+)?")


def mask_numbers(text):
    """노드 식별에서 숫자를 지운다.

    임베딩은 숫자 자체에 지배당한다 — 같은 문장인데 '820점'은 0.962,
    '320점'은 0.561 로 떨어졌다. 어느 노드에 대한 주장인지는 숫자와 무관하므로
    가리고 매칭하고, 크기 비교는 수치조건이 따로 한다."""
    return _number_pattern.sub("§", text)


숫자가리기 = mask_numbers


def _decompose_jamo(text):
    """한글을 자모로 편다. 음절이 아니라 자모로 n-gram 을 잡기 위해서다.

    음절로 자르면 '해고' 와 '해구' 가 한 글자도 안 겹친다. 자모로 펴면
    ㅎㅐㄱㅗ / ㅎㅐㄱㅜ 라 대부분이 겹친다. 재보니 분리도가 0.355 -> 0.519
    로 올랐고 오타 '침해/짐해' 가 0.17 -> 0.57 이 됐다."""
    out = []
    for c in text:
        k = ord(c) - 0xAC00
        if 0 <= k < 11172:
            out.append(chr(0x1100 + k // 588))
            out.append(chr(0x1161 + (k % 588) // 28))
            if k % 28:
                out.append(chr(0x11A7 + k % 28))
        else:
            out.append(c)
    return "".join(out)


def _character_vector(text, dimensions=None):
    """음절 n-gram 해시 벡터. 신경망도 토큰도 안 쓴다.

    한국어는 형태가 붙어 변하므로(해고/해고가/해고를) 글자 n-gram 이 그
    변화를 흡수한다. 2~4 글자를 함께 보면 '부당해고' 와 '해고' 가 겹치는
    부분을 공유한다.

    자모로 펴는 것도 재봤다. 쌍끼리는 더 잘 갈린다(분리도 0.355 -> 0.519,
    오타 '침해/짐해' 0.17 -> 0.57). 그런데 후보가 7,195개인 실제 그래프에서
    졌다 — 가림 84% -> 75%, 대목 99% -> 96%, 발화샘플 적중 7/7 -> 5/7.
    자모로 펴면 짧은 말끼리 우연히 겹치는 양이 늘고, 후보가 많을수록 그
    잡음이 쌓여 진짜 답을 밀어낸다. 오타는 오타고침(자모 편집거리)이 따로
    맡으므로 인코더까지 자모로 갈 이유가 없다.

    못 하는 것은 동의어다 — '해고' 와 '면직' 은 자모가 안 겹쳐 0 이다.
    그 자리는 그래프가 메운다: 노드마다 말 예시가 여럿 있고, 개념망이
    상위어에 하위어 표현을 붙여 준다. 그래서 이 엔진에서는 인코더가
    혼자 짊어질 짐이 적다.

    부호 해싱을 쓴다. 서로 다른 n-gram 이 같은 칸에 떨어져도 부호가 갈리면
    서로를 지워 충돌이 점수를 부풀리지 않는다.

    해시는 crc32 다. 파이썬 내장 hash() 는 문자열에 대해 프로세스마다
    무작위로 달라진다(PYTHONHASHSEED). 벡터를 디스크에 캐시하는 순간
    그것이 치명적이다 — 만든 프로세스와 읽는 프로세스의 벡터가 아예 다른
    공간에 놓인다. 문서그래프에서 노드 이름을 그대로 물었는데 적중이
    0/400 이었다. 한 프로세스 안에서만 맞으니 눈에 잘 안 띈다."""
    import numpy as np
    dimensions = dimensions or _character_dimensions
    v = np.zeros(dimensions, dtype=np.float32)
    g = mask_numbers(text).strip()
    # 음절과 자모를 섞는다. 음절은 정밀하고(우연한 겹침이 적다) 자모는
    # 강인하다(오타·형태 변화를 잡는다). 한쪽만 쓰면 한쪽을 잃는다.
    for t, w in (("\x02" + g + "\x03", 1.0),
                 ("\x02" + _decompose_jamo(g) + "\x03", _jamo_weight)):
        if w == 0.0:
            continue
        for n in (2, 3, 4):
            for k in range(len(t) - n + 1):
                fragment = t[k:k + n]
                조각 = fragment.encode("utf-8")
                h = zlib.crc32(조각) % dimensions
                v[h] += w * (1.0 if zlib.crc32(조각 + b"\x00") % 2 else -1.0)
    magnitude = float(np.linalg.norm(v))
    return v / magnitude if magnitude else v


@lru_cache(maxsize=512)
def _vec(text):
    if _mode == "문자":
        return _character_vector(text)
    return _model().encode([mask_numbers(text)], normalize_embeddings=True)[0]


def _vecs(texts):
    """여러 문장을 한 판에. 하나씩 부르면 모델 forward 가 그 수만큼 돈다 —
    숙고가 후보 다섯의 발췌 여섯을 각각 부르느라 질문 하나에 서른 번이었다."""
    texts = list(texts)
    if not texts:
        import numpy as np
        return np.zeros((0, 1), dtype="float32")
    if _mode == "문자":
        import numpy as np
        return np.array([_character_vector(t) for t in texts], dtype="float32")
    return _model().encode([mask_numbers(t) for t in texts],
                           normalize_embeddings=True)


class _CharacterModel:
    """sentence-transformers 와 같은 모양으로 감싼다. 부르는 쪽은 안 바뀐다."""

    def encode(self, sentences, normalize_embeddings=True, **_):
        import numpy as np
        return np.array([_character_vector(sentence) for sentence in sentences], dtype=np.float32)


def _self_check():
    """문자 인코더가 벡터로서 갖춰야 할 성질. 신경망 없이 돈다."""
    import numpy as np
    v = _character_vector("해고")
    assert abs(float(np.linalg.norm(v)) - 1.0) < 1e-5      # 정규화돼 있다
    assert float(_character_vector("해고") @ _character_vector("해고")) > 0.99
    # 형태 변화는 잡는다 — 한국어는 조사가 붙어 변한다
    assert float(_character_vector("해고") @ _character_vector("해고가")) > 0.3
    # 동의어는 못 잡는다 — '해고' 와 '면직' 은 자모가 안 겹쳐 0 이다.
    # 그 자리는 그래프가 메운다(노드마다 말 예시가 여럿, 개념망이 상위어에
    # 하위어 표현을 붙임).
    assert float(_character_vector("해고") @ _character_vector("면직")) < 0.05
    # 자모를 섞으면 짧은 말끼리 우연히 겹치는 양이 조금 는다. 절대값이
    # 아니라 격차로 본다 — 형태 변화가 남남보다 몇 배인지.
    similar = float(_character_vector("해고") @ _character_vector("해고가"))
    unrelated = float(_character_vector("해고") @ _character_vector("고양이"))
    assert similar > 0.3, similar
    assert similar > 4 * max(unrelated, 0.01), (similar, unrelated)
    # 숫자는 가려서 본다. '820점' 과 '320점' 이 다른 노드가 되면 안 된다
    assert float(_character_vector("820점입니다") @ _character_vector("320점입니다")) > 0.9
    print("인코더 selfcheck ok")


_sentence_splitter = re.compile(r"[.!?\n]+|(?<=니다)\s*[,;]\s*|(?<=습니다)\s+")


def split_fragments(text):
    """긴 발화를 문장 단위로 쪼갠다.

    실제 사용자는 '증거를 보면 A입니다. 따라서 B이고, 그러므로 C입니다' 처럼
    한 번에 여러 주장을 한다. 문장 하나 = 주장 하나로 가정하면 전체 평균이
    흐려져 아무 노드에도 안 걸리고 미지로 떨어진다."""
    fragments = [x.strip() for x in _sentence_splitter.split(text) if x and len(x.strip()) > 3]
    return ([text] + fragments) if len(fragments) > 1 else [text]


조각내기 = split_fragments


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
