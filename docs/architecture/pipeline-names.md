> Reference document, written by the owner. The article that explains these names to readers, with what each pipeline is today, is [docs/en/pipelines.md](../en/pipelines.md).

# MARCO Canonical Pipeline Naming

> **Status:** Naming convention / terminology proposal  
> **Date:** 2026-09-24  
> **Scope:** MARCO / SOMA / ALMA / POLO  
>
> This document defines canonical names for major reasoning, perception, language,
> cognition, affect, research, and provenance pipelines in the MARCO family.
>
> The names are intentionally drawn from classical Greek philosophical vocabulary.
> They are not abbreviations of implementation details. Each name denotes a stable
> conceptual boundary that may survive internal refactors.

---

# 1. Why name the pipelines?

MARCO is no longer a single input → answer path.

The system contains several distinct processes:

- sensory measurement,
- semantic apprehension,
- query decomposition,
- evidence-bounded reasoning,
- deliberation,
- research,
- knowledge admission,
- language realization,
- affect interpretation,
- provenance recording.

If these processes are referred to only by implementation names such as:

```text
router
parser
reasoner
realizer
logger
research loop
```

then architecture discussions become tied to current files and modules.

The goal of this naming system is to give each major conceptual process a
stable name independent of implementation.

A module may move.

A class may disappear.

A pipeline name should remain.

---

# 2. Naming principle

The terminology should satisfy four rules.

## 2.1 Concept before implementation

A canonical name represents a conceptual process, not a file.

For example:

```text
Apodeixis
```

does not mean `graph_inference.py`.

It means the process by which explicit premises and evidence are transformed
into a justified conclusion.

---

## 2.2 Names should survive refactoring

The implementation may change from:

```text
engine.py
```

to:

```text
marco/reasoning/
```

without changing the architectural term.

---

## 2.3 Names should encode philosophy

The terminology should reflect MARCO's core principles:

- observation is not automatically fact,
- uncertainty is not falsity,
- conclusions require evidence,
- meaning is distinct from language,
- knowledge admission is distinct from knowledge discovery,
- affect is derived rather than injected,
- provenance is part of cognition rather than an afterthought.

---

## 2.4 Canonical names are proper nouns

When used as architectural terms, capitalize them:

```text
Aisthesis
Noesis
Diairesis
Apodeixis
Bouleusis
Zetesis
Katalepsis
Hermeneia
Hypomnema
Pathognosis
```

Do not reduce them to opaque acronyms unless required in diagrams.

---

# 3. Canonical vocabulary

| Canonical name | Role | Plain technical description |
| --- | --- | --- |
| **Aisthesis** | SOMA perception | Raw sensory input → measurable observations |
| **Noesis** | Semantic apprehension | Observations / language structures → meaning-bearing entities, relations and events |
| **Diairesis** | Query decomposition | One utterance → multiple explicit user queries / goals |
| **Apodeixis** | MARCO reasoning | Premises + evidence + rules → justified conclusion |
| **Bouleusis** | Deliberation | Goal → possible actions / subgoals / choices |
| **Zetesis** | Inquiry | Knowledge gap → evidence-seeking research |
| **Katalepsis** | Knowledge admission | Candidate knowledge → verified / accepted knowledge |
| **Hermeneia** | Language realization | Meaning → communicable natural-language expression |
| **Hypomnema** | Provenance ledger | Events, causes, evidence and reasoning history |
| **Pathognosis** | Affect interpretation | Events / cues / goals → affect or emotion hypothesis |

---

# 4. Aisthesis

> Greek: **αἴσθησις**  
> Approximate sense: sensation, perception, sensory apprehension.

**Aisthesis** is the canonical name for the SOMA sensory pipeline.

It converts raw signals into reproducible observations without requiring those
observations to already have linguistic names.

```text
RAW SIGNAL
    ↓
MEASUREMENT
    ↓
SEGMENT
    ↓
ENTITY CANDIDATE
    ↓
RELATION
    ↓
OBSERVATION
```

Examples:

```text
pixels
→ edges
→ regions
→ tracked entity
→ spatial relation
```

```text
waveform
→ energy / frequency / onset
→ acoustic segment
→ temporal relation
```

```text
sensor values
→ measurements
→ state changes
```

Aisthesis should not be described as "understanding the world."

Its responsibility is narrower:

> **Aisthesis records what can be observed.**

The output of Aisthesis belongs in an Observation Graph and should preserve:

- source,
- time,
- confidence,
- operator/version,
- provenance,
- uncertainty.

---

# 5. Noesis

> Greek: **νόησις**  
> Approximate sense: apprehension by intellect, understanding, cognition.

**Noesis** transforms observations or parsed language structures into
meaning-bearing structures.

```text
Observation
    ↓
Entity hypothesis
    ↓
Relation
    ↓
Event
    ↓
Semantic structure
```

Aisthesis may know that:

```text
entity_17 moved from A to B
```

Noesis may form the higher-level hypothesis that:

```text
entity_17 is a ball
```

or:

```text
the movement constitutes a transfer event
```

depending on available evidence.

Noesis is therefore intentionally distinct from Aisthesis.

```text
Aisthesis = perception
Noesis    = semantic apprehension
```

The same distinction may also apply to text:

```text
characters / clauses
→ Noesis
→ meaning structure
```

Text is therefore not privileged as the system's internal language.

---

# 6. Diairesis

> Greek: **διαίρεσις**  
> Approximate sense: division, separation, conceptual partition.

**Diairesis** is the canonical name for multi-query decomposition.

Example:

```text
"TCP가 뭐고 UDP는 뭐야? 둘의 차이도 알려줘."
```

becomes:

```text
Query 1: What is TCP?
Query 2: What is UDP?
Query 3: How do they differ?
```

Diairesis preserves user-stated goals.

It must not be confused with autonomous subgoal generation.

```text
Diairesis:
    user already supplied several goals

Bouleusis:
    the system creates or evaluates subgoals while solving a goal
```

This distinction is important for agency and traceability.

---

# 7. Apodeixis

> Greek: **ἀπόδειξις**  
> Approximate sense: demonstration, proof, reasoned showing.

**Apodeixis** is the canonical name for MARCO's evidence-bounded reasoning process.

This is the central MARCO pipeline.

```text
Premises
    ↓
Evidence retrieval
    ↓
Rule application
    ↓
Alternative / contradiction checks
    ↓
Conclusion
```

Apodeixis must preserve the distinction between:

```text
observed
reported
hypothesized
inferred
verified
contradicted
withdrawn
unknown
```

A conclusion produced by Apodeixis should be traceable to its parents.

```text
Evidence A ─┐
Evidence B ─┼→ Rule Application → Conclusion
Rule R ─────┘
```

The architectural principle is:

> **MARCO does not merely output a conclusion.  
> MARCO performs Apodeixis over explicit evidence.**

The stronger design rule is:

> **Every important conclusion should have a reconstructible evidential path.**

Apodeixis is the preferred name for the pipeline previously described informally as:

- reasoning pipeline,
- proof path,
- grounded inference,
- evidence reasoning.

---

# 8. Bouleusis

> Greek: **βούλευσις**  
> Approximate sense: deliberation, counsel, consideration of what to do.

**Bouleusis** is the canonical name for goal-directed deliberation.

```text
Goal
    ↓
Requirements
    ↓
Possible actions
    ↓
Possible subgoals
    ↓
Preconditions
    ↓
Choice
```

Bouleusis is not the same as Apodeixis.

```text
Apodeixis:
    What follows from what is known?

Bouleusis:
    What should be attempted next to satisfy the goal?
```

Bouleusis is expected to become increasingly important in POLO and later
autonomous-goal work.

Generated subgoals should record:

```text
origin = generated
parent_goal = ...
reason = ...
```

so that system-created goals never become indistinguishable from user goals.

---

# 9. Zetesis

> Greek: **ζήτησις**  
> Approximate sense: inquiry, investigation, search.

**Zetesis** begins when Apodeixis or Bouleusis identifies a required premise
that is not currently known.

```text
Unknown
    ↓
Knowledge gap
    ↓
Research need
    ↓
Evidence acquisition
    ↓
Candidate knowledge
```

Example:

```text
Original question
    ↓
required premise missing
    ↓
Zetesis
    ↓
external evidence found
```

Zetesis should not directly mutate trusted knowledge.

Its output is a candidate supported by provenance.

That candidate must pass through Katalepsis before becoming accepted knowledge.

---

# 10. Katalepsis

> Greek: **κατάληψις**  
> Approximate sense: apprehension, grasp, cognition accepted as secure.

**Katalepsis** is the knowledge-admission boundary.

```text
Candidate knowledge
    ↓
Source verification
    ↓
Conflict checking
    ↓
Rule / policy checks
    ↓
Approval when required
    ↓
Accepted knowledge
```

This separates:

```text
"I found something"
```

from:

```text
"MARCO now accepts this as usable knowledge"
```

Therefore:

```text
Zetesis
    ↓
Knowledge Candidate
    ↓
Katalepsis
    ↓
Knowledge Graph / Overlay
```

This distinction is essential for preserving MARCO's refusal to silently turn
retrieved text into truth.

---

# 11. Hermeneia

> Greek: **ἑρμηνεία**  
> Approximate sense: interpretation, expression, articulation.

**Hermeneia** is the canonical architectural name for MARCO's language
realization process.

The existing technical pipeline remains:

```text
Meaning
    ↓
Utterance Intent
    ↓
Discourse Planner
    ↓
Expression Selector
    ↓
Grammar Realizer
    ↓
Semantic Check
    ↓
Utterance
```

The descriptive technical term **Language Realization Pipeline** may continue to
appear in documentation.

The canonical architectural name is:

> **Hermeneia**

The important design principle is:

```text
Meaning ≠ Language
```

Hermeneia expresses an already-established meaning.

It must not invent new semantic content merely to make a sentence sound better.

---

# 12. Hypomnema

> Greek: **ὑπόμνημα**  
> Approximate sense: record, memorandum, written reminder.

**Hypomnema** is the canonical name for the MARCO-family provenance and event
history system.

It contains the append-only record of epistemically important events.

```text
SOURCE
    ↓
OBSERVATION
    ↓
INTERPRETATION
    ↓
REASONING
    ↓
DECISION
    ↓
MUTATION
    ↓
OUTPUT
```

The storage representation may be:

- JSONL,
- SQLite,
- MCO-native storage,
- another future backend.

The canonical concept remains Hypomnema.

Internally it may expose:

```text
Event Ledger
Trace DAG
Why Chain
Provenance Graph
```

but those are data structures and views of Hypomnema, not separate philosophies.

Core identifiers should include:

```text
event_id
trace_id
parent_ids[]
source
runtime/build
epistemic_status
```

The design principle is:

> **MARCO should never have to say:  
> "I don't know why I thought that."**

---

# 13. Pathognosis

> Constructed from Greek **pathos** (affect, passion, experience) and **gnosis** (knowledge).  
> Intended sense: cognition or interpretation of affect.

**Pathognosis** is the canonical name for ALMA's affect interpretation process.

For ALMA's own state:

```text
Event
    ↓
Goal relation
    ↓
Expectation
    ↓
Control
    ↓
Preference / memory
    ↓
Appraisal
    ↓
Affect state
    ↓
Emotion concept
```

For another person's state:

```text
Observed cues
    ↓
Context
    ↓
Reported state
    ↓
Appraisal hypothesis
    ↓
Affect hypothesis
```

Pathognosis must never collapse an uncertain inference into a fact.

For example:

```text
person_A is angry
```

should normally be represented as:

```text
hypothesis:
    affect = frustration-like
    evidence = [...]
    confidence = ...
```

unless the system has a stronger source, such as the person's own report.

The architectural principle is:

```text
Emotion State ≠ Emotion Word
```

and:

```text
Affect is derived, not injected.
```

---

# 14. Full architecture vocabulary

A high-level conceptual flow may be written as:

```text
                         WORLD
                           │
                           ▼
                      AISthesis
                   sensory perception
                           │
                           ▼
                  Observation Graph
                           │
                           ▼
                        Noesis
                semantic apprehension
                           │
                 ┌─────────┴─────────┐
                 │                   │
                 ▼                   ▼
             Diairesis           Apodeixis
        query decomposition        reasoning
                 │                   │
                 └─────────┬─────────┘
                           ▼
                       Bouleusis
                      deliberation
                           │
                 ┌─────────┴─────────┐
                 ▼                   ▼
              Zetesis              Action
              inquiry
                 │
                 ▼
             Katalepsis
         knowledge admission
                 │
                 ▼
            Knowledge Graph


              Meaning / Intention
                       │
                       ▼
                   Hermeneia
                       │
                       ▼
                    Utterance


        Epistemically relevant events
                       │
                       ▼
                   Hypomnema
              provenance / history
```

For affective cognition:

```text
Experience / Event / Cue
          │
          ▼
     Pathognosis
          │
          ▼
    Appraisal / Affect
```

---

# 15. System ownership

Suggested responsibility boundaries:

| System | Canonical processes |
| --- | --- |
| **SOMA** | Aisthesis |
| **MARCO** | Noesis, Diairesis, Apodeixis, Zetesis, Katalepsis, Hermeneia |
| **ALMA** | Pathognosis, memory-linked appraisal, personal-state interpretation |
| **POLO** | Bouleusis, action permission / execution boundaries |
| **Shared infrastructure** | Hypomnema |

These boundaries are conceptual and may evolve.

No package layout is implied by this table.

---

# 16. Recommended terminology in papers

Prefer:

> MARCO performs **Apodeixis** over explicit premises and evidence.

Instead of:

> MARCO runs its reasoning function.

Prefer:

> Missing premises trigger **Zetesis**, while candidate knowledge must pass
> **Katalepsis** before admission.

Instead of:

> MARCO searches the web and learns it.

Prefer:

> SOMA transforms raw sensory streams through **Aisthesis** into the
> Observation Graph.

Instead of:

> The vision model detects things.

Prefer:

> ALMA derives affect through **Pathognosis** rather than accepting emotion
> labels as facts.

Instead of:

> ALMA has an emotion classifier.

Prefer:

> The final meaning is expressed through **Hermeneia** and checked against the
> intended semantics.

Instead of:

> MARCO generates a sentence.

Prefer:

> The full evidential history is retained in **Hypomnema**.

Instead of:

> We save debug logs.

---

# 17. Recommended terminology in code comments

Canonical names should appear at architectural boundaries, not everywhere.

Good:

```python
# Apodeixis boundary: all candidate conclusions must be grounded here.
```

Good:

```python
# Aisthesis emits observations, never verified world facts.
```

Good:

```python
# Katalepsis decides whether this research candidate may enter the overlay.
```

Avoid:

```python
def apodeixis_everything_everywhere():
    ...
```

Implementation names should remain readable.

The canonical terminology belongs primarily in:

- architecture documents,
- README diagrams,
- module docstrings,
- trace stage descriptions,
- papers,
- design discussions.

---

# 18. Canonical vs descriptive names

Both forms may coexist.

Example:

```text
Canonical: Apodeixis
Descriptive: evidence-bounded reasoning pipeline
```

```text
Canonical: Aisthesis
Descriptive: sensory observation pipeline
```

```text
Canonical: Hermeneia
Descriptive: language realization pipeline
```

First mention in formal writing should generally use both:

> **Apodeixis**, MARCO's evidence-bounded reasoning pipeline, ...

After that:

> Apodeixis ...

This gives readers exactly one chance to understand the term.

After that, they are on their own.

---

# 19. Terms intentionally not used

## ProofPath / SensePath / VoicePath

Rejected as canonical names because they are too easy to infer from the name.

They may be acceptable as informal explanations, but not as official
architecture terminology.

---

## Perception Pipeline / Reasoning Pipeline / Research Loop

Useful descriptive labels, but too generic to function as stable names.

Use them only as explanations of the canonical terms.

---

## Acronym-heavy names

Avoid names invented primarily to produce attractive acronyms.

Example:

```text
Grounded Reasoning and Proof System = GRAPS
```

is discouraged.

The MARCO naming system should look like a philosophical vocabulary, not a
corporate framework taxonomy.

---

# 20. Reserved future terms

The following names may be useful later but are not yet assigned as canonical
pipeline names.

## Anamnesis

> **ἀνάμνησις** — recollection, remembrance.

Candidate for:

- memory reconstruction,
- episodic recall,
- reactivation of prior knowledge.

Do not use until ALMA memory architecture requires a stable named boundary.

---

## Metabole

> **μεταβολή** — change, transition.

Candidate for:

- explicit state-transition semantics,
- world-state mutation layer.

---

## Metanoia

> **μετάνοια** — change of mind, transformation of understanding.

Candidate for:

- belief revision,
- major self-model revision,
- later controlled self-modification.

Use cautiously because of its strong historical/religious associations.

---

## Orexis

> **ὄρεξις** — desire, appetite, striving.

Candidate for:

- ALMA motivation,
- preference / desire layer,
- goal-directed drive.

Could later sit below Pathognosis:

```text
Orexis
  ↓
Appraisal
  ↓
Pathognosis
```

---

# 21. Short glossary

```text
Aisthesis   = sensing
Noesis      = understanding
Diairesis   = dividing
Apodeixis   = demonstrating / proving
Bouleusis   = deliberating
Zetesis     = investigating
Katalepsis  = admitting as sufficiently grasped
Hermeneia   = expressing meaning
Hypomnema   = recording the epistemic history
Pathognosis = interpreting affect
```

This glossary is for maintainers.

It does not need to appear next to every use in the paper.

---

# 22. Core chain

The most important MARCO-family chain is:

```text
Aisthesis
    ↓
Noesis
    ↓
Apodeixis
    ↓
Hermeneia
```

Expanded:

```text
World
 ↓
Aisthesis
 ↓
Observation
 ↓
Noesis
 ↓
Meaning
 ↓
Apodeixis
 ↓
Conclusion
 ↓
Hermeneia
 ↓
Utterance
```

When knowledge is missing:

```text
Apodeixis
    ↓
Knowledge Gap
    ↓
Zetesis
    ↓
Candidate
    ↓
Katalepsis
    ↓
Knowledge
    ↓
Apodeixis resumes
```

When action is required:

```text
Goal
 ↓
Bouleusis
 ↓
Subgoals / Actions
 ↓
Observation
 ↓
Apodeixis
```

When affect is involved:

```text
Experience
 ↓
Pathognosis
 ↓
Affect State
```

And all of it is recorded in:

```text
Hypomnema
```

---

# 23. Canonical naming decision

The following terms are recommended as the official MARCO-family architectural vocabulary:

1. **Aisthesis** — sensory perception
2. **Noesis** — semantic apprehension
3. **Diairesis** — query decomposition
4. **Apodeixis** — evidence-bounded reasoning
5. **Bouleusis** — deliberation and goal-directed planning
6. **Zetesis** — knowledge-gap inquiry
7. **Katalepsis** — knowledge admission
8. **Hermeneia** — language realization
9. **Hypomnema** — provenance and event history
10. **Pathognosis** — affect interpretation

Reserved:

- **Anamnesis** — memory reconstruction / recall
- **Metabole** — explicit state transition
- **Metanoia** — belief/self revision
- **Orexis** — motivation / desire

---

# 24. Final architectural sentence

> **Aisthesis observes.  
> Noesis apprehends.  
> Apodeixis demonstrates.  
> Bouleusis deliberates.  
> Zetesis investigates.  
> Katalepsis admits.  
> Hermeneia speaks.  
> Pathognosis feels by inference.  
> Hypomnema remembers why.**

Or, in the preferred MARCO formulation:

> **The world enters through Aisthesis, becomes intelligible through Noesis,
> is justified through Apodeixis, and is expressed through Hermeneia.
> When knowledge is missing, Zetesis seeks it and Katalepsis decides whether
> it may be admitted. Bouleusis decides what to do, Pathognosis derives affect,
> and Hypomnema preserves the reason for every important change.**
