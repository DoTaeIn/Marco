# Re-verification set of step 4, at the frozen baseline

Step 4 of `docs/ko/2026-09-30-conversation-identity-graph.md`: the numbers and replies the node-based
conversation (steps 1 to 3) must meet or beat. Recorded 2026-09-30 by the statements chat on main `fa16533`,
whose code is the baseline tag `ur7-baseline-90` = `dd016c8` (`git diff --stat dd016c8 fa16533` touches
documents only). Dev data only; the frozen sets are never read.

The reports and the replies are kept beside this file, in `docs/ko/reverification-2026-09-30/`, so a later
run can be compared turn by turn (`bench/dialogue_gate.py score` reads the same fields).

## 1. Dev check halves at effort 3 and effort 0

```
KG_ENCODER=문자 MARCO_EFFORT=<0|3> python bench/dialogue_gate.py run \
    --dataset data/benchmarks/dialogues_<dev3|dev4|dev5|dev6> --split check \
    --report-out docs/ko/reverification-2026-09-30/<set>_check_e<n>.report.json --quiet
```

| Set (dataset sha256) | Effort | Answerable | ko | en | Record | Why | Gate wrong | Violations |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| dev3 check (b5d0c99113fd) | 3 | 98/106 | 47/53 | 51/53 | 79/82 | 6/10 | 0 | 0 |
| dev3 check | 0 | 98/106 | 47/53 | 51/53 | 79/82 | 6/10 | 0 | 0 |
| dev4 check (08fc8e5da525) | 3 | 269/323 | 133/164 | 136/159 | 351/377 | 8/13 | 0 | 0 |
| dev4 check | 0 | 268/323 | 131/164 | 137/159 | 351/377 | 8/13 | 0 | 0 |
| dev5 check (78a930970409) | 3 | 220/252 | 105/122 | 115/130 | 307/335 | – | 0 | 0 |
| dev5 check | 0 | 220/252 | 105/122 | 115/130 | 307/335 | – | 0 | 0 |
| dev6 check (459b3f79febd) | 3 | 188/234 | 86/118 | 102/116 | 411/434 | 16/28 | 0 | 0 |
| dev6 check | 0 | 109/234 | 39/118 | 70/116 | 381/434 | 11/28 | 0 | 0 |

Wrong turns outside the gate label, the same at both efforts, all older than round 7: dev4
`dev4_ko_c_19` turns 3 and 5 (`misrecorded:재윤=None`) and `dev4_ko_c_28` turn 7 (correction, `state:시우=10`);
dev6 `dev6_en_c_17` turn 6 (why, `missing_citation:[3]`). The node-based version may not add one.

## 2. Reading tests of rounds 2 to 7

```
KG_ENCODER=문자 python -m pytest -q -n 6 tests/test_understanding_r2.py tests/test_understanding_r3.py \
    tests/test_understanding_r4.py tests/test_understanding_r5.py tests/test_r6_*.py \
    tests/test_understanding_r7_questions.py tests/test_understanding_r7_statements.py
```

895 passed, 2 xfailed (the context's default effort, 3).

| File | Passed | xfail |
| --- | --- | --- |
| test_understanding_r2.py | 119 | |
| test_understanding_r3.py | 111 | |
| test_understanding_r4.py | 61 | |
| test_understanding_r5.py | 70 | |
| test_r6_parse_speed.py | 6 | |
| test_r6_reading_2.py | 126 | |
| test_r6_reading_forms.py | 112 | |
| test_r6_receiver_count.py | 54 | |
| test_r6_unread_numeral.py | 2 | |
| test_r6_unread_order.py | 2 | |
| test_r6_why_fact.py | 67 | 2 |
| test_understanding_r7_questions.py | 62 | |
| test_understanding_r7_statements.py | 103 | |

Pins that name a count of the packs: `tests/test_pack_model.py:58` and `tests/test_inflection.py:210`, the
Korean relational examples, 117. Pins that name an effort: `test_understanding_r7_statements.py` checks each
round-7 candidate step at the efforts below its level (as on main) and at its level and above;
`test_r6_reading_2.py::test_a_transfer_to_a_holder_counted_under_another_key_is_held` holds at effort 0 and
reads at effort 2. A reply text may be re-pinned only where the text changes and the meaning does not.

## 3. The seven-step dialogue, effort 0 and effort 3

```
KG_ENCODER=문자 MARCO_EFFORT=<0|3> python bench/seven_step_dialogue.py --out docs/ko/reverification-2026-09-30/seven_e<n>.json
```

7/7 in both languages at both efforts; every reply is the same at effort 0 and effort 3 (status and text).

English:

| Said | Status | Reply |
| --- | --- | --- |
| Minsu has five apples, and Jiyeon has two. | observed | Recorded. Jiyeon has 2 apples. |
| Minsu gave Jiyeon two. | observed | Recorded. Minsu gave Jiyeon 2 apples. Now Minsu has 3 apples and Jiyeon has 4. |
| How many does Jiyeon have now? | answered | 4 apples. |
| Where is that person? | unresolved | This conversation never stated the location of Jiyeon. So I did not answer. |
| Actually, the one given was one, not two. | observed | I changed the amount in the same event "Minsu gave Jiyeon two." from 2 to 1. No new event was added. Now Minsu has 4 apples and Jiyeon has 3. |
| Why did that happen? | answered | Now Minsu has 4 apples and Jiyeon has 3. This is because of the correction "Actually, the one given was one, not two.". I changed the amount in the same event "Minsu gave Jiyeon two." from 2 to 1. No new event was added. The giver loses that many. The receiver gains that many. It rests on "Minsu has five apples, and Jiyeon has two.", "Minsu gave Jiyeon 1.", "Minsu gave Jiyeon two." and "Actually, the one given was one, not two.". |
| What about the other person, not that one? | unresolved | I do not know who 'that one' refers to. Which of 'Jiyeon' and 'Minsu' do you mean? |
| 지연은 지금 몇 개야? | answered | 3개입니다. |
| How many apples does Jiyeon have now? (after restart) | answered | 3 apples. |
| 지연은 지금 몇 개야? (after restart) | answered | 3개입니다. |

한국어:

| Said | Status | Reply |
| --- | --- | --- |
| 민수는 사과 다섯 개, 지연은 두 개가 있어. | observed | 반영했습니다. 민수 사과는 5개, 지연은 2개입니다. |
| 민수가 지연에게 두 개 줬어. | observed | 반영했습니다. 민수가 지연에게 사과 2개를 줬습니다. 이제 민수 사과는 3개, 지연은 4개입니다. |
| 지연은 지금 몇 개야? | answered | 4개입니다. |
| 그 사람은 어디 있어? | unresolved | 이 대화에서 지연의 위치는 나온 적이 없습니다. 그래서 답하지 않았습니다. |
| 아까 준 건 두 개가 아니라 한 개야. | observed | 같은 사건 "민수가 지연에게 두 개 줬어."의 수량을 2개에서 1개로 고쳤습니다. 새 사건은 더하지 않았습니다. 이제 민수 사과는 4개, 지연은 3개입니다. |
| 왜 그렇게 됐어? | answered | 이제 민수 사과는 4개, 지연은 3개입니다. 정정 "아까 준 건 두 개가 아니라 한 개야." 때문입니다. 같은 사건 "민수가 지연에게 두 개 줬어."의 수량을 2개에서 1개로 고쳤습니다. 새 사건은 더하지 않았습니다. 주는 쪽에서 그만큼 뺍니다. 받는 쪽에 그만큼 더합니다. 근거는 "민수는 사과 다섯 개, 지연은 두 개가 있어.", "민수가 지연에게 한 개 줬어.", "민수가 지연에게 두 개 줬어.", "아까 준 건 두 개가 아니라 한 개야."입니다. 이 가운데 수정으로 읽은 말: "민수는 사과 다섯 개" → "민수 사과는 다섯 개"; "지연은 두 개가 있어" → "지연은 두 개 있어"; "민수가 지연에게 한 개 줬어" → "민수가 지연에게 한 개를 줬어". |
| 그 사람 말고 다른 사람은? | unresolved | '그 사람'이 누구를 가리키는지 알지 못합니다. '민수', '지연' 가운데 누구인가요? |
| How many apples does Jiyeon have now? | answered | 3 apples. |
| 지연은 지금 몇 개야? (after restart) | answered | 3개입니다. |
| How many apples does Jiyeon have now? (after restart) | answered | 3 apples. |

## 4. Full suite

```
KG_ENCODER=문자 python -m pytest -q -n 8 --dist loadfile -rf \
    --deselect tests/test_dialogue_gate.py --deselect tests/test_reasoning_gate.py
```

2353 passed, 8 skipped, 2 xfailed, 1 failed (`tests/test_alma_integrated_reproduction.py`, the macOS RSS
assertion, machine-dependent), 6 min 38 s. The two gate test files are the plan manager's.

## 5. Composition and reasoning gates

Not run here: both read frozen sets and are owner-run. At the baseline, from the owner's note: composition
340 of 340, reasoning 110 of 113. Frozen exam 90 of 108, 0 wrong, 0 violations.

## 6. Wrong readings on main at the baseline, for the node-based recording's tests

Found while diagnosing, not on the exam's gate turns; each must hold or record right on nodes:

- `가람은 연필 세 개, 컵 두 개를 가지고 있어.` records `컵 연필` = 2: the bare word after the comma is taken as
  a second holder that inherits the thing (coordination ellipsis, `trailing_words`). The right record is
  가람's 연필 3 and 컵 2, or a hold.
- `가윤은 자두가 16개 있어. / 가윤 사위 태오는 자두가 23개 있어. / 가윤 삼촌 민혁은 자두가 7개 있어. / 민혁이 가윤
  사위 태오에게 자두 한 개 줬어.` records the receiver as a new holder `가윤 사위 태오 자두` (count not known), and
  `태오는 자두가 몇 개 있어?` is answered 23; the right answer is 24, or a hold. One node for 태오, whatever words
  name it, is the case of step 1.

## Re-run on the node-based conversation (2026-10-01, main `982343f`)

Step 4 of the identity-graph order, run by the plan manager with the command of section 1. Every set meets or
beats the baseline; no new wrong turn in any label.

| Set | Effort | Answerable | Baseline | Gate wrong | Violations | Wrong turns outside the gate label |
| --- | --- | --- | --- | --- | --- | --- |
| dev3 check | 3 | 98/106 | 98/106 | 0 | 0 | 0 |
| dev3 check | 0 | 98/106 | 98/106 | 0 | 0 | 0 |
| dev4 check | 3 | 269/323 | 269/323 | 0 | 0 | 3, the same three as the baseline |
| dev4 check | 0 | 268/323 | 268/323 | 0 | 0 | 3, the same three |
| dev5 check | 3 | 220/252 | 220/252 | 0 | 0 | 0 |
| dev5 check | 0 | 220/252 | 220/252 | 0 | 0 | 0 |
| dev6 check | 3 | 189/234 | 188/234 | 0 | 0 | 1, the same one as the baseline |
| dev6 check | 0 | 109/234 | 109/234 | 0 | 0 | 1, the same one |

Frozen exam at the same commit, effort 0 to 3: 63, 67, 97, 98 of 108, no wrong turn and no violation at any
level (English 30, 33, 53, 54 of 54; Korean 33, 34, 44, 44 of 54).
