# Tax questions after the held-question work

Same 24 questions and 14 facts as the earlier runs, so this is not a fresh test. 132 fictional lessons. The added wordings were chosen after seeing which questions were held.

| Tier | Arm | correct | held as expected | held | wrong | other |
|---|---|---|---|---|---|---|
| direct | graph | 14 | 0 | 0 | 0 | 0 |
| direct | natural | 14 | 0 | 0 | 0 | 0 |
| paraphrase | graph | 3 | 0 | 3 | 0 | 0 |
| paraphrase | natural | 3 | 0 | 3 | 0 | 0 |
| boundary | graph | 1 | 2 | 1 | 0 | 0 |
| boundary | natural | 1 | 2 | 1 | 0 | 0 |

Total time for both arms on 24 questions: 0.67 s. No timeouts.

| Id | Question | Natural-language arm | Trust | What the answer rests on |
|---|---|---|---|---|
| Q01 | 일반과세자의 세율은 무엇인가? | correct: 10% | not independently verified | every condition of the question holds in the passage; not independently verified |
| Q02 | 일반과세자의 과세기간은 무엇인가? | correct: 6개월 | not independently verified | every condition of the question holds in the passage; not independently verified |
| Q03 | 개인일반사업자의 신고횟수는 무엇인가? | correct: 연2회 | not independently verified | every condition of the question holds in the passage; not independently verified |
| Q04 | 법인사업자의 신고횟수는 무엇인가? | correct: 연4회 | not independently verified | every condition of the question holds in the passage; not independently verified |
| Q05 | 일반과세자제1기확정신고의 신고기간은 무엇인가? | correct: 7월1일~7월25일 | not independently verified | every condition of the question holds in the passage; not independently verified |
| Q06 | 일반과세자제2기확정신고의 신고기간은 무엇인가? | correct: 다음해1월1일~1월25일 | not independently verified | every condition of the question holds in the passage; not independently verified |
| Q07 | 간이과세자의 신고기간은 무엇인가? | correct: 다음해1월1일~1월25일 | not independently verified | every condition of the question holds in the passage; not independently verified |
| Q08 | 사업자등록의 신청기한은 무엇인가? | correct: 사업개시일부터20일이내 | not independently verified | every condition of the question holds in the passage; not independently verified |
| Q09 | 사업자등록의 신청경로는 무엇인가? | correct: 홈택스 | not independently verified | every condition of the question holds in the passage; not independently verified |
| Q10 | 국세상담센터의 상담전화는 무엇인가? | correct: 126 | not independently verified | every condition of the question holds in the passage; not independently verified |
| Q11 | 종합소득세일반신고의 신고기간은 무엇인가? | correct: 다음해5월1일~5월31일 | not independently verified | every condition of the question holds in the passage; not independently verified |
| Q12 | 2025년귀속종합소득세일반신고의 신고기한은 무엇인가? | correct: 2026년6월1일 | not independently verified | every condition of the question holds in the passage; not independently verified |
| Q13 | 성실신고확인서제출자의 신고기한은 무엇인가? | correct: 다음해6월30일 | not independently verified | every condition of the question holds in the passage; not independently verified |
| Q14 | 2026년제1기부가가치세확정신고의 신고기한은 무엇인가? | correct: 2026년7월27일 | not independently verified | every condition of the question holds in the passage; not independently verified |
| Q15 | 면세나 영세율에 해당하지 않는 일반과세자의 부가가치세율은 몇 퍼센트인가요? | held | - | the question was not read with confidence: every reading uses something never seen in trai |
| Q16 | 사업을 시작하고 사업자등록은 언제까지 신청해야 하나요? | correct: 사업개시일부터20일이내 | partial reading | "사업을 시작하고 사업자등록" was taken as "사업자등록"; the words "사업을 시작하고" in front of it were ignored |
| Q17 | 사업자등록을 온라인으로 신청하려면 어디를 이용하면 되나요? | correct: 홈택스 | not independently verified | every condition of the question holds in the passage; not independently verified |
| Q18 | 국세 관련 상담을 받으려면 국번 없이 몇 번으로 전화하나요? | held | - | the question was not read with confidence: the text cannot be cut into known pieces |
| Q19 | 2025년에 발생한 소득에 대한 종합소득세 일반 신고는 2026년 언제까지 해야 하나요? | held | - | the question was not read with confidence: the text cannot be cut into known pieces |
| Q20 | 2026년 제1기 부가가치세 확정신고의 실제 일반 신고기한은 언제인가요? | correct: 2026년7월27일 | partial reading | words in the question were ignored: "실제 일반"; "2026년 제1기 부가가치세 확정신고" was taken as "2026년제1기부가가치세확정신고" (spacing differs) |
| Q21 | 일반과세자가 공급가액 100만원인 과세 거래에 일반세율 10%를 적용하면 부가가치세는 얼마인가요? | held | - | the question was not read with confidence: every reading uses something never seen in trai |
| Q22 | 저는 올해 종합소득세 신고 대상인가요? | held as expected | - | the question was not read with confidence: the text cannot be cut into known pieces |
| Q23 | 상속세의 신고기한은 언제인가요? | held as expected | - | nothing in the passage fits every condition of the question |
| Q24 | 일반과세자의 부가가치세 일반세율은 0%가 맞나요? | correct: 10% (claimed 0%: false) | partial reading | words in the question were ignored: "부가가치세" |
