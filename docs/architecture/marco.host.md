# `marco.host`

Written 2026-10-01 against commit `e3a6394`; checked 2026-10-01 against
`547f85b` (no file named here changed between the two).

## Purpose

Run actions that a graph chose, on the host, and record what happened. Goal S4
([file moves](../ko/2026-09-24-file-moves-goal.md)) moved the root file `act.py`
here whole ([target-map.json](target-map.json): the `modules` row `act` and the
`moved_in_s4` list). The target layout puts the host
permission boundary in this package, layer 7
([structure-audit.md](structure-audit.md) A6); today the package holds only
`act.py`.

The rules [act.py](../../marco/host/act.py) states in its docstring:

1. The plan is not written in code. The nodes a request reaches over `-증명->`
   are the work queue, in the order the `.kg` lists them.
2. An error message is read like an utterance: `engine.match_evidence` finds
   the observation node, and `-증명->` state `-충족->` action is the recovery.
   A new error type is added to the `.kg`, not to the code.
3. Only nodes with a registered tool run. A node without one is not executed
   and is reported in the result (`도구없음`).
4. A run is complete only when every planned node succeeded and one reached
   the goal; otherwise the result says where and why it stopped.
5. The source `.kg` is never edited. Each run appends one JSON line to
   `<graph>.실행.jsonl` beside it (`trace_path`), when `write` is true and the
   graph was read by `act.load`; a failed write is ignored (lines 188–196).

Matching tries string containment first (`engine.match_evidence`) and falls
back to embeddings (`engine.match` over the evidence nodes, accepted at the
graph's `A_MIN` threshold; lines 60–72). The module sets `KG_ENCODER=문자` as
its default before importing `engine` (line 34).

## Owns

| Module | Lines | What |
| --- | --- | --- |
| [act.py](../../marco/host/act.py) | 346 | `load`, `trace_path`, `pick_evidence`, `find_action`, `run` (observe–recover–advance loop, at most `cap=3` tries per action), `report`, `check` (graph and tool table agree, without running; returns 1 on a problem, else 0), `_selfcheck` (seven runs in six numbered groups on `graphs/graph_범용작업.kg` with fake tools; `python marco/host/act.py [graph]`) |

## Does not own

- **Approval and permissions.** The approval step (`approve`,
  `_approve_once`, `_run`) is in the root `goal_runtime.py` (lines 147–214;
  [target-map.json](target-map.json) names 147–210 of the audited commit
  `6195040` for `marco.host.permissions`); that move has not happened, and
  `goal_runtime.py` does not import `act.py`. `act.py` checks no permission:
  it runs whatever tool the caller registered.
- **The tools.** Callers pass a tool table; the only two in the repository are
  in `experiments/autocoder.py` and `experiments/universal_agent.py`.
- **Graph reading and matching.** `engine.load`, `engine.match`,
  `engine.match_evidence`, `engine.reachable`.
- **Collecting web text into a graph.** That direction is
  `marco/knowledge/ingest/web.py`.

## Depends on

- Root module `engine` (imported as `eng` at module load; `load`,
  `match_evidence`, `match`, `reachable`).
- The standard library (`json`, `os`, `pathlib`, `sys`, `time`).
- `act.py` puts the repository root on `sys.path` at import.

## Public interface

| Name | Imported by | Test |
| --- | --- | --- |
| `load(kg_path)` | `experiments/autocoder.py`, `experiments/universal_agent.py` | no test names it |
| `run(g, phrase, tool_table, context=None, cap=3, write=True)` | same | no test names it |
| `report(result, g=None)` | same | no test names it |
| `check(kg_path, tool_table, show=True)` | same | no test names it |
| `trace_path(g)` | same | no test names it |

No file in `tests/` imports `marco.host`. The only check is the module's own
`_selfcheck`, run by hand. Run twice on 2026-10-01 at `547f85b`
(`python marco/host/act.py`), it printed `act 자체검사: 2건 실패` both times:
in group 3, the unknown `PermissionError` is matched to `관찰_데이터오류` by
embedding (score 0.222), so the run recovers and reports itself complete.
