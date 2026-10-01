# MCO Format 1

The native binary `.mco` file. Version 1.0, first slice, written 2026-10-01.
The reference reader and writer are [mco/native/](../../mco/native/); the
fixtures and damaged variants are in
[tests/test_mco_native_format.py](../../tests/test_mco_native_format.py).

This document is meant to be enough to write a second reader that accepts and
refuses exactly the same files. Where this slice stores something as an opaque
copy of a MARCO pack member instead of a real table, the document says so.

**Scope** (owner's decision, 2026-10-01). The format is storage and runtime
infrastructure. It does not make the engine reason or understand better. The
overlay that a later slice adds on top of an immutable base is called the
**Persistent Overlay Infrastructure**; it is storage, and this document does not
describe it as learning.

## 1. What this slice is and is not

A Format 1 file holds what a MARCO `.kgpack` holds today: graph text, learned
and collected records, language packs, axioms, an optional relational model,
the definitions asset, and the pack's graph directory (the "manager" graph the
router reads). It holds it in a chunked binary container with a fixed header,
a table of contents, per-chunk SHA-256 checksums and a manifest.

**Real tables in this slice:** the string table (`STRS`), the member directory
(`MEMB`) and the graph directory (`GDIR`). Their layouts are fixed below.

**Carried members in this slice:** every graph, record file, language pack,
axiom file, relational model and asset is stored as an opaque typed chunk whose
bytes are exactly the bytes of the pack member (`GRPH`, `LERN`, `COLL`, `LANG`,
`AXIM`, `RELM`, `DEFN`, `ASET`). These are **carried members, not tables**. The
runtime of this slice rebuilds the MARCO pack from them and MARCO parses the
`.kg` text when the model is opened, as it does for a `.kgpack`. The next slice
replaces graph text with node, edge and rule tables (reserved types `NODE`,
`EDGE`, `RULE`, `INDX`, section 8). Until then a Format 1 file is not faster to
open than a compat container, and it does not load a graph lazily.

Not in this slice: overlays, snapshots, consolidation, partial-loading
measurements, node/edge/rule tables, a routing index. Section 8 reserves the
names and fields they will use; the manifest's `supports` says overlay and
snapshot are not supported, and `mco inspect` says so too. The identifier scheme
those features need (section 6.7) and the base identity they bind to (section
6.6) are fixed now.

## 2. Conventions

- All integers are unsigned and **little-endian**: `u8`, `u16`, `u32`, `u64`.
- A `u64` value greater than 2^63 − 1 is invalid wherever it appears (offsets,
  lengths, sizes). Readers compute `offset + length` with that bound, so it
  cannot overflow a signed 64-bit integer.
- Strings are UTF-8 without a byte-order mark and without a terminator. A
  string that is not valid UTF-8 makes the file malformed.
- "Malformed" means the reader raises `ModelFormatError`. "Integrity failure"
  means `IntegrityError`. "Unsupported" means `UnsupportedFormatError`. All
  three are `mco` error classes; `IntegrityError` and `UnsupportedFormatError`
  are subclasses of `ModelFormatError`.
- `align8(x)` is the smallest multiple of 8 that is ≥ x.
- Checksums are SHA-256 (32 bytes). **A checksum proves the bytes are the bytes
  the writer wrote. It does not prove who wrote them.** Format 1 has no
  signature; a publisher's identity is a separate contract.

## 3. File layout

```
offset 0            header (96 bytes)
offset 96           chunk 0, zero padding to a multiple of 8
                    chunk 1, padding
                    ...
                    chunk N-1, padding
toc_offset          table of contents: toc_count entries of 64 bytes
toc_offset+toc_size end of file (file_size)
```

The layout is exact. Every byte of the file is the header, a chunk, padding,
or the TOC:

- the first chunk starts at offset 96;
- chunk `i + 1` starts at `align8(offset_i + length_i)` (TOC order is file
  order);
- `toc_offset = align8(offset_last + length_last)`, or 96 when there are no
  chunks;
- `file_size = toc_offset + toc_size`;
- padding bytes are zero.

A reader checks this arithmetic from the TOC without reading any chunk. A chunk
that starts before the end of the previous one **overlaps** it (malformed); one
that starts after it leaves a **gap** (malformed). A full verification also
checks that padding bytes are zero.

## 4. Header (96 bytes)

| Offset | Size | Field | Value and rule |
| --- | --- | --- | --- |
| 0 | 8 | `magic` | `89 4D 43 4F 0D 0A 1A 0A` (`\x89MCO\r\n\x1a\n`). Anything else: malformed. A file shorter than 8 bytes: malformed (truncated). |
| 8 | 2 | `major` | `1`. `0`: malformed. Greater than 1: unsupported, and the reader reads nothing past this field. |
| 10 | 2 | `minor` | `0` in this version. Any minor is accepted by a 1.x reader: a minor version may only add optional chunks, optional manifest keys and optional flag bits. |
| 12 | 4 | `header_size` | `96`. Anything else: malformed. |
| 16 | 4 | `flags` | Bits 0–15 are required flags, bits 16–31 optional flags. None is defined in 1.0; writers write 0. A set required bit the reader does not know: unsupported. Unknown optional bits are ignored. |
| 20 | 4 | `toc_count` | Number of TOC entries, 0 ≤ `toc_count` ≤ 65 536. More: malformed (absurd count), refused before the TOC is read. |
| 24 | 8 | `toc_offset` | Multiple of 8, ≥ 96. |
| 32 | 8 | `toc_size` | Must equal `toc_count × 64`. |
| 40 | 8 | `file_size` | Must equal the actual file size. A shorter file is truncated (malformed); a longer one has trailing bytes (malformed). |
| 48 | 4 | `toc_entry_size` | `64`. |
| 52 | 4 | reserved | `0`. |
| 56 | 32 | `header_sha256` | SHA-256 of header bytes `[0, 56)` ‖ header bytes `[88, 96)` ‖ the `toc_size` TOC bytes. The field itself (bytes 56–87) is not hashed. |
| 88 | 8 | reserved | All zero. |

`toc_offset + toc_size` must equal `file_size`; if it is larger, the TOC lies
outside the file (malformed).

Because `header_sha256` covers the TOC, and every TOC entry carries the
checksum of its chunk, verifying the header and reading one chunk verifies
everything that chunk's interpretation depends on in the container.

Order of header checks, so that every reader gives the same verdict for the same
damage: magic → `major` → `header_size`, `toc_entry_size`, reserved fields →
`file_size` → `toc_count` → `toc_size` and `toc_offset` → `header_sha256` →
required flags → TOC entries (section 5) → chunk-set rules (section 6).

## 5. Table of contents entry (64 bytes)

| Offset | Size | Field | Rule |
| --- | --- | --- | --- |
| 0 | 4 | `type` | Four bytes, each `A`–`Z` or `0`–`9`. Anything else: malformed. |
| 4 | 2 | `chunk_version` | Version of this chunk's own layout, ≥ 1. `0`: malformed. |
| 6 | 1 | `chunk_flags` | Bit 0: **required**. Bits 1–7 are reserved; writers write 0 and 1.x readers ignore them. |
| 7 | 1 | `compression` | `0` none, `1` zlib (RFC 1950 stream, as written by `zlib.compress`). Other values are unsupported when the chunk is read (an optional chunk the reader skips is never read). |
| 8 | 8 | `offset` | Multiple of 8; layout rules in section 3; `offset + length ≤ toc_offset`. |
| 16 | 8 | `length` | Stored length in bytes. ≤ 2^28 (256 MiB). |
| 24 | 8 | `raw_length` | Length after decompression. ≤ 2^28 (256 MiB): larger is malformed, refused before anything is decompressed. With compression 0, `raw_length = length`. |
| 32 | 32 | `sha256` | SHA-256 of the `length` stored bytes, as stored (compressed). |

**Empty chunks.** `length = 0` is allowed. It requires `compression = 0` and
`raw_length = 0`; its `sha256` is the SHA-256 of zero bytes; its `offset` still
follows the layout rule (it equals the next chunk's offset, which is not an
overlap).

**Reading a chunk.** Read `length` bytes at `offset` (fewer: malformed,
truncated). Compare SHA-256 with `sha256` (mismatch: integrity failure). For
zlib, decompress with an output limit of `raw_length + 1` bytes: more output
than `raw_length` is malformed (decompressed size over the declared size), and
so is less output, an incomplete stream, or bytes after the end of the stream.
The reader never allocates more than `raw_length` bytes for a chunk's output.

**Unknown and newer chunks.** A chunk is *understood* if the reader knows its
`type` and supports its `chunk_version`.

- Not understood and **optional**: skipped by its verified length (the layout
  check already proved where it ends). Its checksum is checked only in full
  verification.
- Not understood and **required**: unsupported. The file is refused when it is
  opened.

**Duplicate types.** `MANI`, `STRS`, `MEMB` and `GDIR` appear exactly once
(missing or repeated: malformed). The member types (`GRPH`, `LERN`, `COLL`,
`LANG`, `AXIM`, `RELM`, `DEFN`, `ASET`) repeat, one chunk per member. A type
the reader does not understand may repeat.

## 6. Chunk set of version 1.0

| Type | Ver | Req | Compression | Content | Kind |
| --- | --- | --- | --- | --- | --- |
| `MANI` | 1 | yes | 0 | manifest, canonical JSON (6.1) | metadata |
| `STRS` | 1 | yes | 0 | string table (6.2) | **table** |
| `MEMB` | 1 | yes | 0 | member directory (6.3) | **table** |
| `GDIR` | 1 | yes | 0 | graph directory: the pack's manager graph (6.4) | **table** |
| `GRPH` | 1 | yes | 1 or 0 | one `.kg` graph, MARCO graph text | carried member |
| `LERN` | 1 | yes | 1 or 0 | one `*.학습.jsonl` learned-record file | carried member |
| `COLL` | 1 | yes | 1 or 0 | one `*.수집.jsonl` collected-evidence file | carried member |
| `LANG` | 1 | yes | 1 or 0 | one `styles/*.json` language pack | carried member |
| `AXIM` | 1 | yes | 1 or 0 | one `axioms/*.json` axiom file (rules, operators, comparisons) | carried member |
| `RELM` | 1 | yes | 1 or 0 | one `models/*.json` relational model | carried member |
| `DEFN` | 1 | yes | 1 or 0 | `data/위키/정의문.jsonl`, the definitions asset | carried member |
| `ASET` | 1 | yes | 1 or 0 | any other pack member | carried member |

The writer orders chunks `MANI`, `STRS`, `MEMB`, `GDIR`, then one member chunk
per `MEMB` row in row order. Readers do not depend on that order. Writers use
compression 1 for member chunks only when it makes the chunk smaller, otherwise
0; readers accept either for any type.

A member chunk's type is chosen from its pack path, first match wins: suffix
`.kg` → `GRPH`; suffix `.학습.jsonl` → `LERN`; suffix `.수집.jsonl` → `COLL`;
`styles/*.json` → `LANG`; `axioms/*.json` → `AXIM`; `models/*.json` → `RELM`;
exactly `data/위키/정의문.jsonl` → `DEFN`; anything else → `ASET`. The type is
informative: the runtime finds members through `MEMB`, by path.

There are no schema or index chunks in 1.0 because a `.kgpack` holds none: the
axiom schema name (`nai-axioms-v1`) lives inside the `AXIM` member, and MARCO
builds its routing index when the model is opened.

### 6.1 `MANI` — manifest

A UTF-8 JSON object, written canonically: keys sorted, separators `,` and `:`,
non-ASCII characters written as themselves, no whitespace, no trailing newline.
Readers reject invalid UTF-8, invalid JSON, duplicate keys, `NaN`/`Infinity`,
and a top-level value that is not an object (malformed). Readers ignore keys
they do not know.

| Key | Type | Meaning |
| --- | --- | --- |
| `format` | `"mco"` | required |
| `format_version` | `[major, minor]` | must equal the header's |
| `name` | string or null | model name |
| `build_id` | string | model/build id. The writer's default is `"sha256-"` + the first 12 hex digits of the source pack's SHA-256, the same id the compat container gives the same pack |
| `content_sha256` | hex string | the **base identity**: SHA-256 of the model's content, defined exactly in 6.6. Together with `build_id` it is what a later overlay or snapshot binds to |
| `generator` | string | the writing program, e.g. `"mco 0.1.0"` |
| `semantic_schema` | `{"id": "marco-kgpack", "version": 3}` | what the members mean: MARCO pack format version 3 semantics |
| `requires` | list of strings | runtime features the file needs (below) |
| `runtime` | `{"backend": "mco-native"}` | which `mco` backend runs it |
| `source` | `{"kind": "kgpack", "bytes": n, "sha256": hex}` | hash of the input pack the file was compiled from. A source tree is first built into a pack, so this is that pack's hash; per-member input hashes are in `MEMB` |
| `model` | object or null | MARCO's model declaration (`nai-model` v1: `language`, `axioms`, `relational_model`), copied from the pack |
| `language` | string or null | the selected language pack path |
| `languages` | list of strings | every language pack path in the file |
| `counts` | object | `members`, `graphs`, `manager_nodes`, `strings` |
| `base` | null | reserved (section 8) |
| `change_sequence` | null | reserved (section 8) |
| `snapshot` | null | reserved (section 8) |
| `supports` | `{"overlay": false, "snapshot": false}` | stated plainly: this file can be neither the base of an overlay nor a snapshot in 1.0. Both are `false` in every 1.0 file; a 1.0 reader refuses `true` (unsupported) |

**Runtime features.** Version 1.0 defines two, and the writer lists both:

- `marco.kg-text/1` — `GRPH` members are MARCO `.kg` graph text, parsed by the
  runtime.
- `marco.pack-model/1` — `model` follows MARCO's `nai-model` v1 declaration.

A feature the reader does not know is unsupported. A non-null `base`,
`change_sequence` or `snapshot`, or a `supports` value other than `false`, is
unsupported in 1.0 (a reader that cannot apply an overlay must not run a file
that needs one). A `counts` value that disagrees with the tables is malformed.
A `content_sha256` that is not 64 lowercase hex digits is malformed; one that
does not match the content (6.6) is an integrity failure, found by full
verification.

### 6.2 `STRS` — string table (table)

```
u32 count
u32 reserved            0
u32 offsets[count + 1]  byte offsets into data; offsets[0] = 0; non-decreasing
u8  data[offsets[count]]
```

`raw_length = 8 + 4 × (count + 1) + offsets[count]` exactly. String `i` is
`data[offsets[i] : offsets[i+1]]`, valid UTF-8. Strings are unique and sorted
ascending by their UTF-8 bytes; the empty string is allowed. A *string id* is
the index `i`. `0xFFFFFFFF` is the null string id; no field of 1.0 is nullable,
so a 1.0 reader rejects it.

A string id is a **storage reference**, not an identifier (section 6.7): it
is local to the file, changes between builds, and nothing outside the file may
refer to one.

### 6.3 `MEMB` — member directory (table)

```
u32 count
u32 reserved            0
row[count], 56 bytes each:
  u32 path              string id of the member's pack path
  u32 chunk             TOC index of the chunk holding the member's bytes (a locator)
  u8  pack_kind         1 graph, 0 asset
  u8  reserved[7]       0
  u64 bytes             member size (the chunk's raw_length)
  u8  sha256[32]        SHA-256 of the member's raw bytes
```

`raw_length = 8 + 56 × count`. Rules (each violation is malformed unless noted):

- rows are sorted ascending by path (UTF-8 bytes), paths are unique; the
  path is the member's identifier (6.7);
- a path is relative POSIX: not empty, not starting with `/`, no empty, `.` or
  `..` segment, and is not `manifest.json`;
- `pack_kind` is 1 exactly when the path ends in `.kg`; at least one row is a
  graph;
- `chunk` indexes a member-type chunk, and `bytes` equals its `raw_length`;
- every member-type chunk is referenced by exactly one row;
- when a member is read, the SHA-256 of its decompressed bytes must equal
  `sha256` (mismatch: integrity failure).

### 6.4 `GDIR` — graph directory (table)

The pack's manager graph: one node per routable graph, with the role, goal and
example phrases the router indexes, and the edges joining them to the
manager's goal.

```
header, 32 bytes:
  u32 format            string id ("nai-kg-manager")
  u32 version           manager version (1)
  u32 role              string id
  u32 goal              string id
  u32 node_count
  u32 edge_count
  u32 example_count
  u32 reserved          0
node[node_count], 20 bytes each:
  u32 path              string id: the graph's graph_id (6.7)
  u32 role              string id
  u32 goal              string id
  u32 first_example     index into examples
  u32 examples          number of examples
u32 examples[example_count]       string ids
edge[edge_count], 12 bytes each:
  u32 from, u32 relation, u32 to  string ids
```

`raw_length = 32 + 20 × node_count + 4 × example_count + 12 × edge_count`.
Node `i`'s `first_example` equals the sum of the `examples` counts of nodes
`0 … i−1`, and the counts sum to `example_count`. A node's path must be the
path of a `MEMB` row whose `pack_kind` is graph; nodes are found by that path,
never by row position. Node paths are unique. Every string id must be
`< count` of `STRS`.

### 6.5 Rebuilding the pack

A runtime that needs MARCO's pack form rebuilds it from these chunks:

- `files`: one entry per `MEMB` row, `{"path", "kind": "graph"|"asset",
  "bytes", "sha256", "lf_normalized_sha256", "line_endings": {"crlf", "lf",
  "cr"}}`, where the last two are computed from the member bytes exactly as
  MARCO's `content_identity` does (CRLF and CR replaced by LF, then SHA-256;
  counts of CRLF, of LF not in CRLF, of CR not in CRLF);
- `manager`: `{"format", "version", "role", "goal", "nodes": [{"path", "role",
  "goal", "examples": [...]}], "edges": [[from, relation, to], ...]}` from
  `GDIR`;
- `model` from `MANI.model`; `format` `"nai-kgpack"`; `version` from
  `MANI.semantic_schema.version`.

The writer checks that this rebuild equals the source pack's manifest before it
writes, and refuses a pack holding anything Format 1.0 does not represent. The
reference reader rebuilds the pack as a deterministic ZIP identical, byte for
byte, to one MARCO's `write_pack` produces for the same members.

### 6.6 Content identity (`content_sha256`)

`content_sha256` is the SHA-256 of the canonical JSON of the rebuilt pack
manifest of 6.5 (keys sorted, separators `,` and `:`, non-ASCII written as
itself, UTF-8) followed by one `\n` byte. These are exactly the bytes of the
`manifest.json` member of the rebuilt pack, so the value equals the SHA-256 of
that member.

What it covers: that manifest lists, for every member, its path, kind, size and
the SHA-256 of its raw bytes, plus the manager graph and the model declaration.
So it covers every knowledge byte of the model, transitively. What it does not
cover: anything about the container (header, TOC, compression, chunk order,
padding) and the `MANI` chunk itself (name, generator, `build_id` and the
`content_sha256` field). Re-encoding the same content, with other compression
or a later table layout, keeps the same `content_sha256`; changing one byte of
one member changes it.

### 6.7 Identifiers

Every identifier in the format is a stable key derived from content, never a
position. Row indexes, string ids, TOC indexes and byte offsets are **storage
references**: they locate bytes inside one file, they may differ between two
builds of the same input, and they are never used to name a thing outside the
file, in an overlay, in a snapshot, or in the `mco` API.

The encoding is exact, so that this format and the Persistent Overlay
Infrastructure produce the same bytes for the same thing. `NFC(x)` is Unicode
Normalization Form C; every identifier is a UTF-8 string.

| Thing | Identifier |
| --- | --- |
| member | its pack path, e.g. `styles/english.json` |
| graph (`graph_id`) | `NFC(pack path)` with every `\` replaced by `/`, e.g. `graphs/graph_en_bill_split.kg` |
| node (`node_id`) | `graph_id + "#" + NFC(node name)`. The node name is the name the graph declares the node under: the text before `:` in a `[개념]`, `[사례]`, `[무관]` or `[공리]` line, without the leading `*` and without a `{...}` value or condition |
| edge (`edge_id`) | `"e:"` + the first 32 lowercase hex digits of the SHA-256 of `graph_id`, `NFC(src)`, `NFC(rel)`, `NFC(dst)`, each as UTF-8, joined by the single byte `0x1F`. One edge per destination of a `[논증]` or `[개념망]` line |
| rule (`rule_id`) | the rule's existing `id` string in its axiom file, unchanged (unique within a model) |
| model content | `content_sha256` (6.6), with `build_id` |

Example: `edge_id("graphs/a.kg", "총액", "이어짐", "몫을안다")` is `"e:"` + the
first 32 hex digits of SHA-256 over `graphs/a.kg␟총액␟이어짐␟몫을안다` (`␟` = byte
`0x1F`).

The reference functions are in `marco/storage/ids.py`, standard library only;
`mco/native/ids.py` is a byte-identical copy, because `mco` does not import
MARCO, and a test checks the two are identical and agree.

Reordering the lines of a graph, or the order members are given to the writer,
changes no identifier. In 1.0 only member, graph and model identifiers appear in
tables (`MEMB`, `GDIR`, `MANI`); node, edge and rule identifiers are fixed here
for the `NODE`, `EDGE` and `RULE` tables of the next slice and for the Persistent
Overlay Infrastructure.

## 7. Verification levels

- **Open** (always): header, TOC, layout arithmetic, required flags, chunk-set
  rules, and the `MANI`, `STRS`, `MEMB`, `GDIR` chunks with their checksums and
  table rules. No member chunk is read. Reading one member afterwards reads
  exactly that chunk and checks its two checksums. This is what lets a reader
  take one graph from a file without reading the whole file.
- **Full**: everything in *open*, plus every chunk's checksum (including
  skipped optional chunks), every member's raw SHA-256, `content_sha256`, and
  zero padding.
  `mco.load` and `mco.inspect` do a full verification unless called with
  `verify=False`.

## 8. Reserved for later slices

Reserved now so that later slices do not need a new major version. A 1.0 reader
treats each reserved chunk type as unknown (optional: skipped; required:
unsupported) and refuses a non-null reserved manifest key.

| Name | Where | Intended use |
| --- | --- | --- |
| `NODE`, `EDGE`, `RULE`, `INDX` | chunk types | node, edge, rule tables and a routing index replacing the carried `GRPH`/`AXIM` text |
| `OVLY`, `CHNG` | chunk types | Persistent Overlay Infrastructure: delta and change log |
| `SNAP` | chunk type | snapshot reference data |
| `PROV` | chunk type, **optional** | provenance of folded items: for each item a consolidation folds into a base, the id of the overlay change it came from. Reserved only; a 1.0 writer never writes it and a 1.0 reader skips it |
| `base` | manifest | `{"build_id", "content_sha256"}` of the immutable base an overlay or snapshot applies to |
| `change_sequence` | manifest | last Persistent Overlay Infrastructure change sequence folded into this file |
| `snapshot` | manifest | reference to the snapshot this file was consolidated from |

**Identity across files.** A reference from another file (an overlay on this
base, a snapshot) names the base by `content_sha256` and `build_id`, and the
thing inside it by an identifier of 6.7. It never stores a storage reference.

## 9. Safety

- No chunk contains pickle data, bytecode, or anything executed. Reading,
  inspecting or verifying a file runs no code from it.
- Every length is checked against the file and against the 256 MiB cap before
  any allocation; decompression is bounded by `raw_length`.
- Member paths are checked before they are used as file names.

## 10. Verdicts

| Condition | Verdict |
| --- | --- |
| fewer than 8 bytes, or `file_size` larger than the file | malformed (truncated) |
| wrong magic | malformed |
| `major` = 0 | malformed |
| `major` > 1 | unsupported |
| wrong `header_size`, `toc_entry_size`, nonzero reserved header field | malformed |
| file longer than `file_size` | malformed (trailing bytes) |
| `toc_count` > 65 536 | malformed (absurd count) |
| `toc_size` ≠ `toc_count × 64`, misaligned `toc_offset`, TOC outside the file | malformed |
| `header_sha256` mismatch | integrity failure |
| unknown required header flag | unsupported |
| bad type characters, `chunk_version` 0, value > 2^63 − 1 | malformed (overflow) |
| `length` or `raw_length` > 256 MiB | malformed (over the cap) |
| misaligned chunk, overlap, gap, chunk past the TOC | malformed |
| bad empty chunk, `length ≠ raw_length` without compression | malformed |
| unknown or newer required chunk | unsupported |
| missing or repeated `MANI`/`STRS`/`MEMB`/`GDIR` | malformed |
| chunk checksum mismatch | integrity failure |
| unknown compression on a chunk that is read | unsupported |
| decompressed output larger or smaller than `raw_length`, bad zlib stream | malformed |
| manifest not canonical-JSON-readable, wrong `format`, version mismatch | malformed |
| unknown required runtime feature, non-null reserved manifest key | unsupported |
| `supports` not `false` | unsupported |
| table rule violated (sections 6.2–6.4), `counts` mismatch | malformed |
| member raw SHA-256 mismatch, `content_sha256` mismatch (full verification) | integrity failure |
| nonzero padding (full verification) | malformed |
