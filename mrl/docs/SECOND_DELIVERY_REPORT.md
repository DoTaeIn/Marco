# Second delivery — 2026-09-28

The three existing workers continued on **GPT-5.6 Terra**, with separate file ownership in the
MRL worktree. The coordinator integrated and checked their results. No commit, push, merge,
active-checkout edit, shared PATH change or system-wide compiler installation was performed.

## Delivered

1. Typed `if/else`, `while` and half-open `for` source syntax, lexical scopes and definite-return
   checks, carried through IR v2 into checked C11. Both range endpoints are evaluated once,
   the while condition is reevaluated, and integer overflow exits with a diagnostic.
2. A working private C11 toolchain: portable Zig 0.16.0. The official archive SHA256 was verified:
   `68659eb5f1e4eb1437a722f1dd889c5a322c9954607f5edcf337bc3684a75a7e`.
   Archive, compiler, caches and generated binaries stay under ignored MRL directories.
3. A C implementation of the admitted single-premise closure/provenance subset. It preserves
   ordered facts, alternate support paths, native-computed bindings, candidate-search counts,
   explicit denials and incomplete-result budgets. Wire v2 rejects malformed records and
   reports fixed native capacity separately from requested graph budgets.

## Verification

`python -B -m unittest discover -s mrl/tests -v`: **27 passed, 0 skipped**.
Ten frozen fixture cases match the native C result exactly. The fixtures, oracle adapter and
baseline graph implementation were not regenerated or modified.

Boundary checks cover truncated packets, invalid counts/terms, trailing bytes, capacity overflow,
Windows binary-mode handling of a 26-fact header, duplicate supports/evidence selection,
arbitrary variable labels, constant-bucket search counts, initial graph overflow, and self-loop
proof snapshots. Compiler checks include malformed IR, both if branches, lexical scope, overflow,
range-bound capture, descending ranges and the signed-32-bit upper boundary.

The actual native examples print `42` and `10`. Sizes and seven-run launch medians are saved in
[SECOND_DELIVERY_MEASUREMENTS.json](SECOND_DELIVERY_MEASUREMENTS.json). Timings include process
startup and subprocess overhead and use default compiler flags with warm caches; they do not
establish graph runtime performance or compare native computation with Python.

## Limits and next gate

The C compatibility slice admits one body triple per rule and string terms; fixed capacities are
64 input/known facts, 32 rules, and 128 proofs per fact. Unique rule IDs and effective positive
asserted support IDs are required. The adapter's precise admission constraints are documented
in [NATIVE_GRAPH.md](NATIVE_GRAPH.md).

The standalone C graph runtime is not yet reachable through graph syntax/IR in a `.mrl` program.
Struct/enum, collections, Result, multi-premise joins, full relation/graph traversal and the rest of
the handoff remain incomplete. No graph speedup, RAM reduction or completed v0.1 is claimed.
The next scope decision is a measured benefit review on this slice; only then connect or expand
the graph-language surface. Existing first-delivery reports remain unchanged as historical evidence.

