# Third delivery — 2026-09-28

Three GPT-5.6 Terra workers continued the isolated experiment: C ABI/toolchain, benchmark,
and independent ABI tests/graph-connection review. The coordinator completed the Python adapter,
integrated tests and reviewed the result. Changes stay under this worktree's mrl/ directory;
the active Marco checkout and its engine sources remain untouched.

## Delivered

- `native_graph.evaluate(case)` now reuses an in-process C shared library through stdlib ctypes.
  It compiles once per Python process into ignored `.tools/native/`; repeated calls do not
  compile or launch an executable. The loader retains the DLL for the process lifetime.
- The shared entry point and existing CLI use one inference implementation and the same v2 wire
  contract. `evaluate_subprocess(case, executable)` preserves the prebuilt CLI comparison path.
- Input validation, full structural output decoding and native error statuses remain enforced.
  The C ABI bounds input/output spans, checks pointer combinations, uses local state and leaves
  host stdin/stdout modes alone. Only the CLI sets Windows binary stream mode.
- A redundant maximum-buffer copy was removed; decoding copies only the returned bytes.
- `python -B -m mrl.benchmark --output mrl/docs/THIRD_DELIVERY_BENCHMARK.json` reproduces the
  parity-gated comparison with four workloads, five alternating-order batches of 200 calls each.

## Verification

`python -B -m unittest discover -s mrl/tests -v`: **31 passed, 0 skipped** in 8.160 seconds.

All ten frozen Golden cases match through both the shared library and CLI, with repeat determinism
and unchanged inputs. New ABI checks cover success/malformed/oversized input, null-pointer rules,
output capacity guard bytes, and sixteen distinct concurrent requests compared with sequential
results. The compiler/control-flow and prior graph-boundary checks remain green.

Benchmark source hashes were independently checked against the final adapter, C runtime, toolchain,
oracle adapter and pinned graph implementation. Full structural parity and deterministic repeated
output are required before each timed workload. The frozen fixtures and oracle were not regenerated.

## Measured result

| Workload | Python | Native public adapter | Native / Python |
|---|---:|---:|---:|
| Closure chain | 56.39 microseconds | 45.36 microseconds | 0.80 |
| Closure fan-out, 64 output facts | 253.13 microseconds | 411.23 microseconds | 1.62 |
| Provenance chain | 165.91 microseconds | 100.39 microseconds | 0.61 |
| Alternate supports | 132.51 microseconds | 119.42 microseconds | 0.90 |

Lower ratios are better. The native path is faster in three measured cases and slower in the
near-capacity fan-out case. The strongest measured result is about 39% less elapsed time for
the provenance chain. This establishes a narrow latency benefit, not a general native speedup.

These are end-to-end public adapter calls: validation, symbol marshaling, C execution and decoding
are included. Python uses the frozen structural oracle wrapper. Compiler flags are the recorded
default C11/shared-library flags, without added optimization flags. No RAM benefit is claimed.

The first native call, including build/load, took 544.69 ms in a fresh benchmark process with
existing compiler caches. A separate CLI build took 573.36 ms. Prebuilt CLI calls took
71.49–161.04 ms including process launch; those are kept separate from warm in-process timings.
First-call build cost is still material for one-shot use. The JSON preserves every batch,
compiler/environment, hashes, workload and output counts.

## Graph connection and remaining work

The performance gate has limited positive evidence and an explicit fan-out regression. Full graph
syntax is still pending. Connecting it honestly requires node/string values, typed facts/rules,
relation metadata, evidence and a structured closure/proof result. The current primitive frontend
cannot express those values. `find/find_all` must remain Path traversal, distinct from Proof.

[GRAPH_CONNECTION_PROPOSAL.md](GRAPH_CONNECTION_PROPOSAL.md) records the minimum next contract;
no alternative Horn language, placeholder graph syntax or fake Path operation was added.
This delivery improves and measures the existing runtime rather than claiming end-to-end
`.mrl` graph equivalence or v0.1 completion.

See [benchmark details](BENCHMARK.md) and [raw measurements](THIRD_DELIVERY_BENCHMARK.json).
Previous delivery reports remain historical.

