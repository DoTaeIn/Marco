# The graph engine

> Moved out of the root README on 2026-09-29, unchanged. Numbers and `engine.py` line
> numbers are as measured at `5f321a3` unless a line says otherwise; the root README
> carries the current gate numbers.

## How the graph engine answers

This is the older of MARCO's two answering paths: a router over 904 authored
`.kg` graphs, each with its own evidence, requirements and reply lines. Its
answers are the graph's own lines; what it computes is the values in them.

```
> 밥값 나눠야 하는데                      (I need to split the bill)
  정산을 도와드리죠. 얼마 나왔고 몇 분이신지부터 알려 주세요.
> 12만원 나왔어                          (it came to 120,000 won)
  12만원 니까 얼마 나왔는지 안다. 몇 분이서 나누세요?
> 3명이야                                (three of us)
  3명이야 니까 몇 명인지 안다. 그러면 한 사람 40000원 입니다.
```

`40000` appears in no graph. The two numbers came from the user, the formula
`{원 = 총액 / 인원}` was written by a person, and the engine only evaluated it.
Reproduce: `printf '밥값 나눠야 하는데\n12만원 나왔어\n3명이야\n' | python engine.py graphs/graph_정산_나눠내기.kg`
(output above, at `5f321a3`). Proof: `tests/test_grounded_routing.py::test_dialogue_keeps_a_grounded_session_for_follow_up_values`
and `tests/test_mco_package.py::test_multi_turn_run` assert the `40000` answer;
`python engine.py --check` asserts that the value is empty before the head count
arrives and `40000.0` after (engine.py:4524-4530).

### Why it does not invent answers

**1. The answer space is authored.** Replies come from `[대사]` templates whose
slots are filled with sentences already in the graph. There is no decoder.

**2. "Irrelevant" and "unknown" are different verdicts.**

| Verdict | Condition | Meaning |
|---|---|---|
| `인정` accept | evidence supports the claim | proven |
| `A` ask back | `A_MIN ≤ conf < OK_MIN` | "did you mean X?" |
| `근거없음` | a claim was made with no evidence given | "what are you basing that on?" |
| `B1` | evidence was given, but nothing reaches the claim | the evidence does not support it |
| `B2` reject | **a null-class node scored highest** | *positive* evidence of irrelevance |
| `미지` unknown | nothing scored above `A_MIN` | *absence* of evidence |

The judge also returns `C` and `수치미달` (a numeric condition not met)
(engine.py:1158 `_judge_raw`). The `[무관]` null class is what makes `B2`
possible: without it a graph cannot tell "off topic" from "I have no idea".

**3. Values are carried, never produced.** `{등}` captures a number from the
user's words; `{등 <- other_node}` moves it; `{원 = total / people}` evaluates a
formula a person wrote. A missing operand emits nothing, division by zero gives
no value, and the formula grammar is a whitelisted AST walk (`+ - * /`,
parentheses, node names, literals). Proof: the capability table above.

### Request lifecycle

```
                        user utterance
                              │
                ┌─────────────▼─────────────┐
                │  fragment split           │  sentence ends + Korean connective
                │  language detection       │  endings (-하여, -는데, -면서 …)
                └─────────────┬─────────────┘
                              │
                ┌─────────────▼─────────────┐
                │  ROUTER  (graph index)    │  one table of contents per graph,
                │  sparse dot product       │  always resident; built from each
                │                           │  file's text, bodies not loaded
                └─────────────┬─────────────┘
                              │
              below threshold │ above threshold
                    ┌─────────┴─────────┐
                    ▼                   ▼
              ┌──────────┐   ┌──────────────────┐
              │  미지     │   │  graph loader    │  LRU, 2 bodies max
              │ "unknown"│   │  (expands 포함:)  │
              └──────────┘   └────────┬─────────┘
                                      │
                     ┌────────────────▼────────────────┐
                     │            judge()              │
                     │  1. find ALL evidence           │  literal, digit- and
                     │     (concept-network expanded)  │  ending-tolerant
                     │  2. erase evidence, match claim │
                     │  3. compete against null class  │  → B2
                     │  4. read 근거관계 edge           │  when the utterance IS evidence
                     └────────────────┬────────────────┘
                                      │
                     ┌────────────────▼────────────────┐
                     │       session (multi-turn)      │
                     │  · evidence → requirement       │
                     │  · capture / carry / compute    │
                     │  · context-narrowed ask-back    │  → A → learn
                     └────────────────┬────────────────┘
                                      │
                     ┌────────────────▼────────────────┐
                     │  render: 대사 · 물음 · 되물음     │
                     │  Korean particle agreement       │  은/는 이/가 을/를 …
                     └────────────────┬────────────────┘
                                      ▼
                     realize(): graph lines pass through unchanged,
                     "unknown" and hold replies are composed
                                      ▼
                            answer + evidence path
```

| Tier | Residency |
|---|---|
| **Index** | always; read from each `.kg` file and cached by size and time, does not expand `포함:` |
| **Body** | only the graphs in use, LRU of 2 (`engine.load_graph`, engine.py:3281) |
| **File** | on disk |

### The encoder: coverage, not cosine

The default encoder has no neural network and no tokenizer. It hashes signed
character n-grams into a fixed vector (4,096 dimensions by default,
`KG_DIM`, encoder.py:38), with the two sides built asymmetrically so the dot
product measures *containment*: "what fraction of this index line appears in
the question?", not "how similar are these two strings?".

Three guards, each asserted by the self-checks in the capability table:

- **Short index lines cannot win long questions.** Otherwise a short polite
  phrase shares `-습니다` n-grams with unrelated sentences and captures them.
- **Short questions are also scored in reverse.** A short question has few
  n-grams and cannot cover a long line on its own.
- **Digits are masked on both sides.** `2등을 제쳤다` and `5등을 제쳤다` are the
  same evidence; magnitude is handled by numeric conditions.

A neural encoder (`KG_ENCODER=신경망`, needs `sentence-transformers`) is
optional. This README has no measurement of it at this commit.

## Graph format (`.kg`)

```
역할: 정산 도우미                      role
목표: 몫을안다                         goal
임계값: 0.50 / 0.60                    A_MIN / OK_MIN
이름말: 문장                           render node names as sentences
전진관계: 확인함, 이어짐                ← relation NAMES are per-graph
부정관계: 어긋남
근거관계: 확인함

[개념]   concepts — states
몫을안다 {원 = 총액 / 인원}: "한 사람이 얼마 낼지 안다" | "밥값 나눠야 하는데"
총액 {원}:  "전체 금액을 안다"
인원 {명}:  "몇 명인지 안다"

[공리]   axioms — facts needing no evidence
신고기간은5월@국세청: "종합소득세 신고 기간은 5월입니다"

[사례]   instances — actions and evidence
*금액들음: "12만원" | "12만원 나왔어" | "12만원인데"
*인원들음: "3명이야" | "3명입니다" | "세 명이서 먹었어"

[무관]   null class — decoys and small talk; the basis for refusal
_잡담: "점심 뭐 먹지" | "날씨가 좋네요"

[논증]   argument edges ← this is the knowledge
금액들음 -확인함-> 총액
인원들음 -확인함-> 인원
총액 -이어짐-> 몫을안다
인원 -이어짐-> 몫을안다

[개념망] concept network — lexical widening, hyponym -상위-> hypernym
뺐어요 -상위-> 모았어요

[물음]   ask for a missing requirement instead of announcing it
인원: 몇 분이서 나누세요?

[되물음] what to say when unsure
총액: 금액 이야기인가요? 얼마 나왔는지 말씀해 주세요.

[대사]   per-verdict templates
인정: {ev} 니까 {claim}.
결론값: 그러면 한 사람 {값} 입니다.
```

The reader is `engine.read_kg` (engine.py:303). The authoring guide is
[docs/ko/그래프-저작-프롬프트.md](../ko/그래프-저작-프롬프트.md) (Korean) and
[docs/en/graph-authoring.md](graph-authoring.md).

### Relation names are data, not code

The engine knows three roles; every graph names them itself.

| Role | Determines |
|---|---|
| `근거관계` | which instance nodes are **evidence** |
| `전진관계` into the goal | which concepts are **requirements** |
| `전진관계` between concepts | **reachability** |
| `부정관계` | counters and self-defeat |

Requirements are the concepts with a `전진관계` edge into the goal
(`engine.requirements`, engine.py:1357). They are conjunctive, and each needs
its own evidence (`--check` L5067-5085).

### Sharing knowledge across graphs

`포함:` merges another graph's concepts, argument edges and axioms, and also its
null class, templates, value rules, questions and ask-backs (engine.py:151
`_include`). Relation names are translated by role on import, so a graph using
`충족` can be included by one using `이어짐`. Proof: the capability table.

`python engine.py --dups` lists knowledge duplicated across graphs. It ignores
overlap inside a null class, which is a boundary, not redundancy.

---

## Learning

The graph engine learns one thing on its own, and only with a person's
confirmation: **that a phrase denotes an existing node.** It is one of the
narrow doors of Katalepsis, MARCO's knowledge admission: a candidate becomes
knowledge only after a person approves it.

```
> 녹화 화면                                    (recorded footage)
  혹시 「나갈 길이 막혀 있었습니다」는 말씀입니까?
> 네                                           (yes)
  → graphs/graph.학습.jsonl  {"노드": "현장사진", "말": "녹화 화면"}
```

The ask-back narrows candidates to evidence that still reaches an unfilled
requirement. A "네" stores an alias; an "아니요" stores the phrase in the null
class. Learned aliases feed the router index, so a phrase learned in one
conversation routes in the next. Proof: `--check` L4671-4694, L5218-5284 and
L4564-4583.

The graph engine does not create nodes, edges or graphs. The proposal tools
(`--dups`, `--bridges`, `--edges`, `--suggest`) print candidates only; a person
decides. Two other paths do add knowledge, each after approval: approved web
sources are saved as facts (`test_learning_question_flow.py`), and ALMA adds
approved graph assets (`test_alma_runtime.py`).
