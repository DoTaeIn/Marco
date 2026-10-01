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

## `.mco` native file (MCO Format 1.0)

Not in 0.1.0 on PyPI; in the repository since 2026-10-01. The byte layout,
tables, identifiers and every accept/refuse verdict are specified in
[format-1.md](format-1.md). In short: a 96-byte header, chunks, a table of
contents with a SHA-256 per chunk, a canonical JSON manifest, and three real
tables (strings, members, graph directory). Graphs, language packs and axioms
are **carried members** in this version: typed chunks holding the pack files
unchanged, to be replaced by node, edge and rule tables in the next slice.

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
  required, compression, offset, stored and raw size, SHA-256) and `members`.
  `notes` say that overlay and snapshot are not supported in this version.
* A native file this reader cannot run (a newer major version, an unknown
  required chunk or runtime feature, an overlay base) is still described by
  `inspect`, with `runnable=False` and the reason in `notes`; `load` raises
  `UnsupportedFormatError`. A damaged one raises `ModelFormatError` or
  `IntegrityError`.

What it cannot do yet: no overlay (the Persistent Overlay Infrastructure is a
later slice), no snapshot, no consolidation; graphs are not loaded lazily (the
engine parses the carried graph text when the model opens, as with a
`.kgpack`); no node, edge, rule or index tables; partial loading is not
measured. The format is storage and runtime infrastructure: it changes how a
model is stored and opened, not what the engine can answer.

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
