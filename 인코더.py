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

MODEL = "jhgan/ko-sroberta-multitask"   # 768d. 온디바이스로 줄일 땐 multilingual-MiniLM
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


@lru_cache(maxsize=512)
def _vec(text):
    return _model().encode([숫자가리기(text)], normalize_embeddings=True)[0]


_문장쪼개기 = re.compile(r"[.!?\n]+|(?<=니다)\s*[,;]\s*|(?<=습니다)\s+")


def 조각내기(text):
    """긴 발화를 문장 단위로 쪼갠다.

    실제 사용자는 '증거를 보면 A입니다. 따라서 B이고, 그러므로 C입니다' 처럼
    한 번에 여러 주장을 한다. 문장 하나 = 주장 하나로 가정하면 전체 평균이
    흐려져 아무 노드에도 안 걸리고 미지로 떨어진다."""
    조각 = [x.strip() for x in _문장쪼개기.split(text) if x and len(x.strip()) > 3]
    return ([text] + 조각) if len(조각) > 1 else [text]


