# Conversation identity graph (M1, steps 1–3, question side)

Owner's decision 2026-09-30 (`docs/ko/2026-09-30-conversation-identity-graph.md`): the holders, things and
places of one conversation are nodes; every way the conversation named them is an alias edge; a count is an
edge from a holder to a thing. The node is the identity, the strings are aliases. Minimal: only what the gate's
turns need. No model, no general ontology, no knowledge-graph lookup.

## Schema

`marco/reasoning/identity.py`, class `ConversationGraph`, built from the recorded statements (the replayed
facts of `ReasoningContext._cached_replay`), kept on the context, carried in the snapshot.

| Part | Fields | Made from |
| --- | --- | --- |
| node | `id` (`h1`, `t1`, `p1`: stable in order of first mention), `kind` (`holder`, `thing`, `place`), `name` (the key word(s) the reader gave) | each count fact's key, split into holder and thing (a place from the fact's `places`; otherwise the holder is the longest holder key the key starts with, as `_holder_keys` splits today) |
| alias edge | `node`, `text` (as said), `form` (`key`, `said`, `title`, `relation`, `possessive`, `number` (pen/pens), `pointer`, `particle`), `turn` | the key; the words said right before the key in the statement (`Dr.`, `my cousin`, `김 … 과장님`, `제 친구`); the other declared number of a thing; pointers resolved by a question (`that one` → h2 at turn 5) |
| count edge | `holder`, `thing`, `value` (int, or `null` for a count not known), `origin` (`said`: a statement gave the value; `computed`: replay derived it from a transfer or a use-up), `turns` (the evidence turns it rests on) | the current state after replay (`current_facts`), its evidence; observed and inferred kept apart (principle 6), and "why" reads `origin` |
| frame | `turn`, `holders` (node ids), `thing` (node id), `op` | each question read (today's `last_frame`, `recent_frames`) |

**The split is not the graph's identity rule.** In step 1 a fact's key is split into holder and thing by the longest
holder key it starts with, because the replayed facts carry no split. Step 3 moves the split to the reader: the reader
names the holder node and the thing node of each fact, and the graph never splits a string. Until then a key split
wrongly today stays wrong in the graph (`보늬는 연필 세 개, 컵 두 개를 …` makes `컵` a holder); a strict expected
failure in `tests/test_conversation_graph.py` keeps it in view.

Lookups, all by node: `find(text, kind=None)` → nodes whose alias matches (folded; a declared particle, title or
suffix taken off first); `holders_of(thing)`, `things_of(holder)`; `count(holder, thing)`; `key(holder, thing)` →
the string key the replay uses, for the one place strings are still needed (step 3 removes it).

Snapshot: schema `reasoning-context-v10` adds `graph` (nodes, aliases with turns, frames); counts are rebuilt by
replay, the aliases a statement cannot give (pointers resolved, which-person answers) are kept. A v9 snapshot
restores with a graph rebuilt from its observations. Trace: `routing_selected.payload.nodes_read` lists the node
ids a turn resolved to.

## What each step replaces (places of the 2026-09-29 map, `marco/reasoning/context.py`)

**Step 1 — the graph, nothing else changes.** New module, snapshot v10, trace field. No reply changes.

**Step 2 — partial candidates grounded to nodes.** The candidate generators take nodes, not split strings:
`_partial_frame` (slot candidates = the frame's holder/thing nodes; the named word → nodes by `find`),
`_ground_question` (holder/thing words → nodes; open thing → `things_of`), `_which_person` (candidates =
`holders_of(thing)`; description → relation/title aliases instead of a regex over statement text),
`_ground_pair` (the two = frame holder nodes, else `holders_of`), `_named_reply` (reply word → node among the
asked candidates), `_record_frame` (frames hold node ids). The local `holder(subject)` helpers go.

**Step 3, question side — lookup, pointers, which-person, corrections by id.** `_ground_lookup` (a near key is
an alias edge: number, title, particle, relation), `_holder_keys`/`_holder_of` (become `graph.find`),
`_resolve_pointers`, `_alone`, `_salient_choice`, `_remember_referents`, `_pointer_readings` (candidates and
salience are node ids), `_name_reply` (the name replaces a node, not the first k words), `_unknown_subject` /
`_premise_missing` (a name with no node), `_correction_frame`, `_correct_by_reference` (touched holders),
`_recipient_contrast`, `_correct_recipient` (giver/receiver as nodes), `_explain_count`, `_answer_other_than`,
`_compared`, `_declare_holders`. The statement side of step 3 (recording, `_read_other_keys`,
`_read_unsaid_thing`, `_read_wrong_thing`, `_read_without_adjunct`, `_shaken_by_unread`) is G7-S's, through the
same `ConversationGraph` API (request `docs/requests/G7-4.md`).

## Rules kept

Candidates validated by replay, ranked by the declared order, a clear win answers, a tie asks, none holds;
effort 0 is main's behaviour on the seven-step dialogue; the graph is the conversation's state (persists in the
snapshot), candidates stay turn-local; a declaration only for a word the pack lacks; no sentence-shaped entries.
