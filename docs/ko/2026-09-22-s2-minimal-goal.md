# Goal S2-min: package skeleton and the language seam — nothing more

Model: the owner's chat model, effort high. Read `docs/ko/2026-09-22-freeze-decision.md` first.
Starts after S1 reports A6 (target layout) and after P0 (branches merged).

## Core rule

Create the smallest structure the realizer needs. Do not split `engine.py`.
Do not move ALMA, storage, or reasoning files. The full refactor is frozen.

## Definition of done

M1. Packages exist with `__init__.py`: `marco/`, `marco/language/`. Others from
    the S1 layout only if they are empty placeholders with one README line.
M2. `marco/language/__init__.py` exports `realize(meaning, intent, language) -> str`
    as a stub that returns exactly what the current dialogue path returns today.
    One test proves byte-identical output over the 20 phrasings in
    `docs/ko/repair-and-english-2026-09-22/unseen-before.json`.
M3. The dialogue path calls `realize()` at exactly one point, named as file:line
    in the report. That is the only edit to an existing `.py` file.
M4. `conftest.py` keeps every flat `import engine`-style call working. Full
    suite pass count equals the count recorded in S3, or the pre-S3 baseline if
    S3 has not run.
M5. Root-level `.py` count is unchanged. Zero files moved.

## Not in this goal

Anything from plan file §4 phases 1–5. Any second seam. Any behaviour change.

## Working conditions

Own hidden checkout, branch `s2-minimal`. Commit by name, owner as author, no
co-author lines. Do not push.
