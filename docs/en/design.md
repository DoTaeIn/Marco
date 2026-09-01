# Design record

The project is designed around constrained, inspectable reasoning. A neural
encoder proposes candidate graph nodes, but graph relations determine whether a
claim can reach a conclusion. This keeps a response tied to explicit evidence
and lets the system reject unsupported statements.

The important design boundary is between learned matching and authored logic:

- The encoder handles wording variation and numeric masking.
- Graph data carries domain knowledge and legal or procedural structure.
- Thresholds, a null class, and clarification questions handle uncertainty.
- Source documents remain separate from derived graphs for review and rebuilds.

The current repository layout follows those boundaries: code is at the root,
runtime knowledge is in `graphs/`, `cases/`, and `legal/`, source material is
in `data/`, and documentation is in `docs/`.
