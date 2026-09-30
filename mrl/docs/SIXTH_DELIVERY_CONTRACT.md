# Sixth delivery contract - source search and bounded Horn queries

All work stays under mrl/ in the attached isolated worktree. Active Marco, engine sources,
oracle, frozen fixtures and historical reports are read-only. GPT-5.6 Terra owns frontend,
search backend/runtime and Horn bridge separately; coordinator owns integration checks/docs.
No shared-file edits until ownership is explicitly handed off. Preserve all prior 68 tests.

## Search source and IR v4

Primitive-only source keeps IR v2; existing graph programs keep v3. New features select v4.
V4 root has exactly version/structs/relations/graphs/functions, as v3. In v4 every graph row adds
edge_type (flat struct declaration name or null), every graph_add_edge adds payload (expr or null),
and every graph_find adds cost (field name or null) and heuristic (function name or null).

A graph may declare edge: Road, where Road is a flat struct. Typed-edge add takes payload fourth,
Evidence fifth if supplied. Graphs without edge payload preserve optional fourth Evidence.
Dijkstra/A* require explicit cost: edge.distance selecting an si32 payload field. No implicit
edge weight. BFS/DFS/auto reject cost; auto selects BFS. A* additionally requires
heuristic: estimate(node, goal), a pure function of two node payload values returning si32.
Purity is transitive: no print, graph mutation/search or Horn calls in the function/callees.
All live, allowed, non-blocked edge costs are checked before weighted traversal. Cost and used heuristic values are nonnegative; invalid values and total-cost si32 overflow produce
checked runtime diagnostics. A* shortest-cost claims require an admissible heuristic.

find admits bfs/dfs/dijkstra/astar; find_all admits the same. Each retains relation filtering,
direction/traversal modes, depth and expansion budgets and generation/ownership validation.
The new graph_find_all expression has graph_find fields plus max_paths, with type result:paths:g.
max_paths is 0..256, default256; depth default64 and expansions default100000, nonnegative int32.
max_paths0 returns BudgetExceeded. Equal valid endpoints yield one empty path if max_paths>0.

Paths are vertex-simple; parallel edges define distinct paths. Candidate order is relation ID,
destination node ID and original edge insertion order. BFS enumerates depth then lexicographic
candidate sequence; DFS is deterministic depth-first. Weighted searches use cost and depth ties
with deterministic candidate order. Depth-limited weighted search must retain alternate states
needed to reach a goal within the depth bound; zero-cost cycles must terminate.

find_all returns Ok(paths) when any path was found, even on later truncation. Paths.len counts
stored paths; Paths.complete reports exhaustive completion; Paths.reason is a stable string:
Complete, PathLimit, DepthLimit or BudgetExceeded. Hitting max_paths reports PathLimit
conservatively without searching beyond the requested cap. Zero results return the existing
NoPath/DepthLimit/BudgetExceeded/InvalidNode error. Depth/budget cannot be silently reported
as complete. Single-path BFS retains its established node-global visited/expansion semantics in both v3 and v4.

Ok paths have type paths:g. Indexing paths[i] returns path:g; index must be si32 and bounds
are checked at runtime. IR exact index shape is {kind:index,type:path:g,value:expr,index:expr}.
len accepts paths; field accepts path.cost (si32), paths.complete (b), paths.reason (s).
Unweighted path.cost equals edge count. Paths are value snapshots on let/assignment/match, backed by per-function-invocation frames freed on return; recursion cannot overwrite another invocation. Temporary frontiers grow on demand and are freed. No general collection/GC implementation is implied.
No new graph-handle/Path/Paths/Evidence function parameter or return types.

## Bounded source Horn vertical slice

Reuse runtime/native_graph.c inference exactly; do not use Path traversal for Proof and do not
precompute inference in Python. New module horn_bridge owns checked source/IR admission,
native wire construction, C embedding and complete native-result JSON rendering.

Source queries use inline, literal-only constructors, not new fact/rule declaration syntax:
closure(Horn(facts=Facts(Fact(...)),rules=Rules(Rule(...))), limit=..., target=Triple(...))
and closure_with_provenance(Horn(...),limit=...,proof_limit=...,search_limit=...).
Triple has subject/predicate/object string fields; Rule has id/body/head and optional version;
Fact has id/subject/predicate/object, optional typed literal Evidence, polarity and modality.
Evidence uses the already validated source/start/end/text form. Exact defaults and record shape
are frozen in SIXTH_HORN_CONTRACT.md by its owner. Query inputs are compile-time literals;
standalone plan variables and dynamic facts/rules are not admitted in this slice.

Neutral horn_query IR contains its checked plan, operation, budgets and optional target;
backend independently validates it. It has distinct horn_result type, with fact_count,
proof_count, complete, reason and searches summary fields. print(result) emits structured JSON
matching the native adapter result, including closure target selected proof and provenance
proof bundles, premise/parent links, bindings and alternate supports. No string flag is used
as a replacement for the internal typed result or proof records.

Each syntactic static query has program-lifetime immutable output storage and runs the C
inference engine on first execution. Repeated evaluation may reuse that exact deterministic
result. Compilation may marshal metadata/bytes but must not execute inference to generate an
answer. No Python runtime is used by the produced executable. This does not introduce dynamic
source Horn updates or general collection/epistemic-state semantics.

## Verification and remaining boundary

Compile real .mrl examples using new search and source Horn operations. Compare path results
against independent small reference cases, including weighted path-vs-hop differences, zeros,
cycles, parallel edges, bounded depth, stale handles and incomplete enumeration. Test debug
find_all for Windows stack safety. Independently reject hostile IR and source schemas.
Compare parsed native Horn JSON structurally to the existing Python oracle on admitted cases,
including duplicate supports, denials, derived bindings/links and explicit budget outcomes.
Keep old tests and goldens unchanged. Measure only equivalent fully consumed results if timing.

General collections/enums/Result, dynamic strings/Evidence/plans, multi-premise Horn joins,
unbounded storage/GC, full epistemic/correction semantics and numeric kernels remain outside
this bounded increment. Report remaining work explicitly, never call all v0.1 complete.
