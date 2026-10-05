# Goal F2: the frozen reasoning set and the composition gate

Model: the owner's chat model, effort high. Read `docs/ko/2026-09-22-freeze-decision.md` first.
Written 2026-09-24. Starts now, in parallel with G2 (understanding round 2).
Data, scorers, tests, and one report. **No engine edits, no realizer edits, no
pack edits.**

## Why

The owner named two things MARCO 1 must be, and the current gate measures neither
directly:

1. **It creates its sentences; it never picks from a list.** The realizer exists
   (`marco/language/`) and reports per reply whether it composed the sentence
   (`marco.language.realizer.last_report()["realized"]`). Nobody counts that on
   the frozen dialogues yet. Engine answers routed from graphs pass through uncomposed.
2. **It reasons.** Arithmetic over state, chains of transfers, comparisons,
   negation, order in time, missing premises, corrections, restarts. Individual
   tests exist; there is no scored set, and the dialogue gate mixes reasoning
   failures with understanding failures (87 of 108 turns hold before reasoning starts).

This goal builds the two measurements. The freeze decision now lists them as gate
conditions 5 and 6.

## Exam rule

Never open `data/benchmarks/dialogues_v1/` and never run any scorer against it;
the owner does. You may run against the fixed 7-step benches, the 20 phrasings in
`docs/ko/repair-and-english-2026-09-22/unseen-before.json`, and your own set.

## Definition of done — all seven, measured

F2.1 **Reasoning set** `data/benchmarks/reasoning_v1/`: at least 100 problems, at
     least 40 per language. One JSON per problem: setup statements, one or more
     questions, expected answer as a semantic structure (never a surface string),
     the reasoning kind, and the derivation the answer needs (which facts, which
     rule). Kinds, each with at least 8 problems: count arithmetic; transfer
     chains of 3 or more events; comparison (more, fewer, equal); totals over two
     or more holders; negation; order in time (before, after, then); missing
     premise (the right answer is a hold that names what is missing);
     correction then re-derivation; restart (snapshot, restore, ask); and one
     kind of your choice the engine supports (check the tests named below).
     **Phrasing rule:** every sentence uses only surface forms the packs declare
     (`styles/*.json` examples and their declared variants), so that a failure is
     a reasoning failure, not a parsing one. Zero full-sentence overlap with
     `data/benchmarks/dialogues_v1/`, `dialogues_dev/`, `dialogues_dev2/` (reuse
     the overlap script from `bench/dialogue_gate.py`; the frozen directory is
     read only by that script, never printed).

F2.2 **Reasoning scorer** `bench/reasoning_gate.py`: runs each problem through the
     same entry the UI uses (`views.kgpack_ui.AppState.turn`, see how
     `bench/dialogue_gate.py` does it), compares semantic structures, and
     classifies every question as correct, wrong, hold, execution error, or
     **unparsed** (a setup statement was not recorded, so reasoning never
     started). Unparsed questions leave the reasoning denominator and are
     reported separately with the statement that failed. Prints totals per kind
     and per language with the denominator stated. `--dataset` flag as in the
     dialogue gate.

F2.3 **Error injection** in `tests/test_reasoning_gate.py`: a deliberately wrong
     expected-answers file scores 0 correct; swapping two expected values changes
     exactly those problems; a setup statement replaced by an undeclared phrasing
     lands in unparsed, not in wrong.

F2.4 **Baseline recorded** at the `main` commit you start from, in
     `docs/ko/reasoning-gate-2026-09-24/baseline.json`: commit hash, per-kind and
     per-language table, the unparsed list. Then **freeze**: SHA-256 of the
     directory in `data/benchmarks/reasoning_v1/FROZEN.sha256`, and a test that
     fails if the directory hash changes.

F2.5 **Composition gate** `bench/composition_gate.py`: for any dialogue directory
     in the dialogue-gate format, runs the turns and, after each reply, reads the
     realizer report; counts replies as composed, passed through, or held, per
     act (`answer`, `hold`, `record`, `explain`, `ask`, `correct`) and per
     language; prints `composed N / M spoken replies` with the denominator. A
     reply that quotes a graph node's own text counts as composed only if the
     sentence around the quotation was composed. Do not edit
     `bench/dialogue_gate.py`; import from it.

F2.6 **Composition gate validated** on the fixed 7-step dialogues and the 20
     phrasings: numbers recorded in the report; `tests/test_composition_gate.py`
     proves a monkeypatched realizer that passes everything through scores 0
     composed.

F2.7 **Report** `docs/ko/reasoning-gate-2026-09-24/README.md`: what the set
     covers, the baseline tables, the composition numbers on the fixed sets, how
     the owner runs both gates on the frozen dialogues, and every problem kind
     the engine could not express (listed, not silently dropped). Full parallel
     suite unchanged from `main` at your start, counts recorded.

## Owns

`data/benchmarks/reasoning_v1/`, `bench/reasoning_gate.py`,
`bench/composition_gate.py`, `tests/test_reasoning_gate.py`,
`tests/test_composition_gate.py`, `docs/ko/reasoning-gate-2026-09-24/`.

Must not touch: every `.py` at the repository root, `marco/`, `styles/`,
`bench/dialogue_gate.py`, any other test, any frozen area. If a measurement
needs an engine change, write `docs/requests/F2-<n>.md` and record the gap in
the report.

Useful reading: `tests/test_signed_inference.py`, `tests/test_temporal_relations.py`,
`tests/test_quantity_relations.py`, `tests/test_relational_transfer.py`,
`tests/test_concept_relation_reasoning.py`, `tests/test_indexed_inference.py`,
`bench/seven_step_dialogue.py`, `marco/language/W1-report.md`.

## Working conditions

Own checkout, branch `reasoning-gate`. Commit by name, owner as author, no
co-author lines, no assistant name anywhere. `python`, not `python3`. Do not push.
Report tersely: F2.1–F2.7 each done or not with numbers, then the baseline table.
