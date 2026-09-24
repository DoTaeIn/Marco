# Goal G5: understanding, round 5 — the blocking classes, and readings as candidates

Model: Opus 5.5, effort high. Read `docs/ko/2026-09-22-freeze-decision.md` first,
then `docs/ko/2026-09-25-g5-compositional-understanding-design.md` (the owner's
design; this goal is its hybrid scope), `docs/ko/2026-09-24-understanding-r4-goal.md`
and G4's report in the freeze queue, `docs/requests/W3-1.md`, `docs/requests/L1-1.md`,
`docs/requests/W4-1.md`, `docs/architecture/trace-ledger.md`. Written 2026-09-25.
Own checkout, branch `understanding-r5`. Runs alongside W5 (realizer round 5),
which owns `marco/language/` and the reply-return sites.

## Where round 4 left the exam

Frozen dialogues: **40 of 108** answerable (from 21), 0 wrong, 0 violations,
records 115 of 150 (from 82). Round 4's own check half: records 88.5%,
answerable 66.7%, and it trailed the build half by 25 points, which stopped the
round at the guard. The natural-language method transfers; the reader still
reads one way and gives up when that way fails. The check half's blocking
classes, with counts: transfer verbs beyond give (send 10, give back 7, pass 6,
receive 6, of 34), holders that are places (10) or relations (6), "only"
quantities (11 of 17 zero / vague), fronting (13), question forms (9). Also:
some six ungrammatical Korean phrasings passed the checker.

## Two things at once

**A. The classes, the G4 way.** Declared closed classes for the list above,
statements first, largest class first, with the guard unchanged. The process
fix from round 4: **both check halves are phrased and scored before the first
fix**, and the check half is scored after every batch from batch 1.

**B. Readings as candidates, the design note's minimum.** Today the reader
commits to its first reading. Add, around the existing reader and without
replacing it: (1) the reader returns every reading its declarations allow, not
the first; (2) each reading is checked against the conversation's state (a
holder that exists, a count that can move, a recipient that is a holder), the
particles and the verb frame, and readings that fail are dropped with the
reason; (3) if exactly one survives it is used; if several survive and differ
in what they would record, the turn asks instead of guessing; if none, the turn
holds with the failing reasons. No numeric scores: constraints are declared and
ordered, and the order is in the report. G4's declarations are the primitives
(design note §15). Measured first on dev set v4's gold scenarios, which are the
meaning graphs the sentences were phrased from: reading accuracy per sentence
before and after B, both halves.

## Definition of done — all nine, measured

G5.0 **Housekeeping in your own files.** (a) Request W4-1: a live "왜?" / "why?"
     after an answer uses the trace graph's chain through `marco.trace.explain.say_why`
     when recording is on, the engine's own explanation otherwise; test. (b) Request
     L1-1, the minimum: at the sites the request lists in `reasoning_context.py` and
     `engine.py`, emit `routing_selected` with the candidates and their scores, `rule_applied`
     with bindings, `evidence_rejected`, and on every hold the gap class from the
     adaptive note's taxonomy (routing, lexical, concept, relation, parser, evidence,
     conflict) in `payload.gap`. (c) The dev-v4 checker rejects ungrammatical
     Korean (doubled endings, "가지고 없다", a statement that contradicts itself);
     re-phrase the affected dialogues with a new seed and record how many changed.

G5.1 **Dev set v5.** From the same generator: 80 or more new dialogues per language
     built around the blocking classes above, each class in at least 12 dialogues per
     language, plus **surface variation of the same scenario** (design note §18):
     for 40 scenarios, three phrasings each with different word order, subject
     omission, fronting, particles, honorifics. Build and check halves disjoint in
     names, items, places, phrased at different seeds, both phrased and scored
     before any fix. Zero sentence overlap with every earlier dev set; the frozen
     sets are never opened, the owner runs the overlap check.

G5.2 **Cause tables** from the ledger's statistics (`python -m marco.trace record`
     then `stats`) on both halves of v4 and v5 before any fix, root causes apart
     from cascades and realizer holds, counts summing to the totals.

G5.3 **Fixes A**, batches of declared classes, build then check after every batch,
     stop if check trails build by more than 15 points, rule table and
     declaration-to-code ratio per batch as in round 4.

G5.4 **Readings as candidates B**, measured: on v4's gold scenarios, per-sentence
     reading accuracy before and after, by half; on the surface-variation set of
     G5.1, the share of scenarios where all three phrasings give the same reading;
     the number of turns that became asks and holds instead of wrong readings.
     0 wrong on every set stays.

G5.5 **Targets on the check halves (v4 and v5 together):** records 92% or
     higher, answerable 75% or higher, 0 wrong, 0 violations, check within 15
     points of build. If unreachable, the blocking class with its count.

G5.6 **Multi-query, one class (Diairesis):** a turn with two questions is answered
     in order, each with its own evidence; tests, 10 cases per language.

G5.7 **Nothing regresses:** repair 19/19; r1 to r4 tests; round-3 check half 98/106
     or better; v4 check half at its final numbers or better; `tests/language/`,
     seam, composition and trace tests; full parallel suite at main's count with the
     same known failure.

G5.8 **Hand-off:** the commit hash and the tables. The owner scores the frozen sets.

## Owns

Same as G4: `frame_induction.py`, `language_components.py`, `relational_semantics.py`,
`hangul.py`, `engine.py`, `explain.py`, `reasoning_context.py`, `state_engine.py`,
`pack_model.py`, `styles/*.json`, `data/benchmarks/dialogues_dev4/` and `dialogues_dev5/`,
`tests/test_understanding_r5.py`, `tests/` files for those modules, the `--dataset`
handling in `bench/dialogue_gate.py`. The carve-out with W5 is the same as with W3
and W4: W5 owns the reply-return sites and the `meaning` blocks in `engine.py`,
`reasoning_context.py` and `views/kgpack_ui.py`; you own parsing, repair, matching,
correction, and the ledger emission sites of G5.0(b). Requests to `docs/requests/G5-<n>.md`.

Must not touch: `marco/language/`, `marco/trace/` beyond calling it, `mco/`, `alma_*`,
the gate scorers beyond `--dataset`, any frozen area. `build.py` must not read
`data/benchmarks/dialogues_v1/` or `reasoning_v1/`, not even for its overlap
check: drop them from its `OTHER_SETS`; the owner runs the overlap check.

## Working conditions

Commit by name, owner as author, no co-author lines, no assistant or model name in
commits or product files (the phrasing model's id is data in `build.py` and the
report). `python`, not `python3`; `KG_ENCODER=문자`. Commit after every batch. The
phrasing model runs only while building the sets. Do not push. Report tersely.
