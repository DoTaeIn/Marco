# -*- coding: utf-8 -*-
"""The identity layer over the mention layer.

Mentions are joined into an entity only by an accepted rule of
``identity-policy.json``.  A rejection beats a transitive chain: if two
mentions may never be one entity, no sequence of other accepted pairs is
allowed to put them together.  Everything that held but did not accept is kept
as a recorded ambiguity instead of a silent merge.
"""
from experiments.graph_language_repair.core import policy as policy_module


class IdentityBuilder(object):
    def __init__(self, store, mention_list, limits):
        self.store = store
        self.mentions = list(mention_list)
        self.limits = dict(limits)
        self.evidence_records = store.of_kind("identity_evidence")
        self.policy = store.get("identity-policy:rules")

    def build(self, context):
        decisions = self._decisions(context)
        groups = self._group(decisions)
        entities, entity_of = [], {}
        for index, members in enumerate(groups):
            entity_id = "entity:%d" % index
            evidence = [item for item in decisions
                        if item["status"] == "accepted"
                        and item["left"] in members and item["right"] in members]
            entities.append({"id": entity_id, "mentions": list(members),
                             "evidence": [{"kind": kind["kind"], "policy": kind["policy"],
                                           "mentions": [item["left"], item["right"]],
                                           "spans": [item["left_span"], item["right_span"]]}
                                          for item in evidence for kind in item["detail"]
                                          if kind["sufficiency"] == "sufficient"]})
            for member in members:
                entity_of[member] = entity_id
        ambiguities = []
        for item in decisions:
            if item["status"] == "accepted":
                continue
            rules = policy_module.ambiguity_records(self.policy, item["labels"])
            if not rules:
                continue
            # "No sufficient evidence" and "refuted" must stay distinguishable
            # (C9).  A pair the policy neither accepted nor rejected is
            # published as unaccepted, with the ambiguity rule recorded as an
            # ambiguity rather than as a blocking reason, and a pair a reject
            # rule actually refused keeps its own rule as the reason.
            ambiguities.append({"mentions": [item["left"], item["right"]],
                                "spans": [item["left_span"], item["right_span"]],
                                "candidates": sorted({entity_of[item["left"]],
                                                      entity_of[item["right"]]}),
                                "evidence": [kind["kind"] for kind in item["detail"]],
                                "ambiguity_rules": [rule.get("id") for rule in rules],
                                "rule": item["rule"],
                                "blocked_by": list(item["blocked_by"]),
                                "status": item["status"] or "unaccepted"})
        return entities, entity_of, ambiguities

    def _decisions(self, context):
        self.capped = False
        cap = self.limits.get("max_mention_pairs")
        ordered = sorted(self.mentions, key=lambda item: item["span"])
        decisions, pairs = [], 0
        for position, left in enumerate(ordered):
            for right in ordered[position + 1:]:
                if cap is not None and pairs >= cap:
                    self.capped = True
                    return decisions
                pairs += 1
                labels, detail = policy_module.evidence_present(
                    context, self.evidence_records, left, right)
                if not labels:
                    continue
                status, rule_id, blocked = policy_module.decide(self.policy, labels)
                decisions.append({"left": left["id"], "right": right["id"],
                                  "left_span": left["span"], "right_span": right["span"],
                                  "labels": labels, "detail": detail,
                                  "status": status, "rule": rule_id,
                                  "blocked_by": blocked})
        return decisions

    def _group(self, decisions):
        parent = {mention["id"]: mention["id"] for mention in self.mentions}

        def find(node):
            # No path compression: a union is undone when it would join a pair
            # the policy rejects, and a compressed parent would survive the undo.
            while parent[node] != node:
                node = parent[node]
            return node

        forbidden = [(item["left"], item["right"]) for item in decisions
                     if item["status"] == "rejected"]
        for item in sorted([entry for entry in decisions if entry["status"] == "accepted"],
                           key=lambda entry: (entry["left_span"], entry["right_span"])):
            left, right = find(item["left"]), find(item["right"])
            if left == right:
                continue
            parent[left] = right
            if any(find(one) == find(other) for one, other in forbidden):
                parent[left] = left
        groups = {}
        for mention in self.mentions:
            groups.setdefault(find(mention["id"]), []).append(mention["id"])
        ordered = []
        for root in sorted(groups, key=lambda key: sorted(groups[key])):
            ordered.append(sorted(groups[root]))
        return ordered
