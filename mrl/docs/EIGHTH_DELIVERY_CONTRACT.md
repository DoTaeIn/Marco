# Eighth delivery contract — usable values and growing knowledge

This work belongs only to `mrl/` in the isolated MRL worktree. The active Marco
checkout, engine, Python oracle, and frozen fixtures remain outside its scope.
Three GPT-5.6 Terra workers own the compiler, knowledge runtime, and numeric runtime
with integration checks. This contract records the agreed scope; the eighth delivery report and verification
file record the implementation and 131 passing checks.

## Values and ownership

Keep IR v2–v5 behavior. New capabilities select IR v6 and must be independently
validated when receiving raw IR, including types, mutability, and A* purity.
Horn and snapshot values may cross function boundaries. Horn copies have independent
value semantics, implemented with shared immutable backing and copying on mutation.
Snapshots retain the input and version they captured. Returning a value, replacing
a value, recursive calls, and repeated loop sites must not create dangling pointers
or retain an unbounded history. Loaded strings and Evidence belong to retained data.

The initial collection slice covers numeric `arr<T,N>` fixed-size values and
`list<T>` shared-reference values, using concrete `si32` and `f32` elements.
Use `.len`, checked indexing, list append, and function parameters/returns.
`Result<T,E>` supports the concrete payload types admitted by this delivery and
`Ok`/`Err` matching. General user-defined generics are not needed for these builtins.
The report must state any narrower supported combinations.

## Growing and external knowledge

An explicit literal Horn capacity admits 64 through 16384 facts, defaulting to 64.
Storage allocation follows the selected capacity and current data rather than
inflating every old program to the maximum. Rule and proof limits remain explicit.
The source must exercise capacity above 64; extending only a Python adapter is not
a completion of this item.

A compiled program loads external UTF-8 JSON Lines facts without recompilation.
`plan.load(path)` returns a recoverable result. Parse and validate the entire batch
before committing, including unique IDs, nonempty triples, polarity/modality,
Evidence spans, malformed Unicode/JSON, and capacity. A failed load leaves the plan
and its version unchanged. The exact accepted record schema and size bounds will
be documented with a runnable example. No runtime Python or new package is required.

## Numeric and incremental operations

Provide checked f32 arithmetic and numeric reductions/vector operations needed for
sum, dot product, norm, and cosine. Preserve ordinary source evaluation order.
Reject out-of-range indexing, invalid numeric values, mismatched dimensions, and
undefined zero-norm operations explicitly. Do not silently produce invalid scores.

Implement useful reuse when knowledge changes, not only repeated queries of an
unchanged plan. Preserve the full oracle result: insertion order, selected proofs,
provenance, budgets, denials, and incomplete reasons. A bounded incremental subset
may fall back to full inference for unsupported edits, but the boundary must be
explicit. Record actual work reused and compare changed-input results with a cold
full evaluation. Full-result rendering and input validation still have their own
cost; do not claim the whole pipeline is constant time.

## Completion evidence

Run source-to-C executables, positive and negative admission checks, and the previous
110 tests. Check external-load atomicity, large inputs, copies/returns/snapshots,
array versus list assignment behavior, Result matching, numeric edge cases, and
mixed old/new graph and Horn operations. Compare full structured inference results
with the unchanged oracle. Record actual benchmark inputs, compilation and process
startup boundaries, repeated measurements, and source hashes. No universal Python
speedup or real Marco learning/overlay integration is claimed by this experiment.

## Delivered combinations and bounds

Result payloads are primitive si32/f32/s/b only. Fixed arrays have 1..16384
elements and support index reads, not writes. Numeric kernels take list<f32>.
External JSONL has a 32 MiB total byte bound and a remaining-capacity record bound.
Incremental reuse is for positive asserted append-only closure with constant-predicate,
nonrecursive single-premise rules whose outputs do not feed any rule. Provenance
and all unsupported changes fall back to full inference. Input validation/output
replay and copy-on-mutation still have costs proportional to retained knowledge.
See EIGHTH_DELIVERY_REPORT.md for exact schema, measured boundaries and examples.
