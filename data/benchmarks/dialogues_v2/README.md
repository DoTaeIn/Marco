# Frozen dialogue set v2 — the fresh exam

Goal X2 (`docs/ko/2026-09-30-fresh-exam-goal.md`). Written 2026-09-30, apart from
every trace of v1: its dialogues, its recorded runs, the experiment log and the
development sets were not read. Only v1's count table
(`python bench/dialogue_gate.py categories`) was, to match the composition.

**Rule: this set is scored once, by the plan manager, at the release.** Nobody
runs the engine on it before that, and nothing is tuned to it after. Adding or
editing a dialogue means `dialogues_v3/`; `FROZEN.sha256` pins this folder and
`tests/test_dialogue_gate_v2.py` fails if it changes.

## Contents

52 dialogues (26 Korean `ko-*.json`, 26 English `en-*.json`), 4 to 10 turns,
340 turns, schema `marco1-dialogue-gate-v1` as `bench/dialogue_gate.py` reads it.
Gate denominator: 108 answerable turns, 98 needed for 90%.

## Turns per label

| label | act | ko | en | all | v1 |
| --- | --- | ---: | ---: | ---: | ---: |
| answerable | answer | 54 | 54 | 108 | 108 |
| hold | record (statement) | 75 | 75 | 150 | 170 with the next row |
| hold | hold (missing premise) | 10 | 10 | 20 | |
| ambiguous | clarify (which person, which place) | 6 | 6 | 12 | 12 |
| unsupported | decline | 3 | 3 | 6 | 6 |
| correction | revise | 9 | 9 | 18 | 18 |
| why | explain | 13 | 13 | 26 | 26 |
| all | | 170 | 170 | 340 | 340 |

## Dialogues and turns per category

| category | ko dialogues | en dialogues | ko turns | en turns |
| --- | ---: | ---: | ---: | ---: |
| ownership | 26 | 26 | 46 | 46 |
| transfer | 26 | 26 | 83 | 83 |
| follow_up | 16 | 16 | 22 | 22 |
| missing_premise | 9 | 9 | 10 | 10 |
| correction | 9 | 9 | 25 | 25 |
| why | 13 | 13 | 13 | 13 |
| ambiguous_referent | 6 | 6 | 12 | 12 |
| restart | 6 | 6 | 6 | 6 |
| cross_language | 3 | 3 | 3 | 3 |

Corrections per language: 3 immediate, 5 after a question, 1 after a why; of
amount (5, one of them of an initial count), of receiver (2) and of direction
(2). Unsupported turns carry no category tag.

## How expectations were made

Each statement declares its events (`has`, `use`, `transfer`); every expected
quantity, state row, evidence turn, `retracted_quantity` and
`reexecuted_quantity` was computed by replaying those events, not typed. Holder
names are the shortest form that tells the holders apart (a surname, a place
without its article), so the scorer's name checks do not depend on a title or
an article. No holder or item name contains a digit.

## Commands

```bash
python bench/dialogue_gate.py validate   --dataset data/benchmarks/dialogues_v2
python bench/dialogue_gate.py categories --dataset data/benchmarks/dialogues_v2
python bench/dialogue_gate.py overlap    --dataset data/benchmarks/dialogues_v2
python bench/dialogue_gate.py hash       --dataset data/benchmarks/dialogues_v2
python -m pytest tests/test_dialogue_gate_v2.py
```

Recorded 2026-09-30: validate 0 problems; overlap 0 of 340 sentences; categories
as the tables above.
