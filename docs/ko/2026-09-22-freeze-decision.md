# Freeze decision — useful MARCO 1 first

Decided 2026-09-22 by the repository owner after an independent audit. **Every
session working on this repository reads this file before its goal file.** A
goal that touches a frozen area stops and reports; it does not "just add a bit".

## Frozen until MARCO 1 ships

| Area | What is frozen | What remains allowed |
| --- | --- | --- |
| POLO | All of it. `polo/`, host permission boundary (P1), workflows (G4, G5) | Nothing |
| MCO binary | Consolidation, compaction, scaling measurements and device profiles. Unfrozen on 2026-10-01 as storage and runtime infrastructure only: the binary format, the persistent overlay, the snapshot (see "MCO scope for MARCO 1" below) | The scope below, and nothing in it that makes MARCO learn |
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

## Owner-fixed timeline (2026-09-29)

`docs/ko/2026-09-29-marco-fixed-timeline.md` fixes the order of the phases:
M1 (MARCO 1 language gate) → MARCO 1 release → M2 self-improving → M3 capability →
M4 goal / prompt → A1 → A2 → S1 → P1 → N1. A new idea is placed under a phase; it
never reorders them. Where an older roadmap disagrees on order, this file wins.

- **One track until gate 2 passes (owner, 2026-09-29).** Only understanding rounds
  run. No realizer, docs, trace, refactor or storage round starts before the gate;
  a request from an understanding round to another area is answered inside that
  round or waits.
- **Names.** Understanding rounds are UR<n>. UR7 is the round written as G7
  (chats G7-Q and G7-S, requests `G7-<n>.md`); its names stay until it merges. The
  next round is UR8. In the fixed timeline M1 to M4 are MARCO phases; the storage
  milestones this file calls "MCO binary M1–M4" are not those.
- **Merging (owner, 2026-09-29).** The plan manager merges a round's branch into
  `main` when its regression list passes on a re-run, scores the frozen sets the
  same day, and writes the next round from the cause counts. Pushing stays the
  owner's.
- **Placed under MARCO 1 release: a fresh exam.** The frozen 52 were never shown
  as sentences, but seven rounds were written from their failing classes. Before
  the release, 50 or more new dialogues written outside the development chats
  (`data/benchmarks/dialogues_v2/`, frozen on arrival) are scored once. The gate
  number stays the frozen 52; the fresh score is published beside it.
- **Effort and ranking (UR7 amendments A2, A4)** are sub-items of M1's candidate
  readings: a bound on the search and an order on its survivors. Owner's limit
  (2026-09-29): effort level 3 is turn-local deliberation only. No persistent
  learning, no permanent repair, no external research, no OpenProblem promotion.
- **Experiments, not rounds (owner, 2026-09-29).** An understanding round is one
  hypothesis tested, not a schedule. The loop is fixed: cause found → patch →
  regression → merge → frozen score → next cause. Failures are grouped by
  structural cause; one cause is fixed and the whole exam is scored again at
  once. A patch whose regression passes is merged and scored the same day
  without waiting for a hand-off. No round count and no date is estimated ahead.
  At 90% or better the next step is gate verification; below it, the remaining
  failures are grouped again and only the one to three largest structural causes
  go into the next experiment. Graph grounding is built only as far as the gate
  needs: identity, referent and frame grounding. Documents describe the work and
  never hold it up. Work time and wait time are logged apart in
  `docs/ko/2026-09-29-experiment-log.md`. This replaces "scored once per round"
  in the exam rule: the plan manager scores after every merge, and still only
  the plan manager; development chats never open or run the frozen sets.
- **Nodes, not strings (owner, 2026-09-30).** The frozen exam at 90 of 108 is the
  frozen baseline (tag `ur7-baseline-90`). No further patch on the string-key
  route. The rest of M1 goes: minimal conversation identity graph → reader partial
  candidates grounded to nodes → state, corrections and lookup by id →
  re-verification of every existing pass → frozen exam → gate.
  `docs/ko/2026-09-30-conversation-identity-graph.md`.
- **The fresh exam is written (2026-09-30).** Frozen dialogue set v2: branch
  `fresh-exam-v2`, commit `f4f52f3`, 52 dialogues (26 Korean, 26 English), 340
  turns, 108 answerable, the label counts of v1 exactly, 0 validator problems, 0
  sentences shared with the repository. Written by a chat that saw neither v1 nor
  any trace. It stays on its branch, unmerged and unread, until the release; no
  development chat checks that branch out, and the plan manager scores it once.
- **Placements decided by the owner (2026-09-29), top-level order unchanged:** the
  real MCO format under MARCO 1 release, before M2; the Observation Graph Contract
  at the end of M2, before M3; M3 owns capability declaration, discovery, binding
  and the permission contract, P1 owns side-effectful execution and enforcement,
  and today's bounded read-only research stays as it is. Gate condition 4
  (sample count and full failure list published) stands; the fixed timeline's
  first version had dropped it by accident.

## MCO scope for MARCO 1 (owner, 2026-10-01)

The fixed timeline is authoritative for the MCO storage and runtime infrastructure only. It does not lift
the freeze on MARCO's learning or reasoning behaviour. The top-level timeline does not change.

In MARCO 1:

- the real binary `.mco`, with stable non-positional ids;
- compile, run, inspect;
- a persistent overlay format, and the application of graph and rule changes that are explicit or approved
  from outside;
- provenance;
- validation of the base hash and build id;
- conversation snapshot and restore.

Not in MARCO 1: autonomous persistent learning, learning verbs from conversation, promotion of a
self-repair, automatic rule creation, automatic graph mutation from dialogue, promotion of web or document
knowledge, and any reasoning or language change needed to learn persistently.

The second slice is named **Persistent Overlay Infrastructure**, not learning. MARCO 1 can store and apply
approved graph changes; M2 decides how MARCO itself discovers, validates and promotes such changes. The
snapshot is in MARCO 1 because it is state and persistence infrastructure. The existing learning routes
(the sidecars beside each graph, the approval door, the pack export) stay as they are and are not moved
onto the overlay before M2.

| Slice | Content | State (2026-10-01) |
| --- | --- | --- |
| 1 | Format 1 specification, writer and reader, compile, run, inspect, stable ids, base identity | merged `99cc0c8` |
| 1, tables | Format 1.1: node, edge and rule tables, every graph equal to the engine's reading; not yet on the running path | merged `1a56bb5` |
| 2 | Persistent Overlay Infrastructure: store bound to a base, atomic commit, deltas and tombstones, candidates kept apart until approved from outside | merged `bbd4d3c` |
| 2, view | Merged graph and rule view with origins, application at the next turn with no recompile, `mco overlay` | merged `eca0367` |
| 3 | Snapshot and restore: base and overlay sequence recorded and checked, conversation state | merged `d734447`, overlay recorded since `eca0367` |
| later | Consolidation into a new base, compaction, scaling curves, profiles, the engine reading the tables directly | after the release |

## Gate declared, release freeze (owner, 2026-10-01)

Gate 2 is declared passed at 98 of 108, 0 wrong, 0 violations; all six conditions are measured as met
(`python tools/doc_facts.py frozen --run graph-step-3s6`). MARCO 1 is a completed first-generation
architecture, not a target for further capability expansion.

- No more exam-targeted coverage work. The remaining held turns stay held.
- Before the release, a reasoning change is allowed only for a demonstrated safety or correctness bug that
  can produce a wrong or unsupported state or answer. Allowed and in work: one thing counted in two units
  (the second count replaced the first). Stopped: the Korean restated swap, whose only purpose was a held
  exam turn; parked for M2.
- Snapshot and persistence work continues inside the approved MCO scope; the test-cache race continues as
  test infrastructure.
- Real-text reading moves to M2. The SVAMP result is published as a known limitation of MARCO 1
  ([2026-10-01-svamp-accuracy.md](2026-10-01-svamp-accuracy.md)).
- Efforts 4 (multi-hop graph grounding) and 5 (bounded multi-hypothesis search) move to M2.
- The history rewrite that removes the attribution line of `d81f2d0` is done before the release tag,
  changing no code and no measured behaviour; the release head is verified after it and that history is
  tagged.
- The release checks are re-run once after the last allowed change, before the tag.
- MARCO 1 is published with its limits stated: narrow language and domain coverage, the SVAMP real-text
  reading result, no autonomous learning, no effort 4 or 5, persistent overlays as infrastructure and not
  self-learning.
- After the release, M2 begins.

## Path to the tag (owner, 2026-10-01, evening)

Four wrong answers were found on invented sentences after the declaration (an unread sentence dropped as
changing nothing; an unread correction whose second sentence names a holder; a count answered while a
which-event question is open; a readable first sentence lost when the turn's second sentence is not read).
With the first three fixed the exam scores 97 of 108, 0 wrong, 0 violations: one English answer after a
request went back to a hold, because MARCO did not recognise the request as one and the old rule had
guessed that the unread sentence changed nothing.

The owner's decision: keep the fixes, and allow the minimal positive request recognition needed to meet the
gate honestly, as the completion of that safety fix and not as language expansion. After it no capability or
coverage is added to MARCO 1. The remaining release blockers, and nothing else:

1. merge and verify the known wrong-answer safety fixes;
2. complete the two-unit count safety fix;
3. add the minimal request recognition;
4. re-run the final release checks;
5. score the fresh exam once and publish the result as measured;
6. the `d81f2d0` history rewrite;
7. the release tag.

The frozen gate must finish at 98 of 108 or better with 0 wrong and 0 evidence violations. If the minimal
request recognition does not recover it, work stops and the reason is reported before any other language
feature is added. No exam-score chasing after this.

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
| G4 | Understanding round 4: dev v4 phrased by a local language model from structured scenarios, the natural-language classes above, statements first, places as holders, referent repairs | `main`, merged 2026-09-25 from 922f551 (24 commits) | done, stopped by the guard: check half answerable 220/330 = 66.7% (target 70), records 340/384 = 88.5% (target 90), 0 wrong, 0 violations, check trailed build by 25 points from batch 3 (seen only after batch 11: the check half was phrased late). Dev v4: 192 dialogues (ko 104, en 88; build 97, check 95), declarations +2,501 lines vs Python +941. **Frozen round 4: 40/108 (37.0%)**, KO 20/54, EN 20/54, 0 wrong, 0 violations, record 115/150; composition 340/340; reasoning 148/151 PASS. Requests G4-1 (seven W3 tests re-pinned by the owner at merge; recipient-correction plan → W5), G4-2 (→ W5). Suite on merged main e16b3fb: 1,645 passed, the three known machine-dependent failures (macOS RSS, two response_composer), one flaky under parallel load that passes alone |
| W3 | Realizer round 3: requests G3-1 to G3-4 closed (수선 gone, "1 knife", held answers become holds, fewer/same/tie/before/after composed), plans for round-4 meanings (user as holder, places, titled and relational holders, zero, vague counts; 59 tests), request W3-1 tells G4 the meaning fields those plans expect, fluency sample 3 (40 replies), suite 1,407 / 1 known / 8 | `main` 0edfd2b, merged 2026-09-24 | done. Frozen after W3 (`after-w3.json` in both report folders): dialogue **21/108 unchanged**, 0 wrong, 0 violations; composition **340/340**; reasoning 148/151, gate 6 PASS. Scorer fix ead6302: a local in the overlap loop shadowed `status()` and crashed every non-quiet run |
| L1 | Trace ledger: declared schema, append-only JSONL event ledger with DAG parents, adapter from the turn envelope, why chain, failure statistics; emission at the engine sites deferred to round 5 as request L1-1 | `docs/ko/2026-09-24-trace-ledger-goal.md` | done, merged 2026-09-24 from e07f1c9. 35 kinds and 9 statuses declared, 96 tests; seven-step dialogue in both languages: every event has a parent, replay identical twice; recording costs 0.2–0.3 ms per turn, ~4.5 KB per turn, off by default. Dev3 stats: 198/210 answerable said, 12 held (9 waiting on an earlier unread turn, 3 on their own words), record 179/182 = 98.4%, 0 answers without evidence, 0 on withdrawn evidence. Requests L1-1 (20 engine sites + 4 envelope gaps, for round 5) and L1-2 (what a spoken why needs). Doc `docs/architecture/trace-ledger.md` |
| S4 | File moves, no shims: the 51 whole-file rows of the target map moved into packages with every reference rewritten in the same commit; root 61 → 8; the seven split files stay | `docs/ko/2026-09-24-file-moves-goal.md` | written 2026-09-24; runs alone after G4 merges and before round 5, on the owner's go. Partially unfreezes the refactor: phases 2, 4, 5 for whole files; phase 3 splits stay frozen. Done 2026-09-28, on `main` and pushed (40bad53): 53 files in six batches of at most nine plus three commits (files that go with them, `.marco/`, docs); root 61 → 8; 1,041 references rewritten; full suite 2214 passed with main's 4 known failures; dev3 202/210, dev4 check 268/323, dev6 check 109/234, every turn identical to main; 7 layer edges left for the split phase (structure-audit A8). |
| W4 | Realizer round 4: "why" composed from the trace graph's why chain (request L1-2), both languages, CLI and API, fluency sample of explanations; live-dialogue wiring as request W4-1 for round 5 | `docs/ko/2026-09-24-realizer-r4-goal.md` | done, merged 2026-09-24 from f5da807 (43 minutes). `chain_meaning` + plans for `chain` and `chain_hold` (15 declared hold reasons), 40 of 40 seven-step explanations composed, four injected faults caught, `python -m marco.trace why … --say`, `say_why()`, `last_explainable()`, fluency-sample-why.md (30), suite 1,572 / 1 known / 8, 69 new tests. Requests W4-1 (live why at `_explain_last`, round 5) and W4-2 (trace side of the report fields). Known limit: totals and comparisons explain the counts read, not the sum or winner, because the ledger records only the counts. Frozen after W4 (`after-w4.json`, both folders): dialogue 21/108, 0 wrong, 0 violations, 0 changed turns; composition 340/340; reasoning 148/151, gate 6 PASS |
| D2 | Docs round 2: README to the current truth (composed never picked, after-w3 numbers via `tools/doc_facts.py frozen`, canonical names), principles §24 + §57, `mco` on PyPI, docs index complete, `marco.trace` package doc | `docs/ko/2026-09-24-docs-r2-goal.md` | done, merged 2026-09-24 from dcb1534 (44 minutes). README rewritten to the current truth, gate table 1–6 from the after-w3 reports, `tools/doc_facts.py frozen / index / layout` (+7 tests), docs index lists all 226 documents, `marco.trace` and realizer package docs current, mco 0.1.0 documented, release notes. Found: the engine writes `그래프쓰임.json` at the repository root and any local run can flip `test_general_knowledge_coverage` (S4 fixes); the target map has 53 whole-file moves with three shared targets (S4 goal corrected) |
| G5 | Understanding round 5, the hybrid scope of the owner's compositional design: the blocking classes the G4 way (transfer verbs, place and relation holders, "only", fronting, question forms) plus readings as candidates validated by state and constraints with ask / hold; both check halves phrased before any fix; multi-query class; W4-1 live why; L1-1 minimum emission with gap classes | `main`, merged 2026-09-25 from ca64770 (23 commits) | done, every target met: check halves v4+v5 records 804/870 = 92.4%, answerable 576/688 = 83.7%, 0 wrong of 1,641 turns, 0 violations, gap 11.0 (max 14.5 at batch 3). Dev v5: 240 dialogues, 40 scenarios × 3 phrasings; readings as candidates with 8 ordered constraints: wrong dev turns → holds or asks 23 → 0, agreeing-and-correct triples 12 → 29 of 40; the ledger emits from the engine sites with a gap class on every hold; live why from the trace graph; multi-query 10 + 10 cases. Declarations 891 vs Python 394 in the batches. Suite 1,778 / 1 known / 8. **Frozen round 5: 45/108 (41.7%)**, KO 22/54, EN 23/54, 0 wrong, 0 violations, record 120/150; composition 340/340; reasoning PASS. Check 83.7% vs frozen 41.7%. The owner then recorded the exam through the ledger and read the failing turns at class level: 29 unread statements (counts as words and native numerals, English double-object and particle-verb transfers, partitive pronouns, a count in a following fragment, Korean transfer compounds, a few holder forms) cascade into most of the 63 held questions; 29 questions unread (leftover forms, time adverbs, topic-switch ellipsis, repair-plus-question turns); all 26 why turns held because the exam's why names the holder and the number. The dev generator never produced these forms. Round 6 is written from that list Request G5-2 (2 realizer items, 9 reading items) |
| W5 | Realizer round 5: recipient-correction plan (G4-1), the Korean user in totals and as recipient (G4-2), W4-2 trace fields, fluency sample 5, plans for G5's meanings | `main`, merged 2026-09-25 from c6bf448 (56 minutes, 8 commits) | done. Recipient corrections name the two receivers (G4-1), the Korean user left unsaid with the honorific verb in totals, comparisons and as recipient (G4-2; dev4 holds 4 → 0), `output_created` carries act, reason and plan (W4-2), fluency sample 5 (40), plans for two answers in one turn and "did you mean A or B?"; composition dev 269/269, dev4 1,542/1,542; suite 1,708 / 1 known / 8. Requests W5-1, W5-2 (field names, to G5), W5-3 (a relative clause misread as holder words now said; the engine names a different unread statement from run to run, to G5), W5-4 (runtime release stamp). Frozen after W5 (`after-w5.json`, both folders): 40/108, 0 wrong, 0 violations, 0 changed turns; composition 340/340; reasoning PASS |
| G6 | Understanding round 6 from the owner's ledger read of the exam (classes only): counts as words, double-object and particle-verb transfers, partitive pronouns, fragment counts, Korean transfer compounds, remaining holder forms; leftover / time-adverb / other question predicates, topic-switch ellipsis, repair-plus-question turns, cross-language turns; why with a restated fact (0 of 26 today); G5-2 items; determinism | `docs/ko/2026-09-25-understanding-r6-goal.md` | done in part, 2026-09-28, outside the goal's order (no dev set v6 before the first fix; S4 not run first). Done: a transfer to a holder whose count was never said, counts as words and hyphened number words, partitives, fragment counts, Korean transfer compounds, leftover questions, repair with the question in the same turn, why with a restated fact (G6.4), the parse speed fixes of the profile note, the withdrawn-evidence check (G6.0b: the ledger's adapter was wrong, the gate's 0 was right), the deterministic hold (W5-3 b), dev set v6 tooling and scenarios with outside phrasings (204 dialogues). Not done: G5-2 items 3, 4, 5b, 8, 9, 11; cause tables (G6.2); the v4+v5+v6 targets of G6.5. Dev v6 check half after: answerable 109/234 (46.6%), records 381/434 with 0 recorded wrongly, 0 wrong, 0 violations; before (main dfd749a) 112/234, 5 recorded wrongly. **Frozen round 6: 63/108 (58.3%)**, KO 33/54, EN 30/54, 0 wrong, 0 violations, record 138/150, why 18/26, correction 12/18 (`docs/ko/dialogue-gate-2026-09-22/round6.json`, code 11b110b, run on Windows with the two frozen-hash tests failing on line endings). Composition and reasoning gates not run this round |
| W6 | Realizer round 6: G5-2 items 1–2, why with a named holder, the runtime release stamp, fluency sample 6 | `docs/ko/2026-09-25-realizer-r6-goal.md` | done 2026-09-28: W6.1 to W6.5, requests G6-2 and G6-3; composition unchanged on the fixed and dev sets; fluency sample 6 not yet judged by the owner |
| G7 | Understanding round 7, two chats in parallel: G7-Q reads questions as a frame plus slots with declared modifiers and follow-ups as partial frames, and a generated question grid; G7-S fixes the statement classes that cascade (Korean transfers judged `invalid`, the giver-omitted continuation, partitive use-ups, English appositive holders) | `docs/ko/2026-09-29-understanding-r7-goal.md` | written 2026-09-29 from the owner's cause count at 2145028 (frozen 63/108 unchanged after S4; of 45 held answerable, 22 are the question itself unread, 15 wait on an unread statement; dev v6 check 109/234, 43 and 64). Targets: grid 95%, dev v6 check unread questions 43 → 5, unread statements 53 → 15, answerable 70% after both merge |
| W2 | Realizer round 2: every reply through `realize()`, answers name their subject, why in words, repair notes to the trace, bare 왜?, fluency sample 2 | `main` 55fb2c8, merged 2026-09-24 | done. Frozen composition **339/340** (1 held, 0 passed through): gate 5 met. Dialogue score unchanged 21/108; reasoning unchanged 146/149 |
| C1 | Model comparison on the same frozen exams | `main` f621ba5, merged 2026-09-24 | done. MARCO 21/108, 0 invented, reasoning 0 wrong, 27 ms; Qwen2.5-7B 4-bit 75/108, 25 wrong, 5 invented, 22 reasoning wrong, 749 ms; GPT-2 1/108. In the README and the release notes |
| V1 (folded into G3.7 and W2.3–W2.5) | Spoken-reply cleanup (owner judged the 25-reply fluency sample natural except these): rename 수선 → 수정 in the Korean pack templates; move repair notes and rule ids (count_remove, count_add) out of the spoken reply into the trace, reachable by asking; bare 왜? handled like 왜 그렇게 됐어? | pack strings + realizer explain plan, small | after G2 merges |
| G5 (plan B) | Compositional input understanding: candidate readings kept until validated by state and reasoning, canonical frames, ask / hold on ambiguity; G4's declarations promoted to primitives; dev-v4 scenarios as the gold benchmark | `docs/ko/2026-09-25-g5-compositional-understanding-design.md` | decided 2026-09-25 by round 4's 40/108: the hybrid scope, written into G5 |
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
the result-building sites in `marco/reasoning/context.py` (a language-free `meaning` key on
every result with `answer`, plus a stable conversation id) and the return points of
`engine.answer` routed through `realize()`. G1 keeps the parsing, repair, and matching
code in both files and writes a request instead of touching those sites.

**Exam rule:** the frozen 52 are scored once per round by the owner. No development
chat opens them or runs them. Development uses its own dev set (G1.1).
**Data rule (owner, 2026-09-25):** synthetic practice sentences may be generated by
external models or services; the frozen exam data, `data/benchmarks/dialogues_v1/`
and `reasoning_v1/`, never leaves the machine and is never shown to any model, local
or remote. An external phrasing source receives scenarios and class descriptions
only, its output passes the same checker, the scenario stays attached to every
sentence, and the source's name and date are recorded as data.

Parallel at most: four chats (raised from three by the owner on 2026-09-23). Each in its own hidden checkout under
the app's hidden worktrees folder inside the repository, never a sibling folder. The owner merges between goals.

**Principles note (2026-09-24):** the owner's design note
`docs/ko/2026-09-24-perception-reasoning-emotion-philosophy.md` restates the core as
"MARCO proves conclusions, not sensors": learned components may serve as sensors
whose output is an unverified observation with provenance. This changes no frozen
area and nothing before the gate; MARCO 1 keeps "no language model in the runtime".
The post-gate schedule for SOMA, ALMA affect, deliberation and audio is in
`docs/ko/2026-09-24-roadmap-after-marco1.md`. The owner's trace-logging note
`docs/ko/2026-09-24-trace-logging-design.md` is implemented in two parts: the
ledger core now (L1, a new package, no engine edits), emission at the engine
sites in round 5.
Two more owner notes of the same day, the adaptive-intelligence architecture
(`docs/ko/2026-09-24-adaptive-intelligence-design.md`: self-repair, research, capability
graph, compilers, persona, development-aware emotion) and the NERO compute layer
(`docs/ko/2026-09-24-nero-compute-design.md`), are scheduled entirely after the gate in
the roadmap. Self-repair and capability work fall under the frozen autonomous-planning
and POLO areas until then; NERO is a new family member with no code yet.

**Standing decision (owner, 2026-09-25):** no token-based model in MARCO's runtime,
not as a decider and not as a sensor for language. This is permanent, not a MARCO 1
rule. If the understanding rounds stall, the only allowed fallback is to scale the
build-time data tool (a local model phrasing scenarios, declarations induced from
them by script) while the runtime stays model-free. The roadmap's post-gate
"neural sensors behind the boundary" row is for perception only and each sensor is
the owner's decision.

## Unfreezing

Only the owner unfreezes, by editing this file and the plan file. A session
that finds a frozen area blocking its goal writes `docs/requests/<goal>-<n>.md`
and continues on what does not depend on it.
