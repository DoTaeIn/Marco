"""B0 source parser snapshot carrier (L9 runtime).

Scope: B0 only. It captures the grammar *installed* in a live DialogueSession at one moment, as a
frozen attempt state (a private ordinary RelationalParser plus bounded detached JSON binding).
It is NOT complete source tracing, NOT proof of which historical memory owner produced the
state, and NOT usage evidence: no origin is claimed as used, and no candidate catalog is built.
It is not connected to SourceReader, adapters, Answerers, logging, admission or session edits,
and it never reads or writes user memory beyond the one canonical ``session._fresh_parser`` call.

Ownership checks are an in-process contract, not protection against private-attribute mutation
or replaced module code.
"""
import copy
import hashlib
import json
import math

from marco.language.entry_origins import validated_entry_origin
from marco.learning.memory import SCHEMA, LearningMemory
from marco.runtime.learning_dialogue import DialogueSession
from marco.storage import overlay
from marco.storage.overlay import OverlayStore, dumps
from pack_model import PackModel
from relational_semantics import RelationalParser

BINDING_SCHEMA = "marco-source-parser-snapshot-v1"
_BINDING_LIMIT = 65536
_OPTIONAL_LIMIT = 4096
_PREFIX = "source_snapshot_"
_TOKEN = object()

_CANON_FRESH = DialogueSession.__dict__.get("_fresh_parser")
_CANON_MODEL_PARSER = PackModel.__dict__.get("parser")
_CANON_MEMORY_PARSER = LearningMemory.__dict__.get("parser")
_CANON_HEAD = OverlayStore.__dict__.get("head")
_CANON_META = OverlayStore.__dict__.get("meta")


class SourceSnapshotError(Exception):
    """Safe error: only a code, a stage and optionally an exception type name."""

    def __init__(self, code, stage, error_type=None):
        self.code = _PREFIX + code if not str(code).startswith(_PREFIX) else str(code)
        self.stage = str(stage)
        self.error_type = error_type if isinstance(error_type, str) else None
        text = self.code + ":" + self.stage + (":" + self.error_type[:64] if self.error_type else "")
        super().__init__(text)


def _fail(code, stage, exc=None):
    return SourceSnapshotError(code, stage, type(exc).__name__ if exc is not None else None)


def _sha(value):
    return hashlib.sha256(dumps(value).encode("utf-8")).hexdigest()


def _bound_is(obj, name, canon):
    if canon is None:
        return False
    try:
        if name in getattr(obj, "__dict__", {}):
            return False
        method = getattr(obj, name)
        return getattr(method, "__self__", None) is obj and getattr(method, "__func__", None) is canon
    except Exception:
        return False


def _check_live(session, stage):
    if session._closed is not False:
        raise _fail("session_closed", stage)
    if session._persistence_failed is not False:
        raise _fail("persistence_failed", stage)


def _check_types(session, model, stage):
    if type(session) is not DialogueSession:
        raise _fail("invalid_session", stage)
    if type(model) is not PackModel:
        raise _fail("invalid_model", stage)
    if session.model is not model:
        raise _fail("model_mismatch", stage)
    memory = session.memory
    if type(memory) is not LearningMemory:
        raise _fail("invalid_memory", stage)
    store = memory._store
    if type(store) is not OverlayStore:
        raise _fail("invalid_store", stage)
    return memory, store


def _check_providers(session, model, memory, store, stage):
    if not (_bound_is(session, "_fresh_parser", _CANON_FRESH)
            and _bound_is(model, "parser", _CANON_MODEL_PARSER)
            and _bound_is(memory, "parser", _CANON_MEMORY_PARSER)
            and _bound_is(store, "head", _CANON_HEAD)
            and _bound_is(store, "meta", _CANON_META)):
        raise _fail("provider_substitution", stage)


def _head(store, stage):
    try:
        head = store.head()
    except Exception as e:
        raise _fail("invalid_head", stage, e)
    if not isinstance(head, tuple) or len(head) != 2:
        raise _fail("invalid_head", stage)
    seq, change_id = head
    if type(seq) is not int or seq < 0:
        raise _fail("invalid_head", stage)
    if seq == 0:
        if change_id is not None:
            raise _fail("invalid_head", stage)
    elif not isinstance(change_id, str) or not change_id.strip():
        raise _fail("invalid_head", stage)
    return seq, change_id


def _finite_json(value, limit):
    """Detached finite JSON copy of an optional value, or None when it is not finite/encodable/bounded."""
    try:
        detached = copy.deepcopy(value)
        text = json.dumps(detached, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(text.encode("utf-8")) > limit:
            return None, False
        return json.loads(text), True
    except Exception:
        return None, False


def _origin_summary(parser):
    """Summary from the FROZEN detached parser only; never mutates parser attributes."""
    gaps = ["actual_selection_not_executed"]
    out = {"scope": "installed_expression_origin_transport_only", "status": "partial"}
    try:
        present = hasattr(parser, "_entry_origins")
        out["vector_present"] = bool(present)
        vector = getattr(parser, "_entry_origins", None) if present else None
        examples = parser.data.get("examples") if isinstance(parser.data, dict) else None
        expected = len(examples) if isinstance(examples, list) else None
        if not present:
            gaps.append("origin_vector_absent")
            out["status"] = "unknown"
        elif not isinstance(vector, list):
            gaps.append("origin_vector_not_list")
            out["status"] = "unknown"
        elif expected is None or len(vector) != expected:
            gaps.append("origin_vector_misaligned")
            out["status"] = "unknown"
        else:
            known = unknown = 0
            valid = True
            for row in vector:
                if row is None:
                    unknown += 1
                    continue
                try:
                    if validated_entry_origin(row) is None:
                        raise ValueError("origin")
                except Exception:
                    valid = False
                    break
                known += 1
            if valid:
                out["known_entry_count"] = known
                out["unknown_entry_count"] = unknown
            else:
                gaps.append("origin_row_invalid")
                out["status"] = "unknown"
        diag = getattr(parser, "_learning_origin_provenance", None)
        status = diag.get("status") if isinstance(diag, dict) else None
        status_ok = False
        if isinstance(status, str) and len(status) <= 64:
            detached, status_ok = _finite_json(status, _OPTIONAL_LIMIT)
            if status_ok:
                out["transport_status"] = detached
        if not status_ok:
            gaps.append("origin_diagnostic_absent" if status is None else "origin_status_not_finite_json")
            out["status"] = "unknown"
    except Exception:
        gaps.append("origin_summary_failed")
        out["status"] = "unknown"
    out["gaps"] = gaps[:8]
    return out


def _effort(session):
    try:
        effort = getattr(session, "effort", None)
    except Exception:
        return None, False
    if effort is None:
        return None, True
    if isinstance(effort, float) and not math.isfinite(effort):
        return None, False
    return _finite_json(effort, _OPTIONAL_LIMIT)


class SourceParserSnapshot:
    """Frozen installed-grammar attempt state. Construct only via capture_source_snapshot."""

    __slots__ = ("_token_ok", "_session", "_model", "_memory", "_store", "_conversation_id", "_parser",
                 "_binding_json")

    def __init__(self, token, session, model, memory, store, conversation_id, parser, binding):
        if token is not _TOKEN:
            raise _fail("invalid_session", "construct")
        self._session, self._model, self._memory, self._store = session, model, memory, store
        self._conversation_id, self._parser = conversation_id, parser
        self._binding_json = binding
        self._token_ok = True

    @property
    def binding(self):
        return json.loads(self._binding_json)

    def fresh_parser(self, session):
        stage = "fresh"
        if type(session) is not DialogueSession:
            raise _fail("invalid_session", stage)
        if session is not self._session:
            raise _fail("session_mismatch", stage)
        try:
            if session.conversation_id != self._conversation_id:
                raise _fail("session_mismatch", stage)
            if session.model is not self._model or session.memory is not self._memory:
                raise _fail("owner_changed", stage)
            if self._memory._store is not self._store:
                raise _fail("owner_changed", stage)
            _check_live(session, stage)
            if self._store._db is None:
                raise _fail("memory_closed", stage)
            return copy.deepcopy(self._parser)
        except SourceSnapshotError:
            raise
        except Exception as e:
            raise _fail("detach_failed", stage, e)


def capture_source_snapshot(session, *, model, conversation_id):
    stage = "capture"
    try:
        return _capture(session, model, conversation_id)
    except SourceSnapshotError:
        raise
    except Exception as e:
        raise _fail("build_failed", stage, e)


def _capture(session, model, conversation_id):
    stage = "capture"
    memory, store = _check_types(session, model, stage)
    if not isinstance(conversation_id, str) or session.conversation_id != conversation_id:
        raise _fail("session_mismatch", stage)
    _check_live(session, stage)
    if store._db is None:
        raise _fail("memory_closed", stage)
    _check_providers(session, model, memory, store, stage)

    fingerprint = model.content_fingerprint
    # Group 2: complete selected binding captured BEFORE the active build.
    try:
        declaration_sha = _sha(model.declaration)
        sources_sha = _sha(model.sources)
        effective_key = model.effective_key
        if not isinstance(effective_key, str) or not isinstance(fingerprint, str):
            raise ValueError("identity")
    except Exception as e:
        raise _fail("binding_invalid", "binding", e)

    try:
        base = model.parser()
        base_sha = _sha({"data": base.data, "language_pack": base.language_pack})
        mem_sha = _sha({"data": memory._data, "language_pack": memory._pack})
    except Exception as e:
        raise _fail("build_failed", "base", e)
    if base_sha != mem_sha or base_sha != session.base_sha256:
        raise _fail("base_mismatch", "base")
    if memory._graph_binding != fingerprint:
        raise _fail("graph_binding_mismatch", "base")

    try:
        expected = _sha({"data": memory._data, "language_pack": memory._pack, "graph_binding": fingerprint})
        meta = store.meta()
        ok = (meta.get("base_sha256") == expected and meta.get("base_build_id") == SCHEMA
              and meta.get("format_version") == "1"
              and str(meta.get("overlay_schema")) == str(overlay.OVERLAY_SCHEMA))
    except Exception as e:
        raise _fail("invalid_store", "meta", e)
    if not ok:
        raise _fail("store_binding_mismatch", "meta")

    before = _head(store, "head_before")
    try:
        parser = session._fresh_parser()
    except Exception as e:
        raise _fail("build_failed", "active", e)
    # Group 1: check the native type, then FULL deepcopy before the coherent after-head endpoint.
    if type(parser) is not RelationalParser:
        raise _fail("invalid_active_parser", "active")
    try:
        parser = copy.deepcopy(parser)
    except Exception as e:
        raise _fail("detach_failed", "detach", e)
    try:
        active_sha = _sha({"data": parser.data, "language_pack": parser.language_pack})
    except Exception as e:
        raise _fail("invalid_active_parser", "active", e)

    # Group 5: optional summaries are bounded local gaps and never fail a valid parser.
    origins = _origin_summary(parser)
    effort, effort_ok = _effort(session)

    try:
        seq, change_id = before
        active = {"data_language_sha256": active_sha}
        if effort_ok:
            active["effort"] = effort
        else:
            active["metadata_gaps"] = ["effort_not_finite_json"]
        binding = {
            "schema": BINDING_SCHEMA,
            "state_scope": "frozen_attempt_state",
            "conversation_id": conversation_id,
            "selected_model": {
                "content_fingerprint": fingerprint,
                "effective_key": effective_key,
                "declaration_sha256": declaration_sha,
                "sources_sha256": sources_sha,
                "base_parser_sha256": base_sha,
            },
            "installed_memory": {
                "head": {"seq": seq, "change_id": change_id},
                "base_store_sha256": meta["base_sha256"],
                "base_build_id": meta["base_build_id"],
                "scope": "installed_attempt_state_not_usage",
            },
            "active_parser": active,
            "origins": origins,
        }
        text = json.dumps(binding, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
        if len(text.encode("utf-8")) > _BINDING_LIMIT:
            raise ValueError("budget")
    except Exception as e:
        raise _fail("binding_invalid", "binding", e)

    # Group 2: coherent after-head endpoint covers build, detach and binding assembly. No retry.
    after = _head(store, "head_after")
    if before != after:
        raise _fail("head_changed", "head_after")
    if session.model is not model or session.memory is not memory or memory._store is not store:
        raise _fail("owner_changed", "owner_after")
    _check_live(session, "owner_after")
    if store._db is None:
        raise _fail("memory_closed", "owner_after")
    try:
        mem_after = _sha({"data": memory._data, "language_pack": memory._pack})
    except Exception as e:
        raise _fail("build_failed", "base", e)
    if mem_after != base_sha or session.base_sha256 != base_sha:
        raise _fail("base_mismatch", "owner_after")
    try:
        model_same = (model.content_fingerprint == fingerprint and memory._graph_binding == fingerprint
                      and model.effective_key == effective_key
                      and _sha(model.declaration) == declaration_sha and _sha(model.sources) == sources_sha)
    except Exception as e:
        raise _fail("model_changed", "owner_after", e)
    if not model_same:
        raise _fail("model_changed", "owner_after")

    return SourceParserSnapshot(_TOKEN, session, model, memory, store, conversation_id, parser, text)
