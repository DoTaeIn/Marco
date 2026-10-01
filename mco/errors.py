"""Exceptions raised by the public ``mco`` API.

Every error the package raises on purpose derives from :class:`MCOError`, so
callers can catch one type. Backend-internal exceptions are never allowed to
escape unwrapped: they are re-raised as :class:`BackendError` with the original
exception chained as ``__cause__``.
"""
from __future__ import annotations

__all__ = [
    "MCOError",
    "ModelNotFoundError",
    "ModelFormatError",
    "IntegrityError",
    "UnsupportedFormatError",
    "BackendError",
    "BackendUnavailableError",
    "CompileError",
    "InvalidInputError",
    "UnsupportedInputError",
    "ModelClosedError",
    "OverlayError",
    "OverlayBaseMismatchError",
]


class MCOError(Exception):
    """Base class for every error raised by ``mco``."""


class ModelNotFoundError(MCOError, FileNotFoundError):
    """The model path does not exist."""


class ModelFormatError(MCOError, ValueError):
    """The file is not a readable model (unknown, truncated or malformed)."""


class IntegrityError(ModelFormatError):
    """A recorded size or SHA-256 does not match the stored bytes."""


class UnsupportedFormatError(ModelFormatError):
    """The format is recognised, but no installed backend can execute it."""


class BackendError(MCOError):
    """A backend failed while opening or running a model."""


class BackendUnavailableError(BackendError):
    """The backend's runtime (for example the MARCO engine) cannot be found."""


class CompileError(MCOError):
    """Compilation into a model file failed."""


class InvalidInputError(MCOError, ValueError):
    """The input given to ``run``/``reason``/``benchmark`` is malformed."""


class UnsupportedInputError(InvalidInputError):
    """The input is well formed but the selected backend cannot accept it."""


class ModelClosedError(MCOError):
    """The model or session was used after :meth:`close`."""


class OverlayError(MCOError):
    """An overlay refused an operation (a stale revision, a second writer, a change the model
    cannot take, ...); nothing was written."""


class OverlayBaseMismatchError(OverlayError):
    """The overlay was made for another model (another content SHA-256 or build id)."""
