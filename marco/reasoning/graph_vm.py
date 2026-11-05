"""Bounded, data-only graph control primitives for existing reasoning owners.

No language semantics, pack authority, effects, persistence or I/O live here.
"""


import hashlib
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
    "intersect": frozenset(("id", "op", "name", "left", "right", "next")),
    "return": frozenset(("id", "op", "value")),
}
_NAME_FIELDS = ("name", "item", "bindings")
_EDGE_FIELDS = ("next", "body", "done", "yes", "no")
_EXPR_FIELDS = ("value", "source", "left", "right", "pattern")
_PROGRAM_KEYS = frozenset(("schema", "entry", "nodes"))
_COMPUTE_KEYS = frozenset(("op", "args"))
_COMPUTE_ARITY = {
    "split": (2, 2),
    "concat": (1, 256),
    "len": (1, 1),
    "get": (2, 2),
    "slice": (3, 3),
    "find": (2, 2),
    "add": (2, 2),
    "lookup": (3, 3),
}
_CHARGE_UNIT = 64
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


def _int(value):
    return type(value) is int


def _encoded_size(value):
    """Bounded canonical UTF-8 size of an exact plain JSON value."""
    _check_json(value)
    return len(json.dumps(value, ensure_ascii=False, allow_nan=False,
                          sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _validate_expression(expr):
    if type(expr) is not dict or len(expr) != 1:
        raise _Refusal("invalid_expression")
    (tag, arg), = expr.items()
    if tag == "literal":
        return
    if tag == "object":
        if type(arg) is not dict:
            raise _Refusal("invalid_expression")
        for child in arg.values():
            _validate_expression(child)
        return
    if tag == "array":
        if type(arg) is not list:
            raise _Refusal("invalid_expression")
        for child in arg:
            _validate_expression(child)
        return
    if tag == "compute":
        if type(arg) is not dict or arg.keys() != _COMPUTE_KEYS:
            raise _Refusal("invalid_expression")
        op = arg["op"]
        args = arg["args"]
        if type(op) is not str or op not in _COMPUTE_ARITY or type(args) is not list:
            raise _Refusal("invalid_expression")
        low, high = _COMPUTE_ARITY[op]
        if not low <= len(args) <= high:
            raise _Refusal("invalid_expression")
        if op == "lookup":
            first = args[0]
            if (type(first) is not dict or len(first) != 1
                    or next(iter(first)) not in ("input", "var")):
                raise _Refusal("invalid_expression")
        for child in args:
            _validate_expression(child)
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


def validate_value(value):
    """Return a detached plain JSON value under the VM's existing bounds.

    Structural validation only: this does not authorize programs or facts.
    """
    _check_json(value)
    return _copy(value)


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


def _execute(program, inputs, budget, state, rec=None):
    nodes = {node["id"]: node for node in program["nodes"]}
    env = {}
    cursors = {}

    def charge():
        if state[0] >= budget:
            raise _Capacity()
        state[0] += 1

    def charge_units(count):
        for _ in range(count // _CHARGE_UNIT + 1):
            charge()

    def grow(total, value):
        size = _encoded_size(value)
        total += size
        if total > MAXIMUM_PAYLOAD_UTF8_BYTES:
            raise _Refusal("limit")
        charge_units(size)
        return total

    def compute(op, vals):
        if op == "split":
            text, sep = vals
            if type(text) is not str or not _nonempty_str(sep):
                raise _Refusal("invalid_expression")
            charge_units(len(text))
            pieces = text.split(sep, MAXIMUM_SCAN_LENGTH)
            if len(pieces) > MAXIMUM_SCAN_LENGTH:
                raise _Refusal("limit")
            return pieces
        if op == "concat":
            total = 0
            for val in vals:
                if type(val) is not str:
                    raise _Refusal("invalid_expression")
                total += len(val)
                if total > MAXIMUM_PAYLOAD_UTF8_BYTES:
                    raise _Refusal("limit")
            charge_units(total)
            return "".join(vals)
        if op == "len":
            val, = vals
            if type(val) not in (str, list, dict):
                raise _Refusal("invalid_expression")
            return len(val)
        if op == "get":
            container, key = vals
            if type(container) is dict and type(key) is str:
                if key not in container:
                    raise _Refusal("invalid_expression")
                return _copy(container[key])
            if type(container) is list and _int(key):
                if key < 0 or key >= len(container):
                    raise _Refusal("invalid_expression")
                return _copy(container[key])
            raise _Refusal("invalid_expression")
        if op == "slice":
            text, start, end = vals
            if type(text) is not str or not _int(start) or not _int(end):
                raise _Refusal("invalid_expression")
            if not 0 <= start <= end <= len(text):
                raise _Refusal("invalid_expression")
            charge_units(end - start)
            return text[start:end]
        if op == "find":
            text, needle = vals
            if type(text) is not str or not _nonempty_str(needle):
                raise _Refusal("invalid_expression")
            charge_units(len(text))
            return text.find(needle)
        if op == "add":
            left, right = vals
            if not _int(left) or not _int(right):
                raise _Refusal("invalid_expression")
            return left + right
        raise _Refusal("invalid_expression")

    def borrow(ref):
        # Read-only resolution of a validated direct reference; never escapes.
        (tag, path), = ref.items()
        if rec is not None:
            rec.read(tag, path)
        if tag == "input":
            root = inputs
        else:
            if path[0] not in env:
                raise _Refusal("invalid_expression")
            root = env[path[0]]
            path = path[1:]
        charge()
        for comp in path:
            charge()
            if type(comp) is str:
                charge_units(len(comp.encode("utf-8")))
            root = _walk(root, (comp,))
        return root

    def lookup(args):
        ref, key_expr, default_expr = args
        charge()
        container = borrow(ref)
        charge()
        key = evaluate(key_expr)
        total = grow(0, key)
        charge()
        default = evaluate(default_expr)
        grow(total, default)
        if type(container) is not dict or type(key) is not str:
            raise _Refusal("invalid_expression")
        charge_units(len(key.encode("utf-8")))
        if key in container:
            selected = container[key]
        else:
            selected = default
        charge_units(_encoded_size(selected))
        return _copy(selected)

    def evaluate(expr):
        (tag, arg), = expr.items()
        if tag == "literal":
            return _copy(arg)
        if tag == "object":
            charge()
            out = {}
            total = 2
            for key, child in arg.items():
                charge()
                key_size = _encoded_size(key) + 1 + (1 if out else 0)
                total += key_size
                if total > MAXIMUM_PAYLOAD_UTF8_BYTES:
                    raise _Refusal("limit")
                charge_units(key_size)
                val = evaluate(child)
                total = grow(total, val)
                out[key] = val
                _check_json(out)
            _check_json(out)
            return out
        if tag == "array":
            charge()
            out = []
            total = 0
            for child in arg:
                charge()
                val = evaluate(child)
                total = grow(total, val)
                out.append(val)
                _check_json(out)
            _check_json(out)
            return out
        if tag == "compute":
            charge()
            if arg["op"] == "lookup":
                return lookup(arg["args"])
            vals = []
            total = 0
            for child in arg["args"]:
                charge()
                val = evaluate(child)
                total = grow(total, val)
                vals.append(val)
                _check_json(vals)
            result = compute(arg["op"], vals)
            charge_units(_encoded_size(result))
            return result
        if rec is not None:
            rec.read(tag, arg)
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
        if rec is not None:
            rec.begin(nodes[current], state[0])
        _check_json([env, cursors])
        charge()
        node = nodes[current]
        op = node["op"]
        if op == "set":
            val = evaluate(node["value"])
            _check_json(val)
            env[node["name"]] = val
            if rec is not None:
                rec.bind(node["name"], val)
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
                if rec is not None:
                    rec.bind(node["item"], env[node["item"]])
                cursor[1] += 1
                _check_json([env, cursors])
                current = node["body"]
            else:
                del cursors[node_id]
                if rec is not None:
                    rec.mark(None, "scan_exhausted")
                _check_json([env, cursors])
                current = node["done"]
        elif op == "branch":
            left = evaluate(node["left"])
            right = evaluate(node["right"])
            same = _equal(left, right, charge)
            if rec is not None:
                rec.mark(same, None if same else "branch_false")
            current = node["yes"] if same else node["no"]
        elif op == "match":
            pattern = evaluate(node["pattern"])
            value = evaluate(node["value"])
            captures = match(pattern, value)
            if captures is None:
                if rec is not None:
                    rec.mark(False, "match_failed")
                current = node["no"]
            else:
                _check_json(captures)
                env[node["bindings"]] = captures
                if rec is not None:
                    rec.bind(node["bindings"], captures)
                    rec.mark(True, None)
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
            if rec is not None:
                rec.bind(name, candidate)
            _check_json([env, cursors])
            current = node["next"]
        elif op == "intersect":
            left = evaluate(node["left"])
            right = evaluate(node["right"])
            if type(left) is not list or type(right) is not list:
                raise _Refusal("invalid_expression")
            if len(left) > MAXIMUM_SCAN_LENGTH or len(right) > MAXIMUM_SCAN_LENGTH:
                raise _Refusal("limit")
            out = []
            for item in left:
                charge()
                hit = False
                for other in right:
                    if _equal(item, other, charge):
                        hit = True
                        break
                if not hit:
                    continue
                dup = False
                for kept in out:
                    if _equal(item, kept, charge):
                        dup = True
                        break
                if not dup:
                    out.append(item)
            _check_json(out)
            env[node["name"]] = out
            if rec is not None:
                rec.bind(node["name"], out)
            _check_json([env, cursors])
            current = node["next"]
        else:
            val = evaluate(node["value"])
            _check_json(val)
            if rec is not None:
                rec.end(state[0])
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


RECORD_SCHEMA = "marco-graph-vm-receipt-v1"
DEFAULT_TRACE_LIMIT = 128
MAXIMUM_TRACE_LIMIT = 256
_STEP_BYTES = 320
_STEP_ITEMS = 16
_RESERVE_BYTES = 1024
_RESERVE_ITEMS = 32


def _measure(value, depth):
    """Conservative (bytes, items) of a bounded value placed at record depth."""
    items = 0
    stack = [(value, depth)]
    while stack:
        item, level = stack.pop()
        items += 1
        if level > MAXIMUM_JSON_DEPTH or items > MAXIMUM_JSON_ITEMS:
            return None
        if type(item) is list:
            stack.extend((child, level + 1) for child in item)
        elif type(item) is dict:
            stack.extend((child, level + 1) for child in item.values())
    try:
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False,
                              sort_keys=True, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError, UnicodeEncodeError):
        return None
    return size, items


class _Recorder:
    """Temporary bounded step recorder; observes execution, never steers it."""

    def __init__(self, limit):
        self.limit = limit
        self.steps = []
        self.cur = None
        self.cut = None
        self.fatal = None
        self.size = _RESERVE_BYTES
        self.items = _RESERVE_ITEMS

    def _take(self, value, depth, size, items):
        if self.cur is None:
            return False
        got = _measure(value, depth)
        if got is not None:
            size += self.size + got[0]
            items += self.items + got[1]
            if size <= MAXIMUM_PAYLOAD_UTF8_BYTES and items <= MAXIMUM_JSON_ITEMS:
                self.size, self.items = size, items
                return True
        self.cur = None
        self.cut = self.cut or "trace_size_limit"
        return False

    def _finish(self, used, next_node, status="completed", reason=None):
        step = self.cur
        if step is None or not self._take([next_node], 3, 8, 0):
            return
        step["used_after"] = used
        step["next_node"] = next_node
        step["status"] = status
        if reason is not None:
            step["reason"] = reason
        self.steps.append(step)
        self.cur = None

    def begin(self, node, used):
        self._finish(used, node["id"])
        if self.cut is not None:
            return
        if len(self.steps) >= self.limit:
            self.cut = "trace_limit"
            return
        self.cur = {"index": len(self.steps), "node_id": node["id"], "op": node["op"],
                    "used_before": used, "used_after": used, "next_node": None,
                    "status": "completed", "bindings": {}, "reads": [],
                    "branch": None, "reason": None}
        self._take([node["id"], node["op"]], 3, _STEP_BYTES, _STEP_ITEMS)

    def read(self, kind, path):
        if self._take(path, 6, 32, 3):
            self.cur["reads"].append({"kind": kind, "path": _copy(path)})

    def bind(self, name, value):
        if self._take([name, value], 4, 8, 0):
            self.cur["bindings"][name] = _copy(value)

    def mark(self, branch, reason):
        if self.cur is not None:
            self.cur["branch"] = branch
            self.cur["reason"] = reason

    def end(self, used):
        self._finish(used, None)

    def fail(self, used, reason):
        self.fatal = reason
        status = "capacity" if reason == "capacity" else "invalid"
        self._finish(used, None, status, reason)


def _sha256(value):
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False).encode("utf-8")).hexdigest()


def _receipt(result, pins, budget, limit, steps, complete, reason):
    record = {"schema": RECORD_SCHEMA, "program_sha256": pins[0],
              "input_sha256": pins[1], "budget": budget, "trace_limit": limit,
              "steps": steps, "complete": complete, "reason": reason}
    while True:
        try:
            _check_json(record)
            break
        except _Refusal:
            if not steps:
                break
            steps.pop()
            if record["complete"]:
                record["complete"] = False
                record["reason"] = "trace_size_limit"
    return {"result": result, "record": record}


def run_recorded(program, inputs, *, budget=4096, trace_limit=DEFAULT_TRACE_LIMIT):
    """Run once, also returning a bounded diagnostic receipt.

    The receipt describes trace coverage of one execution, not logical truth.
    """
    budget_ok = (type(budget) is int
                 and MINIMUM_BUDGET <= budget <= MAXIMUM_BUDGET)
    limit_ok = type(trace_limit) is int and 1 <= trace_limit <= MAXIMUM_TRACE_LIMIT
    limit = trace_limit if limit_ok else None
    pins = [None, None]
    invalid = _result("invalid", None, 0)
    if not budget_ok:
        return _receipt(invalid, pins, None, limit, [], False, "invalid_budget")
    if not limit_ok:
        return _receipt(invalid, pins, budget, None, [], False, "invalid_trace_limit")
    try:
        normalized = _validate(program)
        pins[0] = _sha256(normalized)
        _check_json(inputs)
        pins[1] = _sha256(inputs)
    except _Refusal as refusal:
        return _receipt(invalid, pins, budget, limit, [], False, str(refusal))
    if budget == 0:
        return _receipt(_result("capacity", None, 0), pins, budget, limit, [],
                        True, "capacity")
    detached_inputs = _copy(inputs)
    state = [0]
    rec = _Recorder(limit)
    try:
        value = _execute(normalized, detached_inputs, budget, state, rec)
        result = _result("completed", _copy(value), state[0])
    except _Capacity:
        rec.fail(state[0], "capacity")
        result = _result("capacity", None, state[0])
    except _Refusal as refusal:
        rec.fail(state[0], str(refusal))
        result = _result("invalid", None, state[0])
    if rec.cut is not None:
        complete, reason = False, rec.cut
    else:
        complete, reason = True, rec.fatal
    return _receipt(result, pins, budget, limit, rec.steps, complete, reason)
