# -*- coding: utf-8 -*-
"""Events, the links between them, and what a link is allowed to do.

Three decisions live here, each driven entirely by a policy record:

*   whether two clauses are one event — ``event-link-policy.json``;
*   whether an accepted link may fill a role the earlier clause left open —
    the ``role_completion`` section of the same file;
*   whether a checking clause verifies another event — ``verification-policy.json``.

An unsatisfied link survives as a candidate.  A rejected link survives as a
rejected hypothesis with its blocking reason.  Nothing is deleted, and no link
is ever licensed by a shared item alone.
"""
from experiments.graph_language_repair.core import policy as policy_module


class EventLinker(object):
    def __init__(self, store, limits):
        self.store = store
        self.capped = False
        self.limits = dict(limits)
        self.policy = store.get("event-link:rules")
        self.evidence_records = store.of_kind("link_evidence")
        self.verification_policy = store.get("verification:rules")
        self.verification_evidence = store.of_kind("verification_evidence")

    # -- same event ------------------------------------------------------

    def link(self, context, events):
        """Link hypotheses over ordered event pairs."""
        cap = self.limits.get("max_event_pairs")
        ordered = sorted(events, key=lambda event: event["order"])
        hypotheses, pairs = [], 0
        for position, earlier in enumerate(ordered):
            for later in ordered[position + 1:]:
                if cap is not None and pairs >= cap:
                    self.capped = True
                    for item in hypotheses:
                        if item["status"] == "accepted":
                            item["status"] = self.policy.get("on_multiple_antecedents", "candidate")
                            item["blocked_by"].append("max_event_pairs")
                    return hypotheses
                pairs += 1
                if earlier["clause"] == later["clause"]:
                    continue
                labels, detail = policy_module.evidence_present(
                    context, self.evidence_records, earlier, later)
                if not labels:
                    continue
                status, rule_id, blocked = policy_module.decide(self.policy, labels)
                if status is None:
                    continue
                hypotheses.append({"kind": "event_link",
                                   "subjects": [earlier["id"], later["id"]],
                                   "status": status, "rule": rule_id,
                                   "evidence": detail,
                                   "blocked_by": blocked,
                                   "spans": [earlier["span"], later["span"]],
                                   "policy": self.policy["key"]})
        return self._require_one_antecedent(hypotheses, {event["id"]: event["clause"] for event in events})

    def _require_one_antecedent(self, hypotheses, clauses):
        """Downgrade an accepted link whose later clause has rival antecedents.

        A referring expression is evidence that *some* earlier happening is
        meant, not proof of which one.  Two accepted links from one clause to
        two different earlier events are mutually exclusive, so neither may be
        asserted.
        """
        if not self.policy.get("unique_antecedent_required"):
            return hypotheses
        counts = {}
        for item in hypotheses:
            if item["status"] == "accepted":
                counts.setdefault(item["subjects"][1], set()).add(clauses[item["subjects"][0]])
        downgraded = self.policy.get("on_multiple_antecedents", "candidate")
        for item in hypotheses:
            later = item["subjects"][1]
            if item["status"] == "accepted" and len(counts.get(later, ())) > 1:
                item["status"] = downgraded
                item["blocked_by"] = list(item["blocked_by"]) + [
                    "ambiguous_antecedent:%d" % len(counts[later])]
        return hypotheses

    # -- role completion -------------------------------------------------

    def completions(self, context, events_by_id, hypotheses):
        """Roles an accepted link fills, each with its own proof."""
        section = self.policy.get("role_completion", {})
        if not section:
            return []
        required = section.get("requires_link_status", "accepted")
        filled = []
        for hypothesis in hypotheses:
            if hypothesis["kind"] != "event_link" or hypothesis["status"] != required:
                continue
            left, right = (events_by_id[key] for key in hypothesis["subjects"])
            for target, donor in ((left, right), (right, left)):
                donor_roles = {}
                for item in context.roles_of(donor["id"]):
                    donor_roles.setdefault(item["role"], []).append(item)
                present = {item["role"] for item in context.roles_of(target["id"])}
                for role in target["missing_roles"]:
                    if role in present or role not in donor_roles:
                        continue
                    for item in donor_roles[role]:
                        filled.append({"event": target["id"], "role": role,
                                       "from_event": donor["id"],
                                       "mention": item.get("mention"),
                                       "value_span": item["value_span"],
                                       "value": item["value"],
                                       "marker": item.get("marker"),
                                       "marker_span": item.get("marker_span"),
                                       "proof_kind": section.get("proof_kind",
                                                                 "role_completion"),
                                       "policy": self.policy["key"],
                                       "spans": [target["span"], item["value_span"]],
                                       "hypothesis": hypothesis})
        return filled

    # -- verification ----------------------------------------------------

    def verifications(self, context, events, claims_by_id):
        """Verification hypotheses between a checking event and a target event.

        Three channels stay apart, as ``verification-policy.json`` declares:

        *   **occurrence** — whether the checking action happened at all.  A
            checking action the text negates produces no link: a check that did
            not happen is the same epistemic situation as no check, which C5
            calls a hold.  It is reported as a rejected hypothesis with its
            reason, never as a positive ``verified_by``.
        *   **result** — what the text says the check found.  Bare 확인했다
            states no result; only a declared result form does.
        *   **independent result** — the result as it bears on this target.
            A direct check may legitimately target an event introduced in a
            report; the link is allowed and the target's scope is published,
            but the independent result is withheld, because a result about a
            merely reported event is not independent evidence about the event.
        """
        policy = self.verification_policy
        forbidden = set(policy.get("forbidden_source_scopes", ()))
        required_scope = policy.get("requires_scope_kind")
        required_occurrence = policy.get("requires_occurrence")
        withheld = policy.get("independent_result_default", "unstated")
        found = []
        checks = [event for event in events if event["emits_verification"]]
        targets = [event for event in events if not event["emits_verification"]]
        for check in checks:
            claim = claims_by_id[check["claim"]]
            for target in targets:
                if target["order"] > check["order"]:
                    continue
                if target["clause"] == check["clause"]:
                    continue
                labels, detail = policy_module.evidence_present(
                    context, self.verification_evidence, target, check)
                if not labels:
                    continue
                status, rule_id, blocked = policy_module.decide(policy, labels)
                if status is None:
                    continue
                blocked = list(blocked)
                target_claim = claims_by_id[target["inherited_claim"] or target["claim"]]
                if required_occurrence and check["checking_occurrence"] != required_occurrence:
                    status = "rejected"
                    blocked.append("check_did_not_occur:%s" % check["checking_occurrence"])
                    rule_id = policy["key"]
                elif claim["kind"] in forbidden:
                    status = "rejected"
                    blocked.append("forbidden_source_scope:%s" % claim["kind"])
                    rule_id = policy["key"]
                elif required_scope and claim["kind"] != required_scope:
                    status = "rejected"
                    blocked.append("scope_not_verification_eligible:%s" % claim["kind"])
                    rule_id = policy["key"]
                found.append({"kind": "verification",
                              "subjects": [target["id"], check["id"]],
                              "status": status, "rule": rule_id,
                              "evidence": detail, "blocked_by": blocked,
                              "spans": [target["span"], check["span"]],
                              "policy": policy["key"],
                              "occurrence": check["checking_occurrence"],
                              "result": check["checking_result"],
                              "independent_result": withheld,
                              "check_scope": claim["kind"],
                              "target_scope": target_claim["kind"],
                              "target_clause": target["clause"]})
        return self._settle_verifications(found, policy, withheld)

    def _settle_verifications(self, found, policy, withheld):
        """Target uniqueness, then the independent-result conditions.

        A reference expression can be positive evidence without identifying one
        target.  Where one check reaches several targets under the same
        reference the bindings are mutually exclusive, so each is kept as a
        candidate and none is asserted.

        Independence is then decided by the declared conditions — the check's
        own scope, an explicit result, and a unique target binding — not by how
        the target was first introduced.  A directly evidenced explicit result
        about an event a report introduced is independent evidence about that
        event, and the report's own claim and scope are preserved beside it.
        """
        if policy.get("unique_target_required"):
            counts = {}
            for item in found:
                if item["status"] == "accepted":
                    check = item["subjects"][1]
                    counts.setdefault(check, set()).add(item.get("target_clause", item["subjects"][0]))
            downgraded = policy.get("on_multiple_targets", "candidate")
            for item in found:
                check = item["subjects"][1]
                if item["status"] == "accepted" and len(counts.get(check, ())) > 1:
                    item["status"] = downgraded
                    item["blocked_by"] = list(item["blocked_by"]) + [
                        "ambiguous_target:%d" % len(counts[check])]

        conditions = list(policy.get("independent_result_requires", ()))
        for item in found:
            missing = []
            for name in conditions:
                if name == "check_scope_direct":
                    if item["check_scope"] in set(policy.get("forbidden_source_scopes", ())):
                        missing.append(name)
                elif name == "explicit_result_form":
                    if item["result"] not in policy.get("result_from_form_class", {}).values():
                        missing.append(name)
                elif name == "unique_target_binding":
                    if item["status"] != "accepted":
                        missing.append(name)
                else:
                    missing.append("unknown_condition:%s" % name)
            if missing:
                item["independent_result"] = withheld
                item["blocked_by"] = list(item["blocked_by"]) + [
                    "independent_result_requires:%s" % ",".join(missing)]
            else:
                item["independent_result"] = item["result"]
        return found

    # -- scope inheritance -----------------------------------------------

    def inheritance(self, events_by_id, claims_by_id, hypotheses):
        """Claims an accepted link makes a continuation inherit."""
        policy = None
        for record in self.store.of_kind("policy"):
            if record["key"] == "scope:link_inheritance":
                policy = record
        if policy is None:
            return []
        required = policy.get("requires_link_status", "accepted")
        inherited = []
        for hypothesis in hypotheses:
            if hypothesis["kind"] != "event_link" or hypothesis["status"] != required:
                continue
            left, right = (events_by_id[key] for key in hypothesis["subjects"])
            left_kind = claims_by_id[left["claim"]]["kind"]
            right_kind = claims_by_id[right["claim"]]["kind"]
            direct = [event for event, kind in ((left, left_kind), (right, right_kind))
                      if kind == "direct_text"]
            reported = [(event, kind) for event, kind in ((left, left_kind), (right, right_kind))
                        if kind != "direct_text"]
            if len(direct) != 1 or len(reported) != 1:
                continue
            target = direct[0]
            source, source_kind = reported[0]
            inherited.append({"event": target["id"], "claim": source["claim"],
                              "scope_kind": source_kind,
                              "from_event": source["id"],
                              "proof_kind": policy.get("proof_kind", "scope_inheritance"),
                              "policy": policy["key"],
                              "spans": [source["span"], target["span"]],
                              "hypothesis": hypothesis})
        return inherited
