# `marco.language.realizer`

Hermeneia, MARCO's language realization pipeline, with the check that makes it
Palinorrhesis: speak only after the sentence has returned to its meaning.
Rewritten 2026-09-24 against commit `5f321a3` (goal D2). The first version of
this page, written 2026-09-23 against `78bd062`, described a stub that returned
the engine's sentence unchanged; realizer rounds W1, W2 and W3 replaced it. The
names are explained in [the pipelines article](../en/pipelines.md#hermeneia-language-realization)
and fixed in [naming.md](naming.md).

## Purpose

Turn a turn's language-free meaning into the sentence the user reads, and
never let a sentence out that does not say that meaning. A turn result carries
a meaning block (act, reason, facts, state changes; request W1-1); the realizer
builds a Meaning Graph from it, plans why each part is said, decides what to
leave unsaid, picks a declared way of saying each clause, inflects it, and then
parses every clause back with the same language pack. A clause that does not
return its proposition unchanged is never emitted; when no declared expression
passes, the turn is said as the declared hold. The engine's finished sentence
is never read as input: when no plan matches, that sentence passes through
unchanged and the report says so.

On the frozen dialogue exam every one of the 340 spoken replies was composed,
none passed through (gate condition 5,
`docs/ko/dialogue-gate-2026-09-22/composition-after-w3.json`; printed by
`python tools/doc_facts.py frozen`).

## Owns

| Module | Layer | What |
| --- | --- | --- |
| [`__init__.py`](../../marco/language/realizer/__init__.py) | entry | `Realizer`, `realize`, `last_report`, `follow_up`, `default_realizer` |
| [`meaning.py`](../../marco/language/realizer/meaning.py) | 1 Meaning Graph | the turn's propositions from its structure; the engine's sentence is never read |
| [`intent.py`](../../marco/language/realizer/intent.py) | 2 Utterance Intent | declared turn plans map act and reason to acts (INFORM, ASK, WARN, CORRECT, REFUSE, REASSURE); no plan, no realization |
| [`discourse.py`](../../marco/language/realizer/discourse.py) | 3 Discourse Planner | known facts not repeated, answer ellipsis, repeated-role ellipsis, conclusion first, coordination |
| [`expression.py`](../../marco/language/realizer/expression.py) | 4 Expression Selector | declared (and learned) candidates whose roles and conditions fit; order only, the check decides |
| [`grammar.py`](../../marco/language/realizer/grammar.py) | 5 Grammar Realizer | particles, endings, inflection, agreement, order, from declarations only; a closed set of part kinds |
| [`check.py`](../../marco/language/realizer/check.py) | 6 Semantic Check | five independent readers: numbers, polarity, quotations, the full-clause reading, ellipsis |
| [`learning.py`](../../marco/language/realizer/learning.py) | beside 4 | a user's phrasing becomes a candidate only if it realizes its own meaning and passes the check; off unless a language file declares it |
| [`packs.py`](../../marco/language/realizer/packs.py) | loading | the realizer's declarations and the pack pieces it reuses |
| [`meaning.json`](../../marco/language/realizer/meaning.json), [`english.json`](../../marco/language/realizer/english.json), [`한국어.json`](../../marco/language/realizer/한국어.json) | data | what every language shares (acts, plans, discourse rules); each language's expressions, lexicon, cases, endings, follow-up phrasings |

## Does not own

- **Reasoning and state.** What the meaning says is decided before the call, by
  `reasoning_context.py`, `state_engine.py`, `graph_inference.py` (Apodeixis,
  evidence-bounded reasoning). The realizer adds no fact.
- **Parsing the user.** Noesis, semantic apprehension of text, is
  `relational_semantics.py`, `frame_induction.py`, `input_understanding.py`;
  `check.py` calls the pack's parser, it does not define one.
- **The language packs** `styles/한국어.json` and `styles/english.json`, read
  through `pack_model.py` and `language_components.py`.
- **The graph engine's lines.** An answer from a `.kg` graph is the line its
  author wrote; `engine.answer` passes it through `realize`, which has no plan
  for it and returns it unchanged (`realized: False`, `no_plan`). The graph
  engine's unknown and hold replies are composed.
- **Why from the provenance ledger.** Hypomnema, the provenance ledger, is
  [`marco.trace`](marco.trace.md); composing "why" from its why chain is goal W4.

## Depends on

- Standard library: `collections`, `copy`, `functools`, `json`, `pathlib`, `re`,
  `unicodedata`.
- Root modules, for the pack's own grammar: `language_components`, `pack_model`
  (`packs.py`), `relational_semantics`, `hangul` (`grammar.py`),
  `numeral_semantics` (`check.py`, `learning.py`). They move in goal S4 or split
  later; see `python tools/doc_facts.py layout`.

## Public interface

`realize(meaning, intent, language) -> str`, re-exported as
`marco.language.realize`.

| Argument | Meaning |
| --- | --- |
| `meaning` | the turn result: a `dict` with a language-free `meaning` block and the engine's `answer`, which is returned only when no plan matches |
| `intent` | the turn's status (`answered`, `unresolved`, ...) or the graph verdict |
| `language` | the pack path, a loaded pack model, or `None` for the declared default (English) |

Callers today: `ReasoningContext.turn` (`reasoning_context.py`, the state
dialogue), `engine.answer` through `_spoken` (`engine.py`, the graph route),
and `AppState` for the UI's own holds (`views/kgpack_ui.py`).

| Name | What | Proof |
| --- | --- | --- |
| `realize` | signature and export | `tests/test_language_seam.py::test_realize_is_exported_with_the_declared_signature` |
| `realize` | every answered state-dialogue turn and every engine answer passes through it once | `tests/test_language_seam.py::test_every_answered_turn_passes_through_realize_once`; `tests/language/test_w1_engine_seam.py` |
| `realize` | composes from meaning in both languages: the seven-step dialogue, the twenty recorded phrasings, every comparison and time kind | `tests/language/test_w3_realizer_r3.py::test_the_seven_step_the_twenty_phrasings_and_these_kinds_are_all_composed`, `::test_every_comparison_and_time_kind_is_composed` |
| `realize` | a clause whose parse differs is never emitted; swapped roles, changed numbers, dropped negation injected and caught; every clause checked | `tests/language/test_w1_r3_injected_errors.py` |
| `realize` | holds, clarifications and refusals composed in both languages; a held answer stays a hold | `tests/language/test_w2_realizer_r2.py::test_every_hold_clarify_and_refusal_plan_is_composed_in_both_languages`; `tests/language/test_w3_realizer_r3.py::test_a_held_answer_is_a_hold_with_the_realizers_reason` |
| `realize` | a realizer that passes everything through scores 0 composed on the gate's own classifier | `tests/test_composition_gate.py::test_f2_6_a_realizer_that_passes_everything_through_scores_zero_composed` |
| `realize` | no sentence literal in realizer code | `tests/language/test_w1_r8_literals.py` |
| `last_report()` | the last turn's report: `realized`, `reason`, acts, clauses and their checks | `tests/test_composition_gate.py::test_the_live_realizer_is_seen_composing_the_seven_step_dialogue` |
| `follow_up(text, language)` | only the declared follow-up phrasings (the bare why, what a reading changed) | `tests/language/test_w2_realizer_r2.py::test_follow_ups_are_only_the_declared_phrasings` |
| `Realizer(learning=True)` | expression learning, off by default | `tests/language/test_w1_r7_learning.py` |

Round reports: `marco/language/W1-report.md`; the owner's fluency samples in
`marco/language/measurements/fluency-sample*.md`.
