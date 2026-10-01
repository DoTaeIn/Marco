# MARCO Fixed Development Timeline

> **Status:** Owner-fixed roadmap  
> **Purpose:** 개발 순서를 고정하고, 새로운 기능 아이디어가 생겨도 기존 타임라인을 흔들지 않도록 하기 위한 기준 문서  
> **Core Rule:** 상위 단계 순서는 고정한다. 새로운 기능은 기존 단계를 재배치하지 않고, 가장 적절한 시점 아래에 추가한다.

---

# 1. 현재 상태

```text
MARCO Core
├─ 언어 입력 이해        ◐
├─ 상태 추적             ●
├─ symbolic reasoning    ●
├─ corrections           ◐
├─ why / explanation     ◐
├─ restart persistence   ◐
├─ compositional output  ●
└─ evidence safety       ●
```

현재 측정:

```text
Statement recording      138 / 150
Dialogue answering        63 / 108 = 58.3%
Wrong answers              0
Why                        18 / 26
Structured reasoning      110 / 113 = 97.3%
Runtime latency           ~27 ms / turn
Runtime LLM                none
```

현재 병목:

> **Reasoning이 아니라 Input / Context Understanding.**

MARCO 1 gate:

```text
1. Fixed 7-step dialogue        PASS
2. 90% unseen dialogue         FAIL — 58.3%
3. No unsupported answer,
   no withdrawn evidence       PASS
4. Sample count and full
   failure list published      PASS
5. Composed replies            PASS
6. Reasoning gate              PASS
```

Condition 4 was left out of the first version of this file by accident and is
restored (owner, 2026-09-29). The numbering is the freeze decision's.

따라서 MARCO 1 전 최우선 목표는:

> **Gate #2 — Input Understanding 90%+**

---

# 2. Roadmap Governance Rule

고정 순서:

```text
M1 → RELEASE → M2 → M3 → M4 → A1 → A2 → S1 → P1 → N1
```

새로운 기능이 생겨도:

```text
기존 단계 삭제      금지
기존 단계 순서 변경 금지
기존 단계를 앞당김  금지
```

새 기능은 반드시:

```text
1. 책임 영역 판단
2. 선행조건 확인
3. 기존 단계 중 가장 자연스러운 위치 선택
4. 해당 단계의 하위 항목으로 추가
```

한다.

> **새 기능이 생기면 타임라인을 다시 만들지 않는다.  
> 타임라인 안에서 그 기능이 들어갈 위치만 결정한다.**

예외는 Owner가 명시적으로 새 고정 로드맵을 선언한 경우뿐이다.

---

# 3. Naming Rule

앞으로 `G4 / G5 / G6 / G7`을 전체 프로젝트 로드맵 번호로 사용하지 않는다.

이해 개선 반복:

```text
UR = Understanding Round
```

예:

```text
UR6
UR7
UR8
```

큰 개발 단계:

```text
M = MARCO
A = ALMA
S = SOMA
P = POLO
N = NERO
```

---

# 4. 전체 고정 타임라인

```text
NOW
 │
 ▼
M1 — MARCO 1 Language Gate
 │
 ▼
MARCO 1 RELEASE
 │
 ▼
M2 — Self-Improving MARCO
 │
 ▼
M3 — Capability System
 │
 ▼
M4 — Goal / Prompt Compilation
 │
 ▼
A1 — ALMA Self / Persona
 │
 ▼
A2 — ALMA Affect / Development
 │
 ▼
S1 — SOMA Perception
 │
 ▼
P1 — POLO Action
 │
 ▼
N1 — NERO Acceleration
```

---

# 5. M1 — MARCO 1 Language Gate

## 상태

```text
PASSED — gate declared by the owner, 2026-10-01
RELEASE FREEZE until the MARCO 1 tag
```

## 목표

```text
Dialogue answerability ≥ 90%
Wrong answers = 0
```

## 현재

```text
98 / 108 = 90.7%, 0 wrong, 0 violations (2026-10-01)
```

Release freeze (owner, 2026-10-01): no more work aimed at the exam score or at held turns. Before the
release a reasoning change is allowed only for a demonstrated safety or correctness bug that can produce
a wrong or unsupported state or answer. New language coverage, broader text reading and further
understanding improvements are M2.

## 주요 작업

```text
UR7 완료
Graph-Grounded Understanding
Follow-up Questions
Referent Resolution
Cross-language Questions
Corrections
Why / Explanation
Restart residuals
```

입력 이해 목표 구조:

```text
Surface Reader
↓
Candidate Readings
↓
Graph Grounding
↓
Context / State Validation
↓
Reasoning Validation
↓
Accept / Ask / Hold
```

기존:

```text
Rules
→ Meaning
→ KG
```

목표:

```text
Rules
+
Knowledge Graph
+
Conversation Context
→ Candidate Meaning Graphs
→ State / Reasoning Validation
```

M1 종료 조건:

```text
≥ 90% answerable
0 wrong
0 unsupported confident answers
0 withdrawn-evidence violations
sample count + full failure list published
```

Effort (UR7) stays in M1 only as **turn-local deliberation**: level 3 may try one
repair step and retry inside the turn. No persistent learning, no permanent
repair, no external research, no OpenProblem promotion; those are M2.

---

# 6. MARCO 1 RELEASE

Gate 통과 직후 새 기능을 시작하기 전에 먼저 release를 남긴다.

```text
README truth update
benchmark update
release notes
versioning
MCO public API check
documentation
release artifact
fresh exam: 50+ new dialogues, scored once, published beside the gate number
real MCO format: native container, overlay, snapshot (before M2)
```

The real MCO format sits here, under the release and before M2 (owner,
2026-09-29). It is not a top-level phase. The older documents call its
milestones "MCO M1–M4"; those are not the MARCO phases M1–M4 of this file.

Scope (owner, 2026-10-01): storage and runtime infrastructure only — binary format with stable ids,
compile / run / inspect, persistent overlay applied only by explicit or outside approval, provenance, base
hash and build id validation, conversation snapshot and restore. Consolidation comes after the release. It
adds no learning: how MARCO discovers, validates and promotes changes is M2.

핵심:

> **Gate를 통과한 시점의 MARCO를 하나의 명확한 버전으로 남긴다.**

---

# 7. M2 — Self-Improving MARCO

기존:

```text
Unknown
→ HOLD
→ End
```

목표:

```text
Unknown
→ Diagnose
→ Repair
→ Retry
→ Research if needed
→ Retry
→ Validate
→ Learn Candidate
```

세부 순서:

```text
M2.1 Open Problems
M2.2 Failure Diagnosis
M2.3 Partial Self-Repair
M2.4 Retry Loop
M2.5 External Knowledge Gap Research
M2.6 Validation / Promotion
M2.7 Observation Graph Contract (end of M2, before M3)

Placed in M2 by the owner (2026-10-01), order inside M2 not yet fixed:
Real-text reading: language coverage beyond MARCO 1's forms (SVAMP: 20 of 151 in-domain statements read)
Effort 4: multi-hop graph grounding
Effort 5: bounded multi-hypothesis search
```

The Observation Graph Contract is the last item of M2 (owner, 2026-09-29), not a
phase of its own: A1, A2 and S1 write into it, so it is fixed before M3 starts.

Failure classes 예:

```text
routing_gap
lexical_gap
concept_gap
relation_gap
fact_gap
rule_gap
operator_gap
representation_gap
parser_gap
conflict_gap
```

---

# 8. M3 — Capability System

목표:

```text
MARCO가 "내가 무엇을 할 수 있는가?"를 그래프로 안다.
```

순서:

```text
Capability Core
↓
Capability Graph
↓
MCP Compiler
↓
Skill Compiler
↓
External Tool Binding
```

Boundary with P1 (owner, 2026-09-29): M3 owns capability declaration, discovery,
binding and the **permission contract**. POLO / P1 owns the actual side-effectful
execution and the enforcement of that contract. The bounded read-only research
that exists today stays as it is.

정의:

```text
Knowledge Graph
= 무엇을 아는가

Capability Graph
= 무엇을 할 수 있는가
```

---

# 9. M4 — Goal / Prompt Compilation

Prompt를 단순 텍스트 context가 아닌 실행 가능한 임시 graph로 만든다.

```text
Prompt
↓
Goal
Constraints
Priorities
Permissions
Completion Condition
↓
Task Graph
↓
Policy Graph
↓
Capability Binding
↓
Execution
```

원칙:

> **Prompt state must not overwrite persistent knowledge.**

---

# 10. A1 — ALMA Self / Persona

```text
Persona Prompt
↓
Self Graph
↓
Memory
↓
Beliefs
↓
Goals
↓
Relationships
```

핵심:

```text
Persona Prompt ≠ Persona
```

실제 Persona:

```text
Initial Self
+
Experience
+
Memory
+
Goals
+
Relationships
+
Belief Revision
=
Current Self Model
```

---

# 11. A2 — ALMA Affect / Development

```text
General Affect Core
+
Development Profile
+
Persona
+
Experience
+
Context
```

핵심:

```text
Age
→ Development Prior

Experience
→ Development Revision
```

감정 흐름:

```text
Event
→ Appraisal
→ Affect
→ Regulation
→ Behavior
→ Outcome
→ Emotional Learning
```

---

# 12. S1 — SOMA Perception

```text
Camera
Audio
Sensors
↓
SOMA
↓
Observation Graph
↓
MARCO
```

Perception Controller:

```text
Glance
↓
Track
↓
Inspect
↓
Identify
↓
Explain
```

budget 기반으로 필요한 곳만 깊게 분석한다.

---

# 13. P1 — POLO Action

```text
MARCO
↓
Action Decision
↓
POLO
↓
Capability / Environment
```

예:

```text
File
API
Application
Robot
Message
```

로봇 제어가 필요하면 P1 아래의 하위 기능으로 추가한다.

```text
POLO
↓
Motion Planner
↓
Trajectory / Whole-body Control
↓
Motor Controller
```

이 기능 때문에 P1 순서를 앞당기지 않는다.

---

# 14. N1 — NERO Acceleration

현재 MARCO latency가 약 27 ms이므로 지금의 병목은 compute가 아니다.

따라서 NERO는 후순위다.

순서:

```text
Backend Abstraction
↓
CPU Backend
↓
GPU Routing / Scoring
↓
Parallel Frontier
↓
Batch Rule Matching
↓
Parallel Hypotheses
↓
Multi-GPU / Remote
```

---

# 15. 새 기능 추가 규칙

앞으로 새 아이디어는 다음 형태로 기록한다.

```yaml
feature:
  name: ...

  responsibility:
    marco | alma | soma | polo | nero | mco | relay

  depends_on:
    - ...

  earliest_phase:
    M2

  target_phase:
    M3

  reason:
    ...

  does_not_change_timeline: true
```

---

# 16. 기능 배치 예시

```text
인터넷 검색 / Knowledge Gap Research → M2
MCP adapter                       → M3
Skill adapter/compiler            → M3
Task Prompt Compiler              → M4
Persona Prompt Compiler           → A1
감정 발달                         → A2
Camera / Audio perception         → S1
Robot action                      → P1 하위
GPU graph traversal               → N1
```

---

# 17. 금지 규칙

새 아이디어가 매력적이라는 이유만으로:

```text
"이거 먼저 만들자"
```

하지 않는다.

반드시:

```text
현재 단계 완료?
↓
아니오
↓
roadmap에 위치만 기록
↓
구현은 보류
```

한다.

---

# 18. MARCO 1 전 Frozen Items

MARCO 1 gate 전에는 제품 코드로 구현하지 않는다.

```text
Self-Repair
Web / Document Learning
MCP / Skill Capability expansion
Prompt Task Graph
ALMA expansion
SOMA
POLO
NERO
```

설계 문서 작성은 허용한다.

---

# 19. NOW / NEXT / LATER

항상 프로젝트 화면에는 세 단계만 강조한다.

## NOW

```text
MARCO 1 RELEASE (M1 gate passed 2026-10-01)
```

## NEXT

```text
M2 — Self-Improving MARCO
```

## LATER

```text
M3 Capability
M4 Prompt / Goal
A1 Persona
A2 Affect
S1 SOMA
P1 POLO
N1 NERO
```

---

# 20. 한눈에 보는 타임라인

```text
┌────────────────────────────────────────────────────────────┐
│                    MARCO FIXED ROADMAP                     │
└────────────────────────────────────────────────────────────┘

NOW

[M1 MARCO 1 LANGUAGE GATE]
        │
        ├─ UR7
        ├─ Graph-Grounded Understanding
        ├─ Follow-up / Referent
        ├─ Cross-language
        ├─ Correction / Why / Restart
        │
        ▼
[90%+ / 0 wrong]
        │
        ▼

[MARCO 1 RELEASE]
        │
        ▼

NEXT

[M2 SELF-IMPROVEMENT]
        │
        ├─ Open Problems
        ├─ Diagnose
        ├─ Partial Repair
        ├─ Retry
        ├─ External Research
        └─ Validation / Promotion
        │
        ▼

[M3 CAPABILITIES]
        │
        ├─ Capability Graph
        ├─ MCP Compiler
        └─ Skill Compiler
        │
        ▼

[M4 GOAL / PROMPT]
        │
        ├─ Task Graph
        ├─ Policy
        └─ Capability Binding
        │
        ▼

LATER

[A1 ALMA SELF / PERSONA]
        │
        ▼
[A2 ALMA AFFECT / DEVELOPMENT]
        │
        ▼
[S1 SOMA PERCEPTION]
        │
        ▼
[P1 POLO ACTION]
        │
        ▼
[N1 NERO ACCELERATION]
```

---

# 21. Roadmap Editing Policy

기존 roadmap / timeline 문서를 이 문서 기준으로 수정할 때:

```text
1. 기존 상위 순서를 이 문서와 맞춘다.
2. 중복된 G번호 체계를 제거하거나 Understanding Round로 한정한다.
3. 오래된 계획의 기능은 삭제하지 말고 적절한 phase 아래로 이동한다.
4. 새로운 기능은 새로운 상위 timeline item으로 끼워 넣지 말고 phase sub-item으로 배치한다.
5. Owner-fixed order를 변경하지 않는다.
6. 각 기능에는 earliest allowed phase와 target phase를 남긴다.
7. 현재 작업은 반드시 NOW 하나만 활성 상태로 둔다.
8. 완료된 단계는 다시 열지 않는다. 회귀 수정은 해당 단계의 maintenance item으로만 기록한다.
9. 새 아이디어는 먼저 배치만 하고, 현재 NOW를 밀어내지 않는다.
```

---

# 22. 최종 고정 순서

```text
M1  MARCO 1 Language Gate
 ↓
MARCO 1 Release
 ↓
M2  Self-Improving MARCO
 ↓
M3  Capability System
 ↓
M4  Goal / Prompt Compilation
 ↓
A1  ALMA Self / Persona
 ↓
A2  ALMA Affect / Development
 ↓
S1  SOMA Perception
 ↓
P1  POLO Action
 ↓
N1  NERO Acceleration
```

---

# 23. Owner Rule

> **This roadmap order is fixed.**

> **When a new feature is proposed, do not rewrite or reorder the timeline.  
> Decide where the feature belongs, record its dependencies, and attach it beneath the appropriate fixed phase.**

한국어:

> **이 타임라인의 상위 순서는 고정한다.  
> 새로운 기능이 생기면 타임라인을 다시 짜지 말고, 어느 단계에 들어갈지만 판단해서 해당 단계 아래에 추가한다.**

이 원칙은 Owner가 명시적으로 새 로드맵을 고정하기 전까지 유지한다.
