# -*- coding: utf-8 -*-
"""그림 층 — 사진을 국소 무늬로 쪼개고, 그 무늬의 어휘가 포화하는지 잰다.

    python 그림.py --힙스              # 시각 어휘가 포화하나 (data/그림)
    python 그림.py --갈림              # 비트를 얼마로 잡아야 하나
    python 그림.py --관계              # 관계를 넣으면 분리도가 오르나 (RAG)
    python 그림.py --흔들기            # 구조만 무너뜨렸을 때 관계가 알아채나
    python 그림.py --각도              # 같은 물건을 몇 도까지 알아보나 (COIL-100)
    python 그림.py --맞히기            # 시점 일부로 익히고 나머지로 맞힌다
    python 그림.py --어수선            # 실제 사진 배경 위에서도 찾아내나
    python 그림.py --표적스캔 --유도 --차지 .25  # 1홉 창 → 부분그래프 3홉 확인
    python 그림.py --덩이 [--씨앗 3] [--조건부]  # 씨앗 덩이 국소화
                                       # 기본은 열린 판. --조건부 는 목표를 준다
    python 그림.py --힙스 <폴더> --장 800
    python 그림.py --check             # 자체 검사

여기에는 신경망이 없다. 학습하는 것도 없다. 고정 필터로 기울기를 재고,
고정 무작위 초평면으로 쪼갠다 — 인코더.py 의 부호 해싱과 같은 계열이다.

**왜 코드북을 학습하지 않나.** 시각 단어를 만드는 흔한 방법은 서술자를
k-means 로 묶어 사전을 만드는 것이다. 그런데 그러면 사전 크기 k 를 사람이
정하는 것이라 "어휘가 몇 개냐" 를 사람이 답해 버린다. 힙스가 순환논법이
된다. 고정 초평면은 아무것도 안 배우므로 어휘 수가 자료에서만 나온다.
비트를 늘리면 천장이 열리고, 자료가 포화하면 비트를 늘려도 안 는다.
그 차이를 보는 것이 이 파일의 전부다.
"""
import glob, json, os, re, sys, warnings
import numpy as np

# PIL 이 팔레트/투명도 조합마다 뿜는 경고는 이 측정과 무관하다. 1,000장을
# 도는 동안 표를 밀어내서 정작 볼 숫자가 안 보인다.
warnings.filterwarnings("ignore", category=UserWarning, module="PIL")

_여기 = os.path.dirname(os.path.abspath(__file__))
_최대비트 = 32          # 코드는 늘 32비트로 만들고, 앞자리만 잘라 쓴다
_씨 = 20260901


def _길(p):
    return p if os.path.isabs(p) or os.path.exists(p) else os.path.join(_여기, p)


# ───────────────────────── 보기 ─────────────────────────

def 회색(경로, 최대변=256):
    """사진 하나를 회색 배열로. 크기를 맞추는 이유는 무늬의 크기를 맞추려는 것.

    원본 크기 그대로 보면 큰 사진의 무늬와 작은 사진의 무늬가 서로 다른
    단어가 된다 — 같은 것을 찍었는데 화소 수가 다르다는 이유로."""
    from PIL import Image
    im = Image.open(경로)
    if getattr(im, "n_frames", 1) > 1:
        im.seek(0)                       # 움직이는 그림은 첫 장만
    im = im.convert("L")
    w, h = im.size
    배 = 최대변 / max(w, h)
    if 배 < 1:
        im = im.resize((max(8, int(w * 배)), max(8, int(h * 배))), Image.BILINEAR)
    return np.asarray(im, dtype=np.float32) / 255.0


def _줄이기(a, 배):
    if 배 >= 1.0:
        return a
    from PIL import Image
    h, w = a.shape
    나 = Image.fromarray((a * 255).astype(np.uint8))
    나 = 나.resize((max(8, int(w * 배)), max(8, int(h * 배))), Image.BILINEAR)
    return np.asarray(나, dtype=np.float32) / 255.0


def _기울기(a):
    """가장 단순한 방향 필터. V1 이 하는 일에서 학습이 필요 없는 부분이다."""
    gx = np.zeros_like(a)
    gy = np.zeros_like(a)
    gx[:, 1:-1] = a[:, 2:] - a[:, :-2]
    gy[1:-1, :] = a[2:, :] - a[:-2, :]
    return gx, gy


def 서술자들(a, 칸=4, 칸크기=4, 성김=8, 최소에너지=0.02, 방향수=8):
    """사진 하나 -> 국소 무늬 서술자 여럿. (n, 칸*칸*방향수)

    조각 하나를 4x4 칸으로 나누고 칸마다 기울기 방향 히스토그램을 센다.
    사진 한 장을 벡터 하나로 만들지 않는 것이 요점이다 — 인코더.py 의
    조각내기 주석과 같은 이유다. 한 장에 문·사람·흉기가 다 들어 있는데
    평균을 내면 아무것도 아닌 것이 된다.

    밋밋한 조각(하늘, 흰 벽)은 버린다. 무늬가 없는 자리는 단어가 아니고,
    그냥 두면 가장 흔한 단어 하나가 통계를 다 먹는다."""
    P = 칸 * 칸크기
    if a.shape[0] < P or a.shape[1] < P:
        return np.zeros((0, 칸 * 칸 * 방향수), np.float32)
    gx, gy = _기울기(a)
    크기 = np.hypot(gx, gy)
    빈 = np.minimum((np.arctan2(gy, gx) % (2 * np.pi)) / (2 * np.pi) * 방향수, 방향수 - 1)
    빈 = 빈.astype(np.int32)
    H, W = a.shape
    나온것 = []
    for y in range(0, H - P + 1, 성김):
        for x in range(0, W - P + 1, 성김):
            m = 크기[y:y + P, x:x + P]
            if float(m.mean()) < 최소에너지:
                continue
            b = 빈[y:y + P, x:x + P]
            v = np.zeros(칸 * 칸 * 방향수, dtype=np.float32)
            for cy in range(칸):
                for cx in range(칸):
                    mm = m[cy * 칸크기:(cy + 1) * 칸크기, cx * 칸크기:(cx + 1) * 칸크기].ravel()
                    bb = b[cy * 칸크기:(cy + 1) * 칸크기, cx * 칸크기:(cx + 1) * 칸크기].ravel()
                    np.add.at(v, (cy * 칸 + cx) * 방향수 + bb, mm)
            크 = float(np.linalg.norm(v))
            if 크 < 1e-6:
                continue
            v /= 크
            np.minimum(v, 0.2, out=v)     # 한 방향이 다 먹는 것을 막는다
            크 = float(np.linalg.norm(v))
            나온것.append(v / 크)
    if not 나온것:
        return np.zeros((0, 칸 * 칸 * 방향수), np.float32)
    return np.asarray(나온것, dtype=np.float32)


def 여러크기(경로, 배들=(1.0, 0.5, 0.25)):
    """같은 사진을 세 크기로 본다. 사람 눈도 한 크기로만 보지 않는다.

    작게 줄여서 같은 16화소 조각을 보면 더 넓은 것을 보는 셈이다 —
    큰 무늬(얼굴 윤곽)와 작은 무늬(털결)를 같은 코드로 다룰 수 있다."""
    a = 회색(경로)
    묶음 = [서술자들(_줄이기(a, 배)) for 배 in 배들]
    묶음 = [x for x in 묶음 if len(x)]
    return np.concatenate(묶음) if 묶음 else np.zeros((0, 128), np.float32)


# ───────────────────────── 시각 단어 ─────────────────────────

_판 = {}


def _투영판(차원):
    """고정 무작위 초평면. 씨가 박혀 있어서 언제 돌려도 같은 단어가 나온다.

    씨를 바꾸면 단어 이름이 전부 바뀐다. 인코더.py 가 MODEL 이름에 방식을
    적어 둔 것과 같은 이유로, 이 씨는 함부로 바꾸면 안 된다."""
    if 차원 not in _판:
        _판[차원] = np.random.RandomState(_씨).randn(차원, _최대비트).astype(np.float32)
    return _판[차원]


def 시각단어(서술, 비트=_최대비트):
    """서술자 -> 정수 단어. 앞 비트만 잘라 쓰면 그대로 더 거친 단어가 된다.

    비트가 곧 어휘의 고움이다. 12비트면 4096칸, 20비트면 100만 칸.
    자료가 포화하는지 보려면 천장을 올려 가며 봐야 한다 — 천장에 닿아서
    안 느는 것과 자료가 다 떨어져서 안 느는 것은 완전히 다른 이야기다."""
    if not len(서술):
        return np.zeros(0, dtype=np.int64)
    부호 = (서술 @ _투영판(서술.shape[1])) > 0
    자리 = (1 << np.arange(_최대비트, dtype=np.int64))[::-1]
    코드 = (부호 * 자리).sum(1)
    return 코드 >> (_최대비트 - 비트)


# ───────────────────────── 힙스 ─────────────────────────

def _기울기맞추기(엔, 브이):
    """log V = log K + b log N 을 최소제곱으로 맞춘다. -> b

    앞쪽은 K 가 지배해서 휘므로 뒤쪽 절반만 쓴다."""
    엔 = np.asarray(엔, dtype=np.float64)
    브이 = np.asarray(브이, dtype=np.float64)
    성한곳 = (엔 > 0) & (브이 > 0)
    엔, 브이 = 엔[성한곳], 브이[성한곳]
    if len(엔) < 3:
        return float("nan")
    절반 = len(엔) // 2
    x, y = np.log(엔[절반:]), np.log(브이[절반:])
    if len(x) < 2 or x.std() < 1e-9:
        return float("nan")
    return float(np.polyfit(x, y, 1)[0])


def 힙스(폴더="data/그림", 비트들=(8, 12, 16, 20, 24, 28, 32), 최대장=None, 씨=1):
    """사진을 하나씩 보며 새 시각 단어가 얼마나 나오는지 센다.

    텍스트에서 이 저장소가 잰 것과 같은 것이다 — 법 코퍼스에서 b=0.342 였고,
    그래서 '개념 공간이 무한해서 못 덮는다' 가 뒤집혔다. 그림에도 같은 것을
    묻는다. b 가 1 에 가까우면 사진마다 새 무늬가 계속 나온다는 뜻이라
    이 방향은 거기서 끝난다. 확실히 작으면 시각 알파벳이 유한하다는 뜻이다."""
    폴더 = _길(폴더)
    파일들 = sorted(f for f in glob.glob(os.path.join(폴더, "*"))
                    if os.path.splitext(f)[1].lower()
                    in (".jpg", ".jpeg", ".png", ".gif", ".webp"))
    np.random.RandomState(씨).shuffle(파일들)      # 문서 순서가 남으면 주제가 뭉친다
    if 최대장:
        파일들 = 파일들[:최대장]
    if not 파일들:
        print("%s 에 사진이 없다. 먼저: python collectors/위키.py --그림 --아무거나 300" % 폴더)
        return None

    본것 = {b: set() for b in 비트들}
    자취, 엔, 장수 = [], 0, 0
    # 막판 새 단어 비율은 비트마다 따로 센다. 가장 고운 비트에서만 재면
    # 거의 아무것도 안 맞는 자리의 숫자라 늘 100%에 가깝게 나온다.
    막판새것 = {b: 0 for b in 비트들}
    막판전체 = {b: 0 for b in 비트들}
    막판시작 = int(len(파일들) * 0.9)
    for i, f in enumerate(파일들):
        try:
            서술 = 여러크기(f)
        except Exception:
            continue
        if not len(서술):
            continue
        장수 += 1
        엔 += len(서술)
        코드 = 시각단어(서술)
        for b in 비트들:
            거친것 = set((코드 >> (_최대비트 - b)).tolist())
            if i >= 막판시작:
                막판새것[b] += len(거친것 - 본것[b])
                막판전체[b] += len(거친것)
            본것[b] |= 거친것
        자취.append((장수, 엔, {b: len(본것[b]) for b in 비트들}))
        if 장수 % 100 == 0:
            print("  %4d장  서술자 %8d  단어(16비트) %7d" % (장수, 엔, len(본것[16])
                                                        if 16 in 본것 else -1))

    print()
    print("사진 %d장, 서술자 %s개" % (장수, "{:,}".format(엔)))
    print()
    print("비트   천장       어휘 V      V/천장    기울기 b   막판새단어")
    print("---- --------- ---------- --------- --------- ----------")
    결과 = {}
    for b in 비트들:
        브이 = [x[2][b] for x in 자취]
        기울 = _기울기맞추기([x[1] for x in 자취], 브이)
        천장 = 1 << b
        결과[b] = {"어휘": 브이[-1], "천장": 천장, "b": 기울}
        막판 = (100.0 * 막판새것[b] / 막판전체[b]) if 막판전체[b] else float("nan")
        결과[b]["막판"] = 막판
        표 = "  천장" if 브이[-1] > 0.5 * 천장 else ""
        print("%4d %9d %10d %8.1f%% %8.3f %8.1f%%%s"
              % (b, 천장, 브이[-1], 100.0 * 브이[-1] / 천장, 기울, 막판, 표))
    print()
    print("읽는 법: '천장' 은 어휘가 천장의 절반을 넘은 줄이다 — 자료가 아니라")
    print("비트 수가 막은 것이라 그 줄의 b 는 믿을 수 없다. 갈림이 고른 비트가")
    print("천장에 안 걸리는지 함께 본다. b 가 1 에 가까우면 무늬가 계속 새로")
    print("나온다는 뜻이고, 작으면 포화한다(법 코퍼스 글은 b=0.342 였다).")
    print("막판새단어 = 마지막 10%% 사진이 처음 보는 무늬를 몇 %% 가져왔나.")
    return {"장": 장수, "서술자": 엔, "비트별": 결과, "자취": 자취}


# ───────────────────────── 갈림 ─────────────────────────

def _문서표(폴더):
    """파일 -> 어느 문서에서 왔나. 수집기가 남긴 목록에서 읽는다."""
    경로 = os.path.join(폴더, "그림목록.jsonl")
    표 = {}
    if os.path.exists(경로):
        with open(경로, encoding="utf-8") as f:
            for 줄 in f:
                try:
                    x = json.loads(줄)
                except Exception:
                    continue
                표[x["파일"]] = x.get("문서", "")
    return 표


def 갈림(폴더="data/그림", 비트들=(8, 12, 16, 20, 24, 28, 32),
        최대장=None, 짝수=4000, 씨=1):
    """비트를 얼마로 잡아야 하나. 어휘는 커야 좋은 게 아니라 갈려야 좋다.

    힙스의 b 는 비트 수에 통째로 끌려다닌다 — 잘게 쪼개면 당연히 새 단어가
    계속 나온다. 그래서 b 만으로는 아무 말도 못 한다. 쓸모 있는 고움이
    어디인지를 먼저 못박아야 그 자리의 b 가 뜻을 갖는다.

    자는 수집기가 공짜로 남겨 뒀다. 같은 문서에서 온 사진끼리는 닮았고
    아무 사진 둘은 안 닮았다. 그 격차가 가장 큰 비트가 쓸모 있는 고움이다.
    인코더.py 가 '해고/해고가' 와 '해고/고양이' 를 견준 것과 같은 모양이다.

    겹침을 두 가지로 잰다. 그냥 자카드는 흔한 무늬에 먹힌다 — 사진 한 장에
    단어가 수천 개인데 어디에나 있는 밋밋한 에지가 교집합을 채운다. 드문
    가중은 드문 단어에 무게를 준다(글에서 IDF 가 하는 일). 둘이 갈리면
    문제는 재는 법이고, 안 갈리면 무늬 하나가 원래 아무것도 안 가리키는
    것이다 — 그러면 부품 하나로 매칭한다는 발상을 접고 배치로 가야 한다."""
    폴더 = _길(폴더)
    문서표 = _문서표(폴더)
    파일들 = sorted(f for f in glob.glob(os.path.join(폴더, "*"))
                    if os.path.splitext(f)[1].lower()
                    in (".jpg", ".jpeg", ".png", ".gif", ".webp"))
    rs = np.random.RandomState(씨)
    rs.shuffle(파일들)
    if 최대장:
        파일들 = 파일들[:최대장]

    단어, 문서 = [], []
    for f in 파일들:
        try:
            서술 = 여러크기(f)
        except Exception:
            continue
        if not len(서술):
            continue
        단어.append(np.unique(시각단어(서술)))
        문서.append(문서표.get(os.path.basename(f), ""))
    if len(단어) < 4:
        print("사진이 너무 적다 (%d장)" % len(단어))
        return None

    무리 = {}
    for i, d in enumerate(문서):
        if d:
            무리.setdefault(d, []).append(i)
    같은짝 = [(a, b) for v in 무리.values() if len(v) > 1
              for k, a in enumerate(v) for b in v[k + 1:]]
    if not 같은짝:
        print("같은 문서에서 온 사진 짝이 없다. 그림목록.jsonl 이 있는지 본다.")
        return None
    rs.shuffle(같은짝)
    같은짝 = 같은짝[:짝수]
    남남짝 = []
    while len(남남짝) < len(같은짝):
        a, b = rs.randint(0, len(단어)), rs.randint(0, len(단어))
        if a != b and (not 문서[a] or 문서[a] != 문서[b]):
            남남짝.append((a, b))

    print("사진 %d장, 같은 문서 짝 %d, 남남 짝 %d"
          % (len(단어), len(같은짝), len(남남짝)))
    print()
    print("비트   같은문서     남남      배수   |  분리도   드문가중")
    print("---- --------- --------- -------- | -------- --------")
    결과 = {}
    for 비트 in 비트들:
        나눔 = _최대비트 - 비트
        목록 = [np.unique(w >> 나눔) for w in 단어]
        어휘, 몇장 = np.unique(np.concatenate(목록), return_counts=True)
        무게 = np.log(len(목록) / 몇장.astype(np.float64))   # 드문 단어일수록 무겁다
        무게합 = [float(무게[np.searchsorted(어휘, x)].sum()) for x in 목록]

        def _잼(짝들):
            그냥, 드문 = [], []
            for a, b in 짝들:
                A, B = 목록[a], 목록[b]
                교 = np.intersect1d(A, B, assume_unique=True)
                합 = len(A) + len(B) - len(교)
                그냥.append(len(교) / max(1, 합))
                교무게 = float(무게[np.searchsorted(어휘, 교)].sum()) if len(교) else 0.0
                아래 = 무게합[a] + 무게합[b] - 교무게
                드문.append(교무게 / 아래 if 아래 > 1e-12 else 0.0)
            return np.array(그냥), np.array(드문)

        ㄱ, ㄱ드 = _잼(같은짝)
        ㄴ, ㄴ드 = _잼(남남짝)
        배 = float(np.mean(ㄱ)) / max(float(np.mean(ㄴ)), 1e-12)
        나눔편차 = np.sqrt((np.var(ㄱ) + np.var(ㄴ)) / 2)
        분리도 = (np.mean(ㄱ) - np.mean(ㄴ)) / max(float(나눔편차), 1e-12)
        나눔편차드 = np.sqrt((np.var(ㄱ드) + np.var(ㄴ드)) / 2)
        분리도드 = (np.mean(ㄱ드) - np.mean(ㄴ드)) / max(float(나눔편차드), 1e-12)
        결과[비트] = {"같은쪽": float(np.mean(ㄱ)), "남남": float(np.mean(ㄴ)),
                    "배수": 배, "분리도": float(분리도), "분리도드": float(분리도드)}
        print("%4d %9.4f %9.4f %7.2f배 | %8.3f %8.3f"
              % (비트, np.mean(ㄱ), np.mean(ㄴ), 배, 분리도, 분리도드))

    최고 = max(결과, key=lambda b: 결과[b]["분리도"])
    최고드 = max(결과, key=lambda b: 결과[b]["분리도드"])
    print()
    print("분리도가 가장 큰 곳: 그냥 %d비트 %.3f / 드문가중 %d비트 %.3f"
          % (최고, 결과[최고]["분리도"], 최고드, 결과[최고드]["분리도드"]))
    print()
    print("배수가 아니라 분리도로 고른다. 비트를 올리면 배수는 끝없이 오르는데")
    print("겹침 자체가 0 으로 가기 때문이다 — 아무것도 안 맞는 자리에서 비율만")
    print("커지는 것은 자가 아니다. 분리도는 격차를 흩어진 정도로 나눈다.")
    print("인코더.py 가 자모를 재던 그 자다(0.355 -> 0.519).")
    return 결과


# ───────────────────────── 관계 (RAG) ─────────────────────────
# 봉지로는 분리도가 0.407 에서 안 올랐다. 무늬 하나가 개도 고양이도 나무도
# 가리키기 때문이다. 관계가 본체라면 관계를 넣었을 때 그 숫자가 올라야 한다.
#
# 그래프 편집 거리(GED)가 이 자리의 고전인데 큰 그래프에서 계산이 터진다 —
# 근사 알고리즘이 그 분야 연구 주제 전체다. 대신 WL(Weisfeiler-Lehman)
# 라벨을 쓴다. 되풀이 0회는 관계를 안 보는 봉지고, n회는 n홉 이웃을 라벨에
# 접어 넣은 것이다. 같은 자료 같은 자로 0회와 n회를 견주면 관계의 몫만
# 딱 떨어져 나온다. 학습은 여전히 없다.

def _번호(키):
    """라벨 튜플 -> 정수 하나. 실행이 달라도 같은 값이 나와야 한다.

    처음엔 사전에 나온 순서대로 번호를 붙였다. 한 실행 안에서는 멀쩡한데
    캐시에 넣어 둔 라벨과 나중에 새로 뽑은 라벨이 서로 다른 번호를 받는다 —
    같은 사진을 다시 계산했더니 조각 수는 178개로 같은데 겹침이 0.082 였고,
    어수선함 기준선이 100%에서 25%로 떨어졌다.

    파이썬의 hash 는 정수 튜플에 대해 실행마다 같은 값을 준다(무작위화되는
    것은 문자열이다). 그래서 키에 문자열을 넣지 않는다."""
    return hash(키)


def 영역나누기(경로, 영역수=None, 최대변=320):
    """사진 -> (RGB 배열, 영역 라벨 배열). SLIC 초픽셀.

    영역수를 고정하지 않고 넓이로 정한다. 사진마다 크기가 다른데 영역 수를
    고정하면 영역 하나의 크기가 달라져서, 같은 무늬가 사진 크기에 따라 다른
    라벨을 받는다. 넓이/384 로 두면 영역 크기가 자료가 바뀌어도 같다 —
    위키 사진(320px)과 COIL(128px)을 같은 자로 재려면 이게 있어야 한다."""
    from PIL import Image
    from skimage.segmentation import slic
    im = Image.open(경로)
    if getattr(im, "n_frames", 1) > 1:
        im.seek(0)
    im = im.convert("RGB")
    im.thumbnail((최대변, 최대변))
    a = np.asarray(im, dtype=np.uint8)
    if min(a.shape[:2]) < 24:
        return None
    n = 영역수 or max(12, int(a.shape[0] * a.shape[1] / 384))
    return a, slic(a, n_segments=n, compactness=10, start_label=0)


def 영역자질(a, seg):
    """영역마다 평균 색과 결(기울기 세기)과 크기. -> (색 n×3, 결 n, 크기 n)"""
    n = int(seg.max()) + 1
    납 = seg.ravel()
    크기 = np.bincount(납, minlength=n).astype(np.float64)
    크기 = np.maximum(크기, 1)
    색 = np.stack([np.bincount(납, weights=a[:, :, c].ravel().astype(np.float64),
                               minlength=n) / 크기 for c in range(3)], 1) / 255.0
    회 = a.mean(2).astype(np.float32) / 255.0
    gx = np.zeros_like(회)
    gy = np.zeros_like(회)
    gx[:, 1:-1] = 회[:, 2:] - 회[:, :-2]
    gy[1:-1, :] = 회[2:, :] - 회[:-2, :]
    결 = np.bincount(납, weights=np.hypot(gx, gy).ravel().astype(np.float64),
                     minlength=n) / 크기
    return 색, 결, 크기 / 크기.sum()


def 이웃표(seg):
    """맞닿은 영역끼리 잇는다. 이것이 RAG 의 엣지다 — 계산이지 학습이 아니다."""
    n = int(seg.max()) + 1
    쌍 = []
    for A, B in ((seg[:-1, :], seg[1:, :]), (seg[:, :-1], seg[:, 1:])):
        다름 = A != B
        쌍.append(np.stack([A[다름], B[다름]], 1))
    쌍 = np.unique(np.sort(np.concatenate(쌍), axis=1), axis=0)
    이웃 = [[] for _ in range(n)]
    for x, y in 쌍:
        이웃[x].append(int(y))
        이웃[y].append(int(x))
    return 이웃


_결벽 = (0.05, 0.12)


def 첫라벨(색, 결, 색칸=4):
    """영역 하나를 이름 하나로. 평균 색과 결을 칸에 넣어 자른다."""
    c = np.clip((색 * 색칸).astype(np.int32), 0, 색칸 - 1)
    t = np.digitize(결, _결벽)
    # 키에 문자열을 넣지 않는다. 앞의 0 은 영역 라벨임을 나타내는 표다.
    return [_번호((0, 색칸, int(c[i, 0]), int(c[i, 1]), int(c[i, 2]), int(t[i])))
            for i in range(len(결))]


def 그래프엔그램(초기, 이웃, 최대=3):
    """RAG 를 n-gram 으로 편다. -> [1홉 집합, 2홉 집합, 3홉 집합]

      1-gram  영역 하나            (관계 없음. 봉지다)
      2-gram  맞닿은 두 영역       (a-b)
      3-gram  이어진 세 영역       (a-b-c)

    인코더.py 가 글자에 하는 것과 같다. 낱자만 세면 뜻이 없고 2~4자를
    함께 세면 뜻이 생긴다 — 그래프에서는 그 '이어짐' 이 곧 맞닿음이다.

    처음엔 WL(이웃 라벨을 통째로 접기)을 썼는데 1회 만에 겹침이 0 이 됐다.
    영역이 140개고 차수가 5라 이웃 다중집합이 죄다 유일해져서, 어떤 두
    사진도 라벨을 하나도 공유하지 못한다. n-gram 은 조각이 작아서
    촘촘함이 유지된다."""
    묶음 = [set(초기)]
    if 최대 >= 2:
        둘 = set()
        for i, 옆 in enumerate(이웃):
            for j in 옆:
                if i < j:
                    a, b = 초기[i], 초기[j]
                    둘.add((a, b) if a <= b else (b, a))
        묶음.append(둘)
    if 최대 >= 3:
        셋 = set()
        for i, 옆 in enumerate(이웃):
            가 = [초기[j] for j in 옆]
            for k in range(len(가)):
                for l in range(k + 1, len(가)):
                    a, c = 가[k], 가[l]
                    셋.add((a, 초기[i], c) if a <= c else (c, 초기[i], a))
        묶음.append(셋)
    return 묶음


def 관계(폴더="data/그림", 색칸들=(2, 3, 4), 되풀이=3, 최대장=None,
        짝수=4000, 씨=1):
    """관계를 넣으면 분리도가 오르는가. 갈림과 같은 짝, 같은 자를 쓴다."""
    폴더 = _길(폴더)
    문서표 = _문서표(폴더)
    파일들 = sorted(f for f in glob.glob(os.path.join(폴더, "*"))
                    if os.path.splitext(f)[1].lower()
                    in (".jpg", ".jpeg", ".png", ".gif", ".webp"))
    rs = np.random.RandomState(씨)
    rs.shuffle(파일들)
    if 최대장:
        파일들 = 파일들[:최대장]

    쟁여둠, 문서 = [], []
    노드수, 엣지수 = [], []
    for f in 파일들:
        try:
            난것 = 영역나누기(f)
            if 난것 is None:
                continue
            a, seg = 난것
            색, 결, _ = 영역자질(a, seg)
            이웃 = 이웃표(seg)
        except Exception:
            continue
        쟁여둠.append((색, 결, 이웃))
        문서.append(문서표.get(os.path.basename(f), ""))
        노드수.append(len(결))
        엣지수.append(sum(len(x) for x in 이웃) // 2)
    if len(쟁여둠) < 4:
        print("사진이 너무 적다 (%d장)" % len(쟁여둠))
        return None

    무리 = {}
    for i, d in enumerate(문서):
        if d:
            무리.setdefault(d, []).append(i)
    같은짝 = [(a, b) for v in 무리.values() if len(v) > 1
              for k, a in enumerate(v) for b in v[k + 1:]]
    if not 같은짝:
        print("같은 문서에서 온 사진 짝이 없다.")
        return None
    rs.shuffle(같은짝)
    같은짝 = 같은짝[:짝수]
    남남짝 = []
    while len(남남짝) < len(같은짝):
        a, b = rs.randint(0, len(쟁여둠)), rs.randint(0, len(쟁여둠))
        if a != b and (not 문서[a] or 문서[a] != 문서[b]):
            남남짝.append((a, b))

    print("사진 %d장  영역 중앙값 %d개  엣지 중앙값 %d개  같은문서 짝 %d"
          % (len(쟁여둠), int(np.median(노드수)), int(np.median(엣지수)), len(같은짝)))
    print()
    print("색칸  n홉    같은문서     남남      분리도")
    print("---- ------ --------- --------- ---------")
    결과 = {}
    for 색칸 in 색칸들:
        묶음들 = [그래프엔그램(첫라벨(색, 결, 색칸), 이웃, 되풀이)
                 for 색, 결, 이웃 in 쟁여둠]
        for t in range(되풀이):
            집합 = [x[t] for x in 묶음들]

            def _잼(짝들):
                점 = []
                for a, b in 짝들:
                    A, B = 집합[a], 집합[b]
                    ㅎ = len(A | B)
                    점.append(len(A & B) / ㅎ if ㅎ else 0.0)
                return np.array(점)

            ㄱ, ㄴ = _잼(같은짝), _잼(남남짝)
            흩 = float(np.sqrt((np.var(ㄱ) + np.var(ㄴ)) / 2))
            if 흩 < 1e-9:          # 짝이 너무 적으면 분산이 0 이 되어 터진다
                분 = float("nan")
            else:
                분 = (ㄱ.mean() - ㄴ.mean()) / 흩
            결과[(색칸, t + 1)] = float(분)
            print("%4d %6d %9.4f %9.4f %9.3f%s"
                  % (색칸, t + 1, ㄱ.mean(), ㄴ.mean(), 분,
                     "   <- 봉지(관계 없음)" if t == 0 else ""))
        print()
    성한것 = {k: v for k, v in 결과.items() if v == v}
    if not 성한것:
        print("전부 분산 0 이다. 짝이 너무 적다.")
        return 결과
    최고 = max(성한것, key=성한것.get)
    봉지최고 = max((k for k in 성한것 if k[1] == 1), key=성한것.get)
    print("가장 높은 분리도: 색칸 %d, %d홉 -> %.3f"
          % (최고[0], 최고[1], 성한것[최고]))
    print("관계 없는 봉지 중 최고: 색칸 %d -> %.3f  (%+.0f%%)"
          % (봉지최고[0], 성한것[봉지최고],
             100 * (성한것[최고] / max(성한것[봉지최고], 1e-9) - 1)))
    print("견줄 자리: 시각단어 봉지는 0.407 이었다(--갈림, 16비트).")
    return 결과


# ───────────────────────── 흔들기 ─────────────────────────
# 관계가 값을 하는지를 '같은 문서' 라는 흐린 자 없이 재는 법.
#
# 타일을 잘라 섞으면 색 분포는 그대로인데 맞닿음만 무너진다. 글에서
# 낱말 순서를 섞는 것과 같다 — 봉지는 못 알아채고 n-gram 은 알아챈다.
# 관계가 정보를 나른다면 2·3홉의 겹침이 1홉보다 크게 떨어져야 한다.
# 안 떨어지면 관계는 이 층에서 나를 것이 없다.


def 뒤섞기(a, 칸=8, 씨=0):
    """타일 칸x칸 으로 잘라 섞는다. 같은 화소가 그대로 다 남는다."""
    H, W = a.shape[:2]
    h, w = H // 칸, W // 칸
    if h < 4 or w < 4:
        return None
    타일 = [a[y * h:(y + 1) * h, x * w:(x + 1) * w]
            for y in range(칸) for x in range(칸)]
    차례 = np.random.RandomState(씨).permutation(len(타일))
    새 = np.zeros((h * 칸, w * 칸, a.shape[2]), dtype=a.dtype)
    for k, i in enumerate(차례):
        y, x = divmod(k, 칸)
        새[y * h:(y + 1) * h, x * w:(x + 1) * w] = 타일[i]
    return 새


def 엣지되섞기(이웃, 씨=0):
    """라벨은 그대로 두고 맞닿음만 아무렇게나 다시 잇는다.

    대조군이다. 타일을 섞으면 이음매에서 분할이 달라져 1홉 라벨도 변하고,
    그러면 2·3홉은 그 변화가 곱해져서 떨어진다 — 관계를 본 것이 아니다.
    라벨을 한 글자도 안 바꾸고 구조만 무작위로 만든 이 대조군이 그 몫을
    떼어낸다."""
    쌍 = [(i, j) for i, 옆 in enumerate(이웃) for j in 옆 if i < j]
    rs = np.random.RandomState(씨)
    끝 = np.array([x for 짝 in 쌍 for x in 짝])
    rs.shuffle(끝)
    새 = [[] for _ in 이웃]
    for k in range(0, len(끝) - 1, 2):
        a, b = int(끝[k]), int(끝[k + 1])
        if a != b:
            새[a].append(b)
            새[b].append(a)
    return 새


def _엔그램(a, 색칸, 되풀이=3):
    from skimage.segmentation import slic
    n = max(12, int(a.shape[0] * a.shape[1] / 384))
    seg = slic(a, n_segments=n, compactness=10, start_label=0)
    색, 결, _ = 영역자질(a, seg)
    return 그래프엔그램(첫라벨(색, 결, 색칸), 이웃표(seg), 되풀이)


def 흔들기(폴더="data/그림", 색칸=3, 칸들=(2, 4, 8), 최대장=300, 씨=1):
    """구조만 무너뜨리고 겉모습은 남긴다. 관계의 몫만 떨어져 나온다."""
    폴더 = _길(폴더)
    파일들 = sorted(f for f in glob.glob(os.path.join(폴더, "*"))
                    if os.path.splitext(f)[1].lower()
                    in (".jpg", ".jpeg", ".png", ".gif", ".webp"))
    rs = np.random.RandomState(씨)
    rs.shuffle(파일들)
    파일들 = 파일들[:최대장]

    원본, 되섞음, 섞음 = [], [], {g: [] for g in 칸들}
    for f in 파일들:
        try:
            난것 = 영역나누기(f)
            if 난것 is None:
                continue
            a, seg = 난것
            색, 결, _ = 영역자질(a, seg)
            라벨, 옆 = 첫라벨(색, 결, 색칸), 이웃표(seg)
            ㄱ = 그래프엔그램(라벨, 옆)
            되섞음.append(그래프엔그램(라벨, 엣지되섞기(옆)))
            섞은것 = {}
            for g in 칸들:
                b = 뒤섞기(a, g)
                if b is None:
                    break
                섞은것[g] = _엔그램(b, 색칸)
            if len(섞은것) != len(칸들):
                되섞음.pop()
                continue
        except Exception:
            if len(되섞음) > len(원본):
                되섞음.pop()
            continue
        원본.append(ㄱ)
        for g in 칸들:
            섞음[g].append(섞은것[g])

    if len(원본) < 10:
        print("사진이 너무 적다 (%d장)" % len(원본))
        return None

    def _겹(A, B):
        ㅎ = len(A | B)
        return len(A & B) / ㅎ if ㅎ else 0.0

    # 남남 바닥: 아무 사진 둘. 이보다 안 떨어지면 아무 뜻도 없다
    짝 = [(rs.randint(0, len(원본)), rs.randint(0, len(원본)))
          for _ in range(2000)]
    짝 = [(a, b) for a, b in 짝 if a != b]

    print("사진 %d장, 색칸 %d. 타일을 섞어도 화소는 그대로다." % (len(원본), 색칸))
    print()
    print("n홉   원본↔남남  라벨같고구조무작위  "
          + "  ".join("%d×%d칸" % (g, g) for g in 칸들))
    print("---- ---------  ----------------  "
          + "  ".join(["-------"] * len(칸들)))
    표 = {}
    for t in range(3):
        바닥 = float(np.mean([_겹(원본[a][t], 원본[b][t]) for a, b in 짝]))
        줄 = []
        for g in 칸들:
            줄.append(float(np.mean([_겹(원본[i][t], 섞음[g][i][t])
                                     for i in range(len(원본))])))
        되 = float(np.mean([_겹(원본[i][t], 되섞음[i][t])
                            for i in range(len(원본))]))
        표[t] = (바닥, 줄, 되)
        print("%3d  %9.4f  %16.4f  " % (t + 1, 바닥, 되)
              + "  ".join("%7.4f" % x for x in 줄))
    print()
    print("구조 민감도 = 1 - 겹침. 관계가 정보를 나르면 홉이 늘수록 커야 한다.")
    print("n홉   " + "  ".join("%d×%d칸" % (g, g) for g in 칸들))
    for t in range(3):
        print("%3d   " % (t + 1)
              + "  ".join("%6.1f%%" % (100 * (1 - x)) for x in 표[t][1]))
    print()
    print()
    print("읽는 법. '라벨같고구조무작위' 가 대조군이다 — 라벨을 한 글자도 안")
    print("바꾸고 맞닿음만 무작위로 만든 것이라, 1홉은 정확히 1.0 이어야 하고")
    print("2·3홉이 떨어지는 만큼이 순수한 관계의 몫이다. 그 값이 1 에 가까우면")
    print("관계는 아무것도 안 나른다. 타일 섞기는 거기에 분할 변화까지 얹힌다.")
    return 표


# ───────────────────────── DCT 질감 라벨 ─────────────────────────
# 지금 결은 기울기 세기 평균 하나로 3칸이라, 털결과 격자무늬와 글자가 같은
# 칸에 들어간다. JPEG 이 하듯 8x8 블록을 코사인 기저로 갈라 방향과 주파수를
# 나누면 훨씬 곱게 잡힌다. (JPEG 은 '자주 쓰는 패턴' 을 모으지 않는다 —
# 기저는 고정이고 빈도를 쓰는 것은 마지막 허프만 부호화뿐이다.)
#
# **기본으로 쓰지 않는다.** 재보니 자에 따라 정반대가 나온다.
#   COIL(도는 물건)  방향 넣으면 94.1% -> 89.0%
#   위키(안 도는 것) 방향 넣으면 분리도 0.619 -> 0.697 (1홉)
# 물건이 돌면 질감 방향도 같이 돈다. 결이 세기 하나뿐이라 조잡했던 것이
# 우연히 회전 불변이었다. 건물·글자·나뭇결처럼 안 도는 것에서는 반대다.

_세기벽 = (-3.0, -2.0, -1.0)
_비율벽 = (0.15, 0.35)


def 블록질감(회, 블록=8):
    """8x8 블록마다 DCT -> (가로, 세로, 고주파, 세기) 화소 지도 넉 장."""
    from scipy.fft import dctn
    H, W = 회.shape
    h, w = H // 블록 * 블록, W // 블록 * 블록
    if h < 블록 or w < 블록:
        z = np.zeros((H, W), np.float32)
        return z, z, z, z
    a = 회[:h, :w].reshape(h // 블록, 블록, w // 블록, 블록).transpose(0, 2, 1, 3)
    E = dctn(a, axes=(2, 3), norm="ortho") ** 2
    AC = E.sum((-1, -2)) - E[:, :, 0, 0]
    가로 = E[:, :, 0, 1:].sum(-1) / np.maximum(AC, 1e-9)
    세로 = E[:, :, 1:, 0].sum(-1) / np.maximum(AC, 1e-9)
    높 = E[:, :, 4:, 4:].sum((-1, -2)) / np.maximum(AC, 1e-9)
    세기 = np.log10(AC + 1e-6)

    def 펴기(x):
        y = np.repeat(np.repeat(x, 블록, 0), 블록, 1)
        z = np.zeros((H, W), np.float32)
        z[:h, :w] = y
        if h < H:
            z[h:, :w] = y[-1:, :]
        if w < W:
            z[:, w:] = z[:, w - 1:w]
        return z

    return 펴기(가로), 펴기(세로), 펴기(높), 펴기(세기)


def 질감라벨(판, seg, 색, 색칸=4, 방식="전부"):
    """색 + DCT 질감으로 영역 이름. 방식: 세기 / 방향 / 전부

    라벨을 곱게 할수록 1홉은 좋아지고 3홉은 무너진다(위키 분리도,
    현재 0.619->0.561 대 전부 0.734->0.409). 라벨 가짓수와 홉 차수가
    곱해져서 유효 어휘가 되기 때문이다 — 고움에 예산이 있고 둘이 나눠 쓴다."""
    회 = 판.mean(2).astype(np.float32) / 255.0
    가, 세, 높, 힘 = 블록질감(회)
    n = int(seg.max()) + 1
    납 = seg.ravel()
    수 = np.maximum(np.bincount(납, minlength=n), 1)

    def 평(m):
        return np.bincount(납, weights=m.ravel().astype(np.float64), minlength=n) / 수

    c = np.clip((색 * 색칸).astype(np.int32), 0, 색칸 - 1)
    t힘 = np.digitize(평(힘), _세기벽)
    t가 = np.digitize(평(가), _비율벽)
    t세 = np.digitize(평(세), _비율벽)
    t높 = np.digitize(평(높), _비율벽)
    라벨 = []
    for i in range(n):
        기 = (0, 색칸, int(c[i, 0]), int(c[i, 1]), int(c[i, 2]))
        if 방식 == "세기":
            꼬리 = (int(t힘[i]),)
        elif 방식 == "방향":
            꼬리 = (int(t가[i]), int(t세[i]))
        else:
            꼬리 = (int(t가[i]), int(t세[i]), int(t높[i]), int(t힘[i]))
        라벨.append(_번호(기 + 꼬리))
    return 라벨


# ───────────────────────── 물건 (COIL-100) ─────────────────────────
# 지금까지의 자는 '같은 문서' 였는데 그것은 같은 주제이지 같은 물건이 아니다.
# 관계가 구조를 나르는 것은 대조군으로 확인했지만(1.0 -> 0.37), 같은 문서
# 사진끼리는 구조를 안 나누므로 그 자로는 관계의 값이 안 보인다.
#
# COIL-100 은 물건 100개를 5도씩 돌려가며 72장씩 찍은 것이다. 짝이 완벽하고,
# 게다가 각도라는 눈금이 있다 — 같다/다르다가 아니라 "몇 도까지 버티나" 를
# 잴 수 있다. 라벨은 사람이 붙인 것이 아니라 턴테이블이 준 것이다.


def 어두운데빼기(색, 결, 이웃, 벽=0.12):
    """검은 배경 영역을 그래프에서 뺀다. -> (남은 자리, 새 이웃)

    COIL 은 배경이 검정이라 물건마다 똑같은 검은 영역이 잔뜩 생긴다.
    그대로 두면 다른 물건끼리도 배경 조각을 공유해 바닥이 부풀고, 물건이
    작을수록 배경이 신호를 덮는다. 뺀 자리의 이웃은 그냥 끊는다."""
    남 = [i for i in range(len(결)) if 색[i].max() >= 벽]
    새번호 = {i: k for k, i in enumerate(남)}
    새이웃 = [[새번호[j] for j in 이웃[i] if j in 새번호] for i in 남]
    return 남, 새이웃


def 물건읽기(폴더="data/물건"):
    """-> {물건번호: {각도: 경로}}. 파일 이름이 obj12__85.png 꼴이다."""
    폴더 = _길(폴더)
    표 = {}
    이름꼴 = re.compile(r"obj(\d+)__(\d+)\.png$", re.I)
    for 뿌리, _, 파일들 in os.walk(폴더):
        for f in 파일들:
            m = 이름꼴.search(f)
            if m:
                표.setdefault(int(m.group(1)), {})[int(m.group(2))] = \
                    os.path.join(뿌리, f)
    return 표


def 각도자(폴더="data/물건", 물건수=40, 색칸=4, 영역수=200, 배경빼기=True,
         각도들=(5, 15, 30, 45, 60, 90, 180)):
    """같은 물건을 몇 도까지 알아보나. 다른 물건 바닥과 함께 본다.

    이것이 임계값을 정해 준다. 지금까지 임계값은 손으로 맞췄는데, 여기서는
    각도가 눈금이라 자료가 답한다."""
    표 = 물건읽기(폴더)
    if not 표:
        print("%s 에 COIL 사진이 없다." % _길(폴더))
        return None
    번호들 = sorted(표)[:물건수]
    print("물건 %d개, 시점 %d개씩. n-gram 을 뽑는 중..."
          % (len(번호들), len(표[번호들[0]])))

    주머니 = {}
    for 번호 in 번호들:
        for 각, 길 in sorted(표[번호].items()):
            난것 = 영역나누기(길, 영역수=영역수)
            if 난것 is None:
                continue
            a, seg = 난것
            색, 결, _ = 영역자질(a, seg)
            옆 = 이웃표(seg)
            라벨 = 첫라벨(색, 결, 색칸)
            if 배경빼기:
                남, 옆 = 어두운데빼기(색, 결, 옆)
                라벨 = [라벨[i] for i in 남]
            if len(라벨) < 4:
                continue
            주머니[(번호, 각)] = 그래프엔그램(라벨, 옆)

    def _겹(A, B):
        ㅎ = len(A | B)
        return len(A & B) / ㅎ if ㅎ else 0.0

    rs = np.random.RandomState(1)
    남남 = [(rs.choice(번호들), rs.randint(0, 72) * 5,
             rs.choice(번호들), rs.randint(0, 72) * 5) for _ in range(4000)]
    남남 = [x for x in 남남 if x[0] != x[2]][:2000]

    print()
    print("Δ각도    " + "   ".join("%d홉" % (t + 1) for t in range(3)))
    print("------  " + "  ".join(["------"] * 3))
    결과 = {}
    for d in 각도들:
        짝 = [(번호, 각, 번호, (각 + d) % 360)
              for 번호 in 번호들 for 각 in range(0, 360, 5)]
        줄 = []
        for t in range(3):
            값 = [_겹(주머니[(a, b)][t], 주머니[(c, e)][t])
                  for a, b, c, e in 짝
                  if (a, b) in 주머니 and (c, e) in 주머니]
            줄.append(float(np.mean(값)))
        결과[d] = 줄
        print("%5d°  " % d + "  ".join("%6.4f" % x for x in 줄))
    바닥 = []
    for t in range(3):
        값 = [_겹(주머니[(a, b)][t], 주머니[(c, e)][t])
              for a, b, c, e in 남남
              if (a, b) in 주머니 and (c, e) in 주머니]
        바닥.append(float(np.mean(값)))
    print("남남    " + "  ".join("%6.4f" % x for x in 바닥))
    print()
    print("분리도 (같은 물건 Δ각도 vs 다른 물건)")
    print("Δ각도    " + "   ".join("%d홉" % (t + 1) for t in range(3)))
    for d in 각도들:
        print("%5d°  " % d
              + "  ".join("%6.2f배" % (결과[d][t] / max(바닥[t], 1e-9))
                          for t in range(3)))
    print()
    print("읽는 법: 각도가 벌어져도 바닥보다 확실히 높으면 그 각도까지는")
    print("같은 물건으로 알아본다는 뜻이다. 홉이 늘수록 배수가 커지면")
    print("관계가 시점 변화를 견디는 쪽으로 값을 하는 것이다.")
    return 결과, 바닥


def _성긴표(주머니, 열쇠들, 홉):
    """n-gram 집합들 -> 희소 0/1 행렬. 집합 연산을 행렬 곱으로 바꾼다.

    시험 6,000장 x 학습 1,200장을 파이썬 집합으로 돌리면 720만 번이라
    안 끝난다. |A ∩ B| 는 0/1 행렬의 곱이고 합집합은 크기에서 빼면 된다."""
    from scipy import sparse
    칸 = {}
    행, 열 = [], []
    for i, k in enumerate(열쇠들):
        for g in 주머니[k][홉]:
            c = 칸.get(g)
            if c is None:
                c = len(칸)
                칸[g] = c
            행.append(i)
            열.append(c)
    X = sparse.csr_matrix((np.ones(len(행), dtype=np.float32), (행, 열)),
                          shape=(len(열쇠들), len(칸)))
    return X, 칸


def _물건주머니(폴더, 번호들, 색칸, 영역수, 배경빼기):
    """n-gram 을 뽑아 캐시한다. 사진 7,200장에 4분이라 채점 규칙을 바꿔
    가며 재보려면 매번 다시 뽑을 수가 없다."""
    import pickle
    이름 = ".물건_%d_%d_%d_%d.pkl" % (len(번호들), 색칸, 영역수, int(배경빼기))
    길 = os.path.join(_길(폴더), 이름)
    if os.path.exists(길):
        with open(길, "rb") as f:
            return pickle.load(f)
    표 = 물건읽기(폴더)
    주머니 = {}
    for 번호 in 번호들:
        for 각, 파일 in sorted(표[번호].items()):
            난것 = 영역나누기(파일, 영역수=영역수)
            if 난것 is None:
                continue
            a, seg = 난것
            색, 결, _ = 영역자질(a, seg)
            옆 = 이웃표(seg)
            라벨 = 첫라벨(색, 결, 색칸)
            if 배경빼기:
                남, 옆 = 어두운데빼기(색, 결, 옆)
                라벨 = [라벨[i] for i in 남]
            if len(라벨) < 4:
                continue
            주머니[(번호, 각)] = 그래프엔그램(라벨, 옆)
    with open(길, "wb") as f:
        pickle.dump(주머니, f)
    return 주머니


def 물건맞히기(폴더="data/물건", 물건수=100, 배움간격=30, 색칸=4, 영역수=200,
           배경빼기=True, 굳힘들=(0.25, 0.5, 0.75)):
    """시점 일부로 물건을 익히고 나머지 시점으로 맞힌다. 진짜 정확도.

    두 가지를 견준다.
      1-NN   배운 시점을 통째로 외워 두고 가장 닮은 것을 찾는다 (기준선)
      노드   물건마다 노드 하나. 정의는 배운 시점 여러 장에 살아남은 n-gram
             의 교집합이다 — 한 시점에만 있는 조각은 우연이고, 여러 시점을
             견딘 조각이 그 물건이다.

    노드 쪽이 이 엔진이 하려는 것이다. 가중치를 고치는 것이 아니라 세고
    걸러내는 것이라, '물건 37번이 무엇이냐' 에 조각 목록으로 답할 수 있다."""
    표 = 물건읽기(폴더)
    if not 표:
        print("%s 에 COIL 사진이 없다." % _길(폴더))
        return None
    번호들 = sorted(표)[:물건수]
    배움각 = list(range(0, 360, 배움간격))
    주머니 = _물건주머니(폴더, 번호들, 색칸, 영역수, 배경빼기)

    배움 = [k for k in 주머니 if k[1] in 배움각]
    시험 = [k for k in 주머니 if k[1] not in 배움각]
    print("물건 %d개. 배움 %d장(%d도마다), 시험 %d장. 찍기 정확도 %.1f%%"
          % (len(번호들), len(배움), 배움간격, len(시험), 100.0 / len(번호들)))
    print()
    print("홉  굳힘   조각수    담김     자카드    코사인   |   1-NN")
    print("--- ----  ------  --------  --------  --------  |  -------")
    답 = {}
    from scipy import sparse
    for 홉 in range(3):
        X배, 칸 = _성긴표(주머니, 배움, 홉)
        행, 열 = [], []
        for i, k in enumerate(시험):
            for g in 주머니[k][홉]:
                c = 칸.get(g)
                if c is not None:
                    행.append(i)
                    열.append(c)
        X시 = sparse.csr_matrix((np.ones(len(행), dtype=np.float32), (행, 열)),
                               shape=(len(시험), len(칸)))
        시크기 = np.array([len(주머니[k][홉]) for k in 시험], dtype=np.float32)
        참 = np.array([k[0] for k in 시험])

        겹 = np.asarray((X시 @ X배.T).todense())
        배크기 = np.asarray(X배.sum(1)).ravel()
        자 = 겹 / np.maximum(시크기[:, None] + 배크기[None, :] - 겹, 1e-9)
        일NN = float(np.mean(np.array([배움[j][0] for j in 자.argmax(1)]) == 참))

        for 굳힘 in 굳힘들:
            노드행, 노드열 = [], []
            for n, 번호 in enumerate(번호들):
                자리 = [i for i, k in enumerate(배움) if k[0] == 번호]
                if not 자리:
                    continue
                셈 = np.asarray(X배[자리].sum(0)).ravel()
                산것 = np.where(셈 >= max(2, 굳힘 * len(자리)))[0]
                노드행 += [n] * len(산것)
                노드열 += list(산것)
            N = sparse.csr_matrix((np.ones(len(노드행), dtype=np.float32),
                                   (노드행, 노드열)), shape=(len(번호들), len(칸)))
            ㅋ = np.asarray(N.sum(1)).ravel()
            겹N = np.asarray((X시 @ N.T).todense())
            점수 = {
                # 담김: 노드 정의 중 몇 %가 이 사진에 들어 있나.
                # 정의가 작은 노드가 유리해진다 — 물건이 늘수록 그런 노드가
                # 우연히 이길 기회가 늘어난다.
                "담김": 겹N / np.maximum(ㅋ[None, :], 1e-9),
                "자카드": 겹N / np.maximum(시크기[:, None] + ㅋ[None, :] - 겹N, 1e-9),
                "코사인": 겹N / np.maximum(
                    np.sqrt(시크기[:, None] * ㅋ[None, :]), 1e-9),
            }
            줄 = {이름: float(np.mean(np.array([번호들[j] for j in v.argmax(1)]) == 참))
                  for 이름, v in 점수.items()}
            답[(홉, 굳힘)] = (줄, 일NN, float(ㅋ.mean()))
            print("%2d  %.2f  %6.0f  %7.1f%%  %7.1f%%  %7.1f%%  | %7.1f%%"
                  % (홉 + 1, 굳힘, ㅋ.mean(), 100 * 줄["담김"],
                     100 * 줄["자카드"], 100 * 줄["코사인"], 100 * 일NN))
        print()
    print()
    print("1-NN 은 배운 시점 %d장을 통째로 들고 있고, 노드는 물건마다 조각"
          % len(배움))
    print("목록 하나뿐이다. 노드가 1-NN 에 가까우면 교집합이 물건을 붙든")
    print("것이고, 크게 지면 시점마다 따로 외워야 한다는 뜻이다.")
    return 답


# ───────────────────────── 어수선함 ─────────────────────────
# COIL 은 검은 배경에 물건 하나다. 쉬운 판이라고 적었으니 얼마나 쉬운지
# 재야 한다. INSTRE 는 토렌트로만 배포돼서 못 받았고, 대신 어수선함만
# 떼어내 눈금으로 만든다 — COIL 물건은 배경이 검정이라 오려낼 수 있고
# 위키에서 받은 사진 809장이 배경이 된다.
#
# 합성이라 경계가 부자연스러운 것은 안다. 그 대신 어수선함의 양을 조절할
# 수 있다. 실제 자료는 어수선함·시점·크기·조명이 한꺼번에 바뀌어서
# 무엇 때문에 졌는지 못 가린다.
#
# 익히기는 깨끗한 판에서 하고 시험만 어수선한 데서 한다. 물건을 따로
# 배우고 장면 속에서 찾아내는 것이 실제로 쓰이는 모양이다.


def 오려내기(경로, 벽=30):
    """COIL 사진에서 물건만. -> (RGB, 마스크). 가장 큰 덩어리만 남긴다."""
    from PIL import Image
    from scipy import ndimage
    a = np.asarray(Image.open(경로).convert("RGB"), dtype=np.uint8)
    m = a.max(2) >= 벽
    표, 수 = ndimage.label(m)
    if 수 > 1:
        크기 = ndimage.sum(m, 표, range(1, 수 + 1))
        m = 표 == (int(np.argmax(크기)) + 1)
    return a, m


def 어수선하게(a, m, 배경길, 차지, rs):
    """물건을 실제 사진 위에 붙인다. 차지 = 물건이 화폭에서 차지하는 넓이 비율.

    물건은 원래 화소 크기 그대로 두고 화폭만 키운다. 물건을 줄이면 영역
    크기가 달라져 익힐 때와 다른 라벨이 나온다 — 어수선함이 아니라 크기
    때문에 진 것이 되어버린다."""
    from PIL import Image
    if not m.any():
        return None
    높, 넓 = a.shape[:2]
    # 원래 틀(128x128)을 그대로 옮긴다. 상자만큼 잘라내면 화폭 크기가 달라져
    # SLIC 격자가 익힐 때와 어긋나고, 물건 화소가 같은데도 영역 경계가
    # 달라진다 — 실제로 차지 1.00 기준선이 100% 에서 44% 로 떨어졌다.
    변 = max(높, 넓, int(np.sqrt(int(m.sum()) / max(차지, 1e-6))))
    if 배경길 is None:
        판 = np.zeros((변, 변, 3), dtype=np.uint8)
    else:
        b = Image.open(배경길).convert("RGB")
        b.thumbnail((변 * 3, 변 * 3))
        판 = np.asarray(b, dtype=np.uint8)
        if 판.shape[0] < 변 or 판.shape[1] < 변:
            판 = np.asarray(Image.fromarray(판).resize((변, 변)), dtype=np.uint8)
        y0 = rs.randint(0, 판.shape[0] - 변 + 1)
        x0 = rs.randint(0, 판.shape[1] - 변 + 1)
        판 = 판[y0:y0 + 변, x0:x0 + 변].copy()
    ty = rs.randint(0, 변 - 높 + 1)
    tx = rs.randint(0, 변 - 넓 + 1)
    조각 = 판[ty:ty + 높, tx:tx + 넓]
    조각[m] = a[m]              # 검은 여백은 안 붙인다. 물건 화소만
    return 판


def _노드무게(N):
    """조각마다 무게. 여러 노드에 나오는 조각은 아무것도 안 가리킨다.

    어수선한 판에서는 배경 조각이 흔하고 물건 조각이 드물다. 흔한 것의
    무게를 낮추면 배경이 밀려난다. (위키 갈림에서 IDF 가 나빴던 것과
    반대인데, 거기서는 흔한 것이 신호였고 여기서는 잡음이다.)"""
    df = np.asarray(N.sum(0)).ravel()
    return np.log(1.0 + N.shape[0] / np.maximum(df, 1.0)).astype(np.float32)


def _노드틀(주머니, 배움, 번호들, 홉, 굳힘):
    """배운 시점에서 물건마다 노드 하나. -> (칸, 노드행렬, 노드크기)

    홉은 사람이 부르는 이름(1·2·3홉)이고 그래프엔그램의 자리는 0부터다."""
    from scipy import sparse
    X배, 칸 = _성긴표(주머니, 배움, 홉 - 1)
    행, 열 = [], []
    for n, 번호 in enumerate(번호들):
        자리 = [i for i, k in enumerate(배움) if k[0] == 번호]
        if not 자리:
            continue
        셈 = np.asarray(X배[자리].sum(0)).ravel()
        산것 = np.where(셈 >= max(2, 굳힘 * len(자리)))[0]
        행 += [n] * len(산것)
        열 += list(산것)
    N = sparse.csr_matrix((np.ones(len(행), dtype=np.float32), (행, 열)),
                          shape=(len(번호들), len(칸)))
    무게 = _노드무게(N)
    return 칸, N, np.asarray(N.sum(1)).ravel(), N.multiply(무게).tocsr(), 무게


# ───────────────────────── 표적 조건부 스캔 ─────────────────────────
# 대화 그래프가 찾을 물건 노드를 이미 골랐다는 조건에서만 쓴다. 전체 화폭은
# SLIC 영역의 1홉 라벨과 위치만 보고, 관계(3홉)는 상위 후보 창에서만 읽는다.

def _영역중심(seg):
    """SLIC 영역마다 중심 좌표. 1홉 창 스캔은 라벨과 이것만 쓴다."""
    n = int(seg.max()) + 1
    yy, xx = np.indices(seg.shape)
    납 = seg.ravel()
    수 = np.maximum(np.bincount(납, minlength=n), 1)
    return (np.bincount(납, weights=yy.ravel(), minlength=n) / 수,
            np.bincount(납, weights=xx.ravel(), minlength=n) / 수)


def _창겹침(a, b):
    ay0, ay1, ax0, ax1 = a
    by0, by1, bx0, bx1 = b
    겹 = max(0, min(ay1, by1) - max(ay0, by0)) * max(0, min(ax1, bx1) - max(ax0, bx0))
    합 = (ay1 - ay0) * (ax1 - ax0) + (by1 - by0) * (bx1 - bx0) - 겹
    return 겹 / max(합, 1)


def _표적창후보(라벨, seg, 틀, 표적, 창=128, 성김=16, 후보수=3):
    """목표 노드의 1홉 조각으로 고정 Bounding Box top-k를 찾는다.

    이 단계에는 이웃표나 2·3홉 조각이 없다. 창 안의 1홉 라벨 집합과 목표
    노드 1홉 정의의 자카드만 세며, 과도하게 겹친 창은 NMS로 하나만 남긴다.
    """
    칸, N, _, _, _ = 틀
    if not 0 <= 표적 < N.shape[0]:
        return []
    목표열 = set(N.getrow(표적).indices.tolist())
    if not 목표열:
        return []
    열 = np.asarray([칸.get(g, -1) for g in 라벨])
    yy, xx = _영역중심(seg)
    h, w = seg.shape
    창h, 창w = min(창, h), min(창, w)
    ys = list(range(0, max(h - 창h, 0) + 1, 성김))
    xs = list(range(0, max(w - 창w, 0) + 1, 성김))
    if ys[-1] != h - 창h:
        ys.append(h - 창h)
    if xs[-1] != w - 창w:
        xs.append(w - 창w)
    후보 = []
    for y0 in ys:
        for x0 in xs:
            든것 = set(열[(yy >= y0) & (yy < y0 + 창h) &
                          (xx >= x0) & (xx < x0 + 창w)].tolist())
            든것.discard(-1)
            겹 = len(든것 & 목표열)
            점 = 겹 / max(len(든것) + len(목표열) - 겹, 1)
            후보.append((float(점), (y0, y0 + 창h, x0, x0 + 창w)))
    후보.sort(key=lambda x: x[0], reverse=True)
    답 = []
    for 점, 상자 in 후보:
        if all(_창겹침(상자, 앞상자) < .5 for _, 앞상자 in 답):
            답.append((점, 상자))
        if len(답) >= 후보수:
            break
    return 답


def _상자영역만(seg, 라벨, 이웃, 상자):
    """상자 중심에 든 기존 SLIC 영역만 남긴 유도 부분그래프.

    후보 창에서 새 SLIC을 돌리지 않는다. 학습 때와 같은 장면 분할의 조각 이름을
    보존한 채, 상자 밖 영역과 그 관계만 끊는다.
    """
    y0, y1, x0, x1 = 상자
    yy, xx = _영역중심(seg)
    남 = [i for i in range(len(라벨)) if y0 <= yy[i] < y1 and x0 <= xx[i] < x1]
    새번호 = {i: k for k, i in enumerate(남)}
    return ([라벨[i] for i in 남],
            [[새번호[j] for j in 이웃[i] if j in 새번호] for i in 남])


def _조각맞히기(조각, 틀, 홉):
    """이미 만든 n-gram 집합을 기존 노드 정의와 자카드로 맞힌다."""
    칸, N, 노드크기, _, _ = 틀[홉]
    v = np.zeros(len(칸), dtype=np.float32)
    v[[칸[g] for g in 조각 if g in 칸]] = 1.0
    겹 = np.asarray(N @ v).ravel()
    점수 = 겹 / np.maximum(len(조각) + 노드크기 - 겹, 1e-9)
    n = int(점수.argmax())
    return float(점수[n]), n


def 표적스캔시험(폴더="data/물건", 배경폴더="data/그림", 물건수=100,
            배움간격=30, 시험간격=15, 색칸=4, 영역수=200, 굳힘=.25,
            차지=.25, 후보수=3, 씨=1, 유도=True):
    """표적 1홉 스캔 → 고정 상자 top-k → 유도 부분그래프 3홉 시험.

    회귀 채점에서는 각 시험 사진의 물건 번호를 대화 그래프가 고른 목표로 둔다.
    실제 대화에서는 그 목표 하나만 스캔하고, 목표가 없으면 먼저 되묻는다.
    """
    from skimage.segmentation import slic
    import time
    표 = 물건읽기(폴더)
    if not 표:
        print("%s 에 COIL 사진이 없다." % _길(폴더))
        return None
    번호들 = sorted(표)[:물건수]
    배움각 = list(range(0, 360, 배움간격))
    시험각 = [x for x in range(0, 360, 시험간격) if x not in 배움각]
    주머니 = _물건주머니(폴더, 번호들, 색칸, 영역수, True)
    배움 = [k for k in 주머니 if k[1] in 배움각]
    틀 = {h: _노드틀(주머니, 배움, 번호들, h, 굳힘) for h in (1, 3)}
    배경들 = sorted(glob.glob(os.path.join(_길(배경폴더), "*.jpg")))
    낱 = 128 * 128 / 영역수
    rs = np.random.RandomState(씨)
    맞음, 셈, 스캔초, 확인초 = 0, 0, 0.0, 0.0
    for 번호 in 번호들:
        표적인덱스 = 번호들.index(번호)
        for 각 in 시험각:
            길 = 표[번호].get(각)
            if 길 is None:
                continue
            a, m = 오려내기(길)
            판 = 어수선하게(a, m, 배경들[rs.randint(0, len(배경들))], 차지, rs)
            n = max(12, int(판.shape[0] * 판.shape[1] / 낱))
            t0 = time.perf_counter()
            seg = slic(판, n_segments=n, compactness=10, start_label=0)
            색, 결, _ = 영역자질(판, seg)
            라벨 = 첫라벨(색, 결, 색칸)
            후보들 = _표적창후보(라벨, seg, 틀[1], 표적인덱스, 후보수=후보수)
            스캔초 += time.perf_counter() - t0
            t0 = time.perf_counter()
            옆 = 이웃표(seg)
            최고 = None
            for _, 상자 in 후보들:
                부분라벨, 부분옆 = _상자영역만(seg, 라벨, 옆, 상자)
                if len(부분라벨) < 4:
                    continue
                결과 = _조각맞히기(그래프엔그램(부분라벨, 부분옆)[2], 틀, 3)
                if 최고 is None or 결과[0] > 최고[0]:
                    최고 = 결과
            확인초 += time.perf_counter() - t0
            맞음 += int(최고 is not None and 번호들[최고[1]] == 번호)
            셈 += 1
    답 = 맞음 / max(셈, 1)
    print("표적 조건부 스캔. 물건 %d개 · 시험 %d장 · 차지 %.0f%% · 창 128px top-%d"
          % (len(번호들), 셈, 100 * 차지, 후보수))
    print("  전체 화폭: SLIC+1홉 라벨만 | 후보 창: 기존 SLIC 유도 부분그래프+3홉 자카드")
    print("  최종 3홉 정확도: %.1f%% (%d/%d)" % (100 * 답, 맞음, 셈))
    print("  시간: 스캔 %.1fs · 정밀검사 %.1fs · 합계 %.1fs"
          % (스캔초, 확인초, 스캔초 + 확인초))
    return {"정확도": 답, "장수": 셈, "스캔초": 스캔초, "확인초": 확인초}


def _씨앗덩이(라벨, 옆, 칸, 목표열, 후보수=3):
    """목표 노드의 1홉 조각과 맞는 영역(씨앗)만 골라 연결요소로 묶는다.

    **창도 상자도 안 쓴다.** 유도 부분그래프를 만드는 행위 자체가 국소화이기
    때문이다 — 3홉 조각은 이웃 둘을 낀 가운데가 있어야 만들어지므로, 배경에
    흩어진 가짜 씨앗은 조각을 하나도 못 낳고 물건 위에 뭉친 씨앗만 낳는다.

    그래서 넓히면 전부 나빠진다. 재본 것(물건 100개, 차지 25%):
      씨앗만                       83.9%
      씨앗 + 씨앗이웃 4개 이상      76.3%
      씨앗의 상자 안 전부           63.6%
      씨앗 + 이웃 한 겹             62.5%
    비씨앗을 넣으면 흩어진 씨앗에게 없던 이웃을 만들어 줘서 걔들이 조각을
    낳기 시작한다 — 켜 놓은 거름망을 스스로 끄는 셈이다."""
    맞나 = [칸.get(g, -1) in 목표열 for g in 라벨]
    씨집 = set(i for i, b in enumerate(맞나) if b)
    if not 씨집:
        return []
    본것, 덩이들 = set(), []
    for 씨 in 씨집:
        if 씨 in 본것:
            continue
        더미, 쌓 = [], [씨]
        본것.add(씨)
        while 쌓:
            i = 쌓.pop()
            더미.append(i)
            for j in 옆[i]:
                if j in 씨집 and j not in 본것:
                    본것.add(j)
                    쌓.append(j)
        덩이들.append(더미)
    덩이들.sort(key=len, reverse=True)
    return 덩이들[:후보수]


def _부분조각(라벨, 옆, 남, 홉=3):
    """영역 자리 목록 -> 유도 부분그래프의 n-gram 집합."""
    새 = {i: k for k, i in enumerate(남)}
    return 그래프엔그램([라벨[i] for i in 남],
                     [[새[j] for j in 옆[i] if j in 새] for i in 남])[홉 - 1]


def _씨앗모으기(라벨, 옆, 틀, 차수, 표적=None):
    """차수 조각이 노드 정의에 있는 영역을 씨앗으로. -> {노드자리: 씨앗집합}

    표적을 주면 그 노드 하나만, 안 주면 모든 노드를 훑는다.

    차수를 올릴수록 순도가 오른다 — 배경 영역이 우연히 라벨 하나와 맞을
    확률은 꽤 되지만 이웃과 함께 쌍으로, 셋으로 맞을 확률은 훨씬 낮다.
    목표를 아는 판에서 재보니 1홉 83.9% / 2홉 87.2% / 3홉 90.1% 였고,
    1홉과 2홉을 합집합으로 쓰면 1홉 값으로 되돌아간다(83.9%) — 회수가
    아니라 순도가 이긴다."""
    칸, N = 틀[차수][0], 틀[차수][1]
    if 표적 is None:
        코 = N.tocoo()
        열별 = {}
        for r, c in zip(코.row.tolist(), 코.col.tolist()):
            열별.setdefault(c, []).append(r)
        볼것 = None
    else:
        볼것 = set(N.getrow(표적).indices.tolist())
    모음 = {}

    def 담기(열, 자리들):
        if 볼것 is not None:
            if 열 in 볼것:
                모음.setdefault(표적, set()).update(자리들)
        else:
            for nd in 열별.get(열, ()):
                모음.setdefault(nd, set()).update(자리들)

    if 차수 == 1:
        for i, g in enumerate(라벨):
            열 = 칸.get(g, -1)
            if 열 >= 0:
                담기(열, (i,))
    elif 차수 == 2:
        for i, 옆i in enumerate(옆):
            for j in 옆i:
                if i < j:
                    a, b = 라벨[i], 라벨[j]
                    열 = 칸.get((a, b) if a <= b else (b, a), -1)
                    if 열 >= 0:
                        담기(열, (i, j))
    else:
        for i, 옆i in enumerate(옆):
            가 = [(j, 라벨[j]) for j in 옆i]
            for k in range(len(가)):
                for l in range(k + 1, len(가)):
                    (j1, a), (j2, c) = 가[k], 가[l]
                    열 = 칸.get((a, 라벨[i], c) if a <= c else (c, 라벨[i], a), -1)
                    if 열 >= 0:
                        담기(열, (i, j1, j2))
    return 모음


def _덩이나누기(씨집, 옆, 후보수=3):
    """씨앗을 연결요소로 나눈다. 큰 것부터 후보수 개."""
    본것, 덩이들 = set(), []
    for 씨 in 씨집:
        if 씨 in 본것:
            continue
        더미, 쌓 = [], [씨]
        본것.add(씨)
        while 쌓:
            i = 쌓.pop()
            더미.append(i)
            for j in 옆[i]:
                if j in 씨집 and j not in 본것:
                    본것.add(j)
                    쌓.append(j)
        덩이들.append(더미)
    덩이들.sort(key=len, reverse=True)
    return 덩이들[:후보수]


def 덩이시험(폴더="data/물건", 배경폴더="data/그림", 물건수=100, 배움간격=30,
         시험간격=15, 색칸=4, 영역수=200, 굳힘=.25, 차지들=(1.0, .5, .25, .10, .05),
         후보수=3, 씨앗차수=3, 열림=True, 씨=1):
    """씨앗 덩이 국소화. 창·상자·NMS 없이 유도 부분그래프만 쓴다.

    **열림이 이 표의 전부다.**

    열림=False 는 찾을 물건을 이미 아는 판이다("이 사진에 X 있어?"). 대화
    그래프가 목표 노드를 고른 뒤 그 자리를 확인하는 자리이고, 이 엔진에서는
    질문에 목표가 딸려 오므로 정당한 설정이다. 다만 **씨앗을 목표 노드의
    조각으로 잡고 확인도 같은 조각으로 하므로 덩이가 목표 쪽으로 기울어진
    채 만들어진다.** 그 숫자를 목표 없이 잰 값과 나란히 놓으면 안 된다.

    열림=True 는 목표를 안 알려준다. 노드마다 자기 씨앗으로 덩이를 만들고
    가장 잘 맞는 (노드, 덩이) 를 고른다. 재보니 이쪽이 국소화를 아예 안 한
    전체 화폭(54.9%)보다 나쁘다(43.8%) — 틀린 노드 99개가 각자 자기한테
    제일 유리한 잘라내기를 얻는데 맞는 노드는 하나뿐이기 때문이다.

    그래서 이 국소화는 **열린 인식이 아니라 목표가 주어진 확인용**이다."""
    from skimage.segmentation import slic
    import time
    표 = 물건읽기(폴더)
    if not 표:
        print("%s 에 COIL 사진이 없다." % _길(폴더))
        return None
    번호들 = sorted(표)[:물건수]
    배움각 = list(range(0, 360, 배움간격))
    시험각 = [x for x in range(0, 360, 시험간격) if x not in 배움각]
    주머니 = _물건주머니(폴더, 번호들, 색칸, 영역수, True)
    배움 = [k for k in 주머니 if k[1] in 배움각]
    틀 = {h: _노드틀(주머니, 배움, 번호들, h, 굳힘) for h in (1, 2, 3)}
    배경들 = sorted(glob.glob(os.path.join(_길(배경폴더), "*.jpg")))
    낱 = 128 * 128 / 영역수
    찍기 = 100.0 / len(번호들)
    print("물건 %d개 · 시험 %d장/차지 · 씨앗 %d홉 · 확인 3홉 · 찍기 %.1f%%"
          % (len(번호들), len(번호들) * len(시험각), 씨앗차수, 찍기))
    print("** %s **" % ("목표를 안 알려준다 (열린 판)" if 열림
                        else "목표를 알려준다 (조건부). 열린 값과 나란히 놓지 말 것"))
    print()
    print("차지     정확도    초")
    print("-----  --------  -----")
    답 = {}
    for 차지 in 차지들:
        rs = np.random.RandomState(씨)
        맞음, 셈, 초 = 0, 0, 0.0
        for 번호 in 번호들:
            표적 = None if 열림 else 번호들.index(번호)
            for 각 in 시험각:
                길 = 표[번호].get(각)
                if 길 is None:
                    continue
                if 차지 >= 1.0:
                    난것 = 영역나누기(길, 영역수=영역수)
                    if 난것 is None:
                        continue
                    판, seg = 난것
                else:
                    a, m = 오려내기(길)
                    판 = 어수선하게(a, m, 배경들[rs.randint(0, len(배경들))], 차지, rs)
                    if 판 is None:
                        continue
                    seg = None
                t0 = time.perf_counter()
                if seg is None:
                    n = max(12, int(판.shape[0] * 판.shape[1] / 낱))
                    seg = slic(판, n_segments=n, compactness=10, start_label=0)
                색, 결, _ = 영역자질(판, seg)
                라벨 = 첫라벨(색, 결, 색칸)
                옆 = 이웃표(seg)
                최고 = None
                for _, 씨집 in _씨앗모으기(라벨, 옆, 틀, 씨앗차수, 표적).items():
                    for 덩 in _덩이나누기(씨집, 옆, 후보수):
                        if len(덩) < 4:
                            continue
                        결과 = _조각맞히기(_부분조각(라벨, 옆, 덩), 틀, 3)
                        if 최고 is None or 결과[0] > 최고[0]:
                            최고 = 결과
                초 += time.perf_counter() - t0
                맞음 += int(최고 is not None and 번호들[최고[1]] == 번호)
                셈 += 1
        답[차지] = 맞음 / max(셈, 1)
        print("%5s  %7.1f%%  %5.0f"
              % ("검은배경" if 차지 >= 1.0 else "%.0f%%" % (100 * 차지),
                 100 * 답[차지], 초))
    # 찍기보다 낮으면 성능이 아니라 버그다. 실제로 열별 노드 표를 잘못 만들어
    # 0.7% 가 나온 적이 있는데, 그 짝 숫자가 아니었으면 못 잡았다.
    최저 = min(답.values()) * 100
    if 최저 < 찍기:
        print()
        print("!! %.1f%% 는 찍기(%.1f%%)보다 낮다. 성능이 아니라 버그를 의심하라."
              % (최저, 찍기))
    return 답


def 어수선시험(폴더="data/물건", 배경폴더="data/그림", 물건수=100, 배움간격=30,
           시험간격=15, 색칸=4, 영역수=200, 굳힘=0.25, 홉들=(2, 3),
           차지들=(1.0, 0.5, 0.25, 0.10, 0.05), 씨=1):
    """깨끗한 판에서 익히고 어수선한 판에서 맞힌다. 차지가 작을수록 어수선하다."""
    from skimage.segmentation import slic
    표 = 물건읽기(폴더)
    if not 표:
        print("%s 에 COIL 사진이 없다." % _길(폴더))
        return None
    번호들 = sorted(표)[:물건수]
    배움각 = list(range(0, 360, 배움간격))
    시험각 = [x for x in range(0, 360, 시험간격) if x not in 배움각]
    주머니 = _물건주머니(폴더, 번호들, 색칸, 영역수, True)
    배움 = [k for k in 주머니 if k[1] in 배움각]
    틀 = {h: _노드틀(주머니, 배움, 번호들, h, 굳힘) for h in 홉들}

    배경들 = sorted(glob.glob(os.path.join(_길(배경폴더), "*.jpg")))
    낱 = 128 * 128 / 영역수          # 익힐 때의 영역 크기. 여기에 맞춘다
    print("물건 %d개. 노드 조각 평균 %s. 시험 %d장/차지."
          % (len(번호들),
             " / ".join("%d홉 %.0f개" % (h, 틀[h][2].mean()) for h in 홉들),
             len(번호들) * len(시험각)))
    print("배경 %d장. 물건은 원래 크기 그대로, 화폭만 키운다." % len(배경들))
    print()
    규칙들 = ("자카드", "담김", "드문담김")
    print("차지    물건/화폭  홉  " + "  ".join("%8s" % r for r in 규칙들)
          + "     (찍기 %.1f%%)" % (100.0 / len(번호들)))
    print("-----  ---------  --  " + "  ".join(["--------"] * len(규칙들)))

    답 = {}
    for 차지 in 차지들:
        rs = np.random.RandomState(씨)
        맞음 = {(h, r): 0 for h in 홉들 for r in 규칙들}
        셈 = 0
        for 번호 in 번호들:
            for 각 in 시험각:
                길 = 표[번호].get(각)
                if 길 is None:
                    continue
                if 차지 >= 1.0:
                    # 기준선은 원본을 그대로 쓴다. 오려서 다시 붙이면 COIL
                    # 배경의 어두운 잡음이 순수 검정이 되어 화소의 68%가
                    # 달라지고, SLIC 이 다르게 잘라 기준선이 100%에서
                    # 22%로 떨어졌다. 견줄 자리는 익힐 때와 똑같아야 한다.
                    난것 = 영역나누기(길, 영역수=영역수)
                    if 난것 is None:
                        continue
                    판, seg = 난것
                else:
                    a, m = 오려내기(길)
                    판 = 어수선하게(a, m, 배경들[rs.randint(0, len(배경들))],
                                 차지, rs)
                    if 판 is None:
                        continue
                    n = max(12, int(판.shape[0] * 판.shape[1] / 낱))
                    seg = slic(판, n_segments=n, compactness=10, start_label=0)
                색, 결, _ = 영역자질(판, seg)
                옆 = 이웃표(seg)
                라벨 = 첫라벨(색, 결, 색칸)
                if 차지 >= 1.0:
                    남, 옆 = 어두운데빼기(색, 결, 옆)
                    라벨 = [라벨[i] for i in 남]
                if len(라벨) < 4:
                    continue
                모두 = 그래프엔그램(라벨, 옆)
                for 홉 in 홉들:
                    칸, N, 노드크기, N무게, 무게 = 틀[홉]
                    조각 = 모두[홉 - 1]
                    v = np.zeros(len(칸), dtype=np.float32)
                    v[[칸[g] for g in 조각 if g in 칸]] = 1.0
                    겹 = N @ v
                    무게겹 = N무게 @ v
                    무게합 = np.asarray(N무게.sum(1)).ravel()
                    점수 = {
                        "자카드": 겹 / np.maximum(len(조각) + 노드크기 - 겹, 1e-9),
                        "담김": 겹 / np.maximum(노드크기, 1e-9),
                        "드문담김": 무게겹 / np.maximum(무게합, 1e-9),
                    }
                    for r in 규칙들:
                        맞음[(홉, r)] += int(
                            번호들[int(점수[r].argmax())] == 번호)
                셈 += 1
        답[차지] = {k: v / max(셈, 1) for k, v in 맞음.items()}
        for i, 홉 in enumerate(홉들):
            머리 = ("%5.2f  %9s  " % (차지, "검은배경" if 차지 >= 1.0
                                     else "%.0f%%" % (100 * 차지))
                   if i == 0 else " " * 18)
            print(머리 + "%2d  " % 홉
                  + "  ".join("%7.1f%%" % (100 * 답[차지][(홉, r)])
                              for r in 규칙들))
    print()
    print("차지 1.00 은 원래 COIL(검은 배경)이라 기준선이다. 아래로 갈수록")
    print("물건이 작고 배경이 넓다. 어디서 무너지는지가 이 표의 전부다.")
    return 답


# ───────────────────────── 자체검사 ─────────────────────────

def _자체검사():
    가로 = np.tile(np.linspace(0, 1, 64, dtype=np.float32), (64, 1))
    세로 = 가로.T.copy()
    무늬 = np.zeros((64, 64), np.float32)
    무늬[::4, :] = 1.0

    d = 서술자들(무늬)
    assert len(d) > 0, "무늬가 있는데 서술자가 하나도 안 나왔다"
    assert abs(float(np.linalg.norm(d[0])) - 1.0) < 1e-4       # 정규화돼 있다

    민 = np.full((64, 64), 0.5, np.float32)
    assert len(서술자들(민)) == 0, "밋밋한 면에서 단어가 나오면 안 된다"

    # 앞자리 자르기가 곧 거친 단어여야 한다 (힙스가 이 성질에 기댄다)
    코드 = 시각단어(d)
    for b in (8, 12, 16):
        assert np.array_equal(시각단어(d, b), 코드 >> (_최대비트 - b))

    # 조금 옮긴 그림은 대체로 같은 단어를 낸다 — 아니면 단어가 아니라 잡음이다
    옮김 = np.roll(무늬, 1, axis=1)
    ㄱ = set(시각단어(서술자들(무늬), 12).tolist())
    ㄴ = set(시각단어(서술자들(옮김), 12).tolist())
    겹침 = len(ㄱ & ㄴ) / max(1, len(ㄱ | ㄴ))
    assert 겹침 > 0.5, ("옮기면 딴 단어가 된다", 겹침)

    # 방향이 다르면 다른 단어여야 한다
    ㄷ = set(시각단어(서술자들(무늬.T.copy()), 12).tolist())
    assert len(ㄱ & ㄷ) / max(1, len(ㄱ | ㄷ)) < 0.5, "가로줄과 세로줄이 같은 단어다"

    print("그림 selfcheck ok (겹침 %.2f)" % 겹침)


if __name__ == "__main__":
    인자 = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--check" in sys.argv:
        _자체검사()
        sys.exit(0)
    if "--덩이" in sys.argv:
        수 = 100
        if "--물건" in sys.argv:
            수글 = sys.argv[sys.argv.index("--물건") + 1]
            수 = int(수글)
            인자 = [a for a in 인자 if a != 수글]
        차수 = 3
        if "--씨앗" in sys.argv:
            차수글 = sys.argv[sys.argv.index("--씨앗") + 1]
            차수 = int(차수글)
            인자 = [a for a in 인자 if a != 차수글]
        덩이시험(인자[0] if 인자 else "data/물건", 물건수=수, 씨앗차수=차수,
              열림=("--조건부" not in sys.argv))
        sys.exit(0)
    if "--표적스캔" in sys.argv:
        수, 차지 = 100, .25
        if "--물건" in sys.argv:
            수글 = sys.argv[sys.argv.index("--물건") + 1]
            수 = int(수글)
            인자 = [a for a in 인자 if a != 수글]
        if "--차지" in sys.argv:
            차지글 = sys.argv[sys.argv.index("--차지") + 1]
            차지 = float(차지글)
            인자 = [a for a in 인자 if a != 차지글]
        표적스캔시험(인자[0] if 인자 else "data/물건", 물건수=수, 차지=차지)
        sys.exit(0)
    if "--어수선" in sys.argv:
        수 = 100
        if "--물건" in sys.argv:
            수 = int(sys.argv[sys.argv.index("--물건") + 1])
            인자 = [a for a in 인자 if a != str(수)]
        어수선시험(인자[0] if 인자 else "data/물건", 물건수=수)
        sys.exit(0)
    if "--맞히기" in sys.argv:
        수 = 100
        if "--물건" in sys.argv:
            수 = int(sys.argv[sys.argv.index("--물건") + 1])
            인자 = [a for a in 인자 if a != str(수)]
        물건맞히기(인자[0] if 인자 else "data/물건", 물건수=수)
        sys.exit(0)
    if "--각도" in sys.argv:
        수 = 40
        if "--물건" in sys.argv:
            수 = int(sys.argv[sys.argv.index("--물건") + 1])
            인자 = [a for a in 인자 if a != str(수)]
        각도자(인자[0] if 인자 else "data/물건", 물건수=수)
        sys.exit(0)
    if "--흔들기" in sys.argv:
        장 = 300
        if "--장" in sys.argv:
            장 = int(sys.argv[sys.argv.index("--장") + 1])
            인자 = [a for a in 인자 if a != str(장)]
        흔들기(인자[0] if 인자 else "data/그림", 최대장=장)
        sys.exit(0)
    if "--관계" in sys.argv:
        장 = None
        if "--장" in sys.argv:
            장 = int(sys.argv[sys.argv.index("--장") + 1])
            인자 = [a for a in 인자 if a != str(장)]
        관계(인자[0] if 인자 else "data/그림", 최대장=장)
        sys.exit(0)
    if "--갈림" in sys.argv:
        장 = None
        if "--장" in sys.argv:
            장 = int(sys.argv[sys.argv.index("--장") + 1])
            인자 = [a for a in 인자 if a != str(장)]
        갈림(인자[0] if 인자 else "data/그림", 최대장=장)
        sys.exit(0)
    if "--힙스" in sys.argv:
        장 = None
        if "--장" in sys.argv:
            장 = int(sys.argv[sys.argv.index("--장") + 1])
            인자 = [a for a in 인자 if a != str(장)]
        힙스(인자[0] if 인자 else "data/그림", 최대장=장)
        sys.exit(0)
    print(__doc__)
