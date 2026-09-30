# Fourth delivery benchmark

The accompanying `FOURTH_DELIVERY_BENCHMARK.json` is the authoritative raw
evidence for this run. It records every batch mean, the median and maximum
batch mean, path order, complete-output parity, result sizes, build identity,
source hashes, and copied-test attribution.

## Method

Each ordinary workload first requires equal complete structured results from
the frozen oracle, stateless debug C path, stateless release C
path, generic resident C graph, and specialized resident C graph. The benchmark
then runs seven batches of 200 calls per path. Path order rotates by batch and
reverses every other batch. `batch_tail_ns` is the maximum recorded batch mean;
it is not a per-request percentile.

Construction, an explicit compiler invocation, and a fresh-process cache-hit
startup are reported separately from warm evaluation. The compiler timing may
reuse its own compiler cache. The fresh-process probe replaces compilation with
an exception and succeeds only when the persistent native-library cache is
reused.

Append measurements prepare independent identical base inputs outside the
timer, append the same delta, then evaluate the full result inside the timer.
The near-capacity fan-out update is recorded separately as the expected
declared graph-budget rejection; its successful comparison uses one fewer base
seed and declares that adjustment in the JSON.

## Results

All six ordinary workloads and all six successful updates passed full-output
parity before timing. Times below are medians in microseconds. The last column
is specialized resident C divided by generic resident C, so values below one
favor specialization.

| Workload | Oracle | Debug C | Release C | Generic resident C | Specialized resident C | Specialized / generic |
|---|---:|---:|---:|---:|---:|---:|
| Closure chain | 55.16 | 37.59 | 32.34 | 9.85 | 9.89 | 1.004 |
| Closure fan-out | 251.50 | 209.40 | 180.62 | 118.06 | 110.25 | 0.934 |
| Provenance chain | 142.46 | 79.26 | 72.47 | 42.70 | 43.34 | 1.015 |
| Provenance alternatives | 131.70 | 90.93 | 86.77 | 52.17 | 54.24 | 1.040 |
| Copied event alternatives | 55.44 | 58.47 | 52.38 | 27.96 | 27.57 | 0.986 |
| Copied signed block | 39.33 | 37.40 | 33.06 | 10.02 | 9.70 | 0.968 |

Specialization improves fan-out, copied event alternatives, and copied signed
block; it regresses the closure chain by 0.4%, provenance chain by 1.5%, and
provenance alternatives by 4.0%. The debug stateless path also regresses the
copied event-alternatives case against the oracle (1.055x). These measurements
compare the generic and specialized forms of the same C core and do not
establish a language-wide speed claim.

Append plus full evaluation remained faster than the oracle for every
successful row. Generic/specialized ratios to the oracle were respectively:
closure chain 0.507/0.491, fan-out 0.603/0.616, provenance chain 0.397/0.359,
provenance alternatives 0.624/0.555, copied event alternatives 0.849/0.736,
and copied signed block 0.709/0.739. Specialization regresses fan-out append
by 2.0% and signed-block append by 4.2% versus generic resident C.

Resident generic construction took 0.13–0.24 ms and reused its cached library.
Specialized construction took 25.46–41.58 ms; each specialized library was
also reused from the persistent cache. The explicit release compiler invocation
took 587.41 ms, with the compiler cache potentially warm. A fresh process
reused the release library without launching a compiler in 338.67 ms.

The original 32-seed fan-out append is an expected `graph_limit` budget
rejection for the oracle and both resident paths. Its successful update row
uses 31 initial seeds, then appends the same fact and reaches the declared
budget. This is a graph-limit result, not a claim of native-capacity parity.

The JSON retains the seven raw batch means and maximum batch mean for every
row, together with source hashes and compiler/build identity.

This is one local run and no confidence interval is claimed. The small
specialization differences should not be treated as repeatable wins without
repeated independent runs.
