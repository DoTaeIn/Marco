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

## A node's type agrees with its role (2026-11-23)

- The lessons are counted for which type of node filled each role (`fills`: role, then type).
- The recipe's argument rules gain one line: a role may be filled only by a type seen filling
  it. A reading that breaks this relies on a zero count and is not chosen, like any other.
- Why: a word's type was chosen from the word or the connector alone. A question word taught
  for two roles (asking for a value, asking for a subject) then gave two readings with the same
  edges and different types, and the reader held on sentences it had read before those lessons.
- The rule is skipped for a pack without the `fills` table, and a pack carries its own recipe,
  so packs built earlier read exactly as before.
- Cost: one counted row in `build`, one value in the argument context, one recipe line.

## Names the field pack knows (2026-11-23)

- A free value was any text up to the next connector, so "A와 B" was read as one name and
  nothing said so. The reader already refuses a reading that leaves a known piece unused in a
  way the lessons never did; the field's names are now such pieces.
- Which names: those of the word pack and the subjects of the fact pack, as the pack's
  conventions list under `known_names`. Removing that entry switches the rule off.
- A free value that is exactly a known name uses it. A known name found inside any other free
  value is a piece left unused, with a zero count, so that reading is not chosen. A value that
  is itself a known name, or a value the fact pack states, explains what lies inside it.
- A name that is already a word of the language pack is not registered.
- Packs built earlier carry conventions without `known_names` and read exactly as before.
- Known limits: a short name blocks any other value that contains it; a longer name the pack
  does not know is held when it contains one the pack does; a name the pack does not know at
  all is still read as a name; names told in conversation (`learn.mark_name`) are not included.

## No answer from a question read only in part (2026-11-23)

This changes the rule of 2026-11-19 under "Partial reading, loose names, yes/no checks".
Owner decision after a wrong answer in a development probe: "중앙도서관의 주말 운영시간은
언제인가요?" was answered with the plain opening hours, with "주말" ignored and flagged.

- The pack's conventions carry `partial_answers`. With `withhold`, which the shipped recipe now
  states, no answer is given when words of the question were ignored, or when a name was
  matched by ignoring the words in front of it. The words passed over may be the ones that
  change the answer.
- The reading and the match are still made and reported: the result is a hold whose reason
  names what was passed over, and the candidate is kept under `withheld`.
- A name that differs only in spacing is still matched and flagged, as before.
- `give` restores the earlier behaviour (answer given, flagged, never verified). Packs built
  earlier have no `partial_answers` entry and behave as before.
- Cost, measured on the public tax questions with a rebuilt pack: the two answers that had been
  right only with a flag (Q20, Q24) are now held. No answer that was right without a flag changed.

## Parts one by one, heads under heads, and what may hold a reading back (2026-11-23)

Owner's direction: before anything is taught by asking back, one lesson has to be worth more
than one sentence. Measured by `probes/transfer.py`: features taught apart, then every
combination of them on unseen words. Before: 5 of 26 combined sentences read. After: 26 of 26.
The grid was designed by the implementer and worked on while these rules were made; it shows
that the mechanism works, not how far it generalises.

- **Parts one by one.** The recipe's `head` rule read the `frame` table: the whole set of a
  head's roles had to have been seen together. It now reads `part`: for each role a head ever
  had, how often the head had it (`+role`) and how often it stood without it (`-role`). A role
  never seen with the head, or a role never missing that is missing, is a zero count.
- **A head under a head.** With `nesting` in the recipe, a head may fill a role of another
  head. The head with everything under it is its phrase. A phrase is one unbroken stretch, so
  phrases never cross. The connectors at the two ends of the phrase decide its role, by the
  same tables as for any argument; `stands` counts, per closing connector, whether a head stood
  alone or under another. Lessons could always state such graphs; only reading was closed.
  "X의 P의 Q": P under Q as its subject. "…V이면 …W이다": the first relation under the second,
  role `if`.
- **Negation, comparison:** written as a fixed word under the relation, the shape a claim check
  already has (`denies` → "아니", `compare` → "이상"). No new role names per modality.
- **What may hold a reading back.** Two conventions, both `true` in effect for older packs:
  - `partial_reading_blocks_whole: false` — a reading that ignores words never holds back one
    that explains every word with seen pieces.
  - `contradicted_reading_blocks: false` — a higher-scoring reading holds the text back only
    if what it relies on was never observed either way (0 of 0). One that goes against the
    lessons (0 of N: a known piece buried in a name, a clause left alone after a connector that
    always joined it) does not. Reason: a reading with fewer pieces has less to pay for and
    outscored every longer, fully seen reading; conditionals and modifiers were held for it.
  **These two loosen a fail-closed rule of 2026-11-18 and need the owner's review.** On the
  development probes no reading came out different from the meant one (0 of about 190 lines),
  but those probes were written by the implementer.
- Not done: a nested graph is read but not yet answered (the matcher compares node types, and
  the bridge to the structured questions of `know.py` is not built); the writer cannot write
  nested sentences; evidence descriptions that differ only in the order of their spans count
  as different and can tie.
- Packs built earlier carry their own recipe and conventions and read exactly as before.

## Blind test of 2026-11-23 (`probes/blind_20261123/`)

Items by two authors who saw neither lessons nor code; runner and inputs fixed before the
items existed; one run; nothing changed afterwards. Not the owner's independent examiner.

- Reading, 60 sentences combining the claimed features in an invented domain: 30 read exactly
  as meant, 22 held, 4 partial, **4 read differently without any flag**.
- The 4 are one pattern: a chain ("X의 P의 Q") with a time or a condition in front; the time or
  condition was attached to the inner relation instead of the outer one.
- With the two conventions of the previous section set back to `true`, the same run gives
  12 read as meant, 48 held or partial, 0 read differently. So loosening them bought 18
  sentences and cost 4 silent misreadings. The statement "0 read differently" in the previous
  section holds only for the implementer's own probes.
- Answering, an invented field with 50 questions: 0 wrong answers; 8 of 8 questions without
  an answer were held; 15 of 42 answerable questions were answered right (direct 9 of 12,
  checks 2 of 6, other names 4 of 6, natural wording 0 of 18).

## A part whose place the sentence leaves open is asked about (2026-11-23)

Made after the blind test above, from its four misread sentences. Those items are therefore
exposed; what this rule is worth has to be measured on new ones.

- The reader could not know those readings were wrong: every count was nonzero, and a
  higher-scoring rival of another meaning was just as common among the sentences read right
  (18 of 30) as among the wrong ones (4 of 4). More search would pick the same reading.
- The rule (`attachment_check` in the pack's conventions): a chosen reading is not accepted
  when one of its parts (an argument, or a head with everything under it) could by form
  belong to another head as well. That is the case when the other head has no part in that
  role yet, heads like it were seen with such a part (`part`), the role was seen written on
  that side of its head (`side`, a new counted table), and moving the part leaves every phrase
  one unbroken stretch.
- The result is a hold with status `ambiguous`, the candidate reading kept, and under
  `attachment` what to ask back: the piece, its role, and the head words between which the
  choice lies. Answering that question back into the reading is not built yet.
- On the exposed blind items: the 4 misread sentences are held with the right question, the 30
  read as meant stay read. On the implementer's probes one line changed: a time in front of a
  condition sentence is now asked about. Packs built earlier read exactly as before.
- Second blind reading test (`probes/blind2_20261123/`, a new author, a new domain, same brief,
  one run after this rule): 32 of 60 read exactly as meant, 21 held, 7 partial, **0 read
  differently**. Three sentences were held by this rule with the right question; with the rule
  switched off, the same three come out read differently. See `diagnosis_after_the_run.txt`.

## Endings as pieces, first step (2026-11-23)

- Lessons only, no code: where Korean lets a word be cut between two characters, the ending
  after the fixed words 아니 and 맞 is a piece of its own (아니|야. 아니|에요. 맞|아요? 맞|죠?
  맞|습니까?). 48 made-up lessons on the plain shape (`endings` in `probes/reading_limits.py`).
- Measured: the transfer grid, widened by these five endings, reads 41 of 41 combined
  sentences. On the two exposed blind sets, reading goes from 30 to 32 and from 32 to 34 of 60,
  checks answered from 2 to 5 of 6; nothing read differently, no wrong answer. Exposed items:
  a check of the mechanism only.
- Not covered: endings that fuse into the last character (아닙니다, 아닌가요, 입니다). The plan is
  to extend the existing stem-and-ending discovery to fixed words and to compare letters
  instead of characters; see the reader design note, section 2.6. Not built.

## Stems and endings of fixed words, letter by letter (2026-11-23)

This replaces the first step above: the lessons no longer write an ending as a piece of its
own. They show the word whole (아니다, 아니야, 아닙니다, 맞나요, 맞죠 …) and the reader finds
stem and ending, as it always did for head words.

- `build` compares the forms of one fixed word (same type, not a word that asks) in Unicode's
  decomposed form and counts the shared beginning as a stem (`closed_stem`) and the rests as
  endings (`closed_ending`). Korean writes a stem's last sound and an ending's first sound
  into one character (아니 + ㅂ니다 = 아닙니다); compared by characters the two never meet.
- A stem does not stop on the first letter of a syllable (맞나요 and 맞는가 share ㄴ; the stem
  is 맞). Knowledge of the writing system, used like the last sound of a word already is.
- A word that asks (무엇, 얼마, 어디 …) is never cut: such words share a meaning and stray
  letters, and "어" plus an ending must not become a question word.
- Reading: a stem followed by any ending learned from any such word is a fixed word with the
  stem's meaning, if it ends on a character of the text. Nodes and evidence stay in the
  text's own characters. Endings are shared across stems: 죠, shown only in 맞죠, reads 아니죠.
- The recipe gains `meaning.closed_stem`. Packs without the two tables read as before.
- Measured on the implementer's grid: 44 of 44 combined sentences. On the two exposed blind
  sets, reading goes from 32 to 34 and from 34 to 36 of 60; nothing read differently. Exposed
  items again: a check that the mechanism works.
- Not done: head words still use the older character-level stems and their own ending table;
  the copula after a value (이다, 입니다, 인가요) is still a whole connector. Bringing both under
  this one mechanism is the base for reading predicate sentences.
- Third blind reading test (`probes/blind3_20261123/`, a new author, a new domain, one run
  after this rule): 31 of 60 read exactly as meant, 23 held, 6 partial, 0 read differently.
  Four sentences were held by the attachment rule with the right question. The pack loader
  refused the author's property word "높이" because the lessons use it as a made-up word; the
  first attempt stopped there before anything was scored (kept as
  `output_first_attempt_loader_refused.txt`), the runner was changed to report the clash and
  go on, and no reader code changed between the two attempts.
- Across the three blind sets the share read as meant stays near one half (30, 32, 31 of 60)
  while silent misreadings went 4, 0, 0. The forms added in this section moved the exposed sets
  by two sentences each and the fresh set not visibly: what is held there is mostly other
  things (a modifier or a denial inside "…인 것은", a time after a condition clause, a
  modifier after a topic-marked subject, endings no lesson shows such as 맞아 and 맞니).

## The lessons' own property words make way for the field (2026-11-24)

- Found by two blind sets: a field's "동절기" was held because the lessons' "절기" lay inside it
  as a known piece left unused, and a field's "높이" was refused by the pack loader because
  the lessons use that very word. The lessons need some word in the property slot to show the
  form of a sentence; that word was never meant as vocabulary of every field.
- Convention `lesson_words: make_way`. When a word pack is put on the language pack
  (`pack.with_words`), the lessons' words of the pack's slot are taken out of the model's
  `head` and `head_in` tables and out of its known pieces. Their counts stay where they
  matter: pooled into the form every field word gets, as before. The language pack itself is
  not changed, and without a word pack it reads its own lesson sentences as before.
- A field may now use such a word, or a word that contains it. A field that does not list it
  does not read it: the sentence is held like any sentence with an unknown property.
- Still refused: a field word equal to a fixed word of the language (무엇, 얼마, 아니다 …).
- Packs without the convention behave as before; the shipped packs carry their own. The 81
  library and tax questions give the same SHA-256 as before (470df3c3…). 90 public checks
  pass; one existing check was changed to assert both the new rule and the old one.
- Reruns on the three exposed blind sets (`output_rerun_after_lesson_words.txt` in each
  folder): 37, 36, 31 of 60 read as meant (before: 34, 36, 31); nothing read differently; the
  loader refuses no word of the third set. Exposed items: this shows the clash is gone, not
  how far reading generalises. The implementer's grid stays 44 of 44.
- Not covered: a field name or value that contains a connector or a fixed word of the
  language is a different clash and is untouched.
- Fourth blind reading test (`probes/blind4_20261124/`, a new author, a new domain, code frozen
  at the commit of this rule, one run, nothing changed afterwards): 32 of 60 read exactly as
  meant, 18 held, 8 partial, 2 READ DIFFERENTLY WITHOUT A FLAG. No field word was refused.
  The answering set is the same exposed one as before and says nothing new.
- The two misreadings are one pattern: a topic-marked subject, a condition clause, then a
  result clause with no subject of its own and a modifier in front of its property
  ("참나무장구는 재료가 쇠가죽이면 긴급 수리비가 얼마야?"). The modifier was read as the subject of
  the result. The attachment check did not see it: it asks when a part could belong to another
  head, not when a word could fill another role of the same head. Not fixed.
- Across the four blind sets: read as meant 30, 32, 31, 32 of 60; silent misreadings 4, 0, 0, 2.

## Word kinds: what kind of thing a word names (2026-11-24)

- `data/word_kinds_ko.json` lists words by kind: 25 words of time (올해, 내년, 지난달 …) and 68
  words for a circumstance (season, kind of day, part of the day, grade, group). Chosen by
  category, not from failed sentences. `reader.build(..., kinds=)` puts them in the table
  `word_kind`; they are not known pieces, so a longer word that contains one is its own word.
- Recipe `meaning.known_kind`: a free value that is a listed word has the listed kind, whatever
  connector follows it. With the rule that a node's type agrees with its role, such a word can
  no longer be read as a thing or a value.
- Recipe `argument.by_kind`: when the pieces on both sides of a listed word do not together
  support a role, the piece after it alone may (a modifier after "는 " instead of "의 "). The
  piece after the word still has to have been seen marking that role: "오전에", a circumstance
  marked as a time, is held, not read either way.
- One kind per word. Listing words of time under both kinds was tried and gave ties and four
  misreadings on exposed sets; taken back before the blind run.
- Packs without the table or the recipe parts read as before; shipped packs: same SHA-256 for
  the 81 library and tax questions (470df3c3…). 94 public checks pass (4 new,
  `tests/test_reader_kinds.py`). The implementer's grid stays 44 of 44.
- Exposed blind sets, read as meant before → after: 37 → 43, 36 → 41, 31 → 35, 32 → 38 of 60;
  the two silent misreadings of the fourth set are now held. Exposed: a mechanism check.
- Fifth blind reading test (`probes/blind5_20261124/`, a new author, a new domain, written after
  the word list and the rule were fixed, one run, nothing changed afterwards): 42 of 60 read
  exactly as meant, 15 held, 3 partial, 0 read differently. A control run of the same items
  without the word-kinds file: 36 of 60, 0 read differently. So the file is worth 6 sentences
  on this set; the rest of the difference to earlier sets (30 to 32) is the set itself.
- Limits: a word the file does not list is read as before, including the misreading of the
  fourth set ("특급 기본요금" after a topic and a condition clause; asserted in the checks). A
  time without "에" at the start of a sentence ("올해 X의 …") is still held: no lesson shows
  that form. A listed modifier after a bare subject ("밤식빵 명절 값은") is still passed over.

## A word whose role the form leaves open is asked about (2026-11-24)

- Made from the two misreadings of the fourth blind set and the limit stated above: a word no
  list knows, in front of a property whose clause has no subject of its own, was read as the
  subject ("…이면 특급 기본요금이 얼마야?"). By form the sentence is the same as one that names
  another thing there; what differs is what kind of word it is.
- Convention `role_check: true`, `reader._open_roles`. A reading is not accepted when the
  connector after one of its free values was also seen marking another role, that role was
  seen written on that side of a head, free values were seen filling it, and the head does not
  have it yet. Not asked about: a word whose kind is listed, a name or a value the field pack
  knows. The result is a hold with `open_roles`: the word, its head, the roles between which
  the choice lies. Feeding the answer back (it is one line of the word-kinds file) is not built.
- First version asked about ten "…인 것은" sentences on the exposed sets: the role of a
  comparison, which only fixed words fill, was offered as a choice. Corrected before the blind
  run by the condition that free values were seen filling the role.
- 95 public checks pass (1 new); shipped packs: same SHA-256 (470df3c3…); the grid stays 44 of
  44. Exposed blind sets unchanged in what is read as meant (43, 41, 35, 38, 42); one sentence
  is now asked about ("포장 용량이": subject or modifier).
- Sixth blind reading test (`probes/blind6_20261124/`, a new author, a new domain, one run,
  nothing changed afterwards): 37 of 60 read exactly as meant, 21 held, 2 partial, 0 read
  differently. Control without the check on the same items: the same numbers. The check did
  not fire: on this set it cost nothing and its use was not shown.
- What the sixth set did show: the author named a thing "새벽", a word the word-kinds file
  lists as a circumstance. Every sentence with that name in it is held. A name the field pack
  states has to outrank the general list; not changed after the run. Also held: "…5만마리면"
  (the condition ending after a vowel, which no lesson shows).

## Where the kind of a field's word comes from (2026-11-24)

- Owner's question: words never stop being made, so what becomes of a list? Decided: no list
  of open-class words is written ahead. `data/word_kinds_ko.json` keeps closed classes of the
  language only (words of the calendar seen from now, seasons, kinds of day, days of the week,
  parts of the day: 61 words); the 32 words of grade and group listed earlier the same day
  were taken out.
- A name the field pack states outranks the file (`pack._know_names` takes it out of the
  field model's `word_kind`; the language pack is not changed). Made from the sixth blind set,
  where a thing was named "새벽".
- A sentence whose form decides teaches the kind of its word. `reader._role_choices` finds
  free values whose own connector marks more than one role; where the head already has the
  other role, the form decided, and the complete reading reports the word and its kind in
  `kinds_seen`. `learn.note_kinds` keeps it in the conversation's memory with the sentence it
  was seen in; `learn.overlay` shows it to the reader as a `word_kind` row whose origin is that
  sentence. `answer.answer_graph` does this for every question read completely.
- The answer to the reader's question about a word is one line: `learn.tell_kind(memory, word,
  kind, by, at)`. Two kinds stored for one word are a dispute and the word is not used; a word
  the file lists keeps its kind; `learn.forget` removes what was stored.
- 99 public checks pass (4 new, `tests/test_word_kinds_learned.py`); shipped packs: same
  SHA-256 (470df3c3…); the grid stays 44 of 44. Exposed sets: nothing read differently.
- The blind runner now reads each set twice: as it is, and after keeping what the completely
  read sentences showed (no label of the author is used for that).
- Seventh blind reading test (`probes/blind7_20261124/`, a new author, a new domain, one run,
  nothing changed afterwards): 38 of 60 read exactly as meant, 15 held, 7 partial, 0 read
  differently; second reading 39. Control without the word-kinds file on the same items: 32,
  1 READ DIFFERENTLY ("햇살마루의 품종은 작년 수확량이 40톤이 맞습니까?", 작년 taken for a value);
  second reading 38, the misreading stays. From the sentences alone the reader kept 주말, 단체,
  평일 as circumstances and 작년 under two kinds (a dispute, not used).
- What this says: the closed-class file is worth 6 sentences on a first reading and one
  misreading prevented; reading the set once makes up the 6 without the file but not the
  misreading. The file stays.
- Cost seen: 작년 is listed as a time, and the author wrote it as a modifier ("작년 수확량")
  four times; those are passed over or held, with a flag. One kind per word is too narrow for
  words of the calendar. Not changed after the run.
- Not built: kinds from a fact pack's own statements (the fact format has no circumstance
  yet), and carrying the memory from one conversation to the field pack.

## An open word: each reading is tried against the knowledge, one survivor is answered (2026-11-24)

- Owner's decision: rather than only asking, the system answers by its own understanding and
  reports at the end how it understood, for the user to correct. Bounded by four conditions
  agreed with it:
  1. the answer has its own status, `assumed`, never `answered`, and is never `verified`;
  2. only when exactly one reading survives; none or two: the question is put to the user;
  3. questions only: a sentence taken in as knowledge is never read by assumption;
  4. a question read by passing over words is still withheld (`partial_answers`).
- Convention `open_role_answers: assume`, `answer._one_reading`. For one open word, each role
  the form allows is tried: the word is taken as the kind that fills the role, the question is
  read again, the knowledge is asked. A reading counts only if every word is read and the
  knowledge answers, which it can do only where it uses that word in that role itself.
- The result carries `assumed` (word, head, role, kind, and for every reading tried how it
  went) and `asked` (the question that would have been put). `explain` marks the first line
  "UNDER AN ASSUMPTION" and ends with "How the question was understood".
- Memory: `learn.note_assumed` records the assumption. It is a record, not knowledge: the
  reader does not use it, and repeating an assumption does not confirm it. `learn.tell_kind`
  confirms or corrects.
- 102 public checks pass (3 new, `tests/test_answer_assumed.py`); shipped packs: same SHA-256
  (470df3c3…); the grid stays 44 of 44; the exposed answering set is unchanged (no assumed
  answer occurs in it).
- Limit, found while building: of the two readings of an open word, only "a thing" can
  currently succeed. The other, a modifier of a clause that has no subject of its own
  ("모래섬호는 정원이 30명이면 특급 기본요금이 얼마야?"), is a sentence the reader cannot read
  under any assumption: it has no way to give one subject to two clauses. So the mechanism
  answers "특급 is a thing" when the knowledge has such a thing and otherwise asks.
- Not measured on blind items: no blind answering set with unknown words exists yet. Assumed
  answers are to be counted apart from answers, with how many of them were right.

## One part under two heads (2026-11-24)

- "X는 P가 V이면 Q가 W이다": X is the subject of both relations and is written once. A part could
  belong to one head only, so such a sentence was held, and with a word in front of Q that word
  was read as Q's subject (the misreadings of the fourth blind set).
- Lessons (`probes/reading_limits.py`, set `shared`, 48 lessons) show one node under two heads.
  `reader.build`: the part is an ordinary part of the head nearer to it; for the other head it
  is counted in the table `share`, under the role that joins the two heads (`if` → `subject`).
  A part under two heads that are not joined is refused.
- Reading (`_assign`): where two heads are joined and lessons showed that role shared through
  that join, the head without the part has the part of the other. One node, two edges. The
  attachment check treats a shared part as standing with the nearer head and does not ask
  about it.
- Recipe `argument.always` gains the side of its head a role is written on (table `side`, kept
  since the attachment check). Without it a listed modifier could be attached behind the head
  of the clause before it, and the sentence was held.
- Matching (`match._one_name_many_places`): a name the question writes once for two heads is
  matched at each place on its own, since the knowledge may write the name twice. The second
  answer method is given the question in that form (`as_matched`), so it still checks.
- With this, the assumed answer of the section before works both ways: the knowledge uses the
  open word as a modifier (answer under that assumption), as a thing (likewise), or not at all
  (the question is put to the user).
- 107 public checks pass (5 new, `tests/test_reader_shared.py`); shipped packs: same SHA-256
  (470df3c3…) — it changed once while building, because a result field was added even when
  empty; the field is now added only when it applies. The grid stays 44 of 44.
- Exposed blind sets, read as meant: 46, 43, 37, 40, 45, 40, 38 of 60; nothing read differently.
- Eighth blind reading test (`probes/blind8_20261124/`, a new author, a new domain, one run,
  nothing changed afterwards): 45 of 60 read exactly as meant, 13 held, 2 partial, 0 read
  differently. Control without the `shared` lessons on the same items: 44, 0 read differently.
  The set has few such sentences: the lessons are worth one sentence here. What is held: a time
  in front of a chain or a condition (asked about, 6), a time or a denial with "…인 것은" (4),
  a time after a condition clause (3), a modifier after a bare subject (2, passed over).
- Blind sets so far, read as meant on the first reading: 30, 32, 31, 32, 42, 37, 38, 45 of 60;
  read differently: 4, 0, 0, 2, 0, 0, 0, 0. The sets differ in difficulty; only the controls
  on the same items say what a change is worth.

## A fact answers only a question that names all its parts; first blind test from knowledge to answer (2026-11-24)

- Found on the implementer's own practice items while writing the runner below, before any
  blind item existed: with only "모래섬호의 주말 기본요금은 9000원이다" known, the plain question
  "모래섬호의 기본요금은 얼마입니까?" was answered 9000원. A qualifier of the knowledge was
  dropped: a wrong answer.
- Convention `unasked_parts: block`, in `match.match`. A fact fits a question only if the
  question names every part the fact has (a circumstance, a time, a condition, a denial). The
  hold says which part is missing ("when of 요금"). Packs without the convention: as before.
- `probes/blind_e2e.py`: knowledge is given as sentences and taken in one by one (only a
  sentence read completely, with no word passed over, is knowledge; the others are refused out
  loud); what the taken sentences showed about word kinds is kept; then every question is
  asked. Answered, assumed and held are counted apart. Written and frozen before the items.
- Ninth blind set, the first from knowledge to answer (`probes/blind9_e2e_20261124/`, a new
  author, field and 30 sentences and 50 questions of its own, one run, nothing changed
  afterwards): knowledge taken 30 of 30. Of 38 questions that have an answer: 32 right, 0
  wrong, 6 held. Of 12 that have none: 12 held. No answer was given under an assumption.
  By kind: direct 10 of 10, with a modifier or a time 8 of 8, yes/no checks 6 of 6, under a
  condition 5 of 5, asking for the thing 3 of 4, through a chain 0 of 5.
- What is held: every chain question (the knowledge says X's office in one sentence and the
  office's phone in another; nothing joins the two mentions of the office: the known limit
  "a nested graph is read but not answered"), and "…인 것은 어디인가요?" (어디 asking for the
  thing, no lesson).
- A defect seen in the output and not changed after the run: for a question under a condition
  the value is right, but the answer written as a sentence states the condition as a fact
  ("은행골의 상태가 공사중이다."). The scoring uses the value; the sentence is wrong and must
  not be shown as the answer until this is fixed.
- How far this goes: the author was told which forms the system claims to read and to stay
  within them. This measures those forms on unseen words and unseen knowledge, not questions
  asked freely (those were 0 of 18 on the first blind set and have not been measured since).
- 107 public checks pass; shipped packs: same SHA-256 (470df3c3…).

## A chain is answered from two facts joined by a name; second blind test from knowledge to answer (2026-11-24)

- Convention `name_joins: value`, in `match` (`_through`). A question that puts one relation in
  a role of another ("X의 P의 Q") is answered from two facts stated apart: the first relation's
  value and the thing in that role of the second carry the same name. The first relation must
  have exactly one part the question does not name; so a first link known only for a year,
  only under a condition or only as a denial gives no join. Both sentences are the grounds.
  Such an answer says `joined_by` and is never counted as independently verified (the older
  executor cannot join; `executor` is "not comparable").
- No sentence is written for an answer whose question has one relation under another (a
  condition, a chain): the writer stated the condition as a fact. The value and its grounds
  are the answer.
- 111 public checks pass (4 new, `tests/test_answer_parts_and_chains.py`); shipped packs: same
  SHA-256 (470df3c3…); the grid stays 44 of 44. The exposed ninth set: chains 0 → 5 of 5, 37 of
  38 right, 0 wrong.
- Tenth blind set (`probes/blind10_e2e_20261124/`, a new author, a museum, 36 sentences and
  60 questions with more traps, one run, nothing changed afterwards): knowledge taken 30 of
  36. Of 42 questions that have an answer: 27 right, 0 WRONG, 15 held (8 of them because their
  knowledge was refused). Of 18 that have none: 18 held, among them 5 chain traps and 5 plain
  questions about what is known only with a qualifier. Chains: 6 of 10 right, 0 wrong.
- What was refused or held, by cause:
  1. A day of the week as a value ("동관의 휴관일은 화요일이다", 5 sentences): the word-kinds file
     lists days as circumstances and a listed word is not read as a value. This is the file's
     doing; it cost 5 sentences of knowledge and 8 questions.
  2. "어린이 관람료" (1 sentence): a word ending in 이 followed by a space is cut as the particle.
  3. 누구 (6 questions): no lesson has that question word.
  4. A time in front of a chain (1): asked about, as it should be.
- Not changed after the run.

## The form decides first; what is known about a word is asked only where the form is silent (2026-11-24)

- Three times a piece of knowledge about words, put in to read more, made the reader read
  less: the lessons' own words blocked a field's words; the list blocked a field's name
  (새벽); the list blocked a value ("동관의 휴관일은 화요일이다", tenth blind set: 5 sentences of
  knowledge and 8 questions lost). Each time the knowledge said what a word is and was used as
  a veto on anything else. Changing the entries of the list does not end that.
- Convention `word_kinds: where_open`, `_Scorer.leaves_open`. The kind of a word (from the
  file, from sentences, from being told) is used only where the connector written after the
  word leaves its role open, that is where free values were seen in more than one role in
  front of that connector. Before "이다" a word is a value, before "의" a subject, before "에" a
  time: the form has decided, and nothing known about the word can refuse it.
- 111 public checks pass (two changed to the new behaviour: "오전에" is a time, "새벽의" a
  subject in any field); shipped packs: same SHA-256 (470df3c3…); the grid stays 44 of 44.
- Exposed sets: tenth, knowledge taken 30 → 35 of 36 and answers right 27 → 34 of 42, 0 wrong;
  ninth unchanged (37 of 38). Reading sets: 46, 43, 37, 38, 44, 40, 38, 45; nothing read
  differently. Two sets lose sentences (fourth 40 → 38, fifth 45 → 44): a listed word of time
  after a condition clause ("…이면 내년에 …") had been read only because a listed word skipped
  the connector in front of it. That was the list doing by accident what the reader should do
  for every word; see the next step in the design note (2.15).
- Not measured on a fresh blind set.

## An unread question is put to the knowledge the other way round (2026-11-24, after checkpoint 728dd70)

- Owner's direction: do not try to generalise the language; use the knowledge to make the
  problem small. What the system can answer is only what it holds, so the meaning of a
  question is "which of my facts does this ask about", and those can be counted.
- Convention `unread_question_answers: anchor`, `answer._anchor`. For a question the reader
  did not read: the things, property words and circumstances it names are looked up among the
  plain facts of the knowledge (one thing, one property, one value; facts under a condition,
  denied or with a relation as a part are left out). What narrows the property, in this order:
  a property word; a counter (convention `counter_question_word`, "몇 명" asks for a value
  counted in 명, the unit being taken from the values the knowledge has); what the question
  word asked for in questions that were read and answered before (`learn.note_ask`).
- One fit: the value is given with status `assumed`, never `answered`, never verified, with
  what was understood, what was recognised, how the fact was chosen and what was not read.
  Several: they are listed in `candidates` and nothing is answered. None: as before.
- Not anchored: a question with a word that checks or denies (the value in it has to be
  read); a question that names a circumstance the fact does not have, or lacks one the fact
  has; a question in which an unread word is marked as a noun of the sentence ("수심은").
- `pack.with_words` keeps the slot of the word pack in the model (`field_slot`).
- 115 public checks pass (4 new, `tests/test_answer_anchor.py`; one earlier check now expects
  the candidates in a hold); shipped packs: same SHA-256 (470df3c3…).
- Exposed first answering set (`probes/blind_20261123`, rerun kept): questions asked freely
  0 → 8 of 18, all as assumed answers, 0 assumed wrong; 5 more direct and alias questions with
  untaught endings likewise; the 8 questions without an answer are all still held. Exposed
  sets nine and ten: unchanged but for 2 more assumed right; 0 wrong.
- THESE ITEMS WERE IN VIEW WHILE THE RULE WAS MADE. By the owner's own test this is the
  overfitting case; the numbers show the mechanism runs, nothing more. Known weak points: a
  verb form ending in 는 is taken for a marked noun and blocks ("빌리는 데"); an unread word
  that is a qualifier and is not marked, not listed and not in the knowledge is passed over
  ("어린이" before a verb); 얼마 inside 얼마나 is found as 얼마.
- `probes/examiner_brief_ko.md`: a brief for an examiner outside this work, who writes the
  field, 36 sentences of knowledge and 70 questions without form limits (short, particles
  dropped, verbs), with 18 that have no answer. `probes/blind_e2e.py` runs it; it now takes
  other words for properties and names. The owner decides who the examiner is.

## First set from an examiner outside this work (2026-11-24)

- `probes/outside1_e2e_20261124/`: field, 36 sentences of knowledge and 70 questions written
  from `probes/examiner_brief_ko.md` by an examiner who is not the lesson writer and did not
  see the code; brought by the owner. Questions had no form limits. Code as it stood (the
  anchored reading uncommitted), one run, nothing changed afterwards.
- Knowledge taken 35 of 36 (refused: "새벽쉼터의 위치는 남쪽정원이다", a value that contains the
  property word 정원).
- 52 questions that have an answer: answered right 11, answered wrong 0; ASSUMED right 19,
  ASSUMED WRONG 3; held 19. 18 that have none: held 16, ASSUMED WRONG 2.
  By kind (right as answered + right as assumed, of all): direct 5+2 of 8, short 0+8 of 12,
  asked freely 0+7 of 14, with a modifier or time 4+2 of 8, checks 1+0 of 4, chains 1+0 of 6.
- The five wrong assumed answers:
  1. "숲바람쉼터 관리처 연락처?" → the office, not its phone. Two property words are a chain; the
     anchor took the one the thing has a fact for.
  2. "숲바람쉼터 단체 얼마?" → the plain fee. 단체 is unread, unmarked, in no list: the weak point
     stated beforehand.
  3. "별빛쉼터는 어디에 있어요?" → its office. 어디 had asked for 위치 and for 관리처; the thing has
     no 위치, so one fit was left. What a question word may ask for must not be narrowed by
     what happens to be known of the thing.
  4, 5. "…정원이 20명인가요?", "…전화가 02-730-1101인가요?" → the true value instead of yes or no.
     A check without 맞 was not recognised as a check; the stated value was passed over.
- A defect seen in the output: the relation inside a condition ("노을쉼터의 예약이 승인완료이면 …")
  is listed by `_known_facts` as a plain fact. Here it only made two candidates of one and
  held two questions; it could as well give a condition's value as a fact.
- Reading of the result: the answered tier stays clean (11 right, 0 wrong). The assumed tier
  is 19 right to 5 wrong; without it 19 fewer questions are answered and none wrongly. As it
  stands the anchored reading is not fit to be shown as an answer; its report makes each of
  the five wrong ones visible, which is what the tier is for, but a rate of one in five is
  not acceptable.

## Every piece of an unread question has to be accounted for (2026-11-24)

- What was wrong with the anchored reading, in one line: it treated what it had not read as
  what did not matter. In all five wrong answers of the outside set the word that changed the
  answer was among the unread ones. One fact left over is not the question understood.
- The rule is turned round. Before: an unread piece blocked only when it was known to be
  risky. Now: an unread piece is passed only when it is accounted for, and there are two ways
  to be: a connector or closing piece the lessons have, or wording that was said before for
  this very property and that the user confirmed (`learn.note_said`).
- All pieces accounted for: status `assumed`, as before. A piece left over: no answer; the
  result is a hold with `proposal` (what the question was taken to ask, the pieces not
  accounted for, the value to give on a yes, a sentence to put to the user).
  `answer.confirm(result, memory, by, at)` is the yes: it returns the answer and keeps the
  wording, so the same wording for the same property is read next time.
- With it, the four causes and one defect of the outside set:
  two property words are a chain (first fact's value is the thing of the second; both
  sentences are the grounds), not a choice; a question that states a value the knowledge has
  is a check whatever its ending and is not anchored; a question word that has asked for
  more than one property never gives an assumed answer; a relation that stands inside
  another (the clause of a condition) is not a plain fact; exactly one thing must be named.
- 116 public checks pass (`tests/test_answer_anchor.py` rewritten, 5 checks); shipped packs:
  same SHA-256 (470df3c3…).
- The outside set again (EXPOSED NOW; a mechanism check): assumed wrong 5 → 0. As asked:
  answered right 11, assumed right 13, proposed right and waiting for a yes 11, proposed
  otherwise 2 (the two questions without an answer that had been answered wrongly are now
  put to the user), held 17, held without an answer 16 of 18. With a user saying yes or no to
  each proposal: 35 of 52 right, 0 wrong, 2 declined. The runner plays that user with the
  examiner's answers, so that pass is not blind to them.
- Within the 70 questions a confirmed wording was hardly said again: the yes of one question
  did not turn a later proposal into an answer. What use teaches shows over more use than this.
- A new outside set is needed to say what this is worth.
- A defect found the same day while answering the owner's question about "단체": with a plain
  fact and a qualified fact of the same thing and property both known ("이용료는 1000원",
  "단체 이용료는 700원"), the plain question was held, because the qualified fact counted as an
  event that fits the question without saying what was asked. `match` now applies the
  unasked-parts rule there too (`_more_than_asked`), and an answer for which other facts were
  set aside is "not comparable" for the older executor, which has no such rule and gives both
  values; such an answer is not counted as independently verified. No blind set had a thing
  with both a plain and a qualified value of one property. 117 public checks pass (1 new);
  shipped packs: same SHA-256; exposed sets unchanged, 0 wrong.

## A question is read with the knowledge (2026-11-24, after checkpoint 05955b1)

- Owner's instruction: understanding a sentence has to use the knowledge graph. Until now the
  reader read a question from lessons, lists and packs, and the knowledge came in afterwards
  (matching) or as a rescue (an open word, an unread question).
- `reading_uses_knowledge: true`, `answer._with_knowledge`. The model a question is read with
  gets what the knowledge shows about its own words: a word the knowledge uses (a thing, a
  value, a circumstance, a time) is known as the kind it was read as there, origin "the
  knowledge uses … as a …". It outranks the general list, and like every word kind it is
  asked only where the form leaves a role open. A field whose knowledge states a "단체 이용료"
  knows 단체 with no lesson and no list.
- `close_readings: ask_knowledge`, `answer._decided_by_knowledge`. When the reader cannot
  choose between fully seen readings of a question, each is put to the knowledge; if those
  that are answered agree, that answer is given with status `assumed` and every reading
  tried. If they differ, or none is answered, the question stays held.
- A form that was missing, found while trying this: a subject without 의 followed by a
  modifier ("물결쉼터 주말 이용료는 …"). The modifier was passed over however well the word was
  known, because no lesson showed a free value after " " after a free value. Lesson set
  `bare_modifier` (48 lessons). With both words unknown the order alone decides which is the
  thing; within a field the knowledge and the pack name the things.
- Consequence for earlier checks: an open word that the knowledge itself uses is now simply
  read, and the answer is `answered`, not `assumed`. The checks of the assumed path switch
  the convention off; one new check asserts the new behaviour and its origin.
- 118 public checks pass (1 new); shipped packs: same SHA-256 (470df3c3…); the grid stays 44
  of 44. Exposed reading sets, read as meant: 48, 45, 39, 40, 47, 42, 40, 47 of 60 (before:
  46, 43, 37, 38, 44, 40, 38, 45); nothing read differently. Exposed sets from knowledge to
  answer: the outside set 11 → 12 answered right (the weekend check without particles), the
  rest as before; ninth and tenth unchanged; 0 wrong on all three.
- What this did not do: on the outside set it changed one question. The questions that are
  not read there fail on verbs and endings no lesson has, and those go to the anchored
  reading, which already used the knowledge. Knowledge still enters the reader as word kinds
  and as a judge between finished readings; it does not yet take part in cutting the
  sentence into pieces or in building a reading. Not measured on a fresh outside set.

## The knowledge used more deeply when a question is not read (2026-11-24)

- Owner's instruction: go deeper and see how much it gains. Three more uses of the knowledge
  in `answer._anchor`, each made from a held question of the (exposed) outside set:
  1. A value the knowledge has, stated in the question, makes it a check of that value,
     whatever its ending: with a property word, the answer is yes or no (`claim`) and the
     true value. Before, such a question was given up.
  2. Letters an unread word shares with a property word ("관리하는", 관리처) or with the value a
     fact of the thing has ("요일마다", 매주화요일) point at a property. A pointer, not a
     reading: it can lead to a proposal and never to an answer, even after every piece of
     the wording has been confirmed.
  3. The last word of a question is its predicate whatever it ends in ("들어가?"); only an
     unknown word that is not last and is marked as a noun makes the question be given up.
- A defect of the day before, found here: the words of the knowledge that `_with_knowledge`
  adds to the word kinds made every value of the knowledge a "circumstance" for the anchored
  reading, so a question stating a value named a circumstance no fact had. Only words known
  as something other than a thing or a value count as circumstances now.
- 120 public checks pass (2 new, 1 changed to yes/no); shipped packs: same SHA-256.
- The outside set, EXPOSED, step by step (52 questions with an answer, 18 without):

      step                                   answered  assumed  proposed  proposed   held  wrong
                                             right     right    right     otherwise
      one fit is answered (first run, blind)    11        19        -         -       19     5
      every piece accounted for                 11        13       11         2       17     0
      a question is read with the knowledge     12        13       11         2       14     0
      the three deeper uses                     12        15       13         2       10     0

  With a user answering each proposal: 35, 36 and 40 of 52 right for the last three rows,
  0 wrong; the 2 other proposals are declined. Of the 18 without an answer, 16 are held and
  2 are put to the user, in every row but the first.
- Ninth and tenth sets: unchanged but for one more proposal; 0 wrong. First answering set:
  questions asked freely, 9 of 18 proposed right, 0 answered, 0 wrong.
- What the rows say: going deeper moved 7 questions out of "held", 3 of them into answers and
  4 into proposals. The largest step was not depth but the rule that every piece be accounted
  for. All of it on items that were in view; a fresh outside set is needed.
- Still held on that set, by cause: 어디 has asked for two properties (위치, 관리처) and nothing
  in the question separates them (4); verbs with no shared letters and no known question word
  ("맡아 운영하나요", "어떻게 신청해요", "언제까지 열어", 4); "한 번에" marked as a noun (1); one
  whose knowledge was refused (2).

## A second set from the owner's outside examiner, on four checkpoints (2026-11-25)

- `probes/outside2_e2e_20261125/`, run once with `compare_checkpoints.py`. It is not a fresh
  set: its 36 sentences of knowledge are the same as the first outside set's, and 54 of its 70
  questions have the same text. 16 questions are new (`new_question_ids.json`): 9 with an
  answer, 7 without. Only those 16 are blind; the other 54 were in view while the rules of
  05955b1 and 2c3944f were made.
- All 70, as asked (52 with an answer, 18 without):

      commit   answered  assumed  proposed  proposed   held  wrong  no-answer
               right     right    right     otherwise               held
      ded9098      9        0        0         0        43     2      16
      728dd70      9        0        0         0        43     0      18
      05955b1      9       12       14         2        17     0      16
      2a2d0b0     10       14       16         2        12     0      16

- The 16 new questions alone:

      commit   assumed  proposed  proposed   held  wrong  no-answer held (of 7)
               right    right     otherwise
      ded9098     0        0         0         9     0        7
      728dd70     0        0         0         9     0        7
      05955b1     1        3         1         5     0        6
      2a2d0b0     1        3         1         5     0        6

- What the new 16 say. The anchored reading with every piece accounted for (05955b1) carries
  over to questions it had not seen: of 9 with an answer, 1 answered and 3 proposed rightly,
  none wrong; of 7 without, none answered, one put to the user with the unread word named
  ("단체로"). The deeper uses of 2c3944f add nothing on the new questions: its gain of the day
  before was on the items it was made from. No checkpoint gives a wrong answer on the new 16.
- Held among the new ones: 어디 alone (2; it has asked for 위치 and for 관리처), two long chain
  questions asked with verbs, one whose knowledge sentence is refused.

## A third set from the owner's outside examiner: a new field and new knowledge (2026-11-25)

- `probes/outside3_e2e_20261125/` (greenhouses and their centres; 36 sentences, 70 questions
  without form limits), run once on four checkpoints with `compare_checkpoints.py`, code as
  committed (2a2d0b0), nothing changed afterwards. The property words are much the same as in
  the earlier outside sets; the things, the values, the knowledge and the questions are new.
  This is the first run in which every item is blind for 05955b1 and for 2c3944f.
- As asked (52 questions with an answer, 18 without):

      commit   knowledge  answered  assumed  proposed  proposed   held  wrong  no-answer
               taken      right     right    right     otherwise               held
      ded9098  35 of 36      9         0        0         0        42     1      18
      728dd70  36 of 36      9         0        0         0        43     0      18
      05955b1  36 of 36     10        11       16         1        14     0      18
      2a2d0b0  36 of 36     10        12       16         1        13     0      18

  With a user answering each proposal: 38 of 52 right at 2a2d0b0 (10 answered, 14 assumed,
  14 after a yes), 0 wrong, 1 proposal declined. Two proposals became assumed answers within
  the run, because wording confirmed earlier in it was said again.
- What it says:
  1. No wrong answer from 728dd70 on. The one wrong answer of ded9098 gives the plain fee and
     the weekend fee together for the plain question: the defect the unasked-parts rule ended.
  2. The step of 05955b1 holds on a new field: from 9 answered and 43 held to 21 answered or
     assumed, 16 proposed rightly and 14 held, with all 18 questions without an answer held.
  3. The deeper uses of 2c3944f are worth one question here (a check that states a value
     without 맞: "바람온실 정원은 20명인가요?" → no, 15명). The pointer by shared letters and the
     final-predicate rule changed nothing on this set.
  4. The one proposal that is not what was asked: "별숲온실 담당센터는 어디에 있나요?" is taken to
     ask for the centre, not where the centre is; "어디에 있나요" is not understood as 위치.
- Still held (13): verbs with no property word and no counter for what is asked ("얼마를 내야
  해요" with "하루에" in between, "몇 번으로 걸어요" where the phone number has no unit, "어떻게
  미리 신청해요"); 어디 where the thing has both a place and a centre; chains asked with verbs
  ("관리하는 센터에 전화하려면"); two checks asked with verbs.
- Of the 18 held without an answer, most are held because the question was not read, not
  because the missing qualifier was seen. Whether they would be held once read is not shown.

### Fourth outside set (2026-11-25); step 2 of the structure note tried and set aside

- `probes/outside4_e2e_20261125/C.json`, made outside from `probes/examiner_brief_ko.md`: a new
  field (instrument rental desks), 36 sentences, 70 questions (52 with an answer, 18 without).
  The values of 위치 are buildings that have a phone and an office of their own. Run once on
  five checkpoints with `probes/compare_checkpoints.py`; outputs in `by_checkpoint/`.
- Of 52, as asked: `ded9098` 8 right, 1 WRONG, 43 held. `728dd70` 8 right, 44 held.
  `05955b1` 9 right, 12 assumed right, 6 proposed right, 25 held.
  `2c3944f` 9 right, 13 assumed right, 7 proposed right, 23 held, 0 wrong; 29 of 52 with yes/no.
  Questions without an answer: 18 of 18 held on every checkpoint.
- `ad18b1e` was step 2 of the structure note (basic concepts thing / quantity / name told from
  the knowledge; 어디 asks for a name). On this set it gave **1 assumed WRONG**: "현악창구 어디?"
  → 현악지원팀. Where a place has facts of its own, 위치 turns into kind thing and 관리처 into
  kind name. `2c3944f` holds that question with both candidates. Its gains on the second and
  third sets had come from rules made while looking at those sets.
- Step 2 is not on this branch. It is kept, with its record, on the local branch
  `failed/goal1-step2-basic-concepts`. This branch continues from the behaviour of `2c3944f`.
- Rules kept from this:
  1. What is guessed (word kinds, basic concepts, the look of a value) never makes an answer
     and never takes a candidate away.
  2. A step that tidies the structure must leave behaviour as it is (same pack digest, same
     outputs on the outside sets). A change of behaviour is put forward on its own and
     measured on a new set.
- Still unread on this set: all 6 chains ("…가 있는 건물의 …"), 10 of 14 questions in natural
  wording, 3 of 4 checks asked with verbs. This set is now exposed.

### Tried and set aside (2026-11-25): wording counts from ordinary text

- Tried: count, in 2.1 million ordinary sentences, the words standing near a field's property
  words (first 1–3 letters of each word, integer counts, no vectors, no list of endings), and
  use them, for proposals only, to say which property an unread word of a question is about.
  Light: 11–14 s and 300–500 KB per field, a table look-up when answering.
- It does tie some wording to properties (걸다 → 전화, 건물 → 위치). On the four exposed outside
  sets it added 6 right proposals and 6 that were not what was asked; no answer changed; 0 wrong.
- Why it is not kept: standing near a property word is not asking for it (어린이, 주차장 stand
  near 요금); a field's own property words are rare in ordinary text (대여기간 8 sentences,
  관리처 30 of 2.1 million); common verbs (있다, 가다) stand near everything.
- Kept, with the code and the full record, on the local branch `failed/goal1-wording-counts`.
  Not on this branch: the code here is that of `2c3944f`.
- Also ruled out the same day, by the owner: a graph of dictionary definitions. It was tried
  early in this project and dropped because it does nothing for new words.

### Counted, not built (2026-11-25): one step through the dictionary and hanja readings

- Asked for by the owner as a second look at a method dropped early in this project. Then it
  was open-ended (understand every word; it found meanings and stopped there). Here it has two
  ends and one step: from each property word of the field to its dictionary definition and to
  the native reading of its hanja (休務日 → 쉴, 貸與 → 빌릴), and from there to an unread word of
  the question. Data: the standard dictionary of the national language institute (434,361
  entries, with the hanja of each word) and a table of 5,978 hanja readings; both deleted after
  the count. No project code was written.
- The bridges are real: 휴무일 "직무를 보지 아니하고 쉬는 날", 이용료 "이용한 값으로 내는 요금",
  소재지 "… 자리 잡고 있는 곳", 예약 豫 미리, 운영 … 開 열, 대여 貸 빌릴.
- Count on the 50 held questions that have an answer, in the four exposed outside sets
  (a stem that leads to two properties of the field is not used):
  every word of the definitions: right 6, wrong 9, several 13, none 22;
  hanja readings and the definitions' "-는" verbs only: right 5, wrong 7, several 6, none 32.
  On the 58 held questions without an answer it points at one property for 16–21 of them.
- The same half and half as the wording counts from ordinary text, with different words
  (쉬다, 내다, 미리, 열다 here; 걸다, 통화, 건물, 얼마 there). What goes wrong: one-letter stems
  (하-, 되-, 들-) land everywhere; a word's other senses come along (전화 as 轉化 gives 될);
  in a chain the bridge finds the first link, not what is asked ("관리하는 곳에 연락하려면" →
  관리처, asked: 전화); and nothing says which word of the question is the one that asks.
- Both together (counted the same day, same 50 held questions; the files were fetched again and
  deleted again). A pointer is used only where the dictionary step and the counts from ordinary
  text name the same property for the question:
  every word of the definitions: right 11, wrong 2, none 37 (alone: dictionary 6 right / 9
  wrong, text 10 / 10); hanja readings and "-는" verbs only: right 6, wrong 0, none 44.
  The two wrong ones are chains ("…가 있는 건물의 전화번호"): both sources name 위치, which is the
  first link of what is asked, not a wrong property.
  On the 58 held questions without an answer the two agree for 15–20, and in each of them on
  the property that is in fact asked ("언제 쉬어요" → 휴무일, "얼마 내요" → 이용료); that there
  is no answer is for the graph to find (a qualifier, a condition, an unknown thing).
- Reading: either source alone is right as often as wrong; where two unrelated sources agree
  the wrong ones nearly vanish, at a quarter of the questions. Exposed sets, thresholds set on
  them, 50 questions: a reason to build and measure on a new set, not a result.

### Two sources that must agree (2026-11-25): built, not yet measured on a new set

- `lexicon.py`: one step through a dictionary from the field's property words (definition and the
  native reading of each hanja; a word that is no headword is cut into headwords; of several
  senses those that share something with the property's other words; a stem leading to two
  properties of the field is left out). `wording.py`: the counts from ordinary text, as on the
  set-aside branch. Both are plain integer or string data with where each step came from.
- `answer._both_point`: the properties both sources tie to unread words (and question words) of
  a question. Used in `_anchor` in three places, each leading to a proposal only:
  1. nothing else points anywhere and the question word asked for nothing before: the one
     property both agree on is proposed;
  2. a property word is there and both sources lead to another property whose value is a thing
     that has the asked property: proposed as a chain ("…있는 건물 연락처" → 위치, then 전화);
  3. an unread word marked as a noun stops the question as before, unless both sources agree on
     what that very word is about (`bridge['stop']` = `word`, the default) or on what the
     question is about (`question`).
- A model without `bridge` behaves as before: 123 public checks pass (3 new,
  `tests/test_bridge.py`), shipped packs same SHA-256 (470df3c3…), and the four outside sets give
  the output of `2c3944f` line for line.
- Sources, outside the repository (`.worktrees/data/`, 181 MB): 269,281 noun senses of the
  standard dictionary (36 MB, CC BY-SA), 5,978 hanja readings (0.3 MB, no licence stated),
  2,106,219 sentences of a public Q&A site (145 MB, no licence stated). Nothing derived from
  them is committed. `probes/blind_e2e.py` builds both tables when `GOAL1_BRIDGE_DIR` names the
  folder (`GOAL1_BRIDGE_STOP=question` for the looser rule); about 15 s per field.
- On the four exposed sets, against no sources (a check of the mechanism, not a measurement;
  the first and second set share their knowledge):
  stop by word: right proposals +4, proposals that are not what was asked +0, answers the same;
  stop by question: right proposals +14 (four of them chains, the first chains ever proposed),
  not what was asked +6, two questions without an answer now put to the user (어린이 … 이용료);
  0 wrong answers either way.
- The rules and thresholds were made while looking at these sets. To be measured on a new outside
  set, both stop rules, before anything is claimed.
- A stop rule between the two (`bridge['stop']` = `between`, added the same day after the
  owner asked for the middle): as `question`, but where an unexplained noun was let pass, a
  property word put straight to the thing stays stopped (in "N의 P" an unknown N is likely whose
  P is asked); the agreed property, a chain, shared letters, a counter and a question word's
  history go on. On the four exposed sets, against no sources: right proposals +14 (the same as
  `question`), not what was asked +3 (`question`: +6), 0 wrong answers. The three left: one chain
  taken as the thing's own phone, and "어린이가 … 얼마 내요" twice (the fee is what is asked; that
  there is no children's fee is not seen, and the word is shown as not accounted for).
  Third rule made on the same exposed sets. All three (`word`, `between`, `question`) are to be
  run once on a new outside set.
- Fifth outside set (`probes/outside5_e2e_20261125`, a coastal visitor park; 52 questions with an
  answer, 18 without), run once at `8f58739` on each configuration, nothing changed afterwards;
  outputs in `by_configuration/`. 33 of 36 sentences taken (refused: a modifier never met, one
  conditional, one sentence with a wrong particle).
  No sources: right 6, assumed right 8, proposed right 16, proposed otherwise 1, held 22, held
  rightly 17, 0 wrong answers.
  `word`: proposed right +1 ("쉬는 날"). `between`: +2 (also "무슨 요일에 쉬어요"), nothing else
  changed. `question`: +2 and one more proposal that is not what was asked (a chain taken as its
  first link only). 0 wrong answers on all four.
  The +14 seen on the exposed sets did not come back: on a new field the two sources agreed on
  two questions. Of 14 questions asked with a verb, 10 are held without sources and 9 with them.
  The one proposal that is not what was asked on every configuration (a year the knowledge does
  not have, shown as not accounted for) does not come from the bridge.
- Set aside after the fifth set (owner's decision): +2 proposals did not pay for two modules and
  181 MB of outside sources. The code is kept on `failed/goal1-dictionary-text-bridge`;
  `answer.py` and `probes/blind_e2e.py` are back as at `1732237`, and the sources are deleted.
  The `word`, `between` and `question` outputs of the fifth set cannot be reproduced from here.

## Basic words (2026-11-25, built; not measured)

- The owner's direction after three attempts to learn without teaching: teach. A teacher wrote, for
  the first 1,000 words of a frequency list (942 distinct), which concepts each word points at
  (`packs/basic_words_ko.tsv`: 163 concepts, 942 words; brief in
  `probes/teacher_brief_basic_words_ko.md`). The words were cut by frequency rank, not picked from
  held questions. The teacher saw no outside set. The builder checked form and consistency only and
  sent faults back; it did not write or change a meaning.
- A field may explain a property in plain words (`explained` in the word pack). `basic.py` reads
  the lessons; `pack.with_words(language, words, basic)` keeps the concepts each explanation
  reaches and the words of it no lesson knows.
- `answer._anchor`: where a question names one thing and nothing in it points at a property by
  form (no property word, no counter, no shared letters, nothing the question word asked for
  before), the pieces not read and the question word are put next to the explanations. A property
  is found when every piece has a sense wholly inside its explanation's concepts or a light use,
  and at least one piece meets it by meaning. One property: a proposal, never an answer. Several:
  candidates. A piece no lesson knows, or a taught word no explanation has, finds nothing.
- Without the lessons nothing is in the model and nothing changes: the five outside sets give the
  same lines as the committed code, the hashes of the changed files apart. 128 checks pass.
- Shapes. The language pack has 9 endings and 6 connectors, so most inflected words did not reach
  their lesson: of 308 distinct question words of the five exposed sets, 69 did (a mechanism check
  on exposed sets, not a measure). The teacher then wrote, for the 290 basic words in -다, three
  stems each, and four lists of 80: endings after each stem and connectors after a noun
  (`packs/word_ends_ko.tsv`; brief in `probes/teacher_brief_word_ends_ko.md`).
  `basic.load(words, ends)` makes every stem with every ending of its kind a form of the word
  (64,970 forms, compared letter by letter); an ending of several words is cut at its first word.
  With them 138 of the 308 reach a lesson. Taught connectors are used only to find a word and
  inside the worked-out step; they do not make a piece "accounted for" where form decides, so no
  proposal turns into an answer because of them.
- The examiner brief now asks for `explained`, one plain line per property, written before the
  questions. Sets made from it are not comparable with the first five as they stand; a new set is
  to be run once without and once with the lessons (`blind_e2e.py <folder> [words] [ends]`).
- Known limits. Not taught: endings that go under a stem as ㅂ니다, ㅂ니까, ㄴ다, and the bare
  third stem as a whole word (해, 가). The stems hold forms that are not used (갖으, 갖아) and the
  other verb written 걷다; they add forms and remove none. A yes to a worked-out proposal is not
  kept yet. No outside set has been run with explanations: whether this answers more is unknown.
- Sixth outside set (`probes/outside6_e2e_20261125`, a made-up luggage store; 52 answerable, 18
  without answer; made from the brief with `explained`), run once at `53c1e5b` without and with
  the lessons (`by_configuration/none.txt`, `taught.txt`). All 36 sentences taken.

  | | right | assumed right | proposed right | proposed otherwise | held | held rightly | wrong |
  | --- | --- | --- | --- | --- | --- | --- | --- |
  | without | 9 | 13 | 9 | 2 | 21 | 16 | 0 |
  | with | 9 | 13 | 11 | 4 | 17 | 16 | 0 |

  The worked-out step found nothing: not one of the four changed questions was chosen by
  taught words meeting an explanation. All four come from the other change that rode along, a
  taught word in front of a connector no longer stopping the look-up ("하루에", "건물의"): two
  right proposals (Q21, Q22, chosen by what 얼마 asked for before) and two chains proposed as
  their first link (Q47, Q50). That change was not measured apart, against the rule that a
  change of behaviour goes alone.
  Why nothing was worked out, looked at after the run and not used to change anything: 7 of 8
  explanations and 12 of 14 natural questions have a word no lesson reaches. Outside the first
  1,000 words: 짐, 맡기다, 신청하다, 통화하다, 누르다, 돌보다, 찾아가다, 번호, 날수, 운영하다,
  입주하다. Taught words in a shape nobody taught: the third stem alone (맡아, 알려, 들어가) and
  어디예요. Where every word is known (Q29 "어느 건물에 있어요") the rule itself does not meet:
  건물 is not among the concepts of "찾아가면 만날 수 있는 곳". A building being a place is
  knowledge between concepts, which the lessons do not have.

## Worked out by degree (2026-11-25, built after the sixth set; not measured)

- The owner's question after the sixth set: is too little compared by number? The reader counts;
  the step from a question to a property did not. It was all or nothing, and one piece the
  explanation lacked ("건물") left a question with nothing.
- `basic.ranked` replaces the all-or-nothing rule. Every property a piece meets comes back with
  the pieces met and the pieces not met, most pieces met first. The number only orders. Nothing
  is taken above some number, and nothing worked out is answered: one property that leaves no
  piece over, or the only property any piece meets, is a proposal that names the pieces not
  met; otherwise the properties are shown as candidates in order (`candidates` carry
  `if_confirmed`, `met`, `unmet`). The runner counts where the right one stands.
- Without the lessons the six outside sets give the same lines as before. 130 checks pass.
- On the sixth set, which is exposed now, so this shows the step running and measures nothing:
  against the frozen run with lessons, one more right proposal, three more that are not what
  was asked (two of them where there is no answer), and four questions with candidates: the
  right one first twice, listed once, missing once. 0 wrong answers.
  What it shows about the number: in the two lists where one property met more pieces than the
  rest (3 against 2, 2 against 1) it was the right one. In the other two every candidate met one
  piece, the order was that of the names, and the right one was not first. The three new
  proposals that are not what was asked each rest on one common piece (수, 있다, 곳) that many
  explanations have. A piece that meets every explanation says nothing and counts the same as
  one that meets a single explanation. Weighing a piece by how few explanations it meets would
  be a number from the field itself; it was thought of after looking at these lines, so it is
  not built, and if built it has to be measured on a new set.

## A trial: a vector model on the hearing side (2026-11-25, the owner's request, once)

- Not part of the system. `probes/hear_vector.py` reads a Korean sentence encoder that was already
  on the machine (jhgan/ko-sroberta-multitask, 423 MB, network off). Where nothing in a question
  points at a property by form, the whole question is put next to each property's words (its
  word, other words, its explanation where the set has one) and the nearest property the thing
  has is put to the user as a proposal with every piece that was not read. Nothing it picks is
  answered. No number decides anything. `MARCO_HEAR=vector` on the runner; `MARCO_HEAR=veto` puts
  nothing there and only lifts the stop on an unknown word in front of a connector.
- Run once on all six outside sets (420 questions), all of them exposed before; the first five
  have no explanations. What was compared was fixed before the run. 0 wrong answers everywhere.

  | all six sets | proposed right | proposed otherwise | held | held rightly |
  | --- | --- | --- | --- | --- |
  | as committed | 77 | 8 | 98 | 101 |
  | stop lifted only | 99 | 29 | 62 | 94 |
  | stop lifted + vector | 119 | 47 | 35 | 82 |

- The stop lifted, alone: of questions about one fact, 18 more right proposals and none that is
  not what was asked. Its cost is elsewhere: 14 chains proposed as their first link (4 right) and
  7 questions without an answer proposed.
- The vector, on top of that: of questions about one fact it newly decided 25, 20 of them right.
  It cannot tell that there is no answer: 11 such questions got a proposal, and 2 chains. One
  question crashed in the trial's own code (a thing with no fact left to order); fixed after
  the run, not run again.

## Relations inside a sentence (2026-11-26, built; not measured)

The owner's direction: a sentence is made into a small graph of its own words, and a word no lesson
knows is guessed from where it stands. First of three steps (this graph; then the same graph read
over ordinary text to count who stands where; then both together).

`relate.words(basic, text)` cuts every word by form: a taught connector after a noun, or a taught
ending after a stem. A stem is brought back to its first shape by the ways the taught words change
theirs (`basic.load_ends` now also returns these, 3 + 8 + 23 of them): 맡겨, 맡길 and 맡기면 give one
stem though no lesson has the word. A word with a connector hangs on the next word that can take
endings; any other word hangs on the next word. A cut that could go two ways is kept both ways.

`relate.placed(basic, question, explanations)` looks only at words no lesson knows. Such a word is
"same" when it is a word of a property's explanation in another shape, and "place" when it stands
where a word of the explanation stands: same connector, same head ("짐을 맡기면" next to "물건을
맡길 때"). In `answer._anchor` a placed word counts as met in `basic.ranked`, is named in the
proposal (`placed`: the word, how, the word it was taken for), and no longer stops the look-up as
an unknown noun. Place says what part a word plays, not what it means: nothing here is answered.

Not done: 을 and 를 are two connectors to this (the lessons do not say they are one); the bare
third stem (맡아, 알려) and ㅂ니다, ㅂ니까, ㄴ다 are still untaught; a word that stands in several
explanations (맡다 in three of eight) points at all of them alike.

Mechanism check only, on the sixth set, which was seen (the design was made with its questions in
view, so this says nothing about a new field): 23 of 46 natural, qualified, chain and no-answer
questions have a word placed. Verdicts: two held questions became right proposals, nothing else
moved, 0 wrong answers (`outside6_e2e_20261125/by_configuration/placed.txt`). Both came from the
unknown noun no longer stopping the look-up, not from the order of properties. Without the lessons
all six sets give the same lines as before. 133 checks pass. A seventh set is needed to measure it.

### Who stands where in ordinary text (2026-11-26, second step; built, no gain seen)

`relate.places(basic, sentences)` runs the same cut over ordinary sentences and counts, for every
place (connector, head), the nouns seen there; `probes/places_from_text.py` writes the table,
`relate.load` reads it, and the runner takes it as a fourth argument (`model['places']`). With it,
`relate.placed` has a third way, "like": ordinary text has a noun of the explanation in the very
place the unknown word stands in here, and the two share other places; the number (how many of a
thousand places of either both stand in) only orders. Without a table nothing changes.

Text used: the first 1,000,000 sentences of a Korean encyclopedia dump of 2023-11 that was already
on this machine (CC BY-SA / GFDL), 56 s, 278,234 places kept (a noun seen twice or more), 40 MB,
kept outside the repository (`.worktrees/corpus/places_wiki_ko_1m.tsv`). Nothing of it is committed.

The table itself looks right: (를, 마시) holds 차, 커피, 맥주, 홍차, 우유; (에, 살) holds 지역, 곳, 마을, 섬.

Mechanism check on the sixth set (seen): no verdict changed, and what "like" said was not right.
"짐을" came out like 돈, 날, 곳, 방법 and 사람, one for nearly every explanation, with numbers of
5 to 27 per thousand. Why: a common verb takes nearly any noun (돈을 두다, 곳을 두다), so the place
prunes little; common nouns share places with everything; everyday words are thin in this text
(가방 was kept in no place); and with no number above which a likeness counts, the faintest one
passes. The same was seen with the wording counts: standing near is not meaning the same.
Not tuned on this set. Left in, off unless a table is given. 134 checks pass.

### Places weighed (2026-11-26, the owner's request; a checkpoint of its own)

A place weighs one over the number of nouns seen in it. The likeness of two nouns is the weight of
the places both stand in, per thousand of the weight of all the places of either. Among properties
that meet as many pieces, `basic.ranked` puts first the one whose placed words are most like its
explanation's. Still no number above which a likeness counts, and nothing is answered.
Checkpoints to compare: `0d21618` (places counted, not weighed) and the one after it (weighed).

### Seventh set: the tax knowledge, questions by an examiner who saw no code (2026-11-26)

`probes/tax7_e2e_20261126/`. The knowledge is the 14 facts of `packs/tax_facts.json`, written out
as "X의 P는 V이다." by form. A fresh examiner, given only the facts (12 of them) and the kinds of
question, wrote the plain-words explanation of the 8 properties and 44 questions (8 direct, 8
short, 14 natural, 4 check, 10 without an answer). Both checkpoints were committed before the
items existed. The first run stopped on the form of the check items (my brief had asked for
예/아니오 where the runner wants the true value and `claim`); the items were put in that form by
rule and all runs repeated. No code was changed.

| configuration | right | assumed right | proposed right | proposed otherwise | held | held rightly | wrong |
| --- | --- | --- | --- | --- | --- | --- | --- |
| no lessons (`none`) | 7 | 8 | 10 | 1 | 8 | 10 | 0 |
| lessons, nothing placed (`taught`) | 7 | 8 | 12 | 1 | 6 | 10 | 0 |
| + unknown words placed (`placed`) | 7 | 8 | 12 | 1 | 6 | 10 | 0 |
| + places counted, `0d21618` (`counted`) | 7 | 8 | 12 | 1 | 6 | 10 | 0 |
| + places weighed, `a975516` (`weighed`) | 7 | 8 | 12 | 1 | 6 | 10 | 0 |

The last three give the same lines as `taught`, question for question. Placing an unknown word,
with or without ordinary text, weighed or not, changed nothing here. In all 44 questions no word
was the "same" as a word of an explanation, none stood in the "place" of one, and three were
"like" one (세금을 like 돈을 or 값에). The questions say 신고, 세금, 전화; the explanations say
알리다, 돈, 번호: they share neither words nor places. The two questions the lessons moved were
moved by the worked-out step, not by this.
Of 14 natural questions: 7 proposed right, 1 proposed for another property, 6 held (5 of them
before the look-up: "the text cannot be cut into known pieces").

## Ways of asking, listed per property (2026-11-26, built; measured once on an eighth set)

After a survey of how others close the gap between a user's words and stored words
(`reports/`, not committed): what works everywhere is pairs of "this wording asks for that", not
the form they are kept in. So the pairs are asked for when a field is prepared, and kept as edges.

- A property may come with `asked`: ways people ask for it, the thing written as X
  (`probes/teacher_brief_asked_ko.md`; the runner takes a file through `MARCO_ASKED`).
- `relate.asked` keeps every wording as it is (`exact`), cuts it into words by form and counts, per
  shape a word may come back to, in how many wordings of each property it stood (`words`). A
  wording listed under two properties points at neither and is named (`clash`).
- `relate.heard`: a question that is a listed wording word for word points at its property; a word
  of the question points at the properties whose wordings it stood in, with a number: of a
  thousand wordings it stood in, how many were that property's.
- In `answer._anchor` these words count as met in `basic.ranked` beside the taught ones. Where the
  first property is ahead of the second (pieces met, then the numbers) it alone is put to the
  user. Everything here is a proposal: nothing is answered, and no number says a thing is right.
- Without `asked` nothing changes (the sixth and seventh sets give the same lines). 137 checks pass.

Eighth set, `probes/tax8_e2e_20261126/`: the tax knowledge and the seventh set's explanations;
60 new questions by a second examiner (30 natural, 14 without an answer); 156 ways of asking by a
teacher (160 written, 4 left out by the form rule for using another word of the property). Neither
saw the code or the other's text. Code frozen before both; one run each; nothing changed after.

| configuration | right | assumed right | proposed right | proposed otherwise | held | held rightly | wrong |
| --- | --- | --- | --- | --- | --- | --- | --- |
| no lessons | 3 | 4 | 10 | 1 | 29 | 13 | 0 |
| lessons | 3 | 4 | 21 | 1 | 18 | 13 | 0 |
| lessons + ways of asking | 3 | 4 | 24 | 2 | 14 | 13 | 0 |

Natural questions (30): proposed right 3 → 14 → 17; with the ways one more is proposed for another
property (the rate asked as "세금이 몇 프로 붙는", proposed as 과세기간). No question was a listed
wording word for word. The 12 natural questions still held never reached this step: each has a
word that shares letters with three property words (신고해야 with 신고횟수, 신고기간, 신고기한), and
the look-up gives up there before the listed ways are asked. Seen after the run; not changed.
Teacher and examiner are the same kind of writer, so their wordings may be nearer to each other
than a real user's would be: the gain is an upper reading.

### Letters shared with three property words no longer stop the look-up; ninth set (2026-11-26)

One change after the eighth set: where an unread word shares letters with three property words or
more, `answer._anchor` used to return nothing. With taught words in the model it now drops those
pointers and lets the taught words and the listed ways of asking decide. 138 checks pass; runs
without lessons are unchanged.

Ninth set, `probes/tax9_e2e_20261126/`: the tax knowledge, 60 questions by a third examiner told
to write as different people (30 natural, 14 without an answer), the same 156 ways of asking.
Code frozen before the items; one run each; `asked_before_fix` is a copy with the change taken out.

| configuration | right | assumed right | proposed right | proposed otherwise | held | held rightly | WRONG |
| --- | --- | --- | --- | --- | --- | --- | --- |
| no lessons | 4 | 5 | 8 | 0 | 28 | 14 | 1 |
| lessons | 4 | 5 | 23 | 4 | 13 | 10 | 1 |
| lessons + ways of asking, before the change | 4 | 5 | 28 | 4 | 8 | 10 | 1 |
| lessons + ways of asking | 4 | 5 | 28 | 4 | 8 | 10 | 1 |

- **A wrong answer, in every configuration, the one without lessons included.** "사업자등록
  신청기한이 사업개시일부터 20일 이내 맞나요?" was answered "아니다: 사업개시일부터20일이내". The
  question writes the value with spaces; the claim was compared with the stored value letter for
  letter and denied. Older than today's work (the code of `2c3944f` does it too); no earlier set
  had a check question with a spaced value. Not fixed after the run.
- Natural questions (30): proposed right 2 → 17 → 22. The ways of asking gave 5, none otherwise.
- The change itself moved nothing on this set: the two last rows are the same, line for line.
  The 8 natural questions still held leave the look-up elsewhere (an unknown word in front of a
  connector; no fact left that fits). On the eighth set, which was seen, the change moves natural
  17 → 24 and makes 2 more questions without an answer into proposals: a mechanism check only.
- With lessons, 4 of 14 questions without an answer are put to the user as another property of
  the same thing ("일 년에 몇 번 신고해야 해요" of a thing that has only 신고기간). Without lessons
  none is. Hearing more also proposes more where nothing is known.

### A stated value is denied only when it is plainly another value (2026-11-26)

The wrong answer of the ninth set came from `_answer_read`: what stands in front of the claim word
is a stretch of text ("사업개시일부터 20일 이내", "15%라던데", "연2회라고 들었는데"), and it was
compared with the stored value letter for letter; any difference was answered "아니다". So a true
value written with spaces, with words after it, or in other words would all have been denied.

Now (`answer._claim_holds`): it holds when it is the value, spaces apart. It is denied only when
it is plainly another value: the same shape with other numbers, or a name or value the knowledge
has. Anything else is a hold that says so ("neither confirmed nor denied"): saying no is an answer
too. The change after the eighth set (letters shared with three property words) was taken out
again: it did nothing on the ninth set. 138 checks pass; one older check expected "만원이 맞나?" to
be denied against 천원 and now expects a hold.

Effect on sets already run (all seen): of nine sets only the ninth changes. Its wrong answer is
now "맞다"; two right denials ("연2회라고 들었는데", "15%라던데") became holds.

Two new sets of 46 check questions each, by two more examiners, old code (`a975516`) and new code
run once each:
- `probes/tax10_e2e_20261126/`: free wording. All 46 held, before and after. The examiner left the
  connector off the property ("상담전화 126 맞죠?") and no such question is read at all, so the
  rule was never reached. Nothing wrong, and nothing learned about the rule.
- `probes/tax11_e2e_20261126/`: the front of the question fixed as "X의 P가/는", the value written
  freely. Before and after are the same lines: right 13, assumed right 3, proposed otherwise 2,
  held 28, wrong 0. Values written freely (20) and questions asked by denial (6) were all held by
  the reader before the rule.
So on new questions the rule has not yet been seen to change a verdict; what it is known to do is
remove the one wrong answer found. 92 new check questions, 0 wrong either way.

## Every checkpoint on the tax knowledge (2026-11-26), and a correction

**Correction first.** Several "before" runs of 2026-11-25 and 26 were made from a copy of
`experiments/graph_weighted_acquisition` outside the repository with the repository appended to
the path. `experiments` is a package there, so Python took the working tree's code and the copy
was never used: those runs compared the new code with itself. Wrong, and withdrawn:
- "the eleventh set is the same before and after the claim rule". In a clean copy of `a975516`
  the eleventh set gives **8 wrong answers** (every one a true value written freely and denied:
  "여섯 달이 맞죠?" → 아니다) and the new code none.
- "the change after the eighth set did nothing on the ninth". Measured properly on the twelfth
  set, which did not exist when it was made: proposed right 24 → 29, and two more questions without
  an answer are put to the user (held rightly 12 → 10). It stays taken out until the owner decides.
- The seventh set's `counted` output and the sixth-set baseline comparison of 2026-11-25. Redone
  for the seventh set: `0d21618` and `a975516` do give the same lines there.
From now on another checkpoint is run only in a git worktree of that commit, and the run asserts
where the code was imported from.

**The table.** Six sets on the tax knowledge (seventh to twelfth, 326 questions: 104 natural, 54
without an answer, 70 checks), each checkpoint with what it could use at the time. The twelfth set
(70 questions, a fourth examiner) was written after the last commit. Earlier sets were seen before
`c12ae76`, and the claim rule was made after the ninth.

| checkpoint | what it adds | right | assumed right | proposed right | proposed otherwise | held | held rightly (of 54) | WRONG |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `ded9098` | structured look-up, reader rules | 38 | 0 | 0 | 0 | 225 | 54 | 9 |
| `728dd70` | word kinds, open roles, chains | 38 | 0 | 0 | 0 | 225 | 54 | 9 |
| `05955b1` | unread questions put to the knowledge | 38 | 25 | 31 | 3 | 166 | 54 | 9 |
| `2c3944f` | question read with the knowledge | 38 | 29 | 38 | 6 | 154 | 52 | 9 |
| `ad18b1e` (set aside) | basic concepts | 38 | 29 | 40 | 6 | 152 | 52 | 9 |
| `7be51fb`, `8f58739` (set aside) | text counts; dictionary bridge (their data is gone) | 38 | 29 | 38 | 6 | 154 | 52 | 9 |
| `53c1e5b` + lessons | taught basic words | 38 | 29 | 45 | 6 | 147 | 52 | 9 |
| `0d21618` + lessons, places | worked out by degree, sentence relations | 38 | 29 | 68 | 9 | 124 | 49 | 9 |
| `a975516` + lessons, places | places weighed | 38 | 29 | 67 | 9 | 125 | 49 | 9 |
| `c12ae76`, no lessons | claim rule alone | 27 | 29 | 38 | 6 | 174 | 52 | 0 |
| `c12ae76` + lessons | | 27 | 29 | 67 | 9 | 145 | 49 | 0 |
| `c12ae76` + lessons, ways of asking | ways of asking | 27 | 29 | 82 | 12 | 129 | 47 | 0 |
| `c12ae76` + lessons, vector trial | a vector model on the hearing side (crash fixed, not committed) | 27 | 29 | 83 | 19 | 124 | 44 | 0 |

All nine wrong answers of the older checkpoints are true stated values denied (eight in the
eleventh set, one in the ninth). The claim rule removes them and turns eleven right denials into
holds. Natural questions proposed, assumed or answered right, of 104: 0, 0, 9, 16, 18, 16, 23,
45, 44, 16, 44, 58, 59 in the order of the rows. The vector trial crashed on 46 questions at
`c12ae76` (a row without the key the new code reads); fixed in the working tree and rerun.
