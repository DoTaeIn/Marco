# MRL 9차 결과 — 늘어나는 지식과 복구 가능한 실행

요청한 다섯 영역을 격리 작업트리 `C:/Users/hirob/.codex/worktrees/mrl-runtime/Marco/mrl/`에 구현했다. GPT-5.6 Terra 작업자들이 저장·추론 검증·컴파일러를 병렬 작업했고, 주 작업에서 런타임 통합과 추가 수정·검증을 수행했다. 다른 Marco 체크아웃에는 반영하지 않았다. 아직 실험용 언어이며 v0.1 전체 구현 완료를 뜻하지 않는다.

## 구현 범위

| 영역 | 이번에 실행 가능한 것 | 범위 제한 |
|---|---|---|
| 대용량 저장 | 안정적인 fact/symbol ID, ID·predicate 색인, 256개 단위 페이지 공유와 변경 시 복사, 공유 메모리 예산. 소스에서 기존 16,384 한도를 넘어 로드한다. | capacity는 si32 범위이며 실제 한도는 메모리 예산. 페이지 포인터 메타데이터 복사와 해시 확장에는 전체 크기에 따른 비용이 있다. |
| 증분 추론 | 최대 8개 전제·8개 변수·128개 규칙. 연쇄·재귀 추론, 중복·대체 근거, 부정 사실, 삭제·정정 후 재도출. | 삭제는 영향받는 predicate 영역을 재계산한다. 항상 변경 한 건의 비용만 드는 알고리즘은 아니다. 가변 head predicate는 더 넓게 재계산한다. |
| 선택 질의 | exists, count, 필터 select, 마지막 평가의 changes, 선택된 근거를 따라가는 explain. 선택 결과만 복사하고 스냅샷 버전을 보존한다. | explain은 선택된 증명 DAG다. 모든 대체 증명 열거는 v7에 없다. 기존 v4–v6 provenance 경로는 유지한다. |
| 지속 저장 | save의 체크포인트·준비된 엔진 캐시, commit의 변경분 기록, restore의 캐시+커밋 재생. 체크섬·규칙/내용 식별·증명 연결 검증, 원자적 교체, 끊긴 마지막 기록 복구. | 재시작은 파일 검증·색인 복원을 수행한다. 작은 추가마다 전체 캐시를 쓰지는 않지만 재시작 비용은 저장 크기에 따라 증가한다. |
| 언어 기능 | 관리형 일반 record, 중첩/관리형 Result, map<s,si>·map<s,s>, 검사된 배열 쓰기, 상대경로 import·중복 제거·순환 검사·원본 파일 위치 오류. | import는 한 프로그램의 이름 공간으로 합쳐진다. 패키지 관리자·별도 네임스페이스·임의 map 키/값 타입은 없다. |

## 실제 파일과 재시작 측정

서로 다른 문자열 사실 N개와 단일 `p → q` 규칙을 사용했다. 결과는 약 2N개다. 각 단계는 새 native 프로세스이며 첫 답변 표시는 부모 프로세스에서 받는 시점까지 측정했다. 소스/C 컴파일과 입력 파일 생성은 제외했다. 운영체제 파일 캐시는 비우지 않았다. 각 수치는 3회 중앙값이다. 헤더를 직접 사용하는 native C 경로를 측정하며, MRL 소스→C 실행은 별도 통합 검사에서 20,000건까지 확인했다.

| 입력 사실 | JSONL→첫 답변, 프로세스 시작 포함 | 체크포인트→첫 답변, 프로세스 시작 포함 | 복구 완료 뒤 count만 | 추가 한 건+디스크 commit | 변경 기록 복구 뒤 증분 질의만 |
|---|---:|---:|---:|---:|---:|
| 10,000 | 177.58 ms | 196.64 ms | 0.0017 ms | 0.917 ms | 0.0071 ms |
| 100,000 | 402.42 ms | 381.99 ms | 0.0030 ms | 0.907 ms | 0.0087 ms |
| 1,000,000 | 3001.23 ms | 2746.65 ms | 0.0042 ms | 0.994 ms | 0.0096 ms |

복구 후 count 시간만 전체 시작 시간으로 제시하면 안 된다. 마지막 열도 앞의 전체 복구 시간을 제외한 값이다. 이 단순 규칙에서는 추론이 저렴해서 준비 캐시의 전체 시작 이득이 작을 수 있다. 원시 기록에는 중앙값·nearest-rank p95·모든 표본·메모리·소스 해시가 있다. 표본 3개에서 p95는 최댓값이므로 안정적인 꼬리 지연 추정으로 해석하지 않는다.

100만 입력/200만 결과의 준비 캐시 복원 시 추적 메모리 최대치는 **1.188 GB**였다. 공유 예산 설정은 1.5 GiB다. 이 예산은 저장소·색인·엔진·스냅샷의 추적 할당을 포함하지만 C 입출력 버퍼, 최대 1 MiB JSONL 행 버퍼, 최대 32 MiB journal 트랜잭션 버퍼와 프로세스 전체 RSS를 뜻하지 않는다.

별도의 규칙 없는 숫자 ID 중심 native 미세 측정에서는 100만 건의 추가+질의 중앙값 0.1278 ms, 삭제 10.00 ms, 정정 10.17 ms였다. 실제 문자열 인코딩·JSONL·재시작은 포함하지 않는다. Python oracle 측정은 문자열 생성·전체 closure 출력을 포함하므로 동일 경계의 언어 속도비로 사용하지 않는다.

[재시작 원시 측정](NINTH_RESTART_BENCHMARK.json) / [Native 미세 측정](NINTH_NATIVE_BENCHMARK.json)

```powershell
python -B -m mrl.benchmark_ninth_restart --sizes 10000 100000 1000000 --samples 3
python -B -m mrl.benchmark_ninth_native --sizes 10000,100000,1000000 --samples 5 --python-max 10000 --output mrl/docs/NINTH_NATIVE_BENCHMARK.json
```

## 소스 사용

IR7은 `Horn(memory_budget=..., capacity=..., facts=Facts(...), rules=Rules(...))`로 선택한다. 예산 단위는 byte이고 capacity는 살아 있는 입력/추론 사실의 계산 한도다. 다중 전제는 `Rule(..., body=All(Triple(...), Triple(...)), head=Triple(...))`이다.

```mrl
count = plan.count(predicate="ancestor")
selected = plan.select(subject="a", predicate="ancestor")
found = plan.exists(Triple("a", "ancestor", "d"))
proof = plan.explain(Triple("a", "ancestor", "d"))
changes = plan.changes()
saved = plan.save("knowledge.mrlk")
committed = plan.commit("knowledge.mrlk")
restored = plan.restore("knowledge.mrlk")
```

load/save/commit/restore는 `Result<si32,s>`이며 실패 분기를 처리해야 한다. 성공 값은 byte 수가 아니다. load는 추가한 수, 다른 저장 작업은 현재 입력 사실 수이며 변경 없는 commit은 0이다. correct(Fact(...))와 remove(id)는 사실 ID를 기준으로 수정한다. 질의 문자열은 현재 소스에서 리터럴이다.

changes는 마지막 엔진 평가 트랜잭션의 추가·제거된 참 사실이며 임의 과거 버전 비교 API가 아니다. 같은 버전에서 다시 읽으면 같은 결과다. 스냅샷은 version/complete/reason/fact_count/added_count/removed_count를 제공하고 출력에도 완료 여부가 들어간다. 한도에 걸린 결과를 완성된 추론으로 취급하지 않는다.

[growing_knowledge.mrl](../examples/growing_knowledge.mrl)은 재귀 ancestor 규칙, 저장 뒤 추가, 실제 변경 commit, 복구, 과거 스냅샷 보존을 실행한다. `closure(plan)`은 v7에서도 스냅샷을 만든다. v7 closure_with_provenance는 선택 증명만 제공한다는 미완료 사유를 반환한다. v7에 예전 static `closure(Horn(...))` 또는 예산 없는 Horn 생성자를 섞으면 명시적으로 거절한다. 모든 Horn 생성자에 예산을 쓰고 plan 메서드를 사용한다. 기존 v2–v6 프로그램 자체는 유지한다.

## 저장 수명과 제한

- save는 입력 체크포인트를 원자적으로 교체하고 준비 엔진 캐시를 기록한다. 캐시가 없거나 검증에 실패하면 입력으로부터 다시 추론한다. 다른 규칙 fingerprint의 체크포인트는 거절한다.
- commit은 마지막 성공한 save/restore/commit 뒤 새 symbol과 바뀐 fact 행만 기록하고 디스크 flush 뒤 성공을 반환한다. 매번 전체 준비 캐시를 저장하지 않는다.
- 체크포인트 내용 식별자를 journal 세대 이름에 넣어 다른 체크포인트의 로그를 잘못 적용하지 않는다. 오래된 세대 파일은 자동 삭제하지 않는다.
- 한 체크포인트에는 한 writer를 사용한다. 멀티프로세스 동시 쓰기·분산 저장은 제공하지 않는다. 분기한 Horn은 별도 save/restore 후 커밋한다.
- 끊긴 마지막 기록은 완전한 앞부분만 복원하고 첫 후속 commit 직전에 꼬리를 정리한다. 완전한 레코드의 손상은 거절한다. 커밋 실패의 결과가 불확실하면 다시 save 또는 restore한 뒤 재개한다.
- 문자열·삭제 슬롯·변경 이력은 가족 메모리 예산 안에서 보존된다. restore는 변경 이력과 작업 버퍼를 재구성하지만 fact ID·symbol ID·tombstone을 보존한다. ID를 재사용하는 자동 compaction은 없다. 일반 스냅샷과 달리 Horn 분기 복사본의 첫 질의는 엔진을 새로 준비할 수 있다.

## 검증

전체 **163개 검사 통과**, 실패 0 / 오류 0 / 건너뜀 0. 규칙 fixture 7개·22상태, seeded 무작위 증분 변경과 고정 oracle 대조, 순환 근거 제거·대체 근거·중복·부정, 자원/할당 실패, 관리형 값 해제 균형, 20,000건 소스→C 로드와 Unicode Evidence 출력, 손상/끊긴 기록·재시작 후 재커밋, 캐시 복원 뒤 추가/삭제와 원본 보존을 확인했다.

[검사 로그](NINTH_TEST_LOG.txt) / [소스·보호 파일 해시](NINTH_DELIVERY_VERIFICATION.json). oracle/native_graph.c/native_graph.py/frozen golden 및 Marco 핵심 파일을 유지했다. 실행물은 C11이며 Python은 부트스트랩 컴파일·검증 도구에 필요하다. Marco 본체에 병합·배포하지 않았다.
