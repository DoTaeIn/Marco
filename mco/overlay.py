"""Persistent Overlay Infrastructure through ``mco``: explicit graph and rule changes beside a model.

An overlay is one file beside a model file. It holds changes that were stated
explicitly or approved from outside, each with an approver identity; the model
file is never written. A model loaded with ``mco.load(model, overlay=path)`` reads
the overlay at the start of every turn, so a change committed here is used from the
next turn on, in the same process, with no recompile and no export::

    import mco
    from mco import overlay as ov

    mco.create_overlay("MARCO-1.mco", "MARCO-1.overlay")      # bound to this model's content and build
    with mco.open_overlay("MARCO-1.mco", "MARCO-1.overlay") as o:
        o.commit([ov.add_edge("graphs/graph_화분.kg", "잎시듦", "증명", "흙이말랐다")],
                 approved_by="owner", reason="observed in the greenhouse")
    model = mco.load("MARCO-1.mco", overlay="MARCO-1.overlay")

Nothing here makes, proposes or approves a change by itself: every change is one of
these calls, made by a caller who names the approver. The overlay is not learning;
how MARCO itself might discover changes is outside this module.

The store itself is MARCO's (``marco/storage/overlay.py``, design note
``docs/architecture/overlay.md``); ``mco`` reaches it through the MARCO backend.
Without a MARCO checkout these calls raise :class:`~mco.BackendUnavailableError`.
The delta builders below are plain dictionaries and need no runtime.
"""
from __future__ import annotations

import os
from pathlib import Path
from types import TracebackType
from typing import Any, Iterable, Mapping, Optional, Union

from .errors import InvalidInputError, OverlayError
from .native.ids import edge_id, graph_id, node_id, rule_id

__all__ = ["Overlay", "create_overlay", "open_overlay", "overlay_status",
           "add_node", "add_edge", "retract_edge", "retract_node", "add_rule", "replace_rule", "disable_rule",
           "OPS", "node_id", "edge_id", "graph_id", "rule_id"]

PathLike = Union[str, "os.PathLike[str]"]

#: The delta operations an overlay accepts.
OPS = ("ADD_NODE", "ADD_EDGE", "RETRACT_EDGE", "RETRACT_NODE", "ADD_RULE", "REPLACE_RULE", "DISABLE_RULE")


def _delta(op: str, revision: Optional[int], **fields: Any) -> dict[str, Any]:
    out = {"op": op, **{k: v for k, v in fields.items() if v is not None}}
    if revision is not None:
        out["revision"] = revision
    return out


def add_node(graph: str, name: str, *, examples: Iterable[str], layer: str = "개념",
             source: Optional[str] = None, revision: Optional[int] = None) -> dict[str, Any]:
    """ADD NODE ``name`` to ``graph`` in ``layer`` (``개념``, ``사례``, ``무관`` or ``공리``) with its
    example sentences. A node the base has is replaced (its layer and examples)."""
    return _delta("ADD_NODE", revision, graph=graph, name=name, examples=list(examples), layer=layer,
                  source=source)


def add_edge(graph: str, src: str, rel: str, dst: str, *, list: str = "엣지",
             revision: Optional[int] = None) -> dict[str, Any]:
    """ADD EDGE ``src -rel-> dst`` in ``graph``: an argument edge (``엣지``), or with ``list="개념엣지"``
    a hypernym edge (relation ``상위``)."""
    return _delta("ADD_EDGE", revision, graph=graph, src=src, rel=rel, dst=dst,
                  list=None if list == "엣지" else list)


def retract_edge(graph: str, src: str, rel: str, dst: str, *, revision: Optional[int] = None) -> dict[str, Any]:
    """RETRACT EDGE: hide the edge, in the base or the overlay, from the next turn on."""
    return _delta("RETRACT_EDGE", revision, graph=graph, src=src, rel=rel, dst=dst)


def retract_node(graph: str, name: str, *, revision: Optional[int] = None) -> dict[str, Any]:
    """RETRACT NODE: hide the node and, in the same change, every edge that touches it."""
    return _delta("RETRACT_NODE", revision, graph=graph, name=name)


def add_rule(rule: Mapping[str, Any], *, revision: Optional[int] = None) -> dict[str, Any]:
    """ADD RULE: a rule object (``id``, ``body``, ``head``); also re-enables a disabled rule."""
    return _delta("ADD_RULE", revision, rule=dict(rule))


def replace_rule(rule: Mapping[str, Any], *, revision: Optional[int] = None) -> dict[str, Any]:
    """REPLACE RULE: the rule with ``rule["id"]`` gets this body from the next turn on."""
    return _delta("REPLACE_RULE", revision, rule=dict(rule))


def disable_rule(rule: str, *, revision: Optional[int] = None) -> dict[str, Any]:
    """DISABLE RULE: the rule is not used from the next turn on."""
    return _delta("DISABLE_RULE", revision, rule_id=rule)


def _store(model: PathLike, overlay: PathLike, *, create: bool, writer: bool, marco_root: Optional[str],
           verify: bool) -> Any:
    from .backends import select_backend
    from .formats import detect
    file = detect(Path(model), verify=verify)
    backend = select_backend(file)
    opener = getattr(backend, "open_overlay", None)
    if opener is None:
        raise OverlayError(f"backend {backend.name!r} cannot apply an overlay")
    return opener(file, Path(overlay), create=create, writer=writer,
                  options={"marco_root": marco_root} if marco_root else {})


class Overlay:
    """An overlay opened for writing (one writer at a time). Use :func:`open_overlay`."""

    def __init__(self, inner: Any, model: PathLike, path: PathLike) -> None:
        self._inner = inner
        self.model = str(model)
        self.path = str(path)

    def commit(self, deltas: Iterable[Mapping[str, Any]], *, approved_by: str, reason: str,
               actor: Optional[str] = None, source: str = "mco", evidence: Any = None) -> dict[str, Any]:
        """Record one change, all of ``deltas`` or nothing, approved by ``approved_by``. It is
        checked against the model first; a change the model cannot take is refused and nothing
        is written. Returns ``{"seq", "change_id"}``."""
        return self._inner.commit(_list(deltas), approved_by=approved_by, reason=reason,
                                  actor=actor or approved_by, source=source, evidence=evidence)

    def propose(self, deltas: Iterable[Mapping[str, Any]], *, actor: str, reason: str, source: str = "mco",
                evidence: Any = None) -> str:
        """Store a candidate change. It changes nothing until :meth:`approve`. Returns its id."""
        return self._inner.propose(_list(deltas), actor=actor, reason=reason, source=source, evidence=evidence)

    def approve(self, candidate_id: str, *, approved_by: str) -> dict[str, Any]:
        """Make a pending candidate a change, approved by ``approved_by``. Returns ``{"seq", "change_id"}``."""
        return self._inner.approve(candidate_id, approved_by=approved_by)

    def reject(self, candidate_id: str, *, rejected_by: str, reason: str) -> None:
        """Reject a pending candidate; it is kept with the reason and never applies."""
        self._inner.reject(candidate_id, rejected_by=rejected_by, reason=reason)

    def undo(self, change: Union[int, str], *, approved_by: str, reason: str, actor: Optional[str] = None,
             source: str = "mco") -> dict[str, Any]:
        """Undo change ``change`` (its seq or change id) by a new compensating change."""
        return self._inner.undo(change, approved_by=approved_by, reason=reason, actor=actor or approved_by,
                                source=source)

    def head(self) -> dict[str, Any]:
        """``{"seq", "change_id"}`` of the newest change (``seq`` 0 when empty)."""
        return self._inner.head()

    def counts(self) -> dict[str, int]:
        """Active items at the head by kind and state; candidates are not counted."""
        return self._inner.counts()

    def history(self, target: str) -> list[dict[str, Any]]:
        """Every delta on ``target`` (a node id, edge id or rule id; see :func:`node_id`,
        :func:`edge_id`), oldest first, with its change's actor, approval and reason."""
        return self._inner.history(target)

    def candidates(self, status: Optional[str] = None) -> list[dict[str, Any]]:
        """Candidates (``pending``, ``approved``, ``rejected`` or all), oldest first."""
        return self._inner.candidates(status)

    def status(self) -> dict[str, Any]:
        """The base binding, head, counts and pending candidates, as :func:`overlay_status` gives."""
        return self._inner.status()

    def close(self) -> None:
        self._inner.close()

    def __enter__(self) -> "Overlay":
        return self

    def __exit__(self, exc_type: Optional[type[BaseException]], exc: Optional[BaseException],
                 tb: Optional[TracebackType]) -> None:
        self.close()


def _list(deltas: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(deltas, Mapping):
        raise InvalidInputError("deltas is a list of delta dictionaries (add_edge(...), ...), not one dictionary")
    out = [dict(d) for d in deltas]
    for d in out:
        if d.get("op") not in OPS:
            raise InvalidInputError(f"unknown overlay operation {d.get('op')!r}; one of {', '.join(OPS)}")
    return out


def create_overlay(model: PathLike, overlay: PathLike, *, marco_root: Optional[str] = None,
                   verify: bool = True) -> dict[str, Any]:
    """Create an empty overlay at ``overlay`` bound to ``model``'s content SHA-256 and build id.
    Refused if ``overlay`` exists. Returns :func:`overlay_status`."""
    store = _store(model, overlay, create=True, writer=True, marco_root=marco_root, verify=verify)
    try:
        return store.status()
    finally:
        store.close()


def open_overlay(model: PathLike, overlay: PathLike, *, marco_root: Optional[str] = None,
                 verify: bool = True) -> Overlay:
    """Open the overlay of ``model`` at ``overlay`` for writing. An overlay made for another
    model (another content or build) raises :class:`~mco.OverlayBaseMismatchError`."""
    return Overlay(_store(model, overlay, create=False, writer=True, marco_root=marco_root, verify=verify),
                   model, overlay)


def overlay_status(model: PathLike, overlay: PathLike, *, marco_root: Optional[str] = None,
                   verify: bool = True) -> dict[str, Any]:
    """Read an overlay without running the model: ``{"path", "base": {"content_sha256", "build_id",
    "format_version"}, "head": {"seq", "change_id"}, "counts", "pending"}``."""
    store = _store(model, overlay, create=False, writer=False, marco_root=marco_root, verify=verify)
    try:
        return store.status()
    finally:
        store.close()
