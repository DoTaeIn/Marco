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
