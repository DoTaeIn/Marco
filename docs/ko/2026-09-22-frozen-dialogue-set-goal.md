# Goal F1: the frozen dialogue set — 50 unseen dialogues and a scorer

Model: the owner's chat model, effort high. Read `docs/ko/2026-09-22-freeze-decision.md` first.
Written 2026-09-22. Starts now. Data and scorer only; **no engine edits**.

## Core rule

These dialogues are the exam. They are written before the realizer exists and
never used to tune it. This goal does not fix anything the exam finds. It records.

## Owns

`data/benchmarks/dialogues_v1/`, `bench/dialogue_gate.py`,
`tests/test_dialogue_gate.py`, `docs/ko/dialogue-gate-2026-09-22/`.
Nothing else. Any other file change fails the goal.

## Definition of done — all seven, measured

F1.1 **At least 50 dialogues**, at least 20 in Korean and 20 in English, each
     4 to 10 turns, in one JSON file per dialogue with: language, domain, turns,
     and per turn the expected answer as a **semantic structure** (entity,
     quantity, relation, evidence expected), never a surface string, plus a
     label from {answerable, hold, unsupported, ambiguous, correction, why}.

F1.2 **Every one of the 7 categories** of roadmap §12 (ownership, transfer,
     follow-up, missing premise, correction without re-execution, why, ambiguous
     referent, restart) appears in at least 5 dialogues. Word order, register,
     initial values, roles, sentence splitting, and correction position vary. A
     script counts this and prints the table.

F1.3 **Unseen means unseen.** No dialogue shares a full sentence with any file
     under `tests/`, `bench/`, `cases/`, `data/`, or `styles/` at HEAD. A script
     checks this and prints 0 overlaps.

F1.4 **Scorer** `bench/dialogue_gate.py` runs every dialogue through the
     dialogue path (the same entry the UI uses, not an internal function),
     compares semantic structures, and prints: answerable N, correct, hold,
     wrong, execution error, unverifiable, per language and per category, with
     the exact 90% denominator stated.

F1.5 **Error injection.** A deliberately wrong answers file scores 0 correct.
     Swapping two expected quantities in one dialogue changes the score by
     exactly that dialogue. Both are tests in `tests/test_dialogue_gate.py`.

F1.6 **Baseline recorded once** at the first `main` that contains commit
     `f985857` (English default), in `docs/ko/dialogue-gate-2026-09-22/baseline.json`
     with the commit hash and the full failure list. This is the "before" number.

F1.7 **Frozen.** A SHA-256 of the dialogue directory is written to
     `data/benchmarks/dialogues_v1/FROZEN.sha256`, and a test fails if the
     directory hash changes. Adding dialogues later means a `dialogues_v2/`.

## Not in this goal

Fixing the engine. Editing tests outside `tests/test_dialogue_gate.py`.
Touching any frozen area. Using the dialogues to write phrasings into `styles/`.

## Working conditions

Own hidden checkout, branch `frozen-dialogue-set`. Commit only owned paths, by
name. Author is the repository owner, no co-author lines, no assistant name.
Run `python -m pytest tests/test_dialogue_gate.py` only. Do not push.

## Reporting

F1.1–F1.7 each as done or not, with the number. Then the baseline table.
