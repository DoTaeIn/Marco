# `mco.backends`

The extension API for runtime authors. Written 2026-09-23 against commit
`78bd062`. Parked with [`mco`](mco.md) by the freeze decision.

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
  | `mco-native` | `NativeMcoBackend` ([native.py](../../mco/backends/native.py)) | recognises native files, reports them not runnable, raises `UnsupportedFormatError` on open |

## Does not own

- The public result, error and model types. They belong to [`mco`](mco.md).
- MARCO itself. `marco.py` imports `kgpack`, `pack_model`, `engine` and
  `views.kgpack_ui` from a MARCO checkout, on first open or compile.

## Depends on

- `mco.errors`, `mco.formats`, `mco.info`, `mco.result` (parent package).
- For `marco-kgpack` only: a MARCO checkout found through the `marco_root`
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
