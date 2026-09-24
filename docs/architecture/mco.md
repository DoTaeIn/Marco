# `mco`

The public Python API and CLI over MARCO models. Written 2026-09-23 against
commit `78bd062`. The user guide is [docs/mco/README.md](../mco/README.md) and
the stability contract is [docs/mco/api.md](../mco/api.md).

**Release state.** Version 0.1.0 is on PyPI since 2026-09-24
([release notes](../releases/2026-09-24-mco-0.1.0.md)): `pip install mco`. The
[freeze decision](../ko/2026-09-22-freeze-decision.md) still parks the API: it
is packaged as it is and not extended until MARCO 1 ships. The native `.mco`
binary format is frozen and does not exist; `.mco` files written today are a
compatibility container.

## Purpose

Let callers load, run, inspect, compile and benchmark a MARCO model without
importing MARCO's internal modules, so their code keeps working while the
engine and the file format change.

## Owns

- The public names exported from `mco` (`mco.__all__` in
  [mco/__init__.py](../../mco/__init__.py)): `load`, `compile`, `inspect`,
  `benchmark`, `Model`, `Session`, `Result`, `Status`, `Evidence`,
  `EvidenceList`, `Trace`, `TraceStep`, `Fact`, `ReasoningInput`, `ModelInfo`,
  `Capability`, `CompileReport`, `BenchmarkCase`, `BenchmarkReport`,
  `CaseResult`, `load_cases`, `available_backends`, `register_backend`, and the
  error classes under `MCOError`.
- The compatibility container: a deterministic ZIP holding `mco.json` (the
  manifest) and `payload.kgpack` ([mco/formats.py](../../mco/formats.py)).
- The `mco` console command ([mco/cli.py](../../mco/cli.py)), installed by
  `pyproject.toml` `[project.scripts]`.

## Does not own

- Answering. Every answer comes from the MARCO engine through the backend in
  [`mco.backends`](mco.backends.md).
- The `.kgpack` format (`kgpack.py`) and the pack model (`pack_model.py`).
- The native MCO Format 1 binary, overlays, snapshots, consolidation (frozen).

## Depends on

- The Python standard library only. `pyproject.toml` declares
  `dependencies = []`.
- `mco.backends` for running and compiling. Only `mco/backends/marco.py`
  imports MARCO (`kgpack`, `pack_model`, `engine`, `views.kgpack_ui`), lazily.

## Public interface

| Claim | Test in `tests/test_mco_package.py` |
| --- | --- |
| `import mco` and `mco.inspect()` import no MARCO module | `test_import_and_inspect_do_not_import_marco` |
| No `mco` module except `backends/marco.py` imports a MARCO module | `test_public_modules_never_import_marco_names` |
| `inspect` reports format `mco-compat`, the backend, the graph count, and the note "not MCO Format 1" | `test_inspect_reports_model` |
| `compile` is deterministic, byte for byte, and wraps a bare `.kgpack` | `test_compile_is_deterministic_and_wraps_packs` |
| Missing, truncated, garbage, tampered and future-version files raise `ModelNotFoundError`, `ModelFormatError`, `IntegrityError` | `test_damaged_files_are_rejected` |
| A native `.mco` is recognised by its magic prefix and `load` raises `UnsupportedFormatError` | `test_native_format_is_recognised_but_unsupported` |
| `run` keeps a conversation: "12만원 나왔어" then "3명이야" answers with 40000 and routes to `graph_정산_나눠내기.kg` | `test_multi_turn_run` |
| An out-of-domain question returns status `unknown`, offline | `test_unknown_is_declined_offline` |
| Sessions are isolated; `reset` and `close` work | `test_sessions_and_reset_are_isolated` |
| `reason()` runs in a fresh context: "돌은 23개 있다." + "돌 8개를 꺼냈다." answers "15개입니다." | `test_reason_is_self_contained` |
| Structured facts raise `UnsupportedInputError`; blank or non-text input raises `InvalidInputError` | `test_reason_rejects_unsupported_input` |
| Unknown options, a wrong `marco_root`, an unknown backend and a closed model raise the documented errors | `test_load_options_and_lifecycle` |
| The six statuses map from MARCO's verdicts | `test_translate_verdicts`, `test_translate_plan_payload` |
| The same user code runs on another registered backend | `test_backend_can_be_swapped_without_changing_user_code` |
| `benchmark` scores cases and reports latency; `load_cases` validates | `test_benchmark`, `test_benchmark_reads_repository_case_format` |
| CLI `inspect`, `run`, `compile`, `backends`, `benchmark`; exit codes 0, 1, 2, 3 | `test_cli_inspect_run_compile`, `test_cli_benchmark_and_errors` |
| `python -m mco` runs the CLI | `test_console_entry_point_runs_as_module` |

Two statements in [docs/mco/README.md](../mco/README.md) have no test at this
commit: the four-step order in which the backend looks for a MARCO checkout
(only a wrong explicit `marco_root` is tested), and that backend exceptions are
re-raised with the original chained as `__cause__` (the code does it at
[mco/model.py:53](../../mco/model.py) and [mco/model.py:151](../../mco/model.py);
no test asserts it).
