# Goal: structure audit — decide the layout before anything moves

Written 2026-09-22. This is Phase 0 of the repository refactor
(`docs/ko/2026-09-22-plans-organized.md` §4). It is the only refactor work
allowed while the ALMA goal and the repair + English goal are running.

## Core rule

**Read code, write documents. Move nothing.** This goal produces a decision
record and measurement scripts. It does not rename, move, delete, or edit any
existing `.py` file. If a step needs an edit to an existing file, the step is
out of scope and gets written down as a Phase 1 task instead.

## Why now

- Two sessions edit `engine.py`, `explain.py`, `language_components.py`,
  `pack_model.py`, `relational_semantics.py`, `alma/runtime.py`,
  `marco/learning/concepts.py`, `marco/learning/chunking.py`, `marco/reasoning/context.py`.
  Moving those now causes silent merge loss.
- The realization goal (next) must build straight into `marco/language/`.
  That folder does not exist and its contents are undecided. This goal decides it.
- 61 root-level `.py` files. Nobody can say from the names which subsystem each
  belongs to. §4.19 of the plan file is a guess, not an audit.

## Definition of done — all nine, measured

A0. **Baseline recorded** in `docs/architecture/structure-audit.md`:
    root-level `.py` count, lines per root file, full test suite pass / fail /
    skip count at the audited commit hash on this clone.

A1. **Every root `.py` file classified.** One table row per file: file, lines,
    what it actually does (from reading it, not its name), target package,
    confidence (sure / unsure), and the reason when unsure. Row count equals the
    root `.py` count from A0. Zero rows say "TBD".

A2. **Import graph measured by a script**, not by hand. `tools/import_graph.py`
    prints, for root files and packages: edges, in-degree, out-degree, and the
    number of import cycles. The numbers go in the audit document. The script
    is new; it changes nothing.

A3. **`engine.py` responsibilities listed with line ranges.** Each responsibility
    named, its line span, its callers from A2, and the package it moves to.
    The sum of spans covers the file. No edits.

A4. **The four `nai` artifacts get names and homes.** Today the project name
    is used for four unrelated things:
    - `marco/runtime/conversation.py` — CLI entry point, tracked
    - `NAI.kgpack` — built model file, ignored
    - `.nai/` — runtime conversation store written by `conversation_store.py`, ignored
    - `.nai-tools/` — downloaded vision binary and YOLO config, ignored
    Decide one target path for each and say which code paths read them
    (`views/kgpack_ui.py:249`, `marco/perception/visual.py:27`). Do not move them.

A5. **`mco/` placed.** The public API package on branch `mco-package` gets a
    row in the target layout: does it stay a top-level package, and which
    internal modules is it allowed to import (dependency rule §4.6).

A6. **Target layout written** as a directory tree with one line per package
    saying what goes in and what is forbidden. `marco/language/` is defined
    down to file names so the realization goal can create files there on day one.

A7. **Do-not-touch list** for Phase 1: every file the two running goals edit,
    with the goal that owns it. Phase 1 may not start until every file on the
    list is merged to `main`.

A8. **Phase plan with gates.** Phases 1–5 from §4.9, each with: files moved,
    the compatibility shim added, the test command, and the pass count that
    must match A0. A phase without a numeric gate is not a phase.

## Invariants — breaking one fails the goal

- `git diff --stat main -- '*.py'` shows only files under `tools/` that did
  not exist before. Any other `.py` change fails the goal.
- No file renamed, moved, or deleted.
- The full suite is not required to run more than once (A0). If it runs
  again, the count must match A0.

## Build order

1. Record A0. Commit.
2. Write `tools/import_graph.py`. Run it. Record A2. Commit.
3. Read every root file. Fill A1, one commit per 15 files.
4. Read `engine.py`. Fill A3.
5. A4, A5, A6 in one sitting; they depend on A1–A3.
6. A7, A8 last.

## Not in this goal

- Moving or renaming any file. That is Phase 1, after goals 1 and 2 merge.
- Fixing anything found while reading. Write it in the audit under
  "found, not fixed".
- Documentation architecture (§4.10–4.13). Later.

## Working conditions

- Branch `structure-audit` from `main`. Docs and `tools/` only.
- Clone: this one (`/Users/dotaein/Downloads/NAI`). Run `git worktree prune`
  before any `git worktree add`.
- Run Python as `python`, not `python3`.

## Reporting style

Numbers and file:line. Each of A0–A8 reported as done or not, with the
measurement. No prose summaries.
