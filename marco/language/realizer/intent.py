"""Utterance Intent: why each part is said.

The declared turn plans (``meaning.json: turn_plans``) map a turn — its act and
reason, or an answered fact — to an ordered list of acts from the declared set
(INFORM, ASK, WARN, CORRECT, REFUSE, REASSURE). Each act carries the
propositions it says; the plan builds them from the Meaning Graph's fields.
A turn no plan matches is not realized.
"""
import copy
import unicodedata

from marco.language.realizer import meaning as mg
from marco.language.realizer.packs import language, meaning_declarations


def _field(fields, path):
    value = fields
    for key in path.split(meaning_declarations()["field_path_separator"]):
        if not isinstance(value, dict) or key not in value:
            return None
        value = value[key]
    return value


def _typed(kind, value, source, holders=()):
    """A role value of the declared kind, from a field value."""
    if value is None:
        return None
    if kind == "owners":
        # Holders named by compound subjects (owner words, then item words): each said as its
        # owner. Two that share an owner are not told apart by it: no value.
        owners = [_split_subject(item, source, holders)[0] for item in value]
        if not owners or any(not owner for owner in owners) or len(set(owners)) != len(owners):
            return None
        return {"list": [mg.entity(owner, source, "agent") for owner in owners]}
    if kind == "numeral":
        return mg.number(value)
    if kind == "quote":
        return mg.quote(value)
    if kind == "relation":
        return {"relation": value}
    if kind in ("rule_id", "slot_id"):
        return {"id": value}
    if kind == "names":
        return {"list": [mg.entity(item, source, "agent") for item in value]}
    if kind == "quotes":
        return {"list": [mg.quote(item) for item in value]}
    if kind == "quote_pairs":
        return {"list": [{"source": pair.get("source", ""), "reading": pair.get("reading", "")} for pair in value]}
    if kind == "operations":
        return {"list": [dict(op) for op in value]}
    if kind == "name":
        return mg.entity(value, source, "agent")
    return mg.entity(value, source, kind)


def _matches(plan, graph):
    for key, wanted in plan["match"].items():
        if key == "source":
            if wanted == "fact" and not (graph.get("fact") and mg.fact_prop(
                    graph["fact"]["fact"], graph["source"]) is not None):
                return False
            continue
        if key == "checks_exclude":
            if set(wanted) & set(graph.get("checks", [])):
                return False
            continue
        if key == "kind":
            if graph["fields"].get("kind") != wanted:
                return False
            continue
        if key == "fields_has":
            # One field, or every field of a list, carries a value.
            names = wanted if isinstance(wanted, list) else [wanted]
            if any(graph["fields"].get(name) in (None, {}, [], "") for name in names):
                return False
            continue
        if key == "fields":
            # Each named field of the meaning block has exactly this value.
            if any(graph["fields"].get(name) != value for name, value in wanted.items()):
                return False
            continue
        if isinstance(wanted, list):
            if graph.get(key) not in wanted:
                return False
        elif graph.get(key) != wanted:
            return False
    return True


def _named_in(value, asked):
    """Whether the question's own words named this holder: each of its words begins a word the
    question said (a name with a suffix or a particle still names it). A pointer does not."""
    said = [word.lower() for word in str(asked).split()]
    words = str((value or {}).get("text", "")).lower().split()
    return bool(words) and all(any(token.startswith(word) for token in said) for word in words)


def _holders_named(prop, fields):
    """True when the question named the answer's holder itself, False when it did not
    (a pointer, no holder at all); None when the turn does not say what was asked."""
    if "asked" not in fields:
        return None
    asked = fields.get("asked")
    subject = asked[0] if isinstance(asked, list) and asked else None
    if not isinstance(subject, str) or subject.startswith(tuple(meaning_declarations().get("variable_marks", ()))):
        return False
    holders = meaning_declarations()["discourse"]["answer_ellipsis"].get("holder_roles", [])
    return all(_named_in(prop["roles"][role], subject) for role in holders if role in prop["roles"])


def _split_subject(subject, source, holders=()):
    """The engine's compound subject as (holder entity, item text or None)."""
    relation = meaning_declarations()["relations"]["count"]
    parts = mg._subject_roles(subject, relation["subject"], source, holders)
    holder_role, item_role = relation["subject"][0], relation["subject"][-1]
    return parts.get(holder_role), parts.get(item_role)


def _members(subjects, source, holders=()):
    """Holders and the one thing they all hold, from compound subjects; (None, None) otherwise."""
    split = [_split_subject(subject, source, holders) for subject in subjects or []]
    if len(split) < 2 or any(holder is None for holder, _item in split):
        return None, None
    items = {item for _holder, item in split}
    return [holder for holder, _item in split], (items.pop() if len(items) == 1 and None not in items else None)


def _compared(template, fields, source):
    """A total over several holders, which of two holders has more or fewer, or whether they
    hold the same number: from the subjects the engine's proof read, split into holders and the
    thing they hold. ``same_count`` says the number when it is the same; ``count`` says each
    holder's own count (the values the proof read, in the question's order)."""
    frame = template["frame"]
    kinds = meaning_declarations()["frames"][frame]["roles"]
    holders = mg.holder_keys(fields)
    if frame == "same_count":
        members, item = _members(fields.get("subjects"), source, holders)
        polarity = template.get("polarity", True)
        if members is None or (polarity and fields.get("value") is None):
            return []
        roles = {"members": _typed(kinds["members"], members, source)}
        if item:
            roles["item"] = mg.entity(item, source, kinds["item"])
        if polarity:
            roles["value"] = mg.number(fields["value"])
        return [{"frame": frame, "roles": roles, "polarity": polarity}]
    if frame == "count":
        subjects, values = fields.get("subjects") or [], fields.get("values") or []
        if len(subjects) < 2 or len(values) != len(subjects):
            return []
        props = [mg.fact_prop([subject, "count", value], source, holders=holders)
                 for subject, value in zip(subjects, values)]
        return props if all(prop is not None for prop in props) else []
    if frame == "total":
        split = [_split_subject(subject, source, holders) for subject in fields.get("subjects") or []]
        if len(split) < 2 or any(holder is None for holder, _item in split) or fields.get("value") is None:
            return []
        items = {item for _holder, item in split}
        roles = {"members": _typed(kinds["members"], [holder for holder, _item in split], source),
                 "value": mg.number(fields["value"])}
        if len(items) == 1 and None not in items:
            roles["item"] = mg.entity(items.pop(), source, kinds["item"])
        prop = {"frame": frame, "roles": roles, "polarity": True}
        if isinstance(fields.get("render"), list):
            prop["question_render"] = {"render": list(fields["render"]),
                                       "slot": meaning_declarations().get("total_slot")}
        return [prop]
    holder, item = _split_subject(fields.get("winner"), source, holders) if fields.get("winner") else (None, None)
    if holder is None:
        return []
    roles = {"winner": mg.entity(holder, source, kinds["winner"])}
    if item:
        roles["item"] = mg.entity(item, source, kinds["item"])
    return [{"frame": frame, "roles": roles, "polarity": True}]


def _event_props(time, source, holders=()):
    """The earlier event an answer is relative to (``meaning.time``): the one transfer its
    recorded changes make, composed; otherwise the user's own statement of it, quoted without
    its closing marks. No order, or nothing to say it with: none."""
    decl = meaning_declarations()
    order = time.get("order")
    if order not in (decl.get("time_orders") or ()):
        return []
    transfers = mg.transfer_props(time.get("changes") or [], source, holders)
    if len(transfers) == 1:
        prop = transfers[0]
        prop.pop("stated", None)
        return [prop]
    said = str(time.get("event") or "").strip()
    while said and unicodedata.category(said[-1]).startswith("P"):
        said = said[:-1].rstrip()
    if not said:
        return []
    frame = decl["time_event"]["quoted_frame"]
    return [{"frame": frame, "tense": "past", "polarity": True, "roles": {"said": mg.quote(said)}}]


def _row_value(ref, row, fields):
    """A value a row case names: the row's own field (``chain.row_mark``), a meaning field (``$``),
    or the value as written."""
    mark = meaning_declarations()["chain"]["row_mark"]
    if isinstance(ref, str) and ref.startswith(mark):
        return _field(row, ref[len(mark):])
    if isinstance(ref, str) and ref.startswith("$"):
        return _field(fields, ref[1:])
    return ref


def _row_matches(where, row):
    return all(row.get(key) == wanted for key, wanted in (where or {}).items())


def _rows(template, graph):
    """One proposition per row of a list field, by the first case the row matches
    (``meaning.json: chain``). A row no case covers, or without a value its case requires,
    says nothing."""
    decl = meaning_declarations()
    fields, source = graph["fields"], graph["source"]
    holders = mg.holder_keys(fields)
    rows = _field(fields, template["rows"][1:])
    props = []
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        case = next((c for c in template["cases"] if _row_matches(c.get("where"), row)), None)
        if case is None:
            continue
        values = {role: _row_value(ref, row, fields) for role, ref in (case.get("roles") or {}).items()}
        if any(values.get(role) in (None, [], "") for role in case.get("requires", [])):
            continue
        if "fact" in case:
            triple = [_row_value(ref, row, fields) for ref in case["fact"]]
            prop = mg.fact_prop(triple, source, holders=holders) if None not in triple else None
            if prop is None:
                continue
        else:
            kinds = decl["frames"][case["frame"]]["roles"]
            typed = {role: _typed(kinds.get(role, "any"), value, source, holders)
                     for role, value in values.items() if value not in (None, [], "")}
            if any(typed.get(role) is None for role in case.get("requires", [])):
                continue
            prop = {"frame": case["frame"], "polarity": case.get("polarity", True),
                    "roles": {role: value for role, value in typed.items() if value is not None}}
        prop.update({key: case[key] for key in ("tense", "sentence", "optional") if key in case})
        props.append(prop)
    return props


def _hold_reason(template, graph):
    """The reason a reply was held, in the templates ``chain.hold_reasons`` lists under its id;
    ``_default`` when there is no entry or the entry says nothing."""
    table = meaning_declarations()["chain"]["hold_reasons"]
    reason = _field(graph["fields"], template.get("reason", "$reason")[1:])
    for key in (reason, "_default"):
        templates = table.get(key) if isinstance(key, str) else None
        if not isinstance(templates, list):
            continue
        props = [prop for entry in templates for prop in _props(entry, graph)]
        if props:
            return props
    return []


def _reading_props(template, graph):
    """The readings of one ambiguous sentence (the list field ``readings`` names; each reading the
    state changes it would record), each as the one proposition it would add: its one transfer, or
    its one stated count or place. Fewer than two readings, a reading that is not one proposition,
    or two readings that say the same: none, so no choice is offered in part."""
    fields, source = graph["fields"], graph["source"]
    holders = mg.holder_keys(fields)
    readings = _field(fields, template["readings"][1:])
    if not isinstance(readings, list) or len(readings) < 2:
        return []
    props, seen = [], set()
    for reading in readings:
        rows = [row for row in (reading.get("changes") or []) if isinstance(row, dict)] \
            if isinstance(reading, dict) else []
        said = mg.transfer_props(rows, source, holders) or mg.change_props(rows, source, state=template["state"],
                                                                           holders=holders)
        if len(said) != 1:
            return []
        prop = said[0]
        prop.pop("stated", None)
        prop.pop("provenance", None)
        key = repr(sorted((role, sorted(value.items())) for role, value in prop["roles"].items()))
        if (prop["frame"], key) in seen:
            return []
        seen.add((prop["frame"], key))
        props.append(prop)
    return props


def _props(template, graph):
    decl = meaning_declarations()
    fields, source = graph["fields"], graph["source"]
    holders = mg.holder_keys(fields)
    if template.get("rows"):
        return _rows(template, graph)
    if template.get("readings"):
        return _reading_props(template, graph)
    if template.get("from") == "hold_reason":
        return _hold_reason(template, graph)
    if template.get("from") == "fact":
        row = graph["fact"]
        prop = mg.fact_prop(row["fact"], source, focus=template.get("focus"), evidence=row.get("evidence"),
                            holders=holders)
        if prop is not None:
            prop["answer"] = True
            named = _holders_named(prop, fields)
            if named is not None:
                prop["holder_named"] = named
            query = fields.get("query")
            if isinstance(fields.get("render"), list) and isinstance(query, list) and len(query) == 3:
                # The question declared how its answer is shaped (its counter, for a
                # counting language). Kept as the pack's own data; the grammar reads it.
                prop["question_render"] = {"render": list(fields["render"]), "slot": query[2]}
            if template.get("time"):
                time = _field(fields, template["time"][1:])
                events = _event_props(time, source, holders) if isinstance(time, dict) else []
                if not events:
                    return []
                # The state at an earlier time is said in the past, after the event it is relative to.
                prop["tense"] = "past"
                prop["subordinate"] = {"order": time.get("order"), "props": events}
        return [prop] if prop else []
    if template.get("from") == "compared":
        return _compared(template, fields, source)
    if template.get("from") == "repairs_full":
        spec = decl.get("repair_notes") or {}
        kinds = decl["frames"][spec.get("full_frame", "repair_note_full")]["roles"]
        return [{"frame": spec.get("full_frame", "repair_note_full"), "polarity": True, "tense": "past",
                 "roles": {role: _typed(kind, report.get(role), source) for role, kind in kinds.items()
                           if report.get(role) is not None}}
                for report in fields.get("repairs_full") or []]
    if template.get("from") == "changes":
        rows = [row for row in fields.get("changes") or [] if isinstance(row, dict)]
        # The state a turn leaves: one value per subject and relation, the last one its changes set.
        last = {(str(row.get("subject")), row.get("predicate")): index for index, row in enumerate(rows)}
        rows = [row for index, row in enumerate(rows) if last[(str(row.get("subject")), row.get("predicate"))] == index]
        props = mg.change_props(rows, source, state=template["state"], holders=holders)
        for prop in props:
            prop["new_only"] = bool(template.get("new_only"))
        return props
    if template.get("from") == "held_repairs":
        kinds = decl["frames"]["repair_held"]["roles"]
        return [{"frame": "repair_held", "polarity": False, "tense": "past",
                 "roles": {role: _typed(kind, report.get(role), source) for role, kind in kinds.items()
                           if report.get(role) is not None}} for report in graph.get("held_repairs") or []]
    if template.get("from") == "transfers":
        props = mg.transfer_props(fields.get("changes") or [], source, holders)
        for prop in props:
            prop["new_only"] = bool(template.get("new_only"))
        return props
    if template.get("split"):
        # A compound subject (holder words, then thing words) said as its two roles.
        holder, item = _split_subject(_field(fields, template["split"][1:]) or "", source, holders)
        if holder is None or not item:
            return []
        kinds = decl["frames"][template["frame"]]["roles"]
        prop = {"frame": template["frame"], "polarity": template.get("polarity", True),
                "roles": {"owner": mg.entity(holder, source, kinds["owner"]), "item": mg.entity(item, source, kinds["item"])}}
        return [dict(prop, **{key: template[key] for key in ("tense", "sentence") if key in template})]
    if template.get("each"):
        items = _field(fields, template["each"][1:]) or []
        kinds = decl["frames"][template["frame"]]["roles"]
        return [dict({"frame": template["frame"], "polarity": template.get("polarity", True),
                      "roles": {template["role"]: _typed(kinds[template["role"]], item, source)}},
                     **{key: template[key] for key in ("tense", "sentence", "optional") if key in template})
                for item in items]
    frame = template["frame"]
    kinds = decl["frames"][frame]["roles"]
    roles = {}
    for role, ref in (template.get("roles") or {}).items():
        value = _field(fields, ref[1:]) if isinstance(ref, str) and ref.startswith("$") else ref
        if value in (None, [], ""):
            if template.get("optional"):
                return []
            continue
        typed = _typed(kinds.get(role, "any"), value, source, holders)
        if typed is None:
            # A value its kind cannot carry (holders not told apart by their owners).
            if template.get("optional"):
                return []
            continue
        roles[role] = typed
    prop = {"frame": frame, "roles": roles, "polarity": template.get("polarity", True)}
    for key in ("tense", "sentence"):
        if key in template:
            prop[key] = template[key]
    return [prop]


def holder_of(text, graph):
    """What kind of holder ``text`` is (``meaning.json: holders``): the meaning block's own entry
    for it, or the speaker when it is the conversation language's declared first-person holder
    word (its pack's ``임자자리말``); None for a holder that is a bare name."""
    spec = meaning_declarations()["holders"]
    declared = graph["fields"].get(spec["field"])
    entry = declared.get(text) if isinstance(declared, dict) else None
    kinds = set(spec["kinds"])
    if isinstance(entry, dict) and entry.get("kind") in kinds:
        holder = {"kind": entry["kind"]}
        if entry.get("said"):
            holder["said"] = str(entry["said"])
        return holder
    first = language(graph["source"]).person()["first"]["holder"]
    if first and text == first:
        return {"kind": spec["speaker"]}
    return None


def _mark_holders(prop, graph):
    """Each entity of a proposition (and of a list role, and the holder words that begin a
    compound) carries what kind of holder it is, for the grammar to say it."""
    holders = mg.holder_keys(graph["fields"])
    for value in (prop.get("roles") or {}).values():
        entities = value.get("list", []) if isinstance(value, dict) and "list" in value else [value]
        for entity in entities:
            if not isinstance(entity, dict) or "text" not in entity:
                continue
            text = str(entity["text"])
            if entity.get("kind") == "compound":
                text = mg._subject_roles(text, ["owner", "item"], graph["source"], holders).get("owner") or ""
                if text:
                    entity["owner_text"] = text
            holder = holder_of(text, graph) if text else None
            if holder:
                entity["holder"] = holder
    for sub in (prop.get("subordinate") or {}).get("props") or []:
        _mark_holders(sub, graph)
    if prop.get("alternative"):
        _mark_holders(prop["alternative"], graph)


def _said_as_none(prop):
    """A count of zero is said as having none of the thing (``meaning.json: zero_count``): the
    none proposition first, the count itself as its alternative when the language cannot say
    none in words its pack reads back."""
    spec = meaning_declarations().get("zero_count") or {}
    value = (prop.get("roles") or {}).get(spec.get("value")) or {}
    if prop.get("frame") != spec.get("frame") or str(value.get("number")) != str(spec.get("zero")) \
            or prop.get("polarity", True) is not True:
        return prop
    none = {key: item for key, item in prop.items() if key != "roles"}
    none.update({"frame": spec["said_as"], "polarity": False, "alternative": prop,
                 "roles": {role: item for role, item in prop["roles"].items() if role != spec["value"]}})
    return none


def spoken_repairs(graph):
    """The repairs the reply says: at most the declared number, and only a reading that did
    more than the declared silent operations (a particle or an ending) — those change no meaning.
    Every repair stays in the trace in full."""
    spec = meaning_declarations().get("repair_notes") or {}
    silent = set(spec.get("silent_operations", []))
    said = [report for report in graph.get("repairs") or []
            if any(op.get("op") not in silent for op in report.get("operations") or [])]
    limit = spec.get("spoken_at_most")
    return said if limit is None else said[:limit]


def repair_props(graph):
    spec = meaning_declarations().get("repair_notes") or {}
    kinds = meaning_declarations()["frames"][spec.get("frame", "repair_note")]["roles"]
    props = []
    for report in spoken_repairs(graph):
        roles = {role: _typed(kind, report.get(role), graph["source"])
                 for role, kind in kinds.items() if report.get(role) is not None}
        props.append({"frame": spec["frame"], "roles": roles, "polarity": True})
    return props


def _plan_acts(chosen, graph):
    """The acts one plan says of one graph, each with the propositions its templates build. An act
    declared ``fallback`` is said only when no act before it said anything; an act declared
    ``options`` offers its propositions as the choices of one question."""
    acts = []
    for act in chosen["acts"]:
        if act.get("fallback") and acts:
            continue
        props = [prop for template in act["props"] for prop in _props(template, graph)]
        if not props:
            continue
        acts.append({"intent": act["intent"], "props": props, "conclusion": bool(act.get("conclusion")),
                     "lead": act.get("lead"), "lead_optional": bool(act.get("lead_optional")),
                     "options": bool(act.get("options"))})
    return acts


def _answers_acts(chosen, graph):
    """Several questions asked in one turn (Diairesis), from the list field the plan names
    (``each``): each answer is a meaning of its own, said in the order asked by the plan it would
    have alone, and each names whose it is; consecutive answers are one act, so the discourse
    planner joins them. None when any one of them has no plan: a turn is not said in part."""
    decl = meaning_declarations()
    fields = graph["fields"]
    items = _field(fields, chosen["each"][1:])
    if not isinstance(items, list) or not items:
        return None
    # The fields every answer shares with the turn (``shared``), and the fields of an answer that
    # are its answered fact's row (``answer_row``: the triple, then what it rests on).
    shared = {key: fields[key] for key in chosen.get("shared", []) if key in fields}
    acts = []
    for item in items:
        if not isinstance(item, dict):
            return None
        row = {key: copy.deepcopy(item[key]) for key in chosen.get("answer_row", []) if key in item}
        meaning = dict(shared, **{key: value for key, value in item.items() if key not in row and key != "status"})
        triple = row.get(chosen["answer_row"][0]) if chosen.get("answer_row") else None
        rows = [row] if isinstance(triple, list) and len(triple) == 3 else []
        sub = mg.build({"status": item.get("status"), "meaning": meaning, "transitions": rows}, graph["source"])
        own = next((p for p in decl["turn_plans"] if not p.get("each") and _matches(p, sub)), None)
        said = _plan_acts(own, sub) if own is not None else []
        if not said:
            return None
        for act in said:
            for prop in act["props"]:
                if prop.get("answer"):
                    # Two answers in one turn: each says whose it is.
                    prop["holder_named"] = False
        acts.extend(said)
    joined = []
    for act in acts:
        answers = all(prop.get("answer") for prop in act["props"])
        if joined and answers and not act.get("lead") and joined[-1]["intent"] == act["intent"] \
                and joined[-1].get("answers"):
            joined[-1]["props"].extend(act["props"])
            continue
        joined.append(dict(act, answers=answers))
    return joined


def plan(graph):
    """Fill ``graph["acts"]`` and ``graph["props"]``; return True when a plan matched."""
    decl = meaning_declarations()
    chosen = next((p for p in decl["turn_plans"] if _matches(p, graph)), None)
    if chosen is None:
        return False
    # A plan over several answers says each by its own plan; when one has none, the plan's own acts
    # (its declared fallback) are said instead: a turn is never said in part.
    acts = (_answers_acts(chosen, graph) or _plan_acts(chosen, graph)) if chosen.get("each") \
        else _plan_acts(chosen, graph)
    notes = repair_props(graph)
    if notes:
        spec = decl["repair_notes"]
        note_act = {"intent": spec["intent"], "props": notes, "conclusion": False, "lead": None, "notes": True}
        acts = [note_act] + acts if spec.get("position") == "first" else acts + [note_act]
    if not acts:
        return False
    for index, act in enumerate(acts):
        act["props"] = [_said_as_none(prop) for prop in act["props"]]
        for number, prop in enumerate(act["props"]):
            prop["id"] = f"p{index}_{number}"
            prop["intent"] = act["intent"]
            if prop.get("alternative"):
                prop["alternative"].update(id=prop["id"], intent=act["intent"])
            _mark_holders(prop, graph)
    graph["acts"] = acts
    graph["props"] = [copy.deepcopy(prop) for act in acts for prop in act["props"]]
    graph["plan"] = chosen.get("_about") or chosen["match"]
    graph["plan_match"] = copy.deepcopy(chosen["match"])
    return True
