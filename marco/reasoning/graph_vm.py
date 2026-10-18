"""Bounded, data-only graph control primitives for existing reasoning owners.

No language semantics, pack authority, effects, persistence or I/O live here.
"""


import json


PROGRAM_SCHEMA = "marco-graph-vm-program-v1"
RESULT_SCHEMA = "marco-graph-vm-result-v1"

MAXIMUM_BUDGET = 1000000
MINIMUM_BUDGET = 0
MAXIMUM_PROGRAM_NODES = 256
MAXIMUM_PAYLOAD_UTF8_BYTES = 131072
MAXIMUM_JSON_DEPTH = 24
MAXIMUM_JSON_ITEMS = 8192
MAXIMUM_APPEND_LENGTH = 256
MAXIMUM_SCAN_LENGTH = 256

_NODE_KEYS = {
    "set": frozenset(("id", "op", "name", "value", "next")),
    "scan": frozenset(("id", "op", "source", "item", "body", "done")),
    "branch": frozenset(("id", "op", "left", "right", "yes", "no")),
    "match": frozenset(("id", "op", "pattern", "value", "bindings", "yes", "no")),
    "append": frozenset(("id", "op", "name", "value", "next")),
    "return": frozenset(("id", "op", "value")),
}
_NAME_FIELDS = ("name", "item", "bindings")
_EDGE_FIELDS = ("next", "body", "done", "yes", "no")
_EXPR_FIELDS = ("value", "source", "left", "right", "pattern")
_PROGRAM_KEYS = frozenset(("schema", "entry", "nodes"))
_MAX_INT_BITS = 8 * MAXIMUM_PAYLOAD_UTF8_BYTES


class _Refusal(ValueError):
    """Expected VM refusal carrying one fixed enum string."""


class _Capacity(Exception):
    """Budget exhausted before a charged operation."""


def _check_json(value):
    """Iteratively verify exact plain JSON within host bounds."""
    size = 0
    items = 0
    stack = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if depth > MAXIMUM_JSON_DEPTH:
            raise _Refusal("limit")
        items += 1
        if items > MAXIMUM_JSON_ITEMS:
            raise _Refusal("limit")
        kind = type(item)
        if item is None:
            size += 4
        elif kind is bool:
            size += 5
        elif kind is int:
            bits = item.bit_length()
            if bits > _MAX_INT_BITS:
                raise _Refusal("limit")
            size += bits // 3 + 2
        elif kind is str:
            if len(item) > MAXIMUM_PAYLOAD_UTF8_BYTES:
                raise _Refusal("limit")
            try:
                size += len(item.encode("utf-8")) + 2
            except UnicodeEncodeError:
                raise _Refusal("invalid_payload") from None
        elif kind is list:
            size += 2 + len(item)
            if len(item) > MAXIMUM_JSON_ITEMS:
                raise _Refusal("limit")
            for child in item:
                stack.append((child, depth + 1))
        elif kind is dict:
            size += 2 + len(item)
            if len(item) > MAXIMUM_JSON_ITEMS:
                raise _Refusal("limit")
            for key, child in item.items():
                if type(key) is not str:
                    raise _Refusal("invalid_payload")
                if len(key) > MAXIMUM_PAYLOAD_UTF8_BYTES:
                    raise _Refusal("limit")
                try:
                    size += len(key.encode("utf-8")) + 3
                except UnicodeEncodeError:
                    raise _Refusal("invalid_payload") from None
                stack.append((child, depth + 1))
        else:
            raise _Refusal("invalid_payload")
        if size > MAXIMUM_PAYLOAD_UTF8_BYTES:
            raise _Refusal("limit")
    # Structural prewalk bounded the work before canonical serialization.
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False,
                             sort_keys=True, separators=(",", ":")).encode("utf-8")
    except (ValueError, UnicodeEncodeError):
        raise _Refusal("invalid_payload") from None
    if len(encoded) > MAXIMUM_PAYLOAD_UTF8_BYTES:
        raise _Refusal("limit")


def _copy(value):
    """Detached copy of an already bounded JSON value (depth <= 24)."""
    kind = type(value)
    if kind is list:
        return [_copy(child) for child in value]
    if kind is dict:
        return {key: _copy(child) for key, child in value.items()}
    return value


def _equal(left, right, charge=None):
    """Exact-type structural equality, iterative."""
    stack = [(left, right)]
    while stack:
        if charge is not None:
            charge()
        a, b = stack.pop()
        if type(a) is not type(b):
            return False
        if type(a) is list:
            if len(a) != len(b):
                return False
            stack.extend(zip(a, b))
        elif type(a) is dict:
            if a.keys() != b.keys():
                return False
            for key in a:
                stack.append((a[key], b[key]))
        elif a != b:
            return False
    return True


def _nonempty_str(value):
    return type(value) is str and value != ""


def _validate_expression(expr):
    if type(expr) is not dict or len(expr) != 1:
        raise _Refusal("invalid_expression")
    (tag, arg), = expr.items()
    if tag == "literal":
        return
    if tag not in ("input", "var"):
        raise _Refusal("invalid_expression")
    if type(arg) is not list:
        raise _Refusal("invalid_expression")
    path = arg
    if tag == "var":
        if not arg or not _nonempty_str(arg[0]):
            raise _Refusal("invalid_expression")
        path = arg[1:]
    for comp in path:
        if type(comp) is str:
            continue
        if type(comp) is int and comp >= 0:
            continue
        raise _Refusal("invalid_expression")


def _validate(program):
    _check_json(program)
    if type(program) is not dict or program.keys() != _PROGRAM_KEYS:
        raise _Refusal("invalid_program")
    if program["schema"] != PROGRAM_SCHEMA or type(program["schema"]) is not str:
        raise _Refusal("invalid_program")
    entry = program["entry"]
    nodes = program["nodes"]
    if not _nonempty_str(entry) or type(nodes) is not list:
        raise _Refusal("invalid_program")
    if not nodes or len(nodes) > MAXIMUM_PROGRAM_NODES:
        raise _Refusal("limit")
    ids = set()
    for node in nodes:
        if type(node) is not dict:
            raise _Refusal("invalid_node")
        op = node.get("op")
        if type(op) is not str or op not in _NODE_KEYS:
            raise _Refusal("invalid_node")
        if node.keys() != _NODE_KEYS[op]:
            raise _Refusal("invalid_node")
        node_id = node["id"]
        if not _nonempty_str(node_id) or node_id in ids:
            raise _Refusal("invalid_node")
        ids.add(node_id)
        for field in _NAME_FIELDS:
            if field in node and not _nonempty_str(node[field]):
                raise _Refusal("invalid_node")
        for field in _EDGE_FIELDS:
            if field in node and not _nonempty_str(node[field]):
                raise _Refusal("invalid_edge")
        for field in _EXPR_FIELDS:
            if field in node:
                _validate_expression(node[field])
    if entry not in ids:
        raise _Refusal("invalid_edge")
    for node in nodes:
        for field in _EDGE_FIELDS:
            if field in node and node[field] not in ids:
                raise _Refusal("invalid_edge")
    return _copy(program)


def validate_program(program):
    return _validate(program)


def _walk(value, path):
    for comp in path:
        if type(comp) is str:
            if type(value) is not dict or comp not in value:
                raise _Refusal("invalid_expression")
            value = value[comp]
        else:
            if type(value) is not list or comp >= len(value):
                raise _Refusal("invalid_expression")
            value = value[comp]
    return value


def _execute(program, inputs, budget, state):
    nodes = {node["id"]: node for node in program["nodes"]}
    env = {}
    cursors = {}

    def charge():
        if state[0] >= budget:
            raise _Capacity()
        state[0] += 1

    def evaluate(expr):
        (tag, arg), = expr.items()
        if tag == "literal":
            return _copy(arg)
        if tag == "input":
            return _copy(_walk(inputs, arg))
        if arg[0] not in env:
            raise _Refusal("invalid_expression")
        return _copy(_walk(env[arg[0]], arg[1:]))

    def match(pattern, value):
        captures = {}
        stack = [(pattern, value)]
        while stack:
            charge()
            p, v = stack.pop()
            if (type(p) is dict and len(p) == 1 and "capture" in p
                    and _nonempty_str(p["capture"])):
                name = p["capture"]
                if name in captures:
                    if not _equal(captures[name], v, charge):
                        return None
                else:
                    captures[name] = _copy(v)
                continue
            if type(p) is not type(v):
                return None
            if type(p) is dict:
                if p.keys() != v.keys():
                    return None
                for key in p:
                    stack.append((p[key], v[key]))
            elif type(p) is list:
                if len(p) != len(v):
                    return None
                stack.extend(zip(p, v))
            elif p != v:
                return None
        return captures

    current = program["entry"]
    while True:
        # Bound the aggregate retained local state, including scan snapshots.
        _check_json([env, cursors])
        charge()
        node = nodes[current]
        op = node["op"]
        if op == "set":
            val = evaluate(node["value"])
            _check_json(val)
            env[node["name"]] = val
            _check_json([env, cursors])
            current = node["next"]
        elif op == "scan":
            node_id = node["id"]
            if node_id not in cursors:
                source = evaluate(node["source"])
                if type(source) is not list:
                    raise _Refusal("invalid_expression")
                if len(source) > MAXIMUM_SCAN_LENGTH:
                    raise _Refusal("limit")
                _check_json(source)
                cursors[node_id] = [source, 0]
                _check_json([env, cursors])
            cursor = cursors[node_id]
            if cursor[1] < len(cursor[0]):
                charge()
                env[node["item"]] = _copy(cursor[0][cursor[1]])
                cursor[1] += 1
                _check_json([env, cursors])
                current = node["body"]
            else:
                del cursors[node_id]
                _check_json([env, cursors])
                current = node["done"]
        elif op == "branch":
            left = evaluate(node["left"])
            right = evaluate(node["right"])
            current = node["yes"] if _equal(left, right, charge) else node["no"]
        elif op == "match":
            pattern = evaluate(node["pattern"])
            value = evaluate(node["value"])
            captures = match(pattern, value)
            if captures is None:
                current = node["no"]
            else:
                _check_json(captures)
                env[node["bindings"]] = captures
                _check_json([env, cursors])
                current = node["yes"]
        elif op == "append":
            name = node["name"]
            if name not in env or type(env[name]) is not list:
                raise _Refusal("invalid_node")
            val = evaluate(node["value"])
            target = env[name]
            if len(target) >= MAXIMUM_APPEND_LENGTH:
                raise _Refusal("limit")
            candidate = target + [val]
            _check_json(candidate)
            env[name] = candidate
            _check_json([env, cursors])
            current = node["next"]
        else:
            val = evaluate(node["value"])
            _check_json(val)
            return val


def _result(status, value, used):
    return {"schema": RESULT_SCHEMA, "status": status, "value": value, "used": used}


def run(program, inputs, *, budget=4096):
    if type(budget) is not int or budget < MINIMUM_BUDGET or budget > MAXIMUM_BUDGET:
        return _result("invalid", None, 0)
    try:
        normalized = _validate(program)
        _check_json(inputs)
    except _Refusal:
        return _result("invalid", None, 0)
    if budget == 0:
        return _result("capacity", None, 0)
    detached_inputs = _copy(inputs)
    state = [0]
    try:
        value = _execute(normalized, detached_inputs, budget, state)
    except _Capacity:
        return _result("capacity", None, state[0])
    except _Refusal:
        return _result("invalid", None, state[0])
    return _result("completed", _copy(value), state[0])
