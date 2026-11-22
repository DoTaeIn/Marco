# Migration notes: the count-based reader on `weight_test`

Written 2026-11-22 for whoever continues this work, human or AI. It is self-contained: read
this file first, then `experiments/graph_weighted_acquisition/CONTRACT.md` for the rules in
force and `README.md` in the same folder for the measured history.

## 1. What this is

A small, explainable question-answering system for Korean that uses no neural network, no
embedding and no token prediction. It reads text into a graph using integer counts taken from
a few hundred annotated lessons, matches a question graph against a knowledge graph, and
writes the answer back as a sentence. Every decision carries its count and the ids of the
lessons behind it.

- Repository: `https://github.com/DoTaeIn/Marco.git`
- Branch: `weight_test`, pushed, one commit `e81da1dd` on top of `fb32c969` (which is on `origin/marco2`)
- Code: `experiments/graph_weighted_acquisition/` (about 2,300 lines of Python, standard library only)
- It builds on two older packages it imports unchanged:
  `experiments/graph_example_acquisition/` (graph checks, the older "native" executor) and
  `experiments/graph_language_repair/` (the query-graph engine behind that executor).

## 2. The owner's rules (do not break these)

1. **Keep it pure.** No token model, embedding or neural network anywhere in the run path,
   including for wording answers.
2. **Least Python, maximum graph.** Behaviour belongs in graph data (packs). Python should be a
   small generic engine. Before adding Python, ask whether the decision can be pack data.
3. **Three packs:** language, field words, facts. Changing the field must not need code or lessons.
4. **The product is a light model for one specific field.** A general one would be a very large
   graph run in the cloud; that is not the current goal.
5. **Fail closed.** A wrong answer is worse than no answer. Every run so far has 0 wrong answers;
   keep it that way. Anything read loosely must be flagged in the answer.
6. **No assistant, vendor or model name anywhere in the repository,** including commit messages,
   file names and co-author lines. Scan before every commit and push.
7. **Commit and push only when the owner asks.** Unfinished work goes on a branch, never `main`.
8. **Reports to the owner:** in English, short, with numbers and denominators, pass/fail stated plainly.
9. **Measurement discipline:** say what a number was measured on and whether that set was seen
   while building. Do not tune on a set and then report it as generalisation.
10. **One heavy job at a time** on this laptop; check running processes first.
11. **Hand-over file:** `HANDOFF.md` at the repository root (git-ignored) is the running log
    between sessions. Read it at the start, append a dated block at the end.

## 3. Layout

`experiments/graph_weighted_acquisition/`

| File | Role |
|---|---|
| `reader.py` | Builds the count model from lessons (`build`) and reads text (`read`): sentence split, cutting into pieces, meanings, roles, choice between readings, unknown-word detection |
| `match.py` | Matches a question graph against a passage graph by backtracking; loose name matching in levels |
| `answer.py` | `answer` (passage text + question) and `answer_graph` (given graph + question); second opinion from the older executor; `explain` writes the full report |
| `write.py` | `say` writes a sentence from a meaning and keeps it only if the reader reads it back as that meaning; `answer_sentences` |
| `learn.py` | Provisional memory for words told in conversation: `teach`, `mark_name`, `forget`, `overlay`, `propose` |
| `variants.py` | Finds connector variants (은/는, 을/를) in raw text by counting; `check_against_lessons` |
| `pack.py` | Three packs: `language_pack`, `with_words`, `load`, `ask`, `tell` |
| `merge.py` | Merges a repeated name into one node, gated by lesson counts (gate is closed with current lessons) |
| `weights.py`, `driver.py`, `augment.py` | Earlier stage: count weights for the template learner, and blind name substitution to scale lessons |
| `data/reading_recipe.json` | Which counts decide what, plus engine conventions. Copied into every language pack at build |
| `data/connector_variants_ko.json` | The two pairs learned from raw text |
| `data/korean_given_names.txt` | 660 names used for blind scaling |
| `packs/` | `make_language.py`, `language_lessons.json`, `language.json`, tax and library word and fact packs, `library_questions.json`, a sample report |
| `tests/test_reader.py`, `tests/test_weights.py` | 44 tests |
| `CONTRACT.md` | Every rule in force, in the order it was decided, including rejected ideas |

`experiments/tax_graph_trial_20261119/` holds a tax trial run by another session. Only its
inputs and two lesson sets are in git: `questions.json`, `facts.json`, `lessons.json`,
`contexts.json`, `runner.py`, `lessons_fix_20261119/`, `helds_fix_20261119/`. Its frozen run
outputs and source snapshots stay local and must not be edited.

## 4. How it works

1. **Lessons** are examples in the teacher schema (`experiments/graph_example_acquisition/SCHEMA.md`):
   a text, a graph (`nodes`, `edges`, `edge_spans`, `project`), with character spans as evidence.
2. **`reader.build(lessons, variants=None)`** counts pieces into tables: connectors and where they
   occur, fixed words and their meanings, which connector marks which role, word order, what a
   sentence ending does (asks / claims / states), name lengths, and more. The result is a JSON
   model of counts with lesson ids. This is the **language pack**.
3. **`reader.read(text, model)`**
   - cuts the text into sentences at learned closing pieces followed by blank space;
   - cuts each sentence into connectors, fixed words, stem+ending words and free values;
   - gives each argument a head and a role by counts, following the recipe in the pack;
   - chooses a reading only if every count it relies on is nonzero and it leads clearly;
   - otherwise holds, and names an unknown word when that is the only thing wrong.
4. **Trust tiers of a reading**, most trusted first: fully seen; read through a raw-text variant
   or a broader count (flagged); partial, with unknown words ignored (flagged, questions only).
5. **`match.match`** assigns question nodes to passage nodes so every condition holds. Names are
   compared exactly, then through other names from the word pack, then ignoring spaces, then
   with leading words ignored and reported.
6. **`answer.answer_graph`** adds the second opinion of the older executor (agrees / disagrees /
   refuses / unavailable / not comparable), yes/no claim checking, and the answer as a sentence.
   Only "agrees" with a full reading counts as verified.
7. **`pack.load(language, words, facts)`** gives field words the pooled counts of lesson words in
   the same slot, writes every fact as a sentence, reads it back, and keeps fact-to-sentence
   links so answers cite sources.

## 5. Running it

There is no `pytest` for `python3` on this machine. Tests are plain functions; run them with:

```python
# save as run_tests.py
import importlib, sys, traceback
failed = 0
for name in sys.argv[1:]:
    mod = importlib.import_module(name)
    for attr in sorted(dir(mod)):
        if attr.startswith('test_'):
            try:
                getattr(mod, attr)(); print('PASS', attr)
            except Exception:
                failed += 1; print('FAIL', attr); traceback.print_exc()
sys.exit(1 if failed else 0)
```

```bash
PYTHONPATH=. python3 run_tests.py experiments.graph_weighted_acquisition.tests.test_reader experiments.graph_weighted_acquisition.tests.test_weights
```

Expected: 44 PASS. Two older tests in `graph_example_acquisition` need pytest fixtures and
cannot run this way.

Ask a field a question:

```python
import json
from experiments.graph_weighted_acquisition import pack
B = 'experiments/graph_weighted_acquisition/packs/'
system = pack.load(json.load(open(B + 'language.json')), json.load(open(B + 'library_words.json')),
                   json.load(open(B + 'library_facts.json')))
q = '꼬마회원의 대출기간은 얼마인가?'
print(pack.tell(system, q, pack.ask(system, q)))
```

Other entry points:

```bash
PYTHONPATH=. python3 -m experiments.tax_graph_trial_20261119.helds_fix_20261119.run
PYTHONPATH=. python3 -m experiments.graph_weighted_acquisition.variants --text data/위키/정의문.jsonl --field 정의 --output VARIANTS.json
PYTHONPATH=. python3 experiments/graph_weighted_acquisition/packs/make_language.py
```

## 6. Measured state

All with 0 wrong answers. "Held" means no answer was given.

| Check | Result | Independence |
|---|---|---|
| Helper language, 117 fresh passage/question pairs, 560-example model | 117 correct, all verified | Names unseen; sentence shapes reuse the development set |
| Same, 56-example model | 117 correct | Same |
| Leave-one-out on 56 lessons | 55 read exactly, 1 held | Clean |
| Held-out set, run once on 2026-11-18 with an earlier version | 48 of 56 correct, 8 held | Clean; **do not rerun or tune on it** |
| Written answer sentences | 117 of 117 identical to the authored passage sentence | Clean check of the writer |
| Tax trial, 24 questions, lessons written for it | 18 correct, 4 held, 2 held as expected | Lessons were written after seeing held questions |
| Tax through three packs, no tax word in any lesson | 16 correct, 6 held, 2 held as expected | Field words unseen by lessons |
| Made-up library through three packs | 12 correct, 3 held as expected | Written by the same session that built the code |
| Each field asked the other field's questions | all held (24 and 14) | Clean |
| Speed | 32 sentences read in 0.07 s; about 85 MB memory; language pack 30 KB | - |

The helper-language sets live under `.marco/private-evaluation-preservation/graph-example-acquisition-20261117/`
(git-ignored). The scaled 560-lesson set and the 234-utterance fresh set were generated in a
temporary folder that no longer exists; regenerate them with `augment.py`, seed 20261118,
9 copies for train (`--half train`) and 5 for the development file (`--half test --drop-original`).

## 7. What it cannot do

- **Language coverage is tiny.** Two sentence families: "per X, A helped/did not help B" and
  "X의 P은/는 V". Any other shape needs lessons.
- **Paraphrase.** Free wordings are held unless a lesson teaches that wording.
- **Reasoning.** Look-up, comparison and yes/no checks only. No arithmetic, no chains.
- **Writing.** Only taught shapes, one head per sentence, no pronouns, no yes/no wording.
- **Unknown words** are detected only when they change what the sentence does (a question that
  would ask nothing). An unknown ordinary word in a name position still reads as a name.
- **Repeated person across two events** stays as two nodes: lessons never show a shared person,
  so the learned merge gate stays closed. Answers are unaffected.
- **Raw-text variants:** only 은/는 and 을/를 were learned. 이/가 and 과/와 fail the thresholds.
- **Verification:** the older executor runs out of search budget above roughly two sentences,
  so most real answers are "not independently verified".
- **Least Python, maximum graph is not met.** Words, counts, facts, thresholds, the scoring
  recipe and conventions are data. The procedures (cutting, search, graph building, matching,
  writing, report wording) are Python, and `write.py` still names count tables in code.

## 8. Decisions already made, so they are not reopened by accident

- **Hard name-length rule removed.** Length is a graded cost, never a block.
- **Connectors are counted with their spaces**, and an occurrence inside already-read structure
  is not "left over".
- **Thresholds for raw-text pairs stay hand-set.** Choosing pairs by held-out prediction of raw
  text was tried and failed: merging never predicts the next word better, for real or false pairs.
- **Same-context variants are never paired** (polite/plain, past/present): they can differ in meaning.
- **A passage is never answered from part of it;** only a question may be read partially.
- **An executor refusal is final;** only a confirmed budget stop is "unavailable".
- **Nothing is stored on the reader's own guess.** A word enters memory only by `teach` or `mark_name`.
- **Lessons win over memory and over field words.**

## 9. Suggested next steps, in the owner's priority order

1. **More Python into pack data.** Same kind of move as the recipe: the writer's rules, then the
   report wording. The large step is turning the procedures into graph programs run by a small
   engine, as the main branch's Graph VM does.
2. **An independent test.** New facts and new wordings from an author who has not seen the
   lessons, scored once per change. Nothing since the first tax run has been independent.
3. **Lessons with a shared person in two events,** from an independent author, to open the merge gate.
4. **Self-learning, next stages:** infer the kind of an unknown word from its slot before asking;
   promote confirmed words into a pack; re-check past answers after a `forget`.
5. **Operations beyond look-up:** arithmetic, counting, comparison, each reported as a step.
6. **이/가 from raw text:** count an ending only where it behaves as a connector.

## 10. Local state that is not in git

- `HANDOFF.md`: the running log, with every measurement and its conditions.
- `.marco/`: private evaluation data and audit records. Do not read private gold or cases
  beyond what a task needs, and never copy them into the repository.
- Unstaged or untracked, left alone on purpose:
  `tests/test_graph_language_repair_api.py` and `tests/test_graph_language_repair_questions_select_respond.py`
  (modified by other work); `experiments/graph_language_repair/AUDITOR.md` and `MANIFEST.md`
  (they name development tools, so they were never committed); about 80 other untracked files
  under `tests/` and the tax trial outputs.
- The local branch `codex/graph-language-repair-20261111` still has an older, unpushed commit
  whose files name development tools. Do not push it as it is.
- The audit manifests under `.marco/` record hashes of `experiments/graph_language_repair/`
  from before 22 of its files were reworded on 2026-11-22. Those hashes no longer match the
  branch; behaviour was not changed, only names in comments, notes and two file names.
