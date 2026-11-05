# marco.runtime.relation_attempt

## Purpose

Acquire current native carriers for a bounded relation hypothesis attempt in one caller-serialized operation.

## Owns

Standalone acquisition, canonical owner/binding checks, finite detached Context/proposal/query/projection/binding carriers and a current acquisition witness. It calls the existing B0 snapshot, parser, Context and L1 proposal once.

## Does not own

Language meanings, candidate reasoning, learning admission, stores, logging, history replay, mutexes, source authentication or ordinary Session replies. A ready acquisition is not an answer or confirmed word meaning. The caller excludes concurrent state changes.

## Depends on

Existing source_snapshot, learning_dialogue, relation_hypotheses in L1/L5, Context, PackModel, LearningMemory and OverlayStore.

## Public interface

`prepare_relation_attempt(session, query_text, *, unread_text, unread_at)` returns a disposable native parser plus detached bounded carriers when ready, or a local gap with all carriers cleared. Never serialize the parser. Only exact native owners are supported; the operation is standalone and requires Session._active to be None. Current native effects of Context snapshot remain visible.

## Native traced internal caller

The private `_prepare_relation_attempt_owned(..., active=...)` delegates to the same acquisition core inside an already durable native respond Attempt. It checks the actual active dictionary, Attempt, recorder, current Session recorder and Ledger ownership/nonterminal input before and after capture. New trace-provider gates apply only to that internal mode; the public default-None path remains unchanged. Native objects stay ephemeral and never enter JSON or persistent state. The adapter does not emit a conditional reply or admit a lesson. See [native trace owner audit](../archive/README.md "보관 ZIP 내부: docs/ko/2026-10-08-marco2-trace-owner-audit.md").
