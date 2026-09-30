# Selective startup and durable growth measurements

This run compares the new persistent fact index with the eager MRL runtime at
`2a7d4f9e29695dae4757d2024ca6c4b9902afa5b`. It does **not** compare with Python.
Both programs verify the same exact asserted triple in a fresh native process,
with no inference rules. Results are milliseconds; initial-query entries are
medians of three runs. Compilation, input generation, and initial exports are
excluded. The Windows filesystem cache was not flushed.

## Process start to first verified answer

| Initial facts | Eager restore | Indexed lookup | Eager / indexed |
| ---: | ---: | ---: | ---: |
| 10,000 | 79.56 | 73.82 | 1.08x |
| 100,000 | 150.29 | 76.17 | 1.97x |
| 1,000,000 | 1096.42 | 76.34 | 14.36x |

In this range, increasing knowledge 100-fold changed indexed first-answer
latency from 73.82 to 76.34 ms (about 3.4%). This is measured behavior for this
lookup workload, not proof of constant startup cost for arbitrary knowledge.
The process-launch floor dominates these indexed measurements.

## Growing database: append, correct, close, reopen

Each of three successive rounds adds 1% of the original fact count and corrects
the same existing fact to a new value. The databases accumulate all rounds; they
are not reset between updates. Restart verifies the original query, the latest
added fact, the new correction, and absence of obsolete correction values.
The table gives medians across these three growing states.

| Initial facts → final facts | Eager reopen + verification | Indexed reopen + verification |
| ---: | ---: | ---: |
| 10,000 → 10,300 | 84.33 | 77.53 |
| 100,000 → 103,000 | 167.60 | 77.18 |
| 1,000,000 → 1,030,000 | 1259.27 | 81.57 |

No application-level full-index rebuild or full-fact replay occurs on this
indexed reopen path. SQLite still has normal B-tree reads and journal/checkpoint
work; the experiment does not measure cold-disk latency or crash recovery.

## Durable update cost

These are native batch operations: one transaction/commit for all added facts
and one correction. Timing includes preparation, insertion, and durable commit,
but excludes database open / eager restore. Source-level indexed calls currently
commit each call separately, so these batch numbers are not a source-loop claim.

| Facts added per round (+ one correction) | Eager journal commit | Indexed transaction |
| ---: | ---: | ---: |
| 100 | 0.83 | 3.20 |
| 1,000 | 1.62 | 13.43 |
| 10,000 | 11.16 | 109.36 |

**Indexed writes are slower in this comparison.** At one million initial
facts, the 10,000-row update costs 109.36 ms versus 11.16 ms for the existing
journal. The benefit is selective reopening (81.57 ms versus 1,259.27 ms), not a
universal speed improvement. Use eager Horn plans when full inference/provenance
is required; this new API serves exact stored assertions.

## Work counters and reproduction

At all three sizes, the initial indexed query materializes one fact record
(52 logical payload bytes), executes 39 SQLite VM steps, and reports zero
full-scan steps. After the last growth round, five checks materialize three
fact records (156 logical bytes), with 151 VM steps and zero full-scan steps.
These counters cover native find statements; they are not physical disk bytes,
whole-process allocation counts, or metadata-open work.

```powershell
python -B -m mrl.benchmark_scalable_startup --sizes 10000 100000 1000000 --samples 3
```

The driver retrieves the frozen baseline headers with `git show`, builds both
executables in a temporary directory, alternates measurement order, and records
raw samples and source hashes in [SCALABILITY_BENCHMARK.json](SCALABILITY_BENCHMARK.json).
The final source-stability check passed. Three-sample p95 is simply the maximum;
it is not a reliable tail-latency estimate. See [the API contract](INDEXED_KNOWLEDGE.md)
and [full-suite verification](SCALABILITY_VERIFICATION.json) for behavior and limits.
