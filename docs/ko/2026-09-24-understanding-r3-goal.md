# Goal G3: understanding, round 3 — the exam is the language, not the generator

Model: Opus 5.5, effort high. Read `docs/ko/2026-09-22-freeze-decision.md` first.
Written 2026-09-24. Own checkout, branch `understanding-r3`. Runs alongside W2
(realizer round 2), which owns `marco/language/` and a few reply-return sites.

## Facts from rounds 1 and 2 (owner-run, `docs/ko/dialogue-gate-2026-09-22/`)

- Frozen gate: baseline 3/108, round 1 19/108, **round 2 21/108 (19.4%)**,
  Korean 10/54, English 11/54, record turns 81/150. Round 2's own held-out half
  scored 92%. Two rounds in a row passed their own exam and failed the real one.
- Owner-side diagnosis, at the class level, no sentences:
  1. **Vocabulary.** 198 of the 240 failing frozen turns contain a word that
     appears nowhere in any dev set or pack: everyday item nouns, place nouns,
     and person names, Korean and foreign, in Hangul and Latin script. The dev
     generators draw from a small declared item list, so no rule ever met an
     unknown noun.
  2. **First statements.** 14 of 52 dialogues fail on their very first
     statement; 10 of those 14 first statements carry two clauses, two facts.
     After a missed statement every later question holds, so one miss costs a
     whole dialogue.
  3. **Two gate-3 violations, new in round 2:** a numeric answer was spoken
     under a clarify act (the engine was asking, the reply answered), and a
     corrected event's old value was reused by a later question.
- Reasoning is not the problem: the frozen reasoning set scores 146/149 parsed,
  0 wrong. Whatever is understood is reasoned correctly.

## Exam rule — breaking it fails the goal

Never open `data/benchmarks/dialogues_v1/` or `data/benchmarks/reasoning_v1/`;
never run a scorer against them. From the round reports read only `gate`,
`by_language`, `by_category`, `other_labels`. `dialogues_dev/` and
`dialogues_dev2/` are seen: regression only, never tune on them.

## Definition of done — all nine, measured

G3.0 **Violations first, two commits, before any rule work.**
     (a) A clarify or ask act never carries a value: if the engine is asking,
     the reply asks and nothing is answered. Injection test: 10 cases where a
     value is available but the act is clarify, all held or asked, none answered.
     (b) After a correction, the retracted value is unreachable for every later
     question: counts, totals, comparisons, why, and after restart. Injection
     test: 10 corrected dialogues, the old value never appears in any later reply.
     Both become permanent tests in `tests/test_understanding_r3.py`.

G3.1 **Open vocabulary by rule, not by list.** An unknown noun is read as an
     item or a place from its morphology and position, in both languages:
     English regular plurals by rule (-s, -es, -ies, and a declared list of the
     common irregulars), Korean noun + counter and noun + particle by rule,
     person names by position, honorific and name-suffix rules, Latin-script
     names inside Korean text. Probe: `data/benchmarks/vocab_probe/` with at
     least 300 item nouns, 100 place nouns and 200 person names taken from a
     named public word list (source cited in the file), never from any dialogue
     set; each used in one statement and one question per language by a
     generator. Target: 95% recorded and answered. The probe words must not be
     added to the packs; the rule must read them.

G3.2 **Multi-clause statements.** Two or three facts in one statement, joined
     by comma, and, 그리고, -고, -며, a relative clause, or a second holder after
     the first. Probe: 200 generated statements varying join type, clause order
     and holder count; every fact recorded. Target 90%.

G3.3 **Dev set v3** `data/benchmarks/dialogues_dev3/`: at least 80 dialogues,
     40 per language. Vocabulary sampled from the G3.1 lists, never the packs'
     declared example items. At least half the statements multi-clause; at
     least half the dialogues open with a statement carrying two or three facts.
     **Build and check halves come from different generator plans and disjoint
     vocabulary halves** (no item, place or name shared), seed recorded. Zero
     full-sentence overlap with v1, dev, dev2.

G3.4 **Cause tables** on the build half for held answerable turns and failed
     record turns, then fixes largest first, statements before questions. The
     anti-hardcoding guard applies: declarations over code; every rule names the
     closed grammar class it covers, entered in full; declaration-to-code line
     ratio per commit; check-half numbers after every batch; if check trails
     build by more than 15 points, stop and report before continuing.

G3.5 **Targets on the check half**, disjoint vocabulary, never tuned on:
     answerable 60% or higher, record turns 85% or higher, 0 wrong, 0 gate-3
     violations. Build half 75% or higher, 0 wrong. If a target cannot be
     reached, name the blocking cause and its count with evidence.

G3.6 **Declare the kinds the packs cannot say yet** (from
     `docs/requests/F2-2.md`): English negation of possession and transfer,
     comparisons with fewer and equal, before/after questions. Class-level
     declarations with tests in both languages. Do not read the reasoning set.

G3.7 **Pack string:** in `styles/한국어.json` the repair-note label 수선 becomes
     수정 in every template that speaks it (the `repaired`, `repair_*` and
     `explain_repairs` keys). Owner's word. One commit, no other template change;
     W2 decides what is spoken versus traced.

G3.8 **Nothing regresses.** `tests/test_repair_and_english.py` 19/19;
     `tests/test_understanding_r1.py` and `_r2.py` pass; `tests/language/` and
     the seam test pass; the parallel full suite at main's pass count with the
     same three known failures; round-1 dev set at 66/96 or better and round-2
     check half at 48/52 or better, run once at the end as regression.

G3.9 **Hand-off:** the commit hash to score. The owner runs the frozen
     dialogues, the reasoning set and the composition gate, and records round 3.

## Owns

`marco/language/frames.py`, `language_components.py`, `relational_semantics.py`,
`marco/language/hangul.py`, `engine.py`, `marco/runtime/explain.py`, `marco/reasoning/context.py`,
`marco/reasoning/state.py`, `pack_model.py`, `styles/*.json`,
`data/benchmarks/vocab_probe/`, `data/benchmarks/dialogues_dev3/`,
`tests/test_understanding_r3.py`, `tests/` files for those modules, the
`--dataset` handling in `bench/dialogue_gate.py`.

Carve-out: W2 owns, in `engine.py`, `marco/reasoning/context.py` and
`views/kgpack_ui.py`, only the reply-return sites where a hold or clarify reply
is produced without `realize()`, and the result-building `meaning` blocks. You
own parsing, repair, matching, and correction logic in those files. If a fix
needs one of W2's sites, write `docs/requests/G3-<n>.md` instead.

Must not touch: `marco/language/`, `mco/`, `alma_*`, `bench/reasoning_gate.py`,
`bench/composition_gate.py`, any frozen area.

## Working conditions

Commit by name, owner as author, no co-author lines, no assistant or model name
anywhere. `python`, not `python3`. `python -m pytest -q` is parallel by
`pytest.ini`. Do not push. Report tersely: G3.0–G3.9 each done or not with
numbers, the probe results, both cause tables before and after, build and check
side by side per batch, the rule table (class, declaration or code, motivated-by
count, check turns fixed), and the commit hash to score.
