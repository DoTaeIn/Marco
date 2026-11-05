# `marco.runtime.dialogue_trace`

## Purpose

An opt-in L9 orchestration contract for the existing Hypomnema ledger. It records
an input durably before the caller executes a turn, connects pending internal
events and the declared checks to the output, and preserves execution, save and
trace failures without claiming that an undelivered answer reached the user.

## Owns

`Attempt` binds one immutable attempt identity to its input, conversation, turn,
runtime stamp and installed memory head. `DialogueTrace` runs the caller's
operation, records caller-reported persistence outcomes separately from semantic
use, and finalizes the same attempt. It can record an interruption once for an
unfinished durable input; that record says the outcome is unknown and performs
no state restoration.

## Does not own

It selects no graph, encoder, realizer, meaning, fact or learning candidate. It
does not discover selected components from host defaults or infer a used rule
from the installed memory head. It provides no second reasoning engine, ledger,
cross-store transaction or automatic recovery of dialogue state. The
[MARCO 2 session adapter](marco.runtime.learning_dialogue.md) now calls this contract
when an explicit ledger is supplied. Exact declaration/learning-use collection
remains separate work.
Missing metadata stays `provenance_incomplete`; a reported criterion result is
not a declaration of absolute world truth.

## Depends on

The Python standard library and `marco.trace` runtime validation, turn adapter
and ledger. The ledger must have fsync enabled. A partial write or fsync failure
prevents further writes through that writer until it is closed and reopened.
Input-write failure prevents execution. An execution or save exception retains
its identity even when recording its error also fails.

## Public interface

`DialogueTrace(ledger, conversation=..., runtime_stamp=..., provenance=...)`
offers `begin`, `finish`, `run`, `mark_persistence` and `recover_interrupted`.
`run(text, execute, save=..., pending_flush=...)` returns the operation's result
and trace summary. The caller supplies actual-use metadata and pending-event
IDs; metadata must be finite JSON and pending events must descend from the
current input. `TraceWriteError` identifies a failed attempt and write stage.

The public example is `examples/marco2_trace_contract_demo.py`. The contract and
fault boundaries are covered by `tests/test_marco2_dialogue_trace.py`,
`tests/test_public_trace_faults.py`, `tests/test_trace_exception_integrity.py` and
`tests/test_trace_metadata_boundaries.py`. Root review ran those 46 checks plus
52 existing ledger/schema/adapter checks successfully, and separately verified
criterion and routing ancestors on all six outputs of a real public context.
That context example covers the foundation contract. The subsequently audited
M2 session hook records response and memory/research API attempts automatically
when enabled; its 41 focused checks and 12-process demo are recorded in the
[session module document](marco.runtime.learning_dialogue.md).
