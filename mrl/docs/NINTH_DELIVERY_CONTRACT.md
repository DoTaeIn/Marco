# Ninth delivery contract — growing, editable, recoverable knowledge

The user authorized all five roadmap areas, using existing GPT-5.6 Terra workers.
All changes stay inside the isolated worktree's mrl/. The active Marco checkout,
engine.py, semantic_parser.py, graph_inference.py, oracle.py, native_graph.c and
frozen fixtures are preserved. Eighth delivery: 131 checks passed.

## Owned work

- Compiler lane: frontend.py, c_backend.py, horn_bridge.py, __main__.py, module
  loading, value runtime, language checks/examples. Managed record values,
  nested/managed Result, relative module imports, string-key maps, checked array
  writes, diagnostics, and source access to native knowledge operations.
- Store lane: knowledge_store.h, knowledge_persist.h, horn_jsonl.h if needed,
  storage/persistence checks. Stable symbols, indexed facts, page-level snapshot
  sharing, budgeted growth, atomic admission, durable restart.
- Engine lane: knowledge_engine.h and focused inference/query checks. Multiple
  premises, recursive/chain inference, delta append, sound deletion/correction,
  selective queries, changed results and derivation diagnostics.
- Integration: reconcile interfaces, exercise real source programs, cross-lane
  correctness/scaling measurements, final report and verification.

Dependencies use agreed accessor contracts. No two workers modify the same file.
An interface declaration or a host-side Python prototype is not completion.
Generated executables must run without Python. No global dependencies, commits,
PRs, deployment, or modifications to another active checkout are authorized here.

## Semantic requirements

Old IR v2–v6 programs remain supported. New v7 source/IR must be independently
validated. All managed values have explicit transfer/retain/release behavior;
no dangling borrowed error strings, invalidated snapshots, or unbounded implicit
history. Resource budgets must fail safely with an explicit diagnostic.

Knowledge admission uses stable symbols and indexes. Snapshot mutation must avoid
copying every retained fact/string. Growth beyond 16384 is subject to an explicit
memory/resource budget. Atomic file load and Unicode/Evidence checks remain.

New positive Horn rules admit multiple premises and rule chains/recursion.
Insertion processes deltas; deletion/correction must not retain unsupported cycles
and must preserve conclusions with independent surviving evidence. Recomputing
an affected predicate component is acceptable when documented and measured;
pretending this is fact-local truth maintenance is not. Bounded computations must
report incomplete results instead of silently claiming complete answers.

Exists/count/selected facts/changed conclusions must not require full JSON output.
Explicit snapshot versions delimit changes. Full materialization remains available.

Checkpoint and committed update replay restore a coherent state, validate format,
lengths and identities, and handle interrupted writes. Acknowledged durable writes
must survive restart. Measure preparation and first query after restore; do not
hide index rebuild/full inference in untimed setup or claim instant startup.

## Completion evidence

Exercise every feature from source through C to execution. Check retained snapshots,
managed return/assignment/Result/match, imports with source file diagnostics, map
and array mutation errors, cyclic deletion and alternate supports, corrupted/torn
persistence, and memory/work budget failures. Use the unchanged Python oracle for
supported inference comparisons, plus explicit expected results for extended APIs.

Target 10k/100k/1M facts with additions, deletions and corrections. Report admission,
first query, changed-input response, retained-snapshot overhead, save/open/first
restored response, p50/p95, and peak memory separately. Record workload, samples,
source hashes and exact exclusions; no universal speedup claim. If a target cannot
be met, report the measured limitation and continue fixing it within this task.
