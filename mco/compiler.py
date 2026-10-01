"""``mco.compile`` and ``mco.inspect``."""
from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
from typing import Any, Optional, Sequence, Union

from ._version import __version__
from .backends import get_backend, select_backend
from .errors import CompileError, MCOError, ModelNotFoundError
from .formats import detect, write_compat, write_native
from .info import ModelInfo
from .result import _thaw

__all__ = ["CompileReport", "compile", "inspect"]

#: Output formats of :func:`compile`: the 0.1.0 compatibility container, or MCO Format 1.
FORMATS = ("compat", "native")

PathLike = Union[str, "os.PathLike[str]"]


@dataclass(frozen=True)
class CompileReport:
    """What :func:`mco.compile` wrote."""

    output: str
    info: ModelInfo

    @property
    def sha256(self) -> str:
        return self.info.sha256

    @property
    def size_bytes(self) -> int:
        return self.info.size_bytes

    def to_dict(self) -> dict[str, Any]:
        return {"output": self.output, "info": self.info.to_dict()}


def compile(source: PathLike, output: PathLike, *, name: Optional[str] = None,
            build_id: Optional[str] = None, backend: str = "marco-kgpack",
            graphs: Optional[Sequence[str]] = None, language: Optional[str] = None,
            format: str = "compat", **options: Any) -> CompileReport:
    """Compile ``source`` into an ``.mco`` model file at ``output``.

    ``source`` is either an existing ``.kgpack`` (wrapped as-is, no runtime
    needed) or a MARCO source tree (``graphs/``, ``styles/``, ``axioms/``),
    compiled by ``backend``. ``graphs`` selects a subset of graph files by glob,
    relative to ``source`` (for example ``["graphs/graph_정산_*.kg"]``);
    ``language`` picks the language asset when the tree declares several.

    ``format`` picks the file written: ``"compat"`` (the default, the 0.1.0
    compatibility container, see :mod:`mco.formats`) or ``"native"`` (MCO
    Format 1, ``docs/mco/format-1.md``, run by the ``mco-native`` backend).

    The output is deterministic: the same inputs give byte-identical files.
    """
    source, output = Path(source), Path(output)
    if not source.exists():
        raise ModelNotFoundError(f"compile source not found: {source}")
    if output.resolve() == source.resolve():
        raise CompileError("output must differ from source")
    if format not in FORMATS:
        raise CompileError(f"unknown output format {format!r}; choose one of {', '.join(FORMATS)}")
    compiler = get_backend(backend)
    generator = f"mco {__version__}"

    def write(payload: bytes, name: Optional[str], recorded: Optional[str]) -> None:
        if format == "native":
            write_native(output, payload, name=name, build_id=build_id, generator=generator)
        else:
            write_compat(output, payload, name=name, build_id=build_id, backend=recorded or backend,
                         generator=generator)

    try:
        if source.is_file():
            if graphs or language:
                raise CompileError("graphs/language apply to source trees, not to an existing pack")
            file = detect(source)
            if file.kind == "mco-native":
                raise CompileError("native .mco files are already compiled")
            payload = file.payload_bytes()
            recorded = (file.manifest.get("runtime") or {}).get("backend") if file.manifest else None
            write(payload, name or (file.manifest or {}).get("name") or source.stem, recorded)
        else:
            if not compiler.accepts_source(source):
                raise CompileError(f"backend {backend!r} does not recognise {source} as a source tree")
            compile_options = dict(options)
            if graphs:
                compile_options["graphs"] = list(graphs)
            if language:
                compile_options["language"] = language
            with tempfile.TemporaryDirectory(prefix="mco-compile-") as scratch:
                payload = compiler.compile(source, Path(scratch) / "payload.kgpack", compile_options)
            write(payload, name or output.stem, None)
    except MCOError:
        raise
    except Exception as exc:
        raise CompileError(f"compilation failed: {type(exc).__name__}: {exc}") from exc
    return CompileReport(output=str(output), info=inspect(output))


def inspect(path: PathLike, *, verify: bool = True, overlay: Optional[PathLike] = None,
            marco_root: Optional[str] = None) -> ModelInfo:
    """Describe a model file without running it.

    Works without the MARCO runtime: ``ModelInfo.runnable`` then reports
    ``False`` and ``notes`` says why. With ``overlay``, the overlay store beside
    the model is read too (through the MARCO backend, which must be available):
    its base binding, head and active counts are added to ``notes`` and to
    ``manifest["overlay"]``; nothing is run.
    """
    file = detect(Path(path), verify=verify)
    info = select_backend(file).describe(file)
    if overlay is None:
        return info
    from .overlay import overlay_status
    status = overlay_status(path, overlay, marco_root=marco_root, verify=False)
    return info.replace(notes=info.notes + (overlay_note(status),),
                        manifest={**_thaw(info.manifest), "overlay": status})


def overlay_note(status: Any) -> str:
    """One line describing an overlay's binding, head and active counts."""
    base, head, c = status["base"], status["head"], status["counts"]
    return (f"overlay {status['path']}: bound to content {base['content_sha256'][:16]} build {base['build_id']}; "
            f"head seq {head['seq']}" + (f" ({head['change_id']})" if head["change_id"] else "")
            + f"; active nodes +{c['nodes_added']} -{c['nodes_tombstoned']}, edges +{c['edges_added']} "
              f"-{c['edges_tombstoned']}, rules +{c['rules_added']} ~{c['rules_replaced']} -{c['rules_disabled']}; "
              f"{status['pending']} pending candidate(s)")
