# Development guide

This repository is a graph-grounded AI system. It does not generate a free-form
answer first and then look for support. Instead, it maps a statement to a graph
node, follows `evidence → satisfies → conclusion` relations, and returns the
supporting path.

## Repository map

- `encoder.py`: sentence vectorization and shared path helpers.
- `engine.py`: graph loading, matching, reasoning, sessions, and evaluation.
- `explain.py`: evidence-based explanation and document procedures.
- `build.py`: source documents to knowledge-graph authoring tool.
- `codegen.py`: algorithm-description to code generation tool.
- `graphs/`, `cases/`, `legal/`, and `data/`: domain knowledge and source data.

## Common checks

```bash
KG_ENCODER=문자 python encoder.py --check
KG_ENCODER=문자 python build.py --check
KG_ENCODER=문자 python codegen.py --check
python engine.py --regress
```

Use the character encoder for offline checks. It avoids downloading a sentence
transformer model.

## Safe changes

Keep graph data and code separate. Add domain knowledge in `.kg` files, retain
the source material in `data/`, and run the relevant self-check after every
small change. Case Markdown belongs in `cases/`; compiled `.kg` files and
regression entries must use paths relative to that directory.
