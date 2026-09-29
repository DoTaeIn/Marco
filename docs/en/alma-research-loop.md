# ALMA 0.1 research loop (not in MARCO 1)

> Moved out of the root README on 2026-09-29, unchanged. Numbers and `engine.py` line
> numbers are as measured at `5f321a3` unless a line says otherwise; the root README
> carries the current gate numbers.


`alma/cli.py` is a small, resumable environment that reuses the event and proof
core. It keeps personal state outside portable `.kgpack` knowledge. ALMA
advancement is frozen; the existing loop stays and its tests run. Design record:
[docs/ko/alma-0.1.md](../ko/alma-0.1.md).

```bash
python -m alma.cli --state .nai/alma-state.json --identity demo --turn "민수 구슬은 8개 있다."
python -m alma.cli --state .nai/alma-state.json --identity demo --search "민수" --search-kinds event,log
python -m alma.cli --state .nai/alma-state.json --identity demo --project-state-at 2
python -m alma.cli --state .nai/alma-state.json --identity demo --backup-state .nai/alma-backup.json
python -m alma.cli --state .nai/alma-environment.json --identity demo --environment bench/alma_local_environment.json --step-budget 1
```

| Claim | Test in `tests/test_alma_cli.py` |
| --- | --- |
| The durable ledger is searchable by kind | `test_cli_exposes_durable_ledger_search` |
| A backup keeps a personal life separate from its original state | `test_cli_backup_keeps_personal_life_separate_from_its_original_state` |
| Personal state is restored from a pack in a clean working directory | `test_cli_restores_personal_state_from_a_pack_in_a_clean_working_directory` |
| The local environment starts and resumes | `test_cli_starts_and_resumes_the_local_environment` |
| A timed personal state is projected | `test_cli_projects_a_timed_personal_state` |
| A structured mental-event condition is evaluated | `test_cli_evaluates_a_structured_mental_event_condition` |
| A missing capability adapter returns `adapter_unavailable` instead of changing state | `test_alma_runtime.py` (the `adapter_unavailable` tests) |
