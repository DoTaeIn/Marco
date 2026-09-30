# Sixth delivery: bounded source Horn bridge

`closure(Horn(facts = Facts(Fact(...)), rules = Rules(Rule(...))))` and
`closure_with_provenance(...)` are literal-only source builtins. They lower to one
`horn_query` IR node and the generated executable runs the existing bounded C engine
on first evaluation. Python never evaluates closure or proofs for generated programs.

The admitted subset is one body triple, up to three variables, 64 input facts, 32
rules, 128 proof rows per fact, positive int32 budgets, and literal string terms.
`Evidence(source, start, end, text)` validates the scalar span. Rules accept an
optional string/int32 `version`; facts accept optional `polarity` and `modality`.
Plans cannot be named or reused in source yet.

`horn_query` has exact fields `kind`, `type`, `operation`, `plan`, `limit`,
`proof_limit`, `search_limit`, and `target`. `validate_query` independently checks
this IR before C emission. C retains per-query static wire/output storage and prints
the same structured closure/provenance JSON as the native adapter, including support
IDs, rule versions, bindings, and parent proof IDs. Closure target selection remains
Proof behavior; it is unrelated to `Path`. A source target absent from the native
result retains its `known` records but prints `complete: false`, `reason:
"target_not_found"`, and counts because the legacy adapter/oracle raise `KeyError`
for that case. `MrlHornResult` also exposes `mrl_horn_reason_name`: native status,
then missing target, then incomplete native reason, then `Complete`.
