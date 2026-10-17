"""Caller-local reading of normalized source observations through an explicit selected model."""

import copy
import hashlib
import json

from pack_model import PackModel

_COORD = "normalized_observation_text"


def _dumps(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, ensure_ascii=False)


def _size(value):
    return len(_dumps(value).encode("utf-8"))


def _sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _get(obj, name, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _gap(kind, reason):
    return {"kind": kind, "reason": str(reason)[:120]}


class SourceReader:
    def __init__(self, model, caller_scope, *, snapshot=None, session=None,
                 max_capture_bytes=65536):
        if not isinstance(model, PackModel):
            raise TypeError("an explicit PackModel is required")
        if (isinstance(caller_scope, bool) or not isinstance(caller_scope, (str, dict))
                or not caller_scope):
            raise ValueError("caller_scope must be a nonempty str or dict")
        if (isinstance(max_capture_bytes, bool) or not isinstance(max_capture_bytes, int)
                or not 1 <= max_capture_bytes <= 65536):
            raise ValueError("max_capture_bytes must be an int in 1..65536")
        self._scope = json.loads(_dumps(caller_scope))
        if not self._scope:
            raise ValueError("caller_scope must be nonempty")
        self._model = model
        if snapshot is not None or session is not None:
            if snapshot is None or session is None:
                raise ValueError("snapshot and session must be supplied together")
            if type(model) is not PackModel:
                raise TypeError("an actual PackModel is required for frozen binding")
        fp = model.content_fingerprint
        self._fingerprint = fp() if callable(fp) else fp
        self._max = max_capture_bytes
        self._records = []
        self._unbindable = set()
        # Separate monotone actual-invocation counter (never storage position).
        self._calls = 0
        # Bounded aggregate loss bookkeeping (counts only; no per-overflow growth).
        self._lost = 0
        self._lost_first = None
        self._lost_last = None
        # Global TOTAL budget for caller-local capture storage, reserving room
        # for one fixed aggregate loss marker so `records` stays <= 65536 bytes.
        self._total_max = min(self._max, 65536)
        self._reserve = 512
        self._snapshot = None
        self._session = None
        self._binding = None
        if snapshot is None and session is None:
            return
        from marco.runtime.learning_dialogue import DialogueSession
        from marco.runtime.source_snapshot import SourceParserSnapshot, SourceSnapshotError
        if type(snapshot) is not SourceParserSnapshot:
            raise TypeError("an actual SourceParserSnapshot is required")
        if type(session) is not DialogueSession:
            raise TypeError("an actual DialogueSession is required")
        try:
            if (snapshot._token_ok is not True or snapshot._session is not session
                    or snapshot._model is not model or session.model is not model):
                raise ValueError("snapshot ownership mismatch")
            memory = session.memory
            if snapshot._memory is not memory or snapshot._store is not memory._store:
                raise ValueError("snapshot ownership mismatch")
            conv = session.conversation_id
            if snapshot._conversation_id != conv:
                raise ValueError("snapshot ownership mismatch")
            raw = _dumps(snapshot.binding)
            if len(raw.encode("utf-8")) > 65536:
                raise ValueError("snapshot binding invalid")
            binding = json.loads(raw)
            sm, im = binding["selected_model"], binding["installed_memory"]
            ap, org = binding["active_parser"], binding["origins"]
            head = im["head"]
            seq, cid = head["seq"], head["change_id"]
            hexchars = frozenset("0123456789abcdef")

            def _hex64(v):
                return isinstance(v, str) and len(v) == 64 and set(v) <= hexchars

            def _nonempty(v):
                return isinstance(v, str) and bool(v.strip())
            if (binding["schema"] != "marco-source-parser-snapshot-v1"
                    or binding["state_scope"] != "frozen_attempt_state"
                    or binding["conversation_id"] != conv
                    or sm["content_fingerprint"] != self._fingerprint
                    or not _hex64(sm["content_fingerprint"])
                    or not _hex64(sm["declaration_sha256"])
                    or not _hex64(sm["sources_sha256"])
                    or not _hex64(sm["base_parser_sha256"])
                    or not _nonempty(sm["effective_key"])
                    or not _hex64(ap["data_language_sha256"])
                    or not _hex64(im["base_store_sha256"])
                    or not _nonempty(im["base_build_id"])
                    or im["scope"] != "installed_attempt_state_not_usage"
                    or isinstance(seq, bool) or not isinstance(seq, int) or seq < 0
                    or (cid is not None if seq == 0
                        else (not isinstance(cid, str) or not cid.strip()))
                    or org["scope"] != "installed_expression_origin_transport_only"
                    or org["status"] not in ("partial", "unknown")):
                raise ValueError("snapshot binding invalid")
        except SourceSnapshotError:
            raise
        except Exception:
            raise ValueError("snapshot configuration refused") from None
        self._snapshot, self._session, self._binding = snapshot, session, binding

    def _assumption(self):
        return {"kind": "caller_declared_interpretation",
                "value": copy.deepcopy(self._scope), "sourced_time": False}

    def _store(self, ordinal, text, build):
        """Store a bounded record; build() returns the full record (may raise)."""
        try:
            digest = _sha(text)
        except Exception:
            digest = None
        reason = None
        if self._lost:
            # Once detailed capture has been lost, storage position no longer
            # equals the call index; keep only the bounded aggregate marker.
            self._mark_lost(ordinal, "storage stopped")
            return
        budget = self._total_max - self._reserve
        try:
            rec = copy.deepcopy(build())
            if _size(rec) <= self._max and _size(self._records + [rec]) <= budget:
                self._records.append(rec)
                return
            reason = "record exceeds max_capture_bytes"
        except Exception as exc:  # optional metadata only
            reason = "capture failed: %s" % type(exc).__name__
        base = {
            "ordinal": ordinal,
            "text_sha256": digest,
            "model_content_fingerprint": self._fingerprint,
            "status": "capture_gap",
            "gaps": [_gap("capture_gap", reason)],
        }
        for rec in (dict(base, text=text), base):
            try:
                if _size(rec) <= self._max and _size(self._records + [rec]) <= budget:
                    self._records.append(rec)
                    return
            except Exception:
                pass
        self._mark_lost(ordinal, reason or "metadata limit")

    def _mark_lost(self, ordinal, reason):
        """Record a lost detailed capture with bounded aggregate counters only."""
        self._unbindable.add(0)  # fixed-size sentinel: any loss blocks binding
        self._lost += 1
        if self._lost_first is None:
            self._lost_first = ordinal
        self._lost_last = ordinal
        self._lost_reason = str(reason)[:120]

    def _loss_marker(self):
        return {
            "status": "capture_gap",
            "ordinal_first": self._lost_first,
            "ordinal_last": self._lost_last,
            "lost_count": self._lost,
            "gaps": [_gap("capture_gap_summary", getattr(self, "_lost_reason", "metadata limit"))],
        }

    def __call__(self, text):
        ordinal = self._calls
        self._calls += 1
        diag = []
        parser = None
        try:
            if self._snapshot is not None:
                parser = self._snapshot.fresh_parser(self._session)
            else:
                parser = self._model.parser()
            parsed = parser.parse(
                text, partial=True, events=False, repair=False,
                _entry_selection=True, _diagnostics=diag)
        except BaseException as exc:
            if parser is None and self._snapshot is not None:
                from marco.runtime.source_snapshot import SourceSnapshotError
                if isinstance(exc, SourceSnapshotError):
                    code = str(getattr(exc, "code", ""))[:120]
                    self._store(ordinal, text, lambda: {
                        "ordinal": ordinal,
                        "text": text,
                        "text_sha256": _sha(text),
                        "model_content_fingerprint": self._fingerprint,
                        "status": "snapshot_refused",
                        "snapshot_refusal_code": code,
                        "gaps": [_gap("snapshot_refused", code)],
                    })
                    raise
            name = type(exc).__name__
            self._store(ordinal, text, lambda: (_ for _ in ()).throw(
                RuntimeError("native parse error " + name)))
            raise
        inserted = []
        result = parsed
        if isinstance(parsed, dict):
            result = dict(parsed)
            facts = parsed.get("facts")
            if isinstance(facts, list):
                new_facts = []
                for i, fact in enumerate(facts):
                    if isinstance(fact, dict) and fact.get("scope") is None:
                        fact = dict(fact)
                        fact["scope"] = copy.deepcopy(self._scope)
                        inserted.append(i)
                    new_facts.append(fact)
                result["facts"] = new_facts

        def build():
            sel = result.get("entry_selection") if isinstance(result, dict) else None
            rec = {
                "ordinal": ordinal,
                "text": text,
                "text_sha256": _sha(text),
                "model_content_fingerprint": self._fingerprint,
                "scope_assumption": self._assumption(),
                "scope_inserted_fact_indices": list(inserted),
                "reading": result,
                "diagnostics": list(diag),
                "entry_selection": sel,
                "status": "read" if result is not None else "unreadable",
                "gaps": [],
            }
            if self._snapshot is not None:
                rec["frozen_parser_binding"] = copy.deepcopy(self._binding)
            return rec
        # serialization check is inside _store via _size
        self._store(ordinal, text, build)
        return result

    @property
    def records(self):
        try:
            out = copy.deepcopy(self._records)
            if self._lost:
                out.append(self._loss_marker())
            if _size(out) > 65536:
                raise ValueError("records exceed global limit")
            return out
        except Exception:
            return [{"status": "capture_gap",
                     "gaps": [_gap("capture_gap_summary", "metadata detach failed")]}]

    def _refused(self, reason):
        env = {"status": "refused", "provenance_status": "partial",
               "coordinate_space": _COORD,
               "model_content_fingerprint": self._fingerprint,
               "records": [], "gaps": [_gap("binding_refused", reason)]}
        try:
            if _size(env) <= self._max:
                return env
        except Exception:
            pass
        # Exemption: a caller detail limit smaller than the physically minimal
        # refusal envelope may be exceeded ONLY by this fixed, finite fallback
        # (a few hundred bytes, always << 65536); never by detail/model payload.
        return {"status": "refused", "provenance_status": "partial",
                "coordinate_space": _COORD, "model_content_fingerprint": None,
                "records": [], "gaps": [{"kind": "binding_refused"}]}

    def bind(self, report):
        try:
            obs = list(_get(report, "observations") or [])
            n = self._calls
            if self._unbindable or self._lost or len(self._records) != n:
                return self._refused("capture summarized; provenance unavailable")
            seen_ids = set()
            tail = False
            if len(obs) != n:
                claims = _get(report, "claims")
                limit = _get(report, "claim_limit")
                if not (len(obs) > n and _get(report, "claims_truncated") is True
                        and isinstance(limit, int) and not isinstance(limit, bool)
                        and limit > 0 and claims is not None and len(claims) >= limit):
                    return self._refused("observation count mismatch")
                tail = True
            out = []
            for i, o in enumerate(obs):
                text = _get(o, "text")
                if not isinstance(text, str):
                    return self._refused("observation text invalid")
                digest = _sha(text)
                if _get(o, "text_sha256", digest) != digest:
                    return self._refused("observation hash mismatch")
                if _get(o, "ordinal", i) != i:
                    return self._refused("observation ordinal mismatch")
                oid = _get(o, "id")
                sid = _get(o, "source_id")
                if (not isinstance(oid, str) or not oid or isinstance(oid, bool)
                        or not isinstance(sid, str) or not sid):
                    return self._refused("observation identity missing")
                if oid in seen_ids:
                    return self._refused("duplicate observation id")
                seen_ids.add(oid)
                if i < n:
                    rec = copy.deepcopy(self._records[i])
                    if rec.get("ordinal") != i:
                        return self._refused("record ordinal mismatch")
                    if rec.get("text", text) != text or rec.get("text_sha256") != digest:
                        return self._refused("observation text mismatch")
                    rec["observation_id"] = oid
                    rec["source_id"] = sid
                else:
                    rec = {"ordinal": i, "text": text, "text_sha256": digest,
                           "model_content_fingerprint": self._fingerprint,
                           "observation_id": oid, "source_id": sid,
                           "status": "not_read_due_limit",
                           "gaps": [_gap("not_read_due_limit", "claim limit reached")]}
                out.append(rec)
            gaps = [g for r in out for g in r.get("gaps", [])]
            env = {"status": "bound", "provenance_status": "partial",
                   "coordinate_space": _COORD,
                   "model_content_fingerprint": self._fingerprint,
                   "records": out, "gaps": gaps}
            if _size(env) > self._max:
                env = self._refused("metadata limit exceeded")
                env["gaps"][0]["kind"] = "metadata_limit"
            return env
        except Exception as exc:
            return self._refused("bind failed: %s" % type(exc).__name__)
