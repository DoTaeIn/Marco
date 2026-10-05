# Next goal: say what was meant — a language realizer from meaning to sentence
> **Added 2026-09-23.** Model: the owner's chat model, effort high. Read
> `docs/ko/2026-09-22-freeze-decision.md` first. The owner started this goal on
> 2026-09-23 in parallel with G1 round 1 (`docs/ko/2026-09-23-understanding-r1-goal.md`),
> which owns the parsing side. The frozen gate baseline is 3/108, so develop
> against the fixed 7-step dialogue, the 20 phrasings in
> `docs/ko/repair-and-english-2026-09-22/unseen-before.json`, and your own dev
> sentences. Never open `data/benchmarks/dialogues_v1/` or run
> `bench/dialogue_gate.py` against it; the owner scores it. Until goal S3 (test
> speed) reports, run only `tests/language/` and `tests/test_language_seam.py`;
> the full parallel suite once, at the end.
> Seam facts from S2-min: `marco/language/__init__.py: realize()` is called once
> per dialogue turn from `marco/reasoning/context.py`; answers the engine composes from
> graph routing still bypass it (second seam needed, request it). Owns
> `marco/language/**`, `tests/test_language_seam.py`, `tests/language/`; expression
> tables live in `marco/language/realizer/*.json`, never in `styles/*.json`.
> Changes to `engine.py` or `marco/reasoning/context.py` go to `docs/requests/W1-<n>.md`.


Written 2026-09-22. Runs **after** `2026-09-22-repair-and-english-goal.md`. This is
a goal, not a report. Do not start it while that goal is still running in another
session.

## Core rule

MARCO first decides **what** to say. The realizer then decides **how** to say it.

    Reasoning decides meaning.
    Discourse decides content.
    Style decides expression.
    Grammar decides form.

    MARCO reasoning
      -> Meaning Graph        no language in it
      -> Utterance Intent     why this is said
      -> Discourse Planner    what to say, what to omit
      -> Expression Selector  which way of saying it fits here
      -> Grammar Realizer     particles, endings, inflection, order
      -> Surface Sentence
      -> Semantic Check       parse the sentence back; meaning unchanged?

Everything up to the Meaning Graph is shared by all languages. Changing language
changes only the realizer's declarations. MARCO never reasons twice to answer in
another language.

## Relation to the previous goal

That goal is expected to report two blockers. Both are correct behaviour, not
failures, and this goal resolves them:

- Its G3 requires the §12 dialogue of `2026-09-22-mco-integrated-roadmap.md` in
  English. Steps 3b (missing premise), 5 (why) and 6 (ambiguous referent) need
  answers that nothing currently composes. They will block.
- Its G4 ("no Korean in Python") spans 1224 words at ~1000 sites in 34 files, many
  off the dialogue path (`marco/knowledge/ingest/text.py`, `experiments/codegen.py`, `marco/knowledge/ingest/web.py`). It may block.
  This goal does not inherit that breadth; see R8 for its own exact scope.

## Definition of done

This goal ends when **all** of R0–R9 hold, each verified by running. It does not
end because a layer works, because tests pass, because time ran out, or because
an item was moved to "not supported". If an item cannot be reached, stop and
report the blocker with evidence. Do not redefine the item to fit what was built.

- **R0** Previous goal's final report read; its actual state re-verified by
  running; list of what it left blocked recorded before any code changes. Also
  record: which test files select their language (52 of 75 did not at `6195040`);
  the English-default gap on existing graphs; tests whose result differs by
  machine (`test_response_composer`: 2 fail on one clone, pass on another).
- **R1** Thin slice: one INFORM answer produced through all six layers and the
  Semantic Check, in Korean and in English, from one Meaning Graph.
- **R2** §12 steps 3b, 5, 6 answered by composition from structure — in Korean and
  in English, in the wording written in §12, not a rephrasing chosen to fit.
- **R3** Semantic Check blocks injected errors: a realizer rule that swaps giver and
  receiver, one that changes a number, one that drops a negation. All three must
  be caught and none emitted.
- **R4** Removal test: delete an event from the Meaning Graph; its clause becomes
  unproducible. If it still appears, the realizer reads from somewhere it must not.
- **R5** Discourse: established referents are elided, known facts not repeated,
  measured on fixed multi-turn dialogues with the counts published.
- **R6** One reasoning pass, two languages: the same Meaning Graph realized in both,
  with the reasoning path shown to execute once.
- **R7** Expression learning: an expression observed in user input becomes a
  selectable output candidate in the same context, is removable, and the
  before/after is shown.
- **R8** Zero language-specific literals in the realization-path files, listed by
  name at R0 and measured with the pattern count used in
  `docs/ko/언어-기능차이-측정.md`. Scope is those files, not the whole repository.
- **R9** Existing Korean graphs, kept and reachable in English. All 905 remain
  unchanged and usable under the Korean pack. A fixed sample, chosen at R0 before
  implementation, is answered from an English question through sense links, the
  answer realized in English from the same graph node. Linked, unlinked and
  structure-less ranges are counted and published; the unlinked range is not claimed.

## Invariants — breaking one fails the goal even if R0–R8 pass

- **I1 Not a list-picker.** Sentences are realized from structure plus declared
  grammar, the way `뒹굴 + 는데 -> 뒹구는데` is computed today for a stem that appears
  nowhere in the data. A finished sentence stored in a table is not an
  implementation of any layer.
- **I2 Nothing language-specific in Python.** Intents, discourse rules, expression
  candidates, selection conditions, styles, grammar and check rules live in the
  pack, so they travel inside a single shareable `.mco`. A branch on a word, verb,
  name, sentence or test id fails. A JSON string blob in one node also fails —
  it must be declared structure the runtime executes.
- **I3 Meaning never changes between graph and sentence.** The Semantic Check is
  not optional and not sampled. A sentence that fails it is never emitted. Fall
  back to a plainer expression; if none passes, hold and say so.

## Layers — what exists, what to build

Checked at HEAD `f02d803`. Re-check at R0; the tree changes under other sessions.

| Layer | Exists | Build |
| --- | --- | --- |
| Meaning Graph | `transitions`: subject, predicate, before, after, delta, evidence; proof | Language-free contract; carry intent, focus, provenance |
| Utterance Intent | none | Declared set: INFORM, ASK, WARN, CORRECT, REFUSE, REASSURE at minimum |
| Discourse Planner | `last_subject` only | Known info, subject ellipsis, whether to give reasons, conclusion first, no repetition |
| Expression Selector | `관계말` slot phrasings, no selection | Candidates chosen by language, formality, relationship, persona, context |
| Grammar Realizer | `hangul.inflect`, `조사붙임`/`붙일조사`/`조사짝`, `explain._link_form` | Reuse. English realizer from English pack declarations |
| Semantic Check | parser exists | Realize -> re-parse with the same pack -> compare meaning |

`parser.answer()` currently ignores all of the realizer pieces and emits
`상태표현.value` = `"{value}{unit}입니다."`. Much of the work is connecting parts that
already exist.

## Existing Korean knowledge — keep, link, never discard

English is the core language because English users far outnumber Korean users.
The 905 Korean graphs stay. Never delete, rewrite, or duplicate them into English.

1. Link through the language-free concept IDs of the Meaning Graph layer. Prep:
   `docs/ko/english-pack-preparation/02-sense-links-ko-en.json`,
   `03-existing-knowledge-links.json` (draft — convert, do not copy).
2. String similarity between a Korean and an English word is not evidence of the
   same meaning.
3. Korean questions keep working from the Korean pack. The frozen yardstick,
   measured under the Korean pack, must not drop.
4. A node with only Korean source text and no structure is shown as a Korean
   source, not translated. No translation API.

## Build order

1. **Thin vertical slice first (R1).** One intent, one expression, realizer,
   check, both languages. Do not build all six layers wide before one sentence
   runs end to end.
2. Widen intents, then discourse rules, then expression candidates.
3. Expression learning last among required items, because it needs the check to
   reject bad learned candidates.

## Expression learning — where the data comes from

No language model, no external corpus. The parser already turns every user
sentence into a (meaning, context, expression) triple. That is the training data.

    meaning:   DESIRE(activity)
    context:   casual, question
    observed:  "뭐 하고 싶어?"
      -> pattern: DESIRE + casual + question -> "-고 싶어?"

A learned candidate must pass the Semantic Check before it is ever selected, and
can be listed, disabled and removed with the conversation that produced it.

## Persona — last, bounded

Same meaning, different style:

    WARN(user, danger)
    Adam  "그거 위험해 보이는데. 안 하는 게 좋겠어."
    Eve   "잠깐, 그건 좀 위험할 것 같아."
    POLO  "위험 조건이 감지되었습니다. 작업을 중단하십시오."

Persona selects expressions; it never changes the Meaning Graph. POLO's audit
facts must not be altered by any persona. Not required for R0–R8.

## Verification

1. Fluency is judged by a person on a fixed sample. Publish the sample and the
   judgement. Do not claim fluency from automated counts.
2. Report separately: structured-input results, natural-language results,
   check passes, check blocks, holds, wrong assertions, execution errors.
3. Re-measure the frozen routing figures and existing benchmarks; do not assume
   they are unchanged.
4. Report cost: startup, per-turn latency, memory, pack size. Suite is ~20 min.

## Not in this goal

- Any language model at runtime, in any form, including for "naturalness".
- Understanding or producing arbitrary Korean or English. Range is bounded by
  what is declared, and the bound is reported.
- Irregular morphology beyond what is declared (`춥 -> 춥었다` is wrong today).
- Building the `.mco` container.

## Working conditions

- Other sessions work in this repository. Do not revert, overwrite, or tidy
  changes you did not make. Stage files by name; never `git add -A`.
- Local may lag the remote. Check before and after every step that commits.
- `git worktree prune` before `git worktree add`. A failed `cd` afterwards runs the
  tests in the working tree and reports a false pass. Confirm `pwd` and that
  `data/위키/정의문.jsonl` is absent before trusting a clean-checkout result.
- Verify every push from a clean checkout of the pushed commit.
- ~32 test failures come from `tests/test_reasoning_persistence.py:create_app`
  requiring a gitignored 86MB corpus. Pre-existing; not your regressions; not in
  scope.
- Commit author is the repository owner only. No co-author or generated-by lines.

## Reporting style

Minimum words. Numbers, file:line, pass/fail. No prose, no restating the task, no
announcing what you are about to do.
