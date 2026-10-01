"""Stable identifiers of MCO Format 1 and the Persistent Overlay Infrastructure.

The encoding is fixed in docs/mco/format-1.md section 6.7. Every identifier is a
key derived from content, never a position: the same item has the same id in
every build of the base and in every overlay. Standard library only.

* ``graph_id`` = the pack path of the graph with forward slashes, NFC-normalised.
* ``node_id`` = ``graph_id + "#" + node name``, the name NFC-normalised.
* ``edge_id`` = ``"e:"`` + the first 32 hex digits of SHA-256 over the UTF-8 bytes
  of graph_id, src, rel and dst, each NFC-normalised, joined by the byte 0x1F.
  ``src`` and ``dst`` are node names within the graph, not node ids. A part that
  contains 0x1F is refused, so the join is unambiguous.
* ``rule_id`` = the rule's existing id string, unchanged.

Two byte-identical copies of this file exist: marco/storage/ids.py and
mco/native/ids.py (the mco package does not import MARCO).
tests/test_mco_native_format.py checks that they are identical and agree.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
from typing import Any, Union
import unicodedata

__all__ = ["graph_id", "node_id", "edge_id", "rule_id"]

_EDGE_SEPARATOR = b"\x1f"


def _nfc(value: str, what: str = "an identifier part") -> str:
    if not isinstance(value, str):
        raise TypeError(f"{what} must be a string, not {type(value).__name__}")
    return unicodedata.normalize("NFC", value)


def graph_id(path: str) -> str:
    """The graph's pack path with forward slashes, NFC-normalised."""
    return _nfc(path, "a graph path").replace("\\", "/")


def node_id(graph: str, name: str) -> str:
    """``graph_id + "#" + node name``, both NFC-normalised."""
    return graph_id(graph) + "#" + _nfc(name, "a node name")


def edge_id(graph: str, src: str, rel: str, dst: str) -> str:
    """``"e:"`` + the first 32 hex digits of SHA-256 over the UTF-8 bytes of
    graph_id, src, rel and dst, each NFC-normalised, joined by the byte 0x1F."""
    parts = []
    for what, value in (("src", src), ("rel", rel), ("dst", dst)):
        parts.append(_nfc(value, what).encode("utf-8"))
    parts.insert(0, graph_id(graph).encode("utf-8"))
    for data in parts:
        if _EDGE_SEPARATOR in data:
            raise ValueError("an edge part contains the separator byte 0x1F: %r" % data.decode("utf-8"))
    return "e:" + hashlib.sha256(_EDGE_SEPARATOR.join(parts)).hexdigest()[:32]


def rule_id(rule: Union[str, Mapping[str, Any]]) -> str:
    """The rule's existing id string, unchanged (a rule mapping's ``id``, or the id itself)."""
    value = rule.get("id") if isinstance(rule, Mapping) else rule
    if not isinstance(value, str) or not value:
        raise ValueError("a rule id is a non-empty string")
    return value
