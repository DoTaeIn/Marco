# Understanding experiments — the log

One row per experiment. The loop (owner, 2026-09-29):
cause found → patch → regression → merge → frozen score → next cause.
Work time is the time the chat or the plan manager was changing or measuring.
Wait time is the time a finished patch sat before the next step (a permission
prompt, a merge, a score). Times are local, from commit and run timestamps.

| # | Structural cause | Patch (commit) | Work | Wait | Regression | Frozen exam | Remaining largest causes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | baseline, main f88f679 | — | — | — | — | 63/108, 0 wrong, 0 violations | question itself unread 22; earlier statement unread 15; other 8 |
| 1 | (from dev v6, statements) a holding recorded under a key that kept a case particle, so the later transfer finds no count | b10e621, merged 2ccd19c | chat 18 min; plan manager 10 min (merge, exam, suite) | chat 13 min on runs; 0 on prompts; patch reported 14:01, merged 14:02, scored 14:05 | suite 2254 passed, the 3 known failures; seven-step 7/7 both languages; dev v6 check 109 → 121/234 at effort 3 | **63/108, 0 turns changed**, 0 wrong, 0 violations (`dialogue-gate-2026-09-22/experiment-01.json`); the ranking fired on 0 exam turns | see below |

## What experiment 1 showed

The cause was found on the dev set and the exam does not have it. From experiment
2 on, the cause is found on the exam's own failures, by structure and counts only
(the plan manager's profile; no sentence leaves the exam), and the chats patch that.

Exam profile at 2ccd19c, the 45 held answerable turns:

| Structural cause | Held answerable turns | Evidence (counts) |
| --- | --- | --- |
| A follow-up of 1 to 3 words inherits a question frame only right after an answered count question | 13 | previous turn: a held question 5, a clarify exchange 8, a why 2; almost all name a new holder |
| A statement that does not name its thing | about 15 (behind 9 statements) | 12 statements unrecorded; holder named in 12; thing not named in 9; count as a word in 12, as digits in 0; 5 English transfers refused as missing_initial_quantity |
| Other unread questions | 9 | 4 count questions over 3 words; 2 totals of several holders; 2 without a count word; 1 comparison |
| Cross-language question | 4 | no_referent / cross_language_unmatched |
| Other | 4 | unresolved 2, repair_protected 1, not_stated 1 |

Experiment 2 (statements chat): the unnamed thing as a candidate from the
conversation. Experiment 3 (questions chat): the question frame kept when the
question is read, so a follow-up inherits it whatever became of the question.

## Experiments 2 and 3

| # | Structural cause | Patch (commit) | Work | Wait | Regression | Frozen exam | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2 | (exam) a short follow-up inherits a question frame only right after an answered count question; the question reader accepts forms one by one | c47a132, merged 095b434 | chat 35 min; plan manager 12 min | chat 15 min on runs; reported 14:19, merged 14:19, scored 14:22 | **7 new failures** (suite 2,248 passed, 10 failed): round-2 safety test of a scope word over one holder ×3, a probe word declared, a grid sentence shared with dev4, a learning-flow test, the chat's own effort-3 pin inside the parallel run. Merged before the suite had run: from now on the chat runs the full suite before it reports | **69/108** (+6), 0 wrong, 0 violations; questions unread 22 → 8; held behind something unread 15 → 22; one missing-premise turn right → held (`experiment-02.json`); composition 340/340; reasoning 110/113, 0 wrong | grid en 115/299 → 293/314, ko 173/357 → 343/375; dev v6 check 109 → 151/234 |
| 3 | (exam) a statement that does not name its thing | 4845db8, merged dc4d103 | chat 11 min; plan manager 6 min | chat 12 min on runs; reported 14:28, merged 14:41 (13 min behind the suite re-run), scored 14:43 | same 10 as experiment 2, none new | **69/108, gate unchanged**; missing premise 3 → 5 of 20, ambiguous 7 → 8 of 12 (`experiment-03.json`) | the patch covers "nothing after the number"; the exam's form has a word after the number |

Exam profile at dc4d103, the 39 held answerable turns: held behind something
unread 22 (13 behind the 12 unrecorded statements, 6 behind a correction turn
that is not read, 3 other); question not read 8; cross-language 4;
which_referent 2, unresolved 2, not_stated 1.

Masked shapes of the unrecorded English transfers (names, things and numbers as
placeholders, every other word as `w`): `GIVER w RECEIVER NUMWORD w .` (2),
`GIVER w NUMWORD w w RECEIVER .` (1), and the same with a title written with a
period before each name (2). The slot after the number holds a word that is not
the thing.

Next: the seven regressions (questions chat, first); the slot after the number
as candidates (statements chat); correction turns the reader does not read
(questions chat, after the regressions).

## Diagnosis of the grounding path (owner's request, 2026-09-29, main dc4d103)

No code changed. Every exam turn was played with the reader's output, the
conversation's state just before the turn, the candidate steps run and the hold
reason recorded; structure and counts only.

**The conversation's state (the overlay) works.** Of 210 gold facts a turn needed
where every earlier statement had been read, 205 were in the state with the right
value; the other 5 had the holder counted, not with that thing. 0 uses of
withdrawn evidence. The state is a list of the sentences said, replayed into facts
keyed by words (holder words + thing); there is no canonical identity. 25 matching
keys keep 1 to 3 extra words and 7 facts have several keys, and that is the root
of only 2 failures.

**The break is the reader → grounding bridge.** 84 exam turns are not right:

| Class | Turns | Of the 39 held answerable |
| --- | --- | --- |
| reader_did_not_emit_partial_candidate (the reader returns nothing; no candidate is built; the state is never asked) | 36 | 11 |
| grounding_candidate_not_built (a complete reading with a wrong word in the thing slot; the state refuses it; no other candidate) | 5 | 0 |
| overlay_lookup_failure | 7 | 2 |
| identity_resolution_failure | 2 | 1 |
| other: a tie held where the exam expects one answer | 2 | 2 |
| overlay_write_failure | 0 | 0 |
| state_validation_rejected_correct_candidate | 0 | 0 |
| cascade, held behind one of the above | 32 | 23 |

The 23 cascaded answerable turns wait on: a statement with no candidate built 9,
a statement the reader returned nothing for 4, a correction the reader returned
nothing for 6, a lookup failure 2, an identity failure 1, unexplained 1. So the
bridge accounts for 30 of the 39, lookup 4, identity 2, ties 2, unexplained 1.
In all 11 unread answerable questions the state already held every needed fact.

Smallest code paths: `marco/reasoning/context.py` `_read_unsaid_thing` (the test
that skips a subject that already carries a thing), and `_turn` where a reading of
None goes to `_check_readings` and then to the unread store, with
`RelationalParser.parse(partial=True)` returning None instead of what it did
recognise. Experiment 3's patch was reached on the 5 statements and returned None
on each: it fixed a symptom the exam does not have.

## Experiment 4: the regressions of experiment 2

| # | Cause | Patch (commit) | Work | Wait | Regression | Frozen exam |
| --- | --- | --- | --- | --- | --- | --- |
| 4 | the question patch read a scope word over one holder as a modifier, declared a probe word, put a dev4 sentence in the grid, let a follow-up name nothing of the conversation, and its pin test depended on other tests' writes | 675c1f5, merged a18c617 | chat 40 min; plan manager 10 min | chat 12 min on runs; reported about 14:57, merged 14:58, exam scored 15:01; **the suite took 52 min instead of 6** and the composition and reasoning gates an hour, because two chats and the plan manager ran tests on one machine (load average 10 to 15) | suite 2,270 passed, the 3 known failures; gate test files 35 passed | **67/108** (−2: two Korean turns back to held, the cost of the restored safety hold), 0 wrong, 0 violations; composition 340/340; reasoning 110/113, 0 wrong (`experiment-04.json` in both folders) |

Owner's decision after the diagnosis (2026-09-29): the statements chat adds the
wrong-thing candidate; the questions chat returns the recognised structure as a
partial candidate instead of None.
