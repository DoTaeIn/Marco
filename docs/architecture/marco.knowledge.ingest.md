# `marco.knowledge.ingest`

Written 2026-10-01 against commit `c8ad9a5`; checked 2026-10-01 against `5c50e90`, which
changes none of the files named here.

## Purpose

Read outside material (text folders, a dictionary export, PDF and PPTX files, web pages)
into graph form without inventing what the source does not say. Three docstrings state a
limit: `documents.py` keeps unresolved pronouns and figures without verified facts as review
items, not facts; `web.py` never writes fetched sentences into a `.kg` file, only into its
sidecar; `text.py` says it makes only two edge kinds and never "A implies B", but `build`
also puts `상위` and `정의` edges and any hand-written relations it is given into `엣지`
(text.py:846–857). Goal S4 moved the four modules here from the root (`build`,
`dict_extract`, `document_kg`, `web_learn` before S4; [target-map.json](target-map.json),
`modules` and `moved_in_s4`).

## Owns

| Module | Lines | What |
| --- | --- | --- |
| [`__init__.py`](../../marco/knowledge/ingest/__init__.py) | 0 | empty; exports nothing |
| [`text.py`](../../marco/knowledge/ingest/text.py) | 974 | a folder of `.txt`/`.md` to a concept graph: splits by law article, markdown heading or paragraph; one node per concept (compound nouns joined, via `kiwipiepy`); edges `설명함` (the passage title is this concept), `같은조문` (same passage), `상위` (compound-noun head) and `정의` (definition clause), plus hand-written relations and synonyms passed to `build` (the CLI reads `_관계.json` and `_동의어.json` in the folder); definition genus and target extraction; source excerpts, their kinds from hand labels (the CLI reads `_발췌꼴.json`) or the passage classifier, else `진술`. Nodes below weight `KG_TOPIC_MIN` (default 10) are dropped unless they are titles, taught or related. CLI with `--check` self-check |
| [`dictionary.py`](../../marco/knowledge/ingest/dictionary.py) | 347 | the National Institute of Korean Language basic dictionary's XML files (`krdict_*.xml`, default folder `data/사전`) to genus, action and target per noun headword; genus chains, schema seeds, concurrent-work seeds, sense picking. `--check` self-check; without it the CLI prints the docstring |
| [`documents.py`](../../marco/knowledge/ingest/documents.py) | 507 | PDF and PPTX to a claim graph: only sentences with a page or slide position become claims; sentence kinds come from the language pack's `document_kinds`, and a pack without them classifies nothing; a sentence matching the pack's pronoun pattern (`지시어시작`) goes to review. An analysis is `sufficient` with at least three claims and no too-little-PDF-text warning; `to_graph` refuses one that is not. Figures go through `marco.perception.visual`; a visual fact becomes a claim only at confidence 0.70 or more and, in a PDF, only of a kind the page text allows. CLI `_main` |
| [`web.py`](../../marco/knowledge/ingest/web.py) | 1347 | open-web search through DuckDuckGo's lite HTML page (`https://lite.duckduckgo.com/lite/`), page reading into complete sentences, topic and role evidence checks, and storage in a sidecar `<graph>.수집.jsonl` beside the graph under a file lock (`<sidecar>.lock`). Limits from `KG_LEARN_MAX_TOPICS` (200), `KG_LEARN_MAX_RECORDS` (20), `KG_LEARN_MAX_BYTES` (5 MiB), `KG_LEARN_COOLDOWN` (300 s). `load()` is `engine.load()` with the collected records stacked on under prefixed node names (`지식_`, `출처_`). CLI `_main` with `--check` self-check |

The sidecar files are one of "the existing learning routes" the
[freeze decision](../ko/2026-09-22-freeze-decision.md) keeps as they are; it lists
"promotion of web or document knowledge" as not in MARCO 1.

## Does not own

- When reading happens. The callers in the public interface below decide: `views/kgpack_ui.py`
  (document upload, web learning when a question is unknown), `goal_runtime.py`
  (`GoalRuntime.research`, read-only web research; `plan_learning`; `_run`, which saves
  approved sources with `save_verified_knowledge`), `marco/runtime/conversation.py`,
  `marco/runtime/explain.py`, `marco/learning/authoring.py`, `purpose_graph.py` and two tools.
- `purpose_graph.py` and the case reader in `engine.py` (`read_case`, `compile_case`). The
  target map names `marco.knowledge.ingest.purpose` and `marco.knowledge.ingest.cases` for
  them; the structure audit ([structure-audit.md](structure-audit.md)) says these splits
  (its Phase 3) are pending and frozen until MARCO 1.
- Candidate graph authoring from the dictionary: [`marco.learning`](marco.learning.md)
  (`authoring.py`).
- OCR and figure analysis: `marco.perception.visual`.

## Depends on

- `text.py`: `marco.language.passage_components`; lazily `marco.language.hangul`, `kiwipiepy`.
- `dictionary.py`: lazily `marco.language.hangul`, `marco.progress`.
- `documents.py`: `marco.perception.visual`; lazily `language_components` (root); the
  `pdftotext`, `pdftoppm` and `pdfimages` programs. `pdftotext` is taken from
  `NAI_PDFTOTEXT`, then `PATH`; `pdftoppm` and `pdfimages` from `PATH`; each falls back to a
  fixed absolute path in a cache directory under the owner's home (documents.py:81–83,
  149–158). Renders set `FONTCONFIG_FILE` to `/opt/homebrew/etc/fonts/fonts.conf` when that
  file exists.
- `web.py`: `engine`, `encoder` (root); lazily `language_components`, `marco.knowledge.ingest.text`,
  `kiwipiepy`. At import it sets `KG_ENCODER=문자` when unset (web.py:39). Network through
  `urllib`: the search page and each result URL.
- All four modules put the repository root on `sys.path` at import (`parents[3]` of the file).

## Public interface

| Name | Imported by | Test |
| --- | --- | --- |
| `text.build` | `marco/runtime/conversation.py:46` | no test names it |
| `text.extract_concepts` | `marco/runtime/explain.py:17`, `tools/self_learning.py:90`, `web.py` | no test names it |
| `text.extract_target` | `purpose_graph.py:31` | no test names it |
| `dictionary.read_dict`, `.build_chain` | `marco/learning/authoring.py:178`, `tools/build_concept_net.py:59` | no test names them |
| `dictionary.find_schema` | `marco/learning/authoring.py:200` | no test names it |
| `documents.learn`, `.DocumentKGError` | `views/kgpack_ui.py` (lines 756, 1612) | `DocumentKGError`: `tests/test_document_kg.py::test_insufficient_input_does_not_become_knowledge`; `learn`: no test names it |
| `documents.Unit`, `.analyze_units`, `.read_pptx`, `.to_graph`, `.add_visual_claims` | tests only | `tests/test_document_kg.py` (five tests; all but `add_visual_claims`), `tests/test_document_visual.py` (three tests; `analyze_units`, `add_visual_claims`) |
| `web.search`, `.read_source`, `.question_word` | `goal_runtime.py` | `tests/test_learning_question_flow.py` patches them, e.g. `test_research_sends_only_the_needed_topic_and_reports_evidence_status` |
| `web.external_need`, `.relation_evidence_sentences`, `.evidence_coverage` | `goal_runtime.py` | no test names them; `GoalRuntime.research` runs them in `tests/test_learning_question_flow.py` |
| `web.extract_topic`, `.load` | `goal_runtime.py`, `views/kgpack_ui.py` | `tests/test_learning_question_flow.py::test_natural_question_extracts_its_content_topic` |
| `web.save_verified_knowledge` | `goal_runtime.py` | `tests/test_learning_question_flow.py::test_approved_sources_are_saved_without_a_second_search` |
| `web.collect_path`, `.read_collected`, `.ask` | `views/kgpack_ui.py` | `tests/test_learning_question_flow.py::test_approved_sources_are_saved_without_a_second_search` |
| `web.learn`, `.topic_related` | `views/kgpack_ui.py` | no test names them |
| `web.LearnFailed` | `views/kgpack_ui.py`, `goal_runtime.py` | no test names it |
| every other name | used only inside its own module, except `text.stopwords` and `text._kiwi`, which `web.py` reads | `documents._pptx_visuals`: `tests/test_document_kg.py::test_pptx_media_is_bound_to_its_slide_location`; `web._read_dialect` is patched in `tests/test_learning_question_flow.py::test_question_detection_follows_language_style_data`; the rest: no test names them |
