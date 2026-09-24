# `marco.trace`

The trace ledger: why MARCO said what it said, as an append-only event graph.
Written 2026-09-24 by goal L1 (`docs/ko/2026-09-24-trace-ledger-goal.md`),
implementing the first part of the owner's design note
`docs/ko/2026-09-24-trace-logging-design.md`.

## Purpose

The knowledge graph records what MARCO knows; the trace graph records how it
came to say something (note §3). Each dialogue turn becomes a small DAG of
events: what the user said, what the engine stored, which operator ran over
which statements, which state changed from what to what, what was concluded,
whether the checks held, why a turn was held, and what the user was shown.
An answer's why chain is that graph walked backwards, so "no confident answer
without evidence" (gate condition 3) is checkable per turn.

## Owns

| Module | What |
| --- | --- |
| `schema.py` | the §38 envelope as a declared field table; the §39 kinds (category, pretty tag, allowed statuses, required payload keys, the subset emitted now); the §16 epistemic statuses; `validate()` names the offending field |
| `ledger.py` | `Ledger`: JSONL, one event per line; `evt_`/`trace_` ids; DAG, supersession and withdrawal checks on append and on read; `correct()`, `withdraw()`, `state_changed()`; truncated-line recovery |
| `runtime.py` | the stamp: build, language pack, pack digest, model digest, encoder, realizer declaration digest, replay status |
| `from_turn.py` | `record_turn()`: one turn envelope to events |
| `why.py` | `Graph.chain()`, `Graph.inputs()`, `why()`: from an output back to its inputs |
| `pretty.py` | one line per event (§32) |
| `stats.py` | failure statistics with the dialogue gate's denominators (§23) |
| `drive.py` | plays dialogues through `AppState.turn` exactly as `bench/dialogue_gate.py` does and records them; refuses the frozen exam sets |
| `__main__.py` | `python -m marco.trace record / why / pretty / stats / cost` |

Also `tests/trace/` (four files, 96 tests), `docs/requests/L1-1.md`,
`docs/requests/L1-2.md`, and the `.gitignore` line `logs/`.

## Does not own

No engine file. The events come from what a turn already returns; nothing in
`engine.py`, `reasoning_context.py`, `views/`, `marco/language/` or `bench/`
was edited. Emitting at the engine sites themselves is round 5 (request L1-1).
Saying "why" in words is the realizer's (request L1-2).

## Depends on

Only the standard library, except `drive.py`, which imports the engine
(`views.kgpack_ui`, `reasoning_context`, `marco.language.realizer`,
`bench.dialogue_gate`) lazily, to play dialogues.

## The event

Every event has the §38 fields: `event_id`, `trace_id`, `parent_ids`,
`timestamp`, `kind`, `status`, `epistemic_status`, `subject`, `input_refs`,
`output_refs`, `source`, `operation`, `payload`, `runtime`. Optional:
`schema`, `system`, `subsystem`, `supersedes`, `level`, and, for post-gate
work only, `scope` (§27) and `goal_id` (§30). `runtime` always carries
`build` and `pack`; the first event of a trace adds `pack_digest`,
`model_digest`, `encoder`, `realizer` and `replay_status`.

A trace is one turn (§6). Its events, as `from_turn.py` writes them:

| Kind | When | Parents |
| --- | --- | --- |
| `input_received` | every turn; epistemic status `reported` | none |
| `observation_created` | the engine stored the statement as observation k | the input |
| `rule_applied` | the envelope names a reasoning operator; `input_refs` = the statements it used | the input |
| `routing_selected` | no operator named: the path the turn took, with route candidates when present | the input |
| `state_changed` | a transition the ledger does not hold yet: before, after, cause | the operator, the cause, the subject's previous state |
| `conclusion_withdrawn` | a correction replaced or removed an earlier change (the new one `supersedes` it) | the new event, or the correction |
| `evidence_found` | a cited source, by reference | the operator |
| `conclusion_created` | each answered fact, or the explanation | the operator, the fact's state change and statement |
| `hypothesis_verified`, `hypothesis_rejected`, `contradiction_found` | the verification checks | the conclusions, else the changes, else the operator |
| `hold` | a held turn: reason, where the reason came from, what is missing | the failed check, else the operator |
| `output_created` | what the user was shown: text, realized, status, gate status | the conclusions, the hold, or the recorded changes |
| `error` | an execution error, or a ledger's truncated-line declaration | the input |

The envelope replays the conversation's whole state on every turn; a
transition already in the ledger is referenced, not written again. A
correction turn's replay differs from the old one: each changed transition is
a new `state_changed` that supersedes the old, the old one gets a
`conclusion_withdrawn`, and the corrected statement's reading is a
`state_changed` on `observation:<k>` that rests on the original statement and
the correction. The why chain follows `parent_ids` only; `input_refs` (what an
operator read) is available with `--refs`.

Output statuses: `answered`, `recorded`, `hold`, `refused` (only when the
meaning's act is `refuse`), `dialogue`, `error`, `unknown`. The gate status is
`bench.dialogue_gate.status` on the same envelope; a test checks the verdict
tables and the status against the gate's own code.

## Ledger rules (L1.2)

* One file per ledger, one event per line, in the directory the caller names;
  default `logs/` at the repository root (gitignored), `MARCO_TRACE_DIR`
  overrides, file name `<date>.jsonl` unless named.
* Ids are 26-character ULIDs after `evt_` / `trace_`: never repeated in a
  process, and checked against the file before an append.
* `parent_ids`, `input_refs`, `supersedes`, a withdrawal's target and a state
  change's `cause` must name earlier events of the same ledger, checked on
  append and on read; a forward reference is refused, so no cycle can form.
  An event is superseded at most once and withdrawn at most once.
* A truncated last line is reported by the reader. The next writer ends it and
  appends an `error` event declaring it; any other unreadable line is an error.

## Measurements

### Failure statistics, round-3 dev set (L1.5)

`data/benchmarks/dialogues_dev3/` (seen data, regression only), 88 dialogues,
468 turns (ko 44, en 44), current engine, one run:
`python -m marco.trace record data/benchmarks/dialogues_dev3 --out <dir>` then
`python -m marco.trace stats <ledger>`. Denominators are the gate's: the gate
number is over turns labelled `answerable`; `record` and `hold` are expected
acts; the rest are labels.

| Output by | N | answered | recorded | hold | refused |
| --- | --- | --- | --- | --- | --- |
| answerable | 210 | 198 | 0 | 12 | 0 |
| record | 182 | 0 | 179 | 3 | 0 |
| hold | 14 | 0 | 0 | 8 | 6 |
| ambiguous | 12 | 0 | 0 | 12 | 0 |
| unsupported | 6 | 0 | 0 | 6 | 0 |
| correction | 22 | 0 | 19 | 3 | 0 |
| why | 22 | 18 | 0 | 4 | 0 |
| all | 468 | 216 | 198 | 48 | 6 |

No turn was `dialogue`, `error` or `unknown`.

Held answerable turns (12), by reason: `unread_event` 9, `input_understanding_failed` 3.
Of the 12, **9 wait on an earlier turn the engine did not read**: a held
correction 5, a held statement 3, a declined turn 1. Only 3 fail on their
own words.

All holds (54), by reason: `unread_event` 13, `which_referent` 12,
`input_understanding_failed` 9, `not_stated` 8, `premise_missing` 6,
`unknown_word` 3, `reference_which_event` 2, `reference_value_unclear` 1.
Every reason came from a meaning (54 of 54).

Record rate: 179 of 182 statement turns were followed by `state_changed` (98.4%).
Graph checks over 216 answered turns: an answer whose why chain reaches no
statement and no source 0; an answer resting on an event withdrawn before it 0.

The same run scored by the gate: answerable 197 correct of 210 (93.8%), 12
hold, 0 wrong, 1 unverifiable; the ledger's 198 answered = 197 + 1. Record 179,
hold 3, as above.

### Cost (L1.7)

`python -m marco.trace cost --language en --repeat 7` and `--language ko --repeat 5`:
the seven-step dialogue (10 turns) through the gate's player, one warm-up,
then alternating runs; turn time is the player's own timing around
`AppState.turn`, which with recording on includes `record_turn`.

| Language | ms/turn off | ms/turn on | change | recording itself, ms/turn | bytes/turn | events/turn |
| --- | --- | --- | --- | --- | --- | --- |
| en | 32.02 | 32.30 | +0.9% | 0.20 | 4478 | 5.9 |
| ko | 406.96 | 399.31 | -1.9% (noise) | 0.27 | 4607 | 5.9 |

Measured at `6cbfc0a` on a quiet machine. Again at `88d5224` with other runs
on the machine: en 53.78 off / 53.64 on (-0.3%), recording 0.29 ms/turn; ko
700.92 / 680.82 (-2.9%), recording 0.42 ms/turn; bytes unchanged. The
recording itself stays under 0.6% of a turn in both runs; the wall-time
difference is inside the run-to-run noise.

The budget is 10%. Recording is off unless a ledger is passed or
`MARCO_TRACE_DIR` is set; `drive.record` then runs the gate's player
untouched. Events hold references and digests only: a test checks that no
pack string or graph line of 16 characters or more appears in any event
outside the user's own text and the shown reply, and that no event exceeds
2 KB.

### Suite (L1.8)

`KG_ENCODER=문자 python -m pytest -q` (parallel) at `88d5224`: 1404 passed,
1 failed, 8 skipped (1413 collected, 96 of them in `tests/trace/`). The one
failure is the known macOS RSS assertion
(`tests/test_alma_integrated_reproduction.py`); the two machine-dependent
`test_response_composer` tests passed on this run. No file outside the goal's
ownership changed, so the other 1317 tests are main's own. The 96 trace tests
also pass on a trial merge with `main` at `ead6302` (W3 merged).

### Replay (L1.6)

Recording the seven-step dialogue twice gives identical event sequences once
ids and timestamps are masked, in both languages. Every event is stamped
`replay_status: exact`. A turn is stamped `approximate` when it used web
research, live realizer learning, or a semantic parser backend other than the
structural one; none did here.

## Deferred

* Emission at the engine sites (routing candidates and scores, rejected
  evidence, rule applications with bindings, pointer resolution, the unread
  statements): request **L1-1**, round 5, after G4 and W3 merge.
* "Why" in words from the chain, the meaning's reason in the realizer report,
  a declared realizer version: request **L1-2**, for the realizer's owner.
* SOMA, ALMA affect, mental-state scope, budgets, goals and subgoals (note
  §24–§31): post-gate. The schema has `system`, `subsystem`, `scope` and
  `goal_id`, and declares their kinds without emitting them.
* SQLite indexes (§34), retention (§36): when a ledger outgrows JSONL.

## Public interface

| Name | Proof |
| --- | --- |
| `schema.validate(event)` | `tests/trace/test_trace_schema.py` |
| `Ledger(directory, name)`, `.append`, `.correct`, `.withdraw`, `.state_changed`, `read(path)` | `tests/trace/test_trace_ledger.py` |
| `record_turn(ledger, trace_id, text, envelope, realizer_report, ...)` | `tests/trace/test_trace_turns.py` (seven-step, both languages) |
| `why(source, event_id)`, `Graph(...).chain`, `.withdrawn_in_chain` | `tests/trace/test_trace_turns.py`, `tests/trace/test_trace_stats.py` |
| `pretty.lines(events)` | `tests/trace/test_trace_turns.py` |
| `stats.table(source)`, `stats.format_table` | `tests/trace/test_trace_stats.py` (denominators against `bench.dialogue_gate.score`) |
| `drive.record(dialogues, ledger)`, `drive.cost(language)`, `drive.guard(path)` | `tests/trace/test_trace_turns.py` |
