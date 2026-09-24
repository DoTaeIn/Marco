"""Discourse Planner: what to say, what to leave out, in which order.

Rules come from ``meaning.json: discourse``:

* known facts — a fact the user stated in this turn is not repeated unless its
  reading added something not typed (ellipsis, repair, a resolved referent);
* answer ellipsis — an answer says its focus; the question already named the rest;
* repeated-role ellipsis — inside one utterance a role equal to the one in the
  previous clause of the same frame is not said again;
* conclusion first — an act marked as the conclusion comes before the reasons;
* coordination — consecutive clauses of one frame in one act share a sentence.

The planner decides content and ellipsis; how an elided role disappears is
the language's business (zero anaphora, fragment answer).
"""
from marco.language.realizer.packs import meaning_declarations


def _same(a, b):
    return isinstance(a, dict) and isinstance(b, dict) and a.get("text") == b.get("text") and a.get("text")


def plan(graph):
    """Sentences to realize, and the discourse counts of this turn."""
    rules = meaning_declarations()["discourse"]
    keep_when = set(rules.get("known_facts", {}).get("keep_when", []))
    counts = {"eligible_referents": 0, "elided_referents": 0, "known_facts": 0, "known_facts_repeated": 0,
              "known_facts_omitted": 0, "repeated_roles": 0, "repeated_roles_elided": 0}
    acts = list(graph["acts"])
    if rules.get("conclusion_first"):
        notes = [a for a in acts if a.get("notes")]
        first = [a for a in acts if a.get("conclusion") and not a.get("notes")]
        rest = [a for a in acts if not a.get("conclusion") and not a.get("notes")]
        acts = notes + first + rest
    answer_rule = rules.get("answer_ellipsis") or {}
    repeat_rule = rules.get("repeat_ellipsis") or {}
    coordinate = set((rules.get("coordinate") or {}).get("frames", []))
    sentences = []
    for act in acts:
        said = []
        for prop in act["props"]:
            if prop.get("new_only") and prop.get("stated"):
                counts["known_facts"] += 1
                if not keep_when & set(prop.get("marks", [])):
                    counts["known_facts_omitted"] += 1
                    continue
                counts["known_facts_repeated"] += 1
            said.append(prop)
        clauses = []
        previous = None
        for prop in said:
            elided = set()
            if prop.get("answer") and act["intent"] in answer_rule.get("intents", []) and prop.get("focus"):
                holders = set(answer_rule.get("holder_roles", []))
                for role in prop["roles"]:
                    if role in holders and prop.get("holder_named") is False:
                        # The question did not name this holder: the answer names it.
                        continue
                    if role != prop["focus"]:
                        counts["eligible_referents"] += 1
                        elided.add(role)
                        counts["elided_referents"] += 1
            holder_kinds = {((prop["roles"].get(role) or {}).get("holder") or {}).get("kind")
                            for role in answer_rule.get("holder_roles", [])}
            if previous is not None and previous["frame"] == prop["frame"] and prop["frame"] in repeat_rule.get(
                    "frames", []) and not holder_kinds & set(repeat_rule.get("not_for_holders", [])):
                for role in repeat_rule.get("roles", []):
                    if _same(prop["roles"].get(role), previous["roles"].get(role)):
                        counts["repeated_roles"] += 1
                        counts["repeated_roles_elided"] += 1
                        elided.add(role)
            clauses.append({"prop": prop, "elided": elided, "act": act["intent"]})
            previous = prop
        groups = []
        for clause in clauses:
            frame = clause["prop"]["frame"]
            if (groups and frame in coordinate and groups[-1][-1]["prop"]["frame"] == frame
                    and groups[-1][-1]["prop"].get("sentence", "declarative") == "declarative"):
                groups[-1].append(clause)
            else:
                groups.append([clause])
        lead = act.get("lead")
        if lead and (rules.get("lead_needs_change") or {}).get("on") and all(p.get("stated") for p in said):
            lead = None
        for index, group in enumerate(groups):
            sentences.append({"clauses": group, "act": act["intent"],
                              "sentence": group[0]["prop"].get("sentence", "declarative"),
                              "lead": lead if index == 0 else None,
                              "lead_optional": bool(act.get("lead_optional")),
                              # A lead that answers yes or no must agree with what its sentence says.
                              "polarity": group[0]["prop"].get("polarity", True)})
    return sentences, counts
