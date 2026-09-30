# Dynamic Horn domain APIs

A `Horn` value supports bounded, runtime filters and evidence-aware interpretations:

```mrl
rows = plan.select(subject = current_subject, predicate = "known",
                   limit = 32, proof_limit = 8, search_limit = 4096)
meaning = Candidate(id = "draft", meaning = rows)
result = interpret(Candidates(meaning),
                   Constraints(Constraint(required = Triple("a", "known", "b"),
                                         consistent = true)),
                   budget = 4096)
```

`select` accepts dynamic string filters. Its default result, proof, and search limits are 1,000,000, 32, and 16,384. `select` accepts the named limits shown above; each must be positive. `count` and `status(Triple(...))` use the default search budget. `status` has the closed `EpistemicState` values `known`, `unknown`, `ambiguous`, `contradicted`, `withdrawn`, and `incomplete`.

An interpretation selects a candidate only when exactly one meaning satisfies every constraint. Zero matches yields `unknown`, multiple matches yields `ambiguous`, and an inconsistent meaning yields `contradicted`. If a candidate snapshot is incomplete or the work budget runs out, the result is `incomplete`; callers should not treat that result as a selection. The budget charges candidates, constraints, fact rows inspected, and bounded rule matches used to detect a derived positive fact denied by an explicit negative fact.

`proof_count(fact_index)` and the proof metadata accessors inspect alternate rule matches lazily. The snapshot's `proof_limit` caps reported proofs; its `search_limit` caps rows examined when rebuilding the proof matcher. A limit or memory ceiling marks the snapshot incomplete and sets a reason. Proofs record one selected derivation plus bounded alternative one-step rule matches; they do not recursively enumerate every derivation tree.

`withdraw`, `replace`, and `supersede` preserve the removed fact as a tombstone, including its polarity and evidence. Replacement identifiers must be new across the plan's retained history. `history_fact(id)` exposes the withdrawn version, and `superseded_by(id)` returns the replacement ID for a supersede operation. `save` writes a checkpoint; later mutations become durable through `commit`.
