# Fifth delivery: first source-level graph slice

User: start the remaining work with GPT-5.6 Terra. Reuse isolated worktree only;
all edits stay under mrl/. Existing Marco engine/oracle/frozen fixtures/history are read-only.
This increment connects the guide's Appendix B source graph smoke test to real native execution.
It also addresses cached specialized-graph setup cost. It does not declare all v0.1 implemented.

Ownership: frontend.py + tests/test_graph_frontend.py (frontend Terra);
c_backend.py + runtime/graph_runtime.h + tests/test_graph_backend.py (backend Terra);
graph_plan.py + tests/test_plan_cache.py + benchmark_setup.py + FIFTH_DELIVERY_SETUP.md (setup Terra).
Root owns examples, integration tests, contract/report and integration fixes after coordination.
Never edit another lane's file concurrently. No commits/push/install or active checkout writes.

## Source surface

Preserve primitive syntax and paired # comments. Support immutable UTF-8 string literals (s),
struct declarations with fields of si/si32, b, s; named constructors; struct field access;
relation declarations and graph declarations exactly as in the supplied guide.
Graph fields: node: StructName, relation: RelationName, optional directed: true/false (default true).
Relation member metadata is mandatory: polarity positive/negative/neutral, evidence none/optional/required,
traverse forward/reverse/both/block. Metadata remains a distinct declaration, not enum lowering.
All declaration names share a checked namespace. Structs cannot recursively contain structs in this slice.
Named constructor arguments evaluate left-to-right in written order, even when field names are reordered.
Node payload structs are copied values; their string fields point to immutable program-lifetime strings.
String literals with embedded NUL or Unicode surrogates are explicitly unsupported and rejected by both frontend/backend.
Builtin names print and Evidence cannot be redeclared. String equality must use value semantics or be rejected, never pointer equality.
No implicit graph weight. No heap/GC claim: bounded static graph state is deliberate for this slice.

Edge relation arguments are direct Relation.Member literals in this slice; typed aliases are rejected explicitly.
Graph methods: g.add(StructName(field = value, ...)) -> graph-specific node handle;
g.add(from, to, Relation.Member) -> no value; optional fourth Evidence(...) argument;
g.remove(node) -> no value, invalidates incident edges and increments node generation.
Graph handles from different graphs are incompatible even if node payload types match.
add/remove invalid handles or capacity exhaustion are checked runtime diagnostics (nonzero exit).
Find invalid/stale handles return Err(InvalidNode), not a runtime exception.

Evidence is a reserved built-in typed value with named fields source:s,start:si,end:si,text:s.
This first slice requires literal fields. start/end are Unicode scalar offsets in source;
0 <= start <= end <= scalar length, source[start:end] == text. Surrogates are rejected.
Frontend AND IR backend validate the span. Evidence metadata is retained in C edge storage.
Required-evidence relations reject omission at compile time; none-evidence relations reject evidence.
Dynamic evidence values are explicitly unsupported rather than silently trusted.

result = g.find(from, to) { relation in [Relation.A, Relation.B] depth <= 8 method: bfs }
Options are optional: all graph relations, max_depth64, max_expansions100000, method bfs/auto.
Also accept max_depth: N and max_expansions: N with nonnegative int32 literals; reject duplicate options.
Only bfs/auto admitted now. Unsupported find_all/dfs/dijkstra/astar produce located diagnostics.
Auto selects BFS. Directed is default; undirected permits both directions unless traverse:block.
In directed graphs, relation traversal forward/reverse/both controls usable orientation; block is excluded.
Relation polarity is preserved metadata, not an inference operation or a fake Proof.

Find returns distinct Result<Path<graph>,SearchError>. match (result) { Ok(path) {...} Err(error) {...} }
is exhaustive exactly once each, scopes immutable binders; no implicit successful unwrap.
path.len counts EDGES; equal endpoints succeed with zero. s.len counts Unicode scalar values.
print accepts si32,b,s,path length expression, and a match Err SearchError (stable error names).
fn main() without a return type is accepted for graph programs (prints only explicit print calls).
Primitive fn main()->si continues printing its return result exactly as before.
A graph program may also return si from main; primitive arithmetic/control flow stays checked.

## Neutral IR v3 (exact shape)

Primitive-only programs keep IR v2 unchanged. Programs with extended values/declarations use:
{version:3, structs:[{name,fields:[{name,type}]}],
 relations:[{name,members:[{name,polarity,evidence,traverse}]}],
 graphs:[{name,node_type,relation,directed}], functions:[existing function shapes]}.
Types are strings: si32,b,s, struct:Name, node:graph, relation:Name,
evidence, result:path:graph, path:graph, search_error; None means no value.
All source type names are normalized; node/path/result inferred types need not be source-annotatable yet.
Keep declaration list order; IDs are declaration/member order, never hash iteration order.

Existing literal/name/unary/binary/call nodes unchanged. Additional exact expr shapes:
- {kind:construct,type:struct:Name,fields:[{name,value:expr}, ...]} written argument order (left-to-right); exact unique declared field set
- {kind:field,type:FIELD_TYPE,value:expr,name:FIELD_NAME}
- {kind:relation,type:relation:Name,member:MEMBER_NAME}
- {kind:evidence,type:evidence,source:STRING,start:INT,end:INT,text:STRING} validated raw literal fields
- {kind:graph_add_node,type:node:graph,graph:GRAPH_NAME,value:expr}
- {kind:graph_add_edge,type:None,graph:GRAPH_NAME,source:expr,target:expr,relation:expr,evidence:expr_or_None}
- {kind:graph_remove,type:None,graph:GRAPH_NAME,value:expr}
- {kind:graph_find,type:result:path:graph,graph:GRAPH_NAME,source:expr,target:expr,
   relations:[MEMBER_NAME,...],max_depth:INT,max_expansions:INT,method:bfs}
- {kind:len,type:si32,value:expr} only s/path in this slice
- {kind:print,type:None,value:expr} only si32,b,s,search_error
- {kind:match,value:expr,ok_name:NAME,ok:[statements],err_name:NAME,err:[statements]} is a STATEMENT;
  its value must be result:path:graph, arm types path:graph/search_error. Definite return iff both arms return.
No C identifiers or source snippets in IR. Backend independently validates complete schemas/types,
metadata, safe literal evidence, lexical scopes, graph ownership and budget bounds before emitting C.
Use generated C identifiers for all user declarations/members/fields. No string code injection.
Functions may use primitive/s/struct source parameter/return types; no untyped graph handle coercion.

## Native runtime / search behavior

Declaration limits: 65,536 relations, 65,535 graphs, 256 members per relation; frontend and backend both check them.
Bounded storage: 64 live nodes per graph, 256 edges per graph. Reuse removed slots with generation counters;
old handles never revive, including remove/re-add. Generation overflow is a checked failure.
Store actual node payloads (per-graph typed array okay) and relation/evidence records.
Use simple fixed pooled adjacency or bounded edge lists; mark scan/storage ceilings with ponytail comment.
Do not claim CSR, unbounded graph support, or dynamic lifetime GC in this slice.

BFS deterministic candidate order: relation ID, destination node ID, edge insertion order;
queue order then establishes shortest-depth and lexicographic path order. Path contains node/edge sequence.
Test the goal when a node is dequeued, before charging its expansion. Do not return early on neighbor discovery.
Each dequeued non-goal node consumes one expansion, including nodes at the depth boundary.
Check equal endpoints first; with no expansion budget and distinct valid endpoints return BudgetExceeded.
Depth boundary with any eligible unvisited neighbor records depth truncation; continue other queued nodes.
When queue exhausts: DepthLimit if depth truncation occurred, otherwise NoPath.
If expansion budget is exhausted with work pending: BudgetExceeded. Valid graph nodes required first.
All find failures are typed results printed as NoPath,DepthLimit,BudgetExceeded,InvalidNode.
Keep Path separate from the existing Horn/provenance runtime; do not implement find as closure.
Generated C is self-contained: embed runtime source text in output, no Python runtime invocation.

## Gates and known remainder

Compile/run exact Appendix B smoke source, directed/reverse/both/block/undirected cases,
deterministic ties, no path, depth/expansion boundaries, stale/cross-graph handles, required/invalid evidence,
and hostile IR/source values. Preserve all 50 prior tests, frozen10 native cases and arithmetic errors.
Independent source->IR->C integration tests compare graph results with a tiny explicit Python BFS oracle.
Add runnable .mrl examples. Record actual verification and compile-time invariant catches.

Still later: find_all and weighted/DFS searches, full collection/Result/enum system, dynamic strings/evidence,
CSR+overlay scalability, source-level Horn fact/rule/proof integration and broader Marco-native/numeric kernel.
The current request starts this remaining work; report this increment honestly, not as complete v0.1.
