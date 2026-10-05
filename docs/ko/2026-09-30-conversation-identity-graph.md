# Conversation identity graph — the rest of M1 on nodes, not strings

Owner's decision, 2026-09-30. Read `docs/ko/2026-09-22-freeze-decision.md` first
(the exam rule, no token-based model in the runtime) and the experiment log
`docs/ko/2026-09-29-experiment-log.md` (the audit of 2026-09-29: the state is right,
the grounding compares holders and things by the words of string keys in about
130 places and consults no graph).

**Baseline frozen:** tag `ur7-baseline-90` = `dd016c8`, frozen exam 90 of 108,
0 wrong, 0 violations, composition 340 of 340, reasoning 110 of 113. No further
patch on the string-key route is merged. The owner does not allow an architecture
outside MARCO's own: the internal language is the graph.

## The order

1. **Minimal conversation identity graph.** One node per holder, thing and place
   the conversation names, created when a statement is recorded; every mention
   (with its particle, title, relation word, other number, or pointer) is an edge
   from the mention to the node, with the turn it came from; a count is an edge
   from the holder node to the thing node with its value and its evidence turn.
   The node is the identity; the strings are its aliases. Minimal: only what the
   gate's turns need (identity, referent, frame), no general ontology, no
   knowledge-graph lookup yet.
2. **Reader partial candidates → node grounding.** The partial reading's open
   slots are filled with nodes, not key strings: each candidate is a node the
   conversation has (holders of the thing, things of the holder, the last
   frame's nodes), validated by replay and ranked as today (`_rank_candidates`,
   clear winner only, a tie asks, none holds, turn-local, effort levels kept).
3. **State, corrections and lookup by id.** The replayed facts are keyed by node
   id; a correction finds its event through the nodes; a question looks up by
   node; the pointer and salience code resolves to nodes. The string keys stay
   only as the nodes' aliases and in the trace.
4. **Re-verification of every existing pass.** The seven-step dialogue verbatim in
   both languages; the round-2 to round-7 reading tests, re-pinned only where a
   reply text changes and the meaning does not; the full suite at main's count
   with the 3 known failures; dev v3, v4, v5 and v6 check halves at their numbers
   or better; composition and reasoning gates unchanged.
5. **Frozen exam**, scored by the plan manager: 90 of 108 or better with 0 wrong
   and 0 violations before anything else is added; then the remaining causes,
   through the loop, on nodes.
6. **Gate.**

## Rules that do not change

Candidates validated by state and ranked by the declared order; an answer only
on a clear win; nothing kept after the turn except the conversation's own graph,
which is the state; effort 0 stays main's behaviour on the seven-step dialogue;
a declaration only for a word the pack lacks; no sentence-shaped entries; no
exam sentence anywhere; the full suite before every report; one cause per
report; the trace records the nodes a turn read and the candidates it dropped.

## Who does what

- **Questions chat** (branch `understanding-r7-questions`, it holds the map of the
  119 places): steps 1 and 2, then the question side of 3 (lookup, pointers,
  which-person, corrections).
- **Statements chat** (branch `understanding-r7-statements`): its current patch is
  stopped; it writes the re-verification set of step 4 first (the pins, the dev
  scores at the baseline), then the statement side of 3 (recording, the
  candidate steps `_read_other_keys`, `_read_unsaid_thing`, `_read_wrong_thing`,
  `_read_without_adjunct`, `_shaken_by_unread`) once the graph of step 1 is on
  main.
- The plan manager merges, scores the frozen exam after every merge, and keeps
  the log. The snapshot of a conversation (`ReasoningContext.snapshot`,
  `restore`, schema `reasoning-context-v9`) carries the graph, so a restart
  restores it.
