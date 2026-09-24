"""Meaning Graph: what the turn means, with no language in it.

Built from the dialogue's turn result. Two sources, both structure:

* the answered fact (the last ``{"fact": [s, p, v]}`` transition) and the
  recorded state changes (``quantity_update`` / ``state_update`` rows);
* the ``meaning`` block a turn result carries when the engine declares its
  act (request ``docs/requests/W1-1.md``): act, reason and the fields it names.

The finished sentence the engine built (``result["answer"]``) is never read.
Values are the user's own words, numbers, relation ids and rule ids.
"""
import copy

from marco.language.realizer.packs import language, meaning_declarations

SCHEMA = "marco-meaning-v1"


def entity(text, source, kind):
    return {"text": str(text), "lang": source, "kind": kind}


def number(value):
    return {"number": str(value)}


def quote(text):
    return {"quote": str(text)}


def holder_keys(fields):
    """The holder keys of several words the meaning block declares (``meaning.json: holders``),
    longest first: a compound subject that begins with one has that holder as its owner."""
    spec = meaning_declarations().get("holders") or {}
    declared = (fields or {}).get(spec.get("field")) if isinstance(fields, dict) else None
    joint = meaning_declarations()["compound_subject"]["separator"]
    keys = [key for key in (declared or {}) if isinstance(key, str) and len(key.split(joint)) > 1]
    return tuple(sorted(keys, key=len, reverse=True))


def _subject_roles(subject, roles, source, holders=()):
    """Split the engine's compound subject (owner words, then item words) into roles.

    The owner is the first word, or a declared holder key of several words the subject
    begins with (``holders``: a place or a named holder, ``holder_keys``)."""
    joint = meaning_declarations()["compound_subject"]["separator"]
    words = str(subject).split(joint)
    frame_roles = meaning_declarations()["frames"]
    if len(roles) == 1:
        return {roles[0]: joint.join(words)}
    for key in holders:
        size = len(key.split(joint))
        if len(roles) == 2 and len(words) > size and joint.join(words[:size]) == key:
            return {roles[0]: key, roles[1]: joint.join(words[size:])}
    if len(words) >= len(roles):
        head = words[:len(roles) - 1]
        return dict(zip(roles, head + [joint.join(words[len(roles) - 1:])]))
    # One word for a compound: a word the pack links to a thing concept is the
    # item; any other word is the owner. Nothing is guessed beyond that.
    thing_roles = [role for role in roles if _role_kind(frame_roles, role) == "thing"]
    other_roles = [role for role in roles if role not in thing_roles]
    target = thing_roles[0] if (language(source).concept(words[0]) and thing_roles) else other_roles[0]
    return {target: words[0]}


def _role_kind(frames, role):
    for frame in frames.values():
        if role in frame.get("roles", {}):
            return frame["roles"][role]
    return "any"


def fact_prop(triple, source, *, focus=None, evidence=None, polarity=True, holders=()):
    """A proposition from a state triple, or None when its relation is not declared."""
    decl = meaning_declarations()
    subject, predicate, value = triple
    relation = decl["relations"].get(predicate)
    if relation is None or not isinstance(subject, str) or value is None:
        return None
    frame = relation["frame"]
    kinds = decl["frames"][frame]["roles"]
    roles = {}
    for role, text in _subject_roles(subject, relation["subject"], source, holders).items():
        roles[role] = entity(text, source, kinds.get(role, "any"))
    object_role = relation["object"]
    roles[object_role] = (number(value) if kinds.get(object_role) == "numeral"
                          else entity(value, source, kinds.get(object_role, "any")))
    prop = {"frame": frame, "roles": roles, "polarity": polarity}
    if focus == "object":
        prop["focus"] = object_role
    if evidence is not None:
        prop["provenance"] = copy.deepcopy(evidence)
    return prop


def change_props(changes, source, *, state, holders=()):
    """The state each change leaves, one count/location proposition per changed subject."""
    props = []
    for row in changes:
        if row.get("operation") not in ("quantity_update", "state_update"):
            continue
        value = row.get(state)
        if value is None:
            continue
        prop = fact_prop([row.get("subject"), row.get("predicate"), value], source,
                         evidence=row.get("evidence"), holders=holders)
        if prop is None:
            continue
        evidence = row.get("evidence") or {}
        prop["stated"] = row.get("operation") == "state_update"
        marks = []
        if evidence.get("ellipsis"):
            marks.append("ellipsis")
        if (evidence.get("normalization") or {}).get("repair"):
            marks.append("repaired")
        if row.get("resolved_from"):
            marks.append("resolved")
        prop["marks"] = marks
        props.append(prop)
    return props


def transfer_props(changes, source, holders=()):
    """Changes that together are one transfer: one side loses what the other gains in one event."""
    spec = meaning_declarations()["quantity_effects"]
    kinds = meaning_declarations()["frames"][spec["frame"]]["roles"]
    groups = {}
    for row in changes:
        if row.get("operation") != "quantity_update" or not isinstance(row.get("delta"), (int, float)):
            continue
        evidence = row.get("evidence") or {}
        key = (evidence.get("source"), evidence.get("start"), evidence.get("end"), evidence.get("turn"))
        groups.setdefault(key, []).append(row)
    props = []
    for rows in groups.values():
        losing = [r for r in rows if r["delta"] < 0]
        gaining = [r for r in rows if r["delta"] > 0]
        if len(losing) != 1 or len(gaining) != 1 or -losing[0]["delta"] != gaining[0]["delta"]:
            continue
        pair = ["owner", "item"]
        giver = _subject_roles(losing[0]["subject"], pair, source, holders)
        receiver = _subject_roles(gaining[0]["subject"], pair, source, holders)
        if not (giver.get("owner") and receiver.get("owner") and giver.get("item")) \
                or giver["item"] != receiver.get("item"):
            continue
        amount = gaining[0]["delta"]
        amount = int(amount) if float(amount).is_integer() else amount
        props.append({"frame": spec["frame"], "tense": "past", "polarity": True,
                      "roles": {spec["loses"]: entity(giver["owner"], source, kinds[spec["loses"]]),
                                spec["gains"]: entity(receiver["owner"], source, kinds[spec["gains"]]),
                                spec["item"]: entity(giver["item"], source, kinds[spec["item"]]),
                                spec["amount"]: number(amount)},
                      "marks": ["resolved"] if any(r.get("resolved_from") for r in rows) else [],
                      "stated": True,
                      "provenance": copy.deepcopy(gaining[0].get("evidence"))})
    return props


def answered_fact(result):
    meaning = result.get("meaning") if isinstance(result.get("meaning"), dict) else {}
    query = meaning.get("query", ())
    if "query" in meaning and not (isinstance(query, list) and len(query) == 3):
        # A question no single triple asks (a sum, a comparison): the facts its
        # proof lists are what it read, not its answer.
        return None
    rows = [row for row in result.get("transitions") or [] if isinstance(row.get("fact"), list)
            and len(row["fact"]) == 3]
    return rows[-1] if rows else None


def answer_language(result, source):
    """A companion answer is said in the companion's language."""
    if result.get("meaning", {}).get("answer_language"):
        from marco.language.realizer.packs import stem_of
        return stem_of(result["meaning"]["answer_language"])
    if result.get("cross_language"):
        for check in (result.get("verification") or {}).get("checks", []):
            if check.get("reason") == "cross_language_question" and check.get("language"):
                from marco.language.realizer.packs import stem_of
                return stem_of(check["language"])
    return source


def build(result, source):
    """The Meaning Graph of one turn result. Props are filled by the intent layer's plan."""
    fields = copy.deepcopy(result.get("meaning") or {})
    row = answered_fact(result)
    return {"schema": SCHEMA, "source": source, "answer_language": answer_language(result, source),
            "status": result.get("status"), "fields": fields,
            "checks": sorted({c.get("reason") for c in (result.get("verification") or {}).get("checks", [])
                              if isinstance(c, dict) and c.get("reason")}),
            "act": fields.get("act"), "reason": fields.get("reason"),
            "fact": copy.deepcopy(row) if row else None,
            "repairs": [copy.deepcopy(report) for report in result.get("repair") or []
                        if report.get("status") == "repaired"],
            "held_repairs": [copy.deepcopy(report) for report in result.get("repair") or []
                             if report.get("status") == "over_bound"],
            "props": [], "acts": []}
