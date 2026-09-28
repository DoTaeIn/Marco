"""Small persistent ALMA research loop built on MARCO's existing event core.

The runtime owns *personal* state only.  Packs remain portable knowledge
assets; event replay, proofs and action programs remain the responsibility of
``ReasoningContext``.  This deliberately keeps three logical memories in one
atomic JSON file instead of introducing three databases.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import time
import uuid

from reasoning_context import ReasoningContext
from proof_chunking import applicable as shortcut_applicable, evaluate as evaluate_shortcut, invalidate as invalidate_shortcut, propose as propose_shortcut
from graph_inference import closure


SCHEMA = "alma-runtime-v1"
LOG_KINDS = {"SYSTEM", "COGNITION", "LIFE"}
MEMORY_KINDS = {"episodic", "semantic", "procedural"}
WORKING_MEMORY_LIMIT = 16
CLOSURE_SHORTCUT_CONTEXT_LIMIT = 8
MENTAL_MODALITIES = {"belief", "planned", "conditional", "hypothetical"}


def _key(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":")).encode("utf-8")).hexdigest()


def _portable(value):
    """Store only the JSON representation that a later process will read."""
    return json.loads(json.dumps(value, ensure_ascii=False))


def _matches_schema(value, schema):
    """Small, explicit JSON-shaped contract checker for local adapters."""
    if not isinstance(schema, dict):
        return False
    kind = schema.get("type", "any")
    primitive = {"object": dict, "array": list, "string": str, "number": (int, float),
                 "boolean": bool, "null": type(None)}
    if kind == "any":
        return True
    if kind not in primitive or not isinstance(value, primitive[kind]):
        return False
    if kind == "number" and isinstance(value, bool):
        return False
    if kind == "object":
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        if not isinstance(required, list) or not isinstance(properties, dict) or any(key not in value for key in required):
            return False
        return all(key not in properties or _matches_schema(item, properties[key])
                   for key, item in value.items())
    if kind == "array" and "items" in schema:
        return all(_matches_schema(item, schema["items"]) for item in value)
    return True


def _valid_schema(schema):
    if not isinstance(schema, dict) or schema.get("type", "any") not in {
            "any", "object", "array", "string", "number", "boolean", "null"}:
        return False
    if schema.get("type") == "object":
        required, properties = schema.get("required", []), schema.get("properties", {})
        if not isinstance(required, list) or not all(isinstance(key, str) for key in required) or not isinstance(properties, dict):
            return False
        return all(isinstance(key, str) and _valid_schema(value) for key, value in properties.items())
    return schema.get("type") != "array" or "items" not in schema or _valid_schema(schema["items"])


def local_file_read_adapter(root, *, max_bytes=65536):
    """Build a read-only adapter confined to one explicitly chosen directory."""
    allowed = Path(root).resolve()
    if not allowed.is_dir() or not isinstance(max_bytes, int) or max_bytes <= 0:
        raise ValueError("invalid_read_adapter_root")

    def read(payload):
        relative = Path(payload["path"])
        target = (allowed / relative).resolve()
        if target != allowed and allowed not in target.parents:
            raise ValueError("read_path_outside_root")
        if not target.is_file():
            raise ValueError("read_target_not_file")
        data = target.read_bytes()
        if len(data) > max_bytes:
            raise ValueError("read_target_too_large")
        return {"path": target.relative_to(allowed).as_posix(), "bytes": len(data),
                "text": data.decode(payload.get("encoding", "utf-8"))}

    return read


def _empty(identity, model_fingerprint):
    return {"schema": SCHEMA, "identity": identity, "revision": 0,
            "model_fingerprint": model_fingerprint, "graph_assets": {},
            "reasoning_context": None, "logs": [], "snapshots": [], "milestones": [],
            "memories": {kind: [] for kind in MEMORY_KINDS}, "goals": [],
            "affect": {"causes": [], "current": None}, "preferences": [],
            "capabilities": {}, "capability_revisions": [], "capability_runs": [], "shortcuts": [], "event_index": [],
            "mental": [], "cycles": [], "autonomous_runs": [], "action_candidates": [], "structural_changes": [], "milestone_rules": {
                "FIRST_SELF_REFERENCE": {"kind": "self_reference", "required": ["identity", "decision_id", "input"]},
                "FIRST_UNPROMPTED_GOAL": {"kind": "unprompted_goal", "required": ["goal_id", "source_event_id"]},
                "FIRST_NEW_CONCEPT": {"kind": "new_concept", "required": ["candidate_id", "evidence_event_ids"]},
                "FIRST_EXISTENTIAL_QUESTION": {"kind": "existential_question", "required": ["decision_id", "input"]},
            }}



# ALMA's life-event dialogues and their checks are written in Korean. It names
# its pack instead of inheriting whatever the pack set declares as default.
LANGUAGE = "한국어"

class AlmaRuntime:
    """A resumable one-agent research environment.

    ``turn`` is the natural-language route: it delegates all event parsing,
    correction and proof work to MARCO, then records the resulting durable
    event/revision/proof material without rewriting the source engine.
    """

    def __init__(self, state_path, identity="alma", *, model=None):
        self.path = Path(state_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.model_fingerprint = getattr(model, "fingerprint", "builtin")
        self.state = self._load(identity, self.model_fingerprint)
        migrated_event_kind = bool(self.state.pop("_event_kind_migrated", False))
        # Adapter implementations are host-local runtime objects.  Their
        # portable declarations and past outcomes live in the state file.
        self.adapters = {}
        # Recent deliberation is process-local working memory, deliberately
        # bounded and never written into the personal-life checkpoint.
        self._working_memory = []
        self.context = ReasoningContext(model=model, language=None if model is not None else LANGUAGE)
        if self.state.get("reasoning_context"):
            self.context.restore(self.state["reasoning_context"])
        # ``event_index`` is the portable event envelope.  Older checkpoints
        # already retain the action in the saved core record, so backfill it
        # without replaying or reinterpreting any event.
        actions = {row.get("event", {}).get("id"): row.get("event", {}).get("action")
                   for row in self.context.snapshot().get("events", [])}
        migrated_event_action = False
        for event in self.state["event_index"]:
            action = actions.get(event.get("local_id"))
            if action and not event.get("action"):
                event["action"] = action
                migrated_event_action = True
        self._install_active_structures()
        if migrated_event_kind or migrated_event_action:
            # Persist the conservative envelope-only migration immediately;
            # no world event is replayed or reinterpreted during this save.
            self._save()

    def _load(self, identity, model_fingerprint):
        # A process can stop after writing the temporary file but before the
        # atomic replacement.  Prefer the newest valid state, never a partial
        # JSON document, and restore the winning temporary state as the main
        # file so the next process has one canonical checkpoint again.
        candidates, problems = [], []
        temporary = self.path.with_suffix(".tmp")
        for candidate in (self.path, temporary):
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except FileNotFoundError:
                continue
            except json.JSONDecodeError:
                problems.append("state_corrupt")
                continue
            except OSError:
                problems.append("state_read_error")
                continue
            if not isinstance(data, dict):
                problems.append("state_corrupt")
                continue
            if data.get("schema") != SCHEMA:
                problems.append("state_schema_mismatch")
                continue
            if data.get("identity") != identity:
                problems.append("state_identity_mismatch")
                continue
            recorded = data.get("model_fingerprint", model_fingerprint)
            if recorded != model_fingerprint:
                problems.append("model_fingerprint_mismatch")
                continue
            candidates.append((int(data.get("revision", 0)), candidate == self.path, candidate, data))
        if candidates:
            # On equal revisions the completed main file wins over its stale
            # temporary predecessor.
            _, _, source, data = max(candidates, key=lambda item: (item[0], item[1]))
            if source == temporary:
                os.replace(temporary, self.path)
            for kind in MEMORY_KINDS:
                data.setdefault("memories", {}).setdefault(kind, [])
            for name, default in _empty(identity, model_fingerprint).items():
                data.setdefault(name, deepcopy(default))
            for name, default in _empty(identity, model_fingerprint)["milestone_rules"].items():
                data["milestone_rules"].setdefault(name, deepcopy(default))
                for key, value in default.items():
                    data["milestone_rules"][name].setdefault(key, deepcopy(value))
            # ``kind`` was added to make world, observation and private
            # Mental rows one explicit Event envelope.  Old personal states
            # remain valid lives: infer only the envelope kind from their
            # durable execution status, never replay or reinterpret facts.
            migrated_event_kind = False
            for event in data.get("event_index", []):
                if not isinstance(event, dict) or event.get("kind"):
                    continue
                status = event.get("execution_status")
                if status == "private":
                    event["kind"] = "mental" if (event.get("source") or {}).get("mental_id") else "private"
                elif status == "observed":
                    event["kind"] = "observation"
                else:
                    event["kind"] = "world"
                migrated_event_kind = True
            if migrated_event_kind:
                data["_event_kind_migrated"] = True
            return data
        if problems:
            raise ValueError(problems[0])
        return _empty(identity, model_fingerprint)

    def _save(self):
        self.state["reasoning_context"] = self.context.snapshot()
        self.state["revision"] += 1
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def backup_state(self, target_path):
        """Copy a complete personal state checkpoint without exporting a pack."""
        target = Path(target_path)
        if target.resolve() == self.path.resolve() or target.exists():
            raise ValueError("backup_target_exists")
        self._save()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(self.path, target)
        data = target.read_bytes()
        return {"path": str(target), "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(), "identity": self.state["identity"]}

    def _install_active_structures(self, context=None):
        """Rebuild the parser overlay solely from approved durable changes."""
        context = self.context if context is None else context
        context._parser_instance = None
        parser = context._parser()
        installed = {row.get("id") for row in parser.data.get("rules", [])}
        for change in self.state.get("structural_changes", []):
            rule = change.get("candidate")
            if (change.get("kind") == "rule" and change.get("status") == "active"
                    and isinstance(rule, dict) and rule.get("id") not in installed):
                parser.data.setdefault("rules", []).append(deepcopy(rule))
                installed.add(rule["id"])
        parser.rule_selector = self._shortcut_rules_for_facts
        parser.closure_selector = self._shortcut_closure_for_facts
        parser.closure_recorder = self._record_shortcut_closure

    def _shortcut_rules_for_facts(self, facts, rules):
        """Select a previously equivalence-checked shortcut for this exact input.

        The candidate's validation fingerprint includes the entire fact input,
        not merely a requested conclusion.  A changed fact set, source rule,
        or version therefore keeps the original parser rules in place.
        """
        fact_hash = _key(facts)
        for shortcut in self.state.get("shortcuts", []):
            if shortcut.get("mode") == "closure_snapshot":
                continue
            if not shortcut_applicable(shortcut, rules):
                continue
            if not any(row.get("facts_sha256") == fact_hash
                       for row in shortcut.get("validated_contexts", [])):
                continue
            source_ids = {row["id"] for row in shortcut.get("source", [])}
            selected = [row for row in rules if row.get("id") not in source_ids]
            selected += deepcopy(shortcut.get("rules", []))
            uses = getattr(self, "_active_turn_shortcuts", None)
            if uses is not None and shortcut["id"] not in uses:
                uses.append(shortcut["id"])
            return selected
        return rules

    @staticmethod
    def _closure_rows(known):
        return [{"fact": list(fact), "record": _portable(record)} for fact, record in known.items()]

    def _shortcut_closure_for_facts(self, facts, rules):
        fact_hash = _key(facts)
        self._last_closure_fact_hash = fact_hash
        for shortcut in self.state.get("shortcuts", []):
            if shortcut.get("mode") != "closure_snapshot" or not shortcut_applicable(shortcut, rules):
                continue
            context = next((row for row in shortcut.get("validated_contexts", [])
                            if row.get("facts_sha256") == fact_hash and isinstance(row.get("closure"), list)), None)
            if context is None:
                continue
            rows = context["closure"]
            if not all(isinstance(row, dict) and isinstance(row.get("fact"), list)
                       and isinstance(row.get("record"), dict) for row in rows):
                continue
            if shortcut["id"] not in self._active_turn_shortcuts:
                self._active_turn_shortcuts.append(shortcut["id"])
            metrics = getattr(self, "_active_turn_shortcut_metrics", None)
            if metrics is not None:
                metrics[shortcut["id"]] = {"rule_scans": 0, "join_attempts": 0}
            return {tuple(row["fact"]): _portable(row["record"]) for row in rows}
        return None

    def _record_shortcut_closure(self, facts, rules, known, metrics):
        fact_hash = _key(facts)
        self._last_closure_fact_hash = fact_hash
        for shortcut in self.state.get("shortcuts", []):
            if shortcut.get("mode") != "closure_snapshot" or not shortcut_applicable(shortcut, rules):
                continue
            contexts = shortcut.setdefault("validated_contexts", [])
            if any(row.get("facts_sha256") == fact_hash for row in contexts):
                continue
            if len(contexts) >= CLOSURE_SHORTCUT_CONTEXT_LIMIT:
                continue
            contexts.append({"facts_sha256": fact_hash, "closure": self._closure_rows(known),
                             "original_metrics": _portable(metrics or {}), "validated_at": time.time()})

    def _observe_natural_shortcut(self, result, decision_id):
        proof_rule_ids = [row.get("rule") for row in result.get("transitions", [])
                          if isinstance(row, dict) and isinstance(row.get("rule"), str)]
        fact_hash = getattr(self, "_last_closure_fact_hash", None)
        if len(proof_rule_ids) < 2 or not isinstance(fact_hash, str):
            return
        rules = self.context._parser().data.get("rules", [])
        source = [{"id": row["id"], "version": row.get("version", row.get("rule_version")),
                   "body": row["body"], "head": row["head"]}
                  for row in rules if isinstance(row, dict) and row.get("id")]
        if not source:
            return
        shortcut_id = "shortcut:closure:" + _key({"source": source, "proof_rule_ids": proof_rule_ids})[:20]
        shortcut = next((row for row in self.state["shortcuts"] if row.get("id") == shortcut_id), None)
        if shortcut is None:
            shortcut = {"schema": "alma-proof-shortcut-v1", "id": shortcut_id,
                        "mode": "closure_snapshot", "source": _portable(source), "rules": [],
                        "proof_rule_ids": proof_rule_ids, "active": False, "uses": 0,
                        "observation_contexts": [], "observations": 0,
                        "validated_contexts": [], "created_at": time.time()}
            self.state["shortcuts"].append(shortcut)
        contexts = shortcut.setdefault("observation_contexts", [])
        if fact_hash not in contexts:
            contexts.append(fact_hash)
            shortcut["observations"] = len(contexts)
            self._log("COGNITION", "shortcut_observed", shortcut_id=shortcut_id,
                      observations=shortcut["observations"], proof_rule_ids=proof_rule_ids,
                      decision_id=decision_id)
        if shortcut["observations"] >= 2 and not shortcut["active"]:
            shortcut["active"], shortcut["activated_at"] = True, time.time()
            self._log("LIFE", "shortcut_activated", shortcut_id=shortcut_id,
                      observations=shortcut["observations"], automatic=True)

    def propose_rule_change(self, corrections, validation):
        """Create a supervised rule candidate without changing active inference."""
        from rule_learning import propose
        parser = self.context._parser()
        before = _key(parser.data.get("rules", []))
        report = propose(parser.data, corrections, validation)
        row = {"id": "structure:" + uuid.uuid4().hex, "kind": "rule",
               "status": "pending_approval" if report["accepted"] else "rejected",
               "candidate": _portable(report["candidate"]), "report": _portable(report),
               "base_rules_sha256": before, "at": time.time()}
        self.state["structural_changes"].append(row)
        self._log("COGNITION", "structural_rule_proposed", change_id=row["id"],
                  status=row["status"], report=report)
        self._save()
        return deepcopy(row)

    def approve_rule_change(self, change_id):
        row = next((item for item in self.state["structural_changes"] if item["id"] == change_id), None)
        if row is None or row.get("kind") != "rule":
            raise ValueError("unknown_rule_change")
        if row["status"] != "pending_approval":
            raise ValueError("rule_change_not_approvable")
        row.update({"status": "active", "approved_at": time.time()})
        self._install_active_structures()
        self._log("LIFE", "structural_rule_approved", change_id=change_id,
                  candidate_id=row["candidate"]["id"])
        self._save()
        return deepcopy(row)

    def rollback_rule_change(self, change_id, reason):
        row = next((item for item in self.state["structural_changes"] if item["id"] == change_id), None)
        if row is None or row.get("kind") != "rule":
            raise ValueError("unknown_rule_change")
        if row["status"] != "active":
            raise ValueError("rule_change_not_active")
        row.update({"status": "withdrawn", "withdrawn_at": time.time(), "withdrawal_reason": str(reason)})
        self._install_active_structures()
        self._log("LIFE", "structural_rule_withdrawn", change_id=change_id, reason=str(reason))
        self._save()
        return deepcopy(row)

    def benchmark_rule_change(self, change_id, facts, target):
        """Measure a candidate's exact closure effect without installing it."""
        row = next((item for item in self.state["structural_changes"] if item["id"] == change_id), None)
        if row is None or row.get("kind") != "rule":
            raise ValueError("unknown_rule_change")
        if not isinstance(target, (list, tuple)) or len(target) != 3:
            raise ValueError("invalid_benchmark_target")
        baseline = [deepcopy(rule) for rule in self.context._parser().data.get("rules", [])
                    if rule.get("id") != row["candidate"].get("id")]
        measured_facts = _portable(facts)
        before_metrics, after_metrics = {}, {}
        before = closure(measured_facts, baseline, metrics=before_metrics)
        after = closure(measured_facts, baseline + [deepcopy(row["candidate"])], metrics=after_metrics)
        report = {"target": list(target), "before": tuple(target) in before,
                  "after": tuple(target) in after, "before_metrics": before_metrics,
                  "after_metrics": after_metrics, "simulated": True, "at": time.time()}
        row["benchmark"] = _portable(report)
        self._log("COGNITION", "structural_rule_benchmarked", change_id=change_id, benchmark=report)
        self._save()
        return deepcopy(report)

    def propose_graph_asset_file_change(self, candidate_file, *, construction_event_ids,
                                        validation_event_ids, base_pack_sha256, policy="manual"):
        """Record a self-authoring graph candidate without changing a shared pack.

        The source may be a file written by ``self_authoring.author``.  Its
        bytes, node/edge counts, independent event lineage, lint result and
        base pack identity become durable personal evidence.  Approval only
        makes it eligible for an explicit local pack export below.
        """
        source = Path(candidate_file)
        return self.propose_graph_asset_change("graphs/" + source.name,
                                               source.read_text(encoding="utf-8"),
                                               construction_event_ids=construction_event_ids,
                                               validation_event_ids=validation_event_ids,
                                               base_pack_sha256=base_pack_sha256, policy=policy)

    def propose_graph_asset_change(self, asset_path, asset_text, *, construction_event_ids,
                                   validation_event_ids, base_pack_sha256, policy="manual"):
        """Validate an experience-backed node/edge asset candidate.

        This never edits a source ``.kg`` or an existing pack.  ``local_auto``
        is a fixed policy for a local experiment only; a later export still
        requires an explicit output path and cannot overwrite a pack.
        """
        from pathlib import PurePosixPath
        import engine

        path = PurePosixPath(str(asset_path))
        if (not str(path).startswith("graphs/") or path.suffix != ".kg" or ".." in path.parts
                or not isinstance(asset_text, str) or not asset_text.strip()):
            raise ValueError("invalid_graph_asset")
        if policy not in {"manual", "local_auto"}:
            raise ValueError("invalid_graph_asset_policy")
        if (not isinstance(base_pack_sha256, str) or len(base_pack_sha256) != 64
                or any(char not in "0123456789abcdef" for char in base_pack_sha256)):
            raise ValueError("invalid_base_pack_sha256")
        construction = list(dict.fromkeys(construction_event_ids or []))
        validation = list(dict.fromkeys(validation_event_ids or []))
        known = {row["id"] for row in self.state["event_index"]}
        if (len(construction) < 3 or not validation or set(construction) & set(validation)
                or not set(construction + validation) <= known):
            raise ValueError("invalid_graph_asset_lineage")
        with TemporaryDirectory(prefix="alma-graph-candidate-") as folder:
            candidate = Path(folder) / path.name
            candidate.write_text(asset_text, encoding="utf-8")
            graph = engine.load(candidate)
            lint = engine.lint(graph)
        if lint:
            raise ValueError("graph_asset_lint_failed")
        node_count = len(graph.get("공통층") or {}) + len(graph.get("사례층") or {})
        edge_count = len(graph.get("엣지") or [])
        candidate = {"asset_path": path.as_posix(), "text": asset_text,
                     "sha256": hashlib.sha256(asset_text.encode("utf-8")).hexdigest(),
                     "node_count": node_count, "edge_count": edge_count}
        row = {"id": "structure:" + uuid.uuid4().hex, "kind": "graph_asset",
               "status": "active" if policy == "local_auto" else "pending_approval",
               "policy": policy, "candidate": candidate, "base_pack_sha256": base_pack_sha256,
               "lineage": {"construction_event_ids": construction,
                           "validation_event_ids": validation},
               "validation": {"lint": "passed", "node_count": node_count, "edge_count": edge_count,
                              "complete": True}, "at": time.time()}
        if row["status"] == "active":
            row["activated_at"] = time.time()
        self.state["structural_changes"].append(row)
        self._log("COGNITION", "structural_graph_asset_proposed", change_id=row["id"],
                  status=row["status"], candidate={key: value for key, value in candidate.items() if key != "text"},
                  lineage=row["lineage"], base_pack_sha256=base_pack_sha256)
        self._save()
        return deepcopy(row)

    def approve_graph_asset_change(self, change_id):
        row = next((item for item in self.state["structural_changes"] if item["id"] == change_id), None)
        if row is None or row.get("kind") != "graph_asset" or row.get("status") != "pending_approval":
            raise ValueError("graph_asset_not_approvable")
        row.update({"status": "active", "activated_at": time.time()})
        self._log("LIFE", "structural_graph_asset_approved", change_id=change_id,
                  asset_path=row["candidate"]["asset_path"])
        self._save()
        return deepcopy(row)

    def rollback_graph_asset_change(self, change_id, reason):
        row = next((item for item in self.state["structural_changes"] if item["id"] == change_id), None)
        if row is None or row.get("kind") != "graph_asset" or row.get("status") != "active":
            raise ValueError("graph_asset_not_active")
        row.update({"status": "withdrawn", "withdrawn_at": time.time(), "withdrawal_reason": str(reason)})
        self._log("LIFE", "structural_graph_asset_withdrawn", change_id=change_id, reason=str(reason))
        self._save()
        return deepcopy(row)

    def export_active_graph_assets(self, base_pack, output_pack):
        """Build a new pack with only approved local graph assets.

        The base pack is verified first; neither it nor the agent's personal
        state is modified.  Every active asset must name that exact base pack.
        """
        import kgpack

        base_pack, output_pack = Path(base_pack), Path(output_pack)
        if output_pack.exists():
            raise ValueError("graph_asset_output_exists")
        base_bytes = base_pack.read_bytes()
        base_sha256 = hashlib.sha256(base_bytes).hexdigest()
        base_manifest, assets = kgpack.read(base_pack)
        active = [row for row in self.state["structural_changes"]
                  if row.get("kind") == "graph_asset" and row.get("status") == "active"]
        if any(row.get("base_pack_sha256") != base_sha256 for row in active):
            raise ValueError("graph_asset_base_pack_mismatch")
        with TemporaryDirectory(prefix="alma-pack-export-") as folder:
            root = Path(folder)
            for name, body in assets.items():
                target = root.joinpath(*name.split("/")); target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(body)
            for row in active:
                name, text = row["candidate"]["asset_path"], row["candidate"]["text"]
                if name in assets:
                    raise ValueError("graph_asset_path_already_in_pack")
                target = root.joinpath(*name.split("/")); target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text, encoding="utf-8")
            files = [path for path in root.rglob("*") if path.is_file()]
            # 새 팩은 바탕 팩이 고른 언어를 그대로 쓴다. 기본 언어 선언에 맡기지 않는다.
            manifest = kgpack.write_pack(output_pack, files, root,
                                         language=(base_manifest.get("model") or {}).get("language"))
        receipt = {"base_pack_sha256": base_sha256,
                   "output_pack_sha256": hashlib.sha256(output_pack.read_bytes()).hexdigest(),
                   "asset_change_ids": [row["id"] for row in active],
                   "files": len(manifest["files"])}
        self._log("LIFE", "structural_graph_assets_exported", **receipt)
        self._save()
        return receipt

    def propose_proof_shortcut(self, rules, chain_ids, *, observation_id):
        """Persist a conservative shortcut candidate from an observed rule path."""
        if not isinstance(observation_id, str) or not observation_id:
            raise ValueError("shortcut_observation_required")
        durable_observations = {value for row in self.state["event_index"]
                                for value in (row.get("id"), row.get("local_id")) if isinstance(value, str)}
        durable_observations.update(row.get("decision_id") for row in self.state["logs"]
                                    if isinstance(row.get("decision_id"), str))
        if observation_id not in durable_observations:
            raise ValueError("shortcut_observation_unlinked")
        candidate = propose_shortcut(rules, chain_ids)
        if candidate is None:
            raise ValueError("shortcut_path_not_composable")
        found = next((row for row in self.state["shortcuts"] if row["id"] == candidate["id"]), None)
        if found is None:
            candidate["observation_ids"] = [observation_id]
            candidate["observations"] = 1
            self.state["shortcuts"].append(candidate)
            found = candidate
        elif observation_id not in found.setdefault("observation_ids", []):
            found["observation_ids"].append(observation_id)
            found["observations"] = len(found["observation_ids"])
        self._log("COGNITION", "shortcut_observed", shortcut_id=found["id"],
                  observations=found["observations"], source=found["source"])
        self._save()
        return deepcopy(found)

    def activate_proof_shortcut(self, shortcut_id):
        row = next((item for item in self.state["shortcuts"] if item["id"] == shortcut_id), None)
        if row is None:
            raise ValueError("unknown_shortcut")
        if int(row.get("observations", 0)) < 2:
            raise ValueError("shortcut_needs_independent_observation")
        row["active"], row["activated_at"] = True, time.time()
        self._log("LIFE", "shortcut_activated", shortcut_id=shortcut_id,
                  observations=row["observations"])
        self._save()
        return deepcopy(row)

    def run_proof_shortcut(self, shortcut_id, facts, rules, target):
        """Run measured original/shortcut closure and preserve source proof metadata."""
        row = next((item for item in self.state["shortcuts"] if item["id"] == shortcut_id), None)
        if row is None:
            raise ValueError("unknown_shortcut")
        result = evaluate_shortcut(facts, rules, row, tuple(target))
        row.update(_portable(result["shortcut"]))
        self._log("COGNITION", "shortcut_evaluated", shortcut_id=shortcut_id, used=result["used"],
                  target=list(target), original_metrics=result["original_metrics"],
                  accelerated_metrics=result["accelerated_metrics"], total_metrics=result["total_metrics"],
                  validation_metrics=result["validation_metrics"], source=row["source"])
        self._save()
        # ``closure`` indexes facts by tuple; expose a portable ledger form
        # rather than leaking a non-JSON map through persistent ALMA APIs.
        return {**_portable({key: value for key, value in result.items() if key != "facts"}),
                "facts": [{"triple": list(triple), **_portable(record)}
                          for triple, record in result["facts"].items()]}

    def invalidate_proof_shortcut(self, shortcut_id, reason):
        row = next((item for item in self.state["shortcuts"] if item["id"] == shortcut_id), None)
        if row is None:
            raise ValueError("unknown_shortcut")
        invalidate_shortcut(row, reason)
        self._log("LIFE", "shortcut_invalidated", shortcut_id=shortcut_id, reason=str(reason))
        self._save()
        return deepcopy(row)

    def _log(self, kind, event, **payload):
        if kind not in LOG_KINDS:
            raise ValueError("invalid_log_kind")
        row = {"id": "%s:%d" % (kind.lower(), len(self.state["logs"]) + 1),
               "kind": kind, "event": event, "at": time.time(), **_portable(payload)}
        self.state["logs"].append(row)
        self._working_memory.append({key: row[key] for key in ("id", "kind", "event", "at", "decision_id", "event_id")
                                     if key in row})
        del self._working_memory[:-WORKING_MEMORY_LIMIT]
        return row

    def _milestone(self, name, evidence):
        rule = self.state.get("milestone_rules", {}).get(name)
        if not isinstance(rule, dict):
            raise ValueError("undeclared_milestone")
        if not isinstance(evidence, dict) or any(key not in evidence or evidence[key] in (None, "")
                                               for key in rule.get("required", [])):
            raise ValueError("milestone_evidence_incomplete")
        if "identity" in rule.get("required", []) and evidence.get("identity") != self.state["identity"]:
            raise ValueError("milestone_identity_mismatch")
        if name in {"FIRST_SELF_REFERENCE", "FIRST_EXISTENTIAL_QUESTION"}:
            decision = next((row for row in self.state["logs"]
                             if row.get("event") == "turn" and row.get("decision_id") == evidence.get("decision_id")), None)
            if decision is None or decision.get("input") != evidence.get("input"):
                raise ValueError("milestone_decision_unlinked")
        if name == "FIRST_UNPROMPTED_GOAL":
            goal_exists = any(row.get("id") == evidence.get("goal_id") for row in self.state["goals"])
            event_exists = any(row.get("id") == evidence.get("source_event_id") for row in self.state["event_index"])
            if not goal_exists or not event_exists:
                raise ValueError("milestone_goal_unlinked")
        if name == "FIRST_NEW_CONCEPT":
            candidate_exists = any((row.get("concept") or {}).get("id") == evidence.get("candidate_id")
                                   for row in self.state["memories"]["semantic"])
            event_ids = {value for item in self.state["event_index"]
                         for value in (item.get("id"), item.get("local_id"))}
            if not candidate_exists or not set(evidence.get("evidence_event_ids", [])).issubset(event_ids):
                raise ValueError("milestone_concept_unlinked")
        if any(row["name"] == name for row in self.state["milestones"]):
            return None
        row = {"name": name, "at": time.time(), "evidence": deepcopy(evidence)}
        self.state["milestones"].append(row)
        self.state["snapshots"].append({"id": "milestone:" + name, "at": row["at"],
                                        "reason": name, "state_revision": self.state["revision"],
                                        "milestone_evidence": deepcopy(evidence),
                                        "context": self.context.snapshot()})
        return row

    def record_milestone_observation(self, name, evidence):
        """Record a declared milestone only when its data-required evidence exists."""
        row = self._milestone(name, evidence)
        if row is not None:
            self._log("LIFE", "milestone_observed", milestone=name, evidence=evidence)
            self._save()
        return deepcopy(row)

    def _event_key(self, event_id):
        return "event:%s:%s" % (self.state["identity"], event_id)

    def _decision_id(self):
        return "decision:%s:%s" % (self.state["identity"], uuid.uuid4().hex)

    def _remember(self, kind, row):
        if kind not in MEMORY_KINDS:
            raise ValueError("invalid_memory_kind")
        identity = row.get("id") or _key(row)
        rows = self.state["memories"][kind]
        if not any(item.get("id") == identity for item in rows):
            rows.append({"id": identity, "at": time.time(), "memory_status": "active", **_portable(row)})

    def _sync_event_contract_memory(self):
        """Promote only an active four-domain contract into semantic recall."""
        contract = self.event_contract_transfer()
        semantic_id = "semantic:" + contract.get("id", "four-domain-event-contract")
        semantic = next((row for row in self.state["memories"]["semantic"] if row["id"] == semantic_id), None)
        if contract.get("status") == "active":
            self._remember("semantic", {"id": semantic_id, "concept": contract,
                                         "confidence": {}, "evidence_event_ids": contract["evidence_event_ids"],
                                         "source": "event_contract_transfer"})
            semantic = next(row for row in self.state["memories"]["semantic"] if row["id"] == semantic_id)
            semantic.update({"concept": _portable(contract),
                             "evidence_event_ids": _portable(contract["evidence_event_ids"]),
                             "source": "event_contract_transfer"})
            if semantic.get("memory_status") == "withdrawn":
                semantic.update({"memory_status": "active", "reactivated_at": time.time(),
                                 "reactivation_reason": "four_domain_contract_revalidated"})
                self._log("COGNITION", "semantic_reactivated", semantic_id=semantic_id,
                          concept_id=contract["id"])
        elif semantic is not None and semantic.get("memory_status", "active") == "active":
            semantic.update({"memory_status": "withdrawn", "withdrawn_at": time.time(),
                             "withdrawal_reason": "four_domain_contract_unavailable"})
            self._log("COGNITION", "semantic_withdrawn", semantic_id=semantic_id, concept_id=contract.get("id"))

    def _sync_memories(self, before, after, result, decision_id, graph_identity):
        old_ids = {row.get("event", {}).get("id") for row in before.get("events", [])}
        for record in after.get("events", []):
            event = record.get("event") or {}
            event_id = event.get("id")
            if not event_id:
                continue
            global_event_id = self._event_key(event_id)
            revision = next((row for row in reversed(after.get("event_revisions", []))
                             if row.get("event_id") == event_id), None)
            if event_id in old_ids:
                existing = next((row for row in self.state["event_index"]
                                 if row.get("local_id") == event_id), None)
                if existing is not None and revision != existing.get("revision"):
                    existing.update({"kind": "world", "action": event.get("action"), "roles": event.get("roles", {}),
                                     "conditions": event.get("conditions", []),
                                     "domain": event.get("domain"),
                                     "modality": event.get("modality", "asserted"),
                                     "polarity": event.get("polarity", True),
                                     "effects": record.get("effects", []),
                                     "state_changes": record.get("state_changes", []),
                                     "execution_status": record.get("status"),
                                     "source": event.get("evidence"),
                                     "definition_version": event.get("definition_version"),
                                     "revision": revision})
                    episode = next((row for row in self.state["memories"]["episodic"]
                                    if row.get("local_event_id") == event_id), None)
                    if episode is not None:
                        episode.update({"event": event, "event_status": record.get("status"),
                                        "effects": record.get("effects", []),
                                        "state_changes": record.get("state_changes", []),
                                        "source": event.get("evidence")})
                    procedure = next((row for row in self.state["memories"]["procedural"]
                                      if row.get("source_event_id") == global_event_id), None)
                    if procedure is not None:
                        procedure.update({"program": event.get("program") or {},
                                          "preconditions": event.get("conditions", []),
                                          "effects": record.get("effects", [])})
                continue
            event_meta = {"id": global_event_id, "local_id": event_id, "kind": "world",
                          "observed_at": time.time(), "processed_at": time.time(),
                          "processed_sequence": len(self.state["event_index"]) + 1, "effective_at": None,
                          "time_status": "unconfirmed", "place": None,
                          "cause": None, "roles": event.get("roles", {}),
                          "action": event.get("action"),
                          "conditions": event.get("conditions", []),
                          "domain": event.get("domain"),
                          "modality": event.get("modality", "asserted"),
                          "polarity": event.get("polarity", True),
                          "sequence": event.get("sequence"),
                          "effects": record.get("effects", []),
                          "state_changes": record.get("state_changes", []),
                          "execution_status": record.get("status"), "source": event.get("evidence"),
                          "graph": graph_identity,
                          "definition_version": event.get("definition_version"),
                          "revision": revision}
            self.state["event_index"].append(event_meta)
            # Scope core-local IDs by agent identity when placed in a durable
            # cross-session memory ledger.  The original ID is retained.
            self._remember("episodic", {"id": "episode:%s:%s" % (self.state["identity"], event_id),
                                         "event_id": global_event_id, "local_event_id": event_id, "event": event,
                                         "event_status": record.get("status"),
                                         "effects": record.get("effects", []),
                                         "state_changes": record.get("state_changes", []),
                                         "source": event.get("evidence")})
            program = event.get("program") or {}
            if event.get("action") and program:
                version = event.get("definition_version")
                self._remember("procedural", {"id": "procedure:%s@%s" % (event["action"], version),
                                               "action": event["action"], "definition_version": version,
                                               "program": program, "preconditions": event.get("conditions", []),
                                               "effects": record.get("effects", []),
                                               "source_event_id": global_event_id})
        # Semantic memory contains only validated generalizations, never one
        # copy of every experience fact.
        active_concepts = set()
        for candidate in after.get("experience_concepts", {}).get("candidates", []):
            if candidate.get("status") == "active":
                active_concepts.add(candidate["id"])
                semantic_id = "semantic:" + candidate["id"]
                self._remember("semantic", {"id": semantic_id,
                                             "concept": candidate, "confidence": candidate.get("validation", {}),
                                             "evidence_event_ids": candidate.get("evidence_event_ids", []),
                                             "source": "experience_concepts"})
                semantic = next(row for row in self.state["memories"]["semantic"]
                                if row["id"] == semantic_id)
                # Candidate applications arrive after activation.  The
                # semantic row is the durable active view of that candidate,
                # so retain its fixed memory identity while refreshing the
                # current lineage rather than freezing the first 3/1 split.
                semantic.update({"concept": _portable(candidate),
                                 "confidence": _portable(candidate.get("validation", {})),
                                 "evidence_event_ids": _portable(candidate.get("evidence_event_ids", [])),
                                 "source": "experience_concepts"})
                if semantic.get("memory_status") == "withdrawn":
                    semantic.update({"memory_status": "active", "reactivated_at": time.time(),
                                     "reactivation_reason": "support_revalidated"})
                    self._log("COGNITION", "semantic_reactivated", semantic_id=semantic_id,
                              concept_id=candidate["id"])
                self._milestone("FIRST_NEW_CONCEPT", {"candidate_id": candidate["id"],
                                                        "evidence_event_ids": candidate.get("evidence_event_ids", [])})
        if self.event_contract_transfer().get("status") == "active":
            active_concepts.add("four-domain-event-contract")
        # A semantic promotion is not immune to its evidence being corrected.
        # Keep the historical row for audit, but make searches exclude it by
        # default and retain unrelated procedural memory untouched.
        for row in self.state["memories"]["semantic"]:
            concept_id = (row.get("concept") or {}).get("id")
            if concept_id and concept_id not in active_concepts and row.get("memory_status", "active") == "active":
                row.update({"memory_status": "withdrawn", "withdrawn_at": time.time(),
                            "withdrawal_reason": "support_or_validation_changed"})
                self._log("COGNITION", "semantic_withdrawn", semantic_id=row["id"], concept_id=concept_id)
                for action in self.state["action_candidates"]:
                    if (action.get("kind") == "learned_action" and action.get("semantic_memory_id") == row["id"]
                            and action.get("status") == "pending"):
                        action.update({"status": "cancelled", "cancelled_at": time.time(),
                                       "cancellation_reason": "semantic_memory_withdrawn"})
                        self._log("COGNITION", "learned_action_cancelled", action_id=action["id"],
                                  semantic_id=row["id"])
        self._sync_event_contract_memory()
        transitions = result.get("transitions") or []
        proof = [row.get("rule") for row in transitions if isinstance(row, dict) and row.get("rule")]
        if len(proof) >= 2:
            try:
                rules = self.context._parser().data.get("rules", [])
                candidate = propose_shortcut(rules, proof)
            except (AttributeError, KeyError, TypeError, ValueError):
                candidate = None
            if candidate is not None:
                found = next((row for row in self.state["shortcuts"] if row.get("id") == candidate["id"]), None)
                if found is None:
                    candidate["observation_ids"] = [decision_id]
                    candidate["observations"] = 1
                    self.state["shortcuts"].append(candidate)
                elif decision_id not in found.setdefault("observation_ids", []):
                    found["observation_ids"].append(decision_id)
                    found["observations"] = len(found["observation_ids"])

    def turn(self, text, graph_path):
        graph_bytes = Path(graph_path).read_bytes()
        graph_identity = hashlib.sha256(graph_bytes).hexdigest()
        self.state["graph_assets"].setdefault(graph_identity, {"sha256": graph_identity,
            "bytes": len(graph_bytes), "path_hint": Path(graph_path).name})
        memory_question = self._memory_question(text)
        if memory_question is not None:
            kind, key = memory_question
            before = self.context.snapshot()
            recalled = self.recall(kind, key)
            decision_id = self._decision_id()
            result = {"status": recalled["status"], "answer": None, "memory": recalled,
                      "transitions": [], "verification": {"memory_kind": kind,
                                                              "memory_key": key,
                                                              "typed_recall": True}}
            self._log("COGNITION", "turn", decision_id=decision_id, input=str(text),
                      status=result["status"], answer=None, reasoning=[],
                      verification=result["verification"], before_event_count=len(before.get("events", [])),
                      after_event_count=len(before.get("events", [])), event_ids=[], shortcut_ids=[],
                      graph_sha256=graph_identity, model_fingerprint=self.model_fingerprint,
                      state_before=before, state_after=self.context.snapshot())
            self._save()
            return _portable(result)
        mental_question = self._mental_question(text)
        if mental_question is not None:
            holder, kind, question_kind = mental_question
            before = self.context.snapshot()
            observed_event_ids = None
            as_of = None
            if question_kind == "condition_status":
                # Only actual world observations/executions (and explicitly
                # private Mental events) satisfy an event condition.  Plans
                # and false/temporary world events remain known but cannot
                # become an observed premise merely by being stored.
                observed_event_ids = [event_id for row in self.state["event_index"]
                                      if (row.get("kind") == "mental" or row.get("execution_status")
                                          in {"executed", "observed"})
                                      for event_id in (row.get("id"), row.get("local_id"))
                                      if isinstance(event_id, str)]
            if question_kind == "previous_state":
                active = next((row for row in self.state["mental"]
                               if row.get("status", "active") == "active"
                               and row.get("holder") == holder and row.get("kind") == kind), None)
                previous = next((row for row in self.state["mental"]
                                 if active and row.get("id") == active.get("supersedes")), None)
                as_of = previous and previous.get("at")
            queried = ({"status": "safe_hold", "holder": holder, "mental_kind": kind,
                        "reason": "previous_mental_state_not_found", "world_asserted": False}
                       if question_kind == "previous_state" and as_of is None else
                       self.query_mental(holder, kind, observed_event_ids=observed_event_ids, as_of=as_of))
            decision_id = self._decision_id()
            result = {"status": queried["status"], "answer": None, "mental": queried,
                      "transitions": [], "verification": {"holder": holder, "mental_kind": kind,
                                                              "question_kind": question_kind,
                                                              "world_asserted": False}}
            self._log("COGNITION", "turn", decision_id=decision_id, input=str(text),
                      status=result["status"], answer=None, reasoning=[],
                      verification=result["verification"], before_event_count=len(before.get("events", [])),
                      after_event_count=len(before.get("events", [])), event_ids=[], shortcut_ids=[],
                      graph_sha256=graph_identity, model_fingerprint=self.model_fingerprint,
                      state_before=before, state_after=self.context.snapshot())
            self._save()
            return _portable(result)
        mental_statement = self._mental_statement(text)
        if mental_statement is not None and not str(text or "").strip().startswith("정정:"):
            holder, kind, content = mental_statement
            before = self.context.snapshot()
            stored = self.update_mental(holder, kind, content, origin="natural")
            decision_id = self._decision_id()
            result = {"status": "observed", "answer": None, "mental": stored, "transitions": [],
                      "verification": {"mental_statement": True, "holder": holder,
                                       "mental_kind": kind, "world_asserted": False}}
            self._log("COGNITION", "turn", decision_id=decision_id, input=str(text),
                      status=result["status"], answer=None, reasoning=[], verification=result["verification"],
                      before_event_count=len(before.get("events", [])), after_event_count=len(before.get("events", [])),
                      event_ids=[], shortcut_ids=[], graph_sha256=graph_identity,
                      model_fingerprint=self.model_fingerprint, state_before=before,
                      state_after=self.context.snapshot())
            self._save()
            return _portable(result)
        mental_correction = self._mental_correction(text)
        if mental_correction is not None:
            holder, kind, before_content, after_content = mental_correction
            before = self.context.snapshot()
            previous = next((row for row in self.state["mental"]
                             if row.get("status", "active") == "active" and row["holder"] == holder
                             and row["kind"] == kind and row.get("content") == before_content), None)
            decision_id = self._decision_id()
            if previous is None:
                result = {"status": "safe_hold", "answer": None,
                          "verification": {"mental_correction": True, "holder": holder,
                                           "mental_kind": kind, "world_asserted": False,
                                           "reason": "active_mental_state_not_found"}}
            else:
                stored = self.revise_mental(previous["id"], after_content,
                                             reason="natural_mental_correction")
                result = {"status": "observed", "answer": None, "mental": stored,
                          "verification": {"mental_correction": True, "holder": holder,
                                           "mental_kind": kind, "world_asserted": False}}
            self._log("COGNITION", "turn", decision_id=decision_id, input=str(text),
                      status=result["status"], answer=None, reasoning=[], verification=result["verification"],
                      before_event_count=len(before.get("events", [])), after_event_count=len(before.get("events", [])),
                      event_ids=[], shortcut_ids=[], graph_sha256=graph_identity,
                      model_fingerprint=self.model_fingerprint, state_before=before,
                      state_after=self.context.snapshot())
            self._save()
            return _portable(result)
        self._active_turn_shortcuts = []
        self._active_turn_shortcut_metrics = {}
        self._last_closure_fact_hash = None
        before = self.context.snapshot()
        decision_id = self._decision_id()
        result = self.context.turn(text, graph_path)
        for shortcut_id in self._active_turn_shortcuts:
            shortcut = next((row for row in self.state["shortcuts"] if row.get("id") == shortcut_id), None)
            if shortcut is not None:
                shortcut["uses"] = int(shortcut.get("uses", 0)) + 1
                self._log("COGNITION", "shortcut_common_path_used", shortcut_id=shortcut_id,
                          input=str(text), uses=shortcut["uses"],
                          accelerated_metrics=self._active_turn_shortcut_metrics.get(shortcut_id))
        # The existing core deliberately has a few non-question utterances
        # with no semantic result.  They are still observations in an ALMA
        # life, so never let a missing reply erase their durable ledger entry.
        if result is None:
            result = {"status": "observed", "answer": None, "transitions": [], "verification": {}}
        after = self.context.snapshot()
        before_ids = {row.get("event", {}).get("id") for row in before.get("events", [])}
        event_ids = [self._event_key(row["event"]["id"]) for row in after.get("events", [])
                     if row.get("event", {}).get("id") not in before_ids]
        self._log("COGNITION", "turn", decision_id=decision_id, input=str(text), status=result.get("status"),
                  answer=result.get("answer"), reasoning=result.get("transitions", []),
                  verification=result.get("verification", {}), before_event_count=len(before.get("events", [])),
                  after_event_count=len(after.get("events", [])), event_ids=event_ids,
                  shortcut_ids=list(self._active_turn_shortcuts),
                  graph_sha256=graph_identity, model_fingerprint=self.model_fingerprint,
                  state_before=before, state_after=after)
        self._sync_memories(before, after, result, decision_id, graph_identity)
        self._observe_natural_shortcut(result, decision_id)
        for record in after.get("events", []):
            if record.get("event", {}).get("id") not in before_ids:
                self._log("LIFE", "event", decision_id=decision_id,
                          event_id=self._event_key(record["event"]["id"]),
                          local_event_id=record["event"]["id"], status=record.get("status"),
                          before_after=record.get("state_changes", []), source=record["event"].get("evidence"))
        if not event_ids and result.get("status") in {"observed", "unresolved"}:
            # A non-action observation must not be lost or promoted to an
            # action.  Keep its raw source separately from the facts that the
            # existing core may infer from it.
            local_id = "observation:" + uuid.uuid4().hex
            event_meta = {"id": self._event_key(local_id), "local_id": local_id,
                          "kind": "observation", "observed_at": time.time(), "processed_at": time.time(),
                          "processed_sequence": len(self.state["event_index"]) + 1,
                          "effective_at": None,
                          "time_status": "unconfirmed", "place": None,
                          "cause": None, "roles": {}, "conditions": [], "modality": "uninterpreted",
                          "polarity": None, "sequence": None, "effects": [], "state_changes": [],
                          "execution_status": "observed", "source": {"text": str(text)},
                          "graph": graph_identity, "definition_version": None, "revision": None}
            self.state["event_index"].append(event_meta)
            self._remember("episodic", {"id": "episode:%s:%s" % (self.state["identity"], local_id),
                                         "event_id": event_meta["id"], "local_event_id": local_id,
                                         "event": None, "event_status": "observed", "effects": [],
                                         "state_changes": [], "source": event_meta["source"]})
            self._log("LIFE", "observation", decision_id=decision_id,
                      event_id=event_meta["id"], source=event_meta["source"])
        # Natural text alone is not evidence of self-reference or subjective
        # experience.  An integration that has a structured observation may
        # call ``record_milestone_observation`` with the rule-required fields.
        self._save()
        return result

    @staticmethod
    def _memory_question(text):
        """Parse the small Korean typed-memory question surface.

        The label selects a lifetime; the trailing durable key is still
        resolved by ``recall`` rather than by a free-text ledger search.
        This keeps an episodic event, a validated generalisation and an action
        procedure from being silently substituted for one another.
        """
        raw = str(text or "").strip().rstrip("?.!？").strip()
        for label, kind in (("과거 경험:", "episodic"), ("일반적으로 아는 것:", "semantic"),
                            ("하는 방법:", "procedural")):
            if raw.startswith(label):
                key = raw[len(label):].strip()
                if key:
                    return kind, key
        for suffix, kind in (("의 과거 경험은 뭐야", "episodic"),
                             ("에 대한 일반 지식은 뭐야", "semantic"),
                             ("의 절차는 뭐야", "procedural"),
                             (" 기억나", "episodic"),
                             ("에 대해 알고 있는 게 뭐야", "semantic"),
                             ("을 어떻게 해", "procedural"),
                             ("를 어떻게 해", "procedural")):
            if raw.endswith(suffix):
                key = raw[:-len(suffix)].strip()
                if key:
                    return kind, key
        return None

    @staticmethod
    def _mental_question(text):
        """Parse a holder-scoped Korean belief/expectation/goal question."""
        raw = str(text or "").strip().rstrip("?.!？").strip()
        for suffix, kind in (("의 믿음은 언제 기록됐어", "belief"),
                             ("의 기대는 언제 기록됐어", "expectation"),
                             ("의 목표는 언제 기록됐어", "goal")):
            if raw.endswith(suffix):
                holder = raw[:-len(suffix)].strip()
                if holder:
                    return holder, kind, "recorded_at"
        # This question checks explicit event-id conditions against the
        # durable observation ledger; it never asserts the mental content as
        # a world fact.
        for suffix, kind in (("의 믿음 조건은 충족됐어", "belief"),
                             ("의 믿음 조건이 충족됐어", "belief"),
                             ("의 기대 조건은 충족됐어", "expectation"),
                             ("의 기대 조건이 충족됐어", "expectation"),
                             ("의 목표 조건은 충족됐어", "goal"),
                             ("의 목표 조건이 충족됐어", "goal")):
            if raw.endswith(suffix):
                holder = raw[:-len(suffix)].strip()
                if holder:
                    return holder, kind, "condition_status"
        for ending in ("은 뭐야", "는 뭐야", "이 뭐야", "가 뭐야", "은 무엇이야", "는 무엇이야"):
            if raw.endswith(ending):
                raw = raw[:-len(ending)].strip()
                break
        for label, kind in (("이전 믿음", "belief"), ("이전 기대", "expectation"), ("이전 목표", "goal")):
            suffix = "의 " + label
            if raw.endswith(suffix):
                holder = raw[:-len(suffix)].strip()
                if holder:
                    return holder, kind, "previous_state"
        for label, kind in (("믿음의 이유", "belief"), ("기대의 이유", "expectation"),
                            ("목표의 이유", "goal"), ("믿음", "belief"),
                            ("기대", "expectation"), ("목표", "goal")):
            suffix = "의 " + label
            if raw.endswith(suffix):
                holder = raw[:-len(suffix)].strip()
                if holder:
                    return holder, kind, "state"
        for suffix, kind in (("은 무엇을 믿어", "belief"), ("는 무엇을 믿어", "belief"),
                             ("은 무엇을 기대해", "expectation"), ("는 무엇을 기대해", "expectation"),
                             ("은 왜 그렇게 믿어", "belief"), ("는 왜 그렇게 믿어", "belief"),
                             ("은 왜 그렇게 기대해", "expectation"), ("는 왜 그렇게 기대해", "expectation"),
                             ("의 목표는 무엇이야", "goal")):
            if raw.endswith(suffix):
                holder = raw[:-len(suffix)].strip()
                if holder:
                    return holder, kind, "state"
        return None

    @staticmethod
    def _mental_statement(text):
        """Parse a bounded natural assertion into private Mental state only."""
        raw = str(text or "").strip().rstrip(".!？").strip()
        for suffix, kind in (("라고 믿어", "belief"), ("라고 기대해", "expectation")):
            if raw.endswith(suffix):
                subject = raw[:-len(suffix)].strip()
                for particle in ("은 ", "는 "):
                    if particle in subject:
                        holder, content = subject.split(particle, 1)
                        if holder and content:
                            return holder.strip(), kind, content.strip()
        marker = "의 목표는 "
        if marker in raw and raw.endswith("야"):
            holder, content = raw[:-1].split(marker, 1)
            if holder.strip() and content.strip():
                return holder.strip(), "goal", content.strip()
        return None

    @staticmethod
    def _mental_correction(text):
        raw = str(text or "").strip()
        if not raw.startswith("정정:") or "=>" not in raw:
            return None
        before_text, after_text = (part.strip() for part in raw[3:].split("=>", 1))
        before = AlmaRuntime._mental_statement(before_text)
        after = AlmaRuntime._mental_statement(after_text)
        if before is None or after is None or before[:2] != after[:2]:
            return None
        return before[0], before[1], before[2], after[2]

    def decision(self, decision_id):
        """Return the immutable record of why a previous turn was made."""
        row = next((item for item in self.state["logs"]
                    if item.get("kind") == "COGNITION" and item.get("event") == "turn"
                    and item.get("decision_id") == decision_id), None)
        if row is None:
            raise ValueError("unknown_decision")
        return deepcopy(row)

    def reconsider(self, decision_id, graph_path):
        """Re-evaluate a historic input against *current* state without mutation.

        Action-like input is intentionally run only on an isolated restored
        ``ReasoningContext``.  The returned result is a present-time
        counterfactual review, never a second execution in the agent's life.
        """
        previous = self.decision(decision_id)
        graph_sha256 = hashlib.sha256(Path(graph_path).read_bytes()).hexdigest()
        clone = ReasoningContext(model=self.context.model, language=self.context.language)
        clone.restore(self.context.snapshot())
        self._install_active_structures(clone)
        current = clone.turn(previous["input"], graph_path)
        review = {"decision_id": decision_id, "input": previous["input"],
                  "historic_answer": previous.get("answer"), "historic_reasoning": previous.get("reasoning", []),
                  "current_answer": current.get("answer"), "current_reasoning": current.get("transitions", []),
                  "graph_sha256": graph_sha256, "simulated": True}
        self._log("COGNITION", "decision_reconsidered", **review)
        self._save()
        return _portable(review)

    def memories(self, kind, query=None):
        if kind not in MEMORY_KINDS:
            raise ValueError("invalid_memory_kind")
        rows = [row for row in deepcopy(self.state["memories"][kind])
                if row.get("memory_status", "active") == "active"]
        if not query:
            return rows
        compact = str(query).lower()
        return [row for row in rows if compact in json.dumps(row, ensure_ascii=False).lower()]

    def working_memory(self):
        """Return the bounded process-local recent deliberation buffer."""
        return deepcopy(self._working_memory)

    def event_contract_transfer(self):
        """Reconstruct a four-domain event-contract candidate from durable rows."""
        domains = ("Quantity", "Location", "Social", "Mental")
        active_mental_ids = {row.get("id") for row in self.state["mental"]
                             if row.get("status", "active") == "active"}
        rows = [row for row in self.state["event_index"]
                if row.get("domain") in domains and row.get("polarity", True)
                and ((row.get("domain") != "Mental" and row.get("execution_status") in {"executed", "observed"})
                     or (row.get("domain") == "Mental" and row.get("execution_status") == "private"
                         and (row.get("source") or {}).get("origin") == "natural"))]
        rows = [row for row in rows if row.get("domain") != "Mental"
                or (row.get("source") or {}).get("mental_id") in active_mental_ids]
        by_domain = {domain: [row for row in rows if row.get("domain") == domain] for domain in domains}
        if any(not by_domain[domain] for domain in domains):
            return {"status": "candidate", "reason": "domain_evidence_missing",
                    "domains": [domain for domain in domains if by_domain[domain]]}
        training = [by_domain[domain][0] for domain in domains[:3]]
        validation, applications = by_domain["Mental"][:1], by_domain["Mental"][1:]
        return {"id": "four-domain-event-contract", "status": "active" if applications else "validated",
                "structural_level": "four_domain_event_contract",
                "scope": {"action": "four-domain-event-contract", "actions": ["four-domain-event-contract"],
                          "domains": list(domains)}, "domains": list(domains),
                "evidence_event_ids": [row["id"] for row in training],
                "support_event_ids": [row["id"] for row in validation],
                "application_event_ids": [row["id"] for row in applications],
                "world_asserted": False, "effect_transfer": False}

    def recall(self, kind, key):
        """Use one memory lifetime as evidence for a typed present query.

        This is intentionally not a ledger substring search.  Episodes are
        addressed by their durable event identity, semantic knowledge by its
        learned structural action, and procedures by their executable action.
        The returned provenance names the exact memory row and its source.
        """
        if kind not in MEMORY_KINDS or not isinstance(key, str) or not key:
            raise ValueError("invalid_memory_recall")
        rows = self.memories(kind)
        if kind == "episodic":
            match = next((row for row in rows if key in {row.get("event_id"), row.get("local_event_id")}), None)
        elif kind == "semantic":
            match = next((row for row in rows if key in {
                (row.get("concept") or {}).get("id"), *((row.get("concept") or {}).get("scope") or {}).get("actions", []),
                ((row.get("concept") or {}).get("scope") or {}).get("action")}), None)
        else:
            match = next((row for row in rows if row.get("action") == key), None)
        if match is None:
            result = {"status": "safe_hold", "memory_kind": kind, "key": key,
                      "reason": "memory_not_found"}
        else:
            result = {"status": "answered", "memory_kind": kind, "key": key,
                      "record": deepcopy(match),
                      "provenance": {"memory_id": match["id"], "source_event_id": match.get("event_id")
                                     or match.get("source_event_id"), "memory_status": match.get("memory_status")}}
        self._log("COGNITION", "memory_recalled", **{key: value for key, value in result.items()
                                                        if key != "record"})
        self._save()
        return _portable(result)

    def set_goal(self, goal, *, relation=None, control="unknown", prompted=True, condition=None):
        if condition is not None:
            if (not isinstance(condition, dict) or not isinstance(condition.get("field"), str)
                    or not condition["field"] or not isinstance(condition.get("at_least"), (int, float))):
                raise ValueError("invalid_goal_condition")
            condition = {"field": condition["field"], "at_least": float(condition["at_least"])}
        row = {"id": "goal:" + uuid.uuid4().hex, "goal": str(goal), "relation": relation,
               "control": control, "condition": condition, "prompted": bool(prompted), "status": "active", "at": time.time()}
        self.state["goals"].append(row)
        self._log("LIFE", "goal", goal_id=row["id"], prompted=row["prompted"], relation=relation)
        self._save()
        return deepcopy(row)

    def assess_goal_from_observation(self, goal_id, *, cause_event_id, measurements):
        """Compute goal threat from a declared goal condition and public observation.

        This route intentionally accepts measurements rather than a caller's
        affect label or ``threatened`` flag.  It is used by the local
        environment loop after an adapter result has been recorded as an
        observation.
        """
        goal = next((row for row in self.state["goals"] if row["id"] == goal_id), None)
        condition = (goal or {}).get("condition")
        if not condition:
            raise ValueError("goal_has_no_observable_condition")
        if not isinstance(measurements, dict) or condition["field"] not in measurements:
            raise ValueError("goal_measurement_unavailable")
        actual = measurements[condition["field"]]
        if not isinstance(actual, (int, float)):
            raise ValueError("invalid_goal_measurement")
        deficit = max(0.0, condition["at_least"] - float(actual))
        return self.assess_goal(goal_id, threatened=deficit > 0, expected_loss=deficit,
                                control=measurements.get("control", goal["control"]),
                                cause_event_id=cause_event_id)

    def update_mental(self, holder, kind, content, *, modality="belief", source_event_id=None,
                      polarity=True, effective_at=None, conditions=None, origin="api"):
        """Store a scoped belief, plan, condition, or hypothesis outside the world KG.

        The value intentionally never enters ``ReasoningContext``'s world
        replay.  It does, however, receive a private Event/Condition ledger
        row so that its time, source and later revision are auditable through
        the same durable event history as other domains.  Thus a mistaken
        belief can be queried and revised while physical/social state remains
        unchanged.
        """
        if (kind not in {"belief", "expectation", "goal"} or not holder or not content
                or modality not in MENTAL_MODALITIES or (conditions is not None and not isinstance(conditions, list))):
            raise ValueError("invalid_mental_state")
        if source_event_id is not None and (not isinstance(source_event_id, str) or not any(
                source_event_id == event.get("id") for event in self.state["event_index"])):
            raise ValueError("unknown_mental_source_event")
        row = {"id": "mental:" + uuid.uuid4().hex, "holder": str(holder), "kind": kind,
               "content": _portable(content), "modality": modality, "polarity": bool(polarity),
               "source_event_id": source_event_id, "effective_at": effective_at,
               "conditions": _portable(conditions or []),
               "time_status": "unconfirmed" if effective_at is None else "specified",
               "status": "active", "at": time.time()}
        event_id = self._event_key(row["id"])
        row["event_id"] = event_id
        self.state["mental"].append(row)
        self.state["event_index"].append({
            "id": event_id, "local_id": row["id"], "kind": "mental",
            "domain": "Mental",
            "observed_at": row["at"], "processed_at": row["at"],
            "processed_sequence": len(self.state["event_index"]) + 1,
            "effective_at": effective_at, "time_status": row["time_status"],
            "place": None, "cause": source_event_id, "roles": {"holder": row["holder"]},
            "conditions": deepcopy(row["conditions"]), "modality": modality,
            "polarity": bool(polarity), "sequence": None, "effects": [], "state_changes": [],
            "execution_status": "private", "private": True,
            "source": {"mental_id": row["id"], "mental_kind": kind, "origin": origin,
                       "content": _portable(content), "source_event_id": source_event_id},
            "graph": None, "definition_version": None, "revision": None})
        self._sync_event_contract_memory()
        self._log("LIFE", "mental", mental_id=row["id"], holder=row["holder"], mental_kind=kind,
                  event_id=event_id, source_event_id=source_event_id)
        self._save()
        return deepcopy(row)

    def revise_mental(self, mental_id, content, *, polarity=None, reason="corrected_belief"):
        """Withdraw a prior belief/expectation without asserting it as a world fact."""
        previous = next((row for row in self.state["mental"] if row["id"] == mental_id
                         and row.get("status", "active") == "active"), None)
        if previous is None:
            raise ValueError("unknown_active_mental_state")
        previous.update({"status": "withdrawn", "withdrawn_at": time.time(),
                         "withdrawal_reason": str(reason)})
        replacement = self.update_mental(previous["holder"], previous["kind"], content,
                                         modality=previous["modality"], source_event_id=previous.get("source_event_id"),
                                         polarity=previous["polarity"] if polarity is None else polarity,
                                         effective_at=previous.get("effective_at"),
                                         conditions=previous.get("conditions", []))
        stored = next(row for row in self.state["mental"] if row["id"] == replacement["id"])
        stored["supersedes"] = mental_id
        previous_event = next((row for row in self.state["event_index"] if row.get("id") == previous.get("event_id")), None)
        replacement_event = next((row for row in self.state["event_index"] if row.get("id") == stored.get("event_id")), None)
        if previous_event is not None:
            previous_event["superseded_by"] = stored["event_id"]
        if replacement_event is not None:
            replacement_event["supersedes"] = mental_id
        self._log("LIFE", "mental_revised", previous_id=mental_id, replacement_id=replacement["id"],
                  reason=str(reason))
        self._save()
        return deepcopy(stored)

    def mental(self, holder=None, kind=None, *, include_withdrawn=False):
        return [deepcopy(row) for row in self.state["mental"]
                if (include_withdrawn or row.get("status", "active") == "active")
                and (holder is None or row["holder"] == holder)
                and (kind is None or row["kind"] == kind)]

    def query_mental(self, holder, kind, *, content=None, observed_event_ids=None, as_of=None):
        """Answer a holder-scoped mental query without asserting a world fact.

        ``as_of`` is a recorded processing timestamp, not a claimed world
        time.  It reconstructs which private state was active then, while the
        normal query remains the currently active state.
        """
        if kind not in {"belief", "expectation", "goal"} or not isinstance(holder, str) or not holder:
            raise ValueError("invalid_mental_query")
        if content is not None:
            content = _portable(content)
        if observed_event_ids is not None and (not isinstance(observed_event_ids, list)
                                               or any(not isinstance(value, str) for value in observed_event_ids)):
            raise ValueError("invalid_mental_condition_events")
        if as_of is not None and (isinstance(as_of, bool) or not isinstance(as_of, (int, float))):
            raise ValueError("invalid_mental_as_of")
        rows = [row for row in self.mental(holder, kind, include_withdrawn=as_of is not None)
                if content is None or row.get("content") == content]
        if as_of is not None:
            rows = [row for row in rows if row.get("at", float("inf")) <= as_of
                    and row.get("withdrawn_at", float("inf")) > as_of]
        if len(rows) != 1:
            result = {"status": "safe_hold", "holder": holder, "mental_kind": kind,
                      "as_of": as_of, "reason": "mental_not_found" if not rows else "ambiguous_mental_state"}
        else:
            row = rows[0]
            conditional = row["modality"] in {"conditional", "hypothetical"}
            conditions = deepcopy(row.get("conditions", []))
            event_conditions = [condition.get("event_id") for condition in conditions
                                if isinstance(condition, dict) and isinstance(condition.get("event_id"), str)]
            only_event_conditions = len(event_conditions) == len(conditions)
            known_events = {event_id for item in self.state["event_index"]
                            for event_id in (item.get("id"), item.get("local_id"))}
            observed = set(observed_event_ids or [])
            condition_proof = [{"event_id": event_id, "observed": event_id in observed,
                                "known": event_id in known_events} for event_id in event_conditions]
            if conditional and event_conditions and only_event_conditions and all(row["known"] for row in condition_proof):
                status = "answered" if all(row["observed"] for row in condition_proof) else "conditional"
            else:
                status = "conditional" if conditional else "answered"
            # Even a satisfied conditional remains a holder-scoped mental
            # proposition.  It never becomes a world assertion through this
            # query path.
            result = {"status": status, "holder": holder, "mental_kind": kind,
                      "content": deepcopy(row["content"]), "modality": row["modality"],
                      "polarity": row["polarity"], "conditions": conditions,
                      "event_id": row.get("event_id"), "recorded_at": row.get("at"),
                      "as_of": as_of, "effective_at": row.get("effective_at"),
                      "source_event_id": row.get("source_event_id"),
                      "condition_proof": condition_proof, "world_asserted": False,
                      "explanation": {"holder": holder, "mental_kind": kind,
                                      "source_event_id": row.get("source_event_id"),
                                      "event_id": row.get("event_id"),
                                      "recorded_at": row.get("at"),
                                      "as_of": as_of,
                                      "effective_at": row.get("effective_at"),
                                      "conditions": deepcopy(conditions),
                                      "condition_proof": deepcopy(condition_proof),
                                      "world_asserted": False},
                      "provenance": {"mental_id": row["id"], "memory_status": row.get("status")}}
        self._log("COGNITION", "mental_queried", **result)
        self._save()
        return _portable(result)

    def compress_episodic(self, keep=16):
        """Replace only older event detail with an auditable summary.

        This deliberately does not touch semantic or procedural rows: working
        memory pressure and long-term knowledge lifetime are separate.
        """
        if keep < 0:
            raise ValueError("invalid_episode_keep")
        rows = self.state["memories"]["episodic"]
        candidates = [row for row in rows if row.get("memory_status", "active") == "active"][:-keep or None]
        changed = []
        for row in candidates:
            event = row.get("event") or {}
            summary = {"event_id": row.get("event_id"), "action": event.get("action"),
                       "definition_version": event.get("definition_version"),
                       "effects": row.get("effects", []), "event_hash": _key(event)}
            row.update({"memory_status": "compressed", "summary": summary, "event": None,
                        "compressed_at": time.time()})
            changed.append(row["id"])
        if changed:
            self._log("LIFE", "episodic_compression", episodes=changed, keep=keep)
            self._save()
        return changed

    def assess_goal(self, goal_id, *, threatened, expected_loss=0, control=None, cause_event_id=None):
        goal = next((row for row in self.state["goals"] if row["id"] == goal_id), None)
        if goal is None:
            raise ValueError("unknown_goal")
        if not any(row["id"] == cause_event_id for row in self.state["event_index"]):
            raise ValueError("unknown_affect_cause_event")
        control = goal["control"] if control is None else control
        cause = {"id": "affect:" + uuid.uuid4().hex, "goal_id": goal_id,
                 "threatened": bool(threatened), "expected_loss": float(expected_loss),
                 "control": control, "relation": goal.get("relation"),
                 "cause_event_id": cause_event_id, "at": time.time()}
        # The label follows the causal structure; it is not inferred from a
        # word in user input.  A resolved threat clears the current state.
        label = "threat" if threatened and expected_loss > 0 else "resolved"
        cause["label"] = label
        self.state["affect"]["causes"].append(cause)
        self.state["affect"]["current"] = cause if label != "resolved" else None
        self._log("LIFE", "affect", **cause)
        self._save()
        return deepcopy(cause)

    def resolve_goal(self, goal_id, outcome, *, source_event_id):
        """Close an active goal only with a durable observed-event reference."""
        if outcome not in {"achieved", "abandoned", "failed"}:
            raise ValueError("invalid_goal_outcome")
        goal = next((row for row in self.state["goals"] if row["id"] == goal_id and row["status"] == "active"), None)
        if goal is None:
            raise ValueError("unknown_active_goal")
        if not any(row["id"] == source_event_id for row in self.state["event_index"]):
            raise ValueError("unknown_goal_resolution_source")
        if outcome == "achieved" and goal.get("condition") and not any(
                cause.get("goal_id") == goal_id and cause.get("cause_event_id") == source_event_id
                and cause.get("label") == "resolved" for cause in self.state["affect"]["causes"]):
            raise ValueError("goal_condition_unmet")
        goal.update({"status": outcome, "resolved_at": time.time(), "resolution_source_event_id": source_event_id})
        for action in self.state["action_candidates"]:
            if action.get("goal_id") == goal_id and action.get("status") in {"pending", "ready"}:
                action.update({"status": "cancelled", "cancelled_at": time.time(),
                               "cancellation_reason": "goal_" + outcome})
        if (self.state["affect"].get("current") or {}).get("goal_id") == goal_id:
            self.state["affect"]["current"] = None
        self._log("LIFE", "goal_resolved", goal_id=goal_id, outcome=outcome,
                  source_event_id=source_event_id)
        self._save()
        return deepcopy(goal)

    def explain_affect(self):
        """Return the active causal record and its durable goal, if any."""
        cause = self.state["affect"].get("current")
        if cause is None:
            return {"status": "resolved", "cause": None, "goal": None}
        goal = next((row for row in self.state["goals"] if row["id"] == cause["goal_id"]), None)
        return {"status": cause["label"], "cause": deepcopy(cause), "goal": deepcopy(goal)}

    def experience_preference(self, item, *, utility, affect_label, context=None, event_id=None):
        """Update preference from observed experience; no item has a prior score."""
        if not any(row["id"] == event_id for row in self.state["event_index"]):
            raise ValueError("unknown_preference_event")
        cause = next((row for row in reversed(self.state["affect"]["causes"])
                      if row.get("cause_event_id") == event_id and row.get("label") == affect_label), None)
        if cause is None:
            raise ValueError("preference_affect_unlinked")
        duplicate = next((row for row in self.state["preferences"]
                          if row["item"] == item and row.get("context") == context
                          and row.get("event_id") == event_id and row.get("status", "active") == "active"), None)
        if duplicate is not None:
            return deepcopy(duplicate)
        evidence = [row for row in self.state["preferences"] if row["item"] == item
                    and row.get("context") == context and row.get("status", "active") == "active"]
        signal = 1 if affect_label == "resolved" else -1 if affect_label == "threat" else 0
        support_event_ids = sorted({row.get("event_id") for row in evidence} | {event_id})
        for evidence_row in evidence:
            evidence_row.update({"confidence": len(support_event_ids), "support_event_ids": support_event_ids})
        row = {"id": "preference:" + uuid.uuid4().hex, "item": str(item), "context": context,
               "utility": float(utility), "affect": affect_label, "signal": signal,
               "confidence": len(support_event_ids), "support_event_ids": support_event_ids,
               "event_id": event_id, "affect_cause_id": cause["id"],
               "status": "active", "at": time.time()}
        self.state["preferences"].append(row)
        self._log("LIFE", "preference", preference_id=row["id"], item=item, event_id=event_id)
        self._save()
        return deepcopy(row)

    def revise_preference(self, preference_id, *, affect_label, utility=None, reason="corrected_experience"):
        previous = next((row for row in self.state["preferences"] if row["id"] == preference_id), None)
        if previous is None or previous.get("status", "active") != "active":
            raise ValueError("unknown_active_preference")
        previous.update({"status": "withdrawn", "withdrawn_at": time.time(), "withdrawal_reason": str(reason)})
        replacement = self.experience_preference(previous["item"], utility=previous["utility"] if utility is None else utility,
                                               affect_label=affect_label, context=previous.get("context"),
                                               event_id=previous.get("event_id"))
        replacement["supersedes"] = preference_id
        # ``experience_preference`` persisted the new row; update that durable
        # record too so restart keeps the correction link.
        next(row for row in self.state["preferences"] if row["id"] == replacement["id"])["supersedes"] = preference_id
        self._log("LIFE", "preference_revised", previous_id=preference_id,
                  replacement_id=replacement["id"], reason=str(reason))
        self._save()
        return deepcopy(replacement)

    def choose(self, options, *, context=None):
        """Choose by learned preference, active goal-threat fit, then utility."""
        scored = []
        active_cause = self.state["affect"].get("current")
        for option in options:
            name = option["id"] if isinstance(option, dict) else str(option)
            rows = [row for row in self.state["preferences"] if row["item"] == name
                    and row.get("context") == context and row.get("status", "active") == "active"]
            preference = sum(row["signal"] for row in rows)
            confidence = len({row.get("event_id") for row in rows})
            utility = float(option.get("utility", 0)) if isinstance(option, dict) else 0.0
            protected = option.get("protects_goal_ids", []) if isinstance(option, dict) else []
            relation = option.get("supports_relation") if isinstance(option, dict) else None
            supported_controls = option.get("supports_controls", []) if isinstance(option, dict) else []
            if not isinstance(supported_controls, list) or not all(isinstance(value, str) for value in supported_controls):
                supported_controls = []
            goal_fit = int(bool(active_cause and (
                active_cause["goal_id"] in protected or
                relation == active_cause.get("relation"))))
            control_fit = int(bool(active_cause and supported_controls
                                   and active_cause.get("control") in supported_controls))
            scored.append({"id": name, "preference": preference, "confidence": confidence, "goal_fit": goal_fit,
                           "control_fit": control_fit,
                           "utility": utility, "evidence": [r["id"] for r in rows]})
        if not scored:
            return None
        chosen = max(scored, key=lambda row: (row["preference"], row["goal_fit"], row["control_fit"],
                                               row["utility"], row["id"]))
        self._log("COGNITION", "choice", options=scored, chosen=chosen,
                  affect_cause_id=(active_cause or {}).get("cause_event_id"))
        self._save()
        return chosen

    def register_capability(self, spec, adapter):
        """Register an adapter without modifying the reasoning/event core."""
        name = str((spec or {}).get("name") or "")
        permission = (spec or {}).get("permission")
        input_schema = (spec or {}).get("input_schema", {"type": "any"})
        output_schema = (spec or {}).get("output_schema", {"type": "any"})
        provides = (spec or {}).get("provides", [])
        idempotency_key_field = (spec or {}).get("idempotency_key_field")
        if (not name or permission not in {"read", "write", "execute"} or not callable(adapter)
                or not _valid_schema(input_schema) or not _valid_schema(output_schema)
                or not isinstance(provides, list) or any(not isinstance(value, str) or not value for value in provides)
                or (idempotency_key_field is not None
                    and (not isinstance(idempotency_key_field, str) or not idempotency_key_field
                         or input_schema.get("type") != "object"))):
            raise ValueError("invalid_capability")
        previous = self.state["capabilities"].get(name, {}).get("spec")
        version = int((previous or {}).get("version", 0)) + 1
        declaration = {**deepcopy(spec), "input_schema": deepcopy(input_schema),
                       "output_schema": deepcopy(output_schema), "version": version}
        self.state["capabilities"][name] = {"spec": declaration}
        self.state["capability_revisions"].append({"capability": name, "version": version,
                                                     "spec": deepcopy(declaration), "at": time.time(),
                                                     "replaces_version": (previous or {}).get("version")})
        self.adapters[name] = adapter
        self._log("SYSTEM", "capability_registered", capability=name, permission=permission,
                  version=version, replaces_version=(previous or {}).get("version"))
        self._save()

    def call_capability(self, name, payload, *, approved=False, request_id=None):
        """Journal a capability request before any adapter can produce an effect."""
        entry = self.state["capabilities"].get(name)
        if not entry:
            raise ValueError("unknown_capability")
        spec = entry["spec"]
        try:
            payload = _portable(payload)
        except (TypeError, ValueError):
            request_id = request_id or "invalid:" + uuid.uuid4().hex
            old = next((row for row in self.state["capability_runs"]
                        if row["capability"] == name and row["request_id"] == request_id), None)
            if old:
                return deepcopy(old)
            run = {"request_id": request_id, "capability": name, "capability_version": spec.get("version"),
                   "status": "failed", "payload_sha256": None, "output": None,
                   "error": "input_not_portable", "finished_at": time.time()}
            self.state["capability_runs"].append(run)
            self._log("SYSTEM", "capability_call", **run)
            self._log("COGNITION", "capability_feedback", request_id=request_id,
                      capability=name, status=run["status"], error=run["error"])
            self._save()
            return deepcopy(run)

        request_id = request_id or _key([name, payload])
        payload_sha256 = _key(payload)
        run = next((row for row in self.state["capability_runs"]
                    if row["capability"] == name and row["request_id"] == request_id), None)
        if run:
            if run.get("payload_sha256") not in {None, payload_sha256}:
                raise ValueError("capability_request_conflict")
            if run.get("status") == "done":
                return deepcopy(run)
            if run.get("status") == "running":
                run.update({"status": "unknown_execution", "finished_at": time.time(),
                            "error": "interrupted_after_execution_started"})
                self._log("SYSTEM", "capability_call", **run)
                self._log("COGNITION", "capability_feedback", request_id=request_id,
                          capability=name, status=run["status"], error=run["error"])
                self._save()
                return deepcopy(run)
            if run.get("status") == "approval_required" and approved:
                run.update({"status": "retrying", "retried_at": time.time()})
            elif run.get("status") == "failed" and run.get("error") == "adapter_unavailable":
                run.update({"status": "retrying", "retried_at": time.time()})
            else:
                return deepcopy(run)
        else:
            run = {"request_id": request_id, "capability": name, "capability_version": spec.get("version"),
                   "permission": spec["permission"], "payload": payload, "payload_sha256": payload_sha256,
                   "status": "requested", "attempts": [], "requested_at": time.time()}
            self.state["capability_runs"].append(run)

        if not _matches_schema(payload, spec["input_schema"]):
            outcome = {"status": "failed", "output": None, "error": "input_schema_invalid"}
        elif spec["permission"] != "read" and not approved:
            outcome = {"status": "approval_required", "output": None}
        elif name not in self.adapters:
            outcome = {"status": "failed", "output": None, "error": "adapter_unavailable"}
        else:
            run.update({"status": "running", "started_at": time.time()})
            run.setdefault("attempts", []).append({"at": run["started_at"], "status": "running"})
            self._log("SYSTEM", "capability_started", request_id=request_id, capability=name,
                      capability_version=spec.get("version"), payload_sha256=payload_sha256)
            self._save()
            try:
                adapter_payload = deepcopy(payload)
                key_field = spec.get("idempotency_key_field")
                if key_field:
                    supplied = adapter_payload.get(key_field)
                    if supplied not in {None, request_id}:
                        raise ValueError("adapter_idempotency_key_conflict")
                    adapter_payload[key_field] = request_id
                output = self.adapters[name](adapter_payload)
                if not _matches_schema(output, spec["output_schema"]):
                    outcome = {"status": "failed", "output": None, "error": "output_schema_invalid"}
                else:
                    try:
                        output = _portable(output)
                    except (TypeError, ValueError):
                        outcome = {"status": "failed", "output": None, "error": "output_not_portable"}
                    else:
                        outcome = {"status": "done", "output": output}
            except Exception as exc:
                outcome = {"status": "failed" if spec["permission"] == "read" else "unknown_execution",
                           "output": None, "error": "%s: %s" % (type(exc).__name__, exc)}
        run.update(outcome)
        run["finished_at"] = time.time()
        self._log("SYSTEM", "capability_call", **run)
        self._log("COGNITION", "capability_feedback", request_id=request_id,
                  capability=name, status=run["status"], error=run.get("error"))
        self._save()
        return deepcopy(run)

    def propose_next_action(self, *, source_event_id, goal_id=None, information_gap=None, action=None):
        """Record a grounded, non-executing response to an observed gap or threat."""
        if not isinstance(source_event_id, str) or not any(row["id"] == source_event_id
                                                            for row in self.state["event_index"]):
            raise ValueError("unknown_action_source_event")
        goal = next((row for row in self.state["goals"] if row["id"] == goal_id and row["status"] == "active"), None)
        if goal_id is not None and goal is None:
            raise ValueError("unknown_active_goal")
        if not goal and not isinstance(information_gap, str):
            raise ValueError("missing_action_motive")
        memory = None
        if action is not None:
            if not isinstance(action, str) or not action:
                raise ValueError("invalid_learned_action")
            semantic, procedure = self.recall("semantic", action), self.recall("procedural", action)
            if semantic["status"] != "answered" or procedure["status"] != "answered":
                result = {"status": "safe_hold", "reason": "learned_action_memory_unavailable", "action": action,
                          "semantic_status": semantic["status"], "procedural_status": procedure["status"]}
                self._log("COGNITION", "next_action_held", source_event_id=source_event_id, **result)
                self._save()
                return result
            memory = {"semantic_memory_id": semantic["provenance"]["memory_id"],
                      "procedural_memory_id": procedure["provenance"]["memory_id"],
                      "procedure_source_event_id": procedure["provenance"]["source_event_id"]}
        candidate = {"id": "action:" + uuid.uuid4().hex, "status": "pending",
                     "source_event_id": source_event_id, "goal_id": goal_id,
                     "information_gap": information_gap, "action": action,
                     "kind": "learned_action" if memory else "seek_information" if information_gap else "protect_goal",
                     "at": time.time(), **(memory or {})}
        self.state["action_candidates"].append(candidate)
        self._log("COGNITION", "next_action_proposed",
                  **{key: value for key, value in candidate.items() if key != "kind"},
                  action_kind=candidate["kind"])
        self._save()
        return deepcopy(candidate)

    def select_capability_for_action(self, action_id):
        """Select a read capability whose declared information contract fits the gap."""
        action = next((row for row in self.state["action_candidates"] if row["id"] == action_id), None)
        if action is None:
            raise ValueError("unknown_action_candidate")
        if action["kind"] != "seek_information":
            raise ValueError("action_has_no_capability_contract")
        reads = [name for name, row in self.state["capabilities"].items()
                 if row["spec"].get("permission") == "read"]
        matching = [name for name in reads
                    if action.get("information_gap") in self.state["capabilities"][name]["spec"].get("provides", [])]
        generic = [name for name in reads
                   if not self.state["capabilities"][name]["spec"].get("provides")]
        # Old declarations had no semantic contract.  Preserve their safe
        # one-read behavior, but never let a generic adapter compete with an
        # explicitly matching one.
        choices = matching or generic
        if len(choices) != 1:
            if action.get("status") == "ready":
                action.setdefault("selection_revisions", []).append({
                    "capability": action.get("selected_capability"), "selected_at": action.get("selected_at"),
                    "withdrawn_at": time.time(), "reason": "capability_set_changed"})
                action.pop("selected_capability", None)
                action.pop("selected_at", None)
                action["status"] = "pending"
            result = {"action_id": action_id, "status": "safe_hold",
                      "reason": ("no_matching_read_capability" if reads else "no_read_capability")
                      if not choices else "ambiguous_read_capability",
                      "candidates": sorted(choices), "available": sorted(reads)}
        else:
            action.update({"status": "ready", "selected_capability": choices[0],
                           "selected_at": time.time()})
            result = {"action_id": action_id, "status": "ready", "capability": choices[0]}
        self._log("COGNITION", "capability_selected_for_action", **result)
        self._save()
        return deepcopy(result)

    def execute_selected_action(self, action_id, payload, *, request_id=None):
        """Explicitly run the one read capability selected for a ready action.

        Selection remains a plan.  This separate call is the only route that
        performs the adapter invocation, and its durable receipt is attached
        to the action candidate as well as the capability ledger.
        """
        action = next((row for row in self.state["action_candidates"] if row["id"] == action_id), None)
        if action is None:
            raise ValueError("unknown_action_candidate")
        if not action.get("selected_capability"):
            raise ValueError("action_not_ready_for_execution")
        capability = action["selected_capability"]
        prior = next((row for row in action.get("executions", [])
                      if row["request_id"] == request_id and row["capability"] == capability), None)
        if action.get("status") == "completed" and prior is not None:
            outcome = self.call_capability(capability, payload, request_id=request_id)
            return {"action_id": action_id, "status": "completed",
                    "capability_result": deepcopy(outcome)}
        if action.get("status") != "ready":
            raise ValueError("action_not_ready_for_execution")
        outcome = self.call_capability(capability, payload, request_id=request_id)
        receipt = {"at": time.time(), "request_id": outcome["request_id"], "capability": capability,
                   "capability_version": outcome.get("capability_version"),
                   "capability_status": outcome["status"]}
        if prior is None:
            action.setdefault("executions", []).append(receipt)
        action["status"] = "completed" if outcome["status"] == "done" else "safe_hold"
        self._log("COGNITION", "selected_action_executed", action_id=action_id,
                  action_status=action["status"], **receipt)
        self._save()
        return {"action_id": action_id, "status": action["status"],
                "capability_result": deepcopy(outcome)}

    def start_cycle(self, graph_path, steps, *, step_budget=16):
        """Start a data-defined observation-to-action loop.

        Each completed step is checkpointed in personal state.  The caller
        supplies declarations rather than a scenario-specific script: a step
        can be an observation, goal assessment, preference observation,
        capability call, or choice.  A bounded run is resumed with the same
        graph bytes, preventing a changed host file from silently continuing
        an old life history.
        """
        if not isinstance(steps, list) or not all(isinstance(row, dict) for row in steps):
            raise ValueError("invalid_cycle_steps")
        graph = Path(graph_path)
        identity = hashlib.sha256(graph.read_bytes()).hexdigest()
        row = {"id": "cycle:" + uuid.uuid4().hex, "at": time.time(),
               "graph_sha256": identity, "steps": _portable(steps), "cursor": 0,
               "results": [], "status": "active"}
        self.state["cycles"].append(row)
        self._log("SYSTEM", "cycle_started", cycle_id=row["id"], graph_sha256=identity,
                  step_count=len(steps))
        self._save()
        return self.resume_cycle(row["id"], graph_path, step_budget=step_budget)

    def _cycle_step(self, step, graph_path):
        kind = step.get("kind")
        if kind == "observation":
            return self.turn(step["text"], graph_path)
        if kind == "goal_assessment":
            return self.assess_goal(step["goal_id"], threatened=step["threatened"],
                                    expected_loss=step.get("expected_loss", 0),
                                    control=step.get("control"),
                                    cause_event_id=step.get("cause_event_id"))
        if kind == "goal_resolution":
            return self.resolve_goal(step["goal_id"], step["outcome"], source_event_id=step["source_event_id"])
        if kind == "preference":
            return self.experience_preference(step["item"], utility=step["utility"],
                                              affect_label=step["affect_label"],
                                              context=step.get("context"), event_id=step.get("event_id"))
        if kind == "capability":
            return self.call_capability(step["name"], step.get("payload", {}),
                                        approved=step.get("approved", False),
                                        request_id=step.get("request_id"))
        if kind == "choice":
            return self.choose(step["options"], context=step.get("context"))
        if kind == "next_action":
            return self.propose_next_action(source_event_id=step["source_event_id"],
                                            goal_id=step.get("goal_id"),
                                            information_gap=step.get("information_gap"))
        if kind == "capability_selection":
            return self.select_capability_for_action(step["action_id"])
        if kind == "selected_action_execution":
            return self.execute_selected_action(step["action_id"], step.get("payload", {}),
                                                request_id=step.get("request_id"))
        raise ValueError("invalid_cycle_step")

    def resume_cycle(self, cycle_id, graph_path, *, step_budget=16):
        if not isinstance(step_budget, int) or step_budget <= 0:
            raise ValueError("invalid_step_budget")
        row = next((item for item in self.state["cycles"] if item["id"] == cycle_id), None)
        if row is None:
            raise ValueError("unknown_cycle")
        actual = hashlib.sha256(Path(graph_path).read_bytes()).hexdigest()
        if actual != row["graph_sha256"]:
            raise ValueError("cycle_graph_fingerprint_mismatch")
        if row["status"] == "completed":
            return deepcopy(row)
        used = 0
        while row["cursor"] < len(row["steps"]) and used < step_budget:
            index, step = row["cursor"], row["steps"][row["cursor"]]
            result = self._cycle_step(step, graph_path)
            row["results"].append({"index": index, "kind": step.get("kind"),
                                   "result": _portable(result), "at": time.time()})
            row["cursor"] += 1
            used += 1
            self._log("SYSTEM", "cycle_step", cycle_id=cycle_id, index=index,
                      step_kind=step.get("kind"))
            self._save()
        row["status"] = "completed" if row["cursor"] == len(row["steps"]) else "paused_budget"
        self._log("SYSTEM", "cycle_finished" if row["status"] == "completed" else "cycle_paused",
                  cycle_id=cycle_id, cursor=row["cursor"], step_count=len(row["steps"]),
                  step_budget=step_budget)
        self._save()
        return deepcopy(row)

    def first(self, event, value=None):
        for row in self.state["logs"]:
            if row.get("event") == event and (value is None or value in json.dumps(row, ensure_ascii=False)):
                return deepcopy(row)
        return None

    def annotate_event(self, event_id, *, effective_at=None, place=None, cause_event_id=None,
                       roles=None, conditions=None):
        """Attach observed metadata without replaying or altering world facts.

        ``observed_at`` remains the time MARCO saw the event.  A caller can
        subsequently provide an effective time, place, or causal event link;
        the update is a revision of the personal event graph, not a new KG
        assertion or an action execution.
        """
        row = next((item for item in self.state["event_index"]
                    if item["id"] == event_id or item["local_id"] == event_id), None)
        if row is None:
            raise ValueError("unknown_event")
        if effective_at is not None and not isinstance(effective_at, (str, int, float)):
            raise ValueError("invalid_effective_time")
        if place is not None and not isinstance(place, str):
            raise ValueError("invalid_event_place")
        if cause_event_id is not None and not isinstance(cause_event_id, str):
            raise ValueError("invalid_cause_event")
        if cause_event_id is not None and not any(cause_event_id in {item.get("id"), item.get("local_id")}
                                                  for item in self.state["event_index"]):
            raise ValueError("unknown_cause_event")
        if roles is not None and (not isinstance(roles, dict) or
                                  not all(isinstance(key, str) and isinstance(value, str)
                                          for key, value in roles.items())):
            raise ValueError("invalid_event_roles")
        if conditions is not None and not isinstance(conditions, list):
            raise ValueError("invalid_event_conditions")
        revision = {"at": time.time(), "effective_at": effective_at, "place": place,
                    "cause_event_id": cause_event_id, "roles": _portable(roles),
                    "conditions": _portable(conditions)}
        row.setdefault("metadata_revisions", []).append(revision)
        if effective_at is not None:
            row["effective_at"], row["time_status"] = effective_at, "specified"
        if place is not None:
            row["place"] = place
        if cause_event_id is not None:
            row["cause"] = cause_event_id
        if roles is not None:
            row["roles"] = {**row.get("roles", {}), **roles}
        if conditions is not None:
            row["conditions"] = _portable(conditions)
        row["metadata_revision"] = len(row["metadata_revisions"])
        self._log("LIFE", "event_metadata", event_id=row["id"], revision=revision)
        self._save()
        return deepcopy(row)

    def project_state_at(self, effective_at):
        """Reconstruct mutable state at a specified event time.

        Event observation order is deliberately not treated as event time.
        For numeric updates, the first observed ``before`` value is the
        recorded baseline and each event's verified delta is then replayed in
        effective-time order. That lets a late observation about the past be
        placed before an already processed event without rewriting either the
        original event or its historical decision record.
        """
        if not isinstance(effective_at, (str, int, float)):
            raise ValueError("invalid_effective_time")
        rows = [row for row in self.state["event_index"]
                if row.get("execution_status") == "executed" and row.get("state_changes")]
        timed = [row for row in rows if row.get("time_status") == "specified"]
        if not timed:
            result = {"status": "safe_hold", "effective_at": effective_at,
                      "reason": "no_timed_state_changes"}
            self._log("COGNITION", "state_projected", **result)
            self._save()
            return result
        values = [row.get("effective_at") for row in timed] + [effective_at]
        if all(isinstance(value, (int, float)) for value in values):
            key = lambda value: float(value)
        elif all(isinstance(value, str) for value in values):
            key = lambda value: value
        else:
            result = {"status": "safe_hold", "effective_at": effective_at,
                      "reason": "incomparable_effective_times"}
            self._log("COGNITION", "state_projected", **result)
            self._save()
            return result
        if any(row.get("time_status") != "specified" for row in rows):
            result = {"status": "safe_hold", "effective_at": effective_at,
                      "reason": "untimed_state_change"}
            self._log("COGNITION", "state_projected", **result)
            self._save()
            return result

        # ``event_index`` append order preserves the original observed
        # baseline; replay below instead follows actual effective time.
        baseline, state, provenance = {}, {}, {}
        mutable = {change.get("predicate") for row in rows for change in row["state_changes"]}
        changed = {(change.get("subject"), change.get("predicate"))
                   for row in rows for change in row["state_changes"]}
        direct = {}
        for fact in (self.state.get("reasoning_context") or {}).get("replay", {}).get("facts", []):
            triple, evidence = fact.get("triple"), fact.get("evidence") or {}
            if (not isinstance(triple, list) or len(triple) != 3 or triple[1] not in mutable
                    or (triple[0], triple[1]) in changed
                    or evidence.get("action_event") or fact.get("polarity", True) is not True
                    or fact.get("modality", "asserted") != "asserted"):
                continue
            value = triple[2]
            if triple[1] == "count" and isinstance(value, str) and value.lstrip("-").isdigit():
                value = int(value)
            values = direct.setdefault((triple[0], triple[1]), [])
            if value not in values:
                values.append(value)
        for pair, values in direct.items():
            if len(values) == 1:
                baseline[pair] = values[0]
        for row in rows:
            for change in row["state_changes"]:
                subject, predicate = change.get("subject"), change.get("predicate")
                if subject is not None and predicate is not None and "before" in change:
                    baseline.setdefault((subject, predicate), change["before"])
        state.update(baseline)
        ordered = sorted(timed, key=lambda row: (key(row["effective_at"]),
                                                  row.get("observed_at", 0), row["id"]))
        for row in ordered:
            if key(row["effective_at"]) > key(effective_at):
                break
            for change in row["state_changes"]:
                subject, predicate = change.get("subject"), change.get("predicate")
                if subject is None or predicate is None or "after" not in change:
                    continue
                pair = (subject, predicate)
                if change.get("operation") == "quantity_update" and isinstance(change.get("delta"), (int, float)):
                    previous = state.get(pair)
                    if not isinstance(previous, (int, float)):
                        result = {"status": "safe_hold", "effective_at": effective_at,
                                  "reason": "numeric_baseline_unavailable", "subject": subject,
                                  "predicate": predicate}
                        self._log("COGNITION", "state_projected", **result)
                        self._save()
                        return result
                    state[pair] = previous + change["delta"]
                elif pair not in state or state[pair] == change.get("before"):
                    state[pair] = change["after"]
                else:
                    result = {"status": "safe_hold", "effective_at": effective_at,
                              "reason": "time_order_state_conflict", "subject": subject,
                              "predicate": predicate, "event_id": row["id"]}
                    self._log("COGNITION", "state_projected", **result)
                    self._save()
                    return result
                provenance[pair] = {"event_id": row["id"], "effective_at": row["effective_at"],
                                    "operation": change.get("operation")}
        result = {"status": "answered", "effective_at": effective_at,
                  "state": [{"subject": subject, "predicate": predicate, "value": value,
                             "provenance": provenance.get((subject, predicate))}
                            for (subject, predicate), value in sorted(state.items())],
                  "time_basis": "effective_at", "observation_order_preserved": True}
        self._log("COGNITION", "state_projected", effective_at=effective_at,
                  state_count=len(result["state"]))
        self._save()
        return _portable(result)

    def search(self, query, *, kinds=None):
        """Search durable event, memory, mental, affect and log records.

        This is deliberately a transparent ledger search, not semantic
        inference.  Callers can therefore locate the first observed record
        without accidentally treating a later summary as a current fact.
        """
        allowed = set(kinds or {"event", "memory", "mental", "affect", "log", "milestone"})
        needle, rows = str(query).lower(), []

        def include(kind, row):
            if kind in allowed and needle in json.dumps(row, ensure_ascii=False).lower():
                rows.append({"kind": kind, "at": row.get("at", row.get("observed_at")),
                             "record": deepcopy(row)})

        for row in self.state["event_index"]:
            include("event", row)
        for memory_kind in MEMORY_KINDS:
            for row in self.state["memories"][memory_kind]:
                include("memory", {"memory_kind": memory_kind, **row})
        for row in self.state["mental"]:
            include("mental", row)
        for row in self.state["affect"]["causes"]:
            include("affect", row)
        for row in self.state["logs"]:
            include("log", row)
        for row in self.state["milestones"]:
            include("milestone", row)
        return sorted(rows, key=lambda row: (row["at"] is None, row["at"] or 0, row["kind"]))

    def snapshot(self):
        return deepcopy(self.state)
