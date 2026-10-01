"""Stable identifiers of MCO Format 1 and the Persistent Overlay Infrastructure.

The encoding is fixed in docs/mco/format-1.md section 6.7. Every identifier is a
key derived from content, never a position. Standard library only.

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


def _nfc(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"an identifier part must be a string, not {type(value).__name__}")
    return unicodedata.normalize("NFC", value)


def graph_id(path: str) -> str:
    """The graph's pack path with forward slashes, NFC-normalised."""
    return _nfc(path).replace("\\", "/")


def node_id(graph: str, name: str) -> str:
    """``graph_id + "#" + node name``, both NFC-normalised."""
    return graph_id(graph) + "#" + _nfc(name)


def edge_id(graph: str, src: str, rel: str, dst: str) -> str:
    """``"e:"`` + the first 32 hex digits of SHA-256 over the UTF-8 bytes of
    graph_id, src, rel and dst, each NFC-normalised, joined by the byte 0x1F."""
    parts = (graph_id(graph), _nfc(src), _nfc(rel), _nfc(dst))
    digest = hashlib.sha256(_EDGE_SEPARATOR.join(p.encode("utf-8") for p in parts)).hexdigest()
    return "e:" + digest[:32]


def rule_id(rule: Union[str, Mapping[str, Any]]) -> str:
    """The rule's existing id string, unchanged (a rule mapping's ``id``, or the id itself)."""
    value = rule.get("id") if isinstance(rule, Mapping) else rule
    if not isinstance(value, str) or not value:
        raise ValueError("a rule id is a non-empty string")
    return value
