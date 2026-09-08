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
# 4096 으로 올렸다. 포함도는 해시 충돌에 코사인보다 예민한데(분모가 문서
# 쪽 조각 무게라 충돌 하나가 곧 오차다) 2048 에서 평균오차 0.004,
# 4096 에서 0.000 이었다. 벡터가 싸므로 넉넉한 쪽을 기본으로 둔다.
_character_dimensions = int(os.environ.get("KG_DIM", "4096"))
_jamo_weight = float(os.environ.get("KG_JAMO", "0.5"))
# 포함도의 분모에 더하는 상수. 짧은 이름이 거저 1.0 을 받는 것을 막는다 —
# 두 글자 노드는 아무 문장에나 통째로 들어간다.
#
# 0 으로 둔다. 두 잣대가 정반대를 가리켰고, 갈라 보니 한쪽이 자를 잘못
# 대고 있었다.
#
#   κ      --score 가림   사람이 쓴 물음 16개
#   0          12%            15/16
#   4          14%            15/16
#   8          25%             8/16
#   16         50%             5/16   (이름으로 물으면 도 84%로 깨진다)
#   32         64%             0/16
#
# --score 의 물음은 발췌에서 이름만 지워 만든 것이라 나머지 글자가 그대로
# 남는다. κ 를 키우면 노드 이름이 눌려 발췌 직접검색이 이기는데, 그 길이
# 하는 일이 '받은 문장을 도로 알아보기' 다. 설명채점 docstring 이 경고한
# 그 인코더 함정을 κ 로 되사는 셈이다. 사람이 쓴 물음에는 그 단서가 없고,
# 거기서는 κ 가 커질수록 그냥 미지가 는다(1개 -> 11개).
#
# 그래서 0 이다. 문서그래프 기준 사람 물음 적중은 신경망 14/16, 고치기 전
# 문자 코사인 0/16, 지금 15/16 이다.
_smoothing = float(os.environ.get("KG_SMOOTH", "0"))
# 이름에 방식을 적어 둔다. 캐시 키가 MODEL 을 쓰므로, 구현을 바꾸고 이름을
# 안 바꾸면 낡은 벡터를 그대로 읽는다 — 음절에서 자모로 바꿨을 때 실제로
# 그래서 적중률이 100%에서 4%로 무너졌다.
MODEL = ("문자포함도2-%d-자모%.1f-매끔%.1f"
         % (_character_dimensions, _jamo_weight, _smoothing) if _mode == "문자"
         else "jhgan/ko-sroberta-multitask")   # 768d
# 라우터가 "이 질문은 어느 그래프냐" 를 자를 문턱. 인코더마다 재는 것이
# 달라 한 값으로 둘 수 없다 — 포함도는 음성이 0.3 대에 몰리는데 코사인은
# 무엇에나 높게 붙는다. 실제로 하나로 두었더니 0.55 가 문자에서는 너무
# 높고(답함 48%) 신경에서는 너무 낮았다(밖 질문 11/25 가 샜다).
#
# routing_benchmark.py 로 쓸어 정했다. 그래프 47개 · 안 본 말투 891개 ·
# 갈 그래프가 없는 질문 25개:
#
#   문자    0.40 답함 66.6% 거절 17/25 | 0.45 64.0% 24/25 | 0.55 48.0% 24/25
#   신경    0.55 답함 87.3% 거절 14/25 | 0.60 77.8% 19/25 | 0.70 46.1% 22/25
#
# 문자는 0.45 에 무릎이 있었다 — 거절이 17에서 24로 뛰고 그 위로는 평평했다.
#
# 짧은 색인 줄 가드가 들어온 뒤 다시 쟀다. 가드가 밖 질문을 따로 막아 주므로
# 문턱이 그 일을 겸할 필요가 줄었다. 0.43 은 0.45 와 밖 거절이 같은데
# (답으로 세면 25/25, 라우터만 보면 19/25) 증거 발화 라우팅이 61.8%에서
# 68.8%로 오른다. 그 아래로는 거절이 무너진다(0.40 에서 17/25). 신경은 무릎이 없어 고르는 문제다. 0.60 에서
# 0.65 로 한 칸 올리면 거절은 하나 늘고 답함은 16.7%p 가 깎여 남는 장사가
# 아니다. 그래프가 늘면 다시 재야 한다.
라우팅문턱 = 0.43 if _mode == "문자" else 0.60
# 미지 로그에서 개념 후보를 뭉칠 때의 문턱. 0.62 하나로 두었더니 문자
# 인코더에서는 아무것도 안 뭉쳤다 — 뜻이 같은 세 문장이 0.23~0.32 라
# 문턱 근처에도 못 갔다. 글자만 보는 인코더에는 바꿔 말한 문장이 남남이다.
#
# 쓸어서 잰 것 (같은 뜻 묶음 2개 · 딴 얘기 묶음 3개):
#
#     문턱    같은뜻 잡음   딴얘기 헛뭉침
#     0.35      0/2          0/3
#     0.32      2/2          0/3     <- 여기서 열린다
#     0.30      2/2          0/3
#     0.22      2/2          0/3
#     0.20      2/2          1/3     <- 여기서 샌다
#
# 창이 0.22~0.32 라 위쪽에 붙여 0.30 으로 둔다. 표본이 다섯 묶음뿐이니
# 미지 로그가 쌓이면 다시 재야 한다.
뭉침문턱 = 0.30 if _mode == "문자" else 0.62
# 목표를 닮았다고 볼 최소 확신. 이보다 낮으면 목표주장이 아니라 미지다.
# 목표주장은 '결론만 말했다' 는 판정이지 거절이 아니라, 낮은 점수에서
# 그대로 두면 밖 질문에 일을 시작한다. 문턱과 마찬가지로 인코더마다
# 눈금이 달라 값을 가른다.
목표닮음문턱 = 0.62 if _mode == "문자" else 0.75
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
    import 한글
    return 한글.자모펴기(text)


# 낱말을 가르는 것은 공백만이 아니다. 코드 이름 'judge()' 의 괄호도,
# '_vec' 의 밑줄도 사람이 물을 때는 안 치는 것들이다.
_word_break = re.compile(r"[\W_]+", re.UNICODE)


def _character_grams(text):
    """음절 n-gram 과 자모 n-gram 을 무게와 함께. 조각당 한 번씩만 센다.

    경계표(\x02 \x03)를 문자열 양 끝이 아니라 **낱말마다** 두른다. 포함도를
    재려면 이래야 한다 — 문자열 끝에만 두르면 '도메인' 의 조각 중 절반이
    경계표를 물고 있어서, 질문 한가운데의 '도메인을' 과는 영영 안 맞는다.
    실제로 그 자리에서 포함도가 0.795 대신 0.538 로 깎였다. 낱말마다
    두르면 '\x02도메' 가 양쪽에 다 생긴다. 재보니 문서그래프에서 양성과
    음성의 중앙값 격차가 0.308 -> 0.588 로 벌어졌다."""
    g = mask_numbers(text).strip()
    out = {}
    for base, w in ((g, 1.0), (_decompose_jamo(g), _jamo_weight)):
        if w == 0.0:
            continue
        t = "\x02" + _word_break.sub("\x03\x02", base) + "\x03"
        for n in (2, 3, 4):
            for k in range(len(t) - n + 1):
                fragment = t[k:k + n]
                out[fragment] = out.get(fragment, 0.0) + w
    return out


def _character_vector(text, 쪽="담", dimensions=None):
    """문자 n-gram 벡터. 신경망도 토큰도 안 쓴다.

    한국어는 형태가 붙어 변하므로(해고/해고가/해고를) 글자 n-gram 이 그
    변화를 흡수한다. 2~4 글자를 함께 보면 '부당해고' 와 '해고' 가 겹치는
    부분을 공유한다.

    **코사인이 아니라 포함도(coverage)를 잰다.** 두 벡터를 다르게 만들어
    내적이 곧 '문서 쪽 조각 중 몇 할이 질문 안에 들어 있나' 가 되게 한다.

      속(담기는 쪽)   조각 무게를 제 총무게로 나눈다(L1). 분모가 자기 자신이다.
      담(담는 쪽)     있는 조각을 1 로만 표시한다. 길이가 분모에 안 들어간다.

    어느 쪽이 속인지는 **답이 될 쪽이 속** 으로 정한다. 노드 이름·발췌·
    절 제목이 속이고 질문이 담이다. 짧은 쪽을 속에 두는 규칙이 더 자연스러워
    보여서 뒤집어도 봤는데, 두 자리에서 다 깨졌다.

      발췌   긴 발췌가 짧은 질문을 거저 담는다. '고양이 키우고 싶다' 에
             도로교통법 제49조가 답으로 나왔다. 근거 없이 답하지 않는다는
             것이 이 엔진의 전부라 그건 회귀다.
      절     긴 절이 이긴다. '개발 흐름이 어떻게 되나' 가 '6. 개발 흐름'
             대신 더 긴 'README > 그래프 성장 도구' 로 샜다.

    담는 쪽에 길이 벌점이 없다는 것이 포함도의 값어치이자 위험이다.
    답 후보를 속에 두면 그 위험이 '길어서 이기는' 쪽이 아니라 '짧아서
    이기는' 쪽으로만 남고, 그건 _모르는말 문과 절차찾기 의 낱말 문이
    이미 막고 있다.

    코사인이었을 때 이것이 무너져 있었다. '도메인' 하나만 물으면 1.000
    인데 '엔진은 도메인을 어떻게 다루나' 로 늘리면 0.211 로 떨어졌다 —
    노드 이름이 질문 안에 통째로 들어 있는데도(포함도로는 0.795다). 코사인의 분모에 질문 길이가
    들어가기 때문이고, 사람이 쓰는 질문은 노드 이름보다 늘 길다. 그래서
    문서그래프에서 짧은 사람 질문의 양성 점수(중앙 0.214)가 코퍼스 밖
    질문(중앙 0.175)과 겹쳐 가를 수가 없었다. 문턱을 낮춰도 소용없다 —
    두 분포가 겹쳐 있으면 자르는 자리가 없다.

    포함도로 바꾸니 양성 중앙 0.625, 음성 중앙 0.317 로 갈렸다. 덤으로
    점수가 [0,1] 의 '몇 할' 이라 신경망 코사인과 눈금이 비슷해져,
    그래프에 적힌 임계값(A_MIN 0.45 / OK_MIN 0.58)을 그대로 쓸 수 있다.

    IDF 가중도 재봤지만 소용없었다(양성 0.203 / 음성 0.154). 문제가
    조각의 흔함이 아니라 분모의 길이였기 때문이다.

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
    grams = _character_grams(text)
    for fragment, w in grams.items():
        조각 = fragment.encode("utf-8")
        h = zlib.crc32(조각) % dimensions
        부호 = 1.0 if zlib.crc32(조각 + b"\x00") % 2 else -1.0
        v[h] += (w if 쪽 == "속" else 1.0) * 부호
    if 쪽 == "속":
        총무게 = sum(grams.values())
        return v / (총무게 + _smoothing) if 총무게 else v
    # 담는 쪽은 '있다/없다' 다. 같은 칸에 여러 조각이 겹쳐 쌓여도 한 몫을
    # 넘지 않게 자른다 — 안 자르면 긴 질문이 제 무게로 포함도를 부풀린다.
    return np.clip(v, -1.0, 1.0)


@lru_cache(maxsize=512)
def _담(text):
    """**담는 쪽** 벡터. 무언가가 이 안에 들어 있는지 볼 대상이다.

    보통은 사람이 방금 친 질문이 여기로 온다. 문서 한 절에서 질문을 찾을
    때처럼 뒤집히는 자리도 있다 — 그때는 절이 담는 쪽이다."""
    if _mode == "문자":
        return _character_vector(text, "담")
    return _model().encode([mask_numbers(text)], normalize_embeddings=True)[0]


# 옛 이름. 부르는 자리 대부분이 '질문' 을 담는 쪽으로 쓰고 있었다.
_vec = _담


@lru_cache(maxsize=512)
def _속(text):
    """**담기는 쪽** 벡터 하나. 짧은 쪽이다 — 노드 이름·말 예시, 또는 질문.

    신경망 모드에서는 _담 과 같은 것을 돌려준다. 그쪽은 두 쪽이 대칭인
    코사인이라 가를 이유가 없다."""
    if _mode == "문자":
        return _character_vector(text, "속")
    return _담(text)


def _속들(texts):
    """담기는 쪽 여럿을 한 판에. 하나씩 부르면 모델 forward 가 그 수만큼 돈다 —
    숙고가 후보 다섯의 발췌 여섯을 각각 부르느라 질문 하나에 서른 번이었다."""
    return _여럿(texts, "속")


def _담들(texts):
    """담는 쪽 여럿을 한 판에."""
    return _여럿(texts, "담")


def _여럿(texts, 쪽):
    texts = list(texts)
    import numpy as np
    if not texts:
        return np.zeros((0, 1), dtype="float32")
    if _mode == "문자":
        return np.array([_character_vector(t, 쪽) for t in texts], dtype="float32")
    return _model().encode([mask_numbers(t) for t in texts],
                           normalize_embeddings=True)


_vecs = _속들


class _CharacterModel:
    """sentence-transformers 와 같은 모양으로 감싼다. 부르는 쪽은 안 바뀐다.

    .encode() 로 들어오는 것은 노드의 말 예시다(지식준비·벡터캐시). 그것이
    질문 안에 들어 있는지 보는 것이므로 담기는 쪽이다."""

    def encode(self, sentences, normalize_embeddings=True, **_):
        import numpy as np
        return np.array([_character_vector(sentence, "속") for sentence in sentences],
                        dtype=np.float32)


def _self_check():
    """문자 인코더가 갖춰야 할 성질. 신경망 없이 돈다.

    코사인이 아니라 포함도라, 재는 것은 '길이가 달라도 들어 있으면
    잡히는가' 다. 대칭성은 이제 성질이 아니다 — 일부러 깼다."""
    import numpy as np
    속 = lambda t: _character_vector(t, "속")
    담 = lambda t: _character_vector(t, "담")
    점 = lambda 작은, 큰: float(속(작은) @ 담(큰))

    assert abs(점("해고", "해고") - 1.0) < 1e-5          # 제 자신은 온전히 들어 있다
    assert float(담("해고").max()) <= 1.0 + 1e-6         # 담는 쪽은 있다/없다다

    # 이 파일을 고친 이유. 노드 이름이 질문 안에 통째로 있으면, 질문이
    # 아무리 길어도 점수가 살아 있어야 한다. 코사인일 때 여기가 0.368 로
    # 주저앉았고 그래서 문서그래프의 모든 질문이 미지로 떨어졌다.
    긴질문 = 점("도메인", "엔진은 도메인을 어떻게 다루나")
    assert 긴질문 > 0.75, 긴질문
    assert 점("도메인", "도메인") >= 긴질문              # 그래도 짧은 쪽이 더 높다

    # 형태 변화는 잡는다 — 한국어는 조사가 붙어 변한다
    assert 점("해고", "해고가 부당하다") > 0.5
    # 동의어는 못 잡는다 — '해고' 와 '면직' 은 자모가 안 겹쳐 0 이다.
    # 그 자리는 그래프가 메운다(노드마다 말 예시가 여럿, 개념망이 상위어에
    # 하위어 표현을 붙임).
    assert 점("해고", "면직") < 0.05
    # 절대값이 아니라 격차로 본다 — 형태 변화가 남남보다 몇 배인지.
    비슷, 남남 = 점("해고", "해고가"), 점("해고", "고양이")
    assert 비슷 > 4 * max(남남, 0.01), (비슷, 남남)
    # 숫자는 가려서 본다. '820점' 과 '320점' 이 다른 노드가 되면 안 된다
    assert 점("820점입니다", "320점입니다") > 0.9
    # 코퍼스 밖 질문은 낮아야 한다. 가르는 자리가 있어야 문턱이 뜻을 갖는다.
    assert 점("그래프", "오늘 서울 날씨 어때") < 0.3
    print("인코더 selfcheck ok")


# 문장 끝뿐 아니라 연결어미에서도 자른다. 한국어는 한 문장에 사실 여럿을
# 이어 붙인다 — '결승점을 코앞에 두고 전력 질주하여 2등을 추월했습니다' 는
# 마침표가 하나인데 사실이 셋이다. 통째로 재면 미끼(전력 질주)가 이겨서
# 정작 증거가 안 걸렸다. 자른 조각은 통째 문장에 더해지는 것이라, 후보가
# 늘 뿐 줄지는 않는다.
_연결어미 = "하여|해서|하고|지만|는데|면서|어서|아서|니까|므로|려고|두고"
_sentence_splitter = re.compile(
    r"[.!?\n]+|(?<=니다)\s*[,;]\s*|(?<=습니다)\s+|(?<=%s)\s+" % _연결어미)


_영단어 = re.compile(r"[A-Za-z][A-Za-z0-9_.\-]*")
_한글낱말 = re.compile(r"[가-힣]+")
# 영어 질문 껍데기. 이 낱말들은 무엇을 묻는지가 아니라 묻는다는 표시다.
_영질문틀 = {"what", "when", "how", "where", "who", "why", "which", "whose",
             "is", "are", "am", "was", "were", "be", "do", "does", "did",
             "can", "could", "should", "would", "will", "the", "a", "an",
             "i", "you", "me", "my", "your", "of", "to", "for", "in", "on",
             "tell", "show", "give", "explain", "about", "please", "s",
             "it", "this", "that", "there", "here", "and", "or", "not",
             "with", "from", "at", "by", "as", "if", "so", "have", "has"}


def 언어보기(text):
    """글자만 보고 언어를 가른다. -> "한국어" / "영어" / "섞임"

    토큰도 모델도 안 쓴다. 한글과 라틴 글자 수를 세면 갈린다. 'CCTV 확인하고
    싶어' 처럼 용어만 영어인 것은 섞임이 아니라 한국어다 — 그 말을 하는
    사람은 한국어로 답을 기대한다.

    숫자와 기호는 안 센다. 어느 언어에도 속하지 않는다."""
    한 = len(re.findall(r"[가-힣]", text))
    영 = len(re.findall(r"[A-Za-z]", text))
    if not 한 and not 영:
        return "섞임"
    if not 영:
        return "한국어"
    if not 한:
        # 낱말 하나짜리 영문은 언어를 못 정한다. 'CCTV' 는 한국어 그래프의
        # 증거 이름이기도 하고 영어 질문이기도 하다. 문장 꼴이 아니면
        # 어느 쪽도 밀어내지 않는다.
        if len(re.findall(r"[A-Za-z][A-Za-z0-9_.\-]*", text)) < 2:
            return "섞임"
        return "영어"
    # 한글이 조금이라도 있으면 한국어로 본다. 용어만 영어인 문장이 대부분이다.
    return "한국어" if 한 >= 2 else "영어"


def 영어껍데기벗기기(text):
    """영어 질문틀을 뺀 알맹이. 뺄 것이 없으면 원문 그대로.

    포함도는 '색인 줄의 조각 중 몇 할이 질문 안에 있나' 라, 질문에 군더더기가
    많으면 그만큼 묽어진다. 한국어 질문틀('~가 뭐야')은 그래프 예시에 그대로
    들어 있어 문제가 안 되는데, 영어 질문틀은 어디에도 없다. 'DNS' 만 물으면
    0.67 인데 'what is DNS' 는 0.35 로 떨어졌다.

    영어 낱말이 실제로 든 질문에만 쓴다. 한국어 질문에 대고 벗기면 오히려
    'DNS가 뭐야' 가 1.00 에서 0.78 로 내려간다 — 그쪽은 틀도 재료다."""
    영 = _영단어.findall(text)
    if not 영:
        return text
    알맹이 = [w for w in 영 if w.lower() not in _영질문틀]
    if not 알맹이:
        return text
    한 = _한글낱말.findall(text)
    return " ".join(알맹이 + 한)


def split_fragments(text):
    """긴 발화를 문장 단위로 쪼갠다.

    실제 사용자는 '증거를 보면 A입니다. 따라서 B이고, 그러므로 C입니다' 처럼
    한 번에 여러 주장을 한다. 문장 하나 = 주장 하나로 가정하면 전체 평균이
    흐려져 아무 노드에도 안 걸리고 미지로 떨어진다."""
    fragments = [x.strip() for x in _sentence_splitter.split(text) if x and len(x.strip()) > 3]
    나온것 = ([text] + fragments) if len(fragments) > 1 else [text]
    # 영어 껍데기를 벗긴 것도 조각으로 더한다. 통째 영어 질문이 그래프가
    # 아는 낱말을 들고도 못 가는 자리를 메운다. 원문도 그대로 남으므로
    # 후보가 늘 뿐이다.
    벗김 = 영어껍데기벗기기(text)
    if 벗김 != text and 벗김 not in 나온것:
        나온것.append(벗김)
    return 나온것


조각내기 = split_fragments


if __name__ == "__main__":
    if "--check" in sys.argv:
        _self_check()
