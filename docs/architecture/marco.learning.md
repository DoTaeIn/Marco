# `marco.learning`

Written 2026-10-01 against commit `e3a6394`; checked against `547f85b`, where `marco/learning/` is unchanged.

## Purpose

Propose changes to what MARCO knows or how it reads, and admit or use a change only after a
check: a routing gate (`authoring`), validation cases (`expressions`, `rules`), a held-out event
(`concepts`), or a comparison with the original closure (`chunking`). Goal S4 moved six root files here
(`self_authoring`, `proof_chunking`, `experience_concepts`, `expression_learning`,
`semantic_feedback`, `rule_learning` before S4; [target-map.json](target-map.json)).

The [freeze decision](../ko/2026-09-22-freeze-decision.md) keeps "the freeze on MARCO's
learning or reasoning behaviour", and MARCO 1 is published with "no autonomous learning". The
decision lists autonomous persistent learning, automatic rule creation and automatic graph
mutation from dialogue as not in MARCO 1. This page states what the code does; the MARCO 1 gate
in the freeze decision names no module here. Whether the gated exam turns depend on any of it
is not measured.

## Owns

| Module | What |
| --- | --- |
| [`__init__.py`](../../marco/learning/__init__.py) | empty; exports nothing |
| [`authoring.py`](../../marco/learning/authoring.py) | dictionary entries to candidate graphs in `graphs/후보/`, `engine.lint`, a gate that drops a candidate which takes a question away from the graph it already routed to (a question that more than 8 candidates take is given up and only counted), a whole-round drop when fewer questions route correctly afterwards, then admit, revert, re-audit; progress, admitted and dropped lists in `graphs/후보/.*.json`, round records in `자가학습기록.jsonl`. Its docstring says the gate does not check that a candidate is useful knowledge, and does not stop a candidate from answering a question no graph answered before |
| [`chunking.py`](../../marco/learning/chunking.py) | `propose`, `evaluate`, `invalidate`, `applicable`: a shortcut rule for an exact chain of two or more one-premise Horn rules that keeps the original proof; it is proposed inactive, `applicable` fails when a source rule changes, `evaluate` falls back to the original rules when the two closures differ, and `invalidate` records a counterexample and deactivates it (schema `alma-proof-shortcut-v1`) |
| [`concepts.py`](../../marco/learning/concepts.py) | `ExperienceConceptStore`: bounded concept candidates from saved action events (`sync`, `snapshot`, `restore`); its docstring says it generalises only an observed action-program shape and never asserts an unobserved outcome. `ReasoningContext` builds one per conversation (`marco/reasoning/context.py:239–240`); the comment there says it is never written into the base pack |
| [`expressions.py`](../../marco/learning/expressions.py) | `propose`, `propose_paraphrase`, `from_paraphrase`: a supervised expression template is kept only if every separate validation case passes after learning and at least one failed before; validation must hold a positive and a negative case and share no entity with the correction; its docstring says validation labels take no part in induction. On acceptance `propose` copies the learned data and templates into the parser it was given |
| [`rules.py`](../../marco/learning/rules.py) | `induce`, `propose`: a Horn rule from two or more aligned, corrected proof examples; `propose` needs positive and negative validation that shares no entity with the examples, and returns the candidate without mutating the model |
| [`feedback.py`](../../marco/learning/feedback.py) | CLI `diagnose / expression / paraphrase / rule`: `diagnose` reports on one question; the other three apply a correction JSON file to a relational model, require `--output`, and save there only when accepted |

## Does not own

- The parser and model that a correction changes: `RelationalParser` in `relational_semantics.py`
  (root). `RelationalParser.learn_rule` calls `rules.propose`.
- When learning runs. `views/kgpack_ui.py` calls `authoring.one_round`; ALMA calls `chunking` and `rules`.
- The dictionary reader: [`marco.knowledge.ingest`](marco.knowledge.ingest.md) (`dictionary.py`).
- The authoring suggestions still in `engine.py` (audit row E15, target `marco.learning.suggest`)
  and template learning in `relational_semantics.py` (target `learning/templates.py`); both splits are frozen.

## Depends on

- `chunking.py`: `marco.reasoning.inference` (`closure`).
- `rules.py`: `marco.reasoning.inference` (`closure`, `current_facts`).
- `concepts.py`: the Python standard library only.
- `expressions.py`, `feedback.py`: `relational_semantics` (root; lazily in `expressions.py`).
  `feedback.py` imports `expressions` lazily.
- `authoring.py`: `engine`, `purpose_graph`, `bench.routing_benchmark`, `marco.progress` at
  import; lazily `marco.knowledge.ingest.dictionary`, `bench.yardstick`. The structure audit
  ([structure-audit.md](structure-audit.md) A6) lists four of these as upward edges to fix in
  Phase 3 (`engine` for `lint` and `load_graph`, `bench.routing_benchmark`, `bench.yardstick`),
  with `marco/reasoning/context.py` → `concepts`; the freeze decision keeps the phase 3 splits
  frozen (row S4).

## Public interface

| Name | Imported by | Test |
| --- | --- | --- |
| `authoring.one_round`, `.read_round`, `.read_progress`, `.revert` | `views/kgpack_ui.py` | no test names them |
| `authoring.self_authored` | `bench/yardstick.py`, `tools/alias_diag.py` | no test names it |
| `chunking.propose`, `.evaluate`, `.invalidate`, `.applicable` | `alma/runtime.py:21` | `propose`, `evaluate`, `invalidate`: `tests/test_proof_chunking.py` (four tests); `applicable`: no test names it |
| `concepts.ExperienceConceptStore` | `marco/reasoning/context.py:239`, `bench/alma_cross_domain_transfer_reproduction.py`, `bench/alma_structural_transfer_reproduction.py` | `tests/test_experience_concepts.py` (ten tests); `tests/test_repair_and_english.py` lists `marco/learning/concepts.py` among the dialogue modules it checks for Korean prose |
| `expressions.propose` | `feedback.py`, tests | `tests/test_expression_learning.py`, `tests/test_r6_parse_speed.py::test_expression_learning_drops_the_literal_memos`, `tests/test_r6_parse_speed.py::test_two_conversations_on_one_model_do_not_share_what_one_learns` |
| `expressions.propose_paraphrase`, `.from_paraphrase` | `propose_paraphrase`: `feedback.py`, tests; `from_paraphrase`: tests (and `propose_paraphrase` itself) | `tests/test_paraphrase_learning.py` |
| `rules.propose` | `relational_semantics.py:2558` (`RelationalParser.learn_rule`), `alma/runtime.py:366` | `tests/test_rule_learning.py` |
| `rules.induce` | tests (and `rules.propose` itself) | `tests/test_rule_learning.py` |
| `python marco/learning/feedback.py` | command line | `tests/test_rule_learning.py::test_cli_publishes_only_validated_rule`, `tests/test_expression_learning.py::test_cli_only_publishes_successful_validation`, `tests/test_paraphrase_learning.py::test_cli_accepts_sentence_pairs_without_explicit_semantic_annotations` |
