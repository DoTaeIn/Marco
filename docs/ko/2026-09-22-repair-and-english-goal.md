# Goal: repair unmatched input and report it, and make English the core language

Written 2026-09-22 for execution in a separate session. This is a goal, not a
report. Baseline HEAD at writing: `f02d803`.

## Definition of done

This goal ends when **all** of G1-G6 below hold, verified by running, not by
reading code. It does not end because a part is working, because tests pass,
because time ran out, or because remaining items were moved to a "not supported"
list. If an item cannot be reached, stop and report the blocker with evidence;
do not redefine the item.

- **G1** An input matching no declared rule produces: the nearest rule, the named
  repair, and an answer computed under that repair — in one turn, without asking
  the user to confirm.
- **G2** `민수는 사과 다섯 개가 있어` (correct Korean, unmatched today) is answered
  this way, and the repair is named in the output.
- **G3** English is the core language: `styles/english.json` carries the declared
  rules, English is the default selection, and the seven-step dialogue of
  `2026-09-22-mco-integrated-roadmap.md` §12 runs in English.
- **G4** The same seven-step dialogue still runs in Korean, from the Korean pack,
  with no Korean left in Python.
- **G5** Removal test passes: delete a declared rule and the sentence that depended
  on it becomes unproducible or held. It must not keep working.
- **G6** The unseen-phrasing number is published: 20 phrasings not used during
  development, how many answered before, how many after, failures listed.

## Confirmed invariants — these are already true, keep them true

Both were verified in the current tree before this goal was written. Breaking
either is a failure of the goal even if G1-G6 pass.

**I1 — It does not pick sentences from a list.** Word forms are computed from
declared rules, not looked up: `뒹굴 + 는데 -> 뒹구는데` with ㄹ deletion, for stems
that appear nowhere in the data. Answers must be produced the same way. Any new
answer type must be realized from structure plus declared grammar. Adding a
finished sentence to a table is not an implementation of an answer type.

**I2 — Nothing language-specific is hardcoded in Python.** Vocabulary, particles,
endings, word order, sentence shapes, answer shapes, repair rules and costs all
live in the pack. Target state is a single shareable `.mco` file that carries the
language; anything left in Python cannot travel in that file. A Python branch on a
specific word, verb, name, sentence or test id is a failure. Moving a Korean list
into a JSON string blob inside one node is also a failure — it must be declared
structure the runtime executes.

## Scope

### A. Repair and report, no confirmation

1. No declared rule matches. Find the nearest declared rules and, for each, the
   repair that would make it fit: token skipped, particle in the wrong position,
   ending missing, order changed.
2. Repair cost is declared in the pack and bounded. Above the bound, hold and say
   which part could not be placed. Do not silently widen the bound.
3. Report the repair, then continue in the same turn. Do not wait for the user.
   The answer carries: rule used, repair applied, resulting reading.
4. A state change made under a repair is marked as resting on that repair, so an
   existing correction retracts it cleanly. No repair may be invisible after the
   fact.
5. Repair is matching at a measured distance. It may not introduce a token that
   was neither typed nor declared. That is the line between this and guessing.

### B. English as the core language

1. `styles/english.json` currently has 0 examples and lacks 37 of the reasoning
   keys the Korean pack declares. Fill it. The prepared material in
   `docs/ko/english-pack-preparation/` is draft-for-exchange, not runtime schema;
   convert it, do not copy it blindly.
2. This is a pack-population job, not an engine rewrite. Verified before writing
   this goal: with four declared English examples and no particles at all, the
   engine already answers
   `Minsu has 8 apples. Jiyeon has 3 apples. Minsu gave Jiyeon 2 apples. how many
   apples does Jiyeon have?` with `5 apples.` Word order alone carried the roles.
3. Default selection moves to English in every path that chooses a language:
   `language_components._language_path`, `marco/runtime/explain.py` (`KG_LANG`), and
   `pack_model.descriptor` (`default_model_language`). One declaration, not three
   defaults drifting apart.
4. `engine.py:108` returns a hardcoded Korean refusal. Move it to the pack. Find
   the rest of the same class; do not fix only the one named here.
5. Korean must keep working from its own pack. Two packs in one process must not
   contaminate each other.
6. Unknown at writing time, resolve early and report: whether event reading
   (`frame_induction.read_event`) works for English, since it locates roles by
   particles attached after a word and English marks them by position and
   prepositions before it. The example path already works; this path is untested.

## Verification

1. Structured-input results and natural-language results are reported separately.
2. Repaired answers, held inputs, wrong assertions and execution errors are
   counted separately. A hold is never counted as solved.
3. Error injection: a deliberately wrong repair rule and a deliberately wrong
   composition rule must both be caught by the evaluation, or the evaluation is
   not trusted.
4. Re-measure and report the frozen routing figures and the existing benchmarks.
   Do not assume they are unchanged.
5. Report cost: startup, per-turn latency, memory, pack size. The suite currently
   takes about 20 minutes; if that grows, say so.

## Not in this goal

- Any language model at runtime, in any form.
- Understanding arbitrary Korean or English. Coverage stays bounded by what is
  declared, and the bound is reported.
- Irregular morphology beyond what is declared. `춥 -> 춥었다` is wrong today;
  declare the irregular class or leave it wrong. Do not special-case the verb.
- Building the `.mco` container. This goal only ensures nothing is left in Python
  that would be unable to travel inside it.

## Working conditions

- **Another session is working in this repository right now, and the previous goal
  is not finished.** Do not revert, overwrite, or "clean up" changes you did not
  make. Stage files by name; never `git add -A`.
- Local may be behind the remote. Check before and after. If `git worktree add`
  fails, `git worktree prune` first — a failed `cd` after it silently runs the
  tests in the working tree and reports a false pass.
- Verify every push from a clean checkout of the pushed commit, not from the
  working tree. A commit has been pushed with a file missing from staging before.
- Expect about 32 test failures caused by a gitignored 86MB corpus
  (`data/위키/정의문.jsonl`) that `tests/test_reasoning_persistence.py:create_app`
  requires unconditionally. That is a known separate issue. Do not count those as
  your regressions, and do not fix them inside this goal.
- Commits: author must be the repository owner only. No co-author or generated-by
  lines.

## Reporting style

Report in minimum words. Numbers, file:line, pass/fail. No full-sentence prose, no
restating the task, no summaries of what you are about to do. Report what changed,
what was measured, and what failed.
