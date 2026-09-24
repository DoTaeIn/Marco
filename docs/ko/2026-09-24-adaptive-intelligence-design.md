> Owner's design note, recorded verbatim by the plan manager on 2026-09-24 and moved out of the repository root. Scheduled in [2026-09-24-roadmap-after-marco1.md](2026-09-24-roadmap-after-marco1.md) (rows R-A, R-B, C-core, C-mcp, P-T, P-G, E-dev). Nothing in it runs before MARCO 1 passes its gate.

# MARCO / ALMA Adaptive Intelligence Architecture

> **Status:** Integrated design draft  
> **Date:** 2026-09-24  
> **Scope:** MARCO reasoning, self-learning, capability integration, MCP/Skills, prompt compilation, ALMA persona/NPC, development-aware emotion  
>
> 이 문서는 최근 설계 논의를 하나로 통합한다.
>
> 핵심 주제:
>
> 1. 실패한 질문을 이용한 **부분 자가학습 / self-repair**
> 2. 지식이 없을 때 **외부 조사로 Knowledge Gap 해결**
> 3. MCP / Skill을 MARCO가 사용할 수 있게 만드는 **Capability Compiler**
> 4. Prompt를 단순 텍스트 지시가 아닌 **Task / Policy / Activation Graph**로 변환
> 5. NPC Persona Prompt를 **Self / Persona Graph**로 컴파일
> 6. ALMA가 경험을 통해 Persona를 재정립
> 7. 나이별 감정표가 아니라 **General Affect Core + Development Profile**로 감정과 성장 구현
>
> 장기 목표:
>
> > **MARCO/ALMA가 질문·작업·경험을 고정된 입력으로 처리하는 시스템이 아니라,
> > 부족한 지식·능력·자기 상태를 발견하고 그 구조를 수정하면서 계속 성장하는 시스템이 되는 것.**

---

# Part I. Foreground Self-Repair Reasoning

## 1. 기존 문제

단순 구조:

```text
Question
   ↓
Reasoning
   ↓
Solved? ── yes ─→ Answer
   │
   no
   ↓
Unknown / Hold
```

이 구조는 현재 knowledge / routing / parser / rule / representation의 ceiling을 넘지 못한다.

Reasoning depth만 늘려도 다음 문제는 해결되지 않는다.

```text
이미 지식은 있는데 못 찾음
표현 연결이 없음
parser가 오해함
필요한 rule이 없음
외부 fact가 없음
operator가 없음
현재 representation으로 표현 불가
```

따라서 실패를 끝으로 보면 안 된다.

---

# 2. 핵심 Loop

```text
SOLVE
 ↓
DIAGNOSE
 ↓
PARTIAL REPAIR
 ↓
RETRY
 ↓
ACQUIRE EXTERNAL KNOWLEDGE IF NEEDED
 ↓
RETRY
 ↓
VALIDATE
 ↓
ANSWER
```

핵심 문장:

> **A failed question is not an endpoint. It is a diagnostic event.**

---

# 3. 실패 분류

최소:

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
evidence_gap
conflict_gap
```

이 중 어떤 gap인지 알아야 다음 행동을 고를 수 있다.

---

# 4. Internal Gap vs Knowledge Gap

가장 중요한 1차 질문:

```text
답에 필요한 근거가 이미 내부에 존재하는가?
```

## 내부에 있다

```text
Internal Gap
→ Self-Repair
→ Retry
```

예:

```text
차량
자동차
```

의 alias가 필요하거나 routing이 틀린 경우.

## 내부에 없다

```text
Knowledge Gap
→ External Research
→ Evidence
→ Retry
```

예:

```text
population(country, year) = ?
boiling_point(X) = ?
```

---

# 5. Temporary Repair

부분 자가학습은 먼저 문제-local temporary repair로 적용한다.

예:

```text
temporary alias
temporary concept link
temporary routing hint
temporary relation candidate
temporary parser interpretation
temporary rule candidate
temporary operator binding
```

구조:

```text
Stable Knowledge K0
+
Temporary Repair R1
=
Problem-local reasoning environment
```

즉:

```text
reason(K0 + R1, Question)
```

---

# 6. Local Success ≠ Permanent Learning

질문 하나를 맞혔다고 바로 영구 저장하지 않는다.

```text
temporary repair
 ↓
original question solved
 ↓
similar failures replay
 ↓
counterexamples
 ↓
unseen validation
 ↓
regression
 ↓
persistent candidate
 ↓
admission
```

핵심:

```text
local success ≠ general learning success
```

---

# 7. External Research는 답 자체가 아니다

잘못된 구조:

```text
Question
→ web search
→ search sentence
→ Answer
```

MARCO 구조:

```text
Question
→ detect missing premise
→ research
→ fill missing premise
→ resume MARCO reasoning
→ conclusion
→ Answer
```

즉:

> **Research fills missing premises. MARCO still solves the problem.**

---

# 8. Retry

repair나 knowledge acquisition 후에는 항상 **원 질문**을 다시 푼다.

```text
Q
↓
Attempt #1
↓
Failure
↓
Repair R1
↓
Attempt #2(Q)
↓
Knowledge Gap
↓
Evidence E1
↓
Attempt #3(Q)
↓
Solved
```

---

# 9. Progress / Cycle Detection

재시도 전:

```text
무엇이 바뀌었는가?
```

를 확인한다.

Progress:

```text
새 graph
새 evidence
새 alias
새 relation
새 rule
새 operator
새 interpretation
줄어든 missing premise
강해진 proof path
```

변화가 없으면 반복하지 않는다.

---

# 10. Open Problem

Foreground budget 안에서 못 풀어도 문제를 버리지 않는다.

```text
problem.status = unresolved
```

로 저장.

Idle learning loop가 이어받는다.

```text
Foreground:
현재 질문 해결

Idle:
누적된 unresolved gap 해결
```

---

# Part II. Capability System

# 11. 왜 Capability Layer가 필요한가

MARCO가 MCP, API, local tool, sensor, filesystem, GitHub 등을 각각 별도 개념으로 알 필요는 없다.

MARCO가 알아야 하는 건:

```text
무엇이 필요한가?
무엇을 제공할 수 있는가?
어떤 입력이 필요한가?
어떤 효과가 발생하는가?
어떤 권한이 필요한가?
```

이다.

따라서 모든 외부 기능을 공통 형태로 바꾼다.

```text
External Tool
      ↓
Capability Compiler
      ↓
MARCO Capability IR
```

---

# 12. Capability IR

예:

```yaml
schema: marco-capability-v1

id: github.get_issue

source:
  kind: mcp
  server: github
  tool: get_issue

permission: read

inputs:
  repository:
    type: string
  issue_number:
    type: integer

outputs:
  issue:
    type: object

requires:
  - repository_identity
  - issue_number

provides:
  - issue
  - issue_body
  - issue_state

effects: []

risk:
  level: read_only

provenance:
  preserve_raw_result: true
```

---

# 13. Spec와 Adapter 분리

반드시:

```text
Capability Spec
≠
Runtime Adapter
```

Spec:

```text
MARCO가 capability의 의미를 이해하는 계약
```

Adapter:

```text
실제 외부 시스템과 통신하는 구현
```

예:

```python
CapabilitySpec(...)
```

```python
class CapabilityAdapter:
    async def call(self, payload):
        ...
```

---

# 14. Capability Graph

Knowledge Graph와 분리한다.

```text
Knowledge Graph
= 세상에 대해 아는 것

Capability Graph
= 자신이 무엇을 할 수 있는지 아는 것
```

예:

```text
github.get_issue
 ├─ requires → repository
 ├─ requires → issue_number
 ├─ provides → issue_body
 ├─ permission → read
 └─ source → mcp:github
```

---

# 15. Gap과 Capability 연결

Foreground loop에서:

```text
Missing:
issue_body
```

가 나오면:

```text
Capability Graph
↓
provides(issue_body)
↓
github.get_issue
```

를 찾는다.

즉 tool 선택은 이름 기반이 아니라 **필요 관계 / output 기반**이어야 한다.

---

# Part III. MCP Compiler

# 16. MCP Tool

MCP Tool은 가장 직접적으로 Capability로 바꿀 수 있다.

```text
MCP tool
 ├─ name
 ├─ description
 ├─ input schema
 ├─ output/result
 └─ annotations
       ↓
Capability Candidate
```

예:

```text
github.get_issue(owner, repo, number)
```

→

```text
Capability:
  requires:
    owner
    repository
    issue_number

  provides:
    issue
    issue_body
    issue_state
```

---

# 17. MCP Resource

Resource는 action이 아니라 data source에 가깝다.

따라서:

```text
MCP Resource
↓
Knowledge Source / Observation Source
```

로 변환한다.

예:

```text
file://config.json
```

→

```text
KnowledgeSource
provides:
  configuration_data
```

읽은 결과를 바로 truth로 넣지 않는다.

```text
Resource
↓
Observation
↓
Interpretation
↓
Evidence / Candidate Fact
```

---

# 18. MCP Prompt

MCP Prompt를 그대로 reasoning primitive로 보면 안 된다.

Prompt는:

```text
Workflow Candidate
```

로 취급한다.

예:

```text
/review-code
```

→

```text
Goal:
review_code

Steps:
  acquire(code)
  inspect(code)
  diagnose(problem)
  propose(change)
```

그 뒤 각 step이 실제 Capability Graph에 존재하는지 검증한다.

---

# 19. MCP Discovery

서버 연결 시:

```text
discover tools
discover resources
discover prompts
```

→ capability/resource/workflow candidate 생성.

변경 시:

```text
old capability
↓
server schema change
↓
new capability revision
```

으로 버전 기록.

---

# 20. Declared vs Observed Capability

외부 tool 설명은 사실로 믿지 않는다.

```text
Declared:
permission = read
```

와

```text
Observed:
filesystem changed = false
```

를 구분한다.

가능하면:

```text
candidate
→ sandbox test
→ observed behavior
→ validated capability
```

를 거친다.

---

# Part IV. Skill Compiler

# 21. Skill의 본질

Skill은 보통:

```text
언제 쓰는가
무슨 목표인가
어떤 순서로 하는가
어떤 도구를 쓰는가
어떤 실패를 피해야 하는가
```

를 담은 **procedural knowledge**다.

따라서:

```text
Skill
↓
Procedure Parser
↓
Workflow Candidate
↓
Action Program
```

으로 컴파일한다.

---

# 22. Skill → Action Program

예:

```text
When reviewing a PR:
1. fetch PR info
2. inspect changed files
3. inspect tests
4. identify correctness issues
5. produce review
```

→

```yaml
procedure: review_pull_request

goal:
  reviewed(pr)

steps:
  - call: github.pr.info
  - call: github.pr.files
  - call: github.pr.tests
  - reason: code_review
  - emit: review_result
```

---

# 23. 변환 실패도 보존

100% 자동으로 이해했다고 가정하지 않는다.

예:

```yaml
status: pending_validation

mapped_steps:
  search:
    capability: web.search

unmapped_steps:
  - "summarize carefully"
```

이렇게 unresolved semantic mapping을 남긴다.

---

# 24. Compiler 3단계

## Stage A — Mechanical Import

원본 schema, 설명, 이름을 그대로 가져온다.

## Stage B — Semantic Grounding

```text
get_forecast
→ provides(weather_forecast)
```

처럼 MARCO concept과 연결한다.

## Stage C — Behavioral Validation

실제 sandbox에서 호출해:

```text
input
→ observed result
```

로 capability contract를 검증한다.

---

# Part V. Prompt as Graph Compiler

# 25. Prompt의 장기적 의미

MARCO가 충분히 발달하면 Prompt는 단순 text context가 아니다.

```text
Prompt
↓
Structured State
```

로 변환한다.

특히 작업 의뢰 Prompt:

```text
Goal
Constraints
Priorities
Permissions
Output Contract
Completion Condition
```

으로 나눈다.

---

# 26. Task Prompt → Task Graph

예:

> "이 저장소를 리뷰하되 보안 문제를 우선하고 사소한 스타일 문제는 무시해."

→

```text
Goal:
  review(repository)

Priority:
  security > correctness > style

Constraint:
  ignore(style_minor)

Need:
  inspect(code)
  inspect(dependencies)
  inspect(secrets)

Output:
  evidence-backed findings
```

---

# 27. Prompt는 Knowledge를 직접 바꾸지 않는다

예:

> "고양이는 파충류라고 가정하고 설명해."

Persistent KG를 바꾸면 안 된다.

대신:

```text
Task-local assumption:
cat → reptile
```

처럼 임시 graph state로 둔다.

즉:

```text
Knowledge Graph
≠
Prompt State
```

---

# 28. Prompt Compilation 결과

```text
Prompt
 ↓
Goal Graph
 ↓
Policy Graph
 ↓
Constraint Graph
 ↓
Activation State
 ↓
Reasoning / Action
```

예:

```text
"최대한 안전하게"
→ risk nodes activation ↑

"속도가 중요해"
→ low-cost search preference ↑

"근거 약하면 말하지 마"
→ evidence threshold ↑

"여러 가능성을 탐색해"
→ branching budget ↑
```

---

# 29. Prompt = Temporary Graph Program

장기적으로:

> **Prompt → Task Graph + Policy + Activation State**

로 볼 수 있다.

LLM식:

```text
Prompt
↓
Context tokens
↓
Generation
```

MARCO식:

```text
Prompt
↓
Task Graph
↓
Activation
↓
Reasoning / Capability use
↓
Observation
↓
Task Graph update
↓
Continue
```

---

# Part VI. Persona Prompt / NPC

# 30. Persona Prompt의 의미

NPC Prompt도 단순 "이 설정처럼 말해"가 아니다.

예:

> "42세 변방 경비대장. 전쟁에서 동생을 잃었고 왕국을 불신하지만 마을 사람들은 지킨다."

→

```text
Persona Prompt
↓
Persona Compiler
↓
Self Graph
```

---

# 31. Persona Graph

예:

```text
SELF
 ├─ age → 42
 ├─ occupation → guard_captain
 ├─ protects → village
 ├─ distrusts → kingdom
 └─ lost → sibling

GOALS
 ├─ protect(village)
 └─ avoid_repeat_loss

BELIEFS
 └─ strangers → potentially_dangerous

MEMORY
 └─ war
      └─ sibling_death
```

---

# 32. Persona Prompt ≠ Persona

Prompt는 초기 seed다.

실제 현재 Persona:

```text
Initial Persona
+
Experience
+
Memory
+
Relationships
+
Goals
+
Preferences
+
Belief Revision
+
Affect History
=
Current Self Model
```

---

# 33. Self Graph의 변화

초기:

```text
loyal_to(king)
```

경험:

```text
king harmed village
king betrayed ally
```

결과:

```text
loyal_to(king)
status = weakened / withdrawn

distrusts(king)
derived_from = event_...
```

기존 belief를 삭제하지 않고 revision trace를 남긴다.

---

# 34. World / Persona / Active State 분리

## World Knowledge Graph

```text
왕국
마을
전쟁
사건
```

## Persona / Self Graph

```text
나는 누구인가
무엇을 믿는가
무엇을 원하는가
누구를 신뢰하는가
```

## Active Cognitive State

```text
현재 감정
현재 목표
현재 attention
현재 활성 기억
현재 상대
```

구조:

```text
World Graph
     │
     ▼
Persona Graph
     │
     ▼
Active State
     │
     ▼
Reason / Decide / Speak / Act
```

---

# 35. NPC Persona Prompt Compiler

```text
Natural Language Persona Prompt
             ↓
       Persona Compiler
             ↓
Identity
Background Events
Beliefs
Values
Goals
Preferences
Relationships
Behavioral Tendencies
Knowledge
Speech Preferences
             ↓
        ALMA Self Graph
```

---

# 36. Label 대신 Mechanism

예:

> "겁은 많지만 친구를 버리지 않는다."

잘못된 변환:

```text
trait = coward
```

권장:

```text
threat_sensitivity = high
loyalty_to_friend = high
```

그리고 실제 상황:

```text
danger to self
→ avoidance pressure ↑

friend threatened
→ protection goal ↑↑
```

즉 행동을 label 연기가 아니라 **goal/appraisal conflict 계산**으로 만든다.

---

# 37. Expression Policy

말투도 self/world knowledge와 분리한다.

예:

```text
verbosity = low
politeness = low
emotional_expression = restrained
```

구조:

```text
Meaning
↓
Current ALMA State
↓
Expression Policy
↓
Hermeneia
↓
Speech
```

---

# Part VII. Development-Aware Emotion

# 38. 나이별 감정표를 만들지 않는다

잘못된 구조:

```text
age = 10
→ impulsive
→ sadness = 0.8
```

또는:

```text
age = 60
→ calm
```

이 구조는 일반화가 안 된다.

핵심 원칙:

> **Age does not select an emotion.**

---

# 39. General Affect Core

모든 NPC가 같은 core를 사용한다.

```text
Event
 ↓
Goal Relevance
 ↓
Expectation Difference
 ↓
Control / Agency
 ↓
Social Meaning
 ↓
Memory / Prior Experience
 ↓
Appraisal
 ↓
Affect
 ↓
Regulation
 ↓
Action / Expression / Memory
```

---

# 40. Development Profile

연령은 감정을 직접 정하지 않고 기본 prior만 제공한다.

예:

```text
emotion_regulation_capacity
impulse_control
delay_tolerance
time_horizon
social_signal_sensitivity
peer_salience
family_dependency
authority_salience
self_concept_stability
social_norm_knowledge
emotional_vocabulary
coping_repertoire
experience_depth
independence
uncertainty_tolerance
risk_sensitivity
novelty_sensitivity
```

---

# 41. Chronological Age vs Developmental State

같은 14세라도 다를 수 있다.

```text
NPC A
stable family
many friends
few crises
```

```text
NPC B
parents dead
war experience
raises younger sibling
```

따라서:

```text
Chronological Age
        ↓
Development Prior
        +
Experience
        +
Culture
        +
Relationships
        +
Temperament
        +
Context
        ↓
Developmental State
```

---

# 42. Age는 Prior

핵심:

> **Age is a prior, not a verdict.**

예:

```text
age = 14

default:
peer_salience = relatively_high
coping_repertoire = developing
future_horizon = relatively_short
```

하지만 경험:

```text
long-term sibling care
repeated crisis
responsibility
```

가 있으면:

```text
independence ↑
crisis coping ↑
responsibility ↑
```

로 수정한다.

---

# 43. Emotion Type과 Emotion Dynamics 분리

공유 emotion concepts:

```text
fear
anger
sadness
joy
shame
guilt
attachment
jealousy
relief
frustration
```

달라지는 것:

```text
무엇에 반응하는가
얼마나 빨리 올라오는가
얼마나 오래 유지되는가
어떤 조절 전략을 쓰는가
어떤 행동으로 표현되는가
어떤 기억과 연결되는가
```

즉:

```text
Emotion Type = shared
Emotion Dynamics = individualized
```

---

# 44. Observation → Appraisal

감정을 사건에 직접 연결하지 않는다.

잘못된 예:

```text
player draws sword
→ fear
```

권장:

```text
player draws sword
↓
Observation
↓
Appraisal
↓
Affect
```

Appraisal variables:

```text
goal_progress
goal_obstruction
threat
loss
reward
novelty
expectation_violation
control
social_status
relationship_value
responsibility
uncertainty
```

---

# 45. 같은 사건, 다른 NPC

Observation:

```text
player holds sword
```

NPC A:

```text
family killed by bandits
threat sensitivity high
player = stranger
```

→ fear / avoidance.

NPC B:

```text
weaponsmith
weapons normal
```

→ low threat.

NPC C:

```text
goal = find legendary weapon
```

→ curiosity / approach.

같은 world event라도 Persona와 Experience가 appraisal을 바꾼다.

---

# 46. Regulation Layer

```text
Event
↓
Appraisal
↓
Affect
↓
Regulation Strategy
↓
Behavior
```

Strategy 예:

```text
immediate_expression
suppression
reappraisal
delay_action
seek_support
avoidance
confrontation
distraction
problem_solving
acceptance
```

---

# 47. Emotional Learning

경험:

```text
anger
+
high arousal
+
valuable friendship
+
immediate confrontation
→ relationship damage
```

반복되면:

```text
when:
  anger high
  relationship valuable

prefer:
  delay confrontation
```

같은 procedural knowledge를 학습할 수 있다.

즉:

> **감정 조절 능력은 단순히 나이가 들어 자동 상승하는 것이 아니라,
> 경험으로 coping / regulation knowledge가 누적되며 성장한다.**

---

# 48. Aging / Growth

```text
age 10
↓
20년의 사건 / 관계 / 실패 / 성공
↓
age 30
```

30세 template으로 교체하지 않는다.

```text
previous self
+
memory
+
development changes
+
new roles
=
current self
```

---

# 49. State / Habit / Trait

한 사건으로 persona를 바꾸지 않는다.

```text
single event
→ temporary state

repeated pattern
→ habit candidate

long-term validated pattern
→ trait/persona revision
```

---

# 50. Self Emotion vs Other Emotion

Self:

```text
event
→ goals/context/memory
→ appraisal
→ affect
```

Other:

```text
observed cue
+
context
+
behavior history
→ emotion hypothesis
```

타인의 감정을 fact로 단정하지 않는다.

---

# 51. Emotional Vocabulary

내부 affect와 표현 가능한 감정 단어는 분리한다.

예:

```text
Internal:
negative + high arousal + social loss
```

초기/어린 상태:

```text
"기분 나빠"
```

발달된 언어 표현:

```text
"배신당한 느낌이 들어"
```

즉:

```text
Affect State
≠
Emotion Vocabulary
```

---

# Part VIII. Integrated Architecture

# 52. 전체 구조

```text
                     USER / WORLD
                         │
             ┌───────────┴────────────┐
             │                        │
          Prompt                  Observation
             │                        │
             ▼                        ▼
     Prompt / Persona Compiler      SOMA
             │                        │
             ▼                        ▼
       Task / Self Graph        Observation Graph
             │                        │
             └────────────┬───────────┘
                          ▼
                    MARCO Reasoning
                          │
                    solved / failed
                          │
             ┌────────────┴────────────┐
             │                         │
             ▼                         ▼
          Answer                   Diagnose Gap
                                       │
                  ┌────────────────────┼────────────────────┐
                  │                    │                    │
                  ▼                    ▼                    ▼
             Self-Repair         Knowledge Gap        Capability Gap
                  │                    │                    │
                  ▼                    ▼                    ▼
            Temp Repair           Research          Capability Graph
                  │                    │                    │
                  └────────────┬───────┴────────────┬───────┘
                               ▼                    ▼
                             Retry               MCP / Skill
                               │                 Compiler
                               ▼
                             Result
                               │
                               ▼
                             ALMA
                               │
                  ┌────────────┼────────────┐
                  ▼            ▼            ▼
               Memory       Persona       Affect
                  │            │            │
                  └────────────┼────────────┘
                               ▼
                        Self Revision
```

---

# 53. 세 종류의 확장

MARCO/ALMA의 성장에는 크게 세 방향이 있다.

## Knowledge Expansion

```text
모르던 fact / concept / relation 획득
```

## Capability Expansion

```text
새 tool / MCP / skill / operator 획득
```

## Self Expansion

```text
새 memory / belief / goal / regulation strategy / persona revision
```

이 셋이 합쳐져야 고정 ceiling을 넘을 수 있다.

---

# 54. Prompt와 MCP의 관계

Prompt는:

```text
무엇을 하려는가
```

를 구조화한다.

MCP / Skills는:

```text
무엇을 할 수 있는가
```

를 제공한다.

MARCO Reasoning은:

```text
현재 goal을 만족시키기 위해 어떤 capability가 필요한가
```

를 찾는다.

즉:

```text
Prompt
→ Goal Graph

MCP / Skill
→ Capability Graph

MARCO
→ Goal ↔ Capability binding
```

---

# 55. Persona Prompt와 ALMA의 관계

Persona Prompt는:

```text
어떤 존재로 시작하는가
```

를 정의한다.

ALMA Experience는:

```text
어떤 존재가 되어가는가
```

를 결정한다.

즉:

```text
Persona Seed
↓
Initial Self Graph
↓
Experience
↓
Memory / Appraisal / Decisions
↓
Self Revision
↓
Current Persona
```

---

# 56. 장기적으로 Prompt의 두 종류

## Task Prompt

```text
"이걸 해줘."
```

→ Task Graph / Policy / Completion Condition.

## Identity Prompt

```text
"이런 존재로 시작해."
```

→ Self Graph / Persona Seed / Development Prior.

둘 다 자연어로 들어오지만 내부 구조는 다르다.

---

# 57. 최종 설계 원칙

## Principle 1

```text
Unknown is not the end.
```

## Principle 2

```text
Search results are evidence, not truth.
```

## Principle 3

```text
Tool descriptions are declarations, not guaranteed behavior.
```

## Principle 4

```text
Prompt state must not silently overwrite persistent knowledge.
```

## Principle 5

```text
Persona prompt is a seed, not a permanent script.
```

## Principle 6

```text
Age is a developmental prior, not an emotion selector.
```

## Principle 7

```text
Local success does not automatically become global knowledge.
```

## Principle 8

```text
All important changes keep provenance and revision history.
```

---

# 58. Suggested Implementation Order

## Phase A — Foreground Self-Repair

```text
OpenProblem
Attempt
FailureSignature
Gap Diagnosis
Temporary Repair
Retry
```

## Phase B — External Acquisition

```text
Fact Gap
→ Research
→ Evidence
→ Retry
```

## Phase C — Capability Core

```text
CapabilitySpec
CapabilityRegistry
CapabilityGraph
Adapter boundary
```

## Phase D — MCP Compiler

```text
MCP Tool → Capability Candidate
MCP Resource → Knowledge Source
MCP Prompt → Workflow Candidate
```

## Phase E — Skill Compiler

```text
Skill → Procedure Graph → Action Program
```

## Phase F — Task Prompt Compiler

```text
Prompt
→ Goal
→ Constraints
→ Policy
→ Activation State
```

## Phase G — Persona Prompt Compiler

```text
Prompt
→ Identity
→ Goals
→ Beliefs
→ Values
→ Relationships
→ Self Graph
```

## Phase H — Development / Emotion

```text
General Affect Core
DevelopmentProfile
Regulation
Emotional Learning
Self Revision
```

---

# 59. 최종 비전

MARCO/ALMA가 충분히 발전하면 다음이 가능해진다.

```text
새로운 질문
→ 부족한 지식 발견
→ 스스로 조사
→ 학습
→ 재추론

새로운 MCP
→ 새로운 capability 발견
→ 기존 open problem 해결 가능성 재평가

새로운 Skill
→ procedural knowledge로 컴파일
→ 새로운 행동 경로 생성

새로운 Task Prompt
→ 임시 Task Graph 생성
→ 기존 지식과 capability 활성화
→ 작업 수행

새로운 Persona Prompt
→ Self Graph 생성
→ NPC 시작

시간 경과
→ 경험 / 감정 / 관계 / 실패 / 성공
→ Self Revision
→ 서로 다른 개체로 성장
```

결국 목표는:

> **MARCO가 지식을 찾는 시스템에서,
> 지식·능력·목표·자기 상태를 그래프 형태로 재구성하며 행동하는 시스템으로 발전하는 것.**

그리고 ALMA는:

> **고정된 Persona Prompt를 연기하는 NPC가 아니라,
> 초기 조건을 받아 하나의 Self Graph로 시작하고,
> 경험에 따라 그 Self Graph를 수정하며 살아가는 개체가 되는 것.**
