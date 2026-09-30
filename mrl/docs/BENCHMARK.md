# Third-delivery native benchmark

The recorded run is in `THIRD_DELIVERY_BENCHMARK.json`: Windows 10, Python
3.10.6, five alternating-order batches of 200 calls per workload. Each workload first passed
full structural parity and a native repeat-determinism check. Timings include
public native adapter validation, marshaling, C ABI call, and decoding; Python
timings call the frozen oracle directly.

| Workload | Python median | Native median | Native / Python |
| --- | ---: | ---: | ---: |
| closure chain | 56.39 µs | 45.36 µs | 0.80× |
| closure fan-out | 253.13 µs | 411.23 µs | 1.62× |
| provenance chain | 165.91 µs | 100.39 µs | 0.61× |
| provenance alternatives | 132.51 µs | 119.42 µs | 0.90× |

Three of four workloads are faster through the current ctypes adapter, while
the near-capacity fan-out is slower. The JSON records every batch, ratio,
source hash, compiler, output size metadata, and environment. First native
call was 544.69 ms (build/load included); a separate CLI build was 573.36 ms.
Prebuilt CLI subprocess medians were 71.49–161.04 ms and include launch, so
they are reported separately from in-process computation.

The cold first call includes a new library build/load with existing compiler caches. Warm adapter timings exclude this one-time cost. No memory benefit or general graph speedup is claimed; the fan-out regression remains open.
