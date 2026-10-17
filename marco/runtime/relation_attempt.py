"""L9 current relation-attempt acquisition (standalone, caller-serialized).

Acquisition only: one bounded capture of the installed private parser, the direct Context snapshot,
the L1 proposal and the incoming query record (or, when unknown_question is explicitly requested, the
native L1 query proposal for the unknown question). No proof evaluation, no Session hook, no learning
admission. The caller owns one serialized operation excluding concurrent respond/teach/retract/
reload/model replacement; nothing here proves that. The returned dict is disposable and holds a
private parser: never serialize it. Witness reports acquisition coherence only.
"""
import copy
import hashlib
import json
import math

from marco.language.relation_hypotheses import propose_relation_hypotheses
from marco.language import relation_query_hypotheses as _l1_query_module
from marco.language.relation_query_hypotheses import propose_relation_query_hypotheses
from marco.reasoning import inference as _inference
from marco.reasoning.context import ReasoningContext
from marco.reasoning.readings import ReadingUnavailable
from marco.reasoning.relation_hypotheses import (
    _Refuse, _valid_json, _validated_context, _validated_query, _validated_rules)
from marco.runtime.learning_dialogue import DialogueSession
from marco.runtime.source_snapshot import (
    SourceSnapshotError, _bound_is, _check_live, _check_providers, _check_types, capture_source_snapshot)
from marco.storage.overlay import dumps
from pack_model import PackModel
from relational_semantics import RelationalParser
import pack_model as _pack_model_module
import relational_semantics as _relational_module
from marco.language import relation_hypotheses as _l1_module
from marco.learning import memory as _memory_module
from marco.learning.memory import LearningMemory
from marco.reasoning import context as _context_module
from marco.reasoning import relation_hypotheses as _l5_module
from marco.runtime import learning_dialogue as _session_module
from marco.runtime import source_snapshot as _snapshot_module
from marco.runtime.learning_dialogue import _native_identity_equal
from marco.runtime.source_snapshot import SourceParserSnapshot
from marco.storage import overlay as _overlay_module
from marco.storage.overlay import OverlayStore
from marco.runtime import dialogue_trace as _trace_module
from marco.runtime.dialogue_trace import Attempt, DialogueTrace
from marco.trace import ledger as _ledger_module
from marco.trace.ledger import Ledger

SCHEMA = "marco-relation-attempt-acquisition-v1"
QUERY_SCHEMA = "marco-relation-query-attempt-acquisition-v1"
WITNESS_SCHEMA = "marco-relation-acquisition-witness-v1"
WITNESS_SCOPE = "current_native_acquisition_not_history_usage"
LOADER_SCOPE = "canonical_active_saved_expression_validation_replay"
_ID_CAP = 8192
_CANDIDATE_LIMIT = 16
_SOURCE_CHARS = 512
_SOURCE_WORDS = 40
_WITNESS_LIMIT = 16384
_PART_LIMIT = 262144
_PROJECTION_LIMIT = 1048576
_TOTAL_LIMIT = 2097152
_FIELD_LIMIT = 128

_CANON_QUERY = propose_relation_query_hypotheses
_CANON_SNAPSHOT = ReasoningContext.__dict__.get("snapshot")
_CANON_LEDGER = ReasoningContext.__dict__.get("_inference_ledger")
_SOURCE_REF_KEYS = {"index", "annotation_sha256", "graph_source"}
_CANON_FRESH = DialogueSession.__dict__.get("_fresh_parser")
_CANON_REVISION = DialogueSession.__dict__.get("_revision")
_CANON_MODEL_PARSER = PackModel.__dict__.get("parser")
_CANON_PROJECTION = PackModel.__dict__.get("language_projection")
_CANON_MEMORY_PARSER = LearningMemory.__dict__.get("parser")
_CANON_HEAD = OverlayStore.__dict__.get("head")
_CANON_META = OverlayStore.__dict__.get("meta")
_CANON_PARSE = RelationalParser.__dict__.get("parse")
_CANON_BINDING = SourceParserSnapshot.__dict__.get("binding")
_CANON_SNAPSHOT_FRESH = SourceParserSnapshot.__dict__.get("fresh_parser")
_CANON_CLOSURE = getattr(_inference, "closure_with_provenance", None)
_CANON_EXPORTS = {
    (_snapshot_module, "capture_source_snapshot"): capture_source_snapshot,
    (_snapshot_module, "SourceSnapshotError"): SourceSnapshotError,
    (_snapshot_module, "SourceParserSnapshot"): SourceParserSnapshot,
    (_snapshot_module, "_bound_is"): _bound_is,
    (_snapshot_module, "_check_live"): _check_live,
    (_snapshot_module, "_check_types"): _check_types,
    (_snapshot_module, "_check_providers"): _check_providers,
    (_snapshot_module, "_CANON_FRESH"): _CANON_FRESH,
    (_snapshot_module, "_CANON_MODEL_PARSER"): _CANON_MODEL_PARSER,
    (_snapshot_module, "_CANON_MEMORY_PARSER"): _CANON_MEMORY_PARSER,
    (_snapshot_module, "_CANON_HEAD"): _CANON_HEAD,
    (_snapshot_module, "_CANON_META"): _CANON_META,
    (_snapshot_module, "DialogueSession"): DialogueSession,
    (_snapshot_module, "PackModel"): PackModel,
    (_snapshot_module, "LearningMemory"): LearningMemory,
    (_snapshot_module, "OverlayStore"): OverlayStore,
    (_snapshot_module, "dumps"): dumps,
    (_l1_module, "propose_relation_hypotheses"): propose_relation_hypotheses,
    (_l5_module, "_Refuse"): _Refuse,
    (_l5_module, "_valid_json"): _valid_json,
    (_l5_module, "_validated_context"): _validated_context,
    (_l5_module, "_validated_query"): _validated_query,
    (_l5_module, "_validated_rules"): _validated_rules,
    (_inference, "closure_with_provenance"): _CANON_CLOSURE,
    (_session_module, "DialogueSession"): DialogueSession,
    (_session_module, "_native_identity_equal"): _native_identity_equal,
    (_context_module, "ReasoningContext"): ReasoningContext,
    (_pack_model_module, "PackModel"): PackModel,
    (_memory_module, "LearningMemory"): LearningMemory,
    (_overlay_module, "OverlayStore"): OverlayStore,
    (_overlay_module, "dumps"): dumps,
    (_relational_module, "RelationalParser"): RelationalParser,
}
_CANON_LOCAL_ALIASES = {
    name: obj for (_module, name), obj in _CANON_EXPORTS.items()
    if obj is not None and globals().get(name) is obj
}
_CANON_DESCRIPTORS = (
    (DialogueSession, "_fresh_parser", _CANON_FRESH),
    (DialogueSession, "_revision", _CANON_REVISION),
    (PackModel, "parser", _CANON_MODEL_PARSER),
    (PackModel, "language_projection", _CANON_PROJECTION),
    (LearningMemory, "parser", _CANON_MEMORY_PARSER),
    (OverlayStore, "head", _CANON_HEAD),
    (OverlayStore, "meta", _CANON_META),
    (ReasoningContext, "snapshot", _CANON_SNAPSHOT),
    (ReasoningContext, "_inference_ledger", _CANON_LEDGER),
    (RelationalParser, "parse", _CANON_PARSE),
    (SourceParserSnapshot, "binding", _CANON_BINDING),
    (SourceParserSnapshot, "fresh_parser", _CANON_SNAPSHOT_FRESH),
)
_CANON_OPEN = DialogueTrace.__dict__.get("_open")
_CANON_LEDGER_GET = Ledger.__dict__.get("get")
_CANON_LEDGER_EVENTS = Ledger.__dict__.get("events")
_CANON_TRACE_CLASSES = (
    (_trace_module, "Attempt", Attempt), (_trace_module, "DialogueTrace", DialogueTrace),
    (_ledger_module, "Ledger", Ledger))


class _Stop(Exception):
    def __init__(self, reason, stage, upstream=None):
        super().__init__(reason)
        self.reason, self.stage, self.upstream = reason, stage, upstream


def _text(value):
    return value[:_FIELD_LIMIT] if isinstance(value, str) else None


def _up(reason, stage=None, error_type=None):
    return {"reason": _text(reason) or "unknown", "stage": _text(stage), "error_type": _text(error_type)}


def _exc_up(reason, exc):
    return _up(reason, None, type(exc).__name__)


def _sha_text(text):
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _json_size(value):
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8"))


def _parser_sha(parser):
    return hashlib.sha256(dumps({"data": parser.data, "language_pack": parser.language_pack})
                          .encode("utf-8")).hexdigest()


def _head(store, stage):
    try:
        seq, change_id = store.head()
    except Exception as e:
        raise _Stop("owner_not_ready" if stage == "before" else "owner_changed", stage, _exc_up("invalid_head", e))
    if type(seq) is not int or seq < 0 or (seq == 0) != (change_id is None):
        raise _Stop("owner_not_ready" if stage == "before" else "owner_changed", stage, _up("invalid_head"))
    return seq, change_id


def _raw_effort(session, stage):
    effort = session.effort
    ok = effort is None or type(effort) in (bool, int, str) or (type(effort) is float and math.isfinite(effort))
    if not ok:
        raise _Stop("owner_not_ready", stage, _up("effort_not_json"))
    return effort


def _replay_key(context):
    return (tuple(context.observations),
            json.dumps(context.fills, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def _replay_ready(context):
    cache = context._replay_cache
    if cache is None or cache[0] != _replay_key(context):
        return False
    records, count = context._stored_event_records, context._event_records_count
    size = len(context.observations)
    if type(records) is not list or type(count) is not int or count != size:
        return False
    corrected = {r.get("index") for r in context.event_revisions
                 if isinstance(r, dict) and type(r.get("index")) is int}
    pending = set(range(count, size)) | {i for i in corrected if 0 <= i < size}
    return not pending


def _unread_rows(rows, text, at):
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict) and r.get("text") == text
            and type(r.get("at")) is int and r.get("at") == at]


def _trace_owner_ok(session, owner, stage):
    """Private mode: the original open native traced operation is current and coherent."""
    local = "owner_not_ready" if stage == "before" else "owner_changed"
    if type(owner) is not tuple or len(owner) != 4:
        raise _Stop(local, stage, _up("trace_owner_invalid"))
    active, attempt, recorder, query_text = owner
    if type(active) is not dict or session._active is not active:
        raise _Stop(local, stage, _up("trace_owner_replaced"))
    kind = active.get("trace_kind")
    if (active.get("trace_attempt") is not attempt or active.get("trace_recorder") is not recorder
            or session._recorder is not recorder or attempt is None or recorder is None or type(kind) is not str or kind != "respond"):
        raise _Stop(local, stage, _up("trace_owner_forged"))
    if any(canon is None or getattr(module, name, None) is not canon for module, name, canon in _CANON_TRACE_CLASSES):
        raise _Stop(local, stage, _up("engine_substitution"))
    if (Attempt is not _CANON_TRACE_CLASSES[0][2] or DialogueTrace is not _CANON_TRACE_CLASSES[1][2]
            or Ledger is not _CANON_TRACE_CLASSES[2][2]):
        raise _Stop(local, stage, _up("engine_substitution"))
    if (_CANON_OPEN is None or _CANON_LEDGER_GET is None or _CANON_LEDGER_EVENTS is None
            or DialogueTrace.__dict__.get("_open") is not _CANON_OPEN
            or Ledger.__dict__.get("get") is not _CANON_LEDGER_GET
            or Ledger.__dict__.get("events") is not _CANON_LEDGER_EVENTS):
        raise _Stop(local, stage, _up("provider_substitution"))
    if type(attempt) is not Attempt or type(recorder) is not DialogueTrace:
        raise _Stop(local, stage, _up("trace_owner_type"))
    opener = recorder._open
    if getattr(opener, "__func__", None) is not _CANON_OPEN or getattr(opener, "__self__", None) is not recorder:
        raise _Stop(local, stage, _up("provider_substitution"))
    ledger = recorder.ledger
    context = session.context
    if (type(ledger) is not Ledger or ledger is not session.trace_ledger or ledger is not context.trace
            or ledger.fsync is not True):
        raise _Stop(local, stage, _up("trace_ledger_invalid"))
    getter = ledger.get
    if (getattr(getter, "__func__", None) is not _CANON_LEDGER_GET or getattr(getter, "__self__", None) is not ledger
            or "get" in vars(ledger) or "events" in vars(ledger)):
        raise _Stop(local, stage, _up("provider_substitution"))
    if type(query_text) is not str or type(attempt.text) is not str or attempt.text != query_text:
        raise _Stop(local, stage, _up("trace_text_mismatch"))
    conversation = attempt.conversation
    if not (type(conversation) is str and conversation == recorder.conversation == session.conversation_id
            == context.conversation_id):
        raise _Stop(local, stage, _up("conversation_mismatch"))
    opener(attempt)


def _owners(session, stage, *, _trace_owner=None):
    """Canonical native owners and providers; any mismatch is a local owner refusal."""
    local = "owner_not_ready" if stage == "before" else "owner_changed"
    try:
        if any(globals().get(name) is not obj for name, obj in _CANON_LOCAL_ALIASES.items()):
            raise _Stop(local, stage, _up("engine_substitution"))
        if any(obj is None or getattr(module, name, None) is not obj
               for (module, name), obj in _CANON_EXPORTS.items()):
            raise _Stop(local, stage, _up("engine_substitution"))
        if any(canon is None or owner.__dict__.get(name) is not canon
               for owner, name, canon in _CANON_DESCRIPTORS):
            raise _Stop(local, stage, _up("provider_substitution"))
        if not callable(_CANON_CLOSURE) or getattr(_CANON_CLOSURE, "__module__", None) != _inference.__name__:
            raise _Stop(local, stage, _up("engine_substitution"))
        if type(session) is not DialogueSession:
            raise _Stop(local, stage, _up("invalid_session"))
        _check_live(session, stage)
        if (session._active is not None) if _trace_owner is None else (
                type(_trace_owner) is not tuple or not _trace_owner or session._active is not _trace_owner[0]):
            raise _Stop(local, stage, _up("session_active"))
        model = session.model
        memory, store = _check_types(session, model, stage)
        if store._db is None:
            raise _Stop(local, stage, _up("memory_closed"))
        _check_providers(session, model, memory, store, stage)
        if not _bound_is(session, "_revision", _CANON_REVISION) or "language_projection" in vars(model):
            raise _Stop(local, stage, _up("provider_substitution"))
        context = session.context
        if type(context) is not ReasoningContext or type(model) is not PackModel:
            raise _Stop(local, stage, _up("invalid_context"))
        if not (_bound_is(context, "snapshot", _CANON_SNAPSHOT)
                and _bound_is(context, "_inference_ledger", _CANON_LEDGER)):
            raise _Stop(local, stage, _up("provider_substitution"))
        if context.conversation_id != session.conversation_id:
            raise _Stop(local, stage, _up("conversation_mismatch"))
        effort = context.effort
        if type(effort) is not int or effort not in ReasoningContext.EFFORT_LEVELS:
            raise _Stop(local, stage, _up("invalid_context_effort"))
        _raw_effort(session, stage)
        if _trace_owner is not None:
            _trace_owner_ok(session, _trace_owner, stage)
        return model, memory, store, context
    except _Stop as e:
        if stage != "before" and e.reason == "owner_not_ready":
            raise _Stop(local, stage, e.upstream)
        raise
    except SourceSnapshotError as e:
        raise _Stop(local, stage, _up(e.code, e.stage, e.error_type))
    except Exception as e:
        raise _Stop(local, stage, _exc_up("owner_check_failed", e))


def _installed(session, context, stage):
    stale = "parser_not_current" if stage == "before" else "owner_changed"
    parser = context._parser_instance
    if type(parser) is not RelationalParser:
        raise _Stop(stale, stage, _up("parser_missing"))
    if not _bound_is(parser, "parse", _CANON_PARSE):
        raise _Stop(stale, stage, _up("provider_substitution"))
    try:
        installed = session._parser_revision
        counters = (installed, session._revision(), context.installed_memory_head)
        current = (all(type(c) is int and c >= 0 for c in counters)
                   and counters[1] == installed and counters[2] == installed
                   and _native_identity_equal(context.parser_base_sha256, session.base_sha256)
                   and _native_identity_equal(parser.effort, session.effort))
    except Exception as e:
        raise _Stop(stale, stage, _exc_up("parser_check_failed", e))
    if not current:
        raise _Stop(stale, stage, _up("installed_parser_stale"))
    return parser


def _endpoint(session, model, memory, store, context, parser, unread, stage):
    seq, change_id = _head(store, stage)
    projection = model.language_projection
    fingerprint = projection.get("fingerprint") if isinstance(projection, dict) else None
    return {
        "conversation_id": session.conversation_id,
        "turn_counter": session.turn_counter,
        "candidate_revision": session._revision(),
        "context_installed_revision": context.installed_memory_head,
        "memory_head": {"seq": seq, "change_id": change_id},
        "model_effective_key": model.effective_key,
        "parser_sha256": _parser_sha(parser),
        "projection_fingerprint": fingerprint if isinstance(fingerprint, str) else None,
        "unread": {"text_sha256": _sha_text(unread[0]), "at": unread[1]},
        "session_effort": _raw_effort(session, stage),
        "context_effort": context.effort,
    }


def _selected_index(parsed):
    selection = parsed.get("entry_selection")
    if type(selection) is not dict:
        raise _Stop("query_selection_invalid", "query", _up("selection_shape"))
    items = selection.get("items")
    if type(items) is not list or len(items) != 1 or type(items[0]) is not dict:
        raise _Stop("query_selection_invalid", "query", _up("selection_shape"))
    item = items[0]
    index = item.get("compiler_index")
    if type(index) is not int or index < 0:
        raise _Stop("query_selection_invalid", "query", _up("compiler_index"))
    targets = item.get("targets")
    if (type(targets) is not dict or targets.get("facts") != [] or type(targets.get("query")) is not list
            or len(targets["query"]) != 1 or type(targets["query"][0]) is not int or targets["query"][0] != 0):
        raise _Stop("query_selection_invalid", "query", _up("selection_targets"))
    return index


def _query_record(parser, query_text, projection):
    try:
        parsed = parser.parse(query_text, partial=True, events=True, repair=True, _entry_selection=True)
    except Exception as e:
        raise _Stop("query_unavailable", "query", _exc_up("parse_failed", e))
    if type(parsed) is not dict:
        raise _Stop("query_unavailable", "query", _up("parse_shape"))
    query, facts = parsed.get("query"), parsed.get("facts")
    if type(facts) is not list or facts or type(query) is not list or len(query) != 1:
        raise _Stop("query_selection_invalid", "query", _up("not_single_query"))
    index = _selected_index(parsed)
    rows = projection.get("query_sources")
    if type(rows) is not list:
        raise _Stop("query_selection_invalid", "query", _up("query_sources"))
    matches = [r for r in rows if type(r) is dict and type(r.get("index")) is int and r["index"] == index]
    if len(matches) != 1 or set(matches[0]) != _SOURCE_REF_KEYS:
        raise _Stop("query_selection_invalid", "query", _up("source_ref"))
    return {"source": query_text, "parsed": copy.deepcopy(parsed),
            "source_ref": {k: copy.deepcopy(matches[0][k]) for k in ("index", "annotation_sha256", "graph_source")}}


def _check_caps(snapshot, proposal, query, projection, binding):
    for value, limit in ((snapshot, _PART_LIMIT), (proposal, _PART_LIMIT), (query, _PART_LIMIT),
                         (projection, _PROJECTION_LIMIT), (binding, _PART_LIMIT)):
        if not _valid_json(value, byte_limit=limit):
            raise _Stop("input_limit", "caps", _up("carrier_limit"))
    if not _valid_json([snapshot, proposal, query, projection, binding], byte_limit=_TOTAL_LIMIT):
        raise _Stop("input_limit", "caps", _up("combined_limit"))


def _ledger_witness(snapshot):
    ledger = snapshot.get("inference_bundles") if isinstance(snapshot, dict) else None
    if not isinstance(ledger, dict):
        return None
    row = {"complete": ledger.get("complete"), "reason": ledger.get("reason"),
           "searches": copy.deepcopy(ledger.get("searches"))}
    return row if _valid_json(row, byte_limit=4096) else None


def _refusal_stop(refusal):
    reason = str(refusal)
    if reason.endswith("limit"):
        mapped = "input_limit"
    elif reason.startswith("unsupported"):
        mapped = "unsupported_capture"
    elif "query" in reason:
        mapped = "query_selection_invalid"
    else:
        mapped = "snapshot_unavailable"
    return _Stop(mapped, "validation", _up(reason, "validation", "_Refuse"))


def _query_provider(stage):
    if (getattr(_l1_query_module, "propose_relation_query_hypotheses", None) is not _CANON_QUERY
            or globals().get("propose_relation_query_hypotheses") is not _CANON_QUERY):
        if stage == "before":
            raise _Stop("owner_not_ready", "before", _up("engine_substitution"))
        raise _Stop("owner_changed", "after", _up("engine_substitution"))


def _query_caps(snapshot, proposal, query_proposal, projection, binding):
    for value, limit in ((snapshot, _PART_LIMIT), (proposal, _PART_LIMIT), (binding, 65536),
                         (projection, _PROJECTION_LIMIT), (query_proposal, _PROJECTION_LIMIT)):
        if not _valid_json(value, byte_limit=limit):
            raise _Stop("input_limit", "caps", _up("carrier_limit"))
    if not _valid_json([snapshot, proposal, query_proposal, projection, binding], byte_limit=_TOTAL_LIMIT):
        raise _Stop("input_limit", "caps", _up("combined_limit"))


def _query_gap_result(stop, w):
    result = _gap_result(stop, w)
    result["schema"] = QUERY_SCHEMA
    result["query_proposal"] = None
    return result


def _prepare(session, query_text, unread_text, unread_at, w, st, *, unknown_question=False, _trace_owner=None):
    for value in (query_text, unread_text):
        if type(value) is not str or not value.strip():
            raise _Stop("invalid_argument", "before")
        if len(value) > _SOURCE_CHARS or len(value.split()) > _SOURCE_WORDS:
            raise _Stop("input_limit", "before")
    if type(unread_at) is not int or unread_at < 0:
        raise _Stop("invalid_argument", "before")
    if unknown_question:
        _query_provider("before")

    model, memory, store, context = _owners(session, "before", _trace_owner=_trace_owner)
    parser = _installed(session, context, "before")
    if not _replay_ready(context):
        raise _Stop("snapshot_not_ready", "before", _up("replay_not_current"))
    rows = _unread_rows(context.unread, unread_text, unread_at)
    if not rows:
        raise _Stop("target_missing", "before")
    if len(rows) > 1:
        raise _Stop("target_ambiguous", "before")
    rows = copy.deepcopy(rows)
    unread = (unread_text, unread_at)
    try:
        w["before"] = _endpoint(session, model, memory, store, context, parser, unread, "before")
    except _Stop:
        raise
    except Exception as e:
        raise _Stop("owner_not_ready", "before", _exc_up("endpoint_failed", e))
    before = w["before"]
    replay_before = _replay_key(context)

    st[0] = "capture"
    try:
        captured = capture_source_snapshot(session, model=model, conversation_id=session.conversation_id)
        private = captured.fresh_parser(session)
        binding = captured.binding
    except SourceSnapshotError as e:
        raise _Stop("source_snapshot_gap", "capture", _up(e.code, e.stage, e.error_type))
    except Exception as e:
        raise _Stop("source_snapshot_gap", "capture", _exc_up("capture_failed", e))
    projection = model.language_projection
    if type(private) is not RelationalParser or type(binding) is not dict or type(projection) is not dict:
        raise _Stop("source_snapshot_gap", "capture", _up("carrier_invalid"))
    try:
        selected, memory_binding = binding["selected_model"], binding["installed_memory"]
        active = binding["active_parser"]
        coherent = (binding["conversation_id"] == session.conversation_id
                    and selected["effective_key"] == model.effective_key
                    and selected["content_fingerprint"] == model.content_fingerprint
                    and memory_binding["head"] == before["memory_head"]
                    and active["data_language_sha256"] == before["parser_sha256"]
                    and _parser_sha(private) == before["parser_sha256"]
                    and private.effort == session.effort
                    and ("effort" not in active or active["effort"] == session.effort)
                    and projection.get("fingerprint") == before["projection_fingerprint"])
    except Exception:
        coherent = False
    if not coherent:
        raise _Stop("parser_not_current", "capture", _up("binding_mismatch"))

    st[0] = "snapshot"
    w["context_snapshot_called"] = True
    try:
        snapshot = copy.deepcopy(context.snapshot(max_bundle_id_bytes=_ID_CAP))
    except ReadingUnavailable as e:
        raise _Stop("snapshot_unavailable", "snapshot", _exc_up("reading_unavailable", e))
    except Exception as e:
        raise _Stop("snapshot_unavailable", "snapshot", _exc_up("snapshot_failed", e))
    if type(snapshot) is not dict:
        raise _Stop("snapshot_unavailable", "snapshot", _up("snapshot_shape"))
    w["native_ledger"] = _ledger_witness(snapshot)
    ledger = snapshot.get("inference_bundles")
    if not isinstance(ledger, dict) or ledger.get("complete") is not True:
        raise _Stop("snapshot_incomplete", "snapshot",
                    _up(ledger.get("reason") if isinstance(ledger, dict) else "ledger_missing", "snapshot"))
    snap_rows = _unread_rows(snapshot.get("unread"), unread_text, unread_at)
    if not snap_rows:
        raise _Stop("target_missing", "snapshot")
    if len(snap_rows) > 1:
        raise _Stop("target_ambiguous", "snapshot")

    st[0] = "proposal"
    try:
        proposal = propose_relation_hypotheses(private, unread_text, projection=projection, binding=binding,
                                               candidate_limit=_CANDIDATE_LIMIT)
    except Exception as e:
        raise _Stop("proposal_unavailable", "proposal", _exc_up("proposal_failed", e))
    candidates = proposal.get("candidates") if isinstance(proposal, dict) else None
    if not isinstance(candidates, list) or (not candidates and not unknown_question):
        gaps = proposal.get("gaps") if isinstance(proposal, dict) else None
        first = gaps[0] if isinstance(gaps, list) and gaps and isinstance(gaps[0], dict) else {}
        raise _Stop("proposal_unavailable", "proposal", _up(first.get("reason") or "no_candidates", "proposal"))

    st[0] = "query"
    query_proposal = None
    if unknown_question:
        try:
            query_proposal = _CANON_QUERY(private, query_text, proposal=proposal, projection=projection,
                                          binding=binding, candidate_limit=_CANDIDATE_LIMIT)
        except Exception as e:
            raise _Stop("query_unavailable", "query", _exc_up("query_proposal_failed", e))
        if type(query_proposal) is not dict:
            raise _Stop("query_unavailable", "query", _up("carrier_invalid", "query"))
        query = None
    else:
        query = _query_record(private, query_text, projection)

    st[0] = "caps"
    if unknown_question:
        _query_caps(snapshot, proposal, query_proposal, projection, binding)
    else:
        _check_caps(snapshot, proposal, query, projection, binding)

    st[0] = "validation"
    try:
        facts, _sources = _validated_context(snapshot, unread_text, binding)
        if not unknown_question:
            triple = _validated_query(query, projection)
            _validated_rules(private, facts, candidates, triple)
    except _Refuse as refusal:
        raise _refusal_stop(refusal)

    st[0] = "after"
    w["after"] = None
    try:
        if unknown_question:
            _query_provider("after")
        after_owners = _owners(session, "after", _trace_owner=_trace_owner)
        after_parser = _installed(session, context, "after")
        if (after_owners != (model, memory, store, context) or after_parser is not parser
                or any(a is not b for a, b in zip(after_owners, (model, memory, store, context)))):
            raise _Stop("owner_changed", "after", _up("owner_replaced"))
        w["after"] = _endpoint(session, model, memory, store, context, parser, unread, "after")
        same = (_native_identity_equal(w["after"], before)
                and session.context is context and session.model is model and session.memory is memory
                and memory._store is store and context._parser_instance is parser
                and _replay_key(context) == replay_before and _replay_ready(context)
                and _native_identity_equal(_unread_rows(context.unread, unread_text, unread_at), rows)
                and ((session._active is None) if _trace_owner is None else (session._active is _trace_owner[0]))
                and _binding_current(session, model, memory, store, parser, private, binding, projection))
        _check_live(session, "after")
    except _Stop:
        raise
    except Exception as e:
        raise _Stop("owner_changed", "after", _exc_up("after_check_failed", e))
    if not same:
        raise _Stop("owner_changed", "after", _up("owner_drift"))

    fitted_witness = _fit(w)
    if fitted_witness is None:
        raise _Stop("input_limit", "caps", _up("witness_limit"))
    if unknown_question:
        return {"schema": QUERY_SCHEMA, "status": "ready", "parser": private, "context_snapshot": snapshot,
                "proposal": proposal, "query_record": None, "projection": projection, "binding": binding,
                "witness": fitted_witness, "gaps": [], "query_proposal": query_proposal}
    return {"schema": SCHEMA, "status": "ready", "parser": private, "context_snapshot": snapshot,
            "proposal": proposal, "query_record": query, "projection": projection, "binding": binding,
            "witness": fitted_witness, "gaps": []}


def _binding_current(session, model, memory, store, parser, private, binding, projection):
    """Native binding still describes the current owners; invalid native state is False or raises."""
    selected, installed_memory, active = binding["selected_model"], binding["installed_memory"], binding["active_parser"]
    fingerprint, effective_key = model.content_fingerprint, model.effective_key
    if type(fingerprint) is not str or type(effective_key) is not str:
        return False
    if not (selected["content_fingerprint"] == fingerprint and selected["effective_key"] == effective_key
            and selected["declaration_sha256"] == _sha_text(dumps(model.declaration))
            and selected["sources_sha256"] == _sha_text(dumps(model.sources))):
        return False
    base_sha = _sha_text(dumps({"data": memory._data, "language_pack": memory._pack}))
    if not (selected["base_parser_sha256"] == base_sha and session.base_sha256 == base_sha
            and memory._graph_binding == fingerprint):
        return False
    seq, change_id = store.head()
    if not _native_identity_equal({"seq": seq, "change_id": change_id}, installed_memory["head"]):
        return False
    meta = store.meta()
    expected = _sha_text(dumps({"data": memory._data, "language_pack": memory._pack, "graph_binding": fingerprint}))
    if not (meta.get("base_sha256") == installed_memory["base_store_sha256"]
            and meta.get("base_build_id") == installed_memory["base_build_id"]
            and meta.get("base_sha256") == expected
            and meta.get("format_version") == "1"
            and str(meta.get("overlay_schema")) == str(_overlay_module.OVERLAY_SCHEMA)):
        return False
    active_sha = active["data_language_sha256"]
    if not (_parser_sha(parser) == active_sha and _parser_sha(private) == active_sha):
        return False
    effort = session.effort
    if not (_native_identity_equal(parser.effort, effort) and _native_identity_equal(private.effort, effort)):
        return False
    if "effort" in active and not _native_identity_equal(active["effort"], effort):
        return False
    current = model.language_projection
    if not _valid_json(current, byte_limit=_PROJECTION_LIMIT):
        return False
    return bool(_native_identity_equal(current, projection))


def _fit(w):
    if w["before"] is None:
        return None
    witness = dict(w)
    if _valid_json(witness, byte_limit=_WITNESS_LIMIT):
        return witness
    witness["native_ledger"] = None
    if _valid_json(witness, byte_limit=_WITNESS_LIMIT):
        return witness
    return None


def _gap_result(stop, w):
    upstream = stop.upstream
    gap = {"reason": stop.reason, "stage": stop.stage, "upstream": upstream}
    return {"schema": SCHEMA, "status": "gap", "parser": None, "context_snapshot": None, "proposal": None,
            "query_record": None, "projection": None, "binding": None, "witness": _fit(w), "gaps": [gap]}


def prepare_relation_attempt(session, query_text, *, unread_text, unread_at, unknown_question=False):
    """One caller-serialized acquisition of the current selected relation attempt, or exactly one gap."""
    w = {"schema": WITNESS_SCHEMA, "scope": WITNESS_SCOPE, "before": None, "after": None,
         "context_snapshot_called": False, "bundle_id_cap": _ID_CAP, "native_ledger": None,
         "loader_scope": LOADER_SCOPE}
    st = ["before"]
    if type(unknown_question) is not bool:
        return _gap_result(_Stop("invalid_argument", "before"), w)
    try:
        return _prepare(session, query_text, unread_text, unread_at, w, st, unknown_question=unknown_question)
    except _Stop as stop:
        return _query_gap_result(stop, w) if unknown_question else _gap_result(stop, w)
    except Exception as e:
        stop = _Stop("acquisition_failed", st[0], _exc_up("acquisition_failed", e))
        return _query_gap_result(stop, w) if unknown_question else _gap_result(stop, w)


def _prepare_relation_attempt_owned(session, query_text, *, unread_text, unread_at, active,
                                    unknown_question=False):
    """Private: the same acquisition inside one genuine open native traced operation."""
    w = {"schema": WITNESS_SCHEMA, "scope": WITNESS_SCOPE, "before": None, "after": None,
         "context_snapshot_called": False, "bundle_id_cap": _ID_CAP, "native_ledger": None,
         "loader_scope": LOADER_SCOPE}
    st = ["before"]
    if type(unknown_question) is not bool:
        return _gap_result(_Stop("invalid_argument", "before"), w)
    try:
        if type(active) is not dict:
            raise _Stop("owner_not_ready", "before", _up("trace_owner_invalid"))
        owner = (active, active.get("trace_attempt"), active.get("trace_recorder"), query_text)
        return _prepare(session, query_text, unread_text, unread_at, w, st, unknown_question=unknown_question,
                        _trace_owner=owner)
    except _Stop as stop:
        return _query_gap_result(stop, w) if unknown_question else _gap_result(stop, w)
    except Exception as e:
        stop = _Stop("acquisition_failed", st[0], _exc_up("acquisition_failed", e))
        return _query_gap_result(stop, w) if unknown_question else _gap_result(stop, w)
