"""MCO Format 1 model layer: manifest, tables, and the mapping to a MARCO pack.

Implements ``docs/mco/format-1.md`` section 6 on top of
:mod:`mco.native.container`. Standard library only, no MARCO import: a pack is
handled as its manifest (a dict) and its members (path -> bytes).
"""
from __future__ import annotations

from bisect import bisect_left
from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import struct
from typing import Any, Optional, Union
import zipfile

from ..errors import CompileError, IntegrityError, ModelFormatError, UnsupportedFormatError
from . import tables as T
from .container import MAJOR, MINOR, Chunk, ChunkEntry, Container, encode, write_file
from .ids import edge_id, graph_id, node_id, rule_id
from .kgtext import KgTextError, parse_kg

__all__ = [
    "FEATURES", "MEMBER_TYPES", "TABLE_TYPES", "GRAPH_TABLE_TYPES", "RESERVED_TYPES", "KNOWN_CHUNKS",
    "SEMANTIC_SCHEMA", "Member", "NativeModel", "build_chunks", "write_model", "member_type",
    "content_identity", "canonical_json", "graph_id", "node_id", "edge_id", "rule_id", "kgpack_zip",
]

PathLike = Union[str, "os.PathLike[str]"]

#: Runtime features this reader can hand to its runtime (6.1).
FEATURES = ("marco.kg-text/1", "marco.pack-model/1")
SEMANTIC_SCHEMA = "marco-kgpack"
TABLE_TYPES = ("MANI", "STRS", "MEMB", "GDIR")
MEMBER_TYPES = ("GRPH", "LERN", "COLL", "LANG", "AXIM", "RELM", "DEFN", "ASET")
#: Format 1.1 graph and rule tables (6.8-6.11). Optional chunks: a 1.0 reader skips them.
GRAPH_TABLE_TYPES = ("INDX", "RULE", "NODE", "EDGE")
#: Reserved for later slices (section 8); this reader treats them as unknown.
RESERVED_TYPES = ("OVLY", "CHNG", "SNAP", "PROV")
KNOWN_CHUNKS = {kind: 1 for kind in TABLE_TYPES + MEMBER_TYPES + GRAPH_TABLE_TYPES}
#: What each chunk type is, as ``mco inspect`` labels it.
ROLES = {"MANI": "metadata", "STRS": "table", "MEMB": "table", "GDIR": "table", "INDX": "table",
         "RULE": "table", "NODE": "table", "EDGE": "table", "GRPH": "source text"}
_RESERVED_KEYS = ("base", "change_sequence", "snapshot")
_NULL = 0xFFFFFFFF
_HEX64 = re.compile(r"[0-9a-f]{64}")
_FROZEN_TIME = (1980, 1, 1, 0, 0, 0)

_STRS_HEAD = struct.Struct("<II")
_MEMB_HEAD = struct.Struct("<II")
_MEMB_ROW = struct.Struct("<IIB7sQ32s")
_GDIR_HEAD = struct.Struct("<8I")
_GDIR_NODE = struct.Struct("<5I")
_GDIR_EDGE = struct.Struct("<3I")
assert (_MEMB_ROW.size, _GDIR_HEAD.size, _GDIR_NODE.size, _GDIR_EDGE.size) == (56, 32, 20, 12)


# --- encoding helpers ---------------------------------------------------------------------

def canonical_json(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def content_identity(data: bytes) -> dict[str, Any]:
    """The per-member identity fields of a MARCO pack manifest entry (6.5)."""
    normal = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
    return {"sha256": hashlib.sha256(data).hexdigest(),
            "lf_normalized_sha256": hashlib.sha256(normal).hexdigest(),
            "line_endings": {"crlf": data.count(b"\r\n"),
                             "lf": data.count(b"\n") - data.count(b"\r\n"),
                             "cr": data.count(b"\r") - data.count(b"\r\n")}}


def member_type(path: str) -> str:
    """The chunk type that carries pack member ``path`` (section 6)."""
    parts = PurePosixPath(path).parts
    if path.endswith(".kg"):
        return "GRPH"
    if path.endswith(".학습.jsonl"):
        return "LERN"
    if path.endswith(".수집.jsonl"):
        return "COLL"
    if len(parts) == 2 and path.endswith(".json"):
        return {"styles": "LANG", "axioms": "AXIM", "models": "RELM"}.get(parts[0], "ASET")
    if path == "data/위키/정의문.jsonl":
        return "DEFN"
    return "ASET"


def _safe_member_path(path: str) -> bool:
    parts = path.split("/")
    return bool(path) and not path.startswith("/") and path != "manifest.json" \
        and all(p not in ("", ".", "..") for p in parts)


# --- writing --------------------------------------------------------------------------------

def _encode_strings(values: set[str]) -> tuple[bytes, dict[str, int]]:
    ordered = sorted(values, key=lambda v: v.encode("utf-8"))
    encoded = [v.encode("utf-8") for v in ordered]
    offsets = [0]
    for item in encoded:
        offsets.append(offsets[-1] + len(item))
    data = _STRS_HEAD.pack(len(encoded), 0) + struct.pack(f"<{len(offsets)}I", *offsets) + b"".join(encoded)
    return data, {v: i for i, v in enumerate(ordered)}


def _graph_tables(paths: list[str], members: Mapping[str, bytes]) -> dict[str, tuple[Optional[dict], Optional[str]]]:
    """Each graph member -> (parsed graph, None) when the tables can hold it
    exactly, or (None, reason) when it stays source text only."""
    out: dict[str, tuple[Optional[dict], Optional[str]]] = {}
    seen: dict[str, str] = {}
    for path in paths:
        if not path.endswith(".kg"):
            continue
        gid = graph_id(path)
        if gid in seen:
            raise CompileError(f"graph members {seen[gid]!r} and {path!r} have the same graph id")
        seen[gid] = path
        try:
            g = parse_kg(members[path], path)
        except KgTextError as exc:
            out[path] = (None, "the graph text does not parse: " + str(exc).splitlines()[0])
            continue
        reason = T.unrepresentable(path, g)
        out[path] = (None, reason) if reason else (g, None)
    return out


def build_chunks(pack_manifest: Mapping[str, Any], members: Mapping[str, bytes], *, source_sha256: str,
                 source_bytes: int, name: Optional[str] = None, build_id: Optional[str] = None,
                 generator: str = "", tables: bool = True) -> list[Chunk]:
    """The chunks of a Format 1 file for a MARCO pack (manifest + members).

    With ``tables`` (the default) the file also holds the node, edge, graph
    index and rule tables of Format 1.1 (6.8-6.11); every graph's source text
    stays as a ``GRPH`` member chunk. Raises :class:`CompileError` when the
    pack holds something Format 1 cannot represent; the caller then gets no
    file rather than a lossy one.
    """
    paths = sorted(members, key=lambda p: p.encode("utf-8"))
    for path in paths:
        if not _safe_member_path(path):
            raise CompileError(f"unsafe pack member path {path!r}")
    manager = pack_manifest.get("manager")
    if not isinstance(manager, Mapping) or not isinstance(manager.get("nodes"), list) \
            or not isinstance(manager.get("edges"), list):
        raise CompileError("the pack has no manager graph Format 1 can store")
    strings: set[str] = set(paths) | {str(manager.get("format")), str(manager.get("role")),
                                      str(manager.get("goal"))}
    for node in manager["nodes"]:
        strings |= {str(node.get("path")), str(node.get("role")), str(node.get("goal"))}
        strings |= {str(e) for e in node.get("examples", [])}
    for edge in manager["edges"]:
        strings |= {str(x) for x in edge}
    graphs = _graph_tables(paths, members) if tables else {}
    rules: list[tuple[str, dict]] = []
    if tables:
        try:
            rules = T.pack_rules(pack_manifest, members)
        except (KeyError, ValueError) as exc:
            raise CompileError(f"the pack's axiom rules cannot be read: {exc}") from exc
        for path, (g, reason) in graphs.items():
            strings |= {graph_id(path)} | (T.graph_strings(g) if g is not None else {reason})
        strings |= {T.rule_id(rule) for _, rule in rules} | {source for source, _ in rules}
    strs, sid = _encode_strings(strings)

    member_chunks: list[Chunk] = []
    rows = bytearray(_MEMB_HEAD.pack(len(paths), 0))
    for row, path in enumerate(paths):
        body = members[path]
        rows += _MEMB_ROW.pack(sid[path], len(TABLE_TYPES) + row, 1 if path.endswith(".kg") else 0,
                               b"\x00" * 7, len(body), hashlib.sha256(body).digest())
        # A graph the tables hold exactly keeps its text as an optional source-text chunk.
        tabled = graphs.get(path, (None, None))[0] is not None
        member_chunks.append(Chunk(member_type(path), body, required=not tabled))

    nodes, examples, edges = bytearray(), bytearray(), bytearray()
    count = 0
    for node in manager["nodes"]:
        items = [str(e) for e in node.get("examples", [])]
        nodes += _GDIR_NODE.pack(sid[str(node.get("path"))], sid[str(node.get("role"))],
                                 sid[str(node.get("goal"))], count, len(items))
        examples += struct.pack(f"<{len(items)}I", *(sid[e] for e in items))
        count += len(items)
    for edge in manager["edges"]:
        if not isinstance(edge, (list, tuple)) or len(edge) != 3:
            raise CompileError(f"manager edge {edge!r} is not a triple")
        edges += _GDIR_EDGE.pack(*(sid[str(x)] for x in edge))
    version = manager.get("version")
    if not isinstance(version, int) or isinstance(version, bool) or not 0 <= version < _NULL:
        raise CompileError(f"manager version {version!r} is not an integer")
    gdir = _GDIR_HEAD.pack(sid[str(manager.get("format"))], version, sid[str(manager.get("role"))],
                           sid[str(manager.get("goal"))], len(manager["nodes"]), len(manager["edges"]),
                           count, 0) + bytes(nodes) + bytes(examples) + bytes(edges)

    table_chunks: list[Chunk] = []
    table_counts = None
    if tables:
        first = len(TABLE_TYPES) + len(paths) + 2              # after the members, INDX and RULE
        index_rows, pairs = [], []
        for path in sorted(graphs, key=lambda p: graph_id(p).encode("utf-8")):
            g, reason = graphs[path]
            gid = graph_id(path)
            if g is None:
                index_rows.append(T.IndexRow(gid, path, T.SOURCE_ONLY, reason, None, None, 0, 0, 0))
                continue
            node = T.encode_node(path, g, sid)
            edge = T.encode_edge(path, g, sid)
            at = first + len(pairs)
            nodes = len(T.node_names(g))
            index_rows.append(T.IndexRow(gid, path, T.TABLES, None, at, at + 1, nodes,
                                         len(g["엣지"]) + len(g["개념엣지"]),
                                         sum(len(x) for layer in T.LAYER_KEYS for x in g[layer].values())))
            pairs += [Chunk("NODE", node, required=False, compression=0),
                      Chunk("EDGE", edge, required=False, compression=0)]
        table_chunks = [Chunk("INDX", T.encode_index(index_rows, sid), required=False, compression=0),
                        Chunk("RULE", T.encode_rules(rules, sid), required=False, compression=0)] + pairs
        table_counts = _table_counts(index_rows, len(rules))

    model = pack_manifest.get("model")
    languages = [p for p in paths if member_type(p) == "LANG"]
    content = hashlib.sha256(canonical_json(pack_manifest) + b"\n").hexdigest()
    manifest = {
        "format": "mco", "format_version": [MAJOR, MINOR], "name": name,
        "build_id": build_id or "sha256-" + source_sha256[:12], "content_sha256": content,
        "generator": generator,
        "semantic_schema": {"id": SEMANTIC_SCHEMA, "version": pack_manifest.get("version")},
        "requires": sorted(FEATURES), "runtime": {"backend": "mco-native"},
        "source": {"kind": "kgpack", "bytes": source_bytes, "sha256": source_sha256},
        "model": model, "language": (model or {}).get("language") if isinstance(model, Mapping) else None,
        "languages": languages,
        "counts": {"members": len(paths), "graphs": sum(p.endswith(".kg") for p in paths),
                   "manager_nodes": len(manager["nodes"]), "strings": len(sid)},
        "base": None, "change_sequence": None, "snapshot": None,
        "supports": {"overlay": False, "snapshot": False},
    }
    if table_counts is not None:
        manifest["tables"] = table_counts
    chunks = [Chunk("MANI", canonical_json(manifest), compression=0), Chunk("STRS", strs, compression=0),
              Chunk("MEMB", bytes(rows), compression=0), Chunk("GDIR", gdir, compression=0)] \
        + member_chunks + table_chunks
    # Self-check: what a reader rebuilds must be the pack we were given, and
    # every tabled graph and rule must read back exactly as parsed.
    try:
        rebuilt = NativeModel(Container.from_bytes(encode(chunks), name="<new file>", known=KNOWN_CHUNKS))
        same = rebuilt.pack_manifest() == pack_manifest
        if tables:
            for path, (g, _reason) in graphs.items():
                if g is not None and not T.ordered_equal(rebuilt.graph(graph_id(path)), g):
                    raise CompileError(f"graph {path} does not read back from the tables identically")
            # Rule objects compare as values: canonical JSON stores their keys sorted (6.11).
            if rebuilt.rules() != [rule for _, rule in rules]:
                raise CompileError("the rules do not read back from the rule table identically")
    except ModelFormatError as exc:
        raise CompileError(f"the pack cannot be stored in Format 1: {exc}") from exc
    if not same:
        raise CompileError("the pack holds data Format 1 does not represent "
                           "(its manifest does not rebuild identically)")
    return chunks


def _table_counts(rows: list[T.IndexRow], rules: int) -> dict[str, Any]:
    """The manifest's ``tables`` object (6.1), from the ``INDX`` rows and the rule count."""
    tabled = [r for r in rows if r.status == T.TABLES]
    return {"graphs": len(rows), "tabled": len(tabled),
            "source_only": sorted(r.member for r in rows if r.status == T.SOURCE_ONLY),
            "nodes": sum(r.nodes for r in tabled), "edges": sum(r.edges for r in tabled),
            "examples": sum(r.examples for r in tabled), "rules": rules}


def write_model(output: PathLike, pack_manifest: Mapping[str, Any], members: Mapping[str, bytes],
                **kwargs: Any) -> dict[str, Any]:
    """Write a Format 1 file for a pack. Returns the ``MANI`` manifest."""
    chunks = build_chunks(pack_manifest, members, **kwargs)
    write_file(output, encode(chunks))
    return json.loads(chunks[0].data)


def kgpack_zip(manifest: Mapping[str, Any], members: Mapping[str, bytes]) -> bytes:
    """A deterministic MARCO pack ZIP: the same bytes MARCO's pack writer gives."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for name, data in [("manifest.json", canonical_json(manifest) + b"\n")] + \
                [(n, members[n]) for n in sorted(members)]:
            info = zipfile.ZipInfo(name, _FROZEN_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            zf.writestr(info, data)
    return buffer.getvalue()


# --- reading -----------------------------------------------------------------------------

def _reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    keys = [k for k, _ in pairs]
    if len(keys) != len(set(keys)):
        raise ValueError("duplicate key")
    return dict(pairs)


def _reject_constant(name: str) -> Any:
    raise ValueError(f"{name} is not allowed")


class _Strings:
    """The ``STRS`` table, validated once, strings decoded on demand."""

    def __init__(self, data: bytes, fail) -> None:
        if len(data) < _STRS_HEAD.size:
            raise fail("STRS: too short")
        count, reserved = _STRS_HEAD.unpack_from(data)
        if reserved:
            raise fail("STRS: reserved field is not zero")
        head = _STRS_HEAD.size + 4 * (count + 1)
        if head > len(data):
            raise fail(f"STRS: absurd string count {count} for {len(data)} bytes")
        offsets = struct.unpack_from(f"<{count + 1}I", data, _STRS_HEAD.size)
        if offsets[0] != 0 or head + offsets[-1] != len(data):
            raise fail("STRS: offsets do not cover the data exactly")
        if any(offsets[i] > offsets[i + 1] for i in range(count)):
            raise fail("STRS: offsets decrease")
        blob = data[head:]
        try:
            blob.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise fail(f"STRS: not UTF-8 ({exc})") from exc
        # A string boundary may not split a character; with the whole blob valid
        # UTF-8, that makes every single string valid UTF-8.
        if any(o < len(blob) and 0x80 <= blob[o] <= 0xBF for o in offsets):
            raise fail("STRS: a string boundary splits a UTF-8 character")
        for i in range(count - 1):
            if blob[offsets[i]:offsets[i + 1]] >= blob[offsets[i + 1]:offsets[i + 2]]:
                raise fail("STRS: strings are not unique and sorted")
        self._blob, self._offsets, self._fail = blob, offsets, fail
        self._decoded: dict[int, str] = {}
        self.count = count

    def __len__(self) -> int:
        return self.count

    def get(self, index: int, where: str) -> str:
        try:
            return self._decoded[index]
        except KeyError:
            pass
        if not 0 <= index < self.count:
            raise self._fail(f"{where}: string id {index} out of range ({self.count} strings)")
        text = self._decoded[index] = self._blob[self._offsets[index]:self._offsets[index + 1]].decode("utf-8")
        return text


@dataclass(frozen=True)
class Member:
    """One ``MEMB`` row."""

    path: str
    chunk: ChunkEntry
    graph: bool
    bytes: int
    sha256: bytes

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "kind": "graph" if self.graph else "asset", "type": self.chunk.type,
                "bytes": self.bytes, "stored": self.chunk.length, "sha256": self.sha256.hex()}


class NativeModel:
    """A Format 1 file opened at the *open* verification level (section 7).

    Opening reads the header, the TOC and the four table chunks. Member bytes
    are read one chunk at a time by :meth:`member_bytes`.
    """

    def __init__(self, container: Container) -> None:
        self.container = container
        self.name = container.name
        try:
            self._load()
        except BaseException:
            container.close()
            raise

    @classmethod
    def open(cls, path: PathLike) -> "NativeModel":
        return cls(Container.open(path, known=KNOWN_CHUNKS))

    @classmethod
    def from_bytes(cls, data: bytes, *, name: str = "<bytes>") -> "NativeModel":
        return cls(Container.from_bytes(data, name=name, known=KNOWN_CHUNKS))

    def close(self) -> None:
        self.container.close()

    def __enter__(self) -> "NativeModel":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def major(self) -> int:
        return self.container.major

    @property
    def minor(self) -> int:
        return self.container.minor

    def _fail(self, message: str, cls: type = ModelFormatError) -> Exception:
        return cls(f"{self.name}: {message}")

    def _single(self, kind: str) -> ChunkEntry:
        found = [e for e in self.container.of_type(kind) if self.container.understands(e)]
        if len(found) != 1:
            raise self._fail(f"{kind} must appear exactly once, found {len(found)}")
        return found[0]

    def _load(self) -> None:
        chunks = {kind: self._single(kind) for kind in TABLE_TYPES}
        self.manifest = self._read_manifest(self.container.read(chunks["MANI"]))
        self.strings = _Strings(self.container.read(chunks["STRS"]), self._fail)
        self.members = self._read_members(self.container.read(chunks["MEMB"]))
        self._paths = [m.path.encode("utf-8") for m in self.members]
        self._manager = self._read_manager(self.container.read(chunks["GDIR"]))
        counts = self.manifest.get("counts")
        expected = {"members": len(self.members), "graphs": sum(m.graph for m in self.members),
                    "manager_nodes": len(self._manager["nodes"]), "strings": len(self.strings)}
        if counts != expected:
            raise self._fail(f"manifest counts {counts} disagree with the tables {expected}")

    def _read_manifest(self, data: bytes) -> dict[str, Any]:
        try:
            manifest = json.loads(data.decode("utf-8"), object_pairs_hook=_reject_duplicates,
                                  parse_constant=_reject_constant)
        except (UnicodeDecodeError, ValueError) as exc:
            raise self._fail(f"MANI: not a valid JSON manifest ({exc})") from exc
        if not isinstance(manifest, dict) or manifest.get("format") != "mco":
            raise self._fail("MANI: not an MCO manifest (format must be 'mco')")
        if manifest.get("format_version") != [self.major, self.minor]:
            raise self._fail(f"MANI: format_version {manifest.get('format_version')!r} does not match "
                             f"the header ({self.major}.{self.minor})")
        requires = manifest.get("requires")
        if not isinstance(requires, list) or not all(isinstance(f, str) for f in requires):
            raise self._fail("MANI: requires must be a list of strings")
        unknown = sorted(set(requires) - set(FEATURES))
        if unknown:
            raise self._fail(f"requires runtime feature(s) this reader does not have: {unknown}",
                             UnsupportedFormatError)
        for key in _RESERVED_KEYS:
            if manifest.get(key) is not None:
                raise self._fail(f"manifest sets {key!r}, which needs overlay/snapshot support "
                                 "this version does not have", UnsupportedFormatError)
        supports = manifest.get("supports", {})
        if not isinstance(supports, dict):
            raise self._fail("MANI: supports must be an object")
        claimed = sorted(k for k, v in supports.items() if v is not False)
        if claimed:
            raise self._fail(f"manifest claims support for {claimed}, which this version does not have",
                             UnsupportedFormatError)
        schema = manifest.get("semantic_schema")
        if not isinstance(schema, dict) or not isinstance(schema.get("version"), int):
            raise self._fail("MANI: semantic_schema must be an object with an integer version")
        if schema.get("id") != SEMANTIC_SCHEMA:
            raise self._fail(f"semantic schema {schema.get('id')!r} is not known to this reader",
                             UnsupportedFormatError)
        if not isinstance(manifest.get("build_id"), str) or not manifest["build_id"]:
            raise self._fail("MANI: build_id must be a non-empty string")
        if not isinstance(manifest.get("content_sha256"), str) or not _HEX64.fullmatch(manifest["content_sha256"]):
            raise self._fail("MANI: content_sha256 must be 64 lowercase hex digits")
        if manifest.get("model") is not None and not isinstance(manifest.get("model"), dict):
            raise self._fail("MANI: model must be an object or null")
        languages = manifest.get("languages", [])
        if not isinstance(languages, list) or not all(isinstance(x, str) for x in languages):
            raise self._fail("MANI: languages must be a list of strings")
        return manifest

    def _read_members(self, data: bytes) -> list[Member]:
        if len(data) < _MEMB_HEAD.size:
            raise self._fail("MEMB: too short")
        count, reserved = _MEMB_HEAD.unpack_from(data)
        if reserved or _MEMB_HEAD.size + count * _MEMB_ROW.size != len(data):
            raise self._fail(f"MEMB: {count} rows do not fill {len(data)} bytes exactly")
        members: list[Member] = []
        used: set[int] = set()
        entries = self.container.entries
        for row in range(count):
            path_sid, chunk, kind, pad, size, sha = _MEMB_ROW.unpack_from(data, _MEMB_HEAD.size + row * _MEMB_ROW.size)
            where = f"MEMB row {row}"
            path = self.strings.get(path_sid, where)
            if pad != b"\x00" * 7 or kind not in (0, 1):
                raise self._fail(f"{where}: reserved bytes or kind invalid")
            if not _safe_member_path(path):
                raise self._fail(f"{where}: unsafe member path {path!r}")
            if bool(kind) != path.endswith(".kg"):
                raise self._fail(f"{where}: kind does not match path {path!r}")
            if members and members[-1].path.encode("utf-8") >= path.encode("utf-8"):
                raise self._fail(f"{where}: paths are not unique and sorted")
            if not 0 <= chunk < len(entries) or entries[chunk].type not in MEMBER_TYPES \
                    or not self.container.understands(entries[chunk]) or chunk in used:
                raise self._fail(f"{where}: chunk {chunk} is not an unused member chunk")
            if entries[chunk].raw_length != size:
                raise self._fail(f"{where}: size {size} differs from the chunk's raw_length")
            used.add(chunk)
            members.append(Member(path, entries[chunk], bool(kind), size, sha))
        orphans = [e.index for e in entries if e.type in MEMBER_TYPES and e.index not in used]
        if orphans:
            raise self._fail(f"member chunk(s) {orphans} are not in MEMB")
        if not any(m.graph for m in members):
            raise self._fail("MEMB: the model has no graph")
        return members

    def _read_manager(self, data: bytes) -> dict[str, Any]:
        if len(data) < _GDIR_HEAD.size:
            raise self._fail("GDIR: too short")
        fmt, version, role, goal, n_nodes, n_edges, n_examples, reserved = _GDIR_HEAD.unpack_from(data)
        size = _GDIR_HEAD.size + n_nodes * _GDIR_NODE.size + 4 * n_examples + n_edges * _GDIR_EDGE.size
        if reserved or size != len(data):
            raise self._fail(f"GDIR: counts ({n_nodes} nodes, {n_examples} examples, {n_edges} edges) "
                             f"do not fill {len(data)} bytes exactly")
        s = self.strings.get
        base = _GDIR_HEAD.size + n_nodes * _GDIR_NODE.size
        examples = struct.unpack_from(f"<{n_examples}I", data, base)
        graphs = {m.path for m in self.members if m.graph}
        nodes, seen, expected = [], set(), 0
        for index in range(n_nodes):
            path, n_role, n_goal, first, count = _GDIR_NODE.unpack_from(data, _GDIR_HEAD.size + index * _GDIR_NODE.size)
            where = f"GDIR node {index}"
            name = s(path, where)
            if name not in graphs or name in seen:
                raise self._fail(f"{where}: {name!r} is not a graph member, or repeats")
            if first != expected:
                raise self._fail(f"{where}: examples start at {first}, expected {expected}")
            expected += count
            if expected > n_examples:
                raise self._fail(f"{where}: examples run past {n_examples}")
            seen.add(name)
            nodes.append({"path": name, "role": s(n_role, where), "goal": s(n_goal, where),
                          "examples": [s(e, where) for e in examples[first:first + count]]})
        if expected != n_examples:
            raise self._fail(f"GDIR: nodes use {expected} of {n_examples} examples")
        edge_base = base + 4 * n_examples
        edges = [[s(x, f"GDIR edge {i}") for x in _GDIR_EDGE.unpack_from(data, edge_base + i * _GDIR_EDGE.size)]
                 for i in range(n_edges)]
        return {"format": s(fmt, "GDIR"), "version": version, "role": s(role, "GDIR"), "goal": s(goal, "GDIR"),
                "nodes": nodes, "edges": edges}

    # -- access -------------------------------------------------------------------------------

    def member(self, path: str) -> Member:
        key = path.encode("utf-8")
        index = bisect_left(self._paths, key)
        if index == len(self._paths) or self._paths[index] != key:
            raise KeyError(path)
        return self.members[index]

    def member_bytes(self, path: str) -> bytes:
        """One member's bytes. Reads only that member's chunk; checks both checksums."""
        member = self.member(path)
        data = self.container.read(member.chunk)
        if hashlib.sha256(data).digest() != member.sha256:
            raise self._fail(f"member {path}: SHA-256 mismatch", IntegrityError)
        return data

    def manager(self) -> dict[str, Any]:
        return json.loads(json.dumps(self._manager))

    def graph_ids(self) -> list[str]:
        return [graph_id(m.path) for m in self.members if m.graph]

    def pack_manifest(self, bodies: Optional[Mapping[str, bytes]] = None) -> dict[str, Any]:
        """The MARCO pack manifest rebuilt from the tables (6.5). Reads every member."""
        files = []
        for member in self.members:
            body = bodies[member.path] if bodies is not None else self.member_bytes(member.path)
            files.append({"path": member.path, "kind": "graph" if member.graph else "asset",
                          "bytes": member.bytes, **content_identity(body)})
        return {"format": "nai-kgpack", "version": self.manifest["semantic_schema"]["version"],
                "files": files, "manager": self.manager(), "model": self.manifest.get("model")}

    def pack(self) -> tuple[dict[str, Any], dict[str, bytes]]:
        bodies = {m.path: self.member_bytes(m.path) for m in self.members}
        return self.pack_manifest(bodies), bodies

    def kgpack_bytes(self) -> bytes:
        """The MARCO pack this file holds, as a deterministic ``.kgpack`` ZIP."""
        manifest, bodies = self.pack()
        return kgpack_zip(manifest, bodies)

    def content_sha256(self) -> str:
        """Recompute 6.6 from the member bytes."""
        return hashlib.sha256(canonical_json(self.pack_manifest()) + b"\n").hexdigest()

    def verify_all(self) -> None:
        """Full verification (section 7), including every graph and rule table."""
        self.container.verify_all()
        if self.content_sha256() != self.manifest["content_sha256"]:
            raise self._fail("content_sha256 does not match the members", IntegrityError)
        if self.has_tables:
            for row in self._index():
                if row.status == T.TABLES:
                    nodes, edges = self._graph_chunks(row)
                    T.build_graph(nodes, edges, self.strings.get, self._fail, f"tables of {row.graph}")
                    T.check_edge_ids(row, edges, self.strings.get, self._fail)
            self.rule_rows()

    # -- graph and rule tables (Format 1.1, sections 6.8-6.11) ------------------------------------
    # Plain-data reader for the next step; the running path does not use it yet.

    def _optional(self, kind: str) -> Optional[ChunkEntry]:
        found = [e for e in self.container.of_type(kind) if self.container.understands(e)]
        if len(found) > 1:
            raise self._fail(f"{kind} must appear at most once, found {len(found)}")
        return found[0] if found else None

    @property
    def has_tables(self) -> bool:
        """Whether the file holds graph tables (an ``INDX`` chunk). 1.0 files do not."""
        return self._optional("INDX") is not None

    def _index(self) -> list[T.IndexRow]:
        """The ``INDX`` rows, read and checked once (6.8)."""
        cached = getattr(self, "_index_rows", None)
        if cached is not None:
            return cached
        entry = self._optional("INDX")
        typed = [e for e in self.container.entries if e.type in ("NODE", "EDGE")]
        if entry is None:
            if typed or self.manifest.get("tables") is not None:
                raise self._fail("NODE/EDGE chunks or a manifest 'tables' object without an INDX chunk")
            raise UnsupportedFormatError(f"{self.name}: this file has no graph tables (Format 1.0)")
        rows = T.decode_index(self.container.read(entry), self.strings.get, self._fail)
        graphs = sorted(m.path for m in self.members if m.graph)
        if sorted(r.member for r in rows) != graphs:
            raise self._fail("INDX rows are not exactly the graph members of MEMB")
        used: set[int] = set()
        entries = self.container.entries
        for row in rows:
            if row.status != T.TABLES:
                continue
            for index, kind in ((row.node_chunk, "NODE"), (row.edge_chunk, "EDGE")):
                if not 0 <= index < len(entries) or entries[index].type != kind or index in used \
                        or not self.container.understands(entries[index]):
                    raise self._fail(f"INDX row {row.graph}: chunk {index} is not an unused {kind} chunk")
                used.add(index)
        orphans = [e.index for e in typed if e.index not in used]
        if orphans:
            raise self._fail(f"NODE/EDGE chunk(s) {orphans} are not in INDX")
        rule = self._optional("RULE")
        if rule is None:
            raise self._fail("an INDX chunk without a RULE chunk")
        rule_count = struct.unpack_from("<I", self.container.read(rule))[0] if rule.raw_length >= 4 else -1
        if self.manifest.get("tables") != _table_counts(rows, rule_count):
            raise self._fail(f"manifest tables {self.manifest.get('tables')} disagree with INDX/RULE")
        self._index_rows = rows
        self._index_keys = [r.graph.encode("utf-8") for r in rows]
        return rows

    def _row(self, graph: str) -> T.IndexRow:
        rows = self._index()
        key = graph_id(graph).encode("utf-8")
        at = bisect_left(self._index_keys, key)
        if at == len(rows) or self._index_keys[at] != key:
            raise KeyError(graph)
        return rows[at]

    def _graph_chunks(self, row: T.IndexRow) -> tuple[T.NodeTable, T.EdgeTable]:
        entries = self.container.entries
        nodes = T.decode_node(self.container.read(entries[row.node_chunk]), row, self.strings.get, self._fail)
        edges = T.decode_edge(self.container.read(entries[row.edge_chunk]), row, self.strings.get, self._fail)
        return nodes, edges

    def _tabled(self, graph: str) -> T.IndexRow:
        row = self._row(graph)
        if row.status != T.TABLES:
            raise UnsupportedFormatError(f"{self.name}: graph {row.graph} is carried as source text only "
                                         f"({row.reason})")
        return row

    def table_index(self) -> list[dict[str, Any]]:
        """Every graph's ``INDX`` row as plain data, sorted by graph id. Reads only ``INDX``."""
        return [r.to_dict() for r in self._index()]

    def graph(self, graph: str) -> dict[str, Any]:
        """One graph, in exactly the shape MARCO's ``read_kg`` returns for its
        source text (without the shared hypernym merge of ``data/개념망.json``).
        Reads only that graph's ``NODE`` and ``EDGE`` chunks (and ``INDX``
        once). ``KeyError`` for an unknown graph id; ``UnsupportedFormatError``
        for a graph carried as source text only."""
        row = self._tabled(graph)
        nodes, edges = self._graph_chunks(row)
        return T.build_graph(nodes, edges, self.strings.get, self._fail, f"tables of {row.graph}")

    def graph_rows(self, graph: str) -> dict[str, Any]:
        """One graph's rows with their stable ids (node_id, edge_id) and ordinal
        fields, as plain data in stored order."""
        row = self._tabled(graph)
        nodes, edges = self._graph_chunks(row)
        return T.graph_rows(row, nodes, edges, self.strings.get)

    def node_edges(self, graph: str, name: str) -> list[dict[str, Any]]:
        """The edges of one graph that touch node ``name`` (as source or
        destination), both lists (``엣지`` and ``개념엣지``), as plain rows with
        their ``edge_id``, in stored (edge id) order. Reads only that graph's
        ``EDGE`` chunk (and ``INDX`` once). ``name`` is matched as stored, the
        name ``read_kg`` returns; an unknown name gives an empty list."""
        row = self._tabled(graph)
        entries = self.container.entries
        edges = T.decode_edge(self.container.read(entries[row.edge_chunk]), row, self.strings.get, self._fail)
        return T.edges_touching(edges, name, self.strings.get)

    def rule_rows(self) -> list[dict[str, Any]]:
        """The ``RULE`` rows, sorted by rule id: ``rule_id``, ``source``, ``ordinal``, ``rule``."""
        self._index()
        entry = self._optional("RULE")
        return T.decode_rules(self.container.read(entry), self.strings.get, self._fail)

    def rules(self) -> list[dict[str, Any]]:
        """The model's rules in the order MARCO collects them (ordinal order)."""
        return [r["rule"] for r in sorted(self.rule_rows(), key=lambda r: r["ordinal"])]

    def tables_summary(self) -> Optional[dict[str, Any]]:
        """Graph, node, edge, example and rule counts from ``INDX`` and the
        manifest (checked against each other), or ``None`` for a 1.0 file."""
        if not self.has_tables:
            return None
        rows = self._index()
        return dict(self.manifest["tables"],
                    source_only_reasons={r.member: r.reason for r in rows if r.status == T.SOURCE_ONLY})

    def summary(self) -> dict[str, Any]:
        """What ``mco inspect`` shows: header, chunks with sizes and roles,
        members, table counts. Reads ``INDX`` and ``RULE`` but no graph table."""
        return {"format": {"major": self.major, "minor": self.minor, "flags": self.container.flags,
                           "file_size": self.container.size},
                "chunks": [dict(e.to_dict(), understood=self.container.understands(e),
                                role=ROLES.get(e.type, "carried member" if e.type in MEMBER_TYPES else "unknown"))
                           for e in self.container.entries],
                "members": [m.to_dict() for m in self.members],
                "tables": self.tables_summary()}
