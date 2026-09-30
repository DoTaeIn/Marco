# Native graph fixture slice

`mrl.native_graph.evaluate(case)` sends a fixture input to the bounded C runtime and decodes its ordered records. The adapter never invokes Python graph inference to obtain the native result.

The private v2 wire protocol uses signed 32-bit little-endian words, a magic header, and explicit malformed-wire status. Native records carry input evidence indexes, proof links, and three computed binding slots; Python only assigns those slots to arbitrary variable names declared by each rule.

The admitted subset has one body triple per rule, string triples, positive int32 budgets, unique string rule IDs, and unique effective asserted support IDs. Duplicate triples with distinct support IDs are supported. Invalid or unsupported inputs fail before native dispatch; the adapter never substitutes provenance for an unknown operation.

The default resident interface, legacy byte/CLI interface, and source Horn queries retain a 64-fact capacity. `PreparedGraph(case, capacity=N)` explicitly opts into 64..16384 input/derived-fact slots; the rule limit remains 32 single-premise rules and the proof limit remains 128 records per fact. Graph budgets in `case["options"]` remain separate from this storage capacity. It reports native capacity separately from requested graph or proof budgets. This remains a standalone Horn compatibility slice. IR v3 has a separate Path/BFS runtime. IR v4 now connects literal source Horn queries through horn_bridge; full graph-language equivalence remains pending.


Admission details: closure facts require an evidence field; provenance evidence is a mapping or falsy. Polarity is boolean, and modality is asserted/planned/conditional. Closure options contain only limit; provenance also admits proof_limit and search_limit. Supplied budgets must be positive int32 values (not booleans), and unknown options are rejected. Effective support IDs are taken from id, evidence.fact_id, or the input index, converted to string. Duplicate positive asserted IDs are rejected even if a denial later filters the fact. Up to three variable slots per rule are admitted.

The default adapter now calls `mrl_native_graph_run` in a C shared library via ctypes. Initialization is serialized; native calls use separate buffers. Release builds use O2 and debug builds use O0. Immutable libraries are cached by source, extra headers, build mode, toolchain, compiler fingerprint and platform under ignored `.tools/native/`. Cache hits reuse builds across processes. Loaded code is a process snapshot: restart Python after editing native sources. `evaluate_subprocess(case, executable)` runs the same packet through a prebuilt CLI for comparison. Both transports share validation/packing/decoding, with no oracle fallback. See THIRD_DELIVERY_CONTRACT.md for ABI return codes and buffer rules.

## Prepared graphs and compiled plans

`PreparedGraph(case, optimization="release", specialized=False, capacity=64)` validates, deep-copies metadata,
interns symbols and parses native inputs once. `evaluate()` reuses opaque native state and an output
buffer, recomputes closure/proofs, and returns a fresh complete decoded result. Input and returned
metadata mutations cannot change the resident graph. Calls on one instance serialize with a lock.

`append_facts(rows)` sends only the delta. It validates prospective metadata and duplicate support IDs
on the Python side, then the native layer validates the complete packet and remaining capacity before
mutation. Failed appends leave both states unchanged. New symbols extend the existing ID map.
Rules, operation and budgets are immutable; use a new instance to change them. Appending a denial
recomputes support correctly on the next evaluation. This is delta input transfer, not incremental
inference or retraction support. An accepted append can cause a later evaluation to report a graph
budget or derived-fact capacity error; it is not automatically rolled back on that later error.

`specialized=True` uses `graph_plan.make_plan/emit_plan/compile_plan` to lower a checked numeric
graph-plan IR to C matcher hooks. Constants, variable slots and repeated variables become explicit
comparisons/assignments. Runtime plan checks reject mismatched numeric rule layouts. Symbols, rule
names and evidence remain adapter metadata, so structurally equivalent numeric layouts may share a
compiled library. The compiled path uses the same inference, index, limits and provenance code.

The C resident ABI uses caller-owned aligned storage sized by `mrl_graph_state_size`. Prepare is
transactional and returns protocol statuses; evaluate returns the same ABI status family as stateless
execution. State is opaque and tied to its originating library and process, checked using a tag,
version, owner token and count bounds. It is not a serialization format; callers must not edit state
bytes or pass unaligned storage. Prepare rejects unsafe rules at construction, whereas stateless
evaluate returns its existing error result. See [the delivery contract](FOURTH_DELIVERY_CONTRACT.md).

Known-fact and denial membership use bounded hash tables. Per-position constant buckets use
insertion-ordered linked lists and hashed lookup, selecting the smallest single bucket with ties
resolved by position. Working fact/index storage is linear in the selected capacity, allocated on
the heap and freed after each evaluation. Closure allocates no proof matrix. Buckets rebuild at
each inference round; facts derived during a round do not change candidate selection or search
counts. Proof alternatives still propagate to a fixed point. Results are recomputed after updates;
this optimization adds no inference-result cache. Provenance proof storage uses a shared row
stride equal to the larger of the requested proof budget (capped at 128) and the largest asserted
support count for one fact. This preserves asserted supports beyond a small proof budget. Many
duplicate supports for a single fact can still raise the stride to 128 for the whole evaluation.

The resident state layout is private version 2. Callers obtain its size with
`mrl_graph_state_size()` (64 slots) or `mrl_graph_state_size_for(capacity)`; the latter returns zero
for unsupported capacities. State stays caller-owned, bounded, and tied to its loaded library.
The public byte protocol remains version 2. Existing source Horn plans remain literal-only and
64-fact bounded; the larger capacity is available through the resident adapter only.

See [growth measurements and verification](GROWTH_REPORT.md) for first-use, append, and memory
results. Build-cache identity now obtains OS/architecture information without an OS-version shell
command; Windows prefers the already provisioned private Zig compiler before scanning PATH.

## Repeated specialized construction

The checked plan header, native source bytes and build mode key a bounded process-local
cache of compiled plans. Every construction still validates and emits its plan. A first
key lookup uses the complete persistent toolchain identity; matching keys avoid repeated
compiler discovery. Restart Python after build-tool/compiler-environment changes.
[Setup measurements](FIFTH_DELIVERY_SETUP.md) report construction separately from inference.

## Literal source queries (sixth delivery)

The same C inference engine is embedded by the source compiler for inline closure and
closure_with_provenance Horn queries. Compilation validates and marshals the literal plan;
the executable performs inference on first use and stores its immutable result for program
lifetime. The C renderer preserves full adapter/oracle structure, including selected target
proofs and alternative provenance bundles. Source summary fields remain typed.

Plans currently contain literal facts/rules, with validated optional Evidence. They cannot be
stored in source variables or updated dynamically. The Python PreparedGraph interface above
remains the available resident update interface. Source target misses have an explicit result
because the legacy oracle raises KeyError; that source behavior is separately tested/documented.
See [the source contract](SIXTH_HORN_CONTRACT.md) and [example](../examples/horn_proof.mrl).
