"""Conversation snapshots: what :meth:`mco.Session.snapshot` writes and :func:`mco.inspect_snapshot` reads.

A snapshot is one file holding a conversation's turns and reasoning state, bound to the
base it ran on (the base's ``content_sha256`` and build id) and to the overlay sequence
when an overlay is attached. Resuming it (``mco.load(model, snapshot=path)`` or
:meth:`mco.Model.resume`) refuses another base, another overlay history, and a damaged
file. The file format belongs to the backend that wrote it; with the built-in backends
that is the MARCO runtime's (``docs/architecture/snapshot.md``).

Inspecting a snapshot reads and verifies the file; it runs no model.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import os
from pathlib import Path
from typing import Any, Optional, Union

from .result import _freeze, _thaw

__all__ = ["SnapshotInfo", "inspect_snapshot", "is_snapshot", "SNAPSHOT_MAGIC"]

#: The first bytes of every snapshot file the built-in backends write.
SNAPSHOT_MAGIC = b"MARCO-SNAPSHOT/1"


@dataclass(frozen=True)
class SnapshotInfo:
    """What a snapshot file holds. Reading it never runs a model."""

    path: Optional[str]
    size_bytes: int
    sha256: str
    version: int
    base: Mapping[str, Any]
    overlay: Optional[Mapping[str, Any]]
    runtime: Optional[str]
    requires: tuple[str, ...] = ()
    schemas: tuple[str, ...] = ()
    conversations: int = 0
    turns: int = 0
    excluded: tuple[str, ...] = ()
    conversation_ids: tuple[str, ...] = field(default=(), compare=False)

    def __post_init__(self) -> None:
        for name in ("requires", "schemas", "excluded", "conversation_ids"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "base", _freeze(self.base))
        if self.overlay is not None:
            object.__setattr__(self, "overlay", _freeze(self.overlay))

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "size_bytes": self.size_bytes, "sha256": self.sha256,
                "version": self.version, "base": _thaw(self.base),
                "overlay": _thaw(self.overlay) if self.overlay is not None else None,
                "runtime": self.runtime, "requires": list(self.requires), "schemas": list(self.schemas),
                "conversations": self.conversations, "turns": self.turns, "excluded": list(self.excluded),
                "conversation_ids": list(self.conversation_ids)}

    @classmethod
    def _from_summary(cls, data: Mapping[str, Any], ids: tuple[str, ...]) -> "SnapshotInfo":
        return cls(path=data.get("path"), size_bytes=data["bytes"], sha256=data["sha256"],
                   version=data["version"], base=data["base"], overlay=data.get("overlay"),
                   runtime=data.get("runtime"), requires=data.get("requires", ()),
                   schemas=data.get("schemas", ()), conversations=data.get("conversations", 0),
                   turns=data.get("turns", 0), excluded=data.get("excluded", ()), conversation_ids=ids)


def is_snapshot(path: Union[str, "os.PathLike[str]"]) -> bool:
    """True when the file starts with the snapshot header (nothing else is checked)."""
    try:
        with Path(path).open("rb") as handle:
            return handle.read(len(SNAPSHOT_MAGIC)) == SNAPSHOT_MAGIC
    except OSError:
        return False


def inspect_snapshot(path: Union[str, "os.PathLike[str]"], *, marco_root: Optional[str] = None) -> SnapshotInfo:
    """Read and verify a snapshot file and describe it: base identity, overlay sequence,
    schemas, conversation and turn counts. Raises :class:`~mco.SnapshotFormatError` for a
    damaged, truncated or unknown file."""
    from .backends.marco import read_snapshot   # the format's reader lives with its runtime
    return read_snapshot(path, marco_root=marco_root)[0]
