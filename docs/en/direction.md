# Project direction

Objection is being developed as a graph-grounded AI system. The goal is not to
produce fluent text without constraints, but to make every conclusion traceable
to a path of evidence and concepts.

Current priorities are:

1. Improve statement-to-node matching without weakening the unknown-response
   boundary.
2. Expand reusable graph and source-data coverage.
3. Make graph authoring, evaluation, and regression checks repeatable.
4. Keep the repository structure predictable for people and tools.

New material enters through `data/`; reviewed concepts and relations enter
graphs. Cases stay in `cases/`, shared legal logic stays in `legal/`, and user
interfaces stay in `views/`. This separation keeps experiments from silently
changing production reasoning.
