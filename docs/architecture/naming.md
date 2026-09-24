# MARCO Canonical Naming

> **Status:** canonical terminology, revision 2 (2026-09-24)
> **Scope:** MARCO / SOMA / ALMA / POLO / NERO
> **Sources:** the owner's two proposals of 2026-09-24, the pipeline naming and the
> structural-concept naming, merged into one reference. The originals are in the git
> history of this file and of `structural-concepts.md`. The reader's article is
> `docs/en/pipelines.md`.
>
> Revision 2 corrects one thing in revision 1: the checked route from meaning to
> speech was described as a "realizer" and named Hermeneia. Hermeneia is now the
> realization step only. The whole route, speak only after the sentence has been
> reconstructed into its meaning, is **Palinorrhesis**, with **Palintrosemia** and
> **Aporrhemia** as its two parts. Five further structural names join the set.

---

## 1. Two kinds of names

MARCO has names for two different things.

**Pipeline names** denote processes: a stable conceptual boundary with an input
and an output. Ten are canonical, four reserved.

**Structural names** denote properties that emerge from how the processes are
constrained to interact: a contract, an invariant, or a principle. Six are
proposed, five canonical and one pending a prior-use check.

Both kinds are proper nouns, capitalised, drawn from classical Greek vocabulary
or constructed from it. They name concepts, not files. A module may move, a
class may disappear, the name stays.

A name is a naming claim, never a novelty claim. "MARCO calls its speak-after-
return contract Palinorrhesis" is a definition. "MARCO is the first system with
Palinorrhesis" needs a literature review and does not follow from the name.

## 2. Naming rules

1. **Concept before implementation.** Apodeixis does not mean `graph_inference.py`;
   it means the process by which explicit premises and evidence become a
   justified conclusion.
2. **Names survive refactoring.** `engine.py` may become `marco/reasoning/`;
   the term does not change.
3. **Names encode the philosophy:** observation is not automatically fact;
   uncertainty is not falsity; conclusions require evidence; meaning is distinct
   from language; knowledge admission is distinct from knowledge discovery;
   affect is derived, not injected; provenance is part of cognition.
4. **First mention gives both forms:** "Apodeixis, MARCO's evidence-bounded
   reasoning pipeline". After that, the name alone.
5. **Canonical names live at boundaries:** architecture documents, README
   diagrams, module docstrings, trace stage descriptions, papers. Not in
   function names. `# Apodeixis boundary: every candidate conclusion is grounded
   here.` is right; `def apodeixis_everything()` is wrong.
6. **No acronyms, no self-explaining compounds.** ProofPath, SensePath,
   VoicePath and GRAPS-style acronyms are rejected as canonical names; they may
   appear as informal explanations.

## 3. Pipeline vocabulary

| Name | Greek | Role | Input → output |
| --- | --- | --- | --- |
| **Aisthesis** | αἴσθησις | SOMA perception | raw signal → measurable observations |
| **Noesis** | νόησις | semantic apprehension | observations or language structure → entities, relations, events |
| **Diairesis** | διαίρεσις | query decomposition | one utterance → its explicit user queries |
| **Apodeixis** | ἀπόδειξις | evidence-bounded reasoning | premises + evidence + rules → justified conclusion |
| **Bouleusis** | βούλευσις | deliberation | goal → possible actions, subgoals, choice |
| **Zetesis** | ζήτησις | inquiry | knowledge gap → evidence-seeking research |
| **Katalepsis** | κατάληψις | knowledge admission | candidate → accepted knowledge, or not |
| **Hermeneia** | ἑρμηνεία | language realization | meaning → candidate sentence |
| **Hypomnema** | ὑπόμνημα | provenance ledger | events, causes, evidence, reasoning history |
| **Pathognosis** | pathos + gnosis | affect interpretation | events, cues, goals → affect hypothesis |

### Aisthesis

Raw signal → measurement → segment → entity candidate → relation → observation.
Pixels to edges, regions, tracked entities, spatial relations; a waveform to
energy, onsets, acoustic segments; sensor values to measurements and state
changes. Output goes into the Observation Graph with source, time, confidence,
operator and version, provenance, uncertainty. Aisthesis records what can be
observed. It does not understand the world, and nothing it emits is yet a fact.

### Noesis

Observation → entity hypothesis → relation → event → semantic structure. From
"entity 17 moved from A to B" it may hypothesise "entity 17 is a ball" or "the
movement is a transfer", given evidence. The same applies to text: characters and
clauses → meaning structure. Text is not the system's internal language; the
graph is. Aisthesis is perception; Noesis is apprehension.

### Diairesis

One utterance that asks several things → the explicit queries the user stated,
answered in order. It divides; it never adds. That is the line to Bouleusis:
Diairesis handles goals the user supplied, Bouleusis creates or evaluates
subgoals while solving one. User goals and generated goals must never become
indistinguishable.

### Apodeixis

Premises → evidence retrieval → rule application → alternative and
contradiction checks → conclusion. Keeps observed, reported, hypothesized,
inferred, assumed, verified, contradicted, withdrawn and unknown apart. Every
conclusion is traceable to its parents: evidence A, evidence B and rule R → rule
application → conclusion. MARCO does not merely output a conclusion; it performs
Apodeixis over explicit evidence, and every important conclusion has a
reconstructible evidential path. Replaces the informal names reasoning pipeline,
proof path, grounded inference, evidence reasoning.

### Bouleusis

Goal → requirements → possible actions → possible subgoals → preconditions →
choice. Apodeixis asks what follows from what is known; Bouleusis asks what to
attempt next. A generated subgoal records `origin = generated`, its parent goal
and its reason. Grows with POLO and later autonomous-goal work.

### Zetesis

Unknown → knowledge gap → research need → evidence acquisition → candidate
knowledge. Begins when Apodeixis or Bouleusis needs a premise that is not known.
Never mutates trusted knowledge; its output is a candidate with provenance that
must pass Katalepsis. Research fills a missing premise; MARCO still solves the
problem.

### Katalepsis

Candidate → source verification → conflict check → rule and policy checks →
approval where required → accepted knowledge in the graph or overlay. Separates
"I found something" from "MARCO now uses this". The mechanism behind the refusal
to turn retrieved text into truth.

### Hermeneia

Meaning → utterance intent → discourse plan → expression choice → grammar →
candidate sentence. Expresses an already established meaning and never invents
content to make a sentence sound better. Meaning ≠ language. The descriptive
term "language realization pipeline" may continue to appear. Hermeneia is the
outward half of speaking only; the candidate it produces is not yet an
utterance. The check and the release are Palinorrhesis (§5).

### Hypomnema

The append-only record of epistemically important events: source → observation
→ interpretation → reasoning → decision → mutation → output. Each event has
`event_id`, `trace_id`, `parent_ids[]` (a DAG, not a tree), `source`, `runtime`
and `epistemic_status`. Corrections are new events that supersede, never edits.
Storage may be JSONL, SQLite or the native container; the concept is the same.
Event ledger, trace DAG, why chain and provenance graph are views of Hypomnema.
MARCO should never have to say "I don't know why I thought that."

### Pathognosis

For ALMA's own state: event → goal relation → expectation → control → preference
and memory → appraisal → affect state → emotion concept. For another person:
observed cues → context → reported state → appraisal hypothesis → affect
hypothesis with evidence and confidence. Never collapses an inference into a
fact. Emotion state ≠ emotion word; affect is derived, not injected.

## 4. Reserved pipeline names

| Name | Greek | Candidate for | Use when |
| --- | --- | --- | --- |
| **Anamnesis** | ἀνάμνησις, recollection | memory reconstruction, episodic recall, reactivation | ALMA memory needs a stable boundary |
| **Metabole** | μεταβολή, change | explicit state-transition semantics, world-state mutation layer | — |
| **Metanoia** | μετάνοια, change of mind | belief revision, self-model revision, controlled self-modification | cautiously; strong historical associations |
| **Orexis** | ὄρεξις, striving | ALMA motivation, preference and desire, goal-directed drive; may sit beneath Pathognosis | — |

## 5. Structural vocabulary

| Name | Built from | Kind | One line |
| --- | --- | --- | --- |
| **Noematic Sovereignty** | noema, the meant content | principle | meaning holds epistemic authority; the sentence is its checked projection |
| **Palinorrhesis** | palin, again + rhesis, utterance | contract | speak only after the utterance has returned through its meaning |
| **Palintrosemia** | palin, again + sema, meaning | mechanism | reconstruct the sentence into meaning and compare with the original |
| **Aporrhemia** | a-, without + rhema, what is said | consequence | unsupported meaning has no valid path to assertion |
| **Doxolysis** | doxa, belief + lysis, dissolution | mechanism | withdrawn evidence dissolves the conclusions that rested on it |
| **Polykrisis** | poly, many + krisis, judgement | architecture | competing knowledge graphs are judged by grounded outcome, not by retrieval score. *Pending a prior-use check before canonical use.* |

### Noematic Sovereignty

The authority hierarchy is evidence, state and rules → meaning → surface
language, never generated sentence → treated as fact. The answer text has no
epistemic authority because MARCO uttered it; it is a projection of a meaning
established elsewhere. This is why Palintrosemia exists: if meaning is
sovereign, the sentence must be checked against it and cannot silently change
the conclusion.

### Palinorrhesis

```text
Proven meaning → Hermeneia → candidate sentence → parser → reconstructed meaning
                                           same → SPEAK        different → HOLD
```

The umbrella contract for speaking. A candidate is not trusted because the
realizer produced it; it must survive semantic reconstruction before it can
leave the system. Palinorrhesis uses Palintrosemia to enforce Aporrhemia.

### Palintrosemia

Meaning M → realization → sentence S → parsing → meaning M′ → compare(M, M′).
The property is not that the grammar can parse its own output; it is that the
comparison gates the answer path. M = M′ admits the sentence; M ≠ M′ rejects it.
Catches swapped roles, changed quantities, dropped negation, changed ownership,
omitted relations, wrong reference.

### Aporrhemia

Conventional abstention: generate → estimate confidence → too low → refuse.
Aporrhemia: grounded meaning unavailable → no valid answer state → no valid
realization path → hold or unknown. Unsupported content does not reach speech
because the route does not exist, not because a score was low. It is an
execution constraint, not a trained reply.

### Doxolysis

Evidence A → conclusion B → derived conclusion C. When A is withdrawn, B loses
its support and C may too; the history stays, with A marked withdrawn and B and
C no longer reachable as active conclusions. A correction changes the validity
of downstream reasoning; it is not a field overwrite. Applies to corrected
facts, withdrawn evidence, revised beliefs, superseded mental states,
invalidated proofs.

### Polykrisis

Question → many independent graph candidates → cheap lexical or structural
retrieval → top-K → execute or inspect reasoning in each → compare evidence
quality and grounded verdicts → select. The winner need not be the candidate
with the highest retrieval score: a graph at 0.74 with a grounded result beats
a graph at 0.81 with none. Retrieval nominates; grounded execution decides.

## 6. Relationships

```text
Evidence / State / Rules
          │
          ▼
    Grounded meaning  ─── Noematic Sovereignty
          │
          ▼
     Palinorrhesis
     ┌────┴────┐
Palintrosemia  Aporrhemia
     └────┬────┘
   speak or hold

Evidence withdrawn → Doxolysis → dependent conclusions re-evaluated
Graph candidates   → Polykrisis → grounded winner
```

Pipelines, the core chain:

```text
World → Aisthesis → Observation → Noesis → Meaning → Apodeixis → Conclusion
      → Hermeneia → candidate → Palinorrhesis → Utterance
```

Missing knowledge: Apodeixis → gap → Zetesis → candidate → Katalepsis →
knowledge → Apodeixis resumes. Action: goal → Bouleusis → subgoals and actions →
observation → Apodeixis. Affect: experience → Pathognosis → affect state. All of
it is recorded in Hypomnema.

## 7. System ownership

| System | Names |
| --- | --- |
| **SOMA** | Aisthesis |
| **MARCO** | Noesis, Diairesis, Apodeixis, Zetesis, Katalepsis, Hermeneia; the six structural names |
| **ALMA** | Pathognosis, memory-linked appraisal, personal-state interpretation |
| **POLO** | Bouleusis, action permission and execution boundaries |
| **NERO** | no name of its own: the compute layer executing what Apodeixis defines, on any backend, without changing a proof |
| **shared** | Hypomnema |

Conceptual boundaries only. No package layout is implied.

## 8. Recommended phrasing

Prefer "MARCO performs **Apodeixis** over explicit premises and evidence" to
"runs its reasoning function". "Missing premises trigger **Zetesis**; candidate
knowledge must pass **Katalepsis**" to "searches the web and learns it". "SOMA
transforms sensory streams through **Aisthesis** into the Observation Graph" to
"the vision model detects things". "ALMA derives affect through **Pathognosis**"
to "has an emotion classifier". "The meaning is expressed through **Hermeneia**
and released through **Palinorrhesis**" to "generates a sentence". "The
evidential history is retained in **Hypomnema**" to "we save logs".

For the structural set in one paragraph: MARCO separates epistemic state from
surface language under **Noematic Sovereignty**. Candidate utterances pass
through **Palinorrhesis**, in which **Palintrosemia** reconstructs their
semantics before release. If no grounded semantic state can produce an
admissible utterance, **Aporrhemia** forces abstention. Corrections are handled
through **Doxolysis**, which withdraws dependent conclusions rather than
overwriting the latest state. Candidate knowledge graphs undergo
**Polykrisis**, where retrieval nominates and grounded execution decides.

## 9. Glossary

```text
Aisthesis    sensing                     Noematic Sovereignty  meaning holds authority
Noesis       understanding               Palinorrhesis         speak only after semantic return
Diairesis    dividing                    Palintrosemia         reconstruct and compare
Apodeixis    demonstrating, proving      Aporrhemia            unsupported meaning has no path
Bouleusis    deliberating                Doxolysis             retraction dissolves consequences
Zetesis      investigating               Polykrisis            graphs judged by grounded outcome
Katalepsis   admitting as grasped
Hermeneia    expressing meaning
Hypomnema    recording why
Pathognosis  interpreting affect
```

## 10. Core formulation

> Aisthesis observes. Noesis apprehends. Apodeixis demonstrates. Bouleusis
> deliberates. Zetesis investigates. Katalepsis admits. Hermeneia speaks, and
> Palinorrhesis lets it. Pathognosis feels by inference. Hypomnema remembers why.

> Meaning is sovereign. Speech must return to meaning. Unsupported speech has no
> path. Retracted evidence dissolves its consequences.
