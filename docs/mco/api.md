# mco API contract

This document states what `mco` promises to keep stable while MARCO's internals
and model format change, and how a new runtime plugs in.

## Layers

```
user code ──► mco (public API)          load · compile · inspect · benchmark
                │                       Model · Session · Result · Status · Evidence · Trace
                ▼
             mco.backends (contract)    Backend · BackendModel · BackendSession
                │
       ┌────────┴──────────┐
       ▼                   ▼
 marco-kgpack          mco-native
 (compat .mco or       (MCO Format 1 .mco, read by mco.native;
  .kgpack payload)      the pack is rebuilt from the file's chunks)
       │                   │
       └────────┬──────────┘
                ▼
          MARCO engine (one shared model/session class, MarcoModel)
```

* Only `mco/backends/marco.py` imports MARCO modules; `mco/backends/native.py`
  reaches the engine through it. A test enforces this, and two others check
  that `import mco` followed by `mco.inspect()` imports no MARCO module, for a
  compat file and for a native file.
* `mco.native` (the Format 1 reader and writer) is standard library only and
  internal: user code goes through `load`, `compile` and `inspect`.
* MARCO's verdict labels (`인정`, `미지`, `B2`, ...) and trace keys are mapped to
  `Status`, `Evidence` and `TraceStep` inside that one file. When MARCO changes a
  label, only that file changes.

## Stability rules (API version 1)

Stable:

* The names exported from `mco` (`mco.__all__`) and their signatures. Parameters
  may be added, as keyword-only with defaults, but never removed or reordered.
* `Result.answer`, `status`, `evidence`, `trace`, `input`, `backend`, `ok`, and
  `to_dict()` keys.
* `Status` values. New values may be added later, so treat an unrecognised
  status like `unknown`.
* `Evidence.kind`, `text`, `source`, `score`, and `TraceStep.stage`, `summary`.
  New kinds and stages may appear.
* `Capability` names, and the `ModelInfo` fields other than `manifest`.
* The error class hierarchy.
* CLI subcommands, flags and exit codes.

Not stable (backend-specific; use only for debugging):

* `Result.raw_status`, `Result.raw`
* `Evidence.detail`, `TraceStep.detail`
* `ModelInfo.manifest`

Current evidence kinds: `graph_node`, `graph_path`, `state_transition`,
`derived_fact`, `definition`, `fact`, `external_source`. Current trace stages:
`understand`, `route`, `judge`, `reason`, `retrieval`, `research`, `plan`,
`verify`, `fact`.

## Sessions and isolation

* `Model.run` uses one default session per model.
* `Model.session()` returns an independent session. With the MARCO backend, each
  session owns a separate MARCO application object, because MARCO keeps some
  dialogue state per application. When a session is closed, its application is
  reset and reused, since opening one re-indexes the pack.
* `Model.reason()` always starts from a clean context, and leaves both the
  default session and the other sessions untouched.

## MARCO backend options

Both built-in backends run on the MARCO engine and take the same options.

| Option | Default | Meaning |
|---|---|---|
| `allow_network` | `False` | Let MARCO research unknown questions on the web and propose learning plans. When off, those questions come back as `unknown` |
| `overlay_dir` | temporary directory | Where the MARCO runtime keeps the files it writes while it runs. The model file itself is never modified |
| `overlay` | none | An overlay store to attach (Persistent Overlay Infrastructure, below): explicit or approved graph and rule changes, read at the start of every turn |
| `marco_root` | discovery | The MARCO checkout to run |

## `.mco` compatibility container (container version 0)

A ZIP with exactly two members, written with fixed timestamps so that the
output is byte-deterministic:

* `mco.json`:
  ```json
  {"format": "mco", "container": "compat-zip", "container_version": 0, "api": 1,
   "name": "MARCO-1", "build_id": "sha256-<12 hex>", "generator": "mco 0.1.0",
   "payload": {"kind": "kgpack", "path": "payload.kgpack", "bytes": 0, "sha256": "…",
               "kgpack_version": 3},
   "runtime": {"backend": "marco-kgpack"},
   "model": {"...": "the kgpack's model declaration (language, axioms)"}}
  ```
* `payload.kgpack`: the unmodified MARCO pack.

Loading verifies the payload hash and every file hash inside the pack. Unknown
container versions are rejected, not guessed at. Files starting with `\x89MCO`
are native files and go to the `mco-native` backend.

## `.mco` native file (MCO Format 1.1)

Not in 0.1.0 on PyPI; in the repository since 2026-10-01. The byte layout,
tables, identifiers and every accept/refuse verdict are specified in
[format-1.md](format-1.md). In short: a 96-byte header, chunks, a table of
contents with a SHA-256 per chunk, a canonical JSON manifest, string, member
and graph-directory tables, and (1.1) node and edge tables per graph, a
per-graph table directory and a rule table. Language packs, axiom files and
records are **carried members**: typed chunks holding the pack files
unchanged. Each graph's source text is kept as a carried `GRPH` chunk, and the
running path still parses it (below).

* Write one with `mco.compile(source, output, format="native")` or
  `mco compile SOURCE -o OUTPUT --format native`. `format` is a new keyword
  with the default `"compat"`, so 0.1.0 calls write exactly what they wrote
  before. Native output is deterministic.
* `mco.load` and `mco.inspect` recognise it by its magic; the manifest's
  runtime is `mco-native`. Loading verifies every chunk checksum, every member
  hash and the content identity unless `verify=False`.
* `ModelInfo` for a native file: `format` `"mco-native"`, `format_version` the
  major version (`1`), and `manifest` (not stable) holds `mco` (the file's
  manifest), `format` (major, minor, flags, size), `chunks` (type, version,
  required, compression, offset, stored and raw size, SHA-256, role),
  `members` and `tables` (graph, node, edge, example and rule counts, and the
  graphs kept as source text only with their reasons). `notes` give the table
  counts and say that an overlay store beside the file can be attached (the
  file itself holds none; `supports.overlay` stays `false`), and that
  conversation snapshots are (they bind to the file's `content_sha256` and
  build id; the manifest's `supports.snapshot` stays `false`, since the file
  itself carries no snapshot).
* A native file this reader cannot run (a newer major version, an unknown
  required chunk or runtime feature, an overlay base) is still described by
  `inspect`, with `runnable=False` and the reason in `notes`; `load` raises
  `UnsupportedFormatError`. A damaged one raises `ModelFormatError` or
  `IntegrityError`.

What it cannot do yet: no overlay in the file (the Persistent Overlay
Infrastructure is a separate store), no snapshot inside the file (conversation
snapshots are separate files, below), no consolidation; graphs are
not loaded lazily (the engine parses the graph source text when the model
opens, as with a `.kgpack`; the tables are not read by the running path); no
routing index. The format is storage and runtime infrastructure: it changes
how a model is stored and opened, not what the engine can answer.

## Format 1.1 table reader (not yet used by the running path)

A base reader for the overlay's merged view (`marco/storage/graph_view.py`
accepts `NativeModel` as its base). **Nothing in the running path calls it in
this version**: `mco.load` still rebuilds the pack, MARCO still parses the
`.kg` text, and the running path builds the overlay view from that text too. It is internal to `mco` (module `mco.native`, not
`mco.__all__`), standard library only, and returns plain data: `dict`,
`list`, `tuple`, `str`, `float`, `int`, `None`.

```python
from mco.native import NativeModel

with NativeModel.open("MARCO-1-native.mco") as model:      # opens; reads no graph table
    model.has_tables                     # False for a 1.0 file
    model.table_index()                  # every graph's INDX row (reads INDX and RULE once)
    g = model.graph("graphs/graph_정산_나눠내기.kg")   # one graph, read_kg's shape
    rows = model.graph_rows("graphs/graph_정산_나눠내기.kg")
    edges = model.node_edges("graphs/graph_정산_나눠내기.kg", "총액")
    model.rules()                        # the model's rules, in MARCO's order
    model.rule_rows()                    # the RULE rows, by rule id
```

| Call | Returns | Reads |
| --- | --- | --- |
| `table_index()` | list of `{"graph_id", "member", "status": "tables" \| "source-only", "reason", "nodes", "edges", "examples"}`, sorted by graph id | `INDX`, `RULE` (once per open file) |
| `graph(graph_id)` | the dictionary `read_kg` returns for the graph's source text: same keys in the same order, same value types (`값옮김`/`값셈` values are tuples, `임계값` floats), dictionaries and lists in source order; without the hypernym merge from `data/개념망.json` (format-1.md 6.12) | that graph's `NODE` and `EDGE` |
| `graph_rows(graph_id)` | `{"graph_id", "member", "nodes": [{"node_id", "name", "layer", "ordinal", "examples", "slots": {slot: {"ordinal", "value"}}}], "edges": [{"edge_id", "src", "rel", "dst", "list": "엣지" \| "개념엣지", "ordinal"}]}`, rows in stored (id) order | that graph's `NODE` and `EDGE` |
| `node_edges(graph_id, name)` | the `edges` rows of `graph_rows` whose `src` or `dst` is `name` (both lists); `[]` for an unknown name. For RETRACT NODE in the overlay store: `[(e["src"], e["rel"], e["dst"]) for e in ...]` are the base edges to name | that graph's `EDGE` only |
| `rules()` | list of rule objects in the order MARCO's `PackModel` collects them; each equal to the source rule as a value (keys come back sorted) | `RULE` |
| `rule_rows()` | list of `{"rule_id", "source", "ordinal", "rule"}`, sorted by rule id | `RULE` |
| `tables_summary()` | the manifest's `tables` counts plus `source_only_reasons`, or `None` | `INDX`, `RULE` |

Errors: `KeyError` for a graph id the file does not have;
`UnsupportedFormatError` for a graph kept as source text only, and for any
table call on a file without tables; `ModelFormatError` or `IntegrityError`
for a damaged table. Graph ids are `graph_id(path)` (format-1.md 6.7), the pack
path for every graph in this repository.

Measured on 2026-10-01, whole source tree (904 graphs), warm file cache, busy
machine, medians: reading all 904 graphs from the tables 30 ms with the string
cache warm and 53 ms from a fresh open, against 56 ms for `read_kg` over the
`.kg` files and 51 ms for reading the `GRPH` chunks and parsing them; one
median graph 0.023 ms from the tables against 0.043 ms for `read_kg`; open
(header, TOC, the four 1.0 tables) 18.9 ms with the tables' strings in `STRS`
against 13.4 ms without. The tables do not make opening faster; they let one
graph be read without the others, keyed by stable ids.

## Conversation snapshots

Additions to API version 1 (in the repository, not in 0.1.0 on PyPI). Design note:
[docs/architecture/snapshot.md](../architecture/snapshot.md).

| Call | Returns | Purpose |
|---|---|---|
| `session.snapshot(path)` | `SnapshotInfo` | Write this conversation (turns and reasoning state) to one file, atomically |
| `model.resume(path, *, conversation=None)` | `Session` | A new session continuing a snapshot's conversation |
| `mco.load(model, snapshot=path)` | `Model` | The default conversation continues the snapshot |
| `mco.inspect_snapshot(path)` | `SnapshotInfo` | Base identity, overlay sequence, schemas, conversation and turn counts; runs nothing |
| `mco snapshot MODEL -o OUT [TEXT ...] [--resume SNAP]` | | CLI: run utterances in one conversation, then write its snapshot |
| `mco run MODEL --resume SNAP [TEXT ...]` | | CLI: continue a snapshot |
| `mco inspect SNAP [--json]` | | CLI: describe a snapshot file |

A snapshot binds to the base it was taken on: `content_sha256` (a native file's
manifest value; for a compat file or bare pack, the SHA-256 of the pack's
`manifest.json`, the same number for the same pack) and the build id when both
sides have one. The same state gives the same bytes. Resuming checks before it
uses anything:

* `SnapshotMismatchError`: another base, or an overlay history that differs from
  the recorded one;
* `SnapshotFormatError`: a damaged or truncated file, or an unknown snapshot
  version, required feature or state schema;
* `SnapshotError` (their base class, a `ValueError`): no such file, or a backend
  that cannot write or resume snapshots.

What a snapshot holds and excludes is listed inside every file
(`SnapshotInfo.excluded`): caches, pending plans, persona and affect state, the
input-understanding history (rebuilt from the turns at resume), the open graph
dialogue of the knowledge-graph route, and learning sidecars. A follow-up to an
unfinished graph dialogue does not carry over a resume; the state dialogue does.
`SnapshotInfo` fields: `path`, `size_bytes`, `sha256`, `version`, `base`,
`overlay` (`None` when no overlay was attached; with `load(..., overlay=)`, the
overlay's `seq` and `change_id`), `runtime`, `requires`, `schemas`, `conversations`, `turns`, `excluded`,
`conversation_ids`.

The backend contract gains two optional methods: `BackendSession.snapshot(path)`
and `BackendModel.resume(path, conversation)`. Their defaults raise
`SnapshotError`, so existing backends keep working unchanged; a backend that
implements them advertises `Capability.SNAPSHOT`.

## Persistent Overlay Infrastructure

Additions to API version 1 (in the repository, not in 0.1.0 on PyPI). Design note:
[docs/architecture/overlay.md](../architecture/overlay.md). An overlay is one file
beside a model file holding graph and rule changes that were stated explicitly or
approved from outside. A model loaded with an overlay reads it at the start of every
turn: a change is used from the next turn on, in the same process, with no recompile
and no export, and the model file is never written. This is storage and runtime
infrastructure, not learning: nothing in `mco` makes, proposes or approves a change by
itself, and every change names its approver.

| Call | Returns | Purpose |
|---|---|---|
| `mco.create_overlay(model, path, *, marco_root=None, verify=True)` | status dict | A new, empty overlay bound to the model's `content_sha256` and build id; refused if `path` exists |
| `mco.open_overlay(model, path, ...)` | `Overlay` | The overlay opened as its one writer (a second writer is refused at once) |
| `mco.overlay_status(model, path, ...)` | status dict | `{"path", "base": {"content_sha256", "build_id", "format_version"}, "head": {"seq", "change_id"}, "counts", "pending"}`; runs nothing |
| `mco.load(model, overlay=path)` | `Model` | Every session reads the overlay at each turn |
| `mco.inspect(model, *, overlay=path, marco_root=None)` | `ModelInfo` | Adds the overlay's binding, head and active counts to `notes` and to `manifest["overlay"]`; runs nothing |
| `Overlay.commit(deltas, *, approved_by, reason, actor=None, source="mco", evidence=None)` | `{"seq", "change_id"}` | One change, all its deltas or none |
| `Overlay.propose(deltas, *, actor, reason, ...)` | candidate id | Stored, changes nothing until approved |
| `Overlay.approve(candidate_id, *, approved_by)` | `{"seq", "change_id"}` | The candidate becomes a change |
| `Overlay.reject(candidate_id, *, rejected_by, reason)` | `None` | Kept with the reason; never applies |
| `Overlay.undo(change, *, approved_by, reason, actor=None)` | `{"seq", "change_id"}` | A compensating change (by seq or change id) |
| `Overlay.head()`, `counts()`, `history(target)`, `candidates(status=None)`, `status()`, `close()` | | Reads |

Deltas are plain dictionaries built by `mco.overlay`: `add_node(graph, name, *,
examples, layer="개념", source=None)`, `add_edge(graph, src, rel, dst, *,
list="엣지")`, `retract_edge(graph, src, rel, dst)`, `retract_node(graph, name)`
(the base's edges of the node are named for you), `add_rule(rule)`,
`replace_rule(rule)`, `disable_rule(rule_id)`; each takes an optional `revision`
(the target's current one when omitted). `mco.overlay.node_id` and `edge_id` give the
stable ids `history` takes. A graph id is the graph's pack path (`graphs/x.kg`).

Every write is checked against the model before it is written; a change the model
cannot take writes nothing. Errors (additions to the hierarchy, under `MCOError`):

* `OverlayBaseMismatchError` (an `OverlayError`): the overlay was made for another
  model (another `content_sha256` or build id), on load, open and resume;
* `OverlayError`: a delta naming a graph the model does not have (whole new graphs
  are not supported), a change to a graph with no exact `.kg` text, a node without
  examples, an edge to an unknown node, a retraction of something the model and the
  overlay never had, a rule change to an unknown rule or with a malformed body, a
  stale revision, a second writer, an approval of a rejected candidate, a missing
  overlay file;
* `BackendUnavailableError`: no MARCO runtime (the store is MARCO's); `import mco`
  alone still imports nothing from MARCO.

Evidence: `Evidence.detail["origin"]` (not stable) of a `graph_path` or `graph_node`
item that came from the overlay is `{"kind": "overlay", "change_id", "seq", "actor",
"source", "approved_by", "approved_at", "candidate_id"}`. Base items carry nothing new.

A conversation snapshot of a session with an overlay records the overlay's head and a
copy of it; `Model.resume` then needs the model loaded with an overlay that holds that
history (else `SnapshotMismatchError`), and re-derives the conversation if the overlay
moved on.

CLI:

```text
mco overlay create MODEL OVERLAY
mco overlay commit MODEL OVERLAY (--delta JSON ... | --deltas FILE) --approved-by WHO --reason WHY [--actor WHO]
mco overlay propose MODEL OVERLAY --delta JSON ... --actor WHO --reason WHY
mco overlay approve MODEL OVERLAY CANDIDATE --approved-by WHO
mco overlay reject MODEL OVERLAY CANDIDATE --rejected-by WHO --reason WHY
mco overlay undo MODEL OVERLAY CHANGE --approved-by WHO --reason WHY
mco overlay status MODEL OVERLAY
mco overlay history MODEL OVERLAY TARGET
mco overlay candidates MODEL OVERLAY [--status pending|approved|rejected]
mco run MODEL --overlay OVERLAY [TEXT ...]
mco inspect MODEL --overlay OVERLAY
```

A delta in JSON is the dictionary a builder returns, for example
`{"op": "ADD_EDGE", "graph": "graphs/x.kg", "src": "a", "rel": "증명", "dst": "b"}`.
`--overlay` (the overlay store) is not `--overlay-dir` (where the runtime keeps its
working files).

## Writing a backend

```python
from mco.backends import Backend, BackendModel, BackendSession, register_backend
import mco

class MySession(BackendSession):
    def run(self, text: str) -> mco.Result: ...
    def reset(self) -> None: ...

class MyModel(BackendModel):
    def __init__(self, info: mco.ModelInfo): self.info = info
    def new_session(self) -> BackendSession: return MySession()
    # reason() has a default: feed text facts, then ask the question.
    # Override it to accept structured facts natively.

@register_backend
class MyBackend(Backend):
    name = "my-runtime"
    formats = ("mco-native",)       # ModelFile.kind values it opens
    priority = 20
    def describe(self, file) -> mco.ModelInfo: ...
    def open(self, file, options) -> BackendModel: return MyModel(self.describe(file))
```

A backend can also be published as a plugin through the `mco.backends` entry
point group:

```toml
[project.entry-points."mco.backends"]
my-runtime = "my_package.backend:MyBackend"
```

How a backend is chosen: `load(..., backend=name)` if given. Otherwise the
backend recorded in the file's manifest, and failing that, the
highest-priority backend that accepts the file's format.
