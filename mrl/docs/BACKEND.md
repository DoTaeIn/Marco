# MRL C11 backend

`emit_c` validates exact IR v1/v2/v3/v4/v5 schemas, types, scopes, definite returns, graph ownership,
Evidence and new search/Horn values before emission. Source names become generated identifiers;
strings use fixed-width octal UTF-8 bytes. Hostile raw IR tests are separate from source checks.

si32 arithmetic uses int64 intermediates and explicit overflow checks. Expression temporaries
preserve left-to-right evaluation, including all typed-edge arguments before insertion. For
bounds are captured once; int64 loop iteration avoids overflowing the final si32 increment.

The emitted translation unit embeds graph_runtime.h. Node payloads have typed arrays; edge
payload costs are selected explicitly per query. Graph identities/generations, stale handles,
capacities, path indexes, negative costs/heuristics and cost overflow are checked.

## Search values and lifetime

Single-path BFS retains its established node-global visited/budget behavior in v3 and v4.
Multiple-path search uses vertex-simple candidates and a temporary frontier that grows only
when needed and is freed at completion. Weighted searches preserve alternate depth states.
Candidate ties use relation, destination and edge insertion order. A* priorities use int64.

Path stores the node/edge sequence. Paths results own value snapshots: lets, assignments and
match binders copy populated paths and headers into a per-function-invocation heap frame.
Frames are freed on returns and avoid large Windows debug stacks; recursive calls get distinct
frames. Fixed PathSet capacity is 256. There is no general heap/GC or unbounded graph claim.

## Horn results

V4 horn_query uses horn_bridge independent validation and emitted support. Literal plans become
native wire bytes plus metadata. The existing native_graph.c engine executes at runtime and
C renders closure records, selected target proofs and full provenance JSON. Each syntactic
static query has immutable program-lifetime storage and is evaluated once on demand.
Compilation never computes its answer through Python. Horn result handles cannot escape via
unsupported function types or be confused with Path values.

V5 adds independently checked horn_plan, horn_add, horn_remove and horn_evaluate
expressions. Plans and horn_snapshot values copy independently. Snapshot inputs and
summary metadata are bounded; structured printing may re-run native inference from
the captured input using temporary output. Summary reads reuse captured metadata.
Repeated query sites and recursive invocations must preserve prior snapshots without
retaining an output allocation for every loop iteration. This is full recomputation,
not incremental inference. Source capacity remains 64 facts and 32 rules.

## Build

`python -B -m mrl SOURCE.mrl -o OUTPUT.c` rejects input overwrite and non-.mrl source; create
the output directory first. si32 main prints its return value; void main prints explicit calls.
Generated executables run without Python.

The local toolchain discovers clang/gcc, complete Visual Studio or portable Zig in `.tools/`.
Release uses O2, debug O0, both retaining checks. Shared-library cache identity includes source,
headers, mode, toolchain/compiler fingerprint and platform. Publication is atomic and immutable.
Specialized Horn plans additionally reuse process cache entries, still validating inputs each
time. Restart Python after changing build tools/compiler environment. See historical
[setup measurements](FIFTH_DELIVERY_SETUP.md) and current [mutable Horn contract](SEVENTH_DELIVERY_CONTRACT.md).
