# MRL second delivery — 2026-09-28

The user asked to continue all three workstreams with the existing GPT-5.6 Terra agents.
This delivery supersedes first-day restrictions only where explicitly stated below.
Keep every write in this isolated worktree's mrl/ subtree. Existing Marco sources stay read-only.
No root checkout edits, branch changes, commits, pushes, global installations, PATH or registry edits.

## Ownership and deliverables

- frontend: mrl/frontend.py, mrl/tests/test_frontend.py, mrl/examples/control_flow.mrl,
  mrl/docs/FRONTEND.md. Add typed if/else, while and for ranges. Preserve existing checks.
- backend: mrl/c_backend.py, mrl/toolchain.py, mrl/tests/test_backend.py, mrl/docs/BACKEND.md,
  mrl/.tools/. Complete local C execution and implement control-flow IR emission/validation.
- graph/golden: mrl/runtime/, mrl/native_graph.py, mrl/tests/test_native_graph.py,
  mrl/docs/NATIVE_GRAPH.md. Build actual native bounded Horn inference and compare to frozen fixtures.
  Existing mrl/oracle.py and frozen fixtures are READ-ONLY this round; never regenerate expected output.
- coordinator: contract, integration tests, README, reports, .gitignore and review fixes after workers finish.

## Local toolchain boundary

First reuse an installed complete compiler. If none is available, the backend worker may obtain an
unmodified portable C compiler from its official source into ignored mrl/.tools/, verifying published
checksums where available. This is scoped build support for the user's requested next milestone.
No machine-wide installer, admin setup, shared PATH edit or modification to existing Visual Studio.
Native build outputs/caches belong in temporary directories or ignored mrl/.tools/.

Shared toolchain API owned by backend: mrl.toolchain.find_compiler() -> (command, uses_cmd),
where command is a list of executable/arguments for a direct compiler, a command prefix string for
MSVC child environment, or None if unavailable; uses_cmd is bool. Existing test helpers can delegate.
mrl.toolchain.build_c(c_file: Path, exe: Path) -> None discovers the toolchain, compiles C11, and raises
RuntimeError if no toolchain, subprocess.CalledProcessError on compiler failure. All artifacts stay by
c_file inside a temporary/build directory. Tests check availability and must not mistake build failure
for an unavailable toolchain. Keep bounded timeouts for builds and native test executions.

## IR v2 extension for control flow

Frontend emits version 2 for all programs. Backend accepts existing version 1 for old straight-line IR,
and version 2 with these additional statements. Program/functions/expressions otherwise unchanged.

- {"kind":"if", "condition":EXPR, "then":[STMT,...], "else":[STMT,...]}
- {"kind":"while", "condition":EXPR, "body":[STMT,...]}
- {"kind":"for", "name":str, "start":EXPR, "stop":EXPR, "body":[STMT,...]}

Syntax: if (condition) { ... } else { ... }; while (condition) { ... };
for (i in start..stop) { ... }. Semicolons here separate examples, not source syntax.
Conditions require b. Range bounds require si32, evaluate start then stop ONCE, and are half-open.
An empty/descending range executes zero times. The scoped induction variable is immutable si32.
Block-local declarations do not escape; assigning existing mutable outer variables persists.
No shadowing of visible names; distinct sibling blocks may independently use the same local name.
A while condition is reevaluated each iteration, with expression temporaries scoped correctly.
A block definitely returns if it reaches return, or an if with both branches definitely returning.
Loops are never assumed to return. Reject statements after a definitely-returning statement;
non-void functions must definitely return. No break/continue this round.

Struct/enum/collections/Result and the full graph language surface remain follow-on work; do not
claim this control-flow increment completes M1. Existing syntax is preserved, not redesigned.

## Native graph slice boundary

Implement real runtime computation from fixture INPUTS in C, not Python oracle evaluation printed by C.
Python may intern symbols, marshal input, and decode output. It must not perform closure/proof inference.
Prioritize all existing 10 golden cases; explicitly report any unsupported semantics without faking passes.
Validate capacities and budgets, preserve proof order and provenance structure. Define C fact/rule/proof
records and statuses, not text flags as the semantic implementation. Preserve oracle quirks in this
compatibility adapter and document any future language contract differences separately.
This native runtime is a building block: until relation/graph syntax and IR are wired through the MRL
frontend, do not label standalone C fixture parity as end-to-end .mrl graph language completion.

## Verification

Run existing and new stdlib checks; native test must compile/run when toolchain exists.
Measure native bytes/timing if obtained, separate graph parity from compiler parity, and retain the
no-scope-expansion-without-actual-benefit gate. Coordinator will record exact pass/skip counts.
