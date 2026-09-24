# MARCO plans — organized record

Written 2026-09-22. One place for every plan and decision discussed in this
session. Plans already written as their own files are indexed, not duplicated.
Plans that existed only in conversation are recorded here in full.

---

## 0. Index — where each plan lives

| Plan | File | Status |
| --- | --- | --- |
| Integrated MARCO / ALMA / POLO roadmap | `docs/ko/2026-09-22-mco-integrated-roadmap.md` | User's master plan. Reference |
| Previous goal: ALMA autonomous experience loop | `docs/ko/2026-09-20-next-goal.md` | Running in another session (other clone). Not done — completion matrix row G "부분" |
| Language graph goal | `docs/ko/2026-09-20-language-graph-goal.md` | Done (per user) |
| Goal: repair unmatched input + English core | `docs/ko/2026-09-22-repair-and-english-goal.md` | Running in another session. Untracked in this clone |
| Next goal: language realizer | `docs/ko/2026-09-22-realization-next-goal.md` | Queued. Untracked in this clone |
| Language realization design spec | this file §3 | Recorded here in full |
| Repository architecture refactor | this file §4 | Postponed until running goals finish |
| Perception / reasoning / emotion philosophy (owner's design note, verbatim) | `docs/ko/2026-09-24-perception-reasoning-emotion-philosophy.md` | Idea. Principles adopted; nothing scheduled before MARCO 1 |
| Canonical pipeline names (owner's reference, 10 Greek names + 4 reserved) and the reader's article with today's status per pipeline | `docs/architecture/pipeline-names.md`, `docs/en/pipelines.md` | Done 2026-09-24; names to be used in docs and papers from now on |
| License change: MARCO Engine License 1.0 (Apache 2.0 + visible attribution in user-facing products, white-label on request), graphs CC BY 4.0 | `LICENSE`, `LICENSE-GRAPHS`, `NOTICE`, README §License | Done 2026-09-24 (3d738ec), brought forward because a fork appeared; legal review of the wording still the owner's item |
| Trace / event logging architecture (owner's design note, verbatim, 45 sections) | `docs/ko/2026-09-24-trace-logging-design.md` | Idea. Ledger core scheduled now as L1; SOMA / ALMA / budget traces post-gate |
| L1 trace ledger goal: schema, append-only ledger, adapter from the turn envelope, why chain, failure statistics | `docs/ko/2026-09-24-trace-ledger-goal.md` | Done 2026-09-24, merged; emission at the engine sites is request L1-1 for round 5 |
| Roadmap after MARCO 1: O0 observation contract, A1' affect layers, V1 SOMA blocks-and-hand, deliberation levels, audio, neural sensors | `docs/ko/2026-09-24-roadmap-after-marco1.md` | Timeline in weeks from the gate |
| **Freeze decision and the current queue** | `docs/ko/2026-09-22-freeze-decision.md` | **Read first. Overrides §2 below** |
| Parallel goals, reduced | `docs/ko/2026-09-22-parallel-goals.md` | F1 now; S3, S2-min, W1, D1 in order |
| Structure audit (refactor Phase 0, read-only) | `docs/ko/2026-09-22-structure-audit-goal.md` | May run now. Docs + `tools/` only |
| English pack preparation data | `docs/ko/english-pack-preparation/` | Draft for exchange. Not connected to runtime |
| Known issues and measurements | this file §5 | Context for all goals |

---

## 1. Decisions and principles (from the user)

### Product direction

- **English is the core language**, because English users far outnumber Korean users.
- **Keep all 905 Korean knowledge graphs.** Never delete, rewrite, or duplicate them
  into English. They "will be handy one day". Make them reachable from English through
  language-free concept IDs.
- **No language model at runtime**, in any form (roadmap §3). Letter / morpheme
  analysis is allowed.

### How MARCO speaks

- **It must not be a picker from a list.** It must *create* sentences.
- Creation means **composing from structure** (option a), not free generation (option b).
  - (a): walk the meaning structure and realize each part through declared grammar.
    Every word traces to a structure element or a declared rule.
  - (b): choose the next word from corpus statistics. Forbidden.
  - The difference is testable: delete the event from the structure → under (a) the
    clause becomes impossible to produce; under (b) it would still appear.
- **Fluency grows as more grammar is declared.** The user accepts stiff early output in
  exchange for this. "At least it does not guess."
- Verified today: word forms really are computed (`뒹굴 + 는데 → 뒹구는데`, a stem that
  appears nowhere in the data). Answer sentences are still template-filled
  (`"{value}{unit}입니다."`).

### How MARCO reads

- When a sentence matches no declared rule: **find the closest rule, report what would
  have to be repaired to make it fit, report it to the user, and continue.** The user is
  **not** required to confirm.
- A repair may not invent a token that was neither typed nor declared.

### Engineering rules

- **Never hardcode anything language-specific in Python.** Everything lives in the pack.
- Target storage: **MCO, a fully shareable single file.** Anything left in Python cannot
  travel inside it.
- A JSON string blob hidden inside one graph node is not a migration either — it must be
  declared structure the runtime executes.

### Process

- Goals must have a **hard definition of done** so they do not end before the objective
  is reached. "If an item cannot be reached, stop and report the blocker with evidence;
  do not redefine the item."
- Do not keep interrupting running goals. The user interrupted the running goal three
  times on 2026-09-22 and wants that to stop.
- Do not push until the user says so.
- Other sessions work in the repository: stage files by name (never `git add -A`),
  `git worktree prune` before `git worktree add`, verify every push from a clean
  checkout, commit author is the repository owner only (no co-author lines).
- Reply in English. Report in minimum words: numbers, file:line, pass/fail.
- **One folder on this Mac: `~/Downloads/NAI`.** No new worktrees or sibling clones.
  Goals on this Mac run one at a time, on branches. `NAI-base` and a stale scratchpad
  worktree were removed 2026-09-22 (both clean). `NAI-repair-english` stays until goal 2
  commits and pushes, then it is removed with `git worktree remove`.
- Subsystem split lives inside the repo as `marco/`, `alma/`, `polo/`, `mco/` (§4.2),
  never as separate folders.

---

## 2. Goal sequence and status

**2026-09-22 freeze:** POLO, the MCO binary, autonomous planning, and ALMA
advancement are frozen until MARCO 1 ships. Items 3–5 below are replaced by the
queue in `docs/ko/2026-09-22-freeze-decision.md`. Item 4 (full refactor) is frozen;
only S1 and S2-min run.

1. **ALMA goal** — running, other clone (Windows, `C:\Users\hirob\Desktop\Marco`).
   Latest remote commit `6195040 Strengthen ALMA independent evidence`: 766 passed /
   8 skipped / exit 0 on that machine, ~22 min.
2. **Repair + English goal** — done 2026-09-22. Pushed as `f985857` on
   `repair-and-english`, 19 goal tests pass. Not merged to `main` yet. Worktree removed.
2b. **Structure audit** — read-only Phase 0 of the refactor. May run now in this
   clone on branch `structure-audit`. Decides `marco/language/` for goal 3.
3. **Realization goal** — next. Do not start while goal 2 runs.
4. **Architecture refactor** — after goals 1 and 2 finish and merge. Run exclusively.
5. **Parallel waves** — after the refactor and test hygiene (S3). W1 realizer, W2 MCO,
   W6 docs first; then W3 ALMA, W4 POLO P1, W5 document fixtures. One folder, one
   branch, disjoint directories. See `docs/ko/2026-09-22-parallel-goals.md`.
   If the realization goal runs before the refactor, tell it the target package
   locations so new code lands in `marco/language/` rather than at the root.

### Notes pasted into the running repair + English session (verbatim)

Note 1 — ALMA:

> Before flipping the default language to English: ALMA never selects a language and
> feeds Korean through the default pack. Measured: `tests/test_alma_runtime.py` 53
> passed on Korean default → 30 failed / 23 passed with `NAI_LANGUAGE=english`. Pin
> ALMA's language explicitly first, or scope the default change. These are not the
> pre-existing corpus failures.

Note 2 — wider impact:

> Additional before G3: (1) 52 of 75 test files feed Korean without selecting a
> language — the default flip breaks all of them, not only ALMA. Tests of Korean
> behaviour must select the Korean pack explicitly. (2) All 905 graphs are Korean.
> English default degrades existing KG answers and the frozen yardstick (400 Korean
> questions). Report the yardstick under the Korean pack; flag any KG drop, do not
> accept it silently. (3) `english.json` lacks `인코더` and `default_model_language`.
> Move the flag (both true raises `multiple_default_model_languages`) and declare the
> encoder.

Note 3 — graph scope:

> Decision: keep all 905 Korean graphs — never delete, rewrite, or duplicate them.
> English access to them is the next goal's scope (R9), not this one. Here, keep them
> working under the Korean pack and report the English-default gap as a known,
> expected limit.

---

## 3. Language realization design — full specification

Source: design proposed by another AI, adopted by the user. The goal version is
`docs/ko/2026-09-22-realization-next-goal.md`; this section keeps every example.

### 3.0 Core idea

MARCO first decides **what meaning to say**. The Language Realizer then decides **how
to say it naturally**.

    Reasoning
    ↓
    Meaning Graph
    ↓
    Utterance Intent
    ↓
    Discourse Planner
    ↓
    Expression Selector
    ↓
    Grammar Realizer
    ↓
    Surface Sentence

### 3.1 Meaning Graph

Keep the reasoning result as a meaning structure, not as natural language.

    INTENT: WARN
    TARGET: user

    CAUSE:
      action = open_door
      risk = high

There is no Korean and no English in it yet.

### 3.2 Utterance Intent

Decides *why* this is being said.

    INFORM
    ASK
    WARN
    REQUEST
    REFUSE
    REASSURE
    CORRECT
    JOKE

The same fact is expressed differently depending on intent.

    Fact: opening the door is likely dangerous

    WARN    → "그 문은 안 여는 게 좋겠어."
    INFORM  → "그 문을 열면 위험할 가능성이 있어."
    ASK     → "그래도 그 문 열 거야?"

### 3.3 Discourse Planner

Looks at the conversation flow and decides what to say and what to omit.

Questions it answers:

    Does the listener already know this?
    Can the subject be omitted?
    Must the reason be explained too?
    Conclusion first?
    Does this repeat the previous sentence?

Example. The meaning structure holds:

    USER wants open door
    DOOR dangerous
    MARCO recommends not open

but the actual output may be only:

    "안 여는 게 좋겠어."

### 3.4 Expression Selector

Among several expressions for the same meaning, chooses the one that fits.

    DESIRE(X)

Candidates:

    X하기를 원하다
    X하고 싶다
    X 할래?
    X 하고 싶은데

Selection conditions:

    language
    relationship
    formality
    persona
    emotion
    conversation context
    style

Example:

    relationship = close
    formality = casual
    persona = Adam

    → "오늘 뭐 하고 싶어?"

### 3.5 Grammar Realizer

Assembles the chosen expression into grammatically correct form.

Responsible for:

    조사 (particles)
    어미 (endings)
    활용 (inflection)
    시제 (tense)
    높임말 (honorifics)
    수 일치 (number agreement)
    어순 (word order)
    관형형 (adnominal forms)
    접속 (conjunction)

Example:

    오늘 + 무엇 + 하다 + desire + casual-question
    ↓
    오늘 뭐 하고 싶어?

By this stage the natural choice of expression is already made. The realizer's job is
only to realize it correctly.

### 3.6 Surface Sentence and Semantic Check

Final output. The important step is to compare the final sentence with the meaning
structure again, to confirm the meaning did not change.

    Meaning Graph
          ↓
    Language Realizer
          ↓
    Sentence
          ↓
    Semantic Check
          ↓
    Meaning preserved?

Considered a very MARCO-like, important step.

### 3.7 The full structure, MARCO style

                    MARCO Reasoning
                           │
                           ▼
                    Meaning Graph
                           │
                           ▼
                  Utterance Intent
                           │
                  "무슨 목적으로 말하지?"   (why am I saying this?)
                           │
                           ▼
                  Discourse Planner
                           │
              "무엇을 말하고 생략하지?"     (what to say, what to omit?)
                           │
                           ▼
                 Expression Selector
                           │
             "이 상황에서 어떻게 말하지?"   (how to say it here?)
                           │
                           ▼
                  Grammar Realizer
                           │
               "문법적으로 어떻게 만들지?"  (how to build it grammatically?)
                           │
                           ▼
                   Surface Sentence

### 3.8 Multilingual support comes from this structure

Everything up to the Meaning Graph is shared.

                   Meaning Graph
                        │
           ┌────────────┼────────────┐
           ▼            ▼            ▼
     Korean Realizer  English      Japanese
           │            │            │
     "뭐 하고 싶어?"  "What do..."   ...

Changing language never makes MARCO think again. This connects directly to the
language-independent Concept / Event layer discussed earlier.

### 3.9 Separable from ALMA personality

Persona can change the result of thinking, but it can also affect expression
separately. Same meaning:

    WARN(user, danger)

    Adam:  "그거 위험해 보이는데. 안 하는 게 좋겠어."
    Eve:   "잠깐, 그건 좀 위험할 것 같아."
    POLO:  "위험 조건이 감지되었습니다. 작업을 중단하십시오."

Same meaning, only the expression differs:

    Meaning
    + Persona Style
    + Context
    → Expression

### 3.10 Expression learning

Not every natural sentence has to be entered as a rule by a person from the start.
Learn sets of

    meaning
    context
    expression

from the expressions people actually use. Example:

    meaning:  DESIRE(activity)
    context:  casual conversation
    observed expression: "뭐 하고 싶어?"

As such experience accumulates:

    DESIRE
    + casual
    + question
    → "-고 싶어?"

becomes an Expression Pattern. MARCO learns not only grammar but **which expressions
people prefer in which situations**.

### 3.11 One-line summary

    Reasoning decides meaning.
    Discourse decides content.
    Style decides expression.
    Grammar decides form.

With this structure, the "grammatically perfect but robotic" problem can be solved
separately, and the reasoning engine and the natural-language expression engine can
evolve independently.

### 3.12 Assessment notes (added in this session)

- The design is the standard natural-language-generation pipeline (Reiter & Dale:
  content determination → planning → microplanning → realization). Proven for 25+
  years, not speculative.
- It fixes robotic output mainly through the Discourse Planner (ellipsis, no
  repetition) and the Expression Selector. A Grammar Realizer alone gives correct but
  robotic output.
- What exists today (checked at HEAD `f02d803`):

| Layer | Exists | Missing |
| --- | --- | --- |
| Meaning Graph | `transitions` (subject, predicate, before, after, delta, evidence), proof | language-free contract carrying intent, focus |
| Utterance Intent | nothing | whole layer |
| Discourse Planner | `last_subject` only | known info, ellipsis, repetition |
| Expression Selector | `관계말` slot phrasings | context-based selection |
| Grammar Realizer | `hangul.inflect`, `조사붙임`/`붙일조사`/`조사짝`, `explain._link_form` | English realizer, honorifics, number agreement |
| Semantic Check | parser exists | re-parse and compare step |

- `parser.answer()` ignores all realizer pieces and emits `상태표현.value`
  = `"{value}{unit}입니다."`. Much of the work is connecting parts that already exist.
- The Semantic Check is cheap: realize → re-parse with the same pack → compare meaning.
  It is the runtime form of the removal test and enforces "never guesses".
- Training data for expression learning needs no language model and no corpus: the
  parser already turns every user sentence into a (meaning, context, expression) triple.
- Risks: six layers is a lot — build one thin vertical slice first (one intent, one
  expression, realizer, check, both languages). The Semantic Check forces input and
  output grammar to be symmetric, so the realizer is limited by parser coverage.
  Persona is a later, separate style layer. All intents, expressions and styles must be
  pack data.
- Fluency is judged by a person on a fixed sample, not claimed from automated counts.

---

## 4. Repository architecture refactor plan — full

Status: **postponed** until the running goals finish (§2). Written by the user; kept
complete here.

### Goal

Refactor the MARCO repository from a growing prototype-style layout into a clear
architecture-oriented structure.

The goal is not to rewrite MARCO or change its behavior. The goal is to:

- define clear subsystem boundaries
- move files into meaningful packages
- reduce root-level file sprawl
- make future feature branches easier to isolate
- make multi-agent development safer
- separate architecture from implementation
- improve README → docs navigation
- preserve backward compatibility during migration
- keep all existing tests and behavior working

Do not perform a large destructive rewrite. Refactor incrementally.

### 4.1 Core design principle

Every feature must have a clear owner. Before moving or creating code, answer:

    Which subsystem owns this responsibility?

The target architecture should roughly follow:

    marco/
    ├ cognition/
    ├ knowledge/
    ├ reasoning/
    ├ learning/
    ├ memory/
    ├ language/
    ├ runtime/
    └ storage/

Higher-level systems may depend on lower-level systems. Lower-level systems should not
depend on higher-level systems. Example:

    ALMA
     ↓
    Cognition
     ↓
    Reasoning
     ↓
    Knowledge
     ↓
    Runtime primitives

A low-level graph module must not import ALMA-specific logic.

### 4.2 Target repository layout

Intended long-term structure:

    MARCO/
    │
    ├ README.md
    ├ pyproject.toml
    │
    ├ marco/
    │  │
    │  ├ cognition/
    │  │  ├ __init__.py
    │  │  ├ working_memory.py
    │  │  ├ decision.py
    │  │  ├ goals.py
    │  │  └ open_problems.py
    │  │
    │  ├ knowledge/
    │  │  ├ __init__.py
    │  │  ├ graph.py
    │  │  ├ events.py
    │  │  ├ rules.py
    │  │  └ provenance.py
    │  │
    │  ├ reasoning/
    │  │  ├ __init__.py
    │  │  ├ context.py
    │  │  ├ semantics.py
    │  │  ├ inference.py
    │  │  ├ conditions.py
    │  │  └ explanation.py
    │  │
    │  ├ learning/
    │  │  ├ __init__.py
    │  │  ├ concepts.py
    │  │  ├ structural.py
    │  │  ├ feedback.py
    │  │  ├ chunking.py
    │  │  └ unlearning.py
    │  │
    │  ├ memory/
    │  │  ├ __init__.py
    │  │  ├ episodic.py
    │  │  ├ semantic.py
    │  │  ├ procedural.py
    │  │  └ consolidation.py
    │  │
    │  ├ language/
    │  │  ├ __init__.py
    │  │  ├ parser.py
    │  │  ├ representation.py
    │  │  ├ grammar.py
    │  │  └ realizer.py
    │  │
    │  ├ runtime/
    │  │  ├ __init__.py
    │  │  ├ engine.py
    │  │  ├ router.py
    │  │  ├ session.py
    │  │  ├ capabilities.py
    │  │  └ permissions.py
    │  │
    │  └ storage/
    │     ├ __init__.py
    │     ├ kgpack.py
    │     ├ kgbin.py
    │     ├ overlay.py
    │     └ snapshot.py
    │
    ├ alma/
    │  ├ __init__.py
    │  ├ runtime.py
    │  ├ identity.py
    │  ├ emotion.py
    │  ├ preference.py
    │  └ relationships.py
    │
    ├ polo/
    │  └ ...
    │
    ├ soma/
    │  └ ...
    │
    ├ mco/
    │  └ ...
    │
    ├ graphs/
    ├ styles/
    ├ axioms/
    ├ tests/
    ├ bench/
    ├ tools/
    └ docs/

This is a target architecture, not a requirement to create empty files immediately.
Only create packages and modules that have real responsibilities.

### 4.3 Architecture vs implementation

Strictly separate architectural concepts from implementation details.

- `Working Memory` is an architectural concept. `deque(maxlen=16)` is an
  implementation detail.
- `Semantic Memory` is an architectural component. `alma-state.json["semantic"]` is
  only one current implementation.

Documentation should describe the architecture independently of the current storage
format wherever possible.

### 4.4 Subsystem responsibilities

**cognition/**

Owns: working memory · current focus · decision cycle · goals · unresolved/open
problems · attention or activation policy · metacognitive state.

Does not own: graph storage · language parsing · persistent persona state ·
filesystem permissions.

**knowledge/**

Owns: semantic graph structures · event representation · rule representation ·
provenance · node / edge identity · graph-level data contracts.

Does not own: decision policy · natural-language generation · runtime execution loops.

**reasoning/**

Owns: inference · reasoning context · relational semantics · conditions · hypotheses ·
proof paths · explanation.

Likely current mappings:

    reasoning_context.py     → marco/reasoning/context.py
    relational_semantics.py  → marco/reasoning/semantics.py
    explain.py               → marco/reasoning/explanation.py

Do not blindly move them before checking actual responsibilities.

**learning/**

Owns: concept formation · structural learning · semantic feedback · rule candidates ·
proof chunking · unlearning / retraction logic.

Likely mappings:

    experience_concepts.py → learning/concepts.py
    rule_learning.py       → learning/structural.py or rules-related learning module
    semantic_feedback.py   → learning/feedback.py
    proof_chunking.py      → learning/chunking.py
    self_authoring.py      → learning/structural.py or an authoring submodule

Split by responsibility, not filename.

**memory/**

Owns: episodic memory · semantic memory · procedural memory · memory consolidation ·
memory lifetime · memory retrieval contracts.

Memory should not decide high-level actions. It stores and retrieves information for
cognition / reasoning.

**language/**

Owns: language detection · parsing · semantic representation from language ·
morphology / particles / grammar · future natural-language realization.

Likely mappings:

    hangul.py                → language/grammar.py
    parts of parser logic    → language/parser.py

Future planned output structure (see §3):

    Meaning Graph → Utterance Intent → Discourse Planner → Expression Selector
    → Grammar Realizer → Surface Sentence

Do not implement planned components merely to satisfy the directory structure.

**runtime/**

Owns: engine lifecycle · graph routing orchestration · session execution · capability
dispatch · host/runtime interfaces · permissions.

Likely mapping: `engine.py → runtime/engine.py`. If `engine.py` currently contains
multiple responsibilities, extract them gradually instead of performing a single large
move.

**storage/**

Owns: binary / packed formats · persistence · index serialization · snapshots · future
MCO overlays.

Likely mappings:

    kgpack.py → storage/kgpack.py
    kgbin.py  → storage/kgbin.py

### 4.5 ALMA boundary

ALMA is a higher-level system built on MARCO. ALMA may depend on: cognition · memory ·
reasoning · knowledge · runtime capabilities. MARCO core must not depend on ALMA.

Target:

    alma/
    ├ runtime.py
    ├ identity.py
    ├ emotion.py
    ├ preference.py
    └ relationships.py

The current `alma_runtime.py` likely owns too many responsibilities. Do not split it
purely by line count. First classify functions by responsibility. Then extract one
responsibility at a time.

### 4.6 Dependency rule

Enforce a mostly one-directional dependency structure. Preferred conceptual direction:

    language ─────┐
                  ↓
    knowledge → reasoning → cognition
                    ↑          ↓
    memory ─────────┘       runtime
                               ↓
                          capabilities

    ALMA
      ↓
    all appropriate MARCO public interfaces

Avoid circular imports. If two subsystems require each other, first check whether:

- a shared abstraction belongs in a lower layer
- an interface/protocol should be introduced
- responsibilities are currently mixed

Do not solve circular dependencies with arbitrary local imports unless necessary as a
temporary compatibility measure.

### 4.7 Public interfaces

Each subsystem exposes a small public interface through `__init__.py` or explicit API
modules. Example:

    from marco.reasoning import ReasoningContext
    from marco.knowledge import Event
    from marco.memory import MemoryStore

External users should not need to import deeply nested internal helpers. Prefix private
implementation modules / functions with `_` where appropriate.

### 4.8 Backward compatibility

The repository currently has many imports using root-level files. Do not break
everything at once. During migration, old modules may temporarily become compatibility
wrappers:

    # reasoning_context.py

    from marco.reasoning.context import *

Mark compatibility wrappers clearly:

    """
    Compatibility shim.

    New code should import from:
        marco.reasoning.context
    """

Only delete old paths after: all internal imports are migrated · tests pass ·
external/documented usage is updated · compatibility period is complete.

### 4.9 Migration strategy

Do not perform the refactor in one enormous commit. Use incremental phases.

**Phase 0 — Audit.** Before moving code: list current Python modules · identify each
module's responsibilities · identify imports and dependency cycles · identify
public/documented entry points · identify files used directly by tests and CLI
commands. Produce a mapping table:

    Current file | Responsibilities | Target subsystem | Can move now? | Needs split? | Compatibility required?

**Phase 1 — Create package skeleton.** Create only necessary package directories
(`marco/`, `marco/knowledge/`, `marco/reasoning/`, `marco/runtime/`, …). Add
`__init__.py`. Do not move behavior yet. All tests must continue to pass.

**Phase 2 — Move clean modules first.** Start with files that already have a clear
single responsibility. Good candidates may include `hangul.py`, `kgbin.py`,
`kgpack.py`, `proof_chunking.py`. Verify before moving. Add compatibility shims. Run
relevant tests after every move.

**Phase 3 — Split mixed modules.** Identify modules such as `engine.py` and
`alma_runtime.py` that contain multiple architectural responsibilities. Extract one
responsibility at a time. Example:

    engine.py
    ├ router
    ├ judge
    ├ session
    ├ value transport
    └ CLI

Possible target:

    runtime/router.py
    reasoning/inference.py
    runtime/session.py
    runtime/engine.py
    tools/cli.py

Do not force this exact split if the code suggests a better boundary.

**Phase 4 — Normalize imports.** Move internal imports to package-qualified paths —
`from marco.reasoning.context import ReasoningContext` instead of
`from reasoning_context import ReasoningContext`. Avoid modifying unrelated behavior.

**Phase 5 — Remove compatibility shims.** Only after the new paths are stable. This
happens in a later cleanup phase, not during the initial refactor.

### 4.10 Documentation architecture

README becomes an introduction, not the complete technical manual. Target README
structure:

1. What is MARCO?
2. Why it exists
3. Architecture overview
4. Small example
5. Current measured state
6. Quick start
7. Project status / limitations
8. Documentation links

Move implementation detail into docs.

### 4.11 Documentation structure

    docs/
    ├ architecture/
    │  ├ 00-overview.md
    │  ├ 01-knowledge.md
    │  ├ 02-reasoning.md
    │  ├ 03-cognition.md
    │  ├ 04-memory.md
    │  ├ 05-learning.md
    │  ├ 06-language.md
    │  ├ 07-runtime.md
    │  └ 08-alma.md
    │
    ├ guides/
    ├ research/
    └ benchmarks/

Existing Korean research records do not need to be destroyed or rewritten. Move only
when doing so improves organization and does not destroy historical context.

### 4.12 Architecture document template

Every subsystem architecture document begins with:

    Purpose
    Owns
    Does not own
    Depends on
    Public interface

Example:

    # Memory

    ## Purpose
    Provide durable and working-memory representations that can be queried by
    reasoning and cognition.

    ## Owns
    - episodic memory
    - semantic memory
    - procedural memory
    - consolidation
    - retrieval

    ## Does not own
    - language parsing
    - action selection
    - emotional policy

    ## Depends on
    - event identity
    - provenance contracts

    ## Public interface
    ...

This is more important than describing every implementation detail.

### 4.13 README navigation

The main README links directly into architecture documentation:

    ## Architecture

    MARCO is organized into several major systems:

    - [Knowledge](docs/architecture/01-knowledge.md)
    - [Reasoning](docs/architecture/02-reasoning.md)
    - [Cognition](docs/architecture/03-cognition.md)
    - [Memory](docs/architecture/04-memory.md)
    - [Learning](docs/architecture/05-learning.md)
    - [Language](docs/architecture/06-language.md)
    - [Runtime](docs/architecture/07-runtime.md)
    - [ALMA](docs/architecture/08-alma.md)

README explains what MARCO is. Docs explain how MARCO works. Code implements the
architecture.

### 4.14 Branching strategy

Subsystem boundaries should make feature branches easier to isolate. Examples:

    refactor/reasoning-package
    refactor/memory-package
    feature/language-realizer
    feature/mco-runtime
    feature/structural-learning
    feature/memory-consolidation

When possible, assign AI agents or developers separate subsystem scopes:

    Agent A: marco/language/**
    Agent B: marco/learning/**

Avoid allowing two agents to perform broad repository-wide rewrites simultaneously.

### 4.15 Tests

The refactor must not weaken verification. At every phase:

1. run subsystem-specific tests
2. run regression tests
3. run full test suite before merging

Refactoring success means `same behavior · same or better test coverage · clearer
architecture`, not merely `files moved successfully`. Do not change tests merely
because imports moved, except for import path updates. If behavior changes
unexpectedly, treat it as a regression.

### 4.16 Avoid unnecessary abstraction

Do not create abstract classes, interfaces, or package layers solely because they look
architecturally clean. Create abstraction only when it solves a real boundary problem.

- Bad: `AbstractUniversalCognitionManagerFactory` for one implementation.
- Good: `MemoryStore` protocol, if multiple memory backends genuinely need the same
  contract.

MARCO should remain lightweight.

### 4.17 Avoid empty architecture

Do not create dozens of placeholder files. If `open_problems.py` does not exist yet as
a real feature, document the planned ownership instead of creating an empty file. The
target tree is a direction, not a checklist.

### 4.18 Preserve provenance and history

Do not destroy: historical benchmark outputs · old experiment records · research
evidence · design documents · failure reports. If these are reorganized, preserve
references and Git history where practical. Research failures are evidence, not
clutter.

### 4.19 Suggested first-pass mapping

Starting hypothesis only. Inspect each file before moving it.

    engine.py              → runtime/engine.py
                             + possible extraction into router/session/reasoning
    encoder.py             → language or runtime routing layer (decide after audit)
    reasoning_context.py   → reasoning/context.py
    relational_semantics.py→ reasoning/semantics.py
    explain.py             → reasoning/explanation.py
    hangul.py              → language/grammar.py
    experience_concepts.py → learning/concepts.py
    rule_learning.py       → learning/structural.py
    semantic_feedback.py   → learning/feedback.py
    proof_chunking.py      → learning/chunking.py
    self_authoring.py      → learning/structural or authoring submodule
    alma_runtime.py        → alma/runtime.py
                             then gradually extract memory, preference, identity, etc.
    kgbin.py               → storage/kgbin.py
    kgpack.py              → storage/kgpack.py

Do not treat this mapping as authoritative if code inspection disagrees.

### 4.20 Definition of done (as written by the user)

- root-level Python file count is substantially reduced
- major responsibilities have clear package ownership
- dependency direction is understandable
- no unnecessary circular imports exist
- existing CLI behavior still works
- all tests pass
- old import paths remain temporarily compatible where necessary
- README is concise and introductory
- architecture documentation exists for major subsystems
- future contributors can answer: where should this feature live? · what subsystem
  owns this state? · what is public API vs implementation detail?
- multiple feature branches can work in different subsystems with fewer conflicts

### 4.21 Non-goals

Do not combine this refactor with: MCO binary format implementation · complete
Language Realizer implementation · new structural-learning algorithms · major benchmark
redesign · ALMA feature expansion · performance optimization · GPU backend work ·
semantic behavior changes. Those are separate tasks. This refactor primarily
reorganizes and clarifies existing functionality.

### 4.22 Final architectural rule

Before adding a new file or feature, ask: **Which subsystem owns this responsibility,
and why?** If there is no clear answer, clarify the architecture before adding another
root-level module.

The repository should evolve from

    new idea → new file

toward

    new idea → identify owner → extend subsystem → test → document

**Guiding principle:** Refactor around responsibilities, not filenames. Preserve
behavior first. Make architectural boundaries visible in both code and documentation.

### 4.23 Notes added in this session

Why postponed:

- It moves exactly the files the two running sessions edit: ALMA
  (`alma_runtime.py`, `experience_concepts.py`, `proof_chunking.py`,
  `reasoning_context.py`) and repair + English (`engine.py`, `explain.py`,
  `language_components.py`, `pack_model.py`, `relational_semantics.py`, ~52 test files).
  A move here plus an edit in another clone produces conflicts, and "take theirs"
  silently loses work.
- The running goals cite exact file:line locations (`engine.py:108`, `explain.py:62`);
  moving files mid-goal breaks them.
- §4.14 itself forbids two agents doing repository-wide rewrites at once.

Safe to do before the running goals finish (read-only): the Phase 0 audit, and deciding
the target layout so the realization goal builds directly into `marco/language/`.

The §4.20 definition of done is too soft for a goal that must not end early. Add
measurable gates:

- root-level `.py` count: record before, set a target number after
- import cycles counted by a tool: 0 new
- full test suite: same pass count before and after
- a test that proves every old import path still works
- every subsystem document contains the five template headings (§4.12)
- `engine.py` (6062 lines) split: each extracted responsibility named, no behavior diff

Sizes that matter for Phase 3: `engine.py` 6062 lines, `explain.py` 2306,
`alma_runtime.py` large. Korean hardcoded in Python as matching patterns: 1224 words at
~1000 sites in 34 files (engine 310, build 213, explain 180, hangul 78).

---

## 5. Known issues and measurements (context for all goals)

Measured in this clone unless stated.

| Topic | Fact |
| --- | --- |
| §12 usability gate | Fails at step 1 verbatim (`민수는 사과 다섯 개가 있어` — particle on counter). With accepted phrasings: steps 1, 2, 3a, 4 (correction without re-execution), 7-restart work; 3b (missing premise), 5 (why), 6 (ambiguous referent), English all return nothing |
| English engine | Works with declared examples, no particles: `Minsu has 8 apples. Jiyeon has 3 apples. Minsu gave Jiyeon 2 apples. how many apples does Jiyeon have?` → `5 apples.` Unknown: `frame_induction.read_event` (particle-based) for English |
| English pack | `styles/english.json`: 25 keys, 0 examples, lacks 37 reasoning keys, no `인코더`, no `default_model_language` |
| Korean graphs | 905 graphs, all Korean |
| Default-language blast radius | 52 of 75 test files feed Korean without selecting a language; ALMA `test_alma_runtime.py` 53 pass → 30 fail / 23 pass under English default |
| Language selection split | `language_components._language_path` reads `NAI_LANGUAGE → KG_LANG → 한국어`; `explain.py:62` reads `KG_LANG` only; `engine.py:108` has a hardcoded Korean refusal |
| Corpus test fixture | `tests/test_reasoning_persistence.py:create_app` passes the gitignored 86MB `data/위키/정의문.jsonl` unconditionally. On corpus-less clones: 27 of 38 failures (32 incl. direct corpus tests, 84% noise). Product code is unaffected. User declined the fix (not lethal) |
| Machine-dependent tests | `test_response_composer` 2 fail here (`'manager' ≠ 'extractive_grounded_response'`, verdict `입력이해실패 ≠ 원문정의비교`), pass on the other machine. This clone differs: 1 untracked learned file, 440 ignored cache files |
| Full suite | Here at `f02d803`: 3 failed / 771 passed, 19m53s. Other machine at `6195040`: 766 passed / 8 skipped / exit 0, ~22 min |
| Morphology | Generates unseen regular forms; irregulars wrong unless declared (`춥 → 춥었다`, should be `추웠다`) |
| Encoder isolation | Done by another session: pack `인코더` declaration, `PackModel.encoder` (`EncoderRuntime`) with `activate()`. `encoder._mode` global still exists for legacy callers |
| Lightness (earlier) | import 13ms · first turn 354ms · ~334ms per turn · RSS 31.4MB · pack 26.0MB, 1.6MB without the optional corpus · 0 sockets · 0 third-party packages on the default path |
| KO/EN comparison (earlier) | English 0/5 on quantity, subject, negation, context, intent |
