# Selected raw graph preparation and native judgement

`marco.runtime.selected_graph.prepare_selected_graph(model, assets, graph_member_path)`
is an explicit L9 adapter over the existing pure L2 graph parser and native L3
preparation block. All three arguments are required. It does not answer a question,
run L5 judgement, activate learning, create a Session, or write a runtime trace.

The caller supplies an actual `PackModel`, the complete `dict[str, bytes]` asset
table used for its native content fingerprint, and one existing `.kg` member key.
The adapter detaches the table and checks the complete table plus actual model
declaration with the native fingerprint recipe before parsing the graph. There is
no filesystem lookup, development model, shared conceptnet, sidecar learning log,
or default graph fallback. Nonempty native includes are retained in the parsed
input and refused; supplied include bytes do not authorize an implicit loader.

The raw selected language-member JSON is encoder declaration authority. Native
Korean-key precedence is preserved. Exactly eight explicit encoder settings must
be well formed and agree with the actual `EncoderRuntime` by type and value.
Only declared `문자` mode and `cpu` device are supported in this adapter. Neither
cached `model.language` nor native environment defaults may replace raw settings.
Malformed or conflicting settings produce a finite local configuration refusal.

`PreparedSelectedGraph` is a frozen dataclass with eight fields: `member_path`,
`member_bytes`, `member_sha256`, `model_content_fingerprint`, `model_declaration`,
`reference_encoder_declaration`, `parsed_graph_snapshot`, and `prepared_graph`.
The native parser receives exact selected bytes. Its snapshot and working graph
are separate deep copies. Native verification, related-node filtering, adjacency,
evidence aliases and character vectors use the original preparation algorithm
inside the selected encoder's ContextVar, with `cache_disk=False`. Runtime context
is restored on success, refusal and process cancellation.

`SelectedGraphError(ValueError)` carries bounded `stage`, `code`, and `error_type`
identifiers. Pure policy errors name the actual local subtype; real native parse
and preparation exceptions retain their class name without copying their raw
message or private graph path. Process cancellation is not swallowed. Unknown
input or configuration is a local refusal, not a claim that an entire future
conversation must stop.

The former `engine.load` prefix and its original preparation statements are
preserved through `engine._prepare_graph`. `_example_vecs` has one original vector
compute block and a keyword-only cache switch. Existing callers keep the old
`cache_disk=True` default, including actual private cache write and cache-hit
behavior. This unit does not call the opaque whole `load` path from the adapter.

The frozen handle contains mutable detached dictionaries; it is not an
authentication boundary. A table may contain several graph members with the same
full content fingerprint. A future answer, Session or LearningMemory connection
must bind the specific member key and SHA as well as the model fingerprint.
Graph source annotations describe author declarations; they do not prove fetched
time, source authenticity or reality. Native module import still changes
environment/logging and probes local markers before the narrower no-disk check.
There is no whole-process IO isolation claim.

The public contracts use two different raw KG bodies under the same language and
empty axioms. The original fixed 25 cases and three new prior-cache faults passed
once on the frozen private candidate and once after byte-exact main relocation.
These are the same 28 finite developer checks, not 56 independent cases or a
fresh accuracy score. The initial three faulty wrapper results and HOST setup
failure are preserved. Both model C CLI sessions exited on their requested budget
caps; their completed edits were separately reviewed and tested, and model exits
were not relabeled successful.

[Actual main results and limits](../../logs/marco2-selected-graph-prepare-audit-2026-10-07.json)
include source hashes, raw graph identities, native vector records, actual finite
refusals, CLI modelUsage and independent review. The existing Hypomnema logger is
unchanged. At this preparation-only stage, `DialogueSession` used selected
language and axiom declarations without invoking native KG judgment. The declared
live Session connection described below was subsequently integrated. MARCO 2
remains incomplete and the protected v2 exam was neither read nor regraded.

## Native judgement on the selected member

`judge_selected_graph(model, assets, graph_member_path, text, *, trace_ledger=None,
conversation_id=None, streak_A=0)` now prepares the selected member in the same
call and invokes the existing `engine.judge` under the actual selected encoder.
An externally supplied prepared handle is not accepted. The detached asset table
also supplies the actual raw language member to the existing pure decoder; that
same declaration reaches native matching, clause splitting and filler removal.
The cached `model.language` and host default language cannot replace it.

The first real public run exposed a default-language leak: 9 of 20 cases passed,
10 failed along that product path, and one unsupported-encoder fixture failed in
the native constructor before the adapter. The original results remain recorded.
The repair carries an optional `language_pack` keyword through existing engine
calls. Explicit selected packs bypass the legacy hardcoded English shell stripper;
their own clauses/fillers still apply. Calls with `language_pack=None` retain the
old behavior. Native matching, thresholds, judgement and graph preparation were
not rewritten; the keyword changes have an exact whole-module AST inverse, and
the encoder change has an exact whole-file byte inverse.

The result contains exactly `verdict`, `reply`, `status`, `gap`, `provenance` and
`trace`. Only native `인정` is `answered`; other verdicts are local holds. A missing
graph-authored goal reply returns a local `authored_reply_missing` gap instead of
the legacy court-domain fallback. Unknown input does not block a later independent
known input. This API does not provide a persistent conversational Context.

Optional tracing uses the existing `DialogueTrace` and fsync-enabled `Ledger`.
The caller supplies a nonempty conversation ID and an empty ledger runtime
declaration, so prior selected-model metadata cannot silently merge. Input is
recorded before native judgement, followed by this call's native events and actual
output. A per-call callback avoids the global trace queue; trace-off calls do not
write to it. Actual input/output IO errors remain errors; a computed output that
could not be recorded is attached as `executed_result` with `trace=None`.

The capsule records actual model/member/encoder identity and native candidates.
The input runtime also records the actual raw language member and SHA. Candidates
are not proof of used premises: edge path, rule, learning and reading usage remain
null. The durable output is explicitly `partial`, `provenance_incomplete` and
`world_truth_status=unverified`. No new logger or runtime token-predictive language
model was introduced.

The frozen 23 public developer cases passed once privately and once against the
physical main source and archived test wrapper. Main's initial HOST run failed
before collection while trying to enumerate `/Users`; a private collection proxy
fixed the HOST path without changing product bytes, test assertions or the access
guard. The successful main run still recorded 33 refused main-read attempts;
there is no zero-IO or OS-level isolation claim. The two successful runs are the
same 23 cases, not 46 independent cases or a new accuracy score. Earlier 28-case
preparation checks and the expensive full regression suite were not repeated.

[Native judgement audit](../../logs/marco2-selected-graph-judge-audit-2026-10-07.json)
and [actual main Hypomnema JSONL](../../tests/fixtures/marco2_selected_graph_judge/audit/main23-Hypomnema.jsonl)
preserve actual A/B replies, original failures, CLI usage and the finite scope.
This judgment adapter alone does not provide ordinary conversational Context or
learn new KG edges. Its subsequent declared Session connection preserves one
counter/save/trace lifecycle and binds the specific member as well as the full
model, as described below.

## Declared live Session connection (2026-10-07)

The explicit `DialogueSession` selected-member route is now integrated. Actual
raw selected conversation declarations route a captured text slot to this native
adapter; unmatched input retains the typed path and ambiguous matches hold
locally. Actual member identity and original native result/capture records survive
reopening without historical judgment replay. See the
[Session contract and remaining limits](marco.runtime.learning_dialogue.md#declared-selected-kg-route-in-the-live-session-2026-10-07) and
[31-case main audit](../../logs/marco2-selected-graph-session-audit-2026-10-07.json).

This route currently judges immutable original KG bytes. Existing graph body
overlay additions/retractions must next be composed through the existing
`PackBase`, `GraphView` and `OverlayAttachment`, with original manifest authority
and a pinned actual head. Base member SHA and the effective view/head are distinct
provenance facts. Expression OverlayStore payloads are not interchangeable with
KG node/edge payloads. Native graph-body learning, general conversation, complete
used provenance and selected-only typed realization remain unfinished.

## Native node/edge overlay read composition (2026-10-07)

`judge_selected_graph(..., graph_pack_path=actual_path, graph_overlay=attachment)`
now accepts an explicit pair: a nonempty internal model pack path and the actual
existing `OverlayAttachment`. Both absent preserve the original native API;
a partial pair refuses locally. Public `prepare_selected_graph`, its original
eight-field prepared dataclass and native judgment algorithms are unchanged.

The adapter reuses `kgpack.read(path, verify=True)` for the actual complete pack,
compares all returned bytes and the strict canonical model declaration to the
supplied selected model, and checks the original canonical manifest SHA against
the attachment. It constructs `PackBase` and `GraphView` through the attachment's
read-only store, checks the view while the handle is open, and detaches the actual
pinned head, raw effective graph and origins before closing. The effective graph
uses the same selected encoder and native preparation with disk caching disabled.
No proposal, approval, commit, store creation, implicit include or fallback graph
occurs in this reader. Nonempty JSON Horn rule changes are explicitly refused;
they are not native graph edges.

Original model/member identity remains unchanged. An optional `graph_overlay`
capsule records the original manifest SHA/build, actual head sequence/change ID,
canonical JSON SHA of the effective raw graph, `rule_changes_applied=False`, and
an actual `origin_catalog` marked `installed_not_used`. The same detached capsule
reaches the standalone trace's declared runtime and output provenance. This
inventory is not evidence of used nodes/edges; native used-proof fields stay null,
partial and world unverified. The raw graph digest does not authenticate every
Python insertion order or prepared vector matrix. Opt-in prepares the base and
effective graph separately; no one-preparation latency claim is made.

Physical main passed the same 13 focused developer cases accepted privately.
The first private run passed 12 and exposed one HOST expectation error: after
retracting a new axiom's sole goal edge, the existing engine moves the disconnected
concept to its unrelated layer. The correct result is a local hold, not the same
axiom answer. Original failure bytes were preserved; original native source and
an independent reading audit support the corrected expectation. Only that failed
case was retried. Successful main still recorded 38 refused read probes. Native
API tests declared no bundled realizer data; there is no zero-IO, whole-OS
isolation, new dialogue accuracy or autonomous-learning claim. See the
[overlay audit](../../logs/marco2-native-graph-overlay-audit-2026-10-07.json) and
[actual main demonstration](../../logs/marco2-native-graph-overlay-demo-2026-10-07.json).

The live `DialogueSession` above still calls this API without an overlay. Its
next connection must bind the actual attachment locally before Memory creation,
keep live head out of stable Memory identity, preserve historical head/reading
records without rejudging, and carry actual overlay output through the existing
sole recorder. Current stores have no portable intrinsic store ID; actual path
plus immutable metadata can define an explicit local namespace, with path moves
and identical store clones requiring a stated limitation. Never patch the input
attempt's immutable runtime stamp with a head discovered after judgment.
