# Goal W5: realizer round 5 — the round-4 requests, the trace fields, the samples

Model: Opus 5.5, effort high. Read `docs/ko/2026-09-22-freeze-decision.md` first,
then `docs/requests/G4-1.md` (second part), `docs/requests/G4-2.md`, `docs/requests/W4-2.md`,
`docs/architecture/naming.md`, `marco/language/W1-report.md`. Written 2026-09-25.
Own checkout, branch `realizer-r5`. Runs alongside G5, which owns the parsing side.

## Facts

- Frozen composition after round 4: 340 of 340. Keep it.
- Round 4 made the packs read the user, titled holders, places and zero; the
  seven tests that pinned the old packs were re-pinned by the owner at the merge.
- Open requests: **G4-1** part two, a plan for the recipient correction (`revise`
  act, `field: recipient`, `old_holder`, `new_holder`) that names the two
  receivers instead of quoting the sentences; **G4-2**, the Korean realizer holds
  any total that includes the user (no declared word for the user inside a list
  or as a recipient); **W4-2**, the trace side of the report fields.
- The owner has three fluency samples to judge (sample 3, the why sample, and
  round 4's replies once recorded). Their judgements arrive as `docs/requests/OWNER-<n>.md`;
  fold them in when they do.

## Definition of done — all six, measured

W5.1 Recipient-correction plan in both languages (G4-1 part two); tests, 6 cases each.
W5.2 The Korean user inside a total, a comparison, and as a recipient, said with
     the declared honorific forms (G4-2); tests, 8 cases; the round-4 dev sets
     re-composed with 0 held for that reason.
W5.3 W4-2: the realizer report carries the meaning's act, reason and matched plan
     into the ledger's `output_created` event through `marco/trace/from_turn.py`
     (you own that file for this item only); test.
W5.4 Fluency sample 5: 40 replies from dev set v4's check half in both languages,
     empty judgement column, `marco/language/measurements/fluency-sample-5.md`.
W5.5 Plans for G5's new meanings (multi-query: two answers in one turn, each with
     its evidence; ask on ambiguous readings: "did you mean A or B?") through
     `docs/requests/W5-<n>.md` to G5 for the field names, as W3-1 did.
W5.6 Nothing regresses: composition on dev, dev2, dev3, dev4 and the fixed sets
     unchanged or better; `tests/language/`, `tests/trace/`; full parallel suite
     at main's count with the same known failure. Report the numbers and the
     commit hash. Do not push.

## Owns

`marco/language/` (all), `tests/language/`, `marco/language/measurements/`,
`marco/trace/from_turn.py` (W5.3 only), `docs/requests/W5-*.md`, and the carve-out
sites: the reply-return sites and the `meaning` blocks in `engine.py`,
`reasoning_context.py`, `views/kgpack_ui.py`. Must not touch parsing, repair,
matching or correction logic, `styles/*.json`, `bench/`, `mco/`, `alma_*`, any
frozen area, any frozen benchmark.

## Working conditions

Commit by name, owner as author, no co-author lines, no assistant or model name
anywhere. `python`, not `python3`; `KG_ENCODER=문자`. Do not push. Report tersely.
