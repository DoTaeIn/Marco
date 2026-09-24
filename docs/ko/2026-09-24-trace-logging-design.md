# MARCO Trace / Event Logging Architecture

Owner's design note, recorded verbatim by the plan manager on 2026-09-24. The
goal that implements the first part is `docs/ko/2026-09-24-trace-ledger-goal.md`
(L1); the post-gate parts are scheduled in `docs/ko/2026-09-24-roadmap-after-marco1.md`.

---

Status: Design note
Date: 2026-09-24
Scope: MARCO / SOMA / ALMA / POLO 공통 로그·추적·provenance 구조

이 문서는 구현 완료 사항을 주장하지 않는다.
향후 디버깅, 설명 가능성, 기억 복원, 감각 검증, 자기 개선 평가를 위한 공통 로그 설계 아이디어다.

## 1. 목적

MARCO 계열에서 로그는 단순한 디버깅 출력이 아니다.
일반 애플리케이션의 로그가 주로:

```
함수 호출
오류 발생
작업 성공
```

을 기록한다면, MARCO의 로그는 다음 질문에 답할 수 있어야 한다.

```
왜 이 답을 했는가?
무엇을 관찰했는가?
어떤 근거를 사용했는가?
어떤 후보를 버렸는가?
어떤 규칙을 적용했는가?
무엇이 상태를 바꿨는가?
이 믿음은 어디서 생겼는가?
이 감정 상태의 원인은 무엇인가?
이 결론을 지금 다시 재현할 수 있는가?
```

따라서 로그 시스템의 목적은:
행동의 기록이 아니라 판단의 계보를 기록하는 것
이다.

## 2. 핵심 철학

MARCO 로그의 기본 원칙:
Do not log only what MARCO said.
Log what happened, what was observed, what was inferred, what changed, and why.
한국어:
MARCO가 무슨 말을 했는지만 기록하지 않는다.
무엇이 일어났고, 무엇을 관찰했고, 무엇을 추론했고, 무엇이 바뀌었으며, 왜 그렇게 되었는지를 기록한다.

## 3. 로그는 사실상 두 번째 그래프다

MARCO에는 크게 두 종류의 그래프가 존재할 수 있다.
Knowledge Graph

```
"What does MARCO know?"
```

무엇을 알고 있는지를 나타낸다.
Trace / Event Graph

```
"How did MARCO come to know or conclude this?"
```

왜 그렇게 알게 되었는지를 나타낸다.
즉:

```
Knowledge Graph
= knowledge structure

Trace Graph
= provenance / reasoning history
```

이다.

## 4. Append-Only Event Ledger

원본 로그는 가능한 한 append-only event ledger로 유지한다.
기존 로그를 수정해서 현재 상태만 남기지 않는다.
예:

```
belief created
belief reinforced
belief contradicted
belief withdrawn
replacement belief created
```

각 단계가 모두 남아야 한다.
최종 상태만:

```
belief = false
```

라고 저장하면 과거의 판단 과정을 복구할 수 없다.

## 5. Event Envelope

모든 이벤트는 공통 envelope를 가진다.
예시:

```
{
  "schema": "marco-event-v1",

  "event_id": "evt_01...",
  "trace_id": "trace_01...",
  "parent_ids": ["evt_00..."],

  "timestamp": {
    "observed_at": 1789990123.123,
    "processed_at": 1789990123.135
  },

  "system": "MARCO",
  "subsystem": "reasoning",

  "kind": "rule_applied",
  "status": "success",

  "epistemic_status": "inferred",

  "subject": "entity_17",

  "input_refs": [],
  "output_refs": [],

  "source": {},
  "operation": {},
  "payload": {},

  "runtime": {}
}
```

## 6. 세 개의 핵심 ID

최소한 다음 세 개의 개념은 반드시 있어야 한다.
event_id
각 사건 자체의 고유 ID.

```
evt_18931
```

trace_id
한 번의 요청 또는 하나의 reasoning episode 전체를 묶는다.
예:

```
사용자 질문
↓
routing
↓
evidence search
↓
reasoning
↓
answer
```

모두 같은 `trace_id`.
parent_ids
이 이벤트의 직접적인 원인을 나타낸다.
단일 `parent_id`보다 배열이 좋다.
MARCO의 결론은 보통:

```
Evidence A ─┐
Evidence B ─┼→ Conclusion
Rule R ─────┘
```

처럼 여러 부모를 가질 수 있기 때문이다.
따라서:

```
{
  "parent_ids": [
    "evt_evidence_a",
    "evt_evidence_b",
    "evt_rule_r"
  ]
}
```

형태가 적합하다.

## 7. Trace는 Tree가 아니라 DAG다

MARCO의 reasoning trace는 대부분 단순한 트리가 아니다.
같은 observation이 여러 추론에 사용될 수 있고, 여러 근거가 하나의 결론으로 모일 수 있다.
따라서:

```
Directed Acyclic Graph
```

형태로 보는 것이 적절하다.
예:

```
Observation A ─────┐
                   ├─→ Hypothesis C ──┐
Observation B ─────┘                  │
                                      ├─→ Conclusion E
Rule D ───────────────────────────────┘
```

## 8. 로그 종류를 분리한다

최소한 다음 이벤트 범주는 구분한다.

```
OBSERVATION
INTERPRETATION
REASONING
DECISION
MUTATION
OUTPUT
```

이들을 하나의 `message` 로그로 뭉개지 않는다.

## 9. OBSERVATION

실제로 무엇이 관찰되었는가.
가능한 한 의미 해석을 넣지 않는다.
예:

```
{
  "kind": "observation",
  "epistemic_status": "observed",

  "payload": {
    "type": "object_position",
    "entity": "visual_17",
    "x": 0.32,
    "y": 0.61
  }
}
```

좋은 observation:

```
entity_17의 위치가 x=.32, y=.61
```

나쁜 observation:

```
빨간 공이 움직였다
```

후자는 이미 object identity와 movement interpretation이 섞여 있다.

## 10. INTERPRETATION

관찰에서 의미 후보가 만들어진 경우.
예:

```
{
  "kind": "hypothesis",
  "epistemic_status": "hypothesized",

  "input_refs": [
    "evt_shape_17",
    "evt_color_17"
  ],

  "payload": {
    "concept": "red_ball",
    "confidence": 0.78
  }
}
```

핵심:

```
Observation ≠ Hypothesis
```

이다.

## 11. REASONING

MARCO가 실제로 어떤 규칙이나 관계를 적용했는지 기록한다.
예:

```
{
  "kind": "rule_applied",
  "epistemic_status": "inferred",

  "input_refs": [
    "evt_before_position",
    "evt_after_position"
  ],

  "operation": {
    "type": "rule",
    "id": "movement_v1",
    "version": "1"
  },

  "payload": {
    "bindings": {
      "x": "entity_17"
    },

    "result": {
      "predicate": "moved",
      "subject": "entity_17"
    }
  }
}
```

## 12. DECISION

후보들 중 무엇을 선택했는지 기록한다.
최종 승자만 저장하지 않는다.
예:

```
{
  "kind": "decision",

  "payload": {
    "candidates": [
      {
        "id": "graph_a",
        "score": 0.73
      },
      {
        "id": "graph_b",
        "score": 0.71
      }
    ],

    "selected": "graph_b",

    "reason": "stronger_grounded_evidence"
  }
}
```

이렇게 해야 나중에:

```
왜 점수가 높은 graph_a를 버렸는가?
```

에 답할 수 있다.

## 13. MUTATION

실제 상태가 변경된 경우.
생각한 것과 상태 변경을 구분한다.
예:

```
{
  "kind": "state_mutation",

  "payload": {
    "target": "belief:381",
    "operation": "withdraw",

    "reason": "contradicting_evidence",

    "replacement": "belief:419"
  }
}
```

ALMA에서는 특히 중요하다.

```
considered
```

와:

```
stored / changed
```

를 구분해야 한다.

## 14. OUTPUT

사용자에게 실제로 무엇을 보여줬는지도 기록한다.
하지만 OUTPUT은 reasoning의 원인이 아니라 결과다.

```
{
  "kind": "spoken_output",

  "parent_ids": [
    "evt_final_conclusion"
  ],

  "payload": {
    "text": "물체가 오른쪽으로 이동했습니다."
  }
}
```

따라서:

```
output text
```

만으로 reasoning을 복원하려고 해서는 안 된다.

## 15. Why Chain

별도의 explanation 데이터를 새로 만드는 대신 trace graph를 역방향으로 따라간다.
예:

```
Answer #900
    ↓
Conclusion #880
    ↓
RuleApplication #731
    ↓
Evidence #512
Evidence #519
    ↓
Observation #201
    ↓
Source frame #19291
```

사용자가:

```
"왜 그렇게 답했어?"
```

라고 하면 이 경로를 사람이 읽을 수 있는 형태로 변환한다.
예:

```
entity_17의 위치가 A에서 B로 변경된 것이 관찰되었습니다.

movement_v1 규칙은 동일한 개체의 시간에 따른 위치 변화가 확인되면
이동 사건으로 판정합니다.

따라서 entity_17이 이동했다고 판단했습니다.
```

즉:
Explanation = Trace Graph의 projection
으로 본다.

## 16. Epistemic Status

모든 중요한 지식/관찰/결론에는 인식론적 상태를 붙인다.
예:

```
observed
reported
hypothesized
inferred
assumed
verified
contradicted
withdrawn
unknown
```

observed
센서나 직접 입력에서 관찰됨.
reported
사용자 또는 다른 주체가 주장함.

```
사용자가 "민수는 집에 있다"고 말했다.
```

이것은:

```
민수는 집에 있다 = verified
```

가 아니다.
hypothesized
관찰을 바탕으로 만든 가설.
inferred
규칙을 통해 도출됨.
assumed
가정적 reasoning을 위해 임시로 둔 전제.
verified
정의된 검증 기준을 만족함.
contradicted
다른 근거와 충돌함.
withdrawn
과거에는 활성 상태였지만 철회됨.
unknown
판단하기 위한 충분한 근거가 없음.

## 17. Source Provenance

모든 observation 또는 외부 근거는 가능한 한 원본 위치를 가리킨다.
이미지 예:

```
{
  "source": {
    "type": "camera_frame",
    "ref": "frames/camera1/001928.jpg",
    "sha256": "...",

    "region": [
      120,
      80,
      440,
      390
    ]
  }
}
```

오디오:

```
{
  "source": {
    "type": "audio",
    "ref": "audio/2026-09-24/a812.wav",

    "start": 12.31,
    "end": 13.80,

    "sha256": "..."
  }
}
```

문서:

```
{
  "source": {
    "type": "document",
    "document_id": "...",
    "page": 12,
    "span": [381, 440]
  }
}
```

## 18. Raw Data는 로그 본체에 복사하지 않는다

원본 이미지, 오디오, 영상 등을 event마다 복사하면 저장 비용이 급격히 증가한다.
따라서:

```
Event Ledger
→ metadata + reference + hash

Blob Storage
→ actual raw data
```

로 분리한다.
원본이 삭제되는 경우:

```
source_available = false
```

같은 상태를 남겨야 한다.
원본이 없는데 여전히 완전 검증 가능하다고 표시하면 안 된다.

## 19. Runtime Version

같은 입력도 MARCO 버전에 따라 결과가 달라질 수 있다.
따라서 반드시 실행 버전을 남긴다.
예:

```
{
  "runtime": {
    "marco_version": "1-preview3",
    "build": "a7c20b2"
  },

  "components": {
    "router": "character-coverage-v2",
    "reasoner": "graph-inference-v4",
    "soma": "perception-v1"
  },

  "knowledge": {
    "model_id": "marco-ko-20260924",
    "revision": 381
  }
}
```

이를 통해:

```
왜 옛날에는 틀렸는데 현재는 맞는가?
```

를 재현할 수 있다.

## 20. Before / After

상태 변경 이벤트에서는 가능하면 이전과 이후를 같이 기록한다.
예:

```
{
  "kind": "state_change",

  "payload": {
    "field": "count",

    "before": 10,
    "after": 7,

    "cause": "evt_381"
  }
}
```

최종값만:

```
count = 7
```

이라고 저장하면 변화 과정 추적이 어려워진다.

## 21. Correction / Retraction

교정은 기존 기록을 지우지 않는다.
예:

```
belief_10
status = withdrawn

belief_11
supersedes = belief_10
```

Event Graph:

```
belief_10
   │
   ├── contradicted_by → evidence_90
   │
   └── superseded_by → belief_11
```

과거의 잘못된 판단도 역사로 남는다.

## 22. 실패도 Event다

MARCO에서 실패는 매우 중요한 정보다.
예:

```
unknown
hold
ambiguous
missing evidence
contradiction
routing failure
parser failure
unsupported capability
```

이런 결과도 1급 이벤트로 저장한다.
예:

```
{
  "kind": "reasoning_result",
  "status": "hold",

  "payload": {
    "reason": "insufficient_evidence",

    "missing": [
      "object_identity",
      "causal_link"
    ]
  }
}
```

## 23. 실패 로그는 Benchmark 데이터가 된다

구조화된 실패 기록이 쌓이면 자동으로 진단 통계를 만들 수 있다.
예:

```
answerable failures

47% routing
31% missing evidence
12% ambiguous entity
10% parser
```

따라서 Trace Ledger는 단순 기록이 아니라:

```
debug dataset
benchmark dataset
learning candidate source
regression source
```

역할까지 할 수 있다.

## 24. SOMA Trace

SOMA는 perception 결과의 생성 과정을 추적할 수 있어야 한다.
예:

```
Frame #100
  ↓
Edge Observation #110
  ↓
Contour #120
  ↓
Region #130
  ↓
Shape Hypothesis #140
  ↓
Entity Candidate #150
```

MARCO는 `Entity Candidate #150`만 보는 것이 아니라 필요하면 원본 frame까지 거슬러 갈 수 있다.

## 25. ALMA Affect Trace

감정도 최종 라벨만 저장하지 않는다.
나쁜 구조:

```
emotion = frustration
```

좋은 구조:

```
Event #10
action_failed

       ↓

Appraisal #20
goal_obstruction = 0.9

Appraisal #21
expectation_violation = 0.8

Appraisal #22
control = 0.5

       ↓

Affect #30
frustration-like

       ↓

Decision #40
retry_selected
```

그러면:

```
"왜 그때 좌절 상태였어?"
```

에 근거를 따라 답할 수 있다.

## 26. Mental State Trace

ALMA의 믿음, 기대, 목표도 world fact와 섞지 않는다.
예:

```
World:
door_closed

ALMA belief:
door_open

source:
old observation
```

로그에서는:

```
World Event
Mental Event
```

를 별도로 관리해야 한다.

## 27. User / ALMA / World Scope

각 이벤트에는 필요할 경우 관점(scope)을 둔다.
예:

```
{
  "scope": {
    "world": true,
    "holder": null
  }
}
```

또는:

```
{
  "scope": {
    "world": false,
    "holder": "alma"
  }
}
```

또는:

```
{
  "scope": {
    "world": false,
    "holder": "person_A"
  }
}
```

이를 통해:

```
실제 사실
ALMA의 믿음
A에 대한 ALMA의 추정
A가 직접 보고한 상태
```

를 구분한다.

## 28. Candidate Logging

후보 탐색에서는 모든 후보를 무제한 저장할 필요는 없다.
하지만 적어도:

```
winner
top-k alternatives
threshold
reason for rejection
```

정도는 남기는 것이 좋다.
예:

```
{
  "kind": "routing_decision",

  "payload": {
    "selected": "graph_b",

    "candidates": [
      {
        "graph": "graph_a",
        "score": 0.73,
        "grounded": false
      },
      {
        "graph": "graph_b",
        "score": 0.71,
        "grounded": true
      }
    ]
  }
}
```

## 29. Thinking Budget Trace

향후 reasoning budget이 생긴다면:

```
{
  "kind": "deliberation_budget",

  "payload": {
    "initial": 100,
    "used": 63,

    "operations": {
      "graph_expand": 10,
      "rule_apply": 21,
      "candidate_check": 32
    }
  }
}
```

같은 형태로 기록할 수 있다.
그러면:

```
계산량 증가가 실제 정확도 향상으로 이어졌는가?
```

를 측정할 수 있다.

## 30. Multi-Goal Trace

하나의 사용자 요청에 여러 query가 있다면 하나의 trace 아래 여러 goal branch를 둔다.

```
trace_100

User Input
   │
   ├─ Goal A
   │    └─ reasoning...
   │
   ├─ Goal B
   │    └─ reasoning...
   │
   └─ Goal C
        └─ reasoning...
```

각 goal에는:

```
goal_id
origin = user
```

를 남긴다.

## 31. Generated Subgoal Trace

MARCO가 향후 스스로 하위 목표를 만들 경우 사용자 goal과 구분한다.

```
{
  "kind": "goal_created",

  "payload": {
    "goal_id": "goal_sub_18",
    "origin": "generated",
    "parent_goal": "goal_user_1",

    "reason": "missing_required_fact"
  }
}
```

이를 통해:

```
사용자가 시킨 것
MARCO가 해결을 위해 스스로 만든 것
```

을 구분할 수 있다.

## 32. Human-readable Log와 Machine Log를 분리한다

원본은 항상 구조화된 이벤트다.
예:

```
{
  ...
}
```

사람에게는 별도의 projection으로 보여준다.
예:

```
13:52:31.124 OBS  camera1/frame9182
               entity_17 observed at (0.21, 0.64)

13:52:31.137 OBS  entity_17 observed at (0.58, 0.64)

13:52:31.144 INF  movement_v1
               x changed 0.21 → 0.58

13:52:31.146 CON  entity_17 moved
```

중요:
Pretty log는 원본이 아니다.
구조화된 ledger가 진짜 데이터다.

## 33. Storage Format

초기 구현에는 JSONL이 적합하다.
예:

```
logs/
  2026-09-24.jsonl
```

한 줄에 한 event.
장점:

```
append 쉬움
부분 손상에 강함
grep 가능
Python에서 간단함
사람도 열어볼 수 있음
향후 변환 쉬움
```

규모가 커지면 SQLite 등으로 옮길 수 있다.

## 34. SQLite 전환 시 주요 Index

추천:

```
event_id
trace_id
parent_id / parent relation
timestamp
kind
system
subject
epistemic_status
```

복잡한 payload 전체에 index를 걸 필요는 없다.

## 35. Log Level은 의미 수준과 별개다

일반적인:

```
DEBUG
INFO
WARN
ERROR
```

도 사용할 수 있지만 이것만으로 이벤트 의미를 표현하지 않는다.
예:

```
level = INFO
kind = observation
```


```
level = INFO
kind = rule_applied
```


```
level = WARN
kind = conflicting_evidence
```

처럼 별도 필드로 둔다.

## 36. 개인정보 / 원본 보존

감각 로그에는 이미지, 음성, 대화 등 민감한 자료가 들어갈 수 있다.
따라서 원본과 event metadata의 retention을 분리한다.
예:

```
raw frame
retention = 24h

derived observation
retention = long-term
```

원본이 삭제되면:

```
source_verification = unavailable
```

상태를 남긴다.

## 37. Deterministic Replay

가능한 이벤트는 재생 가능해야 한다.
예:

```
source hash
runtime build
knowledge revision
rule version
parameters
```

가 있으면 같은 입력을 다시 실행해 결과를 비교할 수 있다.
완전히 deterministic하지 않은 외부 component가 있다면:

```
replay_status = approximate
```

등으로 표시한다.

## 38. 추천 최소 Schema

초기 구현에서 과도하게 복잡하게 만들 필요는 없다.
최소형:

```
{
  "event_id": "evt_...",
  "trace_id": "trace_...",
  "parent_ids": [],

  "timestamp": 0,

  "system": "MARCO",
  "subsystem": "reasoning",

  "kind": "rule_applied",
  "status": "success",

  "epistemic_status": "inferred",

  "subject": null,

  "input_refs": [],
  "output_refs": [],

  "source": {},
  "operation": {},
  "payload": {},

  "runtime": {
    "build": "..."
  }
}
```

필요가 확인될 때 필드를 늘린다.

## 39. 추천 Event Kinds

초기 후보:

```
input_received

observation_created
observation_updated

hypothesis_created
hypothesis_rejected
hypothesis_verified

routing_candidates
routing_selected

evidence_found
evidence_rejected

rule_applied
rule_blocked

contradiction_found

conclusion_created
conclusion_withdrawn

goal_created
goal_completed
goal_failed

subgoal_created

state_changed

memory_created
memory_recalled
memory_withdrawn

belief_created
belief_revised

appraisal_created
affect_changed

action_proposed
action_approved
action_executed
action_failed

output_created

unknown
hold
error
```

고정 enum으로 시작하기보다는 실제 구현에서 필요한 종류를 확인하면서 안정화할 수 있다.

## 40. MARCO Trace 예시

질문:

```
"아까 물체가 움직였어?"
```

Trace:

```
input_received
    ↓
entity_reference_resolved
    ↓
observation_before_found
    ↓
observation_after_found
    ↓
rule_applied: movement_v1
    ↓
conclusion_created: moved(entity_17)
    ↓
output_created
```

## 41. SOMA Trace 예시

```
camera frame
    ↓
region detected
    ↓
track associated
    ↓
position observed
    ↓
position changed
    ↓
movement observation
    ↓
MARCO reasoning
```

## 42. ALMA Trace 예시

```
goal active
    ↓
action attempted
    ↓
action failed
    ↓
goal obstruction measured
    ↓
expectation violation
    ↓
appraisal state
    ↓
frustration-like affect
    ↓
retry decision
```

## 43. 최종 구조

```
                       SOURCE
                          │
                          ▼
                    OBSERVATION
                          │
                          ▼
                   INTERPRETATION
                          │
                          ▼
                      REASONING
                          │
                          ▼
                      DECISION
                          │
                          ▼
                      MUTATION
                          │
                          ▼
                       OUTPUT
```

모든 단계는 event ID로 연결된다.
그리고:

```
Trace Graph
     │
     ├─ Debugging
     ├─ Explanation
     ├─ Benchmark
     ├─ Replay
     ├─ Memory provenance
     ├─ Emotion provenance
     ├─ Perception verification
     └─ Self-improvement evaluation
```

으로 활용된다.

## 44. 최종 원칙

Principle 1
Everything important becomes an event.
중요한 변화는 로그 문자열이 아니라 구조화된 event가 된다.
Principle 2
Never overwrite history to represent correction.
교정은 삭제가 아니라 새 이벤트와 관계로 표현한다.
Principle 3
Observation, hypothesis, inference and fact are different things.
서로 다른 epistemic status로 관리한다.
Principle 4
Every conclusion should have parents.
근거 없는 결론이 trace graph에 갑자기 나타나면 안 된다.
Principle 5
Failures are evidence.
unknown, hold, contradiction, parser failure도 기록하고 분석한다.
Principle 6
The log itself should be explainable.
사람용 explanation은 별도의 진실이 아니라 trace graph의 projection이다.

## 45. 한 문장 요약

Knowledge Graph는 MARCO가 무엇을 아는지 기록하고,
Trace Graph는 MARCO가 왜 그렇게 알게 되었는지를 기록한다.
그리고 가장 중요한 설계 문장:
MARCO should never have to say “I don't know why I thought that.”
