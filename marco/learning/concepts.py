"""Bounded, evidence-first concept candidates from saved action events.

This is intentionally a small overlay beside the Binary KG.  It generalises
only an observed action-program shape; it never asserts that a repeated action
causes some unobserved outcome.  Candidate application is an explicit derived
classification with the event records that support it.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json


SCHEMA = "nai-experience-concepts-v1"


def _key(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _id(prefix, value):
    return "%s:%s" % (prefix, hashlib.sha256(_key(value).encode("utf-8")).hexdigest()[:16])


def _shape(event, effects):
    """Variableise values but retain role wiring, condition and program shape."""
    program = event.get("program") or {}
    steps = []
    for step in program.get("steps") or []:
        row = {key: value for key, value in step.items() if key not in {"status", "value"}}
        # Constants in an action program are part of the behaviour.  Event
        # participant values are not; those are represented by role keys.
        steps.append(row)
    return {"roles": sorted((program.get("signature") or {}).get("open_roles", {}).values()),
            "role_slots": sorted((program.get("signature") or {}).get("role_slots", {}).values()),
            "fixed_values": sorted((program.get("signature") or {}).get("fixed_values", {}).items()),
            "polarity": event.get("polarity", True), "modality": event.get("modality", "asserted"),
            "conditions": [sorted((row or {}).get("triple", [])) for row in event.get("conditions") or []],
            "steps": steps,
            "effect_predicates": sorted({row[1] for row in effects if isinstance(row, list) and len(row) == 3})}


def _abstract_shape(event, effects):
    """Keep only a safe, observed program skeleton for cross-domain use.

    It deliberately omits relation names and fixed values.  A candidate built
    from this shape can classify a later event as sharing a role/operation
    skeleton; it never supplies that event's world effects.
    """
    program = event.get("program") or {}
    return {"open_role_count": len((program.get("signature") or {}).get("open_roles", {})),
            "role_slot_count": len((program.get("signature") or {}).get("role_slots", {})),
            "polarity": event.get("polarity", True), "modality": event.get("modality", "asserted"),
            "condition_count": len(event.get("conditions") or []),
            "steps": [{"op": step.get("op"), "triple_count": len(step.get("triples") or [])}
                      for step in program.get("steps") or []],
            "effect_count": len([row for row in effects if isinstance(row, list) and len(row) == 3])}


def _event_contract_shape(event, effects):
    """The shared event contract; deliberately not an effect generalisation."""
    return {"role_count": len(event.get("roles") or {}),
            "condition_count": len(event.get("conditions") or []),
            "polarity": event.get("polarity", True),
            "modality": event.get("modality", "asserted"),
            "has_program": bool(event.get("program")),
            "has_effects": bool(effects)}


def _experience(record):
    event = record.get("event") or {}
    if (record.get("status") != "executed" or event.get("polarity", True) is not True
            or event.get("modality", "asserted") != "asserted" or not event.get("id")):
        return None
    shape = _shape(event, record.get("effects") or [])
    values = {key: value for key, value in (event.get("roles") or {}).items()
              if isinstance(value, str) and value}
    abstract_shape = _abstract_shape(event, record.get("effects") or [])
    contract_shape = _event_contract_shape(event, record.get("effects") or [])
    return {"event_id": event["id"], "action": event.get("action"), "shape": shape,
            "shape_id": _id("shape", shape), "value_fingerprint": _key(values),
            "record_fingerprint": _key({"roles": values, "source": (event.get("evidence") or {}).get("text")}),
            "definition_version": event.get("definition_version"), "domain": event.get("domain"),
            "abstract_shape": abstract_shape, "abstract_shape_id": _id("abstract-shape", abstract_shape),
            "event_contract_shape": contract_shape,
            "event_contract_shape_id": _id("event-contract-shape", contract_shape)}


class ExperienceConceptStore:
    def __init__(self, *, support_limit=32, candidate_limit=64, validation_limit=32):
        self.support_limit = support_limit
        self.candidate_limit = candidate_limit
        self.validation_limit = validation_limit
        self.candidates = []
        self.applications = []
        self.disabled_ids = set()
        self.complete = True
        self.reason = None

    def sync(self, records):
        """Recompute candidates from durable event records, never source text."""
        events = [row for row in (_experience(record) for record in records) if row is not None]
        recorded_event_ids = {(record.get("event") or {}).get("id") for record in records}
        by_shape = {}
        for row in events:
            # Definitions are versioned evidence.  A later definition must not
            # silently borrow support from an earlier one merely because its
            # current structural rendering happens to match.
            by_shape.setdefault((row["shape_id"], row["definition_version"]), []).append(row)
        independent_counts = {
            key: len({row["record_fingerprint"] for row in rows})
            for key, rows in by_shape.items()
        }
        candidates = []
        previous_by_id = {row.get("id"): row for row in self.candidates if isinstance(row, dict)}
        complete, reason = True, None
        for (shape_id, definition_version), rows in sorted(by_shape.items(), key=lambda pair: _key(pair[0])):
            actions = sorted({row["action"] for row in rows if row.get("action")})
            action = actions[0] if len(actions) == 1 else None
            distinct = []
            seen = set()
            for row in rows:
                # Repeating the identical stored utterance is not a new
                # independent experience merely because it acquired a new
                # event id during the dialogue.
                marker = row["record_fingerprint"]
                if marker not in seen:
                    seen.add(marker); distinct.append(row)
            if len(distinct) < 3:
                continue
            if len(candidates) >= self.candidate_limit:
                complete, reason = False, "candidate_limit"; break
            candidate_id = _id("concept", ({"action": action, "shape": distinct[0]["shape"]}
                                               if action else {"actions": actions,
                                                               "shape": distinct[0]["shape"]}))
            previous = previous_by_id.get(candidate_id)
            by_event_id = {row["event_id"]: row for row in distinct}
            reactivation_lineage = (previous or {}).get("reactivation_lineage", {})
            stored_training = list(reactivation_lineage.get("construction_event_ids", [])
                                   or (previous or {}).get("evidence_event_ids", []))
            stored_validation = list(reactivation_lineage.get("validation_event_ids", [])
                                     or (previous or {}).get("support_event_ids", []))
            if previous is None:
                training, validation, applications_after_validation = distinct[:3], distinct[3:4], distinct[4:]
            elif (len(stored_training) == 3 and stored_validation
                  and all(event_id in by_event_id for event_id in stored_training + stored_validation)):
                # Re-use only the original construction/validation split when
                # every withdrawn source is later restored.  This is a
                # revalidation, never a promotion of a later application.
                training = [by_event_id[event_id] for event_id in stored_training]
                validation = [by_event_id[event_id] for event_id in stored_validation]
                assigned = set(stored_training + stored_validation)
                prior_applications = [by_event_id[event_id]
                                      for event_id in previous.get("application_event_ids", [])
                                      if event_id in by_event_id]
                assigned.update(row["event_id"] for row in prior_applications)
                applications_after_validation = prior_applications + [
                    row for row in distinct if row["event_id"] not in assigned]
            else:
                # Lineage is append-only: correcting a construction event
                # cannot promote a later validation/application event into
                # training or validation merely to keep a candidate alive.
                prior_training = list(previous.get("evidence_event_ids", []))
                prior_validation = list(previous.get("support_event_ids", []))
                # If an old event simply fell outside a bounded dialogue
                # replay window, retain its durable lineage.  If it is still
                # present in the ledger but no longer an eligible experience,
                # it was corrected/withdrawn and must weaken the candidate.
                invalidated = any(event_id in recorded_event_ids and event_id not in by_event_id
                                  for event_id in prior_training + prior_validation)
                training = ([by_event_id.get(event_id, {"event_id": event_id}) for event_id in prior_training]
                            if not invalidated else [by_event_id[event_id] for event_id in prior_training
                                                      if event_id in by_event_id])
                validation = ([by_event_id.get(event_id, {"event_id": event_id}) for event_id in prior_validation]
                              if not invalidated else [by_event_id[event_id] for event_id in prior_validation
                                                        if event_id in by_event_id])
                assigned = {row["event_id"] for row in training + validation}
                if len(training) == 3 and not validation:
                    next_validation = next((row for row in distinct if row["event_id"] not in assigned), None)
                    if next_validation is not None:
                        validation = [next_validation]
                        assigned.add(next_validation["event_id"])
                prior_applications = [by_event_id[event_id]
                                      for event_id in previous.get("application_event_ids", [])
                                      if event_id in by_event_id]
                assigned.update(row["event_id"] for row in prior_applications)
                applications_after_validation = prior_applications + [
                    row for row in distinct if row["event_id"] not in assigned]
            # Version boundaries prevent support leakage, not counterexample
            # blindness: a changed declared definition is evidence that the
            # old structural rule cannot be applied without a scope decision.
            counterexamples = [row["event_id"] for row in events
                               if row["action"] in actions and row["shape_id"] != shape_id]
            conflicting_shapes = [other_shape for (other_shape, _other_version), count in independent_counts.items()
                                  if other_shape != shape_id and count >= 3
                                  and any(row["action"] in actions for row in by_shape[(other_shape, _other_version)])]
            status = "candidate"
            if counterexamples:
                status = "conflict" if conflicting_shapes else "inactive"
            elif len(training) == 3 and validation:
                status = "active"
            if candidate_id in self.disabled_ids:
                status = "inactive"
            candidate = {"id": candidate_id,
                         "schema": SCHEMA, "structural_definition": deepcopy(
                             (previous or {}).get("structural_definition", distinct[0]["shape"])),
                         "scope": {"action": action, "actions": actions,
                                   "definition_versions": [definition_version]},
                         "evidence_event_ids": [row["event_id"] for row in training],
                         "support_event_ids": [row["event_id"] for row in validation],
                         "application_event_ids": [row["event_id"] for row in applications_after_validation],
                         "lineage": {"construction_event_ids": [row["event_id"] for row in training],
                                     "validation_event_ids": [row["event_id"] for row in validation],
                                     "application_event_ids": [row["event_id"] for row in applications_after_validation]},
                         "reactivation_lineage": {
                             "construction_event_ids": (stored_training if len(stored_training) == 3
                                                        else [row["event_id"] for row in training]),
                             "validation_event_ids": (stored_validation or [row["event_id"] for row in validation])},
                         "counterexample_event_ids": counterexamples[:self.support_limit],
                         "conflicts": [{"kind": "competing_structure", "shape_id": other_shape,
                                        "independent_support": sum(
                                            count for (counted_shape, _version), count in independent_counts.items()
                                            if counted_shape == other_shape)}
                                       for other_shape in sorted(conflicting_shapes)],
                         "status": status,
                         "validation": {"matched_holdouts": len(validation),
                                        "counterexamples": len(counterexamples),
                                        "complete": len(validation) == 1},
                         "limits": {"support": self.support_limit, "candidates": self.candidate_limit,
                                    "validation": self.validation_limit}}
            candidates.append(candidate)
        # A cross-domain candidate is opt-in through a declared event domain,
        # but its skeleton is computed from observed programs rather than a
        # caller-provided concept label.  It is classification-only: exact
        # action programs still own all state effects.
        by_abstract = {}
        for row in events:
            if isinstance(row.get("domain"), str) and row["domain"]:
                by_abstract.setdefault((row["abstract_shape_id"], row["definition_version"]), []).append(row)
        for (shape_id, definition_version), rows in sorted(by_abstract.items(), key=lambda pair: _key(pair[0])):
            distinct, seen = [], set()
            for row in rows:
                if row["record_fingerprint"] not in seen:
                    seen.add(row["record_fingerprint"]); distinct.append(row)
            first_by_domain = {}
            for row in distinct:
                first_by_domain.setdefault(row["domain"], row)
            domains = sorted(first_by_domain)
            if len(domains) < 3:
                continue
            if len(candidates) >= self.candidate_limit:
                complete, reason = False, "candidate_limit"; break
            training = [first_by_domain[domain] for domain in domains[:3]]
            assigned = {row["event_id"] for row in training}
            remaining = [row for row in distinct if row["event_id"] not in assigned]
            validation, applications_after_validation = remaining[:1], remaining[1:]
            actions = sorted({row["action"] for row in distinct if row.get("action")})
            candidate_id = _id("concept", {"kind": "cross_domain", "domains": domains,
                                             "actions": actions, "shape": distinct[0]["abstract_shape"]})
            counterexamples = [row["event_id"] for row in events
                               if row.get("domain") in domains and row.get("action") in actions
                               and row["abstract_shape_id"] != shape_id]
            status = "active" if validation and not counterexamples else "inactive"
            if candidate_id in self.disabled_ids:
                status = "inactive"
            candidate = {"id": candidate_id, "schema": SCHEMA,
                         "structural_definition": deepcopy(distinct[0]["abstract_shape"]),
                         "scope": {"action": None, "actions": actions, "domains": domains,
                                   "definition_versions": [definition_version],
                                   "structural_level": "cross_domain"},
                         "member_shape_ids": sorted({row["shape_id"] for row in distinct}),
                         "evidence_event_ids": [row["event_id"] for row in training],
                         "support_event_ids": [row["event_id"] for row in validation],
                         "application_event_ids": [row["event_id"] for row in applications_after_validation],
                         "lineage": {"construction_event_ids": [row["event_id"] for row in training],
                                     "validation_event_ids": [row["event_id"] for row in validation],
                                     "application_event_ids": [row["event_id"] for row in applications_after_validation]},
                         "reactivation_lineage": {"construction_event_ids": [row["event_id"] for row in training],
                                                  "validation_event_ids": [row["event_id"] for row in validation]},
                         "counterexample_event_ids": counterexamples[:self.support_limit], "conflicts": [],
                         "status": status,
                         "validation": {"matched_holdouts": len(validation),
                                        "counterexamples": len(counterexamples), "complete": len(validation) == 1},
                         "limits": {"support": self.support_limit, "candidates": self.candidate_limit,
                                    "validation": self.validation_limit}}
            candidates.append(candidate)
        # Natural actions can share an Event/Condition contract even where
        # their domain-owned programs have different exact effect shapes.
        # This classification never provides effects to another event.
        by_contract = {}
        for row in events:
            if isinstance(row.get("domain"), str) and row["domain"]:
                by_contract.setdefault(row["event_contract_shape_id"], []).append(row)
        for shape_id, rows in sorted(by_contract.items(), key=lambda pair: _key(pair[0])):
            distinct, seen = [], set()
            for row in rows:
                if row["record_fingerprint"] not in seen:
                    seen.add(row["record_fingerprint"]); distinct.append(row)
            first_by_domain = {}
            for row in distinct:
                first_by_domain.setdefault(row["domain"], row)
            domains = sorted(first_by_domain)
            if len(domains) < 3:
                continue
            if len(candidates) >= self.candidate_limit:
                complete, reason = False, "candidate_limit"; break
            training = [first_by_domain[domain] for domain in domains[:3]]
            assigned = {row["event_id"] for row in training}
            remaining = [row for row in distinct if row["event_id"] not in assigned]
            validation, applications_after_validation = remaining[:1], remaining[1:]
            actions = sorted({row["action"] for row in distinct if row.get("action")})
            candidate_id = _id("concept", {"kind": "cross_domain_event_contract", "domains": domains,
                                             "actions": actions, "shape": distinct[0]["event_contract_shape"]})
            counterexamples = [row["event_id"] for row in events
                               if row.get("domain") in domains and row.get("action") in actions
                               and row["event_contract_shape_id"] != shape_id]
            status = "active" if validation and not counterexamples else "inactive"
            if candidate_id in self.disabled_ids:
                status = "inactive"
            candidates.append({"id": candidate_id, "schema": SCHEMA,
                               "structural_definition": deepcopy(distinct[0]["event_contract_shape"]),
                               "scope": {"action": None, "actions": actions, "domains": domains,
                                         "definition_versions": sorted({row["definition_version"] for row in distinct}, key=_key),
                                         "structural_level": "cross_domain_event_contract"},
                               "member_shape_ids": sorted({row["shape_id"] for row in distinct}),
                               "evidence_event_ids": [row["event_id"] for row in training],
                               "support_event_ids": [row["event_id"] for row in validation],
                               "application_event_ids": [row["event_id"] for row in applications_after_validation],
                               "lineage": {"construction_event_ids": [row["event_id"] for row in training],
                                           "validation_event_ids": [row["event_id"] for row in validation],
                                           "application_event_ids": [row["event_id"] for row in applications_after_validation]},
                               "reactivation_lineage": {"construction_event_ids": [row["event_id"] for row in training],
                                                        "validation_event_ids": [row["event_id"] for row in validation]},
                               "counterexample_event_ids": counterexamples[:self.support_limit], "conflicts": [],
                               "status": status,
                               "validation": {"matched_holdouts": len(validation),
                                              "counterexamples": len(counterexamples), "complete": len(validation) == 1},
                               "limits": {"support": self.support_limit, "candidates": self.candidate_limit,
                                          "validation": self.validation_limit}})
        applications = []
        for candidate in candidates:
            if candidate["status"] != "active":
                continue
            for event_id in candidate["support_event_ids"]:
                applications.append({"id": "validation:%s:%s" % (candidate["id"], event_id),
                                     "candidate_id": candidate["id"], "event_id": event_id,
                                     "conclusion": [event_id, "instance_of", candidate["id"]],
                                     "derived_conclusion": [event_id, "classified_by", candidate["id"]],
                                     "premise_event_ids": list(candidate["evidence_event_ids"]),
                                     "validation_event_ids": list(candidate["support_event_ids"]),
                                     "phase": "validation_projection", "valid": True})
            for event_id in candidate["application_event_ids"]:
                row = next(row for row in events if row["event_id"] == event_id)
                level = candidate["scope"].get("structural_level")
                cross_domain = level in {"cross_domain", "cross_domain_event_contract"}
                matches_shape = (row["abstract_shape"] == candidate["structural_definition"]
                                 if level == "cross_domain" else
                                 row["event_contract_shape"] == candidate["structural_definition"]
                                 if level == "cross_domain_event_contract" else
                                 row["shape"] == candidate["structural_definition"])
                if (row["action"] in candidate["scope"].get("actions", []) and matches_shape
                        and (not cross_domain or row.get("domain") in candidate["scope"].get("domains", []))):
                    applications.append({"id": "application:%s:%s" % (candidate["id"], row["event_id"]),
                                         "candidate_id": candidate["id"], "event_id": row["event_id"],
                                         "conclusion": [row["event_id"], "instance_of", candidate["id"]],
                                         "derived_conclusion": [row["event_id"], "classified_by", candidate["id"]],
                                         "premise_event_ids": list(candidate["evidence_event_ids"]),
                                         "validation_event_ids": list(candidate["support_event_ids"]),
                                         "phase": "application", "valid": True})
        # Conversation windows may no longer replay an old application event
        # after a process restore.  Keep its already-derived durable record
        # while its unchanged candidate remains active; do not resurrect it
        # when a correction has withdrawn the candidate.
        active_ids = {row["id"] for row in candidates if row.get("status") == "active"}
        present_ids = {row["id"] for row in applications}
        applications.extend(deepcopy(row) for row in self.applications
                            if row.get("candidate_id") in active_ids and row.get("id") not in present_ids)
        self.candidates, self.applications = candidates, applications
        self.complete, self.reason = complete, reason
        return self.snapshot()

    def snapshot(self):
        return {"schema": SCHEMA, "candidates": deepcopy(self.candidates),
                "applications": deepcopy(self.applications), "complete": self.complete,
                "reason": self.reason, "disabled_ids": sorted(self.disabled_ids),
                "limits": {"support": self.support_limit, "candidates": self.candidate_limit,
                           "validation": self.validation_limit}}

    def restore(self, snapshot):
        if not isinstance(snapshot, dict) or snapshot.get("schema") != SCHEMA:
            raise ValueError("invalid_experience_concept_snapshot")
        if not isinstance(snapshot.get("candidates"), list) or not isinstance(snapshot.get("applications"), list):
            raise ValueError("invalid_experience_concept_snapshot")
        self.candidates = deepcopy(snapshot["candidates"])
        self.applications = deepcopy(snapshot["applications"])
        disabled = snapshot.get("disabled_ids", [])
        if not isinstance(disabled, list) or any(not isinstance(value, str) for value in disabled):
            raise ValueError("invalid_experience_concept_snapshot")
        self.disabled_ids = set(disabled)
        self.complete = bool(snapshot.get("complete", True)); self.reason = snapshot.get("reason")
