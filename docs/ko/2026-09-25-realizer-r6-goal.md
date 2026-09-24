# Goal W6: realizer round 6 — what round 5 asked, and why with a named holder

Model: Opus 5.5, effort high. Read `docs/ko/2026-09-22-freeze-decision.md` first,
then `docs/requests/G5-2.md` (items 1 and 2 are yours), `docs/requests/W5-4.md`,
`docs/ko/2026-09-25-understanding-r6-goal.md` (class C: why with a restated
fact, whose replies you compose), `docs/architecture/naming.md`. Written
2026-09-25. Own checkout, branch `realizer-r6`. Runs alongside G6.

## Definition of done — all five, measured

W6.1 G5-2 item 1: a record kept while its count is not said (`act: hold`,
     `reason: unread_event`, `kept: true`) gets a plan that says it was recorded
     and why the count is not given; both languages; tests, 6 cases each.
W6.2 G5-2 item 2: `reference_which_event` listing an unread statement composes
     as an ask naming both; verify with tests, 4 cases each language.
W6.3 Why with a named holder and number (G6 class 13): the explain plans say the
     holder's count and its derivation when the meaning carries `about:
     {holder, value}`; when the restated number differs from the recorded one,
     the reply says the recorded value and does not confirm the wrong one;
     field names agreed with G6 through `docs/requests/W6-1.md`; tests, 10
     cases per language.
W6.4 W5-4: the runtime release stamp in `marco/trace/runtime.py` (you own that
     file for this item): version from `mco/_version.py`, build hash, pack
     digest; test.
W6.5 Nothing regresses: composition on dev to dev5 and the fixed sets unchanged
     or better; `tests/language/`, `tests/trace/`; full parallel suite at main's
     count with the same known failures. Fluency sample 6: 40 replies including
     20 why answers, both languages, empty judgement column. Report the
     numbers and the commit hash. Do not push.

## Owns

`marco/language/` (all), `tests/language/`, `marco/language/measurements/`,
`marco/trace/runtime.py` (W6.4 only), `docs/requests/W6-*.md`, and the carve-out
sites: the reply-return sites and the `meaning` blocks in `engine.py`,
`reasoning_context.py`, `views/kgpack_ui.py`. Must not touch parsing, repair,
matching or correction logic, `styles/*.json`, `bench/`, `mco/`, `alma_*`, any
frozen area, any frozen benchmark.

## Working conditions

Commit by name, owner as author, no co-author lines, no assistant or model name
anywhere. `python`, not `python3`; `KG_ENCODER=문자`. Do not push. Report tersely.
