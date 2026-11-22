# Graph language repair — shared interface

Branch `codex/graph-language-repair-20261111`. Public self-contained experiment.

Owners:

| Area | Owner | Path |
| --- | --- | --- |
| Reading core: text → explicit reading graph | model A | `experiments/graph_language_repair/core/`, `experiments/graph_language_repair/graphs/core/` |
| Question compilation, answer selection, Korean output | model B | `experiments/graph_language_repair/questions/`, `.../graphs/questions/` |
| Independent evaluation | model C | its own paths |
| Audit | Codex | read-only |

Runtime law: explicit graph data plus generic Python mechanics. No neural inference, token
prediction, embeddings, statistical token models, model or API calls, remote tools, pretrained
NLP runtime. Python in `core/` may only implement generic graph mechanics and transport;
every inventory, marker, construction, policy and decision table is auditable JSON under
`graphs/core/`. See C10.

## 0. Entry points

```python
from experiments.graph_language_repair.core import (read_text, search_rows, matches,
                                                    select_rows, project_rows)

reading = read_text(text)                 # dict, schema "graph-language-repair-reading-v1"
world   = search_rows(reading, ["event:0", "actor", "?x"])
found   = matches(reading, ["?e", "actor", "?x"])   # [(bindings, source_refs, triple), ...]
rows    = select_rows(reading, predicates={"actor", "object"})   # field filter, see §6
```

`read_text(text, extra_graphs=())` also accepts caller-supplied graph records — a path to a
graph file or a list of records. A supplied key may not shadow a core key. This is how
world-specific knowledge such as an alias arrives; the core ships none.

`read_text` consumes only the document text. It never sees a question.
`search_rows` transports rows onto the unchanged pre-existing search
`marco.reasoning.relation_hypotheses._evaluate_world` and returns its world fields plus
projection metadata (`matches`, `facts`, `proof_bundles`, `fact_sources`, `rules`, `complete`,
`reason`, `searches`, `assembled`, `projection`). Question compilation produces the query triple; it must not re-implement
search.

## 1. Coordinates

All spans are `[start, end)` character coordinates, zero-based, over the Unicode code points of
the verbatim `reading["text"]`. `text[start:end]` is the value exactly — no trimming,
normalising or re-tokenising is permitted on either side of this interface. Whitespace tokens
are not a unit of this contract; multiword values are ordinary single spans.

## 2. Reading document

```
{
  "schema": "graph-language-repair-reading-v1",
  "text": str,
  "segments":   [{"id": "seg:0", "span": [s, e]}],
  "mentions":   [{"id": "mention:12-18", "span": [s, e], "surface": str,
                  "segment": "seg:0", "contains": ["mention:..."],
                  "contained_by": ["mention:..."]}],
  "entities":   [{"id": "entity:0", "mentions": ["mention:..."],
                  "evidence": [{"kind": str, "policy": "identity-policy:...",
                                "mentions": ["mention:...", "mention:..."],
                                "spans": [[s, e], [s, e]]}]}],
  "entity_ambiguity": [{"mentions": ["mention:...", "mention:..."],
                        "spans": [[s, e], [s, e]], "candidates": ["entity:0", "entity:1"],
                        "evidence": [str], "rules": ["identity-policy:..."]}],
  "events":     [{"id": "event:0", "clause": "clause:0", "segment": "seg:0",
                  "span": [s, e],
                  "construction": "construction:transfer_passive",
                  "action": "action:transfer", "action_span": [s, e],
                  "voice": "passive" | "active" | "stative",
                  "polarity": bool, "frame": "frame:transfer",
                  "claim": "claim:1", "inherited_claim": "claim:1" | null,
                  "complete": bool, "missing_roles": ["origin"],
                  "filled_by_completion": ["actor"], "expected_roles": [...],
                  "emits_verification": bool, "notes": [str],
                  "reading": "reading:0"}],
  "roles":      [{"event": "event:0", "role": "object", "mention": "mention:...",
                  "value_span": [s, e], "value": str,
                  "marker": "marker:를" | null, "marker_span": [s, e] | null,
                  "construction": "construction:...", "reading": "reading:0",
                  "source": "clause" | "role_completion",
                  "proof": "proof:0" | null, "from_event": "event:1" | null,
                  "row": "row:7"}],
  "claims":     [{"id": "claim:0", "kind": "direct_text", "span": [s, e],
                  "frame": null, "reporter_span": null, "reporter": null,
                  "reporter_mention": null, "inherits_from": null,
                  "policy": "scope:direct_text"}],
  "event_claims": [{"event": "event:0", "claim": "claim:1",
                    "stated_in": "claim:1", "inherited": null}],
  "hypotheses": [{"id": "hyp:0", "kind": str, "status": "candidate"|"accepted"|"rejected",
                  "subjects": [...], "evidence": [...], "blocked_by": [...],
                  "spans": [[s, e], ...]}],
  "readings":   [{"id": "reading:0", "status": "surviving", "events": [...],
                  "competes_with": ["reading:1"], "reason": str}],
  "rows":       [{"id": "row:0", "triple": [s, p, o], "polarity": bool,
                  "modality": "asserted", "claim": "claim:1",
                  "spans": [[s, e], ...], "depends_on": ["row:..."],
                  "construction": str|null, "reading": str|null,
                  "hypotheses": ["hyp:0"], "proof": "proof:0"|null,
                  "scope_kind": str|null, "layer": "content" | "meta"}],
  "proofs":     [{"id": "proof:0", "kind": str, "policy": str,
                  "rows": [...], "spans": [[s, e], ...], "because": str}],
  "contradictions": [{"id": "contra:0", "kind": str, "rows": [...], "spans": [...],
                      "readings": [...], "hypotheses": [...]}],
  "dropped_readings": [{"clause": "clause:0", "reason": str, "policy": str,
                        "span": [s, e],
                        "roles": [{"role": str, "value_span": [s, e]}]}],
  "unresolved": [{"span": [s, e], "reason": str, "clause": str|null,
                  "reading": str|null}],
  "coverage": {"segments": int, "clauses": int, "events": int,
               "regions_without_predicate": int,
               "unsupported_spans": [[s, e], ...]},
  "limits": {"applied": {...}, "notes": [str], "complete": bool, "graph_files": [str]}
}
```

`coverage` is how a reader tells a **missing** event from a **refused** link. A stretch of a
region in which no declared predicate matched is counted in `regions_without_predicate` and
located in `unsupported_spans`; it never disappears silently, and it never suppresses the
clauses that did solve.

Events additionally carry `rival_roles`, `checking_occurrence` and `checking_result`;
hypotheses carry `occurrence`, `result`, `independent_result`, `target_scope` and
`ambiguity_rules` where those apply.

`rows` is the only answer-bearing layer. Everything else explains a row.

`dropped_readings` records duplicate clause solutions and their role assignments; supported distinct interpretations remain in `readings`.

`readings` entries also carry `clause`, and every event carries the same `clause`, so two
events that are competing readings of one clause can be told apart from two events that are
two happenings.

## 3. Identifiers

* `seg:<n>` — a text segment, in document order.
* `mention:<start>-<end>` — a *distinct entity mention*, one per surface occurrence. Two
  mentions with identical surface text are two mentions. A nested span is its own mention and
  is linked to its container only by `contains` / `contained_by`.
* `entity:<n>` — an *identity*, a set of mentions joined by explicit evidence rows. Absent
  evidence, each mention is its own entity.
* `event:<n>` — one asserted happening, allocated per matched clause construction, in document
  order. Event ids are never allocated from a value: see C1.
* `claim:<n>` — an epistemic scope. `claim:0` is always the document's `direct_text` scope.
* `action:<name>`, `marker:<form>`, `construction:<name>`, `frame:<name>` — graph data nodes;
  the suffix is the key of a record in `graphs/core/`.
* `hyp:<n>`, `reading:<n>`, `row:<n>`, `proof:<n>`, `contra:<n>` — allocation order.

## 4. Row predicates

Role rows, subject is an event:

| predicate | object | notes |
| --- | --- | --- |
| `action` | `action:<name>` | what happened; the row's `polarity` is the clause's |
| `action_type` | `action:<name>` | positive metadata identifying the predicate, regardless of occurrence polarity; inspect `action` and `polarity` for occurrence |
| `voice` | `active` / `passive` / `stative` | |
| `polarity` | `true` / `false` | the clause's polarity as a value, so a question can filter on it without reading fact polarity |
| `inherited_scope` | `claim:<n>` | set only by an accepted link, with a `scope_inheritance` proof |
| `actor` | value span text | agent; absent in an agentless passive |
| `object` | value span text | theme / affected thing |
| `origin` | value span text | source of a transfer |
| `destination` | value span text | goal of a transfer |
| `instrument`, `time`, `place` | value span text | |
| `in_claim` | `claim:<n>` | every event has exactly one |
| `same_event` | `event:<n>` | accepted link only, symmetric pair emitted |
| `same_event_candidate` | `event:<n>` | unresolved link hypothesis |
| `verified_by` | `event:<n>` | an independent check that **occurred** on this event, see C5 |
| `verified_by_candidate` | `event:<n>` | the same, unresolved |
| `independent_result` | `confirmed` / `denied` / `unstated` | the checking result **as it bears on this event**; `unstated` when the event is stated only inside a report or an attribution |

Claim rows, subject is a claim:

| predicate | object |
| --- | --- |
| `scope_kind` | `direct_text` / `attribution` / `reported_claim` / `checking_action` / `quoted_text` / `interrogative` |
| `reporter` | value span text of the reporting mention |
| `reporter_mention` | `mention:<id>` |
| `frame` | `frame:<name>` |
| `inherits_from` | `claim:<n>` |

Entity rows:

| subject | predicate | object |
| --- | --- | --- |
| `mention:<id>` | `mention_of` | `entity:<n>` |
| `mention:<id>` | `surface` | span text |
| `entity:<n>` | `name` | span text |
| `mention:<id>` | `contained_by` | `mention:<id>` |

Checking rows, subject is a checking event. **Occurrence, result and independent result are
three channels and must not be read off one another.**

| predicate | object | channel |
| --- | --- | --- |
| `checking_actor` | value span text | who |
| `checking_object` | value span text | what was checked |
| `checking_occurred` | `occurred` / `not_performed` | **occurrence** — whether the checking action happened, from the predicate's polarity |
| `checking_outcome` | `confirmed` / `denied` / `conflicting` / `unstated` | **result** — what the text says the check found |
| `checks` | `event:<n>` | which event it checked |
| `checks_candidate` | `event:<n>` | the same, unresolved |
| `checks_target_scope` | a scope kind | the claim kind of the target at verification time |

`checking_occurred` and `checking_outcome` are emitted with `polarity: true` and carry their
content in the value, so a question reaches them by matching a value rather than by reading
fact polarity. The action's own negation is not duplicated into them: it stays in
`[event, "action", …]` with `polarity: false` and in `[event, "polarity", "false"]`.

A result is set to `confirmed` or `denied` **only** by a declared result form inside the
checking clause (`graphs/core/nouns.json`, classes `result_positive` and `result_negative`).
A bare checking predicate says a check happened and says nothing about what it found, so its
result is `unstated`. A checking action the text negates has no result to state: its
occurrence is `not_performed` and its result is `unstated` — never `denied`.

An explicitly competing positive and negative result yields `conflicting`, not `unstated`; the result row cites the predicate and every attached result-form span, and a `competing_result_forms` contradiction cites the row and its form spans. Bare checking has no result-form spans and stays `unstated`. `independent_result` cites a proof and dependencies for the checking outcome, target binding and target action/polarity; a conflict does not yield a single confirmed or denied independent result.

A negative statement is a row with `polarity: false` plus an explicit `polarity` row.
Negation is never encoded by dropping a row. The roles of a denied clause are still emitted —
who did not do it is an answer.

**Which claim a row is attributed to.** Content rows — `action`, `voice`, `polarity`, every
role, `checking_outcome` — carry the claim their clause was stated inside, or the claim it
inherited. Meta rows — everything in the claim, entity, link and verification tables above,
plus `in_claim` and `inherited_scope` — carry `claim:0`, because they state what the document
says rather than what it asserts to be true. `row["layer"]` is `content` or `meta`
accordingly.

## 5. Invariants

These are the clauses an audit or an evaluation may cite.

* **C1 — Same item does not imply same event; a merge needs a referring expression.** A
  shared value, mention surface or even an accepted entity identity never licenses merging two
  events. `same_event` requires an accepted `event_link` hypothesis, and **every** accept rule
  in `graphs/core/event-link-policy.json` requires one of the kinds listed there under
  `requires_referring_evidence` — an expression that actually points at the earlier happening
  (`그 부품`, `해당 항목`, `그 전달`). A conjunction of non-referring cues is not enough, however
  long: the absence of a contradiction is not positive evidence of identity. Unsatisfied links
  stay `same_event_candidate` with their blocking reason. A prior event is counted once per
  clause, not once per surviving reading, so reading multiplicity can neither manufacture nor
  remove the uniqueness cue.
* **C2 — Mention is not identity.** Role rows cite a mention and a span. Coreference is a
  separate, evidenced `entity` layer. Distinct mentions sharing a surface, an alias key or a
  coordinate prefix are not merged without an evidence row.
* **C3 — Value spans are exact.** `text[start:end] == value` for every role and value row.
* **C4 — Every row is attributed.** Each row carries at least one source span and exactly one
  `claim`. A row with no span is invalid.
* **C5 — A report is not verification, and a check is not a result.** Evidence attaches to
  the claim scope it was stated in, never to `claim:0`. Four separate rules:
  1. A check stated **inside** a report or an attribution is not independent evidence and
     verifies nothing: the hypothesis is `rejected` with
     `blocked_by: ["forbidden_source_scope:<kind>"]` and no row is emitted.
  2. A check that **did not occur** verifies nothing either — a negated checking action is
     the same epistemic situation as no checking action, which is a hold. The hypothesis is
     `rejected` with `blocked_by: ["check_did_not_occur:not_performed"]`; no `verified_by`,
     no `verified_by_candidate`.
  3. A check that occurred directly **may** target an event that was introduced in a report.
     That is not banned: `verified_by` records the occurrence, `checks_target_scope` publishes
     the target's claim kind, and the target's own content rows keep their reported claim.
     An explicitly stated result from that direct check may yield an independent result; a bare check leaves the result `unstated`. The original target claim remains attributed.
  4. Absence of a checking construction yields no verification row at all — a hold, not a
     guess.
* **C6 — Surviving readings stay candidates.** When more than one construction solution
  survives constraint checking, every solution is emitted as its own `reading:<n>`, its rows
  tagged with that reading id, and the readings are cross-listed in `competes_with`. The core
  never picks between surviving readings. Picking is the question/answer owner's decision and
  must be justified from rows. Expected-role completeness never eliminates a supported role interpretation. Exact
  duplicate solutions may be deduplicated and recorded in `dropped_readings`.

  **One reading may never assert two fillers of one role.** A frame declares
  `multi_fill_roles`, the roles that may legitimately repeat (adjuncts such as `place` and
  `time`). For every other role, a clause that offers two fillers is ambiguous, not doubly
  true: the solution is expanded into one reading per filler, each tagged with
  `rival_roles`, cross-listed in `competes_with`, with the fillers not taken recorded in
  `unresolved` as `rival_role_binding` and the readings joined by a `reading_conflict`
  contradiction. Nothing is dropped. This is the backstop for a clause boundary the declared
  inventory missed — two candidate actors become two readings, never one confident answer.
* **C7 — Late completion is proof-carrying.** A role missing from an earlier event may be
  filled later only by emitting a `proof` of kind `role_completion` that cites the span of the
  earlier event, the span of the later evidence and the policy row that allowed it. Both
  spans are retained in the row's `spans`; neither is replaced.
* **C8 — Partial is legal.** Unmatched text yields `unresolved` entries and never suppresses
  rows elsewhere. A correct partial answer must not require a complete global parse.
* **C9 — Contradictions are explicit, and "undecided" is not "refuted".** Conflicting rows
  are both kept and joined by a `contradictions` entry. The core never deletes the loser. A
  hypothesis the policy *refused* has `status: "rejected"` and names the reject rule in
  `blocked_by`; a hypothesis the policy neither accepted nor refused has
  `status: "unaccepted"`, an empty `blocked_by`, and its ambiguity rules in
  `ambiguity_rules`. A consumer must not read the second as exclusion.
* **C10 — No language knowledge in Python.** Markers, predicate forms, frames, reporting
  frames, identity evidence kinds, link policies and scope policies live only in
  `graphs/core/*.json`. No document sentence, benchmark item or case-specific branch may
  appear in `core/*.py` or in the graph data. A marker record states a syntactic class and
  never a role; only a frame maps a class to a role, and class names and role names are
  disjoint by test. `core/comparators.py` holds generic span and string primitives reached
  from policy records by name — a comparator answers a mechanical question and decides
  nothing. The test file `tests/test_graph_data_discipline.py` checks this clause
  mechanically: no non-docstring string literal in `core/` may contain a language form, and
  nothing outside the standard library and the one existing search helper may be imported.

## 6. Search transport

`search_rows(reading, query_triple, rules=())` projects `rows` into the fact shape
`_evaluate_world` accepts — `{"id", "triple", "modality", "polarity"}` — and passes the row's
provenance as `fact_sources`, so `world["fact_sources"][i]["source_ref"]` is

```
{"row": "row:7", "rows": ["row:7", "row:19"],
 "spans": [[s, e], ...], "claim": "claim:1", "claims": ["claim:1"],
 "scope_kind": "reported_claim", "scope_kinds": ["reported_claim"],
 "layer": "content", "layers": ["content"],
 "reading": "reading:0", "readings": ["reading:0", "reading:1"],
 "construction": "construction:...", "constructions": [...],
 "hypotheses": [...], "depends_on": ["row:1", "row:3"],
 "proof": "proof:3", "proofs": ["proof:3"]}
```

**One fact per distinct `(triple, modality, polarity)`.** The reading emits a per-reading copy
of a row, and the existing engine refuses a world where one triple has more than its support
limit of positive supports. A merged fact carries the union of its rows' provenance — the
plural keys above — so merging costs nothing; the singular keys hold the first value for
consumers that want one. Polarity and modality are part of the merge key, so a denial is never
merged into its assertion and a contradiction survives as two facts.

**Every content row carries `depends_on`** naming its event's `action` and `polarity` rows. A
role value alone does not establish that the event happened, so a role answer's provenance
leads to the row that says whether it did. A `role_completion` row additionally depends on the
donor event's rows.

**Support is resolved through `proof_bundles`.** `matches` reads each support id's
`premise_fact_ids` from `world["proof_bundles"]` and maps those to `fact_sources`, rather than
stripping a prefix off the support id, so evidence cannot silently point at a wrong premise or
disappear if the bundle shape changes.

`scope` is not a key of an engine fact, so scope is additionally reachable as ordinary rows
(`[event, "in_claim", claim]`, `[claim, "scope_kind", ...]`). A question that must exclude
reported material therefore filters either on `source_ref["scope_kind"]` or by a second query
arm — both are supported, neither needs a search change.

**The search's own limit, and who may answer from a truncated world.**
`_evaluate_world` assembles a finite world and returns `complete: False` with
`reason: "graph_limit"` once a projection passes its fact limit — measured at 64 distinct
facts on this branch. That limit belongs to the existing search and is not changed here.

* `search_rows` returns the native world plus projection metadata, including a `complete: False`
  world and its `reason`. When the helper could assemble nothing it returns a carrier of the
  same shape with `complete: False`, the helper's `reason`, and `assembled: False`.
* `matches(...)` raises `IncompleteSearch` — a `LookupError` subclass carrying `.reason` and
  `.world` — when the world is not complete. An exact answer may not be read out of truncated
  evidence: rivals or support may have been removed before the caller saw them. A caller that
  accepts the risk passes `require_complete=False` and owns the consequence.
* `select_rows(reading, subjects=…, predicates=…, claims=…, scope_kinds=…, layers=…,
  readings=…)` narrows a projection to the rows a query needs. A narrowed projection must
  still include the negative facts and the competing readings relevant to the query, not only
  the rows that prove a preferred answer.

```python
rows  = select_rows(reading, predicates={"actor", "object", "destination"})
world = search_rows(reading, ["?e", "actor", "?x"], rows=rows)   # complete
```

`select_rows` is a field filter over rows. It ranks nothing, infers nothing and reaches no
graph data; a document long enough to pass the limit is read in more than one projection.

## 7. Stability

The schema string changes when any field meaning changes. Additions are additive; a consumer
must tolerate unknown keys. `limits` reports the caps that were in force and names caps reached in `notes`. `limits.complete` is false whenever a cap was reached. Event `complete` only concerns its expected roles; native search `complete` only concerns the projected search world. A reading with any reached cap is incomplete and cannot authorize an exact answer without accounting for omitted alternatives.

## 8. Shared compositional predicate analysis (phase 2)

`analyze_predicates(text, mode="document" | "question", store=None)` interprets declared
character-span morphology in `graphs/core/morphology.json`. It returns analyses with `span`,
`stem_span`, `ending_span`, `surface`, `lemma`, `action`, `frame`, `voice`, `polarity`, `mood`,
`semantic_status` and graph-rule `derivation`. Every span indexes the input exactly. The
document chart uses the same analysis, with a preceding declared marker and boundary required
for open forms; question mode also exposes relative and complement forms. Results that overlap
an already-declared action use the existing declared action in the reading. Composed known stems
are resolved only through an unambiguous existing action declaration.

An unknown lexical stem uses `action:observed:<UTF-8 stem hex>` and `frame:observed`.
This stable value identifies an exact observed stem across body and question, without asserting
meaning or synonymy. The opaque frame emits grammatical role candidates and is not a transfer,
checking or other known semantic frame. `event.predicate_analysis` carries derivation metadata;
all ordinary rows retain source spans and event dependencies. Unsupported inflections and
unanchored open predicates remain unresolved. Identical orthography does not establish
real-world sense identity; finite inflection coverage, role ambiguity, source scope and all
reading/search caps continue to apply. Inputs beyond `max_text_chars` are rejected, never
silently truncated. The analyzer makes no lexical claim for noun-contained form substrings.


## 9. Direct-row query projection

For empty-rule queries, `search_rows` passes every input row compatible with all fixed query
atoms to the unchanged native search, including negative facts and all source/reading rivals.
Variables beginning with `?` or `$` are unrestricted during projection; the native search
performs the actual binding. The `projection` metadata identifies `kind` (`direct_query` or
`full_input`), `input_scope` (`reading` or caller-provided rows), row/fact counts,
`all_matching_rows_included`, `whole_reading_included`, and `reading_complete`. The first
completeness field describes the projected input only, not native search success or whole-reading
closure. The native `complete` and the reading's own `limits.complete` must both be checked.
Explicit caller subsets remain caller-scoped, never represented as complete for the whole reading.
With any rules, no query-atom slicing is performed: all supplied rows reach the native search,
so cross-predicate derivations are retained and its normal limit remains authoritative. Result
source references and proof dependencies resolve through the original complete reading; the
projected world is not an inventory of the whole reading.


## 10. Nonassertive quotation and questions

`scope:nonassertive_boundaries` declares balanced quotation pairs and interrogative end
marks. A predicate inside a balanced quote that is not already under a declared attribution
or reported claim receives a `quoted_text` claim spanning the entire quotation. An
interrogative sentence receives an `interrogative` claim spanning its segment, including
when a quoted question appears under a report. A quoted value that does not enclose the
predicate does not change the predicate's scope. A directly stated attribution containing
a declarative quotation retains its existing reported/attributed scope and reporter.
These nonassertive kinds do not establish event occurrence or independent checking results;
content rows keep their actual claim and exact span. A quoted statement's surrounding host
is not assumed to endorse or deny its content merely because it exists. Unbalanced or
unsupported constructions remain a coverage limitation, and downstream consumers must
disclose or withhold nonassertive content rather than assert it.


## 11. Marker and adjunct span alternatives

Graph-declared Hangul marker allomorph rules use Unicode syllable coda arithmetic only when
the immediately preceding host character is analyzable; they do not blacklist words.
The clause solver retains a literal-marker alternative for an earlier closing marker when
the following marker admits a subject class or a later marker can fill the same role. Each
surviving solution has its own reading; roles in competing readings must not be combined.
This is not yet an exhaustive analysis of every possible particle-versus-name boundary.
Graph-declared unmarked temporal forms followed by a boundary can alternatively occupy a
`time` role, with exact span and `construction_element` proof, or remain part of a literal
value; either outcome is a competing reading, not an unqualified preference. A balanced
quote enclosing the full value prevents splitting its internal form. The ordinary lattice
caps are reported in `limits`; consumers must withhold exact answers when supported
role readings disagree or are truncated.

## 12. Regular non-do predicate composition

`morphology:regular_verb` declares regular vowel/coda suffixes, negative forms, relative
head conditions, and invertible Hangul vowel/coda contractions. The analyzer returns the
canonical stem and exact original text spans; for a contracted syllable the stem and ending
spans may overlap because one written syllable contributes to both. Derivations name the
graph rule and inversion. Declared known-action stems are recovered only from compatible
existing action forms; an incompatible declared voice or polarity cannot be promoted to a
positive action. Unsupported future, conditional, request and irregular patterns are not
converted to past occurrence by this construction.

Coextensive distinct canonical analyses survive as distinct competing readings of **one**
clause, not two events in sequence. Consumers must retain or explicitly gate those analyses;
choosing a first analysis is not evidence. An opaque regular predicate can denote a state
as well as a dynamic action: its lexical semantic role is unknown. For opaque predicates the historical `actor` alias is structural and carries explicit
unknown semantic-role and agency metadata; it does not establish agency. Coda/suffix coverage, adnominal head
inventory and inverse rewrites are finite and do not implement all Korean morphology.


## 13. Grammatical roles and unknown semantics

`graphs/core/semantic-typing.json` distinguishes an opaque `frame:observed` predicate
from a declared lexical frame. An opaque event carries `semantic_status: unknown`,
`predicate_kind: undetermined`, `agency_status: unknown`, and a `typing_policy` graph key.
This is a syntactic predicate observation; its lexical meaning, whether it denotes an action
or state, and intentional agency are not inferred. A known frame instead carries
`semantic_status: declared`, `predicate_kind: frame_declared` and
`agency_status: frame_dependent`; the latter does not assert an actor occurred.

For an opaque event, legacy `actor`, `object` and other frame role names remain queryable
compatibility aliases. Each alias row and corresponding `roles` entry carries
`role_interpretation: structural_alias`, `semantic_role: null`, its `typing_policy`, and,
when a declared marker supplies it, a `grammatical_role`. The latter includes
`grammatical_subject`, `grammatical_object`, `grammatical_topic`, or `grammatical_oblique`;
voice does not change the syntactic marker class, so a passive nominative is a grammatical
subject even when its compatibility alias is `object`. Separate queryable grammatical rows
cite the exact value and marker, retain claim/reading, and depend on the original role plus
the action/polarity rows. Their `grammatical_role` proof points to the declared graph typing
policy. These are structural evidence, not claims about real-world agency. Known frames
retain graph-declared semantic roles and `role_interpretation: declared_semantic`.

`predicate_semantic_status` and `agency_status` are also queryable metadata rows. Search
`source_ref` carries singular and plural typing fields and exact original row IDs; consumers
must use those IDs to preserve per-row source/reading/typing pairing when facts merge.
A grammatical who/what answer may identify the text's argument while retaining source,
negation, ambiguity and semantic-unknown qualifications. No semantic class is guessed from
unknown stems or from a role's surface value.

### Opaque nominal references and coordination

A demonstrative followed exactly by the stem of a graph-composed 하다 predicate
can support a verification binding, subject to target uniqueness and a prior
entity-head rival. A matching prior role value grounds an entity alternative,
so either a declared event noun or composed stem with that rival stays a
candidate. Generic event heads use the same safeguards. Rival detection is
limited to extracted prior role values and graph-declared head boundaries; it
does not establish that all possible entity interpretations were found.
Ambiguous bindings never produce an independent result.
The declared 하고 ending permits predicate segmentation; it does not supply
semantic roles or imply that coordination shares omitted arguments.

### Composed temporal adjunct alternatives

Graph-declared relative-prefix/calendar-unit and decimal/calendar-unit patterns may
supply an unmarked time span at a whole boundary. The literal enclosing value
remains a competing reading; neither expected roles nor time typing resolve the
attachment. Quoted spans remain literal. Decimal matching uses Unicode decimal
characters; the finite graph inventory is not a general calendar or measure
ontology. Nested, spaced and inflected time expressions are not exhaustively
recognized, and missing an adjunct alternative is not evidence of its absence.

### Across-event polarity evidence

An opposing-proposition record follows the graph policy's same-action, opposite
polarity and shared-item evidence, and is blocked by a decidable conflicting
filled role. It retains both event IDs and their action, polarity and clause-role
row IDs, so selection can see the support on each side. A missing role does not
establish that its values match; remaining ambiguous identity or attachment
readings can still make this a provisional conflict rather than proof that two
independent real-world occurrences are identical.
