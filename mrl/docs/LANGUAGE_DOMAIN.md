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

Rules can be added, replaced, and removed while a plan is live:

```mrl
if (plan.add_rule(Rule(id = rule_id, version = 1,
                       body = All(Triple("?x", "parent", "?y")),
                       head = Triple("?x", "ancestor", "?y")))) { }
plan.replace_rule(rule_id, Rule(id = rule_id, version = 2,
                                body = All(Triple("?x", "parent", "?y")),
                                head = Triple("?x", "relative", "?y")))
plan.remove_rule(rule_id)
```

Rule edits return `false` for duplicate or missing IDs and for unsafe rules. A plan supports at most 128 rules, with up to eight variables and one to eight body triples per rule. Every head variable must appear in the body. Dynamic IDs and terms are strings; versions accept a string or si32. `Rule(...)` is a direct mutation argument, not a first-class stored value. An accepted edit rebuilds the current inference engine, so conclusions that depended on a removed or replaced rule disappear. The rebuild scans the current plan and can cost O(facts × rules); edits are intended for knowledge-base updates rather than high-frequency inner loops. Existing snapshots retain their old rules and proof versions. Runtime rules are stored as internal planned rows in checkpoints and the existing commit journal; they are omitted from query results and logical fact capacity.
