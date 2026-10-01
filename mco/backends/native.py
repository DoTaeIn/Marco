"""The ``mco-native`` backend: runs MCO Format 1 files (``docs/mco/format-1.md``).

Reading the file is :mod:`mco.native` (standard library, no MARCO). Running it
is the MARCO engine, reached through the same model and session classes as the
``marco-kgpack`` backend (:mod:`mco.backends.marco`), so the two backends
cannot drift apart in how they translate MARCO's output.

Where the knowledge comes from: only the ``.mco`` file. On open, the pack MARCO
needs is rebuilt from the file's chunks into the model's private working
directory; no graph, language pack or axiom file of a source tree is read. The
engine *code* still comes from a MARCO checkout, found exactly as the
``marco-kgpack`` backend finds it.

Format 1.1 files also hold node, edge, graph-index and rule tables
(``mco.native`` reads them; ``mco inspect`` shows their counts), but the
running path does not use them yet: MARCO still parses the graph source text
(``GRPH`` chunks) when the model is opened, as it does for a ``.kgpack``.
Language packs, axiom files and records are carried pack members. Nothing is
loaded lazily. An overlay store beside the file can be attached
(``mco.load(path, overlay=...)``, :mod:`mco.overlay`); the file itself holds no
overlay. Conversation snapshots are supported (``Session.snapshot``): they bind
to the file's ``content_sha256`` and build id; the file itself carries no
snapshot.
"""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..errors import BackendUnavailableError, InvalidInputError, UnsupportedFormatError
from ..formats import ModelFile
from ..info import ModelInfo
from .base import Backend, BackendModel
from .marco import CAPABILITIES, OPTIONS, MarcoModel, MarcoOverlay, _find_root, _model_fingerprint

__all__ = ["NativeMcoBackend"]

#: Plain statements ``mco inspect`` shows for every Format 1 file of this version.
LIMITS = ("overlay: an overlay store beside the file can be attached (mco.load(..., overlay=PATH)); "
          "the file itself holds no overlay (manifest supports.overlay stays false)",
          "snapshot: conversation snapshots are supported (Session.snapshot, mco snapshot) and bind to "
          "this file's content_sha256 and build id; the file itself carries no snapshot "
          "(manifest supports.snapshot stays false in Format 1.0)")


class NativeMcoBackend(Backend):
    """Runs MCO Format 1 files on the MARCO engine."""

    name = "mco-native"
    formats = ("mco-native",)
    priority = 10

    def availability(self) -> tuple[bool, str]:
        try:
            _find_root()
        except BackendUnavailableError as exc:
            return False, str(exc)
        return True, ""

    def describe(self, file: ModelFile) -> ModelInfo:
        if file.refusal:
            return ModelInfo(path=str(file.path), format=file.kind, format_version=file.version,
                             size_bytes=file.size_bytes, sha256=file.sha256, backend=self.name,
                             runnable=False, notes=(file.refusal,))
        manifest = file.manifest
        native = file.native
        members = native.get("members", [])
        fmt = native.get("format", {})
        tables = native.get("tables")
        usable, reason = self.availability()
        notes = [f"MCO Format {fmt.get('major')}.{fmt.get('minor')}"]
        if tables:
            notes.append(f"tables: {tables['tabled']} of {tables['graphs']} graphs in node/edge tables "
                         f"({tables['nodes']} nodes, {tables['edges']} edges), {tables['rules']} rules "
                         "in the rule table; not yet used by the running path, which reads the source text")
            for path, why in sorted((tables.get("source_only_reasons") or {}).items()):
                notes.append(f"source text only, no tables: {path} ({why})")
            carried = sorted({m["type"] for m in members if m["type"] != "GRPH"})
            notes.append("graph source text is kept in GRPH chunks (source text); other pack members "
                         f"({', '.join(carried) or '-'}) are carried as typed chunks, not tables, in this version")
        else:
            carried = sorted({m["type"] for m in members})
            notes.append(f"pack members ({', '.join(carried)}) are carried as typed chunks, not tables, "
                         "in this version")
        notes += LIMITS
        if not usable:
            notes.append(reason)
        model = manifest.get("model") if isinstance(manifest.get("model"), Mapping) else {}
        graphs = sum(1 for m in members if m.get("kind") == "graph")
        return ModelInfo(
            path=str(file.path), format=file.kind, format_version=file.version,
            size_bytes=file.size_bytes, sha256=file.sha256,
            name=manifest.get("name") or file.path.stem, build_id=manifest.get("build_id"),
            backend=self.name, language=manifest.get("language"),
            languages=tuple(manifest.get("languages") or ()), graphs=graphs, assets=len(members) - graphs,
            fingerprint=_model_fingerprint({"model": model, "files": members}),
            verified=file.verified, runnable=usable, capabilities=CAPABILITIES, notes=tuple(notes),
            manifest={"mco": manifest, "format": fmt, "chunks": native.get("chunks", []), "members": members,
                      "tables": tables},
        )

    def open(self, file: ModelFile, options: Mapping[str, Any]) -> BackendModel:
        if file.refusal:
            raise UnsupportedFormatError(file.refusal)
        unknown = set(options) - OPTIONS
        if unknown:
            raise InvalidInputError(f"unknown option(s) for backend {self.name!r}: {sorted(unknown)}")
        return MarcoModel(self, file, dict(options))

    def open_overlay(self, file: ModelFile, path: Path, *, create: bool, writer: bool,
                     options: Mapping[str, Any]) -> MarcoOverlay:
        """The overlay store of ``file`` at ``path`` (for :mod:`mco.overlay`)."""
        if file.refusal:
            raise UnsupportedFormatError(file.refusal)
        return MarcoOverlay(file, path, create=create, writer=writer, marco_root=options.get("marco_root"))
