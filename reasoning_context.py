"""Per-conversation evidence ledger, replayed rather than incrementally reapplied.

Only fully recognized user clauses enter memory. Queries and assistant replies
never become facts. Model changes reparse source text before using old evidence.
"""
from copy import deepcopy
import re

from graph_inference import current_facts
from relational_semantics import RelationalParser


class ReasoningContext:
    def __init__(self, max_turns=128, *, model=None):
        self.observations = []
        self.corrections = []
        self.max_turns = max_turns
        self.model = model

    def _permitted(self, knowledge_path):
        from state_engine import _knowledge
        return (self.model.permits("relational_graph") if self.model is not None
                else "relational_graph" in _knowledge(knowledge_path)["axioms"])

    def _parser(self):
        return RelationalParser() if self.model is None else self.model.parser()

    def _verification(self, knowledge_path, checks):
        if self.model is None:
            return {"sources": [str(knowledge_path)], "checks": checks}
        return {"sources": [item["path"] for item in self.model.sources], "checks": checks,
                "model": self.model.fingerprint, "model_assets": self.model.sources}

    def snapshot(self):
        return {"schema": "reasoning-context-v2", "observations": list(self.observations),
                "corrections": deepcopy(self.corrections)}

    def restore(self, snapshot):
        if (not isinstance(snapshot, dict) or snapshot.get("schema") not in {"reasoning-context-v1", "reasoning-context-v2"}
                or not isinstance(snapshot.get("observations"), list)
                or len(snapshot["observations"]) > self.max_turns
                or any(not isinstance(x, str) or not x.strip() for x in snapshot["observations"])):
            raise ValueError("invalid_reasoning_context_snapshot")
        corrections = snapshot.get("corrections", [])
        if (not isinstance(corrections, list) or len(corrections) > self.max_turns
                or any(not isinstance(x, dict) or type(x.get("index")) is not int
                       or not 0 <= x["index"] < len(snapshot["observations"])
                       or any(not isinstance(x.get(k), str) or not x[k].strip() for k in ("before", "after"))
                       for x in corrections)):
            raise ValueError("invalid_reasoning_context_snapshot")
        self.observations = list(snapshot["observations"])
        self.corrections = deepcopy(corrections)

    @staticmethod
    def _replay(parser, sources):
        facts = []
        for index, source in enumerate(sources):
            parsed = parser.parse(source, partial=True)
            if parsed is None:
                raise ValueError("unrecognized_observation")
            for item in parsed["facts"]:
                item = deepcopy(item)
                item["evidence"].update(turn=index, source=source)
                facts.append(item)
        return facts

    def correct(self, index, replacement, knowledge_path=None):
        """Replace one identified observation atomically, then replay all events.

        A correction is not a new event appended to the current quantity. Later
        observations retain their ordering and derived conclusions are rebuilt.
        """
        if not self._permitted(knowledge_path):
            raise ValueError("operator_not_declared_in_kg")
        if type(index) is not int or not 0 <= index < len(self.observations):
            raise ValueError("unknown_correction_target")
        if len(self.corrections) >= self.max_turns:
            raise ValueError("correction_capacity")
        parser = self._parser()
        parsed = parser.parse(replacement, partial=True)
        if not parsed or not parsed["facts"] or parsed["query"]:
            raise ValueError("correction_requires_observation")
        pending = list(self.observations)
        before = pending[index]
        pending[index] = replacement
        facts = self._replay(parser, pending)
        _, changes = current_facts(facts, parser.data.get("mutable_predicates", []),
                                   parser.data.get("numeric_updates", {}))
        record = {"index": index, "before": before, "after": replacement}
        self.observations = pending
        self.corrections.append(record)
        return {"operator": "relational_graph", "status": "observed",
                "answer": parser.data["context_replies"].get("corrected", parser.data["context_replies"]["observed"]),
                "transitions": [{"operation": "correction", **record}] + changes,
                "verification": self._verification(knowledge_path, [{"ok": True, "observation_turns": len(pending)}])}

    def turn(self, text, knowledge_path=None):
        if not self._permitted(knowledge_path):
            return None
        parser = self._parser()
        correction = parser.data.get("context_correction", {})
        for prefix in correction.get("prefixes", []):
            if text.strip().startswith(prefix):
                body = text.strip()[len(prefix):].strip()
                parts = body.split(correction["separator"])
                try:
                    if len(parts) != 2 or not all(part.strip() for part in parts):
                        raise ValueError("invalid_correction_syntax")
                    normalize = lambda value: re.sub(r"[.!?]+$", "", value.strip()).strip()
                    matches = [i for i, old in enumerate(self.observations)
                               if normalize(old) == normalize(parts[0])]
                    if len(matches) != 1:
                        raise ValueError("ambiguous_or_missing_correction_target")
                    return self.correct(matches[0], parts[1].strip(), knowledge_path)
                except ValueError as exc:
                    return {"operator": "relational_graph", "status": "unresolved",
                            "answer": parser.data["context_replies"]["correction_invalid"], "transitions": [],
                            "verification": self._verification(knowledge_path, [{"ok": False, "reason": str(exc)}])}
        current = parser.parse(text, partial=True)
        if current is None:
            return None
        replies = parser.data["context_replies"]
        result = {"operator": "relational_graph", "transitions": [],
                  "verification": self._verification(knowledge_path, [])}
        if current["facts"] and len(self.observations) >= self.max_turns:
            return {**result, "status": "unresolved", "answer": replies["capacity"]}
        pending = self.observations + ([text] if current["facts"] else [])
        try:
            facts = self._replay(parser, pending)
            # Validate a new observation even if no question has been asked yet.
            _, changes = current_facts(facts, parser.data.get("mutable_predicates", []),
                                       parser.data.get("numeric_updates", {}))
            outcome = parser.answer({"facts": facts, "query": current["query"]}) if current["query"] else None
        except ValueError as exc:
            result["verification"]["checks"].append({"ok": False, "reason": str(exc)})
            return {**result, "status": "unresolved", "answer": replies["invalid"]}
        self.observations = pending
        result["verification"]["checks"].append({"ok": True, "observation_turns": len(pending)})
        if outcome:
            return {**result, **outcome, "status": "answered"}
        return {**result, "status": "unresolved" if current["query"] else "observed",
                "answer": replies["unresolved"] if current["query"] else replies["observed"],
                "transitions": changes}
