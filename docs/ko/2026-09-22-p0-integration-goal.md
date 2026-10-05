# Goal P0: integrate goal 2 and park `mco/` — main stays green

Model: the owner's chat model, effort high. Read `docs/ko/2026-09-22-freeze-decision.md` first.
Written 2026-09-22. Starts now. One chat, own hidden checkout branched from `main`.

## Why this is a goal and not a merge command

Goal 2 (`repair-and-english`, commit f985857) was built on f02d803. `main` is
now at 542e8d9 (ALMA evidence commit + the S1 audit). With goal 2's edits laid
over `main`, five tests that pass without them fail:

- `tests/test_mco_package.py`: `test_inspect_reports_model`,
  `test_reason_is_self_contained`, `test_backend_can_be_swapped_without_changing_user_code`,
  `test_benchmark` (30/30 passed on 6195040 without goal 2)
- `tests/test_alma_integrated_reproduction.py::test_fixed_alma_life_reproduction_has_no_wrong_checks`

Plus two known machine-dependent failures in `tests/test_response_composer.py`
that are not this goal's problem.

## Steps, in order

P0.1 **Bring in the untracked work.** These files exist only in the main folder
     `/Users/dotaein/Downloads/NAI`, untracked. Copy them into your checkout by
     absolute path and commit them by name, as one commit each:
     - `mco/`, `docs/mco/`, `pyproject.toml`, `tests/test_mco_package.py` → commit "Add the mco public API package"
     - `docs/ko/2026-09-22-*.md`, `docs/ko/test-speed-2026-09-22/` → commit "Record the plans, the freeze decision, and the goal files"
     Copy exactly these. Do not copy `__pycache__`, `.nai/`, `HANDOFF*.md`, or `.kgpack`.
P0.2 **Merge `repair-and-english` into your branch.** Resolve conflicts keeping
     both sides' intent; list every conflicted file in the report.
P0.3 **Make the five tests pass without weakening them.** A fix changes product
     code or the mco package, never an expected value, unless the report shows
     with evidence that goal 2 changed the declared behaviour on purpose (then
     cite the goal 2 test that declares it). Each fix: file:line and one line why.
P0.4 **Full suite, parallel:**
     `python -m pytest tests -q -n 12 --dist loadfile -p no:cacheprovider --basetemp=/tmp/p0-pytest`
     Expected: only the two `test_response_composer` failures remain, or zero.
     Record counts and wall time. Baseline: 816 passed / 7 failed, 3m34s.
P0.5 **Goal 2's own tests still pass:** `tests/test_repair_and_english.py` 19/19.
P0.6 **Report** the merge commit hash, the fix list, the suite counts, and the
     branch name. The owner merges to `main`. Do not push.

## Owns

Everything, for this goal only, because integration touches whatever conflicts.
Still forbidden: frozen areas (no new POLO, MCO binary, planner, or ALMA
features), rewriting tests to pass, deleting tests.

## Working conditions

Commit by name. Author is the repository owner, no co-author lines, no
assistant name. `python`, not `python3`. Do not push.
