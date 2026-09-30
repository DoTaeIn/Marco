# Seventh delivery — mutable source Horn knowledge

This increment belongs only to `mrl/` in the isolated MRL worktree. It preserves
Marco engine code, the Python oracle, frozen fixtures, and previous IR versions.
GPT-5.6 Terra workers own frontend, C bridge/backend, and integration checks.

## Source and values

A local `ledger = Horn(facts=Facts(...), rules=Rules(...))` constructs a fresh
bounded knowledge value each time it executes. Initial facts/rules retain the
existing checked literal syntax; rules cannot be edited at runtime in this slice.
`ledger.add(Fact(...))` and `ledger.remove(id)` mutate a mutable named binding.
Fact id/subject/predicate/object accept runtime `s` expressions, polarity accepts
`b`, and modality accepts `s` (asserted, planned, or conditional). Optional Evidence
retains checked literal source spans. Defaults are positive asserted facts without
Evidence. Terms and IDs must be nonempty. Arguments preserve written evaluation
order. No automatic coercion of numeric/boolean terms is introduced.

All live fact IDs are unique across polarity and modality. Duplicate insertion
and missing removal return false and preserve the version. Successful insertion
or removal returns true and increases the version exactly once. Removed IDs may
be reused; the reinserted fact follows existing entries in insertion order.
Invalid data, capacity, allocation, and version overflow must be explicit; failed
mutations must not partially change a plan. Initial version is zero.

Assignments copy knowledge values independently. Query results also have value
semantics: an earlier result and its metadata cannot change after an update or a
later query at the same source location. Constructors, queries, assignments,
loops, and recursive calls must not share mutable storage accidentally. These
values cannot escape through function parameters/returns in this increment.

## Queries, snapshots, and inference

`closure(ledger, ...)` and `closure_with_provenance(ledger, ...)` use existing
literal query options and optional literal closure target. Results expose existing
fact_count/proof_count/searches/complete/reason plus the captured version;
`ledger.version` exposes its current version. Structured result JSON preserves the
Python oracle shape, with version accessed separately.

Native C inference is reused without changing its semantics. Each new query
computes against current facts, including denial changes and entirely new answers.
Retraction removes only the named input; conclusions with independent surviving
supports remain. The full evaluator serves as the correctness baseline. There is
no claim of incremental inference or real Marco overlay integration.

Snapshot storage must stay bounded per invocation and lexical value/expression
site, including repeated execution in loops. Store immutable input plus computed
summary where practical; full JSON rendering may recompute deterministically from
that input using bounded temporary output. Summary field reads should reuse the
captured summary. Free temporary heap storage on function exit/return. Do not add
a general garbage collector for this slice.

## IR and compatibility

New source operations select IR v5 with the v4 root keys. `horn_plan`, `horn_add`,
`horn_remove`, and `horn_evaluate` are distinct from the existing `horn_query`.
Dynamic queries use a distinct `horn_snapshot` type. The C backend independently
checks schemas, expression types, mutable receivers, literal metadata and budgets.
All Horn operations count as impure for A* heuristic validation.

Primitive v2, graph v3, and static source Horn/search v4 behavior remain intact.
Static queries keep their valid immutable-input cache. Source Horn remains bounded
at 64 input/result facts, 32 single-premise rules, and 128 proof records per fact;
capacity errors must not be disguised as successful complete answers. The separate
Python PreparedGraph adapter retains its existing optional larger capacity.

## Completion checks

Compile real source to C and execute it without a Python runtime. Compare complete
JSON results with the unchanged oracle after add/remove, including independent
supports, dependent conclusions, denials, evidence, and incomplete budget outcomes.
Check copies, prior snapshots, repeated query sites, recursion, mutation no-ops,
versions, invalid source/IR, and runtime input rejection. Preserve the previous
101 tests. General collections/enums/Result, runtime rule editing, dynamic Evidence,
external ingestion, multi-premise joins and incremental evaluation remain future work.
