"""Stable ids for graphs, nodes, edges and rules, shared by the base format and the overlay.

No id is positional or ordinal: each one is computed from what the item is, so the
same item has the same id in every build of the base and in every overlay.

Exact encoding (fixed; the base format and the overlay must agree byte for byte):

* ``graph_id`` = the pack path of the graph with forward slashes, NFC-normalised,
  e.g. ``graphs/x.kg``. A backslash is turned into a forward slash; nothing else
  is changed.
* ``node_id`` = ``graph_id + "#" + node name``, the name NFC-normalised.
* ``edge_id`` = ``"e:"`` + the first 32 hex characters (lower case) of SHA-256 over
  the UTF-8 bytes of graph_id, src, rel and dst, each NFC-normalised first, joined
  by the single byte 0x1F. ``src`` and ``dst`` are node *names* within the graph
  (not node ids). A part that itself contains 0x1F is refused, so the join is
  unambiguous.
* ``rule_id`` = the existing rule id string, unchanged.

Standard library only; no other import.
"""
import hashlib
import unicodedata

SEPARATOR = b"\x1f"
EDGE_PREFIX = "e:"
EDGE_HEX = 32


def _nfc(text, what):
    if not isinstance(text, str) or not text:
        raise ValueError("%s must be a non-empty string, not %r" % (what, text))
    return unicodedata.normalize("NFC", text)


def graph_id(pack_path):
    """The graph's pack path with forward slashes, NFC-normalised."""
    return _nfc(pack_path, "graph path").replace("\\", "/")


def node_id(graph, name):
    """``graph_id + "#" + name``."""
    return _nfc(graph, "graph_id") + "#" + _nfc(name, "node name")


def edge_id(graph, src, rel, dst):
    """``"e:"`` + 32 hex characters of SHA-256 over graph_id, src, rel, dst joined by 0x1F."""
    parts = []
    for what, text in (("graph_id", graph), ("src", src), ("rel", rel), ("dst", dst)):
        data = _nfc(text, what).encode("utf-8")
        if SEPARATOR in data:
            raise ValueError("%s contains the separator byte 0x1F: %r" % (what, text))
        parts.append(data)
    return EDGE_PREFIX + hashlib.sha256(SEPARATOR.join(parts)).hexdigest()[:EDGE_HEX]


def rule_id(existing):
    """The existing rule id string, unchanged."""
    if not isinstance(existing, str) or not existing:
        raise ValueError("rule id must be a non-empty string, not %r" % (existing,))
    return existing
