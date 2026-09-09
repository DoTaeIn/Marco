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

_MAGIC = b"KGBIN\x00"
fmt_version = 1
_shape_code = {"float32": "f4", "uint8": "u1", "uint16": "u2", "int16": "i2",
          "int32": "i4", "int64": "i8"}


def _pack_bits(v, fmt):
    """실수 배열 -> (누른 배열, 곱, 뺄것, 개수). 되돌리면 q*곱 - 뺄것 이다.

    uint4 는 한 바이트에 둘씩 접는다. 안 접으면 uint8 과 파일 크기가 똑같아
    (8.65 MB) 고를 이유가 없는 선택지가 된다 — 실제로 처음엔 그랬다."""
    import numpy as np
    v = np.asarray(v, dtype=np.float32)
    if fmt == "float32" or v.size == 0:
        return v.astype(np.float32), 1.0, 0.0, int(v.size)
    bit = {"uint8": 8, "uint4": 4}[fmt]
    mask = (1 << bit) - 1
    width = float(np.abs(v).max()) or 1.0
    q = np.clip(np.round((v + width) / (2 * width) * mask), 0, mask).astype(np.uint8)
    count = int(q.size)
    if bit == 4:
        if count % 2:
            q = np.append(q, np.uint8(0))
        q = (q[0::2] << 4) | q[1::2]
    return q, (2 * width) / mask, width, count


def expand(slot):
    """(누른 배열, 곱, 뺄것[, 개수]) -> float32. 안 눌린 것은 그대로."""
    import numpy as np
    if not isinstance(slot, tuple):
        return slot
    q, mul, remove = slot[0], slot[1], slot[2]
    count = slot[3] if len(slot) > 3 else None
    if count is not None and q.dtype == np.uint8 and q.size * 2 - 1 <= count <= q.size * 2:
        q = np.stack([q >> 4, q & 0x0F], axis=1).ravel()[:count]
    if mul == 1.0 and remove == 0.0:
        return np.asarray(q, dtype=np.float32)
    return q.astype(np.float32) * mul - remove


def write_pack(sparse, path, value_fmt="uint8", reversible=True, table=None):
    """engine 의 성김 표 -> .kgbin 한 파일. -> 쓴 바이트 수

    표는 {그래프이름: 예시해시} 다. 이것이 없으면 낡은 bin 이 조용히 옛
    지식을 내놓는다 — 그래프를 고쳐도 파일은 그대로니 알 길이 없다."""
    import numpy as np
    head = {"형식": fmt_version, "값형식": value_fmt, "되집기": bool(reversible),
          "표": dict(table or {}), "칸": {}}
    blob, pos = [], 0

    def pack_vals(a, typ=None):
        nonlocal pos
        a = np.ascontiguousarray(a)
        if typ:
            a = a.astype(typ)
        blob.append(a.tobytes())
        slot = [pos, int(a.size), _shape_code[str(a.dtype)]]
        pos += len(blob[-1])
        other = (-pos) % 8                 # 8바이트 정렬. 자르기가 공짜가 된다
        if other:
            blob.append(b"\x00" * other)
            pos += other
        return slot

    for name, slot in sparse.items():
        value, col, bounds, row_count, length, rear = slot
        q, mul, remove, count = _pack_bits(expand(value), value_fmt)
        rec = {"v": pack_vals(q), "곱": mul, "뺄것": remove, "개수": count,
              "c": pack_vals(col, np.int16), "p": pack_vals(bounds, np.int32),
              "n": int(row_count), "l": pack_vals(length, np.float32)}
        if reversible and rear is not None and len(rear[0]):
            rq, r_mul, r_remove, r_count = _pack_bits(expand(rear[0]), value_fmt)
            rec.update({"rv": pack_vals(rq), "r곱": r_mul, "r뺄것": r_remove, "r개수": r_count,
                       "rc": pack_vals(rear[1], np.int16), "rp": pack_vals(rear[2], np.int32)})
        head["칸"][name] = rec

    txt = json.dumps(head, ensure_ascii=False).encode("utf-8")
    front = _MAGIC + len(txt).to_bytes(4, "little") + txt
    other = (-len(front)) % 8
    front += b"\x00" * other
    with open(path, "wb") as f:
        f.write(front)
        for d in blob:
            f.write(d)
    return len(front) + pos


def unpack(path):
    """.kgbin -> (성김 표, 머리표). 배열은 mmap 을 잘라 쓴다 — 복사 없다."""
    import numpy as np
    byte = np.memmap(path, dtype=np.uint8, mode="r")
    if bytes(byte[:len(_MAGIC)]) != _MAGIC:
        raise ValueError("kgbin 이 아니다: %s" % path)
    n = int.from_bytes(bytes(byte[6:10]), "little")
    head = json.loads(bytes(byte[10:10 + n]).decode("utf-8"))
    if head["형식"] != fmt_version:
        raise ValueError("형식 %s 는 이 판이 못 읽는다" % head["형식"])
    floor = 10 + n
    floor += (-floor) % 8
    buf = byte.data                  # memoryview. frombuffer 가 복사를 안 한다

    def pop(slot):
        pos, count, typ = slot
        return np.frombuffer(buf, dtype=np.dtype(typ), count=count,
                             offset=floor + pos)

    sparse = {}
    for name, rec in head["칸"].items():
        value = (pop(rec["v"]), rec["곱"], rec["뺄것"], rec["개수"])
        rear = None
        if "rv" in rec:
            rear = ((pop(rec["rv"]), rec["r곱"], rec["r뺄것"], rec["r개수"]),
                  pop(rec["rc"]), pop(rec["rp"]))
        sparse[name] = (value, pop(rec["c"]), pop(rec["p"]),
                    int(rec["n"]), pop(rec["l"]), rear)
    return sparse, head


def _selfcheck():
    import numpy as np
    import tempfile
    sparse = {"a.kg": (np.array([0.5, -0.25, 0.125], dtype=np.float32),
                    np.array([1, 3, 5], dtype=np.int16),
                    np.array([0, 2, 3], dtype=np.int64), 2,
                    np.array([7.0, 9.0], dtype=np.float32), None)}
    for fmt in ("float32", "uint8", "uint4"):
        with tempfile.NamedTemporaryFile(suffix=".kgbin", delete=False) as f:
            loc = f.name
        write_pack(sparse, loc, value_fmt=fmt)
        seen, head = unpack(loc)
        v = expand(seen["a.kg"][0])
        true = sparse["a.kg"][0]
        # 눌러도 되돌린 값이 원래에서 한 눈 이상 벗어나면 안 된다.
        mask = {"float32": 1e-6, "uint8": 0.004, "uint4": 0.04}[fmt]
        assert np.abs(v - true).max() <= mask, (fmt, v, true)
        assert seen["a.kg"][3] == 2 and list(seen["a.kg"][1]) == [1, 3, 5]
        assert head["값형식"] == fmt
        os.remove(loc)
    # 되집기를 빼면 뒤 자리가 비어야 한다. 빼는 것이 실제로 빠지는지 본다.
    sparse2 = dict(sparse)
    sparse2["a.kg"] = sparse["a.kg"][:5] + ((np.array([0.5], dtype=np.float32),
                                       np.array([2], dtype=np.int16),
                                       np.array([0, 1], dtype=np.int64)),)
    with tempfile.NamedTemporaryFile(suffix=".kgbin", delete=False) as f:
        loc = f.name
    write_pack(sparse2, loc, reversible=False)
    assert unpack(loc)[0]["a.kg"][5] is None
    write_pack(sparse2, loc, reversible=True)
    assert unpack(loc)[0]["a.kg"][5] is not None
    os.remove(loc)
    print("자가검사 ok")


if __name__ == "__main__":
    value_fmt = "uint8"
    if "--값" in sys.argv:
        value_fmt = sys.argv[sys.argv.index("--값") + 1]
    reversible = "없음" not in sys.argv[sys.argv.index("--되집기") + 1:][:1] \
        if "--되집기" in sys.argv else True
    here = os.path.dirname(os.path.abspath(__file__))
    loc = os.path.join(here, ".색인.kgbin")
    if "--자가검사" in sys.argv:
        _selfcheck()
    elif "--묶기" in sys.argv:
        os.environ.setdefault("KG_ENCODER", "문자")
        sys.path.insert(0, here)
        import engine
        index = engine.graph_index()
        if "성김" not in index:
            print("성긴 색인이 아니다(신경 인코더). 묶을 것이 없다.")
            sys.exit(1)
        import hashlib
        from encoder import MODEL
        table = {name: hashlib.sha1((MODEL + "\n".join(example)).encode("utf-8"))
                   .hexdigest()[:16]
              for name, example in index["공통층"].items()}
        size = write_pack(index["성김"], loc, value_fmt, reversible, table)
        old = os.path.join(here, ".색인벡터.npz")
        print("%s  %.2f MB  (칸 %d개 · 값 %s · 되집기 %s)"
              % (loc, size / 1e6, len(index["성김"]), value_fmt, "있음" if reversible else "없음"))
        if os.path.exists(old):
            print("  견줌: .색인벡터.npz %.2f MB -> %.0f%%"
                  % (os.path.getsize(old) / 1e6, 100 * size / os.path.getsize(old)))
    elif "--보기" in sys.argv:
        sparse, head = unpack(loc)
        print("칸 %d개 · 값 %s · 되집기 %s · %.2f MB"
              % (len(sparse), head["값형식"], head["되집기"],
                 os.path.getsize(loc) / 1e6))
    else:
        print(__doc__)
