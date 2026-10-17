# 문서 안내

현재 구조, 기능 범위, 최근 실제 문장 검증 결과는 [루트 README](../README.md)를 기준으로 읽는다. 날짜별 목표와 중복 설명은 정리했고, 이전 원문은 [보관 안내](archive/README.md)에 따라 복구할 수 있다.

## 사용·호환성 계약

- [mco 가이드](mco/README.md): 설치·Python API·CLI. 과거 실행 예시는 해당 문서가 명시한 당시 버전의 기록이다.
- [API 계약](mco/api.md), [MCO 파일 형식](mco/format-1.md)
- [Overlay](architecture/overlay.md), [Snapshot](architecture/snapshot.md)

## 개발 참고

`architecture/`의 모듈별 문서는 상세 설계와 작성 당시의 구현 기록이다. 과거 MARCO 1 출시·동결 계획은 현재 개발 상태를 정하지 않는다. 최신 모듈 연결은 루트 README의 Mermaid와 실제 소스를 확인한다.

`ko/`에는 코드·도구·검사에서 사용하는 개발/저작 안내와 trace 스키마, 기존 구조 원칙을 남겼다. `releases/`의 mco 두 문서는 배포 패키지의 포함 파일이므로 유지한다.

`target-map.json`과 평가 JSON 등 비 Markdown 자료, 실제 지식 데이터, 테스트 fixture, 별도 TTS·프로토타입 문서, 고정된 개발·평가 계약은 이번 정리에서 삭제하지 않았다. 과거 평가를 새 점수로 덮거나 자동 재실행하지 않는다.
