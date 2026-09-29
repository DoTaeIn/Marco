# Understanding experiments — the log

One row per experiment. The loop (owner, 2026-09-29):
cause found → patch → regression → merge → frozen score → next cause.
Work time is the time the chat or the plan manager was changing or measuring.
Wait time is the time a finished patch sat before the next step (a permission
prompt, a merge, a score). Times are local, from commit and run timestamps.

| # | Structural cause | Patch (commit) | Work | Wait | Regression | Frozen exam | Remaining largest causes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 0 | baseline, main f88f679 | — | — | — | — | 63/108, 0 wrong, 0 violations | question itself unread 22; earlier statement unread 15; other 8 |
