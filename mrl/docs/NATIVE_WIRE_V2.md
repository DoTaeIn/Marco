# Native single-premise wire contract v2

The native core and Python adapter are private experimental interfaces, upgraded together.
All words are signed int32, encoded little-endian explicitly (no struct layout).
Windows streams enter binary mode before the first read. Any short read, invalid length,
invalid term ID, or trailing byte returns status 5. Native status 6 means a fixed native
capacity was reached; it must never be mislabeled as the user's requested graph budget.

Input header (7 words): magic=0x4d524c32, operation(1 closure,2 provenance), fact_count,
rule_count, graph_limit, proof_limit, search_limit. Native capacities:64 facts,32 rules,
128 proof rows per fact. API graph/proof/search limits are positive signed int32 values.
Input fact (5 words): symbol_s,symbol_p,symbol_o,polarity(0/1),actual(0/1).
Input rules: all bodies (3 words each), then all heads (3 words each), matching previous layout.
Constant terms are nonnegative symbol IDs. Variables use -1,-2,-3, ordered by first encounter
in that rule's body. A head variable absent from the body is an unsafe rule (status3).
The adapter may reject unsupported input types or >3 variable slots before dispatch.

Output status word:0 success,1 closure graph_limit,3 unsafe_rule,4 unsupported subset,
5 malformed wire,6 native_capacity. Error statuses have no trailing payload.
Successful header following status (4 words):complete(0/1),reason(0 none,1 graph_limit,
2 proof_or_search_limit),searches,fact_count.
Each fact (7 words):s,p,o,selected_rule,selected_parent_fact,evidence_input_index,bundle_count.
Asserted facts have selected_rule=-1,selected_parent_fact=-1 and the selected input evidence
index (last duplicate for closure, first duplicate for provenance). Derived facts carry rule/
parent fact indexes and evidence_input_index=-1.
Each proof (8 words):asserted(0/1),rule_index,asserted_input_index,parent_fact_index,
parent_bundle_index,binding0,binding1,binding2. Unused fields/slots are -1.
Asserted proofs refer to their exact input record; derived proofs carry native-computed bindings.
The adapter decodes those slots using its rule variable-name table; it does not re-run matching.
All proof links are resolved lazily after every fact has been read; invalid links/cycles fail.

Parity rules within the admitted single-premise subset:
- Initial facts are filtered for actual positive assertions and explicit actual denials.
- Duplicate triples preserve multiple independent asserted supports in provenance.
- Provenance initial graph overflow returns ALL admitted initial facts and complete=false,
  reason=graph_limit, searches=0. Closure initial overflow returns status1.
- Candidate searches choose the smallest SINGLE constant-position bucket (ties by position),
  then run full binding; do not pre-filter the intersection of all constants before counting.
- Provenance increments searches including the budget-exceeding candidate. Closure has no
  search_limit counter budget; its own per-rule successful-match cap is graph_limit*4.
  The admitted unique-fact single-premise subset cannot reach that join cap before graph_limit.
- Snapshot facts per round, snapshot parent proof count/options for each rule match, preserve
  insertion order, and repeat when facts OR alternate proofs change.
- Returned metadata and input are never mutated; frozen fixtures never regenerated.

Admission restrictions must be explicit: one body triple, string fact terms, positive budgets,
unique string rule IDs and unique effective asserted support IDs. Repeated triples with distinct
support IDs ARE admitted. Repeated support IDs or repeated rule IDs are rejected before dispatch
because this initial native protocol uses input/rule indexes as semantic identity.
This limitation is documented, not silently normalized into the Python oracle's broader behavior.
No relation/graph frontend integration is claimed.

Reassigned ownership for final native fixes:
- backend worker: mrl/runtime/native_graph.c ONLY (C protocol, records, bounds, joins).
- golden worker: mrl/tests/test_native_graph.py, mrl/docs/NATIVE_GRAPH.md.
- coordinator: final mrl/native_graph.py integration and decoder validation.
- frontend worker: NEW mrl/tests/test_native_boundaries.py ONLY (adversarial/native parity checks).
All keep their current GPT-5.6 Terra model. No other files or main checkout edits.
