# mco

A stable Python API and CLI for **MARCO-compatible reasoning models** (`.mco`).
Version 0.1.0 is on PyPI: <https://pypi.org/project/mco/>.

MARCO is a reasoning engine with no language model in it. It answers only from
evidence it can point to, and says it does not know when nothing grounds an
answer. In its state dialogue every reply is composed from a proven meaning and
spoken only after it parses back to that meaning; its knowledge-graph route
still answers with the lines people wrote into the graphs. `mco` is the public
interface to it. Your code talks to `mco`, never to MARCO's internal modules, so
it keeps working while the engine and the model format change.

```text
$ printf 'Minsu has five apples, and Jiyeon has two.\nMinsu gave Jiyeon two.\nHow many does Jiyeon have now?\n' \
    | mco run MARCO-1.mco
Recorded. Jiyeon has 2 apples.
  status: observed
Recorded. Minsu gave Jiyeon 2 apples. Now Minsu has 3 apples and Jiyeon has 4.
  status: observed
4 apples.
  status: answered
```

A knowledge-graph conversation, in the Korean the graphs are written in:

```python
import mco

model = mco.load("MARCO-1.mco")
result = model.run("12만원 나왔어")      # "the bill came to 120,000 won"
result = model.run("3명이야")            # "there are three of us"

print(result.answer)    # 3명이야 니까 몇 명인지 안다. 그러면 한 사람 40000원 입니다.
print(result.status)    # answered
print(result.evidence)  # 1. [graph_node] 인원들음 @ graphs/graph_정산_나눠내기.kg (1)
                        # 2. [graph_path] 인원들음 -확인함-> 인원 @ graphs/graph_정산_나눠내기.kg
                        # 3. [graph_path] 인원 -이어짐-> 몫을안다 @ graphs/graph_정산_나눠내기.kg
print(result.trace)     # 1. understand: ...
                        # 2. route: graphs/graph_정산_나눠내기.kg (score 1.0)
                        # 3. judge: argument: 인원 -> 인정
                        # 4. verify: model ..., 0 check(s)
```

Both outputs were produced at commit `5f321a3` with a model built by
`mco compile . -o MARCO-1.mco --name MARCO-1`.

## Install

```bash
pip install mco            # 0.1.0: the API and CLI, no dependencies, Python 3.10 or newer
```

That is enough for `mco.inspect()`, `mco inspect` and `mco backends`: they read
a model file and import nothing from MARCO. **Running** a model uses the MARCO
compatibility backend, which needs two more things:

1. the backend's dependencies, `numpy` and `pillow`: `pip install "mco[marco]"`
   (the quotes keep shells such as zsh from expanding the brackets);
2. a MARCO checkout, because the engine itself is not on PyPI. `mco` looks for
   it here, in order:
   1. `mco.load(..., marco_root="/path/to/marco")`
   2. the `MCO_MARCO_ROOT` environment variable
   3. MARCO modules already importable on `sys.path`
   4. the checkout `mco` itself was installed from (`pip install -e .`)

A model to run: the preview model `MARCO-1-preview.mco` (27,200,481 bytes) is
attached to the GitHub pre-release *MARCO 1 · Preview 1*,
<https://github.com/DoTaeIn/Marco/releases/download/Marco/MARCO-1-preview.mco>.
Or build one from the checkout with `mco compile` ([CLI](#cli)).

```bash
pip install "mco[marco]"
git clone https://github.com/DoTaeIn/Marco
export MCO_MARCO_ROOT=$PWD/Marco
curl -LO https://github.com/DoTaeIn/Marco/releases/download/Marco/MARCO-1-preview.mco
mco inspect MARCO-1-preview.mco
mco run MARCO-1-preview.mco "12만원 나왔어" "3명이야"
```

From a MARCO checkout, for development: `pip install -e ".[marco]"`.

## Python API

| Call | Returns | Purpose |
|---|---|---|
| `mco.load(path, *, backend=None, verify=True, **options)` | `Model` | Open a `.mco` or `.kgpack` |
| `model.run(text)` | `Result` | One utterance in the model's default conversation |
| `model.session()` | `Session` | A new, isolated conversation (`session.run`, `reset`, `close`) |
| `model.reason(data)` | `Result` | A self-contained problem given as facts plus a question |
| `model.reset()` | `None` | Forget the default conversation |
| `model.info` / `mco.inspect(path)` | `ModelInfo` | Metadata. Nothing is executed |
| `mco.compile(source, output, ...)` | `CompileReport` | Build a `.mco` from a MARCO source tree or `.kgpack` |
| `mco.benchmark(model_or_path, cases)` | `BenchmarkReport` | Accuracy and latency on fixed cases |

### Results

`Result.status` is a `mco.Status` (it is also a `str`):

| Status | Meaning |
|---|---|
| `answered` | A grounded answer was reached |
| `observed` | The input was recorded as a fact. Nothing was asked |
| `needs_input` | Progress was made, but the model needs more information |
| `unknown` | No grounded answer exists, so the model declines instead of guessing |
| `rejected` | Positive evidence that the input is out of scope or refuted |
| `pending_approval` | A plan was proposed. Nothing runs until it is approved |

`result.ok` is true for `answered` and `observed`. `result.evidence` is a list of
`Evidence(kind, text, source, score, detail)`. `result.trace` is a list of
`TraceStep(stage, summary, detail)`. Both print one item per line.
`result.to_dict()` / `result.to_json()` serialise the result.

### Structured reasoning

```python
result = model.reason({
    "facts": ["돌은 23개 있다.", "돌 8개를 꺼냈다."],   # "there are 23 stones", "8 were taken out"
    "question": "지금 돌은 몇 개야?",                   # "how many stones now?"
})
result.answer    # '15개입니다.'
result.evidence  # the two state transitions, the derived fact 돌.count = 15, the two facts
```

Facts and question are read by the model's language pack. This example needs a
model whose language is Korean, `mco compile . -o MARCO-1-ko.mco --name MARCO-1
--language styles/한국어.json`; a model compiled without `--language` is English,
and on it this question is held, not answered.

`reason()` runs in a fresh context. It does not read or change the model's
conversation. Facts can be strings, `mco.Fact(...)` objects or mappings.
Structured facts (`subject`/`predicate`/`value`) are part of the API, but the
MARCO backend does not support them yet: it raises `UnsupportedInputError`, and
`model.info.supports(mco.Capability.STRUCTURED_FACTS)` returns `False`.

### Errors

Everything derives from `mco.MCOError`: `ModelNotFoundError`, `ModelFormatError`
(and its subclasses `IntegrityError` and `UnsupportedFormatError`), `BackendError`
(and `BackendUnavailableError`), `CompileError`, `InvalidInputError` (and
`UnsupportedInputError`), and `ModelClosedError`. A backend's internal exceptions
are never raised as-is. They are wrapped, with the original chained as `__cause__`.

## CLI

```bash
mco compile . -o MARCO-1.mco --name MARCO-1              # whole source tree; English is the model's language
mco compile . -o MARCO-1-ko.mco --language styles/한국어.json  # Korean as the model's language
mco compile . -o bills.mco --graph "graphs/graph_정산_*.kg"  # a subset
mco inspect MARCO-1.mco                                  # add --json for machine output
mco run MARCO-1.mco "12만원 나왔어" "3명이야"             # one conversation; -v adds evidence and trace
mco run MARCO-1.mco                                      # interactive, reads stdin
mco benchmark MARCO-1.mco cases.jsonl --output report.json --fail-under 0.9
mco backends
```

Exit codes: `0` ok, `1` an `mco` error, `2` usage error, `3` benchmark below `--fail-under`.

## The `.mco` file in this release

The native MCO Format 1 binary is not specified yet. This release writes a
**compatibility container**: a deterministic ZIP holding `mco.json` (the MCO
manifest, with name, build id, payload hash and backend) and `payload.kgpack` (an
unmodified MARCO pack). `mco inspect` reports it as `format: mco-compat` and adds
the note *not MCO Format 1*.

When the native format and its runtime ship, they will be a new backend behind
the same API. The same `mco.load(...).run(...)` code will open both kinds of
file. Native files are already recognised by their magic prefix, and loading one
today raises `UnsupportedFormatError` instead of misreading it.

See [api.md](https://github.com/DoTaeIn/Marco/blob/main/docs/mco/api.md) for the
stability contract and how to write a backend.

## What 0.1.0 cannot do yet

- Run a model without a MARCO checkout: the engine is not packaged.
- Read or write the native MCO Format 1 file (above).
- Take structured facts in `reason()` with the MARCO backend (`UnsupportedInputError`).
- Compose every reply: the state dialogue composes each reply from its meaning;
  an answer from the knowledge-graph route is the line the graph's author wrote,
  passed through unchanged.

Release notes: [2026-09-24-mco-0.1.0.md](https://github.com/DoTaeIn/Marco/blob/main/docs/releases/2026-09-24-mco-0.1.0.md).

## License

MARCO Engine License 1.0: the Apache License 2.0 plus one condition, that a
product which puts MARCO in front of end users shows "Powered by MARCO — Created
by DoTaeIn, Original project: https://github.com/DoTaeIn/Marco" somewhere they
can find it. Library use, research, development and redistribution need nothing
more than the NOTICE file. Full text: https://github.com/DoTaeIn/Marco/blob/main/LICENSE
