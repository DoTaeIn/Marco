# Graph connection proposal

The current C runtime is a reusable, bounded compatibility slice for one-premise Horn closure and provenance. It is not yet an MRL graph feature: the frontend cannot represent string node values, facts, rules, evidence, relation metadata, or a structured result.

The next contract should retain the already-declared `relation` and `graph` forms from the handoff guide exactly. It should not add a second `fact`/`rule` DSL beside them, lower a relation to an enum, or use `find()` for closure. `find()` and `find_all()` remain future `Path` traversal operations. Closure/provenance must produce a separate proof-oriented result, since a `Path` is not a `Proof`.

Before implementation, freeze these minimum decisions:

- Source/value layer: the representation and ownership of node values, triples, rule terms, evidence, relation metadata, and bounded budgets.
- Result layer: distinct closure facts, completion/reason state, and proof bundles with premise fact IDs, rule/version, bindings, alternate supports, and parent proof links.
- IR layer: typed declaration and operation kinds for those values and results, preserving rule and support order. The IR must state the admitted one-premise restriction until multi-premise joins are implemented.
- Runtime boundary: a graph/proof operation may target the existing native closure subset only when its typed IR passes the same admission checks and preserves explicit capacity and budget outcomes.

The required gate is a frozen syntax/IR contract plus structural parity and a measured benefit against the Python oracle on equivalent admitted workloads. Existing standalone C parity and primitive compiler measurements do not establish `.mrl` graph equivalence, graph speed, RAM reduction, or completion of the v0.1 graph surface.
