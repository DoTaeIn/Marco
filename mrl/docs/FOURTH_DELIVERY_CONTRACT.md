# Fourth delivery: implement every agreed optimization, 2026-09-28

User explicitly requested ALL suggested optimizations with the existing three GPT-5.6 Terra workers.
Only this isolated worktree's mrl/ is writable work. Active Marco checkout, existing engine sources,
oracle.py, frozen fixtures and historical reports are read-only. No commits/push/merge/global installs.
Keep exact output/evidence/proof order, duplicate supports, budgets and candidate-search counts.
No fabricated performance wins, alternate Horn DSL, or claimed complete .mrl graph language.

## Ownership
Backend: runtime/native_graph.c and NEW tests/test_native_resident_abi.py.
Frontend: toolchain.py and NEW graph_plan.py, tests/test_graph_plan.py.
Golden: NEW benchmark_v4.py, tests/test_benchmark_v4.py and v4 benchmark JSON/report.
Root: native_graph.py adapter, tests/test_prepared_graph.py, integration, README/reports/contracts.

## Toolchain interface (frontend)
build_c(source, output, *, optimization="release") and build_shared likewise.
Accept exactly "release" (-O2 or MSVC /O2) and "debug" (-O0 or /Od); no fast-math or removed checks.
Keep existing discovery/private compiler caches and output isolation.
cached_shared(source:Path, *, optimization="release", extra_files=None)->Path:
Persistent ignored .tools/native cache, keyed by source contents, all extra file contents, flags,
compiler identity (command and executable fingerprint where applicable), platform/architecture.
extra_files is optional mapping of SIMPLE basenames to bytes (reject traversal/absolute names).
Copy source + extra files into private build dir. Build into a unique temporary directory and publish
complete result safely; concurrent builders must not expose partial libraries or overwrite loaded DLLs.
Cache hits MUST NOT compile. A previous failed build must not masquerade as a hit.
No need general package/build framework. Log/expose enough identity for benchmark metadata.

## Resident native ABI (backend)
Reuse ONE parsed-graph/closure implementation for existing byte ABI, resident generic, specialization.
Keep wire v2 and capacities64 facts,32 rules,128proofs/fact for this delivery (no larger-size claims).
Existing mrl_native_graph_run remains compatible including ABI status0/1/2.

Export cdecl:
size_t mrl_graph_state_size(void);
int mrl_graph_prepare(const uint8_t *input,size_t input_bytes,void *state,size_t state_bytes);
int mrl_graph_evaluate(const void *state,size_t state_bytes,uint8_t *out,size_t cap,size_t *written);
int mrl_graph_append(void *state,size_t state_bytes,const uint8_t *delta,size_t delta_bytes);

State is opaque caller-owned aligned storage, no C heap ownership/free. Python owns its buffer lifetime.
prepare parses/checks wire/header/rules ONCE into state. Return protocol status0 success,3 unsafe,
4 plan mismatch,5 malformed/invalid ABI span,6 native capacity. Failure does not publish valid state.
evaluate returns ABI0 response (including protocol error statuses),1 output too small with written0,
2 invalid state/pointers/span with written0 when possible. State contents must not be altered by caller;
check tag/version/count bounds before use. Each evaluation recomputes derived closure/proofs from
resident asserted inputs (do NOT cache stale results). No global mutable state/stdio changes.
append takes little-endian [count, then count*5 fact words] (s,p,o,polarity,actual), validates entire
delta and capacity BEFORE mutation. Return protocol0/5/6. Preserve original input indices/duplicates
and all-or-nothing changes. Existing rule/op/budget configuration remains immutable.
A prepared unsafe-rule input may fail at construction; stateless evaluate keeps its error-result API.

Implement bounded triple-hash membership for known facts and per-position candidate buckets.
Buckets preserve snapshot insertion order; choose smallest SINGLE constant bucket, ties by position.
Rebuild/extend indices correctly across rounds, keep proof-alternative fixed-point propagation.
Use uint32 hash math and bounded probes. If performance overhead exists, report it rather than cheat.

## Rule-specialization hook (backend + frontend)
C defines Input/Rule/Fact/bind before optional include:
#ifdef MRL_GRAPH_PLAN_HEADER
#include MRL_GRAPH_PLAN_HEADER
#endif
Default static matcher performs the existing three bind operations.
Call MRL_GRAPH_MATCH(rule_index, rule_pointer, fact_pointer, binding_slots) during matching.
Default function/macro supplied when generated header has not defined it.
Call MRL_GRAPH_PLAN_ACCEPTS(rules, rule_count) during prepare/parse; default true.
Generated header supplies BOTH hooks; rejects a different body/head plan with protocol status4.
Generated matcher specializes constants, variable slots and repeated-variable checks using actual
C comparisons/assignments; no generic bind calls in its cases. Core still handles joins/budgets/
facts/proofs and head projection, preserving exact behavior.

## Graph-plan compiler (frontend)
mrl.graph_plan.make_plan(case)-> neutral dict:
{"version":1,"kind":"horn_graph_plan","rules":[{"body":[int,int,int],"head":[int,int,int]},...]}
Use the current adapter _prepare(case) once to get stable interned symbol IDs, no inference.
Validate safe heads, supported one-premise rule shape, slots and integer ranges; reject malformed IR.
emit_plan(ir)->C header string using checked integer literals only, NEVER source identifier injection.
compile_plan(case, *, optimization="release")->Path:
make_plan + emit header + wrapper:
#define MRL_GRAPH_PLAN_HEADER "graph_plan.h"
#include "native_graph.c"
Use cached_shared(wrapper, extra_files={"native_graph.c":current source bytes,
"graph_plan.h":header bytes}, optimization=...).
This is an actual checked graph-plan IR->C specialization pass, not full .mrl source integration.
Use same exported resident API as generic library; tests must compare bytes/results and reject
mismatched/unsafe plans. Parent root owns Python loader orchestration.

## Python adapter (root)
evaluate(case, *, optimization="release") stays stateless full-output compatibility.
_prepare/_decode remain single shared marshaling/decoding boundaries.
Generic library uses cached_shared; persistent build identity distinguishes release/debug and source changes.
Loaded libraries are immutable process snapshots; restart after changing native source or build code.
PreparedGraph(case, *, optimization="release", specialized=False):
deep-copy immutable metadata at construction; stable symbols, native parsed state and reusable output.
When specialized=True load graph_plan.compile_plan(case) result; generic and specialized SAME C core.
evaluate() returns full freshly decoded output, no cached result; serialize same-instance evaluate/append
with a lock, independent instances can run concurrently.
append_facts(facts): validate prospective full metadata/IDs, intern new symbols WITHOUT renumbering old
IDs, send ONLY appended fact words, commit Python metadata only if native append succeeds.
Constructor raises ValueError for unsafe/unsupported rule; malformed external inputs stay rejected.
No public mutable native state. No lazy output shortcut in parity benchmarks; full results required.

## Fair benchmark and verification (golden)
Use APIs above; implement independent code now while backend arrives.
Compare oracle.evaluate, stateless debug, stateless release, generic PreparedGraph release
(Python+same C), specialized PreparedGraph release. FULL outputs must match before timing.
Keep previous four workloads and add copied real one-premise cases from existing Marco tests,
with source path/test name/source hash attribution; do not call tiny fixtures production coverage.
Also measure append+evaluate against oracle on same evolving inputs, both generic and specialized;
do not compare resident warm reads to Python update jobs.
Separate construction/build/cache-hit startup from repeated evaluation. >=7 alternating-order batches,
>=200 repeats by default, report ALL median/batch-tail ratios, result sizes/completeness and compiler/hash
metadata. Report raw batch samples; batch-tail statistics are not per-request p95.
Verify cached library path reuse/cache hit in fresh process (no compiler launched on hit).
Preserve old v3 benchmark/report. Root runs full regression, independent frozen10 and adversarial cases.
If improvements don't win uniformly, state regressions precisely; don't fallback to Python to hide them.

