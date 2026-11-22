# -*- coding: utf-8 -*-
"""Generic comparison primitives.

A comparator answers one mechanical question about two nodes — are these spans
equal, is one a chunk-aligned suffix of the other, do these events share the
value of a role, is this value prefixed by a declared determiner.  It never
decides anything.  Whether a comparator's answer is sufficient, supporting,
insufficient on its own or blocking is stated in the policy records under
``graphs/core/``, and a comparator is reached from there by name.

Adding a comparator adds a primitive.  Changing what a cue is worth is a data
change.
"""

REGISTRY = {}


def comparator(name):
    def register(function):
        REGISTRY[name] = function
        return function
    return register


def run(name, context, left, right, args):
    try:
        function = REGISTRY[name]
    except KeyError:
        raise ValueError("no comparator named %r" % (name,))
    return function(context, left, right, args or {})


# -- mention comparators -------------------------------------------------

@comparator("exact_surface_equal")
def _exact_surface_equal(context, left, right, args):
    return left["span"] != right["span"] and left["surface"] == right["surface"]


@comparator("demonstrative_plus_surface")
def _demonstrative_plus_surface(context, left, right, args):
    forms = context.store.form_class(args.get("determiner_class", "demonstrative"))
    for form in forms:
        if left["surface"] == form + right["surface"]:
            return True
        if right["surface"] == form + left["surface"]:
            return True
    return False


@comparator("declared_alias_pair")
def _declared_alias_pair(context, left, right, args):
    return (left["surface"], right["surface"]) in context.aliases


@comparator("chunk_aligned_suffix")
def _chunk_aligned_suffix(context, left, right, args):
    long_side, short_side = left, right
    if len(left["surface"]) < len(right["surface"]):
        long_side, short_side = right, left
    if long_side["surface"] == short_side["surface"]:
        return False
    if not long_side["surface"].endswith(short_side["surface"]):
        return False
    offset = len(long_side["surface"]) - len(short_side["surface"])
    if offset <= 0:
        return False
    boundary = long_side["surface"][offset - 1]
    return boundary in set(context.store.mark_forms("space"))


@comparator("demonstrative_plus_class_form")
def _demonstrative_plus_class_form(context, left, right, args):
    determiners = context.store.form_class(args.get("determiner_class", "demonstrative"))
    nouns = context.store.form_class(args.get("noun_class", "generic_item"))
    pointer, target = right, left
    if target["span"][1] > pointer["span"][0]:
        pointer, target = left, right
    if target["span"][1] > pointer["span"][0]:
        return False
    surface = pointer["surface"]
    if not any(surface.startswith(form) for form in determiners):
        return False
    return any(surface.endswith(form) for form in nouns)


def _containment(left, right):
    """``(outer, inner)`` when one span strictly contains the other."""
    if left["span"] == right["span"]:
        return None
    if left["span"][0] <= right["span"][0] and right["span"][1] <= left["span"][1]:
        return left, right
    if right["span"][0] <= left["span"][0] and left["span"][1] <= right["span"][1]:
        return right, left
    return None


@comparator("determiner_head_containment")
def _determiner_head_containment(context, left, right, args):
    """The inner span is the outer span minus a declared determiner.

    그 부품 and the 부품 inside it are one thing; 생산 라인 책임자 and the
    생산 라인 inside it are not.  The difference is mechanical: the inner span
    ends where the outer one ends and everything before it is a determiner.
    """
    pair = _containment(left, right)
    if pair is None:
        return False
    outer, inner = pair
    if inner["span"][1] != outer["span"][1] or inner["span"][0] <= outer["span"][0]:
        return False
    prefix = outer["surface"][:inner["span"][0] - outer["span"][0]].strip()
    if not prefix:
        return False
    forms = context.store.form_class(args.get("determiner_class", "demonstrative"))
    return any(prefix == form.strip() for form in forms if form.strip())


@comparator("span_containment")
def _span_containment(context, left, right, args):
    if _containment(left, right) is None:
        return False
    if args.get("exclude_determiner_head") and _determiner_head_containment(
            context, left, right, args):
        return False
    return True


# -- event comparators ---------------------------------------------------

def _values(context, event, roles):
    found = {}
    for item in context.roles_of(event["id"]):
        if roles and item["role"] not in roles:
            continue
        found.setdefault(item["role"], []).append(item)
    return found


def _same_value(context, left_item, right_item):
    if left_item["value"] == right_item["value"]:
        return True
    left_entity = context.entity_of(left_item.get("mention"))
    right_entity = context.entity_of(right_item.get("mention"))
    return left_entity is not None and left_entity == right_entity


def _undecided_value(context, left_item, right_item, labels):
    """True when the two values are not the same and not yet distinguishable.

    A pointing expression whose head names no particular thing — 해당 항목 — is
    neither a match for an earlier value nor a conflict with it.  Treating it as
    a conflict is what split a continuation into two events and suppressed a
    fact that was already extracted.  Which identity cues leave a pair
    undecided is listed in the policy record, not here.
    """
    if not labels:
        return False
    left = context.mentions.get(left_item.get("mention"))
    right = context.mentions.get(right_item.get("mention"))
    if left is None or right is None:
        return False
    for record in context.store.of_kind("identity_evidence"):
        if record.get("label") not in labels:
            continue
        name = record.get("comparator")
        if name and run(name, context, left, right, record.get("comparator_args")):
            return True
    return False


@comparator("shared_role_value")
def _shared_role_value(context, left, right, args):
    roles = set(args.get("roles", ()))
    left_values = _values(context, left, roles)
    right_values = _values(context, right, roles)
    for role, items in left_values.items():
        for other in right_values.get(role, ()):
            for item in items:
                if item["value"] == other["value"]:
                    return True
    # the same thing can be the object of one clause and the checked thing of
    # another, so roles inside one declared group are compared across names too
    for items in left_values.values():
        for other_items in right_values.values():
            for item in items:
                for other in other_items:
                    if item["value"] == other["value"]:
                        return True
    return False


@comparator("shared_role_entity")
def _shared_role_entity(context, left, right, args):
    roles = set(args.get("roles", ()))
    for items in _values(context, left, roles).values():
        for other_items in _values(context, right, roles).values():
            for item in items:
                for other in other_items:
                    left_entity = context.entity_of(item.get("mention"))
                    right_entity = context.entity_of(other.get("mention"))
                    if left_entity is not None and left_entity == right_entity:
                        return True
    return False


@comparator("same_action")
def _same_action(context, left, right, args):
    return left["action"] == right["action"]


@comparator("unique_prior_same_action")
def _unique_prior_same_action(context, left, right, args):
    """Whether exactly one earlier clause describes the same action.

    Counted over clauses, not over events, because competing readings of one
    clause are not two prior happenings.  Counting events let reading
    multiplicity decide the cue: an extra ambiguous marker made a merge look
    unsupported, which is protection by accident rather than by evidence.
    """
    over = args.get("count_over", "clause")
    priors = [event for event in context.events
              if event["order"] < right["order"] and event["action"] == right["action"]
              and event["clause"] != right["clause"]]
    if over == "clause":
        groups = {event["clause"] for event in priors}
        return len(groups) == 1 and left["clause"] in groups
    return len(priors) == 1 and priors[0]["id"] == left["id"]


def _conflicting_roles(context, left, right, args):
    """Roles the two events fill with values that are decidably different."""
    undecided_labels = set(args.get("undecided_identity_evidence", ()))
    conflicts = []
    left_values = _values(context, left, ())
    right_values = _values(context, right, ())
    for role, items in sorted(left_values.items()):
        others = right_values.get(role)
        if not others:
            continue
        pairs = [(item, other) for item in items for other in others]
        if any(_same_value(context, item, other) for item, other in pairs):
            continue
        if any(_undecided_value(context, item, other, undecided_labels)
               for item, other in pairs):
            continue
        conflicts.append(role)
    return conflicts


@comparator("role_value_conflict")
def _role_value_conflict(context, left, right, args):
    return bool(_conflicting_roles(context, left, right, args))


@comparator("no_role_value_conflict")
def _no_role_value_conflict(context, left, right, args):
    return not _conflicting_roles(context, left, right, args)


@comparator("polarity_conflict")
def _polarity_conflict(context, left, right, args):
    return bool(left["polarity"]) != bool(right["polarity"])


@comparator("adjacent_segment")
def _adjacent_segment(context, left, right, args):
    return abs(left["segment_index"] - right["segment_index"]) <= 1


@comparator("demonstrative_plus_event_noun")
def _demonstrative_plus_event_noun(context, left, right, args):
    determiners = context.store.form_class(args.get("determiner_class", "demonstrative"))
    if not context.store.has(left["action"]):
        return False
    action = context.store.get(left["action"])
    nouns = tuple(action.get("event_nouns", ()))
    if not nouns:
        return False
    heads = {item["value"][len(form):] for item in context.roles_of(right["id"])
             for form in determiners if item["value"].startswith(form)} & set(nouns)
    return bool(heads) and not _event_head_rival(context, right, heads, args)


@comparator("demonstrative_subject")
def _demonstrative_subject(context, left, right, args):
    determiners = context.store.form_class(args.get("determiner_class", "demonstrative"))
    roles = set(args.get("roles", ()))
    for item in context.roles_of(right["id"]):
        if roles and item["role"] not in roles:
            continue
        if any(item["value"].startswith(form) for form in determiners):
            return True
    return False


def _pointed_heads(context, right, args):
    determiners = context.store.form_class(args.get("determiner_class", "demonstrative"))
    roles = set(args.get("roles", ()))
    for item in context.roles_of(right["id"]):
        if roles and item["role"] not in roles:
            continue
        for form in determiners:
            if item["value"].startswith(form):
                yield item["value"][len(form):]


@comparator("demonstrative_composed_stem")
def _demonstrative_composed_stem(context, left, right, args):
    analysis = left.get("predicate_analysis", {})
    if analysis.get("derivation", {}).get("grammar") != args.get("grammar"):
        return False
    heads = set(_pointed_heads(context, right, args)) & {analysis.get("lemma")}
    return bool(heads) and not _event_head_rival(context, right, heads, args)


def _event_head_rival(context, right, heads, args):
    # A prior role can name an entity with the same head. Preserve the rival.
    boundaries = context.store.mark_forms(args.get("head_boundary_mark", "space"))
    for event in context.events:
        if event["order"] >= right["order"]:
            continue
        for role in context.roles_of(event["id"]):
            if any(role["value"] == head or any(role["value"].endswith(boundary + head) for boundary in boundaries)
                   for head in heads):
                return True
    return False


@comparator("event_head_entity_rival")
def _event_head_entity_rival(context, left, right, args):
    heads = set(_pointed_heads(context, right, args)) & set(context.store.form_class(args["noun_class"]))
    return bool(heads) and _event_head_rival(context, right, heads, args)


@comparator("demonstrative_event_head")
def _demonstrative_event_head(context, left, right, args):
    heads = set(_pointed_heads(context, right, args)) & set(context.store.form_class(args["noun_class"]))
    return bool(heads) and not _event_head_rival(context, right, heads, args)


@comparator("demonstrative_nominal_entity_rival")
def _demonstrative_nominal_entity_rival(context, left, right, args):
    analysis = left.get("predicate_analysis", {})
    action = context.store.get(left["action"]) if context.store.has(left["action"]) else {}
    nouns = set(action.get("event_nouns", ()))
    if analysis.get("derivation", {}).get("grammar") == args.get("grammar"):
        nouns.add(analysis.get("lemma"))
    heads = set(_pointed_heads(context, right, args)) & nouns
    return bool(heads) and _event_head_rival(context, right, heads, args)
