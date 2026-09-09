# Marco

**A knowledge-graph engine that selects rather than generates, and says "I don't know"
when the graph has no answer.**

There is no autoregressive loop. One encoder forward per utterance, then the answer is
*chosen* from sentences a human wrote into the graph. Values are *carried* along edges a
human drew. Nothing is invented — which is why every answer leaves an evidence path.

```
> 밥값 나눠야 하는데                      (I need to split the bill)
  정산을 도와드리죠. 얼마 나왔고 몇 분이신지부터 알려 주세요.
> 12만원 나왔어                          (it came to 120,000 won)
  12만원 니까 얼마 나왔는지 안다. 몇 분이서 나누세요?
> 3명이야                                (three of us)
  3명이야 니까 몇 명인지 안다. 그러면 한 사람 40000원 입니다.
> 오늘 서울 날씨 어때                     (what's the weather in Seoul)
  그건 모르겠습니다.                      (I don't know that)
```

`40000` appears nowhere in the graph. Two numbers came from the user's utterances; the
formula `{원 = 총액 / 인원}` was written by a human. The engine only evaluated it.

[Korean README](docs/ko/README-full.md) · [Graph authoring guide](docs/ko/그래프-저작-프롬프트.md) ·
[Knowledge graph viewer](views/지식그래프.html)

---

## Measured state

145 graphs · 2,092 nodes · 2,122 edges. All numbers below are from the repository's own
fixed benchmarks, not estimates.

| | Value | Meaning |
|---|---|---|
| **Out-of-domain rejection** | **27 / 27** | Questions no graph covers are refused |
| Chosen graph answers | 64.0 % | Over 2,018 held-out phrasings |
| Routes to source graph | 37.0 % | Low because overlapping graphs split the credit |
| **Turn latency** | **7.4 ms** | Route + judge + render |
| Cold start | 204 ms | Index 145 graphs from cache |
| **Resident memory** | **68 MB** | `torch` is never imported |
| Dependencies | `numpy` | Character encoder needs nothing else |
| Code | 8,692 lines | `engine` · `encoder` · `explain` · `build` |

Reproduce:

```bash
KG_ENCODER=문자 python routing_benchmark.py --답
KG_ENCODER=문자 python engine.py --regress
KG_ENCODER=문자 python engine.py --check
```

---

## Why it cannot hallucinate

Three structural properties, not guardrails.

**1. The answer space is enumerable.** Responses are drawn from `[대사]` templates whose
slots are filled with sentences already present in the graph. There is no decoder, so
there is no sampling step at which an unseen string could appear.

**2. "Irrelevant" and "unknown" are different verdicts.** Collapsing them is the classic
failure mode — a system that says "not relevant" to everything it lacks will confidently
dismiss valid arguments.

| Verdict | Condition | Meaning |
|---|---|---|
| `인정` accept | evidence supports claim | proven |
| `A` ask-back | `A_MIN ≤ conf < OK_MIN` | "did you mean X?" |
| `B1` / `근거없음` | claim matched, no evidence | "what are you basing that on?" |
| `B2` reject | **null-class node scored highest** | *positive* evidence of irrelevance |
| `미지` unknown | nothing scored above `A_MIN` | *absence* of evidence |

The `[무관]` (null class) section is what makes `B2` possible. Without it a graph cannot
distinguish "off topic" from "I have no idea", and the engine refuses to ask back at all
in that case — a document graph with an empty null class will never guess.

**3. Values are transported, never produced.** `{등}` captures a number from the user's
utterance; `{등 <- other_node}` moves it; `{원 = total / people}` evaluates a formula the
author wrote. If any operand is missing, nothing is emitted — filling a gap with zero
would manufacture an answer. Division by zero yields no value rather than infinity. The
expression grammar is a whitelisted AST walk (`+ - * /`, parentheses, node names,
literals); `eval` is never called, because a `.kg` file is human-authored data, not
trusted code.

---

## Request lifecycle

```
                        user utterance
                              │
                ┌─────────────▼─────────────┐
                │  fragment split           │  sentence ends + Korean connective
                │  language detection       │  endings (-하여, -는데, -면서 …)
                └─────────────┬─────────────┘  English → also add a de-framed fragment
                              │
                ┌─────────────▼─────────────┐
                │  ROUTER  (graph index)    │  145 tables of contents, always resident
                │  sparse dot product       │  12.7 MB · 3.7 % non-zero
                │  0.8 – 4 ms               │  graph bodies are NOT opened here
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
                     │  · bipartite evidence→requirement
                     │  · capture / carry / compute    │
                     │  · context-narrowed ask-back    │  → A → learn
                     └────────────────┬────────────────┘
                                      │
                     ┌────────────────▼────────────────┐
                     │  render: 대사 · 물음 · 되물음     │
                     │  Korean particle agreement       │  은/는 이/가 을/를 …
                     └────────────────┬────────────────┘
                                      ▼
                            answer + evidence path
```

### The three-tier memory model

This is why 145 graphs run in 68 MB.

| Tier | Size | Residency |
|---|---|---|
| **Index** | 12.7 MB | Always. Does **not** expand `포함:` |
| **Body** | ~0.5 MB each | Only the graph in use — LRU of 2 |
| **File** | 2–4 KB | On disk |

Adding one graph re-encodes that graph alone (+9 ms), because the vector cache is keyed
per graph by a content hash. Deleting one drops it automatically.

---

## The encoder: coverage, not cosine

The default encoder uses **no neural network and no tokenizer** — signed character
n-gram hashing into 4,096 dimensions, with the two sides built asymmetrically so the dot
product measures *containment*:

- **contained side** (index lines, node names): weights L1-normalised by their own mass
- **containing side** (the question): presence only, clipped to ±1 — length does not
  enter the denominator

So the score answers *"what fraction of this index line appears in the question?"* rather
than *"how similar are these two strings?"*.

Cosine was measured and rejected: asking `도메인` alone scored 1.000 but
`엔진은 도메인을 어떻게 다루나` collapsed to 0.211, because the question's own length is
in the denominator and real questions are always longer than node names. Under coverage
the positive/negative medians separate to 0.625 / 0.317.

Three guards keep coverage honest:

- **Short index lines cannot win long questions** (< 8 chars, > 2× length ratio). Without
  it `맞습니다` shares `-습니다` n-grams with `맞붙어 싸웠습니다` at 0.74, and one
  etiquette graph hijacked 224 questions.
- **Short questions are also scored in reverse** (≤ 8 chars). A short question has few
  n-grams and cannot cover a long line; measuring the other direction lifted evidence
  routing from 68.8 % to 87.9 % at zero cost to rejection.
- **Digits are masked on both sides.** `2등을 제쳤다` and `5등을 제쳤다` are the same
  evidence; magnitude is handled separately by numeric conditions.

A neural encoder (`jhgan/ko-sroberta-multitask`) is available and handles unseen
phrasings better, at 550 ms/turn and 860 MB.

---

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

### Relation names are data, not code

The engine knows exactly **three roles**; every graph names them itself. `npc_대장장이.kg`
uses no courtroom vocabulary at all.

| Role | Determines |
|---|---|
| `근거관계` | which instance nodes are **evidence** |
| `전진관계` into the goal | which concepts are **requirements** |
| `전진관계` between concepts | **reachability** — over half of all edges |
| `부정관계` | counters and self-defeat |

Delete every edge from a graph and evidence count drops to 0, requirement count drops to
0, and the session reports a *win* without the user having said anything — there are no
requirements left to fill. **Nodes are labels; edges are the knowledge.**

Requirements are conjunctive, but multiple edges *into one concept* are disjunctive —
each alone suffices. Two facts that must both hold have to be two requirements.

### Sharing knowledge across graphs

`포함:` merges another graph's concepts, argument edges and axioms — never its instances,
which belong to their own case. Relation names are translated by role on import, so a
graph using `충족` can be included by one using `이어짐`. Seven case files share
`legal/법리_형법21조.kg` this way.

`python engine.py --dups` finds knowledge duplicated across graphs, deliberately ignoring
overlap that lives in a null class — that kind is a *boundary*, not redundancy, and
removing it makes neighbouring graphs steal each other's questions.

---

## Learning

The engine learns exactly one thing, and only with human confirmation: **that a phrase
denotes an existing node.**

```
> 녹화 화면                                    (recorded footage)
  혹시 「나갈 길이 막혀 있었습니다」는 말씀입니까?
> 네                                           (yes)
  → graphs/graph.학습.jsonl  {"노드": "현장사진", "말": "녹화 화면"}
```

The interesting part is *when* it asks. Similarity alone never triggers this — an unknown
phrase shares no characters with anything (`녹화 화면` scores 0.098). Instead the session
narrows candidates to **evidence that still reaches an unfilled requirement**, turning ten
candidates into six. Measured over 167 unrecognised utterances: **91 % fall inside that
narrowed set, and 44 % are its top-ranked member.** Inside a small candidate set the
question is no longer "what is this?" but "which of these six is it closest to?" — which
is worth asking aloud.

Learned aliases feed back into the router index (keyed on the learning log's mtime), so a
phrase learned in one conversation routes correctly in the next.

What it does **not** learn: new nodes, new edges, new graphs. Proposal tools
(`--dups`, `--bridges`, `--edges`, `--suggest`) emit candidates only; a human decides.
Choosing edge direction automatically is the point at which a graph would begin asserting
without grounds.

---

## Capability

Measured behaviour, run against the shipped graphs.

| Class | Prompt | Result |
|---|---|---|
| Trap reasoning | Overtake 2nd place in a marathon — what place? | **2nd** |
| Trap reasoning | 60 players take 60 min; how long for 120? | asks for the piece's length (headcount irrelevant) |
| Trap reasoning | Carwash 5 min on foot, 10 by car — drive? | time comparison is irrelevant to washing a car |
| Arithmetic | Split 120,000 among 3 | **40,000 each** |
| Multi-turn | facts given across turns | accumulate to the same answer |
| Learning | unknown phrase → ask-back → "yes" | stored as an alias |
| Refusal | bank balance · today's weather | **"I don't know"** |
| English | split the bill / 120000 won / 3 people | **"Then it is 40000won each."** |

### Position relative to other systems

| | Breadth | Reasoning | Refusal |
|---|---|---|---|
| ELIZA / pattern chatbots | none | none | none |
| Expert systems (MYCIN-era) | narrow | yes | partial |
| Retrieval chatbots | broad | none | weak |
| **Marco** | **narrow (145 domains)** | **yes** | **strong (27/27)** |
| Modern LLMs | very broad | yes | **weak** |

A precise specialist with a small world. Inside its 145 domains it computes, resists
traps, and refuses cleanly; outside them it knows nothing. Breadth is the fundamental
gap, and closing it requires humans to draw graphs.

> This table compares system *classes* by what they do; it is not a head-to-head
> benchmark. The measured claims are the 27/27 rejection rate and the trap results above.

---

## Quick start

Python 3.10+.

```bash
pip install numpy                       # character encoder needs nothing else

KG_ENCODER=문자 python engine.py graphs/graph_정산_나눠내기.kg      # chat with one graph
KG_ENCODER=문자 python engine.py --route "밥값 나눠야 하는데"        # route across all 145
KG_ENCODER=문자 python engine.py --diagnose graphs/graph_순위_추월.kg

KG_ENCODER=문자 python engine.py --check      # self-check
KG_ENCODER=문자 python engine.py --regress    # case regression
KG_ENCODER=문자 python routing_benchmark.py --답
```

Graph-growing tools — all propose, none decide:

```bash
python engine.py --dups      # same knowledge written into several graphs
python engine.py --bridges   # graphs worth linking (magnets filtered by mutual rank)
python engine.py --edges     # relation candidates from source text
python engine.py --suggest   # node candidates from source text
```

For the neural encoder: `pip install sentence-transformers` and leave `KG_ENCODER` unset.

---

## Layout

Code identifiers — file, function and variable names — are English. The knowledge
is Korean: `.kg` section headers, node names, verdicts and reply templates are the
product, not the implementation, and they stay as authored.

```text
core
  encoder.py       text → vector. Character n-gram coverage (default) or neural
  engine.py        judging · value transport · learning · router · diagnostics
  explain.py       path-based explanation over document graphs (.json)
  build.py         document → knowledge graph authoring
  nai.py           one chat contract over both .kg and .json graphs
  hangul.py        Korean grammar derived from Unicode, not from tables
  kgbin.py         flat mmap-able index for embedded targets
  kgpack.py        many graphs → one uploadable pack

growth
  self_authoring.py   dictionary → candidate graphs, gated before admission
  self_learning.py    what it got wrong → what to read → rebuild → re-measure
  purpose_graph.py    one definition sentence → one purpose graph
  dict_extract.py     national dictionary → genus/action tables
  web_learn.py        web sources → verified overlay knowledge

measure
  routing_benchmark.py   held-out routing benchmark (fixed, reproducible)
  yardstick.py           frozen benchmark — human-authored graphs only
  intelligence_check.py  paraphrase and generalisation spot-check
  alias_diag.py          which nodes are short of aliases

data
  graphs/*.kg      145 domain graphs
  legal/*.kg       shared legal doctrine, pulled in via 포함:
  cases/사건_*.md  source judgments and their compiled graphs
  styles/          phrasing tables — data, not engine
  data/표지/       domain markers — data, not engine
  docs/ko/         authoring prompts and design records

around
  progress.py      dependency-free progress bar (remaining time, not percent)
  cache_tool.py    what caches exist, what is safe to drop
  vision.py        image → visual words → graph experiments
  tests/           pytest
  views/           web UI and graph visualisation
```

---

## Design principles

**Never invent.** Answers are selected from authored sentences; values are transported
from the user's own utterance; formulas, relations and questions are written by humans.

**Separate "unknown" from "irrelevant."** Merging them makes the system lie about valid
arguments it simply does not cover.

**Machines propose, humans confirm.** Every growth tool emits candidates only.

**Swap domains without touching the engine.** Relation vocabulary, phrasing, and
follow-up questions all live in graphs and data files.

**Stay light.** 68 MB, 7 ms per turn, no `torch`. This constraint is not negotiable.

---

## Limits

- **Narrow knowledge.** 145 graphs is the whole world. Growth is human-paced.
- **Unseen phrasings.** 37 % route to their source graph; much of the remainder is
  defensible overlap between related graphs, but genuine misses remain.
- **English is half-supported.** Questions containing English terms reach Korean graphs,
  but answers come back in Korean. Answering in English requires an English graph for
  that domain.
- **No structural learning.** It learns aliases, not nodes or edges.
- **Korean numerals are not parsed.** `세 명` yields no value — it does not guess.

### Paths measured and abandoned

- **Dictionary synonyms** (12,206 pairs extracted from the Korean standard dictionary) —
  zero improvement. Mostly nouns, senses not disambiguated.
- **IDF weighting** — +0.9 pp at matched rejection rate; not worth recalibrating for.
- **Shared Hanja as a synonym signal** — 5–10 % precision.
- **Word substitution as translation** — catches `smoke 발견했어요` but not
  `I found smoke`. The syntactic frame stays Korean.
