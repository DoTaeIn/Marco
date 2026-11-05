# `marco.runtime.learning_dialogue`

Working-tree implementation and focused verification, 2026-10-06. The first
MARCO 2 session prototype was moved from `marco.conversation` into the original
runtime responsibility boundary after independent review. See the
[implementation record](../archive/README.md "보관 ZIP 내부: docs/ko/2026-10-06-marco2-first-slices.md") for limits.

## Purpose

Connect explicitly taught expression memory to the existing graph reasoner.
An explicitly selected model supplies the parser, graph identity and declared
replies. The omitted-model option is development tooling. No runtime token
language model or language-model service call is added.

## Owns

`DialogueSession` dispatches responses, teaching, retraction, parser refresh,
state persistence and an untrusted read-only research hook. The reasoning
context owns identified reading revisions and retained compiled action programs.
A new utterance uses current declarations; past utterances retain their own
interpretations. Missing historical readings hold only dependent work; a
verified checkpoint can support unrelated dialogue.

Session-v2 binds actual selected-model assets, parser identity and the learning
store's change ancestry. Truly unstamped or unbound old stores are preserved
and refused. The state file is replaced atomically. A failed session save after
a learning commit requires reopening; the learning commit is not concealed.

## Does not own

Grammar, expression admission, inference rules, automatic concept discovery or
search decisions. Retrieved claims never enter conversation facts or learning
automatically. The older `marco.runtime.conversation.Conversation` API is unchanged.
With an explicitly supplied fsync-enabled `trace_ledger`, every response, teaching,
retraction and research attempt is recorded through the existing Hypomnema contract.
Recording selects no semantic decisions. Exact matched learning-candidate, declaration,
realizer, assumption and source usage collectors remain incomplete; installed memory
is never presented as actual use.

## Depends on

`pack_model.PackModel`, `LearningMemory`, `ReasoningContext`, reading identities,
`marco.storage.overlay.dumps`, `DialogueTrace` and the standard library. Full selected-graph
binding belongs to this session envelope; bare context snapshots still lack it.

## Public interface

`DialogueSession(memory_path, state_path=None, model=..., research_hook=...,
trace_ledger=...)`
supports `respond`, `teach`, `retract`, `research`, `snapshot`, `save`, `close`
and context-manager lifecycle. Existing session checks were updated for v2;
18 passed. Together with 45 reading/model checks, the relocated implementation
passed 63 focused checks. These are development checks, not a fresh exam score.


When tracing is enabled, input is durable before execution. State saves and accepted
learning-overlay head changes are reported separately. A completed finite teaching
gate remains recorded even if later parser rehydration or session saving fails;
this is a scoped admission check, not world truth or proof of rule use. Execution
errors retain their original exception. A failed output record after a successful
save does not roll committed dialogue state back. `last_trace` describes the current
attempt separately from the existing public API result; the caller owns the ledger.

Actual used premise readings come only from evidence indexes already returned by
the engine. Their archived observation identity, reading revision, original source,
grammar digest and historical memory head are retained. Historical text is not
reparsed to infer a candidate. All demonstrated outputs still explicitly report
`provenance_incomplete` and `world_truth_status=unverified`.

The first hook candidate passed 128 related checks, but an additional independent
post-teaching rehydration fault exposed a lost gate report and blocked import. The
repaired candidate passed 41 focused checks (20 new session checks, 18 existing
session checks and three independent root faults). Root also ran 12 separate
processes across a public development model and two differently declared models:
36 outputs, 284 events, no schema problems. See `examples/marco2_session_trace_demo.py`
and `logs/marco2-session-provenance-demo-2026-10-06.json`. The source hook demonstration
is an explicit offline fixture; it does not establish live-web semantic answering
or autonomous learning. No protected evaluation was rerun.

## Natural teaching controls (opt in, 2026-10-07)

`DialogueSession(..., model=selected_pack, learning_controls=True)` connects the
selected model's existing `learning_protocol` declarations to ordinary `respond`
calls. Enabling it requires an actual explicitly supplied `PackModel` and a strict
Boolean flag before any store is opened. Disabled or missing controls use the
ordinary path; controls from another model are never supplied as a fallback.

One bounded pending source and lesson draft collect the user's equivalence,
positive example, unrecognized example and current approval. The existing pure
L1 reader interprets the selected controls, and the existing L6 Memory gate admits
the expression once. Admission records the original unknown source and each
actual teaching turn. Other known dialogue continues. Approval asks for the
original sentence again; only a successful fresh observation with a new active
nonnull reading resolves that pending source. Old readings are not reinterpreted.

Approved learning persists in LearningMemory and works in the two actual child
process checks. The later bounded collection extension below also preserves a
current pending source and unfinished lesson draft across restart when a state
path is supplied. This is finite, explicit supervised expression learning; broader
language understanding and autonomous learning remain unfinished. The public A/B models change relation direction, rules and
reply declarations while retaining the same underlying graph asset.

Teaching through `respond` retains one native gate, counter increment and save,
with the actual inner teaching operation attached to the existing Hypomnema
attempt. Finite admission checks, committed Memory changes and failed session
saves remain separate. Answer provenance links actual used archived fact premises
to their learned candidate and teaching turn, with missing origin families marked
partial and world truth unverified.

Main integration covered 27 selected checks: seven passed in the original batch;
20 were blocked by an overly strict HOST subprocess guard before their bodies.
After correcting only the HOST allowance for native read-only Git metadata and
private temporary cleanup, those same 20 passed once. The passing seven were not
repeated. The original failures and actual A/B live and child results are retained
in the [integration audit](../../logs/marco2-natural-learning-audit-2026-10-07.json).
This coverage is a development verification, not a blind accuracy score.

## Unfinished lesson collection across restart (2026-10-07)

With the same explicit selected model, conversation and state file, optional
`learning_collection` metadata carries one pending source, unfinished examples
and the actual native approval/rejection outcome. Legacy absence, malformed
optional data, stale native witnesses or foreign bindings cause a local metadata
gap while independent known dialogue retains its native context. `state_path=None`
remains ephemeral. The native Session-v2 format and Memory engine are unchanged.

Native candidate ID, payload, teacher turn and current head must agree; finite
JSON comparisons preserve Boolean/number distinctions. Approval is stamped
before the same sole native save. A real Memory commit followed by session-save
failure stays committed and requires reopening. Optional metadata faults do not
conceal native save errors or erase the original collector during rollback.

The original three public restart cases failed once on the preceding source and
passed once on the frozen candidate. Candidate checks passed in separate batches
of 3, 6 and 5; main integration passed its selected 11 once, including those same
three restart cases using actual main child processes. These overlapping checks
are lifecycle verification, not a fresh dialogue accuracy score. Full graph-body
knowledge use and broader natural conversation remain unfinished. Actual child
results, partial provenance, CLI modelUsage and original failures are indexed in
the [collection audit](../../logs/marco2-pending-collection-audit-2026-10-07.json).

## Declared selected-KG route in the live session (2026-10-07)

`DialogueSession(..., graph_assets=assets, graph_member_path=member)` now offers an
explicit selected native KG route. Both arguments and the actual selected
`PackModel` are required together. The raw selected language member declares a
single text slot and `engine.judge` in its existing conversation templates. L1
validates and reads these declarations through the existing TemplateBackend; no
KG domain phrase, relationship or answer is inserted in code. No matching route
continues the existing typed path. Several matching routes create a local
ambiguity without falsely recording an executed native judge.

The native call uses `judge_selected_graph` without a second recorder. L9 retains
one actual turn, counter, save and Hypomnema attempt. The full original input,
actual captured span and the original declaration identity stay separate. The
native branch does not pass its KG result through typed observations, expression
learning or stale typed proof flushing. Native candidate events still do not prove
used edge/rule/learning/reading origins: output provenance is partial and world
truth unverified.

Opt-in state and LearningMemory bind the full model fingerprint, actual member
path and original member SHA. Legacy sessions retain their prior binding. The
optional `selected_graph_turns` carrier validates finite types, current member,
actual template/capture and native result consistency, preserves bounded prior
history and records a local gap on malformed or over-capacity data. Reopening
never reruns historical KG judgments or reinterprets old held input. Independent
typed context continues after local holds or optional metadata faults.

The frozen candidate and physical main each passed the same 31 distinct developer
cases (15 original plus 16 supplement cases); this is not 62 independent cases or
a fresh accuracy score. HOST setup/accessor/assertion corrections and their
original failures are retained, and only the failed cases were retried. Actual
main child processes restored both graph members without historical native judge
calls and retained typed expression learning transferred to a new entity. See the
[session audit](../../logs/marco2-selected-graph-session-audit-2026-10-07.json) and
[actual public demonstration](../../logs/marco2-selected-graph-session-demo-2026-10-07.json).

Expression learning already uses the original `LearningMemory` and `OverlayStore`.
Native KG body overlay additions, removals and their origins are not yet consumed
by this route. The existing `PackBase` / `GraphView` / `OverlayAttachment` path is
the next integration: keep immutable member bytes separate from the applied
head/effective view, and do not treat expression-rule records as KG node/edge
records. Broad native historical inference and KG self-learning remain pending.

The actual main checks also exposed two existing typed-path dependencies outside
the selected assets: bundled `marco/language/realizer/한국어.json` and
`styles/한국어.json`. Tests allowed these named read-only data files explicitly,
with exact hashes before/after, instead of hiding access through renamed stems or
fake data. Native selected-language judgment skips that realizer. Connecting the
typed realizer to the actual selected declarations remains required; these checks
do not establish graph-only semantics for all dialogue. B0 research composition
with the opt-in member-bound Memory identity is also pending. No runtime token
language model, new logger or new overlay storage engine was introduced.

## Subsequent native overlay API: Session boundary still pending

The standalone selected native API now composes existing approved KG node/edge
overlay changes; see the [native overlay reader](marco.runtime.selected_graph.md#native-nodeedge-overlay-read-composition-2026-10-07).
This Session constructor and its native-call arguments have not yet been extended
with that attachment. Its original ten-field native history validation also does
not yet accept the API's optional seven-field `graph_overlay` capsule. Therefore
the standalone 13-case result is not persistent overlay dialogue validation.

The next narrow L9 connection must validate actual pack/attachment before Memory,
bind a stable local attachment namespace separately from the changing head,
transport actual output and original history through the existing recorder, and
leave the input attempt runtime stamp immutable. A current head must not replace
the saved historical head or rejudge prior user input. Existing store metadata has
no portable store UUID: do not invent one from creation time or a change ID, nor
create another storage format. The explicit local path/immutable-meta policy must
state path-move/clone limits and retain independent local holds.

## Existing open operation reference

`_traced` retains its actual returned Attempt, recorder and operation kind in the existing ephemeral active dictionary for the private relation acquisition caller. Begin/execute/clear/report/finish ordering and serialization remain unchanged. This reference lets current carrier capture verify the same native log operation; it does not itself deliver a conditional answer or confirm word meaning. See [trace owner audit](../archive/README.md "보관 ZIP 내부: docs/ko/2026-10-08-marco2-trace-owner-audit.md").


## 2026-10-09 자연 질문 교습 연결

선택 그래프의 query controls를 기존 Session의 query 전용 draft로 수집한다.
첫 source/ref와 각 입력 사건·모델/Memory binding·head·counter를 보존하고,
현재 명시 approve 한 번만 기존 _learning_payload와 _teach로 넘긴다. Memory가
검증·승인·overlay 저장을 소유한다. 예외 후 실제 catalog/body/head를 관찰하며
불확실한 durable 결과를 임의 rollback하거나 gate 재실행으로 덮지 않는다.
Teaching의 제한된 무손실 origin wire는 출처의 의미를 축약하지 않는다.
새 저장·추론·로그 owner와 도메인 의미 상수를 추가하지 않았다. 기존 사실
수집과 Context 바이트는 유지한다. 자리 종료·재사용 및 결과 안내는 다음 연결이다.
[실제 감사](../archive/README.md "보관 ZIP 내부: docs/ko/2026-10-09-marco2-natural-query-learning-audit.md").
