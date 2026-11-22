# Public question API

The natural and oracle arms use the same extracted reading:

```python
from experiments.graph_language_repair import public_api

reading = public_api.read(document_text)  # convenience; extraction happens here
natural = public_api.answer(reading, "가람이 무엇을 전달했나요?")
oracle = public_api.answer_plan(reading, supplied_structured_plan)
```

`answer(reading, question, *, search_rows=None)` takes an existing reading and a string.
It never extracts the document again. `answer_plan(reading, plan, *, search_rows=None)`
uses the structured plan as supplied; it does not compile or rewrite a natural-language
oracle question. An evaluator may instead express its oracle query as an equivalent
declarative search program over the same `reading["rows"]` and unchanged native search
transport. Both arms use the already extracted reading. The optional `search_rows` override
exists only for public transport fault controls; evaluations use the default unchanged core
search.

Every return is a detached JSON finite dictionary. `answer` and `answer_plan` raise
`TypeError` only for wrong top-level argument types; pipeline errors are returned in
`error`. Important fields:

| Field | Meaning |
| --- | --- |
| `answer` | Korean text from the response layer. It is `null` when a selected exact answer has incomplete search or unresolved provenance. Selector-produced qualified conflict and ambiguity wording is preserved alongside an abstaining status. |
| `answer_suppression` | A graph-policy reason when the selector's ordinary affirmative response is withheld because the API found a conflict that has no qualified response result or supported source scope. |
| `status`, `abstained`, `signals` | Policy-mapped outcome; `answered` means a supported, traceable text answer, not physical-world truth. |
| `facts` | Full detached copy of the reading's answer-bearing rows. |
| `plan`, `result` | Detached compilation and selector output, including gates, candidates, and reasons. |
| `semantic_relation`, `semantic_value`, `semantic_candidates` | A separate selector-declared semantic channel, used for distinctions such as `checking_occurred=occurred/not_performed` versus `checking_outcome=confirmed/denied/unstated/conflicting`. Candidate entries carry their own resolved support rows, exact evidence, proof chains and source references. The API copies these fields from the selector and does not infer a semantic value from the question or raw result. |
| grammatical role fields in `facts` and `evidence` | `grammatical_role` records an observed structural position such as `grammatical_subject` or `grammatical_object`; it is not an inferred semantic role, real-world agency, or a claim about a participant's intent. `semantic_role`, `predicate_kind`, and `agency_status` remain separate graph-declared fields and may be `null`, `undetermined`, or `unknown`. |
| `compatible_events`, `compatible_readings` | Selector-reported surviving events/readings after the question's constraints. Conflict reconciliation intersects reading alternatives with this set. An excluded sibling cannot veto a constrained answer; a compatible rival that lacks the asked role remains a gate, and opposite event/result claims are not treated as agreement. |
| `evidence`, `proofs`, `hypotheses` | Selected premise rows and their declared proof/dependency/hypothesis chains. Each row keeps its own exact spans and claim. |
| `sources` | Claim records paired with only the evidence rows carrying that claim; plural merged `source_ref.rows` are expanded through the original reading rows. |
| `decision_evidence`, `decision_sources`, `decision_proofs`, `decision_hypotheses` | Premises retained to explain a selector gate. These never populate selected `evidence` or `answer_spans`; each is explicitly marked with its decision basis and cannot be read as an asserted answer. |
| `answer_spans` | Exact source spans on evidence rows that carry the selected value. |
| `candidates`, `conflicts`, `events`, `qualifications` | Alternatives, touching graph conflicts, event context, and source-scope labels. For selector-derived conflict results, `supports_result` marks candidate sides retained as evidence for the conflict; neither side is marked as the selected factual answer. |
| `search` | Every search triple, assembled/complete flags, native reason, and query projection metadata. Exact answers require every hop to report `complete is True` and an assembled world. |
| `missing_references`, `error`, `warnings`, `reading_notes` | Unresolved provenance, pipeline failures, schema notes, and reading coverage/limits. |

Phase 2 adds compositional proposition questions. Their `value` may be the JSON strings
`"true"`, `"false"`, or `"conflicting"`; each answer traces to the exact polarity or
result row and its premise chain. Unknown do-verb stems receive opaque, stem-derived action
identities shared by document and question morphology. These identities establish only
grammatical action matching; they do not identify an unknown verb as transfer, checking,
or any other known meaning. `plan.question_graph.predicate_analyses` records lemma spans,
inflection, voice, polarity, mood, semantic status, and derivation for audit. Each hop's
`projection` distinguishes a complete direct query projection over all compatible rows
from a full-input rule search, and reports input/projected sizes and reading completeness
independently of the native search world's `complete` flag.

Status and abstention are looked up from `graphs/interface/status-policy.json`. The adapter
does not choose a candidate or infer language meaning. It requires all selected support
rows, proof premises, dependencies, and hypotheses to resolve in the supplied reading.
Any missing premise, invalid exact evidence span, or reading limit marked incomplete
prevents an exact public answer. Contradictions are not treated as agreement merely
because both sides happen to support the same answer value. For `reading_conflict`, only
selector-compatible readings are considered; status may remain answered when selected
evidence for the same requested predicate carries the selected value in every such reading.
A sibling excluded by explicit question constraints does not veto the answer. A compatible
rival without the asked role remains unresolved. Opposite event claims and conflicting
result forms remain conflicts. Exact spans from each selected premise and contradiction
record are retained separately.

For a supplied structured occurrence query, `answer_plan` accepts the normal plan fields
(`intent`, `goal`, `slots`, `required_action`, `required_voice`, `required_polarity`, and
`unresolved`) and executes that plan as provided. For example, a caller may supply
`{"intent":"verification_question","goal":"checking_occurrence", ...}` with subject
and object slots. The graph maps that declared goal to the checking-occurrence query. This
does not invoke the question compiler. Natural and structured queries can therefore be run
over one shared reading and compared through `semantic_relation`, `semantic_value`, and the
exact support chain in `semantic_candidates`. A missing checking result remains
`checking_outcome=unstated`; it is not converted into a negative occurrence.

If the API detects a contradiction or competing-reading status while the response graph
still supplied an ordinary unqualified answer, `answer` is `null` and
`answer_suppression.reason` reports the policy decision. Explicit conflict templates and
answers with supported attribution/checking scope retain their graph-authored wording.

For a `nonassertive_scope` gate, the status is abstaining and the response layer's qualified
hold text is preserved. Selector state references are resolved into `decision_evidence`
and `decision_sources`, including the quoted or interrogative claim's exact span. The
candidate remains available under `candidates` and the raw selector `result`, while selected
`evidence`, `sources`, and `answer_spans` stay empty.

For an `occurrence_question`, the selector value `attribution` maps to the abstaining status
`reported_only`: a report alone does not establish independent occurrence or non-occurrence.
An explicit checking outcome remains answerable through its own supported result and semantic
channel; an explicit `checking_occurred=not_performed` remains distinct from a missing check
witness.

Python sets and tuples are copied to deterministic JSON lists; non-finite floats, bytes,
cycles, excessive nesting, and opaque values receive explicit tagged representations.
The input reading is not mutated. No runtime language model, embedding, remote call,
token predictor, or neural inference is involved.

### Role answer and category scope

For compiled role questions, `answer_scope` is `structural_role`, `requested_type` records the question's requested category (for example `person` for 누구/누가, or `unspecified` for 무엇), and `type_verification` is `unknown`. These fields appear on the plan, selector result, and top-level response when applicable. They do not certify a person's identity or type and do not assert that 무엇 excludes people. The selected value and its evidence identify the structural role within the applicable textual/report scope. Explicit classification questions remain unsupported unless separately evidenced and implemented. These fields do not bypass search completeness, source attribution, ambiguity, polarity or conflict checks.

### Query graph API

`graph_api.answer(reading, question, *, search_rows=None)` compiles the question
with `compile_question_graph`, and `graph_api.answer_program(reading, program,
*, search_rows=None)` uses the supplied `query-graph-v1` program directly. Both
use the same complete existing reading, native query executor, policy, evidence
resolution, and renderer. Neither reparses the document. The optional callback
has the native `search_rows` signature and is intended for observing native
worlds or fault testing; the default is the unchanged native search.

The detached JSON-finite response contains `facts`, `question_graph` (null for
a supplied program), `program`, `native` (all alternatives, matches, native
worlds and proof bundles), `candidates` (correlated projected `values`,
bindings, canonical evidence, source records, support and provenance),
`diagnostics`, `status`, `abstained`, `answer`, and `stages`. A two-variable
projection remains a tuple in each candidate. No match means `no_evidence`,
not a negative claim. Rule-derived program values, incomplete native search or
proof closure, incomplete readings, and unsupported programs hold. The policy
and response templates are in `graphs/interface/graph-query-policy.json`.

Soft unknown WH category or opaque predicate meaning can produce a
source-qualified structural role with `type_verification: unknown`; this does
not establish the requested semantic category. Unresolved restrictive meanings,
unconsumed material and unexplained partial metadata retain conditional
candidates and abstain. Quoted, interrogative, and unknown scope cannot produce
an unqualified answer. Reported claims are attributed to the source. Reading conflicts are reconciled when every rival reading supports the same projected value; other touching contradictions and unsupported competing readings hold. Further question constraints may still permit reconciliation in cases the current policy conservatively holds. It does not yet implement general classification, arbitrary
question-scope operators, or projections beyond the native two-variable limit.
`public_api.answer` and `answer_plan` remain unchanged.

Each candidate's `projection_origins` is ordered by projected variable and
identifies its base-support predicate, triple position, and row IDs. A typed
checking value is rendered using its predicate and object position only when
all supporting interpretations agree on that origin; an ordinary entity with
the same spelling remains literal. The policy distinguishes checking occurrence,
checking outcome, and independent result. In particular, an `unstated` result
means the current evidence cannot determine the outcome. A tuple's
`tuple_support_readings` comes from complete individual native support paths,
so separate proofs cannot be combined to manufacture a correlated tuple.
