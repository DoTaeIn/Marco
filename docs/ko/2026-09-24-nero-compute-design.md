> Owner's design note, recorded verbatim by the plan manager on 2026-09-24 and moved out of the repository root. Scheduled in [2026-09-24-roadmap-after-marco1.md](2026-09-24-roadmap-after-marco1.md) (rows N1 to N5). NERO V1 starts with the engine splits after the gate; nothing before.

# NERO — MARCO Compute & Acceleration Layer

> **Status:** Naming and architecture draft  
> **Date:** 2026-09-24  
> **Name:** NERO  
> **Role:** Computation / acceleration / execution scheduling  
>
> NERO는 MARCO의 추론 의미를 바꾸지 않고,
> MARCO가 정의한 계산을 CPU, GPU, 멀티 GPU, 원격 노드 등에서
> 가장 적절한 방식으로 실행하는 연산 계층이다.

---

# 1. MARCO Family

```text
MARCO  = Knowledge / Reasoning
ALMA   = Self / Cognition / Memory / Affect
SOMA   = Perception
POLO   = Action / External Execution
NERO   = Computation / Acceleration
```

핵심 구분:

```text
MARCO decides what reasoning means.
NERO decides how that reasoning is computed.
```

한국어:

> **MARCO가 무엇을 계산해야 하는지를 정의하고,
> NERO가 그것을 어떻게 가장 효율적으로 계산할지를 담당한다.**

---

# 2. NERO는 별도의 AI가 아니다

NERO는 MARCO와 따로 지능적으로 진화하는 별도 reasoner가 아니다.

잘못된 구조:

```text
MARCO CPU
MARCO GPU
```

각각 독자적인 reasoning logic을 가지는 구조.

이 경우 시간이 지나면:

```text
CPU version has rule A
GPU version has rule B
```

처럼 서로 다른 시스템이 될 위험이 있다.

권장 구조:

```text
                MARCO
        semantic/reasoning contract
                  │
                  ▼
                 NERO
                  │
        ┌─────────┼─────────┐
        ▼         ▼         ▼
       CPU       GPU     Multi-GPU
```

즉:

> **코드는 분리하되 지능은 분리하지 않는다.**

---

# 3. NERO의 책임

NERO가 담당한다.

```text
graph memory layout
CPU / GPU backend selection
parallel graph traversal
batch rule matching
candidate scoring
frontier expansion
vector scoring
multi-device scheduling
memory transfer
device cache
compute budget allocation
throughput optimization
latency optimization
```

---

# 4. NERO가 담당하지 않는 것

NERO는 다음을 소유하지 않는다.

```text
truth
knowledge admission
reasoning semantics
logical rules
persona
goals
emotion
language meaning
final epistemic judgment
```

즉 NERO가:

> "이 답이 맞다."

라고 판단하면 안 된다.

NERO는:

> "MARCO가 요청한 연산의 결과가 이것이다."

까지만 반환한다.

---

# 5. 기본 구조

```text
Question
   ↓
MARCO
   ↓
Reasoning Operation
   ↓
NERO
   │
   ├─ CPU
   ├─ GPU
   ├─ Multi-GPU
   └─ Remote Compute
   ↓
Computation Result
   ↓
MARCO
   ↓
Proof / Conclusion
```

---

# 6. CPU와 GPU의 역할

## CPU가 잘하는 것

```text
parser control flow
goal management
small symbolic reasoning
branch-heavy logic
trace generation
state-machine control
irregular decision flow
```

## GPU가 잘하는 것

```text
large candidate scoring
vector comparison
mass graph filtering
wide frontier expansion
batch rule matching
parallel hypothesis evaluation
counterexample scanning
large-scale retrieval
```

---

# 7. Hybrid Execution

NERO의 핵심은 "GPU only"가 아니다.

실제로는 하이브리드가 기본이 된다.

```text
              NERO Controller
          ┌────────┼────────┐
          ▼        ▼        ▼
        CPU       GPU     GPU #2
          │        │        │
          └────────┼────────┘
                   ▼
                Results
                   │
                   ▼
                 MARCO
```

예:

```text
CPU:
control / branch decision

GPU:
candidate expansion

CPU:
proof validation

GPU:
counterexample scan
```

---

# 8. Backend Abstraction

MARCO 내부에 backend-specific code가 퍼지면 안 된다.

추천 인터페이스:

```python
class ReasoningBackend:
    def route(...):
        ...

    def score(...):
        ...

    def expand(...):
        ...

    def match_rules(...):
        ...

    def reduce(...):
        ...
```

NERO는 이 contract를 구현한다.

예:

```text
CPUBackend
CUDABackend
MultiGPUBackend
RemoteBackend
```

---

# 9. Same Semantics Contract

동일한:

```text
question
knowledge revision
reasoning budget
rules
```

에 대해서는 가능한 한:

```text
CPU proof
=
GPU proof
```

가 되어야 한다.

속도와 scheduling은 달라도
reasoning semantics는 같아야 한다.

---

# 10. GPU용 Graph Representation

CPU 자료구조를 그대로 GPU로 복사하는 것은 비효율적일 수 있다.

CPU:

```text
dict
list
objects
strings
```

GPU:

```text
node_ids
edge_src
edge_dst
edge_type
edge_weight
```

또는:

```text
CSR
CSC
```

같은 compact graph representation을 사용한다.

예:

```text
row_ptr
col_idx
edge_type
metadata_index
```

---

# 11. MCO와 연결

장기적으로 MCO compile 단계에서 실행 backend용 표현을 함께 만들 수 있다.

```text
Knowledge Graph
      ↓
    MCO
      ↓
 ┌────┴────┐
 ▼         ▼
CPU IR    GPU IR
```

즉 같은 knowledge asset을
여러 execution representation으로 compile한다.

---

# 12. Automatic Backend Selection

NERO는 문제 크기와 하드웨어 상태를 보고 backend를 선택할 수 있다.

예:

```text
small graph
small frontier
branch-heavy
→ CPU
```

```text
large candidate set
wide search
batch scoring
→ GPU
```

```text
very large frontier
many independent hypotheses
→ Multi-GPU
```

---

# 13. Cost Model

NERO는 최소한 다음을 볼 수 있다.

```text
graph_size
frontier_size
candidate_count
rule_count
estimated_branching
memory_transfer_cost
CPU load
GPU load
available VRAM
current latency target
reasoning budget
```

예:

```text
estimated_cpu_cost = 18 ms
estimated_gpu_cost = 5 ms
```

이면 GPU 선택.

반대로:

```text
estimated_cpu_cost = 3 ms
estimated_gpu_cost = 9 ms
```

이면 CPU 선택.

---

# 14. 작은 문제는 GPU가 느릴 수 있다

GPU에는:

```text
CPU → GPU transfer
kernel launch
synchronization
GPU → CPU transfer
```

오버헤드가 있다.

따라서:

```text
small problem
CPU = faster
```

일 수 있다.

NERO의 목적은:

> **GPU를 무조건 쓰는 것**

이 아니라:

> **가장 적절한 compute path를 선택하는 것**

이다.

---

# 15. Thinking Budget과 NERO

NERO는 MARCO의 reasoning budget과 직접 연결될 수 있다.

예:

```text
FAST
→ CPU
→ shallow search
```

```text
DEEP
→ CPU + GPU
→ wider frontier
```

```text
VERY_DEEP
→ GPU / Multi-GPU
→ broad hypothesis expansion
→ counterexample search
```

---

# 16. GPU의 진짜 가치

GPU의 목적을 단순히:

```text
같은 답을 더 빨리
```

로만 보면 제한적이다.

더 중요한 목표:

```text
같은 시간 안에
더 많은 reasoning states를 탐색
```

이다.

예:

```text
CPU:
1 second → 1,000 states

GPU:
1 second → 100,000 states
```

가능하다면:

```text
same response latency
+
larger reasoning search
=
potentially higher accuracy
```

가 된다.

즉 NERO는:

> **latency accelerator**

뿐 아니라

> **reasoning-space accelerator**

가 될 수 있다.

---

# 17. Foreground Self-Repair Loop와 연결

MARCO의 self-repair loop:

```text
SOLVE
→ DIAGNOSE
→ REPAIR
→ RETRY
→ ACQUIRE
→ RETRY
```

가 깊어지면 여러 candidate를 평가해야 한다.

```text
Repair A
Repair B
Repair C
Hypothesis D
Hypothesis E
```

NERO는 이를 batch로 병렬 실행할 수 있다.

```text
              Question
                 │
         ┌───────┼───────┐
         ▼       ▼       ▼
      Repair A Repair B Repair C
         │       │       │
         └───────┼───────┘
                 ▼
          compare outcomes
```

---

# 18. Parallel Hypothesis Search

NERO가 특히 잘할 수 있는 영역:

```text
multiple graph candidates
multiple rule candidates
multiple repairs
multiple explanations
multiple counterexamples
```

이를 동시에 계산한다.

이는 MARCO의 reasoning depth를 단순 serial depth가 아니라:

```text
depth × breadth
```

로 확장할 수 있게 한다.

---

# 19. NERO와 Capability Graph는 다르다

혼동 금지.

```text
Capability Graph
= MARCO가 외부에서 무엇을 할 수 있는가

NERO
= MARCO 내부 계산을 어디서 어떻게 실행하는가
```

예:

```text
GitHub MCP
→ Capability

CUDA GPU
→ NERO resource
```

---

# 20. NERO와 POLO도 다르다

POLO:

```text
외부 세계에 행동한다.
```

예:

```text
파일 수정
API 호출
로봇 제어
메시지 전송
```

NERO:

```text
내부 계산을 수행한다.
```

예:

```text
graph expansion
rule matching
candidate scoring
```

즉:

```text
NERO = compute
POLO = act
```

---

# 21. NERO와 SOMA

SOMA가 대규모 perceptual graph를 만들 경우
NERO가 그 계산 일부를 가속할 수 있다.

```text
SOMA
↓
visual / audio processing request
↓
NERO
↓
CPU / GPU scheduling
```

하지만:

```text
SOMA owns perception semantics
NERO owns compute execution
```

이다.

---

# 22. NERO와 ALMA

ALMA의:

```text
memory search
multiple appraisal candidates
goal evaluation
open-problem search
```

중 대량 병렬 계산이 필요한 부분은
NERO를 사용할 수 있다.

그러나:

```text
ALMA owns self/cognition
NERO owns computation
```

이다.

---

# 23. NERO Trace

NERO의 실행도 Hypomnema/Trace에 남길 수 있다.

예:

```text
compute_request
backend_selected
cpu_execution
gpu_execution
batch_started
batch_finished
device_fallback
out_of_memory
compute_budget_exhausted
```

예시:

```json
{
  "kind": "backend_selected",
  "operation": "frontier_expand",
  "backend": "cuda",
  "reason": "candidate_count_above_threshold",
  "estimated_cpu_ms": 21.4,
  "estimated_gpu_ms": 4.8
}
```

---

# 24. Failure / Fallback

GPU 실행 실패 시 reasoning 자체가 실패해서는 안 된다.

예:

```text
CUDA OOM
↓
reduce batch size
↓
retry
```

또는:

```text
GPU unavailable
↓
CPU fallback
```

NERO failure는:

```text
compute failure
```

이지:

```text
reasoning contradiction
```

이 아니다.

---

# 25. NERO V1

처음에는 거창하게 만들 필요 없다.

V1:

```text
NERO interface
CPUBackend
backend selection contract
benchmark hooks
```

실제 GPU는 없어도 된다.

목표:

> **MARCO reasoning code와 execution backend를 분리한다.**

---

# 26. NERO V2

```text
GPU routing/scoring
```

부터 시작.

이유:

```text
dense/batched comparison
parallel scoring
```

이라 GPU 친화적이기 때문이다.

---

# 27. NERO V3

```text
graph frontier expansion
batch rule matching
```

추가.

---

# 28. NERO V4

```text
parallel hypotheses
parallel repair evaluation
counterexample scanning
```

추가.

---

# 29. NERO V5

```text
multi-GPU
remote compute
distributed graph partitioning
dynamic scheduler
```

확장.

---

# 30. Benchmark

반드시 측정:

```text
single-query latency
batch throughput
routing latency
frontier expansion latency
rule matching latency
CPU ↔ GPU transfer cost
VRAM usage
RAM usage
energy usage
proof consistency
```

특히:

```text
CPU vs GPU crossover point
```

를 찾아야 한다.

---

# 31. 성공 기준

NERO 초기 성공 조건:

```text
1. CPU backend와 reasoning semantics가 분리되어 있다.
2. backend 변경이 proof meaning을 바꾸지 않는다.
3. 작은 문제는 CPU로 남길 수 있다.
4. 큰 문제는 GPU 가속 경로를 사용할 수 있다.
5. GPU failure 시 CPU fallback이 가능하다.
6. 같은 input/revision/budget에 proof consistency를 확인할 수 있다.
7. NERO execution이 trace에 남는다.
```

---

# 32. 이름의 의미

NERO는 의도적으로:

```text
MARCO
ALMA
SOMA
POLO
NERO
```

와 같은 간단한 사람 이름 계열의 리듬을 유지한다.

이름 자체가 특정 구현 기술에 묶이지 않는다.

따라서 NERO는 장기적으로:

```text
CPU
GPU
NPU
FPGA
Multi-GPU
Cluster
Remote Compute
```

등으로 확장되어도 이름을 바꿀 필요가 없다.

---

# 33. 최종 정의

> **NERO is the compute and acceleration layer of the MARCO family.**

한국어:

> **NERO는 MARCO 계열의 연산·가속 계층이다.**

더 정확히:

> **NERO는 MARCO의 reasoning semantics를 소유하지 않는다.
> MARCO가 정의한 연산을 현재 하드웨어와 reasoning budget에 맞게
> 가장 효율적인 실행 경로로 배치하고 수행한다.**

---

# 34. MARCO Family 최종 구도

```text
             ┌──────────────┐
             │    SOMA      │
             │  Perception  │
             └──────┬───────┘
                    │
                    ▼
             ┌──────────────┐
             │    MARCO     │
             │  Reasoning   │
             └──────┬───────┘
                    │
          ┌─────────┼─────────┐
          ▼         ▼         ▼
       ALMA       NERO      POLO
       Self      Compute    Action
```

개념적으로:

```text
SOMA  sees.
MARCO reasons.
ALMA  becomes.
NERO  computes.
POLO  acts.
```

한국어:

```text
SOMA는 본다.
MARCO는 추론한다.
ALMA는 자신을 형성한다.
NERO는 계산한다.
POLO는 행동한다.
```
