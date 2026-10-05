# Goal W2: realizer round 2 — say everything, name the subject, clean the voice

Model: the owner's chat model, effort high. Read `docs/ko/2026-09-22-freeze-decision.md` first.
Written 2026-09-24. Own checkout, branch `realizer-r2`. Runs alongside G3
(understanding round 3), which owns the parsing side.

## Facts (owner-run, 2026-09-24, `main` at ff8db40)

- Composition gate on the frozen 52 (`docs/ko/dialogue-gate-2026-09-22/composition-round2.json`):
  **207 of 340 spoken replies composed**. Answers 22/23, records 83/84, asks
  6/6. **131 hold replies passed through with no realizer report**: they are
  produced on paths that never call `realize()`. Gate condition 5 needs 340/340.
- `docs/requests/G2-1.md`: answers drop the owner the question named, so an
  answer such as a bare count with no holder was scored unverifiable. The
  realizer's `answer_ellipsis` and the `keep` lists decide this.
- Owner's fluency judgement on W1's 25-reply sample: natural, except three
  things. The `[수선]` repair note spoken at the start of Korean replies. Rule
  ids such as `(count_remove)` spoken inside why-answers, in both languages. A
  bare 왜? / Why? that holds where the long form works.
- The fixed 7-step dialogue and the 20 phrasings are the only sets you may run
  freely; `dialogues_dev/` and `dialogues_dev2/` may be used for the
  composition count (they are seen data, fine for this goal). Never open
  `data/benchmarks/dialogues_v1/` or `reasoning_v1/`.

## Definition of done — all seven, measured

W2.1 **Every spoken reply goes through `realize()` with a meaning.** Find every
     site that returns a hold, clarify or refusal reply without calling the
     realizer (start with `views/kgpack_ui.py`, the manager and routing paths in
     `engine.py`, and `marco/reasoning/context.py`). Give each a language-free
     meaning (`act`, `reason`, the user's words or ids it needs) following
     `marco/language/realizer/meaning.json`, and route it through the seam.
     Measure with `bench/composition_gate.py` on the 7-step, the 20 phrasings,
     `dialogues_dev/` and `dialogues_dev2/`: 100% composed on the first two, at
     least 98% on the dev sets, with every remaining pass-through listed by
     site. The owner then runs the frozen set.

W2.2 **Answers name their subject** when the question names no holder, several
     holders, or asks a total or a comparison. Ellipsis stays only when the
     question names exactly one holder. Tests on the 7-step and your own
     sentences in both languages; the unverifiable class disappears.

W2.3 **Why-answers in words.** Rules are said in the language ("the giver loses
     that many", "주는 쪽에서 그만큼 뺍니다"), never as ids in parentheses. The
     ids stay in the trace. Both languages, tests.

W2.4 **Repair notes leave the spoken reply.** The reply says at most one short
     clause of what was read ("I read X as Y" / the Korean equivalent), or
     nothing when the reading is unchanged in meaning; the full note (rule,
     cost) goes to the trace. A follow-up "what did you change?" / "뭘 고쳤어?"
     returns the full note. Use the pack's own strings (G3 renames the Korean
     label to 수정 in `styles/한국어.json`; you never hardcode the word).

W2.5 **Bare 왜? and Why?** work like the long form when a previous turn exists.

W2.6 **Fluency sample 2:** 40 random composed replies from `dialogues_dev2/`,
     20 per language, in `marco/language/measurements/fluency-sample-2.md` with
     an empty judgement column for the owner.

W2.7 **Nothing regresses.** `tests/language/` (all R tests), the seam test,
     `tests/test_composition_gate.py`, `tests/test_reasoning_gate.py`, the
     parallel full suite at main's pass count with the same three known failures.

## Owns

`marco/language/**`, `tests/language/`, `tests/test_language_seam.py`,
`tests/test_composition_gate.py`, `marco/language/measurements/`. Carve-out in
`engine.py`, `marco/reasoning/context.py`, `views/kgpack_ui.py`: only the reply-return
sites that produce a hold, clarify or refusal without `realize()`, and the
result-building `meaning` blocks. Nothing else in those files; G3 owns their
parsing, repair, matching and correction logic. Do not edit `styles/*.json`;
if a template string must change, write `docs/requests/W2-<n>.md` for G3.

Must not touch: `mco/`, `alma_*`, `bench/reasoning_gate.py`,
`bench/dialogue_gate.py`, any frozen area.

## Working conditions

Commit by name, owner as author, no co-author lines, no assistant or model name
anywhere. `python`, not `python3`. Do not push. Report tersely: W2.1–W2.7 each
done or not with numbers, every routed site as file:line, the composition
numbers per set, and the commit hash.
