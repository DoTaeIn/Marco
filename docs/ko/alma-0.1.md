# ALMA 0.1 연구 루프

`alma_runtime.AlmaRuntime`은 MARCO의 `ReasoningContext`를 감싸는 작은 로컬
연구 환경이다. 사건을 다시 해석하거나 별도 추론기를 만들지 않는다. 자연어
`turn()`의 결과로 나온 event ledger, revision, proof와 action program을 개인
상태 파일에 추가 기록한다.

```powershell
python -m alma.cli --state .nai/alma-state.json --identity demo --turn "민수 구슬은 8개 있다."
python -m alma.cli --state .nai/alma-state.json --identity demo --memory episodic
python -m alma.cli --state .nai/alma-state.json --identity demo --recall procedural --recall-key 베풀
python -m alma.cli --state .nai/alma-state.json --identity demo --turn "과거 경험: event:demo:..."
python -m alma.cli --state .nai/alma-state.json --identity demo --turn "일반적으로 아는 것: 베풀"
python -m alma.cli --state .nai/alma-state.json --identity demo --turn "하는 방법: 베풀"
python -m alma.cli --state .nai/alma-state.json --identity demo --mental-holder 지연 --mental-kind belief
python -m alma.cli --state .nai/alma-state.json --identity demo --turn "지연의 믿음은 뭐야?"
python -m alma.cli --state .nai/alma-state.json --identity demo --search "민수" --search-kinds event,log
python -m alma.cli --state .nai/alma-state.json --identity demo --backup-state .nai/alma-backup.json
python kgpack.py --pack .nai/knowledge.kgpack --root .
python -m alma.cli --pack .nai/knowledge.kgpack --state .nai/packed-state.json --identity packed-demo --turn "민수 구슬은 8개 있다."
python -m alma.cli --pack .nai/knowledge.kgpack --state .nai/packed-state.json --identity packed-demo --backup-state .nai/packed-backup.json
python -m alma.cli --pack .nai/knowledge.kgpack --state .nai/packed-backup.json --identity packed-demo --turn "지금 민수 구슬은 몇 개야?"
python -m alma.cli --state .nai/alma-state.json --identity demo --cycle-steps cycle.json --step-budget 4
python -m alma.cli --state .nai/alma-environment.json --identity demo --environment bench/alma_local_environment.json --step-budget 1
# 앞 명령의 environment ID를 넣어 새 프로세스에서 같은 설정으로 재개한다.
python -m alma.cli --state .nai/alma-environment.json --identity demo --environment bench/alma_local_environment.json --resume-environment environment:ID --step-budget 4
python -m pytest -q tests/test_alma_runtime.py
```

## 보존 경계

- **공유 팩**: KG, 언어팩, 공리, 승인된 웹 학습만 `kgpack`으로 이동한다.
- **개인 상태**: agent identity, 대화 사건, 목표, 감정 원인, 선호, decision/log
  history는 `--state` JSON에만 저장한다. 팩 export에 자동 포함하지 않는다.
- **선택된 실행 자산**: `AlmaRuntime(..., model=PackModel)`은 model fingerprint와
  각 `turn()`의 graph 바이트 SHA-256을 상태/log에 함께 남긴다. 같은 identity/state를
  다른 model fingerprint로 다시 열면 `model_fingerprint_mismatch`로 중단한다.
- **팩 기반 재개**: CLI `--pack`은 검증한 pack의 graph·언어·공리만 사용한다.
  실행 중 graph 바이트는 임시 파일로만 물질화하며, 개인 state/backup은 pack 밖에
  남는다. `--pack-graph`으로 pack 안의 다른 graph 경로를 명시할 수 있다.
- **세 기억**: episodic은 실제 event/revision과 당시 결과, semantic은 검증되어
  활성인 경험 개념, procedural은 action program/version/precondition/effect다.
  한 JSON 파일에 원자적으로 저장하지만 검색과 수명은 분리한다. 저장 도중 프로세스가
  멈추면 다음 시작에서 본 파일과 임시 checkpoint 중 revision이 더 높은 유효 JSON을
  선택해 복구한다. 손상되거나 부분적으로 기록된 JSON은 사실로 읽지 않는다.
  `backup_state()`/CLI `--backup-state`는 기존 state를 덮어쓰지 않는 개인 삶의 사본을
  만들며, 공유 KG pack에는 개인 경험·목표·선호를 넣지 않는다.

통합 재현기의 연속성 실험은 재시작 전후의 identity, 미래 목표, 관계 holder와
episodic 기억을 관찰할 뿐이다. 이 기록은 의식이나 주관적 경험의 증명이 아니다.

통합 원시 보고서의 `costs`는 `time.perf_counter` 초 단위로 초기 준비, 후보
학습/검증/적용, 반복 질문, 당시 decision 설명 조회, 기억 read/write, recovery와
전체 시나리오를 나눈다. 최대 메모리는 추정 RSS가 아니라
`tracemalloc_peak_bytes`의 bytes 단위다.

event ledger는 실제/effective 시각(`effective_at`), 관찰 시각(`observed_at`),
처리 시각과 순서(`processed_at`, `processed_sequence`)를 분리한다. 과거 사건을
나중에 annotate해도 당시 처리 순서나 원 decision은 덮어쓰지 않는다.

세 기억은 canonical Korean 질문 라벨도 지원한다. `과거 경험: event-id`와
`event-id의 과거 경험은 뭐야?`, `일반적으로 아는 것: action-or-concept`와
`action에 대한 일반 지식은 뭐야?`, `하는 방법: action`과 `action의 절차는 뭐야?`는
각각 episodic event identity, 검증된 semantic 구조, procedural action program만
조회한다. 답에는 memory row와 source event provenance가 남는다. 이는 자유형 한국어
전체를 해석한다고 주장하는 기능은 아니다.

Mental도 `holder의 믿음/기대/목표는 뭐야?`, `holder은/는 무엇을 믿어?`,
`holder은/는 무엇을 기대해?`, `holder의 목표는 무엇이야?`의 holder-scoped 질문을
지원한다. 이 경로는 mental record의 modality, conditions, source event와 condition
proof를 반환하지만 `world_asserted: false`를 유지한다. 자유형 Mental 대화 전체를
지원한다고 주장하지 않는다.

`propose_graph_asset_file_change()`는 `self_authoring`이 만든 graph 후보를 source
파일로 받아 construction/validation event ID, lint, node/edge 수, base pack SHA-256과
함께 개인 상태에 기록한다. `approve_graph_asset_change()` 또는 고정 `local_auto`
정책으로 활성화한 후보는 `export_active_graph_assets(base, output)`을 **명시적으로**
호출했을 때만 새 output pack에 들어간다. 원 pack·원 `.kg`·개인 경험은 변경하지
않으며 `rollback_graph_asset_change()` 뒤 다음 export에서는 제외된다.

교정으로 concept의 지지/검증 사건이 바뀌면 semantic record는 삭제하지 않고
`withdrawn` 상태와 이유를 남긴다. 정확히 같은 원 구성·검증 event ID가 다시
eligible experience가 되면 그 원 lineage만 재검증해 semantic을 `active`로 되돌리고
재활성화 기록을 남긴다. 이후에 생긴 적용 사건을 구성/검증으로 승격하지는 않는다.
episodic 압축은 해시·효과·정의 버전 요약을 남기며 semantic/procedural을 건드리지 않는다.
같은 action에 서로 다른 구조가 각각 세 독립 경험으로 지지되면 어느 candidate도
자동 활성화하지 않고 `conflict`와 경쟁 구조의 support 수를 남긴다. 한 번뿐인
구조 반례는 기존처럼 `inactive`로 철회한다.

경험 개념의 lineage는 구성 3건, 별도 검증 1건, 그 뒤의 적용 사건을 서로 다른
event ID로 보관한다. 검증 사건은 활성화 뒤에 회고적으로 질의할 수 있지만
`application_event_ids`에는 넣지 않는다. 따라서 같은 네 번째 사건이 검증과
post-activation 적용 증거를 동시에 늘리지 않는다. 후보가 이미 만들어진 뒤에는
나중 사건을 빠진 구성/검증 slot으로 승격하지 않는다. 단, 대화 창이 오래된 원시
관찰을 보이지 않게 된 경우에도 살아 있는 candidate/application lineage는 개인
state에 유지한다. 같은 ID의 사건이 실제로 교정되어 eligible experience가 아니게
되면 후보와 그 적용은 철회된다.

`propose_rule_change(corrections, validation)`은 기존 `rule_learning.propose`의
훈련/분리된 positive·negative validation을 그대로 사용해 개인 상태에
`pending_approval` 후보와 A/B 결과를 남긴다. `approve_rule_change` 뒤에만 현재
parser의 rule overlay에 설치되며, 재시작 때 같은 승인 ledger에서 다시 설치된다.
`rollback_rule_change`는 원 pack을 고치지 않고 overlay만 철회한다.
`benchmark_rule_change(change_id, facts, target)`은 candidate를 설치하지 않은
baseline closure와 candidate를 더한 simulated closure를 같은 facts로 비교해 target의
전후 결과와 rule scan/join 계측을 변경 ledger에 남긴다.

## Proof shortcut

`proof_chunking.py`는 반복된 **정확한 단항 Horn rule chain**만 shortcut 후보로
합성한다. 원 rule ID·version·body·head를 함께 저장하므로 규칙/조건이 바뀌면
사용하지 않고 원 경로로 돌아간다. 이는 query cache가 아니라 실제 closure의 rule
scan/join 계측을 비교하는 경로다. 중간 proof는 유지되어 설명과 반례 철회에 쓴다.
ALMA의 `propose_proof_shortcut`은 같은 path의 독립 관찰을 두 번 받아야 활성화하고,
`run_proof_shortcut`은 원 closure와 shortcut closure의 실제 rule scan/join 계측을
COGNITION ledger에 남긴다. `invalidate_proof_shortcut`은 원 source chain을 지우지
않고 active flag만 철회한다.

## 로그와 지속성

`SYSTEM`은 capability 등록/호출, `COGNITION`은 입력·해석·proof/검증·선택,
`LIFE`는 사건·목표·감정 원인·선호를 기록한다. `FIRST_NEW_CONCEPT`과
`FIRST_UNPROMPTED_GOAL`은 실제 candidate/goal record가 생긴 경우에만 한 번
snapshot과 함께 기록된다. 문구만으로 milestone을 만들지 않는다.
각 milestone rule은 상태 JSON에 `required` evidence field로 선언된다.
`record_milestone_observation()`은 그 필드가 빠졌거나 self-reference의 identity가
다르면 기록하지 않으며, 같은 이름은 한 번만 snapshot으로 남긴다.
Snapshot에는 milestone 이름뿐 아니라 검증된 evidence도 함께 들어가므로, 나중에
현재 state를 재계산하지 않아도 생성 원인을 검토할 수 있다.

`search(query, kinds=...)`는 event/memory/mental/affect/log/milestone의 영속
ledger를 시간 순으로 돌려준다. 이는 새 사실을 유도하지 않으므로, 과거의 원본과
압축된 기억을 혼동하지 않은 채 최초 관찰을 찾는 용도다.

`recall(kind, key)`/CLI `--recall`은 목록이나 문자열 검색이 아니라, episodic의
event ID, semantic의 learned action/concept ID, procedural의 action을 각각 정확히
찾아 현재 질의에 쓴다. 응답은 선택된 memory row와 source event provenance를
돌려주고 COGNITION `memory_recalled` 기록을 남긴다. 찾지 못한 기억은 추측하지
않고 `safe_hold`로 남는다.

`annotate_event(event_id, effective_at=..., place=..., cause_event_id=..., roles=...,
conditions=...)`는
관찰 시각과 뒤늦게 확인한 유효 시각/장소/원인을 event metadata revision으로
추가하고, 이미 있는 역할을 보존한 채 뒤늦게 확인한 역할·조건을 같은 사건 ID에
보완한다. 이 호출은 세계 fact나 action 효과를 변경하지 않으며, 원천 사건의
observed time과 metadata 변경 시각을 모두 남긴다.
`project_state_at(effective_at)`는 실행된 수량 변화의 최초 관찰 baseline과 검증된
delta를 실제 사건 시각 순으로 재생한다. 따라서 늦게 수집한 과거 사건도 과거/현재
상태 투영에 반영하며, 시각이 빠진 변화나 비교할 수 없는 시각은 추측하지 않고
`safe_hold`로 남긴다. CLI에서는 `--project-state-at 2` 또는
`--project-state-at '"yesterday"'`로 같은 질의를 실행한다.
수량 delta뿐 아니라 선언된 단일값 상태 변화(예: location)의 before/after도 같은
시간 축에서 투영하며, 이 개인 투영은 현재 세계 KG replay를 되돌리거나 바꾸지 않는다.

감정 원인이 활성화된 동안 `choose()`는 preference와 goal relation뿐 아니라 option의
선언된 `supports_controls`와 원인 record의 control을 대조한다. 따라서 같은 관찰이라도
통제 가능성이 다르면 그 control에 맞는 보호 행동을 고르며, 선택 로그에 `control_fit`을
남긴다.

로컬 환경의 `seek_information` 단계는 초기 관찰의 episodic memory를 `recall()`해
source provenance를 확인한 뒤 그 사건을 정보 공백 행동의 근거로 사용한다. 기억이
없으면 임의의 행동을 만들지 않고 `safe_hold`로 끝낸다.

검토에서 발견된 저장/실행 반례의 수정 후 기대값은
`python bench/alma_regression_reproduction.py --output alma-regression-report.json`으로
별도 재현한다. 이 보고서는 identity·손상 JSON 보존, 승인 후 한 번 실행, 효과 뒤
checkpoint 중단의 `unknown_execution` 보류, 무근거 preference 거부를 검사한다.
통합 평가기의 후반 오류 보존은
`python bench/alma_integrated_late_error_reproduction.py --output alma-integrated-late-error-report.json`으로
별도 실행한다. 이 명령은 의도적으로 종료 코드 1을 반환하며, 앞선 functional check와
비용·`failed_stage`가 원시 JSON에 남아야 정상이다.

통합 원시 보고의 `shortcut_costs`는 첫 context 검증의 전체 scan,
검증 뒤 동일 입력의 반복 scan, 원 경로 scan 및 source rule ID를 분리한다. 첫 값이
반복 가속의 비용으로 해석되면 안 된다.
계획·조건·가정 event는 event index와 episodic 기록에 양태를 유지한 채 남지만,
asserted positive event가 아닌 한 action effect나 현재 세계 상태로 승격되지 않는다.
행동 사건을 만들지 않는 `observed` 입력도 `observation`으로 원문과 관찰 시각을
남긴다. 이 record는 역할·효과·실행 상태를 추정하지 않으며, 나중에 보완하거나
재검토할 수 있다.
`decision(id)`는 그 당시 input/answer/proof/state 전후를 돌려주며,
`reconsider(id, graph_path)`는 현재 state를 복제한 context에서만 같은 input을 다시
해석한다. 따라서 과거 판단의 근거는 보존하고도, 재검토가 실제 action을 한 번 더
실행하거나 개인 상태를 바꾸지 않는다.
CLI의 `--search`, `--decision`, `--reconsider`도 같은 durable ledger와 isolated review
경로를 제공한다.

`update_mental()`의 belief/expectation/goal은 세계 KG에 넣지 않는다. 각 row는
`modality`로 `belief`(현재 믿음), `planned`(계획), `conditional`(조건부),
`hypothetical`(가정)을 명시하고, 필요하면 `conditions`와 `effective_at`도 함께
기록한다. 이 양태는 추론 결과나 실제 세계 상태로 승격되지 않는다.
조건을 `{"event_id": ...}`로 구조화하면 `query_mental(...,
observed_event_ids=[...])`와 CLI `--mental-condition-event`가 실제 관찰 event를
대조한 `condition_proof`를 돌려준다. 충족된 경우에도 `world_asserted: false`를
명시해 Mental 판단을 세계 assertion으로 바꾸지 않는다.

경험 개념 후보는 실행 사건의 동사 문자열이 아니라 역할 연결·고정 값·조건·실행
효과로 만든 구조를 기준으로 묶는다. 같은 구조를 가진 여러 동사는 하나의
`scope.actions` 후보가 될 수 있으나, 다른 구조·정의 버전은 support를 섞지 않고
반례/충돌로 남긴다. 직접 구조 입력 검사는 자연어 대화 검증과 분리해 기록한다.
`revise_mental()`은 과거 mental row를 `withdrawn`으로 남기고 새 active row를
`supersedes`로 연결한다. 따라서 믿음 갱신은 재시작 뒤에도 보이되, 타인의 잘못된
믿음이 실제 세계 사실이나 과거 기록을 덮어쓰지 않는다.
`query_mental(holder, kind)`/CLI `--mental-holder`·`--mental-kind`은 holder와 kind가
정확히 하나인 active mental record만 원천 event·양태·시각·조건과 함께 답한다.
conditional/hypothetical은 `conditional` 결과로 남으며, 이 질의 때문에 세계 KG의
사실이나 action 효과로 투영되지 않는다.

`set_goal` → `assess_goal`은 목표/관계/통제/예상 손실에서 threat 또는 resolved
상태를 만든다. 이는 채팅 감정 말투와 분리된 원인 graph다. 선호는 사전값 없이
경험의 resolved/threat 신호와 맥락으로 생기며 utility와 별도로 선택에 반영된다.
같은 item·맥락의 활성 preference는 서로 다른 source event ID 수를 공통 `confidence`와
`support_event_ids`로 기록한다. 같은 event 재전송은 새 근거가 아니며, `choose()`의
선택 근거에도 이 confidence를 함께 남긴다.
`explain_affect()`는 현재 상태를 만든 goal·관계·통제·손실·원천 event record를
되돌려 준다. `revise_preference()`는 잘못 해석된 경험의 preference를 삭제하지
않고 withdrawn 기록과 superseding 경험으로 바꾸며, 이후 선택은 활성 근거만 쓴다.

`start_cycle(graph_path, steps, step_budget=...)`와 `resume_cycle(...)`는 이들을
하나의 data-defined loop로 실행한다. 지원 step은 `observation`, `goal_assessment`,
`goal_resolution`, `preference`, `capability`, `choice`, `next_action`,
`capability_selection`, `selected_action_execution`이며, 완료된 각 step의 결과·cursor를 개인 상태에
저장한다. 예산에 닿으면 `paused_budget`으로 남고, 같은 graph 바이트 SHA-256을
제시해야 재개된다. capability 구현 자체는 재시작 뒤 다시 등록해야 한다.

`alma_environment.run_local_environment()`와 CLI `--environment`는 위 scripted
cycle과 별개인 작은 로컬 환경 경로다. 설정은 초기 공개 관찰, 수치형 목표 조건,
정보 공백, 허용된 read 계약과 그 공개 응답만 제공한다. runtime은 관찰을 일반
`turn()`/event ledger에 먼저 기록하고 목표 조건과 실제 측정값에서 threat/resolved를
계산한다. 정보 공백에는 `provides`가 일치하는 read contract만 선택하며, 일치 항목이
없거나 여럿이면 호출하지 않고 `safe_hold`로 남긴다. `bench/alma_local_environment.json`
은 물 목표·무관한 날씨 read·관련 물 read를 함께 둔 고정 예이고,
`bench/alma_environment_reproduction.py`는 budget 중단, 새 runtime 재개, 계약 선택,
관찰 후 목표 변화와 독립 환경 결과를 분리해 JSON으로 보고한다. 이 환경은 로컬
simulation이며 외부 계정·메시지·write/execute 권한을 사용하지 않는다.

`bench/alma_learning_lifecycle_reproduction.py`는 별도의 3개 구성 경험,
1개 검증 경험, 1개 post-activation 적용 경험을 고정해 lineage ID가 겹치지
않는지 확인한다. 같은 상태·팩에서 candidate만 OFF로 바꾼 대조와 구성 근거
정정 뒤의 철회도 별도 결과로 기록한다.

`bench/alma_unified_reproduction.py`는 하나의 personal state에서 자연어 구조 학습,
procedural recall, scoped mental expectation, 로컬 환경의 정보 공백/read 선택, budget
중단과 새 runtime 재개, 원천 경험 교정의 철회와 정확한 원 근거 복구 뒤 semantic 재검증,
환경 목표의 독립 지속을 한 시나리오로
검사한다. 이 결과는 모든 자연어·환경으로의 일반화를 주장하지 않는 고정 범위 근거다.

위협이 활성일 때 `choose()`는 경험에서 형성된 preference를 우선 유지하면서,
후보의 `protects_goal_ids` 또는 `supports_relation`이 현재 위협 원인과 맞는지도
점수화한다. 따라서 같은 사건이라도 서로 다른 목표 관계를 둔 두 개체는 다른
후보를 고를 수 있으며, 원인이 해소되면 이 적합도는 사라진다.
`resolve_goal(goal_id, outcome, source_event_id=...)`는 실제 event ledger를 근거로
active goal을 `achieved`/`abandoned`/`failed`로 닫는다. 연결된 pending/ready 보호 후보는
취소하지만 과거 후보·목표·원인 기록은 보존한다.
`propose_next_action(source_event_id=..., goal_id=...|information_gap=...)`는 관찰된
사건을 근거로 `protect_goal` 또는 `seek_information` 후보를 **pending**으로만
기록한다. 이는 미리 쓴 대사나 자동 외부 실행이 아니며, cycle의 `next_action` step도
동일한 후보 기록을 재개 가능한 로그에 남긴다.
`select_capability_for_action()`은 `seek_information` 후보에서 read capability가 정확히
하나일 때만 ready plan을 만들고, 없거나 여럿이면 `safe_hold`로 남긴다. 선택 자체는
호출 권한이 아니므로 실제 adapter 실행은 여전히 별도 cycle capability step과 승인 규칙을
거친다.
`execute_selected_action(action_id, payload, request_id=...)`은 ready인 이 후보를
명시적으로 실행할 때만 선택한 read adapter를 호출한다. action ID와 capability run의
receipt를 함께 남기며, 실패·재시작 뒤 adapter 부재는 `safe_hold`로 남긴다. 따라서
선택만으로 외부 행동이 자동 실행되지는 않는다.
이미 ready였던 후보도 capability 구성이 바뀌어 모호해지면 선택 이력을 남기고 다시
`pending`으로 돌아간다.

## Capability adapter

`register_capability(spec, adapter)`는 `read`/`write`/`execute` 권한과 schema를
선언한다. write/execute는 승인 없이는 호출하지 않으며 request ID 중복은 같은
capability의 같은 기록을 돌려준다. 서로 다른 capability는 같은 request ID를 독립적으로
사용할 수 있다. adapter 구현은 호스트 로컬이므로 재시작 후 재등록하지 않으면
고정된 `adapter_unavailable` 실패를 남긴다. 이는 개인 기억/선호를 바꾸지 않는다.
같은 capability를 다시 등록하면 최신 adapter만 활성화하되 이전 schema는
`capability_revisions`에 version과 함께 남고, 각 실행 결과도 사용한 version을 기록한다.
`input_schema`/`output_schema`는 object/array/string/number/boolean/null/any와
object의 required field를 검사한다. 생략하면 명시적으로 `{ "type": "any" }`를
상태 선언에 저장하며, 계약 위반은 adapter 실행/결과를 성공으로 기록하지 않는다.
Schema를 만족해도 JSON 상태로 보존할 수 없는 결과는 `output_not_portable` 실패로
기록하므로, 저장 단계에서 실행 이력이 사라지거나 상태 파일이 깨지지 않는다.
동일한 원칙으로 비직렬화 입력은 adapter를 호출하지 않고 `input_not_portable` 실패로
영속 기록한다.
adapter가 `idempotency_key_field`를 object input 계약에 선언하면 runtime은 journal의
request ID를 그 필드로 전달한다. 선언하지 않은 adapter에는 임의 key를 주입하지 않으며,
로컬 상태 파일만으로 외부 효과의 exactly-once를 보장한다고 주장하지 않는다.
`local_file_read_adapter(root)`는 실제 로컬 read capability의 최소 예다. 호출자가
명시한 root 밖의 path·디렉터리·크기 상한 초과를 거부하고, 읽은 상대 경로/바이트/텍스트를
SYSTEM 실행 이력에 남긴다. 이는 계정/네트워크 권한을 자동으로 얻지 않는다.
각 호출의 성공·승인 대기·실패는 별도의 COGNITION feedback log에도 남기므로,
후속 cycle과 ledger 검색은 adapter의 오류를 실행 성공으로 혼동하지 않는다.

현재 이 루프는 고정 평가용 첫 버전이다. Mental 자연어 표면과 모든 외부 tool을
일반적으로 이해한다고 주장하지 않는다. 지원 범위와 회귀는
`tests/test_alma_runtime.py` 및 `bench/experience_concept_reproduction.py`의 실제
시나리오로 제한된다.

특히 `test_one_persistent_life_connects_experience_transfer_goal_tool_correction_and_restart`
는 하나의 상태 파일에서 Quantity 경험 일반화와 Location 전이, 목표 위협, budget
중단/재개, read capability, Mental 기대의 세계 사실 격리, 근거 정정에 따른 Quantity
semantic 철회와 독립 Location 지식 보존, episodic 압축, 새 프로세스 복구를 연속으로
확인한다. 이는 모든 자연어/도메인의 일반성을 주장하는 시험은 아니다.

## 재현 측정

`bench/experience_concept_reproduction.py --output report.json`은 팩 안 각 파일의
원 바이트 SHA-256과 CRLF/LF 진단 SHA-256을 별도로 기록한다. 무결성 검증은 항상
원 바이트 해시만 사용한다. 같은 줄 내용의 체크아웃 차이는 진단할 수 있지만 서로를
같은 팩으로 검증하게 만들지는 않는다. 보고서의 `costs`에는 초기 설정, 학습 준비,
사건 실행, warm 관계 질의, 이유 설명, state 저장, 저장 뒤 복구의 표본 수·합계·중앙값이
들어간다. Windows에서는 `resource`가 없어 RSS가 `supported: false`로 명시된다.

`bench/alma_integrated_reproduction.py --output alma-report.json`은 별도 고정
상태 파일에서 Quantity/Location/Social/Mental 전이(Mental의 계획·조건·가정과
세계 사실 격리 포함), semantic 분리, goal/cycle 예산 재개, capability, 승인 규칙 A/B, 근거 교정, 압축과 재시작을 한 report에
기록한다. `costs`는 학습, budget 전 중단, 재시작 복구, episodic 저장, 재시작 뒤
장기 ledger 검색을 별도 측정한다. `functional_checks`는 통과한 기능 검사의 수이고,
`outcomes`는 독립 문제의 solved/safe_hold/wrong/execution_error/unverifiable를 위한
별도 분류다. 통합 재현에는 독립 문제 표본이 없으므로 그 solved 수를 기능 검사 수로
대체하지 않는다.
같은 보고서의 `tracemalloc_peak_bytes`는 Python 할당 peak이고, `process_max_rss_*`는
프로세스 RSS 계측 지원 여부와 값을 별도로 나타낸다. Windows처럼 `resource`가 없는
환경에서는 RSS를 추정하지 않고 `supported: false`로 기록한다.

## 선택 정의 말뭉치

`data/위키/정의문.jsonl`은 배포 checkout에 없는 선택 원문 말뭉치다. 없을 때
정의 기반 coverage와 UI 원문 정의 tests만 `optional local definition corpus is not
installed`로 skip하며, event/팩/ALMA 핵심 fixture는 영향을 받지 않는다. 승인된
말뭉치를 해당 UTF-8 JSONL 경로에 설치한 뒤 `python -m pytest -q
tests/test_local_definitions.py tests/test_general_knowledge_coverage.py`로 별도
coverage를 실행한다.
