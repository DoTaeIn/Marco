# MRL isolated experiment: M0 bootstrap contract

Baseline: d5d91a21397fc5ac0d3ce0923d8756c867c85eca (cached origin/main, 2026-09-27).
Worktree: C:/Users/hirob/.codex/worktrees/mrl-runtime/Marco
Branch: codex/mrl-runtime-language
User authorizes separate MRL development and GPT-5.6 Terra parallel workers.
The supplied handoff is a design reference, not authority to change Marco main.
The earlier repository decision to defer MRL remains unchanged; this is the user's separate experiment.

## Isolation
Only mrl/ is writable for this experiment. All existing Marco files are read-only oracles.
No root checkout edits, fetch/pull, shared configuration changes, main merge, commit or push by workers.
No edits to engine.py, graph_inference.py, semantic_parser.py, relational_semantics.py or language assets.
Workers share this isolated checkout, with disjoint owned paths. Parent handles integration and reporting.

## First delivery (not completion of M1-M7)
Pin 5-10 structured closure/proof/provenance golden cases before implementing the graph slice.
Compile primitive .mrl source via lexer/parser/AST, checked backend-neutral IR, then C11.
This bootstrap accepts si/si32 and b, functions, parameters, calls, literals, declarations (=),
reassignment (:=), constants (dec), return, arithmetic (+ - *), comparisons and # paired comments #.
No C source may bypass IR. Unsupported planned features fail with a clear diagnostic.
Signed si32 overflow is checked at compile time for literal range and at runtime for arithmetic.
Arguments and binary operands evaluate left-to-right. Constants cannot be reassigned.
All non-void functions require an unconditional return in this straight-line bootstrap.
The grammar and full kernel in the supplied guide remain the v0.1 target, including .len property,
relation metadata, graph search, Result, Evidence and Proof; none is claimed implemented by this bootstrap.
This subset exists to test the compiler pipeline, not to redefine v0.1 as a primitive language.

## Shared neutral IR schema (Python JSON-compatible objects, v1)
Frontend owns parse(source) -> AST, lower(AST) -> dict; compile_source(source) -> dict combines them.
Every program is {"version":1,"functions":[FUNCTION,...]}.
FUNCTION is {"name":str,"params":[{"name":str,"type":"si32"|"b"},...],
             "return_type":"si32"|"b"|null,"body":[STMT,...]}.
All expressions have a canonical type field: si32, b, or null for a void call.
EXPR: {"kind":"literal","type":TYPE,"value":int|bool}
   or {"kind":"name","type":TYPE,"name":str}
   or {"kind":"binary","type":TYPE,"op":"+"|"-"|"*"|"=="|"!="|"<"|"<="|">"|">=","left":EXPR,"right":EXPR}
   or {"kind":"unary","type":TYPE,"op":"-","value":EXPR}
   or {"kind":"call","type":TYPE,"name":str,"args":[EXPR,...]}.
STMT: {"kind":"let","name":str,"type":TYPE,"mutable":bool,"value":EXPR}
   or {"kind":"assign","name":str,"value":EXPR}
   or {"kind":"return","value":EXPR|null}
   or {"kind":"expr","value":EXPR}.
Types are explicit IR fields, never inferred from C. Relation will require its own IR kind later.
No expression text is raw C. Backend validates incoming IR as a trust boundary.
The bootstrap entry point is fn main() -> si, required for executable emission.
C main prints that signed result followed by newline and exits 0 (not result modulo exit-code range).
Backend owns emit_c(ir) -> str in mrl/c_backend.py; CLI is python -m mrl SOURCE -o OUTPUT.c.
Frontend raises MrlError(ValueError); backend rejects malformed IR with ValueError.

## Worker ownership
- golden: mrl/oracle.py, mrl/tests/test_oracle.py, mrl/tests/fixtures/, mrl/docs/ORACLE.md
- frontend: mrl/frontend.py, mrl/tests/test_frontend.py, mrl/examples/, mrl/docs/FRONTEND.md
- backend: mrl/c_backend.py, mrl/__main__.py, mrl/tests/test_backend.py, mrl/docs/BACKEND.md
- parent: this contract, package markers, README, integration checks and milestone reports.

## Gates
Run Python stdlib unittest checks; native C smoke is required if an existing compiler is available.
Do not install toolchains or dependencies. If none exists, report native execution as unverified.
Golden equality tests validate the oracle snapshot; they are NOT evidence of MRL graph equivalence.
Report each milestone metric honestly (measured, unavailable, or pending). No performance claim yet.
Before broadening graph scope, require semantic equivalence and at least one measured advantage.
