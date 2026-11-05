# 문서 보관

오래된 목표·작업 요청과 중복 설명을 작업 문서에서 정리했다. 공개 보관본에는 이번 변경으로 삭제하는 Markdown 164개만 이전 커밋의 원문 그대로 담았다. 인계 메모·로컬 실행 기록은 포함하지 않는다.

- [2026-10-18-document-cleanup.zip](2026-10-18-document-cleanup.zip)
- 공개 보관본 정리일: 2026-11-05
- SHA-256: `c4e8d442b6ed404ce5fc27036321783a7f960aef2abae189913b091612c32341`

압축 항목은 모두 이전 커밋의 공개 문서와 바이트 단위로 일치한다. 취소된 계획과 당시 측정 기록은 역사 자료이며 최신 구현의 보증으로 사용하지 않는다.

목록 확인:

```bash
python -m zipfile -l docs/archive/2026-10-18-document-cleanup.zip
```

필요한 문서 한 개를 **별도 폴더에** 복구하는 예:

```python
from pathlib import Path
from zipfile import ZipFile

original = "docs/ko/2026-09-29-experiment-log.md"
with ZipFile("docs/archive/2026-10-18-document-cleanup.zip") as archive:
    destination = Path("/tmp/marco-doc-history") / original
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(archive.read(original))
```

현재 문서나 평가 기록 위에 ZIP 전체를 풀어 덮어쓰지 않는다. 복구가 평가 재실행·재채점을 허용하는 것은 아니다. 이전 보관 파일이 이 폴더에 있으면 그 기록도 그대로 유지한다.
