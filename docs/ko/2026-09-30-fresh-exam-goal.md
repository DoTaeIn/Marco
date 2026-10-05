# Goal X2: the fresh exam — frozen dialogue set v2

Model: the owner's chat model, effort high. Written 2026-09-30 by the plan manager on the
owner's go. Own checkout, branch `fresh-exam-v2`.

## Why

The frozen 52 (`data/benchmarks/dialogues_v1/`) were never shown to a development
chat as sentences, but seventeen experiments were steered by their failing
turns: by class, then by the trace of each turn, and once a chat arrived at an
exam sentence word for word. Their score is now a development score. The
release needs a set nothing was steered by.

## What you must never read

`data/benchmarks/dialogues_v1/` and `reasoning_v1/` (any file but
`FROZEN.sha256`); `docs/ko/2026-09-29-experiment-log.md`; `docs/requests/`;
`docs/ko/dialogue-gate-2026-09-22/*.json` (the recorded runs carry exam
sentences); `docs/ko/reverification-2026-09-30/`; the development sets
`data/benchmarks/dialogues_dev*/`; `bench/question_grid.py`;
`tests/test_understanding_r*.py` and `tests/test_r6_*.py`; the understanding
goal files of rounds 1 to 7. You do not run the engine on your dialogues and
you do not look at what it answers: a set written to what MARCO reads is not
an exam.

## What you may read

`docs/ko/2026-09-22-frozen-dialogue-set-goal.md` (how v1 was specified),
`docs/ko/dialogue-gate-2026-09-22/README.md` (the turn schema, labels, scoring),
`bench/dialogue_gate.py` (the validator and the scorer, not the data), the
roadmap's §12 description of stage 1.

## Definition of done

X2.1 `data/benchmarks/dialogues_v2/`: 52 dialogues, 26 Korean and 26 English, 4 to
     10 turns each, the v1 schema exactly, so that
     `python bench/dialogue_gate.py validate --dataset data/benchmarks/dialogues_v2`
     passes (every expected value replays from the declared events; each
     expected value differs from every other holder's value of the same item).
X2.2 The same composition as v1 by the numbers its README gives: about 108
     answerable turns, and statements, missing-premise questions, which-person
     turns, unsupported requests, corrections and whys in the same proportions;
     every one of the seven categories in at least five dialogues per language;
     `python bench/dialogue_gate.py categories --dataset …` recorded.
X2.3 Natural adult language, written as a person types to an assistant: counts
     as words and as digits, titles, relations, places as holders, first person,
     ellipsis, follow-ups, corrections of amount, receiver and direction,
     cross-language questions, restarts. Not templates: no two dialogues share a
     sentence frame. Names, things and places of your own choosing; none need
     be unusual.
X2.4 No full sentence shared with any file of the repository:
     `python bench/dialogue_gate.py overlap --dataset data/benchmarks/dialogues_v2`
     reports 0 (it compares against the repository's text, not against v1's
     data by you).
X2.5 `FROZEN.sha256` for the folder and a test file `tests/test_dialogue_gate_v2.py`
     with the v1 checks that apply (schema and replay, categories, the hash, the
     scorer's self-tests on synthesized perfect and wrong answers). It must not
     run the engine on the set.
X2.6 A short README in the folder: counts per label and category per language,
     the date, the rule that it is scored once, by the plan manager, at the
     release.
X2.7 Hand-off: the commit hash and the counts. You do not score it.

## Working conditions

Commit by name, owner as author, no co-author lines, no assistant or model name
in commits or product files. `python`, not `python3`; `KG_ENCODER=문자`. Do not
push. Report tersely.
