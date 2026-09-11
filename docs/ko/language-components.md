# 대화 언어 부품

`input_understanding`은 언어별 키워드나 정규식을 갖지 않는다. 언어 팩 하나를
선택하면 같은 JSON schema를 반환한다.

기본 선택은 `styles/한국어.json`이며 `NAI_LANGUAGE=english` 또는
`KG_LANG=english`으로 바꾼다. 파일 경로도 직접 줄 수 있다.

```python
understand("summarize the meeting", language="english")
understand("take invoices", language="/path/to/my-language.json")
```

각 팩의 `대화이해`(또는 `conversation`)는 다음만 가진다.

- `templates`: `{target}`, `{count}` 같은 슬롯을 쓰는 선언형 입력/결과 쌍
- `phrases`: 짧은 고정 대화 입력/결과 쌍
- `context_refs`, `replies`: 언어별 문맥 지시어와 응답
- `backend`: 선택 사항. `module:Class` 또는 `module:factory`로 더 좋은
  의미 추출 부품을 지정한다. 해당 객체는 `parse(text, pack)`을 구현한다.

기본 `TemplateBackend`는 의존성이 없고 정규식을 쓰지 않는다. 더 정확한 온디바이스
분류기나 원격 모델은 backend 부품으로 바꾸되, 결과는 기존 `understand` schema를
유지해야 한다. URL·파일 경로·shell 프로토콜은 자연어가 아닌 구조이므로 코어에서
보수적으로 검증하며, 어떤 backend도 실행 권한을 얻지 못한다.

문서 발췌의 `이유/절차/정의` 같은 꼴 분류도 더 이상 한국어 정규식으로 추측하지
않는다. 사람 라벨은 그대로 우선 적용되고, 새 문장은 `NAI_PASSAGE_BACKEND`에
`module:Class`를 지정해 교체한 `classify(text)` 부품이 분류한다. 부품이 없을 때는
의미를 지어내지 않고 `진술`로 남긴다.
