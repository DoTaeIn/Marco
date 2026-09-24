# Documentation

Every document under `docs/`, one line each. The project overview, the measured
numbers and the release status are in the root [README](../README.md).
`python tools/doc_facts.py index` prints how many documents under `docs/` this
page does not link; it prints `0` when the index is complete, and `-v` names
them. Updated 2026-09-24 (goal D2).

Where to start: [the names of MARCO](en/pipelines.md) for the concepts, the
[freeze decision](ko/2026-09-22-freeze-decision.md) for what is being built now
and how it is judged, the [package documents](#architecture-docsarchitecture)
for the code.

## Architecture (`docs/architecture/`)

One document per package. Each carries the five template headings in order:
Purpose, Owns, Does not own, Depends on, Public interface.
`python tools/doc_facts.py packages` prints how many packages lack one (`0`).

| Document | Package |
| --- | --- |
| [marco.md](architecture/marco.md) | `marco`, the core package and its subpackages |
| [marco.language.md](architecture/marco.language.md) | `marco.language`, the language seam: `realize` |
| [marco.language.realizer.md](architecture/marco.language.realizer.md) | `marco.language.realizer`: Hermeneia, the language realization pipeline, and the semantic check of Palinorrhesis |
| [marco.trace.md](architecture/marco.trace.md) | `marco.trace`: Hypomnema, the provenance ledger |
| [mco.md](architecture/mco.md) | `mco`, the public API and CLI (0.1.0 on PyPI) |
| [mco.backends.md](architecture/mco.backends.md) | `mco.backends`, the runtime extension API |

| Document | What |
| --- | --- |
| [naming.md](architecture/naming.md) | Canonical naming, revision 2: ten pipeline names, four reserved, six structural names, and the rules for using them (the owner's) |
| [trace-ledger.md](architecture/trace-ledger.md) | The trace ledger in detail: the event table, the ledger rules, cost per turn, replay, the round-3 failure statistics (goal L1) |
| [structure-audit.md](architecture/structure-audit.md) | Structure audit of commit `6195040`: root files by subsystem, import graph, `engine.py` parts, target layout, phase plan |
| [target-map.json](architecture/target-map.json) | Target package for every root module, with layers and split ranges; read by `tools/import_graph.py` and `tools/doc_facts.py layout` |

## English (`docs/en/`)

| Document | What |
| --- | --- |
| [README.md](en/README.md) | Index of the English documents |
| [pipelines.md](en/pipelines.md) | The names of MARCO: ten pipelines and six structural concepts, what each does and where it stands today |
| [development.md](en/development.md) | Development guide: how the graph-grounded engine maps a statement to evidence and a conclusion |
| [graph-authoring.md](en/graph-authoring.md) | Graph authoring guide: claims, evidence and the relations that reach a conclusion |
| [design.md](en/design.md) | Design record: constrained, inspectable reasoning |
| [direction.md](en/direction.md) | Project direction: every conclusion traceable to evidence |
| [explain.md](en/explain.md) | Explanation-engine guide (`explain.py`) |
| [legal-theory.md](en/legal-theory.md) | Legal-theory guide: the reusable legal layers in `legal/` |

## `mco` (`docs/mco/`)

| Document | What |
| --- | --- |
| [README.md](mco/README.md) | User guide and PyPI page: install, the `marco` extra and `MCO_MARCO_ROOT`, the preview model, Python API, CLI, the `.mco` file, what 0.1.0 cannot do |
| [api.md](mco/api.md) | Stability contract (API version 1), the compatibility container, how to write a backend |

## Releases (`docs/releases/`)

| Document | What |
| --- | --- |
| [2026-09-24-marco-1-preview-1.md](releases/2026-09-24-marco-1-preview-1.md) | MARCO 1 · Preview 1: the `MARCO-1-preview.mco` file on the GitHub pre-release, its measured numbers at round 2 |
| [2026-09-24-mco-0.1.0.md](releases/2026-09-24-mco-0.1.0.md) | `mco` 0.1.0 on PyPI: what the package is, what it needs, what it cannot do yet, the license |

## Archive (`docs/archive/`)

| Document | What |
| --- | --- |
| [2026-09-24-root-cleanup.zip](archive/2026-09-24-root-cleanup.zip) | Retired root files, archived when the root was tidied on 2026-09-24: the old handoff document and the self-learning logs (`python -m zipfile -l` lists them) |

## Requests between goals (`docs/requests/`)

A goal that finds work outside its ownership writes a request; the owner of
that code closes it.

| Document | What |
| --- | --- |
| [F2-1.md](requests/F2-1.md) | "More" and "total" answers composed from one holder's count (all 24 wrongs of the reasoning baseline) |
| [F2-2.md](requests/F2-2.md) | Reasoning kinds no pack can express, and declared forms not recorded |
| [G1-1.md](requests/G1-1.md) | The seam test pinned pre-G1 answers for five unseen phrasings |
| [G1-2.md](requests/G1-2.md) | Result-building sites G1 touched in `reasoning_context.py` |
| [G2-1.md](requests/G2-1.md) | An answer must name whose count it is |
| [G3-1.md](requests/G3-1.md) | The realizer's own repair tag still said 수선 |
| [G3-2.md](requests/G3-2.md) | A count of one said in the plural, or held, for irregular nouns |
| [G3-3.md](requests/G3-3.md) | An answered turn whose realized reply holds was still "answered" |
| [G3-4.md](requests/G3-4.md) | Compose the comparison, equality and order-in-time answers G3 added |
| [L1-1.md](requests/L1-1.md) | Emit trace events at the twenty engine sites (round 5) |
| [L1-2.md](requests/L1-2.md) | What the realizer needs from the why chain to say "why" in words |
| [W1-1.md](requests/W1-1.md) | The turn result must carry its meaning, not only its sentence |
| [W1-2.md](requests/W1-2.md) | Second seam: answers composed by `engine.py` from graph routing |
| [W1-3.md](requests/W1-3.md) | Pass the model to `realize`, not only its path |
| [W2-1.md](requests/W2-1.md) | What the realizer now says, and what is left for the parsing side |
| [W3-1.md](requests/W3-1.md) | The meaning fields and pack readings the round-4 reply plans read |

## Korean design records (`docs/ko/`)

The source records, most of them in Korean. Dated files are decisions, plans,
design notes and goals; dated folders hold the measurements a goal recorded.
The owner edits the goal, plan and design files; other sessions read them.

### Decisions, plans and design notes

| Document | What |
| --- | --- |
| [2026-09-22-freeze-decision.md](ko/2026-09-22-freeze-decision.md) | **What is frozen until MARCO 1 ships, the six gate conditions, the exam rule, the goal queue.** Read first |
| [2026-09-22-plans-organized.md](ko/2026-09-22-plans-organized.md) | The organized record of every plan and decision; §4.12 is the architecture document template |
| [2026-09-24-roadmap-after-marco1.md](ko/2026-09-24-roadmap-after-marco1.md) | Roadmap after the gate: Observation Graph contract, MCO format, ALMA affect, self-repair, NERO, SOMA, with windows counted from the gate |
| [2026-09-24-perception-reasoning-emotion-philosophy.md](ko/2026-09-24-perception-reasoning-emotion-philosophy.md) | Owner's design note: perception, reasoning and emotion; "MARCO proves conclusions, not sensors"; §24 the seven rules |
| [2026-09-24-adaptive-intelligence-design.md](ko/2026-09-24-adaptive-intelligence-design.md) | Owner's design note: self-repair, research, capability graph, MCP, skill and prompt compilers, persona, development-aware emotion; §57 the eight principles |
| [2026-09-24-nero-compute-design.md](ko/2026-09-24-nero-compute-design.md) | Owner's design note: NERO, the compute and acceleration layer; code split by backend, intelligence not |
| [2026-09-24-trace-logging-design.md](ko/2026-09-24-trace-logging-design.md) | Owner's design note: trace and event logging, the basis of the provenance ledger |
| [2026-09-22-mco-integrated-roadmap.md](ko/2026-09-22-mco-integrated-roadmap.md) | MARCO / ALMA / POLO integrated plan and timeline (MCO, overlay, permissions, mobile, SOMA); §12 holds the seven-step dialogue |
| [2026-09-22-parallel-goals.md](ko/2026-09-22-parallel-goals.md) | Parallel goals, reduced by the freeze decision (superseded in scope) |
| [2026-09-21-marco-polo-roadmap.md](ko/2026-09-21-marco-polo-roadmap.md) | MARCO / POLO / ALMA development order and goal plan (G0–G10, A1, A2) |
| [2026-09-20-goal-roadmap.md](ko/2026-09-20-goal-roadmap.md) | MARCO / ALMA roadmap of the next ten goals |
| [2026-09-20-addition-next-directions.md](ko/2026-09-20-addition-next-directions.md) | MARCO / ALMA next development directions, the eleven requirements (formerly `Addition.md` at the root) |
| [2026-09-20-현황점검.md](ko/2026-09-20-현황점검.md) | MARCO → ALMA status check and remaining work, 2026-09-20 |
| [2026-09-20-완료검토.md](ko/2026-09-20-완료검토.md) | Review of the ALMA 0.1 completion report: completion not accepted, defects reproduced |
| [목표와-구조.md](ko/목표와-구조.md) | Goals and structure: what people decided, as opposed to progress records |
| [지능-개발-실행계획.md](ko/지능-개발-실행계획.md) | NAI intelligence development plan of 2026-09-14: ideas, order and acceptance criteria |
| [_방향_범용.md](ko/_방향_범용.md) | Direction note: a general engine that answers from any folder of documents |
| [지식그래프-시각인식-연구메모.md](ko/지식그래프-시각인식-연구메모.md) | Parked research memo: knowledge-graph-based visual recognition |

### Goal files

Each goal is a contract for one session; its state is in the freeze decision's
queue.

| Document | What |
| --- | --- |
| [2026-09-24-docs-r2-goal.md](ko/2026-09-24-docs-r2-goal.md) | D2: docs round 2, names, numbers, the package |
| [2026-09-24-realizer-r4-goal.md](ko/2026-09-24-realizer-r4-goal.md) | W4: realizer round 4, "why" said from the trace graph |
| [2026-09-24-understanding-r4-goal.md](ko/2026-09-24-understanding-r4-goal.md) | G4: understanding round 4, natural language instead of templates |
| [2026-09-24-file-moves-goal.md](ko/2026-09-24-file-moves-goal.md) | S4: file moves, the root becomes packages, references rewritten, no shims |
| [2026-09-24-trace-ledger-goal.md](ko/2026-09-24-trace-ledger-goal.md) | L1: the trace ledger, MARCO records why, not only what it said |
| [2026-09-24-realizer-r3-goal.md](ko/2026-09-24-realizer-r3-goal.md) | W3: realizer round 3, close the requests, say every kind |
| [2026-09-24-understanding-r3-goal.md](ko/2026-09-24-understanding-r3-goal.md) | G3: understanding round 3, the exam is the language, not the generator |
| [2026-09-24-model-comparison-goal.md](ko/2026-09-24-model-comparison-goal.md) | C1: compare MARCO with other models on the same frozen exams |
| [2026-09-24-realizer-r2-goal.md](ko/2026-09-24-realizer-r2-goal.md) | W2: realizer round 2, say everything, name the subject, clean the voice |
| [2026-09-24-reasoning-and-composition-gate-goal.md](ko/2026-09-24-reasoning-and-composition-gate-goal.md) | F2: the frozen reasoning set and the composition gate |
| [2026-09-23-understanding-r2-goal.md](ko/2026-09-23-understanding-r2-goal.md) | G2: understanding round 2, read the statements, then generalize |
| [2026-09-23-understanding-r1-goal.md](ko/2026-09-23-understanding-r1-goal.md) | G1: understanding round 1, turn holds into answers |
| [2026-09-22-docs-goal.md](ko/2026-09-22-docs-goal.md) | D1: documentation that tells the truth |
| [2026-09-22-test-speed-goal.md](ko/2026-09-22-test-speed-goal.md) | S3: test hygiene and speed |
| [2026-09-22-s2-minimal-goal.md](ko/2026-09-22-s2-minimal-goal.md) | S2-min: package skeleton and the language seam |
| [2026-09-22-p0-integration-goal.md](ko/2026-09-22-p0-integration-goal.md) | P0: integrate goal 2 and park `mco/` |
| [2026-09-22-frozen-dialogue-set-goal.md](ko/2026-09-22-frozen-dialogue-set-goal.md) | F1: the frozen dialogue set, 50 unseen dialogues and a scorer |
| [2026-09-22-structure-audit-goal.md](ko/2026-09-22-structure-audit-goal.md) | S1: structure audit, decide the layout before anything moves |
| [2026-09-22-realization-next-goal.md](ko/2026-09-22-realization-next-goal.md) | W1: say what was meant, a language realizer from meaning to sentence |
| [2026-09-22-repair-and-english-goal.md](ko/2026-09-22-repair-and-english-goal.md) | Repair unmatched input and report it; English as the core language |
| [2026-09-20-language-graph-goal.md](ko/2026-09-20-language-graph-goal.md) | Earlier goal: vocabulary and grammar as graphs, reasoning kept across a language switch |
| [2026-09-20-next-goal.md](ko/2026-09-20-next-goal.md) | Earlier goal: close ALMA's defects and finish an autonomous experience loop |
| [2026-09-20-next-goal-evidence.md](ko/2026-09-20-next-goal-evidence.md) | Evidence audit of that goal's conditions A–H |
| [2026-09-20-goal-prompt.md](ko/2026-09-20-goal-prompt.md) | Earlier goal prompt: ALMA 0.1 as a runnable research environment |

### Topic records

Undated or single-topic records, mostly September 9–18, of the graph engine's
development.

| Document | What |
| --- | --- |
| [README.md](ko/README.md) | Korean documentation index |
| [README-full.md](ko/README-full.md) | The long Korean README of the graph engine |
| [design.md](ko/design.md) | Symbolic reasoning architecture for the courtroom-debate game |
| [development.md](ko/development.md) | Developer documentation (Korean) |
| [direction.md](ko/direction.md) | Direction: an AI that does not make things up |
| [explain.md](ko/explain.md) | A dialogue AI filled from its own knowledge: a folder of text becomes a graph |
| [graph-authoring.md](ko/graph-authoring.md) | Making a new knowledge graph (Korean, earlier format) |
| [common-base.md](ko/common-base.md) | The common dialogue base shared by the game and document questions |
| [5-7-지원범위.md](ko/5-7-지원범위.md) | Supported scope of stages 5 to 7, as of 2026-09-17 |
| [agi-minimum-knowledge.md](ko/agi-minimum-knowledge.md) | The minimum general-knowledge graph (`graph_AGI_최소지식.kg`) |
| [general-knowledge-omissions.md](ko/general-knowledge-omissions.md) | What the everyday-knowledge graphs leave out on purpose |
| [alma-0.1.md](ko/alma-0.1.md) | ALMA 0.1 research loop around `ReasoningContext` |
| [alma-0.1-completion-matrix.md](ko/alma-0.1-completion-matrix.md) | ALMA 0.1 completion criteria mapped to implementation and checks |
| [alias-supply.md](ko/alias-supply.md) | How much more aliases help: measured twice, reverted |
| [answer-quality-baseline.md](ko/answer-quality-baseline.md) | Answer quality baseline: whether the answer was right, not whether the graph was |
| [clause-boundaries.md](ko/clause-boundaries.md) | Shared clause boundaries, 2026-09-11 |
| [cross-node-support.md](ko/cross-node-support.md) | Two nodes must speak, not one line: cross-node support in routing |
| [dialogue-evaluation.md](ko/dialogue-evaluation.md) | Evaluation of the real dialogue entry point, 2026-09-10 |
| [document-knowledge.md](ko/document-knowledge.md) | PDF and PPTX documents into knowledge graphs |
| [everyday-phrasing.md](ko/everyday-phrasing.md) | Everyday phrasing: a lookup table replaced by computation |
| [evidence-routing.md](ko/evidence-routing.md) | Evidence picks the graph, not the router rank alone |
| [explanation-learning.md](ko/explanation-learning.md) | Learning from an explanation, then solving what could not be solved |
| [expression-learning.md](ko/expression-learning.md) | Storing verified expression corrections |
| [failure-diagnosis.md](ko/failure-diagnosis.md) | Where and why relation parsing fails (`semantic_feedback.py diagnose`) |
| [filler-prefix.md](ko/filler-prefix.md) | Stripping filler before a question |
| [fragment-weight.md](ko/fragment-weight.md) | Fragments score below the full sentence |
| [frame-induction.md](ko/frame-induction.md) | Frames induced from examples instead of written by hand |
| [geometric-scoring.md](ko/geometric-scoring.md) | Two-way containment score, 2026-09-09 |
| [inference-resources.md](ko/inference-resources.md) | Resources of rule inference (Horn rules) measured |
| [language-components.md](ko/language-components.md) | Dialogue language components: no language-specific keywords in `input_understanding` |
| [multiword-entities.md](ko/multiword-entities.md) | Modified entities and reading across sentences |
| [numeral-semantics.md](ko/numeral-semantics.md) | Korean number words in quantity slots |
| [output-contracts.md](ko/output-contracts.md) | Output instructions ("numbers only") on verified numeric answers |
| [pack-model.md](ko/pack-model.md) | The pack model: language and axiom packs in `kgpack` v3 |
| [paraphrase-ceiling.md](ko/paraphrase-ceiling.md) | The paraphrase ceiling: what the 31% was made of |
| [paraphrase-learning.md](ko/paraphrase-learning.md) | Correcting expressions from sentence pairs |
| [question-endings.md](ko/question-endings.md) | Question endings computed, not listed |
| [rare-word-routing.md](ko/rare-word-routing.md) | A word few graphs contain is evidence in itself |
| [reasoning-challenge-v2.md](ko/reasoning-challenge-v2.md) | Separate generalization diagnosis v2: 14 new questions |
| [reasoning-corrections.md](ko/reasoning-corrections.md) | Correcting facts in a conversation |
| [reasoning-development.md](ko/reasoning-development.md) | Reasoning improvement log |
| [reasoning-integration-audit.md](ko/reasoning-integration-audit.md) | Reasoning integration audit, 2026-09-10 |
| [retrieval-diagnosis.md](ko/retrieval-diagnosis.md) | Failures reclassified after the geometric mean, 2026-09-10 |
| [semantic-contrasts.md](ko/semantic-contrasts.md) | Negated and planned facts in reasoning, 2026-09-10 |
| [slot-particles.md](ko/slot-particles.md) | Particles declared as slots, not written into examples |
| [synonym-table.md](ko/synonym-table.md) | A word-pair synonym table does not work: measured and dropped |
| [unreachable-questions.md](ko/unreachable-questions.md) | 28 questions the frozen routing yardstick cannot answer |
| [unread-event.md](ko/unread-event.md) | After an unread event, a past value is not asserted as current |
| [verbal-expressions.md](ko/verbal-expressions.md) | Formulas said in words, linked to the operation graph |
| [가벼움-측정.md](ko/가벼움-측정.md) | Lightness: measured values and the properties kept, 2026-09-18 |
| [발췌분류-측정.md](ko/발췌분류-측정.md) | The excerpt-classification component: attached and measured, 2026-09-18 |
| [언어-기능차이-측정.md](ko/언어-기능차이-측정.md) | Korean and English feature gap measured, 2026-09-18 |

### Graph-authoring prompts

Prompts handed whole to another AI, which then writes graphs.

| Document | What |
| --- | --- |
| [그래프-저작-프롬프트.md](ko/그래프-저작-프롬프트.md) | The graph authoring prompt, given whole |
| [대화예절-그래프-프롬프트.md](ko/대화예절-그래프-프롬프트.md) | Prompt for dialogue-etiquette graphs, after the authoring prompt |
| [일시작발화-보강-프롬프트.md](ko/일시작발화-보강-프롬프트.md) | Prompt to add task-opening utterances to graphs |
| [시작발화-충돌-고치기-프롬프트.md](ko/시작발화-충돌-고치기-프롬프트.md) | Prompt to fix two collisions the opening utterances caused |

### Data read by `build.py`

| Document | What |
| --- | --- |
| [_관계.json](ko/_관계.json) | Relations a person judged, added as concept edges |
| [_동의어.json](ko/_동의어.json) | Expressions people actually use for each node |
| [_발췌꼴.json](ko/_발췌꼴.json) | Excerpt kinds a person judged, checked before the regular expressions |

### Frozen dialogue gate (`ko/dialogue-gate-2026-09-22/`)

The frozen 52-dialogue exam's reports, recorded by the owner. Aggregates are
printed by `python tools/doc_facts.py frozen --run <name>`.

| Document | What |
| --- | --- |
| [README.md](ko/dialogue-gate-2026-09-22/README.md) | The gate set (goal F1): turn schema, labels, scoring, commands, baseline |
| [baseline.json](ko/dialogue-gate-2026-09-22/baseline.json) | Baseline at `4adc504`: 3 of 108 answerable |
| [round1.json](ko/dialogue-gate-2026-09-22/round1.json) | After understanding round 1, `a8388e9`: 19 of 108 |
| [round2.json](ko/dialogue-gate-2026-09-22/round2.json) | After understanding round 2, `494f599`: 21 of 108, two gate-3 violations |
| [composition-round2.json](ko/dialogue-gate-2026-09-22/composition-round2.json) | Composition gate after round 2, `ff8db40`: 207 of 340 composed, 132 passed through |
| [after-w2.json](ko/dialogue-gate-2026-09-22/after-w2.json) | After realizer round 2, `55fb2c8`: 21 of 108 |
| [composition-after-w2.json](ko/dialogue-gate-2026-09-22/composition-after-w2.json) | Composition after realizer round 2: 339 of 340 composed, 1 held |
| [round3.json](ko/dialogue-gate-2026-09-22/round3.json) | After understanding round 3, `60d796b`: 21 of 108, 0 wrong, 0 violations |
| [composition-round3.json](ko/dialogue-gate-2026-09-22/composition-round3.json) | Composition after round 3: 340 of 340 |
| [after-w3.json](ko/dialogue-gate-2026-09-22/after-w3.json) | After realizer round 3, `ead6302`: 21 of 108, 0 wrong, 0 violations; the README's current numbers |
| [composition-after-w3.json](ko/dialogue-gate-2026-09-22/composition-after-w3.json) | Composition after realizer round 3: 340 of 340, 0 passed through |

### Frozen reasoning gate (`ko/reasoning-gate-2026-09-24/`)

| Document | What |
| --- | --- |
| [README.md](ko/reasoning-gate-2026-09-24/README.md) | The reasoning set and the composition gate (goal F2): kinds, expectations, scoring, baseline |
| [baseline.json](ko/reasoning-gate-2026-09-24/baseline.json) | Baseline at `70ba9f8`: 80 of 109 parsed problems, 24 wrong |
| [round2.json](ko/reasoning-gate-2026-09-24/round2.json) | After understanding round 2, `a7c20b2`: 106 of 109, 0 wrong |
| [after-w2.json](ko/reasoning-gate-2026-09-24/after-w2.json) | After realizer round 2, `55fb2c8`: 106 of 109, 0 wrong |
| [round3.json](ko/reasoning-gate-2026-09-24/round3.json) | After understanding round 3, `60d796b`: 108 of 111, 0 wrong |
| [after-w3.json](ko/reasoning-gate-2026-09-24/after-w3.json) | After realizer round 3, `ead6302`: 108 of 111 problems, 148 of 151 questions, 0 wrong |

### Model comparison (`ko/model-comparison-2026-09-24/`)

| Document | What |
| --- | --- |
| [README.md](ko/model-comparison-2026-09-24/README.md) | Goal C1: MARCO, Qwen2.5-7B, GPT-2 and always-hold on the same frozen exams, one text scorer; method and fairness notes |
| [marco.json](ko/model-comparison-2026-09-24/marco.json) | MARCO's report, with the cross-check against the gates' own scorers |
| [qwen.json](ko/model-comparison-2026-09-24/qwen.json) | Qwen2.5-7B-Instruct, 4-bit, report |
| [gpt2.json](ko/model-comparison-2026-09-24/gpt2.json) | GPT-2 report |
| [always_hold.json](ko/model-comparison-2026-09-24/always_hold.json) | The always-hold floor |

### Other measurement folders

| Document | What |
| --- | --- |
| [repair-and-english-2026-09-22/unseen-before.json](ko/repair-and-english-2026-09-22/unseen-before.json) | Twenty unseen phrasings before the repair-and-English goal: 2 solved |
| [test-speed-2026-09-22/xdist-first-run.txt](ko/test-speed-2026-09-22/xdist-first-run.txt) | First parallel run of the full suite (goal S3) |
| [planning-2026-09-21/english-preparation.json](ko/planning-2026-09-21/english-preparation.json) | Planning spot check: the English-pack preparation check run |
| [planning-2026-09-21/existing-foundations.json](ko/planning-2026-09-21/existing-foundations.json) | Planning spot check: existing foundations run |
| [planning-2026-09-21/verification-summary.json](ko/planning-2026-09-21/verification-summary.json) | Planning spot checks, summary and file hashes |
| [dialogue-check-2026-09-22/answer-quality.json](ko/dialogue-check-2026-09-22/answer-quality.json) | Answer quality, 34 questions, 2026-09-22 |
| [dialogue-check-2026-09-22/answer-quality.stdout.txt](ko/dialogue-check-2026-09-22/answer-quality.stdout.txt) | Its printed output |
| [dialogue-check-2026-09-22/answer-quality.stderr.txt](ko/dialogue-check-2026-09-22/answer-quality.stderr.txt) | Its error output (empty) |
| [dialogue-check-2026-09-22/dialogue-v2.json](ko/dialogue-check-2026-09-22/dialogue-v2.json) | Development dialogue set v2 via `AppState`: 7 of 14 |
| [dialogue-check-2026-09-22/dialogue-v2.stdout.txt](ko/dialogue-check-2026-09-22/dialogue-v2.stdout.txt) | Its printed output |
| [dialogue-check-2026-09-22/dialogue-v2.stderr.txt](ko/dialogue-check-2026-09-22/dialogue-v2.stderr.txt) | Its error output (empty) |
| [dialogue-check-2026-09-22/verification-summary.json](ko/dialogue-check-2026-09-22/verification-summary.json) | Summary of the 2026-09-22 dialogue check |
| [dialogue-check-2026-09-20/answer-quality.json](ko/dialogue-check-2026-09-20/answer-quality.json) | Answer quality, 34 questions, 2026-09-20: 21 correct |
| [dialogue-check-2026-09-20/answer-quality.txt](ko/dialogue-check-2026-09-20/answer-quality.txt) | Its printed output |
| [dialogue-check-2026-09-20/dialogue-v1.json](ko/dialogue-check-2026-09-20/dialogue-v1.json) | Development dialogue set v1: 16 of 16 |
| [dialogue-check-2026-09-20/dialogue-v1.stdout.txt](ko/dialogue-check-2026-09-20/dialogue-v1.stdout.txt) | Its printed output |
| [dialogue-check-2026-09-20/dialogue-v2.json](ko/dialogue-check-2026-09-20/dialogue-v2.json) | Development dialogue set v2: 7 of 14 |
| [dialogue-check-2026-09-20/dialogue-v2.stdout.txt](ko/dialogue-check-2026-09-20/dialogue-v2.stdout.txt) | Its printed output |
| [dialogue-check-2026-09-20/verification-summary.json](ko/dialogue-check-2026-09-20/verification-summary.json) | Summary of the 2026-09-20 dialogue check |
| [audit-2026-09-20/verification-summary.json](ko/audit-2026-09-20/verification-summary.json) | Independent audit of 2026-09-20 on Windows: suite, dialogue sets, answer quality, limits |
| [audit-2026-09-20/answer-quality.json](ko/audit-2026-09-20/answer-quality.json) | Audit: answer quality, 34 questions |
| [audit-2026-09-20/answer-quality.txt](ko/audit-2026-09-20/answer-quality.txt) | Audit: its printed output |
| [audit-2026-09-20/audit-probes.json](ko/audit-2026-09-20/audit-probes.json) | Audit: diagnostic probe observations, not benchmark scores |
| [audit-2026-09-20/audit-probes.py](ko/audit-2026-09-20/audit-probes.py) | Audit: the read-only probe script |
| [audit-2026-09-20/dialogue-v1.json](ko/audit-2026-09-20/dialogue-v1.json) | Audit: development dialogue set v1, 15 of 16 |
| [audit-2026-09-20/dialogue-v2.json](ko/audit-2026-09-20/dialogue-v2.json) | Audit: development dialogue set v2, 7 of 14 |
| [audit-2026-09-20/pytest-last-failed.txt](ko/audit-2026-09-20/pytest-last-failed.txt) | Audit: the failing tests of that run |
| [review-2026-09-20/verification-summary.json](ko/review-2026-09-20/verification-summary.json) | Review of 2026-09-20: targeted tests, probes, reproduction outcomes |
| [review-2026-09-20/review-probes.json](ko/review-2026-09-20/review-probes.json) | Review: eight ALMA defect probes and their results |
| [review-2026-09-20/review_probes.py](ko/review-2026-09-20/review_probes.py) | Review: the read-only probe script |
| [review-2026-09-20/late_error_probe.py](ko/review-2026-09-20/late_error_probe.py) | Review: injects a late checkpoint error into the ALMA evaluator |
| [review-2026-09-20/alma-integrated.json](ko/review-2026-09-20/alma-integrated.json) | Review: ALMA integrated reproduction report |
| [review-2026-09-20/alma-integrated.stdout.txt](ko/review-2026-09-20/alma-integrated.stdout.txt) | Its printed output |
| [review-2026-09-20/alma-late-error.json](ko/review-2026-09-20/alma-late-error.json) | Review: the late-error run |
| [review-2026-09-20/alma-late-error.stdout.txt](ko/review-2026-09-20/alma-late-error.stdout.txt) | Its printed output |
| [review-2026-09-20/experience-concept.json](ko/review-2026-09-20/experience-concept.json) | Review: experience-concept reproduction report |
| [review-2026-09-20/experience-concept.stdout.txt](ko/review-2026-09-20/experience-concept.stdout.txt) | Its printed output |
| [review-2026-09-20/targeted-tests.txt](ko/review-2026-09-20/targeted-tests.txt) | Review: the targeted test run |
| [execution-2026-09-20/alma-full-pytest-report.json](ko/execution-2026-09-20/alma-full-pytest-report.json) | ALMA 0.1 execution: the full suite run |
| [execution-2026-09-20/alma-integrated-report.json](ko/execution-2026-09-20/alma-integrated-report.json) | ALMA 0.1 execution: integrated reproduction |
| [execution-2026-09-20/alma-integrated-late-error-report.json](ko/execution-2026-09-20/alma-integrated-late-error-report.json) | ALMA 0.1 execution: integrated reproduction with a late error |
| [execution-2026-09-20/alma-unified-report.json](ko/execution-2026-09-20/alma-unified-report.json) | ALMA 0.1 execution: unified reproduction |
| [execution-2026-09-20/alma-regression-report.json](ko/execution-2026-09-20/alma-regression-report.json) | ALMA 0.1 execution: regression reproduction |
| [execution-2026-09-20/alma-environment-report.json](ko/execution-2026-09-20/alma-environment-report.json) | ALMA 0.1 execution: local environment |
| [execution-2026-09-20/alma-graph-asset-report.json](ko/execution-2026-09-20/alma-graph-asset-report.json) | ALMA 0.1 execution: graph assets and lineage |
| [execution-2026-09-20/alma-cross-domain-transfer-report.json](ko/execution-2026-09-20/alma-cross-domain-transfer-report.json) | ALMA 0.1 execution: cross-domain transfer |
| [execution-2026-09-20/alma-structural-transfer-report.json](ko/execution-2026-09-20/alma-structural-transfer-report.json) | ALMA 0.1 execution: structural transfer |
| [execution-2026-09-20/structural-transfer-report.json](ko/execution-2026-09-20/structural-transfer-report.json) | Structural transfer report |
| [execution-2026-09-20/unified-life-report.json](ko/execution-2026-09-20/unified-life-report.json) | Unified life report |
| [execution-2026-09-20/experience-concept-report.json](ko/execution-2026-09-20/experience-concept-report.json) | Experience-concept report |
| [execution-2026-09-20/experience-concept-reproduction-report.json](ko/execution-2026-09-20/experience-concept-reproduction-report.json) | Experience-concept reproduction |
| [execution-2026-09-20/experience-concept-before-lifecycle-fix.json](ko/execution-2026-09-20/experience-concept-before-lifecycle-fix.json) | Experience concepts before the lifecycle fix |
| [execution-2026-09-20/experience-concept-after-lifecycle-fix.json](ko/execution-2026-09-20/experience-concept-after-lifecycle-fix.json) | Experience concepts after the lifecycle fix |
| [execution-2026-09-20/learning-lifecycle-report.json](ko/execution-2026-09-20/learning-lifecycle-report.json) | Learning lifecycle report |
| [execution-2026-09-20/learning-lifecycle-before-fix.json](ko/execution-2026-09-20/learning-lifecycle-before-fix.json) | Learning lifecycle before the fix |
| [execution-2026-09-20/learning-lifecycle-after-fix.json](ko/execution-2026-09-20/learning-lifecycle-after-fix.json) | Learning lifecycle after the fix |

### English-pack preparation (`ko/english-pack-preparation/`)

Exchange drafts of 2026-09-21 for the English pack, not runtime assets.

| Document | What |
| --- | --- |
| [README.md](ko/english-pack-preparation/README.md) | What the preparation is and how the drafts relate |
| [01-english-grammar-rules.json](ko/english-pack-preparation/01-english-grammar-rules.json) | Draft English grammar rules |
| [02-sense-links-ko-en.json](ko/english-pack-preparation/02-sense-links-ko-en.json) | Draft Korean–English sense links |
| [03-existing-knowledge-links.json](ko/english-pack-preparation/03-existing-knowledge-links.json) | Where English expressions attach to existing packs, nodes and relations |
| [04-evaluation-cases.json](ko/english-pack-preparation/04-evaluation-cases.json) | Thirteen fixed evaluation scenarios, Korean and English |
| [05-training-examples.json](ko/english-pack-preparation/05-training-examples.json) | Development examples, kept apart from the evaluation cases |
| [06-coverage-and-open-decisions.md](ko/english-pack-preparation/06-coverage-and-open-decisions.md) | Coverage by feature and the open design decisions |
| [07-graph-migration-map.md](ko/english-pack-preparation/07-graph-migration-map.md) | Map from the drafts to the final graph format |
| [check.py](ko/english-pack-preparation/check.py) | Read-only check of the drafts for gaps, duplicates and false claims about the repository |
| [evidence/baseline-2026-09-21.json](ko/english-pack-preparation/evidence/baseline-2026-09-21.json) | Baseline fixed before the English-pack preparation |
