# W1 — language realizer: record

Goal file: `docs/ko/2026-09-22-realization-next-goal.md` (2026-09-23 note governs).
Scope set by the owner: R0–R8, invariants I1–I3. R9 not in this run.

## R0 — state before any code change (HEAD be25630, 2026-09-23)

Previous goal (repair-and-english, f985857, merged 33b9f79, repairs 4adc504).
Its report is the f985857 message plus the HANDOFF stop-point notes. Re-run here:

| Check | Result |
| --- | --- |
| `bench/seven_step_dialogue.py` | english 7/7, 한국어 7/7 |
| `bench/seven_step_ui.py` | english 10/10, 한국어 10/10 |
| `bench/removal_test.py` | 11/11 |
| `bench/error_injection.py` | caught 6/6 |
| `bench/repair_checks.py` | 7/7 |
| `bench/unseen_phrasing.py` | solved 10/20 (answered 8, correct hold 2, held 10, wrong 0, error 0) |
| `bench/yardstick.py`, English default | 대조 375/400, 안 물음 151/400, 근거까지 201/400, 밖 거절 24/24 |
| `bench/yardstick.py`, `NAI_LANGUAGE=한국어` | same, except 근거까지 199/400 |

Left blocked or open by the previous goal:

- §12 steps 3b, 5, 6 pass, but their sentences are pack templates with slots
  (`context_replies`: 51 keys per pack). Nothing composes them.
- Every dialogue answer is a template: answers from the question example's
  `render` (`["$n", "개입니다."]`), holds and records from `context_replies`.
- `realize()` is a stub (returns `meaning["answer"]`). One call site:
  `reasoning_context.py:2731`. Answers composed by `engine.py` from graph
  routing do not pass through it.
- The turn result carries no act and no meaning for holds, explanations,
  corrections or records: `_missing_premise` returns a string,
  `_answer_other_than` returns `transitions: []`, the explanation result has no
  correction utterance and no rule ids. Answered turns carry the answer fact as
  the last transition (`{"fact": [s, p, v]}`).
- "No Korean in Python" is enforced for 9 dialogue modules only
  (`tests/test_repair_and_english.py:test_no_korean_text_left_on_the_dialogue_path`).
- English event reading (`read_event`) is particle-based; English runs only on
  declared example rules.
- Unseen phrasings 10/20: repairs cover particle placement only.

Test files and language (79 `tests/test_*.py`): 64 carry the
`pytest.mark.language` marker, 3 pass a language explicitly
(`test_language_seam.py`, 2 others), 12 neither (9 ALMA reproductions,
`test_dialogue_gate.py`, `test_goal_approval_once.py`, `test_indexed_inference.py`).
At 6195040 it was 52 of 75 without a selection.

English default on existing graphs: routing is the same (yardstick above).
`engine.answer("고혈압이 뭐야")` holds in both packs here (definitions corpus
absent in this checkout); the hold sentence follows the selected pack.
English questions to Korean graph nodes are R9, not measured.

Machine-dependent tests: `tests/test_response_composer.py`, 2 tests fail on one
clone and pass on another (HANDOFF 2026-09-22). Not run here until the end
(owner rule: only `tests/language`, `tests/test_language_seam.py` until S3 reports).

Realization-path files for R8, fixed now: every `.py` under `marco/language/`.
Today: `marco/language/__init__.py`, `marco/language/realizer/__init__.py`.
Language literals in them today: 0 (Hangul string constants outside docstrings: 0).

## Final state (2026-09-23)

Code at 9c3f673; measurements 91afed1; full suite run at 91afed1. main merged at ee7b921.
Fixed dialogues for all counts: §12 ×2, the 20 phrasings of `unseen-before.json`, 12 own dev
dialogues (`tests/language/w1_dev_dialogues.json`) = 34 dialogues, 109 replies. The frozen set was
never opened. Tests: `tests/language/` (12 files) + `tests/test_language_seam.py`.

| Item | State | Evidence |
| --- | --- | --- |
| R0 | done | this file, section above, committed df89c89 before any code |
| R1 | done | one Meaning Graph → `4개입니다.` / `4 apples.`; trace shows meaning, intent, discourse, expression, grammar and check `parsed` (`test_w1_r1_thin_slice.py`) |
| R2 | done, live | §12 steps 3b, 5, 6 composed in ko and en; engine sentence poisoned; bench checks 7/7 per language; `test_the_live_seam_composes_3b_5_and_6` runs with no harness (`test_w1_r2_section12.py`) |
| R3 | done | swapped giver/receiver → `parse`; changed number → `quantities`+`parse`; dropped negation → `polarity`; 6/6 caught, 6/6 held, 0 emitted (`test_w1_r3_injected_errors.py`) |
| R4 | done | each proposition deleted one at a time takes its clause (≥15 per language); a transfer deleted from the recorded changes leaves no amount; a poisoned engine sentence changes no output (`test_w1_r4_removal.py`) |
| R5 | done, live | referents elided 37/37; stated facts 50: left unsaid 35, said 15 (each read through ellipsis, repair or a resolved referent); repeated roles elided 18/18 (`test_w1_r5_discourse.py`) |
| R6 | done | §12 ×2 reasoned once (`_turn` calls = turns, `answer` count unchanged while realizing); 14/14 graphs said in both languages with the same numbers; names by romanization, items by sense links, unlinked words kept in their script (`test_w1_r6_two_languages.py`) |
| R7 | done | ko casual `이제 민재 사과는 2개야.` → learned from `지호는 구슬 열 개가 있어` → `이제 민재는 사과 두 개가 있어.` → removed → before; en `3 apples` → `three apples`; list, disable, enable, remove, remove by conversation; a meaning-changing learned form is never selected. Shipped behaviour: live learning is **off** unless a language file declares `learning.live: true` (both ship `false`); learned forms serve only their own conversation (`test_w1_r7_learning.py`) |
| R8 | done | files: every `.py` under `marco/language/` (8). Hangul words in string constants 0; declared surface forms or whitespace in constants 0; the test plants literals and sees them (`test_w1_r8_literals.py`) |

### Invariants

- **I1** no finished sentence stored: expressions are ordered parts over roles; forms computed
  (`뒹굴 → 뒹굽니다`, particles by coda through the pack's mates, English agreement and do-support).
- **I2** R8 = 0/0; how a language forms verbs and marks cases is declared (`grammar.strategies`).
- **I3** every realized clause is checked (`test_the_check_is_not_sampled…`); a failing clause is never
  emitted and the turn is held. Parse-back covers 75 of 242 clauses (count, transfer, location); the
  other 167 (holds, citations, rules, requests) are checked by the number, polarity and quotation
  readers only.

### Live counts (34 dialogues)

| | value |
| --- | --- |
| replies composed / passed through / held | 109 / 0 / 0 |
| clauses / parsed back / overt readers only | 242 / 75 / 167 |
| check blocks / wrong assertions / execution errors | 0 / 0 / 0 |
| intents | INFORM 166, ASK 22, REFUSE 17, WARN 10, CORRECT 8, REASSURE 8 |

Structured input (graphs given directly): R1, R3, R4, R6 tests. Natural-language input: the dialogue runs.

### Existing benchmarks, be25630 export vs 9c3f673 (same machine)

All 13 identical in outcome: seven_step_dialogue 7/7+7/7, seven_step_ui 10/10+10/10, removal_test 11/11,
error_injection 6/6, repair_checks 7/7, unseen_phrasing 10/20, answer_quality 21/34 wrong 0,
dialogue_evaluation (resource timings only), event_runtime 12/1/6/0, experience_concept 31/14/0/0,
question_endings, relational_learning, semantic_contrasts. `bench/yardstick.py` identical to R0 with the engine seam in.
One regression found on the way and fixed (4461976): answer_quality 경계-01 was held because the
Korean parser offers the right roles only as its second candidate.

### Cost

Import 0.008 s; first realization with pack load 0.055 s (ko), 0.005 s (en); process RSS 22.8 MB.
realize per turn median 0.17 ms, p95 0.82 ms, max 1.25 ms. Declarations: meaning 11.8 KB, 한국어 17.5 KB,
english 19.7 KB; Python 90 KB.

### Fluency

Not claimed. 25 replies for the owner to judge: `marco/language/measurements/fluency-sample.md`.

### Engine sites changed under the carve-out (separate commits)

- **W1-1** 72160d8 + **W1-1 item 5 / W1-3 part 1** 5330d3f, `reasoning_context.py` (+99/−10 total), lines at HEAD:
  9 `import uuid`; 104 conversation id; 1594 snapshot `conversation`; 1654 restore; 2081 companion
  which/no referent; 2098–2104 companion missing premise; 2107–2109 companion answer meaning;
  2142–2171 `_explain_last`; 2182–2216 `_answer_other_than`; 2270 and 2323 `_correct_by_reference`;
  2341–2349 and 2367 `_missing_premise` → `_premise_missing` (sentence unchanged); 2761–2793 `turn`
  (conversation id, `_speaker` passes the model); 2825 `correct`; 2857 correction_invalid; 2878 over-bound
  hold; 3200 event referent; 3259 unread/contradiction/capacity; 3398 contradiction/invalid;
  3422–3424 answered (`query`, `render`); 3439–3450 record / missing premise / unresolved.
- **W1-2** dd4d94c, `engine.py` (+25/−1): 3430 `_spoken`; 3445 `answer` wraps the unchanged `_answer`;
  3718 `Dialogue.say` wraps `_say`. No plan exists for a graph's own line: lines are unchanged.

### Requests

| File | Status |
| --- | --- |
| `docs/requests/W1-1.md` | implemented here (72160d8, 5330d3f), all items including 5 (counter) and 8 (conversation id) |
| `docs/requests/W1-2.md` | implemented here (dd4d94c); graph lines pass through until a plan for them is declared |
| `docs/requests/W1-3.md` | part 1 implemented (5330d3f: the model is passed; path kept as fallback; packed runtime realizes, checked by hand: `15개입니다.`). **Part 2 open**: carry `부정표지` as a component field (`language_components.load_reasoning_language` / `PackModel.language`); deferred until G1 merges; the loose-file fallback stays |

### Other fixes made on the way

- `realize(..., language=None)` follows `NAI_LANGUAGE` like the engine (0ffb41c; cost 111 suite failures once).
- `tests/test_language_seam.py` holds no engine sentence text: unplanned turns compared with the pre-seam
  replay, composed turns pinned by SHA-256 prefix; fixes `test_f1_3_no_full_sentence_shared_with_head`.
- Holds whose meaning a test pins get their own frame: contradiction `셈이 맞지 않습니다`,
  nothing to point at `찾지 못했습니다`.

### Full suite at 91afed1

`KG_ENCODER=문자 python -m pytest tests -q -n 12 --dist loadfile`: **898 passed, 1 failed, 8 skipped, 208 s.**
The failure is the known macOS RSS assertion in `test_alma_integrated_reproduction.py`.

### Limits

- A realizer hold on an answered turn keeps the engine status `answered` (not requested yet).
- A counter the question declares is read in the pack's own counter by the check; the pack cannot yet
  read `N명이다` as a count.
- English engine holds in the dev dialogues are parsing (G1): `Chloe has 1 apple.` then a transfer;
  `there are 20 books` then `Hugo got 6 books.`
