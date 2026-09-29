# Goal G7: understanding, round 7 — questions as frames, statements that cascade

Model: Opus 5.5, effort high. Read `docs/ko/2026-09-22-freeze-decision.md` first
(the exam rule, the data rule, the standing decision: no token-based model in the
runtime), then `docs/ko/2026-09-25-understanding-r6-goal.md` (classes 1–14 are
still the class list) and G6's row in the queue, `docs/requests/G6-2.md`,
`G6-3.md`, `G6-4.md`, `W6-1.md`. Written 2026-09-29 by the plan manager.

Two chats run in parallel, each in its own hidden checkout: **G7-Q** (questions,
branch `understanding-r7-questions`) and **G7-S** (statements, branch
`understanding-r7-statements`). Each reads this whole file and does its own part.

## Where round 6 left MARCO 1

Frozen exam at main f88f679 (owner run 2026-09-29, same as round 6): **63/108
(58.3%)**, 0 wrong, 0 violations, record 138/150, why 18/26. Round 6 did the
statement classes of its list and stopped before the question classes (8–12).
The exam's held answerable turns, by the engine's own hold reason, classes only:

| Hold reason on the held answerable question | Frozen | Dev v6 check |
| --- | --- | --- |
| the question itself not read (`input_understanding_failed`) | 22 of 45 | 43 of 125 |
| an earlier statement not read (`unread_event`) | 15 | 64 |
| no referent / unresolved / other | 8 | 18 |

The same reason also holds 5 of 8 held why turns, 4 of 6 held corrections and 14
of 16 held missing-premise questions on the exam: **about 45 exam turns wait on
the question reader alone.** Dev v6's check half (204 dialogues with outside
phrasings) scores 109/234, below the exam, and shows the same two causes: it is
the right dev set for this round.

What the dev v6 check half shows, by class (dev data, may be read):

**Questions not read (G7-Q).** The count-question reader in
`relational_semantics.py` (`_count_question_meaning`, `_count_predicate_forms`) is
closed-world by design: an undeclared word after the counter means nothing is read.
Measured on main through the gate's own player:

| Asked | Read? |
| --- | --- |
| "How many pens do Nora and Bo have in total?" | yes |
| "… in all?", "… combined?" | no |
| "What about Bo?", "And Bo?", "민수는요?" | yes |
| "And in the garage?" (place switch) | no |
| "And cups?" (item switch) | no |

The dev v6 unread questions are the round-6 classes 9–11: item and place
switches (`And croissants?`, `And in the sunroom?`, `라임은요?`, `물류센터는?`,
`선착장은?`), holder switches the reader misses with titles (`기 대표님은?`),
bare-name referent repairs as a turn (`영훈이요.`, `은호 님입니다.`, `Kurt, I
mean.`, `Dr. Lambert is the one I mean.`), total modifiers (`in all`,
`combined`), and comparisons of two named holders (`A와 B 중에 누가 X를 더 많이
가지고 있어?`, `Which of us has more X, me or A?`).

**Statements not read (G7-S), 53 of 434 on the check half, blocking 93 questions:**

| Class | Reason given | Check count | Example form (dev) |
| --- | --- | --- | --- |
| S1 English appositive relational holder | `input_understanding_failed` | 5 | `A's friend, B, (also) has N X.` |
| S2 Korean continuation, giver omitted | `input_understanding_failed` | 10 | `그리고 R에게 X를 N개 주었다.` |
| S3 Korean transfer judged `invalid` | `invalid` | 11 | `A가 B에게 X를 N개 줬어.` with titled holders, 보냈어, 나눠 줬어요, 빌려주었다, 내가 |
| S4 partitive use-up | `repair_over_bound`, `unknown_word` | 13 | `A used N of them for P.`, `A가 그중 N개로 P를 만들었습니다.`, `그중 N대를 P에 맡겼어` |
| S5 particle-verb transfer | `repair_over_bound` | 1+ | `A passed N X on to B.` |

S3 needs a diagnosis first: the sentences are plain transfers the reader knows,
so `invalid` comes from a state check (a giver whose count is not established, a
titled holder keyed two ways, or the first-person holder), not from the words.

## G7-Q — the question reader as a frame, not a list of forms

The point of this round is to stop adding question forms one at a time. A
question is read as **a frame plus slots**, in both languages:

- operator: `count`, `total` (two or more holders, or "we/us/the two of them"),
  `more` / `fewer` / `same` (two named holders, including me), `left` (what
  remains after use-ups), `where` (a place count), `why` (restated fact);
- slots: holder(s), item, place, and optionally the counter asked;
- modifiers that do not change the operator are a **declared class** in the pack
  (`in all`, `altogether`, `combined`, `in total`, `between them`, `all
  together`, `now`, `at the moment`, `still`, `left`, `remaining`; 모두, 다, 전부,
  합쳐서, 다 합쳐, 총, 이제, 지금, 아직, 남은), not per-form entries; a word in the
  modifier class is allowed anywhere its declaration says;
- a **follow-up is a partial frame**: whatever it names (holder, item, place,
  holder with title, "me") replaces that slot of the previous question's frame and
  the rest is inherited; a turn that names only a referent after an ask (bare-name
  repair) fills the slot the ask was about;
- candidate frames are validated against the conversation's state the way
  statements are (G5.4): the holder, item and place must exist; two candidates
  that both pass mean ask, none means hold with the gap class.

Frames are declarations in `styles/*.json` read by one reader, the same way the
statement frames are. No sentence-shaped entries are added to the pack for this
round's classes.

**G7-Q.0 Question grid probe.** A generated probe, `bench/question_grid.py`, both
languages: every operator × every declared modifier × the holder forms (name,
title + name, name + title, relational noun, me/나, place) × the follow-up kinds
(holder, item, place, bare-name repair), from a small state the probe states
first. Report per cell. Scored before the first change and after every batch.
This is the structural measure; dev v6 is the natural one. It never reads the
frozen sets.

**G7-Q.1 Frames and follow-ups** as above, batches of one kind, dev v6 check
half and the grid scored after every batch.

**G7-Q.2 Why with a restated fact** where round 6 left it: every why turn of
the dev v6 check half that holds with `input_understanding_failed` either
explains or asks which holder.

**G7-Q.3 Counter of the answer** (G6-4 item 3): the asked counter (권, 장, 자루,
송이, 대, 묶음) goes into the query meaning as a field; write the request for the
realizer as `docs/requests/G7-1.md` if a plan must change.

**Targets (G7-Q):** grid 95% or better per language with 0 wrong; dev v6 check
half answerable questions held with `input_understanding_failed` 43 → 5 or
fewer; why on the check half 11/28 → 22/28 or better; 0 wrong, 0 violations.

## G7-S — the statements that hold everything after them

**G7-S.0 Cause table for S3** before any fix: for each `invalid` statement of
the check half, which constraint or state check refused it, as a table.

**G7-S.1 Fixes, S3 first** (it is the one a known verb fails), then S2, S4,
S1, S5, as declared classes, batches of one class, check half after every
batch. S2 is the elided-subject continuation: the giver is the previous
statement's subject (or giver), read as a candidate and validated by state. S4
reads "used N of them / 그중 N개로 … 만들었다" as a use-up of the previous
statement's item by that holder; `repair_over_bound` must not refuse a use-up the
holder's count allows.

**Targets (G7-S):** dev v6 check half unread statements 53 → 15 or fewer;
questions held behind an unread statement 93 → 25 or fewer; records 381/434 →
94% or better; 0 recorded wrongly, 0 wrong, 0 violations.

## Amendment (owner, 2026-09-29): inference, not coverage

The owner's aim is inference: a system that thinks a problem through, where
more effort gives a better answer. The exam alone does not show that; six
rounds of rules for single forms raised the dev scores much faster than the
exam score. From now on, in both chats:

**A1. Candidates, not rules.** A turn that does not read, or reads but is refused
by a state check, is handled by generating candidate readings or repairs and
validating each against the conversation's state and constraints (the G5.4
machinery, extended): the omitted giver is each earlier holder as a candidate;
a transfer from a holder whose count was never stated is recorded with that
count as an unknown with a lower bound, not refused; a follow-up's missing
slots are candidates from the previous frames. One survivor → answer; several →
ask; none → hold with its gap class. A declaration is added only for a word the
pack lacks (a verb, a modifier, a counter), never a sentence-shaped entry for
one form. Each commit says which it is.

**A2. Effort budget.** One declared setting, `effort` 0 to 3, bounds how far
the candidate search goes (0: first reading only, as main behaves now; 1:
readings the reader gives; 2: plus slot and referent candidates from the
conversation; 3: plus one repair step, such as an elided argument, a
lower-bound count or a split holder, and a retry). The budget changes the search,
never the checks: at every level a wrong answer is a failure. The trace records
the level, the candidates tried and why each was dropped.

**A3. The effort curve is a target of its own.** After every batch, score only
the dev v6 check half at effort 0 and 3 (owner, 2026-09-29: about 8 minutes, not
45). At hand-off, score dev v4, v5 and v6 check halves at effort 0, 1, 2, 3. Report answerable, wrong and
median milliseconds per turn per level. Done when accuracy rises from level 0
to level 3 on every check half with 0 wrong at every level. A class fixed only
at level 0 (by a rule) shows no curve and is reported as coverage, not inference.

**A4. Rank, answer on a clear win (owner, 2026-09-29).** Effort sets how many
candidates are generated. Survivors are ranked by a declared order, not by
numeric weights: state fit, then reasoning fit, then grammar fit, then context
fit, then lowest repair cost (the G5 design note §11, made lexicographic). The
top candidate is answered only when it beats the runner-up on one of those
checks; a true tie asks, no survivor holds. The trace records the ranking and
the check that decided it, so "why" can say why this reading won. This replaces
"several → ask" in A1.

**A5. Level 3 is turn-local deliberation (owner, 2026-09-29).** No persistent
learning, no permanent repair, no external research, no OpenProblem promotion:
whatever a repair step tried is gone when the turn ends, except its record in
the trace. A test pins it: after a level-3 turn, the packs, the graphs and the
declarations are byte-identical, and research was not called.

Self-repair that persists (roadmap R-A, the fixed timeline's M2) stays frozen
until the gate.

## Both

**Together, after both merge:** dev v6 check half answerable 109/234 → 70% or
better. The owner then scores the frozen exam.

**Nothing regresses (each chat, on its own branch):** repair 19/19; r1 to r6
tests; round-3 check half 98/106 or better; v4 and v5 check halves at their
round-6 numbers or better (score them before the first change and record them);
`tests/language/`, seam, composition and trace tests; the full parallel suite at
main's count (2214 passed) with main's 4 known failures; the seven-step dialogue
verbatim in both languages.

**Guard:** build and check halves stay apart: fix from the build half's
sentences, score the check half. If the check half trails the build half by 15
points or more after a batch, stop adding rules and report.

**Hand-off:** the commit hash, the grid table (G7-Q), the S3 cause table
(G7-S), the before/after tables per batch. The owner merges and scores the
frozen sets.

## Owns

**G7-Q:** the question reading in `relational_semantics.py`
(`_count_question_meaning`, `_count_predicate_forms` and the query readers),
the question sites of `marco/reasoning/context.py` (`_question_parts`,
`_repair_and_question`, `_resolve_pointers`, the follow-up and referent-repair
paths), question declarations in `styles/*.json`, `marco/language/frames.py`
where it reads questions, `bench/question_grid.py`, `tests/test_understanding_r7_questions.py`.

**G7-S:** statement reading in `relational_semantics.py`, `language_components.py`,
`marco/language/hangul.py`, the replay and reading constraints of
`marco/reasoning/context.py` (`_replay`, `READING_CONSTRAINTS`, `_shaken_by_unread`,
repair bounds), `marco/reasoning/state.py`, statement declarations in
`styles/*.json`, `tests/test_understanding_r7_statements.py`.

Both touch `relational_semantics.py`, `marco/reasoning/context.py` and
`styles/*.json`: keep edits inside your own functions and declaration blocks,
commit small, and write a request to the other chat
(`docs/requests/G7-<n>.md`) instead of editing its sites. The owner merges the
first branch to finish; the second then syncs with main before its hand-off.

Must not touch: `marco/language/realizer/` and the reply-return sites (write a
request), `mco/`, `alma/`, the gate scorers, any frozen area. Nothing reads
`data/benchmarks/dialogues_v1/` or `reasoning_v1/`.

## Working conditions

Commit by name, owner as author, no co-author lines, no assistant or model name
in commits or product files. `python`, not `python3`; `KG_ENCODER=문자`. Commit
after every batch. Do not push. Report tersely: numbers, file:line, pass/fail.
