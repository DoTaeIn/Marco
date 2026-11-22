# Korean tax graph trial

This folder is an isolated experiment. It uses the existing count-based reader and matcher without altering them. `lessons.json` contains fictional subjects and numbers; its annotated examples teach a linguistic construction, not actual tax answers. The model is built only from those examples.

Inputs, all JSON arrays:

- `lessons.json`: objects containing `id`, `kind`, `text`, and the existing teacher `graph` schema.
- `contexts.json`: objects containing `id`, `text`, `graph`, and `sources`, an array of objects each containing `url`, `as_of`, and `scope`. Graph anchors, edges, and evidence spans refer to the context text. Every trial question references the same `tax-all` context containing all 14 facts.
- `facts.json`: the source fact list, including scope and date; included in the frozen hashes.
- `questions.json`: objects containing `id`, `text`, and `context_id`. Reference answers and other metadata may be included for later scoring; the runner does not use them.

Run from the repository root with `python3 -m experiments.tax_graph_trial_20261119.runner freeze`, followed once by `python3 -m experiments.tax_graph_trial_20261119.runner run`. Freeze validates graphs, builds the model, and records hashes. Run rejects changed inputs, source, or model. Output creation is exclusive, and each arm's first result, including exceptions, is flushed immediately. An interrupted run must be reported as incomplete rather than overwritten or silently retried.

The graph arm matches the reader's predicted question graph against the supplied, manually constructed context graph. It is not end-to-end fact extraction. The end-to-end arm reads both the context and the question. Both arms use the existing native second opinion where matching finds an answer; unavailable, refusal and disagreement are recorded separately. The complete raw objects contain readings, count evidence, matching proofs, verification state, sources, and elapsed time. A no-answer result can mean an unsupported reading, a mismatch, refusal, or an error; it must not be conflated with a verified statement that a fact is unknown.
