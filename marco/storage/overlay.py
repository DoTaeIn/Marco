"""Persistent Overlay Infrastructure: the overlay store beside an immutable base.

The overlay holds graph and rule changes that were stated explicitly or approved
from outside (a person, or a caller of the API). Each change applies at the next
read; the base file is never written. The store records and resolves changes; it
makes no word-level, verb-level or case-level judgement, and nothing in it starts
a change by itself. Design note: ``docs/architecture/overlay.md``.

One SQLite file (standard library ``sqlite3``, WAL journal) beside the base:

* ``meta``: the base it is bound to (``base_sha256``, ``base_build_id``,
  ``format_version``) and ``overlay_schema``. Fixed at creation. Opening the
  store against a different base sha is refused.
* ``changes``: append-only (triggers refuse UPDATE and DELETE), one row per
  change, ``seq`` growing by one.
* ``deltas``: append-only, the operations of each change in order.
* ``cur_nodes``, ``cur_edges``, ``cur_rules``: derived state, one row per
  target and per change that touched it (``from_seq`` .. ``to_seq``), so a read
  can be pinned at any ``seq``. ``rebuild()`` recomputes them from ``changes``
  and ``deltas`` and reports whether they matched.

One change is one transaction (``BEGIN IMMEDIATE``). There is one writer: a
writer holds an OS lock on ``<overlay>.writer-lock`` for as long as it is open,
and a second writer is refused at once, never queued. Readers take no lock.

Standard library only.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
import sqlite3

from marco.storage import ids
from marco.trace.ledger import new_id

OVERLAY_SCHEMA = 1
APPLICATION_ID = 0x4D434F4F  # "MCOO"
CHANGE_PREFIX = "chg_"
CANDIDATE_PREFIX = "cand_"
LOCK_SUFFIX = ".writer-lock"

KINDS = ("node", "edge", "rule")
OPS = {
    "ADD_NODE": "node",
    "ADD_EDGE": "edge",
    "ADD_RULE": "rule",
    "RETRACT_EDGE": "edge",
    "DISABLE_RULE": "rule",
    "RETRACT_NODE": "node",
    "REPLACE_RULE": "rule",
}
# Written only by the store itself: RESTORE is how undo puts a target back to its
# state before the undone change, as a new change that keeps the history.
INTERNAL_OPS = ("RESTORE",)


class OverlayError(RuntimeError):
    """The overlay refused an operation; nothing was written."""


class OverlayBaseMismatch(OverlayError):
    """The overlay is bound to a different base."""


class OverlayWriterBusy(OverlayError):
    """Another writer holds the overlay; the overlay has one writer at a time."""


class OverlayStaleRevision(OverlayError):
    """A delta names a revision of its target that is no longer the current one."""


class OverlayConflict(OverlayError):
    """A change id already present names different content."""


_SCHEMA = """
CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TRIGGER meta_no_update BEFORE UPDATE ON meta
BEGIN SELECT RAISE(ABORT, 'overlay meta is fixed at creation'); END;
CREATE TRIGGER meta_no_delete BEFORE DELETE ON meta
BEGIN SELECT RAISE(ABORT, 'overlay meta is fixed at creation'); END;

CREATE TABLE changes (
    seq INTEGER PRIMARY KEY CHECK (seq > 0),
    change_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    source TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence TEXT NOT NULL,
    parent_seq INTEGER NOT NULL,
    approval TEXT NOT NULL,
    validation TEXT NOT NULL,
    request_digest TEXT NOT NULL
);
CREATE TRIGGER changes_no_update BEFORE UPDATE ON changes
BEGIN SELECT RAISE(ABORT, 'overlay changes are append-only: UPDATE refused'); END;
CREATE TRIGGER changes_no_delete BEFORE DELETE ON changes
BEGIN SELECT RAISE(ABORT, 'overlay changes are append-only: DELETE refused'); END;
CREATE TRIGGER changes_seq_grows BEFORE INSERT ON changes
WHEN NEW.seq <> (SELECT COALESCE(MAX(seq), 0) + 1 FROM changes)
BEGIN SELECT RAISE(ABORT, 'overlay seq must be the head plus one'); END;

CREATE TABLE deltas (
    seq INTEGER NOT NULL REFERENCES changes(seq),
    ord INTEGER NOT NULL,
    op TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK (target_kind IN ('node', 'edge', 'rule')),
    target_id TEXT NOT NULL,
    graph_id TEXT,
    payload TEXT NOT NULL,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    PRIMARY KEY (seq, ord)
);
CREATE INDEX deltas_target ON deltas(target_id, seq);
CREATE TRIGGER deltas_no_update BEFORE UPDATE ON deltas
BEGIN SELECT RAISE(ABORT, 'overlay deltas are append-only: UPDATE refused'); END;
CREATE TRIGGER deltas_no_delete BEFORE DELETE ON deltas
BEGIN SELECT RAISE(ABORT, 'overlay deltas are append-only: DELETE refused'); END;
CREATE TRIGGER deltas_only_newest BEFORE INSERT ON deltas
WHEN NEW.seq <> (SELECT MAX(seq) FROM changes)
BEGIN SELECT RAISE(ABORT, 'deltas are written only with their own change'); END;

CREATE TABLE cur_nodes (
    node_id TEXT NOT NULL,
    from_seq INTEGER NOT NULL,
    to_seq INTEGER,
    graph_id TEXT NOT NULL,
    name TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('none', 'added', 'tombstoned')),
    data TEXT NOT NULL,
    revision INTEGER NOT NULL,
    PRIMARY KEY (node_id, from_seq)
);
CREATE UNIQUE INDEX cur_nodes_live ON cur_nodes(node_id) WHERE to_seq IS NULL;

CREATE TABLE cur_edges (
    edge_id TEXT NOT NULL,
    from_seq INTEGER NOT NULL,
    to_seq INTEGER,
    graph_id TEXT NOT NULL,
    src TEXT NOT NULL,
    rel TEXT NOT NULL,
    dst TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('none', 'added', 'tombstoned')),
    data TEXT NOT NULL,
    revision INTEGER NOT NULL,
    PRIMARY KEY (edge_id, from_seq)
);
CREATE UNIQUE INDEX cur_edges_live ON cur_edges(edge_id) WHERE to_seq IS NULL;
CREATE INDEX cur_edges_live_src ON cur_edges(graph_id, src) WHERE to_seq IS NULL;
CREATE INDEX cur_edges_live_dst ON cur_edges(graph_id, dst) WHERE to_seq IS NULL;

CREATE TABLE cur_rules (
    rule_id TEXT NOT NULL,
    from_seq INTEGER NOT NULL,
    to_seq INTEGER,
    graph_id TEXT,
    state TEXT NOT NULL CHECK (state IN ('none', 'added', 'replaced', 'disabled')),
    body TEXT NOT NULL,
    revision INTEGER NOT NULL,
    PRIMARY KEY (rule_id, from_seq)
);
CREATE UNIQUE INDEX cur_rules_live ON cur_rules(rule_id) WHERE to_seq IS NULL;

CREATE TABLE candidates (
    candidate_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    source TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence TEXT NOT NULL,
    request TEXT NOT NULL,
    request_digest TEXT NOT NULL,
    proposed_at_seq INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'approved', 'rejected')),
    decided_at TEXT,
    decided_by TEXT,
    decision_reason TEXT,
    change_seq INTEGER REFERENCES changes(seq),
    CHECK ((status = 'pending') = (decided_at IS NULL)),
    CHECK ((status = 'approved') = (change_seq IS NOT NULL))
);
CREATE INDEX candidates_status ON candidates(status);
CREATE TRIGGER candidates_no_delete BEFORE DELETE ON candidates
BEGIN SELECT RAISE(ABORT, 'candidates are kept, rejected ones too: DELETE refused'); END;
CREATE TRIGGER candidates_decided_once BEFORE UPDATE ON candidates WHEN OLD.status <> 'pending'
BEGIN SELECT RAISE(ABORT, 'a decided candidate stays as decided'); END;
CREATE TRIGGER candidates_request_fixed BEFORE UPDATE OF candidate_id, created_at, actor, source, reason,
    evidence, request, request_digest, proposed_at_seq ON candidates
BEGIN SELECT RAISE(ABORT, 'a candidate''s request is fixed when it is proposed'); END;
"""

# Per kind: (table, key column, the state columns a delta sets).
_TABLE = {
    "node": ("cur_nodes", "node_id", ("graph_id", "name", "state", "data")),
    "edge": ("cur_edges", "edge_id", ("graph_id", "src", "rel", "dst", "state", "data")),
    "rule": ("cur_rules", "rule_id", ("graph_id", "state", "body")),
}
_JSON_FIELDS = ("data", "body")


def dumps(value):
    """Canonical JSON: sorted keys, no spaces, UTF-8 text kept as is."""
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(requests):
    return hashlib.sha256(dumps(requests).encode("utf-8")).hexdigest()


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _text(value, what):
    if not isinstance(value, str) or not value.strip():
        raise OverlayError("%s must be a non-empty string, not %r" % (what, value))
    return value


def _sha(value, what):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise OverlayError("%s must be 64 hex characters, not %r" % (what, value))
    return value.lower()


def file_sha256(path, chunk=1 << 20):
    """SHA-256 of a file's bytes, for binding an overlay to its base."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


# --- delta requests: plain dicts a caller builds and commits ---------------------------

def _request(op, kind, target_id, graph, payload, revision):
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
        raise OverlayError("revision must be an integer >= 0, not %r" % (revision,))
    return {"op": op, "target_kind": kind, "target_id": target_id, "graph_id": graph,
            "payload": payload, "revision": revision}


def add_node(graph, name, *, revision, data=None):
    """ADD NODE ``name`` to ``graph``; ``revision`` is the node's current overlay revision (0 if never touched)."""
    graph = ids.graph_id(graph)
    return _request("ADD_NODE", "node", ids.node_id(graph, name), graph, {"name": name, "data": data}, revision)


def add_edge(graph, src, rel, dst, *, revision, data=None):
    """ADD EDGE ``src -rel-> dst`` in ``graph`` (node names)."""
    graph = ids.graph_id(graph)
    return _request("ADD_EDGE", "edge", ids.edge_id(graph, src, rel, dst), graph,
                    {"src": src, "rel": rel, "dst": dst, "data": data}, revision)


def add_rule(rule, body, *, revision, graph=None):
    """ADD RULE ``rule`` (the existing rule id string) with ``body``, any JSON value the store does not read."""
    return _request("ADD_RULE", "rule", ids.rule_id(rule), ids.graph_id(graph) if graph else None,
                    {"body": body}, revision)


def retract_edge(graph, src, rel, dst, *, revision):
    """RETRACT EDGE: a tombstone that hides the edge, in the base or the overlay, from the next read."""
    graph = ids.graph_id(graph)
    return _request("RETRACT_EDGE", "edge", ids.edge_id(graph, src, rel, dst), graph,
                    {"src": src, "rel": rel, "dst": dst}, revision)


def disable_rule(rule, *, revision):
    """DISABLE RULE: the rule, in the base or the overlay, is not used from the next read."""
    return _request("DISABLE_RULE", "rule", ids.rule_id(rule), None, {}, revision)


def retract_node(graph, name, *, revision, base_edges=()):
    """RETRACT NODE: a tombstone for the node and, in the same change, one RETRACT EDGE per edge of it.

    The overlay's own live edges of the node are found by the store. The base's edges
    of the node are named by the caller as ``(src, rel, dst)`` triples, since this
    store does not read the base; each must have the node as src or dst."""
    graph = ids.graph_id(graph)
    edges = [list(e) for e in base_edges]
    for edge in edges:
        if len(edge) != 3 or name not in (edge[0], edge[2]):
            raise OverlayError("RETRACT_NODE %s: base edge %r is not (src, rel, dst) of this node" % (name, edge))
    return _request("RETRACT_NODE", "node", ids.node_id(graph, name), graph,
                    {"name": name, "base_edges": edges}, revision)


def replace_rule(rule, body, *, revision):
    """REPLACE RULE: from the next read the rule's body is ``body`` (the rule id stays)."""
    return _request("REPLACE_RULE", "rule", ids.rule_id(rule), None, {"body": body}, revision)


def _check_request(d):
    """A caller's delta request, checked: known op, ids that match their parts, JSON payload."""
    if not isinstance(d, dict):
        raise OverlayError("a delta is a dict built by add_node, add_edge, ...; got %r" % (d,))
    op = d.get("op")
    if op not in OPS:
        raise OverlayError("unknown or internal delta op %r" % (op,))
    kind = OPS[op]
    p = d.get("payload")
    if d.get("target_kind") != kind or not isinstance(p, dict):
        raise OverlayError("%s needs target_kind %r and a payload dict" % (op, kind))
    if kind == "node":
        expect = ids.node_id(d["graph_id"], p["name"])
    elif kind == "edge":
        expect = ids.edge_id(d["graph_id"], p["src"], p["rel"], p["dst"])
    else:
        expect = ids.rule_id(d["target_id"])
    if d.get("target_id") != expect:
        raise OverlayError("%s target_id %r does not match its parts (expected %r)" % (op, d.get("target_id"), expect))
    if op == "RETRACT_NODE":
        for edge in p.get("base_edges", ()):
            if len(edge) != 3 or p["name"] not in (edge[0], edge[2]):
                raise OverlayError("RETRACT_NODE %s: base edge %r is not (src, rel, dst) of this node" % (expect, edge))
    clean = _request(op, kind, expect, d.get("graph_id"), p, d.get("revision"))
    dumps(clean)
    return clean


# --- applying one delta to the derived state ------------------------------------------

def _live(cur, kind, target_id):
    table, key, _ = _TABLE[kind]
    row = cur.execute("SELECT * FROM %s WHERE %s = ? AND to_seq IS NULL" % (table, key), (target_id,)).fetchone()
    return dict(row) if row is not None else None


def _refuse(op, target_id, state):
    raise OverlayError("%s refused: %s is %s in the overlay" % (op, target_id, state))


def _transition(cur, d, row):
    """The new state columns of the target after delta ``d``, from its live row (or None)."""
    op, kind, p = d["op"], d["target_kind"], d["payload"]
    state = row["state"] if row else "none"
    if op == "ADD_NODE":
        if state == "added":
            _refuse(op, d["target_id"], state)
        return {"graph_id": d["graph_id"], "name": p["name"], "state": "added", "data": p.get("data")}
    if op == "ADD_EDGE":
        if state == "added":
            _refuse(op, d["target_id"], state)
        for end in (p["src"], p["dst"]):
            node = _live(cur, "node", ids.node_id(d["graph_id"], end))
            if node and node["state"] == "tombstoned":
                raise OverlayError("ADD_EDGE refused: its node %s is tombstoned in the overlay"
                                   % ids.node_id(d["graph_id"], end))
        return {"graph_id": d["graph_id"], "src": p["src"], "rel": p["rel"], "dst": p["dst"],
                "state": "added", "data": p.get("data")}
    if op == "RETRACT_NODE":
        if state == "tombstoned":
            _refuse(op, d["target_id"], state)
        return {"graph_id": d["graph_id"], "name": p["name"], "state": "tombstoned", "data": _old(row, "data")}
    if op == "RETRACT_EDGE":
        if state == "tombstoned":
            _refuse(op, d["target_id"], state)
        return {"graph_id": d["graph_id"], "src": p["src"], "rel": p["rel"], "dst": p["dst"],
                "state": "tombstoned", "data": _old(row, "data")}
    if op == "ADD_RULE":
        if state in ("added", "replaced"):
            _refuse(op, d["target_id"], state)
        return {"graph_id": d["graph_id"], "state": "added", "body": p["body"]}
    if op == "REPLACE_RULE":
        if state == "disabled":
            raise OverlayError("REPLACE_RULE refused: %s is disabled; re-enable it by ADD_RULE or by undoing "
                               "the change that disabled it" % d["target_id"])
        graph = row["graph_id"] if row else d["graph_id"]
        return {"graph_id": graph, "state": "added" if state == "added" else "replaced", "body": p["body"]}
    if op == "DISABLE_RULE":
        if state == "disabled":
            _refuse(op, d["target_id"], state)
        graph = row["graph_id"] if row else d["graph_id"]
        return {"graph_id": graph, "state": "disabled", "body": _old(row, "body")}
    if op == "RESTORE":
        fields = p["fields"]
        if set(fields) != set(_TABLE[kind][2]):
            raise OverlayError("RESTORE of %s carries fields %s" % (d["target_id"], sorted(fields)))
        return dict(fields)
    raise OverlayError("unknown delta op %r" % (op,))


def _old(row, column):
    return json.loads(row[column]) if row else None


def _restores(cur, seq):
    """The RESTORE deltas that put every target of change ``seq`` back to its state before it, last first."""
    targets = []
    for d in cur.execute("SELECT target_kind, target_id FROM deltas WHERE seq = ? ORDER BY ord DESC", (seq,)):
        if (d["target_kind"], d["target_id"]) not in targets:
            targets.append((d["target_kind"], d["target_id"]))
    out = []
    for kind, target_id in targets:
        table, key, columns = _TABLE[kind]
        row = _live(cur, kind, target_id)
        if row is None or row["from_seq"] != seq:
            later = row["from_seq"] if row else None
            raise OverlayStaleRevision("undo of change %d refused: %s was changed again by change %s; "
                                       "undo that one first" % (seq, target_id, later))
        prior = cur.execute("SELECT * FROM %s WHERE %s = ? AND to_seq = ?" % (table, key), (target_id, seq)).fetchone()
        if prior is not None:
            fields = {c: json.loads(prior[c]) if c in _JSON_FIELDS else prior[c] for c in columns}
        else:
            fields = {c: None if c in _JSON_FIELDS else row[c] for c in columns}
            fields["state"] = "none"
        out.append(_request("RESTORE", kind, target_id, row["graph_id"], {"undoes": seq, "fields": fields},
                            row["revision"]))
    return out


def _apply_delta(cur, seq, d):
    """Apply one recorded delta of change ``seq`` to the derived tables, checking its revision."""
    kind, target_id = d["target_kind"], d["target_id"]
    table, key, columns = _TABLE[kind]
    row = _live(cur, kind, target_id)
    have = row["revision"] if row else 0
    if d["revision"] != have:
        raise OverlayStaleRevision("%s %s names revision %d; the overlay has it at revision %d"
                                   % (d["op"], target_id, d["revision"], have))
    fields = _transition(cur, d, row)
    values = [dumps(fields[c]) if c in _JSON_FIELDS else fields[c] for c in columns]
    if row and row["from_seq"] == seq:
        cur.execute("UPDATE %s SET %s, revision = ? WHERE %s = ? AND from_seq = ?"
                    % (table, ", ".join("%s = ?" % c for c in columns), key),
                    values + [have + 1, target_id, seq])
        return
    if row:
        cur.execute("UPDATE %s SET to_seq = ? WHERE %s = ? AND from_seq = ?" % (table, key),
                    (seq, target_id, row["from_seq"]))
    cur.execute("INSERT INTO %s (%s, from_seq, to_seq, %s, revision) VALUES (?, ?, NULL, %s, ?)"
                % (table, key, ", ".join(columns), ", ".join("?" * len(columns))),
                [target_id, seq] + values + [have + 1])


def _expand(cur, request):
    """The recorded deltas of one request.

    RETRACT NODE becomes one RETRACT EDGE per live edge of the node (the overlay's
    own edges, then the base edges the caller named), each naming the edge's current
    revision, then the node's own tombstone. Each is applied before the next is
    made, so the revisions are those of the moment."""
    if request["op"] != "RETRACT_NODE":
        yield request
        return
    graph, name = request["graph_id"], request["payload"]["name"]
    node = request["target_id"]
    own = cur.execute("SELECT edge_id, src, rel, dst FROM cur_edges WHERE to_seq IS NULL AND state = 'added' "
                      "AND graph_id = ? AND (src = ? OR dst = ?) ORDER BY edge_id", (graph, name, name)).fetchall()
    edges = [(r["src"], r["rel"], r["dst"]) for r in own] + [tuple(e) for e in request["payload"]["base_edges"]]
    seen = set()
    for src, rel, dst in edges:
        edge = ids.edge_id(graph, src, rel, dst)
        if edge in seen:
            continue
        seen.add(edge)
        row = _live(cur, "edge", edge)
        if row and row["state"] == "tombstoned":
            continue
        yield _request("RETRACT_EDGE", "edge", edge, graph,
                       {"src": src, "rel": rel, "dst": dst, "cascade_of": node}, row["revision"] if row else 0)
    yield _request("RETRACT_NODE", "node", node, graph, {"name": name}, request["revision"])


# --- the writer lock --------------------------------------------------------------------

def _lock(path):
    handle = open(path + LOCK_SUFFIX, "a+b")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        raise OverlayWriterBusy("%s has a writer already; the overlay has one writer at a time" % path) from None
    return handle


def _connect(path, writer):
    db = sqlite3.connect(path, timeout=0 if writer else 5.0, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA synchronous = FULL")
    if not writer:
        db.execute("PRAGMA query_only = ON")
    return db


class OverlayStore:
    """One overlay file bound to one base. Use ``create`` or ``open``; close it when done."""

    def __init__(self, path, db, lock, writer):
        self.path = path
        self._db = db
        self._lock = lock
        self.writer = writer

    # --- opening ---------------------------------------------------------------------

    @classmethod
    def create(cls, path, *, base_sha256, base_build_id, format_version):
        """A new, empty overlay for the base ``base_sha256``, opened as the writer. Refused if ``path`` exists."""
        path = os.fspath(path)
        meta = {"base_sha256": _sha(base_sha256, "base_sha256"),
                "base_build_id": _text(base_build_id, "base_build_id"),
                "format_version": str(format_version),
                "overlay_schema": str(OVERLAY_SCHEMA),
                "created_at": _now()}
        if os.path.exists(path):
            raise OverlayError("%s exists already; open it instead of creating it" % path)
        lock = _lock(path)
        try:
            db = _connect(path, writer=True)
            db.execute("PRAGMA journal_mode = WAL")
            db.execute("BEGIN IMMEDIATE")
            try:
                for statement in _statements(_SCHEMA):
                    db.execute(statement)
                db.executemany("INSERT INTO meta (key, value) VALUES (?, ?)", sorted(meta.items()))
                db.execute("PRAGMA application_id = %d" % APPLICATION_ID)
                db.execute("PRAGMA user_version = %d" % OVERLAY_SCHEMA)
                db.execute("COMMIT")
            except BaseException:
                if db.in_transaction:
                    db.execute("ROLLBACK")
                db.close()
                raise
        except BaseException:
            lock.close()
            raise
        return cls(path, db, lock, writer=True)

    @classmethod
    def open(cls, path, *, base_sha256, base_build_id=None, writer=False):
        """An existing overlay; refused if it is bound to another base. ``writer=True`` takes the writer lock."""
        path = os.fspath(path)
        base_sha256 = _sha(base_sha256, "base_sha256")
        if not os.path.isfile(path):
            raise OverlayError("no overlay at %s; an overlay is created only by OverlayStore.create" % path)
        lock = _lock(path) if writer else None
        try:
            db = _connect(path, writer)
            try:
                meta = cls._read_meta(db, path)
                if meta["base_sha256"] != base_sha256:
                    raise OverlayBaseMismatch("%s is bound to base %s, not %s; refused"
                                              % (path, meta["base_sha256"], base_sha256))
                if base_build_id is not None and meta["base_build_id"] != base_build_id:
                    raise OverlayBaseMismatch("%s is bound to build %s, not %s; refused"
                                              % (path, meta["base_build_id"], base_build_id))
            except BaseException:
                db.close()
                raise
        except BaseException:
            if lock:
                lock.close()
            raise
        return cls(path, db, lock, writer)

    @staticmethod
    def _read_meta(db, path):
        try:
            application = db.execute("PRAGMA application_id").fetchone()[0]
            meta = {r["key"]: r["value"] for r in db.execute("SELECT key, value FROM meta")}
        except sqlite3.DatabaseError as e:
            raise OverlayError("%s is not an overlay store (%s)" % (path, e)) from None
        if application != APPLICATION_ID:
            raise OverlayError("%s is not an overlay store (application id %#x)" % (path, application))
        missing = {"base_sha256", "base_build_id", "format_version", "overlay_schema"} - set(meta)
        if missing:
            raise OverlayError("%s lacks meta %s" % (path, ", ".join(sorted(missing))))
        if meta["overlay_schema"] != str(OVERLAY_SCHEMA):
            raise OverlayError("%s has overlay schema %s; this code reads schema %d"
                               % (path, meta["overlay_schema"], OVERLAY_SCHEMA))
        return meta

    def close(self):
        if self._db is not None:
            self._db.close()
            self._db = None
        if self._lock is not None:
            self._lock.close()
            self._lock = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # --- writing ----------------------------------------------------------------------

    def _write(self, work):
        """Run ``work(cursor)`` as one IMMEDIATE transaction; any failure leaves nothing written."""
        if not self.writer or self._db is None:
            raise OverlayError("this overlay handle is not an open writer")
        try:
            self._db.execute("BEGIN IMMEDIATE")
        except sqlite3.OperationalError as e:
            if "locked" in str(e) or "busy" in str(e):
                raise OverlayWriterBusy("%s is being written by another connection; refused, not queued"
                                        % self.path) from None
            raise
        try:
            result = work(self._db.cursor())
            self._db.execute("COMMIT")
        except BaseException:
            if self._db.in_transaction:
                self._db.execute("ROLLBACK")
            raise
        return result

    def commit(self, deltas, *, actor, source, reason, approved_by, evidence=None, validation=None,
               change_id=None):
        """Record one change: all of ``deltas`` or nothing. Returns ``(seq, change_id)``.

        ``approved_by`` names who or what approved the change (the caller's identity);
        there is no default. Committing a ``change_id`` already present with the same
        deltas is a no-op that returns the recorded ``(seq, change_id)``."""
        requests = [_check_request(d) for d in deltas]
        if not requests:
            raise OverlayError("a change has at least one delta")
        approval = {"by": _text(approved_by, "approved_by"), "at": _now()}
        return self._write(lambda cur: self._record(cur, requests, actor, source, reason, evidence,
                                                    approval, validation, change_id))

    def undo(self, change, *, actor, source, reason, approved_by, evidence=None, validation=None, change_id=None):
        """Undo change ``change`` (its seq or change_id) by a new, compensating change.

        Every target the undone change touched is put back to its state just before
        that change, by one RESTORE delta each. Both changes stay in the history.
        Refused if a later change touched any of those targets (undo that one first).
        Returns ``(seq, change_id)`` of the compensating change."""
        approval = {"by": _text(approved_by, "approved_by"), "at": _now()}

        def work(cur):
            undone = self._change_row(cur, change)
            request = [{"op": "UNDO", "undoes": undone["change_id"]}]
            return self._record(cur, request, actor, source, reason, evidence, approval, validation, change_id,
                                deltas=lambda: _restores(cur, undone["seq"]))
        return self._write(work)

    @staticmethod
    def _change_row(cur, ref):
        if isinstance(ref, int) and not isinstance(ref, bool):
            row = cur.execute("SELECT * FROM changes WHERE seq = ?", (ref,)).fetchone()
        elif isinstance(ref, str):
            row = cur.execute("SELECT * FROM changes WHERE change_id = ?", (ref,)).fetchone()
        else:
            row = None
        if row is None:
            raise OverlayError("no change %r in this overlay" % (ref,))
        return dict(row)

    def _record(self, cur, requests, actor, source, reason, evidence, approval, validation, change_id,
                deltas=None):
        digest = _digest(requests)
        if change_id is not None:
            seen = cur.execute("SELECT seq, request_digest FROM changes WHERE change_id = ?",
                               (_text(change_id, "change_id"),)).fetchone()
            if seen is not None:
                if seen["request_digest"] != digest:
                    raise OverlayConflict("change %s is recorded with different deltas" % change_id)
                return seen["seq"], change_id
        else:
            change_id = new_id(CHANGE_PREFIX)
        head = cur.execute("SELECT COALESCE(MAX(seq), 0) FROM changes").fetchone()[0]
        seq = head + 1
        cur.execute("INSERT INTO changes (seq, change_id, created_at, actor, source, reason, evidence, "
                    "parent_seq, approval, validation, request_digest) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (seq, change_id, _now(), _text(actor, "actor"), _text(source, "source"),
                     _text(reason, "reason"), dumps(evidence), head, dumps(approval), dumps(validation), digest))
        ord_ = 0
        expanded = (deltas(),) if deltas is not None else (_expand(cur, r) for r in requests)
        for group in expanded:
            for d in group:
                _apply_delta(cur, seq, d)
                cur.execute("INSERT INTO deltas (seq, ord, op, target_kind, target_id, graph_id, payload, revision) "
                            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                            (seq, ord_, d["op"], d["target_kind"], d["target_id"], d["graph_id"],
                             dumps(d["payload"]), d["revision"]))
                ord_ += 1
        return seq, change_id

    # --- candidates: stored, not active, until approved from outside ---------------------

    def propose(self, deltas, *, actor, source, reason, evidence=None, candidate_id=None):
        """Store a candidate change. It is not active: it is in no current-state table and no count
        until ``approve`` is called for it. Returns the candidate id. Proposing a ``candidate_id``
        already present with the same deltas is a no-op."""
        requests = [_check_request(d) for d in deltas]
        if not requests:
            raise OverlayError("a candidate has at least one delta")
        digest = _digest(requests)

        def work(cur):
            cid = candidate_id
            if cid is not None:
                seen = cur.execute("SELECT request_digest FROM candidates WHERE candidate_id = ?",
                                   (_text(cid, "candidate_id"),)).fetchone()
                if seen is not None:
                    if seen["request_digest"] != digest:
                        raise OverlayConflict("candidate %s is stored with different deltas" % cid)
                    return cid
            else:
                cid = new_id(CANDIDATE_PREFIX)
            head = cur.execute("SELECT COALESCE(MAX(seq), 0) FROM changes").fetchone()[0]
            cur.execute("INSERT INTO candidates (candidate_id, created_at, actor, source, reason, evidence, request, "
                        "request_digest, proposed_at_seq, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
                        (cid, _now(), _text(actor, "actor"), _text(source, "source"), _text(reason, "reason"),
                         dumps(evidence), dumps(requests), digest, head))
            return cid
        return self._write(work)

    def approve(self, candidate_id, *, approved_by, validation=None):
        """Approve a pending candidate: in one transaction it becomes a change with its deltas, the
        approval naming ``approved_by`` (the caller's identity; there is no default). Returns
        ``(seq, change_id)``. Approving an approved candidate again is a no-op returning the same
        pair; a rejected candidate is refused; a stale revision is refused and the candidate stays
        pending."""
        approved_by = _text(approved_by, "approved_by")

        def work(cur):
            cand = self._candidate_row(cur, candidate_id)
            if cand["status"] == "approved":
                row = cur.execute("SELECT seq, change_id FROM changes WHERE seq = ?", (cand["change_seq"],)).fetchone()
                return row["seq"], row["change_id"]
            if cand["status"] == "rejected":
                raise OverlayError("candidate %s was rejected by %s: %s"
                                   % (candidate_id, cand["decided_by"], cand["decision_reason"]))
            requests = [_check_request(d) for d in json.loads(cand["request"])]
            when = _now()
            approval = {"by": approved_by, "at": when, "candidate_id": candidate_id}
            seq, change_id = self._record(cur, requests, cand["actor"], cand["source"], cand["reason"],
                                          json.loads(cand["evidence"]), approval, validation, None)
            cur.execute("UPDATE candidates SET status = 'approved', decided_at = ?, decided_by = ?, change_seq = ? "
                        "WHERE candidate_id = ?", (when, approved_by, seq, candidate_id))
            return seq, change_id
        return self._write(work)

    def reject(self, candidate_id, *, rejected_by, reason):
        """Reject a pending candidate; it is kept with the reason and never becomes a change.
        Rejecting it again is a no-op; rejecting an approved candidate is refused (undo its change)."""
        rejected_by, reason = _text(rejected_by, "rejected_by"), _text(reason, "reason")

        def work(cur):
            cand = self._candidate_row(cur, candidate_id)
            if cand["status"] == "rejected":
                return
            if cand["status"] == "approved":
                raise OverlayError("candidate %s is approved as change %d; undo that change instead"
                                   % (candidate_id, cand["change_seq"]))
            cur.execute("UPDATE candidates SET status = 'rejected', decided_at = ?, decided_by = ?, "
                        "decision_reason = ? WHERE candidate_id = ?", (_now(), rejected_by, reason, candidate_id))
        self._write(work)

    @staticmethod
    def _candidate_row(cur, candidate_id):
        row = cur.execute("SELECT * FROM candidates WHERE candidate_id = ?", (candidate_id,)).fetchone()
        if row is None:
            raise OverlayError("no candidate %r in this overlay" % (candidate_id,))
        return dict(row)

    def rebuild(self):
        """Recompute the derived tables from ``changes`` and ``deltas`` alone, in one transaction.

        Returns ``{"matched": bool, "rows": n, "changes": n}``: ``matched`` is True when
        the recomputed tables equal the ones that were there."""
        def work(cur):
            before = self._dump(cur)
            for table, _, _ in _TABLE.values():
                cur.execute("DELETE FROM %s" % table)
            changes = 0
            for seq, in cur.execute("SELECT seq FROM changes ORDER BY seq").fetchall():
                changes += 1
                for row in cur.execute("SELECT * FROM deltas WHERE seq = ? ORDER BY ord", (seq,)).fetchall():
                    d = dict(row)
                    d["payload"] = json.loads(d["payload"])
                    _apply_delta(cur, seq, d)
            after = self._dump(cur)
            return {"matched": before == after, "rows": sum(len(v) for v in after.values()), "changes": changes}
        return self._write(work)

    @staticmethod
    def _dump(cur):
        out = {}
        for table, key, _ in _TABLE.values():
            out[table] = [tuple(r) for r in cur.execute("SELECT * FROM %s ORDER BY %s, from_seq" % (table, key))]
        return out

    # --- reading ----------------------------------------------------------------------

    def _read(self, sql, args=()):
        if self._db is None:
            raise OverlayError("this overlay handle is closed")
        return self._db.execute(sql, args).fetchall()

    def meta(self):
        """The base this overlay is bound to, and its schema: a dict of strings."""
        return {r["key"]: r["value"] for r in self._read("SELECT key, value FROM meta")}

    def head(self):
        """``(seq, change_id)`` of the newest change; ``(0, None)`` for an empty overlay."""
        rows = self._read("SELECT seq, change_id FROM changes ORDER BY seq DESC LIMIT 1")
        return (rows[0]["seq"], rows[0]["change_id"]) if rows else (0, None)

    def _pin(self, at):
        seq, _ = self.head()
        if at is None:
            return seq
        if not isinstance(at, int) or isinstance(at, bool) or at < 0 or at > seq:
            raise OverlayError("cannot read at seq %r: the overlay head is %d" % (at, seq))
        return at

    def item(self, kind, target_id, at=None):
        """The overlay's state of one target at ``seq`` ``at`` (head if None), or None if never touched by then."""
        if kind not in _TABLE:
            raise OverlayError("kind must be one of %s" % ", ".join(KINDS))
        at = self._pin(at)
        table, key, _ = _TABLE[kind]
        rows = self._read("SELECT t.*, c.change_id, c.actor, c.source, c.approval, c.created_at "
                          "FROM %s t JOIN changes c ON c.seq = t.from_seq WHERE t.%s = ? AND t.from_seq <= ? "
                          "AND (t.to_seq IS NULL OR t.to_seq > ?)" % (table, key), (target_id, at, at))
        return _item(kind, rows[0]) if rows else None

    def counts(self, at=None):
        """Active overlay items at ``at`` (head if None), by kind and state. Candidates are not counted."""
        at = self._pin(at)
        out = {"seq": at, "nodes_added": 0, "nodes_tombstoned": 0, "edges_added": 0, "edges_tombstoned": 0,
               "rules_added": 0, "rules_replaced": 0, "rules_disabled": 0}
        for kind, (table, _, _) in _TABLE.items():
            for row in self._read("SELECT state, COUNT(*) AS n FROM %s WHERE from_seq <= ? "
                                  "AND (to_seq IS NULL OR to_seq > ?) AND state <> 'none' GROUP BY state"
                                  % table, (at, at)):
                out["%ss_%s" % (kind, row["state"])] = row["n"]
        return out

    def candidates(self, status=None):
        """Candidates, oldest first; ``status`` is 'pending', 'approved', 'rejected' or None for all."""
        if status not in (None, "pending", "approved", "rejected"):
            raise OverlayError("unknown candidate status %r" % (status,))
        sql = "SELECT * FROM candidates" + (" WHERE status = ?" if status else "") + " ORDER BY created_at, candidate_id"
        return [_candidate(r) for r in self._read(sql, (status,) if status else ())]

    def candidate(self, candidate_id):
        """One candidate as a dict, or None."""
        rows = self._read("SELECT * FROM candidates WHERE candidate_id = ?", (candidate_id,))
        return _candidate(rows[0]) if rows else None


def _candidate(row):
    out = dict(row)
    out["evidence"] = json.loads(out["evidence"])
    out["deltas"] = json.loads(out.pop("request"))
    return out


def _item(kind, row):
    table, key, columns = _TABLE[kind]
    out = {"id": row[key]}
    for c in columns:
        out[c] = json.loads(row[c]) if c in _JSON_FIELDS else row[c]
    out["revision"] = row["revision"]
    out["origin"] = {"change_id": row["change_id"], "seq": row["from_seq"], "actor": row["actor"],
                     "source": row["source"], "approval": json.loads(row["approval"]),
                     "created_at": row["created_at"]}
    return out


def _statements(script):
    """The statements of a DDL script, triggers kept whole."""
    out, buf = [], ""
    for line in script.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                out.append(buf.strip())
            buf = ""
    if buf.strip():
        raise ValueError("incomplete statement in schema: %r" % buf)
    return out
