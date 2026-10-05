# `marco.reasoning`

Written 2026-10-01 against commit `e3a6394`; checked against `547f85b`, which
changes nothing under `marco/reasoning/`.

## Purpose

Reason over what the language reader has already recognised, one conversation
at a time. A conversation is an evidence ledger that is replayed rather than
incrementally reapplied ([context.py](../../marco/reasoning/context.py)
docstring); conclusions come from finite Horn-rule joins that can keep their
proofs ([inference.py](../../marco/reasoning/inference.py) docstring); learned
actions run as JSON action programs ([actions.py](../../marco/reasoning/actions.py)
docstring); `state.evaluate` computes over validated state JSON with the
operators a KG declares. Goal S4 ([file moves](../ko/2026-09-24-file-moves-goal.md))
moved five root files here whole (`reasoning_context`, `graph_inference`,
`state_engine`, `action_runtime`, `situation_reasoner`; commit `11a3383`,
[target-map.json](target-map.json)). `identity.py` was added on 2026-09-30
(commit `0f1fd7c`) for the conversation identity graph
([conversation-graph.md](conversation-graph.md)).

## Owns

| Module | Lines | What |
| --- | --- | --- |
| [context.py](../../marco/reasoning/context.py) | 7778 | `ReasoningContext`: the per-conversation ledger; `turn()`, `correct()`, `snapshot()`/`restore()`, `current_state()`, `learned_action_candidates()`, `execution_evidence()`, `conversation_graph()`, `flush_trace()`; the declared hold reasons `GAP_CLASSES`, `GAP_OF`, `gap_class()`; the reading constraints `READING_CONSTRAINTS`, `CONSTRAINT_OF`; `PendingTrace` |
| [inference.py](../../marco/reasoning/inference.py) | 370 | `closure` (range-restricted Horn joins), `closure_with_provenance` (bounded, replayable proof bundles), `current_facts` (latest value of a declared single-valued property), `bind`, `proof`, `leading_word_referent` |
| [state.py](../../marco/reasoning/state.py) | 166 | `evaluate(state, knowledge_path=None, *, model=None)`: transitions and arithmetic over validated state JSON, using the operators a KG's axioms declare (or the model permits); never edits its input |
| [actions.py](../../marco/reasoning/actions.py) | 453 | the action-program contract (`SCHEMA`): `compile_program`, `bind`, `execute` over `emit`/`lookup`/`select`/`compute`/`when`/`call`, `event_record`, `resolve_state_values` |
| [identity.py](../../marco/reasoning/identity.py) | 189 | `ConversationGraph`: one node per holder, thing and place; alias and count edges; question frames over node ids; no language |
| [situation.py](../../marco/reasoning/situation.py) | 13 | the old `situation_reasoner` name: imports `state.evaluate`; `reason()` always returns `unknown` with reason `raw_text_requires_semantic_parse`; no importer ([structure-audit.md](structure-audit.md) plans its deletion in Phase 5) |
| `__init__.py` | 0 | empty |

## Does not own

- **Reading words.** Which words fill a role, particles, numerals and frame
  induction are `marco.language` (`frames`, `numerals`, `hangul`) and the root
  `relational_semantics.RelationalParser`. `actions.py` says so in its
  docstring: the reader picks the words, the program decides the change.
- **Sentences.** Replies come from `marco.language.realize` and `.realizer`.
- **Argument judgement.** `judge` is still in `engine.py` (part E9); its
  planned home `marco/reasoning/judge.py` and `semantics.py` wait for the
  Phase 3 splits, frozen until MARCO 1 ([structure-audit.md](structure-audit.md)
  A6, A8).
- **The ledger file.** `flush_trace()` hands events to a `marco.trace` ledger;
  the ledger's format and checks are [`marco.trace`](marco.trace.md).
- **Sessions, routing, host actions.** Sessions and the router are in
  `engine.py` ([structure-audit.md](structure-audit.md) A3); `marco.runtime`;
  `marco.host`.

## Depends on

- Root modules: `relational_semantics` (`RelationalParser`, `asserted`,
  `substitute`, `declared_plural`), `pack_model` (`development_model`, in
  `state.py`), `encoder` (`strip_fillers`, in `context.py`).
- `marco.language` (`realize`, `frames`, `numerals`, `hangul`, `arithmetic`,
  `realizer`), `marco.learning.concepts` (`ExperienceConceptStore`),
  `marco.trace` (`runtime`, `why.Graph`, `explain`).
- Inside the package: `context` imports `inference`, `state`, `actions`,
  `identity`; `actions` imports `inference`; `situation` imports `state`.
- The standard library; `identity.py` and `inference.py` import nothing else.
  `relational_semantics` imports `inference` inside functions
  (relational_semantics.py:1780, 1818, 2582, 2607, 4316, 4405), so the root module and
  this package import each other.

## Public interface

| Name | Imported by (outside tests) | Test |
| --- | --- | --- |
| `context.ReasoningContext`, `.turn`, `.correct` | `engine.py`, `views/kgpack_ui.py`, `alma/runtime.py`, `marco/trace/drive.py` (wraps `.turn`), `bench/`; `.correct` is called only inside `context.py` | `tests/test_reasoning_context.py`: 13 tests call `.turn`; `test_direct_state_append_and_correction_replay_only_the_affected_suffix` and `test_correction_after_a_settled_learned_prefix_replays_only_the_direct_suffix` call `.correct` |
| `ReasoningContext.snapshot`, `.restore` | called by `alma/runtime.py`, `views/kgpack_ui.py`, `bench/seven_step_dialogue.py` | `tests/test_reasoning_persistence.py::test_invalid_snapshot_does_not_replace_valid_memory` (`.restore`), `tests/test_action_runtime.py::test_actual_learned_effect_keeps_the_same_event_envelope_as_a_hypothesis` |
| `ReasoningContext.current_state`, `.execution_evidence`, `.learned_action_candidates` | called by `views/kgpack_ui.py` | `tests/test_action_runtime.py` (`test_app_plan_uses_a_learned_action_definition_without_reexecuting_an_event`, `test_app_explanation_uses_executed_action_evidence_but_not_a_hypothesis`); no test names `learned_action_candidates` |
| `ReasoningContext.conversation_graph` | called only inside `context.py` | `tests/test_conversation_graph.py` (seven of its nine tests) |
| `ReasoningContext.flush_trace` | `marco/trace/drive.py` (after each recorded turn) | `tests/test_r6_why_fact.py::test_with_the_ledger_on_a_why_about_another_holder_does_not_say_the_last_answers_chain` |
| `context.gap_class` | `marco/trace/from_turn.py` | `tests/test_understanding_r5.py::test_every_hold_reason_this_file_gives_has_a_declared_gap_class` |
| `context.GAP_CLASSES`, `GAP_OF` | tests only | `tests/test_understanding_r5.py::test_every_hold_reason_this_file_gives_has_a_declared_gap_class` |
| `context.READING_CONSTRAINTS`, `CONSTRAINT_OF` | tests only | `tests/test_understanding_r5.py::test_when_no_reading_fits_the_turn_holds_with_each_readings_failure_in_the_declared_order` |
| `context.realize` (the bound `marco.language.realize`, swapped by the harness) | tests only | `tests/language/w1_harness.py` |
| `inference.closure` | `alma/runtime.py`, `marco/learning/rules.py`, `marco/learning/chunking.py`, `relational_semantics.py`, `bench/` | `tests/test_indexed_inference.py`, `tests/test_signed_inference.py::test_denied_intermediate_cannot_support_downstream_conclusion` |
| `inference.current_facts` | `context.py`, `actions.py`, `marco/learning/rules.py`, `relational_semantics.py`, `bench/` | `tests/test_temporal_relations.py::test_state_projection_prevents_stale_facts_entering_closure` |
| `inference.closure_with_provenance` | `context.py` | `tests/test_event_provenance.py` (`test_independent_proof_bundles_survive_one_support_becoming_invalid` and two more) |
| `inference.bind`, `proof`, `leading_word_referent` | `relational_semantics.py` | `tests/test_indexed_inference.py` uses `bind` in its oracle `reference`, which `test_indexed_join_preserves_proofs_with_variable_predicates_repeated_variables_and_cycles` compares `closure` against; `tests/test_relational_transfer.py::test_generic_rule_join_does_not_assume_relation_names` (`proof`); no test names `leading_word_referent` |
| `state.evaluate` | `engine.py`, `views/kgpack_ui.py`, `situation.py`, `bench/` | `tests/test_state_engine.py` (four tests) |
| `state._knowledge` | `context.py` | no test names it |
| `actions.execute` | `context.py` | `tests/test_action_runtime.py::test_structured_lookup_compute_condition_and_call_use_one_bounded_executor` |
| `actions.SCHEMA` | tests only (used inside `actions.py`) | `tests/test_action_runtime.py::test_structured_lookup_compute_condition_and_call_use_one_bounded_executor` |
| `actions.compile_program`, `event_record` | `context.py` | no test names them directly; `tests/test_action_runtime.py::test_natural_definition_compiles_to_a_versioned_role_program` reaches `compile_program` through `ReasoningContext._rule` |
| `identity.ConversationGraph` | `context.py` | `tests/test_conversation_graph.py::test_the_key_of_a_holder_and_thing_is_the_one_the_replay_counts_under` |
