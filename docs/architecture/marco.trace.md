# `marco.trace`

Hypomnema, MARCO's provenance ledger: the record of why MARCO said what it
said, kept as an append-only graph of events. Written 2026-09-24 against
commit `5f321a3`, after goal L1 (`docs/ko/2026-09-24-trace-ledger-goal.md`)
built the package. The event table, the ledger rules and every measurement
(cost per turn, replay, the round-3 failure statistics) are in
[trace-ledger.md](trace-ledger.md); this page is the package's contract in the
five template headings. The name is explained in
[the pipelines article](../archive/README.md "보관 ZIP 내부: docs/en/pipelines.md").

## Purpose

The knowledge graph records what MARCO knows; this package records how it came
to say something. Each dialogue turn becomes a small directed acyclic graph of
events: what the user said, what was stored, which operator ran over which
statements, which state changed from what to what, what was concluded, whether
the checks held, why a turn was held, and what the user was shown. An answer's
why chain is that graph walked backwards to its inputs, so "no confident answer
without evidence" (gate condition 3 of the
[freeze decision](../archive/README.md "보관 ZIP 내부: docs/ko/2026-09-22-freeze-decision.md")) can be checked turn by
turn instead of only in aggregate. A correction is a new event that supersedes
the old one and withdraws what rested on it, never an edit: the ledger's form
of Doxolysis, retraction that propagates ([naming](naming.md) §5).

Recording is off unless a ledger is named (an argument, or `MARCO_TRACE_DIR`).

Working-tree check, 2026-10-06: `ReasoningContext` can emit pending internal events
when `context.trace` is set. `record_turn(..., pending_flush=...)` writes those
events before the output and connects them and the declared criterion to its
parent chain. The opt-in [DialogueTrace contract](marco.runtime.dialogue_trace.md)
writes the input durably before execution and records failures and interruptions.
The new [MARCO 2 dialogue adapter](marco.runtime.learning_dialogue.md) records its
response, teaching, retraction and research attempts when given an explicit ledger.
The exact per-answer link to matched learned-expression candidates remains incomplete. Learning provenance is
stored separately in `LearningMemory`; an installed memory head does not identify
a used candidate. Missing selected-component or actual-use metadata remains
`provenance_incomplete`. Passing a criterion does not assert absolute world truth.

## Owns

| Module | What |
| --- | --- |
| [`schema.py`](../../marco/trace/schema.py) | the event envelope as a declared field table, the event kinds (category, tag, allowed statuses, required payload keys, the subset emitted today), the epistemic statuses; `validate()` names the offending field |
| [`ledger.py`](../../marco/trace/ledger.py) | `Ledger`: JSONL; parent, supersession and withdrawal checks; complete writes with interruption retry; a failed write or fsync poisons the writer until reopen; truncated-line recovery |
| [`runtime.py`](../../marco/trace/runtime.py) | caller-supplied selected model, encoder and realizer identities, criterion and actual-use metadata; operational build/explicit pack hashing; JSON validation and granular missing fields |
| [`from_turn.py`](../../marco/trace/from_turn.py) | `record_turn()`: a returned turn to events, prewritten-input binding, criterion and pending-event ancestry, reported premises and inferred outputs, honest undelivered-error output |
| [`why.py`](../../marco/trace/why.py) | `Graph.chain()`, `Graph.inputs()`, `why()`: from an output back to the inputs it rests on |
| [`pretty.py`](../../marco/trace/pretty.py) | one line per event |
| [`stats.py`](../../marco/trace/stats.py) | failure statistics with the dialogue gate's denominators |
| [`drive.py`](../../marco/trace/drive.py) | plays dialogues through `views.kgpack_ui.AppState.turn` exactly as `bench/dialogue_gate.py` does and records them; refuses the frozen exam sets before reading them |
| [`__main__.py`](../../marco/trace/__main__.py) | `python -m marco.trace record / why / pretty / stats / cost` |

Also the tests in `tests/trace/` (four files), the requests
[L1-1](../archive/README.md "보관 ZIP 내부: docs/requests/L1-1.md") and [L1-2](../archive/README.md "보관 ZIP 내부: docs/requests/L1-2.md"), and the
gitignored ledger folder `logs/`.

## Does not own

- **No reasoning decisions.** The adapter records returned turn data, and
  `ReasoningContext` can also supply pending internal events when tracing is
  explicitly enabled. Trace recording does not select meanings, derive facts
  or decide whether a conclusion is warranted. The new MARCO 2 session uses
  this contract when enabled; exact matched learning provenance remains incomplete.
- **Saying "why" in words.** Composing an explanation from the why chain is
  Hermeneia's, the language realizer's (request L1-2, taken up by goal W4,
  `docs/ko/2026-09-24-realizer-r4-goal.md`).
- **The frozen exams.** `drive.guard()` refuses `data/benchmarks/dialogues_v1/`
  and `reasoning_v1/`; the owner scores those.
- **Post-gate systems.** SOMA, ALMA affect, mental-state scope, budgets, goals:
  the schema declares their fields and kinds and emits none of them.
- **Storage beyond JSONL.** SQLite indexes and retention wait until a ledger
  outgrows one file.

## Depends on

- The Python standard library, for every module except `drive.py`.
- `drive.py` imports, lazily and only to play dialogues: `views.kgpack_ui`,
  `reasoning_context`, `marco.language.realizer`, `bench.dialogue_gate`,
  `bench.seven_step_dialogue`. Importing `marco.trace` itself loads none of them.

## Public interface

Exported by `marco/trace/__init__.py`: `Ledger`, `LedgerError`, `SchemaError`,
`chain`, `from_env`, `read`, `record_turn`, `validate`, `why`.

| Name | Proof |
| --- | --- |
| `validate(event)`, the declared kinds and statuses | `tests/trace/test_trace_schema.py` (`test_a_valid_event_passes`, `test_the_validator_names_the_offending_field`) |
| `Ledger(directory, name)`, `.append`, `.correct`, `.withdraw`, `.state_changed`, `read(path)`, `from_env()` | `tests/trace/test_trace_ledger.py` (`test_a_parent_must_be_an_earlier_event_of_the_same_ledger`, `test_a_cycle_attempt_is_refused_on_append`, `test_default_directory_is_logs_and_the_environment_overrides`) |
| `record_turn(ledger, trace_id, text, envelope, realizer_report, ...)` | `tests/trace/test_trace_turns.py` (`test_every_event_but_the_input_has_a_parent_and_each_turn_one_output`, `test_a_correction_supersedes_and_withdraws_never_edits`), the seven-step dialogue in both languages |
| `why(source, event_id)`, `chain`, `Graph(...).chain`, `.withdrawn_in_chain` | `tests/trace/test_trace_turns.py` (`test_the_why_chain_reaches_the_inputs_an_output_rests_on`, `test_an_answer_resting_on_a_withdrawn_value_is_caught_and_a_restored_value_is_not`) |
| `pretty.lines(events)` | `tests/trace/test_trace_turns.py::test_pretty_is_one_line_per_event_with_time_tag_subject_summary` |
| `stats.table(source)`, `stats.format_table` | `tests/trace/test_trace_stats.py::test_denominators_match_the_gate_on_the_dev3_labels` |
| `drive.record`, `drive.cost`, `drive.guard` | `tests/trace/test_trace_turns.py` (`test_the_command_line_records_a_text_dialogue_and_reads_it_back`, `test_the_frozen_exam_sets_are_refused_before_they_are_touched`, `test_recording_costs_little_and_copies_no_pack_or_graph_content`) |
| `python -m marco.trace record / why / pretty / stats / cost` | `tests/trace/test_trace_turns.py::test_the_command_line_records_a_text_dialogue_and_reads_it_back` |

The selected runtime stamp comes from the caller. `first_stamp()` preserves
unknown selected components instead of reading host defaults as evidence of
selection; `source_model_digest` describes parser source assets separately from
the selected graph's content fingerprint. Supplied metadata is a caller report,
not independent verification of actual use. `hypothesis_verified` means the
recorded checks passed under the named criterion; outputs retain their reported,
inferred or unknown status and `world_truth_status="unverified"`.

The v2 contract review passed 98 focused development checks (46 new contract,
fault and metadata checks, 49 unchanged ledger/schema checks and three existing
adapter/correction checks). A separate public six-turn ReasoningContext run
wrote 49 events with criterion and pending routing ancestors for every output.
These foundation checks are separate from the subsequently audited MARCO 2
session hook (41 focused checks and 12 separate processes); exact
used-learning collection. The historical whole-dialogue stamp expectations in
the original fixtures are not a claim of validation for the revised contract.
