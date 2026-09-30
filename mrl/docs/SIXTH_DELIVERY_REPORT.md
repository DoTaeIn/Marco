# Sixth delivery - 2026-09-28

GPT-5.6 Terra workers completed source multiple-path search, DFS/Dijkstra/A* and a bounded
Horn/Proof source connection. The coordinator froze the common contract, integrated examples,
reviewed runtime/IR boundaries, added independent lifetime/depth tests and verified the result.

Work remains entirely under mrl/ in C:/Users/hirob/.codex/worktrees/mrl-runtime/Marco,
branch codex/mrl-runtime-language, baseline d5d91a21397fc5ac0d3ce0923d8756c867c85eca.
The active Marco checkout, tracked engine, oracle, frozen fixtures and historical reports were
preserved. No commit, push, merge or global installation occurred.

## Delivered behavior

- Typed edge payloads provide explicit costs. No default weight was added to graph edges.
  All arguments evaluate before insertion. BFS/DFS, Dijkstra and A* support direction,
  relation metadata/filtering and bounded depth/expansion. Single-path BFS preserves its
  prior node-global visited behavior regardless of IR version.
- Find_all enumerates vertex-simple paths; parallel edges remain distinct. Results carry
  length, completion and reason; callers can index paths and inspect edge count/cost.
  PathLimit, DepthLimit and BudgetExceeded cannot masquerade as exhaustive completion.
- Paths are value snapshots across let, assignment, match, loops and recursion. Per-invocation
  heap frames avoid Windows debug-stack overflow and are freed on return. Only populated
  paths are copied. Temporary frontiers grow on demand and are freed.
- Weighted ties use relation, destination and insertion order rather than storage slots.
  All eligible negative edges are rejected before search, including edges that would not be
  expanded before an early goal. A* priority uses int64; optimality requires an admissible
  pure heuristic. Depth-bounded weighted search retains alternate shallower states.
- Inline literal Horn queries compile into the existing native C inference engine. Closure
  may select a target Proof; provenance prints full supports, bindings, versions and parent
  links. No inference answer is computed by Python during compilation. Each static query
  executes in C on first use and retains its immutable result for program lifetime.
- The bridge independently validates raw IR and emits exact structured adapter/oracle JSON,
  including empty maps, Unicode Evidence and nested escaped proof IDs. A missing closure
  target has a documented source result because the legacy oracle raises KeyError.

The [search example](../examples/search_paths.mrl) shows the difference between fewest hops
and cheapest path, then lists all three alternatives. The [Horn example](../examples/horn_proof.mrl)
derives apple-is-food from a validated apple-is-fruit fact and emits its provenance.
Generated executables run without Python. Source primitive/v3 behavior remains supported;
new features use [IR v4](SIXTH_DELIVERY_CONTRACT.md).

## Verification

Final complete discovery: **91 tests passed, 0 failures,
0 errors, 0 skipped**. Discovery plus execution took
33.154 seconds. See [raw verification and source hashes](SIXTH_DELIVERY_VERIFICATION.json).

The existing golden/oracle and compiler tests passed alongside source-to-C checks for all
search methods. An independent exhaustive small-graph reference covers directed/undirected
forward/reverse/both/block traversal, filtering, zero costs and parallel paths. Source tests
compare all visible path lengths/costs; native tests inspect tie-selected edge identities.

Regression checks also cover path-count/depth/work truncation, a weighted depth-state trap,
result preservation after mutation, recursive and direct-match lifetimes, primitive/v4 BFS
budget equivalence, malformed method IR, negative costs and argument evaluation behavior.
Horn checks compare complete JSON against the Python oracle for duplicate supports, denials,
planned facts, rule versions, bindings, proof links and budgets. Empty and escaped-string cases
have separate regression coverage. Both release and debug search examples were exercised.

Five final release examples were rebuilt and run:

| Example | Output | Executable bytes | Warm C build, one sample |
|---|---|---:|---:|
| primitive | 42 | 188,416 | 307.0 ms |
| control_flow | 10 | 188,416 | 336.0 ms |
| graph_smoke | 1 | 189,952 | 550.7 ms |
| search_paths | BFS 1 hop; cheapest 2 hops/cost 4; 3 alternatives | 195,584 | 611.2 ms |
| horn_proof | complete, 2 facts, 2 proof records, full JSON | 473,088 | 776.0 ms |

These build samples are not cold-build benchmarks. Artifacts remain in ignored mrl/.build/.
Reproduction commands are in the [README](../README.md#run).

## Measured search performance

The benchmark repeats the same three-node/five-edge Dijkstra query 20,000 times,
consumes length and cost into a checked checksum, and alternates native/Python order for
7 batches. Python uses prepared adjacency, heapq and path tuples. Native timing
uses Windows QueryPerformanceCounter around the generated program, including graph setup and
one checksum print amortized over the batch. Process wall time is recorded separately.

| Measurement | Median per query |
|---|---:|
| Native generated program execution | 0.377335 us |
| Python search loop | 0.823720 us |
| Native process wall time, including startup | 4.807825 us |

The search-body comparison is **2.18x** on this one small workload.
With executable startup included, this native batch takes about
5.84 times the Python in-process loop time.
Both numbers matter: these measurements do not establish universal Python superiority or
inferiority, or an end-to-end startup advantage. Compilation is excluded. Horn result caching
is not involved in the search measurement. Peak RAM was not measured.

[Raw samples, environment and source hashes](SIXTH_DELIVERY_SEARCH_BENCHMARK.json) are
reproducible with python -B -m mrl.benchmark_search. The earlier setup/inference measurements
remain historical records tied to their own source hashes.

## Remaining boundary

Graphs remain bounded to 64 live nodes, 256 edges and 256 returned paths. General collections,
enums/Result, dynamic strings/Evidence and plans, multi-premise Horn joins, full epistemic and
correction/supersession semantics, scalable indexed storage, general GC and numeric kernels
remain. Source Horn plans are inline literal queries; the Python PreparedGraph interface
continues to provide dynamic resident updates. Proof JSON is complete, but general source
iteration/access over proof bundles is not yet implemented.

This delivers the previously listed search methods and the first real source Horn/Proof
connection, while leaving these wider language capabilities explicit.
