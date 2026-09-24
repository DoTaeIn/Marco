# MARCO G5 — Compositional Input Understanding

> Owner's design note, recorded verbatim by the plan manager on 2026-09-25 as the
> contingency for round 5. Whether it runs, and in which of the two scopes below,
> is decided by round 4's frozen number (see the freeze decision's queue). The
> plan manager's comparison with G4 follows the note.

---

> **Status:** Contingency / next-round design
> **Purpose:** G4가 held-out 자연어 입력에서 포화될 경우 전환할 차세대 입력 이해 구조
> **Core idea:** 문장 패턴을 끝없이 추가하지 말고, 표면 입력을 의미 조각으로 분해한 뒤 여러 의미 후보를 만들고 MARCO의 상태·지식·추론으로 검증한다.

## 1. G4 판단 기준 요약

G4 방향 자체는 유효하다. 현재 G4는: 사람 말투 데이터 생성 → 실패 원인 분류 → 읽기 규칙 추가 → 규칙용 / 검증용 분리 → 과적합 검사 구조이며, 이는 현재 병목이 reasoning보다 reading인지 검증하는 좋은 실험이다.

다만 다음 신호가 나오면 G5로 pivot한다.

1. 규칙용 성능은 높고 검증용 성능은 낮음
2. 새 시험 세트마다 새로운 예외 규칙이 계속 증가
3. 규칙 수는 크게 늘지만 held-out 성능 상승폭은 작음
4. 같은 의미의 어순/표현 변화에 반복 실패
5. recording은 높은데 answering은 계속 낮음

특히 `+30 rules → +2 validation points` 같은 상태가 나오면 문장 패턴 암기 구조의 한계로 본다.

## 2. G5 목표

> **문장 전체 패턴을 외우는 parser에서, 의미 조각을 조합해 해석하는 parser로 전환하는 것.**

기존: Sentence → Pattern Rule → Meaning
G5: Sentence → Surface Fragments → Semantic Fragments → Candidate Meaning Graphs → Constraint / Reasoning Validation → Interpretation

## 3. 핵심 원칙

> **Text Correction is not the goal. Meaning Reconstruction is the goal.**

입력을 완벽한 표준 문장으로 고치는 것이 목적이 아니다. 목표는 사용자가 의도한 의미 그래프를 최대한 적은 가정으로 복원하는 것.

## 4. 전체 Input Understanding Pipeline

```text
RAW INPUT
   ↓
1. Surface Normalization Candidates
   ↓
2. Morphological / Grammatical Reading
   ↓
3. Canonical Frame Candidates
   ↓
4. Semantic Fragment Extraction
   ↓
5. Candidate Meaning Graph Assembly
   ↓
6. Constraint / Context / KG / Reasoning Validation
   ↓
7. Interpretation Selection
   │
   ├─ confident → accept
   ├─ ambiguous → ask
   └─ unsupported → hold
```

## 5. Stage 1 — Surface Normalization Candidates

오탈자를 바로 수정하지 않는다. 잘못된 방식: "줫어" → "줬어" → 확정. 권장: `CorrectionCandidate(original="줫어", replacement="줬어", edit_cost=low)`. 후보를 여러 개 유지할 수 있다. 예: "낳한테" → 나한테 / 너한테 / 고유명사 가능성. 즉 **Spell correction ≠ truth.**

## 6. Stage 2 — Morphological / Grammatical Reading

표면형에서 작은 역할 후보만 읽는다: entity, quantity, particle / case marker, verb / event, time, negation, correction marker, reference, question marker.

입력 "민수가 사과 세 개 영희 줬어" → 민수: entity / agent candidate; 사과: object candidate; 세 개: quantity; 영희: recipient / owner / entity candidate; 줬어: transfer event candidate. 아직 최종 의미는 확정하지 않는다.

## 7. Stage 3 — Canonical Frame Candidates

주다 / 넘기다 / 보내다 / 건네다 / 돌려주다를 각각 독립 문장 규칙으로 다루기보다 TRANSFER family로 묶는다. Canonical frame: `TRANSFER(giver, receiver, object, quantity, time)`.

## 8. Stage 4 — Semantic Fragments

`EntityCandidate(민수)`, `EntityCandidate(영희)`, `Quantity(value=3, unit=count)`, `ObjectCandidate(사과)`, `TransferCandidate(lexical_source="줬어")`. Semantic Fragment는 아직 완성 문장이 아니다.

## 9. Stage 5 — Candidate Meaning Graph Assembly

한 입력에서 하나의 뜻만 만들지 않는다. Candidate A: `Transfer(giver=민수, receiver=영희, object=사과, quantity=3)`. Candidate B: `Transfer(giver=민수, object=영희의 사과, quantity=3)`. 필요하면 여러 후보를 유지한다.

## 10. Parse Lattice

Sentence → Candidate Meaning A / B / C → Constraint Pruning → Best surviving interpretation. 문장 해석을 한 번에 확정하지 않는다.

## 11. Stage 6 — Validation

Meaning 후보는 grammar compatibility, particle compatibility, verb-frame compatibility, conversation context, state consistency, KG compatibility, semantic completeness, unsupported assumption cost, reasoning consistency로 평가한다.

개념 점수: `score = grammar_fit + semantic_fit + context_fit + state_fit + reasoning_fit − correction_cost − unsupported_assumption`. 정확한 숫자 공식일 필요는 없지만 구조는 이 방향으로 둔다.

## 12. Reasoning Feedback

기존: Language → Parser → Meaning → Reasoning. G5: Language → Candidate Meanings ↕ Reasoning / State Consistency → Interpretation Selection. 즉 추론이 parser를 역으로 검증한다.

## 13. Correction 표현 일반화

`CorrectionEvent(target, replacement)`로 통일한다. "민수한테 줬어. 아니, 영희한테." → Event E1: receiver = 민수; Correction: target = E1.receiver, replacement = 영희.

## 14. "둘이 합쳐서" 일반화

`Query(operation=sum, members=selected_entities, cardinality_requirement=2)`. 셋 이상인데 "둘이"라고 하면 `selected_entities.count != 2` → unresolved reference.

## 15. G4 규칙은 버리지 않는다

G4의 규칙 묶음(이름 아닌 소유자, 장소 소유자, 막연한 수량, 전달 동사, 나중 수량, 수신자 정정, 지시 대상 정정, 시간 부사, 존댓말 / 조사 / 단위)은 Sentence Pattern Rules가 아니라 Semantic Reading Primitives, 즉 semantic primitive / frame component로 승격한다.

## 16. G4 데이터는 G5 benchmark가 된다

생성한 대화에는 Scenario → Qwen paraphrase 구조가 있다. 원래 scenario를 보존하면 Surface Sentence ↔ Gold Meaning Graph 쌍이 되며, G5의 semantic parsing benchmark로 그대로 쓴다.

## 17. 반드시 보존할 데이터

각 생성 문장에 raw_sentence, normalized_candidates, gold_scenario, gold_meaning_graph, language, split, failure_type를 남긴다. **Qwen이 문장을 만들기 전의 구조화된 scenario를 절대 버리지 않는다.**

## 18. 다음 데이터 생성 방향

동일 의미에 대해 표면 다양성을 더 크게: different word order, subject omission, object fronting, different particles, pronoun, honorific, correction, relative clause, time phrase, colloquial form, typo, spacing variation. 목표: 같은 meaning graph를 여러 표면형에서 복원할 수 있는지 측정.

## 19. Failure Taxonomy 확장

surface_normalization_failure, morphology_failure, frame_detection_failure, semantic_fragment_failure, binding_failure, reference_failure, meaning_assembly_failure, state_update_failure, query_binding_failure, reasoning_failure, realizer_hold, cascade_failure.

## 20. Rule Growth Metric

매 라운드 기록: new rules, new LOC, new semantic phenomena, training gain, validation gain, generalization gap. `+10 rules → +18 validation points`면 좋은 신호; `+30 rules → +2 validation points`면 구조 전환 신호.

## 21. Pivot 기준

| 결과 | 판단 |
| --- | --- |
| Validation 기록 ≥90%, 답변 ≥70%, wrong=0 | G4 방향 유지 |
| Rule/validation gap >15 | surface overfit 의심 |
| 규칙 추가 대비 validation 증가 급감 | G5 전환 |
| Recording 높고 answering 낮음 | downstream 병목 조사 |
| 새 표현 예외가 라운드마다 폭증 | compositional parser 필요 |
| 동일 의미 어순변화에 반복 실패 | Parse Lattice 필요 |

## 22. G5 최소 구현

1. typo/spacing candidate generator
2. surface fragment reader
3. canonical frame detector
4. semantic fragment objects
5. meaning candidate assembler
6. simple constraint pruning
7. reasoning/state consistency check
8. accept / ask / hold

## 23. 초기 Canonical Frames

OWNERSHIP, TRANSFER, LOCATION, QUANTITY, CORRECTION, COMPARISON, TEMPORAL, QUERY. G4에서 자주 실패한 것부터 시작한다.

## 24. 초기 Fragment Types

EntityCandidate, ReferenceCandidate, QuantityCandidate, ObjectCandidate, LocationCandidate, TimeCandidate, EventCandidate, CorrectionCandidate, QueryCandidate, NegationCandidate.

## 25. 초기 Constraint Types

particle_constraint, role_constraint, cardinality_constraint, state_constraint, reference_constraint, graph_constraint, temporal_constraint, contradiction_constraint.

## 26. Ask / Hold 정책

후보가 하나로 좁혀지지 않으면 억지로 고르지 않는다. candidate A ≈ candidate B이면 ask clarification 또는 hold. **Ambiguity is not parser failure. It is an epistemic state.**

## 27. 오탈자 처리 원칙

raw input preserved, correction candidates logged, high-cost correction penalized, unknown proper noun possibility preserved. 한 번 수정했다고 원문을 잃지 않는다.

## 28. 문법 변환의 의미

오탈자 후보화 → 문법/역할 후보화 → canonical frame 후보화 → meaning graph 후보 생성 → context / KG / reasoning으로 검증 → interpretation.

## 29. 핵심 차이

기존 parser: "이 문장은 어떤 패턴인가?" G5 parser: "이 표면 입력이 어떤 의미 구조로 설명될 수 있는가?"

## 30. 궁극 구조

RAW INPUT → Surface Normalizer → Morphological Reader → Semantic Fragment Generator → Frame Candidate Builder → Candidate Meaning Graphs → Constraint Solver → Reasoning / State Validation → Interpretation → Graph Update / Query

## 31. 핵심 문장

> **G4는 자연어 현상을 발견하는 단계이고, G5는 그 현상을 조합 가능한 의미 단위로 바꾸는 단계다.**

> **문장 패턴을 더 많이 외우는 것이 아니라, 같은 의미를 만드는 다양한 표면형을 하나의 canonical meaning graph로 수렴시키는 것이 G5의 목표다.**

> **MARCO는 올바른 문장을 복원하는 시스템이 아니라, 입력 뒤의 의미를 복원하는 시스템이어야 한다.**

---

## Plan manager's comparison with G4 (2026-09-25)

What is already there: the reader is not a pure pattern matcher. Particles give
roles, the verb lexicon groups transfer verbs into one family, "the two of them"
became a cardinality check in G4 batch 10, recipient corrections became a
correction class. What the note adds that does not exist: several readings kept
until validation (the lattice), validation by the conversation's state and by
reasoning (feedback), typo and spacing candidates with a cost, and the
scenario ↔ sentence pairs used as a semantic-parsing benchmark. The gold
scenarios of dev set v4 already exist, so the benchmark is free.

Risks: candidate explosion without hard constraints; the score of §11 turning
into hand-tuned weights, which is hardcoding in a new costume, so constraints
are declared and lexicographic, never numeric; the lexicon is still needed,
so this note and the build-time data tool at scale are complementary, not
alternatives; and it is two to three agent-days, not one.

Decision by round 4's frozen number: above 40 of 108, keep the G4 method and
adopt only §16, §17 and §20 (benchmark, preserved scenarios, rule-growth
metric). Between 25 and 40, the hybrid: the lattice, the state validation and
ask / hold wrapped around the existing reader, G4's declarations promoted to
primitives (§15), measured first on the dev-v4 gold graphs. At 25 or below,
the minimum implementation of §22 on the frames of §23, as round 5.
