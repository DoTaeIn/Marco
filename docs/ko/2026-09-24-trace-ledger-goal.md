# Goal L1: trace ledger — MARCO records why, not only what it said

Model: Opus 5.5, effort high. Read `docs/ko/2026-09-22-freeze-decision.md` first,
then the owner's design note `docs/ko/2026-09-24-trace-logging-design.md` (45
sections; §38 minimal schema, §39 event kinds, §16 epistemic statuses, §44
principles). Written 2026-09-24. Own checkout, branch `trace-ledger`. Runs
alongside G4 (understanding round 4, owns the parsing side and the engine files)
and W3 (realizer round 3, owns `marco/language/` and the reply-return sites).
You touch neither.

## Why now

The frozen dialogue score has been 21 of 108 for three rounds. Each round's
diagnosis was a cause table written by hand from turn outputs. The note's §23
says what a structured failure ledger gives instead: cause statistics for free,
and every held answer with its reason and what was missing. Round 5 should start
from such a table. And the note's last sentence, "MARCO should never have to say
I don't know why I thought that", is gate condition 3 stated positively: no
confident answer without evidence. A trace graph makes that checkable per turn.

## Scope of this round: the ledger core, populated from outside the engine

The engine's turn envelope (what `views.kgpack_ui.AppState.turn` returns) already
carries `trace` (mode, winner, verdict, activated, path), `reasoning`
(`operator`, `transitions`), `verification`, a `meaning` block (act, reason,
kind, subjects, value …) on every result, and the realizer's per-reply report
(`marco.language.realizer.last_report()`: acts, text, trace, `realized`). This
round builds the ledger and an adapter that turns each turn envelope into events,
**without editing where the envelope is built**. Emission at the sites themselves
(routing candidates and their scores, rejected evidence, rule applications with
bindings, the pointer resolution) is the second round of this goal, after G4 and
W3 merge: write it as request `docs/requests/L1-1.md`, one line per site with
the file, the function, and the event it should emit.

SOMA, ALMA affect, mental-state scope, budgets, goals and subgoals (note §24–§31)
are post-gate. Only the schema leaves room for them: `system`, `subsystem`,
`scope`, `goal_id` exist and are optional. Nothing of theirs is implemented.

## Definition of done — all eight, measured

L1.1 **Schema.** `marco/trace/schema.py`: the minimal envelope of §38 as a
     declared record; the event kinds of §39 as a declared table, with the
     subset this round emits marked; the epistemic statuses of §16 as a declared
     table; a validator that rejects an unknown kind, status, or missing field
     naming the offending field. Tests.

L1.2 **Append-only ledger.** `marco/trace/ledger.py`: JSONL, one event per line,
     in a directory the caller names (default `logs/`, gitignored;
     `MARCO_TRACE_DIR` overrides); `evt_` / `trace_` ids unique within a process
     and across appends to the same file; every `parent_ids` entry is an earlier
     event of the same ledger, checked on append and on read (a DAG, never a
     cycle); a correction is a new event that names what it `supersedes`, plus a
     `conclusion_withdrawn` event for the old one, never an edit (§21); a state
     change carries `before`, `after`, `cause` (§20); the reader tolerates a
     truncated last line and reports it. Tests, including the truncated line
     and a cycle attempt.

L1.3 **Adapter from the turn envelope.** `marco/trace/from_turn.py`:
     `record_turn(ledger, trace_id, text, envelope, realizer_report)` writes,
     per turn: `input_received` (epistemic status `reported`: the user said it,
     it is not a verified fact); the operator as `rule_applied` or
     `routing_selected` with `input_refs` to the events of the statements it
     used, as far as `reasoning.transitions` and `evidence` name them; each
     transition as `state_changed` with before/after/cause; `verification` as
     `hypothesis_verified` or `contradiction_found`; a hold as a `hold` event
     whose payload carries `meaning.reason` and, when the envelope says, what is
     missing; `output_created` whose `parent_ids` are the conclusion or the hold,
     payload `text` and `realized` from the realizer report. Every event except
     `input_received` has at least one parent (principle 4). A test drives the
     fixed seven-step dialogue in both languages (`bench/seven_step_dialogue.py`
     shows how to build the pack and call `AppState.turn`) and asserts that for
     every event, and one `output_created` per turn.

L1.4 **Why chain and pretty projection.** `marco/trace/why.py`: from an
     `output_created` id back to the `input_received` events it rests on, as an
     ordered list without duplicates. `marco/trace/pretty.py`: the §32
     one-line-per-event projection (time, kind tag, subject, short summary).
     No sentence is composed here: a spoken "why" is the realizer's job and W3
     owns it; write what the realizer would need from the chain as
     `docs/requests/L1-2.md`. CLI `python -m marco.trace record <dialogue-file>
     --language ko|en --out <dir>`, `why <ledger> <event_id>`, `pretty <ledger>`,
     `stats <ledger>`.

L1.5 **Failure statistics (§23).** `marco/trace/stats.py`: over a ledger, the
     count of `output_created` by status (answered / hold / refused / dialogue),
     holds by `reason`, and for statement turns whether a `state_changed`
     followed (the record rate). Same denominators as `bench/dialogue_gate.py`
     uses; read them from its code, do not invent new ones. Run it on the
     round-3 dev set (`data/benchmarks/dialogues_dev3/`, seen data, regression
     only) with the current engine and put the table in the report. Never on
     `data/benchmarks/dialogues_v1/` or `reasoning_v1/`.

L1.6 **Runtime stamp and replay check (§19, §37).** Every event's `runtime`
     carries the git build hash and the language pack name; the first event of
     a trace also carries the pack digest the dialogue gate computes (read
     `bench/dialogue_gate.py` for how), the encoder mode, and the realizer
     pack version. A test records the seven-step dialogue twice into two
     ledgers and asserts identical event sequences once ids and timestamps are
     masked. If a component is not deterministic, the event says
     `replay_status = approximate` and the report says which component.

L1.7 **Cost.** Recording is off unless a ledger is passed or `MARCO_TRACE_DIR`
     is set. With recording on, the seven-step dialogue's wall time rises at
     most 10%; report ms per turn on and off, and bytes per turn. No graph,
     pack, or corpus content is copied into an event: references and digests
     only (§18).

L1.8 **Nothing regresses, hand-off.** Full parallel suite at main's count with
     the same known failures; `docs/architecture/trace-ledger.md` (what exists,
     what is deferred, the two requests, the stats and cost tables); the commit
     hash. Do not push.

## Owns

`marco/trace/` (new package, stdlib only), `tests/trace/`,
`docs/architecture/trace-ledger.md`, `docs/requests/L1-*.md`, one `.gitignore`
line for `logs/`.

Must not touch: `engine.py`, `reasoning_context.py`, `state_engine.py`,
`frame_induction.py`, `language_components.py`, `relational_semantics.py`,
`explain.py`, `pack_model.py`, `styles/`, `views/`, `marco/language/`, `bench/`,
`mco/`, `alma_*`, any frozen area, any frozen benchmark. If the envelope lacks
something the adapter needs, the adapter records what is there and request
L1-1 names the gap.

## Working conditions

Commit by name, owner as author, no co-author lines, no assistant or model
name in commits or product files. `python`, not `python3`; `KG_ENCODER=문자` on
every run. Report tersely: L1.1–L1.8 with numbers, the stats table, the cost
table, and the commit hash.
