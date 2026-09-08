# -*- coding: utf-8 -*-
"""라우팅 색인을 평평한 한 파일로 묶는다. numpy 말고는 아무것도 안 쓴다.

    python kgbin.py --묶기                      # .색인.kgbin 을 만든다
    python kgbin.py --묶기 --값 uint4 --되집기 없음
    python kgbin.py --보기                      # 무엇이 얼마나 들었나
    python kgbin.py --자가검사

    KG_INDEX=npz python ...        # 묶어 둔 bin 을 무시하고 npz 로 돈다

왜 만드나. 작은 기기에 얹으려면 두 가지가 걸린다.

    .색인벡터.npz   17.1 MB     zip 이라 풀어서 올려야 한다 (98 ms)
    .kg 원문 188개   0.9 MB     이건 애초에 작다

지식 원문은 이미 1 MB 가 안 돼서 묶어 봐야 아낄 것이 없다. 무게는 전부
색인에 있고, 그 속은 이렇다.

    값 float32   10.98 MB  65.9%
    열 int16      5.49 MB  32.9%
    나머지         0.20 MB   1.2%

그래서 이 파일이 건드리는 것은 값 하나다. 값의 범위가 -0.037 ~ 0.07 이고
고유값이 1,000개뿐이라 눌러도 되는지 재봤다(물음 400개, 문자 인코더).

    원래 float32      제자리 144 / 400
    [검산] 값 전부 0  제자리   0      <- 실험이 실패할 수 있는지부터 봤다
    uint8             제자리 146   (+2)
    uint6             제자리 142   (-2)
    uint4             제자리 147   (+3)

uint4 까지 손실이 없다(±3 은 잡음). 처음 잰 값은 손실 0 이었는데 검산해
보니 배열을 하나도 안 건드리고 있었다. 그래서 검산줄을 자가검사에 박아
뒀다 — 값을 0 으로 만들면 제자리가 0 이 되어야 한다.

눌러 두고 언제 펴나. 점수 낼 때만 그 그래프 것만 편다(`engine._성긴점수`).
통째로 펴면 파일만 작아지고 메모리는 그대로다.

되집기 벡터(rv·rc)는 색인의 46% 인데 짧은 물음을 거꾸로 잴 때만 쓴다.
`--되집기 없음` 으로 빼면 절반이 더 준다. 그만큼 짧은 물음이 약해지므로
기기가 정말 작을 때만 쓰는 선택지다.

파일 꼴. 앞에 JSON 머리표가 있고 뒤에 원시 배열이 8바이트 정렬로 이어
붙는다. 배열마다 (자리, 개수, 형) 이 머리표에 적혀 있어 mmap 한 장을
잘라 쓰면 된다 — 풀 것도 없고 pickle 도 안 쓴다.

머리표에 그래프마다 예시 해시를 같이 넣는다. 그것이 없으면 그래프를
고쳐도 파일은 그대로라, 낡은 bin 이 조용히 옛 지식을 내놓는다. 해시가
어긋나면 engine 이 스스로 npz 길로 물러난다.

무엇을 벌고 무엇을 잃나 (물음 400개, 문자 인코더):

                 npz        bin(uint8)
    파일          17.73 MB    8.75 MB      되집기 빼면 4.64 MB
    색인 올리기      291 ms      53 ms      zip 을 안 푼다
    물음 400개       3.1 s       3.8 s      +23%, 잴 때마다 펴는 값
    제자리           348         349
    답함             392         393
    밖 거절         27/27       27/27
    최대 메모리      144 MB      148 MB      <- 안 준다

메모리가 안 주는 것을 감추면 안 된다. 색인 9 MB 를 아껴도 이 일감의 최대
메모리는 그래프 본문과 파이썬 자체가 잡고 있어 표가 안 난다. bin 이 버는
것은 **파일 크기와 켜는 시간** 둘이고, 값은 잴 때마다 펴므로 점수 내는
일은 23% 느려진다. 늘 켜 두는 서버라면 npz 가 낫고, 껐다 켜는 작은
기기라면 bin 이 낫다. 그래서 고르게 두었다.
"""
import json
import os
import sys

_매직 = b"KGBIN\x00"
형식버전 = 1
_형코드 = {"float32": "f4", "uint8": "u1", "uint16": "u2", "int16": "i2",
          "int32": "i4", "int64": "i8"}


def _누르기(v, 형식):
    """실수 배열 -> (누른 배열, 곱, 뺄것, 개수). 되돌리면 q*곱 - 뺄것 이다.

    uint4 는 한 바이트에 둘씩 접는다. 안 접으면 uint8 과 파일 크기가 똑같아
    (8.65 MB) 고를 이유가 없는 선택지가 된다 — 실제로 처음엔 그랬다."""
    import numpy as np
    v = np.asarray(v, dtype=np.float32)
    if 형식 == "float32" or v.size == 0:
        return v.astype(np.float32), 1.0, 0.0, int(v.size)
    비트 = {"uint8": 8, "uint4": 4}[형식]
    눈 = (1 << 비트) - 1
    폭 = float(np.abs(v).max()) or 1.0
    q = np.clip(np.round((v + 폭) / (2 * 폭) * 눈), 0, 눈).astype(np.uint8)
    개수 = int(q.size)
    if 비트 == 4:
        if 개수 % 2:
            q = np.append(q, np.uint8(0))
        q = (q[0::2] << 4) | q[1::2]
    return q, (2 * 폭) / 눈, 폭, 개수


def 펴기(칸):
    """(누른 배열, 곱, 뺄것[, 개수]) -> float32. 안 눌린 것은 그대로."""
    import numpy as np
    if not isinstance(칸, tuple):
        return 칸
    q, 곱, 뺄것 = 칸[0], 칸[1], 칸[2]
    개수 = 칸[3] if len(칸) > 3 else None
    if 개수 is not None and q.dtype == np.uint8 and q.size * 2 - 1 <= 개수 <= q.size * 2:
        q = np.stack([q >> 4, q & 0x0F], axis=1).ravel()[:개수]
    if 곱 == 1.0 and 뺄것 == 0.0:
        return np.asarray(q, dtype=np.float32)
    return q.astype(np.float32) * 곱 - 뺄것


def 묶기(성김, 경로, 값형식="uint8", 되집기=True, 표=None):
    """engine 의 성김 표 -> .kgbin 한 파일. -> 쓴 바이트 수

    표는 {그래프이름: 예시해시} 다. 이것이 없으면 낡은 bin 이 조용히 옛
    지식을 내놓는다 — 그래프를 고쳐도 파일은 그대로니 알 길이 없다."""
    import numpy as np
    머리 = {"형식": 형식버전, "값형식": 값형식, "되집기": bool(되집기),
          "표": dict(표 or {}), "칸": {}}
    덩이, 자리 = [], 0

    def 담기(a, 형=None):
        nonlocal 자리
        a = np.ascontiguousarray(a)
        if 형:
            a = a.astype(형)
        덩이.append(a.tobytes())
        칸 = [자리, int(a.size), _형코드[str(a.dtype)]]
        자리 += len(덩이[-1])
        남 = (-자리) % 8                 # 8바이트 정렬. 자르기가 공짜가 된다
        if 남:
            덩이.append(b"\x00" * 남)
            자리 += 남
        return 칸

    for 이름, 칸 in 성김.items():
        값, 열, 끊, 행수, 길이, 뒤 = 칸
        q, 곱, 뺄것, 개수 = _누르기(펴기(값), 값형식)
        적 = {"v": 담기(q), "곱": 곱, "뺄것": 뺄것, "개수": 개수,
              "c": 담기(열, np.int16), "p": 담기(끊, np.int32),
              "n": int(행수), "l": 담기(길이, np.float32)}
        if 되집기 and 뒤 is not None and len(뒤[0]):
            rq, r곱, r뺄것, r개수 = _누르기(펴기(뒤[0]), 값형식)
            적.update({"rv": 담기(rq), "r곱": r곱, "r뺄것": r뺄것, "r개수": r개수,
                       "rc": 담기(뒤[1], np.int16), "rp": 담기(뒤[2], np.int32)})
        머리["칸"][이름] = 적

    글 = json.dumps(머리, ensure_ascii=False).encode("utf-8")
    앞 = _매직 + len(글).to_bytes(4, "little") + 글
    남 = (-len(앞)) % 8
    앞 += b"\x00" * 남
    with open(경로, "wb") as f:
        f.write(앞)
        for d in 덩이:
            f.write(d)
    return len(앞) + 자리


def 풀기(경로):
    """.kgbin -> (성김 표, 머리표). 배열은 mmap 을 잘라 쓴다 — 복사 없다."""
    import numpy as np
    바이트 = np.memmap(경로, dtype=np.uint8, mode="r")
    if bytes(바이트[:len(_매직)]) != _매직:
        raise ValueError("kgbin 이 아니다: %s" % 경로)
    n = int.from_bytes(bytes(바이트[6:10]), "little")
    머리 = json.loads(bytes(바이트[10:10 + n]).decode("utf-8"))
    if 머리["형식"] != 형식버전:
        raise ValueError("형식 %s 는 이 판이 못 읽는다" % 머리["형식"])
    바닥 = 10 + n
    바닥 += (-바닥) % 8
    버퍼 = 바이트.data                  # memoryview. frombuffer 가 복사를 안 한다

    def 꺼내기(칸):
        자리, 개수, 형 = 칸
        return np.frombuffer(버퍼, dtype=np.dtype(형), count=개수,
                             offset=바닥 + 자리)

    성김 = {}
    for 이름, 적 in 머리["칸"].items():
        값 = (꺼내기(적["v"]), 적["곱"], 적["뺄것"], 적["개수"])
        뒤 = None
        if "rv" in 적:
            뒤 = ((꺼내기(적["rv"]), 적["r곱"], 적["r뺄것"], 적["r개수"]),
                  꺼내기(적["rc"]), 꺼내기(적["rp"]))
        성김[이름] = (값, 꺼내기(적["c"]), 꺼내기(적["p"]),
                    int(적["n"]), 꺼내기(적["l"]), 뒤)
    return 성김, 머리


def _자가검사():
    import numpy as np
    import tempfile
    성김 = {"a.kg": (np.array([0.5, -0.25, 0.125], dtype=np.float32),
                    np.array([1, 3, 5], dtype=np.int16),
                    np.array([0, 2, 3], dtype=np.int64), 2,
                    np.array([7.0, 9.0], dtype=np.float32), None)}
    for 형식 in ("float32", "uint8", "uint4"):
        with tempfile.NamedTemporaryFile(suffix=".kgbin", delete=False) as f:
            길 = f.name
        묶기(성김, 길, 값형식=형식)
        나온, 머리 = 풀기(길)
        v = 펴기(나온["a.kg"][0])
        참 = 성김["a.kg"][0]
        # 눌러도 되돌린 값이 원래에서 한 눈 이상 벗어나면 안 된다.
        눈 = {"float32": 1e-6, "uint8": 0.004, "uint4": 0.04}[형식]
        assert np.abs(v - 참).max() <= 눈, (형식, v, 참)
        assert 나온["a.kg"][3] == 2 and list(나온["a.kg"][1]) == [1, 3, 5]
        assert 머리["값형식"] == 형식
        os.remove(길)
    # 되집기를 빼면 뒤 자리가 비어야 한다. 빼는 것이 실제로 빠지는지 본다.
    성김2 = dict(성김)
    성김2["a.kg"] = 성김["a.kg"][:5] + ((np.array([0.5], dtype=np.float32),
                                       np.array([2], dtype=np.int16),
                                       np.array([0, 1], dtype=np.int64)),)
    with tempfile.NamedTemporaryFile(suffix=".kgbin", delete=False) as f:
        길 = f.name
    묶기(성김2, 길, 되집기=False)
    assert 풀기(길)[0]["a.kg"][5] is None
    묶기(성김2, 길, 되집기=True)
    assert 풀기(길)[0]["a.kg"][5] is not None
    os.remove(길)
    print("자가검사 ok")


if __name__ == "__main__":
    값형식 = "uint8"
    if "--값" in sys.argv:
        값형식 = sys.argv[sys.argv.index("--값") + 1]
    되집기 = "없음" not in sys.argv[sys.argv.index("--되집기") + 1:][:1] \
        if "--되집기" in sys.argv else True
    여기 = os.path.dirname(os.path.abspath(__file__))
    길 = os.path.join(여기, ".색인.kgbin")
    if "--자가검사" in sys.argv:
        _자가검사()
    elif "--묶기" in sys.argv:
        os.environ.setdefault("KG_ENCODER", "문자")
        sys.path.insert(0, 여기)
        import engine
        색인 = engine.그래프색인()
        if "성김" not in 색인:
            print("성긴 색인이 아니다(신경 인코더). 묶을 것이 없다.")
            sys.exit(1)
        import hashlib
        from encoder import MODEL
        표 = {이름: hashlib.sha1((MODEL + "\n".join(예시)).encode("utf-8"))
                   .hexdigest()[:16]
              for 이름, 예시 in 색인["공통층"].items()}
        크기 = 묶기(색인["성김"], 길, 값형식, 되집기, 표)
        옛 = os.path.join(여기, ".색인벡터.npz")
        print("%s  %.2f MB  (칸 %d개 · 값 %s · 되집기 %s)"
              % (길, 크기 / 1e6, len(색인["성김"]), 값형식, "있음" if 되집기 else "없음"))
        if os.path.exists(옛):
            print("  견줌: .색인벡터.npz %.2f MB -> %.0f%%"
                  % (os.path.getsize(옛) / 1e6, 100 * 크기 / os.path.getsize(옛)))
    elif "--보기" in sys.argv:
        성김, 머리 = 풀기(길)
        print("칸 %d개 · 값 %s · 되집기 %s · %.2f MB"
              % (len(성김), 머리["값형식"], 머리["되집기"],
                 os.path.getsize(길) / 1e6))
    else:
        print(__doc__)
