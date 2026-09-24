# Goal S4: file moves — the root becomes packages, references rewritten, no shims

Model: Opus 5.5, effort high. Read `docs/ko/2026-09-22-freeze-decision.md` first,
then `docs/architecture/structure-audit.md` (A1, A6, A8) and
`docs/architecture/target-map.json`. Written 2026-09-24. Own checkout, branch
`file-moves`. **Runs alone:** it starts only after understanding round 4 (G4) is
merged and before round 5 opens, because it touches every file the rounds own.
The owner starts it.

## The method, decided by the owner 2026-09-24

The audit's phase plan kept a compatibility shim at every old path for a long
migration. There is no long migration: one agent, one window, nothing else
open. So: **no shims.** For each moved file, find every reference to it and
rename that reference in the same commit as the move. Move, rewrite, test,
commit; next batch.

What counts as a reference (the audit measured these, A8 hazards):

- `import x`, `from x import`, `import x as` in product code, `bench/`, `tools/`,
  `tests/`, `views/`, `mco/`, `alma_*`, `conftest.py`;
- `python x.py`, `python -m x` in README, `docs/`, `pyproject.toml`, launch
  files, scripts;
- strings: `mock.patch("x.attr")` and `monkeypatch.setattr("x.attr", …)` in
  tests, the pack string `graph_dialogue:backend` in `styles/한국어.json`, any
  `importlib.import_module("x")`;
- data paths built from `__file__`: 22 root files at 24 sites resolve `graphs/`,
  `styles/`, `data/` relative to their own location. Moved one level down they
  read the wrong directory silently. Each switches to `marco/_paths.py` in the
  same commit.

`pack_model` fingerprints pack content, so rewriting the pack string changes
every pack digest built afterwards; the tests that pin digests are re-recorded
in that commit, with the reason in the message.

## Scope

The whole-file rows of `target-map.json`: every module that is not in its
`splits` list, 53 files by `python tools/doc_facts.py layout` (D2 counted them;
the audit said 51). Three targets are named by two files each (`arithmetic`,
`passages`, `reasoning.state`): merge the pair into one module only if neither
keeps a name the other needs, otherwise give the second file a sibling name and
record it in the map. `response_composer` targets `marco.language.realizer.discourse`,
which already exists: put it beside it as `marco/language/realizer/composer.py`
and record that too. The seven split files stay at the root untouched: `engine.py`,
`relational_semantics.py`, `language_components.py`, `encoder.py`,
`pack_model.py`, `purpose_graph.py`, `goal_runtime.py`. `conftest.py` stays.
`views/kgpack_ui.py` stays where it is. Data directories do not move.

## Also in scope: non-Python files that belong with what moves

`raw_data.txt` and `algorithms/` go with `universal_agent.py` and `codegen.py`
into `experiments/`; `document_vision.swift` goes with `document_visual.py` into
`marco/perception/`; `graphify-out/` (a generated co-occurrence graph that
`explain.py` reads if present, `explain.py:1943`) moves under `data/` with that
path updated; the encoder's `.vec_*.npz` caches at the root move to
`.marco/cache/` with the writer's path updated. Each with its references, as
above. The engine writes its routing tie-break file `그래프쓰임.json` at the repository
root (`engine.py:3241`); any local run then makes
`tests/test_general_knowledge_coverage.py` fail (D2 found this). Move that
file, and `.nai/`, `.nai-tools/` and the `.vec_*.npz` caches, under `.marco/`
(`state/`, `tools/`, `cache/`) with their writers' paths updated, and make the
test suite point the engine at a temporary state directory so a local run can
never change a test result. Cleaned by the owner on 2026-09-24 already: `NAI.kgpack`, the old logs
(`물음기록.jsonl`, `자가학습기록.jsonl`, `그래프쓰임.json`, archived outside the
repository), `HANDOFF.md` (archived), `practice/` (removed), `Addition.md`
(moved to `docs/ko/2026-09-20-addition-next-directions.md`).

## Definition of done — all six, measured

S4.1 **Batches.** At most 10 files per commit. Each commit contains the `git mv`,
     every reference rewrite for those files, and the `_paths` switch for them.
     After each batch: `grep -rn` for each old module name (as an import or a
     string) finds 0 hits outside `.git` and this goal file; the full parallel
     suite reports main's count with the same known failures; the audit's
     import-graph tool shows no new upward edge.

S4.2 **Root count.** `ls *.py` at the root: 61 before, 8 after (the seven split
     files and `conftest.py`); `python tools/doc_facts.py layout` prints 0 files
     left to move. Report the list.

S4.3 **Layer rule.** `marco/` imports nothing from `alma/`, `views/`, `bench/`,
     `tools/`, `experiments/`. 0 violations, or each violation listed with the
     edge and deferred to the split phase with a reason.

S4.4 **Numbers unchanged.** Dev scorers on dev v3 and dev v4 and the composition
     check on the fixed sets: identical numbers before and after, in the report.
     Never run the frozen sets; the owner does that after the merge.

S4.5 **Docs true again.** README Layout section, `docs/architecture/marco.md`, and
     the package docs show the real tree; `target-map.json` rows marked done;
     `structure-audit.md` A8 annotated: phases 2, 4, 5 done for whole files in
     S4, phase 3 splits pending.

S4.6 **No behaviour change.** No logic line edited. Only moves, import lines,
     path helpers, strings, and the docs above. The diff stat shows renames.

Hand-off: the commit hash and a one-line-per-batch table (files, references
rewritten, suite count).

## Owns

Everything the moves touch, since nothing else is open: import lines anywhere,
including `mco/` and `alma_*`. Must not touch: any logic, `data/benchmarks/`,
the gate scorers beyond their import lines, any frozen area beyond import lines.

## Working conditions

Commit by name, owner as author, no co-author lines, no assistant or model name
in commits or files. `python`, not `python3`; `KG_ENCODER=문자` on every run.
Do not push. Report tersely.
