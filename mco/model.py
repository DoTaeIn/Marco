"""The public model and session objects."""
from __future__ import annotations

import os
from pathlib import Path
import threading
from types import TracebackType
from typing import Any, Mapping, Optional, Sequence, Union

from .backends import select_backend
from .backends.base import BackendModel, BackendSession
from .errors import BackendError, InvalidInputError, MCOError, ModelClosedError, SnapshotError
from .formats import detect
from .info import ModelInfo
from .result import ReasoningInput, Result
from .snapshot import SnapshotInfo

__all__ = ["Model", "Session", "load"]

ReasoningData = Union[ReasoningInput, Mapping[str, Any], Sequence[Any]]
PathLike = Union[str, "os.PathLike[str]"]


def _check_text(text: object) -> str:
    if not isinstance(text, str):
        raise InvalidInputError(f"run() takes a str, got {type(text).__name__}")
    if not text.strip():
        raise InvalidInputError("input text is empty")
    return text.strip()


class Session:
    """An independent conversation with a model.

    State (values the user mentioned, the active topic) carries from one
    :meth:`run` to the next within a session and never crosses sessions.
    """

    def __init__(self, model: "Model", inner: BackendSession) -> None:
        self._model = model
        self._inner = inner
        self._closed = False
        self._lock = threading.RLock()

    def run(self, text: str) -> Result:
        """Send one utterance; return the model's :class:`~mco.Result`."""
        text = _check_text(text)
        with self._lock:
            self._check()
            try:
                return self._inner.run(text)
            except MCOError:
                raise
            except Exception as exc:  # never leak a backend's internal exception type
                raise BackendError(f"{type(exc).__name__}: {exc}") from exc

    def reset(self) -> None:
        """Forget this session's conversation state."""
        with self._lock:
            self._check()
            self._inner.reset()

    def snapshot(self, path: PathLike) -> SnapshotInfo:
        """Write this conversation to a snapshot file at ``path`` and describe it.

        The file holds the turns and the reasoning state, bound to the model's base
        identity; :meth:`Model.resume` or ``mco.load(..., snapshot=path)`` continues it,
        in this process or another. The same state gives the same bytes. Raises
        :class:`~mco.SnapshotError` when the backend cannot write snapshots."""
        with self._lock:
            self._check()
            try:
                return self._inner.snapshot(Path(path))
            except MCOError:
                raise
            except Exception as exc:
                raise SnapshotError(f"{type(exc).__name__}: {exc}") from exc

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._closed = True
                self._inner.close()

    @property
    def closed(self) -> bool:
        return self._closed or self._model.closed

    def _check(self) -> None:
        if self.closed:
            raise ModelClosedError("session is closed")

    def __enter__(self) -> "Session":
        return self

    def __exit__(self, exc_type: Optional[type[BaseException]], exc: Optional[BaseException],
                 tb: Optional[TracebackType]) -> None:
        self.close()


class Model:
    """A loaded MCO-compatible model. Create one with :func:`mco.load`.

    ``Model.run`` uses a default session, so consecutive calls form one
    conversation. Use :meth:`session` for independent conversations and
    :meth:`reason` for self-contained structured problems.
    """

    def __init__(self, inner: BackendModel) -> None:
        self._inner = inner
        self._closed = False
        self._lock = threading.RLock()
        self._default: Optional[Session] = None
        self._sessions: list[Session] = []

    @property
    def info(self) -> ModelInfo:
        """Metadata of this model (same as :func:`mco.inspect`)."""
        return self._inner.info

    @property
    def backend(self) -> str:
        return self.info.backend or ""

    @property
    def closed(self) -> bool:
        return self._closed

    def _check(self) -> None:
        if self._closed:
            raise ModelClosedError("model is closed")

    def session(self) -> Session:
        """Start a new, isolated conversation."""
        with self._lock:
            self._check()
            session = Session(self, self._inner.new_session())
            self._sessions.append(session)
            return session

    def resume(self, snapshot: PathLike, *, conversation: Optional[str] = None) -> Session:
        """A new session continuing the conversation saved in ``snapshot``.

        Refused with :class:`~mco.SnapshotMismatchError` if the snapshot was taken on another
        base (or with an overlay history that differs), and with
        :class:`~mco.SnapshotFormatError` if the file is damaged, truncated or of an unknown
        version or schema. ``conversation`` names one when the file holds several."""
        with self._lock:
            self._check()
            try:
                inner = self._inner.resume(Path(snapshot), conversation)
            except MCOError:
                raise
            except Exception as exc:
                raise SnapshotError(f"{type(exc).__name__}: {exc}") from exc
            session = Session(self, inner)
            self._sessions.append(session)
            return session

    def _default_session(self) -> Session:
        with self._lock:
            self._check()
            if self._default is None or self._default.closed:
                self._default = self.session()
            return self._default

    def run(self, text: str) -> Result:
        """Send one utterance to the model's default conversation."""
        return self._default_session().run(text)

    def reason(self, data: ReasoningData) -> Result:
        """Solve a self-contained problem given as structured data.

        ``data`` is a :class:`~mco.ReasoningInput`, a mapping
        ``{"facts": [...], "question": "..."}``, or a list of facts. Facts are
        strings in the model's language, :class:`~mco.Fact` objects or
        mappings. It runs in a fresh context: the default conversation is
        neither read nor changed.
        """
        request = ReasoningInput.coerce(data)
        with self._lock:
            self._check()
        try:
            return self._inner.reason(request)
        except MCOError:
            raise
        except Exception as exc:
            raise BackendError(f"{type(exc).__name__}: {exc}") from exc

    def reset(self) -> None:
        """Forget the default conversation's state."""
        with self._lock:
            self._check()
            if self._default is not None and not self._default.closed:
                self._default.reset()

    def close(self) -> None:
        """Release all resources. Further calls raise :class:`ModelClosedError`."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            for session in self._sessions:
                session.close()
            self._sessions.clear()
            self._inner.close()

    def __enter__(self) -> "Model":
        return self

    def __exit__(self, exc_type: Optional[type[BaseException]], exc: Optional[BaseException],
                 tb: Optional[TracebackType]) -> None:
        self.close()

    def __del__(self) -> None:  # best effort: remove temporary files
        try:
            self.close()
        except Exception:
            pass

    def __repr__(self) -> str:
        state = "closed" if self._closed else "open"
        return f"<mco.Model {self.info.name!r} format={self.info.format} backend={self.backend} {state}>"


def load(path: Union[str, "os.PathLike[str]"], *, backend: Optional[str] = None,
         verify: bool = True, snapshot: Optional[PathLike] = None, **options: Any) -> Model:
    """Load a model file (``.mco`` or ``.kgpack``) and return a :class:`Model`.

    ``backend`` forces a specific backend; by default the backend recorded in
    the file (or the best one accepting its format) is used. ``verify``
    checks every recorded size and SHA-256 before running. ``snapshot`` names a
    snapshot file written by :meth:`Session.snapshot`: the model's default
    conversation continues it (see :meth:`Model.resume` for the checks).
    Remaining keyword ``options`` are passed to the backend (for
    ``marco-kgpack``: ``allow_network``, ``overlay_dir``, ``marco_root``).
    """
    file = detect(Path(path), verify=verify)
    runtime = select_backend(file, backend)
    try:
        inner = runtime.open(file, options)
    except MCOError:
        raise
    except Exception as exc:  # never leak a backend's internal exception type
        raise BackendError(f"backend {runtime.name!r} failed to open {path}: "
                           f"{type(exc).__name__}: {exc}") from exc
    model = Model(inner)
    if snapshot is not None:
        try:
            model._default = model.resume(snapshot)
        except BaseException:
            model.close()
            raise
    return model
