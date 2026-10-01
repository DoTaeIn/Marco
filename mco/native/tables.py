"""The node, edge, graph-index and rule tables of MCO Format 1.1.

Layouts are fixed in ``docs/mco/format-1.md`` section 6.8 to 6.11. This module
encodes a parsed graph (the dictionary :func:`mco.native.kgtext.parse_kg`
returns, which is the dictionary MARCO's ``read_kg`` returns) into one ``NODE``
and one ``EDGE`` chunk, the per-graph directory ``INDX`` and the ``RULE``
table, and decodes them back.

Every row is keyed by a stable identifier (``node_id``, ``edge_id``,
``rule_id``, ``graph_id``) and sorted by it. Where the engine depends on source
order (dictionary insertion order, list order), the row carries an explicit
``ordinal`` field; nothing is identified by its position.

Standard library only, no MARCO import.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
import json
import struct
from typing import Any, Optional
import unicodedata

from .ids import edge_id, graph_id, node_id, rule_id
from .kgtext import LAYER_KEYS, SLOT_KEYS, TOP_KEYS

__all__ = [
    "NULL", "LAYER_CODE", "SLOT_CODE", "LIST_KEYS", "ARGUMENT", "CONCEPT", "TABLES", "SOURCE_ONLY",
    "IndexRow", "node_names", "unrepresentable", "graph_strings", "encode_node", "encode_edge", "encode_index",
    "encode_rules", "pack_rules", "decode_index", "NodeTable", "EdgeTable", "decode_node", "decode_edge",
    "build_graph", "graph_rows", "edges_touching", "decode_rules", "check_edge_ids", "ordered_equal",
]

NULL = 0xFFFFFFFF
LAYER_CODE = {"공통층": 1, "사례층": 2, "무관층": 3}
SLOT_CODE = {key: code for code, key in enumerate(SLOT_KEYS, 1)}     # 수치조건 1 ... 출처 7
LIST_KEYS = ("전진관계", "부정관계", "근거관계", "포함", "공리", "맡음")
ARGUMENT, CONCEPT = 1, 2            # EDGE kind: 엣지 (논증), 개념엣지 (개념망)
EDGE_LIST = {ARGUMENT: "엣지", CONCEPT: "개념엣지"}
TABLES, SOURCE_ONLY = 1, 2          # INDX status
F_GROUNDS, F_DUTIES, F_DUTIES_FIRST = 0x1, 0x2, 0x4   # NODE graph-record flags
_BOUND = {"최소": 1, "최대": 2}
_BOUND_NAME = {1: "최소", 2: "최대"}

_INDX_HEAD = struct.Struct("<II")
_INDX_ROW = struct.Struct("<IIB3sIIIIII")
_NODE_HEAD = struct.Struct("<6Idd6I")
_NODE_LISTS = struct.Struct("<12I")
_NODE_ROW = struct.Struct("<IBBHIIII")
_SLOT = struct.Struct("<BBHIIId")
_EDGE_HEAD = struct.Struct("<II")
_EDGE_ROW = struct.Struct("<16sIIIB3sI")
_RULE_HEAD = struct.Struct("<II")
_RULE_ROW = struct.Struct("<5I")
assert (_INDX_ROW.size, _NODE_HEAD.size, _NODE_LISTS.size, _NODE_ROW.size, _SLOT.size, _EDGE_ROW.size,
        _RULE_ROW.size) == (36, 64, 48, 24, 24, 36, 20)

Fail = Callable[[str], Exception]


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def ordered_equal(a: Any, b: Any) -> bool:
    """Equal values of equal types, with dictionary key order compared too."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return list(a) == list(b) and all(ordered_equal(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(ordered_equal(x, y) for x, y in zip(a, b))
    return a == b


# --- writing ----------------------------------------------------------------------------------

def node_names(g: Mapping[str, Any]) -> dict[str, tuple[int, int]]:
    """Every node name -> (layer code, ordinal in that layer); 0, 0 for slot-only names."""
    names: dict[str, tuple[int, int]] = {}
    for layer in LAYER_KEYS:
        for ordinal, name in enumerate(g[layer]):
            names.setdefault(name, (LAYER_CODE[layer], ordinal))
    for slot in SLOT_KEYS:
        for name in g.get(slot) or {}:
            names.setdefault(name, (0, 0))
    return names


def unrepresentable(path: str, g: Mapping[str, Any]) -> Optional[str]:
    """Why graph ``g`` cannot be stored in the tables exactly, or ``None``."""
    if list(g)[:len(TOP_KEYS)] != list(TOP_KEYS) or set(g) - set(TOP_KEYS) - {"근거관계", "맡음", "출처"}:
        return "unexpected top-level keys"
    seen: dict[str, str] = {}
    for layer in LAYER_KEYS:
        for name in g[layer]:
            if name in seen:
                return f"node name {name!r} is in two layers ({seen[name]}, {layer})"
            seen[name] = layer
    ids: dict[str, str] = {}
    for name in node_names(g):
        key = _nfc(name)
        if key in ids and ids[key] != name:
            return f"node names {ids[key]!r} and {name!r} have the same node_id"
        ids[key] = name
    edges: set[str] = set()
    for kind, key in EDGE_LIST.items():
        for edge in g[key]:
            if not (isinstance(edge, list) and len(edge) == 3 and all(isinstance(x, str) for x in edge)):
                return f"{key} item {edge!r} is not three strings"
            try:
                eid = edge_id(path, *edge)
            except ValueError as exc:              # e.g. a part holding the separator byte 0x1F
                return f"edge {edge!r} has no edge_id ({exc})"
            if eid in edges:
                return f"edge {edge!r} appears twice (one edge_id)"
            edges.add(eid)
    return None


def graph_strings(g: Mapping[str, Any]) -> set[str]:
    """Every string the tables of ``g`` refer to."""
    out = {g["역할"], g["목표"], g["이름말"], g["색인"], g["언어"]}
    out |= set(node_names(g))
    for key in LIST_KEYS:
        out |= set(g.get(key) or ())
    for k, v in g["대사"].items():
        out |= {k, v}
    for layer in LAYER_KEYS:
        for examples in g[layer].values():
            out |= set(examples)
    for slot in SLOT_KEYS:
        for value in (g.get(slot) or {}).values():
            if slot == "수치조건":
                out.add(value["단위"])
            elif isinstance(value, tuple):
                out |= set(value)
            else:
                out.add(value)
    for key in EDGE_LIST.values():
        for edge in g[key]:
            out |= set(edge)
    return out


def _slot_record(slot: str, ordinal: int, value: Any, sid: Mapping[str, int]) -> bytes:
    code = SLOT_CODE[slot]
    if slot == "수치조건":
        bounds = [k for k in value if k in _BOUND]
        if list(value) != ["단위"] + bounds or len(bounds) != 1:
            raise ValueError(f"수치조건 value {value!r} is not {{단위, 최소|최대}}")
        return _SLOT.pack(code, _BOUND[bounds[0]], 0, ordinal, sid[value["단위"]], NULL, float(value[bounds[0]]))
    if slot in ("값옮김", "값셈"):
        if not (isinstance(value, tuple) and len(value) == 2):
            raise ValueError(f"{slot} value {value!r} is not a pair")
        return _SLOT.pack(code, 0, 0, ordinal, sid[value[0]], sid[value[1]], 0.0)
    return _SLOT.pack(code, 0, 0, ordinal, sid[value], NULL, 0.0)


def encode_node(path: str, g: Mapping[str, Any], sid: Mapping[str, int]) -> bytes:
    """The ``NODE`` chunk of one graph (6.9)."""
    names = node_names(g)
    slot_ordinal = {slot: {name: i for i, name in enumerate(g.get(slot) or {})} for slot in SLOT_KEYS}
    rows, slots, examples = bytearray(), bytearray(), []
    n_slots = 0
    for name in sorted(names, key=lambda n: _nfc(n).encode("utf-8")):
        layer, ordinal = names[name]
        items = list(g[LAYER_KEYS[layer - 1]][name]) if layer else []
        mine = [s for s in SLOT_KEYS if name in slot_ordinal[s]]
        rows += _NODE_ROW.pack(sid[name], layer, 0, len(mine), ordinal, len(examples), len(items), n_slots)
        for slot in mine:
            slots += _slot_record(slot, slot_ordinal[slot][name], g[slot][name], sid)
        n_slots += len(mine)
        examples += [sid[e] for e in items]
    pool: list[int] = []
    lists: list[int] = []
    for key in LIST_KEYS:
        items = [sid[x] for x in g.get(key) or ()]
        lists += [len(pool), len(items)]
        pool += items
    flags = (F_GROUNDS if "근거관계" in g else 0) | (F_DUTIES if "맡음" in g else 0)
    if "근거관계" in g and "맡음" in g and list(g).index("맡음") < list(g).index("근거관계"):
        flags |= F_DUTIES_FIRST
    lines = [x for k, v in g["대사"].items() for x in (sid[k], sid[v])]
    threshold = g["임계값"]
    if list(threshold) != ["A_MIN", "OK_MIN"]:
        raise ValueError(f"임계값 {threshold!r} is not {{A_MIN, OK_MIN}}")
    head = _NODE_HEAD.pack(sid[graph_id(path)], sid[g["역할"]], sid[g["목표"]], sid[g["이름말"]], sid[g["색인"]],
                           sid[g["언어"]], float(threshold["A_MIN"]), float(threshold["OK_MIN"]), flags,
                           len(names), n_slots, len(examples), len(pool), len(lines) // 2)
    return (head + _NODE_LISTS.pack(*lists) + bytes(rows) + bytes(slots)
            + struct.pack(f"<{len(examples)}I", *examples) + struct.pack(f"<{len(pool)}I", *pool)
            + struct.pack(f"<{len(lines)}I", *lines))


def encode_edge(path: str, g: Mapping[str, Any], sid: Mapping[str, int]) -> bytes:
    """The ``EDGE`` chunk of one graph (6.10)."""
    rows = []
    for kind, key in EDGE_LIST.items():
        for ordinal, (src, rel, dst) in enumerate(g[key]):
            raw = bytes.fromhex(edge_id(path, src, rel, dst)[2:])
            rows.append(_EDGE_ROW.pack(raw, sid[src], sid[rel], sid[dst], kind, b"\x00" * 3, ordinal))
    rows.sort(key=lambda r: r[:16])
    return _EDGE_HEAD.pack(sid[graph_id(path)], len(rows)) + b"".join(rows)


@dataclass(frozen=True)
class IndexRow:
    """One ``INDX`` row (6.8). ``node_chunk``/``edge_chunk`` are TOC indexes (locators)."""

    graph: str
    member: str
    status: int
    reason: Optional[str]
    node_chunk: Optional[int]
    edge_chunk: Optional[int]
    nodes: int
    edges: int
    examples: int

    def to_dict(self) -> dict[str, Any]:
        return {"graph_id": self.graph, "member": self.member,
                "status": "tables" if self.status == TABLES else "source-only", "reason": self.reason,
                "nodes": self.nodes, "edges": self.edges, "examples": self.examples}


def encode_index(rows: Sequence[IndexRow], sid: Mapping[str, int]) -> bytes:
    """The ``INDX`` chunk; ``rows`` in any order."""
    out = bytearray(_INDX_HEAD.pack(len(rows), 0))
    for r in sorted(rows, key=lambda r: r.graph.encode("utf-8")):
        out += _INDX_ROW.pack(sid[r.graph], sid[r.member], r.status, b"\x00" * 3,
                              NULL if r.reason is None else sid[r.reason],
                              NULL if r.node_chunk is None else r.node_chunk,
                              NULL if r.edge_chunk is None else r.edge_chunk, r.nodes, r.edges, r.examples)
    return bytes(out)


def pack_rules(pack_manifest: Mapping[str, Any], members: Mapping[str, bytes]) -> list[tuple[str, dict]]:
    """The model's rules as MARCO collects them: the axiom files named by the
    model declaration, in that order, and each file's ``rules`` in file order.
    Returns ``(axiom file path, rule)`` pairs. Raises ``ValueError``."""
    model = pack_manifest.get("model")
    if not isinstance(model, Mapping):
        return []
    out: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for path in model.get("axioms") or []:
        doc = json.loads(members[path])
        rules = doc.get("rules", []) if isinstance(doc, dict) else None
        if not isinstance(rules, list):
            raise ValueError(f"{path}: rules is not a list")
        for rule in rules:
            if not isinstance(rule, dict):
                raise ValueError(f"{path}: a rule is not an object")
            rid = rule_id(rule)
            if rid in seen:
                raise ValueError(f"{path}: duplicate rule id {rid!r}")
            seen.add(rid)
            out.append((path, rule))
    return out


def encode_rules(rules: Sequence[tuple[str, dict]], sid: Mapping[str, int]) -> bytes:
    """The ``RULE`` chunk (6.11)."""
    keyed = sorted(((rule_id(rule), source, ordinal, _canonical(rule))
                    for ordinal, (source, rule) in enumerate(rules)), key=lambda r: r[0].encode("utf-8"))
    rows, payload = bytearray(_RULE_HEAD.pack(len(keyed), 0)), bytearray()
    for rid, source, ordinal, body in keyed:
        rows += _RULE_ROW.pack(sid[rid], sid[source], ordinal, len(payload), len(body))
        payload += body
    return bytes(rows) + bytes(payload)


# --- reading ----------------------------------------------------------------------------------

def _permutation(ordinals: list[int], what: str, fail: Fail) -> None:
    if sorted(ordinals) != list(range(len(ordinals))):
        raise fail(f"{what}: ordinals are not 0..{len(ordinals) - 1} each once")


def decode_index(data: bytes, s: Callable[[int, str], str], fail: Fail) -> list[IndexRow]:
    if len(data) < _INDX_HEAD.size:
        raise fail("INDX: too short")
    count, reserved = _INDX_HEAD.unpack_from(data)
    if reserved or _INDX_HEAD.size + count * _INDX_ROW.size != len(data):
        raise fail(f"INDX: {count} rows do not fill {len(data)} bytes exactly")
    rows: list[IndexRow] = []
    previous = b""
    for i, (g, member, status, pad, reason, node_chunk, edge_chunk, nodes, edges, examples) in \
            enumerate(_INDX_ROW.iter_unpack(data[_INDX_HEAD.size:])):
        where = f"INDX row {i}"
        name = s(g, where)
        key = name.encode("utf-8")
        if pad != b"\x00" * 3 or key <= previous:
            raise fail(f"{where}: reserved bytes, or graph ids not unique and sorted")
        previous = key
        if status == TABLES:
            if reason != NULL or NULL in (node_chunk, edge_chunk):
                raise fail(f"{where}: a tabled graph needs its two chunks and no reason")
            rows.append(IndexRow(name, s(member, where), status, None, node_chunk, edge_chunk, nodes, edges, examples))
        elif status == SOURCE_ONLY:
            if reason == NULL or (node_chunk, edge_chunk, nodes, edges, examples) != (NULL, NULL, 0, 0, 0):
                raise fail(f"{where}: a source-only graph has a reason and no chunks or counts")
            rows.append(IndexRow(name, s(member, where), status, s(reason, where), None, None, 0, 0, 0))
        else:
            raise fail(f"{where}: unknown status {status}")
        if graph_id(rows[-1].member) != name:
            raise fail(f"{where}: graph id {name!r} is not the id of member {rows[-1].member!r}")
    return rows


@dataclass
class NodeTable:
    """A decoded ``NODE`` chunk, still in string ids."""

    head: tuple
    lists: tuple
    rows: list[tuple]
    slots: list[tuple]
    examples: tuple
    pool: tuple
    lines: tuple


@dataclass
class EdgeTable:
    graph: int
    rows: list[tuple]


def decode_node(data: bytes, row: IndexRow, s: Callable[[int, str], str], fail: Fail) -> NodeTable:
    where = f"NODE of {row.graph}"
    base = _NODE_HEAD.size + _NODE_LISTS.size
    if len(data) < base:
        raise fail(f"{where}: too short")
    head = _NODE_HEAD.unpack_from(data)
    g, flags, n_nodes, n_slots, n_examples, n_pool, n_lines = head[0], *head[8:]
    size = base + n_nodes * _NODE_ROW.size + n_slots * _SLOT.size + 4 * (n_examples + n_pool + 2 * n_lines)
    if size != len(data):
        raise fail(f"{where}: counts do not fill {len(data)} bytes exactly")
    if s(g, where) != row.graph or (n_nodes, n_examples) != (row.nodes, row.examples):
        raise fail(f"{where}: graph id or counts disagree with INDX")
    if flags & ~(F_GROUNDS | F_DUTIES | F_DUTIES_FIRST) or \
            (flags & F_DUTIES_FIRST and flags & (F_GROUNDS | F_DUTIES) != F_GROUNDS | F_DUTIES):
        raise fail(f"{where}: invalid flags 0x{flags:x}")
    lists = _NODE_LISTS.unpack_from(data, _NODE_HEAD.size)
    expected = 0
    for k, key in enumerate(LIST_KEYS):
        first, count = lists[2 * k], lists[2 * k + 1]
        if first != expected:
            raise fail(f"{where}: list {key} starts at {first}, expected {expected}")
        expected += count
    if expected != n_pool:
        raise fail(f"{where}: lists use {expected} of {n_pool} entries")
    if (not flags & F_GROUNDS and lists[5]) or (not flags & F_DUTIES and lists[11]):
        raise fail(f"{where}: an absent list has entries")
    at = base
    rows = list(_NODE_ROW.iter_unpack(data[at:at + n_nodes * _NODE_ROW.size]))
    at += n_nodes * _NODE_ROW.size
    slots = list(_SLOT.iter_unpack(data[at:at + n_slots * _SLOT.size]))
    at += n_slots * _SLOT.size
    numbers = struct.unpack_from(f"<{n_examples + n_pool + 2 * n_lines}I", data, at)
    examples, pool, lines = numbers[:n_examples], numbers[n_examples:n_examples + n_pool], numbers[n_examples + n_pool:]
    first_example = first_slot = 0
    previous = b""
    for i, (name, layer, pad, count_slots, ordinal, first, count, slot_at) in enumerate(rows):
        w = f"{where} node {i}"
        key = _nfc(s(name, w)).encode("utf-8")
        if key <= previous:
            raise fail(f"{w}: node ids are not unique and sorted")
        previous = key
        if pad or layer > 3 or first != first_example or slot_at != first_slot:
            raise fail(f"{w}: reserved byte, layer, or example/slot ranges invalid")
        if layer == 0 and (count or ordinal or not count_slots):
            raise fail(f"{w}: a node in no layer has no examples, ordinal 0 and at least one slot")
        if layer and not count:
            raise fail(f"{w}: a node in a layer has at least one example")
        first_example += count
        first_slot += count_slots
        codes = [slots[j][0] for j in range(slot_at, min(slot_at + count_slots, n_slots))]
        if len(codes) != count_slots or codes != sorted(set(codes)) or any(not 1 <= c <= 7 for c in codes):
            raise fail(f"{w}: slot records invalid")
    if first_example != n_examples or first_slot != n_slots:
        raise fail(f"{where}: rows use {first_example} examples and {first_slot} slots, "
                   f"header says {n_examples} and {n_slots}")
    for j, (code, bound, pad, ordinal, a, b, value) in enumerate(slots):
        w = f"{where} slot {j}"
        numeric = code == SLOT_CODE["수치조건"]
        pair = code in (SLOT_CODE["값옮김"], SLOT_CODE["값셈"])
        bound_ok = bound in (1, 2) if numeric else bound == 0
        if pad or not bound_ok or (b != NULL) != pair or (not numeric and value != 0.0):
            raise fail(f"{w}: fields do not match slot {code}")
        s(a, w)
        if pair:
            s(b, w)
    for k in examples + pool + lines:
        s(k, where)
    return NodeTable(head, lists, rows, slots, examples, pool, lines)


def decode_edge(data: bytes, row: IndexRow, s: Callable[[int, str], str], fail: Fail) -> EdgeTable:
    where = f"EDGE of {row.graph}"
    if len(data) < _EDGE_HEAD.size:
        raise fail(f"{where}: too short")
    g, count = _EDGE_HEAD.unpack_from(data)
    if _EDGE_HEAD.size + count * _EDGE_ROW.size != len(data):
        raise fail(f"{where}: {count} rows do not fill {len(data)} bytes exactly")
    if s(g, where) != row.graph or count != row.edges:
        raise fail(f"{where}: graph id or count disagree with INDX")
    rows = list(_EDGE_ROW.iter_unpack(data[_EDGE_HEAD.size:]))
    previous = b""
    for i, (raw, src, rel, dst, kind, pad, ordinal) in enumerate(rows):
        if raw <= previous or kind not in EDGE_LIST or pad != b"\x00" * 3:
            raise fail(f"{where} edge {i}: ids not unique and sorted, or kind/reserved invalid")
        previous = raw
        s(src, where), s(rel, where), s(dst, where)
    return EdgeTable(g, rows)


def build_graph(nodes: NodeTable, edges: EdgeTable, s: Callable[[int, str], str], fail: Fail,
                where: str) -> dict[str, Any]:
    """The graph in the shape of ``read_kg`` (without the shared hypernym merge)."""
    head, lists = nodes.head, nodes.lists
    _g, role, goal, name_kind, indexed, language, a_min, ok_min, flags = head[:9]
    pool = nodes.pool

    def strings(k: int) -> list[str]:
        first, count = lists[2 * k], lists[2 * k + 1]
        return [s(x, where) for x in pool[first:first + count]]

    lines = nodes.lines
    layers: list[list] = [[], [], []]
    slot_items: dict[int, list] = {code: [] for code in SLOT_CODE.values()}
    examples = nodes.examples
    slots = nodes.slots
    for name, layer, _pad, count_slots, ordinal, first, count, slot_at in nodes.rows:
        text = s(name, where)
        if layer:
            layers[layer - 1].append((ordinal, text, [s(e, where) for e in examples[first:first + count]]))
        for code, bound, _p, slot_ordinal, a, b, value in slots[slot_at:slot_at + count_slots]:
            if code == SLOT_CODE["수치조건"]:
                item: Any = {"단위": s(a, where), _BOUND_NAME[bound]: value}
            elif b != NULL:
                item = (s(a, where), s(b, where))
            else:
                item = s(a, where)
            slot_items[code].append((slot_ordinal, text, item))
    g: dict[str, Any] = {"역할": s(role, where), "목표": s(goal, where),
                         "임계값": {"A_MIN": a_min, "OK_MIN": ok_min}, "이름말": s(name_kind, where),
                         "색인": s(indexed, where), "언어": s(language, where),
                         "전진관계": strings(0), "부정관계": strings(1),
                         "대사": {s(lines[i], where): s(lines[i + 1], where) for i in range(0, len(lines), 2)}}
    if len(g["대사"]) * 2 != len(lines):
        raise fail(f"{where}: 대사 keys repeat")
    for k, layer in enumerate(LAYER_KEYS):
        items = layers[k]
        _permutation([o for o, _, _ in items], f"{where} {layer}", fail)
        g[layer] = {name: ex for _, name, ex in sorted(items, key=lambda x: x[0])}
    for slot in SLOT_KEYS[:-1]:
        items = slot_items[SLOT_CODE[slot]]
        _permutation([o for o, _, _ in items], f"{where} {slot}", fail)
        g[slot] = {name: v for _, name, v in sorted(items, key=lambda x: x[0])}
    for kind, key in EDGE_LIST.items():
        items = [(o, [s(a, where), s(r, where), s(b, where)]) for _raw, a, r, b, k, _p, o in edges.rows if k == kind]
        _permutation([o for o, _ in items], f"{where} {key}", fail)
        g[key] = [e for _, e in sorted(items, key=lambda x: x[0])]
    g["포함"], g["공리"] = strings(3), strings(4)
    optional = [("근거관계", 2, F_GROUNDS), ("맡음", 5, F_DUTIES)]
    if flags & F_DUTIES_FIRST:
        optional.reverse()
    for key, k, bit in optional:
        if flags & bit:
            g[key] = strings(k)
    sources = slot_items[SLOT_CODE["출처"]]
    if sources:
        _permutation([o for o, _, _ in sources], f"{where} 출처", fail)
        g["출처"] = {name: v for _, name, v in sorted(sources, key=lambda x: x[0])}
    return g


def graph_rows(row: IndexRow, nodes: NodeTable, edges: EdgeTable, s: Callable[[int, str], str]) -> dict[str, Any]:
    """The graph's rows with their stable ids, as plain data, in stored (id) order."""
    where = f"tables of {row.graph}"
    layer_name = {0: None, **{v: k for k, v in LAYER_CODE.items()}}
    slot_name = {v: k for k, v in SLOT_CODE.items()}
    out_nodes = []
    for name, layer, _pad, count_slots, ordinal, first, count, slot_at in nodes.rows:
        text = s(name, where)
        slots = {}
        for code, bound, _p, slot_ordinal, a, b, value in nodes.slots[slot_at:slot_at + count_slots]:
            if code == SLOT_CODE["수치조건"]:
                v: Any = {"단위": s(a, where), _BOUND_NAME[bound]: value}
            elif b != NULL:
                v = [s(a, where), s(b, where)]
            else:
                v = s(a, where)
            slots[slot_name[code]] = {"ordinal": slot_ordinal, "value": v}
        out_nodes.append({"node_id": node_id(row.graph, text), "name": text, "layer": layer_name[layer],
                          "ordinal": ordinal if layer else None,
                          "examples": [s(e, where) for e in nodes.examples[first:first + count]], "slots": slots})
    out_edges = [_edge_row(raw, a, r, b, kind, ordinal, s, where) for raw, a, r, b, kind, _p, ordinal in edges.rows]
    return {"graph_id": row.graph, "member": row.member, "nodes": out_nodes, "edges": out_edges}


def _edge_row(raw: bytes, a: int, r: int, b: int, kind: int, ordinal: int, s: Callable[[int, str], str],
              where: str) -> dict[str, Any]:
    return {"edge_id": "e:" + raw.hex(), "src": s(a, where), "rel": s(r, where), "dst": s(b, where),
            "list": EDGE_LIST[kind], "ordinal": ordinal}


def edges_touching(edges: EdgeTable, name: str, s: Callable[[int, str], str]) -> list[dict[str, Any]]:
    """The rows of ``edges`` whose source or destination is ``name``."""
    return [_edge_row(raw, a, r, b, kind, ordinal, s, "EDGE")
            for raw, a, r, b, kind, _p, ordinal in edges.rows if name in (s(a, "EDGE"), s(b, "EDGE"))]


def check_edge_ids(row: IndexRow, edges: EdgeTable, s: Callable[[int, str], str], fail: Fail) -> None:
    """Full verification: every stored edge id is the id of its (graph, src, rel, dst)."""
    for raw, a, r, b, _kind, _p, _o in edges.rows:
        if "e:" + raw.hex() != edge_id(row.graph, s(a, ""), s(r, ""), s(b, "")):
            raise fail(f"EDGE of {row.graph}: stored edge id {raw.hex()} is not the id of its edge")


def decode_rules(data: bytes, s: Callable[[int, str], str], fail: Fail) -> list[dict[str, Any]]:
    """``RULE`` rows in stored (rule id) order: ``{"rule_id", "source", "ordinal", "rule"}``."""
    if len(data) < _RULE_HEAD.size:
        raise fail("RULE: too short")
    count, reserved = _RULE_HEAD.unpack_from(data)
    base = _RULE_HEAD.size + count * _RULE_ROW.size
    if reserved or base > len(data):
        raise fail(f"RULE: {count} rows do not fit {len(data)} bytes")
    payload = data[base:]
    out, expected, previous = [], 0, b""
    for i, (rid, source, ordinal, offset, length) in enumerate(_RULE_ROW.iter_unpack(data[_RULE_HEAD.size:base])):
        where = f"RULE row {i}"
        name = s(rid, where)
        if name.encode("utf-8") <= previous or offset != expected:
            raise fail(f"{where}: rule ids not unique and sorted, or payload not contiguous")
        previous = name.encode("utf-8")
        expected += length
        if expected > len(payload):
            raise fail(f"{where}: payload runs past the chunk")
        body = payload[offset:offset + length]
        try:
            rule = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise fail(f"{where}: payload is not JSON ({exc})") from exc
        if not isinstance(rule, dict) or rule.get("id") != name or _canonical(rule) != body:
            raise fail(f"{where}: payload is not the canonical JSON of rule {name!r}")
        out.append({"rule_id": name, "source": s(source, where), "ordinal": ordinal, "rule": rule})
    if expected != len(payload):
        raise fail(f"RULE: rows use {expected} of {len(payload)} payload bytes")
    _permutation([r["ordinal"] for r in out], "RULE", fail)
    return out
