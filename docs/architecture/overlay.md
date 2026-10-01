# The overlay store

Persistent Overlay Infrastructure, slice 2 of the MCO scope for MARCO 1
(`docs/ko/2026-09-22-freeze-decision.md`, "MCO scope for MARCO 1";
requirements from `docs/ko/2026-09-22-mco-integrated-roadmap.md` §4 and §8).
Code: `marco/storage/overlay.py`, `marco/storage/ids.py` (the store);
`marco/storage/graph_view.py`, `marco/storage/graph_text.py` (the merged view and
the graph text writer); `views/kgpack_ui.py` and `pack_model.py` (application at
run time); `mco/overlay.py` and `mco/backends/marco.py` (the `mco` surface).
Tests: `tests/test_overlay_store.py`, `tests/test_overlay_view.py`,
`tests/test_overlay_graph_text.py`, `tests/test_overlay_runtime.py`,
`tests/test_mco_overlay.py`, `tests/test_overlay_application.py`.

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

The first half of this slice is the store (below, up to "Cost"). The second half
joins base and overlay into one merged view and applies it at run time
("The merged view" and after). The base format and its reader are slice 1.

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
(`base_edges=[(src, rel, dst), ...]`); `GraphView.retract_node` builds the request
with them from the base reader's `node_edges`.

**Undo** is a compensating change: `undo(change)` writes one `RESTORE` per target
of that change, putting each back to its state before it. Both changes stay in
the history; nothing is ever deleted from `changes`. It is refused if a later
change touched any of the targets (undo that one first). An undo can be undone.

## Tombstones

A tombstone is a row in `cur_nodes` or `cur_edges` with state `tombstoned`. It
hides the item, whether the base or the overlay has it, from reads at or after
its `seq`. It does not touch the base file, does not remove an id from the
base's tables, and does not delete history. It does not by itself withdraw
conclusions or explanations that depended on the item: at the next turn the
running path reads the merged view without it, and the engine and every open
reasoning context derive their answers again ("Application at run time"). The
store alone cannot tell whether a tombstoned or replaced id exists in the base;
`GraphView.check` can, and the `mco` surface runs it before every write.

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

`commit`, `undo`, `approve` and `propose` take an optional `check(store)`. It is
called inside the change's transaction after the change is recorded (for
`propose`, inside a savepoint that is always rolled back), so it reads the store
as it would be; if it raises, nothing is written and a candidate stays pending.
The `mco` surface passes `GraphView(base, store).check()`.

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

## The merged view

`marco/storage/graph_view.py`. `GraphView(base, store, at=None, base_build_id=...)`
reads a base and an overlay store (or `None`) pinned at one `seq` (the head when
`at` is `None`). It reads everything it needs from the store when it is made, so a
later commit never changes it.

The base is read through a small reader protocol, so `marco` does not import `mco`:

| Call | Returns |
| --- | --- |
| `graph_ids()` | the base's graph ids |
| `graph(graph_id)` | the graph in the dictionary shape `engine.read_kg` returns, without the shared hypernym merge of `data/개념망.json` |
| `node_edges(graph_id, name)` | rows `{"src", "rel", "dst", "list", ...}` of the edges that touch the node (both lists) |
| `rules()` | the rule objects in the order MARCO collects them |

`mco.native.NativeModel` satisfies it (a Format 1.1 file's tables).
`graph_view.PackBase(manifest, members)` satisfies it for a MARCO pack held in
memory; the running path uses it for every file kind, so a graph kept as source
text only in a native file is read the same way.

What the view gives, for a graph id the base has:

| Call | Returns |
| --- | --- |
| `graph(g)` | the merged graph: the base graph with the overlay's tombstoned nodes and edges removed and its added nodes and edges applied |
| `origins(g)` | `{"nodes": {name: origin}, "edges": {edge_id: origin}}` for every node and edge of the merged graph |
| `node_origin(g, name)`, `edge_origin(g, src, rel, dst)` | one origin, or `None` |
| `text(g)` | the merged graph as `.kg` text (below) |
| `rules()`, `rule_origins()`, `rule_changes()` | the base rules minus the disabled ones, with replaced bodies, plus the added ones; each rule's origin; the changes as `(rule_id, state, body)` for `apply_rule_changes` |
| `touched_graphs()` | the graph ids the overlay has a live node or edge change for at this seq |
| `retract_node(g, name, revision=)` | a RETRACT NODE request naming the node's base edges from `node_edges` |
| `check()` | refuses an overlay this base cannot take (below) |

An origin is `{"kind": "base", "build_id"}` or `{"kind": "overlay", "change_id", "seq",
"actor", "source", "approved_by", "approved_at", "candidate_id"}` (the candidate id
when the change came from an approved candidate). Pending and rejected candidates are
not changes, so they never appear in a view.

How deltas apply:

| Delta | In the merged graph |
| --- | --- |
| ADD NODE, `data = {"examples": [...], "layer": "개념" \| "사례" \| "무관" \| "공리", "source": ...}` | the node in that layer (`공리` also in the axiom list) with those examples and `source` as its `출처`; `layer` defaults to `개념`, `examples` are required. A node the base has is replaced: its layer, examples and `출처`; its other slots (value annotations, `물음`, `되물음`) stay |
| ADD EDGE, `data = None` or `{"list": "엣지" \| "개념엣지"}` | appended to the argument edges (`엣지`, default) or the hypernym edges (`개념엣지`, relation `상위` only); an edge the base already has is not repeated, and its origin is the change that added it again |
| RETRACT EDGE | removed from both lists |
| RETRACT NODE | the node removed from every layer, the axiom list and its slots (`수치조건`, `값받이`, ..., `물음`, `되물음`, `출처`), and every edge that touches it removed |

A retracted edge added again has the same `edge_id` (the id is a function of graph,
src, rel and dst). Base rules are matched by rule id: DISABLE removes the rule, REPLACE
puts the new body in its place, ADD puts the body in the base rule's place when the base
has that id (a re-enabled rule comes back where it was) and appends it otherwise, in
change order.

## The graph text writer

`marco/storage/graph_text.py`. The engine reads `.kg` files, so a graph the overlay
touches is written back as text. `parse(bytes)` is the parsing part of `read_kg` for
text in memory (no shared hypernym merge; the engine adds those edges when it reads the
written file, as it does for the original). `write(graph)` is its inverse; it parses its
own output and raises `GraphTextError` when the text would not read back equal.

Proved on every graph under `graphs/`: `read_kg(write(read_kg(file))) == read_kg(file)`
for 904 of 904 graphs, dictionary key order included, no mismatch of any class
(`tests/test_overlay_graph_text.py`). `parse` equals `mco.native.kgtext.parse_kg` for all
904. What has no exact text, and is therefore refused: a node name holding `:` or `#`, an
example holding `|` or `#` or ending in `"`, an edge part holding `,` or an arrow, a node
without examples. No graph in the tree has one; an overlay change that would make one
(for example an added node whose example holds `|`) is refused before it is written.

## Application at run time

`views/kgpack_ui.py`, `AppState(pack, overlay_root=..., graph_overlay=attachment)`, where
`attachment` is a `graph_view.OverlayAttachment(path, base_sha256=, base_build_id=)`. The
attachment checks the binding once and then opens a short-lived read-only handle for each
read, so it can be shared by every session of a model and used from any thread. The
application refuses an attachment bound to another pack (`OverlayBaseMismatch`): the
pack's content identity is the SHA-256 of its `manifest.json`, which is the Format 1
`content_sha256` of the same pack.

What triggers re-materialization: at the start of every `turn()` and `ask()` the
application reads the overlay head `(seq, change_id)` (0.12 ms). When it equals the head
it applied last, nothing else runs. When it differs:

1. the view is read at the new head; every touched graph is written as `.kg` text;
2. each graph whose text changed is written again into the working folder if it was
   written before (`_materialize` writes the view's text instead of the pack's bytes for a
   touched graph, and the pack's bytes again for a graph the overlay no longer touches);
3. the graph-selection entries (manager nodes) of those graphs are rebuilt from the
   merged text with the pack builder's own function (`kgpack._graph_meta`), and the
   selection index is rebuilt;
4. the rules: `PackModel.apply_rule_overlay(changes, key)` on the model and its companion
   language models (below);
5. the active graph is reloaded if its include closure holds a changed graph (its engine
   `Session` starts again on the new graph);
6. every open reasoning context is re-created from its own `snapshot()` with the saved
   `replay` dropped, so the conversation is re-derived under the current view
   (`marco/reasoning/context.py` is not changed);
7. a conversation store bound to its base (`conversations.binding`) gets the applied head,
   so each saved state records the head it was derived under.

A saved reasoning state restored from a bound store is used as that store decides (same
head: its replay; another head: re-derived). From an unbound store, with an attached overlay
that has changes, the saved replay is dropped. With the same head nothing is re-derived:
`tests/test_event_provenance.py` (a restored context answers from its saved replay without
re-parsing) keeps passing.

An attached overlay gets its own working folder (the pack hash plus a hash of the overlay's
path), since its graph files differ from the pack's. With no overlay attached, or one whose
head is seq 0, none of the code above runs: the files written and the answers are those of
main (`tests/test_overlay_runtime.py` and `tests/test_overlay_application.py`; also checked
once against main's own `views/kgpack_ui.py`, `pack_model.py` and `mco` `translate` on the same
24 turns, with and without a conversation id: payloads apart from conversation ids and times,
working-folder bytes and translated results equal).

Engine caches: the one cache keyed by file size and mtime (`engine.graph_index`'s
`.색인예시.json`) indexes the source tree, never the working folder; the vector cache is
keyed by content, so a changed graph gets new vectors. The pack's graph-selection index is
rebuilt as in step 3.

Rules (`pack_model.py`): the changes apply after the model is loaded, to the loaded rule
list (axiom rules, then any rules of the pack's relational model), not through
`_load_relational_model`'s extension check. `PackModel.fingerprint` stays the base
fingerprint, byte for byte. `PackModel.effective_key` is the fingerprint without rule
changes, and with them the SHA-256 of the fingerprint and `seq:change_id` of the head they
were read at; the parser cache is keyed by it, so a rule change reaches the next turn's
parser and an unchanged overlay reuses the cached parser (`tests/test_r6_parse_speed.py`
keeps passing).

`AppState.export_pack` is refused while an overlay is attached: folding overlay changes
into a new pack is consolidation, which this slice does not do.

## Evidence origins

When an overlay with changes is attached, a `turn()` result's trace carries
`origins = {"overlay_seq", "overlay_change", "edges": [[src, rel, dst, origin], ...],
"nodes": {name: origin}}` for the graph items of its path and evidence that came from the
overlay (for several graphs, under the same `graph::name` prefixes the merged trace uses).
`mco` puts the origin into `Evidence.detail["origin"]` of the `graph_path` and `graph_node`
evidence it names. Base items get nothing, so their evidence is as it was.

`_packed_evidence` (and the comparison path that uses it) reads the approved collection
records (`.수집.jsonl`) carried in the pack, not graph nodes or edges. The overlay holds no
collection records, so that evidence is read from the pack as before and has no overlay
origin.

## Checks and refusals

| Refused | Where | Error |
| --- | --- | --- |
| an overlay bound to another base (content SHA-256 or build id) | `OverlayStore.open`, `OverlayAttachment`, `AppState`, `mco.load(..., overlay=)`, `mco.open_overlay` | `OverlayBaseMismatch`; `mco.OverlayBaseMismatchError` |
| a delta naming a graph the base does not have (whole new graphs are not supported) | `GraphView.check`, `graph()`, `text()` | `ViewError` (an `OverlayError`); `mco.OverlayError` |
| a change to a graph with no exact `.kg` text, or one that would make it so | `GraphView.text`, `check` | `ViewError` |
| ADD NODE without examples, with an unknown layer or data key | `node_data`, `check` | `ViewError` |
| ADD EDGE whose end is not a node of the graph or of a graph it includes; a `개념엣지` edge whose relation is not `상위` | `check` | `ViewError` |
| RETRACT EDGE or RETRACT NODE of something the base does not have and the overlay never added | `check` | `ViewError` |
| DISABLE or REPLACE of a rule the base does not have and the overlay never added; a rule body that is not an object with that `id` and `head` and `body` lists | `check` | `ViewError` |
| a stale revision, a second writer, a conflicting change id, a rejected candidate approved | the store (above) | `OverlayStaleRevision`, `OverlayWriterBusy`, `OverlayConflict`, `OverlayError`; `mco.OverlayError` |
| export of a pack while an overlay is attached | `AppState.export_pack` | `ValueError` |

Every write through `mco` runs `check` inside the store's transaction, so a refused change
writes nothing (and a refused approval leaves the candidate pending).

## The `mco` surface

`mco.create_overlay(model, path)` creates an overlay bound to the model's content SHA-256
and build id (a bare `.kgpack` has no build id; it gets `sha256-` plus the first 12 hex
digits of the file). `mco.open_overlay(model, path)` opens it as the one writer:
`commit`, `propose`, `approve`, `reject`, `undo`, `head`, `counts`, `history`, `candidates`,
`status`. Every change names its approver (`approved_by`); there is no default.
`mco.load(model, overlay=path)` attaches it to every session; `mco.inspect(model,
overlay=path)` and `mco inspect MODEL --overlay PATH` show its binding, head and active
counts without running the model; `mco overlay ...` does the same from the command line.
A conversation snapshot of a session with an attached overlay records the overlay's head
and a copy of it, and resumes only with an overlay that holds that history. Details:
`docs/mco/api.md`.

## Cost of application (measured 2026-10-01, macOS laptop, busy machine)

The one-graph test model of `tests/test_overlay_runtime.py` (plus two graphs of the tree for
the main comparison), medians of the last 12 of 24 turns. A turn with no overlay attached:
62.9, 61.1 and 63.9 ms on main against 62.0, 61.1 and 63.1 ms on this branch (three runs
each; the same within noise); with an empty overlay attached 64.4 ms. A turn with an overlay attached and
unchanged: 60.4 ms, of which the head check is 0.12 ms. The first turn after a graph commit:
393 ms (the next: 62 ms); after a rule commit: 386 ms (the next: 61 ms). Of the first turn
after a graph commit (388 ms), re-reading the view, writing the graph and rebuilding the
selection index and the active graph take 3.7 ms; re-deriving the open reasoning context
(its next turn reads the conversation's earlier statements again, without a saved replay)
takes 308 ms. That part grows with the length of the open conversations.

## Not supported

- More than one writer at a time.
- Persona scopes, session state, or any per-subject separation.
- New whole graphs through the overlay: a delta naming a graph the base does not have is
  refused at view time.
- Compaction, consolidation into a new base (including `export_pack` with an overlay),
  or deleting history.
- Conflict records: a change on a stale revision is refused, not recorded as a conflict.
- Any self-initiated change: no change from dialogue, self-repair, web or document
  reading, and no automatic approval. Every change is an explicit API or CLI call naming
  its approver. The sidecars beside each graph, the approval door and the pack export are
  not moved onto the overlay.
- Overlay chunks inside a Format 1 file: the overlay is a separate store, and the manifest's
  `supports.overlay` stays `false`.
- Rule changes to rules outside the base rule table (the rules a pack's relational model
  adds after the axioms): `check` refuses them, since a base reader lists the axiom rules.
- Origins for edges a graph borrows through `포함` from another graph: the borrowed edges
  are reported under the borrowing graph, where they have no overlay origin.
- A commit made while another session of the same model is in the middle of a turn: that
  turn may read some graph files at the new head; the next turn of every session applies
  the new head as a whole.
- A conversation snapshot taken while a commit lands between the turn's application of the
  head and the copy of the overlay records the newer head with a state derived under the
  older one.
