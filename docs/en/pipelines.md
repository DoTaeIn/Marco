# The ten pipelines of MARCO, and what they are called

*2026-09-24. The reference that fixes these names is
[docs/architecture/pipeline-names.md](../architecture/pipeline-names.md). This
article explains them to a reader, and says for each one what exists in the
repository today and what is only planned.*

MARCO is not one path from a question to an answer. It is a family of
processes that sense, understand, divide, prove, deliberate, search, admit,
speak, feel by inference, and remember why. Each of those processes now has a
name of its own. The names are Greek, chosen from the vocabulary of classical
philosophy, and they name the process, not the file that implements it today.
A module can move to a new package, a class can disappear in a refactor, and
the name stays. That is the whole point of naming them.

The ten names, in one table:

| Name | What it does | In plain words |
| --- | --- | --- |
| **Aisthesis** | sensory perception (SOMA) | raw signal to measurable observations |
| **Noesis** | semantic apprehension | observations or text to meaning: entities, relations, events |
| **Diairesis** | query decomposition | one utterance to its several explicit questions |
| **Apodeixis** | evidence-bounded reasoning | premises, evidence and rules to a justified conclusion |
| **Bouleusis** | deliberation | a goal to possible actions and subgoals |
| **Zetesis** | inquiry | a knowledge gap to evidence found |
| **Katalepsis** | knowledge admission | a candidate to accepted knowledge, or not |
| **Hermeneia** | language realization | meaning to a sentence a person can read |
| **Hypomnema** | provenance ledger | the record of events, causes, evidence and reasoning |
| **Pathognosis** | affect interpretation | events and cues to an affect hypothesis |

Reading rule: the first time a name appears in a paper or a document, give it
with its plain description, "Apodeixis, MARCO's evidence-bounded reasoning
pipeline". After that, the name alone.

## The core chain

Four of the ten form the spine of the system. The world enters through
Aisthesis, becomes intelligible through Noesis, is justified through
Apodeixis, and is expressed through Hermeneia. Everything epistemically
important along the way is written into Hypomnema.

```mermaid
flowchart TD
    W[World] --> A[Aisthesis<br/>sensory perception]
    A --> OG[Observation Graph]
    OG --> N[Noesis<br/>semantic apprehension]
    T[Text] --> N
    N --> M[Meaning]
    M --> D[Diairesis<br/>query decomposition]
    D --> P[Apodeixis<br/>evidence-bounded reasoning]
    M --> P
    P --> C[Conclusion]
    C --> H[Hermeneia<br/>language realization]
    H --> U[Utterance]
    P -. missing premise .-> Z[Zetesis<br/>inquiry]
    Z --> K[Katalepsis<br/>knowledge admission]
    K --> KG[Knowledge Graph]
    KG --> P
    G[Goal] --> B[Bouleusis<br/>deliberation]
    B --> P
    E[Experience, cues] --> F[Pathognosis<br/>affect interpretation]
    A & N & P & B & Z & K & H & F -.-> Y[(Hypomnema<br/>provenance ledger)]
```

Two loops hang off the spine. When Apodeixis finds that a premise it needs is
not known, Zetesis goes looking, and whatever it brings back must pass
Katalepsis before it counts as knowledge. When something has to be done rather
than concluded, Bouleusis decides what to attempt, and its observations feed
back into Apodeixis. Pathognosis stands to the side: it derives affect from
what happened, and never injects it.

## Where each pipeline stands today

Status words used below: **built** means it runs on `main` and has a measured
number; **partly** means a first version exists but the named pipeline is
larger; **planned** means a design and a date in the roadmap, no code. The
dates come from [the freeze decision](../ko/2026-09-22-freeze-decision.md) and
[the roadmap after MARCO 1](../ko/2026-09-24-roadmap-after-marco1.md).

### Aisthesis, sensory perception

*Greek αἴσθησις: sensation, perception.*

Aisthesis is the pipeline of SOMA, the body of the MARCO family. It turns raw
signals into observations that can be reproduced: pixels into edges, regions,
tracked entities and spatial relations; a waveform into energy, onsets and
acoustic segments; sensor values into measurements and state changes. Its
output goes into an Observation Graph and carries its source, time,
confidence, the operator that produced it, and its uncertainty.

The narrow definition is deliberate. Aisthesis does not "understand the
world". It records what can be observed, and nothing it records is yet a fact.

**Today: partly.** The repository has document perception for charts and
tables from images, objects, pose, and a vision-language hypothesis path, each
proven by its own test. The full SOMA pipeline, non-neural blocks-and-hand
vision into an Observation Graph, is scheduled for the weeks after MARCO 1
passes its gate.

### Noesis, semantic apprehension

*Greek νόησις: apprehension by the intellect.*

Noesis makes meaning out of what Aisthesis observed or out of the characters
and clauses of a sentence. From an observation that entity 17 moved from A to
B it may form the hypothesis that entity 17 is a ball, or that the movement
was a transfer. From a sentence it builds the same kind of structure: who
holds what, how many, what changed hands. Text is one input among others; the
internal language of the system is the graph, not the sentence.

**Today: built, and the weakest link.** The parsing side of the engine is
Noesis for text: frame induction, language components, relational semantics,
the state engine. Four understanding rounds have worked on it. On the frozen
52-dialogue exam it answers 21 of 108 answerable questions, with 0 wrong, and
records 82 of 150 statements. Almost every miss is a statement it did not
read, which then blocks every later question. Round 4, running now, builds its
development data from natural adult language instead of templates because
that is what the exam turned out to be.

### Diairesis, query decomposition

*Greek διαίρεσις: division.*

A person often asks several things at once: what TCP is, what UDP is, and how
they differ. Diairesis divides one utterance into the explicit questions the
person asked, so each can be answered in order. It only divides; it never adds
a question the person did not ask. That is the line between Diairesis and
Bouleusis, and it matters for traceability: user goals and system-made goals
must never become indistinguishable.

**Today: planned.** Multi-query is one parser class queued for understanding
round 5. Every question is still answered one at a time.

### Apodeixis, evidence-bounded reasoning

*Greek ἀπόδειξις: demonstration, proof.*

This is the central pipeline. Apodeixis takes premises, retrieves evidence,
applies rules, checks alternatives and contradictions, and produces a
conclusion that can be traced to its parents. It keeps observed, reported,
hypothesized, inferred, verified, contradicted, withdrawn and unknown apart,
and it would rather say unknown than guess. MARCO does not merely output a
conclusion; it performs Apodeixis over explicit evidence, and every important
conclusion has a reconstructible evidential path.

**Today: built.** The reasoning context carries the state of a conversation
through its transitions and verifies each answer; Horn inference runs over
the graphs; the engine judges candidate answers against a threshold. On the
frozen reasoning exam it gets 148 of 151 parsed questions right with 0 wrong.
On the frozen dialogues it gives 0 confident answers without evidence and
uses retracted evidence 0 times. Those two zeros are the gate condition that
Apodeixis exists to meet.

### Bouleusis, deliberation

*Greek βούλευσις: deliberation, counsel.*

Apodeixis asks what follows from what is known. Bouleusis asks what should be
attempted next: the requirements of a goal, the possible actions and
subgoals, their preconditions, and a choice. Any subgoal the system makes for
itself is labelled as generated, with its parent goal and its reason, so it
can always be told apart from what the person asked for.

**Today: partly, and frozen.** The goal runtime executes a fixed set of
registered tools, each approved once by a person. Re-planning, tool making
and a general planner are frozen until MARCO 1 ships. Declared deliberation
budgets, low, medium and high, measured against accuracy on the reasoning
exam, are in the roadmap for the weeks after the gate.

### Zetesis, inquiry

*Greek ζήτησις: inquiry, search.*

Zetesis starts where Apodeixis or Bouleusis stops for lack of a premise. It
turns the gap into a research need, seeks evidence, and returns a candidate
with its provenance. It never writes into trusted knowledge itself.

**Today: partly.** Approved web research is answered locally: a person
approves a source, and the answer from it is kept. The self-driven
knowledge-gap loop, where a missing premise itself triggers the search, is a
later stage of the roadmap.

### Katalepsis, knowledge admission

*Greek κατάληψις: a grasp secure enough to count as knowledge.*

Katalepsis is the door between "I found something" and "MARCO now uses this".
A candidate is checked against its source, against what is already known,
and against the rules and policies, and where required a person approves it.
Only then does it enter the knowledge graph or its overlay. This is the
mechanism behind MARCO's refusal to turn retrieved text into truth on its own.

**Today: built, in three narrow doors.** The engine learns on its own exactly
one thing, that a phrase denotes an existing node, and only after asking the
person and getting a yes. Approved web sources become facts. ALMA adds graph
assets a person approved. The proposal tools print candidates and decide
nothing. No node, edge or graph is ever created by the engine alone.

### Hermeneia, language realization

*Greek ἑρμηνεία: interpretation, expression.*

Hermeneia turns an established meaning into a sentence: meaning, then the
intent of the utterance, then discourse planning, expression choice, grammar,
and a semantic check that the sentence still says what the meaning said. The
principle is that meaning and language are different things. Hermeneia
expresses what Apodeixis established and never invents content to make a
sentence sound better. Its descriptive name, the language realization
pipeline, stays in the technical documents.

**Today: built.** The realizer in `marco/language/realizer/` has the six
layers above, one language pack each for English and Korean, and three
rounds of work behind it. On the frozen dialogues every spoken reply, 340 of
340, is composed from a meaning; none is picked from a list. The owner reads
a 40-reply fluency sample after each round.

### Hypomnema, the provenance ledger

*Greek ὑπόμνημα: a record, a written reminder.*

Hypomnema is the second graph of the system. The knowledge graph records what
MARCO knows; Hypomnema records how it came to know or conclude it. It is an
append-only ledger of epistemically important events: source, observation,
interpretation, reasoning, decision, mutation, output. Each event has an id,
belongs to a trace, and names its parents, so the whole is a directed acyclic
graph. A correction is a new event that supersedes an old one, never an edit.
The storage may be JSONL today and SQLite or the native container tomorrow;
the concept does not change. Its design sentence: MARCO should never have to
say "I don't know why I thought that."

**Today: built, from the outside.** The package `marco/trace/` declares the
event kinds and epistemic statuses, writes the ledger, walks the why chain
back from any answer, prints a human projection, and produces failure
statistics that feed the next understanding round. Recording is off by
default and costs a quarter of a millisecond per turn when on. It currently
records each turn from the engine's result; emitting events from inside the
engine, at the twenty sites already listed, is the next step.

### Pathognosis, affect interpretation

*Built from pathos, affect, and gnosis, knowledge.*

Pathognosis is ALMA's way of feeling by inference. For ALMA's own state, an
event is related to its goals, expectations, control and preferences, appraised,
and only then does an affect state and an emotion concept follow. For another
person, observed cues, context and the person's own report produce an affect
hypothesis with its evidence and confidence. It never collapses that
hypothesis into a fact. An emotion state is not an emotion word, and affect is
derived, not injected.

**Today: partly.** An affect state colours how the realizer chooses
expressions, with its own test. The layered pipeline, primitives to appraisal
to concept, is scheduled for the weeks after the gate, and affect in other
people some weeks after that.

## Who owns what

| System | Pipelines |
| --- | --- |
| **SOMA** | Aisthesis |
| **MARCO** | Noesis, Diairesis, Apodeixis, Zetesis, Katalepsis, Hermeneia |
| **ALMA** | Pathognosis, memory-linked appraisal, personal state |
| **POLO** | Bouleusis, the permission and execution boundary of actions |
| **shared** | Hypomnema |

These are conceptual boundaries. They do not dictate the package layout, which
the structure audit plans separately.

## How the names are used

In writing, prefer the name to the mechanism: "MARCO performs Apodeixis over
explicit premises and evidence" rather than "MARCO runs its reasoning
function"; "candidate knowledge must pass Katalepsis" rather than "MARCO
learns it"; "the history is retained in Hypomnema" rather than "we save
logs". In code the names belong at boundaries, in a module docstring or a
comment such as "Aisthesis emits observations, never verified world facts",
not in function names. Descriptive names live alongside them: the language
realization pipeline is Hermeneia; the sensory observation pipeline is
Aisthesis.

Four more names are reserved and not yet assigned: **Anamnesis** for memory
reconstruction and recall, **Metabole** for explicit state transition,
**Metanoia** for belief and self revision, and **Orexis** for motivation and
desire, which may one day sit beneath Pathognosis.

## In one breath

Aisthesis observes. Noesis apprehends. Apodeixis demonstrates. Bouleusis
deliberates. Zetesis investigates. Katalepsis admits. Hermeneia speaks.
Pathognosis feels by inference. Hypomnema remembers why.
