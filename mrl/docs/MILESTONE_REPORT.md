# MRL first-day milestone evidence — 2026-09-27

This is an isolated bootstrap delivery, not completion of MRL v0.1.
Three GPT-5.6 Terra workers produced the golden oracle, frontend and C backend;
the coordinator reviewed and integrated them against the frozen bootstrap contract.

## Delivered and checked

- Isolated worktree `C:/Users/hirob/.codex/worktrees/mrl-runtime/Marco`, branch `codex/mrl-runtime-language`.
- Pinned baseline `d5d91a21397fc5ac0d3ce0923d8756c867c85eca`, the cached origin/main at creation.
- Ten frozen input/output cases for closure, proof, provenance alternatives, cycles and budget exhaustion.
  The baseline source and adapter are pinned by SHA-256 with LF normalization.
- Distinct AST, semantic/type checks, backend-neutral IR v1, and checked C11 emission.
- CLI compiles `mrl/examples/primitive.mrl` into C successfully. The intended native output is `42`.
- Full test run: **11 tests total, 10 passed, 1 skipped**, including 10 fixture subcases.
  Command: `python -B -m unittest discover -s mrl/tests -v`.
- Native test remains runnable. It is skipped because no complete C toolchain was found:
  Visual Studio's `cl.exe` exists, but Windows SDK C headers are absent; clang/gcc are absent from PATH.
  No native executable was built or run, so native overflow behavior is not yet verified here.
- Existing tracked Marco files have no diff in this worktree. New source/docs are confined to `mrl/`.
  The separate active checkout, its dirty work and the other agents' worktrees were not modified by this task.

## Measurements

See [machine-readable measurements](measurements.json) for environment, definitions and timing method.

| Required metric | Evidence / limitation |
|---|---|
| Semantic equivalence | Python oracle snapshots pass; MRL graph equivalence is pending |
| Source LOC | Primitive MRL example 6; illustrative equivalent Python functions 4; physical nonblank/non-comment lines, braces counted |
| Generated C LOC | 27 nonblank lines, informational; 1,247 UTF-8 bytes |
| Binary size | Unavailable: native build not verified |
| Static / peak RAM | Unmeasured |
| Startup | Unmeasured |
| Latency | About 0.102 ms median for warm Python source-to-C compilation only; native runtime latency unmeasured |
| Determinism | Repeated primitive IR/C emission matches; frozen Python oracle structures match; MRL graph pending |
| Proof equivalence | Oracle fixture comparisons pass; Python-to-MRL proof equivalence pending |
| Compile-time invariant catches | Literal range, names, constants, argument/assignment/return types, return discipline, unsupported syntax and malformed IR |

The primitive Python comparison does not include checked arithmetic and is not a graph benchmark.
The source-to-C timing used seven batches of 100 compilations, excluding Python startup, file I/O,
and native C compilation. It is not evidence of an inference speedup or embedded suitability.
No representative vertical-slice advantage is established yet.

## Next gates and ownership

1. Complete the C toolchain environment and run the existing native smoke/overflow test.
   Installing the Windows SDK or another compiler is outside this delivery; no installer was run.
2. Review full v0.1 grammar/IR/runtime semantics against the supplied guide. The bootstrap accepts
   only a primitive subset; it does not substitute a different language contract for the full kernel.
3. Implement the smallest bounded graph/proof slice against these pinned fixtures in this worktree.
   Graph handles, relation metadata, budgets, Evidence/Proof and Result failures must remain first-class.
4. Measure semantic/proof equivalence and an actual advantage before expanding the kernel.
   M3–M7, GC, C ABI, numeric arrays, collections and full control flow are still pending.

No main merge or remote push was performed. Changes remain reviewable in this branch's `mrl/` directory.
