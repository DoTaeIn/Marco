"""Source IO builtin lowering shared by the frontend and C backend.

The compiler owns parsing and C type spelling; this module owns the small,
stable contract for the four source calls.  The native implementation lives in
``runtime/language_io.h``.  Lowered nodes use the existing primitive Result
spelling so they fit the current managed value emitter.
"""

from __future__ import annotations


_CALLS = {
    "argc": ((), "si32"),
    "argv": (("si32",), "result:s:s"),
    "read_text": (("s",), "result:s:s"),
    "write_text": (("s", "s"), "result:si32:s"),
}


def _token(node):
    return node[1] if isinstance(node, tuple) and len(node) > 1 else None


def _callee_name(node):
    if not (isinstance(node, tuple) and len(node) == 4 and node[0] == "call"):
        return None
    callee = node[2]
    if isinstance(callee, tuple) and len(callee) == 3 and callee[0] == "name":
        return callee[2]
    return None


def _fail(error, token, message):
    error(token, message)


def lower_io_call(node, expression, env, error):
    """Lower a recognized source IO call, or return ``None`` for other calls.

    ``expression(value, env)`` must return an IR expression containing a
    ``type`` field.  Errors use the frontend's existing ``error(token, text)``
    callback, so source locations stay attached to the original call.
    """
    name = _callee_name(node)
    if name not in _CALLS:
        return None
    args, result_type = _CALLS[name]
    raw_args = node[3]
    if not isinstance(raw_args, list) or len(raw_args) != len(args) or any(field is not None for field, _ in raw_args):
        _fail(error, _token(node), f"{name} expects {len(args)} positional argument(s)" if args else f"{name} expects no arguments")
    lowered = []
    for index, ((_, raw), expected) in enumerate(zip(raw_args, args)):
        value = expression(raw, env)
        if not isinstance(value, dict) or value.get("type") != expected:
            _fail(error, _token(raw), f"{name} argument {index + 1} must be {expected}")
        lowered.append(value)
    return {"kind": "io_call", "type": result_type, "operation": name, "args": lowered}


def _checked_type(check, value):
    result = check(value)
    if isinstance(result, dict):
        return result.get("type")
    return result


def validate_io(node, check, fail):
    """Validate one lowered ``io_call`` node and return its MRL type.

    ``check(child)`` may return a type string or an expression dictionary.
    ``fail(message)`` is called for malformed nodes.
    """
    if not isinstance(node, dict) or set(node) != {"kind", "type", "operation", "args"} or node.get("kind") != "io_call":
        fail("expected io_call expression")
        return None
    name = node.get("operation")
    if not isinstance(name, str):
        fail("unknown IO operation")
        return None
    spec = _CALLS.get(name)
    if spec is None:
        fail("unknown IO operation")
        return None
    expected_args, result_type = spec
    values = node.get("args")
    if node.get("type") != result_type or not isinstance(values, list) or len(values) != len(expected_args):
        fail(f"invalid {name} IO expression")
        return None
    for index, (value, expected) in enumerate(zip(values, expected_args)):
        actual = _checked_type(check, value)
        if actual != expected:
            fail(f"{name} argument {index + 1} must be {expected}")
            return None
    return result_type


def emit_io(node, expr, ctype, add, fresh, own_temp, indent=0):
    """Emit C for one validated IO node and return its temporary variable.

    The backend supplies its normal expression callback, C type mapper, line
    appender, fresh-name allocator, and managed-temporary callback.  The
    returned Result values use ``value_owned=true`` only for successful string
    reads supplied by the native helper; write errors borrow static text.
    """
    if not isinstance(node, dict) or node.get("kind") != "io_call" or node.get("operation") not in _CALLS:
        raise ValueError("invalid IO expression")
    name = node["operation"]
    typ = node["type"]
    values = [expr(value, indent) for value in node["args"]]
    temporary = fresh("io")
    if name == "argc":
        add(f"{ctype(typ)} {temporary} = mrl_io_argc();", indent)
        return own_temp(typ, temporary) if own_temp is not None else temporary
    if name == "argv":
        raw = fresh("io_raw")
        add(f"MrlIoStringResult {raw} = mrl_io_argv({values[0]});", indent)
        add(f"{ctype(typ)} {temporary} = {{0}}; {temporary}.ok = {raw}.ok; {temporary}.value_owned = {raw}.ok;", indent)
        add(f"if ({raw}.ok) {temporary}.value = {raw}.value; else {temporary}.error = mrl_string_copy({raw}.error);", indent)
    elif name == "read_text":
        raw = fresh("io_raw")
        add(f"MrlIoStringResult {raw} = mrl_io_read_utf8({values[0]});", indent)
        add(f"{ctype(typ)} {temporary} = {{0}}; {temporary}.ok = {raw}.ok; {temporary}.value_owned = {raw}.ok;", indent)
        add(f"if ({raw}.ok) {temporary}.value = {raw}.value; else {temporary}.error = mrl_string_copy({raw}.error);", indent)
    else:
        error_name = fresh("io_error")
        add(f"const char *{error_name} = NULL;", indent)
        add(f"{ctype(typ)} {temporary} = {{0}};", indent)
        add(f"if (mrl_io_write_utf8({values[0]}, {values[1]}, &{error_name})) {{", indent)
        add(f"    {temporary}.ok = true; {temporary}.value = (int32_t)strlen({values[1]}); {temporary}.value_owned = false;", indent)
        add("} else {", indent)
        add(f"    {temporary}.ok = false; {temporary}.error = mrl_string_copy({error_name}); {temporary}.value_owned = false;", indent)
        add("}", indent)
    return own_temp(typ, temporary) if own_temp is not None else temporary


__all__ = ["lower_io_call", "validate_io", "emit_io"]
