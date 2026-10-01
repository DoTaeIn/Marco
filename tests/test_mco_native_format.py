"""MCO Format 1 (docs/mco/format-1.md): writer, reader, damaged files, compile, run, inspect.

The format tests at the top build a small pack in memory and need no MARCO
runtime. The tests marked "MARCO" below them compile a model from two graphs
of this checkout and run it through the MARCO engine.
"""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import struct
import zipfile
import zlib

import pytest

import mco
from mco.errors import MCOError
from mco.formats import detect, write_native
from mco.native import Chunk, Container, NativeModel, encode, edge_id, graph_id, node_id, rule_id
from mco.native.container import ENTRY, ENTRY_SIZE, HEADER, HEADER_SIZE, MAX_RAW, header_digest
from mco.native.pack import KNOWN_CHUNKS, build_chunks, canonical_json, content_identity, kgpack_zip

ROOT = Path(__file__).resolve().parents[1]
HEADER_FIELDS = ("magic", "major", "minor", "header_size", "flags", "toc_count", "toc_offset", "toc_size",
                 "file_size", "entry_size", "reserved", "digest", "reserved2")
ENTRY_FIELDS = ("type", "version", "flags", "compression", "offset", "length", "raw_length", "sha256")


# --- a small pack, built without MARCO ------------------------------------------------------

GRAPH_A = """역할: 나눔
목표: 몫을안다

[개념]
몫을안다 {원 = 총액 / 인원}: "나눠 내자" | "얼마씩"
총액 {원}: "총액을 안다"

[논증]
총액 -이어짐-> 몫을안다
"""
GRAPH_B = "# English\n역할: greeter\n목표: greet\n\n[개념]\ngreet: \"hello\" | \"hi\"\n"


def _pack_parts(graph_a: str = GRAPH_A) -> tuple[dict, dict[str, bytes]]:
    members = {
        "axioms/core.json": b'{"schema":"nai-axioms-v1","rules":[{"id":"r.keep"}]}\n',
        "graphs/a.kg": graph_a.encode(),
        "graphs/a.학습.jsonl": b'{"x":1}\n',
        "graphs/b.kg": GRAPH_B.encode(),
        "notes/readme.txt": b"",
        "styles/english.json": b'{"default_model_language": true}\r\n',
    }
    files = [{"path": p, "kind": "graph" if p.endswith(".kg") else "asset", "bytes": len(b),
              **content_identity(b)} for p, b in sorted(members.items())]
    manager = {"format": "nai-kg-manager", "version": 1, "role": "노드 매니저", "goal": "그래프고르기",
               "nodes": [{"path": "graphs/a.kg", "role": "나눔", "goal": "몫을안다",
                          "examples": ["몫을안다", "나눠 내자", "얼마씩"]},
                         {"path": "graphs/b.kg", "role": "greeter", "goal": "greet", "examples": []}],
               "edges": [["graphs/a.kg", "후보", "그래프고르기"], ["graphs/b.kg", "후보", "그래프고르기"]]}
    model = {"format": "nai-model", "version": 1, "language": "styles/english.json",
             "axioms": ["axioms/core.json"], "relational_model": None}
    return {"format": "nai-kgpack", "version": 3, "files": files, "manager": manager, "model": model}, members


def _payload(graph_a: str = GRAPH_A) -> bytes:
    return kgpack_zip(*_pack_parts(graph_a))


def _chunks(payload: bytes | None = None) -> list[Chunk]:
    payload = payload or _payload()
    manifest, members = _pack_parts()
    return build_chunks(manifest, members, source_sha256=hashlib.sha256(payload).hexdigest(),
                        source_bytes=len(payload), name="tiny", generator="test")


@pytest.fixture(scope="module")
def tiny() -> bytes:
    return encode(_chunks())


# --- damage helpers ---------------------------------------------------------------------------

def _header(data: bytes) -> dict:
    return dict(zip(HEADER_FIELDS, HEADER.unpack_from(data)))


def _reseal(data: bytes) -> bytes:
    """Recompute the header checksum, so a test reaches the check after it."""
    h = _header(data)
    toc = data[h["toc_offset"]:h["toc_offset"] + h["toc_size"]]
    return data[:56] + header_digest(data[:HEADER_SIZE], toc) + data[88:]


def _patch_header(data: bytes, reseal: bool = True, **changes) -> bytes:
    h = _header(data)
    h.update(changes)
    out = HEADER.pack(*(h[f] for f in HEADER_FIELDS)) + data[HEADER_SIZE:]
    return _reseal(out) if reseal else out


def _patch_entry(data: bytes, index: int, reseal: bool = True, **changes) -> bytes:
    at = _header(data)["toc_offset"] + index * ENTRY_SIZE
    e = dict(zip(ENTRY_FIELDS, ENTRY.unpack_from(data, at)))
    e.update(changes)
    out = data[:at] + ENTRY.pack(*(e[f] for f in ENTRY_FIELDS)) + data[at + ENTRY_SIZE:]
    return _reseal(out) if reseal else out


def _entry(data: bytes, index: int) -> dict:
    return dict(zip(ENTRY_FIELDS, ENTRY.unpack_from(data, _header(data)["toc_offset"] + index * ENTRY_SIZE)))


def _flip(data: bytes, at: int) -> bytes:
    return data[:at] + bytes([data[at] ^ 0xFF]) + data[at + 1:]


def _with_manifest(chunks: list[Chunk], **changes) -> list[Chunk]:
    manifest = json.loads(chunks[0].data)
    manifest.update(changes)
    return [Chunk("MANI", canonical_json(manifest), compression=0)] + chunks[1:]


def _verdict(data: bytes, full: bool = True) -> str:
    try:
        with NativeModel.from_bytes(data) as model:
            if full:
                model.verify_all()
        return "ok"
    except MCOError as exc:
        return type(exc).__name__


# --- round trip and determinism ------------------------------------------------------------

def test_container_round_trip_gives_identical_chunks() -> None:
    chunks = [Chunk("AAAA", b"first", version=3), Chunk("BBBB", b"", required=False),
              Chunk("CCCC", b"z" * 5000), Chunk("DDDD", "한글".encode(), compression=0)]
    data = encode(chunks)
    assert data == encode(chunks)                                   # deterministic
    with Container.from_bytes(data, known={c.type: 3 for c in chunks}) as box:
        assert [(e.type, e.version, e.required) for e in box.entries] == \
            [(c.type, c.version, c.required) for c in chunks]
        assert [box.read(e) for e in box.entries] == [c.data for c in chunks]
        assert box.entries[2].compression == 1 and box.entries[2].length < 5000   # compressed when smaller
        assert all(e.offset % 8 == 0 for e in box.entries)
        box.verify_all()


def test_writer_is_deterministic_and_pack_round_trips(tmp_path: Path) -> None:
    payload = _payload()
    first, second = tmp_path / "a.mco", tmp_path / "b.mco"
    write_native(first, payload, name="tiny")
    write_native(second, payload, name="tiny")
    assert first.read_bytes() == second.read_bytes()
    manifest, members = _pack_parts()
    with NativeModel.open(first) as model:
        model.verify_all()
        assert model.pack() == (manifest, members)
        assert model.kgpack_bytes() == payload
        assert model.manifest["content_sha256"] == hashlib.sha256(canonical_json(manifest) + b"\n").hexdigest()
        assert model.manifest["supports"] == {"overlay": False, "snapshot": False}
        assert [m.chunk.type for m in model.members] == ["AXIM", "GRPH", "LERN", "GRPH", "ASET", "LANG"]


def test_one_chunk_is_read_without_reading_the_file(tiny: bytes) -> None:
    class Counting(io.BytesIO):
        total = 0

        def read(self, size: int = -1) -> bytes:
            data = super().read(size)
            Counting.total += len(data)
            return data

    stream = Counting(tiny)
    model = NativeModel(Container(stream, len(tiny), known=KNOWN_CHUNKS))
    opened = Counting.total
    tables = sum(e.length for e in model.container.entries[:4])
    toc = len(model.container.entries) * ENTRY_SIZE
    assert opened == 8 + 4 + HEADER_SIZE + toc + tables      # magic, version, header, TOC, the four tables
    member = model.member("graphs/b.kg")
    assert model.member_bytes("graphs/b.kg") == GRAPH_B.encode()
    assert Counting.total - opened == member.chunk.length
    assert Counting.total < len(tiny)


# --- identifiers ------------------------------------------------------------------------------

def test_identifiers_are_stable_keys_not_positions(tmp_path: Path) -> None:
    reordered = "\n".join(reversed(GRAPH_A.strip().splitlines())) + "\n"
    ids = []
    for index, graph in enumerate((GRAPH_A, GRAPH_A, reordered)):
        manifest, members = _pack_parts(graph)
        path = tmp_path / f"m{index}.mco"
        write_native(path, kgpack_zip(manifest, members))
        with NativeModel.open(path) as model:
            ids.append((model.graph_ids(), [m.path for m in model.members],
                        [n["path"] for n in model.manager()["nodes"]], model.manifest["content_sha256"]))
    assert ids[0] == ids[1]                                        # same input twice
    assert ids[2][:3] == ids[0][:3] and ids[2][3] != ids[0][3]      # reordered lines: same ids, new content
    assert graph_id("graphs/a.kg") == "graphs/a.kg"
    assert node_id("graphs/a.kg", "총액") == "graphs/a.kg#총액"
    assert edge_id("graphs/a.kg", "총액", "이어짐", "몫을안다") == hashlib.sha256(
        "graphs/a.kg\x00총액\x00이어짐\x00몫을안다".encode()).hexdigest()
    assert rule_id({"id": "r.keep", "when": []}) == "r.keep"


# --- damaged files: one variant per rule, each with its verdict -------------------------------

def _member_index(data: bytes, kind: str = "GRPH") -> int:
    with NativeModel.from_bytes(data) as model:
        return next(e.index for e in model.container.entries if e.type == kind)


def _padded_index(data: bytes) -> int:
    with NativeModel.from_bytes(data) as model:
        return next(e.index for e in model.container.entries if e.length % 8)


DAMAGE = {
    # name: (mutation of the valid file, verdict on full verification)
    "valid": (lambda d: d, "ok"),
    "truncated tail": (lambda d: d[:-10], "ModelFormatError"),
    "truncated header": (lambda d: d[:50], "ModelFormatError"),
    "shorter than the magic": (lambda d: d[:5], "ModelFormatError"),
    "bad magic": (lambda d: b"\x89MCX" + d[4:], "ModelFormatError"),
    "major version 2": (lambda d: _patch_header(d, reseal=False, major=2), "UnsupportedFormatError"),
    "major version 0": (lambda d: _patch_header(d, major=0), "ModelFormatError"),
    "header checksum mismatch": (lambda d: _flip(d, _header(d)["toc_offset"] + 40), "IntegrityError"),
    "table chunk checksum mismatch": (lambda d: _flip(d, _entry(d, 3)["offset"] + 2), "IntegrityError"),
    "member chunk checksum mismatch": (lambda d: _flip(d, _entry(d, _member_index(d))["offset"] + 1),
                                       "IntegrityError"),
    "TOC outside the file": (lambda d: _patch_header(d, toc_offset=_header(d)["toc_offset"] + 8),
                             "ModelFormatError"),
    "absurd chunk count": (lambda d: _patch_header(d, toc_count=1_000_000, toc_size=64_000_000),
                           "ModelFormatError"),
    "overlapping chunks": (lambda d: _patch_entry(d, 1, offset=_entry(d, 0)["offset"]), "ModelFormatError"),
    "gap between chunks": (lambda d: _patch_entry(d, 1, offset=_entry(d, 1)["offset"] + 8), "ModelFormatError"),
    "offset overflow": (lambda d: _patch_entry(d, 1, offset=2**64 - 8), "ModelFormatError"),
    "length overflow": (lambda d: _patch_entry(d, 1, length=2**64 - 1), "ModelFormatError"),
    "raw_length over the cap": (lambda d: _patch_entry(d, _member_index(d), raw_length=MAX_RAW + 1),
                                "ModelFormatError"),
    "uncompressed length != raw_length": (lambda d: _patch_entry(d, 1, raw_length=_entry(d, 1)["length"] + 1),
                                          "ModelFormatError"),
    "invalid type bytes": (lambda d: _patch_entry(d, 1, type=b"st!s"), "ModelFormatError"),
    "trailing bytes": (lambda d: d + b"\x00" * 8, "ModelFormatError"),
    "nonzero padding": (lambda d: (lambda e: d[:e["offset"] + e["length"]] + b"\x01"
                                   + d[e["offset"] + e["length"] + 1:])(_entry(d, _padded_index(d))),
                        "ModelFormatError"),
    "unknown required header flag": (lambda d: _patch_header(d, flags=0x0001), "UnsupportedFormatError"),
    "unknown optional header flag": (lambda d: _patch_header(d, flags=0x10000), "ok"),
}

REBUILT = {
    # name: (chunk list of the variant, verdict)
    "unknown optional chunk is skipped": (lambda c: c + [Chunk("ZZZZ", b"x" * 100, required=False)], "ok"),
    "reserved optional PROV chunk is skipped": (lambda c: c + [Chunk("PROV", b"{}", required=False)], "ok"),
    "empty optional chunk": (lambda c: c + [Chunk("ZZZZ", b"", required=False)], "ok"),
    "unknown required chunk": (lambda c: c + [Chunk("ZZZZ", b"x")], "UnsupportedFormatError"),
    "reserved required NODE chunk": (lambda c: c + [Chunk("NODE", b"x")], "UnsupportedFormatError"),
    "newer required chunk version": (lambda c: c[:3] + [Chunk("GDIR", c[3].data, version=2)] + c[4:],
                                     "UnsupportedFormatError"),
    "duplicate MANI": (lambda c: c + [c[0]], "ModelFormatError"),
    "missing GDIR": (lambda c: c[:3] + [Chunk("ZZZZ", b"", required=False)] + c[4:], "ModelFormatError"),
    "unknown required runtime feature": (lambda c: _with_manifest(c, requires=["marco.kg-text/1", "x.new/1"]),
                                         "UnsupportedFormatError"),
    "overlay base set": (lambda c: _with_manifest(c, base={"build_id": "b", "content_sha256": "0" * 64}),
                         "UnsupportedFormatError"),
    "change sequence set": (lambda c: _with_manifest(c, change_sequence=7), "UnsupportedFormatError"),
    "snapshot claimed": (lambda c: _with_manifest(c, supports={"overlay": False, "snapshot": True}),
                         "UnsupportedFormatError"),
    "unknown semantic schema": (lambda c: _with_manifest(c, semantic_schema={"id": "other", "version": 1}),
                                "UnsupportedFormatError"),
    "manifest version mismatch": (lambda c: _with_manifest(c, format_version=[1, 3]), "ModelFormatError"),
    "manifest counts mismatch": (lambda c: _with_manifest(c, counts={"members": 1}), "ModelFormatError"),
    "manifest duplicate key": (lambda c: [Chunk("MANI", b'{"format":"mco","format":"mco"}', compression=0)]
                               + c[1:], "ModelFormatError"),
    "manifest not JSON": (lambda c: [Chunk("MANI", b"\xff\xfe", compression=0)] + c[1:], "ModelFormatError"),
    "content_sha256 mismatch": (lambda c: _with_manifest(c, content_sha256="0" * 64), "IntegrityError"),
    "member SHA-256 mismatch": (lambda c: c[:2] + [Chunk("MEMB", c[2].data[:-1] + bytes([c[2].data[-1] ^ 1]),
                                                         compression=0)] + c[3:], "IntegrityError"),
    "MEMB rows do not fill the chunk": (lambda c: c[:2] + [Chunk("MEMB", c[2].data + b"\x00" * 4,
                                                                 compression=0)] + c[3:], "ModelFormatError"),
    "STRS absurd count": (lambda c: c[:1] + [Chunk("STRS", struct.pack("<II", 2**31, 0) + c[1].data[8:],
                                                   compression=0)] + c[2:], "ModelFormatError"),
}


@pytest.mark.parametrize("name", list(DAMAGE))
def test_damaged_bytes_get_their_verdict(tiny: bytes, name: str) -> None:
    mutate, expected = DAMAGE[name]
    assert _verdict(mutate(tiny)) == expected


@pytest.mark.parametrize("name", list(REBUILT))
def test_damaged_chunk_sets_get_their_verdict(name: str) -> None:
    variant, expected = REBUILT[name]
    assert _verdict(encode(variant(_chunks()))) == expected


def test_newer_minor_version_is_read() -> None:
    chunks = _with_manifest(_chunks(), format_version=[1, 4])
    with NativeModel.from_bytes(encode(chunks, minor=4)) as model:
        model.verify_all()
        assert (model.major, model.minor) == (1, 4)


def test_open_level_does_not_read_members(tiny: bytes) -> None:
    damaged = DAMAGE["member chunk checksum mismatch"][0](tiny)
    assert _verdict(damaged, full=False) == "ok"
    with NativeModel.from_bytes(damaged) as model, pytest.raises(mco.IntegrityError):
        model.member_bytes("graphs/a.kg")
    skipped = encode(REBUILT["unknown optional chunk is skipped"][0](_chunks()))
    with NativeModel.from_bytes(skipped) as model, NativeModel.from_bytes(tiny) as plain:
        assert model.pack() == plain.pack()


def test_decompression_is_bounded_by_raw_length() -> None:
    bomb = zlib.compress(b"\x00" * (8 << 20), 9)               # 8 MiB of zeros in a few KiB
    data = encode([Chunk("BOMB", b"\x00" * (8 << 20), compression=1)])
    entry = _entry(data, 0)
    assert entry["length"] == len(bomb) < 16_384
    lying = _patch_entry(data, 0, raw_length=100)
    with Container.from_bytes(lying, known={"BOMB": 1}) as box:
        with pytest.raises(mco.ModelFormatError, match="past its declared raw_length"):
            box.read(0)
    short = _patch_entry(data, 0, raw_length=(8 << 20) + 1)
    with Container.from_bytes(short, known={"BOMB": 1}) as box:
        with pytest.raises(mco.ModelFormatError, match="raw_length says"):
            box.read(0)
    with Container.from_bytes(_patch_entry(data, 0, compression=7), known={"BOMB": 1}) as box:
        with pytest.raises(mco.UnsupportedFormatError):
            box.read(0)


def test_detect_reports_refused_files_and_load_refuses_them(tiny: bytes, tmp_path: Path) -> None:
    newer = tmp_path / "newer.mco"
    newer.write_bytes(DAMAGE["major version 2"][0](tiny))
    file = detect(newer)
    assert (file.kind, file.version) == ("mco-native", 2) and "newer than this reader" in file.refusal
    with pytest.raises(mco.UnsupportedFormatError):
        file.payload_bytes()
    garbage = tmp_path / "garbage.mco"
    garbage.write_bytes(b"\x89MCO" + b"\x00" * 64)
    with pytest.raises(mco.ModelFormatError):
        detect(garbage)


# --- MARCO: compile ------------------------------------------------------------------------------
# A small model per language, built from this checkout's graphs; compat and native from one input.

KO = {"graphs": ["graphs/graph_정산_나눠내기.kg", "graphs/graph_일상추론.kg"], "language": "styles/한국어.json"}
EN = {"graphs": ["graphs/graph_en_bill_split.kg", "graphs/graph_일상추론.kg"], "language": "styles/english.json"}


@pytest.fixture(scope="module")
def builds(tmp_path_factory: pytest.TempPathFactory) -> dict[tuple[str, str], Path]:
    out = tmp_path_factory.mktemp("native")
    paths = {}
    for lang, spec in (("ko", KO), ("en", EN)):
        for fmt in ("compat", "native"):
            path = out / f"{lang}-{fmt}.mco"
            report = mco.compile(ROOT, path, name=f"T-{lang}", format=fmt, **spec)
            assert report.info.format == f"mco-{fmt}"
            paths[lang, fmt] = path
    return paths


def test_compile_native_is_deterministic_and_holds_the_same_pack(builds, tmp_path: Path) -> None:
    again = tmp_path / "again.mco"
    mco.compile(ROOT, again, name="T-ko", format="native", **KO)
    assert again.read_bytes() == builds["ko", "native"].read_bytes()
    native, compat = detect(builds["ko", "native"]), detect(builds["ko", "compat"])
    assert (native.kind, native.version, compat.kind) == ("mco-native", 1, "mco-compat")
    # The pack rebuilt from the chunks is byte for byte the pack MARCO wrote.
    payload = compat.payload_bytes()
    assert native.payload_bytes() == payload
    assert native.manifest["build_id"] == compat.manifest["build_id"]
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        assert native.manifest["content_sha256"] == hashlib.sha256(zf.read("manifest.json")).hexdigest()
    # From the compat file or the bare pack: the same native bytes.
    pack = tmp_path / "bare.kgpack"
    pack.write_bytes(payload)
    for source in (builds["ko", "compat"], pack):
        out = tmp_path / f"from-{source.suffix[1:]}.mco"
        mco.compile(source, out, name="T-ko", format="native")
        assert out.read_bytes() == builds["ko", "native"].read_bytes()
    assert mco.compile(pack, tmp_path / "default.mco").info.format == "mco-compat"   # 0.1.0 default kept
    with pytest.raises(mco.CompileError):
        mco.compile(builds["ko", "native"], tmp_path / "x.mco", format="native")
    with pytest.raises(mco.CompileError):
        mco.compile(pack, tmp_path / "x.mco", format="zip")


def test_cli_compiles_native(tmp_path: Path) -> None:
    from mco.cli import main
    out = io.StringIO()
    code = main(["compile", str(ROOT), "-o", str(tmp_path / "cli.mco"), "--graph", KO["graphs"][0],
                 "--language", KO["language"], "--format", "native", "--json"], stdout=out)
    info = json.loads(out.getvalue())["info"]
    assert code == 0 and info["format"] == "mco-native" and info["format_version"] == 1


# --- MARCO: run ---------------------------------------------------------------------------------

def _run(path: Path, turns: list[str]) -> list[tuple]:
    with mco.load(path) as model:
        out = []
        for text in turns:
            r = model.run(text)
            out.append((r.answer, r.status, [e.to_dict() for e in r.evidence], r.backend))
        return out


def _same_results(builds, lang: str, conversations: list[list[str]]) -> list[list[tuple]]:
    seen = []
    for turns in conversations:
        compat, native = _run(builds[lang, "compat"], turns), _run(builds[lang, "native"], turns)
        assert [r[3] for r in compat] == ["marco-kgpack"] * len(turns)
        assert [r[3] for r in native] == ["mco-native"] * len(turns)
        assert [r[:3] for r in native] == [r[:3] for r in compat]          # answer, status, evidence
        seen.append(native)
    return seen


@pytest.mark.language("한국어")
def test_native_answers_as_compat_does_in_korean(builds) -> None:
    split, stones = _same_results(builds, "ko", [["12만원 나왔어", "3명이야"],
                                                 ["돌은 23개 있다.", "돌 8개를 꺼냈다.", "지금 돌은 몇 개야?"]])
    assert split[-1][1] is mco.Status.ANSWERED and "40000" in split[-1][0] and split[-1][2]
    assert stones[-1][:2] == ("15개입니다.", mco.Status.ANSWERED)


@pytest.mark.language("english")
def test_native_answers_as_compat_does_in_english(builds) -> None:
    split, apples = _same_results(builds, "en", [["the bill was 120000 won", "3 people"],
                                                 ["Minsu has five apples.", "How many apples does Minsu have?"]])
    assert split[0][1] is mco.Status.NEEDS_INPUT and split[-1][1] is mco.Status.ANSWERED
    assert "40000" in split[-1][0] and any(e["kind"] == "graph_path" for e in split[-1][2])
    assert apples[-1][:2] == ("5 apples.", mco.Status.ANSWERED)


@pytest.mark.language("english")
def test_native_knowledge_comes_from_the_file(tmp_path: Path) -> None:
    # A graph that exists only in the .mco: its source tree is deleted before the run,
    # and the run is a separate process started outside the checkout.
    tree = tmp_path / "tree"
    for rel in EN["graphs"] + ["styles/english.json", "styles/한국어.json", "axioms/core.json"]:
        (tree / rel).parent.mkdir(parents=True, exist_ok=True)
        (tree / rel).write_bytes((ROOT / rel).read_bytes())
    graph = tree / EN["graphs"][0]
    marker = "straight from the native file"
    text = graph.read_text(encoding="utf-8")
    assert "결론값: Then it is {값} each." in text
    graph.write_text(text.replace("결론값: Then it is {값} each.", f"결론값: Then it is {{값}} each, {marker}."),
                     encoding="utf-8")
    model = tmp_path / "only-here.mco"
    mco.compile(tree, model, format="native", **EN)
    import shutil
    import subprocess
    import sys
    shutil.rmtree(tree)
    code = ("import sys, mco; m = mco.load(sys.argv[1]); m.run('the bill was 120000 won'); "
            "r = m.run('3 people'); print(r.backend, r.status, r.answer)")
    env = {k: v for k, v in __import__("os").environ.items() if k != "PYTHONPATH"}
    env.update(MCO_MARCO_ROOT=str(ROOT), PYTHONPATH=str(ROOT), KG_ENCODER="문자", NAI_LANGUAGE="english")
    out = subprocess.run([sys.executable, "-c", code, str(model)], cwd=tmp_path, env=env,
                         capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
    assert out.startswith("mco-native answered ") and "40000" in out and marker in out


# --- inspect --------------------------------------------------------------------------------------

def test_inspect_native_shows_version_manifest_and_chunks(builds) -> None:
    path = builds["ko", "native"]
    info = mco.inspect(path)
    compat = mco.inspect(builds["ko", "compat"])
    assert (info.format, info.format_version, info.backend, info.name) == ("mco-native", 1, "mco-native", "T-ko")
    assert info.verified and info.runnable and (info.graphs, info.assets) == (compat.graphs, compat.assets)
    assert (info.language, info.languages) == ("styles/한국어.json", ("styles/english.json", "styles/한국어.json"))
    assert (info.build_id, info.fingerprint) == (compat.build_id, compat.fingerprint)
    assert "overlay: not supported in this version" in info.notes
    assert "snapshot: not supported in this version" in info.notes
    assert any("carried as typed chunks, not tables" in n for n in info.notes)
    manifest = info.to_dict(include_manifest=True)["manifest"]
    assert manifest["format"]["major"] == 1 and manifest["format"]["minor"] == 0
    assert manifest["mco"]["supports"] == {"overlay": False, "snapshot": False}
    chunks = manifest["chunks"]
    assert [c["type"] for c in chunks[:4]] == ["MANI", "STRS", "MEMB", "GDIR"]
    assert sum(c["type"] == "GRPH" for c in chunks) == 2
    assert all(0 < c["length"] <= c["raw_length"] for c in chunks)    # zlib only where it is smaller
    assert {m["path"] for m in manifest["members"]} >= set(KO["graphs"])


def test_inspect_native_runs_nothing(builds) -> None:
    import os
    import subprocess
    import sys
    code = ("import sys, mco; info = mco.inspect(sys.argv[1]); "
            "leaked = [m for m in ('engine', 'pack_model', 'views.kgpack_ui', 'marco.storage.kgpack') "
            "if m in sys.modules]; print(info.format, info.graphs, len(info.manifest['chunks']), leaked)")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    out = subprocess.run([sys.executable, "-c", code, str(builds["en", "native"])], cwd=ROOT, env=env,
                         capture_output=True, text=True, check=True).stdout.strip()
    assert out.startswith("mco-native 2 ") and out.endswith(" []")


def test_cli_inspect_native(builds) -> None:
    from mco.cli import main
    out = io.StringIO()
    assert main(["inspect", str(builds["ko", "native"])], stdout=out) == 0
    text = out.getvalue()
    assert "mco-native v1.0" in text and "content" in text and "marco.kg-text/1" in text
    assert "note: overlay: not supported in this version" in text and "note: snapshot: not supported" in text
    assert "chunks: " in text and "MANI" in text and "GRPH" in text and "GDIR" in text
    out = io.StringIO()
    assert main(["inspect", str(builds["ko", "native"]), "--json", "--manifest"], stdout=out) == 0
    data = json.loads(out.getvalue())
    assert data["graphs"] == 2 and data["manifest"]["chunks"][0]["type"] == "MANI"


def test_native_load_options_and_refusals(builds, tmp_path: Path) -> None:
    with pytest.raises(mco.InvalidInputError):
        mco.load(builds["ko", "native"], temperature=0.1)
    with pytest.raises(mco.UnsupportedFormatError):
        mco.load(builds["ko", "native"], backend="marco-kgpack")
    damaged = tmp_path / "damaged.mco"
    data = builds["ko", "native"].read_bytes()
    damaged.write_bytes(_flip(data, _entry(data, _member_index(data))["offset"] + 3))
    with pytest.raises(mco.IntegrityError):
        mco.load(damaged)
    newer = tmp_path / "newer.mco"
    newer.write_bytes(_patch_header(data, reseal=False, major=2))
    with pytest.raises(mco.UnsupportedFormatError):
        mco.load(newer)
