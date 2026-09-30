# Fifth delivery — specialized-plan setup

`compile_plan` now keeps a bounded process-local `lru_cache` of successful plan
builds. Its key is the emitted checked header, current `native_graph.c` bytes and
optimization mode. Validation and header emission happen before that lookup, so an
invalid case is never admitted and a changed numeric rule layout cannot reuse a
library. A source or mode change has a different key. On the first key lookup,
`toolchain.cached_shared` still verifies and owns the complete persistent build
identity, including the wrapper, headers, toolchain and compiler environment.

The process cache deliberately has the same snapshot boundary as loaded native
libraries: restart Python after changing the build tool or compiler environment.
This avoids repeatedly probing `PATH` while retaining persistent-cache identity
checks when a process populates a key.

## Measured setup cost

On this Windows host with the persistent DLL cache already populated, profiling ten
old warm `compile_plan` calls took 274 ms; `toolchain.find_compiler` accounted for
249 ms (about 24.9 ms per call), mostly `PATH` existence probes.

The raw file records the process-initial persistent-library samples, seven
cache-miss samples per path, and seven alternating warm batches of 50 constructions.
The fourth-delivery report's already-cached specialized construction was
25.46–41.58 ms. The new process-warm specialized path removes that repeated
discovery work; it still validates and emits the plan for every constructor.

Final rerun on 2026-09-28 (seven batches; warm batches average 50 constructors):

| Cache state | Median constructor time |
|---|---:|
| Generic persistent lookup, process loader cleared | 25.7597 ms |
| Specialized persistent lookup, process plan cache cleared | 27.0829 ms |
| Generic process-warm | 0.019696 ms |
| Specialized process-warm | 0.097782 ms |

The specialized process-warm constructor is about 277 times faster than the same workload
with its process plan cache cleared. Both cases retain the persistent DLL; this is not cold
C compilation or an inference/search speedup. Initial samples are order-dependent and
recorded separately in the raw file. The source-level BFS runtime has no Python speed
comparison in this delivery.

## Verification

`python -B -m unittest mrl.tests.test_plan_cache -v` passed (1 test).

`python -B -m unittest mrl.tests.test_graph_plan mrl.tests.test_prepared_graph -v`
passed (12 tests). The focused cache test verifies reuse and invalidation on native
source bytes, emitted-plan semantics and optimization mode.

[Raw ordered samples](FIFTH_DELIVERY_SETUP.json) are reproducible with
`python -B -m mrl.benchmark_setup`.
