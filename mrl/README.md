# MRL

MRL compiles checked source into standalone C11 executables. Python runs the
compiler and test tools; generated programs run without Python. This is an
experimental language implemented in the isolated `codex/mrl-runtime-language`
branch.

## Use

A checkout needs Python 3.10+ and a complete local C11 compiler. No Python
packages or global install are required. On Windows the private Zig toolchain
is used when present; otherwise compiler discovery checks Clang, GCC, and MSVC.

```powershell
python -B -m mrl check mrl/examples/primitive.mrl
python -B -m mrl build mrl/examples/primitive.mrl -o mrl/.build/primitive.exe
python -B -m mrl run mrl/examples/primitive.mrl
python -B -m mrl test
```

The original `python -m mrl SOURCE.mrl -o OUTPUT.c` form remains available.
`main() -> si` prints its result and exits successfully; runtime failures exit
with an error. Relative file paths resolve from the caller's working directory.
Build caches, generated binaries, and local backups are ignored by Git.

## Language and runtime

- Checked integer widths, f32/f64, booleans, strings, structs, unit enums,
  optional values, Result, short-circuit logic, branches, loops, and early exits.
- Managed strings and nested values, arrays, lists, maps with string or integer
  keys, record field mutation, collection iteration, and numeric kernels.
- Relative module imports with aliases and original source diagnostics.
- UTF-8 `read_text`/`write_text`, `argc`/`argv`, and a minimal `extern fn` boundary
  for numeric/boolean scalars and pointers inside explicit `unsafe` blocks.
- Graph mutation and bounded BFS/DFS/Dijkstra/A* searches, plus growing Horn
  knowledge, indexed queries, retained snapshots, and checkpoint/journal restart.
- Typed epistemic and interpretation states, candidate constraints, bounded
  provenance, withdraw/replace/supersede history, and historical fact access.

The [source-only application](examples/language_app/README.md) reads Unicode
input, derives and explains a fact, saves a checkpoint, commits a supersession,
and verifies both current and historical knowledge in a fresh process.

## Verification and contracts

- [231 passing tests](docs/LANGUAGE_VERIFICATION.json) and [test log](docs/LANGUAGE_TEST_LOG.txt)
- [Completion checklist](docs/LANGUAGE_COMPLETION_CHECKLIST.md)
- [Tooling and modules](docs/LANGUAGE_TOOLING.md)
- [Managed values](docs/LANGUAGE_VALUES.md) and [FFI](docs/LANGUAGE_FFI.md)
- [Startup measurements](docs/STARTUP_REPORT.md) and
  [knowledge growth measurements](docs/GROWTH_REPORT.md)
- [Design handoff guide](docs/MRL_BRANCH_HANDOFF_GUIDE.md)

Earlier delivery reports record their own subsets and measurements. The
completion checklist describes the current source-level acceptance coverage.
The active Marco checkout, inference engine, oracle, and frozen golden fixture
are preserved separately from this language work.

## Boundaries

Graph storage is bounded at 64 nodes and 256 edges. Inference, proof enumeration,
file input, and collections have explicit limits; incomplete results retain
status information. Retained snapshots can copy touched storage on mutation.
Initialization, input parsing, and arbitrary inference can still scale with the
amount of knowledge. No universal Python speedup or constant-time growth is
claimed.

Unsafe pointers require correct caller-managed lifetime and matching C ABI.
Callbacks, foreign managed aggregates, runtime rule editing, a package registry,
and self-hosting are outside the current implementation.
