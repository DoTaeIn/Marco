# `mco.native`

Written 2026-10-01 against commit `e3a6394`.

## Purpose

Read and write the native binary `.mco` file, MCO Format 1 (version 1.1:
version 1.0 plus the graph and rule tables), specified byte for byte in
[format-1.md](../mco/format-1.md). The package is standard library only and
imports no MARCO module; it is internal to `mco`, and user code reaches it
through `mco.load`, `mco.compile(..., format="native")` and `mco.inspect`
([`__init__.py`](../../mco/native/__init__.py) docstring). The user-facing
description is in [README.md](../mco/README.md), the table reader's call
reference in [api.md](../mco/api.md), and the place of the format in the
`mco` package in [mco.md](mco.md) and [mco.backends.md](mco.backends.md).

What it does not do yet, as [format-1.md](../mco/format-1.md) section 1 and
[api.md](../mco/api.md) state it: the running path does not read the tables.
`mco.load` rebuilds the MARCO pack from the member chunks and MARCO parses the
`.kg` source text when the model opens, so a 1.1 file is not faster to open
than a compat container and nothing is loaded lazily. The file itself holds no
overlay and no snapshot (an overlay store or a snapshot beside the file binds
to it: [overlay.md](overlay.md), [snapshot.md](snapshot.md)); there is no
consolidation, routing index or file without the source text; the chunk types
`OVLY`, `CHNG`, `SNAP`, `PROV` are reserved and read as unknown
(`RESERVED_TYPES` in [pack.py](../../mco/native/pack.py)). Partial loading is
not measured ([README.md](../mco/README.md)).

## Owns

| Module | Lines (`wc -l`) | What |
| --- | --- | --- |
| [container.py](../../mco/native/container.py) | 347 | Header (96 bytes), table of contents (64-byte entries) and chunks, sections 3 to 5: `encode` (deterministic writer, zlib only when smaller), `write_file` (temporary file, then rename), `Container` (opening reads and validates the header and TOC only; `read` reads one chunk, checksum and `raw_length` checked; `verify_all`). Knows nothing about what a chunk means |
| [pack.py](../../mco/native/pack.py) | 749 | Section 6: the manifest (`MANI`), the string, member and graph-directory tables (`STRS`, `MEMB`, `GDIR`), member chunk types, `build_chunks`/`write_model` (refuse with `CompileError` what Format 1 cannot represent), `kgpack_zip` (rebuild the MARCO pack ZIP), `content_identity` (6.5) and `content_sha256` (6.6), and `NativeModel` (open level of section 7, `verify_all`, and the 1.1 table reader `graph`, `graph_rows`, `node_edges`, `rule_rows`, `rules`, `table_index`, `summary`) |
| [tables.py](../../mco/native/tables.py) | 560 | Sections 6.8 to 6.11: encode and decode `INDX`, `NODE`, `EDGE`, `RULE`; rows keyed and sorted by stable id, source order kept in `ordinal` fields; `unrepresentable` says why a graph stays source text only (status `SOURCE_ONLY`) |
| [kgtext.py](../../mco/native/kgtext.py) | 174 | `parse_kg`: a line-for-line port of the parsing part of `engine.read_kg`, without the hypernym merge from `data/개념망.json`; the writer builds the tables from it |
| [ids.py](../../mco/native/ids.py) | 65 | `graph_id`, `node_id`, `edge_id`, `rule_id` (section 6.7); a byte-identical copy of `marco/storage/ids.py` |
| [`__init__.py`](../../mco/native/__init__.py) | 39 | Re-exports; `__all__` lists the names below |

## Does not own

- Detecting a file's kind, `ModelFile`, and `write_native` (pack ZIP to
  members, then `write_model`): [mco/formats.py](../../mco/formats.py), which
  imports `NativeModel` and `write_model` inside its functions.
- Running a native file: the `mco-native` backend
  ([mco.backends.md](mco.backends.md)), which reaches this package through
  `ModelFile.payload_bytes()`, that is `NativeModel.kgpack_bytes()`.
- The overlay store and its merged view ([overlay.md](overlay.md)).
  `marco/storage/graph_view.py` accepts `NativeModel` as a base reader, but
  the running path uses `PackBase` for every file kind. `mco/overlay.py`
  imports the identifier functions from `mco.native.ids`.
- Conversation snapshots ([snapshot.md](snapshot.md)); they bind to the base
  `content_sha256` this package computes.
- The original identifier module `marco/storage/ids.py` and the parser
  `engine.read_kg` that `kgtext.py` copies.

## Depends on

- `mco.errors` (`CompileError`, `IntegrityError`, `ModelFormatError`,
  `ModelNotFoundError`, `UnsupportedFormatError`), imported by `container.py`
  and `pack.py`.
- The standard library only (`struct`, `hashlib`, `zlib`, `zipfile`, `json`,
  `unicodedata`, `re`, `bisect`, `dataclasses`, `pathlib`, `io`, `os`).
- Inside the package: `pack` imports `container`, `tables`, `ids`, `kgtext`;
  `tables` imports `ids` and `kgtext`.

## Public interface

| Name | Imported by | Test |
| --- | --- | --- |
| `NativeModel` (`open`, `from_bytes`, `verify_all`, `kgpack_bytes`, `content_sha256`, `summary`) | `mco/formats.py`; `tests/test_overlay_view.py` | `test_writer_is_deterministic_and_pack_round_trips`, `test_open_level_does_not_read_members`, `test_newer_minor_version_is_read` (format tests) |
| `NativeModel` table reader (`has_tables`, `table_index`, `graph`, `graph_rows`, `node_edges`, `rule_rows`, `rules`) | no runtime module; `tests/test_overlay_view.py` | `test_every_graph_rebuilt_from_tables_equals_read_kg`, `test_one_graph_reads_only_its_own_chunks`, `test_edges_of_one_node_read_only_that_graphs_edge_chunk`, `test_rules_from_the_table_equal_the_packs` (table tests); `test_native_model_is_a_base_reader` |
| `write_model` | `mco/formats.py`; `tests/test_overlay_view.py`; `tests/test_overlay_application.py` names it through `mco.native.pack` | `test_native_model_is_a_base_reader` |
| `build_chunks` | the two test files below | no test names it; the helpers `_chunks` (format tests) and `_build`, `_chunks` (table tests) call it |
| `Chunk`, `Container`, `encode` | the two test files below | `test_container_round_trip_gives_identical_chunks`, `test_decompression_is_bounded_by_raw_length` |
| `MAGIC` | `tests/test_mco_package.py` | `test_native_format_is_recognised_but_unsupported` |
| `KNOWN_CHUNKS`, `MEMBER_TYPES`, `TABLE_TYPES` | the two test files below | `test_one_chunk_is_read_without_reading_the_file`, `test_a_10_reader_reads_a_11_file_and_a_10_file_has_no_tables` |
| `graph_id`, `node_id`, `edge_id`, `rule_id` | `mco/overlay.py`; the two test files below | `test_identifier_encoding_is_exact_and_shared_with_marco` (also checks the copy is byte-identical) |
| `parse_kg` | `tests/test_mco_native_tables.py`, `tests/test_overlay_graph_text.py` | `test_small_pack_tables_round_trip`, `test_parse_agrees_with_the_mco_reader_for_every_graph` |
| `MAJOR`, `MINOR`, `ChunkEntry`, `Member`, `FEATURES`, `GRAPH_TABLE_TYPES`, `RESERVED_TYPES`, `KgTextError` | no file outside the package | no test names it |

"Format tests" is [tests/test_mco_native_format.py](../../tests/test_mco_native_format.py)
and "table tests" is [tests/test_mco_native_tables.py](../../tests/test_mco_native_tables.py);
[format-1.md](../mco/format-1.md) names both as the home of its fixtures and
damaged variants, and [mco.backends.md](mco.backends.md) lists the format
tests that cover the `mco-native` backend. The time to read one graph from the
tables is not measured; [README.md](../mco/README.md) gives the only size and
open-time comparison with the compat file.
