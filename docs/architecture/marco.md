# `marco`

The MARCO core package. Written 2026-09-23 against commit `78bd062`; the
`marco.trace` rows added 2026-09-24 against `5f321a3` (goal D2).

## Purpose

Give the MARCO modules one importable home. It holds the language seam with
Hermeneia, the language realizer (`marco.language`), Hypomnema, the provenance
ledger (`marco.trace`), and, since goal S4
(`docs/ko/2026-09-24-file-moves-goal.md`), the whole-file modules that stood at
the root: `marco.reasoning`, `marco.runtime`, `marco.storage`,
`marco.knowledge`, `marco.learning`, `marco.perception`, `marco.host`.
`python tools/doc_facts.py layout` prints which file went where. Seven large
files stay at the root (`engine.py`, `relational_semantics.py`, ...); their
splits stay frozen until MARCO 1 ships
([freeze decision](../ko/2026-09-22-freeze-decision.md)).

## Owns

- The `marco` namespace and its version string, `marco.__version__ = "0.0.0"`
  ([marco/__init__.py](../../marco/__init__.py)).
- The subpackage [`marco.language`](marco.language.md).
- The subpackage [`marco.trace`](marco.trace.md).

## Does not own

- The seven split files at the root. Routing, judging and the `.kg` reader stay
  at the repository root until the frozen refactor runs.
- The planned subpackages `marco/memory/` and `marco/cognition/`. They come with
  the splits; S4 made only the packages a moved file needed.
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
`marco/reasoning/context.py` imports `marco.language`. Two tests build such a copy and
run a pack in it: `tests/test_pack_model.py` (the isolated-runtime tests that
copy `marco/` at lines 490 and 543).
