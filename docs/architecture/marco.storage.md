# `marco.storage`

Written 2026-10-01 against commit `e3a6394`.

## Purpose

Bytes on disk: the files MARCO reads its knowledge from and the state it keeps
between turns and processes. The target layout puts the package at layer 2,
"bytes on disk" ([structure-audit.md](structure-audit.md) A6,
[target-map.json](target-map.json)). Goal S4 moved three root files here whole
on 2026-09-28 (commit `7dab5c7`): `conversation_store` (now `conversations.py`),
`kgbin`, `kgpack` (`python tools/doc_facts.py layout`: no root file left to
move). The MCO scope for MARCO 1 (`docs/ko/2026-09-22-freeze-decision.md`)
added the rest on 2026-10-01: `ids`, `overlay`, `graph_view`, `graph_text`
(slice 2, [overlay.md](overlay.md)) and `snapshot` (slice 3,
[snapshot.md](snapshot.md)). Their formats, rules and tests are in those notes
and in [MCO Format 1](../mco/format-1.md) §6.6–6.7, not repeated here. No
module writes the base pack, starts an overlay change or learns (docstrings of
`overlay.py`, `graph_view.py`, `snapshot.py`).

## Owns

| Module | Lines (`wc -l`) | What |
| --- | --- | --- |
| [kgpack.py](../../marco/storage/kgpack.py) | 317 | `.kgpack`: ZIP with one `manifest.json` (format `nai-kgpack`, writes version 3, reads 2 and 3) holding each file's SHA-256 and size, and a manager graph with one node per `.kg`. `write_pack` (fixed zip timestamps; `selfcheck` asserts same input, same bytes), `read` (checks hashes and manager, then builds `pack_model.PackModel`), `unpack`, `default_file`, `model_files`, `content_identity`; CLI `--pack/--list/--unpack/--check` |
| [kgbin.py](../../marco/storage/kgbin.py) | 265 | The engine's sparse routing index as one file `.색인.kgbin`: JSON header, raw arrays 8-byte aligned, read by slicing an mmap; values quantised (`uint8` default), expanded only when a graph is scored (`engine.py:3161`); per-graph example hashes against a stale file. `KG_INDEX=npz` bypasses it (`engine.py:2827`). Size and speed figures are the docstring's; not re-measured |
| [conversations.py](../../marco/storage/conversations.py) | 167 | `ConversationStore`: projects and chats in one JSON file (the UI's: `.marco/state/conversations.json`, `views/kgpack_ui.py:257`), saved by `snapshot.atomic_write`. `binding(...)` ties a store to a base and overlay head; a saved reasoning state is used as saved, reloaded without `replay`, or refused (`ConversationBaseMismatch`) |
| [ids.py](../../marco/storage/ids.py) | 65 | `graph_id`, `node_id`, `edge_id`, `rule_id` from content (Format 1 §6.7); byte-identical copy `mco/native/ids.py`, checked by `tests/test_mco_native_format.py` |
| [overlay.py](../../marco/storage/overlay.py) | 981 | `OverlayStore`: one SQLite file (WAL) bound to one base sha; append-only `changes`, `deltas`; derived `cur_*` tables readable at any `seq`; one transaction per change; one writer (lock on `<overlay>.writer-lock`). `commit`, `undo`, `propose`/`approve`/`reject`, `rebuild`, readers; request builders `add_node`, `add_edge`, `add_rule`, `retract_edge`, `retract_node`, `disable_rule`, `replace_rule`; `OverlayError` and four subclasses |
| [graph_view.py](../../marco/storage/graph_view.py) | 481 | `GraphView`: base plus overlay pinned at one `seq`, as `read_kg`-shaped graphs with each node's and edge's origin, and rules after disables, replacements, additions; read only. `PackBase`, `OverlayAttachment` (read-only, one handle per read), `pack_content_sha256`, `apply_rule_changes`, `pack_rules`, `node_data`, `ViewError` |
| [graph_text.py](../../marco/storage/graph_text.py) | 278 | `.kg` text to graph dictionary and back: `parse` (the parsing part of `engine.read_kg`, without the hypernym merge), `write` (raises `GraphTextError` when its text would not parse back equal), `unwritable` |
| [snapshot.py](../../marco/storage/snapshot.py) | 518 | One file: `MARCO-SNAPSHOT/1` header with body length and SHA-256, then canonical JSON. `build`, `write`, `read`, `loads`, `Snapshot` (`check_base`, `check_overlay`, `extract_overlay`, `restore_states`), `atomic_write`; `SnapshotError` and four subclasses; an attached overlay goes in as a point-in-time SQLite copy |
| `__init__.py` | 0 | empty; nothing re-exported |

## Does not own

- **Model assets.** `pack_model.py` stays at the root ("stay at the root in
  S4", `doc_facts.py layout`); the audit's `marco/storage/model.py` does not
  exist. `kgpack.write_pack` and `kgpack.read` import `pack_model` lazily.
- **The engine's learned-alias sidecars** (`.학습.jsonl`, `.미지.log`, audit
  item E6, mapped to `marco/storage/overlay.py`). That code is still in
  `engine.py` (e.g. lines 711–712, 2616); the `overlay.py` that exists is a
  different store under that name.
- **Applying the overlay at run time:** `views/kgpack_ui.py:415–416` and
  `pack_model.py:202` ([overlay.md](overlay.md)).
- **The `mco` API.** `mco/backends/marco.py` loads these modules by name
  (lines 65–67, 713, 744–745); see [mco.backends.md](mco.backends.md).
- **What a reasoning state holds.** `snapshot.py` stores
  `ReasoningContext.snapshot()` unchanged, schemas `reasoning-context-v1` to
  `v10`; the identity graph in it is `marco.reasoning`'s
  ([conversation-graph.md](conversation-graph.md)). Seven named items are never
  written (`EXCLUDED`).

## Depends on

- Standard library and this package only: `ids`, `graph_text`, `graph_view`,
  `snapshot`, `conversations`.
- `overlay.py`: `marco.trace.ledger.new_id` for change and candidate ids;
  `marco.trace` has no layer in [target-map.json](target-map.json).
- `kgpack.py`: root `pack_model` (lazy). `kgbin.py`: `numpy` (lazy); its
  `__main__` imports root `engine` and `encoder`. Both put the repository root
  on `sys.path` at import.

## Public interface

From a grep excluding the hidden worktree folder and `data/benchmarks/`; names
that `mco/` defines itself are not counted.

| Name | Imported by | Test |
| --- | --- | --- |
| `kgpack.write_pack`, `model_files` | `mco/backends/marco.py`, 9 `bench/` files; `write_pack` also `views/kgpack_ui.py`, `alma/runtime.py` | 13 files (`write_pack` 14), e.g. `tests/test_pack_model.py` |
| `kgpack.read`, `KGPackError` | `views/kgpack_ui.py`, `alma/cli.py`, `alma/runtime.py`, 2 `bench/` files; `KGPackError` also `mco/backends/marco.py` | `tests/test_pack_model.py`, `test_overlay_runtime.py`, `test_mco_package.py`, `test_alma_runtime.py` |
| `kgpack.default_file`, `content_identity` | `default_file`: `mco/backends/marco.py` | `tests/test_pack_model.py`; `default_file` also `test_overlay_runtime.py` |
| `kgpack._graph_meta` (private) | `views/kgpack_ui.py:471` | no test names it |
| `kgpack.unpack`, `selfcheck`, `main` | command line only | no test names it |
| `kgbin.unpack`, `expand`, `write_pack` | `engine.py:2830` (`unpack`), `3161` (`expand`) | `tests/test_geometric_matching.py` (`unpack`, `write_pack`); `expand`: no test names it |
| `ConversationStore` | `views/kgpack_ui.py`, `mco/backends/marco.py`, 7 `bench/` files | `tests/test_reasoning_persistence.py`, `test_learning_question_flow.py`, `test_concept_relation_reasoning.py`, `test_mco_snapshot.py` |
| `binding`, `ConversationBaseMismatch` | `mco/backends/marco.py` | `tests/test_mco_snapshot.py` |
| `graph_id`, `node_id`, `edge_id`, `rule_id` | `overlay`, `graph_view`; `mco/backends/marco.py` via `overlay.ids` | `tests/test_overlay_store.py`, `test_overlay_view.py`, `test_mco_native_format.py` |
| `OverlayStore`, request builders, `OverlayError` | `mco/backends/marco.py` (744, 796–813) | `tests/test_overlay_store.py`, `test_overlay_view.py`, `test_overlay_graph_text.py`, `test_overlay_runtime.py`, `test_overlay_application.py`, `test_mco_snapshot.py` |
| `OverlayBaseMismatch` | `views/kgpack_ui.py:416` | `tests/test_overlay_store.py`, `test_overlay_runtime.py`, `test_overlay_application.py` |
| `OverlayWriterBusy`, `OverlayStaleRevision`, `OverlayConflict` | none outside the package | `tests/test_overlay_store.py` |
| `GraphView`, `PackBase` | `mco/backends/marco.py`; `PackBase` also `views/kgpack_ui.py:415` | `tests/test_overlay_view.py`, `test_overlay_graph_text.py`, `test_overlay_runtime.py` |
| `OverlayAttachment`, `pack_content_sha256` | `views/kgpack_ui.py`; `OverlayAttachment` also `mco/backends/marco.py:713` | `tests/test_overlay_runtime.py` |
| `apply_rule_changes` | `pack_model.py:202` | `tests/test_overlay_view.py` |
| `ViewError`, `graph_text.parse`, `write`, `unwritable`, `GraphTextError` | `graph_view` only, or none | `tests/test_overlay_graph_text.py`; `ViewError`, `parse` also `test_overlay_view.py` |
| `snapshot.read`, `write`, `Snapshot.restore_states`, the four refusal classes | `mco/backends/marco.py` (287, 393, 500) | `tests/test_mco_snapshot.py` |
| `snapshot.build`, `loads`, `canonical` | none outside the package | `tests/test_mco_snapshot.py` |
| `pack_rules`, `node_data`, `overlay.file_sha256`, `atomic_write`, `base_record`, `conversation_record`, `is_snapshot` | `atomic_write`: `conversations`; the rest none | no test names it |

How often these tests pass is not measured here.
