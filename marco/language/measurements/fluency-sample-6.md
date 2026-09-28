# Fluency sample 6 — for the owner to judge

Goal W6.5. 40 replies, 20 per language; 20 of them why answers.

Why answers (10 per language): the check half of goal G6's why-with-a-restated-fact cases (`tests/test_r6_why_fact.py`; names, things and amounts no fix saw), each dialogue played through `ReasoningContext.turn`, its last reply kept: the explained cases, then every counterexample (a number that is not the count, a count before a correction, a pointer to two holders, a thing not settled, nothing answered yet). The explained ones say the holder's count first (W6.3); a number that is not the count is said as the recorded count and denied (request G6-3 item 1); a number no holder was named for asks whose count it is (item 3).

Other replies (10 per language): the check half of `data/benchmarks/dialogues_dev5/` (120 dialogues whose `variation.half` is `check`), played through `AppState.turn` as `bench/composition_gate.py` plays it; composed 876 of 876 spoken replies (held 0, passed through 0). First every reply a round-6 plan said (marked *round 6*), at most 5; then one reply of each act not yet in the sample; then replies drawn at random (seed 20260928).

Every reply here was composed by the realizer. The judgement column is empty on purpose: fluency is judged by a person, not counted.

Regenerate: `KG_ENCODER=문자 python tests/language/w6_fluency.py`.

| # | language | source | act | round 6 | input | composed reply | judgement |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | ko | why: holder and number | explain | round 6 | 왜 도하가 11개야? | 도하 단추는 11개입니다. 주는 쪽에서 그만큼 뺍니다. 받는 쪽에 그만큼 더합니다. 근거는 "세리는 단추가 스무 개 있어요.", "도하는 단추가 세 개 있어요.", "세리가 도하한테 단추 여덟 개를 빌려줬어요."입니다. | |
| 2 | ko | why: number only | explain | round 6 | 왜 11개예요? | 도하 단추는 11개입니다. 주는 쪽에서 그만큼 뺍니다. 받는 쪽에 그만큼 더합니다. 근거는 "세리는 단추가 스무 개 있어요.", "도하는 단추가 세 개 있어요.", "세리가 도하한테 단추 여덟 개를 빌려줬어요."입니다. | |
| 3 | ko | why: the reason noun | explain | round 6 | 도하의 단추가 11개가 된 까닭은 무엇인가? | 도하 단추는 11개입니다. 주는 쪽에서 그만큼 뺍니다. 받는 쪽에 그만큼 더합니다. 근거는 "세리는 단추가 스무 개 있어요.", "도하는 단추가 세 개 있어요.", "세리가 도하한테 단추 여덟 개를 빌려줬어요."입니다. | |
| 4 | ko | why: formal, why inside | explain | round 6 | 도하 단추가 왜 11개가 되었습니까? | 도하 단추는 11개입니다. 주는 쪽에서 그만큼 뺍니다. 받는 쪽에 그만큼 더합니다. 근거는 "세리는 단추가 스무 개 있어요.", "도하는 단추가 세 개 있어요.", "세리가 도하한테 단추 여덟 개를 빌려줬어요."입니다. | |
| 5 | ko | why: the other holder | explain | round 6 | 왜 세리는 12개예요? | 세리 단추는 12개입니다. 주는 쪽에서 그만큼 뺍니다. 받는 쪽에 그만큼 더합니다. 근거는 "세리는 단추가 스무 개 있어요.", "도하는 단추가 세 개 있어요.", "세리가 도하한테 단추 여덟 개를 빌려줬어요."입니다. | |
| 6 | ko | why: wrong number | hold | round 6 | 왜 도하가 14개야? | 도하 단추는 11개입니다. 도하는 단추가 14개 있지 않습니다. | |
| 7 | ko | why: the count before the correction | hold | round 6 | 왜 도하가 11개야? | 도하 단추는 13개입니다. 도하는 단추가 11개 있지 않습니다. | |
| 8 | ko | why: a pointer to two holders | ask |  | 왜 그 사람이 11개야? | '그 사람'이 누구를 가리키는지 알지 못합니다. '세리 단추', '세리', '도하 단추', '도하' 가운데 누구인가요? | |
| 9 | ko | why: the thing not settled | ask |  | 왜 세리가 3개야? | '세리'가 누구를 가리키는지 알지 못합니다. '세리 단추', '세리 우표' 가운데 누구인가요? | |
| 10 | ko | why: nothing answered yet | hold |  | 왜 11개예요? | 이 대화에는 설명할 앞선 답이나 정정이 없습니다. | |
| 11 | ko | dev5_ko_c_13#5 | hold |  | 소희 씨가 회의실에 떡 네 개를 두고 왔어요. | 새 말이 이미 반영한 상태와 맞지 않습니다. 확인해 주세요. | |
| 12 | ko | dev5_ko_c_13#7 | hold | round 6 | 소희 씨가 회의실에서 떡 한 개를 가져갔어요. | 반영했습니다. "소희 씨가 회의실에 떡 네 개를 두고 왔어요."를 아직 읽지 못했습니다. 그래서 지금 값을 정하지 않았습니다. 다른 말로 다시 말해 주세요. | |
| 13 | ko | dev5_ko_c_14#2 | record |  | 제 아들은 지도가 열다섯 장 있습니다. | 반영했습니다. | |
| 14 | ko | dev5_ko_c_21#7 | hold | round 6 | 제 누나가 서점에 카드 세장을 두고 왔어요. | 반영했습니다. "카드 한 장이 방송실에서 서점으로 옮겨졌어요."를 아직 읽지 못했습니다. 그래서 지금 값을 정하지 않았습니다. 다른 말로 다시 말해 주세요. | |
| 15 | ko | dev5_ko_c_24#6 | correct |  | 아, 한 장이 아니라 다섯 장였어요. | 같은 사건 "카드 한 장을 제 며느리가 은비 씨한테 넘겼어요."의 수량을 1개에서 5개로 고쳤습니다. 새 사건은 더하지 않았습니다. 이제 며느리 카드는 5개, 은비는 14개입니다. | |
| 16 | ko | dev5_ko_c_25_v1#2 | record |  | 저는 행주가 하나도 없어요. | 반영했습니다. | |
| 17 | ko | dev5_ko_c_29#7 | answer |  | 지금 복도에 조끼가 몇 개 있어요? | 3개 있습니다. | |
| 18 | ko | dev5_ko_c_35#7 | answer |  | 지현이 지금 키위가 몇 개 있습니까? | 12개입니다. | |
| 19 | ko | dev5_ko_c_36#4 | answer |  | 지은이는 아직 모자가 몇 개 있어요? | 7개입니다. | |
| 20 | ko | dev5_ko_c_38#4 | answer |  | 민주한테 주스가 지금 몇 병 있어요? | 2개입니다. | |
| 21 | en | why: holder and number | explain | round 6 | Why does Milo have 11? | Milo has 11 buttons. The giver loses that many. The receiver gains that many. It rests on "Greta has 20 buttons.", "Milo has 3 buttons." and "Greta lent Milo 8 buttons.". | |
| 22 | en | why: holder, number, thing | explain | round 6 | Why does Greta have 12 buttons? | Greta has 12 buttons. The giver loses that many. The receiver gains that many. It rests on "Greta has 20 buttons.", "Milo has 3 buttons." and "Greta lent Milo 8 buttons.". | |
| 23 | en | why: end up with | explain | round 6 | Why did Milo end up with 11 buttons? | Milo has 11 buttons. The giver loses that many. The receiver gains that many. It rests on "Greta has 20 buttons.", "Milo has 3 buttons." and "Greta lent Milo 8 buttons.". | |
| 24 | en | why: what is the reason | explain | round 6 | What is the reason Milo has 11? | Milo has 11 buttons. The giver loses that many. The receiver gains that many. It rests on "Greta has 20 buttons.", "Milo has 3 buttons." and "Greta lent Milo 8 buttons.". | |
| 25 | en | why: that number | explain | round 6 | Why is that number 11? | Milo has 11 buttons. The giver loses that many. The receiver gains that many. It rests on "Greta has 20 buttons.", "Milo has 3 buttons." and "Greta lent Milo 8 buttons.". | |
| 26 | en | why: wrong number | hold | round 6 | Why does Milo have 14? | Milo has 11 buttons. Milo does not have 14 buttons. | |
| 27 | en | why: the count before the correction | hold | round 6 | Why does Milo have 11? | Milo has 13 buttons. Milo does not have 11 buttons. | |
| 28 | en | why: a pointer to two holders | ask |  | Why does he have 11? | I do not know who 'he' refers to. Which of 'Milo buttons', 'Milo', 'Greta buttons' and 'Greta' do you mean? | |
| 29 | en | why: the thing not settled | ask |  | Why does Greta have 3? | I do not know who 'Greta' refers to. Which of 'Greta buttons' and 'Greta stamps' do you mean? | |
| 30 | en | why: nothing answered yet | hold |  | Why is that number 11? | There is no earlier answer or correction to explain in this conversation. | |
| 31 | en | dev5_en_c_01#8 | correct |  | Wait, make that 1, not 3. | I changed the amount in the same event "For the trip, Diana transferred three forks to Mr. Perry." from 3 to 1. No new event was added. Now Diana has 16 forks and Mr. Perry has 2. | |
| 32 | en | dev5_en_c_04_v2#7 | answer |  | How many locks has Levi got now? | 14 locks. | |
| 33 | en | dev5_en_c_08#1 | record |  | the gift shop holds 7 cupcakes. | Recorded. | |
| 34 | en | dev5_en_c_13#9 | hold | round 6 | Sorry, it was 1, not 4. | "Sorry, it was 1, not 4." could refer to several events: "Stella is responsible for 4 mirrors." and "After that, Stella passed four mirrors to my godson.". So I did not choose between them. Please say which you mean. | |
| 35 | en | dev5_en_c_14#8 | hold | round 6 | Dennis lost two sheets. | Recorded. I could not read "Dennis took 5 sheets from the nursery." yet. So I did not fix the current value. Please say it another way. | |
| 36 | en | dev5_en_c_28#7 | hold | round 6 | Dennis transferred two calendars to Ms. Powell. | Recorded. I could not read "Ms. Powell passed three calendars to Dennis, apparently." yet. So I did not fix the current value. Please say it another way. | |
| 37 | en | dev5_en_c_30#2 | record |  | There are 11 gloves in the farm stand. | Recorded. | |
| 38 | en | dev5_en_c_33#3 | hold | round 6 | Andrew left 4 combs at the conference room. | Recorded. I could not read "The conference room only has combs, 10 of them." yet. So I did not fix the current value. Please say it another way. | |
| 39 | en | dev5_en_c_33#6 | hold |  | How many combs has Andrew got now? | I could not read "The conference room only has combs, 10 of them." yet. So I did not fix the current value. Please say it another way. | |
| 40 | en | dev5_en_c_40#1 | record |  | Our tutor, Mr. Simpson, has 3 mirrors at the moment. | Recorded. | |
