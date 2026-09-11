"""Compose a bounded arithmetic graph from declared phrase grammar.

This is a small formal-language bridge, not unrestricted Korean understanding.
The full input must match; unknown clauses and ambiguous trees are rejected.
"""
import re

from numeral_semantics import parse_numeral

def parse(text, *, grammar=None, numerals=None):
    if len(text) > 512:
        return None
    if grammar is None:
        from pack_model import development_model
        model = development_model()
        grammar = model.language["verbal_expressions"]
        numerals = model.relational_data.get("numerals", {})
    if not grammar:
        return None
    match = re.fullmatch(grammar["equation"], text.strip())
    if not match:
        return None
    numerals = {} if numerals is None else numerals
    remaining = 128

    def tree(source, depth=0):
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 16:
            raise ValueError("verbal_expression_limit")
        source = source.strip()
        if source in grammar["variables"]:
            return ("variable", "x")
        number = parse_numeral(source, numerals)
        if number is not None:
            return ("number", number)
        candidates = []
        for rule in grammar["rules"]:
            found = re.fullmatch(rule["pattern"], source)
            if found:
                left, right = tree(found["left"], depth + 1), tree(found["right"], depth + 1)
                if left is not None and right is not None:
                    candidates.append((rule["op"], left, right))
        unique = set(candidates)
        return next(iter(unique)) if len(unique) == 1 else None

    try:
        left, right = tree(match["left"]), tree(match["right"])
    except ValueError:
        return None
    if left is None or right is None:
        return None
    nodes = []

    def emit(value):
        if value[0] == "variable":
            node = {"op": "variable", "name": value[1]}
        elif value[0] == "number":
            node = {"op": "number", "value": value[1]}
        else:
            node = {"op": value[0], "left": emit(value[1]), "right": emit(value[2])}
        nodes.append(node)
        return len(nodes) - 1

    roots = [emit(left), emit(right)]
    return {"nodes": nodes, "roots": roots, "variable": "x", "source": text.strip()}
