# Goal W4: realizer round 4 — "why" said from the trace graph

Model: Opus 5.5, effort high. Read `docs/ko/2026-09-22-freeze-decision.md` first,
then `docs/architecture/naming.md` (Palinorrhesis, Hypomnema), `docs/architecture/trace-ledger.md`,
`docs/requests/L1-2.md` (the request this goal answers), and `marco/language/W1-report.md`.
Written 2026-09-24. Own checkout, branch `realizer-r4`. Runs alongside G4
(understanding round 4), which owns the parsing side, the engine files and
`styles/*.json`. You touch none of those.

## Why now

The trace ledger (L1) is merged: `marco.trace.why.Graph(ledger).chain(output_id)`
returns every event an answer rests on. The design note's principle 6 says the
explanation of an answer is a projection of that chain, not a separate truth.
Today "why?" in a dialogue is answered from the engine's own explanation
object; the chain-based explanation exists only as field values printed side by
side. This goal makes the chain speakable, in both languages, through the
realizer, with the same round trip every other reply gets.

## Definition of done — all six, measured

W4.1 **Chain → meaning.** `marco/trace/explain.py`: `chain_meaning(graph, output_id)`
     returns a language-free meaning (`act: explain`, `kind: chain`) with the
     roles L1-2 lists: the conclusion (`fact`), the state changes in order
     (subject, before, after, operation type, rule id when present), the
     statements they rest on by turn (quoting `input_received.payload.text`),
     and a correction as `conclusion_withdrawn` with `superseded_by`. A hold
     output gives `kind: chain_hold` with the reason and what was missing.
     Tests on the seven-step dialogue's ledger in both languages: the answer
     after the restart names turns 1, 2, 5 and 9.

W4.2 **Plans in both languages.** `meaning.json`, `english.json`, `한국어.json`:
     an explain plan for `chain` and `chain_hold` that says, in order, what was
     recorded, what changed and by which rule, what was withdrawn after a
     correction, and what was concluded. Every clause goes through the check
     layer like any other reply (numbers, polarity, quotations, reading,
     ellipsis). Composed, never passed through: `realizer.last_report()["realized"]`
     true for every explanation in the tests.

W4.3 **Entry points without engine edits.** `python -m marco.trace why <ledger>
     <event_id> --say ko|en` prints the composed explanation;
     `marco.trace.explain.say_why(ledger_path, event_id, language)` for code.
     Wiring "왜?" / "why?" in a live dialogue to the ledger needs a change at the
     engine's why site, which G4 owns now: write it as `docs/requests/W4-1.md`
     (file, function, the call to make, and the fallback when recording is off).

W4.4 **Fluency sample.** Record the round-3 dev set (`data/benchmarks/dialogues_dev3/`,
     seen data) with `python -m marco.trace record`, pick 20 answered and 10
     held outputs across both languages, and write their composed explanations
     to `marco/language/measurements/fluency-sample-why.md` with an empty
     judgement column for the owner. Never the frozen sets.

W4.5 **Round-4 meanings kept ready.** W3's plans for the user as holder,
     places, titled and relational holders, zero and vague counts stay green
     (`tests/language/test_w3_round4_meanings.py`). Two of those tests pin the
     English pack as it was before G4's batch 1 (`docs/requests/G4-1.md` in G4's
     branch, not yet on main): leave them; the owner re-pins them at G4's merge.

W4.6 **Nothing regresses.** Composition on dev, dev2, dev3 and the fixed sets
     unchanged (W3 recorded 269/269, 415/415, 468/468, 71/71); `tests/language/`,
     `tests/trace/`, the seam and composition tests; full parallel suite at
     main's count with the same known failure. Report the numbers and the
     commit hash. Do not push.

## Owns

`marco/language/` (all), `marco/trace/explain.py` (new), `marco/trace/__main__.py`
(the `--say` option only), `tests/language/`, `tests/trace/test_trace_explain.py`,
`marco/language/measurements/`, `docs/requests/W4-*.md`.

Must not touch: `engine.py`, `reasoning_context.py`, `state_engine.py`,
`frame_induction.py`, `language_components.py`, `relational_semantics.py`,
`explain.py`, `pack_model.py`, `styles/`, `views/`, `bench/`, `mco/`, `alma_*`,
the rest of `marco/trace/`, any frozen area, any frozen benchmark.

## Working conditions

Commit by name, owner as author, no co-author lines, no assistant or model
name in commits or product files. `python`, not `python3`; `KG_ENCODER=문자` on
every run. Report tersely: W4.1–W4.6 with numbers and the commit hash.
