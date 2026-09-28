# Structure audit — refactor Phase 0

> **Dated record.** Every number here describes commit `6195040` and is
> re-measurable with the commands below. Since then `s2-minimal` created
> `marco/` and `marco/language/` (the `realize` seam) and the root has the same
> 61 `.py` files. Numbers for the current commit are in the root
> [README](../../README.md#measured-at-78bd062); package documents are listed in
> [docs/README.md](../README.md).

Goal: `docs/ko/2026-09-22-structure-audit-goal.md`. Written 2026-09-22.
Audited commit: **`6195040`** (`main` = `origin/main`). Nothing was moved, renamed or
deleted. New files: this document, `docs/architecture/target-map.json`,
`tools/import_graph.py`. Edited: `README.md` (architecture diagrams, layout by
subsystem, routing rows re-measured at `6195040`).

Every number below is re-measurable:

```bash
python tools/import_graph.py --rev 6195040                  # A2
python tools/import_graph.py --rev 6195040 --uses engine    # A3 callers
python tools/import_graph.py --rev 6195040 --targets docs/architecture/target-map.json   # A1 rows, A6 layers
```

The tool reads blobs straight from git (`git cat-file --batch`), so it measures a
commit, not whatever the shared working tree holds.

## Status

| Item | Done | Measurement |
| --- | --- | --- |
| A0 baseline | yes | 61 root `.py`, 31,396 lines; suite 770 passed / 4 failed / 0 skipped, 1206.91 s |
| A1 classification | yes | 61 rows = 61 root files; 0 TBD; 55 sure, 6 unsure (reason given); tool: `rows: 61 missing: 0 TBD: 0` |
| A2 import graph | yes | 177 files, 364 module edges, 194 unit edges; 2 runtime cycles (SCC 6 + 2, 5 elementary), 0 import-time cycles |
| A3 `engine.py` | yes | 20 parts, spans sum 6072 / 6072 lines, callers from `--uses engine` (40 importers) |
| A4 `nai` artifacts | yes | 4 artifacts + `NAI_*` env prefix (6 variables), each with target and readers at file:line |
| A5 `mco/` | yes | top-level, layer 11; 0 static imports of MARCO; 4 names loaded by `importlib` |
| A6 target layout | yes | tree + layer rule; `marco/language/` to file names; predicted after move: 9 upward edges, 0 cycles once they are fixed |
| A7 do-not-touch | yes | 22 root `.py` + `views/kgpack_ui.py` + 2 packs + 17 bench + 67 tests, owner per file |
| A8 phase plan | yes | Phases 1–5, each with files, shim, command, numeric gate against A0 |

---

## A0. Baseline

- Commit `6195040`, `main`, 2026-09-22 09:57 +0900. 177 `.py` files in the tree,
  **61 at the root, 31,396 lines at the root.**
- Full suite, once:

  ```bash
  git archive 6195040 | tar -x -C <scratch>/a0      # export of the commit
  # + this clone's gitignored files (not __pycache__/.mypy_cache/.pytest_cache), APFS-cloned in
  #   (data/위키 90M corpus, data/models, .nai-tools, NAI.kgpack, .vec_*.npz caches)
  cd <scratch>/a0 && KG_ENCODER=문자 python -m pytest -q -p no:cacheprovider -rfEs
  ```

  Python 3.13.9 (anaconda), macOS 26 (Darwin 25.6.0).

  | passed | failed | skipped | errors | time | exit |
  | --- | --- | --- | --- | --- | --- |
  | **770** | **4** | 0 | 0 | 1206.91 s (20:06) | 1 |

  | Failing test | Cause | Also fails elsewhere? |
  | --- | --- | --- |
  | `tests/test_alma_integrated_reproduction.py:31` | asserts `process_max_rss_supported is False`; macOS reports RSS | passes on the Windows clone (plan §5: 766 passed there) — machine-dependent |
  | `tests/test_experience_concept_reproduction.py:22` | intentionally-wrong run reports `execution_error == 1`, test wants 0 | not investigated (found, not fixed) |
  | `tests/test_response_composer.py:153` (`…compare…`) | verdict `입력이해실패` ≠ `원문정의비교` | known machine-dependent (plan §5) |
  | `tests/test_response_composer.py` (`…summary…`) | same family: `'manager'` ≠ `extractive_grounded_response` | known machine-dependent (plan §5) |

- Two more baselines on the same export, used as Phase 3 gates:

  | Command | Exit | Time | Output |
  | --- | --- | --- | --- |
  | `KG_ENCODER=문자 python engine.py --check` | **1** | 3 s | `AssertionError: graphs/graph_일상추론.kg` at engine.py:4768 (`2등인 사람을 추월했습니다` expected to route to `graph_순위_추월.kg`) |
  | `KG_ENCODER=문자 python -m bench.routing_benchmark --답` | 0 | 185 s | `제자리 2807/6912 (40.6%)  답함 5259 (76.1%)  밖 거절 24/24` — the whole stdout, 92 bytes, sha1 `d1937d7e1eb111e46b04da6f033a75049fb0cf32` |

- Why an export and not the working tree: at audit time the shared tree held another
  session's uncommitted merge of `repair-and-english` (reset at 15:12 by that session,
  files still modified). Neither state is a commit. The export is the commit plus
  this clone's ignored data, so the count is reproducible on this machine.
- Lines per root file (`wc -l`, commit `6195040`):

```text
engine                 6072  act                     343  alma_cli                123
reasoning_context      2971  graph_inference         336  universal_agent         119
explain                2311  kgpack                  308  proof_chunking          104
alma_runtime           2071  semantic_parser         294  expression_graph        103
vision                 1725  purpose_graph           288  passage_classifier       97
web_learn              1344  kgbin                   262  expression_learning      93
relational_semantics   1170  graph_dialogue          259  rule_learning            91
codegen                 982  response_composer       257  verbal_expression        87
build                   971  pack_model              221  conversation_store       85
document_visual         643  goal_runtime            210  document_vlm             81
frame_induction         607  alias_diag              188  affect_state             65
hangul                  586  routing_benchmark       180  semantic_feedback        58
self_authoring          579  local_definitions       179  document_pose            58
encoder                 567  alma_environment        177  document_objects         44
document_kg             506  nai                     168  passage_components       38
language_components     502  state_engine            164  numeral_semantics        35
action_runtime          453  intelligence_check      151  output_contracts         20
experience_concepts     401  progress                144  conftest                 14
self_learning           360  autocoder               144  situation_reasoner       13
yardstick               353  input_understanding     140
dict_extract            344  cache_tool              137
```

---

## A2. Import graph

Tool: `tools/import_graph.py` (new, stdlib only). AST walk of every `.py`; imports
resolved the way the repo runs (root on `sys.path` via `conftest.py`; a script's
own directory first; relative imports inside packages; a bare name that matches
exactly one module in a plain directory counts as a `sys.path.insert` import).
Edge kinds: `top` (runs at import), `lazy` (inside a function), `main` (under
`if __name__ == "__main__":`), `typing`, `dynamic` (`import_module("literal")`).
A unit is one root file, or one top-level directory.

```text
source: 6195040 (6195040)
python files: 177  root .py: 61  units: 67 (dirs: bench, collectors, docs, tests, tools, views)
module edges: 364 {'lazy': 132, 'main': 2, 'top': 230}  unit edges: 194  root->root: runtime 111, top 44

cycles                  SCCs  sizes                      elementary
  all_modules_runtime      2  6,2                        5
  all_modules_top          0  -                          0
  root_modules_runtime     2  6,2                        5
  root_modules_top         0  -                          0
  units_runtime            2  6,2                        5
  units_top                0  -                          0

unit                              kind     files     out_u      in_u     out_m      in_m   in_root  in_tests   top_out  lazy_out
engine                            root         1         9        16         9        40        13        22         2         7
relational_semantics              root         1         7        10         7        29         8        19         0         7
kgpack                            root         1         1         5         1        22         2        13         0         1
reasoning_context                 root         1         9         5         9        21         2        17         2         7
graph_inference                   root         1         0         9         0        17         6         7         0         0
hangul                            root         1         0        13         0        15        11         3         0         0
state_engine                      root         1         2         6         2        13         3         7         0         2
encoder                           root         1         2        10         2        12         7         3         0         2
language_components               root         1         0         8         0        12         6         5         0         0
alma_runtime                      root         1         6         4         6        11         1         4         3         3
pack_model                        root         1         5         8         5        11         5         3         2         3
semantic_parser                   root         1         2         4         2        10         1         6         0         2
conversation_store                root         1         0         3         0         7         0         2         0         0
numeral_semantics                 root         1         0         6         0         6         5         1         0         0
progress                          root         1         0         6         0         6         6         0         0         0
build                             root         1         2         5         2         5         5         0         1         1
document_visual                   root         1         0         3         0         5         1         1         0         0
input_understanding               root         1         1         3         1         5         0         3         1         0
alma_environment                  root         1         0         3         0         4         1         1         0         0
experience_concepts               root         1         0         3         0         4         1         1         0         0
explain                           root         1         3         4         3         4         3         0         2         1
expression_graph                  root         1         1         4         1         4         3         1         0         1
goal_runtime                      root         1         1         2         1         4         0         3         1         0
local_definitions                 root         1         0         3         0         4         1         2         0         0
action_runtime                    root         1         2         2         2         3         1         2         0         2
document_kg                       root         1         2         2         2         3         0         2         1         1
expression_learning               root         1         1         2         1         3         1         2         0         1
frame_induction                   root         1         3         3         3         3         2         1         2         1
output_contracts                  root         1         1         3         1         3         2         1         0         1
proof_chunking                    root         1         1         3         1         3         1         1         1         0
rule_learning                     root         1         1         3         1         3         2         1         1         0
self_authoring                    root         1         6         3         6         3         2         0         4         2
web_learn                         root         1         3         3         3         3         1         1         2         1
yardstick                         root         1         4         2         4         3         1         0         2         2
act                               root         1         1         2         1         2         2         0         1         0
affect_state                      root         1         1         2         1         2         0         1         1         0
dict_extract                      root         1         2         2         2         2         1         0         0         2
kgbin                             root         1         2         2         2         2         1         1         0         0
passage_components                root         1         0         2         0         2         1         1         0         0
purpose_graph                     root         1         3         2         3         2         1         0         1         2
response_composer                 root         1         0         2         0         2         0         1         0         0
routing_benchmark                 root         1         2         2         2         2         2         0         2         0
graph_dialogue                    root         1         3         1         3         1         0         1         1         2
nai                               root         1         3         1         3         1         0         1         0         3
passage_classifier                root         1         1         1         1         1         0         1         0         1
verbal_expression                 root         1         2         1         2         1         1         0         1         1
alias_diag                        root         1         3         0         3         0         0         0         2         1
alma_cli                          root         1         4         0         4         0         0         0         2         2
autocoder                         root         1         1         0         1         0         0         0         1         0
cache_tool                        root         1         1         0         1         0         0         0         0         1
codegen                           root         1         1         0         1         0         0         0         0         1
conftest                          root         1         0         0         0         0         0         0         0         0
document_objects                  root         1         0         0         0         0         0         0         0         0
document_pose                     root         1         0         0         0         0         0         0         0         0
document_vlm                      root         1         0         0         0         0         0         0         0         0
intelligence_check                root         1         2         0         2         0         0         0         2         0
self_learning                     root         1         2         0         2         0         0         0         0         2
semantic_feedback                 root         1         2         0         2         0         0         0         1         1
situation_reasoner                root         1         1         0         1         0         0         0         1         0
universal_agent                   root         1         1         0         1         0         0         0         1         0
vision                            root         1         0         0         0         0         0         0         0         0
bench                              dir        26        18         2        18        15         0        14        27        20
views                              dir         1        16         2        16        15         0        11        14         2
tests                              dir        75        38         1        50         1         0         0       131        36
collectors                         dir         3         0         0         0         0         0         0         0         0
docs                               dir         4         5         0         5         0         0         0         5         0
tools                              dir         7         4         0         4         0         0         0         2         2

root_modules_runtime SCC (6): expression_graph frame_induction output_contracts pack_model relational_semantics verbal_expression
root_modules_runtime SCC (2): self_authoring yardstick

pack-declared: styles/한국어.json -> graph_dialogue:backend
resolved via sys.path insert: tests/test_answer_quality_scoring.py: answer_quality -> bench.answer_quality
unresolved dynamic: self_learning.py:139: import_module('위키')
third-party (bench): pandas
third-party (build): kiwipiepy
third-party (document_objects): ultralytics
third-party (document_pose): ultralytics
third-party (document_visual): PIL numpy
third-party (document_vlm): PIL qwen_vl_utils torch transformers
third-party (encoder): numpy sentence_transformers
third-party (engine): numpy
third-party (explain): numpy
third-party (kgbin): numpy
third-party (routing_benchmark): numpy
third-party (tests): PIL numpy pytest
third-party (vision): PIL numpy scipy skimage
third-party (web_learn): kiwipiepy
```

Cycles, with the lines that make them (all `lazy`; none can fail at import time):

| SCC | Edges |
| --- | --- |
| 6 modules | `pack_model.py:186` → relational_semantics, `:190` → expression_graph, `:195` → output_contracts; `relational_semantics.py:51`, `marco/language/realizer/contracts.py:10`, `marco/language/arithmetic_spoken.py:14` → `pack_model.development_model`; `relational_semantics.py:805,860,891` → frame_induction; `marco/language/frames.py:23` → relational_semantics (top); `marco/language/arithmetic.py:12` → verbal_expression |
| 2 modules | `marco/learning/authoring.py:261` → yardstick; `bench/yardstick.py:55` → self_authoring |
| not a cycle | `engine.py:2740,3071` → kgbin (lazy); `kgbin.py:239` → engine only under `__main__` |

Importing modules, tests included: `engine` 40 (22 tests), `relational_semantics` 29,
`kgpack` 22, `reasoning_context` 21, `graph_inference` 17, `hangul` 15. `views/kgpack_ui` imports 16.
Entry points with 0 importers: `alias_diag`, `alma_cli`, `autocoder`, `cache_tool`, `codegen`,
`intelligence_check`, `self_learning`, `semantic_feedback`, `situation_reasoner`, `universal_agent`,
`vision`, and 3 subprocess scripts (`document_objects`, `document_pose`, `document_vlm`).

---

## A1. Every root file classified

Read from the code (module docstring, every top-level definition and its
docstring, and the import sites above), not from the name. Target paths use the
A6 layout. "+ split" rows name the primary target; the line ranges are in
`target-map.json` `splits` and in the reason column.

| File | Lines | What it does | Target | Conf | Reason / split |
| --- | --- | --- | --- | --- | --- |
| `marco/host/act.py` | 343 | Runs graph-chosen actions: matches an observation/error to an evidence node, walks -증명->/-충족-> to a registered tool, observe–recover–advance loop, trace sidecar | `marco/host/act.py` | sure | Executes host actions, so it sits with the permission boundary |
| `action_runtime.py` | 453 | JSON action-program contract: compile an induced definition, bind roles, execute emit/lookup/select/compute/when/call into one event's effects | `marco/reasoning/actions.py` | sure |  |
| `marco/language/realizer/affect.py` | 65 | Session-only affect expression mode from the user's own affect words (pack-declared); `decorate` prefixes a verified answer; never changes facts | `marco/language/realizer/affect.py` | unsure | Expression-only today (Expression Selector input). Moves to `cognition/` if affect ever feeds decisions |
| `alias_diag.py` | 188 | Diagnostic CLI: nodes that absorb other nodes' phrasings, nodes short of aliases | `tools/alias_diag.py` | sure |  |
| `alma/cli.py` | 123 | ALMA command line over `AlmaRuntime` (turns, memory, recall, mental, cycles, environment, backup) | `alma/cli.py` | sure |  |
| `alma/environment.py` | 177 | Bounded local observation environment for ALMA: read adapters, persisted run advanced by a step budget | `alma/environment.py` | sure |  |
| `alma/runtime.py` | 2071 | `AlmaRuntime`: personal state (logs, episodic/semantic/procedural memory, mental states, goals, affect, preferences, capabilities, cycles, rule/asset/shortcut proposals) over `ReasoningContext` | `alma/runtime.py` | sure | Target is certain; §4.5 split (identity/emotion/preference/memory) is Phase 3+ |
| `experiments/autocoder.py` | 144 | Demo tool set for `marco/host/act.py`: assembles code from templates (two deliberately buggy), runs it, applies graph-chosen fixes | `experiments/autocoder.py` | sure |  |
| `marco/knowledge/ingest/text.py` | 971 | Text folder → concept graph JSON: passage/article splitting, compound-noun concepts (kiwipiepy), definitions, genus/target, concept net, excerpts | `marco/knowledge/ingest/text.py` | sure |  |
| `cache_tool.py` | 137 | Reports vector caches and deletes dead ones (keys are content hashes) | `tools/cache_tool.py` | sure |  |
| `experiments/codegen.py` | 982 | Language-neutral algorithm blueprints → source in code dialects (`styles/코드`), prose ↔ blueprint parsing, mental evaluation, mutate/fix search, regressions. 0 importers | `experiments/codegen.py` | sure |  |
| `conftest.py` | 14 | Puts the repo root on `sys.path` for pytest | root (stays) | sure | Stays at root |
| `conversation_store.py` | 85 | JSON store of projects and chats at `.nai/conversations.json` | `marco/storage/conversations.py` | sure |  |
| `marco/knowledge/ingest/dictionary.py` | 344 | National dictionary XML → genus/action/target chains, schema/concurrency seeds, sense picking | `marco/knowledge/ingest/dictionary.py` | sure |  |
| `marco/knowledge/ingest/documents.py` | 506 | PDF/PPTX → conservative claim graph with page positions; pack-declared sentence rules; visual observations as review items | `marco/knowledge/ingest/documents.py` | sure |  |
| `marco/perception/objects.py` | 44 | Subprocess script: YOLO boxes → JSON | `marco/perception/objects.py` | sure |  |
| `marco/perception/pose.py` | 58 | Subprocess script: YOLO pose keypoints → JSON | `marco/perception/pose.py` | sure |  |
| `document_visual.py` | 643 | Image → verifiable observations: OCR merge (Vision binary + Tesseract), chart/table structure, objects, pose, contacts, spatial relations, optional VLM hypothesis | `marco/perception/visual.py` | sure |  |
| `document_vlm.py` | 81 | Local VLM adapter; output kept as hypothesis only | `marco/perception/vlm.py` | sure |  |
| `encoder.py` | 567 | `EncoderRuntime` (pack-selected), character n-gram/jamo vectors, neural model loader, embed helpers; surface ops: `view_lang`, `strip_english_shell`, `strip_fillers`, `split_fragments` | `marco/language/encoder.py` + split | sure |  |
| `engine.py` | 6072 | Argument engine: graph format, matching, judgement, sessions, router, answer entry, realization, authoring suggestions, diagnostics, selfcheck, CLI — 20 parts, see A3 | `marco/runtime/engine.py` + 19 more (A3) | sure | Split per A3 |
| `marco/learning/concepts.py` | 401 | `ExperienceConceptStore`: bounded concept candidates abstracted from saved action events, applied only as derived classification with supporting events | `marco/learning/concepts.py` | sure |  |
| `explain.py` | 2311 | Second answer pipeline for marco/knowledge/ingest/text.py concept graphs: question intent, node/typo matching, path explanation, excerpts, procedures, code weaving, `DialogueMemory`, grading, Mermaid. Answers are guidance, not verdicts | `marco/runtime/explain.py` | unsure | Not proof explanation as §4.19 assumed. Phase 3 split: matching → knowledge/matching, `_link_form`/`fit_particle` → realization/grammar, `DialogueMemory` → cognition, `_selfcheck` (337 lines) → runtime/selfcheck |
| `marco/language/arithmetic.py` | 103 | Parses a complete math expression (Python AST as syntax only) into an affine operation graph; `solve` for one variable | `marco/language/arithmetic.py` | unsure | `solve` (40 lines) is reasoning; kept with its parser while it has one caller path |
| `marco/learning/expressions.py` | 93 | Supervised paraphrase-template proposals gated by separate validation cases | `marco/learning/expressions.py` | sure |  |
| `marco/language/frames.py` | 607 | Reads definition bodies by aligning to known examples; particle-marked chunks; induce/apply meaning frames; `read_event`; question detection | `marco/language/frames.py` | sure |  |
| `goal_runtime.py` | 210 | `GoalRuntime`: goal text → approvable plan (work, learning, read-only web research), approval hashing, execution only through registered tools (no shell) | `marco/cognition/goals.py` + split | unsure | Planning is cognition; 147–210 (`_approve_once`, `_run`) is the host permission boundary → `marco/host/permissions.py` (W4 seam). Split in Phase 3 |
| `graph_dialogue.py` | 259 | `GraphDialogueBackend`: the pack-declared dialogue backend (`styles/한국어.json:2993` `graph_dialogue:backend`); asks the KG for dialogue words, computes request endings by inflection | `marco/runtime/graph_dialogue.py` | sure | Imports `engine`, so it sits in runtime. Pack string or a shim must follow the move |
| `graph_inference.py` | 336 | Finite positive Horn-rule closure, `current_facts` projection, replayable proof bundles | `marco/reasoning/inference.py` | sure |  |
| `marco/language/hangul.py` | 586 | Hangul syllable arithmetic, jamo, particle pick/attach/strip/fix, pack-declared `inflect`, clause spans, word spans, yes/no word lists | `marco/language/hangul.py` | sure | §4.19 said `language/grammar.py`; that name is reserved for the Grammar Realizer |
| `marco/language/understanding.py` | 140 | Structures a user utterance: segments, command/URL safety, session context, goals, via pack + `DialogueBackend` | `marco/language/understanding.py` | sure |  |
| `bench/intelligence_check.py` | 151 | Per-ability test: out-of-domain refusal, traps, paraphrase vs control, sense, multi-turn | `bench/intelligence_check.py` | sure |  |
| `kgbin.py` | 262 | Routing index → one flat mmap-able `.kgbin` (bit packing); `unpack` | `marco/storage/kgbin.py` | sure |  |
| `kgpack.py` | 308 | `.kgpack` ZIP with manifest, SHA-256 per file, default inputs, manager graph; write/read/unpack/selfcheck | `marco/storage/kgpack.py` | sure |  |
| `language_components.py` | 502 | Language pack: path choice (`NAI_LANGUAGE`), validation of every declared section, `decode_language_pack`; `DialogueBackend`, `TemplateBackend`, `resolve_backend` | `marco/language/pack.py` + split | sure | Split: 24–403 → `pack.py`, rest → `backends.py` |
| `marco/knowledge/definitions.py` | 179 | Read-only sqlite index over local wiki definitions for exact "X가 뭐야" questions | `marco/knowledge/definitions.py` | sure |  |
| `nai.py` | 168 | `Conversation`/`Reply`: one chat contract over `.kg` (engine) and `.json` (explain) graphs; `--build` CLI | `marco/runtime/conversation.py` | sure | See A4 |
| `marco/language/numerals.py` | 35 | Composes numbers from the pack's numeral vocabulary | `marco/language/numerals.py` | sure |  |
| `marco/language/realizer/contracts.py` | 20 | Applies declared output constraints to a verified numeric answer | `marco/language/realizer/contracts.py` | sure |  |
| `pack_model.py` | 221 | `PackModel`: selected model's assets (language, axioms, relational model, encoder), component loader, parser/expression/format factories; `development_model()` | `marco/storage/model.py` + split | sure | Split: 202–221 `development_model` → `runtime/model.py`; its 3 callers are the 6-module cycle |
| `marco/language/passages.py` | 97 | Passage-kind classifier learned from human labels (char n-grams, CV threshold) | `marco/language/passages.py` | sure |  |
| `marco/language/passage_components.py` | 38 | `PassageBackend` protocol, `StatementFallback`, pack-chosen `resolve_backend` | `marco/language/passages.py` | sure |  |
| `progress.py` | 144 | Dependency-free progress bar | `marco/progress.py` | sure | Layer 0; imported by 6 root files |
| `marco/learning/chunking.py` | 104 | Proposes/evaluates/invalidates shortcut rules for repeated Horn paths, keeping source proofs | `marco/learning/chunking.py` | sure |  |
| `purpose_graph.py` | 288 | Definition sentence → purpose-constrains-means `.kg` text; concurrent-role skeleton | `marco/knowledge/ingest/purpose.py` + split | sure | Split: 223–288 (selfcheck + CLI, uses `engine`) → `tools/purpose_graph.py` |
| `reasoning_context.py` | 2971 | `ReasoningContext`: per-conversation evidence ledger replayed per turn; definitions/programs; asks and completions; pointer resolution; incremental/correction replay; concept-relation reasoning; snapshot/restore; `turn()` | `marco/reasoning/context.py` | sure | Target certain; later split: ledger/snapshot → memory, asks/pointers → cognition |
| `relational_semantics.py` | 1170 | `RelationalParser`: compile pack examples into slot templates, `parse` sentences into facts/events, `learn`/`save` templates, `answer` by closure, `diagnose` | `marco/language/parser.py` + split | sure | Split: 1–42 → `language/facts.py`, 405–478 → `learning/templates.py`, 479–532 + 1077–1170 → `reasoning/semantics.py`, rest → `language/parser.py` |
| `marco/language/realizer/composer.py` | 257 | Selects verified evidence sentences; summary/explanation/plan along declared preconditions, goal steps, causal chain; comparison only on certified shared attributes | `marco/language/realizer/discourse.py` | sure | Seed of the Discourse Planner |
| `bench/routing_benchmark.py` | 180 | Held-out routing benchmark (last alias removed from the index) | `bench/routing_benchmark.py` | sure |  |
| `marco/learning/rules.py` | 91 | Supervised Horn-rule induction from aligned, corrected proof examples | `marco/learning/rules.py` | sure | §4.19 said `learning/structural.py`; content is rule induction |
| `marco/learning/authoring.py` | 579 | Dictionary → candidate graphs → lint → gate against stolen questions → admit/revert/re-audit; round records read by the UI | `marco/learning/authoring.py` | unsure | UI calls `one_round`, so it is library; imports `engine` + 2 benchmarks at top level — 4 upward edges (A6) |
| `self_learning.py` | 360 | Wrong answers → unknown words → wiki fetch → rebuild → re-grade; `import_module("위키")` never resolves | `tools/self_learning.py` | sure | 0 importers; CLI loop |
| `marco/learning/feedback.py` | 58 | CLI: diagnose a question; apply supervised rule corrections to a model file | `marco/learning/feedback.py` | sure |  |
| `marco/language/representation.py` | 294 | Candidate meaning JSON → validated state JSON (spans, types, relations); token-free `StructuralBackend` | `marco/language/representation.py` | sure |  |
| `situation_reasoner.py` | 13 | 13-line compatibility name forwarding to `semantic_parser`/`state_engine`. 0 importers | `marco/reasoning/state.py` | sure | Delete in Phase 5 |
| `state_engine.py` | 164 | Pure state transition/calculation over validated state JSON using KG axioms | `marco/reasoning/state.py` | sure |  |
| `experiments/universal_agent.py` | 119 | Demo tool set for `marco/host/act.py`: data pipeline raising real errors | `experiments/universal_agent.py` | sure |  |
| `marco/language/arithmetic_spoken.py` | 87 | Declared phrase grammar → bounded arithmetic graph; full match only | `marco/language/arithmetic.py` | sure |  |
| `experiments/vision.py` | 1725 | Image-vocabulary experiments: gradient descriptors, LSH words, Heaps' law, SLIC region graphs, COIL-100 angle/clutter tests. 0 importers | `experiments/vision.py` | sure |  |
| `marco/knowledge/ingest/web.py` | 1344 | Open-web search, page reading, topic extraction, relation evidence coverage, verified save to `.수집.jsonl`, stacking onto a graph, `ask` | `marco/knowledge/ingest/web.py` | unsure | Network fetch should become a runtime capability; overlay part stays in knowledge |
| `bench/yardstick.py` | 353 | Frozen question set from human-authored graphs; measures with those aliases removed | `bench/yardstick.py` | sure |  |

Totals: 61 rows, 31,396 lines. Where the reading disagrees with the plan's
first-pass guess (§4.19): `relational_semantics` is mostly a parser (language), not
reasoning; `explain` is a second answer pipeline, not proof explanation; `hangul`
keeps its name because `grammar.py` is the Grammar Realizer; `rule_learning` is rule
induction, not structural learning.

---

## A3. `engine.py` responsibilities

6072 lines. 20 parts. Spans cover 1–6072 exactly (checked by the tool: the split
map has no gap and no overlap). Callers are the modules that take a name from that
part (`--uses engine`); "engine only" means only `engine.py` itself uses it today.

| # | Responsibility | Lines | Count | Callers (non-test) | Moves to |
| --- | --- | --- | --- | --- | --- |
| E1 | Bootstrap (imports, HF env silencing, encoder re-exports) and answer orchestration: state-reasoning entry, verdict ranking, local definitions, `answer()`, leftover routing | 1–35, 3314–3608 | 330 | `bench/reasoning_transfer`, `bench/relational_learning`, `intelligence_check`, `yardstick` + 13 test files | `marco/runtime/engine.py` |
| E2 | Path helper `_here`/`_abs` (used by 6 parts) | 36–41 | 6 | `purpose_graph`, `routing_benchmark` | `marco/_paths.py` |
| E3 | Graph format and structure: relation vocabulary from `data/표지`, `.kg` reader, `포함:` include, verify, concept-net merge, `load()`, `reachable`/`counters`/`_dist`/`requirements` | 42–100, 125–486, 674–737, 1092–1121, 1322–1345 | 539 | `act`, `alma_runtime`, `bench/retrieval_diagnosis`, `cache_tool`, `graph_dialogue`, `intelligence_check`, `nai`, `purpose_graph`, `self_authoring`, `views/kgpack_ui`, `web_learn`, `yardstick` + 6 test files | `marco/knowledge/graph.py` |
| E4 | Refusal wording when no graph answers (`_not_found_reply`, hardcoded Korean at engine.py:108) | 101–124 | 24 | `views/kgpack_ui` | `marco/language/realizer/intent.py` |
| E5 | Yes/no answer words (`_definite_answer`, from `hangul`) | 487–503 | 17 | — (engine only) | `marco/language/understanding.py` |
| E6 | Learned-alias overlay `.학습.jsonl` read/write; unknown-utterance log `.미지.log` | 504–539, 1912–1928 | 53 | — (engine only) | `marco/storage/overlay.py` |
| E7 | Node, evidence and reference matching: example vectors + cache, `match`, alias/evidence erasure, `resolve_pronoun` | 540–584, 738–1091 | 399 | `act`, `bench/retrieval_diagnosis`, `intelligence_check`, `routing_benchmark`, `views/kgpack_ui`, `yardstick` + 1 test files | `marco/knowledge/matching.py` |
| E8 | Case markdown → episode graph (`read_case`, `compile_case`) | 585–673 | 89 | — (engine only) | `marco/knowledge/ingest/cases.py` |
| E9 | Argument judgement 인정/A/B1/B2/C: `judge`, `_judge_raw`, `numeric_verdict`, `_irrelevant_won` | 1122–1321, 1837–1861, 1896–1911 | 241 | `graph_dialogue`, `purpose_graph`, `routing_benchmark`, `self_authoring`, `views/kgpack_ui`, `yardstick` + 3 test files | `marco/reasoning/judge.py` |
| E10 | Sessions: `Session` (per-graph turns, value capture/transport/eval, activation), `Dialogue` (multi-graph), stateless `reply()` | 1346–1769, 2085–2087, 3661–3767 | 534 | `intelligence_check`, `nai`, `purpose_graph`, `views/kgpack_ui` + 8 test files | `marco/runtime/session.py` |
| E11 | Number extraction with Korean place units 조/억/만 (`extract_numbers`) | 1770–1836 | 67 | — (engine only) | `marco/language/numerals.py` |
| E12 | Turn realization: `sentence`/`render`, particle fixing, `_choose`, `compose_line` | 1862–1895, 1963–2084 | 156 | — (engine only) | `marco/language/realizer/grammar.py` |
| E13 | Turn meaning: `utterance_plan` — everything the graph knows this turn, as a structure (proto Meaning Graph) | 1929–1962 | 34 | — (engine only) | `marco/cognition/decision.py` |
| E14 | Diagnostics run by the CLI: `calibrate`, precedent grading, `missing_evidence`/`diagnose`/`auto_argument`/`regression`/`lint` | 2088–2152, 3768–3823, 4271–4424 | 275 | `alma_runtime`, `intelligence_check`, `purpose_graph`, `self_authoring` | `marco/runtime/diagnostics.py` |
| E15 | Authoring suggestions: law-text concepts/edges, bridges, duplicates, direction classifier, semantic relations, edge labels, unknown-log proposals | 2153–2470, 2825–2946, 3824–4152 | 769 | — (engine only) | `marco/learning/suggest.py` |
| E16 | Graph router: index build, sparse vectors, rare words, `pick_graph`, `load_graph` LRU, `graph_for_duty`, `learn_into_graph` | 2471–2824, 2947–3217, 3262–3313, 3609–3660 | 729 | `alias_diag`, `bench/filler_prefix`, `graph_dialogue`, `intelligence_check`, `kgbin`, `routing_benchmark`, `self_authoring`, `views/kgpack_ui`, `yardstick` + 4 test files | `marco/runtime/router.py` |
| E17 | Graph usage activation (warm/cool per graph, `그래프쓰임.json`) | 3218–3261 | 44 | — (engine only) | `marco/cognition/attention.py` |
| E18 | Mermaid drawing of argument graphs and concept net | 4153–4270 | 118 | — (engine only) | `marco/knowledge/mermaid.py` |
| E19 | `_selfcheck` — 1131 lines of inline assertions behind `--check` | 4425–5555 | 1131 | — (engine only) | `marco/runtime/selfcheck.py` |
| E20 | CLI (`__main__`) | 5556–6072 | 517 | — (engine only) | `marco/runtime/cli.py` |

Notes:
- `engine.py:22–33` re-binds `encoder` names (`MODEL`, `route_thresh`, `_embed`,
  `mask_numbers`, …). 5 importers take them through `engine`: `alias_diag`,
  `bench/retrieval_diagnosis`, `routing_benchmark`, 2 tests. After the split they
  import `marco.language.encoder` directly; the `engine.py` shim keeps the old path.
- E14 and E19 stay in `marco/runtime/` because `engine.py --check`, `--regress`,
  `--tune` (calibrate), `--score` (precedents) are CLI behaviour, two of them in the
  README. Converting the selfcheck to pytest is not refactoring.
- Calls between parts become imports. The tool counts them from today's code
  (`--targets`, intra-module edges); none points upward with this split.

---

## A4. The four `nai` artifacts

| Artifact | Is | Code that reads / writes it | Target |
| --- | --- | --- | --- |
| `nai.py` (tracked) | CLI + `Conversation`/`Reply` over `.kg` and `.json` graphs | imported by `tests/test_nai.py`; imports `engine` (nai.py:71), `explain` (:77), `build` (:43) | `marco/runtime/conversation.py`; CLI becomes `python -m marco` (`marco/__main__.py`). `nai.py` stays as a shim until Phase 5 |
| `NAI.kgpack` (ignored) | built model pack, 1.5 MB here | no code hardcodes the name. Written by `python kgpack.py --pack NAI.kgpack` (usage text kgpack.py:7–9); read via `--pack` (usage text views/kgpack_ui.py:4) | `dist/MARCO.kgpack`; add `dist/` to `.gitignore`. Only usage strings and docs change |
| `.nai/` (ignored) | runtime store: `conversations.json`; README's ALMA examples put state files here | `views/kgpack_ui.py:249` `ConversationStore(repo_root / ".nai" / "conversations.json")`; docstring `conversation_store.py:1`; ALMA paths come from the caller (`--state`) | `.marco/state/` |
| `.nai-tools/` (ignored) | machine-built vision binary, YOLO config | `document_visual.py:27` `VISION_BINARY = ROOT / ".nai-tools" / "document_vision"`; `:468`, `:484` `YOLO_CONFIG_DIR` | `.marco/tools/` |

One ignored directory, `.marco/`, then holds all per-machine state. Fifth use of the
old name, found while reading: the `NAI_*` environment prefix —
`NAI_LANGUAGE` (language_components.py:25), `NAI_RELATIONAL_MODEL`
(relational_semantics.py:45), `NAI_PDFTOTEXT` (marco/knowledge/ingest/documents.py:80),
`NAI_DOCUMENT_VLM` (document_visual.py:436), `NAI_DOCUMENT_VLM_ALL` (:599),
`NAI_PASSAGE_LABELS` (marco/language/passages.py:44). Target: `MARCO_*`, with the
`NAI_*` name read as fallback until Phase 5.

---

## A5. `mco/`

- State: untracked in this clone; branch `mco-package` points at `6195040` (no commits
  of its own). Measured from the working tree (`--root .`): 15 files, 0 static
  imports of any MARCO module.
- MARCO is reached only through `importlib` in `mco/backends/marco.py`:
  `_REQUIRED_MODULES = ("kgpack", "pack_model", "engine")` (:54),
  `_UI_MODULE = "views.kgpack_ui"` (:55), and a file-existence check
  `path / f"{m}.py"` (:103).
- **Decision:** stays a top-level package, layer 11 (above `marco`, `alma`, `polo`,
  `views`). Allowed: only `mco/backends/marco.py` may reach MARCO (existing test
  enforces it), and only through public interfaces — `marco.runtime` (app/session
  entry) and `marco.storage` (`kgpack`, later `.mco` I/O). Forbidden: any other
  `marco.*` submodule, `alma`, `polo`, `views`, `bench`, `tools`.
- Phase impact: root shims keep all four names valid through Phase 4, including the
  `*.py` existence check. Phase 4 changes `:54–55` to `marco.storage.kgpack`,
  `marco.storage.model`, `marco.runtime.engine`, `marco.runtime.app` (owner: W2 in
  `docs/ko/2026-09-22-parallel-goals.md`). Phase 5 may not delete those shims before that.

---

## A6. Target layout

### Layer rule

A module may import modules in its own layer or a lower one. Two packages in the
same layer must not import each other in a cycle. Checked by `--targets`.

```text
MARCO/
├ marco/                  core; imports nothing from alma/ polo/ mco/ views/ bench/ tools/ experiments/
│ ├ __init__.py           version only
│ ├ __main__.py           `python -m marco` → runtime/cli.py (replaces nai.py)
│ ├ _paths.py        L0   repo and data roots (engine.py:36–41; 22 root files use __file__ today)
│ ├ progress.py      L0   progress bar
│ ├ language/        L1   text ↔ structure: packs, Hangul arithmetic, encoder, parsing, realization.
│ │                       Forbidden: graphs, judgement, file I/O beyond reading packs
│ ├ perception/      L1   image → verified observations (OCR, chart/table, objects, pose, VLM hypothesis).
│ │                       Forbidden: graph writes, sentences
│ ├ storage/         L2   bytes on disk: kgpack, kgbin, overlay, model assets, conversation store.
│ │                       Forbidden: decisions, reasoning
│ ├ knowledge/       L3   graph format + structure queries, matching, definitions, Mermaid, ingest/.
│ │                       Forbidden: verdicts, routing policy, sentence generation
│ ├ memory/          L4   episodic/semantic/procedural stores, consolidation. Not created before
│ │                       Phase 3 (§4.17): sources are reasoning_context.py:1107–1238,1550–1729
│ │                       and AlmaRuntime memory methods
│ ├ reasoning/       L5   judge, Horn inference, context replay, state, action programs, answer semantics.
│ │                       Forbidden: learning writes, sessions, host actions
│ ├ learning/        L6   concepts, rules, templates, expressions, chunking, feedback, suggestions, authoring.
│ │                       Forbidden: activating a change without approval
│ ├ host/            L7   permission boundary and host actions: `permissions.check()`, marco/host/act.py (W4 seam)
│ ├ cognition/       L8   attention, decision (builds the Meaning Graph), goals
│ └ runtime/         L9   engine entry, router, sessions, app state, model factory, diagnostics,
│                         selfcheck, cli, graph_dialogue, explain, conversation
├ alma/              L10  runtime, environment, cli (identity/emotion/preference/relationships: W3)
├ polo/              L10  POLO. Not created before W4
├ views/             L10  HTML + HTTP handler; AppState → marco/runtime/app.py
├ mco/               L11  public API (A5)
├ experiments/       L12  standalone research programs with 0 importers: vision, codegen, autocoder, universal_agent
├ bench/ tools/ collectors/ docs/   L12
├ tests/             L13  per-package folders are S3, not Phases 1–5
└ graphs/ styles/ axioms/ data/ cases/ legal/ algorithms/ practice/   data, unchanged
```

`experiments/` is the one directory the plan did not name. Reason: 4 root programs
(2,970 lines) have no importer and are neither frozen benchmarks (`bench/`) nor
maintenance scripts (`tools/`).

### Files per package (from A1 and A3)

| Package | Files |
| --- | --- |
| `marco/storage/` | `kgpack.py`, `kgbin.py`, `overlay.py` (engine E6), `model.py` (pack_model 1–201), `conversations.py` |
| `marco/knowledge/` | `graph.py` (E3), `matching.py` (E7), `definitions.py`, `mermaid.py` (E18); `ingest/`: `text.py` (build), `documents.py` (document_kg), `dictionary.py`, `purpose.py`, `cases.py` (E8), `web.py` |
| `marco/perception/` | `visual.py`, `vlm.py`, `objects.py`, `pose.py` (+ `document_vision.swift`) |
| `marco/reasoning/` | `judge.py` (E9), `inference.py`, `context.py`, `state.py` (+ situation_reasoner), `actions.py`, `semantics.py` (relational_semantics 479–532, 1077–1170) |
| `marco/learning/` | `concepts.py`, `rules.py`, `templates.py` (relational_semantics 405–478), `expressions.py`, `chunking.py`, `feedback.py`, `suggest.py` (E15), `authoring.py` |
| `marco/host/` | `marco/host/act.py`, `permissions.py` (goal_runtime 147–210) |
| `marco/cognition/` | `attention.py` (E17), `decision.py` (E13), `goals.py` (goal_runtime 1–146) |
| `marco/runtime/` | `engine.py` (E1), `router.py` (E16), `session.py` (E10), `app.py` (views/kgpack_ui AppState), `model.py` (pack_model 202–221), `diagnostics.py` (E14), `selfcheck.py` (E19), `cli.py` (E20), `graph_dialogue.py`, `explain.py`, `conversation.py` (nai) |

### `marco/language/` — day-one file list for the realization goal

Names follow `docs/ko/2026-09-22-parallel-goals.md` (W1 owns `marco/language/realizer/`
and `realize(meaning, intent, language) -> str`).

```text
marco/language/
├ __init__.py        public: load_language_pack, parse, realize(meaning, intent, language) -> str
├ pack.py            ← language_components.py:24–403   pack path, per-section validation, decode_language_pack
├ backends.py        ← language_components.py:1–23, 404–502   DialogueBackend, TemplateBackend, resolve_backend
├ marco/language/hangul.py          ← marco/language/hangul.py      syllable arithmetic, particles, inflect, clause spans
├ encoder.py         ← encoder.py:1–430   EncoderRuntime, character/jamo vectors, neural loader
├ surface.py         ← encoder.py:431–567   view_lang, strip_english_shell, strip_fillers, split_fragments
├ understanding.py   ← marco/language/understanding.py + engine.py:487–503 (yes/no)
├ facts.py           ← relational_semantics.py:1–42   asserted, joined, substitute (breaks the frame_induction cycle)
├ parser.py          ← relational_semantics.py:43–404, 533–1076   RelationalParser compile + parse
├ frames.py          ← marco/language/frames.py
├ representation.py  ← marco/language/representation.py   candidate → validated state JSON
├ numerals.py        ← marco/language/numerals.py + engine.py:1770–1836
├ arithmetic.py      ← marco/language/arithmetic.py + marco/language/arithmetic_spoken.py
├ passages.py        ← marco/language/passage_components.py + marco/language/passages.py
└ realizer/          goal 3 (W1) builds here
   ├ __init__.py     realize(): the only path from meaning to sentence
   ├ meaning.py      Meaning Graph contract, no language in it (seed: `transitions`; engine.utterance_plan shape)
   ├ intent.py       INFORM ASK WARN CORRECT REFUSE REASSURE, declared in the pack (seed: engine.py:101–124 refusal)
   ├ discourse.py    Discourse Planner (seed: marco/language/realizer/composer.py)
   ├ expression.py   Expression Selector (seed: pack `관계말` phrasings)
   ├ affect.py       ← marco/language/realizer/affect.py   expression mode only
   ├ grammar.py      Grammar Realizer (seed: engine.py:1862–1895, 1963–2084; explain.py:451–473 `_link_form`; hangul.inflect)
   ├ contracts.py    ← marco/language/realizer/contracts.py
   └ check.py        Semantic Check: realize → parser.py → compare meaning
```

Who builds meaning: `marco/cognition/decision.py` (from `engine.utterance_plan`)
imports `realizer/meaning.py` downward. The realizer never imports reasoning.

### Predicted graph after the move

`--targets` maps each of today's import statements to its target by line (split
modules) and by the line that defines each imported name, and turns calls between
parts of one split module into the imports they will become.

```text
source: 6195040 (6195040)
target map: docs/architecture/target-map.json
root modules: 61  rows: 61  missing: 0  TBD: 0  extra: 0  no layer: 0
target-level edges: 338  upward: 9 (top-level 4)
  docs (L12) -> tests (L13) [top]  e.g. docs/ko/audit-2026-09-20/audit-probes.py:14 docs.ko.audit-2026-09-20.audit-probes -> tests.test_concept_relation_reasoning
  marco.language.arithmetic (L1) -> marco.runtime.model (L9) [lazy]  e.g. marco/language/arithmetic_spoken.py:14 verbal_expression -> pack_model.development_model
  marco.language.parser (L1) -> marco.runtime.model (L9) [lazy]  e.g. relational_semantics.py:51 relational_semantics -> pack_model.development_model
  marco.language.realizer.contracts (L1) -> marco.runtime.model (L9) [lazy]  e.g. marco/language/realizer/contracts.py:10 output_contracts -> pack_model.development_model
  marco.learning.authoring (L6) -> bench.routing_benchmark (L12) [top]  e.g. marco/learning/authoring.py:90 self_authoring -> routing_benchmark
  marco.learning.authoring (L6) -> bench.yardstick (L12) [lazy]  e.g. marco/learning/authoring.py:261 self_authoring -> yardstick
  marco.learning.authoring (L6) -> marco.runtime.diagnostics (L9) [top]  e.g. marco/learning/authoring.py:88 self_authoring -> engine.lint
  marco.learning.authoring (L6) -> marco.runtime.router (L9) [top]  e.g. marco/learning/authoring.py:88 self_authoring -> engine.load_graph
  marco.reasoning.context (L5) -> marco.learning.concepts (L6) [lazy]  e.g. reasoning_context.py:60 reasoning_context -> experience_concepts
package-level cycles after move: SCCs 1 sizes [9] elementary 53
  SCC: alma bench marco.cognition marco.knowledge marco.language marco.learning marco.reasoning marco.runtime marco.storage
root .py files left after Phase 5: 1 (conftest)
```

The 8 upward edges inside `marco` are the Phase 3 work list:

| Edge | Fix |
| --- | --- |
| `relational_semantics.py:51`, `marco/language/realizer/contracts.py:10`, `marco/language/arithmetic_spoken.py:14` → `pack_model.development_model` | callers pass the model; the source-tree fallback lives only in `runtime/model.py` and entry points. This is the 6-module cycle |
| `reasoning_context.py:60` → `experience_concepts` | inject the concept store into `ReasoningContext` |
| `marco/learning/authoring.py:88` → `engine.load_graph`, `engine.lint` | inject `route`/`lint` callables from runtime |
| `marco/learning/authoring.py:90` → `routing_benchmark`, `:261` → `yardstick` | move the index-without-alias builder into `runtime/router.py`; yardstick reads authoring records, not the reverse |

Measured: with these 9 edges removed from the predicted graph, package-level cycles
= 0 (marco and whole repo). Root `.py` after Phase 5: 1 (`conftest.py`).

---

## A7. Do-not-touch list for Phase 1

Phase 1 starts only when every file below is merged to `main`: `repair-and-english`
merged, and the ALMA goal's final commit an ancestor of `main`
(`git merge-base --is-ancestor <commit> main`).

| File | Owner |
| --- | --- |
| `alma/cli.py`, `alma/runtime.py`, `encoder.py`, `graph_inference.py`, `kgpack.py`, `language_components.py`, `reasoning_context.py`, `relational_semantics.py`, `marco/knowledge/ingest/web.py`, `views/kgpack_ui.py`, `styles/한국어.json` | both goals |
| `action_runtime.py`, `alma/environment.py`, `marco/learning/concepts.py`, `marco/learning/chunking.py`, `marco/learning/feedback.py`, `marco/language/representation.py` | goal 1 ALMA (Windows clone; edited in `f02d803`) |
| `conftest.py`, `engine.py`, `explain.py`, `goal_runtime.py`, `marco/language/hangul.py`, `pack_model.py`, `state_engine.py`, `styles/english.json`, `data/benchmarks/unseen_phrasing_v1.json` | goal 2 repair + English (`f985857`, not on `main`) |
| 17 `bench/*.py` and 67 `tests/*.py` in `git diff --name-only main repair-and-english` | goal 2 (ALMA shares the `alma_*` ones) |
| `mco/`, `pyproject.toml`, `tests/test_mco_package.py`, `docs/mco/`, the uncommitted `README.md` hunk | unregistered `mco` session (branch `mco-package`) |

The ALMA set is what `f02d803`/`6195040` touched; the running goal may add files —
re-read its final diff before lifting the gate.

22 root `.py` files are on the list; 39 are not. Phase 2 must not move a listed file
before the gate above holds, even if it looks clean.

---

## A8. Phase plan with gates

Test command for every gate: the A0 command, on an export of the phase's commit plus
this clone's ignored files. **Base number:** A0 = 770 passed / 4 failed (the 4 ids
above). If `main` moved before Phase 1 (it will: goals 1 and 2 merge first), re-run A0
at the Phase 1 base commit first and record it as A0′; every gate then compares to A0′
with the same failing ids. `K` = cases in the compatibility test added in Phase 2.

| Phase | Files moved | Shim | Gate (all must hold) |
| --- | --- | --- | --- |
| 1 Skeleton | 0. Create `marco/__init__.py`, `marco/_paths.py`, and `__init__.py` for `language`, `language/realizer`, `perception`, `storage`, `knowledge`, `knowledge/ingest`, `reasoning`, `learning`, `host`, `cognition`, `runtime`; `alma/__init__.py` | none | passed = A0′; failed ids = A0′; root `.py` = 61; `--targets` rows 61, TBD 0; `all_modules_top` SCCs = 0; runtime SCCs = 2 (5 elementary) |
| 2 Clean moves | the 51 unsplit rows of A1 in batches of ≤ 10, not on A7 until A7's gate holds; each moved file's `__file__` paths switch to `marco._paths` in the same commit | one per moved file (template below); plus `tests/test_compat_imports.py`: old name imports and `is` the new module | per batch: passed = A0′ + K; failed ids = A0′; root `.py` = 61; `--targets` upward ≤ 9, never a new one; runtime SCCs ≤ 2 |
| 3 Splits | `engine` (20 parts), `relational_semantics` (4), `language_components` (2), `encoder` (2), `pack_model` (2), `goal_runtime` (2), `purpose_graph` (2); `explain` per its A1 row; fix the 8 edges of A6 | the old file becomes the shim (engine.py keeps every name its 40 importers take) | passed = A0′ + K; `--targets` upward inside `marco` = 0; package SCCs = 0; `engine.py --check` same outcome as A0 (exit 1, same assertion) unless fixed in its own commit first; `bench/routing_benchmark.py --답` stdout sha1 = A0's (`d1937d7e…`) |
| 4 Imports | every internal import package-qualified; `NAI_*` → `MARCO_*` with fallback; pack string `graph_dialogue:backend` (styles/한국어.json:2993) → `marco.runtime.graph_dialogue:backend`; `mco/backends/marco.py:54–55` (W2) | unchanged | passed = A0′ + K; edges into a shim from outside `tests/test_compat_imports.py` = 0 (tool: edges whose target is a root shim); upward = 0; package SCCs = 0 |
| 5 Remove shims | delete the 59 shims (51 + 7 split sources + `explain`) and `situation_reasoner.py` (0 importers); keep `conftest.py`; `tests/test_compat_imports.py` goes | — | root `.py` = 1; passed = A0′; failed ids = A0′; README commands updated and each run once |

Shim template. It keeps module identity, so a test that patches a module attribute
(`tests/test_experience_concept_reproduction.py:38` patches `action_runtime.execute`)
still patches the real module, and private names (`engine._embed`, `encoder._vec`, …)
stay reachable. `from x import *` would break both:

```python
"""Compatibility shim — removed in Phase 5. New code imports marco.storage.kgpack."""
import importlib, runpy, sys
if __name__ == "__main__":
    runpy.run_module("marco.storage.kgpack", run_name="__main__", alter_sys=True)
else:
    sys.modules[__name__] = importlib.import_module("marco.storage.kgpack")
```

Hazards to carry into Phase 2, measured at `6195040`:
- 22 root files (24 sites) resolve data paths from `__file__`; moved one level down, each
  one silently reads the wrong directory unless it uses `marco/_paths.py`.
- `pack_model` fingerprints pack content; changing the pack string in Phase 4 changes
  the fingerprint of every pack built afterwards.

---

## Found, not fixed

| Where | What |
| --- | --- |
| `self_learning.py:139` | `importlib.import_module("위키")` after inserting `collectors/`; the file is `collectors/wiki.py` — never resolves. `.gitignore` also documents `python collectors/위키.py` |
| `tests/test_experience_concept_reproduction.py:22` | fails on this machine (`execution_error` 1, expected 0); cause not traced |
| `tests/test_alma_integrated_reproduction.py:31` | asserts RSS is unsupported; true on Windows only |
| `engine.py:4768` | `python engine.py --check` fails at `6195040`: `2등인 사람을 추월했습니다` routes to `graph_일상추론.kg`, not `graph_순위_추월.kg` |
| `engine.py:4425–5555` | 1131-line `_selfcheck` inside the engine; `explain.py` has another 337 lines (1814–2150) |
| `README.md` (at `6195040`) | "145 graphs · 2,092 nodes"; tree has 904 `graphs/*.kg` + 7 `cases/` + 2 `legal/`. "Code 8,692 lines" for four files; `engine.py` alone is 6,072. Routing figures (27/27, 37.0 %, 64.0 % over 2,018) vs today's `bench/routing_benchmark.py --답`: 24/24, 40.6 %, 76.1 % over 6,912 — README table updated with the commit named; latency/memory rows not re-measured |
| `docs/ko/audit-2026-09-20/audit-probes.py:14` | a docs script imports a test module |
| `views/kgpack_ui.py:33` | the UI imports `self_authoring` at top level and runs authoring rounds |
| `engine.py:108` | hardcoded Korean refusal (already known, plan §5) |
