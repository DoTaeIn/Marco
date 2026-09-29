# Round 7, statements (G7-S): cause table and batches

Branch `understanding-r7-statements`. Goal: `docs/ko/2026-09-29-understanding-r7-goal.md`, part G7-S,
amendments A1 to A4. Dev data only; the frozen sets are never read.

## Before (main da949e9, every effort level the same: no step is gated yet)

`python bench/dialogue_gate.py run --dataset <set> --split <half>`, `KG_ENCODER=문자`.

| Set | Answerable | Record | Why | Gate wrong | Other wrong | Violations |
| --- | --- | --- | --- | --- | --- | --- |
| dev3 check | 98/106 (92.5%) | 79/82 | 6/10 | 0 | 0 | 0 |
| dev4 check | 268/323 (83.0%) | 351/377 | 8/13 | 0 | 3 (2 record, 1 correction) | 0 |
| dev5 check | 220/252 (87.3%) | 307/335 | – | 0 | 0 | 0 |
| dev6 check | 109/234 (46.6%) | 381/434 | 11/28 | 0 | 1 (why, missing citation) | 0 |
| dev6 build | 89/230 (38.7%) | 348/425 | 10/23 | 0 | 3 | 0 |

The dev4 record rows counted wrong are `dev4_ko_c_19` turns 3 and 5 (`misrecorded:재윤=None`); they are on main.

## The 53 unread statements of the dev6 check half, by class

| Class | Hold reason | Count |
| --- | --- | --- |
| S1 English appositive relational holder (`A's friend, B, has N X.`) | `input_understanding_failed` | 5 |
| S2 Korean continuation, giver omitted (`그리고 R에게 X를 N개 주었다.`) | `input_understanding_failed` | 10 |
| S3 Korean transfer refused by a state check | `invalid` | 11 |
| S4 partitive use-up (`A used N of them for P.`, `그중 N개로 P를 만들었다`, `그중 N대를 P에 맡겼어`) | `repair_over_bound` 9, `unknown_word` 8 | 17 |
| S5 particle-verb transfer (`A passed N X on to B.`) | `repair_over_bound` | 1 |
| held behind another unread statement | `unread_event` | 9 |

Of the 9 `unread_event`: 5 are S3 cause B on the receiver side (below), 1 follows an S3 statement
(`dev6_ko_c_20` 5), 3 follow an S1 statement (`dev6_en_c_20` 4, `c_24` 5, `c_31` 3).

## G7-S.0: the cause table for S3

Every one of the 11 is refused by the same constraint, `holder_exists` (`missing_initial_quantity`: the
giver has no count said under the key the transfer names). None is refused for its verb (보냈어, 나눠
줬어요, 빌려주었다, 주었다 all read), for a title keyed two ways, or for the first person as such. The cause is
an **earlier holding recorded under another key**:

| Cause | The earlier holding and its key | Refused statements (dialogue, turn) | Count |
| --- | --- | --- | --- |
| A. thing elided, dative kept in the key | `기 대표님에게는 열 개 있어` -> `기 대표에게` = 10, no thing | ko_c_03 4, ko_c_13 3, ko_c_20 4, ko_c_32 4, ko_c_32 5 | 5 |
| B. a vehicle kept in the key | `경아는 승합차에 형광펜을 23자루 싣고 있어` -> `경아 승합차에 형광펜` = 23 | ko_c_26 5, ko_c_28 3, ko_c_34 4, ko_c_36 3 (giver 내가), ko_c_46 3 | 5 |
| C. 그중 use-up by a holder of two things | `한수가 그중 하나를 바자회 준비에 썼습니다` read as `바자회 한수` (particle moved by repair) | ko_c_10 5 | 1 |

Cause B also holds 5 transfers on the receiver side, as `unread_event` naming the earlier holding
(`_shaken_by_unread`, the other-key part of G6-4 item 1): ko_c_02 4 and 5, ko_c_12 4, ko_c_23 4, ko_c_31 3.
Cause C belongs to S4 and is fixed with it.
