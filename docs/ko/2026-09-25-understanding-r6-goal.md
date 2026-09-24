# Goal G6: understanding, round 6 — the exam's own classes, read from the ledger

Model: Opus 5.5, effort high. Read `docs/ko/2026-09-22-freeze-decision.md` first
(the exam rule and the standing decision: no token-based model in the runtime),
then `docs/ko/2026-09-25-understanding-r5-goal.md` and G5's row in the freeze
queue, `docs/requests/G5-2.md` (items 3 to 11 are yours), `docs/requests/W5-3.md`,
`data/benchmarks/dialogues_dev5/build.py` and `causes.py`. Written 2026-09-25.
Own checkout, branch `understanding-r6`. Runs alongside W6 (realizer round 6),
which owns `marco/language/` and the reply-return sites.

## What the owner found, and why the dev sets did not transfer

Rounds 4 and 5 met their own check-half targets (66.7% then 83.7% answerable)
and moved the frozen exam only from 21 to 40 to 45 of 108. The owner recorded
the frozen dialogues through the ledger (owner-run; you never do this) and read
the failing turns at class level. The finding: the dev generator does not
produce the exam's forms, in a handful of specific ways. The classes below are
the whole gap. Counts are frozen turns per class; every class must be present
in dev set v6 in both languages, at least 12 dialogues per class per language,
and the generator's prompts and the checker must be changed so that they
occur. **No sentence from the exam appears here or anywhere; these are classes.**

### A. Statements the reader does not record (29 of 150; each blocks every later question)

1. **Counts as words, not digits.** English number words in transfer and
   ownership statements ("one" to "twenty-four", "some ... six, to be exact");
   Korean native numerals with counters (한·두·세·네·여섯·스무 + 개·권·장·묶음·자루)
   in transfer statements. The generator wrote digits almost always and the
   checker accepted only digits; v6 phrases counts as words in at least half of
   the statements, and the checker accepts either form.
2. **English double-object transfer** ("gave RECIPIENT N THINGS", no "to") and
   **split particle verbs** ("handed N THINGS over to R"), plus "transferred",
   "returned", "sent", "passed", "left N at PLACE".
3. **Partitive pronoun objects** in transfers and use-ups: "one of them", "N of
   them", 그중 하나, 그중 N개, "used three of them for ...", 그중 N개로 만들었다.
4. **A count given in a following fragment**: "X has some Y. N, to be exact."
   / "X한테 Y이 있어. 여섯 개야." / "X가 Y한테 Z를 줬어. 두 개."
5. **Korean transfer verbs and compounds**: 나눠 주다, 빌려주다, 보내다, 맡기다 (leave
   at a place), 싣고 있다 (carry), 주었다 (plain past formal), and the subject
   omitted in a second sentence ("그리고 R에게 N개를 주었다").
6. **Holder forms** still unread: a title after a name with 에게는 and the thing
   omitted ("X 과장에게는 두 개가 있습니다"); a job-title apposition before a name
   ("택배 기사 X 씨는"); a relational noun with 도 and a vague count ("X 친구 Y도
   Y을 가지고 있어요"); "For the event, X is responsible for N" (fronting +
   responsible-for + number word); a place as recipient ("left N at the shop" /
   "편의점에 맡겼습니다").

### B. Questions the reader does not read (29 of 63 held answerable turns)

7. **Leftover and remaining forms**: "does X have left", "are left with X",
   "left for X", "remain with X", "X에게 남은 Y은 몇 개인가", "Y 몇 개 남았어",
   "X 님께 남은 Y은 몇 권입니까".
8. **Aspect and time adverbs in questions**: "at the moment", "now", 이제, 지금
   ("X는 이제 몇 개야?", "그럼 X는 지금 몇 개예요?").
9. **Other question predicates**: "has X got", "is X responsible for", "맡고
   있습니까", "How many bundles" / "몇 묶음입니까", "모두 몇 개입니까", "combined" /
   "the two of them in total", "둘 중에 누가 더 (many/few)" asked of two named holders.
10. **Topic-switch ellipsis**: "What about X?", "And X?", "And in PLACE?", "And
    THING?", "X는요?", "X는?", "THING은?", "PLACE는 어떻습니까?" (the question of the
    previous turn asked again about a new holder, place or thing).
11. **Referent repair with the question in the same turn**: "I mean X. How many
    does X hold?", "It's X. How many does X have?", "X 말입니다. 몇 묶음입니까?",
    "X요. X는 몇 개예요?"; and bare-name repairs as a turn ("X요.", "X 님입니다.",
    "X, I mean.", "X is the one I mean.") followed by the question next turn.
12. **Cross-language turns** (4): a question in the other language inside a
    dialogue; read it with the other pack and answer in the question's language.

### C. Why questions that restate the fact (all 26 why turns of the exam are held)

13. "Why does X have N?", "Why does X end up with N?", "What is the reason X has
    N?", "Why is that number N?", a why about how the last answer came about, with no holder or number, "Why do I only
    have N?", "왜 X가 N개야?", "왜 N개예요?", "X의 Y이 N개가 된 까닭은 무엇인가?", the same in Korean, "X Y가 왜 N개가 되었습니까?". Today the reader knows bare "왜?" and
    "왜 그렇게 됐어?". A why that names a holder and a number is a why about that
    holder's current count: resolve the fact, then explain it (the realizer's
    explain plans and the trace chain already say it). The why label is reported
    apart from the 108, but MARCO 1's definition includes why, and 0 of 26 is
    the worst number on the exam.

### D. From G5-2 and W5-3

14. Items 3 to 11 of `docs/requests/G5-2.md`: one-syllable names before 은/는,
    N밖에 없다 as an only-count, the elliptic count with a stacked place case, a
    titled possessor before a relation and a name, the English possessive
    determiner before a numeral, the ranking of the polite-ending topic frame,
    the two word orders taken out in round 5, 도 in a second clause. And W5-3
    (b): the engine's hold names a different unread statement from run to run;
    make it a function of the conversation only, with a two-orders test.

## Definition of done — all eight, measured

G6.0 **Generator and checker.** `data/benchmarks/dialogues_dev6/build.py`: prompts
     ask for counts as words at least half the time, for the question forms of
     B by class, for topic-switch ellipsis turns, for repair-plus-question turns,
     for fragment counts, for double-object and particle-verb transfers, for
     why-with-fact turns after an answer, and for one cross-language question in
     10% of dialogues; the checker accepts number words and native numerals and
     refuses a holder the scenario does not name. Class tags per dialogue.

G6.0b **Withdrawn evidence: the ledger says 5, the gate says 0.** `python -m
     marco.trace stats` on dev set v4's check half reports 3 Korean and 2 English
     answered turns whose why chain uses withdrawn evidence, while the gate's
     retracted-evidence check reports 0 on the same turns. Find which is right:
     either the ledger's check counts a superseded event that the answer did not
     rest on (then fix `marco/trace/stats.py`, yours for this item, and add the
     case to its tests), or the answer really rests on a withdrawn value and the
     gate's check is too narrow (then fix the reader and write the gate's gap as
     `docs/requests/G6-1.md` for the owner). Report which, with the five turn
     ids of dev4.

G6.1 **Dev set v6.** 100 or more dialogues per language, every class 1 to 13 in
     at least 12 dialogues per language, build and check halves disjoint in
     names, items and places, **both check halves phrased and scored before the
     first fix**. Zero sentence overlap with dev to dev5 (test). Never open the
     frozen sets; drop nothing from `FROZEN`.

G6.2 **Cause tables** from the ledger on both halves before any fix, per class.

G6.3 **Fixes, statements first (A), then questions (B), then why (C), then D**,
     as declared classes, batches of one class, check halves scored after every
     batch, the guard unchanged (stop fixing at a 15-point gap; safety only after).

G6.4 **Why with a restated fact**: 20 test cases per language covering the forms
     of class 13; each explains the named holder's count through the existing
     explain path, or asks which holder when the name matches two.

G6.5 **Targets on the check halves (v4, v5, v6 together):** records 94% or
     higher, answerable 85% or higher, why 80% or higher, 0 wrong, 0 violations,
     gap 15 or less. If unreachable, the blocking class with its count.

G6.6 **Nothing regresses:** repair 19/19; r1 to r5 tests; round-3 check half 98/106
     or better; v4 and v5 check halves at their round-5 numbers or better;
     `tests/language/`, seam, composition and trace tests; full parallel suite
     at main's count with the same known failures.

G6.7 **Determinism**: the two-orders test of D passes; a dialogue recorded twice
     gives identical events after masking, both languages.

G6.8 **Hand-off:** the commit hash and the tables. The owner scores the frozen sets.

## Owns

Same as G5: `frame_induction.py`, `language_components.py`, `relational_semantics.py`,
`hangul.py`, `engine.py`, `explain.py`, `reasoning_context.py`, `state_engine.py`,
`pack_model.py`, `styles/*.json`, `data/benchmarks/dialogues_dev4/`, `dev5/`, `dev6/`,
`tests/test_understanding_r6.py`, `tests/` files for those modules, the emission
sites in `marco/trace/drive.py` and `from_turn.py`, the `--dataset` handling in
`bench/dialogue_gate.py`. W6 owns the reply-return sites and the `meaning` blocks
in `engine.py`, `reasoning_context.py`, `views/kgpack_ui.py`, and all of
`marco/language/`. Requests to `docs/requests/G6-<n>.md`.

Must not touch: `marco/language/`, `mco/`, `alma_*`, the gate scorers beyond
`--dataset`, any frozen area. `build.py` never reads `data/benchmarks/dialogues_v1/`
or `reasoning_v1/`.

## Working conditions

Commit by name, owner as author, no co-author lines, no assistant or model name
in commits or product files. `python`, not `python3`; `KG_ENCODER=문자`. Commit
after every batch. The phrasing model runs only while building the set. Do not
push. Report tersely.
