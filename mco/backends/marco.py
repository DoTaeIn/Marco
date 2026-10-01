"""Compatibility backend: runs ``.kgpack`` payloads on the existing MARCO engine.

This is the only module in ``mco`` that imports MARCO. It imports MARCO lazily,
on first :meth:`MarcoKgpackBackend.open` or :meth:`compile`, and confines every
MARCO-specific name (verdict labels, trace keys, ``AppState``) to this file.

Locating the runtime, in order:

1. the ``marco_root`` option passed to :func:`mco.load` / :func:`mco.compile`;
2. the ``MCO_MARCO_ROOT`` environment variable;
3. MARCO modules already importable on ``sys.path``;
4. the source checkout this package sits in (development layout).

Runtime behaviour:

* The pack is read-only. Learned knowledge goes to an overlay directory, a
  per-model temporary directory unless ``overlay_dir`` is given.
* Network research is **off** by default. Unknown questions are reported as
  :attr:`~mco.Status.UNKNOWN` instead of triggering web lookups. Pass
  ``allow_network=True`` to restore MARCO's research-and-plan behaviour.
* Each session owns its own MARCO ``AppState``: MARCO keeps some dialogue state
  per application object, so sharing one would leak state between sessions.
* An overlay store (``overlay=PATH``; ``docs/architecture/overlay.md``) holds
  explicit or approved graph and rule changes beside the model file. Every
  session reads it at the start of each turn. Its store lives in MARCO
  (``marco.storage.overlay``); :class:`MarcoOverlay` reaches it for ``mco.overlay``.
"""
from __future__ import annotations

from collections.abc import Mapping
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
from typing import Any, Optional
import uuid

from ..errors import (BackendError, BackendUnavailableError, CompileError, InvalidInputError,
                      ModelClosedError, OverlayBaseMismatchError, OverlayError)
from ..formats import ModelFile
from ..info import Capability, ModelInfo
from ..result import Evidence, EvidenceList, ReasoningInput, Result, Status, Trace, TraceStep
from .base import Backend, BackendModel, BackendSession, fallback_status, run_reasoning

__all__ = ["MarcoKgpackBackend", "MarcoModel", "OPTIONS", "CAPABILITIES"]

#: Options accepted by :func:`mco.load` for this backend.
OPTIONS = frozenset({"marco_root", "overlay_dir", "allow_network", "overlay"})
#: Options accepted by :func:`mco.compile` for this backend.
COMPILE_OPTIONS = frozenset({"marco_root", "graphs", "language"})

_KGPACK = "marco.storage.kgpack"
_REQUIRED_MODULES = (_KGPACK, "pack_model", "engine")
_UI_MODULE = "views.kgpack_ui"
_import_lock = threading.Lock()
_POOL_SIZE = 4
#: What a model run on the MARCO engine can do, whatever file it came from.
CAPABILITIES = (Capability.TEXT_INPUT, Capability.MULTI_TURN, Capability.TEXT_FACTS,
                Capability.APPROVAL_PLANS, Capability.NETWORK)


# --- MARCO verdict labels -> stable Status -----------------------------------
# These are identifiers of the MARCO engine's verdicts, not user-facing text.
_VERDICT_STATUS: dict[str, Status] = {
    # grounded answers
    "계산완료": Status.ANSWERED, "상태추론": Status.ANSWERED, "원문정의": Status.ANSWERED,
    "원문정의비교": Status.ANSWERED, "근거응답": Status.ANSWERED, "원문근거비교": Status.ANSWERED,
    "대화": Status.ANSWERED, "다중KG": Status.ANSWERED, "채택": Status.ANSWERED,
    # state recorded
    "상태기억": Status.OBSERVED,
    # progress, but more input is needed
    "A": Status.NEEDS_INPUT, "B1": Status.NEEDS_INPUT, "근거없음": Status.NEEDS_INPUT,
    "조건부족": Status.NEEDS_INPUT, "애매": Status.NEEDS_INPUT, "목표주장": Status.NEEDS_INPUT,
    # no grounded answer
    "미지": Status.UNKNOWN, "입력이해실패": Status.UNKNOWN, "근거불충분": Status.UNKNOWN,
    "지식부족": Status.UNKNOWN, "오류": Status.UNKNOWN,
    # positive evidence against
    "B2": Status.REJECTED, "C": Status.REJECTED, "수치미달": Status.REJECTED,
    "전제불성립": Status.REJECTED,
}
_ACCEPT = "인정"                       # evidence accepted; outcome depends on the goal
_GOAL_REACHED, _GOAL_COLLAPSED = "성립", "무너짐"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _status_for(verdict: Optional[str], answer: Mapping[str, Any]) -> Status:
    if verdict == _ACCEPT:
        outcome = answer.get("result")
        if outcome == _GOAL_REACHED:
            return Status.ANSWERED
        if outcome == _GOAL_COLLAPSED:
            return Status.REJECTED
        return Status.NEEDS_INPUT
    if verdict in _VERDICT_STATUS:
        return _VERDICT_STATUS[verdict]
    return fallback_status(answer.get("known"))


# --- runtime discovery ---------------------------------------------------------

def _is_marco_root(path: Path) -> bool:
    return (all(path.joinpath(*m.split(".")).with_suffix(".py").is_file() for m in _REQUIRED_MODULES)
            and (path / "views" / "kgpack_ui.py").is_file())


def _candidate_roots(explicit: Optional[str]) -> list[tuple[str, Path]]:
    roots = []
    if explicit:
        roots.append(("marco_root option", Path(explicit).expanduser()))
    env = os.environ.get("MCO_MARCO_ROOT")
    if env:
        roots.append(("MCO_MARCO_ROOT", Path(env).expanduser()))
    return roots


def _dev_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _find_root(explicit: Optional[str] = None) -> Optional[Path]:
    """The MARCO checkout to import from, or ``None`` if already importable."""
    for label, root in _candidate_roots(explicit):
        if not _is_marco_root(root):
            raise BackendUnavailableError(f"{label} does not point at a MARCO runtime: {root}")
        return root.resolve()
    if all(importlib.util.find_spec(m) is not None for m in _REQUIRED_MODULES):
        return None
    dev = _dev_root()
    if _is_marco_root(dev):
        return dev
    raise BackendUnavailableError(
        "the MARCO runtime was not found; set MCO_MARCO_ROOT to a MARCO checkout "
        "or pass marco_root=... to mco.load()/mco.compile()")


def _import(module: str, explicit_root: Optional[str] = None) -> Any:
    with _import_lock:
        root = _find_root(explicit_root)
        if root is not None and str(root) not in sys.path:
            sys.path.insert(0, str(root))
        # MARCO chooses its encoder from this variable; its own tools default it
        # the same way, and packs that declare an encoder override it.
        os.environ.setdefault("KG_ENCODER", "문자")
        try:
            return importlib.import_module(module)
        except ImportError as exc:
            raise BackendUnavailableError(f"cannot import MARCO module {module!r}: {exc}") from exc


# --- metadata without the runtime ------------------------------------------------

def _model_fingerprint(pack_manifest: Mapping[str, Any]) -> Optional[str]:
    """Same digest as MARCO ``PackModel.fingerprint``, computed from the manifest."""
    model = pack_manifest.get("model")
    if not isinstance(model, dict):
        return None
    digests = {f.get("path"): f.get("sha256") for f in pack_manifest.get("files", []) if isinstance(f, dict)}
    paths = ([model["language"]] if model.get("language") else []) + list(model.get("axioms") or []) + (
        [model["relational_model"]] if model.get("relational_model") else [])
    if any(p not in digests for p in paths):
        return None
    sources = [{"path": p, "sha256": digests[p]} for p in paths]
    return hashlib.sha256(json.dumps(sources, sort_keys=True).encode()).hexdigest()


class MarcoKgpackBackend(Backend):
    """Runs MARCO ``.kgpack`` models, bare or inside a compat ``.mco``."""

    name = "marco-kgpack"
    formats = ("mco-compat", "kgpack")
    priority = 10

    def availability(self) -> tuple[bool, str]:
        try:
            _find_root()
        except BackendUnavailableError as exc:
            return False, str(exc)
        return True, ""

    def describe(self, file: ModelFile) -> ModelInfo:
        pm = file.pack_manifest
        files = [f for f in pm.get("files", []) if isinstance(f, dict)]
        model = _mapping(pm.get("model"))
        manifest = file.manifest or {}
        usable, reason = self.availability()
        notes = []
        if file.kind == "mco-compat":
            notes.append("compatibility container: embeds a MARCO kgpack; not MCO Format 1")
        if not model:
            notes.append("pack predates model declarations: no language or axioms are declared")
        if not usable:
            notes.append(reason)
        return ModelInfo(
            path=str(file.path), format=file.kind, format_version=file.version,
            size_bytes=file.size_bytes, sha256=file.sha256,
            name=manifest.get("name") or file.path.stem, build_id=manifest.get("build_id"),
            backend=self.name, language=model.get("language"),
            languages=tuple(sorted(f["path"] for f in files
                                   if str(f.get("path", "")).startswith("styles/")
                                   and str(f.get("path", "")).endswith(".json"))),
            graphs=sum(1 for f in files if f.get("kind") == "graph"),
            assets=sum(1 for f in files if f.get("kind") != "graph"),
            fingerprint=_model_fingerprint(pm), verified=file.verified, runnable=usable,
            capabilities=CAPABILITIES,
            notes=tuple(notes),
            manifest={"mco": manifest, "kgpack": {k: v for k, v in pm.items() if k != "manager"}},
        )

    def open(self, file: ModelFile, options: Mapping[str, Any]) -> BackendModel:
        unknown = set(options) - OPTIONS
        if unknown:
            raise InvalidInputError(f"unknown option(s) for backend {self.name!r}: {sorted(unknown)}")
        return MarcoModel(self, file, dict(options))

    def open_overlay(self, file: ModelFile, path: Path, *, create: bool, writer: bool,
                     options: Mapping[str, Any]) -> "MarcoOverlay":
        """The overlay store of ``file`` at ``path`` (for :mod:`mco.overlay`)."""
        return MarcoOverlay(file, path, create=create, writer=writer, marco_root=options.get("marco_root"))

    def accepts_source(self, source: Path) -> bool:
        return source.is_dir() and (source / "graphs").is_dir()

    def compile(self, source: Path, output: Path, options: Mapping[str, Any]) -> bytes:
        unknown = set(options) - COMPILE_OPTIONS
        if unknown:
            raise InvalidInputError(f"unknown compile option(s) for backend {self.name!r}: {sorted(unknown)}")
        kgpack = _import(_KGPACK, options.get("marco_root"))
        root = source.resolve()
        graphs = options.get("graphs")
        if graphs:
            files: list[Path] = []
            for pattern in graphs:
                matched = sorted(root.glob(pattern))
                if not matched:
                    raise CompileError(f"no source files match {pattern!r} under {root}")
                files += matched
            for path in list(files):  # keep learned/collected records that belong to selected graphs
                if path.suffix == ".kg":
                    for extra in (path.with_suffix(".학습.jsonl"), path.with_suffix(".수집.jsonl")):
                        if extra.is_file():
                            files.append(extra)
            files = list(dict.fromkeys(files)) + kgpack.model_files(root)
        else:
            files = kgpack.default_file(root)
        try:
            kgpack.write_pack(output, files, root, language=options.get("language"))
        except kgpack.KGPackError as exc:
            raise CompileError(str(exc)) from exc
        return output.read_bytes()


# --- opened model and sessions ------------------------------------------------------

class MarcoModel(BackendModel):
    """A model running on the MARCO engine.

    Shared by ``marco-kgpack`` and ``mco-native``: ``backend`` describes the
    file and names the results. A bare ``.kgpack`` is opened in place; any other
    file kind hands over its pack through ``ModelFile.payload_bytes()``.
    """

    def __init__(self, backend: Backend, file: ModelFile, options: dict[str, Any]) -> None:
        self._backend = backend
        self._options = options
        self._ui = _import(_UI_MODULE, options.get("marco_root"))
        self._store_module = _import("marco.storage.conversations", options.get("marco_root"))
        self.info = backend.describe(file)
        self._workdir = Path(tempfile.mkdtemp(prefix="mco-marco-"))
        self._lock = threading.RLock()
        self._closed = False
        self._scratch: Optional[MarcoSession] = None
        # Opening a MARCO application re-reads and indexes the whole pack, so
        # closed sessions hand their (reset) application back for reuse.
        self._pool: list[Any] = []
        try:
            if file.kind == "kgpack":
                self._pack_path = file.path.resolve()
            else:
                self._pack_path = self._workdir / "model.kgpack"
                self._pack_path.write_bytes(file.payload_bytes())
            overlay = options.get("overlay_dir")
            self._overlay = Path(overlay).expanduser() if overlay else self._workdir / "overlay"
            self._graph_overlay = None
            if options.get("overlay"):
                self._graph_overlay = _attach(file, Path(options["overlay"]).expanduser(), options.get("marco_root"))
                self.info = self.info.replace(notes=self.info.notes + (_attached_note(self._graph_overlay),))
            # Opening one application validates the whole pack now, so a bad
            # model fails at load() rather than at the first run().
            self._pool.append(self._new_app())
        except BaseException:
            shutil.rmtree(self._workdir, ignore_errors=True)
            raise

    def _new_app(self) -> Any:
        extra = {"graph_overlay": self._graph_overlay} if self._graph_overlay is not None else {}
        try:
            app = self._ui.AppState(self._pack_path, overlay_root=self._overlay, **extra)
        except Exception as exc:
            raise BackendError(f"MARCO could not open {self.info.path}: {type(exc).__name__}: {exc}") from exc
        store = self._workdir / f"conversations-{uuid.uuid4().hex}.json"
        app.conversations = self._store_module.ConversationStore(store)
        if not self._options.get("allow_network", False):
            app.goals.research = _offline_research
        return app

    def _check(self) -> None:
        if self._closed:
            raise ModelClosedError("model is closed")

    def new_session(self) -> "MarcoSession":
        with self._lock:
            self._check()
            app = self._pool.pop() if self._pool else self._new_app()
            return MarcoSession(self, app)

    def _release(self, app: Any) -> None:
        """Take back a closed session's application; it was reset by the session."""
        with self._lock:
            if not self._closed and len(self._pool) < _POOL_SIZE:
                self._pool.append(app)

    def reason(self, data: ReasoningInput) -> Result:
        with self._lock:
            self._check()
            if self._scratch is None:
                self._scratch = self.new_session()
            scratch = self._scratch
        with scratch.lock:
            scratch.reset()
            try:
                return run_reasoning(scratch, self.info, data)
            finally:
                scratch.reset()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._scratch = None
            self._pool.clear()
            shutil.rmtree(self._workdir, ignore_errors=True)


def _offline_research(question: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
    """Stand-in for MARCO web research when the network is disabled."""
    return {"query": question, "search_terms": None, "sources": [], "verified": False,
            "diagnosis": "network_disabled",
            "need": {"kind": "external_fact", "topic": None, "resolved": False}}


class MarcoSession(BackendSession):
    def __init__(self, model: MarcoModel, app: Any) -> None:
        self._model = model
        self._app = app
        self.lock = threading.RLock()
        self._session_id = self._new_id()
        self._closed = False

    @staticmethod
    def _new_id() -> str:
        return "mco_" + uuid.uuid4().hex

    def run(self, text: str) -> Result:
        with self.lock:
            if self._closed or self._model._closed:
                raise ModelClosedError("session is closed")
            try:
                payload = self._app.turn(text, self._session_id)
            except Exception as exc:
                raise BackendError(f"MARCO failed on input {text!r}: {type(exc).__name__}: {exc}") from exc
            return translate(payload, text, self._model._backend.name)

    def reset(self) -> None:
        with self.lock:
            app, old = self._app, self._session_id
            app.reset()
            for table in ("reasoning_contexts", "understanding_history", "affect_sessions"):
                getattr(app, table, {}).pop(old, None)
            pending = getattr(app.goals, "pending", {})
            for key in [k for k in pending if isinstance(k, tuple) and k and k[0] == old]:
                pending.pop(key, None)
            self._session_id = self._new_id()

    def close(self) -> None:
        with self.lock:
            if self._closed:
                return
            self._closed = True
            if not self._model._closed:
                try:
                    self.reset()
                except Exception:
                    return      # an application that cannot be reset is not reused
                self._model._release(self._app)


# --- translation of MARCO payloads -----------------------------------------------------

def _plan_summary(plan: Mapping[str, Any]) -> str:
    labels = [str(a.get("label")) for a in plan.get("actions", []) if isinstance(a, Mapping) and a.get("label")]
    return "; ".join(labels)


def translate(payload: Mapping[str, Any], text: str, backend: str) -> Result:
    """Convert one ``AppState.turn`` payload into a public :class:`Result`."""
    phase = payload.get("phase")
    answer = _mapping(payload.get("answer"))
    trace = _mapping(answer.get("trace"))
    verdict = trace.get("verdict") or answer.get("verdict")
    plan = _mapping(payload.get("plan")) or None
    actions = list(plan.get("actions") or []) if plan else []

    if phase in ("plan", "research") and actions:
        status = Status.PENDING_APPROVAL
        answer_text = payload.get("web_answer") or answer.get("answer") or _plan_summary(plan or {})
    else:
        status = _status_for(verdict, answer)
        answer_text = answer.get("answer") or ""

    steps: list[TraceStep] = []
    understanding = payload.get("understanding") or {}
    primary = (understanding.get("overall") or {}).get("primary") or {}
    if primary:
        steps.append(TraceStep("understand", f"{primary.get('kind')} ({primary.get('confidence')})",
                               {"act": primary.get("kind"), "confidence": primary.get("confidence"),
                                "needs_clarification": understanding.get("needs_clarification"),
                                "unknown_parts": understanding.get("unknown_parts", [])}))
    route = _mapping(trace.get("route"))
    if route:
        candidates = [list(c) for c in route.get("candidates", [])[:3]]
        steps.append(TraceStep("route", f"{route.get('selected') or 'no graph'} (score {route.get('score')})",
                               {"selected": route.get("selected"), "selected_all": route.get("selected_all", []),
                                "score": route.get("score"), "candidates": candidates}))
    if trace:
        steps.append(TraceStep("judge", f"{trace.get('mode')}: {trace.get('winner')} -> {verdict}",
                               {"mode": trace.get("mode"), "winner": trace.get("winner"), "verdict": verdict,
                                "margin": trace.get("margin"), "goal_outcome": answer.get("result")}))
    reasoning = trace.get("reasoning") or answer.get("reasoning")
    if isinstance(reasoning, Mapping) and (reasoning.get("operator") or reasoning.get("transitions")):
        transitions = list(reasoning.get("transitions") or [])
        steps.append(TraceStep("reason", f"{reasoning.get('operator')}: {len(transitions)} transition(s)",
                               {"operator": reasoning.get("operator"), "transitions": transitions}))
    retrieval = trace.get("retrieval")
    if isinstance(retrieval, Mapping):
        steps.append(TraceStep("retrieval", str(retrieval.get("diagnosis")), dict(retrieval)))
    research = payload.get("research")
    if isinstance(research, Mapping):
        steps.append(TraceStep("research", f"{len(research.get('sources') or [])} source(s), "
                                           f"{research.get('diagnosis') or 'searched'}",
                               {k: research.get(k) for k in ("search_terms", "diagnosis", "verified", "need")}))
    if plan:
        steps.append(TraceStep("plan", f"{len(actions)} action(s) awaiting approval" if actions
                               else "no executable action",
                               {"plan_id": plan.get("plan_id"), "type": plan.get("type"),
                                "actions": actions, "unsupported": plan.get("unsupported", [])}))
    verification = trace.get("verification") or answer.get("verification")
    if isinstance(verification, Mapping):
        steps.append(TraceStep("verify", f"model {str(verification.get('model') or '')[:12]}, "
                                         f"{len(verification.get('checks') or [])} check(s)",
                               {"model": verification.get("model"), "sources": verification.get("sources", []),
                                "checks": verification.get("checks", [])}))

    evidence: list[Evidence] = []
    graph = route.get("selected") if route else None
    # Graph items an attached overlay added carry their change (Persistent Overlay Infrastructure);
    # base items carry nothing extra.
    origins = _mapping(trace.get("origins"))
    node_origin = _mapping(origins.get("nodes"))
    edge_origin = {tuple(e[:3]): e[3] for e in origins.get("edges") or []
                   if isinstance(e, (list, tuple)) and len(e) == 4}
    node = trace.get("evidence")
    if isinstance(node, Mapping) and node.get("name"):
        extra = {"detail": {"origin": node_origin[node["name"]]}} if node["name"] in node_origin else {}
        evidence.append(Evidence("graph_node", str(node["name"]), source=graph, score=node.get("score"), **extra))
    for a, relation, b in (tuple(p) for p in trace.get("path", []) if isinstance(p, (list, tuple)) and len(p) == 3):
        detail = {"from": a, "relation": relation, "to": b}
        if (a, relation, b) in edge_origin:
            detail["origin"] = edge_origin[(a, relation, b)]
        evidence.append(Evidence("graph_path", f"{a} -{relation}-> {b}", source=graph, detail=detail))
    if isinstance(reasoning, Mapping):
        for item in reasoning.get("transitions") or []:
            if not isinstance(item, Mapping):
                continue
            span = _mapping(item.get("evidence"))
            turn = span.get("turn")
            where = f"turn {turn}" if turn is not None else None
            fact = item.get("fact")
            if isinstance(fact, (list, tuple)) and len(fact) == 3:   # a conclusion, not a change
                subject, predicate, value = fact
                evidence.append(Evidence("derived_fact", f"{subject}.{predicate} = {value}",
                                         source=where, detail=dict(item)))
                continue
            summary = span.get("text") or (f"{item.get('subject')}.{item.get('predicate')}: "
                                           f"{item.get('before')} -> {item.get('after')}")
            evidence.append(Evidence("state_transition", str(summary), source=where, detail=dict(item)))
    for item in trace.get("sources") or []:
        if isinstance(item, Mapping) and item.get("text"):
            evidence.append(Evidence("definition", str(item["text"]), source=item.get("source"),
                                     detail=dict(item)))
    if isinstance(research, Mapping):
        for item in research.get("sources") or []:
            if isinstance(item, Mapping):
                evidence.append(Evidence("external_source", str(item.get("title") or item.get("url") or ""),
                                         source=item.get("url"), detail=dict(item)))

    unique: list[Evidence] = []
    for item in evidence:          # MARCO may repeat a transition across trace fields
        if item not in unique:
            unique.append(item)
    evidence = unique
    raw = {k: v for k, v in payload.items() if k != "answer"}
    raw["answer"] = {k: v for k, v in answer.items() if k != "info"}
    return Result(answer=str(answer_text), status=status, evidence=EvidenceList(evidence),
                  trace=Trace(steps), input=text,
                  raw_status=verdict if phase == "answer" or not actions else phase,
                  backend=backend, raw=_jsonable(raw))


def _jsonable(value: Any) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except (TypeError, ValueError):
        return None


# --- overlay (Persistent Overlay Infrastructure) -------------------------------------------

def base_identity(file: ModelFile) -> tuple[str, str, str]:
    """``(content_sha256, build_id, format_version)`` an overlay of ``file`` is bound to.

    The content SHA-256 is the pack's content identity (its canonical manifest), the same
    for a Format 1 file and the pack it holds; the build id is the file's, or for a bare
    ``.kgpack`` ``sha256-`` plus the first 12 hex digits of the file's SHA-256."""
    manifest = file.manifest or {}
    if file.kind == "mco-native":
        version = ".".join(str(x) for x in manifest.get("format_version") or ())
        return manifest["content_sha256"], manifest["build_id"], "mco-" + version
    text = json.dumps(file.pack_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    content = hashlib.sha256((text + "\n").encode("utf-8")).hexdigest()
    if file.kind == "mco-compat":
        return content, manifest.get("build_id") or "sha256-" + file.sha256[:12], f"compat-{file.version}"
    return content, "sha256-" + file.sha256[:12], f"kgpack-{file.version}"


def _overlay_error(exc: Exception) -> OverlayError:
    cls = OverlayBaseMismatchError if type(exc).__name__ == "OverlayBaseMismatch" else OverlayError
    return cls(str(exc))


def _attach(file: ModelFile, path: Path, marco_root: Optional[str]) -> Any:
    """The overlay at ``path`` attached to ``file`` for reading at every turn."""
    graph_view = _import("marco.storage.graph_view", marco_root)
    content, build, _version = base_identity(file)
    try:
        return graph_view.OverlayAttachment(path, base_sha256=content, base_build_id=build)
    except graph_view.ov.OverlayError as exc:
        raise _overlay_error(exc) from exc


def _attached_note(attachment: Any) -> str:
    seq, change = attachment.head()
    return (f"overlay attached: {attachment.path} (bound to build {attachment.base_build_id}), head seq {seq}"
            + (f" ({change})" if change else ""))


def _pack_of(file: ModelFile) -> tuple[dict[str, Any], dict[str, bytes]]:
    import io
    import zipfile
    with zipfile.ZipFile(io.BytesIO(file.payload_bytes())) as zf:
        manifest = json.loads(zf.read("manifest.json"))
        return manifest, {item["path"]: zf.read(item["path"]) for item in manifest["files"]}


class MarcoOverlay:
    """The overlay store of one model, opened through MARCO for :mod:`mco.overlay`.

    Every write is checked against the model (``GraphView.check``) inside the store's
    transaction; a change the model cannot take is refused and nothing is written.
    Revisions a delta does not name are the target's current ones."""

    def __init__(self, file: ModelFile, path: Path, *, create: bool, writer: bool,
                 marco_root: Optional[str]) -> None:
        self._ov = _import("marco.storage.overlay", marco_root)
        self._gv = _import("marco.storage.graph_view", marco_root)
        self.path = str(path)
        self.content, self.build_id, version = base_identity(file)
        self._file = file
        self._base: Any = None
        try:
            if create:
                self._store = self._ov.OverlayStore.create(path, base_sha256=self.content,
                                                           base_build_id=self.build_id, format_version=version)
            else:
                self._store = self._ov.OverlayStore.open(path, base_sha256=self.content,
                                                         base_build_id=self.build_id, writer=writer)
        except self._ov.OverlayError as exc:
            raise _overlay_error(exc) from exc

    def _call(self, work: Any) -> Any:
        try:
            return work()
        except self._ov.OverlayError as exc:
            raise _overlay_error(exc) from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise OverlayError(f"{type(exc).__name__}: {exc}") from exc

    def base(self) -> Any:
        if self._base is None:
            manifest, members = _pack_of(self._file)
            self._base = self._gv.PackBase(manifest, members)
        return self._base

    def _check(self, store: Any) -> None:
        self._gv.GraphView(self.base(), store, base_build_id=self.build_id).check()

    def _requests(self, deltas: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ov, ids, store = self._ov, self._ov.ids, self._store
        out: list[dict[str, Any]] = []
        seen: dict[str, int] = {}

        def revision(kind: str, target: str, given: Any) -> int:
            if given is None:
                item = store.item(kind, target)
                given = seen.get(target, item["revision"] if item else 0)
            seen[target] = given + 1
            return given

        for d in deltas:
            op, given = d["op"], d.get("revision")
            if op == "ADD_NODE":
                data = {"layer": d.get("layer", "개념"), "examples": list(d.get("examples") or [])}
                if d.get("source"):
                    data["source"] = d["source"]
                rev = revision("node", ids.node_id(d["graph"], d["name"]), given)
                out.append(ov.add_node(d["graph"], d["name"], revision=rev, data=data))
            elif op in ("ADD_EDGE", "RETRACT_EDGE"):
                rev = revision("edge", ids.edge_id(d["graph"], d["src"], d["rel"], d["dst"]), given)
                if op == "ADD_EDGE":
                    data = {"list": d["list"]} if d.get("list") else None
                    out.append(ov.add_edge(d["graph"], d["src"], d["rel"], d["dst"], revision=rev, data=data))
                else:
                    out.append(ov.retract_edge(d["graph"], d["src"], d["rel"], d["dst"], revision=rev))
            elif op == "RETRACT_NODE":
                rev = revision("node", ids.node_id(d["graph"], d["name"]), given)
                out.append(self._gv.GraphView(self.base(), None).retract_node(d["graph"], d["name"], revision=rev))
            elif op in ("ADD_RULE", "REPLACE_RULE"):
                target = ids.rule_id(d["rule"])
                build = ov.add_rule if op == "ADD_RULE" else ov.replace_rule
                out.append(build(target, d["rule"], revision=revision("rule", target, given)))
            elif op == "DISABLE_RULE":
                target = ids.rule_id(d["rule_id"])
                out.append(ov.disable_rule(target, revision=revision("rule", target, given)))
            else:
                raise OverlayError(f"unknown overlay operation {op!r}")
        return out

    def commit(self, deltas: list[dict[str, Any]], *, approved_by: str, reason: str, actor: str, source: str,
               evidence: Any) -> dict[str, Any]:
        def work() -> dict[str, Any]:
            seq, change = self._store.commit(self._requests(deltas), actor=actor, source=source, reason=reason,
                                             approved_by=approved_by, evidence=evidence, check=self._check)
            return {"seq": seq, "change_id": change}
        return self._call(work)

    def propose(self, deltas: list[dict[str, Any]], *, actor: str, reason: str, source: str, evidence: Any) -> str:
        return self._call(lambda: self._store.propose(self._requests(deltas), actor=actor, source=source,
                                                      reason=reason, evidence=evidence, check=self._check))

    def approve(self, candidate_id: str, *, approved_by: str) -> dict[str, Any]:
        def work() -> dict[str, Any]:
            seq, change = self._store.approve(candidate_id, approved_by=approved_by, check=self._check)
            return {"seq": seq, "change_id": change}
        return self._call(work)

    def reject(self, candidate_id: str, *, rejected_by: str, reason: str) -> None:
        self._call(lambda: self._store.reject(candidate_id, rejected_by=rejected_by, reason=reason))

    def undo(self, change: Any, *, approved_by: str, reason: str, actor: str, source: str) -> dict[str, Any]:
        def work() -> dict[str, Any]:
            seq, cid = self._store.undo(change, actor=actor, source=source, reason=reason, approved_by=approved_by,
                                        check=self._check)
            return {"seq": seq, "change_id": cid}
        return self._call(work)

    def head(self) -> dict[str, Any]:
        seq, change = self._call(self._store.head)
        return {"seq": seq, "change_id": change}

    def counts(self) -> dict[str, int]:
        return self._call(self._store.counts)

    def history(self, target: str) -> list[dict[str, Any]]:
        return self._call(lambda: self._store.history(target))

    def candidates(self, status: Optional[str]) -> list[dict[str, Any]]:
        return self._call(lambda: self._store.candidates(status))

    def status(self) -> dict[str, Any]:
        meta = self._call(self._store.meta)
        return {"path": self.path,
                "base": {"content_sha256": meta["base_sha256"], "build_id": meta["base_build_id"],
                         "format_version": meta["format_version"]},
                "head": self.head(), "counts": self.counts(), "pending": len(self.candidates("pending"))}

    def close(self) -> None:
        self._store.close()
