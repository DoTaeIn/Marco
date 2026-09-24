> Reference document, written by the owner and moved out of the repository root on 2026-09-24. It names structural properties of MARCO; the ten pipeline names are in [pipeline-names.md](pipeline-names.md). The reader's article covering both is [docs/en/pipelines.md](../en/pipelines.md).

# MARCO Structural Concepts — Naming Proposal

> **Status:** Naming proposal / research terminology  
> **Date:** 2026-09-24  
> **Scope:** MARCO core architecture  
>
> These names are proposed terms for architectural properties that emerge from MARCO's design.
> They are intended as MARCO-specific terminology, not as claims that the underlying research idea is historically unprecedented.
>
> The purpose is to give stable names to mechanisms that are otherwise awkward to describe repeatedly in papers, architecture documents, and discussions.

---

# 1. Why name structural properties?

MARCO is not defined only by individual modules such as:

- graph routing,
- symbolic inference,
- language realization,
- abstention,
- correction,
- provenance.

Its more distinctive properties appear in how those modules are constrained to interact.

For example:

```text
reasoning result
→ language realization
→ sentence
→ semantic reconstruction
→ comparison with original meaning
→ speak or hold
```

This is more than a "realizer."

Likewise:

```text
no grounded meaning
→ no valid utterance path
```

is stronger than a confidence threshold.

The terms below name these higher-level architectural properties.

---

# 2. Palinorrhesis

> **Proposed MARCO term**  
> Constructed from `palin` ("again") + `rhesis` ("utterance / saying").  
> Intended sense: **an utterance must return through its meaning before it is allowed to leave the system.**

**Palinorrhesis** is the umbrella term for MARCO's speak-only-after-semantic-return architecture.

```text
             Proven Meaning
                   │
                   ▼
               Realizer
                   │
                   ▼
            Candidate Sentence
                   │
                   ▼
                Parser
                   │
                   ▼
        Reconstructed Meaning
                   │
            ┌──────┴──────┐
            │             │
          same        different
            │             │
            ▼             ▼
          SPEAK           HOLD
```

Palinorrhesis consists of two narrower concepts:

```text
Palinorrhesis
├─ Palintrosemia
└─ Aporrhemia
```

It names the whole architectural contract:

> **A candidate utterance is not trusted merely because the realizer produced it.  
> It must survive semantic reconstruction before it can be spoken.**

---

# 3. Palintrosemia

> **Proposed MARCO term**  
> Constructed from `palin` ("again") + `sema` ("sign / meaning").  
> Intended sense: **returning an expression to meaning and comparing it with the original meaning.**

**Palintrosemia** is the semantic round-trip constraint.

```text
Meaning M
    ↓
Realization
    ↓
Sentence S
    ↓
Parsing
    ↓
Meaning M'
    ↓
compare(M, M')
```

The important property is not merely that the grammar can parse its own output.

The important property is that semantic reconstruction is used as a **gate on the answer path**.

```text
M == M'
→ candidate utterance is semantically admissible

M != M'
→ candidate utterance is rejected
```

Typical failures caught by Palintrosemia may include:

- swapped semantic roles,
- changed quantities,
- dropped negation,
- changed ownership,
- omitted required relations,
- incorrect reference resolution.

Suggested paper phrasing:

> **Palintrosemia is MARCO's semantic-return constraint: every candidate utterance is reinterpreted and compared against the meaning from which it was realized.**

---

# 4. Aporrhemia

> **Proposed MARCO term**  
> Constructed around `rhema` / `rhesis`, referring to an utterance or what is said.  
> Intended sense: **the absence of a valid path from unsupported meaning to speech.**

**Aporrhemia** names MARCO's structural abstention property.

Typical AI abstention looks like:

```text
generate answer
    ↓
estimate confidence
    ↓
confidence too low?
    ↓
refuse
```

Aporrhemia is different:

```text
grounded meaning unavailable
        ↓
no semantically valid answer state
        ↓
no valid realization path
        ↓
HOLD / UNKNOWN
```

The key claim is:

> **Unsupported semantic content has no valid route to an utterance.**

This is not the same as training a model to say "I don't know."

It is an execution constraint.

Suggested paper phrasing:

> **Aporrhemia denotes structural abstention: when MARCO cannot establish a grounded meaning, the architecture provides no valid transition from reasoning to assertion.**

---

# 5. Relationship between Palinorrhesis, Palintrosemia, and Aporrhemia

These terms should not be used interchangeably.

## Palinorrhesis

The whole speak-after-semantic-return architecture.

## Palintrosemia

The mechanism that reconstructs and compares meaning.

## Aporrhemia

The structural consequence when an admissible grounded meaning cannot reach speech.

```text
                   Palinorrhesis
                         │
          ┌──────────────┴──────────────┐
          │                             │
          ▼                             ▼
    Palintrosemia                  Aporrhemia
 semantic return/check         structural abstention
```

A compact definition:

> **Palinorrhesis uses Palintrosemia to enforce Aporrhemia.**

---

# 6. Doxolysis

> **Proposed MARCO term**  
> Constructed from `doxa` ("belief / judgment") + `lysis` ("loosening / dissolution").  
> Intended sense: **the dissolution of a conclusion when its supporting evidence is withdrawn.**

**Doxolysis** names evidential retraction propagation.

Bad correction handling:

```text
old value = 5
new value = 3

overwrite:
value = 3
```

Doxolysis instead preserves history:

```text
Evidence A
    ↓
Conclusion B
    ↓
Derived Conclusion C

later:

Evidence A
    ↓
WITHDRAWN

therefore:

B loses valid support
C may also lose valid support
```

A correction does not merely replace a field.

It changes the validity of downstream reasoning.

Example:

```text
User:
"민수는 사과가 5개 있어."

Later:
"아니, 3개였어."
```

The older evidence should become:

```text
withdrawn
```

and every later answer that depended exclusively on the old value must cease to be reachable as an active conclusion.

Doxolysis therefore applies to:

- corrected facts,
- withdrawn evidence,
- revised beliefs,
- superseded mental states,
- invalidated proofs.

Suggested paper phrasing:

> **Doxolysis propagates evidential retraction through dependent reasoning rather than treating correction as destructive state overwrite.**

---

# 7. Polykrisis

> **Proposed term — collision / prior-use review recommended before canonization**  
> Constructed from `poly` ("many") + `krisis` ("judgment / discrimination").  
> Intended sense: **selection among multiple independently executable knowledge candidates by judging their actual grounded outcomes.**

**Polykrisis** names MARCO's multi-graph competition architecture.

A conventional retriever may do:

```text
question
→ similarity
→ top document / graph
→ answer
```

Polykrisis instead aims at:

```text
question
    ↓
many independent KG candidates
    ↓
cheap lexical / structural retrieval
    ↓
top-K candidate graphs
    ↓
execute / inspect reasoning in each candidate
    ↓
compare evidence quality / grounded verdicts
    ↓
select
```

The distinctive point is that the final winner need not be the candidate with the highest lexical score.

```text
Graph A
lexical score = 0.81
grounded result = none

Graph B
lexical score = 0.74
grounded result = supported

→ Graph B may win
```

Suggested paper phrasing:

> **Polykrisis separates candidate retrieval from candidate judgment: independently authored knowledge graphs compete not only by lexical fit but by the grounded reasoning they can actually support.**

Because `Polykrisis` is closer to an existing classical formation than the other coined terms, prior-use checks should be completed before treating it as canonical.

---

# 8. Noematic Sovereignty

> **Proposed MARCO principle**  
> `Noematic` refers to meaning/content as distinguished from its surface expression.  
> Intended sense: **the semantic structure, not the output sentence, holds epistemic authority.**

**Noematic Sovereignty** is not a pipeline.

It is an architectural principle.

```text
Surface Sentence ≠ Truth Source
```

The authority hierarchy is:

```text
Evidence / State / Rules
        ↓
      Meaning
        ↓
   Surface Language
```

not:

```text
Generated Sentence
        ↓
     treated as fact
```

Therefore:

> **The answer text has no epistemic authority merely because MARCO uttered it.**

A sentence is a projection of a meaning that was already established elsewhere.

This principle also explains why Palintrosemia matters:

```text
meaning is sovereign
→ sentence must be checked against meaning
→ sentence cannot silently change the conclusion
```

Suggested paper phrasing:

> **MARCO follows Noematic Sovereignty: epistemic authority remains with the grounded semantic state, while natural-language output is treated only as a checked projection of that state.**

---

# 9. Structural relationship

The proposed concepts relate as follows:

```text
Evidence / State / Rules
          │
          ▼
     Grounded Meaning
          │
          │  Noematic Sovereignty
          │
          ▼
     Palinorrhesis
          │
    ┌─────┴─────┐
    │           │
    ▼           ▼
Palintrosemia  Aporrhemia
    │           │
    └─────┬─────┘
          │
          ▼
   Safe Utterance / Hold
```

Correction operates alongside reasoning:

```text
Evidence
   │
   ▼
Conclusion
   │
   ▼
Derived state

Evidence withdrawn
   │
   ▼
Doxolysis
   │
   ▼
Dependent conclusions re-evaluated
```

Multi-graph reasoning may be described as:

```text
Graph candidates
      │
      ▼
   Polykrisis
      │
      ▼
Grounded winner
```

---

# 10. Recommended canonical set

The strongest candidates for MARCO-specific terminology are:

## 1. Palinorrhesis

The overall semantic-return-before-speech architecture.

## 2. Palintrosemia

Semantic reconstruction and equivalence checking.

## 3. Aporrhemia

Structural abstention caused by the absence of a valid grounded utterance path.

## 4. Doxolysis

Propagation of evidence withdrawal through dependent reasoning.

## 5. Noematic Sovereignty

The principle that meaning/evidence, not surface language, possesses epistemic authority.

Candidate requiring additional prior-use review:

## 6. Polykrisis

Execution-grounded competition among multiple independently authored knowledge graphs.

---

# 11. Distinguish terminology from novelty claims

These terms are names proposed for MARCO's architecture.

They do **not** by themselves imply:

```text
"MARCO invented semantic round-tripping."
```

or:

```text
"MARCO invented belief revision."
```

Those broader ideas have prior work.

The research claim, if later supported by a formal literature review, should instead concern the specific MARCO architecture and invariants.

For example:

> We call the complete speak-after-semantic-return mechanism **Palinorrhesis**.

This is a naming claim.

A stronger statement such as:

> MARCO is the first system to implement Palinorrhesis.

requires a separate systematic literature review and should not be inferred from the terminology alone.

---

# 12. Suggested terminology in a paper

Example:

> MARCO separates epistemic state from surface language under **Noematic Sovereignty**.  
> Candidate utterances pass through **Palinorrhesis**, in which **Palintrosemia** reconstructs their semantics before release. If no grounded semantic state can produce an admissible utterance, **Aporrhemia** forces abstention. Corrections are handled through **Doxolysis**, which withdraws dependent conclusions rather than merely overwriting the latest state.

For routing:

> Candidate knowledge graphs undergo **Polykrisis**, where retrieval scores nominate candidates but grounded execution decides among them.

---

# 13. Short glossary

```text
Palinorrhesis
    Speak only after semantic return.

Palintrosemia
    Reconstruct an utterance back into meaning and compare it.

Aporrhemia
    Unsupported meaning has no valid path to assertion.

Doxolysis
    Withdraw evidence and dissolve conclusions that depended on it.

Polykrisis
    Let multiple executable knowledge graphs compete by grounded outcome.

Noematic Sovereignty
    Meaning holds epistemic authority; language is only its checked projection.
```

---

# 14. Core formulation

The proposed MARCO formulation is:

> **Noematic Sovereignty determines what carries epistemic authority.  
> Palinorrhesis governs the route from meaning to utterance.  
> Palintrosemia verifies the return from utterance to meaning.  
> Aporrhemia blocks assertions that cannot complete that route.  
> Doxolysis removes conclusions whose evidential basis has been withdrawn.  
> Polykrisis lets competing knowledge structures be judged by what they can actually prove.**

A shorter version:

> **Meaning is sovereign.  
> Speech must return to meaning.  
> Unsupported speech has no path.  
> Retracted evidence dissolves its consequences.**
