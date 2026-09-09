# -*- coding: utf-8 -*-
"""그림 층 — 사진을 국소 무늬로 쪼개고, 그 무늬의 어휘가 포화하는지 잰다.

    python vision.py --힙스              # 시각 어휘가 포화하나 (data/그림)
    python vision.py --갈림              # 비트를 얼마로 잡아야 하나
    python vision.py --관계              # 관계를 넣으면 분리도가 오르나 (RAG)
    python vision.py --흔들기            # 구조만 무너뜨렸을 때 관계가 알아채나
    python vision.py --각도              # 같은 물건을 몇 도까지 알아보나 (COIL-100)
    python vision.py --맞히기            # 시점 일부로 익히고 나머지로 맞힌다
    python vision.py --어수선            # 실제 사진 배경 위에서도 찾아내나
    python vision.py --표적스캔 --유도 --차지 .25  # 1홉 창 → 부분그래프 3홉 확인
    python vision.py --덩이 [--씨앗 3] [--조건부]  # 씨앗 덩이 국소화
                                       # 기본은 열린 판. --조건부 는 목표를 준다
    python vision.py --힙스 <폴더> --장 800
    python vision.py --check             # 자체 검사

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

_here = os.path.dirname(os.path.abspath(__file__))
_MAX_BITS = 32          # 코드는 늘 32비트로 만들고, 앞자리만 잘라 쓴다
_seed = 20260901


def _abs(p):
    return p if os.path.isabs(p) or os.path.exists(p) else os.path.join(_here, p)


# ───────────────────────── 보기 ─────────────────────────

def to_gray(path, max_side=256):
    """사진 하나를 회색 배열로. 크기를 맞추는 이유는 무늬의 크기를 맞추려는 것.

    원본 크기 그대로 보면 큰 사진의 무늬와 작은 사진의 무늬가 서로 다른
    단어가 된다 — 같은 것을 찍었는데 화소 수가 다르다는 이유로."""
    from PIL import Image
    im = Image.open(path)
    if getattr(im, "n_frames", 1) > 1:
        im.seek(0)                       # 움직이는 그림은 첫 장만
    im = im.convert("L")
    w, h = im.size
    scale = max_side / max(w, h)
    if scale < 1:
        im = im.resize((max(8, int(w * scale)), max(8, int(h * scale))), Image.BILINEAR)
    return np.asarray(im, dtype=np.float32) / 255.0


def _shrink(a, scale):
    if scale >= 1.0:
        return a
    from PIL import Image
    h, w = a.shape
    img = Image.fromarray((a * 255).astype(np.uint8))
    img = img.resize((max(8, int(w * scale)), max(8, int(h * scale))), Image.BILINEAR)
    return np.asarray(img, dtype=np.float32) / 255.0


def _gradient(a):
    """가장 단순한 방향 필터. V1 이 하는 일에서 학습이 필요 없는 부분이다."""
    gx = np.zeros_like(a)
    gy = np.zeros_like(a)
    gx[:, 1:-1] = a[:, 2:] - a[:, :-2]
    gy[1:-1, :] = a[2:, :] - a[:-2, :]
    return gx, gy


def descriptors(a, slot=4, slot_size=4, sparse=8, min_energy=0.02, dir_count=8):
    """사진 하나 -> 국소 무늬 서술자 여럿. (n, 칸*칸*방향수)

    조각 하나를 4x4 칸으로 나누고 칸마다 기울기 방향 히스토그램을 센다.
    사진 한 장을 벡터 하나로 만들지 않는 것이 요점이다 — 인코더.py 의
    조각내기 주석과 같은 이유다. 한 장에 문·사람·흉기가 다 들어 있는데
    평균을 내면 아무것도 아닌 것이 된다.

    밋밋한 조각(하늘, 흰 벽)은 버린다. 무늬가 없는 자리는 단어가 아니고,
    그냥 두면 가장 흔한 단어 하나가 통계를 다 먹는다."""
    P = slot * slot_size
    if a.shape[0] < P or a.shape[1] < P:
        return np.zeros((0, slot * slot * dir_count), np.float32)
    gx, gy = _gradient(a)
    size = np.hypot(gx, gy)
    empty = np.minimum((np.arctan2(gy, gx) % (2 * np.pi)) / (2 * np.pi) * dir_count, dir_count - 1)
    empty = empty.astype(np.int32)
    H, W = a.shape
    yielded = []
    for y in range(0, H - P + 1, sparse):
        for x in range(0, W - P + 1, sparse):
            m = size[y:y + P, x:x + P]
            if float(m.mean()) < min_energy:
                continue
            b = empty[y:y + P, x:x + P]
            v = np.zeros(slot * slot * dir_count, dtype=np.float32)
            for cy in range(slot):
                for cx in range(slot):
                    mm = m[cy * slot_size:(cy + 1) * slot_size, cx * slot_size:(cx + 1) * slot_size].ravel()
                    bb = b[cy * slot_size:(cy + 1) * slot_size, cx * slot_size:(cx + 1) * slot_size].ravel()
                    np.add.at(v, (cy * slot + cx) * dir_count + bb, mm)
            big = float(np.linalg.norm(v))
            if big < 1e-6:
                continue
            v /= big
            np.minimum(v, 0.2, out=v)     # 한 방향이 다 먹는 것을 막는다
            big = float(np.linalg.norm(v))
            yielded.append(v / big)
    if not yielded:
        return np.zeros((0, slot * slot * dir_count), np.float32)
    return np.asarray(yielded, dtype=np.float32)


def multi_size(path, scales=(1.0, 0.5, 0.25)):
    """같은 사진을 세 크기로 본다. 사람 눈도 한 크기로만 보지 않는다.

    작게 줄여서 같은 16화소 조각을 보면 더 넓은 것을 보는 셈이다 —
    큰 무늬(얼굴 윤곽)와 작은 무늬(털결)를 같은 코드로 다룰 수 있다."""
    a = to_gray(path)
    group = [descriptors(_shrink(a, scale)) for scale in scales]
    group = [x for x in group if len(x)]
    return np.concatenate(group) if group else np.zeros((0, 128), np.float32)


# ───────────────────────── 시각 단어 ─────────────────────────

_sess = {}


def _projection(dim):
    """고정 무작위 초평면. 씨가 박혀 있어서 언제 돌려도 같은 단어가 나온다.

    씨를 바꾸면 단어 이름이 전부 바뀐다. 인코더.py 가 MODEL 이름에 방식을
    적어 둔 것과 같은 이유로, 이 씨는 함부로 바꾸면 안 된다."""
    if dim not in _sess:
        _sess[dim] = np.random.RandomState(_seed).randn(dim, _MAX_BITS).astype(np.float32)
    return _sess[dim]


def visual_word(desc, bit=_MAX_BITS):
    """서술자 -> 정수 단어. 앞 비트만 잘라 쓰면 그대로 더 거친 단어가 된다.

    비트가 곧 어휘의 고움이다. 12비트면 4096칸, 20비트면 100만 칸.
    자료가 포화하는지 보려면 천장을 올려 가며 봐야 한다 — 천장에 닿아서
    안 느는 것과 자료가 다 떨어져서 안 느는 것은 완전히 다른 이야기다."""
    if not len(desc):
        return np.zeros(0, dtype=np.int64)
    sign = (desc @ _projection(desc.shape[1])) > 0
    pos = (1 << np.arange(_MAX_BITS, dtype=np.int64))[::-1]
    code = (sign * pos).sum(1)
    return code >> (_MAX_BITS - bit)


# ───────────────────────── 힙스 ─────────────────────────

def _fit_gradient(nmat, vmat):
    """log V = log K + b log N 을 최소제곱으로 맞춘다. -> b

    앞쪽은 K 가 지배해서 휘므로 뒤쪽 절반만 쓴다."""
    nmat = np.asarray(nmat, dtype=np.float64)
    vmat = np.asarray(vmat, dtype=np.float64)
    finite_place = (nmat > 0) & (vmat > 0)
    nmat, vmat = nmat[finite_place], vmat[finite_place]
    if len(nmat) < 3:
        return float("nan")
    half = len(nmat) // 2
    x, y = np.log(nmat[half:]), np.log(vmat[half:])
    if len(x) < 2 or x.std() < 1e-9:
        return float("nan")
    return float(np.polyfit(x, y, 1)[0])


def hips(folder="data/그림", bit_widths=(8, 12, 16, 20, 24, 28, 32), max_sheet=None, seed=1):
    """사진을 하나씩 보며 새 시각 단어가 얼마나 나오는지 센다.

    텍스트에서 이 저장소가 잰 것과 같은 것이다 — 법 코퍼스에서 b=0.342 였고,
    그래서 '개념 공간이 무한해서 못 덮는다' 가 뒤집혔다. 그림에도 같은 것을
    묻는다. b 가 1 에 가까우면 사진마다 새 무늬가 계속 나온다는 뜻이라
    이 방향은 거기서 끝난다. 확실히 작으면 시각 알파벳이 유한하다는 뜻이다."""
    folder = _abs(folder)
    files = sorted(f for f in glob.glob(os.path.join(folder, "*"))
                    if os.path.splitext(f)[1].lower()
                    in (".jpg", ".jpeg", ".png", ".gif", ".webp"))
    np.random.RandomState(seed).shuffle(files)      # 문서 순서가 남으면 주제가 뭉친다
    if max_sheet:
        files = files[:max_sheet]
    if not files:
        print("%s 에 사진이 없다. 먼저: python collectors/wiki.py --그림 --아무거나 300" % folder)
        return None

    seen = {b: set() for b in bit_widths}
    trace, nmat, sheets = [], 0, 0
    # 막판 새 단어 비율은 비트마다 따로 센다. 가장 고운 비트에서만 재면
    # 거의 아무것도 안 맞는 자리의 숫자라 늘 100%에 가깝게 나온다.
    final_fresh = {b: 0 for b in bit_widths}
    final_all = {b: 0 for b in bit_widths}
    final_start = int(len(files) * 0.9)
    for i, f in enumerate(files):
        try:
            desc = multi_size(f)
        except Exception:
            continue
        if not len(desc):
            continue
        sheets += 1
        nmat += len(desc)
        code = visual_word(desc)
        for b in bit_widths:
            coarse_ones = set((code >> (_MAX_BITS - b)).tolist())
            if i >= final_start:
                final_fresh[b] += len(coarse_ones - seen[b])
                final_all[b] += len(coarse_ones)
            seen[b] |= coarse_ones
        trace.append((sheets, nmat, {b: len(seen[b]) for b in bit_widths}))
        if sheets % 100 == 0:
            print("  %4d장  서술자 %8d  단어(16비트) %7d" % (sheets, nmat, len(seen[16])
                                                        if 16 in seen else -1))

    print()
    print("사진 %d장, 서술자 %s개" % (sheets, "{:,}".format(nmat)))
    print()
    print("비트   천장       어휘 V      V/천장    기울기 b   막판새단어")
    print("---- --------- ---------- --------- --------- ----------")
    result = {}
    for b in bit_widths:
        vmat = [x[2][b] for x in trace]
        tilt = _fit_gradient([x[1] for x in trace], vmat)
        ceiling = 1 << b
        result[b] = {"어휘": vmat[-1], "천장": ceiling, "b": tilt}
        final = (100.0 * final_fresh[b] / final_all[b]) if final_all[b] else float("nan")
        result[b]["막판"] = final
        table = "  천장" if vmat[-1] > 0.5 * ceiling else ""
        print("%4d %9d %10d %8.1f%% %8.3f %8.1f%%%s"
              % (b, ceiling, vmat[-1], 100.0 * vmat[-1] / ceiling, tilt, final, table))
    print()
    print("읽는 법: '천장' 은 어휘가 천장의 절반을 넘은 줄이다 — 자료가 아니라")
    print("비트 수가 막은 것이라 그 줄의 b 는 믿을 수 없다. 갈림이 고른 비트가")
    print("천장에 안 걸리는지 함께 본다. b 가 1 에 가까우면 무늬가 계속 새로")
    print("나온다는 뜻이고, 작으면 포화한다(법 코퍼스 글은 b=0.342 였다).")
    print("막판새단어 = 마지막 10%% 사진이 처음 보는 무늬를 몇 %% 가져왔나.")
    return {"장": sheets, "서술자": nmat, "비트별": result, "자취": trace}


# ───────────────────────── 갈림 ─────────────────────────

def _doc_table(folder):
    """파일 -> 어느 문서에서 왔나. 수집기가 남긴 목록에서 읽는다."""
    path = os.path.join(folder, "그림목록.jsonl")
    table = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    x = json.loads(line)
                except Exception:
                    continue
                table[x["파일"]] = x.get("문서", "")
    return table


def branch(folder="data/그림", bit_widths=(8, 12, 16, 20, 24, 28, 32),
        max_sheet=None, pair_count=4000, seed=1):
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
    folder = _abs(folder)
    doc_table = _doc_table(folder)
    files = sorted(f for f in glob.glob(os.path.join(folder, "*"))
                    if os.path.splitext(f)[1].lower()
                    in (".jpg", ".jpeg", ".png", ".gif", ".webp"))
    rs = np.random.RandomState(seed)
    rs.shuffle(files)
    if max_sheet:
        files = files[:max_sheet]

    word, doc = [], []
    for f in files:
        try:
            desc = multi_size(f)
        except Exception:
            continue
        if not len(desc):
            continue
        word.append(np.unique(visual_word(desc)))
        doc.append(doc_table.get(os.path.basename(f), ""))
    if len(word) < 4:
        print("사진이 너무 적다 (%d장)" % len(word))
        return None

    cluster = {}
    for i, d in enumerate(doc):
        if d:
            cluster.setdefault(d, []).append(i)
    same_pair = [(a, b) for v in cluster.values() if len(v) > 1
              for k, a in enumerate(v) for b in v[k + 1:]]
    if not same_pair:
        print("같은 문서에서 온 사진 짝이 없다. 그림목록.jsonl 이 있는지 본다.")
        return None
    rs.shuffle(same_pair)
    same_pair = same_pair[:pair_count]
    stranger_pair = []
    while len(stranger_pair) < len(same_pair):
        a, b = rs.randint(0, len(word)), rs.randint(0, len(word))
        if a != b and (not doc[a] or doc[a] != doc[b]):
            stranger_pair.append((a, b))

    print("사진 %d장, 같은 문서 짝 %d, 남남 짝 %d"
          % (len(word), len(same_pair), len(stranger_pair)))
    print()
    print("비트   같은문서     남남      배수   |  분리도   드문가중")
    print("---- --------- --------- -------- | -------- --------")
    result = {}
    for bit in bit_widths:
        split = _MAX_BITS - bit
        listing = [np.unique(w >> split) for w in word]
        vocab, n__sheet = np.unique(np.concatenate(listing), return_counts=True)
        weight = np.log(len(listing) / n__sheet.astype(np.float64))   # 드문 단어일수록 무겁다
        weight_total = [float(weight[np.searchsorted(vocab, x)].sum()) for x in listing]

        def _measure(pairs):
            bare, rare = [], []
            for a, b in pairs:
                A, B = listing[a], listing[b]
                cross = np.intersect1d(A, B, assume_unique=True)
                sum_ = len(A) + len(B) - len(cross)
                bare.append(len(cross) / max(1, sum_))
                cross_weight = float(weight[np.searchsorted(vocab, cross)].sum()) if len(cross) else 0.0
                bottom = weight_total[a] + weight_total[b] - cross_weight
                rare.append(cross_weight / bottom if bottom > 1e-12 else 0.0)
            return np.array(bare), np.array(rare)

        ㄱ, a_d = _measure(same_pair)
        ㄴ, b_d = _measure(stranger_pair)
        scale = float(np.mean(ㄱ)) / max(float(np.mean(ㄴ)), 1e-12)
        split_stdev = np.sqrt((np.var(ㄱ) + np.var(ㄴ)) / 2)
        separation = (np.mean(ㄱ) - np.mean(ㄴ)) / max(float(split_stdev), 1e-12)
        split_stdev_d = np.sqrt((np.var(a_d) + np.var(b_d)) / 2)
        separation_d = (np.mean(a_d) - np.mean(b_d)) / max(float(split_stdev_d), 1e-12)
        result[bit] = {"같은쪽": float(np.mean(ㄱ)), "남남": float(np.mean(ㄴ)),
                    "배수": scale, "분리도": float(separation), "분리도드": float(separation_d)}
        print("%4d %9.4f %9.4f %7.2f배 | %8.3f %8.3f"
              % (bit, np.mean(ㄱ), np.mean(ㄴ), scale, separation, separation_d))

    best = max(result, key=lambda b: result[b]["분리도"])
    best_d = max(result, key=lambda b: result[b]["분리도드"])
    print()
    print("분리도가 가장 큰 곳: 그냥 %d비트 %.3f / 드문가중 %d비트 %.3f"
          % (best, result[best]["분리도"], best_d, result[best_d]["분리도드"]))
    print()
    print("배수가 아니라 분리도로 고른다. 비트를 올리면 배수는 끝없이 오르는데")
    print("겹침 자체가 0 으로 가기 때문이다 — 아무것도 안 맞는 자리에서 비율만")
    print("커지는 것은 자가 아니다. 분리도는 격차를 흩어진 정도로 나눈다.")
    print("인코더.py 가 자모를 재던 그 자다(0.355 -> 0.519).")
    return result


# ───────────────────────── 관계 (RAG) ─────────────────────────
# 봉지로는 분리도가 0.407 에서 안 올랐다. 무늬 하나가 개도 고양이도 나무도
# 가리키기 때문이다. 관계가 본체라면 관계를 넣었을 때 그 숫자가 올라야 한다.
#
# 그래프 편집 거리(GED)가 이 자리의 고전인데 큰 그래프에서 계산이 터진다 —
# 근사 알고리즘이 그 분야 연구 주제 전체다. 대신 WL(Weisfeiler-Lehman)
# 라벨을 쓴다. 되풀이 0회는 관계를 안 보는 봉지고, n회는 n홉 이웃을 라벨에
# 접어 넣은 것이다. 같은 자료 같은 자로 0회와 n회를 견주면 관계의 몫만
# 딱 떨어져 나온다. 학습은 여전히 없다.

def _idx(key):
    """라벨 튜플 -> 정수 하나. 실행이 달라도 같은 값이 나와야 한다.

    처음엔 사전에 나온 순서대로 번호를 붙였다. 한 실행 안에서는 멀쩡한데
    캐시에 넣어 둔 라벨과 나중에 새로 뽑은 라벨이 서로 다른 번호를 받는다 —
    같은 사진을 다시 계산했더니 조각 수는 178개로 같은데 겹침이 0.082 였고,
    어수선함 기준선이 100%에서 25%로 떨어졌다.

    파이썬의 hash 는 정수 튜플에 대해 실행마다 같은 값을 준다(무작위화되는
    것은 문자열이다). 그래서 키에 문자열을 넣지 않는다."""
    return hash(key)


def segment_regions(path, region_count=None, max_side=320):
    """사진 -> (RGB 배열, 영역 라벨 배열). SLIC 초픽셀.

    영역수를 고정하지 않고 넓이로 정한다. 사진마다 크기가 다른데 영역 수를
    고정하면 영역 하나의 크기가 달라져서, 같은 무늬가 사진 크기에 따라 다른
    라벨을 받는다. 넓이/384 로 두면 영역 크기가 자료가 바뀌어도 같다 —
    위키 사진(320px)과 COIL(128px)을 같은 자로 재려면 이게 있어야 한다."""
    from PIL import Image
    from skimage.segmentation import slic
    im = Image.open(path)
    if getattr(im, "n_frames", 1) > 1:
        im.seek(0)
    im = im.convert("RGB")
    im.thumbnail((max_side, max_side))
    a = np.asarray(im, dtype=np.uint8)
    if min(a.shape[:2]) < 24:
        return None
    n = region_count or max(12, int(a.shape[0] * a.shape[1] / 384))
    return a, slic(a, n_segments=n, compactness=10, start_label=0)


def region_feats(a, seg):
    """영역마다 평균 색과 결(기울기 세기)과 크기. -> (색 n×3, 결 n, 크기 n)"""
    n = int(seg.max()) + 1
    seg_flat = seg.ravel()
    size = np.bincount(seg_flat, minlength=n).astype(np.float64)
    size = np.maximum(size, 1)
    color = np.stack([np.bincount(seg_flat, weights=a[:, :, c].ravel().astype(np.float64),
                               minlength=n) / size for c in range(3)], 1) / 255.0
    rnd = a.mean(2).astype(np.float32) / 255.0
    gx = np.zeros_like(rnd)
    gy = np.zeros_like(rnd)
    gx[:, 1:-1] = rnd[:, 2:] - rnd[:, :-2]
    gy[1:-1, :] = rnd[2:, :] - rnd[:-2, :]
    mag = np.bincount(seg_flat, weights=np.hypot(gx, gy).ravel().astype(np.float64),
                     minlength=n) / size
    return color, mag, size / size.sum()


def neighbor_table(seg):
    """맞닿은 영역끼리 잇는다. 이것이 RAG 의 엣지다 — 계산이지 학습이 아니다."""
    n = int(seg.max()) + 1
    pair = []
    for A, B in ((seg[:-1, :], seg[1:, :]), (seg[:, :-1], seg[:, 1:])):
        diff = A != B
        pair.append(np.stack([A[diff], B[diff]], 1))
    pair = np.unique(np.sort(np.concatenate(pair), axis=1), axis=0)
    neighbor = [[] for _ in range(n)]
    for x, y in pair:
        neighbor[x].append(int(y))
        neighbor[y].append(int(x))
    return neighbor


_strict = (0.05, 0.12)


def first_label(color, mag, color_slot=4):
    """영역 하나를 이름 하나로. 평균 색과 결을 칸에 넣어 자른다."""
    c = np.clip((color * color_slot).astype(np.int32), 0, color_slot - 1)
    t = np.digitize(mag, _strict)
    # 키에 문자열을 넣지 않는다. 앞의 0 은 영역 라벨임을 나타내는 표다.
    return [_idx((0, color_slot, int(c[i, 0]), int(c[i, 1]), int(c[i, 2]), int(t[i])))
            for i in range(len(mag))]


def graph_ngram(init, neighbor, max_n=3):
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
    group = [set(init)]
    if max_n >= 2:
        two = set()
        for i, side in enumerate(neighbor):
            for j in side:
                if i < j:
                    a, b = init[i], init[j]
                    two.add((a, b) if a <= b else (b, a))
        group.append(two)
    if max_n >= 3:
        three = set()
        for i, side in enumerate(neighbor):
            gv = [init[j] for j in side]
            for k in range(len(gv)):
                for l in range(k + 1, len(gv)):
                    a, c = gv[k], gv[l]
                    three.add((a, init[i], c) if a <= c else (c, init[i], a))
        group.append(three)
    return group


def relation(folder="data/그림", color_bins=(2, 3, 4), solution_re=3, max_sheet=None,
        pair_count=4000, seed=1):
    """관계를 넣으면 분리도가 오르는가. 갈림과 같은 짝, 같은 자를 쓴다."""
    folder = _abs(folder)
    doc_table = _doc_table(folder)
    files = sorted(f for f in glob.glob(os.path.join(folder, "*"))
                    if os.path.splitext(f)[1].lower()
                    in (".jpg", ".jpeg", ".png", ".gif", ".webp"))
    rs = np.random.RandomState(seed)
    rs.shuffle(files)
    if max_sheet:
        files = files[:max_sheet]

    stashed, doc = [], []
    node_count, edge_count = [], []
    for f in files:
        try:
            got = segment_regions(f)
            if got is None:
                continue
            a, seg = got
            color, mag, _ = region_feats(a, seg)
            neighbor = neighbor_table(seg)
        except Exception:
            continue
        stashed.append((color, mag, neighbor))
        doc.append(doc_table.get(os.path.basename(f), ""))
        node_count.append(len(mag))
        edge_count.append(sum(len(x) for x in neighbor) // 2)
    if len(stashed) < 4:
        print("사진이 너무 적다 (%d장)" % len(stashed))
        return None

    cluster = {}
    for i, d in enumerate(doc):
        if d:
            cluster.setdefault(d, []).append(i)
    same_pair = [(a, b) for v in cluster.values() if len(v) > 1
              for k, a in enumerate(v) for b in v[k + 1:]]
    if not same_pair:
        print("같은 문서에서 온 사진 짝이 없다.")
        return None
    rs.shuffle(same_pair)
    same_pair = same_pair[:pair_count]
    stranger_pair = []
    while len(stranger_pair) < len(same_pair):
        a, b = rs.randint(0, len(stashed)), rs.randint(0, len(stashed))
        if a != b and (not doc[a] or doc[a] != doc[b]):
            stranger_pair.append((a, b))

    print("사진 %d장  영역 중앙값 %d개  엣지 중앙값 %d개  같은문서 짝 %d"
          % (len(stashed), int(np.median(node_count)), int(np.median(edge_count)), len(same_pair)))
    print()
    print("색칸  n홉    같은문서     남남      분리도")
    print("---- ------ --------- --------- ---------")
    result = {}
    for color_slot in color_bins:
        groups = [graph_ngram(first_label(color, mag, color_slot), neighbor, solution_re)
                 for color, mag, neighbor in stashed]
        for t in range(solution_re):
            members = [x[t] for x in groups]

            def _measure(pairs):
                pt = []
                for a, b in pairs:
                    A, B = members[a], members[b]
                    ㅎ = len(A | B)
                    pt.append(len(A & B) / ㅎ if ㅎ else 0.0)
                return np.array(pt)

            ㄱ, ㄴ = _measure(same_pair), _measure(stranger_pair)
            scatter = float(np.sqrt((np.var(ㄱ) + np.var(ㄴ)) / 2))
            if scatter < 1e-9:          # 짝이 너무 적으면 분산이 0 이 되어 터진다
                min_ = float("nan")
            else:
                min_ = (ㄱ.mean() - ㄴ.mean()) / scatter
            result[(color_slot, t + 1)] = float(min_)
            print("%4d %6d %9.4f %9.4f %9.3f%s"
                  % (color_slot, t + 1, ㄱ.mean(), ㄴ.mean(), min_,
                     "   <- 봉지(관계 없음)" if t == 0 else ""))
        print()
    finite_only = {k: v for k, v in result.items() if v == v}
    if not finite_only:
        print("전부 분산 0 이다. 짝이 너무 적다.")
        return result
    best = max(finite_only, key=finite_only.get)
    bag_best = max((k for k in finite_only if k[1] == 1), key=finite_only.get)
    print("가장 높은 분리도: 색칸 %d, %d홉 -> %.3f"
          % (best[0], best[1], finite_only[best]))
    print("관계 없는 봉지 중 최고: 색칸 %d -> %.3f  (%+.0f%%)"
          % (bag_best[0], finite_only[bag_best],
             100 * (finite_only[best] / max(finite_only[bag_best], 1e-9) - 1)))
    print("견줄 자리: 시각단어 봉지는 0.407 이었다(--갈림, 16비트).")
    return result


# ───────────────────────── 흔들기 ─────────────────────────
# 관계가 값을 하는지를 '같은 문서' 라는 흐린 자 없이 재는 법.
#
# 타일을 잘라 섞으면 색 분포는 그대로인데 맞닿음만 무너진다. 글에서
# 낱말 순서를 섞는 것과 같다 — 봉지는 못 알아채고 n-gram 은 알아챈다.
# 관계가 정보를 나른다면 2·3홉의 겹침이 1홉보다 크게 떨어져야 한다.
# 안 떨어지면 관계는 이 층에서 나를 것이 없다.


def shuffle(a, slot=8, seed=0):
    """타일 칸x칸 으로 잘라 섞는다. 같은 화소가 그대로 다 남는다."""
    H, W = a.shape[:2]
    h, w = H // slot, W // slot
    if h < 4 or w < 4:
        return None
    tile = [a[y * h:(y + 1) * h, x * w:(x + 1) * w]
            for y in range(slot) for x in range(slot)]
    order = np.random.RandomState(seed).permutation(len(tile))
    new = np.zeros((h * slot, w * slot, a.shape[2]), dtype=a.dtype)
    for k, i in enumerate(order):
        y, x = divmod(k, slot)
        new[y * h:(y + 1) * h, x * w:(x + 1) * w] = tile[i]
    return new


def reshuffle_edge(neighbor, seed=0):
    """라벨은 그대로 두고 맞닿음만 아무렇게나 다시 잇는다.

    대조군이다. 타일을 섞으면 이음매에서 분할이 달라져 1홉 라벨도 변하고,
    그러면 2·3홉은 그 변화가 곱해져서 떨어진다 — 관계를 본 것이 아니다.
    라벨을 한 글자도 안 바꾸고 구조만 무작위로 만든 이 대조군이 그 몫을
    떼어낸다."""
    pair = [(i, j) for i, side in enumerate(neighbor) for j in side if i < j]
    rs = np.random.RandomState(seed)
    end = np.array([x for mate in pair for x in mate])
    rs.shuffle(end)
    new = [[] for _ in neighbor]
    for k in range(0, len(end) - 1, 2):
        a, b = int(end[k]), int(end[k + 1])
        if a != b:
            new[a].append(b)
            new[b].append(a)
    return new


def _ngram(a, color_slot, solution_re=3):
    from skimage.segmentation import slic
    n = max(12, int(a.shape[0] * a.shape[1] / 384))
    seg = slic(a, n_segments=n, compactness=10, start_label=0)
    color, mag, _ = region_feats(a, seg)
    return graph_ngram(first_label(color, mag, color_slot), neighbor_table(seg), solution_re)


def jitter(folder="data/그림", color_slot=3, slots=(2, 4, 8), max_sheet=300, seed=1):
    """구조만 무너뜨리고 겉모습은 남긴다. 관계의 몫만 떨어져 나온다."""
    folder = _abs(folder)
    files = sorted(f for f in glob.glob(os.path.join(folder, "*"))
                    if os.path.splitext(f)[1].lower()
                    in (".jpg", ".jpeg", ".png", ".gif", ".webp"))
    rs = np.random.RandomState(seed)
    rs.shuffle(files)
    files = files[:max_sheet]

    orig, reshuffled, shuffled = [], [], {g: [] for g in slots}
    for f in files:
        try:
            got = segment_regions(f)
            if got is None:
                continue
            a, seg = got
            color, mag, _ = region_feats(a, seg)
            label, side = first_label(color, mag, color_slot), neighbor_table(seg)
            ㄱ = graph_ngram(label, side)
            reshuffled.append(graph_ngram(label, reshuffle_edge(side)))
            mixed = {}
            for g in slots:
                b = shuffle(a, g)
                if b is None:
                    break
                mixed[g] = _ngram(b, color_slot)
            if len(mixed) != len(slots):
                reshuffled.pop()
                continue
        except Exception:
            if len(reshuffled) > len(orig):
                reshuffled.pop()
            continue
        orig.append(ㄱ)
        for g in slots:
            shuffled[g].append(mixed[g])

    if len(orig) < 10:
        print("사진이 너무 적다 (%d장)" % len(orig))
        return None

    def _overlap(A, B):
        ㅎ = len(A | B)
        return len(A & B) / ㅎ if ㅎ else 0.0

    # 남남 바닥: 아무 사진 둘. 이보다 안 떨어지면 아무 뜻도 없다
    mate = [(rs.randint(0, len(orig)), rs.randint(0, len(orig)))
          for _ in range(2000)]
    mate = [(a, b) for a, b in mate if a != b]

    print("사진 %d장, 색칸 %d. 타일을 섞어도 화소는 그대로다." % (len(orig), color_slot))
    print()
    print("n홉   원본↔남남  라벨같고구조무작위  "
          + "  ".join("%d×%d칸" % (g, g) for g in slots))
    print("---- ---------  ----------------  "
          + "  ".join(["-------"] * len(slots)))
    table = {}
    for t in range(3):
        floor = float(np.mean([_overlap(orig[a][t], orig[b][t]) for a, b in mate]))
        line = []
        for g in slots:
            line.append(float(np.mean([_overlap(orig[i][t], shuffled[g][i][t])
                                     for i in range(len(orig))])))
        re = float(np.mean([_overlap(orig[i][t], reshuffled[i][t])
                            for i in range(len(orig))]))
        table[t] = (floor, line, re)
        print("%3d  %9.4f  %16.4f  " % (t + 1, floor, re)
              + "  ".join("%7.4f" % x for x in line))
    print()
    print("구조 민감도 = 1 - 겹침. 관계가 정보를 나르면 홉이 늘수록 커야 한다.")
    print("n홉   " + "  ".join("%d×%d칸" % (g, g) for g in slots))
    for t in range(3):
        print("%3d   " % (t + 1)
              + "  ".join("%6.1f%%" % (100 * (1 - x)) for x in table[t][1]))
    print()
    print()
    print("읽는 법. '라벨같고구조무작위' 가 대조군이다 — 라벨을 한 글자도 안")
    print("바꾸고 맞닿음만 무작위로 만든 것이라, 1홉은 정확히 1.0 이어야 하고")
    print("2·3홉이 떨어지는 만큼이 순수한 관계의 몫이다. 그 값이 1 에 가까우면")
    print("관계는 아무것도 안 나른다. 타일 섞기는 거기에 분할 변화까지 얹힌다.")
    return table


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

_COUNT_WALL = (-3.0, -2.0, -1.0)
_RATIO_WALL = (0.15, 0.35)


def block_texture(rnd, block=8):
    """8x8 블록마다 DCT -> (가로, 세로, 고주파, 세기) 화소 지도 넉 장."""
    from scipy.fft import dctn
    H, W = rnd.shape
    h, w = H // block * block, W // block * block
    if h < block or w < block:
        z = np.zeros((H, W), np.float32)
        return z, z, z, z
    a = rnd[:h, :w].reshape(h // block, block, w // block, block).transpose(0, 2, 1, 3)
    E = dctn(a, axes=(2, 3), norm="ortho") ** 2
    AC = E.sum((-1, -2)) - E[:, :, 0, 0]
    width_ = E[:, :, 0, 1:].sum(-1) / np.maximum(AC, 1e-9)
    height_ = E[:, :, 1:, 0].sum(-1) / np.maximum(AC, 1e-9)
    high = E[:, :, 4:, 4:].sum((-1, -2)) / np.maximum(AC, 1e-9)
    tally = np.log10(AC + 1e-6)

    def expand(x):
        y = np.repeat(np.repeat(x, block, 0), block, 1)
        z = np.zeros((H, W), np.float32)
        z[:h, :w] = y
        if h < H:
            z[h:, :w] = y[-1:, :]
        if w < W:
            z[:, w:] = z[:, w - 1:w]
        return z

    return expand(width_), expand(height_), expand(high), expand(tally)


def texture_label(sess, seg, color, color_slot=4, mode="전부"):
    """색 + DCT 질감으로 영역 이름. 방식: 세기 / 방향 / 전부

    라벨을 곱게 할수록 1홉은 좋아지고 3홉은 무너진다(위키 분리도,
    현재 0.619->0.561 대 전부 0.734->0.409). 라벨 가짓수와 홉 차수가
    곱해져서 유효 어휘가 되기 때문이다 — 고움에 예산이 있고 둘이 나눠 쓴다."""
    rnd = sess.mean(2).astype(np.float32) / 255.0
    gv, three_, high, force = block_texture(rnd)
    n = int(seg.max()) + 1
    seg_flat = seg.ravel()
    num = np.maximum(np.bincount(seg_flat, minlength=n), 1)

    def norm(m):
        return np.bincount(seg_flat, weights=m.ravel().astype(np.float64), minlength=n) / num

    c = np.clip((color * color_slot).astype(np.int32), 0, color_slot - 1)
    t_force = np.digitize(norm(force), _COUNT_WALL)
    t_gv = np.digitize(norm(gv), _RATIO_WALL)
    t_three_ = np.digitize(norm(three_), _RATIO_WALL)
    t_high = np.digitize(norm(high), _RATIO_WALL)
    label = []
    for i in range(n):
        mem = (0, color_slot, int(c[i, 0]), int(c[i, 1]), int(c[i, 2]))
        if mode == "세기":
            tail = (int(t_force[i]),)
        elif mode == "방향":
            tail = (int(t_gv[i]), int(t_three_[i]))
        else:
            tail = (int(t_gv[i]), int(t_three_[i]), int(t_high[i]), int(t_force[i]))
        label.append(_idx(mem + tail))
    return label


# ───────────────────────── 물건 (COIL-100) ─────────────────────────
# 지금까지의 자는 '같은 문서' 였는데 그것은 같은 주제이지 같은 물건이 아니다.
# 관계가 구조를 나르는 것은 대조군으로 확인했지만(1.0 -> 0.37), 같은 문서
# 사진끼리는 구조를 안 나누므로 그 자로는 관계의 값이 안 보인다.
#
# COIL-100 은 물건 100개를 5도씩 돌려가며 72장씩 찍은 것이다. 짝이 완벽하고,
# 게다가 각도라는 눈금이 있다 — 같다/다르다가 아니라 "몇 도까지 버티나" 를
# 잴 수 있다. 라벨은 사람이 붙인 것이 아니라 턴테이블이 준 것이다.


def drop_dark(color, mag, neighbor, wall=0.12):
    """검은 배경 영역을 그래프에서 뺀다. -> (남은 자리, 새 이웃)

    COIL 은 배경이 검정이라 물건마다 똑같은 검은 영역이 잔뜩 생긴다.
    그대로 두면 다른 물건끼리도 배경 조각을 공유해 바닥이 부풀고, 물건이
    작을수록 배경이 신호를 덮는다. 뺀 자리의 이웃은 그냥 끊는다."""
    other = [i for i in range(len(mag)) if color[i].max() >= wall]
    new_num = {i: k for k, i in enumerate(other)}
    new_neighbor = [[new_num[j] for j in neighbor[i] if j in new_num] for i in other]
    return other, new_neighbor


def read_objects(folder="data/물건"):
    """-> {물건번호: {각도: 경로}}. 파일 이름이 obj12__85.png 꼴이다."""
    folder = _abs(folder)
    table = {}
    name_form = re.compile(r"obj(\d+)__(\d+)\.png$", re.I)
    for root, _, files in os.walk(folder):
        for f in files:
            m = name_form.search(f)
            if m:
                table.setdefault(int(m.group(1)), {})[int(m.group(2))] = \
                    os.path.join(root, f)
    return table


def angle_probe(folder="data/물건", object_count=40, color_slot=4, region_count=200, drop_background=True,
         angles=(5, 15, 30, 45, 60, 90, 180)):
    """같은 물건을 몇 도까지 알아보나. 다른 물건 바닥과 함께 본다.

    이것이 임계값을 정해 준다. 지금까지 임계값은 손으로 맞췄는데, 여기서는
    각도가 눈금이라 자료가 답한다."""
    table = read_objects(folder)
    if not table:
        print("%s 에 COIL 사진이 없다." % _abs(folder))
        return None
    nums = sorted(table)[:object_count]
    print("물건 %d개, 시점 %d개씩. n-gram 을 뽑는 중..."
          % (len(nums), len(table[nums[0]])))

    pocket = {}
    for idx in nums:
        for each, loc in sorted(table[idx].items()):
            got = segment_regions(loc, region_count=region_count)
            if got is None:
                continue
            a, seg = got
            color, mag, _ = region_feats(a, seg)
            side = neighbor_table(seg)
            label = first_label(color, mag, color_slot)
            if drop_background:
                other, side = drop_dark(color, mag, side)
                label = [label[i] for i in other]
            if len(label) < 4:
                continue
            pocket[(idx, each)] = graph_ngram(label, side)

    def _overlap(A, B):
        ㅎ = len(A | B)
        return len(A & B) / ㅎ if ㅎ else 0.0

    rs = np.random.RandomState(1)
    stranger = [(rs.choice(nums), rs.randint(0, 72) * 5,
             rs.choice(nums), rs.randint(0, 72) * 5) for _ in range(4000)]
    stranger = [x for x in stranger if x[0] != x[2]][:2000]

    print()
    print("Δ각도    " + "   ".join("%d홉" % (t + 1) for t in range(3)))
    print("------  " + "  ".join(["------"] * 3))
    result = {}
    for d in angles:
        mate = [(idx, each, idx, (each + d) % 360)
              for idx in nums for each in range(0, 360, 5)]
        line = []
        for t in range(3):
            value = [_overlap(pocket[(a, b)][t], pocket[(c, e)][t])
                  for a, b, c, e in mate
                  if (a, b) in pocket and (c, e) in pocket]
            line.append(float(np.mean(value)))
        result[d] = line
        print("%5d°  " % d + "  ".join("%6.4f" % x for x in line))
    floor = []
    for t in range(3):
        value = [_overlap(pocket[(a, b)][t], pocket[(c, e)][t])
              for a, b, c, e in stranger
              if (a, b) in pocket and (c, e) in pocket]
        floor.append(float(np.mean(value)))
    print("남남    " + "  ".join("%6.4f" % x for x in floor))
    print()
    print("분리도 (같은 물건 Δ각도 vs 다른 물건)")
    print("Δ각도    " + "   ".join("%d홉" % (t + 1) for t in range(3)))
    for d in angles:
        print("%5d°  " % d
              + "  ".join("%6.2f배" % (result[d][t] / max(floor[t], 1e-9))
                          for t in range(3)))
    print()
    print("읽는 법: 각도가 벌어져도 바닥보다 확실히 높으면 그 각도까지는")
    print("같은 물건으로 알아본다는 뜻이다. 홉이 늘수록 배수가 커지면")
    print("관계가 시점 변화를 견디는 쪽으로 값을 하는 것이다.")
    return result, floor


def _sparse_table(pocket, keys, hop):
    """n-gram 집합들 -> 희소 0/1 행렬. 집합 연산을 행렬 곱으로 바꾼다.

    시험 6,000장 x 학습 1,200장을 파이썬 집합으로 돌리면 720만 번이라
    안 끝난다. |A ∩ B| 는 0/1 행렬의 곱이고 합집합은 크기에서 빼면 된다."""
    from scipy import sparse
    slot = {}
    row, col = [], []
    for i, k in enumerate(keys):
        for g in pocket[k][hop]:
            c = slot.get(g)
            if c is None:
                c = len(slot)
                slot[g] = c
            row.append(i)
            col.append(c)
    X = sparse.csr_matrix((np.ones(len(row), dtype=np.float32), (row, col)),
                          shape=(len(keys), len(slot)))
    return X, slot


def _object_pockets(folder, nums, color_slot, region_count, drop_background):
    """n-gram 을 뽑아 캐시한다. 사진 7,200장에 4분이라 채점 규칙을 바꿔
    가며 재보려면 매번 다시 뽑을 수가 없다."""
    import pickle
    name = ".물건_%d_%d_%d_%d.pkl" % (len(nums), color_slot, region_count, int(drop_background))
    loc = os.path.join(_abs(folder), name)
    if os.path.exists(loc):
        with open(loc, "rb") as f:
            return pickle.load(f)
    table = read_objects(folder)
    pocket = {}
    for idx in nums:
        for each, file in sorted(table[idx].items()):
            got = segment_regions(file, region_count=region_count)
            if got is None:
                continue
            a, seg = got
            color, mag, _ = region_feats(a, seg)
            side = neighbor_table(seg)
            label = first_label(color, mag, color_slot)
            if drop_background:
                other, side = drop_dark(color, mag, side)
                label = [label[i] for i in other]
            if len(label) < 4:
                continue
            pocket[(idx, each)] = graph_ngram(label, side)
    with open(loc, "wb") as f:
        pickle.dump(pocket, f)
    return pocket


def guess_object(folder="data/물건", object_count=100, learning_interval=30, color_slot=4, region_count=200,
           drop_background=True, consensus_levels=(0.25, 0.5, 0.75)):
    """시점 일부로 물건을 익히고 나머지 시점으로 맞힌다. 진짜 정확도.

    두 가지를 견준다.
      1-NN   배운 시점을 통째로 외워 두고 가장 닮은 것을 찾는다 (기준선)
      노드   물건마다 노드 하나. 정의는 배운 시점 여러 장에 살아남은 n-gram
             의 교집합이다 — 한 시점에만 있는 조각은 우연이고, 여러 시점을
             견딘 조각이 그 물건이다.

    노드 쪽이 이 엔진이 하려는 것이다. 가중치를 고치는 것이 아니라 세고
    걸러내는 것이라, '물건 37번이 무엇이냐' 에 조각 목록으로 답할 수 있다."""
    table = read_objects(folder)
    if not table:
        print("%s 에 COIL 사진이 없다." % _abs(folder))
        return None
    nums = sorted(table)[:object_count]
    learning_each = list(range(0, 360, learning_interval))
    pocket = _object_pockets(folder, nums, color_slot, region_count, drop_background)

    learning = [k for k in pocket if k[1] in learning_each]
    test = [k for k in pocket if k[1] not in learning_each]
    print("물건 %d개. 배움 %d장(%d도마다), 시험 %d장. 찍기 정확도 %.1f%%"
          % (len(nums), len(learning), learning_interval, len(test), 100.0 / len(nums)))
    print()
    print("홉  굳힘   조각수    담김     자카드    코사인   |   1-NN")
    print("--- ----  ------  --------  --------  --------  |  -------")
    ans = {}
    from scipy import sparse
    for hop in range(3):
        X_scale, slot = _sparse_table(pocket, learning, hop)
        row, col = [], []
        for i, k in enumerate(test):
            for g in pocket[k][hop]:
                c = slot.get(g)
                if c is not None:
                    row.append(i)
                    col.append(c)
        X_hour = sparse.csr_matrix((np.ones(len(row), dtype=np.float32), (row, col)),
                               shape=(len(test), len(slot)))
        hour_size = np.array([len(pocket[k][hop]) for k in test], dtype=np.float32)
        true = np.array([k[0] for k in test])

        level = np.asarray((X_hour @ X_scale.T).todense())
        scale_size = np.asarray(X_scale.sum(1)).ravel()
        java = level / np.maximum(hour_size[:, None] + scale_size[None, :] - level, 1e-9)
        duty_NN = float(np.mean(np.array([learning[j][0] for j in java.argmax(1)]) == true))

        for consensus in consensus_levels:
            node_row, node_col = [], []
            for n, idx in enumerate(nums):
                pos = [i for i, k in enumerate(learning) if k[0] == idx]
                if not pos:
                    continue
                acc = np.asarray(X_scale[pos].sum(0)).ravel()
                alive_ones = np.where(acc >= max(2, consensus * len(pos)))[0]
                node_row += [n] * len(alive_ones)
                node_col += list(alive_ones)
            N = sparse.csr_matrix((np.ones(len(node_row), dtype=np.float32),
                                   (node_row, node_col)), shape=(len(nums), len(slot)))
            ㅋ = np.asarray(N.sum(1)).ravel()
            level_N = np.asarray((X_hour @ N.T).todense())
            score = {
                # 담김: 노드 정의 중 몇 %가 이 사진에 들어 있나.
                # 정의가 작은 노드가 유리해진다 — 물건이 늘수록 그런 노드가
                # 우연히 이길 기회가 늘어난다.
                "담김": level_N / np.maximum(ㅋ[None, :], 1e-9),
                "자카드": level_N / np.maximum(hour_size[:, None] + ㅋ[None, :] - level_N, 1e-9),
                "코사인": level_N / np.maximum(
                    np.sqrt(hour_size[:, None] * ㅋ[None, :]), 1e-9),
            }
            line = {name: float(np.mean(np.array([nums[j] for j in v.argmax(1)]) == true))
                  for name, v in score.items()}
            ans[(hop, consensus)] = (line, duty_NN, float(ㅋ.mean()))
            print("%2d  %.2f  %6.0f  %7.1f%%  %7.1f%%  %7.1f%%  | %7.1f%%"
                  % (hop + 1, consensus, ㅋ.mean(), 100 * line["담김"],
                     100 * line["자카드"], 100 * line["코사인"], 100 * duty_NN))
        print()
    print()
    print("1-NN 은 배운 시점 %d장을 통째로 들고 있고, 노드는 물건마다 조각"
          % len(learning))
    print("목록 하나뿐이다. 노드가 1-NN 에 가까우면 교집합이 물건을 붙든")
    print("것이고, 크게 지면 시점마다 따로 외워야 한다는 뜻이다.")
    return ans


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


def crop(path, wall=30):
    """COIL 사진에서 물건만. -> (RGB, 마스크). 가장 큰 덩어리만 남긴다."""
    from PIL import Image
    from scipy import ndimage
    a = np.asarray(Image.open(path).convert("RGB"), dtype=np.uint8)
    m = a.max(2) >= wall
    table, num = ndimage.label(m)
    if num > 1:
        size = ndimage.sum(m, table, range(1, num + 1))
        m = table == (int(np.argmax(size)) + 1)
    return a, m


def clutter(a, m, background_path, fill, rs):
    """물건을 실제 사진 위에 붙인다. 차지 = 물건이 화폭에서 차지하는 넓이 비율.

    물건은 원래 화소 크기 그대로 두고 화폭만 키운다. 물건을 줄이면 영역
    크기가 달라져 익힐 때와 다른 라벨이 나온다 — 어수선함이 아니라 크기
    때문에 진 것이 되어버린다."""
    from PIL import Image
    if not m.any():
        return None
    high, wide = a.shape[:2]
    # 원래 틀(128x128)을 그대로 옮긴다. 상자만큼 잘라내면 화폭 크기가 달라져
    # SLIC 격자가 익힐 때와 어긋나고, 물건 화소가 같은데도 영역 경계가
    # 달라진다 — 실제로 차지 1.00 기준선이 100% 에서 44% 로 떨어졌다.
    edge_len = max(high, wide, int(np.sqrt(int(m.sum()) / max(fill, 1e-6))))
    if background_path is None:
        sess = np.zeros((edge_len, edge_len, 3), dtype=np.uint8)
    else:
        b = Image.open(background_path).convert("RGB")
        b.thumbnail((edge_len * 3, edge_len * 3))
        sess = np.asarray(b, dtype=np.uint8)
        if sess.shape[0] < edge_len or sess.shape[1] < edge_len:
            sess = np.asarray(Image.fromarray(sess).resize((edge_len, edge_len)), dtype=np.uint8)
        y0 = rs.randint(0, sess.shape[0] - edge_len + 1)
        x0 = rs.randint(0, sess.shape[1] - edge_len + 1)
        sess = sess[y0:y0 + edge_len, x0:x0 + edge_len].copy()
    ty = rs.randint(0, edge_len - high + 1)
    tx = rs.randint(0, edge_len - wide + 1)
    chunk = sess[ty:ty + high, tx:tx + wide]
    chunk[m] = a[m]              # 검은 여백은 안 붙인다. 물건 화소만
    return sess


def _node_weight(N):
    """조각마다 무게. 여러 노드에 나오는 조각은 아무것도 안 가리킨다.

    어수선한 판에서는 배경 조각이 흔하고 물건 조각이 드물다. 흔한 것의
    무게를 낮추면 배경이 밀려난다. (위키 갈림에서 IDF 가 나빴던 것과
    반대인데, 거기서는 흔한 것이 신호였고 여기서는 잡음이다.)"""
    df = np.asarray(N.sum(0)).ravel()
    return np.log(1.0 + N.shape[0] / np.maximum(df, 1.0)).astype(np.float32)


def _NODE_TEMPLATE(pocket, learning, nums, hop, consensus):
    """배운 시점에서 물건마다 노드 하나. -> (칸, 노드행렬, 노드크기)

    홉은 사람이 부르는 이름(1·2·3홉)이고 그래프엔그램의 자리는 0부터다."""
    from scipy import sparse
    X_scale, slot = _sparse_table(pocket, learning, hop - 1)
    row, col = [], []
    for n, idx in enumerate(nums):
        pos = [i for i, k in enumerate(learning) if k[0] == idx]
        if not pos:
            continue
        acc = np.asarray(X_scale[pos].sum(0)).ravel()
        alive_ones = np.where(acc >= max(2, consensus * len(pos)))[0]
        row += [n] * len(alive_ones)
        col += list(alive_ones)
    N = sparse.csr_matrix((np.ones(len(row), dtype=np.float32), (row, col)),
                          shape=(len(nums), len(slot)))
    weight = _node_weight(N)
    return slot, N, np.asarray(N.sum(1)).ravel(), N.multiply(weight).tocsr(), weight


# ───────────────────────── 표적 조건부 스캔 ─────────────────────────
# 대화 그래프가 찾을 물건 노드를 이미 골랐다는 조건에서만 쓴다. 전체 화폭은
# SLIC 영역의 1홉 라벨과 위치만 보고, 관계(3홉)는 상위 후보 창에서만 읽는다.

def _region_center(seg):
    """SLIC 영역마다 중심 좌표. 1홉 창 스캔은 라벨과 이것만 쓴다."""
    n = int(seg.max()) + 1
    yy, xx = np.indices(seg.shape)
    seg_flat = seg.ravel()
    num = np.maximum(np.bincount(seg_flat, minlength=n), 1)
    return (np.bincount(seg_flat, weights=yy.ravel(), minlength=n) / num,
            np.bincount(seg_flat, weights=xx.ravel(), minlength=n) / num)


def _window_overlap(a, b):
    ay0, ay1, ax0, ax1 = a
    by0, by1, bx0, bx1 = b
    level = max(0, min(ay1, by1) - max(ay0, by0)) * max(0, min(ax1, bx1) - max(ax0, bx0))
    sum_ = (ay1 - ay0) * (ax1 - ax0) + (by1 - by0) * (bx1 - bx0) - level
    return level / max(sum_, 1)


def _target_window_cands(label, seg, template, target, window=128, sparse=16, cand_count=3):
    """목표 노드의 1홉 조각으로 고정 Bounding Box top-k를 찾는다.

    이 단계에는 이웃표나 2·3홉 조각이 없다. 창 안의 1홉 라벨 집합과 목표
    노드 1홉 정의의 자카드만 세며, 과도하게 겹친 창은 NMS로 하나만 남긴다.
    """
    slot, N, _, _, _ = template
    if not 0 <= target < N.shape[0]:
        return []
    goal_col = set(N.getrow(target).indices.tolist())
    if not goal_col:
        return []
    col = np.asarray([slot.get(g, -1) for g in label])
    yy, xx = _region_center(seg)
    h, w = seg.shape
    window_h, window_w = min(window, h), min(window, w)
    ys = list(range(0, max(h - window_h, 0) + 1, sparse))
    xs = list(range(0, max(w - window_w, 0) + 1, sparse))
    if ys[-1] != h - window_h:
        ys.append(h - window_h)
    if xs[-1] != w - window_w:
        xs.append(w - window_w)
    cand = []
    for y0 in ys:
        for x0 in xs:
            held = set(col[(yy >= y0) & (yy < y0 + window_h) &
                          (xx >= x0) & (xx < x0 + window_w)].tolist())
            held.discard(-1)
            level = len(held & goal_col)
            pt = level / max(len(held) + len(goal_col) - level, 1)
            cand.append((float(pt), (y0, y0 + window_h, x0, x0 + window_w)))
    cand.sort(key=lambda x: x[0], reverse=True)
    ans = []
    for pt, box in cand:
        if all(_window_overlap(box, head_box) < .5 for _, head_box in ans):
            ans.append((pt, box))
        if len(ans) >= cand_count:
            break
    return ans


def _box_regions_only(seg, label, neighbor, box):
    """상자 중심에 든 기존 SLIC 영역만 남긴 유도 부분그래프.

    후보 창에서 새 SLIC을 돌리지 않는다. 학습 때와 같은 장면 분할의 조각 이름을
    보존한 채, 상자 밖 영역과 그 관계만 끊는다.
    """
    y0, y1, x0, x1 = box
    yy, xx = _region_center(seg)
    other = [i for i in range(len(label)) if y0 <= yy[i] < y1 and x0 <= xx[i] < x1]
    new_num = {i: k for k, i in enumerate(other)}
    return ([label[i] for i in other],
            [[new_num[j] for j in neighbor[i] if j in new_num] for i in other])


def _guess_chunk(chunk, template, hop):
    """이미 만든 n-gram 집합을 기존 노드 정의와 자카드로 맞힌다."""
    slot, N, node_size, _, _ = template[hop]
    v = np.zeros(len(slot), dtype=np.float32)
    v[[slot[g] for g in chunk if g in slot]] = 1.0
    level = np.asarray(N @ v).ravel()
    score = level / np.maximum(len(chunk) + node_size - level, 1e-9)
    n = int(score.argmax())
    return float(score[n]), n


def target_scan_test(folder="data/물건", background_dir="data/그림", object_count=100,
            learning_interval=30, test_interval=15, color_slot=4, region_count=200, consensus=.25,
            fill=.25, cand_count=3, seed=1, derive=True):
    """표적 1홉 스캔 → 고정 상자 top-k → 유도 부분그래프 3홉 시험.

    회귀 채점에서는 각 시험 사진의 물건 번호를 대화 그래프가 고른 목표로 둔다.
    실제 대화에서는 그 목표 하나만 스캔하고, 목표가 없으면 먼저 되묻는다.
    """
    from skimage.segmentation import slic
    import time
    table = read_objects(folder)
    if not table:
        print("%s 에 COIL 사진이 없다." % _abs(folder))
        return None
    nums = sorted(table)[:object_count]
    learning_each = list(range(0, 360, learning_interval))
    test_each = [x for x in range(0, 360, test_interval) if x not in learning_each]
    pocket = _object_pockets(folder, nums, color_slot, region_count, True)
    learning = [k for k in pocket if k[1] in learning_each]
    template = {h: _NODE_TEMPLATE(pocket, learning, nums, h, consensus) for h in (1, 3)}
    backgrounds = sorted(glob.glob(os.path.join(_abs(background_dir), "*.jpg")))
    cell = 128 * 128 / region_count
    rs = np.random.RandomState(seed)
    matched, acc, scan_sec, check_sec = 0, 0, 0.0, 0.0
    for idx in nums:
        target_index = nums.index(idx)
        for each in test_each:
            loc = table[idx].get(each)
            if loc is None:
                continue
            a, m = crop(loc)
            sess = clutter(a, m, backgrounds[rs.randint(0, len(backgrounds))], fill, rs)
            n = max(12, int(sess.shape[0] * sess.shape[1] / cell))
            t0 = time.perf_counter()
            seg = slic(sess, n_segments=n, compactness=10, start_label=0)
            color, mag, _ = region_feats(sess, seg)
            label = first_label(color, mag, color_slot)
            cands = _target_window_cands(label, seg, template[1], target_index, cand_count=cand_count)
            scan_sec += time.perf_counter() - t0
            t0 = time.perf_counter()
            side = neighbor_table(seg)
            best = None
            for _, box in cands:
                part_label, part_side = _box_regions_only(seg, label, side, box)
                if len(part_label) < 4:
                    continue
                result = _guess_chunk(graph_ngram(part_label, part_side)[2], template, 3)
                if best is None or result[0] > best[0]:
                    best = result
            check_sec += time.perf_counter() - t0
            matched += int(best is not None and nums[best[1]] == idx)
            acc += 1
    ans = matched / max(acc, 1)
    print("표적 조건부 스캔. 물건 %d개 · 시험 %d장 · 차지 %.0f%% · 창 128px top-%d"
          % (len(nums), acc, 100 * fill, cand_count))
    print("  전체 화폭: SLIC+1홉 라벨만 | 후보 창: 기존 SLIC 유도 부분그래프+3홉 자카드")
    print("  최종 3홉 정확도: %.1f%% (%d/%d)" % (100 * ans, matched, acc))
    print("  시간: 스캔 %.1fs · 정밀검사 %.1fs · 합계 %.1fs"
          % (scan_sec, check_sec, scan_sec + check_sec))
    return {"정확도": ans, "장수": acc, "스캔초": scan_sec, "확인초": check_sec}


def _seed_blob(label, side, slot, goal_col, cand_count=3):
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
    matches = [slot.get(g, -1) in goal_col for g in label]
    seed_set = set(i for i, b in enumerate(matches) if b)
    if not seed_set:
        return []
    seen, blobs = set(), []
    for seed in seed_set:
        if seed in seen:
            continue
        pile, stack = [], [seed]
        seen.add(seed)
        while stack:
            i = stack.pop()
            pile.append(i)
            for j in side[i]:
                if j in seed_set and j not in seen:
                    seen.add(j)
                    stack.append(j)
        blobs.append(pile)
    blobs.sort(key=len, reverse=True)
    return blobs[:cand_count]


def _subchunk(label, side, other, hop=3):
    """영역 자리 목록 -> 유도 부분그래프의 n-gram 집합."""
    new = {i: k for k, i in enumerate(other)}
    return graph_ngram([label[i] for i in other],
                     [[new[j] for j in side[i] if j in new] for i in other])[hop - 1]


def _gather_seeds(label, side, template, degree, target=None):
    """차수 조각이 노드 정의에 있는 영역을 씨앗으로. -> {노드자리: 씨앗집합}

    표적을 주면 그 노드 하나만, 안 주면 모든 노드를 훑는다.

    차수를 올릴수록 순도가 오른다 — 배경 영역이 우연히 라벨 하나와 맞을
    확률은 꽤 되지만 이웃과 함께 쌍으로, 셋으로 맞을 확률은 훨씬 낮다.
    목표를 아는 판에서 재보니 1홉 83.9% / 2홉 87.2% / 3홉 90.1% 였고,
    1홉과 2홉을 합집합으로 쓰면 1홉 값으로 되돌아간다(83.9%) — 회수가
    아니라 순도가 이긴다."""
    slot, N = template[degree][0], template[degree][1]
    if target is None:
        co = N.tocoo()
        by_col = {}
        for r, c in zip(co.row.tolist(), co.col.tolist()):
            by_col.setdefault(c, []).append(r)
        to_view = None
    else:
        to_view = set(N.getrow(target).indices.tolist())
    collection = {}

    def pack_vals(col, positions):
        if to_view is not None:
            if col in to_view:
                collection.setdefault(target, set()).update(positions)
        else:
            for nd in by_col.get(col, ()):
                collection.setdefault(nd, set()).update(positions)

    if degree == 1:
        for i, g in enumerate(label):
            col = slot.get(g, -1)
            if col >= 0:
                pack_vals(col, (i,))
    elif degree == 2:
        for i, side_i in enumerate(side):
            for j in side_i:
                if i < j:
                    a, b = label[i], label[j]
                    col = slot.get((a, b) if a <= b else (b, a), -1)
                    if col >= 0:
                        pack_vals(col, (i, j))
    else:
        for i, side_i in enumerate(side):
            gv = [(j, label[j]) for j in side_i]
            for k in range(len(gv)):
                for l in range(k + 1, len(gv)):
                    (j1, a), (j2, c) = gv[k], gv[l]
                    col = slot.get((a, label[i], c) if a <= c else (c, label[i], a), -1)
                    if col >= 0:
                        pack_vals(col, (i, j1, j2))
    return collection


def _split_blobs(seed_set, side, cand_count=3):
    """씨앗을 연결요소로 나눈다. 큰 것부터 후보수 개."""
    seen, blobs = set(), []
    for seed in seed_set:
        if seed in seen:
            continue
        pile, stack = [], [seed]
        seen.add(seed)
        while stack:
            i = stack.pop()
            pile.append(i)
            for j in side[i]:
                if j in seed_set and j not in seen:
                    seen.add(j)
                    stack.append(j)
        blobs.append(pile)
    blobs.sort(key=len, reverse=True)
    return blobs[:cand_count]


def test_blob(folder="data/물건", background_dir="data/그림", object_count=100, learning_interval=30,
         test_interval=15, color_slot=4, region_count=200, consensus=.25, fills=(1.0, .5, .25, .10, .05),
         cand_count=3, seed_degree=3, open_=True, seed=1):
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
    table = read_objects(folder)
    if not table:
        print("%s 에 COIL 사진이 없다." % _abs(folder))
        return None
    nums = sorted(table)[:object_count]
    learning_each = list(range(0, 360, learning_interval))
    test_each = [x for x in range(0, 360, test_interval) if x not in learning_each]
    pocket = _object_pockets(folder, nums, color_slot, region_count, True)
    learning = [k for k in pocket if k[1] in learning_each]
    template = {h: _NODE_TEMPLATE(pocket, learning, nums, h, consensus) for h in (1, 2, 3)}
    backgrounds = sorted(glob.glob(os.path.join(_abs(background_dir), "*.jpg")))
    cell = 128 * 128 / region_count
    show = 100.0 / len(nums)
    print("물건 %d개 · 시험 %d장/차지 · 씨앗 %d홉 · 확인 3홉 · 찍기 %.1f%%"
          % (len(nums), len(nums) * len(test_each), seed_degree, show))
    print("** %s **" % ("목표를 안 알려준다 (열린 판)" if open_
                        else "목표를 알려준다 (조건부). 열린 값과 나란히 놓지 말 것"))
    print()
    print("차지     정확도    초")
    print("-----  --------  -----")
    ans = {}
    for fill in fills:
        rs = np.random.RandomState(seed)
        matched, acc, sec = 0, 0, 0.0
        for idx in nums:
            target = None if open_ else nums.index(idx)
            for each in test_each:
                loc = table[idx].get(each)
                if loc is None:
                    continue
                if fill >= 1.0:
                    got = segment_regions(loc, region_count=region_count)
                    if got is None:
                        continue
                    sess, seg = got
                else:
                    a, m = crop(loc)
                    sess = clutter(a, m, backgrounds[rs.randint(0, len(backgrounds))], fill, rs)
                    if sess is None:
                        continue
                    seg = None
                t0 = time.perf_counter()
                if seg is None:
                    n = max(12, int(sess.shape[0] * sess.shape[1] / cell))
                    seg = slic(sess, n_segments=n, compactness=10, start_label=0)
                color, mag, _ = region_feats(sess, seg)
                label = first_label(color, mag, color_slot)
                side = neighbor_table(seg)
                best = None
                for _, seed_set in _gather_seeds(label, side, template, seed_degree, target).items():
                    for blob in _split_blobs(seed_set, side, cand_count):
                        if len(blob) < 4:
                            continue
                        result = _guess_chunk(_subchunk(label, side, blob), template, 3)
                        if best is None or result[0] > best[0]:
                            best = result
                sec += time.perf_counter() - t0
                matched += int(best is not None and nums[best[1]] == idx)
                acc += 1
        ans[fill] = matched / max(acc, 1)
        print("%5s  %7.1f%%  %5.0f"
              % ("검은배경" if fill >= 1.0 else "%.0f%%" % (100 * fill),
                 100 * ans[fill], sec))
    # 찍기보다 낮으면 성능이 아니라 버그다. 실제로 열별 노드 표를 잘못 만들어
    # 0.7% 가 나온 적이 있는데, 그 짝 숫자가 아니었으면 못 잡았다.
    worst = min(ans.values()) * 100
    if worst < show:
        print()
        print("!! %.1f%% 는 찍기(%.1f%%)보다 낮다. 성능이 아니라 버그를 의심하라."
              % (worst, show))
    return ans


def clutter_test(folder="data/물건", background_dir="data/그림", object_count=100, learning_interval=30,
           test_interval=15, color_slot=4, region_count=200, consensus=0.25, hops=(2, 3),
           fills=(1.0, 0.5, 0.25, 0.10, 0.05), seed=1):
    """깨끗한 판에서 익히고 어수선한 판에서 맞힌다. 차지가 작을수록 어수선하다."""
    from skimage.segmentation import slic
    table = read_objects(folder)
    if not table:
        print("%s 에 COIL 사진이 없다." % _abs(folder))
        return None
    nums = sorted(table)[:object_count]
    learning_each = list(range(0, 360, learning_interval))
    test_each = [x for x in range(0, 360, test_interval) if x not in learning_each]
    pocket = _object_pockets(folder, nums, color_slot, region_count, True)
    learning = [k for k in pocket if k[1] in learning_each]
    template = {h: _NODE_TEMPLATE(pocket, learning, nums, h, consensus) for h in hops}

    backgrounds = sorted(glob.glob(os.path.join(_abs(background_dir), "*.jpg")))
    cell = 128 * 128 / region_count          # 익힐 때의 영역 크기. 여기에 맞춘다
    print("물건 %d개. 노드 조각 평균 %s. 시험 %d장/차지."
          % (len(nums),
             " / ".join("%d홉 %.0f개" % (h, template[h][2].mean()) for h in hops),
             len(nums) * len(test_each)))
    print("배경 %d장. 물건은 원래 크기 그대로, 화폭만 키운다." % len(backgrounds))
    print()
    rules = ("자카드", "담김", "드문담김")
    print("차지    물건/화폭  홉  " + "  ".join("%8s" % r for r in rules)
          + "     (찍기 %.1f%%)" % (100.0 / len(nums)))
    print("-----  ---------  --  " + "  ".join(["--------"] * len(rules)))

    ans = {}
    for fill in fills:
        rs = np.random.RandomState(seed)
        matched = {(h, r): 0 for h in hops for r in rules}
        acc = 0
        for idx in nums:
            for each in test_each:
                loc = table[idx].get(each)
                if loc is None:
                    continue
                if fill >= 1.0:
                    # 기준선은 원본을 그대로 쓴다. 오려서 다시 붙이면 COIL
                    # 배경의 어두운 잡음이 순수 검정이 되어 화소의 68%가
                    # 달라지고, SLIC 이 다르게 잘라 기준선이 100%에서
                    # 22%로 떨어졌다. 견줄 자리는 익힐 때와 똑같아야 한다.
                    got = segment_regions(loc, region_count=region_count)
                    if got is None:
                        continue
                    sess, seg = got
                else:
                    a, m = crop(loc)
                    sess = clutter(a, m, backgrounds[rs.randint(0, len(backgrounds))],
                                 fill, rs)
                    if sess is None:
                        continue
                    n = max(12, int(sess.shape[0] * sess.shape[1] / cell))
                    seg = slic(sess, n_segments=n, compactness=10, start_label=0)
                color, mag, _ = region_feats(sess, seg)
                side = neighbor_table(seg)
                label = first_label(color, mag, color_slot)
                if fill >= 1.0:
                    other, side = drop_dark(color, mag, side)
                    label = [label[i] for i in other]
                if len(label) < 4:
                    continue
                every = graph_ngram(label, side)
                for hop in hops:
                    slot, N, node_size, N_weight, weight = template[hop]
                    chunk = every[hop - 1]
                    v = np.zeros(len(slot), dtype=np.float32)
                    v[[slot[g] for g in chunk if g in slot]] = 1.0
                    level = N @ v
                    depth_weight = N_weight @ v
                    weight_total = np.asarray(N_weight.sum(1)).ravel()
                    score = {
                        "자카드": level / np.maximum(len(chunk) + node_size - level, 1e-9),
                        "담김": level / np.maximum(node_size, 1e-9),
                        "드문담김": depth_weight / np.maximum(weight_total, 1e-9),
                    }
                    for r in rules:
                        matched[(hop, r)] += int(
                            nums[int(score[r].argmax())] == idx)
                acc += 1
        ans[fill] = {k: v / max(acc, 1) for k, v in matched.items()}
        for i, hop in enumerate(hops):
            head = ("%5.2f  %9s  " % (fill, "검은배경" if fill >= 1.0
                                     else "%.0f%%" % (100 * fill))
                   if i == 0 else " " * 18)
            print(head + "%2d  " % hop
                  + "  ".join("%7.1f%%" % (100 * ans[fill][(hop, r)])
                              for r in rules))
    print()
    print("차지 1.00 은 원래 COIL(검은 배경)이라 기준선이다. 아래로 갈수록")
    print("물건이 작고 배경이 넓다. 어디서 무너지는지가 이 표의 전부다.")
    return ans


# ───────────────────────── 자체검사 ─────────────────────────

def _selfcheck():
    width_ = np.tile(np.linspace(0, 1, 64, dtype=np.float32), (64, 1))
    height_ = width_.T.copy()
    pattern = np.zeros((64, 64), np.float32)
    pattern[::4, :] = 1.0

    d = descriptors(pattern)
    assert len(d) > 0, "무늬가 있는데 서술자가 하나도 안 나왔다"
    assert abs(float(np.linalg.norm(d[0])) - 1.0) < 1e-4       # 정규화돼 있다

    plain = np.full((64, 64), 0.5, np.float32)
    assert len(descriptors(plain)) == 0, "밋밋한 면에서 단어가 나오면 안 된다"

    # 앞자리 자르기가 곧 거친 단어여야 한다 (힙스가 이 성질에 기댄다)
    code = visual_word(d)
    for b in (8, 12, 16):
        assert np.array_equal(visual_word(d, b), code >> (_MAX_BITS - b))

    # 조금 옮긴 그림은 대체로 같은 단어를 낸다 — 아니면 단어가 아니라 잡음이다
    moved = np.roll(pattern, 1, axis=1)
    ㄱ = set(visual_word(descriptors(pattern), 12).tolist())
    ㄴ = set(visual_word(descriptors(moved), 12).tolist())
    overlap = len(ㄱ & ㄴ) / max(1, len(ㄱ | ㄴ))
    assert overlap > 0.5, ("옮기면 딴 단어가 된다", overlap)

    # 방향이 다르면 다른 단어여야 한다
    ㄷ = set(visual_word(descriptors(pattern.T.copy()), 12).tolist())
    assert len(ㄱ & ㄷ) / max(1, len(ㄱ | ㄷ)) < 0.5, "가로줄과 세로줄이 같은 단어다"

    print("그림 selfcheck ok (겹침 %.2f)" % overlap)


if __name__ == "__main__":
    argv = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--check" in sys.argv:
        _selfcheck()
        sys.exit(0)
    if "--덩이" in sys.argv:
        num = 100
        if "--물건" in sys.argv:
            count_text = sys.argv[sys.argv.index("--물건") + 1]
            num = int(count_text)
            argv = [a for a in argv if a != count_text]
        degree = 3
        if "--씨앗" in sys.argv:
            degree_text = sys.argv[sys.argv.index("--씨앗") + 1]
            degree = int(degree_text)
            argv = [a for a in argv if a != degree_text]
        test_blob(argv[0] if argv else "data/물건", object_count=num, seed_degree=degree,
              open_=("--조건부" not in sys.argv))
        sys.exit(0)
    if "--표적스캔" in sys.argv:
        num, fill = 100, .25
        if "--물건" in sys.argv:
            count_text = sys.argv[sys.argv.index("--물건") + 1]
            num = int(count_text)
            argv = [a for a in argv if a != count_text]
        if "--차지" in sys.argv:
            fill_text = sys.argv[sys.argv.index("--차지") + 1]
            fill = float(fill_text)
            argv = [a for a in argv if a != fill_text]
        target_scan_test(argv[0] if argv else "data/물건", object_count=num, fill=fill)
        sys.exit(0)
    if "--어수선" in sys.argv:
        num = 100
        if "--물건" in sys.argv:
            num = int(sys.argv[sys.argv.index("--물건") + 1])
            argv = [a for a in argv if a != str(num)]
        clutter_test(argv[0] if argv else "data/물건", object_count=num)
        sys.exit(0)
    if "--맞히기" in sys.argv:
        num = 100
        if "--물건" in sys.argv:
            num = int(sys.argv[sys.argv.index("--물건") + 1])
            argv = [a for a in argv if a != str(num)]
        guess_object(argv[0] if argv else "data/물건", object_count=num)
        sys.exit(0)
    if "--각도" in sys.argv:
        num = 40
        if "--물건" in sys.argv:
            num = int(sys.argv[sys.argv.index("--물건") + 1])
            argv = [a for a in argv if a != str(num)]
        angle_probe(argv[0] if argv else "data/물건", object_count=num)
        sys.exit(0)
    if "--흔들기" in sys.argv:
        sheet = 300
        if "--장" in sys.argv:
            sheet = int(sys.argv[sys.argv.index("--장") + 1])
            argv = [a for a in argv if a != str(sheet)]
        jitter(argv[0] if argv else "data/그림", max_sheet=sheet)
        sys.exit(0)
    if "--관계" in sys.argv:
        sheet = None
        if "--장" in sys.argv:
            sheet = int(sys.argv[sys.argv.index("--장") + 1])
            argv = [a for a in argv if a != str(sheet)]
        relation(argv[0] if argv else "data/그림", max_sheet=sheet)
        sys.exit(0)
    if "--갈림" in sys.argv:
        sheet = None
        if "--장" in sys.argv:
            sheet = int(sys.argv[sys.argv.index("--장") + 1])
            argv = [a for a in argv if a != str(sheet)]
        branch(argv[0] if argv else "data/그림", max_sheet=sheet)
        sys.exit(0)
    if "--힙스" in sys.argv:
        sheet = None
        if "--장" in sys.argv:
            sheet = int(sys.argv[sys.argv.index("--장") + 1])
            argv = [a for a in argv if a != str(sheet)]
        hips(argv[0] if argv else "data/그림", max_sheet=sheet)
        sys.exit(0)
    print(__doc__)
