# ALMA 0.1 완료 기준 매핑

이 표는 `2026-09-20-addition-next-directions.md`의 11개 완료 기준을 구현 단위와 실행 검증에 연결한다. 표의
항목은 계획만으로 완료가 아니며, 각 행의 시나리오가 원시 결과와 함께 통과해야 한다.
next goal A–H의 세부 감사는 [2026-09-20-next-goal-evidence.md](2026-09-20-next-goal-evidence.md)를
함께 본다.

| Addition 기준 | 상태 | 담당 기능 | 검증 시나리오 |
| --- | --- | --- | --- |
| 1. Event / Experience Graph | 부분 | `ReasoningContext` 이벤트 ledger, revision·시간·role provenance | Quantity/Location/Social/Mental의 역할 3개 이상, 보완·정정·재시작 |
| 2. SYSTEM / COGNITION / LIFE 로그 | 검증됨(선택) | 영구 decision ledger, snapshot, milestone recorder | 과거 판단과 현재 재판단 분리, 최초 발생 검색, 중단 뒤 복구 |
| 3. 세 종류 기억 | 부분 | 단일 상태 저장의 episodic/semantic/procedural namespaces | 경험/일반 지식/절차의 독립 검색, 압축, 근거 정정 철회 |
| 4. Concept Formation | 검증됨(고정 분할) | `experience_concepts` 후보·검증·적용·반례 이력 | 서로 다른 3개 경험, 별도 검증, 새 사건 적용, conflict/rollback |
| 5. Structural Learning | 부분 | `rule_learning`, `semantic_feedback`, `self_authoring` 변경 ledger | 후보 node/edge/rule, 승인 A/B, benchmark 전후 및 rollback |
| 6. Chunking | 검증됨(선택) | proof shortcut 후보와 원 proof provenance | 의미 동일, 조건 변경/반례 비적용, traversal·시간 비교 |
| 7. ALMA 시작 조건 | 부분 | 공통 Event/Condition/Hypothesis 계약 | 실제/계획/가정/미해석·시간 정정·재시작을 네 영역에서 검증 |
| 8. 네 영역 transfer | 부분 | pack 선언 기반 Quantity/Location/Social/Mental | 직접 입력과 자연어 입력을 분리하고 최소 3개 영역의 변형/대조 |
| 9. 원인 기반 감정 | 검증됨(선택) | goal·관계·위협·통제 가능성의 원인 graph | 동일 사건의 다른 목표/관계, 원인 해소, 선택 차이와 설명 |
| 10. 경험 기반 취향 | 검증됨(고정 로컬 범위) | 경험→감정→기억→기대→preference 이력 | 초기값 없는 분화, utility 대조, 독립 event confidence·중복·상충·정정·복구 |
| 11. Capability adapter | 검증됨(선택) | 등록형 schema/permission adapter와 실행 이력 | read tool, 고정 실패, 교체, 승인·중복·중단 재개, 상태 보존 |

## Addition 기준별 실행 증거

아래는 위 표의 각 행을 실제 코드·회귀시험·원시 결과에 한 번씩 명시적으로
연결한 H8 보조 목록이다. `검증됨` 표기는 각 행에 적은 **고정된 범위**만 뜻한다.
따라서 `부분` 행은 구현 파일이나 보고서가 있어도 완료로 승격되지 않으며, 이 목록은
독립 변형·자연어 범위가 남은 경우를 숨기지 않는다.

| Addition 기준 | 구현 및 회귀시험 | 원시 결과와 판정 한계 |
| --- | --- | --- |
| 1. Event / Experience Graph | `reasoning_context.py`, `alma_runtime.py`; `tests/test_alma_runtime.py`의 시간 투영·Social 역할 정정·state identity·legacy event-kind migration 회귀 | `alma-regression-report.json`, `alma-integrated-report.json`. world/observation/private Mental의 공통 event envelope와 구 state의 kind 보완은 확인했지만, 네 영역 모든 과거 보완 조합은 아직 부분이다. |
| 2. SYSTEM / COGNITION / LIFE 로그 | `alma_runtime.py`; `tests/test_alma_runtime.py`의 decision/reconsider, milestone·restart 회귀 | `alma-unified-report.json`, `alma-integrated-report.json`. 기록·snapshot·최초 검색의 고정 시나리오는 통과했으며, 이 행의 표기는 그 범위에 한정한다. |
| 3. 세 종류 기억 | `alma_runtime.py`; `tests/test_alma_runtime.py`의 typed recall/철회·재활성화 및 `tests/test_alma_unified_reproduction.py` | `alma-integrated-report.json`, `alma-unified-report.json`. episodic/semantic/procedural 분리·새 프로세스 복원은 있으나 자유형 모든 질의와 수명 조합은 부분이다. |
| 4. Concept Formation | `experience_concepts.py`; `tests/test_experience_concepts.py`, `tests/test_alma_learning_lifecycle_reproduction.py` | `learning-lifecycle-after-fix.json`, `alma-cross-domain-transfer-report.json`. 구성 3·별도 검증 1·첫 적용과 최종 독립 평가 2건, OFF/반례/재시작을 고정 분할에서 검증했다. |
| 5. Structural Learning | `rule_learning.py`, `semantic_feedback.py`, `self_authoring.py`; `tests/test_alma_structural_transfer_reproduction.py` | `structural-transfer-report.json`, `alma-graph-asset-report.json`. graph asset의 승인·export·rollback은 검증됐지만, 일반적인 구조 변경 범위는 부분이다. |
| 6. Chunking | `proof_chunking.py`; `tests/test_proof_chunking.py`, `tests/test_alma_integrated_reproduction.py` | `alma-integrated-report.json`의 `shortcut_costs`. branch/version/counterexample과 준비·반복·원 경로 비용 분리는 고정 평가에서 통과했다. |
| 7. ALMA 시작 조건 | `reasoning_context.py`, `alma_runtime.py`; `tests/test_alma_runtime.py`, `tests/test_alma_integrated_reproduction.py`, `tests/test_event_provenance.py` | `alma-integrated-report.json`, `alma-regression-report.json`. 세 world 영역의 자연어 계획은 `planned`로, 정의 없는 행동은 `uninterpreted`로 재시작 뒤에도 구분한다. 시간·Mental·복원 회귀가 있으나 네 영역의 모든 실제/계획/가정/미해석 변형은 부분이다. |
| 8. 네 영역 transfer | pack 선언, `experience_concepts.py`, `alma_runtime.py`; `tests/test_alma_cross_domain_transfer_reproduction.py`, `tests/test_alma_integrated_reproduction.py`, `tests/test_event_review_regressions.py`, `tests/test_event_provenance.py`, `tests/test_action_runtime.py` | `alma-cross-domain-transfer-report.json`은 Quantity/Location/Social 직접 구조 전이, `alma-integrated-report.json`은 자연어 네 영역 Event/Condition 후보의 3/1/적용·재시작과 네 영역 planned/negative/false-condition event의 nonactual ledger를 보인다. 세 world 영역의 가정도 `hypothetical` 공통 envelope로 임시 투영돼 실제 질의·원장을 바꾸지 않고, pending 역할 보완은 같은 event ID로 실행·복원된다. 정의 없는 행동은 domain/effect를 꾸며내지 않는 `uninterpreted` 보류로 복원되고, 저장된 이력은 새 관찰 suffix만 다시 읽는다. 복원 뒤 Quantity 실제→부정 및 Location·Social 역할 정정도 같은 ID의 저장 program으로 교체한다. 미해석과 역할/시간 정정 전체 조합, 효과 전이는 아직 부분이다. |
| 9. 원인 기반 감정 | `alma_runtime.py`; `tests/test_alma_runtime.py`, `tests/test_alma_unified_reproduction.py` | `alma-unified-report.json`. event-linked goal/relation/control 원인과 원인 해소 후 선택 변화를 고정 로컬 범위에서 확인했다. |
| 10. 경험 기반 취향 | `alma_runtime.py`; `tests/test_alma_runtime.py`, `tests/test_alma_unified_reproduction.py` | `alma-unified-report.json`. 독립 event confidence, 중복 무증가, 상충/정정/재시작은 고정 로컬 범위에서 통과했다. |
| 11. Capability adapter | `alma_runtime.py`; `tests/test_alma_runtime.py`, `tests/test_alma_regression_reproduction.py`, `tests/test_alma_environment_reproduction.py` | `alma-regression-report.json`, `alma-environment-report.json`. schema/permission, approval/retry/unknown execution과 로컬 read 선택을 검증했으며, 외부 adapter의 exactly-once는 주장하지 않는다. |

G0 선행 게이트는 위 모든 행의 공통 기준이다. Quantity와 Location에서 proof와
전제 상태(긍정/명시 부정/미확인/상충)를 정확히 설명하고, 재현 평가의 모든 단계
오류를 결과 파일에 남겨 실패시키기 전에는 후속 완료를 주장하지 않는다.

## 2026-09-20 실행 증거와 현재 판정

아래 판정은 구현 존재나 검사 수를 완료 근거로 바꾸지 않는다. `검증됨`은 해당
시나리오 범위에서만, `부분`은 남은 필수 범위를 뜻한다.

| next goal | 현재 판정 | 코드·시험·원시 결과 |
| --- | --- | --- |
| A | 검증됨(선택 회귀) | `alma_runtime.py`, `tests/test_alma_runtime.py`, `tests/test_alma_integrated_reproduction.py`, 정상 `execution-2026-09-20/alma-integrated-report.json`, 후반 오류 `alma-integrated-late-error-report.json`, `bench/alma_regression_reproduction.py`와 `alma-regression-report.json` |
| B | 검증됨(선택 회귀) | `proof_chunking.py`, `tests/test_proof_chunking.py`, 통합 보고서의 `shortcut_costs`(준비 검증/반복/원 경로 scan과 source rule IDs) |
| C | 부분 | `project_state_at()`의 늦은 과거 수량·위치 사건과 재시작 회귀, typed memory, 실제 event 조건 proof를 쓰되 세계 assertion으로 승격하지 않는 Mental query는 검증됐다. 제한된 자연어 `holder의 기대 조건이 충족됐어?`는 명시적 condition event가 영속 ledger에 관찰됐는지를 별도 확인하며 세계 assertion으로 승격하지 않는다. 원 구성·검증 ID 복구 뒤 semantic 재검증과 새 프로세스 recall도 통합 보고에서 확인했다. 네 영역의 자연어 공통 판단·이유 설명과 모든 시간/조건 변형은 아직 별도 종료 검증이 필요하다. |
| D | 검증됨(고정 분할) | `bench/alma_learning_lifecycle_reproduction.py`, `tests/test_alma_learning_lifecycle_reproduction.py`, `execution-2026-09-20/learning-lifecycle-after-fix.json`. 별도 구조 입력의 `bench/alma_structural_transfer_reproduction.py`와 `execution-2026-09-20/alma-structural-transfer-report.json`은 서로 다른 동사 6개의 같은 역할·연산 구조를 구성 3/검증 1/독립 적용 2로 분리하고, 역할 값 변화는 전이하되 같은 동사의 효과량·조건 변화·계획 양태는 합치지 않는다. `alma-graph-asset-report.json`은 self-authoring graph asset의 node/edge 수·event lineage·승인·새 pack export·rollback을 같은 변경 ledger로 연결한다. |
| E | 검증됨(로컬 환경 범위) | `alma_environment.py`, `bench/alma_local_environment.json`, `tests/test_alma_environment*.py`, `execution-2026-09-20/alma-environment-report.json`. 정보 공백 단계는 initial observation의 episodic provenance를 실제 행동 근거로 재조회한다. |
| F | 검증됨(고정 로컬 범위) | 원인 event 연결, 목표 측정, 중복 preference 방지, 같은 사건의 relation/control별 행동 차이, 독립 event confidence·상충·밤/아침 맥락·개체별 선택과 재시작 뒤의 지속성을 `tests/test_alma_runtime.py`, `alma-unified-report.json`에서 검사한다. 주관적 경험은 주장하지 않는다. |
| G | 부분 | lifecycle bench의 동일 관찰 ON/OFF 및 활성 구조 OFF, 반례 철회는 검증됐다. 통합 보고서도 별도 계획-only 생애의 safe hold, Social post-activation application, 네 영역 post-activation recall을 분리해 2 solved/1 safe_hold/0 wrong으로 기록한다. 구조 전이의 역할 값/같은 동사 효과량/조건/계획 양태 대조도 통과했지만, 네 영역에 걸친 폭넓은 독립 변형 평가는 남아 있다. |
| H | 부분 | `bench/alma_unified_reproduction.py`는 자연어 경험→학습→기억/Mental→환경 중단·CLI subprocess의 새 프로세스 재개→교정 철회와 원 근거 복구 뒤 semantic 재검증→별도 개인 백업 파일의 새 프로세스 절차 기억 복원→원본 `.kg`가 없는 깨끗한 디렉터리에서 pack과 backup의 수량 판단 복원을 연결한다. `alma-integrated-report.json`은 실제 네 영역 계약의 semantic recall·재시작 recall을 포함한 기능 47 solved/0 wrong과 분리된 독립 2 solved/1 safe_hold/0 wrong을 남기며, 후반 오류 보고도 오류 전 기능 43 solved/0 wrong·같은 독립 행과 execution_error를 함께 보존한다. 전체 종료 게이트와 Addition 11개 전 범위의 독립 평가는 아직 완료되지 않았다. |

이번 실행에서 새로 생성한 원시 결과는 `docs/ko/execution-2026-09-20/`에만 둔다.

최신 자연어 통합 원시는 기능 검사 49 solved/0 wrong, 독립 3 solved/2 safe_hold/0 wrong을 구분한다. 네 영역 contract는 계획-only 생애에서 safe_hold, 실제 world 3개·natural Mental 검증/적용 뒤 solved, natural Mental 반례 뒤 safe_hold, 새 natural Mental 관찰 뒤 solved를 각각 독립 행으로 남긴다. 의도적 `episodic_save` 오류 보고서는 오류 전 기능 45 solved/0 wrong과 같은 독립 결과를 보존한 뒤 `execution_error: 1`로 끝난다. 표 안의 이전 통합 수치는 이 최신 raw JSON보다 우선하지 않는다.

최신 전체 회귀 원시는 766 passed/8 skipped, exit 0, pytest 1350.22초다. 표 안의 이전 전체 실행 시간보다 이 원시 JSON을 우선한다.

재시작 lineage 보강 뒤 최신 통합 raw는 기능 50 solved/0 wrong, 독립 3 solved/2 safe_hold/0 wrong이다. contract 재활성화 application lineage는 새 natural Mental event ID만 포함하며 재개 뒤에도 정확히 복원된다. late-error raw는 오류 전 기능 46 solved/0 wrong과 같은 독립 결과를 기록한다.

위 보강이 포함된 최신 전체 회귀 원시는 766 passed/8 skipped, exit 0, pytest 1365.56초다.

환경 원시는 같은 초기 관찰에서 성공 read의 goal achieved 1건과 응답하지 않은 관련 read의 `safe_hold` 1건을 분리하며, 실패 read는 capability journal의 `failed` 상태와 환경 보류 이유로 남는다.
실패 read 반례와 직접 구조의 두 독립 held-out 적용 보강까지 포함한 최신 전체 회귀는 766 passed/8 skipped, exit 0이다. `alma-full-pytest-report.json`은 전용 runner가 직접 생성한 총 1326.634초(그 안의 pytest 1325.66초) 결과이며, 위의 모든 과거 전체 회귀 시간보다 우선한다.

기존 `review-2026-09-20/`와 `audit-2026-09-20/` 원시 결과는 발견 당시의 실패
증거로 보존한다. 변경 범위 회귀는 59 passed, 시간 투영/CLI를 포함한 직접 범위
회귀는 29 passed였다. 최신 별도 runner의 `alma-full-pytest-report.json`은 새 조건
질문, private Mental event ledger, 통합 계약과 legacy event-kind migration까지 포함해
766 passed/8 skipped, exit 0 (pytest 1341.44초)다. 새 변경의 직접 범위는
`test_alma_runtime.py`, `test_event_provenance.py`, `test_action_runtime.py`, `test_event_review_regressions.py`와 정상/후반 오류 통합 재현으로도 검증됐다.
