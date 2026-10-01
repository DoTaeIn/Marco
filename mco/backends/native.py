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

What this first slice does not do: graphs, language packs and axioms are
carried pack members, not tables, so MARCO parses the graph text when the model
is opened, as it does for a ``.kgpack``; nothing is loaded lazily. Overlays are
not supported. Conversation snapshots are (``Session.snapshot``): they bind to the
file's ``content_sha256`` and build id; the file itself carries no snapshot.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..errors import BackendUnavailableError, InvalidInputError, UnsupportedFormatError
from ..formats import ModelFile
from ..info import ModelInfo
from .base import Backend, BackendModel
from .marco import CAPABILITIES, OPTIONS, MarcoModel, _find_root, _model_fingerprint

__all__ = ["NativeMcoBackend"]

#: Plain statements ``mco inspect`` shows for every Format 1 file of this version.
LIMITS = ("overlay: not supported in this version",
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
        carried = sorted({m["type"] for m in members})
        usable, reason = self.availability()
        notes = [f"MCO Format {fmt.get('major')}.{fmt.get('minor')}; pack members ({', '.join(carried)}) "
                 "are carried as typed chunks, not tables, in this version",
                 *LIMITS]
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
            manifest={"mco": manifest, "format": fmt, "chunks": native.get("chunks", []), "members": members},
        )

    def open(self, file: ModelFile, options: Mapping[str, Any]) -> BackendModel:
        if file.refusal:
            raise UnsupportedFormatError(file.refusal)
        unknown = set(options) - OPTIONS
        if unknown:
            raise InvalidInputError(f"unknown option(s) for backend {self.name!r}: {sorted(unknown)}")
        return MarcoModel(self, file, dict(options))
