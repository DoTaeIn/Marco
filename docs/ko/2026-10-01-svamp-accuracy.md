# Outside accuracy check: SVAMP word problems (2026-10-01)

The frozen exam measures MARCO on dialogues written in its own forms. This is the first check on text
written by other people for another purpose: the 726 one-unknown problems of SVAMP (MIT licence), kept
outside the repository under `data/external/mwp/` (git-ignored).

## Method

- Each problem is played as one conversation: its body, one sentence per turn, then its question.
- A problem is **in domain** when its events are holdings, gains, uses and transfers and its question is a
  count or a total. The labels were written by a language model outside MARCO, used only for labelling, and
  each label is checked: its sentences must be the body's own, and its events, replayed, must give the
  dataset's answer. 70 of 726 pass; the rest are comparisons ("how many more than"), unknown starts,
  multiplication, rates and prices.
- Scored by the dialogue gate's own scorer; the expected number is the dataset's answer.
- Harness: `data/external/mwp/work/run_mwp.py svamp`. Engine: main `982343f`, effort 3. 3 h 12 min on one core.

## Result

| Group | Problems | Correct | Held | Wrong |
| --- | --- | --- | --- | --- |
| In domain | 70 | 1 | 69 | 0 |
| Out of domain | 656 | 0 | 655 | 1 |

- In-domain statements recorded: 20 of 151 (13%). 56 of the 70 problems had no statement recorded, 3 had
  every statement recorded, 1 was answered.
- Out-of-domain statements recorded: 131 of 1,480.
- The failure is reading, not reasoning: the reader does not cover textbook English.

## The wrong answer, and its fix

`chal-266`: three statements, the second not read and naming no holder, then a count question. MARCO answered
the last stated count (8; the dataset's answer is 997) where it should have held. Cause and fix are the last
row of the [experiment log](2026-09-29-experiment-log.md): an unread turn now marks every thing node it
mentions, and a holder's count stays held until each marked thing is said again (`1d0751e`, merged
`ea005a5`). Replayed on `eca0367`: held. The frozen exam is unchanged at 98 of 108.

## What it means

The gate number describes the exam. On open English text of the same domain MARCO answers 1 problem in 70,
and before the fix it gave one confident wrong answer in 726. Both numbers belong beside the gate number.
The full run has not been repeated since the fix; only `chal-266` and the one correct problem were replayed.
