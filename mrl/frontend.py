"""Primitive MRL frontend: source -> AST -> checked neutral IR."""

from __future__ import annotations

from dataclasses import dataclass, field
from math import isfinite

from .language_ffi import lower_extern, lower_ffi_call, parse_extern
from .language_io import lower_io_call

_SCALARS = {"si8", "si16", "si32", "si64", "ui8", "ui16", "ui32", "ui64", "f32", "f64", "b", "s"}
_BUILTIN_ENUMS = {
    "InterpretationStatus": ("selected", "ambiguous", "unknown", "contradicted", "incomplete"),
    "EpistemicState": ("known", "unknown", "ambiguous", "contradicted", "withdrawn", "incomplete"),
}


def _option_part(value):
    return value[7:-1] if isinstance(value, str) and value.startswith("option<") and value.endswith(">") else None


def _item_type(value):
    if value.startswith("list:"): return value[5:]
    if value.startswith("arr:"): return value[4:].rsplit(":", 1)[0]
    return None


def _map_parts(value):
    if not isinstance(value, str) or not value.startswith("map:"):
        return None
    parts = value[4:].split(":", 1)
    return tuple(parts) if len(parts) == 2 else None


class MrlError(ValueError):
    """A source-located MRL diagnostic."""

    def __init__(self, message: str, line: int, column: int):
        self.message, self.line, self.column = message, line, column
        super().__init__(f"{line}:{column}: {message}")


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    line: int
    column: int


# The v3/v4 source forms deliberately share the primitive frontend's token/error
# conventions.  Keeping this parser here avoids a second, incompatible DSL.
@dataclass
class _V3Program:
    functions: list[dict]
    structs: list[dict]
    enums: list[dict]
    relations: list[dict]
    graphs: list[dict]
    externs: list[dict] = field(default_factory=list)


class _V3Function(dict):
    """Keeps the old parse(source).functions[0].name inspection usable."""
    @property
    def name(self): return self["name"].text


def _v3lex(source: str) -> list[Token]:
    tokens: list[Token] = []
    i = line = 0; column = 1
    keywords = {"fn", "extern", "unsafe", "dec", "return", "true", "false", "if", "else", "while", "for", "in", "struct", "enum", "relation", "graph", "match", "and", "or", "not", "break", "continue"}
    while i < len(source):
        char = source[i]
        if char in " \t\r": i += 1; column += 1
        elif char == "\n": i += 1; line += 1; column = 1
        elif char == "#":
            end = source.find("#", i + 1)
            if end < 0: raise MrlError("unterminated # comment", line + 1, column)
            text = source[i:end + 1]; count = text.count("\n"); line += count; column = len(text.rsplit("\n", 1)[-1]) + 1 if count else column + len(text); i = end + 1
        elif char == '"':
            start_line, start_column = line + 1, column; i += 1; column += 1; out = []
            while i < len(source) and source[i] != '"':
                if source[i] in "\r\n": raise MrlError("unterminated string literal", start_line, start_column)
                if source[i] == "\\":
                    if i + 1 == len(source) or source[i + 1] not in {'"', "\\", "n", "t"}: raise MrlError("unsupported string escape", line + 1, column)
                    out.append({"n": "\n", "t": "\t"}.get(source[i + 1], source[i + 1])); i += 2; column += 2
                else: out.append(source[i]); i += 1; column += 1
            if i == len(source): raise MrlError("unterminated string literal", start_line, start_column)
            value = "".join(out)
            if "\0" in value or any(0xD800 <= ord(c) <= 0xDFFF for c in value): raise MrlError("string literal contains unsupported NUL or surrogate", start_line, start_column)
            tokens.append(Token("string", value, start_line, start_column)); i += 1; column += 1
        elif char.isascii() and (char.isalpha() or char == "_"):
            start = i
            while i < len(source) and source[i].isascii() and (source[i].isalnum() or source[i] == "_"): i += 1
            value = source[start:i]; tokens.append(Token(value if value in keywords else "name", value, line + 1, column)); column += i - start
        elif char.isascii() and char.isdigit():
            start = i
            while i < len(source) and source[i].isascii() and source[i].isdigit(): i += 1
            floating = False
            if i < len(source) and source[i] == "." and i + 1 < len(source) and source[i + 1].isdigit():
                i += 1
                while i < len(source) and source[i].isascii() and source[i].isdigit(): i += 1
                floating = True
            if i < len(source) and source[i] in "eE" and i + 1 < len(source):
                exponent = i + 1
                if source[exponent] in "+-": exponent += 1
                if exponent < len(source) and source[exponent].isdigit():
                    i = exponent + 1
                    while i < len(source) and source[i].isascii() and source[i].isdigit(): i += 1
                    floating = True
            if floating:
                if i < len(source) and source[i] == "f": i += 1
                tokens.append(Token("float", source[start:i], line + 1, column))
            else: tokens.append(Token("number", source[start:i], line + 1, column))
            column += i - start
        else:
            two = source[i:i + 2]
            if two in {"->", ":=", "==", "!=", "<=", ">=", ".."}: tokens.append(Token(two, two, line + 1, column)); i += 2; column += 2
            elif char in "(){}:,+-*/%<>=.[]?": tokens.append(Token(char, char, line + 1, column)); i += 1; column += 1
            else: raise MrlError(f"unsupported character {char!r}", line + 1, column)
    return [*tokens, Token("eof", "", line + 1, column)]


class _V3Parser:
    def __init__(self, source: str): self.tokens, self.at = _v3lex(source), 0
    def cur(self): return self.tokens[self.at]
    def take(self, kind):
        token = self.cur()
        if token.kind != kind: raise MrlError(f"expected {kind!r}, found {token.text!r}", token.line, token.column)
        self.at += 1; return token
    def match(self, kind): return self.take(kind) if self.cur().kind == kind else None
    def typ(self):
        token = self.take("name"); raw = "si32" if token.text == "si" else token.text
        if self.match("<"):
            parts = [self.typ()]
            while self.match(","):
                if self.cur().kind == "number": parts.append(self.take("number").text)
                else: parts.append(self.typ())
            self.take(">")
            if raw == "arr" and len(parts) == 2 and parts[1].isdigit() and 0 < int(parts[1]) <= 16384:
                raw = f"arr:{parts[0]}:{int(parts[1])}"
            elif raw == "list" and len(parts) == 1: raw = f"list:{parts[0]}"
            elif raw == "Result" and len(parts) == 2:
            # Keep the original colon spelling for primitive Results, while
            # preserving arbitrary nested payload syntax for source lowering.
                raw = "result:" + ":".join(parts) if all(part in {"si32", "f32", "s", "b"} for part in parts) else "result<" + ",".join(parts) + ">"
            elif raw == "map" and len(parts) == 2: raw = "map:" + parts[0] + ":" + parts[1]
            elif raw == "ptr" and len(parts) == 1: raw = "ptr:" + parts[0]
            else: raise MrlError("unsupported generic type", token.line, token.column)
        return "option<" + raw + ">" if self.match("?") else raw
    def parse(self):
        p = _V3Program([], [], [], [], [])
        while self.cur().kind != "eof":
            if self.cur().kind == "extern": p.externs.append(parse_extern(self))
            elif self.cur().kind == "struct": p.structs.append(self.struct())
            elif self.cur().kind == "enum": p.enums.append(self.enum())
            elif self.cur().kind == "relation": p.relations.append(self.relation())
            elif self.cur().kind == "graph": p.graphs.append(self.graph())
            else: p.functions.append(self.function())
        return p
    def enum(self):
        token = self.take("enum"); name = self.take("name"); self.take("{"); members = []
        while self.cur().kind != "}": members.append(self.take("name"))
        self.take("}"); return {"token": token, "name": name, "members": members}
    def struct(self):
        token = self.take("struct"); name = self.take("name"); self.take("{"); fields = []
        while self.cur().kind != "}":
            field = self.take("name"); self.take(":"); fields.append((field, self.typ()))
        self.take("}"); return {"token": token, "name": name, "fields": fields}
    def relation(self):
        token = self.take("relation"); name = self.take("name"); self.take("{"); members = []
        while self.cur().kind != "}":
            member = self.take("name"); self.take("{"); meta = {}
            while self.cur().kind != "}":
                key = self.take("name"); self.take(":")
                if key.text in meta: raise MrlError(f"duplicate relation metadata {key.text!r}", key.line, key.column)
                meta[key.text] = self.take("name")
            self.take("}"); members.append((member, meta))
        self.take("}"); return {"token": token, "name": name, "members": members}
    def graph(self):
        token = self.take("graph"); name = self.take("name"); self.take("{"); fields = {}
        while self.cur().kind != "}":
            key = self.cur(); self.at += 1; self.take(":")
            if key.text in fields: raise MrlError(f"duplicate graph field {key.text!r}", key.line, key.column)
            fields[key.text] = self.cur(); self.at += 1
        self.take("}"); return {"token": token, "name": name, "fields": fields}
    def function(self):
        token = self.take("fn"); name = self.take("name"); self.take("("); params = []
        if self.cur().kind != ")":
            while True:
                param = self.take("name"); self.take(":"); params.append((param, self.typ()))
                if not self.match(","): break
        self.take(")"); result = self.typ() if self.match("->") else None
        return _V3Function({"token": token, "name": name, "params": params, "return": result, "body": self.block()})
    def block(self):
        self.take("{"); body = []
        while self.cur().kind != "}":
            if self.cur().kind == "eof": raise MrlError("unterminated block", self.cur().line, self.cur().column)
            body.append(self.stmt())
        self.take("}"); return body
    def stmt(self):
        token = self.cur()
        if self.match("unsafe"):
            return ("unsafe", token, self.block())
        if self.match("if"):
            self.take("("); value = self.expr(); self.take(")"); yes = self.block(); otherwise = self.match("else")
            no = None if otherwise is None else (self.block() if self.cur().kind == "{" else [self.stmt()])
            return ("if", token, value, yes, no)
        if self.match("while"):
            self.take("("); value = self.expr(); self.take(")"); return ("while", token, value, self.block())
        if self.match("for"):
            self.take("("); name = self.take("name"); self.take("in"); start = self.expr()
            if self.match(".."): stop = self.expr(); self.take(")"); return ("for", token, name, start, stop, self.block())
            self.take(")"); return ("for_each", token, name, start, self.block())
        if self.match("break"): return ("break", token)
        if self.match("continue"): return ("continue", token)
        if self.match("dec"):
            name = self.take("name"); annotation = self.typ() if self.match(":") else None; self.take("="); return ("let", token, name, False, self.expr(), annotation)
        if self.match("return"): return ("return", token, None if self.cur().kind == "}" else self.expr())
        if self.match("match"):
            self.take("("); value = self.expr(); self.take(")"); self.take("{"); arms = {}
            while self.cur().kind != "}":
                kind = self.take("name"); binder = None
                if self.match("."):
                    member = self.take("name")
                    kind = Token("qualified", kind.text + "." + member.text, kind.line, kind.column)
                if self.match("("):
                    if self.cur().kind != ")": binder = self.take("name")
                    self.take(")")
                if kind.text in arms: raise MrlError(f"duplicate match arm {kind.text!r}", kind.line, kind.column)
                arms[kind.text] = (binder, self.block())
            self.take("}")
            return ("match", token, value, arms)
        if token.kind == "name" and self.tokens[self.at + 1].kind in {"=", ":="}:
            name = self.take("name"); op = self.cur(); self.at += 1; return (("let" if op.kind == "=" else "assign"), name, name, op.kind == "=", self.expr())
        if token.kind == "name" and self.tokens[self.at + 1].kind == ":":
            name=self.take("name"); self.take(":"); annotation=self.typ(); self.take("="); return ("let", token, name, True, self.expr(), annotation)
        if token.kind == "name" and self.tokens[self.at + 1].kind == "." and self.tokens[self.at + 2].kind == "name" and self.tokens[self.at + 3].kind == ":=":
            base=self.take("name"); self.take("."); field=self.take("name"); self.take(":="); return ("field_assign", token, base, field, self.expr())
        if token.kind == "name" and self.tokens[self.at + 1].kind == "[":
            name=self.take("name"); self.take("["); index=self.expr(); self.take("]"); self.take(":="); return ("array_assign", token, name, index, self.expr())
        return ("expr", token, self.expr())
    def expr(self): return self.logical_or()
    def logical_or(self):
        value = self.logical_and()
        while self.match("or"):
            op = self.tokens[self.at - 1]; value = ("binary", op, "or", value, self.logical_and())
        return value
    def logical_and(self):
        value = self.compare()
        while self.match("and"):
            op = self.tokens[self.at - 1]; value = ("binary", op, "and", value, self.compare())
        return value
    def compare(self):
        value = self.sum()
        while self.cur().kind in {"==", "!=", "<", "<=", ">", ">="}:
            op = self.cur(); self.at += 1; value = ("binary", op, op.kind, value, self.sum())
        return value
    def sum(self):
        value = self.product()
        while self.cur().kind in {"+", "-"}:
            op = self.cur(); self.at += 1; value = ("binary", op, op.kind, value, self.product())
        return value
    def product(self):
        value = self.unary()
        while self.cur().kind in {"*", "/", "%"}:
            op = self.cur(); self.at += 1; value = ("binary", op, op.kind, value, self.unary())
        return value
    def unary(self):
        token = self.match("-") or self.match("not"); return ("unary", token, self.unary()) if token else self.primary()
    def primary(self):
        token = self.cur()
        if self.match("number"): value = ("literal", token, int(token.text.lstrip("0") or "0"))
        elif self.match("float"): value = ("literal", token, float(token.text.rstrip("f")))
        elif self.match("string"): value = ("literal", token, token.text)
        elif self.match("true"): value = ("literal", token, True)
        elif self.match("false"): value = ("literal", token, False)
        elif self.match("("): value = self.expr(); self.take(")")
        elif self.match("["):
            items = []
            if self.cur().kind != "]":
                while True:
                    items.append(self.expr())
                    if not self.match(","): break
            self.take("]"); value = ("array", token, items)
        else: self.take("name"); value = ("name", token, token.text)
        while True:
            if self.match("."): value = ("field", token, value, self.take("name"))
            elif self.match("("):
                args = []
                if self.cur().kind != ")":
                    while True:
                        if self.cur().kind == "name" and self.tokens[self.at + 1].kind == "=":
                            name = self.take("name"); self.take("="); args.append((name, self.expr()))
                        else: args.append((None, self.expr()))
                        if not self.match(","): break
                self.take(")"); value = ("call", token, value, args)
                if value[2][0] == "field" and value[2][2][0] == "name" and value[2][3].text in {"find", "find_all"} and self.cur().kind == "{": value = self.find(value)
            elif self.match("["):
                value = ("index", token, value, self.expr()); self.take("]")
            else: return value
    def find(self, call):
        graph, args = call[2][2][1], call[3]
        method_name = call[2][3].text
        if len(args) != 2 or any(name for name, _ in args): raise MrlError(f"{method_name} expects source and target", graph.line, graph.column)
        self.take("{"); options = []
        while self.cur().kind != "}":
            key = self.cur(); self.at += 1
            if key.text == "relation":
                self.take("in"); self.take("["); members = []
                if self.cur().kind != "]":
                    while True:
                        rel = self.take("name"); self.take("."); members.append((rel, self.take("name")))
                        if not self.match(","): break
                self.take("]"); options.append((key, members))
            elif key.text in {"depth", "max_depth", "max_expansions"}:
                self.take("<=" if key.text == "depth" else ":"); options.append((key, self.unary()))
            elif key.text in {"method", "max_paths"}: self.take(":"); options.append((key, self.take("name") if key.text == "method" else self.unary()))
            elif key.text in {"cost", "heuristic"}: self.take(":"); options.append((key, self.expr()))
            else: raise MrlError(f"unsupported {method_name} option {key.text!r}", key.line, key.column)
        self.take("}"); return (method_name, graph, args[0][1], args[1][1], options)


def _v3error(token: Token, message: str): raise MrlError(message, token.line, token.column)


def _v3lower(program: _V3Program) -> dict:
    """Lower the frozen source graph slice; primitive-only output remains v2."""
    if len(program.relations) > 65_536: _v3error(program.relations[65_536]["token"], "too many relation declarations")
    if len(program.graphs) > 65_535: _v3error(program.graphs[65_535]["token"], "too many graph declarations")
    for relation in program.relations:
        if len(relation["members"]) > 256: _v3error(relation["token"], "too many relation members")
    decls = {}
    builtin_names = {"print", "argc", "argv", "read_text", "write_text", "addr", "load", "store", "Evidence", "Horn", "Facts", "Fact", "Rules", "Rule", "Triple", "closure", "closure_with_provenance"}
    for item in [*program.structs, *program.enums, *program.relations, *program.graphs, *program.functions]:
        name, token = item["name"].text, item["name"]
        if name in decls or name in builtin_names: _v3error(token, f"redeclaration of declaration {name!r}")
        decls[name] = item
    externs = {}
    for declaration in program.externs:
        name, token = declaration["name"].text, declaration["name"]
        if name in decls or name in externs: _v3error(token, f"redeclaration of declaration {name!r}")
        externs[name] = lower_extern(declaration)
        decls[name] = declaration
    structs = {item["name"].text: item for item in program.structs}; enums = {item["name"].text: item for item in program.enums}; relations = {item["name"].text: item for item in program.relations}; graphs = {item["name"].text: item for item in program.graphs}
    enum_members = {**_BUILTIN_ENUMS, **{name: tuple(member.text for member in row["members"]) for name, row in enums.items()}}
    def source_type(raw, token):
        if raw in _SCALARS: return raw
        if raw == "Horn": return "horn_plan"
        if raw == "Snapshot": return "horn_snapshot"
        if raw in {"candidate", "candidates", "constraint", "constraints", "interpretation"}: return raw
        if raw.startswith("list:"): return "list:" + source_type(raw[5:], token)
        if raw.startswith("arr:"):
            item, count = raw[4:].rsplit(":", 1)
            if not count.isdigit() or not 0 < int(count) <= 16384: _v3error(token, "invalid arr length")
            return "arr:" + source_type(item, token) + ":" + count
        if raw.startswith("map:"):
            parts = _map_parts(raw)
            if parts is None: _v3error(token, "invalid map type")
            key, value = parts
            key = source_type(key, token)
            if key not in _SCALARS - {"f32", "f64", "b"} and key != "s": _v3error(token, "map key must be an integer or string scalar")
            return "map:" + key + ":" + source_type(value, token)
        if raw.startswith("ptr:"):
            pointee = source_type(raw[4:], token)
            if pointee not in _SCALARS - {"s"} : _v3error(token, "pointer requires a numeric or boolean scalar")
            return "ptr:" + pointee
        option = _option_part(raw)
        if option is not None: return "option<" + source_type(option, token) + ">"
        if raw.startswith("result:"):
            return raw
        if raw.startswith("result<") and raw.endswith(">"):
            depth = 0
            for index, char in enumerate(raw[7:-1], 7):
                depth += char == "<"; depth -= char == ">"
                if char == "," and not depth:
                    return "result<" + source_type(raw[7:index], token) + "," + source_type(raw[index + 1:-1], token) + ">"
            _v3error(token, "unsupported generic type")
        if raw in structs: return "struct:" + raw
        if raw in enum_members: return "enum:" + raw
        _v3error(token, f"unsupported type {raw!r}")
    for enum in program.enums:
        if not enum["members"]: _v3error(enum["name"], "enum requires at least one member")
        seen = set()
        for member in enum["members"]:
            if member.text in seen: _v3error(member, f"redeclaration of enum member {member.text!r}")
            seen.add(member.text)
    for struct in program.structs:
        seen = set()
        for token, typ in struct["fields"]:
            if token.text in seen: _v3error(token, f"redeclaration of field {token.text!r}")
            seen.add(token.text)
            source_type(typ, token)
    relation_ir = []
    for relation in program.relations:
        seen = set(); members = []
        for token, metadata in relation["members"]:
            if token.text in seen: _v3error(token, f"redeclaration of relation member {token.text!r}")
            seen.add(token.text)
            if set(metadata) != {"polarity", "evidence", "traverse"}: _v3error(token, "relation member requires polarity, evidence, and traverse")
            values = {key: value.text for key, value in metadata.items()}
            if values["polarity"] not in {"positive", "negative", "neutral"} or values["evidence"] not in {"none", "optional", "required"} or values["traverse"] not in {"forward", "reverse", "both", "block"}: _v3error(token, "invalid relation metadata")
            members.append({"name": token.text, **values})
        relation_ir.append({"name": relation["name"].text, "members": members})
    graph_ir = []; v4 = False
    for graph in program.graphs:
        fields = graph["fields"]
        if set(fields) - {"node", "relation", "directed", "edge"} or "node" not in fields or "relation" not in fields: _v3error(graph["token"], "graph requires node and relation")
        node, relation = fields["node"].text, fields["relation"].text
        if node not in structs or relation not in relations: _v3error(graph["token"], "graph node and relation must name declarations")
        if "directed" in fields and fields["directed"].text not in {"true", "false"}: _v3error(fields["directed"], "graph directed must be true or false")
        edge = None if "edge" not in fields else fields["edge"].text
        if edge is not None and edge not in structs: _v3error(fields["edge"], "graph edge must name a struct declaration")
        v4 |= edge is not None
        graph_ir.append({"name": graph["name"].text, "node_type": node, "relation": relation, "directed": fields.get("directed", Token("", "true", 0, 0)).text != "false", "edge_type": edge})
    signatures = {}
    for fn in program.functions:
        params, seen = [], set()
        for token, typ in fn["params"]:
            if token.text in seen: _v3error(token, f"redeclaration of parameter {token.text!r}")
            seen.add(token.text); params.append(source_type(typ, token))
        signatures[fn["name"].text] = (params, None if fn["return"] is None else source_type(fn["return"], fn["name"]))
    def has_string(value):
        if isinstance(value, tuple): return value[0] == "literal" and type(value[2]) is str if value and value[0] == "literal" else any(has_string(item) for item in value)
        return any(has_string(item) for item in value) if isinstance(value, list) else False
    def has_horn(value):
        if isinstance(value, tuple):
            return (value[0] == "call" and value[2][0] == "name" and value[2][2] in {"Horn", "closure", "closure_with_provenance"}) or any(has_horn(item) for item in value)
        return any(has_horn(item) for item in value) if isinstance(value, list) else False
    def has_v6(value):
        if isinstance(value, tuple): return value[0] in {"array", "break", "continue"} or value[0] == "binary" and value[2] in {"/", "%", "and", "or"} or value[0] == "unary" and value[1].kind == "not" or value[0] == "call" and value[2][0] == "name" and value[2][2] in _SCALARS - {"b", "s"} or (value[0] == "let" and len(value) > 5 and value[5] is not None) or any(has_v6(item) for item in value)
        return any(has_v6(item) for item in value) if isinstance(value, list) else False
    extended = bool(program.externs or program.structs or program.enums or program.relations or program.graphs or any(any(typ not in {"si32", "b"} for _, typ in fn["params"]) or fn["return"] not in {None, "si32", "b"} or has_string(fn["body"]) or has_horn(fn["body"]) or has_v6(fn["body"]) for fn in program.functions))
    if "main" not in signatures or signatures["main"][0] or (signatures["main"][1] not in ({"si32", None} if extended else {"si32"})):
        token = program.functions[0]["token"] if program.functions else Token("", "", 1, 1); _v3error(token, "required entry point is fn main() -> si")
    def is_literal(node, typ, env, message):
        value = expression(node, env)
        if node[0] != "literal" or value["type"] != typ: _v3error(node[1], message)
        return value["value"]
    functions = []; heuristics = []; horn_v5 = False; horn_v7 = False; horn_v6 = bool(program.enums) or any(
        typ in _SCALARS - {"si32", "b", "s"} or typ in {"Horn", "Snapshot"} or typ.startswith(("arr:", "list:", "result:", "map:", "ptr:"))
        for fn in program.functions for _, typ in fn["params"]
    ) or any(fn["return"] in _SCALARS - {"si32", "b", "s"} or fn["return"] in {"Horn", "Snapshot"} or isinstance(fn["return"], str) and fn["return"].startswith(("arr:", "list:", "result:", "map:", "ptr:")) for fn in program.functions) or any(has_v6(fn["body"]) for fn in program.functions)
    for fn in program.functions:
        fname, return_type = fn["name"].text, signatures[fn["name"].text][1]
        iterating = set()
        def expression(node, env, expected_type=None):
            nonlocal extended, v4, horn_v5, horn_v6, horn_v7
            kind = node[0]
            if kind == "literal":
                value = node[2]
                if type(value) is bool: return {"kind": "literal", "type": "b", "value": value}
                if type(value) is str: extended = True; return {"kind": "literal", "type": "s", "value": value}
                if type(value) is float:
                    if not isfinite(value): _v3error(node[1], "float literal must be finite")
                    target = expected_type if expected_type in {"f32", "f64"} else "f32"
                    extended = horn_v6 = True; return {"kind": "literal", "type": target, "value": value}
                target = expected_type if expected_type in _SCALARS - {"f32", "f64", "b", "s"} else "si32"
                bounds = {"si8": (-2**7, 2**7-1), "si16": (-2**15, 2**15-1), "si32": (-2**31, 2**31-1), "si64": (-2**63, 2**63-1), "ui8": (0, 2**8-1), "ui16": (0, 2**16-1), "ui32": (0, 2**32-1), "ui64": (0, 2**64-1)}[target]
                if not bounds[0] <= value <= bounds[1]: _v3error(node[1], f"{target} literal overflow")
                if target != "si32": extended = horn_v6 = True
                return {"kind": "literal", "type": target, "value": value}
            if kind == "name":
                if node[2] == "none":
                    option = _option_part(expected_type)
                    if option is None: _v3error(node[1], "none requires an optional annotation")
                    extended = horn_v6 = True; return {"kind": "option", "type": expected_type, "some": False, "value": None}
                if node[2] not in env: _v3error(node[1], f"undefined name {node[2]!r}")
                return {"kind": "name", "type": env[node[2]][0], "name": node[2]}
            if kind == "unary":
                signed_min = {"si8": 2**7, "si16": 2**15, "si32": 2**31, "si64": 2**63}
                if node[1].kind == "-" and node[2][0] == "literal" and type(node[2][2]) is int:
                    target = expected_type if expected_type in signed_min else "si32"
                    if node[2][2] == signed_min[target]:
                        if target != "si32": extended = horn_v6 = True
                        return {"kind": "literal", "type": target, "value": -signed_min[target]}
                value = expression(node[2], env, expected_type)
                if node[1].kind == "not":
                    if value["type"] != "b": _v3error(node[1], "not requires b")
                    return {"kind": "unary", "type": "b", "op": "not", "value": value}
                if value["type"] not in {"si8", "si16", "si32", "si64", "f32", "f64"}: _v3error(node[1], "unary '-' requires signed numeric value")
                return {"kind": "unary", "type": value["type"], "op": "-", "value": value}
            if kind == "binary":
                left, op = expression(node[3], env), node[2]
                right = expression(node[4], env, None if op in {"and", "or"} else left["type"])
                if left["type"] is None or right["type"] is None: _v3error(node[1], "void call cannot be used as a value")
                if op in {"and", "or"}:
                    if left["type"] != "b" or right["type"] != "b": _v3error(node[1], f"{op!r} requires b operands")
                    typ = "b"
                elif op in {"+", "-", "*", "/", "%"}:
                    if left["type"] == right["type"] == "s" and op == "+":
                        typ = "s"
                        extended = horn_v6 = True
                        return {"kind": "binary", "type": typ, "op": op, "left": left, "right": right}
                    if left["type"] != right["type"] or left["type"] not in _SCALARS - {"b", "s"}: _v3error(node[1], f"{op!r} requires matching numeric operands")
                    if op == "%" and left["type"] not in {"si8", "si16", "si32", "si64", "ui8", "ui16", "ui32", "ui64"}: _v3error(node[1], "'%' requires integer operands")
                    typ = left["type"]
                else:
                    if left["type"] != right["type"] or (left["type"] not in _SCALARS and not (op in {"==", "!="} and left["type"].startswith("enum:"))): _v3error(node[1], "comparison requires matching scalar operands")
                    if op not in {"==", "!="} and left["type"] not in _SCALARS - {"b", "s"}: _v3error(node[1], f"{op!r} requires numeric operands")
                    typ = "b"
                return {"kind": "binary", "type": typ, "op": op, "left": left, "right": right}
            if kind == "array":
                item_type = _item_type(expected_type) if isinstance(expected_type, str) else None
                items = [expression(item, env, item_type) for item in node[2]]
                if not item_type:
                    item_type = items[0]["type"] if items else None
                if item_type is None or not items or any(item["type"] != item_type for item in items): _v3error(node[1], "array items must be nonempty and matching")
                typ = expected_type if isinstance(expected_type, str) and expected_type.startswith(("arr:", "list:")) else "list:" + item_type
                if typ.startswith("arr:") and len(items) != int(typ.rsplit(":", 1)[1]): _v3error(node[1], "array literal length does not match arr type")
                extended = horn_v6 = True; return {"kind": "array", "type": typ, "items": items}
            if kind == "field":
                base, field = node[2], node[3]
                if base[0] == "name" and base[2] in enum_members:
                    if field.text not in enum_members[base[2]]: _v3error(field, "unknown enum member")
                    extended = horn_v6 = True; return {"kind": "enum", "type": "enum:" + base[2], "member": field.text}
                if base[0] == "name" and base[2] in relations:
                    rel = relations[base[2]]
                    if field.text not in {name.text for name, _ in rel["members"]}: _v3error(field, "unknown relation member")
                    extended = True; return {"kind": "relation", "type": "relation:" + base[2], "member": field.text}
                value = expression(base, env)
                if not isinstance(value["type"], str): _v3error(field, "unsupported field access")
                if field.text == "len" and (value["type"] == "s" or value["type"].startswith(("path:", "paths:", "arr:", "list:", "map:"))):
                    extended = True; return {"kind": "len", "type": "si32", "value": value}
                if value["type"].startswith("path:") and field.text == "cost":
                    extended = v4 = True; return {"kind": "field", "type": "si32", "value": value, "name": "cost"}
                if value["type"].startswith("paths:") and field.text in {"complete", "reason"}:
                    extended = v4 = True; return {"kind": "field", "type": "b" if field.text == "complete" else "s", "value": value, "name": field.text}
                if value["type"] == "horn_result" and field.text in {"fact_count", "proof_count", "searches", "complete", "reason"}:
                    extended = v4 = True; return {"kind": "field", "type": "b" if field.text == "complete" else "s" if field.text == "reason" else "si32", "value": value, "name": field.text}
                if value["type"] == "horn_plan" and field.text == "version":
                    extended = v4 = horn_v5 = True; return {"kind": "horn_version", "type": "si32", "plan": value}
                if value["type"] == "horn_snapshot" and field.text in {"fact_count", "proof_count", "searches", "complete", "reason", "version", "added_count", "removed_count"}:
                    extended = v4 = horn_v5 = True; return {"kind": "field", "type": "b" if field.text == "complete" else "s" if field.text == "reason" else "si32", "value": value, "name": field.text}
                if value["type"] == "interpretation" and field.text in {"status", "candidate_id", "reason", "complete"}:
                    extended = horn_v6 = horn_v7 = True
                    return {"kind": "field", "type": {"status": "enum:InterpretationStatus", "candidate_id": "option<s>", "reason": "s", "complete": "b"}[field.text], "value": value, "name": field.text}
                if value["type"].startswith("struct:"):
                    struct = structs[value["type"].split(":", 1)[1]]; found = next(((name, typ) for name, typ in struct["fields"] if name.text == field.text), None)
                    if found is None: _v3error(field, "unknown struct field")
                    extended = True; return {"kind": "field", "type": source_type(found[1], found[0]), "value": value, "name": field.text}
                _v3error(field, "unsupported field access")
            if kind == "index":
                value, index = expression(node[2], env), expression(node[3], env)
                if isinstance(value["type"], str) and value["type"].startswith(("arr:", "list:")) and index["type"] == "si32":
                    extended = horn_v6 = True; return {"kind": "index", "type": _item_type(value["type"]), "value": value, "index": index}
                if not isinstance(value["type"], str) or not value["type"].startswith("paths:") or index["type"] != "si32": _v3error(node[1], "index requires Paths and si32 index")
                extended = v4 = True; return {"kind": "index", "type": "path:" + value["type"].split(":", 1)[1], "value": value, "index": index}
            if kind in {"find", "find_all"}:
                graph_name = node[1].text
                if graph_name not in graphs: _v3error(node[1], "unknown graph")
                graph = graphs[graph_name]; source, target = expression(node[2], env), expression(node[3], env)
                if source["type"] != "node:" + graph_name or target["type"] != "node:" + graph_name: _v3error(node[1], "find handles must belong to this graph")
                options, seen = {}, set()
                for key, value in node[4]:
                    name = "max_depth" if key.text == "depth" else key.text
                    if name in seen: _v3error(key, f"duplicate find option {name!r}")
                    seen.add(name); options[name] = value
                members = [name.text for name, _ in relations[graph["fields"]["relation"].text]["members"]]
                if "relation" in options:
                    members = []
                    for relation, member in options["relation"]:
                        if relation.text != graph["fields"]["relation"].text: _v3error(relation, "find relation belongs to another relation declaration")
                        if member.text not in {name.text for name, _ in relations[relation.text]["members"]}: _v3error(member, "unknown relation member")
                        members.append(member.text)
                def bound(name, default):
                    if name not in options: return default
                    value = is_literal(options[name], "si32", env, f"{name} must be an int32 literal")
                    if value < 0: _v3error(options[name][1], f"{name} must be nonnegative")
                    return value
                method = options.get("method", Token("name", "bfs", node[1].line, node[1].column))
                if not isinstance(method, Token) or method.text not in {"auto", "bfs", "dfs", "dijkstra", "astar"}: _v3error(method if isinstance(method, Token) else node[1], "unsupported search method")
                if kind != "find_all" and "max_paths" in options: _v3error(options["max_paths"][1], "max_paths is only valid for find_all")
                weighted = method.text in {"dijkstra", "astar"}
                edge_type = graph["fields"].get("edge")
                cost = options.get("cost")
                if weighted and cost is None: _v3error(method, "weighted search requires cost")
                if not weighted and cost is not None: _v3error(options["cost"][1], "cost is only valid for weighted search")
                cost_name = None
                if cost is not None:
                    if edge_type is None: _v3error(cost[1], "cost requires a typed edge")
                    if cost[0] != "field" or cost[2][0] != "name" or cost[2][2] != "edge": _v3error(cost[1], "cost must be edge.<si32 field>")
                    field = cost[3]; edge_fields = {name.text: typ for name, typ in structs[edge_type.text]["fields"]}
                    if field.text not in edge_fields or edge_fields[field.text] != "si32": _v3error(field, "cost must name an si32 edge field")
                    cost_name = field.text
                heuristic = options.get("heuristic")
                if method.text == "astar" and heuristic is None: _v3error(method, "astar requires heuristic")
                if method.text != "astar" and heuristic is not None: _v3error(heuristic[1], "heuristic is only valid for astar")
                heuristic_name = None
                if heuristic is not None:
                    if heuristic[0] != "call" or heuristic[2][0] != "name" or any(field is not None for field, _ in heuristic[3]) or [arg[1][2] if arg[1][0] == "name" else None for arg in heuristic[3]] != ["node", "goal"]: _v3error(heuristic[1], "heuristic must be estimate(node, goal)")
                    heuristic_name = heuristic[2][2]
                    expected = ["struct:" + graph["fields"]["node"].text] * 2
                    if heuristic_name not in signatures or signatures[heuristic_name] != (expected, "si32"): _v3error(heuristic[1], "heuristic must accept two node payloads and return si32")
                    heuristics.append((heuristic_name, heuristic[1]))
                max_paths = bound("max_paths", 256) if kind == "find_all" else None
                if kind == "find_all" and max_paths > 256: _v3error(options["max_paths"][1], "max_paths must be at most 256")
                if kind == "find_all" or method.text not in {"auto", "bfs"} or cost is not None or heuristic is not None: v4 = True
                extended = True
                result = {"kind": "graph_find_all" if kind == "find_all" else "graph_find", "type": ("result:paths:" if kind == "find_all" else "result:path:") + graph_name, "graph": graph_name, "source": source, "target": target, "relations": members, "max_depth": bound("max_depth", 64), "max_expansions": bound("max_expansions", 100000), "method": "bfs" if method.text == "auto" else method.text, "cost": cost_name, "heuristic": heuristic_name}
                if kind == "find_all": result["max_paths"] = max_paths
                return result
            if kind == "call":
                callee, args = node[2], node[3]
                io_call = lower_io_call(node, expression, env, _v3error)
                if io_call is not None:
                    extended = horn_v6 = True
                    return io_call
                ffi_call = lower_ffi_call(node, expression, env, _v3error, externs=externs)
                if ffi_call is not None:
                    extended = horn_v6 = True
                    return ffi_call
                from .language_domain import lower_dynamic_call
                dynamic = lower_dynamic_call(node, expression, env, _v3error)
                if dynamic is not None:
                    extended = v4 = horn_v5 = horn_v6 = horn_v7 = True
                    return dynamic
                if callee[0] == "name":
                    name = callee[2]
                    if name in _SCALARS - {"b", "s"}:
                        if len(args) != 1 or args[0][0] is not None: _v3error(node[1], f"{name} cast expects one value")
                        value = expression(args[0][1], env)
                        if value["type"] not in _SCALARS - {"b", "s"}: _v3error(node[1], f"{name} cast requires a numeric value")
                        extended = horn_v6 = True; return {"kind": "cast", "type": name, "value": value}
                    if name in {"sum", "norm", "dot", "cosine"}:
                        wanted = 1 if name in {"sum", "norm"} else 2
                        if len(args) != wanted or any(field is not None for field, _ in args): _v3error(node[1], f"{name} has invalid arguments")
                        out = [expression(value, env) for _, value in args]
                        if any(value["type"] != "list:f32" for value in out): _v3error(node[1], f"{name} requires list<f32>")
                        extended = horn_v6 = True; return {"kind": "kernel", "type": "f32", "op": name, "args": out}
                    if name in {"Ok", "Err"}:
                        if not isinstance(expected_type, str) or not expected_type.startswith(("result:", "result<")) or len(args) != 1 or args[0][0] is not None: _v3error(node[1], f"{name} requires a Result annotation")
                        if expected_type.startswith("result<"):
                            depth = 0
                            for index, char in enumerate(expected_type[7:-1], 7):
                                depth += char == "<"; depth -= char == ">"
                                if char == "," and not depth:
                                    ok_type, err_type = expected_type[7:index], expected_type[index + 1:-1]
                                    break
                            else: _v3error(node[1], "invalid Result annotation")
                        else: ok_type, err_type = expected_type.split(":")[1:]
                        wanted = ok_type if name == "Ok" else err_type
                        value = expression(args[0][1], env, wanted)
                        if value["type"] != wanted: _v3error(node[1], f"{name} payload must be {wanted}")
                        extended = horn_v6 = True; return {"kind": "result", "type": expected_type, "ok": name == "Ok", "value": value}
                    if name == "Some":
                        option = _option_part(expected_type)
                        if option is None or len(args) != 1 or args[0][0] is not None: _v3error(node[1], "Some requires an optional annotation")
                        value = expression(args[0][1], env, option)
                        if value["type"] != option: _v3error(node[1], f"Some payload must be {option}")
                        extended = horn_v6 = True; return {"kind": "option", "type": expected_type, "some": True, "value": value}
                    if name == "Map":
                        if args or _map_parts(expected_type) is None: _v3error(node[1], "Map requires a map annotation")
                        extended = horn_v6 = True; return {"kind": "map", "type": expected_type}
                    if name == "Horn":
                        if any(field is not None and field.text == "memory_budget" for field, _ in args):
                            from .horn_bridge import lower_plan_constructor_v7
                            extended = v4 = horn_v5 = horn_v6 = horn_v7 = True
                            return {"kind": "horn_plan", "type": "horn_plan", "plan": lower_plan_constructor_v7(node, _v3error)}
                        if any(field is not None and field.text == "capacity" for field, _ in args) or horn_v6:
                            from .horn_bridge import lower_plan_constructor_v6
                            extended = v4 = horn_v5 = horn_v6 = True
                            return {"kind": "horn_plan", "type": "horn_plan", "plan": lower_plan_constructor_v6(node, _v3error)}
                        from .horn_bridge import lower_plan_constructor
                        extended = v4 = horn_v5 = True
                        return {"kind": "horn_plan", "type": "horn_plan", "plan": lower_plan_constructor(node, _v3error)}
                    if name in {"closure", "closure_with_provenance"} and args and args[0][0] is None and args[0][1][0] == "name" and args[0][1][2] in env and env[args[0][1][2]][0] == "horn_plan":
                        options = {}
                        for field, value in args[1:]:
                            if field is None or field.text in options: _v3error(field or node[1], "invalid Horn query options")
                            options[field.text] = value
                        allowed = {"limit", "target"} if name == "closure" else {"limit", "proof_limit", "search_limit"}
                        if set(options) - allowed: _v3error(node[1], "invalid Horn query options")
                        def bound(option, default):
                            if option not in options: return default
                            value = is_literal(options[option], "si32", env, f"{option} must be a positive int32 literal")
                            if not 1 <= value <= 2 ** 31 - 1: _v3error(options[option][1], f"{option} must be a positive int32 literal")
                            return value
                        target = None
                        if "target" in options:
                            from .horn_bridge import _triple
                            target = _triple(options["target"], _v3error)
                        extended = v4 = horn_v5 = True
                        return {"kind": "horn_evaluate", "type": "horn_snapshot", "plan": expression(args[0][1], env), "operation": name, "limit": bound("limit", 2048), "proof_limit": bound("proof_limit", 32), "search_limit": bound("search_limit", bound("limit", 2048) * 8), "target": target}
                    if name in {"Horn", "Facts", "Fact", "Rules", "Rule", "Triple", "closure", "closure_with_provenance"}:
                        from .horn_bridge import lower_source_call
                        value = lower_source_call(node, _v3error)
                        if value is not None:
                            extended = v4 = True; return value
                    if name == "print":
                        if len(args) != 1 or args[0][0] is not None: _v3error(node[1], "print expects one value")
                        value = expression(args[0][1], env)
                        if value["type"] not in _SCALARS | {"search_error", "horn_result", "horn_snapshot"}: _v3error(node[1], "print accepts scalar, search error, or horn result")
                        extended = True; return {"kind": "print", "type": None, "value": value}
                    if name == "Evidence":
                        fields = {field.text: value for field, value in args if field is not None}
                        if len(args) != 4 or set(fields) != {"source", "start", "end", "text"}: _v3error(node[1], "Evidence requires literal source, start, end, text")
                        values = {field: is_literal(value, "s" if field in {"source", "text"} else "si32", env, "Evidence fields must be literals") for field, value in fields.items()}
                        if values["start"] < 0 or values["end"] < values["start"] or values["end"] > len(values["source"]) or values["source"][values["start"]:values["end"]] != values["text"]: _v3error(node[1], "invalid Evidence source span")
                        extended = True; return {"kind": "evidence", "type": "evidence", **values}
                    if name in structs:
                        struct = structs[name]; fields = {field.text: value for field, value in args if field is not None}
                        wanted = {field.text for field, _ in struct["fields"]}
                        if len(args) != len(fields) or set(fields) != wanted: _v3error(node[1], f"{name} requires each field exactly once")
                        out = []
                        declared = {field.text: (field, typ) for field, typ in struct["fields"]}
                        for field, value_node in args:
                            declared_field, typ = declared[field.text]; expected = source_type(typ, declared_field); value = expression(value_node, env, expected)
                            if value["type"] != expected: _v3error(field, f"field {field.text!r} must be {expected}")
                            out.append({"name": field.text, "value": value})
                        extended = True; return {"kind": "construct", "type": "struct:" + name, "fields": out}
                    if name not in signatures: _v3error(callee[1], f"undefined function {name!r}")
                    if any(field is not None for field, _ in args): _v3error(node[1], "function calls use positional arguments")
                    expected, result = signatures[name]
                    if len(args) != len(expected): _v3error(node[1], f"function {name!r} expects {len(expected)} arguments")
                    out = [expression(value, env) for _, value in args]
                    for (_, arg), value, typ in zip(args, out, expected):
                        if value["type"] != typ: _v3error(arg[1], f"argument to {name!r} must be {typ}")
                    return {"kind": "call", "type": result, "name": name, "args": out}
                if callee[0] == "field" and callee[2][0] == "name" and callee[2][2] in graphs:
                    graph_name, method = callee[2][2], callee[3].text
                    if any(field is not None for field, _ in args): _v3error(node[1], "graph methods use positional arguments")
                    if method == "add" and len(args) == 1:
                        value = expression(args[0][1], env)
                        if value["type"] != "struct:" + graphs[graph_name]["fields"]["node"].text: _v3error(node[1], "graph node payload has wrong struct type")
                        extended = True; return {"kind": "graph_add_node", "type": "node:" + graph_name, "graph": graph_name, "value": value}
                    if method == "add" and len(args) in {3, 4, 5}:
                        source, target, relation = [expression(arg[1], env) for arg in args[:3]]
                        relation_name = graphs[graph_name]["fields"]["relation"].text
                        if source["type"] != "node:" + graph_name or target["type"] != "node:" + graph_name or relation["type"] != "relation:" + relation_name: _v3error(node[1], "graph edge arguments belong to another graph or relation")
                        if relation["kind"] != "relation": _v3error(args[2][1][1], "graph edge relation must be a Relation.Member literal")
                        edge_name = graphs[graph_name]["fields"].get("edge")
                        if edge_name is not None and len(args) < 4: _v3error(node[1], "typed graph edge requires payload")
                        if edge_name is None and len(args) == 5: _v3error(node[1], "untyped graph edge accepts at most Evidence as fourth argument")
                        payload = None
                        evidence = None
                        if edge_name is not None and len(args) >= 4:
                            payload = expression(args[3][1], env)
                            if payload["type"] != "struct:" + edge_name.text: _v3error(args[3][1][1], "graph edge payload has wrong struct type")
                        if len(args) == (5 if edge_name is not None else 4): evidence = expression(args[-1][1], env)
                        meta = next(meta for member, meta in relations[relation_name]["members"] if member.text == relation["member"])
                        if meta["evidence"].text == "required" and evidence is None: _v3error(node[1], "relation requires Evidence")
                        if meta["evidence"].text == "none" and evidence is not None: _v3error(node[1], "relation forbids Evidence")
                        if evidence is not None and evidence["type"] != "evidence": _v3error(args[-1][1][1], "edge evidence must be Evidence")
                        extended = True; return {"kind": "graph_add_edge", "type": None, "graph": graph_name, "source": source, "target": target, "relation": relation, "payload": payload, "evidence": evidence}
                    if method == "remove" and len(args) == 1:
                        value = expression(args[0][1], env)
                        if value["type"] != "node:" + graph_name: _v3error(node[1], "graph.remove handle belongs to another graph")
                        extended = True; return {"kind": "graph_remove", "type": None, "graph": graph_name, "value": value}
                if callee[0] == "field" and callee[2][0] == "name" and callee[2][2] in env and env[callee[2][2]][0] == "horn_plan":
                    plan_name, method = callee[2][2], callee[3].text
                    if method == "load":
                        if len(args) != 1 or args[0][0] is not None or not env[plan_name][1]: _v3error(node[1], "Horn plan load expects one path and mutable name")
                        path = expression(args[0][1], env)
                        if path["type"] != "s": _v3error(node[1], "Horn plan load path must be s")
                        extended = horn_v6 = True; return {"kind": "horn_load", "type": "result:si32:s", "plan": expression(callee[2], env), "path": path}
                    if method in {"save", "restore", "commit"}:
                        if len(args) != 1 or args[0][0] is not None or (method in {"restore", "commit"} and not env[plan_name][1]): _v3error(node[1], f"Horn plan {method} expects one path")
                        path = expression(args[0][1], env)
                        if path["type"] != "s": _v3error(node[1], "Horn plan path must be s")
                        horn_v7 = horn_v6 = True; return {"kind": "horn_" + method, "type": "result:si32:s", "plan": expression(callee[2], env), "path": path}
                    if method in {"exists", "count", "select", "explain"}:
                        if method in {"count", "select"} and all(field is not None for field, _ in args):
                            fields = {field.text: value for field, value in args}
                            if len(fields) != len(args) or set(fields) - {"subject", "predicate", "object"}:
                                _v3error(node[1], f"Horn plan {method} filters are subject, predicate, object")
                            triple = []
                            for name in ("subject", "predicate", "object"):
                                if name not in fields:
                                    triple.append(None)
                                    continue
                                value = expression(fields[name], env)
                                if value["type"] != "s" or value["kind"] != "literal": _v3error(node[1], "Horn filters must be string literals")
                                triple.append(value["value"])
                        else:
                            if len(args) != 1 or args[0][0] is not None: _v3error(node[1], f"Horn plan {method} expects Triple(...)")
                            from .horn_bridge import _triple
                            triple = _triple(args[0][1], _v3error)
                        horn_v7 = horn_v6 = True; return {"kind": "horn_" + method, "type": "b" if method == "exists" else "si32" if method == "count" else "horn_snapshot", "plan": expression(callee[2], env), "triple": triple}
                    if method == "changes":
                        if args: _v3error(node[1], "Horn plan changes expects no arguments")
                        horn_v7 = horn_v6 = True; return {"kind": "horn_changes", "type": "horn_snapshot", "plan": expression(callee[2], env)}
                    if method not in {"add", "remove", "correct"}: _v3error(callee[3], "unsupported Horn plan method")
                    if not env[plan_name][1]: _v3error(callee[2][1], "Horn plan mutation requires a mutable name")
                    plan = expression(callee[2], env)
                    if method == "remove":
                        if len(args) != 1 or args[0][0] is not None: _v3error(node[1], "Horn plan remove expects one id")
                        identifier = expression(args[0][1], env)
                        if identifier["type"] != "s": _v3error(args[0][1][1], "Horn plan id must be s")
                        extended = v4 = horn_v5 = True
                        return {"kind": "horn_remove", "type": "b", "plan": plan, "id": identifier}
                    if len(args) != 1 or args[0][0] is not None or args[0][1][0] != "call" or args[0][1][2][0] != "name" or args[0][1][2][2] != "Fact": _v3error(node[1], "Horn plan add expects Fact(...)")
                    raw_fields, seen = args[0][1][3], set()
                    fields = []
                    expected = {"id": "s", "subject": "s", "predicate": "s", "object": "s", "polarity": "b", "modality": "s", "evidence": "evidence"}
                    for field, value_node in raw_fields:
                        if field is None or field.text in seen or field.text not in expected: _v3error(field or args[0][1][1], "invalid dynamic Fact fields")
                        seen.add(field.text)
                        if field.text == "evidence" and not (value_node[0] == "call" and value_node[2][0] == "name" and value_node[2][2] == "Evidence"):
                            _v3error(value_node[1], "dynamic Fact evidence must be literal Evidence")
                        value = expression(value_node, env)
                        if value["type"] != expected[field.text]: _v3error(value_node[1], f"Fact field {field.text!r} must be {expected[field.text]}")
                        fields.append({"name": field.text, "value": value})
                    if not {"id", "subject", "predicate", "object"} <= seen: _v3error(args[0][1][1], "Fact requires id, subject, predicate, object")
                    extended = v4 = horn_v5 = True
                    if method == "correct": horn_v6 = horn_v7 = True
                    return {"kind": "horn_" + method, "type": "b", "plan": plan, "fact": fields}
                if callee[0] == "field" and callee[2][0] == "name" and callee[2][2] in env and env[callee[2][2]][0].startswith("list:"):
                    name, method, typ = callee[2][2], callee[3].text, env[callee[2][2]][0]
                    if name in iterating: _v3error(callee[2][1], "cannot mutate a list while iterating it")
                    if method not in {"push", "add"} or len(args) != 1 or args[0][0] is not None or not env[name][1]: _v3error(node[1], "list push requires one value and mutable name")
                    value = expression(args[0][1], env, _item_type(typ))
                    if value["type"] != _item_type(typ): _v3error(node[1], "list push value has wrong type")
                    extended = horn_v6 = True; return {"kind": "list_push", "type": None, "list": expression(callee[2], env), "value": value}
                if callee[0] == "field" and callee[2][0] == "name" and callee[2][2] in env and _map_parts(env[callee[2][2]][0]):
                    base, method, typ = callee[2][2], callee[3].text, env[callee[2][2]][0]
                    key_type, value_type = _map_parts(typ)
                    if base in iterating and method in {"set", "remove"}: _v3error(callee[2][1], "cannot mutate a map while iterating it")
                    if method == "set" and len(args) == 2 and all(field is None for field, _ in args) and env[base][1]:
                        key, value = expression(args[0][1], env, key_type), expression(args[1][1], env, value_type)
                        if key["type"] != key_type or value["type"] != value_type: _v3error(node[1], "map set types")
                        extended = horn_v6 = True; return {"kind":"map_set","type":None,"map":expression(callee[2],env),"key":key,"value":value}
                    if method == "remove" and len(args) == 1 and args[0][0] is None and env[base][1]:
                        key=expression(args[0][1],env, key_type)
                        if key["type"] != key_type: _v3error(node[1], "map remove key")
                        extended=horn_v6=True; return {"kind":"map_remove","type":"b","map":expression(callee[2],env),"key":key}
                    if method == "get" and len(args) == 1 and args[0][0] is None:
                        key=expression(args[0][1],env, key_type)
                        if key["type"] != key_type: _v3error(node[1], "map get key")
                        result = "result:" + value_type + ":s" if value_type in {"si32", "f32", "s", "b"} else "result<" + value_type + ",s>"
                        extended=horn_v6=True; return {"kind":"map_get","type":result,"map":expression(callee[2],env),"key":key}
                _v3error(node[1], "unsupported call")
            raise AssertionError(kind)
        def block(statements, env, loop_depth=0):
            out, returned = [], False
            for statement in statements:
                kind, token = statement[0], statement[1]
                if returned: _v3error(token, "unreachable statement")
                if kind == "let":
                    name, mutable, value_node = statement[2].text, statement[3], statement[4]
                    if name in env: _v3error(statement[2], f"redeclaration of name {name!r}")
                    wanted = source_type(statement[5], statement[2]) if len(statement) > 5 and statement[5] is not None else None
                    value = expression(value_node, env, wanted)
                    if value["type"] is None: _v3error(token, "void call cannot initialize a name")
                    if wanted is not None:
                        if value["type"] != wanted: _v3error(statement[2], f"initializer for {name!r} must be {wanted}")
                    env[name] = (value["type"], mutable); out.append({"kind": "let", "name": name, "type": value["type"], "mutable": mutable, "value": value})
                elif kind == "unsafe":
                    unsafe_env = dict(env)
                    unsafe_env["$unsafe"] = True
                    nested, nested_returned = block(statement[2], unsafe_env, loop_depth)
                    out.append({"kind": "unsafe", "body": nested})
                    returned = nested_returned
                elif kind == "assign":
                    name, value_node = statement[2].text, statement[4]
                    if name not in env: _v3error(statement[2], f"undefined name {name!r}")
                    if not env[name][1]: _v3error(statement[2], f"cannot reassign constant {name!r}")
                    value = expression(value_node, env, env[name][0])
                    if value["type"] != env[name][0]: _v3error(statement[2], f"assignment to {name!r} must be {env[name][0]}")
                    out.append({"kind": "assign", "name": name, "value": value})
                elif kind == "array_assign":
                    name=statement[2].text
                    if name not in env or not env[name][1] or not env[name][0].startswith("arr:"): _v3error(statement[2], "array write requires mutable arr")
                    if name in iterating: _v3error(statement[2], "cannot mutate an arr while iterating it")
                    index,value=expression(statement[3],env),expression(statement[4],env)
                    if index["type"]!="si32" or value["type"]!=_item_type(env[name][0]): _v3error(token,"array write types")
                    extended=horn_v6=True; out.append({"kind":"array_assign","name":name,"index":index,"value":value})
                elif kind == "field_assign":
                    name, field = statement[2].text, statement[3]
                    if name not in env or not env[name][1] or not env[name][0].startswith("struct:"): _v3error(statement[2], "field write requires mutable struct name")
                    struct = structs[env[name][0][7:]]; found = next(((token, typ) for token, typ in struct["fields"] if token.text == field.text), None)
                    if found is None: _v3error(field, "unknown struct field")
                    wanted = source_type(found[1], found[0]); value = expression(statement[4], env, wanted)
                    if value["type"] != wanted: _v3error(field, f"field {field.text!r} must be {wanted}")
                    extended = horn_v6 = True; out.append({"kind": "field_assign", "name": name, "field": field.text, "value": value})
                elif kind == "return":
                    value = None if statement[2] is None else expression(statement[2], env, return_type)
                    if return_type is None:
                        if value is not None: _v3error(token, "void function cannot return a value")
                    elif value is None or value["type"] != return_type: _v3error(token, f"function {fname!r} must return {return_type}")
                    out.append({"kind": "return", "value": value}); returned = True
                elif kind == "expr": out.append({"kind": "expr", "value": expression(statement[2], env)})
                elif kind == "if":
                    condition = expression(statement[2], env)
                    if condition["type"] != "b": _v3error(statement[2][1], "if condition must be b")
                    yes, a = block(statement[3], env.copy(), loop_depth); no, b = ([], False) if statement[4] is None else block(statement[4], env.copy(), loop_depth)
                    out.append({"kind": "if", "condition": condition, "then": yes, "else": no}); returned = statement[4] is not None and a and b
                elif kind == "while":
                    condition = expression(statement[2], env)
                    if condition["type"] != "b": _v3error(statement[2][1], "while condition must be b")
                    nested, _ = block(statement[3], env.copy(), loop_depth + 1); out.append({"kind": "while", "condition": condition, "body": nested})
                elif kind == "for":
                    name, start, stop = statement[2].text, expression(statement[3], env), expression(statement[4], env)
                    if name in env: _v3error(statement[2], f"redeclaration of name {name!r}")
                    if start["type"] != "si32" or stop["type"] != "si32": _v3error(token, "for range bounds must be si32")
                    nested, _ = block(statement[5], {**env, name: ("si32", False)}, loop_depth + 1); out.append({"kind": "for", "name": name, "start": start, "stop": stop, "body": nested})
                elif kind == "for_each":
                    name, source = statement[2].text, expression(statement[3], env)
                    if name in env: _v3error(statement[2], f"redeclaration of name {name!r}")
                    if not isinstance(source["type"], str) or not source["type"].startswith(("list:", "arr:", "map:")): _v3error(token, "for iteration requires list, arr, or map")
                    map_type = _map_parts(source["type"])
                    item = map_type[0] if map_type else _item_type(source["type"])
                    source_name = statement[3][2] if statement[3][0] == "name" else None
                    if source_name: iterating.add(source_name)
                    nested, _ = block(statement[4], {**env, name: (item, False)}, loop_depth + 1)
                    if source_name: iterating.remove(source_name)
                    extended = horn_v6 = True; out.append({"kind": "for_each", "name": name, "source": source, "item_type": item, "body": nested})
                elif kind in {"break", "continue"}:
                    if not loop_depth: _v3error(token, f"{kind} requires a loop")
                    out.append({"kind": kind})
                elif kind == "match":
                    value = expression(statement[2], env)
                    arms = statement[3]
                    if not isinstance(value["type"], str): _v3error(token, "match requires a Result, optional, or enum")
                    if _option_part(value["type"]) is not None:
                        if set(arms) != {"Some", "none"}: _v3error(token, "optional match requires exactly Some and none arms")
                        some_name, some_body = arms["Some"]; none_name, none_body = arms["none"]
                        if some_name is None or none_name is not None or some_name.text in env: _v3error(token, "Some requires one binder and none requires no binder")
                        some, a = block(some_body, {**env, some_name.text: (_option_part(value["type"]), False)}, loop_depth); absent, b = block(none_body, env.copy(), loop_depth)
                        out.append({"kind": "match_option", "value": value, "some_name": some_name.text, "some": some, "none": absent}); returned = a and b
                        continue
                    if value["type"].startswith("enum:"):
                        enum_name = value["type"][5:]
                        members = set(enum_members[enum_name])
                        normalized, fallback = {}, None
                        for arm_name, arm in arms.items():
                            if arm_name == "_":
                                if fallback is not None: _v3error(token, "duplicate enum fallback arm")
                                fallback = arm
                                continue
                            member = arm_name
                            if "." in arm_name:
                                qualified, member = arm_name.split(".", 1)
                                if qualified != enum_name: _v3error(token, "qualified enum arm names another enum")
                            if member not in members or member in normalized: _v3error(token, "enum match requires valid members exactly once")
                            normalized[member] = arm
                        if fallback is None and set(normalized) != members: _v3error(token, "enum match requires every member exactly once")
                        if fallback is not None:
                            if fallback[0] is not None: _v3error(fallback[0], "enum fallback arm does not bind a payload")
                            for member in members - set(normalized): normalized[member] = fallback
                        rows, all_returned = [], True
                        for member in enum_members[enum_name]:
                            binder, body = normalized[member]
                            if binder is not None: _v3error(binder, "enum match arms do not bind a payload")
                            nested, branch_returned = block(body, env.copy(), loop_depth); rows.append({"member": member, "body": nested}); all_returned &= branch_returned
                        out.append({"kind": "match_enum", "value": value, "arms": rows}); returned = all_returned
                        continue
                    if not value["type"].startswith(("result:path:", "result:paths:", "result:", "result<")): _v3error(token, "match requires a Result, optional, or enum")
                    result_kind, graph_name = (value["type"].split(":")[1:3] if value["type"].startswith(("result:path:", "result:paths:")) else (None, None)); ok_name, ok_body = arms.get("Ok", (None, None)); err_name, err_body = arms.get("Err", (None, None))
                    if set(arms) != {"Ok", "Err"} or ok_name is None or err_name is None: _v3error(token, "match requires exactly Ok and Err arms with binders")
                    if ok_name.text == err_name.text or ok_name.text in env or err_name.text in env: _v3error(token, "match binders must be distinct and cannot shadow visible names")
                    if value["type"].startswith("result:") and not value["type"].startswith(("result:path:", "result:paths:")):
                        ok_type, err_type = value["type"].split(":")[1:]
                    elif value["type"].startswith("result<"):
                        depth = 0
                        for index, char in enumerate(value["type"][7:-1], 7):
                            depth += char == "<"; depth -= char == ">"
                            if char == "," and not depth:
                                ok_type, err_type = value["type"][7:index], value["type"][index + 1:-1]
                                break
                        else: _v3error(token, "invalid Result type")
                    else:
                        ok_type = err_type = None
                    if ok_type is not None:
                        yes, a = block(ok_body, {**env, ok_name.text: (ok_type, False)}, loop_depth); no, b = block(err_body, {**env, err_name.text: (err_type, False)}, loop_depth)
                    else:
                        yes, a = block(ok_body, {**env, ok_name.text: (("paths:" if result_kind == "paths" else "path:") + graph_name, False)}, loop_depth); no, b = block(err_body, {**env, err_name.text: ("search_error", False)}, loop_depth)
                    out.append({"kind": "match", "value": value, "ok_name": ok_name.text, "ok": yes, "err_name": err_name.text, "err": no}); returned = a and b
                else: raise AssertionError(kind)
            return out, returned
        env = {token.text: (typ, True) for (token, _), typ in zip(fn["params"], signatures[fname][0])}
        env["$externs"] = externs
        body, returns = block(fn["body"], env)
        if return_type is not None and not returns: _v3error(fn["token"], f"function {fname!r} requires a return")
        functions.append({"name": fname, "params": [{"name": token.text, "type": typ} for (token, _), typ in zip(fn["params"], signatures[fname][0])], "return_type": return_type, "body": body})
    def walk(value):
        if isinstance(value, dict):
            yield value
            for child in value.values(): yield from walk(child)
        elif isinstance(value, list):
            for child in value: yield from walk(child)
    calls, impure = {}, {}
    for fn in functions:
        values = list(walk(fn["body"])); calls[fn["name"]] = {value["name"] for value in values if value.get("kind") == "call"}
        impure[fn["name"]] = any(value.get("kind") in {"print", "horn_query", "horn_plan", "horn_add", "horn_correct", "horn_remove", "horn_evaluate", "horn_load", "horn_save", "horn_restore", "horn_commit", "horn_rule_history", "indexed_call", "list_push", "map_set", "map_remove"} or value.get("kind", "").startswith("graph_") for value in values)
    def pure(name, seen=()):
        return name in seen or (not impure[name] and all(pure(callee, (*seen, name)) for callee in calls[name]))
    for name, token in heuristics:
        if not pure(name): _v3error(token, "heuristic must be transitively pure")
    if horn_v7:
        for value in walk(functions):
            if value.get("kind") == "horn_query": _v3error(program.functions[0]["token"], "static Horn closure is unavailable in IR7; use a Horn plan method")
            if value.get("kind") == "horn_plan" and "memory_budget" not in value["plan"]:
                _v3error(program.functions[0]["token"], "IR7 Horn plans require memory_budget")
    if not extended: return {"version": 2, "functions": functions}
    if not v4:
        def v3shape(value):
            if isinstance(value, list): return [v3shape(child) for child in value]
            if not isinstance(value, dict): return value
            out = {key: v3shape(child) for key, child in value.items()}
            if out.get("kind") == "graph_add_edge": out.pop("payload")
            if out.get("kind") == "graph_find": out.pop("cost"); out.pop("heuristic")
            return out
        graph_ir = [{key: value for key, value in graph.items() if key != "edge_type"} for graph in graph_ir]
        functions = v3shape(functions)
    return {"version": 7 if horn_v7 else 6 if horn_v6 else 5 if horn_v5 else 4 if v4 else 3, "structs": [{"name": item["name"].text, "fields": [{"name": token.text, "type": source_type(typ, token)} for token, typ in item["fields"]]} for item in program.structs], "enums": [{"name": item["name"].text, "members": [member.text for member in item["members"]]} for item in program.enums], "relations": relation_ir, "graphs": graph_ir, "externs": list(externs.values()), "functions": functions}


# Keep the public API stable while routing all source through the extended parser.
def parse(source: str) -> _V3Program: return _V3Parser(source).parse()
def lower(program: _V3Program) -> dict: return _v3lower(program)
def compile_source(source: str) -> dict: return lower(parse(source))
