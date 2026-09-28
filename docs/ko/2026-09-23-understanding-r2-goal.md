# Goal G2: understanding, round 2 — read the statements, then generalize

Model: Opus 5.5, effort high. Read `docs/ko/2026-09-22-freeze-decision.md` first.
Written 2026-09-23. Starts after `main` contains a8388e9 (G1) and 6e03889 (W1).
Check `git log --oneline -8` shows both merges; if not, stop and tell the owner.
Own hidden checkout, branch `understanding-r2`.

## Facts from round 1 (owner-run, `docs/ko/dialogue-gate-2026-09-22/round1.json`)

- Frozen gate at a8388e9: **19 of 108 answerable turns, 17.6%**. Korean 9/54,
  English 10/54. 87 holds, 1 wrong, 1 unverifiable. Baseline was 3/108.
- Round 1's own dev set scored 65/96 (67.7%). **That gap is the round-2 problem:**
  the rules were declared to fit the dev phrasings, not the language.
- Record turns (statements, not questions) were correct **77 of 150, 51%**. A
  question can only be answered if the statements before it were recorded, so
  reading statements is the largest lever in the set.
- By category: transfer 19/102, follow-up 5/38, correction 5/32, restart 6/12,
  ownership 0/6, ambiguous referent 0/10, cross-language 0/4. Every "why" turn held (0/26).
- The one **wrong** answer came from a repair: it dropped the particle from a
  numeral word and turned a "both together" total question into a different
  reading, then answered a wrong total. A repair must never change the scope,
  quantity, counter, or polarity of a question.
- The **unverifiable** answer gave a number with no owner named. An answer must
  name whose.

## Exam rule — breaking it fails the goal

- Never open `data/benchmarks/dialogues_v1/`; never run the scorer against it.
  From `baseline.json` and `round1.json` read only `gate`, `by_language`,
  `by_category`, `other_labels`. Not `failures`, not `rows`.
- Round 1's dev set `data/benchmarks/dialogues_dev/` is now **seen**. You may run
  it as a regression check, but you may not tune on it. Build a new set (G2.1).

## Definition of done — all eight, measured

G2.0 **Housekeeping first, two separate commits, before any rule work.**
     (a) The four result sites in `docs/requests/G1-2.md` get the same
     language-free `meaning` key as their neighbours (contract:
     `marco/language/realizer/meaning.json`). (b) `docs/requests/W1-3.md` part 2:
     carry the negation marker (`부정표지`) as a language component field
     (`negation_marker`) through `language_components.load_reasoning_language`
     and `PackModel.language`; the realizer's check reads it from the model and
     falls back to the loose file only when the model has none. For (b) you may
     touch `marco/language/realizer/check.py` for that one read. Tests under
     `tests/language/` and `tests/test_language_seam.py` pass after each commit.
     (c) **Integration regression, real bug:** on `main` after the G1 and W1
     merges, `tests/test_understanding_r1.py::test_a_total_and_a_comparison_read_current_counts`
     fails: a total question answers 4 where the reasoning produced 9. It passed
     on the G1 branch alone, so W1's answered-result change (the question
     example's render and counter carried on the result, or the realizer's
     count-clause composition) replaces the total with one participant's count.
     Find which, fix it so the realized sentence keeps the value the reasoning
     produced, and add the case to the seam tests. You may touch
     `marco/language/realizer/` for this fix only, minimally, with file:line in the report.
     (d) **Seam test pins understanding:** `tests/test_language_seam.py::
     test_unrealized_turns_are_byte_identical_and_realized_turns_keep_the_value`
     fails for ko-01, ko-02, ko-08 because it pins composed turns by digest, and
     G1 changed those answers from holds to answers. Apply option 2 of
     `docs/requests/G1-1.md`: within one run, compare every turn with `realize`
     patched to identity against the same turn with the real `realize`;
     unplanned turns must be byte-identical, planned turns must keep the value.
     No pinned digests or strings of engine output remain in the file.
     After (a)–(d) the full parallel suite on your branch must show only the three
     known failures: two `test_response_composer` tests and the macOS RSS check.

G2.1 **Dev set v2** `data/benchmarks/dialogues_dev2/`: at least 60 dialogues, at
     least 30 per language, built by varying declared dimensions
     **systematically**, not by writing sentences one at a time: word order,
     particle and ending register, sentence splitting and joining, numeral form
     (digits, native, Sino-Korean, words), counter, correction position, name
     and item substitution across scripts, statement before or after the
     question. Each dialogue records the dimensions it varies. Zero full-sentence
     overlap with `dialogues_v1`, `dialogues_dev`, `tests/`, `bench/`, `cases/`,
     `styles/` (F1.3 script, extended to take several directories). At creation,
     split by a fixed recorded seed into a **build** half (2/3) and a **check**
     half (1/3). The check half is never read while writing rules.

G2.2 **Cause tables on the build half**, at start: one for held answerable
     turns, one for failed record turns. One cause per row from a fixed list you
     define; counts sum to the totals. Both tables in the report.

G2.3 **Fix causes largest first**, statements before questions. Each fix is a
     rule or a declaration covering a class of inputs, with file:line, the cause
     it removes, and build-half counts before and after. The overlap script over
     every file you changed must print 0 against build, check, dev v1, and v1.

G2.4 **Targets**, all on the check half, which you never tuned on:
     answerable turns **60% or higher**, record turns **85% or higher**, **0 wrong**,
     every answer names its subject. On the build half: answerable 75% or higher,
     0 wrong. If a target cannot be reached, the report names the blocking cause
     and its count with evidence, and does not redefine the target.

G2.5 **Repair safety.** A repair that changes a numeral, a counter, a scope word
     (둘, both, together, each, total), or a negation is rejected before the turn
     is answered; the turn holds and says what the repair would have changed.
     Injection test: at least 12 repairs of those kinds, all held, none answered.

G2.6 **Nothing regresses.** `tests/test_repair_and_english.py` 19/19;
     `tests/test_understanding_r1.py` passes; `tests/language/` and the seam test
     pass; the parallel full suite (`python -m pytest -q`, parallel by
     `pytest.ini`) passes at least as many tests as `main` at your start, with the
     same known failures and no new ones. Record both counts.

G2.7 **Round-1 dev set as regression only:** run it once at the end and record
     the number; it must not drop below 65/96.

G2.8 **Hand-off.** The report ends with the commit hash to score. The owner runs
     the frozen set once and records `round2.json`. That number is the result.

## Owns

`marco/language/frames.py`, `language_components.py`, `relational_semantics.py`,
`marco/language/hangul.py`, `engine.py`, `explain.py`, `reasoning_context.py`, `state_engine.py`,
`pack_model.py`, `styles/*.json`, `data/benchmarks/dialogues_dev2/`,
`tests/test_understanding_r2.py`, `tests/` files for those modules, the
`--dataset` handling in `bench/dialogue_gate.py`, and for G2.0(b) only the one
read in `marco/language/realizer/check.py`.

Must not touch: the rest of `marco/language/`, `mco/`, `alma_*`, any frozen area.
A change needed elsewhere goes to `docs/requests/G2-<n>.md`.

## Working conditions

Commit by name, owner as author, no co-author lines, no assistant name in any
commit message or file. `python`, not `python3`. Do not push. Report tersely:
G2.0–G2.8 each done or not with numbers, both cause tables before and after,
build and check numbers side by side, and the commit hash.
