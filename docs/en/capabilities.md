# Capabilities, each with its proof

> Moved out of the root README on 2026-09-29, unchanged. Numbers and `engine.py` line
> numbers are as measured at `5f321a3` unless a line says otherwise; the root README
> carries the current gate numbers.


A claim is listed only if a test or a self-check asserts it. Pytest nodes are in
`tests/`; "`--check` L*n*" is an assertion at that line of `engine.py` run by
`python engine.py --check` (line numbers at `5f321a3`).

**The state dialogue (MARCO 1)**

| Capability | Proof |
| --- | --- |
| Ownership and transfers recorded, corrected in place, and explained, in Korean and English | `test_repair_and_english.py::test_seven_step_dialogue_runs_in_each_language`, `::test_seven_step_dialogue_runs_through_the_ui_turn_handler` |
| English is the declared default language pack; Korean is a second pack; two packs in one process keep separate declarations | `test_repair_and_english.py::test_english_is_the_one_declared_default`, `::test_two_packs_in_one_process_do_not_share_declarations` |
| Korean number words count in state questions (`서른둘` is 32; `서른두 개` in a question is computed locally) | `test_numeral_semantics.py::test_composed_numerals`, `::test_multiple_groups_native_and_sino_numbers_reach_engine_without_lookup` |
| Every answered turn, and every graph-engine answer, passes through `marco.language.realize` exactly once | `test_language_seam.py::test_every_answered_turn_passes_through_realize_once`; `language/test_w1_engine_seam.py` |
| Hermeneia composes each reply from a language-free meaning through intent, discourse, expression and grammar layers, in both languages: the seven-step dialogue, the twenty recorded phrasings, every comparison and time kind | `language/test_w3_realizer_r3.py::test_the_seven_step_the_twenty_phrasings_and_these_kinds_are_all_composed`, `::test_every_comparison_and_time_kind_is_composed`; `language/test_w1_r6_two_languages.py` |
| Palinorrhesis: a sentence whose parse does not match its meaning is never spoken; injected swapped roles, changed numbers and dropped negation are all caught, and every clause is checked | `language/test_w1_r3_injected_errors.py`, `language/test_w1_r4_removal.py` |
| Holds, clarifications and refusals are composed in both languages; a held answer stays a hold | `language/test_w2_realizer_r2.py::test_every_hold_clarify_and_refusal_plan_is_composed_in_both_languages`; `language/test_w3_realizer_r3.py::test_a_held_answer_is_a_hold_with_the_realizers_reason` |
| "Why" is answered in words, with rule ids kept in the trace; the bare 왜? works like the long form | `language/test_w2_realizer_r2.py::test_why_says_its_rules_in_words_and_keeps_the_ids_in_the_trace`, `::test_the_bare_why_works_like_the_long_form` |
| Known referents and repeated roles are left unsaid | `language/test_w1_r5_discourse.py` |
| No sentence literal lives in realizer code; expression learning is off unless a pack declares it | `language/test_w1_r8_literals.py`, `language/test_w1_r7_learning.py` |
| The composition gate's classifier gives 0 composed to a realizer that passes everything through | `test_composition_gate.py::test_f2_6_a_realizer_that_passes_everything_through_scores_zero_composed` |
| Hypomnema: each turn recorded as an event graph in which every event but the input has a parent; an answer's why chain reaches its inputs; a correction supersedes and withdraws, never edits; recording twice gives the same events | `trace/test_trace_turns.py::test_every_event_but_the_input_has_a_parent_and_each_turn_one_output`, `::test_the_why_chain_reaches_the_inputs_an_output_rests_on`, `::test_a_correction_supersedes_and_withdraws_never_edits`, `::test_recording_twice_gives_the_same_events_once_ids_and_times_are_masked` |
| The trace driver refuses the frozen exam folders before reading them | `trace/test_trace_turns.py::test_the_frozen_exam_sets_are_refused_before_they_are_touched` |
| No third-party package on the default state-dialogue path; `torch` not imported | `test_lightweight_runtime.py::test_the_default_path_pulls_in_no_third_party_package` |

**The graph engine**

| Capability | Proof |
| --- | --- |
| Multi-turn: facts given across turns accumulate to one computed answer | `test_grounded_routing.py::test_dialogue_keeps_a_grounded_session_for_follow_up_values`; `test_mco_package.py::test_multi_turn_run`; `--check` L4524-4530 |
| A formula with a missing operand yields no value; division by zero yields no value | `--check` L4527, L4531-4533 |
| Formulas are parsed by a whitelisted grammar; `__import__(...)` evaluates to nothing | `--check` L4535-4536 |
| A number is carried from the user's words to another node (`{등}`, `{등 <- node}`); no number, no value | `--check` L4499-4518 |
| Out-of-domain questions get `unknown`, never an unconfirmed graph's answer | `test_grounded_routing.py::test_out_of_scope_benchmark_never_uses_an_unconfirmed_graph_prompt` (every question of `data/benchmarks/라우팅_밖.json`); `test_mco_package.py::test_unknown_is_declined_offline`; `test_agi_minimum_knowledge.py::test_out_of_scope_realtime_request_is_not_invented` |
| Verdicts `인정` (accept), `B2` (the null class wins) and `미지` (unknown) | `test_short_evidence_question.py` lines 12 and 18; `test_grounded_routing.py` line 12 |
| Verdicts `A` (ask back), `B1` (evidence given, nothing reaches the claim) and `C` | `--check` L5008, L5571-5578 |
| Trap question: overtaking the runner in 2nd place leaves you 2nd | `test_geometric_matching.py::test_explicit_evidence_precedes_goal_gate_but_generic_question_does_not` |
| At most two graph bodies stay loaded (LRU); the oldest is dropped | `--check` L5459-5465 |
| Short index lines cannot win long questions; short questions are also scored in reverse | `--check` L4626-4651 |
| The encoder is coverage-based: a node name inside a long question still scores high; digits are masked | `python encoder.py --check` (encoder.py:396 onward) |
| The character encoder is the default | `test_encoder_default.py::test_default_encoder_is_the_local_character_runtime` |
| `포함:` merges another graph's concepts, axioms and edges; relation names are translated by role | `test_learning_question_flow.py::test_materializing_graph_also_materializes_its_includes`; `--check` L4867-4875 |
| Learning: an unknown phrase is asked back among the evidence that still reaches an unfilled requirement; "네" stores it as an alias of the existing node, "아니요" as a counter-example; the router index picks up learned aliases | `--check` L4671-4694, L5218-5284, L4564-4583 |
| Requirements are conjunctive: one piece of evidence cannot fill two requirements | `--check` L5067-5085 |
| Korean particle agreement (`은/는`, `이/가`, `을/를`, `으로/로`) | `python -m marco.language.hangul` (marco/language/hangul.py:593-611) |
| The `mco` API: load, run, sessions, `reason`, inspect, compile, benchmark, CLI | every test function of `test_mco_package.py`, listed per claim in [docs/architecture/mco.md](../architecture/mco.md) |

Other tested areas, not part of the MARCO 1 gate: words defined in conversation
(`test_explanation_learning.py`), approved web research answered locally after
restart (`test_learning_question_flow.py`), claims from text and PPTX documents
(`test_document_kg.py`), charts and tables from images (`test_document_visual.py`),
actions defined in plain language (`test_action_runtime.py`, `test_rule_learning.py`),
an approved action runs once (`test_goal_approval_once.py`), learned assets travel
in a `.kgpack` (`test_pack_model.py`).
