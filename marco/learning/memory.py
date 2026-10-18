"""Durable, user-taught expression memory over an immutable base parser.

Teaching is gated by ``expressions.propose`` against validation meanings computed
from the immutable base only. Accepted expressions are approved internally; the
public API exposes no approval switch, and observations stay inert. Overlay rule
bodies are records replayed through the gate, never inference rules.

Optional ``graph_binding`` scopes the immutable store identity to a selected
graph/model SHA256 as well as its parser data and language pack. Omitting it
keeps the original parser-only identity for legacy callers.
"""
import copy
import hashlib
import json
import os
import uuid

from marco.learning import expressions
from marco.storage.overlay import OverlayStore, add_rule, disable_rule, dumps

SCHEMA = "marco-learning-memory-v1"
SUPERVISION = "explicit_user_teaching"
PAYLOAD_KEYS = {"text", "equivalent", "validation"}
LEX_KIND = 'lexical_action_meaning'
LEX_VERSION = 'lexical-action-meaning-v1'
LEX_SUPERVISION = 'explicit_user_lexical_action_confirmation'
LEX_TARGET_SCHEMA = 'lexical-action-meaning-target-v1'
LEX_BINDING_SCHEMA = 'selected-action-learning-binding-v1'
LEX_REPORT_SCHEMA = 'lexical-action-meaning-gate-v1'
LEX_REPORT_REASON = 'explicit_scoped_archived_confirmation'
LEX_CRITERION_ID = 'explicit_user_lexical_action_confirmation_v1'
LEX_SCOPE = 'surface_role_pattern_to_exhaustive_ordered_known_programs_v1'
LEX_RECORD_KEYS = ('schema', 'kind', 'record_version', 'record_sha256', 'payload', 'binding',
                   'provenance', 'report', 'supervision', 'replaces')
LEX_PREIMAGE_KEYS = ('schema', 'kind', 'record_version', 'payload', 'binding', 'provenance',
                     'supervision', 'replaces')
LEX_ATTACH_BYTES = 1048576
CASE_KEYS = {"id", "text", "equivalent", "unrecognized"}
ACTOR, SOURCE = "learner", "conversation"


class MemoryLimitError(ValueError):
    """A bound, provenance rule or JSON requirement was violated before any proposal."""


class MemoryReplayError(RuntimeError):
    """Stored expressions do not replay to the recorded, validated state."""


def _positive(name, value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise MemoryLimitError("%s must be a positive int" % name)
    return value


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def _graph_binding(value):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdefABCDEF" for c in value):
        raise MemoryLimitError("graph_binding must be a 64-hex sha256 string")
    return value.lower()


class LearningMemory:
    def __init__(self, path, base_parser, *, graph_binding=None, candidate_limit=128,
                 validation_limit=16, payload_bytes_limit=32768, action_projection=None,
                 action_learning_projection=None, action_binding=None, dialogue_ledger=None):
        self.candidate_limit = _positive("candidate_limit", candidate_limit)
        self.validation_limit = _positive("validation_limit", validation_limit)
        self.payload_bytes_limit = _positive("payload_bytes_limit", payload_bytes_limit)
        binding = _graph_binding(graph_binding)
        self._graph_binding = binding
        self._attach_action_learning(action_projection, action_learning_projection,
                                     action_binding, dialogue_ledger)
        self._data = copy.deepcopy(base_parser.data)
        self._pack = copy.deepcopy(base_parser.language_pack)
        identity = {"data": self._data, "language_pack": self._pack}
        if binding is not None:
            identity["graph_binding"] = binding
        sha = hashlib.sha256(dumps(identity).encode("utf-8")).hexdigest()
        path = os.fspath(path)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        if os.path.exists(path):
            self._store = OverlayStore.open(path, base_sha256=sha, base_build_id=SCHEMA, writer=True)
        else:
            self._store = OverlayStore.create(path, base_sha256=sha, base_build_id=SCHEMA,
                                              format_version=1)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        self._store.close()

    # --- public API ------------------------------------------------------------------

    def teach(self, payload, provenance, *, replaces=None, expression_kind="fact"):
        if type(expression_kind) is not str or expression_kind not in ("fact", "query"):
            raise ValueError("invalid_expression_kind")
        payload = self._bounded(payload, "payload")
        provenance = self._bounded(provenance, "provenance")
        self._bounded({"payload": payload, "provenance": provenance}, "teaching")
        if not isinstance(payload, dict) or set(payload) - PAYLOAD_KEYS:
            raise MemoryLimitError("unsupported_payload_keys")
        if not isinstance(provenance, dict) or not (
                _nonempty(provenance.get("conversation_id")) and _nonempty(provenance.get("turn_id"))):
            raise MemoryLimitError("teach_provenance_requires_conversation_id_and_turn_id")
        validation = payload.get("validation")
        if isinstance(validation, list) and len(validation) > self.validation_limit:
            raise MemoryLimitError("validation_limit_exceeded")
        self._room()
        old = self._active_rule(replaces) if replaces is not None else None
        current = self._replay(self._store, exclude=old["id"] if old else None)
        if expression_kind == "query":
            report = self._evaluate(current, payload, expression_kind=expression_kind)
        else:
            report = self._evaluate(current, payload)
        record = {"schema": SCHEMA, "kind": "expression", "payload": payload,
                  "annotation": report["inferred_annotation"], "provenance": provenance,
                  "report": report, "supervision": SUPERVISION, "replaces": replaces}
        rule_id, cid = "memory:" + uuid.uuid4().hex, "cand_" + uuid.uuid4().hex
        accepted = report["accepted"]
        deltas = [add_rule(rule_id, record, revision=0)]
        if accepted and old:
            deltas.append(disable_rule(old["id"], revision=old["revision"]))
        evidence = {"operation": "replace" if replaces else "teach", "candidate_id": cid,
                    "rule_id": rule_id, "kind": "expression", "report": report}
        self._store.propose(deltas, actor=ACTOR, source=SOURCE, reason="explicit user teaching",
                            evidence=evidence, candidate_id=cid)
        if not accepted:
            self._store.reject(cid, rejected_by="learning-gate", reason=dumps(report))
        else:
            try:
                self._store.approve(cid, approved_by="learning-memory",
                                    validation=report,
                                    check=lambda store: self._replay(store))
            except MemoryReplayError as e:
                self._store.reject(cid, rejected_by="learning-gate", reason="replay_invalidated: %s" % e)
        return self._view(self._store.candidate(cid))

    def teach_patterns(self, payload, provenance, *, replaces=None):
        payload = self._bounded(payload, "payload")
        provenance = self._bounded(provenance, "provenance")
        self._bounded({"payload": payload, "provenance": provenance}, "teaching")
        if not isinstance(payload, dict) or set(payload) != {"demonstrations", "validation"}:
            raise MemoryLimitError("unsupported_payload_keys")
        if not isinstance(provenance, dict) or not (
                _nonempty(provenance.get("conversation_id")) and _nonempty(provenance.get("turn_id"))):
            raise MemoryLimitError("teach_provenance_requires_conversation_id_and_turn_id")
        validation = payload.get("validation")
        if isinstance(validation, list) and len(validation) > self.validation_limit:
            raise MemoryLimitError("validation_limit_exceeded")
        self._room()
        old = self._active_rule(replaces) if replaces is not None else None
        current = self._replay(self._store, exclude=old["id"] if old else None)
        report, graph = self._evaluate_graph(current, payload)
        record = {"schema": SCHEMA, "kind": "expression", "payload": payload,
                  "annotation": report["inferred_annotations"], "pattern_graph": graph,
                  "provenance": provenance, "report": report, "supervision": SUPERVISION,
                  "replaces": replaces}
        rule_id, cid = "memory:" + uuid.uuid4().hex, "cand_" + uuid.uuid4().hex
        accepted = report["accepted"]
        deltas = [add_rule(rule_id, record, revision=0)]
        if accepted and old:
            deltas.append(disable_rule(old["id"], revision=old["revision"]))
        evidence = {"operation": "replace" if replaces else "teach", "candidate_id": cid,
                    "rule_id": rule_id, "kind": "expression", "report": report}
        self._store.propose(deltas, actor=ACTOR, source=SOURCE, reason="explicit user teaching",
                            evidence=evidence, candidate_id=cid)
        if not accepted:
            self._store.reject(cid, rejected_by="learning-gate", reason=dumps(report))
        else:
            try:
                self._store.approve(cid, approved_by="learning-memory",
                                    validation=report,
                                    check=lambda store: self._replay(store))
            except MemoryReplayError as e:
                self._store.reject(cid, rejected_by="learning-gate", reason="replay_invalidated: %s" % e)
        return self._view(self._store.candidate(cid))

    def _evaluate_graph(self, parser, payload, *, entry_origin=None):
        from marco.learning import expression_graph as eg
        base, graph, annotations = self._fresh(), None, None
        try:
            demos = payload.get("demonstrations")
            if (not isinstance(demos, list) or not 2 <= len(demos) <= 8
                    or any(not isinstance(d, dict) or set(d) != {"text", "equivalent"} for d in demos)):
                raise ValueError("invalid_demonstrations")
            cases = self._expected(base, payload.get("validation"))
            # New graph admission requires genuinely flat positive reference semantics;
            # the classic _reference reducer intentionally remains unchanged.
            for case in payload["validation"]:
                if "equivalent" not in case:
                    continue
                raw = base.parse(case["equivalent"], partial=True)
                if type(raw) is not dict:
                    raise ValueError("graph_validation_requires_positive_flat_reference")
                for field in ("definitions", "definition", "events", "condition", "assumption", "reason",
                              "cause", "hypothesis", "correction", "repair", "정의", "사건", "가정사건", "조건", "가정",
                              "원인", "이유물음", "수선", "사건정정"):
                    if field in raw and raw[field] not in (None, [], {}, ""):
                        raise ValueError("graph_validation_requires_positive_flat_reference")
                facts = raw.get("facts")
                if (raw.get("query") not in (None, []) or type(facts) is not list or len(facts) != 1
                        or type(facts[0]) is not dict
                        or set(facts[0]) - {"triple", "evidence", "polarity", "modality"}
                        or facts[0].get("polarity", True) is not True
                        or facts[0].get("modality", "asserted") != "asserted"):
                    raise ValueError("graph_validation_requires_positive_flat_reference")
                triple = facts[0].get("triple")
                if (type(triple) is not list or len(triple) != 3
                        or any(type(term) is not str or not term.strip() or "$" in term or "?" in term
                               for term in triple)):
                    raise ValueError("graph_validation_requires_positive_flat_reference")
            entities = set()
            for d in demos:
                self._reference(base, d["equivalent"])
                ann = expressions.from_paraphrase(base, d["text"], d["equivalent"])
                entities.update(v for v in ann["slots"].values())
            for case in cases:
                if any(e in case["text"] for e in entities):
                    raise ValueError("training_validation_entity_overlap")
            graph = eg.induce_pattern_graph(base, demos)
            annotations = eg.graph_annotations(graph)
            report = eg.propose_pattern_graph(parser, graph, cases, entry_origin=entry_origin)
        except (ValueError, KeyError, TypeError) as e:
            report = {"kind": "validated_supervised_expression", "accepted": False,
                      "reason": str(e) or type(e).__name__, "validation": []}
        report["inferred_annotations"] = annotations if annotations is not None else []
        report["induction_policy"] = "selected-reference-choice-graph-v1"
        return json.loads(dumps(report)), (json.loads(dumps(graph)) if graph is not None else None)

    def parser(self):
        diagnostic = {"scope": "installed_expression_origin_transport", "status": "available", "issues": []}
        try:
            origins = self.installed_expression_origins()
        except MemoryReplayError as e:
            origins = None
            diagnostic["status"] = "incomplete"
            diagnostic["issues"].append({"code": "catalog_unavailable", "error_type": type(e).__name__[:256],
                                         "error_reason": str(e)[:256]})
        return self._replay(self._store, origins=origins, origin_diagnostic=diagnostic)

    def candidates(self):
        return [self._view(c) for c in self._store.candidates()]

    def retract(self, candidate_id, reason, *, expected_head=None, source=None):
        if not _nonempty(reason):
            raise MemoryLimitError("retraction_requires_reason")
        if self._lam_is_lexical(candidate_id):
            return self._lam_withdraw(candidate_id, reason, expected_head, source)
        rule = self._active_rule(candidate_id)
        self._store.commit([disable_rule(rule["id"], revision=rule["revision"])],
                           actor=ACTOR, source=SOURCE, reason=reason, approved_by="learning-retraction",
                           evidence={"operation": "retract", "candidate_id": candidate_id},
                           check=lambda store: self._replay(store))
        return self._view(self._store.candidate(candidate_id))

    def observe(self, meaning, provenance):
        meaning = self._bounded(meaning, "meaning")
        provenance = self._bounded(provenance, "provenance")
        self._bounded({"meaning": meaning, "provenance": provenance}, "observation")
        if not isinstance(provenance, dict) or not (
                _nonempty(provenance.get("source_id")) or _nonempty(provenance.get("conversation_id"))):
            raise MemoryLimitError("observation_provenance_requires_source_id_or_conversation_id")
        self._room()
        report = {"accepted": False, "reason": "inert_observation"}
        record = {"schema": SCHEMA, "kind": "observation", "payload": {"meaning": meaning},
                  "annotation": None, "provenance": provenance, "report": report,
                  "supervision": "source_observation", "replaces": None, "trusted": False}
        rule_id, cid = "memory:" + uuid.uuid4().hex, "cand_" + uuid.uuid4().hex
        evidence = {"operation": "observe", "candidate_id": cid, "rule_id": rule_id,
                    "kind": "observation", "report": report}
        self._store.propose([add_rule(rule_id, record, revision=0)], actor=ACTOR, source=SOURCE,
                            reason="inert observation", evidence=evidence, candidate_id=cid)
        return self._view(self._store.candidate(cid))

    # --- internals -------------------------------------------------------------------

    # --- lexical action-meaning typed transport (structural only; admission unavailable) ---

    def learn_action_meaning(self, payload, source, *, expected_head, replaces=None):
        from marco.storage.overlay import OverlayConflict
        eq = self._lam_eq
        if replaces is not None:
            raise MemoryLimitError('replacement_declaration_unavailable')
        src = self._lx_obj(source, ('ledger_source_id', 'question_output_id', 'confirmation_input_id'), 'source')
        for k in src:
            self._lx_str(src[k], 'source_' + k, 128)
        target = self._canonical_action_target(self._lx_plain(payload, 'payload', self.payload_bytes_limit))
        att = self._action_attachment
        if att is None:
            raise MemoryLimitError('action_meaning_unavailable:feature_unavailable')
        cands = self._store.candidates()
        if len(cands) > self.candidate_limit:
            raise MemoryReplayError('corrupt_action_mutation:candidate_limit')
        for cand in cands:
            got = self._lam_candidate_record(cand)
            if got is None:
                continue
            prov = got[0]['provenance']
            if (prov['ledger_source_id'] != src['ledger_source_id']
                    or prov['confirmation']['input_event_id'] != src['confirmation_input_id']):
                continue
            if (not eq(got[0]['payload'], target) or prov['question']['output_id'] != src['question_output_id']
                    or not eq(got[0]['binding'], att['action_binding'])):
                raise OverlayConflict('confirmation %s is stored with a different action meaning'
                                      % src['confirmation_input_id'])
            return self._view(cand)
        record = self._resolve_action_source(target, src)
        head = self._lam_head(expected_head)
        prior, rows = self._lam_prehead(self._store, head[0])
        if tuple(self._store.head()) != tuple(head):
            raise MemoryLimitError('action_meaning_stale_head')
        hit = self._lam_scope(rows, record)
        if hit is not None:
            view = self._view(self._store.candidate(hit['candidate_id']))
            view['action_meaning_outcome'] = 'already_active'
            view['source_replaced'] = False
            return view
        self._room()
        ident = self._action_record_identity(record)
        cid, rid = ident['candidate_id'], ident['rule_id']
        request = [add_rule(rid, record, revision=0, graph=None)]
        evidence = {'operation': 'teach_action_meaning', 'candidate_id': cid, 'rule_id': rid,
                    'kind': LEX_KIND, 'record_sha256': record['record_sha256'],
                    'report': record['report']}
        self._store.propose(request, actor=ACTOR, source=SOURCE,
                            reason='explicit user action meaning confirmation',
                            evidence=evidence, candidate_id=cid)
        pend = self._store.candidate(cid)
        digest = hashlib.sha256(dumps(request).encode('utf-8')).hexdigest()
        if (type(pend) is not dict or pend['status'] != 'pending' or pend['change_seq'] is not None
                or not eq(pend['deltas'], request) or not eq(pend['evidence'], evidence)
                or pend['request_digest'] != digest or pend['candidate_id'] != cid
                or pend['actor'] != ACTOR or pend['source'] != SOURCE):
            raise MemoryReplayError('corrupt_action_mutation:proposed_candidate')
        pseq = pend['proposed_at_seq']
        if type(pseq) is not int or pseq < head[0]:
            raise MemoryReplayError('corrupt_action_mutation:proposed_candidate')
        cur = self._store.head()
        if pseq != head[0] or cur[0] != head[0]:
            prior_ok = (type(cur[0]) is int and cur[0] >= head[0]
                        and (head[0] == 0 or self._store.change(head[0])['change_id'] == head[1]))
            if prior_ok and cur[0] > head[0] and cur[0] >= pseq:
                raise MemoryLimitError('action_meaning_stale_head')
            raise MemoryReplayError('corrupt_action_mutation:proposed_candidate')
        self._store.approve(cid, approved_by='learning-memory-action-meaning',
                            validation=record['report'],
                            check=lambda store: self._lam_admit_check(store, cid, rid, record, request,
                                                                       evidence, head[0], head[1]))
        return self._view(self._store.candidate(cid))

    @staticmethod
    def _lam_eq(a, b):
        try:
            return dumps(a) == dumps(b)
        except (TypeError, ValueError, RecursionError):
            return False

    def _lam_head(self, expected):
        h = self._store.head()
        ok = (type(expected) is dict and set(expected) == {'seq', 'change_id'}
              and type(expected['seq']) is int and expected['seq'] >= 0
              and ((expected['seq'] == 0) == (expected['change_id'] is None))
              and (expected['change_id'] is None
                   or (_nonempty(expected['change_id']) and len(expected['change_id']) <= 128)))
        if not ok or expected['seq'] != h[0] or expected['change_id'] != h[1]:
            raise MemoryLimitError('action_meaning_stale_head')
        return h

    def _lam_candidate_record(self, cand):
        def bad(code):
            raise MemoryReplayError('corrupt_action_mutation:' + code)
        deltas = cand.get('deltas') if type(cand) is dict else None
        if type(deltas) is not list or not deltas or any(type(d) is not dict for d in deltas):
            bad('candidate_body')
        adds = [d for d in deltas if d.get('op') == 'ADD_RULE' and d.get('target_kind') == 'rule']
        if len(adds) != 1 or type(adds[0].get('payload')) is not dict:
            bad('candidate_body')
        body = adds[0]['payload'].get('body')
        kind = body.get('kind') if type(body) is dict else None
        if type(kind) is not str:
            bad('candidate_kind')
        if kind in ('expression', 'observation'):
            return None
        if kind != LEX_KIND:
            bad('unknown_kind')
        try:
            record = self._canonical_action_record(body)
            ident = self._action_record_identity(record)
        except (ValueError, TypeError, KeyError, AttributeError, IndexError):
            bad('record')
        if cand.get('candidate_id') != ident['candidate_id']:
            bad('candidate_id')
        eq = self._lam_eq
        try:
            request = [add_rule(ident['rule_id'], record, revision=0, graph=None)]
        except (ValueError, TypeError, KeyError, AttributeError, IndexError):
            bad('request')
        if not eq(deltas, request):
            bad('candidate_request')
        evidence = {'operation': 'teach_action_meaning', 'candidate_id': ident['candidate_id'],
                    'rule_id': ident['rule_id'], 'kind': LEX_KIND,
                    'record_sha256': record['record_sha256'], 'report': record['report']}
        if not eq(cand.get('evidence'), evidence):
            bad('candidate_evidence')
        if cand.get('request_digest') != hashlib.sha256(dumps(request).encode('utf-8')).hexdigest():
            bad('request_digest')
        if cand.get('actor') != ACTOR or cand.get('source') != SOURCE:
            bad('candidate_provenance')
        return record, ident

    def _lam_prehead(self, store, preseq):
        def bad(code):
            raise MemoryReplayError('corrupt_action_mutation:prehead_' + code)
        eq = self._lam_eq
        if store is not self._store:
            bad('store')
        prior = store.change(preseq)['change_id'] if preseq else None
        rows = store.added_rules(at=preseq)
        if type(rows) is not list or len(rows) > self.candidate_limit:
            bad('added_rules_limit')
        att = self._action_attachment
        out = []
        for r in rows:
            b = r.get('body') if type(r) is dict else None
            k = b.get('kind') if type(b) is dict else None
            if type(k) is not str or k not in ('expression', 'observation', LEX_KIND):
                bad('unknown_active_kind')
            if k != LEX_KIND:
                continue
            rid = r.get('id')
            try:
                record = self._canonical_action_record(b)
                ident = self._action_record_identity(record)
            except (ValueError, TypeError, KeyError, AttributeError, IndexError):
                bad('record')
            if ident['rule_id'] != rid or not eq(b, record):
                bad('rule_identity')
            try:
                ins = self._action_accepted_add(ident['candidate_id'])
            except MemoryLimitError as e:
                raise MemoryReplayError('corrupt_action_mutation:prehead_origin:%s'
                                        % (str(e).split(':')[-1],)) from None
            if ins['rule_id'] != rid or not eq(ins['record'], record):
                bad('origin_mismatch')
            ch = ins['accepted_change']
            if ch['seq'] > preseq:
                bad('origin_after_prehead')
            item = store.item('rule', rid, at=preseq)
            if (type(item) is not dict or item.get('state') != 'added' or item.get('revision') != 1
                    or item.get('graph_id') is not None or not eq(item.get('body'), record)):
                bad('item')
            expected_origin = {'change_id': ch['change_id'], 'seq': ch['seq'], 'actor': ch['actor'],
                               'source': ch['source'], 'approval': ch['approval'],
                               'created_at': ch['created_at']}
            if not eq(item.get('origin'), expected_origin):
                bad('item_origin')
            hist = [h for h in store.history(rid) if h['seq'] <= preseq]
            if len(hist) != 1 or not eq(hist[0], ins['accepted_history']):
                bad('history')
            usable = False
            if att is not None and eq(att['action_binding'], record['binding']):
                prov = record['provenance']
                try:
                    fresh = self._resolve_action_source(record['payload'], {
                        'ledger_source_id': prov['ledger_source_id'],
                        'question_output_id': prov['question']['output_id'],
                        'confirmation_input_id': prov['confirmation']['input_event_id']})
                except MemoryLimitError:
                    fresh = None
                usable = fresh is not None and eq(fresh, record)
            out.append({'candidate_id': ident['candidate_id'], 'rule_id': rid, 'record': record,
                        'usable': usable})
        return prior, out

    def _lam_scope(self, rows, record):
        eq = self._lam_eq
        p = record['payload']
        hits = []
        for r in rows:
            if not r['usable']:
                continue
            q = r['record']['payload']
            if (eq(r['record']['binding'], record['binding'])
                    and q['surface']['text'] == p['surface']['text']
                    and q['surface']['declaration_sha256'] == p['surface']['declaration_sha256']
                    and eq(q['role_pattern'], p['role_pattern'])):
                hits.append(r)
        if len(hits) > 1 or any(not eq(h['record']['payload'], p) for h in hits):
            raise MemoryLimitError('action_meaning_conflict')
        return hits[0] if hits else None

    def _lam_admit_check(self, store, cid, rid, record, request, evidence, preseq, prior):
        def bad(code):
            raise MemoryReplayError('corrupt_action_mutation:admit_' + code)
        eq = self._lam_eq
        approver = 'learning-memory-action-meaning'
        if store is not self._store:
            bad('store')
        head = store.head()
        if type(head[0]) is not int or head[0] < preseq + 1:
            bad('head')
        if (store.change(preseq)['change_id'] if preseq else None) != prior:
            bad('prior')
        digest = hashlib.sha256(dumps(request).encode('utf-8')).hexdigest()
        if head[0] > preseq + 1:
            late = store.change(head[0])
            lap = late['approval']
            lexp = {'seq': head[0], 'ord': 0, 'op': 'ADD_RULE', 'target_kind': 'rule', 'target_id': rid,
                    'graph_id': None, 'payload': {'body': record}, 'revision': 0}
            lcand = store.candidate(cid)
            congruent = (late['seq'] == head[0] and late['change_id'] == head[1]
                         and late['parent_seq'] == head[0] - 1 and late['request_digest'] == digest
                         and eq(late['evidence'], evidence) and eq(late['validation'], record['report'])
                         and late['actor'] == ACTOR and late['source'] == SOURCE
                         and late['reason'] == 'explicit user action meaning confirmation'
                         and type(lap) is dict and set(lap) == {'by', 'at', 'candidate_id'}
                         and lap['by'] == approver and _nonempty(lap['at']) and lap['candidate_id'] == cid
                         and eq(late['deltas'], [lexp])
                         and type(lcand) is dict and lcand['candidate_id'] == cid
                         and lcand['status'] == 'pending' and lcand['change_seq'] is None
                         and type(lcand['proposed_at_seq']) is int
                         and preseq <= lcand['proposed_at_seq'] < head[0]
                         and lcand['actor'] == ACTOR and lcand['source'] == SOURCE
                         and lcand['request_digest'] == digest and eq(lcand['deltas'], request)
                         and eq(lcand['evidence'], evidence))
            if congruent:
                raise MemoryLimitError('action_meaning_stale_head')
            bad('head')
        chg = store.change(head[0])
        if (chg['seq'] != preseq + 1 or chg['change_id'] != head[1] or chg['parent_seq'] != preseq
                or chg['request_digest'] != digest or not eq(chg['evidence'], evidence)
                or not eq(chg['validation'], record['report']) or chg['actor'] != ACTOR
                or chg['source'] != SOURCE or chg['reason'] != 'explicit user action meaning confirmation'):
            bad('change')
        ap = chg['approval']
        if (type(ap) is not dict or set(ap) != {'by', 'at', 'candidate_id'} or ap['by'] != approver
                or not _nonempty(ap['at']) or ap['candidate_id'] != cid):
            bad('approval')
        exp = {'seq': head[0], 'ord': 0, 'op': 'ADD_RULE', 'target_kind': 'rule', 'target_id': rid,
               'graph_id': None, 'payload': {'body': record}, 'revision': 0}
        if not eq(chg['deltas'], [exp]):
            bad('deltas')
        item = store.item('rule', rid)
        if (type(item) is not dict or item.get('state') != 'added' or item.get('revision') != 1
                or item.get('graph_id') is not None or not eq(item.get('body'), record)):
            bad('item')
        org = item.get('origin')
        if type(org) is not dict or org.get('change_id') != head[1] or org.get('seq') != head[0]:
            bad('item_origin')
        cand = store.candidate(cid)
        keys = {'candidate_id', 'created_at', 'actor', 'source', 'reason', 'evidence', 'deltas',
                'request_digest', 'proposed_at_seq', 'status', 'decided_at', 'decided_by',
                'decision_reason', 'change_seq'}
        if (type(cand) is not dict or set(cand) != keys or cand['status'] != 'pending'
                or cand['change_seq'] is not None or cand['proposed_at_seq'] != preseq
                or cand['actor'] != ACTOR or cand['source'] != SOURCE
                or cand['request_digest'] != digest or not eq(cand['deltas'], request)
                or not eq(cand['evidence'], evidence)):
            bad('candidate')
        prov = record['provenance']
        fresh = self._resolve_action_source(record['payload'], {
            'ledger_source_id': prov['ledger_source_id'],
            'question_output_id': prov['question']['output_id'],
            'confirmation_input_id': prov['confirmation']['input_event_id']})
        if not eq(fresh, record):
            bad('source_mismatch')
        prior2, rows = self._lam_prehead(store, preseq)
        if prior2 != prior:
            bad('prior_rows')
        if self._lam_scope(rows, record) is not None:
            raise MemoryLimitError('action_meaning_conflict')
        self._replay(store)

    def _lam_is_lexical(self, candidate_id):
        if type(candidate_id) is not str:
            return False
        cand = self._store.candidate(candidate_id)
        if cand is None:
            return False
        return self._lam_candidate_record(cand) is not None

    def _lam_withdraw_target(self, rows, proof, cid):
        hits = [r for r in rows if r['usable']
                and r['record']['payload']['surface']['text'] == proof['expression']]
        if len(hits) != 1 or hits[0]['candidate_id'] != cid:
            raise MemoryLimitError('action_meaning_unavailable:withdraw_target_unavailable')
        return hits[0]

    def _lam_withdraw(self, candidate_id, reason, expected_head, source):
        from marco.storage.overlay import OverlayError, OverlayConflict
        eq = self._lam_eq
        approver = 'learning-memory-action-meaning-withdrawal'
        src = self._lx_obj(source, ('ledger_source_id', 'control_input_id'), 'withdraw_source')
        for k in src:
            self._lx_str(src[k], 'withdraw_' + k, 128)
        refs = {'ledger_source_id': src['ledger_source_id'], 'control_input_id': src['control_input_id']}
        change_id = 'lam-withdraw:' + hashlib.sha256(dumps(refs).encode('utf-8')).hexdigest()
        record, ident = self._lam_candidate_record(self._store.candidate(candidate_id))
        cid, rid = ident['candidate_id'], ident['rule_id']
        request = [disable_rule(rid, revision=1)]
        digest = hashlib.sha256(dumps(request).encode('utf-8')).hexdigest()
        try:
            old = self._store.change(change_id)
        except OverlayError as e:
            if str(e) != 'no change %r in this overlay' % (change_id,):
                raise
            old = None
        if old is not None:
            def bad(code):
                raise MemoryReplayError('corrupt_action_mutation:withdraw_history_' + code)
            ev = old['evidence']
            ok = (type(ev) is dict
                  and set(ev) == {'operation', 'candidate_id', 'rule_id', 'kind', 'source', 'proof'}
                  and ev['operation'] == 'retract_action_meaning' and ev['candidate_id'] == cid
                  and ev['rule_id'] == rid and ev['kind'] == LEX_KIND and eq(ev['source'], refs)
                  and eq(old['validation'], ev['proof']) and old['request_digest'] == digest
                  and old['actor'] == ACTOR and old['source'] == SOURCE
                  and type(old['approval']) is dict and old['approval'].get('by') == approver
                  and len(old['deltas']) == 1 and old['deltas'][0]['target_id'] == rid
                  and old['deltas'][0]['op'] == 'DISABLE_RULE')
            if not ok:
                raise OverlayConflict('withdrawal %s is recorded with different content' % change_id)
            proof = ev['proof']
            try:
                self._lx_obj(proof, ('schema', 'ledger_source_id', 'event_id', 'conversation_id',
                                     'context_conversation_id', 'turn', 'expression', 'capture_span',
                                     'text_sha256', 'legacy_sha256', 'form_id', 'form_sha256',
                                     'declaration_sha256', 'binding_sha256'), 'withdraw_proof')
                if proof['schema'] != 'lexical-action-withdraw-source-v1':
                    self._lx_fail('withdraw_proof_schema')
                for k in ('ledger_source_id', 'event_id', 'conversation_id', 'context_conversation_id'):
                    self._lx_str(proof[k], 'withdraw_proof_' + k, 128)
                self._lx_int(proof['turn'], 'withdraw_proof_turn', 1, 65536)
                self._lx_str(proof['expression'], 'withdraw_proof_expression', 512)
                span = self._lx_list(proof['capture_span'], 'withdraw_proof_capture_span', 2, 2)
                self._lx_int(span[0], 'withdraw_proof_capture_span', 0, 32768)
                self._lx_int(span[1], 'withdraw_proof_capture_span', 0, 32768)
                if not span[0] < span[1] or span[1] - span[0] != len(proof['expression']):
                    self._lx_fail('withdraw_proof_capture_span_bounds')
                for k in ('text_sha256', 'legacy_sha256', 'form_sha256', 'declaration_sha256',
                          'binding_sha256'):
                    self._lx_hex(proof[k], 'withdraw_proof_' + k)
                fid = proof['form_id']
                if type(fid) is not str or not fid:
                    self._lx_fail('withdraw_proof_form_id')
                try:
                    fid.encode('utf-8')
                except UnicodeEncodeError:
                    self._lx_fail('withdraw_proof_form_id_utf8')
            except MemoryLimitError as e:
                raise MemoryReplayError('corrupt_action_mutation:withdraw_history_proof:%s'
                                        % (str(e).split(':')[-1],)) from None
            if (proof['ledger_source_id'] != refs['ledger_source_id']
                    or proof['event_id'] != refs['control_input_id']):
                raise OverlayConflict('withdrawal %s is recorded with different content' % change_id)
            if (proof['ledger_source_id'] != record['provenance']['ledger_source_id']
                    or proof['expression'] != record['payload']['surface']['text']
                    or proof['binding_sha256'] != self._lx_sha(record['binding'])
                    or proof['declaration_sha256'] != record['binding']['forms_sha256']):
                bad('proof_binding')
            try:
                ins = self._action_accepted_add(cid)
            except MemoryLimitError as e:
                raise MemoryReplayError('corrupt_action_mutation:withdraw_history_origin:%s'
                                        % (str(e).split(':')[-1],)) from None
            if ins['rule_id'] != rid or not eq(ins['record'], record):
                bad('origin_mismatch')
            keys = {'seq', 'change_id', 'created_at', 'actor', 'source', 'reason', 'evidence',
                    'parent_seq', 'approval', 'validation', 'request_digest', 'deltas'}
            seq = old['seq']
            if (set(old) != keys or type(seq) is not int or seq < 1 or old['change_id'] != change_id
                    or old['parent_seq'] != seq - 1 or not _nonempty(old['reason'])
                    or not _nonempty(old['created_at'])):
                bad('change')
            if type(ins['accepted_change']['seq']) is not int or seq <= ins['accepted_change']['seq']:
                bad('change_order')
            ap = old['approval']
            if set(ap) != {'by', 'at'} or ap['by'] != approver or not _nonempty(ap['at']):
                bad('approval')
            exp = {'seq': seq, 'ord': 0, 'op': 'DISABLE_RULE', 'target_kind': 'rule', 'target_id': rid,
                   'graph_id': None, 'payload': {}, 'revision': 1}
            if not eq(old['deltas'], [exp]):
                bad('deltas')
            row = dict(exp)
            for k in ('change_id', 'created_at', 'actor', 'source', 'reason', 'evidence', 'approval',
                      'validation'):
                row[k] = old[k]
            hist = self._store.history(rid)
            if (type(hist) is not list or len(hist) != 2 or not eq(hist[0], ins['accepted_history'])
                    or not eq(hist[1], row)):
                bad('history')
            item = self._store.item('rule', rid)
            origin = {'change_id': old['change_id'], 'seq': seq, 'actor': old['actor'],
                      'source': old['source'], 'approval': old['approval'],
                      'created_at': old['created_at']}
            if (type(item) is not dict or item.get('state') != 'disabled' or item.get('revision') != 2
                    or item.get('graph_id') is not None or not eq(item.get('body'), record)
                    or not eq(item.get('origin'), origin)):
                bad('item')
            return self._view(self._store.candidate(candidate_id))
        proof = self._resolve_action_withdraw_source(refs)
        head = self._lam_head(expected_head)
        prior, rows = self._lam_prehead(self._store, head[0])
        if tuple(self._store.head()) != tuple(head):
            raise MemoryLimitError('action_meaning_stale_head')
        self._lam_withdraw_target(rows, proof, cid)
        evidence = {'operation': 'retract_action_meaning', 'candidate_id': cid, 'rule_id': rid,
                    'kind': LEX_KIND, 'source': refs, 'proof': proof}
        self._store.commit(request, actor=ACTOR, source=SOURCE, reason=reason, approved_by=approver,
                           evidence=evidence, validation=proof, change_id=change_id,
                           check=lambda store: self._lam_withdraw_check(store, cid, rid, record, request,
                                                                         evidence, proof, refs, reason,
                                                                         change_id, head[0], head[1]))
        return self._view(self._store.candidate(candidate_id))

    def _lam_withdraw_check(self, store, cid, rid, record, request, evidence, proof, refs, reason,
                            change_id, preseq, prior):
        def bad(code):
            raise MemoryReplayError('corrupt_action_mutation:withdraw_' + code)
        eq = self._lam_eq
        if store is not self._store:
            bad('store')
        head = store.head()
        if type(head[0]) is not int or head[0] < preseq + 1 or head[1] != change_id:
            bad('head')
        if (store.change(preseq)['change_id'] if preseq else None) != prior:
            bad('prior')
        chg = store.change(change_id)
        digest = hashlib.sha256(dumps(request).encode('utf-8')).hexdigest()
        if head[0] > preseq + 1:
            lap = chg['approval']
            lexp = {'seq': head[0], 'ord': 0, 'op': 'DISABLE_RULE', 'target_kind': 'rule', 'target_id': rid,
                    'graph_id': None, 'payload': {}, 'revision': 1}
            litem = store.item('rule', rid)
            congruent = (chg['seq'] == head[0] and chg['change_id'] == change_id
                         and chg['parent_seq'] == head[0] - 1 and chg['request_digest'] == digest
                         and eq(chg['evidence'], evidence) and eq(chg['validation'], proof)
                         and chg['actor'] == ACTOR and chg['source'] == SOURCE and chg['reason'] == reason
                         and type(lap) is dict and set(lap) == {'by', 'at'}
                         and lap['by'] == 'learning-memory-action-meaning-withdrawal'
                         and _nonempty(lap['at']) and eq(chg['deltas'], [lexp])
                         and type(litem) is dict and litem.get('state') == 'disabled'
                         and litem.get('revision') == 2 and eq(litem.get('body'), record)
                         and type(litem.get('origin')) is dict
                         and litem['origin'].get('change_id') == change_id
                         and litem['origin'].get('seq') == head[0])
            if congruent:
                raise MemoryLimitError('action_meaning_stale_head')
            bad('head')
        if (chg['seq'] != preseq + 1 or chg['parent_seq'] != preseq or chg['request_digest'] != digest
                or not eq(chg['evidence'], evidence) or not eq(chg['validation'], proof)
                or chg['actor'] != ACTOR or chg['source'] != SOURCE or chg['reason'] != reason):
            bad('change')
        ap = chg['approval']
        if (type(ap) is not dict or set(ap) != {'by', 'at'}
                or ap['by'] != 'learning-memory-action-meaning-withdrawal' or not _nonempty(ap['at'])):
            bad('approval')
        exp = {'seq': head[0], 'ord': 0, 'op': 'DISABLE_RULE', 'target_kind': 'rule', 'target_id': rid,
               'graph_id': None, 'payload': {}, 'revision': 1}
        if not eq(chg['deltas'], [exp]):
            bad('deltas')
        item = store.item('rule', rid)
        if (type(item) is not dict or item.get('state') != 'disabled' or item.get('revision') != 2
                or not eq(item.get('body'), record) or item.get('origin', {}).get('change_id') != change_id):
            bad('item')
        hist = store.history(rid)
        if len(hist) != 2 or hist[1]['change_id'] != change_id:
            bad('history')
        if not eq(self._resolve_action_withdraw_source(refs), proof):
            bad('proof_mismatch')
        prior2, rows = self._lam_prehead(store, preseq)
        if prior2 != prior:
            bad('prior_rows')
        self._lam_withdraw_target(rows, proof, cid)
        self._replay(store)

    def active_action_meanings(self):
        head0 = self._store.head()

        def inv(rows, gaps, head):
            return {'schema': 'lexical-action-meaning-inventory-v1',
                    'head': {'seq': head[0], 'change_id': head[1]},
                    'rows': rows, 'gaps': gaps}

        self._action_scan_added()
        cands = self._store.candidates()
        if len(cands) > self.candidate_limit:
            raise MemoryReplayError('corrupt_action_current:candidate_limit')
        found, gaps = [], []
        for c in cands:
            cid = c.get('candidate_id') if type(c) is dict else None
            try:
                res = self._action_current(cid)
            except MemoryLimitError as e:
                code = str(e).split(':')[-1]
                if code == 'nonlexical_candidate':
                    continue
                if code == 'memory_head_changed':
                    return inv([], [{'code': 'action_meaning_unavailable:memory_head_changed',
                                     'candidate_id': None}], head0)
                gaps.append({'code': 'action_meaning_unavailable:' + code,
                             'candidate_id': cid if type(cid) is str else None})
                continue
            if res['active']:
                found.append((res['accepted_seq'], res['rule_id'],
                              {'payload': copy.deepcopy(res['record']['payload']),
                               'binding': copy.deepcopy(res['record']['binding']),
                               'origin': self._action_origin_of(res)}))
            elif res['status'] == 'unavailable':
                gaps.append({'code': 'action_meaning_' + res['reason_code'],
                             'candidate_id': res['candidate_id']})
        if tuple(self._store.head()) != tuple(head0):
            return inv([], [{'code': 'action_meaning_unavailable:memory_head_changed',
                             'candidate_id': None}], head0)
        if self._action_attachment is None:
            return inv([], [{'code': 'action_meaning_feature_unavailable', 'candidate_id': None}], head0)
        found.sort(key=lambda r: (r[0], r[1]))
        return inv([r[2] for r in found], gaps, head0)

    def action_meaning_origin(self, candidate_id):
        res = self._action_current(candidate_id)
        if not res['active']:
            raise MemoryLimitError('action_meaning_unavailable:' + res['reason_code'])
        return self._action_origin_of(res)

    @staticmethod
    def _lx_fail(why):
        raise MemoryLimitError('lexical_record_invalid:%s' % why)

    @staticmethod
    def _lx_sha(value):
        return hashlib.sha256(dumps(value).encode('utf-8')).hexdigest()

    @classmethod
    def _lx_plain(cls, value, name, limit):
        def walk(v, depth):
            if depth > 64:
                cls._lx_fail(name + '_depth')
            t = type(v)
            if v is None or t is bool or t is str or t is int:
                return
            if t is float:
                if v != v or v in (float('inf'), float('-inf')):
                    cls._lx_fail(name + '_not_finite')
                return
            if t is list:
                for item in v:
                    walk(item, depth + 1)
                return
            if t is dict:
                for k, item in v.items():
                    if type(k) is not str:
                        cls._lx_fail(name + '_key')
                    walk(item, depth + 1)
                return
            cls._lx_fail(name + '_not_json')
        walk(value, 0)
        try:
            text = dumps(value)
        except (TypeError, ValueError, RecursionError):
            text = None
        if text is None:
            cls._lx_fail(name + '_not_json')
        if len(text.encode('utf-8')) > limit:
            cls._lx_fail(name + '_too_large')
        return json.loads(text)

    @classmethod
    def _lx_obj(cls, value, keys, name, optional=()):
        if type(value) is not dict:
            cls._lx_fail(name)
        got = set(value)
        if not set(keys) <= got or not got <= set(keys) | set(optional):
            cls._lx_fail(name + '_keys')
        return value

    @classmethod
    def _lx_str(cls, value, name, high, low=1):
        if type(value) is not str or not low <= len(value) <= high:
            cls._lx_fail(name)
        try:
            value.encode('utf-8')
        except UnicodeEncodeError:
            cls._lx_fail(name + '_utf8')
        return value

    @classmethod
    def _lx_hex(cls, value, name):
        if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
            cls._lx_fail(name)
        return value

    @classmethod
    def _lx_int(cls, value, name, low, high):
        if type(value) is not int or not low <= value <= high:
            cls._lx_fail(name)
        return value

    @classmethod
    def _lx_list(cls, value, name, low, high):
        if type(value) is not list or not low <= len(value) <= high:
            cls._lx_fail(name)
        return value

    @classmethod
    def _lx_span(cls, value, name):
        cls._lx_list(value, name, 2, 2)
        if cls._lx_int(value[0], name, 0, 65536) > cls._lx_int(value[1], name, 0, 65536):
            cls._lx_fail(name + '_order')
        return value

    @classmethod
    def _lx_criterion(cls, value, name):
        c = cls._lx_obj(value, ('id', 'scope', 'policy_id', 'policy_sha256'), name)
        if c['id'] != LEX_CRITERION_ID or c['scope'] != LEX_SCOPE:
            cls._lx_fail(name + '_identity')
        cls._lx_str(c['policy_id'], name + '_policy_id', 128)
        cls._lx_hex(c['policy_sha256'], name + '_policy_sha256')
        return c

    def _attach_action_learning(self, action_projection, action_learning_projection,
                                action_binding, dialogue_ledger):
        from marco.trace.ledger import Ledger
        self._action_attachment = None
        given = (action_projection, action_learning_projection, action_binding, dialogue_ledger)
        if all(v is None for v in given):
            return
        if any(v is None for v in given):
            raise MemoryLimitError('action_learning_attachment_partial')
        if not isinstance(dialogue_ledger, Ledger) or getattr(dialogue_ledger, 'fsync', None) is not True:
            raise MemoryLimitError('action_learning_ledger_invalid')
        # L6: validate first, then keep an order-preserving defensive copy; the sorted
        # canonical roundtrip would reorder native signature/role maps and break L5
        # descriptor equality (actions.py describe_action_catalog regeneration).
        self._lx_plain(action_projection, 'action_projection', LEX_ATTACH_BYTES)
        proj = copy.deepcopy(action_projection)
        lproj = self._lx_plain(action_learning_projection, 'action_learning_projection', LEX_ATTACH_BYTES)
        binding = self._canonical_action_binding(
            self._lx_plain(action_binding, 'action_binding', LEX_ATTACH_BYTES))
        if self._graph_binding is None or self._graph_binding != self._lx_sha(binding):
            raise MemoryLimitError('action_binding_graph_binding_mismatch')

        def linked(prov, name):
            if type(prov) is not dict or type(prov.get('source')) is not dict:
                raise MemoryLimitError(name + '_provenance_shape')
            for k in ('graph_id', 'root_id', 'effective_graph_sha256', 'view_key', 'base_origin'):
                if prov.get(k) != binding[k]:
                    raise MemoryLimitError(name + '_provenance_' + k + '_mismatch')
            src = prov['source']
            for k in ('status', 'member_path', 'member_sha256', 'base_content_sha256', 'base_build_id'):
                if src.get(k) != binding['source'].get(k):
                    raise MemoryLimitError(name + '_provenance_source_mismatch')

        proj = self._lx_obj(proj, ('schema', 'catalog', 'surface', 'policy', 'replies', 'required_operators',
                                   'hypothesis_scope', 'entry_labels', 'source_maps', 'provenance',
                                   'fingerprint', 'catalog_description'), 'action_projection')
        if proj['schema'] != 'graph-action-grounding-projection-v1':
            raise MemoryLimitError('action_projection_schema')
        catalog = proj['catalog']
        if type(catalog) is not dict or any(k not in catalog for k in ('catalog_id', 'limits', 'programs')):
            raise MemoryLimitError('action_projection_catalog_shape')
        cat_core = {'catalog_id': catalog['catalog_id'], 'limits': catalog['limits'],
                    'programs': catalog['programs']}
        pre = {'schema': proj['schema'], 'required_operators': proj['required_operators'],
               'hypothesis_scope': proj['hypothesis_scope'], 'catalog': cat_core,
               'surface': proj['surface'], 'policy': proj['policy'], 'replies': proj['replies'],
               'entry_labels': proj['entry_labels'], 'source_maps': proj['source_maps'],
               'provenance': proj['provenance']}
        afp = self._lx_sha(pre)
        if proj['fingerprint'] != afp or binding['action_projection_fingerprint'] != afp:
            raise MemoryLimitError('action_projection_fingerprint_mismatch')
        if catalog['catalog_id'] != binding['catalog_id'] or self._lx_sha(cat_core) != binding['catalog_sha256']:
            raise MemoryLimitError('action_projection_catalog_mismatch')
        linked(proj['provenance'], 'action_projection')
        lproj = self._lx_obj(lproj, ('schema', 'policy', 'forms', 'render', 'role_labels', 'source_maps',
                                     'provenance', 'parent_action_fingerprint',
                                     'language_projection_fingerprint', 'fingerprint'),
                             'action_learning_projection')
        if lproj['schema'] != 'graph-action-learning-projection-v1':
            raise MemoryLimitError('action_learning_projection_schema')
        lpre = {k: v for k, v in lproj.items() if k != 'fingerprint'}
        lfp = self._lx_sha(lpre)
        if lproj['fingerprint'] != lfp or binding['action_learning_projection_fingerprint'] != lfp:
            raise MemoryLimitError('action_learning_projection_fingerprint_mismatch')
        if lproj['parent_action_fingerprint'] != afp:
            raise MemoryLimitError('action_learning_parent_action_mismatch')
        if lproj['language_projection_fingerprint'] != binding['language_projection_fingerprint']:
            raise MemoryLimitError('action_learning_language_projection_mismatch')
        policy = lproj['policy']
        if type(policy) is not dict or policy.get('policy_id') != binding['policy_id']:
            raise MemoryLimitError('action_learning_policy_id_mismatch')
        for section, key in (('policy', 'policy_sha256'), ('forms', 'forms_sha256'),
                             ('render', 'render_sha256'), ('role_labels', 'role_labels_sha256')):
            if self._lx_sha(lproj[section]) != binding[key]:
                raise MemoryLimitError('action_learning_' + section + '_digest_mismatch')
        linked(lproj['provenance'], 'action_learning_projection')
        self._action_attachment = {'action_projection': proj, 'action_learning_projection': lproj,
                                   'action_binding': binding, 'dialogue_ledger': dialogue_ledger}

    def _canonical_action_target(self, payload):
        p = self._lx_obj(payload, ('schema', 'surface', 'role_pattern', 'role_pattern_sha256', 'terms'), 'target')
        if p['schema'] != LEX_TARGET_SCHEMA:
            self._lx_fail('target_schema')
        s = self._lx_obj(p['surface'], ('text', 'surface_id', 'declaration_sha256'), 'surface')
        self._lx_str(s['text'], 'surface_text', 512)
        self._lx_str(s['surface_id'], 'surface_id', 512)
        self._lx_hex(s['declaration_sha256'], 'surface_declaration_sha256')
        rp = self._lx_obj(p['role_pattern'], ('offset_unit', 'ordered_slots', 'slots', 'omitted_slots'), 'role_pattern')
        if rp['offset_unit'] != 'unicode_codepoint':
            self._lx_fail('offset_unit')
        ordered = self._lx_list(rp['ordered_slots'], 'ordered_slots', 1, 8)
        omitted = self._lx_list(rp['omitted_slots'], 'omitted_slots', 0, 8)
        for item in ordered + omitted:
            self._lx_str(item, 'slot_name', 128)
        names = []
        for slot in self._lx_list(rp['slots'], 'slots', 1, 8):
            d = self._lx_obj(slot, ('slot', 'case_group', 'type_ref', 'presence', 'coreference_group'), 'slot')
            names.append(self._lx_str(d['slot'], 'slot', 128))
            self._lx_str(d['case_group'], 'case_group', 512)
            self._lx_str(d['type_ref'], 'type_ref', 1024)
            if type(d['presence']) is not str or d['presence'] not in ('required', 'optional'):
                self._lx_fail('presence')
            if d['coreference_group'] is not None:
                self._lx_str(d['coreference_group'], 'coreference_group', 512)
        if (len(set(names)) != len(names) or len(set(ordered)) != len(ordered)
                or len(set(omitted)) != len(omitted) or set(ordered) & set(omitted)
                or set(ordered) | set(omitted) != set(names)):
            self._lx_fail('slot_partition')
        presence = {d['slot']: d['presence'] for d in rp['slots']}
        if omitted != [n for n in names if n in set(omitted)]:
            self._lx_fail('omitted_order')
        if any(presence[n] != 'optional' for n in omitted):
            self._lx_fail('omitted_required')
        if self._lx_hex(p['role_pattern_sha256'], 'role_pattern_sha256') != self._lx_sha(rp):
            self._lx_fail('role_pattern_sha256_mismatch')
        consumed = set()
        for term in self._lx_list(p['terms'], 'terms', 1, 2):
            t = self._lx_obj(term, ('id', 'version', 'execute_key', 'source_ref', 'program_sha256', 'slot_map'), 'term')
            tid = self._lx_str(t['id'], 'term_id', 128)
            if type(t['version']) is not int:
                self._lx_str(t['version'], 'term_version', 128)
            if self._lx_str(t['execute_key'], 'execute_key', 257) != tid + '@' + str(t['version']):
                self._lx_fail('execute_key_identity')
            ref = self._lx_str(t['source_ref'], 'source_ref', 128)
            prefix = '/source_maps/catalog/entries/'
            tail = ref[len(prefix):]
            if not ref.startswith(prefix) or not tail or not tail.isascii() or not tail.isdigit():
                self._lx_fail('source_ref')
            self._lx_hex(t['program_sha256'], 'program_sha256')
            sm = t['slot_map']
            if type(sm) is not dict or not 1 <= len(sm) <= 8:
                self._lx_fail('slot_map')
            for k, v in sm.items():
                self._lx_str(k, 'slot_map_key', 128)
                self._lx_str(v, 'slot_map_value', 128)
                if v not in set(ordered):
                    self._lx_fail('slot_map_value_not_present_role')
                if k != v:
                    self._lx_fail('slot_map_identity')
                consumed.add(v)
        if consumed != set(ordered):
            self._lx_fail('slot_map_exhaustive')
        return self._lx_plain(p, 'target', self.payload_bytes_limit)

    def _canonical_action_binding(self, binding):
        hexes = ('model_content_sha256', 'model_effective_key', 'effective_graph_sha256',
                 'language_projection_fingerprint', 'action_projection_fingerprint',
                 'action_learning_projection_fingerprint', 'catalog_sha256', 'policy_sha256',
                 'forms_sha256', 'render_sha256', 'role_labels_sha256', 'parser_base_sha256',
                 'parser_grammar_sha256')
        keys = ('schema',) + hexes + ('graph_id', 'root_id', 'view_key', 'base_origin', 'source',
                                      'catalog_id', 'policy_id')
        b = self._lx_obj(binding, keys, 'binding')
        if b['schema'] != LEX_BINDING_SCHEMA:
            self._lx_fail('binding_schema')
        for k in hexes:
            self._lx_hex(b[k], k)
        self._lx_str(b['graph_id'], 'graph_id', 1024)
        self._lx_str(b['root_id'], 'root_id', 1024)
        vk = self._lx_list(b['view_key'], 'view_key', 2, 2)
        seq = self._lx_int(vk[0], 'view_key_seq', 0, 2147483647)
        if (seq == 0) != (vk[1] is None):
            self._lx_fail('view_key_identity')
        if vk[1] is not None:
            self._lx_str(vk[1], 'view_key_change', 128)
        bo = self._lx_obj(b['base_origin'], ('kind', 'build_id'), 'base_origin')
        if bo['kind'] != 'base':
            self._lx_fail('base_origin_kind')
        if bo['build_id'] is not None:
            self._lx_str(bo['build_id'], 'build_id', 1024)
        src = self._lx_obj(b['source'], ('status', 'member_path', 'member_sha256', 'base_content_sha256'),
                           'source', optional=('base_build_id',))
        if src['status'] != 'caller_supplied':
            self._lx_fail('source_status')
        self._lx_str(src['member_path'], 'member_path', 1024)
        self._lx_hex(src['member_sha256'], 'member_sha256')
        self._lx_hex(src['base_content_sha256'], 'base_content_sha256')
        if src.get('base_build_id') is not None:
            self._lx_str(src['base_build_id'], 'source_base_build_id', 1024)
        self._lx_str(b['catalog_id'], 'catalog_id', 128)
        self._lx_str(b['policy_id'], 'policy_id', 128)
        return self._lx_plain(b, 'binding', self.payload_bytes_limit)

    def _action_record_identity(self, record):
        if type(record) is not dict:
            self._lx_fail('record')
        if any(k not in record for k in LEX_PREIMAGE_KEYS):
            self._lx_fail('record_preimage_keys')
        pre = self._lx_plain({k: record[k] for k in LEX_PREIMAGE_KEYS}, 'record_preimage',
                             self.payload_bytes_limit)
        sha = self._lx_sha(pre)
        if 'record_sha256' in record and record['record_sha256'] != sha:
            self._lx_fail('record_sha256')
        return {'record_sha256': sha, 'candidate_id': 'cand_lam_' + sha,
                'rule_id': 'memory:lexical_action_meaning:' + sha}

    def _canonical_action_record(self, record):
        r = self._lx_plain(self._lx_obj(record, LEX_RECORD_KEYS, 'record'), 'record', self.payload_bytes_limit)
        if (r['schema'] != SCHEMA or r['kind'] != LEX_KIND or r['record_version'] != LEX_VERSION
                or r['supervision'] != LEX_SUPERVISION or r['replaces'] is not None):
            self._lx_fail('record_identity')
        self._lx_hex(r['record_sha256'], 'record_sha256')
        target = self._canonical_action_target(r['payload'])
        binding = self._canonical_action_binding(r['binding'])
        prov = self._lx_obj(r['provenance'], ('kind', 'ledger_source_id', 'conversation_id',
                                              'context_conversation_id', 'turn_id', 'input_turn',
                                              'question', 'confirmation', 'criterion'), 'provenance')
        if prov['kind'] != 'dialogue_input':
            self._lx_fail('provenance_kind')
        for k in ('ledger_source_id', 'conversation_id', 'context_conversation_id', 'turn_id'):
            self._lx_str(prov[k], k, 128)
        self._lx_int(prov['input_turn'], 'input_turn', 1, 65536)
        q = self._lx_obj(prov['question'], ('output_id', 'question_input_id', 'initiating_input_id',
                                            'pending_creation_output_id', 'pending_id', 'text_sha256',
                                            'legacy_sha256', 'template_id', 'template_sha256',
                                            'target_sha256', 'question_span'), 'question')
        for k in ('output_id', 'question_input_id', 'initiating_input_id', 'pending_creation_output_id',
                  'pending_id', 'template_id'):
            self._lx_str(q[k], k, 128)
        for k in ('text_sha256', 'legacy_sha256', 'template_sha256', 'target_sha256'):
            self._lx_hex(q[k], k)
        self._lx_span(q['question_span'], 'question_span')
        c = self._lx_obj(prov['confirmation'], ('input_event_id', 'text', 'sha256', 'legacy_sha256', 'span',
                                                'form_id', 'form_sha256', 'declaration_sha256'), 'confirmation')
        self._lx_str(c['input_event_id'], 'input_event_id', 128)
        self._lx_str(c['text'], 'confirmation_text', 32768)
        self._lx_str(c['form_id'], 'form_id', 128)
        for k in ('sha256', 'legacy_sha256', 'form_sha256', 'declaration_sha256'):
            self._lx_hex(c[k], k)
        self._lx_span(c['span'], 'confirmation_span')
        if hashlib.sha256(c['text'].encode('utf-8')).hexdigest() != c['sha256']:
            self._lx_fail('confirmation_text_sha256')
        if hashlib.sha256(c['text'].strip().encode('utf-8')).hexdigest() != c['legacy_sha256']:
            self._lx_fail('confirmation_legacy_sha256')
        if not 0 <= c['span'][0] < c['span'][1] <= len(c['text']):
            self._lx_fail('confirmation_span_bounds')
        if prov['turn_id'] != c['input_event_id']:
            self._lx_fail('turn_id_input_event_mismatch')
        if c['declaration_sha256'] != binding['forms_sha256']:
            self._lx_fail('confirmation_declaration_forms_mismatch')
        crit = self._lx_criterion(prov['criterion'], 'criterion')
        if crit['policy_id'] != binding['policy_id'] or crit['policy_sha256'] != binding['policy_sha256']:
            self._lx_fail('criterion_policy_binding_mismatch')
        rep = self._lx_obj(r['report'], ('schema', 'kind', 'accepted', 'reason', 'criterion',
                                         'source_digest', 'target_sha256', 'binding_sha256'), 'report')
        if (rep['schema'] != LEX_REPORT_SCHEMA or rep['kind'] != LEX_KIND or rep['accepted'] is not True
                or rep['reason'] != LEX_REPORT_REASON):
            self._lx_fail('report_identity')
        if self._lx_criterion(rep['criterion'], 'report_criterion') != crit:
            self._lx_fail('report_criterion_mismatch')
        if self._lx_hex(rep['source_digest'], 'source_digest') != self._lx_sha(prov):
            self._lx_fail('source_digest_mismatch')
        target_sha = self._lx_sha(target)
        if (self._lx_hex(rep['target_sha256'], 'report_target_sha256') != target_sha
                or q['target_sha256'] != target_sha):
            self._lx_fail('target_sha256')
        if self._lx_hex(rep['binding_sha256'], 'binding_sha256') != self._lx_sha(binding):
            self._lx_fail('binding_sha256')
        self._action_record_identity(r)
        return self._lx_plain(r, 'record', self.payload_bytes_limit)

    def _action_archive(self):
        from marco.trace.ledger import read as ledger_read, LedgerError
        from marco.reasoning.readings import grammar_fingerprint
        from marco.language.teaching import validate_action_meaning_forms
        fail = self._lx_fail
        att = self._action_attachment
        if att is None:
            fail('source_attachment_unavailable')
        led, binding = att['dialogue_ledger'], att['action_binding']
        ap, lp = att['action_projection'], att['action_learning_projection']
        if getattr(led, 'fsync', None) is not True:
            fail('source_ledger_not_fsync')
        if getattr(led, '_broken', False) is True:
            raise OSError('ledger writer invalidated by an earlier write/fsync failure; close and reopen it')
        fixed = {'schema': 'lexical-action-learning-policy-v1',
                 'admission_operator': 'explicit_user_lexical_action_confirmation_v1',
                 'meaning_scope': 'surface_role_pattern_to_exhaustive_ordered_known_programs_v1',
                 'evidence_kind': 'archived_dialogue_input_v1',
                 'question_scope': 'next_external_input_same_conversation_v1',
                 'question_selection': 'oldest_pending_rank_then_target_digest_v1',
                 'retraction_scope': 'unique_active_surface_role_pattern_v1',
                 'active_use_scope': 'conditional_nonexecuting_adjunct_v1'}
        ceil = {'max_forms': 16, 'max_form_chars': 512, 'max_input_bytes': 32768,
                'max_question_bytes': 65536, 'max_target_bytes': 32768, 'max_active_questions': 1,
                'max_terms': 2, 'max_roles': 64, 'max_archive_bytes': 16777216,
                'max_archive_events': 65536}
        pol = lp['policy']
        if type(pol) is not dict or set(pol) != set(fixed) | {'policy_id', 'limits'}:
            fail('source_policy_shape')
        for k, v in fixed.items():
            if pol[k] != v:
                fail('source_policy_value')
        if pol['policy_id'] != binding['policy_id']:
            fail('source_policy_id')
        lim = pol['limits']
        if type(lim) is not dict or set(lim) != set(ceil):
            fail('source_policy_limits')
        for k, high in ceil.items():
            if type(lim[k]) is not int or not 1 <= lim[k] <= high:
                fail('source_policy_limit_' + k)
        parser = self._fresh()
        gf = grammar_fingerprint(parser)
        if binding['parser_base_sha256'] != gf or binding['parser_grammar_sha256'] != gf:
            fail('source_parser_identity')
        try:
            validate_action_meaning_forms(parser, lp['forms'])
        except ValueError:
            fail('source_forms_invalid')
        rows = lp['forms']['forms']
        if type(rows) is not list or len(rows) > lim['max_forms']:
            fail('source_forms_count')
        for row in rows:
            if type(row) is not dict or type(row.get('slots')) is not dict:
                fail('source_form_shape')
            for t in [row.get('text'), row.get('ownership_prefix')] + list(row['slots'].values()):
                if type(t) is not str or not 1 <= len(t) <= lim['max_form_chars']:
                    fail('source_form_chars')
        path = led.path
        try:
            events, problems = ledger_read(path, max_bytes=min(lim['max_archive_bytes'], 16777216))
        except LedgerError:
            fail('source_archive_invalid')
        if problems or len(events) > min(lim['max_archive_events'], 65536):
            fail('source_archive_problems_or_cap')
        sid = 'hypomnema-file:' + hashlib.sha256(os.path.realpath(os.fspath(path)).encode('utf-8')).hexdigest()
        if type(getattr(led, 'runtime', None)) is not dict or led.runtime.get('source_id') != sid:
            fail('source_id_mismatch')
        by_id, pos = {}, {}
        withdrawn, superseded = set(), set()
        for i, e in enumerate(events):
            by_id[e['event_id']] = e
            pos[e['event_id']] = i
            if e['kind'] == 'conclusion_withdrawn':
                withdrawn.add(e['payload']['withdrawn'])
            if e.get('supersedes') is not None:
                superseded.add(e['supersedes'])
        return {'events': events, 'by_id': by_id, 'pos': pos, 'withdrawn': withdrawn,
                'superseded': superseded, 'source_id': sid, 'binding': binding, 'ap': ap, 'lp': lp,
                'limits': lim, 'parser': parser}

    def _action_hash(self, text):
        try:
            return hashlib.sha256(text.encode('utf-8')).hexdigest()
        except UnicodeEncodeError:
            self._lx_fail('source_text_utf8')

    def _action_ancestors(self, arch, eid):
        seen, todo = set(), list(arch['by_id'][eid]['parent_ids'])
        while todo:
            x = todo.pop()
            if x in seen:
                continue
            seen.add(x)
            todo.extend(arch['by_id'][x]['parent_ids'])
        return seen

    def _action_input(self, arch, e):
        fail = self._lx_fail
        if (e is None or e['kind'] != 'input_received' or e['status'] != 'success'
                or e['epistemic_status'] != 'reported' or e.get('subsystem') != 'dialogue'):
            fail('source_input_event')
        p, s, rt = e['payload'], e['source'], e['runtime']
        text, conv, turn, att = p.get('text'), p.get('conversation'), p.get('turn'), p.get('attempt_id')
        if type(text) is not str or not text or len(text) > 32768:
            fail('source_input_text')
        if len(text.encode('utf-8', 'replace')) > min(arch['limits']['max_input_bytes'], 32768):
            fail('source_input_bytes')
        if type(conv) is not str or not 1 <= len(conv) <= 128:
            fail('source_input_conversation')
        if type(turn) is not int or not 1 <= turn <= 65536:
            fail('source_input_turn')
        if type(att) is not str or not att or len(e['event_id']) > 128:
            fail('source_input_attempt')
        if (s.get('type') != 'dialogue_turn' or type(s.get('conversation')) is not str
                or s.get('conversation') != conv or type(s.get('turn')) is not int or s.get('turn') != turn):
            fail('source_input_source')
        legacy = self._action_hash(text.strip())
        if p.get('sha256') != legacy:
            fail('source_input_legacy_sha')
        if type(rt) is not dict or rt.get('source_id') != arch['source_id']:
            fail('source_input_runtime_source')
        dr = rt.get('declared_runtime')
        if type(dr) is not dict:
            fail('source_input_binding')
        try:
            cb = self._canonical_action_binding(dr.get('action_learning_binding'))
        except MemoryLimitError:
            fail('source_input_binding')
        if cb != arch['binding'] or self._lx_sha(cb) != self._lx_sha(arch['binding']):
            fail('source_input_binding')
        ctx = dr.get('context_conversation_id')
        if type(ctx) is not str or not 1 <= len(ctx) <= 128:
            fail('source_input_context')
        head = p.get('installed_memory_head')
        if head is not None and (type(head) is not dict or set(head) != {'attached'}
                                 or head['attached'] is not False):
            fail('source_input_parser_memory_installed')
        if e['event_id'] in arch['withdrawn'] or e['event_id'] in arch['superseded']:
            fail('source_input_withdrawn')
        return {'id': e['event_id'], 'text': text, 'conv': conv, 'turn': turn, 'attempt': att,
                'ctx': ctx, 'raw_sha': self._action_hash(text), 'legacy_sha': legacy}

    def _resolve_action_source(self, payload, source):
        from marco.language.frames import read_unknown_action
        from marco.language.teaching import read_action_meaning_control
        from marco.reasoning.actions import (validate_action_meaning_target, render_action_meaning,
                                             match_action_meaning)
        import string
        fail = self._lx_fail
        src = self._lx_obj(source, ('ledger_source_id', 'question_output_id', 'confirmation_input_id'), 'source')
        for k in src:
            self._lx_str(src[k], 'source_' + k, 128)
        arch = self._action_archive()
        binding, ap, lp, parser = arch['binding'], arch['ap'], arch['lp'], arch['parser']
        by_id, pos = arch['by_id'], arch['pos']
        if src['ledger_source_id'] != arch['source_id']:
            fail('source_ref_id_mismatch')
        try:
            target = validate_action_meaning_target(ap, lp, payload, binding=binding)
        except ValueError:
            fail('target_invalid')
        if target != self._canonical_action_target(payload):
            fail('target_not_canonical')
        tsha = self._lx_sha(target)
        bsha = self._lx_sha(binding)
        errored = {x['trace_id'] for x in arch['events'] if x['kind'] == 'error'}

        def output(eid, name):
            o = by_id.get(eid)
            if o is None:
                fail('source_event_missing')
            if (o['kind'] != 'output_created' or o['status'] not in ('answered', 'recorded', 'hold')
                    or o.get('subsystem') != 'dialogue'):
                fail(name + '_output')
            op = o['payload']
            if (type(op.get('conversation')) is not str or not op.get('conversation')
                    or type(op.get('turn')) is not int or op.get('turn') < 1
                    or type(op.get('attempt_id')) is not str or not op.get('attempt_id')):
                fail(name + '_identity')
            if type(o.get('runtime')) is not dict or o['runtime'].get('source_id') != arch['source_id']:
                fail(name + '_runtime_source')
            if o['trace_id'] in errored:
                fail(name + '_error_state')
            return o

        def turn_input(o, name):
            op = o['payload']
            hits = []
            for x in arch['events']:
                xp = x['payload']
                if (x['kind'] == 'input_received' and x['trace_id'] == o['trace_id']
                        and xp.get('attempt_id') == op['attempt_id']
                        and xp.get('conversation') == op['conversation']
                        and type(xp.get('turn')) is int and xp.get('turn') == op['turn']):
                    hits.append(x['event_id'])
            if len(hits) != 1:
                fail(name + '_input_not_unique')
            if hits[0] not in self._action_ancestors(arch, o['event_id']):
                fail(name + '_input_ancestry')
            info = self._action_input(arch, by_id[hits[0]])
            if (info['conv'] != op['conversation'] or info['turn'] != op['turn']
                    or info['attempt'] != op['attempt_id']):
                fail(name + '_input_identity')
            return info

        qid, cid = src['question_output_id'], src['confirmation_input_id']
        conf = by_id.get(cid)
        if conf is None:
            fail('source_event_missing')
        q = output(qid, 'source_question')
        qp = q['payload']
        text = qp.get('text')
        if type(text) is not str or not text or qp.get('sha256') != self._action_hash(text.strip()):
            fail('source_question_text')
        prov = qp.get('provenance')
        meta = prov.get('meaning_question') if type(prov) is dict else None
        mkeys = ('schema', 'pending_id', 'initiating_input_id', 'pending_creation_output_id',
                 'context_conversation_id', 'target', 'target_sha256', 'selection',
                 'learning_declaration_sha256', 'question_template_id', 'question_template_sha256',
                 'rendered_text_sha256', 'question_span')
        meta = self._lx_obj(meta, mkeys, 'meaning_question')
        if meta['schema'] != 'lexical-action-meaning-question-v1' or meta['question_template_id'] != 'question':
            fail('source_meta_schema')
        self._lx_str(meta['pending_id'], 'meta_pending_id', 128)
        self._lx_str(meta['initiating_input_id'], 'meta_initiating', 128)
        if meta['pending_creation_output_id'] is not None:
            self._lx_str(meta['pending_creation_output_id'], 'meta_creation', 128)
        self._lx_str(meta['context_conversation_id'], 'meta_context', 128)
        for k in ('target_sha256', 'learning_declaration_sha256', 'question_template_sha256', 'rendered_text_sha256'):
            self._lx_hex(meta[k], 'meta_' + k)
        span = self._lx_span(meta['question_span'], 'meta_span')
        try:
            msel = self._canonical_action_binding(meta['selection'])
        except MemoryLimitError:
            fail('source_meta_selection')
        if msel != binding or self._lx_sha(msel) != bsha:
            fail('source_meta_target_binding')
        try:
            mtarget = validate_action_meaning_target(ap, lp, meta['target'], binding=binding)
        except ValueError:
            fail('source_meta_target')
        try:
            mcanon = self._canonical_action_target(meta['target'])
        except MemoryLimitError:
            fail('source_meta_target')
        if mtarget != mcanon:
            fail('source_meta_target')
        msha = self._lx_sha(mtarget)
        if (msha != meta['target_sha256'] or msha != tsha or mtarget != target
                or meta['learning_declaration_sha256'] != binding['action_learning_projection_fingerprint']):
            fail('source_meta_target_binding')
        if (meta['question_template_sha256'] != self._action_hash(lp['render']['question'])
                or meta['rendered_text_sha256'] != self._action_hash(text)):
            fail('source_meta_hashes')
        # question-turn input
        qanc = self._action_ancestors(arch, qid)
        qin = turn_input(q, 'source_question')
        ctx, conv = qin['ctx'], qin['conv']
        if conv != qp['conversation'] or ctx != meta['context_conversation_id']:
            fail('source_question_context')
        # pending creation and initiating input
        crid = meta['pending_creation_output_id'] or qid
        cr = output(crid, 'source_creation')
        crin = turn_input(cr, 'source_creation')
        if crin['conv'] != conv or crin['ctx'] != ctx:
            fail('source_creation_context')
        init_ev = by_id.get(meta['initiating_input_id'])
        init = self._action_input(arch, init_ev)
        if crin['id'] != init['id']:
            fail('source_creation_input')
        if init['conv'] != conv or init['ctx'] != ctx:
            fail('source_initiating_context')
        if init['id'] not in self._action_ancestors(arch, crid):
            fail('source_creation_ancestry')
        if cr['event_id'] in arch['withdrawn'] or cr['event_id'] in arch['superseded']:
            fail('source_creation_withdrawn')
        for a in qanc | self._action_ancestors(arch, crid):
            if a in arch['withdrawn'] or a in arch['superseded']:
                fail('source_ancestor_withdrawn')
        if qid in arch['withdrawn'] or qid in arch['superseded']:
            fail('source_question_withdrawn')
        stagea = {'conversation_id': ctx}
        for k in ('model_content_sha256', 'model_effective_key', 'graph_id', 'root_id',
                  'effective_graph_sha256', 'view_key', 'language_projection_fingerprint',
                  'action_projection_fingerprint', 'parser_base_sha256', 'parser_grammar_sha256'):
            stagea[k] = binding[k]
        stagea['installed_memory_head'] = None
        stagea_sha = self._lx_sha(stagea)
        rows = []
        for x in arch['events']:
            if x['kind'] != 'output_created':
                continue
            xp = x['payload'].get('provenance')
            lst = xp.get('action_pending_created') if type(xp) is dict else None
            if lst is None:
                continue
            if type(lst) is not list:
                fail('source_pending_rows')
            for r in lst:
                if type(r) is not dict:
                    fail('source_pending_row')
                if (r.get('pending_id') == meta['pending_id'] and r.get('context_conversation_id') == ctx
                        and r.get('source_input_id') == init['id']):
                    rows.append((x['event_id'], r))
        if len(rows) != 1 or rows[0][0] != crid:
            fail('source_pending_not_unique')
        row = self._lx_obj(rows[0][1], ('schema', 'pending_id', 'source_input_id', 'context_conversation_id',
                                        'created_input_turn', 'raw_text_sha256', 'binding_sha256'), 'pending_row')
        if row['schema'] != 'contextual-action-pending-source-v1':
            fail('source_pending_schema')
        self._lx_int(row['created_input_turn'], 'created_input_turn', 1, 65536)
        if row['raw_text_sha256'] != init['raw_sha'] or row['binding_sha256'] != stagea_sha:
            fail('source_pending_digest')
        # confirmation
        cin = self._action_input(arch, conf)
        if cin['conv'] != conv or cin['ctx'] != ctx or cin['turn'] <= qin['turn']:
            fail('source_confirmation_scope')
        if not (pos[init['id']] <= pos[crid] <= pos[qid] and pos[qin['id']] < pos[qid] < pos[cid]):
            fail('source_order')
        first = None
        for x in arch['events'][pos[qid] + 1:]:
            if x['kind'] == 'input_received' and x['payload'].get('conversation') == conv:
                first = x['event_id']
                break
        if first != cid:
            fail('source_confirmation_not_next')
        for x in arch['events'][pos[qid] + 1:pos[cid]]:
            xp = x['payload'].get('provenance')
            if (x['kind'] == 'output_created' and x['payload'].get('conversation') == conv
                    and type(xp) is dict and 'meaning_question' in xp):
                fail('source_competing_question')
        # reading and match
        reading = read_unknown_action(init['text'], ap['surface'])
        if (reading.get('status') != 'read' or reading.get('search_complete') is not True
                or reading.get('truncated') is not False or reading.get('gaps')):
            fail('source_reading_incomplete')
        try:
            m = match_action_meaning(ap, lp, target, reading, binding=binding, text=init['text'])
        except ValueError:
            fail('source_match_invalid')
        if (m.get('status') != 'matched' or m.get('search_complete') is not True or m.get('truncated')
                or m.get('gaps') or not m.get('matches')):
            fail('source_match_incomplete')

        def render(ans):
            try:
                return render_action_meaning(ap, lp, target, binding=binding, kind='question', answer=ans)
            except ValueError:
                fail('source_render_invalid')

        base = render(None)
        qtext = base['text']
        if (base['question_template_id'] != 'question'
                or base['question_template_sha256'] != meta['question_template_sha256']):
            fail('source_template_metadata')
        if (span[1] > len(text) or span[1] - span[0] != len(qtext) or text[span[0]:span[1]] != qtext
                or text.count(qtext) != 1):
            fail('source_question_span')
        if span == [0, len(text)]:
            if text != qtext:
                fail('source_question_only')
        else:
            try:
                parts = list(string.Formatter().parse(lp['render']['question_with_answer']))
            except (ValueError, TypeError):
                fail('source_wrapper_template')
            names, lits, idx = [], ['', '', ''], 0
            for lit, n, _s, _c in parts:
                lits[min(idx, 2)] += lit
                if n is not None:
                    names.append(n)
                    idx += 1
            if idx != 2 or sorted(names) != ['answer', 'question']:
                fail('source_wrapper_fields')
            if names[0] == 'answer':
                a0, a1 = len(lits[0]), span[0] - len(lits[1])
            else:
                a0, a1 = span[1] + len(lits[1]), len(text) - len(lits[2])
            if a0 < 0 or a1 <= a0 or a1 > len(text):
                fail('source_wrapper_answer')
            again = render(text[a0:a1])
            if (again['text'] != text or again['question_span'] != span
                    or again['question_template_sha256'] != meta['question_template_sha256']
                    or again['question_template_id'] != 'question'):
                fail('source_wrapper_mismatch')
        # confirmation meaning
        ctl = read_action_meaning_control(parser, cin['text'], lp['forms'])
        if ctl is None or ctl.get('kind') == 'hold':
            fail('source_confirmation_unavailable')
        if ctl['kind'] == 'deny':
            raise MemoryLimitError('action_meaning_denied')
        ev = ctl.get('evidence') or {}
        if (ctl['kind'] != 'affirm' or ctl.get('fields') != {} or ev.get('coverage_status') != 'complete'
                or ev.get('source') != cin['text']):
            fail('source_confirmation_not_affirm')
        cspan = [ev.get('start'), ev.get('end')]
        crit = {'id': LEX_CRITERION_ID, 'scope': LEX_SCOPE, 'policy_id': binding['policy_id'],
                'policy_sha256': binding['policy_sha256']}
        prov_out = {'kind': 'dialogue_input', 'ledger_source_id': arch['source_id'], 'conversation_id': conv,
                    'context_conversation_id': ctx, 'turn_id': cin['id'], 'input_turn': cin['turn'],
                    'question': {'output_id': qid, 'question_input_id': qin['id'],
                                 'initiating_input_id': init['id'], 'pending_creation_output_id': crid,
                                 'pending_id': meta['pending_id'], 'text_sha256': self._action_hash(text),
                                 'legacy_sha256': qp['sha256'], 'template_id': 'question',
                                 'template_sha256': meta['question_template_sha256'],
                                 'target_sha256': tsha, 'question_span': list(span)},
                    'confirmation': {'input_event_id': cin['id'], 'text': cin['text'], 'sha256': cin['raw_sha'],
                                     'legacy_sha256': cin['legacy_sha'], 'span': cspan,
                                     'form_id': ev.get('form_id'), 'form_sha256': ev.get('form_sha256'),
                                     'declaration_sha256': ev.get('declaration_sha256')},
                    'criterion': crit}
        pre = {'schema': SCHEMA, 'kind': LEX_KIND, 'record_version': LEX_VERSION, 'payload': target,
               'binding': copy.deepcopy(binding), 'provenance': prov_out, 'supervision': LEX_SUPERVISION,
               'replaces': None}
        ident = self._action_record_identity(pre)
        report = {'schema': LEX_REPORT_SCHEMA, 'kind': LEX_KIND, 'accepted': True, 'reason': LEX_REPORT_REASON,
                  'criterion': dict(crit), 'source_digest': self._lx_sha(prov_out), 'target_sha256': tsha,
                  'binding_sha256': self._lx_sha(binding)}
        rec = dict(pre)
        rec['record_sha256'] = ident['record_sha256']
        rec['report'] = report
        return self._canonical_action_record(rec)

    def _resolve_action_withdraw_source(self, source):
        from marco.language.teaching import read_action_meaning_control
        fail = self._lx_fail
        src = self._lx_obj(source, ('ledger_source_id', 'control_input_id'), 'withdraw_source')
        self._lx_str(src['ledger_source_id'], 'withdraw_ledger_source_id', 128)
        self._lx_str(src['control_input_id'], 'withdraw_control_input_id', 128)
        arch = self._action_archive()
        if src['ledger_source_id'] != arch['source_id']:
            fail('source_ref_id_mismatch')
        e = arch['by_id'].get(src['control_input_id'])
        info = self._action_input(arch, e)
        ctl = read_action_meaning_control(arch['parser'], info['text'], arch['lp']['forms'])
        if ctl is None or ctl.get('kind') != 'withdraw':
            fail('source_withdraw_not_withdraw')
        ev = ctl.get('evidence') or {}
        fields = ctl.get('fields')
        caps = ev.get('capture_spans')
        if (ev.get('coverage_status') != 'complete' or type(fields) is not dict or set(fields) != {'expression'}
                or type(caps) is not dict or set(caps) != {'expression'}):
            fail('source_withdraw_capture')
        cap = caps['expression']
        if (type(cap) is not dict or type(cap.get('start')) is not int or type(cap.get('end')) is not int
                or info['text'][cap['start']:cap['end']] != fields['expression'] or not fields['expression']):
            fail('source_withdraw_span')
        return {'schema': 'lexical-action-withdraw-source-v1', 'ledger_source_id': arch['source_id'],
                'event_id': info['id'], 'conversation_id': info['conv'],
                'context_conversation_id': info['ctx'], 'turn': info['turn'],
                'expression': fields['expression'], 'capture_span': [cap['start'], cap['end']],
                'text_sha256': info['raw_sha'], 'legacy_sha256': info['legacy_sha'],
                'form_id': ev.get('form_id'), 'form_sha256': ev.get('form_sha256'),
                'declaration_sha256': ev.get('declaration_sha256'),
                'binding_sha256': self._lx_sha(arch['binding'])}

    def _action_accepted_add(self, candidate_id):
        from marco.storage.overlay import OverlayError
        approver = 'learning-memory-action-meaning'

        def unavailable(code):
            raise MemoryLimitError('action_meaning_unavailable:' + code)

        def bad(code):
            raise MemoryReplayError('corrupt_action_accepted_add:' + code)

        def eq(a, b):
            try:
                return dumps(a) == dumps(b)
            except (TypeError, ValueError, RecursionError):
                return False

        def is_int(v, low):
            return type(v) is int and v >= low

        def text(v):
            return type(v) is str and len(v) > 0

        if type(candidate_id) is not str or not 1 <= len(candidate_id) <= 128:
            unavailable('invalid_candidate_id')
        cand = self._store.candidate(candidate_id)
        if cand is None:
            unavailable('candidate_missing')
        if type(cand) is not dict:
            bad('candidate_shape')
        status = cand.get('status')
        if status == 'pending':
            unavailable('candidate_pending')
        if status == 'rejected':
            unavailable('candidate_rejected')
        if status != 'approved':
            bad('candidate_status')
        deltas = cand.get('deltas')
        if type(deltas) is not list or len(deltas) != 1 or type(deltas[0]) is not dict:
            bad('candidate_deltas')
        delta = deltas[0]
        if set(delta) != {'op', 'target_kind', 'target_id', 'graph_id', 'payload', 'revision'}:
            bad('candidate_delta_keys')
        if delta['op'] != 'ADD_RULE' or delta['target_kind'] != 'rule':
            bad('candidate_delta_op')
        if not text(delta['target_id']):
            bad('candidate_delta_target')
        if delta['graph_id'] is not None and not text(delta['graph_id']):
            bad('candidate_delta_graph')
        if not is_int(delta['revision'], 0):
            bad('candidate_delta_revision')
        payload = delta['payload']
        if type(payload) is not dict or set(payload) != {'body'}:
            bad('candidate_delta_payload')
        body = payload['body']
        if type(body) is not dict:
            bad('candidate_body')
        if 'kind' not in body:
            bad('candidate_body_kind')
        kind = body['kind']
        if type(kind) is not str or kind not in ('expression', 'observation', LEX_KIND):
            bad('unknown_kind')
        if kind in ('expression', 'observation'):
            unavailable('nonlexical_candidate')
        if kind != LEX_KIND:
            bad('unknown_kind')
        if set(cand) != {'candidate_id', 'created_at', 'actor', 'source', 'reason', 'evidence',
                         'request_digest', 'proposed_at_seq', 'status', 'decided_at', 'decided_by',
                         'decision_reason', 'change_seq', 'deltas'}:
            bad('candidate_keys')
        try:
            record = self._canonical_action_record(body)
            ident = self._action_record_identity(record)
        except (ValueError, TypeError, KeyError, AttributeError, IndexError):
            bad('record')
        cid, rid = ident['candidate_id'], ident['rule_id']
        if cand['candidate_id'] != candidate_id or candidate_id != cid:
            bad('candidate_id')
        if cand['actor'] != ACTOR or cand['source'] != SOURCE or cand['decided_by'] != approver:
            bad('candidate_provenance')
        seq = cand['change_seq']
        if not is_int(seq, 1) or not is_int(cand['proposed_at_seq'], 0):
            bad('candidate_seq')
        if not text(cand['decided_at']):
            bad('candidate_decided_at')
        try:
            request = [add_rule(rid, record, revision=0, graph=None)]
        except (ValueError, TypeError, KeyError, AttributeError, IndexError):
            bad('request')
        if not eq(deltas, request):
            bad('candidate_request')
        evidence = {'operation': 'teach_action_meaning', 'candidate_id': cid, 'rule_id': rid,
                    'kind': LEX_KIND, 'record_sha256': ident['record_sha256'],
                    'report': record['report']}
        if not eq(cand['evidence'], evidence):
            bad('candidate_evidence')
        digest = hashlib.sha256(dumps(request).encode('utf-8')).hexdigest()
        if cand['request_digest'] != digest:
            bad('request_digest')
        try:
            change = self._store.change(seq)
        except OverlayError as e:
            if str(e) == "no change %r in this overlay" % (seq,):
                bad('change_missing')
            raise
        if type(change) is not dict or set(change) != {'seq', 'change_id', 'created_at', 'actor',
                                                       'source', 'reason', 'evidence', 'parent_seq',
                                                       'approval', 'validation', 'request_digest',
                                                       'deltas'}:
            bad('change_keys')
        if not is_int(change['seq'], 1) or change['seq'] != seq or not text(change['change_id']):
            bad('change_identity')
        if not is_int(change['parent_seq'], 0) or change['parent_seq'] != cand['proposed_at_seq']:
            bad('change_parent')
        for k in ('actor', 'source', 'reason', 'evidence', 'request_digest'):
            if not eq(change[k], cand[k]):
                bad('change_' + k)
        if not eq(change['validation'], record['report']):
            bad('change_validation')
        if not eq(change['approval'], {'by': approver, 'at': cand['decided_at'], 'candidate_id': cid}):
            bad('change_approval')
        expected_delta = {'seq': seq, 'ord': 0, 'op': 'ADD_RULE', 'target_kind': 'rule',
                          'target_id': rid, 'graph_id': None, 'payload': {'body': record},
                          'revision': 0}
        if type(change['deltas']) is not list or not eq(change['deltas'], [expected_delta]):
            bad('change_deltas')
        projection = {k: expected_delta[k] for k in ('op', 'target_kind', 'target_id', 'graph_id',
                                                     'payload', 'revision')}
        if not eq([projection], request):
            bad('change_request')
        rows = self._store.history(rid)
        if type(rows) is not list or not 1 <= len(rows) <= self.candidate_limit + 1:
            bad('history')
        expected_row = dict(expected_delta)
        for k in ('change_id', 'created_at', 'actor', 'source', 'reason', 'evidence', 'approval',
                  'validation'):
            expected_row[k] = change[k]
        if not eq(rows[0], expected_row):
            bad('history_first')
        return {'schema': 'lexical-action-meaning-accepted-add-inspection-v1',
                'candidate': copy.deepcopy(cand),
                'record': copy.deepcopy(record),
                'rule_id': rid,
                'accepted_change': copy.deepcopy(change),
                'accepted_history': copy.deepcopy(rows[0])}

    def _lexical_kind_check(self, body, rid):
        if not isinstance(body, dict) or body.get('kind') != LEX_KIND:
            return False
        try:
            self._canonical_action_record(body)
        except (ValueError, TypeError, KeyError) as e:
            raise MemoryReplayError('corrupt_lexical_record:%s:%s' % (rid, e)) from None
        return True

    def _action_scan_added(self):
        def bad(code):
            raise MemoryReplayError('corrupt_action_current:' + code)

        def eq(a, b):
            try:
                return dumps(a) == dumps(b)
            except (TypeError, ValueError, RecursionError):
                return False

        ids = set()
        rows = self._store.added_rules()
        if type(rows) is not list or len(rows) > self.candidate_limit:
            bad('added_rules_limit')
        for r in rows:
            b = r.get('body') if type(r) is dict else None
            k = b.get('kind') if type(b) is dict else None
            if type(k) is not str or k not in ('expression', 'observation', LEX_KIND):
                bad('unknown_active_kind')
            if k == LEX_KIND:
                rid = r.get('id')
                if type(rid) is not str or not rid:
                    bad('active_lexical_rule_id')
                try:
                    record = self._canonical_action_record(b)
                    ident = self._action_record_identity(record)
                except (ValueError, TypeError, KeyError, AttributeError, IndexError):
                    bad('active_lexical_record')
                if ident['rule_id'] != rid:
                    bad('active_lexical_rule_identity')
                if not eq(b, record):
                    bad('active_lexical_body')
                try:
                    ins = self._action_accepted_add(ident['candidate_id'])
                except MemoryLimitError as e:
                    raise MemoryReplayError('corrupt_action_current:active_lexical_origin:%s'
                                            % (str(e).split(':')[-1],)) from None
                if ins['rule_id'] != rid or not eq(ins['record'], record):
                    bad('active_lexical_origin_mismatch')
            ids.add(r.get('id'))
        return ids

    def _action_origin_of(self, res):
        prov = res['record']['provenance']
        return {'kind': LEX_KIND,
                'ledger_source_id': prov['ledger_source_id'],
                'candidate_id': res['candidate_id'],
                'rule_id': res['rule_id'],
                'rule_revision': res['rule_revision'],
                'accepted_change_id': res['accepted_change_id'],
                'teaching': {'conversation_id': prov['conversation_id'],
                             'turn_id': prov['confirmation']['input_event_id']}}

    def _action_current(self, candidate_id):
        def unavailable(code):
            raise MemoryLimitError('action_meaning_unavailable:' + code)

        def bad(code):
            raise MemoryReplayError('corrupt_action_current:' + code)

        def eq(a, b):
            try:
                return dumps(a) == dumps(b)
            except (TypeError, ValueError, RecursionError):
                return False

        if type(candidate_id) is not str or not 1 <= len(candidate_id) <= 128:
            unavailable('invalid_candidate_id')
        head0 = self._store.head()
        added = self._action_scan_added()
        cand = self._store.candidate(candidate_id)
        if cand is None:
            unavailable('candidate_missing')
        if type(cand) is not dict:
            bad('candidate_shape')
        deltas = cand.get('deltas')
        if type(deltas) is not list or not deltas or any(type(d) is not dict for d in deltas):
            bad('candidate_body')
        adds = [d for d in deltas if d.get('op') == 'ADD_RULE' and d.get('target_kind') == 'rule']
        if len(adds) != 1 or type(adds[0].get('payload')) is not dict:
            bad('candidate_body')
        if any(d is not adds[0] and (d.get('op') != 'DISABLE_RULE' or d.get('target_kind') != 'rule')
               for d in deltas):
            bad('candidate_body')
        body = adds[0]['payload'].get('body')
        if type(body) is not dict or type(body.get('kind')) is not str:
            bad('candidate_body')
        if body['kind'] in ('expression', 'observation'):
            unavailable('nonlexical_candidate')
        if body['kind'] != LEX_KIND:
            bad('unknown_kind')
        if len(deltas) != 1:
            bad('candidate_body')
        status = cand.get('status')
        if type(status) is not str or status not in ('pending', 'rejected', 'approved'):
            bad('candidate_status')
        disabled = {r.get('id') for r in self._store.disabled_rules()}

        def done(res):
            if tuple(self._store.head()) != tuple(head0):
                unavailable('memory_head_changed')
            return res

        if status != 'approved':
            try:
                record = self._canonical_action_record(body)
                ident = self._action_record_identity(record)
            except (ValueError, TypeError, KeyError, AttributeError, IndexError):
                bad('record')
            cid, rid = ident['candidate_id'], ident['rule_id']
            if cand.get('candidate_id') != candidate_id or candidate_id != cid:
                bad('candidate_id')
            request = [add_rule(rid, record, revision=0, graph=None)]
            if not eq(deltas, request):
                bad('candidate_request')
            evidence = {'operation': 'teach_action_meaning', 'candidate_id': cid, 'rule_id': rid,
                        'kind': LEX_KIND, 'record_sha256': ident['record_sha256'],
                        'report': record['report']}
            if not eq(cand.get('evidence'), evidence):
                bad('candidate_evidence')
            if cand.get('request_digest') != hashlib.sha256(dumps(request).encode('utf-8')).hexdigest():
                bad('request_digest')
            if cand.get('change_seq') is not None:
                bad('candidate_change_seq')
            if (rid in added or rid in disabled or self._store.item('rule', rid) is not None
                    or self._store.history(rid) != []):
                bad('provisional_state_installed')
            return done({'candidate_id': candidate_id, 'record': record, 'rule_id': rid,
                         'accepted_seq': None, 'status': status, 'accepted': False, 'active': False,
                         'gate': 'inactive', 'reason_code': 'candidate_' + status,
                         'rule_revision': None, 'accepted_change_id': None,
                         'history': [], 'head': head0, 'decision_reason': cand.get('decision_reason')})

        ins = self._action_accepted_add(candidate_id)
        record, rid = ins['record'], ins['rule_id']
        change, first = ins['accepted_change'], ins['accepted_history']
        rows = self._store.history(rid)
        if type(rows) is not list or not 1 <= len(rows) <= 2 or not eq(rows[0], first):
            bad('history')
        item = self._store.item('rule', rid)
        if type(item) is not dict or set(item) != {'id', 'graph_id', 'state', 'body', 'revision', 'origin'}:
            bad('item')
        if item['id'] != rid or item['graph_id'] is not None or not eq(item['body'], record):
            bad('item_fields')
        if type(item['revision']) is not int:
            bad('item_revision')
        org = item['origin']
        if type(org) is not dict or set(org) != {'change_id', 'seq', 'actor', 'source', 'approval', 'created_at'}:
            bad('item_origin')

        def origin_is(c):
            return (org['change_id'] == c['change_id'] and eq(org['seq'], c['seq'])
                    and org['actor'] == c['actor'] and org['source'] == c['source']
                    and eq(org['approval'], c['approval']) and org['created_at'] == c['created_at'])

        accepted_change_id = change['change_id']
        if len(rows) == 1:
            if (item['state'] != 'added' or item['revision'] != 1 or rid not in added
                    or rid in disabled or not origin_is(change)):
                bad('item_state')
            gap = None
            att = self._action_attachment
            if att is None:
                gap = 'feature_unavailable'
            elif not eq(att['action_binding'], record['binding']):
                gap = 'binding_mismatch'
            else:
                prov = record['provenance']
                try:
                    fresh = self._resolve_action_source(record['payload'], {
                        'ledger_source_id': prov['ledger_source_id'],
                        'question_output_id': prov['question']['output_id'],
                        'confirmation_input_id': prov['confirmation']['input_event_id']})
                except MemoryLimitError:
                    gap = 'source_unavailable'
                else:
                    if not eq(fresh, record):
                        gap = 'source_mismatch'
            res = {'candidate_id': candidate_id, 'record': record, 'rule_id': rid,
                   'accepted_seq': change['seq'], 'accepted': True, 'rule_revision': 1,
                   'accepted_change_id': accepted_change_id, 'history': copy.deepcopy(rows),
                   'head': head0, 'decision_reason': cand.get('decision_reason')}
            if gap is None:
                res.update(status='active', active=True, gate='available', reason_code=None)
            else:
                res.update(status='unavailable', active=False, gate='unavailable', reason_code=gap)
            return done(res)

        row = rows[1]
        s2 = row.get('seq')
        if type(s2) is not int or s2 <= change['seq']:
            bad('disable_seq')
        exp = {'seq': s2, 'ord': 0, 'op': 'DISABLE_RULE', 'target_kind': 'rule', 'target_id': rid,
               'graph_id': None, 'payload': {}, 'revision': 1}
        if set(row) != set(first) or any(not eq(row[k], v) for k, v in exp.items()):
            bad('disable_row')
        c2 = self._store.change(s2)
        if type(c2) is not dict or set(c2) != set(change):
            bad('disable_change_keys')
        if (not eq(c2['seq'], s2) or type(c2['parent_seq']) is not int or c2['parent_seq'] != s2 - 1
                or c2['change_id'] != row['change_id']):
            bad('disable_change_identity')
        for k in ('created_at', 'actor', 'source', 'reason', 'evidence', 'approval', 'validation'):
            if not eq(c2[k], row[k]):
                bad('disable_change_' + k)
        if type(c2['deltas']) is not list or not eq(c2['deltas'], [exp]):
            bad('disable_change_deltas')
        digest = hashlib.sha256(dumps([disable_rule(rid, revision=1)]).encode('utf-8')).hexdigest()
        if c2['request_digest'] != digest:
            bad('disable_request_digest')
        if (item['state'] != 'disabled' or item['revision'] != 2 or rid in added
                or rid not in disabled or not origin_is(c2)):
            bad('disable_item_state')
        return done({'candidate_id': candidate_id, 'record': record, 'rule_id': rid,
                     'accepted_seq': change['seq'], 'status': 'retracted', 'accepted': True,
                     'active': False, 'gate': 'inactive', 'reason_code': 'retracted',
                     'rule_revision': 2, 'accepted_change_id': accepted_change_id,
                     'history': copy.deepcopy(rows), 'head': head0,
                     'decision_reason': cand.get('decision_reason')})

    def _unavailable_action_view(self, cand, record):
        res = self._action_current(cand['candidate_id'])
        view = copy.deepcopy(res['record'])
        gaps = []
        if res['status'] == 'unavailable':
            gaps.append({'code': 'action_meaning_' + res['reason_code'],
                         'candidate_id': res['candidate_id']})
        view.update(candidate_id=res['candidate_id'], rule_id=res['rule_id'],
                    rule_revision=res['rule_revision'],
                    accepted_change_id=res['accepted_change_id'],
                    status=res['status'], accepted=res['accepted'], active=res['active'],
                    current_gate_status=res['gate'], gaps=gaps,
                    decision_reason=res['decision_reason'],
                    revision=res['head'][0], history=res['history'])
        return view

    def _bounded(self, value, name):
        try:
            text = dumps(value)
        except (TypeError, ValueError, RecursionError) as e:
            raise MemoryLimitError("%s is not JSON: %s" % (name, e)) from None
        if len(text.encode("utf-8")) > self.payload_bytes_limit:
            raise MemoryLimitError("%s exceeds payload_bytes_limit" % name)
        return json.loads(text)

    def _room(self):
        if len(self._store.candidates()) >= self.candidate_limit:
            raise MemoryLimitError("candidate_limit_reached")

    def _fresh(self):
        from relational_semantics import RelationalParser
        if "selected_action_surface" in self._pack:
            return RelationalParser(
                data=copy.deepcopy(self._data), language_pack=copy.deepcopy(self._pack),
                selected_action_surface=copy.deepcopy(self._pack["selected_action_surface"]))
        return RelationalParser(data=copy.deepcopy(self._data), language_pack=copy.deepcopy(self._pack))

    def _expected(self, base, validation, *, expression_kind="fact"):
        if type(expression_kind) is not str or expression_kind not in ("fact", "query"):
            raise ValueError("invalid_expression_kind")
        if not isinstance(validation, list):
            raise ValueError("validation_must_be_list")
        out = []
        for case in validation:
            if not isinstance(case, dict) or set(case) - CASE_KEYS or not _nonempty(case.get("text")):
                raise ValueError("invalid_expression_validation")
            if "equivalent" in case:
                if "unrecognized" in case:
                    raise ValueError("ambiguous_validation_label")
                if expression_kind == "query":
                    expected = self._reference(base, case["equivalent"], expression_kind=expression_kind)
                else:
                    expected = self._reference(base, case["equivalent"])
            elif case.get("unrecognized") is True:
                expected = None
            else:
                raise ValueError("validation_requires_equivalent_or_unrecognized")
            out.append({"id": case.get("id"), "text": case["text"], "expected": expected})
        return out

    @staticmethod
    def _reference(base, text, *, expression_kind="fact"):
        if type(expression_kind) is not str or expression_kind not in ("fact", "query"):
            raise ValueError("invalid_expression_kind")
        if not _nonempty(text):
            raise ValueError("reference_not_fully_understood")
        # partial=True permits a statement without a question in this parser;
        # an unread or ambiguous clause still makes the entire parse fail.
        if expression_kind == "query":
            # Query references inspect the native raw carrier once so advanced
            # engine fields (native vocabulary, not language knowledge) are
            # rejected before reduction to the generic facts/query carrier.
            parsed = base.parse(text, partial=True)
            if not isinstance(parsed, dict):
                raise ValueError("reference_requires_one_known_query")
            for key in ("definitions", "events", "condition", "assumption", "reason",
                        "correction", "repair",
                        "정의", "사건", "가정사건", "조건", "가정", "원인", "이유물음", "수선", "사건정정"):
                if key in parsed and parsed[key] not in (None, [], {}, ""):
                    raise ValueError("reference_requires_one_known_query")
            expected = {
                "facts": [{k: v for k, v in item.items() if k != "evidence"}
                          if isinstance(item, dict) else item
                          for item in (parsed.get("facts") or [])],
                "query": parsed.get("query") or [],
            }
            if expected["facts"] != [] or not isinstance(expected["query"], list) \
                    or len(expected["query"]) != 1:
                raise ValueError("reference_requires_one_known_query")
            record = expected["query"][0]
            if not isinstance(record, dict) or set(record) != {"triple", "render"}:
                raise ValueError("reference_requires_one_known_query")
            triple, render = record["triple"], record["render"]
            if (not isinstance(triple, list) or len(triple) != 3
                    or any(not isinstance(x, str) or not x for x in triple)
                    or not isinstance(render, list) or not render
                    or any(not isinstance(x, str) for x in render)
                    or triple[1].startswith(("$", "?"))):
                raise ValueError("reference_requires_one_known_query")
            asked = [i for i in (0, 2) if triple[i].startswith("?")]
            if (len(asked) != 1 or len(triple[asked[0]]) < 2
                    or triple[2 - asked[0]].startswith(("$", "?"))):
                raise ValueError("reference_requires_one_known_query")
            return expected
        expected = expressions.semantics(base, text)
        if not expected or len(expected["facts"]) != 1 or expected["query"]:
            raise ValueError("reference_requires_one_known_fact")
        return expected

    def _evaluate(self, parser, payload, *, entry_origin=None, inherit_declared_slots=True,
                  expression_kind="fact"):
        """Gate one payload; mutates ``parser`` only if accepted. Malformed input yields a rejected report."""
        if type(expression_kind) is not str or expression_kind not in ("fact", "query"):
            raise ValueError("invalid_expression_kind")
        if inherit_declared_slots is not True and inherit_declared_slots is not False:
            raise TypeError("inherit_declared_slots must be a bool")
        if expression_kind == "query" and not inherit_declared_slots:
            raise ValueError("query_requires_selected_inheritance")
        base, annotation = self._fresh(), None
        try:
            if expression_kind == "query":
                self._reference(base, payload.get("equivalent"), expression_kind=expression_kind)
                annotation = expressions.from_paraphrase(base, payload.get("text"), payload.get("equivalent"),
                                                         inherit_declared_slots=inherit_declared_slots,
                                                         expression_kind=expression_kind)
                report = expressions.propose(
                    parser, annotation,
                    self._expected(base, payload.get("validation"), expression_kind=expression_kind),
                    entry_origin=entry_origin, expression_kind=expression_kind)
            else:
                self._reference(base, payload.get("equivalent"))
                annotation = expressions.from_paraphrase(base, payload.get("text"), payload.get("equivalent"),
                                                         inherit_declared_slots=inherit_declared_slots)
                report = expressions.propose(parser, annotation, self._expected(base, payload.get("validation")),
                                             entry_origin=entry_origin)
        except (ValueError, KeyError, TypeError) as e:
            report = {"kind": "validated_supervised_expression", "accepted": False,
                      "reason": str(e) or type(e).__name__, "validation": []}
        report["inferred_annotation"] = annotation
        if expression_kind == "query":
            report["induction_policy"] = "selected-reference-query-slots-v1"
        elif inherit_declared_slots:
            report["induction_policy"] = "selected-reference-word-slots-v1"
        return json.loads(dumps(report))

    def _rules(self, store):
        rules = store.added_rules()
        for rule in rules:
            rule["seq"] = store.history(rule["id"])[0]["seq"]
        return sorted(rules, key=lambda r: (r["seq"], r["id"]))

    def _replay(self, store, exclude=None, *, origins=None, origin_diagnostic=None):
        public = origin_diagnostic is not None
        origin_map = {}
        diagnostic = copy.deepcopy(origin_diagnostic) if public else None

        def issue(code, rule_id=None, reason=None):
            entry = {"code": code}
            if rule_id is not None:
                entry["rule_id"] = rule_id
            if reason is not None:
                entry["error_type"] = "ValueError"
                entry["error_reason"] = str(reason)[:256]
            diagnostic["issues"].append(entry)
            diagnostic["status"] = "incomplete"

        if public:
            rules = self._rules(store)
            if origins is not None:
                from marco.language.entry_origins import validated_entry_origin
                active = {r["id"]: r for r in rules if r["id"] != exclude
                          and not self._lexical_kind_check(r.get("body"), r["id"])}
                groups = {}
                if not isinstance(origins, list):
                    issue("origin_catalog_not_list")
                else:
                    for row in origins:
                        rid = row.get("rule_id") if isinstance(row, dict) else None
                        if isinstance(rid, str) and rid in active:
                            groups.setdefault(rid, []).append(row)
                        else:
                            issue("origin_row_orphan", rid if isinstance(rid, str) else None)
                for rid, rule in active.items():
                    found = groups.get(rid, [])
                    if len(found) != 1:
                        issue("origin_row_missing" if not found else "origin_row_duplicate", rid)
                        continue
                    row = found[0]
                    try:
                        origin = validated_entry_origin(row)
                    except ValueError as e:
                        issue("origin_carrier_invalid", rid, e)
                        continue
                    rule_origin = rule.get("origin")
                    change_id = rule_origin.get("change_id") if isinstance(rule_origin, dict) else None
                    change = store.change(change_id) if isinstance(change_id, str) else None
                    evidence = change.get("evidence") if isinstance(change, dict) else None
                    candidate_id = evidence.get("candidate_id") if isinstance(evidence, dict) else None
                    body = rule.get("body")
                    prov = body.get("provenance") if isinstance(body, dict) else None
                    teaching = ({"conversation_id": prov.get("conversation_id"),
                                 "turn_id": prov.get("turn_id")} if isinstance(prov, dict) else None)
                    if (change_id is None or candidate_id is None or teaching is None
                            or row.get("rule_revision") != rule.get("revision")
                            or row.get("accepted_change_id") != change_id
                            or row.get("candidate_id") != candidate_id
                            or row.get("teaching") != teaching):
                        issue("origin_rule_identity_mismatch", rid)
                        continue
                    binding = row.get("graph_binding")
                    if binding is None:
                        issue("graph_binding_unavailable", rid)
                    elif binding != self._graph_binding:
                        issue("graph_binding_mismatched", rid)
                        continue
                    origin_map[rid] = copy.deepcopy(origin)
            parser = self._fresh()
        else:
            parser = self._fresh()
            rules = self._rules(store)
        records = []
        for rule in rules:
            if rule["id"] == exclude:
                continue
            record = rule["body"]
            if self._lexical_kind_check(record, rule["id"]):
                continue
            if not (isinstance(record, dict) and record.get("schema") == SCHEMA
                    and record.get("kind") == "expression" and isinstance(record.get("payload"), dict)
                    and record.get("supervision") == SUPERVISION
                    and isinstance(record.get("report"), dict)
                    and record["report"].get("accepted") is True):
                raise MemoryReplayError("corrupt_record:%s" % rule["id"])

            def _verified_policy(rid, rec, active):
                # Verify the active rule is backed by exactly one accepted ADD_RULE
                # history row and its change record before trusting the stored report's policy marker.
                def fail(why):
                    raise MemoryReplayError("replay_source:%s:%s" % (rid, why))
                try:
                    active_rev = active.get("revision")
                    if isinstance(active_rev, bool) or not isinstance(active_rev, int):
                        fail("active_revision")
                    origin = active.get("origin")
                    origin = origin if isinstance(origin, dict) else {}
                    o_seq, o_change = origin.get("seq"), origin.get("change_id")
                    rows = store.history(rid)
                    if not isinstance(rows, (list, tuple)):
                        fail("history")
                    matches = []
                    for row in rows:
                        if not isinstance(row, dict) or row.get("op") != "ADD_RULE":
                            continue
                        if row.get("target_kind") != "rule" or row.get("target_id") != rid:
                            continue
                        rev = row.get("revision")
                        if isinstance(rev, bool) or not isinstance(rev, int) or rev + 1 != active_rev:
                            continue
                        matches.append(row)
                    if len(matches) != 1:
                        fail("history_ambiguous" if matches else "history_missing")
                    row = matches[0]
                    if o_seq is not None and row.get("seq") != o_seq:
                        fail("origin_seq")
                    if o_change is not None and row.get("change_id") != o_change:
                        fail("origin_change")
                    row_payload = row.get("payload")
                    if not isinstance(row_payload, dict) or row_payload.get("body") != rec:
                        fail("history_body")
                    change = store.change(row.get("change_id"))
                    if not isinstance(change, dict):
                        fail("change")
                    if change.get("seq") != row.get("seq") or change.get("change_id") != row.get("change_id"):
                        fail("change_identity")
                    deltas = change.get("deltas")
                    if not isinstance(deltas, (list, tuple)):
                        fail("change_deltas")
                    hits = [d for d in deltas if isinstance(d, dict) and d.get("op") == "ADD_RULE"
                            and d.get("target_kind") == "rule" and d.get("target_id") == rid
                            and d.get("revision") == row.get("revision")
                            and not isinstance(d.get("revision"), bool)]
                    if len(hits) != 1:
                        fail("change_delta")
                    d_payload = hits[0].get("payload")
                    if not isinstance(d_payload, dict) or d_payload.get("body") != rec:
                        fail("change_body")
                    stored = rec["report"]
                    for src, name in ((row, "history"), (change, "change")):
                        ev = src.get("evidence")
                        if not isinstance(ev, dict) or ev.get("report") != stored:
                            fail(name + "_evidence")
                        if src.get("validation") != stored:
                            fail(name + "_validation")
                except MemoryReplayError:
                    raise
                except (ValueError, KeyError, TypeError, AttributeError, LookupError) as e:
                    fail(str(e) or type(e).__name__)
                if "induction_policy" not in stored:
                    return False
                marker = stored["induction_policy"]
                if isinstance(marker, str) and marker == "selected-reference-word-slots-v1":
                    return True
                if isinstance(marker, str) and marker == "selected-reference-choice-graph-v1":
                    return "graph"
                if isinstance(marker, str) and marker == "selected-reference-query-slots-v1":
                    return "query"
                fail("induction_policy")

            flag = _verified_policy(rule["id"], record, rule)
            kind = "graph" if flag == "graph" else ("query" if flag == "query" else "fact")
            if (kind == "graph") != ("pattern_graph" in record):
                raise MemoryReplayError("corrupt_record:%s" % rule["id"])
            if kind == "graph":
                report, graph = self._evaluate_graph(parser, record["payload"],
                                                     entry_origin=origin_map.get(rule["id"]))
                if report.get("accepted") is True and (
                        dumps(graph) != dumps(record.get("pattern_graph"))
                        or dumps(report.get("inferred_annotations")) != dumps(record.get("annotation"))):
                    raise MemoryReplayError("replay_graph_mismatch:%s" % rule["id"])
                report["inferred_annotation"] = report.get("inferred_annotations")
            elif kind == "query":
                report = self._evaluate(parser, record["payload"], entry_origin=origin_map.get(rule["id"]),
                                        inherit_declared_slots=True, expression_kind=kind)
            else:
                report = self._evaluate(parser, record["payload"], entry_origin=origin_map.get(rule["id"]),
                                        inherit_declared_slots=flag)
            if not report["accepted"] or report["inferred_annotation"] != record.get("annotation"):
                raise MemoryReplayError("replay_rejected:%s:%s" % (rule["id"], report["reason"]))
            records.append((rule["id"], record, kind))
        # A later expression may match an earlier negative holdout without
        # changing the earlier training example. Check the final combined view.
        base = self._fresh()
        for rule_id, record, kind in records:
            payload = record["payload"]
            pairs = payload["demonstrations"] if kind == "graph" else [payload]
            for pair in pairs:
                if kind == "query":
                    expected = self._reference(base, pair["equivalent"], expression_kind=kind)
                else:
                    expected = self._reference(base, pair["equivalent"])
                if expressions.semantics(parser, pair["text"]) != expected:
                    raise MemoryReplayError("training_meaning_changed:%s" % rule_id)
            if kind == "query":
                cases = self._expected(base, payload["validation"], expression_kind=kind)
            else:
                cases = self._expected(base, payload["validation"])
            for case in cases:
                if expressions.semantics(parser, case["text"]) != case["expected"]:
                    raise MemoryReplayError("prior_validation_changed:%s" % rule_id)
        if public:
            parser._learning_origin_provenance = copy.deepcopy(diagnostic)
        return parser

    def _active_rule(self, candidate_id):
        cand = self._store.candidate(candidate_id)
        rule_id = cand and cand["evidence"].get("rule_id")
        for rule in self._store.added_rules():
            if rule["id"] == rule_id and cand["evidence"].get("kind") == "expression":
                return rule
        raise ValueError("not_an_active_learned_expression")

    def installed_expression_origins(self):
        """Read-only inventory of active accepted expression rules; never actual use."""
        def bad(rule_id, why):
            return MemoryReplayError("installed_origin:%s:%s" % (rule_id, why))

        text = _nonempty

        def add_rule_delta(record, rid, why):
            deltas = record.get("deltas")
            if not isinstance(deltas, list):
                raise bad(rid, why)
            found = [d for d in deltas if isinstance(d, dict) and d.get("op") == "ADD_RULE"
                     and d.get("target_id") == rid]
            if len(found) != 1:
                raise bad(rid, why)
            payload = found[0].get("payload")
            if not isinstance(payload, dict) or not isinstance(payload.get("body"), dict):
                raise bad(rid, why)
            return found[0], payload["body"]

        rows = []
        for rule in self._store.added_rules():
            rid = rule.get("id") if isinstance(rule, dict) else None
            if not text(rid):
                raise bad(rid, "rule_id")
            body, origin = rule.get("body"), rule.get("origin")
            if not isinstance(body, dict):
                raise bad(rid, "record")
            if self._lexical_kind_check(body, rid):
                continue
            if body.get("kind") != "expression":
                raise bad(rid, "record")
            revision = rule.get("revision")
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                raise bad(rid, "rule_revision")
            if not isinstance(origin, dict) or not text(origin.get("change_id")) \
                    or isinstance(origin.get("seq"), bool) or not isinstance(origin.get("seq"), int):
                raise bad(rid, "origin")
            report = body.get("report")
            if body.get("schema") != SCHEMA or body.get("supervision") != SUPERVISION \
                    or not isinstance(report, dict) or report.get("accepted") is not True:
                raise bad(rid, "record")
            prov = body.get("provenance")
            if not isinstance(prov, dict) or not text(prov.get("conversation_id")) \
                    or not text(prov.get("turn_id")):
                raise bad(rid, "teaching")
            change = self._store.change(origin["change_id"])
            evidence = change.get("evidence") if isinstance(change, dict) else None
            if not isinstance(evidence, dict) or change.get("change_id") != origin["change_id"] \
                    or change.get("seq") != origin["seq"] or evidence.get("kind") != "expression" \
                    or evidence.get("rule_id") != rid or not text(evidence.get("candidate_id")) \
                    or evidence.get("operation") not in ("teach", "replace"):
                raise bad(rid, "change")
            cid = evidence["candidate_id"]
            approval = change.get("approval")
            if not isinstance(approval, dict) or approval.get("candidate_id") != cid:
                raise bad(rid, "approval")
            _, change_body = add_rule_delta(change, rid, "change_delta")
            if change_body != body:
                raise bad(rid, "change_body")
            cand = self._store.candidate(cid)
            if not isinstance(cand, dict) or cand.get("candidate_id") != cid \
                    or cand.get("status") != "approved" or cand.get("change_seq") != origin["seq"] \
                    or not isinstance(cand.get("evidence"), dict) \
                    or cand["evidence"].get("rule_id") != rid \
                    or cand["evidence"].get("kind") != "expression" \
                    or cand["evidence"].get("candidate_id") != cid:
                raise bad(rid, "candidate")
            _, cand_body = add_rule_delta(cand, rid, "candidate_delta")
            if cand_body != body:
                raise bad(rid, "candidate_body")
            rows.append((origin["seq"], rid, {
                "scope": "installed_expression_origin", "candidate_id": cid, "rule_id": rid,
                "rule_revision": revision, "accepted_change_id": origin["change_id"],
                "teaching": {"conversation_id": prov["conversation_id"], "turn_id": prov["turn_id"]},
                "graph_binding": self._graph_binding}))
        rows.sort(key=lambda r: (r[0], r[1]))
        return [r[2] for r in rows]

    def _view(self, cand):
        body = next(d["payload"]["body"] for d in cand["deltas"] if "body" in d.get("payload", {}))
        record = copy.deepcopy(body)
        evidence, kind = cand["evidence"], record["kind"]
        if kind == LEX_KIND:
            return self._unavailable_action_view(cand, record)
        if kind not in ("expression", "observation"):
            raise MemoryReplayError("unknown_record_kind:%s" % cand["candidate_id"])
        if kind == "observation":
            status = "observed"
        elif cand["status"] == "pending":
            status = "pending"
        elif cand["status"] == "rejected":
            status = "rejected"
        elif any(r["id"] == evidence["rule_id"] for r in self._store.added_rules()):
            status = "active"
        else:
            last = self._store.history(evidence["rule_id"])[-1]["evidence"] or {}
            status = "superseded" if last.get("operation") == "replace" else "retracted"
        record.update(candidate_id=cand["candidate_id"], status=status,
                      accepted=cand["status"] == "approved",
                      gate_accepted=bool(record["report"] and record["report"].get("accepted")),
                      decision_reason=cand.get("decision_reason"),
                      reason=cand.get("decision_reason") or record["report"].get("reason"),
                      revision=self._store.head()[0])
        record["history"] = self._store.history(evidence["rule_id"])
        return record
