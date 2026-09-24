# `marco.trace`

Hypomnema, MARCO's provenance ledger: the record of why MARCO said what it
said, kept as an append-only graph of events. Written 2026-09-24 against
commit `5f321a3`, after goal L1 (`docs/ko/2026-09-24-trace-ledger-goal.md`)
built the package. The event table, the ledger rules and every measurement
(cost per turn, replay, the round-3 failure statistics) are in
[trace-ledger.md](trace-ledger.md); this page is the package's contract in the
five template headings. The name is explained in
[the pipelines article](../en/pipelines.md#hypomnema-the-provenance-ledger).

## Purpose

The knowledge graph records what MARCO knows; this package records how it came
to say something. Each dialogue turn becomes a small directed acyclic graph of
events: what the user said, what was stored, which operator ran over which
statements, which state changed from what to what, what was concluded, whether
the checks held, why a turn was held, and what the user was shown. An answer's
why chain is that graph walked backwards to its inputs, so "no confident answer
without evidence" (gate condition 3 of the
[freeze decision](../ko/2026-09-22-freeze-decision.md)) can be checked turn by
turn instead of only in aggregate. A correction is a new event that supersedes
the old one and withdraws what rested on it, never an edit: the ledger's form
of Doxolysis, retraction that propagates ([naming](naming.md) §5).

Recording is off unless a ledger is named (an argument, or `MARCO_TRACE_DIR`).

## Owns

| Module | What |
| --- | --- |
| [`schema.py`](../../marco/trace/schema.py) | the event envelope as a declared field table, the event kinds (category, tag, allowed statuses, required payload keys, the subset emitted today), the epistemic statuses; `validate()` names the offending field |
| [`ledger.py`](../../marco/trace/ledger.py) | `Ledger`: JSONL, one event per line; `evt_` / `trace_` ids; parent, supersession and withdrawal checks on append and on read; `correct()`, `withdraw()`, `state_changed()`; truncated-line recovery |
| [`runtime.py`](../../marco/trace/runtime.py) | the stamp every event carries: build, language pack, pack digest, model digest, encoder, realizer declaration digest, replay status |
| [`from_turn.py`](../../marco/trace/from_turn.py) | `record_turn()`: one turn envelope, as the UI turn handler returns it, to events |
| [`why.py`](../../marco/trace/why.py) | `Graph.chain()`, `Graph.inputs()`, `why()`: from an output back to the inputs it rests on |
| [`pretty.py`](../../marco/trace/pretty.py) | one line per event |
| [`stats.py`](../../marco/trace/stats.py) | failure statistics with the dialogue gate's denominators |
| [`drive.py`](../../marco/trace/drive.py) | plays dialogues through `views.kgpack_ui.AppState.turn` exactly as `bench/dialogue_gate.py` does and records them; refuses the frozen exam sets before reading them |
| [`__main__.py`](../../marco/trace/__main__.py) | `python -m marco.trace record / why / pretty / stats / cost` |

Also the tests in `tests/trace/` (four files), the requests
[L1-1](../requests/L1-1.md) and [L1-2](../requests/L1-2.md), and the
gitignored ledger folder `logs/`.

## Does not own

- **No engine file.** Events are built from what a turn already returns;
  nothing in `engine.py`, `reasoning_context.py`, `views/`, `marco/language/`
  or `bench/` emits them. Emission from inside the engine, at the twenty sites
  request L1-1 lists, is understanding round 5.
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
