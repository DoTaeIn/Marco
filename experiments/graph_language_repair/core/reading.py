# -*- coding: utf-8 -*-
"""Orchestration: text in, reading graph out.

The order is chart, scope, clause solutions, mentions, identity, events, links,
and only then rows.  Each stage is allowed to produce nothing for part of the
text without stopping the stages after it, which is the whole point of the
partial-reading clause (CONTRACT C8).
"""
from experiments.graph_language_repair.core.chart import Chart, trim_span
from experiments.graph_language_repair.core.events import EventLinker
from experiments.graph_language_repair.core.graph_store import load_graphs
from experiments.graph_language_repair.core.identity import IdentityBuilder
from experiments.graph_language_repair.core.mentions import MentionTable
from experiments.graph_language_repair.core.rows import ProofBuilder, RowBuilder
from experiments.graph_language_repair.core.scope import ScopeBuilder
from experiments.graph_language_repair.core.solver import solve_region

READING_SCHEMA = "graph-language-repair-reading-v1"

_META_PREDICATES = ("in_claim", "scope_kind", "reporter", "reporter_mention", "frame",
                    "inherits_from", "mention_of", "surface", "contained_by", "name",
                    "same_event", "same_event_candidate", "verified_by",
                    "verified_by_candidate", "checks", "checks_candidate",
                    "inherited_scope", "competes_with")


class _Context(object):
    """What a comparator is allowed to look at."""

    def __init__(self, store, chart):
        self.store = store
        self.chart = chart
        self.aliases = store.alias_pairs()
        self.mentions = {}
        self.events = []
        self.entity_map = {}
        self.role_map = {}

    def roles_of(self, event_id):
        return self.role_map.get(event_id, ())

    def entity_of(self, mention_id):
        if mention_id is None:
            return None
        return self.entity_map.get(mention_id)


def read_text(text, extra_graphs=(), store=None):
    """The reading graph of one document.  Consumes only the text."""
    if not isinstance(text, str):
        raise TypeError("read_text needs a str")
    store = load_graphs(extra_graphs=extra_graphs) if store is None else store
    limits = store.limits()
    notes = []

    cap = limits.get("max_text_chars")
    if cap is not None and len(text) > cap:
        raise ValueError("the text is longer than max_text_chars (%d)" % (cap,))

    chart = Chart(text, store, limits)
    notes.extend(chart.notes)
    context = _Context(store, chart)

    scope_builder = ScopeBuilder(chart, store)
    claims, regions = scope_builder.build()
    table = MentionTable(chart, store, limits)

    drafts = []
    for region in regions:
        drafts.extend(solve_region(chart, store, region["span"], region["segment"],
                                   region["claim"], limits))

    scope_builder.apply_nonassertive_boundaries(drafts)

    for claim in claims:
        if claim["reporter_span"] is not None:
            mention = table.intern(claim["reporter_span"], None)
            claim["reporter_mention"] = mention["id"] if mention else None

    events, role_rows, readings, unresolved, dropped = _events(chart, store, table,
                                                               drafts, claims)
    unresolved.extend(_uncovered(chart, regions, drafts))
    mention_list = table.finish()
    context.mentions = {item["id"]: item for item in mention_list}

    identity = IdentityBuilder(store, mention_list, limits)
    entities, entity_of, ambiguities = identity.build(context)
    if identity.capped:
        notes.append("max_mention_pairs")
    if getattr(table, "capped", False):
        notes.append("max_nested_mentions_per_span")
    notes.extend(note for draft in drafts for note in draft.notes if note.startswith("max_"))
    context.entity_map = entity_of
    context.events = events
    for item in role_rows:
        context.role_map.setdefault(item["event"], []).append(item)

    events_by_id = {event["id"]: event for event in events}
    claims_by_id = {claim["id"]: claim for claim in claims}
    linker = EventLinker(store, limits)

    hypotheses = linker.link(context, events)
    if linker.capped:
        notes.append("max_event_pairs")
    completions = linker.completions(context, events_by_id, hypotheses)
    verifications = linker.verifications(context, events, claims_by_id)
    inherited = linker.inheritance(events_by_id, claims_by_id, hypotheses)

    identity_hypotheses = [{"kind": "entity_identity", "subjects": item["mentions"],
                            "status": item["status"], "rule": item["rule"],
                            "evidence": [{"kind": kind} for kind in item["evidence"]],
                            "blocked_by": list(item["blocked_by"]),
                            "ambiguity_rules": list(item["ambiguity_rules"]),
                            "spans": item["spans"],
                            "policy": "identity-policy:rules"}
                           for item in ambiguities]
    hypotheses = hypotheses + verifications + identity_hypotheses
    for index, hypothesis in enumerate(hypotheses):
        hypothesis["id"] = "hyp:%d" % index

    document = _emit(chart, store, limits, claims, events, role_rows, readings,
                     mention_list, entities, ambiguities, hypotheses, completions,
                     verifications, inherited, unresolved, dropped, notes, context)
    return document


def _uncovered(chart, regions, drafts):
    """Stretches of a region no clause reached.

    Text with no declared predicate is reported rather than ignored, and it
    does not stop the clauses that did solve (CONTRACT C8).
    """
    edges = tuple(chart.trim_forms) + tuple(chart.ender_forms)

    def gap(start, end):
        lo, hi = trim_span(chart.text, start, end, edges)
        return (lo, hi) if lo < hi else None

    covered = []
    for draft in drafts:
        start = min(draft.clause_span[0], draft.predicate["span"][0])
        covered.append((start, draft.predicate["span"][1]))
    found = []
    for region in regions:
        cursor = region["span"][0]
        for start, end in sorted(span for span in covered
                                 if span[0] < region["span"][1]
                                 and span[1] > region["span"][0]):
            if start > cursor:
                span = gap(cursor, start)
                if span:
                    found.append({"span": span, "reason": "no_predicate_match",
                                  "clause": None, "reading": None})
            cursor = max(cursor, end)
        if cursor < region["span"][1]:
            span = gap(cursor, region["span"][1])
            if span:
                found.append({"span": span, "reason": "no_predicate_match",
                              "clause": None, "reading": None})
    return found


def _predicate_typing(store, frame):
    default = None
    for record in store.of_kind("predicate_typing_policy"):
        if frame in record.get("frames", ()) or (frame is None and record.get("when_frame_absent")):
            return record
        if record.get("default"):
            default = record
    return default or {}


def _events(chart, store, table, drafts, claims):
    """Events and role rows, one event per surviving clause solution."""
    events, role_rows, readings, unresolved, dropped = [], [], [], [], []
    clause_ids = {}
    for position, draft in enumerate(drafts):
        clause_key = (draft.segment["id"], draft.predicate["span"], draft.claim_id)
        if clause_key not in clause_ids:
            clause_ids[clause_key] = "clause:%d" % len(clause_ids)
        clause_id = clause_ids[clause_key]
        hit = draft.predicate
        frame = store.get(hit["frame"]) if hit.get("frame") else {}
        construction = "construction:%s_%s" % (frame.get("key", "frame:unknown").split(":")[-1],
                                               hit["voice"])
        expected = tuple(frame.get("expected_roles", ()))
        typing = _predicate_typing(store, frame.get("key"))
        for item in draft.dropped:
            dropped.append({"clause": clause_id, "reason": item["reason"],
                            "policy": item["policy"],
                            "roles": [{"role": role, "value_span": list(span)}
                                      for role, span in item["roles"]],
                            "span": list(draft.clause_span)})
        solutions = draft.solutions or [None]
        sibling_ids = []
        for index, solution in enumerate(solutions):
            reading_id = "reading:%d" % len(readings)
            sibling_ids.append(reading_id)
            event_id = "event:%d" % len(events)
            claim_id = draft.claim_id
            if frame.get("emits_verification"):
                claim_id = _checking_claim(claims, claim_id, draft, hit)
            event = {"id": event_id, "order": len(events), "clause": clause_id,
                     "segment": draft.segment["id"],
                     "segment_index": draft.segment["index"],
                     "span": (draft.clause_span[0] if solution else hit["span"][0],
                              hit["span"][1]),
                     "action": hit["action"], "action_span": hit["span"],
                     "predicate_analysis": {key: hit[key] for key in ("lemma", "stem_span", "ending_span", "semantic_status", "derivation") if key in hit},
                     "voice": hit["voice"], "polarity": hit["polarity"],
                     "semantic_status": typing.get("semantic_status"),
                     "predicate_kind": typing.get("predicate_kind"),
                     "agency_status": typing.get("agency_status"),
                     "typing_policy": typing.get("key"),
                     "mood": hit["mood"], "frame": frame.get("key"),
                     "construction": construction, "claim": claim_id,
                     "reading": reading_id, "notes": list(draft.notes),
                     "emits_verification": bool(frame.get("emits_verification")),
                     "expected_roles": list(expected),
                     "inherited_claim": None,
                     "filled_by_completion": [],
                     "rival_roles": list(solution.get("rival_roles", ()) if solution else ()),
                     "checking_occurrence": None,
                     "checking_result": None,
                     "result_form_hits": [],
                     "result_conflict": []}
            present = []
            if solution:
                for item in solution["roles"]:
                    mention = table.intern(item["value_span"], draft.segment["id"])
                    if mention is None:
                        continue
                    present.append(item["role"])
                    role_rows.append({"event": event_id, "role": item["role"],
                                      "mention": mention["id"],
                                      "value_span": mention["span"],
                                      "value": mention["surface"],
                                      "marker": item["marker"],
                                      "marker_span": item["marker_span"],
                                      "marker_class": item["marker_class"],
                                      "grammatical_role": typing.get("marker_grammatical_roles", {}).get(item["marker_class"]),
                                      "semantic_role": (item["role"] if typing.get("roles_assert_semantics") else None),
                                      "role_interpretation": typing.get("role_interpretation"),
                                      "typing_policy": typing.get("key"),
                                      "grammatical_interpretation": typing.get("grammatical_row_interpretation"),
                                      "construction": construction,
                                      "reading": reading_id,
                                      "source": "clause", "proof": None,
                                      "derivation_policy": item.get("derivation_policy"),
                                      "from_event": None})
                for item in solution["unused"]:
                    unresolved.append({"span": item["value_span"],
                                       "reason": item["reason"],
                                       "clause": clause_id, "reading": reading_id})
            else:
                unresolved.append({"span": draft.clause_span
                                   if draft.clause_span[0] < draft.clause_span[1]
                                   else hit["span"],
                                   "reason": draft.notes[0] if draft.notes else "no_solution",
                                   "clause": clause_id, "reading": reading_id})
            if event["emits_verification"]:
                bound = [item["value_span"] for item in role_rows
                         if item["event"] == event_id]
                _checking_channels(chart, store, hit, draft, event, bound)
            event["missing_roles"] = [role for role in expected if role not in present]
            event["complete"] = not event["missing_roles"]
            events.append(event)
            reason = "clause_solution_%d" % index
            if event["rival_roles"]:
                reason = "rival_role_binding:%s" % ",".join(event["rival_roles"])
            readings.append({"id": reading_id, "status": "surviving", "clause": clause_id,
                             "events": [event_id], "competes_with": [],
                             "reason": reason})
        if len(sibling_ids) > 1:
            for reading in readings:
                if reading["clause"] == clause_id:
                    reading["competes_with"] = [other for other in sibling_ids
                                                if other != reading["id"]]
    for reading in readings:
        reading["competes_with"] = [other["id"] for other in readings
                                    if other["clause"] == reading["clause"]
                                    and other["id"] != reading["id"]]
    return events, role_rows, readings, unresolved, dropped


def _checking_channels(chart, store, hit, draft, event, bound_spans):
    """Fill the occurrence and result channels of a checking clause.

    Occurrence comes from the predicate's polarity.  A result comes only from a
    declared result form that is *structurally attached* to the checking
    construction: it must begin a chunk, end at a declared boundary or at the
    predicate, and not lie inside a span already bound as a role value.  A name
    that merely contains a result form is not a finding.  Where a positive and
    a negative form both qualify the result is withheld and the competitors are
    recorded, rather than letting whichever class sorts first win.
    """
    policy = store.get("verification:rules")
    occurrence = policy.get("occurrence_from_polarity", {}).get(
        "true" if hit["polarity"] else "false")
    event["checking_occurrence"] = occurrence
    if occurrence != policy.get("requires_occurrence"):
        event["checking_result"] = policy.get("result_when_not_performed", "unstated")
        return
    region = (min(draft.clause_span[0], hit["span"][0]), hit["span"][1])
    attachment = policy.get("result_form_attachment", {})
    starts = set(chart.chunk_starts_within(region))
    hits = []
    for class_name, value in sorted(policy.get("result_from_form_class", {}).items()):
        for form in store.form_class(class_name):
            index = chart.text.find(form, region[0], region[1])
            while index != -1:
                end = index + len(form)
                if _result_form_attached(chart, index, end, region, hit, starts,
                                         bound_spans, attachment):
                    hits.append({"class": class_name, "value": value,
                                 "span": (index, end), "form": form})
                index = chart.text.find(form, index + 1, region[1])
    event["result_form_hits"] = hits
    values = sorted({item["value"] for item in hits})
    if not values:
        event["checking_result"] = policy.get("result_default", "unstated")
    elif len(values) == 1:
        event["checking_result"] = values[0]
    else:
        event["checking_result"] = policy.get("on_competing_result_forms", "unstated")
        event["result_conflict"] = [dict(item, span=list(item["span"])) for item in hits]


def _result_form_attached(chart, start, end, region, hit, starts, bound_spans, attachment):
    if attachment.get("must_start_at_chunk_start") and start not in starts:
        return False
    if attachment.get("must_end_at_declared_boundary"):
        if end < region[1] and end != hit["span"][0]:
            follower = chart.text[end:end + 1]
            if follower not in set(chart.boundary_forms):
                return False
    if attachment.get("must_not_overlap_a_role_value"):
        for value_start, value_end in bound_spans:
            if start < value_end and value_start < end:
                return False
    return True


def _checking_claim(claims, claim_id, draft, hit):
    """A verification-eligible claim for a checking clause stated directly."""
    parent = None
    for claim in claims:
        if claim["id"] == claim_id:
            parent = claim
    if parent is None or parent["kind"] != "direct_text":
        return claim_id
    span = (draft.clause_span[0], hit["span"][1])
    for claim in claims:
        if claim["kind"] == "checking_action" and claim["span"] == span:
            return claim["id"]
    claim = {"id": "claim:%d" % len(claims), "kind": "checking_action", "span": span,
             "frame": None, "reporter_span": None, "reporter_mention": None,
             "inherits_from": claim_id, "policy": "scope:checking_action"}
    claims.append(claim)
    return claim["id"]


def _emit(chart, store, limits, claims, events, role_rows, readings, mention_list,
          entities, ambiguities, hypotheses, completions, verifications, inherited,
          unresolved, dropped, notes, context):
    builder = RowBuilder(limits)
    proofs = ProofBuilder()
    claims_by_id = {claim["id"]: claim for claim in claims}
    events_by_id = {event["id"]: event for event in events}

    for item in inherited:
        event = events_by_id[item["event"]]
        event["inherited_claim"] = item["claim"]

    def kind_of(claim_id):
        return claims_by_id[claim_id]["kind"]

    def content_claim(event):
        return event["inherited_claim"] or event["claim"]

    for claim in claims:
        builder.add([claim["id"], "scope_kind", claim["kind"]], "claim:0",
                    [claim["span"]], layer="meta", scope_kind=claim["kind"],
                    proof=None)
        if claim["frame"]:
            builder.add([claim["id"], "frame", claim["frame"]], "claim:0",
                        [claim["span"]], layer="meta", scope_kind=claim["kind"])
        if claim["reporter_span"] is not None:
            builder.add([claim["id"], "reporter", chart.value(claim["reporter_span"])],
                        "claim:0", [claim["reporter_span"]], layer="meta",
                        scope_kind=claim["kind"])
        if claim["reporter_mention"]:
            builder.add([claim["id"], "reporter_mention", claim["reporter_mention"]],
                        "claim:0", [claim["reporter_span"]], layer="meta",
                        scope_kind=claim["kind"])
        if claim["inherits_from"]:
            builder.add([claim["id"], "inherits_from", claim["inherits_from"]], "claim:0",
                        [claim["span"]], layer="meta", scope_kind=claim["kind"])

    # Every content row of an event depends on that event's action and
    # polarity rows.  A role value alone does not establish that the event
    # happened, so following a role answer's provenance has to reach the row
    # that says whether it did.
    occurrence_rows = {}
    for event in events:
        claim_id = content_claim(event)
        action_row = builder.add([event["id"], "action", event["action"]], claim_id,
                                 [event["action_span"]], polarity=event["polarity"],
                                 construction=event["construction"],
                                 semantic_status=event["semantic_status"],
                                 predicate_kind=event["predicate_kind"],
                                 agency_status=event["agency_status"],
                                 typing_policy=event["typing_policy"],
                                 reading=event["reading"], scope_kind=kind_of(claim_id))
        builder.add([event["id"], "action_type", event["action"]], "claim:0",
                    [event["action_span"]], layer="meta", reading=event["reading"],
                    semantic_status=event["semantic_status"],
                    predicate_kind=event["predicate_kind"], agency_status=event["agency_status"],
                    typing_policy=event["typing_policy"],
                    construction=event["construction"], scope_kind=kind_of(claim_id))
        builder.add([event["id"], "predicate_semantic_status", event["semantic_status"]],
                    "claim:0", [event["action_span"]], layer="meta",
                    reading=event["reading"], scope_kind=kind_of(claim_id),
                    typing_policy=event["typing_policy"])
        builder.add([event["id"], "agency_status", event["agency_status"]],
                    "claim:0", [event["action_span"]], layer="meta",
                    reading=event["reading"], scope_kind=kind_of(claim_id),
                    typing_policy=event["typing_policy"])
        builder.add([event["id"], "voice", event["voice"]], claim_id,
                    [event["action_span"]], construction=event["construction"],
                    reading=event["reading"], scope_kind=kind_of(claim_id))
        polarity_row = builder.add(
            [event["id"], "polarity", "true" if event["polarity"] else "false"],
            claim_id, [event["action_span"]], construction=event["construction"],
            reading=event["reading"], scope_kind=kind_of(claim_id))
        occurrence_rows[event["id"]] = [row["id"] for row in (action_row, polarity_row)
                                        if row is not None]
        builder.add([event["id"], "in_claim", event["claim"]], "claim:0",
                    [event["span"]], layer="meta", reading=event["reading"],
                    scope_kind=kind_of(event["claim"]))

    for item in role_rows:
        event = events_by_id[item["event"]]
        claim_id = content_claim(event)
        spans = [item["value_span"]]
        if item["marker_span"]:
            spans.append(item["marker_span"])
        adjunct_proof = None
        if item.get("derivation_policy"):
            adjunct_proof = proofs.add("construction_element", item["derivation_policy"], spans,
                                       "A declared boundary-attached form supports this role.")
        row = builder.add([item["event"], item["role"], item["value"]], claim_id, spans,
                          proof=adjunct_proof["id"] if adjunct_proof else None,
                          construction=item["construction"], reading=item["reading"],
                          scope_kind=kind_of(claim_id), mention=item["mention"],
                          grammatical_role=item.get("grammatical_role"),
                          semantic_role=item.get("semantic_role"),
                          role_interpretation=item.get("role_interpretation"),
                          typing_policy=item.get("typing_policy"),
                          value_span=item["value_span"], source=item["source"],
                          depends_on=occurrence_rows.get(item["event"], ()))
        item["row"] = row["id"] if row else None
        if adjunct_proof and row:
            adjunct_proof["rows"].append(row["id"])
            item["proof"] = adjunct_proof["id"]
        if row and item.get("grammatical_role"):
            grammatical_proof = proofs.add(
                "grammatical_role", item["typing_policy"], spans,
                "A marker class identifies a grammatical role, without asserting agency.",
                rows=[row["id"]])
            grammatical_row = builder.add(
                [item["event"], item["grammatical_role"], item["value"]], claim_id, spans,
                construction=item["construction"], reading=item["reading"],
                scope_kind=kind_of(claim_id), mention=item["mention"],
                value_span=item["value_span"], source="grammatical_alias",
                grammatical_role=item["grammatical_role"], semantic_role=None,
                role_interpretation=item.get("grammatical_interpretation"),
                typing_policy=item["typing_policy"],
                proof=grammatical_proof["id"],
                depends_on=[row["id"]] + list(occurrence_rows.get(item["event"], ())))
            if grammatical_row:
                grammatical_proof["rows"].append(grammatical_row["id"])

    for item in completions:
        event = events_by_id[item["event"]]
        claim_id = content_claim(event)
        if item["role"] not in event["filled_by_completion"]:
            event["filled_by_completion"].append(item["role"])
        proof = proofs.add(item["proof_kind"], item["policy"], item["spans"],
                           "role %s of %s is filled from %s on an accepted link; both "
                           "spans are retained" % (item["role"], item["event"],
                                                   item["from_event"]))
        completion_typing = _predicate_typing(store, event["frame"])
        interpretation = completion_typing.get("role_interpretation")
        semantic_role = item["role"] if completion_typing.get("roles_assert_semantics") else None
        row = builder.add([item["event"], item["role"], item["value"]], claim_id,
                          item["spans"], semantic_role=semantic_role,
                          role_interpretation=interpretation, grammatical_role=None,
                          typing_policy=completion_typing.get("key"),
                          construction=event["construction"],
                          reading=event["reading"], scope_kind=kind_of(claim_id),
                          mention=item["mention"], value_span=item["value_span"],
                          source="role_completion", proof=proof["id"],
                          depends_on=(list(occurrence_rows.get(item["event"], ()))
                                      + list(occurrence_rows.get(item["from_event"], ()))),
                          hypotheses=[item["hypothesis"]["id"]])
        if row:
            proof["rows"].append(row["id"])
            role_rows.append({"event": item["event"], "role": item["role"],
                              "mention": item["mention"], "value_span": item["value_span"],
                              "value": item["value"], "marker": item["marker"],
                              "marker_span": item["marker_span"], "marker_class": None,
                              "construction": event["construction"],
                              "grammatical_role": None, "semantic_role": semantic_role,
                              "role_interpretation": interpretation,
                              "typing_policy": completion_typing.get("key"),
                              "reading": event["reading"], "source": "role_completion",
                              "proof": proof["id"], "from_event": item["from_event"],
                              "row": row["id"]})

    for item in inherited:
        event = events_by_id[item["event"]]
        proof = proofs.add(item["proof_kind"], item["policy"], item["spans"],
                           "%s is the same event as %s, which is stated inside %s, so its "
                           "content rows are attributed there; the report is not promoted "
                           "to direct text" % (item["event"], item["from_event"],
                                               item["claim"]))
        row = builder.add([item["event"], "inherited_scope", item["claim"]], "claim:0",
                          item["spans"], layer="meta", reading=event["reading"],
                          scope_kind=item["scope_kind"], proof=proof["id"],
                          hypotheses=[item["hypothesis"]["id"]])
        if row:
            proof["rows"].append(row["id"])

    role_value_mentions = {item["mention"] for item in role_rows if item.get("mention")}
    entity_of = context.entity_map
    multi = {item["id"] for item in entities if len(item["mentions"]) > 1}
    for mention in mention_list:
        entity_id = entity_of.get(mention["id"])
        if mention["id"] not in role_value_mentions and entity_id not in multi:
            continue
        builder.add([mention["id"], "surface", mention["surface"]], "claim:0",
                    [mention["span"]], layer="meta")
        if entity_id:
            builder.add([mention["id"], "mention_of", entity_id], "claim:0",
                        [mention["span"]], layer="meta")
            builder.add([entity_id, "name", mention["surface"]], "claim:0",
                        [mention["span"]], layer="meta")
        for outer in mention["contained_by"]:
            if outer in role_value_mentions or entity_of.get(outer) in multi:
                builder.add([mention["id"], "contained_by", outer], "claim:0",
                            [mention["span"], context.mentions[outer]["span"]],
                            layer="meta")

    link_names = {"accepted": "same_event", "candidate": "same_event_candidate"}
    verify_names = {"accepted": ("verified_by", "checks"),
                    "candidate": ("verified_by_candidate", "checks_candidate")}
    pending_results = []
    for hypothesis in hypotheses:
        if hypothesis["kind"] == "event_link":
            name = link_names.get(hypothesis["status"])
            if name is None:
                continue
            left, right = hypothesis["subjects"]
            for one, other in ((left, right), (right, left)):
                builder.add([one, name, other], "claim:0", hypothesis["spans"],
                            layer="meta", hypotheses=[hypothesis["id"]])
        elif hypothesis["kind"] == "verification":
            target, check = hypothesis["subjects"]
            if store.get("verification:rules").get("record_target_scope"):
                builder.add([check, "checks_target_scope", hypothesis["target_scope"]],
                            "claim:0", hypothesis["spans"], layer="meta",
                            hypotheses=[hypothesis["id"]])
            names = verify_names.get(hypothesis["status"])
            if names is None:
                continue
            builder.add([target, names[0], check], "claim:0", hypothesis["spans"],
                        layer="meta", hypotheses=[hypothesis["id"]])
            link_row = builder.add([check, names[1], target], "claim:0", hypothesis["spans"],
                                   layer="meta", hypotheses=[hypothesis["id"]])
            pending_results.append((hypothesis, link_row))

    outcome_rows = {}
    for event in events:
        if not event["emits_verification"]:
            continue
        claim_id = content_claim(event)
        # Both rows are value-encoded and positive: they state what the text
        # says about the check, so a question can reach them.  The action's own
        # negation stays in [event, 'action', ...] with polarity false and in
        # [event, 'polarity', 'false'].
        builder.add([event["id"], "checking_occurred", event["checking_occurrence"]],
                    claim_id, [event["action_span"]],
                    construction=event["construction"], reading=event["reading"],
                    scope_kind=kind_of(claim_id),
                    depends_on=occurrence_rows.get(event["id"], ()))
        outcome_spans = [event["action_span"]] + [item["span"] for item in event["result_form_hits"]]
        outcome_rows[event["id"]] = builder.add(
                    [event["id"], "checking_outcome", event["checking_result"]],
                    claim_id, outcome_spans,
                    construction=event["construction"], reading=event["reading"],
                    scope_kind=kind_of(claim_id),
                    depends_on=occurrence_rows.get(event["id"], ()))

    # Independent-result provenance names both the target binding and the
    # check outcome.  The check outcome itself cites the exact result forms.
    for hypothesis, link_row in pending_results:
        target, check = hypothesis["subjects"]
        outcome = outcome_rows.get(check)
        dependencies = ([link_row["id"]] if link_row else [])
        if outcome:
            dependencies.append(outcome["id"])
        dependencies.extend(occurrence_rows.get(target, ()))
        spans = list(hypothesis["spans"])
        if outcome:
            spans.extend(outcome["spans"])
        proof = proofs.add("independent_result", hypothesis["policy"], spans,
                           "Target binding and checking outcome support this result.",
                           rows=dependencies)
        row = builder.add([target, "independent_result", hypothesis["independent_result"]],
                          "claim:0", spans, layer="meta", proof=proof["id"],
                          depends_on=dependencies, hypotheses=[hypothesis["id"]])
        if row:
            proof["rows"].append(row["id"])

    multi_fill = set()
    for event in events:
        frame = store.get(event["frame"]) if event["frame"] else {}
        for role in frame.get("multi_fill_roles", ()):
            multi_fill.add((event["id"], role))
    contradictions = _contradictions(builder.rows, events_by_id, hypotheses, readings,
                                     context, multi_fill, store)
    for event in events:
        if not event["result_conflict"]:
            continue
        contradictions.append({"id": "contra:%d" % len(contradictions),
                               "kind": "competing_result_forms",
                               "rows": [row["id"] for row in builder.rows
                                        if row["triple"][0] == event["id"]
                                        and row["triple"][1] == "checking_outcome"],
                               "spans": [item["span"] for item in event["result_conflict"]],
                               "readings": [event["reading"]]})

    if builder.capped:
        notes.append("max_rows")

    return {"schema": READING_SCHEMA,
            "text": chart.text,
            "segments": [{"id": segment["id"], "span": list(segment["span"])}
                         for segment in chart.segments],
            "mentions": [{"id": item["id"], "span": list(item["span"]),
                          "surface": item["surface"], "segment": item["segment"],
                          "contains": list(item["contains"]),
                          "contained_by": list(item["contained_by"])}
                         for item in mention_list],
            "entities": [{"id": item["id"], "mentions": list(item["mentions"]),
                          "evidence": item["evidence"]} for item in entities],
            "entity_ambiguity": [{"mentions": item["mentions"],
                                  "spans": [list(span) for span in item["spans"]],
                                  "candidates": item["candidates"],
                                  "evidence": item["evidence"],
                                  "status": item["status"],
                                  "rule": item["rule"],
                                  "blocked_by": list(item["blocked_by"]),
                                  "ambiguity_rules": list(item["ambiguity_rules"])}
                                 for item in ambiguities],
            "events": [_public_event(event) for event in events],
            "roles": [{"event": item["event"], "role": item["role"],
                       "mention": item["mention"],
                       "value_span": list(item["value_span"]), "value": item["value"],
                       "marker": item["marker"],
                       "marker_span": list(item["marker_span"]) if item["marker_span"] else None,
                       "construction": item["construction"], "reading": item["reading"],
                       "source": item["source"], "proof": item["proof"],
                       "grammatical_role": item.get("grammatical_role"),
                       "semantic_role": item.get("semantic_role"),
                       "role_interpretation": item.get("role_interpretation"),
                       "typing_policy": item.get("typing_policy"),
                       "from_event": item["from_event"], "row": item.get("row")}
                      for item in role_rows],
            "claims": [{"id": item["id"], "kind": item["kind"], "span": list(item["span"]),
                        "frame": item["frame"],
                        "reporter_span": list(item["reporter_span"]) if item["reporter_span"] else None,
                        "reporter": chart.value(item["reporter_span"]) if item["reporter_span"] else None,
                        "reporter_mention": item["reporter_mention"],
                        "inherits_from": item["inherits_from"],
                        "policy": item["policy"]} for item in claims],
            "event_claims": [{"event": event["id"], "claim": content_claim(event),
                              "stated_in": event["claim"],
                              "inherited": event["inherited_claim"]} for event in events],
            "hypotheses": [{"id": item["id"], "kind": item["kind"], "status": item["status"],
                            "subjects": list(item["subjects"]), "rule": item.get("rule"),
                            "policy": item.get("policy"),
                            "evidence": item["evidence"],
                            "blocked_by": list(item.get("blocked_by") or ()),
                            "spans": [list(span) for span in item["spans"]],
                            "ambiguity_rules": list(item.get("ambiguity_rules") or ()),
                            "occurrence": item.get("occurrence"),
                            "result": item.get("result"),
                            "independent_result": item.get("independent_result"),
                            "target_scope": item.get("target_scope")}
                           for item in hypotheses],
            "readings": [{"id": item["id"], "status": item["status"], "clause": item["clause"],
                          "events": list(item["events"]),
                          "competes_with": list(item["competes_with"]),
                          "reason": item["reason"]} for item in readings],
            "rows": [_public_row(row) for row in builder.rows],
            "proofs": [{"id": item["id"], "kind": item["kind"], "policy": item["policy"],
                        "spans": [list(span) for span in item["spans"]],
                        "because": item["because"], "rows": list(item["rows"])}
                       for item in proofs.proofs],
            "contradictions": contradictions,
            "dropped_readings": list(dropped),
            "unresolved": [{"span": list(item["span"]), "reason": item["reason"],
                            "clause": item.get("clause"), "reading": item.get("reading")}
                           for item in unresolved],
            "coverage": {"segments": len(chart.segments),
                         "clauses": len({event["clause"] for event in events}),
                         "events": len(events),
                         "regions_without_predicate": len(
                             [item for item in unresolved
                              if item["reason"] == "no_predicate_match"]),
                         "unsupported_spans": [list(item["span"]) for item in unresolved
                                               if item["reason"] == "no_predicate_match"]},
            "limits": {"applied": limits, "notes": sorted(set(notes)),
                       "complete": not bool(notes),
                       "graph_files": list(store.files)}}


def _public_event(event):
    return {"id": event["id"], "clause": event["clause"], "segment": event["segment"],
            "span": list(event["span"]),
            "construction": event["construction"], "action": event["action"],
            "predicate_analysis": event["predicate_analysis"],
            "action_span": list(event["action_span"]), "voice": event["voice"],
            "semantic_status": event["semantic_status"],
            "predicate_kind": event["predicate_kind"], "agency_status": event["agency_status"],
            "typing_policy": event["typing_policy"],
            "polarity": event["polarity"], "frame": event["frame"],
            "claim": event["claim"], "inherited_claim": event["inherited_claim"],
            "reading": event["reading"], "complete": event["complete"],
            "missing_roles": list(event["missing_roles"]),
            "filled_by_completion": list(event["filled_by_completion"]),
            "expected_roles": list(event["expected_roles"]),
            "emits_verification": event["emits_verification"],
            "checking_occurrence": event["checking_occurrence"],
            "checking_result": event["checking_result"],
            "result_form_hits": [dict(item, span=list(item["span"]))
                                 for item in event["result_form_hits"]],
            "result_conflict": list(event["result_conflict"]),
            "rival_roles": list(event["rival_roles"]),
            "notes": list(event["notes"])}


def _public_row(row):
    public = dict(row)
    public["spans"] = [list(span) for span in row["spans"]]
    return public


def _contradictions(rows, events_by_id, hypotheses, readings, context, multi_fill=(), store=None):
    found = []
    by_subject_predicate = {}
    for row in rows:
        if row["layer"] != "content":
            continue
        key = (row["triple"][0], row["triple"][1], row["triple"][2])
        by_subject_predicate.setdefault(key, []).append(row)
    for key, group in sorted(by_subject_predicate.items()):
        polarities = {row["polarity"] for row in group}
        if len(polarities) > 1:
            found.append({"id": "contra:%d" % len(found), "kind": "polarity",
                          "rows": [row["id"] for row in group],
                          "spans": [list(span) for row in group for span in row["spans"]]})
    filled_twice = {}
    for row in rows:
        if row["layer"] != "content" or row.get("source") != "clause":
            continue
        subject, predicate, _ = row["triple"]
        if (subject, predicate) in multi_fill:
            continue
        filled_twice.setdefault((subject, predicate, row["reading"]), []).append(row)
    for key, group in sorted(filled_twice.items()):
        if len(group) < 2:
            continue
        found.append({"id": "contra:%d" % len(found), "kind": "role_filled_twice",
                      "rows": [row["id"] for row in group],
                      "spans": [list(span) for row in group for span in row["spans"]]})

    for policy in store.of_kind("contradiction_policy") if store else ():
        for hypothesis in hypotheses:
            if (hypothesis["kind"] != policy.get("hypothesis_kind")
                    or hypothesis["status"] != policy.get("hypothesis_status")):
                continue
            kinds = {item["kind"] for item in hypothesis["evidence"]}
            if not set(policy.get("all_of", ())) <= kinds:
                continue
            if policy.get("any_of") and not kinds.intersection(policy["any_of"]):
                continue
            if kinds.intersection(policy.get("none_of", ())):
                continue
            subjects = hypothesis["subjects"]
            support = [row for row in rows
                       if row["triple"][0] in subjects and row["layer"] == "content"
                       and (row["triple"][1] in policy.get("support_predicates", ())
                            or row.get("source") == policy.get("support_source"))]
            found.append({"id": "contra:%d" % len(found), "kind": "polarity_across_events",
                          "rows": [row["id"] for row in support],
                          "subjects": list(subjects), "policy": policy["key"],
                          "hypotheses": [hypothesis["id"]],
                          "spans": [list(span) for span in hypothesis["spans"]]})
    for reading in readings:
        if not reading["competes_with"]:
            continue
        partner = min(reading["competes_with"])
        if reading["id"] > partner:
            continue
        group = [reading["id"]] + list(reading["competes_with"])
        affected = [row["id"] for row in rows if row["reading"] in group]
        found.append({"id": "contra:%d" % len(found), "kind": "reading_conflict",
                      "rows": affected, "readings": group,
                      "spans": [list(row["spans"][0]) for row in rows
                                if row["reading"] in group]})
    return found
