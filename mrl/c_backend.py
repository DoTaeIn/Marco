"""C11 reference backend for the MRL bootstrap IR."""

import re


_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_TYPES = {"si32", "b"}
_ARITHMETIC = {"+", "-", "*", "/", "%"}
_COMPARE = {"==", "!=", "<", "<=", ">", ">="}
_SCALARS = {"si8", "si16", "si32", "si64", "ui8", "ui16", "ui32", "ui64", "f32", "f64", "b", "s"}
_BUILTIN_ENUMS = {"InterpretationStatus": ("selected", "ambiguous", "unknown", "contradicted", "incomplete"), "EpistemicState": ("known", "unknown", "ambiguous", "contradicted", "withdrawn", "incomplete")}
_I32_MIN, _I32_MAX = -(2**31), 2**31 - 1


def _fail(where, message):
    raise ValueError(f"invalid IR {where}: {message}")


def _object(value, where, keys):
    if not isinstance(value, dict) or set(value) != set(keys):
        _fail(where, "unexpected schema")
    return value


def _name(value, where):
    if not isinstance(value, str) or not _NAME.fullmatch(value):
        _fail(where, "invalid identifier")
    return value


def _type(value, where, void=False):
    if value is None and void:
        return value
    if not isinstance(value, str) or value not in _TYPES:
        _fail(where, "invalid type")
    return value


def _validate_expr(expr, functions, values, where):
    if not isinstance(expr, dict):
        _fail(where, "unexpected schema")
    fields = {"literal": ("value",), "name": ("name",), "binary": ("op", "left", "right"),
              "unary": ("op", "value"), "call": ("name", "args")}
    if not isinstance(expr.get("kind"), str) or expr["kind"] not in fields:
        _fail(where, "unknown expression kind")
    _object(expr, where, ("kind", "type") + fields[expr["kind"]])
    kind, typ = expr["kind"], _type(expr["type"], where + ".type", void=True)
    if kind == "literal":
        if typ not in _TYPES:
            _fail(where, "literal cannot be void")
        if typ == "si32" and (type(expr["value"]) is not int or not _I32_MIN <= expr["value"] <= _I32_MAX):
            _fail(where, "invalid si32 literal")
        if typ == "b" and type(expr["value"]) is not bool:
            _fail(where, "invalid boolean literal")
        return typ
    if kind == "name":
        if typ not in _TYPES:
            _fail(where, "name cannot be void")
        name = _name(expr["name"], where + ".name")
        if name not in values or typ != values[name][0]:
            _fail(where, "unknown name or incorrect type")
        return typ
    if kind == "unary":
        if expr["op"] != "-" or typ != "si32" or _validate_expr(expr["value"], functions, values, where + ".value") != "si32":
            _fail(where, "invalid unary expression")
        return typ
    if kind == "binary":
        op = expr["op"]
        if not isinstance(op, str):
            _fail(where, "invalid binary operator")
        left = _validate_expr(expr["left"], functions, values, where + ".left")
        right = _validate_expr(expr["right"], functions, values, where + ".right")
        if op in _ARITHMETIC and typ == left == right == "si32":
            return typ
        if op in _COMPARE and left == right == "si32" and typ == "b":
            return typ
        if op in {"==", "!="} and left == right == "b" and typ == "b":
            return typ
        _fail(where, "invalid binary expression")
    if kind == "call":
        name = _name(expr["name"], where + ".name")
        if name not in functions:
            _fail(where, "unknown function")
        params, return_type = functions[name]
        if typ != return_type or not isinstance(expr["args"], list) or len(expr["args"]) != len(params):
            _fail(where, "invalid call")
        for index, (arg, expected) in enumerate(zip(expr["args"], params)):
            if _validate_expr(arg, functions, values, f"{where}.args[{index}]") != expected:
                _fail(where, "call argument type mismatch")
        return typ
    _fail(where, "unknown expression kind")


def _validate_block(statements, functions, values, return_type, where, version):
    if not isinstance(statements, list):
        _fail(where, "body must be a list")
    local, returned = values.copy(), False
    schemas = {
        "let": ("kind", "name", "type", "mutable", "value"), "assign": ("kind", "name", "value"),
        "return": ("kind", "value"), "expr": ("kind", "value"),
        "if": ("kind", "condition", "then", "else"), "while": ("kind", "condition", "body"),
        "for": ("kind", "name", "start", "stop", "body"),
    }
    if version == 1:
        for kind in ("if", "while", "for"):
            del schemas[kind]
    for index, statement in enumerate(statements):
        sw = f"{where}[{index}]"
        if returned:
            _fail(sw, "statement after definite return")
        if not isinstance(statement, dict) or not isinstance(statement.get("kind"), str) or statement["kind"] not in schemas:
            _fail(sw, "unknown statement kind")
        kind = statement["kind"]
        _object(statement, sw, schemas[kind])
        if kind == "let":
            name, typ = _name(statement["name"], sw + ".name"), _type(statement["type"], sw + ".type")
            if name in local or type(statement["mutable"]) is not bool:
                _fail(sw, "duplicate name or invalid mutability")
            if _validate_expr(statement["value"], functions, local, sw + ".value") != typ:
                _fail(sw, "initializer type mismatch")
            local[name] = (typ, statement["mutable"])
        elif kind == "assign":
            name = _name(statement["name"], sw + ".name")
            if name not in local or not local[name][1]:
                _fail(sw, "assignment to unknown or immutable name")
            if _validate_expr(statement["value"], functions, local, sw + ".value") != local[name][0]:
                _fail(sw, "assignment type mismatch")
        elif kind == "return":
            value = statement["value"]
            if return_type is None:
                if value is not None:
                    _fail(sw, "void function cannot return a value")
            elif value is None or _validate_expr(value, functions, local, sw + ".value") != return_type:
                _fail(sw, "return type mismatch")
            returned = True
        elif kind == "expr":
            _validate_expr(statement["value"], functions, local, sw + ".value")
        elif kind == "if":
            if _validate_expr(statement["condition"], functions, local, sw + ".condition") != "b":
                _fail(sw, "if condition must be b")
            then_returned = _validate_block(statement["then"], functions, local, return_type, sw + ".then", version)
            else_returned = _validate_block(statement["else"], functions, local, return_type, sw + ".else", version)
            returned = then_returned and else_returned
        elif kind == "while":
            if _validate_expr(statement["condition"], functions, local, sw + ".condition") != "b":
                _fail(sw, "while condition must be b")
            _validate_block(statement["body"], functions, local, return_type, sw + ".body", version)
        else:
            name = _name(statement["name"], sw + ".name")
            if name in local:
                _fail(sw, "for variable shadows visible name")
            if _validate_expr(statement["start"], functions, local, sw + ".start") != "si32" or _validate_expr(statement["stop"], functions, local, sw + ".stop") != "si32":
                _fail(sw, "for bounds must be si32")
            scoped = local.copy(); scoped[name] = ("si32", False)
            _validate_block(statement["body"], functions, scoped, return_type, sw + ".body", version)
    return returned


def _validate_functions(ir):
    functions = {}
    for index, function in enumerate(ir["functions"]):
        where = f"functions[{index}]"
        _object(function, where, ("name", "params", "return_type", "body"))
        name = _name(function["name"], where + ".name")
        if name in functions or not isinstance(function["params"], list):
            _fail(where, "duplicate function or invalid parameters")
        params, names = [], set()
        for pindex, param in enumerate(function["params"]):
            _object(param, f"{where}.params[{pindex}]", ("name", "type"))
            pname = _name(param["name"], f"{where}.params[{pindex}].name")
            if pname in names:
                _fail(where, "duplicate parameter")
            names.add(pname); params.append(_type(param["type"], f"{where}.params[{pindex}].type"))
        functions[name] = (params, _type(function["return_type"], where + ".return_type", void=True))
    if functions.get("main") != ([], "si32"):
        _fail("program", "requires main() -> si32")
    for index, function in enumerate(ir["functions"]):
        scope = {param["name"]: (param["type"], True) for param in function["params"]}
        returned = _validate_block(function["body"], functions, scope, function["return_type"], f"functions[{index}].body", ir["version"])
        if function["return_type"] is not None and not returned:
            _fail(f"functions[{index}]", "non-void function must definitely return")
    return functions


def _validate(ir):
    _object(ir, "program", ("version", "functions"))
    if type(ir["version"]) is not int or ir["version"] not in {1, 2} or not isinstance(ir["functions"], list):
        _fail("program", "expected version 1 or 2 and functions")
    return _validate_functions(ir)


def _legacy_emit_c(ir):
    """Validate MRL IR v1/v2 and emit portable checked C11."""
    return _emit_c(ir, _validate(ir))


def _emit_c(ir, functions):
    ctype = lambda typ: "int32_t" if typ == "si32" else "bool"
    fn_names = {name: f"mrl_fn_{index}" for index, name in enumerate(functions)}
    lines = [
        "#include <stdbool.h>", "#include <stdint.h>", "#include <stdio.h>", "#include <stdlib.h>", "#include <inttypes.h>", "",
        "static void mrl_overflow(void) { fputs(\"MRL si32 overflow\\n\", stderr); exit(1); }",
        "static int32_t mrl_add(int32_t a, int32_t b) { int64_t r = (int64_t)a + b; if (r < INT32_MIN || r > INT32_MAX) mrl_overflow(); return (int32_t)r; }",
        "static int32_t mrl_sub(int32_t a, int32_t b) { int64_t r = (int64_t)a - b; if (r < INT32_MIN || r > INT32_MAX) mrl_overflow(); return (int32_t)r; }",
        "static int32_t mrl_mul(int32_t a, int32_t b) { int64_t r = (int64_t)a * b; if (r < INT32_MIN || r > INT32_MAX) mrl_overflow(); return (int32_t)r; }",
        "static int32_t mrl_neg(int32_t a) { int64_t r = -(int64_t)a; if (r < INT32_MIN || r > INT32_MAX) mrl_overflow(); return (int32_t)r; }", "",
    ]
    def signature(function):
        params = ", ".join(f"{ctype(p['type'])} mrl_p_{index}" for index, p in enumerate(function["params"])) or "void"
        return "void" if function["return_type"] is None else ctype(function["return_type"]), params
    for function in ir["functions"]:
        result, params = signature(function); lines.append(f"static {result} {fn_names[function['name']]}({params});")
    horn_queries = []
    def collect_horn(value):
        if isinstance(value, dict):
            if value.get("kind") == "horn_query": horn_queries.append(value)
            for child in value.values(): collect_horn(child)
        elif isinstance(value, list):
            for child in value: collect_horn(child)
    if ir["version"] == 4:
        collect_horn(ir["functions"])
        if horn_queries:
            from .horn_bridge import emit_support
            lines.append(emit_support(horn_queries))
        wrappers = []
        for row in ir["functions"]:
            def collect_heuristic(value):
                if isinstance(value, dict):
                    if value.get("kind") in {"graph_find", "graph_find_all"} and value.get("heuristic") is not None: wrappers.append((value["graph"], value["heuristic"]))
                    for child in value.values(): collect_heuristic(child)
                elif isinstance(value, list):
                    for child in value: collect_heuristic(child)
            collect_heuristic(row["body"])
        for graph, heuristic in dict.fromkeys(wrappers):
            index = graph_ids[graph] - 1
            node_struct = struct_ids[ir["graphs"][index]["node_type"]]
            lines.append(f"static int32_t mrl_heuristic_{index}_{fn_names[heuristic]}(MrlNode a, MrlNode b) {{ return {fn_names[heuristic]}(*((MrlStruct{node_struct} *)mrl_graph_node_payload(&mrl_graph_{index}, a)), *((MrlStruct{node_struct} *)mrl_graph_node_payload(&mrl_graph_{index}, b))); }}")
    lines.append("")
    for function in ir["functions"]:
        counter, values = [0], {param["name"]: f"mrl_p_{index}" for index, param in enumerate(function["params"])}
        def fresh(prefix):
            name = f"mrl_{prefix}_{counter[0]}"; counter[0] += 1
            return name
        def add(text, indent):
            lines.append("    " * indent + text)
        def expression(node, indent, scope):
            kind, typ = node["kind"], node["type"]
            if kind == "literal":
                value = "true" if node["value"] is True else "false" if node["value"] is False else "INT32_MIN" if node["value"] == _I32_MIN else str(node["value"])
                name = fresh("t"); add(f"{ctype(typ)} {name} = {value};", indent); return name
            if kind == "enum":
                name = fresh("t"); add(f"int32_t {name} = {info['$enums'][typ[5:]].index(node['member'])};", indent); return name
            if kind == "name": return scope[node["name"]]
            if kind == "unary":
                value = expression(node["value"], indent, scope); name = fresh("t")
                add(f"int32_t {name} = mrl_neg({value});", indent); return name
            if kind == "binary":
                left = expression(node["left"], indent, scope); right = expression(node["right"], indent, scope); name = fresh("t")
                if node["op"] in _ARITHMETIC:
                    helper = {"+": "mrl_add", "-": "mrl_sub", "*": "mrl_mul"}[node["op"]]
                    add(f"int32_t {name} = {helper}({left}, {right});", indent)
                else: add(f"bool {name} = {left} {node['op']} {right};", indent)
                return name
            if kind == "cast":
                value, name, source = expr(node["value"], indent, scope), fresh("t"), node["value"]["type"]
                integer = {"si8": ("INT8_MIN", "INT8_MAX"), "si16": ("INT16_MIN", "INT16_MAX"), "si32": ("INT32_MIN", "INT32_MAX"), "si64": ("INT64_MIN", "INT64_MAX"), "ui8": ("0", "UINT8_MAX"), "ui16": ("0", "UINT16_MAX"), "ui32": ("0", "UINT32_MAX"), "ui64": ("0", "UINT64_MAX")}
                if typ in integer:
                    lo, hi = integer[typ]
                    if source.startswith("f"):
                        upper = {"si8":"128.0", "si16":"32768.0", "si32":"2147483648.0", "si64":"9223372036854775808.0", "ui8":"256.0", "ui16":"65536.0", "ui32":"4294967296.0", "ui64":"18446744073709551616.0"}[typ]
                        add(f"if (!isfinite({value}) || {value} < ({ctype(source)})({lo}) || {value} >= ({ctype(source)}){upper} || trunc({value}) != {value}) mrl_runtime_fail(\"MRL checked cast\");", indent)
                    elif source.startswith("ui") and typ.startswith("si"):
                        add(f"if ((uint64_t){value} > (uint64_t){hi}) mrl_runtime_fail(\"MRL checked cast\");", indent)
                    elif source.startswith("si") and typ.startswith("ui"):
                        add(f"if ({value} < 0 || (uint64_t){value} > (uint64_t){hi}) mrl_runtime_fail(\"MRL checked cast\");", indent)
                    elif source.startswith("si"):
                        add(f"if ((int64_t){value} < (int64_t){lo} || (int64_t){value} > (int64_t){hi}) mrl_runtime_fail(\"MRL checked cast\");", indent)
                    elif source.startswith("ui"):
                        add(f"if ((uint64_t){value} > (uint64_t){hi}) mrl_runtime_fail(\"MRL checked cast\");", indent)
                    else:
                        add(f"if ({value} < ({ctype(source)})({lo}) || {value} > ({ctype(source)})({hi})) mrl_runtime_fail(\"MRL checked cast\");", indent)
                elif typ == "f32":
                    add(f"if (!isfinite((double){value}) || (double){value} > FLT_MAX || (double){value} < -FLT_MAX) mrl_runtime_fail(\"MRL checked cast\");", indent)
                add(f"{ctype(typ)} {name} = ({ctype(typ)}){value};", indent); return name
            args = [expression(arg, indent, scope) for arg in node["args"]]
            call = f"{fn_names[node['name']]}({', '.join(args)})"
            if typ is None: add(call + ";", indent); return None
            name = fresh("t"); add(f"{ctype(typ)} {name} = {call};", indent); return name
        def block(statements, indent, scope):
            for statement in statements:
                kind = statement["kind"]
                if kind == "let":
                    value = expression(statement["value"], indent, scope); name = fresh("v"); scope[statement["name"]] = name
                    add(f"{ctype(statement['type'])} {name} = {value};", indent)
                elif kind == "assign":
                    value = expression(statement["value"], indent, scope); add(f"{scope[statement['name']]} = {value};", indent)
                elif kind == "return":
                    if statement["value"] is None: add("return;", indent)
                    else:
                        value = expression(statement["value"], indent, scope); add(f"return {value};", indent)
                elif kind == "expr": expression(statement["value"], indent, scope)
                elif kind == "if":
                    condition = expression(statement["condition"], indent, scope); add(f"if ({condition}) {{", indent)
                    block(statement["then"], indent + 1, scope.copy()); add("} else {", indent)
                    block(statement["else"], indent + 1, scope.copy()); add("}", indent)
                elif kind == "while":
                    add("while (true) {", indent); condition = expression(statement["condition"], indent + 1, scope)
                    add(f"if (!{condition}) break;", indent + 1); block(statement["body"], indent + 1, scope.copy()); add("}", indent)
                else:
                    start_value = expression(statement["start"], indent, scope); start = fresh("bound")
                    add(f"int32_t {start} = {start_value};", indent)
                    stop_value = expression(statement["stop"], indent, scope); stop = fresh("bound")
                    add(f"int32_t {stop} = {stop_value};", indent)
                    index, variable = fresh("range"), fresh("v")
                    add(f"for (int64_t {index} = {start}; {index} < (int64_t){stop}; ++{index}) {{", indent)
                    add(f"const int32_t {variable} = (int32_t){index};", indent + 1)
                    scoped = scope.copy(); scoped[statement["name"]] = variable
                    block(statement["body"], indent + 1, scoped); add("}", indent)
        result, params = signature(function); lines.append(f"static {result} {fn_names[function['name']]}({params}) {{")
        block(function["body"], 1, values); lines.extend(["}", ""])
    lines.extend(["int main(void) {", f"    int32_t result = {fn_names['main']}();", '    printf("%" PRId32 "\\n", result);', "    return 0;", "}", ""])
    return "\n".join(lines)


# V3 deliberately has a separate validator/emitter so v1/v2 keep their frozen shape.
_V3_BASE = {"si32", "b", "s"}


def _result_parts(value):
    if not isinstance(value, str) or not value.startswith("result<") or not value.endswith(">"):
        return None
    depth = 0
    for index, char in enumerate(value[7:-1], 7):
        depth += char == "<"; depth -= char == ">"
        if char == "," and not depth:
            return value[7:index], value[index + 1:-1]
    return None


def _result_type_parts(value):
    if isinstance(value, str) and value.startswith(("result:path:", "result:paths:")):
        return None
    nested = _result_parts(value)
    if nested: return nested
    parts = value.split(":") if isinstance(value, str) else []
    return tuple(parts[1:]) if len(parts) == 3 and parts[0] == "result" else None


def _option_part(value):
    return value[7:-1] if isinstance(value, str) and value.startswith("option<") and value.endswith(">") else None


def _item_type(value):
    if isinstance(value, str) and value.startswith("list:"): return value[5:]
    if isinstance(value, str) and value.startswith("arr:"): return value[4:].rsplit(":", 1)[0]
    return None


def _map_parts(value):
    if not isinstance(value, str) or not value.startswith("map:"):
        return None
    parts = value[4:].split(":", 1)
    return tuple(parts) if len(parts) == 2 else None


def _v6_value_type(value, structs=None):
    parts = value.split(":")
    atom = lambda typ: typ in _SCALARS or structs is not None and typ.startswith("struct:") and typ[7:] in structs
    if isinstance(value, str) and value.startswith("list:"): return atom(value[5:]) or _v6_value_type(value[5:], structs)
    map_parts = _map_parts(value)
    if map_parts:
        key, item = map_parts
        return key in {"s", "si8", "si16", "si32", "si64", "ui8", "ui16", "ui32", "ui64"} and (atom(item) or _v6_value_type(item, structs))
    if isinstance(value, str) and value.startswith("arr:"):
        item, count = value[4:].rsplit(":", 1)
        return count.isdigit() and str(int(count)) == count and 0 < int(count) <= 16384 and (atom(item) or _v6_value_type(item, structs))
    if len(parts) == 3 and parts[0] == "result" and all(part in {"si32", "f32", "s", "b"} for part in parts[1:]): return True
    nested = _result_parts(value)
    if nested:
        return all(_v6_value_type(part, structs) or part in {"si32", "f32", "s", "b", "horn_plan", "horn_snapshot"} or structs is not None and part.startswith("struct:") and part[7:] in structs for part in nested)
    option = _option_part(value)
    if option is not None:
        return _v6_value_type(option, structs) or option in _SCALARS | {"horn_plan", "horn_snapshot"} or structs is not None and (option.startswith("struct:") and option[7:] in structs or option.startswith("enum:") and option[5:] in structs.get("$enums", {}))
    return False
_RESERVED = {"print", "Evidence"}


def _string(value, where):
    if not isinstance(value, str) or "\0" in value or any(0xD800 <= ord(c) <= 0xDFFF for c in value):
        _fail(where, "invalid string literal")
    return value


def _v3_type(value, where, structs, void=False):
    if value is None and void:
        return None
    if not isinstance(value, str):
        _fail(where, "invalid type")
    if structs.get("$version") in {6, 7} and value.startswith("ptr:") and value[4:] in _SCALARS - {"s"}:
        return value
    if value in _V3_BASE or structs.get("$version") in {6, 7} and value in _SCALARS or value.startswith("struct:") and value[7:] in structs and not value[7:].startswith("$") or value.startswith("enum:") and value[5:] in structs.get("$enums", {}):
        return value
    if structs.get("$version") in {6, 7} and _v6_value_type(value, structs): return value
    if value.startswith("node:") and value[5:] in structs["$graphs"]:
        return value
    if value.startswith("relation:") and value[9:] in structs["$relations"]:
        return value
    if value == "evidence" or value == "search_error":
        return value
    if value.startswith("path:") and value[5:] in structs["$graphs"]:
        return value
    if value.startswith("result:path:") and value[12:] in structs["$graphs"]:
        return value
    if structs.get("$version") in {4, 5, 6, 7} and value.startswith("paths:") and value[6:] in structs["$graphs"]:
        return value
    if structs.get("$version") in {4, 5, 6, 7} and value.startswith("result:paths:") and value[13:] in structs["$graphs"]:
        return value
    if structs.get("$version") in {4, 5, 6, 7} and value == "horn_result":
        return value
    if structs.get("$version") in {5, 6, 7} and value in {"horn_plan", "horn_snapshot"} or structs.get("$version") == 7 and value in {"horn_triple", "horn_rule", "candidate", "candidates", "constraint", "constraints", "interpretation"}:
        return value
    _fail(where, "invalid type")


def _v3_expr(node, functions, values, info, where):
    if not isinstance(node, dict) or not isinstance(node.get("kind"), str):
        _fail(where, "unexpected schema")
    kind = node["kind"]
    fields = {
        "literal": ("value",), "name": ("name",), "unary": ("op", "value"),
        "binary": ("op", "left", "right"), "call": ("name", "args"),
        "construct": ("fields",), "field": ("value", "name"), "relation": ("member",), "enum": ("member",),
        "evidence": ("source", "start", "end", "text"),
        "graph_add_node": ("graph", "value"),
        "graph_add_edge": ("graph", "source", "target", "relation", "evidence") if info.get("$version") == 3 else ("graph", "source", "target", "relation", "payload", "evidence"),
        "graph_remove": ("graph", "value"),
        "graph_find": ("graph", "source", "target", "relations", "max_depth", "max_expansions", "method") if info.get("$version") == 3 else ("graph", "source", "target", "relations", "max_depth", "max_expansions", "method", "cost", "heuristic"),
        "len": ("value",), "print": ("value",),
    }
    if info.get("$version") in {4, 5, 6, 7}:
        fields["graph_find_all"] = ("graph", "source", "target", "relations", "max_depth", "max_expansions", "method", "cost", "heuristic", "max_paths")
        fields["index"] = ("value", "index")
        fields["horn_query"] = ("operation", "plan", "limit", "proof_limit", "search_limit", "target")
    if info.get("$version") in {6, 7}:
        fields.update({"array": ("items",), "kernel": ("op", "args"), "list_push": ("list", "value"), "result": ("ok", "value"), "option": ("some", "value"), "horn_load": ("plan", "path"), "map": (), "map_set": ("map", "key", "value"), "map_remove": ("map", "key"), "map_get": ("map", "key"), "cast": ("value",), "io_call": ("operation", "args"), "ffi_call": ("name", "symbol", "args", "unsafe"), "ffi_addr": ("name", "unsafe"), "ffi_load": ("pointer", "unsafe"), "ffi_store": ("pointer", "value", "unsafe")})
    if info.get("$version") in {5, 6, 7}:
        fields.update({"horn_plan": ("plan",), "horn_add": ("plan", "fact"),
                       "horn_remove": ("plan", "id"),
                       "horn_evaluate": ("plan", "operation", "limit", "proof_limit", "search_limit", "target"),
                       "horn_version": ("plan",)})
    if info.get("$version") == 7:
        fields.update({"horn_correct": ("plan", "fact"), "horn_exists": ("plan", "triple"), "horn_count": ("plan", "triple"), "horn_select": ("plan", "triple"), "horn_explain": ("plan", "triple"), "horn_changes": ("plan",), "horn_save": ("plan", "path"), "horn_restore": ("plan", "path"), "horn_commit": ("plan", "path"), "horn_load": ("plan", "path"), "horn_call": (), "horn_triple": (), "horn_rule_construct": (), "horn_rule_history": (), "indexed_call": (), "candidate_construct": ("id", "meaning"), "candidates_construct": ("items",), "constraint_construct": ("required", "forbidden", "consistent"), "constraints_construct": ("items",), "interpret": ("candidates", "constraints", "budget"), "horn_history": ()})
    if kind not in fields:
        _fail(where, "unknown expression kind")
    if kind in {"candidate_construct", "constraint_construct", "interpret"}:
        base = ("kind", "type") + fields[kind]
        if set(node) not in (set(base), set(base) | {"eval_order"}): _fail(where, "unexpected schema")
    elif kind not in {"horn_call", "horn_history", "horn_rule_history", "horn_triple", "horn_rule_construct", "indexed_call"}: _object(node, where, ("kind", "type") + fields[kind])
    typ = _v3_type(node["type"], where + ".type", info, void=True)
    if kind == "io_call":
        from .language_io import validate_io
        return validate_io(node, lambda child: _v3_expr(child, functions, values, info, where + ".io"), lambda message: _fail(where, message))
    if kind.startswith("ffi_"):
        from .language_ffi import validate_ffi
        return validate_ffi(node, lambda child: _v3_expr(child, functions, values, info, where + ".ffi"), lambda message: _fail(where, message), info.get("$externs", {}), unsafe=info.get("$unsafe", False), locals=values)
    if kind == "literal":
        integer_bounds = {"si8": (-2**7, 2**7-1), "si16": (-2**15, 2**15-1), "si32": (_I32_MIN, _I32_MAX), "si64": (-2**63, 2**63-1), "ui8": (0, 2**8-1), "ui16": (0, 2**16-1), "ui32": (0, 2**32-1), "ui64": (0, 2**64-1)}
        if typ in integer_bounds and type(node["value"]) is int and integer_bounds[typ][0] <= node["value"] <= integer_bounds[typ][1]: return typ
        if typ == "b" and type(node["value"]) is bool: return typ
        if typ in {"f32", "f64"} and type(node["value"]) is float and __import__("math").isfinite(node["value"]) and (typ == "f64" or abs(node["value"]) <= 3.402823466e38): return typ
        if typ == "s": _string(node["value"], where + ".value"); return typ
        _fail(where, "invalid literal")
    if kind == "name":
        name = _name(node["name"], where + ".name")
        if name not in values or values[name][0] != typ: _fail(where, "unknown name or incorrect type")
        return typ
    if kind == "enum":
        if not isinstance(typ, str) or not typ.startswith("enum:") or node["member"] not in info["$enums"].get(typ[5:], ()): _fail(where, "invalid enum value")
        return typ
    if kind == "horn_call":
        op = node.get("operation")
        if not isinstance(op, str): _fail(where, "invalid Horn call")
        if "plan" in node:
            base = {"kind", "type", "operation", "plan", "filters", "limits"}
            if set(node) not in (base, base | {"eval_order"}) or _v3_expr(node["plan"], functions, values, info, where + ".plan") != "horn_plan" or not isinstance(node["filters"], dict) or not isinstance(node["limits"], dict): _fail(where, "invalid Horn call")
            if set(node["filters"]) - {"subject", "predicate", "object"} or set(node["limits"]) - {"limit", "proof_limit", "search_limit"}: _fail(where, "invalid Horn call")
            for key, value in node["filters"].items():
                if _v3_expr(value, functions, values, info, where + ".filters." + key) != "s": _fail(where, "invalid Horn filter")
            for key, value in node["limits"].items():
                if _v3_expr(value, functions, values, info, where + ".limits." + key) != "si32": _fail(where, "invalid Horn limit")
            expected = {"select": "horn_snapshot", "count": "si32", "exists": "b", "status": "enum:EpistemicState"}.get(op)
            supplied = {"plan", *node["filters"], *node["limits"]}
            if "eval_order" in node and (not isinstance(node["eval_order"], list) or len(node["eval_order"]) != len(set(node["eval_order"])) or set(node["eval_order"]) != supplied): _fail(where, "invalid Horn evaluation order")
            if typ != expected or op == "count" and set(node["limits"]) - {"search_limit"}: _fail(where, "invalid Horn call")
            return typ
        if set(node) != {"kind", "type", "operation", "snapshot", "indexes"} or _v3_expr(node["snapshot"], functions, values, info, where + ".snapshot") != "horn_snapshot" or not isinstance(node["indexes"], list): _fail(where, "invalid Horn accessor")
        signatures = {"fact_id": ("s", 1), "subject": ("s", 1), "predicate": ("s", 1), "object": ("s", 1), "fact_polarity": ("b", 1), "proof_count": ("si32", 1), "proof_id": ("s", 2), "proof_kind": ("s", 2), "proof_rule": ("s", 2), "proof_rule_version": ("s", 2), "proof_complete": ("b", 2), "proof_premise_count": ("si32", 2), "proof_binding_count": ("si32", 2), "proof_premise_id": ("s", 3), "proof_binding_name": ("s", 3), "proof_binding_value": ("s", 3)}
        wanted = signatures.get(op)
        if wanted is None or typ != wanted[0] or len(node["indexes"]) != wanted[1] or any(_v3_expr(value, functions, values, info, where + ".indexes") != "si32" for value in node["indexes"]): _fail(where, "invalid Horn accessor")
        return typ
    if kind == "horn_triple":
        if set(node) not in ({"kind", "type", "terms"}, {"kind", "type", "terms", "eval_order"}) or typ != "horn_triple" or not isinstance(node["terms"], list) or len(node["terms"]) != 3 or any(_v3_expr(term, functions, values, info, where + ".terms") != "s" for term in node["terms"]) or "eval_order" in node and (not isinstance(node["eval_order"], list) or any(type(i) is not int for i in node["eval_order"]) or sorted(node["eval_order"]) != [0, 1, 2]): _fail(where, "invalid Horn triple")
        return typ
    if kind == "horn_rule_construct":
        required = {"kind", "type", "id", "version", "body", "head", "eval_order"}
        if set(node) != required or typ != "horn_rule" or _v3_expr(node["id"], functions, values, info, where + ".id") != "s" or node["version"] is not None and _v3_expr(node["version"], functions, values, info, where + ".version") not in {"s", "si32"} or _v3_expr(node["head"], functions, values, info, where + ".head") != "horn_triple" or not isinstance(node["body"], list) or not 1 <= len(node["body"]) <= 8 or any(_v3_expr(item, functions, values, info, where + ".body") != "horn_triple" for item in node["body"]): _fail(where, "invalid Horn rule")
        expected = {"id", "head", *("body:" + str(i) for i in range(len(node["body"]))) } | ({"version"} if node["version"] is not None else set())
        if not isinstance(node["eval_order"], list) or len(node["eval_order"]) != len(expected) or any(not isinstance(token, str) for token in node["eval_order"]) or set(node["eval_order"]) != expected: _fail(where, "invalid Horn rule evaluation order")
        return typ
    if kind == "candidate_construct":
        if typ != "candidate" or _v3_expr(node["id"], functions, values, info, where + ".id") != "s" or _v3_expr(node["meaning"], functions, values, info, where + ".meaning") != "horn_snapshot": _fail(where, "invalid Candidate")
        if "eval_order" in node and (not isinstance(node["eval_order"], list) or set(node["eval_order"]) != {"id", "meaning"} or len(node["eval_order"]) != 2): _fail(where, "invalid Candidate evaluation order")
        return typ
    if kind in {"candidates_construct", "constraints_construct"}:
        wanted = "candidates" if kind == "candidates_construct" else "constraints"; item = "candidate" if kind == "candidates_construct" else "constraint"
        if typ != wanted or not isinstance(node["items"], list) or any(_v3_expr(value, functions, values, info, where + ".items") != item for value in node["items"]): _fail(where, "invalid collection")
        return typ
    if kind == "constraint_construct":
        if typ != "constraint" or _v3_expr(node["consistent"], functions, values, info, where + ".consistent") != "b" or any(node[key] is not None and _v3_expr(node[key], functions, values, info, where + "." + key) != "horn_triple" for key in ("required", "forbidden")): _fail(where, "invalid Constraint")
        if "eval_order" in node and (not isinstance(node["eval_order"], list) or len(node["eval_order"]) != len(set(node["eval_order"])) or set(node["eval_order"]) - {"required", "forbidden", "consistent"}): _fail(where, "invalid Constraint evaluation order")
        return typ
    if kind == "interpret":
        if typ != "interpretation" or _v3_expr(node["candidates"], functions, values, info, where + ".candidates") != "candidates" or _v3_expr(node["constraints"], functions, values, info, where + ".constraints") != "constraints" or _v3_expr(node["budget"], functions, values, info, where + ".budget") != "si32": _fail(where, "invalid interpret")
        if "eval_order" in node and (not isinstance(node["eval_order"], list) or len(node["eval_order"]) != len(set(node["eval_order"])) or set(node["eval_order"]) - {"candidates", "constraints", "budget"}): _fail(where, "invalid interpret evaluation order")
        return typ
    if kind == "horn_rule_history":
        if isinstance(node.get("operation"), str) and node["operation"] in {"add_rule", "replace_rule", "remove_rule"}:
            if set(node) != {"kind", "type", "operation", "plan", "id", "rule", "eval_order"} or typ != "b" or _v3_expr(node["plan"], functions, values, info, where + ".plan") != "horn_plan": _fail(where, "invalid Horn rule history")
            if node["plan"].get("kind") != "name" or not values.get(node["plan"].get("name"), (None, False))[1]: _fail(where, "Horn rule mutation needs mutable plan")
            operation = node["operation"]
            if operation == "add_rule" and (node["id"] is not None or _v3_expr(node["rule"], functions, values, info, where + ".rule") != "horn_rule"): _fail(where, "invalid Horn rule history")
            if operation == "replace_rule" and (_v3_expr(node["id"], functions, values, info, where + ".id") != "s" or _v3_expr(node["rule"], functions, values, info, where + ".rule") != "horn_rule"): _fail(where, "invalid Horn rule history")
            if operation == "remove_rule" and (_v3_expr(node["id"], functions, values, info, where + ".id") != "s" or node["rule"] is not None): _fail(where, "invalid Horn rule history")
            expected = {"plan"} | ({"id"} if node["id"] is not None else set()) | ({"rule"} if node["rule"] is not None else set())
            if not isinstance(node["eval_order"], list) or len(node["eval_order"]) != len(expected) or any(not isinstance(token, str) for token in node["eval_order"]) or set(node["eval_order"]) != expected: _fail(where, "invalid Horn rule evaluation order")
            return typ
        _fail(where, "invalid Horn rule history")
    if kind == "indexed_call":
        required = {"kind", "type", "operation", "plan", "path", "triple", "id", "fact", "eval_order"}
        op = node.get("operation")
        expected_type = "result:si32:s" if op == "save" else "result:b:s"
        if set(node) != required or not isinstance(op, str) or op not in {"save", "exists", "add", "correct", "remove"} or typ != expected_type or _v3_expr(node["path"], functions, values, info, where + ".path") != "s": _fail(where, "invalid indexed call")
        if op == "save" and (_v3_expr(node["plan"], functions, values, info, where + ".plan") != "horn_plan" or any(node[key] is not None for key in ("triple", "id", "fact"))): _fail(where, "invalid indexed save")
        if op == "exists" and (node["plan"] is not None or _v3_expr(node["triple"], functions, values, info, where + ".triple") != "horn_triple" or node["id"] is not None or node["fact"] is not None): _fail(where, "invalid indexed exists")
        if op == "remove" and (node["plan"] is not None or _v3_expr(node["id"], functions, values, info, where + ".id") != "s" or node["triple"] is not None or node["fact"] is not None): _fail(where, "invalid indexed remove")
        if op in {"add", "correct"}:
            fact = node["fact"]
            if node["plan"] is not None or node["triple"] is not None or node["id"] is not None or not isinstance(fact, dict) or set(fact) != {"id", "subject", "predicate", "object", "polarity"} or any(_v3_expr(fact[key], functions, values, info, where + ".fact." + key) != ("b" if key == "polarity" else "s") for key in fact): _fail(where, "invalid indexed fact")
        present = {"path"} | ({"plan"} if node["plan"] is not None else set()) | ({"triple"} if node["triple"] is not None else set()) | ({"id"} if node["id"] is not None else set()) | ({"fact:" + key for key in node["fact"]} if node["fact"] is not None else set())
        if not isinstance(node["eval_order"], list) or len(node["eval_order"]) != len(present) or any(not isinstance(token, str) for token in node["eval_order"]) or set(node["eval_order"]) != present: _fail(where, "invalid indexed evaluation order")
        return typ
    if kind == "horn_history":
        if set(node) not in ({"kind", "type", "operation", "plan", "id"}, {"kind", "type", "operation", "plan", "id", "fact"}) or node["operation"] not in {"withdraw", "replace", "supersede", "superseded_by", "history_fact"} or _v3_expr(node["plan"], functions, values, info, where + ".plan") != "horn_plan" or _v3_expr(node["id"], functions, values, info, where + ".id") != "s": _fail(where, "invalid Horn history")
        return typ
    if kind == "unary":
        if node["op"] == "not" and typ == "b" and _v3_expr(node["value"], functions, values, info, where + ".value") == "b": return typ
        if node["op"] != "-" or typ not in {"si8", "si16", "si32", "si64", "f32", "f64"} or _v3_expr(node["value"], functions, values, info, where + ".value") != typ: _fail(where, "invalid unary expression")
        return typ
    if kind == "cast":
        value = _v3_expr(node["value"], functions, values, info, where + ".value")
        if typ not in _SCALARS - {"b", "s"} or value not in _SCALARS - {"b", "s"}: _fail(where, "invalid cast")
        return typ
    if kind == "binary":
        op = node["op"]
        left = _v3_expr(node["left"], functions, values, info, where + ".left")
        right = _v3_expr(node["right"], functions, values, info, where + ".right")
        if not isinstance(op, str): _fail(where, "invalid binary operator")
        if op in {"and", "or"} and typ == left == right == "b": return typ
        if op == "+" and typ == left == right == "s": return typ
        if op in _ARITHMETIC and typ == left == right and left in _SCALARS - {"b", "s"} and not (op == "%" and left in {"f32", "f64"}): return typ
        if op in _COMPARE and left == right and left in _SCALARS - {"b", "s"} and typ == "b": return typ
        if op in {"==", "!="} and left == right and (left in {"b", "s"} or isinstance(left, str) and left.startswith("enum:")) and typ == "b": return typ
        _fail(where, "invalid binary expression")
    if kind == "call":
        name = _name(node["name"], where + ".name")
        if name not in functions or not isinstance(node["args"], list): _fail(where, "unknown function or invalid call")
        params, result = functions[name]
        if typ != result or len(params) != len(node["args"]): _fail(where, "invalid call")
        for i, (arg, expected) in enumerate(zip(node["args"], params)):
            if _v3_expr(arg, functions, values, info, f"{where}.args[{i}]") != expected: _fail(where, "call argument type mismatch")
        return typ
    if kind == "construct":
        if not isinstance(typ, str) or not typ.startswith("struct:") or typ[7:] not in info or not isinstance(node["fields"], list): _fail(where, "invalid struct constructor")
        expected = info[typ[7:]]
        if len(node["fields"]) != len(expected): _fail(where, "constructor field mismatch")
        expected_types, seen = dict(expected), set()
        for i, field in enumerate(node["fields"]):
            _object(field, f"{where}.fields[{i}]", ("name", "value"))
            field_name = _name(field["name"], f"{where}.fields[{i}].name")
            if field_name in seen or field_name not in expected_types or _v3_expr(field["value"], functions, values, info, f"{where}.fields[{i}].value") != expected_types[field_name]: _fail(where, "constructor field mismatch")
            seen.add(field_name)
        return typ
    if kind == "option":
        part = _option_part(typ)
        if part is None or type(node["some"]) is not bool or (node["some"] and _v3_expr(node["value"], functions, values, info, where + ".value") != part) or (not node["some"] and node["value"] is not None): _fail(where, "invalid optional")
        return typ
    if kind == "field":
        value = _v3_expr(node["value"], functions, values, info, where + ".value")
        name = _name(node["name"], where + ".name")
        if info.get("$version") in {4, 5, 6, 7} and isinstance(value, str) and value.startswith("path:"):
            if name == "cost" and typ == "si32": return typ
            _fail(where, "invalid path field")
        if info.get("$version") in {4, 5, 6, 7} and isinstance(value, str) and value.startswith("paths:"):
            if (name, typ) in {("complete", "b"), ("reason", "s")}: return typ
            _fail(where, "invalid paths field")
        if info.get("$version") in {4, 5, 6} and value == "horn_result":
            if (name, typ) in {("fact_count", "si32"), ("proof_count", "si32"), ("searches", "si32"), ("complete", "b"), ("reason", "s")}: return typ
            _fail(where, "invalid horn result field")
        if info.get("$version") in {5, 6, 7} and value == "horn_snapshot":
            if (name, typ) in {("fact_count", "si32"), ("proof_count", "si32"), ("searches", "si32"), ("complete", "b"), ("reason", "s"), ("version", "si32"), ("added_count", "si32"), ("removed_count", "si32")}:
                return typ
            _fail(where, "invalid horn snapshot field")
        if info.get("$version") == 7 and value == "interpretation":
            if (name, typ) in {("status", "enum:InterpretationStatus"), ("candidate_id", "option<s>"), ("reason", "s"), ("complete", "b")}: return typ
            _fail(where, "invalid interpretation field")
        if not isinstance(value, str) or not value.startswith("struct:"): _fail(where, "field access requires struct")
        fields_by_name = dict(info[value[7:]])
        if name not in fields_by_name or typ != fields_by_name[name]: _fail(where, "invalid struct field")
        return typ
    if kind == "relation":
        if not isinstance(typ, str) or not typ.startswith("relation:") or typ[9:] not in info["$relations"]: _fail(where, "invalid relation")
        member = _name(node["member"], where + ".member")
        if member not in info["$relations"][typ[9:]]: _fail(where, "unknown relation member")
        return typ
    if kind == "evidence":
        if typ != "evidence": _fail(where, "invalid evidence")
        source, text = _string(node["source"], where + ".source"), _string(node["text"], where + ".text")
        if type(node["start"]) is not int or type(node["end"]) is not int or not 0 <= node["start"] <= node["end"] <= len(source) or source[node["start"]:node["end"]] != text: _fail(where, "invalid evidence span")
        return typ
    if kind == "index":
        value = _v3_expr(node["value"], functions, values, info, where + ".value")
        if info.get("$version") in {6, 7} and isinstance(value, str) and value.startswith(("arr:", "list:")) and typ == _item_type(value) and _v3_expr(node["index"], functions, values, info, where + ".index") == "si32": return typ
        if not isinstance(value, str) or not value.startswith("paths:") or typ != "path:" + value[6:] or _v3_expr(node["index"], functions, values, info, where + ".index") != "si32": _fail(where, "invalid path index")
        return typ
    if kind == "horn_query":
        if typ != "horn_result": _fail(where, "invalid horn query")
        try:
            from .horn_bridge import validate_query
            validate_query(node)
        except ImportError: _fail(where, "horn bridge unavailable")
        except ValueError as error: _fail(where, str(error))
        return typ
    if kind == "horn_plan":
        if typ != "horn_plan": _fail(where, "invalid horn plan")
        try:
            from .horn_bridge import validate_plan_constructor, validate_plan_constructor_v6, validate_plan_constructor_v7
            (validate_plan_constructor_v7 if info.get("$version") == 7 else validate_plan_constructor_v6 if info.get("$version") == 6 else validate_plan_constructor)(node["plan"])
        except ImportError: _fail(where, "horn bridge unavailable")
        except ValueError as error: _fail(where, str(error))
        return typ
    if kind in {"horn_add", "horn_correct"}:
        if typ != "b" or _v3_expr(node["plan"], functions, values, info, where + ".plan") != "horn_plan" or not isinstance(node["fact"], list): _fail(where, "invalid horn add")
        if node["plan"].get("kind") != "name" or not values.get(node["plan"].get("name"), (None, False))[1]: _fail(where, "horn add requires mutable plan")
        expected = {"id": "s", "subject": "s", "predicate": "s", "object": "s", "polarity": "b", "modality": "s", "evidence": "evidence"}
        seen = set()
        for i, field in enumerate(node["fact"]):
            _object(field, f"{where}.fact[{i}]", ("name", "value")); name = _name(field["name"], f"{where}.fact[{i}].name")
            if name in seen or name not in expected or _v3_expr(field["value"], functions, values, info, f"{where}.fact[{i}].value") != expected[name]: _fail(where, "invalid horn add")
            seen.add(name)
        if not {"id", "subject", "predicate", "object"} <= seen: _fail(where, "invalid horn add")
        return typ
    if kind == "horn_remove":
        if typ != "b" or _v3_expr(node["plan"], functions, values, info, where + ".plan") != "horn_plan" or _v3_expr(node["id"], functions, values, info, where + ".id") != "s": _fail(where, "invalid horn remove")
        if node["plan"].get("kind") != "name" or not values.get(node["plan"].get("name"), (None, False))[1]: _fail(where, "horn remove requires mutable plan")
        return typ
    if kind == "horn_evaluate":
        if typ != "horn_snapshot" or _v3_expr(node["plan"], functions, values, info, where + ".plan") != "horn_plan" or not isinstance(node["operation"], str) or node["operation"] not in {"closure", "closure_with_provenance"} or any(type(node[key]) is not int or not 1 <= node[key] <= _I32_MAX for key in ("limit", "proof_limit", "search_limit")) or (node["operation"] == "closure_with_provenance" and node["target"] is not None): _fail(where, "invalid horn evaluate")
        target = node["target"]
        if target is not None and (not isinstance(target, list) or len(target) != 3): _fail(where, "invalid horn target")
        if target is not None:
            for i, part in enumerate(target):
                try: _string(part, f"{where}.target[{i}]")
                except ValueError: _fail(where, "invalid horn target")
                if not part: _fail(where, "invalid horn target")
        return typ
    if kind == "horn_version":
        if typ != "si32" or _v3_expr(node["plan"], functions, values, info, where + ".plan") != "horn_plan": _fail(where, "invalid horn version")
        return typ
    if kind == "horn_load":
        if typ != "result:si32:s" or _v3_expr(node["plan"], functions, values, info, where + ".plan") != "horn_plan" or _v3_expr(node["path"], functions, values, info, where + ".path") != "s" or node["plan"].get("kind") != "name" or not values.get(node["plan"].get("name"), (None, False))[1]: _fail(where, "invalid horn load")
        return typ
    if kind in {"horn_save", "horn_restore", "horn_commit"}:
        if typ != "result:si32:s" or _v3_expr(node["plan"], functions, values, info, where + ".plan") != "horn_plan" or _v3_expr(node["path"], functions, values, info, where + ".path") != "s" or kind in {"horn_restore", "horn_commit"} and (node["plan"].get("kind") != "name" or not values.get(node["plan"].get("name"), (None, False))[1]): _fail(where, "invalid horn persistence")
        return typ
    if kind in {"horn_exists", "horn_count", "horn_select", "horn_explain"}:
        wanted = {"horn_exists": "b", "horn_count": "si32", "horn_select": "horn_snapshot", "horn_explain": "horn_snapshot"}[kind]
        if typ != wanted or _v3_expr(node["plan"], functions, values, info, where + ".plan") != "horn_plan" or not isinstance(node["triple"], list) or len(node["triple"]) != 3 or any(not isinstance(x, str) or "\0" in x or any(0xD800 <= ord(char) <= 0xDFFF for char in x) if x is not None else kind not in {"horn_count", "horn_select"} for x in node["triple"]): _fail(where, "invalid horn query")
        return typ
    if kind == "horn_changes":
        if typ != "horn_snapshot" or _v3_expr(node["plan"], functions, values, info, where + ".plan") != "horn_plan": _fail(where, "invalid horn changes")
        return typ
    if kind in {"graph_add_node", "graph_remove", "graph_add_edge", "graph_find", "graph_find_all"}:
        graph = _name(node["graph"], where + ".graph")
        if graph not in info["$graphs"]: _fail(where, "unknown graph")
        graph_info = info["$graphs"][graph]
        node_type, relation_type = f"node:{graph}", f"relation:{graph_info[1]}"
        if kind == "graph_add_node":
            if typ != node_type or _v3_expr(node["value"], functions, values, info, where + ".value") != f"struct:{graph_info[0]}": _fail(where, "invalid graph node add")
        elif kind == "graph_remove":
            if typ is not None or _v3_expr(node["value"], functions, values, info, where + ".value") != node_type: _fail(where, "invalid graph remove")
        elif kind == "graph_add_edge":
            if not isinstance(node["relation"], dict) or node["relation"].get("kind") != "relation" or typ is not None or _v3_expr(node["source"], functions, values, info, where + ".source") != node_type or _v3_expr(node["target"], functions, values, info, where + ".target") != node_type or _v3_expr(node["relation"], functions, values, info, where + ".relation") != relation_type: _fail(where, "invalid graph edge")
            member = node["relation"]["member"]
            payload = node.get("payload")
            edge_type = graph_info[3] if len(graph_info) > 3 else None
            if info.get("$version") in {4, 5, 6} and ((edge_type is None and payload is not None) or (edge_type is not None and (payload is None or _v3_expr(payload, functions, values, info, where + ".payload") != "struct:" + edge_type))): _fail(where, "invalid graph edge payload")
            evidence = node["evidence"]
            evidence_kind = info["$relations"][graph_info[1]][member][1]
            if evidence is None and evidence_kind == "required": _fail(where, "required evidence missing")
            if evidence is not None and evidence_kind == "none": _fail(where, "evidence forbidden")
            if evidence is not None and _v3_expr(evidence, functions, values, info, where + ".evidence") != "evidence": _fail(where, "invalid evidence")
        else:
            result_type = f"result:path:{graph}" if kind == "graph_find" else f"result:paths:{graph}"
            if typ != result_type or _v3_expr(node["source"], functions, values, info, where + ".source") != node_type or _v3_expr(node["target"], functions, values, info, where + ".target") != node_type: _fail(where, "invalid graph find")
            if not isinstance(node["relations"], list): _fail(where, "invalid find relations")
            seen = set()
            for member in node["relations"]:
                member = _name(member, where + ".relations")
                if member in seen or member not in info["$relations"][graph_info[1]]: _fail(where, "invalid find relations")
                seen.add(member)
            if type(node["max_depth"]) is not int or not 0 <= node["max_depth"] <= _I32_MAX or type(node["max_expansions"]) is not int or not 0 <= node["max_expansions"] <= _I32_MAX: _fail(where, "invalid find bounds")
            if info.get("$version") == 3:
                if node["method"] != "bfs": _fail(where, "invalid find method")
            else:
                method, cost, heuristic = node["method"], node["cost"], node["heuristic"]
                if not isinstance(method, str) or method not in {"bfs", "dfs", "dijkstra", "astar"}: _fail(where, "invalid find method")
                weighted = method in {"dijkstra", "astar"}
                if weighted != (cost is not None): _fail(where, "weighted searches require exactly one cost")
                edge_type = graph_info[3]
                if cost is not None and (not isinstance(cost, str) or edge_type is None or cost not in dict(info[edge_type]) or dict(info[edge_type])[cost] != "si32"): _fail(where, "invalid edge cost")
                if (method == "astar") != (heuristic is not None): _fail(where, "astar requires exactly one heuristic")
                if heuristic is not None and (not isinstance(heuristic, str) or heuristic not in functions or functions[heuristic] != (["struct:" + graph_info[0], "struct:" + graph_info[0]], "si32")): _fail(where, "invalid heuristic")
                if kind == "graph_find_all" and (type(node["max_paths"]) is not int or not 0 <= node["max_paths"] <= 256): _fail(where, "invalid max paths")
        return typ
    if kind == "len":
        value = _v3_expr(node["value"], functions, values, info, where + ".value")
        if typ != "si32" or not (value == "s" or isinstance(value, str) and (value.startswith("path:") or value.startswith("paths:") or info.get("$version") in {6, 7} and value.startswith(("arr:", "list:", "map:")))): _fail(where, "invalid len")
        return typ
    if kind == "array":
        if not isinstance(typ, str) or not typ.startswith(("arr:", "list:")) or not isinstance(node["items"], list): _fail(where, "invalid array")
        item = _item_type(typ)
        if not node["items"] or any(_v3_expr(value, functions, values, info, where + ".items") != item for value in node["items"]): _fail(where, "invalid array")
        if typ.startswith("arr:") and len(node["items"]) != int(typ.rsplit(":", 1)[1]): _fail(where, "invalid array")
        return typ
    if kind == "kernel":
        if typ != "f32" or not isinstance(node["op"], str) or node["op"] not in {"sum", "norm", "dot", "cosine"} or not isinstance(node["args"], list) or len(node["args"]) != (1 if node["op"] in {"sum", "norm"} else 2) or any(_v3_expr(arg, functions, values, info, where + ".args") != "list:f32" for arg in node["args"]): _fail(where, "invalid kernel")
        return typ
    if kind == "list_push":
        value = _v3_expr(node["list"], functions, values, info, where + ".list")
        if typ is not None or not isinstance(value, str) or not value.startswith("list:") or _v3_expr(node["value"], functions, values, info, where + ".value") != value[5:]: _fail(where, "invalid list push")
        return typ
    if kind == "result":
        parts = _result_type_parts(typ)
        if not parts or type(node["ok"]) is not bool or _v3_expr(node["value"], functions, values, info, where + ".value") != parts[0 if node["ok"] else 1]: _fail(where, "invalid result")
        return typ
    if kind == "map":
        if _map_parts(typ) is None: _fail(where,"invalid map")
        return typ
    if kind in {"map_set","map_remove","map_get"}:
        value=_v3_expr(node["map"],functions,values,info,where+".map")
        parts = _map_parts(value)
        if parts is None or _v3_expr(node["key"],functions,values,info,where+".key") != parts[0]: _fail(where,"invalid map")
        if kind=="map_set" and (typ is not None or _v3_expr(node["value"],functions,values,info,where+".value")!=parts[1]): _fail(where,"invalid map")
        if kind=="map_remove" and typ!="b": _fail(where,"invalid map")
        wanted = "result:" + parts[1] + ":s" if parts[1] in {"si32", "f32", "s", "b"} else "result<" + parts[1] + ",s>"
        if kind=="map_get" and typ != wanted: _fail(where,"invalid map")
        return typ
    value = _v3_expr(node["value"], functions, values, info, where + ".value")
    if typ is not None or value not in _SCALARS | {"search_error", "horn_result", "horn_snapshot"}: _fail(where, "invalid print")
    return typ


def _v3_block(statements, functions, values, return_type, info, where):
    if not isinstance(statements, list): _fail(where, "body must be a list")
    local, returned = values.copy(), False
    schemas = {"let": ("kind", "name", "type", "mutable", "value"), "assign": ("kind", "name", "value"), "array_assign": ("kind", "name", "index", "value"), "field_assign": ("kind", "name", "field", "value"), "return": ("kind", "value"), "expr": ("kind", "value"), "if": ("kind", "condition", "then", "else"), "while": ("kind", "condition", "body"), "for": ("kind", "name", "start", "stop", "body"), "for_each": ("kind", "name", "source", "item_type", "body"), "unsafe": ("kind", "body"), "match": ("kind", "value", "ok_name", "ok", "err_name", "err"), "match_option": ("kind", "value", "some_name", "some", "none"), "match_enum": ("kind", "value", "arms"), "break": ("kind",), "continue": ("kind",)}
    for i, statement in enumerate(statements):
        sw = f"{where}[{i}]"
        if returned: _fail(sw, "statement after definite return")
        if not isinstance(statement, dict) or not isinstance(statement.get("kind"), str) or statement["kind"] not in schemas: _fail(sw, "unknown statement kind")
        kind = statement["kind"]; _object(statement, sw, schemas[kind])
        if kind == "let":
            name, typ = _name(statement["name"], sw + ".name"), _v3_type(statement["type"], sw + ".type", info)
            if name in local or type(statement["mutable"]) is not bool or _v3_expr(statement["value"], functions, local, info, sw + ".value") != typ: _fail(sw, "invalid let")
            local[name] = (typ, statement["mutable"])
        elif kind == "assign":
            name = _name(statement["name"], sw + ".name")
            if name not in local or not local[name][1] or _v3_expr(statement["value"], functions, local, info, sw + ".value") != local[name][0]: _fail(sw, "invalid assignment")
        elif kind == "array_assign":
            name = _name(statement["name"], sw + ".name")
            if name not in local or not local[name][1] or not local[name][0].startswith("arr:") or _v3_expr(statement["index"],functions,local,info,sw+".index") != "si32" or _v3_expr(statement["value"],functions,local,info,sw+".value") != _item_type(local[name][0]): _fail(sw,"invalid array assignment")
        elif kind == "field_assign":
            name, field = _name(statement["name"], sw + ".name"), _name(statement["field"], sw + ".field")
            if name not in local or not local[name][1] or not local[name][0].startswith("struct:") or field not in dict(info[local[name][0][7:]]) or _v3_expr(statement["value"], functions, local, info, sw + ".value") != dict(info[local[name][0][7:]])[field]: _fail(sw, "invalid field assignment")
        elif kind == "return":
            if (return_type is None and statement["value"] is not None) or (return_type is not None and (statement["value"] is None or _v3_expr(statement["value"], functions, local, info, sw + ".value") != return_type)): _fail(sw, "return type mismatch")
            returned = True
        elif kind == "expr": _v3_expr(statement["value"], functions, local, info, sw + ".value")
        elif kind in {"if", "while"}:
            if _v3_expr(statement["condition"], functions, local, info, sw + ".condition") != "b": _fail(sw, "condition must be b")
            if kind == "if":
                then_returned = _v3_block(statement["then"], functions, local, return_type, info, sw + ".then")
                else_returned = _v3_block(statement["else"], functions, local, return_type, info, sw + ".else")
                returned = then_returned and else_returned
            else: _v3_block(statement["body"], functions, local, return_type, info, sw + ".body")
        elif kind == "for":
            name = _name(statement["name"], sw + ".name")
            if name in local or _v3_expr(statement["start"], functions, local, info, sw + ".start") != "si32" or _v3_expr(statement["stop"], functions, local, info, sw + ".stop") != "si32": _fail(sw, "invalid for")
            nested = local.copy(); nested[name] = ("si32", False); _v3_block(statement["body"], functions, nested, return_type, info, sw + ".body")
        elif kind == "for_each":
            name, source = _name(statement["name"], sw + ".name"), _v3_expr(statement["source"], functions, local, info, sw + ".source")
            item = _map_parts(source)[0] if _map_parts(source) else _item_type(source)
            if name in local or item is None or statement["item_type"] != item: _fail(sw, "invalid for iteration")
            nested = local.copy(); nested[name] = (item, False); _v3_block(statement["body"], functions, nested, return_type, info, sw + ".body")
        elif kind == "unsafe":
            was_unsafe = info.get("$unsafe", False); info["$unsafe"] = True
            returned = _v3_block(statement["body"], functions, local, return_type, info, sw + ".body")
            info["$unsafe"] = was_unsafe
        elif kind in {"break", "continue"}:
            pass
        elif kind == "match_option":
            value = _v3_expr(statement["value"], functions, local, info, sw + ".value"); part = _option_part(value)
            name = _name(statement["some_name"], sw + ".some_name")
            if part is None or name in local: _fail(sw, "invalid optional match")
            some_scope = local.copy(); some_scope[name] = (part, False)
            returned = _v3_block(statement["some"], functions, some_scope, return_type, info, sw + ".some") and _v3_block(statement["none"], functions, local, return_type, info, sw + ".none")
        elif kind == "match_enum":
            value = _v3_expr(statement["value"], functions, local, info, sw + ".value")
            if not isinstance(value, str) or not value.startswith("enum:") or not isinstance(statement["arms"], list): _fail(sw, "invalid enum match")
            members, seen, branches = info["$enums"][value[5:]], set(), []
            for j, arm in enumerate(statement["arms"]):
                _object(arm, f"{sw}.arms[{j}]", ("member", "body")); member = _name(arm["member"], f"{sw}.arms[{j}].member")
                if member not in members or member in seen: _fail(sw, "invalid enum match arm")
                seen.add(member); branches.append(_v3_block(arm["body"], functions, local, return_type, info, f"{sw}.arms[{j}].body"))
            if seen != set(members): _fail(sw, "non-exhaustive enum match")
            returned = all(branches)
        else:
            value = _v3_expr(statement["value"], functions, local, info, sw + ".value")
            if not isinstance(value, str) or not (value.startswith("result:path:") or info.get("$version") in {4, 5, 6, 7} and value.startswith("result:paths:") or info.get("$version") in {6, 7} and _result_type_parts(value)):
                _fail(sw, "match requires graph result")
            ok_name, err_name = _name(statement["ok_name"], sw + ".ok_name"), _name(statement["err_name"], sw + ".err_name")
            if ok_name == err_name or ok_name in local or err_name in local: _fail(sw, "invalid match binder")
            ok_scope, err_scope = local.copy(), local.copy(); graph = value[13:] if value.startswith("result:paths:") else value[12:]
            result = _result_type_parts(value)
            if info.get("$version") in {6, 7} and result:
                ok_type, err_type = result; ok_scope[ok_name], err_scope[err_name] = (ok_type, False), (err_type, False)
            else:
                ok_type = f"paths:{graph}" if value.startswith("result:paths:") else f"path:{graph}"; ok_scope[ok_name], err_scope[err_name] = (ok_type, False), ("search_error", False)
            ok_returned = _v3_block(statement["ok"], functions, ok_scope, return_type, info, sw + ".ok")
            err_returned = _v3_block(statement["err"], functions, err_scope, return_type, info, sw + ".err")
            returned = ok_returned and err_returned
    return returned


def _validate_v3(ir, version=3):
    expected = {"version", "structs", "relations", "graphs", "functions"}
    if not isinstance(ir, dict) or set(ir) not in (expected, expected | {"enums"}, expected | {"externs"}, expected | {"enums", "externs"}): _fail("program", "unexpected schema")
    if type(ir["version"]) is not int or ir["version"] != version or any(not isinstance(ir[x], list) for x in ("structs", "relations", "graphs", "functions")) or len(ir["relations"]) > 65536 or len(ir["graphs"]) > 65535: _fail("program", "expected bounded graph declarations")
    info = {"$relations": {}, "$graphs": {}, "$enums": dict(_BUILTIN_ENUMS), "$version": version, "$externs": {}}
    if "externs" in ir:
        from .language_ffi import validate_extern
        if not isinstance(ir["externs"], list): _fail("program.externs", "invalid extern declarations")
        for index, declaration in enumerate(ir["externs"]):
            if not validate_extern(declaration, lambda message, index=index: _fail(f"externs[{index}]", message)) or declaration["name"] in info["$externs"]: _fail(f"externs[{index}]", "invalid extern declaration")
            info["$externs"][declaration["name"]] = declaration
    namespace = set()
    for i, enum in enumerate(ir.get("enums", [])):
        w = f"enums[{i}]"; _object(enum, w, ("name", "members")); name = _name(enum["name"], w + ".name")
        if name in namespace or name in _RESERVED or name in _BUILTIN_ENUMS or not isinstance(enum["members"], list) or not enum["members"]: _fail(w, "invalid enum")
        members = tuple(_name(member, w + ".member") for member in enum["members"])
        if len(set(members)) != len(members): _fail(w, "duplicate enum member")
        namespace.add(name); info["$enums"][name] = members
    for i, struct in enumerate(ir["structs"]):
        w = f"structs[{i}]"; _object(struct, w, ("name", "fields")); name = _name(struct["name"], w + ".name")
        if name in namespace or name in _RESERVED or not isinstance(struct["fields"], list): _fail(w, "invalid declaration")
        namespace.add(name); fields, seen = [], set()
        for j, field in enumerate(struct["fields"]):
            _object(field, f"{w}.fields[{j}]", ("name", "type")); field_name, field_type = _name(field["name"], f"{w}.fields[{j}].name"), field["type"]
            if field_name in seen: _fail(w, "invalid struct field")
            _v3_type(field_type, w + ".field", info)
            seen.add(field_name); fields.append((field_name, field_type))
        info[name] = fields
    if version in {6, 7}:
        for name, fields in ((name, fields) for name, fields in info.items() if not name.startswith("$")):
            for field_name, field_type in fields: _v3_type(field_type, f"struct {name}.{field_name}", info)
    for i, relation in enumerate(ir["relations"]):
        w = f"relations[{i}]"; _object(relation, w, ("name", "members")); name = _name(relation["name"], w + ".name")
        if name in namespace or name in _RESERVED or not isinstance(relation["members"], list) or len(relation["members"]) > 256: _fail(w, "invalid declaration")
        namespace.add(name); members = {}
        for j, member in enumerate(relation["members"]):
            _object(member, f"{w}.members[{j}]", ("name", "polarity", "evidence", "traverse")); m = _name(member["name"], f"{w}.members[{j}].name")
            if m in members or not all(isinstance(member[key], str) for key in ("polarity", "evidence", "traverse")) or member["polarity"] not in {"positive", "negative", "neutral"} or member["evidence"] not in {"none", "optional", "required"} or member["traverse"] not in {"forward", "reverse", "both", "block"}: _fail(w, "invalid relation metadata")
            members[m] = (j, member["evidence"], member["traverse"], member["polarity"])
        info["$relations"][name] = members
    info["$graphs"] = {}
    for i, graph in enumerate(ir["graphs"]):
        w = f"graphs[{i}]"; _object(graph, w, ("name", "node_type", "relation", "directed") if version == 3 else ("name", "node_type", "relation", "directed", "edge_type")); name = _name(graph["name"], w + ".name")
        node_type, relation_name = _name(graph["node_type"], w + ".node_type"), _name(graph["relation"], w + ".relation")
        edge_type = graph.get("edge_type")
        if name in namespace or name in _RESERVED or node_type not in info or node_type.startswith("$") or relation_name not in info["$relations"] or type(graph["directed"]) is not bool or (version in {4, 5, 6, 7} and edge_type is not None and (not isinstance(edge_type, str) or edge_type not in info or edge_type.startswith("$"))): _fail(w, "invalid graph")
        namespace.add(name); info["$graphs"][name] = (node_type, relation_name, graph["directed"], edge_type)
    functions = {}
    for i, function in enumerate(ir["functions"]):
        w = f"functions[{i}]"; _object(function, w, ("name", "params", "return_type", "body")); name = _name(function["name"], w + ".name")
        if name in namespace or name in _RESERVED or not isinstance(function["params"], list): _fail(w, "invalid function")
        namespace.add(name); params, names = [], set()
        for j, param in enumerate(function["params"]):
            _object(param, f"{w}.params[{j}]", ("name", "type")); p = _name(param["name"], f"{w}.params[{j}].name")
            if p in names: _fail(w, "duplicate parameter")
            param_type = _v3_type(param["type"], f"{w}.params[{j}].type", info)
            _v3_type(param_type, w + ".param", info)
            names.add(p); params.append(param_type)
        return_type = _v3_type(function["return_type"], w + ".return_type", info, void=True)
        _v3_type(return_type, w + ".return", info, void=True)
        functions[name] = (params, return_type)
    if "main" not in functions or functions["main"][0] or functions["main"][1] not in {None, "si32"}: _fail("program", "requires main() or main() -> si32")
    for i, function in enumerate(ir["functions"]):
        params, result = functions[function["name"]]; scope = {p["name"]: (typ, True) for p, typ in zip(function["params"], params)}
        info["$unsafe"] = False
        if result is not None and not _v3_block(function["body"], functions, scope, result, info, f"functions[{i}].body"): _fail(f"functions[{i}]", "non-void function must definitely return")
        if result is None: _v3_block(function["body"], functions, scope, result, info, f"functions[{i}].body")
    return functions, info


def _validate_v4_purity(ir):
    rows = {row["name"]: row for row in ir["functions"]}
    calls, impure = {}, {}
    def scan(value, names):
        if isinstance(value, dict):
            kind = value.get("kind")
            if kind == "call": names.add(value["name"])
            if kind in {"print", "graph_add_node", "graph_add_edge", "graph_remove", "graph_find", "graph_find_all", "horn_query", "horn_plan", "horn_add", "horn_correct", "horn_remove", "horn_evaluate", "horn_version", "horn_load", "horn_save", "horn_restore", "horn_commit", "horn_rule_history", "indexed_call", "list_push", "map_set", "map_remove"}: return True
            return any(scan(child, names) for child in value.values())
        if isinstance(value, list): return any(scan(child, names) for child in value)
        return False
    for name, row in rows.items():
        called = set(); impure[name] = scan(row["body"], called); calls[name] = called
    used = []
    def collect(value):
        if isinstance(value, dict):
            if value.get("kind") in {"graph_find", "graph_find_all"} and value.get("heuristic") is not None: used.append(value["heuristic"])
            for child in value.values(): collect(child)
        elif isinstance(value, list):
            for child in value: collect(child)
    collect(ir["functions"])
    def pure(name, seen):
        if name in seen: return True
        return not impure[name] and all(pure(child, seen | {name}) for child in calls[name])
    for name in used:
        if not pure(name, set()): _fail("program", "heuristic must be pure")


def _validate_v4(ir):
    functions, info = _validate_v3(ir, 4)
    _validate_v4_purity(ir)
    return functions, info


def _validate_v5(ir):
    functions, info = _validate_v3(ir, 5)
    _validate_v4_purity(ir)
    return functions, info


def _validate_v6(ir):
    functions, info = _validate_v3(ir, 6)
    def controls(rows, depth=0):
        for row in rows:
            if row["kind"] in {"break", "continue"} and not depth: _fail("program", "loop control outside loop")
            if row["kind"] in {"while", "for"}: controls(row["body"], depth + 1)
            elif row["kind"] == "unsafe": controls(row["body"], depth)
            elif row["kind"] == "if": controls(row["then"], depth); controls(row["else"], depth)
            elif row["kind"] == "match": controls(row["ok"], depth); controls(row["err"], depth)
            elif row["kind"] == "match_option": controls(row["some"], depth); controls(row["none"], depth)
            elif row["kind"] == "match_enum":
                for arm in row["arms"]: controls(arm["body"], depth)
    for function in ir["functions"]: controls(function["body"])
    _validate_v4_purity(ir)
    return functions, info


def _validate_v7(ir):
    functions, info = _validate_v3(ir, 7)
    # Rule constructor strings are borrowed until the mutation deep-copies them.
    # Keep that internal payload from escaping into arbitrary raw-IR values.
    def rule_payloads(value, allowed=False):
        if isinstance(value, dict):
            if value.get("return_type") == "horn_rule" or value.get("type") == "horn_rule" and (value.get("kind") != "horn_rule_construct" or not allowed):
                _fail("program", "Rule values are only supported inside rule mutations")
            for key, child in value.items():
                rule_payloads(child, value.get("kind") == "horn_rule_history" and key == "rule")
        elif isinstance(value, list):
            for child in value: rule_payloads(child)
    rule_payloads(ir)
    def controls(rows, depth=0):
        for row in rows:
            if row["kind"] in {"break", "continue"} and not depth: _fail("program", "loop control outside loop")
            if row["kind"] in {"while", "for"}: controls(row["body"], depth + 1)
            elif row["kind"] == "unsafe": controls(row["body"], depth)
            elif row["kind"] == "if": controls(row["then"], depth); controls(row["else"], depth)
            elif row["kind"] == "match": controls(row["ok"], depth); controls(row["err"], depth)
            elif row["kind"] == "match_option": controls(row["some"], depth); controls(row["none"], depth)
            elif row["kind"] == "match_enum":
                for arm in row["arms"]: controls(arm["body"], depth)
    for function in ir["functions"]: controls(function["body"])
    def has_static_query(value):
        if isinstance(value, dict): return value.get("kind") == "horn_query" or any(has_static_query(child) for child in value.values())
        return any(has_static_query(child) for child in value) if isinstance(value, list) else False
    if has_static_query(ir["functions"]): _fail("program", "static Horn closure is unavailable in IR7; use a Horn plan method")
    _validate_v4_purity(ir)
    return functions, info


def _c_string(value):
    return '"' + ''.join(f"\\{byte:03o}" for byte in value.encode("utf-8")) + '"'


def _emit_v3(ir, functions, info):
    def result_name(typ):
        return "MrlResult_" + "".join(char if char.isalnum() else "_" for char in typ).strip("_")
    def ctype(typ):
        if typ is None: return "void"
        if typ.startswith("ptr:"): return ctype(typ[4:]) + " *"
        if typ == "si8": return "int8_t"
        if typ == "si16": return "int16_t"
        if typ == "si32": return "int32_t"
        if typ == "si64": return "int64_t"
        if typ == "ui8": return "uint8_t"
        if typ == "ui16": return "uint16_t"
        if typ == "ui32": return "uint32_t"
        if typ == "ui64": return "uint64_t"
        if typ == "f32": return "float"
        if typ == "f64": return "double"
        if typ == "b": return "bool"
        if typ == "s": return "const char *"
        if typ.startswith("enum:"): return "int32_t"
        if typ.startswith("struct:"): return f"MrlStruct{struct_ids[typ[7:]]}"
        if typ.startswith("node:"): return "MrlNode"
        if typ.startswith("relation:"): return "MrlRelation"
        if typ == "evidence": return "MrlEvidence"
        if typ.startswith("path:"): return "MrlPath"
        if typ.startswith("paths:"): return "MrlPathSet *"
        if typ.startswith("result:path:"): return "MrlSearchResult"
        if typ.startswith("result:paths:"): return "MrlPathsResult"
        if typ == "search_error": return "MrlSearchError"
        if typ == "horn_result": return "const MrlHornResult *"
        if typ == "horn_plan": return "MrlHornPlan *" if ir["version"] in {6, 7} else "MrlHornPlan"
        if typ == "horn_snapshot": return "MrlHornSnapshot *" if ir["version"] in {6, 7} else "MrlHornSnapshot"
        if typ == "horn_triple": return "MrlHornTriple"
        if typ == "horn_rule": return "MrlHornPlanRule"
        if typ == "candidate": return "MrlCandidate *"
        if typ == "candidates": return "MrlCandidates *"
        if typ == "constraint": return "MrlConstraint *"
        if typ == "constraints": return "MrlConstraints *"
        if typ == "interpretation": return "MrlInterpretation *"
        if typ.startswith("arr:"): return "MrlArr_" + typ[4:].replace(":", "_")
        if typ.startswith("list:"): return "MrlList *"
        if typ.startswith("map:"): return "MrlMap *"
        if _result_parts(typ): return result_name(typ)
        if _option_part(typ) is not None: return "MrlOption_" + "".join(char if char.isalnum() else "_" for char in typ).strip("_")
        if typ.startswith("result:"): return "MrlResult_" + typ[7:].replace(":", "_")
        return "void"
    struct_ids = {row["name"]: i for i, row in enumerate(ir["structs"])}
    graph_ids = {row["name"]: i + 1 for i, row in enumerate(ir["graphs"])}
    relation_ids = {row["name"]: i for i, row in enumerate(ir["relations"])}
    fn_names = {row["name"]: f"mrl_fn_{i}" for i, row in enumerate(ir["functions"])}
    def uses_io(value):
        if isinstance(value, dict): return value.get("kind") == "io_call" or any(uses_io(child) for child in value.values())
        return any(uses_io(child) for child in value) if isinstance(value, list) else False
    has_io = uses_io(ir["functions"])
    lines = ["#include <stdbool.h>", "#include <stdint.h>", "#include <stdio.h>", "#include <stdlib.h>", "#include <string.h>", "#include <inttypes.h>", "#include <float.h>", "#include <math.h>", "", "static void mrl_runtime_fail(const char *message) { fputs(message, stderr); fputc('\\n', stderr); exit(1); }", "static void mrl_overflow(void) { mrl_runtime_fail(\"MRL integer overflow\"); }", "static double mrl_f64_result(double value) { if (!isfinite(value)) mrl_runtime_fail(\"MRL f64 overflow\"); return value; }", "static int32_t mrl_add(int32_t a, int32_t b) { int64_t r = (int64_t)a + b; if (r < INT32_MIN || r > INT32_MAX) mrl_overflow(); return (int32_t)r; }", "static int32_t mrl_sub(int32_t a, int32_t b) { int64_t r = (int64_t)a - b; if (r < INT32_MIN || r > INT32_MAX) mrl_overflow(); return (int32_t)r; }", "static int32_t mrl_mul(int32_t a, int32_t b) { int64_t r = (int64_t)a * b; if (r < INT32_MIN || r > INT32_MAX) mrl_overflow(); return (int32_t)r; }", "static int32_t mrl_div(int32_t a, int32_t b) { if (!b) mrl_runtime_fail(\"MRL division by zero\"); if (a == INT32_MIN && b == -1) mrl_overflow(); return a / b; }", "static int32_t mrl_mod(int32_t a, int32_t b) { if (!b) mrl_runtime_fail(\"MRL modulus by zero\"); if (a == INT32_MIN && b == -1) return 0; return a % b; }", "static int32_t mrl_neg(int32_t a) { int64_t r = -(int64_t)a; if (r < INT32_MIN || r > INT32_MAX) mrl_overflow(); return (int32_t)r; }"]
    from pathlib import Path
    runtime = (Path(__file__).with_name("runtime") / "graph_runtime.h").read_text(encoding="utf-8")
    lines.extend(["", runtime, ""])
    if ir["version"] in {6, 7}:
        lines.extend([(Path(__file__).with_name("runtime") / "value_runtime.h").read_text(encoding="utf-8"), ""])
        if has_io: lines.extend([(Path(__file__).with_name("runtime") / "language_io.h").read_text(encoding="utf-8"), ""])
        lines.extend(["typedef struct MrlHornPlan MrlHornPlan;", "typedef struct MrlHornSnapshot MrlHornSnapshot;", "typedef const char *MrlHornTriple[3];", ""])
        arr_types = sorted({typ for row in ir["functions"] for typ in [*(p["type"] for p in row["params"]), row["return_type"]] if isinstance(typ, str) and typ.startswith("arr:")})
        def collect_arr(value):
            if isinstance(value, dict):
                if isinstance(value.get("type"), str) and value["type"].startswith("arr:"): arr_types.append(value["type"])
                for child in value.values(): collect_arr(child)
            elif isinstance(value, list):
                for child in value: collect_arr(child)
        collect_arr(ir["functions"])
        for row in ir["structs"]:
            arr_types.extend(field["type"] for field in row["fields"] if field["type"].startswith("arr:"))
        result_types, option_types = [], []
        def collect_results(value):
            if isinstance(value, dict):
                if isinstance(value.get("type"), str) and (value["type"].startswith("result:") and not value["type"].startswith(("result:path:", "result:paths:")) or _result_parts(value.get("type"))): result_types.append(value["type"])
                if _option_part(value.get("type")) is not None: option_types.append(value["type"])
                for child in value.values(): collect_results(child)
            elif isinstance(value, list):
                for child in value: collect_results(child)
        collect_results(ir["functions"])
        for row in ir["structs"]:
            result_types.extend(field["type"] for field in row["fields"] if _result_type_parts(field["type"]))
            option_types.extend(field["type"] for field in row["fields"] if _option_part(field["type"]) is not None)
        def collect_composite(typ):
            result = _result_type_parts(typ)
            if result:
                result_types.append(typ)
                for part in result: collect_composite(part)
            option = _option_part(typ)
            if option is not None:
                option_types.append(typ); collect_composite(option)
        for typ in [*result_types, *option_types]: collect_composite(typ)
        def direct_composites(typ):
            nested = _result_type_parts(typ)
            if nested: return [part for part in nested if _result_type_parts(part) or part.startswith("struct:")]
            option = _option_part(typ)
            if option is not None: return [option] if _result_type_parts(option) or _option_part(option) is not None or option.startswith("struct:") else []
            if typ.startswith("result:") and not typ.startswith(("result:path:", "result:paths:")): return [typ]
            return [typ] if typ.startswith("struct:") else []
        pending = {"result:" + typ: typ for typ in set(result_types)}
        pending.update({"option:" + typ: typ for typ in set(option_types)})
        pending.update({"arr:" + typ: typ for typ in set(arr_types)})
        pending.update({"struct:" + row["name"]: row for row in ir["structs"]})
        emitted = set()
        while pending:
            ready = []
            for key, item in pending.items():
                types = ([_item_type(item)] if isinstance(item, str) and item.startswith("arr:") else _result_type_parts(item) or (_option_part(item),)) if isinstance(item, str) else [field["type"] for field in item["fields"]]
                deps = {("arr:" if dep.startswith("arr:") else "result:" if _result_type_parts(dep) else "option:" if _option_part(dep) is not None else "") + dep for dep in types if dep.startswith("arr:") or _result_type_parts(dep) or _option_part(dep) is not None or dep.startswith("struct:")}
                if deps <= emitted: ready.append(key)
            if not ready: raise ValueError("recursive managed record type")
            for key in sorted(ready):
                item = pending.pop(key); emitted.add(key)
                if isinstance(item, str):
                    result = _result_type_parts(item)
                    if item.startswith("arr:"):
                        part, count = _item_type(item), item.rsplit(":", 1)[1]
                        lines.append(f"typedef struct {{ {ctype(part)} items[{count}]; }} {ctype(item)};")
                    elif result:
                        ok, err = result; lines.append(f"typedef struct {{ bool ok, value_owned; union {{ {ctype(ok)} value; {ctype(err)} error; }}; }} {ctype(item)};")
                    else: lines.append(f"typedef struct {{ bool some, value_owned; {ctype(_option_part(item))} value; }} {ctype(item)};")
                else:
                    index = struct_ids[item["name"]]
                    members = " ".join(f"{ctype(field['type'])} f{n};" for n, field in enumerate(item["fields"])) or "uint8_t unused;"
                    lines.append(f"typedef struct {{ {members} }} MrlStruct{index};")
        lines.append("")
    else:
        for row in ir["structs"]:
            index = struct_ids[row["name"]]
            members = " ".join(f"{ctype(field['type'])} f{n};" for n, field in enumerate(row["fields"])) or "uint8_t unused;"
            lines.append(f"typedef struct {{ {members} }} MrlStruct{index};")
    if ir["version"] in {6, 7}:
        lines.extend(["static MrlHornPlan *mrl_horn_plan_copy(MrlHornPlan *);", "static void mrl_horn_plan_release(MrlHornPlan *);", "static MrlHornSnapshot *mrl_horn_snapshot_retain(MrlHornSnapshot *);", "static void mrl_horn_snapshot_release(MrlHornSnapshot *);"])
        def managed_type(typ):
            if not isinstance(typ, str): return False
            if typ == "s" or typ in {"horn_plan", "horn_snapshot", "candidate", "candidates", "constraint", "constraints", "interpretation"} or typ.startswith(("list:", "map:")): return True
            if typ.startswith("arr:"): return managed_type(_item_type(typ))
            result = _result_type_parts(typ)
            if result: return True
            if _option_part(typ) is not None: return True
            if typ.startswith("struct:"): return any(managed_type(field["type"]) for field in ir["structs"][struct_ids[typ[7:]]]["fields"])
            return False
        def helper_tag(typ): return "T_" + "".join(char if char.isalnum() else "_" for char in typ)
        helpers = set()
        def emit_helper(typ):
            if not managed_type(typ) or typ in helpers: return
            if typ == "s": helpers.add(typ); return
            result = _result_type_parts(typ)
            if result:
                ok, err = result; emit_helper(ok); emit_helper(err)
                tag = helper_tag(typ); helpers.add(typ)
                lines.append(f"static {ctype(typ)} mrl_copy_{tag}({ctype(typ)} value) {{ if (value.ok) value.value = {copy_expr(ok, 'value.value')}; else value.error = {copy_expr(err, 'value.error')}; value.value_owned = false; return value; }}")
                lines.append(f"static void mrl_release_{tag}({ctype(typ)} value) {{ if (value.ok) {{ {release_stmt(ok, 'value.value')} }} else {{ {release_stmt(err, 'value.error')} }} }}")
            elif _option_part(typ) is not None:
                part = _option_part(typ); emit_helper(part); tag = helper_tag(typ); helpers.add(typ)
                lines.append(f"static {ctype(typ)} mrl_copy_{tag}({ctype(typ)} value) {{ if (value.some) value.value = {copy_expr(part, 'value.value')}; value.value_owned = false; return value; }}")
                lines.append(f"static void mrl_release_{tag}({ctype(typ)} value) {{ if (value.some) {{ {release_stmt(part, 'value.value')} }} }}")
            elif typ.startswith("struct:"):
                row = ir["structs"][struct_ids[typ[7:]]]
                for field in row["fields"]: emit_helper(field["type"])
                tag = helper_tag(typ); helpers.add(typ)
                copies = " ".join(f"value.f{i} = {copy_expr(field['type'], f'value.f{i}')};" for i, field in enumerate(row["fields"]) if managed_type(field["type"]))
                releases = " ".join(release_stmt(field["type"], f"value.f{i}") for i, field in enumerate(row["fields"]) if managed_type(field["type"]))
                lines.append(f"static {ctype(typ)} mrl_copy_{tag}({ctype(typ)} value) {{ {copies} return value; }}")
                lines.append(f"static void mrl_release_{tag}({ctype(typ)} value) {{ {releases} }}")
            elif typ.startswith("arr:"):
                item, count = _item_type(typ), typ.rsplit(":", 1)[1]; emit_helper(item); tag = helper_tag(typ); helpers.add(typ)
                lines.append(f"static {ctype(typ)} mrl_copy_{tag}({ctype(typ)} value) {{ for (uint32_t i=0;i<{count};++i) value.items[i] = {copy_expr(item, 'value.items[i]')}; return value; }}")
                lines.append(f"static void mrl_release_{tag}({ctype(typ)} value) {{ for (uint32_t i=0;i<{count};++i) {{ {release_stmt(item, 'value.items[i]')} }} }}")
            elif typ.startswith(("list:", "map:")):
                item = typ[5:] if typ.startswith("list:") else _map_parts(typ)[1]; emit_helper(item); tag = helper_tag(typ); helpers.add(typ)
            else:
                helpers.add(typ)
            if typ != "s":
                tag = helper_tag(typ)
                lines.append(f"static void mrl_copy_into_{tag}(void *out, const void *in) {{ *({ctype(typ)} *)out = {copy_expr(typ, f'*(const {ctype(typ)} *)in')}; }}")
                lines.append(f"static void mrl_drop_{tag}(void *value) {{ {release_stmt(typ, f'*( {ctype(typ)} *)value')} }}")
        def copy_expr(typ, value):
            if typ == "s": return f"mrl_string_copy({value})"
            if typ == "horn_plan": return f"mrl_horn_plan_copy({value})"
            if typ == "horn_snapshot": return f"mrl_horn_snapshot_retain({value})"
            if typ == "candidate": return f"mrl_candidate_retain({value})"
            if typ == "candidates": return f"mrl_candidates_retain({value})"
            if typ == "constraint": return f"mrl_constraint_retain({value})"
            if typ == "constraints": return f"mrl_constraints_retain({value})"
            if typ == "interpretation": return f"mrl_interpretation_retain({value})"
            if typ.startswith("map:"): return f"mrl_map_retain({value})"
            if typ.startswith("list:"): return f"mrl_list_copy({value})"
            return f"mrl_copy_{helper_tag(typ)}({value})" if managed_type(typ) else value
        def release_stmt(typ, value):
            if typ == "s": return f"free((void *){value});"
            if typ == "horn_plan": return f"mrl_horn_plan_release({value});"
            if typ == "horn_snapshot": return f"mrl_horn_snapshot_release({value});"
            if typ == "candidate": return f"mrl_candidate_release({value});"
            if typ == "candidates": return f"mrl_candidates_release({value});"
            if typ == "constraint": return f"mrl_constraint_release({value});"
            if typ == "constraints": return f"mrl_constraints_release({value});"
            if typ == "interpretation": return f"mrl_interpretation_release({value});"
            if typ.startswith("map:"): return f"mrl_map_release({value});"
            if typ.startswith("list:"): return f"mrl_list_release({value});"
            return f"mrl_release_{helper_tag(typ)}({value});" if managed_type(typ) else ""
        def collect_type(typ):
            emit_helper(typ)
            if isinstance(typ, str) and typ.startswith("list:"): collect_type(typ[5:])
            elif isinstance(typ, str) and _map_parts(typ): collect_type(_map_parts(typ)[1])
            elif isinstance(typ, str) and typ.startswith("arr:"): collect_type(_item_type(typ))
        for row in ir["structs"]: emit_helper("struct:" + row["name"])
        for typ in arr_types: emit_helper(typ)
        for typ in result_types: emit_helper(typ)
        for typ in option_types: emit_helper(typ)
        for function in ir["functions"]:
            collect_type(function["return_type"])
            for param in function["params"]: collect_type(param["type"])
        lines.append("")
    for row in ir["graphs"]:
        i = graph_ids[row["name"]] - 1
        lines.append(f"static MrlGraph mrl_graph_{i};")
    lines.append("static void mrl_init_graphs(void) {")
    for row in ir["graphs"]:
        i = graph_ids[row["name"]] - 1; members = ir["relations"][relation_ids[row["relation"]]]["members"]
        data = ", ".join("{" + ", ".join(str(({"positive": 0, "negative": 1, "neutral": 2}[m["polarity"]], {"none": 0, "optional": 1, "required": 2}[m["evidence"]], {"forward": 0, "reverse": 1, "both": 2, "block": 3}[m["traverse"]])[x]) for x in range(3)) + "}" for m in members) or "{0, 0, 0}"
        lines.append(f"    static const MrlRelationMeta mrl_meta_{i}[] = {{{data}}};")
        lines.append(f"    mrl_graph_init(&mrl_graph_{i}, {i + 1}, {relation_ids[row['relation']]}, mrl_meta_{i}, {len(members)});")
        node_size = f"sizeof(MrlStruct{struct_ids[row['node_type']]})"
        edge_size = f"sizeof(MrlStruct{struct_ids[row['edge_type']]})" if row.get("edge_type") is not None else "0"
        lines.append(f"    mrl_graph_set_payload_sizes(&mrl_graph_{i}, {node_size}, {edge_size});")
    lines.extend(["}", ""])
    def signature(function):
        params = ", ".join(f"{ctype(param['type'])} mrl_p_{i}" for i, param in enumerate(function["params"]))
        return ctype(function["return_type"]), params or "void"
    for function in ir["functions"]:
        result, params = signature(function); lines.append(f"static {result} {fn_names[function['name']]}({params});")
    for declaration in info.get("$externs", {}).values():
        params = ", ".join(ctype(param["type"]) for param in declaration["params"]) or "void"
        lines.append(f"extern {ctype(declaration['return_type'])} {declaration['symbol']}({params});")
    lines.append("")
    horn_queries, horn_plans = [], []
    if ir["version"] in {4, 5}:
        def collect_v4(value):
            if isinstance(value, dict):
                if value.get("kind") == "horn_query": horn_queries.append(value)
                if value.get("kind") == "horn_plan": horn_plans.append(value["plan"])
                if value.get("kind") in {"graph_find", "graph_find_all"} and value.get("heuristic") is not None:
                    graph, heuristic = value["graph"], value["heuristic"]
                    index = graph_ids[graph] - 1; marker = (graph, heuristic)
                    if marker not in wrappers:
                        wrappers.add(marker)
                        node_struct = struct_ids[ir["graphs"][index]["node_type"]]
                        lines.append(f"static int32_t mrl_heuristic_{index}_{fn_names[heuristic]}(MrlNode a, MrlNode b) {{ return {fn_names[heuristic]}(*((MrlStruct{node_struct} *)mrl_graph_node_payload(&mrl_graph_{index}, a)), *((MrlStruct{node_struct} *)mrl_graph_node_payload(&mrl_graph_{index}, b))); }}")
                for child in value.values(): collect_v4(child)
            elif isinstance(value, list):
                for child in value: collect_v4(child)
        wrappers = set(); collect_v4(ir["functions"])
        if horn_queries or horn_plans:
            from .horn_bridge import emit_support
            lines.append(emit_support(horn_queries, horn_plans))
    elif ir["version"] in {6, 7}:
        wrappers = set(); indexed_calls = []
        def collect_v6(value):
            if isinstance(value, dict):
                if value.get("kind") == "indexed_call": indexed_calls.append(value)
                if value.get("kind") == "horn_plan": horn_plans.append(value["plan"])
                if value.get("kind") == "horn_query": horn_queries.append(value)
                if value.get("kind") in {"graph_find", "graph_find_all"} and value.get("heuristic") is not None:
                    graph, heuristic = value["graph"], value["heuristic"]; marker = (graph, heuristic)
                    if marker not in wrappers:
                        wrappers.add(marker); index = graph_ids[graph] - 1
                        node_struct = struct_ids[ir["graphs"][index]["node_type"]]
                        lines.append(f"static int32_t mrl_heuristic_{index}_{fn_names[heuristic]}(MrlNode a, MrlNode b) {{ return {fn_names[heuristic]}(*((MrlStruct{node_struct} *)mrl_graph_node_payload(&mrl_graph_{index}, a)), *((MrlStruct{node_struct} *)mrl_graph_node_payload(&mrl_graph_{index}, b))); }}")
                for child in value.values(): collect_v6(child)
            elif isinstance(value, list):
                for child in value: collect_v6(child)
        collect_v6(ir["functions"])
        from .horn_bridge import emit_v6_support, emit_v7_support
        lines.append((emit_v7_support if ir["version"] == 7 else emit_v6_support)(horn_plans, horn_queries))
        if ir["version"] == 7 and indexed_calls:
            indexed_runtime = (Path(__file__).with_name("runtime") / "knowledge_indexed.h").read_text(encoding="utf-8")
            lines.append("\n".join(line for line in indexed_runtime.splitlines() if not line.startswith('#include "')))
    for function in ir["functions"]:
        counter, values = [0], {param["name"]: f"mrl_p_{i}" for i, param in enumerate(function["params"])}
        value_types = {f"mrl_p_{i}": param["type"] for i, param in enumerate(function["params"])}
        owned = {}
        temps = []
        pathset_temps = []
        rule_version_allocs = {}
        loop_frames = []
        pathsets, next_pathset = {}, [0]
        def collect_pathsets(statements):
            for statement in statements:
                if statement["kind"] == "let" and (statement["type"].startswith("result:paths:") or statement["type"].startswith("paths:")):
                    pathsets["budget" + str(len(pathsets))] = len(pathsets)
                if statement["kind"] == "match" and statement["value"]["type"].startswith("result:paths:"):
                    pathsets["budget" + str(len(pathsets))] = len(pathsets)
                for branch in ("then", "else", "body", "ok", "err"):
                    if isinstance(statement.get(branch), list): collect_pathsets(statement[branch])
        collect_pathsets(function["body"])
        pathset_count = len(pathsets); pathsets = {}
        def take_pathset(name):
            slot = next_pathset[0]; next_pathset[0] += 1; pathsets[name] = slot
            return f"&mrl_pathsets[{slot}]"
        def fresh(prefix):
            name = f"mrl_{prefix}_{counter[0]}"; counter[0] += 1; return name
        def add(text, indent): lines.append("    " * indent + text)
        def path_managed(typ): return isinstance(typ, str) and typ.startswith(("path:", "result:path:"))
        def managed(typ): return path_managed(typ) or ir["version"] in {6, 7} and managed_type(typ)
        def copy_value(typ, value):
            if isinstance(typ, str) and typ.startswith("path:"): return f"mrl_path_copy({value})"
            if isinstance(typ, str) and typ.startswith("result:path:"): return f"mrl_search_result_copy({value})"
            return copy_expr(typ, value)
        def release_value(typ, value, indent):
            if isinstance(typ, str) and typ.startswith("path:"): add(f"mrl_path_release(&{value});", indent)
            elif isinstance(typ, str) and typ.startswith("result:path:"): add(f"mrl_search_result_release(&{value});", indent)
            else: add(release_stmt(typ, value), indent)
        def own_temp(typ, value):
            if managed(typ): temps.append((value, typ))
            return value
        def take_temp(value):
            for index in range(len(temps) - 1, -1, -1):
                if temps[index][0] == value: temps.pop(index); return True
            return False
        def take_pathset_temp(value):
            for index in range(len(pathset_temps) - 1, -1, -1):
                if pathset_temps[index][0] == value: return pathset_temps.pop(index)[1]
            return None
        def release_temps(indent, start=0):
            while len(temps) > start:
                value, typ = temps.pop(); release_value(typ, value, indent)
        def expr(node, indent, scope):
            kind, typ = node["kind"], node["type"]
            if kind == "io_call":
                from .language_io import emit_io
                return emit_io(node, lambda child, level: expr(child, level, scope), ctype, add, fresh, own_temp, indent)
            if kind.startswith("ffi_"):
                from .language_ffi import emit_ffi
                if kind == "ffi_addr": node = {**node, "name": scope[node["name"]]}
                return emit_ffi(node, lambda child, level: expr(child, level, scope), ctype, add, fresh, own_temp, indent)
            if kind == "literal":
                value = _c_string(node["value"]) if typ == "s" else ("true" if node["value"] is True else "false" if node["value"] is False else (repr(node["value"]) + "f" if typ == "f32" else "INT32_MIN" if node["value"] == _I32_MIN else str(node["value"])))
                name = fresh("t"); add(f"{ctype(typ)} {name} = {'mrl_string_copy(' + value + ')' if typ == 's' and managed(typ) else value};", indent); return own_temp(typ, name)
            if kind == "enum":
                name = fresh("t"); add(f"int32_t {name} = {info['$enums'][typ[5:]].index(node['member'])};", indent); return name
            if kind == "name": return scope[node["name"]]
            if kind == "unary":
                value = expr(node["value"], indent, scope); name = fresh("t")
                if node["op"] == "not": add(f"bool {name} = !{value};", indent); return name
                if typ == "f32": add(f"float {name} = mrl_f32_result(-(double){value});", indent)
                elif typ == "f64": add(f"double {name} = -{value};", indent)
                elif typ == "si32": add(f"int32_t {name} = mrl_neg({value});", indent)
                else:
                    minimum = {"si8":"INT8_MIN", "si16":"INT16_MIN", "si64":"INT64_MIN"}.get(typ)
                    if minimum: add(f"if ({value} == {minimum}) mrl_overflow();", indent)
                    add(f"{ctype(typ)} {name} = ({ctype(typ)})(-{value});", indent)
                return name
            if kind == "binary":
                left, name = expr(node["left"], indent, scope), fresh("t")
                if node["op"] in {"and", "or"}:
                    add(f"bool {name} = {left};", indent)
                    add(f"if ({'!' if node['op'] == 'or' else ''}{name}) {{", indent)
                    temp_start = len(temps)
                    right = expr(node["right"], indent + 1, scope)
                    add(f"{name} = {right};", indent + 1); release_temps(indent + 1, temp_start); add("}", indent)
                    return name
                right = expr(node["right"], indent, scope)
                if typ == "s" and node["op"] == "+":
                    add(f"const char *{name} = mrl_string_join({left}, {right});", indent); return own_temp(typ, name)
                if node["op"] in _ARITHMETIC:
                    if typ == "f32":
                        if node["op"] == "/": add(f"if ({right} == 0.0f) mrl_runtime_fail(\"MRL division by zero\");", indent)
                        add(f"float {name} = mrl_f32_result((double){left} {node['op']} {right});", indent); return name
                    if typ == "f64":
                        if node["op"] == "/": add(f"if ({right} == 0.0) mrl_runtime_fail(\"MRL division by zero\");", indent)
                        add(f"double {name} = mrl_f64_result({left} {node['op']} {right});", indent); return name
                    if typ == "si32":
                        helper = {"+": "mrl_add", "-": "mrl_sub", "*": "mrl_mul", "/": "mrl_div", "%": "mrl_mod"}[node["op"]]
                        add(f"int32_t {name} = {helper}({left}, {right});", indent)
                    else:
                        if node["op"] in {"/", "%"}: add(f"if ({right} == 0) mrl_runtime_fail(\"MRL division by zero\");", indent)
                        limits = {"si8":("INT8_MIN","INT8_MAX"),"si16":("INT16_MIN","INT16_MAX"),"si64":("INT64_MIN","INT64_MAX"),"ui8":("0","UINT8_MAX"),"ui16":("0","UINT16_MAX"),"ui32":("0","UINT32_MAX"),"ui64":("0","UINT64_MAX")}
                        lo, hi = limits[typ]
                        if typ.startswith("ui"):
                            if node["op"] == "+": add(f"if ({right} > {hi} - {left}) mrl_overflow();", indent)
                            elif node["op"] == "-": add(f"if ({left} < {right}) mrl_overflow();", indent)
                            elif node["op"] == "*": add(f"if ({left} && {right} > {hi} / {left}) mrl_overflow();", indent)
                        elif node["op"] == "+": add(f"if (({right} > 0 && {left} > {hi} - {right}) || ({right} < 0 && {left} < {lo} - {right})) mrl_overflow();", indent)
                        elif node["op"] == "-": add(f"if (({right} < 0 && {left} > {hi} + {right}) || ({right} > 0 && {left} < {lo} + {right})) mrl_overflow();", indent)
                        elif node["op"] == "*": add(f"if (({left} > 0 && (({right} > 0 && {left} > {hi} / {right}) || ({right} < 0 && {right} < {lo} / {left}))) || ({left} < 0 && (({right} > 0 && {left} < {lo} / {right}) || ({right} < 0 && {right} < {hi} / {left})))) mrl_overflow();", indent)
                        elif node["op"] == "/": add(f"if ({left} == {lo} && {right} == -1) mrl_overflow();", indent)
                        if typ.startswith("si") and node["op"] == "%":
                            add(f"{ctype(typ)} {name} = ({left} == {lo} && {right} == -1) ? 0 : ({ctype(typ)})({left} % {right});", indent)
                        else: add(f"{ctype(typ)} {name} = ({ctype(typ)})({left} {node['op']} {right});", indent)
                elif node["left"]["type"] == "s": add(f"bool {name} = (strcmp({left}, {right}) {'==' if node['op'] == '==' else '!='} 0);", indent)
                else: add(f"bool {name} = {left} {node['op']} {right};", indent)
                return name
            if kind == "cast":
                value, name, source = expr(node["value"], indent, scope), fresh("t"), node["value"]["type"]
                integer = {"si8": ("INT8_MIN", "INT8_MAX"), "si16": ("INT16_MIN", "INT16_MAX"), "si32": ("INT32_MIN", "INT32_MAX"), "si64": ("INT64_MIN", "INT64_MAX"), "ui8": ("0", "UINT8_MAX"), "ui16": ("0", "UINT16_MAX"), "ui32": ("0", "UINT32_MAX"), "ui64": ("0", "UINT64_MAX")}
                if typ in integer:
                    lo, hi = integer[typ]
                    if source.startswith("f"):
                        upper = {"si8":"128.0", "si16":"32768.0", "si32":"2147483648.0", "si64":"9223372036854775808.0", "ui8":"256.0", "ui16":"65536.0", "ui32":"4294967296.0", "ui64":"18446744073709551616.0"}[typ]
                        add(f"if (!isfinite({value}) || {value} < ({ctype(source)})({lo}) || {value} >= ({ctype(source)}){upper} || trunc({value}) != {value}) mrl_runtime_fail(\"MRL checked cast\");", indent)
                    elif source.startswith("ui") and typ.startswith("si"):
                        add(f"if ((uint64_t){value} > (uint64_t){hi}) mrl_runtime_fail(\"MRL checked cast\");", indent)
                    elif source.startswith("si") and typ.startswith("ui"):
                        add(f"if ({value} < 0 || (uint64_t){value} > (uint64_t){hi}) mrl_runtime_fail(\"MRL checked cast\");", indent)
                    elif source.startswith("si"):
                        add(f"if ((int64_t){value} < (int64_t){lo} || (int64_t){value} > (int64_t){hi}) mrl_runtime_fail(\"MRL checked cast\");", indent)
                    elif source.startswith("ui"):
                        add(f"if ((uint64_t){value} > (uint64_t){hi}) mrl_runtime_fail(\"MRL checked cast\");", indent)
                    else:
                        add(f"if ({value} < ({ctype(source)})({lo}) || {value} > ({ctype(source)})({hi})) mrl_runtime_fail(\"MRL checked cast\");", indent)
                elif typ == "f32": add(f"if (!isfinite((double){value}) || (double){value} > FLT_MAX || (double){value} < -FLT_MAX) mrl_runtime_fail(\"MRL checked cast\");", indent)
                add(f"{ctype(typ)} {name} = ({ctype(typ)}){value};", indent); return name
            if kind == "call":
                temp_start = len(temps)
                args = [expr(arg, indent, scope) for arg in node["args"]]; call = f"{fn_names[node['name']]}({', '.join(args)})"
                if typ is None: add(call + ";", indent); release_temps(indent, temp_start); return None
                name = fresh("t"); add(f"{ctype(typ)} {name} = {call};", indent); release_temps(indent, temp_start); return own_temp(typ, name)
            if kind == "construct":
                values = [expr(field["value"], indent, scope) for field in node["fields"]]; name = fresh("t")
                field_names = [field[0] for field in info[typ[7:]]]
                initializers = []
                for field, value in zip(node["fields"], values):
                    field_type = field["value"]["type"]
                    if managed(field_type) and not take_temp(value): value = copy_value(field_type, value)
                    initializers.append(f".f{field_names.index(field['name'])} = {value}")
                add(f"{ctype(typ)} {name} = {{{', '.join(initializers) or '0'}}};", indent); return own_temp(typ, name)
            if kind == "horn_triple":
                terms = [None, None, None]
                for item in node.get("eval_order", [0, 1, 2]): terms[item] = expr(node["terms"][item], indent, scope)
                name = fresh("t")
                add(f"MrlHornTriple {name} = {{{', '.join(terms)}}};", indent); return name
            if kind == "horn_rule_construct":
                values, body = {}, [None] * len(node["body"])
                for token in node["eval_order"]:
                    if token.startswith("body:"): body[int(token[5:])] = expr(node["body"][int(token[5:])], indent, scope)
                    else: values[token] = expr(node[token], indent, scope)
                version = "\"null\"" if node["version"] is None else values["version"]; allocated_version = None
                if node["version"] is not None and node["version"]["type"] == "s":
                    allocated_version = fresh("rule_version_json")
                    add(f"char *{allocated_version} = mrl_horn_rule_version_json_string({version}); if (!{allocated_version}) mrl_runtime_fail(\"MRL rule version allocation\");", indent)
                    version = allocated_version
                elif node["version"] is not None:
                    buffer = fresh("rule_version"); add(f"char {buffer}[32]; snprintf({buffer}, sizeof({buffer}), \"%\" PRId32, {version});", indent); version = buffer
                body_rows = ", ".join("{" + ", ".join(f"{value}[{i}]" for i in range(3)) + "}" for value in body)
                head = values["head"]; name = fresh("t")
                add(f"MrlHornPlanRule {name} = {{{values['id']}, {version}, {len(body)}, {{{body_rows}}}, {{{head}[0], {head}[1], {head}[2]}}}};", indent)
                if allocated_version: rule_version_allocs[name] = allocated_version
                return name
            if kind == "candidate_construct":
                values = {key: expr(node[key], indent, scope) for key in node.get("eval_order", ["id", "meaning"])}
                ident, meaning, name = values["id"], values["meaning"], fresh("t")
                add(f"MrlCandidate *{name} = mrl_candidate_new({ident}, {meaning});", indent); return own_temp(typ, name)
            if kind in {"candidates_construct", "constraints_construct"}:
                item_type, fun = ("MrlCandidate *", "mrl_candidates_new") if kind == "candidates_construct" else ("MrlConstraint *", "mrl_constraints_new")
                items, name = [expr(item, indent, scope) for item in node["items"]], fresh("t")
                data = "NULL" if not items else "(" + item_type + "[]){" + ", ".join(items) + "}"
                add(f"{ctype(typ)} {name} = {fun}({data}, {len(items)});", indent); return own_temp(typ, name)
            if kind == "constraint_construct":
                values = {key: expr(node[key], indent, scope) for key in node.get("eval_order", ["required", "forbidden", "consistent"]) if node[key] is not None}
                required = "(MrlHornTriple){0}" if node["required"] is None else values["required"]
                forbidden = "(MrlHornTriple){0}" if node["forbidden"] is None else values["forbidden"]
                consistent, name = values.get("consistent") or expr(node["consistent"], indent, scope), fresh("t")
                add(f"MrlConstraint *{name} = mrl_constraint_new({str(node['required'] is not None).lower()}, {required}, {str(node['forbidden'] is not None).lower()}, {forbidden}, {consistent});", indent); return own_temp(typ, name)
            if kind == "interpret":
                values = {key: expr(node[key], indent, scope) for key in node.get("eval_order", ["candidates", "constraints", "budget"])}
                candidates, constraints, budget, name = values["candidates"], values["constraints"], values["budget"], fresh("t")
                add(f"MrlInterpretation *{name} = mrl_horn_interpret({candidates}, {constraints}, {budget});", indent); return own_temp(typ, name)
            if kind == "field":
                value, name = expr(node["value"], indent, scope), fresh("t")
                source_type = node["value"]["type"]
                if source_type.startswith("path:"):
                    add(f"int32_t {name} = {value}.cost;", indent); return name
                if source_type.startswith("paths:"):
                    member = "complete" if node["name"] == "complete" else "reason"
                    add(f"{ctype(typ)} {name} = {value}->{member};", indent); return name
                if source_type == "horn_result":
                    if node["name"] == "reason":
                        add(f"const char *{name} = mrl_string_copy(mrl_horn_reason_name({value}));", indent)
                        return own_temp(typ, name)
                    else: add(f"{ctype(typ)} {name} = {value}->{node['name']};", indent)
                    return name
                if source_type == "horn_snapshot":
                    if ir["version"] in {6, 7}:
                        getter = {"fact_count": "fact_count", "proof_count": "proof_count", "searches": "searches", "complete": "complete", "reason": "reason", "version": "version", "added_count": "added_count", "removed_count": "removed_count"}[node["name"]]
                        raw = f"mrl_horn_snapshot_{getter}({value})"
                        add(f"{ctype(typ)} {name} = {f'mrl_string_copy({raw})' if typ == 's' else raw};", indent)
                        return own_temp(typ, name) if typ == "s" else name
                    add(f"{ctype(typ)} {name} = {value}.{node['name']};", indent); return name
                if source_type == "interpretation":
                    getter = {"status": "mrl_interpretation_status", "reason": "mrl_interpretation_reason", "complete": "mrl_interpretation_complete"}.get(node["name"])
                    if node["name"] == "candidate_id":
                        raw = fresh("candidate_id")
                        add(f"const char *{raw} = mrl_interpretation_candidate_id({value});", indent)
                        add(f"{ctype(typ)} {name} = {{.some=mrl_interpretation_candidate_id_some({value}), .value=mrl_string_copy({raw}), .value_owned=false}};", indent); return own_temp(typ, name)
                    raw = f"{getter}({value})"
                    add(f"{ctype(typ)} {name} = {f'mrl_string_copy({raw})' if typ == 's' else raw};", indent)
                    return own_temp(typ, name) if typ == "s" else name
                field_index = [field[0] for field in info[node["value"]["type"][7:]]].index(node["name"])
                field_value = f"{value}.f{field_index}"
                if managed(typ): field_value = copy_value(typ, field_value)
                add(f"{ctype(typ)} {name} = {field_value};", indent); return own_temp(typ, name)
            if kind == "relation":
                name = fresh("t"); relation = typ[9:]; member = info["$relations"][relation][node["member"]][0]
                add(f"MrlRelation {name} = {{{relation_ids[relation]}, {member}}};", indent); return name
            if kind == "evidence":
                name = fresh("t"); add(f"MrlEvidence {name} = {{{_c_string(node['source'])}, {_c_string(node['text'])}, {node['start']}, {node['end']}}};", indent); return name
            if kind == "graph_add_node":
                value, name = expr(node["value"], indent, scope), fresh("t"); index = graph_ids[node["graph"]] - 1
                payload_type = node["value"]["type"]
                if managed(payload_type) and not take_temp(value): value = copy_value(payload_type, value)
                node_struct = struct_ids[ir["graphs"][index]["node_type"]]
                add(f"MrlNode {name} = mrl_graph_add_node(&mrl_graph_{index});", indent); add(f"*((MrlStruct{node_struct} *)mrl_graph_node_payload(&mrl_graph_{index}, {name})) = {value};", indent); return name
            if kind == "graph_add_edge":
                source, target, relation = expr(node["source"], indent, scope), expr(node["target"], indent, scope), expr(node["relation"], indent, scope)
                payload = expr(node["payload"], indent, scope) if ir["version"] in {4, 5, 6, 7} and node["payload"] is not None else None
                evidence = "(MrlEvidence){0}" if node["evidence"] is None else expr(node["evidence"], indent, scope); index = graph_ids[node["graph"]] - 1
                edge = fresh("edge")
                add(f"uint32_t {edge} = mrl_graph_add_edge(&mrl_graph_{index}, {source}, {target}, {relation}, {evidence});", indent)
                if payload is not None:
                    field = node.get("_cost_field")
                    payload_type = node["payload"]["type"]
                    if managed(payload_type) and not take_temp(payload): payload = copy_value(payload_type, payload)
                    edge_struct = struct_ids[ir["graphs"][index]["edge_type"]]
                    add(f"*((MrlStruct{edge_struct} *)mrl_graph_edge_payload(&mrl_graph_{index}, {edge})) = {payload};", indent)
                return None
            if kind == "graph_remove":
                value = expr(node["value"], indent, scope); index = graph_ids[node['graph']] - 1
                node_type = "struct:" + ir["graphs"][index]["node_type"]
                node_struct = struct_ids[ir["graphs"][index]["node_type"]]
                if managed(node_type): add(release_stmt(node_type, f"*((MrlStruct{node_struct} *)mrl_graph_node_payload(&mrl_graph_{index}, {value}))"), indent)
                edge_type = ir["graphs"][index].get("edge_type")
                if edge_type and managed("struct:" + edge_type):
                    edge_struct = struct_ids[edge_type]
                    add(f"for (uint32_t mrl_edge_i = 0; mrl_edge_i < mrl_graph_{index}.edge_capacity; ++mrl_edge_i) if (mrl_graph_{index}.edges[mrl_edge_i].live && (mrl_graph_{index}.edges[mrl_edge_i].source == {value}.id || mrl_graph_{index}.edges[mrl_edge_i].target == {value}.id)) {{ {release_stmt('struct:' + edge_type, f'*((MrlStruct{edge_struct} *)mrl_graph_edge_payload(&mrl_graph_{index}, mrl_edge_i))')} }}", indent)
                add(f"mrl_graph_remove(&mrl_graph_{index}, {value});", indent); return None
            if kind in {"graph_find", "graph_find_all"}:
                index = graph_ids[node["graph"]] - 1
                relation_name = ir["graphs"][index]["relation"]
                ids = [info["$relations"][relation_name][member][0] for member in node["relations"]]
                allowed = "NULL" if not ids else fresh("relations")
                if ids: add(f"const uint16_t {allowed}[] = {{{', '.join(map(str, ids))}}};", indent)
                source, target, name = expr(node["source"], indent, scope), expr(node["target"], indent, scope), fresh("t")
                directed = "true" if ir["graphs"][index]["directed"] else "false"
                if ir["version"] == 3 or node["method"] == "bfs" and kind == "graph_find":
                    add(f"MrlSearchResult {name} = mrl_graph_find(&mrl_graph_{index}, {directed}, {source}, {target}, {allowed}, {len(ids)}, {node['max_depth']}, {node['max_expansions']});", indent); return own_temp(typ, name)
                method = {"bfs": "MRL_SEARCH_BFS", "dfs": "MRL_SEARCH_DFS", "dijkstra": "MRL_SEARCH_DIJKSTRA", "astar": "MRL_SEARCH_ASTAR"}[node["method"]]
                cost = "NULL"; heuristic = "NULL"
                if node["cost"] is not None:
                    field_index = [field[0] for field in info[ir["graphs"][index]["edge_type"]]].index(node["cost"])
                    edge_struct = struct_ids[ir["graphs"][index]["edge_type"]]
                    add(f"for (uint32_t mrl_cost_i = 0; mrl_cost_i < mrl_graph_{index}.edge_capacity; ++mrl_cost_i) if (mrl_graph_{index}.edges[mrl_cost_i].live) mrl_graph_{index}.edge_costs[mrl_cost_i] = ((MrlStruct{edge_struct} *)mrl_graph_edge_payload(&mrl_graph_{index}, mrl_cost_i))->f{field_index};", indent)
                    cost = f"mrl_graph_{index}.edge_costs"
                if node["heuristic"] is not None: heuristic = f"mrl_heuristic_{index}_{fn_names[node['heuristic']]}"
                if kind == "graph_find":
                    add(f"MrlSearchResult {name} = mrl_graph_find_method(&mrl_graph_{index}, {directed}, {source}, {target}, {allowed}, {len(ids)}, {node['max_depth']}, {node['max_expansions']}, {method}, {cost}, {heuristic});", indent)
                else:
                    slot = fresh("pathset")
                    add(f"MrlPathSet {slot} = {{0}};", indent)
                    add(f"MrlPathsResult {name} = mrl_graph_find_all(&mrl_graph_{index}, {directed}, {source}, {target}, {allowed}, {len(ids)}, {node['max_depth']}, {node['max_expansions']}, {node['max_paths']}, {method}, {cost}, {heuristic}, &{slot});", indent)
                    pathset_temps.append((name, slot))
                return own_temp(typ, name)
            if kind == "index":
                value, index_value, name = expr(node["value"], indent, scope), expr(node["index"], indent, scope), fresh("t")
                if node["value"]["type"].startswith("arr:"):
                    count = node["value"]["type"].rsplit(":", 1)[1]
                    item = f"{value}.items[mrl_array_index({index_value}, {count})]"
                    add(f"{ctype(typ)} {name} = {copy_value(typ, item) if managed(typ) else item};", indent); return own_temp(typ, name)
                if node["value"]["type"].startswith("list:"):
                    item = f"*((const {ctype(typ)} *)mrl_list_at_const({value}, {index_value}))"
                    add(f"{ctype(typ)} {name} = {copy_value(typ, item) if managed(typ) else item};", indent); return own_temp(typ, name)
                add(f"if ({index_value} < 0 || {index_value} >= {value}->length) mrl_runtime_fail(\"MRL path index\");", indent)
                add(f"MrlPath {name} = mrl_path_copy({value}->paths[{index_value}]);", indent); return own_temp(typ, name)
            if kind == "array":
                values = [expr(item, indent, scope) for item in node["items"]]; name = fresh("t"); item = _item_type(typ)
                if typ.startswith("arr:"):
                    values = [value if not managed(item) or take_temp(value) else copy_value(item, value) for value in values]
                    add(f"{ctype(typ)} {name} = {{{{{', '.join(values)}}}}};", indent); return own_temp(typ, name)
                maker = "mrl_list_new_f32" if item == "f32" else "mrl_list_new"
                hooks = "NULL, NULL" if not managed(item) else ("mrl_string_copy_into, mrl_string_drop" if item == "s" else f"mrl_copy_into_{helper_tag(item)}, mrl_drop_{helper_tag(item)}")
                args = f"{len(values)}" if item == "f32" else f"sizeof({ctype(item)}), {len(values)}, {hooks}"
                add(f"MrlList *{name} = {maker}({args});", indent)
                for value in values: add(f"mrl_list_push({name}, &{value});", indent)
                return own_temp(typ, name)
            if kind == "kernel":
                args = [expr(arg, indent, scope) for arg in node["args"]]; name = fresh("t")
                add(f"float {name} = mrl_f32_{node['op']}({', '.join(args)});", indent); return name
            if kind == "result":
                value, name = expr(node["value"], indent, scope), fresh("t")
                member = "value" if node["ok"] else "error"
                payload_type = _result_type_parts(typ)[0 if node["ok"] else 1]
                if managed(payload_type) and not take_temp(value): value = copy_value(payload_type, value)
                add(f"{ctype(typ)} {name} = {{.{member} = {value}, .ok = {'true' if node['ok'] else 'false'}, .value_owned = false}};", indent); return own_temp(typ, name)
            if kind == "option":
                name = fresh("t")
                if not node["some"]:
                    add(f"{ctype(typ)} {name} = {{.some = false, .value_owned = false}};", indent); return own_temp(typ, name)
                value, part = expr(node["value"], indent, scope), _option_part(typ)
                if managed(part) and not take_temp(value): value = copy_value(part, value)
                add(f"{ctype(typ)} {name} = {{.value = {value}, .some = true, .value_owned = false}};", indent); return own_temp(typ, name)
            if kind == "map":
                name=fresh("t"); key, item = _map_parts(typ); hooks="NULL, NULL" if not managed(item) else ("mrl_string_copy_into, mrl_string_drop" if item == "s" else f"mrl_copy_into_{helper_tag(item)}, mrl_drop_{helper_tag(item)}")
                add(f"MrlMap *{name} = mrl_map_new(sizeof({ctype(key)}), {'true' if key == 's' else 'false'}, sizeof({ctype(item)}), {hooks});",indent); return own_temp(typ,name)
            if kind == "map_set":
                m,k,v=expr(node["map"],indent,scope),expr(node["key"],indent,scope),expr(node["value"],indent,scope)
                add(f"mrl_map_set({m}, &{k}, &{v});",indent); return None
            if kind == "map_remove":
                m,k,n=expr(node["map"],indent,scope),expr(node["key"],indent,scope),fresh("t"); add(f"bool {n}=mrl_map_remove({m},&{k});",indent); return n
            if kind == "map_get":
                m,k,n=expr(node["map"],indent,scope),expr(node["key"],indent,scope),fresh("t"); vtype=_result_type_parts(typ)[0]
                add(f"const {ctype(vtype)} *mrl_p_{n}=mrl_map_get({m},&{k});",indent)
                value = f"{copy_value(vtype, f'*mrl_p_{n}') if managed(vtype) else f'*mrl_p_{n}'}"
                add(f"{ctype(typ)} {n}=!mrl_p_{n} ? ({ctype(typ)}){{.ok=false,.error=mrl_string_copy(\"missing map key\"),.value_owned=false}} : ({ctype(typ)}){{.ok=true,.value={value},.value_owned=false}};",indent); return own_temp(typ, n)
            if kind == "horn_load":
                plan, path, name = expr(node["plan"], indent, scope), expr(node["path"], indent, scope), fresh("t")
                add(f"MrlHornLoadResult mrl_load_{name} = mrl_horn_plan_load(&{plan}, {path});", indent)
                add(f"{ctype(typ)} {name} = mrl_load_{name}.ok ? ({ctype(typ)}){{.ok=true,.value=mrl_load_{name}.value,.value_owned=false}} : ({ctype(typ)}){{.ok=false,.error=mrl_string_copy(mrl_load_{name}.error),.value_owned=false}};", indent); return own_temp(typ, name)
            if kind == "list_push":
                target, value = expr(node["list"], indent, scope), expr(node["value"], indent, scope)
                add(f"mrl_list_push({target}, &{value});", indent); return None
            if kind == "horn_query":
                name = fresh("t"); query_index = horn_queries.index(node)
                add(f"const MrlHornResult *{name} = mrl_horn_run({query_index});", indent); return name
            if kind == "horn_plan":
                if ir["version"] in {6, 7}:
                    name = fresh("t"); plan_index = horn_plans.index(node["plan"]); add(f"MrlHornPlan *{name} = mrl_horn_plan_new(&mrl_horn_plan_{plan_index});", indent); return own_temp(typ, name)
                name = fresh("t"); plan_index = horn_plans.index(node["plan"])
                add(f"MrlHornPlan {name} = mrl_horn_plan_new(&mrl_horn_plan_{plan_index});", indent); return name
            if kind == "horn_call":
                name = fresh("t")
                if "plan" in node:
                    order = node.get("eval_order")
                    values = {}
                    if order is None:
                        order = ["plan", *(key for key in ("subject", "predicate", "object") if key in node["filters"]), *(key for key in ("limit", "proof_limit", "search_limit") if key in node["limits"])]
                    for key in order:
                        values[key] = expr(node["plan"] if key == "plan" else node["filters"].get(key, node["limits"].get(key)), indent, scope)
                    plan = values["plan"]
                    filters = {key: values.get(key, "NULL") for key in ("subject", "predicate", "object")}
                    limits = {key: values.get(key, str(default)) for key, default in (("limit", 1000000), ("proof_limit", 32), ("search_limit", 16384))}
                    args = ", ".join(filters[key] for key in ("subject", "predicate", "object"))
                    if node["operation"] == "select": add(f"MrlHornSnapshot *{name} = mrl_horn_plan_select_dynamic({plan}, {args}, {limits['limit']}, {limits['proof_limit']}, {limits['search_limit']});", indent); return own_temp(typ, name)
                    if node["operation"] == "count": add(f"int32_t {name} = mrl_horn_plan_count_dynamic({plan}, {args}, {limits['search_limit']});", indent); return name
                    if node["operation"] == "exists": add(f"bool {name} = mrl_horn_plan_exists({plan}, {args});", indent); return name
                    add(f"int32_t {name} = mrl_horn_plan_epistemic_state({plan}, {args}, {limits['search_limit']});", indent); return name
                snapshot = expr(node["snapshot"], indent, scope); indexes = [expr(value, indent, scope) for value in node["indexes"]]
                op = node["operation"]
                if op == "fact_id": add(f"const char *{name} = mrl_string_copy(mrl_horn_snapshot_fact_id({snapshot}, {indexes[0]}));", indent); return own_temp(typ, name)
                if op in {"subject", "predicate", "object"}:
                    term = {"subject": 0, "predicate": 1, "object": 2}[op]
                    add(f"const char *{name} = mrl_string_copy(mrl_horn_snapshot_term({snapshot}, {indexes[0]}, {term}));", indent); return own_temp(typ, name)
                if op == "fact_polarity": add(f"bool {name} = mrl_horn_snapshot_polarity({snapshot}, {indexes[0]});", indent); return name
                elif op == "proof_count": add(f"int32_t {name} = mrl_horn_snapshot_proof_count_at({snapshot}, {indexes[0]});", indent)
                elif op in {"proof_premise_count", "proof_binding_count"}: add(f"int32_t {name} = mrl_horn_snapshot_{op}({snapshot}, {', '.join(indexes)});", indent)
                elif op in {"proof_id", "proof_kind", "proof_rule", "proof_rule_version", "proof_premise_id"}: add(f"const char *{name} = mrl_string_copy(mrl_horn_snapshot_{op}({snapshot}, {', '.join(indexes)}));", indent); return own_temp(typ, name)
                elif op == "proof_complete": add(f"bool {name} = mrl_horn_snapshot_{op}({snapshot}, {', '.join(indexes)});", indent)
                elif op in {"proof_binding_name", "proof_binding_value"}:
                    binding_name, binding_value = fresh("binding_name"), fresh("binding_value")
                    add(f"const char *{binding_name}, *{binding_value}; mrl_horn_snapshot_binding({snapshot}, {', '.join(indexes)}, &{binding_name}, &{binding_value});", indent); add(f"const char *{name} = mrl_string_copy({binding_name if op.endswith('name') else binding_value});", indent); return own_temp(typ, name)
                else: add(f"{ctype(typ)} {name} = mrl_horn_snapshot_{op}({snapshot}, {indexes[0]});", indent)
                return name
            if kind == "horn_rule_history":
                values = {}
                for token in node["eval_order"]: values[token] = expr(node[token], indent, scope)
                name, plan = fresh("t"), values["plan"]
                if node["operation"] == "add_rule": add(f"bool {name} = mrl_horn_plan_add_rule(&{plan}, &{values['rule']});", indent)
                elif node["operation"] == "replace_rule": add(f"bool {name} = mrl_horn_plan_replace_rule(&{plan}, {values['id']}, &{values['rule']});", indent)
                else: add(f"bool {name} = mrl_horn_plan_remove_rule(&{plan}, {values['id']});", indent)
                if values.get("rule") in rule_version_allocs: add(f"free((void *){rule_version_allocs.pop(values['rule'])});", indent)
                return name
            if kind == "indexed_call":
                values = {}
                for token in node["eval_order"]:
                    if token.startswith("fact:"): values[token] = expr(node["fact"][token[5:]], indent, scope)
                    else: values[token] = expr(node[token], indent, scope)
                name, op = fresh("t"), node["operation"]
                if op == "save": call = f"mrl_indexed_save({values['plan']}->store, {values['path']})"
                elif op == "exists": call = f"mrl_indexed_exists({values['path']}, {values['triple']}[0], {values['triple']}[1], {values['triple']}[2])"
                elif op == "remove": call = f"mrl_indexed_remove({values['path']}, {values['id']})"
                else: call = f"mrl_indexed_{op}({values['path']}, {values['fact:id']}, {values['fact:subject']}, {values['fact:predicate']}, {values['fact:object']}, {values['fact:polarity']})"
                add(f"MrlIndexedResult mrl_indexed_{name} = {call};", indent)
                add(f"{ctype(typ)} {name} = mrl_indexed_{name}.ok ? ({ctype(typ)}){{.ok=true,.value=mrl_indexed_{name}.value,.value_owned=false}} : ({ctype(typ)}){{.ok=false,.error=mrl_string_copy(mrl_indexed_{name}.error),.value_owned=false}};", indent)
                return own_temp(typ, name)
            if kind == "horn_history":
                plan, ident, name = expr(node["plan"], indent, scope), expr(node["id"], indent, scope), fresh("t")
                if node["operation"] == "withdraw": add(f"bool {name} = mrl_horn_plan_withdraw(&{plan}, {ident});", indent); return name
                if node["operation"] == "superseded_by": add(f"const char *{name} = mrl_string_copy(mrl_horn_plan_superseded_by({plan}, {ident}, \"mrl:supersededBy\"));", indent); return own_temp(typ, name)
                if node["operation"] == "history_fact": add(f"MrlHornSnapshot *{name} = mrl_horn_plan_history_fact({plan}, {ident});", indent); return own_temp(typ, name)
                fields = {"polarity": "true", "modality": _c_string("asserted"), "evidence": "(MrlHornEvidence){0}"}
                for key, value in node["fact"].items(): fields[key] = expr(value, indent, scope)
                evidence = fields["evidence"]
                if node["fact"].get("evidence") is not None:
                    fields["evidence"] = f"(MrlHornEvidence){{!!{evidence}.source,{evidence}.source,{evidence}.text,{evidence}.start,{evidence}.end}}"
                fun = "mrl_horn_plan_" + node["operation"]
                add(f"bool {name} = {fun}(&{plan}, {ident}, {fields['id']}, {fields['subject']}, {fields['predicate']}, {fields['object']}, {fields['polarity']}, {fields['modality']}, {fields['evidence']});", indent); return name
            if kind == "horn_add":
                plan = expr(node["plan"], indent, scope); fields = {"polarity": "true", "modality": _c_string("asserted"), "evidence": "(MrlEvidence){0}"}
                for field in node["fact"]: fields[field["name"]] = expr(field["value"], indent, scope)
                evidence, name = fields["evidence"], fresh("t"); add(f"bool {name} = mrl_horn_plan_add(&{plan}, {fields['id']}, {fields['subject']}, {fields['predicate']}, {fields['object']}, {fields['polarity']}, {fields['modality']}, (MrlHornEvidence){{!!{evidence}.source,{evidence}.source,{evidence}.text,{evidence}.start,{evidence}.end}});", indent); return name
            if kind == "horn_correct":
                plan = expr(node["plan"], indent, scope); fields = {"polarity": "true", "modality": _c_string("asserted"), "evidence": "(MrlEvidence){0}"}
                for field in node["fact"]: fields[field["name"]] = expr(field["value"], indent, scope)
                evidence, name = fields["evidence"], fresh("t"); add(f"bool {name} = mrl_horn_plan_correct(&{plan}, {fields['id']}, {fields['subject']}, {fields['predicate']}, {fields['object']}, {fields['polarity']}, {fields['modality']}, (MrlHornEvidence){{!!{evidence}.source,{evidence}.source,{evidence}.text,{evidence}.start,{evidence}.end}});", indent); return name
            if kind in {"horn_exists", "horn_count", "horn_select", "horn_explain"}:
                plan, name = expr(node["plan"], indent, scope), fresh("t"); triple = ", ".join("NULL" if value is None else _c_string(value) for value in node["triple"])
                fun = "mrl_horn_plan_" + kind[5:]
                add(f"{ctype(typ)} {name} = {fun}({plan}, {triple});", indent); return own_temp(typ, name)
            if kind == "horn_changes":
                plan, name = expr(node["plan"], indent, scope), fresh("t"); add(f"MrlHornSnapshot *{name} = mrl_horn_plan_changes({plan});", indent); return own_temp(typ, name)
            if kind in {"horn_save", "horn_restore", "horn_commit"}:
                plan, path, name = expr(node["plan"], indent, scope), expr(node["path"], indent, scope), fresh("t")
                call = f"mrl_horn_plan_{kind[5:]}({'&' if kind in {'horn_restore', 'horn_commit'} else ''}{plan}, {path})"
                add(f"MrlHornLoadResult mrl_load_{name} = {call};", indent); add(f"{ctype(typ)} {name} = mrl_load_{name}.ok ? ({ctype(typ)}){{.ok=true,.value=mrl_load_{name}.value,.value_owned=false}} : ({ctype(typ)}){{.ok=false,.error=mrl_string_copy(mrl_load_{name}.error),.value_owned=false}};", indent); return own_temp(typ, name)
            if kind == "horn_remove":
                plan, ident, name = expr(node["plan"], indent, scope), expr(node["id"], indent, scope), fresh("t")
                add(f"bool {name} = mrl_horn_plan_remove(&{plan}, {ident});", indent); return name
            if kind == "horn_evaluate":
                plan, name = expr(node["plan"], indent, scope), fresh("t"); target = node["target"]
                targets = ["NULL", "NULL", "NULL"] if target is None else [_c_string(value) for value in target]
                if ir["version"] in {6, 7}:
                    add(f"MrlHornSnapshot *{name} = mrl_horn_evaluate({plan}, {1 if node['operation'] == 'closure' else 2}, {node['limit']}, {node['proof_limit']}, {node['search_limit']}, {1 if target is not None else 0}, {targets[0]}, {targets[1]}, {targets[2]});", indent); return own_temp(typ, name)
                add(f"MrlHornSnapshot {name} = mrl_horn_evaluate(&{plan}, {1 if node['operation'] == 'closure' else 2}, {node['limit']}, {node['proof_limit']}, {node['search_limit']}, {1 if target is not None else 0}, {targets[0]}, {targets[1]}, {targets[2]});", indent); return name
            if kind == "horn_version":
                plan, name = expr(node["plan"], indent, scope), fresh("t"); add(f"int32_t {name} = {'mrl_horn_plan_version(' + plan + ')' if ir['version'] in {6, 7} else plan + '.version'};", indent); return name
            if kind == "len":
                value, name = expr(node["value"], indent, scope), fresh("t")
                code = f"mrl_string_len({value})" if node["value"]["type"] == "s" else f"(int32_t){value}{'->' if node['value']['type'].startswith('paths:') else '.'}length"
                if node["value"]["type"].startswith("arr:"): code = node["value"]["type"].rsplit(":", 1)[1]
                elif node["value"]["type"].startswith("list:"): code = f"mrl_list_len({value})"
                elif node["value"]["type"].startswith("map:"): code = f"(int32_t){value}->length"
                add(f"int32_t {name} = {code};", indent); return name
            value = expr(node["value"], indent, scope)
            if node["value"]["type"] == "si32": add(f"printf(\"%\" PRId32 \"\\n\", {value});", indent)
            elif node["value"]["type"] in {"si8", "si16", "si64"}: add(f"printf(\"%\" PRId64 \"\\n\", (int64_t){value});", indent)
            elif node["value"]["type"] in {"ui8", "ui16", "ui32", "ui64"}: add(f"printf(\"%\" PRIu64 \"\\n\", (uint64_t){value});", indent)
            elif node["value"]["type"] == "b": add(f"puts({value} ? \"true\" : \"false\");", indent)
            elif node["value"]["type"] == "s": add(f"puts({value});", indent)
            elif node["value"]["type"] == "f32": add(f"printf(\"%.9g\\n\", (double){value});", indent)
            elif node["value"]["type"] == "f64": add(f"printf(\"%.17g\\n\", {value});", indent)
            elif node["value"]["type"] == "horn_result": add(f"mrl_horn_print_result({value});", indent)
            elif node["value"]["type"] == "horn_snapshot": add(f"{'mrl_horn_snapshot_print(' + value + ')' if ir['version'] >= 6 else 'mrl_horn_print_snapshot(&' + value + ')'};", indent)
            else: add(f"puts(mrl_search_error_name({value}));", indent)
            return None
        def block(statements, indent, scope):
            nonlocal owned
            saved_owned = owned.copy()
            for statement in statements:
                kind = statement["kind"]
                if kind == "let":
                    value, name = expr(statement["value"], indent, scope), fresh("v"); scope[statement["name"]] = name
                    if statement["type"].startswith("result:paths:"):
                        slot = take_pathset(name)
                        source_slot = take_pathset_temp(value)
                        add(f"MrlPathsResult {name} = {value};", indent); add(f"if ({name}.ok) {{ mrl_pathset_copy({slot}, {name}.paths); {name}.paths = {slot}; }}", indent)
                        if source_slot: add(f"mrl_pathset_release(&{source_slot});", indent)
                    elif statement["type"].startswith("paths:"):
                        slot = take_pathset(name)
                        add(f"MrlPathSet *{name} = {value};", indent); add(f"mrl_pathset_copy({slot}, {name}); {name} = {slot};", indent)
                    else:
                        typ = statement["type"]
                        transferred = managed(typ) and take_temp(value)
                        if managed(typ) and not transferred: value = copy_value(typ, value)
                        add(f"{ctype(typ)} {name} = {value};", indent)
                        value_types[name] = typ
                        if managed(typ): owned[name] = typ
                        release_temps(indent)
                elif kind == "assign":
                    value = expr(statement["value"], indent, scope); target = scope[statement["name"]]
                    if statement["value"]["type"].startswith("result:paths:"):
                        slot = f"&mrl_pathsets[{pathsets[target]}]"; add(f"{target} = {value};", indent); add(f"if ({target}.ok) {{ mrl_pathset_copy({slot}, {target}.paths); {target}.paths = {slot}; }}", indent)
                        source_slot = take_pathset_temp(value)
                        if source_slot: add(f"mrl_pathset_release(&{source_slot});", indent)
                    elif statement["value"]["type"].startswith("paths:"):
                        slot = f"&mrl_pathsets[{pathsets[target]}]"; add(f"{target} = {value};", indent); add(f"mrl_pathset_copy({slot}, {target}); {target} = {slot};", indent)
                    else:
                        typ = statement["value"]["type"]
                        if managed(typ):
                            transferred = take_temp(value)
                            copy = value if transferred else fresh("copy")
                            if not transferred: add(f"{ctype(typ)} {copy} = {copy_value(typ, value)};", indent)
                            release_value(typ, target, indent); add(f"{target} = {copy};", indent)
                        else: add(f"{target} = {value};", indent)
                        release_temps(indent)
                elif kind == "array_assign":
                    target = scope[statement["name"]]; index = expr(statement["index"], indent, scope); value = expr(statement["value"], indent, scope)
                    item = statement["value"]["type"]; slot = f"{target}.items[mrl_array_index({index}, sizeof({target}.items)/sizeof({target}.items[0]))]"
                    if managed(item):
                        transfer = take_temp(value); copy = value if transfer else copy_value(item, value)
                        release_value(item, slot, indent); add(f"{slot} = {copy};", indent)
                    else: add(f"{slot} = {value};", indent)
                elif kind == "field_assign":
                    target, value = scope[statement["name"]], expr(statement["value"], indent, scope)
                    target_type = value_types[target]
                    field_index = [field[0] for field in info[target_type[7:]]].index(statement["field"])
                    field_type = statement["value"]["type"]
                    slot = f"{target}.f{field_index}"
                    if managed(field_type):
                        transferred = take_temp(value)
                        copy = value if transferred else copy_value(field_type, value)
                        release_value(field_type, slot, indent)
                        add(f"{slot} = {copy};", indent)
                    else:
                        add(f"{slot} = {value};", indent)
                    release_temps(indent)
                elif kind == "return":
                    if statement["value"] is None:
                        release_temps(indent)
                        for slot, slot_type in reversed(list(owned.items())): release_value(slot_type, slot, indent)
                        add(f"for (uint32_t mrl_pathset_i = 0; mrl_pathset_i < {pathset_count}; ++mrl_pathset_i) mrl_pathset_release(&mrl_pathsets[mrl_pathset_i]);", indent); add("free(mrl_pathsets); return;", indent)
                    else:
                        value, name = expr(statement["value"], indent, scope), fresh("return")
                        typ = statement["value"]["type"]
                        transferred = managed(typ) and take_temp(value)
                        if managed(typ) and not transferred: value = copy_value(typ, value)
                        add(f"{ctype(typ)} {name} = {value};", indent)
                        release_temps(indent)
                        for slot, slot_type in reversed(list(owned.items())): release_value(slot_type, slot, indent)
                        add(f"for (uint32_t mrl_pathset_i = 0; mrl_pathset_i < {pathset_count}; ++mrl_pathset_i) mrl_pathset_release(&mrl_pathsets[mrl_pathset_i]);", indent); add(f"free(mrl_pathsets); return {name};", indent)
                elif kind == "expr": expr(statement["value"], indent, scope); release_temps(indent)
                elif kind in {"break", "continue"}:
                    release_temps(indent)
                    for slot, slot_type in reversed(list(owned.items())):
                        if slot not in loop_frames[-1]: release_value(slot_type, slot, indent)
                    add(kind + ";", indent)
                elif kind == "if":
                    condition = expr(statement["condition"], indent, scope); release_temps(indent); add(f"if ({condition}) {{", indent); block(statement["then"], indent + 1, scope.copy()); add("} else {", indent); block(statement["else"], indent + 1, scope.copy()); add("}", indent)
                elif kind == "while":
                    add("while (true) {", indent); condition = expr(statement["condition"], indent + 1, scope); release_temps(indent + 1); add(f"if (!{condition}) break;", indent + 1)
                    loop_frames.append(owned.copy()); block(statement["body"], indent + 1, scope.copy()); loop_frames.pop(); add("}", indent)
                elif kind == "for":
                    start_value, stop_value = expr(statement["start"], indent, scope), expr(statement["stop"], indent, scope)
                    start, stop, index, var = fresh("bound"), fresh("bound"), fresh("range"), fresh("v")
                    add(f"int32_t {start} = {start_value};", indent); add(f"int32_t {stop} = {stop_value};", indent); release_temps(indent)
                    add(f"for (int64_t {index} = {start}; {index} < (int64_t){stop}; ++{index}) {{", indent); add(f"const int32_t {var} = (int32_t){index};", indent + 1); nested = scope.copy(); nested[statement["name"]] = var
                    loop_frames.append(owned.copy()); block(statement["body"], indent + 1, nested); loop_frames.pop(); add("}", indent)
                elif kind == "for_each":
                    source = expr(statement["source"], indent, scope)
                    source_type, item_type, index, item = statement["source"]["type"], statement["item_type"], fresh("each_i"), fresh("each")
                    if managed(source_type):
                        if take_temp(source): owned[source] = source_type
                        else:
                            held = fresh("each_source")
                            add(f"{ctype(source_type)} {held} = {copy_value(source_type, source)};", indent)
                            owned[held] = source_type; source = held
                    release_temps(indent)
                    nested = scope.copy(); nested[statement["name"]] = item
                    if source_type.startswith("list:"):
                        add(f"for (int32_t {index} = 0; {index} < mrl_list_len({source}); ++{index}) {{", indent)
                        element = f"*((const {ctype(item_type)} *)mrl_list_at_const({source}, {index}))"
                        add(f"{ctype(item_type)} {item} = {copy_value(item_type, element) if managed(item_type) else element};", indent + 1)
                    elif source_type.startswith("arr:"):
                        count = source_type.rsplit(":", 1)[1]
                        add(f"for (int32_t {index} = 0; {index} < {count}; ++{index}) {{", indent)
                        element = f"{source}.items[{index}]"
                        add(f"{ctype(item_type)} {item} = {copy_value(item_type, element) if managed(item_type) else element};", indent + 1)
                    else:
                        key_type = _map_parts(source_type)[0]
                        add(f"for (uint32_t {index} = 0; {index} < {source}->length; ++{index}) {{", indent)
                        key = f"*(const {ctype(key_type)} *){source}->items[{index}].key" if key_type != "s" else f"(const char *){source}->items[{index}].key"
                        add(f"{ctype(item_type)} {item} = {copy_value(item_type, key) if managed(item_type) else key};", indent + 1)
                    frame = owned.copy()
                    if managed(item_type): owned[item] = item_type
                    loop_frames.append(frame); block(statement["body"], indent + 1, nested); loop_frames.pop()
                    if managed(item_type): release_value(item_type, item, indent + 1); owned.pop(item)
                    add("}", indent)
                    if managed(source_type):
                        release_value(source_type, source, indent); owned.pop(source)
                elif kind == "unsafe":
                    add("{", indent); block(statement["body"], indent + 1, scope.copy()); add("}", indent)
                elif kind == "match_option":
                    value, some = expr(statement["value"], indent, scope), fresh("v")
                    part = _option_part(statement["value"]["type"])
                    typ = statement["value"]["type"]
                    stabilized = managed(typ)
                    if stabilized:
                        if take_temp(value): owned[value] = typ
                        else:
                            held = fresh("match")
                            add(f"{ctype(typ)} {held} = {copy_value(typ, value)};", indent)
                            owned[held] = typ; value = held
                    release_temps(indent)
                    add(f"if ({value}.some) {{", indent); add(f"{ctype(part)} {some} = {value}.value;", indent + 1)
                    nested = scope.copy(); nested[statement["some_name"]] = some; block(statement["some"], indent + 1, nested)
                    add("} else {", indent); block(statement["none"], indent + 1, scope.copy()); add("}", indent)
                    if stabilized: release_value(typ, value, indent); owned.pop(value)
                elif kind == "match_enum":
                    value = expr(statement["value"], indent, scope)
                    for index, arm in enumerate(statement["arms"]):
                        prefix = "if" if not index else "else if"
                        add(f"{prefix} ({value} == {info['$enums'][statement['value']['type'][5:]].index(arm['member'])}) {{", indent); block(arm["body"], indent + 1, scope.copy()); add("}", indent)
                else:
                    value = expr(statement["value"], indent, scope); ok, err = fresh("v"), fresh("v")
                    source_slot = take_pathset_temp(value) if statement["value"]["type"].startswith("result:paths:") else None
                    typ = statement["value"]["type"]
                    stabilized = managed(typ)
                    if stabilized:
                        if take_temp(value): owned[value] = typ
                        else:
                            held = fresh("match")
                            add(f"{ctype(typ)} {held} = {copy_value(typ, value)};", indent)
                            owned[held] = typ; value = held
                    release_temps(indent)
                    result_parts = _result_type_parts(typ)
                    if ir["version"] in {6, 7} and result_parts:
                        ok_type, err_type = result_parts
                        add(f"if ({value}.ok) {{", indent); add(f"{ctype(ok_type)} {ok} = {value}.value;", indent + 1); nested = scope.copy(); nested[statement["ok_name"]] = ok; block(statement["ok"], indent + 1, nested); add("} else {", indent); add(f"{ctype(err_type)} {err} = {value}.error;", indent + 1); nested = scope.copy(); nested[statement["err_name"]] = err; block(statement["err"], indent + 1, nested); add("}", indent)
                        if stabilized: release_value(typ, value, indent); owned.pop(value)
                        continue
                    add(f"if ({value}.ok) {{", indent)
                    ok_type = "MrlPathSet *" if statement["value"]["type"].startswith("result:paths:") else "MrlPath"
                    ok_value = f"{value}.paths" if ok_type.startswith("MrlPathSet") else f"{value}.path"
                    add(f"{ok_type} {ok} = {ok_value};", indent + 1)
                    if ok_type.startswith("MrlPathSet"):
                        slot = take_pathset(ok); add(f"mrl_pathset_copy({slot}, {ok}); {ok} = {slot};", indent + 1)
                    nested = scope.copy(); nested[statement["ok_name"]] = ok; block(statement["ok"], indent + 1, nested); add("} else {", indent); add(f"MrlSearchError {err} = {value}.error;", indent + 1); nested = scope.copy(); nested[statement["err_name"]] = err; block(statement["err"], indent + 1, nested); add("}", indent)
                    if source_slot: add(f"mrl_pathset_release(&{source_slot});", indent)
                    if stabilized: release_value(typ, value, indent); owned.pop(value)
            for slot, slot_type in reversed(list(owned.items())):
                if slot not in saved_owned: release_value(slot_type, slot, indent)
            release_temps(indent)
            owned = saved_owned
        result, params = signature(function); lines.append(f"static {result} {fn_names[function['name']]}({params}) {{")
        lines.append("    MrlPathSet *mrl_pathsets = NULL;")
        if ir["version"] in {6, 7}:
            for index, param in enumerate(function["params"]):
                typ = param["type"]
                if managed(typ):
                    local = f"mrl_arg_{index}"
                    lines.append(f"    {ctype(typ)} {local} = {copy_value(typ, f'mrl_p_{index}')};")
                    values[param["name"]] = local; owned[local] = typ
        if pathset_count: lines.append(f"    mrl_pathsets = calloc({pathset_count}, sizeof(*mrl_pathsets)); if (!mrl_pathsets) mrl_runtime_fail(\"MRL path set allocation\");")
        block(function["body"], 1, values)
        if function["return_type"] is None:
            for slot, slot_type in reversed(list(owned.items())): release_value(slot_type, slot, 1)
            lines.append(f"    for (uint32_t mrl_pathset_i = 0; mrl_pathset_i < {pathset_count}; ++mrl_pathset_i) mrl_pathset_release(&mrl_pathsets[mrl_pathset_i]);")
            lines.append("    free(mrl_pathsets);")
        lines.extend(["}", ""])
    lines.append("int main(int argc, char **argv) {" if has_io else "int main(void) {")
    if has_io: lines.append("    mrl_io_set_argv(argc, argv);")
    lines.append("    mrl_init_graphs();")
    if functions["main"][1] == "si32": lines.append(f"    int32_t result = {fn_names['main']}();"); lines.append('    printf("%" PRId32 "\\n", result);')
    else: lines.append(f"    {fn_names['main']}();")
    if ir["version"] in {6, 7}:
        for index, graph in enumerate(ir["graphs"]):
            node_type = "struct:" + graph["node_type"]
            if managed_type(node_type):
                node_struct = struct_ids[graph["node_type"]]
                lines.append(f"    for (uint32_t mrl_node_i = 0; mrl_node_i < mrl_graph_{index}.node_capacity; ++mrl_node_i) if (mrl_graph_{index}.nodes[mrl_node_i]) {{ {release_stmt(node_type, f'*((MrlStruct{node_struct} *)(mrl_graph_{index}.node_payloads + (size_t)mrl_node_i * mrl_graph_{index}.node_payload_size))')} }}")
            if graph.get("edge_type") and managed_type("struct:" + graph["edge_type"]):
                edge_type = "struct:" + graph["edge_type"]
                edge_struct = struct_ids[graph["edge_type"]]
                lines.append(f"    for (uint32_t mrl_edge_i = 0; mrl_edge_i < mrl_graph_{index}.edge_capacity; ++mrl_edge_i) if (mrl_graph_{index}.edges[mrl_edge_i].live) {{ {release_stmt(edge_type, f'*((MrlStruct{edge_struct} *)(mrl_graph_{index}.edge_payloads + (size_t)mrl_edge_i * mrl_graph_{index}.edge_payload_size))')} }}")
    for index, graph in enumerate(ir["graphs"]):
        lines.append(f"    mrl_graph_destroy(&mrl_graph_{index});")
    if has_io: lines.append("    mrl_io_cleanup_argv();")
    lines.extend(["    return 0;", "}", ""])
    return "\n".join(lines)


def emit_c(ir):
    """Validate MRL IR v1/v2/v3/v4 and emit portable checked C11."""
    if isinstance(ir, dict) and ir.get("version") == 3:
        functions, info = _validate_v3(ir)
        return _emit_v3(ir, functions, info)
    if isinstance(ir, dict) and ir.get("version") == 4:
        functions, info = _validate_v4(ir)
        return _emit_v3(ir, functions, info)
    if isinstance(ir, dict) and ir.get("version") == 5:
        functions, info = _validate_v5(ir)
        return _emit_v3(ir, functions, info)
    if isinstance(ir, dict) and ir.get("version") == 6:
        functions, info = _validate_v6(ir)
        return _emit_v3(ir, functions, info)
    if isinstance(ir, dict) and ir.get("version") == 7:
        functions, info = _validate_v7(ir)
        return _emit_v3(ir, functions, info)
    return _emit_c(ir, _validate(ir))
