"""MCO Format 1.1 graph and rule tables (docs/mco/format-1.md sections 6.8-6.11).

The acceptance check is the first MARCO test: for every graph in ``graphs/``,
the dictionary rebuilt from the NODE and EDGE tables equals what MARCO's
``read_kg`` returns for the source file, with key order, list order and value
types. The format tests below it need no MARCO runtime.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import struct

import pytest

import mco
from mco.errors import MCOError
from mco.formats import write_native
from mco.native import Chunk, Container, NativeModel, edge_id, encode, graph_id, node_id
from mco.native.kgtext import parse_kg
from mco.native.pack import KNOWN_CHUNKS, MEMBER_TYPES, TABLE_TYPES, build_chunks, kgpack_zip
from mco.native.tables import ordered_equal

from test_mco_native_format import _pack_parts, _payload

ROOT = Path(__file__).resolve().parents[1]
ALL_GRAPHS = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "graphs").glob("*.kg"))


def _build(pack_parts=None, **kwargs) -> bytes:
    manifest, members = pack_parts or _pack_parts()
    payload = kgpack_zip(manifest, members)
    return encode(build_chunks(manifest, members, source_sha256=hashlib.sha256(payload).hexdigest(),
                               source_bytes=len(payload), name="t", generator="test", **kwargs))


def _with_graph(text: str, path: str = "graphs/a.kg") -> tuple[dict, dict]:
    """The small pack of test_mco_native_format with one graph's text replaced."""
    manifest, members = _pack_parts()
    members = dict(members, **{path: text.encode()})
    from mco.native.pack import content_identity
    manifest = dict(manifest, files=[dict(f, bytes=len(members[f["path"]]), **content_identity(members[f["path"]]))
                                     for f in manifest["files"]])
    return manifest, members


def _verdict(data: bytes) -> str:
    try:
        with NativeModel.from_bytes(data) as model:
            model.verify_all()
        return "ok"
    except MCOError as exc:
        return type(exc).__name__


def _mismatch_classes(want: dict, got: dict) -> list[str]:
    out = []
    if list(want) != list(got):
        out.append("top-level keys or their order")
    for key in want:
        if key in got and not ordered_equal(want[key], got[key]):
            out.append(f"{key}: {'order or type' if want[key] == got[key] else 'value'}")
    return out


# --- MARCO: every graph in graphs/ ------------------------------------------------------------

@pytest.fixture(scope="module")
def full(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("tables") / "all.mco"
    mco.compile(ROOT, path, name="all-graphs", format="native", graphs=["graphs/*.kg"])
    return path


@pytest.fixture
def read_kg(monkeypatch: pytest.MonkeyPatch):
    import engine
    # read_kg ends by merging hypernyms from data/개념망.json of the engine
    # checkout, a file outside the graph and outside the pack; the tables hold
    # the graph file's own content (format-1.md 6.9), so compare without it.
    monkeypatch.setattr(engine, "_shared_net", {})
    return lambda rel: engine.read_kg(str(ROOT / rel))


def test_every_graph_rebuilt_from_tables_equals_read_kg(full: Path, read_kg) -> None:
    assert len(ALL_GRAPHS) > 0
    mismatches: Counter = Counter()
    failed: dict[str, list[str]] = {}
    with NativeModel.open(full) as model:
        index = {row["member"]: row for row in model.table_index()}
        assert sorted(index) == ALL_GRAPHS
        source_only = sorted(p for p, row in index.items() if row["status"] != "tables")
        for path in ALL_GRAPHS:
            if path in source_only:
                continue
            classes = _mismatch_classes(read_kg(path), model.graph(graph_id(path)))
            mismatches.update(classes)
            if classes:
                failed[path] = classes
        checked = len(ALL_GRAPHS) - len(source_only)
        print(f"\ngraphs checked {checked} of {len(ALL_GRAPHS)}, source only {source_only}, "
              f"mismatch classes {dict(mismatches)}")
        assert not failed, failed
        assert source_only == [] and checked == len(ALL_GRAPHS)
        assert model.manifest["tables"]["tabled"] == checked


def test_rules_from_the_table_equal_the_packs(full: Path) -> None:
    from pack_model import PackModel
    with NativeModel.open(full) as model:
        manifest, assets = model.pack()
        expected = PackModel(manifest, assets)._axioms["rules"]
        assert len(expected) > 0
        assert model.rules() == expected
        rows = model.rule_rows()
        assert [r["rule_id"] for r in rows] == sorted((r["id"] for r in expected), key=lambda x: x.encode())
        assert {r["source"] for r in rows} == set(manifest["model"]["axioms"])


def test_full_tree_compiles_deterministically(full: Path, tmp_path: Path) -> None:
    again = tmp_path / "again.mco"
    mco.compile(ROOT, again, name="all-graphs", format="native", graphs=["graphs/*.kg"])
    assert again.read_bytes() == full.read_bytes()


def test_inspect_shows_table_counts(full: Path) -> None:
    from mco.cli import main
    info = mco.inspect(full)
    tables = info.manifest["tables"]
    assert tables["graphs"] == len(ALL_GRAPHS) and tables["tabled"] == len(ALL_GRAPHS)
    assert tables["nodes"] > 0 and tables["edges"] > 0 and tables["rules"] > 0
    assert any(n.startswith(f"tables: {len(ALL_GRAPHS)} of {len(ALL_GRAPHS)} graphs") for n in info.notes)
    out = io.StringIO()
    assert main(["inspect", str(full)], stdout=out) == 0
    text = out.getvalue()
    assert f"{tables['nodes']} nodes, {tables['edges']} edges, {tables['rules']} rules" in text
    assert "source text" in text and "NODE" in text and "INDX" in text


# --- format: tables of the small pack --------------------------------------------------------

def test_small_pack_tables_round_trip() -> None:
    manifest, members = _pack_parts()
    data = _build()
    with NativeModel.from_bytes(data) as model:
        model.verify_all()
        assert (model.major, model.minor) == (1, 1)
        for path in ("graphs/a.kg", "graphs/b.kg"):
            assert ordered_equal(model.graph(path), parse_kg(members[path], path))
        a = model.graph("graphs/a.kg")
        assert a["값셈"] == {"몫을안다": ("원", "총액 / 인원")} and isinstance(a["값셈"]["몫을안다"], tuple)
        assert model.rules() == [{"id": "r.keep"}]
        rows = model.graph_rows("graphs/a.kg")
        assert [n["node_id"] for n in rows["nodes"]] == ["graphs/a.kg#몫을안다", "graphs/a.kg#총액"]
        assert rows["edges"] == [{"edge_id": edge_id("graphs/a.kg", "총액", "이어짐", "몫을안다"), "src": "총액",
                                  "rel": "이어짐", "dst": "몫을안다", "list": "엣지", "ordinal": 0}]
        with pytest.raises(KeyError):
            model.graph("graphs/none.kg")
        types = {e.type: e.required for e in model.container.entries}
        assert types["GRPH"] is False and types["NODE"] is False and types["INDX"] is False


def test_one_graph_reads_only_its_own_chunks() -> None:
    data = _build()

    class Counting(io.BytesIO):
        total = 0

        def read(self, size: int = -1) -> bytes:
            out = super().read(size)
            Counting.total += len(out)
            return out

    model = NativeModel(Container(Counting(data), len(data), known=KNOWN_CHUNKS))
    model.table_index()                                      # INDX (and the RULE header), once
    before = Counting.total
    model.graph("graphs/b.kg")
    row = next(r for r in model._index() if r.graph == "graphs/b.kg")
    entries = model.container.entries
    assert Counting.total - before == entries[row.node_chunk].length + entries[row.edge_chunk].length


def test_reordered_lines_keep_every_identifier() -> None:
    text = ("역할: 나눔\n목표: 몫을안다\n\n[개념]\n몫을안다 {원 = 총액 / 인원}: \"나눠 내자\" | \"얼마씩\"\n"
            "총액 {원}: \"총액을 안다\"\n인원: \"몇 명\"\n\n[논증]\n총액 -이어짐-> 몫을안다\n인원 -이어짐-> 몫을안다\n"
            "\n[무관]\n날씨: \"비 온다\"\n")
    reordered = ("[무관]\n날씨: \"비 온다\"\n\n[논증]\n인원 -이어짐-> 몫을안다\n총액 -이어짐-> 몫을안다\n\n[개념]\n"
                 "인원: \"몇 명\"\n총액 {원}: \"총액을 안다\"\n몫을안다 {원 = 총액 / 인원}: \"나눠 내자\" | \"얼마씩\"\n")
    reordered = "역할: 나눔\n목표: 몫을안다\n" + reordered
    rows, graphs, files = [], [], []
    for body in (text, text, reordered):
        data = _build(_with_graph(body))
        files.append(data)
        with NativeModel.from_bytes(data) as model:
            r = model.graph_rows("graphs/a.kg")
            rows.append(([n["node_id"] for n in r["nodes"]], [e["edge_id"] for e in r["edges"]]))
            graphs.append(model.graph("graphs/a.kg"))
    assert files[0] == files[1]                                   # same input twice: same bytes
    assert rows[0] == rows[2]                                     # reordered lines: identical ids, same row order
    assert {k: v for k, v in graphs[0].items() if k != "엣지"} == \
        {k: v for k, v in graphs[2].items() if k != "엣지"}           # same content as values ...
    assert sorted(graphs[0]["엣지"]) == sorted(graphs[2]["엣지"])
    assert not ordered_equal(graphs[0], graphs[2])                # ... with the source order kept as ordinals
    assert list(graphs[2]["공통층"]) == ["인원", "총액", "몫을안다"]
    assert graphs[2]["엣지"][0] == ["인원", "이어짐", "몫을안다"]
    assert node_id("graphs/a.kg", "인원") in rows[2][0]


UNREPRESENTABLE = {
    "name in two layers": ("역할: r\n목표: g\n[개념]\ng: \"x\"\nn: \"y\"\n[사례]\nn: \"z\"\n", "is in two layers"),
    "duplicate edge": ("역할: r\n목표: g\n[개념]\ng: \"x\"\nn: \"y\"\n[논증]\nn -증명-> g\nn -증명-> g\n",
                       "appears twice"),
    "text that does not parse": ("역할: r\n[개념]\nno colon here\n", "does not parse"),
    "edge part holding the separator byte 0x1F": ("역할: r\n목표: g\n[개념]\ng: \"x\"\na\x1fb: \"y\"\n[논증]\n"
                                                  "a\x1fb -증명-> g\n", "has no edge_id"),
    "NFC-equal names": ("역할: r\n목표: g\n[개념]\ng: \"x\"\n가: \"a\"\n가: \"b\"\n", "same node_id"),
}


@pytest.mark.parametrize("name", list(UNREPRESENTABLE))
def test_unrepresentable_graph_stays_source_text_only(name: str) -> None:
    text, reason = UNREPRESENTABLE[name]
    data = _build(_with_graph(text))
    with NativeModel.from_bytes(data) as model:
        model.verify_all()
        row = next(r for r in model.table_index() if r["member"] == "graphs/a.kg")
        assert row["status"] == "source-only" and reason in row["reason"]
        assert model.manifest["tables"]["source_only"] == ["graphs/a.kg"]
        with pytest.raises(mco.UnsupportedFormatError, match="source text only"):
            model.graph("graphs/a.kg")
        grph = model.member("graphs/a.kg").chunk
        assert grph.type == "GRPH" and grph.required                   # the text is what holds the graph
        assert model.member_bytes("graphs/a.kg") == text.encode()
        assert model.graph("graphs/b.kg")["목표"] == "greet"


def test_a_10_reader_reads_a_11_file_and_a_10_file_has_no_tables() -> None:
    data = _build()
    reader_10 = {kind: 1 for kind in TABLE_TYPES + MEMBER_TYPES}       # what a Format 1.0 reader knows
    with NativeModel(Container.from_bytes(data, known=reader_10)) as old, NativeModel.from_bytes(data) as new:
        old.verify_all()
        assert old.pack() == new.pack() and not old.has_tables and new.has_tables
    plain = _build(tables=False)
    with NativeModel.from_bytes(plain) as model:
        model.verify_all()
        assert not model.has_tables and "tables" not in model.manifest
        assert model.summary()["tables"] is None
        with pytest.raises(mco.UnsupportedFormatError, match="no graph tables"):
            model.graph("graphs/a.kg")


def _replace(chunks: list[Chunk], kind: str, mutate, nth: int = 0) -> list[Chunk]:
    out, seen = [], 0
    for c in chunks:
        if c.type == kind and seen == nth:
            c = Chunk(c.type, mutate(c.data), version=c.version, required=c.required, compression=c.compression)
        seen += c.type == kind
        out.append(c)
    return out


def _chunks() -> list[Chunk]:
    manifest, members = _pack_parts()
    payload = _payload()
    return build_chunks(manifest, members, source_sha256=hashlib.sha256(payload).hexdigest(),
                        source_bytes=len(payload), name="t", generator="test")


def _manifest(chunks: list[Chunk], **changes) -> list[Chunk]:
    from mco.native.pack import canonical_json
    manifest = json.loads(chunks[0].data)
    manifest.update(changes)
    return [Chunk("MANI", canonical_json(manifest), compression=0)] + chunks[1:]


TABLE_DAMAGE = {
    "valid": (lambda c: c, "ok"),
    "NODE rows do not fill the chunk": (lambda c: _replace(c, "NODE", lambda d: d + b"\x00" * 4), "ModelFormatError"),
    "NODE layer code out of range": (lambda c: _replace(c, "NODE", lambda d: d[:116] + b"\x09" + d[117:]),
                                     "ModelFormatError"),
    "EDGE stored id is not the edge's id": (lambda c: _replace(c, "EDGE", lambda d: d[:8] + b"\x00" * 16 + d[24:]),
                                            "ModelFormatError"),
    "EDGE kind unknown": (lambda c: _replace(c, "EDGE", lambda d: d[:36] + b"\x07" + d[37:]), "ModelFormatError"),
    "INDX row missing": (lambda c: _replace(c, "INDX", lambda d: struct.pack("<II", 1, 0) + d[8:44]),
                         "ModelFormatError"),
    "RULE payload not canonical": (lambda c: _replace(c, "RULE", lambda d: d[:-1] + b" "), "ModelFormatError"),
    "manifest table counts wrong": (lambda c: _manifest(c, tables=dict(json.loads(c[0].data)["tables"], nodes=99)),
                                    "ModelFormatError"),
    "NODE checksum": (None, "IntegrityError"),
    "RULE without INDX": (lambda c: [x for x in c if x.type not in ("INDX", "NODE", "EDGE")], "ModelFormatError"),
    "INDX without RULE": (lambda c: [x for x in c if x.type != "RULE"], "ModelFormatError"),
}


@pytest.mark.parametrize("name", list(TABLE_DAMAGE))
def test_damaged_tables_get_their_verdict(name: str) -> None:
    mutate, expected = TABLE_DAMAGE[name]
    if mutate is None:
        data = encode(_chunks())
        with NativeModel.from_bytes(data) as model:
            entry = next(e for e in model.container.entries if e.type == "NODE")
        data = data[:entry.offset + 3] + bytes([data[entry.offset + 3] ^ 0xFF]) + data[entry.offset + 4:]
    else:
        data = encode(mutate(_chunks()))
    assert _verdict(data) == expected


def test_writer_with_tables_is_deterministic(tmp_path: Path) -> None:
    first, second = tmp_path / "a.mco", tmp_path / "b.mco"
    write_native(first, _payload())
    write_native(second, _payload())
    assert first.read_bytes() == second.read_bytes()
    with NativeModel.open(first) as model:
        assert model.has_tables and model.manifest["format_version"] == [1, 1]


def test_edges_of_one_node_read_only_that_graphs_edge_chunk(full: Path) -> None:
    with NativeModel.open(full) as model:
        touched = 0
        for row in model.table_index():
            rows = model.graph_rows(row["graph_id"])
            for node in rows["nodes"]:
                want = [e for e in rows["edges"] if node["name"] in (e["src"], e["dst"])]
                assert model.node_edges(row["graph_id"], node["name"]) == want
                touched += bool(want)
        assert touched > 0
        assert model.node_edges(ALL_GRAPHS[0], "no such node") == []
    data = _build()

    class Counting(io.BytesIO):
        total = 0

        def read(self, size: int = -1) -> bytes:
            out = super().read(size)
            Counting.total += len(out)
            return out

    small = NativeModel(Container(Counting(data), len(data), known=KNOWN_CHUNKS))
    small.table_index()
    before = Counting.total
    assert [e["src"] for e in small.node_edges("graphs/a.kg", "몫을안다")] == ["총액"]
    row = next(r for r in small._index() if r.graph == "graphs/a.kg")
    assert Counting.total - before == small.container.entries[row.edge_chunk].length
