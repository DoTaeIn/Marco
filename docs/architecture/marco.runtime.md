# `marco.runtime`

Written 2026-10-01 against commit `c8ad9a5`; checked 2026-10-01 against
`2864b34` (no file named here changed between the two).

## Purpose

The entry points that open a graph for conversation. Goal S4
([file moves](../ko/2026-09-24-file-moves-goal.md)) moved three root files here
whole: `nai` became `conversation.py`, `explain` became `explain.py`,
`graph_dialogue` became `graph_dialogue.py` ([target-map.json](target-map.json):
the `modules` rows and the `moved_in_s4` list). The package is the planned home
of the engine's entry, router, sessions, app state, model factory, diagnostics,
self-check and command line ([structure-audit.md](structure-audit.md) A6,
layer 9); those parts are still inside `engine.py`, `views/kgpack_ui.py` and
`pack_model.py`, whose splits stay frozen until MARCO 1 ships
([marco.md](marco.md)).

## Owns

| Module | Lines | What |
| --- | --- | --- |
| [conversation.py](../../marco/runtime/conversation.py) | 171 | `Conversation(graph_path, mode=None)`: one chat contract over a `.kg` graph (mode `game`, `engine.Session`) and a document graph (mode `guide`, `explain.ask` with `DialogueMemory`); without `mode`, a `.kg` suffix picks `game` and any other suffix `guide` (line 69); `.reply(text)` returns a `Reply(text, intent, topic, path, status)`; `.state()`; `build_graph(source, output, *, minimum=2)` builds a `.json` graph from the `.txt`/`.md` files of a folder; a command line (`--build`, `--out`, `--min`, `--ask`, `--chat`) |
| [explain.py](../../marco/runtime/explain.py) | 2315 | the second answer pipeline, for concept graphs built by `marco/knowledge/ingest/text.py`: `open_` (also converts a graphify `graph.json` with `graphify_read`), `ask`, `explain`, `explain_path`, typo repair (`fix_typo`), procedures and code (`procedure_answer`, `woven_answer`), `DialogueMemory` (decaying activation per node), `grade_explain`, `knowledge_image` (Mermaid), `_selfcheck` behind `--check`. Its docstring: it explains and does not judge |
| [graph_dialogue.py](../../marco/runtime/graph_dialogue.py) | 257 | `GraphDialogueBackend` (`component_id = "graph-dialogue-v1"`): dialogue words are looked up in `graphs/graph_대화예절.kg`, request endings are computed by inflection; `.parse(text, pack)` tries a request first, then dialogue, and claims dialogue only when the router (`engine.pick_graph` unless one is passed) picks that graph (lines 47–69, 166–168); `backend()` returns one instance |

`graph_dialogue.backend` is named by a string in the Korean language pack,
`"backend": "marco.runtime.graph_dialogue:backend"` (`styles/한국어.json:5274`),
and loaded with `importlib` by `language_components.resolve_backend` (lines
696–702). Moving or renaming the function breaks that pack entry.

## Does not own

- **The argument engine.** `.kg` loading, matching, judging, sessions, the
  graph router and the CLI are in `engine.py`. The A3 split would move the
  sessions (E10), the router (E16) and the CLI (E20) here and the `.kg` reader,
  matching and judging to `marco/knowledge/` and `marco/reasoning/`
  ([structure-audit.md](structure-audit.md) A3); it is frozen
  ([marco.md](marco.md)).
- **The app state and turn handler.** `views/kgpack_ui.AppState`
  (`AppState.turn`, `views/kgpack_ui.py:814`); planned target
  `marco/runtime/app.py`, not created.
- **Per-conversation reasoning.** [`marco.reasoning`](marco.reasoning.md).
- **Building the concept graph.** `marco.knowledge.ingest.text` (`build`,
  `extract_concepts`).

## Depends on

- Root modules: `engine` (`conversation.py`: `load`, `Session`,
  `forward_rels`, lazily in `game` mode; `graph_dialogue.py`: `load`, `judge`,
  `pick_graph`, lazily); `encoder` (`explain.py:18`: `DEVICE`, `MODEL`, `_abs`,
  `_embed`, `_embed_all`, `_model`, `_embed_sub`, `_embed_sub_all`,
  `mask_numbers`, `split_fragments`); `language_components` (`explain.py:65`:
  `_language_path`, lazily). `explain.py` does not import `engine`.
- `marco.knowledge.ingest.text`: `build` (`conversation.py:46`, lazily) and
  `extract_concepts` (`explain.py:17`).
- `marco.language.hangul` (`graph_dialogue.py:22`; `explain.py`, lazily) and
  `marco.language.numerals.parse_numeral` (`graph_dialogue.py:250`, lazily).
- Inside the package: `conversation` imports `explain` (lazily, in `guide` mode).
- Third party: `numpy` (in `explain.py`, imported inside functions).
- `conversation.py` and `explain.py` put the repository root on `sys.path` at
  import, so the root modules above resolve when the file is run as a script.
  `graph_dialogue.py` does not; it expects the root to be importable already.
- Back edge: `engine.py` imports `marco.runtime.explain` inside functions
  (lines 3599 and 3869) and calls `explain.open_` and `explain.ask`, while
  `conversation.py` and `graph_dialogue.py` import `engine`; the package and
  `engine` reach each other at call time.

## Public interface

| Name | Imported by (outside tests) | Test |
| --- | --- | --- |
| `conversation.Conversation`, `.reply`, `.state`, `Reply` | no module imports it; the command line runs it (its docstring still shows the old `python nai.py`) | `tests/test_nai.py` (`test_game_exposes_forward_path`, `test_game_hides_untrusted_topic`, `test_guide_updates_context_after_every_reply`), with `engine` and `explain` replaced by stubs |
| `conversation.build_graph` | none | no test names it |
| `explain.open_` | `engine.py`, `marco/runtime/conversation.py`, `tools/grade_questions.py`, `tools/self_learning.py` | no test names it (`tests/test_nai.py` stubs it) |
| `explain.ask` | `engine.py`, `tools/grade_questions.py`, `tools/self_learning.py`; `marco/runtime/conversation.py` calls it through the module it imported (line 117) | no test names it (`tests/test_nai.py` stubs it) |
| `explain.DialogueMemory` | `marco/runtime/conversation.py` | no test names it (`tests/test_nai.py` stubs it) |
| `explain._abs` | `tools/grade_questions.py`, `tools/self_learning.py` | no test names it |
| `graph_dialogue.GraphDialogueBackend`, `.parse` | no module names the class; `backend()` builds it, and `language_components.resolve_backend` calls `.parse` on what the pack string returns | `tests/test_graph_dialogue.py` (nine tests, e.g. `test_aliases_come_from_the_graph_not_the_language_pack`, `test_without_a_router_no_dialogue_is_claimed`) |
| `graph_dialogue.backend` | `language_components.py` through the pack string | no test names it |

`explain.py`'s inline self-check (`python -m marco.runtime.explain --check`,
`_selfcheck`) is not run by any file in `tests/`; how often it passes is not
measured. `tests/test_understanding_r1.py` and `tests/test_understanding_r3.py`
read `marco/runtime/explain.py` only as text, to check that no development
sentence is written in it.
