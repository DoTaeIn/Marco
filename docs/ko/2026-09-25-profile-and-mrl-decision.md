# 2026-09-25 — Where marco's time goes, and the MRL decision

Measured on main ffedc8b, `KG_ENCODER=문자`, Python 3.13.9 (anaconda), M-series laptop.
Wall-clock instrumentation of the gate's in-process `run()`; cProfile was discarded
(it inflated the regex share ~3×). Frozen exams were timed, not scored.

## Reasoning gate — 114 problems, 505 turns, 36.9 s

| where | s | % |
|---|---|---|
| parser build (`RelationalParser.__init__`) | 15.0 | 41 — 244 builds × 62 ms, once per conversation/restart |
| `RelationalParser.parse` | 11.8 | 32 |
| graph routing `engine._pick_graph` | 7.5 | 20 — 28 ms/call, numpy |
| first turns (114) | 21.0 | 57 — median 306 ms |
| later turns (391) | 14.5 | 39 — **median 27 ms, p90 73 ms** |

## Dialogue gate — 52 dialogues, 340 turns, 241 s

| where | s | % |
|---|---|---|
| `RelationalParser.parse` | 215 | **89** |
| parser build | 17.5 | 7 |
| graph routing | 5.5 | 2.3 |
| realizer + snapshot + understand | 13 | 5 |

Tail: 66 turns (19 %) take 81 % of the time; slowest 6.2 s (ko-24 #5). Median turn 43 ms.

Inside `parse`: `_clause_meanings` 125,745 calls (74 per sentence, relational_semantics.py:2296);
`_variant_literals` 125,483 calls = 50 % of wall (relational_semantics.py:507);
42 M `re.compile` lookups = 13 % (5,258 distinct patterns vs Python's 512-entry cache);
`hangul.inflect` 6.9 M calls = 7 %.

## Reading

- Steady state is already fast (27–43 ms/turn). No BFS/path search runs in the hot path;
  routing is numpy.
- The cost is combinatorial: `_clause_candidates` × 5 variant kinds × every example template,
  recomputing the same `_variant_literals(literal)` ~74× per sentence. A faster runtime makes
  each iteration cheaper; it does not remove the iterations.
- Parser build is per-conversation setup dominated by recompiling the same 1,139 regexes.

## Speed fixes that keep answers identical (not yet done)

1. Memoize `_variant_literals` / `_clause_candidates` per (parser, literal).
2. Module-level unbounded compiled-regex cache (the parser is mutated at
   relational_semantics.py:2205/2238, so share patterns, not parsers).
3. Cache the parser per model identity so restart and the realizer do not rebuild it.

Check: the answers file must diff empty against the round-6 run.

## MRL decision

MRL v0.1 (a general systems language: si/ui, GC, ptr, unsafe, FFI, modules, CSR graph store,
BFS/Dijkstra) is **not built**. Speed is not the bottleneck, intelligence has moved only with
declarations, and the embedded target is reached by compiling declarations to C tables plus a
small C core (NERO/C-core, already scheduled after the gate).

Kept from the idea: a small **declaration language** for Marco packs, after the §29 semantics
(evidence, unknown, retraction, budget) are designed. Sketch:

```text
relation gives { polarity: positive, evidence: required }
form en "{holder} has {n} {item}"        => has(holder, item, n)
rule  has(a,x,n) & gives(a,b,x,m)         => has(a,x,n-m), has(b,x,m)   requires: evidence(both)
say   en has(holder, item, n)             => "{holder} has {n} {item}."
test  en "Mina has 3 pens. She gives Tom 1. How many does Mina have?" => 2
```

Compiler in Python emits today's JSON first (engine unchanged), C tables later. Compile-time
checks: every `say` parses back through a `form` to the same meaning (Palintrosemia); rules on
`evidence: required` relations must say `requires`; `unknown` ≠ `none`, with a `say` for
`unknown` per question kind (Aporrhemia); inline tests must pass; declaration-vs-Python line
ratio reported.

Go/no-go test: write the three frozen-failure classes (zero/vague counts, non-name holders,
referent repairs) in this syntax next to their JSON. Build it only if shorter *and* check 1
catches a real mismatch.
