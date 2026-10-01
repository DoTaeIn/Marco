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
* Each session is one MARCO conversation (a conversation id in a store bound to the
  model's base identity), so its turns and reasoning state can be written to a
  snapshot and resumed in another process (``marco.storage.snapshot``).
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
import zipfile

from .._version import __version__
from ..errors import (BackendError, BackendUnavailableError, CompileError, IntegrityError, InvalidInputError,
                      ModelClosedError, SnapshotError, SnapshotFormatError, SnapshotMismatchError)
from ..formats import ModelFile
from ..info import Capability, ModelInfo
from ..result import Evidence, EvidenceList, ReasoningInput, Result, Status, Trace, TraceStep
from ..snapshot import SnapshotInfo
from .base import Backend, BackendModel, BackendSession, fallback_status, run_reasoning

__all__ = ["MarcoKgpackBackend", "MarcoModel", "OPTIONS", "CAPABILITIES", "read_snapshot"]

#: Options accepted by :func:`mco.load` for this backend.
OPTIONS = frozenset({"marco_root", "overlay_dir", "allow_network"})
#: Options accepted by :func:`mco.compile` for this backend.
COMPILE_OPTIONS = frozenset({"marco_root", "graphs", "language"})

_KGPACK = "marco.storage.kgpack"
_SNAPSHOT = "marco.storage.snapshot"
_STORE = "marco.storage.conversations"
_REQUIRED_MODULES = (_KGPACK, "pack_model", "engine")
_UI_MODULE = "views.kgpack_ui"
_import_lock = threading.Lock()
_POOL_SIZE = 4
#: What a model run on the MARCO engine can do, whatever file it came from.
CAPABILITIES = (Capability.TEXT_INPUT, Capability.MULTI_TURN, Capability.TEXT_FACTS,
                Capability.APPROVAL_PLANS, Capability.NETWORK, Capability.SNAPSHOT)


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


# --- snapshots -----------------------------------------------------------------------------

def _snapshot_error(module: Any, exc: Exception) -> SnapshotError:
    """The public error for a MARCO snapshot or store refusal."""
    if isinstance(exc, (module.SnapshotBaseMismatch, module.SnapshotOverlayMismatch)):
        return SnapshotMismatchError(str(exc))
    if isinstance(exc, (module.SnapshotDamaged, module.SnapshotUnsupported)):
        return SnapshotFormatError(str(exc))
    return SnapshotError(str(exc))


def read_snapshot(path: Any, *, marco_root: Optional[str] = None) -> tuple[SnapshotInfo, Any]:
    """Read and verify a snapshot file: its :class:`~mco.SnapshotInfo` and the MARCO reader's object.

    Imports only ``marco.storage.snapshot`` (standard library); runs no model."""
    module = _import(_SNAPSHOT, marco_root)
    try:
        snap = module.read(path)
    except module.SnapshotError as exc:
        raise _snapshot_error(module, exc) from exc
    ids = tuple(c["id"] for c in snap.body["conversations"])
    return SnapshotInfo._from_summary(snap.summary(), ids), snap


def _base_identity(file: ModelFile, pack_path: Path) -> dict[str, Any]:
    """The base a conversation binds to: the SHA-256 of the pack's ``manifest.json``.

    For a native file that is its manifest's ``content_sha256`` (format-1.md 6.6); a compat
    file or a bare pack of the same content gets the same value."""
    with zipfile.ZipFile(pack_path) as zf:
        content = hashlib.sha256(zf.read("manifest.json")).hexdigest()
    manifest = file.manifest or {}
    if file.kind == "mco-native":
        if manifest.get("content_sha256") != content:
            raise IntegrityError(f"{file.path}: the rebuilt pack does not match the manifest's content_sha256")
        fmt = file.native.get("format") or {}
        version = f"{fmt.get('major')}.{fmt.get('minor')}"
        source = "MCO Format 1 manifest content_sha256"
    else:
        version = str(file.version)
        source = "sha256 of the pack's manifest.json (equals the Format 1 content_sha256 of the same pack)"
    return {"content_sha256": content, "build_id": manifest.get("build_id"), "format": file.kind,
            "format_version": version, "identity_source": source}


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
        self._store_module = _import(_STORE, options.get("marco_root"))
        self._snapshot_module = _import(_SNAPSHOT, options.get("marco_root"))
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
            # What a conversation binds to. No Persistent Overlay Infrastructure store is
            # attached to a session in this version, so the overlay part is "none".
            self._base = _base_identity(file, self._pack_path)
            self._binding = self._store_module.binding(self._base["content_sha256"], self._base["build_id"])
            self._runtime = f"mco {__version__}; backend {backend.name}"
            # Opening one application validates the whole pack now, so a bad
            # model fails at load() rather than at the first run().
            self._pool.append(self._new_app())
        except BaseException:
            shutil.rmtree(self._workdir, ignore_errors=True)
            raise

    def _new_app(self) -> Any:
        try:
            app = self._ui.AppState(self._pack_path, overlay_root=self._overlay)
        except Exception as exc:
            raise BackendError(f"MARCO could not open {self.info.path}: {type(exc).__name__}: {exc}") from exc
        app.conversations = self._new_store()
        if not self._options.get("allow_network", False):
            app.goals.research = _offline_research
        return app

    def _new_store(self) -> Any:
        """A conversation store of its own for one session, bound to this model's base."""
        path = self._workdir / f"conversations-{uuid.uuid4().hex}.json"
        return self._store_module.ConversationStore(path, self._binding)

    def _check(self) -> None:
        if self._closed:
            raise ModelClosedError("model is closed")

    def resume(self, path: Path, conversation: Optional[str] = None) -> "MarcoSession":
        """A new session continuing a snapshot's conversation, after its checks."""
        with self._lock:
            self._check()
        module = self._snapshot_module
        _info, snap = read_snapshot(path, marco_root=self._options.get("marco_root"))
        try:
            # No overlay is attached to a session in this version: a snapshot taken with one is refused.
            _status, records = snap.restore_states(self._base, None)
            wanted = snap.conversation(conversation)["id"]     # names one conversation, or the only one
        except module.SnapshotError as exc:
            raise _snapshot_error(module, exc) from exc
        record = next(r for r in records if r["id"] == wanted)
        session = self.new_session()
        try:
            session._adopt(record)
        except BaseException:
            session.close()
            raise
        return session

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
        # The MARCO conversation this session is; created at the first turn or snapshot.
        self._chat_id: Optional[str] = None
        self._closed = False

    @staticmethod
    def _new_id() -> str:
        return "mco_" + uuid.uuid4().hex

    def _check(self) -> None:
        if self._closed or self._model._closed:
            raise ModelClosedError("session is closed")

    def _chat(self) -> str:
        if self._chat_id is None:
            self._chat_id = self._app.conversations.create_chat()["id"]
        return self._chat_id

    def run(self, text: str) -> Result:
        with self.lock:
            self._check()
            try:
                payload = self._app.turn(text, self._session_id, conversation_id=self._chat())
            except Exception as exc:
                raise BackendError(f"MARCO failed on input {text!r}: {type(exc).__name__}: {exc}") from exc
            return translate(payload, text, self._model._backend.name)

    def snapshot(self, path: Path) -> SnapshotInfo:
        """Write this conversation (turns and reasoning state) to a snapshot file."""
        with self.lock:
            self._check()
            module, app = self._model._snapshot_module, self._app
            chat_id = self._chat()
            with app.lock, app.model.encoder.activate():
                chat = app.conversations.get_chat(chat_id)
                context = app.reasoning_contexts.get("chat_" + chat_id)
                try:
                    state = (context.snapshot() if context is not None
                             else app.conversations.reasoning_state(chat_id))
                except self._model._store_module.ConversationBaseMismatch as exc:
                    raise SnapshotMismatchError(str(exc)) from exc
            record = {key: chat.get(key) for key in ("id", "title", "created_at", "updated_at")}
            record.update(turns=chat["turns"], reasoning_state=state)
            try:
                module.write(path, base=self._model._base, conversations=[record], overlay=None,
                             runtime=self._model._runtime)
            except module.SnapshotError as exc:
                raise _snapshot_error(module, exc) from exc
            return read_snapshot(path, marco_root=self._model._options.get("marco_root"))[0]

    def _adopt(self, record: dict[str, Any]) -> None:
        """Take over a conversation from a checked snapshot record.

        The turns and reasoning state go into this session's store; the context is restored
        from it at the next turn, exactly as MARCO restores a saved conversation. The
        input-understanding history is not stored in a snapshot; it is regenerated here from
        the turns' user texts, in order, as the original turns built it."""
        with self.lock:
            self._check()
            app = self._app
            with app.lock, app.model.encoder.activate():
                store = app.conversations
                app.conversations = self._model._new_store()
                Path(store.path).unlink(missing_ok=True)
                self._chat_id = app.conversations.import_chat(record)["id"]
                understand = self._model._ui.input_understanding.understand
                history = app.understanding_history.setdefault("chat_" + self._chat_id, [])
                for turn in record.get("turns") or []:
                    history.append(understand(turn["user"], history, language_pack=app.language_pack))
                    del history[:-30]

    def reset(self) -> None:
        with self.lock:
            app, old = self._app, self._session_id
            app.reset()
            keys = {old} | ({"chat_" + self._chat_id} if self._chat_id else set())
            for table in ("reasoning_contexts", "understanding_history", "affect_sessions"):
                for key in keys:
                    getattr(app, table, {}).pop(key, None)
            pending = getattr(app.goals, "pending", {})
            for key in [k for k in pending if isinstance(k, tuple) and k and k[0] in keys]:
                pending.pop(key, None)
            if self._chat_id is not None:
                store = app.conversations
                app.conversations = self._model._new_store()
                Path(store.path).unlink(missing_ok=True)
                self._chat_id = None
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
    node = trace.get("evidence")
    if isinstance(node, Mapping) and node.get("name"):
        evidence.append(Evidence("graph_node", str(node["name"]), source=graph, score=node.get("score")))
    for a, relation, b in (tuple(p) for p in trace.get("path", []) if isinstance(p, (list, tuple)) and len(p) == 3):
        evidence.append(Evidence("graph_path", f"{a} -{relation}-> {b}", source=graph,
                                 detail={"from": a, "relation": relation, "to": b}))
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
