# MARCO / SOMA / ALMA — Perception, Reasoning, Emotion Philosophy

Status: Idea / design note
Date: 2026-09-24
Author: repository owner. Recorded verbatim by the plan manager on 2026-09-24.

이 문서는 현재 구현 완료 사항을 주장하는 문서가 아니다.
기존 MARCO 로드맵과 freeze decision을 대체하지 않으며, 향후 Vision / Audio / ALMA / Planning 설계를 위한 철학과 구조 아이디어를 기록한다.

## 1. 출발점

MARCO의 초기 철학은 강한 형태의 다음 원칙에 가까웠다.

* 토큰 기반 생성 모델을 사용하지 않는다.
* 근거 없는 답을 만들지 않는다.
* 사람이 작성한 지식과 규칙 안에서 판단한다.
* 판단의 이유를 추적할 수 있어야 한다.
* 모르는 것은 `unknown`으로 남긴다.
* 가능한 한 판단 과정을 증명 가능하게 만든다.

텍스트 입력에서는 이 철학이 비교적 잘 작동한다.
사람이 이미 현실을 언어로 표현해 주기 때문이다.

```
현실
 ↓
인간의 인식
 ↓
"빨간 공이 책상 위에 있다"
 ↓
MARCO
```

즉 자연어 자체가 이미 상당히 높은 수준으로 구조화된 감각 입력이다.
그러나 이미지, 음성, 영상, 센서 입력에서는 문제가 달라진다.

```
이미지 → pixel array
음성   → waveform
센서   → numeric stream
```

이 원시 입력에는 이미 해석된 의미가 존재하지 않는다.
따라서 멀티모달 MARCO를 만들려면 다음 질문을 해결해야 한다.
원시 감각을 굳이 텍스트나 토큰으로 변환하지 않고도 MARCO가 사용할 수 있는 의미 구조로 만들 수 있는가?
이 문서의 결론은 가능하다이다.

## 2. 토큰을 없애는 것과 숫자를 없애는 것은 다르다

컴퓨터가 감각을 처리하려면 결국 계산은 필요하다.

```
Text   → character/code values
Image  → pixel values
Audio  → waveform samples
Sensor → measurements
```

따라서 목표는 "계산하지 않는 AI"가 아니다.
목표는: 원시 입력을 토큰 기반 언어 표현으로 강제로 변환하지 않고, 관찰 가능한 구조를 직접 추출하는 것이다.

즉 다음 경로를 피한다.

```
IMAGE → caption → text → parser → meaning
```

대신:

```
IMAGE → observable structure → Observation Graph → MARCO
```

를 사용한다.

## 3. MARCO의 내부 공용어는 텍스트가 아니라 그래프다

텍스트는 MARCO의 본질적인 내부 표현이 아니다. 텍스트도 하나의 입력 modality일 뿐이다.
모든 입력은 최종적으로 같은 구조로 변환될 수 있다.

```
                 TEXT
                   │
                Parser
                   │
                   ▼
IMAGE ───────→ Observation Graph ←────── AUDIO
                   ▲
                   │
                SENSOR
                   │
                   ▼
                 MARCO
```

공통 의미 표현은 다음과 같은 primitive를 중심으로 한다.

```
Entity, Property, Relation, Event, State, Quantity, Time, Source, Confidence, Provenance
```

예를 들어 텍스트 "민수가 공을 옮겼다."는

```
Event #91
type   = move
actor  = person_minsu
object = ball_3
```

가 될 수 있다. 영상에서는 이름을 몰라도 된다.

```
Event #103
type   = movement_observed
actor  = unknown_entity_7
object = unknown_entity_17
```

즉 언어를 거치지 않고 동일한 세계 모델에 들어갈 수 있다.

## 4. Anonymous Entity First

Vision에서 가장 중요한 원칙 중 하나다. 처음부터 모든 것을 dog / cup / person / car 라고 분류하려 하지 않는다.
먼저 `entity_17`이라고만 한다. 그리고 관찰된 속성을 붙인다.

```
entity_17
position = (241, 332)
shape    = approximately_round
color    = red
motion   = stationary
```

이후 시간에 따라 t1: x=100, t2: x=150, t3: x=220 이라면, 정체를 몰라도 `entity_17 moved_right`은 판단할 수 있다.

지능은 모든 것의 이름을 아는 능력이 아니다. 이름이 없어도 존재, 변화, 관계, 사건을 이해할 수 있다.

## 5. Object Recognition보다 Event Recognition을 먼저 한다

일반적인 Vision 시스템은 흔히 "What is this?"를 먼저 해결하려 한다.
MARCO/SOMA에서는 오히려 "What happened?", "What changed?", "What is related to what?"를 우선할 수 있다.

```
t1: object_17 is on table
t2: object_22 approaches object_17
t3: object_22 overlaps object_17
t4: object_17 changes position
```

이때 object_17이 컵인지 블록인지 몰라도 `object_17 moved`은 강하게 말할 수 있다.
그러나 `object_22 pushed object_17`은 인과 추론이다. 따라서 다음을 구분한다.

```
Observed:   object_22 approached object_17; object_22 overlapped object_17; object_17 moved
Inferred:   object_22 may have caused movement
Not proven: object_22 definitely pushed object_17
```

이 구분이 MARCO의 기존 철학과 잘 맞는다.

## 6. SOMA의 역할

SOMA — What can I observe? 감각 입력으로부터 측정 가능한 것을 추출한다. 세계가 무엇을 "의미한다"고 최종 결정하지 않는다.
(edge, corner, region, motion, frequency, pitch, distance, overlap, temperature, pressure)

MARCO — What follows from those observations? 관계를 판단하고, 사건을 연결하고, 기존 지식과 비교하고, 규칙을 적용하고, 반례를 찾고, 결론을 만든다.

```
SOMA  = perception / measurement
MARCO = cognition / reasoning
```

## 7. 공통 Perception Pipeline

```
RAW SIGNAL → MEASUREMENT → SEGMENT → ENTITY → RELATION → EVENT → CONCEPT → REASONING
```

Image: pixels → edges / color / regions → object candidates → spatial relations → movement / interaction events → concept candidates
Audio: waveform → energy / frequency / pitch / formants → acoustic segments → source / temporal relations → acoustic events → speech/sound concept candidates
Sensors: numeric stream → measurements → changes / intervals → state transitions → events
Text: characters → clauses → entities / relations / events → meaning

따라서 최종적으로는 Text도 하나의 Sensor Adapter처럼 볼 수 있다.

## 8. Observation Primitive와 Concept Hypothesis를 분리한다

Observation Primitive: 직접 측정하거나 재현하기 쉬운 값 (brightness, hue, edge, corner, contour, region, motion, overlap, distance; energy, pitch, frequency, duration, onset, harmonic structure, spectral change; temperature, pressure, acceleration, distance). 이 층은 가능한 한 측정에 가깝게 유지한다.

Concept Hypothesis: 그 위에 의미를 붙인 것 ("cup", "dog", "running", "angry", "request"). 이것은 사실이 아니라 Hypothesis이다.

```
hypothesis:  concept = cup
evidence:    shape_signature, handle_like_region, stable tabletop position
confidence:  0.74
```

이 구조를 유지하면 감각 모델이 틀려도 세계 사실이 자동으로 오염되지 않는다.

## 9. Perceptual Graph Compiler

```
Sensory Stream → Perceptual Graph Compiler → Observation Graph → MARCO
```

SOMA does not have to decide what the world means. SOMA records what it can measure. MARCO decides what follows.
SOMA는 세상이 무엇을 의미하는지 최종 결정하지 않는다. SOMA는 측정 가능한 것을 기록하고, MARCO가 그 의미와 결론을 판단한다.

## 10. 이미지에서의 증명 가능성

기존 강한 주장: 모든 판단 과정은 증명 가능해야 한다.
수정된 주장: 모든 결론은 어떤 관찰, 가정, 규칙에서 나왔는지 추적 가능해야 한다.
MARCO proves conclusions, not sensors.

```
Observation #812  type = edge, source = camera1/frame3812, operator = edge_detector_v1
Observation #813  type = closed_contour, parents = [#812]
Observation #814  type = approximately_rectangular, parents = [#813], checks: corner_count = 4
Hypothesis  #815  concept = box, parents = [#814, color_observation]
```

```
raw input → measurement → observation → relation → hypothesis → rule → conclusion
```

## 11. Neural Perception을 허용할 경우의 경계

MARCO의 핵심 철학을 "No neural network" 자체로 정의할 필요는 없다. 더 중요한 원칙은:

1. 생성 모델이 추론을 대신하지 않는다.
2. perception 결과를 ground truth로 취급하지 않는다.
3. 관찰과 사실을 분리한다.
4. 결론의 근거 경로를 유지한다.
5. unknown을 허용한다.

따라서 필요할 경우 YOLO, Whisper, OCR, Pose Detector, Feature Extractor 같은 학습 모델을 센서로 사용할 수 있다.

```
detector observation: candidate_class = dog, confidence = 0.91, source = camera1/frame382, model = detector-x-v4, verified = false
```

이것은 `dog exists = true`가 아니다.
Neural perception may be allowed. Neural interpretation does not automatically become truth.

## 12. Neural Perception 없이도 가능한 범위

Canny / edge detection, connected components, contours, Hough lines / circles, optical flow, color histograms, shape descriptors, feature matching, prototype matching, nearest neighbour, dynamic time warping, graph matching.

이를 이용하면 색, 모양, 위치, 이동, 가림, 반복 패턴, 간단한 identity tracking, 제한된 환경의 object concept 등을 학습 모델 없이 처리할 수 있다.
다만 복잡한 자연 영상에서 cat / dog / car / chair / person 같은 범용 object recognition을 규칙만으로 구현하는 것은 매우 어렵다. 따라서 V1에서는 범용 인식보다 좁고 검증 가능한 환경을 우선하는 것이 좋다.

## 13. SOMA V1의 좋은 첫 시나리오

범용 이미지 이해를 목표로 하지 않는다. 빨간 블록, 파란 블록, 테이블, 손 정도의 제한 환경.

```
red_object_1 exists; red_object_1 at position A
hand_1 approaches red_object_1
red_object_1 becomes occluded
red_object_1 reappears at position B
```

"빨간 물체 어디 갔어?" → 처음에는 왼쪽에 있었고, 가려진 뒤 오른쪽 위치에서 다시 관찰되었습니다.
"손이 옮긴 거야?" → 손이 물체에 가까워진 뒤 위치가 변한 것은 관찰했지만, 손이 직접 이동시켰다고 확정할 근거는 충분하지 않습니다.

이 시나리오는 caption model보다 MARCO의 철학을 훨씬 잘 보여준다.

## 14. Audio도 텍스트를 거치지 않을 수 있다

waveform → spectral / temporal features → acoustic pattern → meaning candidate.

```
AcousticConcept: OPEN_REQUEST_PATTERN
features: temporal trajectory, spectral pattern, pitch movement, duration
input acoustic pattern → prototype matching / DTW → OPEN_REQUEST_PATTERN = 0.84
```

자유로운 언어 전체에는 어려운 방식이지만, 특정 명령/상황/소리의 인식에는 유효하다.

## 15. ALMA의 감정도 같은 철학으로 본다

나쁜 방식: `emotion = angry`.
좋은 방식: events, goals, expectations, preferences, control, observations → appraisal state → emotion concept hypothesis.

## 16. ALMA 자신의 감정

ALMA는 자신의 내부 goal, expectation, preference를 알고 있기 때문에 외부 표정 인식보다 더 강한 근거를 사용할 수 있다.

```
Goal: solve_problem
Expectation: action_A → success
Actual: action_A → failure
Control: retry_available
History: same failure repeated 3 times
→ goal obstruction = high, expectation violation = high, control = medium, repetition = high
→ goal_blocked + negative_result + some_control → frustration-like state
```

사건 → 목표와의 관계 → 예상과 실제 → 통제 가능성 → 기억 / 선호 → 감정 상태 라는 원인 경로를 가진다.

## 17. Emotion State와 Emotion Word를 분리한다

MARCO에서 Meaning ≠ Language 인 것처럼 ALMA에서는 Emotion State ≠ Emotion Word 로 본다.
내부 상태 (goal blocked, expected loss high, control low, uncertainty high)가 먼저 존재하고, 한국어로는 불안하다 / 걱정된다 / 두렵다, 영어로는 anxious / worried / afraid 로 표현한다. 다국어 및 문화별 표현 차이에도 유리하다.

## 18. 타인의 감정 이해

`person_A is angry`로 바로 저장하면 안 된다.

```
Observed: voice intensity increased; interruptions increased; short negative utterances; preceding goal obstruction observed
Hypothesis: person_A may be frustrated
confidence: 0.68
```

상대가 "나 화난 거 아니야."라고 말한다면 이것 역시 새로운 evidence다 (reported_state: not_angry → previous_hypothesis weakened / revised). 향후 Theory of Mind와 자연스럽게 연결된다.

## 19. ALMA Emotion Architecture 제안

Layer 1 — Affect Primitives: goal_progress, goal_obstruction, reward, loss, threat, novelty, control, expectation_violation, social_relation, arousal, uncertainty.
Layer 2 — Appraisal State: goal is blocked, expected loss is high, control is low, uncertainty is high.
Layer 3 — Emotion Concept: fear-like, frustration-like, relief-like, joy-like.

Layer 1과 2가 실제 reasoning에 중요하다. Layer 3의 이름은 그 상태를 사람이 이해하기 쉽게 묶은 concept이다.

## 20. Vision / Audio / Emotion은 하나의 구조다

```
RAW / EVENT → OBSERVATION → RELATIONS → APPRAISAL / STRUCTURE → CONCEPT HYPOTHESIS → REASONING
```

핵심은: 이름 붙이기는 가능한 한 마지막에 한다.

## 21. Multi-query와 Autonomous Goal Generation은 구분한다

Multi-query: 사용자가 직접 여러 요구를 한 경우 ("TCP가 뭐고 UDP가 뭐야? 차이도 알려줘." → User Query 1, 2, 3). MARCO가 새로운 목표를 만든 것이 아니다. 언어 이해 단계에서 `query` 하나 대신 `queries[]` 형태를 고려할 수 있다.

Autonomous Subgoal Generation: "이 회사가 투자할 만한지 조사해줘."에 대해 MARCO가 revenue / debt / market research subgoal을 스스로 만드는 것은 완전히 다른 능력이다. 향후 planning / G7 계열 문제다. 내부적으로 `user_goals[]`와 `generated_subgoals[]`을 분리하는 것이 바람직하다.

## 22. Knowledge Gap과 장기 Research Loop

```
Original Goal → Reasoning → Missing fact detected → Knowledge Gap → Research Subgoal → Observation / external evidence → Knowledge Gap resolved → Original reasoning resumes
```

예: assess danger requires flash point, toxicity, current temperature; known: temperature; unknown: flash point, toxicity → research subgoals, then return. 현재 MARCO 1의 범위와는 별개이며 장기 planner 영역이다.

## 23. Thinking Budget과 연결

추론 시간을 늘린다는 것은 같은 연산을 반복하는 것이 아니다. 좋은 thinking budget: more candidates, more graph traversal, more evidence checking, more contradiction checks, more alternative hypotheses.

```
LOW:    Top-1 graph, short reasoning path
MEDIUM: Top-5 graphs, evidence reranking, several-hop inference
HIGH:   wider graph exploration, alternative hypotheses, counter-evidence, related graph expansion
```

compute ↑ → explored reasoning paths ↑ → potentially better answer 관계를 측정할 수 있다. 향후 MARCO의 deliberation 개념으로 발전할 수 있다.

## 24. MARCO의 철학 재정의

절대 지킬 원칙

1. 근거 없는 사실을 확정하지 않는다.
2. 관찰과 사실을 구분한다.
3. 추론과 감각 인식을 구분한다.
4. 결론은 근거 경로를 가진다.
5. unknown을 정상적인 결과로 인정한다.
6. 가정, 관찰, 추론, 검증된 사실의 상태를 구분한다.
7. 생성 모델이 reasoning 결과를 대신 결정하지 않는다.

선택 가능한 구현 (철학 자체가 아니라 implementation choice): character encoder, neural perception, OCR, speech recognizer, object detector, feature extractor, non-neural prototype matcher. 이들은 어디에 쓰이는지가 중요하다.

## 25. 한 문장으로 표현한 새로운 철학

MARCO does not need every observation to be provable. It requires every conclusion to be traceable to observations, assumptions, and rules.
MARCO proves conclusions, not sensors.
SOMA measures. MARCO reasons.
ALMA does not receive emotions as labels. It derives affect from experience, goals, expectations, and control.

## 26. 라이선스 방향에 대한 아이디어

Knowledge Graph: 형식과 개별 지식 그래프는 강하게 제한하지 않는다. Knowledge should be accessible to everyone.
MARCO Engine: 개인 사용, 연구, 수정, 재배포, 상업 이용 허용을 기본으로 하되, 사용자-facing 제품에서는 "Powered by MARCO — Created by DoTaeIn, Original project: https://github.com/DoTaeIn/Marco" 같은 attribution을 사용자에게 보이게 유지하는 방향을 고려한다. 완전한 white-label을 원하는 기업에는 별도 라이선스. 아이디어 단계이며 실제 라이선스 변경 시 별도 법률 검토가 필요하다.

## 27. 전체 구조

```
                           WORLD
                             │
          ┌──────────────────┼──────────────────┐
       CAMERA             MICROPHONE          SENSOR
          └──────────────┬───┴──────────────────┘
                         ▼
                       SOMA  (Perceptual Graph Compiler)
                         ▼
                  Observation Graph
           ┌─────────────┴─────────────┐
        MARCO                        ALMA
     reasoning core             personal cognition (goals / memory / appraisal / affect)
           └─────────────┬─────────────┘
                         ▼
                     Meaning
                         ▼
                 Language Realizer
                         ▼
                      OUTPUT
```

## 28. 핵심 요약

1. MARCO가 멀티모달이 되기 위해 모든 감각을 텍스트로 번역할 필요는 없다.
2. 이미지·음성·센서는 직접 Observation Graph로 변환할 수 있다.
3. 처음부터 사물의 이름을 맞히지 않는다. anonymous entity first.
4. Object identity보다 관계와 사건을 먼저 이해할 수 있다.
5. SOMA는 관찰하고 MARCO는 추론한다.
6. Perception 결과는 사실이 아니라 출처와 불확실성을 가진 관찰이다.
7. 감정도 직접 라벨링하지 않는다. 사건, 목표, 기대, 통제 가능성, 선호로부터 appraisal을 만들고 감정 개념을 추론한다.
8. 감정 상태와 감정 단어를 분리한다.
9. 완전한 sensor proof가 불가능하더라도 결론의 provenance는 유지할 수 있다.
10. MARCO의 핵심은 "신경망을 쓰지 않는 것"보다 관찰과 사실을 구분하고, 근거를 따라 추론하며, 모르면 모른다고 하는 것에 있다.

## 29. 임시 연구 문장

MARCO should not translate the world into language before thinking. It should translate the world into observations, then reason over them.
MARCO는 세상을 생각하기 전에 언어로 번역할 필요가 없다. 세상을 관찰 구조로 바꾸고, 그 구조 위에서 생각하면 된다.
