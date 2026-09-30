# Fifth delivery - 2026-09-28

Three GPT-5.6 Terra workers implemented the source frontend, C backend/runtime and specialized
plan setup optimization. The coordinator integrated the boundaries, added independent source-to-C
tests, reviewed edge cases and ran final verification. This delivery starts the remaining language
work with a working bounded graph slice; it does not complete v0.1.

Changes are confined to `mrl/` in `C:/Users/hirob/.codex/worktrees/mrl-runtime/Marco`, branch
`codex/mrl-runtime-language`, baseline `d5d91a21397fc5ac0d3ce0923d8756c867c85eca`.
The active Marco checkout, tracked engine files, oracle, frozen fixtures and historical reports
were preserved. No commit, push, merge or global installation was performed.

## Delivered behavior

The guide's Appendix B [graph example](../examples/graph_smoke.mrl) now runs through
`.mrl -> checked IR v3 -> self-contained C11 -> executable` and prints `1`.
It declares a Concept struct, a relation with polarity/evidence/traversal metadata, a graph,
adds two nodes and an edge, runs BFS and handles Ok/Err. Execution does not invoke Python.

The source slice includes immutable UTF-8 strings, Unicode scalar length, flat struct values,
named constructors, node/edge addition, node removal, directed/undirected traversal, relation
filters, depth/expansion limits, literal Evidence spans and typed search errors.
Cross-graph handles fail compilation; stale handles return InvalidNode from find. Node removal
invalidates incident edges. Runtime edge insertion also checks relation declaration ownership.

Constructors evaluate arguments in written order; for bounds are captured once. The backend
checks v3 independently, including both branches of control flow, scopes, exact schemas,
malformed values and Evidence. Primitive-only programs retain IR v2 and existing behavior.
Declaration IDs and capacities are checked before narrowing into native storage.

Path search uses 64 live nodes and 256 edges per graph. Its deterministic BFS stores actual
node/edge paths and retained edge Evidence. Path is separate from Horn Proof inference.
The existing resident single-premise Horn runtime and optional rule specialization remain available.

## Verification

Final full discovery: **68 passed, 0 failed, 0 errors, 0 skipped**. Discovery plus execution
recorded 16.989 seconds (test runner: 16.653 seconds).
[Raw verification and source hashes](FIFTH_DELIVERY_VERIFICATION.json) accompany this report.

Checks cover the prior 50-test behavior, frozen native fixtures, primitive overflow/control flow,
source lowering, independent hostile IR validation, actual compiled C execution and plan caching.
An independent Python BFS reference matches 44 source queries across directed/undirected graphs,
traversal modes, relation filters and depth/expansion boundaries. Native tests inspect path tie
ordering after edge-slot reuse and verify Evidence storage; source tests compare path length/error.
Unicode spans, stale handles, node capacity, declaration capacities, constructor evaluation order
and captured loop bounds are also checked. These tests are bounded evidence, not a proof of full
Marco/Horn source-language equivalence.

The final smoke artifact has 32 source lines, 168 generated C lines and a 189,952-byte executable.
Its single C build took 504.076 ms with a warm local toolchain; this is not a cold-build benchmark.
Exit status is 0, stdout is `1\n`, stderr is empty. Artifacts are in ignored `mrl/.build/`.

Reproduce from the worktree root using the [README commands](../README.md#run-the-source-graph-example).
Run `python -B -m unittest discover -s mrl/tests -v` for the complete suite.

## Setup performance

Repeated specialized construction previously repeated compiler discovery despite cached DLLs.
A bounded process-local cache now keys successful builds by checked emitted plan, native source
bytes and mode. Validation/header emission still run each time; first lookup retains full
persistent toolchain identity checks. Restart Python after compiler/build-tool environment changes.

| Constructor state | Median |
|---|---:|
| Specialized, process plan cache cleared, persistent DLL retained | 27.0829 ms |
| Specialized, process-warm | 0.097782 ms |
| Generic, process-warm | 0.019696 ms |

Seven alternating warm batches of 50 constructions were measured on the recorded Windows/Python
3.10.6/Zig 0.16.0 environment. The same-workload specialized comparison is about 277x for setup.
The [method](FIFTH_DELIVERY_SETUP.md) and [raw samples](FIFTH_DELIVERY_SETUP.json) distinguish
initial, persistent-cache and process-warm states. It does not measure search/inference speed.
No Python speed or RAM advantage is claimed for the new source BFS runtime. Historical fourth
delivery inference timings remain associated with their recorded source hashes.

## Remaining boundary

`find_all`, DFS/Dijkstra/A*, general collections/enums/Result, dynamic strings/Evidence,
unbounded or indexed scalable graph storage, source Horn fact/rule/proof integration and
numeric kernels remain. Source currently exposes Path length, not path iteration. Structs have
primitive/string fields only. Edge relation arguments must be direct member expressions.
Literal strings have program lifetime; there is no general heap/GC claim.

The fixed edge scan is intentionally simple for this capacity. Raise the ceiling and add adjacency
indexes only with larger workload evidence. Next source milestones can build on the frozen
[v3 contract](FIFTH_DELIVERY_CONTRACT.md) while keeping Path and Proof semantics distinct.
