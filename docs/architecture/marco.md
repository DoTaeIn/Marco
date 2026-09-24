# `marco`

The MARCO core package. Written 2026-09-23 against commit `78bd062`; the
`marco.trace` rows added 2026-09-24 against `5f321a3` (goal D2).

## Purpose

Give the MARCO modules one importable home. Today it holds two subpackages:
the language seam with Hermeneia, the language realizer (`marco.language`), and
Hypomnema, the provenance ledger (`marco.trace`). Every other part of MARCO
still lives in the root modules (`engine.py`, `reasoning_context.py`, ...).
Goal S4 (`docs/ko/2026-09-24-file-moves-goal.md`) moves the whole-file root
modules into this package between understanding rounds 4 and 5, on the owner's
go; `python tools/doc_facts.py layout` prints which files move where. The
splits of the seven large root files stay frozen until MARCO 1 ships
([freeze decision](../ko/2026-09-22-freeze-decision.md)).

## Owns

- The `marco` namespace and its version string, `marco.__version__ = "0.0.0"`
  ([marco/__init__.py](../../marco/__init__.py)).
- The subpackage [`marco.language`](marco.language.md).
- The subpackage [`marco.trace`](marco.trace.md).

## Does not own

- Any root module. Routing, judging, sessions, the `.kg` reader and the dialogue
  state machine stay at the repository root until the frozen refactor runs.
- The planned subpackages `marco/runtime/`, `marco/reasoning/`,
  `marco/knowledge/`, `marco/memory/`, `marco/learning/`, `marco/cognition/`,
  `marco/perception/`, `marco/storage/`, `marco/host/`. None of them exists
  before S4 runs.
- ALMA, POLO and the public `mco` API. They sit beside `marco`, not inside it.

## Depends on

- Nothing outside the Python standard library. `marco/__init__.py` has no imports.

## Public interface

| Name | Kind | Proof |
| --- | --- | --- |
| `marco.__version__` | `str`, `"0.0.0"` | read in [marco/__init__.py](../../marco/__init__.py); no test asserts the value |
| `marco.language` | subpackage | `tests/test_language_seam.py::test_realize_is_exported_with_the_declared_signature` |
| `marco.trace` | subpackage | `tests/trace/` (four files), per name in [marco.trace.md](marco.trace.md) |

A runtime copied out of the source tree must include this package, because
`reasoning_context.py` imports `marco.language`. Two tests build such a copy and
run a pack in it: `tests/test_pack_model.py` (the isolated-runtime tests that
copy `marco/` at lines 490 and 543).
