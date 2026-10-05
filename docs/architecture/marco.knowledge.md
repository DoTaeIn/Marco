# `marco.knowledge`

Written 2026-10-01 against commit `e3a6394`; checked 2026-10-01 against `d9c9559`, which
changes none of the files named here.

## Purpose

Give MARCO's knowledge code one package. Today it holds no graph code (that is still in
`engine.py`); goal S4 ([file moves](../ko/2026-09-24-file-moves-goal.md)) created it for
two kinds of moved file: the local definition index (`local_definitions.py` before S4) and the readers
in the subpackage [`marco.knowledge.ingest`](marco.knowledge.ingest.md). The target map
([target-map.json](target-map.json)) puts the package on layer 3: it may import only
targets on layers 0 to 3 (`marco`, `marco._paths`, `marco.progress`, `marco.language`,
`marco.perception`, `marco.storage` and itself), not memory, reasoning, learning, host,
cognition or runtime.

## Owns

| Module | Lines | What |
| --- | --- | --- |
| [`__init__.py`](../../marco/knowledge/__init__.py) | 0 | empty; exports nothing |
| [`definitions.py`](../../marco/knowledge/definitions.py) | 179 | `DefinitionLookup`: a read-only index over a JSONL file of wiki definitions (`말`, `정의` per line). It strips a fixed list of Korean question endings ("…이 뭐야", "…란 무엇인가요", "…에 대해 알려 줘") to find one headword of at least two characters, and answers only when that headword matches exactly, or matches with its spaces removed. The answer is the first sentence of the source definition, cut at 480 characters, marked `"source": "data/위키/정의문.jsonl", "verified": True`; a homonym guide line ending in "다음 뜻으로 쓰인다" or "다음과 같은 뜻이 있다" is refused. Comparison questions ("A와 B의 차이가 뭐야") need two exact headwords. The index is a SQLite file built on first use, by default `/private/tmp/nai-definition-index.sqlite`, rebuilt when the JSONL is newer or the file lacks the `compact` column |
| [`ingest/`](../../marco/knowledge/ingest/) | see its document | the subpackage [`marco.knowledge.ingest`](marco.knowledge.ingest.md) |

## Does not own

- The `.kg` reader, `load()` and node matching. They are still in
  `engine.py`; the structure audit ([structure-audit.md](structure-audit.md), rows E3 and
  E7) names `marco/knowledge/graph.py` and `marco/knowledge/matching.py` as their targets.
  The same audit says these splits (its Phase 3) are pending and frozen until MARCO 1.
- The definition data. `data/위키/정의문.jsonl` is read, never written; the caller passes its path.
  `views/kgpack_ui.py:261–266` passes the pack's copy (a path under the overlay when the pack
  has none) and a cache path under the overlay.
- When a definition is used. `engine._local_definitions` (engine.py, the function at line
  3518) and `views/kgpack_ui.py` decide that. The engine returns no definition, and goes on
  to its graphs, when `DefinitionLookup` cannot be constructed or `lookup_any` raises
  `OSError` or `ValueError` (engine.py:3525–3537).
- Learning from definitions. The dictionary and web readers are in `ingest/`; candidate
  graph authoring is in [`marco.learning`](marco.learning.md).

## Depends on

- `definitions.py`: the Python standard library only (`json`, `re`, `sqlite3`, `pathlib`).
- `ingest/`: see [marco.knowledge.ingest.md](marco.knowledge.ingest.md); it imports
  `engine`, `encoder`, `language_components`, `marco.language`, `marco.perception`,
  `marco.progress` and `kiwipiepy`.

## Public interface

| Name | Imported by | Test |
| --- | --- | --- |
| `DefinitionLookup(source, cache=...)` | `engine.py:3527` (lazily), `views/kgpack_ui.py:40` | `tests/test_local_definitions.py` (five tests: three build it directly, one reaches it through `engine.answer`, one reads the JSONL only); `tests/test_general_knowledge_coverage.py::test_local_definition_coverage_across_domains` |
| `.lookup(text)` | `views/kgpack_ui.py:960` | `tests/test_local_definitions.py::test_definition_question_forms_and_domains`, `test_definition_lookup_refuses_dialogue_and_empty_disambiguation`; `tests/test_general_knowledge_coverage.py::test_local_definition_coverage_across_domains` |
| `.lookup_any(text)` | `engine._local_definitions` (engine.py:3535) | `tests/test_local_definitions.py::test_engine_uses_local_definition_adapter_for_long_tail_term` and the `engine.answer` half of `test_local_definition_comparison_requires_two_exact_terms` (both through the engine) |
| `.compare(text)`, `.comparison_terms(text)`, `.compare_target(target)`, `.lookup_term(term)` | `views/kgpack_ui.py` (lines 992, 964, 962, 906) | `.compare`: `tests/test_local_definitions.py::test_local_definition_comparison_requires_two_exact_terms`; the other three: no test names them |
| `.question_term(text)` | used only inside `definitions.py` | no test names it |
| `marco.knowledge.ingest` | subpackage | per name in [marco.knowledge.ingest.md](marco.knowledge.ingest.md) |
