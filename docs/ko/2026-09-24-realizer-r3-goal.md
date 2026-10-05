# Goal W3: realizer round 3 — close the requests, say every kind

Model: the owner's chat model, effort high. Read `docs/ko/2026-09-22-freeze-decision.md` first.
Written 2026-09-24. Own checkout, branch `realizer-r3`. Runs alongside G4
(understanding round 4), which owns the parsing side.

## Facts

- Frozen composition after round 3: **340 of 340** composed. Gate 5 is met.
  Keep it met.
- Open requests from round 3, in `docs/requests/`:
  - **G3-1:** the realizer's own repair tag still says `[수선]`; the packs say 수정.
  - **G3-2:** a count of one is said as "1 knives"; irregular singulars
    (goose/geese, child/children) are held instead of said.
  - **G3-3:** when the realizer holds an answered turn, the turn keeps status
    `answered`, so the gate scores it unverifiable instead of hold. The seam must
    set the status to a hold when nothing is spoken.
  - **G3-4:** fewer, equal, tied comparisons and before/after answers are new
    question kinds on the parsing side; the realizer has no plan for them and
    passes the engine sentence through. Compose them in both languages.
- Goal G4 will add meanings for holders that are not bare names (first person,
  relational nouns, titles, appositions, places), zero and vague quantities,
  and referent repairs. Their replies need plans too; coordinate through
  `docs/requests/G4-<n>.md` and `W3-<n>.md`.

## Definition of done — all six, measured

W3.1 G3-1 fixed: no realizer string carries 수선; the label comes from the pack.
W3.2 G3-2 fixed: number agreement for one in both languages; English irregular
     plurals and singulars from a declared table; "1 knives" and held geese are
     tests.
W3.3 G3-3 fixed: a held reply sets the result status to a hold with a reason
     the scorer reads; the composition gate still reports 0 passed through.
W3.4 G3-4 done: composed answers for fewer, equal, tied, before and after, in
     both languages, tested on the 7-step, the 20 phrasings and your own
     sentences; the reasoning-gate tests still pass.
W3.5 **Plans for round 4's meanings** as they land in G4's requests: first
     person ("You have 3 apples." / "3개 있으시네요." style must follow the pack's
     declared person forms), places as holders, titled and relational holders
     said as the user named them, zero and vague quantities ("none left",
     "some, count unknown"). Each with tests in both languages.
W3.6 No regressions: `tests/language/`, seam, composition-gate, reasoning-gate
     tests, the full parallel suite at main's count with the same known failure;
     composition on `dialogues_dev3/` and, when it exists, `dialogues_dev4/`
     at 100%; a fluency sample 3 of 40 replies from dev4 for the owner.

## Owns

`marco/language/**`, `tests/language/`, `tests/test_language_seam.py`,
`tests/test_composition_gate.py`, `marco/language/measurements/`, and the
carve-out sites in `engine.py`, `marco/reasoning/context.py`, `views/kgpack_ui.py`:
reply-return sites and result-building `meaning` blocks only. Do not edit
`styles/*.json`; request G4 for template strings.

## Working conditions

Commit by name, owner as author, no co-author lines, no assistant or model name
anywhere. `python`, not `python3`. Do not push. Report tersely: W3.1–W3.6 with
numbers, routed sites as file:line, composition per set, and the commit hash.
