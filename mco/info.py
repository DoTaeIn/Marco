"""Model metadata returned by :func:`mco.inspect` and ``Model.info``."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Optional

from .result import _freeze, _thaw

__all__ = ["ModelInfo", "Capability"]


class Capability:
    """Stable capability names a backend may advertise in ``ModelInfo.capabilities``."""

    TEXT_INPUT = "text_input"          #: ``Model.run(str)``
    MULTI_TURN = "multi_turn"          #: state carries across ``run`` calls in a session
    TEXT_FACTS = "text_facts"          #: ``Model.reason`` with sentence facts
    STRUCTURED_FACTS = "structured_facts"  #: ``Model.reason`` with subject/predicate/value facts
    APPROVAL_PLANS = "approval_plans"  #: may return ``Status.PENDING_APPROVAL``
    NETWORK = "network"                #: may consult external sources when enabled
    SNAPSHOT = "snapshot"              #: ``Session.snapshot`` and ``Model.resume`` (conversation snapshots)


@dataclass(frozen=True)
class ModelInfo:
    """What a model file is and what can run it. Reading it never executes the model.

    ``format`` is one of ``"mco-compat"`` (the interim ``.mco`` container that
    embeds a ``.kgpack``), ``"kgpack"`` (a bare MARCO pack) or ``"mco-native"``
    (the future MCO binary format).
    """

    path: str
    format: str
    format_version: Optional[int]
    size_bytes: int
    sha256: str
    name: Optional[str] = None
    build_id: Optional[str] = None
    backend: Optional[str] = None
    language: Optional[str] = None
    languages: tuple[str, ...] = ()
    graphs: int = 0
    assets: int = 0
    fingerprint: Optional[str] = None
    verified: bool = False
    runnable: bool = False
    capabilities: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    #: Native manifest data. Backend/format specific; not stable.
    manifest: Mapping[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "languages", tuple(self.languages))
        object.__setattr__(self, "capabilities", tuple(self.capabilities))
        object.__setattr__(self, "notes", tuple(self.notes))
        object.__setattr__(self, "manifest", _freeze(self.manifest))

    def supports(self, capability: str) -> bool:
        return capability in self.capabilities

    def to_dict(self, *, include_manifest: bool = False) -> dict[str, Any]:
        data = {
            "path": self.path, "format": self.format, "format_version": self.format_version,
            "size_bytes": self.size_bytes, "sha256": self.sha256, "name": self.name,
            "build_id": self.build_id, "backend": self.backend, "language": self.language,
            "languages": list(self.languages), "graphs": self.graphs, "assets": self.assets,
            "fingerprint": self.fingerprint, "verified": self.verified, "runnable": self.runnable,
            "capabilities": list(self.capabilities), "notes": list(self.notes),
        }
        if include_manifest:
            data["manifest"] = _thaw(self.manifest)
        return data

    def replace(self, **changes: Any) -> "ModelInfo":
        from dataclasses import replace
        return replace(self, **changes)
