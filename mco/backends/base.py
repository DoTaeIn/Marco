"""The backend contract.

A backend turns a detected model file into running sessions and translates its
native output into :class:`~mco.result.Result`. The public :class:`~mco.Model`
talks only to these three abstract classes, which is what lets the MARCO
``.kgpack`` engine be replaced by a native ``.mco`` runtime without changing
user code.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar, Optional

from ..errors import CompileError, SnapshotError, UnsupportedInputError
from ..formats import ModelFile
from ..info import Capability, ModelInfo
from ..result import Evidence, EvidenceList, ReasoningInput, Result, Status, Trace, TraceStep

__all__ = ["Backend", "BackendModel", "BackendSession", "run_reasoning"]


class BackendSession(ABC):
    """One independent conversation. State carries across ``run`` calls."""

    @abstractmethod
    def run(self, text: str) -> Result:
        """Process one utterance and return a translated :class:`Result`."""

    @abstractmethod
    def reset(self) -> None:
        """Forget all conversation state held by this session."""

    def close(self) -> None:
        """Release resources. Must be idempotent."""

    def snapshot(self, path: Path) -> Any:
        """Write this conversation's snapshot to ``path``; return a :class:`~mco.SnapshotInfo`.

        Optional: the default refuses with :class:`~mco.SnapshotError`."""
        raise SnapshotError(f"{type(self).__name__} cannot write snapshots")


class BackendModel(ABC):
    """An opened model. Creates sessions; owns shared resources."""

    #: Metadata of the opened model.
    info: ModelInfo

    @abstractmethod
    def new_session(self) -> BackendSession:
        """Return a fresh, isolated session."""

    def reason(self, data: ReasoningInput) -> Result:
        """Evaluate premises and a question in a fresh session.

        The default feeds each text fact as an utterance, then asks the
        question (see :func:`run_reasoning`). Backends with native structured
        input override this.
        """
        session = self.new_session()
        try:
            return run_reasoning(session, self.info, data)
        finally:
            session.close()

    def resume(self, path: Path, conversation: Optional[str] = None) -> BackendSession:
        """A session continuing the conversation saved in the snapshot at ``path``.

        Optional: the default refuses with :class:`~mco.SnapshotError`. An implementation
        refuses a snapshot of another base or overlay history, or a damaged one."""
        raise SnapshotError(f"{type(self).__name__} cannot resume snapshots")

    def close(self) -> None:
        """Release resources. Must be idempotent."""


class Backend(ABC):
    """A runtime able to open some model formats."""

    #: Stable identifier, recorded in compiled models and in ``Result.backend``.
    name: ClassVar[str]
    #: ``ModelFile.kind`` values this backend can open.
    formats: ClassVar[tuple[str, ...]] = ()
    #: Higher wins when several backends accept the same file.
    priority: ClassVar[int] = 0

    def availability(self) -> tuple[bool, str]:
        """``(True, "")`` if the runtime can be used here, else ``(False, reason)``."""
        return True, ""

    def accepts(self, file: ModelFile) -> bool:
        return file.kind in self.formats

    @abstractmethod
    def describe(self, file: ModelFile) -> ModelInfo:
        """Metadata for ``file``. Should not need the runtime to be importable."""

    @abstractmethod
    def open(self, file: ModelFile, options: Mapping[str, Any]) -> BackendModel:
        """Open ``file`` for execution."""

    def compile(self, source: Path, output: Path, options: Mapping[str, Any]) -> bytes:
        """Build a model payload from a source tree. Returns the payload bytes."""
        raise CompileError(f"backend {self.name!r} cannot compile source trees")

    def accepts_source(self, source: Path) -> bool:
        return False


def fallback_status(known: Optional[bool]) -> Status:
    """Status for a verdict a backend does not recognise."""
    return Status.ANSWERED if known else Status.UNKNOWN


def run_reasoning(session: BackendSession, info: ModelInfo, data: ReasoningInput) -> Result:
    """Feed ``data.facts`` into ``session`` as utterances, then ask ``data.question``.

    The caller provides a fresh session and owns its lifetime.
    """
    if any(f.structured for f in data.facts) and not info.supports(Capability.STRUCTURED_FACTS):
        raise UnsupportedInputError(
            f"backend {info.backend!r} accepts facts as sentences in the model's language; "
            "structured subject/predicate/value facts need a backend advertising "
            f"the {Capability.STRUCTURED_FACTS!r} capability")
    steps: list[TraceStep] = []
    evidence: list[Evidence] = []
    last: Optional[Result] = None
    for index, fact in enumerate(data.facts):
        assert fact.text is not None
        last = session.run(fact.text)
        steps.append(TraceStep("fact", f"#{index + 1} {last.status.value}: {fact.text}",
                               {"index": index, "id": fact.id, "text": fact.text,
                                "status": last.status.value, "raw_status": last.raw_status,
                                "answer": last.answer}))
        if last.status.grounded:
            evidence.append(Evidence("fact", fact.text, source=fact.id,
                                     detail={"index": index, "status": last.status.value}))
    if data.question is not None:
        last = session.run(data.question)
    assert last is not None  # ReasoningInput guarantees a fact or a question
    return Result(answer=last.answer, status=last.status,
                  evidence=EvidenceList(list(last.evidence) + [e for e in evidence if e not in last.evidence]),
                  trace=Trace(steps + list(last.trace)), input=data.question or data.facts[-1].text or "",
                  raw_status=last.raw_status, backend=last.backend, raw=last.raw)
