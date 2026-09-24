"""Append-only JSONL event ledger (design note §4, §33).

One event per line. A ledger is one file in a directory the caller names; the
default directory is ``logs/`` at the repository root (gitignored) and
``MARCO_TRACE_DIR`` overrides it. Nothing is ever rewritten:

* every ``parent_ids`` and ``input_refs`` entry names an earlier event of the
  same ledger, checked on append and on read, so the events form a DAG;
* a correction is a new event that names what it ``supersedes``, plus a
  ``conclusion_withdrawn`` event for the old one (§21);
* a ``state_changed`` event carries ``before``, ``after`` and ``cause`` (§20);
* a truncated last line (a writer that died mid-line) is tolerated and
  reported by the reader. The next writer ends that line and appends an
  ``error`` event that declares it truncated, so a later read still accepts it;
  any other unreadable line is an error.

One writer per file at a time. Ids stay unique across processes that append
to the same file one after another: a writer reads the file before it appends.

Only the standard library.
"""
import hashlib
import json
import os
from pathlib import Path
import threading
import time

from marco.trace import schema

ENV = "MARCO_TRACE_DIR"
ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = ROOT / "logs"

_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_id_lock = threading.Lock()
_last = [0, 0]


class LedgerError(ValueError):
    """The ledger file or an append breaks the ledger's rules. ``line`` is 1-based when known."""

    def __init__(self, message, line=None, field=None):
        super().__init__(("line %d: " % line if line else "") + message)
        self.line = line
        self.field = field


def _ulid():
    """48-bit milliseconds + 80 bits; within one process never the same value twice."""
    with _id_lock:
        now = int(time.time() * 1000) & ((1 << 48) - 1)
        if now <= _last[0]:
            now, tail = _last[0], (_last[1] + 1) & ((1 << 80) - 1)
        else:
            tail = int.from_bytes(os.urandom(10), "big")
        _last[0], _last[1] = now, tail
    n = (now << 80) | tail
    out = []
    for _ in range(26):
        out.append(_B32[n & 31])
        n >>= 5
    return "".join(reversed(out))


def new_id(prefix):
    return prefix + _ulid()


def default_directory():
    return Path(os.environ.get(ENV) or DEFAULT_DIR)


def from_env(name=None, **options):
    """The ledger in ``MARCO_TRACE_DIR``, or None: recording is off unless it is set."""
    return Ledger(os.environ[ENV], name, **options) if os.environ.get(ENV) else None


def dumps(event):
    return json.dumps(event, ensure_ascii=False, separators=(",", ":"))


def check_links(event, index, withdrawn, superseded_by, line=None):
    """The DAG rules: every reference names an earlier event; one successor, one withdrawal."""
    eid = event["event_id"]
    if eid in index:
        raise LedgerError("duplicate event id %s" % eid, line=line, field="event_id")
    for name in ("parent_ids", "input_refs"):
        for ref in event[name]:
            if ref not in index:
                raise LedgerError("%s names %s, which is not an earlier event of this ledger "
                                  "(a forward reference is how a cycle would start)" % (name, ref),
                                  line=line, field=name)
    target = event.get("supersedes")
    if target is not None:
        if target not in index:
            raise LedgerError("supersedes %s, which is not an earlier event" % target, line=line,
                              field="supersedes")
        if target in superseded_by:
            raise LedgerError("%s is already superseded by %s" % (target, superseded_by[target]),
                              line=line, field="supersedes")
    if event["kind"] == "conclusion_withdrawn":
        old = event["payload"]["withdrawn"]
        if old not in index:
            raise LedgerError("withdraws %s, which is not an earlier event" % old, line=line,
                              field="payload.withdrawn")
        if old in withdrawn:
            raise LedgerError("%s is already withdrawn by %s" % (old, withdrawn[old]), line=line,
                              field="payload.withdrawn")
    if event["kind"] == "state_changed":
        cause = event["payload"]["cause"]
        if cause is not None and cause not in index:
            raise LedgerError("cause %s is not an earlier event" % cause, line=line, field="payload.cause")


class _Index:
    """Events in ledger order and the links between them."""

    def __init__(self):
        self.events, self.index = [], {}
        self.withdrawn, self.superseded_by = {}, {}
        self.problems = []
        self.bad = {}                # unreadable line number -> fragment, until an error event declares it
        self.lines = 0               # complete lines consumed

    def feed(self, data):
        """Consume complete lines (``data`` ends with a newline or is empty)."""
        for raw in data.split(b"\n")[:-1]:
            self.lines += 1
            if not raw.strip():
                continue
            try:
                event = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                self.bad[self.lines] = raw
                continue
            self.add(event, self.lines)

    def tail(self, raw):
        """An unterminated last line: an event if it parses, else a reported truncation."""
        number = self.lines + 1
        try:
            event = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            cut = {"line": number, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
            self.problems.append({"problem": "truncated_last_line", **cut})
            return cut
        self.problems.append({"problem": "unterminated_last_line", "line": number})
        self.add(event, number)
        return None

    def add(self, event, number=None, checked=False):
        if not checked:
            found = schema.problems(event)
            if found:
                field, message = found[0]
                raise LedgerError("%s: %s" % (field, message), line=number, field=field)
            check_links(event, self.index, self.withdrawn, self.superseded_by, line=number)
        if event["kind"] == "error" and event["payload"].get("problem") == "truncated_line":
            declared = event["payload"].get("line")
            if declared in self.bad:
                del self.bad[declared]
                self.problems.append({"problem": "truncated_line_declared", "line": declared,
                                      "declared_by": event["event_id"]})
        self.index[event["event_id"]] = len(self.events)
        self.events.append(event)
        if event.get("supersedes") is not None:
            self.superseded_by[event["supersedes"]] = event["event_id"]
        if event["kind"] == "conclusion_withdrawn":
            self.withdrawn[event["payload"]["withdrawn"]] = event["event_id"]

    def undeclared(self):
        if self.bad:
            line = min(self.bad)
            raise LedgerError("unreadable line, not declared truncated by a later error event", line=line)


def read(path):
    """``(events, problems)`` of one ledger file.

    A truncated last line is reported in ``problems``; an unreadable line
    elsewhere, a schema violation, or a reference to a later or missing event
    raises ``LedgerError`` with the line number.
    """
    data = Path(path).read_bytes()
    index = _Index()
    cut = data.rfind(b"\n") + 1
    index.feed(data[:cut])
    index.undeclared()
    if data[cut:].strip():
        index.tail(data[cut:])
    return index.events, index.problems


def read_many(path):
    """Events of a ledger file, or of every ``*.jsonl`` in a directory (each checked on its own)."""
    path = Path(path)
    files = sorted(path.glob("*.jsonl")) if path.is_dir() else [path]
    events, found = [], []
    for one in files:
        got, problems = read(one)
        events += got
        found += [dict(p, file=str(one)) for p in problems]
    return events, found


class Ledger:
    """One append-only ledger file.

    ``directory``: where the file lives (default ``MARCO_TRACE_DIR``, else ``logs/``).
    ``name``: the file name (default ``<date>.jsonl``, §33). ``runtime``: fields
    stamped into every event's ``runtime``.
    """

    def __init__(self, directory=None, name=None, *, runtime=None, fsync=False):
        directory = Path(directory) if directory is not None else default_directory()
        name = name or time.strftime("%Y-%m-%d")
        if not name.endswith(".jsonl"):
            name += ".jsonl"
        self.path = directory / name
        self.runtime = dict(runtime or {})
        self.fsync = fsync
        self.sessions = {}           # adapter state per conversation (marco/trace/from_turn.py)
        self.bytes_written = 0
        self._lock = threading.RLock()
        self._fd = None
        self._state = _Index()
        self._offset = 0
        self._open_line = False      # the file does not end with a newline
        self._cut = None             # the truncated last line, until it is declared
        self._sync()
        self._state.undeclared()

    # -- reading -------------------------------------------------------------------
    @property
    def events(self):
        return self._state.events

    @property
    def withdrawn(self):
        return self._state.withdrawn

    @property
    def superseded_by(self):
        return self._state.superseded_by

    @property
    def problems(self):
        return self._state.problems

    def get(self, event_id):
        position = self._state.index.get(event_id)
        return None if position is None else self._state.events[position]

    def position(self, event_id):
        return self._state.index.get(event_id)

    def __contains__(self, event_id):
        return event_id in self._state.index

    def is_withdrawn(self, event_id, before=None):
        """Whether ``event_id`` was withdrawn (by an event earlier than position ``before``)."""
        by = self._state.withdrawn.get(event_id)
        return by is not None and (before is None or self._state.index[by] < before)

    def _sync(self):
        """Read what was appended to the file since the last read (by anyone)."""
        try:
            size = self.path.stat().st_size
        except FileNotFoundError:
            return
        if size <= self._offset:
            return
        with open(self.path, "rb") as handle:
            handle.seek(self._offset)
            data = handle.read(size - self._offset)
        cut = data.rfind(b"\n") + 1
        self._state.feed(data[:cut])
        self._offset += len(data)
        tail = data[cut:]
        self._open_line = bool(tail)
        if tail:
            self._cut = self._state.tail(tail)

    # -- writing -------------------------------------------------------------------
    def _write(self, data):
        if self._fd is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fd = os.open(self.path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        os.write(self._fd, data)
        if self.fsync:
            os.fsync(self._fd)
        self._offset += len(data)
        self.bytes_written += len(data)

    def _end_open_line(self):
        """End a cut last line; declare it truncated with an ``error`` event (§22)."""
        self._write(b"\n")
        self._open_line = False
        self._state.lines += 1
        cut, self._cut = self._cut, None
        if cut is None:
            return
        self._state.bad[cut["line"]] = b""
        self._append("error", new_id(schema.TRACE_PREFIX), status="error", epistemic_status="observed",
                     subsystem="trace", subject=self.path.name,
                     payload={"problem": "truncated_line", "line": cut["line"], "bytes": cut["bytes"],
                              "sha256": cut["sha256"]},
                     runtime={"build": self.runtime.get("build"), "pack": None})

    def new_event_id(self):
        while True:
            candidate = new_id(schema.EVENT_PREFIX)
            if candidate not in self._state.index:
                return candidate

    def new_trace_id(self):
        return new_id(schema.TRACE_PREFIX)

    def append(self, kind, trace_id, **fields):
        """Validate, check the DAG rules, write one line. Returns the event (a dict).

        Keyword fields: ``parent_ids``, ``status`` (default success),
        ``epistemic_status`` (default unknown), ``subject``, ``input_refs``,
        ``output_refs``, ``source``, ``operation``, ``payload``, ``runtime``,
        ``supersedes``, ``subsystem``, ``system``, ``scope``, ``goal_id``,
        ``level``, ``event_id``, ``timestamp``.
        """
        with self._lock:
            if self._open_line:
                self._end_open_line()
            return self._append(kind, trace_id, **fields)

    def _append(self, kind, trace_id, *, parent_ids=(), status="success", epistemic_status="unknown",
                subject=None, input_refs=(), output_refs=(), source=None, operation=None, payload=None,
                runtime=None, supersedes=None, subsystem=None, system=schema.SYSTEM, scope=None,
                goal_id=None, level=None, event_id=None, timestamp=None):
        event = {"schema": schema.SCHEMA,
                 "event_id": event_id or self.new_event_id(),
                 "trace_id": trace_id,
                 "parent_ids": list(parent_ids),
                 "timestamp": round(time.time() if timestamp is None else timestamp, 6),
                 "system": system,
                 "subsystem": subsystem,
                 "kind": kind,
                 "status": status,
                 "epistemic_status": epistemic_status,
                 "subject": subject,
                 "input_refs": list(input_refs),
                 "output_refs": list(output_refs),
                 "source": dict(source or {}),
                 "operation": dict(operation or {}),
                 "payload": dict(payload or {}),
                 "runtime": {**self.runtime, **(runtime or {})}}
        for name, value in (("supersedes", supersedes), ("scope", scope), ("goal_id", goal_id),
                            ("level", level)):
            if value is not None:
                event[name] = value
        schema.validate(event)
        state = self._state
        if any(ref not in state.index for ref in event["parent_ids"] + event["input_refs"]):
            self._sync()             # another writer may have appended them since
        check_links(event, state.index, state.withdrawn, state.superseded_by)
        self._write((dumps(event) + "\n").encode("utf-8"))
        state.lines += 1
        state.add(event, state.lines, checked=True)
        return event

    def state_changed(self, trace_id, subject, field, before, after, cause, *, parent_ids=None, **fields):
        """§20: a state change names its value before and after and the event that caused it."""
        payload = {"field": field, "before": before, "after": after, "cause": cause,
                   **(fields.pop("payload", None) or {})}
        parents = list(parent_ids) if parent_ids is not None else ([cause] if cause else [])
        return self.append("state_changed", trace_id, subject=subject, parent_ids=parents,
                           payload=payload, **fields)

    def withdraw(self, old_id, trace_id, *, parent_ids, reason, superseded_by=None, **fields):
        """A ``conclusion_withdrawn`` event for ``old_id``; the old event stays as it was."""
        old = self.get(old_id) or {}
        payload = {"withdrawn": old_id, "reason": reason}
        if superseded_by is not None:
            payload["superseded_by"] = superseded_by
        fields.setdefault("epistemic_status", "withdrawn")
        fields.setdefault("subsystem", old.get("subsystem"))
        fields.setdefault("subject", old.get("subject"))
        return self.append("conclusion_withdrawn", trace_id, parent_ids=parent_ids,
                           input_refs=[old_id], payload=payload, **fields)

    def correct(self, old_id, kind, trace_id, *, reason="corrected", **fields):
        """§21: a new event that ``supersedes`` ``old_id``, then the old one's withdrawal.

        Returns ``(new_event, withdrawal_event)``.
        """
        new = self.append(kind, trace_id, supersedes=old_id, **fields)
        gone = self.withdraw(old_id, trace_id, parent_ids=[new["event_id"]], reason=reason,
                             superseded_by=new["event_id"], runtime=fields.get("runtime"))
        return new, gone

    def close(self):
        with self._lock:
            if self._fd is not None:
                os.close(self._fd)
                self._fd = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
