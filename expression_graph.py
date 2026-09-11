"""Parse complete mathematical expressions into a bounded operation graph.

Python AST is syntax only: no eval, calls, attributes, indexing or execution.
Each node evaluates to an affine pair (variable coefficient, constant).
"""
import ast
from fractions import Fraction
import re


def parse(text, *, grammar=None, numerals=None):
    from verbal_expression import parse as parse_verbal
    verbal = parse_verbal(text, grammar=grammar, numerals=numerals)
    if verbal is not None:
        return verbal
    # Only select a contiguous mathematical region with an explicit operator.
    regions = list(re.finditer(r"[0-9A-Za-z().+*/=−×÷\-\s]+", text))
    regions = [m for m in regions if re.search(r"\d", m.group()) and
               re.search(r"[+*/=−×÷-]", m.group())]
    if len(regions) != 1:
        return None
    match = regions[0]
    source = match.group().strip()
    if len(source) > 512:
        return None
    normalized = source.translate(str.maketrans({"−": "-", "×": "*", "÷": "/"}))
    normalized = re.sub(r"(?<=\d)(?=[A-Za-z])", "*", normalized)
    sides = normalized.split("=")
    if len(sides) > 2:
        return None
    nodes, variables = [], set()

    def visit(node):
        if len(nodes) >= 128:
            raise ValueError("expression_too_large")
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            record = {"op": "number", "value": ast.get_source_segment(current, node)}
        elif isinstance(node, ast.Name) and re.fullmatch("[A-Za-z]", node.id):
            variables.add(node.id)
            record = {"op": "variable", "name": node.id}
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            record = {"op": "neg" if isinstance(node.op, ast.USub) else "pos", "arg": visit(node.operand)}
        elif isinstance(node, ast.BinOp) and type(node.op) in (ast.Add, ast.Sub, ast.Mult, ast.Div):
            record = {"op": {ast.Add: "+", ast.Sub: "-", ast.Mult: "*", ast.Div: "/"}[type(node.op)],
                      "left": visit(node.left), "right": visit(node.right)}
        else:
            raise ValueError("unsupported_expression")
        nodes.append(record)
        return len(nodes) - 1

    roots = []
    try:
        for side in sides:
            current = side.strip()
            roots.append(visit(ast.parse(current, mode="eval").body))
    except (SyntaxError, ValueError, RecursionError):
        return None
    if len(variables) > 1 or (variables and len(roots) != 2):
        return None
    return {"nodes": nodes, "roots": roots, "variable": next(iter(variables), None),
            "source": source}


def solve(graph):
    values, steps = [], []
    for node in graph["nodes"]:
        op = node["op"]
        if op == "number":
            value = (Fraction(0), Fraction(node["value"]))
        elif op == "variable":
            value = (Fraction(1), Fraction(0))
        elif op in ("pos", "neg"):
            a, b = values[node["arg"]]
            value = (a, b) if op == "pos" else (-a, -b)
        else:
            a, b = values[node["left"]]
            c, d = values[node["right"]]
            if op == "+":
                value = (a + c, b + d)
            elif op == "-":
                value = (a - c, b - d)
            elif op == "*" and not (a and c):
                value = (a * d + b * c, b * d)
            elif op == "/" and not c and d:
                value = (a / d, b / d)
            else:
                raise ValueError("nonlinear_or_undefined_expression")
        values.append(value)
        steps.append({"node": len(values) - 1, "operation": op,
                      "coefficient": str(value[0]), "constant": str(value[1])})
    roots = graph["roots"]
    a, b = values[roots[0]]
    if len(roots) == 2:
        c, d = values[roots[1]]
        if a == c:
            raise ValueError("no_unique_solution")
        result = (d - b) / (a - c)
        steps.append({"operation": "isolate", "variable": graph["variable"], "value": str(result)})
    else:
        if a:
            raise ValueError("unbound_variable")
        result = b
    return str(result), steps
