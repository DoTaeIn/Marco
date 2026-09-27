# Handoff: MCO compile and the Marco language (MRL)

Written 2026-09-27 for the agent that takes over MCO compile and the Marco language.

## 0. Read this first: the freeze, and which tree is the truth

**The native MCO format is frozen.** `docs/ko/2026-09-22-freeze-decision.md` freezes the real `.mco` format, overlay, snapshot and consolidation (stages M1 to M4) until MARCO 1 ships. The `mco/` API shell "stays as is ... not extended". A goal that touches a frozen area stops and reports; it does not start. So sections 4 and 5 below are reference for later, not work to begin. The same file fixes two more rules you must follow: the frozen exams in `data/benchmarks/dialogues_v1/` and `reasoning_v1/` are scored only by the owner, once per round, and are never opened, run, or shown to any model.

**The local checkout was updated on 2026-09-28** and is now at `d5d91a2`, the same as `origin/main`. The table below describes the state before that update, kept to explain section 7.

**The truth is `origin/main` at commit `d5d91a2` (2026-09-26).** The local checkout at `C:/Users/hirob/Desktop/Marco` is on `main` at `6195040` (2026-09-22), which is **309 commits behind**, and carries uncommitted changes made against that old base.

| Tree | Commit | State |
| --- | --- | --- |
| `origin/main` | `d5d91a2` | Current. Contains the `mco` package, the `marco` package, understanding rounds 1 to 5, the trace ledger, the round 6 goal |
| local `main` | `6195040` + uncommitted | Stale. Do not use it as a reference for MCO |
| `codex/mrl-runtime-language` | `d5d91a2` | A worktree at `C:/Users/hirob/.codex/worktrees/mrl-runtime/Marco`, same commit as `origin/main` |

Everything in sections 1 to 3 below was read from `origin/main` with `git show`, without checking it out. Nothing was run on that tree for this handoff, so treat quoted numbers as "recorded upstream", not re-measured. Start your own work from `origin/main`.

Files on `origin/main` to read before anything else:

| File | Why |
| --- | --- |
| `docs/releases/2026-09-24-mco-0.1.0.md` | What shipped |
| `docs/mco/README.md`, `docs/mco/api.md` | User guide, stable API contract, how to write a backend |
| `mco/formats.py`, `mco/compiler.py`, `mco/backends/` | The three file forms and the two backends |
| `docs/ko/2026-09-25-profile-and-mrl-decision.md` | Where the time goes, and the decision on MRL |
| `docs/ko/2026-09-22-mco-integrated-roadmap.md` sections 2 to 4, 6 to 9, 11 | The native format plan, stages M1 to M4 and N1 |
| `README.md` | Gate status of MARCO 1 |

---

## 1. MCO: what already exists

`mco` 0.1.0 was published to PyPI on 2026-09-24 from the GitHub release `mco-v0.1.0`, by a trusted-publishing workflow that runs `tests/test_mco_package.py` before building.

| Part | What |
| --- | --- |
| `mco.load`, `Model.run`, `Model.session`, `Model.reason`, `Model.reset` | Open a model, one utterance, isolated conversations, a self-contained problem |
| `mco.inspect`, `ModelInfo` | Metadata without running anything |
| `mco.compile` | Build a `.mco` from a MARCO source tree or a `.kgpack` |
| `mco.benchmark` | Accuracy and latency on fixed cases |
| `Result` | `answer`, `status`, `evidence`, `trace` |
| `Status` values | `answered`, `observed`, `needs_input`, `unknown`, `rejected`, `pending_approval` |
| Errors | One hierarchy under `mco.MCOError`. Backend exceptions are wrapped |
| CLI | `compile`, `inspect`, `run`, `benchmark`, `backends`. Exit codes 0 to 3 |
| Backends | `marco-kgpack` runs a MARCO checkout. `mco-native` is a placeholder that recognises the native format and refuses it |

The names in `mco.__all__`, the `Result` fields, the `Status` values, the error classes, and the command line are the **stable surface, API version 1**. Do not break them.

### The three file forms (`mco/formats.py`)

| Form | What it is |
| --- | --- |
| `mco-compat`, container version 0 | What 0.1.0 writes. A deterministic ZIP with exactly two members: `mco.json` (the MCO manifest) and `payload.kgpack` (an unmodified MARCO pack). **It is not MCO Format 1** |
| `kgpack` | A bare MARCO pack, accepted directly |
| `mco-native` | The future binary format. Detected by a reserved magic prefix so loading fails with `UnsupportedFormatError` instead of a parse error |

Integrity checks in `mco/formats.py` re-implement the pack's size and SHA-256 rules on purpose, so `mco.inspect` works without the MARCO runtime installed.

### What 0.1.0 cannot do, in its own words

- **Run without MARCO.** The engine is not on PyPI. The only runnable backend imports it from a checkout, found through `marco_root=`, `MCO_MARCO_ROOT`, `sys.path`, or the checkout `mco` was installed from.
- **The native format.** Frozen until MARCO 1 passes its gate.
- **Structured facts.** `reason()` accepts `mco.Fact` objects, but the MARCO backend raises `UnsupportedInputError` for subject, predicate, value facts. Only sentences work.
- **Language is fixed at compile time.** English unless `mco compile --language styles/한국어.json`.
- **MARCO 1 has not passed its own gate.** The release note records 21 of 108 answerable turns on the frozen unseen dialogues. A later commit records 45 of 108 with 0 wrong after understanding round 5. The gate needs 90 percent.

Preview model recorded upstream: `MARCO-1-preview.mco`, 27,200,481 bytes, 905 graphs, English and Korean packs.

### So what is "MCO compile" work now

The compile command exists. What does not exist is **the native format behind it**. That is stages M1 to M4 in section 4, and it is frozen behind the MARCO 1 gate. Before starting it, confirm with the user whether the freeze is lifted. Work that is not blocked by the freeze:

- M1 specification text, fixtures for valid, truncated, corrupt, and version-mismatched files.
- Baseline measurements, with conditions written down before running.
- The speed fixes in section 2, which keep answers identical.

---

## 2. MRL: a decision was already made on 2026-09-25

From `docs/ko/2026-09-25-profile-and-mrl-decision.md`, measured on `ffedc8b` with the character encoder on an M-series laptop.

Dialogue gate, 52 dialogues, 340 turns, 241 s:

| Where | Seconds | Share |
| --- | --- | --- |
| `RelationalParser.parse` | 215 | 89 percent |
| parser build | 17.5 | 7 percent |
| graph routing | 5.5 | 2.3 percent |
| realizer, snapshot, understand | 13 | 5 percent |

Reasoning gate, 114 problems, 505 turns, 36.9 s: parser build 41 percent, parse 32 percent, routing 20 percent. Later turns have a median of 27 ms.

The reading recorded there:

- Steady state is already fast. No path search runs in the hot path. Routing is numpy.
- **The cost is combinatorial, not runtime speed.** Clause candidates times five variant kinds times every example template, recomputing the same variant literals about 74 times per sentence. A faster runtime makes each iteration cheaper and removes none of them.
- Parser build is dominated by recompiling the same 1,139 regexes.

### The decision

> MRL v0.1 (a general systems language: si/ui, GC, ptr, unsafe, FFI, modules, CSR graph store, BFS/Dijkstra) is **not built**.

Reasons given: speed is not the bottleneck, intelligence has moved only with declarations, and the embedded target is reached by compiling declarations to C tables plus a small C core. That C core is named NERO/C-core and is scheduled after the gate.

### What was kept: a small declaration language

To be designed after the evidence, unknown, retraction, and budget semantics. The sketch:

```text
relation gives { polarity: positive, evidence: required }
form en "{holder} has {n} {item}"        => has(holder, item, n)
rule  has(a,x,n) & gives(a,b,x,m)         => has(a,x,n-m), has(b,x,m)   requires: evidence(both)
say   en has(holder, item, n)             => "{holder} has {n} {item}."
test  en "Mina has 3 pens. She gives Tom 1. How many does Mina have?" => 2
```

The compiler is Python and emits **today's JSON first, engine unchanged**. C tables come later. Compile-time checks planned:

- every `say` parses back through a `form` to the same meaning
- rules on `evidence: required` relations must say `requires`
- `unknown` is not `none`, with a `say` for `unknown` per question kind
- inline tests must pass
- the declaration to Python line ratio is reported

**Go or no-go test recorded there:** write the three frozen-failure classes (zero and vague counts, non-name holders, referent repairs) in this syntax next to their JSON. Build it only if it is shorter **and** the parse-back check catches a real mismatch.

### What this means for the 12-point and kernel specifications

The user's later kernel specification (static fixed-width types, automatic memory plus unsafe, AOT, C FFI, graph traversal built in, IR with a C backend) describes the systems language that the 2026-09-25 note decided not to build. **Ask the user which one stands** before writing any compiler. If the systems language is reopened, these review points apply:

1. The control must be a compiled language. Against Python the experiment cannot fail.
2. Hand-write the slice in C or Rust first. That is the same C the language would emit, and it delivers the embedded path either way.
3. Try the language on paper before building a compiler.
4. Most "Marco native" features are enums and structs. The exception is `path != proof` checked at compile time.
5. The numeric block (arrays, ranking, quantized storage) is legitimate for the routing index only. Those vectors pick which graph to look at and never decide meaning.

### Speed fixes identified upstream, not yet done

1. Memoize variant literals and clause candidates per parser and literal.
2. A module-level unbounded compiled-regex cache. The parser is mutated, so share patterns, not parsers.
3. Cache the parser per model identity so restart and the realizer do not rebuild it.

Check: the answers file must diff empty against the round 6 run.

---

## 3. Constraints that do not move

- **No language model in the product runtime.** No generative model, no pretrained sentence encoder or text embedding, no translation API. Character and morpheme analysis is allowed.
- **Language knowledge is declared data**, not Python string branches and not an opaque blob.
- **The storage layer never decides meaning.**
- **No pickle and no executable payload** in a model file. Reading or inspecting must not run code.
- **Do not rebuild the engine.**
- **Performance never excuses a meaning error.**
- **Report unfavourable numbers.**
- **The frozen exam never leaves the machine.** Upstream commit `ffedc8b` records the data rule: synthetic practice sentences may come from external models, the frozen exam may not.

`encoder.py` has a character n-gram default and an optional neural path. Confirm which one a compiled model uses and make the manifest state it.

---

## 4. The native format plan (roadmap stages, frozen until the gate)

### Storage model

| Store | Contents | Rule |
| --- | --- | --- |
| `.mco` | Compiled knowledge, rules, language, axioms, schema, indexes | Immutable |
| model overlay | Approved knowledge, rules, concepts, retractions, history | Visible from the next read |
| candidate store | Pending, conflicting, rejected candidates | Never mixed into fact inference before approval |
| persona state | One subject's experiences, relations, preferences, goals | Separated per subject |
| session and task state | Current context, tasks, receipts | Lifetime stated |
| cache | Regenerable indexes | Losing it loses no meaning |

### M1. Specification

- Header: magic, format version, flags, table-of-contents offset and size, integrity fields, with sizes, byte order, ranges, and checksum coverage fixed.
- Chunks: type, version, required or optional, offset, length, raw length, compression, checksum. Rules for duplicates, empty chunks, overflow, overlap, references outside the file, and a decompressed-size ceiling.
- Tables: Node, Edge, String, Rule, Graph Directory, Index, Language.
- Unknown optional chunk: skip by verified length. Unknown required chunk, schema, or feature: reject explicitly.
- Exit: expected verdicts fixed for valid, truncated, corrupt, and version-mismatched files.

### M2. Compiler, runner, inspect

- Real tables, not compressed source text re-parsed at start.
- Small writer, file, reader, one query, inspect, end to end, then widen.
- Materialize only what the question needs.
- Compare source execution against native execution on meaning, effects, evidence, corrections.
- Exit: runs from one native file in a separate process with the source folder inaccessible.

### M3. Overlay

- One of SQLite transactions or framed JSONL. Not both.
- ADD NODE, ADD EDGE, ADD RULE, RETRACT EDGE, DISABLE RULE as versioned deltas.
- Base `A→B` plus overlay `B→C` infers `A→C` with evidence from both.
- Tombstones withdraw dependent conclusions and keep independently supported ones.
- Exit: a correction changes the answer immediately, base hash unchanged, recompile count zero.

### M4. Snapshot, consolidation, scaling

- Consolidation folds approved overlay into a new base, verifies, switches atomically.
- Scaling at 10, 50, 100, 250, 500, 1K, 5K, 10K graphs, recording nodes, edges, rules, string bytes, and what the query touched.
- Measure storage, memory, time, learning, maintenance, and correctness as separate axes. A warm page cache is not a cold start.
- Never lossy-compress meaning ids, quantities, or rules.

### N1. Native backend

Only for a measured bottleneck. NumPy on CPU is the baseline. A device that is not available gives "not measured".

### A lesson already in the repo (`kgbin.py` header)

| | npz | bin (uint8) |
| --- | --- | --- |
| File size | 17.73 MB | 8.75 MB |
| Index load | 291 ms | 53 ms |
| 400 questions | 3.1 s | 3.8 s |
| Peak memory | 144 MB | 148 MB |

The binary index saved file size and start time and **did not save memory**. The same header records that the first measurement showed zero loss because the code had not touched the arrays. A control was added: zeroing every value must drive hits to zero. Always prove the experiment can fail.

---

## 5. Decisions that are the user's

| Decision | Note |
| --- | --- |
| Is the native format freeze lifted | Upstream says frozen until MARCO 1 passes its gate |
| Systems language or declaration language | Upstream decided declaration language on 2026-09-25. The user later described a systems kernel |
| Overlay storage | SQLite or framed JSONL |
| Control language for any native slice | C, Rust, or Zig |
| Whether embedded is a real requirement | Upstream plans NERO/C-core after the gate |
| Encoder path in a shipped model | Character n-gram only, or neural allowed |

---

## 6. Environment notes for this Windows machine

```bash
PYTHONIOENCODING=utf-8 PYTHONPATH=. /c/Users/hirob/anaconda3/python.exe -m pytest <files> -q -p no:cacheprovider --basetemp=<writable dir>
```

The default pytest temp directory and `.pytest_cache` are not writable here. The system `python` has no pytest. Upstream measurements were taken on an M-series laptop, so timings will not match this machine.

---

## 7. The understanding change set, so you do not mistake it for main

An understanding change set (unknown-word guessing, dropped-particle reading, conversation-learned expressions) was first written against the stale local `main`, then ported onto `d5d91a2` on 2026-09-28. It lives on branch `understanding-u`, not on `main`. It did not change the frozen dialogue score. Do not build on it; build on `main`.
