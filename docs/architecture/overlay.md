# The overlay store

Persistent Overlay Infrastructure, slice 2 of the MCO scope for MARCO 1
(`docs/ko/2026-09-22-freeze-decision.md`, "MCO scope for MARCO 1";
requirements from `docs/ko/2026-09-22-mco-integrated-roadmap.md` §4 and §8).
Code: `marco/storage/overlay.py`, `marco/storage/ids.py`. Tests:
`tests/test_overlay_store.py`.

## Purpose

A compiled base (`.mco`) is immutable. The overlay is one file beside it that
holds graph and rule changes that were **stated explicitly or approved from
outside**: by a person, or by a caller of the API who names an approver. A change
applies at the next read, with no recompile, and the base file is never written.

This is storage and runtime infrastructure. Nothing in it starts a change by
itself: there is no code path from dialogue, self-repair, web or document reading
to a change, and no default approver. The existing routes (the sidecars beside
each graph, the approval door, the pack export) are not moved onto the overlay.
The store records and resolves; it holds no word-level, verb-level or case-level
judgement.

This slice is the store alone. Joining base and overlay into one graph view, and
connecting the engine, is the next slice; the base format and its reader are slice 1.

## Schema

One SQLite file (`sqlite3`, standard library), WAL journal, `synchronous = FULL`,
`application_id` `0x4D434F4F`, `user_version` = the overlay schema (1).

| Table | Rows | Rule |
| --- | --- | --- |
| `meta` | `base_sha256`, `base_build_id`, `format_version` (the base format version the overlay was made for), `overlay_schema`, `created_at` | fixed at creation; triggers refuse UPDATE and DELETE |
| `changes` | `seq`, `change_id` (`chg_` + ULID from `marco.trace.ledger.new_id`), `created_at`, `actor`, `source`, `reason`, `evidence` (JSON), `parent_seq` (the head the change was made on), `approval` (JSON: `by`, `at`, and `candidate_id` when it came from a candidate), `validation` (JSON, the caller's), `request_digest` | append-only: triggers refuse UPDATE and DELETE; `seq` must be the head plus one |
| `deltas` | `seq`, `ord`, `op`, `target_kind`, `target_id`, `graph_id`, `payload` (JSON), `revision` | append-only; written only with their own change |
| `cur_nodes`, `cur_edges`, `cur_rules` | one row per target and per change that touched it, valid from `from_seq` until `to_seq` (NULL = current), with `state`, the item's columns and its `revision` | derived; `rebuild()` recomputes them from `changes` and `deltas` alone and reports whether they matched |
| `candidates` | the proposed deltas, proposer, evidence, `proposed_at_seq`, `status` (`pending`, `approved`, `rejected`), `decided_at`, `decided_by`, `decision_reason`, `change_seq` | never deleted; a decided candidate cannot change; the request is fixed at proposal |

Opening an overlay with a different `base_sha256` (or, when given, a different
`base_build_id`) raises `OverlayBaseMismatch`. Opening a path with no overlay is
an error; only `OverlayStore.create` makes one, and it refuses an existing path.
No empty overlay is ever started silently.

## Ids

`marco/storage/ids.py`, standard library only, shared with the base format so
both agree byte for byte. No id is positional or ordinal.

| Id | Encoding |
| --- | --- |
| `graph_id` | the graph's pack path with forward slashes, NFC (`graphs/x.kg`) |
| `node_id` | `graph_id + "#" + name`, the name NFC |
| `edge_id` | `"e:"` + the first 32 lower-case hex characters of SHA-256 over the UTF-8 bytes of graph_id, src, rel, dst (each NFC; src and dst are node names) joined by the byte `0x1F`; a part containing `0x1F` is refused |
| `rule_id` | the existing rule id string, unchanged |

Fixed values in the tests: `edge_id("graphs/x.kg", "a", "is", "b")` =
`e:ad915d5e1daca67813991cca8c86fef2`; `edge_id("graphs/사람.kg", "철수", "친구", "영희")`
= `e:26924db0004b2a70ae2de12c9fa26366`. Retracting an edge and adding it again
gives the same id.

## Operations and revisions

| Op | Effect on the target's overlay state |
| --- | --- |
| `ADD_NODE` | none or tombstoned → added |
| `ADD_EDGE` | none or tombstoned → added; refused if either end node is tombstoned in the overlay |
| `ADD_RULE` | none or disabled → added |
| `RETRACT_EDGE` | none or added → tombstoned |
| `DISABLE_RULE` | none, added or replaced → disabled |
| `RETRACT_NODE` | none or added → tombstoned, and one `RETRACT_EDGE` per live edge of the node, recorded as explicit deltas in the same change |
| `REPLACE_RULE` | none or replaced → replaced (the base rule's body is superseded); added → added with the new body; disabled → refused |
| `RESTORE` | written only by `undo`: the target's state just before the undone change |

Every target has a revision: 0 until the overlay first touches it, plus one per
delta. A delta names the revision it applies to; a different current revision
raises `OverlayStaleRevision` and the whole change is refused. Builders
(`add_node`, `add_edge`, `add_rule`, `retract_edge`, `disable_rule`,
`retract_node`, `replace_rule`) return plain dicts and require `revision`.

`RETRACT_NODE` finds the overlay's own live edges of the node. This store does not
read the base, so the base's edges of the node are named by the caller
(`base_edges=[(src, rel, dst), ...]`); the next slice, which has the base reader,
supplies them.

**Undo** is a compensating change: `undo(change)` writes one `RESTORE` per target
of that change, putting each back to its state before it. Both changes stay in
the history; nothing is ever deleted from `changes`. It is refused if a later
change touched any of the targets (undo that one first). An undo can be undone.

## Tombstones

A tombstone is a row in `cur_nodes` or `cur_edges` with state `tombstoned`. It
hides the item, whether the base or the overlay has it, from reads at or after
its `seq`. It does not touch the base file, does not remove an id from the
base's tables, and does not delete history. It does not by itself withdraw
conclusions or explanations that depended on the item: that is the view and the
engine's work in the next slice. The store cannot tell whether a tombstoned or
replaced id exists in the base; it records the tombstone either way.

## One writer

A writer holds an OS lock (`fcntl.flock` on POSIX, `msvcrt.locking` on Windows)
on `<overlay>.writer-lock` for as long as it is open. A second writer, in the same
process or another, gets `OverlayWriterBusy` at once; it is never queued. Every
change is one `BEGIN IMMEDIATE` transaction with a busy timeout of 0, so a foreign
connection holding a write transaction also makes the commit refuse at once.
Readers take no lock (`PRAGMA query_only`), and WAL lets them read while the
writer commits. The lock file holds no data; it is left in place.

## Reading

All reads are plain data (dicts, lists, tuples), no engine types. Every read that
takes `at` reads the state as of that `seq` (head if `None`); a reader that needs
one consistent picture over several calls pins `at = head()[0]` once. Rows valid
at an earlier `seq` are never rewritten, so a pinned read gives the same answer
later.

| Function | Returns |
| --- | --- |
| `head()` | `(seq, change_id)`, `(0, None)` when empty |
| `added_nodes(at)`, `added_edges(at)`, `added_rules(at)` | items with their columns, `revision` and `origin` (`change_id`, `seq`, `actor`, `source`, `approval`, `created_at`) |
| `tombstoned_nodes(at)`, `tombstoned_edges(at)`, `tombstoned_ids(at)` | hidden items, or `{"nodes": [...], "edges": [...]}` |
| `disabled_rules(at)`, `replaced_rules(at)` | rules with origin; a replaced rule carries the new body |
| `item(kind, target_id, at)` | one target's state, or `None` |
| `counts(at)` | active items by kind and state; candidates are not counted |
| `history(target_id)` | every delta on the target with its change's provenance |
| `change(seq or change_id)` | one change with its deltas |
| `candidates(status)`, `candidate(id)`, `meta()` | as named |

## Candidates

`propose(deltas, actor, source, reason, evidence)` stores a candidate. It is in no
current-state table and no count. `approve(candidate_id, approved_by=...)` is
always an explicit call with the approver's identity from the caller: in one
transaction the candidate becomes a change with its deltas (actor and evidence
from the proposal, approval naming the approver and the candidate) and is marked
approved. Approving again is a no-op that returns the same change. A candidate
whose target revision went stale is refused at approval and stays pending.
`reject(candidate_id, rejected_by, reason)` keeps it with the reason; it never
becomes a change. `commit()` also requires `approved_by`.

## Crash behaviour

A failure inside a change rolls the whole transaction back: no change row, no
delta, no derived row is visible. A process killed mid-commit leaves an
uncommitted WAL tail that SQLite discards on the next open; the OS releases the
writer lock with the process, so the store reopens as a writer at once. A process
killed just after `COMMIT` keeps the change; retrying with the same `change_id`
is a no-op (a different content under the same id raises `OverlayConflict`).
SQLite's journal does the work a truncated-line rule does in the JSONL ledger.

## Cost (measured 2026-10-01, macOS laptop, busy machine)

A store of 10,000 changes (9,000 adding a node and an edge, 1,000 retracting an
edge): building it took 1.7 s; one commit, median 0.14 ms, p95 0.19 ms; a full
pinned read (all seven lists plus counts) 36 ms at seq 5,000 and 78 ms at
seq 10,000; one pinned item lookup 0.008 ms; `head()` 0.004 ms; `rebuild()`
0.4 s. File 9.9 MB plus a 4.2 MB WAL. With `PRAGMA fullfsync = ON` (macOS
power-loss durability, not set by default) one commit is 4.0 ms.

## Not supported

- More than one writer at a time.
- Persona scopes, session state, or any per-subject separation.
- New whole graphs through the overlay (a delta names a `graph_id`; the store does
  not create or register graphs).
- Compaction, consolidation into a new base, or deleting history.
- Reading the base: the store cannot check that a retracted or replaced id exists
  in the base, and cannot find a base node's edges by itself.
- Any self-initiated change: no change from dialogue, self-repair, web or
  document reading, and no automatic approval.
