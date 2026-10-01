# `mco.backends`

The extension API for runtime authors. Written 2026-09-23 against commit
`78bd062`; the `mco-native` rows updated 2026-10-01 for MCO Format 1.0
([format-1.md](../mco/format-1.md)).

## Purpose

Decide which runtime opens a model file, and keep every MARCO-specific name in
one module, so that a new runtime (such as a native `.mco` runtime) can be added
without changing user code.

## Owns

- The registry: `register_backend`, `get_backend`, `available_backends`,
  `select_backend` ([mco/backends/__init__.py](../../mco/backends/__init__.py)),
  including the `mco.backends` entry-point group for third-party backends.
- The abstract classes `Backend`, `BackendModel`, `BackendSession`
  ([mco/backends/base.py](../../mco/backends/base.py)).
- Two built-in backends:

  | Name | Class | State |
  | --- | --- | --- |
  | `marco-kgpack` | `MarcoKgpackBackend` ([marco.py](../../mco/backends/marco.py)) | runs `.kgpack` payloads on the MARCO engine; network research off unless `allow_network=True` |
  | `mco-native` | `NativeMcoBackend` ([native.py](../../mco/backends/native.py)) | runs MCO Format 1 files: reads them with `mco.native`, rebuilds the MARCO pack from the file's chunks into the model's working directory, and runs it with the same `MarcoModel`/`MarcoSession` as `marco-kgpack`. A recognised file it cannot run (newer major version, unknown required chunk or feature) is described with `runnable=False` and refused on open with `UnsupportedFormatError` |

  What `mco-native` cannot do yet: graphs, language packs and axioms are
  carried pack members, not tables, so MARCO parses the graph text when the
  model opens and nothing is loaded lazily; no overlay (the later Persistent
  Overlay Infrastructure), no snapshot, no consolidation; partial loading is
  not measured. It is storage and runtime infrastructure only.

## Does not own

- The public result, error and model types. They belong to [`mco`](mco.md).
- MARCO itself. `marco.py` imports `kgpack`, `pack_model`, `engine` and
  `views.kgpack_ui` from a MARCO checkout, on first open or compile.
  `native.py` imports nothing from MARCO directly; it uses `marco.py`.
- The Format 1 byte layout: [`mco.native`](../../mco/native/) (standard library
  only), specified in [format-1.md](../mco/format-1.md).

## Depends on

- `mco.errors`, `mco.formats`, `mco.info`, `mco.result` (parent package).
- For `marco-kgpack` and `mco-native`: a MARCO checkout found through the `marco_root`
  option, the `MCO_MARCO_ROOT` environment variable, `sys.path`, or the
  checkout `mco` was installed from. The backend needs `numpy` and `pillow`,
  which `pip install "mco[marco]"` adds.

## Public interface

| Name | Purpose | Test in `tests/test_mco_package.py` |
| --- | --- | --- |
| `register_backend(cls, *, replace=False)` | add a backend; rejects a duplicate name | `test_backend_can_be_swapped_without_changing_user_code` |
| `available_backends()` | `{name: (usable, reason)}` | `test_backend_can_be_swapped_without_changing_user_code`; CLI `backends` in `test_cli_inspect_run_compile` |
| `select_backend(file, name=None)` | explicit name, then the manifest's backend, then highest priority | exercised by every `mco.load` test; an unknown name raises `BackendUnavailableError` in `test_load_options_and_lifecycle` |
| `Backend.availability/accepts/describe/open/compile/accepts_source` | what a runtime implements | the test's `_EchoBackend` overrides `describe` and `open` and runs through `mco.load` |
| `BackendModel.new_session/reason/close`, `BackendSession.run/reset/close` | per-model and per-conversation objects | `test_sessions_and_reset_are_isolated`, `test_reason_is_self_contained` |

Tests of `mco-native`, in `tests/test_mco_native_format.py`:

| Claim | Test |
| --- | --- |
| A Korean and an English conversation give the same answer, status and evidence from the compat and the native file | `test_native_answers_as_compat_does_in_korean`, `test_native_answers_as_compat_does_in_english` |
| The answer comes from the file: a graph that exists only inside the `.mco` answers in a separate process after its source tree is deleted | `test_native_knowledge_comes_from_the_file` |
| Unknown options, a damaged member, a newer major version, and forcing `marco-kgpack` on a native file are refused | `test_native_load_options_and_refusals` |
| `inspect` shows version, manifest and chunks, and imports no MARCO module | `test_inspect_native_shows_version_manifest_and_chunks`, `test_inspect_native_runs_nothing`, `test_cli_inspect_native` |
