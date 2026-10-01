"""MCO Format 1: the native ``.mco`` file (``docs/mco/format-1.md``).

Two layers, standard library only, no MARCO import:

:mod:`mco.native.container`
    Header, table of contents and chunks. Validates the byte layout and reads
    one chunk at a time.
:mod:`mco.native.pack`
    The manifest, the string/member/graph-directory tables and the mapping to
    and from a MARCO pack. :class:`NativeModel` opens a file;
    :func:`write_model` writes one.
:mod:`mco.native.ids`
    The stable identifiers (graph, node, edge, rule), a byte-identical copy of
    ``marco/storage/ids.py``.

This package is internal to ``mco``: user code goes through ``mco.load``,
``mco.compile(..., format="native")`` and ``mco.inspect``.
"""
from __future__ import annotations

from .container import MAGIC, MAJOR, MINOR, Chunk, ChunkEntry, Container, encode
from .ids import edge_id, graph_id, node_id, rule_id
from .pack import (FEATURES, KNOWN_CHUNKS, MEMBER_TYPES, RESERVED_TYPES, TABLE_TYPES, Member, NativeModel,
                   build_chunks, write_model)

__all__ = [
    "MAGIC", "MAJOR", "MINOR", "Chunk", "ChunkEntry", "Container", "encode",
    "FEATURES", "KNOWN_CHUNKS", "MEMBER_TYPES", "RESERVED_TYPES", "TABLE_TYPES", "Member", "NativeModel",
    "build_chunks", "write_model", "graph_id", "node_id", "edge_id", "rule_id",
]
