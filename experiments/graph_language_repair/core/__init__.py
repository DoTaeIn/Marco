# -*- coding: utf-8 -*-
"""Graph language repair — the reading core.

``read_text`` turns a document into the explicit reading graph described in
``experiments/graph_language_repair/CONTRACT.md``.  ``search_rows`` runs the
repository's existing relation search over that graph's rows.

The runtime is explicit graph data under ``graphs/core/`` plus generic Python
mechanics.  There is no neural inference, token prediction, embedding,
statistical token model, model or API call, remote tool or pretrained NLP
runtime anywhere in the import graph of this package.
"""
from experiments.graph_language_repair.core.graph_store import (GraphDataError,
                                                                GraphStore,
                                                                load_graphs)
from experiments.graph_language_repair.core.reading import READING_SCHEMA, read_text
from experiments.graph_language_repair.core.morphology import analyze_predicates
from experiments.graph_language_repair.core.search import (IncompleteSearch, matches,
                                                          project_rows, search_rows,
                                                          select_rows)

__all__ = ["analyze_predicates", "read_text", "search_rows", "matches", "project_rows", "select_rows",
           "IncompleteSearch", "load_graphs",
           "GraphStore", "GraphDataError", "READING_SCHEMA"]
