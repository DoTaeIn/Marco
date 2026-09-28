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
    # 값을 묻는 꼴. 등식이 아니라 셈 하나를 묻는다 — `8 빼기 3은 얼마야?`.
    # **연산을 알아보는 자리는 하나로 둔다.** 갈리는 것은 문장꼴뿐이고, 셈은
    # 아래 규칙 표가 그대로 읽는다. 그래서 말투가 늘어도 코드가 안 는다.
    value = None
    if not match:
        form = grammar.get("value")
        value = re.fullmatch(form, text.strip()) if form else None
        if not value:
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
        parts = ([tree(match["left"]), tree(match["right"])] if match
                 else [tree(value["expr"])])
    except ValueError:
        return None
    if any(part is None for part in parts):
        return None
    # 값을 물었는데 변수가 남았으면 셈이 아니라 못 푼 식이다. 한쪽만 있는
    # 식을 값처럼 내주면 `3x + 1은 얼마야?` 가 답을 가진 것처럼 보인다.
    if not match and _carries_variable(parts[0]):
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

    roots = [emit(part) for part in parts]
    return {"nodes": nodes, "roots": roots,
            "variable": "x" if match else None, "source": text.strip()}


def _carries_variable(value):
    if value[0] == "variable":
        return True
    if value[0] == "number":
        return False
    return _carries_variable(value[1]) or _carries_variable(value[2])
