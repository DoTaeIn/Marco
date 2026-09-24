"""The trace ledger: why MARCO said what it said, as an append-only event graph.

Design note ``docs/ko/2026-09-24-trace-logging-design.md``; goal L1
(``docs/ko/2026-09-24-trace-ledger-goal.md``); package doc
``docs/architecture/trace-ledger.md``.

    schema     the declared envelope, kinds, statuses, epistemic statuses; validate()
    ledger     Ledger: append-only JSONL, DAG checks, corrections, truncated-line recovery
    runtime    build, pack digest, encoder, realizer version stamps
    from_turn  record_turn(): one turn envelope -> events
    why        the why chain: an output back to the inputs it rests on
    pretty     one line per event
    stats      failure statistics with the dialogue gate's denominators
    drive      play dialogues through the UI turn handler and record them (imports the engine)

``python -m marco.trace record|why|pretty|stats|cost``. Everything except
``drive`` uses the standard library only.
"""
from marco.trace.schema import SchemaError, validate
from marco.trace.ledger import Ledger, LedgerError, from_env, read
from marco.trace.from_turn import record_turn
from marco.trace.why import chain, why

__all__ = ["Ledger", "LedgerError", "SchemaError", "chain", "from_env", "read", "record_turn", "validate", "why"]
