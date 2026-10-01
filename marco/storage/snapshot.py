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
FEATURES = frozenset({FEATURE_BASE, FEATURE_TURNS, FEATURE_STATE, FEATURE_OVERLAY})

TURNS_SCHEMA = "conversation-turns-v1"
#: The reasoning state schemas ``ReasoningContext.restore`` accepts today.
REASONING_SCHEMAS = frozenset("reasoning-context-v%d" % n for n in range(1, 11))
STATE_SCHEMAS = REASONING_SCHEMAS | {TURNS_SCHEMA}

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

_RECORD_KEYS = frozenset({"id", "title", "created_at", "updated_at", "turns", "reasoning_state"})
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


def conversation_record(*, id, turns, reasoning_state=None, title=None, created_at=None, updated_at=None):
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
    return {"id": id, "title": title, "created_at": created_at, "updated_at": updated_at,
            "turns": turns, "reasoning_state": state}


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
