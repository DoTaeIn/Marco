"""MCO: a stable Python interface to MARCO-compatible reasoning models.

    import mco

    model = mco.load("MARCO-1.mco")
    result = model.run("밥값 나눠야 하는데")
    print(result.answer, result.status, result.evidence, result.trace, sep="\\n")

Everything importable from ``mco`` directly is the public, stable API. The
submodule ``mco.backends`` is the extension API for runtime authors. Nothing
here imports the MARCO engine until a model is loaded or compiled.
"""
from ._version import __version__
from .backends import available_backends, register_backend
from .benchmark import BenchmarkCase, BenchmarkReport, CaseResult, benchmark, load_cases
from .compiler import CompileReport, compile, inspect
from .errors import (BackendError, BackendUnavailableError, CompileError, IntegrityError,
                     InvalidInputError, MCOError, ModelClosedError, ModelFormatError,
                     ModelNotFoundError, OverlayBaseMismatchError, OverlayError, SnapshotError,
                     SnapshotFormatError, SnapshotMismatchError, UnsupportedFormatError, UnsupportedInputError)
from .info import Capability, ModelInfo
from .model import Model, Session, load
from .overlay import Overlay, create_overlay, open_overlay, overlay_status
from .result import Evidence, EvidenceList, Fact, ReasoningInput, Result, Status, Trace, TraceStep
from .snapshot import SnapshotInfo, inspect_snapshot

__all__ = [
    "__version__",
    # core
    "load", "compile", "inspect", "benchmark",
    "Model", "Session", "Result", "Status", "Evidence", "EvidenceList", "Trace", "TraceStep",
    "Fact", "ReasoningInput", "ModelInfo", "Capability", "CompileReport",
    "BenchmarkCase", "BenchmarkReport", "CaseResult", "load_cases",
    # conversation snapshots
    "inspect_snapshot", "SnapshotInfo",
    # overlay (Persistent Overlay Infrastructure)
    "create_overlay", "open_overlay", "overlay_status", "Overlay",
    # backends
    "available_backends", "register_backend",
    # errors
    "MCOError", "ModelNotFoundError", "ModelFormatError", "IntegrityError", "UnsupportedFormatError",
    "BackendError", "BackendUnavailableError", "CompileError", "InvalidInputError",
    "UnsupportedInputError", "ModelClosedError",
    "SnapshotError", "SnapshotFormatError", "SnapshotMismatchError",
    "OverlayError", "OverlayBaseMismatchError",
]
