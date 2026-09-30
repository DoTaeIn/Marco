"""Checked expression calls for the dynamic Horn domain surface."""


def lower_dynamic_call(node, expression, env, error):
    """Lower plan queries and typed snapshot access from the primitive AST."""
    if not (isinstance(node, tuple) and len(node) == 4 and node[0] == "call"):
        return None
    callee = node[2]
    if callee[0] == "name" and callee[2] in {"Candidate", "Candidates", "Constraint", "Constraints", "interpret"}:
        name = callee[2]

        def triple_terms(raw):
            if not (isinstance(raw, tuple) and len(raw) == 4 and raw[0] == "call"
                    and raw[2][0] == "name" and raw[2][2] == "Triple"):
                error(raw[1] if isinstance(raw, tuple) and len(raw) > 1 else node[1], "expected Triple(...)")
            if len(raw[3]) != 3 or any(field is not None for field, _ in raw[3]):
                error(raw[1], "Triple requires three positional strings")
            values = [expression(value, env) for _, value in raw[3]]
            if any(value["type"] != "s" for value in values): error(raw[1], "Triple terms must be strings")
            return values

        def triple_value(raw):
            return {"kind": "horn_triple", "type": "horn_triple", "terms": triple_terms(raw)}

        if name == "Candidate":
            fields = {}
            for field, value in node[3]:
                if field is None or field.text not in {"id", "meaning"} or field.text in fields:
                    error(field or node[1], "Candidate requires id and meaning")
                fields[field.text] = expression(value, env)
            if set(fields) != {"id", "meaning"} or fields["id"]["type"] != "s" or fields["meaning"]["type"] != "horn_snapshot":
                error(node[1], "Candidate requires id: s and meaning: HornSnapshot")
            return {"kind": "candidate_construct", "type": "candidate", **fields, "eval_order": [field.text for field, _ in node[3]]}
        if name in {"Candidates", "Constraints"}:
            typ = "candidate" if name == "Candidates" else "constraint"
            if any(field is not None for field, _ in node[3]):
                error(node[1], "%s requires positional values" % name)
            items = [expression(value, env) for _, value in node[3]]
            if any(value["type"] != typ for value in items): error(node[1], "%s contains the wrong value type" % name)
            return {"kind": name.lower() + "_construct", "type": name.lower(), "items": items}
        if name == "Constraint":
            fields = {}
            for field, value in node[3]:
                if field is None or field.text not in {"required", "forbidden", "consistent"} or field.text in fields:
                    error(field or node[1], "invalid Constraint field")
                if field.text == "consistent":
                    fields[field.text] = expression(value, env)
                    if fields[field.text]["type"] != "b": error(value[1], "Constraint consistent must be b")
                else:
                    fields[field.text] = triple_value(value)
            return {"kind": "constraint_construct", "type": "constraint",
                    "required": fields.get("required"), "forbidden": fields.get("forbidden"),
                    "consistent": fields.get("consistent", {"kind": "literal", "type": "b", "value": True}),
                    "eval_order": [field.text for field, _ in node[3]]}
        if len(node[3]) not in {2, 3} or any(field is not None for field, _ in node[3][:2]):
            error(node[1], "interpret requires Candidates, Constraints, and optional budget")
        candidates, constraints = expression(node[3][0][1], env), expression(node[3][1][1], env)
        if candidates["type"] != "candidates" or constraints["type"] != "constraints": error(node[1], "interpret requires Candidates and Constraints")
        options = {}
        for field, value in node[3][2:]:
            if field is None or field.text != "budget" or "budget" in options: error(field or node[1], "interpret accepts one named budget")
            options[field.text] = expression(value, env)
        budget = options.get("budget", {"kind": "literal", "type": "si32", "value": 16384})
        if budget["type"] != "si32": error(node[1], "interpret budget must be si32")
        return {"kind": "interpret", "type": "interpretation", "candidates": candidates,
                "constraints": constraints, "budget": budget,
                "eval_order": ["candidates", "constraints"] + [field.text for field, _ in node[3][2:]]}

    if not (isinstance(callee, tuple) and len(callee) == 4 and callee[0] == "field"):
        return None
    receiver, method = callee[2], callee[3].text
    if receiver[0] != "name" or receiver[2] not in env:
        return None
    receiver_type = env[receiver[2]][0]

    def arguments(allowed):
        out = {}
        for field, value in node[3]:
            if field is None or field.text not in allowed or field.text in out:
                error(field or node[1], "invalid Horn call arguments")
            out[field.text] = value
        return out

    if receiver_type == "horn_plan" and method in {"select", "count", "exists", "status"}:
        # Preserve IR7's established lowering for literal queries.
        if method in {"select", "count"} and all(
            field is not None and value[0] == "literal"
            for field, value in node[3]
        ) and not any(field.text in {"limit", "proof_limit", "search_limit"}
                     for field, _ in node[3]):
            return None
        if method in {"exists", "status"}:
            args = node[3]
            if len(args) != 1 or args[0][0] is not None:
                error(node[1], "%s requires one Triple" % method)
            triple = args[0][1]
            if not (isinstance(triple, tuple) and len(triple) == 4 and triple[0] == "call"
                    and triple[2][0] == "name" and triple[2][2] == "Triple"):
                error(triple[1] if isinstance(triple, tuple) and len(triple) > 1 else node[1],
                      "%s requires Triple(subject, predicate, object)" % method)
            raw = triple[3]
            if len(raw) != 3 or any(field is not None for field, _ in raw):
                error(triple[1], "Triple requires three positional strings")
            terms = [expression(value, env) for _, value in raw]
            if any(value["type"] != "s" for value in terms):
                error(triple[1], "Triple terms must be strings")
            if method == "exists" and all(value["kind"] == "literal" for value in terms):
                return None
            return {"kind": "horn_call", "type": "b" if method == "exists" else "enum:EpistemicState",
                    "operation": method, "plan": expression(receiver, env),
                    "filters": dict(zip(("subject", "predicate", "object"), terms)), "limits": {},
                    "eval_order": ["plan", "subject", "predicate", "object"]}

        if node[3] and node[3][0][0] is None:
            triple = node[3][0][1]
            if not (len(node[3]) == 1 and isinstance(triple, tuple) and len(triple) == 4
                    and triple[0] == "call" and triple[2][0] == "name" and triple[2][2] == "Triple"):
                return None
            raw = triple[3]
            if len(raw) != 3 or any(field is not None for field, _ in raw):
                error(triple[1], "Triple requires three positional strings")
            terms = [expression(value, env) for _, value in raw]
            if any(value["type"] != "s" for value in terms):
                error(triple[1], "Triple terms must be strings")
            if all(value["kind"] == "literal" for value in terms): return None
            return {"kind": "horn_call", "type": "horn_snapshot" if method == "select" else "si32",
                    "operation": method, "plan": expression(receiver, env),
                    "filters": dict(zip(("subject", "predicate", "object"), terms)), "limits": {},
                    "eval_order": ["plan", "subject", "predicate", "object"]}

        args = arguments({"subject", "predicate", "object", "limit", "proof_limit", "search_limit"})
        filters, limits = {}, {}
        for key in ("subject", "predicate", "object"):
            if key in args:
                filters[key] = expression(args[key], env)
                if filters[key]["type"] != "s": error(args[key][1], "%s filter must be a string" % key)
        for key in ("limit", "proof_limit", "search_limit"):
            if key in args:
                limits[key] = expression(args[key], env)
                if limits[key]["type"] != "si32": error(args[key][1], "%s must be si32" % key)
        if method == "count" and limits: error(node[1], "count does not accept reasoning limits")
        return {"kind": "horn_call", "type": "horn_snapshot" if method == "select" else "enum:EpistemicState" if method == "status" else "si32",
                "operation": method, "plan": expression(receiver, env), "filters": filters, "limits": limits,
                "eval_order": ["plan"] + [field.text for field, _ in node[3]]}

    if receiver_type == "horn_plan" and method in {"withdraw", "replace", "supersede", "superseded_by", "history_fact"}:
        args = node[3]
        if method in {"withdraw", "superseded_by", "history_fact"}:
            if len(args) != 1 or args[0][0] is not None: error(node[1], "%s expects one fact ID" % method)
            identifier = expression(args[0][1], env)
            if identifier["type"] != "s": error(args[0][1][1], "fact ID must be s")
            if method == "withdraw" and not env[receiver[2]][1]: error(callee[2][1], "withdraw requires a mutable Horn plan")
            if method == "withdraw": return {"kind": "horn_history", "type": "b", "operation": method, "plan": expression(receiver, env), "id": identifier}
            if method == "history_fact": return {"kind": "horn_history", "type": "horn_snapshot", "operation": method, "plan": expression(receiver, env), "id": identifier}
            return {"kind": "horn_history", "type": "s", "operation": method, "plan": expression(receiver, env), "id": identifier}
        if not env[receiver[2]][1]: error(callee[2][1], "%s requires a mutable Horn plan" % method)
        if len(args) != 2 or any(field is not None for field, _ in args) or args[1][1][0] != "call" or args[1][1][2][0] != "name" or args[1][1][2][2] != "Fact":
            error(node[1], "%s expects an old ID and Fact(...)" % method)
        old_id = expression(args[0][1], env)
        if old_id["type"] != "s": error(args[0][1][1], "old fact ID must be s")
        fields = {}
        for field, value in args[1][1][3]:
            if field is None or field.text not in {"id", "subject", "predicate", "object", "polarity", "modality", "evidence"} or field.text in fields:
                error(field or args[1][1][1], "invalid replacement Fact fields")
            fields[field.text] = expression(value, env)
        if not {"id", "subject", "predicate", "object"} <= set(fields): error(args[1][1][1], "Fact requires id, subject, predicate, object")
        for key in ("id", "subject", "predicate", "object", "modality"):
            if key in fields and fields[key]["type"] != "s": error(args[1][1][1], "Fact %s must be a string" % key)
        if "polarity" in fields and fields["polarity"]["type"] != "b": error(args[1][1][1], "Fact polarity must be b")
        if "evidence" in fields and fields["evidence"]["type"] != "evidence": error(args[1][1][1], "Fact evidence must be Evidence")
        return {"kind": "horn_history", "type": "b", "operation": method, "plan": expression(receiver, env),
                "id": old_id, "fact": fields}

    if receiver_type == "horn_snapshot":
        signatures = {
            "fact_id": ("s", 1), "subject": ("s", 1), "predicate": ("s", 1),
            "object": ("s", 1), "fact_polarity": ("b", 1), "proof_count": ("si32", 1),
            "proof_id": ("s", 2), "proof_kind": ("s", 2), "proof_rule": ("s", 2),
            "proof_rule_version": ("s", 2), "proof_complete": ("b", 2),
            "proof_premise_count": ("si32", 2), "proof_binding_count": ("si32", 2),
            "proof_premise_id": ("s", 3), "proof_binding_name": ("s", 3),
            "proof_binding_value": ("s", 3),
        }
        signature = signatures.get(method)
        if signature is None: return None
        typ, count = signature
        if len(node[3]) != count or any(field is not None for field, _ in node[3]):
            error(node[1], "%s requires %d positional indices" % (method, count))
        indexes = [expression(value, env) for _, value in node[3]]
        if any(value["type"] != "si32" for value in indexes):
            error(node[1], "%s indices must be si32" % method)
        return {"kind": "horn_call", "type": typ, "operation": method,
                "snapshot": expression(receiver, env), "indexes": indexes}
    return None
