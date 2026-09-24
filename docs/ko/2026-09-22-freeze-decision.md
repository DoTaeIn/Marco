# Freeze decision — useful MARCO 1 first

Decided 2026-09-22 by the repository owner after an independent audit. **Every
session working on this repository reads this file before its goal file.** A
goal that touches a frozen area stops and reports; it does not "just add a bit".

## Frozen until MARCO 1 ships

| Area | What is frozen | What remains allowed |
| --- | --- | --- |
| POLO | All of it. `polo/`, host permission boundary (P1), workflows (G4, G5) | Nothing |
| MCO binary | The real `.mco` format, overlay, snapshot, consolidation (M1–M4) | `mco/` API shell stays as is: committed to branch `mco-package`, parked, not merged, not extended |
| Autonomous planning | Re-planning, tool making, self-modification (G6–G9), general planner | Existing `goal_runtime` registered tools stay as they are |
| ALMA advancement | Persona/social features (A1, A2), new ALMA modules, any ALMA goal after goal 1 | Goal 1 on the Windows machine finishes and merges. Existing ALMA tests keep passing |

Also frozen: the full five-phase repository refactor (plan file §4). Only the
read-only audit (S1) and the minimal skeleton the realizer needs (S2-min) run.

## What "useful MARCO 1" means (roadmap §12, stage 1)

A dialogue in a supported life or work domain where MARCO records state,
handles follow-ups, ellipsis, referents, corrections, and "why", in Korean and
English, and creates its sentences instead of picking them.

**Gate, fixed before implementation, not after:**

1. The fixed 7-step dialogue passes in both languages with the verbatim phrasings.
2. 50 or more unseen multi-turn dialogues, written before the realizer work and
   never used during development, score **90% or better** on answerable
   questions. A hold is not a correct answer. Unsupported, ambiguous, and
   correction cases are reported separately.
3. No confident answer without evidence, no use of retracted evidence, in any
   of the 50.
4. Sample count, composition, and the full failure list are published with the number.
5. **Composed, never picked (added 2026-09-24).** On the frozen 52, every spoken
   reply is composed by the realizer from a meaning, as its per-reply report
   shows. A graph node's own text may be quoted only inside a composed sentence.
   Measured by `bench/composition_gate.py` (goal F2), owner-run.
6. **Reasons (added 2026-09-24).** On the frozen reasoning set (100 or more
   structured problems in declared phrasings, `data/benchmarks/reasoning_v1/`),
   95% or better correct among parsed problems, 0 wrong, unparsed reported
   separately and at most 10%. Measured by `bench/reasoning_gate.py` (goal F2).

No storage format, test count, or refactor progress counts toward this gate.

## The queue (replaces plan file §2 items 3–5) — updated 2026-09-23

| # | Goal | File | State |
| --- | --- | --- | --- |
| S1 | Structure audit | `docs/architecture/structure-audit.md` | done, on `main` |
| F1 | Frozen dialogue set: 52 dialogues, scorer, baseline **3/108 (2.8%)** | `main` 986e753 | done |
| P0 | Integrate goal 2, park `mco/` | `main` 4adc504 | done |
| S2-min | Skeleton + `marco/language/` seam | `main` 78bd062 | done |
| S3 | Test hygiene and speed: parallel default, 211 s vs 1744 s, same 3 failures, corpus skips | `main` 344078c | done |
| D1 | Docs that tell the truth: README from scripts, 5 package docs, `tools/doc_facts.py` | `main` 366c630 | done |
| G1 | Understanding round 1: 50 dev dialogues, dev set **65/96 answerable, 0 wrong**, 29 commits of declared rules | `main` a8388e9 | done 2026-09-23. **Frozen round 1: 19/108 (17.6%)**, KO 9/54, EN 10/54, 87 holds, 1 wrong, 1 unverifiable (`docs/ko/dialogue-gate-2026-09-22/round1.json`). Dev 67.7% vs frozen 17.6%: the rules fit the dev set, not the language |
| W1 | Language realizer: R0–R8 done, seam composes 109/109 fixed replies, suite 898 passed / 1 known / 8 skipped, report `marco/language/W1-report.md` | `main`, merged 2026-09-23 | done. Open: W1-3 part 2 (negation marker as a pack component field) after G1 merges |
| G2 | Understanding round 2: 72 dev-v2 dialogues with a recorded build/check split; **check half 48/52 answerable (92.3%), record 66/68, 0 wrong**; build 101/104; repair safety 12/12 held; the four integration failures fixed; declarations 1,040 lines vs Python 687; round-1 dev set 66/96 | `main`, merged 2026-09-24 from 3237873 | done. Not met: answers name their subject (realizer ellipsis, request G2-1, folded into V1). **Frozen round 2: 21/108 (19.4%)**, KO 10/54, EN 11/54, record 81/150, 86 holds, 1 wrong, and two new gate-3 violations (one confident answer without evidence, one retracted-evidence use). Dev check half 92% vs frozen 19%: the second round in a row where a dev set did not transfer |
| F2 | Frozen reasoning set (114 problems, 63 ko / 51 en) + composition gate | `main` a7c20b2, merged 2026-09-24 | done. Reasoning baseline at 70ba9f8: 80/109 parsed (73.4%), 24 wrong, all the one-holder-count realizer bug G2 fixed; composition 71/71 on fixed sets. Round-2 runs of both gates recorded below |
| G3 | Understanding round 3: violations fixed, 1,200-word and 200-statement probes at 100%, dev v3 check half **94/106 (88.7%)** with disjoint vocabulary, 0 wrong, 0 violations; F2-2 declarations; 수선 → 수정 | `main` 60d796b, merged 2026-09-24 | done. **Frozen round 3: 21/108 (19.4%) again**, but 0 wrong, **0 violations (gate 3 met)**, record 82/150; composition **340/340 (gate 5 met)**; reasoning 148/151, 0 wrong (gate 6 met). Owner read the failing turns: the frozen set is natural adult language (zero and vague counts, lend/pass/hand/return/send, titles, relational nouns, first person, places as holders, fronting, partitives, referent repairs); every dev set so far was template output |
| G4 | Understanding round 4: dev v4 phrased by a local language model from structured scenarios, the natural-language classes above, statements first, places as holders, referent repairs | `docs/ko/2026-09-24-understanding-r4-goal.md` | running 2026-09-24, background agent |
| W3 | Realizer round 3: requests G3-1 to G3-4 (수선 tag, "1 knives", held-answer status, fewer/equal/before/after), plans for round-4 meanings, fluency sample 3 | `docs/ko/2026-09-24-realizer-r3-goal.md` | running 2026-09-24, background agent, alongside G4 |
| W2 | Realizer round 2: every reply through `realize()`, answers name their subject, why in words, repair notes to the trace, bare 왜?, fluency sample 2 | `main` 55fb2c8, merged 2026-09-24 | done. Frozen composition **339/340** (1 held, 0 passed through): gate 5 met. Dialogue score unchanged 21/108; reasoning unchanged 146/149 |
| C1 | Model comparison on the same frozen exams | `main` f621ba5, merged 2026-09-24 | done. MARCO 21/108, 0 invented, reasoning 0 wrong, 27 ms; Qwen2.5-7B 4-bit 75/108, 25 wrong, 5 invented, 22 reasoning wrong, 749 ms; GPT-2 1/108. In the README and the release notes |
| V1 (folded into G3.7 and W2.3–W2.5) | Spoken-reply cleanup (owner judged the 25-reply fluency sample natural except these): rename 수선 → 수정 in the Korean pack templates; move repair notes and rule ids (count_remove, count_add) out of the spoken reply into the trace, reachable by asking; bare 왜? handled like 왜 그렇게 됐어? | pack strings + realizer explain plan, small | after G2 merges |
| G3.. | Understanding rounds until the frozen gate reaches 90% | written per round | after each frozen run |

Known failures on `main`: two `test_response_composer` tests (machine-dependent)
and the macOS RSS assertion in the ALMA reproduction tests. At a8388e9 (G1 + W1
merged) four more appeared from their integration, assigned to G2.0(c)(d): a total
question answers 4 instead of 9 (`test_understanding_r1`), and the seam test pins
three answers G1 changed (`test_language_seam` ko-01, ko-02, ko-08). Suite there:
915 passed / 7 failed. Found by D1, not fixed:
`tests/test_dialogue_gate.py::test_f1_3` fails because `tests/test_language_seam.py`
shares a sentence with a frozen dialogue (W1 owns the fix); `target-map.json` gives
`marco` no layer; `tests/test_dialogue_etiquette.py` collects nothing.

**Ownership carve-out (2026-09-23):** W1 implements its own requests W1-1 and W1-2:
the result-building sites in `reasoning_context.py` (a language-free `meaning` key on
every result with `answer`, plus a stable conversation id) and the return points of
`engine.answer` routed through `realize()`. G1 keeps the parsing, repair, and matching
code in both files and writes a request instead of touching those sites.

**Exam rule:** the frozen 52 are scored once per round by the owner. No development
chat opens them or runs them. Development uses its own dev set (G1.1).

Parallel at most: four chats (raised from three by the owner on 2026-09-23). Each in its own hidden checkout under
the app's hidden worktrees folder inside the repository, never a sibling folder. The owner merges between goals.

**Principles note (2026-09-24):** the owner's design note
`docs/ko/2026-09-24-perception-reasoning-emotion-philosophy.md` restates the core as
"MARCO proves conclusions, not sensors": learned components may serve as sensors
whose output is an unverified observation with provenance. This changes no frozen
area and nothing before the gate; MARCO 1 keeps "no language model in the runtime".
The post-gate schedule for SOMA, ALMA affect, deliberation and audio is in
`docs/ko/2026-09-24-roadmap-after-marco1.md`.

## Unfreezing

Only the owner unfreezes, by editing this file and the plan file. A session
that finds a frozen area blocking its goal writes `docs/requests/<goal>-<n>.md`
and continues on what does not depend on it.
