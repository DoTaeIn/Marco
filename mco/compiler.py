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


def inspect(path: PathLike, *, verify: bool = True) -> ModelInfo:
    """Describe a model file without running it.

    Works without the MARCO runtime: ``ModelInfo.runnable`` then reports
    ``False`` and ``notes`` says why.
    """
    file = detect(Path(path), verify=verify)
    return select_backend(file).describe(file)
