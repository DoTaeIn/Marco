# `alma`

Written 2026-10-01 against commit `c8ad9a5`; checked again at `2864b34`, where `alma/`, its
tests and the `bench/alma_*` scripts are unchanged.

## Purpose

ALMA 0.1: a small, resumable, one-agent research loop on MARCO's event and proof core
([alma-research-loop.md](../en/alma-research-loop.md), design record
[alma-0.1.md](../ko/alma-0.1.md)). It keeps one agent's personal state in one JSON file,
apart from portable `.kgpack` knowledge; event replay, proofs and action programs stay
with `ReasoningContext` (module docstring of `runtime.py`). ALMA is not in MARCO 1
(title of alma-research-loop.md). ALMA advancement is frozen: no persona or social
features (A1, A2), no new ALMA modules and no ALMA goal after goal 1; existing ALMA tests
keep passing ([freeze decision](../ko/2026-09-22-freeze-decision.md), line 14). Goal S4
moved the three files here from the root (`alma_runtime`, `alma_environment`, `alma_cli`;
`moved_in_s4` in [target-map.json](target-map.json)).

## Owns

| Module | Lines | What |
| --- | --- | --- |
| [`__init__.py`](../../alma/__init__.py) | 0 | empty; exports nothing |
| [`runtime.py`](../../alma/runtime.py) | 2077 | `AlmaRuntime(state_path, identity="alma", *, model=None)`. `turn(text, graph_path)` first answers a typed-memory question (`과거 경험:`, `일반적으로 아는 것:`, `하는 방법:` and suffix forms), a holder-scoped mental question, a mental statement (`…라고 믿어`, `…라고 기대해`, `…의 목표는 …야`) or a `정정: … => …` mental correction from ALMA's own state; any other text goes to `ReasoningContext.turn`, and ALMA records the resulting events, revisions and proofs. State schema `alma-runtime-v1`, written through a `.tmp` file and `os.replace`; on load the newer valid one of the two wins. State: logs (`SYSTEM`, `COGNITION`, `LIFE`), episodic, semantic and procedural memory, mental states (kind `belief`, `expectation` or `goal`; modality `belief`, `planned`, `conditional` or `hypothetical`), goals, affect, preferences, capabilities with a request journal, cycles, autonomous runs, action candidates, milestones, decisions (`decision`, `reconsider`), timed state projection (`project_state_at`) and ledger search (`search`). A working memory of at most 16 log rows is kept in the process, not in the file. Rule changes: propose, benchmark, approve, roll back. Graph-asset changes: propose, approve, roll back, export into a new pack. Proof shortcuts: propose, activate after two observations, run, invalidate; a closure-snapshot shortcut is also recorded and activated by `turn` after two observations. `local_file_read_adapter(root, *, max_bytes=65536)`: a read-only adapter confined to one directory |
| [`environment.py`](../../alma/environment.py) | 177 | `run_local_environment(runtime, graph_path, config, *, step_budget=16, run_id=None)`: advances a persisted run by at most `step_budget` decisions through three phases (initial observation, seek information, observe result), ending `completed`, `safe_hold` or `paused_budget`; its docstring says the runtime receives only the public observation payload through read adapters, never the backing mapping or an evaluation answer |
| [`cli.py`](../../alma/cli.py) | 129 | `python -m alma.cli --state … [--identity …] [--graph …]` with one command of `--turn`, `--memory`, `--recall` (with `--recall-key`), `--mental-holder` with `--mental-kind` (and `--mental-condition-event`), `--project-state-at`, `--search` (with `--search-kinds`), `--decision`, `--reconsider`, `--backup-state`, `--cycle-steps`, `--resume-cycle`, `--environment` (with `--resume-environment`); `--step-budget`, `--pack` (with `--pack-graph`). With no command it prints the state snapshot |

Not in the package: five scripts under `bench/` import it (`alma_environment_reproduction.py`,
`alma_graph_asset_reproduction.py`, `alma_integrated_reproduction.py`,
`alma_regression_reproduction.py`, `alma_unified_reproduction.py`).

## Does not own

- Event parsing, correction replay and proofs: `marco.reasoning.context.ReasoningContext`
  and `marco.reasoning.inference` (`closure`, used by `benchmark_rule_change`).
- Proof shortcuts and rule induction themselves: [`marco.learning`](marco.learning.md)
  (`chunking.py`, `rules.py`); ALMA keeps the proposal, approval and activation records.
- Pack format: `marco.storage.kgpack`; graph loading and lint: `engine.py` (`engine.load`,
  `engine.lint` in `propose_graph_asset_change`).
- MARCO. Rule S4.3 of [goal S4](../ko/2026-09-24-file-moves-goal.md) says `marco/` imports
  nothing from `alma/`; `alma` is on layer 10 of [target-map.json](target-map.json), above
  every `marco` layer (0 to 9).

## Depends on

- `runtime.py`: `marco.reasoning.context`, `marco.reasoning.inference`, `marco.learning.chunking`
  at import; lazily `marco.learning.rules`, `engine` (root), `marco.storage.kgpack`.
- `environment.py`: the Python standard library only.
- `cli.py`: `alma.runtime`, `alma.environment`; lazily `marco.storage.kgpack`, `pack_model` (root).
  It puts the repository root on `sys.path` so `python alma/cli.py` runs.
- No third-party library is imported directly.

## Public interface

| Name | Imported by | Test |
| --- | --- | --- |
| `runtime.AlmaRuntime` | `alma/cli.py`, the five `bench/` scripts above, `docs/ko/review-2026-09-20/review_probes.py` | `tests/test_alma_runtime.py` (53 tests), `tests/test_alma_environment.py`, `tests/test_alma_cli.py`, `tests/test_proof_chunking.py::test_validated_shortcut_is_available_to_the_parser_common_rule_selector`; through the `bench/` scripts, `tests/test_alma_{environment,graph_asset,integrated,integrated_late_error,regression,unified}_reproduction.py` |
| `runtime.local_file_read_adapter` | tests only | `tests/test_alma_runtime.py::test_goal_affect_preference_and_capability_are_causal_and_resumable` |
| `runtime.LANGUAGE` (`"한국어"`) | `alma/cli.py` | no test names it |
| `environment.run_local_environment` | `alma/cli.py`, `bench/alma_environment_reproduction.py`, `bench/alma_unified_reproduction.py` | `tests/test_alma_environment.py` (three tests) |
| `python -m alma.cli` / `python alma/cli.py` | command line; `bench/alma_unified_reproduction.py` runs `alma/cli.py` as a subprocess | `tests/test_alma_cli.py` (six tests, listed in [alma-research-loop.md](../en/alma-research-loop.md)) |
| fixed reproduction | `bench/alma_integrated_reproduction.py` | `tests/test_alma_integrated_reproduction.py` (two tests; [structure-audit.md](structure-audit.md) line 64 records its RSS assertion as machine-dependent: macOS reports RSS) |
