# Fourth delivery — 2026-09-28

All four agreed optimizations were implemented in the isolated MRL experiment with
GPT-5.6 Terra workers: optimized builds and persistent caching, resident graphs and
delta input transfer, native indexes, and checked rule-plan compilation. The coordinator
integrated the adapter, tested the complete implementation and ran the final benchmark.

Work stays under `mrl/` in `C:/Users/hirob/.codex/worktrees/mrl-runtime/Marco`, branch
`codex/mrl-runtime-language`, based on `d5d91a21397fc5ac0d3ce0923d8756c867c85eca`.
No tracked Marco engine files were changed. The active checkout, frozen oracle/fixtures
and historical reports were preserved; no commit, push, merge or system installation occurred.

## Delivered behavior

- C11 builds default to O2; debug mode uses O0. Checked arithmetic remains enabled.
  Immutable shared libraries are cached by source/header contents, build mode, toolchain,
  compiler fingerprint and platform. Fresh-process cache reuse was verified with compilation
  replaced by an exception. Concurrent builders never publish incomplete or overwrite loaded libraries.
- `PreparedGraph` owns parsed native input, stable symbol IDs and reusable result storage.
  `append_facts` transfers only new rows and commits both stores only after validation succeeds.
  Each evaluation still recomputes inference and returns a fresh complete result. This is not
  incremental inference; accepted inputs may subsequently exceed a requested inference budget.
- Known facts use triple-hash membership and snapshot candidate buckets. Candidate ordering,
  search counts, denial behavior and alternative proof propagation match the reference.
- A checked graph-plan IR emits rule-specific C matchers for constants, variable slots and
  repeated variables. Runtime plan checks reject incompatible numeric layouts. Generic and
  specialized execution share exactly the same inference, indexes and provenance implementation.
  Specialization is optional; the default remains generic resident execution.

## Verification

`python -B -m unittest discover -s mrl/tests -v`: **50 passed, 0 skipped**, 10.326 seconds.
Checks include frozen golden cases, real compiled plans, unsafe/malformed inputs, cache
invalidation/failure/concurrency, transactional append rollback, new symbols, duplicate supports,
denials, budget ordering, output buffer guards and concurrent independent results.

Final benchmark source hashes and the two copied Marco test-source hashes were independently
checked against the recorded JSON. The refreshed release CLI matched all ten frozen cases;
release examples still print `42` and `10`. The original engine files remain unchanged in Git.

## Measured outcome

Seven alternating/rotating batches of 200 full-result calls per path; six ordinary cases and
six successful append cases all matched the Python oracle before timing. The reference is
Python 3.10.6 on this Windows host, using the recorded Zig 0.16.0 toolchain. Prepared-graph
construction is excluded from repeated calls and measured separately.

| Case | Python, us | Generic resident C, us | Repeated-call speedup | Specialized / same generic C | Append + evaluate speedup, generic |
|---|---:|---:|---:|---:|---:|
| closure_chain | 55.16 | 9.85 | 5.60x | 1.004 | 1.97x |
| closure_fanout | 251.50 | 118.06 | 2.13x | 0.934 | 1.66x |
| provenance_chain | 142.46 | 42.70 | 3.34x | 1.015 | 2.52x |
| provenance_alternatives | 131.70 | 52.17 | 2.52x | 1.040 | 1.60x |
| real_event_alternatives | 55.44 | 27.96 | 1.98x | 0.986 | 1.18x |
| real_signed_block | 39.33 | 10.02 | 3.92x | 0.968 | 1.41x |

The stateless release adapter was also faster than the reference on all six measured cases.
The debug stateless path was 5.5% slower on copied event alternatives. Against the same generic
C engine, specialized query medians were 1.4–6.6% lower in three cases and 0.4–4.0% higher in
three. Specialized updates also regressed in two cases. These small mixed differences from
one local run, without confidence intervals, do not establish a reliable compiler-specific win.
The substantial demonstrated benefit comes from native execution and reusing prepared inputs.

Costs remain material: generic construction took 0.13–0.24 ms, while specialized construction
with an already cached library took 25.46–41.58 ms. The latter is a remaining setup bottleneck.
An explicit release compiler invocation took 587.41 ms with potentially warm compiler caches.
A fresh-process library-cache lookup took 338.67 ms including process launch/imports; that probe
proves no compilation but does not measure loading the DLL and performing a first inference.

The successful fan-out update starts with 31 seeds and adds one, producing 64 facts. Separately,
the original 32-seed update returns the same `graph_limit` budget error in Python and both native
paths. The legacy JSON key `append_capacity_rejection` contains this explicitly tagged
`graph_limit_budget` result; it must not be interpreted as native-capacity equivalence.
Raw batch maxima are batch means, not per-request p95. No memory saving is claimed.

## Remaining boundary

This is a bounded single-premise Horn runtime: 64 input/known facts, 32 rules, 128 proofs per fact.
The copied test inputs are small compatibility examples, not production workload coverage.
Full `.mrl` graph source syntax is not connected to the primitive frontend. Appends do not provide
fact deletion or incremental inference, and arbitrary Python tasks/libraries were not benchmarked.
The measurements therefore support a narrow runtime benefit, not universal superiority to Python
or proof that a new language is needed instead of a Python API over the same C library.

[Benchmark details](FOURTH_DELIVERY_BENCHMARK.md) · [Raw measurements](FOURTH_DELIVERY_BENCHMARK.json)
· [API and limits](NATIVE_GRAPH.md) · [Delivery contract](FOURTH_DELIVERY_CONTRACT.md)
