# Parallel goals — reduced by the freeze decision (2026-09-22)

Superseded in scope by `docs/ko/2026-09-22-freeze-decision.md`. The earlier
six-goal version (W1–W6, one shared branch) is withdrawn.

## What runs, and when

| Goal | Chat | Starts | File |
| --- | --- | --- | --- |
| S1 audit | running | now | `2026-09-22-structure-audit-goal.md` |
| F1 frozen dialogue set | own chat | now | `2026-09-22-frozen-dialogue-set-goal.md` |
| P0 integration | own chat | now | `2026-09-22-p0-integration-goal.md` |
| S3 test speed | own chat | after P0 | `2026-09-22-test-speed-goal.md` |
| S2-min skeleton | own chat | after S1, P0 | `2026-09-22-s2-minimal-goal.md` |
| W1 realizer | own chat | after S2-min, F1 | `2026-09-22-realization-next-goal.md` |
| D1 docs | own chat | alongside W1 | `2026-09-22-docs-goal.md` |
| Gate loop | own chat | after W1 | written then |

Frozen, no chat: W2 MCO binary, W3 ALMA, W4 POLO, W5 document fixtures.

## Mechanics

- Each chat is opened from a task card posted by the plan-manager session, or
  by the owner. Each gets its own hidden checkout in the app's worktrees folder inside the repository
  on its own branch. No sibling folders.
- Model: the owner's chat model, effort high, set by the owner in the chat or by the
  plan-manager session after the chat exists.
- At most three chats at once.
- A chat commits only the paths its goal file lists, by name, author is the
  owner, no co-author lines, no assistant name. It does not push.
- The owner merges finished branches to `main` between goals and runs the
  full suite once per merge.
- Cross-goal needs go to `docs/requests/<goal>-<n>.md`, never into another
  goal's files.
