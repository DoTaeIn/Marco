# Count-weighted reading selection

Adds integer count weights on top of the example-acquisition learner. The learner and its
parser (`experiments/graph_example_acquisition`) are imported unchanged. See
[CONTRACT.md](CONTRACT.md) for what the weights may and may not do.

## Why

The acquisition result had 37 of 56 training sentences and 29 of 48 development sentences
ambiguous, with nothing to choose between readings but the byte length of literal text.
Counts over shared pieces give a graded choice and keep the fail-closed behaviour.

## Commands

Input files use the teacher schema of `experiments/graph_example_acquisition/SCHEMA.md`.

Build the weight file:

```sh
PYTHONPATH=. python3 -m experiments.graph_weighted_acquisition.driver build --train TRAIN.json --output WEIGHTS.json
```

Leave-one-out over the training set (grammar and counts never see the scored example):

```sh
PYTHONPATH=. python3 -m experiments.graph_weighted_acquisition.driver loo --train TRAIN.json --output LOO.json
```

Score a separate set:

```sh
PYTHONPATH=. python3 -m experiments.graph_weighted_acquisition.driver evaluate --train TRAIN.json --eval DEV.json --output REPORT.json
```

Options: `--alpha-num`, `--alpha-den`, `--margin-ratio`, `--allow-unsupported`.

## Reading a report

`summary.transitions` counts each example by state before and after ranking. States are
`correct`, `wrong`, `ambiguous_gold_present`, `ambiguous_gold_absent`, `unresolved`, `hold`.

- `resolved_correct`: ambiguous with the authored graph present, now selected.
- `gold_lost`: ambiguous with the authored graph present, now a wrong selection. Keep at 0.

Weights do not touch `unresolved`, so they cannot raise coverage. They only convert ambiguity.

## Blind name scaling

`augment.py` copies each passage/question pair with every named value swapped for a random
name of the same final-consonant class. Names come from `data/korean_given_names.txt`, split
by seed into disjoint train and test halves. Nothing in the draw looks at parser output.

```sh
PYTHONPATH=. python3 -m experiments.graph_weighted_acquisition.augment --input TRAIN.json --names experiments/graph_weighted_acquisition/data/korean_given_names.txt --output TRAIN-X10.json --copies 9 --seed 20261118 --half train
```

Use `--half test --drop-original` on a development file to make a fresh test of the same
sentence shapes with unseen names. This scales values only, never sentence structure.

## Piece reader and explained answers

`reader.py` replaces sentence templates. A text is cut into pieces seen in training
(connecting strings, fixed words, stem + ending) plus free values; each argument then picks a
head and a role by counts. `answer.py` reads a passage and a question, matches the question
graph against the passage graph, and prints a full report: the answer, the passage text that grounds
it, every decision with its training count and example ids, and the rejected rival readings.

```sh
PYTHONPATH=. python3 -m experiments.graph_weighted_acquisition.answer --train TRAIN.json --passage "..." --question "..."
```

No answer is given unless both texts are read with every piece seen in training and a clear
lead, and the executor returns grounded evidence. The model is a JSON file of integer counts
(about 9 KB for the teacher set). Standard library only: no neural network, embedding or token
prediction.

## Status (2026-11-18)

Exact authored-graph match, weights from train only, default policy.

| Run | Correct before | Correct after | Wrong before | Wrong after | Right graph lost |
| --- | ---: | ---: | ---: | ---: | ---: |
| Leave-one-out, 56 train | 4 | 27 | 1 | 1 | 0 |
| 56 train -> 48 dev | 6 | 19 | 6 | 7 | 0 |
| 56 train -> 234 fresh | 30 | 108 | 30 | 35 | 0 |
| 560 train -> 234 fresh | 0 | 130 | 17 | 22 | 0 |

Piece reader, same 234 fresh utterances (117 passage/question pairs):

| Train | Answers correct | Wrong | Held | Graphs exactly as authored |
| --- | ---: | ---: | ---: | ---: |
| 56 | 97 | 0 | 20 | 137 of 234 |
| 560 | 117 | 0 | 0 | 157 of 234 |

Leave-one-out on the 56 training utterances: 50 read exactly, 0 wrong, 6 held (template
parser with weights: 27). Build takes under 0.1 s and the 234 reads plus 117 answers about 4 s.

The 77 graphs that differ are the two-event passages: the reader keeps a person named twice as
two nodes because training never shows a shared person, so the learned merge gate stays
closed. Answers are unaffected. The language covered is very small: one action, positive and
negative, an optional reported source, who and whom questions.

Dev was inspected while the weight rule was fixed, and the fresh set reuses dev sentence shapes
with unseen names, so it tests new names and unseen combinations of known shapes, not new
constructions. Tests: 16 pass with a plain runner.

After the held-out run, benchmarking long passages exposed two reader faults, both fixed: an
8-node limit borrowed from the old graph comparison, and a piece inside a larger used piece
being counted as left over. With the fix: fresh 234 is 117/117 (560 train) and 112/117 with 5
held (56 train); leave-one-out on 56 train is 55 exact, 0 wrong, 1 held. Held-out was not rerun.

Cost on an Apple M4 Pro, one core, pure Python: model 9 KB, build 0.03 s for 560 examples,
about 85 MB peak memory (mostly the Python runtime and project imports). Reading takes 0.002 s
for one sentence, 0.01 s for two, 0.11 s for eight, 0.68 s for 32 (704 characters). Work per
position is capped by `beam`, and role assignment by `max_assignments`; past a cap the reader
holds instead of running longer.

Answering now uses `match.py`, a direct graph matcher, with the native executor as a second
opinion that must agree when it finishes (it stops with `proof_or_search_limit` at three or
more sentences). A 32-sentence passage is read and answered in 0.72 s. Free values are also
charged by length, which keeps long passages from being read as one swallowed name. Current
numbers: fresh 234 is 117/117 (560 train) and 109/117 with 8 held (56 train, where three-syllable
names are an unseen length); leave-one-out on 56 train is 55 exact, 0 wrong, 1 held. The two
methods never disagreed. Held-out was not rerun.

Review fixes (ties, verification holds, answer evidence): see the last three points of the
piece-reader section in CONTRACT.md. Numbers are unchanged: fresh 117/117 with 560 train, all
117 verified by the older executor; 109 + 8 held with 56 train; tests 23 pass. Known gap: the
tiling search keeps a fixed number of candidates per position and often drops low-ranked ones
that score the same as the last one kept (43 of 117 fresh pairs). This is reported in the
answer report but does not block an answer.

Second review (2026-11-19), three faults fixed: an executor safety refusal could be turned
into `unavailable` by a later budget stop; the report crashed when the chosen reading ranked
below the five kept; stem and ending origins were word forms, not example ids. Numbers
unchanged; tests 26 pass. How often the first fault could occur on real pairs is unmeasured:
on the fresh set the executor agreed on every answered pair.

Length rule changed (2026-11-19): name length is now a graded cost and no longer blocks a
reading. Fresh 234: 117/117 (560 train, all verified), 112/117 with 5 held (56 train);
leave-one-out 55/56; tests 26 pass; 0 wrong throughout. On the tax trial inputs
(`experiments/tax_graph_trial_20261119`, rechecked outside its frozen run) the graph arm goes
from 0 to 10 of 24 answered, all 10 correct and none wrong; the other 14 are held because the
lessons never contain the particle 는 (4) or those question wordings (10). Open defect: a long
text the reader cannot split still takes about 5 s before it holds on its search bound.

Sentence-by-sentence reading (2026-11-19) closes that defect. A passage is cut at learned
closing pieces followed by blank space and each sentence is read alone, so no lesson has to
show sentences joined. Reading time is now linear: 32 sentences in 0.07 s (was 0.66 s), 64 in
well under a second. Tax trial inputs, rechecked outside the frozen runs: the 14-sentence
context reads in 0.006 s (was 5 s then held), and the natural-language arm goes from 0 to 10 of
24 answered, all correct, none wrong; the same 14 questions stay held as in the graph arm.
Other numbers unchanged: fresh 117/117 verified (560 train), 112 + 5 held (56 train),
leave-one-out 55/56, tests 28 pass.

Held-out, run once on 2026-11-18, answers scored against expected bindings, no tuning after:

| Cohort | Pairs | 560 train | 56 train | Wrong |
| --- | ---: | ---: | ---: | ---: |
| New values, familiar forms | 20 | 20 | 16 | 0 |
| Matched controls | 28 | 28 | 24 | 0 |
| Source-question extension | 8 | 0 | 0 | 0 |

Everything not answered was held. The extension asks who the source is; that question word
never occurs in training and is read as a name, so the question asks for nothing.

Held-question work (2026-11-19): flagged partial reading (ignored words), loose name matching,
yes/no checks, and connectors counted with their spaces; see the last contract section. Tax
trial, same 24 questions, both arms identical (`experiments/tax_graph_trial_20261119/helds_fix_20261119`):
direct 14/14, paraphrase 3 of 6 (two of them partial readings), the yes/no boundary question
correct, two boundary questions held as expected, 4 still held (a calculation, a subject
described in other words, a question with no subject, and one where the subject clause contains
another rate term). 0 wrong. The added wordings were written after seeing the held questions,
so this shows the mechanisms work, not that they generalise. Other numbers: fresh 117/117 with
both the 560- and the 56-example model (the 56 model was 112 + 5 held; names containing a
connector's letter no longer hold), all verified; leave-one-out 55/56; tests 32 pass;
32 sentences read in 0.07 s. Held-out not rerun.

Raw-text connector variants (2026-11-19): `variants.py` finds 은/는 and 을/를, and nothing
else, in 534,198 Wikipedia definition sentences (`data/위키/정의문.jsonl`, 20 s); the result is
`data/connector_variants_ko.json`. 이/가 and 과/와 fail the thresholds and are not learned.
Pass it to `reader.build(lessons, variants=...)`. Two checks, 0 wrong in both:
the tax trial's original lessons, which teach only 은, go from 0 to 14 of 14 direct questions;
the teacher language with every 를 example removed from training (560 to 230 examples) goes
from 20 to 80 of 117 fresh pairs, the other 37 held because the fixed word 누구를 was removed
too. Without `variants` nothing changes: fresh 117/117 for both models, leave-one-out 55/56.
Tests: 34 pass.

```sh
PYTHONPATH=. python3 -m experiments.graph_weighted_acquisition.variants --text data/위키/정의문.jsonl --field 정의 --output VARIANTS.json
```

Negative result (2026-11-19): replacing the hand-set thresholds with a held-out prediction test
on raw text does not work; see the end of CONTRACT.md. `variants.check_against_lessons` was
added. On the 560 teacher lessons it reads 270 of 330 hidden 를 lessons and 260 of 280 hidden 을
lessons exactly as authored; 60 differ, all of them 누구를 questions read as a person called
누구 (the question word was hidden along with 를), and all 60 are then held at the answer step.
Tests: 35 pass.

Unknown-word detection (2026-11-19): a question that would ask for nothing if one of its words
were a name is no longer read that way; the word is reported as unknown ("누구에 따르면, …
도왔나?" now names 누구). The 60 lessons the pair check read differently are now held (270
same, 0 different, 60 held). Everything else is unchanged: fresh 117/117 for both models,
leave-one-out 55/56, tax questions as before. Tests: 37 pass. Held-out was not rerun, so the
effect on its extension cohort is expected but not measured.

Provisional memory (2026-11-19, `learn.py`): for an unknown word the reader proposes a meaning in
terms of words it knows and the question to ask; a confirmed answer is stored outside the
lessons and the model, flagged in every answer that uses it, promoted after three different
confirmations, disputed on disagreement, and removable with the list of questions it was used
for. Worked example on the 560-example model: "누구에 따르면, 하늘이 서연을 도왔나?" is held and
asks whether 누구 asks for a person like 누가; once confirmed it answers 가영, and
"누구가 서연을 도왔나?" answers 지호 without further teaching. Lessons and model are byte-identical
afterwards. Regressions unchanged (fresh 117/117 both models, leave-one-out 55/56, tax as
before). Tests: 39 pass.

```python
from experiments.graph_weighted_acquisition import answer, learn, reader
memory = learn.new_memory()
result = answer.answer(passage, question, model, memory)      # held, with result['proposals']
learn.teach(memory, model, '누구', result['proposals'][0]['meaning'], by='owner', at='2026-11-19')
answer.answer(passage, question, model, memory)                # answered, flagged as told
learn.forget(memory, '누구')                                    # returns the uses
```

Writing sentences (2026-11-19, `write.py`): a meaning is written with the reader's counts used
backwards and kept only if the reader reads it back as that meaning. Answers now carry a full
sentence. Check with an independent yardstick: for all 117 fresh pairs the written answer
sentence is character-for-character a sentence of the authored passage (names never seen in
training); the same holds for the 18 answered tax questions. `say` also writes questions
("누가 준서를 도왔나?") and refuses shapes or meanings the lessons never showed. Regressions
unchanged; tests 41 pass. Limits: one head per sentence, only taught shapes, no pronouns, no
joining of sentences, and no yes/no wording (a checked claim is answered by stating the fact).

```python
from experiments.graph_weighted_acquisition import write
write.say(model, 'event', [['action', 'help'], ['polarity', 'positive']], [('actor', '하늘'), ('object', '준서')])
# {'status': 'said', 'text': '하늘이 준서를 도왔다.', 'steps': [...]}
```

Three packs (2026-11-19, `pack.py`, data in `packs/`): one language pack (26 KB, built from 112
field-free lessons and the raw-text variants) serves two fields whose words appear in no
lesson. Tax (1 KB words, 5 KB facts): direct 14/14, the yes/no question and one paraphrase
correct, 6 held, 2 held as expected. A made-up library (1 KB words, 2 KB facts): 12 of 12
answerable questions correct, including other words for a property, other names for a subject
and yes/no checks, and 3 held as expected. Each field holds on all of the other field's
questions (24 and 14). 0 wrong. The system writes its own fact sentences ("어린이회원의 대출권수는
10권입니다.") and each answer lists its fact and source; see `packs/SAMPLE-LIBRARY-REPORT.md`.
Field-specific phrasings such as "언제까지 신청해야 하나요?" are not covered by packs. Tests: 42 pass.

```python
from experiments.graph_weighted_acquisition import pack
system = pack.load(language, words, facts)       # three JSON files
result = pack.ask(system, '꼬마회원의 대출기간은 얼마인가?')
print(pack.tell(system, '꼬마회원의 대출기간은 얼마인가?', result))
```

Recipe as data (2026-11-19): which counts decide what, and the engine's conventions, now live in
the language pack (3 KB of its 30 KB), copied from `data/reading_recipe.json` at build. Tests
edit only the pack and show the behaviour change: dropping a rule from the recipe, switching
off a way of comparing names, removing the sentence rules, renaming the yes/no marker. Check
that nothing else moved: all answers identical before and after (same hash at 41 hash seeds);
the tax pack's full readings, with every count and score, identical at 14 of 41 seeds. The
other two reading sets could not be compared exactly, because the old output order depended
on the hash seed; that is fixed and output is now identical across seeds. Tests: 44 pass.
The procedures are still about 2,300 lines of Python.
