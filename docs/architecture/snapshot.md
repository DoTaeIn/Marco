# Conversation snapshots

Slice 3 of the MCO scope for MARCO 1 (`docs/ko/2026-09-22-freeze-decision.md`,
"MCO scope for MARCO 1"; requirements from `docs/ko/2026-09-22-mco-integrated-roadmap.md`
§9, the snapshot paragraph). Code: `marco/storage/snapshot.py` (format, writer, reader,
checks), `marco/storage/conversations.py` (the store's envelope), `mco/snapshot.py` and
`mco/backends/marco.py` (the `mco` surface). Tests: `tests/test_mco_snapshot.py`.

## Purpose

A snapshot fixes, at one point in time, what a conversation needs to continue in another
process, and the base and overlay it was valid for. Restoring it either continues the
conversation exactly or refuses with a named reason.

This is state and persistence infrastructure. Writing or restoring a snapshot changes no
knowledge: no graph, rule, sidecar or overlay is written, and nothing here learns. Folding an
overlay into a new base (consolidation) is not part of it.

## The file

```
MARCO-SNAPSHOT/1 <body length> <sha256 of the body, hex>\n
<body>
```

The body is canonical JSON: UTF-8, keys sorted, separators `,` and `:`, non-ASCII written as
itself, no NaN, no trailing newline. There is no pickle and nothing executable; reading a
snapshot runs no code from it. The same state gives the same bytes: the writer records no
time of its own (the turns' own timestamps are part of the state).

| Body key | Content |
| --- | --- |
| `format`, `version` | `"marco-snapshot"`, `1` |
| `base` | `content_sha256`, `build_id`, `format`, `format_version`, `identity_source` |
| `overlay` | `{"attached": false}` when no overlay is attached; otherwise `attached`, `seq`, `change_id`, `base_sha256`, `base_build_id`, `overlay_schema`, and `copy` (`encoding` base64, `bytes`, `sha256`, `data`) |
| `contract` | `runtime` (e.g. `mco 0.1.0; backend mco-native`), `requires` (features the reader must have), `schemas` (state schemas inside) |
| `conversations` | per conversation: `id`, `title`, `created_at`, `updated_at`, `turns` (`id`, `at`, `user`, `assistant`, `phase`), `reasoning_state` |
| `excluded` | what the snapshot does not hold, each with its reason (below) |

Features of version 1: `base-binding/1`, `conversation-turns/1`,
`reasoning-context-state/1`, `overlay-sqlite-copy/1` (only when an overlay is attached).
Schemas: `conversation-turns-v1` and the reasoning state's own (`reasoning-context-v1` to
`reasoning-context-v10`, the ones `ReasoningContext.restore` accepts).

`reasoning_state` is `ReasoningContext.snapshot()` unchanged, inside the envelope; its
`replay` record (the verified semantic input) is kept, so a restored context answers from it
without re-parsing the old turns. The binding to base and overlay lives in the envelope, so
`marco/reasoning/context.py` is not changed.

## The base

The base identity is `content_sha256`: for an MCO Format 1 file, its manifest's value
(format-1.md 6.6); for a compat `.mco` or a bare `.kgpack`, the SHA-256 of the pack's
`manifest.json`, which is the same number for the same pack. A snapshot written on a compat
file therefore resumes on the native file of the same content. `build_id` is recorded and
compared when both sides have one.

## The overlay

When an overlay is attached, the writer opens its own connection to the overlay file and
copies it with `Connection.backup(..., pages=-1)`: every page in one step under one read
transaction, so a commit running in another connection is wholly in the copy or wholly out
of it. The recorded `seq` and `change_id` are read from the copy itself, so they always
describe it. An overlay bound to another base is not recorded (`SnapshotBaseMismatch`).
`Snapshot.extract_overlay(path)` writes the copy to a new file after checking its size and
SHA-256.

The `mco` sessions of this version have no overlay attached: the engine does not read the
Persistent Overlay Infrastructure store yet. Their snapshots say `{"attached": false}`, and
resuming a snapshot that was taken with an overlay through `mco` is refused.

## What is excluded

| Excluded | Why, and what a resumed conversation does instead |
| --- | --- |
| `caches` | replay, parser and index caches; rebuilt on demand |
| `pending_plans` | a plan awaiting approval is not carried; the request is planned again |
| `persona_state` | not part of a conversation snapshot |
| `affect_state` | the expression state is memory-only by design (`views/kgpack_ui.py`); a resumed conversation starts with none. It only adds a short prefix to a reply, so a resumed reply can differ by that prefix, never in what it says |
| `understanding_history` | regenerable: the `mco` backend rebuilds it at resume from the turns' user texts, in order, as the original turns built it |
| `graph_dialogue_session` | the routed graph and its filled slots (`engine.Session`) are not serialisable here. A follow-up to an unfinished graph dialogue starts that graph dialogue again: after "12만원 나왔어", a snapshot, and a resume, "3명이야" is asked for the amount again (`needs_input`) instead of answering 40000 |
| `learning_sidecars` | learned-record sidecars and the runtime's learning directory are knowledge, not conversation state |

Personal state that *is* included, in plain text: the user's turns and the reasoning state
derived from them. A snapshot is not encrypted.

## Restoring, and every refusal

`snapshot.read(path)` then `Snapshot.restore_states(base, overlay)`:

| Condition | `marco.storage.snapshot` | `mco` |
| --- | --- | --- |
| no header, truncated, extra bytes, body SHA-256 differs, body not canonical JSON, malformed record | `SnapshotDamaged` | `SnapshotFormatError` |
| unknown snapshot version, required feature or state schema | `SnapshotUnsupported` | `SnapshotFormatError` |
| base `content_sha256` differs, or both build ids are recorded and differ | `SnapshotBaseMismatch` | `SnapshotMismatchError` |
| an overlay was recorded and none is attached; the overlay is bound to another base; its head is below the recorded `seq`; it holds another `change_id` at that `seq` | `SnapshotOverlayMismatch` | `SnapshotMismatchError` |
| overlay copy does not match its recorded size and SHA-256 (when extracted) | `SnapshotDamaged` | `SnapshotFormatError` |
| no snapshot file; several conversations and none named | `SnapshotError` | `SnapshotError` |

Same base and the same overlay head: each reasoning state is restored as saved and its replay
is used. Same base and an overlay that holds the recorded history plus later changes
(`"advanced"`; also any overlay when none was recorded): each state is returned without its
`replay`, so the context re-derives it from its observations under the current overlay.

## The conversation store's envelope

`ConversationStore(path, binding)` with `binding(content_sha256, build_id, overlay_seq,
overlay_change_id)`. A bound store writes `reasoning_binding` (base and overlay head) beside
each saved `reasoning_state`, and on `reasoning_state(chat)`:

- same base, same overlay head: the state as saved (as before);
- same base, another overlay head: the state without `replay`;
- another base: `ConversationBaseMismatch`, with both identities in the message; `get_chat`
  and `overview` still read the turns.

A chat saved without an envelope (every file written before this change), or a store opened
without a binding (`views/kgpack_ui.py` today), loads exactly as before. A state saved by an
unbound store drops an older envelope, so an old binding never vouches for a newer state.
`import_chat(record)` adds a snapshot's conversation under the store's binding; the caller
checks the snapshot first.

## Crash behaviour

- A snapshot is written to a temp file with a unique name in the target directory
  (`.<name>.<random>.<pid>.<random>.tmp`), flushed and `fsync`ed, moved over the target with
  `os.replace`, and the directory is `fsync`ed. A crash leaves the old file or the new one; a
  failed write removes its temp file and leaves the old file whole.
- The conversation store saves the same way. The temp name used to be the fixed
  `conversations.tmp`, which two processes could share; it is now unique per process and
  write. A failed save still rolls the chat back in memory, as before.
- A snapshot written while an overlay commit runs records the head before that commit, and
  its copy holds exactly that head (tested with a commit stopped inside its transaction).
- A reader refuses a partial file by its recorded length and digest; it never guesses.

## Measured cost (2026-10-01, macOS laptop, busy machine)

A 20-turn Korean conversation (statements and questions about two counts) on a native model
compiled from `graph_정산_나눠내기.kg` and `graph_일상추론.kg`, in one process:

| What | Value |
| --- | --- |
| snapshot size | 8,933 bytes |
| `Session.snapshot`, median of 5 | 1.1 ms |
| `Model.resume`, median of 5 | 0.52 s, nearly all of it regenerating the understanding history (about 25 ms per turn); reading and checking the file 0.4 ms |
| first answer after resume, median of 5 | 33 ms (the same question without a restart: 31 ms) |
| conversation store save per turn, median | 0.6 ms (the `mco` backend now saves each turn) |

An attached overlay adds its SQLite pages as base64 (a one-change overlay copies to
98,304 bytes, about 131 KB in the snapshot).

## Not supported

- Consolidation: folding an overlay into a new base.
- Persona state, affect state and pending plans (excluded above).
- Cross-version migration: a reader refuses a snapshot version, feature or state schema it
  does not know; nothing is converted.
- An overlay attached to an `mco` session (the engine does not read the overlay yet).
- Carrying an unfinished graph dialogue (`engine.Session`).
- More than one conversation from `mco`: the format holds several; `Session.snapshot`
  writes one.
- Partial restore, compression and encryption.
