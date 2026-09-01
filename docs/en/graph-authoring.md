# Graph authoring guide

Graphs describe claims, evidence, and the relations that allow the engine to
reach a conclusion. The three core edge types are:

- `증명` (evidence): an item supports a case fact.
- `충족` (satisfies): a fact or concept satisfies a higher-level requirement.
- `부정` (negates): a fact defeats a requirement.

Store reusable domain graphs in `graphs/`, shared legal layers in `legal/`, and
case-specific materials in `cases/`. When a graph includes another graph, use
a relative path from the graph file itself; a case graph normally refers to a
shared legal graph as `../legal/...`.

Build a graph from a source folder with:

```bash
python build.py data/법지식 --out graph.json
```

Review suggested nodes and edges before promoting them into a tracked `.kg`
file. Keep the original source documents in `data/` so every graph claim can
be audited.
