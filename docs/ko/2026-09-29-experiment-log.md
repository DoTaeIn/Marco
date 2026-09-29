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

## Experiment 5: the wrong-thing candidate (with the Korean holding that names no thing)

| # | Cause | Patch (commit) | Work | Wait | Regression | Frozen exam |
| --- | --- | --- | --- | --- | --- | --- |
| 5 | (exam, diagnosed) a statement read completely with a word in the thing slot that is not the thing; the state refuses it and no other candidate is built | 52f3609 with daa4c8a, merged 89cd4b0 | chat 35 min; plan manager 8 min | chat 85 min, of which its full suite 63 min at load average about 60; reported 17:00, merged 17:01, scored 17:03 | suite 2,312 passed, the 3 known failures, 344 s run alone | gate **67/108** unchanged, 0 wrong, 0 violations; **statements recorded 138 → 142 of 150**; refused as invalid 5 → 2; ambiguous 8 → 7 of 12 (`experiment-05.json`) |

The four statements are recorded and the questions after them stay held: the
question reader returns nothing for them, or they wait on a correction or a
which-person turn. The two transfers still refused are the two cases the patch
excludes on purpose (the amount "one" before a word without a plural form; a
plural word that is not the thing): taking out a thing that was said would
answer about another thing.

## Experiment 6: the one wrong record

| # | Cause | Patch (commit) | Work | Wait | Regression | Frozen exam |
| --- | --- | --- | --- | --- | --- | --- |
| 6 | (exam) a transfer recorded with a stale count: the safety check that holds a holder behind an unread statement asked for every word of the holder's key, and an unread use-up that leaves the thing to a pronoun has no thing word | 6a4bff0, merged 18b9f53 | chat 10 min; plan manager 5 min | chat 8 min on runs; reported 17:18, merged 17:19, scored 17:22 | chat's full suite 2,284 passed, 1 known failure (gate files left out), 6 min; gate files and both round-7 test files run at merge: passed | gate 67/108 unchanged; **wrong records 1 → 0: no wrong turn is left on the exam**; statements 142 right, 8 held (`experiment-06.json`) |

## Experiment 7: the partial reading as a candidate

| # | Cause | Patch (commit) | Work | Wait | Regression | Frozen exam |
| --- | --- | --- | --- | --- | --- | --- |
| 7 | (exam, diagnosed) the reader returns nothing for a sentence it cannot read whole, so no candidate is built and the conversation's state is never asked | d93ab7e with 92f3d72 and f814f38, merged 46427c5 | chat 75 min; plan manager 6 min | chat 45 min (machine load 25 to 52 from other runs); reported 17:35, merged 17:36, scored 17:39 | chat's full suite 2,292 passed, 1 known failure (gate files left out); gate files, round-2 and round-7 tests at merge: 258 passed | **76/108 (70.4%)**, +9, 0 wrong on the whole exam, 0 violations; English 41 of 54, Korean 35 of 54; corrections 12 → 14 of 18; why 18 → 19 of 26 (`experiment-07.json`) |

Exam profile at 46427c5, the 32 held answerable turns: the reader returns nothing
and the grounding builds no candidate 11 (in 10 the state holds every needed
fact); held behind an unread turn 17 (behind a statement the reader returns
nothing for 4, behind a correction 4, behind the two transfers the wrong-thing
candidate excludes on purpose 4, behind a lookup failure 3, other 2); lookup
failure 2; identity 1; a tie held where the exam expects one answer 1.

## Experiment 8: the short follow-up, the comparison, the near key

| # | Cause | Patch (commit) | Work | Wait | Regression | Frozen exam |
| --- | --- | --- | --- | --- | --- | --- |
| 8 | (exam) the grounding builds no candidate for a very short turn that names a holder or thing of the state beside a word that says nothing, for a comparison of two named holders, and for a count asked under a key the state lacks | bbc4cda with 4c128c4, merged 1683212 | chat 75 min; plan manager 5 min | chat 20 min on runs; reported 18:13, merged 18:14, scored 18:17 | chat's full suite 2,303 passed, 1 known failure (gate files left out); gate files and the round-2, round-6 and round-7 reading tests at merge: 381 passed. One pin of round 6 changed: a held question is now answered with the expected value | **81/108 (75.0%)**, +5, 0 wrong on the whole exam, 0 violations; English 44 of 54, Korean 37 of 54 (`experiment-08.json`) |

Exam profile at 1683212, the 27 held answerable turns: 19 wait behind a root turn
(two English transfers the wrong-thing candidate excludes 4; three which-person
turns held as not stated or without a referent 5; two corrections the reader
returns nothing for 4; three Korean statements 5; the English use-up with a
pronoun 1); question not read 5; lookup 2; tie 1.

## Experiments 9 and 10

| # | Cause | Patch (commit) | Work | Wait | Regression | Frozen exam |
| --- | --- | --- | --- | --- | --- | --- |
| 9 | (exam, then diagnosed on invented sentences) a use-up is not read when a trailing phrase says what the things went to; the pronoun was not the blocker | b659a5f with 6797663, merged 564a97e | chat 35 min; plan manager 12 min | chat 33 min on runs; reported 18:27, merged 18:28, scored 18:34 | full suite on the merged tree 2,354 passed, the 3 known failures, 397 s; the chat's own suite had caught a dropped negation before its report | **82/108** (+1), statements 142 → 144 of 150, why 19 → 20 of 26, 0 wrong, 0 violations (`experiment-09.json`); dev v6 check 149 → 177/234 |
| 10 | (invented reproduction of the exam's which-person turns) a question whose holder words describe several holders is held instead of asked, and the reply after it is held behind itself | adc07f2, merged 5e9289a | chat 15 min; plan manager 8 min | chat 15 min on runs; reported 18:38, merged 18:41 after the suite of experiment 9, scored 18:46 | chat's full suite on the merged tree 2,323 passed, 1 known failure (gate files left out); gate files and reading tests at merge: 401 passed | **82/108, no turn changed its bucket**: the invented forms are not the exam's (`experiment-10.json`) |

The exam's which-person turns by masked shape: 12 turns, two candidates each, 5
held. None names a candidate; ten do not name the thing; nine have a pronoun and
three describe the person in other words. The held ones are held as `not_stated`
(English, a description without a pronoun) or `no_referent` (a pronoun). The turn
after is the person's reply, a candidate's name alone or with one or two words,
and it is held when the question before it was held.

## Experiment 11

| # | Cause | Patch (commit) | Work | Wait | Regression | Frozen exam |
| --- | --- | --- | --- | --- | --- | --- |
| 11 | (guessed from the token kinds of the exam's corrections) "the one" read as the amount 1; a correction of two sentences refused; the swap of giver and receiver | 90d6e61, merged 030d04c | chat 30 min; plan manager 8 min | chat 15 min on runs; reported 18:57, merged 18:58, scored 19:03 | chat's full suite on the merged tree 2,328 passed, 1 known failure (gate files left out); gate files and reading tests at merge: 406 passed | **82/108, no turn changed its bucket** (`experiment-11.json`) |

Two patches in a row were built from invented sentences and changed no exam turn.
From experiment 12 on the chats get, for each failing exam turn, the trace of the
steps that ran and what each returned, with the token kinds of the partial
reading: the place where the exam turn gives up, not a guess at its words.

## Experiment 12: which-person turns, from the exam's own trace

| # | Cause | Patch (commit) | Work | Wait | Regression | Frozen exam |
| --- | --- | --- | --- | --- | --- | --- |
| 12 | (exam trace) the five held which-person turns are read as a query and end at the pointer resolution (no referent) or at the lookup (not stated); the ask naming the candidates was never reached | 1cf66d0, 8f8c32b, 8b97d42, merged fc113ea | chat 20 min; plan manager 8 min | chat 25 min on runs; reported 19:50, merged 19:51, scored 19:55 | chat's full suite on the merged tree 2,333 passed, 1 known failure (gate files left out); gate files and reading tests at merge: 522 passed | **85/108 (78.7%)**, +3; which-person turns 7 → 12 of 12; Korean 39 of 54, English 46 of 54; 0 wrong, 0 violations (`experiment-12.json`). The chat named the turns it expected to move: the five which-person turns and the replies after them. All five moved, and three replies |

Exam profile at fc113ea, the 23 held answerable turns: 13 read and held behind an
earlier unread turn (six unrecorded statements and four held corrections are the
roots); 10 fail on their own: a total of two holders and a comparison, neither
read (2); very short Korean turns not read or tied (4); read as a query and held
at the lookup (3); one held as a protected repair.
