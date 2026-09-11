# 검증된 표현 교정 저장

`semantic_feedback.py expression`은 이제 교정 사례와 별도 검증 사례를 함께 받는다.
예전의 주석 사례 하나만 담은 JSON은 이 CLI에서 더 이상 저장 입력으로 쓰지 않는다.
직접 `RelationalParser.learn`을 부르는 저수준 감독 학습 API는 그대로 남는다.

입력 JSON에는 다음 두 키가 필요하다.

- `correction`: `text`, `slots`, `meaning`으로 된 주석 사례.
- `validation`: `id`, `text`, `expected`를 가진 검증 사례 배열.

`expected`는 `{"facts":[{"triple":["주체","관계","대상"]}],"query":null}` 같은
해석 구조이며, 해석하면 안 되는 반례는 `null`이다. 부정과 양태도 기대 사실의
메타데이터로 검사할 수 있다. 성공 사례와 반례가 모두 필요하며, 교정에 사용한
개체 문자열이 검증 문장에 포함되면 거부한다.

```sh
python semantic_feedback.py expression correction.json --output /private/tmp/learned-relations.json
NAI_RELATIONAL_MODEL=/private/tmp/learned-relations.json python semantic_feedback.py diagnose '질문'
```

교정 한 개로 복사한 모델에 후보를 먼저 만든다. 검증의 기대 구조는 후보 생성에
쓰지 않는다. 모든 검증을 통과하고 기존 실패가 적어도 하나 개선되어야 모델을
반영한다. CLI는 그때만 저장한다. 거부된 시도는 기존 출력 파일도 덮어쓰지 않는다.
검증 결과와 전후 모델 SHA-256은 CLI 출력에 남는다. 기본 시드 파일 저장 금지는 유지한다.

테스트에서는 '하루의 키는 모래의 키를 웃돈다'를 주석 교정하고, 다른 두 개체로
주체·대상 뒤집기와 부정 반례를 검사했다. 저장 후 실제 엔진은 교정·검증에 없던
세 개체의 비교 사슬을 풀었다. 검증 문장이나 정답은 저장 모델에 들어가지 않는다.

이는 사람이 제공한 의미 주석의 제한적인 전이 검증이다. 새로운 표현의 뜻을 스스로
발견하거나 자유로운 자연어 교정으로 학습하는 단계는 아니다. 유한 검증 통과가
보편적으로 올바른 해석을 보장하지 않는다. 기존 고정 평가 파일은 수정하지 않았다.
