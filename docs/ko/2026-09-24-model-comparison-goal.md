# Goal C1: compare MARCO with other models on the same frozen exams

Model: the owner's chat model, effort high. Read `docs/ko/2026-09-22-freeze-decision.md` first.
Written 2026-09-24. Own checkout, branch `model-comparison`. Evaluation only:
**no change to any MARCO product file.**

## Why

Nobody can judge MARCO's numbers without a second column. The owner wants the
same two frozen exams, the 52 dialogues and the 114 reasoning problems, run
through other models and scored by the same rules, then published side by side.

## Rules for this goal

- This is the evaluator's seat: you may read and run the frozen sets. You may
  not edit `styles/`, the root `.py` modules, `marco/`, `mco/`, or any test that
  is not yours. No frozen sentence appears in any document or commit message;
  results are aggregates and per-turn buckets by id only.
- Nothing leaves the machine. Every compared model runs locally. An API model
  may be added only by the owner later, behind an environment variable, and
  only after the owner decides the frozen sets may be sent out; you do not
  handle keys.
- `torch 2.9` and `transformers 5.0` are installed; `mlx-lm` may be installed
  (`python -m pip install mlx-lm`). The machine is an M4 Pro with 24 GB; other
  agents are running test suites, so keep a model under 6 GB resident.

## Definition of done — all six, measured

C1.1 **Harness** `bench/compare_models.py`: plays every frozen dialogue and
     reasoning problem turn by turn through an *answerer* interface
     (`answer(history, utterance) -> str`) and scores the reply text with the
     same denominators as `bench/dialogue_gate.py` and `bench/reasoning_gate.py`:
     for each answerable turn, extract the value (digits, number words in both
     languages, counters) and the holder name from the reply and compare with
     the expected semantic structure; classify **correct / wrong / hold /
     unverifiable** where a hold is a reply that declines or says the information
     is missing. Two more columns per model: **invented answers**, the count of
     value-bearing replies on turns labelled missing-premise or unsupported
     (MARCO's gate condition 3), and **latency and resident memory** per turn.
     The extractor is tested (C1.4) and applied identically to every model,
     MARCO included.

C1.2 **Answerers**, each a small module under `bench/answerers/`:
     - `marco`: the same entry the gate uses (`views.kgpack_ui.AppState.turn`),
       so MARCO is scored through the same extractor as everyone else, and its
       gate report is cited alongside for the structural score.
     - `always_hold`: replies "I do not know" / "모르겠습니다" to everything. The floor.
     - `gpt2`: `openai-community/gpt2` through transformers, greedy, with a
       plain few-shot prompt. The owner's reference point; expected near zero.
     - one **instruction-tuned open model that handles Korean**, 3B to 7B
       parameters, 4-bit through `mlx-lm` or bf16 through transformers on MPS,
       under 6 GB resident: prefer `Qwen/Qwen2.5-7B-Instruct` 4-bit via mlx-lm,
       else `Qwen/Qwen2.5-3B-Instruct`. Same prompt for every turn: the
       dialogue so far, then the utterance, with an instruction to answer
       briefly and to say that the information was not given when it was not.
       Record model id, quantization, prompt, temperature 0.
     Every answerer gets the whole dialogue history, since MARCO keeps state too.

C1.3 **Runs**: every answerer on both frozen sets, both languages, once, on
     the same commit. Reports as JSON under `docs/ko/model-comparison-2026-09-24/`
     plus one `README.md` with the table:

     | model | params | dialogues answerable correct | wrong | invented answers on unsupported turns | reasoning correct | reasoning wrong | median latency | resident memory |

     with MARCO's row taken from the same harness and its gate reports cited.

C1.4 **Extractor tests** `tests/test_compare_models.py`: 40 hand-written reply
     strings per language covering digits, number words, counters, holder
     names, declines and hedges; an injected wrong reply scores wrong; a decline
     scores hold; an invented value on an unsupported turn counts as invented.
     Also: scoring MARCO's own frozen replies through the extractor gives a
     correct count within 2 of the structural gate report, or the difference is
     explained turn by turn in the report.

C1.5 **Fairness notes** in the README: what each model was given, what it was
     not (no tools, no retries), why prompt-based holds are counted as holds,
     and what the comparison cannot say (general knowledge, free chat, fluency).

C1.6 **No regressions**: the full parallel suite at main's count with the same
     three known failures; your tests added.

## Owns

`bench/compare_models.py`, `bench/answerers/`, `tests/test_compare_models.py`,
`docs/ko/model-comparison-2026-09-24/`. Nothing else.

## Working conditions

Commit by name, owner as author, no co-author lines, no assistant or model
name of the assistant anywhere (the compared models' names are data and belong
in the report). `python`, not `python3`. Do not push. Report tersely:
C1.1–C1.6 each done or not, the table, and the commit hash.
