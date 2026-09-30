"""Literal source Horn calls lowered to one bounded native query node.

This module deliberately owns no inference: generated C invokes native_graph.c.
"""
from __future__ import annotations

import json
from pathlib import Path

_I32 = 2 ** 31 - 1
_SOURCE = Path(__file__).with_name("runtime") / "native_graph.c"
_MAGIC = 0x4D524C32


def _bad(message):
    raise ValueError(message)


def _text(value):
    return isinstance(value, str) and "\0" not in value and not any(0xD800 <= ord(char) <= 0xDFFF for char in value)


def _literal(node, kind, error, message):
    if not (isinstance(node, tuple) and len(node) == 3 and node[0] == "literal"
            and type(node[2]) is kind):
        error(node[1] if isinstance(node, tuple) and len(node) > 1 else None, message)
    return node[2]


def _name(node):
    return node[2] if isinstance(node, tuple) and len(node) == 3 and node[0] == "name" else None


def _call(node, name, error):
    if not (isinstance(node, tuple) and len(node) == 4 and node[0] == "call" and _name(node[2]) == name):
        error(node[1] if isinstance(node, tuple) and len(node) > 1 else None, "expected %s(...)" % name)
    return node[3]


def _fields(args, required, optional, error, token, message):
    out = {}
    for field, value in args:
        if field is None or field.text in out:
            error(field or token, message)
        out[field.text] = value
    if set(out) - set(required) - set(optional) or not set(required) <= set(out):
        error(token, message)
    return out


def _triple(node, error):
    args = _call(node, "Triple", error)
    if all(field is None for field, _ in args) and len(args) == 3:
        values = [value for _, value in args]
    else:
        values = [_fields(args, ("subject", "predicate", "object"), (), error, node[1],
                          "Triple requires subject, predicate, object")[key]
                  for key in ("subject", "predicate", "object")]
    return [_literal(value, str, error, "Triple values must be string literals") for value in values]


def _evidence(node, error):
    args = _fields(_call(node, "Evidence", error), ("source", "start", "end", "text"), (),
                   error, node[1], "Evidence requires source, start, end, text")
    source = _literal(args["source"], str, error, "Evidence fields must be literals")
    start = _literal(args["start"], int, error, "Evidence fields must be literals")
    end = _literal(args["end"], int, error, "Evidence fields must be literals")
    text = _literal(args["text"], str, error, "Evidence fields must be literals")
    if start < 0 or end < start or end > len(source) or source[start:end] != text:
        error(node[1], "invalid Evidence source span")
    return {"source": source, "start": start, "end": end, "text": text}


def _fact(node, error):
    args = _fields(_call(node, "Fact", error), ("id", "subject", "predicate", "object"),
                   ("evidence", "polarity", "modality"), error, node[1],
                   "Fact requires id, subject, predicate, object")
    row = {"id": _literal(args["id"], str, error, "Fact id must be a string literal"),
           "triple": [_literal(args[key], str, error, "Fact terms must be string literals")
                      for key in ("subject", "predicate", "object")],
           "polarity": True, "modality": "asserted", "evidence": {}}
    if not row["id"]:
        error(node[1], "Fact id must not be empty")
    if "evidence" in args:
        row["evidence"] = _evidence(args["evidence"], error)
    if "polarity" in args:
        row["polarity"] = _literal(args["polarity"], bool, error, "Fact polarity must be true or false")
    if "modality" in args:
        row["modality"] = _literal(args["modality"], str, error, "Fact modality must be a string literal")
    return row


def _rule(node, error):
    args = _fields(_call(node, "Rule", error), ("id", "body", "head"), ("version",), error,
                   node[1], "Rule requires id, body, head")
    version = None
    if "version" in args:
        value = args["version"]
        if not (isinstance(value, tuple) and value[0] == "literal" and type(value[2]) in (str, int)):
            error(value[1], "Rule version must be a string or int32 literal")
        version = value[2]
    return {"id": _literal(args["id"], str, error, "Rule id must be a string literal"),
            "body": _triple(args["body"], error), "head": _triple(args["head"], error),
            "version": version}


def _horn(node, error):
    args = _fields(_call(node, "Horn", error), ("facts", "rules"), (), error, node[1],
                   "Horn requires facts and rules")
    facts_args = _call(args["facts"], "Facts", error)
    rules_args = _call(args["rules"], "Rules", error)
    if any(field is not None for field, _ in facts_args + rules_args):
        error(node[1], "Facts and Rules use positional entries")
    return {"facts": [_fact(value, error) for _, value in facts_args],
            "rules": [_rule(value, error) for _, value in rules_args]}


def lower_plan_constructor(node, error_callback):
    """Lower one literal plan constructor for the mutable source v5 slice."""
    plan = _horn(node, error_callback)
    try:
        validate_plan_constructor(plan)
    except ValueError as failure:
        error_callback(node[1], str(failure))
    ids = [fact["id"] for fact in plan["facts"]]
    if len(ids) != len(set(ids)):
        error_callback(node[1], "duplicate horn plan fact id")
    return plan


def lower_plan_constructor_v6(node, error_callback):
    args = _fields(_call(node, "Horn", error_callback), ("facts", "rules"), ("capacity",), error_callback, node[1], "Horn requires facts and rules; optional capacity")
    capacity = 64 if "capacity" not in args else _literal(args["capacity"], int, error_callback, "capacity must be an integer literal")
    plain_node = (node[0], node[1], node[2], [(key, value) for key, value in node[3] if key is None or key.text != "capacity"])
    plan = dict(_horn(plain_node, error_callback), capacity=capacity)
    try:
        return validate_plan_constructor_v6(plan)
    except ValueError as failure:
        error_callback(node[1], str(failure))


def lower_plan_constructor_v7(node, error_callback):
    args = _fields(_call(node, "Horn", error_callback), ("facts", "rules", "memory_budget"), ("capacity",), error_callback, node[1], "Horn requires facts, rules, memory_budget; optional capacity")
    budget = _literal(args["memory_budget"], int, error_callback, "memory_budget must be an integer literal")
    capacity = 64 if "capacity" not in args else _literal(args["capacity"], int, error_callback, "capacity must be an integer literal")
    facts_args, rules_args = _call(args["facts"], "Facts", error_callback), _call(args["rules"], "Rules", error_callback)
    if any(field is not None for field, _ in facts_args + rules_args): error_callback(node[1], "Facts and Rules use positional entries")
    rules = []
    for _, raw in rules_args:
        fields = _fields(_call(raw, "Rule", error_callback), ("id", "body", "head"), ("version",), error_callback, raw[1], "Rule requires id, body, head")
        body_args = _call(fields["body"], "All", error_callback)
        if not 1 <= len(body_args) <= 8 or any(field is not None for field, _ in body_args): error_callback(raw[1], "All requires one to eight positional Triple values")
        version = None
        if "version" in fields:
            value = fields["version"]
            if not (isinstance(value, tuple) and value[0] == "literal" and type(value[2]) in {str, int}): error_callback(value[1], "Rule version must be a string or int32 literal")
            version = value[2]
        rules.append({"id": _literal(fields["id"], str, error_callback, "Rule id must be a string literal"), "body": [_triple(value, error_callback) for _, value in body_args], "head": _triple(fields["head"], error_callback), "version": version})
    plan = {"facts": [_fact(value, error_callback) for _, value in facts_args], "rules": rules, "capacity": capacity, "memory_budget": budget}
    if not 1 <= capacity <= _I32 or not 1 <= budget <= 2 ** 63 - 1 or len(rules) > 128: error_callback(node[1], "invalid Horn v7 capacity, memory_budget, or rule count")
    return plan


def validate_plan_constructor_v7(plan):
    if not isinstance(plan, dict) or set(plan) != {"facts", "rules", "capacity", "memory_budget"}: _bad("invalid v7 horn plan")
    if type(plan["capacity"]) is not int or not 1 <= plan["capacity"] <= _I32 or type(plan["memory_budget"]) is not int or not 1 <= plan["memory_budget"] <= 2 ** 63 - 1: _bad("invalid v7 Horn capacity or memory budget")
    if not isinstance(plan["facts"], list) or not isinstance(plan["rules"], list): _bad("invalid v7 Horn plan lists")
    if len(plan["facts"]) > plan["capacity"] or len(plan["rules"]) > 128: _bad("invalid v7 Horn limits")
    _validate_plan({"facts": plan["facts"], "rules": []}, plan["capacity"])
    ids = set()
    for rule in plan["rules"]:
        if not isinstance(rule, dict) or set(rule) != {"id", "body", "head", "version"} or not _text(rule["id"]) or not rule["id"] or rule["id"] in ids or not isinstance(rule["body"], list) or not 1 <= len(rule["body"]) <= 8: _bad("invalid v7 Horn rule")
        version = rule["version"]
        if not (version is None or isinstance(version, str) and _text(version) or type(version) is int and -2 ** 31 <= version <= _I32): _bad("invalid v7 Horn rule version")
        triples = [*rule["body"], rule["head"]]
        if any(not isinstance(triple, list) or len(triple) != 3 or any(not _text(term) or not term for term in triple) for triple in triples): _bad("invalid v7 Horn rule triple")
        ids.add(rule["id"])
        terms = [term for triple in triples for term in triple]
        variables = {term for term in terms if term.startswith("?")}
        body_variables = {part for triple in rule["body"] for part in triple if part.startswith("?")}
        if "?" in variables or len(variables) > 8 or any(term.startswith("?") and term not in body_variables for term in rule["head"]): _bad("unsafe v7 Horn rule")
    return plan


def emit_v7_support(plan_nodes=(), query_nodes=()):
    plans = [validate_plan_constructor_v7(node) for node in plan_nodes]
    headers = ["knowledge_store.h", "knowledge_engine.h", "horn_jsonl.h", "knowledge_persist.h", "knowledge_cache.h", "knowledge_journal.h", "horn_runtime_v7.h"]
    lines = []
    for header in headers:
        text = (_SOURCE.parent / header).read_text(encoding="utf-8")
        for included in headers: text = text.replace('#include "' + included + '"', '')
        lines.append(text)
    for index, plan in enumerate(plans):
        prefix = "mrl_horn_plan_%d" % index
        facts = []
        for fact in plan["facts"]:
            evidence = fact["evidence"]
            ev = "{0,0,0,0,0}" if not evidence else "{1,%s,%s,%d,%d}" % (_c_string(evidence["source"]), _c_string(evidence["text"]), evidence["start"], evidence["end"])
            facts.append("{%s,%s,%s,%s,%s,%d,%s}" % (_c_string(fact["id"]), *[_c_string(x) for x in fact["triple"]], _c_string(fact["modality"]), int(fact["polarity"]), ev))
        rules = []
        for rule in plan["rules"]:
            body = "{" + ",".join("{" + ",".join(_c_string(x) for x in triple) + "}" for triple in rule["body"]) + "}"
            rules.append("{%s,%s,%d,%s,{%s}}" % (_c_string(rule["id"]), _c_string(json.dumps(rule["version"], ensure_ascii=False)), len(rule["body"]), body, ",".join(_c_string(x) for x in rule["head"])))
        lines += ["static const MrlHornPlanFact %s_facts[] = {%s};" % (prefix, ",".join(facts) or "{0}"), "static const MrlHornPlanRule %s_rules[] = {%s};" % (prefix, ",".join(rules) or "{0}"), "static const MrlHornPlanTemplate %s = {%s_facts,%d,%s_rules,%d,%d,%d};" % (prefix, prefix, len(facts), prefix, len(rules), plan["capacity"], plan["memory_budget"])]
    return "\n".join(lines)


def validate_plan_constructor(plan):
    """Validate the literal backing plan used by the legacy IR v5 Horn value."""
    probe = {"kind": "horn_query", "type": "horn_result", "operation": "closure",
             "plan": plan, "limit": 2048, "proof_limit": 32, "search_limit": 16384,
             "target": None}
    validate_query(probe)
    ids = [fact["id"] for fact in plan["facts"]]
    if len(ids) != len(set(ids)):
        _bad("duplicate horn plan fact id")
    return plan


def validate_plan_constructor_v6(plan):
    """Admit the v6 source-plan storage ceiling without widening v4/v5 wire ABI."""
    if not isinstance(plan, dict) or set(plan) not in ({"facts", "rules"}, {"facts", "rules", "capacity"}):
        _bad("invalid horn plan")
    capacity = plan.get("capacity", 64)
    if type(capacity) is not int or not 64 <= capacity <= 16384:
        _bad("invalid horn capacity")
    plain = {"facts": plan["facts"], "rules": plan["rules"]}
    _validate_plan(plain, capacity)
    return {**plain, "capacity": capacity}


def validate_external_fact_record(record):
    """Strict JSONL ingress schema; callers reject a whole batch before mutation."""
    if not isinstance(record, dict) or set(record) - {"id", "triple", "subject", "predicate", "object", "polarity", "modality", "evidence"}:
        _bad("invalid horn input record")
    triple = record.get("triple")
    named = [record.get(key) for key in ("subject", "predicate", "object")]
    if (triple is None and not all(value is not None for value in named)) or (triple is not None and any(value is not None for value in named)):
        _bad("horn input requires triple or subject/predicate/object")
    fact = {"id": record.get("id"), "triple": triple if triple is not None else named,
            "polarity": record.get("polarity", True), "modality": record.get("modality", "asserted"),
            "evidence": record.get("evidence", {})}
    _validate_plan({"facts": [fact], "rules": []}, 1)
    return fact


def _validate_plan(plan, capacity):
    probe = {"kind": "horn_query", "type": "horn_result", "operation": "closure",
             "plan": plan, "limit": 2048, "proof_limit": 32, "search_limit": 16384,
             "target": None}
    _validate_query(probe, capacity)
    ids = [fact["id"] for fact in plan["facts"]]
    if len(ids) != len(set(ids)):
        _bad("duplicate horn plan fact id")
    return plan


def lower_source_call(node, error_callback):
    """Lower the frontend's raw tuple AST, or return None for another builtin."""
    if not (isinstance(node, tuple) and len(node) == 4 and node[0] == "call"):
        return None
    operation = _name(node[2])
    if operation in {"Horn", "Facts", "Fact", "Rules", "Rule", "Triple"}:
        error_callback(node[1], "%s values are only supported inline in closure calls" % operation)
    if operation not in {"closure", "closure_with_provenance"}:
        return None
    args = node[3]
    if not args or args[0][0] is not None:
        error_callback(node[1], "%s requires Horn(...) as its first argument" % operation)
    named = _fields(args[1:], (),
                    ("limit", "proof_limit", "search_limit", "target"), error_callback, node[1],
                    "invalid Horn query options")
    if operation == "closure" and set(named) - {"limit", "target"}:
        error_callback(node[1], "closure accepts only limit and target")
    if operation == "closure_with_provenance" and "target" in named:
        error_callback(node[1], "closure_with_provenance has no target")
    def bound(key, default):
        value = default if key not in named else _literal(named[key], int, error_callback,
                                                           "%s must be a positive int32 literal" % key)
        if type(value) is not int or not 1 <= value <= _I32:
            error_callback(named.get(key, node)[1], "%s must be a positive int32 literal" % key)
        return value
    limit = bound("limit", 2048)
    query = {"kind": "horn_query", "type": "horn_result", "operation": operation,
             "plan": _horn(args[0][1], error_callback), "limit": limit,
             "proof_limit": bound("proof_limit", 32),
             "search_limit": bound("search_limit", limit * 8), "target": None}
    if "target" in named:
        query["target"] = _triple(named["target"], error_callback)
    try:
        validate_query(query)
    except ValueError as failure:
        error_callback(node[1], str(failure))
    return query


def validate_query(query):
    return _validate_query(query, 64)


def validate_query_v6(query):
    return _validate_query(query, 16384)


def _validate_query(query, capacity):
    """Independently admit the exact backend-neutral, literal-only Horn IR."""
    if not isinstance(query, dict) or set(query) != {"kind", "type", "operation", "plan", "limit", "proof_limit", "search_limit", "target"}:
        _bad("invalid horn_query")
    if query["kind"] != "horn_query" or query["type"] != "horn_result" or not isinstance(query["operation"], str) or query["operation"] not in {"closure", "closure_with_provenance"}:
        _bad("invalid horn_query")
    if query["operation"] == "closure_with_provenance" and query["target"] is not None:
        _bad("invalid horn target")
    if query["target"] is not None and (not _triple_value(query["target"])):
        _bad("invalid horn target")
    if any(type(query[key]) is not int or not 1 <= query[key] <= _I32
           for key in ("limit", "proof_limit", "search_limit")):
        _bad("invalid horn budget")
    plan = query["plan"]
    if not isinstance(plan, dict) or set(plan) != {"facts", "rules"} or not isinstance(plan["facts"], list) or not isinstance(plan["rules"], list):
        _bad("invalid horn plan")
    if len(plan["facts"]) > capacity or len(plan["rules"]) > 32:
        _bad("native_capacity")
    ids, supports = set(), set()
    for fact in plan["facts"]:
        if not isinstance(fact, dict) or set(fact) != {"id", "triple", "polarity", "modality", "evidence"} or not _text(fact["id"]) or not fact["id"] or not _triple_value(fact["triple"]) or type(fact["polarity"]) is not bool or not isinstance(fact["modality"], str) or fact["modality"] not in {"asserted", "planned", "conditional"}:
            _bad("invalid horn fact")
        evidence = fact["evidence"]
        if evidence:
            if not isinstance(evidence, dict) or set(evidence) != {"source", "start", "end", "text"} or not _text(evidence["source"]) or type(evidence["start"]) is not int or type(evidence["end"]) is not int or not _text(evidence["text"]) or evidence["start"] < 0 or evidence["end"] < evidence["start"] or evidence["end"] > len(evidence["source"]) or evidence["source"][evidence["start"]:evidence["end"]] != evidence["text"] or evidence["start"] > _I32 or evidence["end"] > _I32:
                _bad("invalid horn evidence")
        elif evidence != {}:
            _bad("invalid horn evidence")
        if fact["polarity"] and fact["modality"] == "asserted":
            if fact["id"] in supports: _bad("duplicate_native_support_id")
            supports.add(fact["id"])
    for rule in plan["rules"]:
        if not isinstance(rule, dict) or set(rule) != {"id", "body", "head", "version"} or not _text(rule["id"]) or not rule["id"] or rule["id"] in ids or not _triple_value(rule["body"]) or not _triple_value(rule["head"]) or type(rule["version"]) not in (str, int, type(None)) or (type(rule["version"]) is int and not -2**31 <= rule["version"] <= _I32) or (isinstance(rule["version"], str) and not _text(rule["version"])):
            _bad("invalid horn rule")
        ids.add(rule["id"])
        variables = list(dict.fromkeys(value for value in rule["body"] + rule["head"] if value.startswith("?")))
        if any(value == "?" for value in variables) or len(variables) > 3:
            _bad("unsupported_native_rule")
        if any(value.startswith("?") and value not in rule["body"] for value in rule["head"]):
            _bad("unsafe_rule")
    return _prepared(query)


def _triple_value(value):
    return isinstance(value, list) and len(value) == 3 and all(_text(item) and item for item in value)


def _prepared(query):
    plan, symbols = query["plan"], {}
    for fact in plan["facts"]:
        for value in fact["triple"]: symbols.setdefault(value, len(symbols))
    for rule in plan["rules"]:
        for value in rule["body"] + rule["head"]:
            if not value.startswith("?"): symbols.setdefault(value, len(symbols))
    terms, variables = [], []
    for rule in plan["rules"]:
        names = list(dict.fromkeys(value for value in rule["body"] + rule["head"] if value.startswith("?")))
        variables.append(names)
        term = lambda value: -(names.index(value) + 1) if value.startswith("?") else symbols[value]
        terms.append(([term(value) for value in rule["body"]], [term(value) for value in rule["head"]]))
    words = [_MAGIC, 1 if query["operation"] == "closure" else 2, len(plan["facts"]), len(plan["rules"]), query["limit"], query["proof_limit"], query["search_limit"]]
    for fact in plan["facts"]:
        words += [*(symbols[value] for value in fact["triple"]), int(fact["polarity"]), int(fact["modality"] == "asserted")]
    words += [value for body, _ in terms for value in body]
    words += [value for _, head in terms for value in head]
    target = None if query["target"] is None else [symbols.get(value, -1) for value in query["target"]]
    return {"query": query, "symbols": list(symbols), "variables": variables, "words": words, "target": target}


def _c_string(value):
    return '"' + ''.join("\\%03o" % byte for byte in value.encode("utf-8")) + '"'


def _array(values, render=str):
    return ", ".join(render(value) for value in values) or "0"


def emit_support(query_nodes, plan_nodes=()):
    """Emit static query storage and a JSON renderer around the shared native core."""
    prepared = [validate_query(node) for node in query_nodes]
    plans = [validate_plan_constructor(node) for node in plan_nodes]
    if not prepared and not plans:
        return ""
    prelude, functions = _C_RUNTIME.split("/* MRL_HORN_FUNCTIONS */", 1)
    lines = ["#define MRL_GRAPH_SHARED", _SOURCE.read_text(encoding="utf-8"), "", prelude]
    descriptors = []
    for index, item in enumerate(prepared):
        query, plan = item["query"], item["query"]["plan"]
        prefix = "mrl_horn_%d" % index
        lines.append("static const int32_t %s_words[] = {%s};" % (prefix, _array(item["words"])))
        lines.append("static const char *const %s_symbols[] = {%s};" % (prefix, _array(item["symbols"], _c_string)))
        lines.append("static const char *const %s_supports[] = {%s};" % (prefix, _array([fact["id"] for fact in plan["facts"]], _c_string)))
        evidence = []
        for fact in plan["facts"]:
            row = fact["evidence"]
            evidence.append("{0,0,0,0,0}" if not row else "{1,%s,%s,%d,%d}" % (_c_string(row["source"]), _c_string(row["text"]), row["start"], row["end"]))
        lines.append("static const MrlHornEvidence %s_evidence[] = {%s};" % (prefix, _array(evidence)))
        rule_rows = []
        for rule, names in zip(plan["rules"], item["variables"]):
            order = sorted(range(len(names)), key=names.__getitem__) + [-1] * (3 - len(names))
            version = rule["version"]
            version_text = "None" if version is None else str(version)
            version_json = _c_string("null" if version is None else json.dumps(version, ensure_ascii=False))
            rule_rows.append("{%s,%s,%s,{%s},{%s},%d}" % (_c_string(rule["id"]), _c_string(version_text), version_json, _array(names + [""] * (3 - len(names)), _c_string), _array(order), len(names)))
        lines.append("static const MrlHornRule %s_rules[] = {%s};" % (prefix, _array(rule_rows)))
        target = item["target"] or [-1, -1, -1]
        descriptors.append("{%s_words,%d,%s_symbols,%s_supports,%s_evidence,%s_rules,%d,%d,%d,{%s}}" % (prefix, len(item["words"]), prefix, prefix, prefix, prefix, len(plan["rules"]), 1 if query["operation"] == "closure" else 2, int(query["target"] is not None), _array(target)))
    lines.append("static MrlHornResult mrl_horn_results[%d] = {%s};" % (max(1, len(prepared)), _array(descriptors)))
    lines.append("static const size_t mrl_horn_result_count = %d;" % len(prepared))
    lines.append(functions)
    if plans:
        lines.append(_MUTABLE_C_RUNTIME)
        for index, plan in enumerate(plans):
            prefix = "mrl_horn_plan_%d" % index
            facts = []
            for fact in plan["facts"]:
                evidence = fact["evidence"]
                ev = "{0,0,0,0,0}" if not evidence else "{1,%s,%s,%d,%d}" % (_c_string(evidence["source"]), _c_string(evidence["text"]), evidence["start"], evidence["end"])
                facts.append("{%s,%s,%s,%s,%s,%d,%s}" % (_c_string(fact["id"]), *[_c_string(value) for value in fact["triple"]], _c_string(fact["modality"]), int(fact["polarity"]), ev))
            lines.append("static const MrlHornPlanFact %s_facts[] = {%s};" % (prefix, _array(facts)))
            rules = []
            for rule in plan["rules"]:
                names = list(dict.fromkeys(value for value in rule["body"] + rule["head"] if value.startswith("?")))
                order = sorted(range(len(names)), key=names.__getitem__) + [-1] * (3 - len(names))
                version = rule["version"]
                meta = "{%s,%s,%s,{%s},{%s},%d}" % (_c_string(rule["id"]), _c_string("None" if version is None else str(version)), _c_string("null" if version is None else json.dumps(version, ensure_ascii=False)), _array(names + [""] * (3-len(names)), _c_string), _array(order), len(names))
                rules.append("{%s,{%s},{%s}}" % (meta, _array(rule["body"], _c_string), _array(rule["head"], _c_string)))
            lines.append("static const MrlHornPlanRule %s_rules[] = {%s};" % (prefix, _array(rules)))
            lines.append("static const MrlHornPlanTemplate %s = {%s_facts,%d,%s_rules,%d};" % (prefix, prefix, len(plan["facts"]), prefix, len(plan["rules"])))
    return "\n".join(lines)


def emit_v6_support(plan_nodes=(), query_nodes=()):
    """Emit capacity-sized owned Horn values, sharing the unchanged inference core."""
    plans = [validate_plan_constructor_v6(node) for node in plan_nodes]
    queries = [validate_query(node)["query"] for node in query_nodes]
    plans += [dict(query["plan"], capacity=64) for query in queries]
    prelude, functions = _C_RUNTIME.split("/* MRL_HORN_FUNCTIONS */", 1)
    prelude = prelude.replace("uint8_t input[MAX_INPUT],output[MAX_OUTPUT]; size_t written;", "uint8_t *output; size_t output_capacity,written,*offsets;")
    functions = "\n".join(line for line in functions.splitlines() if not line.startswith("static const MrlHornResult *mrl_horn_run("))
    old_at = next(line for line in functions.splitlines() if line.startswith("static size_t mrl_horn_fact_at("))
    functions = functions.replace(old_at, "static size_t mrl_horn_fact_at(const MrlHornResult *r,int32_t fact){return r->offsets[fact];}")
    functions = functions.replace("int32_t chain[64],n=0;while(at>=0&&n<64)", "int32_t *chain=malloc(((size_t)r->fact_count+1)*sizeof(*chain)),n=0;if(!chain)mrl_runtime_fail(\"MRL horn proof allocation\");while(at>=0&&n<r->fact_count)")
    functions = functions.replace("mrl_horn_record(r,chain[--n]);if(n)putchar(',');}}", "mrl_horn_record(r,chain[--n]);if(n)putchar(',');}free(chain);}")
    lines = ["#define MRL_GRAPH_SHARED", _SOURCE.read_text(encoding="utf-8"),
             (_SOURCE.parent / "horn_incremental.h").read_text(encoding="utf-8"), prelude, functions,
             (_SOURCE.parent / "horn_jsonl.h").read_text(encoding="utf-8"),
             (_SOURCE.parent / "horn_runtime.h").read_text(encoding="utf-8")]
    for index, plan in enumerate(plans):
        prefix = "mrl_horn_plan_%d" % index
        facts = []
        for fact in plan["facts"]:
            evidence = fact["evidence"]
            ev = "{0,0,0,0,0}" if not evidence else "{1,%s,%s,%d,%d}" % (_c_string(evidence["source"]), _c_string(evidence["text"]), evidence["start"], evidence["end"])
            facts.append("{%s,%s,%s,%s,%s,%d,%s}" % (_c_string(fact["id"]), *[_c_string(x) for x in fact["triple"]], _c_string(fact["modality"]), int(fact["polarity"]), ev))
        lines.append("static const MrlHornPlanFact %s_facts[] = {%s};" % (prefix, _array(facts)))
        rules = []
        for rule in plan["rules"]:
            names = list(dict.fromkeys(x for x in rule["body"] + rule["head"] if x.startswith("?")))
            order = sorted(range(len(names)), key=names.__getitem__) + [-1] * (3-len(names))
            version = rule["version"]
            meta = "{%s,%s,%s,{%s},{%s},%d}" % (_c_string(rule["id"]), _c_string("None" if version is None else str(version)), _c_string("null" if version is None else json.dumps(version, ensure_ascii=False)), _array(names + [""]*(3-len(names)), _c_string), _array(order), len(names))
            rules.append("{%s,{%s},{%s}}" % (meta, _array(rule["body"], _c_string), _array(rule["head"], _c_string)))
        lines.append("static const MrlHornPlanRule %s_rules[] = {%s};" % (prefix, _array(rules)))
        lines.append("static const MrlHornPlanTemplate %s = {%s_facts,%d,%s_rules,%d,%d};" % (prefix, prefix, len(plan["facts"]), prefix, len(plan["rules"]), plan["capacity"]))
    lines.append("static MrlHornSnapshot *mrl_horn_static_snapshots[%d];" % max(1, len(queries)))
    lines.append("static const MrlHornResult *mrl_horn_run(int index){switch(index){")
    for i, query in enumerate(queries):
        targets = ["NULL"]*3 if query["target"] is None else [_c_string(x) for x in query["target"]]
        lines.append("case %d:if(!mrl_horn_static_snapshots[%d]){MrlHornPlan*p=mrl_horn_plan_new(&mrl_horn_plan_%d);mrl_horn_static_snapshots[%d]=mrl_horn_evaluate(p,%d,%d,%d,%d,%d,%s,%s,%s);mrl_horn_plan_release(p);}return &mrl_horn_static_snapshots[%d]->result;" % (i,i,len(plan_nodes)+i,i,1 if query["operation"]=="closure" else 2,query["limit"],query["proof_limit"],query["search_limit"],int(query["target"] is not None),*targets,i))
    lines.append("default:return NULL;}}")
    return "\n".join(lines)


_C_RUNTIME = r'''
typedef struct { int present; const char *source,*text; int32_t start,end; } MrlHornEvidence;
typedef struct { const char *id,*version_text,*version_json,*vars[3]; int order[3],count; } MrlHornRule;
typedef struct {
 const int32_t *words; size_t word_count; const char *const *symbols; const char *const *supports; const MrlHornEvidence *evidence; const MrlHornRule *rules; int32_t rule_count,operation,has_target,target[3];
 uint8_t input[MAX_INPUT],output[MAX_OUTPUT]; size_t written; int32_t status,complete,reason,searches,fact_count,proof_count,ran;
} MrlHornResult;
#include <inttypes.h>
/* MRL_HORN_FUNCTIONS */
static void mrl_horn_put(uint8_t *p,int32_t v){uint32_t u=(uint32_t)v;p[0]=(uint8_t)u;p[1]=(uint8_t)(u>>8);p[2]=(uint8_t)(u>>16);p[3]=(uint8_t)(u>>24);}
static int32_t mrl_horn_get(const MrlHornResult *r,size_t at){const uint8_t *p=r->output+at;return (int32_t)((uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24));}
static size_t mrl_horn_fact_at(const MrlHornResult *r,int32_t fact){size_t p=20;int32_t i;for(i=0;i<fact;i++)p+=28+(size_t)mrl_horn_get(r,p+24)*32;return p;}
static const MrlHornResult *mrl_horn_run(int index){MrlHornResult *r;size_t i,p;if(index<0||(size_t)index>=mrl_horn_result_count)return 0;r=&mrl_horn_results[index];if(r->ran)return r;for(i=0;i<r->word_count;i++)mrl_horn_put(r->input+i*4,r->words[i]);r->status=mrl_native_graph_run(r->input,r->word_count*4,r->output,sizeof(r->output),&r->written);if(r->status==0&&r->written>=4){r->status=mrl_horn_get(r,0);if(r->status==0&&r->written>=20){r->complete=mrl_horn_get(r,4);r->reason=mrl_horn_get(r,8);r->searches=mrl_horn_get(r,12);r->fact_count=mrl_horn_get(r,16);for(i=0;i<(size_t)r->fact_count;i++){p=mrl_horn_fact_at(r,(int32_t)i);r->proof_count+=mrl_horn_get(r,p+24);}}}r->ran=1;return r;}
static void mrl_horn_byte(unsigned char c,int level){const char *short_escape=c==8?"b":c==9?"t":c==10?"n":c==12?"f":c==13?"r":0;if(level<=0){putchar(c);return;}if(c=='"'||c=='\\'){mrl_horn_byte('\\',level-1);mrl_horn_byte(c,level-1);return;}if(short_escape){mrl_horn_byte('\\',level-1);mrl_horn_byte((unsigned char)*short_escape,level-1);return;}if(c<32){mrl_horn_byte('\\',level-1);mrl_horn_byte('u',level-1);mrl_horn_byte('0',level-1);mrl_horn_byte('0',level-1);mrl_horn_byte((unsigned char)("0123456789abcdef"[c>>4]),level-1);mrl_horn_byte((unsigned char)("0123456789abcdef"[c&15]),level-1);return;}putchar(c);}
static void mrl_horn_piece(const char *s,int level){const unsigned char *p=(const unsigned char *)s;for(;*p;p++)mrl_horn_byte(*p,level);}
static void mrl_horn_string(const char *s){putchar('"');mrl_horn_piece(s,1);putchar('"');}
static void mrl_horn_triple(const MrlHornResult *r,int32_t s,int32_t p,int32_t o,int escape){mrl_horn_piece("[",escape);mrl_horn_piece("\"",escape);mrl_horn_piece(r->symbols[s],escape+1);mrl_horn_piece("\",\"",escape);mrl_horn_piece(r->symbols[p],escape+1);mrl_horn_piece("\",\"",escape);mrl_horn_piece(r->symbols[o],escape+1);mrl_horn_piece("\"]",escape);}
static void mrl_horn_id(const MrlHornResult *r,int32_t fact,int32_t bundle,int escape){size_t p=mrl_horn_fact_at(r,fact)+28+(size_t)bundle*32;int32_t asserted=mrl_horn_get(r,p),rule=mrl_horn_get(r,p+4),input=mrl_horn_get(r,p+8),parent=mrl_horn_get(r,p+12),parent_bundle=mrl_horn_get(r,p+16);if(asserted){mrl_horn_piece("support:",escape);mrl_horn_piece(r->supports[input],escape);return;}mrl_horn_piece("derive:",escape);mrl_horn_piece(r->rules[rule].id,escape);mrl_horn_piece(":",escape);mrl_horn_piece(r->rules[rule].version_text,escape);mrl_horn_piece(":",escape);mrl_horn_piece("[",escape);{size_t f=mrl_horn_fact_at(r,fact);mrl_horn_triple(r,mrl_horn_get(r,f),mrl_horn_get(r,f+4),mrl_horn_get(r,f+8),escape);}mrl_horn_piece(",[",escape);{int k;for(k=0;k<r->rules[rule].count;k++){int slot=r->rules[rule].order[k];if(k)mrl_horn_piece(",",escape);mrl_horn_piece("[\"",escape);mrl_horn_piece(r->rules[rule].vars[slot],escape+1);mrl_horn_piece("\",\"",escape);mrl_horn_piece(r->symbols[mrl_horn_get(r,p+20+(size_t)slot*4)],escape+1);mrl_horn_piece("\"]",escape);}}mrl_horn_piece("],[\"",escape);mrl_horn_id(r,parent,parent_bundle,escape+1);mrl_horn_piece("\"]]",escape);}
static void mrl_horn_record(const MrlHornResult *r,int32_t fact){size_t p=mrl_horn_fact_at(r,fact);int32_t rule=mrl_horn_get(r,p+12),parent=mrl_horn_get(r,p+16),evidence=mrl_horn_get(r,p+20);fputs("{\"fact\":",stdout);mrl_horn_triple(r,mrl_horn_get(r,p),mrl_horn_get(r,p+4),mrl_horn_get(r,p+8),0);if(rule<0){const MrlHornEvidence *e=&r->evidence[evidence];fputs(",\"evidence\":",stdout);if(!e->present)fputs("{}",stdout);else{fputs("{\"source\":",stdout);mrl_horn_string(e->source);printf(",\"start\":%" PRId32 ",\"end\":%" PRId32 ",\"text\":",e->start,e->end);mrl_horn_string(e->text);putchar('}');}}else{fputs(",\"rule\":",stdout);mrl_horn_string(r->rules[rule].id);fputs(",\"parents\":[",stdout);{size_t q=mrl_horn_fact_at(r,parent);mrl_horn_triple(r,mrl_horn_get(r,q),mrl_horn_get(r,q+4),mrl_horn_get(r,q+8),0);}putchar(']');}putchar('}');}
static void mrl_horn_proof(const MrlHornResult *r,int32_t fact,int32_t bundle){size_t p=mrl_horn_fact_at(r,fact)+28+(size_t)bundle*32;int32_t asserted=mrl_horn_get(r,p),rule=mrl_horn_get(r,p+4),input=mrl_horn_get(r,p+8),parent=mrl_horn_get(r,p+12),parent_bundle=mrl_horn_get(r,p+16);fputs("{\"id\":\"",stdout);mrl_horn_id(r,fact,bundle,1);fputs("\",\"kind\":",stdout);mrl_horn_string(asserted?"asserted":"derived");fputs(",\"conclusion\":",stdout);{size_t q=mrl_horn_fact_at(r,fact);mrl_horn_triple(r,mrl_horn_get(r,q),mrl_horn_get(r,q+4),mrl_horn_get(r,q+8),0);}fputs(",\"premise_fact_ids\":[\"",stdout);if(asserted)mrl_horn_piece(r->supports[input],1);else mrl_horn_id(r,parent,parent_bundle,1);fputs("\"],\"rule\":",stdout);if(asserted)fputs("null",stdout);else mrl_horn_string(r->rules[rule].id);fputs(",\"rule_version\":",stdout);if(asserted)fputs("null",stdout);else fputs(r->rules[rule].version_json,stdout);fputs(",\"bindings\":{",stdout);if(!asserted){int k;for(k=0;k<r->rules[rule].count;k++){int slot=r->rules[rule].order[k];if(k)putchar(',');mrl_horn_string(r->rules[rule].vars[slot]);putchar(':');mrl_horn_string(r->symbols[mrl_horn_get(r,p+20+(size_t)slot*4)]);}}fputs("},\"valid\":true}",stdout);}
static void mrl_horn_map(const MrlHornResult *r){int32_t i;if(!r->fact_count){fputs("{}",stdout);return;}fputs("{\"$tuple_map\":[",stdout);for(i=0;i<r->fact_count;i++){size_t p=mrl_horn_fact_at(r,i);if(i)putchar(',');fputs("{\"key\":",stdout);mrl_horn_triple(r,mrl_horn_get(r,p),mrl_horn_get(r,p+4),mrl_horn_get(r,p+8),0);fputs(",\"value\":",stdout);mrl_horn_record(r,i);putchar('}');}fputs("]}",stdout);}
static int32_t mrl_horn_target(const MrlHornResult *r){int32_t i;for(i=0;i<r->fact_count;i++){size_t p=mrl_horn_fact_at(r,i);if(mrl_horn_get(r,p)==r->target[0]&&mrl_horn_get(r,p+4)==r->target[1]&&mrl_horn_get(r,p+8)==r->target[2])return i;}return -1;}
const char *mrl_horn_reason_name(const MrlHornResult *r){if(!r)return "native_graph_abi_error";if(r->status)return r->status==1?"graph_limit":r->status==3?"unsafe_rule":r->status==4?"unsupported_native_rule":r->status==5?"malformed_native_wire":r->status==6?"native_capacity":"native_graph_abi_error";if(r->operation==1&&r->has_target&&mrl_horn_target(r)<0)return "target_not_found";return r->reason==1?"graph_limit":r->reason==2?"proof_or_search_limit":"Complete";}
static void mrl_horn_print_result(const MrlHornResult *r){int32_t i;if(!r||r->status){printf("{\"error\":");mrl_horn_string(mrl_horn_reason_name(r));puts("}");return;}if(r->operation==1){fputs("{\"known\":",stdout);mrl_horn_map(r);if(r->has_target){int32_t at=mrl_horn_target(r);if(at<0){printf(",\"complete\":false,\"reason\":\"target_not_found\",\"fact_count\":%" PRId32 ",\"proof_count\":%" PRId32 ",\"searches\":%" PRId32 "}\n",r->fact_count,r->proof_count,r->searches);return;}fputs(",\"proof\":[",stdout);{int32_t chain[64],n=0;while(at>=0&&n<64){size_t p=mrl_horn_fact_at(r,at);chain[n++]=at;at=mrl_horn_get(r,p+16);}while(n){mrl_horn_record(r,chain[--n]);if(n)putchar(',');}}putchar(']');}puts("}");return;}fputs("{\"facts\":",stdout);mrl_horn_map(r);if(!r->fact_count)fputs(",\"proof_bundles\":{}",stdout);else{fputs(",\"proof_bundles\":{\"$tuple_map\":[",stdout);for(i=0;i<r->fact_count;i++){size_t p=mrl_horn_fact_at(r,i);int32_t b,count=mrl_horn_get(r,p+24);if(i)putchar(',');fputs("{\"key\":",stdout);mrl_horn_triple(r,mrl_horn_get(r,p),mrl_horn_get(r,p+4),mrl_horn_get(r,p+8),0);fputs(",\"value\":[",stdout);for(b=0;b<count;b++){if(b)putchar(',');mrl_horn_proof(r,i,b);}fputs("]}",stdout);}fputs("]}",stdout);}printf(",\"complete\":%s,\"reason\":",r->complete?"true":"false");if(!r->reason)fputs("null",stdout);else mrl_horn_string(r->reason==1?"graph_limit":"proof_or_search_limit");printf(",\"searches\":%" PRId32 "}\n",r->searches);}
'''


_MUTABLE_C_RUNTIME = r'''
typedef struct { const char *id,*s,*p,*o,*modality; int polarity; MrlHornEvidence evidence; } MrlHornPlanFact;
typedef struct { MrlHornRule meta; const char *body[3],*head[3]; } MrlHornPlanRule;
typedef struct { const MrlHornPlanFact *facts; int32_t fact_count; const MrlHornPlanRule *rules; int32_t rule_count; } MrlHornPlanTemplate;
typedef struct { const MrlHornPlanTemplate *template; MrlHornPlanFact facts[MAX_FACTS]; int32_t fact_count,version; } MrlHornPlan;
typedef struct { MrlHornPlan plan; int32_t operation,limit,proof_limit,search_limit,has_target,version,fact_count,proof_count,searches; const char *target[3],*reason; bool complete; } MrlHornSnapshot;
static int32_t mrl_horn_dynamic_words[MAX_INPUT/4];
static const char *mrl_horn_dynamic_symbols[MAX_FACTS*3+MAX_RULES*6];
static const char *mrl_horn_dynamic_supports[MAX_FACTS];
static MrlHornEvidence mrl_horn_dynamic_evidence[MAX_FACTS];
static MrlHornRule mrl_horn_dynamic_rules[MAX_RULES];
static MrlHornResult mrl_horn_dynamic_result;
static MrlHornPlan mrl_horn_plan_new(const MrlHornPlanTemplate *t){MrlHornPlan p;memset(&p,0,sizeof(p));p.template=t;p.fact_count=t->fact_count;if(p.fact_count)memcpy(p.facts,t->facts,(size_t)p.fact_count*sizeof(*p.facts));return p;}
static int mrl_horn_plan_text(const char *s){return s&&*s;}
static int mrl_horn_plan_modality(const char *s){return s&&(!strcmp(s,"asserted")||!strcmp(s,"planned")||!strcmp(s,"conditional"));}
static bool mrl_horn_plan_add(MrlHornPlan *p,const char *id,const char *s,const char *q,const char *o,bool polarity,const char *modality,MrlHornEvidence evidence){int32_t i;if(!mrl_horn_plan_text(id)||!mrl_horn_plan_text(s)||!mrl_horn_plan_text(q)||!mrl_horn_plan_text(o)||!mrl_horn_plan_modality(modality))mrl_runtime_fail("invalid horn fact");for(i=0;i<p->fact_count;i++)if(!strcmp(p->facts[i].id,id))return false;if(p->fact_count>=MAX_FACTS)mrl_runtime_fail("native_capacity");if(p->version==INT32_MAX)mrl_runtime_fail("MRL horn version overflow");p->facts[p->fact_count++]=(MrlHornPlanFact){id,s,q,o,modality,polarity,evidence};p->version++;return true;}
static bool mrl_horn_plan_remove(MrlHornPlan *p,const char *id){int32_t i;if(!mrl_horn_plan_text(id))mrl_runtime_fail("invalid horn fact");for(i=0;i<p->fact_count;i++)if(!strcmp(p->facts[i].id,id)){if(p->version==INT32_MAX)mrl_runtime_fail("MRL horn version overflow");if(i+1<p->fact_count)memmove(p->facts+i,p->facts+i+1,(size_t)(p->fact_count-i-1)*sizeof(*p->facts));p->fact_count--;p->version++;return true;}return false;}
static int32_t mrl_horn_dynamic_symbol(const char *s,size_t *count){size_t i;for(i=0;i<*count;i++)if(!strcmp(mrl_horn_dynamic_symbols[i],s))return (int32_t)i;if(*count>=sizeof(mrl_horn_dynamic_symbols)/sizeof(*mrl_horn_dynamic_symbols))mrl_runtime_fail("native_capacity");mrl_horn_dynamic_symbols[*count]=s;return (int32_t)(*count)++;}
static int32_t mrl_horn_dynamic_term(const MrlHornPlanRule *rule,const char *s,size_t *symbols){int32_t i;if(s[0]=='?'){for(i=0;i<rule->meta.count;i++)if(!strcmp(rule->meta.vars[i],s))return -i-1;mrl_runtime_fail("unsafe_rule");}return mrl_horn_dynamic_symbol(s,symbols);}
static int32_t mrl_horn_dynamic_find(const char *s,size_t count){size_t i;for(i=0;i<count;i++)if(!strcmp(mrl_horn_dynamic_symbols[i],s))return (int32_t)i;return -1;}
static const MrlHornResult *mrl_horn_dynamic_execute(const MrlHornSnapshot *snap){MrlHornResult *r=&mrl_horn_dynamic_result;size_t words=0,symbols=0,i,p;memset(r,0,sizeof(*r));for(i=0;i<(size_t)snap->plan.fact_count;i++){const MrlHornPlanFact *f=&snap->plan.facts[i];mrl_horn_dynamic_words[7+i*5]=mrl_horn_dynamic_symbol(f->s,&symbols);mrl_horn_dynamic_words[8+i*5]=mrl_horn_dynamic_symbol(f->p,&symbols);mrl_horn_dynamic_words[9+i*5]=mrl_horn_dynamic_symbol(f->o,&symbols);mrl_horn_dynamic_words[10+i*5]=f->polarity;mrl_horn_dynamic_words[11+i*5]=!strcmp(f->modality,"asserted");mrl_horn_dynamic_supports[i]=f->id;mrl_horn_dynamic_evidence[i]=f->evidence;}for(i=0;i<(size_t)snap->plan.template->rule_count;i++){const MrlHornPlanRule *rule=&snap->plan.template->rules[i];int j;mrl_horn_dynamic_rules[i]=rule->meta;for(j=0;j<3;j++)mrl_horn_dynamic_words[7+(size_t)snap->plan.fact_count*5+i*3+j]=mrl_horn_dynamic_term(rule,rule->body[j],&symbols);for(j=0;j<3;j++)mrl_horn_dynamic_words[7+(size_t)snap->plan.fact_count*5+(size_t)snap->plan.template->rule_count*3+i*3+j]=mrl_horn_dynamic_term(rule,rule->head[j],&symbols);}words=7+(size_t)snap->plan.fact_count*5+(size_t)snap->plan.template->rule_count*6;mrl_horn_dynamic_words[0]=0x4d524c32;mrl_horn_dynamic_words[1]=snap->operation;mrl_horn_dynamic_words[2]=snap->plan.fact_count;mrl_horn_dynamic_words[3]=snap->plan.template->rule_count;mrl_horn_dynamic_words[4]=snap->limit;mrl_horn_dynamic_words[5]=snap->proof_limit;mrl_horn_dynamic_words[6]=snap->search_limit;r->words=mrl_horn_dynamic_words;r->word_count=words;r->symbols=mrl_horn_dynamic_symbols;r->supports=mrl_horn_dynamic_supports;r->evidence=mrl_horn_dynamic_evidence;r->rules=mrl_horn_dynamic_rules;r->rule_count=snap->plan.template->rule_count;r->operation=snap->operation;r->has_target=snap->has_target;for(i=0;i<3;i++)r->target[i]=snap->has_target?mrl_horn_dynamic_find(snap->target[i],symbols):-1;for(i=0;i<words;i++)mrl_horn_put(r->input+i*4,r->words[i]);r->status=mrl_native_graph_run(r->input,words*4,r->output,sizeof(r->output),&r->written);if(r->status==0&&r->written>=4){r->status=mrl_horn_get(r,0);if(r->status==0&&r->written>=20){r->complete=mrl_horn_get(r,4);r->reason=mrl_horn_get(r,8);r->searches=mrl_horn_get(r,12);r->fact_count=mrl_horn_get(r,16);for(i=0;i<(size_t)r->fact_count;i++){p=mrl_horn_fact_at(r,(int32_t)i);r->proof_count+=mrl_horn_get(r,p+24);}}}return r;}
static MrlHornSnapshot mrl_horn_evaluate(const MrlHornPlan *p,int32_t operation,int32_t limit,int32_t proof_limit,int32_t search_limit,int has_target,const char *s,const char *q,const char *o){MrlHornSnapshot snap;const MrlHornResult *r;memset(&snap,0,sizeof(snap));snap.plan=*p;snap.operation=operation;snap.limit=limit;snap.proof_limit=proof_limit;snap.search_limit=search_limit;snap.has_target=has_target;snap.target[0]=s;snap.target[1]=q;snap.target[2]=o;snap.version=p->version;r=mrl_horn_dynamic_execute(&snap);snap.fact_count=r->fact_count;snap.proof_count=r->proof_count;snap.searches=r->searches;snap.complete=r->status==0&&r->complete&&(!has_target||mrl_horn_target(r)>=0);snap.reason=mrl_horn_reason_name(r);return snap;}
static void mrl_horn_print_snapshot(const MrlHornSnapshot *snap){mrl_horn_print_result(mrl_horn_dynamic_execute(snap));}
'''
