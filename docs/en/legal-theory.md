# Legal-theory guide

The `legal/` directory contains reusable legal layers shared by case graphs.
It is not a case-record store: case facts and evidence belong in `cases/`.

A case graph may include a legal layer using a path relative to the case file,
for example:

```text
포함: ../legal/법리_형법21조.kg
```

Keep shared requirements, their supporting concepts, and reusable relations in
`legal/`. Keep the factual record, evidence items, and the case target in the
case graph. This makes the legal layer reusable while preserving the source and
reasoning path for each individual case.
