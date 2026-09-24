# Roadmap after MARCO 1 — perception, affect, deliberation

Written 2026-09-24 by the plan manager from the owner's design note
`docs/ko/2026-09-24-perception-reasoning-emotion-philosophy.md`. Extended the same day
with the owner's adaptive-intelligence note (`2026-09-24-adaptive-intelligence-design.md`)
and the NERO compute-layer note (`2026-09-24-nero-compute-design.md`). It adds to the
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
| during MARCO 1 | **Q1 multi-query** `queries[]` (Diairesis): several user questions in one turn, answered in order | parsing side, an understanding-round class | nothing | a dev class in understanding round 5; frozen set unaffected |
| during MARCO 1 | **P-doc** README design principles rewritten to §24 of the philosophy note, and this roadmap linked | docs | nothing | docs only, one commit |
| done 2026-09-24 | **L1 trace ledger** (Hypomnema): declared schema, append-only JSONL ledger with DAG parents, adapter from the turn envelope, why chain, failure statistics | `marco/trace/` | — | merged; stats feed round 5 |
| round 5 | **L2 trace emission at the sites**: routing candidates and scores, rejected evidence, rule applications with bindings, pointer resolution, emitted where they happen. The hold reasons it records use the adaptive note's gap classes (routing, lexical, concept, relation, fact, rule, operator, representation, parser, evidence, conflict), so the self-repair work after the gate starts from measured gaps | `engine.py`, `reasoning_context.py` | L1, G4 merged | request L1-1 closed; every frozen-set turn replayable from its ledger |
| after round 4, before round 5 | **S4 file moves**: the 51 whole-file moves of the structure plan (phases 2, 4, 5) into `marco/`, `alma/`, `bench/`, `tools/`, `experiments/`; the 7 split files stay at the root | repository | G4 merged, nothing else open | root `.py` from 61 to about 8; suite unchanged; one day |
| T1 + 0 to 2 wk | **O0 Observation Graph contract**: Entity, Property, Relation, Event, State, Quantity, Time, Source, Confidence, Provenance, and the observation / hypothesis / verified-fact status; written as a schema with tests, and the existing text `transitions` shown to fit it | `marco/knowledge/` schema, docs | MARCO 1 | text dialogue re-expressed through the contract with identical gate scores |
| T1 + 0 to 6 wk | **M1–M3 MCO format**: native container, overlay, snapshot; the ledger stored and consolidated inside it | `mco/`, `marco/storage/` | O0 for the record schema | a real `.mco` that learns and restores across processes |
| T1 + 2 to 6 wk | **A1' ALMA affect layers** (Pathognosis): affect primitives → appraisal state → emotion concept hypothesis, ALMA's own state first; emotion state ≠ emotion word through the realizer | `alma/`, `marco/language/` plans | O0 | an appraisal trace for every affect-coloured reply; the same state said in both languages; no emotion label without a derivation |
| T1 + 2 to 8 wk | **R-A foreground self-repair** (adaptive note Part I, phase A): OpenProblem, Attempt, FailureSignature, gap diagnosis read from the ledger, internal gap vs knowledge gap, temporary problem-local repair (alias, routing hint, relation candidate, interpretation, rule candidate), retry of the original question with a progress check, no repeat without change; nothing admitted without replay of similar failures, counterexamples, unseen validation and regression, then the existing approval doors (Katalepsis) | `marco/learning/`, `marco/reasoning/` | L2 | on held answerable turns of a seen dev set, temporary repairs answer a measured share with 0 new wrong answers; every repair and its outcome in the ledger; the persistent candidates listed, none auto-admitted |
| T1 + 4 to 8 wk | **N1 NERO V1**: a `ReasoningBackend` contract (route, score, expand, match_rules, reduce), `CPUBackend`, backend selection contract, benchmark hooks; done together with the engine splits of the structure plan (phase 3), since both cut the same file | `nero/`, `marco/reasoning/` | S4, MARCO 1 | swapping the backend changes no proof on the frozen reasoning set; the benchmark table of note §30 recorded for CPU |
| T1 + 4 to 12 wk | **V1 SOMA blocks-and-hand** (Aisthesis): non-neural pipeline (edges, contours, optical flow, tracking) → Observation Graph; anonymous entities; events before identities; occlusion; "where did the red object go" and "did the hand move it" answered with observed / inferred / not proven | `soma/` | O0; POLO P1 for camera access | the philosophy note's §13 dialogue passes on recorded clips, with provenance from frame to answer |
| T1 + 6 to 10 wk | **D-lib deliberation levels**: low / medium / high budgets as declared exploration limits (NERO's FAST / DEEP / VERY_DEEP map onto them); measured compute vs explored paths vs accuracy on the frozen reasoning set | `marco/reasoning/` | N1 | a table with three budgets; no budget may lower the 0-wrong result |
| T1 + 6 to 12 wk | **C-core capability core** (Part II, phase C): `CapabilitySpec` ≠ runtime adapter, registry, Capability Graph (requires / provides / permission / effects / risk / provenance), lookup by need and output rather than by name; POLO's P1 permission boundary is the adapter boundary | `polo/`, `marco/cognition/` | POLO unfrozen at the gate, P1 | the existing registered tools re-declared as capabilities with identical behaviour; a missing premise resolved to a capability by `provides` |
| T1 + 8 to 14 wk | **A2' other minds**: others' affect as hypotheses from observed cues, revised by their own reports | `alma/` | A1', O0 | hypothesis with confidence, never a stored label; a report from the person revises it |
| T1 + 8 to 14 wk | **N2 NERO V2**: routing and candidate scoring on the GPU; on this machine the GPU path is Metal through MLX, not CUDA; the CPU / GPU crossover point measured; small problems stay on the CPU | `nero/` | N1 | same proofs on both backends; crossover table; fallback to CPU on any GPU failure |
| T1 + 8 to 16 wk | **R-B external acquisition** (phase B, Zetesis → Katalepsis): fact gap → research need → evidence with provenance → missing premise filled → the original question re-solved by MARCO; the search result is evidence, never the answer; the note's idle loop takes unresolved open problems | `marco/learning/` | R-A, C-core for the web capability | a knowledge gap on a seen dev question filled and re-solved with the evidence in its why chain; nothing enters the graphs without the approval door |
| T1 + 10 to 16 wk | **P-G persona compiler** (Part VI, phase G): a persona prompt → Self Graph (identity, background events, beliefs, values, goals, relationships, tendencies, knowledge, speech policy); mechanisms not labels (threat sensitivity, loyalty) ; World graph / Persona graph / Active state kept apart; belief revision with a trace | `alma/` | A1', O0 | the note's guard-captain example compiled and its beliefs revised by events with a trace; expression policy separate from knowledge |
| T1 + 10 to 18 wk | **V2 audio without text**: acoustic observation primitives, prototype matching / DTW for a small set of commands and sounds | `soma/` | V1 | a fixed command set recognised from audio into the Observation Graph, unknown for the rest |
| T1 + 12 to 20 wk | **C-mcp MCP and skill compilers** (phases D, E): MCP tool → capability candidate, resource → knowledge source whose reads are observations, prompt → workflow candidate; skill → procedure graph → action program; three stages (mechanical import, semantic grounding, behavioural validation in a sandbox); declared vs observed capability; unmapped steps kept as pending | `polo/` | C-core | one real MCP server and one skill compiled, validated in a sandbox, and used by a goal through the Capability Graph |
| T1 + 12 wk on | **N-sensor neural sensors behind the boundary**: detector / OCR / speech outputs enter as unverified observations | `soma/` adapters | V1 | a test that a detector claim never becomes a fact without a rule |
| T1 + 14 to 20 wk | **P-T task prompt compiler** (Part V, phase F): a task prompt → goal graph, constraints, priorities, permissions, output contract, completion condition, activation state ("be safe" raises risk nodes, "evidence weak, say nothing" raises the threshold); task-local assumptions never write the knowledge graph | `marco/cognition/` | C-core, D-lib | the note's review-repository example compiled; a task-local assumption visible in the trace and gone after the task |
| T1 + 14 to 20 wk | **N3 NERO V3**: graph frontier expansion and batch rule matching on the backend | `nero/` | N2 | same proofs; frontier and rule-matching latencies recorded |
| T1 + 14 to 24 wk | **E-dev development-aware emotion** (Part VII, phase H): one General Affect Core for every ALMA, a Development Profile of priors (regulation capacity, impulse control, time horizon, peer salience …) that experience revises, a regulation layer, emotional learning as procedural knowledge, state → habit → trait revision with provenance | `alma/` | A1', A2', P-G | the same event appraised differently by three personas with their derivations; age changes priors only, never selects an emotion; a regulation strategy learned from repeated outcomes |
| T1 + 20 to 28 wk | **N4 NERO V4**: parallel hypotheses, parallel repair evaluation, counterexample scanning; R-A's candidate repairs batched | `nero/` | N3, R-A | depth × breadth measured against accuracy at fixed latency |
| months 4 to 12 | **G6–G7 knowledge-gap research loop**, `user_goals[]` vs `generated_subgoals[]` (Bouleusis): R-A and R-B running unattended on accumulated open problems | `marco/cognition/` | R-A, R-B, C-mcp | unchanged from the integrated roadmap |
| unscheduled | **N5 NERO V5**: multi-GPU, remote compute, distributed partitioning, dynamic scheduler | `nero/` | N4 | — |
| done 2026-09-24 | **Licensing** (§26): `LICENSE` is now the MARCO Engine License 1.0 (Apache 2.0 + visible attribution in user-facing products, white-label on request), graphs CC BY 4.0 in `LICENSE-GRAPHS`, README and release notes updated | repository | owner's call, brought forward because a fork appeared | done; a legal review of the wording is still open, owner's item |

Ordering rule: O0 first, because every later item writes into it. V1 and A1'
can run in parallel: different packages, both reading O0. R-A needs the ledger
emitting inside the engine (L2) before it can diagnose anything. N1 rides on the
engine splits so the reasoning code is cut once, not twice. C-core comes before
every compiler and before R-B's web capability. Nothing here runs while the
understanding rounds are still open; the freeze holds until the gate.

## Principles adopted from the two notes of 2026-09-24, effective now

From `2026-09-24-adaptive-intelligence-design.md` §57: unknown is not the end;
search results are evidence, not truth; tool descriptions are declarations, not
guaranteed behaviour; prompt state never silently overwrites persistent
knowledge; a persona prompt is a seed, not a script; age is a developmental
prior, not an emotion selector; local success is not global knowledge; every
important change keeps provenance. From `2026-09-24-nero-compute-design.md`:
MARCO decides what reasoning means, NERO decides how it is computed; code may
be split by backend, intelligence may not; a backend swap changes no proof; a
compute failure is never a reasoning contradiction. None of these change a
frozen area or anything before the gate.

## What is explicitly not promised

General object recognition in natural scenes, free speech recognition, and
emotion from faces. The note says why: those need learned perception, which is
allowed only as a sensor, and the first versions are deliberately narrow so
that every answer keeps its provenance.
