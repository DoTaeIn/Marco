# Published tax trial receipts — 2026-11-22

The `weight_test` source and the two hand-over documents were already committed in
`e81da1dd` and `6d74db80`. This publication adds only the public tax trial records captured
and audited in this chat. It does not change the reader, field packs, runtime or `main`.
The earlier hand-over's statements that these receipts were local describe the earlier moment.

## Continue on another computer

1. Check out `weight_test`, including this publication commit.
2. Read the root `HANDOFF-WEIGHT-TEST-2026-11-22.md` and `MIGRATION-weight_test.md`.
3. From the repository root, restore the exact recorded outputs and historical source files:

```sh
python3 experiments/tax_graph_trial_20261119/restore_receipts.py
```

This restores files; it does not train a model, run questions, change Git's index or overwrite
changed local files. It verifies all 457 checksums first. Existing identical files are kept.
An interrupted restoration can be run again. Python 3.9 or later is required.

The raw first returns and historical source versions are compressed in
`receipts-20261119.tar.gz`. Source bytes already present in this commit's Git ancestry are
reused through exact Git blob identifiers instead of storing duplicate source copies.
`RECEIPTS-MANIFEST.json` records every original path, byte length and SHA-256. No original
receipt or pinned source content was edited for publication.

## Results preserved

The final audited run is `rerun_after_acquisition_fix_20261119/REPORT.md`:

| Configuration | Main questions: returned values agree | Held |
|---|---:|---:|
| Existing frozen model | 10/24 | 14 |
| Same examples rebuilt with connector variants | 14/24 | 10 |
| Expanded 132 examples | 18/24 | 6 |

The last row includes three partial readings. No answer was independently verified by the
older executor. The same exposed questions were reused; this is regression evidence, not
fresh generalisation. Four supplemental controls remain separate from the 24 main questions.

The original runs and the length-fix and sentence-fix regressions are preserved too. Two
other locally generated `helds_fix_20261119/results.jsonl` and
`lessons_fix_20261119/results.jsonl` files are outside this publication; their tracked
implementation reports are already available. Unrelated tests and concurrent work are excluded.

The current implementation has moved beyond the audited source snapshots. Publishing these
records does not certify the latest implementation's reported results. No model evaluation was
rerun for this publication.
