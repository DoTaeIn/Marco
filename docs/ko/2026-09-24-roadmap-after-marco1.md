# Roadmap after MARCO 1 — perception, affect, deliberation

Written 2026-09-24 by the plan manager from the owner's design note
`docs/ko/2026-09-24-perception-reasoning-emotion-philosophy.md`. It adds to the
integrated roadmap (`2026-09-22-mco-integrated-roadmap.md`) and changes nothing
in the freeze decision: everything below starts after MARCO 1 passes its gate,
except the items marked "during MARCO 1" (docs, one parser class, and the trace
ledger core, which is a new package with no engine edits).

## What the note changes in principle, effective now

- The stated core is no longer "no neural network". It is the seven rules of
  the note's §24: no unsupported fact, observation separated from fact,
  perception separated from reasoning, every conclusion traceable, unknown is
  a normal result, the status of assumption / observation / inference /
  verified fact is kept apart, and no generative model decides a reasoning
  result. Learned components are allowed as **sensors** whose output is an
  observation with source, model id, confidence, and `verified = false`.
- MARCO 1 keeps its stricter rule, no language model in the runtime, because
  the dialogue gate measures reasoning over text and a language model there
  would be a decider, not a sensor.
- The internal common language is the graph, not text. Text is one adapter.

## Timeline, weeks counted from the day MARCO 1 passes its gate (T1)

| Window | Item | Package | Depends on | Done when |
| --- | --- | --- | --- | --- |
| during MARCO 1 | **Q1 multi-query** `queries[]`: several user questions in one turn, answered in order | parsing side, an understanding-round class | nothing | a dev class in the next understanding round; frozen set unaffected |
| during MARCO 1 | **L1 trace ledger** (owner's note `2026-09-24-trace-logging-design.md`): declared schema, append-only JSONL ledger with DAG parents, adapter from the turn envelope, why chain, failure statistics | `marco/trace/` new | nothing | goal L1, running; the stats table feeds round 5 |
| round 5 | **L2 trace emission at the sites**: routing candidates and scores, rejected evidence, rule applications with bindings, pointer resolution, emitted where they happen | `engine.py`, `reasoning_context.py` | L1, G4 and W3 merged | request L1-1 closed; every frozen-set turn replayable from its ledger |
| during MARCO 1 | **P-doc** README design principles rewritten to §24, and this roadmap linked | docs | nothing | docs only, one commit |
| T1 + 0 to 2 wk | **O0 Observation Graph contract**: Entity, Property, Relation, Event, State, Quantity, Time, Source, Confidence, Provenance, and the observation / hypothesis / verified-fact status; written as a schema with tests, and the existing text `transitions` shown to fit it | `marco/knowledge/` schema, docs | MARCO 1 | text dialogue re-expressed through the contract with identical gate scores |
| T1 + 0 to 6 wk | **M1–M3 MCO format** (already in the roadmap): native container, overlay, snapshot | `mco/`, `marco/storage/` | O0 for the record schema | a real `.mco` that learns and restores across processes |
| T1 + 2 to 6 wk | **A1' ALMA affect layers**: affect primitives → appraisal state → emotion concept hypothesis, for ALMA's own state first; emotion state ≠ emotion word through the realizer | `alma/`, `marco/language/` plans | O0, W-round persona separation | an appraisal trace for every affect-coloured reply; the same state said in both languages; a test that no emotion label is ever written without a derivation |
| T1 + 4 to 12 wk | **V1 SOMA blocks-and-hand**: non-neural pipeline (edges, contours, optical flow, tracking) → Observation Graph; anonymous entities; events before identities; occlusion; "where did the red object go" and "did the hand move it" answered with observed / inferred / not proven | `soma/` | O0; the roadmap's P1 host permissions for camera access | the note's §13 dialogue passes on recorded clips, with provenance from frame to answer |
| T1 + 6 to 10 wk | **D-lib deliberation levels**: low / medium / high budgets as declared exploration limits; measured compute vs explored paths vs accuracy on the frozen reasoning set | `marco/reasoning/` | MARCO 1 | a table with three budgets; no budget may lower the 0-wrong result |
| T1 + 8 to 14 wk | **A2' other minds**: others' affect as hypotheses from observed cues, revised by their own reports | `alma/` | A1', O0 | hypothesis with confidence, never a stored label; a report from the person revises it |
| T1 + 10 to 18 wk | **V2 audio without text**: acoustic observation primitives, prototype matching / DTW for a small set of commands and sounds | `soma/` | V1 | a fixed command set recognised from audio into the Observation Graph, unknown for the rest |
| T1 + 12 wk on | **N-sensor neural sensors behind the boundary**: detector / OCR / speech outputs enter as unverified observations | `soma/` adapters | V1, the §11 rules as tests | a test that a detector claim never becomes a fact without a rule |
| months 4 to 12 | **G6–G7 knowledge-gap research loop**, `user_goals[]` vs `generated_subgoals[]` (already in the roadmap) | `marco/cognition/` | POLO P1, G4/G5 | unchanged from the integrated roadmap |
| with O0, A1', V1, D-lib, M1–M3 | **Trace extensions** (note §24–§31): observation events with source provenance in O0; SOMA perception trace with V1; appraisal and mental-state scope with A1'; budget trace with D-lib; goal and subgoal branches with G6–G7; the ledger stored and consolidated inside the `.mco` with M1–M3 | each item's package | L1 | each item's done-when includes its trace; no item ships a label without a derivation |
| done 2026-09-24 | **Licensing** (§26): `LICENSE` is now the MARCO Engine License 1.0 (Apache 2.0 + visible attribution in user-facing products, white-label on request), graphs CC BY 4.0 in `LICENSE-GRAPHS`, README and release notes updated | repository | owner's call, brought forward because a fork appeared | done; a legal review of the wording is still open, owner's item |

Ordering rule: O0 first, because every later item writes into it. V1 and A1'
can run in parallel: different packages, both reading O0. Nothing here runs
while the understanding rounds are still open; the freeze holds until the gate.

## What is explicitly not promised

General object recognition in natural scenes, free speech recognition, and
emotion from faces. The note says why: those need learned perception, which is
allowed only as a sensor, and the first versions are deliberately narrow so
that every answer keeps its provenance.
