# MRL source frontend

`compile_source` uses one lexer/parser/lowering path. Primitive programs use IR v2, the
previous graph slice v3, search/static Horn v4, and mutable Horn values v5. The backend still checks each IR
independently. Diagnostics are located MrlError (ValueError) messages.

Primitive support: si/si32, b, functions, forward calls, declarations, constants, assignment,
checked + - *, comparisons, if/else/while and half-open for ranges. Bounds evaluate once.
Paired # comments, immutable UTF-8 s literals and scalar-count s.len remain supported;
NUL/surrogates are rejected. Struct fields are primitive/string values. Named arguments
run left-to-right in written order. Main returns si32 or is void in extended programs.

## Source graph/search

Graph/relation syntax and generation-specific handles follow the [v3 contract](FIFTH_DELIVERY_CONTRACT.md).
V4 adds `edge: StructName`. Typed edge insertion takes payload fourth and optional Evidence fifth;
untyped edge insertion retains optional fourth Evidence. All arguments evaluate before insertion.

`find` and `find_all` admit bfs/auto/dfs/dijkstra/astar. Auto selects BFS. Weighted methods require
`cost: edge.field` selecting an si32 field. A* also requires `heuristic: estimate(node, goal)`;
the function takes two node payload structs, returns si32, and must be transitively pure.
Local assignments are allowed; printing, graph operations and Horn queries are not.

Find_all adds max_paths (0..256, default256), with existing depth/expansion budgets. Match gates
access to Path or Paths; Paths has len/complete/reason and checked `[index]`, while Path exposes
len/cost. Paths are copied values. Omitted filters mean all members; `relation in []` means none.
See [v4 semantics](SIXTH_DELIVERY_CONTRACT.md) and [example](../examples/search_paths.mrl).

Declaration limits remain 65,536 relations, 65,535 graphs and 256 members per relation.
Path/Paths/graph handles/Evidence/Horn results cannot be function parameter/return annotations.
Primitive, string and flat struct function types remain supported.

## Source inference

Inline `closure(Horn(facts=Facts(...),rules=Rules(...)),...)` and
`closure_with_provenance(...)` are literal-only builtins. These inline calls retain the original v4 literal contract. Horn-only void main is supported, including empty plans.
Evidence is optional; when supplied its literal span must match the source. Query IR retains
operation, checked plan, budgets and optional closure target.

Results expose fact_count/proof_count/complete/reason/searches; print emits complete structured
JSON. Proof selection/bundles are distinct from graph Paths. See [Horn contract](SIXTH_HORN_CONTRACT.md)
and [example](../examples/horn_proof.mrl).

V5 also permits local `ledger = Horn(facts=Facts(...), rules=Rules(...))` with literal
initial facts/rules. Mutable bindings admit `ledger.add(Fact(...))` and
`ledger.remove(id)`; both return b. Fact id/triple terms accept s expressions,
polarity b, modality s, and Evidence remains a validated literal. Duplicate live IDs
or absent removals return false without changing `ledger.version`; successful changes
increase it once. Plans assigned to another binding become independent copies.

`closure(ledger, ...)` and `closure_with_provenance(ledger, ...)` retain literal
budgets/target and return a distinct horn_snapshot with the same result fields plus
version. A saved snapshot preserves its inputs, summary and version after later
mutations. Full JSON keeps the oracle format; version is a separate field access.
These bounded local values cannot be function arguments/returns. See the
[mutable Horn contract](SEVENTH_DELIVERY_CONTRACT.md).
