# Graph inference oracle

`mrl/oracle.py` is a read-only adapter over the baseline `graph_inference.py`.
`mrl/tests/fixtures/graph_inference_golden.json` contains input and expected
structured values; tests recompute values and compare Python structures without
regenerating the fixture.

The fixture records baseline commit `d5d91a21397fc5ac0d3ce0923d8756c867c85eca`,
the baseline source hash, and the adapter source hash. Hashes are SHA-256 over
UTF-8 source after LF normalization, so checkout line-ending conversion does
not change the pinned source identity. Updating either adapter or baseline
requires an intentional review and fixture refresh outside tests.

This oracle preserves current behavior rather than proposing MRL semantics:

- `closure` signals `graph_limit` and `join_limit` by raising `ValueError`.
- `closure_with_provenance` returns `complete: false`; initial fact overflow
  reports `graph_limit`, while derived graph, proof, and search caps report
  `proof_or_search_limit`.
- The provenance result exposes no separate incomplete status for `closure`.
  A later runtime must define that status explicitly; these fixtures cannot.
- Determinism here is the baseline's insertion-order proof selection and its
  replayable provenance bundle order, not a new MRL tie-break rule.
