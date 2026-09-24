# Fluency sample 3 — for the owner to judge

Goal W3.6. 40 replies, 20 per language. Per language: 12 drawn at random (seed 20260924) from the replies the realizer composed on `data/benchmarks/dialogues_dev3/` (468 of 468 spoken replies composed), played through `AppState.turn` as `bench/composition_gate.py` plays it; then 8 of the kinds round 3 adds, one each — fewer, a tie, the same number, different numbers, before and after an event or one of a thing (dialogues written for this sample, played through `ReasoningContext.turn`), a vague count and the user as a holder (round-4 meaning blocks as request `docs/requests/W3-1.md` asks for them, the pack as it is). The judgement column is empty on purpose: fluency is judged by a person, not counted.

Regenerate: `KG_ENCODER=문자 python tests/language/w3_fluency.py` (`--dataset data/benchmarks/dialogues_dev4` once that set is on the branch).

| # | language | turn | act | input | composed reply | judgement |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | ko | dev3_en_c_16#6 | answer | Dwight은 지금 몇 개 있어? | 10개입니다. | |
| 2 | ko | dev3_ko_b_07#1 | record | 태호는 가솔린이 12대 있습니다. | 반영했습니다. | |
| 3 | ko | dev3_ko_c_04#5 | answer | 지현에게 거울이 몇 개 남았니? | 4개입니다. | |
| 4 | ko | dev3_ko_c_05#3 | ask | 그 사람은 지금 반지 몇 개 있니? | '그 사람'이 누구를 가리키는지 알지 못합니다. '지민 반지', '재욱 반지' 가운데 누구인가요? | |
| 5 | ko | dev3_ko_c_05#5 | answer | 지민에게 반지가 몇 개 남았니? | 8개입니다. | |
| 6 | ko | dev3_ko_c_08#5 | answer | 동윤이와 태규는 빗자루가 모두 몇 개야? | 태규와 동윤은 합쳐서 빗자루 12개입니다. | |
| 7 | ko | dev3_ko_c_10#4 | hold | 그럼 용주는? | 이 문장이 무엇에 대한 말인지 찾지 못했습니다. 더 쉽게 다시 말씀해 주세요. | |
| 8 | ko | dev3_ko_c_12#4 | correct | 아, 녹 1개가 아니라 9개였어요. | 같은 사건 "지환이 영근한테서 녹 1개를 받았어요."의 수량을 1개에서 9개로 고쳤습니다. 새 사건은 더하지 않았습니다. 이제 영근 녹은 2개, 지환은 16개입니다. | |
| 9 | ko | dev3_ko_c_13#5 | answer | 진욱은 몇 개예요? | 10개입니다. | |
| 10 | ko | dev3_ko_c_16#4 | answer | 원진은 연어가 몇 개 있습니까? | 6개입니다. | |
| 11 | ko | dev3_ko_c_18#3 | hold | 지은은 계피가 몇 개 있습니까? | "지현이 승현에게 계피 세 개를 빌려주고 승현이 지은에게 두 개를 빌려주었습니다."를 아직 읽지 못했습니다. 그래서 지금 값을 정하지 않았습니다. 다른 말로 다시 말해 주세요. | |
| 12 | ko | dev3_ko_c_22#6 | answer | 동윤은 분필을 몇 개 가지고 있니? | 9개입니다. | |
| 13 | ko | fewer | answer | 도하와 세린 중 누가 무화과가 더 적어? | 무화과는 세린이 더 적습니다. | |
| 14 | ko | different | answer | 도하와 세린은 무화과가 같아? | 아니요, 도하와 세린은 무화과 수가 같지 않습니다. 도하 무화과는 6개, 세린은 2개입니다. | |
| 15 | ko | before | answer | 도하가 세린에게 무화과를 주기 전에 세린은 무화과가 몇 개 있었어? | 도하가 세린에게 무화과를 주기 전에는 2개였습니다. | |
| 16 | ko | tie | answer | 도하와 세린 중 누가 무화과가 더 많아? | 도하와 세린은 무화과가 4개로 같습니다. | |
| 17 | ko | same | answer | 도하와 세린은 무화과가 같아? | 네, 도하와 세린은 무화과가 4개로 같습니다. | |
| 18 | ko | after | answer | 도하가 세린에게 무화과를 준 뒤에 도하는 무화과가 몇 개 있었어? | 도하가 세린에게 무화과를 준 뒤에는 4개였습니다. | |
| 19 | ko | vague count (W3-1 meaning) | record | 솔은 배가 좀 있어. | 반영했습니다. 솔은 배가 있지만 몇 개인지 알 수 없습니다. | |
| 20 | ko | the user (W3-1 meaning) | record | 내가 솔에게 살구 2개를 줬어. | 반영했습니다. 이제 살구는 3개 있으시고, 솔은 3개입니다. | |
| 21 | en | dev3_en_b_03#5 | answer | How many squids does Duane have? | 3 squids. | |
| 22 | en | dev3_en_b_14#2 | record | Mikael handed one mutton to Shawn. | Recorded. Now Mikael has 4 muttons and Shawn has 13. | |
| 23 | en | dev3_en_b_17#2 | record | Three shoelaces were given to Wolfgang by Isidore. | Recorded. Now Isidore has 4 shoelaces and Wolfgang has 9. | |
| 24 | en | dev3_en_b_19#1 | record | Marci has 5 vests and 4 vanillas. | Recorded. | |
| 25 | en | dev3_en_b_21#4 | correct | The one Jorge passed was 3, not 2. | I changed the amount in the same event "Jorge passed 2 porks to Shuvra." from 2 to 3. No new event was added. Now Jorge has 5 porks and Shuvra has 10. | |
| 26 | en | dev3_en_b_22#2 | record | Jorge lent one net to Shuvra. | Recorded. Now Jorge has 5 nets and Shuvra has 8. | |
| 27 | en | dev3_en_c_05#1 | record | Helge has 10 pianos, and Noemi has 8. | Recorded. Noemi has 8 pianos. | |
| 28 | en | dev3_en_c_10#5 | explain | Why does Andre have that many neckties? | Roxie has 6 neckties, Nicolas has 10 and Andre has 11. The giver loses that many. The receiver gains that many. It rests on "Roxie's got seven neckties, Nicolas's got eleven, and Andre's got nine." and "Roxie gave Nicolas one necktie, and Nicolas gave Andre two.". | |
| 29 | en | dev3_en_c_15#4 | answer | How many dandelions does Craig have? | 9 dandelions. | |
| 30 | en | dev3_en_c_16#2 | hold | How many rusts does Lukas have? | This conversation never mentioned Lukas's rusts. So I did not answer. | |
| 31 | en | dev3_en_c_19#1 | record | Mongo has five masks and Doug eight. | Recorded. | |
| 32 | en | dev3_en_c_20#4 | correct | Actually, Doug gave Piotr fourteen cages, not one. | I changed the amount in the same event "Doug gave one cage to Piotr." from 1 to 14. No new event was added. Now Doug has 1 cage and Piotr has 19. | |
| 33 | en | fewer | answer | Who has fewer figs, Wren or Pell? | Pell has fewer figs. | |
| 34 | en | different | answer | Do Wren and Pell have the same number of figs? | No, Wren and Pell do not have the same number of figs. Wren has 6 figs and Pell has 2. | |
| 35 | en | before | answer | How many figs did Pell have before Wren gave Pell 2 figs? | Before Wren gave Pell figs, Pell had 2 figs. | |
| 36 | en | tie | answer | Who has more figs, Wren or Pell? | Wren and Pell both have 4 figs. | |
| 37 | en | same | answer | Do Wren and Pell have the same number of figs? | Yes, Wren and Pell both have 4 figs. | |
| 38 | en | one of a thing | answer | How many ladles does Wren have? | 1 ladle. | |
| 39 | en | vague count (W3-1 meaning) | record | Sol has some pears. | Recorded. Sol has some pears, but I do not know how many. | |
| 40 | en | the user (W3-1 meaning) | answer | Who has more plums, me or Sol? | You have more plums. | |
