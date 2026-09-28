# Goal G4: understanding, round 4 — natural language, not templates

Model: Opus 5.5, effort high. Read `docs/ko/2026-09-22-freeze-decision.md` first.
Written 2026-09-24. Own checkout, branch `understanding-r4`. Runs alongside W3
(realizer round 3), which owns `marco/language/` and the reply-return sites.

## What three rounds taught

| Round | Own held-out check | Frozen gate |
| --- | --- | --- |
| 1 | 68% (no split) | 19/108 |
| 2 | 92% | 21/108 |
| 3 | 89%, disjoint vocabulary | 21/108 |

Round 3 fixed every violation and every wrong answer (0 and 0 now), and passed
its 1,200-word and 200-statement probes, and the frozen number did not move.
The owner then read the failing frozen turns. The gap is not vocabulary and not
clause count. **The frozen dialogues are natural adult language; every dev set
so far was template output.** Classes seen on the frozen set, described here
at the class level only:

- **Zero and vague quantities:** "has no X at all", "한 X도 없다", "has some X",
  a count given only in a following sentence, "only has X, N of them", "also has some X".
- **Transfer and possession verbs beyond give/have:** lend, pass, hand over,
  return, send, transfer, leave at, move (also passive: "N were moved from A to
  B"), give back, use up ("used three of them for …"), hold, carry, be
  responsible for; Korean 빌려주다, 넘기다, 돌려주다, 보내다, 가지고 있다,
  formal 있습니다 / 없습니다.
- **Holders that are not bare names:** first person ("I", "my roommate"),
  relational nouns ("A's cousin B", "A's friend B"), titles ("Mr. A", "Ms. B",
  "A 씨"), appositions ("the courier, Mr. A"), and places as holders ("the
  north warehouse holds N", "are in the south warehouse", "left N at the shop").
- **Fronting and discourse adverbs:** "To B, A passed N …", "For the event,
  …", "Then …", "… , apparently", "at the moment", "now", "left".
- **Partitives and anaphora:** "two of hers", "one of them", "N of them",
  "the same X" / "같은 X", "gave them to B, not C".
- **Question forms:** "has X got", "does X have left", "how many do the two
  of them have in total", "how many are in <place> now", "how many does X hold".
- **Referent repairs as their own turns:** "I mean X.", "X, I mean.", "X is who
  I meant.", then the question.
- **Korean register:** polite -어요 / -습니다 throughout, -씨, -한테 and -에게는,
  counters 자루 / 묶음 / 장 / 개, clause order with the count phrase first.

Because one missed statement holds every later question, the record rate (82 of
150 statements) caps the answerable rate. Statements first, again.

## The change in method: dev data phrased by a language model, truth from a scenario

Templates cannot produce the classes above. So dev set v4 is built in two steps:

1. **Scenario generator** (yours, code): holders (persons with names, titles,
   relational descriptions, first person, places), items with counts (including
   zero and vague-then-exact), events (the verb classes above), corrections,
   referent repairs, questions with their expected semantic answers. The
   scenario is the ground truth; nothing in it is prose.
2. **Phrasing model** (local, Qwen2.5-7B-Instruct 4-bit through `mlx-lm`,
   already installed by goal C1; `bench/answerers/qwen.py` shows how it is
   loaded): given one scenario and a register instruction, it writes the
   dialogue turns as natural sentences, in Korean or English, at temperature
   0.7, several variants per scenario. A checker (yours, code) verifies that
   every number, name and item of the scenario appears in the phrasing and
   nothing else does; failed phrasings are discarded, never edited by hand.
   The model is a data tool at development time; the runtime has no model.

This produces the frozen set's kind of language without anyone reading the
frozen set. The scorer already accepts semantic expectations, so the scenario's
answers score the dialogue as before.

## Exam rule

Never open `data/benchmarks/dialogues_v1/` or `reasoning_v1/`; never run a
scorer against them. Earlier dev sets are seen: regression only.

## Definition of done — all eight, measured

G4.1 **Scenario generator + phrasing pipeline** as above, committed under
     `data/benchmarks/dialogues_dev4/` with `marco/knowledge/ingest/text.py`, the prompts, the checker,
     and the seed. At least **160 dialogues, 80 per language**, each class in
     the list above present in at least 10 dialogues per language (a script
     counts by scenario tags). Build and check halves by scenario, disjoint in
     names, items and places, and phrased at different sampling seeds. Zero
     full-sentence overlap with every other dialogue file.

G4.2 **Cause tables** on the build half for failed record turns and held
     answerable turns, classes from the list above plus any new one, counts
     summing to the totals.

G4.3 **Fixes, statements first, largest class first.** Every fix is a rule or a
     declaration naming the closed class it covers in full: the verb lexicon of
     transfer and possession in both languages as a declared table; zero and
     vague quantity forms; holder forms (first person, relational nouns, titles,
     appositions, places); fronted phrases and discourse adverbs skipped by
     rule; partitives resolved to the last mentioned item; question forms.
     The anti-hardcoding guard applies unchanged (declarations over code,
     class named, ratio per commit, check after every batch, stop if check
     trails build by more than 15 points).

G4.4 **Targets on the check half:** record turns **90% or higher**, answerable
     **70% or higher**, 0 wrong, 0 violations. Build: 85% answerable, 0 wrong.
     If unreachable, the blocking class with its count and evidence.

G4.5 **Referent repairs and pronoun corrections:** "I mean X" forms in both
     languages re-bind the pointer of the previous question and answer it;
     "gave them to Y, not Z" corrects the recipient. Tests with 10 cases each.

G4.6 **Places as holders:** a place can hold items, receive and give them, and
     be asked about ("how many are in <place> now"). Both languages. Tests.

G4.7 **Nothing regresses:** repair 19/19; r1, r2, r3 tests; `tests/language/`,
     the seam and composition tests; full parallel suite at main's count with
     the same known failure; the round-3 check half at 94/106 or better; both
     probes at their final numbers.

G4.8 **Hand-off:** the commit hash. The owner scores the frozen sets.

## Owns

Same as G3: `marco/language/frames.py`, `language_components.py`,
`relational_semantics.py`, `marco/language/hangul.py`, `engine.py`, `explain.py`,
`reasoning_context.py`, `state_engine.py`, `pack_model.py`, `styles/*.json`,
`data/benchmarks/dialogues_dev4/`, `tests/test_understanding_r4.py`, `tests/`
files for those modules, the `--dataset` handling in `bench/dialogue_gate.py`.
The carve-out with W3 is the same as with W2: W3 owns the reply-return sites
and the result-building `meaning` blocks in `engine.py`, `reasoning_context.py`
and `views/kgpack_ui.py`; you own parsing, repair, matching and correction
logic. Requests to `docs/requests/G4-<n>.md`.

Must not touch: `marco/language/`, `mco/`, `alma_*`, the gate scorers, any
frozen area. The phrasing model is used only by `marco/knowledge/ingest/text.py`, never imported by
product code.

## Working conditions

Commit by name, owner as author, no co-author lines, no assistant or model
name in commits or product files (the phrasing model's id belongs in
`marco/knowledge/ingest/text.py` and the report as data). `python`, not `python3`. Keep the phrasing
model under 6 GB resident and run it only while building the set. Do not push.
Report tersely: G4.1–G4.8 with numbers, class coverage table, both cause tables
before and after, build and check per batch, the rule table, declaration-to-code
totals, and the commit hash.
