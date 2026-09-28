# Explanation-engine guide

`marco/runtime/explain.py` turns graph matches into evidence-based explanations. It can load
a graph, retrieve relevant passages, assemble a path to the target, and work
with ordered project documents.

Examples:

```bash
python -m marco.runtime.explain --draw data/법지식/지식그래프.json
python -m marco.runtime.explain --score data/법지식/지식그래프.json
python -m marco.runtime.explain --절차 docs/ko/development.md README.md "What should happen before a PR?"
```

The explanation engine should preserve the distinction between an explicit
graph-supported answer and an unsupported guess. When a suitable path or
source passage is absent, the correct behavior is to report that limitation,
not to invent a conclusion.
