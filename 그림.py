# -*- coding: utf-8 -*-
"""그림 층 — 사진을 국소 무늬로 쪼개고, 그 무늬의 어휘가 포화하는지 잰다.

    python 그림.py --힙스              # 시각 어휘가 포화하나 (자료/그림)
    python 그림.py --갈림              # 비트를 얼마로 잡아야 하나
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
import glob, json, os, sys
import numpy as np

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


def 힙스(폴더="자료/그림", 비트들=(8, 12, 16, 20, 24, 28, 32), 최대장=None, 씨=1):
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
        print("%s 에 사진이 없다. 먼저: python 수집/위키.py --그림 --아무거나 300" % 폴더)
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


def 갈림(폴더="자료/그림", 비트들=(8, 12, 16, 20, 24, 28, 32),
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
    if "--갈림" in sys.argv:
        장 = None
        if "--장" in sys.argv:
            장 = int(sys.argv[sys.argv.index("--장") + 1])
            인자 = [a for a in 인자 if a != str(장)]
        갈림(인자[0] if 인자 else "자료/그림", 최대장=장)
        sys.exit(0)
    if "--힙스" in sys.argv:
        장 = None
        if "--장" in sys.argv:
            장 = int(sys.argv[sys.argv.index("--장") + 1])
            인자 = [a for a in 인자 if a != str(장)]
        힙스(인자[0] if 인자 else "자료/그림", 최대장=장)
        sys.exit(0)
    print(__doc__)
