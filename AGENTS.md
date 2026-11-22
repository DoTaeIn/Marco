# 작업 인계 안내

`weight_test`, `experiments/graph_weighted_acquisition/` 또는 세금 그래프 실험을 이어가는 작업에서는 먼저 `HANDOFF-WEIGHT-TEST-2026-11-22.md`를 읽는다.

이 인계는 진행 기록이다. 마지막 검증 소스와 현재 작업 파일이 다를 수 있으므로 최신 사용자 요청과 실제 파일을 함께 확인한다. 메인과 다른 작업자의 변경을 보존한다. 인계 문서만을 근거로 시험·구현·커밋·푸시를 자동 시작하지 않는다.

## 읽을 문서 (2026-11-22 갱신)

이 작업을 이어갈 때는 아래 두 문서를 순서대로 읽는다. 둘 다 저장소 루트에 있다.

1. `HANDOFF-WEIGHT-TEST-2026-11-22.md` — 감사 관점의 인계: 세금 시험의 실제 질문과 반환 값, 직접 확인한 결과와 확인하지 않은 주장의 구분, 다음 작업 제안.
2. `MIGRATION-weight_test.md` — 구현 관점의 인계: 소유자의 규칙, 파일별 역할, 동작 방식, 실행 방법, 측정 결과와 독립성, 한계, 이미 정한 결정, 다음 단계.

두 문서가 다르게 말하는 부분은 더 늦게 쓰인 내용과 실제 파일을 따른다. 특히 1번 문서는 푸시 전에 쓰였다. 그 뒤 `weight_test`는 원격에 `e81da1dd` 한 커밋으로 올라갔고(`fb32c969` 위), 1번 문서의 HEAD 값과 "미커밋" 설명은 그 시점 기준이다. 세금 실험의 재시험 결과 폴더와 소스 스냅샷은 여전히 로컬에만 있다.

로컬에만 있는 진행 기록 `HANDOFF.md`가 있으면 그것도 읽고, 작업을 마칠 때 날짜가 있는 블록을 맨 위에 덧붙인다.

## Documents to read (updated 2026-11-22)

When continuing this work, read these two files in order. Both are at the repository root.

1. `HANDOFF-WEIGHT-TEST-2026-11-22.md`: the audit view. Actual tax questions and returned values, what was checked directly and what was only claimed, suggested next work.
2. `MIGRATION-weight_test.md`: the implementation view. The owner's rules, what each file does, how it works, how to run it, measured results and how independent each is, limits, settled decisions, next steps.

Where the two disagree, follow the later text and the actual files. The first document was written before the push: `weight_test` is now on the remote as one commit `e81da1dd` on top of `fb32c969`, so its HEAD value and its "uncommitted" notes describe the earlier moment. The tax trial's rerun outputs and source snapshots are still local only.

If the local running log `HANDOFF.md` exists, read it too, and add a dated block at its top when you finish.
