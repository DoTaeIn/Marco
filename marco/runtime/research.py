"""Answers over isolated source observations, never persistent world facts.

This first slice accepts ordinary binary-fact queries only. Every included
claim must have the same explicit caller-declared source scope. That condition
is an interpretation assumption, not proof of sourced time, and is exposed in
every result. Unscoped web claims, events, updates, conflicting/partial
reports and unreadable statements are held. Fetch time never supplies scope.

The answer text is composed by the language helper from declared parser
examples; source sentences are evidence/citations only, never the answer.
Only the ordinary Horn graph engine proves a conclusion. Citations identify
exact asserted leaves of one selected proof, and the emitted full statement
must parse back to that conclusion. Parser operations use a fresh clone
without conversation hooks. No ReasoningContext, learning or persistence API
is imported or called.
"""
from __future__ import annotations

import copy
import json

from relational_semantics import RelationalParser, substitute
from marco.language.realizer.source_answer import (
    compose_statement, has_declared_output_time, statement_matches,
)
from marco.reasoning.inference import bind, closure_with_provenance, current_facts
from marco.knowledge.ingest.retrieval import public_url


_OTHER_MEANING = ("정의", "사건", "가정사건", "조건", "가정", "원인", "이유물음", "수선", "사건정정")


class _Hold(ValueError):
    pass


def _fact_signature(fact):
    return (tuple(fact["triple"]), fact.get("polarity", True), fact.get("modality", "asserted"))


def _plain_reading(parsed, *, query=False):
    return (isinstance(parsed, dict) and isinstance(parsed.get("facts"), list)
            and not any(parsed.get(key) for key in _OTHER_MEANING)
            and (bool(parsed.get("query")) and not parsed["facts"] if query else not parsed.get("query")))


class ResearchAnswerer:
    def __init__(self, parser):
        self.parser = parser

    def answer(self, report, question=None, parsed_query=None, source_scope=None):
        """Return an unverified, scoped source answer or an explicit hold.

        ``source_scope`` must equal each claim's scope; it never manufactures a
        missing claim scope. ``parsed_query`` is optional but must match a fresh
        strict reading of ``question`` (or the report query). Caller parser
        state, report dictionaries and persistent conversations remain intact.
        """
        base = {"status": "hold", "answer": None, "reason": None,
                "mode": report.get("mode") if isinstance(report, dict) else None,
                "verified": False, "truth_status": "source_observed",
                "qualification": "Only cited source observations under the declared interpretation; not verified world truth.",
                "scope_assumption": {"value": copy.deepcopy(source_scope),
                                     "kind": "caller_declared_interpretation", "sourced_time": False},
                "candidate_answer": None, "matched_fact": None, "proof": None, "citations": [],
                "clarification": None}
        try:
            if not isinstance(report, dict) or base["mode"] not in {"actual_web", "offline_fixture"}:
                raise _Hold("invalid_report_mode")
            if source_scope is None or not isinstance(source_scope, (str, dict)) or not source_scope:
                raise _Hold("unknown_source_scope")
            json.dumps(source_scope)
            if report.get("conflicts"):
                raise _Hold("conflicting_source_observations")
            if report.get("claims_truncated"):
                raise _Hold("incomplete_claim_report")
            # Reconstruct a native reader, without closure/rule selectors or
            # recorder hooks that a conversation may have attached to it.
            parser = RelationalParser(data=copy.deepcopy(self.parser.data),
                                      language_pack=copy.deepcopy(self.parser.language_pack))
            question = report.get("query") if question is None else question
            if not isinstance(question, str) or not question.strip() or len(question) > 2000:
                raise _Hold("unreadable_query")
            # ``partial`` permits a standalone fact or question instead of a
            # complete facts+question story; unknown clauses still fail. The
            # fact-only/query-only checks below constrain that return shape.
            request = parser.parse(question, partial=True)
            if not _plain_reading(request, query=True):
                raise _Hold("unreadable_or_nonquery_input")
            if parsed_query is not None and (not _plain_reading(parsed_query, query=True)
                                             or parsed_query["query"] != request["query"]):
                raise _Hold("query_roundtrip_failed")
            queries = request["query"]
            if (not isinstance(queries, list) or len(queries) > 8
                    or any(not isinstance(q, dict) or not self._triple(q.get("triple")) for q in queries)):
                raise _Hold("unsupported_query")
            facts, origins = self._ground_claims(report, parser, source_scope)
            self._reject_disagreement(facts, parser.data)
            # Collapse agreeing duplicate triples only after inspecting every
            # claim; mutable replay cannot silently discard a disagreement.
            canonical = {}
            for fact in facts:
                canonical.setdefault(_fact_signature(fact), fact)
            facts = list(canonical.values())
            replayed, _ = current_facts(facts, parser.data.get("mutable_predicates", []),
                                       parser.data.get("numeric_updates", {}))
            if {_fact_signature(f) for f in replayed} != {_fact_signature(f) for f in facts}:
                raise _Hold("source_replay_changed_meaning")
            ledger = closure_with_provenance(facts, parser.data.get("rules", []),
                                             limit=512, proof_limit=8, search_limit=8192)
            if not ledger["complete"]:
                raise _Hold("incomplete_graph_proof")
            matches = [(q, list(f), bind(q["triple"], f, {})) for q in queries for f in ledger["facts"]
                       if bind(q["triple"], f, {}) is not None]
            if len(matches) != 1:
                raise _Hold("no_unique_matching_evidence")
            query, target, bindings = matches[0]
            outcome = parser.answer({**copy.deepcopy(request), "facts": copy.deepcopy(facts)})
            steps = [row for row in (outcome or {}).get("transitions", [])
                     if isinstance(row, dict) and self._triple(row.get("fact"))]
            if not steps or list(steps[-1]["fact"]) != target:
                raise _Hold("ordinary_answer_proof_mismatch")
            bound = substitute(query, {key[1:]: value for key, value in bindings.items()})
            expected = ("".join(bound["render"]) if "render" in bound
                        else bound["answer"] + parser.data["answer_suffix"])
            if outcome.get("answer") != expected:
                raise _Hold("ordinary_answer_render_mismatch")
            proof, leaves = self._selected_proof(ledger, target, origins)
            citations = []
            for claim_id in leaves:
                origin = origins[claim_id]
                citations.append({"claim_id": claim_id, "observation_id": origin["observation"]["id"],
                                  "source_id": origin["source"]["id"], "url": origin["url"],
                                  "title": origin["source"].get("title", ""),
                                  "text": origin["observation"]["text"],
                                  "fetched_at": origin["source"]["fetched_at"]})
            # A rendering hold does not erase a complete, grounded proof.
            # These citations are evidence about what the sources stated,
            # never a candidate answer or a promoted world fact.
            base.update(matched_fact=target, proof=proof, citations=citations)
            if not has_declared_output_time(parser, target):
                base["clarification"] = {"kind": "missing_interpretation",
                                         "missing": "time_interpretation", "question": None}
                raise _Hold("missing_declared_output_time")
            statement = compose_statement(parser, target)
            if not statement_matches(parser, statement, target):
                raise _Hold("answer_semantic_roundtrip_failed")
            base.update(status="answered", answer=statement, matched_fact=target, proof=proof, citations=citations,
                        candidate_answer={"text": statement, "truth_status": "source_observed", "verified": False,
                                          "scope_assumption": copy.deepcopy(base["scope_assumption"]),
                                          "qualification": base["qualification"]})
            return base
        except _Hold as exc:
            base["reason"] = str(exc)
        except Exception:
            # Network/source/semantic failures never turn into an answer or
            # arbitrary exception text that might contain a private payload.
            base["reason"] = "invalid_or_unsupported_evidence"
        return base

    @staticmethod
    def _triple(triple):
        return (isinstance(triple, (list, tuple)) and len(triple) == 3
                and all(isinstance(value, str) and value and len(value) <= 2000 for value in triple))

    def _ground_claims(self, report, parser, scope):
        rows = report.get("claims")
        if not isinstance(rows, list) or not rows or len(rows) > 256:
            raise _Hold("no_or_excessive_parsed_source_claims")
        sources = self._index(report.get("sources"), 8)
        observations = self._index(report.get("observations"), 256)
        graph = report.get("graph") or {}
        nodes = self._index(graph.get("nodes"), 1024)
        edges = graph.get("edges")
        if not isinstance(edges, list) or len(edges) > 2048:
            raise _Hold("incomplete_source_provenance")
        by_observation = {}
        for row in rows:
            if not isinstance(row, dict) or not self._triple(row.get("triple")):
                raise _Hold("invalid_source_claim")
            by_observation.setdefault(row.get("observation_id"), []).append(row)
        facts, origins, readings = [], {}, {}
        for claim in rows:
            if (not isinstance(claim, dict) or not isinstance(claim.get("id"), str)
                    or not claim["id"] or claim["id"] in origins or not self._triple(claim.get("triple"))):
                raise _Hold("invalid_source_claim")
            if claim.get("status") != "observed" or claim.get("trusted") is not False:
                raise _Hold("pending_or_trusted_claim_not_source_observation")
            if claim.get("scope") is None or claim["scope"] != scope:
                raise _Hold("unknown_or_mismatched_source_scope")
            if claim.get("modality", "asserted") != "asserted" or type(claim.get("polarity", True)) is not bool:
                raise _Hold("nonasserted_source_claim")
            source = sources.get(claim.get("source_id"))
            observation = observations.get(claim.get("observation_id"))
            if (not source or not observation or source.get("status") != "ok"
                    or observation.get("source_id") != source["id"]
                    or observation.get("status") != "observed" or observation.get("trusted") is not False
                    or not isinstance(source.get("fetched_at"), str)
                    or observation.get("text") not in (source.get("sentences") or [])
                    or (claim.get("evidence") or {}).get("text") != observation.get("text")):
                raise _Hold("incomplete_source_provenance")
            url = public_url(source.get("final_url") or source.get("url"))
            node_claim, node_observation, node_source = (nodes.get(claim["id"]), nodes.get(observation["id"]),
                                                       nodes.get(source["id"]))
            if (not node_claim or node_claim.get("kind") != "parsed_claim"
                    or node_claim.get("triple") != claim["triple"]
                    or node_claim.get("polarity", True) != claim.get("polarity", True)
                    or not node_observation or node_observation.get("text") != observation["text"]
                    or not node_source or public_url(node_source.get("url")) != url
                    or not any(e.get("source") == claim["id"] and e.get("target") == observation["id"]
                               and e.get("relation") == "parsed_from" for e in edges)
                    or not any(e.get("source") == observation["id"] and e.get("target") == source["id"]
                               and e.get("relation") == "provenance" for e in edges)):
                raise _Hold("incomplete_source_graph_provenance")
            if observation["id"] not in readings:
                parsed = parser.parse(observation["text"], partial=True)
                if (not _plain_reading(parsed) or not parsed["facts"]
                        or any(f.get("modality", "asserted") != "asserted" for f in parsed["facts"])):
                    raise _Hold("unreadable_or_nonasserted_source_statement")
                # Ground the whole included observation, not a convenient
                # positive subset. This also detects a per-observation fact
                # cap even when its report omitted a truncation flag.
                expected = {_fact_signature(f) for f in parsed["facts"]}
                represented = {_fact_signature(f) for f in by_observation[observation["id"]]}
                if expected != represented:
                    raise _Hold("incomplete_observation_semantics")
                readings[observation["id"]] = parsed
            parsed_facts = readings[observation["id"]]["facts"]
            if not any(_fact_signature(f) == _fact_signature(claim) for f in parsed_facts):
                raise _Hold("claim_semantic_roundtrip_failed")
            if any(f.get("scope") is not None and f["scope"] != scope for f in parsed_facts
                   if _fact_signature(f) == _fact_signature(claim)):
                raise _Hold("semantic_scope_mismatch")
            facts.append({"id": claim["id"], "triple": list(claim["triple"]),
                          "polarity": claim.get("polarity", True), "modality": "asserted", "scope": copy.deepcopy(scope),
                          "evidence": {"text": observation["text"], "claim_id": claim["id"],
                                       "observation_id": observation["id"], "source_id": source["id"], "url": url}})
            origins[claim["id"]] = {"claim": claim, "observation": observation, "source": source, "url": url}
        return facts, origins

    @staticmethod
    def _index(rows, limit):
        if not isinstance(rows, list) or len(rows) > limit:
            raise _Hold("invalid_source_provenance_table")
        result = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"] or row["id"] in result:
                raise _Hold("invalid_source_provenance_identifier")
            result[row["id"]] = row
        return result

    @staticmethod
    def _reject_disagreement(facts, data):
        signed, mutable = {}, {}
        for fact in facts:
            triple = tuple(fact["triple"])
            polarity = fact.get("polarity", True)
            if triple in signed and signed[triple] != polarity:
                raise _Hold("opposed_source_facts")
            signed[triple] = polarity
            if triple[1] in data.get("numeric_updates", {}):
                raise _Hold("source_update_event_unsupported")
            if polarity and triple[1] in data.get("mutable_predicates", []):
                key = triple[:2]
                if key in mutable and mutable[key] != triple[2]:
                    raise _Hold("ambiguous_mutable_source_values")
                mutable[key] = triple[2]

    @staticmethod
    def _selected_proof(ledger, target, origins):
        table = {bundle["id"]: bundle for rows in ledger["proof_bundles"].values() for bundle in rows}
        options = ledger["proof_bundles"].get(tuple(target)) or []
        if not options:
            raise _Hold("missing_graph_proof")
        ordered, leaves, visiting, seen = [], [], set(), set()
        def visit(identifier):
            if identifier in visiting or identifier not in table:
                raise _Hold("incomplete_graph_provenance")
            if identifier in seen:
                return
            visiting.add(identifier)
            bundle = table[identifier]
            if not bundle.get("valid"):
                raise _Hold("invalid_graph_proof")
            if bundle["kind"] == "asserted":
                ids = bundle["premise_fact_ids"]
                if len(ids) != 1 or ids[0] not in origins:
                    raise _Hold("uncited_asserted_proof_leaf")
                if ids[0] not in leaves:
                    leaves.append(ids[0])
            elif bundle["kind"] == "derived":
                for parent in bundle["premise_fact_ids"]:
                    visit(parent)
            else:
                raise _Hold("unsupported_graph_proof")
            visiting.remove(identifier)
            seen.add(identifier)
            ordered.append(copy.deepcopy(bundle))
        visit(options[0]["id"])
        return {"root": options[0]["id"], "conclusion": list(target), "bundles": ordered,
                "complete": True, "searches": ledger["searches"]}, leaves
