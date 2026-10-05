# Goal S3: test hygiene and speed

Model: the owner's chat model, effort high. Read `docs/ko/2026-09-22-freeze-decision.md` first.
Starts after P0 (goal 2 merged to `main`), because it edits test files goal 2 changed.

## Baseline

Single process: 771 passed / 3 failed in 19m53s at f02d803 on the 14-core Mac.
Parallel measurement with `pytest-xdist -n 12 --dist loadfile` is recorded in
`docs/ko/test-speed-2026-09-22/xdist-first-run.txt` (written by the plan-manager
session on 2026-09-22; treat as the starting point, re-measure).

## Definition of done

T1. `pytest.ini` at the root makes `python -m pytest` run in parallel by default
    (`-n auto --dist loadfile`) and puts temp files under `.pytest_tmp/`, gitignored.
T2. Parallel pass/fail/skip counts equal the single-process counts at the same
    commit. Both runs recorded with wall time. Any test that passes alone and
    fails in parallel is fixed or isolated with a marker, each one listed.
T3. `tests/test_reasoning_persistence.py:create_app` and any direct corpus test
    skip with a named reason when `data/위키/정의문.jsonl` is absent. On a
    corpus-less clone the suite reports skips, not failures: count recorded.
T4. Every test file that exercises one language carries the `language` marker
    from `conftest.py`. Count of files with the marker equals the count of
    files that select a language, listed.
T5. Slowest 25 tests listed with durations before and after. Any test over 60 s
    is either split, marked `slow` and excluded from the default run, or
    justified in one line.
T6. Wall time of the default run is under 5 minutes on the 14-core Mac, or the
    report says what blocks it, by test name.

## Working conditions

Own hidden checkout, branch `test-speed`. Owns `pytest.ini`, `conftest.py`,
`tests/`, `.gitignore`. No product code edits. Commit by name, owner as author,
no co-author lines. Do not push.
