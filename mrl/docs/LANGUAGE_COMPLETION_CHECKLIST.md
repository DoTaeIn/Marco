# Language completion acceptance

The earlier language slice is recorded in `LANGUAGE_VERIFICATION.json` and
`LANGUAGE_TEST_LOG.txt`. The graph growth, runtime rule editing, and indexed
startup extension has its own current full-suite result and source/protected
hashes in `SCALABILITY_VERIFICATION.json` and `SCALABILITY_TEST_LOG.txt`.
Run the suite with `python -B -m mrl test`.

| Area | Runnable evidence |
| --- | --- |
| Checked operations and control flow | `test_language_core.py`, `test_language_acceptance.py` |
| Scalars, enums, optional values, and exhaustive matches | `test_language_core_enums.py`, `test_language_core_options.py`, `test_language_frontend_completion.py` |
| Managed strings, collections, records, and scope cleanup | `test_language_values.py`, `test_v9_managed_values.py`, allocation/poison cases in `test_language_acceptance.py` |
| Runtime input, graph storage, and knowledge queries | `test_language_app_e2e.py`, graph payload acceptance, `test_language_domain.py` |
| Result errors and failed input transactions | `test_v6_knowledge.py`, `test_language_io.py`, `test_language_ffi.py` |
| CLI, modules, and original source diagnostics | `test_language_tools.py`, `test_module_diagnostics.py`, module acceptance cases |
| Epistemic states, candidates, provenance, and history | `test_language_domain.py`, `test_language_app_e2e.py` |
| UTF-8 argv/file APIs | `test_language_io.py`, `test_language_io_helpers.py`, Unicode app E2E |
| Explicit unsafe C scalar/pointer boundary | `test_language_ffi.py`, `test_language_frontend_completion.py`, source FFI E2E |
| Retained answers and incremental growth | `test_language_growth_acceptance.py`, `test_growth_runtime.py` |
| Graph storage beyond 64 nodes / 256 edges and owned recursive search results | `test_dynamic_graph.py`, `test_scalability_acceptance.py` |
| Rule add/replace/remove, old proof versions, and durable rule changes | `test_scalability_acceptance.py`, `test_language_domain.py` |
| Selective indexed startup, durable fact edits, and stale-writer rejection | `test_indexed_storage.py`, `test_scalability_acceptance.py` |

The source-only [application](../examples/language_app/README.md) imports a
module, reads Unicode data from a caller-relative path, derives a fact, prints
its proof, saves a checkpoint, commits a supersession with evidence, and checks
current plus historical facts after a fresh-process restore.

This is an experimental implementation of the agreed slice. It does not imply
self-hosting, unrestricted generics, unbounded graphs/proofs, a package registry,
or a universal speed advantage over Python. See [tooling](LANGUAGE_TOOLING.md),
[managed values](LANGUAGE_VALUES.md), [domain APIs](LANGUAGE_DOMAIN.md), and
[unsafe FFI](LANGUAGE_FFI.md) for concrete contracts and limits. Historical
benchmark reports retain the measurements and code hashes of their own runs.
