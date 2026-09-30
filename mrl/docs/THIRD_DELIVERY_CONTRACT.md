# Third delivery: callable native graph and benefit gate

Continue the same three GPT-5.6 Terra workers. Every write stays below this isolated worktree's
mrl/. No edits to the active Marco checkout, existing Python engine, oracle.py or frozen fixtures.
No commit/push/merge, global install, PATH/registry edit, new dependency or graph-scope expansion.

## Scope
Make the EXISTING single-premise runtime reusable in-process, retain its CLI wire path, and compare
full equivalent structured results with the pinned Python oracle. Full graph syntax cannot honestly
be wired yet: string/graph/evidence/result value contracts are missing. Record the smallest next
language contract without inventing a parallel Horn DSL or presenting closure as find()/Path.

## C ABI (backend owns native_graph.c and toolchain.py)
Export cdecl:
int mrl_native_graph_run(const uint8_t *input, size_t input_bytes,
                         uint8_t *output, size_t output_capacity, size_t *written);
Return0 = complete wire response (including error-status responses), *written actual bytes.
Return1 = insufficient output capacity, *written=0, output contents unspecified (never decode).
Return2 = invalid ABI pointer combination, *written=0 when written pointer exists.
NULL input is allowed ONLY for input_bytes=0 (malformed-wire response5).
NULL output/written is invalid. The caller owns valid memory spans; no pointer dereference before checks.
Wire statuses/formats/limits remain v2. Worst-case output is 4*(5+64*(7+128*8)) bytes.
Bound every write. Per-call state is local; calls with separate buffers can run concurrently.
Keep ONE implementation of matching/closure/provenance. A reader/writer context over buffers and
a thin stdin/stdout main wrapper are enough. MRL_GRAPH_SHARED excludes main and enables export.
CLI switches Windows binary mode before reading; bounded input also rejects excess/trailing data.
Do not add batching/async/graphs/new semantics. Safe Update edits; no delete/re-add file.
Add toolchain.build_shared(c_file, library), reusing existing compiler/private-cache discovery.
Zig/clang/gcc shared build; MSVC /LD support if its existing discovery path is used.

## Adapter and benchmark (coordinator owns native_graph.py; golden owns benchmark.py and benchmark report)
Keep evaluate(case) signature/structural outputs compatible; default calls reusable ctypes C ABI.
Factor existing validation/packing into ONE preparation helper reused by both transports.
Provide evaluate_subprocess(case, executable) for old CLI parity/benchmark without recompiling.
Library compiles once per Python process into a unique ignored mrl/.tools/native/ subdirectory.
A stdlib cached loader retains the library; do not try deleting a loaded DLL on Windows.
No native library downloads; build current source. New Python process reloads current source.
No inference in Python adapter, no oracle import there. ABI failures raise explicit errors, never
silently fall back to oracle or suppress malformed output. Keep strict output decoding.

Benchmark module: python -B -m mrl.benchmark --output PATH, sensible bounded defaults.
Representative admitted cases: short closure chain, closure fan-out/near-capacity, acyclic provenance
chain, provenance alternatives. Full structural parity BEFORE timing and deterministic repeat check.
Time the public native evaluate path (including validation/marshaling/decoding) against oracle.evaluate.
Use repeated batches and medians (at least5 batches); record both absolute times and ratios for
EVERY workload, not only wins. Report cold native first-call build/load separately. Prebuilt subprocess
transport is separate launch-inclusive data, never label it core compute time. No RAM claim without
measurement. Source hashes/compiler/environment/method and workload sizes belong in machine JSON.
Do not mask native-capacity or incomplete results as complete. No cyclic proof-ID explosions.

## Independent boundary/review work (frontend worker)
Own NEW mrl/tests/test_native_abi.py ONLY, plus mrl/docs/GRAPH_CONNECTION_PROPOSAL.md.
Test ctypes ABI success and parity with existing CLI, malformed bytes, output capacity/null-pointer
rules, repeated/concurrent independent calls with bounded iterations (stdlib ThreadPoolExecutor).
Compile source copies once per class using build_shared/build_c. Present compiler failure is failure,
not a skip. Coordinate exact exported symbol with backend. Existing test files remain root-owned
for necessary adapter-transport integration updates.

## Coordinator
Own contracts, integration fixes, README and final delivery report/measurements review.
Run complete appropriate checks once integrated. Record actual successes and regressions.
If no measured advantage exists, report the failed benefit gate and improve/review the current slice;
do not invent a success metric or broaden language scope just to claim completion.

