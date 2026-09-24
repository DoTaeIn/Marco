# mco

A stable Python API and CLI for **MARCO-compatible reasoning models** (`.mco`).

MARCO is a knowledge-graph engine that selects answers instead of generating
them, and says it does not know when its graph holds no answer. `mco` is the
public interface to it. Your code talks to `mco`, never to MARCO's internal
modules, so it keeps working while the engine and the model format change.

```python
import mco

model = mco.load("MARCO-1.mco")
result = model.run("12만원 나왔어")      # "the bill came to 120,000 won"
result = model.run("3명이야")            # "there are three of us"

print(result.answer)    # 3명이야 니까 몇 명인지 안다. 그러면 한 사람 40000원 입니다.
print(result.status)    # answered
print(result.evidence)  # 1. [graph_node] 인원들음 @ graphs/graph_정산_나눠내기.kg (1)
                        # 2. [graph_path] 인원들음 -확인함-> 인원 @ graphs/graph_정산_나눠내기.kg
                        # ...
print(result.trace)     # 1. understand: ...
                        # 2. route: graphs/graph_정산_나눠내기.kg (score 1.0)
                        # 3. judge: argument: 인원 -> 인정
```

## Install

```bash
pip install mco            # the API and CLI; no dependencies
```

From a MARCO checkout (development):

```bash
pip install -e .
```

The `mco` package has no dependencies. Running a model uses the **MARCO
compatibility backend**, which needs a MARCO checkout and its dependencies
(`numpy` and `pillow`, installed by `pip install mco[marco]`). `mco` looks for the checkout here, in order:

1. `mco.load(..., marco_root="/path/to/marco")`
2. the `MCO_MARCO_ROOT` environment variable
3. MARCO modules already importable on `sys.path`
4. the checkout `mco` itself was installed from (`pip install -e .`)

`mco.inspect()` and `mco backends` work without MARCO installed. To run a
model today, clone the checkout and point `mco` at it:

```bash
git clone https://github.com/DoTaeIn/Marco
pip install mco[marco]          # adds numpy and pillow
export MCO_MARCO_ROOT=$PWD/Marco
mco run MARCO-1-preview.mco "12만원 나왔어"
```

The preview model file is attached to the MARCO release on GitHub
(https://github.com/DoTaeIn/Marco/releases).

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
mco compile . -o MARCO-1.mco --name MARCO-1              # whole source tree
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

## License

MARCO Engine License 1.0: the Apache License 2.0 plus one condition, that a
product which puts MARCO in front of end users shows "Powered by MARCO — Created
by DoTaeIn, Original project: https://github.com/DoTaeIn/Marco" somewhere they
can find it. Library use, research, development and redistribution need nothing
more than the NOTICE file. Full text: https://github.com/DoTaeIn/Marco/blob/main/LICENSE
