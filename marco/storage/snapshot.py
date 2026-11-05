"""Conversation snapshot and restore: one self-describing file, checked before it is used.

A snapshot fixes, at one point in time, what a conversation needs to continue in another
process: the base it ran on, the overlay sequence when an overlay is attached, the contract
(runtime, required features, state schemas), and per conversation its turns and its
reasoning state (``ReasoningContext.snapshot()``, unchanged). It is state and persistence
infrastructure: writing or restoring one changes no knowledge, and nothing here learns.
Design note: ``docs/architecture/snapshot.md``.

File layout (no pickle, nothing executable)::

    MARCO-SNAPSHOT/1 <body length> <sha256 of body, hex>\\n
    <body: canonical JSON, UTF-8, keys sorted, separators "," ":", no trailing newline>

The same state gives the same bytes. Writing is temp file + fsync + ``os.replace``, so a
reader sees the old file or the new one, never a part. Reading refuses, each with its own
class: a damaged or truncated file (``SnapshotDamaged``), an unknown version, feature or
state schema (``SnapshotUnsupported``), another base (``SnapshotBaseMismatch``), and an
overlay whose history differs from the recorded one (``SnapshotOverlayMismatch``).

Standard library only.
"""
import base64
from copy import deepcopy
import hashlib
import json
import os
import re
import sqlite3
import tempfile
import uuid

MAGIC = b"MARCO-SNAPSHOT/1"
FORMAT = "marco-snapshot"
VERSION = 1
#: Bodies above this are refused before they are parsed.
MAX_BODY = 1 << 30

#: Features a snapshot may require; a reader refuses one it does not know.
FEATURE_BASE = "base-binding/1"
FEATURE_TURNS = "conversation-turns/1"
FEATURE_STATE = "reasoning-context-state/1"
FEATURE_OVERLAY = "overlay-sqlite-copy/1"
FEATURE_ACTION = "contextual-action-state/1"
FEATURES = frozenset({FEATURE_BASE, FEATURE_TURNS, FEATURE_STATE, FEATURE_OVERLAY, FEATURE_ACTION})

TURNS_SCHEMA = "conversation-turns-v1"
ACTION_STATE_SCHEMA = "contextual-action-state-v1"
#: The reasoning state schemas ``ReasoningContext.restore`` accepts today.
REASONING_SCHEMAS = frozenset("reasoning-context-v%d" % n for n in range(1, 12))
STATE_SCHEMAS = REASONING_SCHEMAS | {TURNS_SCHEMA, ACTION_STATE_SCHEMA}

#: What a snapshot never holds, written into every snapshot so a reader does not have to guess.
EXCLUDED = (
    {"id": "caches", "reason": "replay, parser and index caches; rebuilt on demand"},
    {"id": "pending_plans", "reason": "plans awaiting approval are not carried; they are asked for again"},
    {"id": "persona_state", "reason": "persona state is not part of a conversation snapshot"},
    {"id": "affect_state", "reason": "expression (affect) state is memory-only by design"},
    {"id": "understanding_history", "reason": "input-understanding history; regenerable from the turns"},
    {"id": "graph_dialogue_session", "reason": "the routed graph and its filled slots; not serialisable here"},
    {"id": "learning_sidecars", "reason": "learned-record sidecars and the runtime's learning directory"},
)

_RECORD_KEYS = frozenset({"id", "title", "created_at", "updated_at", "turns", "reasoning_state",
                          "action_grounding_state"})
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_HEADER = re.compile(rb"MARCO-SNAPSHOT/1 ([1-9][0-9]{0,11}) ([0-9a-f]{64})\n")


class SnapshotError(ValueError):
    """A snapshot cannot be written, read or restored."""


class SnapshotDamaged(SnapshotError):
    """Not a snapshot, truncated, extended, or its bytes do not match the recorded digest."""


class SnapshotUnsupported(SnapshotError):
    """A snapshot version, required feature or state schema this reader does not know."""


class SnapshotBaseMismatch(SnapshotError):
    """The snapshot was taken on another base (``content_sha256`` or build id differs)."""


class SnapshotOverlayMismatch(SnapshotError):
    """The overlay is missing, shorter than the recorded seq, or holds another change at it."""


# --- canonical bytes ------------------------------------------------------------------------

def canonical(value):
    """Canonical JSON bytes: keys sorted, no whitespace, UTF-8, no NaN."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def _plain(value, what):
    """``value`` as JSON data exactly as a JSON store would give it back (keys become strings)."""
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as e:
        raise SnapshotError("%s is not plain JSON data: %s" % (what, e)) from None


def _sha(data):
    return hashlib.sha256(data).hexdigest()


# --- the parts ------------------------------------------------------------------------------

def base_record(*, content_sha256, build_id=None, format=None, format_version=None, identity_source=None):
    """The base a snapshot binds to. ``content_sha256`` is required (64 lower-case hex)."""
    if not isinstance(content_sha256, str) or not _HEX64.match(content_sha256):
        raise SnapshotError("base content_sha256 must be 64 lower-case hex digits, got %r" % (content_sha256,))
    for name, value in (("build_id", build_id), ("format", format), ("format_version", format_version),
                        ("identity_source", identity_source)):
        if value is not None and not isinstance(value, str):
            raise SnapshotError("base %s must be a string or None" % name)
    return {"content_sha256": content_sha256, "build_id": build_id, "format": format,
            "format_version": format_version, "identity_source": identity_source}


def _check_turn(turn, where):
    if (not isinstance(turn, dict) or not isinstance(turn.get("user"), str)
            or not isinstance(turn.get("assistant"), str)):
        raise SnapshotError("%s: a turn needs string 'user' and 'assistant'" % where)


def conversation_record(*, id, turns, reasoning_state=None, title=None, created_at=None, updated_at=None,
                        action_grounding_state=None):
    """One conversation: its turns and its reasoning state (the context's snapshot, unchanged)."""
    if not isinstance(id, str) or not id:
        raise SnapshotError("a conversation needs a non-empty string id")
    turns = _plain(list(turns), "turns of %s" % id)
    for turn in turns:
        _check_turn(turn, id)
    state = None
    if reasoning_state is not None:
        state = _plain(reasoning_state, "reasoning state of %s" % id)
        if not isinstance(state, dict) or state.get("schema") not in REASONING_SCHEMAS:
            raise SnapshotError("%s: reasoning state schema %r is not one this writer knows"
                                % (id, state.get("schema") if isinstance(state, dict) else None))
    record = {"id": id, "title": title, "created_at": created_at, "updated_at": updated_at,
              "turns": turns, "reasoning_state": state}
    if action_grounding_state is not None:
        record["action_grounding_state"] = _action_state_pair(action_grounding_state, state, id)
    return record


def _overlay_copy(path, base):
    """A consistent point-in-time copy of the overlay at ``path`` and the head inside that copy.

    ``Connection.backup`` with ``pages=-1`` copies every page in one step under one read
    transaction, so a commit running in another connection is either wholly in the copy or
    not in it. The recorded ``seq`` is read from the copy itself, so it always matches it.
    """
    path = os.fspath(path)
    if not os.path.isfile(path):
        raise SnapshotError("no overlay at %s" % path)
    source = sqlite3.connect(path, timeout=5.0, isolation_level=None)
    target = sqlite3.connect(":memory:", isolation_level=None)
    try:
        source.execute("PRAGMA query_only = ON")
        source.backup(target, pages=-1)
        data = target.serialize()
        try:
            meta = {k: v for k, v in target.execute("SELECT key, value FROM meta")}
            row = target.execute("SELECT seq, change_id FROM changes ORDER BY seq DESC LIMIT 1").fetchone()
        except sqlite3.DatabaseError as e:
            raise SnapshotError("%s is not an overlay store (%s)" % (path, e)) from None
    finally:
        source.close()
        target.close()
    if meta.get("base_sha256") != base["content_sha256"]:
        raise SnapshotBaseMismatch("overlay %s is bound to base %s, not %s"
                                   % (path, meta.get("base_sha256"), base["content_sha256"]))
    seq, change_id = (row[0], row[1]) if row else (0, None)
    return {"attached": True, "seq": seq, "change_id": change_id,
            "base_sha256": meta.get("base_sha256"), "base_build_id": meta.get("base_build_id"),
            "overlay_schema": meta.get("overlay_schema"),
            "copy": {"encoding": "base64", "bytes": len(data), "sha256": _sha(data),
                     "data": base64.b64encode(data).decode("ascii")}}


# --- writing --------------------------------------------------------------------------------

def build(*, base, conversations, overlay=None, runtime=None):
    """The snapshot bytes for ``base`` (a :func:`base_record` dict or its keywords),
    ``conversations`` (:func:`conversation_record` dicts) and ``overlay`` (the overlay's
    path, or None when no overlay is attached). Same inputs, same bytes."""
    base = base_record(**base)
    records = []
    for item in conversations:
        if not isinstance(item, dict) or set(item) - _RECORD_KEYS:
            raise SnapshotError("a conversation is a dict with keys among %s" % sorted(_RECORD_KEYS))
        records.append(conversation_record(**item))
    ids = [c["id"] for c in records]
    if len(set(ids)) != len(ids):
        raise SnapshotError("conversation ids repeat: %s" % ids)
    if runtime is not None and not isinstance(runtime, str):
        raise SnapshotError("runtime must be a string")
    requires = {FEATURE_BASE, FEATURE_TURNS}
    schemas = {TURNS_SCHEMA}
    for record in records:
        if record["reasoning_state"] is not None:
            requires.add(FEATURE_STATE)
            schemas.add(record["reasoning_state"]["schema"])
        if record.get("action_grounding_state") is not None:
            requires.add(FEATURE_ACTION)
            schemas.add(ACTION_STATE_SCHEMA)
    if overlay is None:
        overlay_part = {"attached": False}
    else:
        overlay_part = _overlay_copy(overlay, base)
        requires.add(FEATURE_OVERLAY)
    body = {"format": FORMAT, "version": VERSION, "base": base, "overlay": overlay_part,
            "contract": {"runtime": runtime, "requires": sorted(requires), "schemas": sorted(schemas)},
            "conversations": records, "excluded": [dict(x) for x in EXCLUDED]}
    data = canonical(body)
    return b"%s %d %s\n" % (MAGIC, len(data), _sha(data).encode("ascii")) + data


def atomic_write(path, data):
    """Write ``data`` to ``path`` through a unique temp file, fsync, ``os.replace``, then fsync the directory."""
    path = os.fspath(path)
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    handle, temporary = tempfile.mkstemp(prefix=".%s." % os.path.basename(path),
                                         suffix=".%d.%s.tmp" % (os.getpid(), uuid.uuid4().hex[:8]), dir=folder)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    if os.name != "nt":
        directory = os.open(folder, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


def write(path, *, base, conversations, overlay=None, runtime=None):
    """Write a snapshot to ``path`` atomically. Returns ``{"path", "bytes", "sha256"}``."""
    data = build(base=base, conversations=conversations, overlay=overlay, runtime=runtime)
    atomic_write(path, data)
    return {"path": os.fspath(path), "bytes": len(data), "sha256": _sha(data)}


# --- reading --------------------------------------------------------------------------------

def _no_duplicates(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise SnapshotDamaged("snapshot body repeats the key %r" % key)
        out[key] = value
    return out


def _no_constant(name):
    raise SnapshotDamaged("snapshot body holds %s, which canonical JSON never writes" % name)


def _parse(data, where):
    if not isinstance(data, (bytes, bytearray)):
        raise SnapshotError("snapshot data must be bytes")
    data = bytes(data)
    if not data.startswith(MAGIC):
        raise SnapshotDamaged("%s is not a MARCO snapshot (no %s header)" % (where, MAGIC.decode()))
    end = data.find(b"\n", 0, 128)
    header = _HEADER.fullmatch(data[:end + 1]) if end >= 0 else None
    if header is None:
        raise SnapshotDamaged("%s: malformed or truncated snapshot header" % where)
    length, digest = int(header.group(1)), header.group(2).decode("ascii")
    if length > MAX_BODY:
        raise SnapshotDamaged("%s: body length %d is above the %d-byte cap" % (where, length, MAX_BODY))
    body = data[end + 1:]
    if len(body) < length:
        raise SnapshotDamaged("%s is truncated: body has %d of %d bytes" % (where, len(body), length))
    if len(body) > length:
        raise SnapshotDamaged("%s has %d bytes after the body" % (where, len(body) - length))
    if _sha(body) != digest:
        raise SnapshotDamaged("%s is damaged: the body's sha256 does not match the header" % where)
    try:
        value = json.loads(body.decode("utf-8"), object_pairs_hook=_no_duplicates, parse_constant=_no_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise SnapshotDamaged("%s: body is not UTF-8 JSON (%s)" % (where, e)) from None
    if not isinstance(value, dict) or canonical(value) != body:
        raise SnapshotDamaged("%s: body is not a canonical JSON object" % where)
    return value, digest


def _validate(body, where):
    if body.get("format") != FORMAT:
        raise SnapshotDamaged("%s: format is %r, not %r" % (where, body.get("format"), FORMAT))
    if body.get("version") != VERSION:
        raise SnapshotUnsupported("%s: snapshot version %r; this reader reads version %d"
                                  % (where, body.get("version"), VERSION))
    contract = body.get("contract")
    if (not isinstance(contract, dict) or not isinstance(contract.get("requires"), list)
            or not isinstance(contract.get("schemas"), list)):
        raise SnapshotDamaged("%s: contract is malformed" % where)
    unknown = sorted(set(map(str, contract["requires"])) - FEATURES)
    if unknown:
        raise SnapshotUnsupported("%s requires feature(s) this reader does not have: %s" % (where, unknown))
    unknown = sorted(set(map(str, contract["schemas"])) - STATE_SCHEMAS)
    if unknown:
        raise SnapshotUnsupported("%s holds state schema(s) this reader does not know: %s" % (where, unknown))
    try:
        base_record(**body.get("base"))
    except (TypeError, SnapshotError) as e:
        raise SnapshotDamaged("%s: base record is malformed (%s)" % (where, e)) from None
    overlay = body.get("overlay")
    if not isinstance(overlay, dict) or not isinstance(overlay.get("attached"), bool):
        raise SnapshotDamaged("%s: overlay record is malformed" % where)
    if overlay["attached"]:
        copy = overlay.get("copy")
        if (FEATURE_OVERLAY not in contract["requires"] or type(overlay.get("seq")) is not int
                or overlay["seq"] < 0 or not isinstance(copy, dict) or copy.get("encoding") != "base64"):
            raise SnapshotDamaged("%s: overlay record is malformed" % where)
    conversations = body.get("conversations")
    if not isinstance(conversations, list):
        raise SnapshotDamaged("%s: conversations is not a list" % where)
    for record in conversations:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str) \
                or not isinstance(record.get("turns"), list):
            raise SnapshotDamaged("%s: a conversation record is malformed" % where)
        for turn in record["turns"]:
            if not isinstance(turn, dict) or not isinstance(turn.get("user"), str) \
                    or not isinstance(turn.get("assistant"), str):
                raise SnapshotDamaged("%s: a turn of %s is malformed" % (where, record["id"]))
        state = record.get("reasoning_state")
        if state is not None:
            schema = state.get("schema") if isinstance(state, dict) else None
            if schema not in REASONING_SCHEMAS:
                raise SnapshotUnsupported("%s: conversation %s has state schema %r, which this reader "
                                          "does not know" % (where, record["id"], schema))
            if schema not in contract["schemas"]:
                raise SnapshotDamaged("%s: conversation %s has a schema its contract does not list"
                                      % (where, record["id"]))
        action = record.get("action_grounding_state")
        if action is not None:
            if FEATURE_ACTION not in contract["requires"] or ACTION_STATE_SCHEMA not in contract["schemas"]:
                raise SnapshotDamaged("%s: conversation %s has an action state its contract does not list"
                                      % (where, record["id"]))
            try:
                _action_state_pair(action, state, record["id"])
            except SnapshotError as e:
                raise SnapshotDamaged("%s: conversation %s has a malformed action state (%s)"
                                      % (where, record["id"], e)) from None


class Snapshot:
    """A read and validated snapshot. Use :func:`read` or :func:`loads`."""

    def __init__(self, body, sha256, size, path=None):
        self.body = body
        self.sha256 = sha256
        self.size = size
        self.path = path

    @property
    def base(self):
        return dict(self.body["base"])

    @property
    def overlay(self):
        """``None`` when no overlay was attached, else ``{"seq", "change_id", ...}`` without the copy."""
        part = self.body["overlay"]
        return {k: v for k, v in part.items() if k != "copy"} if part["attached"] else None

    @property
    def contract(self):
        return deepcopy(self.body["contract"])

    @property
    def conversations(self):
        return deepcopy(self.body["conversations"])

    def conversation(self, conversation_id=None):
        """One conversation by id; with no id, the only one (refused if there are several)."""
        records = self.body["conversations"]
        if conversation_id is None:
            if len(records) != 1:
                raise SnapshotError("the snapshot holds %d conversations; name one" % len(records))
            return deepcopy(records[0])
        for record in records:
            if record["id"] == conversation_id:
                return deepcopy(record)
        raise SnapshotError("the snapshot holds no conversation %r" % conversation_id)

    def summary(self):
        """What ``inspect`` shows: base, overlay sequence, schemas, counts. Runs nothing."""
        records = self.body["conversations"]
        return {"path": self.path, "bytes": self.size, "sha256": self.sha256, "format": FORMAT,
                "version": self.body["version"], "base": self.base, "overlay": self.overlay,
                "runtime": self.body["contract"].get("runtime"),
                "requires": list(self.body["contract"]["requires"]),
                "schemas": list(self.body["contract"]["schemas"]),
                "conversations": len(records), "turns": sum(len(c["turns"]) for c in records),
                "with_reasoning_state": sum(c.get("reasoning_state") is not None for c in records),
                "excluded": [x.get("id") for x in self.body.get("excluded", []) if isinstance(x, dict)]}

    # --- checks -------------------------------------------------------------------------

    def check_base(self, base):
        """Refuse (``SnapshotBaseMismatch``) unless ``base`` is the base this snapshot was taken on.

        ``content_sha256`` must be equal; ``build_id`` must be equal when both sides record one.
        """
        current = base_record(**base)
        recorded = self.body["base"]
        if current["content_sha256"] != recorded["content_sha256"]:
            raise SnapshotBaseMismatch("the snapshot was taken on base %s; this base is %s; refused"
                                       % (recorded["content_sha256"], current["content_sha256"]))
        if (current["build_id"] is not None and recorded["build_id"] is not None
                and current["build_id"] != recorded["build_id"]):
            raise SnapshotBaseMismatch("the snapshot was taken on build %s; this build is %s; refused"
                                       % (recorded["build_id"], current["build_id"]))

    def check_overlay(self, overlay=None):
        """Compare the recorded overlay with the current one (a path, an open ``OverlayStore``,
        or None for no overlay). Returns ``"same"`` (same head) or ``"advanced"`` (the current
        overlay holds the recorded history and more changes after it, so saved replays must be
        re-derived). Refuses with ``SnapshotOverlayMismatch`` when the overlay is missing, is
        shorter than the recorded seq, or holds another change at that seq."""
        recorded = self.body["overlay"]
        if overlay is None:
            if recorded["attached"]:
                raise SnapshotOverlayMismatch("the snapshot was taken with an overlay at seq %d; "
                                              "no overlay is attached; refused" % recorded["seq"])
            return "same"
        from marco.storage import overlay as overlay_store
        store, opened = overlay, False
        if not isinstance(overlay, overlay_store.OverlayStore):
            try:
                store = overlay_store.OverlayStore.open(overlay, base_sha256=self.body["base"]["content_sha256"])
            except overlay_store.OverlayBaseMismatch as e:
                raise SnapshotOverlayMismatch("the overlay is bound to another base: %s" % e) from None
            except overlay_store.OverlayError as e:
                raise SnapshotOverlayMismatch("the overlay cannot be read: %s" % e) from None
            opened = True
        try:
            meta = store.meta()
            if meta.get("base_sha256") != self.body["base"]["content_sha256"]:
                raise SnapshotOverlayMismatch("the overlay is bound to base %s, not the snapshot's %s; refused"
                                              % (meta.get("base_sha256"), self.body["base"]["content_sha256"]))
            head, head_id = store.head()
            seq = recorded["seq"] if recorded["attached"] else 0
            if head < seq:
                raise SnapshotOverlayMismatch("the overlay's head is seq %d, shorter than the recorded seq %d; "
                                              "refused" % (head, seq))
            if seq:
                at = store.change(seq)["change_id"]
                if at != recorded["change_id"]:
                    raise SnapshotOverlayMismatch("the overlay holds change %s at seq %d; the snapshot recorded "
                                                  "%s; refused" % (at, seq, recorded["change_id"]))
            return "same" if head == seq else "advanced"
        finally:
            if opened:
                store.close()

    def overlay_bytes(self):
        """The overlay copy, verified against its recorded size and sha256."""
        part = self.body["overlay"]
        if not part["attached"]:
            raise SnapshotError("the snapshot has no overlay")
        copy = part["copy"]
        try:
            data = base64.b64decode(copy["data"].encode("ascii"), validate=True)
        except (ValueError, TypeError, AttributeError):
            raise SnapshotDamaged("the overlay copy is not valid base64") from None
        if len(data) != copy.get("bytes") or _sha(data) != copy.get("sha256"):
            raise SnapshotDamaged("the overlay copy does not match its recorded size and sha256")
        return data

    def extract_overlay(self, path):
        """Write the overlay copy to a new file at ``path`` (refused if it exists). Returns the path."""
        path = os.fspath(path)
        data = self.overlay_bytes()
        if os.path.exists(path):
            raise SnapshotError("%s exists already; the overlay copy is written only to a new path" % path)
        atomic_write(path, data)
        return path

    def restore_states(self, base, overlay=None):
        """Check base and overlay, then return the conversations ready to restore.

        Same base and same overlay seq: each reasoning state as saved (its replay is used).
        Same base, overlay advanced past the recorded seq: each state without its ``replay``,
        so the context re-derives it under the current overlay. Anything else is refused.
        """
        self.check_base(base)
        status = self.check_overlay(overlay)
        records = self.conversations
        if status == "advanced":
            for record in records:
                if isinstance(record.get("reasoning_state"), dict):
                    record["reasoning_state"].pop("replay", None)
                if record.get("action_grounding_state") is not None:
                    record["action_grounding_state"] = invalidate_action_grounding_state(
                        record["action_grounding_state"], "overlay_head_changed")
        return status, records


def loads(data, *, where="<snapshot>"):
    """Read and validate snapshot bytes. Raises a :class:`SnapshotError` subclass."""
    body, digest = _parse(data, where)
    _validate(body, where)
    return Snapshot(body, _sha(bytes(data)), len(data), None)


def read(path):
    """Read and validate the snapshot file at ``path``."""
    path = os.fspath(path)
    try:
        with open(path, "rb") as handle:
            data = handle.read(MAX_BODY + 256)
    except FileNotFoundError:
        raise SnapshotError("no snapshot at %s" % path) from None
    snapshot = loads(data, where=path)
    snapshot.path = path
    return snapshot


def is_snapshot(path):
    """True when the file at ``path`` starts with the snapshot header (nothing else is checked)."""
    try:
        with open(os.fspath(path), "rb") as handle:
            return handle.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


# --- optional outer action state (transport and bookkeeping validation only) -----------------

_ACTION_MAX_INT = 9007199254740991
_ACTION_MAX_BYTES = 2097152
_ACTION_ID = re.compile(r'a[1-9][0-9]{0,30}\Z')
_ACTION_CODE = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,63}\Z')
_ACTION_STATE_KEYS = frozenset(('schema', 'binding', 'input_turn', 'next_pending', 'observation_turns',
                                'pending', 'gaps'))
_ACTION_PENDING_KEYS = frozenset(('id', 'text', 'created_input_turn', 'pre_observation_refs', 'binding',
                                  'reading', 'original_outcome', 'status', 'reason'))
_ACTION_BINDING_KEYS = frozenset(('conversation_id', 'model_content_sha256', 'model_effective_key', 'graph_id',
                                  'root_id', 'effective_graph_sha256', 'view_key',
                                  'language_projection_fingerprint', 'action_projection_fingerprint',
                                  'parser_base_sha256', 'parser_grammar_sha256', 'installed_memory_head'))
_ACTION_HEX_FIELDS = ('model_content_sha256', 'model_effective_key', 'effective_graph_sha256', 'language_projection_fingerprint',
                      'action_projection_fingerprint', 'parser_base_sha256', 'parser_grammar_sha256')


def _action_state_fail(what):
    raise SnapshotError('action grounding state: %s' % what)


def _action_state_scan(value, depth, count):
    count[0] += 1
    if count[0] > 65536 or depth > 64:
        _action_state_fail('exceeds the node or depth bound')
    kind = type(value)
    if value is None or kind is bool or kind is str:
        return
    if kind is int:
        if abs(value) > _ACTION_MAX_INT:
            _action_state_fail('an integer exceeds the bound')
        return
    if kind is float:
        if value - value != 0:
            _action_state_fail('a number is not finite')
        return
    if kind is list:
        for item in value:
            _action_state_scan(item, depth + 1, count)
        return
    if kind is dict:
        for key, item in value.items():
            if type(key) is not str:
                _action_state_fail('an object key is not a string')
            _action_state_scan(item, depth + 1, count)
        return
    _action_state_fail('holds a value that is not plain JSON')


def _action_state_int(value, low, what, high=_ACTION_MAX_INT):
    if type(value) is not int or value < low or value > high:
        _action_state_fail('%s is not an integer within bounds' % what)


def _action_state_str(value, what, limit=512):
    if type(value) is not str or not value or len(value) > limit:
        _action_state_fail('%s is not a bounded non-empty string' % what)


def _action_state_hex(value, what):
    if type(value) is not str or not _HEX64.match(value):
        _action_state_fail('%s is not 64 lower-case hex digits' % what)


def _action_state_binding(value, what):
    if type(value) is not dict or set(value) != _ACTION_BINDING_KEYS:
        _action_state_fail('%s binding keys are not exact' % what)
    _action_state_str(value['conversation_id'], 'conversation_id', 128)
    for key in ('model_effective_key', 'graph_id', 'root_id'):
        _action_state_str(value[key], key)
    if not value['model_effective_key']:
        _action_state_fail('model_effective_key is empty')
    for key in _ACTION_HEX_FIELDS:
        _action_state_hex(value[key], key)
    view = value['view_key']
    if type(view) is not list or len(view) != 2:
        _action_state_fail('view_key is not a pair')
    _action_state_int(view[0], 0, 'view_key sequence')
    if view[1] is not None:
        _action_state_str(view[1], 'view_key name')
    if value['installed_memory_head'] is not None:
        _action_state_int(value['installed_memory_head'], 0, 'installed_memory_head')


def validate_action_grounding_state(value, reasoning_state=None):
    """A detached normalized action state, or None; SnapshotError otherwise. With a
    ``reasoning_state`` the matching reasoning-context-v11 pairing is required too."""
    if value is None:
        return None
    _action_state_scan(value, 0, [0])
    if type(value) is not dict or set(value) != _ACTION_STATE_KEYS:
        _action_state_fail('keys are not exact')
    if len(canonical(value)) > _ACTION_MAX_BYTES:
        _action_state_fail('exceeds the byte bound')
    state = deepcopy(value)
    if state['schema'] != ACTION_STATE_SCHEMA:
        _action_state_fail('schema is not %s' % ACTION_STATE_SCHEMA)
    _action_state_binding(state['binding'], 'state')
    conversation_id = state['binding']['conversation_id']
    chronology_ids = None
    chronology_records = None
    if reasoning_state is not None:
        if type(reasoning_state) is not dict or reasoning_state.get('schema') != 'reasoning-context-v11':
            _action_state_fail('needs a reasoning-context-v11 state beside it')
        conversation = reasoning_state.get('conversation')
        if type(conversation) is not str or not conversation or len(conversation) > 128:
            _action_state_fail('reasoning state conversation is not a bounded nonempty string')
        if conversation != conversation_id:
            _action_state_fail('conversation id differs from the reasoning state')
        chronology_ids = reasoning_state.get('observation_ids')
        if type(chronology_ids) is not list:
            _action_state_fail('reasoning state observation_ids is not a list')
        for oid in chronology_ids:
            if type(oid) is not str:
                _action_state_fail('a reasoning state observation id is not a string')
        if len(set(chronology_ids)) != len(chronology_ids):
            _action_state_fail('reasoning state observation_ids repeat')
        ledger = reasoning_state.get('reading_ledger')
        if type(ledger) is not dict or type(ledger.get('records')) is not dict:
            _action_state_fail('reasoning state reading_ledger records are not a dictionary')
        chronology_records = ledger['records']
    turn = state['input_turn']
    _action_state_int(turn, 0, 'input_turn')
    _action_state_int(state['next_pending'], 1, 'next_pending')
    rows = state['observation_turns']
    if type(rows) is not list or len(rows) > 128:
        _action_state_fail('observation_turns is not a bounded list')
    seen = set()
    last_index = -1
    for row in rows:
        if type(row) is not dict or set(row) != {'observation_id', 'reading_revision', 'input_turn'}:
            _action_state_fail('an observation row has inexact keys')
        _action_state_str(row['observation_id'], 'observation_id', 128)
        _action_state_int(row['reading_revision'], 1, 'reading_revision')
        _action_state_int(row['input_turn'], 1, 'observation input_turn', turn)
        identity = (row['observation_id'], row['reading_revision'])
        if identity in seen:
            _action_state_fail('an observation identity repeats')
        seen.add(identity)
        if chronology_ids is not None:
            oid = row['observation_id']
            if oid not in chronology_ids:
                _action_state_fail('an observation row names an id missing from the reasoning state')
            index = chronology_ids.index(oid)
            if index <= last_index:
                _action_state_fail('observation rows do not follow the reasoning state chronology')
            last_index = index
            entry = chronology_records.get(oid)
            if type(entry) is not dict or type(entry.get('active')) is not int or isinstance(entry.get('active'), bool):
                _action_state_fail('an observation row has no active reading in the reasoning state')
            if entry['active'] < 1 or entry['active'] != row['reading_revision']:
                _action_state_fail('an observation row revision differs from the active reading')
    pending = state['pending']
    if type(pending) is not list or len(pending) > 64:
        _action_state_fail('pending is not a bounded list')
    ids = set()
    for item in pending:
        if type(item) is not dict or set(item) != _ACTION_PENDING_KEYS:
            _action_state_fail('a pending entry has inexact keys')
        pid = item['id']
        if type(pid) is not str or len(pid) > 128 or not _ACTION_ID.match(pid):
            _action_state_fail('a pending id is malformed')
        if int(pid[1:]) >= state['next_pending'] or pid in ids:
            _action_state_fail('a pending id is reused or not below next_pending')
        ids.add(pid)
        if type(item['text']) is not str or len(item['text']) > 512:
            _action_state_fail('pending text is not a bounded string')
        _action_state_int(item['created_input_turn'], 1, 'created_input_turn', turn)
        refs = item['pre_observation_refs']
        if type(refs) is not list or len(refs) > 128:
            _action_state_fail('pre_observation_refs is not a bounded list')
        ref_seen = set()
        for ref in refs:
            if type(ref) is not dict or set(ref) != {'observation_id', 'reading_revision', 'record_sha256'}:
                _action_state_fail('a pre observation ref has inexact keys')
            _action_state_str(ref['observation_id'], 'ref observation_id', 128)
            _action_state_int(ref['reading_revision'], 1, 'ref reading_revision')
            _action_state_hex(ref['record_sha256'], 'record_sha256')
            identity = (ref['observation_id'], ref['reading_revision'])
            if identity in ref_seen:
                _action_state_fail('a pre observation ref repeats')
            ref_seen.add(identity)
        _action_state_binding(item['binding'], 'pending')
        if item['status'] == 'active' and item['binding']['conversation_id'] != conversation_id:
            _action_state_fail('a pending binding names another conversation')
        reading = item['reading']
        if type(reading) is not dict or reading.get('schema') != 'unknown-action-reading-v1':
            _action_state_fail('a pending reading is not unknown-action-reading-v1')
        if item['original_outcome'] is not None and type(item['original_outcome']) is not dict:
            _action_state_fail('original_outcome is not an object or null')
        if item['status'] == 'active':
            if item['reason'] is not None:
                _action_state_fail('an active pending has a reason')
        elif item['status'] == 'stale':
            reason = item['reason']
            if type(reason) is not str or not _ACTION_CODE.match(reason):
                _action_state_fail('a stale pending needs a finite reason code')
        else:
            _action_state_fail('a pending status is unknown')
    gaps = state['gaps']
    if type(gaps) is not list or len(gaps) > 16:
        _action_state_fail('gaps is not a bounded list')
    codes = set()
    for gap in gaps:
        if type(gap) is not dict or set(gap) != {'code'}:
            _action_state_fail('a gap has inexact keys')
        code = gap['code']
        if type(code) is not str or not _ACTION_CODE.match(code) or code in codes:
            _action_state_fail('a gap code is malformed or repeats')
        codes.add(code)
    return state


def _action_state_pair(value, reasoning_state, conversation_id):
    """Validate an action state against the reasoning state it rides beside. The outer
    ``conversation_id`` is the store record id, independent of the Context conversation."""
    if value is None:
        return None
    if reasoning_state is None:
        _action_state_fail('needs a reasoning state beside it')
    return validate_action_grounding_state(value, reasoning_state)


def invalidate_action_grounding_state(value, code):
    """A detached copy with every active pending marked stale for ``code``; evidence unchanged."""
    if type(code) is not str or not _ACTION_CODE.match(code):
        raise SnapshotError('action grounding state: invalidation code is not a finite identifier')
    state = validate_action_grounding_state(value)
    if state is None:
        return None
    for item in state['pending']:
        if item['status'] == 'active':
            item['status'] = 'stale'
            item['reason'] = code
    gap = {'code': code}
    if gap not in state['gaps'] and len(state['gaps']) < 16:
        state['gaps'].append(gap)
    return state
