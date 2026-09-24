# Fluency sample 5 — for the owner to judge

Goal W5.4. 40 replies, 20 per language, from the check half of `data/benchmarks/dialogues_dev4/` (95 dialogues whose `variation.half` is `check`; seen data, phrased from structured scenarios), played through `AppState.turn` as `bench/composition_gate.py` plays it. On that half the realizer composed 782 of 782 spoken replies (ko 414 of 414, en 368 of 368; held 0, passed through 0).

Per language: first every reply round 5 changed (marked *round 5*: a corrected receiver named, request G4-1; the Korean user said by the honorific in a total, a comparison or as a recipient, request G4-2; a holder's count said with the existence verb; a vague count in a place), at most 8; then one reply of each act not yet in the sample; then replies drawn at random (seed 20260925) until 20. The judgement column is empty on purpose: fluency is judged by a person, not counted.

Regenerate: `KG_ENCODER=문자 python tests/language/w5_fluency.py`.

| # | language | turn | act | round 5 | input | composed reply | judgement |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | ko | dev4_ko_c_30#7 | answer | round 5 | 두 사람 합쳐서 스티커가 몇 개 있어요? | 재윤과 합쳐서 스티커가 26개 있으십니다. | |
| 2 | ko | dev4_ko_c_33#9 | answer | round 5 | 두 사람 합쳐서 장작이 몇 개 있어요? | 곽과 합쳐서 15개 있으십니다. | |
| 3 | ko | dev4_ko_c_46#2 | record | round 5 | 도서관에는 머핀이 좀 있어요. | 반영했습니다. 도서관에는 머핀이 있지만 몇 개인지 알 수 없습니다. | |
| 4 | ko | dev4_ko_c_46#4 | hold | round 5 | 도서관은 지금 머핀이 몇 개 있어요? | 도서관에는 머핀이 있지만 몇 개인지 알 수 없습니다. | |
| 5 | ko | dev4_ko_c_50#6 | correct | round 5 | 아, 시윤이가 아니라 저한테 줬어요. | 같은 사건 "시윤이 선우씨에게서 스티커 한 장을 받았어요."에서 시윤이 받은 것을 받으신 것으로 고쳤습니다. 새 사건은 더하지 않았습니다. 이제 시윤 스티커는 하나도 없습니다. 스티커는 16개 있으십니다. | |
| 6 | ko | dev4_ko_c_03#7 | answer |  | 최 기사님한테 자두가 지금 몇 개 있어요? | 2개입니다. | |
| 7 | ko | dev4_ko_c_04#4 | answer |  | 성진이는 지금 방석이 몇 개 있어? | 1개입니다. | |
| 8 | ko | dev4_ko_c_05#4 | answer |  | 미경은 지금 명찰이 몇 개 있습니까? | 9개입니다. | |
| 9 | ko | dev4_ko_c_07#2 | record |  | 곽 기사님 짝꿍 우진은 양파가 일곱 개 있어요. | 반영했습니다. | |
| 10 | ko | dev4_ko_c_08#3 | record |  | 그다음에 시현이 태민 씨한테 건전지 한 개를 보냈어요. | 반영했습니다. 이제 시현 건전지는 10개, 태민은 16개입니다. | |
| 11 | ko | dev4_ko_c_13#4 | record |  | 다은이 예원한테서 자두 두 개를 받았어요. | 반영했습니다. 이제 예원 자두는 10개, 다은은 7개입니다. | |
| 12 | ko | dev4_ko_c_21#10 | hold |  | 다은씨가 지금 샌드위치가 얼마나 가지고 있는지 입니까? | 이 문장이 무엇에 대한 말인지 찾지 못했습니다. 더 쉽게 다시 말씀해 주세요. | |
| 13 | ko | dev4_ko_c_24#3 | record |  | 저는 열두 장의 티켓을 가지고 있습니다. | 반영했습니다. | |
| 14 | ko | dev4_ko_c_30#8 | explain |  | 재윤이 지금 스티커가 왜 그만큼 있어요? | 재윤 스티커는 6개, 스티커는 20개 있으십니다. 주는 쪽에서 그만큼 뺍니다. 받는 쪽에 그만큼 더합니다. 근거는 "제 친구 재윤은 스티커 열여섯 장이 있어요.", "제가 스티커 열 장을 들고 있어요.", "재윤이가 저한테 스티커 열 장을 줬어요.", "재윤이가 저한테 스티커 다섯 장을 줬어요.", "아, 다섯 개가 아니라 열 개였어요."입니다. 이 가운데 수정으로 읽은 말: "재윤은 스티커 열여섯 장이 있어요" → "재윤 스티커가 열여섯 장 있어요". | |
| 15 | ko | dev4_ko_c_32#1 | record |  | 하은 님이 젓가락 다섯 벌을 가지고 있어요. | 반영했습니다. | |
| 16 | ko | dev4_ko_c_38#3 | hold |  | 풍선 한 개를 준서가 수진 씨한테 넘겼습니다. | 새 말이 이미 반영한 상태와 맞지 않습니다. 확인해 주세요. | |
| 17 | ko | dev4_ko_c_44#2 | record |  | 현재 헬멧 열세 개가 음악실에 있어요. | 반영했습니다. | |
| 18 | ko | dev4_ko_c_47#7 | ask |  | 걔는 지금 여행가방이 몇 개 있어요? | '걔'가 누구를 가리키는지 알지 못합니다. '하준 여행가방', '예은 여행가방' 가운데 누구인가요? | |
| 19 | ko | dev4_ko_c_48#8 | hold |  | 은서와 제 친구가 합쳐서 봉투가 몇 장 있어요? | "은서가 지안한테 봉투 두 장을 돌려줘요."를 아직 읽지 못했습니다. 그래서 지금 값을 정하지 않았습니다. 다른 말로 다시 말해 주세요. | |
| 20 | ko | dev4_ko_c_50#2 | record |  | 제가 스티커 열다섯 장이 있어요. | 반영했습니다. 스티커는 15개 있으십니다. | |
| 21 | en | dev4_en_c_14#5 | correct | round 5 | Actually they went to Abigail, not to Ryan. | I changed the receiver in the same event "After that, Ryan took 2 of his helmets from the stockroom." from Ryan to Abigail. No new event was added. Now Ryan has 15 helmets and Abigail has 14. | |
| 22 | en | dev4_en_c_30#7 | correct | round 5 | Actually they went to Olivia, not to me. | I changed the receiver in the same event "Delia transferred 3 bagels to me, apparently." from you to Olivia. No new event was added. Now you have 12 bagels and Olivia has 14. | |
| 23 | en | dev4_en_c_31#7 | correct | round 5 | Wait, Noah gave them to Omar, not Ms. Davis. | I changed the receiver in the same event "Noah transferred three rulers to Ms. Davis." from Davis to Omar. No new event was added. Now Davis has 11 rulers and Omar has 19. | |
| 24 | en | dev4_en_c_05#7 | hold |  | Actually, it was 13, not 4. | "Actually, it was 13, not 4." could refer to several events: "my brother is holding 4 wrenches." and "We moved 4 of them from the storage room to the reception desk.". So I did not choose between them. | |
| 25 | en | dev4_en_c_06#8 | hold |  | How many apples do I and Eric have in total? | I could not find what this statement is about. Please say what to use or what you want to know more plainly. | |
| 26 | en | dev4_en_c_07#4 | hold |  | How many suitcases does Petra hold? | I could not read "Petra gave back five suitcases to me." yet. So I did not fix the current value. Please say it another way. | |
| 27 | en | dev4_en_c_08#9 | answer |  | How many rulers do I have now? | 12 rulers. | |
| 28 | en | dev4_en_c_09#4 | answer |  | How many rulers does Eli have now? | 13 rulers. | |
| 29 | en | dev4_en_c_09#6 | record |  | Sara lent Eli one ruler, apparently. | Recorded. Now Sara has 13 rulers and Eli has 14. | |
| 30 | en | dev4_en_c_11#10 | explain |  | Why does Rosa have that many chargers now? | Rosa has 3 chargers and you have 8 chargers. The giver loses that many. The receiver gains that many. It rests on "Rosa hasn't got any chargers.", "I have some chargers, actually. 11 of them.", "Then I passed 4 chargers to Rosa.", "Rosa lent me 1 chargers, apparently.", "Rosa lent me three chargers, apparently." and "Actually, it was 1, not 3.". | |
| 31 | en | dev4_en_c_13#6 | answer |  | How many bowls does my neighbor have left? | 12 bowls. | |
| 32 | en | dev4_en_c_14#2 | record |  | Abigail has 12 helmets and Ryan has 15 helmets. | Recorded. | |
| 33 | en | dev4_en_c_21#8 | answer |  | How many bagels does Ms. Morgan have now? | 2 bagels. | |
| 34 | en | dev4_en_c_25#2 | record |  | Our coach, Mr. Hernandez, has some mats too. | Recorded. Hernandez has some mats, but I do not know how many. | |
| 35 | en | dev4_en_c_26#6 | answer |  | How many scooters does I hold? | 6 scooters. | |
| 36 | en | dev4_en_c_31#9 | answer |  | How many rulers does Noah have left? | 4 rulers. | |
| 37 | en | dev4_en_c_35#3 | record |  | Delia left 4 of hers at the lobby. | Recorded. Delia put 4 bowls in the lobby. Now Delia has 5 bowls and the lobby has 18. | |
| 38 | en | dev4_en_c_41#1 | record |  | my coworker Petra is responsible for 8 bagels. | Recorded. | |
| 39 | en | dev4_en_c_41#8 | answer |  | How many bagels does my partner hold? | 12 bagels. | |
| 40 | en | dev4_en_c_43#10 | hold |  | How many paintbrushes do the basement and the supply closet have in total? | I could not find what this statement is about. Please say what to use or what you want to know more plainly. | |
