"""Small, checked contract for MRL's unsafe C boundary.

Parsing is deliberately delegated to the existing frontend parser.  The
``parse_extern`` helper consumes that parser's token methods; it does not
introduce another grammar.  Frontend/backend owners can import the lowering,
validation, and emission helpers without coupling the source parser to C text.
"""

from __future__ import annotations

import re


_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_SCALARS = {"si8", "si16", "si32", "si64", "ui8", "ui16", "ui32", "ui64", "f32", "f64", "b", "s"}
_FFI_SCALARS = _SCALARS - {"s"}
_POINTEE = _FFI_SCALARS
_OPS = {"addr", "load", "store"}


def _error(parser, token, message):
    error = getattr(parser, "error", None)
    if error is not None:
        error(token, message)
    raise ValueError(message)


def _valid_symbol(value):
    return isinstance(value, str) and _NAME.fullmatch(value) is not None


def _text(value):
    return value if isinstance(value, str) else getattr(value, "text", None)


def parse_extern(parser):
    """Consume ``extern fn name(params) -> type = "symbol"``.

    The parser must expose the existing ``cur``, ``take``, ``match`` and
    ``typ`` methods.  The returned declaration is intentionally shaped like a
    normal function declaration, with the additional validated C symbol.
    """
    token = parser.take("extern")
    parser.take("fn")
    name = parser.take("name")
    parser.take("(")
    params = []
    if parser.cur().kind != ")":
        while True:
            param = parser.take("name")
            parser.take(":")
            typ = parser.typ()
            params.append((param, typ))
            if not parser.match(","):
                break
    parser.take(")")
    result = parser.typ() if parser.match("->") else None
    parser.take("=")
    symbol = parser.take("string")
    if not _valid_symbol(symbol.text):
        _error(parser, symbol, "extern symbol must be a C identifier")
    return {"token": token, "name": name, "params": params, "return": result, "symbol": symbol.text}


def lower_extern(declaration):
    """Convert parser tokens to token-free neutral declaration IR."""
    if not isinstance(declaration, dict):
        raise ValueError("invalid extern declaration")
    name = _text(declaration.get("name"))
    params = declaration.get("params")
    if not isinstance(name, str) or not isinstance(params, list):
        raise ValueError("invalid extern declaration")
    return {
        "name": name,
        "params": [{"name": _text(param[0]), "type": param[1]} for param in params],
        "return_type": declaration.get("return"),
        "symbol": declaration.get("symbol"),
    }


def _ffi_type(value):
    if isinstance(value, str) and value in _FFI_SCALARS:
        return True
    return isinstance(value, str) and value.startswith("ptr:") and value[4:] in _POINTEE


def validate_extern(declaration, fail):
    """Validate a lowered extern declaration without trusting source metadata."""
    if not isinstance(declaration, dict) or set(declaration) != {"name", "params", "return_type", "symbol"}:
        fail("invalid extern declaration")
        return False
    if not isinstance(declaration["name"], str) or not _NAME.fullmatch(declaration["name"]):
        fail("invalid extern name")
        return False
    if not _valid_symbol(declaration["symbol"]):
        fail("extern symbol must be a C identifier")
        return False
    params = declaration["params"]
    if not isinstance(params, list) or any(not isinstance(item, dict) or set(item) != {"name", "type"} or not isinstance(item["name"], str) or not _NAME.fullmatch(item["name"]) or not _ffi_type(item["type"]) for item in params):
        fail("extern parameters must use scalar or ptr scalar types")
        return False
    if declaration["return_type"] is not None and not _ffi_type(declaration["return_type"]):
        fail("extern return type must use a scalar or ptr scalar type")
        return False
    return True


def _callee_name(node):
    if not (isinstance(node, tuple) and len(node) == 4 and node[0] == "call"):
        return None
    callee = node[2]
    return callee[2] if isinstance(callee, tuple) and len(callee) == 3 and callee[0] == "name" else None


def _token(node):
    return node[1] if isinstance(node, tuple) and len(node) > 1 else None


def _unsafe_context(env, unsafe):
    return bool(unsafe or isinstance(env, dict) and env.get("$unsafe"))


def _externs(env, externs):
    if externs is not None:
        return externs
    return env.get("$externs", {}) if isinstance(env, dict) else {}


def _fail(error, node, message):
    error(_token(node), message)


def lower_ffi_call(node, expression, env, error, externs=None, unsafe=False):
    """Lower an extern or pointer operation, or return ``None`` if unrelated."""
    name = _callee_name(node)
    active = _unsafe_context(env, unsafe)
    if name in _externs(env, externs):
        declaration = _externs(env, externs)[name]
        if not active:
            _fail(error, node, "foreign calls require an unsafe block")
        params = declaration.get("params", [])
        args = node[3]
        if len(args) != len(params) or any(field is not None for field, _ in args):
            _fail(error, node, f"{name} expects {len(params)} positional arguments")
        lowered = []
        for index, ((_, raw), parameter) in enumerate(zip(args, params)):
            expected = parameter["type"]
            value = expression(raw, env)
            if not isinstance(value, dict) or value.get("type") != expected:
                _fail(error, raw, f"foreign argument {index + 1} must be {expected}")
            lowered.append(value)
        return {"kind": "ffi_call", "type": declaration.get("return_type"), "name": name,
                "symbol": declaration["symbol"], "args": lowered, "unsafe": True}
    if name not in _OPS:
        return None
    if not active:
        _fail(error, node, f"{name} requires an unsafe block")
    args = node[3]
    if name == "addr":
        if len(args) != 1 or args[0][0] is not None or not isinstance(args[0][1], tuple) or args[0][1][0] != "name":
            _fail(error, node, "addr expects one mutable local")
        local = args[0][1]
        if local[2] not in env:
            _fail(error, local, "addr expects a local name")
        typ, mutable = env[local[2]][0], env[local[2]][1]
        if typ not in _POINTEE:
            _fail(error, local, "addr requires a scalar local")
        if not mutable:
            _fail(error, local, "addr requires a mutable local")
        return {"kind": "ffi_addr", "type": "ptr:" + typ, "name": local[2], "unsafe": True}
    expected = 1 if name == "load" else 2
    if len(args) != expected or any(field is not None for field, _ in args):
        _fail(error, node, f"{name} expects {expected} positional arguments")
    pointer = expression(args[0][1], env)
    pointer_type = pointer.get("type") if isinstance(pointer, dict) else None
    if not isinstance(pointer_type, str) or not pointer_type.startswith("ptr:") or pointer_type[4:] not in _POINTEE:
        _fail(error, args[0][1], f"{name} requires a scalar pointer")
    pointee = pointer_type[4:]
    if name == "load":
        return {"kind": "ffi_load", "type": pointee, "pointer": pointer, "unsafe": True}
    value = expression(args[1][1], env)
    if not isinstance(value, dict) or value.get("type") != pointee:
        _fail(error, args[1][1], f"store value must be {pointee}")
    return {"kind": "ffi_store", "type": None, "pointer": pointer, "value": value, "unsafe": True}


def _checked(check, value):
    result = check(value)
    return result.get("type") if isinstance(result, dict) else result


def _fail_validation(fail, message):
    fail(message)


def validate_ffi(node, check, fail, externs=None, unsafe=False, locals=None):
    """Validate raw FFI IR and independently enforce unsafe context."""
    kind = node.get("kind") if isinstance(node, dict) else None
    if not isinstance(kind, str) or not kind.startswith("ffi_"):
        _fail_validation(fail, "expected FFI expression")
        return None
    if not unsafe or node.get("unsafe") is not True:
        _fail_validation(fail, "FFI expressions require an unsafe block")
        return None
    if kind == "ffi_addr":
        if set(node) != {"kind", "type", "name", "unsafe"}:
            _fail_validation(fail, "invalid addr expression")
            return None
        typ = node.get("type")
        local_name = node.get("name")
        local = locals.get(local_name) if isinstance(locals, dict) else None
        if not isinstance(typ, str) or not typ.startswith("ptr:") or typ[4:] not in _POINTEE or not isinstance(local_name, str) or not local or local[0] != typ[4:] or not local[1]:
            _fail_validation(fail, "invalid addr expression")
            return None
        return typ
    if kind == "ffi_load":
        if set(node) != {"kind", "type", "pointer", "unsafe"}:
            _fail_validation(fail, "invalid load expression")
            return None
        pointer = node.get("pointer")
        typ = node.get("type")
        if not _ffi_type(typ) or typ.startswith("ptr:"):
            _fail_validation(fail, "invalid load type")
            return None
        pointer_type = _checked(check, pointer)
        if pointer_type != "ptr:" + typ:
            _fail_validation(fail, "invalid load pointer")
            return None
        return typ
    if kind == "ffi_store":
        if set(node) != {"kind", "type", "pointer", "value", "unsafe"}:
            _fail_validation(fail, "invalid store expression")
            return None
        pointer, value = node.get("pointer"), node.get("value")
        pointer_type = _checked(check, pointer)
        if not isinstance(pointer_type, str) or not pointer_type.startswith("ptr:") or _checked(check, value) != pointer_type[4:] or node.get("type") is not None:
            _fail_validation(fail, "invalid store expression")
            return None
        return None
    if kind == "ffi_call":
        if set(node) != {"kind", "type", "name", "symbol", "args", "unsafe"}:
            _fail_validation(fail, "invalid foreign call")
            return None
        symbol, name, args = node.get("symbol"), node.get("name"), node.get("args")
        declaration = externs.get(name) if isinstance(externs, dict) else None
        if declaration is None or declaration.get("symbol") != symbol or not _valid_symbol(symbol) or not isinstance(args, list):
            _fail_validation(fail, "invalid foreign call")
            return None
        params = declaration.get("params", [])
        if len(args) != len(params) or any(_checked(check, value) != parameter["type"] for value, parameter in zip(args, params)) or node.get("type") != declaration.get("return_type"):
            _fail_validation(fail, "foreign call argument or return type mismatch")
            return None
        return node["type"]
    _fail_validation(fail, "unknown FFI expression")
    return None


def emit_ffi(node, expr, ctype, add, fresh, own_temp=None, indent=0):
    """Emit checked C for a validated FFI node.

    Pointer values are intentionally returned as unmanaged C pointers.  The
    caller must keep the addressed local alive; no callback or aggregate ABI is
    inferred here.
    """
    kind = node.get("kind") if isinstance(node, dict) else None
    if kind == "ffi_call":
        values = [expr(value, indent) for value in node["args"]]
        call = f"{node['symbol']}({', '.join(values)})"
        if node["type"] is None:
            add(call + ";", indent)
            return None
        name = fresh("ffi")
        add(f"{ctype(node['type'])} {name} = {call};", indent)
        return own_temp(node["type"], name) if own_temp else name
    if kind == "ffi_addr":
        name = fresh("ptr")
        add(f"{ctype(node['type'])} {name} = &{node['name']};", indent)
        return name
    if kind == "ffi_load":
        pointer = expr(node["pointer"], indent)
        name = fresh("load")
        add(f"{ctype(node['type'])} {name} = *{pointer};", indent)
        return name
    if kind == "ffi_store":
        pointer = expr(node["pointer"], indent)
        value = expr(node["value"], indent)
        add(f"*{pointer} = {value};", indent)
        return None
    raise ValueError("invalid FFI expression")


__all__ = ["parse_extern", "lower_extern", "validate_extern", "lower_ffi_call", "validate_ffi", "emit_ffi"]
