# Goal G1: understanding, round 1 — turn holds into answers

Model: Opus 5, effort high. Read `docs/ko/2026-09-22-freeze-decision.md` first.
Written 2026-09-23. Starts after `frozen-dialogue-set` and `s2-minimal` are on `main`.
Check `git log --oneline -5` shows both merges; if not, stop and tell the owner.

## The fact this goal answers

The frozen gate baseline (`docs/ko/dialogue-gate-2026-09-22/baseline.json`, at
`main` 4adc504): **3 correct of 108 answerable turns, 2.8%**. Korean 0 of 54,
English 3 of 54. 105 holds, 0 wrong. The engine does not understand unseen
phrasings; it holds. Sentence creation is not the bottleneck yet. This round
attacks the holds.

## Exam rule — breaking it fails the goal

- Never open `data/benchmarks/dialogues_v1/`. Never run `bench/dialogue_gate.py`
  against it. The frozen set is run once per round by the owner, not by this chat.
- From `baseline.json` read only the top-level `gate`, `by_language`, and
  `by_category` blocks. Do not read `failures` or per-dialogue entries.
- Build your own development set instead (G1.1). Fix causes, not sentences.

## Definition of done — all six, measured

G1.1 **Development set** `data/benchmarks/dialogues_dev/`: at least 30 dialogues,
     at least 15 per language, same JSON schema as v1 (read the schema from
     `bench/dialogue_gate.py`, not from v1 files), varied in word order, register,
     initial values, roles, sentence splitting, correction position. Zero full
     sentences shared with v1 or with any file under `tests/`, `bench/`,
     `cases/`, `styles/` (reuse the overlap script from F1.3; extend it to take
     a directory). Add a `--dataset <dir>` flag to `bench/dialogue_gate.py` so it
     scores this set; that flag is the only change to the scorer.

G1.2 **Cause table at start.** Run the dev set. Every hold gets one cause from a
     fixed list you define (for example: particle on counter, unknown verb form,
     numeral not parsed, referent not resolved, English event not read, unknown
     frame). Counts sum to the hold count. Table in the report.

G1.3 **Fix the causes, largest first.** Each fix is a rule or a declaration that
     covers a class of inputs, with file:line, the cause it removes, and the dev
     count before and after. A fix that names a dev-set sentence, or adds a full
     sentence to `styles/*.json`, is rejected: a script checks that no dev
     sentence appears verbatim in any file you changed.

G1.4 **Round target:** dev-set accuracy on answerable turns **60% or higher**,
     Korean and English each **50% or higher**, with 0 wrong answers (a hold is
     allowed, a wrong answer is not). If a target cannot be reached, the report
     names the blocking cause and its count, with evidence, and does not
     redefine the target.

G1.5 **Nothing regresses.** `tests/test_repair_and_english.py` 19/19; the fixed
     7-step dialogue passes in both languages; the parallel full suite
     (`python -m pytest tests -q -n 12 --dist loadfile -p no:cacheprovider --basetemp=/tmp/g1-pytest`)
     passes at least as many tests as `main` did at your start, with the same
     known failures and no new ones.

G1.6 **Hand-off for the frozen run.** The report ends with the commit hash to
     score. The owner runs the frozen set and records
     `docs/ko/dialogue-gate-2026-09-22/round1.json`. That number, not the dev
     number, is the round's result.

## Owns

`marco/language/frames.py`, `language_components.py`, `relational_semantics.py`,
`marco/language/hangul.py`, `engine.py`, `explain.py`, `marco/reasoning/context.py`, `marco/reasoning/state.py`,
`styles/*.json`, `data/benchmarks/dialogues_dev/`, `tests/` files for those
modules, and the one flag in `bench/dialogue_gate.py`.

Must not touch: `marco/language/` (W1 owns it; the `realize()` call in
`marco/reasoning/context.py` stays where it is), `mco/`, `alma_*`, any frozen area.
A change needed in `marco/language/` goes to `docs/requests/G1-<n>.md`.

## Working conditions

Own hidden checkout, branch `understanding-r1`. Commit by name, owner as author,
no co-author lines, no assistant name. `python`, not `python3`. Do not push.
Report tersely: G1.1–G1.6 each done or not, with numbers, then the cause table
before and after.
