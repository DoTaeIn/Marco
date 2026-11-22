# 세금 지식 그래프: 첫 실행 결과

2026-11-19 기준. 24개 질문 모두 동일한 14개 사실 그래프를 받았다. 그래프 방식은 질문을 모델이 읽은 뒤 그래프를 검색한다. 자연어 방식은 전체 사실 문장과 질문을 모두 모델이 읽는다. 답변 칸은 모델의 상태, 원시 answers 배열, 이유 및 검증 상태를 그대로 표시한다.

적용 범위는 사실 메타데이터에 기록되었으나 그래프의 조건으로 자동 검증되지 않는다. 입력 문장은 공식 페이지를 근거로 만든 정규화 문장이지 공식 페이지의 직인용이 아니다. 질문별 정답 메타데이터는 추론에 사용하지 않았다.

| 번호 | 질문 | 그래프 방식: 실제 원시 결과 | 자연어 방식: 실제 원시 결과 |
|---|---|---|---|
| Q01 | 일반과세자의 세율은 무엇인가? | hold; answers=[]; reason=the question was not read with confidence: every reading uses something never seen in training; executor=not run | hold; answers=[]; reason=the passage was not read with confidence: search bound reached; executor=not run |
| Q02 | 일반과세자의 과세기간은 무엇인가? | hold; answers=[]; reason=the question was not read with confidence: every reading uses something never seen in training; executor=not run | hold; answers=[]; reason=the passage was not read with confidence: search bound reached; executor=not run |
| Q03 | 개인일반사업자의 신고횟수는 무엇인가? | hold; answers=[]; reason=the question was not read with confidence: the text cannot be cut into known pieces; executor=not run | hold; answers=[]; reason=the passage was not read with confidence: search bound reached; executor=not run |
| Q04 | 법인사업자의 신고횟수는 무엇인가? | hold; answers=[]; reason=the question was not read with confidence: the text cannot be cut into known pieces; executor=not run | hold; answers=[]; reason=the passage was not read with confidence: search bound reached; executor=not run |
| Q05 | 일반과세자제1기확정신고의 신고기간은 무엇인가? | hold; answers=[]; reason=the question was not read with confidence: every reading uses something never seen in training; executor=not run | hold; answers=[]; reason=the passage was not read with confidence: search bound reached; executor=not run |
| Q06 | 일반과세자제2기확정신고의 신고기간은 무엇인가? | hold; answers=[]; reason=the question was not read with confidence: every reading uses something never seen in training; executor=not run | hold; answers=[]; reason=the passage was not read with confidence: search bound reached; executor=not run |
| Q07 | 간이과세자의 신고기간은 무엇인가? | hold; answers=[]; reason=the question was not read with confidence: every reading uses something never seen in training; executor=not run | hold; answers=[]; reason=the passage was not read with confidence: search bound reached; executor=not run |
| Q08 | 사업자등록의 신청기한은 무엇인가? | hold; answers=[]; reason=the question was not read with confidence: every reading uses something never seen in training; executor=not run | hold; answers=[]; reason=the passage was not read with confidence: search bound reached; executor=not run |
| Q09 | 사업자등록의 신청경로는 무엇인가? | hold; answers=[]; reason=the question was not read with confidence: the text cannot be cut into known pieces; executor=not run | hold; answers=[]; reason=the passage was not read with confidence: search bound reached; executor=not run |
| Q10 | 국세상담센터의 상담전화는 무엇인가? | hold; answers=[]; reason=the question was not read with confidence: the text cannot be cut into known pieces; executor=not run | hold; answers=[]; reason=the passage was not read with confidence: search bound reached; executor=not run |
| Q11 | 종합소득세일반신고의 신고기간은 무엇인가? | hold; answers=[]; reason=the question was not read with confidence: every reading uses something never seen in training; executor=not run | hold; answers=[]; reason=the passage was not read with confidence: search bound reached; executor=not run |
| Q12 | 2025년귀속종합소득세일반신고의 신고기한은 무엇인가? | hold; answers=[]; reason=the question was not read with confidence: every reading uses something never seen in training; executor=not run | hold; answers=[]; reason=the passage was not read with confidence: search bound reached; executor=not run |
| Q13 | 성실신고확인서제출자의 신고기한은 무엇인가? | hold; answers=[]; reason=the question was not read with confidence: every reading uses something never seen in training; executor=not run | hold; answers=[]; reason=the passage was not read with confidence: search bound reached; executor=not run |
| Q14 | 2026년제1기부가가치세확정신고의 신고기한은 무엇인가? | hold; answers=[]; reason=the question was not read with confidence: every reading uses something never seen in training; executor=not run | hold; answers=[]; reason=the passage was not read with confidence: search bound reached; executor=not run |
| Q15 | 면세나 영세율에 해당하지 않는 일반과세자의 부가가치세율은 몇 퍼센트인가요? | hold; answers=[]; reason=the question was not read with confidence: the text cannot be cut into known pieces; executor=not run | hold; answers=[]; reason=the passage was not read with confidence: search bound reached; executor=not run |
| Q16 | 사업을 시작하고 사업자등록은 언제까지 신청해야 하나요? | hold; answers=[]; reason=the question was not read with confidence: the text cannot be cut into known pieces; executor=not run | timeout; answers=[]; reason=first attempt exceeded 10 seconds; executor=기록 없음 |
| Q17 | 사업자등록을 온라인으로 신청하려면 어디를 이용하면 되나요? | hold; answers=[]; reason=the question was not read with confidence: the text cannot be cut into known pieces; executor=not run | timeout; answers=[]; reason=first attempt exceeded 10 seconds; executor=기록 없음 |
| Q18 | 국세 관련 상담을 받으려면 국번 없이 몇 번으로 전화하나요? | hold; answers=[]; reason=the question was not read with confidence: the text cannot be cut into known pieces; executor=not run | timeout; answers=[]; reason=first attempt exceeded 10 seconds; executor=기록 없음 |
| Q19 | 2025년에 발생한 소득에 대한 종합소득세 일반 신고는 2026년 언제까지 해야 하나요? | hold; answers=[]; reason=the question was not read with confidence: the text cannot be cut into known pieces; executor=not run | timeout; answers=[]; reason=first attempt exceeded 10 seconds; executor=기록 없음 |
| Q20 | 2026년 제1기 부가가치세 확정신고의 실제 일반 신고기한은 언제인가요? | hold; answers=[]; reason=the question was not read with confidence: the text cannot be cut into known pieces; executor=not run | hold; answers=[]; reason=the passage was not read with confidence: search bound reached; executor=not run |
| Q21 | 일반과세자가 공급가액 100만원인 과세 거래에 일반세율 10%를 적용하면 부가가치세는 얼마인가요? | hold; answers=[]; reason=the question was not read with confidence: the text cannot be cut into known pieces; executor=not run | hold; answers=[]; reason=the passage was not read with confidence: search bound reached; executor=not run |
| Q22 | 저는 올해 종합소득세 신고 대상인가요? | hold; answers=[]; reason=the question was not read with confidence: the text cannot be cut into known pieces; executor=not run | hold; answers=[]; reason=the passage was not read with confidence: search bound reached; executor=not run |
| Q23 | 상속세의 신고기한은 언제인가요? | hold; answers=[]; reason=the question was not read with confidence: the text cannot be cut into known pieces; executor=not run | hold; answers=[]; reason=the passage was not read with confidence: search bound reached; executor=not run |
| Q24 | 일반과세자의 부가가치세 일반세율은 0%가 맞나요? | hold; answers=[]; reason=the question was not read with confidence: the text cannot be cut into known pieces; executor=not run | hold; answers=[]; reason=the passage was not read with confidence: search bound reached; executor=not run |

## 구분별 결과

- direct: 14문항, 그래프 상태 {'hold': 14}, 직접 사실값과 정확히 일치한 답 0개, 그 밖의 답변 0개. 보류는 정답으로 계산하지 않았다.
- paraphrase: 6문항, 그래프 상태 {'hold': 6}, 직접 사실값과 정확히 일치한 답 0개, 그 밖의 답변 0개. 보류는 정답으로 계산하지 않았다.
- boundary: 4문항, 그래프 상태 {'hold': 4}, 직접 사실값과 정확히 일치한 답 0개, 그 밖의 답변 0개. 보류는 정답으로 계산하지 않았다.

## 사실 및 출처

| 사실 | 대상 | 속성 | 값 | 범위 | 출처 |
|---|---|---|---|---|---|
| F01 | 일반과세자 | 세율 | 10% | 부가가치세 일반세율; 영세율·면세 등 예외 제외 | [국세청](https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?cntntsId=7693&mi=2272) |
| F02 | 일반과세자 | 과세기간 | 6개월 | 부가가치세 일반 계속사업자 과세기간 | [국세청](https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?cntntsId=7694&mi=2273) |
| F03 | 개인일반사업자 | 신고횟수 | 연2회 | 통상 부가가치세 정기신고; 특례 제외 | [국세청](https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?cntntsId=7694&mi=2273) |
| F04 | 법인사업자 | 신고횟수 | 연4회 | 통상 부가가치세 신고; 소규모법인 예정고지 등 특례 제외 | [국세청](https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?cntntsId=7694&mi=2273) |
| F05 | 일반과세자제1기확정신고 | 신고기간 | 7월1일~7월25일 | 일반 법정기간; 토요일/공휴일/연장 시 실제기한 달라짐 | [국세청](https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?cntntsId=7694&mi=2273) |
| F06 | 일반과세자제2기확정신고 | 신고기간 | 다음해1월1일~1월25일 | 일반 법정기간; 토요일/공휴일/연장 예외 | [국세청](https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?cntntsId=7694&mi=2273) |
| F07 | 간이과세자 | 신고기간 | 다음해1월1일~1월25일 | 일반 계속사업자 정기신고; 전환·세금계산서발급 중간신고 예외 별도 | [국세청](https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?cntntsId=7694&mi=2273) |
| F08 | 사업자등록 | 신청기한 | 사업개시일부터20일이내 | 사업장별 신청; 개시 전 신청도 가능 | [국세청](https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?cntntsId=7776&mi=2444) |
| F09 | 사업자등록 | 신청경로 | 홈택스 | 온라인 신청경로; 세무서 방문도 가능 | [국세청](https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?cntntsId=7806&mi=2486) |
| F10 | 국세상담센터 | 상담전화 | 126 | 국번없이 국세상담 | [국세청](https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?cntntsId=7776&mi=2444) |
| F11 | 종합소득세일반신고 | 신고기간 | 다음해5월1일~5월31일 | 원칙적 법정기간; 성실신고확인서 제출/휴일/연장 예외 | [국세청](https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?cntntsId=7665&mi=2225) |
| F12 | 2025년귀속종합소득세일반신고 | 신고기한 | 2026년6월1일 | 일반 신고기한; 개별 특수사유 제외; 납부직권연장과 신고 구분 | [국세청](https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?cntntsId=7665&mi=2225) |
| F13 | 성실신고확인서제출자 | 신고기한 | 다음해6월30일 | 종합소득세 일반법정기한; 개별연장 별도 | [국세청](https://www.nts.go.kr/nts/cm/cntnts/cntntsView.do?cntntsId=7665&mi=2225) |
| F14 | 2026년제1기부가가치세확정신고 | 신고기한 | 2026년7월27일 | 2026년 공지 일반신고납부기한; 개별연장 별도 | [국세청](https://www.nts.go.kr/gangseo/na/ntt/selectNttInfo.do?mi=5512&nttSn=1353291) |

## 재현과 검증

전체 결과와 모델의 후보 읽기·카운트·근거·독립 검증 상태는 `first_results.jsonl`에 있다. 각 줄은 고정된 manifest와 모델의 SHA-256을 포함하며, 한 번의 실행에서 처음 기록된 결과다. 응답이 보류되었다는 것은 해당 사실이 없다는 판단과 다르다. 그래프 데이터는 사람이 구성했으며 14개 사실에 대한 작은 시험이므로 세법 전반의 성능을 나타내지 않는다.

- manifest SHA-256: 1f6972280a86b930d44c41eb965af19cd74d3cf19a66cbfc16ba324bff8aa9a1
- model SHA-256: b4a9cdeaf3fb67af41e4386480c25b490101db1f71e47e67ea73388fed0a2fda
- first_results SHA-256: a8ebaac4210fc774c3526bce7dd04431ad9783a4c9d1f18391136c8bfb12ef35

## 사후 문형 진단 (별도 4문항)

기존 예시의 질문 문형에 사실의 대상만 대입했다. 조사가 어색한 표현도 포함되며, 독립적인 일반화 평가가 아니다. 원본 모델과 동일한 전체 그래프를 사용했다.

| 번호 | 질문 | 실제 원시 결과 |
|---|---|---|
| C01 | 일반과세자의 세율은 얼마인가? | hold; answers=[]; reason=the question was not read with confidence: every reading uses something never seen in training; executor=not run |
| C02 | 법인사업자의 신고횟수은 몇회인가? | hold; answers=[]; reason=the question was not read with confidence: every reading uses something never seen in training; executor=not run |
| C03 | 사업자등록의 신청경로은 어디인가? | hold; answers=[]; reason=the question was not read with confidence: every reading uses something never seen in training; executor=not run |
| C04 | 국세상담센터의 상담전화은 무엇인가? | hold; answers=[]; reason=the question was not read with confidence: every reading uses something never seen in training; executor=not run |

- 사후 진단 첫 결과 SHA-256: c52e76d2543022bcacfb725b39e7dcdc5635e24803c7b05317b5f75d4d9ff150


## 저장된 진단 영수증 추가 분석

추가 모델 실행 없이 C01–C04의 저장된 첫 후보 terms를 읽었다. C01 일반과세자, C02 법인사업자, C03 사업자등록은 5글자 길이 관찰 횟수0, C04 국세상담센터는 6글자 길이 관찰 횟수0이다. 각 첫 후보에서 이것이 유일한 count0 항목이었다. 해당 길이가 일반적으로 유효하지 않다는 뜻이 아니라, 현재 모든 항목의 관찰을 요구하는 정책이 새 값의 길이를 미지원으로 처리한 것이다. 질문 그래프가 승인되지 않아 세무 사실 조회와 native 검증은 실행되지 않았다.

실험 준비의 한계도 남긴다. 새 가상 학습 예문 일부는 열린음절 속성 뒤에도 ‘은’을 붙여 ‘신고횟수은’, ‘신청경로은’, ‘상담전화은’ 같은 잘못된 조사를 포함했다. 이 오류는 실험 작성 과정의 문제이며 모델의 일반 세무 판단 능력으로 전가하면 안 된다. 원본 24개 질문은 문법적으로 작성했고, 사후 4개는 어색한 원래 학습 문형을 그대로 보존했다. 원본 입력·모델·첫 출력은 수정하지 않았다. 결과는 이 제한된 새 표현 학습 설정에서의 실패이며, 세법 지식 자체의 부재나 모든 그래프 모델의 불가능성을 증명하지 않는다.
