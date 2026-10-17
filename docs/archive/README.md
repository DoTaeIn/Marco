# 문서 보관

2026-10-18 문서 정리에서 날짜별 목표·작업 요청, 중복 설명, 취소된 MARCO 1 출시 문서를 제거했다. 로컬 정리 대상은 Markdown 195개였으며, 이 공개 브랜치에는 이전 공개 소스에 있던 164개의 삭제를 반영했다.

[2026-10-18-document-cleanup.zip](2026-10-18-document-cleanup.zip)에는 이전 공개 커밋 `bd3bd837fc4db142d773bff9259258c4b073c9e0`의 문서만 담았다. 삭제 문서와 참조·개요를 수정하기 전 문서, 총 182개이며 각 경로와 SHA-256은 ZIP의 `CLEANUP-MANIFEST.json`에 있다. 로컬 인계 기록·평가 원문·개발 전용 자료는 포함하지 않았다.

압축 파일 SHA-256: `782505aa4abac1c1cf4a8880e112f1ffc4ecfcd8feec977b843e4e1344c60df6`

```bash
python -m zipfile -l docs/archive/2026-10-18-document-cleanup.zip
```

필요한 문서 한 개만 별도 폴더에 복구한다. 현재 문서나 평가 기록 위에 전체를 풀어 덮어쓰지 않는다. 보관 문서 링크의 제목에는 ZIP 내부의 원래 경로를 표시했다. 과거 평가의 재실행·재채점을 허용하는 것은 아니다. 현재 구조와 검증 범위는 [루트 README](../../README.md)를 참고한다.
