"""Placeholder for the native MCO Format 1 runtime.

The binary specification is not final. This backend claims ``mco-native``
files only so they fail with an explicit :class:`UnsupportedFormatError`
instead of being misread. A future release replaces it with a real reader
behind the same :class:`~mco.backends.base.Backend` contract.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ..errors import UnsupportedFormatError
from ..formats import ModelFile
from ..info import ModelInfo
from .base import Backend, BackendModel

_REASON = "the native MCO Format 1 runtime is not available in this version of mco"


class NativeMcoBackend(Backend):
    name = "mco-native"
    formats = ("mco-native",)

    def availability(self) -> tuple[bool, str]:
        return False, _REASON

    def describe(self, file: ModelFile) -> ModelInfo:
        return ModelInfo(path=str(file.path), format=file.kind, format_version=file.version,
                         size_bytes=file.size_bytes, sha256=file.sha256, backend=self.name,
                         runnable=False, notes=tuple(n for n in (file.refusal, _REASON) if n))

    def open(self, file: ModelFile, options: Mapping[str, Any]) -> BackendModel:
        raise UnsupportedFormatError(f"{file.path}: {_REASON}")
