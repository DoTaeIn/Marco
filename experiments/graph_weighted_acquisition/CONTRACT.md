# Count-weighted reading selection — contract

Branch `weight_test` only. Owner decision 2026-11-18: count-based weights are allowed in
graph data when they are built offline. This amends, for this branch and this package only,
the runtime law in `experiments/graph_language_repair/CONTRACT.md` that bans statistical
models. That file and the frozen 91-file package are not edited.

## What is allowed

1. Integer counts of pieces observed in teacher examples, stored as JSON with the ids of the
   examples each count came from.
2. A declared policy in the same file: smoothing `alpha` as an integer ratio, a `margin_ratio`,
   and `require_support`.
3. At run time, arithmetic on those integers: a smoothed log ratio per piece, summed per reading.

## What stays banned

Neural inference, token prediction, embeddings, pretrained models, model or API calls, and any
weight that is fitted by optimisation instead of counted. No count is updated at run time.

## What weights may do

- Order the readings the unchanged `graph_example_acquisition.v2` parser already produced.
- Turn status `ambiguous` into `complete` only when the top reading leads the second by at
  least `margin_ratio` and, with `require_support`, every one of its terms has a nonzero count.

## What weights may not do

- Create a reading, a rule or an answer.
- Change an `unresolved`, `hold` or already `complete` parse.
- Bypass the admission gate, native execution or evidence checks. Those run after selection,
  unchanged.

## Pieces counted

Language-independent, read from authored spans and graphs only:

| Table | Cue | Counted against |
| --- | --- | --- |
| `left`, `right` | literal text before / after an anchored node | that node's label |
| `surface` | text of a closed (non-copy) anchor | that node's label |
| `cues` | a cue string | times used as structure vs. found inside a free value |

A node label is its type, incoming role predicates, literal attributes and whether it is projected.

## Measurement rules

- Counts built from a set must not be scored on that set as generalisation. Use `loo` or a
  separate evaluation file.
- Reports carry ids, states and counts only.
- `ambiguous_gold_present -> wrong` is reported as `gold_lost` and is the number to keep at 0.
- The synthetic tests show the mechanism. They are not evidence about Korean or the private sets.

## Piece reader (`reader.py`, `answer.py`)

Same law: integer counts built offline, no fitted weights, no run-time learning.

- A reading may be chosen only if every count it relies on is nonzero, it leads the next such
  reading by `margin_ratio`, and no reading with an unseen piece leads it by that ratio.
- A fixed word that was itself seen in a role is judged by its own counts; a free value by the
  pieces before and after it.
- Whether a repeated name is one node is decided by `identity` counts only.
- Answers come from `match.py`: plain backtracking that assigns question nodes to passage
  nodes so every condition holds. No scoring, no learning, no generated text. Owner decision
  2026-11-18, because the native executor stops at three or more sentences.
- `graph_example_acquisition.native.run_pair` still runs, unchanged, as a second opinion, with
  four outcomes. `agrees`: the answer is given and marked verified. `disagrees` (different
  answers or no match) and `refuses` (it stopped for a safety reason of its own): no answer
  is given and the withheld result is shown. `unavailable` (its search budget ran out): the
  answer is given and marked not independently verified.
- The executor's own stop is classified first and is final. `unavailable` is possible only
  when the executor itself stopped inside a search and that stop is confirmed as a budget
  limit. A safety refusal stays `refuses` whatever any later search returns.
- Every `origins` entry in a model is a training example id. A stem or ending also lists the
  word forms it was taken from under `forms`; its count is the number of word-form
  observations.
- The reading chosen is always among the readings kept for the report.
- Ties are never broken silently. Every meaning seen for a fixed word stays a candidate, so
  equal counts end as two readings and a hold. Two equally common ways to ground a fact, or
  equal scores, also hold. A reading with no fully seen rival is reported as the only one,
  not as a lead, and any higher-scoring reading with an unseen piece is stated.
- Every separate place in the passage that yields an answer is kept as its own ground, and
  each ground lists the text for every condition, for names given in the question and for the
  answer's own name. A condition with no passage text behind it blocks the answer.
- No answer when a passage event fits the stated conditions but lacks the asked-for role.
- A free value is charged for its length: a value continues or stops at each character, with
  stop rates counted from training lengths and, past the longest length seen, the overall
  stop rate per character. An unseen length lowers the score more the longer it is, but it is
  not an unseen piece and does not block a reading (changed 2026-11-19; the earlier hard rule
  held every name longer than the training names).
- Every decision keeps its count, its total and up to five origin example ids, so each answer
  can be traced to training examples.

## Sentences (2026-11-19)

- A text is cut where a closing piece seen in training is followed by blank space. Blank space
  as the separator is the one structural assumption; the closing pieces are learned.
- Each sentence is read on its own and must pass the same rule as any reading. A stretch that
  is not a sentence is retried together with the next one or two.
- One unread sentence holds the whole text. A passage is never answered from part of it.
- A text of at most `max_whole_chars` that fails this way is tried once as a whole.

## Partial reading, loose names, yes/no checks (2026-11-19)

Three ways an answer can rest on less than a full reading. Each is reported with the answer,
none is counted as verified, and none is used when a full reading or an exact match exists.

- **Ignored words.** Unknown text standing between a connector and a fixed word may be passed
  over (`max_skip_chars`). No count stands behind it. Such a reading is chosen only when no
  reading explains the whole text. A passage read this way is held; only a question may be.
- **Loose names.** A name in the question is compared with passage names exactly first; then
  with blank space removed; then as "ends with the passage name after a space", where the
  words in front are reported as ignored. The older executor cannot check a loose match, so
  its state is `not comparable`.
- **Yes/no checks.** An edge with predicate `claim` marks a check; the value mention right
  before the claim word is the value checked. It is answered by looking that value up and
  comparing: the answer carries the passage's value and whether the claim holds.

A connector is counted with its spaces ("가 " is a piece, the letter inside a name is not).
An occurrence of a known piece that lies wholly inside text already read as structure is
explained by it; only one reaching into a free value counts as left unused.

## Connector variants from raw text (2026-11-19)

Owner approved learning from raw, unlabelled text. Still counts only: no neural network,
no embedding, no prediction of text.

- `variants.py` reads raw text split on blank space and counts, for the commonest word
  endings, which character comes before and which word comes after.
- Two endings are one connector in two forms when all of this holds: same length, letters
  only; each follows at least `min_distinct_before` different characters; they almost never
  follow the same character (`max_left_share`); the words after them coincide for at least
  `min_right_share`; each is the other's best match by `lead_ratio`.
- Endings that follow the same characters are never paired, however alike their contexts:
  those are different words (tense, polarity, register), and pairing them could change meaning.
- The reader uses a pair only to read an untaught connector whose other form the lessons
  did teach, with the taught form's counts. Every such use is listed in the answer with the
  raw-text evidence. Nothing is added when the lessons already show both forms.
- `min_distinct_before` (250) was set after looking at the raw-text statistics, where real
  connectors follow 300 to 1000 different characters and other endings fewer than 210. It
  was not set on any question set.

Tried and rejected (2026-11-19): choosing pairs by held-out prediction of raw text, so that no
threshold is set by hand. Merging two endings never predicted the following word better than
keeping them apart, for real pairs or false ones (은/는 -0.17, 을/를 -0.10, against 년/력 -0.03 and
고/져 +0.005 per word), and counting an ending only where the rest of the word is itself a word
did not change that. The reason is that the two forms attach to different words, and
different words are followed by different words. The thresholds therefore stay. What was
added instead is `variants.check_against_lessons`, which hides one form in lessons that show
both and reports whether it is read correctly through the other.

## Unknown words (2026-11-19)

- The lessons are counted for what each closing piece, and each head word, makes of a
  sentence: it asks for something, checks a claim, or states.
- A reading in which a sentence closed like a question asks for nothing (or one closed like a
  statement asks for something) uses something never seen, and is not chosen.
- When that is a reading's only fault, the free values in it are reported as possible unknown
  words. With a passage, values the passage also uses as names are set aside, and the rest
  are named as the unknown word.
- Nothing is guessed about what the word means and nothing is stored. This is detection
  only; learning the word is a later step.

## Provisional memory (2026-11-19)

Words told in conversation live in a separate memory file (`learn.py`), never in the lessons
or the model. Owner approved this as the next step toward self-learning.

- **How a word gets in.** Only through `teach` (someone confirmed a proposed meaning) or
  `mark_name` (someone said it is a name). Nothing is stored on the reader's own guess.
- **What can be proposed.** A meaning the lessons already use for a fixed word, and only if
  the question then reads with confidence. The reader asks, e.g. `Is "누구" a word that asks
  for a person, like "누가"? Or is it a name?`
- **Lessons win.** A word the lessons already teach cannot be re-taught here.
- **Status.** `provisional` until `promote_after` (3) different people have confirmed the
  same meaning, then `confirmed`. A second, different meaning makes the word `disputed`, and
  a disputed word is not used.
- **Disclosure.** Every answer that used a stored word names it, its status and who confirmed
  it, and is not counted as verified.
- **Undo.** `forget` removes the word and returns the questions it was used for.
- **Broader counts.** A connector never seen after a fixed word may be read with the counts
  for that word's type (a fixed word for a person takes the connectors persons take). It is
  used only when the exact count is zero and is listed in the answer.

## Writing sentences (2026-11-19)

`write.py` turns a meaning into a sentence with the reader's own counts. Owner chose to keep
the system pure: no token model writes or rewords anything.

- **What is chosen, and from what.** The order of a head and its arguments (`order`), the head
  word for the meaning in a stating or asking sentence (`head`, `head_in`), the word that asks
  (`closed`, `role_surface`), and each connector: it must follow that kind of word, mark the
  role, fit what comes next, and have been seen after words ending in that sound
  (`gap_after_part`, backing off to the kind of sound, `gap_after_part_class`).
- **Read-back rule.** A candidate sentence is given only if `reader.read` reads it with
  confidence, ignoring nothing, as exactly the meaning asked for. The system never says
  something it could not itself understand.
- **No improvising.** A shape or a meaning the lessons never showed gives "cannot say".
- **Answers.** Each answer is also given as a full statement: the question's meaning with the
  answer in place, using the passage's name where the question's was matched loosely.
- The ending sound of a word is read from Unicode decomposition of its last character. That
  is knowledge of the writing system, used in the same way as blank space.

## Three packs (2026-11-19)

Owner's design: the input-understanding graph and the knowledge graph are one system, split
into three packs, so a field is changed by changing graph data. Owner's rule: least Python,
maximum graph.

- **Language pack.** Counts from lessons that use made-up property words and belong to no
  field, plus raw-text connector variants. Shared by every field.
- **Word pack.** A field's property words, other words for them, other names for subjects.
- **Fact pack.** The field's facts, each with source, date and scope.
- **Loading** gives each field word the pooled counts of the lesson words in the same slot,
  writes every fact out as a sentence with `write.say`, reads those sentences back, and keeps
  which sentence came from which fact. No lesson is added or changed.
- **A field word may not replace a word of the language pack.**
- **A fact whose property is not in the word pack, or that cannot be written and read back,
  is listed as unusable and left out.**
- **Answers name the facts and sources they rest on.**

Known gap against "least Python, maximum graph": the packs hold all words, counts, facts and
thresholds, but the procedures (reading, matching, writing, how counts are combined) are
about 2,300 lines of Python, with 22 count-table names and conventions such as `claim`,
`value` and asks/states fixed in code. Moving those into graph data is not done.

## Recipe and conventions as pack data (2026-11-19)

First step toward "least Python, maximum graph".

- `data/reading_recipe.json` states which counts decide what (connector, meaning of a word,
  role of an argument, roles of a head, what a sentence does, the broader count to fall back
  to) and the conventions the engine follows (what marks a yes/no check, how a sentence's
  kind is told, which ways of comparing names are in use, which executor stops are budget
  stops). It is copied into every language pack when the pack is built.
- The engine reads the recipe and conventions from the pack. Editing them in the pack changes
  how the system reads, with no code change. A pack built before this uses the shipped file.
- The reader no longer names a count table when it scores a reading, except for two generic
  helpers (used/unused pieces and name length).
- Output order no longer depends on the Python hash seed; readings are identical across seeds.

Still in Python, not yet data: the procedures themselves (cutting text into pieces, the
search, graph building, matching, writing, the report wording), the writer's own use of the
count tables, and the `value` marker, which the teacher schema fixes.
